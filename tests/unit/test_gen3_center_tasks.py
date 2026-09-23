"""C4-UR: SLink writes land inside Pokemon Centers (PLAN s0, owner ruling 2026-09-23).

Every FRLG/RR Center 1F runs CableClub_OnResume -> special InitUnionRoom (pret c75f3523
data/scripts/cable_club.inc:1120-1122), which leaves the rev-0 Union Room background tasks
active.  The overworld checkpoint must ADMIT that world and still REFUSE once a link session
starts.  The addresses are literal on purpose (the live pc-exit dump listed 081199FD, 08119D35,
080F8B35 on FR): the falsifier must not read the allow-list it is testing.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "tests" / "unit"))
import gen_gen3_write_checkpoint as G  # noqa: E402
from test_gen3_safety import World  # noqa: E402

# Task_InitUnionRoom, Task_SearchForChildOrParent, Task_UnionRoomListen (even, Thumb bit off).
# RR keeps the FR bodies byte-identical at the FR addresses (gen_gen3_write_checkpoint ok_code).
CENTER = {
    "firered": (0x081199FC, 0x08119D34, 0x080F8B34),
    "leafgreen": (0x081199D4, 0x08119D0C, 0x080F8B0C),
    "radical_red": (0x081199FC, 0x08119D34, 0x080F8B34),
}
FIELD = ("Task_RunPerStepCallback", "Task_RunTimeBasedEvents", "Task_WeatherMain")
# What appears when "background only" ends (pret c75f3523):
SESSION = (
    "Task_PlayerExchange",               # link_rfu_2.c:541/559 -- a partner link is up
    "Task_PlayerExchangeChat",           # link_rfu_2.c:539
    "Task_TryConnectToUnionRoomParent",  # link_rfu_2.c:2519/3025
    "Task_RunUnionRoom",                 # union_room.c:2579-2584, Union Room ON_RESUME
    "Task_StartActivity",                # union_room.c:1872 -- trade/battle/chat start
    "Task_TryBecomeLinkLeader",          # union_room.c:382-396 -- 2F attendant
    "Task_TryJoinLinkGroup",             # union_room.c:1126-1146 -- 2F attendant
    "Task_TriggerHandshake",             # link.c:404 -- cable OpenLink
)
CASES = [("firered", "clean"), ("leafgreen", "clean"),
         ("radical_red", "clean"), ("radical_red", "companion")]


def sym_file(title: str) -> str:
    return "pokeleafgreen.sym" if title == "leafgreen" else "pokefirered.sym"


def center_world(title: str, kind: str, extra: int | None = None) -> World:
    """The three field tasks + the Center background set (+ one extra task) in gTasks."""
    w = World(title, kind)
    g, t = w.lua.globals(), w.pack["tasks"]
    syms = G.parse_sym(G.SYM_DIR / sym_file(title))
    for i in range(t["count"] * t["struct_size"]):
        g.mem[t["address"] + i] = 0
    funcs = [syms[n][0] for n in FIELD] + list(CENTER[title]) + ([extra] if extra else [])
    for i, fn in enumerate(funcs):
        base = t["address"] + i * t["struct_size"]
        g.put(base + t["func_offset"], fn | 1, 4)
        g.put(base + t["is_active_offset"], 1, 1)
    return w


@pytest.mark.parametrize("title", ["firered", "leafgreen"])
def test_center_addresses_are_the_sym(title):
    syms = G.parse_sym(G.SYM_DIR / sym_file(title))
    assert CENTER[title] == tuple(syms[n][0] for n in G.CENTER_UNION_ROOM_TASKS)


@pytest.mark.parametrize("title,kind", CASES)
def test_center_world_is_admitted(title, kind):
    ok, why, clauses = center_world(title, kind).check_reason("overworld")
    assert (ok, why, clauses) == (True, "verified overworld checkpoint", [])


@pytest.mark.parametrize("title,kind", CASES)
@pytest.mark.parametrize("task", SESSION)
def test_link_session_task_in_a_center_is_refused(title, kind, task):
    fn = G.parse_sym(G.SYM_DIR / sym_file(title))[task][0]
    ok, why, clauses = center_world(title, kind, fn).check_reason("overworld")
    assert ok is False and clauses == ["task"] and "unknown active task" in why


@pytest.mark.parametrize("title,kind", CASES)
def test_link_players_received_in_a_center_is_refused(title, kind):
    w = center_world(title, kind)
    p = w.pack["predicates"]["link_players_received"]
    w.lua.globals().put(p["address"] + p["offset"], 1, p["width"])
    assert w.check_reason("overworld")[2] == ["link_players_received"]


def test_no_session_task_is_allowed():
    assert not set(SESSION) & set(G.ALLOWED_TASKS)
