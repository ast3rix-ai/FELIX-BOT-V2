import json
from types import SimpleNamespace

import pytest

from core.classifier import classify_and_maybe_reply
from core.llm import LLM


class DummyLLM(LLM):
    def __init__(self, payload):
        super().__init__(url="http://localhost", model="dummy")
        self._payload = payload

    async def classify(self, text, history):
        return self._payload


@pytest.mark.asyncio
async def test_low_confidence_goes_manual():
    llm = DummyLLM({"intent": "other", "confidence": 0.5, "reply": "Hi"})
    intent, conf, reply = await classify_and_maybe_reply(llm, "text", [], threshold=0.75)
    assert reply is None


@pytest.mark.asyncio
async def test_valid_json_sends_reply():
    llm = DummyLLM({"intent": "greeting", "confidence": 0.9, "reply": "Hello!"})
    intent, conf, reply = await classify_and_maybe_reply(llm, "text", [], threshold=0.75)
    assert reply == "Hello!"


