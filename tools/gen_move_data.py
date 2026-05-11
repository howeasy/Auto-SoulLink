#!/usr/bin/env python3
"""Generate move data dicts for server/move_data.py.

Sources:
  RR moves:   funnotbun/funnotbun.github.io/data/moves/battle_moves.c
  RR names:   funnotbun/funnotbun.github.io/data/moves/attack_name_table long.string
  RR species: funnotbun/funnotbun.github.io/data/species/species.h  (for MOVE_* enum)
  Vanilla:    pret/pokefirered (decapitalization branch) move data

Usage:
    python tools/gen_move_data.py

Outputs server/move_data.py with RR_MOVE_NAMES, RR_MOVE_DATA, VANILLA_MOVE_NAMES,
and VANILLA_MOVE_DATA dicts.
"""

import os
import re
import sys
import urllib.request

# ── URLs ───────────────────────────────────────────────────────────────────────

_FUNNOTBUN = "https://raw.githubusercontent.com/funnotbun/funnotbun.github.io/main"

BATTLE_MOVES_URL = f"{_FUNNOTBUN}/data/moves/battle_moves.c"
MOVE_NAMES_URL = f"{_FUNNOTBUN}/data/moves/attack_name_table%20long.string"

# The MOVE_* enum defines are in the CFRU defines_battle.h,
# but funnotbun doesn't ship that directly. The move IDs are implicit
# in the order of the [MOVE_*] entries in battle_moves.c.
# We parse them from the battle_moves.c array index labels.

_PRET = "https://raw.githubusercontent.com/pret/pokefirered/master"

VANILLA_MOVES_URL = f"{_PRET}/src/data/battle_moves.h"
VANILLA_NAMES_URL = f"{_PRET}/src/data/text/move_names.h"

# ── Constants ──────────────────────────────────────────────────────────────────

# Gen III type byte values (same in vanilla and CFRU)
TYPE_MAP = {
    "TYPE_NORMAL": 0, "TYPE_FIGHTING": 1, "TYPE_FLYING": 2,
    "TYPE_POISON": 3, "TYPE_GROUND": 4, "TYPE_ROCK": 5,
    "TYPE_BUG": 6, "TYPE_GHOST": 7, "TYPE_STEEL": 8,
    "TYPE_MYSTERY": 9, "TYPE_FIRE": 10, "TYPE_WATER": 11,
    "TYPE_GRASS": 12, "TYPE_ELECTRIC": 13, "TYPE_PSYCHIC": 14,
    "TYPE_ICE": 15, "TYPE_DRAGON": 16, "TYPE_DARK": 17,
    "TYPE_FAIRY": 18, "TYPE_ROOSTLESS": 19, "TYPE_STELLAR": 20,
}

# CFRU split constants
SPLIT_MAP = {
    "SPLIT_PHYSICAL": 0,
    "SPLIT_SPECIAL": 1,
    "SPLIT_STATUS": 2,
}

# Vanilla Gen 3 has no physical/special split — categorized by type.
# Types whose moves are Special in Gen 1-3:
VANILLA_SPECIAL_TYPES = frozenset({
    10, 11, 12, 13, 14, 15, 16, 17,  # Fire, Water, Grass, Electric, Psychic, Ice, Dragon, Dark
})

SPLIT_NAMES = {0: "Physical", 1: "Special", 2: "Status"}


def fetch(url: str) -> str:
    print(f"  Fetching {url.split('/')[-1]}...")
    with urllib.request.urlopen(url) as resp:
        return resp.read().decode("utf-8")


# ── RR move data parsing ──────────────────────────────────────────────────────

def parse_rr_battle_moves(text: str) -> dict[int, dict]:
    """Parse gBattleMoves[] from battle_moves.c.

    Returns {move_id: {type, power, accuracy, pp, split}} indexed by
    sequential position in the array.
    """
    # First pass: extract all MOVE_* enum names in order and build name→id map
    # Format: [MOVE_FOO] = \n { \n .field = VALUE, ... }
    move_pattern = re.compile(r'\[MOVE_(\w+)\]\s*=')

    # We parse each [MOVE_FOO] = { ... } block
    results: dict[str, dict] = {}
    current_move = None
    current_data: dict = {}
    move_order: list[str] = []

    for line in text.splitlines():
        line = line.strip()

        # Match start of a move entry: [MOVE_FOO] = (with { possibly on next line)
        m = move_pattern.match(line)
        if m:
            # Save previous if any
            if current_move and current_data:
                results[current_move] = current_data
            current_move = m.group(1)
            current_data = {}
            if current_move not in [mo for mo in move_order]:
                move_order.append(current_move)
            continue

        if current_move and '.' in line:
            # Parse .field = VALUE lines
            fm = re.match(r'\.(\w+)\s*=\s*(.+?)[\s,]*$', line)
            if fm:
                field = fm.group(1)
                value = fm.group(2).strip().rstrip(',')
                if field == "type":
                    current_data["type"] = TYPE_MAP.get(value, 9)
                elif field == "power":
                    try:
                        current_data["power"] = int(value)
                    except ValueError:
                        current_data["power"] = 0
                elif field == "accuracy":
                    try:
                        current_data["accuracy"] = int(value)
                    except ValueError:
                        current_data["accuracy"] = 0
                elif field == "pp":
                    try:
                        current_data["pp"] = int(value)
                    except ValueError:
                        current_data["pp"] = 0
                elif field == "split":
                    current_data["split"] = SPLIT_MAP.get(value, 0)

    # Save last entry
    if current_move and current_data:
        results[current_move] = current_data

    # Build ID-indexed dict: move_order gives the sequential ID
    # MOVE_NONE = 0, MOVE_POUND = 1, etc.
    id_results: dict[int, dict] = {}
    for idx, name in enumerate(move_order):
        if name in results:
            id_results[idx] = results[name]

    return id_results


def parse_rr_move_names(text: str) -> dict[int, str]:
    """Parse attack_name_table long.string.

    Names are in sequential order: #org @NAME_LONG_* followed by the name on
    the next line. Returns {move_id: name}.
    """
    names: dict[int, str] = {}
    move_id = 0
    expect_name = False

    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("MAX_LENGTH") or line.startswith("FILL_FF"):
            continue
        if line.startswith("#org @"):
            expect_name = True
            continue
        if expect_name:
            names[move_id] = line
            move_id += 1
            expect_name = False

    return names


# ── Vanilla move data parsing ─────────────────────────────────────────────────

def parse_vanilla_battle_moves(text: str) -> dict[int, dict]:
    """Parse vanilla gBattleMoves[] from pret/pokefirered.

    The vanilla format uses [MOVE_*] = { ... } blocks with same fields.
    Vanilla has no .split field — we infer it from type.
    """
    move_pattern = re.compile(r'\[MOVE_(\w+)\]\s*=')
    results: dict[str, dict] = {}
    current_move = None
    current_data: dict = {}
    move_order: list[str] = []

    for line in text.splitlines():
        line = line.strip()
        m = move_pattern.match(line)
        if m:
            if current_move and current_data:
                results[current_move] = current_data
            current_move = m.group(1)
            current_data = {}
            if current_move not in move_order:
                move_order.append(current_move)
            continue

        if current_move and '.' in line:
            fm = re.match(r'\.(\w+)\s*=\s*(.+?)[\s,]*$', line)
            if fm:
                field = fm.group(1)
                value = fm.group(2).strip().rstrip(',')
                if field == "type":
                    type_id = TYPE_MAP.get(value, 9)
                    current_data["type"] = type_id
                    # Infer split from type for vanilla Gen 3
                    if type_id in VANILLA_SPECIAL_TYPES:
                        current_data["split"] = 1  # Special
                    else:
                        current_data["split"] = 0  # Physical
                elif field == "power":
                    try:
                        current_data["power"] = int(value)
                    except ValueError:
                        current_data["power"] = 0
                elif field == "accuracy":
                    try:
                        current_data["accuracy"] = int(value)
                    except ValueError:
                        current_data["accuracy"] = 0
                elif field == "pp":
                    try:
                        current_data["pp"] = int(value)
                    except ValueError:
                        current_data["pp"] = 0

    if current_move and current_data:
        results[current_move] = current_data

    # Fix: status moves (power == 0) should have split = Status
    for name, data in results.items():
        if data.get("power", 0) == 0 and data.get("type", 0) != 9:
            data["split"] = 2  # Status

    id_results: dict[int, dict] = {}
    for idx, name in enumerate(move_order):
        if name in results:
            id_results[idx] = results[name]

    return id_results


def parse_vanilla_move_names(text: str) -> dict[int, str]:
    """Parse vanilla move names from pret/pokefirered move_names.h.

    Format: [MOVE_*] = _("Name"),
    """
    names: dict[int, str] = {}
    move_order: list[str] = []
    name_map: dict[str, str] = {}

    for line in text.splitlines():
        m = re.match(r'\s*\[MOVE_(\w+)\]\s*=\s*_\("([^"]+)"\)', line)
        if m:
            move_enum = m.group(1)
            name = m.group(2)
            if move_enum not in move_order:
                move_order.append(move_enum)
            name_map[move_enum] = name.title()

    for idx, name in enumerate(move_order):
        if name in name_map:
            names[idx] = name_map[name]

    return names


# ── Output generation ─────────────────────────────────────────────────────────

def write_module(
    rr_names: dict[int, str],
    rr_data: dict[int, dict],
    vanilla_names: dict[int, str],
    vanilla_data: dict[int, dict],
    output_path: str,
):
    """Write server/move_data.py with all move data dicts."""

    lines = [
        '"""',
        'server/move_data.py — Generated move data for Gen 3 (RR + vanilla FRLG).',
        '',
        'Generated by tools/gen_move_data.py — DO NOT EDIT MANUALLY.',
        '',
        'RR data: funnotbun/funnotbun.github.io (battle_moves.c, attack_name_table)',
        'Vanilla data: pret/pokefirered (battle_moves.h, move_names.h)',
        '',
        'Split values: 0 = Physical, 1 = Special, 2 = Status',
        '"""',
        '',
        '',
    ]

    # RR move names
    lines.append(f'RR_MOVE_NAMES: dict[int, str] = {{')
    for mid in sorted(rr_names.keys()):
        name = rr_names[mid].replace("'", "\\'")
        lines.append(f"    {mid}: '{name}',")
    lines.append('}')
    lines.append('')

    # RR move data
    lines.append('# {move_id: {"type": int, "power": int, "accuracy": int, "pp": int, "split": int}}')
    lines.append(f'RR_MOVE_DATA: dict[int, dict] = {{')
    for mid in sorted(rr_data.keys()):
        d = rr_data[mid]
        lines.append(
            f"    {mid}: {{"
            f"'type': {d.get('type', 9)}, "
            f"'power': {d.get('power', 0)}, "
            f"'accuracy': {d.get('accuracy', 0)}, "
            f"'pp': {d.get('pp', 0)}, "
            f"'split': {d.get('split', 0)}"
            f"}},"
        )
    lines.append('}')
    lines.append('')

    # Vanilla move names
    lines.append(f'VANILLA_MOVE_NAMES: dict[int, str] = {{')
    for mid in sorted(vanilla_names.keys()):
        name = vanilla_names[mid].replace("'", "\\'")
        lines.append(f"    {mid}: '{name}',")
    lines.append('}')
    lines.append('')

    # Vanilla move data
    lines.append('# Vanilla Gen 3: split inferred from type (no physical/special split in-game)')
    lines.append(f'VANILLA_MOVE_DATA: dict[int, dict] = {{')
    for mid in sorted(vanilla_data.keys()):
        d = vanilla_data[mid]
        lines.append(
            f"    {mid}: {{"
            f"'type': {d.get('type', 9)}, "
            f"'power': {d.get('power', 0)}, "
            f"'accuracy': {d.get('accuracy', 0)}, "
            f"'pp': {d.get('pp', 0)}, "
            f"'split': {d.get('split', 0)}"
            f"}},"
        )
    lines.append('}')
    lines.append('')

    # Convenience functions
    lines.extend([
        '',
        'def move_name(move_id: int, is_rr: bool = False) -> str:',
        '    """Return display name for a move ID."""',
        '    if is_rr:',
        '        return RR_MOVE_NAMES.get(move_id, "")',
        '    return VANILLA_MOVE_NAMES.get(move_id, "")',
        '',
        '',
        'def move_data(move_id: int, is_rr: bool = False) -> dict | None:',
        '    """Return move data dict {type, power, accuracy, pp, split} or None."""',
        '    if is_rr:',
        '        return RR_MOVE_DATA.get(move_id)',
        '    return VANILLA_MOVE_DATA.get(move_id)',
        '',
    ])

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main():
    output_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "server", "move_data.py"
    )

    print("=== Generating RR move data ===")
    rr_moves_text = fetch(BATTLE_MOVES_URL)
    rr_data = parse_rr_battle_moves(rr_moves_text)
    print(f"  Parsed {len(rr_data)} RR move entries")

    rr_names_text = fetch(MOVE_NAMES_URL)
    rr_names = parse_rr_move_names(rr_names_text)
    print(f"  Parsed {len(rr_names)} RR move names")

    print("\n=== Generating vanilla FRLG move data ===")
    try:
        vanilla_moves_text = fetch(VANILLA_MOVES_URL)
        vanilla_data = parse_vanilla_battle_moves(vanilla_moves_text)
        print(f"  Parsed {len(vanilla_data)} vanilla move entries")
    except Exception as e:
        print(f"  Warning: failed to fetch vanilla moves ({e}), using empty")
        vanilla_data = {}

    try:
        vanilla_names_text = fetch(VANILLA_NAMES_URL)
        vanilla_names = parse_vanilla_move_names(vanilla_names_text)
        print(f"  Parsed {len(vanilla_names)} vanilla move names")
    except Exception as e:
        print(f"  Warning: failed to fetch vanilla names ({e}), using empty")
        vanilla_names = {}

    print(f"\n=== Writing {output_path} ===")
    write_module(rr_names, rr_data, vanilla_names, vanilla_data, output_path)

    # Summary stats
    print(f"\nDone!")
    print(f"  RR:      {len(rr_names)} names, {len(rr_data)} entries")
    print(f"  Vanilla: {len(vanilla_names)} names, {len(vanilla_data)} entries")

    # Sanity check: verify a few well-known moves
    checks = {
        1: ("Pound", 0, 40, 35, 0),      # MOVE_POUND: Normal, 40 power, 35 pp, Physical
        7: ("Fire Punch", 10, 75, 15, 0), # MOVE_FIREPUNCH: Fire, 75 power, 15 pp, Physical
    }
    ok = True
    for mid, (exp_name, exp_type, exp_power, exp_pp, exp_split) in checks.items():
        got_name = rr_names.get(mid, "?")
        got_data = rr_data.get(mid, {})
        if got_name != exp_name:
            print(f"  ⚠ Move {mid}: expected name '{exp_name}', got '{got_name}'")
            ok = False
        if got_data.get("type") != exp_type:
            print(f"  ⚠ Move {mid}: expected type {exp_type}, got {got_data.get('type')}")
            ok = False
        if got_data.get("power") != exp_power:
            print(f"  ⚠ Move {mid}: expected power {exp_power}, got {got_data.get('power')}")
            ok = False
        if got_data.get("pp") != exp_pp:
            print(f"  ⚠ Move {mid}: expected pp {exp_pp}, got {got_data.get('pp')}")
            ok = False
    if ok:
        print("  ✓ Sanity checks passed")
    else:
        print("  ✗ Some sanity checks failed — review output")


if __name__ == "__main__":
    main()
