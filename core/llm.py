from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx


class LLMReject(Exception):
    """Raised when the LLM response is invalid or cannot be parsed."""


SYSTEM_PROMPT = """
You are a STRICT FALLBACK CLASSIFIER for a Telegram sales assistant.
Persona context only helps you choose the next PREDEFINED TEMPLATE to send; you DO NOT write free-text unless explicitly allowed.

Allowed templates: greeting, pricelist, paylink, confirmation.
Allowed moves: move_manual, move_timewaster, move_confirmation.

Hard rules:
- Output JSON ONLY.
- Prefer sending a template if it advances the funnel (greeting→pricelist→paylink→confirmation).
- Never repeat a template already used in this chat.
- If user says they paid/are paying → action=move_confirmation (the app will send 'confirmation' template once, then move).
- If language isn’t English, interpret intent and still choose a template or move; do NOT translate or chat.
- If conversation is complex/ambiguous or all useful templates are already used → move_manual.
- In folders Manual/Timewaster/Confirmation you DO NOT send; choose a move if appropriate.
JSON schema:
{
  "action": "send_template|move_manual|move_timewaster|move_confirmation",
  "template_key": "greeting|pricelist|paylink|confirmation|null",
  "confidence": 0..1,
  "reason": "short"
}
"""

FEW_SHOT_MESSAGES = [
    {"role": "system", "content": SYSTEM_PROMPT},
    {"role": "user", "content": "hi"},
    {"role": "assistant", "content": '{"intent":"greeting","confidence":0.95,"reply":"Hello!"}'},
    {"role": "user", "content": "price?"},
    {"role": "assistant", "content": '{"intent":"price","confidence":0.9,"reply":null}'},
    {"role": "user", "content": "how pay"},
    {"role": "assistant", "content": '{"intent":"payment_info","confidence":0.9,"reply":null}'},
    {"role": "user", "content": "paid"},
    {"role": "assistant", "content": '{"intent":"confirmation","confidence":0.9,"reply":null}'},
    {"role": "user", "content": "not interested"},
    {"role": "assistant", "content": '{"intent":"not_interested","confidence":0.9,"reply":null}'},
    {"role": "user", "content": "(random off-topic)"},
    {"role": "assistant", "content": '{"intent":"other","confidence":0.4,"reply":null}'},
]


def _extract_json(text: str) -> Dict[str, Any]:
    # Remove fenced code if present
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
    if fenced:
        text = fenced.group(1)
    # Extract first JSON object
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise LLMReject("No JSON object found")
    snippet = text[start : end + 1]
    try:
        obj = json.loads(snippet)
    except Exception as exc:
        raise LLMReject(f"Invalid JSON: {exc}")
    if not isinstance(obj, dict):
        raise LLMReject("Top-level JSON must be an object")
    return obj


class LLM:
    def __init__(self, url: str, model: str, temperature: float = 0.1, timeout_s: int = 15) -> None:
        self.url = url.rstrip("/")
        self.model = model
        self.temperature = float(temperature)
        self.timeout_s = int(timeout_s)

    async def classify(self, text: str, history: List[str]) -> Dict[str, Any]:
        """Classify text and return a dict per SYSTEM_PROMPT.

        Raises LLMReject on invalid response.
        """
        messages: List[Dict[str, str]] = list(FEW_SHOT_MESSAGES)
        # Append past user messages as context (lightweight)
        for h in history[-5:]:
            messages.append({"role": "user", "content": h})
        messages.append({"role": "user", "content": text})

        payload = {
            "model": self.model,
            "messages": messages,
            "options": {"temperature": self.temperature},
            "stream": False,
        }

        endpoint = f"{self.url}/api/chat"
        try:
            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                resp = await client.post(endpoint, json=payload)
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            raise LLMReject(f"HTTP failure: {exc}")

        # Ollama chat response structure: { message: { role, content }, ... }
        try:
            content = data.get("message", {}).get("content") or data.get("response") or ""
            obj = _extract_json(content)
        except Exception as exc:
            raise LLMReject(f"Parse failure: {exc}")

        # Basic validation
        confidence = float(obj.get("confidence", 0.0))
        if not (0.0 <= confidence <= 1.0):
            raise LLMReject("Confidence out of range")

        action = str(obj.get("action", "move_manual"))
        template_key = obj.get("template_key")
        template_key = str(template_key) if template_key is not None else None

        return {"action": action, "template_key": template_key, "confidence": confidence, "reason": obj.get("reason")}


__all__ = ["LLM", "LLMReject"]


