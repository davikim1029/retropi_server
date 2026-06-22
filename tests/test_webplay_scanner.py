"""Scanner + launcher API tests — temp ROM dir + sample gamelist, no hardware."""

from fastapi.testclient import TestClient

from webplay.scanner import scan_games
from webplay.server import create_app


def _make_library(tmp_path):
    roms = tmp_path / "roms"
    (roms / "gbc").mkdir(parents=True)
    (roms / "gba").mkdir(parents=True)
    (roms / "gbc" / "Pokemon Gold.gbc").write_bytes(b"x")
    (roms / "gbc" / "Pokemon Gold.srm").write_bytes(b"save")  # excluded (not a ROM)
    (roms / "gba" / "0171 - Golden Sun.gba").write_bytes(b"x")
    (roms / "gba" / "notes.txt").write_bytes(b"x")  # excluded

    lists = tmp_path / "gamelists"
    (lists / "gba").mkdir(parents=True)
    (lists / "gba" / "gamelist.xml").write_text(
        "<gameList><game><path>./0171 - Golden Sun.gba</path>"
        "<name>0171 - Golden Sun</name></game></gameList>"  # catalog prefix stripped by scanner
    )
    return roms, lists


def test_scan_filters_and_names(tmp_path):
    roms, lists = _make_library(tmp_path)
    games = scan_games(roms, lists)
    by_file = {g.filename: g for g in games}

    assert set(by_file) == {"Pokemon Gold.gbc", "0171 - Golden Sun.gba"}  # saves/txt out
    assert by_file["0171 - Golden Sun.gba"].name == "Golden Sun"          # from gamelist
    assert by_file["Pokemon Gold.gbc"].name == "Pokemon Gold"             # filename stem
    assert by_file["Pokemon Gold.gbc"].system == "gbc"


def test_games_api(tmp_path, monkeypatch):
    roms, lists = _make_library(tmp_path)
    monkeypatch.setenv("RPC_ROMS_DIR", str(roms))
    monkeypatch.setenv("RPC_GAMELISTS_DIR", str(lists))
    # scanner reads env at call time via its DEFAULT_* only at import; pass through args
    import webplay.scanner as sc

    monkeypatch.setattr(sc, "DEFAULT_ROMS_DIR", roms)
    monkeypatch.setattr(sc, "DEFAULT_GAMELISTS_DIR", lists)

    with TestClient(create_app()) as client:
        data = client.get("/api/games").json()
        names = sorted(g["name"] for g in data["games"])
        assert names == ["Golden Sun", "Pokemon Gold"]
        assert data["games"][0]["system_label"] in ("Game Boy", "Game Boy Advance")

        # state defaults to idle when no runner has written a state file
        assert client.get("/api/state").json()["status"] == "idle"

        # launch with no runner FIFO -> 503 (reported, not hung)
        r = client.post("/api/launch", json={"system": "gbc", "rom": "/x.gbc"})
        assert r.status_code == 503
