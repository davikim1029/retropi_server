"""Mock video backend.

Cycles a few small bundled JPEG frames (``backend/video/assets/*.jpg``) at the
configured FPS, so the entire transport + frontend split view can be developed and
tested on macOS / in CI with no capture hardware and no extra dependencies. Used on
non-Linux hosts, under ``RPC_FORCE_MOCK``, and via ``RPC_VIDEO_CAPTURE=test``.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from backend.config import settings
from backend.video.source import VideoSource

logger = logging.getLogger(__name__)

ASSETS_DIR = Path(__file__).resolve().parent / "assets"


def _load_asset_frames() -> list[bytes]:
    """Read the bundled placeholder JPEGs (committed under assets/).

    Raises if none are found rather than guessing — the server lifespan catches this
    and disables video, so a broken checkout degrades to "no stream" without ever
    touching the controller path.
    """
    frames = [path.read_bytes() for path in sorted(ASSETS_DIR.glob("*.jpg"))]
    if not frames:
        raise RuntimeError(f"no mock video assets found in {ASSETS_DIR}")
    return frames


class MockVideoSource(VideoSource):
    """Publishes bundled placeholder JPEGs in a loop (no capture hardware)."""

    name = "mock"

    def __init__(self, fps: int | None = None) -> None:
        super().__init__()
        self._fps = max(1, fps if fps is not None else settings.video_fps)
        self._frames = _load_asset_frames()
        self._task: asyncio.Task | None = None
        self._running = False

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        # Publish the first frame immediately so a subscriber that connects right away
        # gets a frame without waiting a full period.
        await self.publish(self._frames[0])
        self._task = asyncio.create_task(self._run())
        logger.info("mock video source started: %d frame(s) @ %d fps", len(self._frames), self._fps)

    async def _run(self) -> None:
        period = 1.0 / self._fps
        i = 1
        try:
            while self._running:
                await asyncio.sleep(period)
                await self.publish(self._frames[i % len(self._frames)])
                i += 1
        except asyncio.CancelledError:
            pass

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("mock video source stopped")

    @property
    def is_running(self) -> bool:
        return self._running
