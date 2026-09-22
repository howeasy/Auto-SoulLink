#!/usr/bin/env python3
"""Generate pinned G/S/C encounter tables without collapsing map rows.

ASM is parsed independently of both ROM scanners. Every encoded source table
is compared with the verified title ROM. Slots remain ordered and unaggregated;
fishing species zero remains its source-defined time-group reference.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))

from tools.gen_gen2_area_map import (  # noqa: E402
    build_area_map,
    constants,
    integer,
    rom_bytes,
    run_generator,
    source_lines,
)


def byte(value):
    if not isinstance(value, int) or not 0 <= value <= 255:
        raise ValueError(f"byte out of bounds: {value}")
    return value


def level(value):
    if not 1 <= value <= 100:
        raise ValueError(f"level out of bounds: {value}")
    return value


def threshold(token):
    match = re.fullmatch(r"([0-9]+) percent(?:\s*\+\s*([0-9]+))?", token.strip())
    if not match or not 0 <= int(match[1]) <= 100:
        raise ValueError(f"unsupported percentage: {token}")
    # macros/data.asm: percent EQUS "* $ff / 100". This is a byte threshold,
    # not an asserted encounter probability or a percentage denominator of 256.
    return byte(int(match[1]) * 255 // 100 + int(match[2] or 0))


def verify(ctx, symbol, encoded):
    expected = bytes(encoded)
    flat, actual = rom_bytes(ctx, symbol, len(expected))
    if actual != expected:
        raise ValueError(f"{symbol}: independently encoded source disagrees with ROM at {flat:#x}")


def lines(ctx, path):
    return list(source_lines(ctx.read_source(path), ctx.title))


def map_pair(name, maps):
    if name not in maps:
        raise ValueError(f"unknown map name: {name}")
    return {"map_group": maps[name]["map_group"], "map_number": maps[name]["map_number"]}


def pair_bytes(pair):
    return [byte(pair["map_group"]), byte(pair["map_number"])]


def species_id(name, species):
    if name not in species or not 1 <= species[name] <= 251:
        raise ValueError(f"unknown/non-Pokemon species: {name}")
    return species[name]


def parse_wild(ctx, path, method, maps, species):
    records, encoded, current, rates, slots = [], [], None, [], []
    table, terminated = None, False
    periods = ("morning", "day", "night") if method == "grass" else ("all",)
    slot_count = 7 if method == "grass" else 3

    def finish():
        if current is None:
            return
        if len(rates) != len(periods) or len(slots) != len(periods) * slot_count:
            raise ValueError(f"{table}/{current}: incomplete rate/slot record")
        pair = map_pair(current, maps)
        encoded.extend(pair_bytes(pair) + rates)
        for slot in slots:
            encoded.extend([slot["level"], slot["species"]])
        for index, period in enumerate(periods):
            records.append({"table": table, **pair, "time": period, "rate": rates[index],
                            "slots": slots[index * slot_count:(index + 1) * slot_count]})

    for _, line in lines(ctx, path):
        if line.endswith(":") and table is None:
            table = line.rstrip(":")
        elif match := re.fullmatch(r"(?:def_(?:grass|water)_wildmons|map_id) ([A-Z0-9_]+)", line):
            if terminated:
                raise ValueError(f"{path}: record after terminator")
            finish()
            current, rates, slots = match[1], [], []
        elif line in ("end_grass_wildmons", "end_water_wildmons"):
            if current is None:
                raise ValueError(f"{path}: unmatched record end")
            finish()
            current = None
        elif line == "db -1":
            if terminated:
                raise ValueError(f"{path}: duplicate terminator")
            finish()
            current, terminated = None, True
            encoded.append(255)
        elif line.startswith("db ") and current is not None:
            fields = [part.strip() for part in line[3:].split(",")]
            if not rates:
                rates = [threshold(part) for part in fields]
            elif len(fields) == 2:
                slots.append({"species": species_id(fields[1], species), "level": level(integer(fields[0]))})
            else:
                raise ValueError(f"{path}: malformed slot {line}")
        else:
            raise ValueError(f"{path}: unsupported wild source line {line}")
    if not table or not terminated or current is not None:
        raise ValueError(f"{path}: incomplete table")
    keys = [(row["map_group"], row["map_number"], row["time"]) for row in records]
    if len(keys) != len(set(keys)):
        raise ValueError(f"{path}: duplicate map/time")
    if not records and table != "SwarmWaterWildMons":
        raise ValueError(f"{path}: empty required table")
    verify(ctx, table, encoded)
    return records


def parse_probabilities(ctx):
    result, table, encoded = {}, None, []
    for _, line in lines(ctx, "data/wild/probabilities.asm"):
        if line.endswith(":"):
            table, encoded = line[:-1], []
            result[table] = []
        elif line.startswith("mon_prob "):
            limit, index = map(integer, line[9:].split(","))
            row = {"threshold": byte(limit), "slot_offset": byte(index * 2)}
            result[table].append(row)
            encoded.extend(row.values())
        elif line.startswith("assert_table_length "):
            rows = result[table]
            if not rows or rows[-1]["threshold"] != 100 or any(
                row["slot_offset"] != index * 2 or row["threshold"] <= (rows[index - 1]["threshold"] if index else 0)
                for index, row in enumerate(rows)
            ):
                raise ValueError("invalid wild slot probability table")
            verify(ctx, table, encoded)
        elif not line.startswith("table_width "):
            raise ValueError(f"unsupported probability line: {line}")
    if set(result) != {"GrassMonProbTable", "WaterMonProbTable"}:
        raise ValueError("missing wild slot probabilities")
    return result


def parse_tree(ctx, maps, species):
    sets = constants(ctx.read_source("constants/pokemon_data_constants.asm"), "TREEMON_SET_", ctx.title)
    tables, encoded, current = {}, [], None
    for _, line in lines(ctx, "data/wild/treemon_maps.asm"):
        if line.endswith(":"):
            current, encoded = line[:-1], []
            tables[current] = []
        elif line.startswith("treemon_map "):
            name, set_name = [part.strip() for part in line[12:].split(",")]
            if set_name not in sets:
                raise ValueError(f"unknown tree set: {set_name}")
            row = {**map_pair(name, maps), "set_id": sets[set_name]}
            tables[current].append(row)
            encoded.extend(pair_bytes(row) + [byte(row["set_id"])])
        elif line == "db -1":
            verify(ctx, current, encoded + [255])
            current = None
        else:
            raise ValueError(f"unsupported tree map line: {line}")
    if current is not None or set(tables) != {"TreeMonMaps", "RockMonMaps"}:
        raise ValueError("incomplete headbutt/rock map tables")
    source = lines(ctx, "data/wild/treemons.asm")
    pointers = []
    for _, line in source:
        if line.startswith("assert_table_length"):
            break
        if line.startswith("dw "):
            pointers.append(line[3:])
    if len(pointers) != len(sets):
        raise ValueError("tree set pointer/constant count mismatch")
    ptr_bytes = []
    result = []
    for set_id, pointer in enumerate(pointers):
        sym = ctx.symbol(pointer)
        if sym.bank != ctx.symbol("TreeMons").bank:
            raise ValueError("tree pointer crosses bank")
        ptr_bytes.extend(sym.address.to_bytes(2, "little"))
        if set_id == sets["TREEMON_SET_NONE"]:
            continue
        rock = set_id == sets["TREEMON_SET_ROCK"]
        start = next((i for i, (_, line) in enumerate(source) if line == pointer + ":"), None)
        if start is None:
            raise ValueError(f"missing tree set label: {pointer}")
        parts, encoded = [[]], []
        for _, line in source[start + 1:]:
            if line.endswith(":") and not encoded:
                continue  # legitimate aliased set labels
            if line == "db -1":
                encoded.append(255)
                if len(parts) == (1 if rock else 2):
                    break
                parts.append([])
            elif line.startswith("db "):
                weight, mon, lvl = [part.strip() for part in line[3:].split(",")]
                row = {"weight": byte(integer(weight)), "species": species_id(mon, species),
                       "level": level(integer(lvl))}
                parts[-1].append(row)
                encoded.extend(row.values())
            else:
                raise ValueError(f"{pointer}: incomplete/unsupported tree set")
        if not encoded or encoded[-1] != 255 or any(sum(r["weight"] for r in p) != 100 for p in parts):
            raise ValueError(f"{pointer}: invalid tree probabilities/terminator")
        verify(ctx, pointer, encoded)
        result.append({"set_id": set_id, "kind": "rock_smash" if rock else "headbutt",
                       "common": parts[0], "rare": [] if rock else parts[1]})
    verify(ctx, "TreeMons", ptr_bytes)
    return {"headbutt_maps": tables["TreeMonMaps"], "rock_smash_maps": tables["RockMonMaps"], "sets": result}


def parse_fishing(ctx, species):
    source = lines(ctx, "data/wild/fish.asm")
    headers, rods, times, current = [], {}, [], None
    for _, line in source:
        if line.startswith("fishgroup "):
            headers.append([part.strip() for part in line[10:].split(",")])
        elif line.startswith(".") and line.endswith(":"):
            entries = rods[current] if current in rods and not rods[current] else []
            current = line[:-1]
            rods[current] = entries  # consecutive labels alias one source table
        elif line == "TimeFishGroups:":
            current = "time"
        elif line.startswith("db "):
            fields = [part.strip() for part in line[3:].split(",")]
            if current == "time":
                if len(fields) != 4:
                    raise ValueError("malformed time fish group")
                times.append({"group_id": len(times),
                              "day": {"species": species_id(fields[0], species), "level": level(integer(fields[1]))},
                              "night": {"species": species_id(fields[2], species), "level": level(integer(fields[3]))}})
            elif current in rods:
                limit = threshold(fields[0])
                if len(fields) == 2 and fields[1].startswith("time_group "):
                    mon, lvl = 0, byte(integer(fields[1][11:]))
                elif len(fields) == 3:
                    mon, lvl = species_id(fields[1], species), level(integer(fields[2]))
                else:
                    raise ValueError("malformed fishing slot")
                rods[current].append({"threshold": limit, "species": mon, "level": lvl})
            else:
                raise ValueError("orphan fishing bytes")
        elif not (line in ('DEF time_group EQUS "0,"', "FishGroups:")
                  or line.startswith(("table_width ", "assert_table_length "))):
            raise ValueError(f"unsupported fishing source: {line}")
    fish_consts = constants(ctx.read_source("constants/map_data_constants.asm"), "FISHGROUP_", ctx.title)
    if len(headers) != len(fish_consts) - 1 or not times:
        raise ValueError("missing fishing groups")
    encoded_times = [value for row in times for part in (row["day"], row["night"]) for value in part.values()]
    verify(ctx, "TimeFishGroups", encoded_times)
    encoded_headers, result = [], []
    for index, header in enumerate(headers, 1):
        if len(header) != 4:
            raise ValueError("malformed fishing header")
        bite = threshold(header[0])
        encoded_headers.append(bite)
        group = {"group_id": index, "bite_threshold": bite}
        for method, pointer in zip(("old", "good", "super"), header[1:], strict=True):
            if pointer not in rods or not rods[pointer] or rods[pointer][-1]["threshold"] != 255:
                raise ValueError(f"missing/unterminated fishing rod table: {pointer}")
            entries = rods[pointer]
            if any(row["threshold"] <= (entries[i - 1]["threshold"] if i else 0)
                   or (row["species"] == 0 and row["level"] >= len(times)) for i, row in enumerate(entries)):
                raise ValueError(f"invalid fishing thresholds/time reference: {pointer}")
            symbol = "FishGroups" + pointer
            sym = ctx.symbol(symbol)
            if sym.bank != ctx.symbol("FishGroups").bank:
                raise ValueError("fishing pointer crosses bank")
            encoded_headers.extend(sym.address.to_bytes(2, "little"))
            verify(ctx, symbol, [value for row in entries for value in row.values()])
            group[method] = entries
        result.append(group)
    verify(ctx, "FishGroups", encoded_headers)
    return {"groups": result, "time_groups": times}


def parse_roamers(ctx, maps, species):
    graph, encoded = [], []
    ended = False
    for _, line in lines(ctx, "data/wild/roammon_maps.asm"):
        if line.startswith("roam_map "):
            if ended:
                raise ValueError("roamer map after terminator")
            names = [part.strip() for part in line[9:].split(",")]
            origin = map_pair(names[0], maps)
            destinations = [map_pair(name, maps) for name in names[1:]]
            if not destinations:
                raise ValueError("empty roamer adjacency")
            graph.append({**origin, "destinations": destinations})
            encoded.extend(pair_bytes(origin) + [byte(len(destinations))])
            encoded.extend(value for pair in destinations for value in pair_bytes(pair))
            encoded.append(0)
        elif line == "db -1":
            encoded.append(255)
            ended = True
    if not ended or not graph:
        raise ValueError("incomplete roamer map table")
    verify(ctx, "RoamMaps", encoded)
    source = lines(ctx, "engine/overworld/wildmons.asm")
    start = next((i for i, (_, line) in enumerate(source) if line == "InitRoamMons:"), None)
    if start is None:
        raise ValueError("missing InitRoamMons source label")
    initial, encoded, value = {}, [], None
    field_names = {"Species": "species", "Level": "level", "MapGroup": "map_group", "MapNumber": "map_number"}
    for _, line in source[start + 1:]:
        if line.startswith("ld a, "):
            token = line[6:]
            if token.startswith("GROUP_"):
                value = map_pair(token[6:], maps)["map_group"]
            elif token.startswith("MAP_"):
                value = map_pair(token[4:], maps)["map_number"]
            elif token in species:
                value = species_id(token, species)
            else:
                value = byte(integer(token))
            encoded.extend([0x3e, value])
        elif match := re.fullmatch(r"ld \[(wRoamMon([1-3])(Species|Level|MapGroup|MapNumber|HP))\], a", line):
            if value is None:
                raise ValueError("roamer store before value")
            address = ctx.symbol(match[1]).address
            encoded.extend([0xea, address & 255, address >> 8])
            if match[3] != "HP":
                initial.setdefault(int(match[2]), {})[field_names[match[3]]] = value
        elif line == "xor a":
            value = 0
            encoded.append(0xaf)
        elif line == "ret":
            encoded.append(0xc9)
            break
        else:
            raise ValueError(f"unsupported roamer initialization: {line}")
    if not initial or encoded[-1] != 0xc9 or any(set(row) != set(field_names.values()) for row in initial.values()):
        raise ValueError("incomplete roamer initialization")
    verify(ctx, "InitRoamMons", encoded)
    return {"initial": [initial[key] for key in sorted(initial)], "maps": graph}


def parse_contest(ctx, species):
    slots, fallback, encoded = [], None, []
    for _, line in lines(ctx, "data/wild/bug_contest_mons.asm"):
        if line == "ContestMons:":
            continue
        if not line.startswith("db ") or fallback is not None:
            raise ValueError("unsupported/trailing contest source")
        weight, mon, lo, hi = [part.strip() for part in line[3:].split(",")]
        weight, low, high = integer(weight), level(integer(lo)), level(integer(hi))
        if low > high:
            raise ValueError("reversed contest levels")
        row = {"weight": weight, "species": species_id(mon, species), "min_level": low, "max_level": high}
        encoded.extend([255 if weight == -1 else byte(weight), row["species"], low, high])
        if weight == -1:
            fallback = row
        else:
            slots.append(row)
    if fallback is None or sum(row["weight"] for row in slots) != 100:
        raise ValueError("incomplete contest table")
    verify(ctx, "ContestMons", encoded)
    return {"area_id": "national_park_contest", "slots": slots, "fallback": fallback}


def build_source_tables(ctx, area_map=None):
    if 'DEF percent EQUS "* $ff / 100"' not in ctx.read_source("macros/data.asm"):
        raise ValueError("unsupported percentage encoding")
    area_map = build_area_map(ctx) if area_map is None else area_map
    maps = {row["map_const"]: row for row in area_map.values()}
    pokemon_source = ctx.read_source("constants/pokemon_constants.asm").split("DEF NUM_POKEMON", 1)[0]
    species = constants(pokemon_source, "", ctx.title)
    if len(species) != 251 or set(species.values()) != set(range(1, 252)):
        raise ValueError("source species index is not exactly 1..251")
    wild = {}
    for method in ("grass", "water"):
        wild[method] = [record for region in ("johto", "kanto", "swarm")
                        for record in parse_wild(ctx, f"data/wild/{region}_{method}.asm", method, maps, species)]
    probabilities = parse_probabilities(ctx)
    wild["grass_probabilities"] = probabilities["GrassMonProbTable"]
    wild["water_probabilities"] = probabilities["WaterMonProbTable"]
    return {"wild": wild, "tree": parse_tree(ctx, maps, species),
            "fishing": parse_fishing(ctx, species), "roamers": parse_roamers(ctx, maps, species),
            "contest": parse_contest(ctx, species)}


def build_encounters(ctx):
    areas = build_area_map(ctx)
    tables = build_source_tables(ctx, areas)
    return {"schema": "gen2-encounter-tables-v1", "generator": "tools/gen_gen2_encounters.py",
            "source": ctx.source_record(), "title": ctx.title, **tables,
            "map_areas": {key: row["area_id"] for key, row in areas.items()},
            "policy": {"ordinary_area": "shared_across_times_and_methods",
                       "contest_area": "national_park_contest", "roamer_area": "legend_<species>",
                       "roamer_consumes_ordinary_area": False, "egg_hatch_area": "gift_daycare",
                       "acquisition_events": "NOT_ESTABLISHED_BY_TABLES"},
            "inventory": {"complete": ["map_headers", "map_fishing_groups", "grass", "water",
                                        "grass_swarms", "water_swarms", "headbutt_slots", "rock_smash_slots",
                                        "fishing", "time_fishing", "roamer_initialization_and_map_graph", "contest"],
                          "open": ["unown_form_unlocks:data/wild/unlocked_unowns.asm",
                                   "flee_rules:data/wild/flee_mons.asm",
                                   "runtime_encounter_selection_and_acquisition_qualification"]
                          + (["headbutt_sleep_status:data/wild/treemons_asleep.asm"]
                             if ctx.title == "crystal" else [])}}


def main(argv=None):
    return run_generator(argv, "encounter_tables.json", build_encounters)


if __name__ == "__main__":
    raise SystemExit(main())
