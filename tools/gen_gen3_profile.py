#!/usr/bin/env python3
"""Generate the Gen 3 packs' profile.json from Lua literals and pinned pret facts.

The primary source is the literal address database in `lua/games/gen3_frlge.lua`
(`GEN3.profiles.vanilla` / `.ap` / `.radical_red` and the additive
`GEN3.profiles.emerald`).  Nothing here re-types an address: the tables are parsed
out of the Lua text by a small strict parser for the subset those tables use
(`KEY = 0xHEX | integer | "string" | true/false/nil | { ... }` plus `+`/`*`
arithmetic and comments).  The file is never `require`d under a Lua runtime.
RR-P5 additions are decoded from captured instruction/literal-pool anchors in
the admitted RR binary. The anchors are shipped for ROM-free generation and
verified against patch/build/slink_RR.gba whenever that local witness exists.

Packs (PLAN §4, §5.1):
    data/games/gen3_frlg/profile.json   titles firered, leafgreen (admitted; both read the
                                        `vanilla` table today) + the unadmitted titles
                                        firered_ap (`.ap`) and emerald (`.emerald`), copied
                                        verbatim so no data is lost
    data/games/gen3_rr/profile.json     title radical_red (`.radical_red`) + a `native` block
                                        for kind `companion`: the companion-patch mailbox ABI and
                                        the ghost/object-event addresses, sourced from the patch's
                                        own C (patch/src/handlers.c -- the companion is BUILT from
                                        it, so it is the ABI's actual authority, not a copy of it;
                                        C5-6 deleted the old archive/gen3-old-client:lua/mailbox.lua + archive/gen3-old-client:lua/peer_ghost_npc.lua
                                        scrape targets), each with its source file:line in the
                                        sibling `_src` map

    python tools/gen_gen3_profile.py            # rewrite both profiles
    python tools/gen_gen3_profile.py --check    # exit 1 if either committed file is stale
                                                # (the P2 exit condition "profile diff = 0")
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
SRC = "lua/games/gen3_frlge.lua"
HANDLERS_SRC = "patch/src/handlers.c"
PRET_PIN = "pret/pokefirered@c75f352304d529f6ba92d4f74b9cf8b5c3810788"
STORAGE_HEADER = f"{PRET_PIN}:include/pokemon_storage_system.h"

# Pinned C layout facts, independent of the optional local pret checkout.
# boxes follows u8 currentBox, but BoxPokemon begins with u32 personality:
# ARM alignment inserts three padding bytes (the header's 0x0001 comment is wrong).
FRLG_DERIVED = {
    "EXPERIENCE_TABLE_ENTRY_COUNT": (101, f"{PRET_PIN}:src/data/pokemon/experience_tables.h:18 "
                                    "(gExperienceTables[][MAX_LEVEL + 1])"),
    "MAX_LEVEL": (100, f"{PRET_PIN}:include/constants/pokemon.h:187 (MAX_LEVEL)"),
    "BOX_DATA_OFFSET": (4, f"{STORAGE_HEADER}:44-48; "
                         f"{PRET_PIN}:include/pokemon.h:105-108 (u32 alignment)"),
    "BOXES_PER_STORE": (14, f"{STORAGE_HEADER}:7 (TOTAL_BOXES_COUNT)"),
    "MONS_PER_BOX": (5 * 6, f"{STORAGE_HEADER}:8-10 (IN_BOX_ROWS * IN_BOX_COLUMNS)"),
    "PARTY_CAPACITY": (6, f"{PRET_PIN}:include/constants/global.h:78 (PARTY_SIZE)"),
    # ── P4 card C4-2a: trainer/location/badges/bag/battle facts the new client needs,
    # none of which the vanilla Lua table carries (docs/gen3/research/p4_gen1_contract_map.md
    # §2 item 3, §3.2). Every offset below is read straight off the pinned pret commit, never
    # off Radical Red (memory: RR types are non-standard).
    "SB2_OT_ID_OFFSET": (0x0A, f"{PRET_PIN}:include/global.h:332 (SaveBlock2.playerTrainerId); "
                         f"{PRET_PIN}:src/pokemon.c:1798-1801 (u32 little-endian assembly)"),
    "SB2_NAME_OFFSET": (0, f"{PRET_PIN}:include/global.h:329 (SaveBlock2.playerName)"),
    "SB1_LOCATION_MAP_GROUP_OFFSET": (0x04, f"{PRET_PIN}:include/global.h:759-762 "
                                      "(SaveBlock1.location); "
                                      f"{PRET_PIN}:include/global.h:392-398 (struct WarpData.mapGroup)"),
    "SB1_LOCATION_MAP_NUM_OFFSET": (0x05, f"{PRET_PIN}:include/global.h:759-762 "
                                    "(SaveBlock1.location); "
                                    f"{PRET_PIN}:include/global.h:392-398 (struct WarpData.mapNum)"),
    "SB1_BADGE_BYTE_OFFSET": (0x104, f"{PRET_PIN}:include/constants/flags.h:1324,1364-1371 "
                              "(SYS_FLAGS=0x800; FLAG_BADGE01_GET..FLAG_BADGE08_GET = "
                              "SYS_FLAGS+0x20..+0x27; byte = flag_id >> 3, relative to "
                              "SaveBlock1.flags[])"),
    "OUTCOME_WON": (1, f"{PRET_PIN}:include/constants/battle.h:76 (B_OUTCOME_WON)"),
    "OUTCOME_LOST": (2, f"{PRET_PIN}:include/constants/battle.h:77 (B_OUTCOME_LOST)"),
    "OUTCOME_DREW": (3, f"{PRET_PIN}:include/constants/battle.h:78 (B_OUTCOME_DREW)"),
    "OUTCOME_RAN": (4, f"{PRET_PIN}:include/constants/battle.h:79 (B_OUTCOME_RAN)"),
    "OUTCOME_CAUGHT": (7, f"{PRET_PIN}:include/constants/battle.h:82 (B_OUTCOME_CAUGHT)"),
    "BATTLE_TYPE_TRAINER_MASK": (0x08, f"{PRET_PIN}:include/constants/battle.h:50 "
                                 "(BATTLE_TYPE_TRAINER)"),
    "BATTLE_TYPE_DOUBLE_MASK": (0x01, f"{PRET_PIN}:include/constants/battle.h:47 "
                                "(BATTLE_TYPE_DOUBLE)"),
    "GMAIN_INBATTLE_OFFSET": (0x439, "data/games/gen3_frlg/write_checkpoint.json: "
                              "firered.predicates.in_battle (gMain+0x439; verified live by the "
                              "cb1_overworld census probe, docs/gen3/probes/census_fr_overworld_"
                              "2026-09-21.txt)"),
    "GMAIN_INBATTLE_MASK": (0x02, "data/games/gen3_frlg/write_checkpoint.json: "
                            "firered.predicates.in_battle"),
    "BATTLE_MOVE_ENTRY_SIZE": (12, "data/gen3/pret/pokefirered.sym:26905 gBattleMoves "
                               "(0x10A4 bytes / 355 moves = 12); "
                               f"{PRET_PIN}:include/pokemon.h:284"),
    "BATTLE_MOVE_PP_OFFSET": (4, f"{PRET_PIN}:include/pokemon.h:238-249 (struct BattleMove.pp)"),
    # boxes card (C4-3) addendum: PP restore needs the species growth rate, which lives inside
    # the existing BASESTATS entry (rom.BASESTATS_ADDR / BASESTATS_ADDR_BY_GAME_CODE) -- no new
    # ROM address, just its offset.
    "BASESTATS_GROWTH_RATE_OFFSET": (0x13, f"{PRET_PIN}:include/pokemon.h:230 "
                                     "(struct SpeciesInfo.growthRate)"),
    "SHEDINJA_SPECIES_ID": (303, f"{PRET_PIN}:include/constants/species.h:312 (SPECIES_SHEDINJA); "
                            "used by CalculateMonStats' 1-HP exception, src/pokemon.c:2124-2132"),
    # C4-ACTIVE-FAINT-P: mechanism P (docs/gen3/research/active_faint_in_battle_scope_2026-09-23.md
    # §2d) -- the Perish-counter-0 + no-op commit. Together with the ram fields below these are
    # the pack's active_faint capability; RR ships none of them (CFRU layout OPEN, G5).
    "STATUS3_PERISH_SONG": (0x20, f"{PRET_PIN}:include/constants/battle.h:138 (STATUS3_PERISH_SONG)"),
    "DISABLE_STRUCT_SIZE": (0x1C, f"{PRET_PIN}:include/battle.h:139-172 (sizeof(struct DisableStruct)); "
                            "data/gen3/pret/pokefirered.sym:126 gDisableStructs 0x70 bytes / 4"),
    "DISABLE_STRUCT_PERISH_TIMER_OFF": (0x0F, f"{PRET_PIN}:include/battle.h:153-154 "
                                        "(perishSongTimer:4 low nibble, perishSongTimerStartValue:4)"),
    "B_ACTION_NOTHING_FAINTED": (13, f"{PRET_PIN}:include/battle.h:48 (B_ACTION_NOTHING_FAINTED)"),
    # C5-6: gBattleMons[b].statStages[STAT_ATK] -- ATK..EVA are the 7 bytes from here, in the
    # wire order; statStages[STAT_HP] at +0x18 is never shown (reads.lua read_stat_stages).
    "BATTLE_MON_STAT_STAGES_OFF": (0x19, f"{PRET_PIN}:include/pokemon.h:187 (BattlePokemon."
                                   "statStages at 0x18); include/constants/pokemon.h:166-175 "
                                   "(STAT_HP=0, STAT_ATK=1 .. STAT_EVASION=7)"),
}

# ── more P4 card C4-2a facts: symbols read straight out of each title's own .sym file (same
# technique as the gPokemonStorage match below), so the address is self-verifying per title
# rather than a literal this file could get wrong for one of the two ROMs.
FRLG_SYM_ADDR = {
    # profile section, key -> the unique global .sym symbol
    ("ram", "TRAINER_OPPONENT_ADDR"): "gTrainerBattleOpponent_A",
    ("rom", "EXPERIENCE_TABLES_ADDR"): "gExperienceTables",
    ("rom", "BATTLE_MOVES_ADDR"): "gBattleMoves",
    ("rom", "PP_UP_GET_MASK_ADDR"): "gPPUpGetMask",
    # C4-ACTIVE-FAINT-P (mechanism P). CHOSEN_ACTION_ADDR/BATTLE_COMM_ADDR share RR's names on
    # purpose; CHOSEN_MOVE_ADDR is deliberately absent, so vanilla stays not explode_capable.
    ("ram", "STATUS3_ADDR"): "gStatuses3",
    ("ram", "DISABLE_STRUCTS_ADDR"): "gDisableStructs",
    ("ram", "CHOSEN_ACTION_ADDR"): "gChosenActionByBattler",
    ("ram", "BATTLE_COMM_ADDR"): "gBattleCommunication",
}

# C5-9: the same three values for the vanilla titles, taken from each title's own .sym.  They are
# stored Thumb (|1) because that is the form gBattleMainFunc holds and the write_checkpoint pack's
# `expect_symbol` already produces (syms[symbol][0] | 1).  The symbol's .sym scope letter varies
# (BeginBattleIntroDummy/BeginBattleIntro are `g`, BattleIntroGetMonsData is `l`), so the lookup
# below accepts any scope rather than the `g`-only one FRLG_SYM_ADDR uses.
FRLG_SYM_THUMB_ADDR = {
    ("rom", "BEGIN_BATTLE_INTRO_ADDR"): "BeginBattleIntro",
    ("rom", "BEGIN_BATTLE_INTRO_DUMMY_ADDR"): "BeginBattleIntroDummy",
    ("rom", "BATTLE_INTRO_GET_MONS_DATA_ADDR"): "BattleIntroGetMonsData",
}
# _thumb_keys runs inside _title(), before these facts exist, so their keys are declared here.
INTRO_THUMB_KEYS = ("BEGIN_BATTLE_INTRO_ADDR", "BEGIN_BATTLE_INTRO_DUMMY_ADDR",
                    "BATTLE_INTRO_GET_MONS_DATA_ADDR")

# ── gen3_rr facts sourced from the OLD client (archive/gen3-old-client:lua/memory_gba.lua), per the owner's 2026-09-23
# ruling relayed on card C4-2a: the old RR client is production-tested, so its RAM offsets are
# acceptable RR evidence where no ROM/pret evidence exists. Every one of these is read from
# archive/gen3-old-client:lua/memory_gba.lua GENERICALLY (no RR-only branch), i.e. the exact same code path already serves
# RR live today -- never a value the pack already derives from the ROM (that trap is
# SB1_PTR_ADDR/SB2_PTR_ADDR above, which this dict does not touch).
RR_DERIVED = {
    "SB1_LOCATION_MAP_GROUP_OFFSET": (0x04, "archive/gen3-old-client:lua/memory_gba.lua:271,1112 (old-client RR profile, "
                                      "production-tested: mapGroup read generically off SB1_PTR_ADDR)"),
    "SB1_LOCATION_MAP_NUM_OFFSET": (0x05, "archive/gen3-old-client:lua/memory_gba.lua:272,1113 (old-client RR profile, "
                                    "production-tested)"),
    "SB1_BADGE_BYTE_OFFSET": (0x104, "archive/gen3-old-client:lua/memory_gba.lua:1177,1181 (old-client RR profile, "
                              "production-tested: M.readBadges is generic over M.SB1_FLAGS_OFFSET)"),
    "BATTLE_TYPE_TRAINER_MASK": (0x08, "archive/gen3-old-client:lua/memory_gba.lua:378 (old-client RR profile, "
                                 "production-tested)"),
    "BATTLE_TYPE_DOUBLE_MASK": (0x01, "archive/gen3-old-client:lua/memory_gba.lua:385 (old-client RR profile, "
                                "production-tested)"),
    "OUTCOME_WON": (1, "archive/gen3-old-client:lua/memory_gba.lua:389 (old-client RR profile, production-tested; "
                    "unconditional, never overridden per-profile)"),
    "OUTCOME_LOST": (2, "archive/gen3-old-client:lua/memory_gba.lua:390 (old-client RR profile, production-tested)"),
    "OUTCOME_DREW": (3, "archive/gen3-old-client:lua/memory_gba.lua:391 (old-client RR profile, production-tested: "
                     "\"CFRU inserts DREW=3, shifting RAN from 3->4\")"),
    # Confirmed unrenumbered by CFRU: data/games/gen3_frlge/rr_species.json["303"] == "Shedinja",
    # the same id as pret's SPECIES_SHEDINJA (FRLG_DERIVED above).
    "SHEDINJA_SPECIES_ID": (303, 'data/games/gen3_frlge/rr_species.json:"303"="Shedinja" '
                            "(RR species table; CFRU keeps this id unrenumbered)"),
    "BATTLE_MON_STAT_STAGES_OFF": (0x19, "archive/gen3-old-client:lua/memory_gba.lua:402-406 (old-client RR profile, "
                                   "production-tested: M.readStatStages; CFRU puts type3 at "
                                   "+0x18, so ATK..EVA start at +0x19)"),
}

# RR-P5 binary witnesses: file offsets, NOT GBA virtual addresses. These bytes
# were read from the admitted companion SHA1 below and checked against clean RR.
# Keep complete reader bodies + literal pools, so a pointer alone is not evidence
# for which field is being accessed. No Capstone dependency in the generator.
RR_WITNESS_SHA1 = "ea5352f8a3b9073f8ae20870ad12857925d442cd"
RR_ROM_ANCHORS = {
    "controller_exec_marker": (0x17248,
        "00b50006030e0848006802210840002810d0064a06499800401801680907106808431060"
        "0ee000004c2b0202c83b02025ce42508044a054998004018116800680143116001bc0047"
        "c83b02025ce42508"),
    "controller_exec_reader": (0x141DC,
        "154c1649164b1d78a800401802681001f0210906084310431102084312031043216801409846002901d0"),
    "controller_exec_reader_pool": (0x14234, "c83b0202"),
    "calculate_pp": (0x4101C,
        "10b50004000c1206120e0d4c43001b189b001b191c790b48101803780b4052001341"
        "9800c018800060436421a2f1e6ff24182406240e201c10bc02bc08470000d0211509a1de2508"),
    "box_level": (0x3E830,
        "70b5051c0b21002201f084fa041c2404240c281c1921002201f07cfa031c0122104e1149"
        "e000001b80004118c87c20256d01684304308019006898420bd80c1c0132fa2a07dc9100"
        "e07c68430918891908689842f4d9501e0006000e70bc02bc084700004c511509ec987b09"),
    "trainer_id": (0xCC1E4,
        "06480268507b0006117b09040843d17a09020843917a0843704700000c500003"),
    "pp_up_masks": (0x25DEA1, "030c30c0"),
    # Expanded CFRU code actually loads and stores the callback into gBattleMainFunc.
    "action_callback_store": (0x1070626, "2d4b2d4a1a60"),
    "action_callback_pool": (0x10706DC, "844f000341400108"),
    "action_callback_entry": (0x14040, "f0b557464e464546e0b487b00f480021"),
    # C5-9 (the rival-swap window): every site that installs gBattleMainFunc with a phase value.
    # Each is a Thumb LDR pair (the gBattleMainFunc pointer, then the value) followed by STR, so
    # the pool word alone is not evidence -- the store is.  pret: battle_controllers.c:88,113,150,
    # 175,213 assigns BeginBattleIntro / BeginBattleIntroDummy per battle type, and
    # BeginBattleIntro's own tail writes BattleIntroGetMonsData|1 (battle_main.c:2196-2200).
    "intro_store_controllers": (0xD27C,
        "80b4194919480860002219488046002318498c46184fff26184d194c4046614604318c46"
        "043901c1d11908783043087050190370101903700132032aeeddfff7b9ff104800240460"
        "65f0fcf836f078fe00480047992b04090c48047008bc9846f0bc01bc00470000844f0003"
        "bd23010811e30208e04f0003d63b0202f83f0202fc3f0202c83b0202542b0202dc3d0202"
        "30b50448006802210840002804d000f0bbf803e04c2b020200f01ef800f01efa0b480068"
        "4021084000280ed10024094801788c4209da051c2006000e00211af12dfd013428788442"
        "f6db30bc01bc00474c2b0202cc3b020210b50c4802680124131c2340002b4fd109490a48"
        "0860802040021040002817d0074a084911600848037051604470074902206fe04c2b0202"
        "844f0003c1230108"),
    "intro_store_begin": (0x123C0,
        "00b500f037f804490020487003490448086001bc00470000823e0202844f0003ad2f0108"),
    "intro_getmons_body": (0x12FAC,
        "30b5034d2878002804d0012814d02ee0823e0202074c68782070002000210022faf7eaff"
        "207804f039f92878013028701de00000c43b020208480268002a16d16878013068700649"
        "0006000e097888420cd104490448086009e00000c83b0202cc3b0202844f000321300108"
        "2a7030bc01bc0047"),
    # G4-PH (mechanism P on RR, docs/gen3/research/rr_active_faint_parity_scope_2026-09-23.md §2,
    # facts re-asserted by tools/research/rr_active_faint.py): CFRU end-turn state 34, the Perish
    # case (0x090923C8..0x0909243C) and its pool words (0x09092764..0x09092773).
    "perish_state34": (0x10923C8,
        "2027e64db30059599c46394201d1fff74ff9582002007243e14b9b181c8d002c01d1fff745f9fd23de48"
        "0370fc3b43708370c3701b337343ff26db4ad2180832d3791b071b0f03714671d84809d16346b94359"
        "51d64b1c60d64b03600068fff740f90f24d1790f332340a1430b43d371d14bf2e7"),
    "perish_state34_pool": (0x1092764, "fc3d0202e43b0202b82a02020c3e0202"),
    # HandleTurnActionSelectionState case 0, absent battler: gChosenActionByBattler[b] = 13
    # (LDR@0x0801412E, movs r1,#0xd @0x08014132), pool 0x08014164.
    "htas_absent_action": (0x14128, "0340002b26d00d4810180d21"),
    "htas_absent_action_pool": (0x14164, "7c3d0202"),
    # sTurnActionsFuncsTable[13] (table 0x08250038) = HandleAction_NothingIsFainted|1
    "turn_actions_nothing_fainted": (0x25006C, "3d6d0108"),
}


def rr_rom_facts(rom: bytes | None = None) -> dict:
    """Decode captured RR instructions/literals; verify a supplied ROM before use.

    Embedded anchors keep ordinary profile generation reproducible without a
    copyrighted ROM. With a local binary, --check also checks every witness byte.
    A rebuild must be deliberately re-pinned if any witness changes.
    """
    anchors = [(name, off, bytes.fromhex(raw)) for name, (off, raw) in RR_ROM_ANCHORS.items()]
    if rom is not None:
        for name, off, raw in anchors:
            if rom[off:off + len(raw)] != raw:
                raise ValueError(f"RR ROM anchor mismatch: {name} at 0x{off:X}")

    def read(off: int, size: int) -> int:
        for _, start, raw in anchors:
            if start <= off and off + size <= start + len(raw):
                return int.from_bytes(raw[off - start:off - start + size], "little")
        raise ValueError(f"RR fact reads outside captured anchors: 0x{off:X}")

    def literal(off: int) -> int:
        ins = read(off, 2)
        if ins & 0xF800 != 0x4800:
            raise ValueError(f"not a Thumb LDR literal: 0x{off:X}")
        return read(((off + 4) & ~3) + (ins & 255) * 4, 4)

    # CalculatePPWithBonus: (move*2 + move)*4, then LDRB +4.
    move_stride = ((1 << ((read(0x41028, 2) >> 6) & 31)) + 1) \
        << ((read(0x4102C, 2) >> 6) & 31)
    pp_offset = (read(0x41030, 2) >> 6) & 31
    # GetLevelFromBoxMonExp: growth byte +0x13; growth row = 0x20 << 5;
    # u32 experience entries, and CMP level,#0xFA. RR is NOT vanilla 101/100.
    row_bytes = (read(0x3E85E, 2) & 255) << ((read(0x3E860, 2) >> 6) & 31)
    growth_offset = (read(0x3E85C, 2) >> 6) & 31
    # GetPlayerTrainerId assembles byte offsets D,C,B,A into u32 little endian.
    ot_offsets = [(read(off, 2) >> 6) & 31 for off in (0xCC1E8, 0xCC1EC, 0xCC1F2, 0xCC1F8)]
    if ot_offsets != list(range(ot_offsets[-1] + 3, ot_offsets[-1] - 1, -1)):
        raise ValueError("RR trainer ID reader is not four contiguous bytes")
    # The canonical SB2 pointer is ROM-derived in write_checkpoint (C3-33).
    # This witness checks that symbol; it never replaces the legacy profile value.
    if literal(0xCC1E4) != 0x0300500C:
        raise ValueError("RR trainer reader no longer uses canonical gSaveBlock2Ptr")
    if literal(0x1070626) != 0x03004F84 or read(0x107062A, 2) != 0x601A:
        raise ValueError("RR callback witness no longer stores into gBattleMainFunc")
    # C5-9: the intro window's callback installs (see RR_ROM_ANCHORS).  Each is LDR-the-pointer,
    # LDR-the-value, STR -- the same shape as the 0x1070626 witness above -- so the facts are
    # *stored*, not merely pooled.
    for ldr_ptr, ldr_val, str_site, label in (
            (0xD27E, 0xD280, 0xD282, "intro_store_controllers/BeginBattleIntroDummy"),
            (0xD374, 0xD376, 0xD378, "intro_store_controllers/BeginBattleIntro"),
            (0x123CC, 0x123CE, 0x123D0, "intro_store_begin/BattleIntroGetMonsData")):
        if literal(ldr_ptr) != 0x03004F84 or read(str_site, 2) != 0x6008:
            raise ValueError(f"RR intro callback install no longer stores into gBattleMainFunc "
                             f"({label} @0x{ldr_ptr:X})")
        if literal(ldr_val) & 1 == 0:
            raise ValueError(f"RR intro install is not a Thumb pointer ({label})")
    exec_flags = literal(0x1725A)
    if exec_flags != literal(0x1727C) or exec_flags != literal(0x141DC):
        raise ValueError("RR controller execution-flag writer/reader disagree")
    # G4-PH: mechanism P's layout, read out of CFRU's own Perish case (state 34).
    def imm8(off: int, op: int) -> int:        # the #imm8 of a Thumb `movs/adds/subs rN,#imm8`
        ins = read(off, 2)
        if ins & 0xFF00 != op:
            raise ValueError(f"RR Perish witness moved: 0x{off:X} is 0x{ins:04X}")
        return ins & 0xFF
    perish_bit = imm8(0x10923C8, 0x2700)                                  # movs r7,#0x20
    if read(0x10923D2, 2) != 0x4239 or read(0x1092418, 2) != 0x43B9:      # tst r1,r7 / bics r1,r7
        raise ValueError("RR Perish case no longer tests/clears gStatuses3 with r7")
    # movs r3,#0xfd; subs r3,#0xfc; adds r3,#0x1b; muls r3,r6 (r6 = battler)
    disable_size = imm8(0x10923EE, 0x2300) - imm8(0x10923F4, 0x3B00) + imm8(0x10923FC, 0x3300)
    if read(0x10923FE, 2) != 0x4373:
        raise ValueError("RR Perish case no longer scales the battler by the DisableStruct size")
    # adds r2,#8; ldrb r3,[r2,#7]; lsls r3,#0x1c; lsrs r3,#0x1c (the low nibble)
    ldrb = read(0x1092408, 2)
    if ldrb & 0xF83F != 0x7813 or read(0x109240A, 2) != 0x071B or read(0x109240C, 2) != 0x0F1B:
        raise ValueError("RR Perish case no longer reads the timer as a low nibble")
    timer_off = imm8(0x1092406, 0x3200) + ((ldrb >> 6) & 31)
    nothing_fainted = imm8(0x14132, 0x2100)                                # movs r1,#0xd
    if read(0x25006C, 4) != 0x08016D3D:
        raise ValueError("RR sTurnActionsFuncsTable[13] is not HandleAction_NothingIsFainted")
    perish_where = "perish_state34:0x090923C8..0x0909243C (CFRU end-turn state 34)"
    facts = {
        ("ram", "STATUS3_ADDR"): (literal(0x10923CA),
            f"{perish_where} LDR@0x090923CA pool@0x09092764"),
        ("ram", "DISABLE_STRUCTS_ADDR"): (literal(0x1092402),
            f"{perish_where} LDR@0x09092402 pool@0x09092770"),
        ("derived", "STATUS3_PERISH_SONG"): (perish_bit,
            f"{perish_where} movs r7,#imm@0x090923C8; tst@0x090923D2, bics@0x09092418"),
        ("derived", "DISABLE_STRUCT_SIZE"): (disable_size,
            f"{perish_where} 0x090923EE..0x090923FE (movs #0xfd, subs #0xfc, adds #0x1b, muls)"),
        ("derived", "DISABLE_STRUCT_PERISH_TIMER_OFF"): (timer_off,
            f"{perish_where} adds r2,#8 @0x09092406; ldrb [r2,#7] @0x09092408; low nibble @0x0909240A..0C"),
        ("derived", "B_ACTION_NOTHING_FAINTED"): (nothing_fainted,
            "htas_absent_action:movs r1,#imm@0x08014132; "
            "turn_actions_nothing_fainted:0x0825006C = HandleAction_NothingIsFainted|1"),
        ("ram", "CHOSEN_ACTION_ADDR"): (literal(0x1412E),
            "htas_absent_action:LDR@0x0801412E pool@0x08014164 (HTAS case-0 absent path)"),
        ("ram", "BATTLE_CONTROLLER_EXEC_FLAGS_ADDR"): (exec_flags,
            "controller_exec_marker:LDR@0x1725A/0x1727C pools@0x17274/0x17290; "
            "OR/STR@0x17266..0x1726A,0x17284..0x1728A; "
            "controller_exec_reader:LDR@0x141DC pool@0x14234,word-test@0x141FC..0x14204"),
        ("derived", "SB2_OT_ID_OFFSET"): (ot_offsets[-1], "trainer_id:0xCC1E4 byte assembly +0xA..D"),
        ("rom", "EXPERIENCE_TABLES_ADDR"): (literal(0x3E850), "box_level:LDR@0x3E850 pool@0x3E894"),
        ("derived", "EXPERIENCE_TABLE_ENTRY_COUNT"): (row_bytes // 4, "box_level:0x3E85E..0x3E862 row stride / u32"),
        ("derived", "MAX_LEVEL"): (read(0x3E872, 2) & 255, "box_level:CMP@0x3E872"),
        ("rom", "BATTLE_MOVES_ADDR"): (literal(0x41026), "calculate_pp:LDR@0x41026 pool@0x4105C"),
        ("derived", "BATTLE_MOVE_ENTRY_SIZE"): (move_stride, "calculate_pp:0x41028..0x4102C index arithmetic"),
        ("derived", "BATTLE_MOVE_PP_OFFSET"): (pp_offset, "calculate_pp:LDRB@0x41030"),
        ("rom", "PP_UP_GET_MASK_ADDR"): (literal(0x41032), "calculate_pp:LDR@0x41032 pool@0x41060; bytes@0x25DEA1"),
        ("derived", "BASESTATS_GROWTH_RATE_OFFSET"): (growth_offset, "box_level:LDRB@0x3E85C"),
        ("rom", "HANDLE_TURN_ACTION_SELECTION_ADDR"): (literal(0x1070628),
            "action_callback_store:0x1070626..0x107062A; pool@0x10706DC; entry@0x14040 (Thumb)"),
        ("rom", "BEGIN_BATTLE_INTRO_ADDR"): (literal(0xD376),
            "intro_store_controllers:LDR@0xD374/0xD376 pools@0xD39C/0xD3A0 STR@0xD378; "
            "the BeginBattleIntro body is the intro_store_begin anchor (0x123C0, == FR)"),
        ("rom", "BEGIN_BATTLE_INTRO_DUMMY_ADDR"): (literal(0xD280),
            "intro_store_controllers:LDR@0xD27E/0xD280 pools@0xD2E4/0xD2E8 STR@0xD282"),
        ("rom", "BATTLE_INTRO_GET_MONS_DATA_ADDR"): (literal(0x123CE),
            "intro_store_begin:LDR@0x123CC/0x123CE pools@0x123DC/0x123E0 STR@0x123D0 (the tail of "
            "BeginBattleIntro); the data-request phase is the intro_getmons_body anchor (0x12FAC)"),
    }
    return {key: (value, f"rom:patch/build/slink_RR.gba sha1={RR_WITNESS_SHA1} {where}")
            for key, (value, where) in facts.items()}

SCHEMA = "gen3-profile-v1"

# ── pins (P0 card C0-2/C0-4, docs/gen3/research/pins_inventory.md) ───────────────
ROM_HASHES = {
    "firered": {"rom_sha1": "41cb23d8dccc8ebd7c649cd8fbb58eeace6e2fdc"},
    "leafgreen": {"rom_sha1": "574fa542ffebb14be69902d1d36f1ec0a4afd71e"},
    "radical_red": {"rom_sha1": "964f951a0fdaf209e4ea1344883ef0d557bb3a80",
                    "rom_md5": "8529f3a45d32bce4da637976fcf269d4"},
}

# pack -> [(title, profile key in GEN3.profiles, admitted)]
PACKS = {
    "gen3_frlg": [
        ("firered", "vanilla", True),
        ("leafgreen", "vanilla", True),
        ("firered_ap", "ap", False),
        ("emerald", "emerald", False),
    ],
    "gen3_rr": [
        ("radical_red", "radical_red", True),
    ],
}

# Every key the Lua tables carry, and the section it lands in.  A key that is not
# listed fails the run: the generator stays honest about what it understands.
#   ram      EWRAM/IWRAM addresses the client reads or writes
#   rom      ROM addresses (incl. SE_SONG_HEADERS, BASESTATS_ADDR, CB2_* callbacks)
#   derived  sizes, offsets, counts, modes and flags
SECTION = {
    # ── ram ──
    "PARTY_COUNT_ADDR": "ram", "PARTY_BASE": "ram",
    "ENEMY_COUNT_ADDR": "ram", "ENEMY_BASE": "ram",
    "BATTLE_TYPE_ADDR": "ram", "BATTLE_OUTCOME_ADDR": "ram", "BATTLE_MONS_ADDR": "ram",
    "BATTLER_PARTY_INDEXES_ADDR": "ram", "BATTLERS_COUNT_ADDR": "ram",
    "BATTLE_MAIN_FUNC_ADDR": "ram", "LOCKED_MOVES_ADDR": "ram",
    "GMAIN_ADDR": "ram", "SB1_PTR_ADDR": "ram", "SB2_PTR_ADDR": "ram", "PSP_PTR_ADDR": "ram",
    "SPECIAL_VAR_BOX_ID_ADDR": "ram", "SPECIAL_VAR_BOX_POS_ADDR": "ram",
    "TASKS_BASE_ADDR": "ram", "BATTLE_RESULTS_ADDR": "ram",
    "CHOSEN_MOVE_ADDRS": "ram", "CHOSEN_ACTION_ADDR": "ram", "CHOSEN_MOVE_ADDR": "ram",
    "BATTLE_COMM_ADDR": "ram", "BATTLE_STRUCT_PTR_ADDR": "ram",
    "POKEMON_STORAGE_BASE": "ram", "CFRU_BOX_NAME_BASE": "ram",
    "BALL_POCKET_ADDR": "ram", "TRAINER_OPPONENT_ADDR": "ram",
    "REAL_PARTY_BACKUP_ADDR": "ram",
    # ── rom ──
    "RETURN_FROM_BATTLE_ADDR": "rom", "SE_SONG_HEADERS": "rom", "BASESTATS_ADDR": "rom",
    "POST_BATTLE_WRITER_TASKS": "rom", "CB2_EVOLUTION_LOAD_ADDR": "rom",
    "CB2_EVOLUTION_BEGIN_ADDR": "rom", "CB2_EVOLUTION_UPDATE_ADDR": "rom",
    "CB2_TRADE_EVOLUTION_UPDATE_ADDR": "rom", "CFRU_BASESTATS_PTR": "rom",
    # ── derived ──
    "SB2_ENC_KEY_OFFSET": "derived", "SB1_BALL_POCKET_OFFSET": "derived",
    "SB1_BALL_POCKET_COUNT": "derived", "SB1_FLAGS_OFFSET": "derived",
    "SB1_VARS_OFFSET": "derived", "OVERWORLD_MODE": "derived",
    "BASESTATS_ENTRY_SIZE": "derived", "TASK_STRUCT_SIZE": "derived",
    "BASESTATS_ADDR_BY_GAME_CODE": "derived",
    "GMAIN_CB2_OFFSET": "derived",
    "BATTLE_RESULTS_PLAYER_FAINTS_OFF": "derived", "BATTLE_RESULTS_FOE_FAINTS_OFF": "derived",
    "PARTY_IN_SB1": "derived", "SB1_PARTY_BASE_OFFSET": "derived",
    "BATTLE_STRUCT_MOVE_TARGET_OFF": "derived", "BATTLE_STRUCT_CHOSEN_MOVE_POS_OFF": "derived",
    "CFRU_COMPRESSED_BOX": "derived", "COMPRESSED_MON_SIZE": "derived",
    "BOXES_PER_STORE": "derived", "CFRU_BOX_BASES": "derived", "BOX_NAMES_OFFSET": "derived",
    "BAG_IN_EWRAM": "derived", "BALL_POCKET_ENC": "derived",
    "OUTCOME_CAUGHT": "derived", "OUTCOME_RAN": "derived",
    "SE_NUZLOCKE_START": "derived", "SE_GAME_OVER": "derived",
    "SE_NEW_LINK": "derived", "SE_LINKED_KO": "derived",
    "CFRU_NO_ENCRYPT": "derived",
}


# ── the Lua subset parser ────────────────────────────────────────────────────────
_TOK = re.compile(r"""
      (?P<ws>\s+)
    | (?P<comment>--\[\[.*?\]\]|--[^\n]*)
    | (?P<str>"[^"\n]*")
    | (?P<num>0[xX][0-9A-Fa-f]+|\d+)
    | (?P<name>[A-Za-z_]\w*)
    | (?P<punct>[{}\[\],=+*./\-])
""", re.VERBOSE | re.DOTALL)

NIL = object()


class _Lex:
    """Cursor-based lexer: only the table being parsed is ever lexed."""

    def __init__(self, text: str, pos: int) -> None:
        self.text, self.pos, self._peeked = text, pos, None

    def _lex(self) -> tuple[str, str]:
        while True:
            m = _TOK.match(self.text, self.pos)
            if not m:
                sys.exit(f"gen_gen3_profile: cannot lex {SRC} at {self.text[self.pos:self.pos + 40]!r}")
            self.pos = m.end()
            if m.lastgroup not in ("ws", "comment"):
                return m.lastgroup, m.group()

    def peek(self) -> tuple[str, str]:
        if self._peeked is None:
            self._peeked = self._lex()
        return self._peeked

    def take(self) -> tuple[str, str]:
        tok, self._peeked = self.peek(), None
        return tok

    def expect(self, want: str) -> None:
        kind, val = self.take()
        if val != want:
            sys.exit(f"gen_gen3_profile: expected {want!r}, got {val!r} ({kind})")

    # value ::= table | string | true|false|nil | expr
    def value(self):
        kind, val = self.peek()
        if val == "{":
            return self.table()
        if kind == "str":
            self.take()
            return val[1:-1]
        if kind == "name" and val in ("true", "false", "nil"):
            self.take()
            return {"true": True, "false": False, "nil": NIL}[val]
        return self.expr()

    # expr ::= term ('+' term)*   |   term ::= num ('*' num)*
    def expr(self) -> int:
        total = self.term()
        while self.peek()[1] == "+":
            self.take()
            total += self.term()
        return total

    def term(self) -> int:
        val = self.number()
        while self.peek()[1] == "*":
            self.take()
            val *= self.number()
        return val

    def number(self) -> int:
        kind, val = self.take()
        if kind != "num":
            sys.exit(f"gen_gen3_profile: expected a number, got {val!r}")
        return int(val, 16) if val[:2].lower() == "0x" else int(val)

    def table(self):
        """A Lua table literal.  Positional entries, or keys 1..n, come back as a list;
        anything else as a dict keyed by the literal key (stringified for JSON)."""
        self.expect("{")
        items: list[tuple[object, object]] = []
        while True:
            kind, val = self.peek()
            if val == "}":
                self.take()
                break
            if val == "[":                      # [16] = ...
                self.take()
                key = self.expr()
                self.expect("]")
                self.expect("=")
                items.append((key, self.value()))
            elif kind == "name" and val not in ("true", "false", "nil"):
                self.take()
                self.expect("=")
                items.append((val, self.value()))
            else:                               # positional entry
                items.append((None, self.value()))
            if self.peek()[1] == ",":
                self.take()
        keys = [k for k, _ in items]
        if not items:
            return {}
        if all(k is None for k in keys) or keys == list(range(1, len(items) + 1)):
            return [v for _, v in items]
        return {str(k): v for k, v in items}


def _table_at(text: str, assignment: str):
    """Parse the table literal assigned by `assignment`.  Anchored at line start so the
    prose copy of `GEN3.profiles.emerald = {...}` in a comment is not mistaken for it."""
    m = re.search(r"^" + re.escape(assignment) + r"\s*=\s*\{", text, re.M)
    if not m:
        sys.exit(f"gen_gen3_profile: {SRC} has no `{assignment} = {{`")
    return _Lex(text, m.end() - 1).table()


def parse_profiles(text: str) -> dict:
    """{profile key: table} from GEN3.profiles = {...} plus the additive .emerald."""
    out = {k: v for k, v in _table_at(text, "GEN3.profiles").items() if v is not NIL}
    out["emerald"] = _table_at(text, "GEN3.profiles.emerald")
    return out


# ── the companion-patch native ABI (gen3_rr only) ────────────────────────────────
# C5-6 deleted archive/gen3-old-client:lua/mailbox.lua and archive/gen3-old-client:lua/peer_ghost_npc.lua (the old Lua client's copies of the
# ABI). The companion patch is BUILT from patch/src/handlers.c, so that C source -- not a Lua
# mirror of it -- is the actual authority; every name below is read out of it, never re-typed.
# Two naming conventions collide here on purpose: every MB.OP_* opcode already shares its exact
# name with handlers.c's opcode enum (both say "OP_PING"), so those are looked up by name alone;
# everything else predates this generator and keeps its old Lua-side name via an explicit map to
# whatever handlers.c calls the same literal (e.g. MB.BASE is handlers.c's MAILBOX_ADDR).
MAILBOX_C_SYMBOL = {
    "BASE": "MAILBOX_ADDR", "SIG": "SLNK_SIG", "ABI": "ABI_VER",
    "BLOB_BUF": "SLINK_BLOB_BUF", "TEXT_BUF": "SLINK_TEXT_BUF", "MENU_BUF": "SLINK_MENU_BUF",
    "BATTLE_NOTIF": "BN", "TN_ENABLE": "TN", "CALC_OFF": "SLINK_CALC_OFF", "INFO": "SI",
    "INFO_MAXLINES": "INFO_ROWS", "INFO_PAGESLOT": "INFO_PAGE_SLOT", "INFO_BAR_W": "BAR_W",
    "EVR": "EV", "GH": "GH", "GHOST_PAL_BUF": "GHOST_PAL_BUF", "GPLAYER_AVATAR": "gPlayerAvatar",
    "SW": "SW", "EV_PLAYER_FAINT": "EV_PLAYER_FAINT", "EV_FOE_FAINT": "EV_FOE_FAINT",
    "EV_OUTCOME": "EV_OUTCOME", "EV_PARTY_ADD": "EV_PARTY_ADD", "EV_EVOLVE": "EV_EVOLVE",
}
# ghost/object-event addresses (post-RC feature; kept for the same byte-identical reason as
# everything else above -- native.lua doesn't read these today, but the profile shape must not
# change out from under a future consumer). Every one is ALSO a plain handlers.c #define.
GHOST_C_SYMBOL = {
    "OBJECT_EVENTS_BASE": "gObjectEvents", "CB2_OVERWORLD": "CB2_OVERWORLD",
    "SPRITES_BASE": "gSprites", "OBJ_PALETTE_BUF": "gPlttBufferUnfaded_OBJ",
    "CAMERA_Y_ADDR": "gSpriteCoordOffsetY",
}
# every MB.OP_* name is spelled identically in handlers.c's opcode enum
MAILBOX_OPCODES = (
    "OP_PING", "OP_FORCE_FAINT", "OP_FORCE_MOVE", "OP_CREATE_MON", "OP_FORCE_MOVE_SLOT",
    "OP_SPAWN_PEER_NPC", "OP_DESPAWN_PEER_NPC", "OP_SHOW_MESSAGE", "OP_PLAY_FANFARE",
    "OP_ARM_PEER_INTERACT", "OP_GHOST_SPAWN", "OP_GHOST_CLEAR", "OP_SET_ENEMY_PARTY",
    "OP_SHOW_MENU", "OP_SET_PARTY_MON", "OP_PLAY_SE", "OP_CHOOSE_PARTY_MON", "OP_TRADE_SCENE",
    "OP_SHOW_CHOICES", "OP_SHOW_BATTLE_MESSAGE", "OP_DEPOSIT_MON", "OP_WITHDRAW_MON",
    "OP_MEMORIALIZE", "OP_SHOW_INFO", "OP_RIVAL_SWAP",
)

# `#define NAME <literal>` or the pointer-cast form `#define NAME ((Type *)<literal>)`.
_CDEFINE_RE = (r"^#define\s+{name}\s+(?:\(\(\s*[A-Za-z_ ]+\*\)\s*)?"
              r"(0[xX][0-9A-Fa-f]+|\d+)u?\)?\s*(?://.*|/\*.*)?$")


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _c_define(text: str, cname: str) -> tuple[int, int]:
    """(value, match offset) of `#define cname ...` in handlers.c (plain or pointer-cast)."""
    m = re.search(_CDEFINE_RE.format(name=re.escape(cname)), text, re.M)
    if not m:
        sys.exit(f"gen_gen3_profile: {HANDLERS_SRC} no longer defines {cname}")
    lit = m.group(1)
    return (int(lit, 16) if lit[:2].lower() == "0x" else int(lit)), m.start()


def native_block() -> dict:
    values: dict[str, int] = {}
    src: dict[str, str] = {}
    text = (REPO / HANDLERS_SRC).read_text(encoding="utf-8", errors="replace")

    def put(name: str, cname: str) -> int:
        value, off = _c_define(text, cname)
        values[name] = value
        src[name] = f"{HANDLERS_SRC}:{_line_of(text, off)} ({cname})"
        return value

    for name, cname in MAILBOX_C_SYMBOL.items():
        put(name, cname)
    for name, cname in GHOST_C_SYMBOL.items():
        put(name, cname)
    for op in MAILBOX_OPCODES:
        m = re.search(rf"\b{op}\s*=\s*(\d+)", text)
        if not m:
            sys.exit(f"gen_gen3_profile: {HANDLERS_SRC} no longer defines {op}")
        values[op] = int(m.group(1))
        src[op] = f"{HANDLERS_SRC}:{_line_of(text, m.start())} (opcode enum)"
    # GMAIN_CB2_PTR = gMain + 4 (gMain.callback2 -- archive/gen3-old-client:lua/peer_ghost_npc.lua used to read this directly)
    gmain, gmain_off = _c_define(text, "gMain")
    values["GMAIN_CB2_PTR"] = gmain + 4
    src["GMAIN_CB2_PTR"] = f"{HANDLERS_SRC}:{_line_of(text, gmain_off)} (gMain + 4, callback2)"
    # PI_COUNT = SlinkState.pi_count -- SS + 3 (struct field order: _rsvd0, pi_armed, pi_oe, pi_count)
    ss, ss_off = _c_define(text, "SS")
    values["PI_COUNT"] = ss + 3
    src["PI_COUNT"] = f"{HANDLERS_SRC}:{_line_of(text, ss_off)} (SlinkState.pi_count, SS + 3)"
    # EVR_PRIM = EvRing.prim -- EV + 6 (struct field order: wr,rd,overflow,inb,pfc,ofc,prim)
    values["EVR_PRIM"] = values["EVR"] + 6
    src["EVR_PRIM"] = src["EVR"] + " (EvRing.prim, EV + 6)"
    # INFO_LINEW: SlinkInfo.line[8][N] row width is a struct array dimension, not a #define.
    m = re.search(r"volatile u8 line\[8\]\[(\d+)\]", text)
    if not m:
        sys.exit(f"gen_gen3_profile: {HANDLERS_SRC} no longer carries SlinkInfo.line[8][N]")
    values["INFO_LINEW"] = int(m.group(1))
    src["INFO_LINEW"] = f"{HANDLERS_SRC}:{_line_of(text, m.start())} (SlinkInfo.line[8][N])"
    # LOCALID: the ghost's sentinel localId (0xF0), checked inline rather than named -- its
    # documented neighbor TN_LOCALID (0xF1) calls it out: "exclusive sentinel (ghost uses 0xF0)".
    m = re.search(r"R8\(oo \+ 0x08\) == (0x[0-9A-Fa-f]+)u", text)
    if not m:
        sys.exit(f"gen_gen3_profile: {HANDLERS_SRC} no longer checks the ghost sentinel localId")
    values["LOCALID"] = int(m.group(1), 16)
    src["LOCALID"] = f"{HANDLERS_SRC}:{_line_of(text, m.start())} (ghost sentinel localId check)"

    values["_src"] = src  # type: ignore[assignment]
    return values


# ── assembly ─────────────────────────────────────────────────────────────────────
def _thumb_keys(rom: dict) -> list[str]:
    """ROM keys whose literal already carries the Thumb bit (bit 0 set).  The values are
    kept verbatim -- gTasks[].func / gMain.callback2 are read from RAM with the +1, so
    re-stripping here would make the profile disagree with what the client compares."""
    out = []
    for key, val in rom.items():
        vals = val if isinstance(val, list) else [val]
        nums = [v for v in vals if isinstance(v, int)]
        if nums and all(v & 1 for v in nums):
            out.append(key)
    return sorted(out)


def _title(profile: dict, title: str, key: str, admitted: bool) -> dict:
    sections: dict[str, dict] = {"ram": {}, "rom": {}, "derived": {}}
    for name, val in profile.items():
        section = SECTION.get(name)
        if section is None:
            sys.exit(f"gen_gen3_profile: {key}.{name} is not classified in SECTION")
        sections[section][name] = None if val is NIL else val
    out = {
        "variant": key,
        "admitted": admitted,
        "rom_thumb": _thumb_keys(sections["rom"]),
        **sections,
    }
    out.update(ROM_HASHES.get(title, {}))
    return out


# ── C4-LGSE: LeafGreen ROM addresses the shared `vanilla` table gets wrong ─────────
# Same bug class as the BASESTATS_ADDR override above: the Lua `vanilla` profile is
# one table shared by both titles, so it can only carry one literal per key -- and it
# carries FireRed's for SE_SONG_HEADERS and the evolution-scene CB2s.  Translate by
# symbol NAME (FR address -> FR symbol -> LG address for that symbol), never by a
# fixed byte offset, and hard-fail on any ambiguity rather than guess.
_SYM_LINE = re.compile(r"^([0-9a-fA-F]{8})\s+[a-zA-Z]\s+[0-9a-fA-F]+\s+(\S+)$", re.M)


def _sym_index(text: str) -> tuple[dict[int, list[str]], dict[str, list[int]]]:
    """{address: [symbol names]} and {name: [addresses]} for a pret .sym file's text.
    `.gcc2_compiled.` pseudo-symbols are excluded from the name index -- never a real
    translation target -- but kept in the address index so callers can still see (and
    reject) an address that names more than one thing."""
    by_addr: dict[int, list[str]] = {}
    by_name: dict[str, list[int]] = {}
    for m in _SYM_LINE.finditer(text):
        addr, name = int(m[1], 16), m[2]
        by_addr.setdefault(addr, []).append(name)
        if not name.startswith("."):
            by_name.setdefault(name, []).append(addr)
    return by_addr, by_name


def _real_names_at(by_addr: dict, addr: int) -> list[str]:
    return [n for n in by_addr.get(addr, []) if not n.startswith(".")]


def _resolve_symbol(by_addr: dict, val: int, is_thumb: bool) -> tuple[list[str], int]:
    """Resolve `val` to (real symbol names there, the address they're at). Looks up the EXACT
    address first -- a data symbol can legitimately be odd (gPPUpGetMask sits at 0x0825DEA1 in
    FireRed; that is not a Thumb pointer) -- and only strips bit 0 when the field is a known
    Thumb pointer (`is_thumb`, from `rom_thumb` membership) AND the exact odd address names
    nothing on its own."""
    names = _real_names_at(by_addr, val)
    if names or not is_thumb or not (val & 1):
        return names, val
    stripped = val & ~1
    return _real_names_at(by_addr, stripped), stripped


def _unique_global_name(by_addr: dict, by_name: dict, val: int, is_thumb: bool,
                        sym_file: str, label: str) -> tuple[str, int]:
    """The one real symbol naming `val`, hard-failing unless it is unique both AT that address
    (no aliases sharing the address) and GLOBALLY (no duplicate statics elsewhere in the file)
    -- a name that recurs elsewhere can't be trusted to mean the same thing at every occurrence,
    so picking a counterpart by name alone could silently pick the wrong one."""
    names, addr = _resolve_symbol(by_addr, val, is_thumb)
    if len(names) != 1:
        sys.exit(f"gen_gen3_profile: {label}: {sym_file} names {names or 'no'} real symbols "
                 f"at 0x{addr:08X} (need exactly one)")
    name = names[0]
    if len(by_name.get(name, [])) != 1:
        sys.exit(f"gen_gen3_profile: {label}: {sym_file} has {len(by_name[name])} addresses "
                 f"named {name} (need a globally-unique symbol, not just one unique at "
                 f"0x{addr:08X})")
    return name, addr


def _translate_fr_default(fr_by_addr: dict, fr_by_name: dict, lg_by_name: dict, fr_val: int,
                          is_thumb: bool, label: str) -> tuple[int, str]:
    """FR ROM address -> LG's address for the same, globally-unique symbol, keeping the Thumb
    bit `is_thumb` fields carry."""
    name, _ = _unique_global_name(fr_by_addr, fr_by_name, fr_val, is_thumb,
                                  "pokefirered.sym", label)
    addrs = lg_by_name.get(name, [])
    if len(addrs) != 1:
        sys.exit(f"gen_gen3_profile: {label}: pokeleafgreen.sym has {len(addrs)} addresses "
                 f"for {name} (need exactly one)")
    return addrs[0] | (fr_val & 1 if is_thumb else 0), name


# Paths the guard below must never flag: known cases where a leafgreen value legitimately
# equals FireRed's without being a copy-paste bug -- each verified directly (never by name
# lookup alone, which is exactly what the stricter guard now refuses to trust).
_GUARD_EXCLUDE_PATHS = {
    # Keyed by FireRed's own game code -- FR's value IS the right value here.
    "derived.BASESTATS_ADDR_BY_GAME_CODE.BPRE",
    # Task_LaunchLvlUpAnim is a `static` helper repeated 3x across translation units in BOTH
    # .sym files -- not globally unique by name, so the stricter guard correctly refuses to
    # resolve it by name alone. Direct address comparison (not name lookup) confirms the
    # specific instance this task writer targets did not move between builds:
    #   pokefirered.sym:2013/9168/12833  -> 0x08030238 / 0x080e8190 / 0x08156c68
    #   pokeleafgreen.sym:2013/9170/12835 -> 0x08030238 / 0x080e8168 / 0x08156c44
    # Both name 0x08030238, and it is the one POST_BATTLE_WRITER_TASKS[0] carries.
    "rom.POST_BATTLE_WRITER_TASKS[0]",
}


def _walk_rom_addrs(lg_val, fr_val, path: str):
    """Yield (path, lg value, fr value) for every int in `lg_val` that sits in the ROM
    address range, recursing into dicts/lists (e.g. SE_SONG_HEADERS, POST_BATTLE_WRITER_TASKS).
    `fr_val` is the value at the same path in FireRed's entry, or None where it has none."""
    if isinstance(lg_val, dict):
        for k, v in lg_val.items():
            yield from _walk_rom_addrs(v, fr_val.get(k) if isinstance(fr_val, dict) else None,
                                       f"{path}.{k}")
    elif isinstance(lg_val, list):
        for i, v in enumerate(lg_val):
            fv = fr_val[i] if isinstance(fr_val, list) and i < len(fr_val) else None
            yield from _walk_rom_addrs(v, fv, f"{path}[{i}]")
    elif isinstance(lg_val, int) and 0x08000000 <= lg_val <= 0x09FFFFFF:
        yield path, lg_val, fr_val


def _guard_leafgreen_not_copied(lg_entry: dict, fr_entry: dict, fr_by_addr: dict,
                                fr_by_name: dict, lg_by_name: dict) -> None:
    """C4-LGSE: fail the build -- don't ship -- the next time a leafgreen ROM address is left at
    FireRed's default. Fail-CLOSED: any ambiguity (an FR address naming more than one symbol, an
    FR or LG symbol name that recurs elsewhere) is treated as unresolved evidence of a bug, not
    silently accepted. An earlier version of this guard resolved a name at an address without
    checking global uniqueness on either side, and unconditionally stripped bit 0 before looking
    an address up; that let an aliased FR address, a duplicate LG static, and a genuinely-odd data
    address (gPPUpGetMask) all slip a copied value past the guard. A value only trips this if it
    (a) still equals FireRed's value at the same path, (b) FireRed's address names exactly one
    real, globally-unique symbol, and (c) that same symbol is NOT at the same address in
    pokeleafgreen.sym -- positive, unambiguous evidence LG disagrees, not just two ROMs
    coincidentally sharing an address (e.g. BeginBattleIntro) or a name that recurs and so
    proves nothing (e.g. a `static` helper repeated across translation units)."""
    thumb_keys = set(lg_entry.get("rom_thumb", ()))
    for section in ("ram", "rom", "derived"):
        for key, lg_val in lg_entry[section].items():
            fr_val = fr_entry[section].get(key)
            is_thumb = section == "rom" and key in thumb_keys
            for path, val, fr_leaf in _walk_rom_addrs(lg_val, fr_val, f"{section}.{key}"):
                if path in _GUARD_EXCLUDE_PATHS or val != fr_leaf:
                    continue
                names, addr = _resolve_symbol(fr_by_addr, val, is_thumb)
                if not names:
                    continue  # nothing to resolve -- no evidence either way
                if len(names) > 1:
                    sys.exit(f"gen_gen3_profile: leafgreen.{path} = 0x{val:08X}: pokefirered.sym "
                             f"names {names} at 0x{addr:08X} -- ambiguous (aliases); translate "
                             f"explicitly, or add a _GUARD_EXCLUDE_PATHS entry with the reason, "
                             f"instead of leaving this copied")
                name = names[0]
                if len(fr_by_name.get(name, [])) != 1:
                    sys.exit(f"gen_gen3_profile: leafgreen.{path} = 0x{val:08X}: pokefirered.sym "
                             f"has {len(fr_by_name[name])} addresses named {name} -- not "
                             f"globally unique; translate explicitly instead of leaving this "
                             f"copied")
                lg_addrs = lg_by_name.get(name, [])
                if len(lg_addrs) != 1:
                    sys.exit(f"gen_gen3_profile: leafgreen.{path} = 0x{val:08X}: "
                             f"pokeleafgreen.sym has {len(lg_addrs)} addresses named {name} -- a "
                             f"duplicate static means an address match at 0x{addr:08X} proves "
                             f"nothing; translate explicitly instead of leaving this copied")
                if lg_addrs[0] != addr:
                    sys.exit(f"gen_gen3_profile: leafgreen.{path} = 0x{val:08X} still equals "
                             f"FireRed's value, and FireRed's {name} sits at a different address "
                             f"(0x{lg_addrs[0]:08X}) in pokeleafgreen.sym -- translate it "
                             f"(see C4-LGSE)")


def build(pack: str, profiles: dict, source: dict) -> dict:
    out = {
        "schema": SCHEMA,
        "generator": "tools/gen_gen3_profile.py",
        "pack": pack,
        "source": source,
        "titles": {t: _title(profiles[k], t, k, adm) for t, k, adm in PACKS[pack]},
    }
    if pack == "gen3_frlg":
        # C4-LGSE: FireRed's own index, used below to translate leafgreen's copied ROM
        # addresses and to guard against the next one nobody translates.
        fr_by_addr, fr_by_name = _sym_index(
            (REPO / "data/gen3/pret/pokefirered.sym").read_text(encoding="utf-8"))
        lg_by_name: dict[str, list[int]] = {}
        for title in ("firered", "leafgreen"):
            entry = out["titles"][title]
            path = f"data/gen3/pret/poke{title}.sym"
            text = (REPO / path).read_text(encoding="utf-8")
            matches = list(re.finditer(
                r"^([0-9a-fA-F]{8})\s+g\s+[0-9a-fA-F]+\s+gPokemonStorage$", text, re.M))
            if len(matches) != 1:
                sys.exit(f"gen_gen3_profile: {path} must name exactly one gPokemonStorage")
            match = matches[0]
            entry["ram"]["POKEMON_STORAGE_BASE"] = int(match[1], 16)
            entry["_src"] = {
                "ram.POKEMON_STORAGE_BASE":
                    f"{path}:{_line_of(text, match.start())} (gPokemonStorage; {PRET_PIN})",
            }
            for name, (value, where) in FRLG_DERIVED.items():
                entry["derived"][name] = value
                entry["_src"][f"derived.{name}"] = where
            for (section, name), symbol in FRLG_SYM_ADDR.items():
                sym_matches = list(re.finditer(
                    rf"^([0-9a-fA-F]{{8}})\s+g\s+[0-9a-fA-F]+\s+{re.escape(symbol)}$", text, re.M))
                if len(sym_matches) != 1:
                    sys.exit(f"gen_gen3_profile: {path} must name exactly one {symbol}")
                sym_match = sym_matches[0]
                entry[section][name] = int(sym_match[1], 16)
                entry["_src"][f"{section}.{name}"] = (
                    f"{path}:{_line_of(text, sym_match.start())} ({symbol}; {PRET_PIN})")
            for (section, name), symbol in FRLG_SYM_THUMB_ADDR.items():
                sym_matches = list(re.finditer(
                    rf"^([0-9a-fA-F]{{8}})\s+[glt]\s+[0-9a-fA-F]+\s+{re.escape(symbol)}$", text, re.M))
                if len(sym_matches) != 1:
                    sys.exit(f"gen_gen3_profile: {path} must name exactly one {symbol}")
                sym_match = sym_matches[0]
                entry[section][name] = int(sym_match[1], 16) | 1
                entry["_src"][f"{section}.{name}"] = (
                    f"{path}:{_line_of(text, sym_match.start())} "
                    f"({symbol}|1, the Thumb form gBattleMainFunc stores; {PRET_PIN})")
                if name in INTRO_THUMB_KEYS:
                    entry["rom_thumb"].append(name)
                    entry["rom_thumb"].sort()
            # C4-3c separately requested correction: the shared legacy vanilla
            # table carries FR's default; LG must publish its own table address.
            if title == "leafgreen":
                match = re.search(r"^([0-9a-fA-F]{8})\s+g\s+[0-9a-fA-F]+\s+gSpeciesInfo$", text, re.M)
                if not match:
                    raise ValueError("LeafGreen gSpeciesInfo symbol missing")
                entry["rom"]["BASESTATS_ADDR"] = int(match[1], 16)
                entry["_src"]["rom.BASESTATS_ADDR"] = (
                    f"{path}:{_line_of(text, match.start())} (gSpeciesInfo; {PRET_PIN})")
                # C4-LGSE: the same "shared vanilla table carries FR's default" bug, for
                # SE_SONG_HEADERS and the evolution CB2s. Translate each by symbol name.
                _, lg_by_name = _sym_index(text)
                new_headers = {}
                for sid, fr_val in entry["rom"]["SE_SONG_HEADERS"].items():
                    # even addresses, never Thumb-tagged (SongHeader table entries, not funcs)
                    new_val, name = _translate_fr_default(
                        fr_by_addr, fr_by_name, lg_by_name, fr_val, False,
                        f"rom.SE_SONG_HEADERS[{sid}]")
                    new_headers[sid] = new_val
                    entry["_src"][f"rom.SE_SONG_HEADERS.{sid}"] = (
                        f"{path} {name} translated by symbol name from pokefirered.sym "
                        f"0x{fr_val:08X} ({PRET_PIN})")
                entry["rom"]["SE_SONG_HEADERS"] = new_headers  # a fresh dict: FR's entry
                # still points at the original, un-translated dict object -- never mutate it.
                for cb2_key in ("CB2_EVOLUTION_LOAD_ADDR", "CB2_EVOLUTION_BEGIN_ADDR",
                                "CB2_EVOLUTION_UPDATE_ADDR", "CB2_TRADE_EVOLUTION_UPDATE_ADDR"):
                    fr_val = entry["rom"][cb2_key]
                    new_val, name = _translate_fr_default(
                        fr_by_addr, fr_by_name, lg_by_name, fr_val, True, f"rom.{cb2_key}")
                    entry["rom"][cb2_key] = new_val
                    entry["_src"][f"rom.{cb2_key}"] = (
                        f"{path} {name} translated by symbol name from pokefirered.sym "
                        f"0x{fr_val:08X} ({PRET_PIN})")
        # C4-LGSE guard: the next FR-default value nobody translated must fail the build.
        _guard_leafgreen_not_copied(out["titles"]["leafgreen"], out["titles"]["firered"],
                                    fr_by_addr, fr_by_name, lg_by_name)
    if pack == "gen3_rr":
        # The existing RR detector explicitly rejects party counts above this limit.
        text = (REPO / SRC).read_text(encoding="utf-8")
        detector = re.search(r"^local function _detectRR\(\)(.*?)^end", text, re.M | re.S)
        match = re.search(r"^    if partyCount > (\d+) then return false end$",
                          detector[1] if detector else "", re.M)
        if not match:
            sys.exit(f"gen_gen3_profile: {SRC} no longer carries the RR party capacity check")
        entry = out["titles"]["radical_red"]
        entry["derived"]["PARTY_CAPACITY"] = int(match[1])
        entry["_src"] = {
            "derived.PARTY_CAPACITY":
                f"{SRC}:{_line_of(text, detector.start(1) + match.start())} (_detectRR partyCount limit)",
        }
        # The old client's radical_red table still ships 0x03003840 / 0x03003838 for
        # SB1_PTR_ADDR / SB2_PTR_ADDR.  Those are not the pointers: both are literal-pool
        # constants inside IntrMain_Buffer (the DMA'd intr_main blob), correct on today's RR only
        # because its save-block offset is fixed at 0.  The values stay, because every Lua
        # literal has to survive at its key, and the NEW client reads the ROM-derived
        # write_checkpoint.pointers.gSaveBlock1Ptr instead (card C3-33) -- so the legacy address
        # is recorded here as the documented limit it is rather than silently inherited.
        legacy = entry["ram"].get("SB1_PTR_ADDR")
        hits = [m.start() for m in
                re.finditer(rf"^\s*SB1_PTR_ADDR\s*=\s*0x{legacy:08X}\s*,", text, re.M)
                ] if isinstance(legacy, int) else []
        if len(hits) != 1:
            sys.exit(f"gen_gen3_profile: {SRC} must spell the RR SB1_PTR_ADDR "
                     f"0x{legacy:X} exactly once (found {len(hits)})")
        entry["_src"]["ram.SB1_PTR_ADDR"] = (
            f"{SRC}:{_line_of(text, hits[0])} (the old client's address, kept for parity: it is "
            "a literal-pool constant inside IntrMain_Buffer, not the pointer -- the new client "
            "reads write_checkpoint.pointers.gSaveBlock1Ptr, which is ROM-derived)")
        for name, (value, where) in RR_DERIVED.items():
            entry["derived"][name] = value
            entry["_src"][f"derived.{name}"] = where
        for (section, name), (value, where) in rr_rom_facts().items():
            if name in entry[section] and entry[section][name] != value:
                raise ValueError(f"RR binary fact would replace existing {section}.{name}")
            entry[section][name] = value
            entry["_src"][f"{section}.{name}"] = where
            if section == "rom" and name in INTRO_THUMB_KEYS:
                entry["rom_thumb"].append(name)
        entry["rom_thumb"].append("HANDLE_TURN_ACTION_SELECTION_ADDR")
        entry["rom_thumb"].sort()
        entry["_rom_anchors"] = {
            name: {"rom_offset": off, "expected_hex": raw.upper()}
            for name, (off, raw) in RR_ROM_ANCHORS.items()
        }
        out["native"] = native_block()
    return out


def source_block(text: str) -> dict:
    head = subprocess.run(["git", "log", "-1", "--format=%H", "--", SRC],
                          cwd=REPO, capture_output=True, text=True).stdout.strip()
    return {
        "file": SRC,
        # the last commit that touched the source table, not the branch tip: a profile that
        # nothing changed must stay byte-identical so --check means "stale", not "rebased"
        "git_head": head or "unknown",
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }


def render(profile: dict) -> str:
    return json.dumps(profile, indent=2, sort_keys=True) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="exit 1 if a committed profile differs from a fresh generation")
    args = ap.parse_args()

    rr_witness = REPO / "patch/build/slink_RR.gba"
    if rr_witness.exists():
        rr_rom_facts(rr_witness.read_bytes())

    text = (REPO / SRC).read_text(encoding="utf-8", errors="replace")
    profiles = parse_profiles(text)
    source = source_block(text)
    stale = []
    for pack in PACKS:
        out = REPO / "data" / "games" / pack / "profile.json"
        rendered = render(build(pack, profiles, source))
        if args.check:
            current = out.read_text(encoding="utf-8") if out.exists() else ""
            if current != rendered:
                stale.append(str(out.relative_to(REPO)).replace("\\", "/"))
            continue
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(rendered, encoding="utf-8", newline="\n")
        titles = json.loads(rendered)["titles"]
        print(f"wrote data/games/{pack}/profile.json: " + ", ".join(
            f"{t} ram={len(v['ram'])} rom={len(v['rom'])} derived={len(v['derived'])}"
            for t, v in titles.items()))
    if stale:
        print("stale (run tools/gen_gen3_profile.py): " + ", ".join(stale), file=sys.stderr)
        return 1
    if args.check:
        print("data/games/gen3_{frlg,rr}/profile.json are current")
    return 0


if __name__ == "__main__":
    sys.exit(main())
