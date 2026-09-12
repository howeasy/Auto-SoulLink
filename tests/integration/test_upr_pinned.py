"""Required actual official-JAR generation checks; no mock runner or ROM bundling."""
import hashlib
import json
import os
from pathlib import Path

import pytest

from server.gen1_upr_policy import build_preset, verify_effective
from server.gen1_upr_scan import scan_generated
from server.upr_runner import JAR_SHA256, UprRunError, run_pinned, run_pair_pinned

ROOT = Path(__file__).resolve().parents[2]
PRESETS = {
    "unchanged": {}, "wild": {"wildPokemonMod": "RANDOM"},
    "starters": {"startersMod": "COMPLETELY_RANDOM"},
    "statics": {"staticPokemonMod": "COMPLETELY_RANDOM"},
    "trainers": {"trainersMod": "RANDOM", "trainersLevelModified": True, "trainersLevelModifier": 20},
    "tms": {"tmsMod": "RANDOM"}, "items": {"fieldItemsMod": "RANDOM"},
    "evolution_methods": {"changeImpossibleEvolutions": True, "makeEvolutionsEasier": True},
    "fastest_text": {"currentMiscTweaks": 8},
}
PRESETS["combined"] = {key: value for changes in list(PRESETS.values()) for key, value in changes.items()}


def user_jar():
    explicit = os.environ.get("SLINK_UPR_JAR")
    candidates = [Path(explicit)] if explicit else [root/".cache/upr/PokeRandoZX.jar" for root in (ROOT, *ROOT.parents)]
    result = next((path for path in candidates if path.is_file()), None)
    assert result is not None, "required user-supplied UPR JAR is absent"
    assert hashlib.sha256(result.read_bytes()).hexdigest() == JAR_SHA256
    return result


@pytest.mark.parametrize("variant", ["red", "blue", "yellow"])
@pytest.mark.parametrize("preset", list(PRESETS))
def test_official_jar_preserves_catalog_and_repeats_exact_output(variant, preset, tmp_path):
    source = ROOT/f"patch/build/gen1_{variant}{'.gbc' if variant == 'yellow' else '.gb'}"
    settings = build_preset(PRESETS[preset])
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    first = run_pinned(user_jar(), settings, source, tmp_path/"first", seed="123456789", generation=1)
    second = run_pinned(user_jar(), settings, source, tmp_path/"second", seed="123456789", generation=1)
    assert first["output_sha256"] == second["output_sha256"]
    assert first["effective_settings_string"] == second["effective_settings_string"]
    # UPR getStarters order is source config StarterOffsets1/2/3, not ball placement.
    starters = [25, 133] if variant == "yellow" else [4, 7, 1]
    verify_effective(settings, first["effective_settings_string"], starters)
    assert first["source_sha256"] == before == hashlib.sha256(source.read_bytes()).hexdigest()
    assert first["custom_names"]["sha256"] == second["custom_names"]["sha256"]
    assert first["status"] == "produced_requires_semantic_scan"
    final = Path(first["output"]).read_bytes()
    original = source.read_bytes()
    ghost = [0xD43D, 0x60B22, 0x60BF9, 0x70945, 0xF4070, 0xF6095, 0x60B27] if variant == "yellow" else [
        0xD6F4, 0x3EF9A, 0x58DE4, 0x60B33, 0x60C0A, 0x708E1, 0x60B38]
    moves = [0x39C6B] if variant == "yellow" else [0x39D32, 0x39CDF, 0x39CE0]+[0x39D23+i*2 for i in range(8)]
    assert all(final[offset] == original[offset] for offset in ghost+moves)
    audit=scan_generated(original,final,settings)
    assert audit["candidate_sha256"]==first["output_sha256"]
    assert audit["settings_sha256"]==first["settings_sha256"]
    assert json.loads((tmp_path/"first/provenance.json").read_text()) == first


def test_wrong_requested_generation_is_refused_by_actual_handler(tmp_path):
    with pytest.raises(UprRunError, match="requested generation"):
        run_pinned(user_jar(), build_preset(), ROOT/"patch/build/gen1_red.gb", tmp_path/"wrong",
                   seed="123", generation=2)
    assert not (tmp_path/"wrong/provenance.json").exists()


@pytest.mark.parametrize("variants", [("red","blue"),("blue","yellow"),("yellow","yellow")])
def test_pair_uses_the_same_settings_and_names_with_distinct_exact_seeds(variants,tmp_path):
    sources = {player: ROOT/f"patch/build/gen1_{variant}{'.gbc' if variant=='yellow' else '.gb'}"
               for player,variant in zip(("a","b"),variants)}
    settings = build_preset({"wildPokemonMod":"RANDOM"})
    pair = run_pair_pinned(user_jar(),settings,sources,tmp_path/"pair",
        seeds={"a":"0","b":"281474976710655"},generations={"a":1,"b":1})
    a,b = pair["players"]["a"],pair["players"]["b"]
    assert a["seed"]=="0" and b["seed"]=="281474976710655"
    assert a["settings_sha256"]==b["settings_sha256"]==pair["settings_sha256"]
    assert a["custom_names"]["sha256"]==b["custom_names"]["sha256"]==pair["custom_names"]["sha256"]
    assert a["output_sha256"]!=b["output_sha256"]
    assert json.loads((tmp_path/"pair/pair-provenance.json").read_text())==pair


def test_input_hash_and_output_alias_refusals_leave_no_pair_admission(tmp_path):
    sources={"a":ROOT/"patch/build/gen1_red.gb","b":ROOT/"patch/build/gen1_yellow.gbc"}
    with pytest.raises(UprRunError,match="must differ"):
        run_pair_pinned(user_jar(),build_preset(),sources,tmp_path/"same",seeds={"a":"1","b":"1"},generations={"a":1,"b":1})
    assert not (tmp_path/"same").exists()
    changed=bytearray(sources["b"].read_bytes());changed[-1]^=1
    altered=tmp_path/"altered.gbc";altered.write_bytes(changed)
    sources["b"]=altered
    with pytest.raises(UprRunError,match="pinned clean"):
        run_pair_pinned(user_jar(),build_preset(),sources,tmp_path/"incomplete",seeds={"a":"1","b":"2"},generations={"a":1,"b":1})
    assert not (tmp_path/"incomplete/pair-provenance.json").exists()
    assert (tmp_path/"incomplete/a/provenance.json").exists()
    with pytest.raises(UprRunError,match="new isolated"):
        run_pinned(user_jar(),build_preset(),sources["a"],tmp_path/"incomplete/a",seed="1",generation=1)


def test_yellow_long_tm48_name_preserves_the_following_dialogue(tmp_path):
    from server.gen1_upr_scan import LAYOUT
    from server.rom_change_audit import RomAuditError
    source=ROOT/"patch/build/gen1_yellow.gbc";original=source.read_bytes()
    settings=build_preset({"tmsMod":"RANDOM"})
    result=run_pinned(user_jar(),settings,source,tmp_path/"long-name",seed="4",generation=1)
    final=Path(result["output"]).read_bytes()
    layout=LAYOUT["profiles"]["yellow"]
    record=next(row for row in layout["tm_text"] if row["number"]==48)
    assert record["offset"]==0xae655 and record["limit"]==0xae66b
    assert final[layout["settings"]["TMMovesOffset"]+47]==86  # THUNDER WAVE, twelve encoded bytes
    cursor=layout["settings"]["MoveNamesOffset"]
    for _ in range(85):cursor=original.index(b"\x50",cursor)+1
    name=original[cursor:original.index(b"\x50",cursor)]
    assert len(name)==12
    assert final[record["offset"]:record["limit"]]==original[record["offset"]:record["offset"]+9]+name+b"\x57"
    assert final[record["limit"]:record["limit"]+64]==original[record["limit"]:record["limit"]+64]
    scan_generated(original,final,settings)
    overflow=bytearray(final);overflow[record["limit"]-1]=0xe7;overflow[record["limit"]]=0x57
    with pytest.raises(RomAuditError):scan_generated(original,bytes(overflow),settings)
