"""Mock gamepad backend.

Implements the driver interface without any kernel interaction: it logs every
emitted channel change and records them on ``self.events`` for inspection in tests.
Used on macOS, under ``RPC_FORCE_MOCK``, and whenever the uinput backend can't load.
"""

from __future__ import annotations

import logging

from backend.input.driver import BaseGamepadDriver, Channel
from backend.profiles.loader import Profile

logger = logging.getLogger(__name__)


class MockGamepadDriver(BaseGamepadDriver):
    """Records emitted (channel, value) events instead of touching /dev/uinput."""

    def __init__(self) -> None:
        super().__init__()
        # Ordered log of every emit, e.g. [(("key", "BTN_SOUTH"), 1), ...].
        self.events: list[tuple[Channel, int]] = []
        self.syn_count = 0

    @property
    def name(self) -> str:
        return "mock"

    @property
    def state(self) -> dict[Channel, int]:
        """Current value of every channel (mirrors what a real device would hold)."""
        return dict(self._last)

    def _build_device(self, profile: Profile) -> None:
        logger.info(
            "mock device created: keys=%s hats=%s", profile.key_codes(), profile.hat_axes()
        )

    def _emit(self, channel: Channel, value: int) -> None:
        self.events.append((channel, value))
        logger.debug("mock emit %s = %s", channel, value)

    def _syn(self) -> None:
        self.syn_count += 1

    def _teardown(self) -> None:
        logger.debug("mock device torn down after %d emits", len(self.events))
