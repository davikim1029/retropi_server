# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository status

The **MVP is implemented**: Game Boy profile, full touch → WebSocket → virtual gamepad path,
auto-reconnect, QR discovery, and `/health`. The design spec
(`iPhone_RetroPie_Controller_Production_Design.md`, the "PEDD") remains the source of truth for
the broader vision; keep it in sync when design decisions change.

**Deferred (not yet built):** the security model (pairing token, origin validation, rate
limiting — PEDD §10), NES/SNES profiles, and load tests. The code is structured so these layer on
without rework.

Layout (`backend/` mirrors PEDD §21):

```
app.py                      # entrypoint (python3 app.py / systemd)
backend/ api/ sessions/ input/ profiles/ discovery/ system/  config.py  server.py
frontend/ index.html controller.css controller.js
tests/  systemd/
pyproject.toml  uv.lock
```

## What is being built

A browser-based virtual gamepad that turns an iPhone into a low-latency controller for RetroPie
on a Raspberry Pi (3B+/4/5). **Constraint that shapes every decision: no native iOS app** — the
controller runs entirely in mobile Safari and talks to the Pi over WebSocket. There is no build
step on the client; the frontend is plain `index.html` / `controller.css` / `controller.js`.

## Architecture

The input pipeline is a one-way flow; understanding it requires reading several components
together, because each stage exists to protect the stage below it from inconsistent state:

```
iPhone Safari UI ──WebSocket──> FastAPI gateway ──> Session mgmt ──> Input State Engine ──> python-uinput device ──> RetroPie/RetroArch
```

- **Frontend (Safari)** — Renders the controller layout, tracks **active touches** (not click
  events), and sends *delta* state updates. Multi-touch is mandatory: chords like `Up+Right+A`
  must work, so the client maintains a set of pressed buttons and diffs it on every touch
  start/end. Handles its own reconnection.
- **FastAPI + Uvicorn gateway** (`backend/server.py`, `backend/api/ws.py`) — Serves the static
  frontend, accepts WebSocket sessions, dispatches button events. The app's **lifespan** opens the
  gamepad driver on startup and closes it on shutdown (the "recreate on restart" behavior). Static
  files mount at `/` *after* `/ws` and `/health` are registered, so the catch-all mount doesn't
  shadow them. (Auth/origin/rate-limit are deferred — see Repository status.)
- **Input State Engine** (`backend/input/state.py`) — The correctness core. It holds the
  authoritative per-button boolean state and guarantees **last-write-wins per button**: releasing
  one button must never clear another that is still held (e.g. `RIGHT down, A down, RIGHT up` ⇒ `A`
  stays pressed). The most-tested component; it's what prevents stuck-button bugs.
- **Gamepad driver** (`backend/input/driver.py`) — A `GamepadDriver` ABC with two backends chosen
  at runtime by `create_driver()`: `uinput_driver.py` (real Linux device on the Pi) and
  `mock_driver.py` (records emits; used on macOS, in tests, or via `RPC_FORCE_MOCK`). **Develop the
  whole stack on the Mac via the mock; uinput is Linux-only.** Shared diff logic lives in
  `BaseGamepadDriver`: logical state → *channels* (`("key", CODE)` 0/1, `("hat", AXIS)` resolved so
  opposing presses cancel to 0), emitting only what changed. The real device is named exactly
  `"iPhone Virtual Gamepad"` (`DEVICE_NAME`) — a hard contract with RetroPie/udev autoconfig.

### Controller profiles

Button sets are **loaded from YAML** (`backend/profiles/*.yaml`, parsed/validated by `loader.py`).
Only `gameboy.yaml` exists today; new consoles are new YAML files, not new code. Each button maps
to a uinput event: `type: key` (full constant name, e.g. `BTN_SOUTH`) or `type: hat` (short axis,
e.g. `HAT0X`, with `value: -1/1`). The MVP runs **one** startup-selected virtual gamepad
(`RPC_PROFILE`, default `gameboy`); multi-pad is future work.

A profile may also declare a `hotkeys:` mapping (action → button name) for RetroArch hotkeys.
`gameboy.yaml` wires `enable` + `exit` both to a dedicated `EXIT` button (uinput `BTN_MODE`) so a
a press quits the game back to EmulationStation. `EXIT` has a non-retropad name, so autoconfig
does **not** emit it as a game bind (only names in `RETROPAD_BTN_FIELDS` become `input_<x>_btn`);
it acts purely as a hotkey. The frontend has a matching top-right `EXIT` button, but — like
`REBOOT` — it is **not** a `data-button`: a two-tap confirm dialog gates it, and on confirm the
client sends a *momentary* `EXIT` press (`button_down`, then `button_up` ~250 ms later) so the
hotkey registers across a RetroArch poll frame. Same-button enable+exit is deliberate: RetroPie's global `retroarch.cfg`
defines an enable-hotkey that would otherwise gate joypad hotkeys off, so pointing both at one
button satisfies the gate while keeping exit a single press. `gameboy.yaml` also declares `L`/`R`
shoulder buttons (`BTN_TL`/`BTN_TR`) — inert on real GB cores but real RetroPad binds (`input_l_btn`
/`input_r_btn`), present for SNES-style profiles and menu use, with matching top-corner UI buttons.

A **REBOOT** button (top of the frontend, `id="reboot-btn"`, *not* a `data-button`) power-cycles the
Pi. It is **not** gamepad input: a two-tap confirm dialog in the UI sends a WebSocket
`{"type":"system","action":"reboot"}`, which `backend/system/control.py` turns into
`sudo -n systemctl reboot`. `request_reboot()` is guarded so it only fires on a real Pi
(`settings.allow_reboot` on, Linux, not mock) — inert on the Mac / in tests / under `RPC_FORCE_MOCK`.
The service runs non-root, so `install.sh` writes a narrow `/etc/sudoers.d` NOPASSWD rule scoped to
exactly `systemctl reboot`. Note: auth is still deferred, so any LAN device can trigger it; disable
with `RPC_ALLOW_REBOOT=0` until pairing lands.

### RetroArch autoconfig (PEDD §14)

`backend/profiles/autoconfig.py` derives a `<device>.cfg` from the profile so RetroPie recognizes
the pad without manual mapping. The server writes it on startup into `RPC_AUTOCONFIG_DIR` (default
RetroPie's `/opt/retropie/configs/all/retroarch-joypads`), skipping gracefully when the dir is
absent (e.g. on the Mac). Button indices replicate RetroArch's **udev** ordering (ascending evdev
code via `BTN_CODES`); the d-pad hat maps to `h0<dir>`. `scripts/generate_autoconfig.py` prints or
installs it by hand. **Adding a profile with a new `BTN_*` code requires adding that code to
`BTN_CODES`**, or autoconfig generation raises.

### EmulationStation input (es_input.cfg)

The autoconfig above covers *in-game* input; EmulationStation (the launcher) reads its own
`es_input.cfg` to navigate menus with a pad. `backend/profiles/es_input.py` derives a joystick
`<inputConfig>` from the profile (reusing autoconfig's `button_index` ordering; hats use SDL
bitmask up=1/right=2/down=4/left=8) and **merges** it into an existing `es_input.cfg` without
disturbing the keyboard entry (idempotent — replaces any prior entry for our device, never
duplicates). ES matches the pad by SDL2 GUID; our uinput device has no USB vendor/product, so SDL
derives the GUID from bus+name, making `ES_DEVICE_GUID` stable for our fixed device name (captured
from the Pi; override with `--guid`). Unlike autoconfig, this is **not** written by the server
(ES owns the file and only reads it at launch) — `scripts/generate_es_input.py` does it, run by
`install.sh` against the standard ES config paths.

### WebSocket protocol (v1.0)

The client/server contract is small and message-typed — keep these shapes stable:

- Client → `{"type":"hello","protocol":"1.0","controller":"gameboy"}`
- Server → `{"type":"accepted","session_id":"<uuid>"}`
- Client → `{"type":"button_down","button":"A","timestamp":...}` / `{"type":"button_up",...}`
- Client → `{"type":"heartbeat"}` every **2 s**
- Client → `{"type":"system","action":"reboot"}` (REBOOT button, after the confirm dialog)

## Cross-cutting requirements (treat as acceptance gates)

- **Latency**: target < 20 ms, hard max < 50 ms input-to-uinput. Favor delta updates and avoid
  per-event allocation/logging on the hot path.
- **Fail-safe input**: any disconnect (Wi-Fi loss, browser crash, 15-min session timeout) must
  **immediately release all buttons**. On server restart, recreate the gamepad and restore the
  active profile.
- **Headless / auto-config**: runs as a `systemd` service (`systemd/iphone-controller.service`,
  `User=dkim`, `Restart=always`). Startup logs the LAN IP + `<hostname>.local` URLs and prints a
  scannable QR. Health is exposed at `GET /health`.
- **Resource budget**: < 100 MB RSS, < 5% CPU on a Pi 4.

Config is env-overridable via `backend/config.py` (`RPC_PORT` default 8080, `RPC_PROFILE`,
`RPC_SESSION_TIMEOUT`, `RPC_FORCE_MOCK`, `RPC_LOG_LEVEL`, `RPC_WRITE_AUTOCONFIG`,
`RPC_AUTOCONFIG_DIR`, `RPC_ALLOW_REBOOT` default on).

## Commands

**Local dev (Mac, mock driver):** deps are managed by **uv** (`pyproject.toml` + `uv.lock`).
```bash
uv sync                            # builds .venv from the lock (incl. dev group: pytest, httpx)
uv run app.py                      # serves on :8080 (RPC_PORT to change), prints QR
uv run pytest -q                   # full suite (forces mock via tests/conftest.py)
uv run pytest tests/test_input_state.py::test_last_write_wins_per_button  # single test
```

**Deploy/install on the Pi** (`ssh dkim@raspberrypi`, real uinput):
```bash
rsync -av --exclude .venv --exclude __pycache__ ./ dkim@raspberrypi:~/retropi_server/
# then on the Pi — one command does everything (apt deps, uinput module+perms, uv +
# venv via `uv sync`, systemd service, RetroArch autoconfig, firewall):
cd ~/retropi_server && ./scripts/install.sh        # self-sudos; idempotent
# overrides: RPC_USER, RPC_PORT, RPC_PROFILE, RPC_AUTOCONFIG_DIR
sudo journalctl -u iphone-controller -f             # logs incl. the connect QR
grep -A5 "iPhone Virtual Gamepad" /proc/bus/input/devices   # verify the device (or `evtest`)
```
`scripts/install.sh` (PEDD §15) is the supported path; `systemd/iphone-controller.service` is a
reference for manual installs. Dependencies live in `pyproject.toml`, pinned by `uv.lock`;
`python-uinput` (Linux-only) is platform-gated with `; sys_platform == 'linux'`, so `uv sync`
skips it on the Mac and builds it only on the Pi (needs `python3-dev` + `libudev-dev` +
`build-essential`). The installer fetches `uv` to `/usr/local/bin` and runs `uv sync --frozen
--no-dev`; the service runs `uv run --no-sync app.py`. **Python is pinned to 3.12 via
`.python-version`** — the code uses 3.10+ runtime syntax (PEP 604 `X | Y` unions in
`profiles/loader.py`), so on an older Pi (Bullseye ships 3.9) `uv` transparently downloads a
managed CPython 3.12 and builds `python-uinput` against it. If the `python-uinput` build fails,
`python-evdev`'s `UInput` could back an alternative driver behind the same `GamepadDriver` ABC
(not yet written).
