from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

from PySide6 import QtCore, QtWidgets
from qasync import QEventLoop

from core.config import BrokerSettings, _ENV_PATH, load_settings
from core.logging import logger, configure_logging, get_log_queue
from telethon.tl import functions, types
from core.llm import LLM
from telegram.client_manager import get_client, ensure_authorized
from telegram.handlers import register_handlers
from core.templates import load_templates
from core.folder_manager import FolderManager


import yaml
from .testlab import TestLab
from .accounts import AccountsDialog, list_accounts


class UIQueueWriter:
    def __init__(self, queue: asyncio.Queue[str]) -> None:
        self.queue = queue

    def write(self, message: str) -> None:  # loguru writes str
        if message.strip():
            try:
                self.queue.put_nowait(message.rstrip("\n"))
            except Exception:
                pass

    def flush(self) -> None:
        pass


class DesktopWindow(QtWidgets.QMainWindow):
    def __init__(self, settings: BrokerSettings) -> None:
        super().__init__()
        self.setWindowTitle("Telegram Broker")
        self.settings = settings

        # State
        self._running = False
        self._client = None
        self._worker_task: Optional[asyncio.Task] = None
        self._counters_task: Optional[asyncio.Task] = None
        self._log_task: Optional[asyncio.Task] = None
        self._log_queue: asyncio.Queue[str] = asyncio.Queue()
        self._folder_manager: Optional[FolderManager] = None

        # UI
        central = QtWidgets.QWidget(self)
        layout = QtWidgets.QVBoxLayout(central)

        row_top = QtWidgets.QHBoxLayout()

        self.account_combo = QtWidgets.QComboBox()
        self._refresh_accounts()
        self.btn_manage = QtWidgets.QPushButton("Manage…")
        self.btn_manage.clicked.connect(self._on_manage)
        row_top.addWidget(QtWidgets.QLabel("Account:"))
        row_top.addWidget(self.account_combo)
        row_top.addWidget(self.btn_manage)

        self.start_button = QtWidgets.QPushButton("Start")
        self.start_button.clicked.connect(self.on_start_stop)
        self.stop_button = QtWidgets.QPushButton("Stop")
        self.stop_button.clicked.connect(lambda: asyncio.ensure_future(self._stop()))
        self.stop_button.setEnabled(False)
        row_top.addWidget(self.start_button)
        row_top.addWidget(self.stop_button)

        # Counters
        grid = QtWidgets.QGridLayout()

        self._folder_titles: Dict[int, str] = {1: "M0", 2: "B0", 4: "C0"}
        self.counter_labels: Dict[int, QtWidgets.QLabel] = {}
        for idx, (fid, title) in enumerate(self._folder_titles.items()):
            grid.addWidget(QtWidgets.QLabel(f"{title}:"), idx, 0)
            lab = QtWidgets.QLabel("0")
            self.counter_labels[fid] = lab
            grid.addWidget(lab, idx, 1)

        # Tabs: Main controls + Test Lab
        self.tabs = QtWidgets.QTabWidget()
        layout.addWidget(self.tabs)

        main_tab = QtWidgets.QWidget()
        main_layout = QtWidgets.QVBoxLayout(main_tab)

        main_layout.addLayout(row_top)
        main_layout.addLayout(grid)

        main_layout.addWidget(QtWidgets.QLabel("Logs:"))
        self.log_view = QtWidgets.QTextEdit()
        self.log_view.setReadOnly(True)
        # Log controls
        log_controls = QtWidgets.QHBoxLayout()
        self.btn_copy_logs = QtWidgets.QPushButton("Copy All")
        self.btn_save_logs = QtWidgets.QPushButton("Save...")
        log_controls.addWidget(self.btn_copy_logs)
        log_controls.addWidget(self.btn_save_logs)
        main_layout.addLayout(log_controls)
        main_layout.addWidget(self.log_view)

        self.tabs.addTab(main_tab, "Main")

        # Test Lab tab
        self.testlab = TestLab(self._build_sim_engine(), live_classifier=None)
        lab_container = QtWidgets.QWidget()
        lab_layout = QtWidgets.QVBoxLayout(lab_container)
        lab_layout.addWidget(self.testlab)
        self.tabs.addTab(lab_container, "Test Lab")

        self.setCentralWidget(central)

        # Install an additional non-JSON sink for UI
        logger.add(UIQueueWriter(self._log_queue), level="INFO", format="{message}", enqueue=True)

        # Wire copy/save actions
        self.btn_copy_logs.clicked.connect(self._copy_logs)
        self.btn_save_logs.clicked.connect(self._save_logs)

        # Diagnostics line for env path and account
        diag = QtWidgets.QLabel()
        s = load_settings()
        diag.setText(f"Env: {_ENV_PATH or '(none)'} | Account: {s.account}")
        layout.insertWidget(0, diag)

    def log(self, msg: str) -> None:
        try:
            self.log_view.append(msg)
        except Exception:
            pass
        try:
            print(msg, flush=True)
        except Exception:
            pass

    def _build_sim_engine(self):
        from core.sim import SimEngine
        from core.templates import load_templates
        # Preload templates for Test Lab
        templates = {}
        try:
            templates = load_templates()
        except Exception:
            templates = {}
        return SimEngine(templates=templates, threshold=self.settings.llm_threshold)

    @QtCore.Slot()
    def on_start_stop(self) -> None:
        if not self._running:
            asyncio.ensure_future(self._start())
        else:
            asyncio.ensure_future(self._stop())

    async def _start(self) -> None:
        if self._running:
            return
        self._running = True
        self.start_button.setText("Stop")
        self.stop_button.setEnabled(True)

        configure_logging("DEBUG")

        account = self.account_combo.currentText()
        # Preload templates (module-global) for live mode
        self.log("Loading templates…")
        try:
            load_templates(account)
        except Exception:
            pass
        # Load templates and rules
        acc_dir = Path(self.settings.paths.accounts_dir) / account
        templates_path = acc_dir / "templates.yaml"
        rules_path = acc_dir / "rules.yaml"
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

        llm = LLM(url=self.settings.ollama_url, model=self.settings.llm_model)

        self._client = await get_client(account)
        fm = FolderManager(self._client)
        # Robust start with UI logging and error handling
        self.log("Connecting…")
        try:
            await ensure_authorized(self._client, self.settings.telegram_phone)
            self.log("Ensuring folders exist…")
            await fm.ensure_folders()
            self.log("Folders ready.")
        except Exception as e:
            # Friendly message and keep UI alive; include full traceback
            import traceback, sys
            tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))
            self.log(f"❌ Start failed: {type(e).__name__}: {e}")
            self.log(tb)
            try:
                print(tb, file=sys.stderr, flush=True)
            except Exception:
                pass
            self._client = None
            return
        register_handlers(
            self._client, templates, rules, llm=llm, threshold=self.settings.llm_threshold
        )

        # Refresh Test Lab engine with current templates
        self.testlab.engine.templates = templates
        self.testlab.mount()

        self._worker_task = asyncio.create_task(self._worker())
        self._counters_task = asyncio.create_task(self._update_counters_periodically())
        self._log_task = asyncio.create_task(self._consume_logs())

    async def _stop(self) -> None:
        if not self._running:
            return
        self._running = False
        self.start_button.setText("Start")
        self.stop_button.setEnabled(False)

        for task in (self._worker_task, self._counters_task, self._log_task):
            if task:
                task.cancel()
        self._worker_task = self._counters_task = self._log_task = None

        if self._client is not None:
            try:
                await self._client.disconnect()
            except Exception:
                pass
            self._client = None

    @QtCore.Slot()
    def _on_manage(self) -> None:
        dlg = AccountsDialog(self)
        if dlg.exec() == QtWidgets.QDialog.Accepted and dlg.selected:
            self._refresh_accounts(select=dlg.selected)

    def _refresh_accounts(self, select: str | None = None) -> None:
        names = list_accounts()
        if not names:
            names = [self.settings.account]
        cur = select or (self.account_combo.currentText() if self.account_combo.count() else None) or names[0]
        self.account_combo.clear()
        self.account_combo.addItems(names)
        idx = max(0, names.index(cur)) if cur in names else 0
        self.account_combo.setCurrentIndex(idx)

    async def _worker(self) -> None:
        # Keep the client alive while running
        assert self._client is not None
        while self._running and self._client.is_connected():
            await asyncio.sleep(0.5)

    async def _update_counters_periodically(self) -> None:
        while self._running:
            try:
                if self._client is not None:
                    res = await self._client(functions.messages.GetDialogFiltersRequest())
                    fl = getattr(res, "filters", []) or []
                    title_to_count: Dict[str, int] = {}
                    for f in fl:
                        if isinstance(f, types.DialogFilter):
                            t = getattr(f, "title", "")
                            title_to_count[t] = len(getattr(f, "include_peers", []) or [])
                    for fid, lab in self.counter_labels.items():
                        title = self._folder_titles.get(fid, "")
                        lab.setText(str(title_to_count.get(title, 0)))
            except Exception:
                pass
            await asyncio.sleep(5.0)

    async def _consume_logs(self) -> None:
        q = get_log_queue()
        while self._running:
            try:
                item = await q.get()
                ts = item.get("ts")
                level = item.get("level")
                msg = item.get("message")
                self.log_view.append(f"[{ts:.0f}] {level} | {msg}")
            except Exception:
                await asyncio.sleep(0.1)

    @QtCore.Slot()
    def _copy_logs(self) -> None:
        self.log_view.selectAll()
        self.log_view.copy()
        self.log_view.moveCursor(QtWidgets.QTextCursor.End)

    @QtCore.Slot()
    def _save_logs(self) -> None:
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save Logs", str(Path.cwd() / "logs.txt"), "Text (*.txt)")
        if not path:
            return
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.log_view.toPlainText())


def run_desktop(settings: BrokerSettings) -> None:
    app = QtWidgets.QApplication([])
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    win = DesktopWindow(settings)
    win.resize(800, 600)
    win.show()

    with loop:
        loop.run_forever()


__all__ = ["run_desktop", "DesktopWindow"]


