from __future__ import annotations

from typing import List, Optional, Tuple

from .llm import LLM, LLMReject


async def classify_and_maybe_reply(
    llm: LLM, text: str, history: List[str], threshold: float
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
    return intent, confidence, (str(reply) if reply is not None else None)


__all__ = ["classify_and_maybe_reply"]


