"""C1-8 row o probe, MODEL level: the pure API of lua/tests/probe_gen4_battle_faint.lua run under
lupa against a synthetic battle world built with the real PK4 codec (server/adapters/gen4_codec.py).

Nothing here is PHYSICAL evidence: it proves the instrument (guarded resolve, two-copy write,
four-byte readback, controls that can go red). The game's behaviour is the live probe's job."""

import random
import struct
from pathlib import Path

import pytest

lupa = pytest.importorskip("lupa")

from server.adapters import gen4_codec as codec  # noqa: E402

SCRIPT = Path(__file__).resolve().parents[2] / "lua/tests/probe_gen4_battle_faint.lua"
BASE = 0x02000000
FS_PTR, SAVE_PTR = 0x021D4158, 0x021D2228
FS, SUB0, MAN, BS, CTX = 0x022A01EC, 0x022A0334, 0x022A6B04, 0x022C020C, 0x022C32D8
SAVE, PARTY_OFF = 0x022D0000, 0x1234
SAVE_PARTY = SAVE + 0x10 + PARTY_OFF
PID, OTID = 0x5A3C91E7, 0x12345678


@pytest.fixture(scope="module")
def api():
    rt = lupa.LuaRuntime(unpack_returned_tuples=True)
    rt.globals().SLINK_GEN4_FAINT_TEST = True
    return rt, rt.execute(SCRIPT.read_text(encoding="utf-8"))


def plain_mon(pid, otid, species, hp, maxhp):
    p = bytearray(codec.PARTY_MON_SIZE)
    struct.pack_into("<I", p, 0, pid)
    struct.pack_into("<HHI", p, 8, species, 0, otid)  # block A (logical): species, item, otid
    struct.pack_into("<I", p, 0x88, 0)
    p[0x8C] = 5
    struct.pack_into("<HH", p, 0x8E, hp, maxhp)
    return bytes(p)


class World:
    """Byte-addressed main RAM with the HGSS battle chain and a 2-slot save party."""

    def __init__(self, *, btype=0, hp=20, maxhp=20, ehp=13, save_hdr=0x23014):
        self.m = bytearray(0x400000)
        w = self.w32
        w(FS_PTR, FS)
        w(SAVE_PTR, SAVE)
        w(FS, SUB0)
        w(SUB0 + 4, MAN)
        w(MAN + 0x0C, 12)
        w(MAN + 0x1C, BS)
        w(BS + 0x30, CTX)
        w(BS + 0x2C, btype)
        w(SAVE + save_hdr + 2 * 16 + 8, PARTY_OFF)
        self.recs = [plain_mon(PID, OTID, 155, hp, maxhp), plain_mon(0x0BADF00D, 0x777, 155, 11, 11)]
        self.party_ptr = [0x022C8000, 0x022C9000]  # trainerParty[0] (player), [1] (enemy)
        raw = [codec.encrypt_party(r) for r in self.recs]
        for base, count in ((SAVE_PARTY, 2), (self.party_ptr[0], 2)):
            w(base, 6)
            w(base + 4, count)
            for i, r in enumerate(raw):
                self.put(base + 8 + 0xEC * i, r)
        enemy = plain_mon(0x01010101, 0x2, 16, ehp, 13)
        w(self.party_ptr[1], 6)
        w(self.party_ptr[1] + 4, 1)
        self.put(self.party_ptr[1] + 8, codec.encrypt_party(enemy))
        w(BS + 0x68, self.party_ptr[0])
        w(BS + 0x6C, self.party_ptr[1])
        w(BS + 0x70, self.party_ptr[0])  # doubles: b&1 -> owner
        w(BS + 0x74, self.party_ptr[1])
        w(CTX + 8, 5)
        for b in range(4):
            self.m[CTX + 0x219C + b - BASE] = 6
        self.battler(0, 0, PID, OTID, 155, hp, maxhp)
        self.battler(1, 0, 0x01010101, 0x2, 16, ehp, 13)

    def battler(self, b, idx, pid, otid, species, hp, maxhp):
        mon = CTX + 0x2D40 + 0xC0 * b
        self.m[CTX + 0x219C + b - BASE] = idx
        self.w16(mon, species)
        self.w32(mon + 0x4C, hp)
        self.w32(mon + 0x50, maxhp)
        self.w32(mon + 0x68, pid)
        self.w32(mon + 0x74, otid)

    def put(self, a, data):
        self.m[a - BASE:a - BASE + len(data)] = data

    def get(self, a, n):
        return bytes(self.m[a - BASE:a - BASE + n])

    def w32(self, a, v):
        struct.pack_into("<I", self.m, a - BASE, v & 0xFFFFFFFF)

    def w16(self, a, v):
        struct.pack_into("<H", self.m, a - BASE, v & 0xFFFF)

    def mem(self, rt, log=None):
        m = self.m
        log = [] if log is None else log
        return rt.table_from({
            "r8": lambda a: m[a - BASE],
            "r16": lambda a: struct.unpack_from("<H", m, a - BASE)[0],
            "r32": lambda a: struct.unpack_from("<I", m, a - BASE)[0],
            "w8": lambda a, v: (log.append(("w8", a)), m.__setitem__(a - BASE, v & 0xFF))[1],
            "w16": lambda a, v: (log.append(("w16", a)), self.w16(a, v))[1],
            "w32": lambda a, v: (log.append(("w32", a)), self.w32(a, v))[1],
        })


def lt(rt, **kw):
    return rt.table_from(kw)


def want(rt, slot=0, pid=PID, otid=OTID):
    return lt(rt, pid=pid, otid=otid, slot=slot)


def rec0(world):
    return codec.decrypt_party(world.get(world.party_ptr[0] + 8, codec.PARTY_MON_SIZE))


def test_block_a_table_matches_codec(api):
    _, m = api
    for row in range(32):
        pid = row << 13
        assert m.block_a_offset(pid) == codec.block_offsets(pid)[0], row


def test_identity_and_hp_match_codec_for_random_records(api):
    rt, m = api
    rnd = random.Random(4)
    for _ in range(40):
        pid, otid = rnd.getrandbits(32), rnd.getrandbits(32)
        hp, mx = rnd.randint(1, 300), 300
        w = World(hp=1)
        raw = codec.encrypt_party(plain_mon(pid, otid, rnd.randint(1, 493), hp, mx))
        w.put(SAVE_PARTY + 8, raw)
        ident = m.read_identity(w.mem(rt), SAVE_PARTY + 8)
        assert (ident.pid, ident.otid) == (pid, otid)
        assert tuple(m.rec_hp(w.mem(rt), SAVE_PARTY + 8))[:2] == (hp, mx)


def test_read_identity_refuses_locked_and_bad_checksum(api):
    rt, m = api
    w = World()
    rec = SAVE_PARTY + 8
    w.w16(rec + 4, 1)  # partyDecrypted
    ident, why, _detail = m.read_identity(w.mem(rt), rec)
    assert ident is None and why == "locked"
    w.w16(rec + 4, 0)
    w.w16(rec + 6, (struct.unpack_from("<H", w.m, rec + 6 - BASE)[0] + 1) & 0xFFFF)
    ident, why, _detail = m.read_identity(w.mem(rt), rec)
    assert ident is None and why == "checksum"


def test_resolve_apply_verify_writes_both_copies_and_nothing_else(api):
    rt, m = api
    w = World()
    log = []
    mem = w.mem(rt, log)
    before = rec0(w)
    plan = m.resolve(mem, want(rt))
    assert plan.b == 0 and plan.idx == 0 and not plan.noop
    assert (plan.before.battle_hp, plan.before.party_hp) == (20, 20)
    m.apply(mem, plan, lt(rt, battle=True, party=True))
    # exactly one full-width battle-HP store (s32) and one u16 party-HP store, at the pinned offsets
    assert log == [("w32", CTX + 0x2D40 + 0x4C), ("w16", w.party_ptr[0] + 8 + 0x8E)]
    v = m.verify(mem, plan, lt(rt, battle=True, party=True))
    assert v.ok and list(v.battle_bytes.values()) == [0, 0, 0, 0] and v.party_plain == 0
    after = rec0(w)  # the real codec: checksum still valid, only HP changed
    assert struct.unpack_from("<H", after, 0x8E)[0] == 0
    assert after[:0x8E] == before[:0x8E] and after[0x90:] == before[0x90:]
    assert w.get(CTX + 0x2D40 + 0x4C, 4) == b"\0\0\0\0"
    # the save-array party and the enemy are untouched
    save_rec = codec.decrypt_party(w.get(SAVE_PARTY + 8, codec.PARTY_MON_SIZE))
    assert struct.unpack_from("<H", save_rec, 0x8E)[0] == 20


@pytest.mark.parametrize("mutate,reason", [
    ({"pid": PID ^ 1}, "identity"),
    ({"otid": OTID ^ 0x10000}, "identity"),
    ({"slot": 1}, "slot_not_active"),
    ({"slot": 3}, "slot_not_active"),
])
def test_resolve_refuses_wrong_key_or_slot(api, mutate, reason):
    rt, m = api
    w = World()
    plan, why = m.resolve(w.mem(rt), want(rt, **mutate))
    assert plan is None and why == reason
    assert w.get(CTX + 0x2D40 + 0x4C, 4) == struct.pack("<I", 20)


def test_resolve_refuses_sentinel_locked_unsupported_and_wrong_battlemon(api):
    rt, m = api
    w = World()
    w.m[CTX + 0x219C - BASE] = 6
    assert m.resolve(w.mem(rt), want(rt, slot=6))[1] == "slot_not_active"
    w = World()
    w.w16(w.party_ptr[0] + 8 + 4, 1)
    assert m.resolve(w.mem(rt), want(rt))[1] == "locked"
    for bt in (4, 8, 16):  # link, multi, tag
        assert World(btype=bt) and m.resolve(World(btype=bt).mem(rt), want(rt))[1] == "battle_type_unsupported"
    w = World()
    w.w32(CTX + 0x2D40 + 0x68, PID ^ 1)  # battle copy names another mon than the party copy
    assert m.resolve(w.mem(rt), want(rt))[1] == "battlemon_identity"
    w = World()
    w.w32(CTX + 0x2D40 + 0x4C, 0)  # one copy already zero, the other not
    assert m.resolve(w.mem(rt), want(rt))[1] == "copies_incoherent"
    w = World()
    w.w32(MAN + 0x0C, 74)  # another launched app: never a battle
    assert m.resolve(w.mem(rt), want(rt))[1] == "chain_overlay"


def test_same_species_slots_are_told_apart_by_pid_otid(api):
    rt, m = api
    w = World()
    # the SECOND slot becomes the active battler; same species, so only PID:OTID can tell them apart
    w.m[CTX + 0x219C - BASE] = 1
    w.battler(0, 1, 0x0BADF00D, 0x777, 155, 11, 11)
    assert m.resolve(w.mem(rt), want(rt, slot=0))[1] == "slot_not_active"
    assert m.resolve(w.mem(rt), want(rt, slot=1))[1] == "identity"
    assert m.resolve(w.mem(rt), want(rt, slot=1, pid=0x0BADF00D, otid=0x777)).idx == 1


def test_doubles_local_battlers_0_and_2_but_never_the_opposing_side(api):
    rt, m = api
    w = World(btype=2)
    w.battler(2, 1, 0x0BADF00D, 0x777, 155, 11, 11)  # second local battler, party slot 1
    w.battler(3, 0, PID, OTID, 155, 20, 20)  # an ENEMY battler that happens to reference slot 0
    plan = m.resolve(w.mem(rt), want(rt, slot=1, pid=0x0BADF00D, otid=0x777))
    assert plan.b == 2 and plan.own == 0
    assert m.resolve(w.mem(rt), want(rt, slot=0)).b == 0


def test_controls_pass_on_real_memory_and_never_mutate_it(api):
    rt, m = api
    w = World()
    snap = bytes(w.m)
    c = m.controls(w.mem(rt), want(rt))
    ok, why = m.judge_controls(c)
    assert ok, why
    assert bytes(w.m) == snap


@pytest.mark.parametrize("fault,expected", [
    ("identity", "wrong_pid_accepted"),
    ("slot", "wrong_slot_accepted"),
    ("locked", "locked_accepted"),
    ("verify_party", "battle_only_not_detected"),
    ("verify_high", "two_byte_stale_high_not_detected"),
])
def test_each_control_can_go_red(api, fault, expected):
    rt, m = api
    w = World()
    c = m.controls(w.mem(rt), want(rt), lt(rt, fault=fault))
    ok, why = m.judge_controls(c)
    assert not ok and why == expected


def test_two_byte_write_leaves_stale_high_half_that_readback_catches(api):
    rt, m = api
    w = World()
    mem = w.mem(rt)
    plan = m.resolve(mem, want(rt))
    w.w32(CTX + 0x2D40 + 0x4C, 0x00010014)  # a high half the 2-byte write will not touch
    w.w16(CTX + 0x2D40 + 0x4C, 0)
    m.apply(mem, plan, lt(rt, party=True))
    v = m.verify(mem, plan, lt(rt, battle=True, party=True))
    assert not v.ok and list(v.reasons.values()) == ["battle_hp_high_stale"]


LIVE = {"liveness": {"frames": 1500, "vbl_delta": 1500, "keys_seen": 30}}


def obs(**kw):
    base = {"controls_ok": True, "write": {"verify": {"ok": True, "reasons": {}}},
            "effect": {"outcome_frame": 900, "outcome_value": 2}, "latency": {"write_to_effect": 1},
            "heal": {1: {"frame": 1200, "saved_hp_at_entry": 0}}, "post_heal_saved_hp": 20, "saved_max_hp": 20}
    base.update(kw)
    return base


def to_lua(rt, v):
    if isinstance(v, dict):
        return rt.table_from({k: to_lua(rt, x) for k, x in v.items()})
    return v


def judge(api, scenario, **kw):
    rt, m = api
    return tuple(m.judge(m.SCENARIOS[scenario], to_lua(rt, obs(**kw))))


def test_judge_secondary_one_mon_requires_both_copies_independent_oracle_and_red_controls(api):
    assert judge(api, "seam_turnend")[0] == "PASS"
    assert judge(api, "seam_turnend", controls_ok=False, controls_why="x")[0] == "FAIL"
    assert judge(api, "seam_turnend", write=None)[0] == "OPEN"
    assert judge(api, "seam_turnend", write={"verify": {"ok": False, "reasons": {1: "party_hp_nonzero"}}})[0] == "FAIL"
    assert judge(api, "seam_turnend", effect={})[0] == "OPEN"
    # a result that only appears long after the write is not the write's effect
    assert judge(api, "seam_turnend", latency={"write_to_effect": 4361})[0] == "OPEN"
    assert judge(api, "seam_turnend", effect={"outcome_frame": 900, "outcome_value": 1})[0] == "FAIL"
    assert judge(api, "seam_turnend", heal={})[0] == "OPEN"
    # the zero must have reached the SAVE party before the heal: a lost copy-back goes red
    assert judge(api, "seam_turnend", heal={1: {"frame": 1, "saved_hp_at_entry": 20}})[0] == "FAIL"
    assert judge(api, "seam_turnend", post_heal_saved_hp=None)[0] == "OPEN"
    # the replacement branch on a ONE-mon party would be a different (wrong) game path
    assert judge(api, "seam_turnend", effect={"outcome_frame": 900, "outcome_value": 2, "repl_flag_frame": 5})[0] == "FAIL"
    assert judge(api, "poll_fightmenu")[0] == "OPEN"  # exploratory: never a gate


def test_judge_control_needs_liveness_and_the_specific_wrong_outcome_not_just_no_lose(api):
    bad_write = {"write": {"verify": {"ok": False, "reasons": {1: "party_hp_nonzero"}}}, "heal": {}}
    base = {**bad_write, **LIVE}
    # battle_only: the game must have taken the replacement branch with the live party copy
    assert judge(api, "battle_only", **base, effect={"repl_flag_frame": 5})[0] == "PASS"
    assert judge(api, "battle_only", **base, effect={})[0] == "OPEN"  # "no LOSE" alone fits a hung game
    assert judge(api, "battle_only", **bad_write, effect={"repl_flag_frame": 5})[0] == "OPEN"  # no liveness proof
    stalled = {"liveness": {"frames": 1500, "vbl_delta": 10, "keys_seen": 30}}
    assert judge(api, "battle_only", **bad_write, **stalled, effect={"repl_flag_frame": 5})[0] == "OPEN"
    deaf = {"liveness": {"frames": 1500, "vbl_delta": 1500, "keys_seen": 0}}
    assert judge(api, "battle_only", **bad_write, **deaf, effect={"repl_flag_frame": 5})[0] == "OPEN"
    # party_only: the game must have restored the party-copy HP
    assert judge(api, "party_only", **base, effect={"party_restored_frame": 9})[0] == "PASS"
    assert judge(api, "party_only", **base, effect={})[0] == "OPEN"
    # a single-copy write that reads back clean, or that reaches the save as zero + LOSE, means the oracle is blind
    assert judge(api, "battle_only", write={"verify": {"ok": True, "reasons": {}}}, **LIVE)[0] == "FAIL"
    assert judge(api, "battle_only", write={"verify": {"ok": False, "reasons": {}}}, **LIVE)[0] == "FAIL"


P2_OK = {"effect": {"repl_flag_frame": 40, "outcome_final": 1, "chain_gone_frame": 900},
         "p2": {"switched_frame": 300}, "heal": {}, "blackout": {}, "saved_final_slots": {"s0": 0, "s1": 20},
         "map_before": 33, "map_after": 33, **LIVE}


def test_judge_p2_primary_is_the_replacement_path_and_never_a_whiteout(api):
    assert judge(api, "seam_ufce_bit_p2", **P2_OK)[0] == "PASS"
    assert judge(api, "seam_turnend_p2", **P2_OK)[0] == "PASS"
    cases = [
        ({"effect": {**P2_OK["effect"], "lose_frame": 50}}, "FAIL"),  # LOSE byte on a 2-mon party
        ({"heal": {1: {"frame": 1, "saved_hp_at_entry": 0}}}, "FAIL"),  # whiteout heal
        ({"blackout": {1: {"frame": 1}}}, "FAIL"),
        ({"effect": {**P2_OK["effect"], "repl_flag_frame": None}}, "OPEN"),  # replacement branch not observed
        ({"p2": {}}, "OPEN"),  # slot 1 never sent in
        ({"effect": {**P2_OK["effect"], "outcome_final": 0}}, "OPEN"),  # battle did not finish
        ({"effect": {**P2_OK["effect"], "outcome_final": 2}}, "FAIL"),
        ({"saved_final_slots": {"s0": 7, "s1": 20}}, "FAIL"),  # copy-back lost the zero on slot 0
        ({"saved_final_slots": {"s0": 0, "s1": 0}}, "FAIL"),  # slot 1 not alive
        ({"map_after": 63}, "FAIL"),
        ({"liveness": None}, "OPEN"),
        ({"write": {"verify": {"ok": False, "reasons": {1: "party_hp_nonzero"}}}}, "FAIL"),
    ]
    for patch, want in cases:
        assert judge(api, "seam_ufce_bit_p2", **{**P2_OK, **patch})[0] == want, patch


def test_scenario_kinds_follow_the_owner_ruling(api):
    _, m = api
    kinds = {k: v.kind for k, v in m.SCENARIOS.items()}
    assert kinds["seam_ufce_bit_p2"] == kinds["seam_turnend_p2"] == "primary"
    assert kinds["seam_ufce_bit"] == kinds["seam_turnend"] == "secondary"
    assert m.SCENARIOS.seam_ufce_bit_p2.faint_bit and not m.SCENARIOS.seam_turnend_p2.faint_bit


# ---- smoke: the LIVE run() flow against a fake emulator + a crude game MODEL (not the game) ----
LOC = 0x022A5000
TURN_END, UFCE, HEAL, BLACKOUT = 0x0224A958, 0x0224A70C, 0x02090C1C, 0x02052858
SYS = 0x021D110C  # gSystem (pack profile.system)
STUBS = """
memory = {read_u8 = function(a) return PY.r8(a) end, read_u16_le = function(a) return PY.r16(a) end,
  read_u32_le = function(a) return PY.r32(a) end, write_u8 = function(a, v) PY.w8(a, v) end,
  write_u16_le = function(a, v) PY.w16(a, v) end, write_u32_le = function(a, v) PY.w32(a, v) end}
emu = {framecount = function() return PY.frame() end, frameadvance = function() PY.advance() end,
  limitframerate = function() end, getregister = function(n) return PY.reg(n) end}
joypad = {set = function(t) PY.joy(t.A and 1 or 0, t.Down and 1 or 0) end}
savestate = {load = function() return true end}
client = {screenshot = function() end, speedmode = function() end, exit = function() PY.exit() end}
event = {on_bus_exec = function(cb, addr) return PY.hook(cb, addr) end,
  unregisterbyid = function(h) PY.unhook(h) end}
"""


class Sim:
    """MODEL of the game, only rich enough to drive probe_gen4_battle_faint.lua end to end:
    menu -> (two A presses) -> commands 6..11 -> TurnEnd hook -> sweeps. Both HP copies zero: LOSE on a
    one-mon run (p2=False) -> copy-back -> Task_Blackout -> HealParty; with p2=True the D540 replacement
    branch (flag ctx+0x13C) waits for Down + two A presses, switches slot 1 in, a FIGHT wins, copy-back, no
    heal. Battle HP 0 with the party copy alive: replacement flag + stuck. Party HP 0 only: the game's
    battle->party copy restores it. gSystem.vblankCounter/newKeys advance like the game's. Nothing here is a
    game claim."""

    def __init__(self, world, noise=False, copyback=True, p2=False, hung=False, deaf_replace=False, wrong_pid=False):
        self.noise, self.copyback, self.p2, self.hung, self.deaf = noise, copyback, p2, hung, deaf_replace
        self.wrong_pid = wrong_pid
        self.w, self.frame, self.hooks, self.n = world, 100, {}, 0
        self.joy_a = self.a_prev = self.joy_down = self.down_prev = False
        self.a_edges, self.down_edges = 0, 0
        self.state, self.t, self.exited, self.regs = "menu", 0, False, {}
        for addr, word in ((TURN_END, 0x1C0CB538), (UFCE, 0xB082B5F8), (HEAL, 0xB083B5F0),
                           (BLACKOUT, 0xB086B5F8)):
            world.w32(addr, word)
        world.w32(FS + 0x10, 0)
        world.w32(FS + 0x6C, 1)
        world.w32(FS + 0x20, LOC)
        world.w32(LOC, 33)

    def u32(self, a):
        return struct.unpack_from("<I", self.w.m, a - BASE)[0]

    def fire(self, addr, r0=BS, r1=CTX):
        self.regs = {"ARM9 r0": r0, "ARM9 r1": r1, "ARM9 r15": addr + 4}
        for a, cb in list(self.hooks.values()):
            if a == addr:
                cb(addr, self.u32(addr), 0)

    def noisy_hits(self):
        """Hits the seam must DROP: wrong command, another battle's pointers, another overlay's bytes."""
        self.fire(TURN_END)  # command is 7 here, not 12
        self.fire(TURN_END, r0=BS + 4)
        word = self.u32(TURN_END)
        self.w.w32(TURN_END, 0)
        self.fire(TURN_END)
        self.w.w32(TURN_END, word)

    def hp(self, base, slot=0):
        rec = codec.decrypt_party(self.w.get(base + 8 + 0xEC * slot, codec.PARTY_MON_SIZE))
        return struct.unpack_from("<H", rec, 0x8E)[0]

    def set_hp(self, base, slot, hp):
        a = base + 8 + 0xEC * slot
        rec = bytearray(codec.decrypt_party(self.w.get(a, codec.PARTY_MON_SIZE)))
        struct.pack_into("<H", rec, 0x8E, hp)
        self.w.put(a, codec.encrypt_party(bytes(rec)))

    def advance(self):
        self.frame += 1
        if not self.hung:
            self.w.w32(SYS + 0x2C, self.u32(SYS + 0x2C) + 1)  # vblankCounter
        a, self.joy_a = self.joy_a, False
        d, self.joy_down = self.joy_down, False
        self.a_edges += a and not self.a_prev
        self.down_edges += d and not self.down_prev
        self.w.w32(SYS + 0x48, 1 if (a and not self.a_prev) else 0)  # newKeys bit0 = A
        self.a_prev, self.down_prev = a, d
        getattr(self, "tick_" + self.state)()

    def tick_menu(self):
        if self.a_edges >= 2:
            self.state, self.t = "turn", 0

    def tick_turn(self):
        self.t += 1
        cmds = {4: 6, 8: 7, 12: 8, 16: 9, 20: 10}
        if self.t in cmds:
            self.w.w32(CTX + 8, cmds[self.t])
        if self.t == 14 and self.noise:
            self.noisy_hits()
        if self.t == 24:
            self.w.w32(CTX + 8, 11)
            self.fire(UFCE)
        if self.t == 28:
            self.w.w32(CTX + 8, 12)
            self.fire(TURN_END)
            self.sweep()

    def sweep(self):
        pty = self.w.party_ptr[0]
        bhp, php = self.u32(CTX + 0x2D40 + 0x4C), self.hp(pty)
        other_alive = self.hp(pty, 1) > 0
        if bhp == 0 and php == 0:
            if self.p2 and other_alive:  # D540: replacement branch
                self.w.w32(CTX + 0x13C, 1)
                self.w.w32(CTX + 8, 22)
                self.state, self.t, self.a_edges, self.down_edges = "replace", 0, 0, 0
            else:  # D7EC: nothing left -> LOSE
                self.w.m[BS + 0x2420 - BASE] = 2
                self.state, self.t = "ending", 0
        elif bhp == 0:  # party copy still alive: D540 offers a replacement that cannot work
            self.w.w32(CTX + 0x13C, 1)
            self.w.w32(CTX + 8, 22)
            self.state = "stuck"
        elif php == 0:  # only the party copy was zeroed: the next battle->party copy restores it
            self.set_hp(pty, 0, bhp)
            self.w.w32(CTX + 8, 2)
            self.state, self.t = "next", 0
        else:
            self.w.w32(CTX + 8, 2)
            self.state, self.t = "next", 0

    def tick_stuck(self):
        pass

    def tick_replace(self):
        if not self.deaf and self.down_edges >= 1 and self.a_edges >= 4:  # 2 prompt As, then Down + A + A on the party screen
            self.w.m[CTX + 0x219C - BASE] = 1  # selectedMonIndex[0] = slot 1
            second = codec.decrypt_party(self.w.get(self.w.party_ptr[0] + 8 + 0xEC, codec.PARTY_MON_SIZE))
            mon = CTX + 0x2D40
            self.w.w32(mon + 0x68, 0xDEAD if self.wrong_pid else struct.unpack_from("<I", second, 0)[0])
            self.w.w32(mon + 0x74, struct.unpack_from("<I", second, 8 + 4)[0])
            self.w.w32(mon + 0x4C, self.hp(self.w.party_ptr[0], 1))
            self.w.w32(mon + 0x50, self.hp(self.w.party_ptr[0], 1))
            self.w.w32(CTX + 0x13C, 0)
            self.w.w32(CTX + 8, 5)
            self.state, self.a_edges = "menu2", 0

    def tick_menu2(self):
        if self.a_edges >= 2:  # a FIGHT: the enemy faints, the battle is WON
            self.w.m[BS + 0x2420 - BASE] = 1
            self.state, self.t = "ending", 0

    def tick_next(self):
        self.t += 1
        if self.t == 8:
            self.w.w32(CTX + 8, 5)
            self.state, self.a_edges = "menu", 0

    def tick_ending(self):
        self.t += 1
        won = self.w.m[BS + 0x2420 - BASE] == 1
        if self.t == 30:  # copy-back (Party_Copy), then the application is gone
            n = 8 + 0xEC * 2
            if self.copyback:
                self.w.put(SAVE_PARTY, self.w.get(self.w.party_ptr[0], n))
            self.w.w32(SUB0 + 4, 0)
        if won:
            if self.t == 31:
                self.state = "idle"
            return
        if self.t == 40:
            self.fire(BLACKOUT)
            self.w.w32(LOC, 10)
        if self.t == 41:
            self.fire(HEAL)
            self.set_hp(SAVE_PARTY, 0, struct.unpack_from("<H", codec.decrypt_party(
                self.w.get(SAVE_PARTY + 8, codec.PARTY_MON_SIZE)), 0x90)[0])
            self.state = "idle"

    def tick_idle(self):
        pass


def run_probe(tmp_path, monkeypatch, scenario, fault=None, cfg_extra=None, **sim_kw):
    import json

    rt = lupa.LuaRuntime(unpack_returned_tuples=True)
    world = World()
    sim = Sim(world, **sim_kw)
    mem = world.mem(rt)

    def hook(cb, addr):
        sim.n += 1
        sim.hooks[sim.n] = (addr, cb)
        return f"guid-{sim.n}"

    py = rt.table_from({
        "r8": lambda a: mem.r8(a), "r16": lambda a: mem.r16(a), "r32": lambda a: mem.r32(a),
        "w8": lambda a, v: mem.w8(a, v), "w16": lambda a, v: mem.w16(a, v), "w32": lambda a, v: mem.w32(a, v),
        "frame": lambda: sim.frame, "advance": sim.advance, "reg": lambda n: sim.regs.get(n, 0),
        "joy": lambda a, d: (setattr(sim, "joy_a", bool(a)), setattr(sim, "joy_down", bool(d))),
        "exit": lambda: setattr(sim, "exited", True), "hook": hook, "unhook": lambda h: None,
    })
    rt.globals().PY = py
    rt.execute(STUBS)
    prof = json.loads((SCRIPT.parents[2] / "data/games/gen4_hgss/profile.json").read_text(encoding="utf-8"))
    prof = prof["titles"]["heartgold"]["profile"]
    cfg = tmp_path / "cfg.json"
    out = tmp_path / "receipt.txt"
    cfg.write_text(json.dumps({
        "run_id": "t/x", "title": "heartgold", "rom_sha1": "ab" * 20, "scenario": scenario, "state_path": "s",
        "shot_dir": str(tmp_path), "requested_rate": 300, "fault": fault, "max_frames": 900, "move_right": True,
        "script_sha256": "s", "profile_sha256": "p", "source_head": "cut",
        "pack": {"save": prof["save"], "battle": prof["battle"], "system": prof["system"]},
        "setup": "SYNTH" if scenario.endswith("_p2") else "NATIVE", "synth": {"sidecar_sha256": "00" * 32},
        **(cfg_extra or {})}), encoding="utf-8")
    monkeypatch.setenv("SLINK_ROOT", str(SCRIPT.parents[2]).replace("\\", "/"))
    monkeypatch.setenv("SLINK_GEN4_FAINT_CONFIG", str(cfg))
    monkeypatch.setenv("SLINK_GEN4_FAINT_OUT", str(out))
    rt.execute(SCRIPT.read_text(encoding="utf-8"))
    assert sim.exited
    lines = out.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2 and lines[1].startswith("RESULT: ")
    status, _, raw = lines[0][len("PROBE o "):].partition(" ")
    assert lines[1] == f"RESULT: {status}"
    return status, json.loads(raw), world


def test_smoke_secondary_one_mon_scenario_reaches_pass_through_the_real_run_flow(tmp_path, monkeypatch):
    status, payload, world = run_probe(tmp_path, monkeypatch, "seam_turnend")
    o = payload["observation"]
    assert status == "PASS", payload["reason"]
    assert payload["callback_errors"] == 0 and payload["producer"] == "C1-8" and payload["negative_control"]
    assert payload["setup"] == "NATIVE"
    assert o["write"]["where"] == "BattleControllerPlayer_TurnEnd" and o["write"]["cmd"] == 12
    assert o["effect"]["outcome_value"] == 2 and o["heal"][0]["saved_hp_at_entry"] == 0
    assert o["post_heal_saved_hp"] == 20 and o["map_before"] == 33 and o["map_after"] == 10
    assert o["seam"]["hits"] >= 1 and o["seam"]["wrong_image"] == 0 and o["seam"]["stale"] == 0
    assert o["latency"]["cmd_to_write"] > 0 and o["latency"]["write_to_effect"] is not None
    assert o["seam"]["first"]["r0"] == BS and o["seam"]["first"]["r1"] == CTX  # raw registers recorded
    assert o["seam"]["regs_mode"] == "r0r1"
    assert world.get(SAVE_PARTY, 4) == struct.pack("<I", 6)


@pytest.mark.parametrize("scenario", ["seam_turnend_p2", "seam_ufce_bit_p2"])
def test_smoke_p2_primary_reaches_the_replacement_path_and_passes(tmp_path, monkeypatch, scenario):
    status, payload, world = run_probe(tmp_path, monkeypatch, scenario, p2=True)
    o = payload["observation"]
    assert status == "PASS", payload["reason"]
    assert payload["setup"] == "SYNTH" and payload["synth"]["sidecar_sha256"] == "00" * 32
    assert o["effect"]["repl_flag_frame"] and not o["effect"].get("lose_frame") and o["p2"]["switched_frame"]
    assert o["effect"]["outcome_final"] == 1 and o["heal"] == [] and o["blackout"] == []
    assert o["saved_final_slots"] == {"s0": 0, "s1": 11} and o["map_after"] == o["map_before"] == 33
    # independent oracle: the real codec on the final save-array bytes
    hps = [struct.unpack_from("<H", codec.decrypt_party(world.get(SAVE_PARTY + 8 + 0xEC * i, codec.PARTY_MON_SIZE)), 0x8E)[0]
           for i in (0, 1)]
    assert hps == [0, 11]


def test_smoke_p2_goes_red_when_the_game_whites_out_and_open_when_slot1_never_goes_in(tmp_path, monkeypatch):
    status, payload, _ = run_probe(tmp_path, monkeypatch, "seam_turnend_p2", p2=False)  # model whites out
    assert status == "FAIL" and "LOSE" in payload["reason"], payload["reason"]
    status, payload, _ = run_probe(tmp_path, monkeypatch, "seam_turnend_p2", p2=True, deaf_replace=True)
    assert status == "OPEN" and "slot 1 never sent in" in payload["reason"], payload["reason"]


def test_smoke_switch_in_needs_the_slot1_identity_not_just_the_index(tmp_path, monkeypatch):
    status, payload, _ = run_probe(tmp_path, monkeypatch, "seam_turnend_p2", p2=True, wrong_pid=True)
    assert status == "OPEN" and "slot 1 never sent in" in payload["reason"], payload["reason"]


@pytest.mark.parametrize("scenario", ["battle_only", "party_only"])
def test_smoke_single_copy_controls_pass_on_liveness_and_the_specific_wrong_outcome(tmp_path, monkeypatch, scenario):
    status, payload, _ = run_probe(tmp_path, monkeypatch, scenario)
    o = payload["observation"]
    assert status == "PASS", payload["reason"]
    assert o["write"]["verify"]["ok"] is False and o["effect"].get("outcome_frame") is None
    assert o["liveness"]["vbl_delta"] >= 0.9 * o["liveness"]["frames"] and o["liveness"]["keys_seen"] >= 3
    flag = "repl_flag_frame" if scenario == "battle_only" else "party_restored_frame"
    assert o["effect"][flag]


def test_smoke_battle_only_on_a_hung_game_is_not_a_pass(tmp_path, monkeypatch):
    status, payload, _ = run_probe(tmp_path, monkeypatch, "battle_only", hung=True)
    assert status == "OPEN" and "kept running" in payload["reason"], payload["reason"]


def test_smoke_exploratory_scenarios_are_never_a_gate(tmp_path, monkeypatch):
    status, payload, _ = run_probe(tmp_path, monkeypatch, "poll_fightmenu")
    assert status == "OPEN" and "exploratory" in payload["reason"], payload["reason"]
    assert payload["observation"]["write"]["verify"]["ok"] is True
    status, payload, _ = run_probe(tmp_path, monkeypatch, "seam_ufce_bit")
    assert status == "PASS" and payload["observation"]["write"]["where"].endswith("UpdateFieldConditionExtra")


def test_smoke_disabled_check_turns_the_whole_run_red_before_any_write(tmp_path, monkeypatch):
    status, payload, world = run_probe(tmp_path, monkeypatch, "seam_turnend", fault="identity")
    assert status == "FAIL" and "wrong_pid_accepted" in payload["reason"]
    assert "write" not in payload["observation"]
    assert world.get(CTX + 0x2D40 + 0x4C, 4) == struct.pack("<I", 20)


def test_smoke_seam_drops_wrong_state_stale_pointers_and_wrong_overlay_hits(tmp_path, monkeypatch):
    status, payload, _ = run_probe(tmp_path, monkeypatch, "seam_turnend", noise=True)
    seam = payload["observation"]["seam"]
    assert status == "PASS", payload["reason"]
    assert (seam["bad_state"], seam["stale"], seam["wrong_image"]) == (1, 1, 1)
    assert seam["hits"] == 1 and payload["observation"]["write"]["cmd"] == 12  # only the real TurnEnd wrote


def test_smoke_lost_copy_back_turns_the_secondary_oracle_red(tmp_path, monkeypatch):
    status, payload, _ = run_probe(tmp_path, monkeypatch, "seam_turnend", copyback=False)
    assert status == "FAIL" and "copy-back lost the zero" in payload["reason"]


def test_smoke_p2_lost_copy_back_turns_the_replacement_oracle_red(tmp_path, monkeypatch):
    status, payload, _ = run_probe(tmp_path, monkeypatch, "seam_ufce_bit_p2", p2=True, copyback=False)
    assert status == "FAIL" and "copy-back" in payload["reason"], payload["reason"]


def test_smoke_poll_vs_hook_is_a_measurement_of_exact_dispatches(tmp_path, monkeypatch):
    status, payload, _ = run_probe(tmp_path, monkeypatch, "seam_turnend")
    pvh = payload["observation"]["poll_vs_hook"]
    assert status == "PASS" and set(pvh) == {"turnend", "ufce"}
    assert pvh["turnend"]["cmd"] == 12 and pvh["ufce"]["cmd"] == 11
    # both seams count exact hook dispatches in EVERY scenario (the non-writing one is an observer)
    assert pvh["turnend"]["dispatches"] == 1 and pvh["ufce"]["dispatches"] == 1
    assert "hits_without_poll_sight" not in payload["observation"]["seam"]


def test_smoke_regs_unreliable_is_reported_and_chain_only_is_a_recorded_fallback(tmp_path, monkeypatch):
    """If every hit is classed stale (r0/r1 unreadable) the run says so; regs=false classifies by chain + command + pin."""
    orig = Sim.fire

    def bad_regs(self, addr, r0=BS, r1=CTX):
        return orig(self, addr, r0=0, r1=0)

    monkeypatch.setattr(Sim, "fire", bad_regs)
    status, payload, _ = run_probe(tmp_path, monkeypatch, "seam_turnend")
    assert status == "OPEN" and "ALL seam hits classified stale" in payload["observation"]["no_write_reason"]
    assert payload["observation"]["seam"]["first"]["r0"] == 0  # the raw (wrong) register is visible in the receipt
    status, payload, _ = run_probe(tmp_path, monkeypatch, "seam_turnend", cfg_extra={"regs": False})
    assert status == "PASS" and payload["observation"]["seam"]["regs_mode"] == "chain_only"
