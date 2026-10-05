#!/usr/bin/env python3
"""server/adapters/polished_trade_fingerprint.py — the Polished trade DISPATCH-ENTRY gate, as a
pure predicate. No ROM bytes are written and no overlay source is touched: this is the decision
half of `SlinkTradeDispatch`, and the card that turns it into asm is a different one.

WHY A PREDICATE AND NOT ASM
    `patch/gen2/src/trade_dispatch.asm` refuses a frame by reading `sp+N` and WRAM. Reading those
    from Lua or Python is not a weakening if the same bytes are checked in the same order with the
    same constants: the engine is the same engine. What a predicate buys is that the constants are
    resolved from the committed symbol file and unit-tested against a real measurement, so a moved
    label fails here instead of silently comparing a dispatcher against the wrong address.

WHAT IT ACCEPTS, AND WHY THAT IS ALL IT ACCEPTS
    Exactly one stack: the idle overworld's own frame wait, measured live (see below). The stage B
    run sampled `SlinkDelayFrameBridge` (ROM0 $0070) ENTRY; `SlinkTradeDispatch` runs three frames
    further in, so the window the dispatcher reads is NOT the one that was sampled. The offset is
    arithmetic, not a guess, and it lives in exactly one function here (`dispatch_view`):

        at bridge entry sp = B, and $0DAB (the return into DelayFrame+3) sits at B+0;
        the bridge pushes af(hROMBank), hl, bc, af(xor a)           -> B-8   (slink.asm:41-45)
        rst Bankswitch                                             -> no change
        call SlinkService                                          -> B-10
        SlinkService runs straight-line (no pushes, no early ret)
        call SlinkTradeDispatch                                    -> B-12

    so `dispatch sp == bridge sp - 12`, i.e. `dispatch sp + 12 + k == bridge sp + k`.

THE MEASUREMENT (tests/fixtures/polished/explore_B_stacks.json, sha256 pinned by the test)
    overlay 34942315bb3e62189a56dabbcb9cef6dd3e9a9f5, Pokemon Center 2F, 937 samples over 181
    distinct stacks. The nine pinned bytes are constant in the two overworld phases (300 + 61
    samples) and every expected value re-derives from data/polished/polished_slink.sym:

        sp+12-13  LOW/HIGH(DelayFrame + 3)                    00:0da8 + 3   -> ab 0d
        sp+14-15  LOW/HIGH(NextOverworldFrame.gfx_done + 6)   25:51bc + 6   -> c2 51
        sp+24-25  LOW/HIGH(HandleMap + $15)                   25:5156 + $15 -> 6b 51
        sp+26-27  LOW/HIGH(OverworldLoop.loop + 9)            25:50d9 + 9   -> e2 50
        sp+5      hROMBank == BANK(NextOverworldFrame)                      -> 25

WHY THE ENGINE STATE IS THE GATE, NOT A SECONDARY CHECK
    Four measured samples carry a stack BYTE-IDENTICAL to the accept case and must still be
    refused: `talk` x3 and `after_wait` x1, all SP $C0DE, hROMBank $25, bytes
    ab0dc25100fe86d6444622d16b51e2501400018a611400120f00584314000177 — the same 32 bytes the
    idle overworld carries 297 times. No choice of pinned positions can separate them, because
    there is nothing left to separate. The WRAM refusals are therefore the ONLY discriminator for
    those four samples, and `accepts()` evaluates both halves before it says yes.

DISCLOSED GAP
    The lane recorded stack bytes, bank and SVBK only — its `stacks.json` has exactly six keys and
    none of them is engine state, and `result.txt` never logs any of the eight WRAM symbols. The
    WRAM values the test supplies are therefore INFERRED, not measured, and the inference is
    stated per vector in tests/unit/test_polished_trade_fp.py. The one that carries the talk case
    is `wPlayerStepFlags` bit PLAYERSTEP_CONTINUE_F: the talk frame is the A press that STARTS the
    receptionist script, so wScriptMode and wMapStatus are still idle there and vanilla's own
    reason for that bit (patch/gen2/src/trade_dispatch.asm:55-60) is the only one that applies.
    Until a probe logs those eight bytes per frame, the engine half is a hypothesis with a test.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SYM_PATH = ROOT / "data" / "polished" / "polished_slink.sym"
# The pinned checkout, quoted where the value is not a symbol. Both from
# F:/slink-work/lanes/pol-trade2/cache/polished/src/constants/ram_constants.asm at the commit in
# data/polished_sources.lock.json (:173 and :209). They are NOT labels in the .sym — a grep for
# them as sym names returns zero — so they cannot be resolved the way the addresses below are.
PLAYERSTEP_CONTINUE_F = 5
MAPSTATUS_HANDLE = 2
MAPEVENTS_ON = 0

# dispatch-entry byte positions this gate pins. sp+5 is hROMBank; the rest are bridge-entry words
# shifted by FRAME_DEPTH.
FRAME_DEPTH = 12
PINNED_POSITIONS = (5, 12, 13, 14, 15, 24, 25, 26, 27)
# Positions deliberately NOT pinned: the game's own registers, in DISPATCH-entry terms. At
# bridge-entry depth they are sp+4..11 — the four AF/BC/HL pushes — so at dispatch depth they are
# sp+16..23. Stage B and Stage 4 both record sp+4 and sp+8..9 varying between runs and between
# fixtures; pinning them pins a register.
NOISE_POSITIONS = tuple(range(16, 24))

# label, offset added, position it fills, and how the value reads. The offset is what the caller's
# `call` instruction contributes: a 3-byte `call z` pushes the address 3 past the `call`, and the
# symbol sits at the byte before the instruction.
_SYMBOL_SPECS = (
    ("NextOverworldFrame", 0, 5, "BANK(NextOverworldFrame)"),
    ("DelayFrame", 3, 12, "LOW/HIGH(DelayFrame + 3)"),
    ("NextOverworldFrame.gfx_done", 6, 14, "LOW/HIGH(NextOverworldFrame.gfx_done + 6)"),
    ("HandleMap", 0x15, 24, "LOW/HIGH(HandleMap + $15)"),
    ("OverworldLoop.loop", 9, 26, "LOW/HIGH(OverworldLoop.loop + 9)"),
)
_LABEL = re.compile(r"^([0-9a-f]{2}):([0-9a-f]{4})\s+(\S+)$")


@dataclass(frozen=True)
class Verdict:
    """Why the gate said what it said. `stage` is which half refused, or None on accept."""

    accepted: bool
    stage: str | None
    reason: str
    position: int | None = None

    def __bool__(self) -> bool:
        return self.accepted



def load_symbols(sym_path: Path = SYM_PATH) -> dict[str, tuple[int, int]]:
    """Every `bb:aaaa name` in the overlay .sym, CRLF/LF agnostic. Fails closed on a missing file."""
    try:
        text = sym_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"cannot read {sym_path}: {exc}") from exc
    out: dict[str, tuple[int, int]] = {}
    for line in text.splitlines():
        m = _LABEL.match(line)
        if m:
            out.setdefault(m.group(3), (int(m.group(1), 16), int(m.group(2), 16)))
    if not out:
        raise ValueError(f"{sym_path} yielded no symbols: refusing to guess addresses")
    return out




def expected_positions(sym_path: Path = SYM_PATH) -> dict[int, int]:
    """The nine expected dispatch-entry bytes, resolved from the committed .sym.

    A label that moved, or a rename, raises here — at import, in a test — instead of leaving a
    dispatcher comparing a live stack against a constant pasted from an old build.
    """
    syms = load_symbols(sym_path)
    out: dict[int, int] = {}
    for label, offset, position, how in _SYMBOL_SPECS:
        if label not in syms:
            raise ValueError(f"{how}: {label!r} is not in {sym_path.name}")
        bank, addr = syms[label]
        if position == 5:
            out[5] = bank                      # sp+5 is the BANK byte, not an address
            continue
        value = (addr + offset) & 0xFFFF
        out[position] = value & 0xFF                  # LOW
        out[position + 1] = (value >> 8) & 0xFF        # HIGH
    missing = [p for p in PINNED_POSITIONS if p not in out]
    if missing:
        raise ValueError(f"{sym_path.name} left positions unresolved: {missing}")
    return out


def dispatch_view(bridge_bytes: bytes | str, rombank: int | str) -> dict[int, int]:
    """ONE place the frame depth lives: bridge-entry sp+0..31 -> dispatch-entry sp+12..43, with
    hROMBank at sp+5. Every caller goes through this; nothing else may shift."""
    raw = bytes.fromhex(bridge_bytes) if isinstance(bridge_bytes, str) else bytes(bridge_bytes)
    if len(raw) != 32:
        raise ValueError(f"bridge sample is {len(raw)} bytes, expected 32")
    view = {index + FRAME_DEPTH: byte for index, byte in enumerate(raw)}
    view[5] = int(str(rombank), 16) if isinstance(rombank, str) else int(rombank)
    return view


def stack_fingerprint_ok(view: dict[int, int],
                         expected: dict[int, int] | None = None) -> Verdict:
    """The nine pinned bytes, bank first. sp+5 rejects script ($24) and the link wait ($0A) on its
    own, which is three of the five measured phases before any deeper comparison."""
    want = expected_positions() if expected is None else expected
    for position in PINNED_POSITIONS:
        if position not in view:
            return Verdict(False, "stack", f"dispatch sp+{position} is not in the sample", position)
        got = view[position]
        if got != want[position]:
            return Verdict(False, "stack",
                           f"dispatch sp+{position} is ${got:02x}, expected ${want[position]:02x}",
                           position)
    return Verdict(True, None, "stack fingerprint matches the idle overworld")


# The eight WRAM refusals, in patch/gen2/src/trade_dispatch.asm's order (:34-63). A nonzero value
# refuses; `expect` is the one value that ACCEPTS.
ENGINE_REFUSALS = (
    ("wScriptMode", 0), ("wBattleMode", 0), ("wLinkMode", 0), ("wGameLogicPaused", 0),
    ("hInMenu", 0), ("wMapStatus", MAPSTATUS_HANDLE), ("wMapEventStatus", MAPEVENTS_ON),
)
# A separate shape: a BIT that must be CLEAR, not a value that must match.
ENGINE_CLEAR_BITS = (("wPlayerStepFlags", PLAYERSTEP_CONTINUE_F),)
ENGINE_KEYS = tuple(name for name, _ in ENGINE_REFUSALS) + tuple(n for n, _ in ENGINE_CLEAR_BITS)


def engine_state_ok(engine: dict[str, int]) -> Verdict:
    """Every refusal the vanilla dispatcher makes, minus the two that are Gen 2 specific: `hVBlank`
    is a 0-7 mode selector in Polished, not a flag (TRADE.md 10.7, engine/link/link.asm:2276-2278),
    so its check is `cp 0` rather than `and a`; and the SVBK window has no recorded Polished
    evidence, so it is NOT here. Both are omissions, not grants — the gate is already fail-closed
    because a missing key refuses."""
    for key in ENGINE_KEYS:
        if key not in engine:
            return Verdict(False, "engine", f"{key} is not in the snapshot: refusing")
    for name, expected in ENGINE_REFUSALS:
        got = int(engine[name])
        if got != expected:
            return Verdict(False, "engine",
                           f"{name} is ${got:02x}, expected ${expected:02x} for a safe frame")
    for name, bit in ENGINE_CLEAR_BITS:
        got = int(engine[name])
        if got & (1 << bit):
            return Verdict(False, "engine",
                           f"{name} bit {bit} (PLAYERSTEP_CONTINUE_F) is set: this frame adds no "
                           f"step vector, so opening a prompt would reanchor the background")
    return Verdict(True, None, "engine state is a safe idle overworld frame")


def accepts(snapshot: dict, expected: dict[int, int] | None = None) -> Verdict:
    """The whole gate. `snapshot` needs `stack_view` (from `dispatch_view`) and `engine`.

    Both halves run before the answer is yes, and the stack half runs first because it is the cheap
    one and it is what rejects the service's own frames: a frame inside `SlinkTradeWaitFrame` runs
    with hROMBank = $7E, so it fails sp+5 twice over.
    """
    view = snapshot.get("stack_view")
    if view is None:
        return Verdict(False, "stack", "no stack_view in the snapshot: refusing")
    verdict = stack_fingerprint_ok(view, expected)
    if not verdict.accepted:
        return verdict
    engine = snapshot.get("engine")
    if engine is None:
        return Verdict(False, "engine", "no engine block in the snapshot: refusing")
    return engine_state_ok(engine)


def snapshot_from_probe(sample: dict, engine: dict[str, int]) -> dict:
    """A raw lane record (`{bytes, rombank, ...}`) plus an engine block -> a snapshot."""
    return {"stack_view": dispatch_view(sample["bytes"], sample["rombank"]),
            "engine": dict(engine), "phase": sample.get("phase")}


__all__ = [
    "FRAME_DEPTH", "PINNED_POSITIONS", "NOISE_POSITIONS", "ENGINE_KEYS", "ENGINE_REFUSALS",
    "ENGINE_CLEAR_BITS", "PLAYERSTEP_CONTINUE_F", "MAPSTATUS_HANDLE", "MAPEVENTS_ON",
    "Verdict", "accepts", "dispatch_view", "engine_state_ok", "expected_positions",
    "load_symbols", "snapshot_from_probe", "stack_fingerprint_ok",
]
