from backend.input.driver import create_driver
from backend.input.state import InputStateEngine
from backend.profiles.loader import load_profile


def make_engine():
    profile = load_profile("gameboy")
    driver = create_driver(force_mock=True)
    driver.open(profile)
    return profile, driver, InputStateEngine(profile, driver)


def test_last_write_wins_per_button():
    """Releasing RIGHT must not release a still-held A. (PEDD §6 invariant.)"""
    _, driver, engine = make_engine()
    engine.press("RIGHT")
    engine.press("A")
    engine.release("RIGHT")

    state = engine.state
    assert state["A"] is True
    assert state["RIGHT"] is False
    # A's button stays down at the driver; the d-pad axis recenters.
    assert driver.state[("key", "BTN_SOUTH")] == 1
    assert driver.state[("hat", "HAT0X")] == 0


def test_release_all_clears_everything():
    _, driver, engine = make_engine()
    engine.press("A")
    engine.press("UP")
    engine.release_all()

    assert not any(engine.state.values())
    assert driver.state[("key", "BTN_SOUTH")] == 0
    assert driver.state[("hat", "HAT0Y")] == 0


def test_unknown_button_ignored():
    _, _, engine = make_engine()
    before = engine.state
    engine.press("DOES_NOT_EXIST")
    assert engine.state == before


def test_repeated_press_is_noop_at_driver():
    _, driver, engine = make_engine()
    engine.press("A")
    emits_after_first = len(driver.events)
    engine.press("A")  # already down
    assert len(driver.events) == emits_after_first
