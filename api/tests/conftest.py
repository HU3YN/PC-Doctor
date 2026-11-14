"""Test setup.

The tests run against SQLite by default (nothing to install) and against
PostgreSQL when PCDOCTOR_TEST_DATABASE_URL is set - CI runs both.
"""

from __future__ import annotations

import os
import warnings
from collections.abc import Iterator

import pytest

warnings.filterwarnings("ignore", message="Using `httpx` with `starlette.testclient`")

from fastapi.testclient import TestClient  # noqa: E402
from pcdoctor_analysis import synth  # noqa: E402
from sqlalchemy import text  # noqa: E402

from pcdoctor_api import db  # noqa: E402
from pcdoctor_api.config import get_settings  # noqa: E402
from pcdoctor_api.main import create_app  # noqa: E402

TABLES = (
    "photos",
    "photo_links",
    "sessions",
    "identities",
    "accounts",
    "work_log",
    "findings",
    "runs",
)
MASTER = {"username": "huey", "password": "correct horse battery"}


@pytest.fixture
def client(tmp_path, monkeypatch) -> Iterator[TestClient]:
    monkeypatch.setenv("PCDOCTOR_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PCDOCTOR_DATABASE_URL", os.environ.get("PCDOCTOR_TEST_DATABASE_URL", ""))
    monkeypatch.setenv("PCDOCTOR_WEB_DIST", str(tmp_path / "no-dashboard"))
    get_settings.cache_clear()
    db.reset_engine()
    with TestClient(create_app()) as test_client:  # start-up runs the migrations
        if not get_settings().sqlalchemy_url.startswith("sqlite"):
            with db.get_engine().begin() as connection:  # a shared database: start clean
                connection.execute(text(f"TRUNCATE {', '.join(TABLES)} RESTART IDENTITY CASCADE"))
        from pcdoctor_api.services import auth

        auth.login_attempts.reset()
        auth.guest_uploads.reset()
        auth.bot_uploads.reset()
        # Most tests act as the signed-in master; the "guest" fixture is everyone else.
        code = auth.setup_code(get_settings().data_dir)
        created = test_client.post("/api/auth/setup", json={**MASTER, "setup_code": code})
        assert created.status_code == 200, created.text
        yield test_client
    db.reset_engine()
    get_settings.cache_clear()


@pytest.fixture
def session(client):
    """A database session for looking at what was stored. Always closed: an
    open session holds locks on PostgreSQL and would block the next test."""
    database = next(db.get_db())
    try:
        yield database
    finally:
        database.rollback()
        database.close()


@pytest.fixture
def guest(client) -> Iterator[TestClient]:
    """A second browser on the same server, not signed in."""
    with TestClient(client.app, cookies={}) as other:
        other.cookies.clear()
        yield other


@pytest.fixture
def upload(client):
    """Upload one of the synthetic sample runs and return the response JSON."""

    def _upload(name: str = "healthy", label: str = "") -> dict:
        sample = synth.build(name)
        response = client.post(
            "/api/runs",
            files={"file": (f"{name}.zip", sample.zip_bytes(), "application/zip")},
            data={"label": label},
        )
        assert response.status_code in (200, 201), response.text
        return response.json()

    return _upload


def entry(**overrides) -> dict:
    return {"title": "PC restarts under load", "symptoms": "Cuts out mid-game.", **overrides}
