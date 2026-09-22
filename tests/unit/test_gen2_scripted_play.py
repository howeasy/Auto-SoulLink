"""MODEL controls for lua/tests/gen2_scripted_play.lua's Mom's-house day-of-week/DST handling,
and for lua/tests/gen2_qualify.lua (the CONTINUE / native re-save qualification driver).

Pure point -> buttons/phase, same lua harness as tests/unit/test_gen2_fixtures.py (no emulator).
Passing here is authoring evidence only, never PHYSICAL evidence.

Mom's SetDayOfWeek picker (engine/rtc/timeset.asm:385-436, both pokecrystal and pokegold/pokesilver)
runs before the day-of-week/DST question chain in maps/PlayersHouse1F.asm (MeetMomScript, line 49
in pokecrystal / line 40 in pokegold). Its own confirm box ("<DAY>, is it?", ConfirmWeekdayText at
engine/rtc/timeset.asm:531-540, text at data/text/common_1.asm _OakTimeIsItText) executes through the
same shared YesNoBox routine as every other yes/no prompt in the game, so it is observed generically
as ui.kind == "yes_no" with a classified ui.prompt, exactly like mom_dst/mom_dst_confirm/mom_phone.
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


def text_point(lua, f, *, area="PlayersHouse1F", x=9, y=1):
    """A dismiss-with-A textbox observation (covers the picker's own "What day is it?" display)."""
    value = point(lua, f, area, x, y, mom_scene=0, pokegear_obtained=False)
    ui = lua.table_from({"kind": "text", "origin": f["ui_origins"]["text"]["symbol"]}, recursive=True)
    value["ui"], value["input_ready"] = ui, True
    return value


def press_then_release(d, value):
    """The driver holds a button for exactly one observed frame, then consumes one release
    frame (gen2_scripted_play.lua:121) before it will act on the next observation again."""
    buttons, phase, request = step(d, value)
    empty, phase2, _ = step(d, value)
    assert empty == {}, "expected the driver's one-frame release before the next press"
    return buttons, phase2, request

@pytest.mark.parametrize("title", TITLES)
def test_day_picker_dismiss_text_presses_a(lua, title):
    """"What day is it?" (WaitPressAorB_BlinkCursor origin) is the generic ui.kind == "text" case:
    press A. Day navigation (Up/Down) is never driven; the un-navigated default (wTempDayOfWeek =
    SUNDAY, engine/rtc/timeset.asm:398-399) is what reaches the picker's own YesNoBox confirm."""
    d, f = driver(lua, title)
    buttons, phase, _ = step(d, text_point(lua, f))
    assert buttons == {"A": True} and phase == "new-game"


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
    """One decision plus the driver's one-frame release (gen2_qualify.lua press())."""
    buttons, phase, _ = step(d, value)
    if buttons:
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
