"""Provider provisioning CLI safety tests."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "provision_provider.py"
SPEC = importlib.util.spec_from_file_location("provision_provider", SCRIPT)
assert SPEC and SPEC.loader
provision = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(provision)


def test_provider_provisioning_feed_payload_starts_paused():
    payload = provision.feed_create_payload("Main Feed", "provider-main")
    assert payload == {
        "name": "Main Feed",
        "source_namespace": "provider-main",
        "paused": True,
    }
