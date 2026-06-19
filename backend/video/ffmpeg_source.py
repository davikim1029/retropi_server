"""ffmpeg video backend (the real Pi capture).

Spawns ffmpeg as a child process, reads its MJPEG stdout, splits it into JPEG frames
(:class:`~backend.video.source.JpegStreamSplitter`) and publishes them. The process is
*supervised*: if ffmpeg exits or crashes, it is relaunched with exponential backoff, so
a transient capture hiccup self-heals — and because this lives in its own module and
subprocess, none of it can disturb the WebSocket gamepad path.

Capture defaults to a **KMS scanout grab** (``-f kmsgrab``), which is the right tool for
the Pi's full-KMS stack (``vc4-kms-v3d``): it maps the framebuffer already being scanned
out to HDMI, read-only, so the TV is unaffected. The exact pipeline (which ``/dev/dri``
card, the ``hwdownload,format=`` for VC4) may need tuning on hardware, so the whole
command is overridable via ``RPC_VIDEO_FFMPEG_CMD`` — iterate on the Pi without code
changes. ``RPC_VIDEO_CAPTURE=fbdev`` is a diagnostic fallback (under full KMS ``/dev/fb0``
usually shows the console, not the game).

kmsgrab needs ``CAP_SYS_ADMIN``; the service runs non-root, so ``scripts/install.sh``
grants it (opt-in) via ``setcap`` on the ffmpeg binary.
"""

from __future__ import annotations

import asyncio
import logging
import shlex

from backend.config import settings
from backend.video.source import JpegStreamSplitter, VideoSource

logger = logging.getLogger(__name__)

# Cap the relaunch backoff so a persistently-failing capture keeps retrying calmly.
_MAX_BACKOFF_S = 15.0
_READ_CHUNK = 65536


class FfmpegVideoSource(VideoSource):
    """Captures the screen via ffmpeg and publishes MJPEG frames."""

    name = "ffmpeg"

    def __init__(self) -> None:
        super().__init__()
        self._proc: asyncio.subprocess.Process | None = None
        self._supervisor: asyncio.Task | None = None
        self._running = False

    def _build_command(self) -> list[str]:
        """Assemble the ffmpeg argv from config, or use the full override verbatim."""
        if settings.video_ffmpeg_cmd:
            return shlex.split(settings.video_ffmpeg_cmd)

        fps = str(settings.video_fps)
        scale = f"scale={settings.video_width}:-2"
        out = ["-c:v", "mjpeg", "-q:v", str(settings.video_quality), "-an", "-f", "mjpeg", "pipe:1"]
        base = ["ffmpeg", "-hide_banner", "-loglevel", "error"]

        if settings.video_capture == "fbdev":
            return [
                *base,
                "-f", "fbdev", "-framerate", fps, "-i", settings.video_fb_device,
                "-vf", scale, *out,
            ]
        # Default: read-only KMS scanout grab (the correct path on full-KMS Pis).
        return [
            *base,
            "-device", settings.video_dri_device,
            "-f", "kmsgrab", "-framerate", fps, "-i", "-",
            "-vf", f"hwdownload,format=bgr0,{scale}", *out,
        ]

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._supervisor = asyncio.create_task(self._supervise())

    async def _supervise(self) -> None:
        backoff = 1.0
        splitter = JpegStreamSplitter()
        while self._running:
            cmd = self._build_command()
            logger.info("starting ffmpeg capture: %s", " ".join(cmd))
            try:
                self._proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
            except Exception:
                logger.exception("failed to launch ffmpeg; retrying in %.1fs", backoff)
                await self._sleep_backoff(backoff)
                backoff = min(backoff * 2, _MAX_BACKOFF_S)
                continue

            assert self._proc.stdout is not None
            try:
                while self._running:
                    chunk = await self._proc.stdout.read(_READ_CHUNK)
                    if not chunk:
                        break
                    for frame in splitter.feed(chunk):
                        await self.publish(frame)
                        backoff = 1.0  # frames flowing => healthy; reset backoff
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("error reading ffmpeg output")

            await self._log_stderr()
            rc = self._proc.returncode if self._proc else None
            self._proc = None
            if self._running:
                logger.warning("ffmpeg capture exited (rc=%s); restarting in %.1fs", rc, backoff)
                await self._sleep_backoff(backoff)
                backoff = min(backoff * 2, _MAX_BACKOFF_S)

    async def _sleep_backoff(self, seconds: float) -> None:
        try:
            await asyncio.sleep(seconds)
        except asyncio.CancelledError:
            raise

    async def _log_stderr(self) -> None:
        """Surface ffmpeg's error output — the key signal when capture won't start."""
        if not self._proc or not self._proc.stderr:
            return
        try:
            err = await asyncio.wait_for(self._proc.stderr.read(), timeout=1.0)
        except (asyncio.TimeoutError, Exception):
            return
        text = err.decode("utf-8", "replace").strip()
        if text:
            logger.warning("ffmpeg stderr: %s", text)

    async def stop(self) -> None:
        self._running = False
        if self._supervisor is not None:
            self._supervisor.cancel()
            try:
                await self._supervisor
            except asyncio.CancelledError:
                pass
            self._supervisor = None
        await self._terminate_proc()
        logger.info("ffmpeg video source stopped")

    async def _terminate_proc(self) -> None:
        proc = self._proc
        self._proc = None
        if proc is None or proc.returncode is not None:
            return
        try:
            proc.terminate()
        except ProcessLookupError:
            return
        try:
            await asyncio.wait_for(proc.wait(), timeout=3.0)
        except asyncio.TimeoutError:
            proc.kill()

    @property
    def is_running(self) -> bool:
        return self._running and self._proc is not None and self._proc.returncode is None
