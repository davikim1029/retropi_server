#!/usr/bin/env python3
"""Add/refresh the EmulationStation joystick mapping in es_input.cfg.

EmulationStation reads es_input.cfg to navigate its menus with a controller. A
fresh RetroPie image only maps the keyboard, so the iPhone pad can't drive the
launcher. This merges a joystick <inputConfig> for the virtual gamepad into an
existing es_input.cfg, preserving the keyboard entry (idempotent). install.sh runs
it; you can also run it by hand, or print the block for inspection.

Examples:
  python scripts/generate_es_input.py                     # print the joystick block
  python scripts/generate_es_input.py --profile gameboy
  python scripts/generate_es_input.py \
      --file /opt/retropie/configs/all/emulationstation/es_input.cfg
  python scripts/generate_es_input.py --file es_input.cfg --guid 000098a6...00
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Make `backend` importable when run as a standalone script.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.profiles.es_input import (  # noqa: E402
    ES_DEVICE_GUID,
    generate_es_input_block,
    merge_es_input,
)
from backend.profiles.loader import load_profile  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="gameboy", help="profile name (default: gameboy)")
    parser.add_argument("--file", help="es_input.cfg to merge into (default: print only)")
    parser.add_argument(
        "--guid", default=ES_DEVICE_GUID, help="SDL deviceGUID (default: name-derived)"
    )
    args = parser.parse_args()

    profile = load_profile(args.profile)

    if args.file:
        path = merge_es_input(profile, args.file, guid=args.guid)
        if path is None:
            print(f"es_input.cfg not found or unparseable: {args.file}", file=sys.stderr)
            return 1
        print(f"updated {path}")
        return 0

    print(generate_es_input_block(profile, guid=args.guid))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
