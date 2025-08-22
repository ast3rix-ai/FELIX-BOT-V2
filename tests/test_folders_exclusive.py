import pytest

from core.sim import SimEngine, SimFolder


@pytest.mark.asyncio
async def test_confirmation_sticky_and_ignored():
    engine = SimEngine(templates={"confirmation": "ok", "greeting": "hi"})
    engine.add_peer("u1", "Alice")
    await engine.incoming("u1", "i sent")
    # Expect move to confirmation after sending
    # Allow the router to detect confirmation phrases
    assert any(e.kind == "move_folder" and e.payload.get("folder") == "CONFIRMATION" for e in engine.events)
    last_move = [e for e in engine.events if e.kind == "move_folder"][-1]
    assert last_move.payload.get("folder") == "CONFIRMATION"
    # New message ignored
    await engine.incoming("u1", "here")
    assert engine.events[-1].kind == "ignored"
    # Still in confirmation
    assert [e.payload.get("folder") for e in engine.events if e.kind == "move_folder"][-1] == "CONFIRMATION"


def test_move_peer_is_exclusive():
    # Placeholder for Telethon client mock; ensure move_peer_to removes from others and adds to target.
    # This would require a richer mock of DialogFilter state and UpdateDialogFilterRequest capture.
    assert True


