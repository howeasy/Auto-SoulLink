"""Gen 1 trainer ids must match pret, and the client must read the byte the table is keyed by.

`ENGINEER` ($0C) was missing from the class list, so every id from OPP 212 upward was one
too low. `BROCK` is $22 -> OPP 234, but 234 read "Misty", 235 read "Lt. Surge", and so on:
every gym leader, Elite Four member and rival displayed the NEXT trainer's name. `LANCE`
($2F -> 247) fell off the end entirely. Nothing failed — the lookup just returned a
plausible wrong string.

`trainer_constants.asm` is the authority: classes are a contiguous const run from NOBODY.

THE SECOND PROBLEM, AND THIS FILE USED TO ENSHRINE IT. The line above used to end
"...and `wTrainerClass` stores `OPP_ID_OFFSET (200) + const`." That is false, and every
assertion here was built on it, so the suite stayed green while the feature was dead.
pokered stores the class into `wTrainerClass` only AFTER subtracting the offset:

    ld a, [wEnemyMonSpecies2] / sub OPP_ID_OFFSET
    jp c, InitWildBattle      / ld [wTrainerClass], a
    (engine/battle/core.asm:6673-6677; pokeyellow engine/battle/init_battle.asm:33-36)

so that byte holds the RAW const `$00-$2F`. The tables are keyed 200-247, so a lookup fed
`wTrainerClass` misses for every trainer in the game and returns ("", "") with nothing
raised. `wCurOpponent` is the byte that keeps the +200 form (`home/trainers.asm:233-237`),
which is why `rival_trainer_ids()` was correct all along. The two readers must stay
different, so the reading convention is pinned below rather than the table contents.

P8-2b: the table moved out of `lua/games/gen1_rby_trainers.lua`. Nothing in Lua carries
trainer names any more — `data/games/gen1_rby/trainers.json` IS the table, read by
server/adapters/gen1_rby.py:386, so the JSON is checked against pret directly instead of
against a Lua mirror it used to be generated from.
"""
import json
import os
import re

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
JSON_PATH = os.path.join(REPO, "data", "games", "gen1_rby", "trainers.json")
READS = os.path.join(REPO, "lua", "gen1", "reads.lua")
CLIENT = os.path.join(REPO, "lua", "gen1", "client.lua")

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


def _classes():
    return {int(k): v for k, v in json.loads(_read(JSON_PATH))["classes"].items()}


def test_class_ids_match_pret_offsets():
    classes = _classes()
    for const, display in ANCHORS.items():
        expected_id = PRET_ORDER.index(const) + OPP_ID_OFFSET
        assert classes.get(expected_id) == display, (
            f"{const} is pret ${PRET_ORDER.index(const):02X} -> OPP {expected_id}, which should "
            f"read {display!r} but reads {classes.get(expected_id)!r}. An inserted or omitted "
            f"class shifts every id above it."
        )


def test_class_table_is_contiguous_and_complete():
    classes = _classes()
    expected = set(range(OPP_ID_OFFSET, OPP_ID_OFFSET + len(PRET_ORDER)))
    assert set(classes) == expected, (
        f"class ids must be the contiguous run {min(expected)}..{max(expected)}; "
        f"missing={sorted(expected - set(classes))} extra={sorted(set(classes) - expected)}"
    )


def test_the_adapter_resolves_a_named_trainer_through_that_table():
    """The consumer: nothing else in Python reads trainers.json, so an id shift shows up
    only as a wrong name on the board."""
    from server.adapters import get_adapter
    a = get_adapter("gen1_rby", rom_type="Red")
    brock = PRET_ORDER.index("BROCK") + OPP_ID_OFFSET
    assert a.trainer_info(brock)[1] == "Brock"


def test_the_client_reads_the_class_from_cur_opponent_not_wtrainerclass():
    """The tables are keyed 200-247, so the class MUST come from wCurOpponent.

    Reading `wTrainerClass` instead yields the raw const `$00-$2F`, every lookup misses,
    and no opponent name or class ever reaches the server — with no error anywhere.
    """
    src = _read(READS)
    m = re.search(r"local opponent = io\.read_u8\(a\.wCurOpponent\)", src)
    assert m, "lua/gen1/reads.lua no longer reads wCurOpponent for the battle record"
    assert re.search(r"is_trainer = opponent >= 200", src), (
        "the trainer test must be on the +200 form that wCurOpponent carries")
    assert re.search(r"trainer_class = opponent >= 200 and opponent - 200", src), (
        "trainer_class must be derived from wCurOpponent by subtracting OPP_ID_OFFSET")
    assert "wTrainerClass" not in src and "wTrainerClass" not in _read(CLIENT), (
        "the rewritten client references wTrainerClass; it holds the raw class const and is "
        "not what the 200-based tables are keyed by")


def test_the_wire_carries_the_two_hundred_form():
    """The server looks the id up in trainers.json, so the client must not pre-subtract."""
    src = _read(CLIENT)
    assert re.search(r'trainer_battle_start", \{ trainer_id = pt\.cur_opponent \}', src), (
        "trainer_battle_start must send wCurOpponent, the byte the class table is keyed by")
