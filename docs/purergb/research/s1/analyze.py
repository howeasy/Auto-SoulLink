import json, os, sys
from symtool import Title, TITLES, hexstr, rom_offset

OUT = os.path.dirname(os.path.abspath(__file__))

titles = {t: Title(t) for t in TITLES}

def get(t, label, offset=0, n=8):
    r = titles[t].resolve(label, offset)
    if r is None:
        return None
    b = titles[t].bytes_at(r["rom_offset"], n)
    r["bytes"] = hexstr(b)
    r["bytes_raw"] = list(b)
    return r

# ---------------------------------------------------------------------------
# SITES: list of (kind_name, symbol, offset, expected_desc)
# ---------------------------------------------------------------------------
SITES = [
    ("wild_begin", "InitWildBattle", 0x13, "call LoadEnemyMonData (CD lo hi) right after ld [wIsInBattle],a"),
    ("battle_loop_head", "MainInBattleLoop", 6, "call ReadPlayerMonCurHPAndStatus (CD lo hi)"),
    ("trainer_staging_1", "_InitBattleCommon", 0x48, "task hypothesis: 3E 02 (ld a,2) -- to be checked against derived byte count"),
    ("trainer_staging_2", "_InitBattleCommon", 0x4D, "task hypothesis: continuation of above"),
    ("battle_faint", "RemoveFaintedPlayerMon", 0, "FA lo hi = ld a,[wPlayerMonNumber]"),
    ("poison_faint", "ApplyOutOfBattlePoisonDamage.noBorrow", 4, "E5 23 23 77 1A EA lo hi (wPokedexNum store)"),
    ("bag_received", "AddItemToInventory_.done", 8, "C9 (ret) -- epilogue E1 D1 C1 C1 78 EA lo hi C9, +8=C9"),
    ("save_witness", "SaveMenu.save", 3, "CD lo hi of ClearTextBox (after CD lo hi SaveGameData at +0)"),
    ("capture_party_begin", "ItemUseBall.skipShowingPokedexData", 34, "call AddPartyMon (CD lo hi)"),
    ("capture_party_end", "ItemUseBall.skipShowingPokedexData", 37, "pop af (Bill's Garden $80 branch epilogue)"),
    ("capture_box_begin", "ItemUseBall.sendToBox", 3, "call SendNewMonToBox (CD lo hi)"),
    ("capture_box_end", "ItemUseBall.sendToBox", 6, "start of next instr after call SendNewMonToBox"),
    ("pc_deposit", "BillsPCDeposit", 0x4B, "derived: CD lo hi call WaitForSoundToFinish"),
    ("pc_withdraw", "BillsPCWithdraw", 0x67, "derived: CD lo hi call WaitForSoundToFinish"),
    ("pc_release", "BillsPCRelease", 0x70, "derived: CD lo hi call WaitForSoundToFinish"),
    ("changebox_full_save", "ChangeBox.yes", 0x38, "derived: CD lo hi call SaveGameData"),
    ("evolve_species_store", "Evolution_PartyMonLoop.skipfix_end", 60, "77 (ld [hl],a) then E5 6B 62 18 01 (push hl; ld l,e; ld h,d; jr +1)"),
    ("transform_base", "ChangePartyPokemonSpecies", 0, "FA lo hi ld a,[wCurPartySpecies]"),
    ("transform_species_list", "ChangePartyPokemonSpecies", 0x16, "77 = ld [hl],a (species-list write)"),
    ("transform_struct_species", "ChangePartyPokemonSpecies", 0x27, "77 = ld [hl],a (struct species write)"),
    ("transform_hp_hi", "ChangePartyPokemonSpecies", 0x4A, "22 = ld [hli],a (HP MSB store)"),
    ("transform_hp_lo", "ChangePartyPokemonSpecies", 0x4C, "32 = ld [hld],a (HP LSB store)"),
    ("apex_preflight", "ItemUseMedicine.useApexChip", 0x0F, "= .setDVs; 22 (ld [hli],a, first DV byte max)"),
    ("apex_commit", "ItemUseMedicine.useApexChip", 0x11, "E1 (pop hl) after both DV bytes maxed"),
    ("apex_recalc_call", "ItemUseMedicine.useApexChip", 0x13, "CD lo hi of ItemUseMedicine.recalculateStats"),
    ("npc_trade_remove", "InGameTrade_DoTrade", 0x7B, "CD lo hi call RemovePokemon"),
    ("npc_trade_add", "InGameTrade_DoTrade", 0x83, "CD lo hi call AddPartyMon, preceded by 3E 80 EA lo hi wMonDataLocation"),
    ("npc_trade_done", "InGameTrade_DoTrade", 0x89, "CD lo hi call ClearScreen"),
    ("cable_remove", "TradeCenter_Trade.doTrade", 0x77, "CD lo hi call RemovePokemon"),
    ("cable_add", "TradeCenter_Trade.doTrade", 0xA0, "CD lo hi call AddEnemyMonToPlayerParty"),
    ("cable_partial_save", "TradeCenter_Trade.tradeCompleted", 0x2C, "callfar SavePartyAndDexData = 21 lo hi 06 bank C7"),
    ("daycare_withdraw", "DaycareGentlemanText.enoughMoney", 0x27, "CD lo hi call MoveMon"),
    ("blackout", "ResetStatusAndHalveMoneyOnBlackout", 0, "dump only"),
    ("whiteout_endofbattle", "EndOfBattle", 0, "dump only, bank must be 0x3A"),
    ("starter", "OaksLabMonChoiceMenu.continue", 0x23, "CD lo hi call AddPartyMon"),
    ("checkpoint_delayframe_halt", "DelayFrame", 23, "76 00 = halt; nop"),
    ("checkpoint_overworldloop", "OverworldLoop", 0, "D7 = rst _DelayFrame"),
    ("checkpoint_init", "Init", 0, "dump only"),
    ("checkpoint_softreset", "SoftReset", 0, "dump only"),
    ("checkpoint_start", "_Start", 0, "dump only (cp BOOTUP_A_CGB; ld a,TRUE; jr z .gbc; dec a; ...)"),
]

# VBlank vector and RST vectors are raw addresses (bank 0), handle separately.
RAW_ADDR_SITES = [
    ("checkpoint_vblank_vector", 0x0040, "C3 lo hi of VBlank"),
    ("rst_0000", 0x0000, "C3 lo hi _Bankswitch = jp Bankswitch, then text"),
    ("rst_0008", 0x0008, "C3 lo hi _Predef = jp Predef, then text"),
    ("rst_0010", 0x0010, "C3 lo hi _DelayFrame = jp DelayFrame, then text"),
    ("rst_0018", 0x0018, "D7 0D 20 xx C9 = rst _DelayFrame; dec c; jr nz DelayFrames; ret"),
    ("rst_0020", 0x0020, "C3 lo hi _CopyData = jp CopyData, then text"),
    ("rst_0028", 0x0028, "C3 lo hi _PrintText = jp PrintText, then text"),
]

results = {"sites": {}, "raw_addr_sites": {}}

for kind, sym, off, note in SITES:
    per_title = {}
    for t in TITLES:
        r = get(t, sym, off, 8)
        per_title[t] = r
    results["sites"][kind] = {"symbol": sym, "offset": off, "note": note, "titles": per_title}

for kind, addr, note in RAW_ADDR_SITES:
    per_title = {}
    for t in TITLES:
        rom_off = rom_offset(0, addr)
        b = titles[t].bytes_at(rom_off, 8)
        per_title[t] = {"bank": 0, "address": addr, "rom_offset": rom_off, "bytes": hexstr(b), "bytes_raw": list(b)}
    results["raw_addr_sites"][kind] = {"address": addr, "note": note, "titles": per_title}

with open(os.path.join(OUT, "sites_raw.json"), "w") as f:
    json.dump(results, f, indent=2)

print("wrote sites_raw.json")
