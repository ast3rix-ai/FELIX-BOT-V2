import asyncio
from types import SimpleNamespace
from typing import Dict, List

import pytest
from telethon import functions, types

from core.folder_manager import ensure_filters, add_peer_to, remove_peer_from, current_filters, FOLDERS


class MockClient:
    def __init__(self) -> None:
        self._filters: Dict[int, types.DialogFilter] = {}

    async def __call__(self, request):
        if isinstance(request, functions.messages.GetDialogFiltersRequest):
            return types.messages.DialogFilters(filters=list(self._filters.values()))
        if isinstance(request, functions.messages.UpdateDialogFilterRequest):
            f: types.DialogFilter = request.filter
            self._filters[f.id] = f
            return SimpleNamespace(ok=True)
        raise AssertionError(f"Unexpected request: {request}")

    async def get_input_entity(self, peer):
        # peer provided as ('user', id) etc.
        kind, pid = peer
        if kind == 'user':
            return types.InputPeerUser(user_id=pid, access_hash=0)
        if kind == 'chat':
            return types.InputPeerChat(chat_id=pid)
        if kind == 'channel':
            return types.InputPeerChannel(channel_id=pid, access_hash=0)
        raise AssertionError("Unknown peer kind")


@pytest.mark.asyncio
async def test_ensure_filters_creates_all():
    client = MockClient()
    result = await ensure_filters(client)  # type: ignore[arg-type]
    assert set(result.keys()) == set(FOLDERS.keys())
    assert all(isinstance(f, types.DialogFilter) for f in result.values())


@pytest.mark.asyncio
async def test_add_and_remove_peer():
    client = MockClient()
    await ensure_filters(client)  # type: ignore[arg-type]

    await add_peer_to(client, 2, ("user", 123))  # type: ignore[arg-type]
    cur = await current_filters(client)  # type: ignore[arg-type]
    peers = cur[2].include_peers
    assert any(isinstance(p, types.InputPeerUser) and p.user_id == 123 for p in peers)

    # idempotent add
    await add_peer_to(client, 2, ("user", 123))  # type: ignore[arg-type]
    cur = await current_filters(client)  # type: ignore[arg-type]
    peers2 = cur[2].include_peers
    assert len(peers2) == len(peers)

    await remove_peer_from(client, 2, ("user", 123))  # type: ignore[arg-type]
    cur = await current_filters(client)  # type: ignore[arg-type]
    peers3 = cur[2].include_peers
    assert not any(isinstance(p, types.InputPeerUser) and p.user_id == 123 for p in peers3)


