"""Generate data/games/polished_crystal/profile.json (gen2-profile-v1 family) for the Polished Lua client.

Every address and struct member offset comes from the OVERLAY build's own .sym
(data/polished/polished_slink.sym, so wSlinkMailbox is included); the Polished MON_* rsreset block is
never used (docs/polished/RAM.md §2.1: it disagrees with the built ROM). Source constants (stat-stage
bounds, masks, capacities) come from the pinned polishedcrystal checkout via tools/gen_polished_pack.py's
parser, and each is cross-checked against the .sym geometry where one exists. Run with --check to compare.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gen_polished_pack as pack  # noqa: E402
from gen_gen2_profile import OVERLAY_RAM, render, slink_abi_version  # noqa: E402
from rgbds_symbols import parse_symbols  # noqa: E402

ROOT = pack.ROOT
OUT = ROOT / "data/games/polished_crystal/profile.json"
SYM = ROOT / "data/polished/polished_slink.sym"
PROVENANCE = ROOT / "data/polished/overlay_provenance.json"
TITLE, ARTIFACT = "polished", "polishedcrystal"

RAM = (
    "wPartyCount", "wPartyMons", "wPartyMonOTs", "wPartyMonNicknames", "wPartyMonNicknamesEnd",
    "wPlayerID", "wPlayerName", "wRivalName", "wMapGroup", "wMapNumber", "wYCoord", "wXCoord",
    "wBattleMode", "wBattleType", "wBattleResult", "wCurBattleMon", "wOtherTrainerClass", "wOtherTrainerID",
    "wJohtoBadges", "wKantoBadges", "wCurBox", "wSavedAtLeastOnce", "wScriptRunning", "wLinkMode",
    "wBattleMonNickname", "wEnemyMonNickname", "wPlayerStatLevels", "wEnemyStatLevels",
    "wOTPlayerName", "wOTPlayerID", "wOTPartyCount", "wOTPartyMons", "wOTPartyMonOTs",
    "wOTPartyMonNicknames", "wOTPartyDataEnd", "wMirrorHerbPendingBoosts",
)
# (id+quantity) pockets: count byte, data, End label (capacity = (End - data - 1) / 2), source constant
POCKETS = {"items": ("wNumItems", "wItems", "wItemsEnd", "MAX_ITEMS"),
           "medicine": ("wNumMedicine", "wMedicine", "wMedicineEnd", "MAX_MEDICINE"),
           "balls": ("wNumBalls", "wBalls", "wBallsEnd", "MAX_BALLS"),
           "berries": ("wNumBerries", "wBerries", "wBerriesEnd", "MAX_BERRIES")}
STAGES = (("ATTACK", "Atk"), ("DEFENSE", "Def"), ("SPEED", "Spe"), ("SP_ATTACK", "SAtk"),
          ("SP_DEFENSE", "SDef"), ("ACCURACY", "Acc"), ("EVASION", "Eva"))
CONSTANTS = {
    "constants/battle_constants.asm": ("MAX_LEVEL", "NUM_MOVES", "BASE_STAT_LEVEL", "MAX_STAT_LEVEL",
                                       "NUM_LEVEL_STATS", "WILD_BATTLE", "TRAINER_BATTLE",
                                       "BATTLERESULT_BITMASK", *(name for name, _ in STAGES)),
    "constants/pokemon_data_constants.asm": ("NUM_BOXES", "MONS_PER_BOX", "PARTY_LENGTH", "SHINY_MASK",
                                             "ABILITY_MASK", "NATURE_MASK", "GENDER_MASK", "IS_EGG_MASK",
                                             "EXTSPECIES_MASK", "FORM_MASK"),
    "constants/text_constants.asm": ("NAME_LENGTH", "MON_NAME_LENGTH", "PLAYER_NAME_LENGTH"),
    "constants/ram_constants.asm": ("NUM_JOHTO_BADGES", "NUM_KANTO_BADGES"),
    "constants/item_data_constants.asm": ("MAX_ITEM_STACK", "MAX_ITEMS", "MAX_MEDICINE", "MAX_BALLS",
                                          "MAX_BERRIES"),
}
# C-ROMTABLES (docs/polished/ROMTABLES.md): the encounter-table reader lua/gen2/rom.lua.
CONSTANTS["constants/pokemon_constants.asm"] = ("NUM_SPECIES", "NUM_POKEMON")
CONSTANTS["constants/map_data_constants.asm"] = ("FISHGROUP_SHORE", "NUM_FISHGROUPS")
# rom.lua base_stats field -> BASE_* member. Polished has no BASE_DEX_NO (no species byte) and packs
# gender with egg steps in one byte (BASE_EGG_STEPS EQU BASE_GENDER), so `hatch` is left out.
BASE_FIELDS = {"hp": "BASE_HP", "attack": "BASE_ATK", "defense": "BASE_DEF", "speed": "BASE_SPE",
               "sat": "BASE_SAT", "sdf": "BASE_SDF", "type1": "BASE_TYPE_1", "type2": "BASE_TYPE_2",
               "catch_rate": "BASE_CATCH_RATE", "base_exp": "BASE_EXP", "item1": "BASE_ITEM_1",
               "item2": "BASE_ITEM_2", "gender": "BASE_GENDER", "growth": "BASE_GROWTH_RATE",
               "egg_groups": "BASE_EGG_GROUPS", "tmhm": "BASE_TMHM"}
CONSTANTS["constants/pokemon_data_constants.asm"] += (
    "NUM_GRASSMON", "NUM_WATERMON", "GRASS_WILDDATA_LENGTH", "WATER_WILDDATA_LENGTH", "FISHGROUP_DATA_LENGTH",
    "NUM_ROAMMON_MAPS", "LEVEL_FROM_BADGES", "NUM_TREEMON_SETS", "TREEMON_SET_ROCK", *BASE_FIELDS.values())
WILD_REGIONS = ("Johto", "Kanto", "Orange", "Swarm")
ROM_SYMBOLS = ("BaseData", "GrassMonProbTable", "WaterMonProbTable", "TreeMons", "TreeMonMaps", "RockMonMaps",
               "FishGroups", "RoamMaps", "InitRoamMons", "CheckEncounterRoamMon", "ContestMons", "ContestMonsEnd",
               *(f"{r}{kind}WildMons" for r in WILD_REGIONS for kind in ("Grass", "Water")))
# rom symbol -> its key in the generated UPR ini (a second, independently generated view of the clean sym)
INI_KEYS = {"BaseData": "PokemonStatsOffset", "FishGroups": "FishingWildsOffset", "ContestMons": "BCCWildsOffset",
            "TreeMons": "TreemonWildsOffset", "RoamMaps": "RoamMonsterMapsOffset",
            **{f"{r}{k}WildMons": f"{r}{k}WildMonsOffset" for r in WILD_REGIONS for k in ("Grass", "Water")}}
INI = ROOT / "data/polished/upr_polished_entries.ini"
PARTY_REQUIRED = ("Species", "Item", "Moves", "ID", "Exp", "EVs", "HPEV", "AtkEV", "DefEV", "SpeEV",
                  "SatEV", "SdfEV", "DVs", "Personality", "Form", "PP",
                  "Happiness", "PokerusStatus", "CaughtData", "CaughtLevel", "CaughtLocation", "Level",
                  "Status", "Unused", "HP", "MaxHP", "Attack", "Defense", "Speed", "SpAtk", "SpDef", "End")
BATTLE_REQUIRED = ("Species", "Item", "Moves", "DVs", "Personality", "Form", "PP", "Happiness", "Level",
                   "Status", "HP", "MaxHP", "Attack", "Defense", "Speed", "SpAtk", "SpDef", "Type1", "Type2",
                   "StructEnd")


def require(cond, msg):
    if not cond:
        raise ValueError(msg)


def _members(symbols, prefix, end_name):
    """{suffix: offset} of every <prefix><Suffix> label inside [prefix, prefix+end]; one bank."""
    bank, base = symbols[prefix]
    end = symbols[prefix + end_name]
    require(end.bank == bank and end.address > base, f"{prefix}{end_name} geometry")
    out = {}
    for name, (b, address) in symbols.items():
        suffix = name[len(prefix):]
        if name.startswith(prefix) and re.fullmatch(r"[A-Z]\w*", suffix) and b == bank \
                and base <= address <= end.address:
            out[suffix] = address - base
    return out


def _routine(rel, label, stop):
    """Code lines of `label` up to (not including) the first line equal to `stop`."""
    out, inside = [], False
    for _, line in pack.lines(rel):
        if line == label:
            inside = True
        elif inside and line == stop:
            return out
        elif inside:
            out.append(line)
    raise ValueError(f"{rel}: {label} .. {stop} not found")


def _ini() -> dict:
    """key=value pairs of the generated UPR ini, after checking it was cut from the pinned clean sym."""
    text = INI.read_text(encoding="utf-8")
    require(f"sym sha256 {pack.sha256(pack.SYM_PATH)}" in text, f"{INI.name}: not generated from {pack.SYM_PATH.name}")
    pairs = (line.split("//", 1)[0].strip().partition("=") for line in text.splitlines())
    return {k.strip(): v.strip() for k, sep, v in pairs if sep}


def rom_tables(symbols, constants) -> tuple[dict, dict, dict]:
    """profile.rom, the reader's derived counts and the `layout` block for lua/gen2/rom.lua."""
    clean, ini = parse_symbols(pack.SYM_PATH.read_text(encoding="utf-8")), _ini()
    rom = {}
    for name in ROM_SYMBOLS:
        require(name in symbols and symbols[name] == clean.get(name), f"{name}: overlay and clean sym disagree")
        bank, addr = symbols[name]
        require(bank >= 1 and 0x4000 <= addr < 0x8000, f"{name} outside banked ROM")
        rom[name] = {"bank": bank, "addr": addr, "flat": bank * 0x4000 + addr - 0x4000}
        if name in INI_KEYS:
            require(int(ini[INI_KEYS[name]], 16) == rom[name]["flat"], f"{name}: ini offset disagrees")
    require("TimeFishGroups" not in symbols, "TimeFishGroups present: the fishing layout changed")
    regions = sorted(WILD_REGIONS, key=lambda r: rom[f"{r}GrassWildMons"]["flat"])
    require(tuple(regions) == WILD_REGIONS, "wild region tables out of order")

    # GRASS_WILDDATA_LENGTH = 2 + (1 + NUM_GRASSMON * slot) * 3, slot = level byte + species bytes
    grass, water = constants["GRASS_WILDDATA_LENGTH"], constants["WATER_WILDDATA_LENGTH"]
    slot, rest = divmod((grass - 2) // 3 - 1, constants["NUM_GRASSMON"])
    require(rest == 0 and (grass - 2) % 3 == 0 and slot >= 2, "GRASS_WILDDATA_LENGTH shape")
    require(water == 2 + 1 + constants["NUM_WATERMON"] * slot, "WATER_WILDDATA_LENGTH disagrees with the grass slot")
    widths = {line.split()[1] for _, line in pack.lines("data/wild/probabilities.asm")
              if line.startswith("table_width")}
    require(len(widths) == 1, "probability tables disagree on table_width")
    gate = _routine("engine/events/treemons.asm", "GetTreeMons:", "add a")
    require(gate == ["cp NUM_TREEMON_SETS", "ret nc"], f"unsupported GetTreeMons set gate: {gate}")
    init = _routine("engine/overworld/wildmons.asm", "InitRoamMons:", "CheckEncounterRoamMon:")
    roamers = sorted({int(n) for line in init for n in re.findall(r"ld \[wRoamMon(\d+)Species\], a", line)})
    require(roamers and roamers == list(range(1, len(roamers) + 1)), "non-contiguous or empty roamer slots")

    tmhm_bits = sum(1 for _, line in pack.lines("constants/tmhm_constants.asm")
                    if line.split(" ", 1)[0] in ("add_tm", "add_hm", "add_mt"))
    stride = constants["BASE_TMHM"] + (tmhm_bits + 7) // 8
    require(int(ini["BaseStatsEntrySize"]) == stride, "BASE_DATA_SIZE: source and ini disagree")
    require(int(ini["SpeciesCount"]) == constants["NUM_SPECIES"], "NUM_SPECIES: source and ini disagree")
    derived = {
        # 291 is the species-id validation bound; 289 (NUM_POKEMON) is not (ROMTABLES.md 8.5)
        "species_count": constants["NUM_SPECIES"], "num_pokemon": constants["NUM_POKEMON"],
        "base_stats_stride": stride, "base_tmhm_offset": constants["BASE_TMHM"],
        "num_grassmon": constants["NUM_GRASSMON"], "num_watermon": constants["NUM_WATERMON"],
        "num_treemon_sets": constants["NUM_TREEMON_SETS"], "treemon_set_rock": constants["TREEMON_SET_ROCK"],
        "treemon_enabled_limit": constants["NUM_TREEMON_SETS"],
        "num_fishgroups": constants["NUM_FISHGROUPS"], "num_time_fishgroups": 0,
        "num_roammon_maps": constants["NUM_ROAMMON_MAPS"], "roamer_count": len(roamers),
        # battle types whose wild encounter resolves an area (ROMTABLES.md 4.1): normal, fish, tree
        "area_battle_types": [constants[f"BATTLETYPE_{n}"] for n in ("NORMAL", "FISH", "TREE")],
    }
    layout = {
        "species_bytes": slot - 1, "prob_width": int(widths.pop()),
        "wild_grass_row": grass, "wild_water_row": water, "wild_regions": list(WILD_REGIONS),
        "fish_group_header": constants["FISHGROUP_DATA_LENGTH"], "fish_group_base": constants["FISHGROUP_SHORE"],
        "tree_first_set": 0, "level_from_badges": constants["LEVEL_FROM_BADGES"],
        "roamer_inc_a": "inc a" in init,
        "species_count": int(ini["SpeciesCount"]), "base_stats_stride": int(ini["BaseStatsEntrySize"]),
        "base_fields": {field: constants[name] for field, name in BASE_FIELDS.items()},
    }
    return rom, derived, layout


def build() -> dict:
    pack.verify_source()
    raw_sym, raw_prov = SYM.read_bytes(), PROVENANCE.read_bytes()
    prov = json.loads(raw_prov)
    sym_sha = hashlib.sha256(raw_sym).hexdigest()
    require(prov.get("schema") == "polished-overlay-provenance-v1", "overlay provenance: unsupported schema")
    require(prov["symbols"].get(SYM.name) == sym_sha, f"{SYM.name} sha256 differs from overlay provenance")
    clean = pack.LOCK["outputs"][ARTIFACT]
    out = prov["output"]
    require(prov["base_sha1"] == clean["sha1"] and prov["source"]["commit"] == pack.LOCK["source"]["commit"],
            "overlay provenance base/commit disagrees with the lock")
    require(out["identical_to_clean"] is False and out["sha1"] != clean["sha1"], "overlay must differ from clean")
    require(out["title"].split("\u0000")[0] == clean["title"], "overlay header title disagrees with the lock")
    abi = slink_abi_version(ROOT)
    require(prov["abi_version"] == abi, "overlay provenance ABI differs from patch/gb/slink_abi.inc")
    symbols = parse_symbols(raw_sym.decode("utf-8"))

    constants = {}
    for rel, names in CONSTANTS.items():
        values = pack.parse_consts(rel)
        for name in names:
            require(type(values.get(name)) is int, f"{rel}: {name} unresolved")
            constants[name] = values[name]
    constants.update({k: v for k, v in pack.parse_consts("constants/battle_constants.asm").items()
                      if k.startswith("BATTLETYPE_")})

    names = set(RAM) | {fields[i] for fields in POCKETS.values() for i in range(3)}
    names |= {f"w{side}{suffix}Level" for side in ("Player", "Enemy") for _, suffix in STAGES}
    patterns = (r"wPartyMon[1-6]\w*", r"wBattleMon\w*", r"wEnemyMon\w*", r"wRoamMon\d\w*", r"h\w+")
    names |= {n for n in symbols if any(re.fullmatch(p, n) for p in patterns)}
    names |= set(OVERLAY_RAM)
    ram, ram_bank, hram = {}, {}, {}
    for name in sorted(names):
        require(name in symbols, f"{SYM.name}: required symbol {name} missing")
        bank, address = symbols[name]
        if name.startswith("h"):
            require(bank == 0 and 0xFF80 <= address <= 0xFFFF, f"{name} outside HRAM")
            hram[name] = address
        else:
            require((bank == 0 and 0xC000 <= address < 0xD000) or (1 <= bank <= 7 and 0xD000 <= address < 0xE000),
                    f"{name} outside WRAM0/WRAMX")
        ram[name], ram_bank[name] = address, bank

    party = _members(symbols, "wPartyMon1", "End")
    battle = _members(symbols, "wBattleMon", "StructEnd")
    enemy = _members(symbols, "wEnemyMon", "StructEnd")
    require(all(k in party for k in PARTY_REQUIRED), f"party_struct members missing: {set(PARTY_REQUIRED) - set(party)}")
    require(all(k in battle for k in BATTLE_REQUIRED), f"battle_struct members missing: {set(BATTLE_REQUIRED) - set(battle)}")
    require({k: v for k, v in enemy.items() if k in battle} == {k: battle[k] for k in enemy if k in battle}
            and set(BATTLE_REQUIRED) <= set(enemy), "wEnemyMon/wBattleMon struct offsets differ")

    def diff(a, b):
        require(symbols[a].bank == symbols[b].bank, f"{a}/{b} in different banks")
        return symbols[a].address - symbols[b].address

    size, cap = party["End"], constants["PARTY_LENGTH"]
    checks = {
        "wPartyMon2 - wPartyMon1": (diff("wPartyMon2", "wPartyMon1"), size),
        "wPartyMonOTs - wPartyMons": (diff("wPartyMonOTs", "wPartyMons"), cap * size),
        "NAME_LENGTH": (diff("wPartyMon2OT", "wPartyMon1OT"), constants["NAME_LENGTH"]),
        "PLAYER_NAME_LENGTH": (diff("wPartyMon1Extra", "wPartyMon1OT"), constants["PLAYER_NAME_LENGTH"]),
        "MON_NAME_LENGTH": (diff("wPartyMon2Nickname", "wPartyMon1Nickname"), constants["MON_NAME_LENGTH"]),
        "wPartyMonNicknames - wPartyMonOTs": (diff("wPartyMonNicknames", "wPartyMonOTs"), cap * constants["NAME_LENGTH"]),
        "wPartyMonNicknamesEnd": (diff("wPartyMonNicknamesEnd", "wPartyMonNicknames"), cap * constants["MON_NAME_LENGTH"]),
        "wPlayerName length": (diff("wRivalName", "wPlayerName"), constants["NAME_LENGTH"]),
        "wPlayerStatLevels": (diff("wEnemyStatLevels", "wPlayerStatLevels"), constants["NUM_LEVEL_STATS"]),
        "wOTPartyMons stride": (diff("wOTPartyMonOTs", "wOTPartyMons"), cap * size),
        "wOTPartyDataEnd": (diff("wOTPartyDataEnd", "wOTPartyMonNicknames"), cap * constants["MON_NAME_LENGTH"]),
    }
    for side in ("Player", "Enemy"):
        for index, suffix in STAGES:
            checks[f"w{side}{suffix}Level"] = (diff(f"w{side}{suffix}Level", f"w{side}StatLevels"), constants[index])
    pockets = {}
    for pocket, (count, data, end, constant) in POCKETS.items():
        capacity, rest = divmod(diff(end, data) - 1, 2)
        checks[f"{pocket} capacity"] = (capacity, constants[constant])
        checks[f"{pocket} terminator byte"] = (rest, 0)
        checks[f"{pocket} count precedes data"] = (diff(data, count), 1)
        pockets[pocket] = {"count": count, "data": data, "capacity": capacity}
    for label, (measured, expected) in checks.items():
        require(measured == expected, f"{label}: sym geometry {measured} != source {expected}")

    overlay = {"artifact": "polished_overlay", "base_sha1": clean["sha1"], "rom_sha1": out["sha1"],
               "md5": out["md5"], "sym": SYM.name, "sym_sha256": sym_sha, "abi": abi,
               "ram": {name: ram[name] for name in OVERLAY_RAM}}
    for name in OVERLAY_RAM:
        require(ram_bank[name] == 0, f"{name} outside WRAM0")
    rom, rom_derived, layout = rom_tables(symbols, constants)
    source = pack.source_block()
    source.update({"artifact": ARTIFACT, "overlay_sha1": out["sha1"], "overlay_sym_sha256": sym_sha,
                   "overlay_provenance_sha256": hashlib.sha256(raw_prov).hexdigest(),
                   "generator": "tools/gen_polished_profile.py"})
    selected = {
        "title": TITLE, "variant": TITLE, "artifact": ARTIFACT, "repo": pack.LOCK["source"]["url"],
        "sym": SYM.name, "rom_sha1": clean["sha1"], "header_title": clean["title"],
        "ram": ram, "ram_bank": ram_bank, "hram": hram, "constants": constants, "rom": rom, "layout": layout,
        "structs": {"party": party, "battle": battle},
        "derived": {"party_struct_size": size, "battle_struct_size": battle["StructEnd"], "party_capacity": cap,
                    "name_length": constants["NAME_LENGTH"], "mon_name_length": constants["MON_NAME_LENGTH"],
                    "player_name_length": constants["PLAYER_NAME_LENGTH"], "num_boxes": constants["NUM_BOXES"],
                    "rom_size": out["size"], "pockets": pockets, **rom_derived,
                    # (species_id, form_id) pairs that are REGIONAL/variant forms = different mons (owner 2026-10-04);
                    # every other form is cosmetic and keys as form 0 (polished_codec.key_form). From forms_index.json.
                    "variant_forms": sorted([r["species_id"], r["form_id"]] for r in json.loads(
                        (OUT.parent / "forms_index.json").read_text(encoding="utf-8"))["variant_forms"])},
        "overlay": overlay,
    }
    return {"schema": "gen2-profile-v1", "generator": "tools/gen_polished_profile.py", "source": source,
            "write_authority": "NONE", "titles": {TITLE: selected}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    try:
        data = render(build()).encode()
        if args.check:
            require(OUT.is_file() and OUT.read_bytes() == data, f"profile missing or stale: {OUT}")
            print("Polished profile is current (SOURCE only)")
        else:
            OUT.write_bytes(data)
            print(f"wrote {OUT.relative_to(ROOT)} (SOURCE only)")
        return 0
    except (ValueError, OSError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
