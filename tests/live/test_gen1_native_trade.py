"""Assembled physical trade component on real R/B/Y with isolated battery saves.

The probe enters at a paused IRQ boundary and returns to the original IRQ. It
does not establish receptionist/scheduler admission or paired durable recovery.
"""
import hashlib
import json
import os
from pathlib import Path

import pytest

from server.gen1_party_codec import PartyCodec
from server.gen1_trade_result import TradeResultRules
from tests.unit.test_gen1_party_codec import make_blob
from tools.build_gen1_native_trade import build
from tools.run_gb_gate import run_gate

ROOT = Path(__file__).resolve().parents[2]
pytestmark = [pytest.mark.live, pytest.mark.slow,
              pytest.mark.skipif(os.environ.get("SLINK_LIVE") != "1", reason="explicit live emulator lane required")]


def canonical_nickname(variant, species):
    """The cartridge's ten-byte MonsterNames row plus GetMonName's terminator."""
    target = {"red": "pokered", "blue": "pokeblue", "yellow": "pokeyellow"}[variant]
    pin = json.loads((ROOT / "data/pret_sources.lock.json").read_text())["clean_roms"][target]
    rom = (ROOT / pin["filename"]).read_bytes()
    assert hashlib.sha1(rom).hexdigest() == pin["sha1"]
    table = json.loads((ROOT / "data/pret_rom_syms.json").read_text())[target]
    assert table["rom_sha1"] == pin["sha1"]
    symbol = table["symbols"]["MonsterNames"]
    address = (symbol >> 16) * 0x4000 + (symbol & 0xFFFF) % 0x4000 + (species - 1) * 10
    return rom[address:address + 10] + b"\x50"


def trade_cases(variant):
    codec = PartyCodec(variant)
    rows = []
    for count in range(1, 7):
        for slot in range(count):
            incoming = bytearray(make_blob(codec, species=177, otid=0xBEEF, dv=0x7654))
            incoming[4] = 8  # poison remains exact through the native trade
            rows.append({"id": f"count{count}-slot{slot}", "slot": slot,
                         "party": [make_blob(codec, dv=0x1000+i).hex().upper() for i in range(count)],
                         "incoming": incoming.hex().upper()})
    for count, slot in ((1, 0), (3, 0), (3, 2)):
        members = [make_blob(codec, dv=0x1000+i).hex().upper() for i in range(count)]
        rows.append({"id": f"identical-transfer-count{count}-slot{slot}", "slot": slot,
                     "party": members, "incoming": members[slot]})
    for dex in (64, 67, 75, 93):
        species = next(int(index) for index, facts in codec.profile["species"].items() if facts["dex"] == dex)
        target = codec.profile["species"][str(species)]["evolution_targets"][0]
        incoming = bytearray(make_blob(codec, species=species, otid=0xBEEF, dv=0x7654))
        incoming[4] = 8
        rows.append({"id": f"evolve-dex{dex}", "slot": 1, "evolution": True, "evolved_species": target,
                     "party": [make_blob(codec, dv=0x1000+i).hex().upper() for i in range(3)],
                     "incoming": incoming.hex().upper()})
        incoming[55:66] = canonical_nickname(variant, species)
        rows.append({**rows[-1], "id": f"evolve-default-name-dex{dex}",
                     "incoming": incoming.hex().upper(),
                     "expected_nickname": canonical_nickname(variant, target).hex().upper()})
    incoming = bytearray(make_blob(codec, species=177, otid=0xBEEF, dv=0x7654))
    incoming[8:12] = bytes((1, 2, 3, 4))
    incoming[29:33] = bytes((ups << 6) | (codec.max_pp(move, ups) - move)
                            for move, ups in zip((1, 2, 3, 4), (0, 1, 2, 3), strict=True))
    rows.append({"id": "four-moves-mixed-pp-ups", "slot": 0,
                 "party": [make_blob(codec).hex().upper()], "incoming": incoming.hex().upper()})
    forced = next(row for row in rows if row["id"] == "evolve-dex93")
    rows.append({**forced, "id": "trade-evolution-cannot-cancel", "press_cancel": True})
    if variant == "yellow":
        for happiness in (50, 150, 250):
            for disabled in (False, True):
                party = [make_blob(codec, species=0x54 if i == 1 else 153, dv=0x1000+i).hex().upper() for i in range(3)]
                rows.append({"id": f"starter-happiness{happiness}-disabled{int(disabled)}", "slot": 1,
                             "party": party, "incoming": make_blob(codec, species=177, otid=0xBEEF, dv=0x7654).hex().upper(),
                             "pikachu_happiness": happiness, "following_disabled": disabled})
    guards = [
        ("battle", [{"field": "wIsInBattle", "value": 1}]),
        ("serial", [{"field": "hSerialConnectionStatus", "value": 2}]),
        ("link", [{"field": "wLinkState", "value": 0x32}]),
        ("cable", [{"field": "wEnteringCableClub", "value": 1}]),
        ("empty-party", [{"field": "wPartyCount", "value": 0}]),
        ("overfull-party", [{"field": "wPartyCount", "value": 7}]),
        ("stale-slot", [{"field": "wTradingWhichPlayerMon", "value": 3}]),
        ("party-list", [{"field": "wPartySpecies", "offset": 3, "value": 0}]),
        ("enemy-count", [{"field": "wEnemyPartyCount", "value": 2}]),
        ("enemy-list", [{"field": "wEnemyPartySpecies", "offset": 1, "value": 0}]),
        ("enemy-species", [{"field": "wEnemyMons", "value": 0x1F}, {"field": "wEnemyPartySpecies", "value": 0x1F}]),
        ("selected-fainted", [{"field": "wPartyMon2HP", "value": 0}, {"field": "wPartyMon2HP", "offset": 1, "value": 0}]),
        ("incoming-fainted", [{"field": "wEnemyMons", "offset": 1, "value": 0}, {"field": "wEnemyMons", "offset": 2, "value": 0}]),
    ]
    if variant == "yellow":
        guards.append(("printer", [{"field": "wPrinterConnectionOpen", "value": 1}]))
    for name, changes in guards:
        rows.append({"id": "refuse-" + name, "slot": 1, "refusal": changes,
                     "party": [make_blob(codec, dv=0x1000+i).hex().upper() for i in range(3)],
                     "incoming": make_blob(codec, species=177, otid=0xBEEF, dv=0x7654).hex().upper()})
    return rows


def run_cases(variant, cases, *, evidence_name):
    result = build(variant, probe=True)
    (ROOT / f".cache/native-trade-cases-{variant}.json").write_text(json.dumps(cases), encoding="utf-8")
    evidence = ROOT / f".cache/native-trade-engine-{variant}.json"
    evidence.unlink(missing_ok=True)
    passed, path, log = run_gate("lua/tests/test_gen1_native_trade_engine.lua", rom_key=variant + "_native_trade",
                                  target="town", timeout=480, quiet=True)
    assert passed, f"native engine {variant} failed\n{path}\n{log[-10000:]}"
    observed = json.loads(evidence.read_text(encoding="utf-8"))
    assert observed["variant"] == variant and observed["final_sha1"] == result["final_sha1"]
    assert hashlib.sha1((ROOT / result["output"]).read_bytes()).hexdigest() == result["final_sha1"]
    assert [row["id"] for row in observed["cases"]] == [row["id"] for row in cases]
    codec = PartyCodec(variant)
    rules = TradeResultRules.from_rom(variant, (ROOT / result["output"]).read_bytes(), expected_sha1=result["final_sha1"])
    for spec, actual in zip(cases, observed["cases"], strict=True):
        if "refusal" in spec:
            assert actual["refused"] is True
            continue
        before = codec.validate_party([bytes.fromhex(blob) for blob in actual["before"]])
        after = codec.validate_party([bytes.fromhex(blob) for blob in actual["party"]])
        expected = [mon.raw for i, mon in enumerate(before) if i != spec["slot"]]
        assert [mon.raw for mon in after[:-1]] == expected
        incoming = codec.validate_blob(bytes.fromhex(spec["incoming"]))
        outcome = rules.verify_party([mon.raw for mon in before], spec["slot"], incoming.raw,
            [mon.raw for mon in after], expected_key=before[spec["slot"]].key,
            incoming_key=incoming.key, boxed_keys=())
        actual["verified_save_sha256"] = rules.verify_save_region(
            bytes.fromhex(actual["saved_region_hex"]), bytes.fromhex(actual["live_party_hex"]),
            [mon.raw for mon in after], before_region=bytes.fromhex(actual["before_save_region_hex"]),
            before_dex=bytes.fromhex(actual["before_dex_hex"]), incoming=incoming.raw,
            outgoing=before[spec["slot"]].raw, outcome=outcome, save_id=actual["save_id"],
            save_name=bytes.fromhex(actual["save_name_hex"]),
            before_pikachu=bytes.fromhex(actual["before_pikachu_hex"]) if "before_pikachu_hex" in actual else None)
        assert after[-1].key == incoming.key[:-2] + f'{spec.get("evolved_species", incoming.species_index):02X}'
        assert after[-1].ot_id == incoming.ot_id and after[-1].dv_word == incoming.dv_word
        assert after[-1].experience == incoming.experience and after[-1].stat_experience == incoming.stat_experience
        expected_pp = spec.get("expected_packed_pp", list(incoming.raw[29:33]))
        assert after[-1].status == incoming.status
        assert after[-1].pp == tuple(value & 63 for value in expected_pp)
        assert after[-1].pp_ups == tuple(value >> 6 for value in expected_pp)
        assert after[-1].moves == tuple(spec.get("expected_moves", incoming.moves))
        assert after[-1].ot_name == incoming.ot_name
        assert after[-1].nickname == bytes.fromhex(spec.get("expected_nickname", incoming.nickname.hex()))
        assert actual["frames"] > 2000 and actual["native_calls"]["InternalClockTradeAnim"] == 1
    # Matrix and reset runs used to overwrite the only evidence file per title.
    # Retain both validated results even when the whole live file runs together.
    retained = ROOT / f".cache/native-trade-engine-{variant}-{evidence_name}.json"
    retained.write_text(json.dumps(observed, indent=2) + "\n", encoding="utf-8")
    return observed


@pytest.mark.parametrize("variant", ["red", "blue", "yellow"])
def test_native_trade_evolution_learns_level_move_through_original_cartridge(variant):
    codec = PartyCodec(variant)
    incoming = make_blob(codec, species=147, level=29, otid=0xBEEF, dv=0x7654)  # Haunter
    case = {"id": "evolve-level29-learn-hypnosis", "slot": 0, "evolution": True, "evolved_species": 14,
            "party": [make_blob(codec).hex().upper()], "incoming": incoming.hex().upper(),
            "expected_moves": [1, 2, 95, 0], "expected_packed_pp": [incoming[29], incoming[30], codec.max_pp(95, 0), 0],
            "expected_learn_calls": 1}
    cases = [case]
    full = bytearray(incoming)
    full[8:12] = bytes((1, 2, 3, 4))
    full[29:33] = bytes((0xC0 | codec.max_pp(1, 3), 25, 5, 5))
    for slot in range(4):
        moves, pp = list(full[8:12]), list(full[29:33])
        moves[slot], pp[slot] = 95, codec.max_pp(95, 0)
        cases.append({**case, "id": f"evolve-learn-replace-slot{slot}", "incoming": full.hex().upper(),
                      "expected_moves": moves, "expected_packed_pp": pp, "learning_action": "replace", "forget_slot": slot})
    cases.append({**case, "id": "evolve-learn-declined", "incoming": full.hex().upper(),
                  "expected_moves": list(full[8:12]), "expected_packed_pp": list(full[29:33]),
                  "learning_action": "decline"})
    known = bytearray(full)
    known[8], known[29] = 95, 1
    cases.append({**case, "id": "evolve-known-move-keeps-pp", "incoming": known.hex().upper(),
                  "expected_moves": list(known[8:12]), "expected_packed_pp": list(known[29:33]),
                  "expected_learn_calls": 0})
    hm = bytearray(full)
    hm[8], hm[29] = 15, codec.max_pp(15, 0)
    cases.append({**case, "id": "evolve-hm-refused-then-replace", "incoming": hm.hex().upper(),
                  "expected_moves": [15, 95, 3, 4], "expected_packed_pp": [hm[29], codec.max_pp(95, 0), hm[31], hm[32]],
                  "learning_action": "replace", "forget_choices": [0, 1], "expected_forget_menus": 2})
    target_name = {"red": "pokered", "blue": "pokeblue", "yellow": "pokeyellow"}[variant]
    pin = json.loads((ROOT / "data/pret_sources.lock.json").read_text())["clean_roms"][target_name]
    rules = TradeResultRules.from_rom(variant, (ROOT / pin["filename"]).read_bytes(), expected_sha1=pin["sha1"])
    for dex in (64, 67, 75):
        species = next(int(index) for index, facts in codec.profile["species"].items() if facts["dex"] == dex)
        target = codec.profile["species"][str(species)]["evolution_targets"][0]
        level, move = next((level, move) for level, move in rules._records[target][1] if move not in (1, 2))
        raw = make_blob(codec, species=species, level=level, otid=0xBEEF, dv=0x7654)
        cases.append({**case, "id": f"evolve-dex{dex}-level{level}-learn{move}", "incoming": raw.hex().upper(),
                      "evolved_species": target, "expected_moves": [1, 2, move, 0],
                      "expected_packed_pp": [raw[29], raw[30], codec.max_pp(move, 0), 0]})
    run_cases(variant, cases, evidence_name="learning")


@pytest.mark.parametrize("variant", ["red", "blue", "yellow"])
def test_native_trade_party_movie_evolution_save_and_return(variant):
    run_cases(variant, trade_cases(variant), evidence_name="matrix")


@pytest.mark.parametrize("variant", ["red", "blue", "yellow"])
def test_native_trade_survives_real_reset_and_continue(variant):
    codec = PartyCodec(variant)
    case = next(row for row in trade_cases(variant) if row["id"] == "evolve-dex93")
    incoming = bytearray.fromhex(case["incoming"])
    incoming[4] = 0  # boot proof walks; do not introduce poison damage after saving
    case.update(id="reset-after-native-trade", incoming=incoming.hex().upper(), reset=True)
    if variant == "yellow":
        case["party"][1] = make_blob(codec, species=0x54, dv=0x1001).hex().upper()
        case.update(pikachu_happiness=250, following_disabled=False)
    observed = run_cases(variant, [case], evidence_name="reset")
    assert observed["cases"][0]["reset_verified"] is True
