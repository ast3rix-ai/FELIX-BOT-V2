from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional, Set, Tuple

from telethon import events, functions, types
from telethon.client.telegramclient import TelegramClient

from core.delays import typing_delay
from core.folder_manager import FOLDERS, add_peer_to, get_filters
from core.router import route
from core.logging import logger
from core.classifier import classify_and_maybe_reply
from core.llm import LLM, LLMReject


class FolderCache:
    def __init__(self) -> None:
        # folder_id -> set of peer key strings
        self.map: Dict[int, Set[str]] = {}

    @staticmethod
    def _peer_key(peer: types.TypeInputPeer) -> str:
        if isinstance(peer, types.InputPeerUser):
            return f"user:{peer.user_id}"
        if isinstance(peer, types.InputPeerChat):
            return f"chat:{peer.chat_id}"
        if isinstance(peer, types.InputPeerChannel):
            return f"channel:{peer.channel_id}"
        if isinstance(peer, types.InputPeerSelf):
            return "self"
        return str(peer)

    @classmethod
    def from_filters(cls, filters: Any) -> "FolderCache":
        inst = cls()
        for f in filters:
            inst.map[f.id] = {cls._peer_key(p) for p in getattr(f, "include_peers", [])}
        return inst

    def contains(self, folder_id: int, input_peer: types.TypeInputPeer) -> bool:
        return self._peer_key(input_peer) in self.map.get(folder_id, set())

    def add(self, folder_id: int, input_peer: types.TypeInputPeer) -> None:
        self.map.setdefault(folder_id, set()).add(self._peer_key(input_peer))


async def build_folder_cache(client: TelegramClient) -> FolderCache:
    filters = await get_filters(client)
    return FolderCache.from_filters(filters)


def register_handlers(client: TelegramClient, templates: Dict[str, str], llm: Optional[LLM] = None, threshold: float = 0.75) -> None:
    folder_cache: FolderCache = FolderCache()

    async def init_cache() -> None:
        nonlocal folder_cache
        folder_cache = await build_folder_cache(client)

    # initialize cache in background
    asyncio.create_task(init_cache())

    @client.on(events.NewMessage(incoming=True))
    # Per-peer locks and a simple global RPS limiter
    peer_locks: Dict[str, asyncio.Lock] = {}
    rps_lock = asyncio.Semaphore(5)

    async def on_new_message(event: events.NewMessage.Event) -> None:  # type: ignore[override]
        if event.is_private is False:
            return

        sender = await event.get_input_sender()
        peer_key = FolderCache._peer_key(sender)

        lock = peer_locks.setdefault(peer_key, asyncio.Lock())
        async with rps_lock, lock:
        # Obtain latest folder state if cache is empty
            if not folder_cache.map:
                fc = await build_folder_cache(client)
                folder_cache.map = fc.map

        # Ignore if already in Manual(1) / Timewaster(3) / Confirmation(4)
        for fid in (1, 3, 4):
            if folder_cache.contains(fid, sender):
                return

        # Otherwise treat as Bot folder (2) by default
        text = event.raw_text or ""
        action, payload = route(text, rules={})

        if action == "manual":
            # Try LLM fallback if available
            if llm is not None:
                history: list[str] = []
                try:
                    intent, confidence, reply = await classify_and_maybe_reply(llm, text, history, threshold)
                except LLMReject:
                    reply = None
                    confidence = 0.0
                if reply and confidence >= threshold and len(reply.split()) <= 120:
                    from telegram.actions import mark_read, type_then_send

                    await mark_read(client, event.chat_id, event.message)
                    delay = typing_delay(len(reply))
                    await type_then_send(client, event.chat_id, reply, delay)
                    return
            # Fallback: route to Manual without read/typing
            await add_peer_to(client, 1, sender)
            folder_cache.add(1, sender)
            return

        if action == "move_timewaster":
            await add_peer_to(client, 3, sender)
            folder_cache.add(3, sender)
            return

        if action == "move_confirmation":
            await add_peer_to(client, 4, sender)
            folder_cache.add(4, sender)
            return

        if action == "send_template":
            template_key = payload.get("template_key", "welcome")
            reply_text = templates.get(template_key) or templates.get("welcome") or "Thanks for your message."

            from telegram.actions import mark_read, type_then_send  # local import to avoid cyc.

            await mark_read(client, event.chat_id, event.message)
            delay = typing_delay(len(reply_text))
            await type_then_send(client, event.chat_id, reply_text, delay)

    # end handler


__all__ = ["register_handlers", "build_folder_cache", "FolderCache"]


