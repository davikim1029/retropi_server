from backend.profiles.autoconfig import (
    autoconfig_filename,
    generate_autoconfig,
    write_autoconfig,
)
from backend.profiles.loader import load_profile


def parse_cfg(text):
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or "=" not in line:
            continue
        key, _, value = line.partition("=")
        out[key.strip()] = value.strip().strip('"')
    return out


def test_gameboy_autoconfig_contents():
    cfg = parse_cfg(generate_autoconfig(load_profile("gameboy")))
    assert cfg["input_device"] == "iPhone Virtual Gamepad"
    assert cfg["input_driver"] == "udev"
    # Button indices by ascending evdev code: SOUTH<EAST<TL<TR<SELECT<START<MODE.
    assert cfg["input_a_btn"] == "0"       # BTN_SOUTH
    assert cfg["input_b_btn"] == "1"       # BTN_EAST
    assert cfg["input_l_btn"] == "2"       # BTN_TL
    assert cfg["input_r_btn"] == "3"       # BTN_TR
    assert cfg["input_select_btn"] == "4"  # BTN_SELECT
    assert cfg["input_start_btn"] == "5"   # BTN_START
    # D-pad hat directions.
    assert cfg["input_up_btn"] == "h0up"
    assert cfg["input_down_btn"] == "h0down"
    assert cfg["input_left_btn"] == "h0left"
    assert cfg["input_right_btn"] == "h0right"
    # EXIT (BTN_MODE) is the exit hotkey, not a game bind: enable + exit point at the
    # same button index (BTN_MODE sorts last among the profile's codes -> index 6).
    assert cfg["input_enable_hotkey_btn"] == "6"
    assert cfg["input_exit_emulator_btn"] == "6"
    assert "input_exit_btn" not in cfg  # EXIT's non-RetroPad name -> never a game bind


def test_filename_matches_device_name():
    assert autoconfig_filename() == "iPhone Virtual Gamepad.cfg"


def test_write_creates_file_in_existing_dir(tmp_path):
    path = write_autoconfig(load_profile("gameboy"), tmp_path)
    assert path is not None
    assert path.name == "iPhone Virtual Gamepad.cfg"
    assert path.read_text() == generate_autoconfig(load_profile("gameboy"))


def test_write_skips_missing_dir(tmp_path):
    missing = tmp_path / "nope"
    assert write_autoconfig(load_profile("gameboy"), missing) is None
