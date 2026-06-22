#!/usr/bin/env python3
"""Throwaway Phase 0 spike relay — NOT production code.

Reads the MPEG-TS stream RetroArch records into a FIFO and fans the bytes out to
browser WebSocket clients running jsmpeg. This validates the jsmpeg transport
(RetroArch mpeg1/ts -> FIFO -> WS -> mobile Safari) with no extra Pi binary; it
reuses the project venv's FastAPI/uvicorn/websockets only.

Run with the project venv (so websockets is available):
    uv run --no-sync spike/relay.py [FIFO_PATH]

Defaults: FIFO=/tmp/rpc_spike.ts, port 8090. Then open http://<pi>:8090/ on the
phone. Newest-wins per client (a slow phone drops frames, never back-pressures
the capture) — same ethos as the input path's last-write-wins.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import sys
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
import websockets
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

FIFO = sys.argv[1] if len(sys.argv) > 1 else "/tmp/rpc_spike.ts"
PORT = int(os.environ.get("SPIKE_PORT", "8090"))
HERE = Path(__file__).resolve().parent
# The real gamepad app (uinput driver) we proxy /control to, so a single funnel
# origin both shows the game (this relay) and plays it (the controller on :8080).
GAMEPAD_WS = os.environ.get("RPC_GAMEPAD_WS", "ws://127.0.0.1:8080/ws")

clients: set[asyncio.Queue[bytes]] = set()
_loop: asyncio.AbstractEventLoop | None = None


def _broadcast(data: bytes) -> None:
    """Called on the event loop thread; push to each client.

    MPEG-TS is a *continuous* stream: dropping bytes mid-stream corrupts every
    later frame until the next keyframe (looks like persistent colored garbage).
    So we never drop bytes — if a client falls too far behind we disconnect it
    (sentinel None) and let the player reconnect clean at the next sequence header.
    """
    for q in list(clients):
        try:
            q.put_nowait(data)
        except asyncio.QueueFull:
            clients.discard(q)
            with contextlib.suppress(asyncio.QueueFull):
                q.put_nowait(None)


def _reader_thread() -> None:
    """Blocking-read the FIFO; reopen across RetroArch relaunches."""
    while True:
        try:
            with open(FIFO, "rb", buffering=0) as f:  # blocks until a writer opens
                while True:
                    data = f.read(65536)
                    if not data:
                        break  # writer (RetroArch) closed; loop to await the next
                    if _loop is not None:
                        _loop.call_soon_threadsafe(_broadcast, data)
        except FileNotFoundError:
            return
        time.sleep(0.2)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _loop
    _loop = asyncio.get_running_loop()
    os.makedirs(os.path.dirname(FIFO) or ".", exist_ok=True)
    if not os.path.exists(FIFO):
        os.mkfifo(FIFO)
    threading.Thread(target=_reader_thread, daemon=True).start()
    print(f"[spike] relay up on :{PORT}, reading FIFO {FIFO}")
    yield


app = FastAPI(lifespan=lifespan)


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(HERE / "play.html")  # video + touch controls


@app.get("/video")
async def video_only() -> FileResponse:
    return FileResponse(HERE / "index.html")  # original video-only test page


@app.get("/jsmpeg.min.js")
async def jsmpeg() -> FileResponse:
    return FileResponse(HERE / "jsmpeg.min.js", media_type="application/javascript")


@app.websocket("/ws")
async def ws(sock: WebSocket) -> None:
    await sock.accept()
    q: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=128)
    clients.add(q)
    try:
        while True:
            item = await q.get()
            if item is None:  # we fell behind; close so the player reconnects fresh
                break
            await sock.send_bytes(item)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        clients.discard(q)


@app.websocket("/control")
async def control(sock: WebSocket) -> None:
    """Transparently bridge the phone's controller WS to the gamepad app on :8080.

    The funnel only exposes this relay's port, so off-WiFi play needs controls to
    ride the same origin as the video. We just pipe the v1.0 protocol frames both
    ways; the :8080 app does the real work (sessions + uinput)."""
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


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="warning")
