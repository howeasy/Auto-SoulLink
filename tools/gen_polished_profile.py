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

    names = set(RAM) | {fields[i] for fields in POCKETS.values() for i in range(3)}
    names |= {f"w{side}{suffix}Level" for side in ("Player", "Enemy") for _, suffix in STAGES}
    patterns = (r"wPartyMon[1-6]\w*", r"wBattleMon\w*", r"wEnemyMon\w*", r"h\w+")
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
    source = pack.source_block()
    source.update({"artifact": ARTIFACT, "overlay_sha1": out["sha1"], "overlay_sym_sha256": sym_sha,
                   "overlay_provenance_sha256": hashlib.sha256(raw_prov).hexdigest(),
                   "generator": "tools/gen_polished_profile.py"})
    selected = {
        "title": TITLE, "variant": TITLE, "artifact": ARTIFACT, "repo": pack.LOCK["source"]["url"],
        "sym": SYM.name, "rom_sha1": clean["sha1"], "header_title": clean["title"],
        "ram": ram, "ram_bank": ram_bank, "hram": hram, "constants": constants,
        "structs": {"party": party, "battle": battle},
        "derived": {"party_struct_size": size, "battle_struct_size": battle["StructEnd"], "party_capacity": cap,
                    "name_length": constants["NAME_LENGTH"], "mon_name_length": constants["MON_NAME_LENGTH"],
                    "player_name_length": constants["PLAYER_NAME_LENGTH"], "num_boxes": constants["NUM_BOXES"],
                    "rom_size": out["size"], "pockets": pockets},
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
