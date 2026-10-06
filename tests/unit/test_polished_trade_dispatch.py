"""Polished trade card D1/D2: the responder DISPATCHER (patch/polished/src/trade_dispatch.asm, TRADE.md s18).

The REAL built bytes (the committed UPS applied to the pinned release ROM) run on the real SM83 interpreter
(tests/unit/polished_sm83.py, real SP, `ld hl, sp+n`, push/pop, flags). Nothing here pastes an address: every
position, value and symbol comes from data/polished/polished_slink.sym or from the pinned source constants.

Evidence, by group:
 (0) the built routine EQUALS an independent byte model assembled from the symbols (so every guard's `ret cc`
     is located by construction, not by searching for a constant);
 (a) the positive vector (trap fires once, DE restored, sp balanced, no lease/WRAM write by the dispatcher);
 (b) the NINE pinned stack bytes, each alone invalid -> refused; (c) every other stack byte flipped -> still
     accepted, and the set of stack bytes the dispatcher READS is exactly the nine (the mask is structural);
 (d) one negative per engine-state guard; (e) lease negatives; (f) a RED CONTROL PER GUARD: a mutant of the
     built bytes with only that guard's conditional return removed ACCEPTS that guard's negative vector and
     still refuses every other guard's; (g) adversarial re-entry from a service/menu-shaped stack;
 (h) the stack budget.

Absent input skips (no cached release ROM); present-but-wrong input fails.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "patch" / "tools"))

import build_polished_companion as pc  # noqa: E402
from build_gen2_companion import _symbols  # noqa: E402
from make_ups import ups_apply  # noqa: E402

from tests.unit import polished_sm83 as sm  # noqa: E402

RELEASE = Path(os.environ.get("SLINK_WORK_ROOT", "F:/slink-work")) / "cache/polished/release/polishedcrystal-3.2.3.gbc"
CLEAN_SYM = REPO / "data/polished/polishedcrystal.sym"
OVERLAY_SYM = REPO / "data/polished/polished_slink.sym"
UPS = REPO / "patch/dist/SLink-Polished.ups"
ABI = REPO / "patch/gb/slink_abi.inc"
BANK7E = 0x7E

ENTRY_SP = 0xD000            # the dispatcher's sp+2 (call_routine pushes the 2-byte sentinel below it)
SENT_SP = ENTRY_SP - 2       # the dispatcher's sp at its first instruction
HI = 0xCF80                  # nested (re-entry) stacks live far from the outer one
RSVBK = 0xFF70               # rSVBK = rWBK = $FF70 (constants/hardware.inc:688); asserted against the clean source below

# the nine pinned stack positions (offsets from the dispatcher's sp at entry): the saved bank and four words
PINNED = (5, 12, 13, 14, 15, 24, 25, 26, 27)
NOISE = tuple(p for p in range(2, 44) if p not in PINNED)       # +0..1 is the sentinel the machine itself RETs to


def abi(name: str) -> int:
    """A numeric DEF out of the shared ABI include (a name on the right-hand side resolves recursively)."""
    m = re.search(rf"^DEF {name}\s+EQU\s+([^;\n]+?)\s*(?:;.*)?$", ABI.read_text(), re.M)
    assert m, name
    total = 0
    for term in re.split(r"\s*\+\s*", m.group(1)):
        total += int(term[1:], 16) if term.startswith("$") else int(term) if term.isdigit() else abi(term)
    return total


@pytest.fixture(scope="module")
def clean_rom():
    if not RELEASE.is_file():
        pytest.skip(f"pinned Polished release ROM not cached at {RELEASE}")
    return RELEASE.read_bytes()


@pytest.fixture(scope="module")
def built(clean_rom):
    return ups_apply(clean_rom, UPS.read_bytes())


@pytest.fixture(scope="module")
def nsyms():
    return _symbols(OVERLAY_SYM)


@pytest.fixture(scope="module")
def csyms():
    return _symbols(CLEAN_SYM)


def flat(bank: int, addr: int) -> int:
    return addr if bank == 0 else bank * 0x4000 + addr - 0x4000


class World:
    """Everything the dispatcher reads, derived from the symbol file and the ABI include."""

    def __init__(self, rom: bytes, syms: dict):
        self.rom = rom
        self.syms = syms
        self.entry = syms["SlinkTradeDispatch"][1]
        self.stub = syms["SlinkTradePromptEntry"][1]
        self.end = syms["SlinkTradeDispatchEnd"][1]
        self.code_end = syms["SlinkTradeDispatchCodeEnd"][1]
        a = lambda n: syms[n][1]  # noqa: E731
        self.script_mode, self.battle_mode, self.link_mode = a("wScriptMode"), a("wBattleMode"), a("wLinkMode")
        self.paused, self.map_status, self.map_events = a("wGameLogicPaused"), a("wMapStatus"), a("wMapEventStatus")
        self.step_flags, self.in_menu, self.vblank = a("wPlayerStepFlags"), a("hInMenu"), a("hVBlank")
        self.lease = a("wSlinkMailbox") + abi("SLINK_OFS_TRADE_LEASE")
        self.magic = bytes(abi(f"SLINK_TRADE_MAGIC_{i}") for i in range(4))
        self.version = abi("SLINK_TRADE_VERSION")
        self.prompt = abi("SLINK_TRADE_CMD_PROMPT")
        self.cmd_at, self.gen_at, self.ack_at = self.lease + 5, self.lease + 6, self.lease + 7
        # the pinned values, derived from labels (never typed): +5 bank, +12 DelayFrame+3, +14 gfx_done+6, ...
        bank = syms["NextOverworldFrame"][0]
        word = lambda n, d: (syms[n][1] + d) & 0xFFFF  # noqa: E731
        self.pinned = {5: bank,
                       12: word("DelayFrame", 3) & 0xFF, 13: word("DelayFrame", 3) >> 8,
                       14: word("NextOverworldFrame.gfx_done", 6) & 0xFF, 15: word("NextOverworldFrame.gfx_done", 6) >> 8,
                       24: word("HandleMap", 0x15) & 0xFF, 25: word("HandleMap", 0x15) >> 8,
                       26: word("OverworldLoop.loop", 9) & 0xFF, 27: word("OverworldLoop.loop", 9) >> 8}
        self.bank_nof = bank

    # ---- the synthetic machine state --------------------------------------------------------------------------
    def stack(self, **over) -> dict[int, int]:
        """{position: byte} for positions 2..43: noise everywhere except the nine pinned values."""
        img = {p: (0xA5 ^ (p * 7)) & 0xFF for p in range(2, 44)}
        img.update(self.pinned)
        img[4] = 0x30            # saved F low byte: a plausible register image
        img.update({int(k.lstrip("p")): v for k, v in over.items()})
        return img

    def state(self) -> dict[int, int]:
        """A fully valid machine: engine fields, header, command PROMPT, generation != ack."""
        st = {RSVBK: 1, self.script_mode: 0, self.battle_mode: 0, self.link_mode: 0, self.paused: 0,
              self.in_menu: 0, self.vblank: 0, self.map_status: 2, self.step_flags: 0, self.map_events: 0,
              self.lease + 4: self.version, self.cmd_at: self.prompt, self.gen_at: 5, self.ack_at: 4}
        st.update({self.lease + i: b for i, b in enumerate(self.magic)})
        return st

    def machine(self, rom: bytes | None = None) -> sm.SM83:
        m = sm.SM83(rom if rom is not None else self.rom, BANK7E, mbc="mbc3")
        return m

    def run(self, state: dict | None = None, stack: dict | None = None, *, rom: bytes | None = None,
            de: int = 0x1234, bc: int = 0x5678, hl: int = 0x9ABC, on_entry=None, read_log: list | None = None):
        m = self.machine(rom)
        calls: list[dict] = []

        def hit(mm):
            calls.append({"sp": mm.sp, "de": mm.de, "ret": mm.stack_word(0), "pushed_de": mm.stack_word(2)})
            if on_entry is not None:
                on_entry(mm, calls)

        m.trap(self.stub, hit, bank=BANK7E)
        mem: dict[int, bytes | int] = dict(self.state() if state is None else state)
        for pos, v in (self.stack() if stack is None else stack).items():
            mem[SENT_SP + pos] = v
        if read_log is not None:
            for pos in range(2, 44):
                a = SENT_SP + pos
                m.mem.read_hooks[a] = (lambda mm, addr, pos=pos: read_log.append(pos))
        r = m.call_routine(self.entry, {"de": de, "bc": bc, "hl": hl}, sp=ENTRY_SP, mem=mem, bank=BANK7E)
        return m, r, calls

    def accepted(self, state=None, stack=None, **kw) -> bool:
        _m, r, calls = self.run(state, stack, **kw)
        assert r.sp_delta == 0 and r.returned
        assert len(calls) <= 1
        return bool(calls)


@pytest.fixture(scope="module")
def world(built, nsyms):
    return World(built, nsyms)


# ----------------------------------------------------------------------------------------------------------------
# (0) the built routine equals an independent byte model; every guard's conditional return is located by construction

def lo(x): return x & 0xFF
def hi(x): return (x >> 8) & 0xFF


def model(w: World) -> tuple[bytes, list[tuple[str, int]]]:
    """The routine as the assembler must emit it. Returns (bytes, [(guard name, offset of its conditional return)])."""
    s = w.syms
    out = bytearray()
    guards: list[tuple[str, int]] = []

    def chunk(name, *code, ret):
        out.extend(b"".join(code))
        out.append(ret)
        guards.append((name, len(out) - 1))

    RNZ, RNC, RC, RZ = 0xC0, 0xD0, 0xD8, 0xC8
    ld_hl_sp = lambda n: bytes([0xF8, n])  # noqa: E731
    cp = lambda v: bytes([0xFE, v])  # noqa: E731
    ld_a_nn = lambda addr: bytes([0xFA, lo(addr), hi(addr)])  # noqa: E731
    LDI_A, LD_A_HL = b"\x2a", b"\x7e"
    P = w.pinned
    chunk("p5", ld_hl_sp(5), LD_A_HL, cp(P[5]), ret=RNZ)
    chunk("p12", ld_hl_sp(12), LDI_A, cp(P[12]), ret=RNZ)
    chunk("p13", LD_A_HL, cp(P[13]), ret=RNZ)
    chunk("p14", ld_hl_sp(14), LDI_A, cp(P[14]), ret=RNZ)
    chunk("p15", LD_A_HL, cp(P[15]), ret=RNZ)
    chunk("p24", ld_hl_sp(24), LDI_A, cp(P[24]), ret=RNZ)
    chunk("p25", LDI_A, cp(P[25]), ret=RNZ)
    chunk("p26", LDI_A, cp(P[26]), ret=RNZ)
    chunk("p27", LD_A_HL, cp(P[27]), ret=RNZ)
    chunk("rSVBK", bytes([0xF0, lo(RSVBK)]), b"\xe6\x07", cp(2), ret=RNC)
    for name, addr in (("script_mode", w.script_mode), ("battle_mode", w.battle_mode), ("link_mode", w.link_mode),
                       ("paused", w.paused)):
        chunk(name, ld_a_nn(addr), b"\xa7", ret=RNZ)
    chunk("in_menu", bytes([0xF0, lo(w.in_menu)]), b"\xa7", ret=RNZ)
    chunk("vblank", bytes([0xF0, lo(w.vblank)]), b"\xa7", ret=RNZ)
    chunk("map_status", ld_a_nn(w.map_status), cp(2), ret=RNZ)
    chunk("step_continue", ld_a_nn(w.step_flags), b"\xcb\x6f", ret=RNZ)       # bit 5, a
    chunk("map_events", ld_a_nn(w.map_events), cp(0), ret=RNZ)
    chunk("header", bytes([0xCD, lo(s["SlinkTradeCheckHeader"][1]), hi(s["SlinkTradeCheckHeader"][1])]), ret=RC)
    chunk("command", ld_a_nn(w.cmd_at), cp(w.prompt), ret=RNZ)
    chunk("generation", ld_a_nn(w.gen_at), b"\x47", ld_a_nn(w.ack_at), b"\xb8", ret=RZ)       # ld b,a / cp b
    out.extend(b"\xd5" + bytes([0xCD, lo(w.stub), hi(w.stub)]) + b"\xd1\xc9")                  # push de/call/pop de/ret
    return bytes(out), guards


def test_the_built_routine_is_exactly_the_independent_byte_model(world):
    w = world
    want, guards = model(w)
    got = w.rom[flat(BANK7E, w.entry):flat(BANK7E, w.entry) + len(want)]
    assert got == want, (got.hex(), want.hex())
    assert w.entry + len(want) == w.code_end
    # 22 guards: nine stack bytes, rSVBK, four engine bytes, hInMenu, hVBlank, wMapStatus, step bit, map events,
    # then the lease (header, command, generation)
    assert [g for g, _ in guards][:9] == [f"p{p}" for p in PINNED]
    assert len(guards) == 9 + 1 + 4 + 5 + 3 == 22
    # the stub is a bare ret and nothing else lives in the stub section
    assert w.rom[flat(BANK7E, w.stub):flat(BANK7E, w.end)] == b"\xc9" and w.end == w.stub + 1
    assert w.stub >= w.code_end


def test_the_pinned_values_are_what_the_sources_say(world, built, csyms):
    """The nine bytes follow from labels AND from the instruction bytes at those labels (no pasted address)."""
    w = world
    s = w.syms
    assert w.pinned[5] == 0x25
    assert (w.pinned[13] << 8 | w.pinned[12], w.pinned[15] << 8 | w.pinned[14],
            w.pinned[25] << 8 | w.pinned[24], w.pinned[27] << 8 | w.pinned[26]) == (0x0DAB, 0x51C2, 0x516B, 0x50E2)
    # +6 after .gfx_done is the return of `call z, DelayFrame`: ldh a,[hDelayFrameLY] / and a / call z, DelayFrame
    b, a = s["NextOverworldFrame.gfx_done"]
    o = flat(b, a)
    assert built[o] == 0xF0 and built[o + 2] == 0xA7 and built[o + 3] == 0xCC
    assert int.from_bytes(built[o + 4:o + 6], "little") == s["DelayFrame"][1]
    # HandleMap+$15 follows `call NextOverworldFrame`, OverworldLoop.loop+9 follows a 3-byte call
    b, a = s["HandleMap"]
    assert built[flat(b, a + 0x12)] == 0xCD and int.from_bytes(built[flat(b, a + 0x13):flat(b, a + 0x15)], "little") == s["NextOverworldFrame"][1]
    b, a = s["OverworldLoop.loop"]
    assert built[flat(b, a + 6)] == 0xCD
    # DelayFrame+3: the patched lead-in `call SlinkDelayFrameBridge` is 3 bytes, so the return is DelayFrame+3
    assert built[flat(0, s["DelayFrame"][1])] == 0xCD
    assert int.from_bytes(built[s["DelayFrame"][1] + 1:s["DelayFrame"][1] + 3], "little") == s["SlinkDelayFrameBridge"][1]
    # the clean sym agrees on every native the dispatcher names (the overlay moved none of them)
    for n in ("NextOverworldFrame", "NextOverworldFrame.gfx_done", "HandleMap", "OverworldLoop.loop", "DelayFrame",
              "hVBlank", "hInMenu", "wScriptMode", "wBattleMode", "wLinkMode", "wGameLogicPaused", "wMapStatus",
              "wMapEventStatus", "wPlayerStepFlags"):
        assert csyms[n] == s[n], n
    # the bridge pushes exactly af/bc/hl then the saved bank (ldh a,[hROMBank] / push af) before `call SlinkService`:
    # that is what puts the saved bank at dispatcher +5 and the bridge's own entry at +12 (DEPTH-dependent offsets)
    b, a = s["SlinkDelayFrameBridge"]
    o = flat(b, a)
    hrom = csyms["hROMBank"][1]
    assert built[o + 7:o + 13] == bytes([0xF5, 0xC5, 0xE5, 0xF0, hrom & 0xFF, 0xF5]), built[o + 7:o + 13].hex()
    assert built[o + 13:o + 15] == bytes([0x3E]) + bytes([s["SlinkService"][0]])        # ld a, BANK(SlinkService)
    assert built[o + 15] == 0xCF and built[o + 16] == 0xCD                          # rst Bankswitch / call SlinkService
    assert int.from_bytes(built[o + 17:o + 19], "little") == s["SlinkService"][1]
    assert RSVBK == 0xFF70
    src = Path(os.environ.get("SLINK_WORK_ROOT", "F:/slink-work")) / "cache/polished/src/constants/hardware.inc"
    if src.is_file():
        assert re.search(r"def rWBK equ \$FF70", src.read_text(), re.I)


def test_the_service_calls_the_dispatcher_at_its_own_depth_before_the_sfx_tail_jump(world, built):
    """`call SlinkTradeDispatch` sits right before `jp SlinkSfxService` with the frame-sample store before it."""
    s = world.syms
    end = flat(*s["SlinkServiceEnd"])
    tail = built[end - 6:end]
    call = bytes([0xCD, lo(world.entry), hi(world.entry)])
    jp = bytes([0xC3, lo(s["SlinkSfxService"][1]), hi(s["SlinkSfxService"][1])])
    assert tail == call + jp, tail.hex()
    assert s["SlinkService"][1] == 0x4000
    # behavioural: run the REAL service; at the dispatcher's first instruction sp is exactly the service's entry sp
    # minus its own 2-byte call (nothing pushed before it), and the dispatcher is reached exactly once
    m = world.machine()
    seen: list[int] = []
    m.trap(world.entry, lambda mm: seen.append(mm.sp), bank=BANK7E)
    m.trap(s["SlinkSfxService"][1], lambda mm: seen.append(-1), bank=BANK7E)
    r = m.call_routine(s["SlinkService"][1], {"de": 0x1111}, sp=ENTRY_SP, bank=BANK7E)
    assert seen == [SENT_SP - 2, -1], seen          # dispatcher entered once at sp = entry - 2 (sentinel) - 2 (call)
    assert r.sp_delta == 0 and r.de == 0x1111


# ----------------------------------------------------------------------------------------------------------------
# (a) the positive vector

def test_the_positive_vector_calls_the_entry_once_with_de_preserved_and_writes_nothing_persistent(world):
    w = world
    m, r, calls = w.run(de=0x1234)
    assert len(calls) == 1
    assert calls[0]["de"] == 0x1234                      # DE at the entry stub: untouched going in
    assert calls[0]["pushed_de"] == 0x1234               # push de happened, so the bridge's DE can be restored
    assert r.sp_delta == 0 and r.returned
    assert (r.d, r.e) == (0x12, 0x34)                    # DE restored
    assert not m.rom_writes
    # every write is a stack write BELOW the dispatcher's own entry sp (push de / call): no lease, no WRAM state
    assert r.writes and all(addr < SENT_SP for _pc, addr, _v in r.writes), [(hex(a)) for _p, a, _v in r.writes]
    assert not any(w.lease <= a < w.lease + 16 for _p, a, _v in r.writes)


def test_the_stub_neither_acks_nor_closes_the_lease(world):
    """With the REAL stub (no trap) an accepted frame still leaves every lease byte as published."""
    w = world
    m = w.machine()
    mem = dict(w.state())
    mem.update({SENT_SP + p: v for p, v in w.stack().items()})
    r = m.call_routine(w.entry, {"de": 0x4321}, sp=ENTRY_SP, mem=mem, bank=BANK7E)
    before = bytes(m.peek(w.lease, 16))
    assert r.sp_delta == 0 and r.de == 0x4321
    assert before[4:8] == bytes([w.version, w.prompt, 5, 4])           # version, PROMPT, generation 5, ack 4
    assert all(addr < SENT_SP for _pc, addr, _v in r.writes)


# ----------------------------------------------------------------------------------------------------------------
# (b) nine single-byte stack negatives, (c) noise positives, and the structural mask

STACK_FLIPS = (lambda v: v ^ 0x01, lambda v: v ^ 0x80, lambda v: 0x00 if v else 0xFF)


@pytest.mark.parametrize("pos", PINNED)
@pytest.mark.parametrize("flip", range(3))
def test_each_pinned_stack_byte_alone_invalid_is_refused(world, pos, flip):
    w = world
    bad = STACK_FLIPS[flip](w.pinned[pos]) & 0xFF
    assert bad != w.pinned[pos]
    m, r, calls = w.run(stack=w.stack(**{f"p{pos}": bad}))
    assert calls == [] and r.sp_delta == 0
    assert all(addr < SENT_SP - 4 for _pc, addr, _v in r.writes) or r.writes == []


@pytest.mark.parametrize("pos", NOISE)
@pytest.mark.parametrize("val", (0x00, 0xFF, 0x5A, 0xC3))
def test_every_other_stack_byte_may_hold_anything_and_the_frame_is_still_accepted(world, pos, val):
    assert world.accepted(stack=world.stack(**{f"p{pos}": val}))


def test_the_dispatcher_reads_exactly_the_nine_pinned_stack_bytes(world):
    """The mask is structural: on the accept path the stack bytes it READS (above the return slot) are the nine."""
    w = world
    log: list[int] = []
    _m, r, calls = w.run(read_log=log)
    assert len(calls) == 1
    assert sorted(set(log)) == sorted(PINNED), sorted(set(log))
    # and on a refusal it reads a prefix of them: never anything outside the nine
    log2: list[int] = []
    w.run(stack=w.stack(p14=0), read_log=log2)
    assert set(log2) <= set(PINNED) and 5 in log2 and 14 in log2 and 24 not in log2


def test_the_return_slots_at_plus_0_to_1_are_the_machines_own_return(world):
    """+0..1 is the return into SlinkService: the interpreter faults on any other return, so it is intact (not read)."""
    w = world
    _m, r, _c = w.run()
    assert r.returned and r.pc == sm.SENTINEL


# ----------------------------------------------------------------------------------------------------------------
# (d) engine-state negatives; (e) lease negatives

def engine_vectors(w: World) -> dict[str, list[dict[int, int]]]:
    """guard -> list of states (overrides on the valid state) that violate ONLY that guard."""
    v: dict[str, list[dict[int, int]]] = {}
    v["rSVBK"] = [{RSVBK: x} for x in (2, 3, 4, 5, 6, 7, 0x0A, 0xFA)]
    for name, at in (("script_mode", w.script_mode), ("battle_mode", w.battle_mode), ("link_mode", w.link_mode),
                     ("paused", w.paused), ("in_menu", w.in_menu)):
        v[name] = [{at: x} for x in (1, 0x80, 0xFF)]
    v["vblank"] = [{w.vblank: x} for x in (1, 2, 3, 4, 5, 6, 7, 8, 0x80, 0xFF)]
    v["map_status"] = [{w.map_status: x} for x in range(256) if x != 2]
    v["step_continue"] = [{w.step_flags: x} for x in (0x20, 0xFF, 0x21, 0xE0)]
    v["map_events"] = [{w.map_events: x} for x in (1, 2, 0x80, 0xFF)]
    return v


def lease_vectors(w: World) -> dict[str, list[dict[int, int]]]:
    v: dict[str, list[dict[int, int]]] = {}
    v["header"] = ([{w.lease + i: w.magic[i] ^ x} for i in range(4) for x in (1, 0x80, 0xFF)]
                   + [{w.lease + 4: x} for x in (0, 2, w.version ^ 0x80, 0xFF)])
    v["command"] = [{w.cmd_at: x} for x in range(256) if x != w.prompt]
    gens = [(g, g) for g in range(256)]                                   # generation == ack for every value
    v["generation"] = [{w.gen_at: g, w.ack_at: a} for g, a in gens]
    return v


@pytest.mark.parametrize("name", ("rSVBK", "script_mode", "battle_mode", "link_mode", "paused", "in_menu", "vblank",
                                  "map_status", "step_continue", "map_events"))
def test_each_engine_guard_refuses_its_violation_alone(world, name):
    w = world
    vecs = engine_vectors(w)[name]
    assert vecs
    for over in vecs:
        st = {**w.state(), **over}
        assert not w.accepted(st), (name, {hex(k): v for k, v in over.items()})


def test_the_positive_engine_values_are_accepted(world):
    w = world
    for over in ({RSVBK: 0}, {RSVBK: 1}, {RSVBK: 0xF8}, {RSVBK: 0xF9}, {w.step_flags: 0xDF}, {w.step_flags: 0x00},
                 {w.step_flags: 0x10}, {w.step_flags: 0x40}):
        assert w.accepted({**w.state(), **over}), {hex(k): v for k, v in over.items()}


@pytest.mark.parametrize("name", ("header", "command", "generation"))
def test_each_lease_guard_refuses_its_violation_alone(world, name):
    w = world
    for over in lease_vectors(w)[name]:
        assert not w.accepted({**w.state(), **over}), (name, {hex(k): v for k, v in over.items()})


def test_generation_against_ack_wrap_equalities_and_inequalities(world):
    w = world
    for g, a, ok in ((0xFF, 0x00, True), (0x00, 0xFF, True), (0xFF, 0xFF, False), (0x00, 0x00, False),
                     (0x01, 0x00, True), (0x00, 0x01, True), (0x80, 0x00, True), (0x7F, 0x7F, False)):
        assert w.accepted({**w.state(), w.gen_at: g, w.ack_at: a}) is ok, (g, a)
    for g in range(256):                                              # any unequal pair accepts
        assert w.accepted({**w.state(), w.gen_at: g, w.ack_at: (g + 1) & 0xFF}), g


def test_a_valid_header_with_commands_1_2_5_7_8_is_refused_and_3_is_the_only_accept(world):
    w = world
    got = {c: w.accepted({**w.state(), w.cmd_at: c}) for c in range(256)}
    assert [c for c, ok in got.items() if ok] == [w.prompt]
    assert not got[0] and not got[1] and not got[2] and not got[5] and not got[7] and not got[8]


# ----------------------------------------------------------------------------------------------------------------
# (f) RED CONTROL PER GUARD

def mutant(w: World, offset_of_ret: int) -> bytes:
    """A copy of the built ROM with ONE conditional return (a single opcode byte) turned into a NOP."""
    rom = bytearray(w.rom)
    at = flat(BANK7E, w.entry) + offset_of_ret
    assert rom[at] in (0xC0, 0xD0, 0xD8, 0xC8), hex(rom[at])
    rom[at] = 0x00
    return bytes(rom)


def vector_for(w: World, guard: str):
    """(state, stack) violating ONLY this guard (one representative vector)."""
    if guard[:1] == "p" and guard[1:].isdigit():
        pos = int(guard[1:])
        return w.state(), w.stack(**{f"p{pos}": (w.pinned[pos] ^ 0x01) & 0xFF})
    table = {**engine_vectors(w), **lease_vectors(w)}
    over = table[guard][0]
    if guard == "vblank":
        over = {w.vblank: 3}
    if guard == "generation":
        over = {w.gen_at: 0x42, w.ack_at: 0x42}
    return {**w.state(), **over}, w.stack()


def test_every_guard_has_a_vector_that_the_unmutated_routine_refuses(world):
    w = world
    _want, guards = model(w)
    for name, _off in guards:
        st, stk = vector_for(w, name)
        assert not w.accepted(st, stk), name


def test_a_mutant_without_one_guards_return_accepts_that_guards_vector_and_still_refuses_the_others(world):
    """22 mutants (one per guard: the nine pinned bytes individually, the engine and the lease guards).

    A mutant where only guard G's `ret cc` is a NOP must ACCEPT G's own violation, and must still REFUSE every
    other guard's violation: the mutation removed exactly that guard and nothing else.
    """
    w = world
    _want, guards = model(w)
    vectors = {name: vector_for(w, name) for name, _ in guards}
    caught = 0
    for name, off in guards:
        mrom = mutant(w, off)
        st, stk = vectors[name]
        assert w.accepted(st, stk, rom=mrom), f"mutant of {name} did not accept its own vector"
        for other, (ost, ostk) in vectors.items():
            if other != name:
                assert not w.accepted(ost, ostk, rom=mrom), f"mutant of {name} accepted the vector of {other}"
        caught += 1
    assert caught == 22


@pytest.mark.parametrize("name", ["p5", "p12", "p13", "p14", "p15", "p24", "p25", "p26", "p27"])
def test_each_of_the_nine_stack_guards_is_individually_red(world, name):
    """The saved-bank guard and every pinned word byte: the mutant accepts its violation across all three flips."""
    w = world
    _want, guards = model(w)
    off = dict(guards)[name]
    pos = int(name[1:])
    mrom = mutant(w, off)
    for flip in STACK_FLIPS:
        stk = w.stack(**{f"p{pos}": flip(w.pinned[pos]) & 0xFF})
        assert not w.accepted(stack=stk)
        assert w.accepted(stack=stk, rom=mrom), (name, flip)


def test_removing_a_guard_that_does_not_exist_changes_nothing_a_nop_in_the_stub_is_not_a_guard(world):
    """Control for the control: NOPing a non-guard byte (the final `ret`) is NOT 'accepting the negative'."""
    w = world
    rom = bytearray(w.rom)
    at = flat(BANK7E, w.entry) + (w.code_end - w.entry) - 1
    assert rom[at] == 0xC9
    rom[at] = 0x00                                   # falls off into the stub's `ret`-less neighbour: must fault, not accept
    with pytest.raises(sm.Fault):
        w.run(rom=bytes(rom))


# ----------------------------------------------------------------------------------------------------------------
# (g) adversarial re-entry

def _nest(w: World, shaped: dict[int, int]):
    """A PromptEntry trap that re-invokes the dispatcher on a different stack; records whether THAT accepts."""
    seen: list[str] = []

    def on_entry(mm, calls):
        if len(calls) > 1:                           # the nested invocation reached the stub: it ACCEPTED
            return
        saved = (mm.sp, mm.pc, mm.min_sp, mm.af, mm.bc, mm.de, mm.hl)
        nested_sp = HI
        mem = {nested_sp - 2 + p: v for p, v in shaped.items()}
        r = mm.call_routine(w.entry, {"de": 0x7777}, sp=nested_sp, mem=mem, bank=BANK7E)
        seen.append("accepted" if len(calls) > 1 else "refused")
        assert r.sp_delta == 0
        mm.sp, mm.pc, mm.min_sp = saved[0], saved[1], saved[2]
        mm.af, mm.bc, mm.de, mm.hl = saved[3:]

    return seen, on_entry


def test_reentry_from_a_service_or_menu_shaped_stack_is_not_accepted(world):
    w = world
    svc_bank = w.syms["SlinkService"][0]
    own_wait = w.syms["SlinkTradeEntry"][1]
    shapes = {
        "saved bank is the overlay bank": w.stack(p5=svc_bank),
        "the service's own wait (bank $7E, +14/15 return into the overlay)":
            w.stack(p5=svc_bank, p14=own_wait & 0xFF, p15=own_wait >> 8),
        "a menu: bank $25 but the HandleMap return replaced": w.stack(p24=0x00, p25=0x62),
        "script frames": w.stack(p5=0x24, p25=0x62, p26=0xB5),
    }
    for label, shaped in shapes.items():
        seen, on_entry = _nest(w, shaped)
        m, r, calls = w.run(on_entry=on_entry)
        assert len(calls) == 1, (label, "the nested dispatcher reached the entry stub: re-entry accepted")
        assert seen == ["refused"], (label, seen)
        assert r.sp_delta == 0 and r.de == 0x1234


# ----------------------------------------------------------------------------------------------------------------
# (h) the stack budget

def test_the_stack_budget_of_the_refuse_and_accept_paths(world):
    w = world
    # earliest refusal: nothing is pushed beyond the sentinel/return slot
    _m, r, calls = w.run(stack=w.stack(p5=0x24))
    assert calls == [] and r.stack_used == 2, r.stack_used
    # a late refusal (the lease check) adds one call frame (SlinkTradeCheckHeader pushes nothing itself)
    st = {**w.state(), w.cmd_at: 1}
    _m, r, calls = w.run(st)
    assert calls == [] and r.stack_used == 4, r.stack_used
    # acceptance: the return slot + push de + the call into the entry; the stub's own `ret` adds nothing
    _m, r, calls = w.run()
    assert len(calls) == 1 and r.stack_used == 2 + 2 + 2, r.stack_used
    assert calls[0]["sp"] == SENT_SP - 4
    # the budget the SERVICE pays for the dispatcher on the frame wait: its own 2-byte call + the 4 above
    print(f"dispatcher stack: early refuse {2}, lease refuse {4}, accept {6} (bytes, incl. the 2-byte return slot)")


# ----------------------------------------------------------------------------------------------------------------
# the section does not overlap any existing bank-$7E symbol, and the builder allows exactly its span

def test_the_dispatch_section_overlaps_no_other_bank_7e_symbol_and_fits_its_slots(world, nsyms):
    w = world
    ours = {"SlinkTradeDispatch", "SlinkTradeDispatchCodeEnd", "SlinkTradePromptEntry", "SlinkTradeDispatchEnd"}
    lo_, hi_ = w.entry, w.end
    assert lo_ >= 0x4700 and w.code_end <= 0x4780 and w.stub >= 0x4780 and hi_ <= 0x4800
    others = {n: a for n, (b, a) in nsyms.items() if b == BANK7E and n not in ours}
    assert others
    inside = {n: hex(a) for n, a in others.items() if lo_ <= a <= hi_ and a < w.code_end or w.stub <= a <= hi_}
    assert inside == {}, inside
    below = max(a for n, a in others.items() if a < lo_)
    assert below <= nsyms["SlinkTradeValidateEnd"][1] < lo_, hex(below)
    # nothing else in bank $7E is at or above our start other than ours
    assert [n for n, a in others.items() if a >= lo_] == []


def test_the_builder_allows_the_dispatch_span_and_refuses_one_byte_past_it(world, clean_rom, csyms, nsyms):
    w = world
    pc.verify_overlay(clean_rom, w.rom, csyms, nsyms)                       # the real overlay passes
    last = flat(BANK7E, w.end)
    data = bytearray(w.rom)
    data[last - 1] ^= 0xFF                                                   # the stub's byte: inside the span
    pc.verify_overlay(clean_rom, bytes(data), csyms, nsyms)
    data[flat(BANK7E, w.entry)] ^= 0xFF                                      # the dispatcher's first byte
    pc.verify_overlay(clean_rom, bytes(data), csyms, nsyms)
    data[last] ^= 0xFF                                                       # one past the end: refused
    with pytest.raises(RuntimeError, match=r"unexpected change at"):
        pc.verify_overlay(clean_rom, bytes(data), csyms, nsyms)
