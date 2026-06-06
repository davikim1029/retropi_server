"""Session tracking and the fail-safe release path.

A session is created per WebSocket connection and refreshed on every message
(including the 2s heartbeat). Two things end a session:

* the WebSocket disconnects (handled by the endpoint), or
* it goes quiet past ``timeout_s`` and the reaper collects it.

Either way the gamepad's buttons are released. The MVP drives a single virtual
gamepad, so removing any session triggers ``release_all`` — there is no per-session
button ownership to preserve yet.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Callable

from backend.input.state import InputStateEngine

logger = logging.getLogger(__name__)


@dataclass
class Session:
    session_id: str
    profile: str
    created_at: float
    last_seen: float


class SessionManager:
    def __init__(
        self,
        engine: InputStateEngine,
        timeout_s: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._engine = engine
        self._timeout_s = timeout_s
        self._clock = clock
        self._lock = threading.Lock()
        self._sessions: dict[str, Session] = {}

    @property
    def count(self) -> int:
        with self._lock:
            return len(self._sessions)

    def create(self, profile: str) -> Session:
        now = self._clock()
        session = Session(
            session_id=str(uuid.uuid4()),
            profile=profile,
            created_at=now,
            last_seen=now,
        )
        with self._lock:
            self._sessions[session.session_id] = session
        logger.info("session %s created (profile=%s)", session.session_id, profile)
        return session

    def touch(self, session_id: str) -> None:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is not None:
                session.last_seen = self._clock()

    def remove(self, session_id: str) -> None:
        with self._lock:
            existed = self._sessions.pop(session_id, None) is not None
        if existed:
            logger.info("session %s removed", session_id)
            # Single shared gamepad: any disconnect must release buttons so nothing
            # stays stuck down.
            self._engine.release_all()

    def reap(self) -> int:
        """Remove sessions idle past the timeout. Returns how many were reaped."""
        cutoff = self._clock() - self._timeout_s
        with self._lock:
            stale = [sid for sid, s in self._sessions.items() if s.last_seen < cutoff]
            for sid in stale:
                del self._sessions[sid]
        for sid in stale:
            logger.info("session %s timed out", sid)
        if stale:
            self._engine.release_all()
        return len(stale)
