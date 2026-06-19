"""Live-video source abstraction for the optional streaming mode.

Mirrors the :class:`~backend.input.driver.GamepadDriver` pattern: a small ABC with two
backends chosen at runtime by :func:`create_source`, so no other module needs to know
which platform it is on.

* ``FfmpegVideoSource`` — captures the Pi's screen via ffmpeg (default: a read-only KMS
  scanout grab) and encodes MJPEG. Used on the Pi. HDMI keeps working because the grab
  never becomes DRM master — it just maps the buffer already being scanned out.
* ``MockVideoSource`` — cycles a few small bundled JPEGs at the configured FPS. Used on
  macOS, in tests, under ``RPC_FORCE_MOCK``, and via ``RPC_VIDEO_CAPTURE=test``.

Both publish a stream of complete JPEG frames. Subscribers consume via :meth:`frames`
and always receive the *latest* frame, so a slow phone never back-pressures capture —
newest-wins, analogous to the input engine's last-write-wins.
"""

from __future__ import annotations

import asyncio
import logging
import platform
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from backend.config import settings

logger = logging.getLogger(__name__)

# JPEG frame delimiters. ffmpeg's MJPEG muxer emits each frame as a standalone JPEG
# bracketed by Start-Of-Image (FF D8) and End-Of-Image (FF D9); we resync on those.
SOI = b"\xff\xd8"
EOI = b"\xff\xd9"


class JpegStreamSplitter:
    """Reassemble a raw MJPEG byte stream into individual JPEG frames.

    ffmpeg's stdout arrives in arbitrary chunks that do not line up with frame
    boundaries, so we buffer and split on SOI…EOI. This is the testable correctness
    core of the video path (the analogue of the input engine's last-write-wins logic):
    feed it any chunking of a stream and it yields exactly the embedded frames.
    """

    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, chunk: bytes) -> list[bytes]:
        """Append ``chunk`` and return any now-complete JPEG frames (in order)."""
        self._buf.extend(chunk)
        frames: list[bytes] = []
        while True:
            start = self._buf.find(SOI)
            if start < 0:
                # No frame start yet. Drop everything but a trailing byte, which may be
                # the first half (0xFF) of an SOI split across two reads.
                if len(self._buf) > 1:
                    del self._buf[:-1]
                break
            if start > 0:
                del self._buf[:start]  # discard junk/leading bytes before the frame
            end = self._buf.find(EOI, len(SOI))
            if end < 0:
                break  # frame not finished; wait for more bytes
            end += len(EOI)
            frames.append(bytes(self._buf[:end]))
            del self._buf[:end]
        return frames


class VideoSource(ABC):
    """Publish/subscribe base for live JPEG frames.

    Backends call :meth:`publish` as frames arrive; HTTP handlers iterate :meth:`frames`.
    The base holds only the most recent frame plus a monotonically increasing sequence
    number, so every subscriber jumps to the newest frame and laggards skip stale ones.
    """

    #: Human-readable backend name (for logs, /health, /video/status).
    name: str = "base"

    def __init__(self) -> None:
        self._latest: bytes | None = None
        self._seq = 0
        self._cond = asyncio.Condition()

    @property
    def has_frames(self) -> bool:
        """True once at least one frame has been published."""
        return self._seq > 0

    async def publish(self, frame: bytes) -> None:
        """Make ``frame`` the latest and wake every waiting subscriber."""
        async with self._cond:
            self._latest = frame
            self._seq += 1
            self._cond.notify_all()

    async def frames(self) -> AsyncIterator[bytes]:
        """Yield the latest JPEG frame as soon as one is available, then each new one.

        Newest-wins: a subscriber that falls behind simply receives the most recent
        frame on its next iteration rather than a backlog.
        """
        last_seq = -1
        while True:
            async with self._cond:
                if self._seq == last_seq:
                    await self._cond.wait()
                frame = self._latest
                last_seq = self._seq
            if frame is not None:
                yield frame

    # --- lifecycle (backend-specific) -------------------------------------
    @abstractmethod
    async def start(self) -> None:
        """Begin producing frames (idempotent)."""

    @abstractmethod
    async def stop(self) -> None:
        """Stop producing frames and release any resources (idempotent)."""

    @property
    @abstractmethod
    def is_running(self) -> bool:
        """Whether the producer is currently active."""


def create_source(force_mock: bool = False) -> VideoSource:
    """Return the appropriate video backend for this host.

    Uses the real ffmpeg capture on Linux; otherwise (macOS, ``force_mock``, or
    ``RPC_VIDEO_CAPTURE=test``) returns the mock that cycles bundled placeholder frames,
    so the whole transport + frontend split view is developable on the Mac.
    """
    if not force_mock and settings.video_capture != "test" and platform.system() == "Linux":
        from backend.video.ffmpeg_source import FfmpegVideoSource

        return FfmpegVideoSource()

    from backend.video.mock_source import MockVideoSource

    return MockVideoSource()
