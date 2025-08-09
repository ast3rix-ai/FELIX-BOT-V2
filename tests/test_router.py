from core.router import route


RULES = {
    "keywords": {
        "greeting": [r"\b(hi|hey|hello|helo|yo|sup)\b"],
        "pricelist": [r"\b(menu|prices?|pricelist|what (do|dya) (you|u) have|content\??)\b"],
        "paylink": [r"\b(pay(link)?|paypal|payment|how to pay|how (do|to) i pay|where do i send)\b"],
        "confirmation": [r"\b(i (sent|send(ing)?)|(i'?ve|have) (paid|payed)|sending now|baby got it|sent it)\b"],
    },
    "not_interested": [r"\b(no|nah|not interested|stop|leave me|go away)\b"],
}


def test_greeting_template():
    action, payload = route("Hi there", RULES)
    assert action == "send_template"
    assert payload.get("key") == "greeting"


def test_price_template():
    action, payload = route("Do you have a pricelist?", RULES)
    assert action == "send_template"


def test_payment_template():
    action, payload = route("how to pay?", RULES)
    assert action == "send_template"


def test_move_timewaster():
    action, payload = route("I'm not interested", RULES)
    assert action == "move_timewaster"


def test_move_confirmation():
    action, payload = route("paid, sending", RULES)
    assert action == "move_confirmation"


def test_fallback_manual():
    action, payload = route("random text with no keywords", {})
    assert action == "manual"


