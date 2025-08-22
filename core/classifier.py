from __future__ import annotations

from typing import List, Optional, Tuple, Dict, Any

from .llm import LLM, LLMReject
from .persistence import template_already_used, get_used_templates
from .config import load_settings


async def choose_template_or_move(
    llm: LLM,
    text: str,
    history: List[str],
    folder: str,
    used_templates: List[str],
    threshold: float,
) -> Tuple[str, Dict[str, Any]]:
    """Ask LLM for the next template to send or a move action.

    Returns (action, payload). Actions: send_template, move_manual, move_timewaster, move_confirmation.
    """
    settings = load_settings()
    result = await llm.classify(text, history)
    # Enforce template-only when in classify mode
    if settings.llm_mode == "classify":
        action = str(result.get("action", "move_manual"))
        key = result.get("template_key")
        if action == "send_template":
            if key not in {"greeting", "pricelist", "paylink", "confirmation"}:
                return ("move_manual", {"reason": "bad_key"})
        else:
            key = None
    else:
        action = str(result.get("action", "move_manual"))
        key = result.get("template_key")

    confidence = float(result.get("confidence", 0.0))
    if confidence < threshold:
        return ("move_manual", {})

    if action == "send_template":
        if key in (used_templates or []):
            return ("move_manual", {"reason": "repeat_template"})
        return ("send_template", {"key": key})
    if action == "move_confirmation":
        return ("move_confirmation", {"send_key": "confirmation"})
    if action == "move_timewaster":
        return ("move_timewaster", {})
    return ("move_manual", {})


__all__ = ["choose_template_or_move"]


async def classify_and_maybe_reply(
    llm: LLM,
    text: str,
    history: List[str],
    threshold: float,
    *,
    peer_id: Optional[str] = None,
    folder: str = "BOT",
    paylink: Optional[str] = None,
) -> Tuple[str, float, Optional[str]]:
    """Compatibility wrapper for legacy tests: returns (intent, confidence, reply_or_none).

    Supports both old LLM outputs with keys (intent, confidence, reply) and new
    chooser outputs with keys (action, template_key, confidence). For the latter,
    no free-text is returned.
    """
    result = await llm.classify(text, history)
    confidence = float(result.get("confidence", 0.0))
    # Old shape: intent/reply present
    if "intent" in result or "reply" in result:
        intent = str(result.get("intent", "other"))
        reply = result.get("reply")
        if confidence < threshold:
            return intent, confidence, None
        return intent, confidence, (str(reply) if isinstance(reply, str) and reply else None)
    # New chooser shape: never returns prose
    return "other", confidence, None


