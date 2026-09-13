"""The paired speed gate must not hide a live-session protocol failure."""

import pytest

from tests.live.test_gen1_free_service import classify_teardown_errors


def row(event, error, began):
    return {"event": event, "error": error, "began": began}


def test_only_post_finish_stale_control_is_an_expected_teardown_error():
    stale = row("control", "ProtocolError: connection does not own this player session", 11.0)
    assert classify_teardown_errors([stale], 10.0) == [stale]
    assert classify_teardown_errors([], 10.0) == []


@pytest.mark.parametrize("error", [
    row("control", "ProtocolError: connection does not own this player session", 9.9),
    row("observation", "ProtocolError: connection does not own this player session", 11.0),
    row("control", "JournalError: committed state changed", 11.0),
])
def test_live_or_non_teardown_errors_fail_the_speed_gate(error):
    with pytest.raises(AssertionError):
        classify_teardown_errors([error], 10.0)
