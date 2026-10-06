#!/usr/bin/env python3
"""Read-only Polished rival gate callback-PC probe; authoring does not authorize a live run.

    python tools/polished_live/rival_gate_probe.py --setup played --fixture SAVE --route route.json

The fixture is native SaveRAM. The route starts at emulator boot and must include any
CONTINUE/menu input needed to reach a real trainer battle. No route means bounded idle.
Route JSON: {"steps": [{"frames": 120, "buttons": []}, {"frames": 2, "buttons": ["A"]}]}.
Each step holds exactly those buttons for its frame count; remaining frames are idle.
No SLink client/server, forced battle, WRAM setup, warp, or CPU manipulation is used.
A fresh private lane is staged per invocation; only harness.launch's own PID is killed.
The Lua RESULT certifies recording completion, not the PC finding. The oracle owns that verdict.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WORK = Path("F:/slink-work/lanes/pol-rival-probe")
RELEASE = Path("F:/slink-work/cache/polished/release/polishedcrystal-3.2.3.gbc")
BANK, GATE, NEXT, LAST = 0x0F, 0x47DD, 0x47E0, 0x480D
PINNED_BYTES = bytes.fromhex("218BD2")
BUTTONS = frozenset(("A", "B", "Start", "Select", "Up", "Down", "Left", "Right"))
EXTRA_SYMBOLS = (
    "SendInUserPkmn", "SendInUserPkmn.got_partymon", "wOtherTrainerClass",
    "wOtherTrainerID", "wCurOTMon", "wCurPartyMon", "wOTPartyCount",
)
HOOKS = {"gate": GATE, "next": NEXT, "last": LAST}


def evaluate(trace) -> tuple[bool, list[str]]:
    """PASS requires a complete, uncensored recording and at least one qualified gate hit.

    Wrong-bank callbacks retain only their first 16 rows per site; mandatory totals
    account for every callback without consuming protected trace capacity.
    Wrong-PC rows retain full diagnostics and never count as qualified hits.
    """
    why: list[str] = []
    if not isinstance(trace, list) or any(not isinstance(e, dict) for e in trace):
        return False, ["INVALID_TRACE: expected a list of event objects"]
    finals = [e for e in trace if e.get("kind") == "final"]
    if len(finals) != 1 or trace[-1] is not finals[0] or finals[0].get("completed") is not True:
        why.append("INCOMPLETE_TRACE: missing unique completed final event at end")
    elif finals[0].get("guest_writes") != 0 or finals[0].get("cpu_changes") != 0:
        why.append("PROBE_MUTATION: final write/register-change counters are not zero")
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    from tools.polished_live.faint_probe import validate_hook_counts

    final = finals[0] if len(finals) == 1 else {}
    why.extend(validate_hook_counts(trace, final, {
        name: {"bank": BANK, "addr": addr} for name, addr in HOOKS.items()
    }))
    counts = final.get("hook_counts")
    if isinstance(counts, dict) and set(counts) == set(HOOKS):
        totals = [v.get("total") if isinstance(v, dict) else None for v in counts.values()]
        if (type(final.get("hook_hits")) is not int or any(type(v) is not int for v in totals)
                or final["hook_hits"] != sum(totals)):
            why.append("MALFORMED_TRACE: hook_hits must equal all callback totals")
    if final.get("driver_errors", 0) != 0:
        why.append("DRIVER_ERROR: final driver error counter is not zero")
    qualified_gates = []
    for e in trace:
        kind = e.get("kind")
        if kind in ("guest_write", "cpu_change", "overflow", "driver_error"):
            code = {"guest_write": "GUEST_WRITE", "cpu_change": "CPU_CHANGE",
                    "overflow": "TRACE_OVERFLOW", "driver_error": "DRIVER_ERROR"}[kind]
            why.append(f"{code}: {e}")
        if kind not in HOOKS:
            continue
        addr = HOOKS[kind]
        if e.get("hook_addr") != addr:
            why.append(f"HOOK_ADDRESS: {kind} hook_addr={e.get('hook_addr')!r} != {addr:#06x}")
        matched, bank = e.get("matched"), e.get("bank")
        if type(matched) is not bool or type(bank) is not int or matched != (bank == BANK):
            why.append(f"WRONG_BANK_HIT: {kind} matched={matched!r}, hROMBank={bank!r}")
        if matched is not True or bank != BANK:
            continue
        if kind == "gate":
            if e.get("qualified") is True:
                qualified_gates.append(e)
            if e.get("pc") != GATE:
                code = "PC_IS_NEXT_INSTRUCTION" if e.get("pc") == NEXT else "PC_OTHER"
                pc = e.get("pc")
                observed = f"{pc:#06x}" if type(pc) is int else repr(pc)
                why.append(f"{code}: 0f:47DD callback observed PC={observed}")
            idx, party_idx, count = (e.get(k) for k in ("cur_ot_mon", "cur_party_mon", "ot_party_count"))
            if (any(type(v) is not int for v in (idx, party_idx, count))
                    or not 1 <= count <= 6 or not 0 <= idx < count or idx != party_idx):
                why.append(f"BAD_SELECTED_INDEX: wCurOTMon={idx!r}, wCurPartyMon={party_idx!r}, wOTPartyCount={count!r}")
            if e.get("mode") != 2:
                why.append(f"NOT_TRAINER_BATTLE: wBattleMode={e.get('mode')!r} != 2")
        elif kind == "next" and e.get("pc") != NEXT:
            why.append(f"NEXT_PC_MISMATCH: 0f:47E0 callback observed PC={e.get('pc')!r}")
        elif kind == "last" and e.get("pc") != LAST:
            why.append(f"LAST_PC_MISMATCH: 0f:480D callback observed PC={e.get('pc')!r}")
        site = e.get("site_bytes")
        try:
            observed_bytes = bytes.fromhex(site) if isinstance(site, str) else b""
        except ValueError:
            observed_bytes = b""
        if len(observed_bytes) != 6 or observed_bytes[:3] != PINNED_BYTES:
            why.append(f"SITE_BYTES_MISMATCH: gate ROM bytes={site!r}, expected six bytes beginning 218bd2")
    if not qualified_gates:
        why.append("NO_GATE_HIT: OPEN; no bank-and-PC-qualified 0f:47DD callback (not a PASS)")
    return not why, why


def verdict(reasons: list[str]) -> str:
    """Keep PC findings and zero-hit OPEN distinguishable from generic failures."""
    for code in ("PC_IS_NEXT_INSTRUCTION", "PC_OTHER", "NO_GATE_HIT"):
        if any(r.startswith(code + ":") for r in reasons):
            return code
    return "FAIL" if reasons else "PASS"


def parse_route(path: Path | None, frame_cap: int) -> list[dict]:
    """Validate timed native button holds; reject hidden/synthetic setup fields."""
    if path is None:
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or set(data) != {"steps"} or not isinstance(data["steps"], list):
        raise ValueError("route must be an object containing only a steps list")
    steps, total = [], 0
    for i, step in enumerate(data["steps"]):
        if not isinstance(step, dict) or set(step) != {"frames", "buttons"}:
            raise ValueError(f"route step {i} must contain only frames and buttons")
        frames, buttons = step["frames"], step["buttons"]
        if type(frames) is not int or frames <= 0:
            raise ValueError(f"route step {i} frames must be a positive integer")
        if (not isinstance(buttons, list) or any(not isinstance(b, str) or b not in BUTTONS for b in buttons)
                or len(set(buttons)) != len(buttons)):
            raise ValueError(f"route step {i} buttons must be unique native button names")
        total += frames
        steps.append({"frames": frames, "buttons": buttons})
    if total > frame_cap:
        raise ValueError(f"route needs {total} frames, exceeds --frames {frame_cap}")
    return steps


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--setup", choices=("played",), required=True)
    ap.add_argument("--fixture", type=Path, required=True, help="native SaveRAM, copied unchanged")
    ap.add_argument("--route", type=Path, help="timed native input from emulator boot; optional for idle observation")
    ap.add_argument("--frames", type=int, default=12000, help="total observation frames, including route")
    ap.add_argument("--trace-cap", type=int, default=4096, help="maximum bank-matched hook rows; overflow fails the oracle")
    ap.add_argument("--timeout", type=int, default=600, help="wall-clock deadline in seconds")
    args = ap.parse_args(argv)
    for name in ("frames", "trace_cap", "timeout"):
        if getattr(args, name) <= 0:
            ap.error(f"--{name.replace('_', '-')} must be positive")
    if not args.fixture.is_file():
        ap.error(f"fixture does not exist: {args.fixture}")
    try:
        args.steps = parse_route(args.route, args.frames)
    except (OSError, ValueError) as exc:
        ap.error(str(exc))
    return args


def check_site_bytes(rom: bytes) -> str:
    """Pure prelaunch check of the pinned bank's instruction, plus six bytes for evidence."""
    offset = BANK * 0x4000 + GATE - 0x4000
    site = rom[offset:offset + 6]
    if len(site) != 6 or site[:3] != PINNED_BYTES:
        raise ValueError(f"staged 0f:47DD ROM bytes {site.hex()} != pinned prefix 218bd2 (six bytes required)")
    return site.hex()


def check_pack_facts() -> None:
    """Refuse drift between this bounded probe, checkpoint, engine sites and overlay symbols."""
    pack = REPO / "data/games/polished_crystal"
    checkpoint = json.loads((pack / "write_checkpoint.json").read_text(encoding="utf-8"))
    signals = json.loads((pack / "engine_signals.json").read_text(encoding="utf-8"))
    gate = checkpoint["titles"]["polished_crystal"]["battle_hold"]["rival_swap_gate"]
    sites = signals["titles"]["polished_crystal"]["sites"]
    signal, last = sites["rival_swap_gate"], sites["rival_swap_last_consumption"]
    offset = BANK * 0x4000 + GATE - 0x4000
    if ((gate["bank"], gate["pc"], gate["rom_offset"]) != (BANK, GATE, offset)
            or (signal["bank"], signal["addr"], signal["symbol_offset"], signal["expected_hex"].upper())
            != (BANK, GATE, 149, "218BD2")
            or (last["bank"], last["addr"], last["symbol_offset"]) != (BANK, LAST, 197)):
        raise ValueError("pinned rival gate/last-consumption pack facts differ from this probe")
    symbols = {}
    for line in (REPO / "data/polished/polished_slink.sym").read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) == 2 and ":" in parts[0]:
            symbols.setdefault(parts[1], tuple(int(v, 16) for v in parts[0].split(":")))
    if (symbols.get("SendInUserPkmn") != (BANK, GATE - 149)
            or symbols.get("SendInUserPkmn.got_partymon") != (BANK, NEXT)
            or symbols.get("hROMBank") != (0, 0xFF87)):
        raise ValueError("pinned SendInUserPkmn/next/hROMBank symbols differ from this probe")


def stage(lane: Path) -> tuple[Path, str, str]:
    check_pack_facts()
    provenance = json.loads((REPO / "data/polished/overlay_provenance.json").read_text(encoding="utf-8"))
    clean = RELEASE.read_bytes()
    if hashlib.sha1(clean).hexdigest() != provenance["base_sha1"]:
        raise ValueError("release ROM sha1 differs from provenance base_sha1")
    sys.path.insert(0, str(REPO))
    from patch.tools.make_ups import ups_apply

    data = ups_apply(clean, (REPO / "patch/dist/SLink-Polished.ups").read_bytes())
    sha1 = hashlib.sha1(data).hexdigest()
    if sha1 != provenance["output"]["sha1"]:
        raise ValueError(f"staged overlay sha1 {sha1} differs from provenance output.sha1")
    site = check_site_bytes(data)
    rom = lane / "rom/pol_overlay.gbc"  # harness SAVE_NAME is pol overlay.SaveRAM
    rom.parent.mkdir(parents=True)
    rom.write_bytes(data)
    return rom, sha1, site


def recording_reasons(text: str, elapsed: float = 0, timeout: float = float("inf")) -> list[str]:
    """Missing RESULT, early exit/crash/deadline, and driver failure are never evidence of success."""
    reasons = []
    results = [line for line in text.splitlines() if line.startswith("RESULT:")]
    if len(results) != 1 or not results[0].startswith("RESULT: PASS rival-gate-probe recording "):
        reasons.append("INCOMPLETE_RECORDING: missing unique successful driver RESULT (early exit, deadline or crash)")
    if elapsed >= timeout:
        reasons.append(f"DEADLINE: launch/recording took {elapsed:.3f}s >= {timeout}s; late RESULT is not accepted")
    return reasons


def main(argv=None) -> int:
    args = parse_args(argv)
    WORK.mkdir(parents=True, exist_ok=True)
    lane = Path(tempfile.mkdtemp(prefix="played-", dir=WORK))
    rom, sha1, site = stage(lane)
    os.environ.update(POL_LANE=str(lane), POL_KIND="overlay", POL_FIXTURE=str(args.fixture.resolve()))
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import harness

    harness.SYMBOLS = tuple(harness.SYMBOLS) + tuple(s for s in EXTRA_SYMBOLS if s not in harness.SYMBOLS)
    harness.ROM_SRC = harness.ROM = rom
    harness.SRAM.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(args.fixture, harness.SRAM / harness.SAVE_NAME)
    fixture_digest = hashlib.sha256(args.fixture.read_bytes()).hexdigest()
    run = lane / "probe"
    run.mkdir()
    config = run / "input.json"
    config.write_text(json.dumps({"steps": args.steps, "frames": args.frames, "trace_cap": args.trace_cap}), encoding="utf-8")
    header = [f"[probe] setup played; no synthetic guest setup; fixture {args.fixture} sha256 {fixture_digest}",
              f"[probe] overlay sha1 {sha1}; gate 0f:47DD ROM bytes {site}",
              f"[probe] native route {args.route}; canonical input {config}; frames {args.frames}; cap {args.trace_cap}"]
    print("\n".join(header), flush=True)
    started = time.monotonic()
    text, pid = harness.launch("tools/polished_live/rival_gate_probe.lua", run,
                               {"POL_PROBE_CONFIG": config.as_posix()}, args.timeout)
    # Conservative: include harness shutdown/flush time rather than accepting a RESULT seen after its deadline.
    reasons = recording_reasons(text, time.monotonic() - started, args.timeout)
    try:
        trace = json.loads((run / "trace.json").read_text(encoding="utf-8"))
        _, oracle_reasons = evaluate(trace)
        reasons.extend(oracle_reasons)
    except (OSError, ValueError) as exc:
        reasons.append(f"INVALID_TRACE: {exc}")
    finding = verdict(reasons)
    rows = header + [f"  [FAIL] {r}" for r in reasons]
    rows.append(f"RESULT: {finding} rival-gate-probe (played, EmuHawk pid {pid}, {len(reasons)} reasons)")
    with (run / "result.txt").open("a", encoding="utf-8") as fh:
        fh.write("\n" + "\n".join(rows) + "\n")
    print("\n".join(rows))
    print(f"[probe] evidence {run / 'trace.json'}; result {run / 'result.txt'}")
    return 0 if not reasons else 1


if __name__ == "__main__":
    raise SystemExit(main())
