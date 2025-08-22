from __future__ import annotations

import re
import unicodedata
from typing import Dict, Optional, Tuple

from .persistence import template_already_used
from . import persistence


SPACE_RE = re.compile(r"\s+")
TRAIL_PUNCT_RE = re.compile(r"\s+([?.!,])")
AFFIRM_INLINE = re.compile(r"\b(yes|yeah|yep|yup|sure|of\s*course|ofcourse|ofc|absolutely|ready|i'?m in|interested)\b", re.I)


def normalize_text(s: str) -> str:
    s = unicodedata.normalize("NFKC", s)
    s = s.lower().strip()
    s = TRAIL_PUNCT_RE.sub(r"\1", s)
    s = SPACE_RE.sub(" ", s)
    return s


def match_any(patterns, text: str) -> bool:
    for pat in patterns:
        norm = pat.replace("\\\\", "\\")
        try:
            if re.search(norm, text, flags=re.IGNORECASE):
                return True
        except re.error:
            token = norm.strip("\\b")
            if token and token in text:
                return True
    return False


GREETING_SYNS = {
    "hi",
    "hey",
    "hello",
    "helo",
    "yo",
    "sup",
    "hiya",
    "howdy",
    "heyya",
    "heyyaaa",
    "hey baby",
    "hey babe",
    "hi babe",
    "hi baby",
}

MENU_SYNS = {
    "menu",
    "price",
    "prices",
    "pricelist",
    "list",
    "offer",
    "content",
    "what you have",
    "what u have",
    "what do you have",
}

PAY_SYNS = {
    "pay",
    "payment",
    "paypal",
    "paylink",
    "how do i pay",
    "how to i pay",
    "how to pay",
    "where do i send",
    "send money",
    "payment link",
    "payment info",
    "pay?",
}

CONFIRM_SYNS = {
    "paid",
    "i paid",
    "sending",
    "i sent",
    "sent",
    "payment sent",
}


def token_set(text: str) -> set[str]:
    return set(re.findall(r"[a-z]+", text))


def contains_any_phrase(text: str, phrases: set[str]) -> bool:
    for p in phrases:
        if p in text:
            return True
    return False


PAYMENT_INTENT_RE = re.compile(
    r"(here\s*(?:you|u)\s*go|there\s*(?:you|u)\s*go|just\s*sent|already\s*sent|money\s*sent|sent\s*it|"
    r"payment\s*(done|sent)|check(\s*it)?|proof|screenshot|receipt|txn|transaction|conf(irmation)?|"
    r"about\s*to\s*(send|pay)|gonna\s*(send|pay)|going\s*to\s*(send|pay)|i(?:'?m| am)\s*sending|i(?:'?ll| will)\s*(send|pay))",
    re.I,
)


def looks_like_payment_intent(text: str) -> bool:
    return bool(PAYMENT_INTENT_RE.search(text))


def is_affirmative_inline(text: str) -> bool:
    return bool(AFFIRM_INLINE.search(text))


def route_fast(message_text: str, rules: Dict, peer_id: Optional[str] = None) -> Tuple[str, Dict]:
    """Fast router: regex/keywords first, then simple affirmative context fallback only.

    Returns (action, payload).
    """
    text = normalize_text(message_text)

    kw = rules.get("keywords", {}) if isinstance(rules, dict) else {}

    def _match_any_local(patterns):
        return match_any(patterns, text)

    # Explicit keyword/regex checks (same order as route)
    if _match_any_local(kw.get("greeting", [])):
        key = "greeting"
        if peer_id and template_already_used(peer_id, key):
            return ("manual", {"reason": "repeat_template"})
        return ("send_template", {"key": key})

    if _match_any_local(kw.get("pricelist", [])):
        key = "pricelist"
        if peer_id and template_already_used(peer_id, key):
            return ("manual", {"reason": "repeat_template"})
        return ("send_template", {"key": key})

    if _match_any_local(kw.get("paylink", [])):
        key = "paylink"
        return ("send_template", {"key": key})

    if _match_any_local(kw.get("confirmation", [])) or ("paid" in text or "sending" in text):
        return ("move_confirmation", {"send_key": "confirmation"})

    notint = rules.get("not_interested", []) if isinstance(rules, dict) else []
    if _match_any_local(notint):
        return ("move_timewaster", {})

    # Context fallback: broadened affirmative
    # If no rules are provided, use simple heuristics first
    if not kw:
        # greetings
        if any(k in text for k in ["hi", "hey", "hello", "yo", "sup"]):
            if peer_id and template_already_used(peer_id, "greeting"):
                return ("manual", {"reason": "repeat_template"})
            return ("send_template", {"key": "greeting"})
        # pricelist
        if any(k in text for k in ["price", "menu", "pricelist", "content"]):
            if peer_id and template_already_used(peer_id, "pricelist"):
                return ("manual", {"reason": "repeat_template"})
            return ("send_template", {"key": "pricelist"})
        # paylink
        if any(k in text for k in [
            "how do i pay",
            "how to pay",
            "how pay",
            "payment",
            "paypal",
            "paylink",
            "where do i send",
            "where to i send",
            "payment link",
            "payment info",
            "pay?",
            "pay",
        ]):
            return ("send_template", {"key": "paylink"})
        # timewaster
        if any(k in text for k in ["not interested", "stop", "go away", "leave me", "nah"]):
            return ("move_timewaster", {})
        # confirmation
        if any(k in text for k in ["paid", "sending", "sent", "i sent"]):
            return ("move_confirmation", {"send_key": "confirmation"})

    last = persistence.get_last_template(peer_id) if peer_id else None
    if is_affirmative_inline(text):
        if last == "greeting":
            return ("send_template", {"key": "pricelist"})
        if last == "pricelist":
            return ("send_template", {"key": "paylink"})

    return ("manual", {})


def route(message_text: str, rules: Dict, peer_id: Optional[str] = None) -> Tuple[str, Dict]:
    """Return (action, payload) for a given message text.

    Actions: send_template, move_timewaster, move_confirmation, manual
    """
    text = normalize_text(message_text)

    kw = rules.get("keywords", {}) if isinstance(rules, dict) else {}

    AFFIRM_RE = re.compile(r"^\s*(y|ya|yeah|yep|yup|yes|ok|okay|oky|sure|why not|let'?s go|go|ready)\s*[\!\.\)]?$", re.I)

    def is_affirmative(text_raw: str) -> bool:
        return bool(AFFIRM_RE.match(text_raw.strip()))

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
        if any(k in text for k in [
            "how do i pay",
            "how to pay",
            "how pay",
            "payment",
            "paypal",
            "paylink",
            "where do i send",
            "where to i send",
            "payment link",
            "payment info",
            "pay?",
            "pay",
        ]):
            return ("send_template", {"key": "paylink"})
        if any(k in text for k in ["not interested", "stop", "go away", "leave me", "nah"]):
            return ("move_timewaster", {})
        if any(k in text for k in ["paid", "sending", "sent", "i sent"]):
            return ("move_confirmation", {"send_key": "confirmation"})

        # Synonyms-based intent matching for robustness
        toks = token_set(text)
        if contains_any_phrase(text, GREETING_SYNS) or (toks & {"hi", "hey", "hello", "yo", "sup", "hiya", "howdy"}):
            if peer_id and template_already_used(peer_id, "greeting"):
                return ("manual", {"reason": "repeat_template"})
            return ("send_template", {"key": "greeting"})
        if contains_any_phrase(text, MENU_SYNS) or (toks & {"menu", "price", "prices", "pricelist", "content"}):
            if peer_id and template_already_used(peer_id, "pricelist"):
                return ("manual", {"reason": "repeat_template"})
            return ("send_template", {"key": "pricelist"})
        if (
            contains_any_phrase(text, PAY_SYNS)
            or (toks & {"pay", "payment", "paypal", "paylink"})
            or text.endswith("pay?")
        ):
            return ("send_template", {"key": "paylink"})
        if contains_any_phrase(text, CONFIRM_SYNS) or (toks & {"paid", "sending", "sent"}):
            return ("move_confirmation", {"send_key": "confirmation"})

        # ----- Context-aware fallback -----
        last = persistence.get_last_template(peer_id) if peer_id else None
        if is_affirmative(message_text):
            if last == "greeting":
                return ("send_template", {"key": "pricelist"})
            if last == "pricelist":
                return ("send_template", {"key": "paylink"})
        # ----------------------------------

        return ("manual", {})
    def _match_any_local(patterns):
        return match_any(patterns, text)

    if _match_any_local(kw.get("greeting", [])):
        key = "greeting"
        if peer_id and template_already_used(peer_id, key):
            return ("manual", {"reason": "repeat_template"})
        return ("send_template", {"key": key})

    if _match_any_local(kw.get("pricelist", [])):
        key = "pricelist"
        if peer_id and template_already_used(peer_id, key):
            return ("manual", {"reason": "repeat_template"})
        return ("send_template", {"key": key})

    if _match_any_local(kw.get("paylink", [])):
        key = "paylink"
        # Allow resending paylink idempotently if desired; here we allow repeat
        return ("send_template", {"key": key})

    if _match_any_local(kw.get("confirmation", [])) or ("paid" in text or "sending" in text):
        return ("move_confirmation", {"send_key": "confirmation"})

    notint = rules.get("not_interested", []) if isinstance(rules, dict) else []
    if _match_any_local(notint):
        return ("move_timewaster", {})

    # ----- Context-aware fallback -----
    last = persistence.get_last_template(peer_id) if peer_id else None
    if is_affirmative(message_text):
        if last == "greeting":
            return ("send_template", {"key": "pricelist"})
        if last == "pricelist":
            return ("send_template", {"key": "paylink"})
    # ----------------------------------

    return ("manual", {})


__all__ = ["route"]
__all__ += ["normalize_text", "looks_like_payment_intent"]


async def route_full(
    message_text: str,
    rules: Dict,
    peer_id: Optional[str],
    *,
    history,
    folder_name: str,
    classifier,
    threshold: float,
):
    # 1) Fast routing first
    action, payload = route_fast(message_text, rules, peer_id)
    if action != "manual":
        return action, payload

    # 2) LLM chooser
    if classifier is not None:
        try:
            used = list(persistence.get_used_templates(peer_id) if peer_id else [])
            # Support either an adapter with choose_template_or_move or a raw LLM
            if hasattr(classifier, "choose_template_or_move"):
                act, pay = await classifier.choose_template_or_move(
                    message_text=message_text,
                    history=history[-12:],
                    folder=folder_name,
                    used_templates=used,
                    threshold=threshold,
                )
            else:
                from .classifier import choose_template_or_move as _choose
                act, pay = await _choose(
                    classifier,
                    message_text,
                    [m.get("text", "") if isinstance(m, dict) else str(m) for m in history][-12:],
                    folder_name,
                    used,
                    threshold,
                )
            return act, pay
        except Exception as e:
            from .logging import logger as _logger
            _logger.warning(f"LLM fallback failed: {e}")

    # 3) Heuristic rescue
    used = persistence.get_used_templates(peer_id) if peer_id else set()
    last = persistence.get_last_template(peer_id) if peer_id else None
    text_norm = normalize_text(message_text)
    if looks_like_payment_intent(text_norm) and ("paylink" in used or last in {"paylink", "pricelist"}):
        return ("move_confirmation", {"send_key": "confirmation"})

    # 4) Default
    return ("manual", {})


