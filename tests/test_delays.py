from core.delays import typing_delay


def test_typing_delay_bounds():
    # Randomized jitter makes exact checks hard; verify bounds
    for chars in [0, 1, 10, 50, 1000]:
        d = typing_delay(chars)
        assert d >= 0.6  # base min
        assert d <= 4.6  # base max 4.0 + jitter 0.6


