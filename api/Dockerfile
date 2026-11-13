# Build from the repository root:  docker build -f api/Dockerfile .
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PCDOCTOR_DATA_DIR=/data

# Tesseract reads the text off photos of error screens.
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY workers/pyproject.toml workers/README.md workers/
COPY workers/pcdoctor_analysis workers/pcdoctor_analysis
COPY api/pyproject.toml api/README.md api/
COPY api/pcdoctor_api api/pcdoctor_api
RUN pip install ./workers "./api[photo]"

# The Windows collector, offered for download from the dashboard.
COPY collector/PCDoctor.cmd collector/Collect-PCDoctor.ps1 collector/PCDoctorCollector.psm1 \
     collector/Get-Tools.ps1 collector/README.md collector/
ENV PCDOCTOR_COLLECTOR_DIR=/app/collector

# Run as an ordinary user; /data holds the uploaded runs.
RUN useradd --create-home --uid 10001 pcdoctor && mkdir /data && chown pcdoctor /data
USER pcdoctor
VOLUME /data
EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2)"

CMD ["uvicorn", "pcdoctor_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
