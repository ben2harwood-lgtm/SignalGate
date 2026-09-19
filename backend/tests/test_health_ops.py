"""Operational probe tests."""
from __future__ import annotations


def test_liveness_does_not_need_application_state(client):
    response = client.get("/livez")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_readiness_checks_database(client):
    response = client.get("/readyz")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "database": "ok"}
