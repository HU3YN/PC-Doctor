# upload-service (Phase 4 - not built yet)

A small Go service that takes uploads, stores the raw file in object storage,
and puts an analysis job on a queue. Today the FastAPI app does this in one
step (`api/pcdoctor_api/services/ingest.py`); that function is the behaviour
to reproduce, including its limits on size and file names.
