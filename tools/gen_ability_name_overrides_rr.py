#!/usr/bin/env python3
"""Generate per-species ability name overrides for RR from funnotbun sources.

Usage:
    python tools/gen_ability_name_overrides_rr.py
    python tools/gen_ability_name_overrides_rr.py \\
        --duplicates path\\to\\duplicate_abilities.h \\
        --abilities-h path\\to\\abilities.h \\
        --names-string path\\to\\ability_name_table.string \\
        --species-h path\\to\\species.h

Parses funnotbun's duplicate_abilities.h (the same source the funnotbun web dex
uses for per-species ability display) and emits the (ability_id, natdex_id) -> name
table consumed by server/pokemon_data.py.

By default, all inputs are fetched from the authoritative funnotbun raw GitHub URLs.
Output is written to server/rr_ability_overrides.py.
"""

from __future__ import annotations

import argparse
import re
import sys
import urllib.request
from pathlib import Path

# Reuse parsers from the sibling ability-name generator.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from gen_ability_names_rr import (  # noqa: E402
    NORMALIZED_NAME_ALIASES,
    normalize_name,
    parse_abilities_h,
    parse_names_string,
    read_text,
)

DUPLICATES_URL = (
    "https://raw.githubusercontent.com/funnotbun/funnotbun.github.io/"
    "main/data/abilities/duplicate_abilities.h"
)
ABILITIES_H_URL = (
    "https://raw.githubusercontent.com/funnotbun/funnotbun.github.io/"
    "main/data/abilities/abilities.h"
)
NAMES_STRING_URL = (
    "https://raw.githubusercontent.com/funnotbun/funnotbun.github.io/"
    "main/data/abilities/ability_name_table.string"
)
SPECIES_H_URL = (
    "https://raw.githubusercontent.com/funnotbun/funnotbun.github.io/"
    "main/data/species/species.h"
)

OUTPUT_PATH = Path(__file__).resolve().parents[1] / "server" / "rr_ability_overrides.py"

# Minimum entry count: hard floor below which we assume the source file is
# truncated or the parser is broken. Current file has ~100 entries.
MIN_ENTRIES = 80


def parse_species_h(text: str) -> dict[str, int]:
    """Map SPECIES_X constant name -> CFRU internal species ID."""
    name_to_id: dict[str, int] = {}
    for m in re.finditer(r"#define\s+SPECIES_(\w+)\s+0x([0-9A-Fa-f]+)", text):
        name = m.group(1)
        num = int(m.group(2), 16)
        if name in ("NONE", "EGG"):
            continue
        name_to_id.setdefault(name, num)
    return name_to_id


# Block pattern for one entry. Captures the three constant tokens; tolerates
# inline `//comments` and arbitrary whitespace.
_ENTRY_RE = re.compile(
    r"\.species\s*=\s*SPECIES_(?P<species>\w+).*?"
    r"\.currAbility\s*=\s*ABILITY_(?P<ability>\w+).*?"
    r"\.replaceAbilityString\s*=\s*NAME_(?P<name>\w+)",
    re.DOTALL,
)


def parse_duplicates(text: str) -> list[tuple[str, str, str]]:
    """Return list of (SPECIES_X, ABILITY_Y, NAME_Z) triples (suffixes only)."""
    return [(m["species"], m["ability"], m["name"]) for m in _ENTRY_RE.finditer(text)]


def load_cfru_to_national() -> dict[int, int]:
    """Pull the CFRU->NatDex map from server.pokemon_data without importing the
    whole module's side-effect-heavy state (the dict literal is at module load).
    """
    repo_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo_root))
    from server.pokemon_data import CFRU_TO_NATIONAL  # noqa: E402
    return dict(CFRU_TO_NATIONAL)


def build_overrides(
    duplicates_text: str,
    abilities_h_text: str,
    names_string_text: str,
    species_h_text: str,
) -> dict[tuple[int, int], tuple[str, str]]:
    """Return {(ability_id, natdex_id): (display_name, species_constant)}.

    species_constant is carried only for emitting a `# Mightyena` style comment.
    """
    # Stage 1: resolve constants
    species_to_cfru = parse_species_h(species_h_text)              # SPECIES_X -> CFRU id
    ability_to_id = parse_abilities_h(abilities_h_text)            # id -> ABILITY_X (existing parser is reversed)
    # Build the reverse: ABILITY_X -> id. parse_abilities_h returns {id: "QUICKFEET"} (suffix only).
    ability_name_to_id = {name: aid for aid, name in ability_to_id.items()}
    normalized_to_display = parse_names_string(names_string_text)  # normalized NAME -> "Pure Power"
    cfru_to_natdex = load_cfru_to_national()

    # Stage 2: resolve each duplicate-ability entry
    overrides: dict[tuple[int, int], tuple[str, str]] = {}
    errors: list[str] = []
    # Form-collisions: distinct CFRU forms collapse to the same NatDex via
    # to_national() (e.g. Kyurem-Black + Kyurem-White both -> 646). When their
    # override names differ, we can't pick one from the (ability_id, natdex) key
    # alone, so we drop ALL conflicting entries and warn. Affected mons fall
    # back to the generic ability name. Add to CFRU_ABILITY_NAME_OVERRIDES_MANUAL
    # if a specific form's display matters more.
    conflicts: dict[tuple[int, int], list[tuple[str, str]]] = {}

    for sp, ab, nm in parse_duplicates(duplicates_text):
        # Species
        cfru = species_to_cfru.get(sp)
        if cfru is None:
            errors.append(f"Unknown SPECIES_{sp}")
            continue
        # CFRU -> NatDex (identity for Gen 1-2)
        natdex = cfru_to_natdex.get(cfru, cfru)

        # Ability
        aid = ability_name_to_id.get(ab)
        if aid is None:
            errors.append(f"Unknown ABILITY_{ab} (entry: SPECIES_{sp})")
            continue

        # Display name (apply normalize + alias the same way gen_ability_names_rr.py does)
        normalized = normalize_name(f"NAME_{nm}")
        display = normalized_to_display.get(normalized)
        if not display:
            display = normalized_to_display.get(NORMALIZED_NAME_ALIASES.get(normalized, normalized))
        if not display:
            errors.append(f"Unknown NAME_{nm} (entry: SPECIES_{sp} ABILITY_{ab})")
            continue

        key = (aid, natdex)
        existing = overrides.get(key)
        if existing and existing[0] != display:
            conflicts.setdefault(key, [(existing[0], existing[1])]).append((display, sp))
            continue
        overrides[key] = (display, sp)

    if errors:
        msg = "\n  ".join(errors)
        raise ValueError(f"duplicate_abilities.h resolution errors:\n  {msg}")

    # Drop conflicting entries entirely; warn for visibility.
    for key, variants in conflicts.items():
        variants_str = ", ".join(f"{name!r} ({sp})" for name, sp in variants)
        print(
            f"warning: form collision at (ability={key[0]}, natdex={key[1]}): "
            f"{variants_str} -- dropping override, will show generic name",
            file=sys.stderr,
        )
        overrides.pop(key, None)

    if len(overrides) < MIN_ENTRIES:
        raise ValueError(
            f"Override coverage too low: {len(overrides)} < {MIN_ENTRIES}. "
            f"Source file may be truncated."
        )

    return overrides


def format_output(overrides: dict[tuple[int, int], tuple[str, str]]) -> str:
    lines = [
        '"""RR per-species ability name overrides — AUTO-GENERATED.',
        "",
        "Source: funnotbun/funnotbun.github.io data/abilities/duplicate_abilities.h",
        "Regenerate with: python tools/gen_ability_name_overrides_rr.py",
        "",
        "DO NOT EDIT MANUALLY. Manual additions go in CFRU_ABILITY_NAME_OVERRIDES_MANUAL",
        "in server/pokemon_data.py (where they take precedence over generated entries).",
        '"""',
        "",
        f"# {len(overrides)} entries",
        "CFRU_ABILITY_NAME_OVERRIDES_GENERATED: dict[tuple[int, int], str] = {",
    ]
    for (aid, natdex), (display, sp) in sorted(overrides.items()):
        escaped = display.replace("\\", "\\\\").replace('"', '\\"')
        sp_human = sp.replace("_", " ").title()
        lines.append(f'    ({aid}, {natdex}): "{escaped}",  # {sp_human}')
    lines.append("}")
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--duplicates", default=DUPLICATES_URL)
    p.add_argument("--abilities-h", default=ABILITIES_H_URL)
    p.add_argument("--names-string", default=NAMES_STRING_URL)
    p.add_argument("--species-h", default=SPECIES_H_URL)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    overrides = build_overrides(
        read_text(args.duplicates),
        read_text(args.abilities_h),
        read_text(args.names_string),
        read_text(args.species_h),
    )
    output = format_output(overrides)
    OUTPUT_PATH.write_text(output, encoding="utf-8")
    print(f"Wrote {len(overrides)} entries to {OUTPUT_PATH}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
