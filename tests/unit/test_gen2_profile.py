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
