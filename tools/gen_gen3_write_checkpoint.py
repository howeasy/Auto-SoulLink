#!/usr/bin/env python3
"""Generate data/games/gen3_{frlg,rr,emerald}/write_checkpoint.json from the pinned pret .sym + the ROMs.

The Gen 3 overworld write checkpoint is the Gen 1 idea (lua/gen1_write_safety.lua,
data/games/gen1_rby/write_checkpoint.json) carried to GBA: a SOURCE predicate that admits a
host write only while no member of the writer inventory (docs/gen3_write_checkpoint.md) can be
in progress.  Nothing here is an observation -- every address is a symbol from
data/gen3/pret/*.sym (pret/pokefirered c75f3523, provenance.json) and every ROM anchor is
sliced from the admitted ROM at that symbol.

Radical Red ships no symbols, so each FRLG fact is re-derived from the RR binary before it is
allowed into the RR pack:

  * a code symbol is VERIFIED when the whole FR function body is byte-identical at the same
    address in both RR ROMs (clean 4.1 base and the SLink companion build);
  * a data symbol is VERIFIED when the literal-pool word(s) that hold its address inside a
    named FR witness function still hold the same address at the same offsets in both RR ROMs
    (this survives a patched instruction in the witness -- e.g. the companion's hook inside
    CallCallbacks -- because only the pool word is asserted).

An RR entry that fails its check is NOT emitted; it is reported here and listed as UNVERIFIED
in docs/gen3_write_checkpoint.md.  Fail-closed: a missing fact is a missing predicate, never a
guessed one.

Vanilla Emerald (E1-CHECKPOINT, docs/gen3_emerald/write_checkpoint.md) is generated from
data/gen3/pret/pokeemerald.sym (pret/pokeemerald c65e93f2) the FR/LG way, as SOURCE facts only:
it is not an admitted pack (UNADMITTED_PACKS) until EG4 signs it.  pret publishes no
pokeemerald.map, so the player controller's .text span comes from the .sym (sym_text_span).

    python tools/gen_gen3_write_checkpoint.py            # rewrite every pack
    python tools/gen_gen3_write_checkpoint.py --check    # exit 1 if a committed file is stale
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import struct
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SYM_DIR = ROOT / "data" / "gen3" / "pret"
VERSION = "gen3-overworld-v1"
ROM_BASE = 0x08000000

# (pack, title, kind) -> (path, sha1).  Duplicated from tools/pin_gen3_site.py ROM_SPECS on
# purpose: that file is a different P2 lease.  Fold the two together once both have landed.
ROMS = {
    ("gen3_frlg", "firered", "clean"): (
        pathlib.Path("E:/Google Drive/SLink/Pokemon - FireRed Version (USA).gba"),
        "41cb23d8dccc8ebd7c649cd8fbb58eeace6e2fdc"),
    ("gen3_frlg", "leafgreen", "clean"): (
        pathlib.Path("E:/Google Drive/SLink/Pokemon - LeafGreen Version (USA).gba"),
        "574fa542ffebb14be69902d1d36f1ec0a4afd71e"),
    ("gen3_rr", "radical_red", "clean"): (
        pathlib.Path("E:/Google Drive/SLink/Pokemon - Radical Red.gba"),
        "964f951a0fdaf209e4ea1344883ef0d557bb3a80"),
    ("gen3_rr", "radical_red", "companion"): (
        ROOT / "patch" / "build" / "slink_RR.gba",
        "ea5352f8a3b9073f8ae20870ad12857925d442cd"),
    ("gen3_emerald", "emerald", "clean"): (
        pathlib.Path("E:/Google Drive/SLink/Pokemon - Emerald Version (USA, Europe).gba"),
        "f3ae088181bf583e55daf962a92bb46f4f1d07b7"),
}

# pack -> {title: (sym file, kinds...)}.  RR reads the FireRed symbols and proves each one
# against its own ROMs; firered_ap is not admitted (PLAN s0) and gets no checkpoint.
PACKS = {
    "gen3_frlg": {"firered": ("pokefirered.sym", ("clean",)),
                  "leafgreen": ("pokeleafgreen.sym", ("clean",))},
    "gen3_rr": {"radical_red": ("pokefirered.sym", ("clean", "companion"))},
}
# E1-CHECKPOINT: generated and --check'ed like the admitted packs, but kept out of PACKS: Emerald
# stays unadmitted (ruling 24) until EG4 signs the port (docs/gen3_emerald/PLAN.md s0, s3 E1).
UNADMITTED_PACKS = {
    "gen3_emerald": {"emerald": ("pokeemerald.sym", ("clean",))},
}
ALL_PACKS = {**PACKS, **UNADMITTED_PACKS}

# title -> {FR spelling the tables below use: the title's own spelling}.  Applied right after
# parse_sym by title_syms; a stale or missing target is fatal, never a silent skip.
#   sSaveDialogCB   -> sSaveDialogCallback  pokeemerald src/start_menu.c:88 (EWRAM; FR's is IWRAM)
#   RunSaveDialogCB -> RunSaveCallback      pokeemerald src/start_menu.c:884-894
RENAMES = {"emerald": {"sSaveDialogCB": "sSaveDialogCallback", "RunSaveDialogCB": "RunSaveCallback"}}

# name -> (symbol, offset into it, length or None = the symbol's own size)
ANCHORS = {
    "cb2_overworld": ("CB2_Overworld", 0, None),
    "cb1_overworld": ("CB1_Overworld", 0, None),
    "run_tasks": ("RunTasks", 0, None),
    # the per-frame exec site the P1 probe measured (docs/gen3/probes/hooks_*_2026-09-21.txt
    # REGISTER frame addr=0x0800051A): CallCallbacks' `bl RunHelpSystemCallback`.
    "frame_control": ("CallCallbacks", 0x0A, 8),
    "try_saving_data": ("TrySavingData", 0, None),
}
# title -> anchors that differ.  Emerald's CallCallbacks (pokeemerald src/main.c:188-195) has no
# save-failed/help-system gate, so FR's +0x0A `bl RunHelpSystemCallback` slice does not exist
# there; the anchor pins the whole body, the entry docs/gen3_emerald/engine_sites.md captures.
TITLE_ANCHORS = {"emerald": {"frame_control": ("CallCallbacks", 0, None)}}

# name -> (symbol, offset, width, mask, expect).  mask None = compare the whole read.
PREDICATES = {
    # gMain.callback1 / .callback2 (include/main.h: +0x000, +0x004); expect is the Thumb pointer
    "callback1": ("gMain", 0x000, 4, None, "CB1_Overworld"),
    "callback2": ("gMain", 0x004, 4, None, "CB2_Overworld"),
    # struct Main +0x439 bitfield: bit0 oamLoadDisabled, bit1 inBattle
    "in_battle": ("gMain", 0x439, 1, 0x02, 0),
    # struct PaletteFadeControl +4 bitfield, active is bit 31 -> byte +7 bit 7
    "palette_fade_active": ("gPaletteFade", 0x007, 1, 0x80, 0),
    # src/script.c: field controls are locked for the whole life of a script
    "field_controls_locked": ("sLockFieldControls", 0, 1, None, 0),
    # src/script.c CONTEXT_RUNNING=0, CONTEXT_WAITING=1, CONTEXT_SHUTDOWN=2
    "script_context_status": ("sGlobalScriptContextStatus", 0, 1, None, 2),
    # src/save.c Task_LinkFullSave sets this for the duration of the link full save
    "soft_reset_disabled": ("gSoftResetDisabled", 0, 1, None, 0),
    # C4-SAVE: "a link callback can run" is sLinkOpen, not gLinkCallback != NULL.  gLinkCallback
    # is executed at exactly one site, LinkMain2 link.c:522-523, behind `if (!sLinkOpen) return`
    # (:512-513).  sLinkOpen is set only by InitLink (:373), reached only from OpenLink's cable
    # branch (:390-394, the same call that sets gLinkCallback), and cleared by CloseLink (:424,
    # also the link-error path :1400-1412).  CloseLink never clears gLinkCallback, so after a
    # cancelled no-partner Cable Club link it rests on LinkCB_RequestPlayerDataExchange with the
    # link closed (live FR center_controls r9) -- a dead pointer that held every write forever.
    # The key keeps its name because lua/gen3/safety.lua requires it by name.
    "link_callback": ("sLinkOpen", 0, 1, None, 0),
    "link_transferring": ("gLinkTransferringData", 0, 1, None, 0),
    # src/link.c:421 CloseLink / :410 OpenLink clear it; :540 (cable) and link_rfu_2.c:1879,2065
    # (wireless) set it once the partner's player data is in -- non-zero for a whole link session.
    # NOT gWirelessCommType: that is the transport selector (0 cable, 1 RFU), set by the title
    # menu's adapter probe (main_menu.c:573 -> link.c:243-261) and sticky (CloseLink leaves it),
    # so it is 1 for the whole session on hardware with the adapter (receipt
    # docs/gen3/probes/checkpoint_fr_parcel_lineage_2026-09-22.txt).  The pre-exchange window is
    # link_callback (sLinkOpen, cable) + callback1 + the task allow-list; the RFU branch of
    # OpenLink (:406-408) never set gLinkCallback, so wireless never rested on that clause.
    "link_players_received": ("gReceivedRemoteLinkPlayers", 0, 1, None, 0),
}

# name -> the same shape as PREDICATES, emitted as `witnesses`: read by the test drivers, never a
# safety clause.  C4-SAVE: sSaveDialogCB (start_menu.c:71) is assigned at :608-842, always
# non-NULL, and never reset, so after the first save of a boot it rests on
# SaveDialogCB_ReturnSuccess (live LG r9: 0x0806F9E1, 404 holds on an idle field).  A live save
# is refused without it: the whole START-menu dialog runs inside Task_StartMenuHandleInput
# (:378-394) under ShowStartMenu's lock (:405 until :586/:598, the call that destroys the task);
# the script save runs task50_save_game (:620-654) under waitstate (CONTEXT_WAITING) and the
# script lock; TrySavingData is synchronous inside SaveDialogCB_DoSave (:791-805).  It stays a
# witness because a change in it is how gen3_boot_check.save_via_menu sees the dialog OPEN.
WITNESSES = {
    "save_dialog_cb": ("sSaveDialogCB", 0, 4, None, 0),
}

# data symbol -> the FR function whose literal pool pins it (used only to prove RR)
WITNESS = {
    "gMain": "CallCallbacks",
    "gTasks": "RunTasks",
    "gPaletteFade": "CB2_Overworld",
    "sLockFieldControls": "ArePlayerFieldControlsLocked",
    "sGlobalScriptContextStatus": "ScriptContext_IsEnabled",
    "sSaveDialogCB": "RunSaveDialogCB",
    "gSoftResetDisabled": "AgbMain",
    "gLinkTransferringData": "AgbMain",
    "sLinkOpen": "CloseLink",
    "gReceivedRemoteLinkPlayers": "CloseLink",
}

# predicate -> the FR code its soundness argument rests on.  For RR every body must be
# byte-identical (verify_code) or the predicate is not emitted (fail-closed).
PREDICATE_CODE = {
    "link_callback": ("InitLink", "OpenLink", "CloseLink", "LinkMain2"),
}

# Every task that is legitimately running while the player just stands in the overworld:
# SetUpFieldTasks (src/field_tasks.c:84-94) and StartWeather (src/field_weather.c:146-170),
# both reached from Overworld resume (src/overworld.c:2118-2121, 2444-2446).  Task_WeatherInit
# is deliberately absent: it is the transient that becomes Task_WeatherMain, and an in-flight
# initialiser is not an idle frame.
#
# C4-UR (owner ruling PLAN s0 "Writes inside Pokemon Centers"): every Center 1F's ON_RESUME is
# CableClub_OnResume -> special InitUnionRoom (data/scripts/cable_club.inc:1120-1122), which
# leaves the rev-0 Union Room *background* set running: Task_InitUnionRoom (src/union_room.c:
# 3515-3604, parks in state 3 forever), Task_SearchForChildOrParent (:3714-3745) and
# Task_UnionRoomListen (src/link_rfu_2.c:505-564, via :2727-2742).  None of them, nor anything
# they reach, names gPlayerParty/gPlayerPartyCount/gPokemonStoragePtr or a save/flash routine;
# their save-block access is read-only (link_rfu_3.c:850-873, :1178-1192, link_rfu_2.c:2151-2154).
# Every step out of "background only" creates a task that stays OFF this list (Task_PlayerExchange
# /Chat link_rfu_2.c:539-559, Task_TryConnectToUnionRoomParent :2519, Task_RunUnionRoom
# union_room.c:2579-2584, Task_StartActivity, Task_TryBecomeLinkLeader/Task_TryJoinLinkGroup)
# or trips a predicate (gReceivedRemoteLinkPlayers, callback1/2, script lock).
CENTER_UNION_ROOM_TASKS = ("Task_InitUnionRoom", "Task_SearchForChildOrParent", "Task_UnionRoomListen")
ALLOWED_TASKS = ("Task_RunPerStepCallback", "Task_RunTimeBasedEvents", "Task_WeatherMain") \
    + CENTER_UNION_ROOM_TASKS
# C4-SAVE audit: the Elite Four / Champion room lighting.  DoPokemonLeagueLightingEffect
# (src/field_specials.c:2133-2158) is each league room's ON_RESUME (e.g. data/maps/
# PokemonLeague_LoreleisRoom/scripts.inc:9-12 -> data/scripts/pokemon_league.inc:62-64) and
# creates Task_RunPokemonLeagueLightingEffect, which never destroys itself (:2160-2185) and keeps
# running after the entrance script's releaseall (scripts.inc:43-48), so the player walks freely
# beside it.  Its whole reach is palettes: FlagGet (event_data.c:303-311, a read), a read of
# gSaveBlock1Ptr->location, LoadPalette and ApplyGlobalTintToPaletteSlot (fieldmap.c:863-883,
# gPlttBufferUnfaded/Faded).  It is destroyed by StopPokemonLeagueLightingEffectTask
# (:2205-2209; the START menu :453 and item_use.c call it before leaving the field) and by
# ResumeMap's ResetTasks (overworld.c:2105).  Task_CancelPokemonLeagueLightingEffect stays OFF:
# it lives only inside the post-battle script, until FLAG_TEMP_4 (pokemon_league.inc:7,41).
# FR/LG only: RR's RunOnResumeMapScript body differs and CFRU's league map scripts are not
# decoded, so reachability there is unproven and RR keeps refusing (fail-closed).
FRLG_ONLY_TASKS = ("Task_RunPokemonLeagueLightingEffect",)
ALLOWED_TASKS_SOURCE = ("pret c75f3523: src/field_tasks.c:84-94, src/field_weather.c:146-170; "
                        "Center 1F Union Room background (C4-UR): data/scripts/cable_club.inc:1120-1122, "
                        "src/union_room.c:3515-3604,3714-3745, src/link_rfu_2.c:505-564,2727-2742; "
                        "league room lighting (FR/LG only): src/field_specials.c:2133-2185,2205-2209; "
                        "RR: FR body byte-identical at the same address in every RR ROM")

# E1-CHECKPOINT, Emerald (pret/pokeemerald c65e93f2).  SetUpFieldTasks (src/field_tasks.c:181-194)
# creates a third always-on field task FR lacks: Task_MuddySlope (:893-957).  Its whole reach is
# PlayerGetDestCoords, a read of gSaveBlock1Ptr->location (:900), MapGridGetMetatileBehaviorAt, and
# SetMuddySlopeMetatile (:880-891: MapGridSetMetatileIdAt + CurrentMapDrawMetatileAt, the map grid
# and BG tilemap) -- no party, storage or save routine.  Without it every Emerald field frame would
# refuse on "unknown active task".  Task_RunPokemonLeagueLightingEffect does not exist in Emerald
# (0 in pokeemerald.sym, 0 in src/), so the FR/LG league row is excluded by name with that reason.
# E2-CKPT: the map-name popup.  ShowMapNamePopup (src/map_name_popup.c:231-251) creates
# Task_MapNamePopUpWindow on every warp or connection into a show_map_name map
# (src/overworld.c:822-824,1698-1702,1946-1947) and on CONTINUE; it lives ~190 frames with the
# player free (E2 census: 111 settled frames after CONTINUE).  Its whole reach (:254-426) is
# window/BG/palette work: FlagGet (a read), CurrentBattlePyramidLocation (a gMapHeader read,
# src/battle_pyramid.c:1423-1431), GetMapName into a stack buffer (src/region_map.c:1568-1598;
# the secret-base spelling reads gSaveBlock1Ptr, src/secret_base.c:728-738), Add/Remove
# MapNamePopUpWindow (src/menu.c:521-540, window buffers from gHeap 0x02000000..0x0201C000,
# disjoint from gPlayerParty/gSaveblock1/2 and storage), LoadBgTiles/LoadPalette/BlitBitmap/
# AddTextPrinterParameterized/CopyWindowToVram, SetGpuReg and DestroyTask -- no party, storage,
# flag/var or save write.  FR/LG keep their Task_MapNamePopup OFF (a finite hold, checkpoint
# predicate audit 2026-09-23); admitting it there is a separate FR decision.
EMERALD_ONLY_TASKS = ("Task_MuddySlope", "Task_MapNamePopUpWindow")
# title -> the tasks it adds to ALLOWED_TASKS (RR adds none: see FRLG_ONLY_TASKS)
TITLE_TASKS = {"firered": FRLG_ONLY_TASKS, "leafgreen": FRLG_ONLY_TASKS, "emerald": EMERALD_ONLY_TASKS}
# title -> {FR/LG allow-list task left out: why}.  Emitted as tasks.excluded_tasks.
TASKS_EXCLUDED = {"emerald": {
    "Task_RunPokemonLeagueLightingEffect": (
        "absent from pret/pokeemerald c65e93f2 (0 in pokeemerald.sym, 0 in src/): the Hoenn league "
        "rooms create no lighting task, so there is nothing to admit")}}
TASKS_SOURCE = {"emerald": (
    "pret pokeemerald c65e93f2: src/field_tasks.c:181-194 (SetUpFieldTasks: Task_RunPerStepCallback "
    ":138, Task_MuddySlope :880-957, Task_RunTimeBasedEvents :150-177), src/field_weather.c:154-181,"
    "216-227 (StartWeather -> Task_WeatherInit -> Task_WeatherMain); Center 1F Union Room background: "
    "data/scripts/cable_club.inc:1226-1228 (CableClub_OnResume), src/union_room.c:3294-3377,3465-3497, "
    "src/link_rfu_2.c:510-565,2640-2649; map-name popup (E2-CKPT): src/map_name_popup.c:231-426, "
    "src/menu.c:521-540, src/overworld.c:822-824,1698-1702,1946-1947; FR/LG league lighting excluded "
    "(absent in Emerald)")}
# E1-CHECKPOINT: the Emerald-only forbidden states (docs/gen3_emerald/write_checkpoint.md s3).  The
# checkpoint is fail-closed on any task off the allow-list and on callback2 != CB2_Overworld, so
# these are refused already; the table is documentation + the E2 negative-control targets, and
# every name must be in the title's .sym (a missing one stops the build).
FORBIDDEN_INVENTORY = {"emerald": (
    "CB2_StartContest", "Task_StartContest", "CB2_ContestMain",            # contests
    "Task_EnterSecretBase", "Task_WarpOutOfSecretBase",                    # secret bases
    "Task_DoRecordMixing", "Task_RecordMixing_Main",                       # record mixing
    "CB2_LoadBerryBlender", "CB2_StartBlenderLink", "CB2_StartBlenderLocal",  # berry blender
    "CB2_FrontierPass", "Task_BattlePyramidChooseMonHeldItems",            # Frontier / Pyramid
    "Task_TrainerHillWaitForPaletteFade",                                  # Trainer Hill
    "CB2_HandleStartMultiPartnerBattle", "CB2_PreInitMultiBattle",         # multi-partner battle
    "CB2_HandleStartMultiBattle",
    "CB2_UnionRoomBattle",
)}
FORBIDDEN_PREFIXES = {"emerald": ("Task_LinkContest_",)}             # every link-contest task


def forbidden_inventory(title: str, syms) -> dict[str, int]:
    """{name: address} of the title's forbidden-state inventory; a name missing from the .sym is fatal."""
    out = {}
    for name in FORBIDDEN_INVENTORY.get(title, ()):
        if name not in syms:
            raise SystemExit(f"{title}: forbidden-inventory symbol {name} is not in the .sym")
        out[name] = syms[name][0]
    for prefix in FORBIDDEN_PREFIXES.get(title, ()):
        found = {n: a for n, (a, _) in syms.items() if n.startswith(prefix)}
        if not found:
            raise SystemExit(f"{title}: no {prefix}* symbol in the .sym")
        out.update(found)
    return out

# include/task.h: struct Task { TaskFunc func; bool8 isActive; u8 prev, next, priority; s16 data[16]; }
TASK_STRUCT_SIZE = 0x28
TASK_COUNT = 16

# The frame-end "parked CPU" clause is per title: one R15 range + CPSR mode + T bit.
#
# FRLG idles in ROM, not the BIOS: AgbMain ends every frame in WaitForVBlank (pret/pokefirered
# c75f3523 src/main.c:216 the call, :462-468 the body -- a busy-wait on gMain.intrCheck), so the
# range is that symbol's whole body from the title's own .sym, System mode (0x1F), Thumb.  FR
# census (docs/gen3/probes/census_fr_overworld_2026-09-21.txt): 1707/1800 frame ends at R15
# 0x080008AC..0x080008B4, mode 0x1F, T=1.  The other 93 landed in the BIOS IRQ vector (R15=0x1C,
# mode 0x12, T=0) and are refused on purpose -- the next parked frame admits.  LG census
# (docs/gen3/probes/census_lg_overworld_2026-09-23.txt, the first LG frame-end evidence): 1675/1800
# frame ends at R15 0x080008AC..0x080008B4, mode 0x1F, T=1, the same symbol range (the FR and LG
# .sym files agree on 0x08000890 + 0x30); the other 125 landed in the same BIOS IRQ vector and are
# refused on purpose.
PARKED_SYMBOL = "WaitForVBlank"
# Emerald: AgbMain ends every frame in WaitForVBlank too (pokeemerald src/main.c:167 the call,
# :410-416 the body, the same gMain.intrCheck busy-wait), so the range is SOURCE from the .sym.  E2
# census (docs/gen3_emerald/probes/census_emerald_overworld_2026-09-25.txt, Oldale, no input):
# 1678/1800 frame ends at R15 0x080008C8..0x080008D0, mode 0x1F, T=1 -- modal 0x080008C8, the same
# WaitForVBlank+0x1C as FR/LG's 0x080008AC; the other 122 in the same BIOS IRQ vector, refused.
FRLG_CENSUS = {"firered": (0x080008AC, "docs/gen3/probes/census_fr_overworld_2026-09-21.txt"),
               "leafgreen": (0x080008AC, "docs/gen3/probes/census_lg_overworld_2026-09-23.txt"),
               "emerald": (0x080008C8, "docs/gen3_emerald/probes/census_emerald_overworld_2026-09-25.txt")}
# RR (CFRU) parks in the BIOS instead (docs/gen3/probes/census_rr_overworld_2026-09-21.txt):
# 1800/1800 frames at R15=0x000001C4 with CPSR mode 0x1F (System) and T=0.
# G5-RR-CPU-IRQ (owner ruling 23, 2026-09-24): with the client's exec hooks registered, every RR frame
# instead ends on the BIOS IRQ vector entry taken from that halt (docs/gen3/probes/
# rr_cpu_irq_bios_2026-09-24.txt): R15 = 0x1C (the vector at 0x18 + 4, before the handler runs), CPSR
# mode 0x12, ARM, and the banked R14_irq = 0x1C4 (emu.getregister("R14") is the current mode's bank).
# The BIOS is mGBA's HLE BIOS (BizHawk 2.11.1, no firmware): SWI 2 Halt = 0x1B4..0x1C0 (mov r11,#0;
# mov r12,#0x04000000; strb r11,[r12,#0x301]; bx lr), so R14_irq - 4 = 0x1C0 is the instruction after
# the HALTCNT write. The shape admits an IRQ entry only when R14_irq - 4 lies in Halt's body
# (0x1B4..0x1C0): an interrupt taken from game code (R14 in ROM/RAM) stays refused.
RR_IRQ_ENTRY = {"mode": 0x12, "thumb": 0, "pc": [0x1C], "lr_min": 0x1B8, "lr_max": 0x1C4,
                "bios_sha1": "d0418465f8783dc6cbb180a16808fc9d3a7bae1d",
                "evidence": "docs/gen3/probes/rr_cpu_irq_bios_2026-09-24.txt"}
RR_CPU = {"mode": 0x1F, "thumb": 0, "pc_min": 0x00000000, "pc_max": 0x00003FFF,
          "observed_pc": 0x000001C4,
          "census": "docs/gen3/probes/census_rr_overworld_2026-09-21.txt",
          "irq_entry": RR_IRQ_ENTRY}


def cpu_clause(title: str, syms, is_rr: bool) -> dict:
    if is_rr:
        return json.loads(json.dumps(RR_CPU))            # a deep copy: irq_entry is a nested dict
    if PARKED_SYMBOL not in syms:
        raise SystemExit(f"{title}: missing parked-CPU symbol {PARKED_SYMBOL}")
    addr, size = syms[PARKED_SYMBOL]
    cpu = {"mode": 0x1F, "thumb": 1, "pc_min": addr, "pc_max": addr + size - 1,
           "symbol": PARKED_SYMBOL}
    if title in FRLG_CENSUS:
        pc, census = FRLG_CENSUS[title]
        if not addr <= pc < addr + size:
            raise SystemExit(f"{title}: census PC {pc:#010x} is outside {PARKED_SYMBOL}")
        cpu.update(observed_pc=pc, census=census)
    return cpu

# ── the RR save-block pointers, read out of the ROM's own setter (card C3-33) ─────────────────
# pret/pokefirered c75f3523 src/load_save.c:69-83 SetSaveBlocksPointers stores &<object> + offset
# into three IWRAM pointer variables.  The *address* of the function is the FireRed symbol (RR is
# an FR rebuild and keeps it there), but no pointer address is taken from the symbol table: the
# pool words are read out of the body after it is signature-checked, so a build that moved or
# reshaped the setter fails closed instead of shipping an address nobody verified.
#
# The old client's radical_red profile ships 0x03003840 / 0x03003838 for these two, which is
# neither of them: those addresses are a literal-pool constant (`&gSaveBlock1` / `&gSaveBlock2`)
# inside IntrMain_Buffer, the DMA'd copy of the intr_main blob at ROM 0x08000248.  They read
# correctly on today's RR only because its offset is fixed at 0, so the constant equals the live
# pointer; nothing enforces that, and it cannot be a pack's evidence.
SETTER_SYMBOL = "SetSaveBlocksPointers"
# ROM file 0x4C058: push {r4,r5,lr}; ldr r4,[pc,#0x30]; ldr r5,[r4]; bl Random
SETTER_PREFIX = bytes.fromhex("30b50c4c2568f8f733ff")
SETTER_BODY = 0x34          # the body; its six-word literal pool starts here (ROM file 0x4C08C)
SETTER_OFFSET_AT = 0x0A
# `movs r1,#0` twice, where vanilla FR has `movs r1,#0x7C; ands r1,r0` (load_save.c:75).  RR's
# save-block offset is therefore always 0: the pointer values never move, while the legacy
# 0x03003840 alias inside IntrMain_Buffer would not move with them if they did
# (docs/gen3/research/checkpoint_unreached_states.md §4).
SETTER_OFFSET_BYTES = bytes.fromhex("00210021")
# EWRAM object -> the pointer variable the setter stores its address into.  The three objects are
# the pool's EWRAM words; docs/gen3/research/rr_save_layout.md:55-68 validates them against the
# bytes the real save file has at those bases.
SAVEBLOCK_BASES = {0x0202552C: "gSaveBlock1Ptr", 0x02024588: "gSaveBlock2Ptr",
                   0x02029314: "gPokemonStoragePtr"}
SAVEBLOCK_POINTERS = ("gSaveBlock1Ptr", "gSaveBlock2Ptr", "gPokemonStoragePtr")
IWRAM_RANGE = (0x03000000, 0x03008000)
POOL_SOURCE = "rom:SetSaveBlocksPointers pool"


def parse_sym(path: pathlib.Path) -> dict[str, tuple[int, int]]:
    """`address l/g size name` -> {name: (address, size)}; the first spelling wins."""
    out: dict[str, tuple[int, int]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) == 4 and parts[1] in ("l", "g"):
            out.setdefault(parts[3], (int(parts[0], 16), int(parts[2], 16)))
    if not out:
        raise SystemExit(f"{path}: no symbols parsed")
    return out


PLAYER_CONTROLLER_OBJ = "src/battle_controller_player.o"


def text_span(map_path: pathlib.Path, obj: str) -> tuple[int, int]:
    """The [start, end) of obj's .text in a pret linker map."""
    for line in map_path.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) == 4 and parts[0] == ".text" and parts[3] == obj:
            start = int(parts[1], 16)
            return start, start + int(parts[2], 16)
    raise SystemExit(f"{map_path}: no .text for {obj}")


# E1-CHECKPOINT: pret publishes no pokeemerald.map (data/gen3/pret/pokeemerald_provenance.json
# "map"), so for a .sym without a .map the player controller's span is derived from the .sym.  The
# pret checkout is read at the provenance's pinned source commit (git show), never its work tree.
PRET_CACHE = next((p for p in (ROOT / ".cache" / "pret", pathlib.Path("E:/Google Drive/SLink/.cache/pret"))
                   if p.is_dir()), ROOT / ".cache" / "pret")
PLAYER_CONTROLLER_SRC = "src/battle_controller_player.c"
C_FUNCTION = re.compile(r"^[A-Za-z_][\w\s*]*?\b(\w+)\s*\(")


def pret_repo(sym_file: str) -> pathlib.Path:
    return PRET_CACHE / pathlib.Path(sym_file).stem


def pret_commit(sym_file: str) -> str:
    prov = SYM_DIR / sym_file.replace(".sym", "_provenance.json")
    return json.loads(prov.read_text(encoding="utf-8"))["origin"]["source_commit"]


def player_controller_functions(sym_file: str) -> list[str]:
    """Every function src/battle_controller_player.c defines, at the .sym's pinned pret commit.

    pret style: a definition is a column-0 line ending in `)` whose next line is `{` (prototypes end
    in `;`, table initialisers in `=`)."""
    repo, commit = pret_repo(sym_file), pret_commit(sym_file)
    try:
        text = subprocess.run(["git", "-C", str(repo), "show", f"{commit}:{PLAYER_CONTROLLER_SRC}"],
                              capture_output=True, check=True, encoding="utf-8").stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"{sym_file}: cannot read {PLAYER_CONTROLLER_SRC} @ {commit} from {repo}: {exc}") from exc
    lines = text.splitlines()
    names = [m.group(1) for line, nxt in zip(lines, lines[1:], strict=False)
             if nxt == "{" and line.rstrip().endswith(")") and (m := C_FUNCTION.match(line))]
    if not names:
        raise SystemExit(f"{PLAYER_CONTROLLER_SRC} @ {commit}: no function definitions parsed")
    return names


def sym_text_span(sym_path: pathlib.Path, names) -> tuple[int, int]:
    """The [start, end) of one object's .text from a pret .sym, by its explicit function list.

    Membership is the name list; the proof is structural: exactly one run of consecutive .sym
    symbols is made of exactly those names (so a duplicate static spelling in another controller
    is never inside it and no foreign symbol is), every gap in the run is alignment (< 4 bytes),
    and the run starts on a `.gcc2_compiled.` object marker and ends within alignment of the next
    one, with no marker inside."""
    want = set(names)
    rows: list[tuple[int, int, str]] = []
    markers: set[int] = set()
    for line in sym_path.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) == 4 and parts[1] in ("l", "g"):
            if parts[3] == ".gcc2_compiled.":
                markers.add(int(parts[0], 16))
            else:
                rows.append((int(parts[0], 16), int(parts[2], 16), parts[3]))
    runs, start = [], None
    for i, row in enumerate([*rows, (0, 0, "")]):
        if row[2] in want and start is None:
            start = i
        elif row[2] not in want and start is not None:
            runs.append((start, i))
            start = None
    hits = [(a, b) for a, b in runs if b - a == len(want) and {r[2] for r in rows[a:b]} == want]
    if len(hits) != 1:
        raise SystemExit(f"{sym_path.name}: {len(hits)} runs are exactly the {len(want)} names, need 1")
    a, b = hits[0]
    run = rows[a:b]
    lo, hi = run[0][0], run[-1][0] + run[-1][1]
    for (addr, size, _), (nxt, _, name) in zip(run, run[1:], strict=False):
        if not 0 <= nxt - (addr + size) < 4:
            raise SystemExit(f"{sym_path.name}: span not contiguous before {name} @ {nxt:#010x}")
    after = rows[b][0] if b < len(rows) else None
    if lo not in markers or after not in markers or not 0 <= after - hi < 4 \
            or any(lo < m < hi for m in markers):
        raise SystemExit(f"{sym_path.name}: [{lo:#010x}, {hi:#010x}) is not one object between "
                         f".gcc2_compiled. markers")
    return lo, hi


def player_span(sym_file: str) -> tuple[int, int]:
    """The player controller's .text: from the .map when pret ships one, else from the .sym."""
    map_path = SYM_DIR / sym_file.replace(".sym", ".map")
    if map_path.exists():
        return text_span(map_path, PLAYER_CONTROLLER_OBJ)
    return sym_text_span(SYM_DIR / sym_file, player_controller_functions(sym_file))


def span_source(sym_file: str) -> str:
    lo, hi = player_span(sym_file)
    if (SYM_DIR / sym_file.replace(".sym", ".map")).exists():
        return f"{PLAYER_CONTROLLER_OBJ} .text [0x{lo:08X}, 0x{hi:08X}) from the .map"
    return (f"{PLAYER_CONTROLLER_OBJ} .text [0x{lo:08X}, 0x{hi:08X}) sym-derived (no .map): the "
            f"{len(player_controller_functions(sym_file))} functions pret {pret_commit(sym_file)[:8]} "
            f"{PLAYER_CONTROLLER_SRC} defines, one contiguous .sym run, no foreign symbol, "
            f".gcc2_compiled. at both ends")


def title_syms(title: str, sym_file: str) -> dict[str, tuple[int, int]]:
    """parse_sym + the title's RENAMES (the FR spelling resolves to the title's own symbol)."""
    syms = parse_sym(SYM_DIR / sym_file)
    for fr_name, name in RENAMES.get(title, {}).items():
        if fr_name in syms:
            raise SystemExit(f"{title}: {fr_name} is itself in {sym_file}; the rename to {name} is stale")
        if name not in syms:
            raise SystemExit(f"{title}: rename {fr_name} -> {name}, but {name} is not in {sym_file}")
        syms[fr_name] = syms[name]
    return syms


def load_rom(pack: str, title: str, kind: str) -> bytes:
    path, sha1 = ROMS[(pack, title, kind)]
    if not path.exists():
        raise SystemExit(f"ROM not present at {path}")
    rom = path.read_bytes()
    if hashlib.sha1(rom).hexdigest() != sha1:
        raise SystemExit(f"{path}: sha1 differs from the pinned dump")
    return rom


def body(rom: bytes, address: int, length: int) -> bytes:
    off = address - ROM_BASE
    if off < 0 or off + length > len(rom):
        raise SystemExit(f"{address:#010x}+{length} is outside the ROM")
    return rom[off:off + length]


def pool_offsets(blob: bytes, word: int) -> list[int]:
    """Word-aligned offsets inside blob whose little-endian u32 equals word."""
    return [i for i in range(0, len(blob) - 3, 4) if struct.unpack_from("<I", blob, i)[0] == word]


def verify_code(syms, roms: dict[str, bytes], name: str) -> bool:
    """The FR body of `name` is byte-identical at the same address in every RR ROM."""
    addr, size = syms[name]
    if not size:
        raise SystemExit(f"{name}: zero-size symbol cannot be byte-verified")
    want = body(roms["_fr"], addr, size)
    return all(body(rom, addr, size) == want for key, rom in roms.items() if key != "_fr")


def verify_data(syms, roms: dict[str, bytes], name: str) -> bool:
    """The literal-pool words that pin `name` inside its witness are unchanged in every RR ROM."""
    witness = WITNESS.get(name)
    if witness is None:
        return False
    waddr, wsize = syms[witness]
    fr = body(roms["_fr"], waddr, wsize)
    offs = pool_offsets(fr, syms[name][0])
    if not offs:
        raise SystemExit(f"{name} is not in {witness}'s literal pool -- witness table is wrong")
    return all(all(body(rom, waddr + o, 4) == fr[o:o + 4] for o in offs)
               for key, rom in roms.items() if key != "_fr")


def setter_pairs(address: int, code: bytes, rom: bytes) -> list[tuple[int, int]]:
    """[(pointer variable, &object)] for every store in a SetSaveBlocksPointers body.

    Only the three instruction forms this body uses are decoded -- the Thumb short literal load
    (`ldr rN,[pc,#imm8]`), the three-register add (`adds rD,rA,rB`) and the zero-offset short
    store (`str rM,[rN]`) -- and a 32-bit `bl` is stepped over whole.  The caller
    signature-checks the body first, so an unrecognised form cannot quietly mis-pair; a store
    whose registers do not resolve to two pool words is dropped, and the caller requires all
    three pairs to be present.
    """
    reg: dict[int, int] = {}            # register -> the literal word it carries
    out: list[tuple[int, int]] = []
    at = 0
    while at + 1 < len(code):
        op = int.from_bytes(code[at:at + 2], "little")
        if op & 0xF800 == 0xF000:                                   # first half of a 32-bit bl
            at += 4
            continue
        if 0x4800 <= op <= 0x4FFF:                                  # ldr rN,[pc,#imm8*4]
            n, imm = (op >> 8) & 7, (op & 0xFF) * 4
            word_at = ((address + at + 4) & ~3) + imm
            reg[n] = struct.unpack_from("<I", rom, word_at - ROM_BASE)[0]
        elif op & 0xF800 == 0x1800:                                 # adds rD,rA,rB
            d, a, b = op & 7, op >> 3 & 7, op >> 6 & 7
            if a in reg:
                reg[d] = reg[a]
            elif b in reg:
                reg[d] = reg[b]
            else:
                reg.pop(d, None)
        elif op & 0xF800 == 0x6000 and ((op >> 6) & 0x1F) == 0:      # str rM,[rN]
            n, m = (op >> 3) & 7, op & 7
            if n in reg and m in reg:
                out.append((reg[n], reg[m]))
        at += 2
    return out


def rr_saveblock_pointers(syms: dict[str, tuple[int, int]], rom: bytes) -> dict[str, int]:
    """{gSaveBlock*Ptr: IWRAM address} for RR, read out of the setter's literal pool.

    Named SystemExit -- never a guess -- when the ROM is not the pinned RR build: the setter's
    address comes from the pret .sym, so a build that moved or reshaped it, or that restored the
    relocation mask, invalidates every pointer address this pack names and has to be re-pinned
    by hand.
    """
    address, _size = syms[SETTER_SYMBOL]
    code = body(rom, address, SETTER_BODY)
    if code[:len(SETTER_PREFIX)] != SETTER_PREFIX:
        raise SystemExit(
            f"rr_saveblock_pointers: {SETTER_SYMBOL} at {address:#010x} is not the pinned body "
            f"(got {code[:len(SETTER_PREFIX)].hex()}, expected {SETTER_PREFIX.hex()}); the RR "
            f"save-block pointers must be re-pinned before regenerating")
    offset = code[SETTER_OFFSET_AT:SETTER_OFFSET_AT + 4]
    if offset != SETTER_OFFSET_BYTES:
        raise SystemExit(
            f"rr_saveblock_pointers: {SETTER_SYMBOL} at {address:#010x} no longer fixes the "
            f"save-block offset to 0 at +{SETTER_OFFSET_AT:#x} (got {offset.hex()}, expected "
            f"{SETTER_OFFSET_BYTES.hex()}): the pointer values would relocate on every battle "
            f"start and map load, and the legacy 0x03003840 alias would not follow them")
    out: dict[str, int] = {}
    for variable, base in setter_pairs(address, code, rom):
        name = SAVEBLOCK_BASES.get(base)
        if name is None or not IWRAM_RANGE[0] <= variable < IWRAM_RANGE[1]:
            raise SystemExit(
                f"rr_saveblock_pointers: {SETTER_SYMBOL} at {address:#010x} stores "
                f"{variable:#010x} <- {base:#010x}, which is not a save-block pointer")
        out[name] = variable
    missing = [name for name in SAVEBLOCK_POINTERS if name not in out]
    if missing:
        raise SystemExit(
            f"rr_saveblock_pointers: {SETTER_SYMBOL} at {address:#010x} yielded {sorted(out)}; "
            f"the setter no longer names {missing}")
    return out


def build_title(pack: str, title: str, sym_file: str, kinds: tuple[str, ...]) -> tuple[dict, list[str]]:
    syms = title_syms(title, sym_file)
    roms = {kind: load_rom(pack, title, kind) for kind in kinds}
    is_rr = pack == "gen3_rr"
    unverified: list[str] = []
    if is_rr:
        # every RR fact is proven against the RR binaries, with FireRed as the reference body
        roms["_fr"] = load_rom("gen3_frlg", "firered", "clean")

    def ok_code(name: str) -> bool:
        if not is_rr or verify_code(syms, roms, name):
            return True
        unverified.append(f"code {name} @ {syms[name][0]:#010x}")
        return False

    def ok_data(name: str) -> bool:
        if not is_rr or verify_data(syms, roms, name):
            return True
        unverified.append(f"data {name} @ {syms[name][0]:#010x}")
        return False

    anchors = {}
    for key, (symbol, offset, length) in {**ANCHORS, **TITLE_ANCHORS.get(title, {})}.items():
        addr, size = syms[symbol]
        length = size if length is None else length
        # frame_control is the companion's own hook slot: its bytes differ per build, so the
        # symbol is proven through gMain's pool word instead of a whole-body comparison.
        proven = ok_data("gMain") if key == "frame_control" else ok_code(symbol)
        if not proven:
            continue
        anchors[key] = {
            "symbol": symbol, "address": addr, "rom_offset": addr - ROM_BASE + offset,
            "length": length,
            "expected_hex": {kind: body(rom, addr + offset, length).hex().upper()
                             for kind, rom in roms.items() if kind != "_fr"},
        }

    predicates, witnesses = {}, {}
    for key, (symbol, offset, width, mask, expect) in [*PREDICATES.items(), *WITNESSES.items()]:
        if not ok_data(symbol) or not all(ok_code(fn) for fn in PREDICATE_CODE.get(key, ())):
            continue
        entry = {"symbol": RENAMES.get(title, {}).get(symbol, symbol), "address": syms[symbol][0],
                 "offset": offset, "width": width}
        if mask is not None:
            entry["mask"] = mask
        if isinstance(expect, str):
            if not ok_code(expect):
                continue
            entry["expect_symbol"] = expect
            entry["expect"] = syms[expect][0] | 1  # Thumb pointer, as gMain stores it
        else:
            entry["expect"] = expect
        (witnesses if key in WITNESSES else predicates)[key] = entry

    allowed = {}
    for name in ALLOWED_TASKS + TITLE_TASKS.get(title, ()):
        if name not in syms:
            raise SystemExit(f"{title}: allowed task {name} is not in {sym_file}")
        if ok_code(name):
            allowed[name] = syms[name][0]

    out = {
        "version": VERSION,
        # G5-CPU-HARDEN: safety.lua honours cpu.irq_entry only on the pack titled radical_red
        "title": title,
        "sym": sym_file,
        "anchors": anchors,
        "predicates": predicates,
        "witnesses": witnesses,
        "tasks": {"symbol": "gTasks", "struct_size": TASK_STRUCT_SIZE, "count": TASK_COUNT,
                  "func_offset": 0, "is_active_offset": 4,
                  "allowed_overworld_tasks": allowed,
                  "source": TASKS_SOURCE.get(title, ALLOWED_TASKS_SOURCE)},
        "cpu": cpu_clause(title, syms, is_rr),
        "pointers": {},
    }
    if title in TASKS_EXCLUDED:
        out["tasks"]["excluded_tasks"] = TASKS_EXCLUDED[title]
    if title in FORBIDDEN_INVENTORY:
        out["tasks"]["forbidden_inventory"] = forbidden_inventory(title, syms)
    if ok_data("gTasks"):
        out["tasks"]["address"] = syms["gTasks"][0]
    else:  # fail-closed: no task base, no allow-list
        out["tasks"]["allowed_overworld_tasks"] = {}

    profile = json.loads((ROOT / "data" / "games" / pack / "profile.json").read_text("utf-8"))
    span = span_source(sym_file) if title in TITLE_SOURCES else ""
    out["battle"], battle_dropped = battle_block(title, syms, is_rr, profile, roms, span)
    if battle_dropped:  # REV-C5-RR-BW-FIX 1: a partial clause set is a weaker permit, not a closed one
        raise SystemExit(f"{title}: battle clause(s) unproven, no battle block emitted: "
                         + "; ".join(battle_dropped))
    if not is_rr:  # several HandleInputChooseAction spellings; parse_sym must have kept the player's
        lo, hi = player_span(sym_file)
        if not lo <= syms["HandleInputChooseAction"][0] < hi:
            raise SystemExit(f"{title}: HandleInputChooseAction is not {PLAYER_CONTROLLER_OBJ}'s")
    slot = next(c["address"] for c in out["battle"]["clauses"] if c["name"] == "battle_input_controller")
    handoff, why = handoff_block(syms, sym_file, is_rr, roms, slot, profile["titles"][title], title)
    if is_rr:
        # F1 M5 / G5-CPU-HARDEN: structural, not gated on commit_hold. RR Explode's behaviour flips on
        # this shape, so every RR build proves the hand-off AND move 153's effect + PP in every RR
        # ROM, or it stops -- never a quiet drop to `unverified`.
        if handoff is None:
            raise SystemExit(f"{title}: battle.handoff (RR, carries Explode+H) unproven: {why}")
        explode, why = explode_head(profile["titles"][title], roms)
        if explode is None:
            raise SystemExit(f"{title}: battle.handoff.explode (RR Explode+H) unproven: {why}")
        handoff["explode"] = explode
    elif handoff is None:
        unverified.append(f"battle.handoff: {why}")
    if handoff is not None:
        out["battle"]["handoff"] = handoff
    if is_rr:
        native = native_block(profile)
        if native is not None:
            out["native"] = native
    out["sound"] = sound_block(syms, is_rr, title)
    out["sound"]["se_ids"] = se_ids(title, profile["titles"][title]["rom"]["SE_SONG_HEADERS"])
    out["gift_areas"] = gift_areas(pack, title)

    if is_rr:
        ram = profile["titles"][title]["ram"]
        # Card C3-33: the three pointers come out of the ROM's own setter, not out of the old
        # client's legacy profile (whose 0x03003840/0x03003838 are literal-pool constants inside
        # IntrMain_Buffer).  Both RR artifacts must agree -- the companion patch is additive.
        derived = rr_saveblock_pointers(syms, roms["clean"])
        for kind, rom in roms.items():
            if kind != "_fr" and rr_saveblock_pointers(syms, rom) != derived:
                raise SystemExit(f"{title}/{kind}: the save-block pointers differ from the clean ROM")
        for name in SAVEBLOCK_POINTERS:
            out["pointers"][name] = {"address": derived[name], "source": POOL_SOURCE}
        # RR (CFRU) keeps box storage in a fixed EWRAM struct as well as behind the pointer; the
        # struct base stays a separate fact for the reads layer's cross-check.
        if ram.get("POKEMON_STORAGE_BASE") is not None:
            out["pointers"]["pokemon_storage_base"] = {
                "address": ram["POKEMON_STORAGE_BASE"], "source": "profile.ram.POKEMON_STORAGE_BASE"}
        # The setter itself, byte-pinned per artifact.  safety.lua re-reads every anchor's bytes
        # from the running ROM, so a build that moved the setter -- or that restored the
        # relocation mask -- is refused at runtime as well as here.
        setter_addr, setter_size = syms[SETTER_SYMBOL]
        out["anchors"]["saveblocks_setter"] = {
            "symbol": SETTER_SYMBOL, "address": setter_addr,
            "rom_offset": setter_addr - ROM_BASE, "length": setter_size,
            "expected_hex": {kind: body(rom, setter_addr, setter_size).hex().upper()
                             for kind, rom in roms.items() if kind != "_fr"},
        }
    else:
        for name in ("gSaveBlock1Ptr", "gSaveBlock2Ptr", "gPokemonStoragePtr"):
            out["pointers"][name] = {"symbol": name, "address": syms[name][0], "source": sym_file}
    return out, unverified


# ── C4-B2: the battle / native / sound blocks ────────────────────────────────────────────────
# The overworld block above stays the G3-signed predicate.  These are the *additional* reason
# sets the design (docs/gen3/research/battle_write_predicate.md) specifies.  Every emitted value
# carries a source: FR/LG from the title's own .sym, RR from RR-PROD facts only (the profile's
# ram keys and the old client's constants) -- a FireRed sym address is never asserted for RR.
#
# compare semantics (safety.lua evaluates them):
#   eq       value == expect                (mask applied first when given)
#   eq_symbol  the symbol's address | 1     (a Thumb function pointer, as gMain stores them)
#   nonzero  value ~= 0
#   lt       value <  value_field           (the commit guard; indexed by args.battler)

# C4-BW: the input wait is NOT exec-idle. STATE_BEFORE_ACTION_CHOSEN emits CHOOSE_ACTION and
# MarkBattlerForControllerExec(0) sets bit 0 (pret battle_main.c:3133-3135, battle_util.c:185-191);
# only PlayerBufferExecCompleted clears it, once the player has CHOSEN (battle_controller_player.c
# :186-200). "flags == 0" admitted only the frame after a committed choice -- the choice already in
# gBattleBufferB, possibly a SWITCH into the mon being zeroed -- and never the parked menu (live
# linked_faint_active_gen3 r3, 123c6c45: a bench force_faint held 99 s on this clause).
# The window is the parked menu itself: exactly battler 0's input exec pending (the opponent AI
# completes inside its own frame; in doubles battler 2 is only asked after battler 0 reaches
# STATE_WAIT_ACTION_CONFIRMED, battle_main.c:3110-3113, so flags == 1 is battler 0's menu only), and
# battler 0's controller is the PLAYER's HandleInputChooseAction. That pin also refuses the
# HandleChooseActionAfterDma3 draw frames, the move/target submenus, the bag and party menus, and
# the Safari / Oak-old-man / Pokedude controllers (Teachy TV swaps gPlayerParty: teachy_tv.c:1178).
# F-B (card E2-FIX-AB): STATE_WAIT_ACTION_CHOSEN and STATE_WAIT_ACTION_CONFIRMED_STANDBY, BY
# NAME, in each vanilla title's own src/battle_main.c enum -- battle_comm_0's expect and
# commit_guard's value are that enum's indices, not a bare literal that happens to be right for
# one title. FR/LG's enum starts at STATE_BEFORE_ACTION_CHOSEN (index 0): WAIT_ACTION_CHOSEN = 1,
# WAIT_ACTION_CONFIRMED_STANDBY = 3 (pret pokefirered c75f3523 src/battle_main.c:3086-3092; also
# docs/gen3/research/battle_write_predicate.md:61-63,237). Emerald's enum has one extra leading
# member, STATE_TURN_START_RECORD, so every later state's index is +1: WAIT_ACTION_CHOSEN = 2,
# WAIT_ACTION_CONFIRMED_STANDBY = 4 (pret pokeemerald c65e93f2 src/battle_main.c:4116-4124).
# Physically, gBattleCommunication[0] reads 2 at Emerald's parked action menu, not FR/LG's 1.
#
# A per-title constant, not a live re-derive from the pret checkout at generation time: FR/LG's
# own build provenance (data/gen3/pret/provenance.json: {"source": {"commit": ...}}) and
# Emerald's (pokeemerald_provenance.json: {"origin": {"source_commit": ...}}) don't share a JSON
# shape, and the enum is fixed source text that only changes together with a title's own .sym --
# re-deriving it live at generation time would not catch anything the citation above doesn't
# already pin. RR is untouched: it has no pret and keeps its own ROM-pinned expect
# (BATTLE_CLAUSES_RR / BATTLE_COMMIT_GUARD_RR), never routed through this table.
BATTLE_COMM_STATES_FRLG = {"WAIT_ACTION_CHOSEN": 1, "WAIT_ACTION_CONFIRMED_STANDBY": 3}
BATTLE_COMM_STATES = {"emerald": {"WAIT_ACTION_CHOSEN": 2, "WAIT_ACTION_CONFIRMED_STANDBY": 4}}
BATTLE_CLAUSES_FRLG = (
    ("battle_main_func", "gBattleMainFunc", 0, 4, None, "eq_symbol", "HandleTurnActionSelectionState"),
    ("battle_comm_0", "gBattleCommunication", 0, 1, None, "eq", 1),
    ("battle_exec_flags_input", "gBattleControllerExecFlags", 0, 4, None, "eq", 1),
    ("battle_input_controller", "gBattlerControllerFuncs", 0, 4, None, "eq_symbol", "HandleInputChooseAction"),
    ("battle_not_link", "gBattleTypeFlags", 0, 4, 0x02, "eq", 0),
    ("battle_engine_loaded", "gBattleMons", 0x2C, 2, None, "nonzero", None),
    ("battle_outcome_open", "gBattleOutcome", 0, 1, None, "eq", 0),
)
BATTLE_CLAUSES_RR = (
    # (name, profile.ram key, offset, width, mask, compare, expect)
    # The expect for battle_main_func is a ROM pin, not a FireRed sym value: CFRU's
    # HandleTurnActionSelectionState is byte-anchored at 0x08014041 (profile.rom
    # HANDLE_TURN_ACTION_SELECTION_ADDR; the expanded code at file 0x1070626/28 loads the pools
    # 0x03004F84 / 0x08014041 and stores the callback).  Read, never retyped.
    ("battle_main_func", "BATTLE_MAIN_FUNC_ADDR", 0, 4, None, "eq_rom", "HANDLE_TURN_ACTION_SELECTION_ADDR"),
    ("battle_comm_0", "BATTLE_COMM_ADDR", 0, 1, None, "eq", 1),
    # C5-RR-BW (docs/gen3/research/rr_battle_tuple_2026-09-23.md §1): CFRU's input handler keeps
    # battler 0's exec bit set for the whole parked menu and clears it (PlayerBufferExecCompleted)
    # in the same call that commits the choice -- so the FR/LG C4-BW shape, flags == 1.
    ("battle_exec_flags_input", "BATTLE_CONTROLLER_EXEC_FLAGS_ADDR", 0, 4, None, "eq", 1),
    ("battle_input_controller", None, 0, 4, None, "eq", None),   # rr_input_controller()
    ("battle_not_link", "BATTLE_TYPE_ADDR", 0, 4, 0x02, "eq", 0),
    ("battle_engine_loaded", "BATTLE_MONS_ADDR", 0x2C, 2, None, "nonzero", None),
    ("battle_outcome_open", "BATTLE_OUTCOME_ADDR", 0, 1, None, "eq", 0),
)
# Both RR callback and controller-exec word are now ROM-pinned in profile.json.
BATTLE_DROPPED_RR = ()
# C5-RR-BW: the parked controller pin, read out of the RR bytes.  HandleChooseActionAfterDma3 is
# the FR body RR keeps verbatim (pool included) and the one store of the parked pointer:
# `ldr r1,=gBattlerControllerFuncs` at +0x18 (0x08032BAC), `ldr r1,=<controller>` at +0x22
# (0x08032BB6), str.  CFRU detours 0x0802E438 to its own body, so the pin is that ROM literal,
# never `eq_symbol HandleInputChooseAction` (whose RR body differs).  Any byte change -- pool word
# included -- drops the clause and lists it as unverified.
RR_INPUT_CONTROLLER = ("HandleChooseActionAfterDma3", 0x18, 0x22)
# REV-C5-RR-BW-FIX 2: RR HOLDS battle_commit (safety.lua refuses it by this reason).  The commit
# writes gBattleCommunication[b] = 3 while CFRU's parked controller is still battler 0's, and an L
# press then runs its ball shortcut -- RemoveBagItem at 0x090AA114 -- before the engine takes the
# coerced action (docs/gen3/research/rr_battle_tuple_2026-09-23.md §1 e).  FR/LG's parked handler
# has no side effect.  Drop this only with a proven controller-handoff design (G5).
# G4-PH: the hold stays in the pack; safety.lua replaces it by the battle_commit_handoff clause
# only for a plan that ends in the exact battle.handoff tail (mechanism P), so Explode stays held.
RR_COMMIT_HOLD = ("battle_commit held on RR: CFRU's parked controller stays live after the commit "
                  "(L-throw RemoveBagItem 0x090AA114) unless the plan ends in the battle.handoff tail")
BATTLE_COMMIT_GUARD = {"symbol": "gBattleCommunication", "offset": 0, "width": 1, "compare": "lt",
                       "value": 3, "indexed_by": "battler"}
BATTLE_COMMIT_GUARD_RR = {"symbol": "BATTLE_COMM_ADDR", "offset": 0, "width": 1, "compare": "lt",
                          "value": 3, "indexed_by": "battler"}
BATTLE_SOURCE_FRLG = "pokefirered.sym/pokeleafgreen.sym (data address); pret src/battle_main.c"
BATTLE_SOURCE_RR = "profile.ram.%s (old client production path)"
# title -> {block: source} for a sym-sourced title other than FR/LG.  E1-CHECKPOINT Emerald, pret/
# pokeemerald c65e93f2: C4-BW holds as in FR -- STATE_BEFORE_ACTION_CHOSEN emits CHOOSE_ACTION
# (src/battle_main.c:4143-4168) and MarkBattlerForControllerExec sets the bit (src/battle_util.c:
# 856-862); only PlayerBufferExecCompleted clears it (src/battle_controller_player.c:200-214), and
# HandleChooseActionAfterDma3 parks the slot on HandleInputChooseAction (:2565-2571).
# BATTLE_TYPE_LINK = (1 << 1) (include/constants/battle.h:60); gBattleMons +0x2C is
# BattlePokemon.maxHP (include/pokemon.h:260-295, the FR layout and offset).
TITLE_SOURCES = {"emerald": {
    "battle": ("pokeemerald.sym (data address); pret pokeemerald c65e93f2 src/battle_main.c:4129-4168, "
               "src/battle_util.c:856-862, src/battle_controller_player.c:200-214,2565-2571, "
               "include/constants/battle.h:60, include/pokemon.h:260-295; "),
    "handoff": "pret pokeemerald c65e93f2 src/battle_controller_player.c:200-214,216",
    "sound": ("pokeemerald.sym; pret pokeemerald c65e93f2 include/gba/m4a_internal.h:185-221 (SoundInfo "
              "+0x24 musicPlayerHead), :272-315 (MusicPlayerTrack), :327-350 (MusicPlayerInfo, +0x3C "
              "musicPlayerNext): the FR offsets"),
}}

# The companion arena, from profile.native (addresses) + patch/src/ADDRESSES.md:59-77 (sizes).
# safety.lua checks every native write lands inside one of these spans.
NATIVE_ARENA = (
    ("BASE", 64, "mailbox ABI v1"),
    ("SW", 8, "SwapState"),
    ("GH", 44, "GhostState"),
    ("CALC_OFF", 1, "SLINK_CALC_OFF"),
    ("TEXT_BUF", 256, "SLINK_TEXT_BUF"),
    ("BLOB_BUF", 600, "SLINK_BLOB_BUF"),
    ("MENU_BUF", 112, "SLINK_MENU_BUF"),
    ("BATTLE_NOTIF", 8, "BattleNotif"),
    ("GHOST_PAL_BUF", 32, "GHOST_PAL_BUF"),
    ("EVR", 52, "EvRing"),
    ("INFO", 264, "SlinkInfo"),
)
NATIVE_LAYOUT = {"opcode_off": 6, "status_off": 10, "busy": 1, "abi_off": 4,
                 "info_drawn_off": 1, "info_ack_off": 2}
NATIVE_SOURCE = "profile.native + patch/src/ADDRESSES.md:59-77"

# m4a: the exact fields the old client's M.playSE pokes (archive/gen3-old-client:lua/memory_gba.lua:2003-2055).  The
# clause set is {the driver is up (ident magic), the player/track are in IWRAM}; no save or
# transition clause is needed -- a Lua write lands between frames, so the engine cannot observe a
# half-written player, and the ISR skips a player whose ident is the lock value by design
# (pret include/gba/m4a_internal.h:185-188, src/m4a.c:50-66,209-215).
SOUND_FIELDS = (
    ("songHeader", 0x00, 4), ("status", 0x04, 4), ("trackCount", 0x08, 1),
    ("priority", 0x09, 1), ("clock", 0x0C, 4), ("tracks", 0x2C, 4), ("ident", 0x34, 4),
    ("flags", 0x00, 4, "track"), ("bendRange", 0x0F, 1, "track"), ("volX", 0x13, 1, "track"),
    ("lfoSpeed", 0x19, 1, "track"), ("chan", 0x20, 4, "track"), ("cmdPtr", 0x40, 4, "track"),
)
SOUND_CONSTANTS = {"sound_info_ptr": "SOUND_INFO_PTR", "sound_info": "gSoundInfo",
                   "player_se1": "gMPlayInfo_SE1", "ident_magic": 0x68736D53,
                   "player_head_off": 0x24, "player_next_off": 0x3C,
                   "iwram_min": 0x03000000, "iwram_max": 0x03008000}
SOUND_SOURCE_FRLG = "pokefirered.sym/pokeleafgreen.sym; pret include/gba/m4a_internal.h"
SOUND_SOURCE_RR = "old client archive/gen3-old-client:lua/memory_gba.lua:1945-1996 (SOUND_INFO_PTR + the linked-list walk)"


# E3-CLIENT: play_sound ids on the wire keep FR/LG numbering (a protocol constant: server/state.py
# and lua/core/session.lua:301; docs/protocol.md "play_sound ids"). se_ids maps a wire id to THIS
# title's song id before the SE_SONG_HEADERS lookup; the client refuses an id the map lacks.
# FR/LG/RR: the identity over the title's own SE_SONG_HEADERS keys (today's behaviour).
# Emerald: SE_FAINT 16, SE_FLEE 17, SE_BOO 22, SE_SUCCESS 31, SE_FAILURE 32, SE_SHINY 102
# (pret pokeemerald c65e93f2 include/constants/songs.h:22,23,28,37,38,108) against FR's
# 16/17/22/25/26/95 (pret pokefirered c75f3523 include/constants/songs.h:20,21,26,29,30,99).
SE_WIRE_IDS = {"emerald": {16: 16, 17: 17, 22: 22, 25: 31, 26: 32, 95: 102}}


def se_ids(title: str, headers: dict) -> dict:
    wire = SE_WIRE_IDS.get(title) or {int(k): int(k) for k in headers}
    for w, t in wire.items():
        if str(t) not in headers:
            raise SystemExit(f"{title}: wire SE {w} maps to {t}, which has no SE_SONG_HEADERS entry")
    return {str(w): t for w, t in sorted(wire.items())}


# E3-CLIENT: area ids where a mon is handed over rather than caught, so the client shows no NEW
# ENCOUNTER banner and sends no no_catch there. FR/LG/RR emit area ids from the shared FRLG area map
# and keep server/adapters/gen3_frlge.py _GIFT_AREAS verbatim (today's client literal).
# Emerald (E3-GIFTLINK): gen_area_map.py names every statics.json gift map (its location name,
# never a wild id), so the ids are the gift rows' areas. The exception is the starter: it is chosen
# on wild route_101 before the player has balls, and listing that route would exempt it from no_catch
# for good. A gift row off the area map, or a stale wild exception, fails the build.
# Any other pack has no rule: SystemExit, never a Kanto default.
GIFT_AREAS_FRLG = ["celadon_condominiums", "cinnabar_lab", "gift", "intro", "oaks_lab",
                   "route_4_pokecenter", "saffron_dojo", "silph_co_7f"]
KANTO_GIFT_PACKS = ("gen3_frlg", "gen3_rr")
GIFT_KINDS = ("gift", "choice_gift", "fixed_gift")
GIFT_WILD_ROUTES = {"emerald": {"route_101"}}


def gift_areas(pack: str, title: str) -> dict:
    if pack in KANTO_GIFT_PACKS:
        return {"ids": GIFT_AREAS_FRLG, "source": "server/adapters/gen3_frlge.py _GIFT_AREAS"}
    if pack != "gen3_emerald":
        raise SystemExit(f"{pack}/{title}: no gift_areas rule; add the pack to gift_areas()")
    base = ROOT / "data" / "games" / pack
    area_map = json.loads((base / "area_map.json").read_text("utf-8"))
    rows = [r for r in json.loads((base / "statics.json").read_text("utf-8"))["entries"]
            if r["kind"] in GIFT_KINDS]
    unmapped = [r["id"] for r in rows if r["map"] not in area_map]
    if unmapped:
        raise SystemExit(f"{title}: gift rows {unmapped} have no area; run gen_area_map.py --game emerald")
    mapped, wild = {area_map[r["map"]] for r in rows}, GIFT_WILD_ROUTES[title]
    if not wild <= mapped:
        raise SystemExit(f"{title}: no gift row maps to {sorted(wild - mapped)}; update GIFT_WILD_ROUTES")
    return {"ids": sorted(mapped - wild),
            "source": f"{pack}/statics.json gift rows x area_map.json, less the starter's wild route_101"}


def ldr_literal(rom: bytes, site: int) -> int | None:
    """The word a Thumb `ldr rN,[pc,#imm8*4]` at site loads, else None."""
    op = int.from_bytes(body(rom, site, 2), "little")
    if op & 0xF800 != 0x4800:
        return None
    return struct.unpack_from("<I", body(rom, ((site + 4) & ~3) + (op & 0xFF) * 4, 4))[0]


def rr_input_controller(syms, roms: dict[str, bytes] | None) -> tuple[dict | None, str]:
    """(the battle_input_controller clause, "") from the RR pool, or (None, why it is unproven)."""
    fn, addr_at, value_at = RR_INPUT_CONTROLLER
    if not roms or "_fr" not in roms or fn not in syms:
        return None, "no RR ROMs to prove it against"
    lo, hi = text_span(SYM_DIR / "pokefirered.map", PLAYER_CONTROLLER_OBJ)
    if not lo <= syms[fn][0] < hi:  # parse_sym keeps the first spelling; it must be the player's
        return None, f"{fn} @ {syms[fn][0]:#010x} is not {PLAYER_CONTROLLER_OBJ}'s"
    if not verify_code(syms, roms, fn):
        return None, f"{fn} @ {syms[fn][0]:#010x} differs from FR in an RR ROM"
    start = syms[fn][0]
    rom = roms["clean"]
    address, value = ldr_literal(rom, start + addr_at), ldr_literal(rom, start + value_at)
    if address is None or value is None:
        return None, f"{fn}: no ldr at +{addr_at:#x}/+{value_at:#x}"
    return {"name": "battle_input_controller", "symbol": "gBattlerControllerFuncs",
            "address": address, "offset": 0, "width": 4, "compare": "eq", "expect": value,
            "source": f"rom:{fn} @ 0x{start:08X} (FR-identical in every RR ROM): address "
                      f"LDR@0x{start + addr_at:08X}, value LDR@0x{start + value_at:08X}"}, ""


def battle_block(title: str, syms, is_rr: bool, profile: dict | None,
                 roms: dict[str, bytes] | None = None, span: str = "") -> tuple[dict, list[str]]:
    dropped: list[str] = []
    clauses = []
    if is_rr:
        ram = (profile or {}).get("titles", {}).get(title, {}).get("ram", {})
        for name, key, offset, width, mask, compare, expect in BATTLE_CLAUSES_RR:
            if name == "battle_input_controller":
                entry, why = rr_input_controller(syms, roms)
                if entry is None:
                    dropped.append(f"{name}: {why}")
                else:
                    clauses.append(entry)
                continue
            if ram.get(key) is None:
                dropped.append(f"{name}: profile.ram.{key} absent")
                continue
            entry = {"name": name, "symbol": key, "address": ram[key], "offset": offset,
                     "width": width, "compare": compare,
                     "source": BATTLE_SOURCE_RR % key}
            if key == "BATTLE_CONTROLLER_EXEC_FLAGS_ADDR":
                entry["source"] = f"profile.ram.{key}; " + profile["titles"][title]["_src"][f"ram.{key}"]
            if mask is not None:
                entry["mask"] = mask
            if compare == "eq_rom":
                rom_key = expect
                value = (profile or {}).get("titles", {}).get(title, {}).get("rom", {}).get(rom_key)
                if value is None:
                    dropped.append(f"{name}: profile.rom.{rom_key} absent")
                    continue
                entry["expect_symbol"] = rom_key
                entry["expect"] = value
                entry["source"] = f"profile.ram.{key} + profile.rom.{rom_key} (CFRU code pin)"
            elif expect is not None:
                entry["expect"] = expect
            clauses.append(entry)
        guard = dict(BATTLE_COMMIT_GUARD_RR)
        guard["address"] = ram.get("BATTLE_COMM_ADDR")
        guard["source"] = BATTLE_SOURCE_RR % "BATTLE_COMM_ADDR"
        dropped += list(BATTLE_DROPPED_RR)
        hold = {"commit_hold": RR_COMMIT_HOLD}
    else:
        source = TITLE_SOURCES[title]["battle"] + span if title in TITLE_SOURCES else BATTLE_SOURCE_FRLG
        comm_states = BATTLE_COMM_STATES.get(title, BATTLE_COMM_STATES_FRLG)
        for name, symbol, offset, width, mask, compare, expect in BATTLE_CLAUSES_FRLG:
            entry = {"name": name, "symbol": symbol, "address": syms[symbol][0], "offset": offset,
                     "width": width, "compare": compare, "source": source}
            if mask is not None:
                entry["mask"] = mask
            if compare == "eq_symbol":
                entry["expect_symbol"] = expect
                entry["expect"] = syms[expect][0] | 1
            elif name == "battle_comm_0":
                # F-B: the index of STATE_WAIT_ACTION_CHOSEN in *this title's* enum, not FR/LG's.
                entry["expect"] = comm_states["WAIT_ACTION_CHOSEN"]
            elif expect is not None:
                entry["expect"] = expect
            clauses.append(entry)
        guard = dict(BATTLE_COMMIT_GUARD)
        guard["address"] = syms["gBattleCommunication"][0]
        guard["value"] = comm_states["WAIT_ACTION_CONFIRMED_STANDBY"]  # F-B: same by-name shift
        guard["source"] = source
        hold = {}
    return {"version": "gen3-battle-v1", "clauses": clauses, "commit_guard": guard, **hold}, dropped


# G4-PH (owner rulings 15-18, 2026-09-24; docs/gen3/research/rr_active_faint_parity_scope_2026-09-23.md
# §3.2, §5.1): mechanism P's plan ends by handing battler 0's controller slot to
# PlayerBufferExecCompleted, so the engine itself installs PlayerBufferRunCommand and clears the exec
# bit on the next BattleMainCB1 pass -- exactly how a real commit ends, with no A press. The slot is the
# battle_input_controller clause's word. FR/LG: the value is the player controller's .sym spelling,
# proven in the title's own ROM by the body's pool words (the slot array and PlayerBufferRunCommand|1,
# pret battle_controller_player.c:186-200). RR: the value is the word CFRU's action menu commits through
# (LDR@0x090A9EFE), equal in every RR ROM, equal to FR's symbol, and FR's slot-addressing prefix and
# pool are kept verbatim there (the body detours after it). Any failed check drops the block: FR/LG
# then keep the A press, RR keeps the commit hold (fail-closed).
HANDOFF_FN = "PlayerBufferExecCompleted"
RR_HANDOFF_VALUE_LDR = 0x090A9EFE
HANDOFF_PREFIX = 0x10        # push; gActiveBattler -> slot address (before RR's detour at +0x10)
HANDOFF_POOL = (0x40, 0x48)  # gBattlerControllerFuncs, gActiveBattler
# G4-PH-FIX1b (R1 L7): FR/LG's first 16 bytes of PlayerBufferExecCompleted, the pret build of
# src/battle_controller_player.c:186-188 at the .sym address (FR and LG identical):
#   push {r4,lr}; sub sp,#4; ldr r1,=gBattlerControllerFuncs; ldr r4,=gActiveBattler;
#   ldrb r0,[r4]; lsls r0,#2; adds r0,r0,r1; ldr r1,=PlayerBufferRunCommand
FRLG_HANDOFF_PREFIX = bytes.fromhex("10b581b00e490f4c2078800040180e49")


# R1 L1: the exact P head a hand-off plan must carry before [comm, hand-off] (battler 0), so the
# policy judges the whole plan, not just its tail. Every number comes from the pack's own profile
# (FR/LG: the title's .sym + pret; RR: read out of CFRU's Perish case, tools/gen_gen3_profile.py).
# Row rules: set = live | mask, keep = live & mask (the timer's high nibble; the low nibble,
# perishSongTimer:4, becomes 0), value = exactly this.
HANDOFF_HEAD = (
    # (name, ram address key, derived offset key, width, rule, derived value key or constant)
    ("perish_status", "STATUS3_ADDR", None, 4, "set", "STATUS3_PERISH_SONG"),
    ("perish_timer", "DISABLE_STRUCTS_ADDR", "DISABLE_STRUCT_PERISH_TIMER_OFF", 1, "keep", 0xF0),
    ("no_op_action", "CHOSEN_ACTION_ADDR", None, 1, "value", "B_ACTION_NOTHING_FAINTED"),
)


def handoff_head(title_profile: dict) -> tuple[list | None, str]:
    """([the three head rows], "") from one title's profile, or (None, the missing field)."""
    ram, derived = title_profile.get("ram", {}), title_profile.get("derived", {})
    rows = []
    for name, addr_key, off_key, width, rule, arg in HANDOFF_HEAD:
        need = [("ram", addr_key, ram)] + ([("derived", off_key, derived)] if off_key else []) \
            + ([("derived", arg, derived)] if isinstance(arg, str) else [])
        for section, key, table in need:
            if not isinstance(table.get(key), int):
                return None, f"profile.{section}.{key} absent"
        address = ram[addr_key] + (derived[off_key] if off_key else 0)
        rows.append({"name": name, "address": address, "width": width,
                     rule: derived[arg] if isinstance(arg, str) else arg})
    return rows, ""


# G5-EXPLODE-HANDOFF (owner ruling 19, 2026-09-24): on a pack that HOLDS battle_commit (RR), Explode's
# menu skip ends in the same hand-off, so the policy must know its exact rows too -- commit_plan's
# (lua/gen3/client.lua), battler 0, in write order. `group: moves` rows are all-or-none (the first
# commit only); `ptr` rows sit at read_u32(ptr) + offset and are absent while the pointer is 0.
# Values: Explosion = 153 with PP 5 (asserted in this ROM's own gBattleMoves), B_ACTION_USE_MOVE = 0,
# chosenMovePositions = 0, moveTarget = 1 (the old client's production constants,
# archive/gen3-old-client:lua/memory_gba.lua:1318-1345); BattlePokemon.moves +0x0C / .pp +0x24 (pret include/pokemon.h,
# CFRU keeps the layout).
EXPLODE_MOVE, EXPLODE_PP, EXPLODE_ACTION, EXPLODE_TARGET = 153, 5, 0, 1
# F1 M5: the move identity, not just its PP -- gBattleMoves[153].effect (byte 0 of struct BattleMove,
# pret include/pokemon.h) must be EFFECT_EXPLOSION (pret include/constants/battle_move_effects.h:11)
EFFECT_EXPLOSION = 7
BATTLE_MON_MOVES_OFF, BATTLE_MON_PP_OFF = 0x0C, 0x24
EXPLODE_SOURCE = ("client.lua commit_plan rows, battler 0; profile.ram BATTLE_MONS/CHOSEN_ACTION/"
                  "CHOSEN_MOVE/BATTLE_STRUCT_PTR + derived BATTLE_STRUCT_*_OFF; Explosion effect "
                  "EFFECT_EXPLOSION and PP 5 read from rom.BATTLE_MOVES_ADDR in every RR ROM; constants "
                  "archive/gen3-old-client:lua/memory_gba.lua:1318-1345")


def explode_head(title_profile: dict, roms: dict[str, bytes]) -> tuple[dict | None, str]:
    """({"head": rows, "source"}, "") for RR's Explode+H shape, or (None, why it is unproven)."""
    ram, derived, rom_facts = (title_profile.get(k, {}) for k in ("ram", "derived", "rom"))
    for section, key, table in (("ram", "BATTLE_MONS_ADDR", ram), ("ram", "CHOSEN_ACTION_ADDR", ram),
                                ("ram", "CHOSEN_MOVE_ADDR", ram), ("rom", "BATTLE_MOVES_ADDR", rom_facts),
                                ("derived", "BATTLE_MOVE_ENTRY_SIZE", derived),
                                ("derived", "BATTLE_MOVE_PP_OFFSET", derived)):
        if not isinstance(table.get(key), int):
            return None, f"profile.{section}.{key} absent"
    entry_at = rom_facts["BATTLE_MOVES_ADDR"] + EXPLODE_MOVE * derived["BATTLE_MOVE_ENTRY_SIZE"]
    pp_at = entry_at + derived["BATTLE_MOVE_PP_OFFSET"]
    for kind, rom in roms.items():
        if kind == "_fr":
            continue
        if body(rom, entry_at, 1)[0] != EFFECT_EXPLOSION:
            return None, f"move {EXPLODE_MOVE} effect at {entry_at:#010x} is not EFFECT_EXPLOSION in RR {kind}"
        if body(rom, pp_at, 1)[0] != EXPLODE_PP:
            return None, f"move {EXPLODE_MOVE} PP at {pp_at:#010x} is not {EXPLODE_PP} in RR {kind}"
    base = ram["BATTLE_MONS_ADDR"]
    rows = [row for i in range(4) for row in (
        {"name": f"move_{i}", "address": base + BATTLE_MON_MOVES_OFF + 2 * i, "width": 2,
         "value": EXPLODE_MOVE, "group": "moves"},
        {"name": f"pp_{i}", "address": base + BATTLE_MON_PP_OFF + i, "width": 1,
         "value": EXPLODE_PP, "group": "moves"})]
    rows += [{"name": "chosen_action", "address": ram["CHOSEN_ACTION_ADDR"], "width": 1, "value": EXPLODE_ACTION},
             {"name": "chosen_move", "address": ram["CHOSEN_MOVE_ADDR"], "width": 2, "value": EXPLODE_MOVE}]
    if isinstance(ram.get("BATTLE_STRUCT_PTR_ADDR"), int):
        for name, key, value in (("chosen_move_position", "BATTLE_STRUCT_CHOSEN_MOVE_POS_OFF", 0),
                                 ("move_target", "BATTLE_STRUCT_MOVE_TARGET_OFF", EXPLODE_TARGET)):
            if isinstance(derived.get(key), int):
                rows.append({"name": name, "ptr": ram["BATTLE_STRUCT_PTR_ADDR"], "offset": derived[key],
                             "width": 1, "value": value})
    return {"head": rows, "source": EXPLODE_SOURCE}, ""


def handoff_block(syms, sym_file: str, is_rr: bool, roms: dict[str, bytes],
                  slot: int, title_profile: dict | None = None, title: str = "") -> tuple[dict | None, str]:
    """(the battle.handoff block, "") or (None, why it is unproven)."""
    fn = HANDOFF_FN
    head, why = handoff_head(title_profile or {})
    if head is None:
        return None, f"head: {why}"
    if fn not in syms or "gBattlerControllerFuncs" not in syms:
        return None, f"{fn}: symbol absent"
    addr, size = syms[fn]
    lo, hi = player_span(sym_file)
    if not lo <= addr < hi:
        return None, f"{fn} @ {addr:#010x} is not {PLAYER_CONTROLLER_OBJ}'s"
    if slot != syms["gBattlerControllerFuncs"][0]:
        return None, f"battle_input_controller slot {slot:#010x} is not gBattlerControllerFuncs"
    value = addr | 1
    block = {"symbol": "gBattlerControllerFuncs", "address": slot, "stride": 4, "width": 4,
             "value": value, "value_symbol": fn, "head": head}
    if is_rr:
        fr = body(roms["_fr"], addr, size)
        for kind, rom in roms.items():
            if kind == "_fr":
                continue
            got = body(rom, addr, size)
            if got[:HANDOFF_PREFIX] != fr[:HANDOFF_PREFIX] or \
                    got[HANDOFF_POOL[0]:HANDOFF_POOL[1]] != fr[HANDOFF_POOL[0]:HANDOFF_POOL[1]]:
                return None, f"{fn} @ {addr:#010x}: prefix/pool differs from FR in RR {kind}"
            if ldr_literal(rom, RR_HANDOFF_VALUE_LDR) != value:
                return None, f"LDR@0x{RR_HANDOFF_VALUE_LDR:08X} does not load {value:#010x} in RR {kind}"
        block["source"] = (f"rom: slot = the battle_input_controller pin (LDR@0x08032BAC, "
                           f"HandleChooseActionAfterDma3, FR-identical); value LDR@0x{RR_HANDOFF_VALUE_LDR:08X} "
                           f"(the {fn} call every CFRU action-menu commit makes) == pokefirered.sym {fn}|1; "
                           f"{fn} prefix +0..+0x{HANDOFF_PREFIX - 1:X} and pool +0x40..+0x47 FR-identical")
    else:
        pool = body(roms["clean"], addr, size)
        if pool[:len(FRLG_HANDOFF_PREFIX)] != FRLG_HANDOFF_PREFIX:
            return None, f"{fn} @ {addr:#010x}: prefix +0..+0xF differs from the pret build"
        for word in (slot, syms["PlayerBufferRunCommand"][0] | 1):
            if not pool_offsets(pool, word):
                return None, f"{fn} @ {addr:#010x}: pool lacks {word:#010x} in this ROM"
        block["source"] = (f"{fn}|1 (.sym, {PLAYER_CONTROLLER_OBJ}); ROM body prefix +0..+0xF == "
                           f"the pret build, pools gBattlerControllerFuncs + PlayerBufferRunCommand|1; pret "
                           f"src/battle_controller_player.c:186-200,244")
        if title in TITLE_SOURCES:
            block["source"] = (f"{fn}|1 (.sym; {span_source(sym_file)}); ROM body prefix +0..+0xF == "
                               f"the FR/LG pret build, pools gBattlerControllerFuncs + PlayerBufferRunCommand|1; "
                               + TITLE_SOURCES[title]["handoff"])
    return block, ""


def native_block(profile: dict | None) -> dict | None:
    if not profile or not isinstance(profile.get("native"), dict):
        return None
    nat = profile["native"]
    spans = []
    for key, size, what in NATIVE_ARENA:
        if nat.get(key) is None:
            continue
        spans.append({"key": key, "start": nat[key], "size": size, "what": what})
    entry = {"version": "gen3-native-v1", "base": nat.get("BASE"), "sig": nat.get("SIG"),
             "abi": nat.get("ABI"), "info": nat.get("INFO"), "spans": spans, "source": NATIVE_SOURCE}
    entry.update(NATIVE_LAYOUT)
    return entry


def sound_block(syms, is_rr: bool, title: str = "") -> dict:
    constants = dict(SOUND_CONSTANTS)
    out = {"version": "gen3-sound-v1",
           "ident_magic": constants["ident_magic"], "tracks_off": 0x2C,
           "player_head_off": constants["player_head_off"],
           "player_next_off": constants["player_next_off"],
           "iwram_min": constants["iwram_min"], "iwram_max": constants["iwram_max"],
           "ident_off": 0x34, "track0_off": 0x00,
           "fields": [{"name": n, "offset": o, "size": s, "on": (t[0] if t else "player")}
                      for row in SOUND_FIELDS for n, o, s, *t in [row]],
           "source": SOUND_SOURCE_RR if is_rr else TITLE_SOURCES.get(title, {}).get("sound", SOUND_SOURCE_FRLG)}
    if not is_rr:
        for key in ("sound_info_ptr", "sound_info", "player_se1"):
            symbol = constants[key]
            if symbol in syms:
                out[key] = {"symbol": symbol, "address": syms[symbol][0], "source": "sym"}
    return out


def build(pack: str) -> tuple[dict, list[str]]:
    out, unverified = {}, []
    for title, (sym_file, kinds) in ALL_PACKS[pack].items():
        out[title], bad = build_title(pack, title, sym_file, kinds)
        unverified += [f"{title}: {row}" for row in bad]
    return out, unverified


def out_path(pack: str) -> pathlib.Path:
    return ROOT / "data" / "games" / pack / "write_checkpoint.json"


def render(value: dict) -> str:
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="fail if a committed file is stale")
    args = ap.parse_args()
    rc = 0
    for pack in ALL_PACKS:
        target, unverified = build(pack)
        text = render(target)
        path = out_path(pack)
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != text:
                print(f"{path.relative_to(ROOT)} is stale; run tools/gen_gen3_write_checkpoint.py",
                      file=sys.stderr)
                rc = 1
            else:
                print(f"{path.relative_to(ROOT)} is current")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8", newline="\n")
            print(f"wrote {path.relative_to(ROOT)}: " + ", ".join(
                f"{t} {len(v['anchors'])} anchors, {len(v['predicates'])} predicates, "
                f"{len(v['tasks']['allowed_overworld_tasks'])} tasks" for t, v in target.items()))
        for row in unverified:
            print(f"  UNVERIFIED (not emitted) {row}", file=sys.stderr)
    return rc


if __name__ == "__main__":
    sys.exit(main())
