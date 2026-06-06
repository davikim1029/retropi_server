import pytest

from backend.profiles.loader import ProfileError, load_profile, parse_profile


def test_gameboy_loads():
    profile = load_profile("gameboy")
    assert profile.name == "gameboy"
    assert profile.display_name == "Game Boy"
    assert len(profile.buttons) == 11
    assert set(profile.buttons) == {
        "A", "B", "L", "R", "START", "SELECT", "UP", "DOWN", "LEFT", "RIGHT", "EXIT"
    }
    assert "BTN_SOUTH" in profile.key_codes()
    assert set(profile.hat_axes()) == {"HAT0X", "HAT0Y"}
    # EXIT is wired as the exit hotkey (single tap quits to EmulationStation).
    assert profile.hotkeys == {"enable": "EXIT", "exit": "EXIT"}


def test_hotkey_must_reference_existing_button():
    with pytest.raises(ProfileError):
        parse_profile(
            {
                "name": "x",
                "buttons": {"A": {"type": "key", "code": "BTN_SOUTH"}},
                "hotkeys": {"exit": "NOPE"},
            }
        )


def test_invalid_button_type():
    with pytest.raises(ProfileError):
        parse_profile({"name": "x", "buttons": {"A": {"type": "bogus"}}})


def test_key_binding_requires_code():
    with pytest.raises(ProfileError):
        parse_profile({"name": "x", "buttons": {"A": {"type": "key"}}})


def test_hat_value_must_be_plus_or_minus_one():
    with pytest.raises(ProfileError):
        parse_profile({"name": "x", "buttons": {"U": {"type": "hat", "axis": "HAT0Y", "value": 2}}})


def test_requires_buttons():
    with pytest.raises(ProfileError):
        parse_profile({"name": "x"})
