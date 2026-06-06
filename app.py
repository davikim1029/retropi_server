"""Entrypoint. Run directly (`python3 app.py`) or under the systemd unit.

Reads host/port/etc. from backend.config (env-overridable) and serves the FastAPI
app with uvicorn.
"""

from __future__ import annotations

import logging

import uvicorn

from backend.config import settings


def main() -> None:
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # Pass the import string so uvicorn owns the app lifecycle (lifespan, reload).
    uvicorn.run(
        "backend.server:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
