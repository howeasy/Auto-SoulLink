"""A11: lua/gen1/panel.lua under lupa, against a fake bus / fake writes.lua.

The panel is the one module that writes 360 bytes straight into the tile map, so what is
tested here is not "does it paint" but "does it refuse to": a mailbox that was already AWAIT
when we attached is of unknown age, an AWAIT that merely persists is not a fresh open, and a
link_panel reply that arrives after the deadline is held for the next open rather than painted
over a fallback the player is already reading.
"""
from __future__ import annotations

import json
import pathlib

import lupa
import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
PANEL = (REPO / "lua" / "gen1" / "panel.lua").as_posix()
RAM = json.loads(
    (REPO / "data" / "games" / "gen1_rby" / "profile.json").read_text(encoding="utf-8")
)["titles"]["red"]["ram"]

TILEMAP = RAM["wTileMap"]          # 0xC3A0
MB = 0xDEE2                        # slink.asm:38 SLINK_MAILBOX
CAPS, STATE, PAGE, PAGES = MB + 8, MB + 9, MB + 10, MB + 11
CLOSED, AWAIT, STAGED = 0, 1, 2
COLS, ROWS, TILES = 20, 18, 360
BLANK = 0x7F

# "SOUL LINK" in the Gen 1 charset: 'A' is $80, space is $7F (lua/gen1/panel.lua's _tile_for).
SOUL_LINK = [0x92, 0x8E, 0x94, 0x8B, 0x7F, 0x8B, 0x88, 0x8D, 0x8A]

FAKE_WRITES = """
return function(rec_arm, rec_disarm, rec_write, fail)
  return {
    arm = function(self, reason, allow) rec_arm(reason, allow) end,
    disarm = function(self) rec_disarm() end,
    write_bytes = function(self, addr, bytes)
      if fail() then error("fake bus write failure") end
      rec_write(addr, bytes)
    end,
  }
end
"""


def _seq(t):
    return [int(t[i]) for i in range(1, len(t) + 1)]


class World:
    """Fake BizHawk bus + fake writes.lua, recording every write and every arm/disarm."""

    def __init__(self, patched=True, state=CLOSED):
        self.bus = bytearray(0x10000)
        self.frame = 0
        self.writes: list[tuple[int, list[int]]] = []
        self.arms: list[tuple] = []
        self.sanitized: list[str] = []
        self.fail_write = False
        self.allow_arg = None
        if patched:
            self.bus[MB:MB + 4] = b"SLNK"
            self.bus[MB + 4] = 3
            self.bus[CAPS] = 0x02
        self.bus[STATE] = state

        self.lua = lupa.LuaRuntime(unpack_returned_tuples=True)
        L = self.lua
        io = L.table(read_u8=lambda a, d=None: self.bus[int(a)], framecount=lambda: self.frame)
        writes = L.execute(FAKE_WRITES)(
            self._arm, self._disarm, self._write, lambda: self.fail_write
        )
        profile = L.table(ram=L.table(wTileMap=TILEMAP))
        self.P = L.eval(f'dofile("{PANEL}")')
        self.panel = self.P.new(profile, io, writes, self._sanitize)

    # -- fakes ---------------------------------------------------------------------------
    def _arm(self, reason, allow):
        self.arms.append(("arm", str(reason)))
        self.allow_arg = allow

    def _disarm(self):
        self.arms.append(("disarm",))

    def _write(self, addr, bytes_t):
        addr, data = int(addr), _seq(bytes_t)
        self.writes.append((addr, data))
        self.bus[addr:addr + len(data)] = bytes(data)

    def _sanitize(self, s):
        s = str(s)
        self.sanitized.append(s)
        return s

    # -- driving -------------------------------------------------------------------------
    def call(self, name, *args):
        """panel:method(...) — lupa needs the receiver spelled out (test_gen1_client.py does too)."""
        return getattr(self.panel, name)(self.panel, *args)

    def tick(self, n=1):
        for _ in range(n):
            self.call("service")
            self.frame += 1

    def rows(self, texts):
        return self.lua.table(*texts)

    def painted(self):
        """The tile-map writes recorded so far, as page payloads."""
        return [d for a, d in self.writes if a == TILEMAP]

    def row_tiles(self, page, row):
        return page[row * COLS:(row + 1) * COLS]

    def open_panel(self):
        """CLOSED observed once, then the patch's own CLOSED->AWAIT."""
        self.tick()
        self.bus[STATE] = AWAIT


def panel_rows(n, first="SOUL LINK"):
    out = [first, ""]
    out += [f"ROW {i}" for i in range(2, n)]
    return out


def test_first_sight_await_is_stale_and_never_painted():
    w = World(state=AWAIT)
    assert w.call("hold", w.rows(panel_rows(26)))
    w.tick(5)
    assert w.writes == []
    assert w.arms == []
    assert w.bus[STATE] == AWAIT      # the fallback stays up for that one open


def test_closed_to_await_paints_page_zero():
    w = World()
    assert w.call("hold", w.rows(panel_rows(26)))
    w.open_panel()
    w.tick()

    assert [a for a, _ in w.writes] == [TILEMAP, PAGES, STATE]
    page = w.painted()[0]
    assert len(page) == TILES
    assert w.row_tiles(page, 0)[:9] == SOUL_LINK
    assert w.row_tiles(page, 0)[9:] == [BLANK] * (COLS - 9)
    assert w.row_tiles(page, 1) == [BLANK] * COLS
    assert w.bus[PAGES] == 2
    assert w.bus[STATE] == STAGED
    assert w.arms == [("arm", "panel"), ("disarm",)]


def test_deadline_boundary_59_paints_61_is_held_for_the_next_open():
    for late, expected in ((59, True), (61, False)):
        w = World()
        w.open_panel()
        w.tick()                      # frame 1: the observed CLOSED->AWAIT
        w.frame = 1 + late
        assert w.call("hold", w.rows(panel_rows(26)))
        w.tick()
        assert bool(w.painted()) is expected, f"late={late}"

    # The rows the deadline refused are HELD, not dropped: the next open paints them.
    w.bus[STATE] = CLOSED
    w.tick()
    w.bus[STATE] = AWAIT
    w.tick()
    assert len(w.painted()) == 1
    assert w.row_tiles(w.painted()[0], 0)[:9] == SOUL_LINK


def test_page_turn_paints_page_one_with_a_fresh_deadline():
    w = World()
    assert w.call("hold", w.rows(panel_rows(26)))
    w.open_panel()
    w.tick()
    assert w.bus[STATE] == STAGED

    # The patch's A: +10 bumped, whited out, AWAIT rewritten (slink.asm:248-271).
    w.frame += 500                    # well past the first deadline; the turn is its own open
    w.bus[PAGE] = 1
    w.bus[STATE] = AWAIT
    w.tick()

    assert len(w.painted()) == 2
    page1 = w.painted()[1]
    assert w.row_tiles(page1, 0)[:6] == [0x91, 0x8E, 0x96, 0x7F, 0xF7, 0xFE]   # "ROW 18"
    assert w.row_tiles(page1, 7)[:6] == [0x91, 0x8E, 0x96, 0x7F, 0xF8, 0xFB]   # "ROW 25"
    for r in range(8, ROWS):
        assert w.row_tiles(page1, r) == [BLANK] * COLS
    assert w.bus[PAGES] == 2


def test_persisting_await_never_resets_the_deadline():
    w = World()
    w.open_panel()
    w.tick(100)                       # AWAIT the whole time, no rows to paint
    assert w.call("hold", w.rows(panel_rows(26)))
    w.tick(50)
    assert w.writes == []
    assert w.arms == []


def test_hold_validates_and_sanitizes_every_row():
    w = World()
    assert w.call("hold", w.rows(panel_rows(26)))
    assert w.sanitized == panel_rows(26)

    bad = w.lua.eval('{"SOUL LINK", 7}')
    ok, err = w.call("hold", bad)
    assert ok is None and "not a string" in str(err)

    ok, err = w.call("hold", w.rows(["X"] * 145))
    assert ok is None and "144" in str(err)

    ok, err = w.call("hold", "not a list")
    assert ok is None and "list" in str(err)

    # A rejected payload holds nothing new: the earlier rows are still the ones painted.
    w.open_panel()
    w.tick()
    assert w.row_tiles(w.painted()[0], 0)[:9] == SOUL_LINK


def test_clear_drops_the_held_rows():
    w = World()
    assert w.call("hold", w.rows(panel_rows(26)))
    w.call("clear")
    w.open_panel()
    w.tick()
    assert w.writes == []


def test_a_write_error_still_disarms():
    w = World()
    assert w.call("hold", w.rows(panel_rows(26)))
    w.fail_write = True
    w.open_panel()
    ok, err = w.call("service")
    assert ok is None and "fake bus write failure" in str(err)
    assert w.arms == [("arm", "panel"), ("disarm",)]
    assert w.writes == []


def test_every_write_lands_inside_the_allow_set():
    w = World()
    assert w.call("hold", w.rows(panel_rows(26)))
    w.open_panel()
    w.tick()
    w.bus[PAGE] = 1
    w.bus[STATE] = AWAIT
    w.tick()
    assert w.writes

    for addr, data in w.writes:
        inside = (addr >= TILEMAP and addr + len(data) <= TILEMAP + TILES) or (
            addr in (STATE, PAGES) and len(data) == 1
        )
        assert inside, f"{addr:#06x}+{len(data)} escaped the panel allow set"
        assert w.panel.allow(addr, len(data)) is True

    assert w.panel.allow(TILEMAP + TILES - 1, 2) is False   # full interval, not just the start
    assert w.panel.allow(PAGE, 1) is False                  # +10 is the patch's byte
    assert w.panel.allow(RAM["wPartyMons"], 1) is False


def test_unpatched_cartridge_is_never_painted():
    w = World(patched=False, state=AWAIT)
    assert w.call("hold", w.rows(panel_rows(26)))
    assert w.call("present") is False
    w.bus[STATE] = CLOSED
    w.tick()
    w.bus[STATE] = AWAIT
    w.tick(5)
    assert w.writes == []


def test_present_abi_and_awaiting_read_the_mailbox():
    w = World()
    assert w.call("present") is True
    assert w.call("abi") == 3
    assert w.call("awaiting") is False
    w.bus[STATE] = AWAIT
    assert w.call("awaiting") is True
    w.bus[CAPS] = 0xFF                # open bus / no cartridge reads as all-ones, not "all caps"
    assert w.call("present") is False


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))


def test_an_overlay_profile_moves_the_mailbox_and_its_abi_bytes(monkeypatch):
    """PLAN A4: the overlay build's mailbox is linker-placed; $DEE2 is inside pureRGB box data."""
    other = 0xDF40
    w = World(patched=False)
    L = w.lua
    profile = L.table(ram=L.table(wTileMap=TILEMAP), trade=L.table(mailbox=other))
    io = L.table(read_u8=lambda a, d=None: w.bus[int(a)], framecount=lambda: w.frame)
    writes = L.execute(FAKE_WRITES)(w._arm, w._disarm, w._write, lambda: w.fail_write)
    panel = w.P.new(profile, io, writes, lambda s: s)
    w.bus[other:other + 4] = b"SLNK"
    w.bus[other + 4] = 3
    w.bus[other + 8] = 0x02
    assert panel.present(panel) is True and panel.abi(panel) == 3
    w.bus[other + 9] = AWAIT
    assert panel.awaiting(panel) is True
    # the vanilla mailbox bytes are not consulted at all
    w.bus[MB:MB + 4] = b"SLNK"
    w.bus[other:other + 4] = bytes(4)
    assert panel.present(panel) is False
    # and the module default is still the vanilla patch's mailbox
    assert w.P.MAILBOX == MB
