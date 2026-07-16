"""Telegram bot configuration (reads the shared project .env)."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import List

from dotenv import load_dotenv

# Load .env from project root if present.
load_dotenv()


class BotConfig:
    def __init__(self) -> None:
        self.token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.backend_base_url: str = os.getenv(
            "BACKEND_BASE_URL", "http://127.0.0.1:8000"
        )
        admin_raw: str = os.getenv("ADMIN_TELEGRAM_IDS", "")
        self.admin_ids: List[str] = [x.strip() for x in admin_raw.split(",") if x.strip()]
        provider_raw: str = os.getenv("SIGNAL_PROVIDER_TELEGRAM_IDS", "")
        self.provider_ids: List[str] = [
            x.strip() for x in provider_raw.split(",") if x.strip()
        ]
        self.provider_invite_code: str = os.getenv("SIGNAL_PROVIDER_INVITE_CODE", "")
        self.provider_store_path: Path = Path(__file__).with_name("provider_ids.json")
        # HOSTED: shared secrets the backend requires (see backend security.py).
        # Sent on every backend call so a hardened public backend accepts the
        # bot. Empty locally (backend then runs in open local-demo mode).
        self.bot_backend_secret: str = os.getenv("BOT_BACKEND_SECRET", "")
        self.admin_api_token: str = os.getenv("ADMIN_API_TOKEN", "")

    def is_admin(self, telegram_user_id: int | str) -> bool:
        return str(telegram_user_id) in self.admin_ids

    def is_signal_provider(self, telegram_user_id: int | str) -> bool:
        user_id = str(telegram_user_id)
        return (
            user_id in self.admin_ids
            or user_id in self.provider_ids
            or user_id in self.local_provider_ids()
        )

    def local_provider_ids(self) -> List[str]:
        try:
            data = json.loads(self.provider_store_path.read_text())
        except (OSError, json.JSONDecodeError):
            return []
        ids = data.get("provider_ids", []) if isinstance(data, dict) else []
        return [str(x) for x in ids if str(x).strip()]

    def add_local_provider(self, telegram_user_id: int | str) -> None:
        user_id = str(telegram_user_id)
        ids = set(self.local_provider_ids())
        ids.add(user_id)
        payload = {"provider_ids": sorted(ids)}
        self.provider_store_path.write_text(json.dumps(payload, indent=2) + "\n")

    def first_admin_id(self) -> str:
        return self.admin_ids[0] if self.admin_ids else ""


config = BotConfig()
