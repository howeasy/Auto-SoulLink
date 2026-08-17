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
from gen_gen1_encounters import parse_pokemon_constants  # noqa: E402

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


def main() -> int:
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


if __name__ == "__main__":
    sys.exit(main())
