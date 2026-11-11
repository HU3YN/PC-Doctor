# pcdoctor-api

FastAPI backend. Takes uploaded runs, analyses them with `pcdoctor-analysis`,
stores runs and findings, and keeps the work log. If the dashboard has been
built (`web/dist`), it serves that too, so one process is the whole app.

```bash
pip install -e ../workers -e ".[dev]"

python -m pcdoctor_api            # http://127.0.0.1:8000  (API docs at /api/docs)
python -m pcdoctor_api --reload   # restart on code changes

pytest                            # tests, on SQLite
PCDOCTOR_TEST_DATABASE_URL=postgresql://user:pass@localhost/pcdoctor_test pytest   # on PostgreSQL
ruff check .
```

With no settings at all it uses a SQLite file in `./data`. Set
`PCDOCTOR_DATABASE_URL` to use PostgreSQL (Docker Compose does). Every
setting is in `pcdoctor_api/config.py` and `.env.example`.

## Database changes

Tables are defined in `pcdoctor_api/models.py`. After changing them:

```bash
alembic revision --autogenerate -m "what changed"   # writes a migration - read it before committing
alembic upgrade head                                 # the app also does this on start-up
alembic check                                        # fails if models and migrations disagree (CI runs this)
```

## Layout

| Path | What it does |
|---|---|
| `routers/runs.py` | Upload, list, read, re-analyse, download, delete runs |
| `routers/worklog.py` | Work log: create, search, similar cases, export, import |
| `routers/reference.py` | Stop codes, form options, statistics, demo data, health |
| `services/ingest.py` | Unpacks an upload safely, analyses it, stores it |
| `services/similarity.py` | Finds earlier work-log cases that look like this one, and says why |
| `services/privacy.py` | Warns when an entry looks like it holds customer data |
| `services/export.py` | Work log to JSON / CSV / Markdown |
| `migrations/` | Alembic migrations |
