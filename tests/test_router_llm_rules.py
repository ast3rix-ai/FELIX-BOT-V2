import pytest

from core.router import route
from core.persistence import mark_template_used, reset_peer_history


RULES = {
    "keywords": {
        "greeting": [r"\b(hi|hey|hello|helo|yo|sup)\b"],
        "pricelist": [r"\b(menu|prices?|pricelist|what (do|dya) (you|u) have|content\??)\b"],
        "paylink": [r"\b(pay(link)?|paypal|payment|how to pay|how (do|to) i pay|where do i send)\b"],
        "confirmation": [r"\b(i (sent|send(ing)?)|(i'?ve|have) (paid|payed)|sending now|baby got it|sent it)\b"],
    },
    "not_interested": [r"\b(no|nah|not interested|stop|leave me|go away)\b"],
}


def test_greeting_once_then_manual():
    peer = "p1"
    reset_peer_history(peer)
    action, payload = route("hey", RULES, peer)
    assert action == "send_template" and payload.get("key") == "greeting"
    mark_template_used(peer, "greeting")
    action2, payload2 = route("hey", RULES, peer)
    assert action2 == "manual"


def test_paylink_allowed_twice():
    peer = "p2"
    reset_peer_history(peer)
    action, payload = route("how do i pay", RULES, peer)
    assert action == "send_template" and payload.get("key") == "paylink"
    # second time still allowed (idempotent)
    action2, payload2 = route("how do i pay", RULES, peer)
    assert action2 == "send_template" and payload2.get("key") == "paylink"


def test_confirmation_flow():
    peer = "p3"
    action, payload = route("i sent", RULES, peer)
    assert action == "move_confirmation" and payload.get("send_key") == "confirmation"


