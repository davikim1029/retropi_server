"""Privileged host actions triggered from the controller (currently: reboot).

The client's REBOOT button sends ``{"type":"system","action":"reboot"}`` over the
WebSocket; :func:`request_reboot` turns that into a real power-cycle of the Pi.

Two layers keep this safe to ship in the same codebase we develop on the Mac:

* **Dev guard** — a reboot only ever runs on a real Pi: ``settings.allow_reboot`` is
  on, we're on Linux, and the mock driver isn't forced. So the button is inert on
  macOS, in tests, and under ``RPC_FORCE_MOCK`` (it will never reboot your laptop or
  a CI runner).
* **Privilege** — the service runs as a non-root user, so it shells out to
  ``sudo -n systemctl reboot``. ``scripts/install.sh`` writes the matching
  ``/etc/sudoers.d`` NOPASSWD rule scoped to exactly that command; ``-n`` makes sudo
  fail fast (rather than hang on a password prompt) if the rule is missing.

Note: the security model (auth/origin) is still deferred, so any device on the LAN
that loads the page can trigger this — which is why the UI gates it behind a
confirm dialog. Lock it down with ``RPC_ALLOW_REBOOT=0`` until pairing lands.
"""

from __future__ import annotations

import logging
import platform
import socket
import subprocess

from backend.config import settings

logger = logging.getLogger(__name__)

# Resolved by sudo via secure_path; install.sh authorizes this exact command.
REBOOT_COMMAND = ["sudo", "-n", "systemctl", "reboot"]

# RetroArch's UDP network-command interface (network_cmd_enable + network_cmd_port
# in retroarch.cfg). Used for the ★ Save/Load-state menu.
RA_CMD_ADDR = ("127.0.0.1", 55355)


def send_retroarch_command(command: str) -> bool:
    """Send a RetroArch network command (e.g. "SAVE_STATE", "LOAD_STATE") over UDP.

    Fire-and-forget: harmless if no game is running / nothing is listening (e.g. on
    the Mac), so no Pi guard is needed — it's not a privileged action."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.sendto((command + "\n").encode(), RA_CMD_ADDR)  # RetroArch needs newline-terminated
        return True
    except Exception:  # pragma: no cover - defensive
        logger.exception("failed to send RetroArch command %r", command)
        return False


def request_reboot() -> bool:
    """Reboot the host if running on a real Pi. Returns True if one was initiated.

    No-ops (returning False) when disabled via config, or whenever we're not on an
    actual device — the mock driver or a non-Linux host — so it is safe to call from
    tests and from the Mac dev server.
    """
    if not settings.allow_reboot:
        logger.warning("reboot requested but RPC_ALLOW_REBOOT is disabled; ignoring")
        return False
    if settings.force_mock or platform.system() != "Linux":
        logger.info("reboot requested but not on a real Pi (mock/non-Linux); ignoring")
        return False

    logger.warning("reboot requested by client; running %s", " ".join(REBOOT_COMMAND))
    try:
        # Fire-and-forget: systemd tears us (and the gamepad) down during shutdown,
        # which releases all buttons via the lifespan's driver.close().
        subprocess.Popen(REBOOT_COMMAND)
    except Exception:  # pragma: no cover - defensive; sudo missing, etc.
        logger.exception("failed to invoke reboot")
        return False
    return True
