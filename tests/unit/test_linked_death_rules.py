"""The one rule helper left beside the engine: a run is over once every pair is dead."""
from server.linked_death_rules import update_run_over
from server.state import LinkStatus, MonInfo
from tests.unit.rules_fixture import seed_link_half, staged


def test_run_over_needs_both_balls_no_pending_half_and_no_live_pair(tmp_path):
    state = staged(tmp_path)
    a = MonInfo(key="1111:0000:19", level=5, species=25)
    b = MonInfo(key="2222:0000:07", level=5, species=7)
    assert seed_link_half(state, "a", "gift", a) is None and state.pending_captures["gift"]["a"].key == a.key
    link = seed_link_half(state, "b", "gift", b)
    assert link.status == LinkStatus.ALIVE and not state.pending_captures and not any(state.queued_commands.values())
    assert state.party_keys == {"a": {a.key}, "b": {b.key}} and not any(state.pokeballs_obtained.values())
    state.pokeballs_obtained = {"a": True, "b": True}
    update_run_over(state)
    assert not state.run_over  # a live pair keeps the run going
    link.status = LinkStatus.DEAD
    state.pokeballs_obtained["b"] = False
    update_run_over(state)
    assert not state.run_over  # an unproved ball is not a finished run
    state.pokeballs_obtained["b"] = True
    update_run_over(state)
    assert state.run_over
