package main

import (
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"log/slog"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promhttp"
)

// Config comes from environment variables; see README.md.
type Config struct {
	Addr           string
	SpoolDir       string // shared with the worker
	MaxUploadMB    int64
	MaxUnpackedMB  int64
	UploadsPerHour int64
	TrustProxy     bool
}

type Server struct {
	config  Config
	queue   Queue
	metrics *metrics
}

type metrics struct {
	registry *prometheus.Registry
	uploads  *prometheus.CounterVec
	bytes    prometheus.Histogram
	seconds  prometheus.Histogram
}

func newMetrics(depth func() float64) *metrics {
	m := &metrics{
		registry: prometheus.NewRegistry(),
		uploads: prometheus.NewCounterVec(prometheus.CounterOpts{
			Name: "pcdoctor_upload_requests_total",
			Help: "Uploads received, by outcome (accepted, rejected, too_large, rate_limited, error).",
		}, []string{"outcome"}),
		bytes: prometheus.NewHistogram(prometheus.HistogramOpts{
			Name:    "pcdoctor_upload_bytes",
			Help:    "Size of accepted uploads.",
			Buckets: prometheus.ExponentialBuckets(16*1024, 4, 8),
		}),
		seconds: prometheus.NewHistogram(prometheus.HistogramOpts{
			Name:    "pcdoctor_upload_seconds",
			Help:    "Time to read, check, store and queue one upload.",
			Buckets: prometheus.DefBuckets,
		}),
	}
	m.registry.MustRegister(m.uploads, m.bytes, m.seconds,
		prometheus.NewGaugeFunc(prometheus.GaugeOpts{
			Name: "pcdoctor_queue_depth",
			Help: "Jobs waiting for a worker.",
		}, depth))
	return m
}

func NewServer(config Config, queue Queue) *Server {
	s := &Server{config: config, queue: queue}
	s.metrics = newMetrics(func() float64 {
		ctx, cancel := context.WithTimeout(context.Background(), time.Second)
		defer cancel()
		depth, err := queue.Depth(ctx)
		if err != nil {
			return -1
		}
		return float64(depth)
	})
	return s
}

func (s *Server) Handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("POST /upload", s.upload)
	mux.HandleFunc("GET /jobs/{id}", s.job)
	mux.HandleFunc("GET /healthz", s.health)
	mux.Handle("GET /metrics", promhttp.HandlerFor(s.metrics.registry, promhttp.HandlerOpts{}))
	return mux
}

func writeJSON(w http.ResponseWriter, status int, body any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	json.NewEncoder(w).Encode(body)
}

func fail(w http.ResponseWriter, status int, message string) {
	writeJSON(w, status, map[string]string{"detail": message})
}

func randomToken(bytes int) string {
	raw := make([]byte, bytes)
	if _, err := rand.Read(raw); err != nil {
		panic(err) // no randomness: nothing safe can be done
	}
	return base64.RawURLEncoding.EncodeToString(raw)
}

func (s *Server) clientKey(r *http.Request) string {
	if s.config.TrustProxy {
		if forwarded := r.Header.Get("X-Forwarded-For"); forwarded != "" {
			parts := strings.Split(forwarded, ",")
			return strings.TrimSpace(parts[len(parts)-1]) // the entry our own proxy added
		}
	}
	host, _, err := net.SplitHostPort(r.RemoteAddr)
	if err != nil {
		return r.RemoteAddr
	}
	return host
}

func (s *Server) health(w http.ResponseWriter, r *http.Request) {
	if err := s.queue.Ping(r.Context()); err != nil {
		fail(w, http.StatusServiceUnavailable, "The queue cannot be reached.")
		return
	}
	writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
}

func (s *Server) job(w http.ResponseWriter, r *http.Request) {
	state, err := s.queue.State(r.Context(), r.PathValue("id"))
	if errors.Is(err, errNoJob) {
		fail(w, http.StatusNotFound, "No such upload (results are kept for a day).")
		return
	}
	if err != nil {
		fail(w, http.StatusServiceUnavailable, "The queue cannot be reached.")
		return
	}
	writeJSON(w, http.StatusOK, state)
}

func (s *Server) upload(w http.ResponseWriter, r *http.Request) {
	started := time.Now()
	outcome := "error"
	defer func() {
		s.metrics.uploads.WithLabelValues(outcome).Inc()
		s.metrics.seconds.Observe(time.Since(started).Seconds())
	}()

	allowed, err := s.queue.Allow(r.Context(), "pcdoctor:uploads:"+s.clientKey(r), s.config.UploadsPerHour, time.Hour)
	if err != nil {
		fail(w, http.StatusServiceUnavailable, "The queue cannot be reached. Try again shortly.")
		return
	}
	if !allowed {
		outcome = "rate_limited"
		fail(w, http.StatusTooManyRequests, "Too many uploads from here. Try again in an hour.")
		return
	}

	limit := s.config.MaxUploadMB * 1024 * 1024
	// The whole request may be a little larger than the file (form overhead).
	r.Body = http.MaxBytesReader(w, r.Body, limit+1024*1024)
	file, _, err := r.FormFile("file")
	if err != nil {
		var tooLarge *http.MaxBytesError
		if errors.As(err, &tooLarge) {
			outcome = "too_large"
			fail(w, http.StatusRequestEntityTooLarge, "The file is larger than the upload limit.")
			return
		}
		outcome = "rejected"
		fail(w, http.StatusBadRequest, `Send the run as a form file named "file".`)
		return
	}
	defer file.Close()
	data, err := io.ReadAll(io.LimitReader(file, limit+1))
	if err != nil || int64(len(data)) > limit {
		outcome = "too_large"
		fail(w, http.StatusRequestEntityTooLarge, "The file is larger than the upload limit.")
		return
	}

	clean, _, err := CleanRun(data, s.config.MaxUnpackedMB*1024*1024)
	var uploadError *UploadError
	if errors.As(err, &uploadError) {
		outcome = "rejected"
		fail(w, http.StatusBadRequest, uploadError.Message)
		return
	}
	if err != nil {
		slog.Error("clean run", "error", err)
		fail(w, http.StatusInternalServerError, "The upload could not be processed.")
		return
	}

	// The name is ours, never the uploader's.
	id := randomToken(16)
	name := id + ".zip"
	if err := writeAtomically(filepath.Join(s.config.SpoolDir, name), clean); err != nil {
		slog.Error("store upload", "error", err)
		fail(w, http.StatusInternalServerError, "The upload could not be stored.")
		return
	}
	shareKey := randomToken(32)
	shareHash := sha256.Sum256([]byte(shareKey))
	fileHash := sha256.Sum256(clean)
	label := strings.TrimSpace(r.FormValue("label"))
	if len(label) > 200 {
		label = label[:200]
	}
	job := Job{
		ID:        id,
		File:      name,
		Label:     label,
		ShareHash: hex.EncodeToString(shareHash[:]),
		SHA256:    hex.EncodeToString(fileHash[:]),
		QueuedAt:  time.Now().UTC().Format(time.RFC3339Nano),
	}
	if err := s.queue.Enqueue(r.Context(), job); err != nil {
		os.Remove(filepath.Join(s.config.SpoolDir, name)) // no job, so no orphan file
		fail(w, http.StatusServiceUnavailable, "The queue cannot be reached. Try again shortly.")
		return
	}
	outcome = "accepted"
	s.metrics.bytes.Observe(float64(len(clean)))
	// The private key is returned once and only its hash is kept, as in the API.
	writeJSON(w, http.StatusAccepted, map[string]string{
		"job_id":     id,
		"status_url": "/jobs/" + id,
		"share_key":  shareKey,
	})
}

// writeAtomically never leaves a half-written file where the worker can see it.
func writeAtomically(path string, data []byte) error {
	temp, err := os.CreateTemp(filepath.Dir(path), ".incoming-*")
	if err != nil {
		return err
	}
	defer os.Remove(temp.Name())
	if _, err := temp.Write(data); err != nil {
		temp.Close()
		return err
	}
	if err := temp.Close(); err != nil {
		return err
	}
	return os.Rename(temp.Name(), path)
}
