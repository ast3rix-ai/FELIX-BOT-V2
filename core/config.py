from __future__ import annotations

from pathlib import Path
from typing import Optional, Literal, List
import os

from pydantic import BaseModel, Field
from loguru import logger
from dotenv import load_dotenv, find_dotenv
DEFAULT_PAYLINK: str = "https://example.com/pay"

# Eagerly load .env so UI/TestLab imports see credentials
_ENV_PATH = find_dotenv(usecwd=True)
if _ENV_PATH:
    # Ensure we override any existing shell vars so the editor's .env wins
    load_dotenv(_ENV_PATH, override=True)
    try:
        logger.info(f".env loaded from: {_ENV_PATH}")
    except Exception:
        pass
else:
    try:
        logger.warning(".env file not found; relying on process env")
    except Exception:
        pass



class Paths(BaseModel):
    base_dir: Path = Field(default_factory=lambda: Path(__file__).resolve().parents[1])
    data_dir: Path = Field(default_factory=lambda: Path("data"))

    @property
    def accounts_dir(self) -> Path:
        return self.base_dir / self.data_dir / "accounts"

    def session_path(self, account: str) -> Path:
        return self.accounts_dir / account / "session.session"

    def ensure_account_dirs(self, account: str) -> None:
        (self.accounts_dir / account).mkdir(parents=True, exist_ok=True)


class BrokerSettings(BaseModel):
    # General
    environment: str = Field(default="development")
    account: str = Field(default="acc1")

    # Model & scoring
    model_name: str = Field(default="gpt-4o-mini")
    threshold: float = Field(default=0.5)
    paylink: str = Field(default=DEFAULT_PAYLINK)

    # API keys
    telegram_api_id: int = Field(default=0)
    telegram_api_hash: str = Field(default="")
    telegram_phone: str = Field(default="")
    openai_api_key: Optional[str] = None

    # Paths
    paths: Paths = Field(default_factory=Paths)

    # LLM fallback
    ollama_url: str = Field(default="http://localhost:11434")
    llm_model: str = Field(default="deepseek-r1:7b")
    llm_threshold: float = Field(default=0.75)
    llm_mode: Literal["classify", "reply"] = Field(default="classify")
    # Live handling
    admin_ids: List[int] = Field(default_factory=list)
    ignore_channels: bool = Field(default=True)
    ignore_pinned: bool = Field(default=True)

    # Optional proxy
    proxy_enabled: bool = Field(default=False)
    proxy_type: str = Field(default="socks5")  # socks5|http
    proxy_host: str = Field(default="")
    proxy_port: int = Field(default=0)
    proxy_user: str = Field(default="")
    proxy_pass: str = Field(default="")

    def get_session_path(self, account: Optional[str] = None) -> Path:
        acc = account or self.account
        return self.paths.session_path(acc)

    def resolved_paylink(self) -> str:
        link = (self.paylink or "").strip()
        return link if link else DEFAULT_PAYLINK

    # Convenience helpers for account-scoped files
    @property
    def account_dir(self) -> Path:
        return self.paths.accounts_dir / self.account

    def templates_path(self) -> Path:
        return self.account_dir / "templates.yaml"

    def rules_path(self) -> Path:
        return self.account_dir / "rules.yaml"

    @classmethod
    def from_env(cls) -> "BrokerSettings":
        def getenv(name: str, default: Optional[str] = None) -> Optional[str]:
            return os.getenv(name, default)

        raw_id = (getenv("TELEGRAM_API_ID", "") or "").strip()
        telegram_api_id = int(raw_id) if raw_id.isdigit() else 0
        telegram_api_hash = (getenv("TELEGRAM_API_HASH", "") or "").strip()
        telegram_phone = (getenv("TELEGRAM_PHONE", "") or "").strip()

        data = {
            "environment": getenv("ENVIRONMENT", "development"),
            "account": getenv("ACCOUNT", "acc1"),
            "model_name": getenv("MODEL_NAME", "gpt-4o-mini"),
            "threshold": float(getenv("THRESHOLD", "0.5")),
            "paylink": getenv("PAYLINK", "") or "",
            "telegram_api_id": telegram_api_id,
            "telegram_api_hash": telegram_api_hash,
            "telegram_phone": telegram_phone,
            "openai_api_key": getenv("OPENAI_API_KEY"),
            "ollama_url": getenv("OLLAMA_URL", "http://localhost:11434"),
            "llm_model": getenv("MODEL", "deepseek-r1:7b"),
            "llm_threshold": float(getenv("LLM_THRESHOLD", "0.75")),
            "llm_mode": (getenv("LLM_MODE", "classify") or "classify").strip().lower(),
            "ignore_channels": (getenv("IGNORE_CHANNELS", "true") or "true").lower() != "false",
            "ignore_pinned": (getenv("IGNORE_PINNED", "true") or "true").lower() != "false",
        }

        # Parse admin ids
        admins = (getenv("ADMIN_IDS", "") or "").strip()
        admin_ids: List[int] = []
        for part in admins.split(","):
            p = part.strip()
            if p.isdigit():
                try:
                    admin_ids.append(int(p))
                except Exception:
                    continue
        data["admin_ids"] = admin_ids

        # Proxy
        proxy_enabled = (getenv("PROXY_ENABLED", "false") or "false").strip().lower() == "true"
        proxy_type = (getenv("PROXY_TYPE", "socks5") or "socks5").strip().lower()
        proxy_host = (getenv("PROXY_HOST", "") or "").strip()
        try:
            proxy_port = int((getenv("PROXY_PORT", "0") or "0").strip())
        except Exception:
            proxy_port = 0
        proxy_user = (getenv("PROXY_USER", "") or "").strip()
        proxy_pass = (getenv("PROXY_PASS", "") or "").strip()

        data.update(
            dict(
                proxy_enabled=proxy_enabled,
                proxy_type=proxy_type,
                proxy_host=proxy_host,
                proxy_port=proxy_port,
                proxy_user=proxy_user,
                proxy_pass=proxy_pass,
            )
        )

        if telegram_api_id == 0 or not telegram_api_hash:
            logger.warning("Telegram API credentials not set; live mode disabled. UI/Test Lab still works.")

        return cls(**data)


def load_settings() -> BrokerSettings:
    return BrokerSettings.from_env()


