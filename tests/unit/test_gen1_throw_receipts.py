"""Throw receipts classify observed results without shortening or extending the wait."""
import re
from pathlib import Path

import lupa
import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("bundle", ["direct", "duo"])
@pytest.mark.parametrize("foundation", ["rb", "pure"])
@pytest.mark.parametrize("outcome,expected", [("caught", "caught"), ("missed", "missed"),
                                           ("not_consumed", "timeout"), ("boxed", "timeout")])
def test_throw_receipt_names_the_observed_outcome_and_preserves_wait(foundation, outcome, expected, bundle):
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    facts = lua.eval("dofile")((ROOT / f"lua/tests/gen1_{foundation}_facts.lua").as_posix())
    names = ("wTopMenuItemX", "wTopMenuItemY", "wCurrentMenuItem", "wMaxMenuItem",
             "wMenuWatchedKeys", "wIsInBattle", "wPlayerSelectedMove", "wActionResultOrTookBattleTurn",
             "hLoadedROMBank", "wListScrollOffset", "wCurItem", "wPartyCount", "wNumBagItems", "wBagItems")
    addresses = {name: 0xC100 + i * 8 for i, name in enumerate(names)}
    bus = {addresses["wTopMenuItemX"]: facts.MENU.BAG.menu_x,
           addresses["wTopMenuItemY"]: facts.MENU.BAG.menu_y,
           addresses["wMenuWatchedKeys"]: facts.MENU.BAG.watched,
           addresses["wIsInBattle"]: 1, addresses["wPartyCount"]: 6 if outcome == "boxed" else 1,
           addresses["wNumBagItems"]: 1, addresses["wBagItems"]: 4,
           addresses["wBagItems"] + 1: 3, addresses["wCurItem"]: 4}
    state = {"frames": 0, "thrown": False}

    def step(buttons=None):
        state["frames"] += 1
        if buttons and buttons["A"] and not state["thrown"]:
            state["thrown"] = True
            if outcome != "not_consumed":
                bus[addresses["wBagItems"] + 1] -= 1
            if outcome == "caught":
                bus[addresses["wPartyCount"]] += 1

    given = lua.table_from(addresses)
    if bundle == "duo":
        source = (ROOT / "lua/tests/duo/duo_gen1_main.lua").read_text(encoding="utf-8")
        hunt = source[source.index("local function hunt("):]
        literal = re.search(r"addresses = (\{.*?\}),\s*\}\)", hunt, re.S).group(1)
        given = lua.eval("function(symbols) return " + literal + " end")(given)
    driver = lua.eval("dofile")((ROOT / "lua/tests/gen1_battle_driver.lua").as_posix()).new(
        lua.table(step=step, u8=lambda addr: bus.get(int(addr), 0),
                  addresses=given, sites=lua.table(), facts=facts,
                  hook=lambda *_a: 1, unhook=lambda *_a: None, framecount=lambda: state["frames"]))
    driver.choose = lambda _name: lua.table(ok=True)
    result = driver.use_item(0, 5)
    assert result.balls_before == 3 and result.balls_after == (3 if outcome == "not_consumed" else 2)
    assert result.why == expected
    assert result.wait_why == "timeout" and result.frames_after_a == 5 and result.ok is False
    assert state["frames"] == 23
