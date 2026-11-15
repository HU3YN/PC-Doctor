"""Private links and tokens never reach the access log."""

from __future__ import annotations

import logging

import pytest

from pcdoctor_api import logs


@pytest.mark.parametrize(
    ("path", "logged"),
    [
        ("/api/shared/k3Jv9Qp_2xZr-7LmN0aBc", "/api/shared/<key>"),
        ("/api/shared/k3Jv9Qp_2xZr-7LmN0aBc/series", "/api/shared/<key>/series"),
        ("/r/k3Jv9Qp_2xZr-7LmN0aBc?x=1", "/r/<key>?x=1"),
        ("/snap/abcDEF123", "/snap/<key>"),
        ("/api/photo-links/abcDEF123/photos", "/api/photo-links/<key>/photos"),
        ("/api/live/abcDEF123/samples", "/api/live/<token>/samples"),
        ("/api/live/0123abcd", "/api/live/0123abcd"),  # a session id, master only: not secret
        ("/api/runs/0123abcd", "/api/runs/0123abcd"),
    ],
)
def test_secrets_in_paths_are_replaced(path, logged):
    assert logs.redact(path) == logged


def test_the_filter_rewrites_uvicorns_access_record():
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %d',
        ("1.2.3.4:5", "GET", "/api/shared/the-private-key", "1.1", 200),
        None,
    )
    assert logs.RedactPaths().filter(record)
    assert "the-private-key" not in record.getMessage()
    assert "/api/shared/<key>" in record.getMessage()


def test_the_app_installs_the_filter(client):
    assert any(isinstance(f, logs.RedactPaths) for f in logging.getLogger("uvicorn.access").filters)
