from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

from PySide6 import QtCore, QtWidgets
from qasync import QEventLoop

from core.config import BrokerSettings
from core.logging import logger, configure_logging, get_log_queue
from core.folder_manager import FOLDERS, ensure_filters, current_filters
from core.llm import LLM
from telegram.client_manager import create_client
from telegram.handlers import register_handlers

import yaml
from .testlab import TestLab


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

        # UI
        central = QtWidgets.QWidget(self)
        layout = QtWidgets.QVBoxLayout(central)

        row_top = QtWidgets.QHBoxLayout()

        self.account_combo = QtWidgets.QComboBox()
        self.account_combo.addItems([self.settings.account])
        row_top.addWidget(QtWidgets.QLabel("Account:"))
        row_top.addWidget(self.account_combo)

        self.start_button = QtWidgets.QPushButton("Start")
        self.start_button.clicked.connect(self.on_start_stop)
        row_top.addWidget(self.start_button)

        # Counters
        grid = QtWidgets.QGridLayout()

        self.counter_labels: Dict[int, QtWidgets.QLabel] = {}
        for idx, (fid, title) in enumerate(FOLDERS.items()):
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
        logger.add(UIQueueWriter(self._log_queue), level="INFO", format="{time:HH:mm:ss} | {level} | {message}", enqueue=True)

        # Wire copy/save actions
        self.btn_copy_logs.clicked.connect(self._copy_logs)
        self.btn_save_logs.clicked.connect(self._save_logs)

    def _build_sim_engine(self):
        from core.sim import SimEngine
        # Start with empty templates; will refresh on start
        return SimEngine(templates={}, threshold=self.settings.llm_threshold)

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

        configure_logging()

        account = self.account_combo.currentText()
        # Load templates
        templates_path = Path(self.settings.paths.accounts_dir) / account / "templates.yaml"
        templates: dict = {}
        if templates_path.exists():
            try:
                with templates_path.open("r", encoding="utf-8") as f:
                    templates = yaml.safe_load(f) or {}
            except Exception as e:
                logger.warning({"event": "templates_load_failed", "error": str(e)})

        llm = LLM(url=self.settings.ollama_url, model=self.settings.llm_model)

        self._client = create_client(self.settings)
        await self._client.start()
        await ensure_filters(self._client)
        register_handlers(self._client, templates, llm=llm, threshold=self.settings.llm_threshold)

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

    async def _worker(self) -> None:
        # Keep the client alive while running
        assert self._client is not None
        while self._running and await self._client.connected():
            await asyncio.sleep(0.5)

    async def _update_counters_periodically(self) -> None:
        while self._running:
            try:
                if self._client is not None:
                    mapping = await current_filters(self._client)
                    for fid, lab in self.counter_labels.items():
                        count = len(getattr(mapping.get(fid), "include_peers", []) or [])
                        lab.setText(str(count))
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


