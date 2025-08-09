from __future__ import annotations

from typing import Dict, Iterable, List, Optional

from telethon import functions, types
from telethon.tl import types as tl_types
from telethon.client.telegramclient import TelegramClient


FOLDER_MAP: Dict[int, str] = {
    1: "Manual",
    2: "Bot",
    3: "Timewaster",
    4: "Confirmation",
}


async def get_filters(client: TelegramClient) -> List[types.DialogFilter]:
    result = await client(functions.messages.GetDialogFiltersRequest())
    # result is types.messages.DialogFilters with attribute 'filters'
    return list(result.filters)


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
    return await client.get_input_entity(entity)


def _build_dialog_filter(
    folder_id: int,
    title: str,
    include_peers: Optional[List[tl_types.TypeInputPeer]] = None,
) -> types.DialogFilter:
    return types.DialogFilter(
        id=folder_id,
        title=types.TextWithEntities(text=title, entities=[]),
        pinned_peers=[],
        include_peers=include_peers or [],
        exclude_peers=[],
        # Other optional fields intentionally left default/empty for now
    )


async def ensure_filters(client: TelegramClient) -> None:
    current_filters = await get_filters(client)
    current_by_id: Dict[int, types.DialogFilter] = {f.id: f for f in current_filters}

    for folder_id, title in FOLDER_MAP.items():
        existing = current_by_id.get(folder_id)
        if existing is None:
            desired = _build_dialog_filter(folder_id, title, include_peers=[])
            await client(functions.messages.UpdateDialogFilter(id=folder_id, filter=desired))
            continue

        existing_title = (
            existing.title.text if isinstance(existing.title, types.TextWithEntities) else str(existing.title)
        )
        if existing_title != title:
            # Preserve include_peers when only title differs
            desired = _build_dialog_filter(folder_id, title, include_peers=list(existing.include_peers))
            await client(functions.messages.UpdateDialogFilter(id=folder_id, filter=desired))


async def add_peer_to(client: TelegramClient, folder_id: int, peer: object) -> None:
    current_filters = await get_filters(client)
    by_id: Dict[int, types.DialogFilter] = {f.id: f for f in current_filters}
    existing = by_id.get(folder_id)

    input_peer = await _to_input_peer(client, peer)
    input_key = _normalize_input_peer_key(input_peer)

    if existing is None:
        title = FOLDER_MAP.get(folder_id, f"Folder {folder_id}")
        desired = _build_dialog_filter(folder_id, title, include_peers=[input_peer])
        await client(functions.messages.UpdateDialogFilter(id=folder_id, filter=desired))
        return

    existing_keys = {_normalize_input_peer_key(p) for p in existing.include_peers}
    if input_key in existing_keys:
        return

    new_peers = list(existing.include_peers) + [input_peer]
    title = (
        existing.title.text if isinstance(existing.title, types.TextWithEntities) else FOLDER_MAP.get(folder_id, str(existing.title))
    )
    desired = _build_dialog_filter(folder_id, title, include_peers=new_peers)
    await client(functions.messages.UpdateDialogFilter(id=folder_id, filter=desired))


__all__ = ["FOLDER_MAP", "get_filters", "ensure_filters", "add_peer_to"]


