from __future__ import annotations

from pathlib import Path
from typing import Optional
import os

from pydantic import BaseModel, Field


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
    paylink: str = Field(default="")

    # API keys
    telegram_api_id: int = Field(default=0)
    telegram_api_hash: str = Field(default="")
    openai_api_key: Optional[str] = None

    # Paths
    paths: Paths = Field(default_factory=Paths)

    # LLM fallback
    ollama_url: str = Field(default="http://localhost:11434")
    llm_model: str = Field(default="deepseek-r1:7b")
    llm_threshold: float = Field(default=0.75)

    def get_session_path(self, account: Optional[str] = None) -> Path:
        acc = account or self.account
        return self.paths.session_path(acc)

    @classmethod
    def from_env(cls) -> "BrokerSettings":
        def getenv(name: str, default: Optional[str] = None) -> Optional[str]:
            return os.getenv(name, default)

        data = {
            "environment": getenv("ENVIRONMENT", "development"),
            "account": getenv("ACCOUNT", "acc1"),
            "model_name": getenv("MODEL_NAME", "gpt-4o-mini"),
            "threshold": float(getenv("THRESHOLD", "0.5")),
            "paylink": getenv("PAYLINK", "") or "",
            "telegram_api_id": int(getenv("TELEGRAM_API_ID", "0")),
            "telegram_api_hash": getenv("TELEGRAM_API_HASH", "") or "",
            "openai_api_key": getenv("OPENAI_API_KEY"),
            "ollama_url": getenv("OLLAMA_URL", "http://localhost:11434"),
            "llm_model": getenv("MODEL", "deepseek-r1:7b"),
            "llm_threshold": float(getenv("LLM_THRESHOLD", "0.75")),
        }
        return cls(**data)


def load_settings() -> BrokerSettings:
    return BrokerSettings.from_env()


