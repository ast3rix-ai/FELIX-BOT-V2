from __future__ import annotations
import asyncio
from typing import Dict, Any, Optional, Tuple
import re

from loguru import logger
from telethon import events, types
from telethon.errors import FilterIdInvalidError
from telethon.client.telegramclient import TelegramClient

from core.classifier import choose_template_or_move
from core.config import load_settings
from core.delays import typing_delay
from core.folder_manager import ensure_filters as fm_ensure_filters, move_peer_to, get_filters, FOLDERS, FOLDER_IDS
from core.llm import LLM, LLMReject
from core.persistence import mark_template_used, template_already_used, set_last_template
from core.router import route_full
from core.templates import get_templates, load_templates, render_template as render_template_map

def _peer_tuple(ip) -> Tuple[Optional[int], Optional[int], Optional[int]]:
    return (getattr(ip, "user_id", None), getattr(ip, "chat_id", None), getattr(ip, "channel_id", None))

def _same_peer(a, b) -> bool:
    return _peer_tuple(a) == _peer_tuple(b)

async def get_current_folder_name(client, peer, server_filters) -> Optional[str]:
    for f in server_filters:
        title = f.title.text if isinstance(f.title, types.TextWithEntities) else str(f.title)
        norm_title = re.sub(r"^\s*[A-Z0-9]+\s*", "", title).strip()
        if norm_title in FOLDERS.values():
            if any(_same_peer(p, peer) for p in (f.include_peers or [])):
                return norm_title
    return None

def register_handlers(
    client: TelegramClient,
    templates: Dict[str, str],
    rules: Dict[str, Any],
    llm: Optional[LLM] = None,
    threshold: float = 0.75,
) -> None:
    @client.on(events.NewMessage(incoming=True))
    async def on_new_message(event: events.NewMessage.Event) -> None:
        # Use a fresh client for each message to ensure state is not stale
        current_client = event.client
        
        if not event.is_private:
            return
        
        # Always reload templates to catch live edits
        loaded_templates = load_templates()

        try:
            input_peer = await current_client.get_input_entity(event.chat_id)
        except Exception:
            input_peer = await event.get_input_sender()

        if not input_peer:
            return

        peer_key = f"peer_{event.chat_id}"

        # Check if the chat is already in a final folder
        all_filters = await get_filters(current_client)
        folder_name = None
        for df in all_filters:
            if any(_same_peer(p, input_peer) for p in (df.include_peers or [])):
                folder_name = df.title.text if isinstance(df.title, types.TextWithEntities) else str(df.title)
                break
        
        if folder_name in ["M0", "C0"]:
            return

        logger.info(f"user typed: {event.raw_text}")
        text = event.raw_text or ""

        action, payload = await route_full(
            text, rules, peer_key, history=[], folder_name="BOT",
            classifier=llm, threshold=threshold
        )

        move_action_map = {
            "manual": "M0",
            "move_confirmation": "C0",
            "send_template": "B0",
        }

        if action in move_action_map:
            target_folder = move_action_map[action]
            logger.info(f"Moving chat to {target_folder} folder for action: {action}")

            try:
                if action in ["move_confirmation", "send_template"]:
                    key = None
                    if action == "send_template":
                        key = payload.get("key", "greeting") # Use greeting as fallback
                    elif action == "move_confirmation":
                        key = payload.get("send_key", "greeting")

                    if key and not template_already_used(peer_key, key):
                        from telegram.actions import mark_read, type_then_send
                        
                        text_to_send = render_template_map(loaded_templates, key, {}) or "..."

                        await mark_read(current_client, event.chat_id, event.message)
                        delay = typing_delay(len(text_to_send))
                        await type_then_send(current_client, event.chat_id, text_to_send, delay)
                        mark_template_used(peer_key, key)
                        set_last_template(peer_key, key)
                
                    target_folder_id = FOLDER_IDS[target_folder]
                    logger.info(f"Attempting to move chat to {target_folder} (ID: {target_folder_id})")
                    await move_peer_to(current_client, target_folder_id, input_peer)
                    logger.info(f"Successfully moved chat to {target_folder} (ID: {target_folder_id})")
            except Exception as e:
                logger.error(f"Failed to process action {action}: {e}", exc_info=True)

async def start_live(client: TelegramClient, templates: Dict[str, str], rules: Dict[str, Any], llm: Optional[LLM] = None, threshold: float = 0.75) -> None:
    register_handlers(client, templates, rules, llm=llm, threshold=threshold)
    await client.run_until_disconnected()

__all__ = ["register_handlers", "start_live"]


