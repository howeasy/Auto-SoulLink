"""Gen 1 trainer ids must match pret, and the JSON mirror must match the live Lua.

Two things went wrong here at once, and each hid the other.

`ENGINEER` ($0C) was missing from the class list, so every id from OPP 212 upward was one
too low. `BROCK` is $22 -> OPP 234, but 234 read "Misty", 235 read "Lt. Surge", and so on:
every gym leader, Elite Four member and rival displayed the NEXT trainer's name. `LANCE`
($2F -> 247) fell off the end entirely. Nothing failed — the lookup just returned a
plausible wrong string.

The second problem is why it survived: `data/games/gen1_rby/trainers.json` is documented as
mirroring `lua/games/gen1_rby_trainers.lua`, but no Python reads it, so the two drifted
freely and the JSON could not corroborate the Lua. The JSON is now generated from the Lua;
this test keeps them honest.

`trainer_constants.asm` is the authority: classes are a contiguous const run from NOBODY,
and `wTrainerClass` stores `OPP_ID_OFFSET (200) + const`.
"""
import json
import os
import re

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LUA = os.path.join(REPO, "lua", "games", "gen1_rby_trainers.lua")
JSON_PATH = os.path.join(REPO, "data", "games", "gen1_rby", "trainers.json")

OPP_ID_OFFSET = 200

# pret/pokered constants/trainer_constants.asm, $00-$2F in order.
PRET_ORDER = [
    "NOBODY", "YOUNGSTER", "BUG_CATCHER", "LASS", "SAILOR", "JR_TRAINER_M", "JR_TRAINER_F",
    "POKEMANIAC", "SUPER_NERD", "HIKER", "BIKER", "BURGLAR", "ENGINEER", "UNUSED_JUGGLER",
    "FISHER", "SWIMMER", "CUE_BALL", "GAMBLER", "BEAUTY", "PSYCHIC_TR", "ROCKER", "JUGGLER",
    "TAMER", "BIRD_KEEPER", "BLACKBELT", "RIVAL1", "PROF_OAK", "CHIEF", "SCIENTIST",
    "GIOVANNI", "ROCKET", "COOLTRAINER_M", "COOLTRAINER_F", "BRUNO", "BROCK", "MISTY",
    "LT_SURGE", "ERIKA", "KOGA", "BLAINE", "SABRINA", "GENTLEMAN", "RIVAL2", "RIVAL3",
    "LORELEI", "CHANNELER", "AGATHA", "LANCE",
]

# The handful whose display name must line up with a specific pret const. Spot checks on
# the ones a shift actually misroutes — the gym leaders and the rivals.
ANCHORS = {
    "BROCK": "Brock", "MISTY": "Misty", "LT_SURGE": "Lt. Surge", "ERIKA": "Erika",
    "KOGA": "Koga", "BLAINE": "Blaine", "SABRINA": "Sabrina", "GIOVANNI": "Giovanni",
    "BRUNO": "Bruno", "LORELEI": "Lorelei", "AGATHA": "Agatha", "LANCE": "Lance",
    "ENGINEER": "Engineer", "BURGLAR": "Burglar", "PROF_OAK": "Prof. Oak",
}


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _lua_block(name):
    src = _read(LUA)
    start = src.index("{", src.index(f"M.{name} = {{"))
    depth = 0
    for i in range(start, len(src)):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return src[start:i + 1]
    raise AssertionError(f"unterminated M.{name}")


def _lua_classes():
    return {int(m.group(1)): m.group(2)
            for m in re.finditer(r'\[(\d+)\]\s*=\s*"([^"]*)"', _lua_block("CLASS_NAMES"))}


def test_class_ids_match_pret_offsets():
    classes = _lua_classes()
    for const, display in ANCHORS.items():
        expected_id = PRET_ORDER.index(const) + OPP_ID_OFFSET
        assert classes.get(expected_id) == display, (
            f"{const} is pret ${PRET_ORDER.index(const):02X} -> OPP {expected_id}, which should "
            f"read {display!r} but reads {classes.get(expected_id)!r}. An inserted or omitted "
            f"class shifts every id above it."
        )


def test_class_table_is_contiguous_and_complete():
    classes = _lua_classes()
    expected = set(range(OPP_ID_OFFSET, OPP_ID_OFFSET + len(PRET_ORDER)))
    assert set(classes) == expected, (
        f"class ids must be the contiguous run {min(expected)}..{max(expected)}; "
        f"missing={sorted(expected - set(classes))} extra={sorted(set(classes) - expected)}"
    )


def test_rival_ids_are_the_three_pret_rival_classes():
    src = _read(LUA)
    ids = [int(x) for x in re.search(r"M\.RIVAL_CLASS_IDS\s*=\s*\{([^}]*)\}", src).group(1).split(",")]
    expected = [PRET_ORDER.index(c) + OPP_ID_OFFSET for c in ("RIVAL1", "RIVAL2", "RIVAL3")]
    assert ids == expected, f"rival class ids should be {expected} (RIVAL1/2/3 + 200), got {ids}"


def test_json_mirror_matches_lua():
    """The JSON is generated from the Lua; nothing in Python reads it, so only this holds it true."""
    data = json.loads(_read(JSON_PATH))
    assert {int(k): v for k, v in data["classes"].items()} == _lua_classes(), (
        "data/games/gen1_rby/trainers.json has drifted from lua/games/gen1_rby_trainers.lua"
    )
