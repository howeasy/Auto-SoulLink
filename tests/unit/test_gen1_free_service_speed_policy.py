"""The owner's observed active 3x acceptance is narrow and explicit."""

from tests.live.test_gen1_free_service import (
    ACTIVE_THREE_X_MIN_FPS,
    MIN_FRACTION,
    PHASES,
    TARGET_FPS,
    phase_fps_floor,
)


def test_only_changed_inventory_three_x_uses_the_owner_accepted_floor():
    floors = {phase["name"]: phase_fps_floor(phase) for phase in PHASES}
    assert ACTIVE_THREE_X_MIN_FPS == 173.0
    assert floors["three_x"] == ACTIVE_THREE_X_MIN_FPS
    assert 173.116 >= floors["three_x"] > 172.999
    assert floors["one_x"] == TARGET_FPS * MIN_FRACTION
    assert floors["one_x_quiet"] == TARGET_FPS * MIN_FRACTION
    assert floors["three_x_quiet"] == TARGET_FPS * 300 / 100 * MIN_FRACTION
    assert floors["three_x_quiet"] > floors["three_x"]
