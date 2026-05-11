#!/usr/bin/env python3
"""
Generate RR-specific SPECIES_NAMES dict for pokemon_data.py.

Radical Red uses a CUSTOM species numbering that differs from standard CFRU.
Gen 9 mons, RR-exclusive Sevii forms, and some rearranged entries mean the
standard CFRU species table is wrong for many IDs.

Source: https://funnotbun.github.io/ (RR Dex)
        -> data/species/species.h from the funnotbun repo
"""

import re
import json
import urllib.request
from pathlib import Path

SPECIES_H_URL = "https://raw.githubusercontent.com/funnotbun/funnotbun.github.io/main/data/species/species.h"

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


def main():
    print(f"Fetching {SPECIES_H_URL} ...")
    data = urllib.request.urlopen(SPECIES_H_URL).read().decode()

    entries = {}
    for m in re.finditer(r"#define\s+SPECIES_(\w+)\s+0x([0-9A-Fa-f]+)", data):
        name = m.group(1)
        num = int(m.group(2), 16)
        if name in ("NONE", "EGG"):
            continue
        # Some IDs have duplicate defines (e.g. FARFETCHED and FARFETCHD both = 0x53)
        # Keep the first one encountered
        if num not in entries:
            entries[num] = name

    print(f"Parsed {len(entries)} species entries (max ID: {max(entries.keys())} = 0x{max(entries.keys()):X})")

    # Build display names
    names = {}
    for num, define_name in sorted(entries.items()):
        names[num] = to_display(define_name)

    # Save intermediate JSON
    out_json = Path("data/rr_species.json")
    with open(out_json, "w") as f:
        json.dump({str(k): v for k, v in sorted(names.items())}, f, indent=2)
    print(f"Saved {len(names)} names to {out_json}")

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

    # Now generate the SPECIES_NAMES dict for pokemon_data.py
    print(f"\nGenerating SPECIES_NAMES dict with {len(names)} entries...")
    lines = ["# RR 4.1 species names — generated from funnotbun/funnotbun.github.io species.h"]
    lines.append("# DO NOT EDIT MANUALLY. Regenerate with: python tools/gen_rr_species.py")
    lines.append(f"# Total: {len(names)} species (max ID: {max(names.keys())})")
    lines.append("SPECIES_NAMES = {")
    for num in sorted(names.keys()):
        lines.append(f"    {num}: {names[num]!r},")
    lines.append("}")

    # Write to a temp file for review
    out_py = Path("data/rr_species_names.py")
    with open(out_py, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"Wrote Python dict to {out_py}")
    print("Copy SPECIES_NAMES dict into server/pokemon_data.py to apply.")


if __name__ == "__main__":
    main()
