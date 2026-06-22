# Phase 0 spike — jsmpeg transport (throwaway)

Goal: prove the **low-latency video path with no extra Pi binary** before building
the real launcher. Path under test:

```
RetroArch (KMS->HDMI, FFmpeg record)  ──mpeg1/mp2 in mpegts──>  FIFO
        └─ also still shows on the TV                              │
                                                                   ▼
                              spike/relay.py (FastAPI WS, project venv)
                                                                   │ binary WS
                                                                   ▼
                                  jsmpeg in mobile Safari  (spike/index.html)
```

This is a **dead end for committing** — it validates the transport, then we build
the production version per the plan. If latency here is unacceptable, the fallback
is HW H.264 (`h264_v4l2m2m`) + MediaMTX/WebRTC (needs the binary install we deferred).

## What's already verified (read-only, this session)
- RetroArch 1.16 records non-interactively from the CLI: `-r <FILE> --recordconfig <cfg>`.
- ffmpeg 4.3 on the Pi has `mpeg1video` (jsmpeg's codec) + HW `h264_v4l2m2m`/`h264_omx`.
- `video_gpu_record=false` (default) records the core's clean frame — sidesteps VC4 tiling.

## Prerequisites (do these first)
1. **Fix the PSU.** The Pi logs `Undervoltage detected!` — real-time encode/Wi-Fi will
   throttle and any latency number is meaningless until it's on a 5V/2.5A+ supply.
2. Deploy this `spike/` dir to the Pi (it rides along with the normal rsync).
3. Pick a small GBA ROM, e.g. `~/RetroPie/roms/gba/<Game>.gba`.

## Run it
All from your Mac over SSH unless noted.

```bash
# 1) Point tty1 at the spike runner instead of EmulationStation (reversible).
ssh dkim@raspberrypi 'cd ~/retropi_server && \
  bash spike/tty1.sh enable /home/dkim/RetroPie/roms/gba/<Game>.gba gba'
ssh dkim@raspberrypi 'sudo reboot'      # tty1 boots into RetroArch + recording

# 2) After it boots: start the relay (serves the jsmpeg page + WS).
ssh dkim@raspberrypi 'cd ~/retropi_server && uv run --no-sync spike/relay.py'
```

Then:
- **On the TV:** confirm the game is running on HDMI (the spike runner launched it).
- **On the phone:** open `http://raspberrypi.local:8090/` (or the Pi's LAN IP:8090).
  You should see the game in the canvas with a live fps readout.
- **Measure latency:** easiest is to point the phone's camera... no — open a stopwatch
  app on the TV via the game, or press a button and eyeball TV-vs-phone delay. A rough
  "feels playable / clearly laggy" judgment is enough for the gate.

## Restore EmulationStation
```bash
ssh dkim@raspberrypi 'cd ~/retropi_server && bash spike/tty1.sh restore && sudo reboot'
```

## Gate (decide before building the real thing)
- [ ] Game shows on HDMI **and** streams to the phone simultaneously.
- [ ] jsmpeg decodes it (fps readout > 0, recognizable image — not tiled/garbled).
- [ ] Latency feels acceptable for casual GB/GBA play (rough eyeball ok).
- [ ] Quitting RetroArch (EXIT / `BTN_MODE` hotkey) returns cleanly to the tty1 shell.

If all pass → proceed to Phase 1 (launcher backend). If jsmpeg latency disappoints →
revisit MediaMTX/WebRTC (authorize the binary) reusing the HW H.264 encoder.

## Files
- `record_mpeg1.cfg` — RetroArch FFmpeg record-core config (mpeg1video + mp2, mpegts).
- `spike-runner.sh` — runs on tty1 in place of ES; launches the game with recording.
- `tty1.sh` — reversibly swaps tty1 autologin between ES and the runner.
- `relay.py` — FastAPI WS relay: FIFO → browser (newest-wins per client).
- `index.html` + `jsmpeg.min.js` — the browser player.
