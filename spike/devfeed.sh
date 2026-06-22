#!/usr/bin/env bash
# Spike helper: (re)start the relay + a test-pattern ffmpeg feeder.
#
# IMPORTANT: run this as a FILE (`bash devfeed.sh`), never inline via `ssh '...'`.
# As a file, this process's argv is just "bash devfeed.sh", so the pkill/pgrep
# patterns below can't match (and kill) the runner itself — which is exactly what
# bites you when the same patterns are passed inline in an `ssh '<cmd>'` string.
#
# Usage:  bash spike/devfeed.sh [restart|stop]
set -uo pipefail
REPO="$HOME/GitHub/retropi_server"
FIFO="/tmp/rpc_spike.ts"

stop() {
  pkill -f "spike/relay.py" 2>/dev/null
  pkill -x ffmpeg 2>/dev/null
  pkill -x uv 2>/dev/null
  sleep 2
}

start() {
  rm -f "$FIFO"; mkfifo "$FIFO"
  cd "$REPO" || exit 1
  nohup uv run --no-sync spike/relay.py >/tmp/spike_relay.log 2>&1 </dev/null &
  disown
  sleep 5
  # testsrc = unmistakable color-bar test card w/ a moving marker (easy latency eyeball).
  # -g 12 = keyframe every 0.4s (fast late-join sync), -bf 0 = no B-frames (low latency),
  # 800k = cellular/funnel-friendly.
  nohup ffmpeg -hide_banner -loglevel warning -y -re \
    -f lavfi -i "testsrc=size=320x240:rate=30" \
    -c:v mpeg1video -b:v 800k -bf 0 -g 12 -pix_fmt yuv420p \
    -f mpegts "$FIFO" >/tmp/spike_ffmpeg.log 2>&1 </dev/null &
  disown
  sleep 5
}

case "${1:-restart}" in
  stop) stop; echo "stopped relay + feeder" ;;
  restart) stop; start
    ss -ltn | grep -q ":8090" && echo "relay LISTENING :8090" || echo "relay NOT listening"
    pgrep -x ffmpeg >/dev/null && echo "ffmpeg RUNNING" || echo "ffmpeg NOT running"
    echo "--- ffmpeg log ---"; tail -3 /tmp/spike_ffmpeg.log
    echo "--- relay log ---"; tail -3 /tmp/spike_relay.log ;;
  *) echo "usage: devfeed.sh [restart|stop]" >&2; exit 2 ;;
esac
