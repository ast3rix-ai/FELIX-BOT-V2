from core.router import decide_action


def test_greeting_template():
    d = decide_action("Hi there", {})
    assert d.action == "template"
    assert d.template_key == "welcome"


def test_price_template():
    d = decide_action("Do you have a pricelist?", {})
    assert d.action == "template"


def test_payment_template():
    d = decide_action("how to pay?", {})
    assert d.action == "template"


def test_move_timewaster():
    d = decide_action("I'm not interested", {})
    assert d.action == "move" and d.move_to_folder_id == 3


def test_move_confirmation():
    d = decide_action("paid, sending", {})
    assert d.action == "move" and d.move_to_folder_id == 4


def test_fallback_manual():
    d = decide_action("random text with no keywords", {})
    assert d.action == "manual"


