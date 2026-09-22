"""MODEL controls for lua/tests/gen2_scripted_play.lua's Mom's-house day-of-week/DST handling.

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

import pytest

from tests.unit.test_gen2_fixtures import driver, lua, point, step  # noqa: F401  (fixture + helpers)

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
