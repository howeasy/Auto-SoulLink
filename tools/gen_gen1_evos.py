#!/usr/bin/env python3
"""Generate the Gen 1 evolution-family table from pret/pokered raw asm.

Reads:
    .cache/pret/pokered/data/pokemon/evos_moves.asm        (per-species evolutions)
    .cache/pret/pokered/constants/pokemon_constants.asm    (species name → internal idx)
    data/games/gen1_rby/species_index.json                 (internal idx → NatDex)

Writes:
    data/games/gen1_rby/evolutions.json

WHY THIS EXISTS. `Gen1Adapter.evo_family` used to delegate to
`server.pokemon_data.base_form(sid, False)`, which is the CFRU/Gen 3+ family table.
That answers "what is the earliest form of this line in a MODERN game", and for
Gen 1 species it gives answers Gen 1 has no concept of:

    base_form(106) == base_form(107) == 236   # Tyrogue

Hitmonlee and Hitmonchan are unrelated species in RBY — `evos_moves.asm` gives
both an empty evolution list. The Fighting Dojo lets you take exactly one, so the
canonical Soul Link split (A takes Hitmonlee, B takes Hitmonchan) was rejected by
the species clause and one live mon was force-fainted and buried.

The tempting one-line fix — clamp `base_form` to 1..151 — is WRONG. Enumerating
every merge over 1..151 shows 236:[106,107] is the ONLY one joining unrelated
species; 172:[25,26], 173:[35,36] and 174:[39,40] are real families remapped to a
Gen 2 baby form, and clamping would split Pikachu/Raichu, Clefairy/Clefable and
Jigglypuff/Wigglytuff. Hence a real Gen 1 table.

RED AND YELLOW SHARE THIS DATA. `evos_moves.asm` differs between the decomps, but
only in learnsets — the 72 `EVOLVE_*` entries are byte-identical, so one table
serves Red, Blue and Yellow.

Record format (`evos_moves.asm:1-9`), repeated until a `db 0` terminator:
    db EVOLVE_LEVEL, level,      species
    db EVOLVE_ITEM,  item, 1,    species
    db EVOLVE_TRADE, 1,          species
The trailing operand is always the target species constant, which is what we want.

PUREGRB (--foundation purergb). pureRGB's evolution edges are keyed by INTERNAL
species id, never national dex: forms/spirits share a dex number with their base
species (docs/purergb/PLAN.md S3.3), so dex can no longer identify a species. Only
the 151 "ordinary" internal ids ever evolve (every form/spirit/MissingNo points its
`EvosMovesPointerTable` entry at a shared `NothingEvosMoves`/its base's own list, per
PLAN S7.1) so the union-find family graph is built over exactly those 151 ids, the
same shape (72 edges / 79 families) as vanilla's. pureRGB also adds a level-37
`EVOLVE_LEVEL` entry beside the existing `EVOLVE_TRADE` for the four classic
trade-evolution species (Haunter/Kadabra/Graveler/Machoke), so 4 more *method*
entries than edges (76 methods / 72 edges). The pointer table is walked from the
BUILT ROM (not label text) because several internal ids intentionally share one
label (`NothingEvosMoves`) that source-only label matching cannot disambiguate;
source text is still used as an independent cross-check per ordinary species.
"""
from __future__ import annotations

import json
import os
import re
import sys

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.normpath(os.path.join(_THIS_DIR, ".."))
# Worktrees do not carry .cache/; allow pointing at the main checkout's copy.
_PRET = os.environ.get("SLINK_PRET_DIR") or os.path.join(_REPO, ".cache", "pret", "pokered")
_OUT = os.path.join(_REPO, "data", "games", "gen1_rby", "evolutions.json")
_SPECIES_INDEX = os.path.join(_REPO, "data", "games", "gen1_rby", "species_index.json")

sys.path.insert(0, _THIS_DIR)
import gen1_foundation as fnd  # noqa: E402
from gen_gen1_encounters import parse_pokemon_constants  # noqa: E402

_EVOLVE_LEVEL, _EVOLVE_ITEM, _EVOLVE_TRADE = 1, 2, 3

_LABEL_RE = re.compile(r"^(\w+)EvosMoves:")
_EVOLVE_RE = re.compile(r"^db\s+EVOLVE_(LEVEL|ITEM|TRADE)\s*,\s*(.+)$")


def parse_evolutions(path: str) -> dict[str, list[str]]:
    """`<SPECIES_CONST> → [target species consts]`, keyed by the asm label name.

    We walk label blocks rather than the pointer table because the label itself
    names the species, and the evolution section is everything up to the first
    bare `db 0`.
    """
    out: dict[str, list[str]] = {}
    label: str | None = None
    in_evos = False
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.split(";", 1)[0].strip()
            if not line:
                continue
            m = _LABEL_RE.match(line)
            if m:
                label = m.group(1)
                out[label] = []
                in_evos = True
                continue
            if label is None or not in_evos:
                continue
            if line == "db 0":
                in_evos = False          # evolutions done; learnset follows
                continue
            m = _EVOLVE_RE.match(line)
            if m:
                # The target species is always the LAST operand.
                out[label].append(m.group(2).split(",")[-1].strip())
    return out


def _label_to_const(label: str, consts: dict[str, int]) -> str | None:
    """`ClefairyEvosMoves` → `CLEFAIRY`. A few labels need help."""
    special = {
        "NidoranM": "NIDORAN_M", "NidoranF": "NIDORAN_F",
        "Farfetchd": "FARFETCH_D", "MrMime": "MR_MIME",
    }
    if label in special:
        return special[label]
    upper = label.upper()
    return upper if upper in consts else None


def build() -> dict:
    consts = parse_pokemon_constants(
        os.path.join(_PRET, "constants", "pokemon_constants.asm"))
    with open(_SPECIES_INDEX, encoding="utf-8") as f:
        idx_to_nat = {int(k): int(v)
                      for k, v in json.load(f)["index_to_national"].items()}

    def natdex(const: str) -> int | None:
        i = consts.get(const)
        return idx_to_nat.get(i) if i is not None else None

    raw = parse_evolutions(os.path.join(_PRET, "data", "pokemon", "evos_moves.asm"))

    # Union-find over NatDex numbers. The family representative is the LOWEST
    # NatDex in the set, which is stable and reads sensibly in a log line.
    parent: dict[int, int] = {n: n for n in range(1, 152)}

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            lo, hi = (ra, rb) if ra < rb else (rb, ra)
            parent[hi] = lo

    edges: dict[int, list[int]] = {}
    unresolved: list[str] = []
    for label, targets in raw.items():
        const = _label_to_const(label, consts)
        src = natdex(const) if const else None
        if src is None:
            if targets:
                unresolved.append(label)
            continue
        for t in targets:
            dst = natdex(t)
            if dst is None:
                unresolved.append(f"{label} -> {t}")
                continue
            edges.setdefault(src, []).append(dst)
            union(src, dst)

    if unresolved:
        raise SystemExit(f"unresolved evolution species: {unresolved}")

    family = {n: find(n) for n in range(1, 152)}
    return {
        "_source": "pret/pokered data/pokemon/evos_moves.asm "
                   "(evolution entries are identical in pokeyellow)",
        "evolutions": {str(k): sorted(v) for k, v in sorted(edges.items())},
        "family": {str(n): family[n] for n in range(1, 152)},
    }


def _read_evolution_entries(rom: bytes, flat_addr: int) -> list[tuple[int, int]]:
    """[(method, target_internal_id), ...] at a `db 0`-terminated evos block."""
    out: list[tuple[int, int]] = []
    p = flat_addr
    while rom[p] != 0:
        method = rom[p]
        if method == _EVOLVE_LEVEL:
            out.append((method, rom[p + 2]))
            p += 3
        elif method == _EVOLVE_ITEM:
            out.append((method, rom[p + 3]))
            p += 4
        elif method == _EVOLVE_TRADE:
            out.append((method, rom[p + 2]))
            p += 3
        else:
            raise SystemExit(f"unknown evolution method byte {method:#x} at flat {p:#x}")
    return out


def build_purergb() -> dict:
    """Walk `EvosMovesPointerTable` in the built ROM (bank $2C) for every internal
    id classified "ordinary" by `gen_gen1_species.py` -- forms/spirits/MissingNo
    never evolve further (PLAN S7.1), so the evolution graph is exactly the 151
    ordinary ids, keyed by internal id (dex cannot key it: forms share a base
    species' dex). Cross-checked against `data/pokemon/evos_moves.asm` label text
    for the same 151 ids (their own labels are unique, unlike the shared
    `NothingEvosMoves` label the non-evolving forms point at).
    """
    species_index_path = fnd.data_dir("purergb") / "species_index.json"
    species = json.loads(species_index_path.read_text(encoding="utf-8"))
    ordinary = {int(k): v for k, v in species["species"].items() if v["classification"] == "ordinary"}
    transform_edges = species["transform_edges"]

    consts_text = fnd.read_source("purergb", "constants/pokemon_constants.asm")
    consts = parse_pokemon_constants_generic(consts_text)  # NAME -> internal id
    name_by_id = {i: n for n, i in consts.items()}

    src_text = fnd.read_source("purergb", "data/pokemon/evos_moves.asm")
    tmp_source = _write_tmp_source(src_text)
    try:
        src_by_label = parse_evolutions(tmp_source)
    finally:
        os.remove(tmp_source)
    # Reuse `_label_to_const`'s tested label->species-constant resolution (handles
    # the handful of labels whose casing doesn't round-trip, e.g. `FarfetchdEvosMoves`)
    # instead of re-deriving a label spelling from the constant name.
    label_by_id: dict[int, str] = {}
    for label in src_by_label:
        const = _label_to_const(label, consts)
        if const in consts:
            label_by_id[consts[const]] = label

    titles = list(fnd.foundation("purergb")["titles"])
    edges: dict[int, set[int]] = {}
    methods: list[tuple[int, int]] = []
    per_title: dict[str, dict[int, list[tuple[int, int]]]] = {}
    for title in titles:
        syms = fnd.parse_sym(fnd.sym_path("purergb", title))
        rom = fnd.rom_path("purergb", title).read_bytes()
        table_flat = fnd.flat(*syms["EvosMovesPointerTable"])
        table_bank = syms["EvosMovesPointerTable"][0]
        per_id: dict[int, list[tuple[int, int]]] = {}
        for internal_id in ordinary:
            ptr_addr = table_flat + (internal_id - 1) * 2
            target_addr = rom[ptr_addr] | (rom[ptr_addr + 1] << 8)
            entries = _read_evolution_entries(rom, fnd.flat(table_bank, target_addr))
            per_id[internal_id] = entries
        per_title[title] = per_id

    mismatches = [t for t in titles[1:] if per_title[t] != per_title[titles[0]]]
    if mismatches:
        raise SystemExit(f"EvosMovesPointerTable disagrees between titles: {mismatches}")

    for internal_id, entries in per_title[titles[0]].items():
        label_name = label_by_id.get(internal_id)
        src_targets = src_by_label.get(label_name) if label_name else None
        for _method, target_id in entries:
            methods.append((internal_id, target_id))
            edges.setdefault(internal_id, set()).add(target_id)
            if src_targets is not None and name_by_id.get(target_id) not in src_targets:
                raise SystemExit(
                    f"ROM/source disagreement: {label_name} ROM target id {target_id} "
                    f"({name_by_id.get(target_id)}) not in source targets {src_targets}")

    parent = {i: i for i in ordinary}

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            lo, hi = (ra, rb) if ra < rb else (rb, ra)
            parent[hi] = lo

    for src, targets in edges.items():
        for dst in targets:
            union(src, dst)

    family = {i: find(i) for i in ordinary}
    return {
        "_source": "pureRGB data/pokemon/evos_moves.asm, ROM-verified via "
                   "EvosMovesPointerTable (all three built titles agree)",
        "evolutions": {str(k): sorted(v) for k, v in sorted(edges.items())},
        "family": {str(i): family[i] for i in sorted(ordinary)},
        "transform_edges": transform_edges,
    }, len(methods)


def parse_pokemon_constants_generic(text: str) -> dict[str, int]:
    """NAME -> internal id, generic `const_def`/`const`/`const_skip` parser."""
    out: dict[str, int] = {}
    value = -1
    for raw in text.splitlines():
        line = raw.split(";", 1)[0].strip()
        if line == "const_def":
            value = 0
            continue
        if value < 0:
            continue
        m = re.match(r"^const\s+([A-Za-z_][A-Za-z0-9_]*)\s*$", line)
        if m:
            out[m.group(1)] = value
            value += 1
        elif line == "const_skip":
            value += 1
        elif line and not line.startswith(";"):
            break
    return out


def _write_tmp_source(text: str) -> str:
    """`parse_evolutions` reads a path; hand it a scratch copy of the source text."""
    import tempfile
    fd, path = tempfile.mkstemp(suffix=".asm")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def main() -> int:
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--foundation", default="pret", choices=["pret", "purergb"])
    args = p.parse_args()

    if args.foundation == "pret":
        if not os.path.isdir(_PRET):
            raise SystemExit(f"pret/pokered not found at {_PRET} "
                             f"(set SLINK_PRET_DIR to override)")
        data = build()
        n_edges = sum(len(v) for v in data["evolutions"].values())
        n_families = len(set(data["family"].values()))
        with open(_OUT, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1, sort_keys=False)
            f.write("\n")
        print(f"[gen1-evos] {n_edges} evolution edges, {n_families} families "
              f"-> {os.path.relpath(_OUT, _REPO)}", file=sys.stderr)
        return 0

    data, n_methods = build_purergb()
    n_edges = sum(len(v) for v in data["evolutions"].values())
    n_families = len(set(data["family"].values()))
    if (n_methods, n_edges, n_families) != (76, 72, 79):
        raise SystemExit(
            f"purergb evolution shape drifted: methods={n_methods} edges={n_edges} "
            f"families={n_families} (expected 76/72/79)")
    out_path = fnd.data_dir("purergb") / "evolutions.json"
    out_path.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
    print(f"[gen1-evos:purergb] {n_methods} method entries, {n_edges} edges, "
          f"{n_families} families -> {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
