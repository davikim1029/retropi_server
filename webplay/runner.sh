#!/usr/bin/env bash
# tty1 runner for the webplay fork — the ONLY piece that must run on tty1 (so
# RetroArch's KMS driver can be DRM master, like EmulationStation).
#
# MediaMTX (WebRTC relay) and the webplay app (:8091) are systemd services now
# (webplay/install-services.sh), so this runner no longer starts them — it just:
#   1. SINGLETON via flock (a double tty1 hook can't double-launch)
#   2. idle-loops on a launch-request FIFO the launcher writes to
#   3. per request, execs the emulators.cfg command on tty1 recording H.264 to a
#      FIFO, which publish.sh remuxes (-c copy) to RTSP -> MediaMTX -> WebRTC
#   4. EXIT (BTN_MODE) quits RetroArch -> back to idle (launcher reappears)
#
# Removing the old ensure-MediaMTX/ensure-webplay subshells is what fixed the
# stray-instance bug. Enable via tty1.sh webplay; restore ES with tty1.sh restore.
set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Singleton: if another runner holds the lock, exit quietly.
exec 9>/tmp/rpc_runner.lock
if ! flock -n 9; then
  echo "[webplay-runner] another runner is already active; exiting"
  exit 0
fi

LAUNCH_FIFO="${RPC_LAUNCH_FIFO:-/tmp/rpc_launch}"
STATE_FILE="${RPC_STATE_FILE:-/tmp/rpc_state}"
H264_FIFO="/tmp/rpc_h264.ts"
RECCFG="$SCRIPT_DIR/record_h264.cfg"
PUBLISH="$SCRIPT_DIR/publish.sh"

[ -p "$LAUNCH_FIFO" ] || mkfifo "$LAUNCH_FIFO"
[ -p "$H264_FIFO" ] || mkfifo "$H264_FIFO"
set_state() { printf '%s' "$1" > "$STATE_FILE"; }

# Wait briefly for the MediaMTX service (RTSP :8554) so the first publish lands.
for _ in $(seq 1 20); do ss -ltn 2>/dev/null | grep -q ":8554" && break; sleep 1; done

# Hold the request FIFO open read-write so non-blocking writes always find a reader.
exec 3<>"$LAUNCH_FIFO"
set_state '{"status":"idle","game":null}'
echo "[webplay-runner] idle; waiting for launch requests on $LAUNCH_FIFO"

while true; do
  read -r REQ <&3 || { sleep 1; continue; }
  [ -z "$REQ" ] && continue
  SYS=$(printf '%s' "$REQ" | sed -nE 's/.*"system"[[:space:]]*:[[:space:]]*"([^"]+)".*/\1/p')
  ROM=$(printf '%s' "$REQ" | sed -nE 's/.*"rom"[[:space:]]*:[[:space:]]*"([^"]+)".*/\1/p')
  if [ -z "$SYS" ] || [ -z "$ROM" ]; then
    echo "[webplay-runner] bad request: $REQ"; continue
  fi

  EMUCFG="/opt/retropie/configs/$SYS/emulators.cfg"
  DEFAULT=$(sed -nE 's/^default = "?([^"]+)"?.*/\1/p' "$EMUCFG" 2>/dev/null)
  TEMPLATE=$(sed -nE "s/^${DEFAULT} = \"(.*)\"\$/\1/p" "$EMUCFG" 2>/dev/null)
  if [ -z "${TEMPLATE:-}" ]; then
    echo "[webplay-runner] no emulator command for $SYS"; continue
  fi
  # shellcheck disable=SC2086
  eval "set -- ${TEMPLATE//%ROM%/\"$ROM\"}"

  echo "[webplay-runner] launching $SYS: $ROM"
  set_state "{\"status\":\"running\",\"game\":{\"system\":\"$SYS\",\"rom\":\"$ROM\"}}"
  bash "$PUBLISH" "$H264_FIFO" >/tmp/webplay_publish.log 2>&1 &
  PUB=$!
  "$@" -r "$H264_FIFO" --recordconfig "$RECCFG" >/tmp/webplay_retroarch.log 2>&1
  kill "$PUB" 2>/dev/null
  set_state '{"status":"idle","game":null}'
  echo "[webplay-runner] game exited; back to idle"
done
