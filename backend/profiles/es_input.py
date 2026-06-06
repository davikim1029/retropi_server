"""EmulationStation joystick input config (es_input.cfg).

The RetroArch autoconfig (``autoconfig.py``) handles *in-game* input, but
EmulationStation — RetroPie's menu/launcher — reads its own ``es_input.cfg`` to
navigate the UI with a pad. A fresh image only maps the keyboard, so the iPhone
pad can't drive the menus until a joystick ``<inputConfig>`` is added. This module
derives that block from the controller profile (reusing the RetroArch autoconfig's
button ordering) and merges it into an existing ``es_input.cfg`` *without
disturbing the keyboard entry*.

EmulationStation matches a connected pad to a config by SDL2 GUID. Our uinput
device exposes no USB vendor/product, so SDL derives the GUID from the bus type +
device name; for the fixed name ``"iPhone Virtual Gamepad"`` that value is stable,
so the same config keeps matching across reboots and redeploys.
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from pathlib import Path

from backend.input.driver import DEVICE_NAME
from backend.profiles.autoconfig import button_index  # shared udev button ordering
from backend.profiles.loader import HatBinding, KeyBinding, Profile

logger = logging.getLogger(__name__)

# SDL2 name-derived GUID for "iPhone Virtual Gamepad" (bus 0x0000 + crc + the
# device name as ASCII). Captured from the working Pi (RPi OS Bullseye, SDL2);
# stable for this device name + SDL build. Override via the CLI/install env if a
# different SDL build computes another value.
ES_DEVICE_GUID = "000098a66950686f6e65205669727400"

# EmulationStation navigation action -> logical profile button. ES tolerates a
# partial map, so profiles missing one of these simply omit that entry.
ES_NAV_MAP: dict[str, str] = {
    "a": "A",
    "b": "B",
    "start": "START",
    "select": "SELECT",
    "up": "UP",
    "down": "DOWN",
    "left": "LEFT",
    "right": "RIGHT",
}

# SDL hat bitmask per direction (centered = 0).
_HAT_BITS = {"up": 1, "right": 2, "down": 4, "left": 8}


def _hat_bit(axis: str, value: int) -> int:
    """SDL hat bitmask for a profile hat direction (e.g. HAT0X/+1 -> 2 = right)."""
    letter = axis[-1].upper()
    if letter == "X":
        return _HAT_BITS["left" if value < 0 else "right"]
    if letter == "Y":
        return _HAT_BITS["up" if value < 0 else "down"]
    raise ValueError(f"unsupported hat axis {axis!r}")


def _nav_entries(profile: Profile) -> list[tuple[str, str, str, str]]:
    """(name, type, id, value) for each ES nav action this profile supports."""
    key_codes = profile.key_codes()
    entries: list[tuple[str, str, str, str]] = []
    for nav, button in ES_NAV_MAP.items():
        binding = profile.bindings.get(button)
        if isinstance(binding, KeyBinding):
            entries.append((nav, "button", str(button_index(binding.code, key_codes)), "1"))
        elif isinstance(binding, HatBinding):
            hat_num = "".join(ch for ch in binding.axis if ch.isdigit()) or "0"
            entries.append((nav, "hat", hat_num, str(_hat_bit(binding.axis, binding.value))))
    return entries


def build_inputconfig(profile: Profile, guid: str = ES_DEVICE_GUID) -> ET.Element:
    """Build the ``<inputConfig type="joystick">`` element for ``profile``."""
    cfg = ET.Element(
        "inputConfig",
        {"type": "joystick", "deviceName": DEVICE_NAME, "deviceGUID": guid},
    )
    for name, itype, iid, value in _nav_entries(profile):
        ET.SubElement(cfg, "input", {"name": name, "type": itype, "id": iid, "value": value})
    return cfg


def generate_es_input_block(profile: Profile, guid: str = ES_DEVICE_GUID) -> str:
    """The joystick ``<inputConfig>`` block as pretty-printed XML (for inspection)."""
    el = build_inputconfig(profile, guid)
    ET.indent(el, space="  ")
    return ET.tostring(el, encoding="unicode")


def merge_es_input(
    profile: Profile, path: Path | str, guid: str = ES_DEVICE_GUID
) -> Path | None:
    """Insert/replace our joystick ``<inputConfig>`` in an existing es_input.cfg.

    Preserves every other entry (notably the keyboard map and the onfinish action),
    and is idempotent — a prior config for our device name is replaced, never
    duplicated. Returns the path on success, or None if the file is absent (ES
    hasn't written one yet) or unparseable — both logged rather than raised,
    mirroring :func:`autoconfig.write_autoconfig`.
    """
    path = Path(path)
    if not path.is_file():
        logger.info("es_input.cfg not found at %s; skipping (boot ES once to create it)", path)
        return None
    try:
        tree = ET.parse(path)
    except ET.ParseError as exc:
        logger.warning("could not parse %s: %s", path, exc)
        return None

    root = tree.getroot()
    if root.tag != "inputList":
        logger.warning("%s root is <%s>, expected <inputList>; skipping", path, root.tag)
        return None

    # Drop any prior config for our device (match by name), then add the fresh one.
    for existing in root.findall("inputConfig"):
        if existing.get("deviceName") == DEVICE_NAME:
            root.remove(existing)
    root.append(build_inputconfig(profile, guid))

    ET.indent(tree, space="  ")
    try:
        path.write_text('<?xml version="1.0"?>\n' + ET.tostring(root, encoding="unicode") + "\n")
    except OSError as exc:
        logger.warning("could not write %s: %s", path, exc)
        return None
    logger.info("merged joystick mapping into %s", path)
    return path
