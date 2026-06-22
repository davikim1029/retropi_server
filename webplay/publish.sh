#!/usr/bin/env bash
# Republish RetroArch's H.264/TS FIFO to MediaMTX over RTSP. Video is a pure remux
# (-c:v copy, no re-encode, cheap + low latency); audio is transcoded AAC -> Opus
# because WebRTC requires Opus (cheap). MediaMTX then serves WebRTC (WHEP) to the
# phone. If the recording has no audio track, ffmpeg just publishes video.
#
# Usage: publish.sh [H264_FIFO] [RTSP_URL]
set -uo pipefail
H264_FIFO="${1:-/tmp/rpc_h264.ts}"
URL="${2:-rtsp://localhost:8554/game}"

exec ffmpeg -hide_banner -loglevel warning -fflags nobuffer -flags low_delay \
  -f mpegts -i "$H264_FIFO" \
  -c:v copy -c:a libopus -b:a 96k \
  -f rtsp -rtsp_transport tcp "$URL"
