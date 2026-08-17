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

`trainer_constants.asm` is the authority: classes are a contiguous const run from NOBODY.

THE THIRD PROBLEM, AND THIS FILE USED TO ENSHRINE IT. The line above used to end
"...and `wTrainerClass` stores `OPP_ID_OFFSET (200) + const`." That is false, and every
assertion here was built on it, so the suite stayed green while the feature was dead.
pokered stores the class into `wTrainerClass` only AFTER subtracting the offset:

    ld a, [wEnemyMonSpecies2] / sub OPP_ID_OFFSET
    jp c, InitWildBattle      / ld [wTrainerClass], a
    (engine/battle/core.asm:6673-6677; pokeyellow engine/battle/init_battle.asm:33-36)

so that byte holds the RAW const `$00-$2F`. The tables below are keyed 200-247, so the
client's lookup missed for every trainer in the game and `resolve()` returned `("", "")`
— no opponent name or class ever reached the server, and nothing failed.

`wCurOpponent` is the byte that keeps the +200 form (`home/trainers.asm:233-237` stores
`wEngagedTrainerClass` and compares it against `OPP_ID_OFFSET` to decide trainer-vs-wild),
which is why `rival_trainer_ids()` was correct all along. The two readers must stay
different, so `test_client_reads_class_from_cur_opponent` pins the READING CONVENTION
rather than the table contents — the thing this file previously could not see.
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


CLIENT = os.path.join(REPO, "lua", "clients", "gen1_rby_client.lua")


def test_client_reads_class_from_cur_opponent():
    """The tables above are keyed 200-247, so the class MUST come from wCurOpponent.

    Reading `wTrainerClass` instead yields the raw const `$00-$2F`, every lookup
    misses, and `resolve()` returns ("", "") for every trainer in the game — with
    no error anywhere. Nothing else in the suite can see that, because the tables
    themselves are correct.
    """
    src = _read(CLIENT)
    calls = re.findall(r"TRAINERS\.resolve\((\w+)\s*,", src)
    assert calls, "gen1_rby_client.lua never calls TRAINERS.resolve"
    for var in calls:
        # The variable handed to resolve() must have been read from CUR_OPPONENT_ADDR.
        assigned = re.findall(rf"local\s+{var}\s*=\s*M\.read_u8\(M\.(\w+)\)", src)
        assert assigned, f"could not find where {var!r} is assigned before TRAINERS.resolve"
        for addr in assigned:
            assert addr == "CUR_OPPONENT_ADDR", (
                f"TRAINERS.resolve() is fed {var} read from M.{addr}. The class tables are "
                f"keyed OPP_ID_OFFSET(200)+const, and only wCurOpponent carries that form; "
                f"wTrainerClass holds the raw const because pokered subtracts the offset "
                f"before storing it (engine/battle/core.asm:6673-6677)."
            )


def test_trainer_class_addr_is_not_used_for_name_lookup():
    """Belt and braces: the wrong address should not appear in the client at all."""
    src = _read(CLIENT)
    assert "TRAINER_CLASS_ADDR" not in src, (
        "gen1_rby_client.lua still references TRAINER_CLASS_ADDR; it holds the raw "
        "class const and is not what the 200-based tables are keyed by"
    )
