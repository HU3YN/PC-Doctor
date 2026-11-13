// The PC Doctor upload service: takes a run, checks it, stores it in the
// shared spool folder and puts an analysis job on a Redis queue. The Python
// worker (python -m pcdoctor_api.worker) does the analysis.
package main

import (
	"context"
	"errors"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"strconv"
	"syscall"
	"time"

	"github.com/redis/go-redis/v9"
)

func env(name, fallback string) string {
	if value := os.Getenv(name); value != "" {
		return value
	}
	return fallback
}

func envInt(name string, fallback int64) int64 {
	value, err := strconv.ParseInt(os.Getenv(name), 10, 64)
	if err != nil || value <= 0 {
		return fallback
	}
	return value
}

func main() {
	config := Config{
		Addr:           env("PCDOCTOR_UPLOAD_ADDR", ":8090"),
		SpoolDir:       env("PCDOCTOR_SPOOL_DIR", "data/spool"),
		MaxUploadMB:    envInt("PCDOCTOR_MAX_UPLOAD_MB", 200),
		MaxUnpackedMB:  envInt("PCDOCTOR_MAX_UNPACKED_MB", 1024),
		UploadsPerHour: envInt("PCDOCTOR_UPLOADS_PER_HOUR", 30),
		TrustProxy:     os.Getenv("PCDOCTOR_TRUST_PROXY") == "true",
	}
	if err := os.MkdirAll(config.SpoolDir, 0o750); err != nil {
		slog.Error("spool folder", "error", err)
		os.Exit(1)
	}
	options, err := redis.ParseURL(env("PCDOCTOR_REDIS_URL", "redis://localhost:6379/0"))
	if err != nil {
		slog.Error("PCDOCTOR_REDIS_URL", "error", err)
		os.Exit(1)
	}
	server := &http.Server{
		Addr:              config.Addr,
		Handler:           NewServer(config, &redisQueue{client: redis.NewClient(options)}).Handler(),
		ReadHeaderTimeout: 10 * time.Second,
		ReadTimeout:       5 * time.Minute, // a large run over a slow link
		WriteTimeout:      30 * time.Second,
	}
	go func() {
		slog.Info("upload service listening", "addr", config.Addr)
		if err := server.ListenAndServe(); !errors.Is(err, http.ErrServerClosed) {
			slog.Error("server", "error", err)
			os.Exit(1)
		}
	}()
	stop := make(chan os.Signal, 1)
	signal.Notify(stop, syscall.SIGINT, syscall.SIGTERM)
	<-stop
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()
	server.Shutdown(ctx) // let uploads in flight finish
}
