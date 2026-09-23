"""PHYSICAL lane for cards gen2-U1 / gen2-U1-GS: the engine-hook proof + the 5.13 frame-alignment probe (B-9),
one run per title on that title's own qualified battle fixture, ROM and pack rows.

    SLINK_LIVE=1 pytest tests/live/test_gen2_frame_align.py -q -p no:randomly -k crystal   (or gold, silver)

Boots the qualified <title>_battle fixture warm and runs lua/tests/gen2_frame_align.lua: normal-button
play from Route 29 grass to a wild encounter, a Poke Ball catch (the fixture's recorded O-10 stack) and a
native save, with every engine_signals.json site armed through the shared hook registry + GB binding.
This file re-checks the gate's printed hits independently against the pack (pinned bank/PC, engine
order, capture_box silent, callback frame == armed frame, the RAM effect one frame later on the main
loop, the refused negatives) and, on PASS, writes the PHYSICAL receipt that lua/gen2/signals.lua's
production path (S.new -> S.qualified_sites) accepts:

    tests/fixtures/gen2/receipts/<title>.engine_sites.json

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
TITLES = ("crystal", "gold", "silver")
EXPECT = ("wild_ready", "capture_party", "capture_party_finalized", "battle_end", "save_completed", "battle_faint")
# BattlePack's per-pocket input states and ItemSubmenu's USE/QUIT box (engine/items/pack.asm:685-782
# .ItemsPocketMenu/.KeyItemsPocketMenu/.TMHMPocketMenu/.BallsPocketMenu, :783-803 ItemSubmenu; the same
# lines and pocket order in pokecrystal and pokegold, resolved per title from its own .sym).
# The shared scripted gate has no pack UI kinds, so this gate adds them to its own in-memory facts.
PACK_UI = {"pack_items": "BattlePack.ItemsPocketMenu", "pack_balls": "BattlePack.BallsPocketMenu",
           "pack_key": "BattlePack.KeyItemsPocketMenu", "pack_tmhm": "BattlePack.TMHMPocketMenu",
           "item_submenu": "ItemSubmenu"}
# The faint leg's UI origins (card gen2-U1d, shared with the H1c duo through lua/tests/duo/gen2_faint_inputs.lua):
# MoveSelectionScreen.interpret_joypad re-runs after every cursor move (C engine/battle/core.asm:5432-5457);
# PartyMenuSelect is the party list of both BattleMenu_PKMN and PickPartyMonInBattle (core.asm:2842-2861,
# engine/pokemon/party_menu.asm PartyMenuSelect); BattleMonMenu is BattleMenu_PKMN.GetMenu's SWITCH/STATS/CANCEL
# (core.asm:5109-5116). Same labels in pokegold, resolved per title from its own .sym.
FAINT_UI = {"move_menu": "MoveSelectionScreen.interpret_joypad", "battle_party": "PartyMenuSelect",
            "battle_mon_menu": "BattleMonMenu"}


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
    def site(symbol):
        return {k: v for k, v in gen2_fixtures._code_site(ctx, symbol).items() if k != "symbol_offset"}

    pack_ui = {kind: site(symbol) for kind, symbol in PACK_UI.items()}
    # PokeBallEffect asks AskGiveNicknameText -> _AskGiveNicknameText (C engine/items/item_effects.asm:
    # 1113-1115, data/text/common_3.asm:1250-1255; G/S item_effects.asm:1102-1103, common_3.asm:289-294),
    # not the gift-side "received?" text the route facts bind.
    anchor = "Give a nickname to"
    assert f'_AskGiveNicknameText::\n\ttext "{anchor}"' in ctx.read_source("data/text/common_3.asm"), \
        "catch nickname anchor left the source"
    # AskUseNextPokemon prints BattleText_UseNextMon (C data/text/battle.asm:214-216, G/S :207-209); #MON
    # expands to POKéMON, so the anchor stops before it.
    next_mon = "Use next"
    assert f'BattleText_UseNextMon:\n\ttext "{next_mon} #MON?"' in ctx.read_source("data/text/battle.asm"), \
        "use-next-mon anchor left the source"
    return {"pack_ui": pack_ui, "faint_ui": {kind: site(symbol) for kind, symbol in FAINT_UI.items()},
            "decoy": decoy, "prompts": {"catch_nickname": [anchor], "next_mon": [next_mon]},
            "qualification_attempt_id": qualification_attempt_id}


def tag_json(text: str, tag: str):
    return live.tag_json(text, tag)


def verify(text: str, pack: dict, title: str) -> dict:
    """Independent re-check of the gate output; returns the receipt the gate printed."""
    sites = pack["titles"][title]["sites"]
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
    assert production["refused_title"] != title, production
    receipt = tag_json(text, "RECEIPT")
    assert receipt["title"] == title and receipt["fixture"] == f"{title}_battle", receipt
    source = pack["source"]
    assert (receipt["rom_sha1"], receipt["pack_commit"], receipt["pack_specs_sha256"]) == (
        source["rom_sha1"], source["commit"], pack["specs_sha256"])
    assert sorted(receipt["proven"]) == sorted(EXPECT) and receipt["harness_write_scopes"] == []
    assert receipt["evidence_level"] == "PHYSICAL" and receipt["decoy"]["bank_rejects"] == receipt["decoy"]["raw"]
    # the gate emits effect_to_callback_frames in the receipt, not on the ALIGN line (first live PASS 2026-09-23)
    fa = receipt["frame_alignment"]
    assert fa["effect_to_callback_frames"] == a["callback"] - a["party_changed"] >= 0, fa
    # battle_faint: re-checked here from the FAINT line, independently of F.faint_problem
    f = tag_json(text, "FAINT")
    assert f["callback"] == f["armed"] and 0 <= f["slot"] < f["party_count"], f
    assert f["battle_hp"] == 0 and f["callback_party_hp"] > 0, f
    assert (f["party_species"], f["party_dvs"]) == (f["battle_species"], f["battle_dvs"]), f
    assert f["callback"] <= f["hp_zero_frame"] <= f["callback"] + 1, f
    assert {k: v for k, v in receipt["faint_alignment"].items() if k in f} == f, receipt["faint_alignment"]
    return receipt


@pytest.mark.parametrize("title", TITLES)
def test_engine_sites_fire_at_their_routines(emuhawk, title):  # noqa: F811
    spec = gen2_fixtures.BY_NAME[f"{title}_battle"]
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

    pack = json.loads((REPO / f"data/games/gen2_{title}/engine_signals.json").read_text(encoding="utf-8"))
    receipt = verify(text, pack, title)
    assert receipt["fixture_sha256"] == hashlib.sha256(staged).hexdigest(), "receipt names other fixture bytes"
    assert receipt["qualification_attempt_id"] == qualification["attempt_id"]
    (REPO / f"tests/fixtures/gen2/receipts/{title}.engine_sites.json").write_text(json.dumps(receipt, indent=1, sort_keys=True) + "\n", encoding="utf-8")
