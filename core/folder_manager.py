from __future__ import annotations
import asyncio
from typing import Dict, Optional, Iterable, List, Tuple

from loguru import logger
from telethon.errors import FilterIdInvalidError
from telethon.tl import functions, types
from telethon.tl import types as tl_types

FOLDER_TITLES = ["B0", "M0", "C0"]

# Public functional constants (compat with tests and export tooling)
FOLDERS: Dict[int, str] = {
    1: "M0",
    2: "B0",
    4: "C0",
}
FOLDER_NAMES: List[str] = ["M0", "B0", "C0"]

class FolderManager:
    def __init__(self, client):
        self._client = client
        self._filters_cache: Optional[Dict[int, types.DialogFilter]] = None
        # Serialize folder updates to avoid concurrent races across messages
        self._lock = asyncio.Lock()

    async def _list_filters(self, force_refresh: bool = False) -> Dict[int, types.DialogFilter]:
        if self._filters_cache is None or force_refresh:
            res = await self._client(functions.messages.GetDialogFiltersRequest())
            self._filters_cache = {f.id: f for f in (getattr(res, "filters", []) or []) if isinstance(f, types.DialogFilter)}
        return self._filters_cache

    async def _update_filter(self, fid: int, df: types.DialogFilter) -> None:
        try:
            await self._client(functions.messages.UpdateDialogFilterRequest(id=fid, filter=df))
        except FilterIdInvalidError:
            res = await self._client(functions.messages.GetDialogFiltersRequest())
            filters = {f.id: f for f in (getattr(res, "filters", []) or []) if isinstance(f, types.DialogFilter)}
            current_ids = sorted(list(set(filters.keys()) | {fid}))
            await self._client(functions.messages.UpdateDialogFiltersOrderRequest(order=current_ids))
            await asyncio.sleep(1)
            await self._client(functions.messages.UpdateDialogFilterRequest(id=fid, filter=df))

    async def _ensure_ids_in_order(self, ids: Iterable[int]) -> None:
        """Ensure given folder ids are present in Telegram's filters order."""
        try:
            filters = await self._list_filters()
            current_ids = sorted(list(set(filters.keys()) | set(ids)))
            await self._client(functions.messages.UpdateDialogFiltersOrderRequest(order=current_ids))
        except Exception as e:
            logger.debug(f"_ensure_ids_in_order skipped: {e}")
        finally:
            await asyncio.sleep(0.2)
            await self._list_filters(force_refresh=True)

    def _peer_tuple(self, ip):
        return (getattr(ip, "user_id", None), getattr(ip, "chat_id", None), getattr(ip, "channel_id", None))

    def _same_peer(self, a, b):
        return self._peer_tuple(a) == self._peer_tuple(b)

    def _title_text(self, value):
        if isinstance(value, types.TextWithEntities):
            return str(getattr(value, "text", "")).strip()
        if isinstance(value, str):
            return value.strip()
        return ""

    def _find_by_title(self, filters: Dict[int, types.DialogFilter], title: str) -> Optional[int]:
        """Find a folder by its exact title."""
        target_title = title.strip()
        for fid, df in filters.items():
            current_title = self._title_text(df.title)
            if current_title == target_title:
                return fid
        return None

    def _pick_free_slot(self, filters: Dict[int, types.DialogFilter]) -> int:
        used = set(filters.keys())
        for i in range(2, 12): # Start from 2
            if i not in used:
                return i
        raise RuntimeError("All 10 Telegram folder slots are already used.")

    async def ensure_folders(self) -> None:
        """Ensure all predefined folders exist, creating them if necessary."""
        all_filters = await self._list_filters()
        
        current_titles = {self._title_text(df.title) for df in all_filters.values()}
        missing_titles = [t for t in FOLDER_TITLES if t not in current_titles]

        if not missing_titles:
            return

        self_peer = await self._client.get_input_entity('me')
        for title in missing_titles:
            new_fid = self._pick_free_slot(all_filters)
            new_df = types.DialogFilter(id=new_fid, title=title, include_peers=[self_peer], pinned_peers=[], exclude_peers=[])
            await self._update_filter(new_fid, new_df)
            all_filters[new_fid] = new_df # Update local copy for next iteration
            logger.info(f"Created folder '{title}' at slot {new_fid}")
        
        await asyncio.sleep(0.5)
        await self._list_filters(force_refresh=True)
        logger.debug("Folder cache refreshed after creation.")
    
    async def move_to_folder(self, title: str, peer, exclusive: bool = True) -> int:
        logger.debug(f"--- move_to_folder started: title='{title}' ---")
        if title not in FOLDER_TITLES:
            raise ValueError(f"Unknown folder title '{title}'")

        async with self._lock:
            ip = await self._client.get_input_entity(peer)
        
            if exclusive:
                current_filters = await self._list_filters(force_refresh=True)
                for fid, df in current_filters.items():
                    current_title = self._title_text(df.title)

                    if current_title == title:
                        continue

                    if current_title in FOLDER_TITLES and any(self._same_peer(p, ip) for p in (df.include_peers or [])):
                        new_peers = [p for p in df.include_peers if not self._same_peer(p, ip)]
                        df.include_peers = new_peers
                        await self._update_filter(fid, df)
                
                await self._list_filters(force_refresh=True)

            all_filters = await self._list_filters()
            filters_for_log = {f.id: self._title_text(f.title) for f in all_filters.values()}
            logger.debug(f"Looking for folder '{title}'. Available filters: {filters_for_log}")
            target_fid = self._find_by_title(all_filters, title)
        
            if target_fid is None:
                logger.warning(f"Folder '{title}' not found on first lookup. Retrying after delay...")
                await asyncio.sleep(1)
                all_filters = await self._list_filters(force_refresh=True)
                target_fid = self._find_by_title(all_filters, title)

            if target_fid is not None:
                df = all_filters[target_fid]
                if not any(self._same_peer(p, ip) for p in (df.include_peers or [])):
                    df.include_peers.append(ip)
                    await self._update_filter(target_fid, df)
                    await self._list_filters(force_refresh=True)
                return target_fid
            else:
                logger.error(f"FATAL: Folder '{title}' not found even after retry. Aborting move.")
                return -1 # Indicate error

    async def move_to_manual(self, peer): return await self.move_to_folder("M0", peer)
    async def move_to_bot(self, peer): return await self.move_to_folder("B0", peer)
    async def move_to_confirmation(self, peer): return await self.move_to_folder("C0", peer)

__all__ = ["FolderManager"]


# -----------------------------
# Functional API (test/export compat)
# -----------------------------

async def get_filters(client) -> List[types.DialogFilter]:
    res = await client(functions.messages.GetDialogFiltersRequest())
    return [f for f in (getattr(res, "filters", []) or []) if isinstance(f, types.DialogFilter)]


def _normalize_input_peer_key(peer: tl_types.TypeInputPeer) -> str:
    if isinstance(peer, tl_types.InputPeerUser):
        return f"user:{peer.user_id}"
    if isinstance(peer, tl_types.InputPeerChat):
        return f"chat:{peer.chat_id}"
    if isinstance(peer, tl_types.InputPeerChannel):
        return f"channel:{peer.channel_id}"
    if isinstance(peer, tl_types.InputPeerSelf):
        return "self"
    return str(peer)


async def _to_input_peer(client, entity) -> tl_types.TypeInputPeer:
    return await client.get_input_entity(entity)


def _build_dialog_filter(folder_id: int, title: str, include_peers: Optional[List[tl_types.TypeInputPeer]] = None) -> types.DialogFilter:
    return types.DialogFilter(
        id=folder_id,
        title=title,
        emoticon="",
        pinned_peers=[],
        include_peers=include_peers or [],
        exclude_peers=[],
    )


async def _get_filters(client) -> Dict[int, types.DialogFilter]:
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


async def _safe_update_filter(client, fid: int, df: types.DialogFilter) -> None:
    """Robustly update a dialog filter, ensuring the id is included in order first."""
    try:
        filters = await _get_filters(client)
        order_ids = sorted(list(set(filters.keys()) | {fid}))
        await client(functions.messages.UpdateDialogFiltersOrderRequest(order=order_ids))
        await asyncio.sleep(0.3)
        await client(functions.messages.UpdateDialogFilterRequest(id=fid, filter=df))
    except FilterIdInvalidError:
        # If it still fails, the session may be in a bad state.
        # A full refresh of filters might help on the next run.
        logger.warning(f"Filter update for id {fid} failed despite priming order.")
        # We don't re-raise, as the UI might want to continue.

async def ensure_filters(client) -> Dict[int, types.DialogFilter]:
    """
    Ensure that all folders defined in the FOLDERS mapping exist.
    Creates any missing folders with their specified IDs.
    """
    existing = await _get_filters(client)
    was_empty = not existing

    if was_empty:
        logger.info("on this account are not currently any folders, creating folders")

    missing_ids = [fid for fid in FOLDERS.keys() if fid not in existing]

    if missing_ids:
        all_ids = sorted(list(set(existing.keys()) | set(FOLDERS.keys())))
        try:
            await client(functions.messages.UpdateDialogFiltersOrderRequest(order=all_ids))
            await asyncio.sleep(0.5)
        except Exception as e:
            logger.warning(f"Could not update dialog filter order: {e}")

        for fid in missing_ids:
            name = FOLDERS[fid]
            # Create with self as a placeholder peer to satisfy API constraints
            self_peer = await client.get_input_entity('me')
            df = _build_dialog_filter(fid, name, include_peers=[self_peer])
            await _safe_update_filter(client, fid, df)
        
        if was_empty:
            logger.info("folders created")
        
        existing = await _get_filters(client)

    return {fid: existing[fid] for fid in FOLDERS.keys() if fid in existing}


async def add_peer_to(client, folder_id: int, peer: object) -> None:
    by_id = await current_filters(client)
    existing = by_id.get(folder_id)
    input_peer = await _to_input_peer(client, peer)
    input_key = _normalize_input_peer_key(input_peer)
    if existing is None:
        title = FOLDERS.get(folder_id, f"Folder {folder_id}")
        desired = _build_dialog_filter(folder_id, title, include_peers=[input_peer])
        await _safe_update_filter(client, folder_id, desired)
        return
    existing_keys = {_normalize_input_peer_key(p) for p in getattr(existing, "include_peers", [])}
    if input_key in existing_keys:
        return
    new_peers = list(getattr(existing, "include_peers", []) or []) + [input_peer]
    title = existing.title.text if isinstance(existing.title, types.TextWithEntities) else (FOLDERS.get(folder_id, str(existing.title)))
    desired = _build_dialog_filter(folder_id, title, include_peers=new_peers)
    await _safe_update_filter(client, folder_id, desired)


async def remove_peer_from(client, folder_id: int, peer: object) -> None:
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
    title = existing.title.text if isinstance(existing.title, types.TextWithEntities) else (FOLDERS.get(folder_id, str(existing.title)))
    desired = _build_dialog_filter(folder_id, title, include_peers=new_peers)
    await _safe_update_filter(client, folder_id, desired)


async def current_filters(client) -> Dict[int, types.DialogFilter]:
    current = await get_filters(client)
    return {f.id: f for f in current}


async def move_peer_to(client, target_folder_id: int, peer: object) -> None:
    ip = await client.get_input_entity(peer)
    
    filters = await ensure_filters(client)

    # Remove from all known folders except the target one
    for fid, df in list(filters.items()):
        if fid == target_folder_id:
            continue
        
        title_val = df.title.text if isinstance(df.title, types.TextWithEntities) else str(df.title)
        if title_val in FOLDER_NAMES:
            before = list(df.include_peers or [])
            after = [p for p in before if not _same_peer(p, ip)]
            if before != after:
                df2 = types.DialogFilter(
                    id=fid, title=df.title, emoticon=getattr(df, "emoticon", ""),
                    pinned_peers=list(df.pinned_peers or []), include_peers=after,
                    exclude_peers=list(df.exclude_peers or []),
                )
                await _safe_update_filter(client, fid, df2)
    
    # Add to target
    target = filters.get(target_folder_id)
    if not target:
        raise RuntimeError(f"Target folder id {target_folder_id} not found after ensuring filters")
    
    peers = list(target.include_peers or [])
    if not any(_same_peer(p, ip) for p in peers):
        peers.append(ip)
        target2 = types.DialogFilter(
            id=target_folder_id, title=target.title, emoticon=getattr(target, "emoticon", ""),
            pinned_peers=list(target.pinned_peers or []), include_peers=peers,
            exclude_peers=list(target.exclude_peers or []),
        )
        await _safe_update_filter(client, target_folder_id, target2)
    # The actual logging of the move will be handled in the handler for more context


__all__ += [
    "FOLDERS",
    "FOLDER_NAMES",
    "get_filters",
    "ensure_filters",
    "add_peer_to",
    "remove_peer_from",
    "current_filters",
    "move_peer_to",
]


