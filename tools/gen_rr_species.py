#!/usr/bin/env python3
"""
Generate the RR species-name catalog and ROM extension provenance.

Radical Red uses a CUSTOM species numbering that differs from standard CFRU.
Gen 9 mons, RR-exclusive Sevii forms, and some rearranged entries mean the
standard CFRU species table is wrong for many IDs.

Source: https://funnotbun.github.io/ (RR Dex) -> data/species/species.h from
the funnotbun repo. That repo no longer exists on GitHub (confirmed 404,
2026-09-26) -- the byte-for-byte pinned copy this now reads lives in
data/gen3_rr_sources.lock.json (funnotbun_species_h), a Wayback Machine
capture. See docs/gen3_requirements.md row F-7 and tools/fetch_rr_sources.py.

Usage:
    python tools/gen_rr_species.py --rom RR.gba  # regenerate catalog + ROM provenance
    python tools/gen_rr_species.py --check     # regenerate in memory and diff
                                                 # against the committed
                                                 # data/games/gen3_frlge/rr_species.json
"""

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_rr_sources import cached_source, diff_snippet  # noqa: E402
from rr_rom_encounters import default_rom_path, load_rom  # noqa: E402
from rr_rom_species import display_metadata, extend_names  # noqa: E402

_REPO_ROOT = Path(__file__).resolve().parent.parent
CANONICAL_OUTPUT = _REPO_ROOT / "data" / "games" / "gen3_frlge" / "rr_species.json"
# The non-check write target -- kept identical to CANONICAL_OUTPUT so
# `python tools/gen_rr_species.py` (no --check) actually updates the file
# the --check mode (and every consumer) reads, instead of a stray
# CWD-relative data/rr_species.json nothing imports.
OUT_JSON = CANONICAL_OUTPUT
PROVENANCE_OUTPUT = _REPO_ROOT / "data" / "gen3_rr_species_rom.json"

# Special display name overrides
SPECIAL_NAMES = {
    "HO_OH": "Ho-Oh",
    "MR_MIME": "Mr. Mime",
    "MR_RIME": "Mr. Rime",
    "MIME_JR": "Mime Jr.",
    "MIME_JR_G": "Mime Jr.-Galar",
    "NIDORAN_F": "Nidoran♀",
    "NIDORAN_M": "Nidoran♂",
    "PORYGON_Z": "Porygon-Z",
    "PORYGON2": "Porygon2",
    "TYPE_NULL": "Type: Null",
    "JANGMO_O": "Jangmo-o",
    "HAKAMO_O": "Hakamo-o",
    "KOMMO_O": "Kommo-o",
    "TAPU_KOKO": "Tapu Koko",
    "TAPU_LELE": "Tapu Lele",
    "TAPU_BULU": "Tapu Bulu",
    "TAPU_FINI": "Tapu Fini",
    "TING_LU": "Ting-Lu",
    "CHIEN_PAO": "Chien-Pao",
    "WO_CHIEN": "Wo-Chien",
    "CHI_YU": "Chi-Yu",
    "FARFETCHED": "Farfetch'd",
    "FARFETCHD": "Farfetch'd",
    "SIRFETCHD": "Sirfetch'd",
    "FARFETCHD_G": "Farfetch'd-Galar",
}

# Regional suffixes → display suffix
REGION_SUFFIXES = {
    "_A": "-Alola",
    "_G": "-Galar",
    "_H": "-Hisui",
    "_P": "-Paldea",
    "_S": "-Sevii",
    "_F": " (Female)",
    "_O": " (Origin)",
}

# Form suffixes → display form label
FORM_SUFFIXES = [
    "_MEGA_X", "_MEGA_Y", "_MEGA", "_GIGA", "_PRIMAL",
    "_THERIAN", "_ORIGIN", "_SKY", "_BLADE", "_CROWNED",
    "_RESOLUTE", "_PIROUETTE", "_BUSTED", "_HANGRY", "_ETERNAMAX",
    "_NOICE", "_HERO", "_COMPLETE", "_ULTRA", "_DUSK_MANE",
    "_DAWN_WINGS", "_DUSK", "_BLACK", "_WHITE", "_ZEN",
    "_SUN", "_SHIELD", "_GULPING", "_GORGING", "_ICE", "_SHADOW",
    "_LOW_KEY", "_SINGLE", "_RAPID", "_SANDY", "_TRASH",
    "_EAST", "_HEAT", "_WASH", "_FROST", "_FAN", "_MOW",
    "_RED", "_BLUE", "_ORANGE", "_YELLOW", "_INDIGO", "_GREEN", "_VIOLET",
    "_SURFING", "_FLYING", "_COSPLAY", "_LIBRE", "_POP_STAR",
    "_ROCK_STAR", "_BELLE", "_PHD",
    "_CAP_ORIGINAL", "_CAP_HOENN", "_CAP_SINNOH", "_CAP_UNOVA",
    "_CAP_KALOS", "_CAP_ALOLA", "_CAP_PARTNER",
    "_FIGHT", "_FLYING", "_POISON", "_GROUND", "_ROCK", "_BUG",
    "_GHOST", "_STEEL", "_FIRE", "_WATER", "_GRASS", "_ELECTRIC",
    "_PSYCHIC", "_ICE", "_DRAGON", "_DARK", "_FAIRY",
    "_STRAWBERRY", "_ETERNAL", "_XL", "_L", "_M",
    "_CHEST", "_ROAM",
]


def to_display(name):
    """Convert SPECIES_XXX define name to a human-readable display name."""
    if name in SPECIAL_NAMES:
        return SPECIAL_NAMES[name]

    # Check regional suffixes first
    for suf, label in REGION_SUFFIXES.items():
        if name.endswith(suf) and len(name) > len(suf):
            # Make sure it's a regional variant, not part of the base name
            base = name[:-len(suf)]
            if base and not base.endswith("_"):
                return base.replace("_", " ").title() + label

    # Check form suffixes
    for suf in FORM_SUFFIXES:
        if name.endswith(suf):
            base = name[:-len(suf)]
            form_label = suf[1:].replace("_", " ").title()
            return base.replace("_", " ").title() + " (" + form_label + ")"

    # RR-specific: ASHGRENINJA, DARMANITANZEN, etc.
    rr_special = {
        "ASHGRENINJA": "Greninja (Ash)",
        "DARMANITANZEN": "Darmanitan (Zen)",
        "BASCULIN_RED": "Basculin (Red)",
        "BASCULIN_BLUE": "Basculin (Blue)",
        "BASCULEGION": "Basculegion",
        "BASCULEGION_F": "Basculegion (Female)",
        "ALCREMIE_STRAWBERRY": "Alcremie",
        "ALCREMIE_GIGA": "Alcremie (Giga)",
        "MINIOR_SHIELD": "Minior (Shield)",
    }
    if name in rr_special:
        return rr_special[name]

    # Default: title case
    return name.replace("_", " ").title()


def _parse_names(data: str) -> dict[int, str]:
    entries = {}
    for m in re.finditer(r"#define\s+SPECIES_(\w+)\s+0x([0-9A-Fa-f]+)", data):
        name = m.group(1)
        num = int(m.group(2), 16)
        if name in ("NONE", "EGG"):
            continue
        if num not in entries:
            entries[num] = name
    return {num: to_display(define_name) for num, define_name in sorted(entries.items())}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=default_rom_path(), help="pinned RR ROM (or SLINK_RR_ROM)")
    parser.add_argument("--check", action="store_true",
                        help="Regenerate in memory and diff against the "
                             f"committed {CANONICAL_OUTPUT}; exit 1 on drift.")
    args = parser.parse_args()

    data = cached_source("funnotbun_species_h").decode("utf-8")
    names, provenance = extend_names(load_rom(args.rom), _parse_names(data),
        display_metadata(cached_source("jwowsquared_data_js").decode("utf-8")))
    regen = json.dumps({str(k): v for k, v in sorted(names.items())}, indent=2)
    proof = json.dumps(provenance, indent=2)+"\n"

    if args.check:
        committed = CANONICAL_OUTPUT.read_text(encoding="utf-8")
        if regen == committed and PROVENANCE_OUTPUT.exists() and PROVENANCE_OUTPUT.read_text(encoding="utf-8") == proof:
            print(f"OK: regenerated output matches {CANONICAL_OUTPUT} byte-for-byte "
                  f"({len(names)} species).")
            return 0
        print(f"DRIFT: regenerated output ({len(regen)} bytes) != "
              f"{CANONICAL_OUTPUT} ({len(committed)} bytes)\n"
              f"{diff_snippet(committed, regen)}", file=sys.stderr)
        return 1

    print(f"Parsed {len(names)} species entries (max ID: {max(names.keys())} = 0x{max(names.keys()):X})")

    # Save intermediate JSON
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8", newline="\n") as f:
        f.write(regen)
    PROVENANCE_OUTPUT.write_text(proof, encoding="utf-8", newline="\n")
    print(f"Saved {len(names)} names to {OUT_JSON}")

    # Verify key entries
    checks = {
        1: "Bulbasaur", 25: "Pikachu", 37: "Vulpix", 150: "Mewtwo",
        328: "Feebas", 706: "Klawf", 936: "Kingambit",
        1025: "Vulpix-Alola", 1274: "Blitzle-Sevii",
        1285: "Feebas-Sevii", 1314: "Tarountula",
    }
    print("\nVerification:")
    for sid, expected in checks.items():
        actual = names.get(sid, "MISSING")
        ok = "✓" if expected.lower() in actual.lower() else "✗"
        print(f"  {ok} {sid:4d} (0x{sid:03X}): {actual}  (expected: {expected})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
