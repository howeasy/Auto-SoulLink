"""Polished trade card C6: the held RESPONDER service, commit DISABLED
(patch/polished/src/trade_responder.asm; docs/polished/TRADE_COMMIT_RESPONDER.md section 4; TRADE.md s14-18).

Evidence: the REAL assembled bytes (the committed UPS applied to the pinned release ROM) run on the real SM83 machine
(tests/unit/polished_sm83.py: real SP, flags, `ld hl, sp+n`, the Polished `rst FarCall` model) against a SCRIPTED HOST
that acts on the 16-byte lease exactly as lua/gb_trade_lease.lua does (PROMPT/APPLY arm = the whole frame with the
generation previous+1 written LAST; RELEASE = command 8; DONE completion = the lua `completion` test). The native
routines the service calls (DelayFrame, JoyTextDelay, PrintText, YesNoBox, OpenText, CloseText, GetNickname) are
TRAPS (their claims are MODEL); every other byte (the Slink code, validators, snapshot, frame primitives and the
dispatcher itself) is the built ROM's own.

The service is entered the way the engine enters it: through `SlinkTradePromptEntry`, with a PROMPT already published
(and in one scenario through the REAL dispatcher on a fully valid engine state and the nine pinned stack bytes).

Every scenario asserts: the exact lease write ORDER (pickup ACK / DONE result,header,token,slot,command,generation,
ACK-last / close), a balanced stack (sp_delta == 0, one native call depth per transition), that no CPU write lands
outside the allowed set (lease, OT slot 1 snapshot, hROMBank, the stack) and never a party / box / save / SRAM /
OT slot 0 byte, that no DONE for an APPLY is ever result 0, that no commit-class native or farcall runs, and that the
text box opened is closed exactly once. Byte-patch MUTANTS of the built bytes must each go red in a named scenario.

Absent input skips (no cached release ROM); present-but-wrong input fails.
"""
from __future__ import annotations

import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
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

from tests.unit.test_polished_trade_dispatch import World  # noqa: E402

# the scripted host, the staging images and the constants are the proposer test's own (one lease model, two services)
from tests.unit.test_polished_trade_service import (  # noqa: E402
    APPLY,
    HROMBANK,
    LEASE_SIZE,
    MAGIC,
    NICKL,
    OTL,
    PAD_B,
    TOKEN,
    Env,
    Host,
    P,
    Stage,
    incoming_record,
    name,
    own_record,
)

RELEASE_ROM = Path(os.environ.get("SLINK_WORK_ROOT", "F:/slink-work")) / "cache/polished/release/polishedcrystal-3.2.3.gbc"
CLEAN_SYM = REPO / "data/polished/polishedcrystal.sym"
OVERLAY_SYM = REPO / "data/polished/polished_slink.sym"
UPS = REPO / "patch/dist/SLink-Polished.ups"
SRC = REPO / "patch/polished/src/trade_responder.asm"

BANK7E = 0x7E
PROMPT = 3
TEXT_NAMES = ("SlinkTradeResponderOfferText", "SlinkTradeWaitText")
# a commit-class native the responder must never reach (clean sym names; absent names are skipped)
COMMIT_NATIVES = ("AddTempMonToParty", "RemoveMonFromParty", "ShiftPartySlotToEnd", "CopyBetweenPartyAndTemp",
                  "DoNPCTrade", "Link_SaveGame", "ForceGameSave", "SaveAfterLinkTrade", "SaveGameData", "SavedTheGame",
                  "SaveStorageSystem", "TradeAnimation", "DoTradeAnimation", "EvolvePokemon", "FixPlayerEVsAndStats",
                  "HealParty", "Special_TryQuickSave")
NATIVES = {"delay": 0x0DA8, "joy": 0x07C3, "print": 0x0E58, "yesno": 0x18E0, "open": 0x275D, "close": 0x2721,
           "nick": 0x3232}


@pytest.fixture(scope="module")
def env():
    if not RELEASE_ROM.is_file():
        pytest.skip(f"pinned Polished release ROM not cached at {RELEASE_ROM}")
    rom = ups_apply(RELEASE_ROM.read_bytes(), UPS.read_bytes())
    return Env(bytes(rom), _symbols(OVERLAY_SYM), _symbols(CLEAN_SYM))


# ------------------------------------------------------------------ the lease write patterns

class Bad(AssertionError):
    pass


def segment(lw: list[tuple[int, int]]) -> tuple[str, list[dict]]:
    """Split the CPU's lease writes into publications; anything unmatched is an AssertionError.

    A = a pickup ACK (offset 7 alone: the PROMPT or the APPLY generation)
    D = DONE (result, header, token, slot, command 7, then generation and ACK = the same generation LAST)
    C = close (command, available, mask)
    """
    out, info, i = [], [], 0
    while i < len(lw):
        off = lw[i][0]
        if off == 7:
            want, kind = [(7, None)], "A"
        elif off == 8:
            want = [(8, None), (0, 0x53), (1, 0x4C), (2, 0x54), (3, 0x31), (4, 1), (12, None), (13, None), (14, None),
                    (15, None), (9, None), (5, 7), (6, None), (7, None)]
            kind = "D"
        elif off == 5:
            want, kind = [(5, 0), (10, 0), (11, 0)], "C"
        else:
            raise Bad(f"a lease write at offset {off} starts no known publication: {lw[max(0, i - 3):i + 3]}")
        got = lw[i:i + len(want)]
        if len(got) < len(want) or any(g[0] != w[0] or (w[1] is not None and g[1] != w[1]) for g, w in zip(got, want, strict=True)):
            raise Bad(f"the {kind} publication is out of order or incomplete at write {i}: got {got}, want offsets "
                      f"{[w[0] for w in want]}")
        vals = dict(got)
        if kind == "D" and vals[6] != vals[7]:
            raise Bad("DONE: generation and ACK differ")
        out.append(kind)
        info.append({"kind": kind, **{f"o{o}": v for o, v in vals.items()}})
        i += len(want)
    return "".join(out), info


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
    nested: list[dict]
    snap_first: int | None
    entry_sp: int


class Rig:
    def __init__(self, env: Env, *, party: int = 4, own: int = 2, gen0: int = 0x10, hvblank: int = 0,
                 rom: bytes | None = None, prompt_token=TOKEN, prompt_stage: Stage | None = None, contest: int = 0,
                 prompt_ack: int | None = None, prompt_cmd: int = PROMPT, prompt_kwargs: dict | None = None):
        self.env, self.party, self.own, self.gen0 = env, party, own, gen0
        self.hvblank, self.contest = hvblank, contest
        self.rom = env.rom if rom is None else rom
        self.prompt_token, self.prompt_stage = prompt_token, prompt_stage
        self.prompt_ack, self.prompt_cmd, self.prompt_kwargs = prompt_ack, prompt_cmd, prompt_kwargs or {}
        self._world: World | None = None
        self.b_next = False
        self.frame = 0
        self.marks: dict[str, int] = {}
        self.calls: list[tuple] = []
        self.lease = env.lease
        self.yesno = True
        self.on_native: Callable | None = None
        self.nest = False
        self.entry_hooks: dict[str, Callable] = {}      # overlay routine -> host action at its FIRST entry (then the code)

    def a(self, name: str) -> int:
        return self.env.a(name)

    def mark(self, what: str) -> None:
        self.marks[what] = self.frame

    def own_ranges(self, slot: int | None = None) -> list[tuple[int, int]]:
        s = self.own if slot is None else slot
        return [(self.a("wPartyMon1") + s * P, P), (self.a("wPartyMonOTs") + s * OTL, OTL),
                (self.a("wPartyMonNicknames") + s * NICKL, NICKL)]

    def build_ram(self, m: S.SM83) -> Host:
        a = self.a
        m.poke(a("wSavedAtLeastOnce"), 1)
        m.poke(a("wStatusFlags2"), 1 << 2 if self.contest else 0)
        m.poke(a("wPartyCount"), self.party)
        for i in range(6):
            m.poke(a("wPartyMon1") + i * P, own_record(i))
            m.poke(a("wPartyMonOTs") + i * OTL, name(40 + i))
            m.poke(a("wPartyMonNicknames") + i * NICKL, name(50 + i))
        m.poke(a("hVBlank"), self.hvblank)
        m.poke(HROMBANK, BANK7E)
        stale = [0] * LEASE_SIZE
        stale[6] = stale[7] = self.gen0
        stale[8], stale[9] = 0x99, 0x77
        stale[12:16] = (9, 9, 9, 9)
        m.poke(self.lease, bytes(stale))
        h = Host(self, m)
        # the PROMPT the dispatcher accepted: staged incoming mon + sender, then the frame with the generation LAST
        h.stage(self.prompt_stage)
        h.arm(self.own, self.prompt_token, command=self.prompt_cmd, ack=self.prompt_ack, **self.prompt_kwargs)
        return h

    def run(self, host: Callable | None = None, *, yesno: bool = True, rom: bytes | None = None, pcs: bool = False,
            tolerate_fault: bool = False, nest: bool = False, via_dispatch: bool = False, de: int = 0x1234) -> Run:
        env = self.env
        rom = self.rom if rom is None else rom
        m = S.SM83(rom, BANK7E, mbc="mbc3", farcall="model", hrombank=HROMBANK)
        m.farcall_allowed = set()                       # the responder issues NO farcall at all
        self.b_next, self.frame, self.marks, self.calls, self.yesno = False, 0, {}, [], yesno
        h = self.build_ram(m)
        gen = host(h) if host is not None else None
        state = {"gen": gen}
        entry_sp = S.DEFAULT_SP
        depths: dict[str, set] = {"delay": set(), "native": set()}
        nested: list[dict] = []
        text_names = {env.a(n): n for n in TEXT_NAMES}
        snap = [(self.a("wOTPartyMon2"), P), (self.a("wOTPartyMonOTs") + OTL, OTL), (self.a("wOTPartyMonNicknames") + NICKL, NICKL)]
        snap_first: list[int | None] = [None]

        def note_native(mm: S.SM83, what: str, **extra) -> None:
            depths["native"].add(entry_sp - mm.sp)
            wr = mm.mem.writes
            snapped = any(any(lo <= w[1] < lo + n for lo, n in snap) for w in wr)
            self.calls.append((what, self.frame, {"ack": mm.peek(self.lease + 7)[0], "gen": mm.peek(self.lease + 6)[0],
                                                  "snapped": snapped, **extra}))
            if nest:
                nested.extend(self.nested_probe(mm, what))
            if self.on_native is not None:
                self.on_native(h, what)

        def on_frame(mm: S.SM83) -> None:
            self.frame += 1
            depths["delay"].add(entry_sp - mm.sp)
            if nest and (self.frame <= 14 or self.frame % 997 == 0):
                nested.extend(self.nested_probe(mm, f"delay@{self.frame}"))
            g = state["gen"]
            if g is not None:
                try:
                    next(g)
                except StopIteration:
                    state["gen"] = None

        def on_joy(mm: S.SM83) -> None:
            mm.poke(0xFF00 + 0x97, PAD_B if self.b_next else 0)
            self.b_next = False

        def on_print(mm: S.SM83) -> None:
            note_native(mm, "print", text=text_names.get(mm.hl, f"{mm.hl:#06x}"))

        def on_yesno(mm: S.SM83) -> None:
            note_native(mm, "yesno")
            mm.cf = not self.yesno

        def on_open(mm: S.SM83) -> None:
            note_native(mm, "open")

        def on_close(mm: S.SM83) -> None:
            note_native(mm, "close")

        def on_nick(mm: S.SM83) -> None:
            note_native(mm, "nick", a=mm.a, hl=mm.hl)

        m.trap(NATIVES["delay"], on_frame)
        m.trap(NATIVES["joy"], on_joy)
        m.trap(NATIVES["print"], on_print)
        m.trap(NATIVES["yesno"], on_yesno)
        m.trap(NATIVES["open"], on_open)
        m.trap(NATIVES["close"], on_close)
        m.trap(NATIVES["nick"], on_nick)
        for routine, action in self.entry_hooks.items():
            hook_at = env.a(routine)

            def fire(mm: S.SM83, action=action, addr=hook_at) -> None:
                action(h)
                mm._traps.pop(addr)          # one-shot: the next step executes the routine's own first instruction
            m.trap(env.a(routine), fire, bank=BANK7E, ret=False)
        executed: set = set()
        if pcs:
            orig = m.step

            def step() -> None:
                executed.add((m.bank if m.pc >= 0x4000 else 0, m.pc))
                orig()
            m.step = step
        res = fault = None
        w0 = len(m.mem.writes)
        try:
            if via_dispatch:
                w = World(rom, env.sym)
                mem = {k: v for k, v in w.state().items() if not self.lease <= k < self.lease + LEASE_SIZE}
                for pos, v in w.stack().items():
                    mem[S.DEFAULT_SP - 2 + pos] = v
                res = m.call_routine(env.a("SlinkTradeDispatch"), {"de": de}, sp=S.DEFAULT_SP, mem=mem, bank=BANK7E,
                                     max_steps=6_000_000)
            else:
                res = m.call_routine(env.a("SlinkTradePromptEntry"), bank=BANK7E, max_steps=6_000_000)
        except S.Fault as exc:
            if not tolerate_fault:
                raise
            fault = exc
        writes = list(m.mem.writes)[w0:]
        for i, wr in enumerate(writes):
            if any(lo <= wr[1] < lo + n for lo, n in snap):
                snap_first = i
                break
        else:
            snap_first = None
        lw = [(a - self.lease, v) for _pc, a, v in writes if self.lease <= a < self.lease + LEASE_SIZE]
        events, info = segment(lw) if fault is None else ("?", [])
        return Run(res, fault, lw, writes, events, info, list(self.calls), self.frame, dict(self.marks), h, m, executed,
                   {k: sorted(v) for k, v in depths.items()}, nested, snap_first, entry_sp)

    # ---- re-entry: the REAL dispatcher run on the stack the service has at this very native call/wait
    def nested_probe(self, mm: S.SM83, where: str) -> list[dict]:
        env = self.env
        if self._world is None:
            self._world = World(self.rom, env.sym)
        w = self._world
        real = dict(zip(("cmd", "gen", "ack"), mm.peek(self.lease + 5, 3), strict=True))
        out = []
        engine = {k: v for k, v in w.state().items() if not self.lease <= k < self.lease + LEASE_SIZE}

        def lease_state(cmd, gen, ack):
            return {**engine, **{self.lease + i: b for i, b in enumerate(MAGIC)}, self.lease + 4: 1,
                    self.lease + 5: cmd, self.lease + 6: gen, self.lease + 7: ack}
        # the real chain above the DelayFrame/native call: the service's own frames
        chain = {pos: mm.peek((mm.sp + pos - 14) & 0xFFFF)[0] for pos in range(14, 44)}
        nested_stack = {**w.stack(), **chain}
        forged_gen = (real["ack"] + 1) & 0xFF
        for label, st, stack in (
                ("real lease", lease_state(real["cmd"], real["gen"], real["ack"]), nested_stack),
                ("forged fresh PROMPT", lease_state(PROMPT, forged_gen, real["ack"]), nested_stack)):
            _m, r, calls = w.run(st, stack)
            out.append({"where": where, "case": label, "accepted": bool(calls), "sp_delta": r.sp_delta})
        return out


def allowed_write(rig: Rig, run: Run) -> list[tuple[int, int, int]]:
    """CPU writes outside the lease, OT slot 1 (the snapshot), hROMBank and the stack. Empty = clean."""
    a = rig.a
    ok = [(rig.lease, LEASE_SIZE), (a("wOTPartyMon2"), P), (a("wOTPartyMonOTs") + OTL, OTL),
          (a("wOTPartyMonNicknames") + NICKL, NICKL), (HROMBANK, 1), (run.m.min_sp, S.DEFAULT_SP - run.m.min_sp)]
    return [w for w in run.writes if not any(lo <= w[1] < lo + n for lo, n in ok)]


def forbidden_hits(rig: Rig, run: Run) -> list:
    """Party / box / save / SRAM / OT slot 0 / the save flag: never written by the CPU."""
    a = rig.a
    forbidden = [(a("wPartyCount"), 1), (a("wPartyMon1"), 6 * P), (a("wPartyMonOTs"), 6 * OTL),
                 (a("wPartyMonNicknames"), 6 * NICKL), (a("wSavedAtLeastOnce"), 1), (a("wOTPartyMon1"), P),
                 (a("wOTPartyMonOTs"), OTL), (a("wOTPartyMonNicknames"), NICKL), (a("wOTPlayerName"), OTL),
                 (0xA000, 0x2000)]
    return [w for w in run.writes if any(lo <= w[1] < lo + n for lo, n in forbidden)]


def common(rig: Rig, run: Run, events: str, *, calls: list[str] | None = None, frames: int | None = None,
           results: list[int] | None = None) -> None:
    assert run.fault is None, f"the service faulted: {run.fault}"
    assert run.res.sp_delta == 0, f"unbalanced stack: sp_delta {run.res.sp_delta}"
    assert run.events == events, f"lease publications {run.events!r}, want {events!r}: {run.lease_writes}"
    bad = allowed_write(rig, run)
    assert not bad, f"CPU writes outside the allowed set: {[(hex(p), hex(a), v) for p, a, v in bad]}"
    assert not forbidden_hits(rig, run), f"a party/box/save/staging byte was written: {forbidden_hits(rig, run)}"
    assert run.m.farcalls == [], "the responder issued a farcall"
    assert events.endswith("C") and run.lease_writes[-3:] == [(5, 0), (10, 0), (11, 0)], "the lease was not closed"
    got = [d["o8"] for d in run.info if d["kind"] == "D"]
    if results is not None:
        assert got == results, f"DONE results {got}, want {results}"
    # ONE text box: opened at most once and closed exactly once, only if it was opened (never a stray CloseText)
    kinds = [c[0] for c in run.calls]
    assert kinds.count("close") == (1 if "open" in kinds else 0) and kinds.count("open") <= 1, kinds
    if kinds.count("open"):
        assert kinds.index("open") < kinds.index("close")
    if calls is not None:
        assert kinds == calls, f"native calls {kinds}, want {calls}"
    if frames is not None:
        assert run.frames == frames, f"{run.frames} frames, want {frames}"
    # every native call and every wait is reached at ONE stack depth (no extra frame across a shared wait/exit)
    assert len(run.depths["native"]) <= 1 and len(run.depths["delay"]) <= 1, run.depths
    # the lease stays closed-by-us: no commit-class native, no APPLY DONE of result 0
    dones = [d for d in run.info if d["kind"] == "D"]
    assert all(d["o8"] in (0, 1) for d in dones)


def snapshot_matches(rig: Rig, run: Run) -> bool:
    m, a = run.m, rig.a
    return (m.peek(a("wOTPartyMon2"), P) == own_record(rig.own)
            and m.peek(a("wOTPartyMonOTs") + OTL, OTL) == name(40 + rig.own)
            and m.peek(a("wOTPartyMonNicknames") + NICKL, NICKL) == name(50 + rig.own))


def host_consent(token=TOKEN, stage: Stage | None = None, apply: bool = True, apply_at: int = 3, release_at: int = 1,
                 tamper_before_apply=None, apply_slot: int | None = None, apply_kwargs: dict | None = None,
                 final_release: bool = True, overwrite_release_with_apply: bool = False, release_first: bool = True):
    """DONE(consent) -> RELEASE (frame release_at) -> staged APPLY on frame apply_at -> DONE -> RELEASE."""

    def script(h: Host):
        yield from h.until(h.done_pending)
        h.rig.mark("done0")
        yield from h.frames(release_at - 1)
        if overwrite_release_with_apply:
            h.stage(stage)
            h.arm(h.rig.own if apply_slot is None else apply_slot, token, command=APPLY, **(apply_kwargs or {}))
            h.rig.mark("apply_armed")
            yield from h.frames(10 ** 9)
        if release_first:
            h.release()
            h.rig.mark("release0")
        if not apply:
            return
        yield from h.frames(apply_at - release_at)
        if tamper_before_apply is not None:
            tamper_before_apply(h)
        h.stage(stage)
        h.arm(h.rig.own if apply_slot is None else apply_slot, token, command=APPLY, **(apply_kwargs or {}))
        h.rig.mark("apply_armed")
        if not final_release:
            return
        yield from h.until(h.done_pending)
        h.rig.mark("done1")
        yield from h.frames(1)
        h.release()
    return script


def happy_lease(g: int, own: int, token=TOKEN, apply_gen: int | None = None) -> list[tuple[int, int]]:
    """The exact CPU lease write sequence of a full visit: PROMPT pickup, consent DONE, APPLY pickup, DONE 1, close."""
    m = lambda x: x & 0xFF  # noqa: E731
    pg = m(g + 1)                                              # the PROMPT generation (gen0 + 1)
    ag = m(pg + 1) if apply_gen is None else apply_gen
    d = lambda r, gen: [(8, r), (0, 0x53), (1, 0x4C), (2, 0x54), (3, 0x31), (4, 1), (12, token[0]), (13, token[1]),  # noqa: E731
                        (14, token[2]), (15, token[3]), (9, own), (5, 7), (6, gen), (7, gen)]
    return [(7, pg), *d(0, pg), (7, ag), *d(1, ag), (5, 0), (10, 0), (11, 0)]


CONSENT_CALLS = ["nick", "open", "print", "yesno", "print", "close"]


# ------------------------------------------------------------------ scenarios (each is a named, callable check)

def sc_consent_yes(env: Env, rom: bytes | None = None, gen0: int = 0x10, party: int = 4, own: int = 2):
    rig = Rig(env, party=party, own=own, gen0=gen0, rom=rom)
    run = rig.run(host_consent(), pcs=True)
    common(rig, run, "ADADC", calls=CONSENT_CALLS, results=[0, 1])
    assert run.lease_writes == happy_lease(gen0, own), run.lease_writes
    assert [c[2]["text"] for c in run.calls if c[0] == "print"] == list(TEXT_NAMES)
    nick = run.calls[0]
    assert nick[2]["a"] == own and nick[2]["hl"] == rig.a("wPartyMonNicknames")
    # the pickup ACK precedes EVERY native UI call (the first one included)
    pg = (gen0 + 1) & 0xFF
    pre = [c for c in run.calls if c[0] != "close"]          # (the closing CloseText runs after the APPLY generation)
    assert pre and all(c[2]["ack"] == pg and c[2]["gen"] == pg for c in pre), [c[2] for c in pre]
    assert snapshot_matches(rig, run), "OT slot 1 does not hold the selected mon's 70 bytes"
    assert run.host.done_result == 1
    # the consent DONE is NOT a trade: the CPU never wrote a party/box/save byte (common) and the host saw result 0 first
    assert run.info[1]["o8"] == 0 and run.info[3]["o8"] == 1
    return rig, run


def sc_consent_no(env, rom=None):
    # YesNoBox returns carry for NO and for B alike (the native contract, trapped here): both are the DECLINE path
    rig = Rig(env, rom=rom)

    def host(h):
        yield from h.until(h.done_pending)
        yield from h.frames(2)
        h.release()
    run = rig.run(host, yesno=False)
    common(rig, run, "ADC", calls=["nick", "open", "print", "yesno", "close"], results=[1])
    assert not snapshot_matches(rig, run) and run.snap_first is None, "a decline must never snapshot"
    assert run.frames == 3, run.frames
    # no host RELEASE: the bounded 90-frame wait closes by itself, with the text closed once
    rig = Rig(env, rom=rom)
    run = rig.run(None, yesno=False)
    common(rig, run, "ADC", calls=["nick", "open", "print", "yesno", "close"], results=[1], frames=90)


def sc_b_escapes(env, rom=None):
    """B in every wait closes the lease at once: decline wait, consent RELEASE wait, APPLY wait, final RELEASE wait."""
    for where, events, results in (("decline", "ADC", [1]), ("release", "ADC", [0]), ("apply", "ADC", [0]),
                                   ("final", "ADADC", [0, 1])):
        rig = Rig(env, rom=rom)

        def host(h, where=where):
            if where == "decline":
                yield from h.frames(4)
                h.press_b()
                yield from h.frames(10)
                return
            yield from h.until(h.done_pending)
            if where == "release":
                yield from h.frames(3)
                h.press_b()
                yield from h.frames(10)
                return
            h.release()
            if where == "apply":
                yield from h.frames(5)
                h.press_b()
                yield from h.frames(10)
                return
            yield from h.frames(2)
            h.stage()
            h.arm(h.rig.own, TOKEN, command=APPLY)
            yield from h.until(h.done_pending)
            yield from h.frames(3)
            h.press_b()
            yield from h.frames(10)
        run = rig.run(host, yesno=(where != "decline"))
        n = 6 if where != "decline" else 5
        common(rig, run, events, results=results)
        assert run.frames < 25, (where, run.frames)
        assert len(run.calls) == n, (where, [c[0] for c in run.calls])


def sc_prompt_then_timeout(env, rom=None):
    """DONE(consent) and then nothing: ONE 3600-frame budget (RELEASE and APPLY share it), no mutation, close."""
    rig = Rig(env, rom=rom)
    run = rig.run(host_consent(apply=False, release_first=False))
    # host never RELEASEs nor APPLYs
    common(rig, run, "ADC", calls=CONSENT_CALLS, results=[0], frames=3600)
    # the host RELEASEs late (frame 1000) and never APPLYs: still 3600 frames in total
    rig = Rig(env, rom=rom)
    run = rig.run(host_consent(apply=False, release_at=1000))
    common(rig, run, "ADC", calls=CONSENT_CALLS, results=[0], frames=3600)
    # a RELEASE seen in the very last frame is harmless: the visit closes, nothing is mutated
    rig = Rig(env, rom=rom)
    run = rig.run(host_consent(apply=False, release_at=3600))
    common(rig, run, "ADC", calls=CONSENT_CALLS, results=[0], frames=3600)


def sc_apply_window(env, rom=None):
    """The shared 3600-frame budget inspects EVERY frame: an APPLY published during the last frame is accepted,
    one a frame later never exists. (Wait frame j == global frame j: the consent path calls DelayFrame only in waits.)"""
    for k in (4, 3599, 3600):
        rig = Rig(env, rom=rom)
        run = rig.run(host_consent(apply_at=k))
        common(rig, run, "ADADC", results=[0, 1])
        assert run.info[2]["kind"] == "A", k
    rig = Rig(env, rom=rom)
    run = rig.run(host_consent(apply_at=3601))
    common(rig, run, "ADC", results=[0], frames=3600)
    assert "apply_armed" not in run.marks or run.marks["apply_armed"] > 3600


def sc_release_before_apply(env, rom=None):
    """RELEASE of the PROMPT generation is an OBSERVED boundary: an APPLY that replaces it unobserved is ignored
    (never accepted, never ACKed), a RELEASE of another generation / ACK / token ends the visit."""
    rig = Rig(env, rom=rom)
    run = rig.run(host_consent(overwrite_release_with_apply=True))
    common(rig, run, "ADC", results=[0], frames=3600)
    assert run.host.rd(7) != run.host.rd(6), "the unobserved APPLY must remain un-ACKed"
    # RELEASE with a wrong generation / ACK in the release phase ends the visit at once; a wrong token is not a RELEASE
    for label, mutate, frames_max in (("gen", lambda h: h.wr(6, h.rd(6) ^ 1), 10), ("ack", lambda h: h.wr(7, h.rd(7) ^ 1), 10),
                                      ("token", lambda h: h.wr(13, h.rd(13) ^ 1), 10)):
        rig = Rig(env, rom=rom)

        def host(h, mutate=mutate):
            yield from h.until(h.done_pending)
            h.release()
            mutate(h)
            yield from h.frames(10 ** 9)
        run = rig.run(host)
        common(rig, run, "ADC", results=[0])
        assert run.frames <= frames_max, (label, run.frames)


def sc_token_generation_drift(env, rom=None):
    # (a) the PROMPT itself is unusable: zero token, wrong header, command, acknowledged generation -> nothing is
    #     ACKed, no native UI runs, the lease is just closed
    for kw in ({"prompt_token": (0, 0, 0, 0)}, {"prompt_cmd": 1}, {"prompt_cmd": 5}, {"prompt_cmd": 7}):
        rig = Rig(env, rom=rom, **kw)
        run = rig.run(None)
        common(rig, run, "C", calls=[], frames=0)
    rig = Rig(env, rom=rom, prompt_ack=0x11)                  # gen == ack: an acknowledged generation
    run = rig.run(None)
    common(rig, run, "C", calls=[], frames=0)
    for kw in ({"version": 2}, {"magic": (0x53, 0x4C, 0x54, 0x30)}):     # header broken before the first instruction
        rig = Rig(env, rom=rom, prompt_kwargs=kw)
        run = rig.run(None)
        common(rig, run, "C", calls=[], frames=0)

    # (b) the APPLY carries another token / zero / one flipped byte / a stale or skipped generation / wrong ACK / slot
    for label, kw in (("token", {}), ("gen+2", {"apply_kwargs": {"delta": 2}}), ("gen-1", {"apply_kwargs": {"delta": 0xFF}}),
                      ("gen+0", {"apply_kwargs": {"delta": 0}}), ("ack", {"apply_kwargs": {"ack": 0xAA}}),
                      ("slot", {"apply_slot": 1}), ("version", {"apply_kwargs": {"version": 2}}),
                      ("magic", {"apply_kwargs": {"magic": (0x53, 0x4C, 0x54, 0x30)}})):
        toks = ((0x55, 0x66, 0x77, 0x88), (0, 0, 0, 0), (0x11, 0x22, 0x33, 0x45), (0x10, 0x22, 0x33, 0x44)) if label == "token" else (TOKEN,)
        for tok in toks:
            rig = Rig(env, rom=rom)
            run = rig.run(host_consent(token=tok, **kw))
            if label == "gen+0":                              # an acknowledged generation is ignored: the wait runs out
                common(rig, run, "ADC", results=[0], frames=3600)
            else:
                common(rig, run, "ADC", results=[0])
                assert run.frames < 3600, (label, tok, run.frames)
    # (c) FF -> 00 generation wraps are fine at every step of the visit
    for g in (0xFC, 0xFD, 0xFE, 0xFF, 0x00, 0x7F):
        sc_consent_yes(env, rom, gen0=g)
    # (d) the frame is replaced while the native menu is open: another token / another generation -> no snapshot
    for label, mutate in (("token", lambda h: h.wr(14, h.rd(14) ^ 0x80)), ("gen", lambda h: h.wr(6, (h.rd(6) + 3) & 0xFF)),
                          ("ack", lambda h: h.wr(7, h.rd(7) ^ 1)), ("cmd", lambda h: h.wr(5, 5)),
                          ("magic", lambda h: h.wr(1, 0))):
        rig = Rig(env, rom=rom)
        done = []

        def on_native(h, what, mutate=mutate, done=done):
            if what == "yesno" and not done:
                done.append(1)
                mutate(h)
        rig.on_native = on_native
        run = rig.run(None)
        common(rig, run, "AC", calls=CONSENT_CALLS)
        assert run.snap_first is None, label


def sc_late_consent_cancel(env, rom=None):
    """The binder cancels the visit (zeroes the token) after the held-frame check, while the snapshot runs: the
    consent DONE must NOT be published and the private token must NOT be republished; the visit closes."""
    rig = Rig(env, rom=rom)
    cancelled = []

    def cancel(h: Host) -> None:
        for o in range(12, 16):
            h.wr(o, 0)
        cancelled.append(rig.frame)
    rig.entry_hooks["SlinkTradeSnapshot"] = cancel
    run = rig.run(None)
    assert cancelled, "the scheduled cancel never ran: SlinkTradeSnapshot was not reached"
    common(rig, run, "AC", calls=CONSENT_CALLS, results=[])
    assert not [w for w in run.lease_writes if 12 <= w[0] <= 15], f"the token was republished: {run.lease_writes}"
    assert run.m.peek(rig.lease + 12, 4) == bytes(4), "the cancelled token is not zero at exit"
    assert run.snap_first is not None, "the snapshot ran (the cancel landed after the held-frame check)"
    return rig, run


def sc_snapshot_after_menus(env, rom=None):
    rig, run = sc_consent_yes(env, rom)
    assert run.snap_first is not None
    # every native UI call (including the wait text printed after the YesNoBox) saw OT slot 1 still untouched: the
    # 70-byte snapshot is written only after the LAST native menu/text call returned
    natives = [c for c in run.calls if c[0] != "close"]
    assert [c[0] for c in natives] == ["nick", "open", "print", "yesno", "print"]
    assert all(c[2]["snapped"] is False for c in natives), [c[2] for c in natives]
    assert snapshot_matches(rig, run)


def sc_menu_party_changes(env, rom=None):
    """The party/selected mon changes WHILE the native YesNoBox is open: the post-menu re-check refuses, no snapshot."""
    for label, mutate in (("mail on the selected mon", lambda h: h.m.poke(h.rig.a("wPartyMon1") + h.rig.own * P + 1, 0xF5)),
                          ("selected mon species 0", lambda h: h.m.poke(h.rig.a("wPartyMon1") + h.rig.own * P, 0)),
                          ("party shrank below the slot", lambda h: h.m.poke(h.rig.a("wPartyCount"), 2)),
                          ("party emptied", lambda h: h.m.poke(h.rig.a("wPartyCount"), 0))):
        rig = Rig(env, rom=rom)
        done = []

        def on_native(h, what, mutate=mutate, done=done):
            if what == "yesno" and not done:
                done.append(1)
                mutate(h)
        rig.on_native = on_native
        run = rig.run(None)
        common(rig, run, "AC", calls=CONSENT_CALLS)
        assert run.snap_first is None, label


def sc_menu_count_changes(env, rom=None):
    """TRADE_COMMIT_RESPONDER.md 4(3): the party COUNT differs from the context capture after the native menus return
    (the selected slot is still valid): refuse BEFORE the snapshot and BEFORE the consent DONE -> AC, no DONE at all."""
    for newcount in (5, 3, 6):                                  # slot 2 stays valid for every one of these
        rig = Rig(env, rom=rom, party=4)
        done = []

        def on_native(h, what, newcount=newcount, done=done):
            if what == "yesno" and not done:
                done.append(1)
                h.m.poke(h.rig.a("wPartyCount"), newcount)
        rig.on_native = on_native
        run = rig.run(host_consent())                           # a host that would consent: the service must not get there
        common(rig, run, "AC", calls=CONSENT_CALLS, results=[])
        assert run.snap_first is None, newcount
        assert run.res.sp_delta == 0, newcount
    # control: the same hook with the count unchanged takes the normal consent path to the end
    rig = Rig(env, rom=rom, party=4)
    done = []

    def same_count(h, what, done=done):
        if what == "yesno" and not done:
            done.append(1)
            h.m.poke(h.rig.a("wPartyCount"), 4)
    rig.on_native = same_count
    run = rig.run(host_consent())
    common(rig, run, "ADADC", calls=CONSENT_CALLS, results=[0, 1])
    assert run.snap_first is not None


def sc_entry_refusals(env, rom=None):
    """Own slot / own record / contest / incoming staging refused BEFORE the pickup ACK and any native UI."""
    for kw in ({"contest": 1}, {"party": 0}, {"party": 7}, {"party": 255}):
        rig = Rig(env, rom=rom, **kw)
        run = rig.run(None)
        common(rig, run, "C", calls=[], frames=0)
    # the host's slot is outside the party / beyond the table
    for slot in (4, 5, 6, 7, 0xFF):
        rig = Rig(env, rom=rom, party=4)
        rig.own = slot
        run = rig.run(None)
        common(rig, run, "C", calls=[], frames=0)
    # the own mon fails a Polished predicate: mail, mail $FE, species 0, level 0, level 101, nature 25, ext species
    for off, val in ((1, 0xF5), (1, 0xFE), (0, 0), (31, 0), (31, 101), (20, 25), (21, 0x20)):
        rig = Rig(env, rom=rom)
        base = rig.a("wPartyMon1") + rig.own * P
        orig_build = rig.build_ram

        def build_ram(m, orig_build=orig_build, base=base, off=off, val=val):
            h = orig_build(m)
            m.poke(base + off, val)
            if off == 21:
                m.poke(base, 0x24)
            return h
        rig.build_ram = build_ram
        run = rig.run(None)
        common(rig, run, "C", calls=[], frames=0)


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
        ("species 0", with_rec(p0=0)), ("species $FF", with_rec(p0=0xFF)),
        ("species $100 (ext bit, low 0)", with_rec(p0=0, p21=0x20)), ("species $124", with_rec(p0=0x24, p21=0x20)),
        ("held mail $F5", with_rec(p1=0xF5)), ("held mail $FE", with_rec(p1=0xFE)),
        ("level 0", with_rec(p31=0)), ("level 101", with_rec(p31=101)), ("nature 25", with_rec(p20=25)),
    ]


def sc_invalid_incoming(env, rom=None):
    # at PROMPT time: refused before the ACK, no UI at all
    for label, st in _bad_stages():
        rig = Rig(env, rom=rom, prompt_stage=st)
        run = rig.run(None)
        assert run.fault is None, label
        common(rig, run, "C", calls=[], frames=0)
    # at APPLY time (the host restaged something invalid): the APPLY is picked up, then refused, no second DONE
    for label, st in _bad_stages():
        rig = Rig(env, rom=rom)
        run = rig.run(host_consent(stage=st))
        assert run.fault is None, label
        common(rig, run, "ADAC", results=[0])


def sc_good_incoming_boundaries(env, rom=None):
    rec = bytearray(incoming_record())
    for p0, p21, lvl in ((1, 0, 1), (0xFE, 0, 100), (1, 0x20, 50), (0x23, 0x20, 50), (25, 0x40, 5)):
        rec[0], rec[21], rec[31] = p0, p21, lvl
        st = Stage(rec=bytes(rec), nick=bytes([0x53]) + bytes(10))
        rig = Rig(env, rom=rom, prompt_stage=st)
        run = rig.run(host_consent(stage=st))
        common(rig, run, "ADADC", results=[0, 1])


def sc_own_record_flip(env, rom=None):
    """Every one of the 70 snapshotted bytes of the selected mon flipped between the consent snapshot and the APPLY."""
    rig0 = Rig(env, rom=rom)
    targets = [lo + i for lo, n in rig0.own_ranges() for i in range(n)]
    assert len(targets) == 70
    for addr in targets:
        rig = Rig(env, rom=rom)

        def tamper(h, addr=addr):
            h.m.poke(addr, h.m.peek(addr)[0] ^ 0x01)
        run = rig.run(host_consent(tamper_before_apply=tamper))
        assert run.fault is None and run.res.sp_delta == 0
        assert run.events == "ADAC", (hex(addr), run.events)
        assert [d["o8"] for d in run.info if d["kind"] == "D"] == [0], hex(addr)
        assert not allowed_write(rig, run) and not forbidden_hits(rig, run)


def sc_party_count_changes(env, rom=None):
    for newcount in (3, 5, 6, 1):
        rig = Rig(env, party=4, rom=rom)
        run = rig.run(host_consent(tamper_before_apply=lambda h, n=newcount: h.m.poke(h.rig.a("wPartyCount"), n)))
        assert run.fault is None and run.res.sp_delta == 0
        assert run.events == "ADAC", (newcount, run.events)
    rig = Rig(env, party=4, rom=rom)
    run = rig.run(host_consent(tamper_before_apply=lambda h: h.m.poke(h.rig.a("wPartyMon1") + h.rig.own * P + 1, 0xF5)))
    assert run.events == "ADAC"
    # a Bug-Catching Contest starts under the hold (party count and the own record are unchanged: only the own-slot
    # predicate, which includes the contest refusal, can see it -- ValidateSnapshot compares bytes only)
    rig = Rig(env, party=4, rom=rom)
    run = rig.run(host_consent(tamper_before_apply=lambda h: h.m.poke(h.rig.a("wStatusFlags2"), 1 << 2)))
    assert run.fault is None and run.res.sp_delta == 0 and run.events == "ADAC", run.events


def sc_hvblank(env, rom=None):
    """hVBlank != 0 refuses every wait at once (the dispatcher already required 0 at entry)."""
    for phase in ("decline", "release", "apply", "final"):
        rig = Rig(env, rom=rom)

        def host(h, phase=phase):
            if phase == "decline":
                yield from h.frames(2)
                h.hvblank(3)
                yield from h.frames(10 ** 9)
            yield from h.until(h.done_pending)
            if phase == "release":
                h.hvblank(3)
                yield from h.frames(10 ** 9)
            h.release()
            if phase == "apply":
                yield from h.frames(2)
                h.hvblank(3)
                yield from h.frames(10 ** 9)
            yield from h.frames(2)
            h.stage()
            h.arm(h.rig.own, TOKEN, command=APPLY)
            yield from h.until(h.done_pending)
            h.hvblank(3)
            yield from h.frames(10 ** 9)
        run = rig.run(host, yesno=(phase != "decline"))
        events = {"decline": "ADC", "release": "ADC", "apply": "ADC", "final": "ADADC"}[phase]
        common(rig, run, events)
        assert run.frames < 12, (phase, run.frames)


def sc_stack_balance(env, rom=None):
    """sp_delta == 0 on the full path and the short ones; the report carries min_sp / stack_used / native depth."""
    rig, run = sc_consent_yes(env, rom)
    assert run.res.sp_delta == 0
    # the whole visit (context 10 + the return slot 2 + one call deeper for the helpers) stays small and constant
    assert run.res.stack_used <= 64, run.res.stack_used
    assert run.depths["native"] and run.depths["delay"]
    return rig, run


def sc_via_dispatcher(env, rom=None):
    """The service entered the way the engine does it: the REAL dispatcher on a valid idle-overworld state."""
    rig = Rig(env, rom=rom)
    run = rig.run(host_consent(), via_dispatch=True)
    assert run.fault is None
    assert run.res.sp_delta == 0 and run.res.de == 0x1234, (run.res.sp_delta, hex(run.res.de))   # DE preserved
    assert run.events == "ADADC", run.events
    assert [c[0] for c in run.calls] == CONSENT_CALLS
    assert not forbidden_hits(rig, run)
    return run


def sc_reentry(env, rom=None):
    """While the native menu / text / waits are live the dispatcher must not fire a second time: the REAL dispatcher
    run on the service's real stack, with the real lease and with a forged fresh PROMPT."""
    rig = Rig(env, rom=rom)
    run = rig.run(host_consent(), nest=True)
    common(rig, run, "ADADC", results=[0, 1])
    probes = run.nested
    # every native call and every wait frame of the visit (release, apply and final-release waits are all < 14 frames here)
    assert run.frames <= 14 and len(probes) == 2 * (len(CONSENT_CALLS) + run.frames), (len(probes), run.frames)
    assert {p["case"] for p in probes} == {"real lease", "forged fresh PROMPT"}
    assert {p["where"].split("@")[0] for p in probes} >= {"nick", "open", "print", "yesno", "close", "delay"}
    accepted = [p for p in probes if p["accepted"]]
    assert not accepted, f"the dispatcher accepted a nested call: {accepted[:3]}"
    assert all(p["sp_delta"] == 0 for p in probes)
    # CONTROL: the same forged PROMPT with the PINNED idle-overworld stack IS accepted (the stack guard is what refuses)
    w = World(rig.rom, env.sym)
    st = dict(w.state())
    st.update({rig.lease + 5: PROMPT, rig.lease + 6: 0x21, rig.lease + 7: 0x20})
    assert w.accepted(st), "control: a valid forged PROMPT on the idle stack must be accepted"


def sc_no_commit(env, rom=None):
    rig, run = sc_consent_yes(env, rom)
    sym = env.sym
    assert env.rom[env.flat("SlinkTradeCommitEnabled")] == 0, "the release commit gate is enabled"
    assert sym["SlinkTradeCommit"] not in run.pcs and sym["SlinkTradeApplyCommit"] not in run.pcs
    deny = {env.clean[n] for n in COMMIT_NATIVES if n in env.clean}
    assert deny, "no commit natives resolved from the clean sym"
    hit = sorted(n for n in COMMIT_NATIVES if n in env.clean and env.clean[n] in run.pcs)
    assert not hit, f"executed a commit-class routine: {hit}"
    lo, hi = env.flat("SlinkTradeResponderService"), env.flat("SlinkTradeResponderServiceEnd")
    code = env.rom[lo:hi]
    assert not static_commit_scan(code, {n: env.clean[n] for n in COMMIT_NATIVES if n in env.clean})
    # no `rst $10` (FarCall) anywhere in the responder: it issues no farcall at all
    text_at = env.flat("SlinkTradeResponderOfferText") - lo
    assert b"\xd7" not in _opcode_stream(code[:text_at]), "the responder contains a FarCall (rst $10)"
    # the DONE for an APPLY is never result 0, and the only result-0 DONE precedes the (single) APPLY pickup
    dones = [d["o8"] for d in run.info if d["kind"] == "D"]
    assert dones == [0, 1]
    assert run.events.index("D") < run.events.index("A", 1)


def static_commit_scan(code: bytes, denied: dict[str, tuple[int, int]]) -> list[str]:
    """Direct call/jp operands and farcall records naming a denied routine inside `code` (names only)."""
    hits = []
    for n, (bank, addr) in denied.items():
        word = addr.to_bytes(2, "little")
        for i in range(len(code) - 2):
            jumps = code[i] in (0xCD, 0xC3, 0xC2, 0xCA, 0xD2, 0xDA, 0xC4, 0xCC, 0xD4, 0xDC)
            if jumps and code[i + 1:i + 3] == word and bank in (0, BANK7E):
                hits.append(f"{n}: called/jumped to at +{i:#x}")
        if word + bytes([bank]) in code:
            hits.append(f"{n}: far-called")
    return hits


def _opcode_stream(code: bytes) -> bytes:
    """A crude linear opcode walk of the SM83 code (enough to spot an `rst $10`): operand bytes are skipped."""
    length = {}
    for op in range(256):
        if op in (0x01, 0x11, 0x21, 0x31, 0x08, 0xC2, 0xC3, 0xC4, 0xCA, 0xCC, 0xCD, 0xD2, 0xD4, 0xDA, 0xDC, 0xEA, 0xFA):
            length[op] = 3
        elif op in (0x06, 0x0E, 0x16, 0x1E, 0x26, 0x2E, 0x36, 0x3E, 0x18, 0x20, 0x28, 0x30, 0x38, 0xC6, 0xCE, 0xD6, 0xDE,
                    0xE0, 0xE6, 0xE8, 0xEE, 0xF0, 0xF6, 0xF8, 0xFE, 0xCB):
            length[op] = 2
        else:
            length[op] = 1
    out, i = bytearray(), 0
    while i < len(code):
        out.append(code[i])
        i += length[code[i]]
    return bytes(out)


SCENARIOS: dict[str, Callable] = {
    "consent_yes": sc_consent_yes, "consent_no": sc_consent_no, "b_escapes": sc_b_escapes,
    "prompt_then_timeout": sc_prompt_then_timeout, "apply_window": sc_apply_window,
    "release_before_apply": sc_release_before_apply, "token_generation_drift": sc_token_generation_drift,
    "snapshot_after_menus": sc_snapshot_after_menus, "menu_party_changes": sc_menu_party_changes, "menu_count_changes": sc_menu_count_changes,
    "entry_refusals": sc_entry_refusals, "invalid_incoming": sc_invalid_incoming,
    "good_incoming": sc_good_incoming_boundaries, "own_record_flip": sc_own_record_flip,
    "party_count_changes": sc_party_count_changes, "hvblank": sc_hvblank, "stack_balance": sc_stack_balance,
    "via_dispatcher": sc_via_dispatcher, "reentry": sc_reentry, "no_commit": sc_no_commit,
    "late_consent_cancel": sc_late_consent_cancel,
}


@pytest.mark.parametrize("scenario", list(SCENARIOS))
def test_scenario(scenario, env):
    SCENARIOS[scenario](env)


# ------------------------------------------------------------------ the layout / source contract

def test_the_responder_symbols_and_the_section_limits(env):
    s = env.sym
    lo, hi = s["SlinkTradeResponderService"][1], s["SlinkTradeResponderServiceEnd"][1]
    assert s["SlinkTradeResponderService"][0] == s["SlinkTradeResponderServiceEnd"][0] == BANK7E
    assert lo == 0x5000 and 200 < hi - lo <= 0x300, f"the responder ends at {hi:#06x}"
    assert s["SlinkTradeProposerServiceEnd"][1] <= lo, "the responder overlaps the proposer slot"
    for n in ("SlinkTradeResponderWait", "SlinkTradeResponderRelease", "SlinkTradeResponderExit",
              "SlinkTradeResponderOfferText"):
        assert lo < s[n][1] < hi and s[n][0] == BANK7E, n
    for n, addr in NATIVES.items():
        if n != "delay" and n != "joy":
            assert addr in {a for (b, a) in env.clean.values() if b == 0}, n
    assert env.clean["OpenText"] == (0, NATIVES["open"]) and env.clean["CloseText"] == (0, NATIVES["close"])
    assert env.clean["GetNickname"] == (0, NATIVES["nick"])


def test_the_prompt_entry_is_a_three_byte_jp_trampoline_into_the_service(env):
    at = env.flat("SlinkTradePromptEntry")
    assert env.rom[at:at + 3] == b"\xc3" + env.a("SlinkTradeResponderService").to_bytes(2, "little")
    assert env.a("SlinkTradePromptEntry") == 0x4780 and env.a("SlinkTradeDispatchEnd") == 0x4783
    # the dispatcher still pushes DE and CALLs the entry (`push de / call PromptEntry / pop de / ret`)
    end = env.flat("SlinkTradeDispatchCodeEnd")
    assert env.rom[end - 6:end] == b"\xd5\xcd" + env.a("SlinkTradePromptEntry").to_bytes(2, "little") + b"\xd1\xc9"


def test_the_overlay_invariants_hold(env):
    rom = env.rom
    assert rom[0x70:0x77].hex() == "f044e0d7afe08f"
    assert rom[0xDA8:0xDAF].hex() == "cd700000000000"
    assert rom[0x1F8000:0x1F8010].hex() == "210bc63e53223e4c223e4e223e4b223e"
    assert rom[0xC030:0xC036].hex() == "7e00447e1044"


def test_source_shape(env):
    # Preserve the old no-commit assertion as an executable ROM gate, not a
    # prohibition on a helper being present elsewhere in the cartridge.
    assert env.rom[env.flat("SlinkTradeCommitEnabled")] == 0
    lo, hi = env.flat("SlinkTradeResponderService"), env.flat("SlinkTradeResponderServiceEnd")
    assert not static_commit_scan(env.rom[lo:hi], {"SlinkTradeApplyCommit": env.sym["SlinkTradeApplyCommit"],
                                                 **{n: env.clean[n] for n in COMMIT_NATIVES if n in env.clean}})


def test_report_the_stack_budgets(env, capsys):
    rig, run = sc_consent_yes(env)
    via = sc_via_dispatcher(env)
    print(f"[budget] PromptEntry entry: stack_used={run.res.stack_used} min_sp={run.res.min_sp:#06x} "
          f"entry_sp={S.DEFAULT_SP:#06x} native-depth={run.depths['native']} wait-depth={run.depths['delay']} "
          f"steps={run.res.steps}")
    print(f"[budget] via the dispatcher: stack_used={via.res.stack_used} min_sp={via.res.min_sp:#06x} sp_delta={via.res.sp_delta}")
    assert via.res.stack_used == run.res.stack_used + 4      # the dispatcher's push de + its call's return slot


# ------------------------------------------------------------------ MUTANTS: byte patches of the BUILT responder

def find(env: Env, pattern: bytes, nth: int | None = None) -> int:
    lo, hi = env.flat("SlinkTradeResponderService"), env.flat("SlinkTradeResponderServiceEnd")
    code = env.rom[lo:hi]
    hits = [i for i in range(len(code)) if code[i:i + len(pattern)] == pattern]
    assert hits, f"pattern {pattern.hex()} not found in the built responder"
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


def nop_call(env, name, nth=None, rom=None):
    old = b"\xcd" + le(env, name)
    return patch(env.rom if rom is None else rom, find(env, old, nth), old, b"\xa7\x00\x00")           # and a / nop / nop


def mutant_prompt_entry_is_the_old_stub(env):
    at = env.flat("SlinkTradePromptEntry")
    return patch(env.rom, at, env.rom[at:at + 3], b"\xc9\x00\x00")                                    # the pre-C6 bare `ret`


def mutant_pickup_ack_dropped(env):
    old = b"\xf8\x06\x7e\xea" + f(env, 7)
    return patch(env.rom, find(env, old), old, old[:3] + b"\x00\x00\x00")


def mutant_snapshot_before_menus(env):
    # the call to GetNickname (before OpenText) becomes the snapshot: it is taken BEFORE every native menu
    old = b"\xcd" + env.clean["GetNickname"][1].to_bytes(2, "little")
    return patch(env.rom, find(env, old), old, b"\xcd" + le(env, "SlinkTradeSnapshot"))


def mutant_consent_done_result_one(env):
    old = b"\x3e\x00\xcd" + le(env, "SlinkTradePublishDone")
    return patch(env.rom, find(env, old), old, b"\x3e\x01" + old[2:])


def mutant_apply_done_result_zero(env):
    old = b"\x3e\x01\xcd" + le(env, "SlinkTradePublishDone")
    return patch(env.rom, find(env, old, 1), old, b"\x3e\x00" + old[2:])


def mutant_decline_done_result_zero(env):
    old = b"\x3e\x01\xcd" + le(env, "SlinkTradePublishDone")
    return patch(env.rom, find(env, old, 0), old, b"\x3e\x00" + old[2:])


def mutant_close_text_dropped(env):
    return nop_call(env, "CloseText")


def mutant_close_text_unconditional(env):
    old = b"\xcb\x7e\x28"                                         # bit 7,[hl] / jr z
    return patch(env.rom, find(env, old), old, b"\xcb\x7e\x00")


def mutant_release_flag_not_set(env):
    old = b"\xcb\xc6\x3e\x00\xcd" + le(env, "SlinkTradePublishDone")           # set 0,[hl] / ld a,0 / call PublishDone
    return patch(env.rom, find(env, old), old, b"\x00\x00" + old[2:])


def mutant_apply_bound_short(env):
    old = b"\x01\x10\x0e"
    return patch(env.rom, find(env, old), old, b"\x01\x0f\x0e")


def mutant_apply_bound_long(env):
    old = b"\x01\x10\x0e"
    return patch(env.rom, find(env, old), old, b"\x01\x11\x0e")


def mutant_token_compare_dropped_in_wait(env):
    old = b"\xf8\x00\xcd" + le(env, "SlinkTradeCheckToken") + b"\xda" + le(env, "SlinkTradeResponderExit") + b"\xfa" + f(env, 5)
    return patch(env.rom, find(env, old), old, b"\xf8\x00\xa7\x00\x00" + old[5:])


def mutant_late_consent_recheck_dropped(env):
    # the token recheck between the snapshot and the consent DONE: ld hl,sp+0 / call CheckToken / jp c,Exit -> nops
    old = (b"\xf8\x00\xcd" + le(env, "SlinkTradeCheckToken") + b"\xda" + le(env, "SlinkTradeResponderExit")
           + b"\xf8\x09\xcb\xc6")
    return patch(env.rom, find(env, old), old, b"\x00" * 8 + old[8:])


def mutant_validate_snapshot_dropped(env):
    return nop_call(env, "SlinkTradeValidateSnapshot")


def mutant_validate_incoming_entry_dropped(env):
    return nop_call(env, "SlinkTradeValidateIncomingStaged", 0)


def mutant_validate_incoming_apply_dropped(env):
    return nop_call(env, "SlinkTradeValidateIncomingStaged", 1)


def mutant_own_slot_recheck_after_menu_dropped(env):
    return nop_call(env, "SlinkTradeCheckOwnSlot", 1)


def mutant_own_slot_recheck_at_apply_dropped(env):
    return nop_call(env, "SlinkTradeCheckOwnSlot", 2)


def mutant_held_frame_check_dropped(env):
    return nop_call(env, "SlinkTradeCheckHeldFrame")


def mutant_count_check_dropped(env):
    # the post-APPLY compare (the second of the two identical `ld hl,sp+8 / ld a,[wPartyCount] / cp [hl] / jp nz` runs)
    old = b"\xf8\x08\xfa" + le(env, "wPartyCount") + b"\xbe\xc2" + le(env, "SlinkTradeResponderExit")
    return patch(env.rom, find(env, old, 1), old, old[:-3] + b"\x00\x00\x00")


def mutant_count_check_after_menu_dropped(env):
    # the post-menu compare (the first run): before the snapshot and the consent DONE
    old = b"\xf8\x08\xfa" + le(env, "wPartyCount") + b"\xbe\xc2" + le(env, "SlinkTradeResponderExit")
    return patch(env.rom, find(env, old, 0), old, old[:-3] + b"\x00\x00\x00")


def mutant_private_slot_check_dropped(env):
    old = b"\xf8\x04\xfa" + f(env, 9) + b"\xbe\xc2" + le(env, "SlinkTradeResponderExit")
    return patch(env.rom, find(env, old), old, old[:-3] + b"\x00\x00\x00")


def mutant_generation_plus_one_dropped(env):
    old = b"\x3c\xba\xc2" + le(env, "SlinkTradeResponderExit")            # inc a / cp d / jp nz
    return patch(env.rom, find(env, old), old, old[:-3] + b"\x00\x00\x00")


def mutant_entry_generation_guard_dropped(env):
    old = b"\xfa" + f(env, 7) + b"\xb8\xca" + le(env, "SlinkTradeResponderExit")        # ld a,[ack] / cp b / jp z
    return patch(env.rom, find(env, old), old, old[:-3] + b"\x00\x00\x00")


def mutant_unbalanced_exit(env):
    old = b"\xe8\x0a\xc9"                                                  # add sp, 10 / ret
    return patch(env.rom, find(env, old), old, b"\xe8\x08\xc9")


def mutant_release_generation_compare_dropped(env):
    old = b"\xfa" + f(env, 6) + b"\xbe\xc2" + le(env, "SlinkTradeResponderExit")        # RELEASE gen == ctx gen
    return patch(env.rom, find(env, old, 0), old, old[:-3] + b"\x00\x00\x00")


def mutant_yes_no_inverted(env):
    old = b"\xcd" + env.clean["YesNoBox"][1].to_bytes(2, "little") + b"\x38"                # call YesNoBox / jr c
    return patch(env.rom, find(env, old), old, old[:-1] + b"\x30")


def mutant_no_open_text(env):
    return nop_call(env, "OpenText")


MUTANTS = [
    ("PromptEntry is the pre-C6 bare ret stub", mutant_prompt_entry_is_the_old_stub, ("consent_yes", "consent_no", "via_dispatcher")),
    ("pickup ACK dropped", mutant_pickup_ack_dropped, ("consent_yes",)),
    ("snapshot taken before the menus", mutant_snapshot_before_menus, ("snapshot_after_menus",)),
    ("consent DONE result 0 -> 1", mutant_consent_done_result_one, ("consent_yes",)),
    ("APPLY DONE result 1 -> 0", mutant_apply_done_result_zero, ("consent_yes", "no_commit")),
    ("decline DONE result 1 -> 0", mutant_decline_done_result_zero, ("consent_no",)),
    ("CloseText dropped", mutant_close_text_dropped, ("consent_yes", "consent_no")),
    ("CloseText unconditional", mutant_close_text_unconditional, ("entry_refusals",)),
    ("OpenText dropped", mutant_no_open_text, ("consent_yes",)),
    ("RELEASE-owed flag never set", mutant_release_flag_not_set, ("release_before_apply",)),
    ("shared wait budget one frame short", mutant_apply_bound_short, ("apply_window", "prompt_then_timeout")),
    ("shared wait budget one frame long", mutant_apply_bound_long, ("apply_window", "prompt_then_timeout")),
    ("token compare dropped in the wait", mutant_token_compare_dropped_in_wait, ("token_generation_drift", "release_before_apply")),
    ("ValidateSnapshot dropped", mutant_validate_snapshot_dropped, ("own_record_flip",)),
    ("ValidateIncomingStaged dropped at PROMPT", mutant_validate_incoming_entry_dropped, ("invalid_incoming",)),
    ("ValidateIncomingStaged dropped at APPLY", mutant_validate_incoming_apply_dropped, ("invalid_incoming",)),
    ("own-slot recheck after the menu dropped", mutant_own_slot_recheck_after_menu_dropped, ("menu_party_changes",)),
    ("own-slot recheck at APPLY dropped", mutant_own_slot_recheck_at_apply_dropped, ("party_count_changes",)),
    ("held-frame check dropped", mutant_held_frame_check_dropped, ("token_generation_drift",)),
    ("party count check dropped", mutant_count_check_dropped, ("party_count_changes",)),
    ("party count check after the menu dropped", mutant_count_check_after_menu_dropped, ("menu_count_changes",)),
    ("private slot check dropped", mutant_private_slot_check_dropped, ("token_generation_drift",)),
    ("APPLY generation previous+1 check dropped", mutant_generation_plus_one_dropped, ("token_generation_drift",)),
    ("entry generation != ACK guard dropped", mutant_entry_generation_guard_dropped, ("token_generation_drift",)),
    ("unbalanced stack on exit", mutant_unbalanced_exit, ("consent_yes", "stack_balance")),
    ("RELEASE generation compare dropped", mutant_release_generation_compare_dropped, ("release_before_apply",)),
    ("YesNoBox carry inverted", mutant_yes_no_inverted, ("consent_yes", "consent_no")),
    ("late-consent token recheck dropped", mutant_late_consent_recheck_dropped, ("late_consent_cancel",)),
]


@pytest.mark.parametrize("label,make,scenarios", MUTANTS, ids=[m[0] for m in MUTANTS])
def test_each_mutant_of_the_built_bytes_is_caught_by_its_named_scenario(label, make, scenarios, env):
    mutated = make(env)
    assert mutated != env.rom, label
    for scn in scenarios:
        SCENARIOS[scn](env, None)                                           # the unmutated ROM passes ...
    caught = []
    for scn in scenarios:
        try:
            SCENARIOS[scn](env, mutated)                                    # ... and the mutated one must not
        except (AssertionError, S.Fault):
            caught.append(scn)
    assert caught, f"mutant {label!r} survived every named scenario {scenarios}"


def test_the_nested_dispatcher_probe_is_red_when_the_dispatcher_guard_is_removed(env):
    """Red control for sc_reentry: a dispatcher whose fingerprint guard is gone ACCEPTS a nested call (else the
    reentry scenario could never fail)."""
    w = World(env.rom, env.sym)
    entry = w.entry
    # NOP the saved-bank guard and the +12/13 + +14/15 + +24..27 position guards: ld hl,sp+n / ld a,[hl] / cp n / ret nz
    rom = bytearray(env.rom)
    at = pc._flat(BANK7E, entry)
    code = bytes(rom[at:at + 0x7A])
    # every `ret nz` (C0) directly after a `cp imm` in the first 0x4a bytes is a stack-pin guard: make them `nop`s
    for i in range(1, 0x4A):
        if code[i] == 0xC0 and code[i - 2] == 0xFE:
            rom[at + i] = 0x00
    mutated = bytes(rom)
    rig = Rig(env, rom=mutated)
    run = rig.run(host_consent(), nest=True)
    assert [p for p in run.nested if p["accepted"]], "the mutated dispatcher must accept a nested call"


def test_the_service_is_red_on_the_old_bare_ret_stub(env):
    with pytest.raises(AssertionError):
        sc_consent_yes(env, mutant_prompt_entry_is_the_old_stub(env))


def test_the_static_commit_scan_is_red_on_an_injected_call_and_far_call(env):
    lo = env.flat("SlinkTradeResponderService")
    code = env.rom[lo:env.flat("SlinkTradeResponderServiceEnd")]
    assert static_commit_scan(code, {n: env.clean[n] for n in COMMIT_NATIVES if n in env.clean}) == []
    # the clean sym has no ROM0 commit routine, so deny a ROM0 routine the responder really calls: the scan must flag it
    assert static_commit_scan(code, {"CloseText": env.clean["CloseText"]}), "the scan cannot see a direct call"
    # and a far-call record naming a denied banked routine
    fake = {"AddTempMonToParty": env.clean["AddTempMonToParty"]}
    bank, addr = fake["AddTempMonToParty"]
    assert static_commit_scan(code + addr.to_bytes(2, "little") + bytes([bank]), fake), "the scan cannot see a farcall record"
