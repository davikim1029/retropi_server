"""Scan ROM libraries for launchable Game Boy Color / GBA titles.

Pure filesystem + gamelist.xml parsing (no hardware), so it's fully unit-testable
on the Mac. The launcher turns these into a browse grid; manager.py maps a pick to
the emulators.cfg launch command.
"""

from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

# Strip a leading ROM-catalog prefix like "0907 - " / "0940_-_" that EmulationStation
# never scraped away, and turn underscores into spaces, so "0907 - Pokemon - Ruby
# Version" -> "Pokemon - Ruby Version" and "0940_-_golden_sun" -> "golden sun".
_CATALOG_PREFIX = re.compile(r"^\s*\d{2,4}\s*[-_]+\s*")


def _clean_name(raw: str) -> str:
    name = _CATALOG_PREFIX.sub("", raw).replace("_", " ").strip()
    return name or raw


def _path(value: Path | str) -> Path:
    return Path(value).expanduser()


# system -> playable ROM extensions (lowercase). Save/state/zip files are excluded.
SYSTEM_EXTS: dict[str, set[str]] = {
    "gbc": {".gbc", ".gb"},
    "gba": {".gba"},
}
SYSTEM_LABEL = {"gbc": "Game Boy", "gba": "Game Boy Advance"}
REPO_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_ROMS_DIR = _path(os.environ.get("RPC_ROMS_DIR", str(Path.home() / "RetroPie/roms")))
DEFAULT_GAMELISTS_DIR = Path(
    os.environ.get("RPC_GAMELISTS_DIR", str(Path.home() / ".emulationstation/gamelists"))
).expanduser()
REPO_CUSTOM_GAMES_DIR = REPO_ROOT / "custom_games"
SIBLING_CUSTOM_GAMES_DIR = REPO_ROOT.parent / "custom_games"
DEFAULT_CUSTOM_GAMES_DIR = REPO_CUSTOM_GAMES_DIR


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


def _system_for_rom(path: Path) -> str | None:
    suffix = path.suffix.lower()
    for system, exts in SYSTEM_EXTS.items():
        if suffix in exts:
            return system
    return None


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


def scan_custom_games(
    custom_games_dir: Path | str,
    systems: tuple[str, ...] = ("gbc", "gba"),
) -> list[Game]:
    """Scan packaged custom ROMs, skipping development trees.

    `custom_games` is intentionally outside the RetroPie library, so infer the
    system from the ROM extension and recurse through project folders. A `dev`
    subtree may contain build outputs like pokecrystal.gbc; those are sources,
    not library-ready final artifacts, so they are excluded from the launcher.
    """
    root = _path(custom_games_dir)
    if not root.is_dir():
        return []

    allowed_systems = set(systems)
    games: list[Game] = []
    for current, dirs, files in os.walk(root):
        dirs[:] = sorted(
            (d for d in dirs if d != "dev" and not d.startswith(".")),
            key=str.lower,
        )
        for filename in sorted(files, key=str.lower):
            if filename.startswith("."):
                continue
            entry = Path(current) / filename
            system = _system_for_rom(entry)
            if system is None or system not in allowed_systems:
                continue
            games.append(
                Game(
                    system=system,
                    name=_clean_name(entry.stem),
                    rom_path=str(entry),
                    filename=entry.name,
                )
            )
    return games


def _default_custom_games_dirs() -> tuple[Path, ...]:
    override = os.environ.get("RPC_CUSTOM_GAMES_DIR")
    if override:
        return (_path(override),)

    dirs = []
    for path in (DEFAULT_CUSTOM_GAMES_DIR, SIBLING_CUSTOM_GAMES_DIR):
        if path not in dirs:
            dirs.append(path)
    return tuple(dirs)


def _custom_games_dirs(custom_games_dir: Path | str | Sequence[Path | str] | None) -> tuple[Path, ...]:
    if custom_games_dir is None:
        return _default_custom_games_dirs()
    if isinstance(custom_games_dir, (str, Path)):
        return (_path(custom_games_dir),)
    return tuple(_path(path) for path in custom_games_dir)


def scan_games(
    roms_dir: Path | str | None = None,
    gamelists_dir: Path | str | None = None,
    custom_games_dir: Path | str | Sequence[Path | str] | None = None,
    systems: tuple[str, ...] = ("gbc", "gba"),
) -> list[Game]:
    roms = _path(roms_dir) if roms_dir else DEFAULT_ROMS_DIR
    lists = _path(gamelists_dir) if gamelists_dir else DEFAULT_GAMELISTS_DIR
    out: list[Game] = []
    for s in systems:
        out.extend(scan_system(s, roms, lists))

    seen_custom_games: set[tuple[str, str]] = set()
    for custom in _custom_games_dirs(custom_games_dir):
        for game in scan_custom_games(custom, systems):
            key = (game.system, game.filename.lower())
            if key in seen_custom_games:
                continue
            seen_custom_games.add(key)
            out.append(game)
    return out
