import xml.etree.ElementTree as ET

from backend.input.driver import DEVICE_NAME
from backend.profiles.es_input import (
    ES_DEVICE_GUID,
    build_inputconfig,
    merge_es_input,
)
from backend.profiles.loader import load_profile

# A keyboard-only es_input.cfg, like a fresh RetroPie image before the pad is added.
KEYBOARD_ONLY = """<?xml version="1.0"?>
<inputList>
  <inputAction type="onfinish">
    <command>/opt/retropie/supplementary/emulationstation/scripts/inputconfiguration.sh</command>
  </inputAction>
  <inputConfig type="keyboard" deviceName="Keyboard" deviceGUID="-1">
    <input name="a" type="key" id="1073742049" value="1"/>
    <input name="up" type="key" id="119" value="1"/>
  </inputConfig>
</inputList>
"""


def test_inputconfig_matches_working_pi():
    el = build_inputconfig(load_profile("gameboy"))
    assert el.get("type") == "joystick"
    assert el.get("deviceName") == DEVICE_NAME
    assert el.get("deviceGUID") == ES_DEVICE_GUID

    by_name = {i.get("name"): i.attrib for i in el.findall("input")}
    # Buttons match the RetroArch autoconfig's evdev-ascending ordering.
    assert by_name["a"] == {"name": "a", "type": "button", "id": "0", "value": "1"}
    assert by_name["b"] == {"name": "b", "type": "button", "id": "1", "value": "1"}
    assert by_name["select"] == {"name": "select", "type": "button", "id": "4", "value": "1"}
    assert by_name["start"] == {"name": "start", "type": "button", "id": "5", "value": "1"}
    # D-pad uses SDL hat bitmask: up=1, right=2, down=4, left=8.
    assert by_name["up"] == {"name": "up", "type": "hat", "id": "0", "value": "1"}
    assert by_name["right"] == {"name": "right", "type": "hat", "id": "0", "value": "2"}
    assert by_name["down"] == {"name": "down", "type": "hat", "id": "0", "value": "4"}
    assert by_name["left"] == {"name": "left", "type": "hat", "id": "0", "value": "8"}


def test_merge_preserves_keyboard_and_adds_joystick(tmp_path):
    cfg = tmp_path / "es_input.cfg"
    cfg.write_text(KEYBOARD_ONLY)

    assert merge_es_input(load_profile("gameboy"), cfg) == cfg

    root = ET.fromstring(cfg.read_text())
    kinds = {(c.get("type"), c.get("deviceName")) for c in root.findall("inputConfig")}
    assert ("keyboard", "Keyboard") in kinds       # keyboard map untouched
    assert ("joystick", DEVICE_NAME) in kinds      # our pad added
    assert root.find("inputAction") is not None     # onfinish action preserved


def test_merge_is_idempotent(tmp_path):
    cfg = tmp_path / "es_input.cfg"
    cfg.write_text(KEYBOARD_ONLY)

    merge_es_input(load_profile("gameboy"), cfg)
    first = cfg.read_text()
    merge_es_input(load_profile("gameboy"), cfg)
    second = cfg.read_text()

    assert first == second  # stable output, no drift on re-run
    root = ET.fromstring(second)
    joys = [c for c in root.findall("inputConfig") if c.get("deviceName") == DEVICE_NAME]
    assert len(joys) == 1  # replaced, not duplicated


def test_merge_skips_missing_file(tmp_path):
    assert merge_es_input(load_profile("gameboy"), tmp_path / "nope.cfg") is None
