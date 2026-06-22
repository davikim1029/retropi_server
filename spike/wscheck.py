#!/usr/bin/env python3
"""Spike helper: connect to a relay WS (optionally via the funnel) and print the
number of bytes received over a few frames. 0 = nothing flowing. Used to tell
"relay up + streaming" from "relay up but no source feeding the FIFO".

Usage: uv run --no-sync python spike/wscheck.py wss://host:port/ws
"""
import asyncio
import sys

import websockets


async def go() -> None:
    url = sys.argv[1] if len(sys.argv) > 1 else "ws://127.0.0.1:8090/ws"
    try:
        async with websockets.connect(url, max_size=None, open_timeout=10) as ws:
            total = 0
            for _ in range(6):
                total += len(await asyncio.wait_for(ws.recv(), timeout=6))
            print(total)
    except Exception:
        print(0)


asyncio.run(go())
