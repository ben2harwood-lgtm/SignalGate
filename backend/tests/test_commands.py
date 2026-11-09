"""Command polling, execution, and management event tests."""
from __future__ import annotations

import pytest

from .conftest import EA_HEADERS, create_signal, register_user

VALID = "XAUUSD BUY SL 2343 TP1 2353 TP2 2358 TP3 2363"


def _approve(client, telegram_id="123"):
    register_user(client, telegram_id)
    sig = create_signal(client, VALID)
    resp = client.post(
        f"/signals/{sig['id']}/approve", json={"telegram_user_id": telegram_id}
    ).json()
    return resp


def _user_id(client, telegram_id="123"):
    # registration returns id
    u = register_user(client, telegram_id)
    return u["id"]


def test_pending_command_returned_once(client):
    user = register_user(client, "123")
    sig = create_signal(client, VALID)
    client.post(f"/signals/{sig['id']}/approve", json={"telegram_user_id": "123"})

    r1 = client.get(
        "/commands/pending", params={"user_id": user["id"]}, headers=EA_HEADERS
    ).json()
    assert r1["command"] is not None
    assert r1["command"]["symbol"] == "XAUUSD"
    assert len(r1["command"]["take_profits"]) == 3

    # Second poll should not return the same command (now SENT_TO_EA).
    r2 = client.get(
        "/commands/pending", params={"user_id": user["id"]}, headers=EA_HEADERS
    ).json()
    assert r2["command"] is None


def test_pending_requires_ea_key(client):
    resp = client.get("/commands/pending", params={"user_id": "USER-000001"})
    assert resp.status_code == 401


def test_execution_success_updates_status(client):
    user = register_user(client, "123")
    sig = create_signal(client, VALID)
    client.post(f"/signals/{sig['id']}/approve", json={"telegram_user_id": "123"})
    cmd = client.get(
        "/commands/pending", params={"user_id": user["id"]}, headers=EA_HEADERS
    ).json()["command"]
    cid = cmd["command_id"]

    client.post(f"/commands/{cid}/received", json={}, headers=EA_HEADERS)
    resp = client.post(
        f"/commands/{cid}/execution",
        json={
            "status": "SUCCESS",
            "broker_ticket": "100",
            "child_tickets_json": "[100,101,102]",
            "executed_symbol": "XAUUSD",
            "executed_direction": "BUY",
            "executed_price": 2345.0,
            "lot_size": 0.04,
            "initial_stop_loss": 2343.0,
        },
        headers=EA_HEADERS,
    )
    assert resp.status_code == 200

    status = client.get("/admin/status", headers={"X-Admin-Id": "999"}).json()
    assert status["counts"]["executions"] == 1


def test_execution_failed_recorded(client):
    user = register_user(client, "123")
    sig = create_signal(client, VALID)
    client.post(f"/signals/{sig['id']}/approve", json={"telegram_user_id": "123"})
    cmd = client.get(
        "/commands/pending", params={"user_id": user["id"]}, headers=EA_HEADERS
    ).json()["command"]
    cid = cmd["command_id"]

    resp = client.post(
        f"/commands/{cid}/execution",
        json={
            "status": "FAILED",
            "error_code": "SPREAD_TOO_HIGH",
            "error_message": "Spread above max",
        },
        headers=EA_HEADERS,
    )
    assert resp.status_code == 200


def test_management_events_update_status(client):
    user = register_user(client, "123")
    sig = create_signal(client, VALID)
    client.post(f"/signals/{sig['id']}/approve", json={"telegram_user_id": "123"})
    cmd = client.get(
        "/commands/pending", params={"user_id": user["id"]}, headers=EA_HEADERS
    ).json()["command"]
    cid = cmd["command_id"]

    client.post(
        f"/commands/{cid}/execution",
        json={
            "status": "SUCCESS",
            "executed_price": 2345.0,
            "lot_size": 0.04,
            "initial_stop_loss": 2343.0,
        },
        headers=EA_HEADERS,
    )
    for event in ["TP1_CLOSE_SUCCESS", "TP2_CLOSE_SUCCESS", "TP3_CLOSE_SUCCESS",
                  "FULLY_CLOSED"]:
        resp = client.post(
            f"/commands/{cid}/management_event",
            json={"event_type": event, "result": "SUCCESS"},
            headers=EA_HEADERS,
        )
        assert resp.status_code == 200

    status = client.get("/admin/status", headers={"X-Admin-Id": "999"}).json()
    assert status["counts"]["management_events"] == 4


def test_duplicate_execution_report_is_idempotent(client):
    user = register_user(client, "123")
    sig = create_signal(client, VALID)
    client.post(f"/signals/{sig['id']}/approve", json={"telegram_user_id": "123"})
    cmd = client.get(
        "/commands/pending", params={"user_id": user["id"]}, headers=EA_HEADERS
    ).json()["command"]
    cid = cmd["command_id"]
    payload = {
        "status": "SUCCESS",
        "broker_ticket": "100",
        "executed_symbol": "XAUUSD",
        "executed_direction": "BUY",
        "executed_price": 2345.0,
        "lot_size": 0.04,
        "initial_stop_loss": 2343.0,
    }

    first = client.post(f"/commands/{cid}/execution", json=payload, headers=EA_HEADERS)
    second = client.post(f"/commands/{cid}/execution", json=payload, headers=EA_HEADERS)
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["status"] == "duplicate_ignored"

    status = client.get("/admin/status", headers={"X-Admin-Id": "999"}).json()
    assert status["counts"]["executions"] == 1


def test_duplicate_management_event_is_idempotent(client):
    user = register_user(client, "123")
    sig = create_signal(client, VALID)
    client.post(f"/signals/{sig['id']}/approve", json={"telegram_user_id": "123"})
    cmd = client.get(
        "/commands/pending", params={"user_id": user["id"]}, headers=EA_HEADERS
    ).json()["command"]
    cid = cmd["command_id"]
    client.post(
        f"/commands/{cid}/execution",
        json={"status": "SUCCESS", "executed_price": 2345.0, "lot_size": 0.04},
        headers=EA_HEADERS,
    )
    event = {"event_type": "TP1_CLOSE_SUCCESS", "stage": "TP1_DONE", "result": "SUCCESS"}
    first = client.post(f"/commands/{cid}/management_event", json=event, headers=EA_HEADERS)
    second = client.post(f"/commands/{cid}/management_event", json=event, headers=EA_HEADERS)
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["status"] == "duplicate_ignored"

    status = client.get("/admin/status", headers={"X-Admin-Id": "999"}).json()
    assert status["counts"]["management_events"] == 1


def test_late_event_cannot_regress_terminal_command(client):
    from app.database import SessionLocal
    from app import crud

    user = register_user(client, "123")
    sig = create_signal(client, VALID)
    client.post(f"/signals/{sig['id']}/approve", json={"telegram_user_id": "123"})
    cmd = client.get(
        "/commands/pending", params={"user_id": user["id"]}, headers=EA_HEADERS
    ).json()["command"]
    cid = cmd["command_id"]
    client.post(
        f"/commands/{cid}/execution",
        json={"status": "SUCCESS", "executed_price": 2345.0, "lot_size": 0.04},
        headers=EA_HEADERS,
    )
    client.post(
        f"/commands/{cid}/management_event",
        json={"event_type": "FULLY_CLOSED", "stage": "FULLY_CLOSED", "result": "SUCCESS"},
        headers=EA_HEADERS,
    )
    late = client.post(
        f"/commands/{cid}/management_event",
        json={"event_type": "TP1_CLOSE_SUCCESS", "stage": "LATE", "result": "SUCCESS"},
        headers=EA_HEADERS,
    )
    assert late.status_code == 200

    db = SessionLocal()
    try:
        assert crud.get_command(db, cid).status == "FULLY_CLOSED"
    finally:
        db.close()


def test_hosted_callback_is_bound_to_owning_license(client):
    from app import crud

    owner = register_user(client, "123")
    attacker = register_user(client, "456")
    sig = create_signal(client, VALID)
    client.post(f"/signals/{sig['id']}/approve", json={"telegram_user_id": "123"})

    crud.settings.require_license = True
    try:
        owner_headers = {**EA_HEADERS, "X-SG-License-Key": owner["license_key"]}
        attacker_headers = {**EA_HEADERS, "X-SG-License-Key": attacker["license_key"]}
        cmd = client.get("/commands/pending", headers=owner_headers).json()["command"]
        assert cmd is not None

        denied = client.post(
            f"/commands/{cmd['command_id']}/execution",
            json={"status": "FAILED", "error_code": "TEST"},
            headers=attacker_headers,
        )
        assert denied.status_code == 403

        allowed = client.post(
            f"/commands/{cmd['command_id']}/execution",
            json={"status": "FAILED", "error_code": "TEST"},
            headers=owner_headers,
        )
        assert allowed.status_code == 200
    finally:
        crud.settings.require_license = False



def test_conflicting_execution_retry_is_409_and_audited(client):
    from app import models
    from app.database import SessionLocal

    user = register_user(client, "123")
    sig = create_signal(client, VALID)
    client.post(f"/signals/{sig['id']}/approve", json={"telegram_user_id": "123"})
    cmd = client.get(
        "/commands/pending", params={"user_id": user["id"]}, headers=EA_HEADERS
    ).json()["command"]
    cid = cmd["command_id"]

    first = client.post(
        f"/commands/{cid}/execution",
        json={
            "status": "SUCCESS",
            "broker_ticket": "100",
            "executed_symbol": "XAUUSD",
            "executed_direction": "BUY",
            "executed_price": 2345.0,
            "lot_size": 0.04,
        },
        headers=EA_HEADERS,
    )
    conflict = client.post(
        f"/commands/{cid}/execution",
        json={
            "status": "FAILED",
            "error_code": "BROKER_TIMEOUT",
            "error_message": "contradictory retry",
        },
        headers=EA_HEADERS,
    )

    assert first.status_code == 200
    assert conflict.status_code == 409
    assert "manual reconciliation" in conflict.json()["detail"].lower()

    db = SessionLocal()
    try:
        assert db.query(models.Execution).count() == 1
        audit = (
            db.query(models.AuditLog)
            .filter(models.AuditLog.event_type == "EXECUTION_REPORT_CONFLICT")
            .one()
        )
        assert audit.entity_id == cid
    finally:
        db.close()


def test_same_status_different_broker_ticket_is_execution_conflict(client):
    user = register_user(client, "123")
    sig = create_signal(client, VALID)
    client.post(f"/signals/{sig['id']}/approve", json={"telegram_user_id": "123"})
    cmd = client.get(
        "/commands/pending", params={"user_id": user["id"]}, headers=EA_HEADERS
    ).json()["command"]
    cid = cmd["command_id"]

    payload = {
        "status": "SUCCESS",
        "broker_ticket": "100",
        "executed_symbol": "XAUUSD",
        "executed_direction": "BUY",
        "executed_price": 2345.0,
        "lot_size": 0.04,
    }
    first = client.post(
        f"/commands/{cid}/execution", json=payload, headers=EA_HEADERS
    )
    second = client.post(
        f"/commands/{cid}/execution",
        json={**payload, "broker_ticket": "999"},
        headers=EA_HEADERS,
    )

    assert first.status_code == 200
    assert second.status_code == 409


def test_conflicting_management_retry_is_409_and_audited(client):
    from app import models
    from app.database import SessionLocal

    user = register_user(client, "123")
    sig = create_signal(client, VALID)
    client.post(f"/signals/{sig['id']}/approve", json={"telegram_user_id": "123"})
    cmd = client.get(
        "/commands/pending", params={"user_id": user["id"]}, headers=EA_HEADERS
    ).json()["command"]
    cid = cmd["command_id"]
    client.post(
        f"/commands/{cid}/execution",
        json={"status": "SUCCESS", "executed_price": 2345.0, "lot_size": 0.04},
        headers=EA_HEADERS,
    )

    first = client.post(
        f"/commands/{cid}/management_event",
        json={
            "event_type": "TP1_CLOSE_SUCCESS",
            "stage": "TP1_DONE",
            "result": "SUCCESS",
            "price": 2353.0,
        },
        headers=EA_HEADERS,
    )
    conflict = client.post(
        f"/commands/{cid}/management_event",
        json={
            "event_type": "TP1_CLOSE_SUCCESS",
            "stage": "TP1_DONE",
            "result": "SUCCESS",
            "price": 2354.0,
        },
        headers=EA_HEADERS,
    )

    assert first.status_code == 200
    assert conflict.status_code == 409
    assert "manual reconciliation" in conflict.json()["detail"].lower()

    db = SessionLocal()
    try:
        assert db.query(models.TradeManagementEvent).count() == 1
        audit = (
            db.query(models.AuditLog)
            .filter(models.AuditLog.event_type == "MANAGEMENT_EVENT_CONFLICT")
            .one()
        )
        assert audit.entity_id == cid
    finally:
        db.close()


def test_first_execution_report_requires_claimed_command(client):
    from app import models
    from app.database import SessionLocal

    user = register_user(client, "801")
    sig = create_signal(client, VALID)
    decision = client.post(
        f"/signals/{sig['id']}/approve",
        json={"telegram_user_id": "801"},
    ).json()
    cid = decision["command_id"]

    premature = client.post(
        f"/commands/{cid}/execution",
        json={"status": "SUCCESS", "executed_price": 2345.0, "lot_size": 0.04},
        headers=EA_HEADERS,
    )
    assert premature.status_code == 409

    db = SessionLocal()
    try:
        assert db.query(models.Execution).count() == 0
        assert db.get(models.Command, cid).status == "PENDING"
    finally:
        db.close()


def test_broker_snapshot_recovers_lost_execution_callback(client):
    from app import models
    from app.database import SessionLocal

    user = register_user(client, "802")
    sig = create_signal(client, VALID)
    client.post(
        f"/signals/{sig['id']}/approve",
        json={"telegram_user_id": "802"},
    )
    cmd = client.get(
        "/commands/pending",
        params={"user_id": user["id"]},
        headers=EA_HEADERS,
    ).json()["command"]
    cid = cmd["command_id"]

    snapshot = {
        "broker_tickets": ["9001", "9002", "9003"],
        "executed_symbol": "XAUUSD.a",
        "executed_direction": "BUY",
        "executed_price": 2345.0,
        "lot_size": 0.04,
        "stop_loss": 2343.0,
    }
    recovered = client.post(
        f"/commands/{cid}/reconcile_open_position",
        json=snapshot,
        headers=EA_HEADERS,
    )
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["status"] == "recovered"
    assert recovered.json()["command_status"] == "EXECUTED_OPEN"

    repeated = client.post(
        f"/commands/{cid}/reconcile_open_position",
        json={**snapshot, "broker_tickets": ["9002", "9003"]},
        headers=EA_HEADERS,
    )
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["status"] == "matched"

    db = SessionLocal()
    try:
        execution = (
            db.query(models.Execution)
            .filter(models.Execution.command_id == cid)
            .one()
        )
        assert execution.status == "SUCCESS"
        assert execution.executed_symbol == "XAUUSD.a"
        ledger = (
            db.query(models.PerformanceLedger)
            .filter(models.PerformanceLedger.command_id == cid)
            .one()
        )
        assert ledger.result_status == "EXECUTED_OPEN"
        audit = (
            db.query(models.AuditLog)
            .filter(
                models.AuditLog.event_type
                == "EXECUTION_RECOVERED_FROM_BROKER_SNAPSHOT"
            )
            .one()
        )
        assert audit.entity_id == execution.id
    finally:
        db.close()


def test_broker_snapshot_conflict_fails_closed_and_is_audited(client):
    from app import models
    from app.database import SessionLocal

    user = register_user(client, "803")
    sig = create_signal(client, VALID)
    client.post(
        f"/signals/{sig['id']}/approve",
        json={"telegram_user_id": "803"},
    )
    cmd = client.get(
        "/commands/pending",
        params={"user_id": user["id"]},
        headers=EA_HEADERS,
    ).json()["command"]
    cid = cmd["command_id"]

    conflict = client.post(
        f"/commands/{cid}/reconcile_open_position",
        json={
            "broker_tickets": ["9999"],
            "executed_symbol": "EURUSD",
            "executed_direction": "SELL",
            "executed_price": 1.1,
            "lot_size": 0.01,
        },
        headers=EA_HEADERS,
    )
    assert conflict.status_code == 409

    db = SessionLocal()
    try:
        assert db.query(models.Execution).count() == 0
        audit = (
            db.query(models.AuditLog)
            .filter(models.AuditLog.event_type == "BROKER_RECONCILIATION_CONFLICT")
            .one()
        )
        assert audit.entity_id == cid
    finally:
        db.close()


def test_open_snapshot_cannot_override_failed_execution(client):
    user = register_user(client, "804")
    sig = create_signal(client, VALID)
    client.post(
        f"/signals/{sig['id']}/approve",
        json={"telegram_user_id": "804"},
    )
    cmd = client.get(
        "/commands/pending",
        params={"user_id": user["id"]},
        headers=EA_HEADERS,
    ).json()["command"]
    cid = cmd["command_id"]

    failed = client.post(
        f"/commands/{cid}/execution",
        json={
            "status": "FAILED",
            "error_code": "MARKET_CLOSED",
            "error_message": "rejected",
        },
        headers=EA_HEADERS,
    )
    assert failed.status_code == 200

    conflict = client.post(
        f"/commands/{cid}/reconcile_open_position",
        json={
            "broker_tickets": ["8001"],
            "executed_symbol": "XAUUSD",
            "executed_direction": "BUY",
            "executed_price": 2345.0,
            "lot_size": 0.04,
        },
        headers=EA_HEADERS,
    )
    assert conflict.status_code == 409


def test_hosted_reconciliation_is_bound_to_owning_license(client):
    from app import crud

    owner = register_user(client, "805")
    attacker = register_user(client, "806")
    sig = create_signal(client, VALID)
    client.post(
        f"/signals/{sig['id']}/approve",
        json={"telegram_user_id": "805"},
    )
    crud.settings.require_license = True
    try:
        owner_headers = {**EA_HEADERS, "X-SG-License-Key": owner["license_key"]}
        attacker_headers = {**EA_HEADERS, "X-SG-License-Key": attacker["license_key"]}
        cmd = client.get("/commands/pending", headers=owner_headers).json()["command"]
        cid = cmd["command_id"]
        payload = {
            "broker_tickets": ["7001"],
            "executed_symbol": "XAUUSD",
            "executed_direction": "BUY",
            "executed_price": 2345.0,
            "lot_size": 0.04,
        }
        denied = client.post(
            f"/commands/{cid}/reconcile_open_position",
            json=payload,
            headers=attacker_headers,
        )
        assert denied.status_code == 403
        allowed = client.post(
            f"/commands/{cid}/reconcile_open_position",
            json=payload,
            headers=owner_headers,
        )
        assert allowed.status_code == 200
        assert allowed.json()["status"] == "recovered"
    finally:
        crud.settings.require_license = False



def test_rotated_license_refuses_execution_and_reconciliation_after_claim(client):
    """A revoked customer licence cannot report a broker outcome after EA claim.

    Both endpoints receive synthetic payloads; no real broker is contacted.
    """
    from app import crud, models
    from app.database import SessionLocal

    owner = register_user(client, "809")
    sig = create_signal(client, VALID)
    approved = client.post(
        f"/signals/{sig['id']}/approve",
        json={"telegram_user_id": "809"},
    )
    assert approved.status_code == 200
    assert approved.json()["result"] == "APPROVED"

    original_hosted = crud.settings.require_license
    crud.settings.require_license = True
    try:
        old_headers = {**EA_HEADERS, "X-SG-License-Key": owner["license_key"]}
        claimed = client.get("/commands/pending", headers=old_headers)
        assert claimed.status_code == 200
        command = claimed.json()["command"]
        assert command is not None
        cid = command["command_id"]

        with SessionLocal() as db:
            account = crud.get_user_by_telegram(db, "809")
            assert account is not None
            fresh_key = crud.issue_license(db, account)
            db.commit()
        assert fresh_key != owner["license_key"]
        fresh_headers = {**EA_HEADERS, "X-SG-License-Key": fresh_key}

        snapshot = {
            "broker_tickets": ["8091"],
            "executed_symbol": "XAUUSD",
            "executed_direction": "BUY",
            "executed_price": 2345.0,
            "lot_size": 0.04,
        }
        # Missing customer authority and a formerly valid, rotated-out key
        # must both be rejected after claim, without any callback side effects.
        for endpoint, payload in (
            ("execution", {"status": "FAILED", "error_code": "STALE_KEY"}),
            ("reconcile_open_position", snapshot),
        ):
            for credential_case, headers in (
                ("missing", EA_HEADERS),
                ("revoked", old_headers),
            ):
                denied = client.post(
                    f"/commands/{cid}/{endpoint}", json=payload, headers=headers
                )
                assert denied.status_code == 403, (
                    endpoint, credential_case, denied.text
                )

        with SessionLocal() as db:
            assert crud.get_command(db, cid).status == "SENT_TO_EA"
            assert (
                db.query(models.Execution)
                .filter(models.Execution.command_id == cid)
                .count() == 0
            )
            assert (
                db.query(models.AuditLog)
                .filter(
                    models.AuditLog.entity_id == cid,
                    models.AuditLog.event_type == "BROKER_RECONCILIATION_CONFLICT",
                )
                .count() == 0
            )

        # A current key can still report an existing synthetic broker snapshot.
        allowed = client.post(
            f"/commands/{cid}/reconcile_open_position",
            json=snapshot,
            headers=fresh_headers,
        )
        assert allowed.status_code == 200, allowed.text
        assert allowed.json()["status"] == "recovered"
    finally:
        crud.settings.require_license = original_hosted


def test_hosted_ack_and_management_reject_missing_or_foreign_customer_license(client):
    """Synthetic EA callback isolation: a shared EA key is not user authority.

    The existing hosted tests cover execution reports and open-position
    reconciliation. This adds negative coverage for the other two callback
    endpoints, without talking to a broker or creating a real execution.
    """
    from app import crud, models
    from app.database import SessionLocal

    owner = register_user(client, "807")
    other = register_user(client, "808")
    sig = create_signal(client, VALID)
    approval = client.post(
        f"/signals/{sig['id']}/approve",
        json={"telegram_user_id": "807"},
    )
    assert approval.status_code == 200
    assert approval.json()["result"] == "APPROVED"

    original_hosted = crud.settings.require_license
    crud.settings.require_license = True
    try:
        owner_headers = {**EA_HEADERS, "X-SG-License-Key": owner["license_key"]}
        foreign_headers = {**EA_HEADERS, "X-SG-License-Key": other["license_key"]}
        claimed = client.get("/commands/pending", headers=owner_headers)
        assert claimed.status_code == 200
        command = claimed.json()["command"]
        assert command is not None
        cid = command["command_id"]

        # Rotate after EA claim: the previous owner's key is now revoked.
        # A formerly valid key must not retain callback authority.
        with SessionLocal() as db:
            account = crud.get_user_by_telegram(db, "807")
            assert account is not None
            rotated_key = crud.issue_license(db, account)
            db.commit()
        assert rotated_key != owner["license_key"]
        rotated_headers = {**EA_HEADERS, "X-SG-License-Key": rotated_key}

        for headers in (EA_HEADERS, foreign_headers, owner_headers):
            for endpoint, payload in (
                ("received", {}),
                ("management_event", {"event_type": "TP1_REACHED", "result": "PENDING"}),
            ):
                denied = client.post(
                    f"/commands/{cid}/{endpoint}",
                    json=payload,
                    headers=headers,
                )
                assert denied.status_code == 403, (endpoint, denied.text)

        with SessionLocal() as db:
            assert crud.get_command(db, cid).status == "SENT_TO_EA"
            assert (
                db.query(models.TradeManagementEvent)
                .filter(models.TradeManagementEvent.command_id == cid)
                .count() == 0
            )
            assert (
                db.query(models.AuditLog)
                .filter(
                    models.AuditLog.event_type == "COMMAND_RECEIVED_BY_EA",
                    models.AuditLog.entity_id == cid,
                )
                .count() == 0
            )
            assert (
                db.query(models.Execution)
                .filter(models.Execution.command_id == cid)
                .count() == 0
            )

        # The freshly rotated owner credential works; stale credentials do not.
        allowed = client.post(
            f"/commands/{cid}/received", json={}, headers=rotated_headers
        )
        assert allowed.status_code == 200
        assert allowed.json()["status"] == "received"
    finally:
        crud.settings.require_license = original_hosted


@pytest.mark.parametrize("credential_case", ("foreign", "missing", "revoked"))
@pytest.mark.parametrize(
    "endpoint,payload",
    (
        ("received", {}),
        ("execution", {"status": "FAILED", "error_code": "SYNTHETIC"}),
        (
            "reconcile_open_position",
            {
                "broker_tickets": ["811001"],
                "executed_symbol": "XAUUSD",
                "executed_direction": "BUY",
                "executed_price": 2345.0,
                "lot_size": 0.04,
            },
        ),
        ("management_event", {"event_type": "TP1_REACHED", "result": "PENDING"}),
    ),
)
def test_hosted_callback_does_not_reveal_foreign_command_existence(
    client, endpoint, payload, credential_case
):
    """Offline tenant privacy witness, not an externally accepted security fix.

    Check all four callbacks using a foreign, absent, or revoked-after-claim
    customer licence. A shared EA key is not tenant authority. Both foreign
    and absent command IDs must return identical 403 bodies with no mutation.
    This is an offline regression, not independent security acceptance.
    """
    from app import crud, models
    from app.database import SessionLocal

    owner = register_user(client, "812")
    nonowner = register_user(client, "813")
    signal = create_signal(client, VALID)
    approved = client.post(
        f"/signals/{signal['id']}/approve",
        json={"telegram_user_id": "812"},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["result"] == "APPROVED"

    original_hosted = crud.settings.require_license
    crud.settings.require_license = True
    try:
        owner_headers = {**EA_HEADERS, "X-SG-License-Key": owner["license_key"]}
        other_headers = {**EA_HEADERS, "X-SG-License-Key": nonowner["license_key"]}
        claimed = client.get("/commands/pending", headers=owner_headers)
        assert claimed.status_code == 200, claimed.text
        command = claimed.json()["command"]
        assert command is not None
        command_id = command["command_id"]
        absent_id = command_id + "-not-created"
        with SessionLocal() as db:
            assert crud.get_command(db, absent_id) is None
            assert crud.get_command(db, command_id).status == "SENT_TO_EA"

        if credential_case == "foreign":
            probe_headers = other_headers
        elif credential_case == "missing":
            probe_headers = EA_HEADERS
        else:
            # Revocation after an EA claim must not permit an existence probe.
            with SessionLocal() as db:
                owner_account = crud.get_user_by_telegram(db, "812")
                assert owner_account is not None
                replacement = crud.issue_license(db, owner_account)
                db.commit()
            assert replacement != owner["license_key"]
            probe_headers = owner_headers

        foreign = client.post(
            f"/commands/{command_id}/{endpoint}",
            json=payload, headers=probe_headers,
        )
        absent = client.post(
            f"/commands/{absent_id}/{endpoint}",
            json=payload, headers=probe_headers,
        )
        assert foreign.status_code in (403, 404), (endpoint, foreign.text)
        assert absent.status_code in (403, 404), (endpoint, absent.text)
        with SessionLocal() as db:
            assert crud.get_command(db, command_id).status == "SENT_TO_EA"
            assert (
                db.query(models.Execution)
                .filter(models.Execution.command_id == command_id)
                .count() == 0
            )
            assert (
                db.query(models.TradeManagementEvent)
                .filter(models.TradeManagementEvent.command_id == command_id)
                .count() == 0
            )
            assert (
                db.query(models.AuditLog)
                .filter(
                    models.AuditLog.event_type == "COMMAND_RECEIVED_BY_EA",
                    models.AuditLog.entity_id == command_id,
                )
                .count() == 0
            )

        # A nonowner, absent or revoked licence gets the exact same denial
        # whether the opaque command ID belongs to another tenant or is absent.
        assert foreign.status_code == absent.status_code == 403, (
            endpoint, credential_case, foreign.text, absent.text
        )
        assert foreign.json() == absent.json() == {
            "detail": "Command does not belong to this EA licence"
        }
    finally:
        crud.settings.require_license = original_hosted
