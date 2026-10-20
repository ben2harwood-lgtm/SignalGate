"""All-history operational observations must stay tenant-bound and fail closed."""
import datetime as dt

from app import crud, models

from .conftest import register_user
from .test_provider_export import VALID, _headers, _provider


def _command(client, db, provider, feed, key):
    user = register_user(client, "9811")
    crud.subscribe_user_to_feed(db, provider, feed, db.get(models.User, user["id"]))
    db.commit()
    signal = client.post("/signals/create", headers=_headers(provider, key), json={
        "raw_text": VALID, "feed_id": feed.id,
    }).json()
    approval = client.post(f"/signals/{signal['id']}/approve", json={
        "telegram_user_id": user["telegram_user_id"],
    }).json()
    return db.get(models.Command, approval["command_id"])


def _copy(db, command, identifier, **changes):
    values = {column.name: getattr(command, column.name) for column in models.Command.__table__.columns}
    values.update(id=identifier, **changes)
    row = models.Command(**values)
    db.add(row)
    return row


def test_operations_empty_setup_and_authentication(client, db):
    provider, feed, key = _provider(db, "ops-setup")
    crud.set_feed_paused(db, feed, True)
    db.commit()
    assert client.get("/providers/me/operations").status_code in {401, 403}
    assert client.get("/providers/me/operations", headers=_headers(provider, key + "bad")).status_code == 401
    response = client.get("/providers/me/operations", headers=_headers(provider, key))
    assert response.status_code == 200
    body = response.json()
    assert body["demo_only_mode"] is True
    assert body["attention_count"] == 0
    assert any("All feeds are paused" in text for text in body["observations"])
    assert any("No active subscriptions" in text for text in body["observations"])
    assert "not pilot" in body["scope"]
    assert key not in response.text


def test_operations_finds_old_problem_outside_history_window_and_isolates_tenants(client, db):
    provider, feed, key = _provider(db, "ops-a")
    other, _other_feed, other_key = _provider(db, "ops-b")
    command = _command(client, db, provider, feed, key)
    command.status = "SENT_TO_EA"
    command.created_at = models.utcnow() - dt.timedelta(days=2)
    command.sent_to_ea_at = None
    for index in range(110):
        _copy(db, command, f"OPS-RECENT-{index}", status="PENDING", created_at=models.utcnow(), expires_at=models.utcnow() + dt.timedelta(hours=1))
    db.commit()
    body = client.get("/providers/me/operations", headers=_headers(provider, key)).json()
    assert body["attention_count"] == 1
    assert body["counts"]["awaiting_report_over_5_minutes"] == 1
    assert body["oldest_attention_commands"][0]["command_id"] == command.id
    assert command.id not in {row["command_id"] for row in crud.provider_history(db, provider.id, limit=100)}
    other_body = client.get("/providers/me/operations", headers=_headers(other, other_key)).json()
    assert other_body["attention_count"] == 0
    assert other_body["oldest_attention_commands"] == []
    assert command.id not in str(other_body)
    crud.rotate_provider_credential(db, provider)
    db.commit()
    assert client.get("/providers/me/operations", headers=_headers(provider, key)).status_code == 401


def test_operations_matches_reconciliation_rules_and_bounds_samples(client, db):
    provider, feed, key = _provider(db, "ops-states")
    base = _command(client, db, provider, feed, key)
    base.expires_at = models.utcnow() + dt.timedelta(hours=1)
    expected_review = 0
    statuses = ["PENDING", "SENT_TO_EA", "FAILED", "FULLY_CLOSED", "EXECUTED_OPEN", "PARTIAL_TP1_DONE", "PARTIAL_TP2_DONE", "EXPIRED", "UNKNOWN"]
    for index, (command_status, execution_status) in enumerate(
        (c, e) for c in statuses for e in (None, "SUCCESS", "FAILED", "UNKNOWN")
    ):
        row = _copy(db, base, f"OPS-STATE-{index}", status=command_status)
        execution = None
        if execution_status:
            execution = models.Execution(id=f"OPS-EXEC-{index}", command_id=row.id, user_id=row.user_id, status=execution_status)
            db.add(execution)
        expected_review += crud._reconciliation_state(row, execution) == "REVIEW_REQUIRED"
    db.commit()
    body = client.get("/providers/me/operations", headers=_headers(provider, key)).json()
    assert body["counts"]["review_required"] == expected_review
    assert body["attention_count"] == expected_review
    assert len(body["oldest_attention_commands"]) == 20
    assert body["attention_commands_truncated"] is True
    assert "license" not in str(body)


def test_operations_expiry_and_report_age_boundaries(client, db):
    provider, feed, key = _provider(db, "ops-age")
    command = _command(client, db, provider, feed, key)
    command.expires_at = models.utcnow() - dt.timedelta(seconds=1)
    _copy(db, command, "OPS-FRESH", status="SENT_TO_EA", sent_to_ea_at=models.utcnow())
    _copy(db, command, "OPS-OLD", status="SENT_TO_EA", sent_to_ea_at=models.utcnow() - dt.timedelta(minutes=6))
    db.commit()
    body = client.get("/providers/me/operations", headers=_headers(provider, key)).json()
    assert body["counts"]["expired_pending"] == 1
    assert body["counts"]["awaiting_report_over_5_minutes"] == 1
    assert body["attention_count"] == 2
