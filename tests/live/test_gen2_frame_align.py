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

OVERLAY (docs/gen2/OVERLAY_ADMISSION.md D4/D7): SLINK_GEN2_ARTIFACT=overlay boots <title>_overlay on the overlay
qualification receipt (tests/fixtures/gen2/receipts/overlay/<fixture>.qualification.json), arms the overlay execution
binding's own sites (data/games/gen2_<t>/overlay/binding.json) and writes
tests/fixtures/gen2/receipts/overlay/<title>.engine_sites.json; the clean files are never touched. The recorded
identity (rom_sha1, binding_sha256) is checked against the hashed staged overlay, not the environment.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tools"))

from tests.live import test_gen2_new_gates as live  # noqa: E402
from tests.live.test_gen2_new_gates import emuhawk  # noqa: E402,F401 - pytest fixture
from tools import gen2_fixtures, gen2_synth_fixtures  # noqa: E402

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
# O-33 clock setup (tools/gen2_synth_fixtures.day_clock, disclosed in the receipt as clock_setup), as the W6 gate's U1 leg
# (tests/live/test_gen2_w6_gate.py U1_CLOCK): the fixture RTC runs on with the host clock, and Silver's POISON_STING and
# evolution hunts need Route 30 Weedle, morning/day only (pokegold data/wild/johto_grass.asm ROUTE_30, _SILVER nite:
# Hoothoot/Rattata). Only the emulator RTC trailer changes; the CartRAM is the committed fixture's.
# Crystal and Gold hunt Route 30's CATERPIE the same way (data/wild/johto_grass.asm ROUTE_30 day/nite: night is
# SPINARAK/HOOTHOOT/POLIWAG/ZUBAT, no Caterpie at all) for the u1-evolution leg (EVOLUTION_TITLES below), so an
# un-pinned RTC leaves them exposed to the exact same real-clock coin-flip: fsw-postrc 2026-09-25,
# gate/engine_sites/crystal ran its whole ~880-battle Route 30 hunt at hour 23/0/1/2 and never saw a Caterpie.
U1_CLOCK = {"crystal": 11, "gold": 11, "silver": 11}
# Fixed attempts, shared by clean/overlay. Repeating 11:00 can replay the same RNG
# sequence; use the duo's 23-minute spacing, with no search for a favourable seed.
U1_RETRY_MINUTES = (0, 23, 46)


def u1_clock_setup(raw: bytes, title: str, *, now: int):
    attempt = os.environ.get("SLINK_GEN2_U1_ATTEMPT", "1")
    if attempt not in ("1", "2", "3"):
        raise ValueError("SLINK_GEN2_U1_ATTEMPT must be 1, 2 or 3")
    minute = U1_RETRY_MINUTES[int(attempt) - 1]
    boot, clock = gen2_synth_fixtures.day_clock(raw, hour=U1_CLOCK[title], now=now, title=title, minute=minute)
    # New U1 evidence is explicit even for attempt 1; legacy day_clock callers
    # retain their byte-identical omission of zero minutes/seconds.
    clock.update(game_minute=minute, game_second=0)
    return boot, clock


def u1_receipt_metadata(clock: dict) -> dict:
    """Bind the attempt to the clock that actually staged this capture."""
    if clock.get("game_hour") != 11 or clock.get("game_second") != 0 or clock.get("game_minute") not in U1_RETRY_MINUTES:
        raise ValueError("U1 clock is outside the prescribed attempt schedule")
    return {"u1_attempt": U1_RETRY_MINUTES.index(clock["game_minute"]) + 1, "clock_setup": clock}


# Route 29 -> Cherrygrove -> Route 30 (C/G data/maps/attributes.asm `connection`). Crystal/Silver hunt a wild
# Weedle in the Route 30 south grass; Gold goes on to Route 31 and Bug Catcher Wade (pokegold data/trainers/
# parties.asm BUG_CATCHER 4: Caterpie 2, Caterpie 2, WEEDLE 3, Caterpie 2; maps/Route31.asm:361). This is the
# route every OTHER caller still gets (the duo scenarios' natural, unpoisoned Gold boot included, tools/
# e2e_duo.py -> u1_facts -> poison_facts): only test_engine_sites_fire_at_their_routines's own gold_synth_psn
# gate run passes synth_psn=True below, which is the ONLY place the SYNTH_PSN_* override applies (card
# gen2-u1e-poison regression, re-sweep 7ba4d552: an earlier cut changed POISON_ROUTE["gold"] etc. directly,
# which every OTHER Gold caller shares too, breaking the duo's natural Wade-route Gold player).
POISON_ROUTE = {"crystal": (("Route29", "west", "CherrygroveCity"), ("CherrygroveCity", "north", "Route30")),
                "silver": (("Route29", "west", "CherrygroveCity"), ("CherrygroveCity", "north", "Route30")),
                "gold": (("Route29", "west", "CherrygroveCity"), ("CherrygroveCity", "north", "Route30"),
                         ("Route30", "north", "Route31"))}
POISON_HUNT = {"crystal": "Route30", "silver": "Route30", "gold": "Route31"}
# Two floor tiles off the hunt grass: Route 30's south exit (the first next to the south grass) / Route 31 (20,12)-(21,12).
POISON_PARK = {"crystal": ({"x": 7, "y": 49}, {"x": 7, "y": 50}), "silver": ({"x": 7, "y": 49}, {"x": 7, "y": 50}),
               "gold": ({"x": 20, "y": 12}, {"x": 21, "y": 12})}
POISON_TRAINER = {"gold": "TrainerBugCatcherWade1"}
# Gold heals at the Cherrygrove #MON CENTER before Mikey/Don/Wade (Gold run 5 wore the party down). Crystal and
# Silver heal there too: a worn Route 30 hunt goes back through Route 30's south connection and retries (card
# driver-robust; lua/tests/gen2_poison_inputs.lua worn()).
POISON_HEAL = dict.fromkeys(("crystal", "gold", "silver"), ("CherrygroveCity", "CherrygrovePokecenter1F"))
# card gen2-u1e-poison O-33 fallback (owner-approved 2026-09-25): the Wade fight above is a proven, deterministic
# LOSS with the driver as written (fsw-postrc-rr9/rr10, identical stall @51461 both attempts, "both mons PSN"),
# and getting poisoned there was always SETUP, not the behaviour under test (DoPoisonStep.DamageMonIfPoisoned's
# faint branch, engine/events/poisonstep.asm:88-94). gold_synth_psn (tools/gen2_synth_fixtures.py PSN_RECIPES)
# pins PSN onto the errand's own lead instead, so ITS OWN gate run (only) skips travel/hunt/heal/trainer entirely
# and ticks+parks on the SAME Route 29 map its own catch already happened on: (53,11) is the floor tile directly
# north of the O-10 grass patch the errand's catch ends in (xy 52-53,12, fsw-postrc-psn1/2/3/4), (52,11) its own
# floor neighbour (gen2_fixtures._map_facts collision grid) -- a first attempt used a floor-adjacent-to-grass
# pair on the FAR side of the 60-wide map (x=4) and the long walk back there crossed enough Route 29 grass to
# trigger a wild encounter mid-tick (fsw-postrc-psn2: "a battle started on the park tiles"); both re-asserted
# floor at runtime below like every other title's pair.
# Titles whose U1 poison leg boots a disclosed SYNTH poisoned lead (tools/gen2_synth_fixtures.py PSN_FIXTURES) instead
# of hunting a poisoner: Gold (its Wade fight is a deterministic loss) and Crystal (its Weedle hunt is a lottery).
# Silver still hunts. Both catch on the SAME Route 29 patch (xy 52-53,12), so the park pair below serves both.
SYNTH_PSN_FIXTURE = {"gold": "gold_synth_psn", "crystal": "crystal_synth_psn_u1"}
SYNTH_PSN_HUNT = "Route29"
SYNTH_PSN_PARK = ({"x": 53, "y": 11}, {"x": 52, "y": 11})
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


# The collision decode and the ledges field live in tools/gen2_fixtures (card driver-robust: one source for
# every scripted walker, lua/tests/gen2_walk.lua).
collision_names = gen2_fixtures.collision_names
ledges = gen2_fixtures.map_ledges


def collision_name(ctx, name, facts_map, x, y):
    return collision_names(ctx, name, facts_map)[y][x]


def edge_leg(ctx, maps, source, side, target):
    """{map, side, exits}: the source edge tiles whose connection partner tile is walkable too
    (data/maps/attributes.asm `connection`; the offset is in blocks, target = source - 2 * offset)."""
    attributes = ctx.read_source("data/maps/attributes.asm")
    block = attributes.split(f"map_attributes {source},", 1)[1].split("map_attributes", 1)[0]
    found = re.search(rf"^\s*connection {side}, {target}, \w+, (-?\d+)", block, re.M)
    assert found, f"source connection missing: {source} {side} {target}"
    offset = int(found[1])
    a, b = maps[source], maps[target]
    exits = []
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
    return {"map": source, "side": SIDE[side], "exits": exits}


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


# card gen2-u1f-pc: after the U1e chain's closing whiteout, a second catch, then Bill's PC at the Cherrygrove
# #MON CENTER (lua/tests/gen2_pc_inputs.lua). whiteout_before_heal is proven by its own guard-matching record
# (F.whiteout_problem), not by the hit log, since `Special` is a hot shared site.
U1F_TITLES = ("crystal", "gold", "silver")
U1F_SITES = ("pc_deposit_begin", "pc_deposit_complete", "pc_withdraw_begin", "pc_withdraw_complete",
             "change_box_begin", "change_box_loaded", "pc_release_box_begin", "pc_release_box_complete",
             "pc_release_party_begin", "pc_release_party_complete")
# where each title's closing whiteout lands: GetWhiteoutSpawn (engine/events/whiteout.asm) -> wLastSpawnMap,
# SPAWN_HOME = PlayersHouse2F (3,3) before the errand; the errand's `blackoutmod CHERRYGROVE_CITY`
# (pokegold maps/MrPokemonsHouse.asm:37) moves Gold's to Cherrygrove.
U1F_TO_GRASS = {"PlayersHouse2F": ("warp", "PLAYERS_HOUSE_1F"), "PlayersHouse1F": ("warp", "NEW_BARK_TOWN"),
                "NewBarkTown": ("edge", "west", "Route29"), "CherrygroveCity": ("edge", "east", "Route29"),
                "CherrygrovePokecenter1F": ("warp", "CHERRYGROVE_CITY"), "Route29": ("grass",)}
U1F_TO_PC = {"PlayersHouse2F": ("warp", "PLAYERS_HOUSE_1F"), "PlayersHouse1F": ("warp", "NEW_BARK_TOWN"),
             "NewBarkTown": ("edge", "west", "Route29"), "Route29": ("edge", "west", "CherrygroveCity"),
             "CherrygroveCity": ("warp", "CHERRYGROVE_POKECENTER_1F"), "CherrygrovePokecenter1F": ("pc",)}


# card EVO-U1: after the PC leg, a Route 30 day catch evolves at L7 (lua/tests/gen2_evolution_inputs.lua). Caterpie
# (Crystal/Gold) and Weedle (Silver): data/pokemon/evos_attacks.asm CaterpieEvosAttacks/WeedleEvosAttacks (EVOLVE_LEVEL 7);
# data/wild/johto_grass.asm ROUTE_30 day slots (C: Caterpie L3/L4 30%+20%; G: Caterpie L3 30% + L4 5%; S: Weedle L3 30%
# + L4 5%).
EVOLUTION_TITLES = ("crystal", "gold", "silver")
EVOLUTION_TARGET = {"crystal": ("CATERPIE", "METAPOD"), "gold": ("CATERPIE", "METAPOD"), "silver": ("WEEDLE", "KAKUNA")}
EVOLUTION_SITE = "evolution_species_published"
EVOLUTION_DAMAGING = ("TACKLE", "SCRATCH", "POISON_STING", "RAGE", "WATER_GUN")   # EV.DAMAGING's constants


def expect_for(title):
    out = POISON_EXPECT if title in POISON_TITLES else EXPECT
    out = out + U1F_SITES + ("whiteout_before_heal",) if title in U1F_TITLES else out
    return out + (EVOLUTION_SITE,) if title in EVOLUTION_TITLES else out


def evolution_facts(ctx) -> dict:
    """The Cherrygrove #MON CENTER (nurse, carpet), Cherrygrove <-> Route 30 edges, the south Route 30 grass patch, the
    target/evolved species ids, POISON_STING and the damaging moves' ids, all from the pinned source."""
    areas = {row["map_const"]: row for row in gen2_fixtures.build_area_map(ctx).values()}
    by_name = {row["map_name"]: row for row in areas.values()}
    names = ("CherrygrovePokecenter1F", "CherrygroveCity", "Route30", "Route29")
    maps = {name: gen2_fixtures._map_facts(ctx, by_name[name], areas) for name in names}
    for name, facts_map in maps.items():
        facts_map["ledges"] = ledges(ctx, name, facts_map)
    center, city, hunt = (maps[name] for name in names[:3])
    door = next(w for w in city["warps"] if w["destination"] == by_name["CherrygrovePokecenter1F"]["map_const"])
    exit_ = next(w for w in center["warps"] if w["destination"] == city["map_const"])
    nurse = next(o for script, o in center["objects"].items() if script.endswith("NurseScript"))
    stand = {"x": nurse["x"], "y": nurse["y"] + 2}   # across the counter row, facing up (PokecenterNurseScript)
    assert center["grid"][stand["y"] * center["width"] + stand["x"]] == 1, "nurse stand tile not floor"
    # the grass patch nearest the south connection: flood-fill the grass from its southernmost tile
    width = hunt["width"]
    grass = {(x, y) for y in range(hunt["height"]) for x in range(width) if hunt["grid"][y * width + x] == 2}
    todo = [max(grass, key=lambda t: (t[1], -t[0]))]
    patch = set(todo)
    while todo:
        x, y = todo.pop()
        for n in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if n in grass and n not in patch:
                patch.add(n)
                todo.append(n)
    sight = {(t["x"], t["y"]) for _, _, tiles in trainers(ctx, "Route30").values() for t in tiles}
    assert not patch & sight, "a trainer sees the south Route 30 grass"
    species = gen2_fixtures.const_block(ctx.read_source("constants/pokemon_constants.asm"), "CATERPIE")
    moves = gen2_fixtures.const_block(ctx.read_source("constants/move_constants.asm"), "POISON_STING")
    target, evolved = EVOLUTION_TARGET[ctx.title]
    evos = ctx.read_source("data/pokemon/evos_attacks.asm")
    assert f"{target.title()}EvosAttacks:\n\tdb EVOLVE_LEVEL, 7, {evolved}\n" in evos, "evolution row left the source"
    nurse_anchor = "Shall we heal your"
    assert f'para "{nurse_anchor}' in ctx.read_source("data/text/std_text.asm"), "nurse anchor left the source"
    return {"maps": maps, "center": "CherrygrovePokecenter1F", "city": "CherrygroveCity", "hunt": "Route30",
            "hunt_grass": [{"x": x, "y": y} for x, y in sorted(patch, key=lambda t: (t[1], t[0]))],
            "door": {"x": door["x"], "y": door["y"]}, "stand": stand,
            "exit": {"x": exit_["x"], "y": exit_["y"], "carpet": exit_["carpet"]},
            "north": edge_leg(ctx, maps, "CherrygroveCity", "north", "Route30"),
            "south": edge_leg(ctx, maps, "Route30", "south", "CherrygroveCity"),
            "approach": edge_leg(ctx, maps, "Route29", "west", "CherrygroveCity"),   # a start on the fixture map
            "target": species[target], "evolves_to": species[evolved], "poison_sting": moves["POISON_STING"],
            "run_from_sting": target != "WEEDLE",   # a poisoned Caterpie loses HP on the walk; Weedle is POISON-type
            "damaging_ids": {str(moves[name]): True for name in EVOLUTION_DAMAGING},
            "prompts": {"nurse_heal": [nurse_anchor]}}


def u1f_facts(ctx) -> dict:
    """Maps, per-map legs to the Route 29 grass and to the Cherrygrove #MON CENTER PC, the PC tile, the Bill's PC
    UI origins and the PC RAM symbols the PC leg reads its cursors and counts from."""
    areas = {row["map_const"]: row for row in gen2_fixtures.build_area_map(ctx).values()}
    by_name = {row["map_name"]: row for row in areas.values()}
    names = sorted(set(U1F_TO_GRASS) | set(U1F_TO_PC) | {"Route29", "CherrygroveCity"})
    maps = {name: gen2_fixtures._map_facts(ctx, by_name[name], areas) for name in names}
    for name, facts_map in maps.items():
        facts_map["ledges"] = ledges(ctx, name, facts_map)

    def legs(plan):
        out = {}
        for name, step in plan.items():
            if step[0] == "warp":
                warp = next(w for w in maps[name]["warps"] if w["destination"] == step[1])
                out[name] = {"kind": "warp", "tile": {"x": warp["x"], "y": warp["y"]}, "carpet": warp["carpet"]}
            elif step[0] == "edge":
                out[name] = dict(edge_leg(ctx, maps, name, step[1], step[2]), kind="edge")
            else:
                out[name] = {"kind": step[0]}
        return out

    center = maps["CherrygrovePokecenter1F"]
    # The PC is the COLL_PC tile of the shared Pokecenter1F layout (row 1); it is used facing it from below
    # (PokemonCenterPC, engine/events/pokecenter_pc.asm:15-41, via the facing-tile collision).
    grid = collision_names(ctx, "CherrygrovePokecenter1F", center)   # once, not once per cell
    pc = [(x, y) for y in range(center["height"]) for x in range(center["width"]) if grid[y][x] == "PC"]
    assert len(pc) == 1, pc
    stand = {"x": pc[0][0], "y": pc[0][1] + 1}
    assert center["grid"][stand["y"] * center["width"] + stand["x"]] == 1, "PC stand tile not floor"

    def site(symbol):
        return {k: v for k, v in gen2_fixtures._code_site(ctx, symbol).items() if k != "symbol_offset"}

    # Bill's PC UI origins, each read from the pinned source (C/G engine/events/pokecenter_pc.asm,
    # engine/pokemon/bills_pc_top.asm, engine/pokemon/bills_pc.asm):
    #   pc_top          PokemonCenterPC.loop (the BILL's PC / <PLAYER>'s PC / TURN OFF menu, :31-41)
    #   bills_pc        _BillsPC.loop (WITHDRAW / DEPOSIT / CHANGE BOX / MOVE W/O MAIL / SEE YA!, :49-66)
    #   deposit_list    _DepositPKMN.HandleJoypad (per frame, bills_pc.asm:72)
    #   deposit_menu    _DepositPKMN.Submenu (DEPOSIT / STATS / RELEASE / CANCEL, :130-133, :228-240)
    #   withdraw_list   _WithdrawPKMN.Joypad (per frame)
    #   withdraw_menu   BillsPC_Withdraw (WITHDRAW / STATS / RELEASE / CANCEL)
    #   box_list        _ChangeBox.loop (the BOX1..BOX14 scrolling list, SetDefaultBoxNames intro_menu.asm:148-178)
    #   box_menu        BillsPC_ChangeBoxSubmenu (SWITCH / NAME / PRINT / QUIT)
    ui = {"pc_top": site("PokemonCenterPC.loop"), "bills_pc": site("_BillsPC.loop"),
          "deposit_list": site("_DepositPKMN.HandleJoypad"), "deposit_menu": site("_DepositPKMN.Submenu"),
          "withdraw_list": site("_WithdrawPKMN.Joypad"), "withdraw_menu": site("BillsPC_Withdraw"),
          "box_list": site("_ChangeBox.loop"), "box_menu": site("BillsPC_ChangeBoxSubmenu")}
    ram = {}
    for name in ("wBillsPC_CursorPosition", "wBillsPC_ScrollPosition", "wCurBox", "sBoxCount"):
        symbol = ctx.symbol(name)
        ram[name] = {"bank": symbol.bank, "addr": symbol.address}
    common = "".join(ctx.read_source(f"data/text/common_{n}.asm") for n in (1, 2, 3))
    source_pc = ctx.read_source("engine/pokemon/bills_pc.asm")
    assert 'PCString_ReleasePKMN: db "Release <PK><MN>?@"' in source_pc, "release anchor left the source"
    assert 'cont "will be saved. OK?"' in common, "change-box save anchor left the source"
    return {"maps": maps, "to_grass": legs(U1F_TO_GRASS), "to_pc": legs(U1F_TO_PC), "center": "CherrygrovePokecenter1F",
            "pc_stand": stand, "ui": ui, "menus": ["pc_top", "bills_pc", "deposit_menu", "withdraw_menu", "box_list",
                                                   "box_menu"],
            "loops": ["deposit_list", "withdraw_list"], "ram": ram,
            "prompts": {"release": ["Release "], "change_box_save": ["will be saved"]}}


def poison_facts(ctx, *, synth_psn=False) -> dict:
    """Source/ROM-bound maps, connection edges, the POISON_STING id and the PSN mask for the poison leg.

    synth_psn: ONLY test_engine_sites_fire_at_their_routines's own gold_synth_psn gate run passes this -- every
    other caller (the duo scenarios included, tools/e2e_duo.py -> u1_facts -> poison_facts) gets Gold's natural
    Wade route. True skips travel/hunt/heal/trainer for the SYNTH_PSN_* Route 29 tick+park facts instead (the
    boot fixture is already poisoned; card gen2-u1e-poison, regression fix re-sweep 7ba4d552)."""
    title = ctx.title
    if synth_psn:
        if title not in SYNTH_PSN_FIXTURE:
            raise ValueError(f"synth_psn facts are Gold/Crystal-only ({sorted(SYNTH_PSN_FIXTURE.values())})")
        route, hunt_name, park, heal, trainer = (), SYNTH_PSN_HUNT, SYNTH_PSN_PARK, None, None
    else:
        route, hunt_name, park = POISON_ROUTE[title], POISON_HUNT[title], POISON_PARK[title]
        heal, trainer = POISON_HEAL.get(title), POISON_TRAINER.get(title)   # both None when absent
    areas = {row["map_const"]: row for row in gen2_fixtures.build_area_map(ctx).values()}
    by_name = {row["map_name"]: row for row in areas.values()}
    names = {name for leg in route for name in (leg[0], leg[2])} | set(heal or ()) | {hunt_name}
    maps = {name: gen2_fixtures._map_facts(ctx, by_name[name], areas) for name in sorted(names)}
    for name, facts_map in maps.items():
        facts_map["ledges"] = ledges(ctx, name, facts_map)
    legs = []
    for source, side, target in route:
        leg = edge_leg(ctx, maps, source, side, target)
        exits = leg["exits"]
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
    if synth_psn:
        # no travel/hunt legs: the boot fixture is already poisoned (gold_synth_psn); start the driver
        # straight in "tick" (lua/tests/gen2_poison_inputs.lua PI.driver facts.start_phase).
        out["start_phase"] = "tick"
    if heal:
        city_name, center_name = heal
        city, center = maps[city_name], maps[center_name]
        door = next(w for w in city["warps"] if w["destination"] == by_name[center_name]["map_const"])
        exits = [w for w in center["warps"] if w["destination"] == city["map_const"]]
        nurse = next(o for script, o in center["objects"].items() if script.endswith("NurseScript"))
        stand = {"x": nurse["x"], "y": nurse["y"] + 2}   # across the counter row, facing up
        assert center["grid"][stand["y"] * center["width"] + stand["x"]] == 1, "nurse stand tile not floor"
        # the way back for a second heal: the hunt route's maps north of the city, by their south connections
        back = [edge_leg(ctx, maps, "Route30", "south", city_name)]
        if "Route31" in maps:
            back.append(edge_leg(ctx, maps, "Route31", "south", "Route30"))
        out["heal"] = {"city": city_name, "center": center_name, "door": {"x": door["x"], "y": door["y"]}, "back": back,
                       "stand": stand, "exit": {"x": exits[0]["x"], "y": exits[0]["y"], "carpet": exits[0]["carpet"]}}
    if trainer:
        x, y, sight = trainers(ctx, hunt_name)[trainer]
        tile = sight[-1]
        assert hunt["grid"][tile["y"] * hunt["width"] + tile["x"]] == 1, "trainer sight tile not floor"
        out["trainer"] = {"script": trainer, "x": x, "y": y, "tile": tile}
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


def u1_facts(ctx, facts, qualification_attempt_id: str, *, synth_psn=False) -> dict:
    """Pack-UI origins and the wrong-bank decoy: the overworld tick PC in the highest bank that carries
    no symbol and only zero bytes there (never executed), so a hit can only be the real bank's code.

    synth_psn: forwarded to poison_facts (Gold's gold_synth_psn gate run only; see its own docstring)."""
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
    if ctx.title in POISON_HEAL:
        # NurseAskHealText (data/text/std_text.asm:21-27), asked by PokecenterNurseScript (std_scripts.asm:80-81)
        assert 'para "Shall we heal your"' in ctx.read_source("data/text/std_text.asm"), "nurse anchor left the source"
        prompts["nurse_heal"] = ["Shall we heal your"]
    out = {"pack_ui": pack_ui, "faint_ui": {kind: site(symbol) for kind, symbol in FAINT_UI.items()},
           "decoy": decoy, "prompts": prompts, "qualification_attempt_id": qualification_attempt_id}
    if ctx.title in U1F_TITLES:
        out["pc"] = u1f_facts(ctx)
        prompts.update(out["pc"]["prompts"])
    if ctx.title in POISON_TITLES:
        out["poison"] = poison_facts(ctx, synth_psn=synth_psn)
    if ctx.title in EVOLUTION_TITLES:
        out["evolution"] = evolution_facts(ctx)
        prompts.update(out["evolution"]["prompts"])
    return out


def tag_json(text: str, tag: str):
    return live.tag_json(text, tag)


def parse_poison_hunt(text: str) -> dict | None:
    """Read diagnostic evidence on PASS or FAIL; older logs have neither marker.

    A mismatch count remains visible rather than being reinterpreted as bad luck.
    These observations are not a substitute for the poison_faint site proof.
    """
    encounters = [json.loads(line.removeprefix("POISON_ENCOUNTER ")) for line in text.splitlines()
                  if line.startswith("POISON_ENCOUNTER ")]
    summaries = [json.loads(line.removeprefix("POISON_HUNT ")) for line in text.splitlines()
                 if line.startswith("POISON_HUNT ")]
    if not summaries and not encounters:
        return None
    if len(summaries) != 1 or not isinstance(summaries[0], dict):
        raise ValueError("poison hunt needs exactly one summary")
    summary = summaries[0]
    fields = ("encounters", "candidates", "unreadable", "foe_sting_mismatches")
    if summary.get("schema") != "gen2-poison-hunt-summary-v1" or any(
            type(summary.get(key)) is not int or summary[key] < 0 for key in fields):
        raise ValueError("poison hunt summary malformed")
    counts = dict.fromkeys(fields, 0)
    for index, row in enumerate(encounters, 1):
        if (not isinstance(row, dict) or row.get("schema") != "gen2-poison-hunt-encounter-v1"
                or type(row.get("encounter")) is not int or row["encounter"] != index
                or any(type(row.get(key)) is not bool for key in ("readable", "candidate", "foe_sting"))):
            raise ValueError("poison hunt encounter malformed or out of order")
        moves = row.get("moves")
        if (not isinstance(moves, list) or any(type(move) is not int or not 0 <= move <= 255 for move in moves)
                or type(row.get("species_id")) is not int or type(row.get("level")) is not int):
            raise ValueError("poison hunt foe data malformed")
        if row["readable"]:
            if len(moves) != 4 or not 1 <= row["species_id"] <= 251 or not 1 <= row["level"] <= 100:
                raise ValueError("poison hunt foe data outside Gen 2 bounds")
        elif moves or row["species_id"] != 0 or row["level"] != 0:
            raise ValueError("unreadable poison hunt foe carries invented data")
        candidate = row["readable"] and 0x28 in moves  # POISON_STING, pinned GSC move constant
        if row["candidate"] != candidate:
            raise ValueError("poison hunt candidate disagrees with raw move IDs")
        counts["encounters"] += 1
        counts["candidates"] += candidate
        counts["unreadable"] += not row["readable"]
        counts["foe_sting_mismatches"] += row["readable"] and candidate != row["foe_sting"]
    if any(summary[key] != counts[key] for key in fields):
        raise ValueError("poison hunt summary disagrees with encounter records")
    return summary


def verify(text: str, pack: dict, title: str, identity: dict | None = None) -> dict:
    """Independent re-check of the gate output; returns the receipt the gate printed.

    identity: run_gb_gate.artifact_identity of the staged artifact; None is the clean pack exactly as before."""
    overlay = identity is not None and identity["kind"] == "overlay"
    sites = gen2_fixtures.exec_sites(title, "overlay", REPO) if overlay else pack["titles"][title]["sites"]
    expect = expect_for(title)
    summary = tag_json(text, "HIT_SUMMARY")
    for name, row in summary.items():
        if row["hits"]:
            assert (row["pc"], row["bank"], row["off_pin"]) == (sites[name]["addr"], sites[name]["bank"], 0), (name, row)
    previous = 0
    for name in expect:
        if name == "whiteout_before_heal":   # a hot shared site: proven by its WHITEOUT record below
            continue
        log = summary.get(name, {}).get("log") or []
        after = [hit["seq"] for hit in log if hit["seq"] > previous]
        assert after, f"{name} did not fire after the previous expected site"
        previous = after[0]
        assert all(hit["frame"] == hit.get("armed") for hit in log), (name, "callback frame != armed frame")
    u1f = "whiteout_before_heal" in expect
    evolution = EVOLUTION_SITE in expect
    assert summary["capture_party"]["hits"] == (2 if u1f else 1) + (1 if evolution else 0)
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
    assert (receipt["pack_commit"], receipt["pack_specs_sha256"]) == (source["commit"], pack["specs_sha256"])
    if overlay:   # the overlay's own sha1 and sidecar, equal to the HASHED staged artifact (never the clean pack's)
        gen2_fixtures.check_run_identity(receipt, identity)
    else:
        assert receipt["rom_sha1"] == source["rom_sha1"] and "artifact_kind" not in receipt
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
    if u1f:
        # U1f: re-checked from the WHITEOUT / U1F_MODEL lines, independently of F.whiteout_problem
        w, m = tag_json(text, "WHITEOUT"), tag_json(text, "U1F_MODEL")
        assert w["callback"] == w["armed"] and w["de"] == 27 and w["party_hp"] and not any(w["party_hp"]), w
        assert w["healed_frame"] >= w["callback"], w
        faints = [hit["seq"] for hit in summary["battle_faint"]["log"]]
        # the CLOSING faint is the last one before the whiteout; a later leg (the evolution grind) may faint
        # again after it (round-2 Gold: faints [9, 72] around whiteout 12), so never compare to max(faints)
        assert any(seq < w["seq"] for seq in faints), (w, faints)
        captures = [hit["seq"] for hit in summary["capture_party"]["log"]]
        assert captures[0] < w["seq"] < captures[1] < summary["pc_deposit_begin"]["log"][0]["seq"], (captures, w)
        counts = {}
        for e in m["events"]:
            k = f"pc_release_{e['collection']}" if e["kind"] == "pc_release" else e["kind"]
            counts[k] = counts.get(k, 0) + 1
        assert counts == {"whiteout": 1, "party_to_box": 2, "box_to_party": 1, "box_change": 1,
                          "pc_release_box": 1, "pc_release_party": 1}, (counts, m)
        assert receipt["pc_alignment"]["model_events"] == counts, receipt["pc_alignment"]
        assert {k: v for k, v in receipt["whiteout_alignment"].items() if k in w} == w, receipt["whiteout_alignment"]
    if evolution:
        # evolution: re-checked from the EVOLUTION / EVOLUTION_MODEL lines, independently of F.evolution_problem
        e, m = tag_json(text, "EVOLUTION"), tag_json(text, "EVOLUTION_MODEL")
        old = sites[EVOLUTION_SITE]["identity_migration"]["old_species_by_new"][str(e["a"])]
        assert e["callback"] == e["armed"] and 0 <= e["slot"] < e["party_count"] and e["link_mode"] == 0, e
        assert e["a"] == e["list_species"] == e["struct_species"] and e["hl"] == e["list_addr"], e
        assert e["pre_list_species"] == old, (e, old)
        assert summary[EVOLUTION_SITE]["log"][0]["seq"] > summary["capture_party"]["log"][2]["seq"], summary
        assert len(m["events"]) == 1, m
        k = m["events"][0]
        assert (k["kind"], k["reason"], k["site_id"], k["slot"]) == ("key_change", "evolution", EVOLUTION_SITE, e["slot"]), k
        assert (k["old_key"], k["new_key"]) == (f"{e['dvs']:04X}:{e['ot']:04X}:{old:02X}",
                                                f"{e['dvs']:04X}:{e['ot']:04X}:{e['a']:02X}"), (k, e)
        assert {key: v for key, v in receipt["evolution_alignment"].items() if key in e} == e, receipt["evolution_alignment"]
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
    hunt = parse_poison_hunt(text)
    if hunt is not None:
        receipt["poison_hunt"] = hunt
    return receipt


@pytest.mark.parametrize("title", TITLES)
def test_engine_sites_fire_at_their_routines(emuhawk, title):  # noqa: F811
    spec = gen2_fixtures.BY_NAME[U1_FIXTURE[title]]
    kind = live.KIND
    reason = (live.rom_missing_reason(spec.title) or live.fixture_missing_reason(spec.name)
              or live.receipt_missing_reason(spec.name))
    if reason:
        pytest.skip(reason)
    from run_gb_gate import run_gate

    fixture = REPO / "tests/fixtures/gen2" / f"{spec.name}.SaveRAM"
    staged = fixture.read_bytes()
    live.qualified_identity(spec.name, staged)   # the staged bytes are the qualified candidate
    ctx = gen2_fixtures.exec_context(spec.title, kind, REPO)   # overlay-resolved symbols/bytes on an overlay run
    env = live.inspect_env(spec, staged)
    qualification = json.loads(live.receipt_file(f"{spec.name}.qualification.json").read_text(encoding="utf-8"))
    env["SLINK_GEN2_U1_FACTS"] = json.dumps(u1_facts(ctx, gen2_fixtures.spec_route_facts(spec, REPO, kind=kind),
                                                     qualification["attempt_id"], synth_psn=title in SYNTH_PSN_FIXTURE))
    source_path, clock, psn_setup = fixture, None, None
    boot = staged
    if title in SYNTH_PSN_FIXTURE:
        # card gen2-u1e-poison O-33 fallback: boot the disclosed SYNTH fixture (the lead poisoned at 8 HP, 5 Master
        # Balls) instead of the played bytes; `staged`/`fixture` above stay the PLAYED base for
        # qualification/identity, unmodified (same split as the U1_CLOCK trailer swap below).
        boot, psn_setup = gen2_synth_fixtures.build_named(SYNTH_PSN_FIXTURE[title], root=REPO)
    if title in U1_CLOCK:   # set right before the launch: the RTC runs on from here
        boot, clock = u1_clock_setup(boot, title, now=int(time.time()))
    if boot != staged:
        source_path = REPO / ".cache/gen2-fixtures/u1-hook-proof" / f"{spec.name}{'-overlay' if kind == 'overlay' else ''}-boot.SaveRAM"
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_bytes(boot)
    passed, path, text = run_gate(GATE, rom_key=live.rom_key(spec.title), target=spec.target,
                                  timeout=7200 if title in EVOLUTION_TITLES else 3600 if title in POISON_TITLES else 1200,
                                  saveram_dir=str(REPO / ".cache/gen2-fixtures/u1-hook-proof"
                                                  / (f"{spec.name}-overlay" if kind == "overlay" else spec.name)),
                                  fixture_path=str(source_path), speed_percent=300, env_overrides=env)
    assert passed, f"gate FAILED; result {path}: {text[-3000:]}"
    assert fixture.read_bytes() == staged, "fixture changed while the gate ran"

    pack = json.loads((REPO / f"data/games/gen2_{title}/engine_signals.json").read_text(encoding="utf-8"))
    receipt = verify(text, pack, title, live.identity(title))
    assert receipt["fixture_sha256"] == hashlib.sha256(staged).hexdigest(), "receipt names other fixture bytes"
    assert receipt["qualification_attempt_id"] == qualification["attempt_id"]
    if clock is not None:
        receipt.update(u1_receipt_metadata(clock))
    if psn_setup is not None:
        receipt["poison_setup"] = psn_setup
    receipt_path = live.receipt_file(f"{title}.engine_sites.json")   # overlay: receipts/overlay/, never a clean path
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(live.stamped(receipt), indent=1, sort_keys=True) + "\n", encoding="utf-8")
