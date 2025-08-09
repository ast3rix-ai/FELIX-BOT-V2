from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Dict, Optional

import yaml
from PySide6 import QtCore, QtWidgets

from core.sim import SimEngine, SimFolder


class TestLab(QtWidgets.QWidget):
    def __init__(self, engine: SimEngine, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.engine = engine

        root = QtWidgets.QVBoxLayout(self)
        content = QtWidgets.QHBoxLayout()
        root.addLayout(content)

        # Left controls
        left = QtWidgets.QVBoxLayout()
        content.addLayout(left, 2)

        self.peer_combo = QtWidgets.QComboBox()
        left.addWidget(self.peer_combo)

        btns1 = QtWidgets.QHBoxLayout()
        left.addLayout(btns1)
        self.btn_add_peer = QtWidgets.QPushButton("Add Peer")
        self.btn_reset = QtWidgets.QPushButton("Reset")
        btns1.addWidget(self.btn_add_peer)
        btns1.addWidget(self.btn_reset)

        self.input_text = QtWidgets.QLineEdit()
        self.btn_send = QtWidgets.QPushButton("Send Incoming")
        left.addWidget(self.input_text)
        left.addWidget(self.btn_send)

        self.chk_read = QtWidgets.QCheckBox("Simulate Read")
        self.chk_typing = QtWidgets.QCheckBox("Simulate Typing")
        self.chk_llm = QtWidgets.QCheckBox("Use LLM Fallback")
        self.chk_read.setChecked(self.engine.simulate_read)
        self.chk_typing.setChecked(self.engine.simulate_typing)
        left.addWidget(self.chk_read)
        left.addWidget(self.chk_typing)
        left.addWidget(self.chk_llm)

        self.slider_thresh = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.slider_thresh.setRange(50, 95)
        self.slider_thresh.setValue(int(self.engine.threshold * 100))
        self.lbl_thresh = QtWidgets.QLabel(f"Threshold: {self.engine.threshold:.2f}")
        left.addWidget(self.slider_thresh)
        left.addWidget(self.lbl_thresh)

        btns2 = QtWidgets.QHBoxLayout()
        left.addLayout(btns2)
        self.btn_scenario = QtWidgets.QPushButton("Run Scenario…")
        self.btn_clear = QtWidgets.QPushButton("Clear Transcript")
        self.btn_export = QtWidgets.QPushButton("Export Report")
        btns2.addWidget(self.btn_scenario)
        btns2.addWidget(self.btn_clear)
        btns2.addWidget(self.btn_export)

        # Center chat
        center = QtWidgets.QVBoxLayout()
        content.addLayout(center, 3)
        self.chat_list = QtWidgets.QListWidget()
        center.addWidget(self.chat_list)

        # Right inspector
        right = QtWidgets.QVBoxLayout()
        content.addLayout(right, 3)
        self.inspector = QtWidgets.QTextEdit()
        self.inspector.setReadOnly(True)
        right.addWidget(self.inspector)

        # Bottom logs
        self.logs = QtWidgets.QPlainTextEdit()
        self.logs.setReadOnly(True)
        root.addWidget(self.logs)

        # Signals
        self.btn_add_peer.clicked.connect(self._on_add_peer)
        self.btn_reset.clicked.connect(self._on_reset)
        self.btn_send.clicked.connect(self._on_send)
        self.btn_scenario.clicked.connect(self._on_scenario)
        self.btn_clear.clicked.connect(self._on_clear)
        self.btn_export.clicked.connect(self._on_export)
        self.chk_read.toggled.connect(self._on_flags)
        self.chk_typing.toggled.connect(self._on_flags)
        self.chk_llm.toggled.connect(self._on_flags)
        self.slider_thresh.valueChanged.connect(self._on_thresh)

    def mount(self) -> None:
        if not self.engine.peers:
            self.engine.add_peer("user1", "Alice")
        self._refresh_peers()
        self._refresh_logs()

    def _refresh_peers(self) -> None:
        self.peer_combo.clear()
        for pid, p in self.engine.peers.items():
            self.peer_combo.addItem(f"{p.display_name} ({pid})", userData=pid)
        self._refresh_chat()

    def _refresh_chat(self) -> None:
        self.chat_list.clear()
        pid = self.peer_combo.currentData()
        if pid is None:
            return
        peer = self.engine.peers[pid]
        for m in peer.history:
            role = m.get("role")
            ts = m.get("ts")
            text = m.get("text")
            self.chat_list.addItem(f"[{ts:.0f}] {role}: {text}")
        self._refresh_inspector()

    def _refresh_inspector(self) -> None:
        pid = self.peer_combo.currentData()
        if pid is None:
            return
        last = None
        for e in reversed(self.engine.events):
            if e.payload.get("peer_id") == str(pid):
                last = e
                break
        if last is None:
            self.inspector.setPlainText("No events yet")
            return
        self.inspector.setPlainText(json.dumps({"ts": last.ts, "kind": last.kind, "payload": last.payload}, indent=2))

    def _refresh_logs(self) -> None:
        self.logs.clear()
        for e in self.engine.events:
            self.logs.appendPlainText(f"{e.ts:.0f} {e.kind} {e.payload}")

    @QtCore.Slot()
    def _on_add_peer(self) -> None:
        idx = len(self.engine.peers) + 1
        self.engine.add_peer(f"user{idx}", f"User {idx}")
        self._refresh_peers()

    @QtCore.Slot()
    def _on_reset(self) -> None:
        self.engine.reset()
        self.engine.add_peer("user1", "Alice")
        self._refresh_peers()
        self._refresh_logs()

    @QtCore.Slot()
    def _on_send(self) -> None:
        pid = self.peer_combo.currentData()
        text = self.input_text.text().strip()
        if not pid or not text:
            return
        asyncio.create_task(self.engine.incoming(pid, text))
        # Render after a small delay to allow events to accumulate
        asyncio.create_task(self._render_soon())

    async def _render_soon(self) -> None:
        await asyncio.sleep(0.05)
        self._refresh_chat()
        self._refresh_logs()

    @QtCore.Slot()
    def _on_scenario(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Open Scenario", str(Path.cwd()), "YAML (*.yaml *.yml)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                scenario = yaml.safe_load(f) or {}
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", str(e))
            return
        asyncio.create_task(self._run_scenario(scenario))

    async def _run_scenario(self, scenario: Dict[str, Any]) -> None:
        steps = scenario.get("steps", [])
        pid = self.peer_combo.currentData()
        for step in steps:
            text = step.get("text", "")
            await self.engine.incoming(pid, text)
            await asyncio.sleep(0.05)
            self._refresh_chat()
            self._refresh_logs()

    @QtCore.Slot()
    def _on_clear(self) -> None:
        pid = self.peer_combo.currentData()
        if pid is None:
            return
        self.engine.peers[pid].history.clear()
        self._refresh_chat()

    @QtCore.Slot()
    def _on_export(self) -> None:
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Export Report", str(Path.cwd() / "report.json"), "JSON (*.json)")
        if not path:
            return
        data = self.engine.export_report()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    @QtCore.Slot()
    def _on_flags(self) -> None:
        self.engine.simulate_read = self.chk_read.isChecked()
        self.engine.simulate_typing = self.chk_typing.isChecked()
        # LLM toggle is respected by creating/dropping adapter in desktop wiring

    @QtCore.Slot()
    def _on_thresh(self) -> None:
        self.engine.threshold = self.slider_thresh.value() / 100.0
        self.lbl_thresh.setText(f"Threshold: {self.engine.threshold:.2f}")


__all__ = ["TestLab"]


