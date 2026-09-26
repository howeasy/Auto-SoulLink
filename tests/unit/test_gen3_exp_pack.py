"""Unadmitted expansion pack: exact build facts, bytes, and additive generation."""

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

import pytest

from tools import (
    gen_area_map as areas,
    gen_gen3_engine_signals as signals,
    gen_gen3_profile as profile,
    gen_gen3_write_checkpoint as checkpoint,
    pin_gen3_site as pins,
)

ROOT = profile.REPO
PACK = ROOT / "data/games/gen3_exp/28877d73"
TITLE = profile.EXPANSION_TITLE


def read(name):
    return json.loads((PACK / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def context():
    path = Path(os.environ.get("SLINK_EXPANSION_ARTIFACTS", ROOT / ".cache/expansion-output/reference"))
    for name in ("pokeemerald.gba", "pokeemerald.sym", "pokeemerald.map"):
        if not (path / name).is_file():
            pytest.skip(f"local copyrighted ROMs absent: {path / name}")
    return profile.expansion_inputs(artifacts=path)


def test_expansion_is_not_admitted_and_removed_fields_are_absent():
    p = read("profile.json")["titles"][TITLE]
    assert p["admitted"] is False
    assert p["rom_sha1"] == profile.EXPANSION_SHA1
    forbidden = {"STATUS3_ADDR", "DISABLE_STRUCTS_ADDR", "TRAINER_OPPONENT_ADDR", "BATTLE_INTRO_GET_MONS_DATA_ADDR",
                 "STATUS3_PERISH_SONG", "DISABLE_STRUCT_SIZE", "DISABLE_STRUCT_PERISH_TIMER_OFF"}
    for section in ("ram", "rom", "derived"):
        assert not forbidden.intersection(p[section])
        assert all(value is not None for value in p[section].values())
    assert p["derived"]["SHEDINJA_SPECIES_ID"] == 292
    assert p["derived"]["BATTLE_MON_SIZE"] == 140
    assert p["derived"]["NICKNAME11_FIELD"]["shift"] == 5
    assert p["derived"]["NICKNAME12_FIELD"]["shift"] == 6
    assert "NICKNAME_EXTRA_OFFS" not in p["derived"]


def test_every_profile_address_resolves_in_build_symbols(context):
    p = read("profile.json")["titles"][TITLE]
    symbols = {row["address"] for rows in context["symbols"].values() for row in rows}
    derived = context["facts"]["derived_addresses"]
    assert p["ram"]["PARTY_BASE"] == derived["player_party"]
    assert p["ram"]["ENEMY_BASE"] == derived["enemy_party_a"]
    assert p["ram"]["PARTY_COUNT_ADDR"] == derived["player_party_count"]
    assert p["ram"]["ENEMY_COUNT_ADDR"] == derived["enemy_party_a_count"]
    for key, value in p["ram"].items():
        assert value in symbols or value in derived.values(), key
    for key, value in p["rom"].items():
        values = value.values() if isinstance(value, dict) else value if isinstance(value, list) else [value]
        for address in values:
            assert address in symbols or address - 1 in symbols, key
    assert p["ram"]["PARTY_COUNT_ADDR"] != profile.expansion_symbol(context, "gPlayerPartyCountPtr")["address"]


def test_profile_signals_checkpoint_reproduce(context):
    for name, make in (("profile.json", profile.build_expansion), ("engine_signals.json", signals.build_expansion),
                       ("write_checkpoint.json", checkpoint.build_expansion)):
        assert make(context) == read(name), name


def test_every_engine_and_checkpoint_pin_matches_rom(context):
    pack = read("engine_signals.json")
    assert pack["live_verified"] is False
    sites = pack["titles"][TITLE]["artifacts"]["clean"]["sites"]
    assert len(sites) == 18
    assert {kind for kind, row in pack["inventory"].items() if row["status"] == "OPEN"} == {
        "pc_deposit", "pc_release_begin", "pc_release"}
    for kind, row in sites.items():
        data = bytes.fromhex(row["expected_hex"])
        offset = row["rom_offset"]
        assert context["rom"][offset:offset + len(data)] == data, kind
        assert pins.find_offsets(context["rom"], data) == [offset], kind
        assert row["capture_offset"] in pins.instruction_offsets(data, "thumb"), kind
        fn = profile.expansion_symbol(context, row["symbol"])
        pc = row["address"] + row["capture_offset"]
        assert fn["address"] <= pc < fn["address"] + fn["size"]
        enclosing = row["context"]
        pattern = bytes.fromhex(enclosing["expected_hex"])
        assert context["rom"][enclosing["rom_offset"]:enclosing["rom_offset"] + len(pattern)] == pattern
    for row in read("write_checkpoint.json")[TITLE]["anchors"].values():
        data = bytes.fromhex(row["expected_hex"]["clean"])
        assert context["rom"][row["rom_offset"]:row["rom_offset"] + len(data)] == data


def test_wrong_rom_cannot_generate_pins(context):
    bad = dict(context)
    data = bytearray(context["rom"])
    data[0x1000] ^= 1
    bad["rom"] = bytes(data)
    with pytest.raises(ValueError, match="identity mismatch"):
        signals.build_expansion(bad)


def test_expansion_pin_explicit_path_is_not_ignored(tmp_path):
    path = tmp_path / "bad.gba"
    path.write_bytes(b"wrong ROM")
    with pytest.raises(ValueError, match="identity mismatch"):
        pins.load_rom("exp", path)


def test_checkpoint_uses_expansion_geometry_and_keeps_unsupported_clauses_open():
    p = read("write_checkpoint.json")[TITLE]
    facts = read("facts.json")
    field = facts["structs"]["PaletteFadeControl"]["bitfields"]["active"]
    assert p["predicates"]["palette_fade_active"]["offset"] == field["offset"] == 15
    assert p["predicates"]["palette_fade_active"]["mask"] == int(field["mask"], 16)
    assert p["tasks"]["struct_size"] == facts["structs"]["Task"]["size"] == 40
    assert len(p["tasks"]["allowed_overworld_tasks"]) == 8
    assert not set(p["tasks"]["allowed_overworld_tasks"]) & set(p["tasks"]["non_allowed_task_census"])
    assert p["cpu"]["status"] == "OPEN"
    assert "mode" not in p["cpu"] and "pc_min" not in p["cpu"]
    assert p["battle"]["commit_hold"].startswith("OPEN")
    assert "handoff" not in p["battle"]
    assert p["battle"]["commit_guard"]["value"] == facts["constants"]["STATE_WAIT_ACTION_CONFIRMED_STANDBY"]
    assert next(c for c in p["battle"]["clauses"] if c["name"] == "battle_engine_loaded")["offset"] == 46


def test_task_census_and_player_controller_are_symbol_bound(context):
    p = read("write_checkpoint.json")[TITLE]
    for name, address in p["tasks"]["allowed_overworld_tasks"].items():
        assert profile.expansion_symbol(context, name)["address"] == address
    for name, address in p["tasks"]["forbidden_inventory"].items():
        assert profile.expansion_symbol(context, name)["address"] == address
    for name, addresses in p["tasks"]["non_allowed_task_census"].items():
        assert addresses == [r["address"] for r in context["symbols"][name]]
    controller = next(c for c in p["battle"]["clauses"] if c["name"] == "battle_input_controller")
    assert controller["expect"] == profile.expansion_symbol(context, "HandleInputChooseAction", "src/battle_controller_player.o")["address"] | 1
    with pytest.raises(ValueError, match="occurrences"):
        profile.expansion_symbol(context, "HandleInputChooseAction")


def test_existing_profiles_still_generate_identically():
    text = (ROOT / profile.SRC).read_text(encoding="utf-8")
    parsed = profile.parse_profiles(text)
    source = profile.source_block(text)
    for name in profile.PACKS:
        assert profile.render(profile.build(name, parsed, source)) == (ROOT / "data/games" / name / "profile.json").read_text(encoding="utf-8")
    assert profile.render(profile.build_emerald()) == (ROOT / "data/games/gen3_emerald/profile.json").read_text(encoding="utf-8")


def test_frlg_area_check_writes_nothing_and_detects_drift(tmp_path, monkeypatch):
    folder = tmp_path / "data/games/gen3_frlge"
    folder.mkdir(parents=True)
    for name in ("area_map.json", "gen3_frlge_areas.lua", "gen3_frlge_locations.lua"):
        (folder / name).write_bytes((ROOT / "data/games/gen3_frlge" / name).read_bytes())
    monkeypatch.chdir(tmp_path)
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir()}
    assert areas.generate_frlg(check=True)
    assert {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir()} == before
    (folder / "area_map.json").write_text("{}")
    assert not areas.generate_frlg(check=True)
    assert (folder / "area_map.json").read_text() == "{}"


def test_expansion_area_outputs_from_own_source(tmp_path):
    source = ROOT / ".cache/expansion-src"
    if not source.exists():
        pytest.skip(f"pokeemerald not cloned: {source}")
    assert subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip() == "e8bd1cd7b03fc032ea37e3ecd38b379b5d01a1e7"
    assert not subprocess.check_output(["git", "-C", str(source), "status", "--porcelain", "--untracked-files=no"], text=True)
    assert areas.generate_emerald(source=source, output_dir=tmp_path, expansion=True)
    for name in ("area_map.json", "gen3_exp_areas.lua", "gen3_exp_locations.lua"):
        assert (tmp_path / name).read_text(encoding="utf-8") == (PACK / name).read_text(encoding="utf-8")
    mapping = read("area_map.json")
    assert len(mapping) == 240
    assert {"altering_cave", "altering_cave_frlg", "victory_road", "kanto_victory_road"} <= set(mapping.values())
    for name in ("gen3_exp_areas.lua", "gen3_exp_locations.lua"):
        text = (PACK / name).read_text(encoding="utf-8")
        assert text.count("return {") == 1
    assert len(re.findall(r'^  \["', (PACK / "gen3_exp_locations.lua").read_text(), re.M)) == 935
