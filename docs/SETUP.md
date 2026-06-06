# Setup & Test Guide

How to run the iPhone Virtual Gamepad locally on a Mac (mock gamepad) and deploy it to a
Raspberry Pi (real gamepad) so you can play RetroPie from your iPhone — no iOS app required.

- **Part A — Local dev/test on macOS** (no Pi needed; uses the mock driver)
- **Part B — Deploy & install on the Pi**
- **Part C — Connect from the iPhone**
- **Part D — Verify it actually works**
- **Troubleshooting**
- **Configuration reference**
- **Managing the service**

---

## Part A — Local dev/test on macOS

`python-uinput` is Linux-only, so on the Mac the app runs against a **mock driver** that records
button events instead of creating a kernel device. The whole stack (WebSocket, UI, sessions,
autoconfig generation) is exercisable here.

Dependencies are managed by [**uv**](https://docs.astral.sh/uv/) (`pyproject.toml` + `uv.lock`).

```bash
cd /Users/daviskim/Documents/GitHub/retropi_server

# 0. Install uv once if you don't have it:
#    macOS: brew install uv   (or: curl -LsSf https://astral.sh/uv/install.sh | sh)

# 1. Build .venv from the lockfile (installs runtime deps + the dev group: pytest, httpx)
uv sync

# 2. Run the test suite
uv run pytest -q
#   Run a single test:
uv run pytest tests/test_input_state.py::test_last_write_wins_per_button

# 3. Start the server
uv run app.py
#   Serves on http://localhost:8080 ; prints the LAN URL + a QR to the terminal.
#   Change the port with: RPC_PORT=9000 uv run app.py
```

`python-uinput` is platform-gated in `pyproject.toml`, so `uv sync` simply skips it on macOS —
no build, no error — and the app falls back to the mock driver here.

With the server running, open <http://localhost:8080> in a desktop browser. Click/drag the
buttons — the server log shows the mock driver emitting events (key on/off, hat resolution). The
d-pad uses a hat axis, so pressing Up+Down cancels to center.

Quick health check (in another terminal):

```bash
curl -s http://localhost:8080/health
# {"status":"healthy","connections":0,"uptime":..,"driver":"mock"}
```

Stop the server with `Ctrl-C`.

---

## Part B — Deploy & install on the Pi

The Pi is reachable at `ssh dkim@raspberrypi`. One script does everything: system packages
(incl. the `joystick`/`jstest` + `evtest` diagnostics), the uinput module + permissions, **uv and
the venv** (`uv sync`), the systemd service, the RetroArch autoconfig, the EmulationStation
joystick mapping (so the pad drives the launcher menus), and (if present) the firewall rule. (The
installer fetches `uv` to `/usr/local/bin` automatically — no manual install needed on the Pi.)

**1. Copy the code to the Pi** (run from the repo root on the Mac):

```bash
cd /Users/daviskim/Documents/GitHub/retropi_server
rsync -av --exclude .venv --exclude __pycache__ --exclude .git ./ dkim@raspberrypi:~/retropi_server/
```

**2. Run the installer on the Pi** (it self-sudos, so it will prompt for your password):

```bash
ssh dkim@raspberrypi
cd ~/retropi_server
./scripts/install.sh
```

Overrides (optional): `RPC_PORT=9000 ./scripts/install.sh` — also `RPC_USER`, `RPC_PROFILE`,
`RPC_AUTOCONFIG_DIR`. The script is **idempotent**; re-run it any time (e.g. after pulling new code).

**3. If it warns that `/dev/uinput` isn't present yet**, reboot once so the module autoloads:

```bash
sudo reboot
```

After that the uinput module + udev permissions are permanent and the service starts on boot.

---

## Part C — Connect from the iPhone

1. Put the iPhone on the **same Wi-Fi** as the Pi.
2. In **Safari**, open `http://raspberrypi.local:8080` (or the IP shown by the installer / in the
   logs). You can also scan the QR code from the service log (see below).
3. The status banner at the top should turn green: **Connected**.
4. Add to Home Screen (optional) for a full-screen, chrome-free controller.
5. Use the d-pad/buttons to navigate EmulationStation and pick a game. The **MENU** button
   (top-right) quits the current game and jumps back to the EmulationStation main page.

To see the QR / URL the server printed:

```bash
sudo journalctl -u iphone-controller -b --no-pager | tail -n 40
```

---

## Part D — Verify it actually works

On the Pi:

```bash
# Service is running
systemctl is-active iphone-controller            # -> active

# The virtual gamepad exists and is named correctly
grep -A5 "iPhone Virtual Gamepad" /proc/bus/input/devices

# Watch raw input events while you press buttons in Safari
sudo evtest            # pick the "iPhone Virtual Gamepad" device, then press buttons

# See the button index numbers RetroArch will use
jstest /dev/input/js0
```

(`evtest` and `jstest` are installed by the installer — no manual `apt install` needed.)

In **EmulationStation** (the launcher), the d-pad and A/B/Start/Select should move the menu —
that comes from the joystick entry the installer adds to `es_input.cfg`. Then launch a game: the
pad is auto-configured from the generated `iPhone Virtual Gamepad.cfg`, so it should "just work."
Press **MENU** to quit back to EmulationStation. If A and B feel swapped for a given core, note the
button numbers from `jstest` and adjust the autoconfig (see Troubleshooting).

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| Installer fails building `python-uinput` | Build deps are installed first, so this is rare. Paste the error; the fallback is a `python-evdev`-based driver (not yet written). |
| `/dev/uinput` missing / "permission denied" creating device | `sudo reboot` once (module autoload + udev rule). Confirm `dkim` is in the `input` group: `groups dkim`. |
| iPhone can't reach the page | Same Wi-Fi? Try the raw IP from `hostname -I` instead of `raspberrypi.local`. Confirm the service is `active`. |
| Controller connects but RetroArch ignores it | Check the cfg exists in the joypad dir (default `/opt/retropie/configs/all/retroarch-joypads/iPhone Virtual Gamepad.cfg`). Regenerate: `uv run scripts/generate_autoconfig.py --dir <joypad-dir>`. |
| A/B (or other buttons) mapped wrong | Run `jstest /dev/input/js0`, see which index each button reports, and edit the `input_*_btn` values in the cfg. The generator assumes RetroArch's udev (ascending evdev-code) ordering. |
| MENU doesn't exit the game | The exit hotkey lives in the autoconfig as `input_enable_hotkey_btn` + `input_exit_emulator_btn` (both the MENU button). Confirm they're present in `iPhone Virtual Gamepad.cfg`; regenerate with `uv run scripts/generate_autoconfig.py --dir <joypad-dir>`. As a fallback you can map them to a Select+Start combo. |
| Pad doesn't navigate EmulationStation menus | The joystick entry must be in `es_input.cfg` (`/opt/retropie/configs/all/emulationstation/` and/or `~/.emulationstation/`). Re-add it: `uv run scripts/generate_es_input.py --file <es_input.cfg>`, then restart EmulationStation. If ES uses a different `deviceGUID` for the pad, pass `--guid <guid>` (find it via the ES "Configure Input" flow or `jstest`). |
| Buttons get "stuck" | Shouldn't happen — any disconnect releases all buttons. If seen, capture `journalctl -u iphone-controller` and the repro steps. |
| Need to see what's happening | `sudo journalctl -u iphone-controller -f` (live logs). |

---

## Configuration reference

All env vars (set in the shell for `uv run app.py`, or as `Environment=` lines in the systemd unit
— the installer wires `RPC_PORT`, `RPC_PROFILE`, `RPC_AUTOCONFIG_DIR`):

| Variable | Default | Meaning |
|---|---|---|
| `RPC_PORT` | `8080` | HTTP/WebSocket port |
| `RPC_PROFILE` | `gameboy` | Controller profile loaded at startup |
| `RPC_SESSION_TIMEOUT` | `900` | Seconds of silence before a session is dropped + buttons released |
| `RPC_FORCE_MOCK` | unset | Force the mock driver even on Linux |
| `RPC_WRITE_AUTOCONFIG` | `1` | Write the RetroArch autoconfig on startup |
| `RPC_AUTOCONFIG_DIR` | `/opt/retropie/configs/all/retroarch-joypads` | Where to write the autoconfig |
| `RPC_LOG_LEVEL` | `INFO` | Log level |

---

## Managing the service

```bash
sudo systemctl status iphone-controller     # state
sudo systemctl restart iphone-controller    # restart (recreates the gamepad)
sudo systemctl stop iphone-controller        # stop
sudo systemctl disable iphone-controller     # don't start on boot
sudo journalctl -u iphone-controller -f      # follow logs
```

To update after changing code: re-`rsync` from the Mac, then
`sudo systemctl restart iphone-controller` (or re-run `./scripts/install.sh`).
