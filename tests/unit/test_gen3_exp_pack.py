"""Unadmitted expansion pack: exact build facts, bytes, and additive generation."""

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

import lupa
import pytest

from tools import (
    extract_expansion_data as ex,
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
    battle = json.loads((PACK / "facts.json").read_text())["structs"]["BattlePokemon"]["fields"]
    assert p["derived"]["BATTLE_MON_MOVES_OFF"] == battle["moves"]["offset"] == 12
    assert p["derived"]["BATTLE_MON_PP_OFF"] == battle["pp"]["offset"] == 37
    perish = json.loads((PACK / "facts.json").read_text())["structs"]["Volatiles"]["bitfields"]
    volatiles_off = battle["volatiles"]["offset"]
    assert p["derived"]["BATTLE_MON_PERISH_FLAG_OFF"] == volatiles_off + perish["perishSong"]["offset"] == 94
    assert p["derived"]["BATTLE_MON_PERISH_FLAG_MASK"] == int(perish["perishSong"]["mask"], 16) == 0x80
    assert p["derived"]["BATTLE_MON_PERISH_TIMER_OFF"] == volatiles_off + perish["perishSongTimer"]["offset"] == 114
    assert p["derived"]["BATTLE_MON_PERISH_TIMER_KEEP"] == 0xFF ^ int(perish["perishSongTimer"]["mask"], 16) == 0xF3
    # X2: the 12-char nickname lanes in the reads.lua/gen3_codec layout shape (bit 53 and 86
    # of the Growth substruct: nickname11 = experience u32 bits 21-28, nickname12 = +10 bits 6-13)
    chars = p["derived"]["NICKNAME_EXTRA"]["chars"]
    assert [c["word_off"] * 8 + c["shift"] for c in chars] == [53, 86] and {c["width"] for c in chars} == {8}
    assert "NICKNAME_EXTRA_OFFS" not in p["derived"] and "NICKNAME11_FIELD" not in p["derived"]


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
    # X3: the BIOS park + IntrWait IRQ entry from the live census/IRQ receipts (test_gen3_exp_safety.py)
    assert (p["cpu"]["mode"], p["cpu"]["thumb"], p["cpu"]["observed_pc"]) == (0x1F, 1, 0x0817AB3A)
    assert p["cpu"]["irq_entry"]["lr_min"] == p["cpu"]["irq_entry"]["lr_max"] == 0x1F8
    assert "cpu" not in p["open"] and p["tasks"]["status"] == "CENSUS"
    handoff = p["battle"]["handoff"]
    derived = read("profile.json")["titles"][TITLE]["derived"]
    assert p["battle"]["commit_hold"].startswith("HOLD")
    assert handoff["address"] == 0x030023EC and handoff["value"] == 0x0805A209
    assert [row["name"] for row in handoff["head"]] == ["perish_status", "perish_timer", "no_op_action"]
    battle_mons = read("profile.json")["titles"][TITLE]["ram"]["BATTLE_MONS_ADDR"]
    assert handoff["head"][0] == {
        "name": "perish_status", "address": battle_mons + derived["BATTLE_MON_PERISH_FLAG_OFF"],
        "width": 1, "set": derived["BATTLE_MON_PERISH_FLAG_MASK"]}
    assert handoff["head"][1] == {
        "name": "perish_timer", "address": battle_mons + derived["BATTLE_MON_PERISH_TIMER_OFF"],
        "width": 1, "keep": derived["BATTLE_MON_PERISH_TIMER_KEEP"]}
    assert p["battle"]["commit_guard"]["value"] == facts["constants"]["STATE_WAIT_ACTION_CONFIRMED_STANDBY"]
    assert next(c for c in p["battle"]["clauses"] if c["name"] == "battle_engine_loaded")["offset"] == 46


def test_expansion_handoff_refuses_rom_body_or_pool_drift(context):
    original = checkpoint.expansion_handoff(context)
    fn = profile.expansion_symbol(context, "PlayerBufferExecCompleted", "src/battle_controller_player.o")
    for rel in (0, 0x70, 0x74, 0x80):
        changed = dict(context)
        rom = bytearray(context["rom"])
        rom[fn["address"] - checkpoint.ROM_BASE + rel] ^= 1
        changed["rom"] = bytes(rom)
        with pytest.raises(ValueError, match="ROM prefix changed|pool .* changed"):
            checkpoint.expansion_handoff(changed)
    assert original["value"] == fn["address"] | 1


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


# ── F1: gen3_exp is data-only -- nothing routes a real cartridge into it ────────────────────
def test_gen3_exp_is_unreachable_from_entry_lua_and_manager():
    """The pack is deliberately UNADMITTED (module docstring). X3 (the E2-ENTRY precedent) registers
    it in lua/gen3/entry.lua's Entry.PACKS so its hash names its OWN pack (never gen3_emerald's) and
    the launcher refuses it as unrouted (test_gen3_exp_entry.py); it must stay out of Entry.ROUTED,
    carry no header_code (no by-name admission), keep its profile unadmitted, and server/manager.py
    must not offer it as a playable GAMES entry or even list it as a named UNADMITTED_GAMES key."""
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    entry_path = (ROOT / "lua/gen3/entry.lua").as_posix()
    Entry = lua.eval(f'dofile("{entry_path}")')
    assert "gen3_exp" in {key for key, _ in Entry.PACKS.items()}
    assert Entry.PACKS.gen3_exp.header_code is None
    assert "gen3_exp" not in {key for key, _ in Entry.ROUTED.items()}
    assert read("profile.json")["titles"][TITLE]["admitted"] is False

    from server.manager import GAMES, UNADMITTED_GAMES
    assert "gen3_exp" not in {key for key, _, _ in GAMES}
    assert "gen3_exp" not in UNADMITTED_GAMES


# ── F3/F4: a ROM-value oracle independent of the generator's own decode path ────────────────
def _rom_table_row(context, layout, table, row_id):
    """Decode one row of a layout.json table straight off the reference ROM bytes, using only
    ex.Rom/ex.number (never gen_expansion_facts.py's own pipeline) as an independent check that
    layout.json's offsets/widths/shifts actually land on the values the compiler emitted."""
    rom = ex.Rom(context["rom"])
    spec = layout["tables"][table]
    pointer = context["facts"]["headers"]["gf"][table]
    base = rom.address(pointer, spec["stride"] * (row_id + 1))
    pos = base + row_id * spec["stride"]
    return {key: ex.number(rom, pos, field, spec["stride"]) for key, field in spec["fields"].items()}


def test_move_priority_matches_the_rom_for_four_known_moves(context):
    # ids from this build's own include/constants/moves.h (Quick Attack=98, Extreme Speed=245,
    # Protect=182, Pound=1) -- never a vanilla id (owner note: RR types/ids are non-standard).
    layout = read("layout.json")
    expected = {1: 0, 98: 1, 182: 4, 245: 2}  # Pound, Quick Attack, Protect, Extreme Speed
    for move_id, priority in expected.items():
        row = _rom_table_row(context, layout, "moves", move_id)
        assert row["priority"] == priority, move_id


def test_species_base_stats_match_the_rom_for_bulbasaur(context):
    layout = read("layout.json")  # SPECIES_BULBASAUR = 1 (this build's constants/species.h)
    row = _rom_table_row(context, layout, "species", 1)
    assert (row["baseHP"], row["baseAttack"], row["baseDefense"], row["baseSpeed"],
            row["baseSpAttack"], row["baseSpDefense"]) == (45, 49, 49, 45, 65, 65)


def test_item_row_matches_the_rom_for_potion(context):
    layout = read("layout.json")  # ITEM_POTION = 28; I_PRICE=GEN_LATEST(9)>=GEN_7 -> 200
    row = _rom_table_row(context, layout, "items", 28)
    assert row["price"] == 200
    assert row["holdEffectParam"] == 20


# ── F2 -> X3: the task allow-list names its qualification; cpu is a measured clause ──────────
def test_tasks_allow_list_carries_its_census_and_cpu_is_measured():
    p = read("write_checkpoint.json")[TITLE]
    assert p["tasks"]["status"] == "CENSUS" and (ROOT / p["tasks"]["census"]).is_file()
    assert "status" not in p["cpu"] and (ROOT / p["cpu"]["census"]).is_file()
    assert (ROOT / p["cpu"]["irq_entry"]["evidence"]).is_file()


# ── F6: a ValueError from generate_emerald(check=...) is a message, not a traceback ─────────
def test_area_map_main_turns_expansion_value_error_into_exit_1(monkeypatch, capsys):
    source = ROOT / ".cache/expansion-src"
    if not source.exists():
        pytest.skip(f"pokeemerald not cloned: {source}")

    def boom(*_args, **_kwargs):
        raise ValueError("area_id 'x' would merge unrelated maps")

    monkeypatch.setattr(areas, "generate_emerald", boom)
    monkeypatch.setattr("sys.argv", ["gen_area_map.py", "--game", "emerald",
                                     "--expansion", "28877d73", "--source", str(source)])
    assert areas.main() == 1
    assert "area_id 'x' would merge unrelated maps" in capsys.readouterr().err


# ── F7: facts.json's on-disk bytes are exactly gen_gen3_profile.render's serialization ──────
def test_facts_json_bytes_match_profiles_render_and_its_recorded_sha256():
    # a CRLF (core.autocrlf) checkout still hashes the LF bytes the generator wrote and pinned
    raw = (PACK / "facts.json").read_bytes().replace(b"\r\n", b"\n")
    assert profile.render(json.loads(raw)).encode("utf-8") == raw
    digest = hashlib.sha256(raw).hexdigest()
    assert read("profile.json")["source"]["facts_sha256"] == digest
    assert read("write_checkpoint.json")[TITLE]["source"]["facts_sha256"] == digest


# ── F8: the generated Lua headers are bound to the exact source JSON they were built from ──
def test_expansion_area_lua_headers_carry_the_source_sha256():
    source = ROOT / ".cache/expansion-src"
    if not source.exists():
        pytest.skip(f"pokeemerald not cloned: {source}")
    expected = f"-- source_sha256: {areas._expansion_source_sha256(source)}"
    for name in ("gen3_exp_areas.lua", "gen3_exp_locations.lua"):
        lines = (PACK / name).read_text(encoding="utf-8").splitlines()
        assert expected in lines[:5], name
