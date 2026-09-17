"""HUD-1: lua/hud.lua under lupa, against a recording `gui` stub.

BizHawk's lua draw surface is persistent: gui.drawText/gui.drawBox paint pixels that stay
until something overdraws them or the surface is cleared (EmuHawk 2.11 API docs,
`_docs_luacats/gui.d.lua:21-25` -- "clears all lua drawn graphics from the screen"). Painting
a fully transparent box over the old area erases nothing, so an expired banner used to sit
on-screen forever. What is tested here is therefore not "does it paint" but "does the surface
get cleared every frame, before the live elements are drawn".

The stub is written in Lua (not a lupa-wrapped Python callable) so that hud.lua's
`type(gui.clearGraphics) == "function"` guards see a real function.
"""
from __future__ import annotations

import pathlib

import lupa

REPO = pathlib.Path(__file__).resolve().parents[2]
HUD = (REPO / "lua" / "hud.lua").as_posix()

GUI_STUB = """
return function(rec)
  local function mk(name)
    return function(...) rec(name) end
  end
  gui = {
    clearGraphics = mk("clearGraphics"),
    cleartext     = mk("cleartext"),
    drawBox       = mk("drawBox"),
    drawText      = mk("drawText"),
  }
end
"""

CLEARS = ("clearGraphics", "cleartext")


class World:
    def __init__(self):
        self.calls: list[str] = []
        self.lua = lupa.LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute(GUI_STUB)(self.calls.append)
        self.H = self.lua.eval(f'dofile("{HUD}")')

    def render(self):
        """One frame; returns just that frame's gui calls, in order."""
        mark = len(self.calls)
        self.H.render()
        return self.calls[mark:]


def test_expired_message_frame_clears_and_draws_nothing():
    """duration 2 -> the third render is a bare clear: no drawText left on the surface."""
    w = World()
    w.H.show("LINKED: PIKACHU", 255, 255, 0, 2)
    assert "drawText" in w.render()          # frame 1, live
    assert "drawText" in w.render()          # frame 2, last live frame
    third = w.render()
    assert "drawText" not in third, third
    assert "drawBox" not in third, third
    for name in CLEARS:
        assert third.count(name) == 1, (name, third)


def test_live_message_clears_before_it_draws():
    """Within one frame the clear must come first, or it wipes the text it just drew."""
    w = World()
    w.H.show("STILL HERE", 255, 255, 0, 240)
    frame = w.render()
    assert "drawText" in frame, frame
    for name in CLEARS:
        assert name in frame, (name, frame)
        assert frame.index(name) < frame.index("drawText"), frame


def test_explicit_clear_wipes_the_surface_once():
    """H.clear() takes effect immediately rather than waiting for the next render."""
    w = World()
    w.H.prompt("SOUL LINK BROKEN", 255, 0, 0, 300)
    w.render()
    w.calls.clear()
    w.H.clear()
    for name in CLEARS:
        assert w.calls.count(name) == 1, (name, w.calls)
    assert "drawText" not in w.render()
