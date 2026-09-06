"""Strict canonical coverage: effective Lua values and mutation rejection."""
from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
try:
    import verify_gen1_constants as constants
    import verify_profile_addresses as profiles
finally:
    sys.path.pop(0)


@pytest.fixture(scope="module")
def evidence():
    assert importlib.util.find_spec("lupa"), "lupa is mandatory for effective-profile validation"
    return profiles.load_gen1_profiles(), json.loads((ROOT / "data/pret_syms.json").read_text())


def test_all_five_effective_profiles_have_only_verified_categories(evidence):
    loaded, symbols = evidence
    assert set(loaded) == {"red", "blue", "yellow", "red_ap", "blue_ap"}
    rows = profiles.verify_gen1(loaded, symbols)
    assert rows
    assert all(row["severity"] == "OK" for row in rows), [r for r in rows if r["severity"] != "OK"]
    assert all(row["category"] in {"symbol", "structure", "rom_bytes", "invariant", "unsupported"} for row in rows)
    for variant in loaded:
        assert set(loaded[variant]) <= {r["field"] for r in rows if r["variant"] == variant}


@pytest.mark.parametrize("variant,field,value", [
    ("blue", "BATTLE_MON_HP_ADDR", 53270),  # Decimal value in an alias was invisible.
    ("yellow", "party_struct_size", 43),
    ("red_ap", "companion_patch_mailbox", 0xDEE2),  # Overlaps AP's current box.
    ("blue_ap", "bag_max_items", 20),  # AP's actual capacity is 128.
    ("red", "stored_boxes.banks.2", 0x4000),
    ("red", "stored_boxes.banks.3", 0x8000),
    ("red", "pp_encoding", "raw"),
    ("yellow", "SFX_DISPATCH_ADDR", False),
    ("blue_ap", "NEW_UNMAPPED_ADDR", 55000),
    ("red", "sfx_ids.success", 0x89),
    ("yellow", "change_box_bit_test_rom_addr", 0x738B2),
    ("yellow", "write_safe.stack_min", 0xDF00),
    ("red", "write_safe.irq_vector", 0x48),
    ("blue", "write_safe.delay_frame", 0x20B0),
    ("red", "write_safe.extra_entry", 0x4000),
    ("blue_ap", "write_safe.delay_frame", 0x20AF),
])
def test_active_field_drift_cannot_pass(evidence, variant, field, value):
    loaded, symbols = evidence
    changed = copy.deepcopy(loaded)
    changed[variant][field] = value
    row = next(r for r in profiles.verify_gen1(changed, symbols) if r["variant"] == variant and r["field"] == field)
    assert row["severity"] == "FAIL", row


def test_missing_nested_contract_and_missing_symbol_fail(evidence):
    loaded, symbols = copy.deepcopy(evidence)
    del loaded["blue"]["sram_box_layout.checksum_offset"]
    del symbols["alchav_pokered"]["wBattleMonHP"]
    rows = profiles.verify_gen1(loaded, symbols)
    failures = {(r["variant"], r["field"]) for r in rows if r["severity"] == "FAIL"}
    assert ("blue", "sram_box_layout.checksum_offset") in failures
    assert ("red_ap", "BATTLE_MON_HP_ADDR") in failures
    assert ("blue_ap", "BATTLE_MON_HP_ADDR") in failures


def test_loader_inspects_aliases_metatables_decimal_and_inline_fields(tmp_path):
    source = '''local M = {PROFILES = {}}
    M.PROFILES.red = { PARTY_BASE_ADDR = 53611, nested = {value = 17} }
    M.PROFILES.blue = M.PROFILES.red
    M.PROFILES.yellow = {}
    M.PROFILES.red_ap = setmetatable({party_struct_size = 44}, {__index = M.PROFILES.red})
    M.PROFILES.blue_ap = setmetatable({}, {__index = M.PROFILES.red_ap})
    return M'''
    path = tmp_path / "profile.lua"
    path.write_text(source)
    loaded = profiles.load_gen1_profiles(path)
    assert loaded["blue"]["PARTY_BASE_ADDR"] == 53611
    assert loaded["blue_ap"]["nested.value"] == 17
    assert loaded["blue_ap"]["party_struct_size"] == 44


def test_future_vanilla_fields_do_not_appear_in_ap(tmp_path):
    source = profiles.PROFILE_GEN1.read_text(encoding="utf-8")
    source = source.replace("    red = {", "    red = {\n        FUTURE_ADDR = 55000,", 1)
    path = tmp_path / "profile.lua"
    path.write_text(source, encoding="utf-8")
    loaded = profiles.load_gen1_profiles(path)
    assert loaded["red"]["FUTURE_ADDR"] == 55000
    assert "FUTURE_ADDR" not in loaded["red_ap"]
    assert "FUTURE_ADDR" not in loaded["blue_ap"]


@pytest.mark.parametrize("repo", ["pokered", "pokeyellow", "alchav_pokered"])
def test_constant_structures_and_save_geometry_match_exact_sources(evidence, repo):
    _, symbols = evidence
    rows = constants.validate_repo(constants.SOURCE_ROOT / repo, symbols[repo])
    assert len(rows) >= 25
    assert all(row["severity"] == "OK" for row in rows), [r for r in rows if r["severity"] != "OK"]


def test_structure_symbol_drift_is_not_a_warning(evidence):
    _, symbols = copy.deepcopy(evidence)
    symbols["pokeyellow"]["wPartyMon1DVs"] += 1
    rows = constants.validate_repo(constants.SOURCE_ROOT / "pokeyellow", symbols["pokeyellow"])
    assert any(r["severity"] == "FAIL" and r["check"].startswith("party_struct") for r in rows)


def test_missing_sources_fail_both_validators(evidence, tmp_path, monkeypatch):
    loaded, symbols = evidence
    monkeypatch.setattr(profiles, "SOURCE_ROOT", tmp_path)
    rows = profiles.verify_gen1(loaded, symbols)
    assert sum(r["field"] == "source_contracts" and r["severity"] == "FAIL" for r in rows) == 5
    rows = constants.validate_repo(tmp_path / "pokered", symbols["pokered"])
    assert any(r["severity"] == "FAIL" for r in rows)


@pytest.mark.parametrize("fallback", [False, True])
@pytest.mark.parametrize("extra", ["call OverworldLoop", "dw OverworldLoopLessDelay", "jp OverworldLoop"])
def test_main_loop_checkpoint_cannot_be_a_menu_subroutine_or_table_target(tmp_path, monkeypatch, fallback, extra):
    (tmp_path / "home").mkdir()
    (tmp_path / "home/overworld.asm").write_text("OverworldLoop::\n call DelayFrame\nOverworldLoopLessDelay::\n call DelayFrame\n jp OverworldLoop\n")
    if fallback:
        monkeypatch.setattr(profiles.shutil, "which", lambda _: None)
    profiles.verify_checkpoint_references(tmp_path)
    menu = tmp_path / "menu.asm"
    menu.write_text("; OverworldLoop in a comment is not an entry point\n")
    profiles.verify_checkpoint_references(tmp_path)
    menu.write_text(extra + "\n")
    with pytest.raises(profiles.EvidenceError, match="non-main-loop reference"):
        profiles.verify_checkpoint_references(tmp_path)
