#!/usr/bin/env python3
"""Strict Gen 1 constants and storage-structure evidence from pinned pret sources.

This is a source/structure gate, not proof of emulator transformations. Missing
sources, symbols, or a changed source expression are failures, never skips. The
canonical-source gate separately verifies the source and artifact hash chain.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
SOURCE_ROOT = ROOT / ".cache" / "pret"
GEN1_REPOS = {
    "red": "pokered", "blue": "pokered", "yellow": "pokeyellow",
    "red_ap": "alchav_pokered", "blue_ap": "alchav_pokered",
}


class EvidenceError(ValueError):
    """An expected source-backed invariant could not be established."""


def source_text(repo: pathlib.Path, name: str) -> str:
    return re.sub(r";[^\n]*", "", (repo / name).read_text(encoding="utf-8"))


def literal(value: str) -> int:
    value = value.strip()
    if re.fullmatch(r"\$[\da-fA-F]+", value):
        return int(value[1:], 16)
    if re.fullmatch(r"%[01]+", value):
        return int(value[1:], 2)
    if re.fullmatch(r"\d+", value):
        return int(value, 10)
    raise EvidenceError(f"not a literal constant: {value!r}")


def constant(repo: pathlib.Path, name: str, file: str) -> int:
    matches = re.findall(rf"^\s*(?:DEF\s+)?{re.escape(name)}\s+EQU\s+([^\n]+)",
                         source_text(repo, file), re.M)
    if len(matches) != 1:
        raise EvidenceError(f"{repo.name}/{file}: expected one definition of {name}")
    return literal(matches[0])


def enum_prefix(repo: pathlib.Path, file: str, names: list[str]) -> dict[str, int]:
    """Read const_def/const sequences; reject unsupported directives before targets."""
    found = {}
    current = None
    for line in source_text(repo, file).splitlines():
        line = line.strip()
        if line.startswith("const_def"):
            args = line.split(maxsplit=1)
            current = literal(args[1]) if len(args) == 2 else 0
        elif line.startswith("const ") or line.startswith("const\t"):
            if current is None:
                raise EvidenceError(f"{file}: const without const_def")
            name = line.split()[1]
            if name in names:
                found[name] = current
            current += 1
        elif line.startswith("const_skip") and current is not None:
            args = line.split(maxsplit=1)
            current += literal(args[1]) if len(args) == 2 else 1
        elif line.startswith("const_"):
            raise EvidenceError(f"{file}: unsupported enum directive {line}")
        if len(found) == len(names):
            return found
    raise EvidenceError(f"{file}: missing constants {set(names) - found.keys()}")


def structure(repo: pathlib.Path, name: str, num_moves: int) -> tuple[dict[str, int], int]:
    """Interpret only the RAM macro grammar actually used by box/party/battle."""
    file = "macros/ram.asm" if (repo / "macros/ram.asm").exists() else "macros/wram.asm"
    match = re.search(rf"^MACRO {name}\s*\n(.*?)^ENDM\s*$", source_text(repo, file), re.M | re.S)
    if not match:
        raise EvidenceError(f"{file}: missing {name}")
    offsets: dict[str, int] = {}
    size = 0
    for line in match[1].splitlines():
        line = line.strip()
        if not line:
            continue
        if line == r"box_struct \1":
            offsets, size = structure(repo, "box_struct", num_moves)
            continue
        match = re.fullmatch(r"\\1(\w+)::\s*(?:(db|dw|ds)(?:\s+(\w+))?)?", line)
        if not match:
            raise EvidenceError(f"{file}/{name}: unsupported macro line {line!r}")
        field, directive, count = match.groups()
        offsets[field] = size
        if directive in ("db", "dw"):
            size += 1 if directive == "db" else 2
        elif directive == "ds":
            size += num_moves if count == "NUM_MOVES" else literal(count or "")
    return offsets, size


def require_source(repo: pathlib.Path, file: str, pattern: str, meaning: str) -> None:
    if not re.search(pattern, source_text(repo, file), re.M | re.S):
        raise EvidenceError(f"{repo.name}/{file}: cannot establish {meaning}")


def profile_contracts(repo: pathlib.Path, syms: dict[str, int]) -> dict[str, tuple[object, str, str]]:
    """Expected non-address profile leaves, with evidence category and source."""
    out: dict[str, tuple[object, str, str]] = {}

    def add(field, value, evidence, category="structure"):
        out[field] = (value, category, f"{repo.name}/{evidence}")

    num_moves = constant(repo, "NUM_MOVES", "constants/battle_constants.asm")
    party, party_len = structure(repo, "party_struct", num_moves)
    box, box_len = structure(repo, "box_struct", num_moves)
    battle, _ = structure(repo, "battle_struct", num_moves)
    for field, member in {
        "dv_offset_1": "DVs", "otid_offset": "OTID", "species_offset": "Species",
        "hp_offset": "HP", "maxhp_offset": "MaxHP", "level_offset": "Level",
        "stats_offset": "Attack", "status_offset": "Status", "moves_offset": "Moves",
        "pp_offset": "PP",
    }.items():
        add(field, party[member], f"RAM party_struct.{member}")
    add("dv_offset_2", party["DVs"] + 1, "RAM party_struct.DVs + 1")
    add("box_level_offset", box["BoxLevel"], "RAM box_struct.BoxLevel")
    add("enemy_status_offset", battle["Status"], "RAM battle_struct.Status")
    add("party_struct_size", party_len, "RAM party_struct size")
    add("box_struct_size", box_len, "RAM box_struct size")
    for field, key, file in (
        ("box_max_mons", "MONS_PER_BOX", "pokemon_data_constants"),
        ("bag_max_items", "BAG_ITEM_CAPACITY", "menu_constants"),
        ("stored_boxes.count", "NUM_BOXES", "pokemon_data_constants"),
    ):
        add(field, constant(repo, key, f"constants/{file}.asm"), f"constants/{file}.asm:{key}")
    total_boxes = out["stored_boxes.count"][0]
    if total_boxes % 2:
        raise EvidenceError("NUM_BOXES must divide into two equal SRAM banks")
    names = constant(repo, "NAME_LENGTH", "constants/text_constants.asm")
    size = 1 + out["box_max_mons"][0] + 1 + out["box_max_mons"][0] * (box_len + names * 2)
    if syms["wBoxDataEnd"] - syms["wBoxDataStart"] != size:
        raise EvidenceError("box macro/name/count geometry disagrees with WRAM symbols")
    for field in ("stored_boxes.stride", "sram_box_layout.box_len"):
        add(field, size, "ram/wram.asm:wBoxDataEnd - wBoxDataStart")
    for field in ("stored_boxes.per_bank", "sram_box_layout.boxes_per_bank"):
        add(field, total_boxes // 2, "ram/sram.asm:two banks of NUM_BOXES / 2")
    for index, bank in enumerate((2, 3), 1):
        require_source(repo, "layout.link", rf'SRAM \${bank}\s+"Saved Boxes {index}"', "box SRAM bank")
        add(f"stored_boxes.banks.{index}", bank * 0x2000, "layout.link:SRAM bank * $2000")
        add(f"sram_box_layout.banks.{index}", bank, "layout.link:SRAM bank")
    for i in range(1, total_boxes + 1):
        expected = 0xA000 + (i - 1) % (total_boxes // 2) * size
        if syms[f"sBox{i}"] != expected:
            raise EvidenceError(f"sBox{i} has wrong stored-box stride")
    for bank in (2, 3):
        if syms[f"sBank{bank}AllBoxesChecksum"] != 0xA000 + size * (total_boxes // 2):
            raise EvidenceError(f"bank {bank} checksum does not follow all six boxes")
        if syms[f"sBank{bank}IndividualBoxChecksums"] != syms[f"sBank{bank}AllBoxesChecksum"] + 1:
            raise EvidenceError(f"bank {bank} individual checksum geometry disagrees")
    add("sram_box_layout.checksum_offset", syms["sBank2AllBoxesChecksum"] - 0xA000,
        "ram/sram.asm:sBank2AllBoxesChecksum - SRAM start")
    require_source(repo, "layout.link", r'SRAM \$1\s+"Save Data"', "main-save SRAM bank")
    if syms["sPlayerName"] != syms["sGameData"]:
        raise EvidenceError("sGameData no longer starts with sPlayerName")
    add("sram_box_layout.main_save_start", 0x2000 + syms["sGameData"] - 0xA000,
        "ram/sram.asm:sGameData in SRAM bank 1")
    add("sram_box_layout.main_save_len", syms["sGameDataEnd"] - syms["sGameData"],
        "ram/sram.asm:sGameDataEnd - sGameData")
    add("sram_box_layout.main_checksum_offset", 0x2000 + syms["sMainDataCheckSum"] - 0xA000,
        "ram/sram.asm:sMainDataCheckSum in SRAM bank 1")
    add("sram_box_layout.saved_box_flag_offset", 0x2000 + syms["sMainData"] - 0xA000
        + syms["wCurrentBoxNum"] - syms["wMainDataStart"],
        "ram/sram.asm:sMainData + wCurrentBoxNum - wMainDataStart in SRAM bank 1")
    add("sram_box_layout.player_id_addr", syms["wPlayerID"], "ram/wram.asm:wPlayerID", "symbol")
    add("sram_box_layout.saved_player_id_offset", 0x2000 + syms["sMainData"] - 0xA000
        + syms["wPlayerID"] - syms["wMainDataStart"],
        "ram/sram.asm:sMainData + wPlayerID - wMainDataStart in SRAM bank 1")
    ranges = [(syms["wBoxDataStart"], 0x2000 + syms["sCurBoxData"] - 0xA000,
               syms["wBoxDataEnd"] - syms["wBoxDataStart"]),
              (syms["wPartyDataStart"], 0x2000 + syms["sPartyData"] - 0xA000,
               syms["wPartyDataEnd"] - syms["wPartyDataStart"]),
              (syms["wPokedexOwned"], 0x2000 + syms["sMainData"] - 0xA000,
               syms["wPokedexSeenEnd"] - syms["wPokedexOwned"])]
    require_source(repo, "engine/menus/save.asm", r"ld hl, wBoxDataStart\s+ld de, sCurBoxData\s+ld bc, wBoxDataEnd - wBoxDataStart\s+call CopyData", "current-box save copy")
    require_source(repo, "engine/menus/save.asm", r"ld hl, wPartyDataStart\s+ld de, sPartyData\s+ld bc, wPartyDataEnd - wPartyDataStart\s+call CopyData\s+ld hl, wPokedexOwned\s+ld de, sMainData\s+ld bc, wPokedexSeenEnd - wPokedexOwned\s+call CopyData", "party/dex save copy ranges")
    if repo.name == "pokeyellow":
        require_source(repo, "engine/menus/save.asm", r"ld hl, wPikachuHappiness\s+ld de, sMainData \+ \(wPikachuHappiness - wMainDataStart\)\s+ld a, \[hli\]\s+ld \[de\], a\s+inc de\s+ld a, \[hl\]\s+ld \[de\], a", "Yellow happiness/mood save copy")
        ranges.append((syms["wPikachuHappiness"], 0x2000 + syms["sMainData"] - 0xA000
                       + syms["wPikachuHappiness"] - syms["wMainDataStart"], 2))
    for index, values in enumerate(ranges, 1):
        for member, value in zip(("src", "dst", "len"), values, strict=True):
            add(f"sram_box_layout.save_party_dex_ranges.{index}.{member}", value,
                "engine/menus/save.asm:SavePartyAndDexData/SaveSAVtoSRAM2")
    if repo.name == "alchav_pokered":
        require_source(repo, "engine/menus/save.asm", r"bit\s+7,\s*\[hl\]", "AP changed-box initialized flag")
        changed_bit = 7
    else:
        changed_bit = constant(repo, "BIT_HAS_CHANGED_BOXES", "constants/ram_constants.asm")
    add("sram_box_layout.changed_boxes_bit", 1 << changed_bit, "ChangeBox initialized flag")
    # AP predates named PP masks but still applies the identical literal mask.
    if repo.name == "alchav_pokered":
        require_source(repo, "engine/battle/core.asm", r"and\s+\$3f\b", "packed PP mask")
    else:
        if (constant(repo, "PP_UP_MASK", "constants/pokemon_data_constants.asm"),
                constant(repo, "PP_MASK", "constants/pokemon_data_constants.asm")) != (0xC0, 0x3F):
            raise EvidenceError("PP packing changed")
    for field in ("pp_encoding", "enemy_battle_pp_encoding"):
        add(field, "ppup_packed", "PP upper two bits and lower-six-bit mask", "invariant")
    stages = syms["wPlayerMonEvasionMod"] - syms["wPlayerMonAttackMod"] + 1
    add("stat_stages_count", stages, "wPlayerMonAttackMod..wPlayerMonEvasionMod")
    for offset, stat in enumerate(("Attack", "Defense", "Speed", "Special", "Accuracy", "Evasion")):
        if syms[f"wPlayerMon{stat}Mod"] != syms["wPlayerMonAttackMod"] + offset:
            raise EvidenceError(f"stat stages layout changed at {stat}")
    add("stat_stages_layout", "gen1", "six contiguous Atk/Def/Spd/Spc/Acc/Eva stages", "invariant")
    balls = enum_prefix(repo, "constants/item_constants.asm", ["MASTER_BALL", "ULTRA_BALL", "GREAT_BALL", "POKE_BALL"])
    for index, (name, value) in enumerate(balls.items(), 1):
        add(f"ball_item_ids.{index}", value, f"constants/item_constants.asm:{name}")
    if repo.name == "pokeyellow":
        for field, symbol in (("PIKACHU_OVERWORLD_FLAGS_ADDR", "wPikachuOverworldStateFlags"),
                              ("PIKACHU_HAPPINESS_ADDR", "wPikachuHappiness"),
                              ("PIKACHU_MOOD_ADDR", "wPikachuMood")):
            add(field, syms[symbol], f"ram/wram.asm:{symbol}", "symbol")
        species = enum_prefix(repo, "constants/pokemon_constants.asm", ["PIKACHU"])["PIKACHU"]
        add("pikachu_starter_species", species, "constants/pokemon_constants.asm:STARTER_PIKACHU = PIKACHU")
        require_source(repo, "constants/pokemon_constants.asm", r"DEF STARTER_PIKACHU EQU PIKACHU", "starter identity species")
        add("pikachu_ot_match_length", constant(repo, "NAME_LENGTH_JP", "constants/text_constants.asm") - 1,
            "engine/pikachu/pikachu_status.asm:NAME_LENGTH_JP then predecrement loop")
        require_source(repo, "engine/pikachu/pikachu_status.asm", r"ld b, NAME_LENGTH_JP\s+\.loop\s+dec b\s+jr z, \.isPlayerPikachu", "five-byte OT identity loop")
        text = source_text(repo, "engine/events/pikachu_happiness.asm")
        change_table = text.split("HappinessChangeTable:", 1)[1].split("PikachuMoods:", 1)[0]
        changes = [[int(n.strip()) for n in line.split(",")]
                   for line in re.findall(r"^\s*db\s+([^\n]+)", change_table, re.M)]
        event = enum_prefix(repo, "constants/pikachu_emotion_constants.asm", ["PIKAHAPPY_DEPOSITED"])["PIKAHAPPY_DEPOSITED"]
        for index, delta in enumerate(changes[event - 1], 1):
            add(f"pikachu_deposit_happiness.{index}", delta, "engine/events/pikachu_happiness.asm:HappinessChangeTable[PIKAHAPPY_DEPOSITED]")
        moods = [literal(n) for n in re.findall(r"^\s*db\s+([^\n]+)", text.split("PikachuMoods:", 1)[1], re.M)]
        add("pikachu_deposit_mood", moods[event - 1], "engine/events/pikachu_happiness.asm:PikachuMoods[PIKAHAPPY_DEPOSITED]")
    return out


def validate_repo(repo: pathlib.Path, syms: dict[str, int]) -> list[dict]:
    """Canonical limits plus complete macro-to-symbol, name, save and codec checks."""
    rows = []

    def check(name, fn, expected):
        try:
            actual = fn()
            ok = actual == expected
            detail = f"observed={actual!r}; expected={expected!r}"
        except (OSError, KeyError, ValueError) as exc:
            ok, detail = False, str(exc)
        rows.append({"repo": repo.name, "check": name, "severity": "OK" if ok else "FAIL", "note": detail})

    for name, expected, file in (
        ("PARTY_LENGTH", 6, "pokemon_data_constants"),
        ("MONS_PER_BOX", 20, "pokemon_data_constants"),
        ("NUM_BOXES", 12, "pokemon_data_constants"),
        ("NAME_LENGTH", 11, "text_constants"),
        ("NUM_MOVES", 4, "battle_constants"),
        ("MAX_LEVEL", 100, "battle_constants"),
        ("MAX_STAT_VALUE", 999, "battle_constants"),
        ("BAG_ITEM_CAPACITY", 128 if repo.name == "alchav_pokered" else 20, "menu_constants"),
    ):
        check(f"constants/{file}.asm:{name}", lambda n=name, f=file: constant(repo, n, f"constants/{f}.asm"), expected)
    for macro, prefix, length in (("box_struct", "wBoxMon1", 33), ("party_struct", "wPartyMon1", 44), ("battle_struct", "wEnemyMon", 29)):
        def check_struct(m=macro, p=prefix):
            fields, size = structure(repo, m, constant(repo, "NUM_MOVES", "constants/battle_constants.asm"))
            for field, offset in fields.items():
                if syms[p + field] != syms[p] + offset:
                    raise EvidenceError(f"{p}{field}: symbol disagrees with macro offset {offset}")
            return size
        check(f"{macro}: every member matches symbols", check_struct, length)
    check("transfer blob: party + OT + nickname", lambda: structure(repo, "party_struct", 4)[1] + 2 * constant(repo, "NAME_LENGTH", "constants/text_constants.asm"), 66)
    check("experience follows 2-byte OTID", lambda: syms["wBoxMon1Exp"] - syms["wBoxMon1OTID"], 2)
    check("base-stat growth byte offset", lambda: syms["wMonHGrowthRate"] - syms["wMonHeader"], 19)
    check("base-stat record size", lambda: syms["wMonHeaderEnd"] - syms["wMonHeader"], 28)
    def growth_rates():
        from lupa import LuaRuntime
        game = LuaRuntime().execute((ROOT / "lua/games/gen1_rby.lua").read_text(encoding="utf-8"))
        actual = [[game.GROWTH_RATES[i][j] for j in range(1, 6)] for i in range(1, 7)]
        rows = re.findall(r"^\s*growth_rate\s+(-?\d+),\s*(-?\d+),\s*(-?\d+),\s*(-?\d+),\s*(-?\d+)\s*$", source_text(repo, "data/growth_rates.asm"), re.M)
        expected = [[int(value) for value in row] for row in rows]
        if len(expected) != 6 or actual != expected:
            raise EvidenceError("Lua growth coefficients disagree with source GrowthRateTable")
        return True
    check("six experience curves match source coefficients", growth_rates, True)
    for prefix in ("wPartyMon", "wBoxMon"):
        for suffix in ("OT", "Nick"):
            check(f"{prefix}{suffix}: name stride", lambda p=prefix, s=suffix: syms[p + "2" + s] - syms[p + "1" + s], 11)
    check("profile structures, SRAM banks, checksums, PP and stages", lambda: bool(profile_contracts(repo, syms)), True)
    check("name terminator $50", lambda: bool(re.search(r'charmap\s+"@",\s*\$50\b', source_text(repo, "charmap.asm" if (repo / "charmap.asm").exists() else "constants/charmap.asm"))), True)
    check("status bit encoding", lambda: enum_prefix(repo, "constants/battle_constants.asm", ["PSN", "BRN", "FRZ", "PAR"]), {"PSN": 3, "BRN": 4, "FRZ": 5, "PAR": 6})
    check("sleep uses low three status bits", lambda: constant(repo, "SLP_MASK", "constants/battle_constants.asm"), 7)
    check("species list terminator $FF", lambda: require_source(repo, "engine/pokemon/remove_mon.asm", r"ld\s+\[hl\],\s*\$ff\b", "species-list terminator"), None)
    check("computed stats stored high byte first", lambda: require_source(repo, "home/move_mon.asm", r"ldh\s+a,\s*\[hMultiplicand\+1\]\s+ld\s+\[de\],\s*a\s+inc\s+de\s+ldh\s+a,\s*\[hMultiplicand\+2\]\s+ld\s+\[de\],\s*a", "big-endian computed stats"), None)
    check("save checksum is complemented byte sum", lambda: require_source(repo, "engine/menus/save.asm", r"ld\s+d,\s*0\s+\.loop\s+ld\s+a,\s*\[hli\]\s+add\s+d\s+ld\s+d,\s*a\s+dec\s+bc\s+ld\s+a,\s*b\s+or\s+c\s+jr\s+nz,\s*\.loop\s+ld\s+a,\s*d\s+cpl\s+ret", "complemented checksum algorithm"), None)
    check("main checksum covers sGameData through sGameDataEnd", lambda: require_source(repo, "engine/menus/save.asm", r"ld\s+hl,\s*sGameData\s+ld\s+bc,\s*sGameDataEnd\s*-\s*sGameData\s+call\s+(?:CalcCheckSum|SAVCheckSum)\s+ld\s+\[sMainDataCheckSum\],\s*a", "main-save checksum span"), None)
    check("checksum immediately follows covered data", lambda: syms["sMainDataCheckSum"] - syms["sGameDataEnd"], 0)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        symbols = json.loads((ROOT / "data/pret_syms.json").read_text(encoding="utf-8"))
        rows = [row for repo in dict.fromkeys(GEN1_REPOS.values())
                for row in validate_repo(SOURCE_ROOT / repo, symbols[repo])]
    except (OSError, KeyError, ValueError) as exc:
        rows = [{"repo": "all", "check": "dependencies", "severity": "FAIL", "note": str(exc)}]
    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        for row in rows:
            if row["severity"] != "OK":
                print(f"[FAIL] {row['repo']} {row['check']}: {row['note']}")
        print(f"Constants: {sum(r['severity'] == 'OK' for r in rows)} OK / {sum(r['severity'] != 'OK' for r in rows)} FAIL")
    return int(any(row["severity"] != "OK" for row in rows))


if __name__ == "__main__":
    raise SystemExit(main())
