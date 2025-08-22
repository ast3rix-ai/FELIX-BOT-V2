import asyncio
from loguru import logger
from core.config import load_settings
from telegram.client_manager import get_client, ensure_authorized
from core.folder_manager import move_to_bot
from telegram.handlers import start_live
from core.templates import load_templates
import yaml
from pathlib import Path


def load_rules_for_account(account: str) -> dict:
    base = Path("data") / "accounts" / account / "rules.yaml"
    if base.exists():
        try:
            return yaml.safe_load(base.read_text(encoding="utf-8")) or {}
        except Exception:
            return {}
    return {}


async def main() -> None:
    s = load_settings()
    logger.info(f"Using account={s.account}")
    client = await get_client(s.account)
    await ensure_authorized(client)

    templates = load_templates(s.account)
    rules = load_rules_for_account(s.account)

    await start_live(client, templates, rules, llm=None, threshold=s.llm_threshold)


if __name__ == "__main__":
    asyncio.run(main())
