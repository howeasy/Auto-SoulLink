"""pureRGB engine signal sites (PLAN §6 M1): every hook the pure client will arm is really in the
built ROM, at the offset the pinned .sym gives, and agrees with the pure profile.

Two independent derivations must agree: the generator sliced bytes at a flat offset, the .sym
pins the symbol. Byte checks need the built ROMs (SLINK_PURERGB_SRC at the locked commit) and
skip without them; the symbol/profile checks always run.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))

import gen1_foundation as F  # noqa: E402
import gen_gen1_engine_signals as gen  # noqa: E402

DATA = REPO / "data" / "games" / "gen1_purergb"
TITLES = ("purered", "pureblue", "puregreen")
_PROFILE = json.loads((DATA / "profile.json").read_text(encoding="utf-8"))
PROFILE, SOURCE = _PROFILE["titles"], _PROFILE["source"]
SIGNALS = json.loads((DATA / "engine_signals.json").read_text(encoding="utf-8"))
VANILLA_KINDS = set(json.loads((REPO / "data" / "games" / "gen1_rby" / "engine_signals.json")
                               .read_text(encoding="utf-8"))["titles"]["red"]["sites"])


def _rom(title: str) -> bytes:
    try:
        data = F.rom_path("purergb", title).read_bytes()
    except SystemExit as e:
        pytest.skip(f"pureRGB build not available: {e}")
    assert hashlib.sha1(data).hexdigest() == PROFILE[title]["rom_sha1"], f"{title}: not the locked build"
    return data


def test_schema_and_kinds():
    assert SIGNALS["schema"] == "rby-engine-signal-sites-v1"
    assert SIGNALS["source_commit"] == json.loads(
        (REPO / "data" / "purergb_sources.lock.json").read_text(encoding="utf-8"))["source"]["commit"]
    assert set(SIGNALS["titles"]) == set(TITLES)
    kinds = set(SIGNALS["titles"]["purered"]["sites"])
    assert kinds == set(gen.SITES) and len(kinds) == 40
    assert kinds >= VANILLA_KINDS  # the 17 vanilla kinds survive under their names
    assert kinds >= {"trainer_staging", "transform", "transform_hp_hi", "transform_hp_lo", "apex_preflight", "apex_commit",
            "apex_recalc_call", "npc_trade_remove", "npc_trade_add", "npc_trade_done", "daycare_withdraw",
            "cable_trade_remove", "cable_trade_add", "cable_partial_save", "changebox_full_save",
            "capture_party_begin", "capture_party_end", "capture_box_begin", "capture_box_end",
            "pc_deposit", "pc_withdraw", "pc_release", }
    for title in TITLES:
        assert set(SIGNALS["titles"][title]["sites"]) == kinds, title


@pytest.mark.parametrize("title", TITLES)
def test_rows_agree_with_the_sym_and_the_profile(title):
    t = SIGNALS["titles"][title]
    syms = F.parse_sym(F.sym_path("purergb", title))
    prof = PROFILE[title]
    assert t["symbols_sha256"] == SOURCE[prof["sym"]]["sha256"]
    assert t["rom_sha1"] == prof["rom_sha1"]
    for name, addr in t["addresses"].items():
        assert syms[name][1] == addr, name
        if name in prof["ram"]:
            assert prof["ram"][name] == addr, name
    for kind, d in t["sites"].items():
        bank, base = syms[d["symbol"]]
        assert d["bank"] == bank and d["address"] == base + d["anchor_offset"], kind
        assert d["rom_offset"] == F.flat(bank, d["address"]), kind
        assert isinstance(d["capture_offset"], int) and d["capture_offset"] >= 0
        assert len(d["expected_hex"]) >= 16 and bytes.fromhex(d["expected_hex"]), kind
        assert set(d["point"]) <= set(t["addresses"]), kind
        assert d["source"] and d["assert"], kind
        if d["symbol"].split(".")[0] in prof["rom"]:
            assert prof["rom"][d["symbol"].split(".")[0]]["bank"] == bank, kind


@pytest.mark.parametrize("title", TITLES)
def test_pinned_bytes_are_in_the_built_rom(title):
    rom = _rom(title)
    for kind, d in SIGNALS["titles"][title]["sites"].items():
        want = bytes.fromhex(d["expected_hex"])
        assert rom[d["rom_offset"]:d["rom_offset"] + len(want)] == want, kind
        pre = d.get("prelude")
        if pre:
            want = bytes.fromhex(pre["expected_hex"])
            assert rom[pre["rom_offset"]:pre["rom_offset"] + len(want)] == want, f"{kind} prelude"


def test_sites_the_plan_relies_on_are_where_it_says():
    """PLAN §6 M1 / §11.2 offsets, in the file's own words (site_crossref.md *_corrected rows)."""
    s = SIGNALS["titles"]["purered"]["sites"]
    for kind, symbol, off, cap in (
            ("wild_begin", "InitWildBattle", 0x13, 0), ("battle_loop_head", "MainInBattleLoop", 6, 0),
            ("trainer_staging", "InitBattleCommon", 0x48, 0), ("save_witness", "SaveMenu.save", 3, 0),
            ("bag_received", "AddItemToInventory_.done", 0, 8), ("poison_faint", "ApplyOutOfBattlePoisonDamage.noBorrow", 4, 0),
            ("changebox_full_save", "ChangeBox.yes", 0x35, 0), ("cable_trade_add", "TradeCenter_Trade.doTrade", 0x9D, 0),
            ("cable_trade_remove", "TradeCenter_Trade.doTrade", 0x77, 0), ("starter_begin", "OaksLabMonChoiceMenu.continue", 0x23, 0),
            ("starter_end", "OaksLabMonChoiceMenu.continue", 0x26, 0), ("apex_preflight", "ItemUseMedicine.useApexChip", 0x0F, 0),
            ("transform_hp_hi", "ChangePartyPokemonSpecies", 0x4A, 0), ("transform_hp_lo", "ChangePartyPokemonSpecies", 0x4C, 0),
            ("evolve", "Evolution_PartyMonLoop.skipfix_end", 0x3C, 1)):
        assert (s[kind]["symbol"], s[kind]["anchor_offset"], s[kind]["capture_offset"]) == (symbol, off, cap), kind
    assert s["trainer_staging"]["expected_hex"].startswith("3E02EA")  # ld a,2 ; ld [wIsInBattle],a
    assert s["save_witness"]["expected_hex"].startswith("CD")  # call ClearTextBox, not the vanilla ld hl
    assert s["battle_end"]["bank"] == 0x3A and s["save_witness"]["bank"] == 0x1C
    assert s["bag_received"]["expected_hex"].endswith("C9") and len(s["bag_received"]["expected_hex"]) == 18


def test_engine_signals_regenerate_byte_identically():
    try:
        F.source_root("purergb")
    except SystemExit as e:
        pytest.skip(str(e))
    assert (DATA / "engine_signals.json").read_text(encoding="utf-8") == gen.render(gen.build())
