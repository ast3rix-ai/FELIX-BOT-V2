from __future__ import annotations

import os
from string import Formatter
from typing import Any, Dict, Optional


class _SafeDict(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def render_template(templates: Dict[str, str], key: str, context: Optional[Dict[str, Any]] = None) -> str:
    """Render a simple template with {PLACEHOLDER} variables.

    - Looks up `key` in templates; if missing, returns empty string
    - Merges provided context with environment variables
    - Unknown variables are left as-is
    """
    raw = templates.get(key, "")
    if not raw:
        return ""

    base: Dict[str, Any] = {}
    if context:
        base.update(context)
    # Include environment variables like PAYLINK, etc.
    base.update(os.environ)

    try:
        return raw.format_map(_SafeDict(base))
    except Exception:
        return raw


__all__ = ["render_template"]


