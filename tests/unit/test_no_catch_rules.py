"""Shared no-catch policy parity against the existing coordinator's clause rules."""

import copy

import pytest

from server import no_catch_rules
from server.state import AreaStatus, LinkEntry, LinkStatus, MonInfo
from tests.unit.test_gen1_wild_encounter import runtime  # noqa: F401


@pytest.mark.parametrize(
    "case,outcome",
    [
        ("ordinary", "dead_zone"),
        ("partner_capture", "dead_zone"),
        ("gift", "gift_area"),
        ("resolved", "resolved"),
        ("own_capture", "already_captured"),
        ("own_retry", "clause_retry"),
        ("peer_retry", "clause_retry"),
        ("already_notified", "dupe_already_notified"),
        ("own_alive_family", "species_clause"),
        ("peer_alive_family", "species_clause"),
        ("peer_pending_same_area", "species_clause"),
        ("peer_pending_other_area", "species_clause"),
    ],
)
def test_staged_policy_preserves_legacy_area_pending_and_species_decisions(runtime, case, outcome):  # noqa: F811
    base = runtime.state().rules
    base.pokeballs_obtained = {"a": True, "b": True}
    area = "pallet_town" if case == "gift" else "route_1"
    peer = MonInfo(key="peer", species=7, level=5, nickname="PEER")
    if case == "resolved":
        base.area_states[area] = AreaStatus.LINKED
    elif case == "own_capture":
        base.pending_captures[area] = {"a": peer}
    elif case == "partner_capture":
        base.pending_captures[area] = {"b": peer}
        base.party_keys["b"].add(peer.key)
    elif case in ("own_retry", "peer_retry"):
        base.retry_areas["a" if case == "own_retry" else "b"].add(area)
    elif case == "already_notified":
        base.dupe_notified_areas["a"].add(area)
    elif "family" in case:
        base.species_lock = True
        halves = {"a": MonInfo(key="one", species=25, level=5), "b": peer}
        if case == "peer_alive_family":
            halves["a"], halves["b"] = halves["b"], halves["a"]
        base.links.append(LinkEntry(area_id="route_2", status=LinkStatus.ALIVE, **halves))
    elif case.startswith("peer_pending"):
        base.species_lock = True
        base.pending_captures[area if case.endswith("same_area") else "route_2"] = {
            "b": MonInfo(key="peer", species=26, level=5)
        }
    legacy, modern = copy.deepcopy(base), copy.deepcopy(base)
    legacy._handle_no_catch("a", {"area_id": area, "species_id": 25, "level": 7})
    result = no_catch_rules.record(
        modern, "a", area, 25, 7, activated=True, occurred_at="2026-09-08T00:00:00+00:00"
    )
    assert result["outcome"] == outcome
    assert legacy.area_states == modern.area_states
    assert legacy.pending_captures == modern.pending_captures
    assert legacy.retry_areas == modern.retry_areas
    assert legacy.dupe_notified_areas == modern.dupe_notified_areas
    assert legacy.party_keys == modern.party_keys
    assert [
        (link.area_id, link.a, link.b, link.encounter_a, link.encounter_b, link.status, link.cause)
        for link in legacy.links
    ] == [
        (link.area_id, link.a, link.b, link.encounter_a, link.encounter_b, link.status, link.cause)
        for link in modern.links
    ]
    assert not any(modern.queued_commands.values())
    assert (result["retire"] is not None) == (case == "partner_capture")
