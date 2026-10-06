#!/usr/bin/env python3
"""Serverless single-EmuHawk held-service probe (Polished TRADE.md sections 15-17).

SYNTH: event flag + engine warp to POKECENTER_2F (5,3). TEST HOST: lease-only
QUERY/OFFER replies; APPLY stages a COPY of own mon 0 with a distinct OT name,
ONLY in OT slot 0 plus sender. No cable partner, server, SLink client or commit.
The pure oracle consumes ordered byte writes, not just final mailbox snapshots.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WORK = Path("F:/slink-work/lanes/pol-service-probe")
RELEASE = Path("F:/slink-work/cache/polished/release/polishedcrystal-3.2.3.gbc")
FIXTURE = Path("F:/slink-work/lanes/g2int-live/pol/fixture/polished_overlay_warp.SaveRAM")
FIXTURE_SHA256_PREFIX = "75c7a5dc"
CASES = ("offer-reject", "cancel-menu", "no-eligible", "query-timeout", "apply-done1", "apply-invalid")
TOKEN = [0x54, 0x45, 0x53, 0x54]
MAGIC = [0x53, 0x4C, 0x54, 0x31, 1]
HOOKS = ("SlinkTradeEntry", "SlinkTradeClose", "SlinkTradeCheckHeader", "Script_endtext", "GetScriptByte",
         "SelectTradeOrDayCareMon", "NoYesBox", "SlinkTradeTimeoutGate")
EXTRA_SYMBOLS = HOOKS + ("wPartyMon1", "wOTPartyMon1", "wOTPartyMonOTs", "wOTPartyMonNicknames", "wOTPlayerName",
                         "hScriptBank", "hScriptPos", "hVBlank", "wScriptStackSize")
SYNTH = ("SYNTH event flag wEventFlags+4 |= $02 + engine warp POKECENTER_2F (20:1) (5,3); "
         "TEST HOST copies own mon 0 to OT slot 0 with distinct OT name and sender for APPLY; "
         "no cable partner, server, SLink client, or native commit")


def _bytes(value):
    return isinstance(value, list) and len(value) == 16 and all(type(v) is int and 0 <= v <= 255 for v in value)


def _checksum(data):
    value = 0x811C9DC5
    for byte in data:
        value = ((value ^ byte) * 0x01000193) & 0xFFFFFFFF
    return f"{value:08x}"


def _header(frame, command):
    return frame[:5] == MAGIC and frame[5] == command


def _events(trace, kind):
    return [e for e in trace if e.get("kind") == kind]


def _once(trace, kind, why):
    events = _events(trace, kind)
    if len(events) != 1:
        why.append(f"{kind}: expected exactly once, observed {len(events)}")
        return None
    return events[0]


def _check_staging(trace, why):
    staged = _once(trace, "staged", why)
    writes = _events(trace, "host_stage_write")
    expected = [(name, i) for name, length in (("wOTPartyMon1", 48), ("wOTPartyMonOTs", 11),
                                             ("wOTPartyMonNicknames", 11), ("wOTPlayerName", 11))
                for i in range(length)]
    if [(e.get("symbol"), e.get("offset")) for e in writes] != expected:
        why.append("staging escaped OT slot 0/sender or omitted bytes")
    if not staged:
        return None
    try:
        pieces = {key: bytes.fromhex(staged[key]) for key in
                  ("record", "ot", "nick", "sender", "source_record", "source_ot", "source_nick")}
    except (KeyError, ValueError, TypeError):
        why.append("staging copy evidence missing or malformed")
        return staged
    if any(len(pieces[k]) != n for k, n in (("record", 48), ("source_record", 48), ("ot", 11),
                                          ("source_ot", 11), ("nick", 11), ("source_nick", 11), ("sender", 11))):
        why.append("staging copy evidence has wrong lengths")
        return staged
    if pieces["record"] != pieces["source_record"]:
        why.append("incoming record is not a COPY of own mon 0")
    if pieces["ot"][:8] == pieces["source_ot"][:8] or pieces["ot"][8:] != pieces["source_ot"][8:]:
        why.append("staged OT name not distinct or OT metadata changed")
    if pieces["sender"][:8] != pieces["ot"][:8]:
        why.append("staged sender differs from incoming OT name")
    for field, limit in (("ot", 8), ("sender", 11), ("nick", 11)):
        data = pieces[field][:limit]
        valid = 0x53 in data and all(v >= 0x5F for v in data[:data.index(0x53)])
        if field == "nick" and staged.get("invalid"):
            if 0x53 in data:
                why.append("apply-invalid incoming name still has a terminator")
        elif not valid:
            why.append(f"staged {field} has no valid name terminator")
    if not staged.get("invalid") and pieces["nick"] != pieces["source_nick"]:
        why.append("incoming nickname is not copied from own mon 0")
    payload = pieces["record"] + pieces["ot"] + pieces["nick"]
    if _checksum(payload) != staged.get("staged_sum"):
        why.append("staged payload checksum evidence disagrees")
    expected_values = list(pieces["record"] + pieces["ot"] + pieces["nick"] + pieces["sender"])
    if [e.get("value") for e in writes] != expected_values:
        why.append("staging byte writes disagree with disclosed payload")
    return staged


def _write_audit(trace, why):
    """Check continuous before/after images and each publisher's actual store order.

    Host transaction boundaries are frame-end observations. ROM QUERY/OFFER publish
    at generation, DONE at ACK; APPLY pickup's ACK is distinct from DONE publication.
    """
    publications, host_transactions = [], []
    active, host_writes, rom_pending, previous = None, [], [], None
    last_host_frame = None
    rom_waiting_for_host = None
    for e in trace:
        kind = e["kind"]
        frame = e["lease"]
        if previous is not None and frame != previous and kind not in ("rom_write", "host_write"):
            why.append("lease changed without an ordered write observation")
        if kind == "host_begin":
            if active is not None:
                why.append("nested host transaction")
            active, host_writes = e, []
            tx = e.get("tx")
            if e.get("pump") != "onframeend":
                why.append("host transaction did not originate in frame-end pump")
            allowed = ((tx == "query" and _header(frame, 1) and frame[6] != frame[7]) or
                       (tx == "offer" and _header(frame, 2) and frame[6] != frame[7]) or
                       (tx == "apply" and _header(frame, 2) and frame[6] == frame[7] and frame[8] == 0) or
                       (tx == "release" and _header(frame, 7) and frame[6] == frame[7] and frame[8] == 1))
            if not allowed:
                why.append(f"host wrote while ROM-owned ({tx})")
            if e["frame"] == last_host_frame:
                why.append("host pumped more than once in one emulator frame")
            last_host_frame = e["frame"]
        elif kind == "host_stage_write":
            if not active or active.get("tx") != "apply" or host_writes:
                why.append("host staging outside APPLY ownership or after frame publication began")
        elif kind in ("host_write", "rom_write"):
            offset, value, before = e.get("offset"), e.get("value"), e.get("before")
            if type(offset) is not int or not 0 <= offset < 16 or type(value) is not int or not 0 <= value < 256 or not _bytes(before):
                why.append("malformed lease write evidence")
                continue
            after = list(before)
            after[offset] = value
            if after != frame or (previous is not None and before != previous):
                why.append("lease write before/after chain broken")
            if kind == "host_write":
                if not active or e.get("tx") != active.get("tx"):
                    why.append("host write outside frame-end transaction")
                host_writes.append(e)
            else:
                if active:
                    why.append("ROM write interleaved with host transaction")
                if rom_waiting_for_host and not (offset == 5 and value == 0):
                    why.append("ROM payload written after generation/ACK publication")
                rom_pending.append(e)
                cmd = frame[5]
                if offset == 6 and cmd in (1, 2) and frame[6] != frame[7]:
                    needed = {0, 1, 2, 3, 4, 5, 7, 10, 11} if cmd == 1 else {5, 7, 8, 9}
                    if not needed <= {w["offset"] for w in rom_pending[:-1]}:
                        why.append("ROM generation written before payload (publication must be last)")
                    if frame[6] != (before[6] + 1) % 256 or frame[7] != before[6]:
                        why.append("ROM publication generation/ACK mismatch")
                    if not _header(frame, cmd):
                        why.append("ROM publication has invalid lease header")
                    if cmd == 2 and (frame[9] != 0 or frame[12:16] != TOKEN or frame[8] != 255):
                        why.append("OFFER chosen slot/token/result mismatch")
                    publications.append(("query" if cmd == 1 else "offer", e))
                    rom_pending = []
                    rom_waiting_for_host = cmd
                elif offset == 7 and cmd == 7 and frame[6] == frame[7]:
                    needed = {0, 1, 2, 3, 4, 5, 6, 8, 9, 12, 13, 14, 15}
                    if not needed <= {w["offset"] for w in rom_pending[:-1]}:
                        why.append("ROM DONE ACK written before payload (publication must be last)")
                    if not _header(frame, 7) or frame[12:16] != TOKEN or frame[9] != 0:
                        why.append("DONE slot/token/header mismatch")
                    publications.append(("done", e))
                    rom_pending = []
                    rom_waiting_for_host = cmd
                elif offset == 5 and value == 0:
                    publications.append(("closed", e))
                    rom_waiting_for_host = None
        elif kind == "host_end":
            if not active or e.get("tx") != active.get("tx"):
                why.append("unmatched host transaction end")
            else:
                tx, start = active["tx"], active["lease"]
                expected = {"query": [10, 11, 12, 13, 14, 15, 7], "offer": [8, 7],
                            "apply": [*range(16), 6], "release": [5]}.get(tx)
                if [w.get("offset") for w in host_writes] != expected:
                    why.append(f"host {tx} generation/ACK written before payload or write sequence incomplete")
                if tx == "query" and (frame[10] != 1 or frame[11] not in (0, 1) or frame[12:16] != TOKEN or frame[7] != start[6]):
                    why.append("QUERY answer available/mask/token/ACK mismatch")
                if tx == "offer" and (frame[8] not in (0, 1) or frame[7] != start[6]):
                    why.append("OFFER answer result/ACK mismatch")
                if tx == "apply":
                    expected_frame = MAGIC + [5, (start[6] + 1) % 256, start[6], 255, 0, 1, 0] + TOKEN
                    if frame != expected_frame:
                        why.append("APPLY generation/ACK/slot/token/frame mismatch")
                    unpublished = MAGIC + [5, start[6], start[6], 255, 0, 1, 0] + TOKEN
                    if [w["value"] for w in host_writes[:-1]] != unpublished:
                        why.append("host APPLY exposed generation before complete payload")
                if tx == "release" and (frame[5] != 8 or frame[:5] + frame[6:] != start[:5] + start[6:]):
                    why.append("RELEASE changed fields other than command")
                host_transactions.append((tx, active, e))
                rom_waiting_for_host = None
            active, host_writes = None, []
        previous = frame
    if active:
        why.append("unfinished host transaction")
    return publications, host_transactions


def evaluate(case, trace) -> tuple[bool, list[str]]:
    """Fail closed on incomplete instrumentation, invalid protocol, or non-restored machine state."""
    why: list[str] = []
    if case not in CASES:
        return False, [f"unknown case {case}"]
    if not isinstance(trace, list) or not trace or any(not isinstance(e, dict) for e in trace):
        return False, ["missing/malformed ordered trace"]
    required = ("kind", "ord", "frame", "sp", "bank", "vblank", "link", "running", "stack", "count",
                "party_sum", "ot_tail_sum", "ot0_sum", "ot1_sum", "own0_sum", "lease", "sbank", "spos", "x", "y")
    if any(any(k not in e for k in required) or not _bytes(e.get("lease")) for e in trace):
        return False, ["missing snapshot fields or malformed 16-byte lease"]
    if any(type(e[k]) is not int for e in trace for k in
           ("ord", "frame", "sp", "bank", "vblank", "link", "running", "stack", "count", "sbank", "spos", "x", "y")):
        return False, ["malformed numeric snapshot fields"]
    if [e["ord"] for e in trace] != list(range(1, len(trace) + 1)) or any(a["frame"] > b["frame"] for a, b in zip(trace, trace[1:], strict=False)):
        why.append("trace order is not continuous/monotonic")
    if any(not isinstance(e[k], str) or not re.fullmatch(r"[0-9a-f]{8}", e[k]) for e in trace
           for k in ("party_sum", "ot_tail_sum", "ot0_sum", "ot1_sum", "own0_sum")):
        why.append("checksum evidence missing/malformed")
    for kind in ("missing_symbol", "gsb_overflow", "driver_error", "instrumentation_error", "deadline", "early_exit"):
        if _events(trace, kind):
            why.append(f"{kind}: observation incomplete")
    setup, entry, close, ret, endtext, final, m0, m1, complete = (
        _once(trace, k, why) for k in ("setup", "service_entry", "close", "service_return", "endtext", "final",
                                      "move_start", "move_end", "complete"))
    chain = [e for e in (setup, entry, close, ret, endtext, final, m0, m1, complete) if e]
    if any(a["ord"] >= b["ord"] for a, b in zip(chain, chain[1:], strict=False)):
        why.append("service/closure/endtext/movement events out of order")
    if setup and (setup.get("case") != case or setup.get("synth") is not True or setup.get("token") != TOKEN):
        why.append("missing SYNTH/test-token setup disclosure")
    if complete and (complete.get("case") != case or complete is not trace[-1]):
        why.append("early exit: complete must be the final event for this case")
    if entry and (entry["bank"] != 0x7E or entry.get("pc") != 0x4480):
        why.append("service entry is not bank-qualified 7e:4480")
    if entry and ret and (ret.get("ret_sp") != entry["sp"] or ret["sp"] != entry["sp"] + 2):
        why.append("return SP != entry SP (RET boundary / CALL continuation unbalanced)")
    if endtext and (endtext["sbank"], endtext["spos"], endtext["bank"]) != (0x2D, 0x7596, 0x25):
        why.append("Script_endtext did not use the endtext redirect")
    redirects = [e for e in _events(trace, "gsb") if (e["sbank"], e["spos"]) == (0x2D, 0x7595)]
    if len(redirects) != 1 or not ret or not endtext or not ret["ord"] < redirects[0]["ord"] < endtext["ord"]:
        why.append("missing ordered interpreter endtext redirect read")
    if final:
        if final["lease"][5] != 0:
            why.append("lease not closed (command != 0)")
        for key in ("vblank", "link", "running", "stack"):
            if final[key] != 0:
                why.append(f"final {key} != 0")
    if m0 and m1 and (m0["x"], m0["y"]) == (m1["x"], m1["y"]):
        why.append("player did not move")
    if entry:
        for e in trace[entry["ord"] - 1:]:
            if (e["party_sum"], e["count"]) != (entry["party_sum"], entry["count"]):
                why.append("party/OT/nickname checksum changed (or party count changed)")
                break
        if any(e["ot_tail_sum"] != entry["ot_tail_sum"] for e in trace[entry["ord"] - 1:]):
            why.append("OT slots 2..5 checksum changed; only slot 1 snapshot and slot 0 staging allowed")
    if any(e["lease"][5] == 7 and e["lease"][8] == 0 for e in trace):
        why.append("DONE result 0 observed: commit must remain disabled")
    if case != "apply-done1" and any(e["lease"][5] == 7 for e in trace):
        why.append("unexpected DONE on rejection/cancel/invalid/timeout path")
    if case in ("cancel-menu", "no-eligible", "query-timeout") and any(e["lease"][5] == 2 for e in trace):
        why.append("unexpected OFFER on cancel/ineligible/timeout path")
    pubs, txs = _write_audit(trace, why)
    expected_pubs = {
        "offer-reject": ["query", "offer", "closed"], "cancel-menu": ["query", "closed"],
        "no-eligible": ["query", "closed"], "query-timeout": ["query", "closed"],
        "apply-done1": ["query", "offer", "done", "closed"], "apply-invalid": ["query", "offer", "closed"],
    }[case]
    if [p[0] for p in pubs] != expected_pubs:
        why.append(f"ROM publication order: expected {expected_pubs}, observed {[p[0] for p in pubs]}")
    expected_txs = {"offer-reject": ["query", "offer"], "cancel-menu": ["query"], "no-eligible": ["query"],
                    "query-timeout": [], "apply-done1": ["query", "offer", "apply", "release"],
                    "apply-invalid": ["query", "offer", "apply"]}[case]
    if [t[0] for t in txs] != expected_txs:
        why.append(f"host transaction order: expected {expected_txs}, observed {[t[0] for t in txs]}")
    for name, begin, end in txs:
        if name == "query" and end["lease"][11] != (0 if case == "no-eligible" else 1):
            why.append("QUERY eligibility mask incorrect for case")
        if name == "offer" and end["lease"][8] != (1 if case == "offer-reject" else 0):
            why.append("OFFER decision incorrect for case")
        if entry and ret and not entry["ord"] < begin["ord"] < end["ord"] < ret["ord"]:
            why.append("host transaction outside held service")
    menus = _events(trace, "party_menu")
    want_menu = case not in ("no-eligible", "query-timeout")
    if len(menus) != int(want_menu):
        why.append(f"party menu: expected {int(want_menu)}, observed {len(menus)}")
    if want_menu:
        query_end = next((t[2] for t in txs if t[0] == "query"), None)
        if menus and (not query_end or menus[0]["ord"] <= query_end["ord"]):
            why.append("party menu opened before QUERY answer")
        answers = [e for e in _events(trace, "answer") if e.get("which") == "party"]
        if len(answers) != 1 or answers[0].get("btn") != ("B" if case == "cancel-menu" else "A"):
            why.append("native party menu answer missing/incorrect")
        if answers and menus and answers[0]["ord"] <= menus[0]["ord"]:
            why.append("native party input preceded menu milestone")
    if case in ("offer-reject", "apply-done1", "apply-invalid"):
        confirms = [e for e in _events(trace, "answer") if e.get("which") == "confirm" and e.get("btn") == "A"]
        offers = [p[1] for p in pubs if p[0] == "offer"]
        if len(confirms) != 1 or not offers or confirms[0]["ord"] >= offers[0]["ord"]:
            why.append("OFFER without prior native YES confirmation")
        if entry and final and final["ot1_sum"] != entry["own0_sum"]:
            why.append("OT slot 1 snapshot does not match selected own mon 0")
    elif entry and final and final["ot1_sum"] != entry["ot1_sum"]:
        why.append("OT slot 1 changed without an OFFER snapshot")
    if case.startswith("apply-"):
        staged = _check_staging(trace, why)
        if staged and staged.get("invalid") != (case == "apply-invalid"):
            why.append("staging validity disclosure incorrect for case")
        if final and staged and final["ot0_sum"] != staged.get("staged_sum"):
            why.append("staged OT slot 0 changed after staging")
        apply_end = next((t[2] for t in txs if t[0] == "apply"), None)
        pickups = [e for e in _events(trace, "rom_write") if e.get("offset") == 7 and e["lease"][5] == 5]
        if len(pickups) != 1 or not apply_end or pickups[0]["ord"] <= apply_end["ord"] or pickups[0]["lease"][7] != apply_end["lease"][6]:
            why.append("missing matching APPLY pickup ACK")
        dones = [p[1] for p in pubs if p[0] == "done"]
        if case == "apply-done1" and (len(dones) != 1 or not apply_end or dones[0]["lease"][8] != 1 or
                                       dones[0]["lease"][6] != apply_end["lease"][6]):
            why.append("APPLY must publish matching DONE result 1, never success")
    else:
        if _events(trace, "host_stage_write") or _events(trace, "staged"):
            why.append("unexpected incoming staging")
        if entry and final and final["ot0_sum"] != entry["ot0_sum"]:
            why.append("OT slot 0 changed without host staging")
    if case == "query-timeout":
        query = next((p[1] for p in pubs if p[0] == "query"), None)
        closed = next((p[1] for p in pubs if p[0] == "closed"), None)
        if not query or not closed or not 600 <= closed["frame"] - query["frame"] <= 700:
            why.append("QUERY timeout did not wait 600 frames within 700-frame budget")
    return not why, list(dict.fromkeys(why))


def read_provenance(path):
    provenance = json.loads(Path(path).read_text(encoding="utf-8"))
    for digest in (provenance.get("base_sha1"), provenance.get("output", {}).get("sha1")):
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-fA-F]{40}", digest):
            raise ValueError("provenance must contain base_sha1 and output.sha1 (40 hex digits)")
    return provenance["base_sha1"].lower(), provenance["output"]["sha1"].lower()


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--case", choices=CASES, required=True)
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    return args


def plan(args, repo=REPO, work=WORK):
    base_sha1, overlay_sha1 = read_provenance(repo / "data/polished/overlay_provenance.json")
    return {"case": args.case, "timeout": args.timeout, "lane": str(work / args.case),
            "driver": str(repo / "tools/polished_live/trade_service_probe.lua"),
            "release": str(RELEASE), "fixture": str(FIXTURE), "base_sha1": base_sha1,
            "expected_overlay_sha1": overlay_sha1, "disclosure": SYNTH,
            "service_budget_frames": 700 if args.case == "query-timeout" else 2400,
            "cleanup": "harness.launch finally kills only its own EmuHawk PID"}


def read_symbols(path):
    rows = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) == 2 and re.fullmatch(r"[0-9a-fA-F]+:[0-9a-fA-F]+", parts[0]):
            bank, addr = parts[0].split(":")
            rows.setdefault(parts[1], [int(bank, 16), int(addr, 16)])
    return rows


def stage(lane, run_plan):
    clean = RELEASE.read_bytes()
    if hashlib.sha1(clean).hexdigest() != run_plan["base_sha1"]:
        raise ValueError("release sha1 differs from provenance base_sha1")
    sys.path.insert(0, str(REPO))
    from patch.tools.make_ups import ups_apply

    overlay = ups_apply(clean, (REPO / "patch/dist/SLink-Polished.ups").read_bytes())
    sha1 = hashlib.sha1(overlay).hexdigest()
    if sha1 != run_plan["expected_overlay_sha1"]:
        raise ValueError("overlay sha1 differs from provenance output.sha1")
    rom = lane / "rom/pol_overlay.gbc"
    rom.parent.mkdir(parents=True, exist_ok=True)
    rom.write_bytes(overlay)
    return rom, sha1


def main(argv=None):
    args = parse_args(argv)
    run_plan = plan(args)
    print(json.dumps(run_plan, indent=2), flush=True)
    if args.dry_run:
        return 0
    lane = WORK / args.case
    if WORK.resolve() not in lane.resolve().parents:
        raise ValueError(f"refusing lane outside {WORK}: {lane}")
    if lane.exists():
        shutil.rmtree(lane)
    lane.mkdir(parents=True)
    os.environ.update(POL_LANE=str(lane), POL_KIND="overlay", POL_FIXTURE=str(FIXTURE))
    # Load a private harness instance: its environment-derived paths must belong to this lane.
    spec = importlib.util.spec_from_file_location("polished_service_probe_harness", REPO / "tools/polished_live/harness.py")
    harness = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(harness)
    rows = read_symbols(REPO / "data/polished/polished_slink.sym")
    # Optional code hooks are omitted from syms.json when absent; Lua records missing_symbol, oracle FAILS.
    required = tuple(harness.SYMBOLS) + tuple(s for s in EXTRA_SYMBOLS if s not in HOOKS)
    missing = sorted(set(required) - rows.keys())
    if missing:
        raise ValueError(f"required data/setup symbols missing: {missing}")
    harness.SYMBOLS = tuple(dict.fromkeys((*required, *(s for s in HOOKS if s in rows))))
    rom, sha1 = stage(lane, run_plan)
    harness.ROM_SRC = harness.ROM = rom
    digest = hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
    if not digest.startswith(FIXTURE_SHA256_PREFIX):
        raise ValueError("fixture sha256 differs from qualified fixture")
    harness.SRAM.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(FIXTURE, harness.SRAM / harness.SAVE_NAME)
    run = lane / "probe"
    text, pid = harness.launch("tools/polished_live/trade_service_probe.lua", run, {"POL_CASE": args.case}, args.timeout)
    reasons = []
    if not any(line.startswith("RESULT: PASS trade-service-probe") for line in text.splitlines()):
        reasons.append("driver failed or exited early/deadline/crash (missing PASS completion)")
    path = run / "trace.json"
    try:
        trace = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        reasons.append(f"trace unavailable: {exc}")
    else:
        _, failures = evaluate(args.case, trace)
        reasons.extend(failures)
        print("\n".join(f"#{e.get('ord')} f{e.get('frame')} {e.get('kind')} lease={e.get('lease')}"
                        for e in trace if e.get("kind") != "gsb"))
    result = {**run_plan, "staged_sha1": sha1, "fixture_sha256": digest, "emuhawk_pid": pid,
              "ok": not reasons, "reasons": reasons}
    (run / "oracle.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 1 if reasons else 0


if __name__ == "__main__":
    raise SystemExit(main())
