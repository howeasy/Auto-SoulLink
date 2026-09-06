"""Generate immutable RBY party-codec facts from verified canonical builds.

Only numeric species/type/growth/move-PP facts and legal text glyph values are
published. This does not admit a modified ROM; ROM compliance is a separate gate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from server.adapters.gen1_rom_scan import (  # noqa: E402
    evolution_graph,
    scan_pokedex_order,
    sym_to_offset,
)
from tools.verify_canonical_sources import verify  # noqa: E402

JSON_OUTPUT = ROOT / "data/games/gen1_rby/party_codec.json"
LUA_OUTPUT = ROOT / "data/games/gen1_rby/gen1_party_codec_data.lua"
SCHEMA = "gen1-rby-codec-data-v1"


def digest(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=True).encode()).hexdigest()


def name_bytes(source: Path) -> list[int]:
    text = (source / "constants/charmap.asm").read_text(encoding="utf-8")
    glyphs = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 é():;[]'-?!.♂♀×/,¥")
    glyphs.update(("<PK>", "<MN>", "<DOT>", "<ED>", "'d", "'l", "'s", "'t", "'v", "'r", "'m"))
    rows = re.findall(r'^\s*charmap\s+"([^"\n]+)",\s*\$([\da-fA-F]+)', text, re.M)
    values = {int(value, 16) for glyph, value in rows if glyph in glyphs}
    found = {glyph for glyph, _value in rows}
    if glyphs - found:
        raise ValueError(f"name glyphs absent from {source.name}: {sorted(glyphs - found)}")
    if 0x50 in values or any(value < 0x7F or value > 0xFF for value in values):
        raise ValueError("name alphabet overlaps text controls")
    return sorted(values)


def build_tables() -> dict:
    evidence = verify(rom_dir=ROOT)
    if evidence["status"] != "pass":
        raise ValueError("canonical source gate failed: " + "; ".join(evidence["failures"]))
    lock = json.loads((ROOT / "data/pret_sources.lock.json").read_text(encoding="utf-8"))
    syms = json.loads((ROOT / "data/pret_rom_syms.json").read_text(encoding="utf-8"))
    profiles = {}
    sources = {}
    alphabets = []
    curves = []
    for title, target in (("red", "pokered"), ("blue", "pokeblue"), ("yellow", "pokeyellow")):
        pin = lock["clean_roms"][target]
        source = ROOT / ".cache/pret" / pin["source"]
        rom = (ROOT / pin["filename"]).read_bytes()
        symbols = syms[target]["symbols"]
        move_base = sym_to_offset(symbols["Moves"])
        base = sym_to_offset(symbols["BaseStats"])
        if base - move_base != 165 * 6:
            raise ValueError(f"{title}: Moves/BaseStats do not bound 165 six-byte records")
        move_pp = {}
        for move in range(1, 166):
            record = rom[move_base + (move - 1) * 6:move_base + move * 6]
            if record[0] != move or not 1 <= record[5] <= 40:
                raise ValueError(f"{title}: invalid canonical move record {move}")
            move_pp[str(move)] = record[5]
        order = scan_pokedex_order(rom)
        evolutions = evolution_graph(rom)
        species = {}
        for internal, dex in order.items():
            if not dex:
                continue
            offset = (sym_to_offset(symbols["MewBaseStats"])
                      if dex == 151 and "MewBaseStats" in symbols else base + (dex - 1) * 28)
            record = rom[offset:offset + 28]
            if len(record) != 28 or record[0] != dex or record[19] > 5:
                raise ValueError(f"{title}: invalid base-stat record for dex {dex}")
            species[str(internal)] = {"dex": dex, "types": list(record[6:8]),
                                      "base_stats": list(record[1:6]), "growth_rate": record[19],
                                      "evolution_targets": sorted({edge[-1] for edge in evolutions[internal]})}
        if len(species) != 151 or {row["dex"] for row in species.values()} != set(range(1, 152)):
            raise ValueError(f"{title}: internal-species table is incomplete")
        growth_source = (source / "data/growth_rates.asm").read_text(encoding="utf-8")
        growth = [[int(part.strip()) for part in row.split(",")] for row in re.findall(
            r"^[ \t]*growth_rate[ \t]+([-\d, \t]+)(?:;[^\n]*)?$", growth_source, re.M)]
        if len(growth) != 6 or any(len(row) != 5 or row[1] <= 0 for row in growth):
            raise ValueError(f"{title}: expected six canonical growth polynomials")
        curves.append(growth)
        alphabets.append(name_bytes(source))
        profiles[title] = {"species": species, "move_pp": move_pp}
        sources[title] = {"commit": lock["sources"][pin["source"]]["commit"],
                          "clean_sha1": pin["sha1"], "symbols": {name: symbols[name] for name in
                          ("Moves", "BaseStats", "PokedexOrder")}}
    if any(value != curves[0] for value in curves) or any(value != alphabets[0] for value in alphabets):
        raise ValueError("RBY name alphabets or growth polynomials differ; require per-title codec rules")
    result = {"schema": SCHEMA, "sources": sources, "titles": profiles,
              "name_bytes": alphabets[0], "growth_rates": curves[0]}
    result["content_sha256"] = digest(result)
    return result


def lua_value(value):
    if isinstance(value, dict):
        return "{" + ",".join("[" + (key if key.isdecimal() else json.dumps(key)) + "]="
                               + lua_value(item) for key, item in sorted(value.items())) + "}"
    if isinstance(value, list):
        return "{" + ",".join(lua_value(item) for item in value) + "}"
    return json.dumps(value, ensure_ascii=True)


def outputs(data):
    return {JSON_OUTPUT: json.dumps(data, indent=2, sort_keys=True) + "\n",
            LUA_OUTPUT: "-- Generated by tools/gen_gen1_codec_data.py; do not edit.\nreturn "
                        + lua_value(data) + "\n"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    generated = outputs(build_tables())
    if args.check:
        drift = [str(path.relative_to(ROOT)) for path, content in generated.items()
                 if not path.exists() or path.read_text(encoding="utf-8") != content]
        if drift:
            print("FAIL: generated party-codec data drift: " + ", ".join(drift))
            return 1
        print("Party codec data: PASS (three canonical titles, 151 species each, 165 moves each)")
        return 0
    for path, content in generated.items():
        path.write_text(content, encoding="utf-8", newline="\n")
        print(path.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
