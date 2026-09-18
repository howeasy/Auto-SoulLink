#!/usr/bin/env python3
"""Generate a Gen 1 profile.json from a foundation's pinned symbol files.

The Gen 1 client and adapter read every address from this file. Nothing downstream
types a hex address by hand; if a symbol is missing from a title's .sym the
generator fails, so the list below stays honest.

Foundations (tools/gen1_foundation.py):
    pret     data/games/gen1_rby/profile.json from data/pret/*.sym (red/blue/yellow);
             data/pret_rom_syms.json = clean ROM SHA-1 per title
    purergb  data/games/gen1_purergb/profile.json from data/purergb/*.sym (purered/pureblue/
             puregreen); commit + ROM SHA-1 from data/purergb_sources.lock.json; extra RAM
             symbols and derived constants, each asserted against the pinned source and the
             built ROM (needs SLINK_PURERGB_SRC / SLINK_PURERGB_ROMS, see gen1_foundation)

    python tools/gen_gen1_profile.py [--foundation purergb]            # rewrite the profile
    python tools/gen_gen1_profile.py [--foundation purergb] --check    # exit 1 if stale
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

OUT = REPO / "data" / "games" / "gen1_rby" / "profile.json"
SYMS = REPO / "data" / "pret"

PRET_COMMITS = {
    "pokered": "405b6246372d7e5a2cb029cbb65219b13286b8c9",
    "pokeyellow": "0a08515",
}

TITLES = {
    # title: (repo, sym file, rom_syms key)
    "red": ("pokered", "pokered.sym", "pokered"),
    "blue": ("pokered", "pokeblue.sym", "pokeblue"),
    "yellow": ("pokeyellow", "pokeyellow.sym", "pokeyellow"),
}

# RAM symbols the client reads or writes. One purpose each; keep alphabetical inside a group.
RAM_SYMBOLS = [
    # player / save identity
    "wPlayerID", "wPlayerName", "wRivalName", "wPlayerMoney", "wPlayerCoins", "wObtainedBadges",
    "wPokedexOwned", "wPokedexSeen", "wOptions", "wSaveFileStatus",
    "wMainDataStart", "wMainDataEnd", "wSpriteDataStart", "wSpriteDataEnd",
    "wBoxDataStart", "wBoxDataEnd", "wCurMapTileset",
    # party
    "wPartyCount", "wPartySpecies", "wPartyMons", "wPartyMon1", "wPartyMon2",
    "wPartyMonOT", "wPartyMonNicks",
    # active box mirror in WRAM
    "wBoxCount", "wBoxSpecies", "wBoxMons", "wBoxMon1", "wBoxMon2", "wBoxMonOT", "wBoxMonNicks",
    "wCurrentBoxNum",
    # bag
    "wNumBagItems", "wBagItems", "wCurItem", "wItemQuantity",
    # overworld
    "wCurMap", "wLastMap", "wXCoord", "wYCoord", "wWalkCounter",
    "wStatusFlags4", "wStatusFlags5", "wStatusFlags6", "wStatusFlags7",
    "wJoyIgnore", "wFontLoaded", "wTextBoxID", "wLinkState",
    # menus (tilemap oracles + drivers)
    "wTileMap", "wMaxMenuItem", "wCurrentMenuItem", "wListScrollOffset",
    "wMenuWatchMovingOutOfBounds", "wMenuExitMethod", "wListMenuID",
    # battle
    "wIsInBattle", "wBattleType", "wBattleResult", "wCurOpponent", "wTrainerClass", "wTrainerNo",
    "wTrainerName", "wCurEnemyLevel", "wEnemyMonSpecies2", "wCurPartySpecies", "wMonDataLocation",
    "wEnemyMon", "wEnemyMonSpecies", "wEnemyMonHP", "wEnemyMonLevel",
    "wEnemyPartyCount", "wEnemyPartySpecies", "wEnemyMons", "wEnemyMon1", "wEnemyMon2", "wEnemyMonOT",
    "wEnemyMonNicks",
    # $FF between InitBattleCommon (engine/battle/core.asm:6688-6689) and EnemySendOutFirstMon
    # clearing it: the only window in which the enemy party may still be rewritten (A13)
    "wEnemyMonPartyPos",
    "wBattleMon", "wBattleMonSpecies", "wBattleMonHP", "wBattleMonStatus", "wBattleMonMoves",
    "wBattleMonLevel", "wBattleMonMaxHP", "wBattleMonPP",
    # named sub-fields of slot 1 (offsets of every other slot follow by struct size)
    "wPartyMon1HP", "wPartyMon1Status", "wPartyMon1Moves", "wPartyMon1PP", "wPartyMon1Level",
    "wPartyMon1MaxHP", "wEnemyMon1Species", "wEnemyMon1HP", "wEnemyMon1Moves", "wEnemyMon1PP",
    "wEnemyMonMoves", "wEnemyMonPP", "wEnemyMonStatus",
    "wPlayerMonNumber", "wPlayerSelectedMove", "wPlayerBattleStatus3",
    "wPlayerMonAttackMod", "wPlayerMonDefenseMod", "wPlayerMonSpeedMod", "wPlayerMonSpecialMod",
    "wPlayerMonAccuracyMod", "wPlayerMonEvasionMod",
    "wEnemyMonAttackMod", "wEnemyMonDefenseMod", "wEnemyMonSpeedMod", "wEnemyMonSpecialMod",
    "wEnemyMonAccuracyMod", "wEnemyMonEvasionMod",
    "wCapturedMonSpecies", "wGrassRate", "wGrassMons", "wWaterRate", "wWaterMons",
    "wWhichPokemon", "wMoveMonType", "wRemoveMonFromBox", "wEngagedTrainerClass", "wEngagedTrainerSet",
    # evolution / trade
    "wForceEvolution", "wEvolutionOccurred",
    "wTradedPlayerMonSpecies", "wTradedEnemyMonSpecies",
    "wInGameTradeGiveMonSpecies", "wInGameTradeReceiveMonSpecies",
    "wLinkEnemyTrainerName", "wSerialPartyMonsPatchList", "wSurroundingTiles", "wTileMapBackup",
    # SRAM
    "sPlayerName", "sMainData", "sSpriteData", "sPartyData", "sCurBoxData", "sTileAnimations",
    "sMainDataCheckSum", "sGameData", "sGameDataEnd", "sHallOfFame",
    "sBox1", "sBox2", "sBox6", "sBox7", "sBox12",
    "sBank2AllBoxesChecksum", "sBank2IndividualBoxChecksums",
    "sBank3AllBoxesChecksum", "sBank3IndividualBoxChecksums",
    # HRAM
    "hLoadedROMBank", "hJoyInput", "hJoyHeld", "hJoyLast", "hJoyPressed", "hFrameCounter",
    "hSerialConnectionStatus", "hTileAnimations", "hAutoBGTransferEnabled", "hWY",
    "hUILayoutFlags", "hDisableJoypadPolling", "hSoftReset",
]

# ROM routines the signals/writes layers hook. Locals ("Label.local") are fine: the .sym has them.
ROM_SYMBOLS = [
    "MainInBattleLoop", "ExecutePlayerMove", "RemoveFaintedPlayerMon", "HandlePlayerMonFainted",
    "ApplyOutOfBattlePoisonDamage", "ResetStatusAndHalveMoneyOnBlackout", "HealParty",
    "InitBattleCommon", "InitWildBattle", "EndOfBattle", "HandlePlayerBlackOut",
    "AddPartyMon", "SendNewMonToBox", "RemovePokemon", "AddEnemyMonToPlayerParty",
    "AddItemToInventory_.done", "RemoveItemFromInventory",
    "SaveMenu.save", "SaveGameData", "SavePartyAndDexData", "SaveMainData", "SaveCurrentBoxData",
    "ChangeBox", "EmptyAllSRAMBoxes", "CalcCheckSum", "CalcIndividualBoxCheckSums",
    "TryLoadSaveFile", "TryLoadSaveFile.done", "MainMenu", "MainMenu.choseContinue", "MainMenu.pressedA",
    "LoadMapHeader", "EnterMap", "SpecialEnterMap", "OverworldLoop", "OverworldLoopLessDelay",
    "DelayFrame", "DelayFrame.halt", "Joypad", "_Joypad",
    "TryEvolvingMon", "EvolutionAfterBattle", "Evolution_PartyMonLoop", "Evolution_ChangeMonPic",
    "InGameTrade_DoTrade", "CableClubNPC", "SoftReset", "Init",
    "DisplayPartyMenu", "StartMenu_Pokemon", "CalcStat", "CalcStats",
    # battle menu sites the live battle driver hooks (lua/tests/gen1_battle_driver.lua header)
    "DisplayBattleMenu", "MoveSelectionMenu", "SelectEnemyMove", "ExecuteEnemyMove",
    # ROM data tables the client reads (base stats for the withdraw rebuild; dex order)
    "BaseStats", "PokedexOrder",
    # pret data/wild/grass_water.asm:1,251-252; data/wild/good_rod.asm:2;
    # engine/items/item_effects.asm:1826-1830 (Yellow:2026-2030).
    "WildDataPointers", "GoodRodMons", "ItemUseOldRod",
]
# Symbols a title may legitimately lack (recorded when present, no failure when absent).
OPTIONAL_ROM_SYMBOLS = [
    "MewBaseStats",  # R/B keep Mew outside the table; Yellow has it inline as record 150
    "SuperRodData",  # pokered data/wild/super_rod.asm:2,35-38 (R/B only)
    "SuperRodFishingSlots",  # pokeyellow data/wild/super_rod.asm:1-2 (Yellow only)
]  # pureRGB: Mew is BaseStats record 150 and fishing is SuperRodData only, so both are absent there

# ROM symbols the pure scanners/generators need on top of ROM_SYMBOLS (pureRGB only; vanilla unchanged).
EXTRA_ROM_SYMBOLS = {
    "pret": [],
    "purergb": [
        "EvosMovesPointerTable", "TrainerDataPointers", "GoodRodMonsOcean", "NonDexMonsBaseStats",
        "MonsterNames", "MoveNameJumpTable", "ItemNameJumpTable", "TrainerNames", "Moves", "TypeEffects",
    ],
}

# RAM symbols the pure client reads on top of RAM_SYMBOLS (pureRGB only; vanilla's list is unchanged).
EXTRA_RAM_SYMBOLS = {
    "pret": [],
    "purergb": [
        "wDelayFrameBank", "wUsedItemOnWhichPokemon", "wSafariType", "wPkmnTypeRemapFlags",
        "wGameInternalVersion", "wPocketAbraNick", "wDayCareMon", "wDayCareInUse",
        "wBattleFunctionalFlags", "wEnemyMonSpecies2", "wOptions2", "hGBC", "wLoadedMonSpecies",
    ],
}

# pureRGB game constants the client needs that no symbol carries. Each value is asserted against
# the pinned source text it comes from and, where the ROM can show it, the built ROM.
PURERGB_CONSTANTS = {
    "ball_items": [1, 2, 3, 4, 5, 8], "opp_id_offset": 197, "bag_capacity": 30, "base_stats_stride": 35,
    "dex_count": 152, "species_count": 190, "rival_trainer_ids": [197 + 0x18, 197 + 0x28, 197 + 0x29],
    "wram_bank_gate": True, "hardware": "cgb",
}
PURERGB_CONSTANT_ASSERTS = {
    "ball_items": ("constants/item_constants.asm", [
        "\tconst MASTER_BALL   ; $01", "\tconst ULTRA_BALL    ; $02", "\tconst GREAT_BALL    ; $03",
        "\tconst POKE_BALL     ; $04", "\tconst HYPER_BALL    ; $05", "\tconst SAFARI_BALL   ; $08"]),
    "opp_id_offset": ("constants/trainer_constants.asm", ["DEF OPP_ID_OFFSET EQU 197"]),
    "bag_capacity": ("constants/menu_constants.asm", ["DEF BAG_ITEM_CAPACITY EQU 30"]),
    # 27 vanilla bytes + four added `rw` pointers = 35 (also proven from the dex bytes in the ROM)
    "base_stats_stride": ("constants/pokemon_data_constants.asm", [
        "DEF BASE_PICBANK     rw", "DEF BASE_BACKPICBANK rw", "DEF BASE_ALTFRONTPIC rw",
        "DEF BASE_ALTBACKPIC  rw", "DEF BASE_DATA_SIZE EQU _RS"]),
    "dex_count": ("constants/pokedex_constants.asm", [
        "\tconst DEX_MISSINGNO  ; 0", "\tconst DEX_MEW        ; 151", "DEF NUM_POKEMON EQU const_value"]),
    "species_count": ("constants/pokemon_constants.asm", [
        "\tconst VICTREEBEL         ; $BE", "DEF NUM_POKEMON_INDEXES EQU const_value - 1"]),
    "rival_trainer_ids": ("constants/trainer_constants.asm", [
        "\tDEF OPP_\\1 EQU OPP_ID_OFFSET + \\1", "\ttrainer_const RIVAL1         ; $18",
        "\ttrainer_const RIVAL2         ; $28", "\ttrainer_const RIVAL3         ; $29"]),
    "wram_bank_gate": ("home/vblank.asm", ["\tldh a, [hLoadedROMBank]\n\tld [wDelayFrameBank], a"]),
    "hardware": ("home/start.asm", ["\tcp BOOTUP_A_CGB\n\tld a, TRUE\n\tjr z, .gbc\n\tdec a\n.gbc\n\tldh [hGBC], a"]),
}


def parse_sym(path: pathlib.Path) -> dict[str, tuple[int, int]]:
    """{symbol: (bank, addr)} from an rgblink .sym file."""
    out: dict[str, tuple[int, int]] = {}
    pat = re.compile(r"^([0-9A-Fa-f]{2,3}):([0-9A-Fa-f]{4}) (\S+)$")
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = pat.match(line.strip())
        if m:
            out[m.group(3)] = (int(m.group(1), 16), int(m.group(2), 16))
    return out


def flat(bank: int, addr: int) -> int:
    return addr if addr < 0x4000 else bank * 0x4000 + (addr - 0x4000)


def _purergb_derived(syms: dict, ram: dict) -> dict:
    """pureRGB-only derived constants, each proven against the pinned source (and ROM where possible)."""
    for rel, needles in PURERGB_CONSTANT_ASSERTS.values():
        for needle in needles:
            F.assert_source("purergb", rel, needle)
    rom = F.rom_path("purergb", "purered").read_bytes()
    base = F.flat(*syms["BaseStats"])
    stride = PURERGB_CONSTANTS["base_stats_stride"]
    # BASE_DEX_NO is byte 0 of every record; records run Bulbasaur..Mew in dex order (base_stats.asm)
    if [rom[base + stride * k] for k in range(150)] != list(range(1, 151)):
        sys.exit("gen_gen1_profile: BaseStats stride is not 35 in the built pureRGB ROM")
    if rom[0x143] & 0x80 == 0:  # CGB flag in the cartridge header
        sys.exit("gen_gen1_profile: built pureRGB ROM is not CGB-flagged")
    derived = dict(PURERGB_CONSTANTS)
    # bag = count byte + BAG_ITEM_CAPACITY (id, qty) pairs + $FF terminator, then wPocketAbraNick
    derived["bag_capacity"] = (ram["wPocketAbraNick"] - ram["wBagItems"] - 1) // 2
    if derived["bag_capacity"] != PURERGB_CONSTANTS["bag_capacity"]:
        sys.exit("gen_gen1_profile: wBagItems..wPocketAbraNick does not hold BAG_ITEM_CAPACITY slots")
    return derived


def build(foundation: str = "pret") -> dict:
    fnd = F.foundation(foundation)
    lock = F.lock(foundation)
    rom_syms = None if lock else json.loads((REPO / "data" / "pret_rom_syms.json").read_text(encoding="utf-8"))
    profile: dict = {
        "schema": "gen1-profile-v1",
        "generator": "tools/gen_gen1_profile.py",
        "source": {},
        "titles": {},
    }
    missing: list[str] = []
    ram_symbols = RAM_SYMBOLS + EXTRA_RAM_SYMBOLS[foundation]
    for title, (sym_name, rom_file, repo) in fnd["titles"].items():
        sym_path = F.sym_path(foundation, title)
        syms = parse_sym(sym_path)
        profile["source"][sym_name] = {
            "repo": repo,
            "commit": lock["source"]["commit"] if lock else PRET_COMMITS[repo],
            "sha256": hashlib.sha256(sym_path.read_bytes()).hexdigest(),
        }
        ram: dict[str, int] = {}
        for name in ram_symbols:
            if name not in syms:
                missing.append(f"{title}: {name}")
                continue
            ram[name] = syms[name][1]  # RAM: bank is 0 (WRAM0/HRAM) or the SRAM bank; addr is what code reads
        sram_banks = {name: syms[name][0] for name in ram_symbols if name.startswith("s") and name in syms}
        rom: dict[str, dict] = {}
        for name in ROM_SYMBOLS + EXTRA_ROM_SYMBOLS[foundation] + OPTIONAL_ROM_SYMBOLS:
            if name not in syms:
                if name in ROM_SYMBOLS or name in EXTRA_ROM_SYMBOLS[foundation]:
                    missing.append(f"{title}: {name}")
                continue
            bank, addr = syms[name]
            rom[name] = {"bank": bank, "addr": addr, "flat": flat(bank, addr)}
        party_size = ram["wPartyMon2"] - ram["wPartyMon1"]
        capacity = (ram["wPartyMonOT"] - ram["wPartyMons"]) // party_size
        derived = {
            # struct geometry from symbol arithmetic, not from a constant someone typed
            "party_struct_size": party_size,
            "box_struct_size": ram["wBoxMon2"] - ram["wBoxMon1"],
            "battle_struct_size": ram["wEnemyMon2"] - ram["wEnemyMon1"],
            "party_capacity": capacity,
            "box_capacity": (ram["wBoxMonOT"] - ram["wBoxMons"]) // (ram["wBoxMon2"] - ram["wBoxMon1"]),
            "name_length": (ram["wPartyMonNicks"] - ram["wPartyMonOT"]) // capacity,
            "sram_box_stride": ram["sBox2"] - ram["sBox1"],
            "sram_boxes_per_bank": (ram["sBox6"] - ram["sBox1"]) // (ram["sBox2"] - ram["sBox1"]) + 1,
            "sram_box_banks": [sram_banks["sBox1"], sram_banks["sBox7"]],
        }
        if foundation == "purergb":
            derived.update(_purergb_derived(syms, ram))
        rom_key = pathlib.Path(rom_file).stem  # pokered / pokeblue / pokeyellow / pokegreen
        profile["titles"][title] = {
            "variant": title,  # server/adapters/gen1_rom_scan.py:70 maps these title keys to variants
            "repo": repo,
            "sym": sym_name,
            "rom_sha1": lock["outputs"][rom_key]["sha1"] if lock else rom_syms[rom_key]["rom_sha1"],
            "ram": ram,
            "sram_bank": sram_banks,
            "rom": rom,
            "derived": derived,
        }
    if missing:
        sys.exit("gen_gen1_profile: symbols missing from the .sym files:\n  " + "\n  ".join(missing))
    return profile


def render(profile: dict) -> str:
    return json.dumps(profile, indent=1, sort_keys=True) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="fail if the committed profile is stale")
    ap.add_argument("--foundation", default="pret", choices=sorted(F.FOUNDATIONS))
    args = ap.parse_args()
    out = F.data_dir(args.foundation) / "profile.json"
    text = render(build(args.foundation))
    if args.check:
        current = out.read_text(encoding="utf-8") if out.exists() else ""
        if current != text:
            print(f"{out.relative_to(REPO)} is stale; run tools/gen_gen1_profile.py", file=sys.stderr)
            return 1
        print(f"{out.relative_to(REPO)} is current")
        return 0
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8", newline="\n")
    t = json.loads(text)["titles"]
    print(f"wrote {out.relative_to(REPO)}: " + ", ".join(
        f"{k} ram={len(v['ram'])} rom={len(v['rom'])}" for k, v in t.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
