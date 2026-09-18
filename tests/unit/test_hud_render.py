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

gui.cleartext is stubbed too: hud.lua MUST call it every render (drawText text lives in the text layer).
The diagnostic harnesses under lua/tests redraw their gui.text every frame from their own
onframeend handlers, so the per-render cleartext costs them at most a one-frame flicker.

The stub is written in Lua (not a lupa-wrapped Python callable) so that hud.lua's
`type(gui.clearGraphics) == "function"` guards see a real function.
"""
from __future__ import annotations

import pathlib

import lupa

REPO = pathlib.Path(__file__).resolve().parents[2]
HUD = (REPO / "lua" / "hud.lua").as_posix()

# `state` mirrors what would actually be visible on the BizHawk lua surface:
# Two layers, as BizHawk really has them (HUD-SHOT screenshot 2026-09-18: with zero draws
# the box was gone and the drawText text still on screen): clearGraphics wipes the BOX layer
# only, cleartext wipes the TEXT layer that gui.drawText paints. A render that clears one and
# not the other leaves state.text (or state.box) stale, which is exactly the owner's
# 'notifications never vanish' report.
GUI_STUB = """
return function(rec)
  local state = {box = false, text = false, cleartext_calls = 0, texts = {}, logs = {}}
  gui = {
    clearGraphics = function(...)
      rec("clearGraphics")
      state.box = false
    end,
    cleartext = function(...)
      rec("cleartext")
      state.cleartext_calls = state.cleartext_calls + 1
      state.text = false
    end,
    drawBox = function(...)
      rec("drawBox")
      state.box = true
    end,
    drawText = function(x, y, s, ...)
      rec("drawText")
      state.text = true
      state.texts[#state.texts + 1] = s
    end,
  }
  -- BizHawk hands Lua its API as NLua delegates, whose type() is "userdata", not "function".
  -- Wrap every stubbed API in a callable TABLE so a type(x) == "function" guard in hud.lua
  -- fails here exactly as it fails in EmuHawk (the HUD-SHOT finding, 2026-09-18).
  local function callable(f) return setmetatable({}, {__call = function(_, ...) return f(...) end}) end
  for k, f in pairs(gui) do gui[k] = callable(f) end
  console = {log = callable(function(s) state.logs[#state.logs + 1] = s end)}
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
        self.state.texts = self.lua.eval("{}")
        self.H.render()
        return self.calls[mark:]

    @property
    def drawn(self) -> list[str]:
        """The text hud.lua handed gui.drawText during the last render(), in order."""
        return list(self.state.texts.values())

    def gbc(self):
        """Gen 1/2 geometry: 160x144 -> font 8, char_width 5, 30 chars per line."""
        self.H.init(self.lua.eval("{screen_w = 160, screen_h = 144}"))
        return self


def test_expired_message_frame_clears_and_draws_nothing():
    """duration 2 -> the third render ends with an empty surface: no box, no text visible."""
    w = World()
    w.H.show("LINKED: PIKACHU", 255, 255, 0, 2)
    w.render()  # frame 1, live
    w.render()  # frame 2, last live frame
    w.render()  # frame 3, expired
    assert w.state.box is False
    assert w.state.text is False
    assert w.state.cleartext_calls >= 1


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
    assert w.state.cleartext_calls >= 1


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


# ── HUD-3: word wrap instead of "..." ────────────────────────────────────────
# Truncation ate the end of every long notification -- and the end is where the
# mon name and the outcome live ("[x] Dead in par..."). The bar wraps and grows
# upward instead; "..." survives only past the 3-line cap.

def test_long_message_wraps_instead_of_truncating():
    """A 2-line message is drawn as two full lines, joined back to the original text."""
    w = World().gbc()
    text = "LINKED PIKACHU AND CHARMANDER IN VIRIDIAN FOREST NOW"
    w.H.show(text, 255, 255, 0, 240)
    frame = w.render()
    assert frame.count("drawText") == 2, frame
    assert w.drawn == ["LINKED PIKACHU AND CHARMANDER", "IN VIRIDIAN FOREST NOW"]
    assert "..." not in "".join(w.drawn)
    assert all(len(line) <= 30 for line in w.drawn)
    assert w.state.box is True


def test_wrapped_bar_grows_upward_so_the_bottom_edge_holds():
    """hud_y stays the bottom line: the extra lines must not fall off a 144px screen.

    Read off the y hud.lua passes gui.drawText: bottom line at hud_y-1 = 131, each
    earlier line one font_size+2 higher. A bar that grew DOWNWARD would draw at
    141/151 and put line 2 under the screen.
    """
    ys = []
    w = World().gbc()
    w.lua.execute(
        "local d = gui.drawText; gui.drawText = function(x, y, ...) YS[#YS+1] = y; return d(x, y, ...) end"
    )
    w.lua.globals().YS = w.lua.eval("{}")
    w.H.show("LINKED PIKACHU AND CHARMANDER IN VIRIDIAN FOREST NOW", 255, 255, 0, 240)
    w.render()
    ys = list(w.lua.globals().YS.values())
    assert ys == [121, 131], ys          # font_size 8 -> line_h 10, hud_y 132


def test_only_past_the_line_cap_does_it_ellipsize_and_say_so():
    """Beyond 3 lines the last line is cut -- once, with a console.log receipt."""
    w = World().gbc()
    text = " ".join(["WORD"] * 40)       # ~200 chars, far past 3 x 30
    w.H.show(text, 255, 255, 0, 240)
    frame = w.render()
    assert frame.count("drawText") == 3, frame
    assert w.drawn[-1].endswith("...")
    assert not any(line.endswith("...") for line in w.drawn[:-1])
    logs = list(w.state.logs.values())
    assert len(logs) == 1 and "ellipsized" in logs[0], logs


def test_prompt_wraps_too():
    """H.prompt gets the same treatment, growing downward from prompt_y."""
    w = World().gbc()
    w.H.prompt("SOUL LINK BROKEN BETWEEN PIKACHU AND CHARMANDER FOREVER", 255, 0, 0, 300)
    frame = w.render()
    assert frame.count("drawText") == 2, frame
    assert "..." not in "".join(w.drawn)


# ── HUD-3: messages actually go away ─────────────────────────────────────────
# Only the HEAD of the queue ages, so K queued messages used to hold the screen
# for K x their duration in sequence (a hello that re-memorializes a party, or a
# whiteout cascade). Bounds: coalesce identical text, shorten the head while a
# backlog exists, cap the queue depth.

def test_a_burst_of_distinct_messages_drains_within_the_bounded_dwell():
    """5 x 240 frames would be 1200 frames of HUD; the bound is 3*90 + 240 = 510."""
    w = World()
    for i in range(5):
        w.H.show(f"MSG {i}", 255, 255, 0, 240)
    for _ in range(400):
        w.render()
    assert w.state.text is True, "the burst must not be dropped outright"
    for _ in range(200):
        w.render()
    assert w.state.text is False
    assert w.state.box is False


def test_identical_text_coalesces_instead_of_stacking():
    """The hello re-memorialize loop queues the SAME string once per dead party mon."""
    w = World()
    for _ in range(6):
        w.H.show("[x] Dead in party -> grave", 255, 80, 80, 240)
    for _ in range(241):
        w.render()
    assert w.state.text is False, "6 copies would have held the bar for 1440 frames"


def test_clear_empties_both_queues():
    """H.clear() must drop a queued backlog, not just the head of each queue."""
    w = World()
    for i in range(3):
        w.H.show(f"MSG {i}", 255, 255, 0, 240)
        w.H.prompt(f"ASK {i}", 255, 255, 0, 300)
    w.render()
    w.H.clear()
    assert "drawText" not in w.render()
