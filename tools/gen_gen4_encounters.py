#!/usr/bin/env python3
"""gen_gen4_encounters.py -- HGSS wild encounter tables, per version, from pinned pret/pokeheartgold.

Writes data/games/gen4_hgss/encounters.json.

Sources (pokeheartgold @ the pinned commit; see data/gen4_sources.lock.json):
  files/fielddata/encountdata/gs_enc_data.json  142 encounter banks. HG/SS differences are nested
                                                {"HEARTGOLD":..,"SOULSILVER":..} under land levels, per-time-of-day
                                                species, surf/fishing/rock-smash slots, swarms and radio species
                                                (53 of 142 banks differ). Every bank is emitted once per version.
  include/encounter_tables_narc.h               ENCDATA_<token> -> array index (the bank id the map header names)
  files/arc/headbutt.json                       headbutt tables, one per map id; species {"gold","silver"} split
  files/arc/safari_enc.json                     Safari encounters per Safari AREA (no HG/SS split exists)
  include/constants/species.h, msg_0237.gmm     species id and name
  src/data/map_headers.h (via gen_gen4_area_map) which map ids point at which bank

Slot percentages are not data: they are hard-coded in src/field/encounter_check.c
(EncounterSlot_WildMonSlotRoll_*), cited in `slot_rates`. Safari rolls LCRandom() % 10 (uniform).
Pal Park (files/arc/ppark.json) is deliberately not emitted: it only accepts migrated mons.

Usage:
  python tools/gen_gen4_encounters.py [--pret PATH] [--check]
Exit: 0 ok, 1 drift / wrong pret commit, 2 pret clone absent.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gen_gen4_area_map as base  # noqa: E402

VERSIONS = {"heartgold": "HEARTGOLD", "soulsilver": "SOULSILVER"}
HEADBUTT_VER = {"heartgold": "gold", "soulsilver": "silver"}
TIMES = ("morn", "day", "nite")
SLOT_RATES = {
    "_source": "src/field/encounter_check.c EncounterSlot_WildMonSlotRoll_Land/Surfing/Fishing/RockSmash/Headbutt (LCRandRange(100)); safari: LCRandom() % NUM_ENCOUNTERS_SAFARI",
    "land": [20, 20, 10, 10, 10, 10, 5, 5, 4, 4, 1, 1],
    "surf": [60, 30, 5, 4, 1],
    "fishing": [40, 30, 15, 10, 5],
    "rock_smash": [80, 20],
    "headbutt": [50, 15, 15, 10, 5, 5],
    "safari": [10] * 10,
}
INPUTS = [
    "files/fielddata/encountdata/gs_enc_data.json",
    "include/encounter_tables_narc.h",
    "files/arc/headbutt.json",
    "files/arc/safari_enc.json",
    "include/constants/species.h",
    "files/msgdata/msg/msg_0237.gmm",
    "include/constants/maps.h",
    "src/data/map_headers.h",
]


def split(obj, ver: str):
    """Collapse a {"HEARTGOLD":..,"SOULSILVER":..} node to this version's value; pass anything else through."""
    if isinstance(obj, dict) and set(obj) == {"HEARTGOLD", "SOULSILVER"}:
        return obj[ver]
    return obj


def has_split(obj) -> bool:
    if isinstance(obj, dict):
        if set(obj) == {"HEARTGOLD", "SOULSILVER"}:
            return True
        return any(has_split(v) for v in obj.values())
    if isinstance(obj, list):
        return any(has_split(v) for v in obj)
    return False


class Species:
    def __init__(self, clone: Path):
        self.ids = base.defines(clone, "include/constants/species.h", "SPECIES_")
        names = base.gmm(clone, 237)
        self.names = {sid: base.titled(names[sid]) for sid in names}

    def ref(self, const: str) -> dict:
        sid = self.ids[const]  # KeyError = unknown constant = fail closed
        return {"species_id": sid, "name": "" if sid == 0 else self.names[sid]}


def slot(sp: Species, const: str, lo: int, hi: int, rate: int) -> dict:
    """One encounter slot; its list position is the game slot index."""
    return {**sp.ref(const), "rate": rate, "min_level": lo, "max_level": hi}


def bank_for(sp: Species, enc: dict, ver: str) -> dict:
    out: dict = {
        "rates": {
            "land": enc["land"]["rate"],
            "surf": enc["surf"]["rate"],
            "rock_smash": enc["rock_smash"]["rate"],
            "old_rod": enc["fishing"]["old_rod"]["rate"],
            "good_rod": enc["fishing"]["good_rod"]["rate"],
            "super_rod": enc["fishing"]["super_rod"]["rate"],
        }
    }
    land = enc["land"]["mons"]
    if land:
        assert len(land) == 12, "land slot count drifted"
        out["land"] = {
            t: [
                slot(sp, split(m["species"][t], ver), (lv := split(m["level"], ver)), lv, SLOT_RATES["land"][i])
                for i, m in enumerate(land)
            ]
            for t in TIMES
        }

    def methods(key: str, mons: list, rates: list[int]):
        if not mons:
            return
        assert len(mons) == len(rates), f"{key} slot count drifted"
        out[key] = [
            slot(sp, split(m["species"], ver), split(m["level"]["min"], ver), split(m["level"]["max"], ver), rates[i])
            for i, m in enumerate(mons)
        ]

    methods("surf", enc["surf"]["mons"], SLOT_RATES["surf"])
    methods("rock_smash", enc["rock_smash"]["mons"], SLOT_RATES["rock_smash"])
    for rod in ("old_rod", "good_rod", "super_rod"):
        methods(rod, enc["fishing"][rod]["mons"], SLOT_RATES["fishing"])
    radio = {k: [sp.ref(split(m, ver))["species_id"] for m in enc[k]] for k in ("hoenn", "sinnoh")}
    if any(radio.values()):
        out["radio"] = {k: [sp.ref(split(m, ver)) for m in enc[k]] for k in ("hoenn", "sinnoh")}
    swarm = {}
    for key, name in (("landSwarm", "land"), ("surfSwarm", "surf"), ("fishSwarm", "fish"), ("nightFish", "night_fish")):
        if key in enc:
            swarm[name] = sp.ref(split(enc[key], ver))
    if swarm:
        out["swarm"] = swarm
    return out


def headbutt_for(sp: Species, tables: list[dict], maps: base.Maps, ver: str) -> dict:
    gs = HEADBUTT_VER[ver]

    def mons(rows):
        return [
            {**sp.ref(m["species"][gs] if isinstance(m["species"], dict) else m["species"]), "rate": SLOT_RATES["headbutt"][i], "min_level": m["minLevel"], "max_level": m["maxLevel"]}
            for i, m in enumerate(rows)
        ]

    out = {}
    for mid, t in enumerate(tables):
        assert maps.rows[mid]["token"] == t["Map"], f"headbutt table {mid} is {t['Map']}, map header says {maps.rows[mid]['token']}"
        if not t["Trees"] and not t["SecretTrees"]:
            continue
        out[str(mid)] = {"token": t["Map"], "trees": len(t["Trees"]), "secret_trees": len(t["SecretTrees"]), "common": mons(t["CommonMons"]), "rare": mons(t["RareMons"]), "secret": mons(t["SecretMons"])}
    return out


def safari_for(sp: Species, areas: list[dict]) -> dict:
    def refs(rows):
        return [{**sp.ref(m["species"]), "level": m["level"]} for m in rows]

    out = {}
    for a in areas:
        entry = {}
        for method in ("land", "surf", "oldrod", "goodrod", "superrod"):
            d = a[method]
            entry[method] = {
                "slots": {t: refs(d["mons"][t]) for t in TIMES},
                "bonus": [
                    {"conditions": b["conditions"], **{t: {**sp.ref(b[t]["species"]), "level": b[t]["level"]} for t in TIMES}}
                    for b in d["bonus_mons"]
                ],
            }
        out[a["area"].removeprefix("SAFARI_ZONE_AREA_").lower()] = {"const": a["area"], **entry}
    return out


def build(clone: Path) -> dict[str, str]:
    maps = base.Maps(clone)
    sp = Species(clone)
    enc = json.loads(base.read(clone, "files/fielddata/encountdata/gs_enc_data.json"))["encounters"]
    assert len(enc) == 142, f"gs_enc_data.json has {len(enc)} banks, pinned source has 142"
    index = {int(n): tok for tok, n in re.findall(r"#define ENCDATA_(\w+)\s+ENCDATA\(_(\d+)\)", base.read(clone, "include/encounter_tables_narc.h"))}
    users: dict[str, list[int]] = {}
    for mid, row in maps.rows.items():
        if row["enc_bank"]:
            users.setdefault(row["enc_bank"], []).append(mid)
    area_of = base.build_model(clone)["map_area"]

    banks = {}
    for i, e in enumerate(enc):
        token = index[i]
        banks[token] = {"index": i, "json_map": e["map"], "maps": users.get(token, []), "areas": sorted({area_of[m] for m in users.get(token, []) if area_of[m]}), "version_split": has_split(e)}
    unused = [t for t, b in banks.items() if not b["maps"]]

    doc = {
        "_note": "GENERATED by tools/gen_gen4_encounters.py from pinned pret/pokeheartgold -- do not edit. banks: ENCDATA token -> index/maps/areas (version independent); versions.<title>.banks: the per-version tables; slots keep game slot order with the percentage in `rate`.",
        "_schema": "gen4-hgss-encounters-v1",
        "source": base.provenance(clone, "tools/gen_gen4_encounters.py", INPUTS),
        "slot_rates": SLOT_RATES,
        "banks": banks,
        "banks_without_map": unused,
        "bank_count": len(banks),
        "split_bank_count": sum(b["version_split"] for b in banks.values()),
        "excluded": {"pal_park": "files/arc/ppark.json: migrated mons only, out of scope"},
        "safari": {"version_split": False, "areas": safari_for(sp, json.loads(base.read(clone, "files/arc/safari_enc.json"))["encounters"])},
        "versions": {},
    }
    headbutt = json.loads(base.read(clone, "files/arc/headbutt.json"))["tables"]
    assert len(headbutt) == 540, "headbutt table count drifted"
    for title, ver in VERSIONS.items():
        doc["versions"][title] = {
            "banks": {index[i]: bank_for(sp, e, ver) for i, e in enumerate(enc)},
            "headbutt": headbutt_for(sp, headbutt, maps, title),
        }
    return {"encounters.json": base.dumps(doc, 6)}


def main() -> int:
    return base.cli(build, __doc__.splitlines()[0])


if __name__ == "__main__":
    sys.exit(main())
