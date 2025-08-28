from __future__ import annotations

import asyncio
import os
import sys
import argparse

from dotenv import load_dotenv
import yaml
from pathlib import Path

from core.config import load_settings, BrokerSettings
from core.logging import configure_logging, logger
from telegram.client_manager import create_client, get_client, ensure_authorized
from telegram.handlers import register_handlers
from core.llm import LLM
from ui.desktop import run_desktop


async def _async_main() -> None:
    load_dotenv()
    settings = load_settings()
    configure_logging(os.getenv("LOG_LEVEL", "DEBUG"))

    print("Start successfully")

    client = create_client(settings)
    async with client:
        # Will prompt for login on first run in console
        await client.start()
        print("Connecting…")
        me = await client.get_me()
        print("Connected")

        print("Listening for upcoming messages…")

        # Load templates and rules
        base_acc = Path(settings.paths.accounts_dir) / settings.account
        templates_path = base_acc / "templates.yaml"
        rules_path = base_acc / "rules.yaml"
        templates: dict = {}
        rules: dict = {}
        if templates_path.exists():
            try:
                with templates_path.open("r", encoding="utf-8") as f:
                    templates = yaml.safe_load(f) or {}
            except Exception as e:
                logger.warning({"event": "templates_load_failed", "error": str(e)})
        if rules_path.exists():
            try:
                with rules_path.open("r", encoding="utf-8") as f:
                    rules = yaml.safe_load(f) or {}
            except Exception as e:
                logger.warning({"event": "rules_load_failed", "error": str(e)})

        # LLM fallback instance
        llm = LLM(url=settings.ollama_url, model=settings.llm_model)

        register_handlers(client, templates, rules, llm=llm, threshold=settings.llm_threshold)

        await client.run_until_disconnected()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ui", action="store_true", help="launch desktop UI")
    parser.add_argument("--login", action="store_true", help="authorize account")
    parser.add_argument("--phone", type=str, default=None)
    parser.add_argument("--account", type=str, default=None)
    args = parser.parse_args()

    if args.login:
        asyncio.run(_login_flow(args.account, args.phone))
        return
    if args.ui:
        asyncio.run(_ui_entry())
    else:
        asyncio.run(_async_main())


async def _login_flow(account: str | None, phone: str | None) -> None:
    s = load_settings()
    acc = account or s.account
    client = await get_client(acc)
    try:
        await ensure_authorized(client, phone)
        print("✅ authorized. Session saved.")
    finally:
        await client.disconnect()


async def _ui_entry() -> None:
    load_dotenv()
    settings = load_settings()
    run_desktop(settings)


if __name__ == "__main__":
    main()


