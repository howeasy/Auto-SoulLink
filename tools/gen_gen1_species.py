#!/usr/bin/env python3
"""Generate the pureRGB species/types pack from source + a cross-check against the
built ROM (docs/purergb/PLAN.md S3.3, S11.2 A13; docs/purergb/research/d3/PACK_SCHEMAS.md S6).

pureRGB's internal species-id space is 190 (`$01-$BE`): 151 dex species (`BaseStats`,
Mew inline as dex 151) + 13 complete non-dex records (`NonDexMonsBaseStats`: MISSINGNO,
7 "form"/"transform-target" species, 5 uncatchable "spirits") + 3 picture-only entities
(no stat record) + 23 unused slots. `data/pokemon/base_stats.asm` INCLUDEs exactly these
164 stat-bearing files in one list -- the first 151 in dex order, the last 13 in the same
order as `engine/pokemon/get_mon_header.asm`'s `NonDexPokemonSpecies` table -- so the
generator reads that one INCLUDE list instead of hard-coding two separate orderings.

Every stat/type value is asserted against the built ROM's 35-byte `BaseStats`/
`NonDexMonsBaseStats` record (`constants/pokemon_data_constants.asm` BASE_DATA_SIZE) in
all three titles; source parsing alone would miss a ROM/source drift (S1's own history:
"3/40 predicted offsets wrong on a first pass").
"""
from __future__ import annotations

import json
import os
import re
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gen1_foundation as fnd  # noqa: E402
from gen_gen1_charmap import parse_charmap  # noqa: E402

_CONST_RE = re.compile(r"^\s*const\s+([A-Za-z_][A-Za-z0-9_]*)\s*$")
_SKIP_RE = re.compile(r"^\s*const_skip\b")
_CONST_DEF_RE = re.compile(r"^\s*const_def\b")
_INCLUDE_RE = re.compile(r'INCLUDE\s+"([^"]+)"')

BASE_DATA_SIZE = 35  # constants/pokemon_data_constants.asm BASE_DATA_SIZE:
# dex(1) stats(5) types(2) catch(1) exp(1) picsize(1) frontpic(2) backpic(2) moves(4)
# growth(1) tmhm(7) picbank(2) backpicbank(2) altfrontpic(2) altbackpic(2) = 35

# Ten `callfar ChangePartyPokemonSpecies` sites across 8 scripts (PLAN S3.3/S11.2 A13);
# nine distinct edges after collapsing DiamondMine's two repeatable call sites into one
# and folding SecretLab's single (bidirectional) call site into one row.
_TRANSFORM_EDGES = [
    ("MAGMAR", "VOLCANIC_MAGMAR", "CinnabarVolcanoWest", False),
    ("ONIX", "HARDENED_ONIX", "DiamondMine", False),
    ("POWERED_HAUNTER", "GENGAR", "LavenderCuboneHouse", False),
    ("GENGAR", "POWERED_HAUNTER", "PokemonTowerB1F", False),
    ("MAROWAK", "CUBONE", "PokemonTowerB1F", False),
    ("MAGNETON", "FLOATING_MAGNETON", "PowerPlant", False),
    ("DRAGONAIR", "WINTER_DRAGONAIR", "SeafoamIslands1F", False),
    ("MEWTWO", "ARMORED_MEWTWO", "SecretLab", True),
    ("WEEZING", "FLOATING_WEEZING", "SilphCo1F", False),
]


def parse_const_block(text: str) -> list[tuple[int, str | None]]:
    """[(value, name_or_None), ...] for one `const_def` ... block (const/const_skip)."""
    out: list[tuple[int, str | None]] = []
    value = None
    started = False
    for raw in text.splitlines():
        line = raw.split(";", 1)[0].rstrip()
        if _CONST_DEF_RE.match(line):
            value = 0
            started = True
            continue
        if not started:
            continue
        m = _CONST_RE.match(line)
        if m:
            out.append((value, m.group(1)))
            value += 1
            continue
        if _SKIP_RE.match(line):
            out.append((value, None))
            value += 1
            continue
        if line.strip() == "":
            continue
        break  # first non-const line ends the block
    return out


def parse_pokemon_ids(text: str) -> list[str | None]:
    """index 0 unused; [1] = name of internal id 1, ... up to 190."""
    entries = parse_const_block(text)
    names: list[str | None] = [None] * (len(entries))
    for value, name in entries:
        names[value] = name
    if names[0] != "NO_MON":
        raise SystemExit("pokemon_constants.asm: NO_MON is not id 0 -- parser drifted")
    return names  # names[1..190]


def parse_dex_ids(text: str) -> dict[str, int]:
    entries = parse_const_block(text)
    out = {name: value for value, name in entries if name}
    if out.get("DEX_MISSINGNO") != 0:
        raise SystemExit("pokedex_constants.asm: DEX_MISSINGNO is not 0")
    return out


def parse_dex_order(text: str, dex_ids: dict[str, int]) -> list[int]:
    """190 dex numbers, positional (internal id = position + 1)."""
    out: list[int] = []
    in_table = False
    for raw in text.splitlines():
        line = raw.split(";", 1)[0].strip()
        if line == "PokedexOrder:":
            in_table = True
            continue
        if not in_table:
            continue
        m = re.match(r"^db\s+(\w+)$", line)
        if not m:
            continue
        tok = m.group(1)
        out.append(0 if tok == "0" else dex_ids[tok])
    return out


def parse_species_array(text: str, label: str) -> list[str]:
    """`db NAME` lines between `<label>:` and the `db -1` terminator."""
    out: list[str] = []
    in_block = False
    for raw in text.splitlines():
        line = raw.split(";", 1)[0].strip()
        if line == f"{label}:":
            in_block = True
            continue
        if not in_block:
            continue
        if line == "db -1":
            break
        m = re.match(r"^db\s+(\w+)$", line)
        if m:
            out.append(m.group(1))
    return out


def parse_growth_rates(text: str) -> list[str]:
    # pokemon_data_constants.asm has several `const_def` blocks (EVOLVE_*, growth
    # rates, ...); anchor on the growth-rate block's own header comment.
    block = text.split("; GrowthRateTable indexes", 1)[1]
    return [name for _, name in parse_const_block(block) if name and name.startswith("GROWTH_")]


def parse_type_names(text: str) -> dict[int, str]:
    """id (0..NUM_TYPES-1) -> display name, from constants/type_constants.asm.

    `const_def`/`const`/`const_next N` (not `const_skip`): a handful of ids in the
    $0B-$10 gap have no name at all (reserved, never assigned to any move/species).
    """
    out: dict[int, str] = {}
    value = 0
    started = False
    for raw in text.splitlines():
        line = raw.split(";", 1)[0].rstrip()
        if _CONST_DEF_RE.match(line):
            started = True
            value = 0
            continue
        if not started:
            continue
        m = _CONST_RE.match(line)
        if m:
            out[value] = m.group(1)
            value += 1
            continue
        m = re.match(r"^\s*const_next\s+(\d+)\s*$", line)
        if m:
            value = int(m.group(1))
            continue
        if re.match(r"^\s*DEF\s+NUM_TYPES\s+EQU\s+const_value", line):
            break
    return out


def parse_base_stats_include_order(text: str) -> list[str]:
    return [m.group(1) for m in _INCLUDE_RE.finditer(text)]


_STATS_RE = re.compile(
    r"db\s+DEX_(\w+)\s*;\s*pokedex id.*?"
    r"db\s+(\d+),\s*(\d+),\s*(\d+),\s*(\d+),\s*(\d+)\s*\n\s*;\s*hp\s+atk\s+def\s+spd\s+spc.*?"
    r"db\s+(\w+),\s*(\w+)\s*;\s*type\s*\n\s*db\s+(\d+)\s*;\s*catch rate\s*\n\s*db\s+(\d+)\s*;\s*base exp"
    r".*?db\s+(?:\w+,\s*){0,3}\w+\s*;\s*level 1 learnset\s*\n\s*db\s+(GROWTH_\w+)\s*;\s*growth rate",
    re.DOTALL,
)


def parse_base_stats_file(text: str) -> dict:
    m = _STATS_RE.search(text)
    if not m:
        raise SystemExit("base_stats file did not match the expected record shape")
    dex_const, hp, atk, dfn, spd, spc, t1, t2, catch, exp, growth = m.groups()
    return {
        "dex_const": f"DEX_{dex_const}",
        "stats": [int(hp), int(atk), int(dfn), int(spd), int(spc)],
        "type1": t1, "type2": t2,
        "catch_rate": int(catch), "base_exp": int(exp),
        "growth_rate": growth,
    }


def _unpack_record(raw: bytes) -> dict:
    dex, hp, atk, dfn, spd, spc, t1, t2, catch, exp = struct.unpack_from("<10B", raw, 0)
    growth = raw[19]
    return {"dex": dex, "stats": [hp, atk, dfn, spd, spc], "type1": t1, "type2": t2,
            "catch_rate": catch, "base_exp": exp, "growth": growth}


def parse_monster_names(text: str) -> list[str]:
    """internal id n -> name, from `data/pokemon/names.asm` (line n+2 = `dname "X"`)."""
    names: list[str] = []
    for raw in text.splitlines():
        m = re.match(r'^\s*dname\s+"([^"]*)"', raw)
        if m:
            names.append(m.group(1))
    return names


def decode_name(raw: bytes, glyphs: dict[int, str], terminator: int) -> str:
    out = []
    for b in raw:
        if b == terminator:
            break
        out.append(glyphs.get(b, f"<${b:02X}>"))
    return "".join(out)


def build(foundation: str) -> tuple[dict, dict, list[str]]:
    disagreements: list[str] = []

    pokemon_ids_text = fnd.read_source(foundation, "constants/pokemon_constants.asm")
    fnd.assert_source(foundation, "constants/pokemon_constants.asm", "DEF NUM_POKEMON_INDEXES EQU const_value - 1")
    names_by_id = parse_pokemon_ids(pokemon_ids_text)  # index 1..190
    n_species = len(names_by_id) - 1
    if n_species != 190:
        raise SystemExit(f"expected 190 internal species ids, parsed {n_species}")
    name_to_id = {name: i for i, name in enumerate(names_by_id) if name}

    dex_ids_text = fnd.read_source(foundation, "constants/pokedex_constants.asm")
    fnd.assert_source(foundation, "constants/pokedex_constants.asm", "DEF NUM_POKEMON EQU const_value")
    dex_ids = parse_dex_ids(dex_ids_text)
    num_pokemon = max(dex_ids.values()) + 1
    if num_pokemon != 152:
        raise SystemExit(f"expected NUM_POKEMON=152 (0..151), parsed max dex {num_pokemon - 1}")

    dex_order_text = fnd.read_source(foundation, "data/pokemon/dex_order.asm")
    dex_order = parse_dex_order(dex_order_text, dex_ids)  # 190 entries, index 0 = internal id 1
    if len(dex_order) != 190:
        raise SystemExit(f"PokedexOrder: expected 190 entries, parsed {len(dex_order)}")

    header_text = fnd.read_source(foundation, "engine/pokemon/get_mon_header.asm")
    nondex_order = parse_species_array(header_text, "NonDexPokemonSpecies")  # 13, N0..N12
    if len(nondex_order) != 13:
        raise SystemExit(f"NonDexPokemonSpecies: expected 13, parsed {len(nondex_order)}")
    if nondex_order[0] != "MISSINGNO":
        raise SystemExit("NonDexPokemonSpecies[0] is not MISSINGNO")
    pic_only_block = header_text.split("NonPokemonSpecies:", 1)[1].split("NonDexPokemonSpecies:", 1)[0]
    pic_only = set(re.findall(r"db\s+(\w+),\s*\$[0-9A-Fa-f]+", pic_only_block))
    if pic_only != {"FOSSIL_KABUTOPS", "MON_GHOST", "FOSSIL_AERODACTYL"}:
        raise SystemExit(f"NonPokemonSpecies membership drifted: {sorted(pic_only)}")

    type_names = parse_type_names(fnd.read_source(foundation, "constants/type_constants.asm"))
    fnd.assert_source(foundation, "constants/type_constants.asm", "DEF SPECIAL EQU const_value")
    if type_names.get(0x11) != "TRI":
        raise SystemExit("type_constants.asm: SPECIAL boundary ($11) is not TRI -- table drifted")

    growth_rates = parse_growth_rates(fnd.read_source(foundation, "constants/pokemon_data_constants.asm"))
    if len(growth_rates) != 6:
        raise SystemExit(f"expected 6 growth rates, parsed {len(growth_rates)}")

    base_stats_text = fnd.read_source(foundation, "data/pokemon/base_stats.asm")
    include_order = parse_base_stats_include_order(base_stats_text)
    if len(include_order) != 164:
        raise SystemExit(f"base_stats.asm: expected 164 INCLUDEs (151 + 13), got {len(include_order)}")
    ordinary_files, nondex_files = include_order[:151], include_order[151:]
    expected_nondex_slugs = [n.lower() for n in nondex_order]
    got_nondex_slugs = [os.path.splitext(os.path.basename(p))[0] for p in nondex_files]
    if got_nondex_slugs != expected_nondex_slugs:
        raise SystemExit(
            f"base_stats.asm's last 13 INCLUDEs do not match NonDexPokemonSpecies order: "
            f"{got_nondex_slugs} != {expected_nondex_slugs}")

    source_records: dict[str, dict] = {}  # "BaseStats:i" / "NonDex:i" -> parsed record
    for i, rel in enumerate(ordinary_files):
        source_records[f"BaseStats:{i}"] = parse_base_stats_file(fnd.read_source(foundation, rel))
    for i, rel in enumerate(nondex_files):
        source_records[f"NonDex:{i}"] = parse_base_stats_file(fnd.read_source(foundation, rel))

    charmap_text = fnd.read_source(foundation, "constants/charmap.asm")
    glyphs, terminator = parse_charmap(charmap_text)
    monster_names_src = parse_monster_names(fnd.read_source(foundation, "data/pokemon/names.asm"))
    if len(monster_names_src) != 190:
        raise SystemExit(f"data/pokemon/names.asm: expected 190 dname entries, got {len(monster_names_src)}")

    # ROM cross-check across all three titles.
    titles = list(fnd.foundation(foundation)["titles"])
    rom_records: dict[str, dict[str, dict]] = {}
    rom_names: dict[str, list[str]] = {}
    for title in titles:
        syms = fnd.parse_sym(fnd.sym_path(foundation, title))
        rom = fnd.rom_path(foundation, title).read_bytes()
        base_flat = fnd.flat(*syms["BaseStats"])
        nondex_flat = fnd.flat(*syms["NonDexMonsBaseStats"])
        names_flat = fnd.flat(*syms["MonsterNames"])
        recs: dict[str, dict] = {}
        for i in range(151):
            recs[f"BaseStats:{i}"] = _unpack_record(rom[base_flat + i * BASE_DATA_SIZE:base_flat + (i + 1) * BASE_DATA_SIZE])
        for i in range(13):
            recs[f"NonDex:{i}"] = _unpack_record(rom[nondex_flat + i * BASE_DATA_SIZE:nondex_flat + (i + 1) * BASE_DATA_SIZE])
        rom_records[title] = recs
        names = []
        for i in range(190):
            raw = rom[names_flat + i * 10:names_flat + (i + 1) * 10]
            names.append(decode_name(raw, glyphs, terminator))
        rom_names[title] = names

    for key, src in source_records.items():
        expected_dex = dex_ids[src["dex_const"]]
        expected_t1, expected_t2 = type_names_id(type_names, src["type1"]), type_names_id(type_names, src["type2"])
        expected_growth = growth_rates.index(src["growth_rate"])
        for title in titles:
            rec = rom_records[title][key]
            if key.startswith("BaseStats:") and rec["dex"] != expected_dex:
                disagreements.append(f"{title}:{key} dex ROM={rec['dex']} source={expected_dex}")
            if (rec["stats"] != src["stats"] or rec["type1"] != expected_t1 or rec["type2"] != expected_t2
                    or rec["catch_rate"] != src["catch_rate"] or rec["base_exp"] != src["base_exp"]
                    or rec["growth"] != expected_growth):
                disagreements.append(
                    f"{title}:{key} ROM={rec} != source stats={src['stats']} types=({expected_t1},{expected_t2}) "
                    f"catch={src['catch_rate']} exp={src['base_exp']} growth={expected_growth}")

    for title in titles:
        for i in range(190):
            if rom_names[title][i] != monster_names_src[i]:
                disagreements.append(
                    f"{title}:name[{i + 1}] ROM={rom_names[title][i]!r} source={monster_names_src[i]!r}")

    if disagreements:
        raise SystemExit("ROM/source disagreements found:\n" + "\n".join(disagreements))

    # classification + assembly.
    nondex_by_id = {name_to_id[n]: i for i, n in enumerate(nondex_order)}
    pic_only_ids = {name_to_id[n] for n in pic_only}
    missingno_id = name_to_id["MISSINGNO"]

    def classify(internal_id: int, name: str | None) -> str:
        if name is None:
            return "unused"
        if internal_id == missingno_id:
            return "missingno"
        if internal_id in nondex_by_id:
            return "spirit" if name.startswith("SPIRIT_") else "form"
        if internal_id in pic_only_ids:
            return "picture_only"
        return "ordinary"

    classifications = {i: classify(i, names_by_id[i]) for i in range(1, 191)}

    # base_species: for an ordinary id, itself; for a form/spirit, the lowest internal
    # id classified "ordinary" that shares its PokedexOrder dex value (this is exactly
    # the game's own `PokedexToIndex` first-match rule, S3.3).
    ordinary_by_dex: dict[int, int] = {}
    for i in range(1, 191):
        if classifications[i] == "ordinary":
            ordinary_by_dex.setdefault(dex_order[i - 1], i)

    species: dict[int, dict] = {}
    species_types: dict[int, list[int]] = {}
    for i in range(1, 191):
        name = monster_names_src[i - 1]
        cls = classifications[i]
        dex = dex_order[i - 1]
        if cls == "ordinary":
            base_species = i
            stats_source = f"BaseStats:{dex - 1}"
        elif cls in ("form", "spirit", "missingno"):
            base_species = ordinary_by_dex.get(dex) if cls != "missingno" else None
            stats_source = f"NonDex:{nondex_by_id[i]}"
        else:
            base_species = None
            stats_source = None

        entry: dict = {
            "dex": dex, "name": name, "classification": cls,
            "base_species": base_species,
        }
        if stats_source:
            rec = source_records[stats_source]
            types = [type_names_id(type_names, rec["type1"]), type_names_id(type_names, rec["type2"])]
            entry.update({
                "types": types,
                "stats": dict(zip(("hp", "atk", "def", "spd", "spc"), rec["stats"], strict=True)),
                "catch_rate": rec["catch_rate"], "base_exp": rec["base_exp"],
                "growth_rate": rec["growth_rate"],
                "stats_source": stats_source,
                "obtainable": cls in ("ordinary", "form", "missingno"),
            })
            species_types[i] = types
        else:
            entry.update({
                "types": None, "stats": None, "catch_rate": None, "base_exp": None,
                "growth_rate": None, "stats_source": None, "obtainable": False,
            })
        species[i] = entry

    transform_edges = []
    scripts_dir_cache: dict[str, str] = {}
    for from_name, to_name, script, bidirectional in _TRANSFORM_EDGES:
        rel = f"scripts/{script}.asm"
        text = scripts_dir_cache.setdefault(rel, fnd.read_source(foundation, rel))
        if "ChangePartyPokemonSpecies" not in text or to_name not in text:
            raise SystemExit(f"transform edge {from_name}->{to_name}: {rel} no longer matches")
        transform_edges.append({
            "from": name_to_id[from_name], "to": name_to_id[to_name],
            "site": script, "trigger": "script", "bidirectional": bidirectional,
        })

    species_index = {
        "_comment": f"Gen 1 internal species index -> attributes, generated for {foundation} "
                    "(docs/purergb/PLAN.md S3.3/S11.2 A13).",
        "generator": "tools/gen_gen1_species.py",
        "index_to_national": {str(i): species[i]["dex"] for i in range(1, 191) if species[i]["dex"]},
        "national_to_index": {str(d): idx for d, idx in sorted(ordinary_by_dex.items())},
        "species": {str(i): species[i] for i in range(1, 191)},
        "transform_edges": transform_edges,
    }
    types_doc = {
        "type_names": {str(k): _type_display_name(v) for k, v in sorted(type_names.items())},
        "species_types": {str(i): t for i, t in sorted(species_types.items())},
        "default_typings": True,
    }
    return species_index, types_doc, disagreements


def _type_display_name(const_name: str) -> str:
    """`BONEMERANG_TYPE` -> `Bonemerang`, `PSYCHIC_TYPE` -> `Psychic`, `TRI` -> `Tri`."""
    base = const_name[:-len("_TYPE")] if const_name.endswith("_TYPE") else const_name
    return base.replace("_", " ").title()


def type_names_id(type_names: dict[int, str], const_name: str) -> int:
    alias = const_name.replace("_TYPE", "") if const_name.endswith("_TYPE") and const_name != "PSYCHIC_TYPE" else const_name
    for tid, name in type_names.items():
        if name in (const_name, alias):
            return tid
    raise SystemExit(f"unknown type constant {const_name!r}")


def main() -> int:
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--foundation", default="purergb")
    args = p.parse_args()
    if args.foundation != "purergb":
        raise SystemExit("gen_gen1_species.py only implements the purergb foundation "
                          "(vanilla species_index.json is hand-curated, B3)")

    species_index, types_doc, _ = build(args.foundation)
    out_dir = fnd.data_dir(args.foundation)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "species_index.json").write_text(json.dumps(species_index, indent=1) + "\n", encoding="utf-8")
    (out_dir / "types.json").write_text(json.dumps(types_doc, indent=1) + "\n", encoding="utf-8")

    n_ordinary = sum(1 for s in species_index["species"].values() if s["classification"] == "ordinary")
    n_by_cls: dict[str, int] = {}
    for s in species_index["species"].values():
        n_by_cls[s["classification"]] = n_by_cls.get(s["classification"], 0) + 1
    print(f"[gen1-species:{args.foundation}] 190 ids, {n_ordinary} ordinary, "
          f"classification counts={n_by_cls}, {len(species_index['transform_edges'])} transform edges "
          f"-> {out_dir / 'species_index.json'}, {out_dir / 'types.json'}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
