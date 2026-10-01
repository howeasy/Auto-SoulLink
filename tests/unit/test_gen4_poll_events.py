"""lua/gen4/poll_events.lua: scripted snapshot sequences, one positive + one near-miss per event.

The reducer is pure (snapshot in, wire events out), so the sequences are exact frame scripts. Every
emitted event is also validated against tests/unit/protocol_schema.py. The outcome codes / battle-type
masks used as cfg are a labelled MODEL of the pret enums (include/constants/battle.h:112-118 for the
outcomes; trainer bit 1 is the engine's BATTLE_TYPE_TRAINER, 0x20 stands for an exempt type): the pack
carries none of them yet, see the card report.
"""

from __future__ import annotations

from pathlib import Path

import lupa
import pytest

from tests.unit.protocol_schema import validate_event

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "lua/gen4/poll_events.lua"

OUTCOMES = {"win": 1, "lose": 2, "draw": 3, "caught": 4, "player_fled": 5, "foe_fled": 6}  # MODEL
TRAINER, EXEMPT = 0x01, 0x20  # MODEL battle-type bits
OT = 0xBB83039  # the player's OTID
FOE_PID = 0x1A2B3C4D


def key(pid, otid=OT):
    return f"{pid:08X}:{otid:08X}"


def to_lua(lua, v):
    if isinstance(v, dict):
        return lua.table_from({k: to_lua(lua, x) for k, x in v.items() if x is not None})
    if isinstance(v, list):
        return lua.table_from([to_lua(lua, x) for x in v])
    return v


def py(v):
    if lupa.lua_type(v) != "table":
        return v
    keys = list(v.keys())
    if keys and keys == list(range(1, len(keys) + 1)):
        return [py(v[k]) for k in keys]
    return {k: py(v[k]) for k in keys}


class Rig:
    def __init__(self, src: str | None = None, **cfg):
        self.lua = lupa.LuaRuntime()
        mod = self.lua.eval("function(s) return assert(load(s, '=poll_events'))() end")(
            src if src is not None else SRC.read_text(encoding="utf-8"))
        self.resolved = self.lua.table()
        base = {"outcomes": OUTCOMES, "trainer_mask": TRAINER, "no_catch_mask": EXEMPT}
        base.update(cfg)
        c = to_lua(self.lua, base)
        c["resolved"] = self.resolved
        c["gift_area"] = lambda a: a == "gift_area"
        self.pe = mod.new(c)
        self.events: list[dict] = []
        self.notes: list[str] = []

    def step(self, snap: dict) -> list[dict]:
        ev, notes = self.pe.step(self.pe, to_lua(self.lua, snap))
        out = py(ev) or []
        self.events += out
        self.notes += list(py(notes) or [])
        for e in out:
            msg = {"event": e["name"], "player": "a", "seq": len(self.events), **e["data"]}
            assert validate_event(msg, strict=True) == [], (e, validate_event(msg, strict=True))
        return out

    def run(self, snap: dict, n: int = 1) -> list[dict]:
        out = []
        for _ in range(n):
            out += self.step(snap)
        return out

    def names(self) -> list[str]:
        return [e["name"] for e in self.events]

    def of(self, name: str) -> list[dict]:
        return [e["data"] for e in self.events if e["name"] == name]


def mon(pid, slot, species=155, level=5, hp=20, max_hp=20, egg=False, otid=OT):
    return {"key": key(pid, otid), "slot": slot, "species": species, "level": level, "hp": hp, "max_hp": max_hp,
            "is_egg": egg or None}


def boxes(gen=1, **mons):
    return {"gen": gen, "mons": {k: {"species_id": 16, "nickname": "X", "held_item_id": 0} for k in mons}}


def snap(party, bx=None, *, idle=True, area="A29", loc="Route 29", battle=None, **kw):
    return {"area": area, "loc": loc, "party": party, "boxes": bx if bx is not None else boxes(), "idle": idle,
            "battle": battle, "player_otid": OT, "has_pokeballs": True, **kw}


OWN = mon(0x11111111, 0)


def battler(b, pid, otid, species, hp, max_hp=13, level=2):
    return {"b": b, "pid": pid, "otid": otid, "key": key(pid, otid), "species": species, "level": level,
            "hp": hp, "max_hp": max_hp}


def battle(*mons, fp="F1", btype=0, outcome=0):
    return {"fingerprint": fp, "btype": btype, "outcome": outcome, "mons": list(mons)}


def wild(own_hp=20, foe_hp=13, **kw):
    return battle(battler(0, 0x11111111, OT, 155, own_hp, 20, 5), battler(1, FOE_PID, 0, 16, foe_hp), **kw)


def settled(rig, party=None, bx=None, n=3, **kw):
    """n idle frames of an unchanging overworld (the baseline / a settle window)."""
    return rig.run(snap([OWN] if party is None else party, bx, **kw), n)


def fight(rig, party, bx=None, *, frames=3, final=None, **bk):
    """A battle that runs `frames` frames, the last carrying `final`, then the chain drops (non-idle)."""
    for i in range(frames):
        extra = final if (final is not None and i == frames - 1) else {}
        rig.step(snap(party, bx, idle=False, battle=wild(**{**bk, **extra})))
    rig.run(snap(party, bx, idle=False), 3)  # chain gone for end_frames, copy-back not yet idle


@pytest.fixture
def rig():
    r = Rig()
    settled(r)
    assert r.events == []  # the baseline is learned silently
    return r


# -- area_enter ------------------------------------------------------------------------------
def test_area_enter_once_per_change_and_not_for_the_first_area_or_a_flicker():
    r = Rig()
    r.run(snap([OWN], area="A29"), 3)
    assert r.events == []
    r.step(snap([OWN], area="A30", loc="Route 30"))  # one frame: a transition flicker
    r.run(snap([OWN], area="A29"), 3)
    assert r.events == []
    r.run(snap([OWN], area="A30", loc="Route 30"), 4)
    assert r.of("area_enter") == [{"area_id": "A30", "loc_name": "Route 30"}]


# -- capture ---------------------------------------------------------------------------------
def test_capture_party_matches_the_battle_time_enemy_identity(rig):
    new = mon(FOE_PID, 1, species=16, level=2, hp=13, max_hp=13, otid=OT)
    fight(rig, [OWN], final={"outcome": OUTCOMES["caught"]})
    assert rig.events == []                       # nothing before the copy-back is visible and settled
    settled(rig, [OWN, new])
    cap = rig.of("capture")
    assert len(cap) == 1 and cap[0]["key"] == new["key"] and cap[0]["area_id"] == "A29"
    assert cap[0]["species_id"] == 16 and cap[0]["level"] == 2 and "gift" not in cap[0]
    assert "no_catch" not in rig.names() and rig.resolved["A29"] is True
    assert rig.pe.known(rig.pe, new["key"])


def test_capture_accepts_the_enemy_pid_with_the_players_otid_rewrite(rig):
    # the wild BattleMon carries OTID 0 (set in wild()); the stored record may carry the player's OT
    new = mon(FOE_PID, 1, species=16, level=2, hp=13, max_hp=13, otid=OT)
    assert key(FOE_PID, 0) != new["key"]
    fight(rig, [OWN])                             # outcome byte unreadable: the key evidence carries it
    settled(rig, [OWN, new])
    assert [c["key"] for c in rig.of("capture")] == [new["key"]]
    assert "no_catch" not in rig.names()


def test_capture_to_box_when_the_party_is_full(rig):
    party = [OWN] + [mon(0x20000000 + i, i) for i in range(1, 6)]
    r = Rig()
    settled(r, party)
    fight(r, party, final={"outcome": OUTCOMES["caught"]})
    bx = boxes(2, **{key(FOE_PID): 1})
    settled(r, party, bx)
    cap = r.of("capture")
    assert len(cap) == 1 and cap[0]["in_box"] is True and cap[0]["key"] == key(FOE_PID)
    assert cap[0]["level"] == 2 and "no_catch" not in r.names()


def test_species_equality_alone_is_not_a_capture(rig):
    other = mon(0x77777777, 1, species=16, level=2, hp=13, max_hp=13)   # same species, other PID
    fight(rig, [OWN])
    settled(rig, [OWN, other])
    cap = rig.of("capture")
    assert len(cap) == 1 and cap[0]["gift"] is True                      # an unexplained arrival, never "the catch"
    assert rig.of("no_catch") == [{"area_id": "A29", "species_id": 16, "level": 2}]


def test_a_box_move_is_not_a_capture_and_a_trade_slot_replace_is_neither_capture_nor_release(rig):
    r = Rig()
    boxed = mon(0x31313131, 1)
    settled(r, [OWN, boxed])
    settled(r, [OWN], boxes(2, **{boxed["key"]: 1}))                     # deposit
    assert r.names() == ["party_to_box"] and r.of("party_to_box")[0]["key"] == boxed["key"]
    r.events.clear()
    traded_for = mon(0x42424242, 1, species=100)
    settled(r, [OWN, traded_for], boxes(2, **{boxed["key"]: 1}))          # withdraw of a DIFFERENT key out of nowhere
    assert r.names() == ["capture"] and r.of("capture")[0]["gift"] is True
    r2 = Rig()
    settled(r2, [OWN, boxed])
    r2.run(snap([OWN, traded_for], pc_active=True), 3)                    # slot 1: boxed -> traded_for, pc open
    assert r2.events == [] and any(n.startswith("slot_replace:") for n in r2.notes)


# -- moves -----------------------------------------------------------------------------------
def test_party_to_box_and_back_preserve_the_key():
    r = Rig()
    boxed = mon(0x31313131, 1)
    settled(r, [OWN, boxed])
    settled(r, [OWN], boxes(2, **{boxed["key"]: 1}))
    settled(r, [OWN, boxed], boxes(3))
    assert r.names() == ["party_to_box", "box_to_party"]
    assert r.of("box_to_party")[0]["key"] == boxed["key"] and r.of("box_to_party")[0]["area_id"] == "A29"
    assert r.of("party_to_box")[0]["stats"]["level"] == 5


def test_a_one_frame_party_flicker_moves_nothing(rig):
    r = Rig()
    boxed = mon(0x31313131, 1)
    settled(r, [OWN, boxed])
    r.step(snap([OWN], boxes(2, **{boxed["key"]: 1})))                    # one frame of "deposited"
    settled(r, [OWN, boxed], boxes(1))
    assert r.events == []


def test_non_idle_frames_never_settle():
    r = Rig()
    settled(r, [OWN, mon(0x31313131, 1)])
    r.run(snap([OWN], idle=False), 10)
    assert r.events == []


def test_expected_own_move_is_learned_but_not_reported():
    r = Rig()
    boxed = mon(0x31313131, 1)
    settled(r, [OWN, boxed])
    r.pe.expect(r.pe, "party_to_box", boxed["key"])
    settled(r, [OWN], boxes(2, **{boxed["key"]: 1}))
    assert r.events == []
    settled(r, [OWN, boxed], boxes(3))                                    # the player's own withdraw still reports
    assert r.names() == ["box_to_party"]


def test_release_needs_the_pc_application_and_a_key_that_was_ours():
    r = Rig()
    gone = mon(0x31313131, 1)
    settled(r, [OWN, gone])
    r.run(snap([OWN], pc_active=True), 1)
    settled(r, [OWN])
    assert r.of("release") == [{"key": gone["key"]}]
    r2 = Rig()
    settled(r2, [OWN, gone])
    settled(r2, [OWN])                                                     # vanished with no PC: a daycare, not a release
    assert r2.events == [] and f"vanished:{gone['key']}" in r2.notes


def test_a_known_key_returning_from_nowhere_is_not_a_capture():
    r = Rig()
    d = mon(0x31313131, 1)
    settled(r, [OWN, d])
    settled(r, [OWN])
    settled(r, [OWN, d])
    assert r.events == [] and any(n.startswith("returned:") for n in r.notes)


def test_egg_is_acquired_at_hatch_as_a_daycare_gift():
    r = Rig()
    settled(r, [OWN])
    egg = mon(0x55555555, 1, species=175, level=1, hp=0, max_hp=0, egg=True)
    settled(r, [OWN, egg])
    assert r.events == []
    settled(r, [OWN, mon(0x55555555, 1, species=175, level=1, hp=11, max_hp=11)])
    cap = r.of("capture")
    assert len(cap) == 1 and cap[0]["area_id"] == "gift_daycare" and cap[0]["gift"] is True and cap[0]["is_egg"] is False


# -- faint -----------------------------------------------------------------------------------
def test_faint_in_battle_after_the_debounce_and_only_once_across_the_copy_back(rig):
    for hp in (20, 20, 0, 0, 0):
        rig.step(snap([OWN], idle=False, battle=wild(own_hp=hp)))
    assert rig.of("faint") == [{"key": OWN["key"], "area_id": "A29"}]
    rig.run(snap([OWN], idle=False), 8)                                    # chain gone; the save party is STALE (hp 20)
    settled(rig, [{**OWN, "hp": 0}])                                       # copy-back lands the zero
    rig.run(snap([{**OWN, "hp": 0}]), 3)
    assert len(rig.of("faint")) == 1


def test_an_hp_flicker_during_the_hp_bar_update_does_not_fault(rig):
    for hp in (20, 20, 0, 12, 20, 0, 12, 12):                              # never two zero frames in a row
        rig.step(snap([OWN], idle=False, battle=wild(own_hp=hp)))
    assert rig.of("faint") == []


def test_a_commanded_zero_is_not_a_faint_and_a_revive_re_arms(rig):
    rig.step(snap([OWN], idle=False, battle=wild()))
    rig.step(snap([OWN], idle=False, battle=wild()))
    rig.pe.commanded(rig.pe, OWN["key"])
    for _ in range(3):                                                      # the write has not landed yet
        rig.step(snap([OWN], idle=False, battle=wild()))
    for _ in range(4):
        rig.step(snap([OWN], idle=False, battle=wild(own_hp=0)))
    assert rig.of("faint") == []
    for _ in range(3):                                                      # revived, then genuinely KO'd
        rig.step(snap([OWN], idle=False, battle=wild(own_hp=7)))
    for _ in range(3):
        rig.step(snap([OWN], idle=False, battle=wild(own_hp=0)))
    assert len(rig.of("faint")) == 1


def test_a_partner_battler_that_is_not_in_our_party_never_faints(rig):
    for hp in (30, 30, 0, 0, 0, 0):
        partner = battler(2, 0x99999999, 7, 25, hp, 30, 10)                # TAG/multi partner: another trainer's mon
        rig.step(snap([OWN], idle=False, battle=battle(battler(0, 0x11111111, OT, 155, 20, 20, 5), partner,
                                                       battler(1, FOE_PID, 0, 16, 13))))
    assert rig.of("faint") == []


def test_overworld_faint_uses_party_hp_and_wants_two_frames(rig):
    rig.run(snap([OWN]), 3)                                                # re-arm
    rig.step(snap([{**OWN, "hp": 0}], idle=False))
    rig.step(snap([OWN], idle=False))                                      # a one-frame zero (torn read)
    assert rig.of("faint") == []
    rig.run(snap([{**OWN, "hp": 0}], idle=False), 3)                       # poison: a field task runs, never idle
    assert rig.of("faint") == [{"key": OWN["key"], "area_id": "A29"}]
    rig.run(snap([{**OWN, "hp": 0}], idle=False), 5)
    assert len(rig.of("faint")) == 1


# -- no_catch --------------------------------------------------------------------------------
def test_no_catch_for_a_wild_battle_that_ended_without_a_capture(rig):
    fight(rig, [OWN], final={"outcome": OUTCOMES["win"]})
    assert rig.of("no_catch") == []                                         # decided at the first settled snapshot
    settled(rig)
    assert rig.of("no_catch") == [{"area_id": "A29", "species_id": 16, "level": 2}]
    fight(rig, [OWN], final={"outcome": OUTCOMES["win"]})
    settled(rig)
    assert len(rig.of("no_catch")) == 1                                     # the area is resolved: never twice


@pytest.mark.parametrize("why, kw, cfg", [
    ("trainer battle", {"btype": TRAINER}, {}),
    ("exempt battle type", {"btype": EXEMPT}, {}),
    ("caught per the outcome byte", {"outcome": OUTCOMES["caught"]}, {}),
    ("trainer bit unknown to the pack", {}, {"trainer_mask": None}),
])
def test_no_catch_negatives(why, kw, cfg):
    r = Rig(**cfg)
    settled(r)
    for _ in range(3):
        r.step(snap([OWN], idle=False, battle=wild(**kw)))
    r.run(snap([OWN], idle=False), 3)
    settled(r)
    assert r.of("no_catch") == [], why


def test_no_catch_needs_pokeballs_and_an_unresolved_non_gift_area():
    r = Rig()
    settled(r, has_pokeballs=False)
    for _ in range(3):
        r.step(snap([OWN], idle=False, has_pokeballs=False, battle=wild()))
    r.run(snap([OWN], idle=False, has_pokeballs=False), 3)
    settled(r, has_pokeballs=False)
    assert r.of("no_catch") == []
    r2 = Rig()
    settled(r2, area="gift_area")
    for _ in range(3):
        r2.step(snap([OWN], idle=False, area="gift_area", battle=wild()))
    r2.run(snap([OWN], idle=False, area="gift_area"), 3)
    settled(r2, area="gift_area")
    assert r2.of("no_catch") == []


def test_a_one_frame_chain_dropout_does_not_end_the_battle(rig):
    rig.step(snap([OWN], idle=False, battle=wild()))
    rig.step(snap([OWN], idle=False))                                       # reads.battle refused once
    rig.step(snap([OWN], idle=False, battle=wild()))
    assert rig.notes == [] and rig.pe.st.bt is not None                     # still the same encounter
    fight(rig, [OWN], final={"outcome": OUTCOMES["win"]})
    settled(rig)
    assert len(rig.of("no_catch")) == 1


def test_consecutive_battles_may_recycle_the_pointer_chain(rig):
    for _ in range(2):
        fight(rig, [OWN], final={"outcome": OUTCOMES["win"]})              # the same fingerprint "F1" both times
        settled(rig)
    assert len(rig.of("no_catch")) == 1                                     # second: area already resolved
    r = Rig()
    settled(r)
    fight(r, [OWN], final={"outcome": OUTCOMES["win"]})
    settled(r, area="A30", loc="Route 30")                                  # a new area: the 2nd battle counts again
    fight(r, [OWN], final={"outcome": OUTCOMES["win"]}, )
    # (the second battle ran in the A30 baseline) -> its own no_catch
    settled(r, area="A30", loc="Route 30")
    assert [e["area_id"] for e in r.of("no_catch")] == ["A29", "A30"]


# -- whiteout --------------------------------------------------------------------------------
def lose_battle(rig):
    for _ in range(4):
        rig.step(snap([OWN], idle=False, battle=wild(own_hp=0, outcome=OUTCOMES["lose"])))
    rig.run(snap([OWN], idle=False), 3)


def test_whiteout_after_loss_map_change_and_heal_exactly_once(rig):
    lose_battle(rig)
    rig.run(snap([{**OWN, "hp": 0}], idle=False), 3)                        # copy-back of the zero, blackout task running
    assert rig.of("whiteout") == []
    pc = snap([OWN], area="A30PC", loc="Pokemon Center")                    # healed + warped, idle again
    rig.run(pc, 4)
    assert rig.of("whiteout") == [{}] and rig.of("faint") and rig.of("area_enter")
    rig.run(pc, 10)
    assert len(rig.of("whiteout")) == 1


def test_a_warp_without_the_heal_is_not_a_whiteout(rig):
    lose_battle(rig)
    rig.run(snap([{**OWN, "hp": 0}], area="A30PC", loc="Pokemon Center"), 5)   # warped but not healed
    assert rig.of("whiteout") == []


def test_loss_without_the_blackout_warp_or_the_heal_is_not_a_whiteout(rig):
    lose_battle(rig)
    rig.run(snap([{**OWN, "hp": 0}]), 5)                                     # idle, same map, not healed
    assert rig.of("whiteout") == []
    rig.run(snap([OWN]), 5)                                                  # healed in place: still no warp
    assert rig.of("whiteout") == []
    rig.run(snap([OWN], idle=False), 1900)
    assert rig.of("whiteout") == [] and "whiteout_unconfirmed" in rig.notes


def test_poison_whiteout_without_a_battle(rig):
    rig.run(snap([OWN]), 3)
    rig.run(snap([{**OWN, "hp": 0}], idle=False), 3)
    assert rig.of("faint")
    rig.run(snap([OWN], area="A30PC", loc="Pokemon Center"), 4)
    assert rig.of("whiteout") == [{}]


def test_a_healed_party_with_a_map_change_but_no_loss_is_not_a_whiteout(rig):
    rig.run(snap([OWN], area="A30", loc="Route 30"), 5)
    assert rig.of("whiteout") == []


# -- settle + baseline -----------------------------------------------------------------------
def test_first_settled_view_is_learned_silently_and_a_dup_key_refuses():
    r = Rig()
    settled(r, [OWN, mon(0x31313131, 1)], boxes(1, **{key(0x41414141): 1}))
    assert r.events == [] and r.pe.known(r.pe, key(0x41414141))
    r.run(snap([OWN, OWN], idle=True), 3)
    assert r.events == [] and any(n.startswith("dup_key:") for n in r.notes)


# -- controls: the guards the assertions rely on are real ------------------------------------
def revert(needle: str, repl: str) -> Rig:
    src = SRC.read_text(encoding="utf-8")
    assert src.count(needle) == 1, needle
    return Rig(src.replace(needle, repl))


def test_control_without_the_settle_agreement_a_flicker_moves_a_mon():
    r = revert("st.agree >= cfg.settle_frames", "true")
    boxed = mon(0x31313131, 1)
    settled(r, [OWN, boxed])
    r.step(snap([OWN], boxes(2, **{boxed["key"]: 1})))
    settled(r, [OWN, boxed], boxes(1))
    assert "party_to_box" in r.names()           # the reverted module reports the flicker: the guard is the test's subject


def test_control_without_the_faint_debounce_a_flicker_faints():
    r = revert("st.zero[key] >= n and st.alive[key]", "st.alive[key]")
    settled(r)
    for hp in (20, 20, 0, 12, 20):
        r.step(snap([OWN], idle=False, battle=wild(own_hp=hp)))
    assert r.of("faint")


def test_control_without_the_end_debounce_a_chain_dropout_ends_the_battle():
    r = revert("if st.gone >= self.cfg.end_frames then", "if true then")
    settled(r)
    r.step(snap([OWN], idle=False, battle=wild()))
    r.step(snap([OWN], idle=False))              # one dropout frame
    r.step(snap([OWN], idle=False, battle=wild()))
    assert "pending_superseded" in r.notes       # reverted: the battle was declared over mid-fight


def test_control_without_the_foe_identity_every_new_mon_of_the_species_is_the_catch():
    r = revert("if fk == key or (pid == f.pid", "if f.species == 16 or (pid == f.pid")
    settled(r)
    fight(r, [OWN])
    settled(r, [OWN, mon(0x77777777, 1, species=16, level=2, hp=13, max_hp=13)])
    assert "gift" not in r.of("capture")[0]      # reverted: species equality made it "the capture"
