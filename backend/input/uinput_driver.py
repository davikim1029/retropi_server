"""Real Linux virtual-gamepad backend (python-uinput).

Creates a kernel device named exactly ``DEVICE_NAME`` ("iPhone Virtual Gamepad")
that RetroArch/udev sees as a normal pad at ``/dev/input/eventX``.

Importing this module requires the ``uinput`` package, so it is imported lazily by
``create_driver()`` and never on macOS. Building the device additionally requires
the uinput kernel module loaded and write access to ``/dev/uinput`` (see the Pi
setup notes in ``docs/SETUP.md``); those errors surface at ``open()`` time.

Profile binding names map to uinput constants like so:
* key ``code`` is a full constant name, e.g. ``BTN_SOUTH`` -> ``uinput.BTN_SOUTH``.
* hat ``axis`` is the short form, e.g. ``HAT0X`` -> ``uinput.ABS_HAT0X``.
"""

from __future__ import annotations

import logging

import uinput  # noqa: F401  (Linux-only; absence is handled by create_driver)

from backend.input.driver import BaseGamepadDriver, Channel, DEVICE_NAME
from backend.profiles.loader import Profile

logger = logging.getLogger(__name__)

# Hat axes report -1 / 0 / +1.
_HAT_RANGE = (-1, 1, 0, 0)  # (min, max, fuzz, flat)


class UinputGamepadDriver(BaseGamepadDriver):
    def __init__(self) -> None:
        super().__init__()
        self._device: uinput.Device | None = None
        # channel -> 2-tuple (etype, code) used by Device.emit().
        self._events: dict[Channel, tuple] = {}

    @property
    def name(self) -> str:
        return "uinput"

    def _build_device(self, profile: Profile) -> None:
        device_events: list[tuple] = []

        for code in profile.key_codes():
            event = self._resolve(code)
            self._events[("key", code)] = event
            device_events.append(event)

        for axis in profile.hat_axes():
            event = self._resolve(f"ABS_{axis}")
            self._events[("hat", axis)] = event
            # ABS events need their range appended when declaring the device.
            device_events.append(event + _HAT_RANGE)

        self._device = uinput.Device(device_events, name=DEVICE_NAME)
        logger.info("uinput device created with %d events", len(device_events))

    @staticmethod
    def _resolve(constant: str) -> tuple:
        try:
            return getattr(uinput, constant)
        except AttributeError as exc:
            raise ValueError(f"unknown uinput constant '{constant}'") from exc

    def _emit(self, channel: Channel, value: int) -> None:
        assert self._device is not None
        self._device.emit(self._events[channel], value, syn=False)

    def _syn(self) -> None:
        assert self._device is not None
        self._device.syn()

    def _teardown(self) -> None:
        if self._device is not None:
            try:
                self._device.destroy()
            except Exception:  # pragma: no cover - best-effort cleanup
                logger.exception("error destroying uinput device")
            self._device = None
