"""Entrypoint for the webplay fork: uv run webplay_app.py (serves on :8091)."""

import os

import uvicorn

from webplay.server import create_app

app = create_app()

if __name__ == "__main__":
    uvicorn.run(
        app,
        host=os.environ.get("RPC_WEBPLAY_HOST", "0.0.0.0"),
        port=int(os.environ.get("RPC_WEBPLAY_PORT", "8091")),
        log_level=os.environ.get("RPC_LOG_LEVEL", "warning").lower(),
    )
