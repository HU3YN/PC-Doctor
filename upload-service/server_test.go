package main

import (
	"bytes"
	"context"
	"encoding/json"
	"mime/multipart"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/alicebob/miniredis/v2"
	"github.com/redis/go-redis/v9"
)

func testServer(t *testing.T, change func(*Config)) (*Server, *redis.Client, string) {
	t.Helper()
	mini := miniredis.RunT(t)
	client := redis.NewClient(&redis.Options{Addr: mini.Addr()})
	config := Config{SpoolDir: t.TempDir(), MaxUploadMB: 1, MaxUnpackedMB: 2, UploadsPerHour: 3}
	if change != nil {
		change(&config)
	}
	return NewServer(config, &redisQueue{client: client}), client, config.SpoolDir
}

func post(t *testing.T, s *Server, field string, data []byte, label string) *httptest.ResponseRecorder {
	t.Helper()
	var body bytes.Buffer
	form := multipart.NewWriter(&body)
	part, _ := form.CreateFormFile(field, "../../evil name.zip")
	part.Write(data)
	form.WriteField("label", label)
	form.Close()
	request := httptest.NewRequest(http.MethodPost, "/upload", &body)
	request.Header.Set("Content-Type", form.FormDataContentType())
	recorder := httptest.NewRecorder()
	s.Handler().ServeHTTP(recorder, request)
	return recorder
}

func TestUploadIsStoredAndQueued(t *testing.T) {
	s, client, spool := testServer(t, nil)
	run := makeZip(t, map[string]string{"run/manifest.json": "{}", "run/extra.exe": "MZ"})
	response := post(t, s, "file", run, "  bench 3  ")
	if response.Code != http.StatusAccepted {
		t.Fatalf("status %d: %s", response.Code, response.Body)
	}
	var reply map[string]string
	json.Unmarshal(response.Body.Bytes(), &reply)

	raw, err := client.LPop(context.Background(), jobsKey).Bytes()
	if err != nil {
		t.Fatal("no job on the queue: ", err)
	}
	var job Job
	json.Unmarshal(raw, &job)
	if job.ID != reply["job_id"] || job.Label != "bench 3" || job.File != job.ID+".zip" {
		t.Fatalf("job %+v", job)
	}
	if strings.Contains(string(raw), reply["share_key"]) || len(job.ShareHash) != 64 {
		t.Fatal("the queue must hold the key's hash, never the key")
	}
	stored, err := os.ReadFile(filepath.Join(spool, job.File))
	if err != nil {
		t.Fatal(err)
	}
	if got := names(t, stored); len(got) != 1 || got["manifest.json"] != "{}" {
		t.Fatalf("stored %v", got)
	}

	status := httptest.NewRecorder()
	s.Handler().ServeHTTP(status, httptest.NewRequest(http.MethodGet, reply["status_url"], nil))
	if status.Code != 200 || !strings.Contains(status.Body.String(), `"queued"`) {
		t.Fatalf("status %d %s", status.Code, status.Body)
	}
	missing := httptest.NewRecorder()
	s.Handler().ServeHTTP(missing, httptest.NewRequest(http.MethodGet, "/jobs/nope", nil))
	if missing.Code != 404 {
		t.Fatalf("unknown job answered %d", missing.Code)
	}
}

func TestBadUploadsAreRefusedAndLeaveNothingBehind(t *testing.T) {
	s, client, spool := testServer(t, func(c *Config) { c.UploadsPerHour = 100 })
	checks := []struct {
		name  string
		field string
		data  []byte
		want  int
	}{
		{"not a run", "file", []byte("hello"), 400},
		{"wrong field", "upload", makeZip(t, map[string]string{"manifest.json": "{}"}), 400},
		{"over the upload limit", "file", bytes.Repeat([]byte("PK\x03\x04"), 300_000), 413},
		{"unpacks too large", "file", makeZip(t, map[string]string{"sensors.csv": strings.Repeat("0", 3*mb)}), 400},
	}
	for _, check := range checks {
		if got := post(t, s, check.field, check.data, "").Code; got != check.want {
			t.Errorf("%s: status %d, want %d", check.name, got, check.want)
		}
	}
	if left, _ := os.ReadDir(spool); len(left) != 0 {
		t.Errorf("%d file(s) left in the spool folder", len(left))
	}
	if depth, _ := client.LLen(context.Background(), jobsKey).Result(); depth != 0 {
		t.Errorf("%d job(s) queued for refused uploads", depth)
	}
}

func TestRateLimitPerAddress(t *testing.T) {
	s, _, _ := testServer(t, nil)
	run := makeZip(t, map[string]string{"manifest.json": "{}"})
	for i := 0; i < 3; i++ {
		if code := post(t, s, "file", run, "").Code; code != http.StatusAccepted {
			t.Fatalf("upload %d answered %d", i+1, code)
		}
	}
	if code := post(t, s, "file", run, "").Code; code != http.StatusTooManyRequests {
		t.Fatalf("the fourth upload answered %d", code)
	}
}

func TestHealthAndMetrics(t *testing.T) {
	s, client, _ := testServer(t, nil)
	post(t, s, "file", makeZip(t, map[string]string{"manifest.json": "{}"}), "")
	metrics := httptest.NewRecorder()
	s.Handler().ServeHTTP(metrics, httptest.NewRequest(http.MethodGet, "/metrics", nil))
	for _, want := range []string{`pcdoctor_upload_requests_total{outcome="accepted"} 1`, "pcdoctor_queue_depth 1"} {
		if !strings.Contains(metrics.Body.String(), want) {
			t.Errorf("metrics lack %q", want)
		}
	}
	client.Close() // Redis gone: say so instead of pretending
	health := httptest.NewRecorder()
	s.Handler().ServeHTTP(health, httptest.NewRequest(http.MethodGet, "/healthz", nil))
	if health.Code != http.StatusServiceUnavailable {
		t.Fatalf("health answered %d with Redis gone", health.Code)
	}
}
