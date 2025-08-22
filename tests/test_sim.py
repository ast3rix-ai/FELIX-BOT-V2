import pytest

from core.sim import SimEngine, SimFolder


@pytest.mark.asyncio
async def test_greeting_stays_in_bot():
    engine = SimEngine(templates={"greeting": "Hello", "pricelist": "Prices"})
    engine.add_peer("u1", "User 1")
    await engine.incoming("u1", "hi")
    assert engine.peers["u1"].folder == SimFolder.BOT
    assert any(e.kind == "send" for e in engine.events)


@pytest.mark.asyncio
async def test_not_interested_moves_timewaster():
    engine = SimEngine(templates={"greeting": "Hello"})
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


@pytest.mark.asyncio
async def test_affirmative_advances_funnel():
    from core.persistence import reset_peer_history

    pid = "u_affirm1"
    reset_peer_history(pid)
    engine = SimEngine(templates={"greeting": "Hello", "pricelist": "Prices", "paylink": "Pay here"})
    engine.add_peer(pid, "Alice")
    await engine.incoming(pid, "hey")  # greeting
    await engine.incoming(pid, "yes")  # affirmative
    sends = [e for e in engine.events if e.kind == "send"]
    assert any(s.payload.get("template") == "greeting" for s in sends)
    assert any(s.payload.get("template") == "pricelist" for s in sends)


@pytest.mark.asyncio
async def test_how_do_i_pay_routes_to_paylink():
    from core.persistence import reset_peer_history
    pid = "u_paylink1"
    reset_peer_history(pid)
    engine = SimEngine(templates={"greeting": "Hello", "pricelist": "Prices", "paylink": "Pay here"})
    engine.add_peer(pid, "Alice")
    await engine.incoming(pid, "hey")
    # ensure we're still in BOT for the next message
    engine.peers[pid].folder = SimFolder.BOT
    await engine.incoming(pid, "how do i pay ?")
    sends = [e for e in engine.events if e.kind == "send"]
    assert any(s.payload.get("template") == "paylink" for s in sends)


@pytest.mark.asyncio
async def test_manual_move_is_unread():
    engine = SimEngine(templates={"greeting": "Hello"})
    engine.add_peer("u2", "Bob")
    await engine.incoming("u2", "weird off-topic long text that breaks rules")
    kinds = [e.kind for e in engine.events]
    assert "move_folder" in kinds and "read" not in kinds


@pytest.mark.asyncio
async def test_paylink_not_empty():
    engine = SimEngine(templates={"paylink": "{PAYLINK}"})
    engine.add_peer("u_pay", "Alice")
    await engine.incoming("u_pay", "how do i pay ?")
    sends = [e for e in engine.events if e.kind == "send"]
    assert any(s.payload.get("template") == "paylink" and str(s.payload.get("text", "")).strip() for s in sends)


@pytest.mark.asyncio
async def test_synonyms_greeting_and_pay():
    engine = SimEngine(templates={"greeting": "hi", "paylink": "{PAYLINK}"})
    engine.add_peer("u_syn", "Bob")
    await engine.incoming("u_syn", "hey baby")
    await engine.incoming("u_syn", "payment?")
    sends = [e for e in engine.events if e.kind == "send"]
    assert any(s.payload.get("template") == "greeting" for s in sends)
    assert any(s.payload.get("template") == "paylink" for s in sends)


@pytest.mark.asyncio
async def test_menu_content_variants():
    engine = SimEngine(templates={"pricelist": "Prices"})
    engine.add_peer("u_menu", "C")
    await engine.incoming("u_menu", "content?")
    sends = [e for e in engine.events if e.kind == "send"]
    assert any(s.payload.get("template") == "pricelist" for s in sends)


@pytest.mark.asyncio
async def test_payment_intent_heuristic_without_llm(monkeypatch):
    engine = SimEngine(templates={"greeting": "Hi", "pricelist": "Prices", "paylink": "{PAYLINK}", "confirmation": "ok"})
    engine.add_peer("u1", "Alice")
    await engine.incoming("u1", "hey")
    await engine.incoming("u1", "prices?")
    await engine.incoming("u1", "how do i pay ?")
    import core.classifier as cls
    def raise_down(*a, **k):
        raise RuntimeError("down")
    monkeypatch.setattr(cls, "choose_template_or_move", raise_down)
    await engine.incoming("u1", "here you go")
    sends = [e for e in engine.events if e.kind == "send"]
    assert any(s.payload.get("template") == "confirmation" for s in sends)
    last_folder = [e.payload.get("folder") for e in engine.events if e.kind == "move_folder"][-1]
    assert last_folder == "CONFIRMATION"
    await engine.incoming("u1", "ok?")
    assert engine.events[-1].kind == "ignored"


@pytest.mark.asyncio
async def test_yes_i_am_after_greeting():
    engine = SimEngine(templates={"greeting": "Hello", "pricelist": "Prices"})
    engine.add_peer("u_affirm2", "Alice")
    await engine.incoming("u_affirm2", "hey")
    await engine.incoming("u_affirm2", "yes i am")
    sends = [e for e in engine.events if e.kind == "send"]
    assert any(s.payload.get("template") == "pricelist" for s in sends)


