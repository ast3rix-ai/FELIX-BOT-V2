from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from .config import load_settings, DEFAULT_PAYLINK
from loguru import logger


# Module-global cache for templates so live handlers can hot-reload on miss
_TEMPLATES: Dict[str, str] = {}
_LAST_PATH: Optional[str] = None


def templates_path_for_account(account: Optional[str] = None) -> Path:
    settings = load_settings()
    acc = account or settings.account
    return (settings.paths.accounts_dir / acc / "templates.yaml").resolve()


def load_templates(account: Optional[str] = None) -> Dict[str, str]:
    """Load templates for the (optional) account and store a module-global copy.

    Returns the loaded mapping. Missing files are tolerated and return an empty mapping.
    """
    global _TEMPLATES, _LAST_PATH
    path = templates_path_for_account(account)
    _LAST_PATH = str(path)
    if not path.exists():
        _TEMPLATES = {}
        return _TEMPLATES
    try:
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception as e:
        try:
            logger.warning({"event": "templates_load_failed", "error": str(e)})
        except Exception:
            pass
        data = {}
    if not isinstance(data, dict):
        data = {}
    # Normalize to str->str mapping
    _TEMPLATES = {str(k): str(v) for k, v in data.items()}
    # Keep console clean; do not log noisy info here
    return _TEMPLATES


def ensure_template(templates: Dict[str, str], key: str) -> None:
    if key not in templates:
        raise KeyError(f"Template '{key}' missing. Loaded keys: {list(templates.keys())}")


def render_template(templates: Dict[str, str], key: str, context: Optional[Dict[str, Any]] = None) -> str:
    if key not in templates:
        raise KeyError(f"template '{key}' missing")
    text = templates[key]
    settings = load_settings()
    pay = settings.resolved_paylink()
    if pay == DEFAULT_PAYLINK:
        logger.warning("PAYLINK not set; using default placeholder")
    ctx: Dict[str, Any] = {"PAYLINK": pay}
    if context:
        ctx.update(context)
    rendered = text.format(**ctx)
    if not rendered.strip():
        logger.error(f"Rendered template '{key}' is empty; substituting default paylink text")
        if key == "paylink":
            rendered = pay
        else:
            rendered = "..."
    return rendered


def get_templates() -> Dict[str, str]:
    return _TEMPLATES


def has_template(key: str) -> bool:
    return key in _TEMPLATES


__all__ = [
    "render_template",
    "load_templates",
    "ensure_template",
    "get_templates",
    "has_template",
    "templates_path_for_account",
]


