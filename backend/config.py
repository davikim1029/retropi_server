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

    # --- Live video / "stream mode" (optional, off by default) -------------------
    # The split-screen browser mode streams the Pi's screen as MJPEG. It runs an ffmpeg
    # subprocess fully decoupled from the controller path, so it can't disturb input even
    # if capture fails. Default off because it needs ffmpeg + (for kmsgrab) CAP_SYS_ADMIN.
    video_enabled: bool = os.environ.get("RPC_VIDEO_ENABLED", "").lower() in ("1", "true", "yes")
    # Capture backend: "kmsgrab" (correct for the Pi's full-KMS stack — reads the buffer
    # already scanned out to HDMI, so the TV is unaffected), "fbdev" (diagnostic
    # fallback; under full KMS /dev/fb0 usually shows the console), or "test" (force the
    # bundled-frame mock even on the Pi, to test transport without real capture).
    video_capture: str = os.environ.get("RPC_VIDEO_CAPTURE", "kmsgrab")
    video_fps: int = _env_int("RPC_VIDEO_FPS", 15)
    # Output width; height is derived to preserve aspect (keeps the Pi 3B + Wi-Fi happy).
    video_width: int = _env_int("RPC_VIDEO_WIDTH", 480)
    # ffmpeg MJPEG quality (-q:v): 2 best … 31 worst.
    video_quality: int = _env_int("RPC_VIDEO_QUALITY", 7)
    video_dri_device: str = os.environ.get("RPC_VIDEO_DRI_DEVICE", "/dev/dri/card1")
    video_fb_device: str = os.environ.get("RPC_VIDEO_FB_DEVICE", "/dev/fb0")
    # Full ffmpeg command override (shlex-split). The escape hatch for tuning the VC4
    # kmsgrab pipeline on hardware without code changes; must end by writing MJPEG to
    # stdout (… -f mjpeg pipe:1). Empty => build the command from the settings above.
    video_ffmpeg_cmd: str = os.environ.get("RPC_VIDEO_FFMPEG_CMD", "")


settings = Settings()
