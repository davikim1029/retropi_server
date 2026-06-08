"""Startup discovery helpers: find the LAN address and show a scannable QR.

So a phone on the same WiFi can reach the controller without anyone typing an IP.
"""

from __future__ import annotations

import io
import logging
import socket

import qrcode

logger = logging.getLogger(__name__)


def local_ip() -> str:
    """Best-effort LAN IP of this host.

    Opens a UDP socket "toward" a public address — no packets are actually sent,
    but it makes the OS pick the interface/route it would use, whose local address
    is the LAN IP. Falls back to loopback if offline.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


def controller_urls(port: int) -> list[str]:
    """Candidate URLs to reach the controller, most specific first."""
    urls = [f"http://{local_ip()}:{port}"]
    hostname = socket.gethostname().split(".")[0]
    if hostname:
        urls.append(f"http://{hostname}.local:{port}")
    urls.append(f"http://gamepad:{port}")
    return urls


def qr_ascii(url: str) -> str:
    """Render ``url`` as an ASCII QR code suitable for printing to a terminal."""
    qr = qrcode.QRCode(border=1)
    qr.add_data(url)
    qr.make(fit=True)
    buffer = io.StringIO()
    qr.print_ascii(out=buffer, invert=True)
    return buffer.getvalue()
