from backend.input.driver import create_driver
from backend.profiles.loader import load_profile


def full_state(profile, **down):
    state = {button: False for button in profile.buttons}
    state.update({button: True for button in down})
    return state


def open_driver():
    profile = load_profile("gameboy")
    driver = create_driver(force_mock=True)
    driver.open(profile)
    return profile, driver


def test_hat_resolution_single_direction():
    profile, driver = open_driver()
    driver.sync(full_state(profile, UP=True))
    assert driver.state[("hat", "HAT0Y")] == -1


def test_hat_recenters_on_release():
    profile, driver = open_driver()
    driver.sync(full_state(profile, UP=True))
    driver.sync(full_state(profile))
    assert driver.state[("hat", "HAT0Y")] == 0


def test_opposing_directions_cancel():
    profile, driver = open_driver()
    driver.sync(full_state(profile, UP=True, DOWN=True))
    assert driver.state[("hat", "HAT0Y")] == 0


def test_key_emits_on_and_off():
    profile, driver = open_driver()
    driver.sync(full_state(profile, A=True))
    assert (("key", "BTN_SOUTH"), 1) in driver.events
    assert driver.state[("key", "BTN_SOUTH")] == 1

    driver.sync(full_state(profile))
    assert driver.state[("key", "BTN_SOUTH")] == 0
