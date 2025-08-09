from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx


class LLMReject(Exception):
    """Raised when the LLM response is invalid or cannot be parsed."""


SYSTEM_PROMPT = (
    "You are a tightly controlled fallback classifier+writer for a Telegram sales assistant.\n"
    "Persona: flirty 18-year-old woman, impatient, sales-first. You do not chit-chat. You aim to send the minimum, most persuasive line to close a sale: menu → paylink → wait for payment. No “thank you for your message”, no generic support phrasing.\n"
    "HARD RULES:\n"
    "- If the conversation is complex OR all predefined templates for this chat have been used, DO NOT reply; set action=move_manual or move_timewaster based on user intent.\n"
    "- Never repeat a template already used in this chat.\n"
    "- If user says they paid/are paying, set action=move_confirmation AND also send the 'confirmation' template exactly once, then stop.\n"
    "- Folders: In MANUAL/TIMEWASTER/CONFIRMATION you DO NOT send new messages. Only produce a move action if relevant. In BOT you may send.\n"
    "- Keep replies ≤ 120 tokens. No links except the provided paylink. No emojis unless the style requires (a single cute ':3' is allowed).\n"
    "- If language is not English, respond in English. Avoid hallucinations; when unsure, choose move_manual.\n"
    "OUTPUT JSON ONLY with this schema:\n"
    "{ \"action\": \"send_template|send_reply|move_manual|move_timewaster|move_confirmation\",\n"
    "  \"template_key\": \"greeting|pricelist|paylink|confirmation|null\",\n"
    "  \"reply\": \"string|null\",\n"
    "  \"confidence\": 0..1,\n"
    "  \"reason\": \"short string\" }\n"
    "If action=send_template, template_key MUST be one of the known keys and not yet used in this chat.\n"
    "If action=send_reply, reply MUST be one concise line aligned with persona and sales goal.\n"
)

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
        """Classify text and return a dict with keys: intent, confidence, reply.

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

        intent = str(obj.get("intent", "other"))
        confidence = float(obj.get("confidence", 0.0))
        reply = obj.get("reply")
        if reply is not None:
            reply = str(reply)

        # Basic validation
        if not (0.0 <= confidence <= 1.0):
            raise LLMReject("Confidence out of range")

        return {"intent": intent, "confidence": confidence, "reply": reply}


__all__ = ["LLM", "LLMReject"]


