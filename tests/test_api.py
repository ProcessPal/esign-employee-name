"""Tests for the FastAPI /prepare endpoint."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from esign.api import app, MAX_UPLOAD_SIZE

client = TestClient(app)

FIXTURES = Path(__file__).parent / "fixtures"


def _pdf(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# Success path
# ---------------------------------------------------------------------------


def test_prepare_success():
    pdf_bytes = _pdf("sample.pdf")
    resp = client.post("/prepare", files={"file": ("sample.pdf", pdf_bytes, "application/pdf")})
    assert resp.status_code == 200
    assert resp.content[:5] == b"%PDF-"
    assert "X-Fields-Added" in resp.headers


# ---------------------------------------------------------------------------
# No match
# ---------------------------------------------------------------------------


def test_prepare_no_match():
    pdf_bytes = _pdf("no-match.pdf")
    resp = client.post("/prepare", files={"file": ("no-match.pdf", pdf_bytes, "application/pdf")})
    assert resp.status_code == 422
    body = resp.json()
    assert "Text not found" in body["detail"]


def test_prepare_custom_search_text():
    pdf_bytes = _pdf("sample.pdf")
    resp = client.post(
        "/prepare?search_text=whatever",
        files={"file": ("sample.pdf", pdf_bytes, "application/pdf")},
    )
    assert resp.status_code == 422
    body = resp.json()
    assert "Text not found" in body["detail"]
    assert body["search_text"] == "whatever"


# ---------------------------------------------------------------------------
# Invalid input
# ---------------------------------------------------------------------------


def test_prepare_invalid_pdf():
    resp = client.post(
        "/prepare",
        files={"file": ("bad.pdf", b"this is not a pdf", "application/pdf")},
    )
    assert resp.status_code == 400


def test_prepare_empty_file():
    resp = client.post(
        "/prepare",
        files={"file": ("empty.pdf", b"", "application/pdf")},
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Size limit
# ---------------------------------------------------------------------------


def test_prepare_file_too_large():
    with patch("esign.api.MAX_UPLOAD_SIZE", 10):
        resp = client.post(
            "/prepare",
            files={"file": ("big.pdf", b"%PDF-" + b"x" * 20, "application/pdf")},
        )
    assert resp.status_code == 413
