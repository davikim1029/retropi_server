"""FastAPI application factory and lifecycle wiring.

On startup the lifespan opens the virtual gamepad, builds the input engine and
session manager, starts the session reaper, and prints the controller URL + QR.
On shutdown it stops the reaper and tears the gamepad down (releasing all buttons).
This is what gives the "recreate gamepad on restart" behavior from the design doc.
"""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.api.ws import websocket_endpoint
from backend.config import FRONTEND_DIR, settings
from backend.discovery.network import controller_urls, qr_ascii
from backend.input.driver import create_driver
from backend.input.state import InputStateEngine
from backend.profiles.autoconfig import write_autoconfig
from backend.profiles.loader import load_profile
from backend.sessions.manager import SessionManager

logger = logging.getLogger(__name__)


async def _reaper_loop(app: FastAPI) -> None:
    """Periodically expire idle sessions (releasing their buttons)."""
    sessions: SessionManager = app.state.sessions
    try:
        while True:
            await asyncio.sleep(settings.reaper_interval_s)
            sessions.reap()
    except asyncio.CancelledError:
        pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    profile = load_profile(settings.profile)
    driver = create_driver(force_mock=settings.force_mock)
    driver.open(profile)

    if settings.write_autoconfig:
        write_autoconfig(profile, settings.autoconfig_dir)

    engine = InputStateEngine(profile, driver)
    sessions = SessionManager(engine, timeout_s=settings.session_timeout_s)

    app.state.profile = profile
    app.state.driver = driver
    app.state.engine = engine
    app.state.sessions = sessions
    app.state.started_at = time.time()

    reaper = asyncio.create_task(_reaper_loop(app))

    for url in controller_urls(settings.port):
        logger.info("controller available at %s", url)
    primary = controller_urls(settings.port)[0]
    # Print the QR straight to stdout so it renders in the terminal / journal.
    print(f"\nScan to connect ({profile.display_name}):  {primary}\n")
    print(qr_ascii(primary))

    try:
        yield
    finally:
        reaper.cancel()
        try:
            await reaper
        except asyncio.CancelledError:
            pass
        driver.close()


def create_app() -> FastAPI:
    app = FastAPI(title="iPhone Virtual Gamepad", lifespan=lifespan)

    @app.get("/health")
    async def health() -> JSONResponse:
        started_at = getattr(app.state, "started_at", None)
        sessions: SessionManager | None = getattr(app.state, "sessions", None)
        driver = getattr(app.state, "driver", None)
        uptime = int(time.time() - started_at) if started_at else 0
        return JSONResponse(
            {
                "status": "healthy",
                "connections": sessions.count if sessions else 0,
                "uptime": uptime,
                "driver": driver.name if driver else None,
            }
        )

    # Register the WebSocket route BEFORE the catch-all static mount so the mount
    # at "/" doesn't shadow it (Starlette matches routes in registration order).
    app.add_api_websocket_route("/ws", websocket_endpoint)

    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
    return app
