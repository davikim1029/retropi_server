#!/usr/bin/env python3
"""Generate the RetroArch autoconfig for a controller profile.

The server already writes this on startup; this CLI is for inspecting it or
installing it by hand (e.g. as part of a future installer).

Examples:
  python scripts/generate_autoconfig.py                       # print gameboy cfg
  python scripts/generate_autoconfig.py --profile gameboy
  python scripts/generate_autoconfig.py --dir /opt/retropie/configs/all/retroarch-joypads
  python scripts/generate_autoconfig.py --output ./iphone.cfg
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Make `backend` importable when run as a standalone script.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.profiles.autoconfig import (  # noqa: E402
    autoconfig_filename,
    generate_autoconfig,
    write_autoconfig,
)
from backend.profiles.loader import load_profile  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="gameboy", help="profile name (default: gameboy)")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--dir", help="write '<device>.cfg' into this directory")
    group.add_argument("--output", help="write to this exact file path")
    args = parser.parse_args()

    profile = load_profile(args.profile)

    if args.dir:
        path = write_autoconfig(profile, args.dir)
        if path is None:
            print(f"directory not found or unwritable: {args.dir}", file=sys.stderr)
            return 1
        print(f"wrote {path}")
        return 0

    if args.output:
        out = Path(args.output)
        out.write_text(generate_autoconfig(profile))
        print(f"wrote {out}")
        return 0

    print(f"# {autoconfig_filename()}")
    print(generate_autoconfig(profile), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
