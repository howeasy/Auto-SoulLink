#!/usr/bin/env python3
"""
gen_gen4_trainers.py — Extract HGSS + Platinum trainer roster data from pret decomps.

Outputs:
  data/games/gen4_hgsspt/trainers_hgss.json
  data/games/gen4_hgsspt/trainers_pt.json

Each file has the shape:
  {
    "trainers": { "<id>": {"name": "Falkner", "class": 13}, ... },
    "classes":  { "<id>": "Gym Leader", ... },
  }

Source: pret/pokeheartgold data/trainers/trainer_data.h + trainer_classes.h.
Same files exist under pret/pokeplatinum. Both repos store names in pret's
Gen IV custom 16-bit charcode (NOT standard Unicode); this script decodes those
to ASCII using the mapping in lua/memory_nds.lua readTrainerName.

Usage:
  python tools/gen_gen4_trainers.py \
      --pret-hgss /path/to/pokeheartgold \
      --pret-pt   /path/to/pokeplatinum

Without --pret-* args, the script writes empty-but-valid stub JSONs containing
only the gym leader / E4 / champion / rival seed names. The adapter falls back
to ("", "") for any trainer ID not in the table, so a sparse table is safe.

Seed data (manually entered): Gym Leaders, Elite Four, Champion, Rivals.
Full table requires running with --pret-* paths.
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

# ── Manual seed: gym leaders + E4 + champion + rival names ─────────────────────
# Trainer IDs are PLACEHOLDERS — must be confirmed against pret trainer_data.h
# when generating the full table. The adapter looks up trainers_<game>.json by
# string-converted ID; a missing entry returns ("", "") cleanly.
#
# These names render correctly in stream overlays even without IDs, because the
# generator falls back to "GYM_LEADER_FALKNER" style class+name strings when no
# trainer_id mapping exists. The IDs are required only for the live RAM ID-based
# lookup.

# Format: [(trainer_id, name, class_id), ...]
# Class IDs match pret's class enum order (GymLeader, EliteFour, Champion, etc.)
HGSS_SEED = [
    # Johto Gym Leaders (IDs from pret trainer_data.h — placeholders, run script with --pret-hgss to confirm)
    # (id,  name,        class)
    (None, "Falkner",     "Leader"),
    (None, "Bugsy",       "Leader"),
    (None, "Whitney",     "Leader"),
    (None, "Morty",       "Leader"),
    (None, "Chuck",       "Leader"),
    (None, "Jasmine",     "Leader"),
    (None, "Pryce",       "Leader"),
    (None, "Clair",       "Leader"),
    # Johto Elite Four
    (None, "Will",        "Elite Four"),
    (None, "Koga",        "Elite Four"),
    (None, "Bruno",       "Elite Four"),
    (None, "Karen",       "Elite Four"),
    # Johto Champion
    (None, "Lance",       "Champion"),
    # Kanto Gym Leaders (HGSS-specific)
    (None, "Brock",       "Leader"),
    (None, "Misty",       "Leader"),
    (None, "Lt. Surge",   "Leader"),
    (None, "Erika",       "Leader"),
    (None, "Janine",      "Leader"),
    (None, "Sabrina",     "Leader"),
    (None, "Blaine",      "Leader"),
    (None, "Blue",        "Leader"),
    # Mt. Silver post-game
    (None, "Red",         "Pokémon Trainer"),
    # Rival
    (None, "Silver",      "Rival"),
]

PLATINUM_SEED = [
    # Sinnoh Gym Leaders
    (None, "Roark",       "Leader"),
    (None, "Gardenia",    "Leader"),
    (None, "Maylene",     "Leader"),
    (None, "Crasher Wake","Leader"),
    (None, "Fantina",     "Leader"),
    (None, "Byron",       "Leader"),
    (None, "Candice",     "Leader"),
    (None, "Volkner",     "Leader"),
    # Sinnoh Elite Four
    (None, "Aaron",       "Elite Four"),
    (None, "Bertha",      "Elite Four"),
    (None, "Flint",       "Elite Four"),
    (None, "Lucian",      "Elite Four"),
    # Sinnoh Champion
    (None, "Cynthia",     "Champion"),
    # Rival
    (None, "Barry",       "Rival"),
    # Antagonists (Galactic Bosses)
    (None, "Mars",        "Galactic Commander"),
    (None, "Jupiter",     "Galactic Commander"),
    (None, "Saturn",      "Galactic Commander"),
    (None, "Charon",      "Galactic Boss"),
    (None, "Cyrus",       "Galactic Boss"),
]


def build_stub(seed):
    """Build a sparse trainer table from manually-seeded named trainers.
    Since we don't have real IDs, we just emit the classes map and an empty
    trainers map. The adapter falls back to "" when ID lookup misses."""
    # Collect unique class names → arbitrary 1-based IDs (stable order).
    classes = {}
    next_class_id = 1
    for _, _name, cls in seed:
        if cls not in classes:
            classes[next_class_id] = cls
            next_class_id += 1

    # Reverse map for trainers
    cls_lookup = {v: k for k, v in classes.items()}

    trainers = {}
    # If a seed entry has no ID, we can't reverse-lookup from RAM. We still emit
    # the entry under a synthetic key (negative IDs) so the data is discoverable.
    synthetic_id = -1
    for tid, name, cls in seed:
        key = str(tid) if tid is not None else f"seed_{abs(synthetic_id)}"
        if tid is None:
            synthetic_id -= 1
        trainers[key] = {"name": name, "class": cls_lookup[cls]}

    return {
        "trainers": trainers,
        "classes":  {str(k): v for k, v in classes.items()},
    }


def decode_pret_charcode(raw_bytes):
    """Decode pret's Gen IV custom 16-bit charcode to ASCII.

    Matches lua/memory_nds.lua readTrainerName:
      289..298 → '0'..'9'
      299..324 → 'A'..'Z'
      325..350 → 'a'..'z'
      478=space  446=hyphen  435=apostrophe  430=period
      0xFFFF / 0x0000 = EOS
    """
    out = []
    for i in range(0, len(raw_bytes), 2):
        if i + 1 >= len(raw_bytes):
            break
        c = raw_bytes[i] | (raw_bytes[i+1] << 8)
        if c in (0x0000, 0xFFFF):
            break
        if 289 <= c <= 298:
            out.append(chr(ord('0') + c - 289))
        elif 299 <= c <= 324:
            out.append(chr(ord('A') + c - 299))
        elif 325 <= c <= 350:
            out.append(chr(ord('a') + c - 325))
        elif c == 478:
            out.append(' ')
        elif c == 446:
            out.append('-')
        elif c == 435:
            out.append("'")
        elif c == 430:
            out.append('.')
    return ''.join(out)


def parse_pret_trainers(pret_path: Path):
    """Parse pret's data/trainers/trainer_data.h + trainer_classes.h.

    pret stores trainer_data.h as a C array of struct TrainerData entries, each
    with: { class:u8, sprite_idx:u8, gender:u8, double_battle:u8, ai_flags:u32,
            party_size:u8, name:u16[8], items:u16[4], ... } and the class enum
    in trainer_classes.h.

    Returns (trainers_dict, classes_dict) ready for JSON serialization. Returns
    (None, None) if the pret repo can't be read.
    """
    trainer_h = pret_path / "data" / "trainers" / "trainer_data.h"
    class_h   = pret_path / "data" / "trainers" / "trainer_classes.h"
    if not trainer_h.exists() or not class_h.exists():
        print(f"  ⚠️  pret files not found under {pret_path}/data/trainers/")
        return None, None

    # Class enum: extract CLASS_FOO = N pairs.
    class_text = class_h.read_text(encoding="utf-8", errors="ignore")
    classes = {}
    # pret typically uses enum entries like: CLASS_LEADER,  // 13
    # or an enum block where order = ID. Use a permissive parser.
    next_id = 0
    for line in class_text.splitlines():
        m = re.match(r'\s*CLASS_(\w+)\s*(?:=\s*(\d+))?', line)
        if m:
            cid = int(m.group(2)) if m.group(2) else next_id
            classes[cid] = m.group(1).replace("_", " ").title()
            next_id = cid + 1

    # trainer_data.h: extract { .name = _("Foo"), .class = TRAINER_CLASS_LEADER, ... }
    trainer_text = trainer_h.read_text(encoding="utf-8", errors="ignore")
    trainers = {}
    # Each TRAINER_DATA(...) macro or struct member; pret uses something like:
    #   [TRAINER_FALKNER] = { .name = _("FALKNER"), .class = TRAINER_CLASS_LEADER, ... }
    pat = re.compile(
        r'\[TRAINER_(\w+)\]\s*=\s*\{[^}]*\.name\s*=\s*_\(\s*"([^"]+)"\s*\)'
        r'[^}]*\.class\s*=\s*TRAINER_CLASS_(\w+)',
        re.DOTALL
    )
    seen_index = 0
    trainer_enum = {}
    # First pass: extract trainer enum from trainer.h-style definitions.
    # We need to map TRAINER_FALKNER → integer ID. pret puts the enum in
    # include/constants/trainer.h or data/trainers/trainer_data.h header.
    # For pragmatic parsing, scan all enum-style assignments.
    for m in re.finditer(r'TRAINER_(\w+)\s*=\s*(\d+)', trainer_text):
        trainer_enum[m.group(1)] = int(m.group(2))

    # Second pass: extract trainer data blocks.
    for m in pat.finditer(trainer_text):
        enum_name = m.group(1)
        name = m.group(2)
        cls_name = m.group(3)
        tid = trainer_enum.get(enum_name)
        if tid is None:
            tid = seen_index
            seen_index += 1
        # Map class name back to ID via classes dict.
        cls_id = None
        for cid, cname in classes.items():
            if cname.upper().replace(" ", "_") == cls_name:
                cls_id = cid
                break
        if cls_id is None:
            cls_id = 0
        trainers[str(tid)] = {"name": name, "class": cls_id}

    return trainers, {str(k): v for k, v in classes.items()}


def main():
    ap = argparse.ArgumentParser(description="Generate Gen 4 trainer JSON files")
    ap.add_argument("--pret-hgss", help="Path to cloned pret/pokeheartgold")
    ap.add_argument("--pret-pt",   help="Path to cloned pret/pokeplatinum")
    ap.add_argument("--output-dir", default=None,
                    help="Output dir (default: data/games/gen4_hgsspt)")
    args = ap.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    out_dir = Path(args.output_dir) if args.output_dir else (
        repo_root / "data" / "games" / "gen4_hgsspt")
    out_dir.mkdir(parents=True, exist_ok=True)

    for game, seed, pret_arg, fname in [
        ("HGSS",     HGSS_SEED,     args.pret_hgss, "trainers_hgss.json"),
        ("Platinum", PLATINUM_SEED, args.pret_pt,   "trainers_pt.json"),
    ]:
        out = None
        if pret_arg:
            print(f"Parsing {game} from {pret_arg}...")
            trainers, classes = parse_pret_trainers(Path(pret_arg))
            if trainers and classes:
                out = {"trainers": trainers, "classes": classes}
                print(f"  → {len(trainers)} trainers, {len(classes)} classes")
        if out is None:
            print(f"Writing stub for {game} (no pret path provided).")
            out = build_stub(seed)
        out_path = out_dir / fname
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2, ensure_ascii=False)
            f.write("\n")
        print(f"  Wrote {out_path}")


if __name__ == "__main__":
    sys.exit(main())
