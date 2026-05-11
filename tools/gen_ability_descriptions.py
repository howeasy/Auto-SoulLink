#!/usr/bin/env python3
"""Generate ABILITY_DESCRIPTIONS dict for server/pokemon_data.py.

Sources:
  - RR ability IDs: funnotbun/funnotbun.github.io/data/abilities/abilities.h
  - RR descriptions: funnotbun/funnotbun.github.io/data/abilities/ability_descriptions.string
  - Vanilla descriptions: pret/pokefirered (decapitalization branch)

Usage:
    python tools/gen_ability_descriptions.py

Outputs the dict to stdout for pasting into server/pokemon_data.py.
"""

import re
import urllib.request

RR_ABILITIES_URL = (
    "https://raw.githubusercontent.com/funnotbun/funnotbun.github.io/"
    "main/data/abilities/abilities.h"
)
RR_DESCRIPTIONS_URL = (
    "https://raw.githubusercontent.com/funnotbun/funnotbun.github.io/"
    "main/data/abilities/ability_descriptions.string"
)
VANILLA_DESCRIPTIONS_URL = (
    "https://raw.githubusercontent.com/ProfLeonDias/pokefirered/"
    "decapitalization/src/data/text/abilities.h"
)


def fetch(url: str) -> str:
    with urllib.request.urlopen(url) as resp:
        return resp.read().decode("utf-8")


def parse_ability_ids(text: str) -> dict[str, int]:
    """Parse #define ABILITY_FOO 0xNN lines into {name: id}."""
    result = {}
    for line in text.splitlines():
        m = re.match(r"#define\s+(ABILITY_\w+)\s+0x([0-9A-Fa-f]+)", line)
        if m:
            name = m.group(1)
            val = int(m.group(2), 16)
            result[name] = val
    return result


def parse_rr_descriptions(text: str) -> dict[str, str]:
    """Parse #org @DESC_FOO / description lines into {DESC_name: description}."""
    result = {}
    current_names: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("#include") or line.startswith("//") or not line:
            continue
        if line.startswith("#org @"):
            name = line[6:]  # strip "#org @"
            current_names.append(name)
        elif line.startswith("#ifdef") or line.startswith("#else") or line.startswith("#endif"):
            continue
        elif current_names:
            # Description line — clean up escaped chars and newlines
            desc = line.replace("\\n", " ").replace("\\e", "é")
            desc = re.sub(r"\s+", " ", desc).strip()
            for n in current_names:
                result[n] = desc
            current_names = []
    return result


def normalize_ability_key(ability_name: str) -> str:
    """Convert ABILITY_FOOBAR to DESC_FOOBAR."""
    return "DESC_" + ability_name.replace("ABILITY_", "")


def main():
    print("Fetching RR ability IDs...")
    ids_text = fetch(RR_ABILITIES_URL)
    ability_ids = parse_ability_ids(ids_text)

    print(f"  Found {len(ability_ids)} ability IDs")

    print("Fetching RR descriptions...")
    desc_text = fetch(RR_DESCRIPTIONS_URL)
    rr_descs = parse_rr_descriptions(desc_text)
    print(f"  Found {len(rr_descs)} RR descriptions")

    # Build ID -> description mapping
    rr_map: dict[int, str] = {}
    # Manual name mappings for mismatches between abilities.h and descriptions
    name_fixes = {
        "ABILITY_SPEEDBOOST": "DESC_SPEEDBOOST",
        "ABILITY_BATTLEARMOR": "DESC_BATTLEARMOR",
        "ABILITY_SANDVEIL": "DESC_SANDVEIL",
        "ABILITY_VOLTABSORB": "DESC_VOLTABSORB",
        "ABILITY_WATERABSORB": "DESC_WATERABSORB",
        "ABILITY_CLOUDNINE": "DESC_CLOUDNINE",
        "ABILITY_COMPOUNDEYES": "DESC_COMPOUNDEYES",
        "ABILITY_FLASHFIRE": "DESC_FLASHFIRE",
        "ABILITY_SUCTIONCUPS": "DESC_SUCTIONCUPS",
        "ABILITY_SHADOWTAG": "DESC_SHADOWTAG",
        "ABILITY_WONDERGUARD": "DESC_WONDERGUARD",
        "ABILITY_EFFECTSPORE": "DESC_EFFECTSPORE",
        "ABILITY_CLEARBODY": "DESC_CLEARBODY",
        "ABILITY_NATURALCURE": "DESC_NATURALCURE",
        "ABILITY_LIGHTNINGROD": "DESC_LIGHTNINGROD",
        "ABILITY_SERENEGRACE": "DESC_SERENEGRACE",
        "ABILITY_SWIFTSWIM": "DESC_SWIFTSWIM",
        "ABILITY_GULPMISSILE": "DESC_GULPMISSILE",
        "ABILITY_HUGEPOWER": "DESC_HUGEPOWER",
        "ABILITY_DRAGONSMAW": "DESC_DRAGONSMAW",
        "ABILITY_INNERFOCUS": "DESC_INNERFOCUS",
        "ABILITY_MAGMAARMOR": "DESC_MAGMAARMOR",
        "ABILITY_WATERVEIL": "DESC_WATERVEIL",
        "ABILITY_MAGNETPULL": "DESC_MAGNETPULL",
        "ABILITY_RAINDISH": "DESC_RAINDISH",
        "ABILITY_SANDSTREAM": "DESC_SANDSTREAM",
        "ABILITY_THICKFAT": "DESC_THICKFAT",
        "ABILITY_EARLYBIRD": "DESC_EARLYBIRD",
        "ABILITY_FLAMEBODY": "DESC_FLAMEBODY",
        "ABILITY_BADCOMPANY": "DESC_BADCOMPANY",
        "ABILITY_HYPERCUTTER": "DESC_HYPERCUTTER",
        "ABILITY_CUTECHARM": "DESC_CUTECHARM",
        "ABILITY_SHEDSKIN": "DESC_SHEDSKIN",
        "ABILITY_MARVELSCALE": "DESC_MARVELSCALE",
        "ABILITY_LIQUIDOOZE": "DESC_LIQUIDOOZE",
        "ABILITY_ROCKHEAD": "DESC_ROCKHEAD",
        "ABILITY_ARENATRAP": "DESC_ARENATRAP",
        "ABILITY_PURIFYINGSALT": "DESC_PURIFYING_SALT",
        "ABILITY_ASONESHADOW": "DESC_AS_ONE_SHADOW",
        "ABILITY_NEUTRALIZINGGAS": "DESC_NEUTRALISINGGAS",
        "ABILITY_LETHALPRECISION": "DESC_LETHALPRECISION",
        "ABILITY_HUNGERSWITCH": "DESC_HUNGERSWITCH",
        "ABILITY_ASONEICE": "DESC_AS_ONE_ICE",
        "ABILITY_SWEETVEIL": "DESC_SWEETVEIL",
        "ABILITY_SKILLLINK": "DESC_SKILLLINK",
        "ABILITY_MOTORDRIVE": "DESC_MOTORDRIVE",
        "ABILITY_MULTISCALE": "DESC_MULTISCALE",
        "ABILITY_SUPERLUCK": "DESC_SUPERLUCK",
        "ABILITY_MAGICBOUNCE": "DESC_MAGICBOUNCE",
        "ABILITY_SHEERFORCE": "DESC_SHEERFORCE",
        "ABILITY_IRONFIST": "DESC_IRONFIST",
        "ABILITY_SANDFORCE": "DESC_SANDFORCE",
        "ABILITY_SOLARPOWER": "DESC_SOLARPOWER",
        "ABILITY_DRYSKIN": "DESC_DRYSKIN",
        "ABILITY_TINTEDLENS": "DESC_TINTEDLENS",
        "ABILITY_SOLIDROCK": "DESC_SOLIDROCK",
        "ABILITY_POISONHEAL": "DESC_POISONHEAL",
        "ABILITY_ICEBODY": "DESC_ICEBODY",
        "ABILITY_BULLRUSH": "DESC_BULLRUSH",
        "ABILITY_SUPREMEOVERLORD": "DESC_SUPREMEOVERLORD",
        "ABILITY_ANGERSHELL": "DESC_ANGERSHELL",
        "ABILITY_GOODASGOLD": "DESC_GOODASGOLD",
        "ABILITY_SNOWWARNING": "DESC_SNOWWARNING",
        "ABILITY_QUICKFEET": "DESC_QUICKFEET",
        "ABILITY_SAPSIPPER": "DESC_SAPSIPPER",
        "ABILITY_MAGICGUARD": "DESC_MAGICGUARD",
        "ABILITY_BULLETPROOF": "DESC_BULLETPROOF",
        "ABILITY_GALEWINGS": "DESC_GALEWINGS",
        "ABILITY_CURSEDBODY": "DESC_CURSEDBODY",
        "ABILITY_IRONBARBS": "DESC_IRONBARBS",
        "ABILITY_SANDRUSH": "DESC_SANDRUSH",
        "ABILITY_NOGUARD": "DESC_NOGUARD",
        "ABILITY_MEGALAUNCHER": "DESC_MEGALAUNCHER",
        "ABILITY_TOUGHCLAWS": "DESC_TOUGHCLAWS",
        "ABILITY_STRONGJAW": "DESC_STRONGJAW",
        "ABILITY_VICTORYSTAR": "DESC_VICTORYSTAR",
        "ABILITY_STORMDRAIN": "DESC_STORMDRAIN",
        "ABILITY_DARKAURA": "DESC_DARKAURA",
        "ABILITY_FAIRYAURA": "DESC_FAIRYAURA",
        "ABILITY_SEEDSOWER": "DESC_SEEDSOWER",
        "ABILITY_FELINEPOWER": "DESC_FELINEPOWER",
        "ABILITY_TOXICBOOST": "DESC_TOXICBOOST",
        "ABILITY_FLAREBOOST": "DESC_FLAREBOOST",
        "ABILITY_FURCOAT": "DESC_FURCOAT",
        "ABILITY_WONDERSKIN": "DESC_WONDERSKIN",
        "ABILITY_PARENTALBOND": "DESC_PARENTALBOND",
        "ABILITY_MOLDBREAKER": "DESC_MOLDBREAKER",
        "ABILITY_HADRONENGINE": "DESC_HADRONE_ENGINE",
        "ABILITY_ORICHALCUMPULSE": "DESC_ORICHALCUM_PULSE",
        "ABILITY_ZENMODE": "DESC_ZENMODE",
        "ABILITY_BATTLEBOND": "DESC_BATTLEBOND",
        "ABILITY_BEASTBOOST": "DESC_BEASTBOOST",
        "ABILITY_EMERGENCYEXIT": "DESC_EMERGENCYEXIT",
        "ABILITY_STEELY_SPIRIT": "DESC_STEELYSPIRIT",
        "ABILITY_PERISH_BODY": "DESC_PERISHBODY",
        "ABILITY_WANDERING_SPIRIT": "DESC_WANDERINGSPIRIT",
        "ABILITY_POWERCONSTRUCT": "DESC_POWERCONSTRUCT",
        "ABILITY_TABLETSOFRUIN": "DESC_TABLETSOFRUIN",
        "ABILITY_RAGINGBOXER": "DESC_RAGING_BOXER",
        "ABILITY_BEADSOFRUIN": "DESC_BEADSOFRUIN",
        "ABILITY_SHIELDSDOWN": "DESC_SHIELDSDOWN",
        "ABILITY_SLUSHRUSH": "DESC_SLUSHRUSH",
        "ABILITY_SOULHEART": "DESC_SOULHEART",
        "ABILITY_ZEROTOHERO": "DESC_ZEROTOHERO",
        "ABILITY_THERMALEXCHANGE": "DESC_THERMAL_EXCHANGE",
        "ABILITY_WATERBUBBLE": "DESC_WATERBUBBLE",
        "ABILITY_WATERCOMPACTION": "DESC_WATERCOMPACTION",
        "ABILITY_PARASITICGOO": "DESC_PARASITICGOO",
        "ABILITY_ELECTRICSURGE": "DESC_ELECTRICSURGE",
        "ABILITY_GRASSYSURGE": "DESC_GRASSYSURGE",
        "ABILITY_MISTYSURGE": "DESC_MISTYSURGE",
        "ABILITY_PSYCHICSURGE": "DESC_PSYCHICSURGE",
        "ABILITY_SURGESURFER": "DESC_SURGESURFER",
        "ABILITY_GRASSPELT": "DESC_GRASSPELT",
        "ABILITY_ANGERPOINT": "DESC_ANGERPOINT",
        "ABILITY_EARTHEATER": "DESC_EARTHEATER",
        "ABILITY_QUARKDRIVE": "DESC_QUARKDRIVE",
        "ABILITY_UNSEENFIST": "DESC_UNSEENFIST",
        "ABILITY_TOXICDEBRIS": "DESC_TOXICDEBRIS",
        "ABILITY_ELECTROMORPHOSIS": "DESC_ELECTROMORPHOSIS",
        "ABILITY_FLOWERGIFT": "DESC_FLOWERGIFT",
        "ABILITY_BADDREAMS": "DESC_BADDREAMS",
        "ABILITY_GRIMNEIGH": "DESC_GRIMNEIGH",
        "ABILITY_TRANSISTOR": "DESC_TRANSISTOR",
        "ABILITY_POISONTOUCH": "DESC_POISONTOUCH",
        "ABILITY_STANCECHANGE": "DESC_STANCECHANGE",
        "ABILITY_PRIMORDIALSEA": "DESC_PRIMORDIALSEA",
        "ABILITY_DESOLATELAND": "DESC_DESOLATELAND",
        "ABILITY_DELTASTREAM": "DESC_DELTASTREAM",
        "ABILITY_GORILLATACTICS": "DESC_GORILLATACTICS",
        "ABILITY_PRIMALARMOR": "DESC_PRIMALARMOR",
        "ABILITY_LIQUIDVOICE": "DESC_LIQUIDVOICE",
        "ABILITY_PHOENIXDOWN": "DESC_PHOENIXDOWN",
        "ABILITY_INNARDSOUT": "DESC_INNARDSOUT",
        "ABILITY_MOUNTAINEER": "DESC_MOUNTAINEER",
        "ABILITY_FRIENDGUARD": "DESC_FRIENDGUARD",
        "ABILITY_PROTOSYNTHESIS": "DESC_PROTOSYNTHESIS",
        "ABILITY_STAKEOUT": "DESC_STAKEOUT",
        "ABILITY_BONEZONE": "DESC_BONE_ZONE",
        "ABILITY_SELFSUFFICIENT": "DESC_SELFSUFFICIENT",
        "ABILITY_NEUROFORCE": "DESC_NEUROFORCE",
        "ABILITY_INTREPIDSWORD": "DESC_INTREPIDSWORD",
        "ABILITY_DAUNTLESSSHIELD": "DESC_DAUNTLESSSHIELD",
        "ABILITY_STRIKER": "DESC_STRIKER",
        "ABILITY_COTTONDOWN": "DESC_COTTONDOWN",
        "ABILITY_SWORDOFRUIN": "DESC_SWORDOFRUIN",
        "ABILITY_SHARPNESS": "DESC_SHARPNESS",
        "ABILITY_VESSELOFRUIN": "DESC_VESSELOFRUIN",
        "ABILITY_STEAMENGINE": "DESC_STEAMENGINE",
        "ABILITY_PUNKROCK": "DESC_PUNKROCK",
        "ABILITY_SANDSPIT": "DESC_SANDSPIT",
        "ABILITY_ICESCALES": "DESC_ICESCALES",
        "ABILITY_ICEFACE": "DESC_ICEFACE",
        "ABILITY_ROCKYPAYLOAD": "DESC_ROCKYPAYLOAD",
        "ABILITY_FLAMINGSOUL": "DESC_FLAMINGSOUL",
        "ABILITY_SCREENCLEANER": "DESC_SCREENCLEANER",
        "ABILITY_WELLBAKEDBODY": "DESC_WELLBAKEDBODY",
        "ABILITY_SAGEPOWER": "DESC_SAGEPOWER",
        "ABILITY_WINDRIDER": "DESC_WINDRIDER",
        "ABILITY_QUICKDRAW": "DESC_QUICK_DRAW",
    }

    matched = 0
    unmatched = []
    for ability_name, ability_id in sorted(ability_ids.items(), key=lambda x: x[1]):
        if ability_id == 0:
            continue
        # Try manual mapping first
        if ability_name in name_fixes:
            desc_key = name_fixes[ability_name]
        else:
            # Auto-derive DESC key
            desc_key = normalize_ability_key(ability_name)

        if desc_key in rr_descs:
            rr_map[ability_id] = rr_descs[desc_key]
            matched += 1
        else:
            unmatched.append((ability_id, ability_name, desc_key))

    print(f"  Matched: {matched}, Unmatched: {len(unmatched)}")
    if unmatched:
        print("  Unmatched abilities:")
        for aid, aname, dkey in unmatched:
            print(f"    {aid:3d} (0x{aid:02X}) {aname} -> {dkey}")

    # Output Python dict
    print("\n# --- Paste into server/pokemon_data.py ---\n")
    print("ABILITY_DESCRIPTIONS: dict[int, str] = {")
    for aid in sorted(rr_map.keys()):
        desc = rr_map[aid].replace("'", "\\'")
        print(f"    {aid}: '{desc}',")
    print("}")


if __name__ == "__main__":
    main()
