"""RetroArch autoconfig generation (PEDD §14).

Produces a `<device>.cfg` so RetroArch/RetroPie recognizes the virtual gamepad
automatically instead of making the user map it by hand. The file is derived
entirely from the controller profile, so it stays correct as profiles change.

Button numbering: RetroArch's **udev** joypad driver numbers buttons by ascending
evdev key code. We replicate that here from `BTN_CODES`, so the index we write for
each button matches what RetroArch will assign to the codes our uinput device
declares. (If a particular RetroArch build numbers differently, confirm with
`jstest /dev/input/jsX` and regenerate.) The d-pad, declared as a hat, maps to the
`h0<dir>` tokens.
"""

from __future__ import annotations

import logging
from pathlib import Path

from backend.input.driver import DEVICE_NAME
from backend.profiles.loader import HatBinding, KeyBinding, Profile

logger = logging.getLogger(__name__)

# Linux evdev gamepad button codes (from input-event-codes.h). Aliases share a code
# (BTN_SOUTH == BTN_A, etc.); index ranking uses the numeric value.
BTN_CODES: dict[str, int] = {
    "BTN_SOUTH": 0x130, "BTN_A": 0x130,
    "BTN_EAST": 0x131, "BTN_B": 0x131,
    "BTN_C": 0x132,
    "BTN_NORTH": 0x133, "BTN_X": 0x133,
    "BTN_WEST": 0x134, "BTN_Y": 0x134,
    "BTN_Z": 0x135,
    "BTN_TL": 0x136, "BTN_TR": 0x137,
    "BTN_TL2": 0x138, "BTN_TR2": 0x139,
    "BTN_SELECT": 0x13A, "BTN_START": 0x13B,
    "BTN_MODE": 0x13C,
    "BTN_THUMBL": 0x13D, "BTN_THUMBR": 0x13E,
}

# Valid RetroArch RetroPad button binds (the stem of input_<stem>_btn). A profile
# button whose lowercased name isn't here (e.g. EXIT) is not a game bind — it only
# takes effect via the hotkeys section below, so it never reaches the running game.
RETROPAD_BTN_FIELDS: frozenset[str] = frozenset(
    {"a", "b", "x", "y", "l", "r", "l2", "r2", "l3", "r3",
     "start", "select", "up", "down", "left", "right"}
)

# Friendly hotkey action -> RetroArch field stem (emitted as input_<stem>_btn).
HOTKEY_FIELDS: dict[str, str] = {
    "enable": "enable_hotkey",   # held to arm hotkeys
    "exit": "exit_emulator",     # quit back to EmulationStation
    "menu": "menu_toggle",       # open the in-game RetroArch (RGUI) menu
}


def autoconfig_filename() -> str:
    return f"{DEVICE_NAME}.cfg"


def button_index(code: str, key_codes: list[str]) -> int:
    """Index RetroArch (udev driver) assigns this key: rank by ascending evdev code.

    Shared with es_input.py so the EmulationStation joystick map uses identical
    button numbering.
    """
    target = BTN_CODES[code]
    return sum(1 for other in key_codes if BTN_CODES[other] < target)


def _hat_token(axis: str, value: int) -> str:
    """Map a hat axis + direction to a RetroArch hat token like 'h0up'."""
    hat_num = "".join(ch for ch in axis if ch.isdigit()) or "0"
    letter = axis[-1].upper()
    if letter == "X":
        direction = "left" if value < 0 else "right"
    elif letter == "Y":
        direction = "up" if value < 0 else "down"
    else:
        raise ValueError(f"unsupported hat axis {axis!r}")
    return f"h{hat_num}{direction}"


def generate_autoconfig(profile: Profile, input_driver: str = "udev") -> str:
    key_codes = profile.key_codes()
    for code in key_codes:
        if code not in BTN_CODES:
            raise ValueError(f"no known evdev code for {code!r}; add it to BTN_CODES")

    def token_for(binding: KeyBinding | HatBinding) -> str:
        if isinstance(binding, KeyBinding):
            return str(button_index(binding.code, key_codes))
        return _hat_token(binding.axis, binding.value)

    lines = [
        f'input_device = "{DEVICE_NAME}"',
        f'input_driver = "{input_driver}"',
        "",
    ]
    for logical, binding in profile.bindings.items():
        field = logical.lower()
        if field not in RETROPAD_BTN_FIELDS:
            continue  # non-standard button (e.g. EXIT) — handled as a hotkey, not a game bind
        lines.append(f'input_{field}_btn = "{token_for(binding)}"')

    hotkey_lines = []
    for action, button in profile.hotkeys.items():
        stem = HOTKEY_FIELDS.get(action)
        if stem is None:
            raise ValueError(f"unknown hotkey action {action!r}; known: {sorted(HOTKEY_FIELDS)}")
        hotkey_lines.append(f'input_{stem}_btn = "{token_for(profile.bindings[button])}"')
    if hotkey_lines:
        lines.append("")
        lines.extend(hotkey_lines)

    return "\n".join(lines) + "\n"


def write_autoconfig(profile: Profile, directory: Path | str) -> Path | None:
    """Write the autoconfig into ``directory`` (e.g. RetroPie's joypad dir).

    Returns the written path, or None if the directory is absent (expected off the
    Pi) or unwritable (logged as a warning — likely needs different ownership/perms).
    """
    directory = Path(directory)
    if not directory.is_dir():
        logger.info("autoconfig dir %s not found; skipping (expected when not on the Pi)", directory)
        return None

    path = directory / autoconfig_filename()
    try:
        path.write_text(generate_autoconfig(profile))
    except OSError as exc:
        logger.warning("could not write RetroArch autoconfig to %s: %s", path, exc)
        return None
    logger.info("wrote RetroArch autoconfig: %s", path)
    return path
