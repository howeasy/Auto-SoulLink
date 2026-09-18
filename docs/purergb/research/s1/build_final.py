import json, os
from symtool import Title, TITLES, hexstr, rom_offset

OUT = os.path.dirname(os.path.abspath(__file__))
titles = {t: Title(t) for t in TITLES}


def capture(t, symbol, offset, n=8):
    r = titles[t].resolve(symbol, offset)
    if r is None:
        return None
    b = titles[t].bytes_at(r["rom_offset"], n)
    return {
        "symbol": symbol,
        "offset": offset,
        "bank": r["bank"],
        "address": r["eff_address"],
        "rom_offset": r["rom_offset"],
        "expected_hex": hexstr(b).replace(" ", ""),
        "capture_offset": 0,
        "source_assert_ok": True,   # filled in / overridden below per-site
        "note": "",
    }

# (kind, symbol, offset, note, source_assert_ok override or None=auto-true)
SITE_DEFS = [
    ("wild_begin", "InitWildBattle", 0x13, "Lands exactly on `call LoadEnemyMonData` (CD 8A 6A); the 3 bytes at +0x10 are EA 57 D0 = ld [wIsInBattle],a ($D057), confirming the site starts the next instruction. core.asm L7091-7093.", True),
    ("battle_loop_head", "MainInBattleLoop", 6, "call ReadPlayerMonCurHPAndStatus (CD 00 4E = call $4E00). core.asm L309-317.", True),
    ("trainer_staging", "_InitBattleCommon", 0x48, "MISMATCH: task cites `_InitBattleCommon` (core.asm L7111, the SHARED tail both wild/trainer paths jump to). At +0x48 that label's real bytes are `4E 21 74 74 06 35 C7 CD` (mid-instruction: the high byte of `call z, DrawEnemyHUDAndHPBar` followed by the callfar to CheckInitSpecialBattleEffect) -- no `ld a,2` exists anywhere in `_InitBattleCommon`. The intended site is the DIFFERENT, similarly-named label `InitBattleCommon` (no underscore, core.asm L7044, 67 lines earlier) -- its trainer branch sets wIsInBattle=2 right before jumping into `_InitBattleCommon`. `InitBattleCommon+0x48` = `3E 02 EA 57 D0 18 49 21` = ld a,2 (matches task's own '3E 02' hypothesis exactly); `+0x4D` = `18 49` = jr +0x49, which lands exactly on `_InitBattleCommon`. CORRECTED SYMBOL: InitBattleCommon (not _InitBattleCommon).", False),
    ("battle_faint", "RemoveFaintedPlayerMon", 0, "ld a,[wPlayerMonNumber] (FA 2F CC = ld a,[$CC2F]). core.asm L1151.", True),
    ("poison_faint", "ApplyOutOfBattlePoisonDamage.noBorrow", 4, "E5 23 23 77 1A EA 26 D1 = push hl; inc hl; inc hl; ld [hl],a; ld a,[de]; ld [wPokedexNum],a ($D126). poison.asm L40-45.", True),
    ("bag_received", "AddItemToInventory_.done", 8, "C9 = ret, end of the 9-byte epilogue E1 D1 C1 C1 78 EA lo hi C9. inventory.asm L86-93.", True),
    ("save_witness", "SaveMenu.save", 3, "call ClearTextBox (CD 56 29 = call $2956), immediately after call SaveGameData at +0. save.asm L162-164.", True),
    ("capture_party_begin", "ItemUseBall.skipShowingPokedexData", 34, "call AddPartyMon (CD 9A 34 = call $349A). item_effects.asm L602.", True),
    ("capture_party_end", "ItemUseBall.skipShowingPokedexData", 37, "pop af; and a (F1 A7), start of the Bill's Garden $80-nickname-skip branch epilogue right after AddPartyMon returns. item_effects.asm L604-606.", True),
    ("capture_box_begin", "ItemUseBall.sendToBox", 3, "call SendNewMonToBox (CD 4B 65 = call $654B). item_effects.asm L616.", True),
    ("capture_box_end", "ItemUseBall.sendToBox", 6, "ld hl, ItemUseBallText07 (21 68 54), the instruction right after call SendNewMonToBox returns. item_effects.asm L617.", True),
    ("pc_deposit", "BillsPCDeposit", 0x4B, "Derived (task asked us to derive it): call WaitForSoundToFinish (CD AC 33 = call $33AC), the instruction right after `call RemovePokemon` in the deposit-confirm path. bills_pc.asm L235-236.", True),
    ("pc_withdraw", "BillsPCWithdraw", 0x67, "Derived: call WaitForSoundToFinish (CD AC 33), same pattern as deposit, right after `call RemovePokemon`. bills_pc.asm L311-312.", True),
    ("pc_release", "BillsPCRelease", 0x70, "Derived: call WaitForSoundToFinish (CD AC 33), same pattern, right after `call RemovePokemon`. bills_pc.asm L389-390.", True),
    ("changebox_full_save", "ChangeBox.yes", 0x38, "MISMATCH: at +0x38 the real bytes are `3E B6 CD A5 33 CD AC 33` = ld a, SFX_SAVE($B6); call PlaySoundWaitForCurrent($33A5); call WaitForSoundToFinish($33AC) -- NOT SaveGameData. `call SaveGameData` (CD B5 78 = call $78B5) actually starts 3 bytes earlier, at +0x35. CORRECTED OFFSET: 0x35 (not 0x38). save.asm L397-399.", False),
    ("evolve_species_store", "Evolution_PartyMonLoop.skipfix_end", 60, "77 E5 6B 62 18 01 = ld [hl],a (final species-list store, wLoadedMonSpecies -> party species slot) ; push hl ; ld l,e ; ld h,d ; jr +1 (to .nextEvoEntry2). Matches task's '77 ... 6B 62 18 01' shape (E5=push hl sits between, as the task's 'within the next bytes' phrasing allows). evos_moves.asm L293-300.", True),
    ("transform_base", "ChangePartyPokemonSpecies", 0, "ld a,[wCurPartySpecies] (FA 91 CF = ld a,[$CF91]). change_mon_species.asm L8. Routine total length is 0x5B bytes exactly, as the task predicted.", True),
    ("transform_species_list", "ChangePartyPokemonSpecies", 0x16, "77 = ld [hl],a, the wPartySpecies-array write. change_mon_species.asm L17.", True),
    ("transform_struct_species", "ChangePartyPokemonSpecies", 0x27, "77 = ld [hl],a, the per-mon struct species write. change_mon_species.asm L24.", True),
    ("transform_hp_hi", "ChangePartyPokemonSpecies", 0x4A, "22 = ld [hli],a, new max-HP MSB stored into current-HP MSB. change_mon_species.asm L47.", True),
    ("transform_hp_lo", "ChangePartyPokemonSpecies", 0x4C, "32 = ld [hld],a, new max-HP LSB stored into current-HP LSB. change_mon_species.asm L49.", True),
    ("apex_preflight", "ItemUseMedicine.useApexChip", 0x0F, "= ItemUseMedicine.setDVs (confirmed by symbol table: both resolve to the same address). 22 77 = ld [hli],a ; ld [hl],a, maxing both DV bytes. item_effects.asm L1675-1677.", True),
    ("apex_commit", "ItemUseMedicine.useApexChip", 0x11, "E1 E5 = pop hl ; push hl, immediately after both DV bytes are maxed, restoring hl before the stat recalc call. item_effects.asm L1678-1679.", True),
    ("apex_recalc_call", "ItemUseMedicine.useApexChip", 0x13, "call ItemUseMedicine.recalculateStats (CD 4D 5A = call $5A4D). item_effects.asm L1680.", True),
    ("npc_trade_remove", "InGameTrade_DoTrade", 0x7B, "call RemovePokemon (CD 93 34 = call $3493). in_game_trades.asm L152.", True),
    ("npc_trade_add", "InGameTrade_DoTrade", 0x83, "call AddPartyMon (CD 9A 34 = call $349A), preceded at +0x7E..+0x82 by 3E 80 EA 49 CC = ld a,$80 ; ld [wMonDataLocation],a ($CC49), exactly as the task predicted. in_game_trades.asm L153-155.", True),
    ("npc_trade_done", "InGameTrade_DoTrade", 0x89, "call ClearScreen (CD 34 16 = call $1634). in_game_trades.asm L158.", True),
    ("cable_remove", "TradeCenter_Trade.doTrade", 0x77, "call RemovePokemon (CD 93 34 = call $3493). cable_club.asm L787.", True),
    ("cable_add", "TradeCenter_Trade.doTrade", 0xA0, "MISMATCH: at +0xA0 the real bytes are `FA 6B D1 3D EA 92 CF 3E` = ld a,[wPartyCount] ; dec a ; ld [wWhichPokemon],a ; ... -- the instruction right AFTER the call, not the call itself. `call AddEnemyMonToPlayerParty` (CD CB 34 = call $34CB) actually starts 3 bytes earlier, at +0x9D. CORRECTED OFFSET: 0x9D (not 0xA0). cable_club.asm L804-805.", False),
    ("cable_partial_save", "TradeCenter_Trade.tradeCompleted", 0x2C, "callfar SavePartyAndDexData (21 80 78 06 1C C7 = ld hl,$7880 ; ld b,$1C ; rst 0), matching bank $1C / addr $7880 for SavePartyAndDexData exactly. cable_club.asm L854.", True),
    ("daycare_withdraw", "DaycareGentlemanText.enoughMoney", 0x27, "call MoveMon (CD DC 34 = call $34DC), preceded by ld a,DAYCARE_TO_PARTY ; ld [wMoveMonType],a. Daycare.asm L164-166.", True),
    ("blackout", "ResetStatusAndHalveMoneyOnBlackout", 0, "AF EA 0B CF EA 08 D7 EA = xor a ; ld [wBattleResult],a ($CF0B) ; ld [wWalkBikeSurfState],a ($D708) ; ld [wIsInBattle... (cut off at 8 bytes, low byte visible). Dump-only structural check per task; matches black_out.asm L3-6 instruction order.", True),
    ("whiteout_endofbattle", "EndOfBattle", 0, "Bank confirmed = $3A exactly as the task required. FA 33 D1 FE 04 20 36 FA = ld a,[wPlayerJumpingLedgeCounter or similar] ; cp 4 ; jr nz,+0x36. Dump-only structural check.", True),
    ("starter", "OaksLabMonChoiceMenu.continue", 0x23, "call AddPartyMon (CD 9A 34 = call $349A). OaksLab.asm L843.", True),
    ("checkpoint_delayframe_halt", "DelayFrame", 23, "76 00 = halt ; nop, exactly as the task predicted. vblank.asm L111-113.", True),
    ("checkpoint_overworldloop", "OverworldLoop", 0, "D7 = rst _DelayFrame, exactly as the task predicted. overworld.asm L29.", True),
    ("checkpoint_init", "Init", 0, "F3 AF E0 0F E0 FF E0 43 = di ; xor a ; ldh [rIF],a ; ldh [rIE],a ; ldh [rSCX],a(cut off). init.asm L10-15. Dump-only.", True),
    ("checkpoint_softreset", "SoftReset", 0, "CD DD 1D CD 32 38 0E 20 = call StopAllSounds($1DDD) ; call GBPalWhiteOut($3832) ; ld c,32. init.asm L2-4. Dump-only.", True),
    ("checkpoint_start", "_Start", 0, "FE 11 3E 01 28 01 3D E0 = cp BOOTUP_A_CGB($11) ; ld a,TRUE ; jr z,+1(.gbc) ; dec a ; ldh[hGBC],a(cut off). start.asm L2-7. Dump-only.", True),
]

RAW_ADDR_DEFS = [
    ("checkpoint_vblank_vector", 0x0040, "C3 F3 1D = jp $1DF3 = VBlank, exactly as the task predicted. home/header.asm L82.", True),
    ("rst_0000", 0x0000, "C3 97 32 = jp $3297 = Bankswitch (_Bankswitch::). home/header.asm L6.", True),
    ("rst_0008", 0x0008, "C3 D0 38 = jp $38D0 = Predef (_Predef::). home/header.asm L15.", True),
    ("rst_0010", 0x0010, "C3 76 1E = jp $1E76 = DelayFrame (_DelayFrame::). home/header.asm L21.", True),
    ("rst_0018", 0x0018, "D7 0D 20 FC C9 = rst _DelayFrame ; dec c ; jr nz,-4(self loop) ; ret, exactly the DelayFrames loop body. home/header.asm L26-30.", True),
    ("rst_0020", 0x0020, "C3 AE 00 = jp $00AE = CopyData (_CopyData::). home/header.asm L38.", True),
    ("rst_0028", 0x0028, "C3 A5 36 = jp $36A5 = PrintText (_PrintText::). home/header.asm L45.", True),
]

sites_purergb = {"schema": "purergb-engine-signal-sites-v1", "titles": {}}
corrections = []

for t in TITLES:
    sites = {}
    for kind, sym, off, note, ok in SITE_DEFS:
        entry = capture(t, sym, off)
        entry["note"] = note
        entry["source_assert_ok"] = ok
        sites[kind] = entry
        if not ok and t == TITLES[0]:
            corrections.append((kind, sym, off))
    for kind, addr, note, ok in RAW_ADDR_DEFS:
        rom_off = rom_offset(0, addr)
        b = titles[t].bytes_at(rom_off, 8)
        sites[kind] = {
            "symbol": None, "offset": None, "bank": 0, "address": addr,
            "rom_offset": rom_off, "expected_hex": hexstr(b).replace(" ", ""),
            "capture_offset": 0, "source_assert_ok": ok, "note": note,
        }
    sites_purergb["titles"][t] = {"sites": sites}

# add corrected-offset shadow entries for the 2 real mismatches, so the JSON
# carries both "what the task asked for" (FAIL) and "what actually works" (PASS)
CORRECTED = [
    ("trainer_staging_corrected", "InitBattleCommon", 0x48,
     "CORRECTED site for trainer_staging: same offset (0x48), correct label InitBattleCommon (no underscore). 3E 02 EA 57 D0 18 49 21 = ld a,2 ; ld [wIsInBattle],a ; jr +0x49 (lands exactly on _InitBattleCommon)."),
    ("changebox_full_save_corrected", "ChangeBox.yes", 0x35,
     "CORRECTED offset for changebox_full_save: 0x35 (not 0x38). CD B5 78 = call SaveGameData ($78B5)."),
    ("cable_add_corrected", "TradeCenter_Trade.doTrade", 0x9D,
     "CORRECTED offset for cable_add: 0x9D (not 0xA0). CD CB 34 = call AddEnemyMonToPlayerParty ($34CB)."),
]
for t in TITLES:
    for kind, sym, off, note in CORRECTED:
        entry = capture(t, sym, off)
        entry["note"] = note
        entry["source_assert_ok"] = True
        sites_purergb["titles"][t]["sites"][kind] = entry

with open(os.path.join(OUT, "sites_purergb.json"), "w") as f:
    json.dump(sites_purergb, f, indent=2)

print("wrote sites_purergb.json")
print("mismatches:", corrections)

# cross-title identical check
mismatch_titles = []
for kind in sites_purergb["titles"]["red"]["sites"]:
    hexes = {t: sites_purergb["titles"][t]["sites"][kind]["expected_hex"] for t in TITLES}
    if len(set(hexes.values())) != 1:
        mismatch_titles.append((kind, hexes))
print("cross-title byte differences:", mismatch_titles)
