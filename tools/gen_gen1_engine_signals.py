#!/usr/bin/env python3
"""Generate data/games/gen1_purergb/engine_signals.json from the pinned pureRGB source + built ROMs.

Every row is a bus-exec hook site the Gen 1 client arms (lua/gen1/signals.lua): the client
verifies `expected_hex` at `address` in the ROM domain, fires at PC == address + capture_offset
with `bank` selected, and snapshots the WRAM symbols in `point`. A row is emitted only when

  1. the anchor symbol resolves in the title's .sym (data/purergb/*.sym, M0 build),
  2. the pinned source (SLINK_PURERGB_SRC, HEAD == data/purergb_sources.lock.json) still
     contains the text the row was derived from (`assert`),
  3. the bytes sliced from the built ROM match `shape` — opcodes plus operands resolved from
     the .sym. Each title is proven against its own .sym + ROM: anchors are shared across
     red/blue/green (docs/purergb/research/s1/REPORT.md §1) but bank-1 operands are not
     (`_RemovePokemon` is 01:7792/7793/7798 in red/blue/green), so rows may differ per title.

Any failure exits non-zero and writes nothing. Offsets follow docs/purergb/research/p2/
site_crossref.md (the *_corrected rows; S1's capture_offset is 0 = anchor is the hook).

    python tools/gen_gen1_engine_signals.py            # rewrite
    python tools/gen_gen1_engine_signals.py --check    # exit 1 if the committed file is stale
    python tools/gen_gen1_engine_signals.py --kind overlay
        engine_signals_overlay.json for the SLink companion build (the "purergb_overlay"
        foundation: data/purergb/*_slink.sym + the overlay ROMs). Same kinds and points; every
        expected_hex is re-sliced from the overlay ROM (ROM0/bank growth relocates sites by
        design), and the rows whose source the overlay rewrites carry OVERLAY overrides.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
import gen1_foundation as F  # noqa: E402

FOUNDATION = "purergb"
SCHEMA = "rby-engine-signal-sites-v1"

# WRAM the client snapshots at each hook (lua/gen1/signals.lua S.KINDS point functions).
BATTLE = ["wPartyCount", "wCurMap", "wIsInBattle", "wPlayerMonNumber", "wBattleMonHP", "wBattleMonSpecies",
          "wMonDataLocation", "wCurPartySpecies", "wCurEnemyLevel"]
OPPONENT = ["wCurOpponent", "wEnemyMonSpecies2", "wCurEnemyLevel", "wBattleType", "wIsInBattle", "wCurMap",
            "wLinkState"]
ACQUISITION = ["wIsInBattle", "wMonDataLocation", "wCurPartySpecies", "wCurEnemyLevel", "wCurMap", "wPartyCount"]
STORAGE = ["wWhichPokemon", "wPartyCount", "wBoxCount", "wCurrentBoxNum", "wPartyMonOT", "wPartyMonNicks",
           "wBoxMonOT", "wBoxMonNicks"]
NPC_TRADE = ["wWhichPokemon", "wInGameTradeGiveMonSpecies", "wInGameTradeReceiveMonSpecies", "wPartyCount"]
CABLE = ["wWhichPokemon", "wTradedPlayerMonSpecies", "wTradedEnemyMonSpecies", "wPartyCount"]
APEX = ["wUsedItemOnWhichPokemon", "wWhichPokemon", "wPartyCount"]
SAVE = ["wSaveFileStatus"]

CORE = "engine/battle/core.asm"
ITEMS = "engine/items/item_effects.asm"
TRADES = "engine/events/in_game_trades.asm"
CABLE_CLUB = "engine/link/cable_club.asm"
BILLS_PC = "engine/pokemon/bills_pc.asm"
SPECIES = "engine/pokemon/change_mon_species.asm"
OAKS = "scripts/OaksLab.asm"

# `shape`: space-separated tokens checked against the ROM slice from the anchor: `XX` a byte,
# `{sym}` the 16-bit little-endian address of sym, `{bank:sym}` its bank, `{lo:sym}` its low byte.
# `prelude`: (symbol offset, shape) proving the instruction the hook follows (emitted, client-optional).
# kind: _site(symbol, off, cap, len, point, source, assert_, shape[, prelude])


def _site(**row) -> dict:
    return row


SITES: dict[str, dict] = {
    # --- the 17 vanilla kinds, pureRGB anchors -------------------------------------------------
    "add_party_mon": _site(
        symbol="AddPartyMon", off=0, cap=0, len=8, point=ACQUISITION, source="home/move_mon.asm",
        assert_="AddPartyMon::\n\tpush hl\n\tpush de\n\tpush bc\n\tfarcall _AddPartyMon",
        shape="E5 D5 C5 06 {bank:_AddPartyMon} 21 {_AddPartyMon}"),
    "bag_received": _site(  # anchor .done+0 (the 9-byte epilogue), hook its `ret` at +8, as vanilla
        symbol="AddItemToInventory_.done", off=0, cap=8, len=9, source="engine/items/inventory.asm",
        point=["wCurItem", "wItemQuantity", "wNumBagItems"],
        assert_=".done\n\tpop hl\n\tpop de\n\tpop bc\n\tpop bc\n\tld a, b\n\tld [wItemQuantity], a",
        shape="E1 D1 C1 C1 78 EA {wItemQuantity} C9"),
    "battle_begin": _site(
        symbol="InitBattleCommon", off=0, cap=0, len=8, point=OPPONENT, source=CORE,
        assert_="InitBattleCommon:\n;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;\n; shinpokerednote: ADDED: store PKMN Levels"
                " at the beginning of the Battle.\n\tfarcall StorePKMNLevels",
        shape="06 {bank:StorePKMNLevels} 21 {StorePKMNLevels} C7"),
    "battle_end": _site(
        symbol="EndOfBattle", off=0, cap=0, len=8, point=OPPONENT + ["wBattleResult"],
        source="engine/battle/end_of_battle.asm",
        assert_="EndOfBattle:\n\tld a, [wLinkState]\n\tcp LINK_STATE_BATTLING\n\tjr nz, .notLinkBattle",
        shape="FA {wLinkState} FE 04 20"),
    "battle_faint": _site(
        symbol="RemoveFaintedPlayerMon", off=0, cap=0, len=8, point=BATTLE, source=CORE,
        assert_="RemoveFaintedPlayerMon:\n\tld a, [wPlayerMonNumber]\n\tld c, a\n\tld hl, wPartyGainExpFlags",
        shape="FA {wPlayerMonNumber} 4F 21 {wPartyGainExpFlags}"),
    "battle_loop_head": _site(  # +6: after the added turn-counter increments (PLAN §3.5)
        symbol="MainInBattleLoop", off=6, cap=0, len=8, source=CORE,
        point=["wPlayerMonNumber", "wBattleMonHP", "wBattleMonSpecies", "wIsInBattle", "wBattleType",
               "wLinkState", "wPlayerBattleStatus3"],
        assert_="\tld hl, wPlayerTurnCount\n\tinc [hl]\n\tinc hl\n\tinc [hl] ; wEnemyTurnCount\n;;;;;;\n"
                "\tcall ReadPlayerMonCurHPAndStatus\n\tld hl, wBattleMonHP",
        shape="CD {ReadPlayerMonCurHPAndStatus} 21 {wBattleMonHP}",
        prelude=(0, "21 {wPlayerTurnCount} 34 23 34")),
    # pureRGB re-enters the loop BELOW the HP check when the MOVE menu is cancelled
    # (`jr nz, .loopNoMoveSelected`, core.asm), so a force-faint written at the loop head never
    # gets a free re-entry the way vanilla's `jr nz, MainInBattleLoop` gives it. The client lands
    # the pending battle write here and moves PC back to the loop head (+6, the HP check);
    # proven live 2026-09-18 (probe_gen1_loop_reentry: HandlePlayerMonFainted reached).
    "battle_loop_no_move": _site(
        symbol="MainInBattleLoop.loopNoMoveSelected", off=0, cap=0, len=8, source=CORE,
        point=["wPlayerMonNumber", "wBattleMonHP", "wBattleMonSpecies", "wIsInBattle", "wBattleType",
               "wLinkState", "wPlayerBattleStatus3"],
        assert_=(".loopNoMoveSelected ; will loop to here in the case that the player didn't choose a move"
                 " from the move selection menu" + chr(10) + chr(9) + "call SaveScreenTilesToBuffer1"
                 + chr(10) + chr(9) + "xor a" + chr(10) + chr(9) + "ld [wFirstMonsNotOutYet], a"),
        shape="CD {SaveScreenTilesToBuffer1} AF EA {wFirstMonsNotOutYet}"),
    "blackout": _site(
        symbol="ResetStatusAndHalveMoneyOnBlackout", off=0, cap=0, len=8, point=BATTLE,
        source="engine/events/black_out.asm",
        assert_="ResetStatusAndHalveMoneyOnBlackout::\n; Reset player status on blackout.\n\txor a\n"
                "\tld [wBattleResult], a\n\tld [wWalkBikeSurfState], a\n\tld [wIsInBattle], a",
        shape="AF EA {wBattleResult} EA {wWalkBikeSurfState} EA"),
    "capture_box": _site(
        symbol="SendNewMonToBox", off=0, cap=0, len=8, point=ACQUISITION + ["wBoxCount"], source=ITEMS,
        assert_="SendNewMonToBox:\n\tld de, wBoxCount\n\tld a, [de]\n\tinc a\n\tld [de], a",
        shape="11 {wBoxCount} 1A 3C 12"),
    "evolve": _site(
        symbol="TryEvolvingMon", off=0, cap=0, len=8, point=["wWhichPokemon", "wPartyCount"],
        source="engine/pokemon/evos_moves.asm",
        assert_="TryEvolvingMon:\n\tld hl, wCanEvolveFlags\n\txor a\n\tld [hl], a\n\tld a, [wWhichPokemon]",
        shape="21 {wCanEvolveFlags} AF 77 FA {wWhichPokemon}"),
    "move_mon": _site(
        symbol="MoveMon", off=0, cap=0, len=8, point=STORAGE + ["wMoveMonType"], source="home/move_mon.asm",
        assert_="MoveMon::\n\thomecall_sf _MoveMon",
        shape="F0 {lo:hLoadedROMBank} F5 3E {bank:_MoveMon} CD {SetCurBank}"),
    "npc_trade": _site(
        symbol="InGameTrade_DoTrade", off=0, cap=0, len=8, point=NPC_TRADE, source=TRADES,
        assert_="InGameTrade_DoTrade:\n\txor a ; NORMAL_PARTY_MENU\n\tld [wPartyMenuTypeOrMessageID], a\n"
                "\tdec a\n\tld [wUpdateSpritesEnabled], a",
        shape="AF EA {wPartyMenuTypeOrMessageID} 3D EA {wUpdateSpritesEnabled}"),
    "poison_faint": _site(  # .noBorrow+4 = the `push hl` reached only when the mon fainted
        symbol="ApplyOutOfBattlePoisonDamage.noBorrow", off=4, cap=0, len=8, point=BATTLE + ["wWhichPokemon"],
        source="engine/events/poison.asm",
        assert_="; the mon fainted from the damage\n\tpush hl\n\tinc hl\n\tinc hl\n\tld [hl], a\n\tld a, [de]\n"
                "\tld [wPokedexNum], a",
        shape="E5 23 23 77 1A EA {wPokedexNum}", prelude=(0, "2A B6 20")),
    "remove_pokemon": _site(
        symbol="RemovePokemon", off=0, cap=0, len=8, point=STORAGE + ["wRemoveMonFromBox"],
        source="home/move_mon.asm", assert_="RemovePokemon::\n\tjpfar _RemovePokemon",
        shape="21 {_RemovePokemon} 06 {bank:_RemovePokemon} C7 C9"),
    "save_witness": _site(  # +3 = the instruction after `call SaveGameData` (now `call ClearTextBox`)
        symbol="SaveMenu.save", off=3, cap=0, len=8, point=SAVE, source="engine/menus/save.asm",
        assert_=".save\n\tcall SaveGameData\n\tcall ClearTextBox\n\thlcoord 1, 14",
        shape="CD {ClearTextBox} 21", prelude=(0, "CD {SaveGameData}")),
    "starter_begin": _site(
        symbol="OaksLabMonChoiceMenu.continue", off=0x23, cap=0, len=8, point=BATTLE, source=OAKS,
        assert_="\txor a\n\tld [wIsAltPalettePkmnData], a\n\tcall AddPartyMon\n\tld hl, wStatusFlags4\n"
                "\tset BIT_GOT_STARTER, [hl]\n\tcall OaksLabDisableAllJoypadExceptAorB",
        shape="CD {AddPartyMon} 21 {wStatusFlags4} CB DE"),
    "starter_end": _site(
        symbol="OaksLabMonChoiceMenu.continue", off=0x26, cap=0, len=8, point=BATTLE, source=OAKS,
        assert_="\tcall AddPartyMon\n\tld hl, wStatusFlags4\n\tset BIT_GOT_STARTER, [hl]\n"
                "\tcall OaksLabDisableAllJoypadExceptAorB",
        shape="21 {wStatusFlags4} CB DE CD {OaksLabDisableAllJoypadExceptAorB}",
        prelude=(0x23, "CD {AddPartyMon}")),
    "wild_begin": _site(  # +$13: after MissingNoInit / PreventInvalidEncounters and the wIsInBattle store
        symbol="InitWildBattle", off=0x13, cap=0, len=8, point=OPPONENT, source=CORE,
        assert_="\tcallfar PreventInvalidEncounters\n;;;;;;;;;;\n\tld a, $1\n\tld [wIsInBattle], a\n"
                "\tcall LoadEnemyMonData\n\tcall DoBattleTransitionAndInitBattleVariables",
        shape="CD {LoadEnemyMonData} CD {DoBattleTransitionAndInitBattleVariables}",
        prelude=(0x0E, "3E 01 EA {wIsInBattle}")),
    # --- new kinds ---------------------------------------------------------------------------
    "trainer_staging": _site(  # InitBattleCommon (no underscore): the trainer branch's wIsInBattle=2
        symbol="InitBattleCommon", off=0x48, cap=0, len=8, point=OPPONENT + ["wTrainerClass"], source=CORE,
        assert_="\tld a, $ff\n\tld [wEnemyMonPartyPos], a\n\tld a, $2\n\tld [wIsInBattle], a\n\tjr _InitBattleCommon",
        shape="3E 02 EA {wIsInBattle} 18", prelude=(0x43, "3E FF EA {wEnemyMonPartyPos}")),
    "transform": _site(
        symbol="ChangePartyPokemonSpecies", off=0, cap=0, len=9, source=SPECIES,
        point=["wWhichPokemon", "wCurPartySpecies", "wPartyCount", "wPartyMon1HP"],
        assert_="ChangePartyPokemonSpecies::\n\tld a, [wCurPartySpecies]\n\tld [wCurSpecies], a\n\tcall GetMonHeader",
        shape="FA {wCurPartySpecies} EA {wCurSpecies} CD {GetMonHeader}"),
    "transform_hp_hi": _site(
        symbol="ChangePartyPokemonSpecies", off=0x4A, cap=0, len=8, point=["wWhichPokemon"], source=SPECIES,
        assert_="\tld a, b\n\tld [hli], a\n\tld a, c\n\tld [hld], a\n\tpop hl\n\t; reassign types",
        shape="22 79 32 E1"),
    "transform_hp_lo": _site(
        symbol="ChangePartyPokemonSpecies", off=0x4C, cap=0, len=8, point=["wWhichPokemon"], source=SPECIES,
        assert_="\tld a, c\n\tld [hld], a\n\tpop hl\n\t; reassign types", shape="32 E1 01"),
    "apex_preflight": _site(  # = .setDVs; HL is the target's DV pointer, old DVs still intact
        symbol="ItemUseMedicine.useApexChip", off=0x0F, cap=0, len=8, point=APEX, source=ITEMS,
        assert_=".setDVs\n\tld [hli], a ; set first byte of DVs to max\n\tld [hl], a  ; set second byte of DVs to max\n"
                "\tpop hl\n\tpush hl\n\tcall .recalculateStats",
        shape="22 77 E1 E5 CD {ItemUseMedicine.recalculateStats}"),
    "apex_commit": _site(
        symbol="ItemUseMedicine.useApexChip", off=0x11, cap=0, len=8, point=APEX, source=ITEMS,
        assert_="\tpop hl\n\tpush hl\n\tcall .recalculateStats", shape="E1 E5 CD {ItemUseMedicine.recalculateStats}"),
    "apex_recalc_call": _site(
        symbol="ItemUseMedicine.useApexChip", off=0x13, cap=0, len=8, point=APEX, source=ITEMS,
        assert_="\tcall .recalculateStats\n\tpop hl\n\tld bc, (wPartyMon1MaxHP) - wPartyMon1",
        shape="CD {ItemUseMedicine.recalculateStats} E1 01"),
    "npc_trade_remove": _site(
        symbol="InGameTrade_DoTrade", off=0x7B, cap=0, len=8, point=NPC_TRADE, source=TRADES,
        assert_="\tld [wRemoveMonFromBox], a\n\tcall RemovePokemon\n\tld a, %10000000 ; prevent the player from naming"
                " the mon\n\tld [wMonDataLocation], a\n\tcall AddPartyMon\n\tcall InGameTrade_CopyDataToReceivedMon",
        shape="CD {RemovePokemon} 3E 80 EA {wMonDataLocation}"),
    "npc_trade_add": _site(
        symbol="InGameTrade_DoTrade", off=0x83, cap=0, len=8, point=NPC_TRADE + ["wMonDataLocation"], source=TRADES,
        assert_="\tcall AddPartyMon\n\tcall InGameTrade_CopyDataToReceivedMon",
        shape="CD {AddPartyMon} CD {InGameTrade_CopyDataToReceivedMon}"),
    "npc_trade_done": _site(
        symbol="InGameTrade_DoTrade", off=0x89, cap=0, len=8, point=NPC_TRADE, source=TRADES,
        assert_="\tcall InGameTrade_CopyDataToReceivedMon\n\t;callfar InGameTrade_CheckForTradeEvo ; PureRGBnote: "
                "REMOVED: not needed\n\tcall ClearScreen\n\tcall InGameTrade_RestoreScreen",
        shape="CD {ClearScreen} CD {InGameTrade_RestoreScreen}"),
    "daycare_withdraw": _site(
        symbol="DaycareGentlemanText.enoughMoney", off=0x27, cap=0, len=9, source="scripts/Daycare.asm",
        point=STORAGE + ["wMoveMonType", "wDayCareMon"],
        assert_="\tld a, DAYCARE_TO_PARTY\n\tld [wMoveMonType], a\n\tcall MoveMon\n\tld a, [wDayCareMonSpecies]\n"
                "\tld [wCurPartySpecies], a",
        shape="CD {MoveMon} FA {wDayCareMonSpecies} EA {wCurPartySpecies}",
        prelude=(0x22, "3E 02 EA {wMoveMonType}")),  # DAYCARE_TO_PARTY = 2 (constants/menu_constants.asm)
    "cable_trade_remove": _site(
        symbol="TradeCenter_Trade.doTrade", off=0x77, cap=0, len=8, point=CABLE, source=CABLE_CLUB,
        assert_="\tld [wTradedPlayerMonSpecies], a\n\txor a\n\tld [wRemoveMonFromBox], a\n\tcall RemovePokemon\n"
                "\tld a, [wTradingWhichEnemyMon]",
        shape="CD {RemovePokemon} FA {wTradingWhichEnemyMon}"),
    "cable_trade_add": _site(  # +$9D = the call itself (A7's +$A0 was the instruction after it)
        symbol="TradeCenter_Trade.doTrade", off=0x9D, cap=0, len=10, point=CABLE, source=CABLE_CLUB,
        assert_="\trst _CopyData\n\tcall AddEnemyMonToPlayerParty\n\tld a, [wPartyCount]\n\tdec a\n"
                "\tld [wWhichPokemon], a",
        shape="CD {AddEnemyMonToPlayerParty} FA {wPartyCount} 3D EA {wWhichPokemon}"),
    "cable_partial_save": _site(
        symbol="TradeCenter_Trade.tradeCompleted", off=0x2C, cap=0, len=8, point=SAVE, source=CABLE_CLUB,
        assert_="\tcallfar SavePartyAndDexData ; this allows reset into Pokecenter",
        shape="21 {SavePartyAndDexData} 06 {bank:SavePartyAndDexData} C7"),
    "changebox_full_save": _site(  # +$35 = `call SaveGameData` (A4's +$38 was the following `ld a, SFX_SAVE`)
        symbol="ChangeBox.yes", off=0x35, cap=0, len=8, point=SAVE + ["wCurrentBoxNum"], source="engine/menus/save.asm",
        assert_="\tcall ChangeBoxData\n\tcall SaveGameData\n\tld a, SFX_SAVE\n\tcall PlaySoundWaitForCurrent",
        shape="CD {SaveGameData} 3E"),
    "capture_party_begin": _site(
        symbol="ItemUseBall.skipShowingPokedexData", off=0x22, cap=0, len=8, point=ACQUISITION, source=ITEMS,
        assert_="\tld [wMonDataLocation], a\n\tcall ClearSprites\n\tcall AddPartyMon\n;;;;;;;;;; PureRGBnote: ADDED: "
                "when in bills garden, if a pikachu is caught, force it to have the nickname PIKABLU\n\tpop af\n"
                "\tand a\n\tjr z, .done",
        shape="CD {AddPartyMon} F1 A7 28"),
    "capture_party_end": _site(
        symbol="ItemUseBall.skipShowingPokedexData", off=0x25, cap=0, len=8, point=ACQUISITION, source=ITEMS,
        assert_="\tcall AddPartyMon\n;;;;;;;;;; PureRGBnote: ADDED: when in bills garden, if a pikachu is caught, "
                "force it to have the nickname PIKABLU\n\tpop af\n\tand a\n\tjr z, .done",
        shape="F1 A7 28", prelude=(0x22, "CD {AddPartyMon}")),
    "capture_box_begin": _site(
        symbol="ItemUseBall.sendToBox", off=3, cap=0, len=8, point=ACQUISITION + ["wBoxCount"], source=ITEMS,
        assert_=".sendToBox\n\tcall ClearSprites\n\tcall SendNewMonToBox\n\tld hl, ItemUseBallText07",
        shape="CD {SendNewMonToBox} 21 {ItemUseBallText07}"),
    "capture_box_end": _site(
        symbol="ItemUseBall.sendToBox", off=6, cap=0, len=8, point=ACQUISITION + ["wBoxCount"], source=ITEMS,
        assert_="\tcall SendNewMonToBox\n\tld hl, ItemUseBallText07",
        shape="21 {ItemUseBallText07}", prelude=(3, "CD {SendNewMonToBox}")),
    "pc_deposit": _site(  # the instruction after `call RemovePokemon` in the deposit-confirm path
        symbol="BillsPCDeposit", off=0x4B, cap=0, len=8, point=STORAGE + ["wRemoveMonFromBox"], source=BILLS_PC,
        assert_="\txor a\n\tld [wRemoveMonFromBox], a\n\tcall RemovePokemon\n\tcall WaitForSoundToFinish\n"
                "\tld hl, wBoxNumString",
        shape="CD {WaitForSoundToFinish} 21 {wBoxNumString}", prelude=(0x48, "CD {RemovePokemon}")),
    "pc_withdraw": _site(
        symbol="BillsPCWithdraw", off=0x67, cap=0, len=8, point=STORAGE + ["wRemoveMonFromBox"], source=BILLS_PC,
        assert_="\tld a, 1\n\tld [wRemoveMonFromBox], a\n\tcall RemovePokemon\n\tcall WaitForSoundToFinish\n"
                "\tld hl, MonIsTakenOutText",
        shape="CD {WaitForSoundToFinish} 21 {MonIsTakenOutText}", prelude=(0x64, "CD {RemovePokemon}")),
    "pc_release": _site(
        symbol="BillsPCRelease", off=0x70, cap=0, len=8, point=STORAGE + ["wRemoveMonFromBox", "wCurPartySpecies"],
        source=BILLS_PC,
        assert_="\tinc a\n\tld [wRemoveMonFromBox], a\n\tcall RemovePokemon\n\tcall WaitForSoundToFinish\n"
                "\tld a, [wCurPartySpecies]",
        shape="CD {WaitForSoundToFinish} FA {wCurPartySpecies}", prelude=(0x6D, "CD {RemovePokemon}")),
    "evolve_species_store": _site(  # the final wPartySpecies store of an evolution
        symbol="Evolution_PartyMonLoop.skipfix_end", off=0x3C, cap=0, len=8,
        point=["wWhichPokemon", "wPartyCount", "wLoadedMonSpecies"], source="engine/pokemon/evos_moves.asm",
        assert_="\tpop de\n\tpop hl\n\tld a, [wLoadedMonSpecies]\n\tld [hl], a\n\tpush hl\n\tld l, e\n\tld h, d\n"
                "\tjr .nextEvoEntry2",
        shape="77 E5 6B 62 18", prelude=(0x39, "FA {wLoadedMonSpecies}")),
}

# Rows the SLink overlay's source edits change (tools/apply_purergb_overlay.py): TryEvolvingMon
# gains `::`; .setDVs gains `ld d,h / ld e,l / farcall SlinkApexGuard / jr c / ld h,d / ld l,e /
# ld a, $FF` (14 bytes) before the DV store, so the three APEX anchors move by +14 while HL (the
# DV pointer) and the points stay.
OVERLAY = {
    "evolve": {
        "assert_": "TryEvolvingMon:: ; SLink overlay: exported for the native trade\n\tld hl, wCanEvolveFlags\n"
                   "\txor a\n\tld [hl], a\n\tld a, [wWhichPokemon]"},
    "apex_preflight": {
        "off": 0x0F + 14,
        "assert_": ".setDVs\n\tld d, h ; SLink overlay: the DV pointer rides in de (a farcall takes hl)\n\tld e, l\n"
                   "\tfarcall SlinkApexGuard ; carry = a same-OT/same-species mon is already $FFFF\n"
                   "\tjr c, .alreadyUsedApex ; refused before the chip is consumed\n\tld h, d\n\tld l, e\n\tld a, $FF\n"
                   "\tld [hli], a ; set first byte of DVs to max\n\tld [hl], a  ; set second byte of DVs to max\n"
                   "\tpop hl\n\tpush hl\n\tcall .recalculateStats"},
    "apex_commit": {"off": 0x11 + 14},
    "apex_recalc_call": {"off": 0x13 + 14},
}

_TOKEN = re.compile(r"^\{(?:(bank|lo):)?([^}]+)\}$")


def shape_bytes(shape: str, syms: dict) -> bytes:
    out = bytearray()
    for tok in shape.split():
        m = _TOKEN.match(tok)
        if not m:
            out.append(int(tok, 16))
            continue
        kind, name = m.groups()
        if name not in syms:
            raise SystemExit(f"shape operand {name!r} is not in the .sym")
        bank, addr = syms[name]
        if kind == "bank":
            out.append(bank)
        elif kind == "lo":
            out.append(addr & 0xFF)
        else:
            out += bytes((addr & 0xFF, addr >> 8))
    return bytes(out)


def build(foundation: str = FOUNDATION) -> dict:
    lock = F.lock(foundation)
    fnd = F.foundation(foundation)
    sites_spec = {k: {**v, **OVERLAY.get(k, {})} for k, v in SITES.items()} if foundation.endswith("_overlay") else SITES
    roms = {t: F.rom_path(foundation, t).read_bytes() for t in fnd["titles"]}
    for title, rom in roms.items():
        want = lock["outputs"][pathlib.Path(fnd["titles"][title][1]).stem]["sha1"]
        if hashlib.sha1(rom).hexdigest() != want:
            raise SystemExit(f"{title}: built ROM sha1 differs from the lock")
    for spec in sites_spec.values():
        F.assert_source(foundation, spec["source"], spec["assert_"])
    result: dict = {"schema": SCHEMA, "source_commit": lock["source"]["commit"], "titles": {}}
    for title, rom in roms.items():
        sym_path = F.sym_path(foundation, title)
        syms = F.parse_sym(sym_path)
        sites: dict[str, dict] = {}
        needed: set[str] = set()
        for kind, spec in sites_spec.items():
            if spec["symbol"] not in syms:
                raise SystemExit(f"{title}: {kind}: symbol {spec['symbol']!r} is not in {sym_path.name}")
            bank, base = syms[spec["symbol"]]
            addr = base + spec["off"]
            off = F.flat(bank, addr)
            expected = rom[off:off + spec["len"]]
            want = shape_bytes(spec["shape"], syms)
            if len(want) > spec["len"]:
                raise SystemExit(f"{kind}: shape is longer than the {spec['len']}-byte slice")
            if expected[:len(want)] != want:
                raise SystemExit(f"{title}: {kind}: ROM bytes {expected.hex().upper()} do not match "
                                 f"{spec['shape']} = {want.hex().upper()}")
            row = {"symbol": spec["symbol"], "anchor_offset": spec["off"], "bank": bank, "address": addr,
                   "rom_offset": off, "capture_offset": spec["cap"], "expected_hex": expected.hex().upper(),
                   "point": list(spec["point"]), "source": spec["source"], "assert": spec["assert_"]}
            if "prelude" in spec:
                p_off, p_shape = spec["prelude"]
                p_flat = F.flat(bank, base + p_off)
                p_want = shape_bytes(p_shape, syms)
                if rom[p_flat:p_flat + len(p_want)] != p_want:
                    raise SystemExit(f"{title}: {kind}: prelude bytes at +{p_off:#x} do not match {p_shape}")
                row["prelude"] = {"address": base + p_off, "rom_offset": p_flat, "expected_hex": p_want.hex().upper()}
            sites[kind] = row
            needed.update(spec["point"])
        if syms["ItemUseMedicine.setDVs"] != (syms["ItemUseMedicine.useApexChip"][0],
                                              syms["ItemUseMedicine.useApexChip"][1] + 0x0F):
            raise SystemExit(f"{title}: apex_preflight is no longer .setDVs")
        needed.add("hLoadedROMBank")
        missing = sorted(n for n in needed if n not in syms)
        if missing:
            raise SystemExit(f"{title}: point symbols missing from the .sym: {missing}")
        result["titles"][title] = {
            "symbols_sha256": hashlib.sha256(sym_path.read_bytes()).hexdigest(),
            "rom_sha1": hashlib.sha1(rom).hexdigest(),
            "addresses": {n: syms[n][1] for n in sorted(needed)},
            "sites": sites,
        }
    result["sha256"] = hashlib.sha256(json.dumps(result, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return result


def render(value: dict) -> str:
    return json.dumps(value, indent=1, sort_keys=True) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="fail if the committed file is stale")
    ap.add_argument("--kind", default="clean", choices=("clean", "overlay"),
                    help="overlay: the SLink companion build (engine_signals_overlay.json)")
    args = ap.parse_args()
    foundation = F.with_kind(FOUNDATION, args.kind)
    out = F.out_path(foundation, "engine_signals.json")
    text = render(build(foundation))
    if args.check:
        if not out.exists() or out.read_text(encoding="utf-8") != text:
            print(f"{out.relative_to(REPO)} is stale; run tools/gen_gen1_engine_signals.py", file=sys.stderr)
            return 1
        print(f"{out.relative_to(REPO)} is current")
        return 0
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8", newline="\n")
    titles = json.loads(text)["titles"]
    print(f"wrote {out.relative_to(REPO)}: " + ", ".join(f"{t} sites={len(v['sites'])}" for t, v in titles.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
