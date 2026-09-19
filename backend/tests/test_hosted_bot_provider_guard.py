"""Static guardrails for hosted Telegram provider-source onboarding."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIG = (ROOT / "telegram_bot" / "config.py").read_text(encoding="utf-8")
BOT = (ROOT / "telegram_bot" / "bot.py").read_text(encoding="utf-8")
HANDLERS = (ROOT / "telegram_bot" / "handlers.py").read_text(encoding="utf-8")


def test_bot_config_reads_hosted_mode_and_disables_legacy_provider_identity():
    assert 'os.getenv("REQUIRE_LICENSE", "false")' in CONFIG
    method = CONFIG.split("def is_signal_provider(", 1)[1].split(
        "def local_provider_ids(", 1
    )[0]
    assert "if self.require_license:" in method
    assert "return False" in method


def test_hosted_bot_does_not_register_shared_provider_command():
    assert 'if not config.require_license:' in BOT
    assert 'CommandHandler("provider", handlers.provider_invite)' in BOT


def test_hosted_submission_requires_persisted_source_binding():
    can_submit = HANDLERS.split(
        "async def _can_submit_provider_signal", 1
    )[1].split("# --- user commands", 1)[0]
    assert "_provider_source_status" in can_submit
    assert "if config.require_license:" in can_submit
    assert "return False" in can_submit

    create = HANDLERS.split("async def _create_and_broadcast", 1)[1].split(
        "async def testsignal", 1
    )[0]
    assert "if config.require_license or not config.is_signal_provider(user_id):" in create
    assert "/connectprovider TOKEN" in create


def test_legacy_provider_handler_explicitly_fails_closed_if_called_hosted():
    handler = HANDLERS.split("async def provider_invite", 1)[1].split(
        "# --- callback", 1
    )[0]
    assert "if config.require_license:" in handler
    assert "Legacy /provider enrolment is disabled" in handler
    assert "/connectprovider TOKEN" in handler
