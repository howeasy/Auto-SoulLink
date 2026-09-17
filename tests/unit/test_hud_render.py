"""HUD-1/HUD-2: lua/hud.lua under lupa, against a recording `gui` stub.

BizHawk's lua draw surface is persistent: gui.drawText/gui.drawBox paint pixels that stay
until something overdraws them or the surface is cleared (EmuHawk 2.11 API docs,
`_docs_luacats/gui.d.lua:21-25` -- "clears all lua drawn graphics from the screen"). Painting
a fully transparent box over the old area erases nothing, so an expired banner used to sit
on-screen forever. What is tested here is therefore not "does it paint" but "does the surface
end each frame in the right visible state" -- a live message's box+text must still be on the
surface when the frame is done, an expired message or an explicit H.clear() must leave nothing.

The stub tracks visible state itself (drawBox/drawText mark the surface dirty, clearGraphics
wipes it) rather than just recording call names, so a bug that clears AFTER drawing -- which a
call-order-only check based on "clear appears somewhere in the call list" would miss -- shows
up as the surface ending the frame empty.

gui.cleartext is stubbed too (BizHawk exposes it) but hud.lua must never call it: per
`_docs_luacats/gui.d.lua:34-39` it clears only text drawn with the separate gui.text() API,
which the diagnostic harnesses under lua/tests use and hud.lua does not -- see hud.lua's
clear_surface(). The stub tracks calls to it separately so a regression that reintroduces the
call is visible without erasing the harnesses' actual output.

The stub is written in Lua (not a lupa-wrapped Python callable) so that hud.lua's
`type(gui.clearGraphics) == "function"` guards see a real function.
"""
from __future__ import annotations

import pathlib

import lupa

REPO = pathlib.Path(__file__).resolve().parents[2]
HUD = (REPO / "lua" / "hud.lua").as_posix()

# `state` mirrors what would actually be visible on the BizHawk lua surface:
# drawBox/drawText mark it dirty, clearGraphics wipes it. cleartext_calls is a
# separate tally -- BizHawk's gui.cleartext only affects gui.text() output
# (never drawn by hud.lua), so it must NOT be treated as clearing box/text.
GUI_STUB = """
return function(rec)
  local state = {box = false, text = false, cleartext_calls = 0}
  gui = {
    clearGraphics = function(...)
      rec("clearGraphics")
      state.box = false
      state.text = false
    end,
    cleartext = function(...)
      rec("cleartext")
      state.cleartext_calls = state.cleartext_calls + 1
    end,
    drawBox = function(...)
      rec("drawBox")
      state.box = true
    end,
    drawText = function(...)
      rec("drawText")
      state.text = true
    end,
  }
  return state
end
"""


class World:
    def __init__(self):
        self.calls: list[str] = []
        self.lua = lupa.LuaRuntime(unpack_returned_tuples=True)
        self.state = self.lua.execute(GUI_STUB)(self.calls.append)
        self.H = self.lua.eval(f'dofile("{HUD}")')

    def render(self):
        """One frame; returns just that frame's gui calls, in order."""
        mark = len(self.calls)
        self.H.render()
        return self.calls[mark:]


def test_expired_message_frame_clears_and_draws_nothing():
    """duration 2 -> the third render ends with an empty surface: no box, no text visible."""
    w = World()
    w.H.show("LINKED: PIKACHU", 255, 255, 0, 2)
    w.render()  # frame 1, live
    w.render()  # frame 2, last live frame
    w.render()  # frame 3, expired
    assert w.state.box is False
    assert w.state.text is False
    assert w.state.cleartext_calls == 0


def test_live_message_ends_the_frame_with_box_and_text_visible():
    """A live message's box+text must both still be on the surface once the frame is done.

    Catches a clear placed after the draws, or between drawBox and drawText: either leaves
    state.box and/or state.text false because clearGraphics resets them on the way through.
    """
    w = World()
    w.H.show("STILL HERE", 255, 255, 0, 240)
    frame = w.render()
    assert "drawText" in frame, frame
    assert w.state.box is True
    assert w.state.text is True
    assert w.state.cleartext_calls == 0


def test_explicit_clear_wipes_the_surface_once():
    """H.clear() takes effect immediately rather than waiting for the next render."""
    w = World()
    w.H.prompt("SOUL LINK BROKEN", 255, 0, 0, 300)
    w.render()
    w.calls.clear()
    w.H.clear()
    assert w.calls.count("clearGraphics") == 1, w.calls
    assert w.state.box is False
    assert w.state.text is False
    assert "drawText" not in w.render()
