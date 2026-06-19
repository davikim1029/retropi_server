"""HTTP endpoints for the optional live-video stream.

Two routes, registered before the static mount in :mod:`backend.server` (same ordering
rule as ``/ws`` and ``/health``):

* ``GET /video/stream.mjpeg`` — a ``multipart/x-mixed-replace`` MJPEG stream that mobile
  Safari renders directly in an ``<img>``. Each part is one JPEG frame from the active
  :class:`~backend.video.source.VideoSource`. Open this URL on its own to verify capture
  + transport independently of the controller.
* ``GET /video/status`` — small JSON for diagnosis (is video enabled, which backend, is
  it running, has it produced a frame yet).

Both no-op gracefully (404 / ``enabled: false``) when video is disabled, so the routes
are always present but inert unless ``RPC_VIDEO_ENABLED`` is set.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse

from backend.video.source import VideoSource

logger = logging.getLogger(__name__)

BOUNDARY = "frame"
MEDIA_TYPE = f"multipart/x-mixed-replace; boundary={BOUNDARY}"


async def mjpeg_stream(source: VideoSource) -> AsyncIterator[bytes]:
    """Yield the source's JPEG frames as multipart/x-mixed-replace parts."""
    async for frame in source.frames():
        header = (
            f"--{BOUNDARY}\r\n"
            f"Content-Type: image/jpeg\r\n"
            f"Content-Length: {len(frame)}\r\n\r\n"
        ).encode("ascii")
        yield header + frame + b"\r\n"


async def video_stream_endpoint(request: Request) -> Response:
    source: VideoSource | None = getattr(request.app.state, "video", None)
    if source is None:
        return JSONResponse({"error": "video disabled"}, status_code=404)
    headers = {
        # MJPEG must never be cached, and proxies must not buffer it.
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache",
        "X-Accel-Buffering": "no",
    }
    return StreamingResponse(mjpeg_stream(source), media_type=MEDIA_TYPE, headers=headers)


async def video_status_endpoint(request: Request) -> JSONResponse:
    source: VideoSource | None = getattr(request.app.state, "video", None)
    return JSONResponse(
        {
            "enabled": source is not None,
            "name": source.name if source else None,
            "running": source.is_running if source else False,
            "has_frames": source.has_frames if source else False,
        }
    )
