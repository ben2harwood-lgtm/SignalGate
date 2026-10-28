#!/usr/bin/env python3
"""Offline smoke for hosted Telegram handler wiring; NEVER calls Telegram API.

Run in an isolated environment with telegram_bot/requirements.txt installed.
The bot and its handlers must be importable and register hosted commands without
any backend, broker, user account, internet access or real credentials.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
import sys

# Python -O / PYTHONOPTIMIZE removes assertions, including the safety checks
# below. Refuse a misleading green acceptance receipt before importing the bot.
if sys.flags.optimize:
    raise SystemExit(
        "SignalGate offline smoke refuses optimized Python: "
        "assertions must run to validate safety invariants"
    )
from types import SimpleNamespace
from unittest.mock import patch

import httpx

# Force synthetic credentials before importing config or instantiating the bot.
# This test must never pick up a developer's real token or hosted .env.
os.environ["TELEGRAM_BOT_TOKEN"] = "123456789:OFFLINE_TEST_ONLY"
os.environ["REQUIRE_LICENSE"] = "true"
os.environ["BACKEND_BASE_URL"] = "https://unreachable.example.invalid"

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "telegram_bot"))

from telegram.ext import CallbackQueryHandler, CommandHandler, MessageHandler  # noqa: E402
from bot import build_application  # noqa: E402
from config import config  # noqa: E402
import handlers  # noqa: E402


def check_backend_http_fail_closed() -> None:
    """HTTP errors must never look like accepted decisions; no outbound traffic."""
    original_client = httpx.AsyncClient
    calls = []

    async def exercise(method: str, status: int, valid_json: bool):
        def respond(request):
            calls.append((request.method, request.url.path))
            if not valid_json:
                return httpx.Response(status, content="not-json")
            return httpx.Response(status, json={"result": "APPROVED"})

        transport = httpx.MockTransport(respond)
        with patch.object(
            handlers.httpx, "AsyncClient",
            lambda *args, **kwargs: original_client(*args, transport=transport, **kwargs),
        ):
            if method == "GET":
                return await handlers._backend_get("/fake", params={"key": "SECRET-NEVER-LOG"})
            return await handlers._backend_post("/fake", json={"token": "SECRET-NEVER-LOG"})

    assert asyncio.run(exercise("POST", 403, True)) is None
    assert asyncio.run(exercise("POST", 500, True)) is None
    assert asyncio.run(exercise("POST", 200, False)) is None
    assert asyncio.run(exercise("GET", 404, True)) is None
    assert asyncio.run(exercise("POST", 200, True)) == {"result": "APPROVED"}
    assert calls == [("POST", "/fake"), ("POST", "/fake"),
                     ("POST", "/fake"), ("GET", "/fake"), ("POST", "/fake")]


def check_unconfirmed_decision_does_not_claim_approval() -> None:
    """No untrusted backend decision code/diagnostics can reach a subscriber."""
    seen, called = [], []
    secret = "SYNTHETIC-DECISION-TOKEN-NOT-FOR-TELEGRAM"
    current_response = None

    async def fake_post(path, **_kwargs):
        called.append(path)
        return current_response

    class Query:
        data = "YES:SIG-TEST"
        from_user = SimpleNamespace(id=1)
        message = SimpleNamespace(text="Synthetic demo trade card")

        async def answer(self):
            pass

        async def edit_message_text(self, message):
            seen.append(message)

    async def exercise(payload, decision="YES"):
        nonlocal current_response
        current_response = payload
        seen.clear()
        called.clear()
        query = Query()
        query.data = f"{decision}:SIG-TEST"
        await handlers.on_decision(SimpleNamespace(callback_query=query), None)
        expected_path = (
            f"/signals/SIG-TEST/{'approve' if decision == 'YES' else 'reject'}"
        )
        assert called == [expected_path], "Decision path changed unexpectedly"
        assert len(seen) == 1, "A callback must produce one private response"
        assert secret not in seen[0], "Backend diagnostic leaked into Telegram"
        return seen[0]

    with patch.object(handlers, "_backend_post", fake_post):
        invalid_responses = (
            None,
            ["unexpected", secret],
            {"detail": secret},
            {"result": "", "message": secret},
            {"result": secret, "message": secret},
            {"result": "NOT_A_REAL_DECISION_CODE", "message": secret},
            {"result": ["APPROVED"], "message": secret},
            {"result": {"code": "APPROVED"}, "message": secret},
            {"result": 1, "message": secret},
            {"result": "APPROVED", "detail": None, "message": secret},
            {"result": "APPROVED", "detail": "", "message": secret},
            {"result": "APPROVED", "detail": {"trace": secret}, "message": secret},
        )
        for payload in invalid_responses:
            for decision in ("YES", "NO"):
                summary = asyncio.run(exercise(payload, decision))
                assert "could not be confirmed" in summary.lower(), payload
                assert "Approved. Waiting" not in summary
                assert "➡️" not in summary

        # Even a recognised code is unsafe when it contradicts the called
        # endpoint. NO can report ALREADY_APPROVED (first decision wins), but
        # never a newly APPROVED trade; YES cannot report a newly REJECTED NO.
        # Check every known backend code against BOTH real decision routes.
        for code, expected_message in handlers.DECISION_MESSAGES.items():
            for decision in ("YES", "NO"):
                summary = asyncio.run(
                    exercise({"result": code, "message": secret}, decision)
                )
                if code in handlers.DECISION_ALLOWED_BY_ACTION[decision]:
                    assert summary == (
                        f"Synthetic demo trade card\n\n➡️ {expected_message}"
                    ), (decision, code)
                else:
                    assert "could not be confirmed" in summary.lower(), (decision, code)
                    assert "➡️" not in summary, (decision, code)
                assert secret not in summary
        assert "REJECTED" not in handlers.DECISION_ALLOWED_BY_ACTION["YES"]
        assert "APPROVED" not in handlers.DECISION_ALLOWED_BY_ACTION["NO"]
        assert "ALREADY_APPROVED" in handlers.DECISION_ALLOWED_BY_ACTION["NO"]

        called.clear()
        seen.clear()

        class InvalidQuery(Query):
            data = "UNKNOWN:SIG-TEST"

        asyncio.run(handlers.on_decision(
            SimpleNamespace(callback_query=InvalidQuery()), None
        ))
        assert seen == ["Invalid action."]
        assert not called

        # Telegram callback data is client-supplied and may be malformed or
        # adversarial. Reject it before issuing ANY backend decision request.
        assert handlers._valid_signal_id("SIG-000001")
        assert handlers._valid_signal_id("SIG-0123456789ABCDEF")
        bad_callbacks = (
            None, 123, [], {"action": "YES"}, "YES", "YES:",
            "YES:OTHER-TEST", "YES:SIG-aBc", "YES:SIG-TEST/approve",
            "YES:SIG-TEST/../../admin/status", "NO:SIG-TEST?next=1",
            "YES:SIG-TEST%2Fbad", "YES:SIG-TEST:EXTRA",
            "YES:SIG-TEST\nSECRET", "YES:SIG-Ａ",
            "YES:SIG-" + "A" * 33,
        )
        for callback_data in bad_callbacks:
            called.clear()
            seen.clear()
            malformed_query = Query()
            malformed_query.data = callback_data
            asyncio.run(handlers.on_decision(
                SimpleNamespace(callback_query=malformed_query), None
            ))
            assert seen == ["Invalid action."], callback_data
            assert not called, callback_data


def check_screenshot_extraction_fail_closed() -> None:
    """No stale previews, credential-bearing errors, or hosted legacy fallback."""
    original_client = httpx.AsyncClient
    secret = "SYNTHETIC-SECRET-NOT-FOR-TELEGRAM"

    async def connected(_user_id):
        return {"feed_id": "FEED-OFFLINE"}

    async def disconnected(_user_id):
        return None

    def exercise(*, status=500, body="", payload=None, fail=None, source=connected):
        replies = []
        warnings = []
        requests = []
        user_state = {"pending_signal_text": "OLD-NOT-APPROVED", "awaiting_edit": True}

        async def reply_text(message, **_kwargs):
            replies.append(message)

        update = SimpleNamespace(
            effective_user=SimpleNamespace(id=123456),
            message=SimpleNamespace(reply_text=reply_text),
        )
        context = SimpleNamespace(user_data=user_state)

        def respond(request):
            requests.append(request.url.path)
            if fail is not None:
                raise RuntimeError(fail)
            if payload is not None:
                return httpx.Response(status, json=payload)
            return httpx.Response(status, text=body)

        transport = httpx.MockTransport(respond)
        with (
            patch.object(handlers, "_provider_source_status", source),
            patch.object(
                handlers.httpx,
                "AsyncClient",
                lambda *args, **kwargs: original_client(
                    *args, transport=transport, **kwargs
                ),
            ),
            patch.object(
                handlers.logger,
                "warning",
                lambda fmt, *args: warnings.append(fmt % args),
            ),
        ):
            asyncio.run(
                handlers._preview_screenshot(
                    update=update,
                    context=context,
                    image_bytes=b"SYNTHETIC-IMAGE-NO-USER-DATA",
                    mime="image/jpeg",
                )
            )
        return replies, warnings, requests, user_state

    for status in (403, 500):
        replies, warnings, requests, state = exercise(
            status=status, body=f"upstream stack and token={secret}"
        )
        assert len(replies) == 1 and "rejected" in replies[0].lower()
        assert requests == ["/provider-sources/telegram/extract"]
        assert all(secret not in item for item in replies + warnings)
        assert any(str(status) in warning for warning in warnings)
        assert state == {}, "Failed extraction retained an earlier unsent preview"

    replies, warnings, requests, state = exercise(fail=f"backend URL token={secret}")
    assert len(replies) == 1 and "couldn't read" in replies[0].lower()
    assert requests == ["/provider-sources/telegram/extract"]
    assert all(secret not in item for item in replies + warnings)
    assert any("RuntimeError" in warning for warning in warnings)
    assert state == {}

    replies, warnings, requests, state = exercise(source=disconnected)
    assert len(replies) == 1 and "no longer connected" in replies[0].lower()
    assert not requests, "Hosted source revocation fell through to legacy extraction"
    assert not warnings
    assert state == {}

    # A nominal HTTP 200 is not sufficient: JSON type and all fields are untrusted.
    malformed = [
        ("array root", [], ""),
        ("null root", None, "null"),
        ("non-string text", {"parser_status": "VALID", "extracted_text": []}, ""),
        ("non-string status", {"parser_status": ["VALID"], "extracted_text": "BUY"}, ""),
        ("empty valid signal", {"parser_status": "VALID", "extracted_text": "  "}, ""),
        ("long text", {"parser_status": "VALID", "extracted_text": "B" * 5000}, ""),
        ("long notes", {"parser_status": "VALID", "extracted_text": "BUY", "notes": "N" * 5000}, ""),
        ("bad number", {"parser_status": "VALID", "extracted_text": "BUY", "tp1": []}, ""),
        ("bool number", {"parser_status": "VALID", "extracted_text": "BUY", "tp1": True}, ""),
        ("huge number", {"parser_status": "VALID", "extracted_text": "BUY", "tp1": 10 ** 400}, ""),
        ("non-finite number", None, '{"parser_status":"VALID","extracted_text":"BUY","tp1":NaN}'),
        ("invalid unicode", None, '{"parser_status":"VALID","extracted_text":"\\ud800"}'),
        ("combined preview", {
            "parser_status": "VALID", "extracted_text": "B" * 1900, "notes": "N" * 1900
        }, ""),
        ("UTF16 preview", {
            "parser_status": "VALID", "extracted_text": "🚀" * 1400, "notes": "🚀" * 600
        }, ""),
    ]
    for label, payload, body in malformed:
        replies, warnings, requests, state = exercise(
            status=200, payload=payload, body=body
        )
        assert requests == ["/provider-sources/telegram/extract"], label
        assert len(replies) == 1 and "nothing was saved" in replies[0].lower(), label
        assert state == {}, f"{label} retained stale or confirmable text"
        assert not any("B" * 64 in item or "N" * 64 in item for item in replies + warnings)

    replies, warnings, requests, state = exercise(
        status=200,
        payload={
            "parser_status": "VALID",
            "extracted_text": "EURUSD BUY SL 1.05 TP1 1.07",
            "symbol": "EURUSD",
            "direction": "BUY",
            "initial_stop_loss": 1.05,
            "tp1": 1.07,
            "confidence": "HIGH",
            "engine": "offline",
        },
    )
    assert requests == ["/provider-sources/telegram/extract"]
    assert len(replies) == 1 and "Read from your screenshot" in replies[0]
    assert state["pending_signal_text"] == "EURUSD BUY SL 1.05 TP1 1.07"
    assert len(state["pending_preview_token"]) == 16
    assert not warnings


def check_malformed_pending_confirmation_fails_closed() -> None:
    """Legacy/corrupt pending user state can never be submitted as a signal."""
    replies = []
    calls = []

    async def connected(_update, _scope=None):
        return True

    async def broadcast(*_args, **_kwargs):
        calls.append("create")
        return "created"

    class Query:
        data = "SIGOK:" + ("b" * 16)

        async def answer(self):
            return None

        async def edit_message_text(self, message):
            replies.append(message)

    context = SimpleNamespace(user_data={
        "pending_signal_text": ["bad"], "awaiting_edit": True,
        "pending_preview_token": "b" * 16,
    })
    update = SimpleNamespace(callback_query=Query())
    with (
        patch.object(handlers, "_preview_source_authorised", connected),
        patch.object(handlers, "_create_and_broadcast", broadcast),
    ):
        asyncio.run(handlers.on_signal_preview(update, context))
    assert len(replies) == 1 and "nothing to send" in replies[0].lower()
    assert calls == [], "Malformed user state reached signal creation"
    assert context.user_data == {}, "Malformed confirmation left pending state"


def check_preview_keyboard_token_contract() -> None:
    """Telegram markup must carry matching, short, preview-bound callback data."""
    from keyboards import extract_preview_keyboard

    token = "a" * 16
    keyboard = extract_preview_keyboard(True, token)
    actions = [
        button.callback_data
        for row in keyboard.inline_keyboard
        for button in row
    ]
    assert actions == [f"SIGOK:{token}", f"SIGEDIT:{token}", f"SIGNO:{token}"]
    assert all(len(action.encode("utf-8")) <= 64 for action in actions)
    invalid_keyboard = extract_preview_keyboard(False, token)
    assert [
        button.callback_data
        for row in invalid_keyboard.inline_keyboard
        for button in row
    ] == [f"SIGEDIT:{token}", f"SIGNO:{token}"]
    for bad in ("", "a" * 65, "INVALID"):
        try:
            extract_preview_keyboard(True, bad)
        except ValueError:
            pass
        else:
            raise AssertionError("Unsafe preview identifier accepted")


def check_preview_callback_identity_and_single_use() -> None:
    """Old A button must not act on B text; a valid B confirms only once."""
    calls = []
    replies = []

    async def connected(_update, _scope=None):
        return True

    async def disconnected(_update, _scope=None):
        return False

    async def broadcast(_update, _context, raw_text, **_kwargs):
        calls.append(raw_text)
        return "synthetic-created"

    class Query:
        def __init__(self, data):
            self.data = data
            self.message = SimpleNamespace(text="Offline screenshot preview")

        async def answer(self):
            return None

        async def edit_message_text(self, message):
            replies.append(message)

    token_a, token_b = "a" * 16, "b" * 16
    state = {"pending_signal_text": "B-SIGNAL", "pending_preview_token": token_b}
    context = SimpleNamespace(user_data=state)

    async def click(data, authorised=connected):
        update = SimpleNamespace(callback_query=Query(data))
        with (
            patch.object(handlers, "_preview_source_authorised", authorised),
            patch.object(handlers, "_create_and_broadcast", broadcast),
        ):
            await handlers.on_signal_preview(update, context)

    for data in (
        f"SIGOK:{token_a}", f"SIGEDIT:{token_a}", f"SIGNO:{token_a}",
        "SIGOK", "SIGOK:short", None,
    ):
        replies.clear()
        asyncio.run(click(data))
        assert calls == [], f"Stale/malformed callback attempted creation: {data}"
        assert state == {
            "pending_signal_text": "B-SIGNAL", "pending_preview_token": token_b
        }, f"Stale callback corrupted newer preview: {data}"
        assert len(replies) == 1 and "expired" in replies[0].lower()

    replies.clear()
    asyncio.run(click(f"SIGOK:{token_b}"))
    assert calls == ["B-SIGNAL"]
    assert state == {}, "A completed confirmation left reusable preview state"
    assert "synthetic-created" in replies[-1]
    replies.clear()
    asyncio.run(click(f"SIGOK:{token_b}"))
    assert calls == ["B-SIGNAL"], "Repeated confirmation created duplicate signal"
    assert len(replies) == 1 and "expired" in replies[0].lower()

    state.update({"pending_signal_text": "C-SIGNAL", "pending_preview_token": token_b})
    asyncio.run(click(f"SIGEDIT:{token_b}"))
    assert state.get("awaiting_edit") is True
    assert "C-SIGNAL" in replies[-1]
    asyncio.run(click(f"SIGNO:{token_b}"))
    assert state == {}
    assert calls == ["B-SIGNAL"]

    # A newer preview can arrive while provider verification awaits HTTP.
    # Old confirmation/edit/cancel must recheck identity after the await.
    for old_action in ("SIGOK", "SIGEDIT", "SIGNO"):
        state.clear()
        state.update({"pending_signal_text": "OLD", "pending_preview_token": token_b})
        async def superseded(_update, _scope=None):
            await asyncio.sleep(0)
            state.clear()
            state.update({"pending_signal_text": "NEW", "pending_preview_token": token_a})
            return True

        replies.clear()
        asyncio.run(click(f"{old_action}:{token_b}", authorised=superseded))
        assert state == {"pending_signal_text": "NEW", "pending_preview_token": token_a}
        assert calls == ["B-SIGNAL"]
        assert len(replies) == 1 and "expired" in replies[0].lower()

    # Revocation of the old source must not wipe a newer preview created during I/O.
    state.clear()
    state.update({"pending_signal_text": "OLD", "pending_preview_token": token_b})
    async def revoked_after_supersession(_update, _scope=None):
        await asyncio.sleep(0)
        state.clear()
        state.update({"pending_signal_text": "NEW", "pending_preview_token": token_a})
        return False

    asyncio.run(click(f"SIGOK:{token_b}", authorised=revoked_after_supersession))
    assert state == {"pending_signal_text": "NEW", "pending_preview_token": token_a}
    assert calls == ["B-SIGNAL"]

    state.clear()
    state.update({"pending_signal_text": "D-SIGNAL", "pending_preview_token": token_b})
    asyncio.run(click(f"SIGOK:{token_b}", authorised=disconnected))
    assert state == {}, "Revocation left an old preview confirmable"
    assert calls == ["B-SIGNAL"]


def check_edit_text_bound_to_preview_across_authorisation_await() -> None:
    """Late edit-text requests cannot use or clear a newer preview."""
    async def superseded(allowed: bool, cancelled: bool) -> None:
        entered, release = asyncio.Event(), asyncio.Event()
        calls, replies = [], []
        state = {
            "awaiting_edit": True,
            "pending_signal_text": "OLD",
            "pending_preview_token": "a" * 16,
        }
        context = SimpleNamespace(user_data=state)

        async def reply_text(text, **_kwargs):
            replies.append(text)

        update = SimpleNamespace(message=SimpleNamespace(
            text="OLD BUY SL 1 TP1 2", reply_text=reply_text
        ))

        async def source(_update, _scope=None):
            entered.set()
            await release.wait()
            return allowed

        async def create(_update, _context, raw_text, **_kwargs):
            calls.append(raw_text)
            return "synthetic-only"

        with (
            patch.object(handlers, "_preview_source_authorised", source),
            patch.object(handlers, "_create_and_broadcast", create),
        ):
            older = asyncio.create_task(handlers.on_text(update, context))
            await asyncio.wait_for(entered.wait(), 1)
            # The first text is suspended; screenshot B or Cancel supersedes it.
            state.clear()
            if not cancelled:
                state.update({
                    "pending_signal_text": "NEW",
                    "pending_preview_token": "b" * 16,
                })
            expected = dict(state)
            release.set()
            await asyncio.wait_for(older, 1)
        assert not calls, "Obsolete edit reached signal creation"
        assert state == expected, "Old edit modified a newer/cancelled preview"
        assert not replies

    async def two_edit_messages() -> None:
        both_entered, release = asyncio.Event(), asyncio.Event()
        calls = []
        entered = 0
        state = {
            "awaiting_edit": True,
            "pending_signal_text": "OLD",
            "pending_preview_token": "a" * 16,
        }
        context = SimpleNamespace(user_data=state)

        async def reply_text(_text, **_kwargs):
            return None

        update = SimpleNamespace(message=SimpleNamespace(
            text="EDITED BUY SL 1 TP1 2", reply_text=reply_text
        ))

        async def source(_update, _scope=None):
            nonlocal entered
            entered += 1
            if entered == 2:
                both_entered.set()
            await release.wait()
            return True

        async def create(_update, _context, raw_text, **_kwargs):
            calls.append(raw_text)
            return "synthetic-only"

        with (
            patch.object(handlers, "_preview_source_authorised", source),
            patch.object(handlers, "_create_and_broadcast", create),
        ):
            first = asyncio.create_task(handlers.on_text(update, context))
            second = asyncio.create_task(handlers.on_text(update, context))
            await asyncio.wait_for(both_entered.wait(), 1)
            release.set()
            await asyncio.wait_for(asyncio.gather(first, second), 1)
        assert calls == ["EDITED BUY SL 1 TP1 2"], (
            "Two edits of one preview created duplicate signals"
        )
        assert state == {}, "Completed edit left reusable preview state"

    async def revoked_then_valid() -> None:
        calls, replies = [], []
        state = {
            "awaiting_edit": True,
            "pending_signal_text": "OLD",
            "pending_preview_token": "a" * 16,
        }
        context = SimpleNamespace(user_data=state)

        async def reply_text(text, **_kwargs):
            replies.append(text)

        update = SimpleNamespace(message=SimpleNamespace(
            text="VALID BUY SL 1 TP1 2", reply_text=reply_text
        ))

        async def create(_update, _context, raw_text, **_kwargs):
            calls.append(raw_text)
            return "synthetic-only"

        async def refused(_update, _scope=None):
            return False

        async def allowed(_update, _scope=None):
            return True

        with (
            patch.object(handlers, "_preview_source_authorised", refused),
            patch.object(handlers, "_create_and_broadcast", create),
        ):
            await handlers.on_text(update, context)
        assert state == {}, "Revocation retained an old edit authorization"
        assert not calls

        state.update({
            "awaiting_edit": True,
            "pending_signal_text": "OLD",
            "pending_preview_token": "a" * 16,
        })
        with (
            patch.object(handlers, "_preview_source_authorised", allowed),
            patch.object(handlers, "_create_and_broadcast", create),
        ):
            await handlers.on_text(update, context)
            await handlers.on_text(update, context)
        assert calls == ["VALID BUY SL 1 TP1 2"]
        assert replies == ["synthetic-only"]
        assert state == {}

        state.update({
            "awaiting_edit": True,
            "pending_signal_text": "OLD",
            "pending_preview_token": "\u2603" * 16,
        })
        with (
            patch.object(handlers, "_preview_source_authorised", allowed),
            patch.object(handlers, "_create_and_broadcast", create),
        ):
            await handlers.on_text(update, context)
        assert calls == ["VALID BUY SL 1 TP1 2"]
        assert not state.get("awaiting_edit"), "Invalid preview token allowed editing"

    asyncio.run(superseded(True, False))
    asyncio.run(superseded(False, False))
    asyncio.run(superseded(True, True))
    asyncio.run(two_edit_messages())
    asyncio.run(revoked_then_valid())


def check_provider_source_status_requires_active_typed_binding() -> None:
    """Malformed or revoked status receipts cannot grant hosted screenshot access."""
    assert config.require_license is True
    secret = "OFFLINE-STATUS-PRIVATE-DIAGNOSTIC"
    valid = {
        "binding_id": "BIND-OFFLINE",
        "provider_id": "PROVIDER-OFFLINE",
        "provider_name": "Provider Offline",
        "feed_id": "FEED-OFFLINE",
        "feed_name": "Feed Offline",
        "source_type": "TELEGRAM",
        "status": "ACTIVE",
    }
    invalid = (
        None, [], [{}], {}, {"detail": secret},
        {**valid, "detail": ""},
        {**valid, "status": "REVOKED"},
        {**valid, "source_type": "OTHER"},
        {**valid, "binding_id": None},
        {**valid, "provider_id": 123},
        {**valid, "provider_name": {"debug": secret}},
        {**valid, "feed_name": ""},
    )
    user = SimpleNamespace(id=123456)
    replies = []

    async def reply_text(message, **_kwargs):
        replies.append(message)

    update = SimpleNamespace(
        effective_user=user,
        message=SimpleNamespace(reply_text=reply_text),
    )

    def exercise(response, expected):
        requests = []

        async def status_reply(path, **kwargs):
            requests.append(path)
            assert path == "/provider-sources/telegram/status"
            assert kwargs["params"] == {"telegram_user_id": "123456"}
            assert kwargs["headers"] == handlers._registration_headers()
            return response

        # A stale local provider flag must never rescue bad hosted status.
        with (
            patch.object(handlers, "_backend_get", status_reply),
            patch.object(config, "is_signal_provider", lambda _id: True),
        ):
            receipt = asyncio.run(handlers._provider_source_status(user.id))
            permitted = asyncio.run(handlers._can_submit_provider_signal(update))
            assert bool(receipt) is expected
            assert permitted is expected

            if not expected:
                # The photo path must stop before resolving/download/upload and
                # must also discard an old confirmable screenshot.
                state = {
                    "pending_signal_text": "OLD",
                    "pending_preview_token": "a" * 16,
                    "awaiting_edit": True,
                }
                context = SimpleNamespace(user_data=state, bot=SimpleNamespace())
                asyncio.run(handlers.on_photo(update, context))
                assert state == {}, "Invalid binding preserved old preview"
                assert "Connect this Telegram account" in replies[-1]
                assert secret not in replies[-1]
        assert len(requests) == (2 if expected else 3), requests

    for response in invalid:
        exercise(response, False)
    exercise(valid, True)


def check_hosted_legacy_provider_status_never_grants_identity() -> None:
    """Even a stale local-provider flag cannot claim hosted provider authority."""
    assert config.require_license is True
    replies = []
    calls = []

    async def disconnected(_user_id):
        return None

    async def register(path, **_kwargs):
        calls.append(("POST", path))
        return {
            "id": "USER-OFFLINE", "telegram_user_id": "123456",
            "status": "ACTIVE", "license_key": None,
        }

    async def health(path, **_kwargs):
        calls.append(("GET", path))
        return {"admin_paused": True, "demo_only_mode": True}

    async def reply_text(message, **_kwargs):
        replies.append(message)

    user = SimpleNamespace(
        id=123456, username="offline-only", first_name="Test"
    )
    update = SimpleNamespace(
        effective_user=user,
        message=SimpleNamespace(reply_text=reply_text),
    )
    with (
        patch.object(config, "is_signal_provider", lambda _user_id: True),
        patch.object(config, "is_admin", lambda _user_id: False),
        patch.object(handlers, "_provider_source_status", disconnected),
        patch.object(handlers, "_backend_post", register),
        patch.object(handlers, "_backend_get", health),
    ):
        asyncio.run(handlers.start(update, None))
        asyncio.run(handlers.status(update, None))
        assert handlers._role_name(user.id) == "tester"

    assert calls == [
        ("POST", "/register_user"), ("GET", "/health"),
    ]
    assert len(replies) == 2
    assert "demo tester registered" in replies[0]
    assert "Provider Portal" in replies[0]
    assert "/connectprovider TOKEN" in replies[0]
    assert "screenshot provider ready" not in replies[0].lower()
    assert "Role: tester" in replies[1]
    assert "Provider Portal" in replies[1]
    assert "Role: screenshot provider" not in replies[1]


def check_start_registration_receipt_integrity() -> None:
    """Untrusted /start registration receipts cannot disclose a licence."""
    assert config.require_license is True
    secret = "SYNTHETIC-REGISTRATION-DIAGNOSTIC-NOT-FOR-TELEGRAM"
    licence = "SYNTHETIC-ONE-TIME-EA-LICENCE"
    valid = {
        "id": "USER-OFFLINE", "telegram_user_id": "123456",
        "status": "ACTIVE", "license_key": licence,
    }

    async def disconnected(_user_id):
        return None

    def exercise(response):
        replies, calls = [], []

        async def reply_text(message, **_kwargs):
            replies.append(message)

        async def fake_post(path, **kwargs):
            calls.append(path)
            assert path == "/register_user"
            assert kwargs["json"]["telegram_user_id"] == "123456"
            assert kwargs["headers"] == handlers._registration_headers()
            return response

        update = SimpleNamespace(
            effective_user=SimpleNamespace(
                id=123456, username="offline", first_name="Test"
            ),
            message=SimpleNamespace(reply_text=reply_text),
        )
        with (
            patch.object(handlers, "_provider_source_status", disconnected),
            patch.object(handlers, "_backend_post", fake_post),
        ):
            asyncio.run(handlers.start(update, None))
        assert calls == ["/register_user"]
        assert len(replies) == 1
        return replies[0]

    invalid = (
        None, [], {}, {"detail": secret},
        {**valid, "detail": None},
        {**valid, "telegram_user_id": "OTHER-USER"},
        {**valid, "status": "INACTIVE"},
        {**valid, "id": None}, {**valid, "id": " "},
        {**valid, "license_key": [secret]},
        {**valid, "license_key": {"debug": secret}},
        {**valid, "license_key": "X" * 129},
    )
    for response in invalid:
        reply = exercise(response)
        assert "registration could not be confirmed" in reply.lower()
        assert "demo tester registered" not in reply.lower()
        assert secret not in reply and licence not in reply
        assert "one-time EA licence" not in reply

    reply = exercise(valid)
    assert "demo tester registered" in reply.lower()
    assert licence in reply and "Demo mode only" in reply
    assert "/connectprovider TOKEN" in reply
    reply = exercise({**valid, "license_key": None})
    assert "demo tester registered" in reply.lower()
    assert "one-time EA licence" not in reply


def check_join_invite_backend_response_integrity() -> None:
    """Hosted invite joins require matching identity and active membership receipts."""
    secret = "OFFLINE-SERVER-DETAIL-NOT-FOR-TELEGRAM"
    invite = "OFFLINE-ONE-TIME-INVITE-TOKEN"
    licence = "OFFLINE-ONE-TIME-LICENCE"
    registration = {
        "id": "USER-OFFLINE", "telegram_user_id": "123456",
        "status": "ACTIVE", "license_key": licence,
    }
    acceptance = {
        "subscription_id": "SUB-OFFLINE", "account_id": "ACC-OFFLINE",
        "provider_id": "PROVIDER-OFFLINE", "provider_name": "Test Provider",
        "provider_display_name": None, "feed_id": "FEED-OFFLINE",
        "feed_name": "Test Feed", "status": "ACTIVE",
    }

    def exercise(register_body, accept_body):
        replies, calls = [], []

        async def reply_text(message, **_kwargs):
            replies.append(message)

        async def fake_post(path, **kwargs):
            calls.append(path)
            if path == "/register_user":
                assert kwargs["json"]["telegram_user_id"] == "123456"
                return register_body
            assert path == "/subscriptions/accept"
            assert kwargs["json"] == {
                "invite_token": invite, "telegram_user_id": "123456",
            }
            return accept_body

        update = SimpleNamespace(
            effective_user=SimpleNamespace(
                id=123456, username="offline", first_name="Test"
            ),
            message=SimpleNamespace(reply_text=reply_text),
        )
        with patch.object(handlers, "_backend_post", fake_post):
            asyncio.run(handlers.join_feed(update, SimpleNamespace(args=[invite])))
        assert len(replies) == 1
        return replies[0], calls

    invalid_registrations = (
        None, [], {"detail": {"internal": secret}}, {},
        {**registration, "telegram_user_id": "OTHER-USER"},
        {**registration, "status": "INACTIVE"},
        {**registration, "detail": ""},
        {**registration, "id": None},
    )
    for body in invalid_registrations:
        reply, calls = exercise(body, acceptance)
        assert calls == ["/register_user"], "Bad identity consumed a feed invite"
        assert "nothing was joined" in reply.lower()
        assert secret not in reply and invite not in reply and licence not in reply

    invalid_acceptances = (
        None, [], {"detail": f"token={invite}; {secret}"},
        {"detail": {"trace": secret}}, {},
        {**acceptance, "detail": ""},
        {**acceptance, "status": "PENDING"},
        {**acceptance, "subscription_id": None},
        {**acceptance, "feed_id": []},
        {**acceptance, "feed_name": ""},
    )
    for body in invalid_acceptances:
        reply, calls = exercise(registration, body)
        assert calls == ["/register_user", "/subscriptions/accept"]
        assert not reply.startswith("Joined "), "Unconfirmed join claimed success"
        assert secret not in reply and invite not in reply and licence not in reply
        assert "check feed membership" in reply.lower() or "not confirmed" in reply.lower()

    reply, calls = exercise(registration, acceptance)
    assert calls == ["/register_user", "/subscriptions/accept"]
    assert "Joined Test Provider — Test Feed." in reply
    assert licence in reply and "Demo mode only" in reply
    assert invite not in reply

    reply, _ = exercise(
        {**registration, "license_key": [secret]},
        {**acceptance, "provider_display_name": {"malformed": secret}},
    )
    assert reply.startswith("Joined Test Provider — Test Feed.")
    assert secret not in reply and "one-time EA licence" not in reply


def check_connectprovider_error_does_not_echo_backend_secrets() -> None:
    """Backend error detail is untrusted and cannot enter Telegram replies."""
    secret = "SYNTHETIC_BACKEND_SECRET_DO_NOT_ECHO"
    replies = []
    calls = []

    async def reply_text(message, **_kwargs):
        replies.append(message)

    async def failed_connection(path, **kwargs):
        calls.append((path, kwargs.get("json", {}).get("connection_token")))
        return {"detail": f"internal token dump: {secret}"}

    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=123456),
        message=SimpleNamespace(reply_text=reply_text),
    )
    context = SimpleNamespace(args=["SYNTHETIC-ONE-TIME-TOKEN"])
    with patch.object(handlers, "_backend_post", failed_connection):
        asyncio.run(handlers.connect_provider_source(update, context))
    assert calls == [
        ("/provider-sources/telegram/connect", "SYNTHETIC-ONE-TIME-TOKEN")
    ]
    assert len(replies) == 1
    assert "connection could not be confirmed" in replies[0].lower()
    assert "Provider Portal" in replies[0]
    assert secret not in replies[0]
    assert "SYNTHETIC-ONE-TIME-TOKEN" not in replies[0]

def check_connectprovider_success_receipt_integrity() -> None:
    """Connection claims require a typed, ACTIVE Telegram binding response."""
    secret = "OFFLINE-SOURCE-CONNECTION-PRIVATE-DIAGNOSTIC"
    token = "OFFLINE-ONE-TIME-SOURCE-TOKEN"
    valid = {
        "binding_id": "BIND-OFFLINE", "provider_id": "PROVIDER-OFFLINE",
        "provider_name": "Provider Offline", "provider_display_name": None,
        "feed_id": "FEED-OFFLINE", "feed_name": "Feed Offline",
        "source_type": "TELEGRAM", "status": "ACTIVE",
    }

    def exercise(response):
        replies, paths = [], []

        async def reply_text(message, **_kwargs):
            replies.append(message)

        async def fake_post(path, **kwargs):
            paths.append(path)
            assert kwargs["json"] == {
                "connection_token": token, "telegram_user_id": "123456",
            }
            return response

        update = SimpleNamespace(
            effective_user=SimpleNamespace(id=123456),
            message=SimpleNamespace(reply_text=reply_text),
        )
        with patch.object(handlers, "_backend_post", fake_post):
            asyncio.run(
                handlers.connect_provider_source(
                    update, SimpleNamespace(args=[token])
                )
            )
        assert paths == ["/provider-sources/telegram/connect"]
        assert len(replies) == 1
        return replies[0]

    negatives = (
        None, [], {}, {"detail": {"error": secret}},
        {**valid, "detail": ""}, {**valid, "status": "REVOKED"},
        {**valid, "source_type": "UNKNOWN"},
        {**valid, "binding_id": None}, {**valid, "feed_id": ""},
        {**valid, "provider_name": 45},
    )
    for value in negatives:
        reply = exercise(value)
        assert "connection could not be confirmed" in reply.lower()
        assert "source connected to" not in reply.lower()
        assert secret not in reply and token not in reply
        assert "Provider Portal" in reply

    reply = exercise(valid)
    assert "Provider source connected to Provider Offline — Feed Offline." in reply
    assert "Demo mode only" in reply
    assert token not in reply
    reply = exercise({**valid, "provider_display_name": { "detail": secret }})
    assert "Provider source connected to Provider Offline — Feed Offline." in reply
    assert secret not in reply


def check_telegram_httpx_token_log_privacy() -> None:
    """Synthetic Bot API URLs must not reach HTTPX INFO transport logs."""
    import io
    import logging

    marker = "123456789:OFFLINE_HTTPX_TOKEN_LOG_PROBE"
    captured = io.StringIO()
    recorder = logging.StreamHandler(captured)
    recorder.setLevel(logging.INFO)
    transport_logger = logging.getLogger("httpx")
    original_level = transport_logger.level
    original_propagate = transport_logger.propagate

    def mock_telegram_request() -> None:
        transport = httpx.MockTransport(
            lambda _request: httpx.Response(200, json={"ok": True})
        )
        with httpx.Client(transport=transport) as client:
            response = client.post(f"https://api.telegram.org/bot{marker}/getMe")
            assert response.status_code == 200

    # Capture in isolation: never print the synthetic token to normal CI logs.
    transport_logger.addHandler(recorder)
    transport_logger.propagate = False
    try:
        # Negative control: an INFO-level HTTPX logger reveals the URL token.
        transport_logger.setLevel(logging.INFO)
        mock_telegram_request()
        assert marker in captured.getvalue(), "HTTPX leak control did not reproduce"
        captured.seek(0)
        captured.truncate(0)

        # Restore actual bot transport logging and verify the leak is blocked.
        transport_logger.setLevel(original_level)
        mock_telegram_request()
        assert marker not in captured.getvalue(), "Bot token reached HTTPX INFO logs"
        assert original_level >= logging.WARNING, "HTTPX transport INFO logging enabled"
        assert logging.getLogger("httpcore").getEffectiveLevel() >= logging.WARNING
    finally:
        transport_logger.removeHandler(recorder)
        transport_logger.propagate = original_propagate
        transport_logger.setLevel(original_level)


def check_screenshot_upload_size_guard() -> None:
    """Telegram image metadata and actual bytes cannot bypass the backend limit."""
    assert handlers.MAX_SIGNAL_IMAGE_BYTES == 5 * 1024 * 1024

    async def permitted(_update):
        return True

    async def exercise(kind, size, contents, resolved_file_size=None):
        requests, previews, replies = [], [], []
        state = {
            "pending_signal_text": "OLD-PREVIEW",
            "pending_preview_token": "a" * 16,
            "awaiting_edit": True,
        }

        async def reply_text(message, **_kwargs):
            replies.append(message)

        async def download_as_bytearray():
            requests.append("download")
            return bytearray(contents)

        class OfflineBot:
            async def get_file(self, _file_id):
                requests.append("get_file")
                return SimpleNamespace(
                    file_size=resolved_file_size,
                    download_as_bytearray=download_as_bytearray,
                )

        async def preview(**kwargs):
            assert handlers._is_current_screenshot_attempt(
                kwargs["context"], kwargs["attempt_token"]
            ), "Photo/document preview has lost its attempt identity"
            # Mirror the real preview's transition to a confirmable callback.
            kwargs["context"].user_data.pop("active_screenshot_attempt", None)
            previews.append((kwargs["image_bytes"], kwargs["mime"]))

        asset = SimpleNamespace(file_id="OFFLINE", file_size=size, mime_type="image/png")
        message = SimpleNamespace(
            reply_text=reply_text,
            photo=[asset],
            document=asset,
        )
        update = SimpleNamespace(message=message, effective_user=SimpleNamespace(id=123))
        context = SimpleNamespace(user_data=state, bot=OfflineBot())
        with (
            patch.object(handlers, "_can_submit_provider_signal", permitted),
            patch.object(handlers, "_preview_screenshot", preview),
            patch.object(handlers, "MAX_SIGNAL_IMAGE_BYTES", 4),
        ):
            await (handlers.on_photo if kind == "photo" else handlers.on_document)(
                update, context
            )
        return requests, previews, replies, state

    for kind in ("photo", "document"):
        # Oversized or invalid Telegram metadata must stop BEFORE get_file.
        for reported_size in (5, -1, "5", True):
            requests, previews, replies, state = asyncio.run(
                exercise(kind, reported_size, b"abc")
            )
            assert not requests and not previews, (kind, reported_size)
            assert "no preview" in replies[-1].lower()
            assert state == {}, "Old confirmable screenshot survived rejection"

        # A second oversized/invalid File metadata claim must stop the
        # download even if the original message reports an allowed size.
        for reported_size in (None, 3):
            for resolved_size in (5, -1, "5", True):
                requests, previews, replies, state = asyncio.run(
                    exercise(kind, reported_size, b"abc", resolved_size)
                )
                assert requests == ["get_file"], (kind, reported_size, resolved_size)
                assert not previews
                assert "no preview" in replies[-1].lower()
                assert state == {}

        # Actual oversized bytes remain authoritative despite two small claims.
        requests, previews, replies, state = asyncio.run(
            exercise(kind, 3, b"abcde", 3)
        )
        assert requests == ["get_file", "download"]
        assert not previews and state == {}
        assert "no preview" in replies[-1].lower()

        # A missing/small claimed size cannot authorize an oversized download.
        for reported_size in (None, 3):
            requests, previews, replies, state = asyncio.run(
                exercise(kind, reported_size, b"abcde")
            )
            assert requests == ["get_file", "download"], (kind, reported_size)
            assert not previews
            assert "no preview" in replies[-1].lower()
            assert state == {}

        # Exact-limit images still reach preview, but no external call occurs.
        requests, previews, replies, state = asyncio.run(
            exercise(kind, 4, b"abcd", 4)
        )
        assert requests == ["get_file", "download"]
        assert previews == [(b"abcd", "image/jpeg" if kind == "photo" else "image/png")]
        assert not state, "New screenshot must invalidate prior pending tokens"

        # Even with both size metadata sources absent, the byte boundary holds.
        requests, previews, replies, state = asyncio.run(
            exercise(kind, None, b"abcd", None)
        )
        assert requests == ["get_file", "download"]
        assert previews == [(b"abcd", "image/jpeg" if kind == "photo" else "image/png")]
        assert not state


def check_telegram_download_transport_failures_fail_closed() -> None:
    """No token-bearing exception escapes; older failed uploads cannot erase newer previews."""
    secret = "OFFLINE-TELEGRAM-TOKEN-NOT-FOR-LOGS"

    async def permitted(_update):
        return True

    async def failure(kind: str, stage: str) -> None:
        warnings, replies, previews = [], [], []
        state = {
            "pending_signal_text": "PREVIOUS",
            "pending_preview_token": "a" * 16,
            "awaiting_edit": True,
        }

        async def reply_text(message, **_kwargs):
            replies.append(message)

        class Bot:
            async def get_file(self, _file_id):
                if stage == "get_file":
                    raise RuntimeError(
                        f"https://api.telegram.org/bot{secret}/getFile"
                    )

                async def download_as_bytearray():
                    raise ValueError(
                        f"https://api.telegram.org/bot{secret}/download"
                    )

                return SimpleNamespace(
                    file_size=3, download_as_bytearray=download_as_bytearray
                )

        async def preview(**_kwargs):
            previews.append("SHOULD-NOT-HAPPEN")

        asset = SimpleNamespace(file_id="FAKE", file_size=3, mime_type="image/png")
        update = SimpleNamespace(
            effective_user=SimpleNamespace(id=12345),
            message=SimpleNamespace(
                photo=[asset], document=asset, reply_text=reply_text,
            ),
        )
        context = SimpleNamespace(user_data=state, bot=Bot())
        with (
            patch.object(handlers, "_can_submit_provider_signal", permitted),
            patch.object(handlers, "_preview_screenshot", preview),
            patch.object(
                handlers.logger, "warning",
                lambda fmt, *args: warnings.append(fmt % args),
            ),
        ):
            await (handlers.on_photo if kind == "photo" else handlers.on_document)(
                update, context
            )
        expected_type = "RuntimeError" if stage == "get_file" else "ValueError"
        assert warnings == [
            f"Telegram screenshot download failed: {expected_type}"
        ], (kind, stage, warnings)
        assert not previews and state == {}, "Failed upload retained confirmation state"
        assert any("couldn't be retrieved" in text for text in replies), replies
        assert all(secret not in text for text in replies + warnings)

    async def stale_failure(kind: str) -> None:
        entered, release = asyncio.Event(), asyncio.Event()
        warnings, replies, previews = [], [], []
        state = {}

        async def reply_text(message, **_kwargs):
            replies.append(message)

        class Bot:
            async def get_file(self, file_id):
                if file_id == "OLD":
                    entered.set()
                    await release.wait()
                    raise RuntimeError(secret)

                async def download_as_bytearray():
                    return bytearray(b"NEW")

                return SimpleNamespace(
                    file_size=3, download_as_bytearray=download_as_bytearray
                )

        async def preview(**kwargs):
            previews.append(kwargs["image_bytes"])
            assert handlers._is_current_screenshot_attempt(
                kwargs["context"], kwargs["attempt_token"]
            )
            state.pop("active_screenshot_attempt", None)
            state["pending_signal_text"] = "NEW"
            state["pending_preview_token"] = "b" * 16

        def make_update(file_id):
            asset = SimpleNamespace(
                file_id=file_id, file_size=3, mime_type="image/png"
            )
            return SimpleNamespace(
                effective_user=SimpleNamespace(id=12345),
                message=SimpleNamespace(
                    photo=[asset], document=asset, reply_text=reply_text,
                ),
            )

        context = SimpleNamespace(user_data=state, bot=Bot())
        handler = handlers.on_photo if kind == "photo" else handlers.on_document
        with (
            patch.object(handlers, "_can_submit_provider_signal", permitted),
            patch.object(handlers, "_preview_screenshot", preview),
            patch.object(
                handlers.logger, "warning",
                lambda fmt, *args: warnings.append(fmt % args),
            ),
        ):
            older = asyncio.create_task(handler(make_update("OLD"), context))
            await asyncio.wait_for(entered.wait(), 1)
            await handler(make_update("NEW"), context)
            release.set()
            await asyncio.wait_for(older, 1)

        assert previews == [b"NEW"]
        assert state == {
            "pending_signal_text": "NEW", "pending_preview_token": "b" * 16
        }, "Late download failure erased newer preview"
        assert not warnings, "A stale failed upload emitted sensitive logs"
        assert all(secret not in text for text in replies)

    for kind in ("photo", "document"):
        for stage in ("get_file", "download"):
            asyncio.run(failure(kind, stage))
        asyncio.run(stale_failure(kind))



def check_overlapping_screenshot_attempts_fail_closed() -> None:
    """A delayed older screenshot cannot overwrite a newer preview."""
    async def permitted(_update):
        return True

    async def exercise_delayed_get_file(kind: str):
        requests, previews, replies = [], [], []
        entered, release = asyncio.Event(), asyncio.Event()
        state = {"pending_signal_text": "OLD", "pending_preview_token": "0" * 16}

        async def reply_text(text, **_kwargs):
            replies.append(text)

        class Bot:
            async def get_file(self, file_id):
                requests.append(("get_file", file_id))
                if file_id == "OLDER":
                    entered.set()
                    await release.wait()

                async def download():
                    requests.append(("download", file_id))
                    return bytearray(b"BBB" if file_id == "NEWER" else b"AAA")

                return SimpleNamespace(file_size=3, download_as_bytearray=download)

        def make_update(file_id):
            asset = SimpleNamespace(
                file_id=file_id, file_size=3, mime_type="image/png"
            )
            return SimpleNamespace(
                effective_user=SimpleNamespace(id=12345),
                message=SimpleNamespace(
                    photo=[asset], document=asset, reply_text=reply_text,
                ),
            )

        async def preview(**kwargs):
            assert handlers._is_current_screenshot_attempt(
                kwargs["context"], kwargs["attempt_token"]
            ), "Stale file created a preview"
            previews.append(kwargs["image_bytes"])
            state["pending_signal_text"] = kwargs["image_bytes"].decode()
            state["pending_preview_token"] = "b" * 16
            state.pop("active_screenshot_attempt", None)

        context = SimpleNamespace(user_data=state, bot=Bot())
        handler = handlers.on_photo if kind == "photo" else handlers.on_document
        with (
            patch.object(handlers, "_can_submit_provider_signal", permitted),
            patch.object(handlers, "_preview_screenshot", preview),
        ):
            older = asyncio.create_task(handler(make_update("OLDER"), context))
            await asyncio.wait_for(entered.wait(), 1)
            await handler(make_update("NEWER"), context)
            assert previews == [b"BBB"], (kind, previews)
            assert state["pending_signal_text"] == "BBB"
            release.set()
            await asyncio.wait_for(older, 1)
        assert previews == [b"BBB"], "Late older file reached preview"
        assert ("download", "OLDER") not in requests, "Late file was downloaded"
        assert state["pending_preview_token"] == "b" * 16
        assert state["pending_signal_text"] == "BBB"

    async def exercise_delayed_extraction():
        entered, release = asyncio.Event(), asyncio.Event()
        requests, replies = [], []
        state = {}
        context = SimpleNamespace(user_data=state)

        async def source(_user_id):
            if asyncio.current_task().get_name() == "old-extraction":
                entered.set()
                await release.wait()
            return {"feed_id": "OFFLINE"}

        async def reply_text(text, **_kwargs):
            replies.append(text)

        update = SimpleNamespace(
            effective_user=SimpleNamespace(id=12345),
            message=SimpleNamespace(reply_text=reply_text),
        )
        original_client = httpx.AsyncClient

        def respond(request):
            requests.append(request.url.path)
            return httpx.Response(
                200, json={
                    "parser_status": "VALID",
                    "extracted_text": "NEWER BUY SL 1 TP1 2",
                },
            )

        transport = httpx.MockTransport(respond)
        with (
            patch.object(handlers, "_provider_source_status", source),
            patch.object(
                handlers.httpx,
                "AsyncClient",
                lambda *args, **kwargs: original_client(
                    *args, transport=transport, **kwargs
                ),
            ),
        ):
            old_token = handlers._begin_screenshot_attempt(context)
            older = asyncio.create_task(
                handlers._preview_screenshot(
                    update, context, b"OLDER", "image/jpeg", old_token
                ),
                name="old-extraction",
            )
            await asyncio.wait_for(entered.wait(), 1)
            new_token = handlers._begin_screenshot_attempt(context)
            await handlers._preview_screenshot(
                update, context, b"NEWER", "image/jpeg", new_token
            )
            assert state["pending_signal_text"] == "NEWER BUY SL 1 TP1 2"
            preview_nonce = state["pending_preview_token"]
            release.set()
            await asyncio.wait_for(older, 1)
        assert requests == ["/provider-sources/telegram/extract"]
        assert state["pending_signal_text"] == "NEWER BUY SL 1 TP1 2"
        assert state["pending_preview_token"] == preview_nonce
        assert len(replies) == 1 and "Read from your screenshot" in replies[0]

    for kind in ("photo", "document"):
        asyncio.run(exercise_delayed_get_file(kind))
    asyncio.run(exercise_delayed_extraction())




def check_broadcast_recipient_feed_binding() -> None:
    """A source rebind cannot send feed A's signal to feed B's recipients."""
    source = {
        "binding_id": "BINDING-A",
        "provider_id": "PROVIDER-A",
        "feed_id": "FEED-A",
        "expiry_minutes": 5,
    }
    signal = {
        "id": "SIG-0123456789ABCDEF",
        "parser_status": "VALID", "status": "VALID",
        "provider_id": "PROVIDER-A",
        "feed_id": "FEED-A",
        "source": "FEED:FEED-A:TELEGRAM_BINDING:BINDING-A",
    }
    valid = {
        "binding_id": "BINDING-A",
        "provider_id": "PROVIDER-A",
        "feed_id": "FEED-A",
        "recipients": [{"telegram_user_id": "900000000011"}],
    }
    sent = []
    lookups = []

    async def source_status(_user_id):
        return source

    async def post(_path, **_kwargs):
        return response_signal

    async def get(path, **_kwargs):
        assert path == "/provider-sources/telegram/recipients"
        lookups.append(path)
        return response_recipients

    class OfflineBot:
        async def send_message(self, **kwargs):
            sent.append(kwargs["chat_id"])

    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=123456),
        effective_chat=SimpleNamespace(id=123456),
        effective_message=SimpleNamespace(message_id=97),
    )
    context = SimpleNamespace(bot=OfflineBot())
    bad = (
        # An HTTP 200 error payload must not authorise a broadcast merely by
        # echoing valid binding metadata and a recipient list.
        dict(valid, detail="revoked despite matching identifiers"),
        dict(valid, detail=None),
        dict(valid, binding_id="BINDING-B"),
        dict(valid, provider_id="PROVIDER-B"),
        dict(valid, feed_id="FEED-B"),
        {"recipients": valid["recipients"]},
        {"detail": "backend error", **{"recipients": valid["recipients"]}},
        {"binding_id": "BINDING-A", "provider_id": "PROVIDER-A",
         "feed_id": "FEED-A", "recipients": ["900000000011"]},
        dict(valid, recipients=[{"telegram_user_id": "900000000011"},
                                {"telegram_user_id": "not-a-chat-id"}]),
        ["malformed", "body"],
        None,
    )
    # Even a valid subscriber first in the list must receive NO card if a
    # later target is a negative group/channel ID, zero, noncanonical,
    # over-52-bit or non-string identity.
    bad += tuple(
        dict(valid, recipients=[
            {"telegram_user_id": "900000000011"},
            {"telegram_user_id": malformed},
        ])
        for malformed in (
            "-1001234567890", "0", "0900000000011",
            "4503599627370496", "9999999999999999999",
            900000000011,
        )
    )
    with (
        patch.object(handlers, "_provider_source_status", source_status),
        patch.object(handlers, "_backend_post", post),
        patch.object(handlers, "_backend_get", get),
        patch("keyboards.format_trade_card", lambda *_args: "OFFLINE-TRADE-CARD"),
        patch("keyboards.trade_card_keyboard", lambda *_args: "OFFLINE-BUTTONS"),
    ):
        response_signal = signal
        response_recipients = valid
        result = asyncio.run(
            handlers._create_and_broadcast(update, context, "XAUUSD BUY SL 1 TP1 2")
        )
        assert "sent to 1 subscriber" in result.lower()
        assert sent == ["900000000011"]
        for payload in bad:
            sent.clear()
            response_recipients = payload
            result = asyncio.run(
                handlers._create_and_broadcast(update, context, "XAUUSD BUY SL 1 TP1 2")
            )
            assert not sent, "Mismatched/malformed feed receipt sent a card"
            assert "no subscriber card was sent" in result.lower()
        # A malformed backend signal ID must never become a Telegram
        # callback URL or reach the recipient-lookup/broadcast stage.
        for bad_id in (
            None, "", "SIG-TEST/../../admin/status", "SIG-TEST?next=1",
            "SIG-TEST%2Fbad", "SIG-Ａ", "SIG-" + "A" * 33,
        ):
            sent.clear()
            before = len(lookups)
            response_signal = dict(signal, id=bad_id)
            response_recipients = valid
            result = asyncio.run(
                handlers._create_and_broadcast(update, context, "XAUUSD BUY SL 1 TP1 2")
            )
            assert not sent and len(lookups) == before, bad_id
            assert "could not be confirmed" in result.lower(), bad_id
        response_signal = signal
        # A rebind between initial provider status and signal creation must
        # also refuse before ANY recipient lookup.
        sent.clear()
        before = len(lookups)
        response_signal = dict(signal, provider_id="PROVIDER-B")
        response_recipients = valid
        result = asyncio.run(
            handlers._create_and_broadcast(update, context, "XAUUSD BUY SL 1 TP1 2")
        )
        assert not sent and len(lookups) == before
        assert "no subscriber card was sent" in result.lower()
        response_signal = dict(signal, source="FEED:FEED-B:TELEGRAM_BINDING:BINDING-A")
        result = asyncio.run(
            handlers._create_and_broadcast(update, context, "XAUUSD BUY SL 1 TP1 2")
        )
        assert not sent and len(lookups) == before
        assert "no subscriber card was sent" in result.lower()


def check_broadcast_failure_logs_are_private() -> None:
    """Synthetic Telegram send failures do not leak recipients or token-bearing errors."""
    failed_chat = "900000000001"
    good_chat = "900000000002"
    secret = "OFFLINE-TELEGRAM-BOT-TOKEN-NOT-FOR-LOGS"
    warnings = []
    sends = []

    async def source_status(_user_id):
        return {
            "binding_id": "BINDING-OFFLINE",
            "provider_id": "PROVIDER-OFFLINE",
            "feed_id": "FEED-OFFLINE",
            "expiry_minutes": 5,
        }

    async def backend_post(path, **kwargs):
        assert path == "/provider-sources/telegram/signals"
        assert kwargs["json"]["raw_text"] == "XAUUSD BUY SL 1 TP1 2"
        return {
            "id": "SIG-OFFLINE",
            "parser_status": "VALID", "status": "VALID",
            "provider_id": "PROVIDER-OFFLINE",
            "feed_id": "FEED-OFFLINE",
            "source": "FEED:FEED-OFFLINE:TELEGRAM_BINDING:BINDING-OFFLINE",
        }

    async def recipients(_update, source, signal=None):
        assert source["feed_id"] == "FEED-OFFLINE"
        assert signal["feed_id"] == "FEED-OFFLINE"
        return [failed_chat, good_chat]

    class OfflineBot:
        async def send_message(self, **kwargs):
            sends.append(kwargs["chat_id"])
            if kwargs["chat_id"] == failed_chat:
                raise RuntimeError(
                    f"https://api.telegram.org/bot{secret}/sendMessage?"
                    f"chat_id={failed_chat}"
                )

    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=123456),
        effective_chat=SimpleNamespace(id=123456),
        effective_message=SimpleNamespace(message_id=99),
    )
    context = SimpleNamespace(bot=OfflineBot())
    with (
        patch.object(handlers, "_provider_source_status", source_status),
        patch.object(handlers, "_backend_post", backend_post),
        patch.object(handlers, "_active_recipients", recipients),
        patch.object(
            handlers.logger,
            "warning",
            lambda fmt, *args: warnings.append(fmt % args),
        ),
        patch("keyboards.format_trade_card", lambda *_args: "OFFLINE-TRADE-CARD"),
        patch("keyboards.trade_card_keyboard", lambda *_args: "OFFLINE-BUTTONS"),
    ):
        summary = asyncio.run(
            handlers._create_and_broadcast(update, context, "XAUUSD BUY SL 1 TP1 2")
        )

    assert sends == [failed_chat, good_chat], "One failed send stopped the next recipient"
    assert summary == "Signal SIG-OFFLINE created and card sent to 1 subscriber(s)."
    assert warnings == ["send card failed: RuntimeError"], (
        "A transport error leaked Telegram recipient or exception details"
    )
    assert all(secret not in item for item in warnings)
    assert all(failed_chat not in item and good_chat not in item for item in warnings)


def check_signal_create_backend_errors_remain_private() -> None:
    """Provider creation failures must not echo backend secrets or send cards."""
    secret = "SYNTHETIC-CREATE-RESPONSE-SECRET-NOT-FOR-TELEGRAM"
    received = []

    async def source_status(_user_id):
        return {"binding_id": "BINDING-OFFLINE", "provider_id": "PROVIDER-OFFLINE",
                "feed_id": "FEED-OFFLINE", "expiry_minutes": 5}

    async def forbidden_recipients(_update, _source):
        raise AssertionError("Malformed creation reached recipient lookup")

    class OfflineBot:
        async def send_message(self, **_kwargs):
            raise AssertionError("Malformed creation broadcast a card")

    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=123456),
        effective_chat=SimpleNamespace(id=123456),
        effective_message=SimpleNamespace(message_id=98),
    )
    context = SimpleNamespace(bot=OfflineBot())
    # An HTTP 200 with a valid-looking signal and even a falsy `detail`
    # field is an ambiguous/error-shaped response, never card authority.
    valid_signal = {
        "id": "SIG-OFFLINE", "parser_status": "VALID", "status": "VALID",
        "provider_id": "PROVIDER-OFFLINE", "feed_id": "FEED-OFFLINE",
        "source": "FEED:FEED-OFFLINE:TELEGRAM_BINDING:BINDING-OFFLINE",
    }
    cases = (
        # A duplicate source message can return an older, now-expired signal.
        # A VALID parser status must not override the persisted signal state.
        ({**valid_signal, "status": "EXPIRED"}, "not in a broadcastable state"),
        ({**valid_signal, "status": "REJECTED"}, "not in a broadcastable state"),
        ({**valid_signal, "status": None}, "not in a broadcastable state"),
        ({**valid_signal, "status": ["VALID"]}, "not in a broadcastable state"),
        ({k: v for k, v in valid_signal.items() if k != "status"},
         "not in a broadcastable state"),
        ({**valid_signal, "detail": None}, "could not be confirmed"),
        ({**valid_signal, "detail": ""}, "could not be confirmed"),
        ({**valid_signal, "detail": []}, "could not be confirmed"),
        ({"detail": f"internal token={secret}"}, "could not be confirmed"),
        ({"detail": {"trace": secret}}, "could not be confirmed"),
        ({"parser_status": "REJECTED", "parser_error": secret}, "did not accept"),
        (None, "could not be confirmed"),
        (["unexpected", secret], "could not be confirmed"),
        ({"parser_status": "VALID", "status": "VALID"}, "could not be confirmed"),
        ({"parser_status": "VALID", "status": "VALID", "id": [secret]}, "could not be confirmed"),
    )

    async def fake_post(path, **kwargs):
        assert path == "/provider-sources/telegram/signals"
        assert kwargs["json"]["raw_text"] == "XAUUSD BUY SL 1 TP1 2"
        received.append(path)
        return current_response

    with (
        patch.object(handlers, "_provider_source_status", source_status),
        patch.object(handlers, "_backend_post", fake_post),
        patch.object(handlers, "_active_recipients", forbidden_recipients),
    ):
        for current_response, expected in cases:
            summary = asyncio.run(
                handlers._create_and_broadcast(update, context, "XAUUSD BUY SL 1 TP1 2")
            )
            assert expected in summary.lower(), "Creation response was not safely rejected"
            assert "no subscriber card was sent" in summary.lower()
            assert secret not in summary, "Untrusted error leaked into Telegram reply"
            assert "created and card sent" not in summary.lower()
    assert received == ["/provider-sources/telegram/signals"] * len(cases)



def check_preview_source_rebind_blocks_confirmation() -> None:
    """A screenshot preview for feed A cannot be confirmed/edited into feed B."""
    assert config.require_license is True
    source_a = {
        "binding_id": "BINDING-A", "provider_id": "PROVIDER-A",
        "provider_name": "Provider A", "feed_id": "FEED-A",
        "feed_name": "Feed A", "source_type": "TELEGRAM", "status": "ACTIVE",
    }
    # Real backend rebinding reuses the binding ID; feed/provider still change.
    source_b = {
        "binding_id": "BINDING-A", "provider_id": "PROVIDER-B",
        "provider_name": "Provider B", "feed_id": "FEED-B",
        "feed_name": "Feed B", "source_type": "TELEGRAM", "status": "ACTIVE",
    }
    extracted = {
        "parser_status": "VALID", "extracted_text": "EURUSD BUY SL 1.05 TP1 1.07",
        "symbol": "EURUSD", "direction": "BUY", "initial_stop_loss": 1.05,
        "tp1": 1.07, "confidence": "HIGH", "engine": "offline",
    }
    original_client = httpx.AsyncClient
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(200, json=extracted)
    )

    async def exercise() -> None:
        source = dict(source_a)
        response_override = None
        source_reads = 0
        backend_calls, sends, replies = [], [], []
        state = {}

        async def source_status(_user_id):
            nonlocal source_reads
            source_reads += 1
            if response_override == "rebind-during-confirm" and source_reads >= 2:
                return dict(source_b)
            return dict(source)

        async def fake_post(path, **kwargs):
            backend_calls.append(("POST", path))
            assert path == "/provider-sources/telegram/signals"
            assert kwargs["json"]["raw_text"] in (
                extracted["extracted_text"], "EURUSD SELL SL 1.05 TP1 1.04",
            )
            return {
                "id": "SIG-A", "parser_status": "VALID", "status": "VALID",
                "provider_id": "PROVIDER-A", "feed_id": "FEED-A",
                "source": "FEED:FEED-A:TELEGRAM_BINDING:BINDING-A",
            }

        async def fake_get(path, **_kwargs):
            backend_calls.append(("GET", path))
            assert path == "/provider-sources/telegram/recipients"
            return {
                "binding_id": "BINDING-A", "provider_id": "PROVIDER-A",
                "feed_id": "FEED-A",
                "recipients": [{"telegram_user_id": "900000000011"}],
            }

        async def reply_text(text, **_kwargs):
            replies.append(text)

        class Bot:
            async def send_message(self, **kwargs):
                sends.append(kwargs["chat_id"])

        class Query:
            def __init__(self, action, token):
                self.data = f"{action}:{token}"
                self.message = SimpleNamespace(text="OFFLINE-PREVIEW")

            async def answer(self):
                return None

            async def edit_message_text(self, text):
                replies.append(text)

        message = SimpleNamespace(
            text="EURUSD SELL SL 1.05 TP1 1.04",
            message_id=100,
            reply_text=reply_text,
        )
        update = SimpleNamespace(
            message=message,
            effective_user=SimpleNamespace(id=123456),
            effective_chat=SimpleNamespace(id=123456),
            effective_message=message,
        )
        context = SimpleNamespace(user_data=state, bot=Bot())

        async def preview():
            await handlers._preview_screenshot(
                update, context, b"OFFLINE-IMAGE", "image/jpeg"
            )
            assert state["pending_signal_text"] == extracted["extracted_text"]
            assert state["pending_provider_source_scope"] == {
                "binding_id": "BINDING-A", "provider_id": "PROVIDER-A",
                "feed_id": "FEED-A",
            }
            return state["pending_preview_token"]

        async def click(action, token):
            query_update = SimpleNamespace(
                callback_query=Query(action, token),
                effective_user=update.effective_user,
                effective_chat=update.effective_chat,
                effective_message=message,
            )
            await handlers.on_signal_preview(query_update, context)

        with (
            patch.object(handlers, "_provider_source_status", source_status),
            patch.object(handlers, "_backend_post", fake_post),
            patch.object(handlers, "_backend_get", fake_get),
            patch.object(
                handlers.httpx, "AsyncClient",
                lambda *args, **kwargs: original_client(
                    *args, transport=transport, **kwargs
                ),
            ),
            patch("keyboards.format_trade_card", lambda *_args: "OFFLINE-CARD"),
            patch("keyboards.trade_card_keyboard", lambda *_args: "OFFLINE-BUTTONS"),
        ):
            token = await preview()
            source.update(source_b)
            await click("SIGOK", token)
            assert not backend_calls and not sends
            assert state == {}, "Rebound Confirm left a reusable preview"
            assert "nothing was sent" in replies[-1].lower()

            source = dict(source_a)
            token = await preview()
            await click("SIGEDIT", token)
            assert state.get("awaiting_edit") is True
            source.update(source_b)
            await handlers.on_text(update, context)
            assert not backend_calls and not sends
            assert state == {}, "Rebound edit left reusable source authority"

            # Source A remains valid through the first callback read, but is
            # rebound immediately before the second pre-create status read.
            source = dict(source_a)
            token = await preview()
            response_override = "rebind-during-confirm"
            source_reads = 0
            await click("SIGOK", token)
            assert source_reads >= 2, "Missing pre-create source recheck"
            assert not backend_calls and not sends
            assert "nothing was submitted or sent" in replies[-1].lower()
            assert state == {}
            response_override = None

            # A matching unmodified source remains a valid offline preview.
            source = dict(source_a)
            token = await preview()
            await click("SIGOK", token)
            assert backend_calls == [
                ("POST", "/provider-sources/telegram/signals"),
                ("GET", "/provider-sources/telegram/recipients"),
            ]
            assert sends == ["900000000011"] and state == {}
            assert "sent to 1 subscriber" in replies[-1].lower()

            # A pre-upgrade hosted preview with no scope snapshot is invalid.
            state.update({
                "pending_signal_text": extracted["extracted_text"],
                "pending_preview_token": "a" * 16,
            })
            backend_calls.clear()
            sends.clear()
            await click("SIGOK", "a" * 16)
            assert not backend_calls and not sends and state == {}
            assert "nothing was sent" in replies[-1].lower()

    asyncio.run(exercise())


def main() -> int:
    assert config.require_license is True, "Hosted-mode test failed to set boundary"
    app = build_application()  # Builder only: no initialize()/run_polling()/network

    all_handlers = [item for group in app.handlers.values() for item in group]
    commands = set()
    for handler in all_handlers:
        if isinstance(handler, CommandHandler):
            commands.update(handler.commands)

    mandatory = {
        "start", "join", "connectprovider", "status", "settings",
        "screenshothelp", "testsignal", "pause", "resume", "users",
        "lastsignals", "lastcommands",
    }
    missing = mandatory - commands
    assert not missing, f"Required hosted commands missing: {sorted(missing)}"
    assert "provider" not in commands, "Legacy shared-provider enrolment enabled in hosted bot"

    callback_patterns = [
        h.pattern for h in all_handlers
        if isinstance(h, CallbackQueryHandler) and h.pattern is not None
    ]
    assert any(
        p.match("YES:CMD-TEST") and p.match("NO:CMD-TEST")
        for p in callback_patterns
    ), "Explicit YES/NO subscriber approval callback missing"
    assert any(
        p.match("SIGOK:" + "a" * 16)
        and p.match("SIGEDIT:" + "a" * 16)
        and p.match("SIGNO:" + "a" * 16)
        for p in callback_patterns
    ), "Provider screenshot preview/confirm/edit/cancel callbacks missing"

    assert sum(isinstance(h, MessageHandler) for h in all_handlers) >= 3, (
        "Screenshot/photo/text handler routing incomplete"
    )
    check_telegram_httpx_token_log_privacy()
    check_broadcast_failure_logs_are_private()
    check_broadcast_recipient_feed_binding()
    check_signal_create_backend_errors_remain_private()
    check_backend_http_fail_closed()
    check_unconfirmed_decision_does_not_claim_approval()
    check_screenshot_extraction_fail_closed()
    check_screenshot_upload_size_guard()
    check_telegram_download_transport_failures_fail_closed()
    check_overlapping_screenshot_attempts_fail_closed()
    check_malformed_pending_confirmation_fails_closed()
    check_preview_keyboard_token_contract()
    check_preview_callback_identity_and_single_use()
    check_preview_source_rebind_blocks_confirmation()
    check_edit_text_bound_to_preview_across_authorisation_await()
    check_provider_source_status_requires_active_typed_binding()
    check_hosted_legacy_provider_status_never_grants_identity()
    check_connectprovider_error_does_not_echo_backend_secrets()
    check_start_registration_receipt_integrity()
    check_join_invite_backend_response_integrity()
    check_connectprovider_success_receipt_integrity()
    print("Hosted Telegram bot: offline wiring and backend-error safety PASS; no external calls")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
