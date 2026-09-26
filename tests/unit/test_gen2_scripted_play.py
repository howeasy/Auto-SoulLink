"""MODEL controls for lua/tests/gen2_scripted_play.lua's Mom's-house day-of-week/DST handling,
and for lua/tests/gen2_qualify.lua (the CONTINUE / native re-save qualification driver).

Pure point -> buttons/phase, same lua harness as tests/unit/test_gen2_fixtures.py (no emulator).
Passing here is authoring evidence only, never PHYSICAL evidence.

Map-script texts wait in PromptButton (home/joypad.asm:383-431, its .input_wait_loop :411-421) or
WaitButton (:302-309, looping in JoyWaitAorB :292-300); OWPlayerInput does not run while a script runs
(engine/overworld/events.asm:241-246), so these are UI origins of their own, fed with their real
route-fact symbols here, never a synthetic "text" kind. Mom's SetDayOfWeek picker
(engine/rtc/timeset.asm:385-436, both pokecrystal and pokegold/pokesilver) waits in .loop2 (:420-423)
before its own confirm YesNoBox ("<DAY>, is it?", _OakTimeIsItText), which is observed generically as
ui.kind == "yes_no" with a classified ui.prompt, exactly like mom_dst/mom_dst_confirm/mom_phone.
"""
from __future__ import annotations

import json

import pytest

from tests.unit.test_gen2_fixtures import (  # noqa: F401  (fixture + helpers)
    ROOT,
    driver,
    facts,
    lua,
    point,
    step,
)
from tools import gen2_fixtures as g

TITLES = ("crystal", "gold", "silver")


def yes_no_point(lua, f, prompt, cursor, *, area="PlayersHouse1F", x=9, y=1):
    """A yes/no prompt observation: two-item vertical Yes/No box at the given cursor position."""
    value = point(lua, f, area, x, y, mom_scene=0, pokegear_obtained=False)
    ui = lua.table_from({"kind": "yes_no", "origin": f["ui_origins"]["yes_no"]["symbol"], "prompt": prompt,
                         "items": lua.table_from(["YES", "NO"]), "cursor": cursor, "columns": 1}, recursive=True)
    value["ui"], value["input_ready"] = ui, True
    return value


def origin_point(lua, f, kind, *, area="PlayersHouse1F", x=9, y=1, origin=None, **fields):
    """A script-state observation: a bound wait origin is running and overworld input is not."""
    value = point(lua, f, area, x, y, mom_scene=0, pokegear_obtained=False, overworld_ready=False, **fields)
    symbol = origin or f["ui_origins"][kind]["symbol"]
    value["ui"], value["input_ready"] = lua.table_from({"kind": kind, "origin": symbol}), True
    return value


HOLD = 12  # lua/tests/gen2_scripted_play.lua / gen2_qualify.lua press(): frames a native press is held


def press_then_release(d, value):
    """The driver holds a native press for exactly HOLD observed frames (a menu loop may sample input
    only once per WaitBGMap iteration), then consumes one release frame before acting again."""
    buttons, phase, request = step(d, value)
    for _ in range(HOLD - 1):
        assert step(d, value)[0] == buttons, "expected the press held for HOLD frames"
    empty, phase2, _ = step(d, value)
    assert empty == {}, "expected the driver's one-frame release before the next press"
    return buttons, phase2, request

WAITS = {"prompt_button": "PromptButton.input_wait_loop", "wait_button": "JoyWaitAorB",
         "day_picker": "SetDayOfWeek.loop2"}


@pytest.mark.parametrize("title", TITLES)
@pytest.mark.parametrize("kind", WAITS)
def test_script_wait_origins_are_answered_with_a(lua, title, kind):
    """Mom's `writetext ... / promptbutton` (maps/PlayersHouse1F.asm:36-38), the script `waitbutton`s and
    the weekday picker's .loop2: each is its real source symbol and each gets A. On the picker A accepts
    the shown day; Up/Down are never driven, so the un-navigated default (wTempDayOfWeek = SUNDAY,
    engine/rtc/timeset.asm:398-399) reaches the picker's own YesNoBox confirm."""
    d, f = driver(lua, title)
    assert f["ui_origins"][kind]["symbol"] == WAITS[kind]
    buttons, phase, _ = step(d, origin_point(lua, f, kind))
    assert buttons == {"A": True} and phase == "new-game"


@pytest.mark.parametrize("title", TITLES)
def test_unmapped_script_state_idles_or_refuses_never_presses(lua, title):
    """No blind fallback: a script running with no bound origin idles; an unknown or mis-bound origin refuses."""
    d, f = driver(lua, title)
    idle = point(lua, f, "PlayersHouse1F", 9, 1, mom_scene=0, pokegear_obtained=False, overworld_ready=False)
    assert step(d, idle)[:2] == ({}, "new-game")
    for kind, origin in (("script_text", "PrintText"), ("prompt_button", "WaitPressAorB_BlinkCursor")):
        buttons, why, _ = step(d, origin_point(lua, f, kind, origin=origin))
        assert buttons is None and "unmapped or unbound" in why


@pytest.mark.parametrize("title", TITLES)
def test_day_confirm_prompt_is_recognized_and_answered_yes_from_cursor_on_yes(lua, title):
    d, f = driver(lua, title)
    buttons, phase, _ = step(d, yes_no_point(lua, f, "day_confirm", cursor=1))
    assert buttons == {"A": True} and phase == "new-game"


@pytest.mark.parametrize("title", TITLES)
def test_day_confirm_prompt_navigates_up_from_cursor_on_no(lua, title):
    """Cursor starts on NO (index 2); the driver must move up to YES before confirming, never
    accept the picker's default cursor position blind."""
    d, f = driver(lua, title)
    buttons, phase, _ = step(d, yes_no_point(lua, f, "day_confirm", cursor=2))
    assert buttons == {"Up": True} and phase == "new-game"


@pytest.mark.parametrize("title", TITLES)
def test_day_confirm_reasserts_yes_every_time_the_game_loops_back_on_no(lua, title):
    """A real "No" answer on the picker's own confirm (engine/rtc/timeset.asm:429 jr c, .loop) or on
    the DST question chain (maps/PlayersHouse1F.asm .SetDayOfWeek loop) redraws the same prompt.
    The driver is stateless per observation, so it answers YES again exactly as it did the first
    time: the loop converges without any dedicated loop-back bookkeeping."""
    d, f = driver(lua, title)
    for _ in range(3):
        buttons, phase, _ = press_then_release(d, yes_no_point(lua, f, "day_confirm", cursor=1))
        assert buttons == {"A": True} and phase == "new-game"


@pytest.mark.parametrize("title", TITLES)
def test_mom_dst_chain_prompts_remain_answered_yes_alongside_day_confirm(lua, title):
    """Regression: adding day_confirm must not disturb the existing DST question chain (mom_dst,
    mom_dst_confirm, mom_phone) that follows SetDayOfWeek in the same MeetMomScript."""
    d, f = driver(lua, title)
    for prompt in ("mom_dst", "mom_dst_confirm", "mom_phone"):
        buttons, phase, _ = press_then_release(d, yes_no_point(lua, f, prompt, cursor=1))
        assert buttons == {"A": True} and phase == "new-game"


@pytest.mark.parametrize("title", TITLES)
def test_unclassified_yes_no_prompt_still_refuses(lua, title):
    """A prompt the classifier could not bind to a known anchor (ui.prompt is nil, e.g. because a
    live gate lacks a PROMPT_ANCHORS entry) must still refuse rather than guess a button."""
    d, f = driver(lua, title)
    buttons, why, _ = step(d, yes_no_point(lua, f, None, cursor=1))
    assert buttons is None and "unmapped yes/no prompt" in why


# --- lua/tests/gen2_qualify.lua: CONTINUE / re-save driver (pure; no emulator) -------------------

FP = "cd" * 32
DONE = {"continue": 1, "continue_loaded": 1, "rtc_ok": 1, "restart_clock": 0, "finish_continue": 1,
        "same_save_file": 0, "erase_save": 0}
_QFACTS = {}


def qdriver(lua, title="crystal", stage="boot"):
    if title not in _QFACTS:
        _QFACTS[title] = g.qualify_facts(title, ROOT)
    Q = lua.execute((ROOT / "lua/tests/gen2_qualify.lua").read_text(encoding="utf-8"))
    f = facts(title)

    def table(value):
        return lua.table_from(json.loads(json.dumps(value)), recursive=True)

    case = {"name": f"{title}_town", "title": title, "attempt_id": "model", "stage": stage, "stage_fingerprint": FP}
    return Q.new(table(f), table(_QFACTS[title]), lua.table_from(case)), f, _QFACTS[title]


def qpoint(lua, f, *, hits=None, ui=None, overworld=False, saves=0, **fields):
    row = {"title": f["title"], "rom_sha1": f["rom_sha1"], "core_mode": "CGB", "attempt_id": "model",
           "facts_fingerprint": f["fingerprint"], "stage_fingerprint": FP, "overworld_ready": overworld,
           "battle_mode": 0, "save_success_counter": saves, "input_ready": True}
    row.update(fields)
    value = lua.table_from(row)
    value["hits"] = lua.table_from({**dict.fromkeys(DONE, 0), **(hits or {})})
    if ui is not None:
        value["ui"] = lua.table_from({**ui, "items": lua.table_from(ui.get("items", []))})
    return value


def ui(f, q, kind, **fields):
    site = f["ui_origins"].get(kind) or q["ui_origins"][kind]
    return {"kind": kind, "origin": site["symbol"], "columns": 1, **fields}


def act(d, value):
    """One decision, held for HOLD frames, plus the one-frame release (gen2_qualify.lua press())."""
    buttons, phase, _ = step(d, value)
    if buttons:
        for _ in range(HOLD - 1):
            assert step(d, value)[0] == buttons
        assert step(d, value)[0] == {}
    return buttons, phase


def continue_into_overworld(lua, d, f, q):
    assert act(d, qpoint(lua, f, ui=ui(f, q, "title"))) == ({"Start": True}, "title")
    menu = ui(f, q, "main_menu", items=["NEW GAME", "CONTINUE", "OPTION"], cursor=1)
    assert act(d, qpoint(lua, f, ui=menu)) == ({"Down": True}, "continue")
    assert act(d, qpoint(lua, f, ui={**menu, "cursor": 2})) == ({"A": True}, "continue")
    assert act(d, qpoint(lua, f, ui=ui(f, q, "continue_confirm"), hits={"continue": 1})) == ({"A": True}, "continue")


@pytest.mark.parametrize("title", TITLES)
def test_qualify_boot_continues_into_the_overworld_and_stops(lua, title):
    d, f, q = qdriver(lua, title)
    continue_into_overworld(lua, d, f, q)
    assert act(d, qpoint(lua, f, overworld=True, hits=DONE)) == ({}, "loaded")
    assert d.terminal == "loaded" and act(d, qpoint(lua, f, overworld=True, hits=DONE)) == ({}, "loaded")


def test_qualify_overworld_without_the_native_continue_path_refuses(lua):
    d, f, q = qdriver(lua)
    continue_into_overworld(lua, d, f, q)
    buttons, why = act(d, qpoint(lua, f, overworld=True, hits={**DONE, "finish_continue": 0}))
    assert buttons is None and "native CONTINUE path" in why
    d, f, q = qdriver(lua)
    buttons, why = act(d, qpoint(lua, f, overworld=True, hits=DONE))
    assert buttons is None and "native CONTINUE path" in why


@pytest.mark.parametrize("hits,match", [({"restart_clock": 1}, "RestartClock"), ({"erase_save": 1}, "ErasePreviousSave")])
def test_qualify_refuses_an_rtc_reset_or_an_erased_save_at_any_point(lua, hits, match):
    d, f, q = qdriver(lua)
    buttons, why = act(d, qpoint(lua, f, ui=ui(f, q, "title"), hits=hits))
    assert buttons is None and match in why


def test_qualify_refuses_a_foreign_stage_a_reset_and_unmapped_ui(lua):
    d, f, q = qdriver(lua)
    buttons, why = act(d, qpoint(lua, f, ui=ui(f, q, "title"), stage_fingerprint="00" * 32))
    assert buttons is None and "foreign" in why
    d, f, q = qdriver(lua)
    continue_into_overworld(lua, d, f, q)
    buttons, why = act(d, qpoint(lua, f, ui=ui(f, q, "main_menu", items=["CONTINUE"], cursor=1)))
    assert buttons is None and "reset to main menu" in why
    d, f, q = qdriver(lua)
    buttons, why = act(d, qpoint(lua, f, ui=ui(f, q, "text")))
    assert buttons is None and "not valid for qualification" in why


def overwrite_wait(f, q):
    """_AlreadyASaveFileText's `cont` wait (PromptButton), classified by its first line."""
    return ui(f, q, "prompt_button", prompt="save_overwrite_text")


def into_save_confirm(lua, d, f, q):
    continue_into_overworld(lua, d, f, q)
    act(d, qpoint(lua, f, overworld=True, hits=DONE))
    act(d, qpoint(lua, f, ui=ui(f, q, "start_menu", items=["SAVE"], cursor=1), hits=DONE))


@pytest.mark.parametrize("kind", ["prompt_button", "wait_button", "day_picker"])
def test_qualify_refuses_script_wait_origins(lua, kind):
    """Outside the overwrite text a PromptButton/WaitButton/picker wait refuses: at CONTINUE, in the
    overworld, at the save menu before YES, and even carrying the overwrite text's classification."""
    for where in ("title", "continue_confirm", "overworld", "save_menu"):
        d, f, q = qdriver(lua, stage="resave")
        if where == "continue_confirm":
            act(d, qpoint(lua, f, ui=ui(f, q, "title")))
            act(d, qpoint(lua, f, ui=ui(f, q, "main_menu", items=["CONTINUE"], cursor=1)))
        elif where == "overworld":
            continue_into_overworld(lua, d, f, q)
        elif where == "save_menu":
            into_save_confirm(lua, d, f, q)
        wait = ui(f, q, kind, prompt="save_overwrite_text")
        buttons, why = act(d, qpoint(lua, f, ui=wait, hits=DONE))
        assert buttons is None and f"not valid for qualification: {kind}" in why, where


def test_qualify_resave_answers_the_overwrite_text_wait_only_on_its_source_text(lua):
    """(a) save_confirm YES -> the `cont` PromptButton wait -> the same-player overwrite YES -> saved."""
    d, f, q = qdriver(lua, stage="resave")
    into_save_confirm(lua, d, f, q)
    same = {**DONE, "same_save_file": 1}
    assert act(d, qpoint(lua, f, ui=ui(f, q, "yes_no", items=["YES", "NO"], cursor=1, prompt="save_confirm"),
                         hits=DONE)) == ({"A": True}, "save")
    unbound = ui(f, q, "prompt_button", prompt="save_confirm")
    buttons, why = act(d, qpoint(lua, f, ui=unbound, hits=same))
    assert buttons is None and "not valid for qualification: prompt_button" in why
    d, f, q = qdriver(lua, stage="resave")
    into_save_confirm(lua, d, f, q)
    act(d, qpoint(lua, f, ui=ui(f, q, "yes_no", items=["YES", "NO"], cursor=1, prompt="save_confirm"), hits=DONE))
    assert act(d, qpoint(lua, f, ui=overwrite_wait(f, q), hits=same)) == ({"A": True}, "save")
    assert act(d, qpoint(lua, f, ui=overwrite_wait(f, q), hits=same)) == ({"A": True}, "save")   # re-pulse
    box = ui(f, q, "yes_no", items=["YES", "NO"], cursor=1, prompt="save_overwrite")
    assert act(d, qpoint(lua, f, ui=box, hits=same)) == ({"A": True}, "save")
    # (c) after the overwrite answer the window is closed: a further text wait refuses.
    buttons, why = act(d, qpoint(lua, f, ui=overwrite_wait(f, q), hits=same))
    assert buttons is None and "not valid for qualification: prompt_button" in why


def test_qualify_prompt_button_after_the_save_witness_never_presses(lua):
    """(c) once the native save witness counted, the stage is terminal: no A reaches any later wait."""
    d, f, q = qdriver(lua, stage="resave")
    into_save_confirm(lua, d, f, q)
    same = {**DONE, "same_save_file": 1}
    act(d, qpoint(lua, f, ui=ui(f, q, "yes_no", items=["YES", "NO"], cursor=1, prompt="save_confirm"), hits=DONE))
    assert act(d, qpoint(lua, f, ui=overwrite_wait(f, q), hits=same, saves=1)) == ({}, "resaved")
    assert act(d, qpoint(lua, f, ui=overwrite_wait(f, q), hits=same, saves=1)) == ({}, "resaved")


def test_qualify_resave_saves_through_start_and_the_same_player_overwrite(lua):
    d, f, q = qdriver(lua, stage="resave")
    continue_into_overworld(lua, d, f, q)
    assert act(d, qpoint(lua, f, overworld=True, hits=DONE)) == ({"Start": True}, "save")
    menu = ui(f, q, "start_menu", items=["POKéMON", "PACK", "POKéGEAR", "CHRIS", "SAVE", "OPTION", "EXIT"], cursor=5)
    assert act(d, qpoint(lua, f, ui=menu, hits=DONE)) == ({"A": True}, "save")

    def yes_no(prompt, cursor=1):
        return ui(f, q, "yes_no", items=["YES", "NO"], cursor=cursor, prompt=prompt)

    assert act(d, qpoint(lua, f, ui=yes_no("save_confirm", 2), hits=DONE)) == ({"Up": True}, "save")
    assert act(d, qpoint(lua, f, ui=yes_no("save_confirm"), hits=DONE)) == ({"A": True}, "save")
    same = {**DONE, "same_save_file": 1}
    assert act(d, qpoint(lua, f, ui=yes_no("save_overwrite"), hits=same)) == ({"A": True}, "save")
    assert act(d, qpoint(lua, f, overworld=True, hits=same, saves=1)) == ({}, "resaved")
    assert d.terminal == "resaved"


def test_qualify_resave_refuses_another_players_overwrite_and_unknown_prompts(lua):
    for prompt, hits, match in (("save_overwrite", DONE, "same-player"), ("nickname", DONE, "unmapped yes/no")):
        d, f, q = qdriver(lua, stage="resave")
        continue_into_overworld(lua, d, f, q)
        act(d, qpoint(lua, f, overworld=True, hits=DONE))
        menu = ui(f, q, "start_menu", items=["SAVE"], cursor=1)
        act(d, qpoint(lua, f, ui=menu, hits=DONE))
        box = ui(f, q, "yes_no", items=["YES", "NO"], cursor=1, prompt=prompt)
        buttons, why = act(d, qpoint(lua, f, ui=box, hits=hits))
        assert buttons is None and match in why
