#!/usr/bin/env bash
# Restart the spike relay (after a relay.py / play.html change) WITHOUT rebooting,
# then SIGTERM RetroArch so the runner's loop relaunches the transcode against the
# fresh relay. Run as a FILE (bash spike/reload.sh) so the pkill patterns below
# can't match this script's own argv.
set -uo pipefail
cd "$HOME/GitHub/retropi_server" || exit 1

# Kill ONLY the relay's python (its `uv run` parent then exits on its own). Do NOT
# `pkill -x uv` — that also kills the iphone-controller service's `uv run app.py`
# (the gamepad on :8080), taking down controls.
pkill -f "spike/relay.py" 2>/dev/null
sleep 3
nohup uv run --no-sync spike/relay.py >/tmp/spike_relay.log 2>&1 </dev/null &
disown
sleep 5
pkill -TERM -x retroarch 2>/dev/null   # runner relaunches transcode + retroarch
sleep 9

echo "relay:     $(ss -ltn | grep -q ':8090' && echo up || echo DOWN)"
echo "transcode: $(pgrep -x ffmpeg >/dev/null && echo up || echo DOWN)"
echo "retroarch: $(pgrep -x retroarch >/dev/null && echo up || echo DOWN)"
echo "play.html: $(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8090/)"
tail -3 /tmp/spike_relay.log
