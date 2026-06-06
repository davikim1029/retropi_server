"""Test configuration.

Force the mock gamepad backend before any backend module is imported, so the suite
is deterministic on Linux/CI too (not just macOS where mock is already the default).
"""

import os

os.environ.setdefault("RPC_FORCE_MOCK", "1")
