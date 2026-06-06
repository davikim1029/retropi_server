"""Runtime configuration.

Values come from environment variables (handy for the systemd unit) with sane
defaults that match the design doc: port 8080, Game Boy profile, 15-minute
inactivity timeout.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# Repo root (…/retropi_server). Used to locate the frontend/ and profiles/ dirs.
ROOT_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = ROOT_DIR / "frontend"
PROFILES_DIR = Path(__file__).resolve().parent / "profiles"


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    host: str = os.environ.get("RPC_HOST", "0.0.0.0")
    port: int = _env_int("RPC_PORT", 8080)
    # Controller profile loaded at startup; the single virtual gamepad uses this.
    profile: str = os.environ.get("RPC_PROFILE", "gameboy")
    # Release all buttons + drop a session after this many seconds with no traffic.
    session_timeout_s: float = float(_env_int("RPC_SESSION_TIMEOUT", 15 * 60))
    # How often the session reaper checks for stale sessions.
    reaper_interval_s: float = float(_env_int("RPC_REAPER_INTERVAL", 5))
    # Force the mock driver even on Linux (useful for headless CI / dev on the Pi).
    force_mock: bool = os.environ.get("RPC_FORCE_MOCK", "").lower() in ("1", "true", "yes")
    log_level: str = os.environ.get("RPC_LOG_LEVEL", "INFO").upper()
    # Allow the client REBOOT button to power-cycle the host (runs `sudo systemctl
    # reboot`; install.sh grants the narrow NOPASSWD rule). Even when enabled it only
    # fires on a real Pi — never under the mock driver or off-Linux (dev safety), so
    # the button can't reboot your Mac. Set RPC_ALLOW_REBOOT=0 to disable entirely.
    allow_reboot: bool = os.environ.get("RPC_ALLOW_REBOOT", "1").lower() in ("1", "true", "yes")
    # Write the RetroArch autoconfig on startup so RetroPie auto-detects the pad.
    # Default dir is RetroPie's joypad autoconfig directory; harmlessly skipped when
    # absent (e.g. on the Mac). Set RPC_WRITE_AUTOCONFIG=0 to disable.
    write_autoconfig: bool = os.environ.get("RPC_WRITE_AUTOCONFIG", "1").lower() in ("1", "true", "yes")
    autoconfig_dir: str = os.environ.get(
        "RPC_AUTOCONFIG_DIR", "/opt/retropie/configs/all/retroarch-joypads"
    )


settings = Settings()
