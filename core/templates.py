from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from .config import load_settings
from loguru import logger


def load_templates(account: Optional[str] = None) -> Dict[str, str]:
    settings = load_settings()
    acc = account or settings.account
    path = (settings.paths.accounts_dir / acc / "templates.yaml").resolve()
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError("templates.yaml must be a mapping")
    logger.info(f"Templates loaded from {path} with keys={list(data.keys())}")
    return {str(k): str(v) for k, v in data.items()}


def ensure_template(templates: Dict[str, str], key: str) -> None:
    if key not in templates:
        raise KeyError(f"Template '{key}' missing. Loaded keys: {list(templates.keys())}")


def render_template(templates: Dict[str, str], key: str, context: Optional[Dict[str, Any]] = None) -> str:
    if key not in templates:
        raise KeyError(f"template '{key}' missing")
    text = templates[key]
    settings = load_settings()
    ctx: Dict[str, Any] = {"PAYLINK": settings.paylink}
    if context:
        ctx.update(context)
    return text.format(**ctx)


__all__ = ["render_template", "load_templates", "ensure_template"]


