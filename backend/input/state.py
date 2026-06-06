"""Authoritative controller state.

The :class:`InputStateEngine` holds one boolean per logical button and is the
correctness core of the system. Its defining invariant is **last-write-wins per
button**: pressing or releasing one button never disturbs another. So the sequence

    RIGHT down -> A down -> RIGHT up

leaves ``A`` pressed — preventing the "stuck button" / dropped-input bugs that come
from treating the controller as a single shared value.

After every change the engine pushes the full state to the gamepad driver, which
diffs and emits only what actually moved.
"""

from __future__ import annotations

import logging
import threading

from backend.input.driver import GamepadDriver
from backend.profiles.loader import Profile

logger = logging.getLogger(__name__)


class InputStateEngine:
    def __init__(self, profile: Profile, driver: GamepadDriver) -> None:
        self._profile = profile
        self._driver = driver
        # A lock keeps concurrent WebSocket handlers / the reaper from interleaving
        # a state mutation with a driver sync.
        self._lock = threading.Lock()
        self._state: dict[str, bool] = {button: False for button in profile.buttons}

    @property
    def state(self) -> dict[str, bool]:
        with self._lock:
            return dict(self._state)

    def press(self, button: str) -> None:
        self._set(button, True)

    def release(self, button: str) -> None:
        self._set(button, False)

    def _set(self, button: str, pressed: bool) -> None:
        with self._lock:
            if button not in self._state:
                # Unknown buttons (typo, wrong profile, malicious input) are ignored
                # rather than corrupting state.
                logger.warning("ignoring unknown button %r", button)
                return
            if self._state[button] == pressed:
                return  # no-op; nothing to sync
            self._state[button] = pressed
            self._driver.sync(self._state)

    def release_all(self) -> None:
        """Fail-safe: clear every button (disconnect, timeout, shutdown)."""
        with self._lock:
            if not any(self._state.values()):
                return
            for button in self._state:
                self._state[button] = False
            self._driver.sync(self._state)
            logger.info("released all buttons")
