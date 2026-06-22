#!/usr/bin/env bash
# Phase 0 spike runner — runs ON tty1, temporarily in place of EmulationStation,
# so RetroArch becomes DRM master on the active VT exactly the way ES does today.
# (A systemd service has no VT and can't reliably grab the display — this mirrors
# the real "tty1 launcher-runner" from the plan.)
#
# It launches ONE game with RetroArch's FFmpeg recording writing MPEG-1/TS to a
# FIFO (which spike/relay.py serves to jsmpeg), then drops to a shell on exit so
# you can re-run or restore ES.
#
# Driven by env vars (set them in the ~/.bash_profile swap — see spike/README.md):
#   RPC_SPIKE_SYS    gba | gbc            (default gba)
#   RPC_SPIKE_ROM    absolute ROM path    (required)
#   RPC_SPIKE_FIFO   FIFO path            (default /tmp/rpc_spike.ts)
#   RPC_SPIKE_RECCFG record config path   (default ~/retropi_server/spike/record_mpeg1.cfg)
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SYS="${RPC_SPIKE_SYS:-gba}"
ROM="${RPC_SPIKE_ROM:?set RPC_SPIKE_ROM=/home/dkim/RetroPie/roms/gba/<Game>.gba}"
FIFO="${RPC_SPIKE_FIFO:-/tmp/rpc_spike.ts}"            # mpeg1/ts OUT (relay reads)
FIFO_RAW="${RPC_SPIKE_FIFO_RAW:-/tmp/rpc_raw.nut}"    # MJPEG/nut from RetroArch
RECCFG="${RPC_SPIKE_RECCFG:-$SCRIPT_DIR/record_raw.cfg}"
EMUCFG="/opt/retropie/configs/$SYS/emulators.cfg"

[ -p "$FIFO" ] || mkfifo "$FIFO"
[ -p "$FIFO_RAW" ] || mkfifo "$FIFO_RAW"

# Resolve the default emulator command template from emulators.cfg:
#   default = "lr-mgba"
#   lr-mgba = "/opt/.../retroarch -L <core> --config <cfg> %ROM%"
DEFAULT=$(sed -nE 's/^default = "?([^"]+)"?.*/\1/p' "$EMUCFG")
TEMPLATE=$(sed -nE "s/^${DEFAULT} = \"(.*)\"\$/\1/p" "$EMUCFG")
if [ -z "${TEMPLATE:-}" ]; then
  echo "[spike-runner] could not resolve emulator command from $EMUCFG" >&2
  exec bash -i
fi

# Ensure the WS relay (the FIFO *reader*) is up BEFORE RetroArch opens the FIFO
# for writing — otherwise RetroArch's record open blocks waiting for a reader.
if ! ss -ltn 2>/dev/null | grep -q ":8090"; then
  echo "[spike-runner] starting relay (FIFO reader) on :8090"
  ( cd "$SCRIPT_DIR/.." && nohup uv run --no-sync spike/relay.py \
      >/tmp/spike_relay.log 2>&1 </dev/null & )
  sleep 4
fi

# Word-split the template (trusted, root-managed cfg) with %ROM% substituted.
# shellcheck disable=SC2086
eval "set -- ${TEMPLATE//%ROM%/\"$ROM\"}"

LOG="/tmp/spike_retroarch.log"
STOP="/tmp/rpc_spike_stop"
rm -f "$STOP"

# Relaunch loop: lets me iterate the record config without rebooting. Kill
# retroarch (SIGTERM) and the loop relaunches with whatever record_mpeg1.cfg
# was just rsynced. `touch /tmp/rpc_spike_stop` then kill = stop for good.
# --verbose captures the FFmpeg record-core init (incl. failures) into $LOG.
# Per-session pipeline: RetroArch records MJPEG/nut to FIFO_RAW (MJPEG has no fps
# restriction, unlike mpeg1video); this ffmpeg transcodes it to MPEG-1/TS at a
# forced 60fps into FIFO, which the relay serves to jsmpeg. The transcode is
# started fresh each loop and killed when RetroArch exits.
while true; do
  echo "[spike-runner] launching (log: $LOG): $* -r $FIFO_RAW --recordconfig $RECCFG"
  # transcode.sh is re-read each iteration, so it can be edited without a reboot.
  bash "$SCRIPT_DIR/transcode.sh" "$FIFO_RAW" "$FIFO" >/tmp/spike_transcode.log 2>&1 &
  TC=$!
  "$@" -r "$FIFO_RAW" --recordconfig "$RECCFG" --verbose >"$LOG" 2>&1
  echo "[spike-runner] retroarch exited rc=$? at $(date)" | tee -a "$LOG"
  kill "$TC" 2>/dev/null
  [ -f "$STOP" ] && { echo "[spike-runner] stop flag set; leaving loop"; break; }
  sleep 2
done

echo "[spike-runner] Dropping to a shell on tty1."
echo "[spike-runner] Restore ES: bash $SCRIPT_DIR/tty1.sh restore && sudo reboot"
exec bash -i
