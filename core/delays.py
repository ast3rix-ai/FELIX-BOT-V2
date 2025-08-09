from __future__ import annotations

import random


def typing_delay(chars: int) -> float:
    base = min(4.0, 0.6 + (chars / 15.0))
    return base + random.uniform(0.0, 0.6)


__all__ = ["typing_delay"]


