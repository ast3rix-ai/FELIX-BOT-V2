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
from core.templates import render_template
from core.persistence import mark_template_used, template_already_used


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


def register_handlers(
    client: TelegramClient,
    templates: Dict[str, str],
    rules: Dict[str, Any],
    llm: Optional[LLM] = None,
    threshold: float = 0.75,
) -> None:
    folder_cache: FolderCache = FolderCache()

    async def init_cache() -> None:
        nonlocal folder_cache
        folder_cache = await build_folder_cache(client)

    # initialize cache in background
    asyncio.create_task(init_cache())

    # Per-peer locks and a simple global RPS limiter
    peer_locks: Dict[str, asyncio.Lock] = {}
    rps_lock = asyncio.Semaphore(5)

    @client.on(events.NewMessage(incoming=True))
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
        action, payload = route(text, rules=rules, peer_id=peer_key)

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
            send_key = payload.get("send_key")
            if send_key and not template_already_used(peer_key, send_key):
                from telegram.actions import mark_read, type_then_send
                reply_text = render_template(templates, send_key, {"peer": getattr(me, "first_name", "") if (me := await client.get_me()) else ""})
                await mark_read(client, event.chat_id, event.message)
                delay = typing_delay(len(reply_text))
                await type_then_send(client, event.chat_id, reply_text, delay)
                mark_template_used(peer_key, send_key)
            await add_peer_to(client, 4, sender)
            folder_cache.add(4, sender)
            return

        if action == "send_template":
            template_key = payload.get("key", "greeting")
            if template_already_used(peer_key, template_key):
                return
            reply_text = render_template(templates, template_key, {"peer": getattr(me, "first_name", "") if (me := await client.get_me()) else ""})

            from telegram.actions import mark_read, type_then_send  # local import to avoid cyc.

            await mark_read(client, event.chat_id, event.message)
            delay = typing_delay(len(reply_text))
            await type_then_send(client, event.chat_id, reply_text, delay)
            mark_template_used(peer_key, template_key)

    # end handler


__all__ = ["register_handlers", "build_folder_cache", "FolderCache"]


