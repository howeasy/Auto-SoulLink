#!/usr/bin/env python3
"""Generate data/games/gen1_rby/profile.json from the pinned pret symbol files.

The Gen 1 client and adapter read every address from this file. Nothing downstream
types a hex address by hand; if a symbol is missing from a title's .sym the
generator fails, so the list below stays honest.

Inputs (committed, reproducible):
    data/pret/pokered.sym, pokeblue.sym   built from pret/pokered  405b6246372d7e5a2cb029cbb65219b13286b8c9
    data/pret/pokeyellow.sym              built from pret/pokeyellow 0a08515
    data/pret_rom_syms.json               clean ROM SHA-1 per title

    python tools/gen_gen1_profile.py            # rewrite the profile
    python tools/gen_gen1_profile.py --check    # exit 1 if the committed file is stale
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
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
]


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


def build() -> dict:
    rom_syms = json.loads((REPO / "data" / "pret_rom_syms.json").read_text(encoding="utf-8"))
    profile: dict = {
        "schema": "gen1-profile-v1",
        "generator": "tools/gen_gen1_profile.py",
        "source": {},
        "titles": {},
    }
    missing: list[str] = []
    for title, (repo, sym_name, rom_key) in TITLES.items():
        sym_path = SYMS / sym_name
        syms = parse_sym(sym_path)
        profile["source"][sym_name] = {
            "repo": repo,
            "commit": PRET_COMMITS[repo],
            "sha256": hashlib.sha256(sym_path.read_bytes()).hexdigest(),
        }
        ram: dict[str, int] = {}
        for name in RAM_SYMBOLS:
            if name not in syms:
                missing.append(f"{title}: {name}")
                continue
            ram[name] = syms[name][1]  # RAM: bank is 0 (WRAM0/HRAM) or the SRAM bank; addr is what code reads
        sram_banks = {name: syms[name][0] for name in RAM_SYMBOLS if name.startswith("s") and name in syms}
        rom: dict[str, dict] = {}
        for name in ROM_SYMBOLS + OPTIONAL_ROM_SYMBOLS:
            if name not in syms:
                if name in ROM_SYMBOLS:
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
        profile["titles"][title] = {
            "variant": title,  # server/adapters/gen1_rom_scan.py:70 maps these title keys to variants
            "repo": repo,
            "sym": sym_name,
            "rom_sha1": rom_syms[rom_key]["rom_sha1"],
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
    args = ap.parse_args()
    text = render(build())
    if args.check:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if current != text:
            print(f"{OUT.relative_to(REPO)} is stale; run tools/gen_gen1_profile.py", file=sys.stderr)
            return 1
        print(f"{OUT.relative_to(REPO)} is current")
        return 0
    OUT.write_text(text, encoding="utf-8", newline="\n")
    t = json.loads(text)["titles"]
    print(f"wrote {OUT.relative_to(REPO)}: " + ", ".join(
        f"{k} ram={len(v['ram'])} rom={len(v['rom'])}" for k, v in t.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
