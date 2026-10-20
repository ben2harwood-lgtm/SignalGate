"""Broker-free tenant API rehearsal; these reports are fabricated, not broker evidence."""
from app import models

from .conftest import EA_HEADERS, register_user
from .test_provider_export import VALID, _headers, _provider


def test_provider_consent_recovery_manual_close_and_evidence(client, db):
    provider, feed, key = _provider(db, "rehearsal")
    other, _other_feed, other_key = _provider(db, "rehearsal-other")
    headers = _headers(provider, key)
    user = register_user(client, "9891")
    invite = client.post("/providers/me/subscription-invites", headers=headers,
                         json={"feed_id": feed.id}).json()
    consent = client.post("/subscriptions/accept", json={
        "invite_token": invite["invite_token"], "telegram_user_id": user["telegram_user_id"],
    })
    assert consent.status_code == 200, consent.text
    signal = client.post("/signals/create", headers=headers,
                         json={"raw_text": VALID, "feed_id": feed.id}).json()
    approved = client.post(f"/signals/{signal['id']}/approve", json={
        "telegram_user_id": user["telegram_user_id"],
    }).json()
    assert approved["result"] == "APPROVED"
    pending = client.get("/commands/pending", headers=EA_HEADERS, params={"user_id": user["id"]}).json()["command"]
    cid = pending["command_id"]
    assert cid == approved["command_id"]
    assert pending["demo_only"] is True
    assert "raw_text" not in pending

    # Deliberately omit the execution callback. A synthetic snapshot recovers it.
    snapshot = {"broker_tickets": ["SYNTHETIC-9891"], "executed_symbol": "EURUSD.a",
                "executed_direction": "BUY", "executed_price": 1.085,
                "lot_size": pending["lot_size"], "stop_loss": 1.08}
    recovered = client.post(f"/commands/{cid}/reconcile_open_position", headers=EA_HEADERS, json=snapshot)
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["status"] == "recovered"
    repeated = client.post(f"/commands/{cid}/reconcile_open_position", headers=EA_HEADERS, json=snapshot)
    assert repeated.json()["status"] == "matched"
    conflict = client.post(f"/commands/{cid}/reconcile_open_position", headers=EA_HEADERS,
                           json={**snapshot, "executed_direction": "SELL"})
    assert conflict.status_code == 409

    # A fabricated manual close has no TP/SL proof and must not invent a return.
    event = {"event_type": "FULLY_CLOSED", "stage": "FULLY_CLOSED", "result": "SUCCESS"}
    closed = client.post(f"/commands/{cid}/management_event", headers=EA_HEADERS, json=event)
    assert closed.status_code == 200, closed.text
    retry = client.post(f"/commands/{cid}/management_event", headers=EA_HEADERS, json=event)
    assert retry.json()["status"] == "duplicate_ignored"
    evidence = client.get("/providers/me/export", headers=headers).json()
    history = next(row for row in evidence["history"] if row["command_id"] == cid)
    assert history["command_status"] == "FULLY_CLOSED"
    assert history["reconciliation_state"] == "RECONCILED_CLOSED"
    assert history["execution"]["broker_ticket"] == "SYNTHETIC-9891"
    assert history["ledger"]["result_status"] == "CLOSED_UNATTRIBUTED"
    assert history["ledger"]["r_result"] is None
    assert len(history["management_events"]) == 1
    assert db.query(models.Execution).filter_by(command_id=cid).count() == 1
    assert cid not in str(client.get("/providers/me/export", headers=_headers(other, other_key)).json())
    for secret in (key, other_key, user["license_key"], invite["invite_token"]):
        assert secret not in str(evidence)
