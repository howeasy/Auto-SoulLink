"""KEY-SCOPE: mon identity is scoped per player (coordinator ruling after DUO-WAVE-D, 727c0976).

An in-game NPC-trade mon has fixed DVs and OT (Kyle's Onix is always 9666:BF1E:5F), so when
BOTH players make that trade they hold equal keys. The server accepted B's key_change and
then rejected A's as a collision, killing the pair (identity_lost). Two players may hold
equal keys; one player may not."""

from server.adapters.gen1_rby import Gen1Adapter
from server.state import LinkEntry, LinkStatus, MonInfo, SoulLinkState
from tests.unit.test_state_trade_uncertain import _gen1_applying, _mon, _tick

ONIX = "9666:BF1E:5F"
A1, B1, A2, B2 = "ABCD:1234:26", "1234:5678:15", "ABCD:1234:30", "1234:5678:31"


def _two_links(tmp_path):
    state = SoulLinkState(data_dir=str(tmp_path), adapter=Gen1Adapter())
    links = []
    for area, a, b in (("route_1", A1, B1), ("route_2", A2, B2)):
        e = LinkEntry(area_id=area, a=MonInfo(key=a, species=0x26, level=20),
                      b=MonInfo(key=b, species=0x15, level=20), status=LinkStatus.ALIVE)
        state.links.append(e)
        state._index_entry(e)
        state.party_keys["a"].add(a)
        state.party_keys["b"].add(b)
        links.append(e)
    state.pokeballs_obtained = {"a": True, "b": True}
    return state, links


def _npc_trade(state, pid, old):
    return state.handle_event(pid, {"event": "key_change", "old_key": old, "new_key": ONIX,
                                    "new_species": 0x5F, "reason": "npc_trade"})


def _named(cmds, name):
    return [c for c in cmds if c.get("cmd") == name]


def test_both_players_npc_trading_to_the_same_key_keep_two_live_distinct_links(tmp_path):
    state, (l1, l2) = _two_links(tmp_path)
    assert _named(_npc_trade(state, "b", B1), "key_change_ack")
    a_cmds = _npc_trade(state, "a", A2)
    assert _named(a_cmds, "key_change_ack") and not _named(a_cmds, "key_change_rejected")
    assert l1.status == l2.status == LinkStatus.ALIVE
    assert (l1.b.key, l2.a.key) == (ONIX, ONIX) and (l1.a.key, l2.b.key) == (A1, B2)
    assert state.entry_for("a", ONIX) is l2 and state.entry_for("b", ONIX) is l1
    assert ONIX in state.party_keys["a"] and ONIX in state.party_keys["b"]
    # a faint of A's Onix kills its own partner (B2), never B's Onix
    state.handle_event("a", {"event": "faint", "key": ONIX})
    b_cmds = state.handle_event("b", {"event": "noop"})
    assert [c["key"] for c in _named(b_cmds, "force_faint")] == [B2]
    assert l2.status == LinkStatus.DEAD and l1.status == LinkStatus.ALIVE


def test_the_presentation_cache_of_the_other_player_is_no_collision(tmp_path):
    from server.server import SLinkServer
    srv = SLinkServer(data_dir=str(tmp_path))
    srv.state, (l1, l2) = _two_links(tmp_path)
    srv.state.presentation_key_in_use = srv._presentation_key_in_use
    srv.party_details["b"][ONIX] = {"species_id": 0x5F, "level": 20}        # B already holds an Onix
    assert not _named(_npc_trade(srv.state, "a", A2), "key_change_rejected")
    srv.party_details["a"]["ABCD:1234:77"] = {"species_id": 1, "level": 5}   # A holds an unlinked twin
    rejected = srv.state.handle_event("a", {"event": "key_change", "old_key": A1,
                                            "new_key": "ABCD:1234:77", "reason": "evolution"})
    assert _named(rejected, "key_change_rejected"), "one player may not hold two equal keys"


def test_one_player_with_a_true_duplicate_is_still_a_collision(tmp_path):
    state, (l1, l2) = _two_links(tmp_path)
    cmds = state.handle_event("a", {"event": "key_change", "old_key": A1, "new_key": A2,
                                    "reason": "evolution"})
    assert _named(cmds, "key_change_rejected")
    assert l1.status == LinkStatus.DEAD and l1.cause == "identity_lost", "the U5 fail-closed rule stands"
    assert l2.status == LinkStatus.ALIVE


def test_a_capture_collides_only_with_the_same_players_keys(tmp_path):
    state, (l1, l2) = _two_links(tmp_path)
    ok = state._check_link_violation(MonInfo(key="ABCD:1234:40", species=1), MonInfo(key=A1, species=4))
    assert ok is None or "collision" not in ok[0].lower(), "B may hold a key A holds"
    bad = state._check_link_violation(MonInfo(key=A1, species=1), MonInfo(key="1234:5678:40", species=4))
    assert bad and "collision" in bad[0].lower() and bad[1] == "a"
    same = state._check_link_violation(MonInfo(key=ONIX, species=0x5F), MonInfo(key=ONIX, species=0x5F))
    assert same is None or "collision" not in same[0].lower()


def test_the_per_player_index_survives_a_reload(tmp_path):
    state, (l1, l2) = _two_links(tmp_path)
    _npc_trade(state, "b", B1)
    _npc_trade(state, "a", A2)
    back = SoulLinkState.load(data_dir=str(tmp_path), adapter=Gen1Adapter())
    assert back.entry_for("a", ONIX).area_id == "route_2"
    assert back.entry_for("b", ONIX).area_id == "route_1"


# ── a native trade moves a mon between players; the per-player index follows it ─────────────────

A_GETS, B_GETS = "1234:5678:15", "ABCD:1234:26"


def test_a_native_commit_moves_each_key_to_its_new_holders_index(tmp_path):
    state, entry, token = _gen1_applying(tmp_path)
    state.handle_event("a", {"event": "trade_done", "token": token, "new_key": A_GETS, "new_species": 0x15})
    state.handle_event("b", {"event": "trade_done", "token": token, "new_key": B_GETS, "new_species": 0x26})
    assert state.pending_trade is None
    assert state.entry_for("a", A_GETS) is entry and state.entry_for("b", B_GETS) is entry
    assert state.entry_for("a", B_GETS) is None and state.entry_for("b", A_GETS) is None


def test_a_split_indexes_the_copy_under_its_holder_only(tmp_path):
    state, entry, token = _gen1_applying(tmp_path)
    state.handle_event("a", {"event": "trade_done", "token": token, "new_key": A_GETS, "new_species": 0x15})
    state.handle_event("b", {"event": "trade_done", "token": token, "new_key": A_GETS, "new_species": 0x15})
    assert state.resolve_trade(token, "adopt") == (True, "")
    assert state.entry_for("a", A_GETS) is entry and state.entry_for("b", A_GETS) is entry
    assert state.entry_for("a", B_GETS) is None
    _tick(state, "a", _mon(A_GETS, 0x15))
    assert entry.status == LinkStatus.ALIVE


# ── KEY-SCOPE-2 (OMP cx-e13143c8) ────────────────────────────────────────────────────────────────

def test_a_key_in_the_partners_pending_shiny_bonus_is_no_collision(tmp_path):
    state, (l1, l2) = _two_links(tmp_path)
    state.pending_bonus["a"].append(ONIX)        # B caught a shiny ONIX; A's bonus encounter awaits
    cmds = _npc_trade(state, "a", A2)
    assert _named(cmds, "key_change_ack") and l2.status == LinkStatus.ALIVE
    assert list(state.pending_bonus["a"]) == [ONIX], "B's shiny key is not A's to migrate"
    state.pending_bonus["b"].append("ABCD:1234:77")   # A's own shiny, queued for B
    cmds = state.handle_event("a", {"event": "key_change", "old_key": A1, "new_key": "ABCD:1234:77"})
    assert _named(cmds, "key_change_rejected"), "A's own pending shiny still collides"


def _boxed_twin(state, key="1234:5678:15"):
    """A live link whose A half, boxed in A's PC, has the key A is about to receive."""
    twin = LinkEntry(area_id="route_9", a=MonInfo(key=key, species=0x15, level=9),
                     b=MonInfo(key="5555:5678:44", species=0x44, level=9), status=LinkStatus.ALIVE)
    state.links.append(twin)
    state._index_entry(twin)
    return twin


def test_a_trade_offer_is_refused_when_the_recipient_already_indexes_the_incoming_key(tmp_path):
    from tests.unit.test_state_trade_uncertain import _gen1_confirming
    state, _entry, _token, _ = _gen1_confirming(tmp_path)
    state.pending_trade = None
    assert state._eligible_trade_pairs("a"), "control"
    _boxed_twin(state)
    assert not state._eligible_trade_pairs("a") and not state._eligible_trade_pairs("b")
    ack = [c for c in state.handle_event("a", {"event": "trade_offer", "slot": 2})
           if c.get("cmd") == "trade_offer_ack"]
    assert ack == [{"cmd": "trade_offer_ack", "ok": False}] and state.pending_trade is None


def _assert_fail_closed(state, entry, twin):
    assert state.entry_for("a", A_GETS) is twin, "the existing link keeps A's index row"
    assert twin.status == LinkStatus.ALIVE
    assert entry.status == LinkStatus.DEAD and entry.cause == "identity_lost"


def test_a_commit_onto_a_key_the_taker_already_holds_retires_the_traded_pair(tmp_path):
    state, entry, token = _gen1_applying(tmp_path)
    twin = _boxed_twin(state)                     # appeared after the offer (the race)
    state.handle_event("a", {"event": "trade_done", "token": token, "new_key": A_GETS, "new_species": 0x15})
    state.handle_event("b", {"event": "trade_done", "token": token, "new_key": B_GETS, "new_species": 0x26})
    assert state.pending_trade is None
    _assert_fail_closed(state, entry, twin)


def test_a_split_onto_a_key_the_taker_already_holds_retires_the_traded_pair(tmp_path):
    state, entry, token = _gen1_applying(tmp_path)
    twin = _boxed_twin(state)
    state.handle_event("a", {"event": "trade_done", "token": token, "new_key": A_GETS, "new_species": 0x15})
    state.handle_event("b", {"event": "trade_done", "token": token, "new_key": A_GETS, "new_species": 0x15})
    assert state.resolve_trade(token, "adopt") == (True, "")
    _assert_fail_closed(state, entry, twin)
