from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Callable, Awaitable

from .delays import typing_delay
from .router import route
from .templates import render_template


class SimFolder(Enum):
    MANUAL = 1
    BOT = 2
    TIMEWASTER = 3
    CONFIRMATION = 4


@dataclass
class SimPeer:
    peer_id: str | int
    display_name: str
    folder: SimFolder = SimFolder.BOT
    history: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class SimEvent:
    ts: float
    kind: str
    payload: Dict[str, Any]


ClassifierFn = Callable[[str, List[str]], Awaitable[Dict[str, Any]]]


class SimEngine:
    def __init__(
        self,
        templates: Dict[str, str],
        rules: Dict[str, Any] | None = None,
        classifier: Optional[ClassifierFn] = None,
        threshold: float = 0.75,
        simulate_typing: bool = True,
        simulate_read: bool = True,
    ) -> None:
        self.templates = templates
        self.rules = rules or {}
        self.classifier = classifier
        self.threshold = threshold
        self.simulate_typing = simulate_typing
        self.simulate_read = simulate_read
        self.respect_peer_cooldown: bool = False
        self.respect_global_rps: bool = False

        self.peers: Dict[str | int, SimPeer] = {}
        self.events: List[SimEvent] = []

    def reset(self) -> None:
        self.peers.clear()
        self.events.clear()

    def export_report(self) -> Dict[str, Any]:
        summary = {
            "num_events": len(self.events),
            "num_peers": len(self.peers),
            "folders": {
                "MANUAL": sum(1 for p in self.peers.values() if p.folder is SimFolder.MANUAL),
                "BOT": sum(1 for p in self.peers.values() if p.folder is SimFolder.BOT),
                "TIMEWASTER": sum(1 for p in self.peers.values() if p.folder is SimFolder.TIMEWASTER),
                "CONFIRMATION": sum(1 for p in self.peers.values() if p.folder is SimFolder.CONFIRMATION),
            },
            "assert_pass": sum(1 for e in self.events if e.kind == "assert" and e.payload.get("pass") is True),
            "assert_fail": sum(1 for e in self.events if e.kind == "assert" and e.payload.get("pass") is False),
        }
        return {
            "peers": {str(k): {"peer_id": str(v.peer_id), "display_name": v.display_name, "folder": v.folder.name, "history": v.history} for k, v in self.peers.items()},
            "events": [asdict(e) for e in self.events],
            "summary": summary,
        }

    def add_peer(self, peer_id: str | int, name: str, folder: SimFolder = SimFolder.BOT) -> SimPeer:
        peer = SimPeer(peer_id=peer_id, display_name=name, folder=folder)
        self.peers[peer_id] = peer
        return peer

    def _now(self) -> float:
        return time.time()

    def _event(self, kind: str, level: str = "INFO", **payload: Any) -> None:
        evt = SimEvent(ts=self._now(), kind=kind, payload=payload)
        self.events.append(evt)
        try:
            from .logging import logger

            if level == "ERROR":
                logger.error({"kind": kind, **payload})
            elif level == "WARNING":
                logger.warning({"kind": kind, **payload})
            else:
                logger.info({"kind": kind, **payload})
        except Exception:
            pass

    async def incoming(self, peer_id: str | int, text: str) -> None:
        peer = self.peers.setdefault(peer_id, SimPeer(peer_id=peer_id, display_name=str(peer_id)))
        peer.history.append({"role": "user", "text": text, "ts": self._now()})
        self._event("incoming", peer_id=str(peer_id), text=text)
        await self.process(peer_id, text)

    async def process(self, peer_id: str | int, text: str) -> None:
        peer = self.peers[peer_id]
        if peer.folder in (SimFolder.MANUAL, SimFolder.TIMEWASTER, SimFolder.CONFIRMATION):
            self._event("ignored", peer_id=str(peer_id), folder=peer.folder.name)
            return

        if self.simulate_read:
            self._event("read", peer_id=str(peer_id))

        action, payload = route(text, self.rules)
        self._event(
            "route",
            peer_id=str(peer_id),
            action=action,
            payload=payload,
            flags={
                "respect_peer_cooldown": self.respect_peer_cooldown,
                "respect_global_rps": self.respect_global_rps,
            },
        )

        if action == "send_template":
            template_key = payload.get("template_key", "welcome")
            reply = render_template(self.templates, template_key)
            if not reply:
                reply = self.templates.get("welcome", "Thanks for your message.")
            delay = typing_delay(len(reply))
            if self.simulate_typing:
                self._event("typing", peer_id=str(peer_id), delay=delay)
            self._event("send", peer_id=str(peer_id), text=reply, template=template_key)
            peer.history.append({"role": "bot", "text": reply, "ts": self._now()})

        if action == "move_timewaster":
            peer.folder = SimFolder.TIMEWASTER
            self._event("move_folder", peer_id=str(peer_id), folder=peer.folder.name)
            return

        if action == "move_confirmation":
            peer.folder = SimFolder.CONFIRMATION
            self._event("move_folder", peer_id=str(peer_id), folder=peer.folder.name)
            return

        if action == "manual":
            # If classifier available, try it
            if self.classifier is not None:
                self._event("llm_call", peer_id=str(peer_id))
                try:
                    result = await self.classifier(text, [m["text"] for m in peer.history if m["role"] == "user"])  # type: ignore[index]
                except Exception as exc:
                    self._event("llm_result", level="ERROR", peer_id=str(peer_id), error=str(exc))
                    peer.folder = SimFolder.MANUAL
                    self._event("move_folder", peer_id=str(peer_id), folder=peer.folder.name)
                    return

                intent = str(result.get("intent", "other"))
                confidence = float(result.get("confidence", 0.0))
                reply = result.get("reply")
                self._event("llm_result", peer_id=str(peer_id), intent=intent, confidence=confidence, reply=reply)

                if reply and confidence >= self.threshold:
                    reply_text = str(reply)
                    delay = typing_delay(len(reply_text))
                    if self.simulate_typing:
                        self._event("typing", peer_id=str(peer_id), delay=delay)
                    self._event("send", peer_id=str(peer_id), text=reply_text, template=None)
                    peer.history.append({"role": "bot", "text": reply_text, "ts": self._now()})
                    return

            # Fallback: move to manual
            peer.folder = SimFolder.MANUAL
            self._event("move_folder", peer_id=str(peer_id), folder=peer.folder.name)


