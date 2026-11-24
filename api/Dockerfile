# Build from the repository root:  docker build -f api/Dockerfile .
# Base images are pinned by digest; Dependabot proposes updates.
FROM python:3.13-slim@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90

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
# Every dependency at the exact version and hash in the lock file
# (api/lock.py makes it, build backend setuptools included), then this
# repository's own two packages built with that backend and no network:
# nothing is downloaded outside the hashed lock.
COPY api/requirements.lock api/
RUN pip install --require-hashes -r api/requirements.lock \
    && pip install --no-deps --no-build-isolation ./workers ./api

# The Windows collector, offered for download from the dashboard.
COPY collector/PCDoctor.cmd collector/Collect-PCDoctor.ps1 collector/PCDoctorCollector.psm1 \
     collector/Get-Tools.ps1 collector/README.md collector/PresentMon-LICENSE.txt \
     collector/temperature-tools.json collector/
COPY collector/licences collector/licences
# Intel's PresentMon, PawnIO's installer and LibreHardwareMonitorLib go inside
# that download, so the zip this server offers is the same file as the release
# for this commit. They are not in git: fetch the versions Get-Tools.ps1 and
# temperature-tools.json pin. The build fails unless every SHA-256 is the pinned one.
RUN python api/pcdoctor_api/services/collector_build.py fetch-tools collector
ENV PCDOCTOR_COLLECTOR_DIR=/app/collector

# Run as an ordinary user; /data holds the uploaded runs.
RUN useradd --create-home --uid 10001 pcdoctor && mkdir /data && chown pcdoctor /data
USER pcdoctor
VOLUME /data
EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2)"

CMD ["uvicorn", "pcdoctor_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
