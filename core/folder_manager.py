from __future__ import annotations
from typing import Dict, List, Tuple
from loguru import logger
from telethon.tl import types, functions

FOLDER_TITLES = ["Manual", "Bot", "Timewaster", "Confirmation"]


def _peer_tuple(ip) -> Tuple[int | None, int | None, int | None]:
    return (getattr(ip, "user_id", None), getattr(ip, "chat_id", None), getattr(ip, "channel_id", None))


def _same_peer(a, b) -> bool:
    return _peer_tuple(a) == _peer_tuple(b)


async def _list_filters(client) -> Dict[int, types.DialogFilter]:
    res = await client(functions.messages.GetDialogFiltersRequest())
    out: Dict[int, types.DialogFilter] = {}
    for f in getattr(res, "filters", []) or []:
        if isinstance(f, types.DialogFilter):
            out[f.id] = f
    return out


def _find_by_title(filters: Dict[int, types.DialogFilter], title: str) -> int | None:
    for fid, df in filters.items():
        if getattr(df, "title", "") == title:
            return fid
    return None


def _pick_free_slot(filters: Dict[int, types.DialogFilter]) -> int:
    used = set(filters.keys())
    for i in range(10):
        if i not in used:
            return i
    raise RuntimeError("All 10 Telegram folder slots are already used. Delete one and retry.")


async def _update_filter(client, fid: int, df: types.DialogFilter) -> None:
    if not isinstance(df, types.DialogFilter):
        raise TypeError(f"internal: filter must be types.DialogFilter, got {type(df)}")
    await client(functions.messages.UpdateDialogFilterRequest(id=fid, filter=df))


async def move_to_folder_lazy(client, title: str, peer, exclusive: bool = True) -> int:
    if title not in FOLDER_TITLES:
        raise ValueError(f"Unknown folder title '{title}'")

    ip = await client.get_input_entity(peer)
    filters = await _list_filters(client)

    # Exclusivity: remove from all known titles first
    if exclusive:
        for fid, df in list(filters.items()):
            if getattr(df, "title", "") in FOLDER_TITLES:
                peers = list(df.include_peers or [])
                newp = [p for p in peers if not _same_peer(p, ip)]
                if newp != peers:
                    new_df = types.DialogFilter(
                        id=fid,
                        title=df.title,
                        emoticon=getattr(df, "emoticon", ""),
                        pinned_peers=list(df.pinned_peers or []),
                        include_peers=newp,
                        exclude_peers=list(df.exclude_peers or []),
                    )
                    await _update_filter(client, fid, new_df)
                    filters[fid] = new_df

    # Find or create target
    fid = _find_by_title(filters, title)
    if fid is None:
        fid = _pick_free_slot(filters)
        new_df = types.DialogFilter(
            id=fid,
            title=title,
            emoticon="",
            pinned_peers=[],
            include_peers=[ip],
            exclude_peers=[],
        )
        await _update_filter(client, fid, new_df)
        logger.info(f"created folder '{title}' at slot {fid} (and added peer)")
        filters[fid] = new_df
        return fid

    # Folder exists -> add peer if missing
    df = filters[fid]
    peers = list(df.include_peers or [])
    if not any(_same_peer(p, ip) for p in peers):
        peers.append(ip)
        upd = types.DialogFilter(
            id=fid,
            title=df.title,
            emoticon=getattr(df, "emoticon", ""),
            pinned_peers=list(df.pinned_peers or []),
            include_peers=peers,
            exclude_peers=list(df.exclude_peers or []),
        )
        await _update_filter(client, fid, upd)
        filters[fid] = upd
    return fid


async def move_to_manual(client, peer):        return await move_to_folder_lazy(client, "Manual", peer, exclusive=True)
async def move_to_bot(client, peer):           return await move_to_folder_lazy(client, "Bot", peer, exclusive=True)
async def move_to_timewaster(client, peer):    return await move_to_folder_lazy(client, "Timewaster", peer, exclusive=True)
async def move_to_confirmation(client, peer):  return await move_to_folder_lazy(client, "Confirmation", peer, exclusive=True)


__all__ = [
    "move_to_folder_lazy",
    "move_to_manual",
    "move_to_bot",
    "move_to_timewaster",
    "move_to_confirmation",
]


