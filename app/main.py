from __future__ import annotations

import asyncio
import os

from dotenv import load_dotenv
import yaml
from pathlib import Path

from core.config import load_settings
from core.folder_manager import ensure_filters
from core.logging import configure_logging, logger
from telegram.client_manager import create_client
from telegram.handlers import register_handlers
from core.llm import LLM


async def _async_main() -> None:
    load_dotenv()
    settings = load_settings()
    configure_logging(os.getenv("LOG_LEVEL", "INFO"))

    logger.info({"event": "start", "account": settings.account})

    client = create_client(settings)
    async with client:
        # Will prompt for login on first run in console
        await client.start()
        me = await client.get_me()
        logger.info({"event": "authorized", "user": getattr(me, "username", None)})

        await ensure_filters(client)
        logger.info({"event": "ensure_filters_done"})

        # Load templates for replies
        templates_path = Path(settings.paths.accounts_dir) / settings.account / "templates.yaml"
        templates: dict = {}
        if templates_path.exists():
            try:
                with templates_path.open("r", encoding="utf-8") as f:
                    templates = yaml.safe_load(f) or {}
            except Exception as e:
                logger.warning({"event": "templates_load_failed", "error": str(e)})

        # LLM fallback instance
        llm = LLM(url=settings.ollama_url, model=settings.llm_model)

        register_handlers(client, templates, llm=llm, threshold=settings.llm_threshold)

        logger.info({"event": "listening"})
        await client.run_until_disconnected()


def main() -> None:
    asyncio.run(_async_main())


if __name__ == "__main__":
    main()


