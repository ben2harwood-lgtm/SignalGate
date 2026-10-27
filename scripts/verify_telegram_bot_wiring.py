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
    """Even a malformed nominally successful body must not produce APPROVED UI."""
    seen = []
    called = []
    async def fake_post(path, **kwargs):
        called.append(path)
        return {"detail": "backend error without result"}

    class Query:
        data = "YES:SIG-TEST"
        from_user = SimpleNamespace(id=1)
        message = SimpleNamespace(text="Synthetic demo trade card")

        async def answer(self):
            pass

        async def edit_message_text(self, message):
            seen.append(message)

    with patch.object(handlers, "_backend_post", fake_post):
        asyncio.run(handlers.on_decision(SimpleNamespace(callback_query=Query()), None))
    assert len(seen) == 1 and "could not be confirmed" in seen[0].lower()
    assert "Approved. Waiting" not in seen[0]
    assert called == ["/signals/SIG-TEST/approve"]

    called.clear()
    seen.clear()
    class InvalidQuery(Query):
        data = "UNKNOWN:SIG-TEST"

    with patch.object(handlers, "_backend_post", fake_post):
        asyncio.run(handlers.on_decision(SimpleNamespace(callback_query=InvalidQuery()), None))
    assert seen == ["Invalid action."]
    assert not called



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

    async def connected(_update):
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
        patch.object(handlers, "_can_submit_provider_signal", connected),
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

    async def connected(_update):
        return True

    async def disconnected(_update):
        return False

    async def broadcast(_update, _context, raw_text):
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
            patch.object(handlers, "_can_submit_provider_signal", authorised),
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
        async def superseded(_update):
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
    async def revoked_after_supersession(_update):
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

        async def source(_update):
            entered.set()
            await release.wait()
            return allowed

        async def create(_update, _context, raw_text):
            calls.append(raw_text)
            return "synthetic-only"

        with (
            patch.object(handlers, "_can_submit_provider_signal", source),
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

        async def source(_update):
            nonlocal entered
            entered += 1
            if entered == 2:
                both_entered.set()
            await release.wait()
            return True

        async def create(_update, _context, raw_text):
            calls.append(raw_text)
            return "synthetic-only"

        with (
            patch.object(handlers, "_can_submit_provider_signal", source),
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

        async def create(_update, _context, raw_text):
            calls.append(raw_text)
            return "synthetic-only"

        async def refused(_update):
            return False

        async def allowed(_update):
            return True

        with (
            patch.object(handlers, "_can_submit_provider_signal", refused),
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
            patch.object(handlers, "_can_submit_provider_signal", allowed),
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
            patch.object(handlers, "_can_submit_provider_signal", allowed),
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


def check_hosted_legacy_provider_status_never_grants_identity() -> None:
    """Even a stale local-provider flag cannot claim hosted provider authority."""
    assert config.require_license is True
    replies = []
    calls = []

    async def disconnected(_user_id):
        return None

    async def register(path, **_kwargs):
        calls.append(("POST", path))
        return {"license_key": None}

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
    assert "not connected" in replies[0].lower()
    assert "Provider Portal" in replies[0]
    assert secret not in replies[0]
    assert "SYNTHETIC-ONE-TIME-TOKEN" not in replies[0]

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
    check_backend_http_fail_closed()
    check_unconfirmed_decision_does_not_claim_approval()
    check_screenshot_extraction_fail_closed()
    check_screenshot_upload_size_guard()
    check_overlapping_screenshot_attempts_fail_closed()
    check_malformed_pending_confirmation_fails_closed()
    check_preview_keyboard_token_contract()
    check_preview_callback_identity_and_single_use()
    check_edit_text_bound_to_preview_across_authorisation_await()
    check_hosted_legacy_provider_status_never_grants_identity()
    check_connectprovider_error_does_not_echo_backend_secrets()
    print("Hosted Telegram bot: offline wiring and backend-error safety PASS; no external calls")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
