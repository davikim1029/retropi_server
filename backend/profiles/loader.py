"""Controller-profile loading and validation.

Profiles are declarative YAML (see gameboy.yaml). This module parses one into an
in-memory :class:`Profile` and validates its shape. It deliberately has **no
uinput dependency** so it imports and runs on any platform (including the Mac and
in tests); resolving the `code`/`axis` strings to real kernel constants is the
uinput driver's job.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from backend.config import PROFILES_DIR

# Hat directions are encoded as -1 / +1 on an axis; 0 is the resting (centered) value.
VALID_HAT_VALUES = (-1, 1)


class ProfileError(ValueError):
    """Raised when a profile file is missing or fails schema validation."""


@dataclass(frozen=True)
class KeyBinding:
    """A digital gamepad button (emitted as 1=down / 0=up)."""

    button: str  # logical name, e.g. "A"
    code: str    # uinput constant name, e.g. "BTN_SOUTH"
    type: str = "key"


@dataclass(frozen=True)
class HatBinding:
    """One direction on a hat axis; the driver combines opposing directions."""

    button: str  # logical name, e.g. "UP"
    axis: str    # "HAT0X" or "HAT0Y"
    value: int   # -1 or +1
    type: str = "hat"


Binding = KeyBinding | HatBinding


@dataclass(frozen=True)
class Profile:
    name: str
    display_name: str
    bindings: dict[str, Binding]  # keyed by logical button name
    # Optional RetroArch hotkeys: action name -> logical button (e.g. {"exit": "EXIT"}).
    # Consumed by autoconfig.py; lets a single pad button quit the game. See gameboy.yaml.
    hotkeys: dict[str, str] = field(default_factory=dict)

    @property
    def buttons(self) -> list[str]:
        """Logical button names, in profile order."""
        return list(self.bindings.keys())

    def key_codes(self) -> list[str]:
        """Distinct uinput KEY constant names used by this profile."""
        seen: list[str] = []
        for b in self.bindings.values():
            if isinstance(b, KeyBinding) and b.code not in seen:
                seen.append(b.code)
        return seen

    def hat_axes(self) -> list[str]:
        """Distinct hat axis names (e.g. HAT0X, HAT0Y) used by this profile."""
        seen: list[str] = []
        for b in self.bindings.values():
            if isinstance(b, HatBinding) and b.axis not in seen:
                seen.append(b.axis)
        return seen


def _parse_binding(button: str, spec: object) -> Binding:
    if not isinstance(spec, dict):
        raise ProfileError(f"button '{button}': expected a mapping, got {type(spec).__name__}")

    btype = spec.get("type")
    if btype == "key":
        code = spec.get("code")
        if not isinstance(code, str) or not code:
            raise ProfileError(f"button '{button}': key binding needs a non-empty 'code'")
        return KeyBinding(button=button, code=code)

    if btype == "hat":
        axis = spec.get("axis")
        value = spec.get("value")
        if not isinstance(axis, str) or not axis:
            raise ProfileError(f"button '{button}': hat binding needs a non-empty 'axis'")
        if value not in VALID_HAT_VALUES:
            raise ProfileError(
                f"button '{button}': hat 'value' must be one of {VALID_HAT_VALUES}, got {value!r}"
            )
        return HatBinding(button=button, axis=axis, value=int(value))

    raise ProfileError(f"button '{button}': type must be 'key' or 'hat', got {btype!r}")


def parse_profile(data: dict) -> Profile:
    """Validate a parsed-YAML mapping and build a :class:`Profile`."""
    if not isinstance(data, dict):
        raise ProfileError("profile root must be a mapping")

    name = data.get("name")
    if not isinstance(name, str) or not name:
        raise ProfileError("profile needs a non-empty 'name'")

    display_name = data.get("display_name") or name

    buttons = data.get("buttons")
    if not isinstance(buttons, dict) or not buttons:
        raise ProfileError("profile needs a non-empty 'buttons' mapping")

    bindings: dict[str, Binding] = {
        str(button): _parse_binding(str(button), spec) for button, spec in buttons.items()
    }

    hotkeys_raw = data.get("hotkeys") or {}
    if not isinstance(hotkeys_raw, dict):
        raise ProfileError("'hotkeys' must be a mapping of action -> button name")
    hotkeys: dict[str, str] = {}
    for action, button in hotkeys_raw.items():
        if not isinstance(button, str) or button not in bindings:
            raise ProfileError(
                f"hotkey '{action}' references unknown button {button!r} (not in 'buttons')"
            )
        hotkeys[str(action)] = button

    return Profile(
        name=name, display_name=str(display_name), bindings=bindings, hotkeys=hotkeys
    )


def load_profile(name: str, profiles_dir: Path | None = None) -> Profile:
    """Load and validate the profile named ``name`` from the profiles directory."""
    base = profiles_dir or PROFILES_DIR
    path = base / f"{name}.yaml"
    if not path.exists():
        raise ProfileError(f"profile '{name}' not found at {path}")
    try:
        data = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:  # pragma: no cover - defensive
        raise ProfileError(f"profile '{name}' is not valid YAML: {exc}") from exc
    return parse_profile(data)
