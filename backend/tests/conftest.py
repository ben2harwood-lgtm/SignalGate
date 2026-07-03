"""Pytest fixtures. Configures an isolated temp SQLite DB before importing the
app so the prototype's module-level engine points at test data."""
from __future__ import annotations

import os
import tempfile

import pytest

# --- Configure environment BEFORE importing app modules -------------------
_TMP_DB = os.path.join(tempfile.gettempdir(), "signalgate_test.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP_DB}"
os.environ["ADMIN_TELEGRAM_IDS"] = "999"
os.environ["SIGNAL_PROVIDER_TELEGRAM_IDS"] = "777"
os.environ["EA_API_KEY"] = "test-ea-key"
os.environ["TELEGRAM_BOT_TOKEN"] = ""  # disable outbound telegram
os.environ["DEFAULT_SIGNAL_EXPIRY_MINUTES"] = "5"
os.environ["SIGNAL_EXTRACTOR"] = "fake"  # keep screenshot tests offline/deterministic

from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app, seed_settings  # noqa: E402

ADMIN_HEADERS = {"X-Admin-Id": "999"}
PROVIDER_HEADERS = {"X-Signal-Provider-Id": "777"}
EA_HEADERS = {"X-EA-API-Key": "test-ea-key"}


@pytest.fixture(autouse=True)
def fresh_db():
    """Drop + recreate all tables and re-seed settings before each test."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    seed_settings()
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client():
    # TestClient triggers startup events (init_db + seed) which is harmless.
    with TestClient(app) as c:
        yield c


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def register_user(client, telegram_id="123", username="ben", first_name="Ben"):
    resp = client.post(
        "/register_user",
        json={
            "telegram_user_id": telegram_id,
            "telegram_username": username,
            "first_name": first_name,
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def create_signal(client, raw_text):
    resp = client.post(
        "/signals/create",
        json={"raw_text": raw_text},
        headers=ADMIN_HEADERS,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()
