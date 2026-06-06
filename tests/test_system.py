"""Reboot path: the guarded host action and its WebSocket routing.

These never actually reboot anything — subprocess.Popen is monkeypatched, and the
real guard (mock/non-Linux) keeps it inert in CI regardless.
"""

from types import SimpleNamespace

from fastapi.testclient import TestClient

import backend.api.ws as ws
import backend.system.control as control
from backend.server import create_app


def test_reboot_is_noop_under_mock(monkeypatch):
    # conftest forces RPC_FORCE_MOCK, so request_reboot must not shell out — this is
    # what keeps the button safe on the Mac, in tests, and on a CI runner.
    calls = []
    monkeypatch.setattr(control.subprocess, "Popen", lambda *a, **k: calls.append(a))
    assert control.request_reboot() is False
    assert calls == []


def test_reboot_runs_on_a_real_pi(monkeypatch):
    calls = []
    monkeypatch.setattr(control.subprocess, "Popen", lambda cmd, *a, **k: calls.append(cmd))
    monkeypatch.setattr(control.platform, "system", lambda: "Linux")
    monkeypatch.setattr(control, "settings", SimpleNamespace(allow_reboot=True, force_mock=False))
    assert control.request_reboot() is True
    assert calls == [control.REBOOT_COMMAND]


def test_reboot_disabled_by_config(monkeypatch):
    calls = []
    monkeypatch.setattr(control.subprocess, "Popen", lambda *a, **k: calls.append(a))
    monkeypatch.setattr(control.platform, "system", lambda: "Linux")
    monkeypatch.setattr(control, "settings", SimpleNamespace(allow_reboot=False, force_mock=False))
    assert control.request_reboot() is False
    assert calls == []


def test_system_reboot_message_routes_to_control(monkeypatch):
    calls = []
    monkeypatch.setattr(ws, "request_reboot", lambda: calls.append("reboot"))
    app = create_app()
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as sock:
            sock.send_json({"type": "hello"})
            sock.receive_json()
            sock.send_json({"type": "system", "action": "reboot"})
            # Round-trip a hello so the system message is guaranteed processed (one
            # socket handles messages in order).
            sock.send_json({"type": "hello"})
            sock.receive_json()
    assert calls == ["reboot"]


def test_unknown_system_action_does_not_reboot(monkeypatch):
    calls = []
    monkeypatch.setattr(ws, "request_reboot", lambda: calls.append("reboot"))
    app = create_app()
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as sock:
            sock.send_json({"type": "hello"})
            sock.receive_json()
            sock.send_json({"type": "system", "action": "shutdown"})
            sock.send_json({"type": "hello"})
            sock.receive_json()
    assert calls == []
