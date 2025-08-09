from __future__ import annotations

import asyncio
from typing import Any

from telethon.client.telegramclient import TelegramClient


async def mark_read(client: TelegramClient, chat: Any, msg: Any | None = None) -> None:
    await client.send_read_acknowledge(chat, message=msg)


async def type_then_send(client: TelegramClient, chat: Any, text: str, delay: float) -> None:
    async with client.action(chat, "typing"):
        await asyncio.sleep(delay)
        await client.send_message(chat, text)


__all__ = ["mark_read", "type_then_send"]


