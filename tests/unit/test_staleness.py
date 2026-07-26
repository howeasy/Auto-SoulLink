"""The dashboard must not claim a client is fine when it has gone quiet.

`connected_players[pid]["connected"]` only clears in the TCP reader's `finally` block, so a
crashed emulator, a stopped Lua script, or a slept laptop all leave the badge green indefinitely.
An AGE cannot lie the same way — it is derived from when the client last actually said something.
"""
import time

import pytest

from server.adapters.gen3_frlge import Gen3Adapter
from server.server import STALE_AFTER_SECS, SLinkServer, _age_label, _age_secs


@pytest.fixture
def srv(tmp_path):
    s = SLinkServer(data_dir=str(tmp_path))
    s.state.adapter = s.adapter = Gen3Adapter(is_rr=True)
    return s


def test_age_is_none_when_the_player_has_never_been_seen():
    assert _age_secs(None) is None
    assert _age_label(None) == "—"


def test_age_counts_from_the_last_message():
    assert _age_secs(time.time() - 5) in (5, 6)
    assert _age_secs(time.time() + 100) == 0      # clock skew must not render negative


@pytest.mark.parametrize("age,label", [
    (0, "0s ago"), (9, "9s ago"), (59, "59s ago"),
    (60, "1m ago"), (3599, "59m ago"), (3600, "1h ago"),
])
def test_age_label_reads_naturally(age, label):
    assert _age_label(age) == label


def test_status_dict_exposes_the_age(srv):
    srv.connected_players["a"] = {"connected": True, "last_event": "tick",
                                  "last_seen": "12:00:00", "last_seen_ts": time.time() - 3}
    assert srv._build_status_dict()["players"]["a"]["last_seen_age"] in (3, 4)


def test_a_silent_client_is_called_out_even_though_it_still_reads_connected(srv):
    """The whole point: `connected` is still True here. Only the age reveals the truth."""
    srv.connected_players["a"] = {"connected": True, "last_event": "tick", "last_seen": "12:00:00",
                                  "last_seen_ts": time.time() - (STALE_AFTER_SECS + 5)}
    assert srv._build_status_dict()["players"]["a"]["connected"] is True
    html = srv._build_status_html()
    assert "stale-warn" in html
    assert "No data for" in html


def test_a_live_client_gets_no_warning(srv):
    srv.connected_players["a"] = {"connected": True, "last_event": "tick", "last_seen": "12:00:00",
                                  "last_seen_ts": time.time()}
    assert "stale-warn" not in srv._build_status_html()


def test_save_failure_is_surfaced_not_just_logged(srv):
    """A run that has stopped persisting looks identical to a healthy one without this."""
    assert "save-warn" not in srv._build_status_html()
    srv.state.save_failed = "[Errno 13] Permission denied: 'links.json'"
    html = srv._build_status_html()
    assert "save-warn" in html
    assert "Permission denied" in html


def test_save_failure_clears_once_a_write_succeeds(srv, tmp_path):
    srv.state.save_failed = "boom"
    srv.state._save()
    assert srv.state.save_failed == ""
