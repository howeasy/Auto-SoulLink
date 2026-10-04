"""Capture and linking holes from the 2026-10-03 code sweep (OMP cx-dd09bde5), checked at the source first."""
from __future__ import annotations

from server.state import AreaStatus, LinkStatus, SoulLinkState
from tests.unit.test_state import SHINY_KEY, has_cmd, make_state_with_link


def test_a_rejected_bonus_catch_can_be_retried_without_dead_zoning_the_area(tmp_path, monkeypatch):
    """A clause-rejected bonus catch re-grants the encounter (unresolve_area) but never armed retry_areas, so the
    reroll's own no_catch dead-zoned the area. The two other clause rejections arm it."""
    monkeypatch.setattr("server.state.LINKS_PATH", str(tmp_path / "links.json"))
    state = SoulLinkState(species_lock=True)
    state.pokeballs_obtained = {"a": True, "b": True}
    state.party_size = {"a": 1, "b": 1}
    state.handle_event("a", {"event": "capture", "key": SHINY_KEY, "area_id": "route_1", "species_id": 25})
    state.handle_event("b", {"event": "area_enter", "area_id": "route_2"})
    cmds = state.handle_event("b", {"event": "capture", "key": "CAFE:BABE", "area_id": "route_2", "species_id": 26})
    assert has_cmd(cmds, "force_faint", "CAFE:BABE")
    state.handle_event("b", {"event": "no_catch", "area_id": "route_2", "species_id": 16})
    assert state.area_states.get("route_2") != AreaStatus.DEAD_ZONE


def test_a_replayed_capture_of_a_linked_mon_does_not_retire_it(tmp_path, monkeypatch):
    """The LINKED retire branch had no 'this key is already that link's half' check, unlike the pending branch: a
    replayed capture event for A's own linked mon queued force_faint + memorialize on a live pair."""
    monkeypatch.setattr("server.state.LINKS_PATH", str(tmp_path / "links.json"))
    state = make_state_with_link()
    cmds = state.handle_event("a", {"event": "capture", "key": "A:1", "area_id": "route_1", "species_id": 16})
    assert not has_cmd(cmds, "force_faint", "A:1") and not has_cmd(cmds, "memorialize", "A:1")
    assert state.links[0].status == LinkStatus.ALIVE
