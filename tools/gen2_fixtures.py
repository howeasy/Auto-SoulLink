"""Gen 2 played-fixture plans and independent qualification binding.

Authoring/inspection is read-only. This module never creates ROM/save/fixture
bytes, repairs a save, or treats a Lua RESULT line as fixture qualification.
game_callbacks() binds the boot/re-save stages to the reviewed gate (warm boot,
CONTINUE, native re-save, reload); the PYDEC stages stay fixed. qualify() runs the
full chain for one played candidate. Process, frame, timeout and qualification
orchestration remain shared (tools/run_gb_gate.py, tools/fixture_qualification.py).
"""
from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

if __package__:
    from . import fixture_qualification as qualification
    from .gen2_source_data import ROOT, load_context, rom_offset
    from .gen_gen2_area_map import build_area_map, constants, rom_bytes, source_lines
    from .gen_gen2_charmap import integer, verify_table
    from .gen_gen2_items import item_ids
    from .gen_gen2_species import const_block
    from .gen_gen2_area_map import constants as const_values
else:
    import fixture_qualification as qualification
    from gen2_source_data import ROOT, load_context, rom_offset
    from gen_gen2_area_map import build_area_map, constants, rom_bytes, source_lines
    from gen_gen2_charmap import integer, verify_table
    from gen_gen2_items import item_ids
    from gen_gen2_species import const_block
    from gen_gen2_area_map import constants as const_values


@dataclass(frozen=True)
class FixtureSpec:
    name: str
    title: str
    target: str
    identity: str
    title_idle_frames: int


FIXTURES = tuple(FixtureSpec(f"{title}_{target}", title, target, "default", 0)
                 for title in ("crystal", "gold", "silver") for target in ("town", "battle")) + tuple(
    FixtureSpec(f"crystal_{target}_ot2", "crystal", target, "ot2", 240) for target in ("town", "battle")) + (
    # The G<->S reconnect wrong-save control: same ot2 recipe (preset name 3 = HIRO, 240-frame title idle).
    # ponytail: battle only; add gold_town_ot2 / silver ot2 when a lane needs them.
    FixtureSpec("gold_battle_ot2", "gold", "battle", "ot2", 240),
    # Card gen2-u1e-poison (main's ruling (1)): Gold after the Mr. Pokemon errand, ending where gold_battle ends
    # (Route 29 grass, O-10 Balls): the only Gold state that reaches a day POISON_STING foe (Bug Catcher Wade,
    # Route 31, behind the Route 30 battle demo that EVENT_ROUTE_30_BATTLE hides, pokegold maps/ElmsLab.asm:299-306).
    # Facts: docs/gen2/reviews/OMP_GOLD_ERRAND_FACTS_2026-09-23.md. Same default identity recipe as gold_battle.
    FixtureSpec("gold_battle_errand", "gold", "battle", "default", 0),)
MAPS = ("PlayersHouse2F", "PlayersHouse1F", "NewBarkTown", "ElmsLab", "Route29")
# The errand's own route facts add its maps, events, prompts and the rival naming screen. Only an errand fixture
# uses them, so every other fixture keeps its recorded route_facts_sha256.
ERRAND_FIXTURES = frozenset({"gold_battle_errand"})
ERRAND_MAPS = MAPS + ("CherrygroveCity", "Route30", "MrPokemonsHouse")
# Route29Tutorial1/2's yesorno (pokegold maps/Route29.asm:46-47/:71-72): CatchingTutorialIntroText's last two
# rows stay on screen after its `cont` scroll (:264-266).
ERRAND_PROMPTS = {"tutorial": ("to show you how to",)}
ERRAND_PROMPT_SOURCES = ("maps/Route29.asm",)
# The errand's progress: MrPokemonsHouse.asm:36 (egg received), ElmsLab.asm:299 (egg handed to Elm).
ERRAND_EVENTS = ("EVENT_GOT_MYSTERY_EGG_FROM_MR_POKEMON", "EVENT_GAVE_MYSTERY_EGG_TO_ELM")
BY_NAME = {spec.name: spec for spec in FIXTURES}
# docs/gen2/reviews/OMP_RTC_SOURCE_2026-09-22.md: 32 KiB CartRAM plus the 22-byte BizHawk 2.11.1
# gambatte RTC trailer. Only the CartRAM is compared; the trailer changes on every save.
CART_RAM_BYTES = 0x8000
SAVERAM_BYTES = CART_RAM_BYTES + 22
# The reviewed played-route gate; run_gb_gate reads its terminal result path from the source.
GATE_SCRIPT = "lua/tests/test_gen2_scripted_gate.lua"
# Qualification (warm boot the candidate SaveRAM, CONTINUE, re-save, reload) runs at 100%; routes at 300%.
QUALIFY_SPEED_PERCENT = 100
# ponytail: live calibration knobs; the Crystal intro alone runs thousands of frames before the title.
QUALIFY_BUDGET = {"max_frames": 30000, "max_phase_frames": 12000, "settle_frames": 30}
# Code sites the qualification gate counts. Every label is in both pinned sources:
#   Continue, .Check1Pass (A accepted), .Check2Pass (RTC accepted)  C engine/menus/intro_menu.asm:338,353,359;
#     G :251,265,271. ConfirmContinue C :429-442, G :313-326 (A continues, B backs out).
#   RestartClock via Continue_CheckRTC_RestartClock (RTC_RESET) C :444-457, G :328-341.
#   FinishContinueFunction -> OverworldLoop C :459-477, G :343-357.
#   AskOverwriteSaveFile.yoursavefile (same player ID) C engine/menus/save.asm:181-203 (:192), G :169-191 (:180).
#   ErasePreviousSave (another player's file: boxes/HoF erased) C :360, G :333.
QUALIFY_SITES = {"continue": "Continue", "continue_loaded": "Continue.Check1Pass", "rtc_ok": "Continue.Check2Pass",
                 "restart_clock": "RestartClock", "finish_continue": "FinishContinueFunction",
                 "same_save_file": "AskOverwriteSaveFile.yoursavefile", "erase_save": "ErasePreviousSave"}
QUALIFY_UI = {"continue_confirm": "ConfirmContinue"}
# SaveMenu prompts _WouldYouLikeToSaveTheGameText then _AlreadyASaveFileText (C data/text/common_3.asm:187-212,
# G data/text/common_2.asm:1274-1299). The overwrite text's first line scrolls off (`cont`), so the
# same-player branch is told from _AnotherSaveFileText by the .yoursavefile site, never by the screen.
# That `cont` waits in PromptButton (<_CONT> -> _ContText, C home/text.asm:231,502-512,528-539); its first
# lines bind the wait: save_overwrite_text.
QUALIFY_PROMPTS = {"save_confirm": ("save the game?",), "save_overwrite": ("OK to overwrite?",),
                   "save_overwrite_text": ("There is already a", "There is another")}
# CartRAM the CONTINUE load and a native re-save may rewrite; every other byte must survive unchanged.
#   _SaveGameData C engine/menus/save.asm:266-295, G :273-291: options + check values, game data, checksums,
#   the backup copy (layout regions), SaveBox into the active box slot, sStackTop (UpdateStackTop),
#   BackupPartyMonMail (engine/pokemon/mail.asm:239), BackupMysteryGift (C engine/link/mystery_gift.asm:1374,
#   G :1217), SaveRTC's sRTCStatusFlags (engine/rtc/rtc.asm:76); Crystal BackupGSBallFlag
#   (mobile/mobile_41.asm:515) and sBattleTowerChallengeState (save.asm:286-292). TryLoadSaveFile
#   (C save.asm:596, G :538) runs LoadBox and the Restore* twins of the same spans.
#   (start, end): end is a symbol or (symbol, bytes past it).
SAVE_WRITES = (("sOptions", "sGameData"), ("sGameData", "sGameDataEnd"), ("sChecksum", "sBox"), ("sBox", "sBoxEnd"),
               ("sBackupOptions", ("sBackupCheckValue1", 1)), ("sBackupChecksum", ("sBackupCheckValue2", 1)),
               ("sStackTop", ("sStackTop", 2)), ("sPartyMail", "sMysteryGiftData"),
               ("sMysteryGiftItem", "sDailyMysteryGiftPartnerIDs"), ("sRTCStatusFlags", ("sRTCStatusFlags", 1)))
SAVE_WRITES_CRYSTAL = (("sGSBallFlag", ("sGSBallFlag", 1)), ("sGSBallFlagBackup", ("sGSBallFlagBackup", 1)),
                       ("sBattleTowerChallengeState", ("sBattleTowerChallengeState", 1)))
# CartRAM the game rewrites outside any save: UI/scratch state, never save data. Gold/Silver keep the menu
# window stack in SRAM bank 0 (G ram/sram.asm:79-84 sWindowStackBottom..sWindowStackTop, flat $1800-$1FFF).
# Every menu writes it: _PushWindow (G engine/menus/menu.asm:438) stores the menu header and tile backups,
# ClearWindowData (G home/menu.asm:712) zeroes its top from StartMenu and MainMenu, so CONTINUE and START/SAVE
# both rewrite it. Crystal keeps the stack in WRAM (wWindowStack, C home/menu.asm:768-772): nothing there.
# Closing an overworld menu also copies the whole screen tilemap into sScratch[0:SCREEN_AREA] in Gold/Silver
# (RestoreOverworldMapTiles, G engine/menus/menu.asm:569-591, SCREEN_AREA = 20*18 = $168); the same routine is
# unreferenced in Crystal (C engine/menus/menu.asm:696); live gold_town re-save corroborates ($0004-$0167 moved).
# Battle-only sScratch writers (G engine/battle_anims/anim_commands.asm, engine/battle/core.asm) are out of scope:
# qualification never battles, so a stray there is a real signal, not a reason to widen this span.
_GS_SCRATCH = (("sWindowStackBottom", ("sWindowStackTop", 1)), ("sScratch", ("sScratch", 20 * 18)))
SCRATCH_WRITES = {"crystal": (), "gold": _GS_SCRATCH, "silver": _GS_SCRATCH}
# Crystal Init zeroes sScratch[0:$20] on every boot (C home/init.asm:98 -> ClearsScratch :205-213; Gold has no
# such routine). Battle animations decompress into sScratch (DecompressRequest2bpp C home/gfx.asm:118-133 via
# LoadBattleAnimGFX engine/battle_anims/helpers.asm:105-122), so a candidate that met a wild battle holds
# graphics there. Those 32 bytes may change on a qualification boot, and only to zero.
BOOT_ZEROED = {"crystal": ("sScratch", ("sScratch", 0x20))}
# PLAN 5.6 expected scenario delta -- a FRESH-FIXTURE oracle. Inside the save spans a no-op CONTINUE + native
# re-save writes the same bytes back (SavePlayerData/SavePokemonData/SaveBox and the backups copy the live WRAM:
# C engine/menus/save.asm:266-295,498-594, G :273-291,396-536), so every saved byte must equal the candidate:
# player ID, map, position, party, items and the Ball pocket, event flags, the active and current storage box,
# mail, options, check values. Scope: the eight early-game fixtures. inspect_candidate REFUSES the inputs whose
# CONTINUE transitions are not modelled (docs/gen2/reviews/N14B_FACTS_CODEX_2026-09-23.md guard table): released
# roamers, active Pokerus, Mystery Gift state, a recorded RTC fault, Crystal Battle Tower carry, a running Bug
# Contest timer. A new scope needs a new rule with its own source transition, never a looser span.
# Free SRAM: the checksums (SaveChecksum C :526, SaveBackupChecksum :583; G :424, :495;
# strict_checksum_witness still verifies them) and sStackTop (UpdateStackTop C :297, G :294).
RESAVE_FREE_SRAM = (("sChecksum", ("sChecksum", 2)), ("sBackupChecksum", ("sBackupChecksum", 2)),
                    ("sStackTop", ("sStackTop", 2)))
# SaveRTC writes 0 to sRTCStatusFlags on every save (C/G engine/rtc/rtc.asm:76-88): the re-saved byte must be 0.
RESAVE_ZEROED_SRAM = ("sRTCStatusFlags",)
# Genuinely dynamic game-data fields, in every copy: CONTINUE, the overworld frames before the save, or the
# save itself rewrite them with time- or movement-dependent values, so any value is accepted:
RESAVE_FREE_WRAM = (
    # StageRTCTimeForSave stamps the RTC time (C/G engine/rtc/rtc.asm:63-74); FixTime derives wCurDay
    # (C home/time.asm:129-174, G :122-167); GameTimer counts play time (C/G home/game_time.asm:11).
    ("wRTC", ("wRTC", 4)), ("wCurDay", ("wCurDay", 1)), ("wGameTimeCap", ("wGameTimeFrames", 1)),
    # Object engine state: MapSetupScript_Continue (C data/maps/setup_scripts.asm:164-182, G :161-179) clears
    # the command queue (HandleContinueMap) and rebuilds the sprites (RefreshMapSprites); NPC movement
    # advances the follow state and wObjectStructs every frame. The saved checkpoint is wMapGroup/wMapNumber/
    # wXCoord/wYCoord, still compared. Span: wObjectFollow_Leader..wCmdQueue end (C ram/wram.asm:3032-3045,
    # G :2441-2460); the `ds 40` pad above wMapObjects (C :3047, G :2462) is never written, so it stays compared.
    ("wObjectFollow_Leader", ("wMapObjects", -40)),
    # wMapObjects is NOT reloaded by CONTINUE (MapSetupScript_Continue -> LoadMapAttributes_SkipObjects skips
    # ReadObjectEvents: C data/maps/setup_scripts.asm:164-182, home/map.asm:385-417; G :161-179, :754-786), and no
    # CONTINUE setup script runs RefreshPlayerCoords (C engine/overworld/player_object.asm:102-123, G :87-108) or
    # re-inits objects (C home/map.asm:568-634, G :937-1005). So all of wMapObjects, the player map object Y/X
    # and every MAPOBJECT_OBJECT_STRUCT_ID included, survives a no-movement re-save byte for byte; movement,
    # warps or visibility changes would need their own witness (N14B facts #3a/#3b).
    # LoadMapTimeOfDay in the same script: time-of-day palette state from the RTC.
    ("wTimeOfDayPal", ("wCurTimeOfDay", 1)),
    # CheckTimeEvents every overworld frame (C engine/overworld/events.asm:449-466, G :436-454):
    # CheckDayDependentEventHL stamps today into the day byte of wDailyResetTimer through _CalcDaysSince
    # (C engine/overworld/time.asm:73-81,399-408, G :59-67,354-363); CheckPokerusTick (C :194-204, G :149-159)
    # stamps wTimerEventStartDay the same way. Day stamps only; the countdown byte is ruled below.
    (("wDailyResetTimer", 1), ("wDailyResetTimer", 2)), ("wTimerEventStartDay", ("wTimerEventStartDay", 1)),
)
# Saved fields that move only along a deterministic source transition: exempt from the byte comparison, and
# checked per copy by _ruled_problems instead. (rule, start, end) with _wram_span's start/end forms.
#   daily_countdown  CheckDailyResetTimer's one-day countdown: minus the days since its stamp, or restarted to 1
#                    by RestartDailyResetTimer -> InitOneDayCountdown when it runs out (C engine/overworld/time.asm
#                    :61-81,99-106,288-306; G :47-67,85-92,243-261).
#   daily_cleared    every byte zeroed when that reset fires, otherwise unchanged (C :107-122 wDailyFlags1/2,
#                    wSwarmFlags, wUnusedDailyFlag and the rematch/phone-item/phone-time-of-day flags; G :92-96
#                    wDailyFlags1/2).
#   kenji            Crystal wKenjiBreakTimer's first byte, ticked by the same reset: minus one, or resampled to
#                    3..6 by SampleKenjiBreakCountdown once it is at or reaches 0 (C :123-142); unchanged otherwise.
#   map_sign         Crystal: only SHOWN_MAP_NAME_SIGN (bit 1, C constants/ram_constants.asm:138-140) may move:
#                    FinishContinueFunction sets it (C engine/menus/intro_menu.asm:467-468), the map-sign check
#                    clears it (C engine/events/map_name_sign.asm:29-31).
#   timer_counting   Gold/Silver: FinishContinueFunction sets GAME_TIMER_COUNTING_F (bit 0,
#                    G constants/ram_constants.asm:29-30) in the saved wGameTimerPaused (G engine/menus/
#                    intro_menu.asm:347-348); nothing else moves.
#   swarm            Gold/Silver: CheckSwarmFlag zeroes wSwarmMapGroup/wSwarmMapNumber/wFishingSwarmFlag every
#                    overworld frame while DAILYFLAGS1_SWARM_F (bit 2, G constants/ram_constants.asm:301-305) is
#                    clear (G engine/overworld/events.asm:452 -> engine/events/specials.asm:299-314); unchanged
#                    while it is set.
#   roam_indices     Continue .Check2Pass -> JumpRoamMons (C engine/menus/intro_menu.asm:372, G :283) ends in
#                    _BackUpMapIndices (C engine/overworld/wildmons.asm:743-752, G :748-757) on EVERY CONTINUE,
#                    even with no roamer: last := cur, cur := (wMapNumber, wMapGroup). Stale-but-unchanged fails.
# Every rule is deterministic because CheckTimeEvents always reaches .do_daily on a qualification CONTINUE
# (C engine/overworld/events.asm:449-465, G :436-453): wLinkMode is unsaved and 0 (C FinishContinueFunction
# intro_menu.asm:462; G Init clears all WRAM, home/init.asm:59-68) and inspect_candidate refuses a saved
# STATUSFLAGS2_BUG_CONTEST_TIMER_F. So no rule has an "unchanged always passes" shortcut.
RESAVE_RULED_WRAM = {
    "all": (("daily_countdown", "wDailyResetTimer", ("wDailyResetTimer", 1)),
            ("daily_cleared", "wDailyFlags1", ("wDailyFlags2", 1)),
            ("roam_indices", "wRoamMons_CurMapNumber", ("wRoamMons_LastMapGroup", 1))),
    "crystal": (("daily_cleared", "wSwarmFlags", ("wUnusedDailyFlag", 1)),
                ("daily_cleared", "wDailyRematchFlags", ("wDailyPhoneTimeOfDayFlags", 4)),
                ("kenji", "wKenjiBreakTimer", ("wKenjiBreakTimer", 1)),
                ("map_sign", "wMapNameSignFlags", ("wMapNameSignFlags", 1))),
    "gold": (("timer_counting", "wGameTimerPaused", ("wGameTimerPaused", 1)),
             ("swarm", "wSwarmMapGroup", ("wFishingSwarmFlag", 1))),
}
RESAVE_RULED_WRAM["silver"] = RESAVE_RULED_WRAM["gold"]
# _CalcDaysSince wraps the day difference at 20 * 7 (C engine/overworld/time.asm:399-408, G :354-363). Each check
# stamps wCurDay into wDailyResetTimer+1 / wTimerEventStartDay. FixTime does NOT reduce wCurDay mod 140 (RTC days
# + wStartDay, C home/time.asm:169-174, G :162-167), so a stamp of 140+ is possible but breaks the mod-140 model:
# fresh-fixture stamps outside 0..139 are refused in both images, not asserted impossible.
DAYS_WRAP = 20 * 7
SHOWN_MAP_NAME_SIGN_F, GAME_TIMER_COUNTING_F, DAILYFLAGS1_SWARM_F = 1, 0, 2
STATUSFLAGS2_BUG_CONTEST_TIMER_F = 2   # C constants/ram_constants.asm:246, G :235
# The WRAM start of each layout.regions copy.
_REGION_STARTS = {"player": "wPlayerData", "player1": "wPlayerData1", "player2": "wPlayerData2",
                  "player3": "wPlayerData3", "map": "wCurMapData", "pokemon": "wPokemonData"}
PASSABLE_COLLISION = ("FLOOR", "TALL_GRASS", "LONG_GRASS", "DOOR", "LADDER", "CAVE", "STAIRCASE",
                      "WARP_CARPET_DOWN", "WARP_CARPET_LEFT", "WARP_CARPET_UP", "WARP_CARPET_RIGHT")
# Yes/no prompt -> on-screen text anchors, each verified as a quoted literal in the pinned source.
# The Elm mission yes/no exists only in Crystal (Gold/Silver ElmsLab.asm has no intro yesorno).
PROMPT_ANCHORS = {
    "clock_confirm": ("What?", "Whoa!"), "mom_dst": ("Saving Time now?",), "mom_dst_confirm": ("is that OK?",),
    "mom_phone": ("the PHONE?",), "elm_mission": ("that I recently",), "starter_confirm": ("TOTODILE, the",),
    # Anchors are rows still on screen under the box: a `cont` scrolls its first line off (TextScroll x2,
    # C home/text.asm:520-526). _CaughtAskNicknameText (C data/text/common_2.asm:1084-1090, G :717-723).
    "nickname": ("received?",), "save_confirm": ("save the game?",),
    # SetDayOfWeek confirm: _OakTimeIsItText, C data/text/common_1.asm:212-213, G :152-153.
    "day_confirm": (", is it?",),
}
PROMPT_SOURCES = ("data/text/common_1.asm", "data/text/common_2.asm", "data/text/common_3.asm",
                  "maps/PlayersHouse1F.asm", "maps/ElmsLab.asm")
if not __package__:
    sys.path.insert(0, str(ROOT))


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def cart_ram(raw):
    """The compared CartRAM of an exact-length SaveRAM; the RTC trailer is never compared."""
    _require(isinstance(raw, bytes) and len(raw) == SAVERAM_BYTES,
             f"Gen 2 SaveRAM must be exactly {SAVERAM_BYTES} bytes (CartRAM + RTC trailer)")
    return raw[:CART_RAM_BYTES]


def _facts_sha256(facts):
    return hashlib.sha256(json.dumps(facts, sort_keys=True).encode()).hexdigest()


def _json(raw):
    value = json.loads(raw)
    _require(isinstance(value, dict), "expected JSON object")
    return value


def _numeric_definitions(text):
    return {name: integer(value) for name, value in re.findall(
        r"^DEF (\w+)\s+EQU\s+(\$[0-9a-fA-F]+|\d+)\s*(?:;[^\n]*)?$", text, re.M)}


def _map_facts(ctx, row, areas):
    name, map_const = row["map_name"], row["map_const"]
    dimensions = re.search(rf"^\s*map_const {map_const},\s*(\d+),\s*(\d+)",
                           ctx.read_source("constants/map_constants.asm"), re.M)
    _require(dimensions is not None, f"missing map dimensions: {name}")
    width, height = map(int, dimensions.groups())
    block_symbol = ctx.symbol(name + "_Blocks")
    _, attrs = rom_bytes(ctx, name + "_MapAttributes", 6)
    _require((attrs[1], attrs[2], attrs[3], int.from_bytes(attrs[4:6], "little")) ==
             (height, width, block_symbol.bank, block_symbol.address), "map block header mismatch")
    _, blocks = rom_bytes(ctx, name + "_Blocks", width * height)
    # A shared layout (every Pokecenter1F) INCBINs another map's .blk (data/maps/blocks.asm): follow the INCBIN.
    blk = re.search(rf"^{name}_Blocks:\s*\n(?:\w+_Blocks:\s*\n)*\s*INCBIN \"(maps/[^\"]+\.blk)\"",
                    ctx.read_source("data/maps/blocks.asm"), re.M)
    source_blocks = (ctx.source_dir / (blk[1] if blk else f"maps/{name}.blk")).read_bytes()
    _require(source_blocks == blocks, f"source/ROM block data mismatch: {name}")
    header = next(line for _, line in source_lines(ctx.read_source("data/maps/maps.asm"), ctx.title)
                  if line.startswith("map " + name + ","))
    tileset = header.split(",")[1].strip()
    tilesets = constants(ctx.read_source("constants/tileset_constants.asm"), "TILESET_", ctx.title)
    index = tilesets[tileset]
    _require(bytes.fromhex(row["source"]["header_hex"])[1] == index, "map tileset byte mismatch")
    table = [line.split()[1] for _, line in source_lines(ctx.read_source("data/tilesets.asm"), ctx.title)
             if line.startswith("tileset ")]
    symbol = table[index] + "Coll"
    gfx = ctx.read_source("gfx/tilesets.asm")
    include = re.search(rf"^{symbol}::?\s*\nINCLUDE \"([^\"]+)\"", gfx, re.M)
    _require(include is not None, f"collision source not found: {symbol}")
    collision_values = _numeric_definitions(ctx.read_source("constants/collision_constants.asm"))
    collision = []
    for _, line in source_lines(ctx.read_source(include[1]), ctx.title):
        _require(line.startswith("tilecoll "), "unsupported collision row")
        tokens = [part.strip() for part in line[9:].split(",")]
        _require(len(tokens) == 4, "collision row width")
        collision.extend(collision_values["COLL_" + token] for token in tokens)
    verify_table(ctx, symbol, bytes(collision))
    allowed = {collision_values["COLL_" + value] for value in PASSABLE_COLLISION if "COLL_" + value in collision_values}
    grid, codes = [], []
    for y in range(height * 2):
        for x in range(width * 2):
            block = blocks[(y // 2) * width + x // 2]
            at = block * 4 + (y % 2) * 2 + x % 2
            _require(at < len(collision), "block indexes unknown collision row")
            code = collision[at]
            codes.append(code)
            grid.append(2 if code == collision_values["COLL_TALL_GRASS"] else 1 if code in allowed else 0)
    carpets = {collision_values["COLL_WARP_CARPET_" + side.upper()]: side for side in ("Down", "Left", "Up", "Right")}
    text = ctx.read_source("maps/" + name + ".asm")
    warps, scenes, objects, coords = [], {}, {}, []
    for line_no, line in source_lines(text, ctx.title):
        if line.startswith("warp_event "):
            x, y, destination, warp = [part.strip() for part in line[11:].split(",")]
            warps.append({"x": int(x), "y": int(y), "destination": destination,
                          "warp": int(warp), "source_line": line_no,
                          "carpet": carpets.get(codes[int(y) * width * 2 + int(x)])})
        elif line.startswith(("scene_script ", "scene_const ")):
            scene = line.split(",")[-1].strip() if line.startswith("scene_script ") else line.split()[1]
            scenes[scene] = len(scenes)
        elif line.startswith("coord_event "):
            x, y, scene, script = [part.strip() for part in line[12:].split(",")]
            coords.append({"x": int(x), "y": int(y), "scene": scene, "script": script})
        elif line.startswith("object_event "):
            fields = [part.strip() for part in line[13:].split(",")]
            objects[fields[11]] = {"x": int(fields[0]), "y": int(fields[1])}
    expected = bytearray([len(warps)])
    for warp in warps:
        destination = areas[warp["destination"]]
        expected.extend([warp["y"], warp["x"], warp["warp"], destination["map_group"], destination["map_number"]])
    _, observed = rom_bytes(ctx, name + "_MapEvents", len(expected), 2)
    _require(observed == expected, "source/ROM warp table mismatch")
    return {"map_group": row["map_group"], "map_number": row["map_number"], "map_const": map_const,
            "width": width * 2, "height": height * 2, "grid": grid, "warps": warps,
            "scenes": scenes, "objects": objects, "coord_events": coords,
            "source": f"{ctx.source_commit} maps/{name}.asm; {include[1]}"}


def _code_site(ctx, symbol, offset=0):
    bank, address = ctx.symbol(symbol)
    flat = rom_offset(bank, address + offset)
    return {"symbol": symbol, "symbol_offset": offset, "bank": bank, "addr": address + offset,
            "flat": flat, "hex": ctx.rom[flat:flat + 1].hex()}


def _observer_facts(ctx, root, errand=False):
    """Source constants and code sites the played-route gate observes; RAM addresses stay in the profile."""
    ram_constants = ctx.read_source("constants/ram_constants.asm")
    objects = ctx.read_source("constants/map_object_constants.asm")
    directions = const_block(ram_constants, "DOWN")
    shifts = dict(re.findall(r"^DEF OW_(DOWN|UP|LEFT|RIGHT)\s+EQU\s+\1\s*<<\s*(\d+)", objects, re.M))
    _require(len(shifts) == 4, "overworld facing constants missing")
    facing = {name.title(): directions[name] << int(shifts[name]) for name in ("DOWN", "UP", "LEFT", "RIGHT")}
    fields, offset = {}, None
    for line in objects.splitlines():
        line = line.split(";", 1)[0].strip()
        if line == "rsreset" and offset is None:
            offset = 0
        elif offset is None:
            continue
        elif match := re.fullmatch(r"DEF (OBJECT_\w+)\s+rb(?:\s+(\d+))?", line):
            fields[match[1]] = offset
            offset += int(match[2] or 1)
        elif match := re.fullmatch(r"rb_skip(?:\s+(\d+))?", line):
            offset += int(match[1] or 1)
        elif line == "DEF OBJECT_LENGTH EQU _RS":
            fields["OBJECT_LENGTH"] = offset
            break
    count = _numeric_definitions(objects)["NUM_OBJECT_STRUCTS"]
    structs = ctx.symbol("wObjectStructs")
    _require(ctx.symbol("wObject1Struct").address - structs.address == fields.get("OBJECT_LENGTH")
             and ctx.symbol("wPlayerDirection").address - structs.address == fields.get("OBJECT_DIRECTION"),
             "object struct geometry disagrees with symbols")
    collision = _numeric_definitions(ctx.read_source("constants/collision_constants.asm"))
    hardware = ctx.read_source("constants/hardware.inc")
    screen = {key: int(re.search(rf"^def SCREEN_{key.upper()}\s+equ\s+(\d+)", hardware, re.M | re.I)[1])
              for key in ("width", "height")}
    events = const_block(ctx.read_source("constants/event_flags.asm"), "EVENT_GOT_A_POKEMON_FROM_ELM")
    prompts = {}
    texts = [ctx.read_source(path) for path in PROMPT_SOURCES + (ERRAND_PROMPT_SOURCES if errand else ())]
    for prompt, anchors in {**PROMPT_ANCHORS, **(ERRAND_PROMPTS if errand else {})}.items():
        found = [anchor for anchor in anchors
                 if any(re.search(r'^\s*(?:text|line|cont|para)\s+"[^"]*' + re.escape(anchor), text, re.M)
                        for text in texts)]
        _require(found == list(anchors) or (not found and prompt == "elm_mission" and ctx.title != "crystal"),
                 f"prompt anchor missing from source: {prompt}")
        if found:
            prompts[prompt] = found
    signals = _json((Path(root) / f"data/games/gen2_{ctx.title}/engine_signals.json").read_bytes())
    save = signals["titles"][ctx.title]["sites"]["save_completed"]
    start = save["rom_offset"]
    _require(signals["source"]["rom_sha1"] == ctx.source_record()["rom_sha1"]
             and ctx.rom[start:start + len(save["expected_hex"]) // 2].hex() == save["expected_hex"]
             and rom_offset(save["bank"], save["addr"]) == start, "save-completed site differs from ROM")
    scenes = {name: f"w{name}SceneID" for name in ("PlayersHouse1F", "ElmsLab", "NewBarkTown")}
    for symbol in scenes.values():
        ctx.symbol(symbol)
    extra = {}
    if errand:
        flags = const_block(ctx.read_source("constants/event_flags.asm"), ERRAND_EVENTS[0])
        extra["errand_events"] = {name: flags[name] for name in ERRAND_EVENTS}
    return {**extra, "overworld_tick": _code_site(ctx, "OWPlayerInput"),
            "save_completed": {"symbol": save["symbol"], "symbol_offset": save["symbol_offset"], "bank": save["bank"],
                               "addr": save["addr"], "flat": start, "hex": save["expected_hex"]},
            "facing": facing, "screen": screen, "scene_symbols": scenes, "prompts": prompts,
            "object": {"length": fields["OBJECT_LENGTH"], "count": count, "sprite": fields["OBJECT_SPRITE"],
                       "direction": fields["OBJECT_DIRECTION"], "map_x": fields["OBJECT_MAP_X"],
                       "map_y": fields["OBJECT_MAP_Y"]},
            "passable_collision": sorted({collision["COLL_" + name] for name in PASSABLE_COLLISION
                                          if "COLL_" + name in collision}),
            "pokegear_obtained_bit": const_values(ram_constants, "POKEGEAR_OBTAINED_F", ctx.title)["POKEGEAR_OBTAINED_F"],
            "got_starter_event": events["EVENT_GOT_A_POKEMON_FROM_ELM"]}


def route_facts(title, root=ROOT, errand=False):
    """Source/ROM-bound candidate navigation facts; no live route qualification. `errand` adds the Gold errand's
    maps, events, prompts and naming-screen origin (spec_route_facts), leaving every other fixture's facts as-is."""
    ctx = load_context(title, root=root)
    profile_path = Path(root) / "data/games" / f"gen2_{title}/profile.json"
    wrapper = _json(profile_path.read_bytes())
    _require(wrapper["source"] == ctx.source_record(), "profile provenance mismatch")
    selected = wrapper["titles"][title]
    areas = {row["map_const"]: row for row in build_area_map(ctx).values()}
    by_name = {row["map_name"]: row for row in areas.values()}
    maps = {name: _map_facts(ctx, by_name[name], areas) for name in (ERRAND_MAPS if errand else MAPS)}
    script = ctx.read_source("maps/ElmsLab.asm")
    _require("setmapscene NEW_BARK_TOWN, SCENE_NEWBARKTOWN_NOOP" in script,
             "starter west-exit release source missing")
    _require("givepoke TOTODILE, 5, BERRY" in script, "starter source changed")
    species = const_block(ctx.read_source("constants/pokemon_constants.asm"), "TOTODILE")
    item_names, _ = item_ids(ctx.read_source("constants/item_constants.asm"))
    items = {name: number for number, name in item_names.items()}
    capacity = _numeric_definitions(ctx.read_source("constants/item_data_constants.asm"))["MAX_BALLS"]
    ui_labels = {"title": "StartTitleScreen", "main_menu": "MainMenu", "name_choices": "NamePlayer",
                 "clock_hour": "InitClock.SetHourLoop", "clock_minute": "InitClock.SetMinutesLoop",
                 # YesNoBox falls into PlaceYesNoBox's `jr _YesNoBox` (C home/menu.asm:418-428, G :382-392);
                 # SaveTheGame_yesorno calls PlaceYesNoBox directly (C engine/menus/save.asm:209-214, G :197-202),
                 # so only the shared body sees every yes/no box. Hooks fire at the exact PC only.
                 "yes_no": "_YesNoBox", "text": "WaitPressAorB_BlinkCursor.loop", "start_menu": "StartMenu",
                 "battle_menu": "BattleMenu",
                 # WaitPressAorB_BlinkCursor .loop (home/joypad.asm:358-367) spins without DelayFrame: it
                 # fires many times per waiting frame, never once an answered wait returns.
                 # Script/text waits, bound at their per-frame loops so an answered wait stops firing:
                 # PromptButton .input_wait_loop (home/joypad.asm:411-421; para/cont/prompt and script
                 # promptbutton), WaitButton's JoyWaitAorB (:292-300, :308; script waitbutton), Mom's weekday
                 # picker SetDayOfWeek .loop2 (engine/rtc/timeset.asm:420-423). Same labels in pokegold.
                 "prompt_button": "PromptButton.input_wait_loop", "wait_button": "JoyWaitAorB",
                 "day_picker": "SetDayOfWeek.loop2"}
    if title == "crystal":
        ui_labels["gender"] = "InitGender"
    if errand:
        # The officer's `special NameRival` (pokegold maps/ElmsLab.asm:508-518, unavoidable: the lab's only
        # north aisle is its coord tiles (4,5)/(5,5)): the naming screen's per-frame loop. START parks the cursor on
        # END (engine/menus/naming_screen.asm:404-418), A there stores the entry (:393-399, :424-428).
        ui_labels["naming"] = "NamingScreenJoypadLoop"
        # The unavoidable Cherrygrove rival (CANLOSE) is lost behind LEER: the move list's joypad pass
        # (MoveSelectionScreen.interpret_joypad, the U1d faint leg's move_menu origin; same label in pokegold).
        ui_labels["move_menu"] = "MoveSelectionScreen.interpret_joypad"
    ui = {kind: {key: value for key, value in _code_site(ctx, symbol).items() if key != "symbol_offset"}
          for kind, symbol in ui_labels.items()}
    result = {"schema": "gen2-scripted-route-facts-v1", "title": title,
              "rom_sha1": ctx.source_record()["rom_sha1"], "source": ctx.source_record(),
              "core_mode": "CGB", "qualified": False, "maps": maps, "ui_origins": ui,
              "starter": {"species": species["TOTODILE"], "level": 5, "object": "TotodilePokeBallScript"},
              "balls": {"item": items["POKE_BALL"], "quantity": 10, "capacity": capacity,
                        "count_address": ctx.symbol("wNumBalls").address,
                        "data_address": ctx.symbol("wBalls").address, "bank": ctx.symbol("wBalls").bank},
              "observer": _observer_facts(ctx, root, errand),
              "required_observer": ["source-bound UI context", "CGB bank-valid point", "script-idle overworld input",
                                    "live movement blocking", "native successful-save counter"],
              "open_obligations": ["live_point_observer_binding", "played_route_and_OT_separation",
                                   "RTC_and_cold_boot_continue_resave_reload_GAME_witnesses"]}
    _require(selected["ram"]["wNumBalls"] + 1 == result["balls"]["data_address"], "ball pocket geometry")
    result["fingerprint"] = _facts_sha256(result)
    return result


def spec_route_facts(spec, root=ROOT):
    """The route facts one fixture spec plays and qualifies on."""
    # ponytail: the keyword only for an errand spec keeps every plain call route_facts(title, root)
    return route_facts(spec.title, root, errand=True) if spec.name in ERRAND_FIXTURES else route_facts(spec.title, root)


def qualify_facts(title, root=ROOT, errand=False):
    """Source-bound CONTINUE/re-save facts for the qualification gate; the route facts stay unchanged."""
    ctx = load_context(title, root=root)
    route = route_facts(title, root, errand=True) if errand else route_facts(title, root)
    texts = [ctx.read_source(path) for path in PROMPT_SOURCES]
    for anchors in QUALIFY_PROMPTS.values():
        for anchor in anchors:
            _require(any(re.search(r'^\s*(?:text|line|cont|para)\s+"[^"]*' + re.escape(anchor), text, re.M)
                         for text in texts), f"qualification prompt anchor missing from source: {anchor}")

    def site(symbol):
        return {key: value for key, value in _code_site(ctx, symbol).items() if key != "symbol_offset"}

    result = {"schema": "gen2-qualify-facts-v1", "title": title, "rom_sha1": route["rom_sha1"],
              "route_facts_fingerprint": route["fingerprint"], "speed_percent": QUALIFY_SPEED_PERCENT,
              "ui_origins": {kind: site(symbol) for kind, symbol in QUALIFY_UI.items()},
              "sites": {kind: site(symbol) for kind, symbol in QUALIFY_SITES.items()},
              "prompts": {kind: list(anchors) for kind, anchors in QUALIFY_PROMPTS.items()}}
    result["fingerprint"] = _facts_sha256(result)
    return result


def fixture_manifest(root=ROOT):
    facts = {title: route_facts(title, root) for title in ("crystal", "gold", "silver")}
    return {"schema": "gen2-fixture-plan-v1", "qualified": False, "facts": facts,
            "fixtures": [{**vars(spec), "filename": spec.name + ".SaveRAM", "core_mode": "CGB",
                          "route_speed_percent": 300, "qualification_speed_percent": 100,
                          "max_frames": 120000, "max_phase_frames": 40000, "settle_frames": 30,
                          "budgets_measured": False,
                          "ball_exception": "O-10" if spec.target == "battle" else None}
                         for spec in FIXTURES]}


def run_play(spec, binding, *, root=ROOT, runner=None):
    """Dispatch only through an explicit reviewed gate binding; return a candidate."""
    _require(spec in FIXTURES, "unknown fixture case")
    _require(isinstance(binding, dict) and binding.get("observer_qualified") is True,
             "qualified Gen2 point observer/gate binding missing")
    from tools import run_gb_gate

    describe = getattr(run_gb_gate, "describe_gen2", None)
    _require(callable(describe), "shared runner Gen2 descriptor binding missing")
    descriptor = describe(spec.title + "_cold")
    facts = spec_route_facts(spec, root)
    _require(descriptor["cold"] is True and descriptor["core_mode"] == "CGB"
             and descriptor["rom_sha1"] == facts["rom_sha1"] and descriptor["title"] == spec.title,
             "shared runner descriptor differs from selected source")
    attempt = binding.get("attempt_id")
    _require(isinstance(attempt, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,80}", attempt), "bounded attempt ID required")
    script = binding.get("gate_script")
    _require(isinstance(script, str) and script.startswith("lua/tests/") and ".." not in Path(script).parts,
             "reviewed game gate script required")
    directory = Path(root).resolve() / ".cache/gen2-fixtures" / attempt / spec.name / "saveram"
    case = {**vars(spec), "attempt_id": attempt, "max_frames": binding.get("max_frames", 120000),
            "max_phase_frames": binding.get("max_phase_frames", 40000), "settle_frames": 30}
    passed, path, text = (runner or run_gb_gate.run_gate)(
        script, rom_key=spec.title + "_cold", target=spec.target, timeout=binding.get("timeout", 1200),
        saveram_dir=str(directory), fixture_path=None, speed_percent=300,
        env_overrides={"SLINK_GEN2_FIXTURE_CASE": json.dumps(case), "SLINK_GEN2_ROUTE_FACTS": json.dumps(facts)})
    return {"case": spec.name, "route_candidate": bool(passed), "qualified": False,
            "result_path": path, "diagnostic": text,
            "candidate_path": str(directory / descriptor["saveram_name"]),
            "receipt_path": str(directory / (spec.name + ".played.json")),
            "requires": list(qualification.FULL_CHAIN)}


def _saved_field(raw, layout, symbol, size):
    address = symbol if isinstance(symbol, int) else layout.addresses[symbol]
    for region in layout.regions:
        base = layout.addresses[_REGION_STARTS[region.name]]
        if base <= address and address + size <= base + region.length:
            start = region.primary + address - base
            return raw[start:start + size]
    raise ValueError(f"saved field outside source copy regions: {symbol}")


def inspect_candidate(raw, profile, rom, spec):
    """Independent PYDEC checks; a structurally valid model is not a played save."""
    from server.adapters import gen2_codec as codec
    from server.adapters.gen2_rom_scan import Rom

    raw = cart_ram(raw)
    layout = codec.Gen2Layout.from_profile(profile, spec.title)
    witness = codec.strict_checksum_witness(raw, layout)
    _require(witness["valid"], "independent checksum/marker/copy witness refused")
    party = codec.decode_saved_party(raw, layout, copy_name="primary")
    _require(party["count"] == 1, "fixture must contain one played starter")
    mon = party["mons"][0]
    _require(mon["species_id"] == 158 and not mon["is_egg"], "fixture starter identity mismatch")
    player_id = int.from_bytes(_saved_field(raw, layout, "wPlayerID", 2), "big")
    _require(mon["ot_id"] == player_id, "starter OT differs from saved player")
    base = Rom(rom, profile["titles"][spec.title]).base_stats(mon["species_id"])
    curves = ("GROWTH_MEDIUM_FAST", "GROWTH_SLIGHTLY_FAST", "GROWTH_SLIGHTLY_SLOW",
              "GROWTH_MEDIUM_SLOW", "GROWTH_FAST", "GROWTH_SLOW")
    _require(mon["level"] == 5 and mon["exp"] == codec.exp_for_level(5, curves[base["growth_rate"]]),
             "starter level/experience is not a fresh level-5 grant")
    computed = codec.calc_stats(base, mon["dvs"], mon["stat_exp"], mon["level"])
    _require(mon["max_hp"] == computed["hp"] and mon["stats"] == {k: v for k, v in computed.items() if k != "hp"},
             "independent stored-stat control mismatch")
    _require(0 < mon["hp"] <= mon["max_hp"], "starter is fainted or HP is invalid")
    location = tuple(_saved_field(raw, layout, key, 1)[0] for key in ("wMapGroup", "wMapNumber"))
    position = tuple(_saved_field(raw, layout, key, 1)[0] for key in ("wXCoord", "wYCoord"))
    count = _saved_field(raw, layout, "wNumBalls", 1)[0]
    _require(count <= 12, "saved Ball pocket exceeds source capacity")
    pocket = _saved_field(raw, layout, "wBalls", count * 2 + 1)
    _require(pocket[-1] == 255, "saved Ball pocket terminator missing")
    items = [(pocket[index * 2], pocket[index * 2 + 1]) for index in range(count)]
    _require(all(1 <= item < 255 and 1 <= quantity <= 99 for item, quantity in items), "invalid saved Ball slot")
    # Fresh-fixture input guards (docs/gen2/reviews/N14B_FACTS_CODEX_2026-09-23.md): CONTINUE transitions the
    # re-save oracle does not model are refused here, where every qualification stage inspects its input.
    ctx = load_context(spec.title)

    def saved(name, size=1):
        return _saved_field(raw, layout, ctx.symbol(name).address, size)

    def sram(name, size=1):
        start, end = _cart_span(ctx, name, (name, size))
        return raw[start:end]

    # New game: species 0, map group/number GROUP_N_A (C engine/menus/intro_menu.asm:163-173, G :78-88).
    _require(all(saved(f"wRoamMon{n}Species") + saved(f"wRoamMon{n}MapGroup", 2) == b"\x00\xff\xff" for n in (1, 2, 3)),
             "fixture has a released roamer (JumpRoamMons would move it)")
    # ApplyPokerusTick (engine/events/pokerus/apply_pokerus_tick.asm:1-25); the one-mon party is required above.
    _require(saved("wPartyMon1PokerusStatus")[0] == 0, "fixture party has Pokerus (CheckPokerusTick would tick it)")
    # New game item 0/unlocked -1 (C intro_menu.asm:175-183, G :90-98); CONTINUE copies received decorations
    # (C intro_menu.asm:373 -> engine/link/mystery_gift.asm:1327-1348, G :1170-1191); flag_array of 6 bytes.
    _require(sram("sMysteryGiftItem", 2) == b"\x00\xff" and not any(sram("sMysteryGiftDecorationsReceived", 6)),
             "fixture has Mystery Gift state")
    # ClockContinue can clear the daily timers on an RTC fault (C engine/rtc/rtc.asm:116-145, G :139-158). This
    # refuses a recorded fault only; a fault raised after loading is the live RTC witness's job.
    _require(sram("sRTCStatusFlags") == b"\x00", "fixture records an RTC fault (sRTCStatusFlags)")
    # Crystal rewrites BATTLETOWER_RECEIVED_REWARD on load/save (C engine/menus/save.asm:286-295,745-753).
    _require(spec.title != "crystal" or sram("sBattleTowerChallengeState") == b"\x00",
             "fixture carries Battle Tower state")
    # CheckTimeEvents skips the daily path while the Bug Contest timer runs (C events.asm:449-465, G :436-453).
    _require(not saved("wStatusFlags2")[0] >> STATUSFLAGS2_BUG_CONTEST_TIMER_F & 1,
             "fixture has the Bug Contest timer running (daily checks would not run)")
    return {"player_id": player_id, "location": location, "position": position, "ball_items": items,
            "party_raw_hex": party["raw_hex"],
            "identity_key": codec.key(mon), "cartram_sha256": hashlib.sha256(raw).hexdigest(),
            "physical_qualification": False}


def validate_played_receipt(receipt, spec, facts, inspection):
    _require(receipt.get("schema") == "gen2-played-route-v1" and receipt.get("case") == spec.name,
             "played-origin receipt missing or misbound")
    _require(receipt.get("facts_fingerprint") == facts["fingerprint"]
             and receipt.get("cartram_sha256") == inspection["cartram_sha256"]
             and receipt.get("rom_sha1") == facts["rom_sha1"], "played-origin byte/source binding mismatch")
    _require(receipt.get("core_mode") == "CGB" and receipt.get("speed_percent") == 300
             and receipt.get("input_mode") == "normal_buttons", "played-origin input/core witness incomplete")
    required = ["new-game", "leave-bedroom", "mom", "to-elm", "starter"]
    if spec.name in ERRAND_FIXTURES:
        # lua/tests/gen2_scripted_play.lua errand phases, in played order
        required += ["o10-balls", "leave-elm", "to-route29", "errand-west", "errand-mr-pokemon", "errand-egg",
                     "errand-east", "errand-elm", "errand-handoff", "leave-elm", "to-route29", "route29-grass"]
    elif spec.target == "battle":
        required += ["o10-balls", "leave-elm", "to-route29", "route29-grass"]
    required += ["native-save", "route-saved"]
    trace = receipt.get("phases")
    _require(isinstance(trace, list) and all(isinstance(row, dict) for row in trace), "played phase trace missing")
    labels = [row.get("phase") for row in trace]
    _require(spec.target == "battle" or "o10-balls" not in labels, "town fixture recorded an O-10 injection")
    previous = -1
    for label in required:
        positions = [i for i, value in enumerate(labels) if value == label and i > previous]
        _require(bool(positions), f"played route phase missing/out of order: {label}")
        previous = positions[0]
    frames = [row.get("frame") for row in trace]
    _require(all(type(frame) is int and frame >= 0 for frame in frames)
             and all(b > a for a, b in zip(frames, frames[1:], strict=False)), "played trace frame order invalid")
    allowed = ["O-10:BallPocket"] if spec.target == "battle" else []
    _require(receipt.get("harness_write_scopes") == allowed, "unauthorized or unrecorded fixture staging")


def validate_game_witness(game, context, inspection, stage, fingerprint):
    _require(game.get("schema") == "gen2-fixture-game-witness-v1"
             and game.get("case") == context.fixture and game.get("stage") == stage
             and game.get("stage_fingerprint") == fingerprint, "independent GAME witness missing/stale/misbound")
    _require(game.get("rom_sha1") == context.provenance["rom_sha1"]
             and game.get("cartram_sha256") == inspection["cartram_sha256"], "GAME source/save binding mismatch")
    hits = game.get("site_hits")
    _require(isinstance(hits, dict) and all(type(hits.get(site)) is int and hits[site] >= 0 for site in QUALIFY_SITES),
             "GAME witness code-site hit counts missing")
    # The verdict is re-derived from the recorded site hits (QUALIFY_SITES), never taken from the gate's flags.
    continued = hits["continue"] >= 1 and hits["continue_loaded"] >= 1
    loaded = continued and hits["finish_continue"] >= 1
    rtc = hits["rtc_ok"] >= 1 and hits["restart_clock"] == 0
    _require(game.get("core_mode") == "CGB" and game.get("speed_percent") == 100
             and game.get("observer") == "independent_GAME" and continued and loaded and rtc
             and hits["erase_save"] == 0 and game.get("continue_selected") is True
             and game.get("native_load_completed") is True and game.get("rtc_validated") is True,
             "GAME boot/RTC/CGB qualification incomplete")
    saves = game.get("save_success_counter")
    _require(type(saves) is int and (saves >= 1 and hits["same_save_file"] >= 1 if stage == "resave" else saves == 0),
             "GAME save counter or overwrite branch does not match the stage")
    _require(game.get("harness_write_scopes") == [] and game.get("input_mode") == "normal_buttons"
             and game.get("qualified") is False, "GAME witness recorded staging, non-button input or a qualification claim")
    _require(game.get("party_raw_hex") == inspection["party_raw_hex"], "GAME/PYDEC loaded-party mismatch")
    _require(game.get("location") == list(inspection["location"]) and game.get("position") == list(inspection["position"]),
             "GAME CONTINUE landed on a different map/checkpoint than the saved fixture")


def _cart_span(ctx, start, end):
    """Flat CartRAM (start, end) of a source span; end is a symbol or (symbol, bytes past it)."""
    def flat(name, extra=0):
        bank, address = ctx.symbol(name)
        _require(0 <= bank < 4 and 0xA000 <= address < 0xC000, f"not a CartRAM symbol: {name}")
        return bank * 0x2000 + address - 0xA000 + extra

    return flat(start), flat(*end) if isinstance(end, tuple) else flat(end)


def _wram_span(ctx, start, end):
    first = ctx.symbol(start[0]).address + start[1] if isinstance(start, tuple) else ctx.symbol(start).address
    last = ctx.symbol(end[0]).address + end[1] if isinstance(end, tuple) else ctx.symbol(end).address
    _require(first < last, f"empty source WRAM span: {start}")
    return first, last


def save_write_spans(title, layout, raw, root=ROOT):
    """Sorted (start, end) CartRAM spans the CONTINUE load and a native re-save may rewrite."""
    ctx = load_context(title, root=root)
    spans = [_cart_span(ctx, start, end)
             for start, end in SAVE_WRITES + (SAVE_WRITES_CRYSTAL if title == "crystal" else ())]
    spans += [(region.backup, region.backup + region.length) for region in layout.regions]
    box = _saved_field(raw, layout, "wCurBox", 1)[0]
    _require(box < len(layout.storage_boxes), "saved wCurBox outside the source box inventory")
    at, size = layout.storage_boxes[box]
    spans.append((at, at + size))
    _require(all(0 <= start < end <= CART_RAM_BYTES for start, end in spans), "save write span outside CartRAM")
    return sorted(spans)


def unexpected_resave_bytes(original, resaved, layout, title, root=ROOT):
    """(start, end) runs where a re-save changed CartRAM outside the source save write and scratch spans."""
    _require(len(original) == len(resaved) == CART_RAM_BYTES, "compare exactly two CartRAM images")
    ctx = load_context(title, root=root)
    allowed = bytearray(CART_RAM_BYTES)
    for start, end in save_write_spans(title, layout, original, root) + [
            _cart_span(ctx, *span) for span in SCRATCH_WRITES[title]]:
        allowed[start:end] = b"\x01" * (end - start)
    zeroed = range(*_cart_span(ctx, *BOOT_ZEROED[title])) if title in BOOT_ZEROED else range(0)
    runs = []
    for index in range(CART_RAM_BYTES):
        if original[index] != resaved[index] and not allowed[index] and not (index in zeroed and resaved[index] == 0):
            if runs and runs[-1][1] == index:
                runs[-1][1] = index + 1
            else:
                runs.append([index, index + 1])
    return [tuple(run) for run in runs]


def _symbol_namer(ctx):
    """(kind 'w'|'s', bank, address) -> the nearest source symbol at or below it."""
    table = {}
    for name, (bank, address) in ctx.symbols.items():
        if name[:1] in ("w", "s") and "." not in name:
            table.setdefault((name[0], bank), []).append((address, name))
    for rows in table.values():
        rows.sort()

    def name_at(kind, bank, address):
        rows = table.get((kind, bank), [])
        at = bisect.bisect_right(rows, (address, "\uffff")) - 1
        return rows[at][1] if at >= 0 else f"${address:04X}"

    return name_at


def _ruled_problems(ctx, title, before, after):
    """Start symbols of RESAVE_RULED_WRAM fields whose re-saved bytes are not their source transition from the
    candidate's, plus day stamps outside 0..DAYS_WRAP-1; before/after(symbol, size) read one save copy."""
    (count_b, day_b), (count_a, day_a) = before("wDailyResetTimer", 2), after("wDailyResetTimer", 2)
    problems = [symbol for symbol, at in (("wDailyResetTimer", 1), ("wTimerEventStartDay", 0))
                if not all(read(symbol, at + 1)[at] < DAYS_WRAP for read in (before, after))]
    days = (day_a - day_b) % DAYS_WRAP
    fired = count_b == 0 or days >= count_b   # UpdateTimeRemaining hit 0 (C engine/overworld/time.asm:288-306)
    for rule, start, end in RESAVE_RULED_WRAM["all"] + RESAVE_RULED_WRAM[title]:
        first, last = _wram_span(ctx, start, end)
        b, a = before(start, last - first), after(start, last - first)
        if rule == "daily_countdown":
            ok = a[0] == (1 if fired else count_b - days)
        elif rule == "daily_cleared":
            ok = not any(a) if fired else a == b
        elif rule == "kenji":
            ok = (a[0] == b[0] - 1 if b[0] >= 2 else 3 <= a[0] <= 6) if fired else a == b
        elif rule == "map_sign":
            ok = (a[0] ^ b[0]) & ~(1 << SHOWN_MAP_NAME_SIGN_F) & 0xFF == 0
        elif rule == "timer_counting":
            ok = a[0] == b[0] | 1 << GAME_TIMER_COUNTING_F
        elif rule == "swarm":
            ok = a == b if after("wDailyFlags1", 1)[0] >> DAILYFLAGS1_SWARM_F & 1 else not any(a)
        else:  # roam_indices
            ok = a == after("wMapNumber", 1) + after("wMapGroup", 1) + b[:2]
        if not ok:
            problems.append(start)
    return problems


def resave_scenario_delta(original, resaved, layout, title, root=ROOT):
    """Saved fields a no-op CONTINUE + native re-save changed inside the save spans (PLAN 5.6); [] passes.

    A FRESH-FIXTURE oracle (see RESAVE_FREE_SRAM's scope note): free fields accept any value, ruled fields only
    their source transition, sRTCStatusFlags only 0, and everything else must be byte-identical."""
    _require(len(original) == len(resaved) == CART_RAM_BYTES, "compare exactly two CartRAM images")
    ctx = load_context(title, root=root)
    free = bytearray(CART_RAM_BYTES)
    for span in RESAVE_FREE_SRAM + tuple((name, (name, 1)) for name in RESAVE_ZEROED_SRAM):
        start, end = _cart_span(ctx, *span)
        free[start:end] = b"\x01" * (end - start)
    copies = [(label, at, layout.addresses[_REGION_STARTS[region.name]], region.length,
               ctx.symbol(_REGION_STARTS[region.name]).bank)
              for region in layout.regions for label, at in (("", region.primary), ("backup ", region.backup))]
    ruled = tuple((start, end) for _, start, end in RESAVE_RULED_WRAM["all"] + RESAVE_RULED_WRAM[title])
    for first, last in (_wram_span(ctx, *row) for row in RESAVE_FREE_WRAM + ruled):
        covered = 0
        for _, at, base, length, _ in copies:  # a field may straddle two Gold/Silver regions
            low, high = max(first, base), min(last, base + length)
            if low < high:
                free[at + low - base:at + high - base] = b"\x01" * (high - low)
                covered += high - low
        _require(covered == 2 * (last - first), f"free WRAM field is not saved data in both copies: ${first:04X}")
    name_at, names = _symbol_namer(ctx), []
    for start, end in save_write_spans(title, layout, original, root):
        for index in range(start, end):
            if original[index] != resaved[index] and not free[index]:
                copy = next((row for row in copies if row[1] <= index < row[1] + row[3]), None)
                name = (copy[0] + name_at("w", copy[4], copy[2] + index - copy[1]) if copy
                        else name_at("s", index // 0x2000, 0xA000 + index % 0x2000))
                if name not in names:
                    names.append(name)

    def reader(image, label):
        def read(symbol, size):
            address = ctx.symbol(symbol).address
            for name, at, base, length, _ in copies:
                if name == label and base <= address and address + size <= base + length:
                    return image[at + address - base:at + address - base + size]
            raise ValueError(f"ruled field outside the saved copies: {label}{symbol}")
        return read

    for label in ("", "backup "):
        names += [label + symbol for symbol in _ruled_problems(ctx, title, reader(original, label), reader(resaved, label))]
    names += [name for name in RESAVE_ZEROED_SRAM if resaved[_cart_span(ctx, name, (name, 1))[0]] != 0]
    return names


def validate_identity_cohorts(rows):
    ids = {row["name"]: row["stages"][0]["evidence"]["player_id"] for row in rows}
    for title in ("crystal", "gold", "silver"):
        _require(ids[f"{title}_town"] == ids[f"{title}_battle"], "town/battle OT cohort differs")
    _require(ids["crystal_town_ot2"] == ids["crystal_battle_ot2"]
             and ids["crystal_town_ot2"] != ids["crystal_town"], "Crystal OT2 is not a distinct played identity")
    _require(ids["gold_battle_ot2"] != ids["gold_battle"], "Gold OT2 is not a distinct played identity")


def qualify_stage(context):
    """Independent PYDEC static oracle for one candidate; never a played-origin or GAME proof."""
    try:
        spec = BY_NAME[context.fixture]
        rom = context.artifacts["rom"]
        profile = _json(context.artifacts["profile"])
        _require(context.provenance["title"] == spec.title
                 and hashlib.sha1(rom).hexdigest() == context.provenance["rom_sha1"],
                 "ROM differs from the pinned sha1 of the selected title")
        _require((profile.get("source") or {}).get("rom_sha1") == context.provenance["rom_sha1"],
                 "profile belongs to another ROM")
        result = inspect_candidate(context.artifacts["fixture"], profile, rom, spec)
        facts = _json(context.artifacts["route_facts"])
        _require(_facts_sha256(facts) == context.provenance["route_facts_sha256"], "route facts differ from verified source")
        target = facts["maps"]["ElmsLab" if spec.target == "town" else "Route29"]
        _require(result["location"] == (target["map_group"], target["map_number"]), "saved target map mismatch")
        x, y = result["position"]
        _require(0 <= x < target["width"] and 0 <= y < target["height"], "saved coordinate outside source map")
        tile = target["grid"][y * target["width"] + x]
        _require(tile == 2 if spec.target == "battle" else tile == 1, "saved fixture terrain is not the required floor/grass")
        if spec.target == "battle":
            _require(any(item == facts["balls"]["item"] and quantity > 0 for item, quantity in result["ball_items"]),
                     "battle fixture has no real Poke Ball in the Ball pocket")
        validate_played_receipt(_json(context.artifacts["played_receipt"]), spec, facts, result)
        # O-10: fixture balls are harness-injected for tests/validation, never a ball_received witness.
        return qualification.StageReceipt(context.stage, context.fingerprint, "PASS",
            evidence={"oracle": "independent Gen2 PYDEC", "player_id": str(result["player_id"]),
                      "ball_origin": "O-10 harness injection" if spec.target == "battle" else "none",
                      "natural_ball_acquisition": "false"},
            notes=("Static bytes do not prove played origin, RTC or GAME qualification.",))
    except (ValueError, KeyError, TypeError) as exc:
        return qualification.StageReceipt(context.stage, context.fingerprint, "FAIL", problems=(str(exc),))


def post_oracle_stage(context):
    """Independent re-save PYDEC plus GAME raw-party witnesses; CartRAM only, never the RTC trailer."""
    try:
        spec = BY_NAME[context.fixture]
        profile = _json(context.artifacts["profile"])
        original = inspect_candidate(context.artifacts["fixture"], profile, context.artifacts["rom"], spec)
        saved = inspect_candidate(context.artifacts["resave:fixture"], profile, context.artifacts["rom"], spec)
        stages = {row["stage"]: row["fingerprint"] for row in context.previous}
        validate_game_witness(_json(context.artifacts["boot:game_witness"]), context, original, "boot", stages["boot"])
        # The native save itself (R4 S3): same-player overwrite branch, a counted successful save, and the
        # CartRAM it witnessed is exactly the re-save output judged below.
        save = _json(context.artifacts["resave:save_witness"])
        validate_game_witness(save, context, original, "resave", stages["resave"])
        _require(save.get("resave_cartram_sha256") == saved["cartram_sha256"],
                 "GAME save witness hash differs from the re-saved fixture")
        validate_game_witness(_json(context.artifacts["resave:reload_witness"]), context, saved, "reload", stages["resave"])
        _require(saved["player_id"] == original["player_id"] and saved["identity_key"] == original["identity_key"],
                 "re-save changed fixture identity")
        # Compared directly with the candidate, not only through the GAME witnesses read after the save.
        for key in ("location", "position", "party_raw_hex", "ball_items"):
            _require(saved[key] == original[key], f"re-save changed the saved {key}")
        from server.adapters import gen2_codec as codec

        layout = codec.Gen2Layout.from_profile(profile, spec.title)
        before, after = cart_ram(context.artifacts["fixture"]), cart_ram(context.artifacts["resave:fixture"])
        stray = unexpected_resave_bytes(before, after, layout, spec.title)
        _require(not stray, "re-save changed CartRAM outside the source save regions: "
                 + ", ".join(f"${start:04X}-${end - 1:04X}" for start, end in stray[:8]))
        delta = resave_scenario_delta(before, after, layout, spec.title)
        _require(not delta, "re-save changed saved fields a CONTINUE + save must preserve: " + ", ".join(delta[:8]))
        return qualification.StageReceipt(context.stage, context.fingerprint, "PASS",
            evidence={"oracle": "independent re-save PYDEC + GAME raw-party witness"})
    except (ValueError, KeyError, TypeError) as exc:
        return qualification.StageReceipt(context.stage, context.fingerprint, "FAIL", problems=(str(exc),))


def _stage_gate(context, stage, fixture, *, label, attempt_id, root, runner, timeout):
    """One warm-boot qualification gate run on exactly these SaveRAM bytes; returns (dir, witness path, witness)."""
    from tools import run_gb_gate

    spec = BY_NAME[context.fixture]
    facts_text = context.artifacts["route_facts"].decode("utf-8")
    qfacts = qualify_facts(spec.title, root, errand=True) if spec.name in ERRAND_FIXTURES else qualify_facts(spec.title, root)
    _require(qfacts["route_facts_fingerprint"] == _json(facts_text)["fingerprint"],
             "qualification facts differ from the recorded route facts")
    directory = (Path(root).resolve() / ".cache/gen2-fixtures" / attempt_id / spec.name / "qualify"
                 / f"{label}-{context.fingerprint[:16]}")
    directory.mkdir(parents=True, exist_ok=True)
    source = directory / (spec.name + ".input.SaveRAM")
    source.write_bytes(fixture)
    witness = directory / f"{spec.name}.{stage}.witness.json"
    witness.unlink(missing_ok=True)
    case = {**vars(spec), "title_idle_frames": 0, "attempt_id": attempt_id, **QUALIFY_BUDGET}
    passed, _, text = (runner or run_gb_gate.run_gate)(
        GATE_SCRIPT, rom_key=spec.title, target=spec.target, timeout=timeout, saveram_dir=str(directory),
        fixture_path=str(source), speed_percent=QUALIFY_SPEED_PERCENT,
        env_overrides={"SLINK_GEN2_FIXTURE_CASE": json.dumps(case), "SLINK_GEN2_ROUTE_FACTS": facts_text,
                       "SLINK_GEN2_QUALIFY": json.dumps({"stage": stage, "stage_fingerprint": context.fingerprint,
                                                         "facts": qfacts})})
    _require(passed and witness.is_file(), f"{stage} gate did not pass: {(text or '').strip()[-400:]}")
    return directory, witness, _json(witness.read_bytes())


def _boot_stage(context, **gate):
    """Warm boot the candidate SaveRAM (COLD=0), CONTINUE into the overworld; GAME must agree with PYDEC."""
    try:
        spec = BY_NAME[context.fixture]
        inspection = inspect_candidate(context.artifacts["fixture"], _json(context.artifacts["profile"]),
                                       context.artifacts["rom"], spec)
        _, path, game = _stage_gate(context, "boot", context.artifacts["fixture"], label="boot", **gate)
        validate_game_witness(game, context, inspection, "boot", context.fingerprint)
        return qualification.StageReceipt(context.stage, context.fingerprint, "PASS",
            evidence={"observer": "independent_GAME CONTINUE", "location": json.dumps(game["location"]),
                      "position": json.dumps(game["position"]), "cartram_sha256": inspection["cartram_sha256"]},
            outputs={"game_witness": path})
    except (ValueError, KeyError, TypeError, OSError) as exc:
        return qualification.StageReceipt(context.stage, context.fingerprint, "FAIL", problems=(str(exc),))


def _resave_stage(context, **gate):
    """CONTINUE, native START/SAVE, flush; then warm boot the re-save and CONTINUE again (reload)."""
    try:
        from tools import run_gb_gate

        spec = BY_NAME[context.fixture]
        profile, rom = _json(context.artifacts["profile"]), context.artifacts["rom"]
        original = inspect_candidate(context.artifacts["fixture"], profile, rom, spec)
        directory, save_path, game = _stage_gate(context, "resave", context.artifacts["fixture"], label="resave", **gate)
        validate_game_witness(game, context, original, "resave", context.fingerprint)
        flushed = (directory / run_gb_gate.describe_gen2(spec.title)["saveram_name"]).read_bytes()
        after = inspect_candidate(flushed, profile, rom, spec)
        _require(game.get("resave_cartram_sha256") == after["cartram_sha256"],
                 "flushed re-save differs from the GAME-witnessed CartRAM")
        resaved = directory / (spec.name + ".resaved.SaveRAM")
        resaved.write_bytes(flushed)
        _, reload_path, reload = _stage_gate(context, "reload", flushed, label="reload", **gate)
        validate_game_witness(reload, context, after, "reload", context.fingerprint)
        return qualification.StageReceipt(context.stage, context.fingerprint, "PASS",
            evidence={"observer": "independent_GAME re-save + reload", "resave_cartram_sha256": after["cartram_sha256"]},
            outputs={"fixture": resaved, "save_witness": save_path, "reload_witness": reload_path})
    except (ValueError, KeyError, TypeError, OSError) as exc:
        return qualification.StageReceipt(context.stage, context.fingerprint, "FAIL", problems=(str(exc),))


def game_callbacks(attempt_id, *, root=ROOT, runner=None, timeout=1200):
    """The Gen 2 boot/resave stages, bound to the reviewed gate through tools/run_gb_gate.run_gate."""
    _require(isinstance(attempt_id, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,80}", attempt_id) is not None,
             "bounded attempt ID required")
    gate = {"attempt_id": attempt_id, "root": root, "runner": runner, "timeout": timeout}
    return {"boot": lambda context: _boot_stage(context, **gate),
            "resave": lambda context: _resave_stage(context, **gate)}


def _fixture_case(spec, fixture, receipt, facts_path, facts, root):
    ctx = load_context(spec.title, root=root)
    return qualification.FixtureCase(spec.name,
        {"fixture": fixture, "profile": Path(root) / f"data/games/gen2_{spec.title}/profile.json",
         "rom": ctx.source_dir / ctx.lock["outputs"][ctx.artifact]["filename"],
         "route_facts": facts_path, "played_receipt": receipt},
        {"title": spec.title, "rom_sha1": ctx.source_record()["rom_sha1"], "scope": "candidate fixture",
         "route_facts_sha256": _facts_sha256(facts)})


def qualify(spec_or_name, candidate_path, attempt_id, *, receipt_path=None, root=ROOT, runner=None, timeout=1200):
    """Full-chain qualification of ONE played candidate (run_play's candidate_path/receipt_path).

    Static PYDEC, boot/CONTINUE, native re-save + reload, independent post-oracle. Launches EmuHawk
    three times (boot, resave, reload) at 100%; the report never claims physical qualification.
    """
    spec = spec_or_name if isinstance(spec_or_name, FixtureSpec) else BY_NAME[spec_or_name]
    callbacks = {"qualify": qualify_stage, "post_oracle": post_oracle_stage,
                 **game_callbacks(attempt_id, root=root, runner=runner, timeout=timeout)}
    candidate = Path(candidate_path)
    receipt = Path(receipt_path) if receipt_path else candidate.parent / (spec.name + ".played.json")
    facts = spec_route_facts(spec, root)
    snapshot = Path(root).resolve() / ".cache/gen2-fixtures" / attempt_id / spec.name / "qualify"
    snapshot.mkdir(parents=True, exist_ok=True)
    facts_path = snapshot / (spec.title + "_route_facts.json")
    facts_path.write_text(json.dumps(facts), encoding="utf-8")
    report = qualification.qualify_fixtures([_fixture_case(spec, candidate, receipt, facts_path, facts, root)],
                                            callbacks, scope="full", attempt_id=attempt_id, max_fixtures=1)
    report["physical_qualification"] = False
    report["open_obligations"] = ["coordinator GAME/RTC/played-origin review", "recorded source/physical gate sign-off"]
    return report


def qualification_report(directory, *, root=ROOT, scope="static", game_callbacks=None):
    """Exactly the FIXTURES cases; full mode requires independent GAME callbacks."""
    callbacks = {"qualify": qualify_stage, "post_oracle": post_oracle_stage}
    by_name = BY_NAME
    if game_callbacks:
        _require(set(game_callbacks) <= {"boot", "resave"}, "independent PYDEC callbacks cannot be replaced")
        callbacks.update(game_callbacks)
    try:
        paths = qualification.enumerate_fixtures(Path(directory), suffix=".SaveRAM", max_fixtures=len(by_name))
        _require({path.stem for path in paths} == set(by_name), "exact played-fixture inventory required")
        # Facts files are supplied by the coordinator's immutable attempt snapshot.
        cases, facts_by_title = [], {}
        for path in paths:
            spec = by_name[path.stem]
            errand = spec.name in ERRAND_FIXTURES
            if (spec.title, errand) not in facts_by_title:
                facts_by_title[spec.title, errand] = spec_route_facts(spec, root)
            cases.append(_fixture_case(spec, path, Path(directory) / (spec.name + ".played.json"),
                                       Path(directory) / (spec.title + ("_errand" if errand else "") + "_route_facts.json"),
                                       facts_by_title[spec.title, errand], root))
        report = qualification.qualify_fixtures(cases, callbacks, scope=scope, max_fixtures=len(by_name))
        if report["passed"]:
            try:
                validate_identity_cohorts(report["fixtures"])
            except (ValueError, KeyError) as exc:
                report["passed"] = False
                report["errors"].append(str(exc))
    except (ValueError, OSError) as exc:
        report = qualification.qualify_fixtures([], callbacks, scope=scope, max_fixtures=len(BY_NAME))
        report["errors"].append(str(exc))
    report["physical_qualification"] = False
    report["open_obligations"] = ["coordinator GAME/RTC/played-origin review", "recorded source/physical gate sign-off"]
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--qualify", type=Path, help="read-only candidate inventory")
    parser.add_argument("--scope", choices=("static", "full"), default="static")
    args = parser.parse_args(argv)
    try:
        result = qualification_report(args.qualify, root=args.root, scope=args.scope) if args.qualify else fixture_manifest(args.root)
        print(json.dumps(result, indent=2))
        return 0 if args.qualify is None or result["passed"] else 1
    except (ValueError, KeyError, OSError) as exc:
        print(json.dumps({"passed": False, "qualified": False, "error": str(exc)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
