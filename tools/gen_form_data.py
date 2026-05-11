#!/usr/bin/env python3
"""Generate form sprite IDs and type data by querying PokeAPI.

Reads SPECIES_NAMES and CFRU_TO_NATIONAL from pokemon_data.py, identifies
alt forms, queries PokeAPI for sprite IDs and types, and outputs Python
dict literals for integration into pokemon_data.py.

Usage:
    python tools/gen_form_data.py
    python tools/gen_form_data.py -o server/pokemon_data.py  # append to file
"""
from __future__ import annotations

import re
import sys
import time

import requests

sys.path.insert(0, ".")
from server.pokemon_data import CFRU_TO_NATIONAL, SPECIES_NAMES

# ── PokeAPI type name → Gen III internal type byte ──────────────────────────
TYPE_NAME_TO_ID: dict[str, int] = {
    "normal": 0, "fighting": 1, "flying": 2, "poison": 3, "ground": 4,
    "rock": 5, "bug": 6, "ghost": 7, "steel": 8, "fire": 10,
    "water": 11, "grass": 12, "electric": 13, "psychic": 14, "ice": 15,
    "dragon": 16, "dark": 17, "fairy": 18,
}


def _to_national(cfru_id: int) -> int:
    if cfru_id <= 251:
        return cfru_id
    return CFRU_TO_NATIONAL.get(cfru_id, cfru_id)


# ── Name-to-PokeAPI conversion ─────────────────────────────────────────────

# Exact overrides for names PokeAPI won't match from our display names.
_POKEAPI_NAME_OVERRIDE: dict[int, str] = {
    # Mega forms
    906: "venusaur-mega", 907: "charizard-mega-x", 908: "charizard-mega-y",
    909: "blastoise-mega", 910: "beedrill-mega", 911: "pidgeot-mega",
    912: "alakazam-mega", 913: "slowbro-mega", 914: "gengar-mega",
    915: "kangaskhan-mega", 916: "pinsir-mega", 917: "gyarados-mega",
    918: "aerodactyl-mega", 919: "mewtwo-mega-x", 920: "mewtwo-mega-y",
    # Hmm, these IDs are wrong — let me skip overrides and derive them
}

# Clear overrides; we'll derive everything programmatically
_POKEAPI_NAME_OVERRIDE.clear()

# Add manual overrides for forms whose names don't match PokeAPI conventions
_POKEAPI_NAME_OVERRIDE = {
    # Calyrex riders
    1210: "calyrex-ice",
    1211: "calyrex-shadow",
    # Darmanitan-Galar
    1230: "darmanitan-galar-standard",
    # Basculin forms
    603: "basculin-red-striped",
    736: "basculin-blue-striped",
    1243: "basculin-white-striped",
    # Burmy/Wormadam sandy/trash → PokeAPI uses "cloak" suffix
    707: "wormadam-sandy",  # PokeAPI: wormadam-sandy
    708: "wormadam-trash",  # These may not exist separately in PokeAPI
    # Shellos/Gastrodon
    711: "shellos-east",
    712: "gastrodon-east",
    # Toxtricity Gmax
    1284: "toxtricity-gmax",
    # Urshifu Gmax
    1292: "urshifu-single-strike-gmax",
    1293: "urshifu-rapid-strike-gmax",
    # Tauros Paldea
    1409: "tauros-paldea-combat-breed",
    1410: "tauros-paldea-blaze-breed",
    1411: "tauros-paldea-aqua-breed",
    # Ogerpon masks
    1423: "ogerpon-wellspring-mask",
    1424: "ogerpon-hearthflame-mask",
    1425: "ogerpon-cornerstone-mask",
    # Minior
    991: "minior-red-meteor",
    # Pyroar female
    831: "pyroar",  # PokeAPI doesn't have separate female entry
}


def _display_to_pokeapi(display_name: str) -> list[str]:
    """Convert our display name to candidate PokeAPI name(s), best first."""
    candidates: list[str] = []

    # Handle mega/primal/giga in parentheses: "Venusaur (Mega)" → "venusaur-mega"
    m = re.match(r"^(.+?) \(Mega(?: (X|Y))?\)$", display_name)
    if m:
        base = _clean(m.group(1))
        suffix = m.group(2)
        if suffix:
            candidates.append(f"{base}-mega-{suffix.lower()}")
        else:
            candidates.append(f"{base}-mega")
        return candidates

    m = re.match(r"^(.+?) \(Primal\)$", display_name)
    if m:
        candidates.append(f"{_clean(m.group(1))}-primal")
        return candidates

    m = re.match(r"^(.+?) \(Giga\)$", display_name)
    if m:
        candidates.append(f"{_clean(m.group(1))}-gmax")
        return candidates

    m = re.match(r"^(.+?) \(F\)$", display_name)
    if m:
        candidates.append(f"{_clean(m.group(1))}-female")
        candidates.append(f"{_clean(m.group(1))}-f")
        return candidates

    # Standard hyphenated forms: "Vulpix-Alola" → "vulpix-alola"
    name = _clean(display_name)
    candidates.append(name)

    # Try lowering regional suffix variants
    for old, new in [
        ("-alola", "-alola"),
        ("-galar", "-galar"),
        ("-hisui", "-hisui"),
        ("-paldea", "-paldea"),
    ]:
        if name.endswith(old):
            base = name[: -len(old)]
            candidates.append(f"{base}{new}n")  # e.g., vulpix-alolan (rare)
            break

    # Therian/Origin etc. → try as-is (already handled by _clean)
    return candidates


def _clean(name: str) -> str:
    """Normalize a display name to PokeAPI-style lowercase slug."""
    n = name.lower()
    n = n.replace("♀", "-f").replace("♂", "-m")
    n = n.replace("'", "").replace("'", "")
    n = n.replace(".", "").replace(":", "").replace(",", "")
    # Spaces → hyphens
    n = n.replace(" ", "-")
    # Remove double hyphens
    while "--" in n:
        n = n.replace("--", "-")
    return n.strip("-")


# ── PokeAPI fetching ────────────────────────────────────────────────────────

def fetch_pokemon_list() -> dict[str, int]:
    """Fetch the full list of pokemon (base + forms) → {name: id}."""
    url = "https://pokeapi.co/api/v2/pokemon?limit=2000"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    mapping: dict[str, int] = {}
    for entry in data["results"]:
        name = entry["name"]
        pid = int(entry["url"].rstrip("/").split("/")[-1])
        mapping[name] = pid
    print(f"Fetched {len(mapping)} entries from PokeAPI", file=sys.stderr)
    return mapping


def fetch_types(pid: int) -> tuple[int, int]:
    """Fetch type data for a PokeAPI pokemon ID."""
    url = f"https://pokeapi.co/api/v2/pokemon/{pid}/"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    types = [t["type"]["name"] for t in data["types"]]
    t1 = TYPE_NAME_TO_ID.get(types[0], 0)
    t2 = TYPE_NAME_TO_ID.get(types[1], t1) if len(types) > 1 else t1
    return (t1, t2)


# ── Main ────────────────────────────────────────────────────────────────────

def main() -> None:
    pokeapi = fetch_pokemon_list()

    # Identify alt forms by name patterns — NOT by CFRU→NatDex difference
    # (which also captures Gen 3+ base species with shifted internal IDs).
    _FORM_PATTERNS = [
        "-Alola", "-Galar", "-Hisui", "-Paldea",
        "(Mega", "(Primal)", "(Giga)",
        "-Origin", "-Therian", "-Sky", "-Resolute", "-Blade",
        "-Black", "-White", "-Dusk", "-Midnight",
        "-Attack", "-Defense", "-Speed",
        "-Heat", "-Wash", "-Frost", "-Fan", "-Mow",
        "-Sandy", "-Trash", "-East", "-Red", "-Blue",
        "-Zen", "-Low Key", "-Single Strike", "-Rapid Strike",
        "-Ice Rider", "-Shadow Rider",
        "-Crowned Sword", "-Crowned Shield",
        "-Bloodmoon", "-Wellspring", "-Hearthflame", "-Cornerstone",
        "-Terastal", "-Stellar",
        "-Strawberry", "-Berry", "-Clover", "-Flower", "-Love",
        "-Ribbon", "-Star",
        "-Shield", " (F)",
    ]

    forms: dict[int, str] = {}
    for cfru_id, display_name in sorted(SPECIES_NAMES.items()):
        if any(pat in display_name for pat in _FORM_PATTERNS):
            forms[cfru_id] = display_name

    print(f"Identified {len(forms)} alt forms to look up", file=sys.stderr)

    # Match to PokeAPI
    sprite_ids: dict[int, int] = {}
    form_types: dict[int, tuple[int, int]] = {}
    unmatched: list[tuple[int, str, list[str]]] = []

    for cfru_id, display_name in sorted(forms.items()):
        # Check override first
        if cfru_id in _POKEAPI_NAME_OVERRIDE:
            api_name = _POKEAPI_NAME_OVERRIDE[cfru_id]
            candidates = [api_name]
        else:
            candidates = _display_to_pokeapi(display_name)

        matched = False
        for api_name in candidates:
            if api_name in pokeapi:
                pid = pokeapi[api_name]
                sprite_ids[cfru_id] = pid
                # Fetch type data
                try:
                    form_types[cfru_id] = fetch_types(pid)
                    time.sleep(0.05)  # gentle rate limit
                except Exception as e:
                    print(f"  WARNING: Failed to fetch types for {display_name} (pid={pid}): {e}",
                          file=sys.stderr)
                matched = True
                break

        if not matched:
            unmatched.append((cfru_id, display_name, candidates))

        # Progress every 25 forms
        total_checked = len(sprite_ids) + len(unmatched)
        if total_checked % 25 == 0:
            print(f"  ... {total_checked}/{len(forms)} checked, {len(sprite_ids)} matched",
                  file=sys.stderr)

    print(f"\nMatched: {len(sprite_ids)} forms", file=sys.stderr)
    print(f"Unmatched: {len(unmatched)} forms", file=sys.stderr)
    if unmatched:
        print("\nUnmatched forms (add overrides if needed):", file=sys.stderr)
        for cid, name, tried in unmatched:
            print(f"  {cid}: {name!r}  tried: {tried}", file=sys.stderr)

    # -- Output (ASCII-safe for Windows console) -----
    print("\n# -- CFRU alt-form -> PokeAPI sprite ID --")
    print("# Maps CFRU internal form IDs to PokeAPI pokemon IDs for sprite URLs.")
    print("# Generated by tools/gen_form_data.py -- do not edit manually.")
    print("CFRU_FORM_SPRITE_ID: dict[int, int] = {")
    for cid in sorted(sprite_ids):
        print(f"    {cid}:{sprite_ids[cid]},", end="")
    print("\n}")

    print("\n# -- CFRU alt-form types --")
    print("# Maps CFRU form IDs to (type1, type2) using Gen III type byte values.")
    print("# Generated by tools/gen_form_data.py -- do not edit manually.")
    print("CFRU_FORM_TYPES: dict[int, tuple[int, int]] = {")
    for cid in sorted(form_types):
        t1, t2 = form_types[cid]
        print(f"    {cid}:({t1},{t2}),", end="")
    print("\n}")


if __name__ == "__main__":
    main()
