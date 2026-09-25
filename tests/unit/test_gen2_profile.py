"""Source-derived profile geometry and selected-title regeneration contracts."""

from dataclasses import replace

import pytest


@pytest.mark.parametrize("title,roamers", [("crystal", 2), ("gold", 3), ("silver", 3)])
def test_profile_uses_native_banked_party_and_box_geometry(title, roamers):
    from tools.gen_gen2_profile import build

    profile = build(title)
    assert profile["schema"] == "gen2-profile-v1"
    assert set(profile["titles"]) == {title}
    selected = profile["titles"][title]
    derived = selected["derived"]
    assert derived["party_struct_size"] == 48
    assert derived["box_struct_size"] == 32
    assert derived["party_capacity"] == 6
    assert derived["box_capacity"] == 20
    assert derived["num_boxes"] == 14
    assert derived["sram_box_stride"] == 0x450
    assert derived["sram_box_banks"] == [2, 3]
    assert derived["species_count"] == 251
    assert derived["egg_species"] == 253
    assert derived["base_stats_stride"] == 32
    assert derived["roamer_count"] == roamers
    assert derived["num_time_fishgroups"] == 22
    assert selected["sram_bank"]["sBox"] == 1
    assert selected["ram_bank"]["wPartyMon1"] == 1
    assert profile["write_authority"] == "NONE"


def test_public_check_detects_corrupt_profile_without_rewriting_any_output(tmp_path):
    from tools.gen_gen2_profile import main

    assert main(["--out-dir", str(tmp_path)]) == 0
    paths = sorted(tmp_path.glob("*/profile.json"))
    assert len(paths) == 3
    before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in paths}
    assert main(["--out-dir", str(tmp_path), "--check"]) == 0
    assert {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in paths} == before
    paths[-1].write_bytes(b"{}\n")
    corrupt = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in paths}
    assert main(["--out-dir", str(tmp_path), "--check"]) == 1
    assert {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in paths} == corrupt


@pytest.mark.parametrize("title,save_exists,saved,backup_spans", [
    ("crystal", 0xCFCD, 0xD4B4, 1), ("gold", 0xD19A, 0xD1DA, 5), ("silver", 0xD19A, 0xD1DA, 5),
])
def test_save_facts_bind_codec_without_injected_symbols_or_magic_values(title, save_exists, saved, backup_spans):
    from server.adapters.gen2_codec import Gen2Layout
    from tools.gen_gen2_profile import build

    profile = build(title)
    row = profile["titles"][title]
    assert row["ram"]["wSaveFileExists"] == save_exists
    assert row["ram"]["wSavedAtLeastOnce"] == saved
    assert row["constants"]["SAVE_CHECK_VALUE_1"] == 99
    assert row["constants"]["SAVE_CHECK_VALUE_2"] == 127
    assert row["constants"]["MAX_ITEM_STACK"] == 99
    layout = Gen2Layout.from_profile(profile, title)
    assert len(layout.checksum_spans["backup"]) == backup_spans
    assert [value for _, value in layout.markers["primary"]] == [99, 127]
    assert [value for _, value in layout.markers["backup"]] == [99, 127]
    assert sum(length for _, length in layout.checksum_spans["primary"]) == sum(length for _, length in layout.checksum_spans["backup"])


@pytest.mark.parametrize("name", ["wSavedAtLeastOnce", "sBackupCheckValue1"])
def test_missing_save_symbol_refuses_generation(monkeypatch, name):
    from tools import gen_gen2_profile as generator

    context = generator.load_context("crystal")
    symbols = dict(context.symbols)
    del symbols[name]
    monkeypatch.setattr(generator, "load_context", lambda *args, **kwargs: replace(context, symbols=symbols))
    with pytest.raises(ValueError, match="required symbol"):
        generator.build("crystal")


@pytest.mark.parametrize("replacement", ["", "DEF SAVE_CHECK_VALUE_1 EQU 256"])
def test_missing_or_out_of_byte_save_constant_refuses(monkeypatch, replacement):
    import re

    from tools import gen_gen2_profile as generator

    context = generator.load_context("crystal")

    class ChangedSource:
        def __getattr__(self, name):
            return getattr(context, name)

        def read_source(self, relative):
            text = context.read_source(relative)
            if relative == "constants/misc_constants.asm":
                return re.sub(r"(?m)^DEF SAVE_CHECK_VALUE_1[^\n]*", replacement, text)
            return text

    monkeypatch.setattr(generator, "load_context", lambda *args, **kwargs: ChangedSource())
    with pytest.raises(ValueError, match="SAVE_CHECK_VALUE_1"):
        generator.build("crystal")


def test_split_save_source_span_change_refuses(monkeypatch):
    from tools import gen_gen2_profile as generator

    context = generator.load_context("gold")

    class ChangedSource:
        def __getattr__(self, name):
            return getattr(context, name)

        def read_source(self, relative):
            text = context.read_source(relative)
            if relative == "ram/sram.asm":
                return text.replace("sBackupPlayerData3:: ds wPlayerDataEnd - wPlayerData3", "sBackupPlayerData3:: ds 1")
            return text

    monkeypatch.setattr(generator, "load_context", lambda *args, **kwargs: ChangedSource())
    with pytest.raises(ValueError, match="save span"):
        generator.build("gold")


@pytest.mark.parametrize("title,active_flat", [("crystal", 0x2D10), ("gold", 0x2D6C), ("silver", 0x2D6C)])
def test_flat_box_facts_match_native_symbols_without_claiming_runtime_binding(title, active_flat):
    from tools.gen_gen2_profile import build

    profile = build(title)
    selected = profile["titles"][title]
    boxes = selected["storage_boxes"]
    assert [box["flat"] for box in boxes] == [
        *range(0x4000, 0x4000 + 7 * 0x450, 0x450),
        *range(0x6000, 0x6000 + 7 * 0x450, 0x450),
    ]
    assert boxes[13]["flat"] == 0x79E0
    assert selected["derived"]["active_box_flat"] == active_flat
    assert selected["derived"]["active_box_copy_length"] == 1102
    assert selected["derived"]["active_box_copy_length"] == selected["ram"]["sBoxEnd"] - selected["ram"]["sBox"]
    assert profile["write_authority"] == "NONE" and profile["source"]["evidence_level"] == "SOURCE"


@pytest.mark.parametrize("name,bank", [("sBox14", 4), ("sBoxEnd", 2)])
def test_flat_box_facts_refuse_outside_storage_banks_and_split_active_span(monkeypatch, name, bank):
    from tools import gen_gen2_profile as generator
    from tools.rgbds_symbols import Symbol

    context = generator.load_context("crystal")
    symbols = dict(context.symbols)
    symbols[name] = Symbol(bank, symbols[name].address)
    monkeypatch.setattr(generator, "load_context", lambda *args, **kwargs: replace(context, symbols=symbols))
    with pytest.raises(ValueError):
        generator.build("crystal")


@pytest.mark.parametrize("title,player,enemy,current,trainer,trainer_id,flags", [
    ("crystal", 0xC6CC, 0xC6D4, 0xD0D4, 0xD22F, 0xD231, 0xC0),
    ("gold", 0xCBAA, 0xCBB2, 0xCFC6, 0xD118, 0xD11B, 0x80),
    ("silver", 0xCBAA, 0xCBB2, 0xCFC6, 0xD118, 0xD11B, 0x80),
])
def test_ancillary_facts_bind_seven_named_stage_bytes_inside_eight_byte_arrays(
    title, player, enemy, current, trainer, trainer_id, flags,
):
    from tools.gen_gen2_profile import build

    profile = build(title)
    row = profile["titles"][title]
    constants, ram, banks = row["constants"], row["ram"], row["ram_bank"]
    assert ram["wCurBattleMon"] == current
    assert banks["wCurBattleMon"] == (1 if title == "crystal" else 0)
    assert (ram["wOtherTrainerClass"], ram["wOtherTrainerID"]) == (trainer, trainer_id)
    assert banks["wOtherTrainerClass"] == banks["wOtherTrainerID"] == 1
    names = ("ATTACK", "DEFENSE", "SPEED", "SP_ATTACK", "SP_DEFENSE", "ACCURACY", "EVASION")
    assert [constants[name] for name in names] == list(range(7))
    assert constants["ABILITY"] == 7 and constants["NUM_LEVEL_STATS"] == 8
    for side, start in (("Player", player), ("Enemy", enemy)):
        assert ram[f"w{side}StatLevels"] == start
        for offset, suffix in enumerate(("Atk", "Def", "Spd", "SAtk", "SDef", "Acc", "Eva")):
            name = f"w{side}{suffix}Level"
            assert ram[name] == start + offset and banks[name] == 0
        assert f"w{side}AbilityLevel" not in ram  # Eighth byte has no such source symbol.
    assert enemy - player == constants["NUM_LEVEL_STATS"]
    assert constants["BASE_STAT_LEVEL"] == 7 and constants["MAX_STAT_LEVEL"] == 13
    assert row["derived"]["stat_stage_min"] == 1
    assert "MIN_STAT_LEVEL" not in constants  # Derived from engine control, not an upstream constant.
    assert constants["NUM_JOHTO_BADGES"] == constants["NUM_KANTO_BADGES"] == 8
    assert constants["NUM_BADGES"] == 16
    assert constants["BATTLERESULT_BITMASK"] == flags
    assert (constants["WILD_BATTLE"], constants["TRAINER_BATTLE"]) == (1, 2)
    assert "engine/battle/effect_commands.asm" in row["constant_sources"]
    assert "constants/ram_constants.asm" in row["constant_sources"]
    assert profile["write_authority"] == "NONE"


@pytest.mark.parametrize("name", ["wCurBattleMon", "wOtherTrainerID", "wEnemyEvaLevel"])
def test_ancillary_source_symbols_are_required_without_defaults(monkeypatch, name):
    from tools import gen_gen2_profile as generator

    context = generator.load_context("crystal")
    symbols = dict(context.symbols)
    del symbols[name]
    monkeypatch.setattr(generator, "load_context", lambda *args, **kwargs: replace(context, symbols=symbols))
    with pytest.raises(ValueError, match="required symbol"):
        generator.build("crystal")


def test_stage_symbol_offset_cannot_disagree_with_named_index(monkeypatch):
    from tools import gen_gen2_profile as generator
    from tools.rgbds_symbols import Symbol

    context = generator.load_context("crystal")
    symbols = dict(context.symbols)
    original = symbols["wPlayerSDefLevel"]
    symbols["wPlayerSDefLevel"] = Symbol(original.bank, original.address + 1)
    monkeypatch.setattr(generator, "load_context", lambda *args, **kwargs: replace(context, symbols=symbols))
    with pytest.raises(ValueError, match="stat.stage"):
        generator.build("crystal")


@pytest.mark.parametrize("fault", ["seven_instead_of_eight", "lower_bound_branch", "sharp_clamp", "lowerstat_clamp", "stage_padding"])
def test_ancillary_stage_facts_require_their_exact_source_contract(monkeypatch, fault):
    from tools import gen_gen2_profile as generator

    context = generator.load_context("gold")

    class ChangedSource:
        def __getattr__(self, name):
            return getattr(context, name)

        def read_source(self, relative):
            text = context.read_source(relative)
            if fault == "seven_instead_of_eight" and relative == "constants/battle_constants.asm":
                return text.replace("DEF NUM_LEVEL_STATS EQU const_value", "DEF NUM_LEVEL_STATS EQU const_value - 1")
            if relative == "engine/battle/effect_commands.asm":
                if fault == "lower_bound_branch":
                    return text.replace("\tjp z, .CantLower", "\tjp c, .CantLower")
                if fault == "sharp_clamp":
                    return text.replace("\tjr nz, .ComputerMiss\n\tinc b", "\tjr nz, .ComputerMiss\n\tdec b")
                if fault == "lowerstat_clamp":  # Curse lowers Speed through LowerStat, not StatDown.
                    return text.replace("\tjr nz, .got_num_stages\n\tinc b", "\tjr nz, .got_num_stages\n\tdec b")
            if fault == "stage_padding" and relative == "ram/wram.asm":
                return text.replace("wPlayerEvaLevel::  db\n\tds 1", "wPlayerEvaLevel::  db\n\tds 2")
            return text

    monkeypatch.setattr(generator, "load_context", lambda *args, **kwargs: ChangedSource())
    with pytest.raises(ValueError, match="stat.stage"):
        generator.build("gold")


# GetTreeMons: pokegold engine/events/treemons.asm:94-106 (cp NUM_TREEMON_SETS - 2,
# asserts UNUSED/CITY are the last two sets); pokecrystal :96-105 (cp NUM_TREEMON_SETS).
@pytest.mark.parametrize("title,limit", [("crystal", 8), ("gold", 4), ("silver", 4)])
def test_treemon_enabled_limit_is_the_gettreemons_cp_bound(title, limit):
    import json
    from pathlib import Path

    from tools.gen2_source_data import load_context
    from tools.gen_gen2_profile import _constants, treemon_enabled_limit

    values, receipts, source = _constants(load_context(title))
    text = source["engine/events/treemons.asm"]
    assert "engine/events/treemons.asm" in receipts
    assert treemon_enabled_limit(text, values) == values["TREEMON_ENABLED_LIMIT"] == limit
    root = Path(__file__).resolve().parents[2]
    selected = json.loads((root / f"data/games/gen2_{title}/profile.json").read_text("utf-8"))["titles"][title]
    assert selected["derived"]["treemon_enabled_limit"] == limit
    assert selected["constants"]["TREEMON_ENABLED_LIMIT"] == limit
    bound = "cp NUM_TREEMON_SETS - 2" if title != "crystal" else "cp NUM_TREEMON_SETS"
    tail = ("\tassert TREEMON_SET_UNUSED == NUM_TREEMON_SETS - 2\n"
            "\tassert TREEMON_SET_CITY == NUM_TREEMON_SETS - 1\n")
    faults = [text.replace(bound, "cp NUM_TREEMON_SETS - 3"),  # bound disagrees with asserts
              text.replace(bound, "cp 1"), text.replace("jr nc, .quit", "jr c, .quit", 1),
              text.replace("assert TREEMON_SET_NONE == 0", "assert TREEMON_SET_NONE == 1")]
    if title == "crystal":
        faults.append(text.replace(bound, "cp NUM_TREEMON_SETS - 1"))  # unasserted disabled set
    else:
        faults.append(text.replace(tail, ""))  # the disabled tail must be asserted in source
        faults.append(text.replace(bound, "cp NUM_TREEMON_SETS"))  # asserts say the tail is ignored
    for fault in faults:
        assert fault != text
        with pytest.raises(ValueError):
            treemon_enabled_limit(fault, values)


_GEN2_SCRIPTED_ROUTE_SYMBOLS = (
    "wTilemap", "wObjectStructs", "wTileUp", "wTileDown", "wTileLeft", "wTileRight",
    "wPokegearFlags", "wEventFlags", "wPlayersHouse1FSceneID", "wElmsLabSceneID",
    "wNewBarkTownSceneID",
)


@pytest.mark.parametrize("title,artifact", [("crystal", "pokecrystal"), ("gold", "pokegold"), ("silver", "pokesilver")])
def test_scripted_route_symbols_match_the_pinned_sym_file(title, artifact):
    """Each new profile RAM symbol must equal the bank:address the pinned .sym file
    gives that title, parsed independently of tools/rgbds_symbols.py."""
    import re
    from pathlib import Path

    from tools.gen_gen2_profile import build

    root = Path(__file__).resolve().parents[2]
    sym_text = (root / f"data/gen2/{artifact}.sym").read_text("utf-8")
    by_name = {}
    for line in sym_text.splitlines():
        match = re.match(r"^([0-9A-Fa-f]{2}):([0-9A-Fa-f]{4}) (\S+)$", line)
        if match:
            by_name[match.group(3)] = (int(match.group(1), 16), int(match.group(2), 16))

    selected = build(title)["titles"][title]
    for name in _GEN2_SCRIPTED_ROUTE_SYMBOLS:
        assert name in by_name, f"{artifact}.sym is missing {name}"
        bank, address = by_name[name]
        assert selected["ram_bank"][name] == bank
        assert selected["ram"][name] == address


@pytest.mark.parametrize("title,stage", [("crystal", 0xC7E8), ("gold", 0xC6E8), ("silver", 0xC6E8)])
def test_phone_build_profile_names_the_stage(title, stage):
    """PHONE-NAMES: lua/gen2/phone.lua stages in wUnusedMapBuffer, from the overlay .sym."""
    from tools.gen_gen2_profile import build

    phone = build(title)["titles"][title]["overlay"]["phone"]
    assert phone == {"stage": stage, "stage_size": 24}


@pytest.mark.parametrize("fault", ["missing", "bank", "size"])
def test_phone_block_refuses_a_bad_stage(fault):
    from tools.gen_gen2_profile import phone_block

    symbols = {"wUnusedMapBuffer": (0, 0xC7E8), "wUnusedMapBufferEnd": (0, 0xC800)}
    if fault == "missing":
        del symbols["wUnusedMapBufferEnd"]
    elif fault == "bank":
        symbols["wUnusedMapBuffer"] = (1, 0xD7E8)
    else:
        symbols["wUnusedMapBufferEnd"] = (0, 0xC801)
    with pytest.raises(ValueError):
        phone_block(symbols)
