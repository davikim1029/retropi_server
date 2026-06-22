"""Scan the RetroPie ROM library for launchable Game Boy Color / GBA titles.

Pure filesystem + gamelist.xml parsing (no hardware), so it's fully unit-testable
on the Mac. The launcher turns these into a browse grid; manager.py maps a pick to
the emulators.cfg launch command.
"""

from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from pathlib import Path

# Strip a leading ROM-catalog prefix like "0907 - " / "0940_-_" that EmulationStation
# never scraped away, and turn underscores into spaces, so "0907 - Pokemon - Ruby
# Version" -> "Pokemon - Ruby Version" and "0940_-_golden_sun" -> "golden sun".
_CATALOG_PREFIX = re.compile(r"^\s*\d{2,4}\s*[-_]+\s*")


def _clean_name(raw: str) -> str:
    name = _CATALOG_PREFIX.sub("", raw).replace("_", " ").strip()
    return name or raw

# system -> playable ROM extensions (lowercase). Save/state/zip files are excluded.
SYSTEM_EXTS: dict[str, set[str]] = {
    "gbc": {".gbc", ".gb"},
    "gba": {".gba"},
}
SYSTEM_LABEL = {"gbc": "Game Boy", "gba": "Game Boy Advance"}

DEFAULT_ROMS_DIR = Path(os.environ.get("RPC_ROMS_DIR", str(Path.home() / "RetroPie/roms")))
DEFAULT_GAMELISTS_DIR = Path(
    os.environ.get("RPC_GAMELISTS_DIR", str(Path.home() / ".emulationstation/gamelists"))
)


@dataclass(frozen=True)
class Game:
    system: str
    name: str
    rom_path: str
    filename: str

    def as_dict(self) -> dict:
        d = asdict(self)
        d["system_label"] = SYSTEM_LABEL.get(self.system, self.system)
        return d


def _gamelist_names(gamelists_dir: Path, system: str) -> dict[str, str]:
    """basename(path) -> display name, from <system>/gamelist.xml (best-effort)."""
    f = gamelists_dir / system / "gamelist.xml"
    names: dict[str, str] = {}
    if not f.is_file():
        return names
    try:
        root = ET.parse(f).getroot()
    except ET.ParseError:
        return names
    for g in root.findall("game"):
        path = (g.findtext("path") or "").strip()
        name = (g.findtext("name") or "").strip()
        if path and name:
            names[os.path.basename(path)] = name
    return names


def scan_system(system: str, roms_dir: Path, gamelists_dir: Path) -> list[Game]:
    exts = SYSTEM_EXTS.get(system, set())
    d = roms_dir / system
    if not d.is_dir():
        return []
    names = _gamelist_names(gamelists_dir, system)
    games: list[Game] = []
    for entry in sorted(d.iterdir(), key=lambda p: p.name.lower()):
        if not entry.is_file() or entry.suffix.lower() not in exts:
            continue
        games.append(
            Game(
                system=system,
                name=_clean_name(names.get(entry.name) or entry.stem),
                rom_path=str(entry),
                filename=entry.name,
            )
        )
    return games


def scan_games(
    roms_dir: Path | str | None = None,
    gamelists_dir: Path | str | None = None,
    systems: tuple[str, ...] = ("gbc", "gba"),
) -> list[Game]:
    roms = Path(roms_dir) if roms_dir else DEFAULT_ROMS_DIR
    lists = Path(gamelists_dir) if gamelists_dir else DEFAULT_GAMELISTS_DIR
    out: list[Game] = []
    for s in systems:
        out.extend(scan_system(s, roms, lists))
    return out
