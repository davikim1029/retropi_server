"""Optional live-video streaming for the controller's split-screen "stream mode".

This package is deliberately self-contained and decoupled from the controller
(``backend/input`` + ``backend/api/ws.py``): video capture runs in its own module
and its own subprocess, so if streaming misbehaves the WebSocket gamepad keeps
working and the two can be diagnosed independently. Video is opt-in
(``RPC_VIDEO_ENABLED``) and off by default.
"""
