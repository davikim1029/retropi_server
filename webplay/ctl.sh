#!/usr/bin/env bash
# Start/stop/restart the webplay app. Run as a FILE (bash webplay/ctl.sh ...) so the
# pkill pattern below matches the python process, not this runner's own argv.
set -uo pipefail
cd "$HOME/GitHub/retropi_server" || exit 1

case "${1:-start}" in
  stop|restart) pkill -f "webplay_app.py" 2>/dev/null; sleep 2 ;;
esac

case "${1:-start}" in
  start|restart)
    nohup uv run --no-sync webplay_app.py >/tmp/webplay_app.log 2>&1 </dev/null &
    disown
    for i in $(seq 1 8); do sleep 2; ss -ltn | grep -q ":8091" && break; done
    if ss -ltn | grep -q ":8091"; then echo "webplay up on :8091"; else echo "webplay DOWN"; tail -15 /tmp/webplay_app.log; fi
    ;;
  stop) echo "webplay stopped" ;;
  *) echo "usage: ctl.sh start|stop|restart" >&2; exit 2 ;;
esac
