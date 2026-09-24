"""Saved-byte and provenance falsifiers for the trade oracle; MODEL only."""
import hashlib
import json
from copy import deepcopy
from functools import lru_cache
from pathlib import Path

import pytest

from server.adapters import gen2_codec as codec
from tools import (
    gen2_trade_oracles as oracle,
    gen2_trade_projection as projection,
    gen2_trade_save_delta as saved_delta,
)
from tools.build_gen2_companion import ups_apply
from tools.gen2_source_data import load_context
from tools.rgbds_symbols import parse_symbols

ROOT = Path(__file__).resolve().parents[2]
_verified_name_encoder = lru_cache(maxsize=None)(saved_delta.encode_partner_name)


def digest(data):
    return hashlib.sha256(data).hexdigest()


@pytest.fixture(scope="module")
def sources():
    return {title: projection._load_projection_data(title, ROOT) for title in ("crystal", "gold", "silver")}


@pytest.fixture(autouse=True)
def cached_sources(monkeypatch, sources):
    monkeypatch.setattr(projection, "_load_projection_data", lambda title, root: sources[title])
    monkeypatch.setattr(codec, "for_foundation", lambda title, root=ROOT: sources[title]["layout"])
    monkeypatch.setattr(saved_delta, "encode_partner_name", _verified_name_encoder)


@lru_cache(maxsize=3)
def overlay(title):
    published = json.loads((ROOT / "data/gen2/overlay_provenance.json").read_bytes())
    pin = next(row for row in published["outputs"].values() if row["slink_title"] == title)
    return ups_apply(load_context(title).rom, (ROOT / pin["ups"]["file"]).read_bytes()), pin


def put(raw, layout, symbol, payload):
    for region in layout.regions:
        base = layout.addresses[oracle.REGIONS[region.name]]
        if base <= layout.addresses[symbol] < base + region.length:
            for copy in ("primary", "backup"):
                start = getattr(region, copy) + layout.addresses[symbol] - base
                raw[start:start + len(payload)] = payload
            return
    raise AssertionError(symbol)


def checksum(raw, layout):
    for copy, offset in layout.checksum_offsets.items():
        raw[offset:offset + 2] = codec.sav_checksum(bytes(raw[:oracle.CART]), layout, copy).to_bytes(2, "little")
    return bytes(raw)


def party_save(raw, layout, party, dex_species=()):
    raw = bytearray(raw)
    put(raw, layout, "wPartyCount", bytes([len(party)]))
    put(raw, layout, "wPartySpecies", bytes([mon["species_marker"] for mon in party] + [255]))
    blobs = [bytes.fromhex(mon["blob_hex"]) for mon in party]
    for symbol, start, end in (("wPartyMon1", 0, 48), ("wPartyMonOTs", 48, 59), ("wPartyMonNicknames", 59, 70)):
        put(raw, layout, symbol, b"".join(blob[start:end] for blob in blobs))
    for symbol in ("wPokedexCaught", "wPokedexSeen"):
        value = bytearray(oracle._saved(raw, layout, symbol, 32, "primary"))
        for species in dex_species:
            value[(species - 1) // 8] |= 1 << ((species - 1) % 8)
        put(raw, layout, symbol, value)
    return checksum(raw, layout)


def save_bytes(raw, layout, symbols, name, data, delta=0):
    """Write data at a saved WRAM symbol (+delta) in BOTH copies; False when the title does not save it."""
    spans = oracle._saved_spans(layout, symbols[name].address + delta, len(data))
    for start in spans:
        raw[start:start + len(data)] = data
    return bool(spans)


def forced_save(raw, layout, symbols, seconds=7, staged=None):
    """MODEL of the 9805ac1c forced pre-trade native save, trgs2-shaped: the clocks move, the player and
    two object structs face another way (START menu -> receptionist), a responder saves its PROMPT staging."""
    raw = bytearray(raw)
    value = oracle._saved(bytes(raw), layout, "wGameTimeSeconds", 1, "primary")[0]
    put(raw, layout, "wGameTimeSeconds", bytes([(value + seconds) % 60]))
    save_bytes(raw, layout, symbols, "wRTC", bytes([0x12]), delta=2)
    for name, facing in (("wPlayerFacing", 0x04), ("wObject1Facing", 0x00), ("wObject2Facing", 0x00)):
        save_bytes(raw, layout, symbols, name, bytes([facing]))
    if staged is not None:   # lua/gen2/trade_overlay.lua stage() on a PROMPT: the name is the incoming OT
        blob, marker = staged
        for name, data in (("wOTPlayerName", blob[48:59]), ("wOTPartyCount", b"\x01"),
                           ("wOTPartySpecies", bytes([marker, 0xFF])), ("wOTPartyMon1", blob[:48]),
                           ("wOTPartyMonOTs", blob[48:59]), ("wOTPartyMonNicknames", blob[59:70])):
            save_bytes(raw, layout, symbols, name, data)
    return checksum(raw, layout)


def image(path, raw, frame):
    path.write_bytes(raw)
    return {"frame": frame, "snapshot_path": str(path), "snapshot_sha256": digest(raw),
            "cartram_sha256": digest(raw[:oracle.CART]), "snapshot_bytes": len(raw), "cartram_bytes": oracle.CART}


def site(symbols, name):
    symbol = symbols[name]
    return {"symbol": name, "bank": symbol.bank, "address": symbol.address}


def span_dump(symbols, prefix, slot, blob):
    names = (prefix + "Mon1", prefix + "MonOTs", prefix + "MonNicknames")
    return {"domain": "System Bus", "bank": 1, "spans": [
        {"address": symbols[name].address + slot * size, "hex": blob[start:start + size].hex()}
        for name, size, start in zip(names, (48, 11, 11), (0, 48, 59), strict=True)]}


def lease(command, token, generation, slot, done=False):
    return bytes([83, 76, 84, 49, 1, command, generation,
                  generation if done else (generation - 1) % 256, 0 if done else 255, slot, 1, 0, *token]).hex()


def encoded(markers):
    return "\n".join(f"{tag} {json.dumps(value)}" for tag, value in markers) + "\nRESULT: PASS"


def get(case, side, tag):
    return next(value for name, value in case["markers"][side] if name == tag)


def invoke(case, on_verified=None):
    return oracle.trade_oracle({side: encoded(rows) for side, rows in case["markers"].items()},
                               **case["kwargs"], on_verified=on_verified)


def make_case(tmp_path, sources, variant="cc", scenario="gen2_trade_new", mail_sides=None):
    titles = dict(zip(("a", "b"), {"cc": ("crystal", "crystal"), "gs": ("gold", "silver"),
                                      "cg": ("crystal", "gold")}[variant], strict=True))
    committed = scenario in oracle.COMMITTED
    # O-31: gen2_trade_evolve's a catches the planted HAUNTER; b's cartridge evolves it natively
    offered_species = {side: 93 if scenario == "gen2_trade_evolve" and side == "a" else 16 for side in ("a", "b")}
    pub = (ROOT / "data/gen2/overlay_provenance.json").read_bytes()
    manifest = {"schema": "gen2-trade-lane-v1", "run_id": "MODEL-trade", "scenario": scenario,
                "evidence_class": "HARNESS_ONLY_OVERLAY", "provenance_sha256": digest(pub), "players": {}}
    refs, baseline_paths, old, offers, markers, syms, before, projected = {}, {}, {}, {}, {}, {}, {}, {}
    tokens = {"a": [1, 2, 3, 4], "b": [5, 6, 7, 8]}
    generations = {"a": 255, "b": 17}
    for number, side in enumerate(("a", "b")):
        title, data = titles[side], sources[titles[side]]
        layout = data["layout"]
        raw = (ROOT / f"tests/fixtures/gen2/{title}_battle.SaveRAM").read_bytes()
        template = codec.decode_saved_party(raw[:oracle.CART], layout, copy_name="primary")["mons"][0]
        party = []
        for index in range(2):
            mon = deepcopy(template)
            species = offered_species[side] if index == 0 else 16 + index
            mon.update(species_id=species, species_marker=species, held_item=0,
                       happiness=120, ot_id=1200 + number, dv_word=0x1234 + number * 10 + index)
            mon["dvs"] = codec.decode_dvs(mon["dv_word"])
            if side in (mail_sides if mail_sides is not None else ("a",) * (scenario == "gen2_trade_refuse_item")) and index == 0:
                mon["held_item"] = next(int(key) for key, row in data["items"].items() if row["mail"])
            party.append({"species_marker": mon["species_marker"], "blob_hex": codec.encode_party_blob(mon, layout).hex()})
        old[side] = party_save(raw, layout, party)
        baseline_paths[side] = tmp_path / f"{side}.baseline.SaveRAM"
        baseline = image(baseline_paths[side], old[side], 100)
        baseline.update(party=party, dex=oracle._dex(old[side], layout))
        offers[side] = {"frame": 110, "token": tokens[side], "generation": generations[side],
                        "slot": 0, "count": 2, **party[0]}
        before[side] = codec.decode_party_blob(bytes.fromhex(party[0]["blob_hex"]), layout,
                                               species_marker=offered_species[side])
        before[side]["key"] = codec.key(before[side])
        rom, pin = overlay(title)
        rom_path = tmp_path / f"{side}.gbc"
        rom_path.write_bytes(rom)
        sym_path = ROOT / f"data/gen2/{title}_slink.sym"
        syms[side] = parse_symbols(sym_path.read_text())
        refs[side] = {"rom_path": str(rom_path), "sym_path": str(sym_path)}
        manifest["players"][side] = {"title": title, "rom_type": title.title(), "foundation": "gen2_gsc",
            "artifact_kind": "overlay", "rom_sha1": pin["sha1"], "base_sha1": pin["base_sha1"],
            "ups_sha256": pin["ups"]["sha256"], "sym_sha256": digest(sym_path.read_bytes())}
        receipt = {"schema": "gen2-duo-trade-v1", "player": side, "title": title, "case": scenario,
                   "rom_sha1": pin["sha1"], "run_id": manifest["run_id"], "fixture_sha256": "a" * 64,
                   "admission_scope": "HARNESS_ONLY_OVERLAY", "token": tokens[side],
                   "generation": generations[side], "role": number,
                   "harness_write_scopes": [], "harness_exception": None}
        symbols = syms[side]
        plant = oracle.PLANTS.get(scenario) if side == "a" else None
        setup = []
        if plant:
            if plant == "d3_mail_item":
                target, address, value = "wPartyMon1Item", symbols["wPartyMon1"].address + layout.constants["MON_ITEM"], party[0]["blob_hex"][2:4]
                bank = symbols["wPartyMon1"].bank
            else:
                target, address, value = "wTempWildMonSpecies", symbols["wTempWildMonSpecies"].address, "5d"
                bank = symbols["wTempWildMonSpecies"].bank
            write = {"frame": 90, "domain": "WRAM", "bank": bank, "address": address, "symbol": target,
                     "wram_offset": 0, "bytes_before": "00", "bytes_after": value, "purpose": plant, "slot": 0}
            receipt.update(harness_write_scopes=[{key: write[key] for key in ("purpose", "domain", "symbol", "address", "bank")}],
                           harness_exception="O-31")
            capture = ("ENGINE_CAPTURE", {"key": "MODEL", "species_id": offered_species[side]})
            setup = [capture, ("HARNESS_WRITE", write)] if plant == "d3_mail_item" else [("HARNESS_WRITE", write), capture]
        markers[side] = [("RECEIPT", receipt), *setup, ("TRADE_BASELINE", baseline),
                         ("TRADE_READY", {"frame": 105, "snapshot_sha256": baseline["snapshot_sha256"]}),
                         ("TRADE_GO", {"frame": 108, "run_id": manifest["run_id"]}), ("TRADE_OFFER", offers[side])]
    for side, partner in (("a", "b"), ("b", "a")):
        layout, symbols = sources[titles[side]]["layout"], syms[side]
        saved_before = old[side]
        offers[side].update(incoming_blob_hex=offers[partner]["blob_hex"],
                            incoming_species_marker=offers[partner]["species_marker"])
        if side == "a" or committed:   # the proposer always saves; a responder only after its YES
            staged = (bytes.fromhex(offers[partner]["blob_hex"]), offers[partner]["species_marker"]) if side == "b" else None
            saved_before = forced_save(old[side], layout, symbols, staged=staged)
            markers[side].append(("TRADE_FORCED_SAVE", image(tmp_path / f"{side}.forced.SaveRAM", saved_before,
                                                             109 if side == "a" else 115)))
        if committed:
            offered = offers[partner]
            p = projection.project_received_mon(bytes.fromhex(offered["blob_hex"]),
                                                species_marker=offered_species[partner], title=titles[side])
            projected[side] = p
            party = oracle._party(saved_before, layout)[1:] + [{"species_marker": p["species_marker"], "blob_hex": p["blob_hex"]}]
            # MODEL construction uses the separate source-derived saved-delta model;
            # corruption controls alter its bytes independently and re-checksum them.
            sender = saved_delta.encode_partner_name(titles[side], f"MODEL-{partner.upper()}",
                        bytes.fromhex(before[partner]["ot_raw_hex"]), root=ROOT)
            dex = oracle._expected_dex(oracle._dex(saved_before, layout), p["expected_dex_species"])
            final = saved_delta._expected(saved_before, layout, party, dex, offers[partner], offers[side], sender)
            generation = (generations[side] + 1) % 256
            markers[side] += [("TRADE_APPLY_PICKUP", {"frame": 120,
                "lease_hex": lease(5, tokens[side], generation, 0), "incoming_blob_hex": offered["blob_hex"],
                "incoming_species_marker": offered_species[partner]}), ("TRADE_PRE_REMOVE", {"frame": 121,
                "site": site(symbols, "RemoveMonFromPartyOrBox"),
                "live": span_dump(symbols, "wParty", 0, bytes.fromhex(offers[side]["blob_hex"])),
                "frozen": span_dump(symbols, "wOTParty", 1, bytes.fromhex(offers[side]["blob_hex"]))})]
            animation = "TradeAnimation" if side == "a" else "TradeAnimationPlayer2"
            for frame, symbol in zip((121, 130, 140, 150, 160), (oracle.CALLS[0], animation, *oracle.CALLS[1:]), strict=True):
                markers[side].append(("TRADE_NATIVE_CALL", {"frame": frame, **site(symbols, symbol)}))
            markers[side] += [("TRADE_DONE", {"frame": 170, "lease_hex": lease(7, tokens[side], generation, 0, True)}),
                             ("TRADE_NATIVE_SAVE", image(tmp_path / f"{side}.native.SaveRAM", final, 170))]
        else:
            final = saved_before
        final_marker = image(tmp_path / f"{side}.final.SaveRAM", final, 200)
        markers[side].append(("TRADE_FINAL", final_marker))
        if committed:   # refinement 7: cold-boot the flushed final, CONTINUE, read back (no save)
            mons = codec.decode_saved_party(final[:oracle.CART], layout, copy_name="primary")["mons"]
            markers[side].append(("TRADE_RELOAD", {"frame": 210, "snapshot_sha256": final_marker["snapshot_sha256"],
                "cartram_sha256": final_marker["cartram_sha256"], "party_keys": [codec.key(mon) for mon in mons],
                "dex": oracle._dex(final, layout)}))
        bottom, top = symbols["wStackBottom"], symbols["wStackTop"]
        phases = []
        for phase in oracle.PHASES:
            visited = phase == "wait" or committed and phase in ("trade_animation", "native_save") or (
                phase == "evolution_animation" and scenario == "gen2_trade_evolve" and side == "b")
            start_name, end_name, first, last = {
                "wait": ("SlinkTradeWaitApply", "SlinkTradeApplyPickup" if committed else "SlinkTradeExit", 115, 120),
                "trade_animation": ("TradeAnimation" if side == "a" else "TradeAnimationPlayer2", "AddTempmonToParty", 130, 140),
                "native_save": ("SaveAfterLinkTrade", "SlinkTradePublishDone", 160, 170),
                "evolution_animation": ("EvolutionAnimation", "SaveAfterLinkTrade", 155, 160),
            }[phase]
            entry = {"frame": first, "site": site(symbols, start_name)}
            end = {"frame": last, "site": site(symbols, end_name)}
            phases.append({"phase": phase, "visited": visited, "start": entry if visited else None,
                "end": end if visited else None, "samples": [{"frame": first, "sp": bottom.address + 61,
                "stack_addr": bottom.address + 60, "pc": symbols["SlinkTradeWaitApply"].address,
                "rom_bank": symbols["SlinkTradeWaitApply"].bank}] if visited else []})
        armed_end = min(top.address, bottom.address + 95)   # stack witness v2: [wStackBottom, floor + 64)
        markers[side].append(("TRADE_STACK", {"domain": "System Bus", "stack_bank": bottom.bank,
            "stack_start": bottom.address, "stack_end": top.address, "armed_start": bottom.address,
            "armed_end": armed_end, "floor": bottom.address + 32, "low_water_state": "exact",
            "canary": {"address": bottom.address + 200, "sp": bottom.address + 201, "hit": True, "frame": 105},
            "armed_count": armed_end - bottom.address + 1,
            "hook_failures": 0, "phases": phases,
            "continuous": True, "registration_complete_before_first_phase": True,
            "coverage_started": {"frame": 105, "site": "harness:trade_go"},
            "coverage_ended": {"frame": 200, "site": "harness:before_report"},
            "global_observations": sum(len(phase["samples"]) for phase in phases),
            "global_low_water": deepcopy(phases[0]["samples"][0]),
            "registration_events": [{"action": "arm", "address": address, "frame": 104, "hook_id": f"stack-{address}"}
                                    for address in range(bottom.address, armed_end + 1)]}))
    if not committed and scenario != "gen2_trade_reset_commit":
        kind = {"gen2_trade_decline_new": "decline", "gen2_trade_timeout": "timeout",
                "gen2_trade_reset_wait": "reset_wait", "gen2_trade_refuse_item": "refuse_item",
                "gen2_trade_refuse_contest": "contest", "gen2_trade_refuse_unsaved": "unsaved"}[scenario]
        active = "b" if kind in ("decline", "contest", "unsaved") else "a"
        symbols = syms[active]
        before_name, after_name = {"decline": ("SlinkTradePublishDone", "SlinkTradeExit"),
            "timeout": ("SlinkTradeWaitApply.wait", "SlinkTradeExit"),
            "reset_wait": ("Reset", "StartTitleScreen"), "refuse_item": ("SlinkTradeItemAllowed", "SlinkTradeExit"),
            "contest": ("SlinkTradeCheckOwnSlot.refuseParty", "SlinkTradeExit"),
            "unsaved": ("SlinkTradePublishDone", "SlinkTradeExit")}[kind]
        command = {"decline": 3, "timeout": 2, "reset_wait": 2, "refuse_item": 1, "contest": 3, "unsaved": 3}[kind]
        old_lease = lease(command, tokens[active], generations[active], 0, True)
        new_lease = bytearray.fromhex(old_lease)
        if kind in ("decline", "unsaved"):
            new_lease[5], new_lease[8] = 7, 1
        if kind == "reset_wait":
            new_lease = bytearray(16)
        bound = oracle._apply_frames(ROOT)   # SLINK_TRADE_APPLY_FRAMES, 3600 since 67143736
        last = 115 + bound + 15 if kind == "timeout" else 150 if kind == "reset_wait" else 116
        registers = {"A": 1} if kind in ("decline", "unsaved") else {"B": bound >> 8, "C": bound & 255} if kind == "timeout" else {
            "A": before[active]["held_item"]} if kind == "refuse_item" else {}
        markers[active].append(("TRADE_CONTROL", {"kind": "d3" if kind == "refuse_item" else kind,   # driver's D3 name
            "before": {"frame": 115, "site": site(symbols, before_name), "registers": registers,
                       "slot": 0, "lease_hex": old_lease},
            "after": {"frame": last, "site": site(symbols, after_name),
                      "registers": {"B": 0, "C": 0} if kind == "timeout" else {}, "lease_hex": new_lease.hex()}}))
        control = get({"markers": markers}, active, "TRADE_CONTROL")
        if kind == "contest":
            control["before"]["wram"] = {"wStatusFlags2": 0x04}   # STATUSFLAGS2_BUG_CONTEST_TIMER_F
        if kind == "unsaved":
            control["save"] = {"frame": 112, "site": site(symbols, "SlinkTradeResponderSave")}
        if kind == "timeout":
            for rows in markers.values():
                next(row for name, row in rows if name == "TRADE_FINAL")["frame"] = last + 85
                next(row for name, row in rows if name == "TRADE_STACK")["coverage_ended"]["frame"] = last + 85
        stack = next(row for name, row in markers[active] if name == "TRADE_STACK")
        stack["phases"][0]["end"] = {"frame": last, "site": site(symbols, "SlinkTradeExit")}
        if kind == "reset_wait":
            stack["phases"][0]["end"] = {"frame": 115, "site": site(symbols, "Reset")}
    links = {"links": [{"area_id": "route_29", "status": "alive", **{
        side: {"key": before[side]["key"], "species": offered_species[side], "level": before[side]["level"]}
        for side in ("a", "b")}}],
        "player_identity": {"a": {"ot_id": 1200, "trainer_name": "MODEL-A"},
                            "b": {"ot_id": 1201, "trainer_name": "MODEL-B"}},
        "artifact_kind": "overlay", "rom_type": "Crystal",
        "game_id": "gen2_gsc", "rules": {"species_lock": True, "type_lock": False},
        "area_states": {"route_29": "linked"}, "pending_captures": {}, "mon_stats": {},
        "pokeballs_obtained": {"a": True, "b": True}, "trainer_names": {"a": "MODEL-A", "b": "MODEL-B"},
        "pending_memorials": {"a": [], "b": []}, "retry_areas": {"a": [], "b": []},
        "bonus_keys": {"a": [], "b": []}, "pending_bonus": {"a": [], "b": []}, "run_over": False,
        "attempts_count": {"a": 0, "b": 0}, "rebuild_pending": {"a": None, "b": None}}
    baseline_links = tmp_path / "baseline-links.json"
    baseline_links.write_text(json.dumps(links))
    if committed:
        row = links["links"][0]
        row["a"], row["b"] = row["b"], row["a"]
        for side in ("a", "b"):
            row[side].update(key=projected[side]["key"], species=projected[side]["to_species"])
    (tmp_path / "links.json").write_text(json.dumps(links))
    events = []
    if committed:
        for number, side in enumerate(("a", "b"), 1):
            events.append({"seq": number, "source": "server_dispatch", "evidence_class": "HARNESS_ONLY_OVERLAY",
                "run_id": manifest["run_id"], "scenario": scenario, "player": side,
                "message": {"event": "trade_done", "token": "t1", "new_key": projected[side]["key"],
                            "new_species": projected[side]["to_species"], "uncertain": False},
                "outcome": {"dispatch": "returned", "commands": []}})
    event_path = tmp_path / "events.jsonl"
    event_path.write_text("\n".join(json.dumps(event) for event in events))
    (tmp_path / "server.log").write_text("trade complete (token t1)" if committed else "")
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    return {"markers": markers, "kwargs": {"data_dir": tmp_path, "baseline_saves": baseline_paths,
        "overlay_provenance": {"manifest_path": str(manifest_path), "manifest_sha256": digest(manifest_path.read_bytes()),
                               "players": refs},
        "expected_case": {"scenario": scenario, "variant": variant, "fixture_sha256": {"a": "a" * 64, "b": "a" * 64},
                          "required_phases": ["wait", "trade_animation", "native_save"] if committed else ["wait"]},
        "transaction_evidence": {"schema": "gen2-duo-trade-transaction-v1", "tokens": tokens, "server_token": "t1",
            "baseline_links": {"path": str(baseline_links), "sha256": digest(baseline_links.read_bytes())},
            "events": {"path": str(event_path), "sha256": digest(event_path.read_bytes())}}}}


@pytest.mark.parametrize("variant", ["cc", "gs", "cg"])
def test_native_trade_images_and_server_agree(tmp_path, sources, variant):
    case = make_case(tmp_path, sources, variant)
    facts = []
    assert invoke(case, facts.append) is None
    assert facts[0]["status"] == "committed"
    assert facts[0]["players"]["a"]["stack"]["evolution_animation"]["visited"] is False


@pytest.mark.parametrize("scenario", ["gen2_trade_decline_new", "gen2_trade_timeout", "gen2_trade_reset_wait", "gen2_trade_refuse_item"])
def test_negative_cases_preserve_saved_gameplay(tmp_path, sources, scenario):
    case = make_case(tmp_path, sources, scenario=scenario)
    assert invoke(case) is None


@pytest.mark.parametrize("scenario", ["gen2_trade_decline_new", "gen2_trade_timeout", "gen2_trade_reset_wait", "gen2_trade_refuse_item"])
def test_no_op_run_cannot_qualify_negative_control(tmp_path, sources, scenario):
    case = make_case(tmp_path, sources, scenario=scenario)
    for side in ("a", "b"):
        case["markers"][side] = [(name, row) for name, row in case["markers"][side] if name != "TRADE_CONTROL"]
    with pytest.raises(RuntimeError, match="no observed native control"):
        invoke(case)


def early_d3(case):
    receipt = get(case, "a", "RECEIPT")
    receipt["visit_state"] = "query"
    case["markers"]["a"] = [(name, row) for name, row in case["markers"]["a"] if name != "TRADE_OFFER"]
    receipt = get(case, "b", "RECEIPT")
    receipt.update(visit_state="none", token=None, generation=None)
    case["markers"]["b"] = [(name, row) for name, row in case["markers"]["b"] if name != "TRADE_OFFER"]
    for phase in get(case, "b", "TRADE_STACK")["phases"]:
        phase.update(visited=False, start=None, end=None, samples=[])
    case["kwargs"]["transaction_evidence"]["tokens"]["b"] = None
    case["kwargs"]["transaction_evidence"]["server_token"] = None


def test_early_item_refusal_has_no_fabricated_offer_or_peer_visit(tmp_path, sources):
    case = make_case(tmp_path, sources, scenario="gen2_trade_refuse_item")
    early_d3(case)
    assert invoke(case) is None


def test_inactive_peer_cannot_hide_a_native_call(tmp_path, sources):
    case = make_case(tmp_path, sources, scenario="gen2_trade_refuse_item")
    early_d3(case)
    case["markers"]["b"].append(("TRADE_NATIVE_CALL", {"frame": 117, "symbol": "SaveAfterLinkTrade"}))
    with pytest.raises(RuntimeError, match="inactive peer"):
        invoke(case)


@pytest.mark.parametrize("fault", ["decline-result", "timeout-counter", "timeout-site", "timeout-short",
                                   "reset-lease", "item-register", "control-token", "control-late"])
def test_negative_control_requires_actual_native_observations(tmp_path, sources, fault):
    scenario = {"decline-result": "gen2_trade_decline_new", "reset-lease": "gen2_trade_reset_wait",
                "item-register": "gen2_trade_refuse_item"}.get(fault, "gen2_trade_timeout")
    case = make_case(tmp_path, sources, scenario=scenario)
    side = "b" if scenario == "gen2_trade_decline_new" else "a"
    control = get(case, side, "TRADE_CONTROL")
    if fault == "decline-result":
        control["before"]["registers"]["A"] = 0
    elif fault == "timeout-counter":
        control["before"]["registers"].update(B=7, C=7)
    elif fault == "timeout-site":
        symbols = parse_symbols((ROOT / "data/gen2/crystal_slink.sym").read_text())
        control["before"]["site"] = site(symbols, "SlinkTradeWaitApply")
    elif fault == "timeout-short":
        control["after"]["frame"] = control["before"]["frame"] + 1799
    elif fault == "reset-lease":
        control["after"]["lease_hex"] = control["before"]["lease_hex"]
    elif fault == "item-register":
        control["before"]["registers"]["A"] = 0
    elif fault == "control-token":
        raw = bytearray.fromhex(control["before"]["lease_hex"])
        raw[12] ^= 1
        control["before"]["lease_hex"] = raw.hex()
    else:
        control["after"]["frame"] = get(case, side, "TRADE_FINAL")["frame"] + 1
    with pytest.raises(RuntimeError):
        invoke(case)


def test_null_server_token_cannot_hide_dispatched_offer(tmp_path, sources):
    case = make_case(tmp_path, sources, scenario="gen2_trade_refuse_item")
    early_d3(case)
    path = tmp_path / "events.jsonl"
    path.write_text(json.dumps({"seq": 1, "source": "server_dispatch", "evidence_class": "HARNESS_ONLY_OVERLAY",
        "run_id": "MODEL-trade", "scenario": "gen2_trade_refuse_item", "player": "a",
        "message": {"event": "trade_offer", "slot": 0}, "outcome": {"dispatch": "returned", "commands": []}}))
    case["kwargs"]["transaction_evidence"]["events"]["sha256"] = digest(path.read_bytes())
    with pytest.raises(RuntimeError, match="null server token"):
        invoke(case)


def test_reset_after_commit_has_no_optimistic_verdict(tmp_path, sources):
    case = make_case(tmp_path, sources, scenario="gen2_trade_reset_commit")
    with pytest.raises(RuntimeError, match="UNCERTAIN"):
        invoke(case)


@pytest.mark.parametrize("tag", ["RECEIPT", "TRADE_BASELINE", "TRADE_READY", "TRADE_GO", "TRADE_OFFER", "TRADE_APPLY_PICKUP",
                                "TRADE_PRE_REMOVE", "TRADE_DONE", "TRADE_NATIVE_SAVE", "TRADE_STACK", "TRADE_FINAL"])
def test_required_markers_cannot_be_dropped(tmp_path, sources, tag):
    case = make_case(tmp_path, sources)
    case["markers"]["a"] = [(name, row) for name, row in case["markers"]["a"] if name != tag]
    with pytest.raises(RuntimeError):
        invoke(case)


@pytest.mark.parametrize("fault", ["duplicate", "token", "generation", "snapshot-domain", "snapshot-address",
                                   "snapshot-bytes", "live-bytes", "native-call", "stack-registration", "stack-frame-only",
                                   "stack-margin", "stack-phase", "native-save-late", "native-save-reused",
                                   "server-link", "server-done", "server-log", "overlay-hash", "role"])
def test_torn_or_fabricated_evidence_refused(tmp_path, sources, fault):
    case = make_case(tmp_path, sources)
    if fault == "duplicate":
        case["markers"]["a"].append(("RECEIPT", get(case, "a", "RECEIPT")))
    elif fault in ("token", "generation"):
        value = get(case, "a", "TRADE_APPLY_PICKUP")
        raw = bytearray.fromhex(value["lease_hex"])
        raw[12 if fault == "token" else 6] ^= 1
        value["lease_hex"] = raw.hex()
    elif fault.startswith("snapshot-") or fault == "live-bytes":
        value = get(case, "a", "TRADE_PRE_REMOVE")["live" if fault == "live-bytes" else "frozen"]
        if fault == "snapshot-domain":
            value["domain"] = "ROM"
        elif fault == "snapshot-address":
            value["spans"][0]["address"] -= 48
        else:
            value["spans"][0]["hex"] = "00" + value["spans"][0]["hex"][2:]
    elif fault == "native-call":
        case["markers"]["a"] = [(name, row) for name, row in case["markers"]["a"]
                                  if not (name == "TRADE_NATIVE_CALL" and row["symbol"] == "SaveAfterLinkTrade")]
    elif fault.startswith("stack-"):
        value = get(case, "a", "TRADE_STACK")
        if fault == "stack-registration":
            value["armed_count"] -= 1
        elif fault == "stack-frame-only":
            value["phases"][0]["samples"][0].pop("stack_addr")
        elif fault == "stack-margin":
            sample = value["phases"][0]["samples"][0]
            sample.update(sp=value["stack_start"] + 31, stack_addr=value["stack_start"] + 30)
        else:
            value["phases"][1].update(visited=False, samples=[])
    elif fault == "native-save-late":
        get(case, "a", "TRADE_NATIVE_SAVE")["frame"] += 1
    elif fault == "native-save-reused":
        get(case, "a", "TRADE_NATIVE_SAVE")["snapshot_path"] = get(case, "a", "TRADE_FINAL")["snapshot_path"]
    elif fault == "server-link":
        path = tmp_path / "links.json"
        value = json.loads(path.read_text())
        value["links"][0]["a"]["key"] = "wrong"
        path.write_text(json.dumps(value))
    elif fault == "server-done":
        path = tmp_path / "events.jsonl"
        path.write_text(path.read_text().splitlines()[0])
        case["kwargs"]["transaction_evidence"]["events"]["sha256"] = digest(path.read_bytes())
    elif fault == "server-log":
        (tmp_path / "server.log").write_text("")
    elif fault == "overlay-hash":
        get(case, "a", "RECEIPT")["rom_sha1"] = "0" * 40
    else:
        get(case, "b", "RECEIPT")["role"] = 0
    with pytest.raises(RuntimeError):
        invoke(case)


@pytest.mark.parametrize("fault", ["survivor", "received", "dex", "dex-backup", "negative-save", "D3-valid-item"])
def test_independent_saved_bytes_cannot_be_replaced_by_pass_flags(tmp_path, sources, fault):
    scenario = "gen2_trade_refuse_item" if fault == "D3-valid-item" else "gen2_trade_timeout" if fault == "negative-save" else "gen2_trade_new"
    case = make_case(tmp_path, sources, scenario=scenario)
    layout = sources["crystal"]["layout"]
    if fault == "D3-valid-item":
        # A normal untouched pair mislabeled D3 cannot qualify refusal of an invalid item.
        case = make_case(tmp_path, sources, scenario="gen2_trade_timeout")
        case["kwargs"]["expected_case"]["scenario"] = "gen2_trade_refuse_item"
        for side in ("a", "b"):
            get(case, side, "RECEIPT")["case"] = "gen2_trade_refuse_item"
        manifest_ref = case["kwargs"]["overlay_provenance"]
        path = Path(manifest_ref["manifest_path"])
        manifest = json.loads(path.read_text())
        manifest["scenario"] = "gen2_trade_refuse_item"
        path.write_text(json.dumps(manifest))
        manifest_ref["manifest_sha256"] = digest(path.read_bytes())
    else:
        tags = ["TRADE_FINAL"] if fault == "negative-save" else ["TRADE_NATIVE_SAVE", "TRADE_FINAL"]
        for tag in tags:
            marker = get(case, "a", tag)
            path = Path(marker["snapshot_path"])
            raw = bytearray(path.read_bytes())
            if fault.startswith("dex"):
                symbol = "wPokedexCaught"
                value = bytearray(oracle._saved(raw, layout, symbol, 32, "primary"))
                value[20] ^= 8
                if fault == "dex-backup":
                    region = next(r for r in layout.regions if r.name == "pokemon")
                    start = region.backup + layout.addresses[symbol] - layout.addresses["wPokemonData"]
                    raw[start:start + 32] = value
                else:
                    put(raw, layout, symbol, value)
                raw = checksum(raw, layout)
            else:
                party = oracle._party(bytes(raw), layout)
                slot = 1 if fault == "received" else 0
                blob = bytearray.fromhex(party[slot]["blob_hex"])
                blob[layout.constants["MON_HAPPINESS"]] ^= 1
                party[slot]["blob_hex"] = blob.hex()
                raw = party_save(raw, layout, party)
            marker.update(image(path, bytes(raw), marker["frame"]))
    with pytest.raises(RuntimeError):
        invoke(case)


def test_frame_only_boundary_cannot_claim_animation_coverage(tmp_path, sources):
    case = make_case(tmp_path, sources)
    rows = get(case, "a", "TRADE_STACK")["phases"]
    rows[1]["start"] = deepcopy(rows[0]["start"])
    rows[1]["samples"][0]["frame"] = rows[0]["start"]["frame"]
    with pytest.raises(RuntimeError, match="boundary"):
        invoke(case)


def test_runner_required_unvisited_evolution_cannot_pass(tmp_path, sources):
    case = make_case(tmp_path, sources)
    case["kwargs"]["expected_case"]["required_phases"].append("evolution_animation")
    with pytest.raises(RuntimeError, match="unvisited"):
        invoke(case)


@pytest.mark.parametrize("payload", [None, [], {"a": "RESULT: PASS", "b": "RESULT: PASS"}])
def test_client_pass_is_not_a_trade_witness(payload):
    with pytest.raises(RuntimeError):
        oracle.check_trade_witness(payload)


@pytest.mark.parametrize("fault", ["late-start", "early-end", "late-registration", "missing-address",
                                   "duplicate-address", "duplicate-hook", "rearm", "disarm", "failure"])
def test_continuous_registration_is_proved_beyond_boolean_claims(tmp_path, sources, fault):
    case = make_case(tmp_path, sources)
    stack = get(case, "a", "TRADE_STACK")
    if fault == "late-start":
        stack["coverage_started"]["frame"] = stack["phases"][0]["start"]["frame"] + 1
    elif fault == "early-end":
        stack["coverage_ended"]["frame"] = stack["phases"][3]["end"]["frame"] - 1
    elif fault == "late-registration":
        stack["registration_events"][-1]["frame"] = stack["phases"][0]["start"]["frame"] + 1
    elif fault == "missing-address":
        stack["registration_events"].pop()
    elif fault == "duplicate-address":
        stack["registration_events"][-1]["address"] = stack["registration_events"][0]["address"]
    elif fault == "duplicate-hook":
        stack["registration_events"][-1]["hook_id"] = stack["registration_events"][0]["hook_id"]
    else:
        event = dict(stack["registration_events"][0], action=fault, frame=125)
        stack["registration_events"].append(event)
    with pytest.raises(RuntimeError):
        invoke(case)


@pytest.mark.parametrize("field", ["rules", "area_states", "pending_captures", "pokeballs_obtained",
                                   "trainer_names", "pending_memorials", "retry_areas", "bonus_keys",
                                   "pending_bonus", "run_over", "attempts_count", "rebuild_pending", "game_id"])
def test_trade_cannot_corrupt_other_durable_server_gameplay(tmp_path, sources, field):
    case = make_case(tmp_path, sources)
    path = tmp_path / "links.json"
    payload = json.loads(path.read_text())
    payload[field] = {"unexpected": "corruption"}
    path.write_text(json.dumps(payload))
    with pytest.raises(RuntimeError, match="server gameplay"):
        invoke(case)


def test_derived_mon_stats_cache_refresh_is_allowed(tmp_path, sources):
    case = make_case(tmp_path, sources)
    path = tmp_path / "links.json"
    payload = json.loads(path.read_text())
    payload["mon_stats"] = {payload["links"][0]["a"]["key"]: {"cached": "new snapshot"}}
    path.write_text(json.dumps(payload))
    assert invoke(case) is None


def test_source_save_inventory_requires_explicit_new_field_policy():
    import ast
    tree = ast.parse((ROOT / "server/state.py").read_text(encoding="utf-8"))
    save = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "_save")
    payload = next(node.value for node in ast.walk(save) if isinstance(node, ast.Assign)
                   and any(isinstance(target, ast.Name) and target.id == "payload" for target in node.targets))
    assert {key.value for key in payload.keys} == (oracle.STABLE_SERVER_FIELDS | oracle.TRADE_SERVER_FIELDS
                                                  | {"links", "mon_stats"})


@pytest.mark.parametrize(("field", "before", "after"), [
    ("pending_trade", None, {"token": "t1", "phase": "uncertain"}),
    ("pending_trade", {"token": "t1", "phase": "applying"}, None),
    ("trade_token", 3, 2),
    ("trade_token", 1, "2"),
])
def test_durable_trade_fsm_must_be_settled_and_monotonic(tmp_path, sources, field, before, after):
    case = make_case(tmp_path, sources)
    for name, value in (("baseline-links.json", before), ("links.json", after)):
        path = tmp_path / name
        payload = json.loads(path.read_text())
        payload[field] = value
        path.write_text(json.dumps(payload))
    ref = case["kwargs"]["transaction_evidence"]["baseline_links"]
    ref["sha256"] = digest((tmp_path / "baseline-links.json").read_bytes())
    with pytest.raises(RuntimeError, match="pending_trade unsettled or trade_token"):
        invoke(case)
    for name, value in (("baseline-links.json", 3 if field == "trade_token" else None),
                        ("links.json", 5 if field == "trade_token" else None)):
        path = tmp_path / name
        payload = json.loads(path.read_text())
        payload[field] = value
        path.write_text(json.dumps(payload))
    ref["sha256"] = digest((tmp_path / "baseline-links.json").read_bytes())
    assert invoke(case) is None


def test_unknown_server_field_is_not_silently_classified_as_cache(tmp_path, sources):
    case = make_case(tmp_path, sources)
    path = tmp_path / "links.json"
    payload = json.loads(path.read_text())
    payload["party_keys"] = {"a": ["unexpected"], "b": []}
    path.write_text(json.dumps(payload))
    with pytest.raises(RuntimeError, match="server gameplay"):
        invoke(case)


def test_reset_commit_refusal_exposes_uncertain_status_without_success():
    with pytest.raises(oracle.TradeUncertain) as error:
        oracle.trade_oracle({}, data_dir=None, baseline_saves=None, overlay_provenance=None,
                            transaction_evidence={}, expected_case={"scenario": "gen2_trade_reset_commit"})
    assert error.value.status is oracle.TradeStatus.UNCERTAIN
    assert error.value.facts["status"] == "uncertain"


@pytest.mark.parametrize("fault", ["gap-overflow", "late", "unrelated-address", "not-global-minimum", "missing", "zero-count"])
def test_global_low_water_covers_gaps_between_named_phases(tmp_path, sources, fault):
    case = make_case(tmp_path, sources)
    stack = get(case, "a", "TRADE_STACK")
    low = stack["global_low_water"]
    if fault == "gap-overflow":
        low.update(frame=125, sp=stack["stack_start"] + 25, stack_addr=stack["stack_start"] + 24)
    elif fault == "late":
        low["frame"] = stack["coverage_ended"]["frame"] + 1
    elif fault == "unrelated-address":
        low["stack_addr"] = low["sp"] + 20
    elif fault == "not-global-minimum":
        low.update(sp=low["sp"] + 1, stack_addr=low["stack_addr"] + 1)
    elif fault == "zero-count":
        stack["global_observations"] = 0
    else:
        stack.pop("global_low_water")
    with pytest.raises(RuntimeError):
        invoke(case)


@pytest.mark.parametrize("symbol", ["wItems", "wEventFlags", "sBox1"])
def test_native_trade_cannot_hide_rechecksummed_bag_flag_or_box_corruption(tmp_path, sources, symbol):
    case = make_case(tmp_path, sources)
    layout = sources["crystal"]["layout"]
    for tag in ("TRADE_NATIVE_SAVE", "TRADE_FINAL"):
        marker = get(case, "a", tag)
        path = Path(marker["snapshot_path"])
        raw = bytearray(path.read_bytes())
        if symbol.startswith("w"):
            byte = oracle._saved(raw, layout, symbol, 1, "primary")[0]
            put(raw, layout, symbol, bytes([byte ^ 1]))
        else:
            offset = layout.sram_banks[symbol] * 0x2000 + layout.addresses[symbol] - 0xA000
            raw[offset] ^= 1
        marker.update(image(path, checksum(raw, layout), marker["frame"]))
    with pytest.raises(RuntimeError, match="saved byte"):
        invoke(case)


def rescenario(case, scenario):
    """Re-bind the frozen admission manifest to another scenario; returns its reference."""
    manifest_ref = case["kwargs"]["overlay_provenance"]
    path = Path(manifest_ref["manifest_path"])
    manifest = json.loads(path.read_text())
    manifest["scenario"] = scenario
    path.write_text(json.dumps(manifest))
    manifest_ref["manifest_sha256"] = digest(path.read_bytes())
    return manifest_ref


def reset_case(tmp_path, sources, outcome="committed", variant="cc", *, unentered=False):
    from tests.unit import test_gen2_trade_reconciliation as recon_model
    case = make_case(tmp_path, sources, variant)
    scenario = "gen2_trade_reset_commit"
    case["kwargs"]["expected_case"].update(scenario=scenario, required_phases=["wait"])
    manifest_ref = rescenario(case, scenario)
    old_keys, final_keys, old_parties, final_parties = {}, {}, {}, {}
    for side in ("a", "b"):
        receipt = get(case, side, "RECEIPT")
        receipt["case"] = scenario
        symbols = parse_symbols(Path(manifest_ref["players"][side]["sym_path"]).read_text())
        layout = sources[receipt["title"]]["layout"]
        baseline = Path(get(case, side, "TRADE_BASELINE")["snapshot_path"]).read_bytes()
        old_mons = codec.decode_saved_party(baseline[:oracle.CART], layout, copy_name="primary")["mons"]
        old_parties[side] = [codec.key(mon) for mon in old_mons]
        old_keys[side] = old_parties[side][0]
        rolled = outcome == "rolled_back" or outcome == "mixed" and side == "b"
        reset = side == "a" or rolled and not unentered
        if rolled:
            final_marker = get(case, side, "TRADE_FINAL")
            before_image = Path(get(case, side, "TRADE_FORCED_SAVE")["snapshot_path"]).read_bytes()
            final_marker.update(image(Path(final_marker["snapshot_path"]), before_image, 200))
            forbidden = {"TRADE_NATIVE_CALL", "TRADE_PRE_REMOVE", "TRADE_DONE", "TRADE_NATIVE_SAVE", "TRADE_RELOAD"}
            case["markers"][side] = [(tag, row) for tag, row in case["markers"][side] if tag not in forbidden]
            for phase in get(case, side, "TRADE_STACK")["phases"][1:]:
                phase.update(visited=False, samples=[], start=None, end=None)
        if unentered and side == "b":
            receipt["visit_state"] = "unentered"
            case["markers"][side] = [(tag, row) for tag, row in case["markers"][side] if tag != "TRADE_APPLY_PICKUP"]
            get(case, side, "TRADE_STACK")["phases"][0]["end"] = {"frame": 120, "site": site(symbols, "SlinkTradeExit")}
        else:
            entry = {"frame": 121, "site": site(symbols, "SlinkTradeCommit"),
                     "lease_hex": lease(5, receipt["token"], (receipt["generation"] + 1) % 256, 0, True)}
            case["markers"][side].append(("TRADE_COMMIT_ENTRY", entry))
            if reset:
                case["markers"][side] = [(tag, row) for tag, row in case["markers"][side]
                                          if tag not in ("TRADE_DONE", "TRADE_NATIVE_SAVE")]
                reset_frame = 122 if rolled else 166
                before = {"frame": reset_frame, "site": site(symbols, "Reset"), "lease_hex": entry["lease_hex"]}
                after = {"frame": 180, "site": site(symbols, "StartTitleScreen"), "lease_hex": bytes(16).hex()}
                case["markers"][side].append(("TRADE_CONTROL", {"kind": "reset_commit", "commit": entry,
                                                               "before": before, "after": after}))
                if not rolled:
                    get(case, side, "TRADE_STACK")["phases"][3]["end"] = {"frame": reset_frame, "site": site(symbols, "Reset")}
        raw = Path(get(case, side, "TRADE_FINAL")["snapshot_path"]).read_bytes()
        mons = codec.decode_saved_party(raw[:oracle.CART], layout, copy_name="primary")["mons"]
        final_parties[side] = [codec.key(mon) for mon in mons]
        final_keys[side] = old_keys[side] if rolled else final_parties[side][-1]
    model = recon_model._resolved({"a": "none", "b": "none"}) if outcome == "rolled_back" else recon_model._committed()
    mapping = {**{recon_model.OLD[s]: old_keys[s] for s in ("a", "b")},
               **({recon_model.NEW[s]: final_keys[s] for s in ("a", "b")} if outcome != "rolled_back" else {}), "t7": "t1", "fixture": "MODEL-trade"}
    def replace(value):
        if isinstance(value, dict):
            return {key: replace(item) for key, item in value.items()}
        if isinstance(value, list):
            return [replace(item) for item in value]
        return mapping.get(value, value) if isinstance(value, str) else value
    model = replace(model)
    for event in model["journal"]:
        message, side = event["message"], event["player"]
        if "party" in message:
            key = message["party"][0]["key"]
            keys = final_parties[side] if key == final_keys[side] else old_parties[side]
            message["party"] = [{"key": value} for value in keys]
    if outcome == "rolled_back":
        (tmp_path / "links.json").write_bytes((tmp_path / "baseline-links.json").read_bytes())
        (tmp_path / "server.log").write_text("trade rolled back (token t1)")
    journal = tmp_path / "events.jsonl"
    journal.write_text("\n".join(json.dumps(event) for event in model["journal"]))
    case["kwargs"]["transaction_evidence"]["events"]["sha256"] = digest(journal.read_bytes())
    refs = {}
    for name in ("events", "status"):
        path = tmp_path / f"reconciliation-{name}.json"
        path.write_text(json.dumps(model[name]))
        refs[name] = {"path": str(path), "sha256": digest(path.read_bytes())}
    (tmp_path / "events.json").write_text(json.dumps(model["events"]))
    case["kwargs"]["transaction_evidence"]["reconciliation"] = refs
    return case


@pytest.mark.parametrize("variant", ["cc", "gs", "cg"])
def test_reset_commit_requires_independent_saves_and_real_reconciliation(tmp_path, sources, variant):
    case = reset_case(tmp_path, sources, variant=variant)
    facts = []
    assert invoke(case, facts.append) is None
    assert facts[0]["status"] == "committed"
    assert facts[0]["reconciliation"]["outcome"] == "committed"
    assert facts[0]["players"]["a"]["stack"]["native_save"]["completed"] is False


@pytest.mark.parametrize("unentered", [False, True])
def test_reset_before_save_can_only_qualify_proved_rollback(tmp_path, sources, unentered):
    case = reset_case(tmp_path, sources, "rolled_back", unentered=unentered)
    facts = []
    assert invoke(case, facts.append) is None
    assert facts[0]["status"] == "unchanged"
    assert facts[0]["reconciliation"]["outcome"] == "rolled_back"


def test_mixed_reset_saved_outcomes_never_pass(tmp_path, sources):
    case = reset_case(tmp_path, sources, "mixed")
    with pytest.raises(RuntimeError):
        invoke(case)


def alter_reset_clock(case, layout, *, symbol="wGameTimeFrames", corrupt_checksum=False):
    marker = get(case, "a", "TRADE_FINAL")
    path = Path(marker["snapshot_path"])
    raw = bytearray(path.read_bytes())
    for region in layout.regions:
        base = layout.addresses[oracle.REGIONS[region.name]]
        address = layout.addresses[symbol]
        if base <= address < base + region.length:
            raw[region.backup + address - base] ^= 1
            break
    raw = bytearray(checksum(raw, layout))
    if corrupt_checksum:
        raw[layout.checksum_offsets["backup"]] ^= 1
    marker.update(image(path, bytes(raw), marker["frame"]))
    get(case, "a", "TRADE_RELOAD").update(snapshot_sha256=marker["snapshot_sha256"], cartram_sha256=marker["cartram_sha256"])


@pytest.mark.parametrize("variant", ["cc", "gs", "cg"])
def test_reset_continue_backup_clock_difference_is_comparison_only(tmp_path, sources, variant):
    case = reset_case(tmp_path, sources, variant=variant)
    layout = sources[get(case, "a", "RECEIPT")["title"]]["layout"]
    alter_reset_clock(case, layout)
    raw = Path(get(case, "a", "TRADE_FINAL")["snapshot_path"]).read_bytes()
    facts = []
    invoke(case, facts.append)
    assert facts[0]["players"]["a"]["backup_clock_normalized"] is True
    assert Path(get(case, "a", "TRADE_FINAL")["snapshot_path"]).read_bytes() == raw


@pytest.mark.parametrize("fault", ["nonclock", "checksum", "normal-trade"])
def test_clock_exception_cannot_hide_other_corruption_or_normal_trade_drift(tmp_path, sources, fault):
    case = make_case(tmp_path, sources) if fault == "normal-trade" else reset_case(tmp_path, sources)
    alter_reset_clock(case, sources["crystal"]["layout"],
                      symbol="wEventFlags" if fault == "nonclock" else "wGameTimeFrames", corrupt_checksum=fault == "checksum")
    with pytest.raises(RuntimeError, match="checksum|copy"):
        invoke(case)


@pytest.mark.parametrize("variant", ["cc", "gs", "cg"])
def test_evolve_case_commits_the_disclosed_plant_and_b_evolves_natively(tmp_path, sources, variant):
    case = make_case(tmp_path, sources, variant, scenario="gen2_trade_evolve")
    facts = []
    assert invoke(case, facts.append) is None
    players = facts[0]["players"]
    assert facts[0]["status"] == "committed" and players["b"]["species_id"] == 94   # HAUNTER -> GENGAR
    assert players["b"]["stack"]["evolution_animation"]["visited"] is True
    assert players["a"]["stack"]["evolution_animation"]["visited"] is False


def _write(case):
    return get(case, "a", "HARNESS_WRITE")


def _edit_write(case, **changes):
    """Change the write AND its receipt scope, so the deeper O-31 check is the one exercised."""
    _write(case).update(changes)
    scope = get(case, "a", "RECEIPT")["harness_write_scopes"][0]
    scope.update({key: value for key, value in changes.items() if key in scope})


def _drop_plant(case):
    case["markers"]["a"] = [(tag, row) for tag, row in case["markers"]["a"] if tag != "HARNESS_WRITE"]
    get(case, "a", "RECEIPT").update(harness_write_scopes=[], harness_exception=None)


def _swap(case, first, second):
    rows = case["markers"]["a"]
    i, j = (next(n for n, (tag, _) in enumerate(rows) if tag == name) for name in (first, second))
    rows[i], rows[j] = rows[j], rows[i]


O31_FAULTS = {
    "d3_undisclosed_mail": ("gen2_trade_refuse_item", _drop_plant, "missing or repeated"),
    "d3_scopes_hidden": ("gen2_trade_refuse_item",
                         lambda c: get(c, "a", "RECEIPT").update(harness_write_scopes=[]), "disclose exactly"),
    "d3_no_exception": ("gen2_trade_refuse_item",
                        lambda c: get(c, "a", "RECEIPT").update(harness_exception=None), "disclose exactly"),
    "d3_wrong_slot": ("gen2_trade_refuse_item", lambda c: _write(c).update(slot=1), "offered linked mon"),
    "d3_wrong_address": ("gen2_trade_refuse_item", lambda c: _edit_write(c, address=_write(c)["address"] + 1),
                         "offered linked mon"),
    "d3_after_baseline": ("gen2_trade_refuse_item", lambda c: _write(c).update(frame=101), "misplaced"),
    "d3_before_catch": ("gen2_trade_refuse_item", lambda c: _swap(c, "ENGINE_CAPTURE", "HARNESS_WRITE"),
                        "offered linked mon"),
    "d3_wrong_item": ("gen2_trade_refuse_item", lambda c: _write(c).update(bytes_after="9f"), "planted item"),
    "evolve_after_catch": ("gen2_trade_evolve", lambda c: _swap(c, "HARNESS_WRITE", "ENGINE_CAPTURE"),
                           "precede the catch"),
    "evolve_other_species": ("gen2_trade_evolve", lambda c: _write(c).update(bytes_after="5e"), "planted species"),
    "evolve_wrong_purpose": ("gen2_trade_evolve", lambda c: _edit_write(c, purpose="d3_mail_item"), "misplaced"),
    "evolve_undisclosed": ("gen2_trade_evolve", _drop_plant, "missing or repeated"),
    "new_with_write": ("gen2_trade_new", lambda c: c["markers"]["b"].insert(1, ("HARNESS_WRITE", {"frame": 1})),
                       "disclose exactly"),
}


@pytest.mark.parametrize("fault", sorted(O31_FAULTS))
def test_o31_planted_state_is_exactly_the_disclosed_writes(tmp_path, sources, fault):
    scenario, mutate, message = O31_FAULTS[fault]
    case = make_case(tmp_path, sources, scenario=scenario)
    mutate(case)
    with pytest.raises(RuntimeError, match=message):
        invoke(case)


def test_undisclosed_trade_evolution_is_refused_outside_the_evolve_case(tmp_path, sources):
    case = make_case(tmp_path, sources, scenario="gen2_trade_evolve")
    case["kwargs"]["expected_case"]["scenario"] = "gen2_trade_new"
    for side in ("a", "b"):
        get(case, side, "RECEIPT")["case"] = "gen2_trade_new"
    _drop_plant(case)
    rescenario(case, "gen2_trade_new")
    with pytest.raises(RuntimeError, match="trade evolution differs"):
        invoke(case)


@pytest.mark.parametrize("event", ["trade_done", "apply_trade"])
@pytest.mark.parametrize("scenario", ["gen2_trade_timeout", "gen2_trade_decline_new"])
def test_negative_case_never_reaches_server_apply(tmp_path, sources, scenario, event):
    """TRADE-HARDEN: the proposer's menu_result choice 0 cancels before APPLY: no apply_trade, no trade_done."""
    case = make_case(tmp_path, sources, scenario=scenario)
    message = {"event": "menu_result", "token": "t1", "choice": 0}
    commands = []
    if event == "trade_done":
        message = {"event": "trade_done", "token": "t1", "new_key": "x", "new_species": 16}
    else:
        commands = [{"cmd": "apply_trade", "token": "t1"}]
    row = {"seq": 1, "source": "server_dispatch", "evidence_class": "HARNESS_ONLY_OVERLAY", "run_id": "MODEL-trade",
           "scenario": scenario, "player": "a", "message": message,
           "outcome": {"dispatch": "returned", "commands": commands}}
    journal = Path(case["kwargs"]["transaction_evidence"]["events"]["path"])
    journal.write_text(json.dumps(row))
    case["kwargs"]["transaction_evidence"]["events"]["sha256"] = digest(journal.read_bytes())
    with pytest.raises(RuntimeError, match="reached server APPLY"):
        invoke(case)
    row.update(message={"event": "menu_result", "token": "t1", "choice": 0}, outcome={"dispatch": "returned", "commands": []})
    journal.write_text(json.dumps(row))
    case["kwargs"]["transaction_evidence"]["events"]["sha256"] = digest(journal.read_bytes())
    assert invoke(case) is None   # the withdrawal itself is the expected journal


def test_reset_commit_carries_no_harness_write(tmp_path, sources):
    case = reset_case(tmp_path, sources)
    case["markers"]["b"].insert(1, ("HARNESS_WRITE", {"frame": 1}))
    with pytest.raises(RuntimeError, match="disclose exactly"):
        invoke(case)


@pytest.mark.parametrize(("scenario", "side"), [("gen2_trade_decline_new", "a"), ("gen2_trade_refuse_item", "b")])
def test_mail_without_the_d3_plant_is_an_undisclosed_write(tmp_path, sources, scenario, side):
    case = make_case(tmp_path, sources, scenario=scenario, mail_sides=("a", side))
    with pytest.raises(RuntimeError, match="mail without the disclosed"):
        invoke(case)


def test_timeout_control_uses_the_overlay_apply_bound(tmp_path, sources):
    """67143736 widened APPLY 1800 -> 3600: the old 1800-frame wait no longer proves an exhausted timeout."""
    assert oracle._apply_frames(ROOT) == 3600
    case = make_case(tmp_path, sources, scenario="gen2_trade_timeout")
    get(case, "a", "TRADE_CONTROL")["before"]["registers"] = {"B": 7, "C": 8}
    with pytest.raises(RuntimeError, match="exhausted native APPLY wait"):
        invoke(case)


@pytest.fixture
def refusal_lane(monkeypatch):
    """MODEL rows only: no driver yet, so the lane does not admit these cases outside this test."""
    from tools import gen2_trade_lane
    monkeypatch.setattr(gen2_trade_lane, "SCENARIOS",
                        gen2_trade_lane.SCENARIOS | {"gen2_trade_refuse_contest", "gen2_trade_refuse_unsaved"})


def test_refusal_rows_are_not_admitted_by_any_lane_yet(tmp_path, sources):
    case = make_case(tmp_path, sources, scenario="gen2_trade_refuse_contest")
    with pytest.raises(RuntimeError, match="unknown trade scenario"):
        invoke(case)


@pytest.mark.parametrize("scenario", ["gen2_trade_refuse_contest", "gen2_trade_refuse_unsaved"])
def test_refusal_model_rows_leave_both_saves_unchanged(tmp_path, sources, refusal_lane, scenario):
    facts = []
    assert invoke(make_case(tmp_path, sources, scenario=scenario), facts.append) is None
    assert facts[0]["status"] == "unchanged"


REFUSAL_FAULTS = {
    "contest_flag_clear": ("gen2_trade_refuse_contest",
                           lambda c: get(c, "b", "TRADE_CONTROL")["before"].update(wram={"wStatusFlags2": 0}),
                           "Bug-Catching Contest flag"),
    "contest_flag_missing": ("gen2_trade_refuse_contest",
                             lambda c: get(c, "b", "TRADE_CONTROL")["before"].pop("wram"), "contest WRAM"),
    "unsaved_is_plain_decline": ("gen2_trade_refuse_unsaved",
                                 lambda c: get(c, "b", "TRADE_CONTROL").pop("save"), "responder save"),
    "unsaved_save_after_decline": ("gen2_trade_refuse_unsaved",
                                   lambda c: get(c, "b", "TRADE_CONTROL")["save"].update(frame=115),
                                   "precede its decline"),
    "unsaved_never_declined": ("gen2_trade_refuse_unsaved",
                               lambda c: get(c, "b", "TRADE_CONTROL")["before"]["registers"].update(A=0),
                               "native No result"),
}


@pytest.mark.parametrize("fault", sorted(REFUSAL_FAULTS))
def test_refusal_model_rows_require_their_native_proof(tmp_path, sources, refusal_lane, fault):
    scenario, mutate, message = REFUSAL_FAULTS[fault]
    case = make_case(tmp_path, sources, scenario=scenario)
    mutate(case)
    with pytest.raises(RuntimeError, match=message):
        invoke(case)


def _set_image(case, side, tag, raw):
    marker = get(case, side, tag)
    marker.update(image(Path(marker["snapshot_path"]), raw, marker["frame"]))


def _drop(case, side, tag):
    case["markers"][side] = [(name, row) for name, row in case["markers"][side] if name != tag]


def _forced_rewrites_items(case, sources):
    layout = sources[get(case, "a", "RECEIPT")["title"]]["layout"]
    raw = bytearray(Path(get(case, "a", "TRADE_FORCED_SAVE")["snapshot_path"]).read_bytes())
    put(raw, layout, "wNumItems", bytes([oracle._saved(bytes(raw), layout, "wNumItems", 1, "primary")[0] ^ 1]))
    _set_image(case, "a", "TRADE_FORCED_SAVE", checksum(raw, layout))


FORCED_FAULTS = {
    # coordinator ruling: A's negative final is byte-exact against the forced save, not the old baseline
    "a_final_is_the_pre_receptionist_baseline": ("gen2_trade_decline_new", lambda c, s: _set_image(
        c, "a", "TRADE_FINAL", Path(get(c, "a", "TRADE_BASELINE")["snapshot_path"]).read_bytes()), "changed saved gameplay"),
    "proposer_without_forced_save": ("gen2_trade_timeout", lambda c, s: _drop(c, "a", "TRADE_FORCED_SAVE"),
                                     "forced pre-trade save"),
    "forced_save_rewrites_more_than_the_clock": ("gen2_trade_reset_wait", _forced_rewrites_items, "rewrote more"),
    "forced_save_after_the_offer": ("gen2_trade_decline_new",
                                    lambda c, s: get(c, "a", "TRADE_FORCED_SAVE").update(frame=111), "native window"),
    "responder_applied_without_its_save": ("gen2_trade_new", lambda c, s: _drop(c, "b", "TRADE_FORCED_SAVE"),
                                           "forced pre-trade save"),
    "responder_save_before_its_prompt": ("gen2_trade_new",
                                         lambda c, s: get(c, "b", "TRADE_FORCED_SAVE").update(frame=109), "native window"),
}


@pytest.mark.parametrize("fault", sorted(FORCED_FAULTS))
def test_forced_pre_trade_save_is_the_byte_exact_before_image(tmp_path, sources, fault):
    scenario, mutate, message = FORCED_FAULTS[fault]
    case = make_case(tmp_path, sources, scenario=scenario)
    mutate(case, sources)
    with pytest.raises(RuntimeError, match=message):
        invoke(case)


def test_inactive_peer_never_saves_for_a_trade(tmp_path, sources):
    case = make_case(tmp_path, sources, scenario="gen2_trade_refuse_item")
    early_d3(case)
    forced = dict(get(case, "a", "TRADE_FORCED_SAVE"))
    case["markers"]["b"].append(("TRADE_FORCED_SAVE", forced))
    with pytest.raises(RuntimeError, match="inactive peer"):
        invoke(case)



def _resave(case, sources, side, mutate):
    """Rewrite a side's forced image (re-checksummed) and re-bind its marker."""
    receipt = get(case, side, "RECEIPT")
    layout = sources[receipt["title"]]["layout"]
    symbols = parse_symbols((ROOT / f"data/gen2/{receipt['title']}_slink.sym").read_text())
    raw = bytearray(Path(get(case, side, "TRADE_FORCED_SAVE")["snapshot_path"]).read_bytes())
    assert mutate(raw, layout, symbols), "the mutated span is not saved on this title"
    _set_image(case, side, "TRADE_FORCED_SAVE", checksum(raw, layout))


@pytest.mark.parametrize("variant", ["cc", "gs"])
def test_trgs2_shaped_forced_saves_pass(tmp_path, sources, variant):
    """Clocks, the player/object facings and (G/S) the responder's own PROMPT staging are native."""
    facts = []
    assert invoke(make_case(tmp_path, sources, variant), facts.append) is None
    assert facts[0]["status"] == "committed"


def test_responder_species_marker_must_match_partner_offer(tmp_path, sources):
    case = make_case(tmp_path, sources, "gs")
    offer = get(case, "b", "TRADE_OFFER")
    wrong_marker = 17 if offer["incoming_species_marker"] != 17 else 18
    offer["incoming_species_marker"] = wrong_marker
    _resave(case, sources, "b", lambda raw, layout, symbols: save_bytes(
        raw, layout, symbols, "wOTPartySpecies", bytes((wrong_marker, 0xFF))))
    with pytest.raises(RuntimeError, match="staged incoming"):
        invoke(case)


def test_responder_staging_blob_must_match_partner_offer(tmp_path, sources):
    case = make_case(tmp_path, sources, "gs")
    offer = get(case, "b", "TRADE_OFFER")
    other = next(row for row in get(case, "b", "TRADE_BASELINE")["party"]
                 if row["blob_hex"] != offer["incoming_blob_hex"])
    offer.update(incoming_blob_hex=other["blob_hex"], incoming_species_marker=other["species_marker"])

    def rewrite(raw, layout, symbols):
        blob = bytes.fromhex(other["blob_hex"])
        writes = (
            save_bytes(raw, layout, symbols, "wOTPlayerName", blob[48:59]),
            save_bytes(raw, layout, symbols, "wOTPartySpecies", bytes((other["species_marker"], 0xFF))),
            save_bytes(raw, layout, symbols, "wOTPartyMon1", blob[:48]),
            save_bytes(raw, layout, symbols, "wOTPartyMonOTs", blob[48:59]),
            save_bytes(raw, layout, symbols, "wOTPartyMonNicknames", blob[59:70]),
        )
        return all(writes)

    _resave(case, sources, "b", rewrite)
    with pytest.raises(RuntimeError, match="staged incoming"):
        invoke(case)


def test_responder_name_must_be_the_prompt_staging_name(tmp_path, sources):
    case = make_case(tmp_path, sources, "gs")
    offer = get(case, "b", "TRADE_OFFER")
    receipt = get(case, "b", "RECEIPT")
    incoming_ot = bytes.fromhex(offer["incoming_blob_hex"])[48:59]
    alternate = saved_delta.encode_partner_name(receipt["title"], "MODEL-A", incoming_ot, root=ROOT)
    assert alternate != incoming_ot
    _resave(case, sources, "b", lambda raw, layout, symbols: save_bytes(
        raw, layout, symbols, "wOTPlayerName", alternate))
    with pytest.raises(RuntimeError, match="rewrote more"):
        invoke(case)


def test_explicit_prompt_partner_name_selects_that_name(tmp_path, sources):
    case = make_case(tmp_path, sources, "gs")
    offer = get(case, "b", "TRADE_OFFER")
    receipt = get(case, "b", "RECEIPT")
    incoming_ot = bytes.fromhex(offer["incoming_blob_hex"])[48:59]
    alternate = saved_delta.encode_partner_name(receipt["title"], "MODEL-A", incoming_ot, root=ROOT)
    offer["partner_name"] = "MODEL-A"
    _resave(case, sources, "b", lambda raw, layout, symbols: save_bytes(
        raw, layout, symbols, "wOTPlayerName", alternate))
    assert invoke(case) is None


FORCED_REWRITE_FAULTS = {
    # the host stages wOTPartyCount = 1 (lua/gen2/trade_overlay.lua stage); an unstaged count is not the staging
    "ot_count_not_staged": ("b", lambda raw, layout, sym: save_bytes(raw, layout, sym, "wOTPartyCount", b"\x00")),
    "ot_block_extra_byte": ("b", lambda raw, layout, sym: save_bytes(raw, layout, sym, "wOTPartySpecies", b"\x10", 2)),
    "ot_staging_wrong_mon": ("b", lambda raw, layout, sym: save_bytes(raw, layout, sym, "wOTPartyMon1", b"\x07", 5)),
    "ot_staging_on_the_proposer": ("a", lambda raw, layout, sym: save_bytes(raw, layout, sym, "wOTPartyCount", b"\x03")),
    "object_non_facing_byte": ("a", lambda raw, layout, sym: save_bytes(raw, layout, sym, "wObject1Struct", b"3",
                                                                   oracle.OBJECT_FACING + 1)),
    "player_non_facing_byte": ("b", lambda raw, layout, sym: save_bytes(raw, layout, sym, "wPlayerStruct", b"3",
                                                                   oracle.OBJECT_FACING - 1)),
}


@pytest.mark.parametrize("fault", sorted(FORCED_REWRITE_FAULTS))
def test_forced_save_allows_nothing_beyond_the_decomp_rewrites(tmp_path, sources, fault):
    side, mutate = FORCED_REWRITE_FAULTS[fault]
    case = make_case(tmp_path, sources, "gs")
    _resave(case, sources, side, mutate)
    with pytest.raises(RuntimeError, match="rewrote more than"):
        invoke(case)


def test_stack_callback_in_rom0_ignores_the_mapped_bank(tmp_path, sources):
    """trgs2: global_low_water pc=$041c with rom_bank 13; a ROM0 PC executes bank 0 whatever MBC3 maps."""
    case = make_case(tmp_path, sources)
    for side in ("a", "b"):
        stack = get(case, side, "TRADE_STACK")
        stack["global_low_water"].update(pc=0x041C, rom_bank=13)
    assert invoke(case) is None


@pytest.mark.parametrize(("frame_delta", "ok"), [(0, True), (1, False)])
def test_wait_may_end_at_the_same_frame_commit_entry(tmp_path, sources, frame_delta, ok):
    """9805ac1c: APPLY pickup falls into SlinkTradeCommit in the same frame; the driver ends the wait there."""
    case = make_case(tmp_path, sources)
    symbols = parse_symbols((ROOT / "data/gen2/crystal_slink.sym").read_text())
    wait = get(case, "a", "TRADE_STACK")["phases"][0]
    wait["end"] = {"frame": wait["end"]["frame"] + frame_delta, "site": site(symbols, "SlinkTradeCommit")}
    if ok:
        assert invoke(case) is None
    else:
        with pytest.raises(RuntimeError):
            invoke(case)


def _continue_rewrite(case, sources, side, symbol, delta=5):
    """MODEL of CONTINUE's TryLoadSaveFile (G engine/menus/save.asm:538-552, C :596-611): the primary copy
    is loaded, then the BACKUP copy is rewritten from WRAM with the clock a few frames on (live gs reset_wait)."""
    receipt = get(case, side, "RECEIPT")
    layout = sources[receipt["title"]]["layout"]
    symbols = parse_symbols((ROOT / f"data/gen2/{receipt['title']}_slink.sym").read_text())
    marker = get(case, side, "TRADE_FINAL")
    raw = bytearray(Path(marker["snapshot_path"]).read_bytes())
    backup = oracle._saved_spans(layout, symbols[symbol].address, 1)[1]
    raw[backup] = (raw[backup] + delta) % 256
    offset = layout.checksum_offsets["backup"]
    raw[offset:offset + 2] = codec.sav_checksum(bytes(raw[:oracle.CART]), layout, "backup").to_bytes(2, "little")
    _set_image(case, side, "TRADE_FINAL", bytes(raw))


def _reboot(case, side):
    rows = case["markers"][side]
    at = next(i for i, (name, _) in enumerate(rows) if name == "TRADE_FINAL")
    rows.insert(at, ("REBOOTED", {"frame": get(case, side, "TRADE_FINAL")["frame"] - 1, "map_group": 20,
                                  "map_number": 1, "x": 5, "y": 3, "party_count": 2}))


@pytest.mark.parametrize("variant", ["gs", "cc"])
def test_rebooted_final_accepts_the_continue_backup_clock_rewrite(tmp_path, sources, variant):
    case = make_case(tmp_path, sources, variant, scenario="gen2_trade_reset_wait")
    _reboot(case, "a")
    _continue_rewrite(case, sources, "a", "wGameTimeFrames")
    assert invoke(case) is None


def test_continue_rewrite_needs_the_observed_reboot(tmp_path, sources):
    case = make_case(tmp_path, sources, "gs", scenario="gen2_trade_reset_wait")
    _continue_rewrite(case, sources, "a", "wGameTimeFrames")
    with pytest.raises(RuntimeError, match="checksum/copy witness"):
        invoke(case)


def test_continue_view_refuses_a_backup_change_beyond_the_clock(tmp_path, sources):
    case = make_case(tmp_path, sources, "gs", scenario="gen2_trade_reset_wait")
    _reboot(case, "a")
    _continue_rewrite(case, sources, "a", "wNumItems", delta=1)
    with pytest.raises(RuntimeError, match="beyond the CONTINUE clock rewrite"):
        invoke(case)


def _rollover(case, sources, *, advance=1, forced_edits=(), base_count=1, forced_count=1,
              base_flag=0x04, forced_flag=0x00, base_kenji=1, forced_kenji=5, rtc_mismatch=False):
    """MODEL of a day rollover between A's baseline and its forced save (HARNESS, unthrottled trgs: wCurDay,
    wRTC[0], wDailyResetTimer+1 and wTimerEventStartDay moved on the forced save). The baseline carries
    yesterday's bookkeeping and set daily flags; the forced save (and the timeout final, byte-exact to it)
    carries what CheckDailyResetTimer / CheckSwarmFlag (G) / CheckPokerusTick write (oracle.ROLLOVER_*
    citations)."""
    receipt = get(case, "a", "RECEIPT")
    layout = sources[receipt["title"]]["layout"]
    symbols = parse_symbols((ROOT / f"data/gen2/{receipt['title']}_slink.sym").read_text())
    crystal = "wKenjiBreakTimer" in symbols
    zeroed = oracle.ROLLOVER_ZEROED["c" if crystal else "gs"]
    forced = bytearray(Path(get(case, "a", "TRADE_FORCED_SAVE")["snapshot_path"]).read_bytes())
    day = (oracle._saved(bytes(forced), layout, "wCurDay", 1, "primary")[0] + 3) % 140
    base = bytearray(Path(get(case, "a", "TRADE_BASELINE")["snapshot_path"]).read_bytes())
    for raw, today, count, flag, kenji, rtc_day in (
            (base, (day - advance) % 140, base_count, base_flag, base_kenji, (day - advance) % 140),
            (forced, day, forced_count, forced_flag, forced_kenji,
             (day + 1) % 140 if rtc_mismatch else day)):
        for name, data in (("wCurDay", [today]), ("wRTC", [rtc_day]),
                           ("wDailyResetTimer", [count, today]), ("wTimerEventStartDay", [today])):
            assert save_bytes(raw, layout, symbols, name, bytes(data))
        for name, size in zeroed:
            assert save_bytes(raw, layout, symbols, name, bytes([flag] * size))
        if crystal:
            assert save_bytes(raw, layout, symbols, "wKenjiBreakTimer", bytes([kenji]))
    for name, data, delta in forced_edits:
        assert save_bytes(forced, layout, symbols, name, data, delta)
    _set_image(case, "a", "TRADE_BASELINE", checksum(base, layout))
    get(case, "a", "TRADE_READY")["snapshot_sha256"] = get(case, "a", "TRADE_BASELINE")["snapshot_sha256"]
    _set_image(case, "a", "TRADE_FORCED_SAVE", checksum(forced, layout))
    _set_image(case, "a", "TRADE_FINAL", bytes(forced))


@pytest.mark.parametrize("variant", ["gs", "cc"])
def test_day_rollover_accepts_an_unexpired_one_day_countdown(tmp_path, sources, variant):
    case = make_case(tmp_path, sources, variant, scenario="gen2_trade_timeout")
    _rollover(case, sources, base_count=3, forced_count=2, forced_flag=0x04, forced_kenji=1)
    assert invoke(case) is None


@pytest.mark.parametrize("variant", ["gs", "cc"])
def test_day_rollover_rejects_a_reset_countdown_with_cleared_flags_on_one_day(tmp_path, sources, variant):
    case = make_case(tmp_path, sources, variant, scenario="gen2_trade_timeout")
    _rollover(case, sources, base_count=3, forced_count=1, forced_kenji=1)
    with pytest.raises(RuntimeError, match="rewrote more than"):
        invoke(case)


@pytest.mark.parametrize("variant", ["gs", "cc"])
def test_day_rollover_requires_rtc_day_to_match_cur_day(tmp_path, sources, variant):
    case = make_case(tmp_path, sources, variant, scenario="gen2_trade_timeout")
    _rollover(case, sources, rtc_mismatch=True)
    with pytest.raises(RuntimeError, match="wRTC"):
        invoke(case)


@pytest.mark.parametrize("variant", ["gs", "cc"])
def test_day_rollover_allows_the_native_day_change_bookkeeping(tmp_path, sources, variant):
    case = make_case(tmp_path, sources, variant, scenario="gen2_trade_timeout")
    _rollover(case, sources)
    assert invoke(case) is None


ROLLOVER_FAULTS = {
    # the same bookkeeping writes with no wCurDay change: no allowance at all
    "no_day_change": dict(advance=0),
    "flag_set_not_reset": dict(forced_edits=(("wDailyFlags2", b"\x01", 0),)),
    "timer_day_not_today": dict(forced_edits=(("wDailyResetTimer", b"\x07", 1),)),
    "timer_countdown_not_restarted": dict(forced_edits=(("wDailyResetTimer", b"\x02", 0),)),
    "event_day_not_today": dict(forced_edits=(("wTimerEventStartDay", b"\x09", 0),)),
    "gameplay_beside_the_rollover": dict(forced_edits=(("wNumItems", b"\x0f", 0),)),
}


@pytest.mark.parametrize("variant", ["gs", "cc"])
@pytest.mark.parametrize("fault", sorted(ROLLOVER_FAULTS))
def test_day_rollover_allows_nothing_else(tmp_path, sources, variant, fault):
    case = make_case(tmp_path, sources, variant, scenario="gen2_trade_timeout")
    _rollover(case, sources, **ROLLOVER_FAULTS[fault])
    with pytest.raises(RuntimeError, match="rewrote more than"):
        invoke(case)


@pytest.mark.parametrize("kenji", [0, 2, 7])
def test_day_rollover_kenji_break_timer_steps_natively(tmp_path, sources, kenji):
    """C: from 1 the timer decrements to 0 and restarts to Random & 3 + 3 (3..6); 0, 2 and 7 are not that."""
    case = make_case(tmp_path, sources, "cc", scenario="gen2_trade_timeout")
    _rollover(case, sources, forced_edits=(("wKenjiBreakTimer", bytes([kenji]), 0),))
    with pytest.raises(RuntimeError, match="rewrote more than"):
        invoke(case)


def _above_window(stack):
    """The live shape (trgs2 low water ~0xDF73, 112 bytes up): no push inside [wStackBottom, floor + 64)."""
    stack.update(low_water_state=">floor+64", global_low_water=None, global_observations=0)
    for phase in stack["phases"]:
        phase["samples"] = []


@pytest.mark.parametrize("variant", ["gs", "cc"])
def test_stack_v2_above_the_window_passes_with_a_lower_bound_margin(tmp_path, sources, variant):
    case = make_case(tmp_path, sources, variant)
    for side in ("a", "b"):
        _above_window(get(case, side, "TRADE_STACK"))
    facts = []
    assert invoke(case, facts.append) is None
    assert facts[0]["players"]["a"]["stack"]["global"] == {"margin": ">=96", "observations": 0}


STACK_V2_FAULTS = {
    # v1's full-stack inventory, or any other window, is not the v2 contract
    "full_stack_window": (False, lambda s: s.update(armed_end=s["stack_end"], armed_count=s["stack_end"] - s["stack_start"] + 1)),
    "shifted_floor": (False, lambda s: s.update(floor=s["stack_start"] + 16)),
    "hook_outside_window": (False, lambda s: s["registration_events"][-1].update(address=s["armed_end"] + 1)),
    # the known positive: hooks that never fired prove nothing
    "canary_missed": (False, lambda s: s["canary"].update(hit=False)),
    "canary_absent": (False, lambda s: s.pop("canary")),
    "canary_before_coverage": (False, lambda s: s["canary"].update(frame=s["coverage_started"]["frame"] - 1)),
    "canary_not_sp_minus_one": (False, lambda s: s["canary"].update(sp=s["canary"]["address"] + 2)),
    "canary_missing_sp": (False, lambda s: s["canary"].pop("sp")),
    "boolean_stack_bank": (False, lambda s: s.update(stack_bank=True)),
    # ">floor+64" claims no push at all
    "above_with_observations": (True, lambda s: s.update(global_observations=2)),
    "above_with_a_low_row": (True, lambda s: s.update(global_low_water={"frame": 115, "sp": s["stack_start"] + 61,
                                                                        "stack_addr": s["stack_start"] + 60, "pc": 1,
                                                                        "rom_bank": 1})),
    "above_with_a_sample": (True, lambda s: s["phases"][0]["samples"].append(
        {"frame": 115, "sp": s["stack_start"] + 61, "stack_addr": s["stack_start"] + 60, "pc": 1, "rom_bank": 1})),
    "unknown_state": (True, lambda s: s.update(low_water_state=">floor+96")),
    # an exact sample the window never armed
    "sample_above_window": (False, lambda s: s["phases"][0]["samples"][0].update(
        sp=s["armed_end"] + 3, stack_addr=s["armed_end"] + 1)),
}


@pytest.mark.parametrize("fault", sorted(STACK_V2_FAULTS))
def test_stack_v2_refuses_anything_but_the_contract(tmp_path, sources, fault):
    above, mutate = STACK_V2_FAULTS[fault]
    case = make_case(tmp_path, sources, "gs")
    stack = get(case, "a", "TRADE_STACK")
    if above:
        _above_window(stack)
    mutate(stack)
    with pytest.raises(RuntimeError):
        invoke(case)


@pytest.mark.parametrize("title", ["gold", "silver", "crystal"])
def test_saved_nickname_decodes_with_the_pinned_charmap(title):
    assert oracle._nickname_text({"nickname_raw_hex": "86848d8680915050505050"}, title) == "GENGAR"
    assert oracle._nickname_text({"nickname_raw_hex": "0150"}, title) is None


def _display_nicknames(tmp_path, carried, shown_b):
    """links.json display nicknames: the baseline carries `carried` on both halves; the final shows shown_b on
    the committed half b now holds (live tr3 G-S evolve: HAUNTER -> GENGAR via server.py's party back-fill)."""
    for name, value in (("baseline-links.json", carried), ("links.json", None)):
        path = tmp_path / name
        payload = json.loads(path.read_text())
        for side in ("a", "b"):
            payload["links"][0][side]["nickname"] = carried
        if value is None and shown_b is not None:
            payload["links"][0]["b"]["nickname"] = shown_b
        path.write_text(json.dumps(payload))


def _rebind_baseline_links(case, tmp_path):
    raw = (tmp_path / "baseline-links.json").read_bytes()
    case["kwargs"]["transaction_evidence"]["baseline_links"]["sha256"] = digest(raw)


@pytest.mark.parametrize("scenario", ["gen2_trade_evolve", "gen2_trade_new"])
def test_committed_half_may_show_the_received_mons_saved_nickname(tmp_path, sources, scenario):
    case = make_case(tmp_path, sources, "gs", scenario=scenario)
    receipt = get(case, "b", "RECEIPT")
    _display_nicknames(tmp_path, "CARRIED", None)
    _rebind_baseline_links(case, tmp_path)
    assert invoke(case) is None                           # the carried nickname stays valid
    # the received mon's nickname as b's final save holds it (after any native evolution rename)
    final = Path(get(case, "b", "TRADE_FINAL")["snapshot_path"]).read_bytes()
    saved = codec.decode_saved_party(final[:oracle.CART], sources[receipt["title"]]["layout"], copy_name="primary")
    shown = oracle._nickname_text(saved["mons"][-1], receipt["title"])
    assert shown and shown != "CARRIED"
    _display_nicknames(tmp_path, "CARRIED", shown)
    _rebind_baseline_links(case, tmp_path)
    assert invoke(case) is None


def test_committed_half_display_nickname_is_nothing_else(tmp_path, sources):
    case = make_case(tmp_path, sources, "gs", scenario="gen2_trade_evolve")
    _display_nicknames(tmp_path, "CARRIED", "ZAPDOS")
    _rebind_baseline_links(case, tmp_path)
    with pytest.raises(RuntimeError, match="expected atomic transaction"):
        invoke(case)
