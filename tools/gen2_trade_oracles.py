"""Independent saved-byte oracles for the HARNESS_ONLY_OVERLAY trade lanes.

Markers are singleton ``TAG {json}`` lines, except TRADE_NATIVE_CALL (ordered).
No client PASS flag is evidence. Image markers bind full SaveRAM and CartRAM
hashes. Overlay inputs bind actual ROM/symbol files; server inputs bind an
immutable pre-trade links image and a captured trade_done event journal.

The contract is intentionally fail-closed while reset-after-commit reconciliation
is unspecified. MODEL fixtures exercise these checks; they are not PHYSICAL runs.

v1 wire keys (all frames are observed emulator frames):
* RECEIPT: schema, player, title, case, run_id, rom_sha1, fixture_sha256,
  admission_scope=HARNESS_ONLY_OVERLAY, role, token[4], generation. Optional
  visit_state defaults to accepted; query is early D3 only; none requires null
  token/generation and forbids OFFER, PICKUP, DONE, native calls and controls.
* TRADE_BASELINE/TRADE_NATIVE_SAVE/TRADE_FINAL: frame, snapshot_path,
  snapshot_sha256, cartram_sha256, snapshot_bytes=32790, cartram_bytes=32768.
  BASELINE also has party=[{species_marker,blob_hex}], dex={primary,backup},
  each dex copy containing caught_hex/seen_hex (32 bytes each).
* TRADE_READY: frame, snapshot_sha256; TRADE_GO: frame, run_id.
* TRADE_OFFER: frame, token, generation, slot, count, species_marker, blob_hex.
* TRADE_APPLY_PICKUP: frame, lease_hex, incoming_blob_hex, incoming_species_marker.
* TRADE_PRE_REMOVE: frame, site, live/frozen={domain:'System Bus',bank:1,
  spans:[{address,hex} x3]}; actual records/OT/nicknames, 48+11+11 bytes.
* TRADE_NATIVE_CALL: frame, symbol, bank, address; TRADE_DONE: frame, lease_hex.
* TRADE_STACK: domain, stack_bank/start/end(inclusive), armed_count, hook_failures,
  global_observations>0, global_low_water={frame,stack_addr,sp,pc,rom_bank},
  continuous=true, registration_complete_before_first_phase=true,
  coverage_started/coverage_ended={frame,site}, registration_events=[
  {action:'arm',address,frame,hook_id} for every unique stack address]. The
  inventory includes all registration changes through coverage end; any
  disarm/rearm/failure, duplicate handle/address or late registration refuses.
  phases=[{phase,visited,start,end,samples}]. start/end={frame,site};
  site={symbol,bank,address}; samples={frame,stack_addr,sp,pc,rom_bank}.
  Phase order: wait, trade_animation, evolution_animation, native_save.
* TRADE_CONTROL: kind, before/after={frame,site,registers,lease_hex}; D3 before
  also records selected slot. Decline uses A=1 at PublishDone; timeout uses BC
  SLINK_TRADE_APPLY_FRAMES (trade_service.asm, 3600 since 67143736) at WaitApply.wait
  then BC=0 at Exit after >= that many frames; reset observes
  Reset then StartTitleScreen/zero lease; D3 observes ItemAllowed's real item A.

transaction_evidence: schema=gen2-duo-trade-transaction-v1, tokens={a,b},
server_token, baseline_links/events={path,sha256}. Events are server_dispatch
JSONL records from the harness server wrapper, not reconstructed client TX.
The early-negative null server token requires no dispatched offer/request/done.
"""
from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from enum import StrEnum
from functools import wraps
from pathlib import Path

from server.adapters import gen2_codec as codec
from tools.gen2_duo_oracles import normalized_gameplay_cartram
from tools.rgbds_symbols import parse_symbols, rom_offset

ROOT = Path(__file__).resolve().parents[1]
CART = 0x8000
CASES = frozenset(("gen2_trade_new", "gen2_trade_decline_new", "gen2_trade_timeout",
                   "gen2_trade_reset_wait", "gen2_trade_reset_commit", "gen2_trade_refuse_item",
                   "gen2_trade_evolve", "gen2_trade_refuse_contest", "gen2_trade_refuse_unsaved"))
# MODEL-only refusal rows (TRADE-ASM 9805ac1c refusal-site contract): no driver yet, so they are NOT in
# tools/gen2_trade_lane.py SCENARIOS and validate_manifest refuses them until a lane admits them.
#   contest: the responder's SlinkTradeCheckOwnSlot.refuseParty with wStatusFlags2 bit 2
#            (STATUSFLAGS2_BUG_CONTEST_TIMER_F) -> SlinkTradeExit; the PROMPT lease is never answered.
#   unsaved: SlinkTradeResponderSave ran, then the decline path (PublishDone A=1 -> Exit, DONE result 1).
COMMITTED = frozenset(("gen2_trade_new", "gen2_trade_evolve"))
# O-31 (docs/gen2/REVIEW_RECORD.md): the ONLY disclosed harness writes, proposer side a only.
PLANTS = {"gen2_trade_refuse_item": "d3_mail_item", "gen2_trade_evolve": "trade_evolve_species"}
SIDES = ("a", "b")
PHASES = ("wait", "trade_animation", "evolution_animation", "native_save")
CALLS = ("RemoveMonFromPartyOrBox", "AddTempmonToParty", "EvolvePokemon", "SaveAfterLinkTrade")
REGIONS = {"player": "wPlayerData", "player1": "wPlayerData1", "player2": "wPlayerData2",
           "player3": "wPlayerData3", "map": "wCurMapData", "pokemon": "wPokemonData"}
# server/state.py _save payload and _commit_trade: only links transition durably.
# party_keys changes in memory, but is NOT serialized at this source cut.
# Subsequent party snapshots may refresh the derived mon_stats cache.
STABLE_SERVER_FIELDS = frozenset(("game_id", "rules", "area_states", "pending_captures",
    "pokeballs_obtained", "rom_type", "artifact_kind", "trainer_names", "player_identity",
    "pending_memorials", "retry_areas", "bonus_keys", "pending_bonus", "run_over",
    "attempts_count", "rebuild_pending"))
# TRADE-HARDEN 7de364f0 (review B1): the durable trade FSM. pending_trade must be settled (null) in
# both the pre-visit baseline and the final document; trade_token is a counter that only goes up.
TRADE_SERVER_FIELDS = frozenset(("pending_trade", "trade_token"))


class TradeStatus(StrEnum):
    COMMITTED = "committed"
    UNCHANGED = "unchanged"
    UNCERTAIN = "uncertain"
    ROLLED_BACK = "rolled_back"


class TradeUncertain(RuntimeError):
    """A refusal with an explicit status, never a successful reconciliation receipt."""
    status = TradeStatus.UNCERTAIN

    def __init__(self, scenario, reason):
        self.facts = {"scenario": scenario, "status": self.status.value,
                      "admission_scope": "HARNESS_ONLY_OVERLAY", "reason": reason}
        super().__init__(f"trade: UNCERTAIN: {reason}")


def _need(ok, reason):
    if not ok:
        raise RuntimeError(f"trade: {reason}")


def _refusals(function):
    @wraps(function)
    def checked(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except (KeyError, TypeError, ValueError, OSError, IndexError, AttributeError) as exc:
            raise RuntimeError(f"trade: malformed or unavailable evidence: {exc}") from exc
    return checked


def _object(value, label):
    _need(isinstance(value, dict), f"{label} must be an object")
    return value


def _integer(value, low, high, label):
    _need(type(value) is int and low <= value <= high, f"invalid {label}")
    return value


def _unique(pairs):
    result = {}
    for key, value in pairs:
        _need(key not in result, f"duplicate JSON key {key}")
        result[key] = value
    return result


def _json(raw, label):
    try:
        return json.loads(raw, object_pairs_hook=_unique)
    except (ValueError, TypeError) as exc:
        raise RuntimeError(f"trade: malformed {label}") from exc


def _markers(text, tag):
    _need(isinstance(text, str), "result text is missing")
    return [_object(_json(line[len(tag) + 1:], tag), tag)
            for line in text.splitlines() if line.startswith(tag + " ")]


def _one(text, tag):
    found = _markers(text, tag)
    _need(len(found) == 1, f"{tag} requires exactly one marker")
    return found[0]


def _hex(value, size, label):
    _need(isinstance(value, str) and len(value) == size * 2, f"invalid {label} byte length")
    try:
        raw = bytes.fromhex(value)
    except ValueError as exc:
        raise RuntimeError(f"trade: invalid {label} hex") from exc
    _need(len(raw) == size, f"invalid {label} byte length")
    return raw


def _token(value):
    _need(isinstance(value, list) and len(value) == 4, "visit token needs four bytes")
    for byte in value:
        _integer(byte, 0, 255, "token byte")
    _need(any(value), "zero visit token")
    return value


def _frame(marker):
    return _integer(marker.get("frame"), 0, 2**53, "frame")


def _register(registers, name):
    registers = _object(registers, "native registers")
    if name == "BC":
        return (_integer(registers.get("B"), 0, 255, "B") << 8) | _integer(registers.get("C"), 0, 255, "C")
    return _integer(registers.get(name), 0, 255, name)


def _read(path, label):
    _need(isinstance(path, (str, Path)) and Path(path).is_absolute(), f"{label} requires absolute path")
    try:
        return Path(path).read_bytes()
    except OSError as exc:
        raise RuntimeError(f"trade: unreadable {label}") from exc


def _digest(raw, claimed, algorithm="sha256"):
    _need(isinstance(claimed, str) and hashlib.new(algorithm, raw).hexdigest() == claimed,
          f"{algorithm} digest mismatch")


def _image(marker, label):
    _frame(marker)
    _need(marker.get("snapshot_bytes") == CART + 22 and marker.get("cartram_bytes") == CART,
          f"{label} image geometry mismatch")
    raw = _read(marker.get("snapshot_path"), label)
    _need(len(raw) == CART + 22, f"{label} requires complete SaveRAM including RTC trailer")
    _digest(raw, marker.get("snapshot_sha256"))
    _digest(raw[:CART], marker.get("cartram_sha256"))
    return raw


def _reference(ref, label):
    ref = _object(ref, label)
    raw = _read(ref.get("path"), label)
    _digest(raw, ref.get("sha256"))
    return _json(raw, label)


def _saved(raw, layout, symbol, count, copy_name):
    address = layout.addresses[symbol]
    for region in layout.regions:
        base = layout.addresses[REGIONS[region.name]]
        if base <= address and address + count <= base + region.length:
            offset = getattr(region, copy_name) + address - base
            return raw[offset:offset + count]
    raise RuntimeError(f"trade: saved symbol outside all regions: {symbol}")


def _party(raw, layout, copy_name="primary"):
    party = codec.decode_saved_party(raw[:CART], layout, copy_name=copy_name)
    return [{"species_marker": mon["species_marker"], "blob_hex": codec.encode_party_blob(mon, layout).hex()}
            for mon in party["mons"]]


def _dex(raw, layout):
    return {copy: {kind + "_hex": _saved(raw, layout, symbol, 32, copy).hex()
                   for kind, symbol in (("caught", "wPokedexCaught"), ("seen", "wPokedexSeen"))}
            for copy in ("primary", "backup")}


def _overlay(ref, receipt):
    ref = _object(ref, "overlay provenance")
    _need(ref.get("title") == receipt["title"], "overlay title mismatch")
    rom = _read(ref.get("rom_path"), "overlay ROM")
    _digest(rom, ref.get("rom_sha1"), "sha1")
    _need(receipt.get("rom_sha1") == ref["rom_sha1"], "receipt is not bound to actual overlay")
    raw = _read(ref.get("sym_path"), "overlay symbols")
    _digest(raw, ref.get("sym_sha256"))
    symbols = parse_symbols(raw.decode("utf-8"))
    for name in ("SlinkTradeApplyPickup", "SlinkTradeCommit", "wStackBottom", "wStackTop", *CALLS):
        _need(name in symbols, f"overlay lacks required symbol {name}")
    return rom, symbols


def _site(marker, symbols, name=None):
    marker = _object(marker, "site")
    name = name or marker.get("symbol")
    _need(name in symbols, f"unknown observed site {name}")
    sym = symbols[name]
    _need(marker.get("symbol") == name and type(marker.get("bank")) is int and marker.get("bank") == sym.bank
          and marker.get("address") == sym.address, f"wrong observation site {name}")


def _spans(record, symbols, names, slot, expected, label):
    record = _object(record, label)
    _need(record.get("domain") == "System Bus" and type(record.get("bank")) is int and record.get("bank") == 1,
          f"{label} domain/bank mismatch")
    spans = record.get("spans")
    _need(isinstance(spans, list) and len(spans) == 3, f"{label} requires three spans")
    data = bytearray()
    for span, name, size in zip(spans, names, (48, 11, 11), strict=True):
        span = _object(span, label)
        symbol = symbols[name]
        _need(symbol.bank == 1 and span.get("address") == symbol.address + slot * size,
              f"{label} span address mismatch")
        data += _hex(span.get("hex"), size, label)
    _need(bytes(data) == expected, f"{label} differs from immutable offer")


def _lease(marker, token, generation, slot, command, *, picked_up=False):
    raw = _hex(marker.get("lease_hex"), 16, "lease")
    _need(raw[:5] == b"SLT1\x01" and raw[5] == command, "invalid lease header/command")
    ack = generation if picked_up else (generation - 1) % 256
    _need(raw[6] == generation and raw[7] == ack and raw[9] == slot
          and list(raw[12:]) == token, "lease token/generation/slot mismatch")
    if command == 7:
        _need(raw[8] == 0, "DONE is not successful native commit")


def _stack_sample(sample, rom, bottom, top, first, last):
    sample = _object(sample, "stack sample")
    _need(first <= _frame(sample) <= last, "stack sample outside observed coverage boundaries")
    sp = _integer(sample.get("sp"), bottom, top + 1, "sample SP")
    address = _integer(sample.get("stack_addr"), bottom, top, "stack write address")
    _need(sp - 2 <= address <= sp + 1, "stack write unrelated to observed SP")
    margin = min(address, sp) - bottom
    _need(margin >= 32, "stack safety margin below 32 bytes")
    pc = _integer(sample.get("pc"), 0, 0x7FFF, "stack callback PC")
    bank = _integer(sample.get("rom_bank"), 0, 0xFFFF, "stack callback ROM bank")
    _need(rom_offset(bank, pc) < len(rom), "stack callback outside overlay ROM")
    return margin


def _stack(marker, rom, symbols, *, committed, evolved=None, visit=True, partial_phases=None):
    """Bus-write observations with full stack-span registration, never frame-only SP."""
    bottom, top = symbols["wStackBottom"].address, symbols["wStackTop"].address
    _need(marker.get("domain") == "System Bus" and marker.get("stack_start") == bottom
          and marker.get("stack_end") == top and marker.get("stack_bank") == symbols["wStackBottom"].bank
          and marker.get("armed_count") == top - bottom + 1
          and type(marker.get("hook_failures")) is int and marker["hook_failures"] == 0,
          "incomplete stack bus-write coverage")
    _need(marker.get("continuous") is True and marker.get("registration_complete_before_first_phase") is True,
          "stack coverage was not declared continuous before phase entry")
    started = _object(marker.get("coverage_started"), "stack coverage start")
    ended = _object(marker.get("coverage_ended"), "stack coverage end")
    first_covered, last_covered = _frame(started), _frame(ended)
    _need(started.get("site") == "harness:trade_go"
          and ended.get("site") == "harness:before_report", "unknown stack harness coverage boundary")
    _need(first_covered <= last_covered, "reversed stack coverage boundaries")
    events = marker.get("registration_events")
    _need(isinstance(events, list) and len(events) == top - bottom + 1, "stack registration inventory incomplete/rearmed")
    addresses, handles, previous_frame = set(), set(), -1
    for event in events:
        event = _object(event, "stack registration event")
        frame = _frame(event)
        _need(event.get("action") == "arm", "stack coverage contains a disarm/rearm/failure gap")
        address = _integer(event.get("address"), bottom, top, "stack hook address")
        handle = event.get("hook_id")
        _need(isinstance(handle, str) and handle and handle not in handles and address not in addresses,
              "duplicate/missing stack hook registration")
        _need(previous_frame <= frame <= first_covered, "stack registration occurred after coverage began")
        previous_frame = frame
        addresses.add(address)
        handles.add(handle)
    _need(addresses == set(range(bottom, top + 1)), "stack address coverage has a hole")
    # The instrumented driver updates this on EVERY qualifying bus-write callback,
    # including gaps between named phases. Samples are minimum witnesses, not a
    # claimed complete trace; registration inventory and driver controls remain required.
    observed = _integer(marker.get("global_observations"), 1, 2**53, "global stack observation count")
    global_margin = _stack_sample(marker.get("global_low_water"), rom, bottom, top, first_covered, last_covered)
    rows = marker.get("phases")
    _need(isinstance(rows, list) and len(rows) == 4, "stack phase coverage incomplete")
    _need([row.get("phase") for row in rows if isinstance(row, dict)] == list(PHASES),
          "stack phases missing, duplicate or reordered")
    coverage = {"global": {"margin": global_margin, "observations": observed}}
    sample_count = 0
    for row in rows:
        phase, visited, samples = row["phase"], row.get("visited"), row.get("samples")
        _need(type(visited) is bool and isinstance(samples, list), "invalid stack coverage record")
        _need(bool(samples) == visited, "stack visitation/sample mismatch")
        required = phase == "wait" and visit or committed and phase in ("trade_animation", "native_save")
        if partial_phases is not None:
            required = phase in partial_phases
        _need(visit or not visited, "unvisited peer claims a native stack phase")
        if phase == "evolution_animation" and evolved is not None:
            _need(visited == evolved, "evolution animation coverage disagrees with projection")
        _need(not required or visited, f"unvisited required stack phase {phase}")
        _need(partial_phases is not None or committed or phase == "wait" or not visited,
              "negative case entered native commit phase")
        minima = []
        if visited:
            start, end = _object(row.get("start"), "phase start"), _object(row.get("end"), "phase end")
            first, last = _frame(start), _frame(end)
            _need(last >= first, "stack phase boundaries reversed")
            _need(first_covered <= first <= last <= last_covered, "stack coverage begins late or ends before phase completion")
            _site(start.get("site"), symbols)
            _site(end.get("site"), symbols)
        for sample in samples:
            margin = _stack_sample(sample, rom, bottom, top, first, last)
            _need(global_margin <= margin, "global stack minimum contradicts a phase witness")
            minima.append(margin)
            sample_count += 1
        coverage[phase] = {"visited": visited, "margin": min(minima) if minima else None,
                           "completed": visited and row["end"]["site"]["symbol"] != "Reset"}
    _need(observed >= sample_count, "global stack observation count is smaller than phase samples")
    return coverage


@_refusals
def check_trade_witness(results, *, expected_case=None, overlay_provenance=None):
    """Validate immutable image bindings and mandatory phase markers before PYDEC.

    The runner supplies actual overlay files when available. Full semantic,
    projection and server checks remain mandatory in ``trade_oracle``.
    """
    _need(isinstance(results, dict) and set(results) == set(SIDES), "both side results required")
    if isinstance(expected_case, dict):
        expected_case = expected_case.get("scenario")
    for side in SIDES:
        text = results[side]
        receipt = _one(text, "RECEIPT")
        case = receipt.get("case")
        _need(case in CASES and (expected_case is None or case == expected_case), "wrong trade case")
        _need(receipt.get("schema") == "gen2-duo-trade-v1" and receipt.get("player") == side
              and receipt.get("title") in ("crystal", "gold", "silver")
              and receipt.get("admission_scope") == "HARNESS_ONLY_OVERLAY", "invalid trade receipt provenance")
        state = receipt.get("visit_state", "accepted")
        _need(state in ("accepted", "query", "none", "unentered"), "invalid visit state")
        _need(case not in COMMITTED or state == "accepted", "committed trade requires accepted visits")
        _need(state != "unentered" or case == "gen2_trade_reset_commit", "unentered exception is reset_commit only")
        _need(state != "query" or case == "gen2_trade_refuse_item", "query-only visit is limited to early D3 refusal")
        if state == "none":
            _need(receipt.get("token") is None and receipt.get("generation") is None, "inactive peer fabricated a visit")
        else:
            _token(receipt.get("token"))
            _integer(receipt.get("generation"), 0, 255, "accepted generation")
        _integer(receipt.get("role"), 0, 1, "native role")
        baseline, final = _one(text, "TRADE_BASELINE"), _one(text, "TRADE_FINAL")
        _image(baseline, "baseline")
        _image(final, "final flushed save")
        _need(_frame(final) > _frame(baseline), "final image predates baseline")
        _need(Path(baseline["snapshot_path"]).resolve() != Path(final["snapshot_path"]).resolve(),
              "baseline reused as mutable final save")
        if state in ("accepted", "unentered"):
            offer = _one(text, "TRADE_OFFER")
            _need(_frame(baseline) <= _frame(offer) <= _frame(final), "offer outside scenario window")
            upper = _frame(offer)
        else:
            _need(not _markers(text, "TRADE_OFFER"), "unoffered visit contains fabricated OFFER")
            upper = _frame(final)
            if state == "none":
                _need(all(not _markers(text, tag) for tag in ("TRADE_NATIVE_CALL", "TRADE_CONTROL", "TRADE_APPLY_PICKUP",
                                                                "TRADE_DONE", "TRADE_FORCED_SAVE")),
                      "inactive peer entered a native trade/control path")
        ready, go = _one(text, "TRADE_READY"), _one(text, "TRADE_GO")
        _need(_frame(baseline) <= _frame(ready) <= _frame(go) <= upper
              and ready.get("snapshot_sha256") == baseline["snapshot_sha256"]
              and go.get("run_id") == receipt.get("run_id"), "baseline ready/go barrier mismatch")
        if case in COMMITTED:
            for tag in ("TRADE_APPLY_PICKUP", "TRADE_PRE_REMOVE", "TRADE_DONE", "TRADE_NATIVE_SAVE"):
                _one(text, tag)
            native = _one(text, "TRADE_NATIVE_SAVE")
            _image(native, "native trade save")
            _need(_frame(native) == _frame(_one(text, "TRADE_DONE")), "native snapshot not captured at DONE")
            paths = {Path(row["snapshot_path"]).resolve() for row in (baseline, native, final)}
            _need(len(paths) == 3, "native save requires a separate immutable image")
        elif case == "gen2_trade_reset_commit":
            if state in ("none", "unentered"):
                _need(all(not _markers(text, tag) for tag in ("TRADE_COMMIT_ENTRY", "TRADE_NATIVE_CALL", "TRADE_DONE",
                                                              "TRADE_NATIVE_SAVE", "TRADE_PRE_REMOVE")),
                      "unentered peer has native commit evidence")
            else:
                _one(text, "TRADE_APPLY_PICKUP")
                _one(text, "TRADE_COMMIT_ENTRY")
                if not _markers(text, "TRADE_DONE"):
                    control = _one(text, "TRADE_CONTROL")
                    _need(control.get("kind") == "reset_commit", "missing DONE lacks own reset-after-commit control")
                for marker in _markers(text, "TRADE_NATIVE_SAVE"):
                    _image(marker, "native trade save")
        else:
            _need(not _markers(text, "TRADE_NATIVE_SAVE") and not _markers(text, "TRADE_PRE_REMOVE"),
                  "negative case contains native commit/save evidence")
        _one(text, "TRADE_STACK")
        if overlay_provenance is not None:
            _, refs = _admission(overlay_provenance, {"scenario": case}, ROOT)
            _overlay(refs[side], receipt)
    if _one(results["a"], "RECEIPT")["case"] == "gen2_trade_reset_commit":
        _need(any(row.get("kind") == "reset_commit" for text in results.values() for row in _markers(text, "TRADE_CONTROL")),
              "reset_commit has no actual commit/reset control")


def _stack_windows(text, committed, evolved):
    stack = _one(text, "TRADE_STACK")
    _need(_frame(stack["coverage_started"]) <= _frame(_one(text, "TRADE_GO")),
          "stack coverage was armed after the visit was released")
    if _one(text, "RECEIPT").get("visit_state") == "none":
        return
    rows = {row["phase"]: row for row in _one(text, "TRADE_STACK")["phases"]}
    wait = rows["wait"]
    _need(wait["start"]["site"]["symbol"] in ("SlinkTradeEntry", "SlinkTradePromptEntry", "SlinkTradeWaitApply", "SlinkTradeWaitAck"),
          "wait coverage begins at an unrelated site")
    if not committed:
        allowed = {"SlinkTradeExit"}
        if _one(text, "RECEIPT")["case"] == "gen2_trade_reset_wait":
            allowed.add("Reset")
        _need(wait["end"]["site"]["symbol"] in allowed, "negative wait coverage lacks terminal exit/reset")
        return
    pickup, done = _one(text, "TRADE_APPLY_PICKUP"), _one(text, "TRADE_DONE")
    calls = {event["symbol"]: event for event in _markers(text, "TRADE_NATIVE_CALL")}
    _need(wait["end"]["site"]["symbol"] == "SlinkTradeApplyPickup"
          and _frame(wait["end"]) == _frame(pickup), "wait coverage does not reach APPLY pickup")
    animation = rows["trade_animation"]
    animation_name = "TradeAnimation" if _one(text, "RECEIPT")["role"] == 0 else "TradeAnimationPlayer2"
    for boundary, name in ((animation["start"], animation_name), (animation["end"], "AddTempmonToParty"),
                           (rows["native_save"]["start"], "SaveAfterLinkTrade")):
        _need(boundary["site"]["symbol"] == name and _frame(boundary) == _frame(calls[name]),
              "stack phase boundary disagrees with observed native call")
    save_end = rows["native_save"]["end"]
    _need(save_end["site"]["symbol"] == "SlinkTradePublishDone" and _frame(save_end) == _frame(done),
          "native-save stack coverage ends before DONE")
    if evolved:
        phase = rows["evolution_animation"]
        _need(phase["start"]["site"]["symbol"] == "EvolutionAnimation"
              and _frame(calls["EvolvePokemon"]) <= _frame(phase["start"]) <= _frame(calls["SaveAfterLinkTrade"])
              and phase["end"]["site"]["symbol"] == "SaveAfterLinkTrade"
              and _frame(phase["end"]) == _frame(calls["SaveAfterLinkTrade"]), "evolution stack coverage lacks native animation boundaries")


def _admission(reference, expected, root):
    from tools.gen2_trade_lane import validate_manifest
    reference = _object(reference, "overlay provenance reference")
    manifest = _reference({"path": reference.get("manifest_path"),
                           "sha256": reference.get("manifest_sha256")}, "admission manifest")
    manifest = validate_manifest(manifest, root=root)
    _need(manifest.get("schema") == "gen2-trade-lane-v1"
          and manifest.get("scenario") == expected["scenario"]
          and manifest.get("evidence_class") == "HARNESS_ONLY_OVERLAY"
          and isinstance(manifest.get("run_id"), str) and manifest["run_id"], "invalid admission manifest")
    published_raw = (root / "data/gen2/overlay_provenance.json").read_bytes()
    _digest(published_raw, manifest.get("provenance_sha256"))
    published = _json(published_raw, "published overlay provenance")
    _need(published.get("schema") == "gen2-overlay-provenance-v1", "wrong published overlay schema")
    refs = {}
    for side in SIDES:
        row = _object(manifest.get("players", {}).get(side), "admitted player")
        _need(row.get("foundation") == "gen2_gsc" and row.get("artifact_kind") == "overlay",
              "clean or wrong-foundation trade admission")
        title = row.get("title")
        pins = [item for item in published.get("outputs", {}).values() if item.get("slink_title") == title]
        _need(len(pins) == 1, "missing/ambiguous published title pin")
        pin = pins[0]
        _need(row.get("rom_sha1") == pin.get("sha1") and row.get("base_sha1") == pin.get("base_sha1")
              and row.get("ups_sha256") == pin.get("ups", {}).get("sha256")
              and row.get("sym_sha256") == published.get("symbols", {}).get(f"{title}_slink.sym"),
              "admission differs from published overlay")
        paths = _object(reference.get("players", {}).get(side), "overlay file paths")
        refs[side] = {**paths, "title": title, "rom_sha1": row["rom_sha1"], "sym_sha256": row["sym_sha256"]}
    return manifest, refs


def _project(blob, marker, title, decisions, root):
    from tools.gen2_trade_projection import project_received_mon
    try:
        projected = project_received_mon(blob, species_marker=marker, title=title,
                                         move_decisions=decisions, root=root)
    except ValueError as exc:
        raise RuntimeError(f"trade: received-mon projection refused: {exc}") from exc
    _need(projected.get("auxiliary_supported") is True, "projection has unsupported saved auxiliary effects")
    return projected


def _expected_dex(before, species):
    result = deepcopy(before)
    for fields in result.values():
        for name, encoded in fields.items():
            raw = bytearray(_hex(encoded, 32, "dex field"))
            for value in species:
                _integer(value, 1, 251, "dex species")
                raw[(value - 1) // 8] |= 1 << ((value - 1) % 8)
            fields[name] = raw.hex()
    return result


def _line(text, tag):
    return next((index for index, line in enumerate(text.splitlines()) if line.startswith(tag + " ")), None)


def _o31(text, case, side, receipt, symbols, layout, mon, slot, root):
    """O-31: the planted state is exactly the disclosed HARNESS_WRITE; anything else is undisclosed.

    Returns the planted byte (a's D3 mail item or evolve species), else None."""
    writes = _markers(text, "HARNESS_WRITE")
    scopes = [{key: row.get(key) for key in ("purpose", "domain", "symbol", "address", "bank")} for row in writes]
    _need(receipt.get("harness_write_scopes") == scopes
          and receipt.get("harness_exception") == ("O-31" if writes else None),
          "receipt does not disclose exactly its harness writes (O-31)")
    items = _json((Path(root) / f"data/games/gen2_{receipt['title']}/items.json").read_bytes(), "items pack")
    mail = {int(key) for key, row in items["items"].items() if row.get("mail")}
    purpose = PLANTS.get(case) if side == "a" else None
    if purpose is None:
        _need(not writes, "harness write in a case/side that plans none (O-31)")
        _need(mon["held_item"] not in mail, "offered mon holds mail without the disclosed D3 plant")
        return None
    _need(len(writes) == 1, "O-31 plant missing or repeated")
    write = writes[0]
    _need(write.get("purpose") == purpose and write.get("domain") == "WRAM"
          and _frame(write) < _frame(_one(text, "TRADE_BASELINE"))
          and _line(text, "HARNESS_WRITE") < _line(text, "TRADE_BASELINE"), "misplaced O-31 plant")
    _hex(write.get("bytes_before"), 1, "plant before")
    value = _hex(write.get("bytes_after"), 1, "plant after")[0]
    capture = _markers(text, "ENGINE_CAPTURE")
    _need(bool(capture), "O-31 plant without the linked catch")
    if purpose == "d3_mail_item":
        base = symbols["wPartyMon1"]
        _need(write.get("symbol") == "wPartyMon1Item" and write.get("bank") == base.bank and write.get("slot") == slot
              and write.get("address") == base.address + slot * layout.party_size + layout.constants["MON_ITEM"]
              and _line(text, "ENGINE_CAPTURE") < _line(text, "HARNESS_WRITE"),
              "D3 plant does not address the offered linked mon after its catch")
        _need(value in mail and mon["held_item"] == value, "D3 planted item differs from the saved baseline")
    else:
        target = symbols["wTempWildMonSpecies"]
        _need(write.get("symbol") == "wTempWildMonSpecies" and write.get("bank") == target.bank
              and write.get("address") == target.address and _line(text, "HARNESS_WRITE") < _line(text, "ENGINE_CAPTURE"),
              "species plant does not precede the catch at wTempWildMonSpecies")
        _need(capture[0].get("species_id") == value == mon["species_id"], "offered linked mon is not the planted species")
    return value


def _control_lease(marker, receipt, slot, commands):
    raw = _hex(marker.get("lease_hex"), 16, "control lease")
    _need(raw[:5] == b"SLT1\x01" and raw[5] in commands
          and raw[6] == raw[7] == receipt["generation"] and (raw[5] == 1 or raw[9] == slot)
          and list(raw[12:]) == receipt["token"], "control does not belong to the held pre-APPLY visit")
    return raw


def _apply_frames(root):
    """The overlay's native APPLY wait bound, from the source the overlay is built from."""
    text = (Path(root) / "patch/gen2/src/trade_service.asm").read_text(encoding="utf-8")
    found = re.findall(r"^DEF SLINK_TRADE_APPLY_FRAMES EQU (\d+)\s*$", text, re.M)
    _need(len(found) == 1, "SLINK_TRADE_APPLY_FRAMES is not uniquely defined")
    return int(found[0])


def _negative_controls(results, case, receipts, offers, decoded, invalid_items, root=ROOT):
    kind = {"gen2_trade_decline_new": "decline", "gen2_trade_timeout": "timeout",
            "gen2_trade_reset_wait": "reset_wait", "gen2_trade_refuse_item": "d3",
            "gen2_trade_refuse_contest": "contest", "gen2_trade_refuse_unsaved": "unsaved"}[case]
    observed = 0
    for side in SIDES:
        controls = _markers(results[side], "TRADE_CONTROL")
        _need(len(controls) <= 1, "duplicate negative control observation")
        for control in controls:
            _need(control.get("kind") == kind, "negative trigger kind does not match scenario")
            before, after = _object(control.get("before"), "control before"), _object(control.get("after"), "control after")
            receipt, slot, symbols = receipts[side], offers[side]["slot"], decoded[side]["symbols"]
            _need(_frame(offers[side]) <= _frame(before) <= _frame(after)
                  <= _frame(_one(results[side], "TRADE_FINAL")), "control outside offered visit")
            registers = _object(before.get("registers"), "control registers")
            if kind == "unsaved":   # the save refusal is what separates it from an offer-NO decline
                save = _object(control.get("save"), "responder save")
                _site(save.get("site"), symbols, "SlinkTradeResponderSave")
                _need(_frame(offers[side]) <= _frame(save) < _frame(before), "save refusal does not precede its decline")
            if kind == "contest":
                _site(before.get("site"), symbols, "SlinkTradeCheckOwnSlot.refuseParty")
                _site(after.get("site"), symbols, "SlinkTradeExit")
                flags = _object(before.get("wram"), "contest WRAM proof")
                _need(receipt["role"] == 1 and _integer(flags.get("wStatusFlags2"), 0, 255, "wStatusFlags2") & 4,
                      "contest refusal lacks the native Bug-Catching Contest flag")
                _control_lease(before, receipt, slot, {3})
                _control_lease(after, receipt, slot, {3})
            elif kind in ("decline", "unsaved"):
                _site(before.get("site"), symbols, "SlinkTradePublishDone")
                _need(_register(registers, "A") == 1 and receipt["role"] == 1, "decline lacks native No result")
                _control_lease(before, receipt, slot, {3})
                _site(after.get("site"), symbols, "SlinkTradeExit")
                raw = _control_lease(after, receipt, slot, {7, 8})
                _need(raw[8] == 1, "decline did not publish refused DONE")
            elif kind == "timeout":
                _site(before.get("site"), symbols, "SlinkTradeWaitApply.wait")
                _site(after.get("site"), symbols, "SlinkTradeExit")
                bound = _apply_frames(root)
                _need(_register(registers, "BC") == bound and _register(after.get("registers"), "BC") == 0
                      and _frame(after) - _frame(before) >= bound, "timeout lacks the exhausted native APPLY wait")
                _control_lease(before, receipt, slot, {2, 7, 8})
                _control_lease(after, receipt, slot, {2, 7, 8})
            elif kind == "reset_wait":
                _site(before.get("site"), symbols, "Reset")
                _site(after.get("site"), symbols, "StartTitleScreen")
                _control_lease(before, receipt, slot, {2, 3, 7, 8})
                _need(_frame(after) > _frame(before) and _hex(after.get("lease_hex"), 16, "reset lease") == bytes(16),
                      "reset lacks cleared lease at native title entry")
            else:
                _site(before.get("site"), symbols, "SlinkTradeItemAllowed")
                _site(after.get("site"), symbols, "SlinkTradeExit")
                _need(side in invalid_items and _register(registers, "A") == invalid_items[side],
                      "D3 native item predicate did not receive the independently invalid held item")
                _need(before.get("slot") == slot, "D3 selected slot does not match independently decoded baseline")
                _control_lease(before, receipt, slot, {1, 2, 3})
                _control_lease(after, receipt, slot, {1, 2, 3})
            wait = next(row for row in _one(results[side], "TRADE_STACK")["phases"] if row["phase"] == "wait")
            terminal = before if kind == "reset_wait" else after
            _need(wait["end"] == {"frame": terminal["frame"], "site": terminal["site"]},
                  "negative stack coverage does not reach the actual control exit/reset")
            observed += 1
    _need(observed > 0, "negative case has no observed native control trigger")


def _server(transaction, data_dir, manifest, receipts, before_mons, after_mons, committed, *, reconciled=None):
    transaction = _object(transaction, "transaction evidence")
    _need(transaction.get("schema") == "gen2-duo-trade-transaction-v1", "missing transaction evidence schema")
    _need(isinstance(transaction.get("tokens"), dict) and set(transaction["tokens"]) == set(SIDES),
          "both visit-token declarations are required")
    for side in SIDES:
        _need(transaction.get("tokens", {}).get(side) == receipts[side]["token"], "transaction visit token mismatch")
    token = transaction.get("server_token")
    _need(token is None and not committed or isinstance(token, str) and token.startswith("t") and token[1:].isdigit(),
          "invalid server token")
    before = _object(_reference(transaction.get("baseline_links"), "baseline links"), "baseline links")
    final = _object(_json(_read(str(Path(data_dir).resolve() / "links.json"), "durable links"), "links"), "links")
    _need(before.keys() >= STABLE_SERVER_FIELDS and final.keys() >= STABLE_SERVER_FIELDS,
          "server gameplay invariant fields missing")
    volatile = {"links", "mon_stats", *TRADE_SERVER_FIELDS}
    before_stable = {key: value for key, value in before.items() if key not in volatile}
    final_stable = {key: value for key, value in final.items() if key not in volatile}
    counters = [document.get("trade_token", 0) for document in (before, final)]
    _need(before.get("pending_trade") is None and final.get("pending_trade") is None
          and all(type(value) is int and value >= 0 for value in counters) and counters[0] <= counters[1],
          "durable pending_trade unsettled or trade_token went backwards")
    _need(before_stable == final_stable, "server gameplay fields changed outside the native trade transition")
    rows = before.get("links")
    _need(isinstance(rows, list), "missing baseline links")
    def occurrences(document, key):
        return sum(isinstance(row, dict) and isinstance(row.get(side), dict) and row[side].get("key") == key
                   for row in document for side in SIDES)
    for mon in before_mons.values():
        _need(occurrences(rows, mon["key"]) == 1, "offered identity duplicated in durable links")
    targets = [index for index, row in enumerate(rows) if isinstance(row, dict)
               and all(isinstance(row.get(side), dict) and row[side].get("key") == before_mons[side]["key"]
                       for side in SIDES)]
    _need(len(targets) == 1, "offered identities do not select exactly one baseline link")
    index = targets[0]
    _need(rows[index].get("status") == "alive", "trade link is not alive")
    expected_rows = deepcopy(rows)
    if committed:
        row = expected_rows[index]
        row["a"], row["b"] = row["b"], row["a"]
        for side in SIDES:
            row[side]["key"], row[side]["species"] = after_mons[side]["key"], after_mons[side]["species_id"]
    _need(final.get("links") == expected_rows, "durable links do not show exactly the expected atomic transaction")
    for mon in after_mons.values():
        _need(occurrences(final["links"], mon["key"]) == 1, "received identity duplicated in durable links")
    _need(final.get("player_identity") == before.get("player_identity")
          and final.get("artifact_kind") == before.get("artifact_kind")
          and final.get("rom_type") == before.get("rom_type"), "server player identity/admission changed")
    if reconciled is not None:
        _need(reconciled.get("token") == token
              and reconciled.get("outcome") == ("committed" if committed else "rolled_back"), "unproved reconciliation outcome")
        return {"area_id": rows[index].get("area_id"), "server_token": token}
    event_ref = _object(transaction.get("events"), "server event journal")
    journal = _read(event_ref.get("path"), "server event journal")
    _digest(journal, event_ref.get("sha256"))
    events = [_object(_json(line, "server event"), "server event") for line in journal.splitlines() if line.strip()]
    seq = -1
    done = {}
    for event in events:
        current = _integer(event.get("seq"), 0, 2**53, "server event sequence")
        _need(current > seq, "server event sequence repeats/reverses")
        seq = current
        _need(event.get("source") == "server_dispatch" and event.get("run_id") == manifest["run_id"]
              and event.get("scenario") == manifest["scenario"]
              and event.get("evidence_class") == "HARNESS_ONLY_OVERLAY", "server journal provenance mismatch")
        _need(event.get("outcome", {}).get("dispatch") == "returned", "server dispatch raised")
        message = _object(event.get("message"), "dispatched message")
        if token is None:
            _need(message.get("event") not in ("trade_offer", "trade_request", "trade_done")
                  and message.get("token") is None, "null server token hides an established/dispatched trade")
        if not committed:
            _need(message.get("event") != "trade_done" and not any(
                isinstance(command, dict) and command.get("cmd") == "apply_trade"
                for command in event["outcome"].get("commands") or ()),
                "negative case reached server APPLY/trade_done")
        if message.get("event") != "trade_done":
            continue
        side = event.get("player")
        _need(side in SIDES and side not in done, "missing/duplicate trade_done side")
        _need(message.get("token") == token and not message.get("uncertain"), "trade_done token/uncertainty mismatch")
        want = after_mons[side] if committed else before_mons[side]
        _need(message.get("new_key") == want["key"] and message.get("new_species") == want["species_id"],
              "server trade_done disagrees with independently decoded save")
        done[side] = message
    completion = f"trade complete (token {token})"
    log = _read(str(Path(data_dir).resolve() / "server.log"), "server log").decode("utf-8")
    if committed:
        _need(set(done) == set(SIDES) and completion in log, "server completion lacks both dispatched trade_done receipts")
    else:
        _need(("trade complete (token " not in log) if token is None else completion not in log,
              "negative case committed on server")
    return {"area_id": rows[index].get("area_id"), "server_token": token}


@_refusals
def trade_oracle(results, *, data_dir, baseline_saves, transaction_evidence,
                 overlay_provenance, expected_case, move_decisions=None, on_verified=None, root=ROOT):
    """Verify both native saved transactions and their durable shared-server result.

    ``expected_case`` names scenario, variant, per-side boot fixture_sha256 and
    required_phases. ``overlay_provenance`` references the frozen admission
    manifest plus per-side actual ROM/symbol paths. No return flag substitutes
    for missing images, raw observations, hook coverage or server evidence.
    """
    root = Path(root)
    expected = _object(expected_case, "expected case")
    case = expected.get("scenario")
    _need(case in CASES, "unknown expected trade scenario")
    if case == "gen2_trade_reset_commit":
        return _reset_commit_oracle(results, data_dir=data_dir, baseline_saves=baseline_saves,
            transaction_evidence=transaction_evidence, overlay_provenance=overlay_provenance,
            expected_case=expected, move_decisions=move_decisions, on_verified=on_verified, root=root)
    check_trade_witness(results, expected_case=case)
    manifest, overlays = _admission(overlay_provenance, expected, root)
    receipts = {side: _one(results[side], "RECEIPT") for side in SIDES}
    committed = case in COMMITTED
    before_mons, after_mons, baseline, offers, layouts, decoded, coverage = {}, {}, {}, {}, {}, {}, {}
    baseline_server = _object(_reference(transaction_evidence.get("baseline_links"), "baseline links"), "baseline links")
    for side in SIDES:
        receipt, text = receipts[side], results[side]
        _need(receipt.get("run_id") == manifest["run_id"]
              and receipt.get("fixture_sha256") == expected.get("fixture_sha256", {}).get(side),
              "receipt run/boot fixture mismatch")
        _need(isinstance(receipt.get("fixture_sha256"), str) and len(receipt["fixture_sha256"]) == 64,
              "missing boot fixture hash")
        _hex(receipt["fixture_sha256"], 32, "boot fixture hash")
        rom, symbols = _overlay(overlays[side], receipt)
        layout = codec.for_foundation(receipt["title"], root=root)
        layouts[side] = layout
        old_marker, final_marker = _one(text, "TRADE_BASELINE"), _one(text, "TRADE_FINAL")
        old, final = _image(old_marker, "baseline"), _image(final_marker, "final")
        _need(old == _read(baseline_saves.get(side), "runner baseline"), "baseline differs from runner's frozen image")
        for raw, label in ((old, "baseline"), (final, "final")):
            _need(codec.strict_checksum_witness(raw[:CART], layout)["valid"], f"{side} {label} checksum/copy witness failed")
        party = _party(old, layout)
        keys = [codec.key(codec.decode_party_blob(bytes.fromhex(mon["blob_hex"]), layout,
                                                 species_marker=mon["species_marker"])) for mon in party]
        _need(len(set(keys)) == len(keys), "baseline party has ambiguous duplicate identities")
        _need(old_marker.get("party") == party and old_marker.get("dex") == _dex(old, layout),
              "raw baseline party/dex differs from independently decoded native save")
        state = receipt.get("visit_state", "accepted")
        pre = _pre_trade(text, receipt, old, layout)
        if state == "none":
            _need(pre is old and normalized_gameplay_cartram(old, layout) == normalized_gameplay_cartram(final, layout),
                  "inactive peer changed saved gameplay bytes")
            baseline[side] = old
            decoded[side] = {"rom": rom, "symbols": symbols, "old_party": party, "saved": final, "final": final}
            continue
        if state == "query":
            control = _one(text, "TRADE_CONTROL")
            before = _object(control.get("before"), "early D3 control")
            slot = _integer(before.get("slot"), 0, len(party) - 1, "early D3 slot")
            # This is a selected baseline record, NOT a claim that OFFER published.
            offer = {"frame": _frame(before), "slot": slot, "count": len(party), **party[slot],
                     "token": receipt["token"], "generation": receipt["generation"]}
        else:
            offer = _one(text, "TRADE_OFFER")
            slot = _integer(offer.get("slot"), 0, len(party) - 1, "offered slot")
            _need(offer.get("count") == len(party) and offer.get("token") == receipt["token"]
                  and offer.get("generation") == receipt["generation"], "offer visit/count mismatch")
            _need({key: offer.get(key) for key in ("species_marker", "blob_hex")} == party[slot],
                  "offered bytes differ from immutable baseline")
        blob = _hex(offer["blob_hex"], 70, "offer")
        mon = codec.decode_party_blob(blob, layout, species_marker=offer["species_marker"])
        mon["key"] = codec.key(mon)
        before_mons[side], baseline[side], offers[side] = mon, pre, offer
        calls = _markers(text, "TRADE_NATIVE_CALL")
        calls = [event for event in calls if _frame(event) >= _frame(old_marker)]
        for event in calls:
            _site(event, symbols)
        if committed:
            animation = "TradeAnimation" if receipt["role"] == 0 else "TradeAnimationPlayer2"
            wanted = [CALLS[0], animation, *CALLS[1:]]
            _need([event.get("symbol") for event in calls] == wanted, "native commit call chain missing/extra/reordered")
            frames = [_frame(event) for event in calls]
            _need(frames == sorted(frames), "native call frames reversed")
            pickup, pre = _one(text, "TRADE_APPLY_PICKUP"), _one(text, "TRADE_PRE_REMOVE")
            done, saved_marker = _one(text, "TRADE_DONE"), _one(text, "TRADE_NATIVE_SAVE")
            generation = (receipt["generation"] + 1) % 256
            _lease(pickup, receipt["token"], generation, slot, 5)
            _lease(done, receipt["token"], generation, slot, 7, picked_up=True)
            _need(_frame(offer) <= _frame(pickup) <= _frame(pre) == frames[0]
                  and frames[-1] <= _frame(done) <= _frame(final_marker), "trade observation order invalid")
            _site(pre.get("site"), symbols, CALLS[0])
            _spans(pre.get("live"), symbols, ("wPartyMon1", "wPartyMonOTs", "wPartyMonNicknames"),
                   slot, blob, "live pre-remove")
            _spans(pre.get("frozen"), symbols, ("wOTPartyMon1", "wOTPartyMonOTs", "wOTPartyMonNicknames"),
                   1, blob, "actual frozen OT slot 1")
            saved = _image(saved_marker, "native save")
            _need(codec.strict_checksum_witness(saved[:CART], layout)["valid"], "native trade save fails checksum/copy witness")
            _need(normalized_gameplay_cartram(saved, layout) == normalized_gameplay_cartram(final, layout),
                  "final save differs from immediate native trade image")
        else:
            _need(not calls and not _markers(text, "TRADE_APPLY_PICKUP"), "negative case entered native commit path")
            _need(normalized_gameplay_cartram(pre, layout) == normalized_gameplay_cartram(final, layout),
                  "negative case changed saved gameplay bytes")
            saved = final
        decoded[side] = {"rom": rom, "symbols": symbols, "old_party": party, "saved": saved, "final": final}
    if len(before_mons) != 2:
        _need(len(before_mons) == 1, "both peers unvisited: no negative control was exercised")
        active = next(iter(before_mons))
        inactive = "b" if active == "a" else "a"
        linked = _reference(transaction_evidence.get("baseline_links"), "baseline links")
        matches = [row for row in linked.get("links", []) if isinstance(row, dict)
                   and isinstance(row.get(active), dict) and row[active].get("key") == before_mons[active]["key"]]
        _need(len(matches) == 1 and isinstance(matches[0].get(inactive), dict), "inactive counterpart is not uniquely linked")
        key = matches[0][inactive].get("key")
        found = []
        for slot, record in enumerate(decoded[inactive]["old_party"]):
            mon = codec.decode_party_blob(bytes.fromhex(record["blob_hex"]), layouts[inactive], species_marker=record["species_marker"])
            mon["key"] = codec.key(mon)
            if mon["key"] == key:
                found.append((slot, mon, record))
        _need(len(found) == 1, "inactive counterpart absent or ambiguous in independent baseline")
        slot, before_mons[inactive], record = found[0]
        offers[inactive] = {"slot": slot, **record}  # PYDEC-selected counterpart; no observed OFFER invented.
    _need({row["role"] for row in receipts.values()} == {0, 1}, "trade roles must be complementary")
    _need(before_mons["a"]["key"] != before_mons["b"]["key"], "offered identities are indistinguishable")
    pairs = {"cc": ("crystal", "crystal"), "gs": ("gold", "silver"), "cg": ("crystal", "gold")}
    _need(expected.get("variant") in pairs and tuple(receipts[s]["title"] for s in SIDES) == pairs[expected["variant"]],
          "unexpected title pairing")
    plants = {}
    for side, other in (("a", "b"), ("b", "a")):
        row, layout, offer = decoded[side], layouts[side], offers[side]
        evolved = False
        if committed:
            incoming = _one(results[side], "TRADE_APPLY_PICKUP")
            partner = offers[other]
            _need(incoming.get("incoming_blob_hex") == partner["blob_hex"]
                  and incoming.get("incoming_species_marker") == partner["species_marker"], "staged incoming record differs from partner offer")
            projected = _project(bytes.fromhex(partner["blob_hex"]), partner["species_marker"],
                                 layout.title, (move_decisions or {}).get(side), root)
            evolved = projected["evolved"]
            expected_party = row["old_party"][:offer["slot"]] + row["old_party"][offer["slot"] + 1:]
            expected_party += [{"species_marker": projected["species_marker"], "blob_hex": projected["blob_hex"]}]
            for copy in ("primary", "backup"):
                _need(_party(row["saved"], layout, copy) == expected_party,
                      f"{side} {copy} received mon/survivors differ from projection")
            expected_dex = _expected_dex(_dex(baseline[side], layout), projected["expected_dex_species"])
            _need(_dex(row["saved"], layout) == expected_dex,
                  "caught/seen dex OR differs in one or both native copies")
            from tools.gen2_trade_save_delta import encode_partner_name, verify_trade_saved_delta
            partner_identity = _object(baseline_server.get("player_identity", {}).get(other), "authenticated partner identity")
            _need("trainer_name" in partner_identity, "authenticated partner trainer name missing")
            partner_name = encode_partner_name(layout.title, partner_identity["trainer_name"],
                                               bytes.fromhex(before_mons[other]["ot_raw_hex"]), root=root)
            verify_trade_saved_delta(baseline[side], row["saved"], title=layout.title,
                expected_party=expected_party, expected_dex=expected_dex,
                partner_offer=partner, own_offer=offer, partner_player_name=partner_name, root=root)
            mon = codec.decode_party_blob(projected["blob"], layout, species_marker=projected["species_marker"])
            mon["key"] = codec.key(mon)
            after_mons[side] = mon
        else:
            after_mons[side] = before_mons[side]
        plants[side] = _o31(results[side], case, side, receipts[side], row["symbols"], layout,
                            before_mons[side], offer["slot"], root)
        _need(evolved == (case == "gen2_trade_evolve" and side == "b"),
              "trade evolution differs from the case plan (only gen2_trade_evolve's b evolves, O-31)")
        coverage[side] = _stack(_one(results[side], "TRADE_STACK"), row["rom"], row["symbols"],
                                committed=committed, evolved=evolved, visit=receipts[side].get("visit_state") != "none")
        _stack_windows(results[side], committed, evolved)
        _reload(results[side], row["final"], layout, required=committed)
        phases = expected.get("required_phases")
        _need(isinstance(phases, list) and len(set(phases)) == len(phases)
              and all(phase in PHASES and (receipts[side].get("visit_state") == "none" or coverage[side][phase]["visited"])
                      for phase in phases),
              "runner-required stack phase unvisited or invalid")
    invalid_items = {}
    if case == "gen2_trade_refuse_item":
        for side, other in (("a", "b"), ("b", "a")):
            title, item = receipts[other]["title"], before_mons[side]["held_item"]
            from tools.gen2_source_data import load_context
            from tools.gen_gen2_items import build
            pack = _json((root / f"data/games/gen2_{title}/items.json").read_bytes(), "receiving items pack")
            _need(pack == build(load_context(title, root=root)), "receiving items pack differs from pinned source/ROM")
            row = pack.get("items", {}).get(str(item))
            allowed = item == 0 or bool(row and not row["mail"] and not row["placeholder"]
                                       and not row["key_item"] and not row["permissions"] & 0x80)
            if not allowed:
                invalid_items[side] = item
        _need(invalid_items == {"a": plants["a"]}, "D3 refusal is not exactly the disclosed O-31 plant")
    if not committed:
        _negative_controls(results, case, receipts, offers, decoded, invalid_items, root)
    server = _server(transaction_evidence, data_dir, manifest, receipts, before_mons, after_mons, committed)
    facts = {"scenario": case, "status": (TradeStatus.COMMITTED if committed else TradeStatus.UNCHANGED).value,
             "admission_scope": "HARNESS_ONLY_OVERLAY", "players": {
                 side: {"title": receipts[side]["title"], "key": after_mons[side]["key"],
                        "species_id": after_mons[side]["species_id"], "stack": coverage[side]} for side in SIDES}, **server}
    if on_verified is not None:
        on_verified(facts)


# pokecrystal/pokegold engine/menus/save.asm SaveGameData rewrites the whole checksummed game data; between
# two saves at the same spot only the play-time clock (ram/wram.asm wGameTime*) and the checksums move.
CLOCK = (("wGameTimeHours", 2), ("wGameTimeMinutes", 1), ("wGameTimeSeconds", 1), ("wGameTimeFrames", 1))


def _with_clock(raw, source, layout):
    """Comparison only: raw with source's play-time bytes in BOTH copies and both checksums recomputed."""
    out = bytearray(raw)
    for name, size in CLOCK:
        address = layout.addresses[name]
        regions = [region for region in layout.regions
                   if layout.addresses[REGIONS[region.name]] <= address
                   and address + size <= layout.addresses[REGIONS[region.name]] + region.length]
        _need(len(regions) == 1, "ambiguous play-time save region")
        offset = address - layout.addresses[REGIONS[regions[0].name]]
        for start in (regions[0].primary + offset, regions[0].backup + offset):
            out[start:start + size] = source[start:start + size]
    for copy, offset in layout.checksum_offsets.items():
        out[offset:offset + 2] = codec.sav_checksum(bytes(out[:CART]), layout, copy).to_bytes(2, "little")
    return bytes(out)


def _pre_trade(text, receipt, old, layout):
    """9805ac1c forced pre-trade native save (coordinator ruling): the proposer always saves before its
    lease opens; a responder saves only after its offer YES (always before APPLY). That image, not the
    pre-receptionist baseline, is the byte-exact "before" of every later comparison. Baseline -> forced
    may differ only in the play-time clock and the checksums. Returns the before image."""
    markers = _markers(text, "TRADE_FORCED_SAVE")
    role, pickup = receipt["role"], _markers(text, "TRADE_APPLY_PICKUP")
    _need(len(markers) <= 1 and (markers or role == 1 and not pickup),
          "missing/duplicate forced pre-trade save (proposer always; responder before APPLY)")
    if not markers:
        return old
    marker = markers[0]
    raw = _image(marker, "forced pre-trade save")
    baseline, final = _one(text, "TRADE_BASELINE"), _one(text, "TRADE_FINAL")
    offers = _markers(text, "TRADE_OFFER")
    first = _frame(offers[0]) if offers else None
    if role == 0:
        upper = [first] if first is not None else []
        upper += [_frame(row["before"]) for row in _markers(text, "TRADE_CONTROL") if isinstance(row.get("before"), dict)]
        window = all(_frame(marker) <= frame for frame in upper)
    else:
        window = first is not None and first <= _frame(marker) and all(_frame(marker) <= _frame(row) for row in pickup)
    _need(_frame(_one(text, "TRADE_GO")) <= _frame(marker) < _frame(final) and window,
          "forced pre-trade save outside its native window")
    _need(len({Path(row["snapshot_path"]).resolve() for row in (baseline, marker, final)}) == 3,
          "forced pre-trade save reuses another image")
    _need(codec.strict_checksum_witness(raw[:CART], layout)["valid"], "forced pre-trade save checksum/copy witness failed")
    _need(normalized_gameplay_cartram(_with_clock(raw, old, layout), layout) == normalized_gameplay_cartram(old, layout),
          "forced pre-trade save rewrote more than the play-time clock and checksums")
    return raw


def _reset_comparison(raw, layout):
    """Comparison only: authenticated CONTINUE copies may differ in five clock bytes.

    Validate BOTH original checksums and all non-clock copy bytes before repairing
    only the comparison's backup clock/checksum. Never alter the original image.
    """
    from tools.gen2_duo_oracles import _relaunch_checksum_witness
    _need(_relaunch_checksum_witness(raw[:CART], layout), "reset checksum/non-clock copy mismatch")
    out = bytearray(raw)
    for name, size in (("wGameTimeHours", 2), ("wGameTimeMinutes", 1),
                       ("wGameTimeSeconds", 1), ("wGameTimeFrames", 1)):
        address = layout.addresses[name]
        regions = [region for region in layout.regions
                   if layout.addresses[REGIONS[region.name]] <= address
                   and address + size <= layout.addresses[REGIONS[region.name]] + region.length]
        _need(len(regions) == 1, "ambiguous reset clock save region")
        region = regions[0]
        offset = address - layout.addresses[REGIONS[region.name]]
        out[region.backup + offset:region.backup + offset + size] = raw[region.primary + offset:region.primary + offset + size]
    offset = layout.checksum_offsets["backup"]
    out[offset:offset + 2] = codec.sav_checksum(bytes(out[:CART]), layout, "backup").to_bytes(2, "little")
    _need(codec.strict_checksum_witness(bytes(out[:CART]), layout)["valid"], "reset clock comparison did not restore copy agreement")
    return bytes(out)


def _reset_control(text, receipt, offer, symbols):
    controls = _markers(text, "TRADE_CONTROL")
    _need(len(controls) <= 1, "duplicate reset-commit control")
    if not controls:
        return None
    control = controls[0]
    _need(control.get("kind") == "reset_commit", "wrong reset-commit trigger")
    entry = _one(text, "TRADE_COMMIT_ENTRY")
    _need(control.get("commit") == entry, "reset control lost the actual commit entry")
    _site(entry.get("site"), symbols, "SlinkTradeCommit")
    generation = (receipt["generation"] + 1) % 256
    _lease(entry, receipt["token"], generation, offer["slot"], 5, picked_up=True)
    before, after = _object(control.get("before"), "reset before"), _object(control.get("after"), "reset after")
    _site(before.get("site"), symbols, "Reset")
    _site(after.get("site"), symbols, "StartTitleScreen")
    raw = _hex(before.get("lease_hex"), 16, "reset commit lease")
    _need(raw[:5] == b"SLT1\x01" and raw[5] in (5, 7) and raw[6] == raw[7] == generation
          and raw[9] == offer["slot"] and list(raw[12:]) == receipt["token"], "reset lost committed visit binding")
    _need(_frame(entry) <= _frame(before) < _frame(after) <= _frame(_one(text, "TRADE_FINAL"))
          and _hex(after.get("lease_hex"), 16, "reset cleared lease") == bytes(16), "missing native reset/cleared-lease observation")
    return control


def _reload(text, raw_final, layout, *, required):
    markers = _markers(text, "TRADE_RELOAD")
    _need(len(markers) == 1 if required else len(markers) <= 1, "missing/duplicate required TRADE_RELOAD")
    if not markers:
        return
    marker, final = markers[0], _one(text, "TRADE_FINAL")
    mons = codec.decode_saved_party(raw_final[:CART], layout, copy_name="primary")["mons"]
    _need(_frame(marker) > _frame(final) and marker.get("snapshot_sha256") == final["snapshot_sha256"],
          "reload precedes final image or boots a different save")
    _need(marker.get("party_keys") == [codec.key(mon) for mon in mons] and marker.get("dex") == _dex(raw_final, layout),
          "reload party/dex differs from independently decoded final image")


def _reset_phases(text, receipt, calls, control, *, traded, evolved):
    """Interrupted native phases end at the observed Reset, not a fabricated return."""
    state = receipt.get("visit_state", "accepted")
    if state == "none":
        return set()
    phases = {row["phase"]: row for row in _one(text, "TRADE_STACK")["phases"]}
    wait = phases["wait"]
    _need(wait["start"]["site"]["symbol"] in ("SlinkTradeEntry", "SlinkTradePromptEntry", "SlinkTradeWaitApply", "SlinkTradeWaitAck"),
          "reset wait starts at unrelated site")
    required = {"wait"}
    if state == "unentered":
        allowed = {"SlinkTradeExit", "SlinkTradeApplyPickup"}
        _need(wait["end"]["site"]["symbol"] in allowed, "unentered wait lost terminal boundary")
        return required
    pickup = _one(text, "TRADE_APPLY_PICKUP")
    _need(wait["end"]["site"]["symbol"] == "SlinkTradeApplyPickup" and _frame(wait["end"]) == _frame(pickup),
          "reset wait coverage does not reach pickup")
    by_name = {call["symbol"]: call for call in calls}
    animation = "TradeAnimation" if receipt["role"] == 0 else "TradeAnimationPlayer2"
    def endpoint(phase, edge, name, frame):
        bound = phases[phase][edge]
        _need(bound["site"]["symbol"] == name and _frame(bound) == frame,
              "reset stack phase lacks its observed native boundary")
    reset = control["before"] if control else None
    for phase, start, finish in (("trade_animation", animation, "AddTempmonToParty"),
                                 ("native_save", "SaveAfterLinkTrade", "SlinkTradePublishDone")):
        if start not in by_name:
            _need(not phases[phase]["visited"], "unentered native phase claimed as visited")
            continue
        required.add(phase)
        endpoint(phase, "start", start, _frame(by_name[start]))
        if finish in by_name:
            endpoint(phase, "end", finish, _frame(by_name[finish]))
        elif finish == "SlinkTradePublishDone" and _markers(text, "TRADE_DONE"):
            endpoint(phase, "end", finish, _frame(_one(text, "TRADE_DONE")))
        else:
            _need(reset is not None, "interrupted phase has no native reset")
            endpoint(phase, "end", "Reset", _frame(reset))
    evolution = phases["evolution_animation"]
    if traded and evolved:
        required.add("evolution_animation")
    if evolution["visited"]:
        _need("EvolvePokemon" in by_name and evolution["start"]["site"]["symbol"] == "EvolutionAnimation"
              and _frame(evolution["start"]) >= _frame(by_name["EvolvePokemon"]), "unobserved native evolution animation")
        if "SaveAfterLinkTrade" in by_name:
            endpoint("evolution_animation", "end", "SaveAfterLinkTrade", _frame(by_name["SaveAfterLinkTrade"]))
        else:
            _need(reset is not None, "interrupted evolution has no reset")
            endpoint("evolution_animation", "end", "Reset", _frame(reset))
    return required


def _reset_commit_oracle(results, *, data_dir, baseline_saves, transaction_evidence,
                         overlay_provenance, expected_case, move_decisions, on_verified, root):
    from tools.gen2_trade_reconciliation import verify_reconciliation
    from tools.gen2_trade_save_delta import encode_partner_name, verify_trade_saved_delta
    transaction = _object(transaction_evidence, "reset transaction")
    if not isinstance(transaction.get("reconciliation"), dict):
        raise TradeUncertain("gen2_trade_reset_commit", "missing authenticated reconciliation events/status")
    check_trade_witness(results, expected_case=expected_case)
    manifest, refs = _admission(overlay_provenance, expected_case, root)
    receipts = {side: _one(results[side], "RECEIPT") for side in SIDES}
    baseline_links = _object(_reference(transaction.get("baseline_links"), "baseline links"), "baseline links")
    rows, before_mons, after_mons, verdicts, parties, coverage = {}, {}, {}, {}, {}, {}
    for side in SIDES:
        text, receipt = results[side], receipts[side]
        _need(receipt.get("run_id") == manifest["run_id"]
              and receipt.get("fixture_sha256") == expected_case.get("fixture_sha256", {}).get(side), "reset run/fixture mismatch")
        _hex(receipt.get("fixture_sha256"), 32, "fixture hash")
        rom, symbols = _overlay(refs[side], receipt)
        layout = codec.for_foundation(receipt["title"], root=root)
        baseline = _image(_one(text, "TRADE_BASELINE"), "baseline")
        raw_final = _image(_one(text, "TRADE_FINAL"), "final raw reset image")
        _need(baseline == _read(baseline_saves.get(side), "frozen baseline")
              and codec.strict_checksum_witness(baseline[:CART], layout)["valid"], "invalid reset baseline")
        old_party = _party(baseline, layout)
        marker = _one(text, "TRADE_BASELINE")
        _need(marker.get("party") == old_party and marker.get("dex") == _dex(baseline, layout), "reset baseline raw party/dex mismatch")
        baseline = _pre_trade(text, receipt, baseline, layout)   # the forced pre-trade save is the "before"
        state = receipt.get("visit_state", "accepted")
        offer = None
        if state != "none":
            offer = _one(text, "TRADE_OFFER")
            slot = _integer(offer.get("slot"), 0, len(old_party) - 1, "reset offered slot")
            _need(offer.get("token") == receipt["token"] and offer.get("generation") == receipt["generation"]
                  and offer.get("count") == len(old_party)
                  and {k: offer.get(k) for k in ("species_marker", "blob_hex")} == old_party[slot], "reset offer mismatch")
            mon = codec.decode_party_blob(bytes.fromhex(offer["blob_hex"]), layout, species_marker=offer["species_marker"])
            mon["key"] = codec.key(mon)
            before_mons[side] = mon
        control = _reset_control(text, receipt, offer, symbols) if state == "accepted" else None
        final = _reset_comparison(raw_final, layout) if control else raw_final
        _need(codec.strict_checksum_witness(final[:CART], layout)["valid"], "reset final checksum/copy mismatch")
        calls = [call for call in _markers(text, "TRADE_NATIVE_CALL") if _frame(call) >= _frame(marker)]
        for call in calls:
            _site(call, symbols)
        if state == "accepted":
            pickup, entry = _one(text, "TRADE_APPLY_PICKUP"), _one(text, "TRADE_COMMIT_ENTRY")
            generation = (receipt["generation"] + 1) % 256
            _lease(pickup, receipt["token"], generation, offer["slot"], 5)
            _site(entry.get("site"), symbols, "SlinkTradeCommit")
            _lease(entry, receipt["token"], generation, offer["slot"], 5, picked_up=True)
            animation = "TradeAnimation" if receipt["role"] == 0 else "TradeAnimationPlayer2"
            wanted = [CALLS[0], animation, *CALLS[1:]]
            _need([call["symbol"] for call in calls] == wanted[:len(calls)], "reset native chain is not a valid prefix")
            frames = [_frame(call) for call in calls]
            _need(frames == sorted(frames) and _frame(offer) <= _frame(pickup) <= _frame(entry)
                  and (not frames or _frame(entry) <= frames[0]), "reset native call order invalid")
            if control:
                _need(all(frame <= _frame(control["before"]) for frame in frames), "native calls continued after observed reset")
            else:
                _need(len(calls) == len(wanted), "nonreset peer needs a complete native chain")
            if calls:
                pre = _one(text, "TRADE_PRE_REMOVE")
                _need(_frame(pre) == frames[0], "reset pre-remove dump is not same-frame")
                _site(pre.get("site"), symbols, CALLS[0])
                blob = bytes.fromhex(offer["blob_hex"])
                _spans(pre.get("live"), symbols, ("wPartyMon1", "wPartyMonOTs", "wPartyMonNicknames"), offer["slot"], blob, "live pre-remove")
                _spans(pre.get("frozen"), symbols, ("wOTPartyMon1", "wOTPartyMonOTs", "wOTPartyMonNicknames"), 1, blob, "frozen pre-remove")
            else:
                _need(not _markers(text, "TRADE_PRE_REMOVE"), "pre-remove dump without native removal")
            if _markers(text, "TRADE_DONE"):
                done = _one(text, "TRADE_DONE")
                _lease(done, receipt["token"], generation, offer["slot"], 7, picked_up=True)
                _need(len(calls) == len(wanted) and frames[-1] <= _frame(done) <= _frame(_one(text, "TRADE_FINAL"))
                      and (control is None or _frame(done) <= _frame(control["before"])), "DONE without completed native chain")
                saved_marker = _one(text, "TRADE_NATIVE_SAVE")
                saved = _image(saved_marker, "native image before reset")
                _need(_frame(saved_marker) == _frame(done)
                      and codec.strict_checksum_witness(saved[:CART], layout)["valid"]
                      and normalized_gameplay_cartram(saved, layout) == normalized_gameplay_cartram(final, layout),
                      "reset final differs from authenticated native DONE image")
            else:
                _need(control is not None, "missing DONE is not explained by own reset")
                if _markers(text, "TRADE_NATIVE_SAVE"):
                    returned = _one(text, "TRADE_SAVE_RETURNED")
                    _site(returned.get("site"), symbols, "SlinkTradeCommit.cleanup")
                    _need(len(calls) == len(wanted) and _register(returned.get("registers"), "B") == 0
                          and frames[-1] <= _frame(returned) <= _frame(control["before"]),
                          "pre-reset native image lacks successful actual save return")
                    saved_marker = _one(text, "TRADE_NATIVE_SAVE")
                    saved = _image(saved_marker, "native returned save")
                    _need(_frame(saved_marker) == saved_marker.get("capture_frame") == _frame(returned)
                          and saved_marker.get("save_entry_frame") == frames[-1]
                          and codec.strict_checksum_witness(saved[:CART], layout)["valid"]
                          and normalized_gameplay_cartram(saved, layout) == normalized_gameplay_cartram(final, layout),
                          "native returned image is not bound to observed return/final saved bytes")
        rows[side] = {"rom": rom, "symbols": symbols, "layout": layout, "baseline": baseline, "final": final,
                      "raw_final": raw_final, "old_party": old_party, "offer": offer, "control": control,
                      "calls": calls}
    _need(any(row["control"] for row in rows.values()), "reset_commit is a no-op without entered reset")
    if len(before_mons) == 1:
        active = next(iter(before_mons))
        other = "b" if active == "a" else "a"
        links = [link for link in baseline_links.get("links", []) if isinstance(link.get(active), dict)
                 and link[active].get("key") == before_mons[active]["key"]]
        _need(len(links) == 1, "unvisited reset counterpart is not uniquely linked")
        wanted_key = links[0][other]["key"]
        matches = []
        for slot, record in enumerate(rows[other]["old_party"]):
            mon = codec.decode_party_blob(bytes.fromhex(record["blob_hex"]), rows[other]["layout"], species_marker=record["species_marker"])
            mon["key"] = codec.key(mon)
            if mon["key"] == wanted_key:
                matches.append((slot, record, mon))
        _need(len(matches) == 1, "unvisited counterpart absent/ambiguous in saved party")
        slot, record, before_mons[other] = matches[0]
        rows[other]["offer"] = {"slot": slot, **record}
    _need(set(before_mons) == set(SIDES) and {r["role"] for r in receipts.values()} == {0, 1}, "reset offered pair/roles missing")
    pairs = {"cc": ("crystal", "crystal"), "gs": ("gold", "silver"), "cg": ("crystal", "gold")}
    _need(tuple(receipts[s]["title"] for s in SIDES) == pairs.get(expected_case.get("variant")), "reset title pairing mismatch")
    for side, other in (("a", "b"), ("b", "a")):
        row, partner = rows[side], rows[other]["offer"]
        layout, offer = row["layout"], row["offer"]
        actual_party = _party(row["raw_final"], layout)
        actual_mons = [codec.decode_party_blob(bytes.fromhex(record["blob_hex"]), layout,
                                              species_marker=record["species_marker"]) for record in actual_party]
        parties[side] = [codec.key(mon) for mon in actual_mons]
        _need(parties[side] and len(set(parties[side])) == len(parties[side]), "conflict: duplicate/empty final saved party")
        unchanged = normalized_gameplay_cartram(row["baseline"], layout) == normalized_gameplay_cartram(row["final"], layout)
        evolved = False
        if unchanged:
            verdicts[side], after_mons[side] = "none", before_mons[side]
        else:
            _need(receipts[side].get("visit_state", "accepted") == "accepted", "conflict: unentered peer changed its save")
            _need([call["symbol"] for call in row["calls"]][-1:] == ["SaveAfterLinkTrade"], "conflict: changed save without native save entry")
            projection = _project(bytes.fromhex(partner["blob_hex"]), partner["species_marker"], layout.title,
                                  (move_decisions or {}).get(side), root)
            expected_party = row["old_party"][:offer["slot"]] + row["old_party"][offer["slot"] + 1:]
            expected_party.append({"species_marker": projection["species_marker"], "blob_hex": projection["blob_hex"]})
            dex = _expected_dex(_dex(row["baseline"], layout), projection["expected_dex_species"])
            _need(all(_party(row["raw_final"], layout, copy) == expected_party for copy in ("primary", "backup"))
                  and _dex(row["raw_final"], layout) == dex, "conflict: saved party/dex is neither original nor projected trade")
            identity = _object(baseline_links.get("player_identity", {}).get(other), "authenticated partner")
            _need("trainer_name" in identity, "missing partner trainer name")
            name = encode_partner_name(layout.title, identity["trainer_name"], bytes.fromhex(before_mons[other]["ot_raw_hex"]), root=root)
            verify_trade_saved_delta(row["baseline"], row["final"], title=layout.title, expected_party=expected_party,
                expected_dex=dex, partner_offer=partner, own_offer=offer, partner_player_name=name, root=root)
            verdicts[side], evolved = "traded", projection["evolved"]
            after_mons[side] = {**actual_mons[-1], "key": codec.key(actual_mons[-1])}
        _o31(results[side], expected_case["scenario"], side, receipts[side], row["symbols"], layout,
             before_mons[side], offer["slot"], root)
        _reload(results[side], row["raw_final"], layout, required=not unchanged)
        if receipts[side].get("visit_state", "accepted") == "accepted":
            pickup = _one(results[side], "TRADE_APPLY_PICKUP")
            _need(pickup.get("incoming_blob_hex") == partner["blob_hex"]
                  and pickup.get("incoming_species_marker") == partner["species_marker"], "reset incoming staging differs from partner baseline")
        required = _reset_phases(results[side], receipts[side], row["calls"], row["control"], traded=not unchanged, evolved=evolved)
        stack = _one(results[side], "TRADE_STACK")
        coverage[side] = _stack(stack, row["rom"], row["symbols"], committed=False,
            evolved=evolved if not unchanged else None, visit=receipts[side].get("visit_state") != "none", partial_phases=required)
        _need(_frame(stack["coverage_started"]) <= _frame(_one(results[side], "TRADE_GO")), "reset coverage began after visit")
        _need(all(phase in PHASES and (receipts[side].get("visit_state") == "none" or coverage[side][phase]["visited"])
                  for phase in expected_case.get("required_phases", [])), "required reset phase unvisited")
    refs = transaction["reconciliation"]
    events, status = _reference(refs.get("events"), "reconciliation events"), _reference(refs.get("status"), "reconciliation status")
    _need(events == _json(_read(str(Path(data_dir).resolve() / "events.json"), "durable outcome events"), "events"),
          "outcome snapshot differs from durable events.json")
    journal_ref = _object(transaction.get("events"), "dispatch journal")
    raw = _read(journal_ref.get("path"), "dispatch journal")
    _digest(raw, journal_ref.get("sha256"))
    journal = [_object(_json(line, "dispatch row"), "dispatch row") for line in raw.splitlines() if line.strip()]
    _need(all(row.get("run_id") == manifest["run_id"] and row.get("scenario") == expected_case["scenario"] for row in journal),
          "reconciliation journal does not belong to admitted attempt")
    reconciliation = verify_reconciliation(token=transaction.get("server_token"),
        before_keys={s: before_mons[s]["key"] for s in SIDES}, after_keys={s: after_mons[s]["key"] for s in SIDES},
        final_party_keys=parties, independent_verdicts=verdicts, events=events, status=status, journal=journal)
    committed = reconciliation["outcome"] == "committed"
    server = _server(transaction, data_dir, manifest, receipts, before_mons, after_mons, committed, reconciled=reconciliation)
    facts = {"scenario": expected_case["scenario"],
             "status": (TradeStatus.COMMITTED if committed else TradeStatus.UNCHANGED).value,
             "admission_scope": "HARNESS_ONLY_OVERLAY", "reconciliation": reconciliation, "players": {
                 side: {"title": receipts[side]["title"], "key": after_mons[side]["key"],
                        "species_id": after_mons[side]["species_id"], "stack": coverage[side],
                        "snapshot_sha256": _one(results[side], "TRADE_FINAL")["snapshot_sha256"],
                        "backup_clock_normalized": rows[side]["raw_final"] != rows[side]["final"]} for side in SIDES}, **server}
    if on_verified is not None:
        on_verified(facts)
