"""Migration-boundary tests."""
from __future__ import annotations

from app import database


def test_hosted_init_db_never_calls_create_all(monkeypatch):
    called = False

    def _unexpected_create_all(*_args, **_kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(database.settings, "require_license", True)
    monkeypatch.setattr(database.Base.metadata, "create_all", _unexpected_create_all)

    database.init_db()
    assert called is False


def test_local_demo_init_db_keeps_create_all(monkeypatch):
    called = False

    def _create_all(*_args, **_kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(database.settings, "require_license", False)
    monkeypatch.setattr(database.Base.metadata, "create_all", _create_all)

    database.init_db()
    assert called is True
