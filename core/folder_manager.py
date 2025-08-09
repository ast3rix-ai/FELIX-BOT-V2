from __future__ import annotations

from typing import Dict, Iterable, List, Optional

from telethon import functions, types
from telethon.tl import types as tl_types
from telethon.client.telegramclient import TelegramClient


"""Utilities for managing Telegram dialog folders using Telethon.

This module provides idempotent operations for creating and updating dialog
filters (also known as folders) and for maintaining peer membership in those
folders. All functions are designed to handle partial/empty results returned by
Telegram gracefully.
"""

FOLDERS: Dict[int, str] = {
    1: "Manual",
    2: "Bot",
    3: "Timewaster",
    4: "Confirmation",
}


async def get_filters(client: TelegramClient) -> List[types.DialogFilter]:
    """Return the list of existing dialog filters (folders).

    Uses messages.GetDialogFiltersRequest and returns a list of DialogFilter
    objects; returns an empty list if Telegram responds without filters.
    """
    result = await client(functions.messages.GetDialogFiltersRequest())
    return list(getattr(result, "filters", []) or [])


def _normalize_input_peer_key(peer: tl_types.TypeInputPeer) -> str:
    if isinstance(peer, tl_types.InputPeerUser):
        return f"user:{peer.user_id}"
    if isinstance(peer, tl_types.InputPeerChat):
        return f"chat:{peer.chat_id}"
    if isinstance(peer, tl_types.InputPeerChannel):
        return f"channel:{peer.channel_id}"
    if isinstance(peer, tl_types.InputPeerSelf):
        return "self"
    return str(peer)  # fallback


async def _to_input_peer(client: TelegramClient, entity: object) -> tl_types.TypeInputPeer:
    """Convert any entity to an InputPeer variant using Telethon helper."""
    return await client.get_input_entity(entity)


def _build_dialog_filter(
    folder_id: int,
    title: str,
    include_peers: Optional[List[tl_types.TypeInputPeer]] = None,
) -> types.DialogFilter:
    """Construct a DialogFilter with provided peers and a title.

    Only sets minimal safe fields. Other optional fields are left empty.
    """
    return types.DialogFilter(
        id=folder_id,
        title=types.TextWithEntities(text=title, entities=[]),
        pinned_peers=[],
        include_peers=include_peers or [],
        exclude_peers=[],
    )


async def ensure_filters(client: TelegramClient) -> Dict[int, types.DialogFilter]:
    """Ensure required folders exist with desired titles.

    Upserts filters for the folder IDs in FOLDERS, preserving include_peers
    when a filter already exists. Returns a mapping of folder_id to the final
    DialogFilter objects (best-effort based on local state after updates).
    """
    current = await get_filters(client)
    by_id: Dict[int, types.DialogFilter] = {f.id: f for f in current}

    for folder_id, title in FOLDERS.items():
        existing = by_id.get(folder_id)
        if existing is None:
            desired = _build_dialog_filter(folder_id, title, include_peers=[])
            await client(functions.messages.UpdateDialogFilterRequest(id=folder_id, filter=desired))
            by_id[folder_id] = desired
            continue

        existing_title = existing.title.text if isinstance(existing.title, types.TextWithEntities) else str(existing.title)
        if existing_title != title:
            desired = _build_dialog_filter(folder_id, title, include_peers=list(existing.include_peers))
            await client(functions.messages.UpdateDialogFilterRequest(id=folder_id, filter=desired))
            by_id[folder_id] = desired

    return by_id


async def add_peer_to(client: TelegramClient, folder_id: int, peer: object) -> None:
    """Add a peer to include_peers of the given folder idempotently."""
    by_id = await current_filters(client)
    existing = by_id.get(folder_id)

    input_peer = await _to_input_peer(client, peer)
    input_key = _normalize_input_peer_key(input_peer)

    if existing is None:
        title = FOLDERS.get(folder_id, f"Folder {folder_id}")
        desired = _build_dialog_filter(folder_id, title, include_peers=[input_peer])
        await client(functions.messages.UpdateDialogFilterRequest(id=folder_id, filter=desired))
        return

    existing_keys = {_normalize_input_peer_key(p) for p in getattr(existing, "include_peers", [])}
    if input_key in existing_keys:
        return

    new_peers = list(getattr(existing, "include_peers", []) or []) + [input_peer]
    title = existing.title.text if isinstance(existing.title, types.TextWithEntities) else FOLDERS.get(folder_id, str(existing.title))
    desired = _build_dialog_filter(folder_id, title, include_peers=new_peers)
    await client(functions.messages.UpdateDialogFilterRequest(id=folder_id, filter=desired))


async def remove_peer_from(client: TelegramClient, folder_id: int, peer: object) -> None:
    """Remove a peer from include_peers of the given folder idempotently."""
    by_id = await current_filters(client)
    existing = by_id.get(folder_id)
    if existing is None:
        return

    input_peer = await _to_input_peer(client, peer)
    input_key = _normalize_input_peer_key(input_peer)
    before = list(getattr(existing, "include_peers", []) or [])
    new_peers = [p for p in before if _normalize_input_peer_key(p) != input_key]
    if len(new_peers) == len(before):
        return

    title = existing.title.text if isinstance(existing.title, types.TextWithEntities) else FOLDERS.get(folder_id, str(existing.title))
    desired = _build_dialog_filter(folder_id, title, include_peers=new_peers)
    await client(functions.messages.UpdateDialogFilterRequest(id=folder_id, filter=desired))


async def current_filters(client: TelegramClient) -> Dict[int, types.DialogFilter]:
    """Return a mapping of folder id to DialogFilter for current state."""
    current = await get_filters(client)
    return {f.id: f for f in current}


__all__ = [
    "FOLDERS",
    "get_filters",
    "ensure_filters",
    "add_peer_to",
    "remove_peer_from",
    "current_filters",
]


