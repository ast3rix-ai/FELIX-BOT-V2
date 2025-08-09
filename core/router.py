from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional


@dataclass
class RouteDecision:
    action: str  # "template" or "manual" or "move"
    template_key: Optional[str] = None
    move_to_folder_id: Optional[int] = None
    intent: Optional[str] = None


def _normalize(text: str) -> str:
    return " ".join(text.lower().strip().split())


def decide_action(message_text: str, rules: Dict) -> RouteDecision:
    text = _normalize(message_text)

    # Simple keyword intents; can be extended with YAML rules later
    if any(k in text for k in ["hi", "hey", "hello"]):
        return RouteDecision(action="template", template_key="welcome", intent="greeting")

    if any(k in text for k in ["price", "pricelist"]):
        return RouteDecision(action="template", template_key="pricelist", intent="price")

    if any(k in text for k in ["how pay", "how to pay", "payment"]):
        return RouteDecision(action="template", template_key="how_to_pay", intent="payment_info")

    if any(k in text for k in ["not interested", "stop", "no thanks"]):
        return RouteDecision(action="move", move_to_folder_id=3, intent="not_interested")

    if any(k in text for k in ["paid", "sending"]):
        return RouteDecision(action="move", move_to_folder_id=4, intent="confirmation")

    # Default: manual
    return RouteDecision(action="manual")


__all__ = ["RouteDecision", "decide_action"]


