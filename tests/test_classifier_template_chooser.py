import pytest

from core.sim import SimEngine


@pytest.mark.asyncio
async def test_ofcourse_after_greeting_picks_pricelist(monkeypatch):
    engine = SimEngine(templates={"greeting": "hi", "pricelist": "Prices"})
    engine.add_peer("u1", "Alice")
    await engine.incoming("u1", "hey")  # greeting

    from core.llm import LLM

    mocked = {"action": "send_template", "template_key": "pricelist", "confidence": 0.92, "reason": "affirmative"}
    async def fake_classify(self, text, history):
        return mocked

    monkeypatch.setattr(LLM, "classify", fake_classify)

    await engine.incoming("u1", "ofcourse")
    sends = [e for e in engine.events if e.kind == "send"]
    assert any(s.payload.get("template") == "pricelist" for s in sends)


