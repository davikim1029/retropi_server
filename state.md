# Project Resume / Session Handoff

> **Purpose:** This file is a context handoff. If you're a fresh Claude Code session, read this
> plus `CLAUDE.md` (operating guidance) and `docs/SETUP.md` (runbook) to get fully up to speed,
> then continue from **Backlog / next steps** below. The original spec is
> `iPhone_RetroPie_Controller_Production_Design.md` (the "PEDD").

_Last updated: 2026-08-18._

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
- **`gamepad.local` mDNS alias (2026-06-09, not yet hardware-tested):** the startup URL list
  (`backend/discovery/network.py`) advertises `http://gamepad.local:8080` alongside the IP and
  `<hostname>.local`, but that name only *resolves* because `install.sh` now installs a second
  systemd unit `gamepad-mdns-alias.service` (`systemd/gamepad-mdns-alias.service` is the reference)
  that runs `avahi-publish -a -R -f gamepad.local <lan-ip>` (needs `avahi-utils`, also apt-installed).
  The unit waits for DHCP to assign an IP then publishes it, so **reboots self-correct** the IP; a
  live IP change without a reboot needs `systemctl restart gamepad-mdns-alias`. Idempotent re-run.
  Keep the literal `gamepad.local` in `network.py` and `install.sh` in sync.
- **Stream mode (2026-06-19, mock-verified; on-Pi capture pending hardware test):** an optional
  split-screen browser layout — top half live game video, bottom half the existing pad. Opt-in
  (`RPC_VIDEO_ENABLED`, default off) and **fully decoupled from the controller**: new package
  `backend/video/` (`VideoSource` ABC + `create_source()`, `JpegStreamSplitter`, `mock_source.py`
  cycling bundled `assets/*.jpg`, `ffmpeg_source.py` supervised subprocess) + new HTTP routes
  `backend/api/video.py` (`GET /video/stream.mjpeg` multipart MJPEG, `GET /video/status`). Transport
  is **MJPEG over HTTP** rendered by a plain `<img>` (no build step). Frontend adds a 📺 toggle +
  `body.mode-stream` split layout (persisted in `localStorage`, honors `?mode=stream`); default pad
  layout unchanged. Capture defaults to `kmsgrab` (correct for the Pi's full-KMS `vc4-kms-v3d`;
  read-only scanout grab → **HDMI keeps working**); the whole ffmpeg command is overridable via
  `RPC_VIDEO_FFMPEG_CMD` for on-hardware tuning. `install.sh` gains an opt-in `setup_video` (ffmpeg +
  `setcap cap_sys_admin` for kmsgrab + `video`/`render` groups + `RPC_VIDEO_*` in the unit).
  **Verified on the Mac:** `/health` shows `"video":"mock"`, `/video/status` + `/video/stream.mjpeg`
  serve real multipart JPEG frames, served page has the toggle. **Untested on hardware:** the actual
  kmsgrab pipeline (which `/dev/dri/cardN`, the `hwdownload,format=` for VC4), and the on-iPhone split
  layout.
- 41 passing tests on the Mac (mock driver) — added `test_video_source.py` (splitter + mock) and
  `test_video_api.py` (routes + multipart stream).

**Verified locally on the Mac:** `pytest` (30/30 on uv-managed 3.12), server boot, `/health`,
static asset serving, QR render, autoconfig file written to a target dir on startup, es_input merge
into a sample `es_input.cfg`. The generated autoconfig + es_input joystick block match the
known-good files captured from the Pi (button ids a=0/b=1, hat bitmask, GUID); after adding L/R the
indices shifted to a=0/b=1/l=2/r=3/select=4/start=5, EXIT(BTN_MODE) hotkey=6 — all derived, regenerated
on startup.

**Deployed + verified on the Pi (2026-06-06):** rsync to `/home/dkim/GitHub/retropi_server` +
`./scripts/install.sh` ran clean (venv rebuilt, `python-uinput` compiled on CPython 3.12.13). Service
**active**, `/health` → `"driver":"uinput"`; `iPhone Virtual Gamepad` device present (`event1 js0`);
the on-Pi RetroArch autoconfig shows the new indices (a=0/b=1/l=2/r=3/select=4/start=5, hotkey=6);
es_input merged into both ES config paths; reboot sudoers rule
`/etc/sudoers.d/iphone-controller-reboot` written, `visudo`-validated, and `sudo -n -l` confirms
`dkim` has NOPASSWD on `/usr/bin/systemctl reboot`. **Still untested on hardware** (Claude won't
trigger them remotely): the iPhone UI layout (L/R/EXIT/REBOOT placement), EXIT→quit in a live game,
and an actual REBOOT. Reload the page on the iPhone (static files served live) and relaunch a game /
restart EmulationStation to test.

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
  api/video.py                      # GET /video/stream.mjpeg (multipart MJPEG) + /video/status (stream mode)
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
  video/                            # OPTIONAL stream mode (off by default), decoupled from input:
    source.py                       #   VideoSource ABC + create_source() + JpegStreamSplitter
    mock_source.py                  #   cycles bundled assets/*.jpg (Mac/tests/RPC_VIDEO_CAPTURE=test)
    ffmpeg_source.py                #   supervised ffmpeg capture (kmsgrab default); RPC_VIDEO_FFMPEG_CMD override
    assets/                         #   bundled placeholder JPEGs for the mock
frontend/
  index.html / controller.css / controller.js   # multi-touch pad (+ L/R/EXIT/REBOOT + 📺 stream mode), deltas, reconnect
scripts/
  install.sh                        # one-shot Pi installer (PEDD §15); apt jstest/evtest/avahi-utils,
                                     #   es_input merge, reboot sudoers, gamepad.local mDNS alias unit
  generate_autoconfig.py            # CLI to print/install the RetroArch autoconfig
  generate_es_input.py              # CLI to print/merge the ES joystick mapping
systemd/iphone-controller.service   # reference unit (installer generates the real one)
systemd/gamepad-mdns-alias.service  # reference unit: avahi-publish gamepad.local alias (installer generates it)
tests/                              # test_input_state, test_profiles, test_driver_mock, test_websocket,
                                     #   test_autoconfig, test_es_input, test_video_source, test_video_api  (41 tests)
docs/SETUP.md                       # the runbook
pyproject.toml                      # deps (uv-managed); python-uinput platform-gated to Linux
uv.lock                             # pinned, reproducible resolution (commit it)
.python-version                     # pins Python 3.12 (code uses 3.10+ syntax; Pi system is 3.9)
pytest.ini  .gitignore  CLAUDE.md   state.md (this file)
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
  (uv-managed; system `python3` is 3.14.x but unused for the project). Git repo, branch `main`.
- **Target Pi:** `ssh dkim@raspberrypi.tail571bc8.ts.net` (**key auth + passwordless sudo** —
  installer runs non-interactively over SSH), user **`dkim`**, LAN hostname `raspberrypi.local`.
  OS is **Raspberry Pi
  OS Bullseye, aarch64, system Python 3.9.2** — too old for the code's 3.10+ syntax, so uv fetches
  a **managed CPython 3.12** at install. Service runs as `dkim`. Default port **8080**.
  Repo lives at **`/home/dkim/GitHub/retropi_server`** (single dir — confirmed via the systemd
  unit's `WorkingDirectory` on 2026-06-06; the earlier "doubled dir" note was wrong).
- **RetroPie joypad dir (default):** `/opt/retropie/configs/all/retroarch-joypads`.
- Routine redeploy via `scripts/deploy.sh` from the Mac. It rsyncs to
  `dkim@raspberrypi.tail571bc8.ts.net:/home/dkim/GitHub/retropi_server`, runs
  `uv sync --frozen --no-dev` on the Pi, then restarts the installed Python services
  (`iphone-controller`, `webplay`) so new backend code is loaded.
- Fresh install / unit changes via `rsync -av --exclude .venv --exclude __pycache__ --exclude .git ./ dkim@raspberrypi.tail571bc8.ts.net:~/GitHub/retropi_server/`,
  then `ssh dkim@raspberrypi.tail571bc8.ts.net 'cd ~/GitHub/retropi_server && ./scripts/install.sh'`.

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

0e. **Enhancements (2026-06-21).**
   - **Custom ROM library scan (2026-08-18):** `webplay/scanner.py` still reads the normal RetroPie
     library from `RPC_ROMS_DIR` / `~/RetroPie/roms`, and now also scans a project-local custom library.
     Default is the sibling folder next to this repo (`../custom_games`, e.g. `~/GitHub/custom_games`
     on the Pi), with `RPC_CUSTOM_GAMES_DIR` as an override. The custom scan recurses for `.gb`, `.gbc`,
     and `.gba` files but skips any `dev/` subtree so packaged ROMs appear without duplicate build
     artifacts from source checkouts.
   - **Services auto-start:** confirmed `iphone-controller`, `mediamtx`, `webplay` all `enabled` (boot-start).
   - **GBA core → `lr-vba-next`** (lighter than mgba; Pi ~79°C/thermal edge; saves backed up to `~/gba_srm_backup_*`).
   - **Scanner name cleanup** (strips `0907 - ` catalog prefixes).
   - **play.html:** view toggle (📺 Video ↔ 🎮 TV-only, hides video + pad fills screen); dpad + A/B nudged
     up (dpad bottom 26→48px, B 32→52, A 68→88, so Select/Start don't cover Down/B).
   - **Audio is OPT-IN to protect latency (2026-06-22).** The stream carries Opus audio (AAC→Opus via
     publish.sh), but the WHEP client requests **video-only by default** — an audio track makes the browser
     add an A/V-sync/jitter buffer that noticeably raised gameplay latency (user noticed). The 🔇/🔊 button
     toggles `wantAudio` and **reconnects** the WHEP with/without the audio transceiver (sound on demand,
     latency only when on). NOTE: publish.sh dying mid-game (broken pipe) drops video until relaunch — only
     seen under rapid restart/quit/relaunch churn; stable in normal use. Hardening idea: supervise publish.sh
     in the runner, or have MediaMTX `runOnDemand` pull the FIFO.
   - **Emulator power + status (#2) DONE — launcher is the power/status hub.** Idle → game grid (tap =
     power ON); running → an "● EMULATOR ON: <game>" card with **▶ Resume** + **⏻ Power off**. Power-off =
     `POST /api/quit` → `manager.quit_game()` → RetroArch network **QUIT** (clean exit, flushes SRAM) →
     runner idle. NOTE: the webplay *service* (systemd) **can't `pkill` the tty1-session RetroArch**
     (different session — confirmed), so it uses **UDP network commands** (QUIT works; SIGTERM from the
     service does not). Whole-Pi power-on remains impossible in software (Pi 3B, no soft wake) — this is
     emulator on/off only, which is what the user wanted.
   - **SAVE STATES DON'T WORK under our launch → use in-game saves.** RetroArch reports "Core does not
     support save states" because launching directly (`-L core.so --config`, not via runcommand) doesn't
     load the **core-info DB** that declares savestate support (`core_info_current_supports_savestate()`
     returns false; both gambatte AND vba-next; setting `libretro_info_path` did NOT fix it; network
     cmd interface itself works — GET_STATUS/PAUSE_TOGGLE confirmed). The ★ save/load menu was BUILT then
     **removed** from both frontends (dead button); the backend plumbing remains dormant
     (`backend/system/control.py send_retroarch_command`, ws `save_state`/`load_state`; webplay
     `manager.send_retroarch_command`, `/api/savestate|loadstate`; `network_cmd_enable=true`,
     `savestate_directory`, `libretro_info_path` set in global retroarch.cfg). **In-game saving works**
     (SRAM→.srm) and is now robust: set `autosave_interval = "60"` (flushes every 60s, survives a
     non-clean power-off; previously flush-on-exit-only). To revive save states later: match how
     runcommand sets up core info, or launch via runcommand.

0w. **WORKING + LOW LATENCY (2026-06-21): video pivoted jsmpeg → WebRTC (MediaMTX).** User verdict:
   "looks and works amazing." The jsmpeg double-transcode (0a) was laggy *and* fragile, so the video
   layer was swapped to **WebRTC** — the launcher/runner/control work from 0a all stayed; only video changed.
   - **Pipeline:** RetroArch records **H.264** (libx264 ultrafast+zerolatency, `webplay/record_h264.cfg`
     — H.264 has no fps limit, so it encodes the GB's 59.7275fps directly, **no transcode**) → FIFO
     `/tmp/rpc_h264.ts` → `webplay/publish.sh` ffmpeg **`-c:v copy`** (+ AAC→Opus audio) → RTSP
     `rtsp://localhost:8554/game` → **MediaMTX** → **WebRTC/WHEP** → native `<video>` in `play.html`.
   - **MediaMTX**: user-local binary at `webplay/mediamtx/mediamtx` (v1.19.1 arm64, NOT a system install).
     Ports: RTSP 8554 (ingest), WebRTC 8889 (WHEP) + 8189 (ICE/UDP). Default mediamtx.yml, no auth (LAN).
   - **play.html** (WebRTC): WHEP client (`http://<host>:8889/game/whep`, video+audio transceivers),
     **🔇/🔊 mute** (starts muted for iOS autoplay — tap to unmute), **view toggle** (📺 Video ↔ 🎮 TV-only:
     hides video, pad fills screen, play on the HDMI TV), controls unchanged (`/control` → :8080 gamepad).
   - **runner.sh** rewritten: **flock singleton** guard, ensures MediaMTX + webplay (:8091), idle-loops
     on the launch FIFO, per launch starts `publish.sh` + RetroArch H.264→FIFO. `webplay/ctl.sh` start/stop.
   - **Latency reality:** WebRTC is LAN/Tailscale only (UDP) — use **`http://raspberrypi.local:8091/`** on
     WiFi for low latency. The **`:8443` funnel can't carry WebRTC media** (HTTPS/TCP only): over the funnel
     controls work but video won't (remote video = a later problem; Tailscale-app on the phone is the path).
   - **Also (2026-06-21):** scanner strips ROM catalog prefixes (`0907 - Pokemon…` → `Pokemon - Ruby Version`);
     and, as of 2026-08-18, merges packaged custom ROMs from `RPC_CUSTOM_GAMES_DIR` / `../custom_games`;
     **GBA default switched `lr-mgba` → `lr-vba-next`** (lighter; Pi 3B runs ~79°C / thermal-throttle edge under
     mGBA+encode — no overclock set, undervoltage is hardware/thermal, user improving cooling). GBA saves
     backed up to `~/gba_srm_backup_*`.
   - **APPLIANCE (2026-06-21) — stray-instance bug FIXED.** MediaMTX + webplay are now **systemd services**
     (`webplay/install-services.sh` generates `mediamtx.service` + `webplay.service`, `User=dkim`,
     `Restart=always`, enabled) alongside the existing `iphone-controller` (:8080). `runner.sh` was
     simplified to drop the ensure-MediaMTX/ensure-webplay `( cmd & )` subshells (the stray source) — it
     now only does the flock-singleton tty1 launch loop. **Verified after reboot: runner=1, webplay-py=1,
     mediamtx=1**, all `active`/`enabled`, video+audio (2 tracks) live. The tty1 hook (runner) stays
     because RetroArch needs a VT. MediaMTX logs to **journald** now (`journalctl -u mediamtx`), not
     /tmp/mediamtx.log. Vestigial: webplay `server.py` still has the unused jsmpeg `/ws`+reader_thread
     (harmless under WebRTC; clean up later).
     - **Reproducible installer (2026-06-22):** `webplay/install-services.sh` now does the whole webplay
       layer idempotently — `ensure_deps` (ffmpeg), `ensure_mediamtx` (downloads the arm64 binary if
       missing), `configure_retroarch` (`network_cmd_enable`/`network_cmd_port`/`autosave_interval` in the
       global retroarch.cfg + flips gba `lr-mgba`→`lr-vba-next` if available), `install_services` (the two
       units), and the tty1 hook. Modes: `full` (default) and `config` (deps+mediamtx+RA cfg only, safe
       while a game runs). Fresh-Pi rebuild = `./scripts/install.sh` → `bash webplay/install-services.sh`
       → reboot. The hand-`sed`'d config tweaks are now captured in code. **Docs TODO:** CLAUDE.md still
       describes the retired MJPEG stream mode (state.md is current).
     - **Still pending (enhancement): remote/off-LAN low-latency play** — WebRTC needs UDP so the HTTPS
       funnel can't carry it; the path is the Tailscale app on the phone.

0a. **WORKING (2026-06-21): `webplay/` fork — browser launcher + low-latency play, end-to-end.** [VIDEO NOW
   WEBRTC — see 0w; the jsmpeg/MJPEG transcode path below is superseded but the launcher/runner/control stand.]
   The whole stack is proven on hardware: from the phone you browse the gbc/gba library, tap a game,
   it launches on the Pi (RetroArch on tty1, HDMI + recording), and plays on the phone with live
   video + touch controls — even off-WiFi over a Tailscale funnel. Built as a **separate app** (a
   fork) on **port 8091 + funnel `https://raspberrypi.tail571bc8.ts.net:8443/`**, leaving the MVP
   controller (`backend/`, :8080) untouched as the gamepad authority (the fork proxies controls to it).
   - **Pipeline (proven):** RetroArch records **MJPEG/nut** (mpeg1video can't do the GB's 59.7275fps:
     "MPEG-1/2 does not support 262144/4389 fps") → `webplay/transcode.sh` ffmpeg → **MPEG-1/TS @ -r 60**
     → `webplay/server.py` FIFO→WS relay → **jsmpeg** in mobile Safari. Controls: `/control` WS proxy →
     `:8080` gamepad app → uinput → RetroArch (`Autoconf: iPhone Virtual Gamepad configured in port 1`).
   - **Launcher:** `webplay/scanner.py` (enumerate `~/RetroPie/roms/{gbc,gba}`, names from gamelist.xml,
     plus packaged custom ROMs from `RPC_CUSTOM_GAMES_DIR` / sibling `../custom_games`, skipping `dev/`),
     `webplay/manager.py` (POST launch → writes a request line to the `/tmp/rpc_launch` FIFO; reads
     `/tmp/rpc_state`), `webplay/server.py` API (`/api/games`, `/api/launch`, `/api/state`). The **tty1
     runner** `webplay/runner.sh` idle-loops on the launch FIFO (held `exec 3<>` so non-blocking writes
     find a reader), execs the `emulators.cfg` command, transcodes, writes state; **EXIT (BTN_MODE)**
     quits RetroArch → runner idle → play.html state-poll redirects to the launcher. 43 tests pass
     (added `tests/test_webplay_scanner.py`).
   - **Gotchas baked in (don't relearn):** ffmpeg to a FIFO needs `-y` (else it exits on the overwrite
     prompt); MPEG-TS relay must **never drop bytes** mid-stream (corrupts → colored garbage), disconnect
     slow clients instead; never `pkill -f "<name>"` inline over ssh (matches the shell's own argv) — use
     a **script file** (`webplay/ctl.sh`, `spike/devfeed.sh`, `reload.sh`) or a `[x]` regex; don't
     `pkill -x uv` (kills the :8080 service's uv too). The undervoltage was self-induced by the retired
     kmsgrab ffmpeg; with video disabled on :8080 it's fine under load (`0x50000` latched, not current).
   - **Enable/restore:** `spike/tty1.sh webplay` (point tty1 at the runner) + reboot; `spike/tty1.sh
     restore` + reboot brings ES back. `webplay/ctl.sh start|stop|restart` manages the app by hand.
   - **NOT done:** persistence/installer (runner is a manual `~/.bash_profile` swap, not a unit);
     gba names still show filename prefixes ("0171 - …") — gamelist enrichment didn't match, polish it;
     NES/SNES; on-device confirmation of EXIT→launcher. The `:8090/:10000` MJPEG spike is now superseded.

0. **PIVOT (2026-06-20): screen-capture is abandoned → browser remote-play box.** The MJPEG
   screen-capture approach (item 0 history below) is a dead end on this Pi: the VC4 scanout buffer is
   T-tiled and ffmpeg 4.3 can't de-tile it. The user's clarified goal is bigger anyway — turn the Pi
   into a **browser-driven remote-play box**: browse/launch gbc+gba games from the phone (bypassing
   EmulationStation), play with low-latency video on the phone, EXIT returns to *our* web launcher;
   the game also stays on the TV via HDMI; the existing controller-only view is preserved (reached
   *through* the launcher, video is an optional 📺 overlay). **Approved plan:**
   `~/.claude/plans/validated-frolicking-wilkinson.md` (3 pieces: web launcher + tty1 launcher-runner
   + RetroArch FFmpeg stream → transport → phone). Phased; **Phase 0 spike is a hard gate.**
   - **Transport decision: jsmpeg over WebSocket (NO extra Pi binary), not MediaMTX/WebRTC.** Reuses
     ffmpeg (already on Pi) + our FastAPI/WS + a vendored jsmpeg.min.js. MediaMTX/WebRTC (lower latency
     but needs a binary install the user/classifier deferred) stays the documented upgrade if jsmpeg
     latency disappoints; HW `h264_v4l2m2m`/`h264_omx` confirmed present for that path.
   - **De-risked read-only (this session):** RetroArch 1.16 records non-interactively via CLI
     `-r <FILE> --recordconfig <cfg> --size WxH`; ffmpeg 4.3 has `mpeg1video` (jsmpeg's codec);
     `video_gpu_record=false` records the core's clean pre-tiling frame (sidesteps tiling entirely).
   - **Built `spike/` bundle (Mac-validated: bash -n, py_compile, deps resolve):** `record_mpeg1.cfg`
     (mpeg1video+mp2/mpegts), `spike-runner.sh` (runs on tty1 in place of ES, launches a game with
     recording → FIFO), `tty1.sh` (reversibly swaps tty1 autologin ES↔runner), `relay.py` (FastAPI WS
     FIFO→browser, newest-wins), `index.html`+`jsmpeg.min.js` (player), `README.md` (runbook + gate).
   - **NEXT = hardware run (needs the user):** fix the PSU first (undervoltage), then per
     `spike/README.md`: `tty1.sh enable <rom> gba` → reboot → `uv run --no-sync spike/relay.py` →
     open `http://raspberrypi.local:8090/` on the phone; confirm game on HDMI + decoded on phone +
     acceptable latency + clean EXIT. Gate passes → build Phase 1 (launcher backend). NOTE: Phase 1
     `scanner.py` (enumerate roms/gbc+gba, names from gamelist.xml) is independent of the spike and
     Mac-testable — can be built in parallel while the hardware run waits.

   --- history (superseded screen-capture approach) ---
   **Stream mode: deployed + enabled on the Pi, but the CAPTURE IMAGE is blocked by VC4 tiling
   (2026-06-19).** All the infrastructure is validated end-to-end on the Pi; only getting a *clean*
   frame out of the GPU is unsolved. Status:
   - Deployed (HEAD `9d21727`), `install.sh RPC_VIDEO_ENABLED=1` run. Service active; `/health` →
     `"video":"ffmpeg"`; `/video/status` → `enabled/running/has_frames:true`; `/video/stream.mjpeg`
     serves valid multipart MJPEG. Controller unaffected (`driver:uinput`), HDMI unaffected.
   - **Fixed:** default `RPC_VIDEO_DRI_DEVICE` is now **`/dev/dri/card0`** (this Pi has card0 +
     renderD128, no card1 — card1 failed with "Failed to open DRM device"). A systemd drop-in on the
     Pi (`/etc/systemd/system/iphone-controller.service.d/10-video-card.conf`) currently forces card0;
     once the card0 code default is committed + redeployed, that drop-in is redundant (remove it).
   - `setcap cap_sys_admin=ep /usr/bin/ffmpeg` is set (kmsgrab needs it; the installer's setcap worked
     — earlier "no cap" was just `getcap` not on dkim's non-sudo PATH, it lives in /sbin).
   - **BLOCKER:** kmsgrab on card0 captures the right surface (ES) but the scanout buffer is
     **T-tiled** (FB reports 1920×1080 32bpp); ffmpeg 4.3's `hwdownload,format=bgr0` can't linearize
     it → output is horizontally striped/garbled (verified by pulling a frame). `fbdev /dev/fb0` is
     linear but shows only the **console** (ES draws via KMS/GBM to a separate plane), so it's not a
     viable source either. Need a de-tiling path — candidates: newer ffmpeg with VC4 DRM-PRIME
     detiling, RetroArch's built-in recording/stream via the V4L2 H.264 encoder (game-only, not ES,
     and not MJPEG so needs a player), or switching the Pi off full-KMS (invasive). **Decision pending
     from the user.**
   - **Also noticed:** the Pi console is spamming `Undervoltage detected!` — inadequate PSU; advise a
     proper 5V/2.5A+ supply (causes throttling/instability/SD corruption).
   Probed Pi facts: Pi **3B**, full KMS (`vc4-kms-v3d`), ffmpeg 4.3.9 (kmsgrab/fbdev/x11grab),
   display node `/dev/dri/card0`, fb `vc4drmfb` 1920×1080.

1. **Hardware test the new features on the iPhone + TV (DEPLOYED 2026-06-06, code is live on the
   Pi).** The redeploy is done and server-side verified (see Status snapshot); what remains is
   on-device testing the user must do:
   - **Reload the page on the iPhone** (static files are served live — no redeploy needed for
     frontend tweaks) and eyeball the layout: L/R shoulders top corners, EXIT top-right, REBOOT
     bottom-right. Adjust CSS positions if cramped.
   - **EXIT→quit:** relaunch a game, tap EXIT → confirm dialog → Exit; it should quit to ES. The
     exit hotkey is same-button enable+exit (`BTN_MODE`, now **index 6** after L/R shifted the
     numbering) because RetroPie's global `retroarch.cfg` has `input_enable_hotkey = "num1"` with no
     joypad enable btn. If EXIT doesn't quit, fallback is a Select+Start combo, or bump
     `EXIT_HOLD_MS` in `controller.js`.
   - **REBOOT:** two-tap confirm → the Pi should power-cycle (sudoers rule + `sudo -n -l` already
     verified server-side; Claude did NOT trigger an actual reboot).
   - **Menu nav with the pad:** the ES joystick mapping was merged into both `es_input.cfg` paths;
     **restart EmulationStation** (it reads the file only at launch) to pick it up.
   - **`gamepad.local` (2026-06-09, redeploy needed — installer change):** rsync + re-run
     `install.sh` so `avahi-utils` + the `gamepad-mdns-alias` unit land, then from the iPhone open
     `http://gamepad.local:8080`. Verify on the Pi with `avahi-resolve -n gamepad.local` and
     `systemctl status gamepad-mdns-alias`.
   - Also still open from before: did the appliance auto-boot to ES on the TV actually work?
   New autoconfig indices live on the Pi: a=0/b=1/l=2/r=3/select=4/start=5. Multi-touch + A/B order
   confirmed on hardware in a prior session.
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
scripts/deploy.sh
# Fresh install / unit changes:
rsync -av --exclude .venv ./ dkim@raspberrypi.tail571bc8.ts.net:~/GitHub/retropi_server/
ssh dkim@raspberrypi.tail571bc8.ts.net 'cd ~/GitHub/retropi_server && ./scripts/install.sh'
```

Full details: `docs/SETUP.md`. Operating guidance for Claude: `CLAUDE.md`.
