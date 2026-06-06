import time

from fastapi.testclient import TestClient

from backend.server import create_app


def wait_for(predicate, timeout=2.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def test_hello_handshake_and_health():
    app = create_app()
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "hello", "protocol": "1.0", "controller": "gameboy"})
            reply = ws.receive_json()
            assert reply["type"] == "accepted"
            assert reply["session_id"]
            assert app.state.sessions.count == 1

            health = client.get("/health").json()
            assert health["status"] == "healthy"
            assert health["connections"] == 1
            assert health["driver"] == "mock"


def test_button_press_drives_the_gamepad():
    app = create_app()
    with TestClient(app) as client:
        engine = app.state.engine
        driver = app.state.driver
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "hello"})
            ws.receive_json()

            ws.send_json({"type": "button_down", "button": "A", "timestamp": 1})
            # Round-trip a hello to guarantee the prior button_down was processed
            # (messages on one socket are handled in order).
            ws.send_json({"type": "hello"})
            ws.receive_json()
            assert engine.state["A"] is True
            assert (("key", "BTN_SOUTH"), 1) in driver.events

            ws.send_json({"type": "button_up", "button": "A", "timestamp": 2})
            ws.send_json({"type": "hello"})
            ws.receive_json()
            assert engine.state["A"] is False


def test_disconnect_releases_all_buttons():
    app = create_app()
    with TestClient(app) as client:
        engine = app.state.engine
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "hello"})
            ws.receive_json()
            ws.send_json({"type": "button_down", "button": "B", "timestamp": 1})
            ws.send_json({"type": "hello"})
            ws.receive_json()
            assert engine.state["B"] is True
        # Leaving the context disconnects the socket; the server must release everything.
        assert wait_for(lambda: app.state.sessions.count == 0)
        assert wait_for(lambda: not any(engine.state.values()))
