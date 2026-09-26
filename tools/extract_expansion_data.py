"""Extract Gen 3 data from GF/RHH headers and an explicit, ROM-bound layout.

Vanilla CONTROL:
  python tools/extract_expansion_data.py --rom emerald.gba --check --output .cache/control.json
Expansion:
  python tools/extract_expansion_data.py --rom build.gba --layout build-layout.json --output pack.json

Layout schema 1 is plain JSON (see vanilla_layout() for a complete example).
Each table has a stride, fields, and name descriptor. Numeric fields specify
offset/width and optionally count, shift, bits, signed. Names specify offset,
length and optionally pointer=true; an external name table uses header/stride.
Expansion must supply species.national_dex and evolution_pointer fields, plus
evolutions stride/fields/end_method/ignored_methods. No expansion ABI defaults
are guessed. The later build probe supplies these, including enum widths and
bitfield positions. rom_sha1 binds the layout to exactly one ROM; provenance
records source/compiler/config evidence, rather than certifying that evidence.

The vanilla GF header does NOT expose dex/evolution addresses: those two come
from the pinned symbol artifact and are disclosed in the output provenance.
This is SOURCE/ROM evidence only, never a runtime or release qualification.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import operator
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRET_COMMIT = "c65e93f20a5275ab03b07d6f6411096a82a60ffd"
VANILLA_SHA1 = "f3ae088181bf583e55daf962a92bb46f4f1d07b7"
ROM_BASE = 0x08000000
# pret and expansion src/rom_header_gf.c:18-105: stable public ARM ABI.
GF_POINTERS = {
    "species_names": 0x44, "move_names": 0x48, "species": 0xBC,
    "abilities": 0xC0, "items": 0xC8, "moves": 0xCC,
}
STAT_FIELDS = ("baseHP", "baseAttack", "baseDefense", "baseSpeed", "baseSpAttack", "baseSpDefense")


class ExtractionError(ValueError):
    """A present input is unsupported, malformed, or does not match its pin."""


def require(condition, reason):
    if not condition:
        raise ExtractionError(reason)


class Rom:
    def __init__(self, data: bytes):
        self.data = data

    def read(self, offset, size):
        require(isinstance(offset, int) and isinstance(size, int) and size >= 0
                and 0 <= offset <= len(self.data) - size, f"ROM range outside file: {offset!r}+{size!r}")
        return self.data[offset:offset + size]

    def address(self, pointer, size=1):
        require(ROM_BASE <= pointer < ROM_BASE + 0x2000000, f"not a ROM pointer: {pointer:#x}")
        offset = pointer - ROM_BASE
        self.read(offset, size)
        return offset

    def uint(self, offset, width):
        return int.from_bytes(self.read(offset, width), "little")


def parse_headers(rom):
    rom.read(0x100, 0x104)
    gf = {"version": rom.uint(0x100, 4), "language": rom.uint(0x104, 4),
          "game_name": rom.read(0x108, 32).split(b"\0", 1)[0].decode("ascii", errors="strict")}
    gf.update({key: rom.uint(0x100 + offset, 4) for key, offset in GF_POINTERS.items()})
    # Only English Emerald is admitted by this extractor's built-in charmap.
    require(gf["version"] == 3 and gf["language"] == 2, "unsupported GF version/language (English Emerald required)")
    for key in ("species", "moves", "items"):
        rom.address(gf[key])
    matches = [i for i in range(0x100, min(0x400, len(rom.data)) - 5)
               if rom.read(i, 6) == b"RHHEXP"]
    require(len(matches) <= 1, "ambiguous RHH magic in header window")
    if not matches:
        return gf, None
    offset = matches[0]
    # expansion e8bd1cd7 src/rom_header_rhh.c:14-28, explicitly annotated offsets.
    require(offset + 24 <= 0x400, "truncated RHH header window")
    rhh = {"offset": offset, "version": list(rom.read(offset + 6, 3)),
           "flags": rom.uint(offset + 9, 1), "moves": rom.uint(offset + 10, 2),
           "species": rom.uint(offset + 12, 2), "abilities": rom.uint(offset + 14, 2),
           "abilities_pointer": rom.uint(offset + 16, 4), "items": rom.uint(offset + 20, 2),
           "item_name_length": rom.uint(offset + 22, 1)}
    require(rhh["version"] == [1, 17, 0], "unsupported RHH version; validate its ABI before admission")
    require(all(rhh[k] > 0 for k in ("moves", "species", "abilities", "items", "item_name_length")), "zero RHH count/length")
    rom.address(rhh["abilities_pointer"])
    return gf, rhh


def charmap(source):
    """Read only the Latin section; preserve symbolic glyphs as {TOKEN}."""
    result = {}
    for line in (source / "charmap.txt").read_text(encoding="utf-8").split("@ Hiragana", 1)[0].splitlines():
        match = re.fullmatch(r"(.+?)\s*=\s*((?:[0-9A-F]{2} ?)+)\s*", line)
        if match:
            key, value = match.groups()
            key = key.strip()
            key = key[1:-1].replace("\\'", "'") if key.startswith("'") else "{" + key + "}"
            result[bytes.fromhex(value)] = key
    return result


def decode_name(data, chars):
    require(255 in data, "name lacks EOS within declared length")
    data = data[:data.index(255)]
    tokens = sorted(chars, key=len, reverse=True)
    result = []
    while data:
        token = next((token for token in tokens if data.startswith(token)), None)
        require(token is not None, f"name has an unknown/control glyph: {data.hex()}")
        result.append(chars[token])
        data = data[len(token):]
    return "".join(result)


def number(rom, base, field, extent):
    offset, width = field["offset"], field["width"]
    count = field.get("count", 1)
    shift = field.get("shift", 0)
    bits = field.get("bits", width * 8)
    require(width in (1, 2, 4) and isinstance(count, int) and count > 0
            and offset >= 0 and offset + width * count <= extent
            and shift >= 0 and 0 < bits <= width * 8 - shift, "invalid numeric layout field")
    values = []
    for i in range(count):
        value = (rom.uint(base + offset + width * i, width) >> shift) & ((1 << bits) - 1)
        if field.get("signed") and value & (1 << (bits - 1)):
            value -= 1 << bits
        values.append(value)
    return values if "count" in field else values[0]


def read_name(rom, base, spec, extent, chars, gf, index):
    offset, length = spec.get("offset", 0), spec["length"]
    require(isinstance(length, int) and 0 < length <= 256, "invalid name length")
    if "header" in spec:
        stride = spec["stride"]
        require(offset >= 0 and offset + length <= stride, "external name outside stride")
        location = rom.address(gf[spec["header"]]) + stride * index + offset
    elif spec.get("pointer"):
        require(offset >= 0 and offset + 4 <= extent, "name pointer outside record")
        location = rom.address(rom.uint(base + offset, 4))
    else:
        require(offset >= 0 and offset + length <= extent, "inline name outside record")
        location = base + offset
    # Pointer strings may end before the maximum length at the end of the ROM.
    return decode_name(rom.read(location, min(length, len(rom.data) - location)), chars)


def families(species, ignored_methods=()):
    """Connected evolution components; root = lowest unevolved ID in component.

    This preserves baby roots (e.g. Pichu=172), unlike minimum-member union-find.
    For a rootless cycle use its minimum ID; raw edges remain available to audit.
    """
    parents = list(range(len(species)))
    incoming = set()

    def root(n):
        while parents[n] != n:
            parents[n] = parents[parents[n]]
            n = parents[n]
        return n

    for row in species:
        for edge in row["evolutions"]:
            target = edge["target"]
            require(0 < target < len(species), f"invalid evolution target {target}")
            if edge["method"] not in ignored_methods:
                incoming.add(target)
                parents[root(target)] = root(row["id"])
    groups = {}
    for i in range(len(species)):
        groups.setdefault(root(i), []).append(i)
    for members in groups.values():
        canonical = min(set(members) - incoming or members)
        for i in members:
            species[i]["family"] = canonical


def extract(data, layout, chars):
    rom = Rom(data)
    require(layout["schema"] == 1, "unsupported layout schema")
    digest = hashlib.sha1(data).hexdigest()
    require(digest == layout["rom_sha1"], "ROM sha1 does not match layout")
    require(bool(layout["provenance"]), "layout provenance is required")
    gf, rhh = parse_headers(rom)
    kind = "expansion" if rhh else "vanilla"
    require(layout["kind"] == kind, "layout/header kind mismatch")
    counts = {k: rhh[k] if rhh else layout["counts"][k] for k in ("species", "moves", "items", "abilities")}
    result = {"schema": 1, "kind": kind, "rom_sha1": digest, "gf_header": gf, "rhh_header": rhh,
              "counts": counts, "layout": layout}
    for table, count in counts.items():
        spec = layout["tables"][table]
        required = {"species": {*STAT_FIELDS, "types", "abilities"},
                    "moves": {"power", "type", "accuracy", "pp"}, "items": set(), "abilities": set()}[table]
        require(required <= spec["fields"].keys(), f"missing required {table} fields")
        if rhh and table == "items":
            # src/data/items.h:17 and include/metaprogram.h:34 bound sizeof
            # COMPOUND_STRING, including EOS, by ITEM_NAME_LENGTH.
            require(spec["name"]["length"] == rhh["item_name_length"],
                    "item name bound must match RHH itemNameLength")
        stride = spec["stride"]
        require(isinstance(stride, int) and stride > 0 and 0 < count <= 65535, "invalid table geometry")
        pointer = rhh["abilities_pointer"] if rhh and table == "abilities" else gf[table]
        base = rom.address(pointer, stride * count)
        rows = []
        for i in range(count):
            pos = base + i * stride
            row = {"id": i, "name": read_name(rom, pos, spec["name"], stride, chars, gf, i)}
            row.update({key: number(rom, pos, value, stride) for key, value in spec["fields"].items()})
            rows.append(row)
        result[table] = rows
    evo = layout["evolutions"]
    for row in result["species"]:
        row["evolutions"] = []
        if rhh:
            require("national_dex" in row and "evolution_pointer" in row, "expansion species needs dex and evolution pointer fields")
            pointer = row.pop("evolution_pointer")
            if not pointer:
                continue
            pos = rom.address(pointer)
            slots = evo["max_entries"]  # Hard bound; reaching it without EOS is a failure.
        else:
            dex = layout["national_dex"]
            row["national_dex"] = (rom.uint(rom.address(dex["address"]) + (row["id"] - 1) * 2, 2)
                                   if row["id"] else 0)
            pos = rom.address(evo["address"]) + row["id"] * evo["slots"] * evo["stride"]
            slots = evo["slots"]
        terminated = False
        for slot in range(slots):
            edge = {key: number(rom, pos + slot * evo["stride"], field, evo["stride"])
                    for key, field in evo["fields"].items()}
            if edge["method"] == evo["end_method"]:
                terminated = True
                if rhh:
                    break
                continue
            row["evolutions"].append(edge)
        require(not rhh or terminated, f"unterminated evolution list for species {row['id']}")
    families(result["species"], evo["ignored_methods"])
    for row in result["species"]:
        require(all(0 <= ability < counts["abilities"] for ability in row["abilities"]), "species ability outside table")
    return result


def clean_source(source):
    """Presence is handled by caller; a present but wrong/dirty cache must fail."""
    commit = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    require(commit == PRET_COMMIT, f"pokeemerald wrong commit: {commit}")
    dirty = subprocess.check_output(["git", "-C", str(source), "status", "--porcelain", "--untracked-files=no"], text=True)
    require(not dirty, "pokeemerald tracked source is dirty")


def strip_comments(text):
    return re.sub(r"/\*.*?\*/|//[^\n]*", "", text, flags=re.S)


class Constants:
    """Small, fail-closed integer expression reader; never eval C or Python."""
    def __init__(self, source):
        self.raw = {}
        for path in sorted((source / "include").glob("*.h")) + sorted((source / "include/constants").glob("*.h")):
            text = strip_comments(path.read_text(encoding="utf-8"))
            for name, value in re.findall(r"^#define\s+(\w+)[ \t]+([^\n]+)", text, re.M):
                self.raw[name] = value.strip()
        text = strip_comments((source / "include/constants/pokedex.h").read_text(encoding="utf-8"))
        for body in re.findall(r"enum\s*\{(.*?)\}", text, re.S):
            last = -1
            for entry in body.split(","):
                if not entry.strip():
                    continue
                parts = entry.strip().split("=", 1)
                last = self.value(parts[1]) if len(parts) == 2 else last + 1
                self.raw[parts[0].strip()] = str(last)
        # include/item.h:87-96 expands these macro lists into sequential aliases.
        tmhm = (source / "include/constants/tms_hms.h").read_text(encoding="utf-8")
        for kind in ("TM", "HM"):
            block = tmhm.split(f"#define FOREACH_{kind}(F)", 1)[1].split("#define", 1)[0]
            for i, name in enumerate(re.findall(r"F\((\w+)\)", block)):
                self.raw[f"ITEM_{kind}_{name}"] = str(self.value(f"ITEM_{kind}01") + i)

    def value(self, expr):
        ops = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
               ast.LShift: operator.lshift, ast.RShift: operator.rshift, ast.BitOr: operator.or_,
               ast.BitAnd: operator.and_}

        def walk(node, seen):
            if isinstance(node, ast.Constant) and type(node.value) is int:
                return node.value
            if isinstance(node, ast.Name):
                require(node.id not in seen and node.id in self.raw, f"unknown/cyclic constant {node.id}")
                return walk(ast.parse(self.raw[node.id], mode="eval").body, seen | {node.id})
            if isinstance(node, ast.BinOp) and type(node.op) in ops:
                return ops[type(node.op)](walk(node.left, seen), walk(node.right, seen))
            if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
                return -walk(node.operand, seen)
            raise ExtractionError(f"unsupported constant expression: {expr}")

        return walk(ast.parse(expr.strip(), mode="eval").body, set())


def field(offset, width=1, **kwargs):
    return {"offset": offset, "width": width, **kwargs}


def vanilla_layout(source, symbols):
    clean_source(source)
    c = Constants(source)
    syms = {name: (int(address, 16), int(size, 16)) for address, size, name in
            re.findall(r"^([0-9a-f]+)\s+\w\s+([0-9a-f]+)\s+(\w+)$", symbols.read_text(), re.M)}
    counts = {key: c.value(value) for key, value in {"species": "NUM_SPECIES", "moves": "MOVES_COUNT",
              "items": "ITEMS_COUNT", "abilities": "ABILITIES_COUNT"}.items()}
    # pret include/pokemon.h:297-338,355-360; include/item.h:10-26.
    # agbcc ARM struct alignment is 4; symbol table sizes independently check strides.
    tables = {
        "species": {"stride": 28, "name": {"header": "species_names", "stride": c.value("POKEMON_NAME_LENGTH") + 1,
                    "length": c.value("POKEMON_NAME_LENGTH") + 1},
                    "fields": {**{key: field(i) for i, key in enumerate(STAT_FIELDS)},
                               "types": field(6, count=2), "abilities": field(22, count=2)}},
        "moves": {"stride": 12, "name": {"header": "move_names", "stride": c.value("MOVE_NAME_LENGTH") + 1,
                  "length": c.value("MOVE_NAME_LENGTH") + 1},
                  "fields": {key: field(i, signed=key == "priority") for i, key in enumerate(
                      ("effect", "power", "type", "accuracy", "pp", "secondaryEffectChance", "target", "priority", "flags"))}},
        "items": {"stride": 44, "name": {"offset": 0, "length": c.value("ITEM_NAME_LENGTH")},
                  "fields": {"itemId": field(14, 2), "price": field(16, 2), "holdEffect": field(18),
                             "holdEffectParam": field(19), "pocket": field(26)}},
        "abilities": {"stride": c.value("ABILITY_NAME_LENGTH") + 1,
                      "name": {"offset": 0, "length": c.value("ABILITY_NAME_LENGTH") + 1}, "fields": {}},
    }
    for table, symbol in {"species": "gSpeciesInfo", "moves": "gBattleMoves", "items": "gItems", "abilities": "gAbilityNames"}.items():
        require(syms[symbol][1] == counts[table] * tables[table]["stride"], f"symbol size mismatch: {symbol}")
    slots = c.value("EVOS_PER_MON")
    require(syms["gEvolutionTable"][1] == counts["species"] * slots * 8, "evolution symbol size mismatch")
    require(syms["sSpeciesToNationalPokedexNum"][1] == (counts["species"] - 1) * 2, "dex symbol size mismatch")
    return {"schema": 1, "kind": "vanilla", "rom_sha1": VANILLA_SHA1,
            "provenance": {"pret_commit": PRET_COMMIT, "symbols_sha256": hashlib.sha256(symbols.read_bytes()).hexdigest(),
                           "layout_source": "include/pokemon.h:297-360; include/item.h:10-26",
                           "supplemental_symbols": ["sSpeciesToNationalPokedexNum", "gEvolutionTable"]},
            "counts": counts, "tables": tables,
            "national_dex": {"address": syms["sSpeciesToNationalPokedexNum"][0]},
            "evolutions": {"address": syms["gEvolutionTable"][0], "slots": slots, "stride": 8,
                           "fields": {"method": field(0, 2), "param": field(2, 2), "target": field(4, 2)},
                           "end_method": 0, "ignored_methods": []}}


def designated(text, prefix):
    """Split top-level designated initializers without confusing nested arrays."""
    matches = list(re.finditer(r"\[(" + prefix + r"\w+)\]\s*=", text))
    return {m[1]: text[m.end():matches[i + 1].start() if i + 1 < len(matches) else len(text)].strip().rstrip(",; \n}")
            for i, m in enumerate(matches)}


def source_name(text):
    match = re.search(r'_\("((?:\\.|[^"\\])*)"\)', text)
    require(match is not None, "source name not found")
    return match[1].replace('\\"', '"').replace("\\'", "'")


def source_control(pack, source):
    """Compare every extracted row/field with C initializers, independent of ROM offsets.

    Returns explicit mismatch rows. No mismatch is suppressed here, including
    placeholder species/items or punctuation. Source parser gaps are failures.
    """
    c = Constants(source)
    diffs = {key: [] for key in ("species_names", "species_stats", "national_dex", "evolutions", "families", "moves", "items", "abilities")}

    def check(table, index, key, actual, expected):
        if actual != expected:
            diffs[table].append({"id": index, "field": key, "rom": actual, "source": expected})

    def read(path):
        return strip_comments((source / path).read_text(encoding="utf-8"))

    names = designated(read("src/data/text/species_names.h"), "SPECIES_")
    stats_text = read("src/data/pokemon/species_info.h").replace("\\\n", "\n")
    old = stats_text.split("#define OLD_UNOWN_SPECIES_INFO", 1)[1].split("const struct", 1)[0]
    stats = designated(stats_text, "SPECIES_")
    expected_species = [{"id": i, "evolutions": []} for i in range(pack["counts"]["species"])]
    require({c.value(k) for k in names} == set(range(len(expected_species))), "incomplete source species names")
    require({c.value(k) for k in stats} == set(range(len(expected_species))), "incomplete source species stats")
    for symbol, text in names.items():
        i = c.value(symbol)
        row = pack["species"][i]
        check("species_names", i, "name", row["name"], source_name(text))
        block = stats[symbol].replace("OLD_UNOWN_SPECIES_INFO", old)
        for key in STAT_FIELDS + ("types", "abilities"):
            if i == 0:
                expected = [0, 0] if key in ("types", "abilities") else 0
            else:
                match = re.search(r"\." + key + r"\s*=\s*(\{[^}]+\}|[^,\n]+)", block)
                require(match is not None, f"source stat absent: {symbol}.{key}")
                value = match[1]
                expected = ([c.value(v) for v in value.strip("{} ").split(",") if v.strip()]
                            if value.startswith("{") else c.value(value))
            check("species_stats", i, key, row[key], expected)
    dex_text = read("src/pokemon.c").split("static const u16 sSpeciesToNationalPokedexNum", 1)[1].split("};", 1)[0]
    dex = {0: 0, **{c.value("SPECIES_" + name): c.value("NATIONAL_DEX_" + name)
                    for name in re.findall(r"SPECIES_TO_NATIONAL\((\w+)\)", dex_text)}}
    require(len(dex) == len(expected_species), "incomplete source national dex")
    for i, value in dex.items():
        check("national_dex", i, "national_dex", pack["species"][i]["national_dex"], value)
    evo_text = read("src/data/pokemon/evolution.h")
    # Each evolution is a flat {method, param, species}; preserve methods/parameters too.
    for symbol, block in designated(evo_text, "SPECIES_").items():
        i = c.value(symbol)
        edges = re.findall(r"\{\s*(EVO_\w+)\s*,\s*([^,{}]+)\s*,\s*(SPECIES_\w+)\s*", block)
        require(bool(edges), f"unparsed source evolution: {symbol}")
        expected_species[i]["evolutions"] = [{"method": c.value(m), "param": c.value(p), "target": c.value(s)} for m, p, s in edges]
    # Independent graph walk oracle (not the extractor's union-find algorithm).
    adjacency = {i: set() for i in range(len(expected_species))}
    incoming = set()
    for row in expected_species:
        for edge in row["evolutions"]:
            adjacency[row["id"]].add(edge["target"])
            adjacency[edge["target"]].add(row["id"])
            incoming.add(edge["target"])
    for row in expected_species:
        component, pending = set(), {row["id"]}
        while pending:
            current = pending.pop()
            component.add(current)
            pending.update(adjacency[current] - component)
        row["family"] = min(component - incoming or component)
    for i, expected in enumerate(expected_species):
        for key, table in (("evolutions", "evolutions"), ("family", "families")):
            check(table, i, key, pack["species"][i][key], expected[key])
    for table, prefix, path, name_path in (
        ("moves", "MOVE_", "src/data/battle_moves.h", "src/data/text/move_names.h"),
        ("items", "ITEM_", "src/data/items.h", "src/data/items.h"),
        ("abilities", "ABILITY_", "src/data/text/abilities.h", "src/data/text/abilities.h"),
    ):
        source_text = read(path)
        if table == "abilities":
            source_text = source_text.split("const u8 gAbilityNames", 1)[1].split("};", 1)[0]
        entries = designated(source_text, prefix)
        name_entries = designated(read(name_path), prefix) if table != "abilities" else entries
        require({c.value(k) for k in entries} == set(range(pack["counts"][table])), f"incomplete source {table}")
        for symbol, block in entries.items():
            i = c.value(symbol)
            row = pack[table][i]
            check(table, i, "name", row["name"], source_name(name_entries[symbol]))
            for key in row.keys() - {"id", "name"}:
                match = re.search(r"\." + key + r"\s*=\s*([^,\n]+)", block)
                expected = c.value(match[1]) if match else 0  # C zero-initializes omitted members.
                check(table, i, key, row[key], expected)
    return diffs


def server_crosscheck(pack):
    """Report, never silently correct, existing server differences.

    Server presentation comparisons ignore case/spacing/punctuation; the ROM
    and source CONTROL above retain every glyph. Invalid old-Unown slots and
    SPECIES_NONE are explicitly excluded from the server's playable projection.
    """
    from server import pokemon_data as pd
    from server.adapters.gen3_frlge import Gen3Adapter
    from server.data.items.gen3_vanilla import ITEM_NAMES
    from server.data.moves.gen3_vanilla import MOVE_DATA, MOVE_NAMES

    def display(value):
        return "".join(c for c in value.casefold() if c.isalnum() or c in "♀♂")

    report = {key: [] for key in ("species_names", "types", "national_dex", "families", "abilities", "moves", "items", "items_missing",
                                  "emerald_moves", "emerald_overlay_items")}
    emerald = Gen3Adapter(is_rr=False, rom_type="emerald")
    for row in pack["species"]:
        i, dex = row["id"], row["national_dex"]
        if i == 0 or 252 <= i <= 276:
            continue
        for key, actual, expected in (
            ("species_names", display(row["name"]), display(pd.species_name(i))),
            ("types", tuple(row["types"]), pd.species_types(i)),
            ("national_dex", dex, pd.to_national(i)),
            ("families", row["family"], pd.EVO_FAMILY.get(i, i)),
        ):
            if actual != expected:
                report[key].append({"id": i, "rom": actual, "server": expected})
    for row in pack["abilities"][1:]:
        expected = pd.ability_name(row["id"])
        if display(row["name"]) != display(expected):
            report["abilities"].append({"id": row["id"], "rom": row["name"], "server": expected})
    for row in pack["moves"][1:]:
        expected = MOVE_DATA.get(row["id"], {})
        for key in ("power", "type", "accuracy", "pp"):
            if row[key] != expected.get(key):
                report["moves"].append({"id": row["id"], "field": key, "rom": row[key], "server": expected.get(key)})
        if display(row["name"]) != display(MOVE_NAMES.get(row["id"], "")):
            report["moves"].append({"id": row["id"], "field": "name", "rom": row["name"], "server": MOVE_NAMES.get(row["id"])})
        effective = emerald.move_data(row["id"])
        for key in ("power", "type", "accuracy", "pp"):
            actual = effective["type_id" if key == "type" else key]
            if row[key] != actual:
                report["emerald_moves"].append({"id": row["id"], "field": key, "rom": row[key], "server": actual})
    for row in pack["items"]:
        expected = ITEM_NAMES.get(row["id"])
        if expected is None:
            report["items_missing"].append({"id": row["id"], "rom": row["name"]})
        elif display(row["name"]) != display(expected):
            report["items"].append({"id": row["id"], "rom": row["name"], "server": expected})
        if row["id"] in (375, 376) and display(row["name"]) != display(emerald.item_name(row["id"])):
            report["emerald_overlay_items"].append({"id": row["id"], "rom": row["name"], "server": emerald.item_name(row["id"])})
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--source", type=Path, default=ROOT / ".cache/pret/pokeemerald", help="matching source tree (also supplies charmap)")
    parser.add_argument("--symbols", type=Path, default=ROOT / "data/gen3/pret/pokeemerald.sym")
    parser.add_argument("--layout", type=Path, help="ROM-bound layout JSON, required for expansion")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--check", action="store_true", help="vanilla source CONTROL + server cross-check; fails any source difference")
    args = parser.parse_args()
    layout = json.loads(args.layout.read_text()) if args.layout else vanilla_layout(args.source, args.symbols)
    pack = extract(args.rom.read_bytes(), layout, charmap(args.source))
    if args.check:
        require(pack["kind"] == "vanilla", "--check is the vanilla CONTROL; expansion needs a build-specific oracle")
        clean_source(args.source)
        pack["control"] = source_control(pack, args.source)
        pack["server_crosscheck"] = server_crosscheck(pack)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(pack, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if args.check:
        print(json.dumps({"control_differences": {k: len(v) for k, v in pack["control"].items()},
                          "server_differences": {k: len(v) for k, v in pack["server_crosscheck"].items()}}, indent=2))
        require(not any(pack["control"].values()), "vanilla CONTROL differs from pret; see output")
    else:
        print(json.dumps({"rom_sha1": pack["rom_sha1"], "counts": pack["counts"]}))


if __name__ == "__main__":
    # Direct tool invocation must resolve this checkout's server for --check.
    import sys

    sys.path.insert(0, str(ROOT))
    main()
