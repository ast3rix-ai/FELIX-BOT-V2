from core.router import route


def test_greeting_template():
    action, payload = route("Hi there", {})
    assert action == "send_template"
    assert payload.get("template_key") == "welcome"


def test_price_template():
    action, payload = route("Do you have a pricelist?", {})
    assert action == "send_template"


def test_payment_template():
    action, payload = route("how to pay?", {})
    assert action == "send_template"


def test_move_timewaster():
    action, payload = route("I'm not interested", {})
    assert action == "move_timewaster"


def test_move_confirmation():
    action, payload = route("paid, sending", {})
    assert action == "move_confirmation"


def test_fallback_manual():
    action, payload = route("random text with no keywords", {})
    assert action == "manual"


