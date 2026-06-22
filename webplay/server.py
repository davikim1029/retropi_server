"""webplay fork server — launcher + low-latency play, on its own port/funnel.

Reuses the spike's proven pieces (MJPEG/TS FIFO -> WS video relay; control proxy to
the existing :8080 gamepad app) and adds the launcher: browse the ROM library, ask
the tty1 runner to launch a pick, route back to the launcher on quit. Kept separate
from backend/ (:8080) so the working controller is untouched until this is ready.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

import websockets
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse

from . import manager
from .scanner import scan_games

FRONTEND = Path(__file__).resolve().parent / "frontend"
VIDEO_FIFO = os.environ.get("RPC_WEBPLAY_FIFO", "/tmp/rpc_webplay.ts")
GAMEPAD_WS = os.environ.get("RPC_GAMEPAD_WS", "ws://127.0.0.1:8080/ws")

_clients: set[asyncio.Queue[bytes | None]] = set()
_loop: asyncio.AbstractEventLoop | None = None


def _broadcast(data: bytes) -> None:
    # MPEG-TS is continuous: never drop bytes mid-stream (corrupts every later
    # frame). Disconnect a slow client instead so it reconnects clean.
    for q in list(_clients):
        try:
            q.put_nowait(data)
        except asyncio.QueueFull:
            _clients.discard(q)
            with contextlib.suppress(asyncio.QueueFull):
                q.put_nowait(None)


def _reader_thread() -> None:
    while True:
        try:
            with open(VIDEO_FIFO, "rb", buffering=0) as f:  # blocks until a writer
                while True:
                    data = f.read(65536)
                    if not data:
                        break
                    if _loop is not None:
                        _loop.call_soon_threadsafe(_broadcast, data)
        except FileNotFoundError:
            return
        time.sleep(0.2)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _loop
    _loop = asyncio.get_running_loop()
    os.makedirs(os.path.dirname(VIDEO_FIFO) or ".", exist_ok=True)
    if not os.path.exists(VIDEO_FIFO):
        with contextlib.suppress(OSError):
            os.mkfifo(VIDEO_FIFO)
    threading.Thread(target=_reader_thread, daemon=True).start()
    yield


def create_app() -> FastAPI:
    app = FastAPI(lifespan=lifespan)

    # ---- launcher API ----
    @app.get("/api/games")
    async def games() -> JSONResponse:
        return JSONResponse({"games": [g.as_dict() for g in scan_games()]})

    @app.get("/api/state")
    async def state() -> JSONResponse:
        return JSONResponse(manager.read_state())

    @app.post("/api/quit")
    async def quit_game() -> JSONResponse:
        # Power off the emulator: SIGTERM RetroArch (clean exit, flushes SRAM); the
        # tty1 runner then returns to idle and the launcher shows the grid again.
        return JSONResponse({"ok": manager.quit_game()})

    @app.post("/api/savestate")
    async def savestate() -> JSONResponse:
        return JSONResponse({"ok": manager.send_retroarch_command("SAVE_STATE")})

    @app.post("/api/loadstate")
    async def loadstate() -> JSONResponse:
        return JSONResponse({"ok": manager.send_retroarch_command("LOAD_STATE")})

    @app.post("/api/launch")
    async def launch(body: dict) -> JSONResponse:
        system, rom = body.get("system"), body.get("rom")
        if not system or not rom:
            return JSONResponse({"error": "system and rom required"}, status_code=400)
        try:
            manager.request_launch(system, rom)
        except manager.LauncherError as e:
            return JSONResponse({"error": str(e)}, status_code=503)
        return JSONResponse({"ok": True, "system": system, "rom": rom})

    # ---- static pages ----
    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(FRONTEND / "launcher.html")

    @app.get("/play")
    async def play() -> FileResponse:
        return FileResponse(FRONTEND / "play.html")

    @app.get("/jsmpeg.min.js")
    async def jsmpeg() -> FileResponse:
        return FileResponse(FRONTEND / "jsmpeg.min.js", media_type="application/javascript")

    # ---- video (jsmpeg) ----
    @app.websocket("/ws")
    async def ws(sock: WebSocket) -> None:
        await sock.accept()
        q: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=128)
        _clients.add(q)
        try:
            while True:
                item = await q.get()
                if item is None:
                    break
                await sock.send_bytes(item)
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            _clients.discard(q)

    # ---- controls (proxy to the :8080 gamepad app) ----
    @app.websocket("/control")
    async def control(sock: WebSocket) -> None:
        await sock.accept()
        try:
            upstream = await websockets.connect(GAMEPAD_WS, open_timeout=5)
        except Exception:
            with contextlib.suppress(Exception):
                await sock.close()
            return

        async def phone_to_pi() -> None:
            with contextlib.suppress(Exception):
                while True:
                    await upstream.send(await sock.receive_text())

        async def pi_to_phone() -> None:
            with contextlib.suppress(Exception):
                async for msg in upstream:
                    await sock.send_text(msg if isinstance(msg, str) else msg.decode())

        try:
            _, pending = await asyncio.wait(
                {asyncio.create_task(phone_to_pi()), asyncio.create_task(pi_to_phone())},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for t in pending:
                t.cancel()
        finally:
            with contextlib.suppress(Exception):
                await upstream.close()

    return app
