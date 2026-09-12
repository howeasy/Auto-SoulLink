"""P3: the Gen 1 translators drive the SHARED rule engine and produce the Gen 3-standard outcomes.

Every test builds a real SoulLinkState with the Gen 1 adapter and feeds it translated events.
Nothing here touches the parallel rule modules (capture_rules, no_catch_rules,
linked_death_rules, party_grant_rules, member_identity_rules).
"""
from server import gen1_semantic_events as ev
from server.adapters import get_adapter
from server.state import AreaStatus, LinkEntry, LinkStatus, MonInfo, SoulLinkState

KEY_A = "ABCD:30B8:4C"   # DVS:OTID:SPECIES (Gen 1 physical key)
KEY_B = "1234:5678:07"
KEY_A2 = "ABCD:30B8:4D"  # same DVs and OT, evolved species byte


def fresh_state(tmp_path, **options):
    return SoulLinkState(data_dir=str(tmp_path), adapter=get_adapter("gen1_rby", rom_type="Red"), **options)


def linked_state(tmp_path, **options):
    state = fresh_state(tmp_path, **options)
    entry = LinkEntry(area_id="route_1", a=MonInfo(key=KEY_A, level=5, species=0x4C),
                      b=MonInfo(key=KEY_B, level=7, species=0x07), status=LinkStatus.ALIVE)
    state.links.append(entry)
    state._index_entry(entry)
    state.area_states["route_1"] = AreaStatus.LINKED
    state.party_keys["a"].add(KEY_A)
    state.party_keys["b"].add(KEY_B)
    state.pokeballs_obtained = {"a": True, "b": True}
    state.party_size = {"a": 2, "b": 2}
    return state


def cmds(state, player):
    return [c["cmd"] for c in state.queued_commands[player]]


def find(state, player, cmd, key=None):
    return [c for c in state.queued_commands[player] if c.get("cmd") == cmd and (key is None or c.get("key") == key)]


def test_two_captures_in_one_area_form_a_live_link(tmp_path):
    state = fresh_state(tmp_path)
    state.pokeballs_obtained = {"a": True, "b": True}
    state.handle_event("a", ev.capture_event(key=KEY_A, area_id="route_1", species_id=0x4C, level=5, nickname="SQUIRT"))
    assert state.area_states["route_1"] in (AreaStatus.PENDING_A, AreaStatus.PENDING_B)
    assert state.find_link("a", KEY_A) is None
    state.handle_event("b", ev.capture_event(key=KEY_B, area_id="route_1", species_id=0x07, level=6))
    link = state.find_link("a", KEY_A)
    assert link is not None and link.status == LinkStatus.ALIVE and link.b.key == KEY_B
    assert state.area_states["route_1"] == AreaStatus.LINKED


def test_capture_event_carries_exactly_the_fields_the_engine_reads():
    event = ev.capture_event(key=KEY_A, area_id="route_1", species_id=76, level=5, nickname="X",
                             gift=True, in_box=True, max_hp=20)
    assert event == {"event": "capture", "key": KEY_A, "area_id": "route_1", "species_id": 76, "level": 5,
                     "nickname": "X", "gift": True, "in_box": True, "maxHP": 20}


def test_scripted_grant_translates_as_a_gift_and_links_under_the_gift_namespace(tmp_path):
    state = fresh_state(tmp_path)

    class Mon:
        species_id, level, nickname, max_hp = 0x99, 5, "BULBA", 20

    fact = {"kind": "scripted_grant", "key": KEY_A, "destination": "party"}
    # A grant received inside a real encounter area must not consume that area: it links under gift_<area>.
    event = ev.capture_from_fact(fact, Mon(), "route_1")
    assert event["gift"] is True and event["in_box"] is False
    state.handle_event("a", event)
    assert state.adapter.gift_link_area("route_1") == "gift_route_1"
    assert "gift_route_1" in state.area_states and "route_1" not in state.area_states
    assert state.pokeballs_obtained["a"] is False   # a gift never activates the ball gate
    # A grant in a gift area (the Oak's Lab starters) keeps that area id, exactly as the adapter says.
    assert state.adapter.is_gift_area("oaks_lab") and state.adapter.gift_link_area("oaks_lab") == "oaks_lab"


def test_no_catch_after_the_partner_caught_makes_a_dead_zone_and_retires_the_catch(tmp_path):
    state = fresh_state(tmp_path)
    state.pokeballs_obtained = {"a": True, "b": True}
    state.handle_event("a", ev.capture_event(key=KEY_A, area_id="route_2", species_id=0x4C, level=5))
    state.queued_commands = {"a": [], "b": []}
    state.handle_event("b", ev.no_catch_event(area_id="route_2", species_id=0xA5, level=3))
    assert state.area_states["route_2"] == AreaStatus.DEAD_ZONE
    assert find(state, "a", "force_faint", KEY_A), cmds(state, "a")
    assert find(state, "a", "memorialize", KEY_A), cmds(state, "a")


def test_faint_propagates_a_force_faint_and_both_memorials(tmp_path):
    state = linked_state(tmp_path)
    # handle_event RETURNS the caller's own commands; cross-player commands are queued for the partner.
    own = state.handle_event("a", ev.faint_event(key=KEY_A, level=9))
    link = state.find_link("a", KEY_A)
    assert link.status == LinkStatus.DEAD and link.a.level == 9
    assert find(state, "b", "force_faint", KEY_B), cmds(state, "b")
    assert find(state, "b", "memorialize", KEY_B), cmds(state, "b")
    assert any(c.get("cmd") == "memorialize" and c.get("key") == KEY_A for c in own), own


def test_faint_under_explode_mode_selects_force_explode_for_gen1(tmp_path):
    state = linked_state(tmp_path, explode_mode=True)
    assert state.adapter.supports_explode_mode() is True
    state.handle_event("a", ev.faint_event(key=KEY_A))
    assert find(state, "b", "force_explode", KEY_B), cmds(state, "b")
    assert not find(state, "b", "force_faint", KEY_B)


def test_faint_before_pokeballs_is_ignored(tmp_path):
    state = linked_state(tmp_path)
    state.pokeballs_obtained = {"a": False, "b": False}
    state.handle_event("a", ev.faint_event(key=KEY_A))
    assert state.find_link("a", KEY_A).status == LinkStatus.ALIVE
    assert not find(state, "b", "force_faint")


def test_evolution_key_change_migrates_the_link(tmp_path):
    state = linked_state(tmp_path)
    state.handle_event("a", ev.key_change_event(old_key=KEY_A, new_key=KEY_A2, reason="evolution",
                                                new_species=0x4D, new_nickname="WART"))
    link = state.find_link("a", KEY_A2)
    assert link is not None and link.status == LinkStatus.ALIVE and link.a.species == 0x4D
    assert state.find_link("a", KEY_A) is None
    assert KEY_A2 in state.party_keys["a"] and KEY_A not in state.party_keys["a"]


def test_whiteout_kills_partners_and_ends_the_run_when_nothing_is_boxed(tmp_path):
    state = linked_state(tmp_path)
    own = state.handle_event("a", ev.whiteout_event(area_id="route_1"))
    assert state.find_link("a", KEY_A).status == LinkStatus.DEAD
    assert find(state, "b", "force_faint", KEY_B), cmds(state, "b")
    assert state.run_over is True
    assert any(c.get("cmd") == "game_over" for c in own), own
    assert find(state, "b", "game_over"), cmds(state, "b")


def test_deposit_boxes_the_partner_half(tmp_path):
    state = linked_state(tmp_path)
    state.handle_event("a", ev.party_to_box_event(key=KEY_A, stats={"level": 5, "maxHP": 20}))
    assert find(state, "b", "box_mon", KEY_B), cmds(state, "b")
    assert KEY_A not in state.party_keys["a"]


def test_trainer_battle_start_is_a_no_op_without_rival_swap(tmp_path):
    state = linked_state(tmp_path)
    rival = sorted(state.adapter.rival_trainer_ids())[0]
    state.handle_event("a", ev.trainer_battle_start_event(trainer_id=rival))
    assert not find(state, "a", "replace_rival_team")


def test_trainer_battle_start_against_a_rival_swaps_in_the_partner_party(tmp_path):
    state = linked_state(tmp_path, rival_team_swap=True)
    rival = sorted(state.adapter.rival_trainer_ids())[0]
    blob_hex = "00" * state.adapter.party_blob_size()            # 66-byte RBY party record
    state._ingest_party_blobs("b", [{"slot": 0, "key": KEY_B, "species_id": 7, "level": 7, "blob_hex": blob_hex}])
    own = state.handle_event("a", ev.trainer_battle_start_event(trainer_id=rival))
    swap = [c for c in own if c.get("cmd") == "replace_rival_team"]
    assert swap, own
    assert swap[0]["blobs_hex"] == [blob_hex]


def test_memorialize_done_from_both_sides_retires_the_pair(tmp_path):
    state = linked_state(tmp_path)
    state.handle_event("a", ev.faint_event(key=KEY_A))
    state.handle_event("a", ev.memorialize_done_event(key=KEY_A))
    assert state.find_link("a", KEY_A).status == LinkStatus.DEAD
    state.handle_event("b", ev.memorialize_done_event(key=KEY_B))
    assert state.find_link("a", KEY_A).status == LinkStatus.MEMORIAL
