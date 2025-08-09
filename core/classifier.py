from __future__ import annotations

from typing import List, Optional, Tuple, Dict, Any

from .llm import LLM, LLMReject
from .persistence import template_already_used, get_used_templates


async def classify_and_maybe_reply(
    llm: LLM, text: str, history: List[str], threshold: float, *, peer_id: Optional[str] = None, folder: str = "BOT", paylink: Optional[str] = None
) -> tuple[str, float, Optional[str]]:
    """Classify text with LLM and decide whether to reply.

    Returns (intent, confidence, reply_or_none). When confidence < threshold,
    reply is None to force manual handling.
    """
    result = await llm.classify(text, history)
    intent = str(result.get("intent", "other"))
    confidence = float(result.get("confidence", 0.0))
    reply = result.get("reply")
    if confidence < threshold:
        return intent, confidence, None
    # Enforce template no-repeat if LLM suggests it in future evolutions
    if result.get("action") == "send_template" and peer_id and template_already_used(peer_id, str(result.get("template_key", ""))):
        return intent, confidence, None
    return intent, confidence, (str(reply) if reply is not None else None)


__all__ = ["classify_and_maybe_reply"]


