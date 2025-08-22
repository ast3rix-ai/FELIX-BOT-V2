from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional, Set, Tuple

from telethon import events, functions, types
from telethon.client.telegramclient import TelegramClient

from core.delays import typing_delay
from core.folder_manager import (
    move_to_bot,
    move_to_manual,
    move_to_timewaster,
    move_to_confirmation,
)
from core.router import route_full, route_fast
from core.logging import logger
from core.classifier import choose_template_or_move
from core.llm import LLM, LLMReject
from core.templates import render_template
from core.persistence import mark_template_used, template_already_used, set_last_template


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
    # Lazy folders: start with empty cache; it will fill as we move peers
    return FolderCache()


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

    # Optional dynamic folder id map injected by UI after ensure_filters()
    folder_map: Dict[str, int] = getattr(client, "_folder_map", {}) if hasattr(client, "_folder_map") else {}
    def fid(name: str, default_id: int) -> int:
        return int(folder_map.get(name, default_id))

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

        # With lazy folders, cache may be empty; we don't attempt early ignore

        # Otherwise treat as Bot folder by default
        text = event.raw_text or ""
        action, payload = await route_full(
            text,
            rules,
            peer_key,
            history=[],
            folder_name="BOT",
            classifier=llm,
            threshold=threshold,
        )

        if action == "manual":
            # Try LLM chooser if available
            if llm is not None:
                history: list[str] = []
                try:
                    act, pay = await choose_template_or_move(llm, text, history, folder="BOT", used_templates=[], threshold=threshold)
                except LLMReject:
                    act, pay = ("move_manual", {})
                if act in ("send_template", "move_manual", "move_timewaster", "move_confirmation"):
                    action, payload = act, pay
                else:
                    action, payload = "move_manual", {}
            if action == "manual":
                new_id = await move_to_manual(client, sender)
                folder_cache.add(new_id, sender)
                return

        if action == "move_timewaster":
            new_id = await move_to_timewaster(client, sender)
            folder_cache.add(new_id, sender)
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
                set_last_template(peer_key, send_key)
            new_id = await move_to_confirmation(client, sender)
            folder_cache.add(new_id, sender)
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
            set_last_template(peer_key, template_key)
            # After any bot reply, ensure chat is only in Bot
            new_id = await move_to_bot(client, sender)
            folder_cache.add(new_id, sender)

    # end handler


async def start_live(client: TelegramClient, templates: Dict[str, str], rules: Dict[str, Any], llm: Optional[LLM] = None, threshold: float = 0.75) -> None:
    """Register handlers and run the client until disconnected.

    This is suitable for headless execution or as a background task from the UI.
    """
    register_handlers(client, templates, rules, llm=llm, threshold=threshold)
    await client.run_until_disconnected()


__all__ = ["register_handlers", "build_folder_cache", "FolderCache", "start_live"]


