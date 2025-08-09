from __future__ import annotations

import re
from typing import Dict, Optional, Tuple

from .persistence import template_already_used


def _normalize(text: str) -> str:
    return " ".join(text.lower().strip().split())


def route(message_text: str, rules: Dict, peer_id: Optional[str] = None) -> Tuple[str, Dict]:
    """Return (action, payload) for a given message text.

    Actions: send_template, move_timewaster, move_confirmation, manual
    """
    text = _normalize(message_text)

    kw = rules.get("keywords", {}) if isinstance(rules, dict) else {}

    # Fallback heuristics when no rules are provided
    if not kw:
        if any(k in text for k in ["hi", "hey", "hello", "yo", "sup"]):
            if peer_id and template_already_used(peer_id, "greeting"):
                return ("manual", {"reason": "repeat_template"})
            return ("send_template", {"key": "greeting"})
        if any(k in text for k in ["price", "menu", "pricelist"]):
            if peer_id and template_already_used(peer_id, "pricelist"):
                return ("manual", {"reason": "repeat_template"})
            return ("send_template", {"key": "pricelist"})
        if any(k in text for k in ["how pay", "how to pay", "payment", "paypal", "paylink"]):
            return ("send_template", {"key": "paylink"})
        if any(k in text for k in ["not interested", "stop", "go away", "leave me", "nah"]):
            return ("move_timewaster", {})
        if any(k in text for k in ["paid", "sending"]):
            return ("move_confirmation", {"send_key": "confirmation"})
        return ("manual", {})
    def match_any(patterns):
        for pat in patterns:
            try:
                # Normalize double escapes like \\b -> \b for regex word boundaries
                norm = pat.replace("\\\\", "\\")
                if re.search(norm, text):
                    return True
            except re.error:
                continue
        return False

    if match_any(kw.get("greeting", [])):
        key = "greeting"
        if peer_id and template_already_used(peer_id, key):
            return ("manual", {"reason": "repeat_template"})
        return ("send_template", {"key": key})

    if match_any(kw.get("pricelist", [])):
        key = "pricelist"
        if peer_id and template_already_used(peer_id, key):
            return ("manual", {"reason": "repeat_template"})
        return ("send_template", {"key": key})

    if match_any(kw.get("paylink", [])):
        key = "paylink"
        # Allow resending paylink idempotently if desired; here we allow repeat
        return ("send_template", {"key": key})

    if match_any(kw.get("confirmation", [])) or ("paid" in text or "sending" in text):
        return ("move_confirmation", {"send_key": "confirmation"})

    notint = rules.get("not_interested", []) if isinstance(rules, dict) else []
    if match_any(notint):
        return ("move_timewaster", {})

    return ("manual", {})


__all__ = ["route"]


