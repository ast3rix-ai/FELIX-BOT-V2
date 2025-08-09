import pytest

from core.sim import SimEngine, SimFolder


@pytest.mark.asyncio
async def test_greeting_stays_in_bot():
    engine = SimEngine(templates={"welcome": "Hello", "pricelist": "Prices"})
    engine.add_peer("u1", "User 1")
    await engine.incoming("u1", "hi")
    assert engine.peers["u1"].folder == SimFolder.BOT
    assert any(e.kind == "send" for e in engine.events)


@pytest.mark.asyncio
async def test_not_interested_moves_timewaster():
    engine = SimEngine(templates={"welcome": "Hello"})
    engine.add_peer("u1", "User 1")
    await engine.incoming("u1", "not interested")
    assert engine.peers["u1"].folder == SimFolder.TIMEWASTER
    # no send after move
    last = [e for e in engine.events if e.payload.get("peer_id") == "u1"][-1]
    assert last.kind == "move_folder"


@pytest.mark.asyncio
async def test_offtopic_llm_disabled_goes_manual():
    engine = SimEngine(templates={"welcome": "Hello"}, classifier=None)
    engine.add_peer("u1", "User 1")
    await engine.incoming("u1", "random")
    assert engine.peers["u1"].folder == SimFolder.MANUAL


@pytest.mark.asyncio
async def test_offtopic_llm_low_confidence_manual():
    async def fake_clf(text, history):
        return {"intent": "other", "confidence": 0.6, "reply": "no"}

    engine = SimEngine(templates={"welcome": "Hello"}, classifier=fake_clf, threshold=0.75)
    engine.add_peer("u1", "User 1")
    await engine.incoming("u1", "random")
    assert engine.peers["u1"].folder == SimFolder.MANUAL


@pytest.mark.asyncio
async def test_offtopic_llm_high_confidence_sends():
    async def fake_clf(text, history):
        return {"intent": "greeting", "confidence": 0.9, "reply": "Hi!"}

    engine = SimEngine(templates={"welcome": "Hello"}, classifier=fake_clf, threshold=0.75)
    engine.add_peer("u1", "User 1")
    await engine.incoming("u1", "random")
    # stays in BOT, sends a message
    assert engine.peers["u1"].folder == SimFolder.BOT
    assert any(e.kind == "send" and e.payload.get("peer_id") == "u1" for e in engine.events)


