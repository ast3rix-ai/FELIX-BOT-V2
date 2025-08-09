from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Dict, Optional

import yaml
from PySide6 import QtCore, QtWidgets

from core.sim import SimEngine, SimFolder
from core.templates import render_template
from core.classifier import classify_and_maybe_reply


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
        # LLM mode and controls
        self.chk_llm = QtWidgets.QCheckBox("Use LLM Fallback")
        mode_row = QtWidgets.QHBoxLayout()
        self.llm_mode = QtWidgets.QComboBox()
        self.llm_mode.addItems(["Disabled", "Live", "Mock"])
        self.spin_conf = QtWidgets.QDoubleSpinBox()
        self.spin_conf.setRange(0.0, 1.0)
        self.spin_conf.setSingleStep(0.05)
        self.spin_conf.setValue(0.9)
        mode_row.addWidget(QtWidgets.QLabel("LLM Mode:"))
        mode_row.addWidget(self.llm_mode)
        mode_row.addWidget(QtWidgets.QLabel("Mock confidence:"))
        mode_row.addWidget(self.spin_conf)
        self.chk_read.setChecked(self.engine.simulate_read)
        self.chk_typing.setChecked(self.engine.simulate_typing)
        left.addWidget(self.chk_read)
        left.addWidget(self.chk_typing)
        left.addWidget(self.chk_llm)
        left.addLayout(mode_row)

        self.slider_thresh = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.slider_thresh.setRange(50, 95)
        self.slider_thresh.setSingleStep(1)
        self.slider_thresh.setValue(int(self.engine.threshold * 100))
        self.lbl_thresh = QtWidgets.QLabel(f"Threshold: {self.engine.threshold:.2f}")
        # Cooldown/RPS checkboxes (annotate events only)
        self.chk_peer_cd = QtWidgets.QCheckBox("Respect per-peer cooldown")
        self.chk_global_rps = QtWidgets.QCheckBox("Respect global RPS")
        left.addWidget(self.chk_peer_cd)
        left.addWidget(self.chk_global_rps)
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
        self.llm_mode.currentIndexChanged.connect(self._on_llm_mode)
        self.spin_conf.valueChanged.connect(lambda _: None)
        self.chk_peer_cd.toggled.connect(self._on_flags)
        self.chk_global_rps.toggled.connect(self._on_flags)

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
        asyncio.create_task(self._incoming_with_mode(pid, text))
        # Render after a small delay to allow events to accumulate
        asyncio.create_task(self._render_soon())

    async def _incoming_with_mode(self, pid, text: str) -> None:
        # Wrap engine.classifier depending on UI mode
        original = self.engine.classifier
        mode = self.llm_mode.currentText()
        use_llm = self.chk_llm.isChecked()
        if use_llm and mode == "Mock":
            conf = float(self.spin_conf.value())

            async def mock_classifier(t: str, history: list[str]):
                low = t.lower()
                if any(k in low for k in ["hi", "hey", "hello"]):
                    return {"intent": "greeting", "confidence": conf, "reply": "Hello!"}
                if any(k in low for k in ["price", "pricelist"]):
                    return {"intent": "price", "confidence": conf, "reply": None}
                if any(k in low for k in ["how pay", "how to pay", "payment"]):
                    return {"intent": "payment_info", "confidence": conf, "reply": None}
                if any(k in low for k in ["paid", "sending"]):
                    return {"intent": "confirmation", "confidence": conf, "reply": None}
                if any(k in low for k in ["not interested", "stop", "no thanks"]):
                    return {"intent": "not_interested", "confidence": conf, "reply": None}
                return {"intent": "other", "confidence": conf, "reply": None}

            self.engine.classifier = mock_classifier  # type: ignore[assignment]
        elif use_llm and mode == "Live" and original is None:
            # Leave as-is; engine.classifier may be None in Test Lab, UI layer could inject a live adapter
            pass
        else:
            self.engine.classifier = None  # disabled

        # Set flags
        self.engine.respect_peer_cooldown = self.chk_peer_cd.isChecked()
        self.engine.respect_global_rps = self.chk_global_rps.isChecked()

        await self.engine.incoming(pid, text)
        self.engine.classifier = original

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
            before = len(self.engine.events)
            text = step.get("text", "")
            await self._incoming_with_mode(pid, text)
            await asyncio.sleep(0.05)
            new_events = [e for e in self.engine.events[before:] if e.payload.get("peer_id") == str(pid)]
            actual_action = None
            actual_template = None
            final_folder = self.engine.peers[pid].folder.name
            for e in new_events:
                if e.kind == "send":
                    actual_action = actual_action or "send_template"
                    actual_template = e.payload.get("template")
                if e.kind == "move_folder":
                    folder = e.payload.get("folder")
                    if folder == "TIMEWASTER":
                        actual_action = "move_timewaster"
                    elif folder == "CONFIRMATION":
                        actual_action = "move_confirmation"
                    elif folder == "MANUAL":
                        actual_action = "manual"
            if actual_action is None and final_folder == "MANUAL":
                actual_action = "manual"

            exp = step.get("expect", {})
            ok = True
            reason = []
            if "action" in exp and actual_action != exp.get("action"):
                ok = False
                reason.append(f"action {actual_action} != {exp.get('action')}")
            if "template" in exp and (actual_template or None) != exp.get("template"):
                ok = False
                reason.append(f"template {actual_template} != {exp.get('template')}")
            if "folder" in exp and final_folder != exp.get("folder"):
                ok = False
                reason.append(f"folder {final_folder} != {exp.get('folder')}")

            self.engine._event(
                "assert",
                peer_id=str(pid),
                step=text,
                expect=exp,
                actual={"action": actual_action, "template": actual_template, "folder": final_folder},
                **{"pass": ok, "reason": "; ".join(reason)},
            )

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
        self.engine.respect_peer_cooldown = self.chk_peer_cd.isChecked()
        self.engine.respect_global_rps = self.chk_global_rps.isChecked()

    @QtCore.Slot()
    def _on_thresh(self) -> None:
        self.engine.threshold = self.slider_thresh.value() / 100.0
        self.lbl_thresh.setText(f"Threshold: {self.engine.threshold:.2f}")

    @QtCore.Slot()
    def _on_llm_mode(self) -> None:
        pass


__all__ = ["TestLab"]


