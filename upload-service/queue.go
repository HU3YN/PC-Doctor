package main

// The queue and the cache, both in Redis:
//
//   pcdoctor:jobs          a list; the Python worker takes jobs off the other end
//   pcdoctor:job:<id>      the state of one job, kept for a day
//   pcdoctor:uploads:<ip>  how many uploads an address made this hour

import (
	"context"
	"encoding/json"
	"errors"
	"time"

	"github.com/redis/go-redis/v9"
)

const (
	jobsKey   = "pcdoctor:jobs"
	jobPrefix = "pcdoctor:job:"
	jobTTL    = 24 * time.Hour
)

// Job is what the worker needs to analyse and store one upload.
type Job struct {
	ID        string `json:"id"`
	File      string `json:"file"`       // name inside the shared spool folder
	Label     string `json:"label"`      // typed by the uploader
	ShareHash string `json:"share_hash"` // SHA-256 of the private link key
	SHA256    string `json:"sha256"`     // of the stored file
	QueuedAt  string `json:"queued_at"`
}

// JobState is what the uploader can ask about a job. It never holds the key.
type JobState struct {
	Status string `json:"status"` // queued | done | failed
	RunID  string `json:"run_id,omitempty"`
	Error  string `json:"error,omitempty"`
}

var errNoJob = errors.New("no such job")

// Queue is everything the HTTP handlers need from Redis.
type Queue interface {
	Enqueue(ctx context.Context, job Job) error
	State(ctx context.Context, id string) (JobState, error)
	Allow(ctx context.Context, key string, limit int64, window time.Duration) (bool, error)
	Depth(ctx context.Context) (int64, error)
	Ping(ctx context.Context) error
}

type redisQueue struct{ client *redis.Client }

func (q *redisQueue) Enqueue(ctx context.Context, job Job) error {
	body, err := json.Marshal(job)
	if err != nil {
		return err
	}
	state, _ := json.Marshal(JobState{Status: "queued"})
	pipe := q.client.TxPipeline()
	pipe.Set(ctx, jobPrefix+job.ID, state, jobTTL)
	pipe.RPush(ctx, jobsKey, body)
	_, err = pipe.Exec(ctx)
	return err
}

func (q *redisQueue) State(ctx context.Context, id string) (JobState, error) {
	var state JobState
	body, err := q.client.Get(ctx, jobPrefix+id).Bytes()
	if errors.Is(err, redis.Nil) {
		return state, errNoJob
	}
	if err != nil {
		return state, err
	}
	return state, json.Unmarshal(body, &state)
}

// Allow counts one event against key and says whether it is within the limit.
func (q *redisQueue) Allow(ctx context.Context, key string, limit int64, window time.Duration) (bool, error) {
	// One MULTI/EXEC transaction: create the key with its expiry if it is
	// new, then count. Two separate calls (INCR, then EXPIRE) could leave a
	// key with no expiry - a permanent block - if the second never arrived.
	var count *redis.IntCmd
	_, err := q.client.TxPipelined(ctx, func(pipe redis.Pipeliner) error {
		pipe.SetNX(ctx, key, 0, window)
		count = pipe.Incr(ctx, key)
		return nil
	})
	if err != nil {
		return false, err
	}
	return count.Val() <= limit, nil
}

func (q *redisQueue) Depth(ctx context.Context) (int64, error) {
	return q.client.LLen(ctx, jobsKey).Result()
}

func (q *redisQueue) Ping(ctx context.Context) error { return q.client.Ping(ctx).Err() }
