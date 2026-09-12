"""The no-catch outcome names stay the live coordinator's clause decisions; the engine records them."""

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
def test_decision_names_the_legacy_area_pending_and_species_outcome_without_touching_state(runtime, case, outcome):  # noqa: F811
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
    before = base.document()
    assert no_catch_rules.decision(base, "a", area, 25, activated=True) == outcome
    assert base.document() == before  # a pure name: the shared engine owns the state change
    legacy = copy.deepcopy(base)
    legacy._handle_no_catch("a", {"area_id": area, "species_id": 25, "level": 7})
    assert (legacy.area_states.get(area) == AreaStatus.DEAD_ZONE) == (outcome == "dead_zone")
