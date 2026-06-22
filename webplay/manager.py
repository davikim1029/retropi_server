"""Game lifecycle: ask the tty1 runner to launch a game, and read back state.

The web server has no VT, so it can't exec RetroArch on tty1 itself (the DRM-master
problem). Instead it writes a launch request to a FIFO the runner blocks on; the
runner execs the emulators.cfg command on tty1, streams video, and writes a status
file we read back. Quitting is done via the gamepad EXIT hotkey (BTN_MODE), which
RetroArch turns into a clean quit — the runner then returns to idle.

Pi-only side effects are guarded so Mac/dev and tests stay inert (mirrors
backend/system/control.py).
"""

from __future__ import annotations

import json
import os
import socket
from pathlib import Path

LAUNCH_FIFO = os.environ.get("RPC_LAUNCH_FIFO", "/tmp/rpc_launch")
STATE_FILE = os.environ.get("RPC_STATE_FILE", "/tmp/rpc_state")
# RetroArch UDP network-command interface (network_cmd_enable in retroarch.cfg).
RA_CMD_ADDR = (os.environ.get("RPC_RA_CMD_HOST", "127.0.0.1"), int(os.environ.get("RPC_RA_CMD_PORT", "55355")))


def send_retroarch_command(command: str) -> bool:
    """Fire a RetroArch network command (e.g. "SAVE_STATE", "LOAD_STATE") over UDP.
    Harmless if no game is running / nothing is listening."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.sendto((command + "\n").encode(), RA_CMD_ADDR)  # RetroArch needs newline-terminated
        return True
    except OSError:
        return False


class LauncherError(RuntimeError):
    pass


def request_launch(system: str, rom_path: str) -> None:
    """Write a launch request to the runner FIFO (non-blocking).

    Raises LauncherError if the runner isn't listening (FIFO has no reader) so the
    API can report it instead of hanging.
    """
    payload = (json.dumps({"system": system, "rom": rom_path}) + "\n").encode()
    try:
        fd = os.open(LAUNCH_FIFO, os.O_WRONLY | os.O_NONBLOCK)
    except FileNotFoundError as e:
        raise LauncherError("launch FIFO missing (runner not running)") from e
    except OSError as e:  # ENXIO: FIFO exists but the runner isn't blocked on it
        raise LauncherError("runner not ready for launch") from e
    try:
        os.write(fd, payload)
    finally:
        os.close(fd)


def quit_game() -> bool:
    """Power off the emulator via RetroArch's network QUIT command (clean exit, flushes
    SRAM; the tty1 runner then returns to idle). Uses UDP because the webplay *service*
    can't signal the tty1-session RetroArch process directly (different session)."""
    return send_retroarch_command("QUIT")


def read_state() -> dict:
    """Current runner state: {"status": "idle"|"running", "game": {...}|None}."""
    try:
        data = json.loads(Path(STATE_FILE).read_text())
        if isinstance(data, dict) and "status" in data:
            return data
    except (OSError, ValueError):
        pass
    return {"status": "idle", "game": None}
