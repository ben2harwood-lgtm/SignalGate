"""Static guardrails for hosted Telegram provider-source onboarding."""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CONFIG = (ROOT / "telegram_bot" / "config.py").read_text(encoding="utf-8")
BOT = (ROOT / "telegram_bot" / "bot.py").read_text(encoding="utf-8")
HANDLERS = (ROOT / "telegram_bot" / "handlers.py").read_text(encoding="utf-8")


def test_bot_config_reads_hosted_mode_and_disables_legacy_provider_identity():
    assert 'os.getenv("REQUIRE_LICENSE", "false")' in CONFIG
    assert 'os.getenv("ENABLE_LEGACY_PROVIDER_DEMO", "false")' in CONFIG
    method = CONFIG.split("def is_signal_provider(", 1)[1].split(
        "def local_provider_ids(", 1
    )[0]
    assert "if self.require_license or not self.legacy_provider_demo_enabled:" in method
    assert "return False" in method


def test_hosted_bot_does_not_register_shared_provider_command():
    assert 'if config.legacy_provider_demo_enabled and not config.require_license:' in BOT
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
    assert "if config.require_license or not config.legacy_provider_demo_enabled:" in handler
    assert "Legacy /provider enrolment is disabled" in handler
    assert "/connectprovider TOKEN" in handler


def _new_bot_config(monkeypatch, tmp_path, require_license, opt_in):
    """Load bot configuration with synthetic identities and no Telegram calls."""
    monkeypatch.setenv("REQUIRE_LICENSE", require_license)
    monkeypatch.setenv("ENABLE_LEGACY_PROVIDER_DEMO", opt_in)
    monkeypatch.setenv("ADMIN_TELEGRAM_IDS", "101")
    monkeypatch.setenv("SIGNAL_PROVIDER_TELEGRAM_IDS", "202")
    spec = importlib.util.spec_from_file_location(
        "signalgate_test_bot_config", ROOT / "telegram_bot" / "config.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    config = module.BotConfig()
    config.provider_store_path = tmp_path / "provider_ids.json"
    return config


@pytest.mark.parametrize(
    ("require_license", "opt_in", "enabled"),
    [
        ("false", "false", False),
        ("false", "", False),
        ("false", "typo", False),
        ("true", "false", False),
        ("true", "true", False),
        ("false", "true", True),
    ],
)
def test_legacy_provider_requires_explicit_local_only_opt_in(
    monkeypatch, tmp_path, require_license, opt_in, enabled
):
    config = _new_bot_config(monkeypatch, tmp_path, require_license, opt_in)
    assert config.legacy_provider_demo_enabled is enabled
    assert config.is_admin("101")  # Admin identity != provider authority.
    assert config.is_signal_provider("101") is enabled
    assert config.is_signal_provider("202") is enabled
    if enabled:
        config.add_local_provider("303")
        assert config.is_signal_provider("303")
        assert config.provider_store_path.exists()
    else:
        with pytest.raises(RuntimeError, match="explicit local-demo opt-in"):
            config.add_local_provider("303")
        assert not config.provider_store_path.exists()
        assert not config.is_signal_provider("303")
