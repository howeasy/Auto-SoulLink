"""PHYSICAL lane for card gen2-U1: the Crystal engine-hook proof + the 5.13 frame-alignment probe (B-9).

    SLINK_LIVE=1 pytest tests/live/test_gen2_frame_align.py -q -p no:randomly

Boots the qualified crystal_battle fixture warm and runs lua/tests/gen2_frame_align.lua: normal-button
play from Route 29 grass to a wild encounter, a Poke Ball catch (the fixture's recorded O-10 stack) and a
native save, with every engine_signals.json site armed through the shared hook registry + GB binding.
This file re-checks the gate's printed hits independently against the pack (pinned bank/PC, engine
order, capture_box silent, callback frame == armed frame, the RAM effect one frame later on the main
loop, the refused negatives) and, on PASS, writes the PHYSICAL receipt that lua/gen2/signals.lua's
production path (S.new -> S.qualified_sites) accepts:

    tests/fixtures/gen2/receipts/crystal.engine_sites.json

FRAME-ALIGNMENT CONTROL: the capture RAM effect (the callback sees wPartyCount N+1, the main loop N
before and N+1 after) substitutes plan 5.13's "DMG Gen 1 pin" (coordinator-accepted, card gen2-U1b).
Hit PC/bank are the MEASURED PC register and hROMBank byte, never the binder's anchor echo; the receipt
binds the staged fixture bytes and the qualification attempt (signals.bind_fixture_qualification).

Skipped without EmuHawk, the pinned build, the fixture or its qualification receipt (the release runner
counts a skip as a failure).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tools"))

from tests.live import test_gen2_new_gates as live  # noqa: E402
from tests.live.test_gen2_new_gates import emuhawk  # noqa: E402,F401 - pytest fixture
from tools import gen2_fixtures, gen2_source_data  # noqa: E402

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(os.environ.get("SLINK_LIVE") != "1",
                       reason="live Gen 2 gates only run with SLINK_LIVE=1 (spawns EmuHawk)"),
]

GATE = "lua/tests/gen2_frame_align.lua"
FIXTURE = "crystal_battle"
RECEIPT = REPO / "tests/fixtures/gen2/receipts/crystal.engine_sites.json"
EXPECT = ("wild_ready", "capture_party", "capture_party_finalized", "battle_end", "save_completed")
# BattlePack's per-pocket input states and ItemSubmenu's USE/QUIT box (pokecrystal engine/items/pack.asm:
# 685-782 .ItemsPocketMenu/.KeyItemsPocketMenu/.TMHMPocketMenu/.BallsPocketMenu, :783-803 ItemSubmenu).
# The shared scripted gate has no pack UI kinds, so this gate adds them to its own in-memory facts.
PACK_UI = {"pack_items": "BattlePack.ItemsPocketMenu", "pack_balls": "BattlePack.BallsPocketMenu",
           "pack_key": "BattlePack.KeyItemsPocketMenu", "pack_tmhm": "BattlePack.TMHMPocketMenu",
           "item_submenu": "ItemSubmenu"}


def battle_menu_grid(ctx) -> dict:
    """BattleMenuHeader (pokecrystal engine/battle/menu.asm:31-48) at _2DMenu's own geometry, for the gate's
    F.grid_menu: GetMenuTextStartCoord puts the first label at (left+2, top+2) for a cursor menu without
    STATICMENU_NO_TOP_SPACING (home/menu.asm:214-235); Place2DMenuItemStrings steps columns by `spacing` and
    rows by 2 tiles (engine/menus/menu.asm:117-157). <PKMN> prints as <PK><MN> (home/text.asm:316,408)."""
    menu = ctx.read_source("engine/battle/menu.asm")
    block = re.search(r"^BattleMenuHeader:$(.*?)^SafariBattleMenuHeader:", menu, re.M | re.S)[1]
    flags = re.search(r"^\s*db (.*?) ; flags$", block.split(".MenuData:")[1], re.M)[1]
    assert "STATICMENU_CURSOR" in flags and "NO_TOP_SPACING" not in flags, flags
    left, top = map(int, re.search(r"menu_coords (\d+), (\d+),", block).groups())
    rows, columns = map(int, re.search(r"dn (\d+), (\d+) ; rows, columns", block).groups())
    spacing = int(re.search(r"db (\d+) ; spacing", block)[1])
    labels = re.findall(r'db "([^"]*)@"', block)
    assert len(labels) == rows * columns and "PACK" in labels, labels
    assert re.search(r'^PlacePKMNText::\s+db "<PK><MN>@"', ctx.read_source("home/text.asm"), re.M)
    glyphs = [["<PK>", "<MN>"] if label == "<PKMN>" else list(label) for label in labels]
    return {"x": left + 2, "y": top + 2, "rows": rows, "columns": columns, "spacing": spacing, "labels": glyphs}


def u1_facts(ctx, facts, qualification_attempt_id: str) -> dict:
    """Pack-UI origins and the wrong-bank decoy: the overworld tick PC in the highest bank that carries
    no symbol and only zero bytes there (never executed), so a hit can only be the real bank's code."""
    tick = facts["observer"]["overworld_tick"]
    banks = {symbol.bank for symbol in ctx.symbols.values()}
    decoy = None
    for bank in range(len(ctx.rom) // 0x4000 - 1, 0, -1):
        flat = bank * 0x4000 + tick["addr"] - 0x4000
        if bank != tick["bank"] and bank not in banks and ctx.rom[flat:flat + 3] == bytes(3):
            decoy = {"symbol": tick["symbol"], "bank": bank, "addr": tick["addr"], "flat": flat,
                     "hex": ctx.rom[flat:flat + 3].hex()}
            break
    assert decoy is not None, "no unused ROM bank for the wrong-bank decoy"
    pack_ui = {kind: {k: v for k, v in gen2_fixtures._code_site(ctx, symbol).items() if k != "symbol_offset"}
               for kind, symbol in PACK_UI.items()}
    # PokeBallEffect asks AskGiveNicknameText -> _AskGiveNicknameText (pokecrystal engine/items/item_effects.asm:
    # 1113-1115, data/text/common_3.asm:1250-1255), not the gift-side "received?" text the route facts bind.
    anchor = "Give a nickname to"
    assert f'text "{anchor}"' in ctx.read_source("data/text/common_3.asm"), "catch nickname anchor left the source"
    return {"pack_ui": pack_ui, "decoy": decoy, "prompts": {"catch_nickname": [anchor]},
            "battle_menu": battle_menu_grid(ctx),
            "qualification_attempt_id": qualification_attempt_id}


def tag_json(text: str, tag: str):
    return live.tag_json(text, tag)


def verify(text: str, pack: dict) -> dict:
    """Independent re-check of the gate output; returns the receipt the gate printed."""
    sites = pack["titles"]["crystal"]["sites"]
    summary = tag_json(text, "HIT_SUMMARY")
    for name, row in summary.items():
        if row["hits"]:
            assert (row["pc"], row["bank"], row["off_pin"]) == (sites[name]["addr"], sites[name]["bank"], 0), (name, row)
    previous = 0
    for name in EXPECT:
        log = summary.get(name, {}).get("log") or []
        after = [hit["seq"] for hit in log if hit["seq"] > previous]
        assert after, f"{name} did not fire after the previous expected site"
        previous = after[0]
        assert all(hit["frame"] == hit.get("armed") for hit in log), (name, "callback frame != armed frame")
    assert summary["capture_party"]["hits"] == 1
    assert summary.get("capture_box", {}).get("hits", 0) == 0, "capture_box fired on a party < 6 catch"
    align = tag_json(text, "ALIGN")
    a = align["align"]
    assert align["misaligned"] == 0 and align["aligned"] >= len(EXPECT), align
    assert a["callback"] == a["armed"] and a["callback_party"] == a["battle_party"] + 1 == a["post_party"], a
    assert a["party_changed"] <= a["callback"], a
    decoy = tag_json(text, "DECOY")
    assert decoy["raw"] >= 1 and decoy["accepted"] == 0 and decoy["bank_rejects"] == decoy["raw"], decoy
    negatives = tag_json(text, "NEGATIVES")
    assert negatives["control"] == "bound", negatives
    assert "differ from the ROM" in negatives["wrong_pack_byte"], negatives
    assert "script bytecode" in negatives["script_bytecode_arm"], negatives
    production = tag_json(text, "PRODUCTION")
    assert sorted(production["registered"]) == sorted(EXPECT), production
    receipt = tag_json(text, "RECEIPT")
    source = pack["source"]
    assert (receipt["rom_sha1"], receipt["pack_commit"], receipt["pack_specs_sha256"]) == (
        source["rom_sha1"], source["commit"], pack["specs_sha256"])
    assert sorted(receipt["proven"]) == sorted(EXPECT) and receipt["harness_write_scopes"] == []
    assert receipt["evidence_level"] == "PHYSICAL" and receipt["decoy"]["bank_rejects"] == receipt["decoy"]["raw"]
    # the gate emits effect_to_callback_frames in the receipt, not on the ALIGN line (first live PASS 2026-09-23)
    fa = receipt["frame_alignment"]
    assert fa["effect_to_callback_frames"] == a["callback"] - a["party_changed"] >= 0, fa
    return receipt


def test_crystal_engine_sites_fire_at_their_routines(emuhawk):  # noqa: F811
    spec = gen2_fixtures.BY_NAME[FIXTURE]
    reason = (live.rom_missing_reason(spec.title) or live.fixture_missing_reason(spec.name)
              or live.receipt_missing_reason(spec.name))
    if reason:
        pytest.skip(reason)
    from run_gb_gate import run_gate

    fixture = REPO / "tests/fixtures/gen2" / f"{spec.name}.SaveRAM"
    staged = fixture.read_bytes()
    live.qualified_identity(spec.name, staged)   # the staged bytes are the qualified candidate
    ctx = gen2_source_data.load_context(spec.title, root=REPO)
    env = live.inspect_env(spec, staged)
    qualification = json.loads((REPO / live.RECEIPTS / f"{spec.name}.qualification.json").read_text(encoding="utf-8"))
    env["SLINK_GEN2_U1_FACTS"] = json.dumps(u1_facts(ctx, gen2_fixtures.route_facts(spec.title, REPO),
                                                     qualification["attempt_id"]))
    passed, path, text = run_gate(GATE, rom_key=spec.title, target=spec.target, timeout=1200,
                                  saveram_dir=str(REPO / ".cache/gen2-fixtures/u1-hook-proof" / spec.name),
                                  fixture_path=str(fixture), speed_percent=300, env_overrides=env)
    assert passed, f"gate FAILED; result {path}: {text[-3000:]}"
    assert fixture.read_bytes() == staged, "fixture changed while the gate ran"

    pack = json.loads((REPO / "data/games/gen2_crystal/engine_signals.json").read_text(encoding="utf-8"))
    receipt = verify(text, pack)
    assert receipt["fixture_sha256"] == hashlib.sha256(staged).hexdigest(), "receipt names other fixture bytes"
    assert receipt["qualification_attempt_id"] == qualification["attempt_id"]
    RECEIPT.write_text(json.dumps(receipt, indent=1, sort_keys=True) + "\n", encoding="utf-8")
