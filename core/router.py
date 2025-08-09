from __future__ import annotations

from typing import Dict, Optional, Tuple


def _normalize(text: str) -> str:
    return " ".join(text.lower().strip().split())


def route(message_text: str, rules: Dict) -> Tuple[str, Dict]:
    """Return (action, payload) for a given message text.

    Actions: send_template, move_timewaster, move_confirmation, manual
    """
    text = _normalize(message_text)

    if any(k in text for k in ["hi", "hey", "hello"]):
        return ("send_template", {"template_key": "welcome"})

    if any(k in text for k in ["price", "pricelist"]):
        return ("send_template", {"template_key": "pricelist"})

    if any(k in text for k in ["how pay", "how to pay", "payment"]):
        return ("send_template", {"template_key": "how_to_pay"})

    if any(k in text for k in ["not interested", "stop", "no thanks"]):
        return ("move_timewaster", {})

    if any(k in text for k in ["paid", "sending"]):
        return ("move_confirmation", {})

    return ("manual", {})


__all__ = ["route"]


