from __future__ import annotations

from pathlib import Path

from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from telethon.network.connection.tcpabridged import ConnectionTcpAbridged

from core.config import BrokerSettings, load_settings
from loguru import logger

try:
    import socks  # PySocks
except Exception:  # pragma: no cover
    socks = None


def _proxy_tuple(settings: BrokerSettings):
    if not settings.proxy_enabled:
        return None
    if settings.proxy_type.lower() == "http":
        ptype = socks.HTTP if socks else None
    else:
        ptype = socks.SOCKS5 if socks else None
    if not ptype:
        logger.warning("Proxy enabled but PySocks not installed; run: pip install PySocks")
        return None
    return (
        ptype,
        settings.proxy_host,
        settings.proxy_port,
        True,
        settings.proxy_user or None,
        settings.proxy_pass or None,
    )


def create_client(settings: BrokerSettings) -> TelegramClient:
    session_path: Path = settings.get_session_path()
    session_path.parent.mkdir(parents=True, exist_ok=True)
    proxy = _proxy_tuple(settings)

    client = TelegramClient(
        str(session_path),
        settings.telegram_api_id,
        settings.telegram_api_hash,
        connection=ConnectionTcpAbridged,
        use_ipv6=False,
        request_retries=3,
        connection_retries=6,
        timeout=10,
        proxy=proxy,
        device_model="Mac",
        system_version="macOS",
        app_version="Broker/0.1",
        lang_code="en",
    )
    return client


async def ensure_authorized(client: TelegramClient, phone: str | None = None):
    # Ensure connected before interacting
    try:
        await client.connect()
    except Exception:
        pass
    if await client.is_user_authorized():
        return
    if not phone:
        phone = input("Enter phone (e.g., +15551234567): ").strip()
    await client.send_code_request(phone)
    code = input("Enter code: ").strip()
    try:
        await client.sign_in(phone=phone, code=code)
    except SessionPasswordNeededError:
        pw = input("Two-step password: ").strip()
        await client.sign_in(password=pw)


async def get_client(account: str) -> TelegramClient:
    s = load_settings()
    acc_dir = Path(s.paths.accounts_dir) / account
    acc_dir.mkdir(parents=True, exist_ok=True)
    session_path = acc_dir / "session.session"
    proxy = _proxy_tuple(s)
    client = TelegramClient(
        str(session_path),
        s.telegram_api_id,
        s.telegram_api_hash,
        connection=ConnectionTcpAbridged,
        use_ipv6=False,
        request_retries=3,
        connection_retries=6,
        timeout=10,
        proxy=proxy,
        device_model="Mac",
        system_version="macOS",
        app_version="Broker/0.1",
        lang_code="en",
    )
    return client


async def test_connectivity(client: TelegramClient) -> tuple[bool, str]:
    try:
        await client.connect()
        ok = client.is_connected()
        return (ok, "connected" if ok else "not connected")
    except Exception as e:  # pragma: no cover
        return (False, f"{type(e).__name__}: {e}")


__all__ = [
    "create_client",
    "ensure_authorized",
    "get_client",
    "test_connectivity",
]


