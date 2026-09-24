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
TITLES = ("crystal", "gold", "silver")
EXPECT = ("wild_ready", "capture_party", "capture_party_finalized", "battle_end", "save_completed", "battle_faint")
# card gen2-u1e-poison: titles whose U1 run adds the overworld poison leg (lua/tests/gen2_poison_inputs.lua).
POISON_TITLES = ("crystal", "silver", "gold")
POISON_EXPECT = EXPECT[:-1] + ("poison_faint",) + EXPECT[-1:]
# The U1 fixture per title (lua/gen2/signals.lua S.U1_FIXTURES). Gold has no day POISON_STING foe south of the
# Route 30 battle demo, so its U1 runs on the post-errand fixture (main's ruling (1)).
U1_FIXTURE = {"crystal": "crystal_battle", "gold": "gold_battle_errand", "silver": "silver_battle"}
# Route 29 -> Cherrygrove -> Route 30 (C/G data/maps/attributes.asm `connection`). Crystal/Silver hunt a wild
# Weedle in the Route 30 south grass; Gold goes on to Route 31 and Bug Catcher Wade (pokegold data/trainers/
# parties.asm BUG_CATCHER 4: Caterpie 2, Caterpie 2, WEEDLE 3, Caterpie 2; maps/Route31.asm:361).
POISON_ROUTE = {"crystal": (("Route29", "west", "CherrygroveCity"), ("CherrygroveCity", "north", "Route30")),
                "silver": (("Route29", "west", "CherrygroveCity"), ("CherrygroveCity", "north", "Route30")),
                "gold": (("Route29", "west", "CherrygroveCity"), ("CherrygroveCity", "north", "Route30"),
                         ("Route30", "north", "Route31"))}
POISON_HUNT = {"crystal": "Route30", "silver": "Route30", "gold": "Route31"}
# Two floor tiles off the hunt grass: Route 30's south exit (the first next to the south grass) / Route 31 (20,12)-(21,12).
POISON_PARK = {"crystal": ({"x": 7, "y": 49}, {"x": 7, "y": 50}), "silver": ({"x": 7, "y": 49}, {"x": 7, "y": 50}),
               "gold": ({"x": 20, "y": 12}, {"x": 21, "y": 12})}
POISON_TRAINER = {"gold": "TrainerBugCatcherWade1"}
SIDE = {"north": "Up", "south": "Down", "west": "Left", "east": "Right"}
FACING = {"UP": (0, -1), "DOWN": (0, 1), "LEFT": (-1, 0), "RIGHT": (1, 0)}


def trainers(ctx, name):
    """{script: (x, y, sight tiles)} for a map's fixed-facing OBJECTTYPE_TRAINER objects (a SPINRANDOM trainer
    faces anywhere and is left to the live battle rule)."""
    out = {}
    for line in ctx.read_source(f"maps/{name}.asm").splitlines():
        line = line.strip()
        if not line.startswith("object_event "):
            continue
        fields = [part.strip() for part in line[13:].split(",")]
        move = re.fullmatch(r"SPRITEMOVEDATA_STANDING_(UP|DOWN|LEFT|RIGHT)", fields[3])
        if fields[9] != "OBJECTTYPE_TRAINER" or not move:
            continue
        x, y, reach = int(fields[0]), int(fields[1]), int(fields[10])
        dx, dy = FACING[move[1]]
        out[fields[11]] = (x, y, [{"x": x + dx * n, "y": y + dy * n} for n in range(1, reach + 1)])
    return out


def connected(facts_map, start, goals, avoid):
    width, grid = facts_map["width"], facts_map["grid"]
    seen, todo = {start}, [start]
    blocked = {(t["x"], t["y"]) for t in avoid} | {(w["x"], w["y"]) for w in facts_map["warps"]}
    while todo:
        x, y = todo.pop()
        if (x, y) in goals:
            return True
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if (0 <= nx < width and 0 <= ny < facts_map["height"] and grid[ny * width + nx]
                    and (nx, ny) not in blocked and (nx, ny) not in seen):
                seen.add((nx, ny))
                todo.append((nx, ny))
    return False


def expect_for(title):
    return POISON_EXPECT if title in POISON_TITLES else EXPECT


def poison_facts(ctx) -> dict:
    """Source/ROM-bound maps, connection edges, the POISON_STING id and the PSN mask for the poison leg."""
    title = ctx.title
    route, hunt_name, park = POISON_ROUTE[title], POISON_HUNT[title], POISON_PARK[title]
    areas = {row["map_const"]: row for row in gen2_fixtures.build_area_map(ctx).values()}
    by_name = {row["map_name"]: row for row in areas.values()}
    names = {name for leg in route for name in (leg[0], leg[2])}
    maps = {name: gen2_fixtures._map_facts(ctx, by_name[name], areas) for name in sorted(names)}
    attributes = ctx.read_source("data/maps/attributes.asm")
    legs = []
    for source, side, target in route:
        block = attributes.split(f"map_attributes {source},", 1)[1].split("map_attributes", 1)[0]
        found = re.search(rf"^\s*connection {side}, {target}, \w+, (-?\d+)", block, re.M)
        assert found, f"source connection missing: {source} {side} {target}"
        offset = int(found[1])
        a, b = maps[source], maps[target]
        exits = []
        # the connection offset is in blocks: the target coordinate along the edge = source - 2 * offset
        for i in range(a["width"] if side in ("north", "south") else a["height"]):
            j = i - 2 * offset
            if side in ("north", "south"):
                if not 0 <= j < b["width"]:
                    continue
                ay, by_ = (0, b["height"] - 1) if side == "north" else (a["height"] - 1, 0)
                ok = a["grid"][ay * a["width"] + i] and b["grid"][by_ * b["width"] + j]
                tile = {"x": i, "y": ay}
            else:
                if not 0 <= j < b["height"]:
                    continue
                ax, bx = (0, b["width"] - 1) if side == "west" else (a["width"] - 1, 0)
                ok = a["grid"][i * a["width"] + ax] and b["grid"][j * b["width"] + bx]
                tile = {"x": ax, "y": i}
            if ok:
                exits.append(tile)
        assert exits, f"no walkable edge tile: {source} -> {target}"
        leg = {"map": source, "side": SIDE[side], "exits": exits}
        # Stay out of fixed-facing trainers' sight where the grid leaves another way (Gold Route 30: Joey at
        # (6,29) is avoided; Mikey's one tile (5,24) is the only aisle north, row 24 x=2-4 being HOP_DOWN ledges).
        avoid = []
        for _, _, sight in trainers(ctx, source).values():
            trial = avoid + sight
            entry = {(e["x"], e["y"]) for e in exits}
            starts = [(x, y) for y in range(maps[source]["height"]) for x in range(maps[source]["width"])
                      if (y in (0, maps[source]["height"] - 1) or x in (0, maps[source]["width"] - 1))
                      and maps[source]["grid"][y * maps[source]["width"] + x] and (x, y) not in entry]
            if all(connected(maps[source], start, entry, trial) for start in starts
                   if connected(maps[source], start, entry, avoid)):
                avoid = trial
        if avoid:
            leg["avoid"] = avoid
        legs.append(leg)
    hunt = maps[hunt_name]
    grass = [{"x": x, "y": y} for y in range(hunt["height"]) for x in range(hunt["width"])
             if hunt["grid"][y * hunt["width"] + x] == 2]
    for tile in park:
        assert hunt["grid"][tile["y"] * hunt["width"] + tile["x"]] == 1, f"park tile not floor: {tile}"
    moves = gen2_fixtures.const_block(ctx.read_source("constants/move_constants.asm"), "POISON_STING")
    status = gen2_fixtures.const_block(ctx.read_source("constants/battle_constants.asm"), "PSN")
    out = {"maps": maps, "legs": legs, "hunt_map": hunt_name, "hunt_grass": grass, "park": list(park),
           "moves": {"POISON_STING": moves["POISON_STING"]}, "psn_mask": 1 << status["PSN"]}
    if title in POISON_TRAINER:
        x, y, sight = trainers(ctx, hunt_name)[POISON_TRAINER[title]]
        tile = sight[-1]
        assert hunt["grid"][tile["y"] * hunt["width"] + tile["x"]] == 1, "trainer sight tile not floor"
        out["trainer"] = {"script": POISON_TRAINER[title], "x": x, "y": y, "tile": tile}
    return out
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
    prompts = {"catch_nickname": [anchor], "next_mon": [next_mon]}
    if ctx.title in POISON_TRAINER:
        # The trainer's "Will <PLAYER> change #MON?" (data/text/battle.asm BattleText_EnemyIsAboutToUse...
        # :222-231; the row "change POKeMON?" stays on screen) and Mom's Route 31 lecture yesorno
        # (data/phone/text/mom.asm:151-165, engine/phone/scripts/mom.asm:143-150).
        assert 'line "change #MON?"' in ctx.read_source("data/text/battle.asm"), "switch anchor left the source"
        assert 'line "Should I save it?"' in ctx.read_source("data/phone/text/mom.asm"), "mom anchor left the source"
        prompts.update(switch=["change "], mom_save=["Should I save it?"])
    out = {"pack_ui": pack_ui, "faint_ui": {kind: site(symbol) for kind, symbol in FAINT_UI.items()},
           "decoy": decoy, "prompts": prompts, "qualification_attempt_id": qualification_attempt_id}
    if ctx.title in POISON_TITLES:
        out["poison"] = poison_facts(ctx)
    return out


def tag_json(text: str, tag: str):
    return live.tag_json(text, tag)


def verify(text: str, pack: dict, title: str) -> dict:
    """Independent re-check of the gate output; returns the receipt the gate printed."""
    sites = pack["titles"][title]["sites"]
    expect = expect_for(title)
    summary = tag_json(text, "HIT_SUMMARY")
    for name, row in summary.items():
        if row["hits"]:
            assert (row["pc"], row["bank"], row["off_pin"]) == (sites[name]["addr"], sites[name]["bank"], 0), (name, row)
    previous = 0
    for name in expect:
        log = summary.get(name, {}).get("log") or []
        after = [hit["seq"] for hit in log if hit["seq"] > previous]
        assert after, f"{name} did not fire after the previous expected site"
        previous = after[0]
        assert all(hit["frame"] == hit.get("armed") for hit in log), (name, "callback frame != armed frame")
    assert summary["capture_party"]["hits"] == 1
    assert summary.get("capture_box", {}).get("hits", 0) == 0, "capture_box fired on a party < 6 catch"
    align = tag_json(text, "ALIGN")
    a = align["align"]
    assert align["misaligned"] == 0 and align["aligned"] >= len(expect), align
    assert a["callback"] == a["armed"] and a["callback_party"] == a["battle_party"] + 1 == a["post_party"], a
    assert a["party_changed"] <= a["callback"], a
    decoy = tag_json(text, "DECOY")
    assert decoy["raw"] >= 1 and decoy["accepted"] == 0 and decoy["bank_rejects"] == decoy["raw"], decoy
    negatives = tag_json(text, "NEGATIVES")
    assert negatives["control"] == "bound", negatives
    assert "differ from the ROM" in negatives["wrong_pack_byte"], negatives
    assert "script bytecode" in negatives["script_bytecode_arm"], negatives
    production = tag_json(text, "PRODUCTION")
    assert sorted(production["registered"]) == sorted(expect), production
    assert production["refused_title"] != title, production
    receipt = tag_json(text, "RECEIPT")
    assert receipt["title"] == title and receipt["fixture"] == U1_FIXTURE[title], receipt
    source = pack["source"]
    assert (receipt["rom_sha1"], receipt["pack_commit"], receipt["pack_specs_sha256"]) == (
        source["rom_sha1"], source["commit"], pack["specs_sha256"])
    assert sorted(receipt["proven"]) == sorted(expect) and receipt["harness_write_scopes"] == []
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
    if "poison_faint" in expect:
        # poison_faint: re-checked here from the POISON / POISON_MODEL lines, independently of F.poison_problem
        p, m = tag_json(text, "POISON"), tag_json(text, "POISON_MODEL")
        psn = receipt["poison_alignment"]["psn_mask"]
        assert p["callback"] == p["armed"] and 0 <= p["slot"] < p["party_count"] and p["battle_mode"] == 0, p
        assert p["callback_hp"] == 0 and p["callback_status"] & psn and p["pre_hp"] in (0, 1), p
        assert p["callback"] <= p["status_zero_frame"] <= p["callback"] + 1, p
        assert len(m["events"]) == 1, m
        e = m["events"][0]
        assert (e["kind"], e["cause"], e["site_id"]) == ("faint", "poison", "poison_faint"), e
        assert (e["slot"], e["species"], e["dvs"]) == (p["slot"], p["species"], p["dvs"]), (e, p)
        assert {k: v for k, v in receipt["poison_alignment"].items() if k in p} == p, receipt["poison_alignment"]
    return receipt


@pytest.mark.parametrize("title", TITLES)
def test_engine_sites_fire_at_their_routines(emuhawk, title):  # noqa: F811
    spec = gen2_fixtures.BY_NAME[U1_FIXTURE[title]]
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
    env["SLINK_GEN2_U1_FACTS"] = json.dumps(u1_facts(ctx, gen2_fixtures.spec_route_facts(spec, REPO),
                                                     qualification["attempt_id"]))
    passed, path, text = run_gate(GATE, rom_key=spec.title, target=spec.target,
                                  timeout=2400 if title in POISON_TITLES else 1200,
                                  saveram_dir=str(REPO / ".cache/gen2-fixtures/u1-hook-proof" / spec.name),
                                  fixture_path=str(fixture), speed_percent=300, env_overrides=env)
    assert passed, f"gate FAILED; result {path}: {text[-3000:]}"
    assert fixture.read_bytes() == staged, "fixture changed while the gate ran"

    pack = json.loads((REPO / f"data/games/gen2_{title}/engine_signals.json").read_text(encoding="utf-8"))
    receipt = verify(text, pack, title)
    assert receipt["fixture_sha256"] == hashlib.sha256(staged).hexdigest(), "receipt names other fixture bytes"
    assert receipt["qualification_attempt_id"] == qualification["attempt_id"]
    (REPO / f"tests/fixtures/gen2/receipts/{title}.engine_sites.json").write_text(json.dumps(receipt, indent=1, sort_keys=True) + "\n", encoding="utf-8")
