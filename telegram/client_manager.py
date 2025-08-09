from __future__ import annotations

from pathlib import Path

from telethon import TelegramClient

from core.config import BrokerSettings


def create_client(settings: BrokerSettings) -> TelegramClient:
    session_path: Path = settings.get_session_path()
    session_path.parent.mkdir(parents=True, exist_ok=True)

    # Telethon accepts a path (with .session) as the session identifier
    client = TelegramClient(str(session_path), settings.telegram_api_id, settings.telegram_api_hash)
    return client


__all__ = ["create_client"]


