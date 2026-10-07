"""Polished trade card C1a: the held PROPOSER-ONLY trade service, commit disabled
(patch/polished/src/trade_service.asm; docs/polished/TRADE.md sections 11, 12, 14-17).

Evidence: the REAL assembled bytes (the committed UPS applied to the pinned release ROM) run on the real SM83
machine (tests/unit/polished_sm83.py: real SP, flags, `ld hl, sp+n`, the Polished `rst FarCall` model) against a
SCRIPTED HOST implemented in Python inside the DelayFrame trap. The host acts on the 16-byte lease bytes exactly
as lua/gb_trade_lease.lua does (QUERY answer: offsets 10..15 then ACK last; OFFER answer: result then ACK; APPLY:
the whole frame with the generation previous+1 written LAST; RELEASE: command 8). The native routines the service
calls (DelayFrame, JoyTextDelay, PrintText, YesNoBox, the farcall to SelectTradeOrDayCareMon) are TRAPS; every
other byte (the Slink code, the item table, snapshot, validators, `rst AddNTimes`) is the built ROM's own.

Every scenario asserts: the exact lease write ORDER (a publication ends with the generation, then the ACK; the
sequence is matched against the QUERY / OFFER / pickup / DONE / close patterns), a balanced stack (sp_delta == 0),
that no CPU write lands outside the allowed set (lease, OT slot 1 snapshot, hROMBank, the stack), that no result 0 is
ever published and that no commit symbol is called. Byte-patch MUTANTS of the built bytes must each go red in a
named scenario.

Absent input skips (no cached release ROM); present-but-wrong input fails.
"""
from __future__ import annotations

import os
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "patch" / "tools"))
sys.path.insert(0, str(REPO / "tests" / "unit"))

import build_polished_companion as pc  # noqa: E402
import polished_sm83 as S  # noqa: E402
from build_gen2_companion import _symbols  # noqa: E402
from make_ups import ups_apply  # noqa: E402

RELEASE = Path(os.environ.get("SLINK_WORK_ROOT", "F:/slink-work")) / "cache/polished/release/polishedcrystal-3.2.3.gbc"
CLEAN_SYM = REPO / "data/polished/polishedcrystal.sym"
OVERLAY_SYM = REPO / "data/polished/polished_slink.sym"
UPS = REPO / "patch/dist/SLink-Polished.ups"
SRC = REPO / "patch/polished/src/trade_service.asm"

BANK7E = 0x7E
HROMBANK = 0xFF87
PAD_B = 0x02
PARTYMENUACTION_GIVE_MON = 6            # constants/menu_constants.asm: the seventh const of the PartyMenuQualityPointers block
SELECT_TRADE_MON = (0x14, 0x4002)       # SelectTradeOrDayCareMon (clean sym; asserted in test_symbols)
LEASE_OFS, LEASE_SIZE = 14, 16
MAGIC = (0x53, 0x4C, 0x54, 0x31)
QUERY, OFFER, APPLY, DONE, CMD_RELEASE = 1, 2, 5, 7, 8
STEP_LIMIT = 6_000_000
TOKEN = (0x11, 0x22, 0x33, 0x44)
P, OTL, NICKL = 48, 11, 11

# a commit-class native routine the proposer must never reach (clean sym names; absent names are skipped)
COMMIT_NATIVES = ("AddTempMonToParty", "RemoveMonFromParty", "ShiftPartySlotToEnd", "DoNPCTrade", "Link_SaveGame",
                  "SaveAfterLinkTrade", "SaveGameData", "TradeAnimation", "DoTradeAnimation", "HealParty",
                  "Special_TryQuickSave")


# ------------------------------------------------------------------ environment

@pytest.fixture(scope="module")
def env():
    if not RELEASE.is_file():
        pytest.skip(f"pinned Polished release ROM not cached at {RELEASE}")
    rom = ups_apply(RELEASE.read_bytes(), UPS.read_bytes())
    return Env(bytes(rom), _symbols(OVERLAY_SYM), _symbols(CLEAN_SYM))


@dataclass
class Env:
    rom: bytes
    sym: dict
    clean: dict

    def a(self, name: str) -> int:
        return self.sym[name][1]

    def flat(self, name: str) -> int:
        return pc._flat(*self.sym[name])

    @property
    def lease(self) -> int:
        return self.a("wSlinkMailbox") + LEASE_OFS


# ------------------------------------------------------------------ the lease write patterns

class Bad(AssertionError):
    pass


def segment(lw: list[tuple[int, int]]) -> tuple[str, list[dict]]:
    """Split the CPU's lease writes into the protocol's publications; anything unmatched is an AssertionError.

    Q = QUERY (header, command, zeroed answer bytes, ACK = old generation, generation = new LAST)
    O = OFFER (slot, result $FF, command, ACK, generation LAST)   A = the APPLY pickup ACK
    D = DONE (result, header, token, slot, command, then generation and ACK = the same generation LAST)
    C = close (command, available, mask)
    """
    out, info, i = [], [], 0
    while i < len(lw):
        off = lw[i][0]
        if off == 0:
            want = [(0, 0x53), (1, 0x4C), (2, 0x54), (3, 0x31), (4, 1), (5, 1), (10, 0), (11, 0), (7, None), (6, None)]
            kind = "Q"
        elif off == 9:
            want = [(9, None), (8, 0xFF), (5, 2), (7, None), (6, None)]
            kind = "O"
        elif off == 8:
            want = [(8, None), (0, 0x53), (1, 0x4C), (2, 0x54), (3, 0x31), (4, 1), (12, None), (13, None), (14, None),
                    (15, None), (9, None), (5, 7), (6, None), (7, None)]
            kind = "D"
        elif off == 5:
            want, kind = [(5, 0), (10, 0), (11, 0)], "C"
        elif off == 7:
            want, kind = [(7, None)], "A"
        else:
            raise Bad(f"a lease write at offset {off} starts no known publication: {lw[max(0, i - 3):i + 3]}")
        got = lw[i:i + len(want)]
        if len(got) < len(want) or any(g[0] != w[0] or (w[1] is not None and g[1] != w[1]) for g, w in zip(got, want, strict=True)):
            raise Bad(f"the {kind} publication is out of order or incomplete at write {i}: got {got}, want offsets "
                      f"{[w[0] for w in want]}")
        vals = dict(got)
        if kind in "QO" and vals[6] != (vals[7] + 1) & 0xFF:
            raise Bad(f"{kind}: generation {vals[6]:#04x} is not the ACK {vals[7]:#04x} + 1")
        if kind == "D":
            if vals[6] != vals[7]:
                raise Bad("DONE: generation and ACK differ")
            if vals[8] == 0:
                raise Bad("DONE with result 0 (a commit is disabled: only result 1 is honest)")
        out.append(kind)
        info.append({"kind": kind, **{f"o{o}": v for o, v in vals.items()}})
        i += len(want)
    return "".join(out), info


# ------------------------------------------------------------------ party / staging images

def own_record(i: int) -> bytes:
    """A valid 48-byte party record: species, item, nature, extspecies, level; the rest is deterministic noise."""
    r = bytearray((i * 37 + j * 11 + 5) & 0xFF for j in range(P))
    r[0] = (25, 4, 7, 1, 133, 150)[i]
    r[1] = (0x0D, 0x00, 0x1E, 0x00, 0x05, 0x00)[i]       # held item (never mail)
    r[20] = 3
    r[21] = 0
    r[31] = 20 + i
    return bytes(r)


def incoming_record() -> bytes:
    r = bytearray((j * 3 + 0x40) & 0xFF for j in range(P))
    r[0], r[1], r[20], r[21], r[31] = 150, 0, 7, 0, 30
    return bytes(r)


def name(seed: int, n: int = 11) -> bytes:
    """A valid name field: glyphs >= $5F, the terminator, filler."""
    return bytes([0x80 + seed, 0x81 + seed, 0x82 + seed, 0x53]) + bytes([0x00] * (n - 4))


@dataclass
class Stage:
    rec: bytes = field(default_factory=incoming_record)
    ot: bytes = field(default_factory=lambda: name(10))
    nick: bytes = field(default_factory=lambda: name(20))
    sender: bytes = field(default_factory=lambda: name(30))


# ------------------------------------------------------------------ the scripted host

class HostTimeout(AssertionError):
    pass


class Host:
    """Acts on the lease exactly as lua/gb_trade_lease.lua does, one step per DelayFrame."""

    def __init__(self, rig: Rig, m: S.SM83):
        self.rig, self.m = rig, m
        self.expected: list[int] | None = None
        self.token: tuple | None = None
        self.done_result: int | None = None

    # raw lease access (pokes are the HOST's writes: unlogged, never part of the CPU write set)
    def rd(self, o: int) -> int:
        return self.m.peek(self.rig.lease + o)[0]

    def wr(self, o: int, v: int) -> None:
        self.m.poke(self.rig.lease + o, v & 0xFF)

    def frames(self, n: int):
        for _ in range(n):
            yield

    def until(self, cond: Callable[[], bool], limit: int = 5000):
        for _ in range(limit):
            if cond():
                return
            yield
        raise HostTimeout("the condition never held")

    def header(self, command: int) -> bool:
        return tuple(self.rd(i) for i in range(4)) == MAGIC and self.rd(4) == 1 and self.rd(5) == command

    # QUERY: poll_query / answer_query
    def query_pending(self) -> bool:
        return self.header(QUERY) and self.rd(7) != self.rd(6)

    def answer_query(self, mask: int, token=TOKEN, available: int | None = None) -> None:
        gen = self.rd(6)
        for o, v in zip(range(10, 16), (int(bool(mask)) if available is None else available, mask, *token), strict=True):
            self.wr(o, v)
        self.wr(7, gen)                         # publication last
        self.token = tuple(token) if mask else None

    # OFFER: poll_offer / answer_offer
    def offer_pending(self) -> bool:
        return (self.header(OFFER) and self.token is not None and self.rd(7) != self.rd(6) and self.rd(9) < 6
                and tuple(self.rd(12 + i) for i in range(4)) == self.token)

    def answer_offer(self, ok: bool = True) -> None:
        self.wr(8, 0 if ok else 1)
        self.wr(7, self.rd(6))                  # result before acknowledgement

    # APPLY: arm
    def stage(self, st: Stage | None = None) -> None:
        st = st or Stage()
        r = self.rig
        self.m.poke(r.a("wOTPartyMon1"), st.rec)
        self.m.poke(r.a("wOTPartyMonOTs"), st.ot)
        self.m.poke(r.a("wOTPartyMonNicknames"), st.nick)
        self.m.poke(r.a("wOTPlayerName"), st.sender)

    def arm(self, slot: int, token=TOKEN, command: int = APPLY, delta: int = 1, ack: int | None = None,
            version: int = 1, magic=MAGIC) -> int:
        previous = self.rd(6)
        gen = (previous + delta) & 0xFF
        frame = [*magic, version, command, previous, previous if ack is None else ack, 0xFF, slot, 1, 0, *token]
        for o, v in enumerate(frame):
            self.wr(o, v)
        self.wr(6, gen)                         # the generation LAST publishes the request
        frame[6] = gen
        self.expected = frame
        return gen

    # DONE: completion
    def done_pending(self) -> bool:
        e = self.expected
        if e is None or not self.header(DONE):
            return False
        return (self.rd(6) == e[6] and self.rd(7) == e[6] and self.rd(9) == e[9]
                and tuple(self.rd(12 + i) for i in range(4)) == tuple(e[12:16]) and self.rd(8) <= 3)

    def release(self) -> None:
        self.done_result = self.rd(8)
        self.wr(5, CMD_RELEASE)

    def press_b(self) -> None:
        self.rig.b_next = True

    def hvblank(self, v: int) -> None:
        self.m.poke(self.rig.a("hVBlank"), v)


# scripted host behaviours -------------------------------------------------------------

def host_happy(mask=0b0110, token=TOKEN, stage: Stage | None = None, apply_slot: int | None = None, tamper=None,
               release: bool = True, apply_kwargs: dict | None = None, offer_ok: bool = True, pre_apply=None):
    """QUERY -> mask, OFFER -> accept, APPLY (incoming staged), DONE -> RELEASE."""

    def script(h: Host):
        yield from h.until(h.query_pending)
        h.answer_query(mask, token)
        yield from h.until(h.offer_pending)
        h.rig.mark("offer_seen")
        h.answer_offer(offer_ok)
        if not offer_ok:
            return
        yield from h.frames(2)
        if tamper is not None:
            tamper(h)
        h.stage(stage)
        if pre_apply is not None:
            pre_apply(h)
        h.arm(h.rig.own if apply_slot is None else apply_slot, token, **(apply_kwargs or {}))
        h.rig.mark("apply_armed")
        if not release:
            return
        yield from h.until(h.done_pending)
        h.rig.mark("done_seen")
        yield from h.frames(1)
        h.release()
    return script


# ------------------------------------------------------------------ the rig

@dataclass
class Run:
    res: S.Result | None
    fault: Exception | None
    lease_writes: list[tuple[int, int]]
    writes: list[tuple[int, int, int]]
    events: str
    info: list[dict]
    calls: list[tuple]
    frames: int
    marks: dict
    host: Host
    m: S.SM83
    pcs: set
    depths: dict
    before: bytes


class Rig:
    def __init__(self, env: Env, *, party: int = 4, own: int = 2, gen0: int = 0x10, saved: int = 1, contest: int = 0,
                 hvblank: int = 0, rom: bytes | None = None):
        self.env, self.party, self.own, self.gen0 = env, party, own, gen0
        self.saved, self.contest, self.hvblank = saved, contest, hvblank
        self.rom = env.rom if rom is None else rom
        self.b_next = False
        self.frame = 0
        self.marks: dict[str, int] = {}
        self.calls: list[tuple] = []
        self.lease = env.lease

    def a(self, name: str) -> int:
        return self.env.a(name)

    def mark(self, what: str) -> None:
        self.marks[what] = self.frame

    def own_ranges(self, slot: int | None = None) -> list[tuple[int, int]]:
        s = self.own if slot is None else slot
        return [(self.a("wPartyMon1") + s * P, P), (self.a("wPartyMonOTs") + s * OTL, OTL),
                (self.a("wPartyMonNicknames") + s * NICKL, NICKL)]

    def build_ram(self, m: S.SM83) -> None:
        a = self.a
        m.poke(a("wSavedAtLeastOnce"), self.saved)
        m.poke(a("wStatusFlags2"), 1 << 2 if self.contest else 0)     # STATUSFLAGS2_BUG_CONTEST_TIMER_F == 2
        m.poke(a("wPartyCount"), self.party)
        for i in range(6):
            m.poke(a("wPartyMon1") + i * P, own_record(i))
            m.poke(a("wPartyMonOTs") + i * OTL, name(40 + i))
            m.poke(a("wPartyMonNicknames") + i * NICKL, name(50 + i))
        m.poke(a("hVBlank"), self.hvblank)
        # the real DelayFrame bridge runs `rst Bankswitch` before SlinkService, so the hROMBank shadow holds the service bank
        # (the FarCall model restores the caller bank from the shadow, as home/farcall.asm does)
        m.poke(HROMBANK, BANK7E)
        stale = [0] * LEASE_SIZE
        stale[6] = stale[7] = self.gen0
        stale[8], stale[9] = 0x99, 0x77                                   # stale result/slot: never trusted
        stale[12:16] = (9, 9, 9, 9)
        m.poke(self.lease, bytes(stale))

    def run(self, host: Callable | None = None, *, menu=("pick", None), yesno: bool = True, pcs: bool = False,
            rom: bytes | None = None, tolerate_fault: bool = False) -> Run:
        env = self.env
        rom = self.rom if rom is None else rom
        m = S.SM83(rom, BANK7E, mbc="mbc3", farcall="model", hrombank=HROMBANK)
        m.farcall_allowed = {SELECT_TRADE_MON}
        self.b_next, self.frame, self.marks, self.calls = False, 0, {}, []
        self.build_ram(m)
        h = Host(self, m)
        gen = host(h) if host is not None else None
        state = {"gen": gen}
        entry_sp = S.DEFAULT_SP
        depths: dict[str, int] = {}
        text_names = {env.a("SlinkTradeConfirmText"): "confirm", env.a("SlinkTradeWaitText"): "wait"}

        def on_frame(mm: S.SM83) -> None:
            self.frame += 1
            depths["wait"] = max(depths.get("wait", 0), entry_sp - mm.sp)
            g = state["gen"]
            if g is not None:
                try:
                    next(g)
                except StopIteration:
                    state["gen"] = None

        def on_joy(mm: S.SM83) -> None:
            mm.poke(0xFF00 + 0x97, PAD_B if self.b_next else 0)         # hJoyPressed (clean sym 00:ff97)
            self.b_next = False

        def on_print(mm: S.SM83) -> None:
            self.calls.append(("print", text_names.get(mm.hl, f"{mm.hl:#06x}"), self.frame))

        def on_yesno(mm: S.SM83) -> None:
            self.calls.append(("yesno", self.frame))
            mm.cf = not yesno

        def on_menu(mm: S.SM83) -> None:
            depths["menu"] = entry_sp - mm.sp
            self.calls.append(("menu", mm.b, self.frame))
            assert mm.b == PARTYMENUACTION_GIVE_MON, f"the party menu was opened with B={mm.b}, not GIVE_MON"
            kind, slot = menu
            if kind == "cancel":
                mm.cf = True
            else:
                mm.poke(self.a("wCurPartyMon"), self.own if slot is None else slot)
                mm.cf = False

        m.trap(0x0DA8, on_frame)                                          # DelayFrame (00:0da8)
        m.trap(0x07C3, on_joy)                                            # JoyTextDelay (00:07c3)
        m.trap(0x0E58, on_print)                                          # PrintText (00:0e58)
        m.trap(0x18E0, on_yesno)                                          # YesNoBox (00:18e0)
        m.trap(SELECT_TRADE_MON[1], on_menu, bank=SELECT_TRADE_MON[0])
        executed: set = set()
        if pcs:
            orig = m.step

            def step() -> None:
                executed.add((m.bank if m.pc >= 0x4000 else 0, m.pc))
                orig()
            m.step = step
        before = bytes(m.mem.ram)
        res = fault = None
        try:
            res = m.call_routine(env.a("SlinkTradeEntry"), bank=BANK7E, max_steps=STEP_LIMIT)
        except S.Fault as exc:
            if not tolerate_fault:
                raise
            fault = exc
        lw = [(addr - self.lease, v) for _pc, addr, v in m.mem.writes if self.lease <= addr < self.lease + LEASE_SIZE]
        events, info = segment(lw) if fault is None else ("?", [])
        if res is not None:
            depths["overall"] = res.stack_used
        return Run(res, fault, lw, list(m.mem.writes), events, info, list(self.calls), self.frame, dict(self.marks), h, m,
                   executed, depths, before)


def allowed_write(rig: Rig, run: Run) -> list[tuple[int, int, int]]:
    """CPU writes outside the lease, OT slot 1 (the snapshot), hROMBank and the stack. Empty = clean."""
    a = rig.a
    ok = [(rig.lease, LEASE_SIZE), (a("wOTPartyMon2"), P), (a("wOTPartyMonOTs") + OTL, OTL),
          (a("wOTPartyMonNicknames") + NICKL, NICKL), (HROMBANK, 1), (run.m.min_sp, S.DEFAULT_SP - run.m.min_sp)]
    return [w for w in run.writes if not any(lo <= w[1] < lo + n for lo, n in ok)]


def common(rig: Rig, run: Run, events: str, *, forbid_calls=(), frames: int | None = None) -> None:
    assert run.fault is None, f"the service faulted: {run.fault}"
    assert run.res.sp_delta == 0, f"unbalanced stack: sp_delta {run.res.sp_delta}"
    assert run.events == events, f"lease publications {run.events!r}, want {events!r}: {run.lease_writes}"
    bad = allowed_write(rig, run)
    assert not bad, f"CPU writes outside the allowed set: {[(hex(p), hex(a), v) for p, a, v in bad]}"
    assert not any(o == 8 and v == 0 for o, v in run.lease_writes), "a result 0 was published"
    assert run.m.farcalls == [] or {(f.bank, f.addr) for f in run.m.farcalls} == {SELECT_TRADE_MON}
    if events.endswith("C"):
        assert run.lease_writes[-3:] == [(5, 0), (10, 0), (11, 0)]
    else:
        raise AssertionError("the lease was not closed on the way out")
    for c in forbid_calls:
        assert not any(x[0] == c for x in run.calls), f"unexpected {c} call: {run.calls}"
    if frames is not None:
        assert run.frames == frames, f"{run.frames} frames, want {frames}"
    # the party, the save flag and OT slot 0 (the host's staging) are never touched by the CPU
    a = rig.a
    forbidden = [(a("wPartyCount"), 1), (a("wPartyMon1"), 6 * P), (a("wPartyMonOTs"), 6 * OTL),
                 (a("wPartyMonNicknames"), 6 * NICKL), (a("wSavedAtLeastOnce"), 1), (a("wOTPartyMon1"), P),
                 (a("wOTPartyMonOTs"), OTL), (a("wOTPartyMonNicknames"), NICKL), (0xA000, 0x2000)]
    hits = [w for w in run.writes if any(lo <= w[1] < lo + n for lo, n in forbidden)]
    assert not hits, f"a party/save/staging byte was written: {hits}"


def snapshot_matches(rig: Rig, run: Run) -> bool:
    m, a = run.m, rig.a
    return (m.peek(a("wOTPartyMon2"), P) == own_record(rig.own)
            and m.peek(a("wOTPartyMonOTs") + OTL, OTL) == name(40 + rig.own)
            and m.peek(a("wOTPartyMonNicknames") + NICKL, NICKL) == name(50 + rig.own))


# ------------------------------------------------------------------ scenarios (each is a named, callable check)

def happy_lease(g: int, own: int, token=TOKEN) -> list[tuple[int, int]]:
    """The exact CPU lease write sequence of a full successful proposer visit, derived from first principles."""
    m = lambda x: x & 0xFF  # noqa: E731
    return [(0, 0x53), (1, 0x4C), (2, 0x54), (3, 0x31), (4, 1), (5, 1), (10, 0), (11, 0), (7, g), (6, m(g + 1)),
            (9, own), (8, 0xFF), (5, 2), (7, m(g + 1)), (6, m(g + 2)),
            (7, m(g + 3)),
            (8, 1), (0, 0x53), (1, 0x4C), (2, 0x54), (3, 0x31), (4, 1), (12, token[0]), (13, token[1]), (14, token[2]),
            (15, token[3]), (9, own), (5, 7), (6, m(g + 3)), (7, m(g + 3)),
            (5, 0), (10, 0), (11, 0)]


def sc_happy(env: Env, rom: bytes | None = None, gen0: int = 0x10, party: int = 4, own: int = 2, mask: int = 0b0110):
    rig = Rig(env, party=party, own=own, gen0=gen0, rom=rom)
    run = rig.run(host_happy(mask=mask), pcs=True)
    common(rig, run, "QOADC")
    assert run.lease_writes == happy_lease(gen0, own), run.lease_writes
    done = run.info[3]
    assert done["o8"] == 1, "DONE must publish result 1 (not performed: commit disabled)"
    assert run.host.done_result == 1
    assert snapshot_matches(rig, run), "OT slot 1 does not hold the selected mon's 70 bytes"
    assert [c[0] for c in run.calls] == ["menu", "print", "yesno", "print"]
    assert [c[1] for c in run.calls if c[0] == "print"] == ["confirm", "wait"]
    # the host's own completion test (lua `completion`) accepted the frame, then RELEASE closed it
    assert run.host.done_result is not None
    return rig, run


def sc_no_eligible_mon(env, rom=None):
    for ans in ({"mask": 0}, {"mask": 0, "available": 1}, {"mask": 0b0110, "available": 0}):
        rig = Rig(env, rom=rom)

        def host(h, ans=ans):
            yield from h.until(h.query_pending)
            h.answer_query(ans["mask"], TOKEN, ans.get("available"))
            yield from h.frames(3)
        run = rig.run(host)
        common(rig, run, "QC", forbid_calls=("menu", "print", "yesno"))
        assert run.frames == 1


def sc_mask_bits_above_count(env, rom=None):
    for party, mask in ((4, 0x10), (4, 0x20), (4, 0x40), (4, 0x80), (4, 0b010110), (2, 0b100), (1, 0b10), (6, 0x40),
                        (6, 0x80), (5, 0x20)):
        rig = Rig(env, party=party, own=0, rom=rom)
        run = rig.run(host_happy(mask=mask), menu=("pick", 0))
        common(rig, run, "QC", forbid_calls=("menu", "print", "yesno"))
    # a full valid mask for the party is accepted all the way
    rig = Rig(env, party=6, own=5, rom=rom)
    run = rig.run(host_happy(mask=0x3F))
    common(rig, run, "QOADC")


def sc_menu_cancel(env, rom=None):
    rig = Rig(env, rom=rom)
    run = rig.run(host_happy(), menu=("cancel", None))
    common(rig, run, "QC", forbid_calls=("print", "yesno"))
    assert [c[0] for c in run.calls] == ["menu"]


def sc_menu_pick_not_offered(env, rom=None):
    # the host offered slots 1 and 2; the player picks slot 0 or a slot beyond the party
    for pick in (0, 3, 5, 7):
        rig = Rig(env, rom=rom)
        run = rig.run(host_happy(), menu=("pick", pick))
        common(rig, run, "QC", forbid_calls=("print", "yesno"))


def sc_confirm_no(env, rom=None):
    rig = Rig(env, rom=rom)
    run = rig.run(host_happy(), yesno=False)
    common(rig, run, "QC")
    assert [c[0] for c in run.calls] == ["menu", "print", "yesno"]
    assert [c[1] for c in run.calls if c[0] == "print"] == ["confirm"]


def sc_offer_rejected(env, rom=None):
    rig = Rig(env, rom=rom)
    run = rig.run(host_happy(offer_ok=False))
    common(rig, run, "QOC", frames=2)                   # a rejection closes at once: it does not wait for an APPLY

    # the host ACKs without ever writing the result: it stays $FF and is refused
    def lazy(h):
        yield from h.until(h.query_pending)
        h.answer_query(0b0110)
        yield from h.until(h.offer_pending)
        h.wr(7, h.rd(6))
        yield from h.frames(2)
    rig = Rig(env, rom=rom)
    run = rig.run(lazy)
    common(rig, run, "QOC", frames=2)
    # any nonzero result is a rejection
    for result in (2, 3, 0x7F, 0xFE):
        def reject(h, result=result):
            yield from h.until(h.query_pending)
            h.answer_query(0b0110)
            yield from h.until(h.offer_pending)
            h.wr(8, result)
            h.wr(7, h.rd(6))
            yield from h.frames(2)
        rig = Rig(env, rom=rom)
        run = rig.run(reject)
        common(rig, run, "QOC", frames=2)


def sc_query_timeout(env, rom=None):
    rig = Rig(env, rom=rom)
    run = rig.run(None)
    common(rig, run, "QC", forbid_calls=("menu", "print", "yesno"), frames=600)
    # a host that answers in the 600th frame is in time; one frame later is a timeout
    for at, ok in ((598, True), (599, True), (600, True), (601, False), (700, False)):
        def late(h, at=at):
            yield from h.frames(at - 1)
            h.answer_query(0b0110)
        rig = Rig(env, rom=rom)
        run = rig.run(late, tolerate_fault=False)
        assert run.events.startswith("QO") is ok, (at, run.events)


def sc_offer_timeout(env, rom=None):
    rig = Rig(env, rom=rom)

    def host(h):
        yield from h.until(h.query_pending)
        h.answer_query(0b0110)
        yield from h.frames(10 ** 9)
    run = rig.run(host)
    common(rig, run, "QOC", frames=1 + 600)


def sc_apply_timeout_and_b(env, rom=None):
    rig = Rig(env, rom=rom)

    def host(h):
        yield from h.until(h.query_pending)
        h.answer_query(0b0110)
        yield from h.until(h.offer_pending)
        h.answer_offer(True)
        yield from h.frames(10 ** 9)
    run = rig.run(host)
    common(rig, run, "QOC", frames=1 + 1 + 3600)
    # B at every wait: QUERY, OFFER, APPLY (DONE was published only after APPLY: B in the RELEASE wait)
    for where, events in (("query", "QC"), ("offer", "QOC"), ("apply", "QOC")):
        def bhost(h, where=where):
            if where == "query":
                yield from h.frames(5)
                h.press_b()
                yield from h.frames(10)
                return
            yield from h.until(h.query_pending)
            h.answer_query(0b0110)
            yield from h.until(h.offer_pending)
            if where == "offer":
                h.press_b()
                yield from h.frames(10)
                return
            h.answer_offer(True)
            yield from h.frames(7)
            h.press_b()
            yield from h.frames(10)
        rig = Rig(env, rom=rom)
        run = rig.run(bhost)
        common(rig, run, events)
        assert run.frames < 20, (where, run.frames)


def host_apply_at(k: int | None):
    """QUERY -> mask, OFFER -> accept, then publish a valid APPLY on APPLY-wait frame K (1-based; None = never)."""

    def script(h: Host):
        yield from h.until(h.query_pending)
        h.answer_query(0b0110)
        yield from h.until(h.offer_pending)
        h.answer_offer(True)
        if k is None:
            yield from h.frames(10 ** 9)
        start = h.rig.frame                      # the OFFER wait's frame 1; APPLY wait frame j is global frame start + j
        yield from h.until(lambda: h.rig.frame >= start + k, limit=k + 10)
        h.stage()
        h.arm(h.rig.own)
        h.rig.mark("apply_armed")
        yield from h.until(h.done_pending)
        yield from h.frames(1)
        h.release()
    return script


def sc_apply_window(env, rom=None):
    """The documented 3600-frame APPLY wait inspects EVERY one of its frames: the frame in which the counter reaches
    zero is still examined (a request published there is accepted), the next frame never exists (refused, no pickup)."""
    for k in (1, 2, 3599, 3600):
        rig = Rig(env, rom=rom)
        run = rig.run(host_apply_at(k))
        common(rig, run, "QOADC")
        assert run.host.done_result == 1, k
        assert run.info[2]["kind"] == "A", k                       # the pickup ACK
    # a request on frame 3601 would be one frame past the wait: the service has already closed (QOC, no pickup, no DONE)
    rig = Rig(env, rom=rom)
    run = rig.run(host_apply_at(3601))
    common(rig, run, "QOC", frames=1 + 1 + 3600)
    assert "apply_armed" not in run.marks
    # nothing ever arrives: the wait ends after exactly 3600 APPLY frames
    rig = Rig(env, rom=rom)
    run = rig.run(host_apply_at(None))
    common(rig, run, "QOC", frames=1 + 1 + 3600)


def sc_release_wait(env, rom=None):
    # a host that never RELEASEs: the 90-frame bounded wait closes after DONE
    rig = Rig(env, rom=rom)
    run = rig.run(host_happy(release=False))
    common(rig, run, "QOADC")
    assert run.frames - run.marks["apply_armed"] == 90, run.frames - run.marks["apply_armed"]
    # B cancels the RELEASE wait
    def host(h):
        yield from host_happy(release=False)(h)
        yield from h.until(h.done_pending)
        yield from h.frames(3)
        h.press_b()
        yield from h.frames(10)
    rig = Rig(env, rom=rom)
    run = rig.run(host)
    common(rig, run, "QOADC")
    assert run.frames < 20 + 5
    # RELEASE with a wrong token / generation / ACK / command is ignored: the wait runs out
    for label, mutate in (("token", lambda h: h.wr(13, h.rd(13) ^ 1)), ("gen", lambda h: h.wr(6, h.rd(6) ^ 1)),
                          ("ack", lambda h: h.wr(7, h.rd(7) ^ 1))):
        def host(h, mutate=mutate):
            yield from host_happy(release=False)(h)
            yield from h.until(h.done_pending)
            h.release()
            mutate(h)
            yield from h.frames(10 ** 9)
        rig = Rig(env, rom=rom)
        run = rig.run(host)
        common(rig, run, "QOADC")
        assert run.frames - run.marks["apply_armed"] == 90, label


def sc_token_drift(env, rom=None):
    # (a) the APPLY carries another token / a zero token / one flipped byte: no pickup, no DONE
    for tok in ((0x55, 0x66, 0x77, 0x88), (0, 0, 0, 0), (0x11, 0x22, 0x33, 0x45), (0x10, 0x22, 0x33, 0x44),
                (0x11, 0x22, 0x33, 0)):
        rig = Rig(env, rom=rom)

        def host(h, tok=tok):
            yield from h.until(h.query_pending)
            h.answer_query(0b0110)
            yield from h.until(h.offer_pending)
            h.answer_offer(True)
            yield from h.frames(2)
            h.stage()
            h.arm(h.rig.own, tok)
            yield from h.frames(10)
        run = rig.run(host)
        common(rig, run, "QOC")
    # (b) the host swaps the token between the QUERY answer and the OFFER acknowledgement
    rig = Rig(env, rom=rom)

    def swap(h):
        yield from h.until(h.query_pending)
        h.answer_query(0b0110)
        yield from h.until(h.offer_pending)
        h.wr(12, h.rd(12) ^ 0x80)
        h.answer_offer(True)
        yield from h.frames(10)
    run = rig.run(swap)
    common(rig, run, "QOC")
    # (c) the token is never nonzero
    rig = Rig(env, rom=rom)

    def zero(h):
        yield from h.until(h.query_pending)
        h.answer_query(0b0110, (0, 0, 0, 0), available=1)
        yield from h.frames(10)
    run = rig.run(zero)
    common(rig, run, "QC", forbid_calls=("menu",))


def sc_wrong_slot(env, rom=None):
    for slot in (0, 1, 3, 5, 6, 0xFF):
        rig = Rig(env, rom=rom)
        run = rig.run(host_happy(apply_slot=slot))
        common(rig, run, "QOC")


def sc_generation(env, rom=None):
    # FF -> 00 wraps are fine at every step of the visit; previous+2, previous+0 and previous-1 are refused
    for g in (0xFC, 0xFD, 0xFE, 0xFF, 0x00, 0x7F):
        rig, run = sc_happy(env, rom, gen0=g)
    for delta in (2, 3, 0xFF, 0x80):
        rig = Rig(env, gen0=0x20, rom=rom)
        run = rig.run(host_happy(apply_kwargs={"delta": delta}))
        common(rig, run, "QOC")
    # a stale APPLY (gen == ack: nothing new) is ignored, not accepted
    rig = Rig(env, gen0=0x20, rom=rom)
    run = rig.run(host_happy(apply_kwargs={"delta": 0}))
    common(rig, run, "QOC", frames=1 + 1 + 3600)
    # an ACK that is not the previous generation is refused
    for ack in (0x00, 0xAA):
        rig = Rig(env, gen0=0x20, rom=rom)
        run = rig.run(host_happy(apply_kwargs={"ack": ack}))
        common(rig, run, "QOC")
    # a bad header / version / command on the frame
    for kw in ({"magic": (0x53, 0x4C, 0x54, 0x30)}, {"version": 2}, {"command": 3}, {"command": 8}):
        rig = Rig(env, gen0=0x20, rom=rom)
        run = rig.run(host_happy(apply_kwargs=kw))
        common(rig, run, "QOC")


def sc_apply_before_accept(env, rom=None):
    # the host publishes APPLY (gen previous+1) while the ROM is still waiting for the OFFER acknowledgement
    rig = Rig(env, rom=rom)

    def early(h):
        yield from h.until(h.query_pending)
        h.answer_query(0b0110)
        yield from h.until(h.offer_pending)
        h.stage()
        h.arm(h.rig.own)
        yield from h.frames(10)
    run = rig.run(early)
    common(rig, run, "QOC")
    # an OFFER ack carrying the wrong generation is not an acknowledgement
    rig = Rig(env, rom=rom)

    def wrong_ack(h):
        yield from h.until(h.query_pending)
        h.answer_query(0b0110)
        yield from h.until(h.offer_pending)
        h.wr(8, 0)
        h.wr(7, (h.rd(6) + 5) & 0xFF)
        yield from h.frames(10)
    run = rig.run(wrong_ack)
    common(rig, run, "QOC")


def _bad_stages() -> list[tuple[str, Stage]]:
    rec = incoming_record()

    def with_rec(**fields) -> Stage:
        r = bytearray(rec)
        for off, v in fields.items():
            r[int(off[1:])] = v
        return Stage(rec=bytes(r))
    no_term = bytes([0x80 + i for i in range(11)])
    return [
        ("nickname without a terminator", Stage(nick=no_term)),
        ("OT name without a terminator in 8", Stage(ot=bytes([0x80] * 8 + [0x53, 0, 0]))),
        ("sender without a terminator", Stage(sender=no_term)),
        ("nickname with a control byte", Stage(nick=bytes([0x80, 0x10, 0x53]) + bytes(8))),
        ("species 0", with_rec(p0=0)),
        ("species $FF", with_rec(p0=0xFF)),
        ("species $100 (ext bit, low 0)", with_rec(p0=0, p21=0x20)),
        ("species $124", with_rec(p0=0x24, p21=0x20)),
        ("held mail $F5", with_rec(p1=0xF5)),
        ("held mail $FE", with_rec(p1=0xFE)),
        ("level 0", with_rec(p31=0)),
        ("level 101", with_rec(p31=101)),
        ("nature 25", with_rec(p20=25)),
    ]


def sc_invalid_incoming(env, rom=None):
    for label, st in _bad_stages():
        rig = Rig(env, rom=rom)
        run = rig.run(host_happy(stage=st))
        assert run.fault is None, label
        common(rig, run, "QOAC")
        assert not any(o == 5 and v == DONE for o, v in run.lease_writes), label


def sc_good_incoming_boundaries(env, rom=None):
    # the legal edges are accepted: species $01 / $FE / $101 / $123, level 1 / 100, empty-ish names
    rec = bytearray(incoming_record())
    for p0, p21, lvl in ((1, 0, 1), (0xFE, 0, 100), (1, 0x20, 50), (0x23, 0x20, 50), (25, 0x40, 5)):
        rec[0], rec[21], rec[31] = p0, p21, lvl
        rig = Rig(env, rom=rom)
        run = rig.run(host_happy(stage=Stage(rec=bytes(rec), nick=bytes([0x53]) + bytes(10))))
        common(rig, run, "QOADC")


def sc_own_record_flip(env, rom=None):
    """Every one of the 70 snapshotted bytes of the selected mon, flipped between the snapshot and APPLY."""
    rig0 = Rig(env, rom=rom)
    spans = rig0.own_ranges()
    targets = [lo + i for lo, n in spans for i in range(n)]
    assert len(targets) == 70
    for addr in targets:
        rig = Rig(env, rom=rom)

        def tamper(h, addr=addr):
            h.m.poke(addr, h.m.peek(addr)[0] ^ 0x01)
        run = rig.run(host_happy(tamper=tamper))
        common_flip(rig, run, addr)


def common_flip(rig: Rig, run: Run, addr: int) -> None:
    assert run.fault is None
    assert run.res.sp_delta == 0
    assert run.events == "QOAC", (hex(addr), run.events)
    assert not any(o == 5 and v == DONE for o, v in run.lease_writes), hex(addr)
    assert not allowed_write(rig, run)


def sc_party_changes(env, rom=None):
    # a different party count under the held transaction
    for newcount in (3, 5, 6, 1):
        rig = Rig(env, party=4, rom=rom)
        addr = rig.a("wPartyCount")
        run = rig.run(host_happy(tamper=lambda h, n=newcount, addr=addr: h.m.poke(addr, n)))
        assert run.fault is None and run.res.sp_delta == 0
        assert run.events in ("QOAC",), (newcount, run.events)
    # the selected slot is no longer in the party (count 2, slot 2)
    rig = Rig(env, party=4, rom=rom)
    run = rig.run(host_happy(tamper=lambda h: h.m.poke(rig.a("wPartyCount"), 2)))
    assert run.events == "QOAC"
    # the party mutates into an invalid own record: held mail on the selected mon after the snapshot
    rig = Rig(env, party=4, rom=rom)
    run = rig.run(host_happy(tamper=lambda h: h.m.poke(rig.a("wPartyMon1") + rig.own * P + 1, 0xF5)))
    assert run.events == "QOAC"


def sc_entry_guards(env, rom=None):
    # no full save yet / Bug-Catching Contest / party count 0 or 7+: nothing is published, the lease is only closed
    for kw in ({"saved": 0}, {"contest": 1}, {"party": 0}, {"party": 7}, {"party": 255}):
        rig = Rig(env, rom=rom, **kw)
        run = rig.run(None)
        common(rig, run, "C", forbid_calls=("menu", "print", "yesno"), frames=0)


def sc_own_mon_refused(env, rom=None):
    # the picked mon passes the menu but fails a Polished predicate: mail, species 0, level 0, an extension species
    # (mail, mail $FE, species 0, level 0, level 101, nature 25, an extension species $124)
    for off, val in ((1, 0xF5), (1, 0xFE), (0, 0), (31, 0), (31, 101), (20, 25), (21, 0x20)):
        rig = Rig(env, rom=rom)
        base = rig.a("wPartyMon1") + rig.own * P

        def host(h, off=off, val=val, base=base):
            yield from h.until(h.query_pending)
            h.m.poke(base + off, val)
            if off == 21:
                h.m.poke(base, 0x24)
            h.answer_query(0b0110)
            yield from h.frames(3)
        run = rig.run(host)
        common(rig, run, "QC", forbid_calls=("print", "yesno"))


def sc_hvblank(env, rom=None):
    # hVBlank != 0 refuses before the wait: no DelayFrame runs in that phase
    for v in (1, 2, 8, 0x80):
        rig = Rig(env, hvblank=v, rom=rom)
        run = rig.run(None)
        common(rig, run, "QC", frames=0)
    for phase in ("offer", "apply", "release"):
        def host(h, phase=phase):
            yield from h.until(h.query_pending)
            h.answer_query(0b0110)
            if phase == "offer":
                yield from h.until(h.offer_pending)
                h.hvblank(3)
                yield from h.frames(10 ** 9)
            yield from h.until(h.offer_pending)
            h.answer_offer(True)
            if phase == "apply":
                h.hvblank(3)
                yield from h.frames(10 ** 9)
            yield from h.frames(2)
            h.stage()
            h.arm(h.rig.own)
            yield from h.until(h.done_pending)
            h.hvblank(3)
            yield from h.frames(10 ** 9)
        rig = Rig(env, rom=rom)
        run = rig.run(host)
        events = {"offer": "QOC", "apply": "QOC", "release": "QOADC"}[phase]
        common(rig, run, events)
        assert run.frames < 8, (phase, run.frames)


def sc_no_commit(env, rom=None):
    rig, run = sc_happy(env, rom)
    sym = env.sym
    assert not [n for n in sym if "Commit" in n and n.startswith("SlinkTrade")], "a commit symbol exists in the overlay"
    deny = {env.clean[n] for n in COMMIT_NATIVES if n in env.clean}
    assert deny, "no commit natives resolved from the clean sym"
    hit = sorted(f"{n}" for n in COMMIT_NATIVES if n in env.clean and env.clean[n] in run.pcs)
    assert not hit, f"executed a commit routine: {hit}"
    # static: no direct call/jp operand and no farcall record to a denied target inside the service
    lo, hi = env.flat("SlinkTradeProposerService"), env.flat("SlinkTradeProposerServiceEnd")
    code = env.rom[lo:hi]
    for n in COMMIT_NATIVES:
        if n not in env.clean:
            continue
        bank, addr = env.clean[n]
        word = addr.to_bytes(2, "little")
        for i in range(len(code) - 2):
            jumps = code[i] in (0xCD, 0xC3, 0xC2, 0xCA, 0xD2, 0xDA, 0xC4, 0xCC, 0xD4, 0xDC)
            assert not (jumps and code[i + 1:i + 3] == word and bank in (0, BANK7E)), f"{n} is called/jumped to at +{i:#x}"
        rec = word + bytes([bank])
        assert rec not in code and bytes([word[0], word[1] | 0x80, bank]) not in code, f"{n} is far-called"
    # DONE is never result 0 on any scenario that reaches it
    assert all(o != 8 or v != 0 for o, v in run.lease_writes)


SCENARIOS: dict[str, Callable] = {
    "happy": sc_happy, "no_eligible_mon": sc_no_eligible_mon, "mask_bits_above_count": sc_mask_bits_above_count,
    "menu_cancel": sc_menu_cancel, "menu_pick_not_offered": sc_menu_pick_not_offered, "confirm_no": sc_confirm_no,
    "offer_rejected": sc_offer_rejected, "query_timeout": sc_query_timeout, "offer_timeout": sc_offer_timeout,
    "apply_timeout_and_b": sc_apply_timeout_and_b, "apply_window": sc_apply_window, "release_wait": sc_release_wait, "token_drift": sc_token_drift,
    "wrong_slot": sc_wrong_slot, "generation": sc_generation, "apply_before_accept": sc_apply_before_accept,
    "invalid_incoming": sc_invalid_incoming, "good_incoming": sc_good_incoming_boundaries,
    "own_record_flip": sc_own_record_flip, "party_changes": sc_party_changes, "entry_guards": sc_entry_guards,
    "own_mon_refused": sc_own_mon_refused, "hvblank": sc_hvblank, "no_commit": sc_no_commit,
}


@pytest.mark.parametrize("scenario", list(SCENARIOS))
def test_scenario(scenario, env):
    SCENARIOS[scenario](env)


# ------------------------------------------------------------------ the layout / source contract

def test_the_service_symbols_and_the_section_limits(env):
    s = env.sym
    assert s["SlinkTradeProposerService"] == (BANK7E, 0x4A00)
    lo, hi = s["SlinkTradeProposerService"][1], s["SlinkTradeProposerServiceEnd"][1]
    assert hi - lo > 300 and hi <= 0x5000, f"the service ends at {hi:#06x}"
    assert s["SlinkTradeEntry"] == (BANK7E, 0x4480) and s["SlinkTradeGatesEnd"] == (BANK7E, 0x4484)
    assert env.clean["SelectTradeOrDayCareMon"] == SELECT_TRADE_MON
    assert (s["DelayFrame"], s["JoyTextDelay"], s["PrintText"], s["YesNoBox"]) == (
        (0, 0x0DA8), (0, 0x07C3), (0, 0x0E58), (0, 0x18E0)) == tuple(env.clean[n] for n in (
            "DelayFrame", "JoyTextDelay", "PrintText", "YesNoBox"))
    assert env.clean["hJoyPressed"] == (0, 0xFF97) and env.clean["hROMBank"] == (0, HROMBANK)
    # every exported service symbol lies in [start, end) and the section is the only thing at $4A00
    for n in ("SlinkTradeWaitApply", "SlinkTradeWaitRelease", "SlinkTradeExit", "SlinkTradeConfirmText",
              "SlinkTradeWaitText"):
        assert lo < s[n][1] < hi and s[n][0] == BANK7E


def test_the_entry_is_a_four_byte_trampoline_and_the_gate_still_calls_it(env):
    at = env.flat("SlinkTradeEntry")
    assert env.rom[at:at + 4] == b"\xc3" + env.a("SlinkTradeProposerService").to_bytes(2, "little") + b"\x00"
    gate = env.flat("SlinkTradeTimeoutGate")
    assert b"\xcd" + env.a("SlinkTradeEntry").to_bytes(2, "little") in env.rom[gate:gate + 0x20]


def test_the_overlay_invariants_hold(env):
    rom = env.rom
    assert rom[0x70:0x77].hex() == "f044e0d7afe08f"
    assert rom[0xDA8:0xDAF].hex() == "cd700000000000"
    assert rom[0x1F8000:0x1F8010].hex() == "210bc63e53223e4c223e4e223e4b223e"
    assert rom[0xC030:0xC036].hex() == "7e00447e1044"


def test_source_shape():
    src = SRC.read_text(encoding="utf-8")
    code = "\n".join(line.split(";", 1)[0] for line in src.splitlines())
    assert "SECTION \"SLink Trade Service\", ROMX[$4a00], BANK[SLINK_SERVICE_BANK]" in src
    assert 'ASSERT @ <= $5000' in src and "SlinkTradeProposerServiceEnd::" in src
    # the proposer-only service never names the vanilla responder branch, the commit or the species list
    for forbidden in ("SlinkTradeCommit", "SlinkTradePromptEntry", "wPartySpecies", "wOTPartySpecies", "VBLANK_NORMAL",
                      "GetSGBLayout", "Link_SaveGame", "OpenText", "CloseText", "GetNickname"):
        assert forbidden not in code, forbidden
    assert not re.search(r"\$50(?![0-9a-fA-F])", code), "a numeric $50 terminator (the Polished terminator is $53)"
    assert "SlinkTradeSnapshot" in src and "SlinkTradeValidateIncomingStaged" in src and "SlinkTradeValidateSnapshot" in src
    assert "farcall SelectTradeOrDayCareMon" in src and "PARTYMENUACTION_GIVE_MON" in src
    assert "call YesNoBox" in src and "call PrintText" in src and "ldh a, [hVBlank]" in src
    gate = (REPO / "patch/polished/src/trade_gate.asm").read_text(encoding="utf-8")
    assert "jp SlinkTradeProposerService\n\tnop\nSlinkTradeGatesEnd::" in gate
    slink = (REPO / "patch/polished/src/slink.asm").read_text(encoding="utf-8")
    # the proposer service precedes the C6 responder service, which is the last include
    assert slink.index("trade_validate.asm") < slink.index("trade_service.asm") < slink.index("trade_responder.asm")
    assert slink.rstrip().endswith('INCLUDE "engine/slink/trade_responder.asm"')


def test_report_the_stack_budgets(env, capsys):
    rig, run = sc_happy(env)
    d = run.depths
    # the DelayFrame trap is entered by a `call` from the wait loop: the real DelayFrame/bridge cost more (UNVERIFIED)
    print(f"[budget] overall stack_used={run.res.stack_used} min_sp={run.res.min_sp:#06x} entry_sp={S.DEFAULT_SP:#06x} "
          f"wait-depth={d['wait']} menu-depth={d['menu']} steps={run.res.steps}")
    assert run.res.stack_used < 64 and d["wait"] < run.res.stack_used + 1


# ------------------------------------------------------------------ MUTANTS: byte patches of the BUILT service

def find(env: Env, pattern: bytes, nth: int | None = None) -> int:
    lo, hi = env.flat("SlinkTradeProposerService"), env.flat("SlinkTradeProposerServiceEnd")
    code = env.rom[lo:hi]
    hits = [i for i in range(len(code)) if code[i:i + len(pattern)] == pattern]
    assert hits, f"pattern {pattern.hex()} not found in the built service"
    assert nth is not None or len(hits) == 1, f"pattern {pattern.hex()} is not unique ({len(hits)} hits)"
    return lo + hits[nth or 0]


def le(env: Env, name: str) -> bytes:
    return env.a(name).to_bytes(2, "little")


def f(env: Env, off: int) -> bytes:
    return (env.lease + off).to_bytes(2, "little")


def patch(rom: bytes, at: int, old: bytes, new: bytes) -> bytes:
    assert len(old) == len(new) and rom[at:at + len(old)] == old, (hex(at), rom[at:at + len(old)].hex(), old.hex())
    out = bytearray(rom)
    out[at:at + len(new)] = new
    return bytes(out)


def mutant_done_result_zero(env):
    at = find(env, b"\x3e\x01\xcd" + le(env, "SlinkTradePublishDone"))
    return patch(env.rom, at, b"\x3e\x01", b"\x3e\x00")


def mutant_generation_before_payload(env):
    # PublishDone tail: ld a,DONE / ld [cmd],a / ld hl,sp+8 / ld a,[hl] / ld [gen],a / ld [ack],a  ->  generation and
    # ACK are published BEFORE the command (same length: the DONE command lands last)
    old = (b"\x3e\x07\xea" + f(env, 5) + b"\xf8\x08\x7e\xea" + f(env, 6) + b"\xea" + f(env, 7))
    new = (b"\xf8\x08\x7e\xea" + f(env, 6) + b"\xea" + f(env, 7) + b"\x3e\x07\xea" + f(env, 5))
    return patch(env.rom, find(env, old), old, new)


def mutant_drop_private_slot_check(env):
    old = b"\xf8\x04\xfa" + f(env, 9) + b"\xbe\xc2" + le(env, "SlinkTradeExit")
    at = find(env, old)
    return patch(env.rom, at, old, old[:-3] + b"\x00\x00\x00")


def mutant_drop_validate_snapshot(env):
    old = b"\xcd" + le(env, "SlinkTradeValidateSnapshot")
    return patch(env.rom, find(env, old), old, b"\xa7\x00\x00")           # and a (clear carry) / nop / nop


def mutant_drop_validate_incoming(env):
    old = b"\xcd" + le(env, "SlinkTradeValidateIncomingStaged")
    return patch(env.rom, find(env, old), old, b"\xa7\x00\x00")


def mutant_unbalanced_stack_on_timeout(env):
    # the APPLY wait's `jp z, SlinkTradeExit` after `dec bc / ld a,b / or c` becomes a bare `ret z`
    old = b"\x0b\x78\xb1\xca" + le(env, "SlinkTradeExit")
    at = find(env, old, nth=0)                                   # the first of the two timeout tails is the APPLY wait's
    assert at < find(env, old, nth=1)
    return patch(env.rom, at, old, b"\x0b\x78\xb1\xc8\x00\x00")


def mutant_skip_token_compare(env):
    # the APPLY wait loop's CheckToken call: ld hl,sp+0 / call CheckToken / jp c,Exit / ld a,[cmd] / cp APPLY
    old = (b"\xf8\x00\xcd" + le(env, "SlinkTradeCheckToken") + b"\xda" + le(env, "SlinkTradeExit")
           + b"\xfa" + f(env, 5) + b"\xfe\x05")
    at = find(env, old)
    return patch(env.rom, at + 2, old[2:5], b"\xa7\x00\x00")


def mutant_skip_count_check(env):
    # `ld hl,sp+8 / ld a,[wPartyCount] / cp [hl] / jp nz,Exit`  ->  no jump
    old = b"\xf8\x08\xfa" + le(env, "wPartyCount") + b"\xbe\xc2" + le(env, "SlinkTradeExit")
    return patch(env.rom, find(env, old), old, old[:-3] + b"\x00\x00\x00")


def mutant_skip_mask_check(env):
    old = b"\xcd" + le(env, "SlinkTradeCheckMask") + b"\xda" + le(env, "SlinkTradeExit")
    return patch(env.rom, find(env, old), old, b"\xa7\x00\x00\x00\x00\x00")


def mutant_skip_hvblank_check(env):
    old = b"\xf0\x8d\xa7\x20"            # ldh a,[hVBlank] / and a / jr nz
    return patch(env.rom, find(env, old), old, b"\xf0\x8d\xa7\x00")


def mutant_offer_result_ignored(env):
    old = b"\xfa" + f(env, 8) + b"\xa7\xc2" + le(env, "SlinkTradeExit")
    return patch(env.rom, find(env, old), old, old[:-3] + b"\x00\x00\x00")


def mutant_drop_validate_record(env):
    # CheckOwnSlot ends `jp SlinkTradeValidateRecord`: the own-record predicate becomes `and a / ret`
    old = b"\xc3" + le(env, "SlinkTradeValidateRecord")
    return patch(env.rom, find(env, old), old, b"\xa7\xc9\x00")


def mutant_drop_mail_policy_everywhere(env):
    # CheckOwnSlot's explicit SlinkTradeItemAllowed call AND the one inside SlinkTradeValidateRecord (the
    # service's call alone is defence in depth: ValidateRecord refuses the same mail, so that single patch is an
    # equivalent mutant and is deliberately not listed)
    old = b"\xcd" + le(env, "SlinkTradeItemAllowed")
    rom = patch(env.rom, find(env, old), old, b"\xa7\x00\x00")
    lo = env.flat("SlinkTradeValidateRecord")
    at = lo + env.rom[lo:lo + 0x40].index(old)
    return patch(rom, at, old, b"\xa7\x00\x00")


def _apply_bound(env):
    """The `ld bc, SLINK_TRADE_APPLY_FRAMES` immediate of the APPLY wait (3600 = $0E10, unique in the service)."""
    return find(env, b"")


def mutant_apply_bound_minus_one(env):
    # one frame short: the pre-fix behaviour (counter expires before the frame just returned is inspected) accepts
    # a request in at most 3599 frames
    at = _apply_bound(env)
    return patch(env.rom, at, b"", b"")


def mutant_apply_bound_plus_one(env):
    at = _apply_bound(env)
    return patch(env.rom, at, b"", b"")


MUTANTS = [
    ("done result 1 -> 0", mutant_done_result_zero, ("happy", "no_commit")),
    ("generation published before the payload", mutant_generation_before_payload, ("happy",)),
    ("private slot check dropped", mutant_drop_private_slot_check, ("wrong_slot",)),
    ("ValidateSnapshot call dropped", mutant_drop_validate_snapshot, ("own_record_flip",)),
    ("ValidateIncomingStaged call dropped", mutant_drop_validate_incoming, ("invalid_incoming",)),
    ("unbalanced stack on the APPLY timeout exit", mutant_unbalanced_stack_on_timeout, ("apply_timeout_and_b",)),
    ("APPLY window one frame short (old expiry order)", mutant_apply_bound_minus_one, ("apply_window",)),
    ("APPLY window one frame long", mutant_apply_bound_plus_one, ("apply_window", "apply_timeout_and_b")),
    ("token compare skipped in the APPLY wait", mutant_skip_token_compare, ("token_drift",)),
    ("party count check dropped", mutant_skip_count_check, ("party_changes",)),
    ("mask check dropped", mutant_skip_mask_check, ("mask_bits_above_count", "no_eligible_mon")),
    ("hVBlank check dropped", mutant_skip_hvblank_check, ("hvblank",)),
    ("OFFER result ignored", mutant_offer_result_ignored, ("offer_rejected",)),
    ("own-record predicate (ValidateRecord) dropped", mutant_drop_validate_record, ("own_mon_refused",)),
    ("mail policy dropped everywhere", mutant_drop_mail_policy_everywhere, ("own_mon_refused",)),
]


@pytest.mark.parametrize("label,make,scenarios", MUTANTS, ids=[m[0] for m in MUTANTS])
def test_each_mutant_of_the_built_bytes_is_caught_by_its_named_scenario(label, make, scenarios, env):
    mutated = make(env)
    assert mutated != env.rom, label
    for name in scenarios:
        SCENARIOS[name](env, None)                                          # the unmutated ROM passes ...
    caught = []
    for name in scenarios:
        try:
            SCENARIOS[name](env, mutated)                                   # ... and the mutated one must not
        except (AssertionError, S.Fault):
            caught.append(name)
    assert caught, f"mutant {label!r} survived every named scenario {scenarios}"
