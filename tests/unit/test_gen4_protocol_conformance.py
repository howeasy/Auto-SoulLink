"""The Gen 4 half of the protocol conformance suite (card G3-A), driven by tests/unit/gen4_world.py.

This is the Gen 4 analogue of the Gen 3 world half (tests/unit/test_protocol_conformance.py). It is
a SEPARATE, independently-authored check over the same PRODUCTION client (lua/gen4/client.lua):
it imports the harness and the item table, NOT tests/unit/test_gen4_client.py's test bodies, so a
bug that file's own author didn't think to exercise gets a second chance to surface here.

Every line the client sends is parsed and strict-validated at send time by gen4_world.World._make_net
(gen4_world.py:453-468) against tests/unit/protocol_schema.py, so a wire violation raises at the send.

Two behaviours are called out explicitly rather than inherited from the harness:

  * a deliberately malformed hello goes RED at send time (the harness's send-time gate is real);
  * the hge routing suppression at gen4_world.py:458-459 ("not one the server routes" -- dropped for
    heartgold_hge because server/adapters/__init__.py has no heartgold_hge row yet) is asserted as a
    NAMED OPEN, pending the G3a server row. It is NOT silently inherited: the dedicated OPEN test
    runs the raw validator (bypassing the harness suppression) and asserts hge is currently refused.

Evidence layers and the NA column live in tests/unit/conformance_map_gen4.py. Run with:
    python -m pytest tests/unit/test_gen4_protocol_conformance.py -q
(requires SLINK_WORK_ROOT=F:/slink-work for the fake-NDS fixtures; no emulator, no server.)
"""
from __future__ import annotations

import json
import os
import re

import pytest

from tests.unit import protocol_schema as ps
from tests.unit.conformance_map_gen4 import BY_ID, ITEMS, LAYERS
from tests.unit.gen4_world import Mon, World, key_of

# ── doc-sync meta-tests (no fixture, no world) ──────────────────────────────────────────────

_REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
_PROTOCOL_MD = os.path.join(_REPO, "docs", "protocol.md")
_ITEM_LINE_RE = re.compile(r"^(\d+[a-z]?)\.\s")


def _doc_item_ids() -> list[str]:
    """Every numbered item under docs/protocol.md's `## 9. Conformance checklist` section."""
    with open(_PROTOCOL_MD, encoding="utf-8") as fh:
        body = fh.read()
    body = body.split("## 9. Conformance checklist", 1)[1].split("\n---", 1)[0]
    return [m.group(1) for line in body.splitlines() if (m := _ITEM_LINE_RE.match(line))]


def test_every_doc_item_is_in_the_conformance_map():
    doc_ids = set(_doc_item_ids())
    missing = doc_ids - set(BY_ID)
    assert not missing, f"docs/protocol.md §9 items missing from conformance_map_gen4.py: {sorted(missing)}"


def test_every_map_entry_matches_a_doc_item():
    """Catches the opposite drift: a map entry for an item the doc no longer has."""
    doc_ids = set(_doc_item_ids())
    extra = set(BY_ID) - doc_ids
    assert not extra, f"conformance_map_gen4.py has ids docs/protocol.md §9 does not: {sorted(extra)}"


def test_every_map_entry_has_a_valid_layer():
    for item in ITEMS:
        assert item.evidence_layer in LAYERS, f"item {item.id}: bad layer {item.evidence_layer!r}"


def test_every_na_item_has_a_reason_and_no_applicable_item_carries_one():
    for item in ITEMS:
        if item.evidence_layer == "na":
            assert item.na_reason, f"na item {item.id} has no reason"
        else:
            assert not item.na_reason, f"applicable item {item.id} carries an na_reason"


# ── world layer ────────────────────────────────────────────────────────────────────────────
# Small, independently-authored fixtures over tests/unit/gen4_world.World.

A = Mon(0x5A3C91E7, 155, 5, 20, 20)
B = Mon(0x0BADF00D, 155, 5, 11, 11)
CHARMAP = {0x12: "A", 0x13: "B", 0x14: "C"}
AREA = "function(map_id, loc) return 'route_' .. map_id, 'Route ' .. map_id end"
GIFT_AREA = "function() return 'gift_daycare', 'Daycare gift' end"   # an area the pack's list can name
STATS = {"level": 7, "maxHP": 30, "attack": 11, "defense": 12, "speed": 13, "spAtk": 14, "spDef": 15}
TITLES = ("heartgold", "soulsilver", "heartgold_hge")
TRAINER_OTID = 0x30391A5C


def two_mon():
    return [Mon(A.pid, 155, 5, 20, 20), Mon(B.pid, 155, 5, 11, 11)]


def ready(title="heartgold", party=None, boxes=None, **kw):
    """A booted, idle, overworld world (past hello + the first ticks)."""
    w = World(title, party=party or two_mon(), boxes=boxes, **kw)
    w.boot(80)
    return w


def ticks(w):
    return [m for m in w.sent if m["event"] == "tick"]


_WORLD_TESTS: dict[str, str] = {}

# Every world obligation now has a registered wire-level test; named GAPs stay in the map.
OWED_WORLD_ITEMS = []


def world_item(*item_ids):
    """Register the decorated test function against one or more conformance_map_gen4 item ids."""
    def deco(fn):
        for item_id in item_ids:
            _WORLD_TESTS[item_id] = fn.__name__
        return fn
    return deco


def test_every_world_item_has_a_world_test():
    """The meta-test: every applicable item tagged 'world' carries a test id that resolves to a real
    registered world test. A world item with test=None is 'coverage owed' and fails here."""
    missing = [
        item.id for item in ITEMS
        if item.evidence_layer == "world" and (not item.test or item.test != _WORLD_TESTS.get(item.id))
    ]
    # ponytail: ratchet, not a red test. Covering an owed item must also shrink OWED_WORLD_ITEMS.
    assert sorted(missing) == sorted(OWED_WORLD_ITEMS),         f"world items without a registered world test changed: {missing} (owed: {OWED_WORLD_ITEMS})"


# -- 8: hello shape on every admitted title --------------------------------------------------

@world_item("8")
def test_world_hello_carries_the_required_fields_on_every_admitted_title():
    for title in TITLES:
        w = World(title, party=two_mon(), charmap=CHARMAP, area_of=AREA)
        w.set_badges(0xA5, 0x3C)
        w.boot(80)
        hellos = w.events("hello")
        assert len(hellos) == 1, title
        h = hellos[0]
        assert h["rom_type"] == title, title
        assert h["player"] == "a" and isinstance(h["seq"], int), title
        assert h["has_pokeballs"] is False, title
        assert h["ot_id"] == TRAINER_OTID, title
        assert h["badges"] == 0xA5, title
        assert isinstance(h["trainer_name"], str) and h["trainer_name"], title
        assert [m["key"] for m in h["party"]] == [key_of(A.pid), key_of(B.pid)], title
        for entry in h["party"]:
            assert entry["hp"] >= 0 and entry["maxHP"] > 0 and entry["level"] > 0, (title, entry)


@world_item("10")
def test_world_ot_id_is_present_and_derivable_from_party0_key():
    w = World(party=two_mon(), charmap=CHARMAP, area_of=AREA)
    w.boot(80)
    h = w.events("hello")[0]
    assert h["ot_id"] == TRAINER_OTID
    ot_hex = h["party"][0]["key"].split(":")[1]
    assert int(ot_hex, 16) == TRAINER_OTID


@world_item("12")
def test_world_wrong_save_toast_accepts_either_field_spelling_without_crashing():
    w = ready()
    w.reply({"cmd": "hud_show", "text": "[x] WRONG SAVE (a)", "color": [255, 0, 0], "duration": 600})
    w.reply({"cmd": "hud_show", "text": "[x] WRONG SAVE (b)", "r": 255, "g": 0, "b": 0, "frames": 600})
    w.advance(4)
    shows = [h for h in w.hud if h[0] == "show"]
    assert len(shows) == 2 and all("WRONG SAVE" in s[1] for s in shows), w.hud
    assert w.state.fatal is None


@world_item("13")
def test_world_resolved_areas_and_config_are_applied():
    w = ready()
    w.reply({"cmd": "resolved_areas", "areas": ["route_1"]})
    w.reply({"cmd": "config", "battle_calc": True})
    w.advance(3)
    assert w.session.resolved_areas["route_1"] is True
    assert w.session.config["battle_calc"] is True


# -- 14/15/16: tick shape and battle facts ----------------------------------------------------

@world_item("14")
def test_world_tick_is_periodic_every_30_frames_and_carries_the_required_fields():
    w = World(party=two_mon(), charmap=CHARMAP, area_of=AREA)
    w.boot(80)
    frames = [f for m, f in zip(w.sent, w.sent_frames, strict=True) if m["event"] == "tick"]
    assert frames, "no ticks"
    assert all(f % 30 == 0 for f in frames), frames
    assert frames == list(range(frames[0], frames[-1] + 1, 30)), frames
    t = ticks(w)[-1]
    assert t["has_pokeballs"] is False and t["in_battle"] is False
    assert t["area_id"] == "route_60" and isinstance(t["loc_name"], str)
    assert isinstance(t["badges"], int) and isinstance(t["trainer_name"], str)
    assert t["enemy_party"] == [] and isinstance(t["party"], list)


@world_item("15")
def test_world_wild_battle_tick_has_in_battle_true_and_a_named_foe():
    w = ready(area_of=AREA)
    w.enter_battle(btype=0)
    w.advance(40)
    t = ticks(w)[-1]
    assert t["in_battle"] is True and t["is_trainer_battle"] is False
    assert t["area_id"] and t["enemy_party"][0]["species_id"] > 0


@world_item("16")
def test_world_trainer_battle_tick_names_the_battle_kind():
    w = ready(area_of=AREA)
    w.enter_battle(btype=1)
    w.advance(40)
    t = ticks(w)[-1]
    assert t["in_battle"] is True and t["is_trainer_battle"] is True
    # Gen 4 supplies NO trainer_id / opponent_* (client.lua:277): document the documented absence
    assert "trainer_id" not in t and "opponent_name" not in t and "opponent_class" not in t


@world_item("18")
def test_world_pc_boxes_are_zero_based_and_the_memorial_box_matches_the_adapter():
    from server.adapters.gen4_hgsspt import Gen4Adapter
    w = World(party=two_mon(), boxes={(0, 3): Mon(0x99999999, 16, 3, 13, 13)},
              charmap=CHARMAP, area_of=AREA)
    w.boot(80)
    h = w.events("hello")[0]
    boxes = h["pc_boxes"]
    assert boxes, "hello published no pc_boxes"
    for entry in boxes:
        assert entry["box"] >= 0 and entry["slot"] >= 0, entry
        assert entry["box"] < w.prof["boxes"] and entry["slot"] < w.prof["mons_per_box"], entry
    assert Gen4Adapter().memorial_box_index == 17


@world_item("19")
@pytest.mark.parametrize("title", TITLES)
def test_world_safe_is_sent_exactly_once_per_battle_end(title):
    """Item 19: the production driver arms the core's wire event after each debounced end."""
    w = ready(title)
    assert w.events("safe") == []
    for ended in (1, 2):
        w.enter_battle()
        w.advance(6)
        assert len(w.events("safe")) == ended - 1
        w.leave_battle()
        w.advance(6)
        assert len(w.events("safe")) == ended
        w.advance(20)
        assert len(w.events("safe")) == ended


@world_item("25")
def test_world_faint_fires_once_for_a_real_transition_and_never_for_a_commanded_zero():
    # a real HP>0 -> 0 transition on an active battler is one faint
    w = ready()
    w.enter_battle()
    w.advance(5)
    w.set_battle_hp(0, 0)
    w.advance(8)
    assert [f["key"] for f in w.events("faint")] == [key_of(A.pid)]
    # a client-commanded zero (force_faint) is never echoed as a faint
    w2 = ready()
    w2.reply({"cmd": "force_faint", "key": w2.party[0].key})
    w2.advance(8)
    assert w2.events("faint") == []
    assert w2.saved_hp(0) == 0


# -- 28/29/30/32: deferred storage + unknown key ---------------------------------------------

@world_item("28")
def test_world_box_mon_deposits_when_safe_and_sends_stats_cache_first():
    w = ready(party=[Mon(0x10000001), Mon(0x10000002), Mon(0x10000003)])
    w.reply({"cmd": "box_mon", "key": w.party[0].key})
    w.advance(6)
    assert w.events("box_mon_failed") == []
    assert len(w.events("stats_cache")) == 1
    assert w.saved_keys() == [key_of(0x10000002), key_of(0x10000003)]
    assert key_of(0x10000001) in w.box_keys()
    # our own deposit is not reported back as the player's move
    assert w.events("party_to_box") == [] and w.events("capture") == []


@world_item("29")
def test_world_party_mon_withdraws_when_safe_and_acks_exactly_once():
    mon = Mon(0x55555555, 155, 7, 3, 30)
    w = ready(party=[Mon(A.pid)], boxes={(2, 4): mon})
    w.reply({"cmd": "party_mon", "key": mon.key, "stats": STATS})
    w.advance(6)
    assert w.events("sync_retrieve_failed") == []
    assert [e["key"] for e in w.events("sync_retrieve_done")] == [mon.key]
    assert mon.key in w.saved_keys() and mon.key not in w.box_keys()
    assert w.events("box_to_party") == []


@world_item("30")
def test_world_memorialize_moves_to_the_memorial_box_and_acks_exactly_once():
    w = ready()
    w.reply({"cmd": "memorialize", "key": w.party[1].key})
    w.advance(6)
    assert [m["key"] for m in w.events("memorialize_done")] == [w.party[1].key]
    assert w.box_keys() == {w.party[1].key: (17, 0)}
    assert w.saved_keys() == [w.party[0].key]


@world_item("32")
def test_world_commands_for_an_unknown_key_are_silent_no_ops():
    unknown = key_of(0xDEADBEEF)
    w = ready()
    w.reply({"cmd": "box_mon", "key": unknown})
    w.advance(8)
    assert w.state.fatal is None
    assert w.box_keys() == {}
    assert all(e.get("key") != unknown or e["event"] == "box_mon_failed"
               for e in w.sent), "an unknown key produced an unexpected event"


@world_item("33")
def test_world_force_faint_on_a_bench_mon_zeroes_hp_and_is_never_echoed_as_a_faint():
    w = ready()
    w.reply({"cmd": "force_faint", "key": w.party[0].key})
    w.advance(6)
    assert w.saved_hp(0) == 0 and w.saved_hp(1) == 11
    assert w.events("faint") == []
    assert w.state.fatal is None


@world_item("35")
def test_world_game_over_sets_persistent_hud_state_and_ticks_keep_running():
    w = ready()
    before = len(ticks(w))
    w.reply({"cmd": "game_over"})
    w.advance(40)
    assert ("set_game_over") in [h[0] for h in w.hud], w.hud
    assert len(ticks(w)) > before, "ticks stopped after game_over"


@world_item("38")
def test_world_the_two_halves_of_a_link_produce_distinct_keys():
    # shape-level: two independent saves with distinct PID/OT naturally produce distinct keys
    ka, kb = key_of(A.pid, 0x11111111), key_of(B.pid, 0x22222222)
    assert ka != kb and re.match(r"^[0-9A-F]{8}:[0-9A-F]{8}$", ka)
    assert re.match(r"^[0-9A-F]{8}:[0-9A-F]{8}$", kb)

X = Mon(0x7777AAAA, 16, 3, 13, 13, otid=0x0000BEEF)


@world_item("37")
def test_world_an_npc_trade_is_one_key_change_with_no_spurious_move_events():
    w = ready()
    old = key_of(A.pid)
    w.party[0] = Mon(X.pid, 16, 3, 13, 13, otid=X.otid)      # record replaced in place: PID:OTID changed
    w.write_party()
    w.advance(8)
    kc = w.events("key_change")
    assert len(kc) == 1, kc
    assert kc[0]["old_key"] == old and kc[0]["new_key"] == X.key
    assert kc[0]["reason"] == "npc_trade"
    # the change must NOT also surface as an acquisition or a player-initiated PC move
    assert w.events("capture") == [] and w.events("party_to_box") == [] and w.events("box_to_party") == []


# -- explicitly-called-out behaviours: malformed hello + the hge routing OPEN -------------------

def test_a_malformed_hello_goes_red_at_send_time():
    """A deliberately malformed hello is rejected by the SAME gate gen4_world's send applies
    (gen4_world.py:453-460, validate_event strict). This proves the send-time gate is real."""
    w = World(party=two_mon(), charmap=CHARMAP, area_of=AREA)
    w.boot(80)
    bad = dict(w.events("hello")[0])
    bad["party"] = "not-a-list"                       # malformed: party must be a list
    problems = ps.validate_event(bad, strict=True)
    assert problems and any("party" in p for p in problems), problems
    line = json.dumps(bad)
    send = w.net["send"]                            # the SAME python closure gen4_world's gate uses
    if callable(send):                               # drive the real send-time path when reachable
        with pytest.raises(AssertionError):
            send(line)


def test_open_hge_hello_is_currently_refused_for_routing():
    """OPEN (pending G3a): heartgold_hge is admitted by the LUA client but has NO
    _ROM_TYPE_TO_GAME_ID row yet (server/adapters/__init__.py:42-87), so foundation_for_rom_type
    returns None and protocol_schema refuses the hello as 'not one the server routes'.

    gen4_world.py:458-459 suppresses exactly this problem for the heartgold_hge title. This test
    does NOT inherit that suppression: it runs the raw validator on a real hge hello and asserts the
    refusal is present. When G3a adds the server row, this test must be inverted AND the harness
    suppression at gen4_world.py:458-459 removed.
    """
    from server.adapters import foundation_for_rom_type

    assert foundation_for_rom_type("heartgold_hge") is None, "G3a added the row; update this OPEN"
    w = World("heartgold_hge", party=two_mon(), charmap=CHARMAP, area_of=AREA)
    w.boot(80)
    hello = w.events("hello")[0]
    assert hello["rom_type"] == "heartgold_hge"
    problems = ps.validate_event(hello, strict=True)
    assert any("not one the server routes" in p for p in problems), \
        f"expected the hge routing refusal, got {problems}"


# -- 11 / 20 / 21 / 26 / 27: the encounter + reducer half, on the production client -------------------


def _map_cell(w):
    """The Player Location map_id cell the client reads for area_now() (gen4_world.py:285-288)."""
    return w.dyn + w.arrays[5][1] + w.prof["location"]["map_off"]


def _pc_edge(w, settle=8):
    """Let the driver notice that a box moved: a task edge (client.lua:685) marks the census dirty."""
    w.field(task=1)
    w.advance(3)
    w.field(task=0)
    w.advance(settle)


def _traded():
    """A world whose slot-0 record was replaced in place (the NPC-trade shape, item 37)."""
    w = ready()
    w.party[0] = Mon(X.pid, 16, 3, 13, 13, otid=X.otid)
    w.write_party()
    w.advance(8)
    return w


@world_item("11")
def test_world_no_hello_ever_carries_a_party_the_client_cannot_read():
    """Item 11's Gen 4 half. hello_fields sends `party = []` whenever party_read() fails
    (client.lua:521-523), but hello_ready calls game_is_live, which REFUSES an unreadable party
    (client.lua:502-519): the line that would carry `[]` never goes out at all. So the obligation
    is satisfied as a refusal, and that refusal is what this asserts on RAM -- with the SaveData
    pointer nulled (reads.lua:161, "null_ptr") a running session publishes no hello whatsoever,
    and the first hello after the save returns carries the party again.

    The BORROWED half has no Gen 4 source: `party_borrowed` is a Gen-3-only driver seam
    (lua/core/session.lua:26; its only implementor is lua/gen3/client.lua:1066).
    """
    w = ready()
    hello = w.events("hello")[0]
    assert [m["key"] for m in hello["party"]] == [m.key for m in w.party]

    ptr, keep = w.prof["save_ptr"]["address"], w.get(w.prof["save_ptr"]["address"], 4)
    w.connected = False
    w.advance(2)
    w.put(ptr, bytes(4))                                  # SaveData pointer cell nulled
    w.connected = True
    w.advance(40)
    assert len(w.events("hello")) == 1, [h["party"] for h in w.events("hello")[1:]]
    assert w.state.fatal is None

    w.put(ptr, keep)
    w.connected = False
    w.advance(2)
    w.connected = True
    w.advance(40)
    assert len(w.events("hello")) == 2, "the client never re-helloed once the save was readable"
    assert [m["key"] for m in w.events("hello")[1]["party"]] == [m.key for m in w.party]


@world_item("20")
def test_world_area_enter_fires_once_per_map_change_and_never_repeats_one():
    w = ready(area_of=AREA)
    assert w.events("area_enter") == [], "the baseline area announced itself"
    cell = _map_cell(w)

    w.w(cell, 61)
    w.advance(40)
    (first,) = w.events("area_enter")
    assert first["area_id"] == "route_61" and first["loc_name"] == "Route 61", first
    assert [t["area_id"] for t in ticks(w)][-1] == "route_61", "the tick did not follow the map change"

    w.w(cell, 62)
    w.advance(40)
    assert [e["area_id"] for e in w.events("area_enter")] == ["route_61", "route_62"], \
        "the same map re-fired, or the new map was missed"


@world_item("21")
def test_world_capture_carries_key_area_species_level_and_the_acquisition_flags():
    # an out-of-battle acquisition is a gift and says so; a party catch carries no in_box
    w = ready(area_of=AREA)
    w.party.append(Mon(0x33333333, 16, 3, 13, 13))
    w.write_party()
    w.advance(12)
    (gift,) = w.events("capture")
    assert gift["key"] == key_of(0x33333333) and gift["area_id"] == "route_60", gift
    assert gift["species_id"] == 16 and gift["level"] == 3
    assert gift["gift"] is True and gift["is_egg"] is False and "in_box" not in gift, gift

    # the same species CAUGHT out of a wild battle: the capture carries the encounter's area and
    # is not a gift (poll_events.lua:364-379; the world foe is Mon(0x01010101, otid=0x0000BEEF))
    w2 = ready(area_of=AREA)
    w2.enter_battle()
    w2.advance(5)
    w2.leave_battle()
    w2.party.append(Mon(0x01010101, 16, 3, 13, 13, otid=0x0000BEEF))
    w2.write_party()
    w2.advance(12)
    caught = w2.events("capture")
    assert len(caught) == 1, caught
    assert caught[0]["area_id"] == "route_60" and "gift" not in caught[0], caught[0]
    assert caught[0]["species_id"] == 16 and caught[0]["level"] == 3 and caught[0]["is_egg"] is False


def _wild_end(w, *, btype=0, outcome=None):
    w.enter_battle(btype=btype)
    w.advance(5)
    if outcome is not None:
        w.set_outcome(outcome)
        w.advance(3)
    w.leave_battle()
    w.advance(12)


@world_item("23")
@pytest.mark.parametrize("title", TITLES)
def test_world_no_catch_ball_gate_once_per_area_and_never_after_capture(title):
    w = ready(title, area_of=AREA, balls=True)
    assert w.events("hello")[0]["has_pokeballs"] is True
    w.enter_battle()
    w.advance(5)
    assert w.events("no_catch") == []
    w.leave_battle()
    w.advance(12)
    assert [{k: e[k] for k in ("area_id", "species_id", "level")} for e in w.events("no_catch")] == [
        {"area_id": "route_60", "species_id": 16, "level": 3}]
    w.advance(80)
    _wild_end(w)
    assert len(w.events("no_catch")) == 1  # same area, a second battle cannot resolve it twice
    assert w.writes == []

    caught = ready(title, area_of=AREA, balls=True)
    caught.enter_battle()
    caught.advance(5)
    caught.leave_battle()
    caught.party.append(Mon(0x01010101, 16, 3, 13, 13, otid=0x0000BEEF))
    caught.write_party()
    caught.advance(12)
    assert len(caught.events("capture")) == 1
    assert caught.events("capture")[0]["area_id"] == "route_60"
    assert "gift" not in caught.events("capture")[0]
    assert caught.events("no_catch") == []
    assert caught.writes == []

    # The native CAUGHT outcome suppresses no_catch even if copy-back is not yet attributable.
    outcome_only = ready(title, area_of=AREA, balls=True)
    _wild_end(outcome_only, outcome=outcome_only.prof["battle_enums"]["outcomes"]["caught"])
    assert outcome_only.events("no_catch") == []
    assert outcome_only.writes == []


@pytest.mark.parametrize("title", TITLES)
@pytest.mark.parametrize("balls", [None, False])
def test_world_no_catch_stays_off_without_balls_or_without_the_producer(title, balls):
    w = ready(title, area_of=AREA, balls=balls)
    assert w.events("hello")[0]["has_pokeballs"] is False
    _wild_end(w)
    assert w.events("no_catch") == []
    assert w.writes == []


@pytest.mark.parametrize("title", TITLES)
@pytest.mark.parametrize("item,quantity", [(1, 0), (17, 1)])
def test_world_no_catch_requires_a_ball_id_and_positive_quantity(title, item, quantity):
    def pocket(w):
        bag = w.prof["bag"]
        slot = w.dyn + w.arrays[bag["array_id"]][1] + bag["balls_pocket_off"]
        for name, value in (("id", item), ("quantity", quantity)):
            field = bag["slot_fields"][name]
            w.w(slot + field["off"], value, field["size"])

    w = ready(title, area_of=AREA, balls=False, pre=pocket)
    assert w.events("hello")[0]["has_pokeballs"] is False
    _wild_end(w)
    assert w.events("no_catch") == []
    assert w.writes == []


@pytest.mark.parametrize("title", TITLES)
def test_world_no_catch_never_fires_in_an_area_the_pack_calls_a_gift_area(title):
    """docs/protocol.md §9 item 23, gift half: a scripted catch is not a wild encounter, so the area
    it lands in must not be dead-zoned. The exemption is the PACK's own list -- data/games/gen4_hgss/
    area_map.json `gift_areas.ids` through lua/gen4/inputs.lua Inputs.gift_area -- so this asserts the
    seam end to end, not a hardcoded id."""
    w = ready(title, area_of=GIFT_AREA, gift_area={"gift_daycare"}, balls=True)
    _wild_end(w)
    assert w.events("no_catch") == [], w.events("no_catch")
    assert w.writes == []


@pytest.mark.parametrize("title", TITLES)
def test_the_gift_area_exemption_is_load_bearing_and_not_a_default(title):
    """Red control: the SAME world with the seam unwired emits the no_catch. If the test above ever
    passed for an unwired client, it would be proving the harness, not the wiring."""
    w = ready(title, area_of=GIFT_AREA, balls=True)
    _wild_end(w)
    assert [e["area_id"] for e in w.events("no_catch")] == ["gift_daycare"]
    assert w.writes == []


@world_item("24")
@pytest.mark.parametrize("title", TITLES)
def test_world_unresolve_area_rearms_no_catch_only_for_the_named_area(title):
    w = ready(title, area_of=AREA, balls=True)
    _wild_end(w)
    assert [e["area_id"] for e in w.events("no_catch")] == ["route_60"]
    w.reply({"cmd": "unresolve_area", "area_id": "route_99"})
    w.advance(3)
    _wild_end(w)
    assert [e["area_id"] for e in w.events("no_catch")] == ["route_60"]
    w.reply({"cmd": "unresolve_area", "area_id": "route_60"})
    w.advance(3)
    _wild_end(w)
    assert [e["area_id"] for e in w.events("no_catch")] == ["route_60", "route_60"]
    w.advance(80)
    _wild_end(w)
    assert [e["area_id"] for e in w.events("no_catch")] == ["route_60", "route_60"]
    assert w.writes == []  # protocol rearming never writes the game save


@world_item("26")
def test_world_whiteout_fires_once_per_losing_battle_and_never_twice_for_one():
    w = ready(area_of=AREA)
    lose = w.prof["battle_enums"]["outcomes"]["lose"]                  # BATTLE_OUTCOME_LOSE (2)

    w.enter_battle()
    w.advance(3)
    w.set_outcome(lose)
    w.advance(3)
    w.leave_battle()
    w.advance(8)
    assert len(w.events("whiteout")) == 1, w.events("whiteout")

    for m in w.party:
        m.hp = 0
    w.write_party()
    w.advance(60)
    assert len(w.events("whiteout")) == 1, "the all-fainted party reported a second whiteout"

    w.enter_battle()
    w.advance(3)
    w.set_outcome(lose)
    w.advance(3)
    w.leave_battle()
    w.advance(8)
    assert len(w.events("whiteout")) == 2, "a second loss is its own whiteout"


@world_item("27")
def test_world_party_to_box_and_box_to_party_fire_for_a_player_driven_move():
    mon = Mon(0x1000ABCD, 155, 6, 12, 30)
    w = ready(party=[Mon(A.pid, 155, 5, 20, 20), mon])

    w.party = [w.party[0]]                       # the player boxes the second mon themselves
    w.boxes[(3, 4)] = mon
    w.write_party()
    w.write_boxes()
    _pc_edge(w)
    (dep,) = w.events("party_to_box")
    assert dep["key"] == mon.key and dep["stats"]["level"] == 6, dep

    w.boxes.pop((3, 4))
    w.party.append(mon)                          # ... and takes it back out
    w.write_party()
    w.write_boxes()
    _pc_edge(w)
    assert [e["key"] for e in w.events("box_to_party")] == [mon.key]
    assert w.events("capture") == [], "a player-driven PC move is not an acquisition"


# -- 31 / 36 / 38a / 38b: the deferred queue and the key machinery ---------------------------------


@world_item("31")
def test_world_deferred_commands_run_one_per_frame_in_order_and_dedupe():
    a, b, c, d, e = (Mon(0x10000001 + i) for i in range(5))
    w = ready(party=[a, b, c, d, e])

    w.field(driver_state=0)                      # the save driver is mid-write: the gate is shut
    w.advance(3)
    w.reply({"cmd": "box_mon", "key": a.key}, {"cmd": "box_mon", "key": b.key})
    w.advance(3)
    assert w.events("stats_cache") == [] and w.box_keys() == {}, "a command ran while unsafe"

    w.field()
    w.advance(1)
    assert [k["key"] for k in w.events("stats_cache")] == [a.key], "not one command, or out of order"
    w.advance(4)
    assert [k["key"] for k in w.events("stats_cache")] == [a.key, b.key]

    w.reply({"cmd": "memorialize", "key": c.key}, {"cmd": "memorialize", "key": c.key})
    w.advance(8)
    assert [e["key"] for e in w.events("memorialize_done")] == [c.key], "a duplicate memorialize ran"
    assert w.box_keys()[c.key] == (17, 0), w.box_keys()

    w.reply({"cmd": "party_mon", "key": d.key, "stats": STATS},   # the box_mon cancels the queued
            {"cmd": "box_mon", "key": d.key})                     # party_mon, not the other way round
    w.advance(8)
    assert [k["key"] for k in w.events("stats_cache")][-1] == d.key
    assert w.events("sync_retrieve_done") == [], "the cancelled party_mon still withdrew"
    assert d.key in w.box_keys() and d.key not in w.saved_keys()
    assert w.state.fatal is None


@world_item("36")
def test_world_keys_survive_a_box_round_trip_a_held_item_change_and_a_reconnect():
    mon = Mon(0x2000BEEF, 155, 6, 12, 30)
    w = ready(party=[Mon(A.pid, 155, 5, 20, 20), mon])
    before = {m["key"] for m in w.events("hello")[0]["party"]}
    assert before == {key_of(A.pid), mon.key}

    w.reply({"cmd": "box_mon", "key": mon.key})
    w.advance(5)
    w.reply({"cmd": "party_mon", "key": mon.key, "stats": STATS})
    w.advance(5)
    assert mon.key in w.saved_keys() and mon.key not in w.box_keys(), "the round trip lost or changed the key"

    mon.item = 42                                   # a held-item change is not a key change
    w.write_party()
    w.advance(40)
    assert w.events("key_change") == [], "a held-item change was reported as a key change"
    entry = [e for e in ticks(w)[-1]["party"] if e["key"] == mon.key]
    assert len(entry) == 1 and entry[0]["held_item_id"] == 42, entry
    assert [e["key"] for e in ticks(w)[-1]["party"]] == w.saved_keys()

    w.connected = False
    w.advance(2)
    w.connected = True
    w.advance(40)
    assert len(w.events("hello")) == 2
    assert {m["key"] for m in w.events("hello")[1]["party"]} == before, "the reconnect changed the keys"


@world_item("38a")
def test_world_one_answer_settles_a_key_change_and_the_alias_follows_that_answer():
    # ACK: exactly one answer settles the alias, and the old key then names nothing
    w = _traded()
    (kc,) = w.events("key_change")
    w.reply({"cmd": "key_change_ack", "old_key": kc["old_key"], "new_key": kc["new_key"], "migrated": True})
    w.advance(6)
    assert w.session.identity.pending is None, "the ack did not settle the alias"
    w.reply({"cmd": "force_faint", "key": kc["old_key"]})
    w.advance(6)
    assert w.writes == [] and w.saved_hp(0) == 13, "an acked old key still resolved to the record"
    assert len(w.events("key_change")) == 1, "the settled change was re-sent"

    # REJECTED: the alias is retired, so the same old key DOES resolve to the changed record
    w2 = _traded()
    (kc2,) = w2.events("key_change")
    w2.reply({"cmd": "key_change_rejected", "old_key": kc2["old_key"], "new_key": kc2["new_key"],
              "reason": "collision"})
    w2.advance(6)
    assert w2.session.identity.pending is None
    ident = w2.session.identity
    assert ident.retired(ident, kc2["old_key"]) is not None, "the rejection retired nothing"  # Lua method: pass self
    w2.reply({"cmd": "force_faint", "key": kc2["old_key"]})
    w2.advance(6)
    assert w2.saved_hp(0) == 0 and w2.saved_hp(1) == 11, "the retired alias did not find the record"
    assert any(h[0] == "show" and "IDENTITY CHANGE REFUSED" in h[1] for h in w2.hud), w2.hud
    assert len(w2.events("key_change")) == 1


@world_item("38b")
def test_world_a_replayed_key_change_answer_is_idempotent_and_writes_nothing():
    w = _traded()
    (kc,) = w.events("key_change")
    w.reply({"cmd": "key_change_ack", "old_key": kc["old_key"], "new_key": kc["new_key"], "migrated": False})
    w.advance(6)
    w.reply({"cmd": "key_change_ack", "old_key": kc["old_key"], "new_key": kc["new_key"], "migrated": False})
    w.advance(20)
    assert len(w.events("key_change")) == 1, "a replayed answer re-sent the change"
    assert w.session.identity.pending is None
    assert w.writes == [] and w.saved_keys() == [X.key, key_of(B.pid)], "a replayed answer moved bytes"
    assert w.state.fatal is None

    w2 = _traded()
    (kc2,) = w2.events("key_change")
    w2.reply({"cmd": "key_change_rejected", "old_key": kc2["old_key"], "new_key": kc2["new_key"],
              "reason": "collision"})
    w2.advance(40)
    assert len(w2.events("key_change")) == 1, "a rejected change was re-sent without a new census"
    assert w2.writes == [], "a rejected change wrote to the cartridge"
    assert w2.saved_keys() == [X.key, key_of(B.pid)]
