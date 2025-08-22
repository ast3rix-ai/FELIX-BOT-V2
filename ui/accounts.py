from __future__ import annotations

import asyncio
from pathlib import Path
from typing import List, Tuple, Optional

from PySide6 import QtCore, QtWidgets
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError

from core.config import load_settings
from telegram.client_manager import get_client, test_connectivity


def list_accounts() -> List[str]:
    s = load_settings()
    base = s.paths.accounts_dir
    if not base.exists():
        return []
    names: List[str] = []
    for p in base.iterdir():
        if p.is_dir() and (p / "session.session").exists():
            names.append(p.name)
    return sorted(names)


async def _is_authorized(account: str) -> bool:
    s = load_settings()
    session = s.paths.accounts_dir / account / "session.session"
    client = TelegramClient(str(session), s.telegram_api_id, s.telegram_api_hash)
    try:
        await client.connect()
        return await client.is_user_authorized()
    finally:
        await client.disconnect()


class AddAccountDialog(QtWidgets.QDialog):
    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add Account")
        self.result_name: Optional[str] = None

        layout = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QFormLayout()
        self.edit_phone = QtWidgets.QLineEdit()
        self.edit_code = QtWidgets.QLineEdit()
        self.edit_pw = QtWidgets.QLineEdit()
        self.edit_pw.setEchoMode(QtWidgets.QLineEdit.Password)
        form.addRow("Phone:", self.edit_phone)
        form.addRow("Code:", self.edit_code)
        form.addRow("2FA (optional):", self.edit_pw)
        layout.addLayout(form)

        btns = QtWidgets.QHBoxLayout()
        self.btn_send_code = QtWidgets.QPushButton("Send Code")
        self.btn_sign_in = QtWidgets.QPushButton("Sign In")
        self.btn_sign_in.setEnabled(False)
        self.btn_test = QtWidgets.QPushButton("Test Connection")
        btns.addWidget(self.btn_send_code)
        btns.addWidget(self.btn_sign_in)
        btns.addWidget(self.btn_test)
        layout.addLayout(btns)

        self.btn_send_code.clicked.connect(self._on_send_code)
        self.btn_sign_in.clicked.connect(self._on_sign_in)
        self.btn_test.clicked.connect(self._on_test)

        self._temp_account = "_tmp"
        self._client: TelegramClient | None = None
        self._send_lock = asyncio.Lock()
        self._sending: bool = False

    def _error(self, msg: str) -> None:
        QtWidgets.QMessageBox.critical(self, "Error", msg)

    def _info(self, msg: str) -> None:
        QtWidgets.QMessageBox.information(self, "Info", msg)

    @QtCore.Slot()
    def _on_send_code(self) -> None:
        phone = self.edit_phone.text().strip()
        if not phone:
            self._error("Enter phone number")
            return
        asyncio.create_task(self._send_code_async(phone))

    async def _send_code_async(self, phone: str) -> None:
        if self._sending:
            return
        async with self._send_lock:
            self._sending = True
            self.btn_send_code.setEnabled(False)
            s = load_settings()
            if s.telegram_api_id == 0 or not s.telegram_api_hash:
                self._error("Telegram API credentials not set. Edit your .env and restart the app.")
                self.btn_send_code.setEnabled(True)
                self._sending = False
                return
            try:
                base = s.paths.accounts_dir / self._temp_account
                base.mkdir(parents=True, exist_ok=True)
                session = base / "session.session"
                # Use robust client factory (with proxy/ipv6 off)
                self._client = await get_client(self._temp_account)
                ok, msg = await test_connectivity(self._client)
                if not ok:
                    self._error(f"Cannot connect to Telegram: {msg}")
                    return
                await self._client.send_code_request(phone)
                self._info("Code sent. Check Telegram app/SMS.")
                self.btn_sign_in.setEnabled(True)
            except Exception as e:
                msg = str(e)
                if "api_id/api_hash" in msg.lower():
                    self._error("Invalid TELEGRAM_API_ID/TELEGRAM_API_HASH. Double-check values at my.telegram.org.")
                else:
                    self._error(f"Send code failed: {type(e).__name__}: {e}")
                try:
                    if self._client is not None:
                        await self._client.disconnect()
                except Exception:
                    pass
                self._client = None
            finally:
                self.btn_send_code.setEnabled(True)
                self._sending = False

    @QtCore.Slot()
    def _on_sign_in(self) -> None:
        phone = self.edit_phone.text().strip()
        code = self.edit_code.text().strip()
        pw = self.edit_pw.text().strip()
        if not phone or not code:
            self._error("Enter phone and code")
            return
        asyncio.create_task(self._sign_in_async(phone, code, pw))

    async def _sign_in_async(self, phone: str, code: str, pw: str) -> None:
        try:
            if self._client is None:
                self._error("Send code first")
                return
            try:
                await self._client.sign_in(phone=phone, code=code)
            except SessionPasswordNeededError:
                await self._client.sign_in(password=pw)
            me = await self._client.get_me()
            default_name = (getattr(me, "username", None) or getattr(me, "phone", None) or self._temp_account)
            name, ok = QtWidgets.QInputDialog.getText(self, "Account Name", "Save as:", text=str(default_name))
            if not ok or not name.strip():
                return
            name = name.strip()
            # Move session dir
            s = load_settings()
            tmp_dir = s.paths.accounts_dir / self._temp_account
            new_dir = s.paths.accounts_dir / name
            new_dir.mkdir(parents=True, exist_ok=True)
            (tmp_dir / "session.session").replace(new_dir / "session.session")
            try:
                tmp_dir.rmdir()
            except Exception:
                pass
            self.result_name = name
            self.accept()
        except Exception as e:
            self._error(str(e))
        finally:
            if self._client is not None:
                await self._client.disconnect()

    @QtCore.Slot()
    def _on_test(self) -> None:
        asyncio.create_task(self._test_clicked())

    async def _test_clicked(self):
        # Ensure we use a temp session so we don't affect existing ones
        try:
            s = load_settings()
            base = s.paths.accounts_dir / self._temp_account
            base.mkdir(parents=True, exist_ok=True)
            self._client = await get_client(self._temp_account)
            ok, msg = await test_connectivity(self._client)
            if ok:
                self._info(f"Test connection → {msg}")
            else:
                self._error(f"Test connection → {msg}")
        except Exception as e:
            self._error(f"Test connection failed: {type(e).__name__}: {e}")
        finally:
            try:
                if self._client is not None:
                    await self._client.disconnect()
            except Exception:
                pass


class AccountsDialog(QtWidgets.QDialog):
    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Manage Accounts")
        self.selected: Optional[str] = None
        layout = QtWidgets.QVBoxLayout(self)

        self.list = QtWidgets.QListWidget()
        layout.addWidget(self.list)

        btns = QtWidgets.QHBoxLayout()
        self.btn_add = QtWidgets.QPushButton("Add Account")
        self.btn_delete = QtWidgets.QPushButton("Delete")
        self.btn_use = QtWidgets.QPushButton("Use Selected")
        btns.addWidget(self.btn_add)
        btns.addWidget(self.btn_delete)
        btns.addWidget(self.btn_use)
        layout.addLayout(btns)

        self.btn_add.clicked.connect(self._on_add)
        self.btn_delete.clicked.connect(self._on_delete)
        self.btn_use.clicked.connect(self._on_use)

        self._refresh()

    def _refresh(self) -> None:
        self.list.clear()
        for name in list_accounts():
            item = QtWidgets.QListWidgetItem(name)
            item.setData(QtCore.Qt.UserRole, name)
            self.list.addItem(item)

    @QtCore.Slot()
    def _on_add(self) -> None:
        dlg = AddAccountDialog(self)
        if dlg.exec() == QtWidgets.QDialog.Accepted and dlg.result_name:
            self._refresh()

    @QtCore.Slot()
    def _on_delete(self) -> None:
        item = self.list.currentItem()
        if not item:
            return
        name = item.data(QtCore.Qt.UserRole)
        s = load_settings()
        p = s.paths.accounts_dir / str(name)
        if p.exists():
            for child in p.iterdir():
                try:
                    child.unlink()
                except Exception:
                    pass
            try:
                p.rmdir()
            except Exception:
                pass
        self._refresh()

    @QtCore.Slot()
    def _on_use(self) -> None:
        item = self.list.currentItem()
        if not item:
            return
        self.selected = str(item.data(QtCore.Qt.UserRole))
        self.accept()


__all__ = ["AccountsDialog", "AddAccountDialog", "list_accounts"]


