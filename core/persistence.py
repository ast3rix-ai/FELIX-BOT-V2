from __future__ import annotations

# simple process-memory registry; replace with SQLite later if needed
USED_TEMPLATES: dict[str, set[str]] = {}
LAST_TEMPLATE: dict[str, str] = {}


def mark_template_used(peer_id: str, template_key: str) -> None:
    USED_TEMPLATES.setdefault(str(peer_id), set()).add(template_key)


def template_already_used(peer_id: str, template_key: str) -> bool:
    return template_key in USED_TEMPLATES.get(str(peer_id), set())


def get_used_templates(peer_id: str) -> set[str]:
    return USED_TEMPLATES.get(str(peer_id), set()).copy()


def reset_peer_history(peer_id: str) -> None:
    USED_TEMPLATES.pop(str(peer_id), None)
    LAST_TEMPLATE.pop(str(peer_id), None)


def set_last_template(peer_id: str, template_key: str) -> None:
    LAST_TEMPLATE[str(peer_id)] = template_key


def get_last_template(peer_id: str) -> str | None:
    return LAST_TEMPLATE.get(str(peer_id))


__all__ = [
    "mark_template_used",
    "template_already_used",
    "get_used_templates",
    "reset_peer_history",
    "set_last_template",
    "get_last_template",
]


