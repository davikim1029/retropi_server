# Project Resume / Session Handoff

> **Purpose:** This file is a context handoff. If you're a fresh Claude Code session, read this
> plus `CLAUDE.md` (operating guidance) and `docs/SETUP.md` (runbook) to get fully up to speed,
> then continue from **Backlog / next steps** below. The original spec is
> `iPhone_RetroPie_Controller_Production_Design.md` (the "PEDD").

_Last updated: 2026-06-06._

---

## What this project is

A browser-based virtual game controller: an **iPhone running mobile Safari** becomes a low-latency
gamepad for **RetroPie** on a Raspberry Pi. **Hard constraint: no native iOS app** — everything is
a web page talking to the Pi over WebSocket. The Pi exposes a kernel virtual gamepad (via
`python-uinput`) that RetroArch sees as a normal pad.

Flow: `iPhone Safari → WebSocket → FastAPI → InputStateEngine → GamepadDriver (uinput) → RetroArch`

---

## Status snapshot

**Built and working (MVP + autoconfig + installer):**

- Full touch → WebSocket → virtual gamepad path, Game Boy profile.
- Auto-reconnect, 2s heartbeat, QR/LAN discovery, `/health`.
- Driver abstraction: **mock** (macOS/tests) + **uinput** (Pi), chosen at runtime.
- RetroArch autoconfig generation (auto-written on startup + CLI).
- EmulationStation joystick mapping: `es_input.py` merges a `<inputConfig type="joystick">` into
  `es_input.cfg` (idempotent, preserves the keyboard entry) so the pad drives the launcher menus.
- Exit-to-EmulationStation: `EXIT` button (uinput `BTN_MODE`) wired in `gameboy.yaml` `hotkeys:`
  as both `enable` + `exit`. The UI EXIT button is **confirm-gated** (two-tap dialog, like REBOOT)
  and on confirm sends a momentary EXIT press (`button_down`/`button_up` ~250ms) so the hotkey fires.
  (Renamed from `MENU`, confirm dialog added 2026-06-06.)
- `L`/`R` shoulder buttons (`BTN_TL`/`BTN_TR`) in `gameboy.yaml` + top-corner UI buttons (added
  2026-06-06). Inert on real GB cores but real RetroPad binds; flow through autoconfig/es_input.
- REBOOT button (2026-06-06): UI two-tap confirm → WS `{"type":"system","action":"reboot"}` →
  `backend/system/control.py` runs `sudo -n systemctl reboot`. Guarded to a real Pi only (no-op on
  Mac/mock/`RPC_ALLOW_REBOOT=0`); `install.sh` writes a narrow `/etc/sudoers.d` NOPASSWD rule.
- One-shot Pi installer (`scripts/install.sh`): now also apt-installs `joystick`/`jstest` + `evtest`,
  merges the ES joystick mapping into `es_input.cfg`, and grants the reboot sudoers rule.
- 30 passing tests on the Mac (mock driver).

**Verified locally on the Mac:** `pytest` (30/30 on uv-managed 3.12), server boot, `/health`,
static asset serving, QR render, autoconfig file written to a target dir on startup, es_input merge
into a sample `es_input.cfg`. The generated autoconfig + es_input joystick block match the
known-good files captured from the Pi (button ids a=0/b=1, hat bitmask, GUID); after adding L/R the
indices shifted to a=0/b=1/l=2/r=3/select=4/start=5, EXIT(BTN_MODE) hotkey=6 — all derived, regenerated
on startup. **Not yet retested on the Pi** (EXIT rename + L/R + reboot need a redeploy).

**Verified end-to-end on the Pi (2026-06-03):** installer ran clean via SSH (passwordless sudo);
uv fetched managed CPython 3.12.13, compiled `python-uinput` against it; the systemd service is
**active and stable** (`/health` → `"driver":"uinput"`, uptime climbing, NRestarts reset to 0);
the **`iPhone Virtual Gamepad`** device exists (`event1 js0`); the RetroArch `.cfg` was written with
the correct byte-for-byte device name and Game Boy mapping. RSS ≈ 75 MB (uv parent ~24 MB +
python ~51 MB), under the 100 MB budget. **iPhone hardware confirmed (2026-06-04):** multi-touch
chords work; A/B reach the device in order (`A=BTN_SOUTH/idx0`, `B=BTN_EAST/idx1`).

**Appliance auto-boot staged (2026-06-04, pending the user's reboot test):** the Pi was a
RetroPie-Setup-over-Raspberry-Pi-OS-Desktop box booting to lightdm. Configured it to boot straight
into EmulationStation: `systemctl set-default multi-user.target` (prev `graphical.target` saved to
`~/.appliance-prev-target.txt`), and a new `~/.bash_profile` launches `emulationstation` only on
tty1 (guarded by `[ -z "$SSH_CONNECTION" ]` so SSH never spawns ES). tty1 already autologins `dkim`.
RetroPie-Setup does NOT create the `.bash_profile` hook (it ships in the RetroPie image, absent
here), so it was written by hand. **Untested:** that ES actually renders on the TV after reboot.
(The ES pad-for-menu-nav config — `es_input.cfg`'s `<inputConfig type="joystick">` — was originally
added by hand on the Pi; it is now reproduced by `install.sh` so redeploys don't need the manual ES
"Configure Input" step.) Revert to desktop: `sudo systemctl set-default graphical.target &&
rm ~/.bash_profile && sudo reboot`.

---

## What's been built (file map)

```
app.py                              # entrypoint: python3 app.py (uvicorn factory)
backend/
  config.py                         # env-overridable settings (RPC_* vars)
  server.py                         # FastAPI factory; lifespan opens/closes driver, writes autoconfig,
                                     #   starts session reaper, /health, static mount AFTER /ws
  api/ws.py                         # WebSocket protocol (hello/accepted, button_down/up, heartbeat, system)
  input/
    state.py                        # InputStateEngine — last-write-wins per button (correctness core)
    driver.py                       # GamepadDriver ABC + BaseGamepadDriver + create_driver() + channels
    mock_driver.py                  # records emits (Mac/tests)
    uinput_driver.py                # real Linux device "iPhone Virtual Gamepad"
  profiles/
    loader.py                       # YAML profile parse/validate (no uinput dep); parses hotkeys
    gameboy.yaml                    # the one profile so far (+ L/R shoulders, EXIT button & exit hotkey)
    autoconfig.py                   # profile -> RetroArch udev .cfg; write_autoconfig(); hotkeys
    es_input.py                     # profile -> EmulationStation joystick <inputConfig>; merge_es_input()
  sessions/manager.py               # sessions, inactivity reaper, fail-safe release_all
  discovery/network.py              # LAN IP + ASCII QR
  system/control.py                 # request_reboot() — guarded `sudo -n systemctl reboot` (Pi only)
frontend/
  index.html / controller.css / controller.js   # multi-touch pad (+ L/R/EXIT/REBOOT), deltas, reconnect
scripts/
  install.sh                        # one-shot Pi installer (PEDD §15); apt jstest/evtest + es_input merge
  generate_autoconfig.py            # CLI to print/install the RetroArch autoconfig
  generate_es_input.py              # CLI to print/merge the ES joystick mapping
systemd/iphone-controller.service   # reference unit (installer generates the real one)
tests/                              # test_input_state, test_profiles, test_driver_mock, test_websocket,
                                     #   test_autoconfig, test_es_input  (25 tests)
docs/SETUP.md                       # the runbook
pyproject.toml                      # deps (uv-managed); python-uinput platform-gated to Linux
uv.lock                             # pinned, reproducible resolution (commit it)
.python-version                     # pins Python 3.12 (code uses 3.10+ syntax; Pi system is 3.9)
pytest.ini  .gitignore  CLAUDE.md   resume.md (this file)
```

---

## Key design decisions & invariants (don't break these)

- **Last-write-wins per button** (`input/state.py`): pressing/releasing one button never disturbs
  another. `RIGHT↓ A↓ RIGHT↑ ⇒ A still down`. This is what prevents stuck-button bugs; it's the
  most-tested logic.
- **Driver abstraction** (`input/driver.py`): logical button state → low-level *channels*
  `("key", CODE)` (0/1) and `("hat", AXIS)` (resolved so opposing presses cancel to 0). The base
  class diffs and emits only changes. Two backends, picked by `create_driver()` (Linux+uinput vs
  mock). **Develop everything on the Mac via the mock.**
- **Device name `"iPhone Virtual Gamepad"`** (`DEVICE_NAME` in `driver.py`) is a hard contract: the
  RetroArch autoconfig filename + `input_device` line must match it byte-for-byte.
- **Profiles are declarative YAML.** New consoles = new YAML files, not new code. Each button is
  `type: key` (full `BTN_*` constant) or `type: hat` (`HAT0X/Y`, `value: -1/1`).
- **Autoconfig button numbering** (`profiles/autoconfig.py`) replicates RetroArch's udev driver:
  ascending evdev code (via `BTN_CODES`). A new profile using a new `BTN_*` must add it to
  `BTN_CODES` or generation raises. **Unverified assumption** — may need a tweak after `jstest` on
  the Pi if A/B come out swapped.
- **Fail-safe:** any disconnect / session timeout / shutdown releases all buttons.
- **Static mount ordering:** `/ws` and `/health` are registered before `StaticFiles` mounts at
  `/`, or the catch-all would shadow them.

---

## Environment & access

- **Dev machine:** macOS (darwin). Repo at `/Users/daviskim/Documents/GitHub/retropi_server`.
  Deps via **uv** (`uv sync` builds `.venv`). Python is pinned to **3.12** via `.python-version`
  (uv-managed; system `python3` is 3.14.x but unused for the project). Not a git repo yet.
- **Target Pi:** `ssh dkim@raspberrypi` (**key auth + passwordless sudo** — installer runs
  non-interactively over SSH), user **`dkim`**, hostname `raspberrypi.local`. OS is **Raspberry Pi
  OS Bullseye, aarch64, system Python 3.9.2** — too old for the code's 3.10+ syntax, so uv fetches
  a **managed CPython 3.12** at install. Service runs as `dkim`. Default port **8080**.
  Repo lives at `~/GitHub/retropi_server/retropi_server/` (note the doubled dir).
- **RetroPie joypad dir (default):** `/opt/retropie/configs/all/retroarch-joypads`.
- Deploy via `rsync -av --exclude .venv --exclude __pycache__ --exclude .git ./ dkim@raspberrypi:~/GitHub/retropi_server/retropi_server/`,
  then `ssh dkim@raspberrypi 'cd ~/GitHub/retropi_server/retropi_server && ./scripts/install.sh'`.

---

## Decisions the user made along the way

- Scope: **MVP first** (defer security, extra profiles, load tests). ✅ done, then added autoconfig
  + installer on request.
- Environment: dev on Mac, **deploy/test on a real Pi**. Build the mock + uinput abstraction.
- Tooling: **uv** (`pyproject.toml` + `uv.lock`). Installer fetches uv to `/usr/local/bin`, runs
  `uv sync --frozen --no-dev`; the service runs `uv run --no-sync app.py` (user chose this over a
  direct `.venv/bin/python` ExecStart despite the ~24 MB resident uv parent). Switched from
  venv+pip on 2026-06-03 after a stale macOS `.venv` broke `python3 -m venv` on the Pi.
- Python **pinned to 3.12** via `.python-version` (rather than rewriting the 3.10+ `X | Y` unions
  in `loader.py` to be 3.9-safe). 3.12 chosen over 3.13/3.14 for full aarch64 wheel coverage.
- Pi validation: **done by Claude this session** over SSH (passwordless sudo) — install + service
  + `/health` + device all confirmed.

---

## Backlog / next steps (pick up here)

1. **Appliance boot + new input features — confirm on the Pi (redeploy needed):** auto-boot to
   EmulationStation is staged (see Status snapshot). Ask the user how the reboot went: did ES appear
   on the TV? The ES pad-menu mapping (`es_input.cfg` joystick), the jstest/evtest install, the
   EXIT exit-hotkey, the new **L/R shoulders**, and the **REBOOT button** are now **in code**
   (2026-06-06) but need a redeploy to land on the Pi: `rsync` + `./scripts/install.sh`, then
   **restart EmulationStation** (it reads `es_input.cfg` at launch) and relaunch a game to test
   EXIT→quit. The exit hotkey uses same-button enable+exit (`BTN_MODE`, now **index 6** after L/R
   shifted the numbering) because RetroPie's global `retroarch.cfg` has `input_enable_hotkey = "num1"`
   with no joypad enable btn — verified by reading the Pi's config a prior session. If EXIT doesn't
   quit, fallback is a Select+Start combo. **Test the REBOOT button on the Pi**: two-tap confirm →
   the Pi should power-cycle; verify `install.sh` wrote `/etc/sudoers.d/iphone-controller-reboot`
   and `sudo -n systemctl reboot` works as `dkim`. New autoconfig indices: a=0/b=1/l=2/r=3/select=4/
   start=5. Multi-touch and A/B order already confirmed on hardware.
2. **NES / SNES profiles** — new YAML files. SNES adds X/Y/L/R → needs `BTN_NORTH`/`BTN_WEST`/
   `BTN_TL`/`BTN_TR` (already present in `BTN_CODES`). Decide how the client selects a profile
   (currently startup-fixed via `RPC_PROFILE`; the `hello.controller` field is accepted but the
   loaded profile wins).
3. **Security model (PEDD §10)** — pairing token, `Origin` validation, rate limiting. Touches
   `api/ws.py` + `server.py`; awkward to retrofit, so likely the next substantial piece.
4. **`python-evdev` fallback driver** — only if `python-uinput` won't build on the Pi's Python.
   Implement behind the existing `GamepadDriver` ABC.
5. **Multi-pad / landscape layouts / analog** — PEDD Phase 2+; future.

---

## How to run & test (quick reference)

```bash
# Mac (mock)
uv sync                                # builds .venv from uv.lock (+ dev group)
uv run pytest -q                       # 25 tests
uv run app.py                          # http://localhost:8080

# Pi (real)
rsync -av --exclude .venv ./ dkim@raspberrypi:~/retropi_server/
ssh dkim@raspberrypi 'cd ~/retropi_server && ./scripts/install.sh'
```

Full details: `docs/SETUP.md`. Operating guidance for Claude: `CLAUDE.md`.
