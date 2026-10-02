"""Pinned expansion gift/static declaration census; no live admission implied."""

import json
from pathlib import Path

import pytest

from tools import gen_gen3_profile as profile

ROOT = profile.REPO
SOURCE = ROOT / ".cache/expansion-src"
OUTPUT = ROOT / "data/games/gen3_exp/28877d73/expansion_gifts.json"


def _source() -> Path:
    """The pinned expansion checkout is an ignored cache: absent skips (tests/TESTING.md);
    a present-but-wrong tree still fails the parity and source-line checks."""
    if not SOURCE.is_dir():
        pytest.skip(f"pinned expansion source absent: {SOURCE}")
    return SOURCE


def test_expansion_gift_census_preserves_active_and_excluded_sources():
    census = json.loads(OUTPUT.read_text(encoding="utf-8"))
    rows = census["declarations"]
    by_source = {(r["source"], r["line"]): r for r in rows}
    assert len(by_source) == len(rows)
    assert len(rows) == 61
    assert rows == sorted(rows, key=lambda r: (r["source"], r["line"]))
    assert len(census["scanned_files"]) == 972
    assert len([p for p in census["scanned_files"] if p.startswith("data/scripts/gift_")]) == 8
    assert census["area_map_inputs_sha256"]
    assert any(r["kind"] == "gift" and r["species"] == "SPECIES_BELDUM"
               and r["status"] == "active" for r in rows)
    assert any(r["kind"] == "egg" and r["species"] == "SPECIES_WYNAUT"
               and r["status"] == "active" for r in rows)
    assert any(r["kind"] == "static" and r["species"] == "SPECIES_REGIROCK"
               and r["status"] == "active" for r in rows)
    assert any(r["source"].endswith("CeladonCity_GameCorner_PrizeRoom_Frlg/scripts.inc")
               and r["species"] == "VAR_TEMP_1" and r["status"] == "excluded"
               and "IS_FRLG" in r["condition"] for r in rows)
    assert any(r["source"] == "data/scripts/debug.inc" and r["status"] == "excluded"
               and r["species"] == "SPECIES_TREECKO" for r in rows)
    assert any(r["kind"] == "gift" and r["source"] == "src/battle_setup.c"
               and r["species"] == "starterMon" and r["status"] == "active" for r in rows)
    for r in rows:
        assert r["source"] and r["line"] > 0 and r["species"]
        if r["status"] == "active" and r["source"].startswith("data/maps/"):
            assert r["map_group_num"] is not None
            assert r["area_id"] or r["unresolved_area"]
        if r["kind"] == "static":
            assert r["gift_area"] is None
    debug = next(r for r in rows if r["source"] == "src/debug.c" and r["line"] == 3198)
    assert debug["arguments"] == ["DebugSelection_GetData(taskId, 0)",
                                  "DebugSelection_GetData(taskId, 1)", "ITEM_NONE"]
    source = _source()
    for r in rows:
        source_line = (source / r["source"]).read_text(encoding="utf-8").splitlines()[r["line"] - 1]
        assert r["opcode"] in source_line and r["species"] in source_line


def test_expansion_gift_generator_parity_and_source_pin():
    from tools import gen_gen3_exp_gifts as gifts

    assert gifts.build(_source()) == json.loads(OUTPUT.read_text(encoding="utf-8"))


def test_nested_native_arguments_and_createmon_target_classification():
    from tools import gen_gen3_exp_gifts as gifts

    assert gifts.split_arguments("DebugSelection_GetData(taskId, 0), DebugSelection_GetData(taskId, 1), ITEM_NONE") == [
        "DebugSelection_GetData(taskId, 0)", "DebugSelection_GetData(taskId, 1)", "ITEM_NONE"]
    assert gifts.split_arguments('SPECIES_X, func("a,b", inner(1, 2)), ITEM_NONE') == [
        "SPECIES_X", 'func("a,b", inner(1, 2))', "ITEM_NONE"]
    assert gifts.createmon_target("B_SIDE_PLAYER") == "player"
    assert gifts.createmon_target("B_SIDE_OPPONENT") == "opponent"
    assert gifts.createmon_target("VAR_TEMP_1") == "runtime"
    assert gifts.classify_grant("createmon", ["B_SIDE_PLAYER", "PARTY_SIZE", "SPECIES_EEVEE"],
                                "active")[:2] == ("gift", "active")
    assert gifts.classify_grant("createmon", ["B_SIDE_OPPONENT", "0", "SPECIES_EEVEE"],
                                "active")[:2] == ("opponent_create", "excluded")
    assert gifts.classify_grant("createmon", ["VAR_TEMP_1", "0", "SPECIES_EEVEE"],
                                "active")[:2] == ("unresolved_create", "unknown")


def test_transitive_include_and_unknown_grant_condition_are_not_silent(tmp_path):
    from tools import gen_gen3_exp_gifts as gifts

    (tmp_path / "data/scripts").mkdir(parents=True)
    (tmp_path / "data/event_scripts.s").write_text(
        '.include "data/scripts/outer.inc"\n', encoding="utf-8")
    (tmp_path / "data/mystery_gift.s").write_text(
        '.include "data/scripts/payload.inc"\n', encoding="utf-8")
    (tmp_path / "data/scripts/outer.inc").write_text(
        '.include "data/scripts/inner.inc"\n', encoding="utf-8")
    (tmp_path / "data/scripts/inner.inc").write_text(
        '.if SOME_UNKNOWN_CONFIG\n givemon SPECIES_EEVEE, 5\n.endif\n', encoding="utf-8")
    (tmp_path / "data/scripts/payload.inc").write_text(
        'giveegg SPECIES_PICHU\n', encoding="utf-8")
    files = gifts.script_closure(tmp_path)
    assert files["data/scripts/inner.inc"] == "IS_EMERALD"
    assert files["data/scripts/payload.inc"] == "mystery_gift_payload"
    grants = list(gifts.script_grants(tmp_path / "data/scripts/inner.inc", files["data/scripts/inner.inc"]))
    assert grants[0]["condition"].endswith("SOME_UNKNOWN_CONFIG")
    assert grants[0]["status"] == "unknown"
