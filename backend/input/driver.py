"""Virtual-gamepad driver abstraction.

The :class:`GamepadDriver` interface decouples the rest of the app from the kernel.
Two backends implement it:

* ``UinputGamepadDriver`` — the real Linux device (python-uinput), used on the Pi.
* ``MockGamepadDriver`` — records emitted events; used on macOS, in tests, and for
  any headless run via ``RPC_FORCE_MOCK``.

``create_driver()`` picks the right one at runtime, so no other module needs to know
which platform it is on.

Logical button state (``{"A": True, "RIGHT": False, ...}``) is translated into
low-level *channels* shared by both backends:

* ``("key", "<CODE>")`` — a digital button, value 0/1.
* ``("hat", "<AXIS>")`` — a hat axis, value resolved from its directions so that
  opposing presses (UP+DOWN) cancel to 0.
"""

from __future__ import annotations

import logging
import platform
from abc import ABC, abstractmethod

from backend.profiles.loader import HatBinding, KeyBinding, Profile

logger = logging.getLogger(__name__)

# A low-level output channel: (kind, name). `kind` is "key" or "hat".
Channel = tuple[str, str]

# The kernel-visible device name. This is a hard contract: RetroPie/udev autoconfig
# matches on it byte-for-byte, so do not change it without updating the autoconfig.
DEVICE_NAME = "iPhone Virtual Gamepad"


def resolve_channels(profile: Profile, state: dict[str, bool]) -> dict[Channel, int]:
    """Translate logical button state into target channel values.

    Keys map straight to 0/1. Each hat axis sums the values of its pressed
    directions and clamps to [-1, 1], so UP+DOWN -> 0 and a lone UP -> -1.
    """
    out: dict[Channel, int] = {}
    for binding in profile.bindings.values():
        if isinstance(binding, KeyBinding):
            out[("key", binding.code)] = 1 if state.get(binding.button) else 0

    for axis in profile.hat_axes():
        value = 0
        for binding in profile.bindings.values():
            if isinstance(binding, HatBinding) and binding.axis == axis and state.get(binding.button):
                value += binding.value
        out[("hat", axis)] = max(-1, min(1, value))
    return out


class GamepadDriver(ABC):
    """Public driver interface used by the input engine and server lifespan."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable backend name (for logs / /health)."""

    @abstractmethod
    def open(self, profile: Profile) -> None:
        """Create the virtual device for ``profile`` (idempotent per instance)."""

    @abstractmethod
    def sync(self, state: dict[str, bool]) -> None:
        """Drive the device to match ``state``, emitting only what changed."""

    @abstractmethod
    def release_all(self) -> None:
        """Release every button — the fail-safe on disconnect/timeout."""

    @abstractmethod
    def close(self) -> None:
        """Release all buttons and tear down the device."""


class BaseGamepadDriver(GamepadDriver):
    """Shared diff logic; backends only implement the low-level emit/teardown."""

    def __init__(self) -> None:
        self._profile: Profile | None = None
        # Last value emitted per channel, so sync() only emits real changes.
        self._last: dict[Channel, int] = {}

    @property
    def profile(self) -> Profile:
        if self._profile is None:
            raise RuntimeError("driver used before open()")
        return self._profile

    def open(self, profile: Profile) -> None:
        self._profile = profile
        # Device powers up centered/released; seed _last so the first press emits.
        self._last = {channel: 0 for channel in resolve_channels(profile, {})}
        self._build_device(profile)
        logger.info("%s opened for profile '%s' as %r", self.name, profile.name, DEVICE_NAME)

    def sync(self, state: dict[str, bool]) -> None:
        target = resolve_channels(self.profile, state)
        changed = False
        for channel, value in target.items():
            if self._last.get(channel) != value:
                self._emit(channel, value)
                self._last[channel] = value
                changed = True
        if changed:
            self._syn()

    def release_all(self) -> None:
        if self._profile is not None:
            self.sync({button: False for button in self._profile.buttons})

    def close(self) -> None:
        try:
            self.release_all()
        finally:
            self._teardown()
            logger.info("%s closed", self.name)

    # --- backend hooks -----------------------------------------------------
    @abstractmethod
    def _build_device(self, profile: Profile) -> None: ...

    @abstractmethod
    def _emit(self, channel: Channel, value: int) -> None: ...

    @abstractmethod
    def _syn(self) -> None: ...

    @abstractmethod
    def _teardown(self) -> None: ...


def create_driver(force_mock: bool = False) -> GamepadDriver:
    """Return the appropriate backend for this host.

    Uses the real uinput device on Linux when python-uinput is importable;
    otherwise (macOS, missing module, or ``force_mock``) returns the mock.
    """
    if not force_mock and platform.system() == "Linux":
        try:
            from backend.input.uinput_driver import UinputGamepadDriver

            return UinputGamepadDriver()
        except Exception as exc:  # ImportError or uinput load failure
            logger.warning("uinput backend unavailable (%s); falling back to mock driver", exc)

    from backend.input.mock_driver import MockGamepadDriver

    return MockGamepadDriver()
