# upload-service (Phase 3)

A small Go service that takes uploads so the API does not have to do the slow
part while the uploader waits:

```
POST /upload  ->  check the file  ->  store it in the spool folder  ->  queue a job (Redis)
                                                                          |
                    python -m pcdoctor_api.worker  <----------------------+
                    (unpack, analyse, store the run)
```

It applies the same limits as `api/pcdoctor_api/services/ingest.py`: upload
size, unpacked size, known file names only, no more than 200 entries, no
password-protected zips. `archive.go` is that function in Go; the tests cover
the same cases.

| Endpoint | What it does |
|---|---|
| `POST /upload` (form file `file`, optional `label`) | `202` with `job_id`, `status_url` and the private `share_key`. Only the key's hash is queued. |
| `GET /jobs/{id}` | `queued`, `done` (with `run_id`) or `failed` (with the reason). Kept for a day. |
| `GET /healthz` | `200` when Redis answers. |
| `GET /metrics` | Prometheus metrics. Do not publish this path (the k3s ingress does not). |

Open the diagnosis at `/shared/<share_key>` on the dashboard once the job is `done`.

## Settings

| Variable | Default | |
|---|---|---|
| `PCDOCTOR_UPLOAD_ADDR` | `:8090` | where to listen |
| `PCDOCTOR_REDIS_URL` | `redis://localhost:6379/0` | queue and rate limits |
| `PCDOCTOR_SPOOL_DIR` | `data/spool` | shared with the worker (its `PCDOCTOR_SPOOL_DIR`) |
| `PCDOCTOR_MAX_UPLOAD_MB` / `PCDOCTOR_MAX_UNPACKED_MB` | `200` / `1024` | same meaning as in the API |
| `PCDOCTOR_UPLOADS_PER_HOUR` | `30` | per address |
| `PCDOCTOR_TRUST_PROXY` | off | `true` behind our own proxy that sets `X-Forwarded-For` |

## Run and test

```bash
go test ./...
```

```bash
go test -run xxx -fuzz=FuzzCleanRun -fuzztime=30s .
```

With the whole stack: `docker compose -f docker-compose.yml -f docker-compose.scale.yml up -d --build`
(see [`deploy/README.md`](../deploy/README.md)).

## Not done

The spool is a folder on a shared volume, which is right for one server. For
more than one server it needs to become object storage (S3): `writeAtomically`
in `server.go` and `process_job` in the worker are the two places to change.
