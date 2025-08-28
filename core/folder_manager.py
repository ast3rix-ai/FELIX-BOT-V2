from __future__ import annotations
import asyncio
from typing import Dict, Optional, Iterable, List, Tuple

from loguru import logger
from telethon.errors import FilterIdInvalidError
from telethon.tl import functions, types
from telethon.tl import types as tl_types

FOLDER_TITLES = ["B0", "M0", "C0"]

FOLDER_IDS = {
    "B0": 2,
    "M0": 3,
    "C0": 4,
}

FOLDERS: Dict[int, str] = {
    3: "M0",
    2: "B0",
    4: "C0",
}
FOLDER_NAMES: List[str] = ["M0", "B0", "C0"]

class FolderManager:
    def __init__(self, client):
        self._client = client
        self._filters_cache: Optional[Dict[int, types.DialogFilter]] = None
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
        target_title = title.strip()
        for fid, df in filters.items():
            current_title = self._title_text(df.title)
            if current_title == target_title:
                return fid
        return None
    
    async def move_to_folder(self, title: str, peer, exclusive: bool = True) -> int:
        if title not in FOLDER_TITLES:
            raise ValueError(f"Unknown folder title '{title}'")

        async with self._lock:
            ip = await self._client.get_input_entity(peer)

            # 1. Add the peer to the target folder, creating it if it doesn't exist.
            all_filters = await self._list_filters(force_refresh=True)
            target_fid = self._find_by_title(all_filters, title)
            
            if target_fid is None:
                target_fid = FOLDER_IDS[title]
                logger.info(f"Target folder '{title}' not found, creating at slot {target_fid}.")
                target_df = types.DialogFilter(id=target_fid, title=title, include_peers=[ip], pinned_peers=[], exclude_peers=[])
                await self._update_filter(target_fid, target_df)
                await self._ensure_ids_in_order({target_fid})
            else:
                target_df = all_filters.get(target_fid)
                if target_df and not any(self._same_peer(p, ip) for p in (target_df.include_peers or [])):
                    target_df.include_peers.append(ip)
                    await self._update_filter(target_fid, target_df)

            # 2. If exclusive, now forcefully remove the peer from all other managed folders.
            if exclusive:
                for other_title in FOLDER_TITLES:
                    if other_title == title:
                        continue
                    
                    other_fid = FOLDER_IDS[other_title]
                    current_filters = await self._list_filters(force_refresh=True)
                    other_df = current_filters.get(other_fid)

                    if other_df and any(self._same_peer(p, ip) for p in (other_df.include_peers or [])):
                        logger.info(f"Exclusively moving: removing peer from '{other_title}' (slot {other_fid}).")
                        new_peers = [p for p in other_df.include_peers if not self._same_peer(p, ip)]
                        other_df.include_peers = new_peers
                        await self._update_filter(other_fid, other_df)

            # 3. Final refresh for consistency.
            await self._list_filters(force_refresh=True)
            return target_fid

    async def move_to_manual(self, peer): return await self.move_to_folder("M0", peer)
    async def move_to_bot(self, peer): return await self.move_to_folder("B0", peer)
    async def move_to_confirmation(self, peer): return await self.move_to_folder("C0", peer)

__all__ = ["FolderManager"]


# -----------------------------
# Functional API (test/export compat)
# -----------------------------

async def get_filters(client) -> List[types.DialogFilter]:
    res = await client(functions.messages.GetDialogFiltersRequest())
    
    # Handle different response formats
    if isinstance(res, list):
        # Response is directly a list of filters
        filters_list = res
    elif hasattr(res, 'filters'):
        # Response is an object with a filters attribute
        filters_list = getattr(res, "filters", []) or []
    else:
        # Unknown response format
        filters_list = []
    
    return [f for f in filters_list if isinstance(f, types.DialogFilter)]


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
    logger.info(f"Raw GetDialogFiltersRequest response type: {type(res)}")
    
    # Handle different response formats
    if isinstance(res, list):
        # Response is directly a list of filters
        filters_list = res
        logger.info(f"Response is a direct list with {len(filters_list)} items")
    elif hasattr(res, 'filters'):
        # Response is an object with a filters attribute
        filters_list = getattr(res, "filters", []) or []
        logger.info(f"Response has filters attribute with {len(filters_list)} items")
    else:
        # Unknown response format
        logger.error(f"Unknown response format: {type(res)}, attributes: {dir(res)}")
        filters_list = []
    
    existing: Dict[int, types.DialogFilter] = {}
    for i, f in enumerate(filters_list):
        logger.info(f"Filter {i}: type={type(f)}, is_DialogFilter={isinstance(f, types.DialogFilter)}")
        if isinstance(f, types.DialogFilter):
            logger.info(f"Adding filter {f.id}: {f.title}")
            existing[f.id] = f
        else:
            logger.info(f"Skipping non-DialogFilter type: {type(f)}")
    
    logger.info(f"Final existing filters dict keys: {list(existing.keys())}")
    return existing


def _peer_tuple(ip) -> Tuple[Optional[int], Optional[int], Optional[int]]:
    return (getattr(ip, "user_id", None), getattr(ip, "chat_id", None), getattr(ip, "channel_id", None))


def _same_peer(a, b) -> bool:
    return _peer_tuple(a) == _peer_tuple(b)


async def _safe_update_filter(client, fid: int, df: types.DialogFilter) -> bool:
    """Robustly update a dialog filter, ensuring the id is included in order first."""
    try:
        # For existing folders, we might still need to update order
        filters = await _get_filters(client)
        if fid not in filters:
            # For new folders, ensure order includes this ID
            order_ids = sorted(list(set(filters.keys()) | {fid}))
            logger.info(f"Updating filter order to include new folder {fid}: {order_ids}")
            await client(functions.messages.UpdateDialogFiltersOrderRequest(order=order_ids))
            await asyncio.sleep(0.5)
        
        logger.info(f"Updating filter {fid} with title: {df.title}")
        await client(functions.messages.UpdateDialogFilterRequest(id=fid, filter=df))
        logger.info(f"Successfully updated filter {fid}")
        return True
    except FilterIdInvalidError as e:
        logger.error(f"Filter update for id {fid} failed with FilterIdInvalidError: {e}")
        return False
    except Exception as e:
        logger.error(f"Filter update for id {fid} failed with unexpected error: {e}")
        return False

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
        # Update order once for all folders to avoid conflicts
        all_ids = sorted(list(set(existing.keys()) | set(FOLDERS.keys())))
        logger.info(f"Setting up filter order for all folders: {all_ids}")
        try:
            await client(functions.messages.UpdateDialogFiltersOrderRequest(order=all_ids))
            await asyncio.sleep(1.0)  # Give more time for order update
            logger.info("Filter order updated successfully")
        except Exception as e:
            logger.warning(f"Could not update dialog filter order: {e}")

        # Create all missing folders without individual order updates
        self_peer = await client.get_input_entity('me')
        for fid in missing_ids:
            name = FOLDERS[fid]
            logger.info(f"Creating folder {name} (ID: {fid})")
            df = _build_dialog_filter(fid, name, include_peers=[self_peer])
            try:
                await client(functions.messages.UpdateDialogFilterRequest(id=fid, filter=df))
                logger.info(f"Successfully created folder {name} (ID: {fid})")
            except Exception as e:
                logger.error(f"Failed to create folder {name} (ID: {fid}): {e}")
        
        if was_empty:
            logger.info("folders created")
        
        # Give Telegram API time to process all the folder creations
        await asyncio.sleep(2.0)  # Increased delay
        
        # Test: Try to get filters immediately after creation to see raw response
        logger.info("Testing immediate filter retrieval after creation...")
        test_filters = await _get_filters(client)
        logger.info(f"Immediate test retrieved {len(test_filters)} filters")
        
        # Refresh filters with a retry mechanism to handle timing issues
        for attempt in range(5):  # Increased attempts
            logger.info(f"Checking folder visibility (attempt {attempt + 1}/5)")
            existing = await _get_filters(client)
            existing_ids = list(existing.keys())
            logger.info(f"Currently visible folder IDs: {existing_ids}")
            missing = [fid for fid in FOLDERS.keys() if fid not in existing]
            if not missing:
                logger.info("All folders are now visible")
                break
            logger.warning(f"Still missing folders: {missing}")
            if attempt < 4:  # Don't sleep on the last attempt
                await asyncio.sleep(1.0)  # Increased sleep time
        
        if missing:
            logger.error(f"Some folders still missing after all retries: {missing}")
            logger.error("This might be a Telegram API issue or account limitation")

    return {fid: existing[fid] for fid in FOLDERS.keys() if fid in existing}


async def add_peer_to(client, folder_id: int, peer: object) -> None:
    by_id = await current_filters(client)
    existing = by_id.get(folder_id)
    input_peer = await _to_input_peer(client, peer)
    input_key = _normalize_input_peer_key(input_peer)
    if existing is None:
        title = FOLDERS.get(folder_id, f"Folder {folder_id}")
        desired = _build_dialog_filter(folder_id, title, include_peers=[input_peer])
        success = await _safe_update_filter(client, folder_id, desired)
        if not success:
            logger.error(f"Failed to create folder {folder_id} when adding peer")
        return
    existing_keys = {_normalize_input_peer_key(p) for p in getattr(existing, "include_peers", [])}
    if input_key in existing_keys:
        return
    new_peers = list(getattr(existing, "include_peers", []) or []) + [input_peer]
    title = existing.title.text if isinstance(existing.title, types.TextWithEntities) else (FOLDERS.get(folder_id, str(existing.title)))
    desired = _build_dialog_filter(folder_id, title, include_peers=new_peers)
    success = await _safe_update_filter(client, folder_id, desired)
    if not success:
        logger.error(f"Failed to add peer to folder {folder_id}")


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
    success = await _safe_update_filter(client, folder_id, desired)
    if not success:
        logger.error(f"Failed to remove peer from folder {folder_id}")


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
                success = await _safe_update_filter(client, fid, df2)
                if not success:
                    logger.error(f"Failed to remove peer from folder {fid}")
    
    # Add to target
    target = filters.get(target_folder_id)
    if not target:
        # Try refreshing filters one more time in case of timing issues
        logger.warning(f"Target folder id {target_folder_id} not found, refreshing filters...")
        await asyncio.sleep(0.5)
        filters = await ensure_filters(client)
        target = filters.get(target_folder_id)
        
        if not target:
            raise RuntimeError(f"Target folder id {target_folder_id} not found after ensuring filters and refresh")
    
    peers = list(target.include_peers or [])
    
    # Remove self (placeholder) peer if it exists and we're adding a real chat
    self_peer = await client.get_input_entity('me')
    original_peer_count = len(peers)
    peers = [p for p in peers if not _same_peer(p, self_peer)]
    if len(peers) < original_peer_count:
        logger.info(f"Removed placeholder 'self' peer from folder {target_folder_id}")
    
    # Add the new peer if it's not already there
    if not any(_same_peer(p, ip) for p in peers):
        peers.append(ip)
        logger.info(f"Added new peer to folder {target_folder_id}")
    else:
        logger.info(f"Peer already exists in folder {target_folder_id}")
        
    # Only update if there are changes
    if set(_normalize_input_peer_key(p) for p in peers) != set(_normalize_input_peer_key(p) for p in (target.include_peers or [])):
        target2 = types.DialogFilter(
            id=target_folder_id, title=target.title, emoticon=getattr(target, "emoticon", ""),
            pinned_peers=list(target.pinned_peers or []), include_peers=peers,
            exclude_peers=list(target.exclude_peers or []),
        )
        success = await _safe_update_filter(client, target_folder_id, target2)
        if not success:
            logger.error(f"Failed to update folder {target_folder_id} with new peer")
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


