from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from telethon import functions, types
from telethon.tl import types as tl_types
from telethon.client.telegramclient import TelegramClient
from .logging import logger
from .config import load_settings


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

# New mapping by names for robust folder management
FOLDER_NAMES: List[str] = ["Manual", "Bot", "Timewaster", "Confirmation"]


def _map_path() -> Path:
    s = load_settings()
    # Persist map under account directory
    return (s.paths.accounts_dir / s.account / "folders.json").resolve()


async def get_filters(client: TelegramClient) -> List[types.DialogFilter]:
    """Return the list of existing dialog filters (folders).

    Uses messages.GetDialogFiltersRequest and returns a list of DialogFilter
    objects; returns an empty list if Telegram responds without filters.
    """
    result = await client(functions.messages.GetDialogFiltersRequest())
    return [f for f in (getattr(result, "filters", []) or []) if isinstance(f, types.DialogFilter)]


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
    """Construct a DialogFilter with provided peers and a title."""
    return types.DialogFilter(
        id=folder_id,
        title=title,  # IMPORTANT: plain string
        emoticon="",
        pinned_peers=[],
        include_peers=include_peers or [],
        exclude_peers=[],
    )


async def _get_filters(client: TelegramClient) -> Dict[int, types.DialogFilter]:
    res = await client(functions.messages.GetDialogFiltersRequest())
    existing: Dict[int, types.DialogFilter] = {}
    for f in getattr(res, "filters", []) or []:
        if isinstance(f, types.DialogFilter):
            existing[f.id] = f
    return existing


def _peer_tuple(ip) -> Tuple[Optional[int], Optional[int], Optional[int]]:
    return (getattr(ip, "user_id", None), getattr(ip, "chat_id", None), getattr(ip, "channel_id", None))


def _same_peer(a, b) -> bool:
    return _peer_tuple(a) == _peer_tuple(b)


async def ensure_filters(client: TelegramClient) -> Dict[str, int]:
    """Ensure 4 folders exist with stable ids and correct types.

    Returns a mapping like {"Manual": id, "Bot": id, ...} and persists it under
    data/accounts/<acc>/folders.json so IDs remain stable across runs.
    """
    # Must be authorized before manipulating folders
    if not await client.is_user_authorized():
        raise RuntimeError("ensure_filters called before authorization")

    path = _map_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = await _get_filters(client)

    # Load previous mapping if present
    mapping: Dict[str, int] = {}
    if path.exists():
        try:
            import json
            mapping = json.loads(path.read_text())
        except Exception:
            mapping = {}

    used_ids = set(existing.keys())
    available: List[int] = [i for i in range(10) if i not in used_ids]

    def reserve_id(name: str) -> int:
        fid = mapping.get(name)
        if isinstance(fid, int) and 0 <= fid <= 9:
            return fid
        if not available:
            raise RuntimeError("All 10 Telegram folders are already used. Delete one manually and retry.")
        return available.pop(0)

    out: Dict[str, int] = {}
    for name in FOLDER_NAMES:
        # find by existing title first
        found_id: Optional[int] = None
        for fid, df in existing.items():
            if getattr(df, "title", "") == name:
                found_id = fid
                break
        if found_id is None:
            fid = reserve_id(name)
            df = _build_dialog_filter(fid, name, include_peers=[])
            await client(functions.messages.UpdateDialogFilterRequest(id=fid, filter=df))
            logger.info(f"created folder '{name}' at slot {fid}")
            existing[fid] = df
            out[name] = fid
        else:
            out[name] = found_id

    # persist
    try:
        import json
        path.write_text(json.dumps(out, indent=2))
    except Exception as e:
        logger.warning(f"failed to write folders.json: {e}")
    return out


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


async def _get_filters_compat(client: TelegramClient) -> Dict[int, types.DialogFilter]:
    # Back-compat alias if older code references this symbol
    return await _get_filters(client)


def _same_peer(a, b) -> bool:
    return (
        getattr(a, "user_id", None) is not None and getattr(b, "user_id", None) is not None and a.user_id == b.user_id
    ) or (
        getattr(a, "channel_id", None) is not None and getattr(b, "channel_id", None) is not None and a.channel_id == b.channel_id
    ) or (
        getattr(a, "chat_id", None) is not None and getattr(b, "chat_id", None) is not None and a.chat_id == b.chat_id
    )


async def move_peer_to(client: TelegramClient, target_folder_id: int, peer: object) -> None:
    """Exclusive move: remove from our folders, add to target idempotently."""
    ip = await client.get_input_entity(peer)
    filters = await _get_filters(client)

    # Remove from every known folder by title
    for fid, df in list(filters.items()):
        if getattr(df, "title", "") in FOLDER_NAMES:
            before = list(df.include_peers or [])
            after = [p for p in before if not _same_peer(p, ip)]
            if before != after:
                df = types.DialogFilter(
                    id=fid,
                    title=df.title,
                    emoticon=getattr(df, "emoticon", ""),
                    pinned_peers=list(df.pinned_peers or []),
                    include_peers=after,
                    exclude_peers=list(df.exclude_peers or []),
                )
                await client(functions.messages.UpdateDialogFilterRequest(id=fid, filter=df))
                filters[fid] = df

    # Add to target
    target = filters.get(target_folder_id)
    if not target:
        raise RuntimeError(f"Target folder id {target_folder_id} not found. Run ensure_filters() first.")
    peers = list(target.include_peers or [])
    if not any(_same_peer(p, ip) for p in peers):
        peers.append(ip)
        target = types.DialogFilter(
            id=target_folder_id,
            title=target.title,
            emoticon=getattr(target, "emoticon", ""),
            pinned_peers=list(target.pinned_peers or []),
            include_peers=peers,
            exclude_peers=list(target.exclude_peers or []),
        )
        await client(functions.messages.UpdateDialogFilterRequest(id=target_folder_id, filter=target))
    logger.info(f"moved peer -> {target_folder_id}")


__all__ = [
    "FOLDERS",
    "get_filters",
    "ensure_filters",
    "add_peer_to",
    "remove_peer_from",
    "current_filters",
    "move_peer_to",
]


