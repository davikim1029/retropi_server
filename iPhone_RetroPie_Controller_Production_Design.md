# iPhone Virtual Gamepad for RetroPie
# Production Engineering Design Document (PEDD)

Version: 1.0
Status: Architecture / Implementation Specification

---

# 1. Executive Summary

This project creates a browser-based virtual game controller that allows an iPhone to function as a low-latency gamepad for RetroPie running on a Raspberry Pi.

The solution must:

- Require no native iOS application
- Operate entirely through Safari
- Automatically integrate with RetroPie
- Present itself as a native Linux gamepad
- Support multi-touch gameplay
- Recover automatically from disconnects
- Support future controller profiles

Target systems:

- Raspberry Pi 3B+
- Raspberry Pi 4
- Raspberry Pi 5
- RetroPie
- RetroArch
- Linux kernel with uinput support

---

# 2. System Context

## Problem

Traditional RetroPie installations require:

- USB controller
- Bluetooth controller
- Keyboard

Users often already possess a smartphone.

This project converts that smartphone into a first-class game controller.

---

# 3. Architecture Overview

```text
┌─────────────────────────┐
│         iPhone          │
│   Safari Controller UI  │
└───────────┬─────────────┘
            │
            │ WebSocket
            │
┌───────────▼─────────────┐
│   Controller Gateway    │
│      FastAPI Server     │
└───────────┬─────────────┘
            │
            ▼
┌─────────────────────────┐
│   Session Management    │
└───────────┬─────────────┘
            ▼
┌─────────────────────────┐
│ Input State Engine      │
└───────────┬─────────────┘
            ▼
┌─────────────────────────┐
│ Linux Virtual Gamepad   │
│ python-uinput           │
└───────────┬─────────────┘
            ▼
┌─────────────────────────┐
│ RetroPie / RetroArch    │
└─────────────────────────┘
```

---

# 4. Design Principles

1. Browser First
2. Low Latency
3. Headless Operation
4. Automatic Configuration
5. Platform Independence
6. Extensible Controller Definitions
7. Fail Safe Input Handling

---

# 5. Non Functional Requirements

## Latency

Target:

<20ms

Maximum:

<50ms

## Availability

99.5% uptime

## Recovery

Reconnect within 3 seconds

## Memory

<100 MB RSS

## CPU

<5% Pi 4 utilization

---

# 6. Component Design

## Web Frontend

Responsibilities:

- Render Game Boy layout
- Capture touch events
- Maintain button state
- Handle reconnection
- Send delta updates

Files:

```text
index.html
controller.css
controller.js
```

---

## API Gateway

Responsibilities:

- Serve static assets
- Accept websocket sessions
- Authenticate clients
- Dispatch controller events

Technology:

FastAPI + Uvicorn

---

## Input State Engine

Purpose:

Prevent inconsistent controller states.

Example:

```text
RIGHT pressed
A pressed
RIGHT released
```

Result:

```text
A remains pressed
```

State model:

```python
{
    "UP": False,
    "DOWN": False,
    "LEFT": False,
    "RIGHT": True,
    "A": True,
    "B": False,
    "START": False,
    "SELECT": False
}
```

---

## Virtual Controller Driver

Implemented using:

python-uinput

Creates:

```text
iPhone Virtual Gamepad
```

Kernel-visible gamepad device.

RetroPie sees:

```text
/dev/input/eventX
```

---

# 7. Controller Profiles

## Game Boy

```text
UP
DOWN
LEFT
RIGHT

A
B

START
SELECT
```

## NES

```text
UP
DOWN
LEFT
RIGHT

A
B

START
SELECT
```

## SNES

```text
UP
DOWN
LEFT
RIGHT

A
B
X
Y

L
R

START
SELECT
```

Profiles loaded from YAML.

---

# 8. WebSocket Protocol

## Session Establishment

Client:

```json
{
  "type":"hello",
  "protocol":"1.0",
  "controller":"gameboy"
}
```

Server:

```json
{
  "type":"accepted",
  "session_id":"uuid"
}
```

---

## Button Down

```json
{
  "type":"button_down",
  "button":"A",
  "timestamp":123456
}
```

---

## Button Up

```json
{
  "type":"button_up",
  "button":"A",
  "timestamp":123460
}
```

---

## Heartbeat

```json
{
  "type":"heartbeat"
}
```

Interval:

2 seconds

---

# 9. Multi-Touch Design

Requirements:

```text
Right + A
Right + B
Up + A
Up + Right + A
```

Controller cannot rely on click events.

Must track active touches.

Algorithm:

1. Touch starts
2. Button added to active set
3. State diff generated
4. Delta transmitted

---

# 10. Security Model

Threats:

- Unauthorized controller access
- Event flooding
- Session hijacking

Controls:

### Pairing Token

Random token generated:

```text
ABCD-1234
```

Required during first connection.

### Session Expiration

15 minute inactivity timeout.

### Rate Limiting

Maximum:

500 events/sec

### Origin Validation

Only approved origins accepted.

---

# 11. Auto Discovery

At startup:

1. Determine local IP
2. Generate QR code
3. Advertise hostname

Example:

```text
http://retropie.local:8080
```

Fallback:

```text
http://192.168.1.100:8080
```

---

# 12. Startup Sequence

```text
systemd starts service
        ↓
FastAPI starts
        ↓
uinput gamepad created
        ↓
RetroPie detects device
        ↓
QR generated
        ↓
User scans
        ↓
Controller connected
```

---

# 13. Failure Handling

## WiFi Loss

Behavior:

- Controller disconnected
- Buttons released immediately
- Reconnect attempts begin

---

## Browser Crash

Behavior:

- Session timeout
- Force release all buttons

---

## Server Restart

Behavior:

- Recreate gamepad
- Restore controller profile

---

# 14. RetroPie Integration

Autoconfig generated:

```ini
input_device = "iPhone Virtual Gamepad"
input_driver = "udev"

input_a_btn = "0"
input_b_btn = "1"

input_start_btn = "2"
input_select_btn = "3"
```

Generated automatically during install (and on server startup). The implemented mapping numbers
buttons by ascending evdev code, so for the Game Boy profile `select = 2` and `start = 3` (the udev
ordering RetroArch's joypad driver uses), not the placeholder values above.

**Exit-to-EmulationStation hotkey.** Profiles may declare `hotkeys:` (action → button). The Game
Boy profile adds a dedicated `MENU` button (`BTN_MODE`) wired as both `input_enable_hotkey_btn` and
`input_exit_emulator_btn`, so a single MENU tap quits the game back to the launcher. Same-button
enable+exit is required because RetroPie's global `retroarch.cfg` defines an enable-hotkey that
otherwise gates joypad hotkeys off.

**EmulationStation menu navigation.** RetroArch autoconfig only covers in-game input; ES (the
launcher) reads its own `es_input.cfg`. The installer merges a joystick `<inputConfig>` for the
virtual pad into `es_input.cfg` (preserving the keyboard entry), matched by SDL2's name-derived
GUID, so the pad drives the menus without the manual ES "Configure Input" step.

---

# 15. Installation Architecture

Installer performs:

1. Dependency installation (incl. `joystick`/`jstest` + `evtest` diagnostics)
2. uinput validation
3. Service registration
4. RetroPie profile creation (RetroArch autoconfig + EmulationStation `es_input.cfg` joystick map)
5. Firewall configuration
6. Health-check registration

---

# 16. systemd Service

```ini
[Unit]
Description=iPhone Controller Service
After=network.target

[Service]
Restart=always
RestartSec=3
User=pi

ExecStart=/usr/bin/python3 app.py

[Install]
WantedBy=multi-user.target
```

---

# 17. Logging Strategy

Levels:

```text
DEBUG
INFO
WARN
ERROR
CRITICAL
```

Log destinations:

```text
stdout
systemd journal
rotating file
```

---

# 18. Health Monitoring

Endpoint:

```text
/health
```

Returns:

```json
{
  "status":"healthy",
  "connections":1,
  "uptime":86400
}
```

---

# 19. Testing Strategy

## Unit Tests

- Input state transitions
- Button mapping
- Session handling

## Integration Tests

- WebSocket connectivity
- uinput device creation
- RetroPie detection

## Load Tests

Simulate:

1000 events/sec

## End-to-End Tests

Safari -> RetroPie

---

# 20. Future Roadmap

Phase 2

- Multiplayer support
- Landscape controller layouts
- Analog sticks
- Vibration support
- Custom skins

Phase 3

- Accelerometer controls
- Gyroscope controls
- Cloud configuration sync
- WebRTC transport

Phase 4

- Multiple simultaneous iPhones
- Tournament mode
- Companion management UI

---

# 21. Recommended Repository Structure

```text
iphone-retropie-controller/

├── backend/
│   ├── api/
│   ├── sessions/
│   ├── input/
│   ├── profiles/
│   └── discovery/
│
├── frontend/
│   ├── html/
│   ├── css/
│   └── js/
│
├── tests/
│
├── scripts/
│
├── docs/
│
├── deployments/
│
└── systemd/
```

---

# 22. Acceptance Criteria

A deployment is considered production-ready when:

- iPhone connects without app installation
- Controller appears automatically in RetroPie
- Multi-touch works correctly
- Input latency remains below 20ms
- Reconnection succeeds automatically
- No stuck-button conditions exist
- Service survives reboot
- Service survives network interruptions

---

END OF DOCUMENT
