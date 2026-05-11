#!/usr/bin/env python3
"""
tools/gen_rr_encounters.py — Generate RR encounter tables from funnotbun's wild_encounter_tables.c.

Usage:
    python tools/gen_rr_encounters.py

Fetches wild_encounter_tables.c from funnotbun's GitHub repository and outputs:
    data/games/gen3_frlge/rr_encounters.json

Format:
    {area_id: {method: [{name, species_id, rate, min_level, max_level}]}}

Methods: Day, Night, Surfing, Rock Smash, Old Rod, Good Rod, Super Rod
(Raid encounters are excluded.)

Encounter rates match funnotbun's regexLocations.js returnRarity() logic.
"""

import json
import os
import re
import sys
import urllib.request

SOURCE_URL = (
    "https://raw.githubusercontent.com/funnotbun/funnotbun.github.io"
    "/main/data/locations/wild_encounter_tables.c"
)

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_DATA_DIR = os.path.normpath(os.path.join(_SCRIPT_DIR, "..", "data", "games", "gen3_frlge"))
OUTPUT_PATH = os.path.join(_DATA_DIR, "rr_encounters.json")
AREA_MAP_PATH = os.path.join(_DATA_DIR, "area_map.json")
SPECIES_PATH = os.path.join(_DATA_DIR, "rr_species.json")

# ── Method label overrides ────────────────────────────────────────────────────

_METHOD_ICON = {
    "Day":        "☀ Day",
    "Night":      "🌙 Night",
    "Surfing":    "🌊 Surfing",
    "Rock Smash": "🪨 Rock Smash",
    "Old Rod":    "🎣 Old Rod",
    "Good Rod":   "🎣 Good Rod",
    "Super Rod":  "🎣 Super Rod",
}

# Preferred display order for methods
_METHOD_ORDER = ["Day", "Night", "Surfing", "Old Rod", "Good Rod", "Super Rod", "Rock Smash"]


# ── Species constant overrides (names that can't be derived mechanically) ────

# Maps SPECIES_xxx constant (without prefix) to correct display / lookup name.
# These are species where the C constant name doesn't match rr_species.json due
# to special characters (♀, ♂, apostrophes, hyphens, parentheses).
_SPECIES_CONST_OVERRIDES: dict[str, str] = {
    "NIDORAN_F":            "Nidoran♀",
    "NIDORAN_M":            "Nidoran♂",
    "FARFETCHD":            "Farfetch'd",
    "SIRFETCHD":            "Sirfetch'd",
    "MIME_JR":              "Mime Jr.",
    "MR_MIME_G":            "Mr Mime-Galar",
    "KOMMO_O":              "Kommo-o",
    "TYPE_NULL":            "Type: Null",
    "MINIOR_SHIELD":        "Minior (Shield)",
    "BASCULIN_RED":         "Basculin (Red)",
    "BASCULIN_BLUE":        "Basculin (Blue)",
    "ALCREMIE_STRAWBERRY":  "Alcremie (Strawberry)",
    "GIMMIGHOUL_CHEST":     "Gimmighoul (Chest)",
}


# ── Parsing helpers (mirrors regexLocations.js logic) ────────────────────────

def _zone_name_from_struct(struct_part: str) -> str:
    """Convert camelCase struct name to spaced zone name.

    'MtMoon1F' → 'Mt Moon 1 F'
    'ViridianForest' → 'Viridian Forest'
    Mirrors JS: name.replace(/([A-Z])/g, " $1").replace(/(\\d+)/g, " $1").trim()
    """
    s = re.sub(r"([A-Z])", r" \1", struct_part)
    s = re.sub(r"(\d+)", r" \1", s)
    return s.strip()


def _replace_method(raw_method: str, slot_index: int) -> str:
    """Map raw C struct method suffix to canonical display method.

    Mirrors replaceMethodString() from regexLocations.js.
    """
    if re.search(r"fish", raw_method, re.I):
        if slot_index <= 1:
            return "Old Rod"
        elif slot_index <= 4:
            return "Good Rod"
        else:
            return "Super Rod"
    elif re.search(r"surf", raw_method, re.I):
        return "Surfing"
    elif re.search(r"smash", raw_method, re.I):
        return "Rock Smash"
    elif re.search(r"night", raw_method, re.I):
        return "Night"
    elif re.search(r"LandMons", raw_method, re.I):
        # Matches Day, LandMonsDay, PostGameLandMons, etc.
        return "Day"
    return raw_method  # pass-through for unrecognised methods


def _encounter_rate(method: str, slot_index: int) -> int:
    """Return encounter rate % for a given method and slot index.

    Mirrors returnRarity() from regexLocations.js.
    Rates for each method sum to 100 per encounter slot set.
    """
    if method in ("Day", "Night"):
        if slot_index <= 1:   return 20
        elif slot_index <= 5: return 10
        elif slot_index <= 7: return 5
        elif slot_index <= 9: return 4
        else:                 return 1   # slots 10–11
    elif method in ("Surfing", "Rock Smash"):
        return [60, 30, 5, 4, 1][slot_index] if slot_index < 5 else 100
    elif method == "Old Rod":
        return [70, 30][slot_index] if slot_index < 2 else 100
    elif method == "Good Rod":
        return [60, 20, 20][slot_index - 2] if 2 <= slot_index <= 4 else 100
    elif method == "Super Rod":
        idx = slot_index - 5
        return [40, 40, 15, 4, 1][idx] if 0 <= idx < 5 else 100
    return 100


def _species_display_name(const: str) -> str:
    """Convert SPECIES constant to a human-readable name.

    SPECIES_BIDOOF → 'Bidoof'
    SPECIES_ZIGZAGOON_G → 'Zigzagoon G'
    SPECIES_DEERLING_SUMMER → 'Deerling Summer'
    Special cases (♀/♂, apostrophes, etc.) handled via _SPECIES_CONST_OVERRIDES.
    """
    key = const.replace("SPECIES_", "")
    if key in _SPECIES_CONST_OVERRIDES:
        return _SPECIES_CONST_OVERRIDES[key]
    return " ".join(part.title() for part in key.split("_"))


# ── Area ID mapping ───────────────────────────────────────────────────────────

def _build_known_area_ids(area_map_path: str) -> set[str]:
    """Load all area_ids from area_map.json."""
    with open(area_map_path, encoding="utf-8") as f:
        area_map = json.load(f)
    return set(area_map.values())


def _zone_to_area_id(zone: str, known_ids: set[str]) -> str | None:
    """Map a zone display name to an area_id.

    Strategy:
    1. Direct lowercased match ("Route 1" → "route_1").
    2. Strip trailing floor suffix (_N_f, _Nf) for multi-floor dungeons
       ("Mt Moon 1 F" → "mt_moon_1" → "mt_moon").
    3. Strip basement floors (_b_N_f patterns like "Digletts Cave B 1 F").
    4. Strip trailing location qualifiers ("North Entrance", "Exterior", etc.)
    5. Strip trailing single-letter sub-zone suffix ("Route21A" → "route_21").
    Returns None if no matching area_id is found.
    """
    simple = zone.lower().replace(" ", "_")
    if simple in known_ids:
        return simple

    # Manual aliases for zones whose names diverge from area_ids
    _ZONE_ALIASES = {
        "three_island_port": "three_isle_port",
        "s_s_anne": "ss_anne",
        "pkmn_tower": "pokemon_tower",
    }
    if simple in _ZONE_ALIASES and _ZONE_ALIASES[simple] in known_ids:
        return _ZONE_ALIASES[simple]

    # Strip trailing _<digit>_f or _<digit>f (floor patterns)
    s1 = re.sub(r"_\d+_f$", "", simple)
    if s1 and s1 != simple and s1 in known_ids:
        return s1

    # Strip trailing _<digit+> (bare number suffix) then optionally _f
    s2 = re.sub(r"(_\d+)+$", "", simple)
    if s2 and s2 != simple and s2 in known_ids:
        return s2

    # Try stripping trailing _f without digits ("Victory Road F" edge case)
    s3 = re.sub(r"_f$", "", simple)
    if s3 and s3 != simple and s3 in known_ids:
        return s3

    # Strip trailing single-letter sub-zone suffix ("Route21A" → "route_21_a" → "route_21")
    s4 = re.sub(r"_[a-z]$", "", simple)
    if s4 and s4 != simple and s4 in known_ids:
        return s4

    # Strip basement/floor pattern: _b_<digit>_f ("Digletts Cave B 1 F" → "digletts_cave")
    s5 = re.sub(r"_b_?\d+_?f?$", "", simple)
    if s5 and s5 != simple and s5 in known_ids:
        return s5

    # Strip trailing location qualifiers (north_entrance, exterior, etc.)
    for suffix in ("_north_entrance", "_south_entrance", "_exterior", "_interior", "_entrance"):
        if simple.endswith(suffix):
            s6 = simple[:-len(suffix)]
            if s6 in known_ids:
                return s6

    return None


# ── Species ID lookup ─────────────────────────────────────────────────────────

def _build_name_to_id(species_path: str) -> dict[str, int]:
    """Build reverse mapping from species name (lowercase) to RR internal ID."""
    with open(species_path, encoding="utf-8") as f:
        rr_species = json.load(f)
    return {v.lower(): int(k) for k, v in rr_species.items()}


def _resolve_species_id(const: str, name_to_id: dict[str, int]) -> int:
    """Attempt to resolve a SPECIES constant to an RR internal species ID.

    Tries the display name first (which handles overrides for special chars),
    then the base name (first word), as a fallback for form variants.
    Returns 0 if unresolved (e.g. SPECIES_NONE).
    """
    display = _species_display_name(const)
    if display == "None":
        return 0  # SPECIES_NONE placeholder
    sid = name_to_id.get(display.lower(), 0)
    if not sid:
        base = display.split()[0]
        sid = name_to_id.get(base.lower(), 0)
    return sid


# ── Main parser ───────────────────────────────────────────────────────────────

def parse_encounters(
    text: str,
    known_ids: set[str],
    name_to_id: dict[str, int],
) -> dict[str, dict[str, list[dict]]]:
    """Parse wild_encounter_tables.c and return encounter data by area_id.

    Returns:
        {area_id: {method: [{name, species_id, rate, min_level, max_level}]}}
    """
    encounters: dict[str, dict[str, list[dict]]] = {}

    current_area_id: str | None = None
    current_raw_method: str | None = None
    slot_index = 0

    for line in text.splitlines():
        # ── Struct declaration: static const struct WildPokemon gXxx_Yyy[]
        m = re.match(r"\s*static const struct WildPokemon g?(\w+)_(\w+)\s*\[\]", line)
        if m:
            struct_zone_part = m.group(1)
            raw_method = m.group(2)

            # funnotbun JS overrides for RR PostGame slots
            if raw_method == "PostGameLandMons":
                zone_display = "Pokemon Tower 1 F"
            elif raw_method == "PostGameLandMons2":
                zone_display = "Pokemon Tower 2 F"
            else:
                zone_display = _zone_name_from_struct(struct_zone_part)

            area_id = _zone_to_area_id(zone_display, known_ids)
            current_area_id = area_id  # None means "skip this struct"
            current_raw_method = raw_method
            slot_index = 0
            continue

        # Skip lines if current struct has no matching area_id
        if current_area_id is None:
            continue

        # ── Species line: {min_lv, max_lv, SPECIES_XXX}
        species_match = re.search(r"SPECIES_\w+", line)
        if not species_match:
            continue

        const = species_match.group(0)
        canon_method = _replace_method(current_raw_method, slot_index)

        # Skip unrecognised pass-through methods (shouldn't occur in practice)
        if canon_method not in _METHOD_ICON:
            slot_index += 1
            continue

        rate = _encounter_rate(canon_method, slot_index)
        display_name = _species_display_name(const)
        species_id = _resolve_species_id(const, name_to_id)

        lv_match = re.match(r"\s*\{(\d+),\s*(\d+),", line)
        min_lv = int(lv_match.group(1)) if lv_match else 0
        max_lv = int(lv_match.group(2)) if lv_match else 0

        area_data = encounters.setdefault(current_area_id, {})
        method_list = area_data.setdefault(canon_method, [])
        method_list.append({
            "name":       display_name,
            "species_id": species_id,
            "rate":       rate,
            "min_level":  min_lv,
            "max_level":  max_lv,
        })
        slot_index += 1

    # Sort methods in each area by preferred display order
    sorted_encounters: dict[str, dict[str, list[dict]]] = {}
    for area_id, methods in sorted(encounters.items()):
        sorted_methods: dict[str, list[dict]] = {}
        for method in _METHOD_ORDER:
            if method in methods:
                sorted_methods[method] = methods[method]
        # Append any unexpected methods at the end
        for method, entries in methods.items():
            if method not in sorted_methods:
                sorted_methods[method] = entries
        sorted_encounters[area_id] = sorted_methods

    return sorted_encounters


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    print(f"Fetching: {SOURCE_URL}")
    try:
        with urllib.request.urlopen(SOURCE_URL, timeout=30) as resp:
            text = resp.read().decode("utf-8")
    except Exception as exc:
        print(f"ERROR fetching source: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"Loaded {len(text):,} bytes — parsing encounters…")

    known_ids = _build_known_area_ids(AREA_MAP_PATH)
    name_to_id = _build_name_to_id(SPECIES_PATH)

    encounters = parse_encounters(text, known_ids, name_to_id)

    n_areas = len(encounters)
    n_entries = sum(
        len(entries)
        for methods in encounters.values()
        for entries in methods.values()
    )
    print(f"Parsed {n_entries} encounter entries across {n_areas} areas.")

    # Report unresolved species (species_id == 0) for diagnostics
    unresolved: list[str] = []
    for methods in encounters.values():
        for entries in methods.values():
            for e in entries:
                if e["species_id"] == 0 and e["name"] not in unresolved:
                    unresolved.append(e["name"])
    if unresolved:
        print(f"Note: {len(unresolved)} species constants unresolved to ID "
              f"(will display without sprite): {', '.join(sorted(unresolved)[:20])}"
              f"{'…' if len(unresolved) > 20 else ''}")

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(encounters, f, ensure_ascii=False, indent=2)
    print(f"Wrote: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
