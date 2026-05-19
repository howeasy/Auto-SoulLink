#!/usr/bin/env python
"""
tools/gen_moves_data.py — generate moves.json for Gen 1 and Gen 2 from
pret-derived data tables.

The move tables are embedded in this script so re-generation is offline-safe
(no live HTTP fetch). To refresh from upstream pret:

  curl https://raw.githubusercontent.com/pret/pokered/master/data/moves/moves.asm
  curl https://raw.githubusercontent.com/pret/pokecrystal/master/data/moves/moves.asm
  curl https://raw.githubusercontent.com/pret/pokecrystal/master/data/moves/names.asm

...then update the embedded tables below. The conversion logic (display
names, physical/special split, type normalization) lives here.

Output:
  data/games/gen1_rby/moves.json  — 165 entries
  data/games/gen2_crystal/moves.json — 251 entries

Each entry: {id, name, type, power, accuracy, pp, split, effect_chance?}
"""

import json
import os

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GEN1_OUT = os.path.join(REPO_ROOT, "data", "games", "gen1_rby", "moves.json")
GEN2_OUT = os.path.join(REPO_ROOT, "data", "games", "gen2_crystal", "moves.json")

# Gen 1/2 type-based physical/special split. Gen 2 adds DARK (special) and STEEL (physical).
_PHYSICAL_TYPES_GEN1 = {"NORMAL", "FIGHTING", "FLYING", "POISON", "GROUND", "ROCK", "BUG", "GHOST"}
_SPECIAL_TYPES_GEN1 = {"FIRE", "WATER", "GRASS", "ELECTRIC", "ICE", "PSYCHIC", "DRAGON"}
_PHYSICAL_TYPES_GEN2 = _PHYSICAL_TYPES_GEN1 | {"STEEL"}
_SPECIAL_TYPES_GEN2 = _SPECIAL_TYPES_GEN1 | {"DARK"}


def normalize_type(raw: str) -> str:
    """PSYCHIC_TYPE → Psychic, CURSE_TYPE → ??? (status-only), NORMAL → Normal."""
    t = raw.replace("_TYPE", "").strip()
    return t.capitalize() if t != "???" else "???"


def split_for(type_upper: str, power: int, physical_set: set[str], special_set: set[str]) -> str:
    # Power-0 moves are Status regardless of type (Growl, Sleep Powder, etc.).
    # Gen 1/2's physical/special split is type-based, but only meaningful for
    # damage-dealing moves. Move 165 "Struggle" still has power so stays in its
    # type-based split.
    if power <= 0:
        return "Status"
    if type_upper in physical_set:
        return "Physical"
    if type_upper in special_set:
        return "Special"
    return "Status"


def display_name(internal: str) -> str:
    """POUND → Pound, KARATE_CHOP → Karate Chop, HI_JUMP_KICK → Hi Jump Kick.
    A handful of Gen 1/2 internal names match exactly to their display form."""
    # Special cases where pret's internal name differs from the displayed name
    overrides = {
        "PSYCHIC_M": "Psychic",
        "DOUBLE_EDGE": "Double-Edge",
        "SAND_ATTACK": "Sand-Attack",
        "MUD_SLAP": "Mud-Slap",
        "LOCK_ON": "Lock-On",
        "HI_JUMP_KICK": "Hi Jump Kick",
        "CONVERSION2": "Conversion 2",
        "EXTREMESPEED": "ExtremeSpeed",
        "ANCIENTPOWER": "AncientPower",
        "POISONPOWDER": "PoisonPowder",
        "SOLARBEAM": "SolarBeam",
        "DYNAMICPUNCH": "DynamicPunch",
        "DRAGONBREATH": "DragonBreath",
        "BUBBLEBEAM": "BubbleBeam",
        "DOUBLESLAP": "DoubleSlap",
        "SONICBOOM": "SonicBoom",
        "THUNDERSHOCK": "ThunderShock",
        "THUNDERPUNCH": "ThunderPunch",
        "VICEGRIP": "ViceGrip",
        "SOFTBOILED": "Softboiled",
        "SELFDESTRUCT": "Selfdestruct",
        "SMOKESCREEN": "SmokeScreen",
        "GROUND_TYPE": "Ground",
    }
    if internal in overrides:
        return overrides[internal]
    parts = internal.split("_")
    return " ".join(p.capitalize() for p in parts)


# Gen 1 (pret/pokered data/moves/moves.asm) — 165 moves
# Fields per entry: (internal_name, power, type, accuracy, pp)
GEN1_MOVES = [
    ("POUND", 40, "NORMAL", 100, 35),
    ("KARATE_CHOP", 50, "NORMAL", 100, 25),  # Gen 1 mislabeled Karate Chop as Normal (fixed in Gen 2)
    ("DOUBLESLAP", 15, "NORMAL", 85, 10),
    ("COMET_PUNCH", 18, "NORMAL", 85, 15),
    ("MEGA_PUNCH", 80, "NORMAL", 85, 20),
    ("PAY_DAY", 40, "NORMAL", 100, 20),
    ("FIRE_PUNCH", 75, "FIRE", 100, 15),
    ("ICE_PUNCH", 75, "ICE", 100, 15),
    ("THUNDERPUNCH", 75, "ELECTRIC", 100, 15),
    ("SCRATCH", 40, "NORMAL", 100, 35),
    ("VICEGRIP", 55, "NORMAL", 100, 30),
    ("GUILLOTINE", 1, "NORMAL", 30, 5),
    ("RAZOR_WIND", 80, "NORMAL", 75, 10),
    ("SWORDS_DANCE", 0, "NORMAL", 100, 30),
    ("CUT", 50, "NORMAL", 95, 30),
    ("GUST", 40, "NORMAL", 100, 35),  # Gen 1 Normal; Gen 2 Flying
    ("WING_ATTACK", 35, "FLYING", 100, 35),
    ("WHIRLWIND", 0, "NORMAL", 85, 20),
    ("FLY", 70, "FLYING", 95, 15),
    ("BIND", 15, "NORMAL", 75, 20),
    ("SLAM", 80, "NORMAL", 75, 20),
    ("VINE_WHIP", 35, "GRASS", 100, 10),
    ("STOMP", 65, "NORMAL", 100, 20),
    ("DOUBLE_KICK", 30, "FIGHTING", 100, 30),
    ("MEGA_KICK", 120, "NORMAL", 75, 5),
    ("JUMP_KICK", 70, "FIGHTING", 95, 25),
    ("ROLLING_KICK", 60, "FIGHTING", 85, 15),
    ("SAND_ATTACK", 0, "NORMAL", 100, 15),  # Gen 1 Normal; Gen 2 Ground
    ("HEADBUTT", 70, "NORMAL", 100, 15),
    ("HORN_ATTACK", 65, "NORMAL", 100, 25),
    ("FURY_ATTACK", 15, "NORMAL", 85, 20),
    ("HORN_DRILL", 1, "NORMAL", 30, 5),
    ("TACKLE", 35, "NORMAL", 95, 35),
    ("BODY_SLAM", 85, "NORMAL", 100, 15),
    ("WRAP", 15, "NORMAL", 85, 20),
    ("TAKE_DOWN", 90, "NORMAL", 85, 20),
    ("THRASH", 90, "NORMAL", 100, 20),
    ("DOUBLE_EDGE", 100, "NORMAL", 100, 15),
    ("TAIL_WHIP", 0, "NORMAL", 100, 30),
    ("POISON_STING", 15, "POISON", 100, 35),
    ("TWINEEDLE", 25, "BUG", 100, 20),
    ("PIN_MISSILE", 14, "BUG", 85, 20),
    ("LEER", 0, "NORMAL", 100, 30),
    ("BITE", 60, "NORMAL", 100, 25),  # Gen 1 Normal; Gen 2 Dark
    ("GROWL", 0, "NORMAL", 100, 40),
    ("ROAR", 0, "NORMAL", 100, 20),
    ("SING", 0, "NORMAL", 55, 15),
    ("SUPERSONIC", 0, "NORMAL", 55, 20),
    ("SONICBOOM", 1, "NORMAL", 90, 20),
    ("DISABLE", 0, "NORMAL", 55, 20),
    ("ACID", 40, "POISON", 100, 30),
    ("EMBER", 40, "FIRE", 100, 25),
    ("FLAMETHROWER", 95, "FIRE", 100, 15),
    ("MIST", 0, "ICE", 100, 30),
    ("WATER_GUN", 40, "WATER", 100, 25),
    ("HYDRO_PUMP", 120, "WATER", 80, 5),
    ("SURF", 95, "WATER", 100, 15),
    ("ICE_BEAM", 95, "ICE", 100, 10),
    ("BLIZZARD", 120, "ICE", 90, 5),
    ("PSYBEAM", 65, "PSYCHIC", 100, 20),
    ("BUBBLEBEAM", 65, "WATER", 100, 20),
    ("AURORA_BEAM", 65, "ICE", 100, 20),
    ("HYPER_BEAM", 150, "NORMAL", 90, 5),
    ("PECK", 35, "FLYING", 100, 35),
    ("DRILL_PECK", 80, "FLYING", 100, 20),
    ("SUBMISSION", 80, "FIGHTING", 80, 25),
    ("LOW_KICK", 50, "FIGHTING", 90, 20),
    ("COUNTER", 1, "FIGHTING", 100, 20),
    ("SEISMIC_TOSS", 1, "FIGHTING", 100, 20),
    ("STRENGTH", 80, "NORMAL", 100, 15),
    ("ABSORB", 20, "GRASS", 100, 20),
    ("MEGA_DRAIN", 40, "GRASS", 100, 10),
    ("LEECH_SEED", 0, "GRASS", 90, 10),
    ("GROWTH", 0, "NORMAL", 100, 40),
    ("RAZOR_LEAF", 55, "GRASS", 95, 25),
    ("SOLARBEAM", 120, "GRASS", 100, 10),
    ("POISONPOWDER", 0, "POISON", 75, 35),
    ("STUN_SPORE", 0, "GRASS", 75, 30),
    ("SLEEP_POWDER", 0, "GRASS", 75, 15),
    ("PETAL_DANCE", 70, "GRASS", 100, 20),
    ("STRING_SHOT", 0, "BUG", 95, 40),
    ("DRAGON_RAGE", 1, "DRAGON", 100, 10),
    ("FIRE_SPIN", 15, "FIRE", 70, 15),
    ("THUNDERSHOCK", 40, "ELECTRIC", 100, 30),
    ("THUNDERBOLT", 95, "ELECTRIC", 100, 15),
    ("THUNDER_WAVE", 0, "ELECTRIC", 100, 20),
    ("THUNDER", 120, "ELECTRIC", 70, 10),
    ("ROCK_THROW", 50, "ROCK", 65, 15),
    ("EARTHQUAKE", 100, "GROUND", 100, 10),
    ("FISSURE", 1, "GROUND", 30, 5),
    ("DIG", 100, "GROUND", 100, 10),
    ("TOXIC", 0, "POISON", 85, 10),
    ("CONFUSION", 50, "PSYCHIC", 100, 25),
    ("PSYCHIC_M", 90, "PSYCHIC", 100, 10),
    ("HYPNOSIS", 0, "PSYCHIC", 60, 20),
    ("MEDITATE", 0, "PSYCHIC", 100, 40),
    ("AGILITY", 0, "PSYCHIC", 100, 30),
    ("QUICK_ATTACK", 40, "NORMAL", 100, 30),
    ("RAGE", 20, "NORMAL", 100, 20),
    ("TELEPORT", 0, "PSYCHIC", 100, 20),
    ("NIGHT_SHADE", 0, "GHOST", 100, 15),
    ("MIMIC", 0, "NORMAL", 100, 10),
    ("SCREECH", 0, "NORMAL", 85, 40),
    ("DOUBLE_TEAM", 0, "NORMAL", 100, 15),
    ("RECOVER", 0, "NORMAL", 100, 20),
    ("HARDEN", 0, "NORMAL", 100, 30),
    ("MINIMIZE", 0, "NORMAL", 100, 20),
    ("SMOKESCREEN", 0, "NORMAL", 100, 20),
    ("CONFUSE_RAY", 0, "GHOST", 100, 10),
    ("WITHDRAW", 0, "WATER", 100, 40),
    ("DEFENSE_CURL", 0, "NORMAL", 100, 40),
    ("BARRIER", 0, "PSYCHIC", 100, 30),
    ("LIGHT_SCREEN", 0, "PSYCHIC", 100, 30),
    ("HAZE", 0, "ICE", 100, 30),
    ("REFLECT", 0, "PSYCHIC", 100, 20),
    ("FOCUS_ENERGY", 0, "NORMAL", 100, 30),
    ("BIDE", 0, "NORMAL", 100, 10),
    ("METRONOME", 0, "NORMAL", 100, 10),
    ("MIRROR_MOVE", 0, "FLYING", 100, 20),
    ("SELFDESTRUCT", 130, "NORMAL", 100, 5),
    ("EGG_BOMB", 100, "NORMAL", 75, 10),
    ("LICK", 20, "GHOST", 100, 30),
    ("SMOG", 20, "POISON", 70, 20),
    ("SLUDGE", 65, "POISON", 100, 20),
    ("BONE_CLUB", 65, "GROUND", 85, 20),
    ("FIRE_BLAST", 120, "FIRE", 85, 5),
    ("WATERFALL", 80, "WATER", 100, 15),
    ("CLAMP", 35, "WATER", 75, 10),
    ("SWIFT", 60, "NORMAL", 100, 20),
    ("SKULL_BASH", 100, "NORMAL", 100, 15),
    ("SPIKE_CANNON", 20, "NORMAL", 100, 15),
    ("CONSTRICT", 10, "NORMAL", 100, 35),
    ("AMNESIA", 0, "PSYCHIC", 100, 20),
    ("KINESIS", 0, "PSYCHIC", 80, 15),
    ("SOFTBOILED", 0, "NORMAL", 100, 10),
    ("HI_JUMP_KICK", 85, "FIGHTING", 90, 20),
    ("GLARE", 0, "NORMAL", 75, 30),
    ("DREAM_EATER", 100, "PSYCHIC", 100, 15),
    ("POISON_GAS", 0, "POISON", 55, 40),
    ("BARRAGE", 15, "NORMAL", 85, 20),
    ("LEECH_LIFE", 20, "BUG", 100, 15),
    ("LOVELY_KISS", 0, "NORMAL", 75, 10),
    ("SKY_ATTACK", 140, "FLYING", 90, 5),
    ("TRANSFORM", 0, "NORMAL", 100, 10),
    ("BUBBLE", 20, "WATER", 100, 30),
    ("DIZZY_PUNCH", 70, "NORMAL", 100, 10),
    ("SPORE", 0, "GRASS", 100, 15),
    ("FLASH", 0, "NORMAL", 70, 20),
    ("PSYWAVE", 1, "PSYCHIC", 80, 15),
    ("SPLASH", 0, "NORMAL", 100, 40),
    ("ACID_ARMOR", 0, "POISON", 100, 40),
    ("CRABHAMMER", 90, "WATER", 85, 10),
    ("EXPLOSION", 170, "NORMAL", 100, 5),
    ("FURY_SWIPES", 18, "NORMAL", 80, 15),
    ("BONEMERANG", 50, "GROUND", 90, 10),
    ("REST", 0, "PSYCHIC", 100, 10),
    ("ROCK_SLIDE", 75, "ROCK", 90, 10),
    ("HYPER_FANG", 80, "NORMAL", 90, 15),
    ("SHARPEN", 0, "NORMAL", 100, 30),
    ("CONVERSION", 0, "NORMAL", 100, 30),
    ("TRI_ATTACK", 80, "NORMAL", 100, 10),
    ("SUPER_FANG", 1, "NORMAL", 90, 10),
    ("SLASH", 70, "NORMAL", 100, 20),
    ("SUBSTITUTE", 0, "NORMAL", 100, 10),
    ("STRUGGLE", 50, "NORMAL", 100, 10),
]
assert len(GEN1_MOVES) == 165, f"Gen 1 move count: {len(GEN1_MOVES)} (expected 165)"

# Gen 2 (pret/pokecrystal data/moves/moves.asm) — 251 moves
# Fields: (internal_name, power, type, accuracy, pp, effect_chance)
# Adapted from CSV; includes Gen 2 type fixes (Karate Chop=Fighting, Bite=Dark, etc.)
GEN2_MOVES = [
    ("POUND", 40, "NORMAL", 100, 35, 0),
    ("KARATE_CHOP", 50, "FIGHTING", 100, 25, 0),
    ("DOUBLESLAP", 15, "NORMAL", 85, 10, 0),
    ("COMET_PUNCH", 18, "NORMAL", 85, 15, 0),
    ("MEGA_PUNCH", 80, "NORMAL", 85, 20, 0),
    ("PAY_DAY", 40, "NORMAL", 100, 20, 0),
    ("FIRE_PUNCH", 75, "FIRE", 100, 15, 10),
    ("ICE_PUNCH", 75, "ICE", 100, 15, 10),
    ("THUNDERPUNCH", 75, "ELECTRIC", 100, 15, 10),
    ("SCRATCH", 40, "NORMAL", 100, 35, 0),
    ("VICEGRIP", 55, "NORMAL", 100, 30, 0),
    ("GUILLOTINE", 0, "NORMAL", 30, 5, 0),
    ("RAZOR_WIND", 80, "NORMAL", 75, 10, 0),
    ("SWORDS_DANCE", 0, "NORMAL", 100, 30, 0),
    ("CUT", 50, "NORMAL", 95, 30, 0),
    ("GUST", 40, "FLYING", 100, 35, 0),
    ("WING_ATTACK", 60, "FLYING", 100, 35, 0),
    ("WHIRLWIND", 0, "NORMAL", 100, 20, 0),
    ("FLY", 70, "FLYING", 95, 15, 0),
    ("BIND", 15, "NORMAL", 75, 20, 0),
    ("SLAM", 80, "NORMAL", 75, 20, 0),
    ("VINE_WHIP", 35, "GRASS", 100, 10, 0),
    ("STOMP", 65, "NORMAL", 100, 20, 30),
    ("DOUBLE_KICK", 30, "FIGHTING", 100, 30, 0),
    ("MEGA_KICK", 120, "NORMAL", 75, 5, 0),
    ("JUMP_KICK", 70, "FIGHTING", 95, 25, 0),
    ("ROLLING_KICK", 60, "FIGHTING", 85, 15, 30),
    ("SAND_ATTACK", 0, "GROUND", 100, 15, 0),
    ("HEADBUTT", 70, "NORMAL", 100, 15, 30),
    ("HORN_ATTACK", 65, "NORMAL", 100, 25, 0),
    ("FURY_ATTACK", 15, "NORMAL", 85, 20, 0),
    ("HORN_DRILL", 1, "NORMAL", 30, 5, 0),
    ("TACKLE", 35, "NORMAL", 95, 35, 0),
    ("BODY_SLAM", 85, "NORMAL", 100, 15, 30),
    ("WRAP", 15, "NORMAL", 85, 20, 0),
    ("TAKE_DOWN", 90, "NORMAL", 85, 20, 0),
    ("THRASH", 90, "NORMAL", 100, 20, 0),
    ("DOUBLE_EDGE", 120, "NORMAL", 100, 15, 0),
    ("TAIL_WHIP", 0, "NORMAL", 100, 30, 0),
    ("POISON_STING", 15, "POISON", 100, 35, 30),
    ("TWINEEDLE", 25, "BUG", 100, 20, 20),
    ("PIN_MISSILE", 14, "BUG", 85, 20, 0),
    ("LEER", 0, "NORMAL", 100, 30, 0),
    ("BITE", 60, "DARK", 100, 25, 30),
    ("GROWL", 0, "NORMAL", 100, 40, 0),
    ("ROAR", 0, "NORMAL", 100, 20, 0),
    ("SING", 0, "NORMAL", 55, 15, 0),
    ("SUPERSONIC", 0, "NORMAL", 55, 20, 0),
    ("SONICBOOM", 20, "NORMAL", 90, 20, 0),
    ("DISABLE", 0, "NORMAL", 55, 20, 0),
    ("ACID", 40, "POISON", 100, 30, 10),
    ("EMBER", 40, "FIRE", 100, 25, 10),
    ("FLAMETHROWER", 95, "FIRE", 100, 15, 10),
    ("MIST", 0, "ICE", 100, 30, 0),
    ("WATER_GUN", 40, "WATER", 100, 25, 0),
    ("HYDRO_PUMP", 120, "WATER", 80, 5, 0),
    ("SURF", 95, "WATER", 100, 15, 0),
    ("ICE_BEAM", 95, "ICE", 100, 10, 10),
    ("BLIZZARD", 120, "ICE", 70, 5, 10),
    ("PSYBEAM", 65, "PSYCHIC", 100, 20, 10),
    ("BUBBLEBEAM", 65, "WATER", 100, 20, 10),
    ("AURORA_BEAM", 65, "ICE", 100, 20, 10),
    ("HYPER_BEAM", 150, "NORMAL", 90, 5, 0),
    ("PECK", 35, "FLYING", 100, 35, 0),
    ("DRILL_PECK", 80, "FLYING", 100, 20, 0),
    ("SUBMISSION", 80, "FIGHTING", 80, 25, 0),
    ("LOW_KICK", 50, "FIGHTING", 90, 20, 30),
    ("COUNTER", 1, "FIGHTING", 100, 20, 0),
    ("SEISMIC_TOSS", 1, "FIGHTING", 100, 20, 0),
    ("STRENGTH", 80, "NORMAL", 100, 15, 0),
    ("ABSORB", 20, "GRASS", 100, 20, 0),
    ("MEGA_DRAIN", 40, "GRASS", 100, 10, 0),
    ("LEECH_SEED", 0, "GRASS", 90, 10, 0),
    ("GROWTH", 0, "NORMAL", 100, 40, 0),
    ("RAZOR_LEAF", 55, "GRASS", 95, 25, 0),
    ("SOLARBEAM", 120, "GRASS", 100, 10, 0),
    ("POISONPOWDER", 0, "POISON", 75, 35, 0),
    ("STUN_SPORE", 0, "GRASS", 75, 30, 0),
    ("SLEEP_POWDER", 0, "GRASS", 75, 15, 0),
    ("PETAL_DANCE", 70, "GRASS", 100, 20, 0),
    ("STRING_SHOT", 0, "BUG", 95, 40, 0),
    ("DRAGON_RAGE", 40, "DRAGON", 100, 10, 0),
    ("FIRE_SPIN", 15, "FIRE", 70, 15, 0),
    ("THUNDERSHOCK", 40, "ELECTRIC", 100, 30, 10),
    ("THUNDERBOLT", 95, "ELECTRIC", 100, 15, 10),
    ("THUNDER_WAVE", 0, "ELECTRIC", 100, 20, 0),
    ("THUNDER", 120, "ELECTRIC", 70, 10, 30),
    ("ROCK_THROW", 50, "ROCK", 90, 15, 0),
    ("EARTHQUAKE", 100, "GROUND", 100, 10, 0),
    ("FISSURE", 1, "GROUND", 30, 5, 0),
    ("DIG", 60, "GROUND", 100, 10, 0),
    ("TOXIC", 0, "POISON", 85, 10, 0),
    ("CONFUSION", 50, "PSYCHIC", 100, 25, 10),
    ("PSYCHIC_M", 90, "PSYCHIC", 100, 10, 10),
    ("HYPNOSIS", 0, "PSYCHIC", 60, 20, 0),
    ("MEDITATE", 0, "PSYCHIC", 100, 40, 0),
    ("AGILITY", 0, "PSYCHIC", 100, 30, 0),
    ("QUICK_ATTACK", 40, "NORMAL", 100, 30, 0),
    ("RAGE", 20, "NORMAL", 100, 20, 0),
    ("TELEPORT", 0, "PSYCHIC", 100, 20, 0),
    ("NIGHT_SHADE", 1, "GHOST", 100, 15, 0),
    ("MIMIC", 0, "NORMAL", 100, 10, 0),
    ("SCREECH", 0, "NORMAL", 85, 40, 0),
    ("DOUBLE_TEAM", 0, "NORMAL", 100, 15, 0),
    ("RECOVER", 0, "NORMAL", 100, 20, 0),
    ("HARDEN", 0, "NORMAL", 100, 30, 0),
    ("MINIMIZE", 0, "NORMAL", 100, 20, 0),
    ("SMOKESCREEN", 0, "NORMAL", 100, 20, 0),
    ("CONFUSE_RAY", 0, "GHOST", 100, 10, 0),
    ("WITHDRAW", 0, "WATER", 100, 40, 0),
    ("DEFENSE_CURL", 0, "NORMAL", 100, 40, 0),
    ("BARRIER", 0, "PSYCHIC", 100, 30, 0),
    ("LIGHT_SCREEN", 0, "PSYCHIC", 100, 30, 0),
    ("HAZE", 0, "ICE", 100, 30, 0),
    ("REFLECT", 0, "PSYCHIC", 100, 20, 0),
    ("FOCUS_ENERGY", 0, "NORMAL", 100, 30, 0),
    ("BIDE", 0, "NORMAL", 100, 10, 0),
    ("METRONOME", 0, "NORMAL", 100, 10, 0),
    ("MIRROR_MOVE", 0, "FLYING", 100, 20, 0),
    ("SELFDESTRUCT", 200, "NORMAL", 100, 5, 0),
    ("EGG_BOMB", 100, "NORMAL", 75, 10, 0),
    ("LICK", 20, "GHOST", 100, 30, 30),
    ("SMOG", 20, "POISON", 70, 20, 40),
    ("SLUDGE", 65, "POISON", 100, 20, 30),
    ("BONE_CLUB", 65, "GROUND", 85, 20, 10),
    ("FIRE_BLAST", 120, "FIRE", 85, 5, 10),
    ("WATERFALL", 80, "WATER", 100, 15, 0),
    ("CLAMP", 35, "WATER", 75, 10, 0),
    ("SWIFT", 60, "NORMAL", 100, 20, 0),
    ("SKULL_BASH", 100, "NORMAL", 100, 15, 0),
    ("SPIKE_CANNON", 20, "NORMAL", 100, 15, 0),
    ("CONSTRICT", 10, "NORMAL", 100, 35, 10),
    ("AMNESIA", 0, "PSYCHIC", 100, 20, 0),
    ("KINESIS", 0, "PSYCHIC", 80, 15, 0),
    ("SOFTBOILED", 0, "NORMAL", 100, 10, 0),
    ("HI_JUMP_KICK", 85, "FIGHTING", 90, 20, 0),
    ("GLARE", 0, "NORMAL", 75, 30, 0),
    ("DREAM_EATER", 100, "PSYCHIC", 100, 15, 0),
    ("POISON_GAS", 0, "POISON", 55, 40, 0),
    ("BARRAGE", 15, "NORMAL", 85, 20, 0),
    ("LEECH_LIFE", 20, "BUG", 100, 15, 0),
    ("LOVELY_KISS", 0, "NORMAL", 75, 10, 0),
    ("SKY_ATTACK", 140, "FLYING", 90, 5, 0),
    ("TRANSFORM", 0, "NORMAL", 100, 10, 0),
    ("BUBBLE", 20, "WATER", 100, 30, 10),
    ("DIZZY_PUNCH", 70, "NORMAL", 100, 10, 20),
    ("SPORE", 0, "GRASS", 100, 15, 0),
    ("FLASH", 0, "NORMAL", 70, 20, 0),
    ("PSYWAVE", 1, "PSYCHIC", 80, 15, 0),
    ("SPLASH", 0, "NORMAL", 100, 40, 0),
    ("ACID_ARMOR", 0, "POISON", 100, 40, 0),
    ("CRABHAMMER", 90, "WATER", 85, 10, 0),
    ("EXPLOSION", 250, "NORMAL", 100, 5, 0),
    ("FURY_SWIPES", 18, "NORMAL", 80, 15, 0),
    ("BONEMERANG", 50, "GROUND", 90, 10, 0),
    ("REST", 0, "PSYCHIC", 100, 10, 0),
    ("ROCK_SLIDE", 75, "ROCK", 90, 10, 30),
    ("HYPER_FANG", 80, "NORMAL", 90, 15, 10),
    ("SHARPEN", 0, "NORMAL", 100, 30, 0),
    ("CONVERSION", 0, "NORMAL", 100, 30, 0),
    ("TRI_ATTACK", 80, "NORMAL", 100, 10, 20),
    ("SUPER_FANG", 1, "NORMAL", 90, 10, 0),
    ("SLASH", 70, "NORMAL", 100, 20, 0),
    ("SUBSTITUTE", 0, "NORMAL", 100, 10, 0),
    ("STRUGGLE", 50, "NORMAL", 100, 1, 0),
    ("SKETCH", 0, "NORMAL", 100, 1, 0),
    ("TRIPLE_KICK", 10, "FIGHTING", 90, 10, 0),
    ("THIEF", 40, "DARK", 100, 10, 100),
    ("SPIDER_WEB", 0, "BUG", 100, 10, 0),
    ("MIND_READER", 0, "NORMAL", 100, 5, 0),
    ("NIGHTMARE", 0, "GHOST", 100, 15, 0),
    ("FLAME_WHEEL", 60, "FIRE", 100, 25, 10),
    ("SNORE", 40, "NORMAL", 100, 15, 30),
    ("CURSE", 0, "???", 100, 10, 0),
    ("FLAIL", 1, "NORMAL", 100, 15, 0),
    ("CONVERSION2", 0, "NORMAL", 100, 30, 0),
    ("AEROBLAST", 100, "FLYING", 95, 5, 0),
    ("COTTON_SPORE", 0, "GRASS", 85, 40, 0),
    ("REVERSAL", 1, "FIGHTING", 100, 15, 0),
    ("SPITE", 0, "GHOST", 100, 10, 0),
    ("POWDER_SNOW", 40, "ICE", 100, 25, 10),
    ("PROTECT", 0, "NORMAL", 100, 10, 0),
    ("MACH_PUNCH", 40, "FIGHTING", 100, 30, 0),
    ("SCARY_FACE", 0, "NORMAL", 90, 10, 0),
    ("FAINT_ATTACK", 60, "DARK", 100, 20, 0),
    ("SWEET_KISS", 0, "NORMAL", 75, 10, 0),
    ("BELLY_DRUM", 0, "NORMAL", 100, 10, 0),
    ("SLUDGE_BOMB", 90, "POISON", 100, 10, 30),
    ("MUD_SLAP", 20, "GROUND", 100, 10, 100),
    ("OCTAZOOKA", 65, "WATER", 85, 10, 50),
    ("SPIKES", 0, "GROUND", 100, 20, 0),
    ("ZAP_CANNON", 100, "ELECTRIC", 50, 5, 100),
    ("FORESIGHT", 0, "NORMAL", 100, 40, 0),
    ("DESTINY_BOND", 0, "GHOST", 100, 5, 0),
    ("PERISH_SONG", 0, "NORMAL", 100, 5, 0),
    ("ICY_WIND", 55, "ICE", 95, 15, 100),
    ("DETECT", 0, "FIGHTING", 100, 5, 0),
    ("BONE_RUSH", 25, "GROUND", 80, 10, 0),
    ("LOCK_ON", 0, "NORMAL", 100, 5, 0),
    ("OUTRAGE", 90, "DRAGON", 100, 15, 0),
    ("SANDSTORM", 0, "ROCK", 100, 10, 0),
    ("GIGA_DRAIN", 60, "GRASS", 100, 5, 0),
    ("ENDURE", 0, "NORMAL", 100, 10, 0),
    ("CHARM", 0, "NORMAL", 100, 20, 0),
    ("ROLLOUT", 30, "ROCK", 90, 20, 0),
    ("FALSE_SWIPE", 40, "NORMAL", 100, 40, 0),
    ("SWAGGER", 0, "NORMAL", 90, 15, 100),
    ("MILK_DRINK", 0, "NORMAL", 100, 10, 0),
    ("SPARK", 65, "ELECTRIC", 100, 20, 30),
    ("FURY_CUTTER", 10, "BUG", 95, 20, 0),
    ("STEEL_WING", 70, "STEEL", 90, 25, 10),
    ("MEAN_LOOK", 0, "NORMAL", 100, 5, 0),
    ("ATTRACT", 0, "NORMAL", 100, 15, 0),
    ("SLEEP_TALK", 0, "NORMAL", 100, 10, 0),
    ("HEAL_BELL", 0, "NORMAL", 100, 5, 0),
    ("RETURN", 1, "NORMAL", 100, 20, 0),
    ("PRESENT", 1, "NORMAL", 90, 15, 0),
    ("FRUSTRATION", 1, "NORMAL", 100, 20, 0),
    ("SAFEGUARD", 0, "NORMAL", 100, 25, 0),
    ("PAIN_SPLIT", 0, "NORMAL", 100, 20, 0),
    ("SACRED_FIRE", 100, "FIRE", 95, 5, 50),
    ("MAGNITUDE", 1, "GROUND", 100, 30, 0),
    ("DYNAMICPUNCH", 100, "FIGHTING", 50, 5, 100),
    ("MEGAHORN", 120, "BUG", 85, 10, 0),
    ("DRAGONBREATH", 60, "DRAGON", 100, 20, 30),
    ("BATON_PASS", 0, "NORMAL", 100, 40, 0),
    ("ENCORE", 0, "NORMAL", 100, 5, 0),
    ("PURSUIT", 40, "DARK", 100, 20, 0),
    ("RAPID_SPIN", 20, "NORMAL", 100, 40, 0),
    ("SWEET_SCENT", 0, "NORMAL", 100, 20, 0),
    ("IRON_TAIL", 100, "STEEL", 75, 15, 30),
    ("METAL_CLAW", 50, "STEEL", 95, 35, 10),
    ("VITAL_THROW", 70, "FIGHTING", 100, 10, 0),
    ("MORNING_SUN", 0, "NORMAL", 100, 5, 0),
    ("SYNTHESIS", 0, "GRASS", 100, 5, 0),
    ("MOONLIGHT", 0, "NORMAL", 100, 5, 0),
    ("HIDDEN_POWER", 1, "NORMAL", 100, 15, 0),
    ("CROSS_CHOP", 100, "FIGHTING", 80, 5, 0),
    ("TWISTER", 40, "DRAGON", 100, 20, 20),
    ("RAIN_DANCE", 0, "WATER", 90, 5, 0),
    ("SUNNY_DAY", 0, "FIRE", 90, 5, 0),
    ("CRUNCH", 80, "DARK", 100, 15, 20),
    ("MIRROR_COAT", 1, "PSYCHIC", 100, 20, 0),
    ("PSYCH_UP", 0, "NORMAL", 100, 10, 0),
    ("EXTREMESPEED", 80, "NORMAL", 100, 5, 0),
    ("ANCIENTPOWER", 60, "ROCK", 100, 5, 10),
    ("SHADOW_BALL", 80, "GHOST", 100, 15, 20),
    ("FUTURE_SIGHT", 80, "PSYCHIC", 90, 15, 0),
    ("ROCK_SMASH", 20, "FIGHTING", 100, 15, 50),
    ("WHIRLPOOL", 15, "WATER", 70, 15, 0),
    ("BEAT_UP", 10, "DARK", 100, 10, 0),
]
assert len(GEN2_MOVES) == 251, f"Gen 2 move count: {len(GEN2_MOVES)} (expected 251)"


def build_entry_gen1(idx, internal, power, type_, acc, pp):
    return {
        "id": idx,
        "name": display_name(internal),
        "internal_name": internal,
        "type": normalize_type(type_),
        "power": power,
        "accuracy": acc,
        "pp": pp,
        "split": split_for(type_.replace("_TYPE", ""), power, _PHYSICAL_TYPES_GEN1, _SPECIAL_TYPES_GEN1),
    }


def build_entry_gen2(idx, internal, power, type_, acc, pp, eff_chance):
    return {
        "id": idx,
        "name": display_name(internal),
        "internal_name": internal,
        "type": normalize_type(type_),
        "power": power,
        "accuracy": acc,
        "pp": pp,
        "split": split_for(type_.replace("_TYPE", ""), power, _PHYSICAL_TYPES_GEN2, _SPECIAL_TYPES_GEN2),
        "effect_chance": eff_chance,
    }


def main():
    gen1_entries = [build_entry_gen1(i + 1, *row) for i, row in enumerate(GEN1_MOVES)]
    gen2_entries = [build_entry_gen2(i + 1, *row) for i, row in enumerate(GEN2_MOVES)]

    os.makedirs(os.path.dirname(GEN1_OUT), exist_ok=True)
    os.makedirs(os.path.dirname(GEN2_OUT), exist_ok=True)

    with open(GEN1_OUT, "w") as f:
        json.dump({"moves": gen1_entries}, f, indent=2)
    with open(GEN2_OUT, "w") as f:
        json.dump({"moves": gen2_entries}, f, indent=2)

    print(f"Wrote {len(gen1_entries)} Gen 1 moves to {GEN1_OUT}")
    print(f"Wrote {len(gen2_entries)} Gen 2 moves to {GEN2_OUT}")


if __name__ == "__main__":
    main()
