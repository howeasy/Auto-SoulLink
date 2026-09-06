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
from tests.unit.test_gen1_party_codec import make_blob
from tools.build_gen1_native_trade import build
from tools.run_gb_gate import run_gate

ROOT = Path(__file__).resolve().parents[2]
pytestmark = [pytest.mark.live, pytest.mark.slow,
              pytest.mark.skipif(os.environ.get("SLINK_LIVE") != "1", reason="explicit live emulator lane required")]


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
    for dex in (64, 67, 75, 93):
        species = next(int(index) for index, facts in codec.profile["species"].items() if facts["dex"] == dex)
        target = codec.profile["species"][str(species)]["evolution_targets"][0]
        incoming = bytearray(make_blob(codec, species=species, otid=0xBEEF, dv=0x7654))
        incoming[4] = 8
        rows.append({"id": f"evolve-dex{dex}", "slot": 1, "evolution": True, "evolved_species": target,
                     "party": [make_blob(codec, dv=0x1000+i).hex().upper() for i in range(3)],
                     "incoming": incoming.hex().upper()})
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


def run_cases(variant, cases):
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
    for spec, actual in zip(cases, observed["cases"], strict=True):
        if "refusal" in spec:
            assert actual["refused"] is True
            continue
        before = codec.validate_party([bytes.fromhex(blob) for blob in actual["before"]])
        after = codec.validate_party([bytes.fromhex(blob) for blob in actual["party"]])
        expected = [mon.raw for i, mon in enumerate(before) if i != spec["slot"]]
        assert [mon.raw for mon in after[:-1]] == expected
        incoming = codec.validate_blob(bytes.fromhex(spec["incoming"]))
        assert after[-1].key == incoming.key[:-2] + f'{spec.get("evolved_species", incoming.species_index):02X}'
        assert after[-1].ot_id == incoming.ot_id and after[-1].dv_word == incoming.dv_word
        assert after[-1].experience == incoming.experience and after[-1].stat_experience == incoming.stat_experience
        assert after[-1].status == incoming.status and after[-1].pp == incoming.pp and after[-1].pp_ups == incoming.pp_ups
        assert actual["frames"] > 2000 and actual["native_calls"]["InternalClockTradeAnim"] == 1
    return observed


@pytest.mark.parametrize("variant", ["red", "blue", "yellow"])
def test_native_trade_party_movie_evolution_save_and_return(variant):
    run_cases(variant, trade_cases(variant))


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
    observed = run_cases(variant, [case])
    assert observed["cases"][0]["reset_verified"] is True
