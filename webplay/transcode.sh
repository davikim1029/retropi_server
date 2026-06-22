#!/usr/bin/env bash
# Transcode RetroArch's MJPEG/nut FIFO -> MPEG-1/TS @ a forced 60fps for jsmpeg.
#
# RetroArch can't emit mpeg1video at the GB's 59.7275 fps (the codec only allows
# fixed broadcast rates), so it records MJPEG (no fps limit) and this bridges it
# to the MPEG-1/TS jsmpeg needs. spike-runner.sh calls this per session, so you
# can iterate the transcode by editing this file + killing retroarch (the runner
# relaunches) — no reboot needed.
#
# Usage: transcode.sh [FIFO_RAW] [FIFO_OUT]
set -uo pipefail
FIFO_RAW="${1:-/tmp/rpc_raw.nut}"
FIFO_OUT="${2:-/tmp/rpc_spike.ts}"

# -y: overwrite the existing FIFO node without prompting (else ffmpeg exits).
# nobuffer/low_delay keep latency tight. -bf 0 (no B-frames), -g 12. -an: video only.
exec ffmpeg -hide_banner -loglevel warning -y -fflags nobuffer -flags low_delay \
  -f nut -i "$FIFO_RAW" \
  -an -r 60 -c:v mpeg1video -b:v 800k -bf 0 -g 12 -pix_fmt yuv420p \
  -f mpegts "$FIFO_OUT"
