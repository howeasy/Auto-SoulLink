#!/usr/bin/env python3
"""Verify every flat Gen 1 ROM offset this project depends on, against the real dumps.

WHY A SECOND VERIFIER. `tools/verify_profile_addresses.py` checks WRAM/SRAM symbols
against the pret symbol tables. It cannot check anything here: a flat file offset is not a
symbol, and the patch manifest's expected bytes are not addresses at all. Those two kinds
of claim fail in different ways and need different evidence, so they get different tools —
and every address this project introduces belongs in one of them, with no WARN and no SKIP
path that would let a missing check read as a passing one.

What is checked, all against the actual cartridge bytes:

  * every scanner offset resolves through `data/pret_rom_syms.json`, decoded as
    `bank << 16 | addr` (NOT a flat offset — decoding it wrongly is a trap this project
    has already fallen into once);
  * the scanners actually parse what is there: wild tables, all three rods, base stats
    for all 151 species, the evolution graph, the index-to-dex map;
  * every span in the companion-patch manifest holds exactly the bytes it expects to
    displace, and none of them touches the protected cartridge header;
  * the ROM0 free runs the patch reserves are still free.

Exit code is 0 only if every check passed on every ROM that is present. A ROM that is
absent is reported and is NOT counted as a pass.

    python tools/verify_gen1_rom_layout.py
    python tools/verify_gen1_rom_layout.py --json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
sys.path.insert(0, os.path.join(_REPO, "patch", "gen1", "tools"))

ROMS = {
    "red": "patch/build/gen1_red.gb",
    "blue": "patch/build/gen1_blue.gb",
    "yellow": "patch/build/gen1_yellow.gbc",
}

# The companion patch exists for Red and Blue only; Yellow has no free WRAM for a mailbox.
PATCHABLE = ("red", "blue")

CLEAN_SHA1 = {
    "red": "ea9bcae617fdf159b045185467ae58b2e4a48b9a",
    "blue": "d7037c83e1ae5b39bde3c30787637ba1d4c48ce2",
    "yellow": "cc7d03262ebfaf2f06772c1a480c7d9d5f4a38e1",
}


# ── UPR pointer roots ────────────────────────────────────────────────────────────────────
# data/games/gen1_rby/upr_layout.json carries the Universal Pokémon Randomizer's flat ROM
# offsets, and server/gen1_upr_scan.py walks tables from them to admit a randomized
# cartridge -- so a wrong root silently mis-scans. Every root is pinned two ways: to the
# pret symbol it lives in (label + instruction/record displacement, each displacement read
# off the pret asm named in the comment) and to the bytes pret says are there.

UPR_ROOTS_CHECK = "UPR pointer roots match pret symbols and clean-ROM bytes"

# Profile keys that are not ROM offsets: identity, counts, sizes, flags, tweak names.
_UPR_METADATA = frozenset({
    "Game", "Version", "NonJapanese", "Type", "ExtraTableFile", "BWXPTweak", "XAccNerfTweak",
    "CritRateTweak", "CRC32", "CopyTMText", "InternalPokemonCount", "PokemonNamesLength",
    "MoveCount", "PokemonMovesetsDataSize", "TradeTableSize", "TradeNameLength",
    "TradesUnused", "TrainerDataClassCounts", "PatchPokedex", "CanChangeStarterText",
    "CanChangeTrainerText", "StaticPokemonSupport",
})

# Yellow (U) is `CopyFrom=Red (U)` in gen1_offsets.ini and these keys are the Red values the
# copy carried over (tools/generate_gen1_upr_layout.py mirrors that copy). Neither UPR's
# Yellow branch (setStarters does its text/Pokédex patching for non-Yellow only; Yellow's
# hidden items walk the 3-byte SpecialMapPointerTable alone) nor gen1_upr_scan's yellow paths
# read them, so on Yellow they are pinned to Red's values, not to pokeyellow symbols.
_YELLOW_INHERITED = frozenset({
    "StarterOffsets3", "StarterTextOffsets", "StarterPokedexOnOffset",
    "StarterPokedexOffOffset", "StarterPokedexBranchOffset", "SpecialMapList",
    "PokedexRamOffset",
})

# Red/Blue starter-species sites: (pret label, displacement, form[, Route22 trainer no]).
# form "ld a": root-1 is the 0x3E opcode; "cp": root-1 is the 0xFE opcode; "db": a
# `db STARTERx, trainer_no` record of the Route22 rival .StarterTable (scripts/Route22.asm
# lines 143-147 and 299-302). Displacements verified against scripts/OaksLab.asm (194-200,
# 379-395, 797-824), scripts/CeruleanCity.asm (127-153), engine/battle/read_trainer_party.asm
# (133-137), scripts/SilphCo7F.asm (189-195), scripts/PokemonTower2F.asm (155-161),
# scripts/SSAnne2F.asm (104-110) and scripts/ChampionsRoom.asm (72-78).
_RB_STARTER_SITES = {
    "StarterOffsets1": [
        ("OaksLabBulbasaurPokeBallText", 0x02, "ld a"), ("OaksLabChoseStarterScript", 0x04, "cp"),
        ("OaksLabCharmanderPokeBallText", 0x0C, "ld a"), ("ReadTrainer", 0xA5, "cp"),
        ("Route22Rival1StartBattleScript", 0x51, "db", 6),
        ("Route22Rival2StartBattleScript", 0x56, "db", 12)],
    "StarterOffsets2": [
        ("OaksLabCharmanderPokeBallText", 0x02, "ld a"), ("CeruleanCityRivalBattleScript", 0x2A, "cp"),
        ("OaksLabChoseStarterScript", 0x08, "cp"), ("OaksLabRivalStartBattleScript", 0x0F, "cp"),
        ("OaksLabSquirtlePokeBallText", 0x0C, "ld a"),
        ("Route22Rival1StartBattleScript", 0x4D, "db", 4),
        ("Route22Rival2StartBattleScript", 0x52, "db", 10),
        ("SilphCo7FRivalStartBattleScript", 0x2D, "cp"), ("PokemonTower2FRivalText", 0x2F, "cp"),
        ("SSAnne2FRivalStartBattleScript", 0x20, "cp"),
        ("ChampionsRoomRivalReadyToBattleScript", 0x34, "cp")],
    "StarterOffsets3": [
        ("OaksLabSquirtlePokeBallText", 0x02, "ld a"), ("CeruleanCityRivalBattleScript", 0x32, "cp"),
        ("OaksLabRivalStartBattleScript", 0x17, "cp"), ("OaksLabBulbasaurPokeBallText", 0x0C, "ld a"),
        ("ReadTrainer", 0x9F, "cp"),
        ("Route22Rival1StartBattleScript", 0x4F, "db", 5),
        ("Route22Rival2StartBattleScript", 0x54, "db", 11),
        ("SilphCo7FRivalStartBattleScript", 0x35, "cp"), ("PokemonTower2FRivalText", 0x37, "cp"),
        ("SSAnne2FRivalStartBattleScript", 0x28, "cp"),
        ("ChampionsRoomRivalReadyToBattleScript", 0x3C, "cp")],
}


def _pret_enum(pret: Path, file: str) -> dict[str, int]:
    """Every const_def/const/const_skip/const_next enum in one pret constants file, plus
    the one-const macros pret layers on them (trainer_const, map_const)."""
    from tools.verify_gen1_constants import literal, source_text
    out: dict[str, int] = {}
    value = None
    for line in source_text(pret, file).splitlines():
        parts = line.split()
        if not parts:
            continue
        op, args = parts[0], parts[1:]
        if op == "const_def":
            value = literal(args[0]) if args else 0
        elif op == "const_next":
            value = literal(args[0])
        elif op == "const_skip" and value is not None:
            value += literal(args[0]) if args else 1
        elif op in ("const", "trainer_const", "map_const") and value is not None:
            out[args[0].rstrip(",")] = value
            value += 1
    return out


def verify_upr_roots(title: str, rom: bytes, syms: dict, layout: dict) -> str:
    """Pin every ROM-offset root of upr_layout.json profile `title` to its pret symbol and to
    the clean-ROM bytes pret's source says are there. Raises RomScanError naming every root
    that fails; a root that is neither symbol- nor byte-checkable is itself a failure."""
    import re

    from server.adapters.gen1_rom_scan import RomScanError, sym_to_offset
    from tools.verify_gen1_constants import constant, source_text

    yellow = title == "yellow"
    pret = Path(_REPO, ".cache", "pret", "pokeyellow" if yellow else "pokered")
    if not pret.is_dir():
        raise RomScanError(f"pret checkout {pret} is missing; roots cannot be source-pinned")
    profile = layout["profiles"][title]["settings"]
    text = {v: k for k, v in layout["text_encoding"].items()}
    ram = json.loads(Path(_REPO, "data/pret_syms.json").read_text(encoding="utf-8"))[
        "pokeyellow" if yellow else "pokered"]
    failures: list[str] = []
    done: set[str] = set()

    enums: dict[str, dict[str, int]] = {}

    def enum(file: str) -> dict[str, int]:
        if file not in enums:
            enums[file] = _pret_enum(pret, "constants/" + file)
        return enums[file]

    species = enum("pokemon_constants.asm")
    moves = enum("move_constants.asm")
    dex = enum("pokedex_constants.asm")
    maps = enum("map_constants.asm")

    def starter(name: str) -> int:
        # `DEF STARTER1 EQU CHARMANDER` (pokered) / `DEF STARTER_PIKACHU EQU PIKACHU`.
        m = re.search(rf"^\s*DEF\s+{name}\s+EQU\s+(\w+)",
                      source_text(pret, "constants/pokemon_constants.asm"), re.M)
        return species[m.group(1)]

    def sym(label: str) -> int:
        if label not in syms:
            raise RomScanError(f"{label} missing from the symbol table")
        return sym_to_offset(syms[label])

    def local(label: str) -> int:
        return syms[label] & 0xFFFF

    def word(off: int) -> int:
        return int.from_bytes(rom[off:off + 2], "little")

    def decode(off: int, limit: int = 20) -> str:
        out = []
        for b in rom[off:off + limit]:
            if b == 0x50:
                break
            out.append(text.get(b, f"\\x{b:02X}"))
        return "".join(out)

    def pin(name: str, root: int, label: str, delta: int, expect: str, ok: bool) -> None:
        done.add(name)
        want = sym(label) + delta
        if root != want:
            failures.append(f"{name}={root:#x} != {label}+{delta:#x} ({want:#x})")
        elif not ok:
            failures.append(f"{name}={root:#x} holds {rom[root - 1:root + 7].hex()}, "
                            f"expected {expect}")

    def same_bank_ptr(off: int, label: str) -> bool:
        # The scanner derives the target bank from the table's own offset.
        return word(off) == local(label) and off // 0x4000 == syms[label] >> 16

    cfg = profile  # short alias below

    # data/pokemon/dex_order.asm:3 -- first index (RHYDON) maps to DEX_RHYDON.
    pin("PokedexOrder", cfg["PokedexOrder"], "PokedexOrder", 0, "DEX_RHYDON",
        rom[cfg["PokedexOrder"]] == dex["DEX_RHYDON"])
    # data/pokemon/names.asm:3 -- dname "RHYDON", '@'-padded to NAME_LENGTH-1.
    pin("PokemonNamesOffset", cfg["PokemonNamesOffset"], "MonsterNames", 0, '"RHYDON"',
        decode(cfg["PokemonNamesOffset"], cfg["PokemonNamesLength"]) == "RHYDON")
    # data/pokemon/base_stats/bulbasaur.asm:1-3 -- db DEX_BULBASAUR; db hp, atk, def, spd, spc.
    stats = re.search(r"db\s+(\d+),\s*(\d+),\s*(\d+),\s*(\d+),\s*(\d+)",
                      source_text(pret, "data/pokemon/base_stats/bulbasaur.asm"))
    bulba = bytes([dex["DEX_BULBASAUR"], *map(int, stats.groups())])
    pin("PokemonStatsOffset", cfg["PokemonStatsOffset"], "BaseStats", 0, bulba.hex(),
        rom[cfg["PokemonStatsOffset"]:cfg["PokemonStatsOffset"] + 6] == bulba)
    if yellow:
        # Yellow keeps Mew inside BaseStats (no data/pokemon/mew.asm); UPR marks it absent.
        done.add("MewStatsOffset")
        if cfg["MewStatsOffset"] != 0:
            failures.append("MewStatsOffset should be 0 on Yellow")
    else:
        # data/pokemon/mew.asm:14 -> data/pokemon/base_stats/mew.asm:1 -- db DEX_MEW.
        pin("MewStatsOffset", cfg["MewStatsOffset"], "MewBaseStats", 0, "DEX_MEW",
            rom[cfg["MewStatsOffset"]] == dex["DEX_MEW"])
    # data/wild/grass_water.asm:3 -- dw NothingWildMons ; PALLET_TOWN.
    pin("WildPokemonTableOffset", cfg["WildPokemonTableOffset"], "WildDataPointers", 0,
        "dw NothingWildMons", same_bank_ptr(cfg["WildPokemonTableOffset"], "NothingWildMons"))
    # engine/items/item_effects.asm ItemUseOldRod: call FishingInit (3) + jp c, ItemUseNotTime
    # (3) put `lb bc, 5, MAGIKARP` = 01 <MAGIKARP> 05 at +6; UPR/the scanner read +1.
    old = cfg["OldRodOffset"]
    pin("OldRodOffset", old, "ItemUseOldRod", 6, "01 MAGIKARP 05",
        rom[old:old + 3] == bytes([0x01, species["MAGIKARP"], 5]))
    # data/wild/good_rod.asm:4-5 -- db 10, GOLDEEN / db 10, POLIWAG; UPR reads +1 and +3.
    good = cfg["GoodRodOffset"]
    pin("GoodRodOffset", good, "GoodRodMons", 0, "0a GOLDEEN 0a POLIWAG",
        rom[good:good + 4] == bytes([10, species["GOLDEEN"], 10, species["POLIWAG"]]))
    sup = cfg["SuperRodTableOffset"]
    if yellow:
        # data/wild/super_rod.asm:2 -- db PALLET_TOWN, STARYU, 10, TENTACOOL, 10, ...
        pin("SuperRodTableOffset", sup, "SuperRodFishingSlots", 0,
            "PALLET_TOWN STARYU 0a TENTACOOL 0a",
            rom[sup:sup + 5] == bytes([maps["PALLET_TOWN"], species["STARYU"], 10,
                                       species["TENTACOOL"], 10]))
    else:
        # data/wild/super_rod.asm:4 -- dbw PALLET_TOWN, .Group1 (a local label the symbol
        # table omits): the pointer must land in this bank past the table on a 1..4 count.
        grp = sup // 0x4000 * 0x4000 + word(sup + 1) - 0x4000
        pin("SuperRodTableOffset", sup, "SuperRodData", 0, "dbw PALLET_TOWN, .Group1",
            rom[sup] == maps["PALLET_TOWN"] and 0x4000 <= word(sup + 1) < 0x8000
            and grp > sup and 1 <= rom[grp] <= 4)
    # data/maps/town_map_entries.asm:10 -- outdoor_map 2, 11, PalletTownName = dn 11, 2 (0xB2)
    # + dw PalletTownName.
    names = cfg["MapNameTableOffset"]
    pin("MapNameTableOffset", names, "ExternalMapEntries", 0, "b2 + dw PalletTownName",
        rom[names] == 0xB2 and word(names + 1) == local("PalletTownName"))
    # data/moves/moves.asm:13 -- move POUND, NO_ADDITIONAL_EFFECT, 40, NORMAL, 100, 35.
    mv = cfg["MoveDataOffset"]
    pin("MoveDataOffset", mv, "Moves", 0, "POUND 00 28 NORMAL ff 23",
        rom[mv:mv + 6] == bytes([moves["POUND"], 0, 40, enum("type_constants.asm")["NORMAL"],
                                 255, 35]))
    # data/moves/names.asm:4 -- li "POUND".
    pin("MoveNamesOffset", cfg["MoveNamesOffset"], "MoveNames", 0, '"POUND"',
        decode(cfg["MoveNamesOffset"]) == "POUND")
    # data/items/names.asm:3 -- li "MASTER BALL".
    pin("ItemNamesOffset", cfg["ItemNamesOffset"], "ItemNames", 0, '"MASTER BALL"',
        decode(cfg["ItemNamesOffset"]) == "MASTER BALL")
    # data/types/type_matchups.asm:3 -- db WATER, FIRE, SUPER_EFFECTIVE (battle_constants:55).
    types = enum("type_constants.asm")
    te = cfg["TypeEffectivenessOffset"]
    pin("TypeEffectivenessOffset", te, "TypeEffects", 0, "WATER FIRE SUPER_EFFECTIVE",
        rom[te:te + 3] == bytes([types["WATER"], types["FIRE"],
                                 constant(pret, "SUPER_EFFECTIVE", "constants/battle_constants.asm")]))
    # data/pokemon/evos_moves.asm:13 -- dw RhydonEvosMoves.
    pin("PokemonMovesetsTableOffset", cfg["PokemonMovesetsTableOffset"], "EvosMovesPointerTable",
        0, "dw RhydonEvosMoves",
        same_bank_ptr(cfg["PokemonMovesetsTableOffset"], "RhydonEvosMoves"))
    extra = cfg["PokemonMovesetsExtraSpaceOffset"]
    if yellow:
        done.add("PokemonMovesetsExtraSpaceOffset")
        if extra != 0:
            failures.append("PokemonMovesetsExtraSpaceOffset should be 0 on Yellow")
    else:
        # engine/battle/move_effects/reflect_light_screen.asm:43-45 -- EffectCallBattleCore is
        # `ld b, BANK(BattleCore)` (2) + `jp Bankswitch` (3), the last routine in bank $0E; the
        # extra space is the free run from its end to the bank boundary.
        pin("PokemonMovesetsExtraSpaceOffset", extra, "EffectCallBattleCore", 5,
            "06 BANK(BattleCore) c3 Bankswitch then zeros to the bank end",
            rom[extra - 5:extra] == bytes([0x06, syms["BattleCore"] >> 16, 0xC3]) + local("Bankswitch").to_bytes(2, "little")
            and not any(rom[extra:(extra // 0x4000 + 1) * 0x4000]))

    def starter_sites(name, sites, want):
        if len(cfg[name]) != len(sites):
            failures.append(f"{name} has {len(cfg[name])} entries, expected {len(sites)}")
        for root, site in zip(cfg[name], sites, strict=False):
            label, delta, form = site[:3]
            if form == "db":
                ok = rom[root:root + 2] == bytes([want, site[3]])
            else:
                ok = rom[root - 1:root + 1] == bytes([0x3E if form == "ld a" else 0xFE, want])
            pin(name, root, label, delta, f"{form} {want:#x}", ok)

    if yellow:
        # scripts/PalletTown.asm:145 `ld a, STARTER_PIKACHU` (+0xF after ld a/ld [nn]/xor a/
        # ld [nn]/ld a/ld [nn]); scripts/OaksLab.asm:1019 (+2 after text_asm) and :1033 (+0x27).
        starter_sites("StarterOffsets1", [("PalletTownPikachuBattleScript", 0x0F, "ld a"),
                                          ("OaksLabPlayerReceivedMonText", 0x02, "ld a"),
                                          ("OaksLabPlayerReceivedMonText", 0x27, "ld a")],
                      starter("STARTER_PIKACHU"))
        # data/trainers/parties.asm:491-493 -- Rival1Data: db 5, EEVEE, 0 (the rival's starter
        # is a trainer-party byte, which is why the scanner aliases it with the trainer walk).
        r1 = cfg["StarterOffsets2"][0]
        pin("StarterOffsets2", r1, "Rival1Data", 1, "05 EEVEE 00",
            rom[r1 - 1:r1 + 2] == bytes([5, species["EEVEE"], 0]) and len(cfg["StarterOffsets2"]) == 1)
    else:
        for name, const in (("StarterOffsets1", "STARTER1"), ("StarterOffsets2", "STARTER2"),
                            ("StarterOffsets3", "STARTER3")):
            starter_sites(name, _RB_STARTER_SITES[name], starter(const))
        # text/OaksLab.asm:28-29 etc. -- +1 skips the `text` command byte (0x00) so UPR's
        # rewrite lands on the string body; the clean body opens "So! You want".
        for i, label in enumerate(("_OaksLabYouWantCharmanderText", "_OaksLabYouWantSquirtleText",
                                   "_OaksLabYouWantBulbasaurText")):
            root = cfg["StarterTextOffsets"][i]
            pin("StarterTextOffsets", root, label, 1, '00 "So! You want"',
                rom[root - 1] == 0x00 and decode(root, 12) == "So! You want")
        # engine/events/starter_dex.asm:3-9 -- ld a, mask (3E nn) / ld [wPokedexOwned], a (EA lo hi)
        # / predef ShowPokedexData (5) / xor a (AF) / ld [wPokedexOwned], a. UPR redirects both
        # writes into a branch it places in the same bank's free tail.
        mask = sum(1 << (dex[d] - 1) for d in ("DEX_BULBASAUR", "DEX_IVYSAUR", "DEX_CHARMANDER",
                                                "DEX_SQUIRTLE"))
        owned = ram["wPokedexOwned"].to_bytes(2, "little")
        on, off, br = (cfg["StarterPokedexOnOffset"], cfg["StarterPokedexOffOffset"],
                       cfg["StarterPokedexBranchOffset"])
        pin("StarterPokedexOnOffset", on, "StarterDex", 0, "3e mask ea wPokedexOwned",
            rom[on:on + 5] == bytes([0x3E, mask, 0xEA]) + owned)
        pin("StarterPokedexOffOffset", off, "StarterDex", 0xA, "af ea wPokedexOwned",
            rom[off:off + 4] == b"\xaf\xea" + owned)
        # The branch target is UPR-chosen free space, not a pret label: it must sit in
        # StarterDex's bank (the redirect is a bank-local jp), past every symbol of that bank,
        # and be all zero up to the bank boundary.
        done.add("StarterPokedexBranchOffset")
        bank = sym("StarterDex") // 0x4000
        last = max(sym_to_offset(v) for v in syms.values()
                   if sym_to_offset(v) // 0x4000 == bank and (v >> 16) == bank)
        if not (br // 0x4000 == bank and last < br and not any(rom[br:(bank + 1) * 0x4000])):
            failures.append(f"StarterPokedexBranchOffset={br:#x} is not free tail space of "
                            f"bank {bank:#x} (last symbol {last:#x})")
        done.add("PokedexRamOffset")
        if cfg["PokedexRamOffset"] != ram["wPokedexOwned"]:
            failures.append(f"PokedexRamOffset={cfg['PokedexRamOffset']:#x} != wPokedexOwned")

    # data/trainers/parties.asm:3 -- dw YoungsterData.
    pin("TrainerDataTableOffset", cfg["TrainerDataTableOffset"], "TrainerDataPointers", 0,
        "dw YoungsterData", same_bank_ptr(cfg["TrainerDataTableOffset"], "YoungsterData"))
    trainers = enum("trainer_constants.asm")
    xm = cfg["ExtraTrainerMovesTableOffset"]
    if yellow:
        # data/trainers/special_moves.asm:7-8 -- db BUG_CATCHER, 15 / db 2, 2, TACKLE.
        pin("ExtraTrainerMovesTableOffset", xm, "SpecialTrainerMoves", 0, "BUG_CATCHER 0f 02 02 TACKLE",
            rom[xm:xm + 5] == bytes([trainers["BUG_CATCHER"], 15, 2, 2, moves["TACKLE"]]))
        done.add("GymLeaderMovesTableOffset")
        if cfg["GymLeaderMovesTableOffset"] != 0:
            failures.append("GymLeaderMovesTableOffset should be 0 on Yellow")
    else:
        # data/trainers/special_moves.asm:20-21 -- TeamMoves: db LORELEI, BLIZZARD / db BRUNO, FISSURE.
        pin("ExtraTrainerMovesTableOffset", xm, "TeamMoves", 0, "LORELEI BLIZZARD BRUNO FISSURE",
            rom[xm:xm + 4] == bytes([trainers["LORELEI"], moves["BLIZZARD"], trainers["BRUNO"],
                                     moves["FISSURE"]]))
        # data/trainers/special_moves.asm:5-8 -- LoneMoves: db 1, BIDE / db 1, BUBBLEBEAM; UPR
        # addresses the move byte of record 0 (+1) and steps by 2 (tools/upr handler 0x39D23+i*2).
        gl = cfg["GymLeaderMovesTableOffset"]
        pin("GymLeaderMovesTableOffset", gl, "LoneMoves", 1, "01 BIDE 01 BUBBLEBEAM",
            rom[gl - 1:gl + 3] == bytes([1, moves["BIDE"], 1, moves["BUBBLEBEAM"]]))
    # data/moves/tmhm_moves.asm:7 -- db TM01_MOVE, which constants/item_constants.asm defines
    # from the first add_tm line.
    tm01 = re.search(r"^\s*add_tm\s+(\w+)", source_text(pret, "constants/item_constants.asm"),
                     re.M).group(1)
    pin("TMMovesOffset", cfg["TMMovesOffset"], "TechnicalMachines", 0, f"TM01 = {tm01}",
        rom[cfg["TMMovesOffset"]] == moves[tm01])
    # data/trainers/name_pointers.asm -- NUM_TRAINERS (47) dw entries, then .YoungsterName:
    # the first pointer must address the byte right after the table; data/trainers/names.asm:3
    # -- li "YOUNGSTER".
    tn0, tn1 = cfg["TrainerClassNamesOffsets"]
    pin("TrainerClassNamesOffsets", tn0, "TrainerNamePointers", 0x5E, '.YoungsterName "YOUNGSTER"',
        word(sym("TrainerNamePointers")) == (syms["TrainerNamePointers"] & 0xFFFF) + 0x5E
        and decode(tn0) == "YOUNGSTER")
    pin("TrainerClassNamesOffsets", tn1, "TrainerNames", 0, '"YOUNGSTER"', decode(tn1) == "YOUNGSTER")
    # engine/movie/oak_speech/oak_speech.asm -- `ld a, POTION` (pokered:54, pokeyellow:62) and
    # `ld a, NIDORINO` (pokered:75) / `ld a, STARTER_PIKACHU` (pokeyellow:83), each 3E nn EA.
    intro = starter("STARTER_PIKACHU") if yellow else species["NIDORINO"]
    ip, pc = cfg["IntroPokemonOffset"], cfg["PCPotionOffset"]
    pin("IntroPokemonOffset", ip, "OakSpeech", 0x56 if yellow else 0x58, f"3e {intro:#x} ea",
        rom[ip - 1:ip + 2] == bytes([0x3E, intro, 0xEA]))
    potion = enum("item_constants.asm")["POTION"]
    pin("PCPotionOffset", pc, "OakSpeech", 0x1D if yellow else 0x1F, f"3e POTION({potion:#x}) ea",
        rom[pc - 1:pc + 2] == bytes([0x3E, potion, 0xEA]))
    # home/text.asm TextCommandSounds (pokered:553, pokeyellow:560) -- entry 7 is
    # `db TX_SOUND_CRY_NIDORINA, NIDORINA` / `db TX_SOUND_CRY_PIKACHU, STARTER_PIKACHU`, both
    # $14; UPR addresses its species byte (7*2+1).
    cry = starter("STARTER_PIKACHU") if yellow else species["NIDORINA"]
    ic = cfg["IntroCryOffset"]
    pin("IntroCryOffset", ic, "TextCommandSounds", 0xF, f"14 {cry:#x}",
        rom[ic - 1:ic + 1] == bytes([0x14, cry]))
    # data/maps/map_header_banks.asm:4 -- db BANK(PalletTown_h); map_header_pointers.asm:4 --
    # dw PalletTown_h.
    pin("MapBanks", cfg["MapBanks"], "MapHeaderBanks", 0, "BANK(PalletTown_h)",
        rom[cfg["MapBanks"]] == syms["PalletTown_h"] >> 16)
    pin("MapAddresses", cfg["MapAddresses"], "MapHeaderPointers", 0, "dw PalletTown_h",
        word(cfg["MapAddresses"]) == local("PalletTown_h"))
    sp = cfg["SpecialMapPointerTable"]
    if yellow:
        # data/events/hidden_events.asm:1-7 -- hidden_event_map SILPH_CO_11F = db map, dw
        # HiddenEventsFor_SILPH_CO_11F (3-byte records, no separate map list on Yellow).
        pin("SpecialMapPointerTable", sp, "HiddenEventMaps", 0, "SILPH_CO_11F dw HiddenEventsFor_SILPH_CO_11F",
            rom[sp] == maps["SILPH_CO_11F"] and same_bank_ptr(sp + 1, "HiddenEventsFor_SILPH_CO_11F"))
    else:
        # data/events/hidden_events.asm:9-10 -- HiddenEventMaps: hidden_event_map REDS_HOUSE_2F;
        # :97-101 -- HiddenEventPointers: dw HiddenEventsFor_REDS_HOUSE_2F.
        pin("SpecialMapList", cfg["SpecialMapList"], "HiddenEventMaps", 0, "REDS_HOUSE_2F",
            rom[cfg["SpecialMapList"]] == maps["REDS_HOUSE_2F"])
        pin("SpecialMapPointerTable", sp, "HiddenEventPointers", 0, "dw HiddenEventsFor_REDS_HOUSE_2F",
            same_bank_ptr(sp, "HiddenEventsFor_REDS_HOUSE_2F"))
    # engine/events/hidden_items.asm:1-2 -- HiddenItems: ld hl, HiddenItemCoords (21 lo hi).
    hi = cfg["HiddenItemRoutine"]
    pin("HiddenItemRoutine", hi, "HiddenItems", 0, "21 HiddenItemCoords",
        rom[hi] == 0x21 and word(hi + 1) == local("HiddenItemCoords"))
    # data/events/trades.asm:18 -- first npctrade give, get, dialog, "name".
    tr = re.search(r'npctrade\s+(\w+),\s*(\w+),\s*(\w+),\s*"([^"]+)"',
                   source_text(pret, "data/events/trades.asm"))
    dialog = enum("script_constants.asm")[tr.group(3)]
    tt = cfg["TradeTableOffset"]
    pin("TradeTableOffset", tt, "TradeMons", 0, f"{tr.group(1)} {tr.group(2)} {tr.group(3)} {tr.group(4)!r}",
        rom[tt:tt + 3] == bytes([species[tr.group(1)], species[tr.group(2)], dialog])
        and decode(tt + 3, cfg["TradeNameLength"]) == tr.group(4))
    # home/print_text.asm:4-5 -- PrintLetterDelay: ld a, [wStatusFlags5] (FA lo hi); UPR's
    # "fastest text" overwrites the opcode with ret.
    td = cfg["TextDelayFunctionOffset"]
    pin("TextDelayFunctionOffset", td, "PrintLetterDelay", 0, "fa wStatusFlags5",
        rom[td] == 0xFA and word(td + 1) == ram["wStatusFlags5"])
    # scripts/ViridianCity.asm -- `ld a, WEEDLE` (pokered:79) / `ld a, RATTATA` (pokeyellow:105).
    tut = species["RATTATA" if yellow else "WEEDLE"]
    ct = cfg["CatchingTutorialMonOffset"]
    pin("CatchingTutorialMonOffset", ct, "ViridianCityOldManStartCatchTrainingScript",
        0x20 if yellow else 0x23, f"3e {tut:#x} ea", rom[ct - 1:ct + 2] == bytes([0x3E, tut, 0xEA]))
    # data/pokemon/palettes.asm:3-4 -- db PAL_MEWMON ; MISSINGNO / db PAL_GREENMON ; BULBASAUR.
    pals = enum("palette_constants.asm")
    mp = cfg["MonPaletteIndicesOffset"]
    pin("MonPaletteIndicesOffset", mp, "MonsterPalettes", 0, "PAL_MEWMON PAL_GREENMON",
        rom[mp:mp + 2] == bytes([pals["PAL_MEWMON"], pals["PAL_GREENMON"]]))
    # data/sgb/sgb_palettes.asm:4 -- first RGB r,g,b of PAL_ROUTE as a little-endian BGR555 word.
    r, g, b = map(int, re.search(r"RGB\s+(\d+),\s*(\d+),\s*(\d+)",
                                 source_text(pret, "data/sgb/sgb_palettes.asm")).groups())
    sg = cfg["SGBPalettesOffset"]
    pin("SGBPalettesOffset", sg, "SuperPalettes", 0, f"RGB {r},{g},{b}",
        word(sg) == r | g << 5 | b << 10)
    if yellow:
        # scripts/CeruleanMelaniesHouse.asm:20-22 -- cp 147 / jr c (FE 93 38): the Pikachu
        # happiness gate on the Bulbasaur gift; UPR nops the jr for a non-Pikachu starter.
        ph = cfg["PikachuHappinessCheckOffset"]
        pin("PikachuHappinessCheckOffset", ph, "CeruleanMelanieHouseMelanieText", 0x18, "fe 93 38",
            rom[ph - 2:ph + 1] == bytes([0xFE, 147, 0x38]))
        # engine/items/item_effects.asm:812-813 -- callfar IsThisPartyMonStarterPikachu (ends in
        # CD lo hi) then `jr nc, .notPlayerPikachu` (30 rr); UPR's "evolve Pikachu" tweak makes
        # it unconditional. Not consumed by gen1_upr_scan; pinned because it is a ROM root.
        pe = cfg["PikachuEvoJumpOffset"]
        pin("PikachuEvoJumpOffset", pe, "ItemUseEvoStone", 0x39, "cd .. .. 30",
            rom[pe - 3] == 0xCD and rom[pe] == 0x30)
        red = layout["profiles"]["red"]["settings"]
        for name in sorted(_YELLOW_INHERITED):
            done.add(name)
            if cfg[name] != red[name]:
                failures.append(f"{name} on Yellow should equal Red's CopyFrom value {red[name]!r}")

    unverified = [k for k, v in cfg.items()
                  if k not in done and k not in _UPR_METADATA
                  and (isinstance(v, int) or isinstance(v, list) and all(isinstance(x, int) for x in v))]
    failures.extend(f"unverified: {k}" for k in unverified)
    if failures:
        raise RomScanError("; ".join(failures))
    note = f"; {len(_YELLOW_INHERITED)} CopyFrom=Red (U) values pinned to Red" if yellow else ""
    return f"{len(done)} roots pinned to {pret.name} symbols and clean bytes{note}"


def _rows_for(title: str, rom: bytes, layout: dict | None = None) -> list[tuple[str, bool, str]]:
    """(check, ok, detail) for one ROM. `layout` overrides upr_layout.json (tests)."""
    from server.adapters.gen1_rom_scan import (
        RomScanError,
        _syms_for,
        evolution_graph,
        identify,
        scan_base_stats,
        scan_fishing,
        scan_pokedex_order,
        scan_wild,
        sym_to_offset,
    )
    rows: list[tuple[str, bool, str]] = []

    def check(name, fn):
        try:
            rows.append((name, True, fn()))
        except Exception as exc:                       # noqa: BLE001
            rows.append((name, False, f"{type(exc).__name__}: {exc}"))

    def _identity():
        value = identify(rom)
        if value["variant"] != title or value["sha1"] != CLEAN_SHA1[title]:
            raise RomScanError(f"expected canonical {title} {CLEAN_SHA1[title]}, got "
                               f"{value['variant']} {value['sha1']}")
        return f"{title} SHA-1={value['sha1']}"
    check("exact supported canonical ROM", _identity)

    def _symbols():
        _ident, syms = _syms_for(rom)
        wanted = ["WildDataPointers", "BaseStats", "EvosMovesPointerTable", "PokedexOrder"]
        out = []
        for name in wanted:
            if name not in syms:
                raise RomScanError(f"{name} missing from the symbol table")
            out.append(f"{name}={sym_to_offset(syms[name]):#07x}")
        return "  ".join(out)
    check("scanner symbols resolve (bank<<16|addr decoded)", _symbols)

    def _wild():
        w = scan_wild(rom)
        if len(w) < 50:
            raise RomScanError(f"only {len(w)} encounter maps")
        return f"{len(w)} maps"
    check("wild tables parse", _wild)

    def _fish():
        f = scan_fishing(rom)
        for rod in ("old_rod", "good_rod", "super_rod"):
            if rod not in f:
                raise RomScanError(f"{rod} missing")
        return "old/good/super all present"
    check("all three fishing rods parse", _fish)

    def _stats():
        st = scan_base_stats(rom)
        missing = sorted(set(range(1, 152)) - set(st))
        if missing:
            raise RomScanError(f"missing dex numbers {missing}")
        return "151 species incl. Mew"
    check("base stats cover every species", _stats)

    def _evos():
        g = evolution_graph(rom)
        edges = sum(len(v) for v in g.values())
        if edges != 72:
            raise RomScanError(f"{edges} evolution edges, expected 72")
        return "72 edges over 190 indexes"
    check("evolution graph parses", _evos)

    def _dex():
        order = scan_pokedex_order(rom)
        live = [x for x in order if x]
        if len(live) != 151:
            raise RomScanError(f"{len(live)} live dex entries")
        return "151 entries"
    check("index-to-dex map parses", _dex)

    from tools.gen1_patch_validation import verify_future_hook_anchors
    check("canonical service/trade prerequisites (not feature proof)",
          lambda: verify_future_hook_anchors(title, rom, _syms_for(rom)[1]))

    def _upr_roots():
        lay = layout or json.loads(Path(_REPO, "data/games/gen1_rby/upr_layout.json")
                                   .read_text(encoding="utf-8"))
        return verify_upr_roots(title, rom, _syms_for(rom)[1], lay)
    check(UPR_ROOTS_CHECK, _upr_roots)

    if title in PATCHABLE:
        import manifest

        from tools.gen1_patch_validation import verify_anchors, verify_assembly_references

        check("complete manifest geometry, source anchors and call banks",
              lambda: verify_anchors(rom, _syms_for(rom)[1], manifest))

        def _assembly():
            source = Path(_REPO, "patch/gen1/src/slink.asm").read_text(encoding="utf-8")
            ram = json.loads(Path(_REPO, "data/pret_syms.json").read_text(encoding="utf-8"))
            return verify_assembly_references(source, _syms_for(rom)[1], ram["pokered"])
        check("all external assembly addresses/banks resolve", _assembly)

        def _spans():
            lo, hi = manifest.PROTECTED_RANGE
            bad = []
            for off, original, new, why in manifest.MENU_PATCHES:
                if not (off + len(new) <= lo or off > hi):
                    bad.append(f"{off:#06x} overlaps the protected header ({why})")
                found = rom[off:off + len(original)]
                if found != original:
                    bad.append(f"{off:#06x} holds {found.hex()}, expected "
                               f"{original.hex()} ({why})")
            if bad:
                raise RomScanError("; ".join(bad))
            return f"{len(manifest.MENU_PATCHES)} spans, header untouched"
        check("companion-patch spans hold their expected bytes", _spans)

        def _hook():
            site = rom[manifest.HOOK_SITE:manifest.HOOK_SITE + len(manifest.HOOK_ORIGINAL)]
            if site != manifest.HOOK_ORIGINAL:
                raise RomScanError(f"{manifest.HOOK_SITE:#06x} holds {site.hex()}")
            return f"{manifest.HOOK_SITE:#06x} = farcall TrackPlayTime"
        check("the VBlank hook site is intact", _hook)

        def _bank():
            base = manifest.INJECT_OFFSET
            if any(rom[base:base + manifest.BANK_SIZE]):
                raise RomScanError(f"bank {manifest.HOOK_BANK:#x} is not empty")
            return f"bank {manifest.HOOK_BANK:#x} is {manifest.BANK_SIZE} bytes of zero"
        check("the target bank is free", _bank)

        def _free_runs():
            # The two ROM0 runs the patch reserves. 0x00BE..0x00FF is 66 usable bytes --
            # the zero run continues to 0x0100, but that byte is the cartridge entrypoint.
            for start, end, what in ((0x00BE, 0x0100, "ROM0 stub run"),
                                     (0x3FA6, 0x4000, "ROM0 trampoline run")):
                used = [i for i in range(start, end) if rom[i]]
                if used:
                    raise RomScanError(f"{what} {start:#06x}-{end:#06x} is not free "
                                       f"(first used byte {used[0]:#06x})")
            if rom[0x0100:0x0104] != bytes([0x00, 0xC3, 0x50, 0x01]):
                raise RomScanError("0x0100 is not the expected `nop; jp $0150` entrypoint")
            return "0x00BE-0x00FF and 0x3FA6-0x3FFF free; entrypoint intact"
        check("the reserved ROM0 runs are still free", _free_runs)

    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    report: dict[str, list] = {}
    ok_total = fail_total = missing = 0

    for title, rel in ROMS.items():
        path = os.path.join(_REPO, rel)
        if not os.path.exists(path):
            report[title] = [("ROM present", False, f"{rel} not found")]
            missing += 1
            continue
        with open(path, "rb") as f:
            rows = _rows_for(title, f.read())
        report[title] = rows
        ok_total += sum(1 for _n, ok, _d in rows if ok)
        fail_total += sum(1 for _n, ok, _d in rows if not ok)

    import manifest

    from tools.gen1_patch_validation import verify_generated_payload
    try:
        detail = verify_generated_payload(manifest)
        report["generated_payload"] = [("fresh assembly matches published bytes", True, detail)]
        ok_total += 1
    except Exception as exc:
        report["generated_payload"] = [("fresh assembly matches published bytes", False,
                                        f"{type(exc).__name__}: {exc}")]
        fail_total += 1

    if args.json:
        print(json.dumps({t: [{"check": n, "ok": o, "detail": d} for n, o, d in rows]
                          for t, rows in report.items()}, indent=2))
    else:
        for title, rows in report.items():
            print(f"\n── {title} " + "─" * (60 - len(title)))
            for name, ok, detail in rows:
                print(f"  [{'ok' if ok else 'FAIL'}] {name}  — {detail}")
        print(f"\nSummary: {ok_total} ok / {fail_total} fail / {missing} ROM(s) missing")

    # A missing ROM is not a pass. It is the difference between "verified" and "not run",
    # and the release gate needs to be able to tell them apart.
    return 0 if (fail_total == 0 and missing == 0) else 1


if __name__ == "__main__":
    sys.exit(main())
