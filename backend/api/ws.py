"""WebSocket controller endpoint.

Implements the protocol from the design doc (PEDD §8):

    client -> {"type":"hello","protocol":"1.0","controller":"gameboy"}
    server -> {"type":"accepted","session_id":"<uuid>"}
    client -> {"type":"button_down","button":"A","timestamp":...}
    client -> {"type":"button_up","button":"A","timestamp":...}
    client -> {"type":"heartbeat"}            (every 2s)
    client -> {"type":"system","action":"reboot"}   (REBOOT button, after confirm)

A session is created when the socket connects, refreshed on every message, and
removed on disconnect (which releases all buttons via the session manager).
"""

from __future__ import annotations

import logging

from fastapi import WebSocket, WebSocketDisconnect

from backend.input.state import InputStateEngine
from backend.profiles.loader import Profile
from backend.sessions.manager import SessionManager
from backend.system.control import request_reboot, send_retroarch_command

logger = logging.getLogger(__name__)

PROTOCOL_VERSION = "1.0"


async def websocket_endpoint(websocket: WebSocket) -> None:
    state = websocket.app.state
    engine: InputStateEngine = state.engine
    sessions: SessionManager = state.sessions
    profile: Profile = state.profile

    await websocket.accept()
    session = sessions.create(profile=profile.name)

    try:
        while True:
            message = await websocket.receive_json()
            if not isinstance(message, dict):
                continue

            sessions.touch(session.session_id)
            mtype = message.get("type")

            if mtype == "hello":
                await websocket.send_json(
                    {
                        "type": "accepted",
                        "session_id": session.session_id,
                        "protocol": PROTOCOL_VERSION,
                        "controller": profile.name,
                    }
                )
            elif mtype == "button_down":
                _handle_button(engine, message, pressed=True)
            elif mtype == "button_up":
                _handle_button(engine, message, pressed=False)
            elif mtype == "system":
                _handle_system(message)
            elif mtype == "heartbeat":
                pass  # touch() above already refreshed the session
            else:
                logger.debug("ignoring message of unknown type %r", mtype)
    except WebSocketDisconnect:
        logger.info("session %s disconnected", session.session_id)
    except Exception:  # malformed frame, non-JSON, etc. — drop the connection cleanly
        logger.exception("websocket error for session %s", session.session_id)
    finally:
        # release_all happens inside remove(); guarantees no stuck buttons.
        sessions.remove(session.session_id)


def _handle_button(engine: InputStateEngine, message: dict, pressed: bool) -> None:
    button = message.get("button")
    if not isinstance(button, str):
        return
    name = button.strip().upper()
    if pressed:
        engine.press(name)
    else:
        engine.release(name)


def _handle_system(message: dict) -> None:
    """Host-level actions (not gamepad input): reboot + RetroArch save/load state."""
    action = message.get("action")
    if action == "reboot":
        request_reboot()  # guarded: no-ops off a real Pi (see system/control.py)
    elif action == "save_state":
        send_retroarch_command("SAVE_STATE")
    elif action == "load_state":
        send_retroarch_command("LOAD_STATE")
    else:
        logger.debug("ignoring system message with unknown action %r", action)
