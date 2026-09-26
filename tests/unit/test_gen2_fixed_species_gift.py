"""Gen 2 GSC fixed-species-gift bypass — OMP census follow-up (card O17, item 1).

server/adapters/gen2_gsc.py did not override `is_fixed_species_gift`, so it
inherited the base default False (server/adapters/base.py:86-98). Since U5,
Crystal/Gold/Silver runs use Gen2GSCAdapter, so under the species clause
(--species-clause/--species-lock) two halves that both receive the SAME
forced species from a fixed gift (Dragon's Den Dratini, Mt. Mortar Tyrogue,
the Route 35 guard's Spearow) could never form a pair: the clause saw two
identical species and force-fainted the second half, even though both
players were always guaranteed to receive that exact mon.

This is a state-level test, not just an adapter unit test, because the bug
lives in the interaction: server/state.py:~1495 remaps the capture's area_id
through `gift_link_area` BEFORE the species-clause check at ~1672 consults
`is_fixed_species_gift`, so on gsc the id the clause actually sees is the
gift-namespaced form (e.g. "gift_dragons_den"), not the raw pack area_id.
"""

from server.adapters.gen2_gsc import Gen2GSCAdapter
from server.state import AreaStatus, LinkStatus, SoulLinkState


def _new_state(tmp_path, monkeypatch, title="crystal"):
    monkeypatch.setattr("server.state.LINKS_PATH", str(tmp_path / "links.json"))
    state = SoulLinkState(species_lock=True, adapter=Gen2GSCAdapter(title))
    state.pokeballs_obtained = {"a": True, "b": True}
    return state


def test_fixed_species_gift_pair_forms_under_species_clause(tmp_path, monkeypatch):
    """Both players' Dragon's Den Dratini are guaranteed identical -- must link."""
    state = _new_state(tmp_path, monkeypatch)
    state.handle_event("a", {"event": "capture", "key": "0001:1111:93",
                              "area_id": "dragons_den", "level": 15,
                              "species_id": 147, "gift": True})
    cmds_b = state.handle_event("b", {"event": "capture", "key": "0002:2222:93",
                                       "area_id": "dragons_den", "level": 15,
                                       "species_id": 147, "gift": True})
    assert not any(c.get("cmd") == "force_faint" for c in cmds_b), (
        "fixed-species gift (Dragon's Den Dratini) must bypass the species clause"
    )
    assert state.area_states.get("gift_dragons_den") == AreaStatus.LINKED
    assert len(state.links) == 1
    assert state.links[0].status == LinkStatus.ALIVE


def test_non_fixed_gift_area_still_enforces_species_clause(tmp_path, monkeypatch):
    """Control: a player-choice gift (Goldenrod Bill's Eevee / Game Corner) is
    NOT fixed-species -- both sides picking the same species must still trip
    the clause, proving the bypass isn't over-broad."""
    state = _new_state(tmp_path, monkeypatch)
    state.handle_event("a", {"event": "capture", "key": "0003:3333:85",
                              "area_id": "goldenrod_city", "level": 20,
                              "species_id": 133, "gift": True})
    cmds_b = state.handle_event("b", {"event": "capture", "key": "0004:4444:85",
                                       "area_id": "goldenrod_city", "level": 20,
                                       "species_id": 133, "gift": True})
    assert any(c.get("cmd") == "force_faint" for c in cmds_b), (
        "player-choice gift areas must still enforce the species clause"
    )
    assert len(state.links) == 0


def test_fixed_species_gift_areas_derived_from_packs():
    """Direct adapter-level check on the derivation itself (Item 1 census fact).

    Crystal-only Dragon's Den Dratini makes Crystal's set one larger than
    Gold/Silver's; state.py consults only the RUN adapter even for a
    Crystal<->Gold pair (server/state.py ~1672), so the adapter answers the
    UNION across all three packs -- every title's adapter must recognize
    every title's fixed gift, not just its own.
    """
    for title in ("crystal", "gold", "silver"):
        adapter = Gen2GSCAdapter(title)
        assert adapter.is_fixed_species_gift("gift_dragons_den")
        assert adapter.is_fixed_species_gift("gift_mt_mortar")
        assert adapter.is_fixed_species_gift("gift_route_35")
        # Player-choice / multi-species gift areas remain unlocked.
        assert not adapter.is_fixed_species_gift("gift_goldenrod_city")
        assert not adapter.is_fixed_species_gift("gift_celadon_city")
        assert not adapter.is_fixed_species_gift("gift_new_bark_town")
        assert not adapter.is_fixed_species_gift("gift_daycare")
        assert not adapter.is_fixed_species_gift(None)
