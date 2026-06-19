"""/video route tests, driven by the mock source (no ffmpeg, no capture hardware).

Settings is a frozen dataclass whose field defaults are read from the environment at
import time, so we enable video by constructing ``Settings(video_enabled=True)`` and
swapping it into the server module rather than mutating os.environ after the fact.
"""

import asyncio

from fastapi.testclient import TestClient

from backend.api.video import mjpeg_stream
from backend.config import Settings
from backend.server import create_app
from backend.video.mock_source import MockVideoSource


def _app_with_video(monkeypatch):
    import backend.server as server_mod

    # force_mock keeps its import-time default (RPC_FORCE_MOCK=1 from conftest), so the
    # source resolves to the bundled-frame mock; we only flip on video here.
    monkeypatch.setattr(server_mod, "settings", Settings(video_enabled=True, video_capture="test"))
    return server_mod.create_app()


def test_status_and_health_when_enabled(monkeypatch):
    app = _app_with_video(monkeypatch)
    with TestClient(app) as client:
        status = client.get("/video/status").json()
        assert status["enabled"] is True
        assert status["name"] == "mock"
        assert status["running"] is True

        assert client.get("/health").json()["video"] == "mock"


def test_disabled_by_default():
    app = create_app()  # RPC_VIDEO_ENABLED unset => video off
    with TestClient(app) as client:
        status = client.get("/video/status").json()
        assert status["enabled"] is False
        assert status["name"] is None
        assert client.get("/video/stream.mjpeg").status_code == 404
        assert client.get("/health").json()["video"] is None


def test_mjpeg_stream_emits_multipart_jpeg_frames():
    async def go():
        src = MockVideoSource(fps=120)
        await src.start()
        gen = mjpeg_stream(src)
        chunks = []
        async for chunk in gen:
            chunks.append(chunk)
            if len(chunks) >= 2:
                break
        await gen.aclose()
        await src.stop()
        return b"".join(chunks)

    data = asyncio.run(go())
    assert b"--frame" in data
    assert b"Content-Type: image/jpeg" in data
    assert b"Content-Length:" in data
    assert b"\xff\xd8" in data  # at least one JPEG SOI made it into the multipart body
