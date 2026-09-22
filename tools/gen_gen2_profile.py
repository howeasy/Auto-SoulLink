"""Generate selected-title Gen 2 profiles from verified SYM, ROM and pinned ASM.

Profiles contain source facts and bank metadata, not runtime write permissions.
Run with --title crystal|gold|silver (default: all three), and --check to compare
without publishing. --root selects an already verified P1 workspace.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import operator
import re
import sys
from pathlib import Path

if __package__:
    from .gen2_source_data import ARTIFACTS, ROOT, load_context, rom_offset
else:
    from gen2_source_data import ARTIFACTS, ROOT, load_context, rom_offset

ROM_SYMBOLS = (
    "BaseData", "PokemonNames", "EvosAttacksPointers", "Moves", "MoveNames", "ItemNames",
    "JohtoGrassWildMons", "JohtoWaterWildMons", "KantoGrassWildMons", "KantoWaterWildMons",
    "SwarmGrassWildMons", "SwarmWaterWildMons", "GrassMonProbTable", "WaterMonProbTable",
    "TreeMonMaps", "RockMonMaps", "TreeMons", "FishGroups", "TimeFishGroups", "RoamMaps",
    "InitRoamMons", "CheckEncounterRoamMon",
)
RAM_SYMBOLS = (
    "wPlayerID", "wPlayerName", "wRivalName", "wMoney", "wCoins", "wJohtoBadges", "wKantoBadges",
    "wMapGroup", "wMapNumber", "wXCoord", "wYCoord", "wBattleMode", "wBattleType", "wBattleResult",
    "wCurPartyMon", "wMonType", "wCurBox", "wPokemonData", "wPokemonDataEnd", "wPlayerData",
    "wPlayerDataEnd", "wCurMapData", "wCurMapDataEnd", "wNumItems", "wItems", "wNumKeyItems",
    "wKeyItems", "wNumBalls", "wBalls", "wTMsHMs", "wOptions", "wOptionsEnd", "wPokedexCaught",
    "wPokedexSeen", "wLinkMode", "wMenuFlags", "wScriptMode", "wScriptRunning", "wPlayerState",
    "wPartyCount", "wPartySpecies", "wPartyMons", "wPartyMonOTs", "wPartyMonNicknames",
    "wPartyMonNicknamesEnd", "sBox", "sBoxCount", "sBoxSpecies", "sBoxMons", "sBoxMonOTs",
    "sBoxMonNicknames", "sBoxMonNicknamesEnd", "sBoxEnd", "sGameData", "sGameDataEnd",
    "sPlayerData", "sCurMapData", "sPokemonData", "sChecksum", "sCheckValue1", "sCheckValue2",
    "sBackupChecksum", "sBackupCheckValue1", "sBackupCheckValue2", "sOptions", "hROMBank",
    "wSavedAtLeastOnce", "wSaveFileExists",
    "wCurBattleMon", "wOtherTrainerClass", "wOtherTrainerID",
    "hJoyDown", "hJoyPressed", "hJoyReleased",
)
STAT_STAGE_FIELDS = (
    ("ATTACK", "Atk"), ("DEFENSE", "Def"), ("SPEED", "Spd"),
    ("SP_ATTACK", "SAtk"), ("SP_DEFENSE", "SDef"), ("ACCURACY", "Acc"), ("EVASION", "Eva"),
)


def _expression(text: str, values: dict[str, int]) -> int:
    """Evaluate only the integer arithmetic used by the selected pinned definitions."""
    text = re.sub(r"\$([0-9a-fA-F]+)", r"0x\1", text)
    text = re.sub(r"%([01]+)", r"0b\1", text)
    tree = ast.parse(text.strip(), mode="eval")
    operations = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
                  ast.Div: operator.floordiv, ast.FloorDiv: operator.floordiv,
                  ast.LShift: operator.lshift, ast.RShift: operator.rshift,
                  ast.BitOr: operator.or_, ast.BitAnd: operator.and_}

    def evaluate(node):
        if isinstance(node, ast.Constant) and type(node.value) is int:
            return node.value
        if isinstance(node, ast.Name) and node.id in values:
            return values[node.id]
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            return evaluate(node.operand) * (-1 if isinstance(node.op, ast.USub) else 1)
        if isinstance(node, ast.BinOp) and type(node.op) in operations:
            return operations[type(node.op)](evaluate(node.left), evaluate(node.right))
        raise ValueError(f"unsupported or unresolved source expression: {text!r}")

    return evaluate(tree.body)


def _definitions(text: str, values: dict[str, int]) -> dict[str, int]:
    """Interpret bounded const/rs blocks, refusing every unrecognized instruction."""
    values = dict(values)
    step = 1
    for raw in text.splitlines():
        line = raw.split(";", 1)[0].strip()
        if not line:
            continue
        if line == "rsreset":
            values["_RS"] = 0
            continue
        if line.startswith("rsset "):
            values["_RS"] = _expression(line[6:], values)
            continue
        if line == "const_def" or line.startswith("const_def "):
            parts = line[9:].strip().split(",")
            values["const_value"] = _expression(parts[0], values) if parts[0] else 0
            step = _expression(parts[1], values) if len(parts) == 2 else 1
            continue
        match = re.fullmatch(r"const ([A-Z0-9_]+)", line)
        if match:
            values[match[1]] = values["const_value"]
            values["const_value"] += step
            continue
        if line == "const_skip" or line.startswith("const_skip "):
            values["const_value"] += step * (_expression(line[10:], values) if line[10:].strip() else 1)
            continue
        match = re.fullmatch(r"(?:DEF\s+([A-Z0-9_]+)\s+)?(rb|rw|rb_skip)(?:\s+(.+))?", line)
        if match:
            name, unit, count = match.groups()
            if name:
                values[name] = values["_RS"]
            values["_RS"] += (2 if unit == "rw" else 1) * (_expression(count, values) if count else 1)
            continue
        match = re.fullmatch(r"DEF\s+([A-Z0-9_]+)\s+(?:EQU|=)\s+(.+)", line)
        if match:
            values[match[1]] = _expression(match[2], values)
            continue
        raise ValueError(f"unsupported statement in selected constant block: {raw!r}")
    return values


def _block(text: str, first: str, last: str, *, prefix: str | None = None) -> str:
    start = re.search(rf"(?m)^\s*{first}[^\n]*", text)
    if start is None:
        raise ValueError(f"source definition missing: {first}")
    end = re.search(rf"(?m)^\s*{last}[^\n]*", text[start.start():])
    if end is None:
        raise ValueError(f"source definition missing after {first}: {last}")
    begin = start.start()
    if prefix:
        candidates = list(re.finditer(rf"(?m)^\s*{prefix}[^\n]*", text[:start.start()]))
        if not candidates:
            raise ValueError(f"source prefix {prefix} missing before {first}")
        begin = candidates[-1].start()
    return text[begin:start.start() + end.end()]


def _literal(text: str, name: str) -> int:
    matches = re.findall(rf"(?m)^DEF {name}\s+EQU\s+([^;\r\n]+)", text)
    if len(matches) != 1:
        raise ValueError(f"expected one source definition for {name}")
    return _expression(matches[0], {})


def treemon_enabled_limit(text: str, values: dict[str, int]) -> int:
    """GetTreeMons' own `cp` bound: tree sets 1..limit-1 can yield an encounter.

    pokecrystal engine/events/treemons.asm:96-105 uses `cp NUM_TREEMON_SETS`;
    pokegold :94-106 uses `cp NUM_TREEMON_SETS - 2` and asserts that UNUSED/CITY are
    the two refused tail sets. Both refuse TREEMON_SET_NONE via `and a / jr z`. The
    source asserts must name exactly the refused tail, so a bound that disagrees with
    them (or an unasserted tail) refuses generation instead of guessing a rule.
    """
    lines = [raw.split(";", 1)[0].strip() for raw in _block(text, "GetTreeMons:", "ld hl, TreeMons").splitlines()]
    lines = [line for line in lines if line and line != "GetTreeMons:"]
    asserted = {}
    for line in lines:
        if line.startswith("assert"):
            match = re.fullmatch(r"assert\s+(TREEMON_SET_[A-Z0-9_]+)\s*==\s*(.+)", line)
            if not match or match[1] not in values or values[match[1]] != _expression(match[2], values):
                raise ValueError(f"GetTreeMons assert fails or is unsupported: {line}")
            asserted[match[1]] = values[match[1]]
    code = [line for line in lines if not line.startswith("assert")]
    if (len(code) != 7 or not code[0].startswith("cp ")
            or code[1:] != ["jr nc, .quit", "and a", "jr z, .quit", "ld e, a", "ld d, 0", "ld hl, TreeMons"]
            or asserted.get("TREEMON_SET_NONE") != 0):
        raise ValueError("unsupported GetTreeMons set gate")
    limit, count = _expression(code[0][3:], values), values["NUM_TREEMON_SETS"]
    tail = {value for name, value in asserted.items() if name != "TREEMON_SET_NONE"}
    if not 1 < limit <= count or tail != set(range(limit, count)):
        raise ValueError(f"GetTreeMons bound {limit} disagrees with its asserted refused sets {sorted(tail)}")
    return limit


def _constants(ctx) -> tuple[dict, dict, dict]:
    paths = (
        "constants/battle_constants.asm", "constants/pokemon_constants.asm",
        "constants/pokemon_data_constants.asm", "constants/text_constants.asm",
        "constants/item_constants.asm", "constants/item_data_constants.asm",
        "constants/map_data_constants.asm", "data/wild/fish.asm", "engine/overworld/wildmons.asm",
        "ram/wram.asm", "ram/sram.asm", "macros/ram.asm", "data/pokemon/base_stats.asm",
        "constants/misc_constants.asm", "engine/menus/save.asm",
        "constants/ram_constants.asm", "engine/battle/effect_commands.asm",
        "engine/events/treemons.asm",
    )
    source = {path: ctx.read_source(path) for path in paths}
    battle, pokemon, data = [source[f"constants/{name}_constants.asm"]
                             for name in ("battle", "pokemon", "pokemon_data")]
    stats = _definitions(_block(battle, "const STAT_HP", "DEF NUM_BATTLE_STATS", prefix="const_def"), {})
    species = _definitions(_block(pokemon, "const BULBASAUR", "const EGG", prefix="const_def"), {})
    values = {key: stats[key] for key in ("NUM_STATS", "NUM_EXP_STATS", "NUM_BATTLE_STATS")}
    values.update({key: species[key] for key in ("NUM_POKEMON", "EGG")})
    values["NUM_MOVES"] = _literal(battle, "NUM_MOVES")
    for key in ("BASE_STAT_LEVEL", "MAX_STAT_LEVEL"):
        values[key] = _literal(battle, key)
    stages = _definitions(_block(battle, "const ATTACK", "DEF NUM_LEVEL_STATS", prefix="const_def"), {})
    for key in (*[name for name, _suffix in STAT_STAGE_FIELDS], "ABILITY", "NUM_LEVEL_STATS"):
        values[key] = stages[key]
    battle_classes = _definitions(_block(battle, "const WILD_BATTLE", "const TRAINER_BATTLE",
                                         prefix="const_def"), {})
    for key in ("WILD_BATTLE", "TRAINER_BATTLE"):
        values[key] = battle_classes[key]
    result_flags = _definitions(_block(battle, "const WIN", "DEF BATTLERESULT_BITMASK",
                                       prefix="const_def"), {})
    values["BATTLERESULT_BITMASK"] = result_flags["BATTLERESULT_BITMASK"]
    badges = _definitions(_block(source["constants/ram_constants.asm"], "const ZEPHYRBADGE",
                                 "DEF NUM_BADGES", prefix="const_def"), {})
    for key in ("NUM_JOHTO_BADGES", "NUM_KANTO_BADGES", "NUM_BADGES"):
        values[key] = badges[key]
    for key in ("NAME_LENGTH", "MON_NAME_LENGTH", "PLAYER_NAME_LENGTH", "BOX_NAME_LENGTH"):
        values[key] = _literal(source["constants/text_constants.asm"], key)
    items = source["constants/item_constants.asm"]
    tm_counts = {kind: len(re.findall(rf"(?m)^\s*add_{kind} [A-Z0-9_]+\s*(?:;[^\n]*)?$", items))
                 for kind in ("tm", "hm", "mt")}
    if not tm_counts["tm"] or not tm_counts["hm"]:
        raise ValueError("source TM/HM declarations missing")
    values["NUM_TM_HM"] = tm_counts["tm"] + tm_counts["hm"]
    values["NUM_TM_HM_TUTOR"] = values["NUM_TM_HM"] + tm_counts["mt"]
    values = _definitions(_block(data, "DEF BASE_DEX_NO", "DEF BASE_DATA_SIZE", prefix="rsreset"), values)
    values = _definitions(_block(data, "DEF MON_SPECIES", "DEF NUM_BOXES", prefix="rsreset"), values)
    values = _definitions(_block(data, "DEF NUM_GRASSMON", "DEF NUM_TREEMON_SETS"), values)
    values = _definitions(_block(source["constants/map_data_constants.asm"], "const FISHGROUP_NONE",
                                "DEF NUM_FISHGROUPS", prefix="const_def"), values)
    for key in ("MAX_ITEMS", "MAX_BALLS", "MAX_KEY_ITEMS", "MAX_ITEM_STACK"):
        values[key] = _literal(source["constants/item_data_constants.asm"], key)
    for key in ("SAVE_CHECK_VALUE_1", "SAVE_CHECK_VALUE_2"):
        values[key] = _literal(source["constants/misc_constants.asm"], key)
        if not 0 <= values[key] <= 255:
            raise ValueError(f"source {key} must fit a byte")
    # TimeFishGroups has no upstream named count; derive its complete final table.
    fish = source["data/wild/fish.asm"].split("\nTimeFishGroups:\n")
    if len(fish) != 2:
        raise ValueError("ambiguous TimeFishGroups source table")
    fish_rows = [line.split(";", 1)[0].strip() for line in fish[1].splitlines()]
    fish_rows = [line for line in fish_rows if line]
    if not fish_rows or any(not re.fullmatch(r"db\s+[A-Z0-9_]+,\s*\d+,\s*[A-Z0-9_]+,\s*\d+", line)
                            for line in fish_rows):
        raise ValueError("unsupported TimeFishGroups source row")
    values["NUM_TIME_FISHGROUPS"] = len(fish_rows)
    roamer_body = _block(source["engine/overworld/wildmons.asm"], "InitRoamMons:", "CheckEncounterRoamMon:")
    roamers = sorted({int(slot) for slot in re.findall(r"ld \[wRoamMon(\d+)Species\], a", roamer_body)})
    if roamers != list(range(1, len(roamers) + 1)) or not roamers:
        raise ValueError("non-contiguous or empty initialized roamer slots")
    values["ROAMER_COUNT"] = len(roamers)
    values["TREEMON_ENABLED_LIMIT"] = treemon_enabled_limit(source["engine/events/treemons.asm"], values)
    # Internal assembler counters are not exported as profile constants.
    values = {key: value for key, value in values.items() if key not in ("_RS", "const_value")}
    receipts = {path: {"sha256": hashlib.sha256(text.encode()).hexdigest(),
                       "encoding": "utf-8-normalized-newlines"} for path, text in source.items()}
    return values, receipts, source


def _check_save_spans(ctx, title: str, source: dict) -> None:
    """Bind the exported save symbols to native declarations and checksum callers.

    This checks source geometry only. Sentinel validity, checksum selection and
    runtime/host durability policies remain with their consumers.
    """
    pairs = (("PlayerData", "wPlayerData", "wPlayerDataEnd"),) if title == "crystal" else tuple(
        (f"PlayerData{i}", f"wPlayerData{i}", f"wPlayerData{i}End") for i in range(1, 4))
    pairs += (("CurMapData", "wCurMapData", "wCurMapDataEnd"),
              ("PokemonData", "wPokemonData", "wPokemonDataEnd"))
    sram = source["ram/sram.asm"]
    addresses = {name: symbol.address for name, symbol in ctx.symbols.items()}
    regions = {"s": [], "sBackup": []}
    for stem, first, last in pairs:
        start, end = ctx.symbol(first), ctx.symbol(last)
        size = end.address - start.address
        if start.bank != end.bank or not 0 < size <= 0x2000:
            raise ValueError(f"incompatible save span: {first}/{last}")
        for prefix in regions:
            name = prefix + stem
            symbol = ctx.symbol(name)
            declarations = re.findall(rf"(?m)^{name}::\s+ds\s+([^;\r\n]+)", sram)
            if (len(declarations) != 1 or _expression(declarations[0], addresses) != size
                    or not 0 <= symbol.bank < 4 or not symbol.address >= 0xA000
                    or symbol.address + size > 0xC000):
                raise ValueError(f"source save span disagrees with symbols: {name}")
            regions[prefix].append((symbol.bank, symbol.address, size))
    for prefix in ("s", "sBackup") if title == "crystal" else ("s",):
        start, end = ctx.symbol(prefix + "GameData"), ctx.symbol(prefix + "GameDataEnd")
        cursor = start.address
        for bank, address, size in regions[prefix]:
            if bank != start.bank or address != cursor:
                raise ValueError(f"source save span is not contiguous: {prefix}")
            cursor += size
        if end.bank != start.bank or cursor != end.address:
            raise ValueError(f"source save span end disagrees: {prefix}")
    for prefix in regions:
        checksum = ctx.symbol(prefix + "Checksum")
        if (not re.search(rf"(?m)^{prefix}Checksum::\s+dw\s*$", sram)
                or not 0 <= checksum.bank < 4 or not 0xA000 <= checksum.address <= 0xBFFE):
            raise ValueError(f"invalid native save checksum storage: {prefix}")
        for number in (1, 2):
            name = prefix + f"CheckValue{number}"
            marker = ctx.symbol(name)
            if (marker.bank != checksum.bank or not 0xA000 <= marker.address < 0xC000
                    or not re.search(rf"(?m)^{name}::\s+db\b", sram)):
                raise ValueError(f"invalid native save sentinel: {name}")
    for name in ("wSavedAtLeastOnce", "wSaveFileExists"):
        if not re.search(rf"(?m)^{name}::\s+db\b", source["ram/wram.asm"]):
            raise ValueError(f"save flag declaration missing: {name}")
    engine = "\n".join(line.split(";", 1)[0].strip() for line in source["engine/menus/save.asm"].splitlines())
    for prefix, routine in (("s", "ValidateSave"), ("sBackup", "ValidateBackupSave")):
        block = re.search(rf"(?m)^{routine}:\n([\s\S]*?)(?=^\w+:|\Z)", engine)
        if block is None or any(f"ld a, SAVE_CHECK_VALUE_{n}\nld [{prefix}CheckValue{n}], a" not in block[1] for n in (1, 2)):
            raise ValueError(f"save sentinel source contract changed: {routine}")
    if "ld hl, sGameData\nld bc, sGameDataEnd - sGameData" not in engine:
        raise ValueError("primary checksum source span missing")
    expected = (("sBackupGameData", "sBackupGameDataEnd - sBackupGameData"),) if title == "crystal" else tuple(
        ("sBackup" + stem, f"{last} - {first}") for stem, first, last in pairs)
    for name, expression in expected:
        if f"ld hl, {name}\nld bc, {expression}" not in engine:
            raise ValueError(f"backup checksum source span missing: {name}")


def _stat_stage_minimum(ctx, constants: dict, source: dict) -> int:
    """Verify native stage storage and derive the engine's lower bound.

    C/G battle_constants.asm:35-46 names seven stages plus ABILITY. C wram.asm:
    454-472 / G:942-960 declare seven named bytes followed by one unnamed byte.
    The lower bound has no upstream constant: StatDown's decrement refuses zero,
    and its sharp-lowering path increments zero back to one (C effect_commands:
    4339-4349; G:4306-4316). LowerStat, Curse's Speed drop, repeats the same
    refusal/clamp (C effect_commands:4674-4683; G:4637-4646). Other writers reset
    to BASE_STAT_LEVEL or copy a whole array. This is a derived source fact, not a
    live-state grant.
    """
    if ([constants[name] for name, _suffix in STAT_STAGE_FIELDS] != list(range(7))
            or constants["ABILITY"] != 7 or constants["NUM_LEVEL_STATS"] != 8
            or not 1 <= constants["BASE_STAT_LEVEL"] <= constants["MAX_STAT_LEVEL"] <= 255):
        raise ValueError("unsupported stat-stage index or range contract")

    def instructions(text):
        return [re.sub(r"\s+", " ", line.split(";", 1)[0].strip())
                for line in text.splitlines() if line.split(";", 1)[0].strip()]

    wram = source["ram/wram.asm"]
    for side, following in (("Player", "wEnemyStatLevels"), ("Enemy", "wEnemyTurnsTaken")):
        name = f"w{side}StatLevels"
        base, end = ctx.symbol(name), ctx.symbol(following)
        if base.bank != end.bank or end.address - base.address != constants["NUM_LEVEL_STATS"]:
            raise ValueError(f"stat-stage array geometry disagrees: {name}")
        block = _block(wram, name + "::", following + "::")
        expected = [name + "::"]
        for index, suffix in STAT_STAGE_FIELDS:
            field = f"w{side}{suffix}Level"
            symbol = ctx.symbol(field)
            if symbol.bank != base.bank or symbol.address - base.address != constants[index]:
                raise ValueError(f"stat-stage symbol/index mismatch: {field}")
            expected.append(field + ":: db")
        if instructions(block)[:-1] != [*expected, "ds 1"]:
            raise ValueError(f"stat-stage seven-byte plus unnamed-byte declaration differs: {name}")
    declarations = "\n".join(instructions(wram))
    for name in ("wCurBattleMon", "wOtherTrainerClass", "wOtherTrainerID"):
        if not re.search(rf"(?m)^{name}::\s*db\s*$", declarations):
            raise ValueError(f"ancillary byte declaration missing: {name}")
    effects = source["engine/battle/effect_commands.asm"]
    lower = "\n".join(instructions(_block(effects, "BattleCommand_StatDown:", r"\.ComputerMiss:")))
    if ("ld b, [hl]\ndec b\njp z, .CantLower" not in lower
            or "ld a, [wLoweredStat]\nand $f0\njr z, .ComputerMiss\ndec b\njr nz, .ComputerMiss\ninc b" not in lower):
        raise ValueError("stat-stage minimum lacks the native decrement/refusal/sharp-clamp proof")
    lowered = "\n".join(instructions(_block(effects, "LowerStat:", r"\.got_num_stages")))
    if ("ld b, [hl]\ndec b\njr z, .cant_lower_anymore" not in lowered
            or "ld a, [wLoweredStat]\nand $f0\njr z, .got_num_stages\ndec b\njr nz, .got_num_stages\ninc b"
            not in lowered):
        raise ValueError("stat-stage minimum lacks the LowerStat decrement/refusal/sharp-clamp proof")
    upper = "\n".join(instructions(_block(effects, "RaiseStat:", r"\.got_num_stages")))
    if "ld b, [hl]\ninc b\nld a, MAX_STAT_LEVEL\ncp b\njp c, .cant_raise_stat" not in upper:
        raise ValueError("stat-stage maximum lacks its native bound check")
    return 1


def build(title: str, root: Path = ROOT) -> dict:
    ctx = load_context(title, root=root)
    constants, source_files, source = _constants(ctx)
    _check_save_spans(ctx, title, source)
    stat_stage_min = _stat_stage_minimum(ctx, constants, source)
    names = set(RAM_SYMBOLS)
    for side in ("Player", "Enemy"):
        names.add(f"w{side}StatLevels")
        names.update(f"w{side}{suffix}Level" for _index, suffix in STAT_STAGE_FIELDS)
    # Crystal's contiguous backup differs from Gold/Silver's split save regions.
    names.update(("sBackupGameData", "sBackupGameDataEnd", "sBackupPlayerData",
                  "sBackupCurMapData", "sBackupPokemonData") if title == "crystal" else
                 ("sBackupPlayerData1", "sBackupPlayerData2", "sBackupPlayerData3",
                  "sBackupPokemonData", "sBackupCurMapData", "sPlayerData1", "sPlayerData2", "sPlayerData3",
                  "wPlayerData1", "wPlayerData1End", "wPlayerData2", "wPlayerData2End",
                  "wPlayerData3", "wPlayerData3End"))
    names.update(f"sBox{number}" for number in range(1, constants["NUM_BOXES"] + 1))
    patterns = (r"wPartyMon[1-6](?:[A-Za-z0-9_]+)?", r"sBoxMon[12](?:[A-Za-z0-9_]+)?",
                r"wBattleMon(?:[A-Za-z0-9_]+)?", r"wEnemyMon(?:[A-Za-z0-9_]+)?",
                r"wRoamMon[1-3](?:[A-Za-z0-9_]+)?", r"h[A-Za-z0-9_]+")
    names.update(name for name in ctx.symbols if any(re.fullmatch(pattern, name) for pattern in patterns))
    ram, banks, sram_banks, hram = {}, {}, {}, {}
    for name in sorted(names):
        bank, address = ctx.symbol(name)
        if (name.startswith("w") and 0xC000 <= address <= 0xE000
                or name.startswith("s") and 0xA000 <= address <= 0xC000
                or name.startswith("h") and 0xFF80 <= address <= 0xFFFF):
            ram[name], banks[name] = address, bank
        else:
            raise ValueError(f"{title}: memory symbol {name} outside its expected region")
        if name.startswith("s"):
            sram_banks[name] = bank
        if name.startswith("h"):
            hram[name] = address
    rom = {}
    for name in ROM_SYMBOLS:
        bank, address = ctx.symbol(name)
        flat = rom_offset(bank, address)
        if flat >= len(ctx.rom):
            raise ValueError(f"{title}: ROM symbol {name} outside artifact")
        rom[name] = {"bank": bank, "addr": address, "flat": flat}

    def difference(end, start):
        a, b = ctx.symbol(end), ctx.symbol(start)
        if a.bank != b.bank or a.address <= b.address:
            raise ValueError(f"incompatible profile geometry: {end} - {start}")
        return a.address - b.address

    party_size = difference("wPartyMon2", "wPartyMon1")
    box_size = difference("sBoxMon2", "sBoxMon1")
    stride = difference("sBox2", "sBox1")
    checks = {"PARTYMON_STRUCT_LENGTH": party_size, "BOXMON_STRUCT_LENGTH": box_size,
              "BOX_LENGTH": stride,
              "PARTY_LENGTH": difference("wPartyMonOTs", "wPartyMons") // party_size,
              "MONS_PER_BOX": difference("sBoxMonOTs", "sBoxMons") // box_size,
              "NAME_LENGTH": difference("wPartyMon2OT", "wPartyMon1OT"),
              "MON_NAME_LENGTH": difference("wPartyMon2Nickname", "wPartyMon1Nickname")}
    for key, measured in checks.items():
        if constants[key] != measured:
            raise ValueError(f"{title}: source {key}={constants[key]} != symbol geometry {measured}")
    if difference("wPartyMonOTs", "wPartyMons") % party_size or difference("sBoxMonOTs", "sBoxMons") % box_size:
        raise ValueError("non-integral native party/box capacity")
    boxes = [{"number": number, "bank": ctx.symbol(f"sBox{number}").bank,
              "addr": ctx.symbol(f"sBox{number}").address, "length": stride}
             for number in range(1, constants["NUM_BOXES"] + 1)]

    def storage_flat(bank, address, length, label):
        # Native save/storage SRAM occupies banks 0..3. These are source address
        # facts only; an emulator's linear CartRAM binding is qualified elsewhere.
        if (type(bank) is not int or not 0 <= bank < 4
                or type(address) is not int or not 0xA000 <= address < 0xC000
                or type(length) is not int or not 0 < length <= 0x2000
                or address + length > 0xC000):
            raise ValueError(f"native storage span exceeds SRAM bank: {label}")
        return bank * 0x2000 + address - 0xA000

    for box in boxes:
        box["flat"] = storage_flat(box["bank"], box["addr"], stride, f"sBox{box['number']}")
    active_copy_length = difference("sBoxEnd", "sBox")
    if active_copy_length != constants["BOX_LENGTH"] - 2:
        raise ValueError("active box source copy span disagrees with native unpadded payload")
    active = ctx.symbol("sBox")
    active_flat = storage_flat(active.bank, active.address, active_copy_length, "sBox")
    derived = {
        "party_struct_size": party_size, "box_struct_size": box_size,
        "party_capacity": constants["PARTY_LENGTH"], "box_capacity": constants["MONS_PER_BOX"],
        "name_length": constants["NAME_LENGTH"], "mon_name_length": constants["MON_NAME_LENGTH"],
        "num_boxes": constants["NUM_BOXES"], "sram_box_stride": stride,
        "sram_box_banks": sorted({box["bank"] for box in boxes}),
        "active_box_flat": active_flat, "active_box_copy_length": active_copy_length,
        "stat_stage_min": stat_stage_min,
        "species_count": constants["NUM_POKEMON"], "egg_species": constants["EGG"],
        "base_stats_stride": constants["BASE_DATA_SIZE"], "base_tmhm_offset": constants["BASE_TMHM"],
        "num_grassmon": constants["NUM_GRASSMON"], "num_watermon": constants["NUM_WATERMON"],
        "num_fishgroups": constants["NUM_FISHGROUPS"], "num_time_fishgroups": constants["NUM_TIME_FISHGROUPS"],
        "num_treemon_sets": constants["NUM_TREEMON_SETS"], "treemon_set_rock": constants["TREEMON_SET_ROCK"],
        "treemon_enabled_limit": constants["TREEMON_ENABLED_LIMIT"],
        "num_roammon_maps": constants["NUM_ROAMMON_MAPS"], "roamer_count": constants["ROAMER_COUNT"],
        "rom_size": len(ctx.rom), "bag_capacity": constants["MAX_ITEMS"],
        "ball_capacity": constants["MAX_BALLS"], "key_item_capacity": constants["MAX_KEY_ITEMS"],
    }
    gate = rom_offset(*ctx.symbol("GetTreeMons"))
    if ctx.rom[gate:gate + 3] != bytes([0xFE, constants["TREEMON_ENABLED_LIMIT"], 0x30]):
        raise ValueError(f"{title}: GetTreeMons ROM gate disagrees with source bound")
    # Validate table numbering directly in the ROM; source and symbol arithmetic
    # must describe all 251 records rather than merely a plausible first row.
    base = rom["BaseData"]["flat"]
    for species in range(1, constants["NUM_POKEMON"] + 1):
        offset = base + (species - 1) * constants["BASE_DATA_SIZE"]
        if offset + constants["BASE_DATA_SIZE"] > len(ctx.rom) or ctx.rom[offset] != species:
            raise ValueError(f"{title}: BaseData stride/order mismatch at species {species}")
    selected = {
        "title": title, "variant": title, "artifact": ctx.artifact,
        "repo": ctx.lock["outputs"][ctx.artifact]["source"], "sym": f"{ctx.artifact}.sym",
        "rom_sha1": ctx.lock["outputs"][ctx.artifact]["sha1"], "ram": ram, "ram_bank": banks,
        "hram": hram, "sram_bank": sram_banks, "rom": rom, "derived": derived,
        "constants": constants, "storage_boxes": boxes,
        "constant_sources": source_files,
    }
    return {"schema": "gen2-profile-v1", "generator": "tools/gen_gen2_profile.py",
            "source": ctx.source_record(), "write_authority": "NONE", "titles": {title: selected}}


def render(profile: dict) -> str:
    return json.dumps(profile, indent=2, sort_keys=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--title", choices=tuple(ARTIFACTS))
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--out-dir", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    try:
        out = args.out_dir or args.root / "data/games"
        titles = [args.title] if args.title else list(ARTIFACTS)
        pending = {out / f"gen2_{title}" / "profile.json": render(build(title, root=args.root)).encode()
                   for title in titles}
        if args.check:
            for path, data in pending.items():
                if not path.is_file() or path.read_bytes() != data:
                    raise ValueError(f"profile missing or stale: {path}")
            print("Gen 2 selected profiles are current (SOURCE only)")
            return 0
        # Finish validation for every selected title before the first publication.
        for path, data in pending.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        print(f"wrote {len(pending)} selected-title profiles (SOURCE only)")
        return 0
    except (ValueError, OSError, SyntaxError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
