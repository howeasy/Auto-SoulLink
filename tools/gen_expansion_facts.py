"""Compile expansion_offsets.c with the reference build's Makefile pipeline.

Run on the build host, with its clean source tree and original build receipt:
  python3 gen_expansion_facts.py --source SOURCE --artifacts OUTPUT \
      --probe expansion_offsets.c --work-dir SCRATCH --output PACK_DIR

Outputs layout.json (extract_expansion_data schema 1) and facts.json. Scratch
retains the object, preprocessed input, assembly, and Makefile flag query.
No ROM is copied/published and no target program is executed. --object skips
compilation for offline verification, but requires the matching compile.json.
All offsets/widths/masks/counts originate in compiler-emitted ELF data. Symbols
and ROM headers independently check sizes, addresses, and critical anchors.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import struct
import subprocess
from pathlib import Path

try:
    from tools import extract_expansion_data as ex
except ModuleNotFoundError:
    import extract_expansion_data as ex

PIN = "e8bd1cd7b03fc032ea37e3ecd38b379b5d01a1e7"
FLAG_NAMES = ("CPP", "CPPFLAGS", "PREPROC", "ASSETS_DIR_NAME", "CC1", "CFLAGS", "AS", "ASFLAGS")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def source_sha(path):
    """Hash source as UTF-8/LF so Git's CRLF checkout policy cannot change pins."""
    return sha(path.read_text(encoding="utf-8").encode("utf-8"))


def run(argv, cwd, env, data=None):
    result = subprocess.run(argv, cwd=cwd, env=env, input=data, capture_output=True, check=True, timeout=120)
    return result.stdout


def elf_symbols(data, prefix=""):
    """Read ELF32 little-endian ARM symbols without an optional ELF dependency."""
    def unpack(fmt, offset):
        size = struct.calcsize(fmt)
        ex.require(0 <= offset <= len(data) - size, "truncated ELF record")
        return struct.unpack_from(fmt, data, offset)

    header = unpack("<16sHHIIIIIHHHHHH", 0)
    ex.require(header[0][:7] == b"\x7fELF\x01\x01\x01" and header[2] == 40,
               "expected ELF32 little-endian ARM")
    ex.require(header[1] in (1, 2) and header[11] == 40 and header[12] > 0, "unsupported ELF header")
    sections = [unpack("<10I", header[6] + i * header[11]) for i in range(header[12])]

    def contents(section):
        ex.require(section[1] != 8, "probe data cannot be NOBITS")
        offset, size = section[4:6]
        ex.require(0 <= offset <= len(data) - size, "ELF section outside file")
        return data[offset:offset + size]

    result = {}
    relocated = {section[7] for section in sections if section[1] in (4, 9) and section[5]}
    for section in sections:
        if section[1] != 2:
            continue
        ex.require(section[9] == 16 and section[5] % 16 == 0 and section[6] < len(sections), "invalid ELF symbol table")
        strings = contents(sections[section[6]])
        table = contents(section)
        for index in range(0, len(table), 16):
            name_offset, value, size, info, _, section_index = struct.unpack_from("<IIIBBH", table, index)
            ex.require(name_offset < len(strings), "invalid ELF string offset")
            end = strings.find(b"\0", name_offset)
            ex.require(end >= 0, "unterminated ELF symbol name")
            name = strings[name_offset:end].decode("utf-8")
            if not name.startswith(prefix) or not name or section_index == 0:
                continue
            if prefix:
                ex.require(name not in result, f"duplicate probe symbol {name}")
                ex.require(info & 15 == 1 and section_index < len(sections), "probe symbol must be an object")
                ex.require(section_index not in relocated, "probe section has relocations")
                target = sections[section_index]
                offset = value if header[1] == 1 else value - target[3]
                raw = contents(target)
                ex.require(0 <= offset <= len(raw) - size, "probe symbol outside section")
                result[name] = raw[offset:offset + size]
            else:
                # Used only for required global table/party/storage symbols.
                if name in result:
                    result[name] = None  # Do not silently choose an ambiguous local name.
                else:
                    result[name] = {"address": value, "size": size}
    ex.require(bool(result), "ELF contains no requested symbols")
    return result


def mask_field(raw, zero):
    ex.require(len(raw) == len(zero) and not any(zero), "nonzero/mismatched probe baseline")
    mask = int.from_bytes(raw, "little")
    ex.require(mask != 0, "empty bitfield mask")
    first = (mask & -mask).bit_length() - 1
    bits = (mask >> first).bit_length()
    ex.require(mask >> first == (1 << bits) - 1, "noncontiguous bitfield mask")
    offset, shift = divmod(first, 8)
    width = next((w for w in (1, 2, 4) if w * 8 >= shift + bits), None)
    ex.require(width is not None and offset + width <= len(raw), "bitfield exceeds reader lane")
    return {"offset": offset, "width": width, "shift": shift, "bits": bits,
            "mask": hex(((1 << bits) - 1) << shift), "initializer_sha256": sha(raw)}


def parse_probe(symbols):
    facts = {"structs": {}, "constants": {}}
    for name, raw in symbols.items():
        if name.startswith("x1_size__"):
            ex.require(len(raw) == 4, "invalid sizeof datum")
            size = int.from_bytes(raw, "little")
            type_name = name.split("__", 1)[1]
            baseline = symbols["x1_zero__" + type_name]
            ex.require(size == len(baseline) and not any(baseline), "sizeof/baseline mismatch")
            facts["structs"][type_name] = {"size": size, "fields": {}, "bitfields": {}}
        elif name.startswith("x1_const__"):
            ex.require(len(raw) == 4, "invalid constant datum")
            facts["constants"][name.split("__", 1)[1]] = int.from_bytes(raw, "little")
    for name, raw in symbols.items():
        parts = name.split("__")
        if parts[0] not in ("x1_field", "x1_array", "x1_mask"):
            continue
        _, type_name, member = parts
        target = facts["structs"][type_name]
        if parts[0] == "x1_mask":
            target["bitfields"][member] = mask_field(raw, symbols["x1_zero__" + type_name])
        else:
            expected = 12 if parts[0] == "x1_array" else 8
            ex.require(len(raw) == expected, "invalid field datum")
            values = struct.unpack("<" + "I" * (expected // 4), raw)
            offset, size = values[:2]
            ex.require(size > 0 and offset + size <= target["size"], "field outside struct")
            value = {"offset": offset, "size": size}
            if len(values) == 3:
                ex.require(values[2] > 0 and size % values[2] == 0, "invalid array geometry")
                value.update(element_size=values[2], count=size // values[2])
            target["fields"][member] = value
    for target in facts["structs"].values():
        occupied = 0
        for field in target["bitfields"].values():
            mask = int(field["mask"], 16) << (8 * field["offset"])
            ex.require(not occupied & mask, "overlapping bitfield initializers")
            occupied |= mask
    return facts


def compile_probe(source, probe, work, receipt, env):
    compiler = Path(receipt["compiler"]["path"])
    ex.require(sha(compiler.read_bytes()) == receipt["compiler"]["sha256"], "compiler differs from ROM receipt")
    overlay = work / "probe-flags.mk"
    overlay.write_text("\n".join(f"$(info X1_{name}=$({name}))" for name in FLAG_NAMES)
                       + "\n.PHONY: x1-probe-flags\nx1-probe-flags:\n\t@:\n", encoding="utf-8")
    argv = ["make", "--no-print-directory", "-s", "-f", "Makefile", "-f", str(overlay),
            *[f"{key}={value}" for key, value in receipt["make_variables"].items()], "x1-probe-flags"]
    text = run(argv, source, env).decode()
    flags = dict(re.findall(r"^X1_(\w+)=(.*)$", text, re.M))
    ex.require(set(flags) == set(FLAG_NAMES), "Makefile did not emit all pipeline flags")
    ex.require("-fshort-enums" not in shlex.split(flags["CFLAGS"]), "unexpected -fshort-enums")
    commands = [
        shlex.split(flags["CPP"]) + shlex.split(flags["CPPFLAGS"]) + [str(probe)],
        shlex.split(flags["PREPROC"]) + ["-i", "-g", flags["ASSETS_DIR_NAME"], str(probe), "charmap.txt"],
        shlex.split(flags["CC1"]) + shlex.split(flags["CFLAGS"]) + ["-o", str(work / "probe.s"), "-"],
        shlex.split(flags["AS"]) + shlex.split(flags["ASFLAGS"]) + ["-o", str(work / "probe.o"), str(work / "probe.s")],
    ]
    preprocessed = run(commands[0], source, env)
    translated = run(commands[1], source, env, preprocessed)
    (work / "probe.i").write_bytes(translated)
    run(commands[2], source, env, translated)
    with (work / "probe.s").open("a", encoding="utf-8") as stream:
        stream.write("\n.text\n\t.align\t2, 0\n")  # Makefile:474's exact assembly suffix.
    run(commands[3], source, env)
    executables = {}
    for command in commands:
        executable = Path(shutil.which(command[0], path=env["PATH"]) or source / command[0]).resolve()
        executables[str(executable)] = sha(executable.read_bytes())
    manifest = {"flags": flags, "commands": commands, "executables": executables,
                "source_hash_normalization": "UTF-8/LF", "probe_sha256": source_sha(probe),
                "object_sha256": sha((work / "probe.o").read_bytes()),
                "preprocessed_sha256": sha(translated), "source_commit": PIN,
                "make_variables": receipt["make_variables"], "build_receipt_sha256": sha(json.dumps(receipt, sort_keys=True).encode())}
    (work / "compile.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return work / "probe.o", manifest


def read_artifacts(artifacts):
    receipt = json.loads((artifacts / "receipt.json").read_text())
    ex.require(receipt["source"]["commit"] == PIN, "unsupported expansion source pin")
    for name in ("pokeemerald.gba", "pokeemerald.elf", "pokeemerald.map", "pokeemerald.sym"):
        raw = (artifacts / name).read_bytes()
        ex.require(sha(raw) == receipt["files"][name]["sha256"] and len(raw) == receipt["files"][name]["size"],
                   f"artifact differs from build receipt: {name}")
    rom = (artifacts / "pokeemerald.gba").read_bytes()
    ex.require(hashlib.sha1(rom).hexdigest() == receipt["rom"]["sha1"], "ROM sha1 mismatch")
    symbols = {}
    for address, size, name in re.findall(r"^([0-9a-f]+)\s+\w\s+([0-9a-f]+)\s+(\w+)$",
                                         (artifacts / "pokeemerald.sym").read_text(), re.M):
        value = {"address": int(address, 16), "size": int(size, 16)}
        symbols[name] = None if name in symbols else value
    return receipt, rom, symbols, elf_symbols((artifacts / "pokeemerald.elf").read_bytes())


def crosscheck(facts, rom, symbols, elf):
    types, const = facts["structs"], facts["constants"]
    reader = ex.Rom(rom)
    gf, rhh = ex.parse_headers(reader)
    ex.require(rhh is not None, "reference ROM has no RHH header")
    checks = {}

    def check(name, actual, expected):
        ex.require(actual == expected, f"probe self-check {name}: {actual!r} != {expected!r}")
        checks[name] = {"compiler": actual, "independent": expected}

    def symbol(name):
        ex.require(symbols.get(name) is not None and elf.get(name) == symbols[name], f"symbol/ELF disagreement: {name}")
        return symbols[name]

    check("Bag.size", types["Bag"]["size"], 0x848 - 0x560)
    check("SaveBlock1.flags", types["SaveBlock1"]["fields"]["flags"]["offset"], 0x1270)
    check("Pokemon.size", types["Pokemon"]["size"], 100)
    check("gParties.size", types["Pokemon"]["size"] * const["PARTY_SIZE"] * const["MAX_BATTLE_TRAINERS"], symbol("gParties")["size"])
    check("gPartiesCount.size", const["MAX_BATTLE_TRAINERS"], symbol("gPartiesCount")["size"])
    check("gBattleMons.size", types["BattlePokemon"]["size"] * const["MAX_BATTLERS_COUNT"], symbol("gBattleMons")["size"])
    for type_name, symbol_name in (("PokemonStorageASLR", "gPokemonStorage"),
                                  ("SaveBlock1ASLR", "gSaveblock1"), ("SaveBlock2ASLR", "gSaveblock2")):
        check(symbol_name + ".size", types[type_name]["size"], symbol(symbol_name)["size"])
        check(type_name + ".padding", types[type_name]["fields"]["aslr"]["size"], const["SAVEBLOCK_MOVE_RANGE"])
    check("gMain.size", types["Main"]["size"], symbol("gMain")["size"])
    for table, type_name, name, count in (
        ("species", "SpeciesInfo", "gSpeciesInfo", "NUM_SPECIES"),
        ("moves", "MoveInfo", "gMovesInfo", "MOVES_COUNT_ALL"),
        ("items", "ItemInfo", "gItemsInfo", "ITEMS_COUNT"),
        ("abilities", "AbilityInfo", "gAbilitiesInfo", "ABILITIES_COUNT"),
    ):
        # SpeciesInfo has one graphics-only Egg entry outside NUM_SPECIES:
        # src/data/pokemon/species_info.h:163; constants/species.h:1697-1698.
        table_count = const["SPECIES_EGG"] + 1 if table == "species" else const[count]
        if table == "species":
            check("species.egg_excluded", const["SPECIES_EGG"], const["NUM_SPECIES"])
        check(name + ".size", types[type_name]["size"] * table_count, symbol(name)["size"])
        check(name + ".pointer", symbol(name)["address"], rhh["abilities_pointer"] if table == "abilities" else gf[table])
        header_count = const["MOVES_COUNT"] if table == "moves" else const[count]
        check(table + ".count", header_count, rhh[table])
    # Public GF header fields independently read from this ROM (src/rom_header_gf.c).
    for name, value, header_offset in (
        ("SaveBlock1.flags.header", types["SaveBlock1"]["fields"]["flags"]["offset"], 0x50),
        ("SaveBlock1.vars.header", types["SaveBlock1"]["fields"]["vars"]["offset"], 0x54),
        ("SaveBlock2.size.header", types["SaveBlock2"]["size"], 0x88),
        ("SaveBlock1.size.header", types["SaveBlock1"]["size"], 0x8C),
        ("SaveBlock1.playerPartyCount.header", types["SaveBlock1"]["fields"]["playerPartyCount"]["offset"], 0x90),
        ("SaveBlock1.playerParty.header", types["SaveBlock1"]["fields"]["playerParty"]["offset"], 0x94),
    ):
        check(name, value, reader.uint(0x100 + header_offset, 4))
    check("item_name_length", const["ITEM_NAME_LENGTH"], rhh["item_name_length"])
    party_stride = const["PARTY_SIZE"] * types["Pokemon"]["size"]
    facts["derived_addresses"] = {
        "player_party": symbol("gParties")["address"] + const["B_TRAINER_PLAYER"] * party_stride,
        "enemy_party_a": symbol("gParties")["address"] + const["B_TRAINER_OPPONENT_A"] * party_stride,
        "player_party_count": symbol("gPartiesCount")["address"] + const["B_TRAINER_PLAYER"],
        "enemy_party_a_count": symbol("gPartiesCount")["address"] + const["B_TRAINER_OPPONENT_A"],
    }
    facts["symbol_checks"] = checks
    facts["headers"] = {"gf": gf, "rhh": rhh}


def make_layout(facts, rom_sha1, provenance):
    types, const = facts["structs"], facts["constants"]

    def field(type_name, name, signed=False):
        target = types[type_name]
        if name in target["bitfields"]:
            result = {k: v for k, v in target["bitfields"][name].items() if k in ("offset", "width", "shift", "bits")}
        else:
            value = target["fields"][name]
            result = {"offset": value["offset"], "width": value.get("element_size", value["size"])}
            if "count" in value:
                result["count"] = value["count"]
        if signed:
            result["signed"] = True
        return result

    def table(type_name, name_field, fields, pointer=False, length=None):
        value = types[type_name]["fields"][name_field]
        name = {"offset": value["offset"], "length": length if pointer else value["size"]}
        if pointer:
            name["pointer"] = True
        return {"stride": types[type_name]["size"], "name": name, "fields": fields}

    species_fields = {key: field("SpeciesInfo", key) for key in (*ex.STAT_FIELDS, "types", "abilities",
                     "growthRate", "expYield", "itemCommon", "itemRare", "genderRatio")}
    species_fields.update(national_dex=field("SpeciesInfo", "natDexNum"), evolution_pointer=field("SpeciesInfo", "evolutions"))
    moves = {key: field("MoveInfo", key, signed=key == "priority") for key in
             ("power", "type", "accuracy", "pp", "effect", "category", "target", "priority", "argument")}
    items = {key: field("ItemInfo", key) for key in ("price", "secondaryId", "holdEffect", "holdEffectParam", "battleUsage", "pocket")}
    return {"schema": 1, "kind": "expansion", "rom_sha1": rom_sha1, "provenance": provenance,
            "tables": {
                "species": table("SpeciesInfo", "speciesName", species_fields),
                "moves": table("MoveInfo", "name", moves, True, const["MOVE_NAME_LENGTH"] + 1),
                "items": table("ItemInfo", "name", items, True, const["ITEM_NAME_LENGTH"]),
                "abilities": table("AbilityInfo", "name", {}),
            },
            "evolutions": {"stride": types["Evolution"]["size"], "max_entries": 256,
                           "end_method": const["EVOLUTIONS_END"], "ignored_methods": [const["EVO_NONE"]],
                           "fields": {"method": field("Evolution", "method"), "param": field("Evolution", "param"),
                                      "target": field("Evolution", "targetSpecies")}}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--probe", type=Path, default=Path(__file__).with_name("expansion_offsets.c"))
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--object", type=Path, help="offline: existing probe.o, with compile.json beside it")
    args = parser.parse_args()
    source, work, probe = args.source.resolve(), args.work_dir.resolve(), args.probe.resolve()
    env = os.environ.copy()
    env["PATH"] = "/usr/bin:/bin" if os.name != "nt" else env["PATH"]
    for name in ("CC", "CXX", "CFLAGS", "CPPFLAGS", "LDFLAGS", "MAKEFLAGS", "DEVKITARM", "CPATH",
                 "LIBRARY_PATH", "PKG_CONFIG_PATH", "GCC_EXEC_PREFIX", "COMPILER_PATH", "C_INCLUDE_PATH", "CPLUS_INCLUDE_PATH"):
        env.pop(name, None)
    ex.require(run(["git", "rev-parse", "HEAD"], source, env).decode().strip() == PIN, "source commit mismatch")
    ex.require(not run(["git", "status", "--porcelain", "--untracked-files=no"], source, env), "source tracked files are dirty")
    receipt, rom, symbols, elf = read_artifacts(args.artifacts)
    work.mkdir(parents=True, exist_ok=True)
    if args.object:
        obj = args.object
        manifest = json.loads(obj.with_name("compile.json").read_text())
        ex.require(manifest["probe_sha256"] == source_sha(probe) and manifest["object_sha256"] == sha(obj.read_bytes()), "offline object/probe hash mismatch")
        ex.require(manifest["build_receipt_sha256"] == sha(json.dumps(receipt, sort_keys=True).encode()), "offline build receipt mismatch")
    else:
        obj, manifest = compile_probe(source, probe, work, receipt, env)
    facts = parse_probe(elf_symbols(obj.read_bytes(), "x1_"))
    crosscheck(facts, rom, symbols, elf)
    provenance = {"source_commit": PIN, "rom_sha1": receipt["rom"]["sha1"],
                  "compiler": receipt["compiler"], "compile": manifest,
                  "artifacts": receipt["files"], "generator_sha256": source_sha(Path(__file__)),
                  "extractor_sha256": source_sha(Path(ex.__file__)),
                  "makefile_sha256": source_sha(source / "Makefile"),
                  "config_sha256": {p.relative_to(source).as_posix(): source_sha(p) for p in sorted((source / "include/config").glob("*.h"))}}
    layout = make_layout(facts, receipt["rom"]["sha1"], provenance)
    # A reserved ID may be completely uninitialized, including no text EOS.
    # Record exact zero rows in this SHA1-bound layout; the extractor verifies
    # each entire row is zero and exports an explicit reserved marker, not a name.
    for table, spec in layout["tables"].items():
        header = facts["headers"]
        pointer = header["rhh"]["abilities_pointer"] if table == "abilities" else header["gf"][table]
        base = ex.Rom(rom).address(pointer)
        stride = spec["stride"]
        zeros = [i for i in range(header["rhh"][table]) if not any(rom[base + i * stride:base + (i + 1) * stride])]
        if zeros:
            spec["zero_records"] = zeros
    pack = ex.extract(rom, layout, ex.charmap(source))
    facts.update(schema=1, evidence="SOURCE/COMPILER/ROM only; no runtime qualification", provenance=provenance,
                 extraction={"counts": pack["counts"], "reserved_zero_records": {k: v.get("zero_records", []) for k, v in layout["tables"].items()},
                             "evolution_edges": sum(len(row["evolutions"]) for row in pack["species"]),
                             "data_sha256": sha(json.dumps(pack, sort_keys=True, ensure_ascii=False).encode())},
                 unavailable={"ItemInfo.battleEffect": "No such member; effect pointer and battleUsage emitted instead (include/item.h:69-90).",
                              "legacy_symbols": [name for name in ("gStatuses3", "gDisableStructs", "gTrainerBattleOpponent_A", "BattleIntroGetMonsData", "GiveMonToPlayer") if not symbols.get(name)],
                              "unresolved_engine_sites": [name for name in ("TryStorePartyMonInBox", "ReleaseMon") if not symbols.get(name)]})
    args.output.mkdir(parents=True, exist_ok=True)
    for name, value in (("layout", layout), ("facts", facts)):
        (args.output / f"{name}.json").write_text(json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"counts": pack["counts"], "checks": len(facts["symbol_checks"]),
                      "struct_sizes": {k: v["size"] for k, v in facts["structs"].items()}}, indent=2))


if __name__ == "__main__":
    main()
