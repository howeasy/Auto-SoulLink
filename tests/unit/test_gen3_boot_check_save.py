"""lua/tests/gen3_boot_check.lua save witness vs gen3_codec.qualify_flash (card gen3-P3-C3-27).

Flash images are built with the codec, fed to the Lua through lupa with a fake flash memory
domain, and judged by both. No emulator.
"""
from pathlib import Path

import pytest

from server.adapters import gen3_codec as codec

lupa = pytest.importorskip("lupa")
ROOT = Path(__file__).resolve().parents[2]
DOMAIN = "Flash"


def _data(sid: int, size: int) -> bytes:
    return bytes((sid * 7 + j) & 0xFF for j in range(size))


def _put(image: bytearray, index: int, raw: bytes) -> None:
    image[index * codec.SECTOR_SIZE:(index + 1) * codec.SECTOR_SIZE] = raw


def _slot(image: bytearray, counter: int, layout: list[dict], ids=None, slot=None) -> None:
    """Write `ids` into consecutive physical sectors of the slot pret uses for `counter`."""
    base = codec.NUM_SECTORS_PER_SLOT * (counter % 2 if slot is None else slot)
    for i, sid in enumerate(range(14) if ids is None else ids):
        _put(image, base + i, codec.write_sector(_data(sid, layout[sid]["size"]), sid, counter, layout))


def valid(counter: int, cfru: bool = False) -> bytearray:
    """A good save at `counter` beside the previous one at counter-1."""
    layout = codec.slot_layout(codec.CHUNK_SIZE_CFRU if cfru else codec.CHUNK_SIZE_VANILLA)
    image = bytearray(codec.FLASH_SIZE)
    _slot(image, counter - 1, layout)
    _slot(image, counter, layout)
    return image


def old_expression(image: bytes, ctr: int) -> int:
    """The pre-fix sectors_at: all 32 sectors, id read from the unused +0xFF0."""
    n = 0
    for s in range(codec.SECTORS_COUNT):
        raw = image[s * codec.SECTOR_SIZE:(s + 1) * codec.SECTOR_SIZE]
        if (int.from_bytes(raw[0xFF8:0xFFC], "little") == codec.SECTOR_SIGNATURE
                and int.from_bytes(raw[0xFFC:0x1000], "little") == ctr
                and int.from_bytes(raw[0xFF0:0xFF2], "little") < 14):
            n += 1
    return n


CTR = 6
LAYOUT = codec.slot_layout()
BASE = codec.NUM_SECTORS_PER_SLOT * (CTR % 2)


def duplicate_ids() -> bytearray:
    image = valid(CTR)
    _put(image, BASE + 13, codec.write_sector(_data(12, LAYOUT[12]["size"]), 12, CTR, LAYOUT))
    return image


def invalid_id() -> bytearray:
    image = valid(CTR)
    image[(BASE + 5) * codec.SECTOR_SIZE + codec.OFF_SECTOR_ID] = 0x20
    return image


def seven_per_slot() -> bytearray:
    image = bytearray(codec.FLASH_SIZE)
    _slot(image, CTR, LAYOUT, ids=range(7), slot=0)
    _slot(image, CTR, LAYOUT, ids=range(7, 14), slot=1)
    return image


def bad_checksum() -> bytearray:
    image = valid(CTR)
    image[(BASE + 3) * codec.SECTOR_SIZE + 0x10] ^= 0xFF
    return image


class World:
    def __init__(self, image: bytes, title: str = "firered"):
        self.lua = lupa.LuaRuntime(unpack_returned_tuples=True)
        g = self.lua.globals()
        g.SLINK_ROOT = ROOT.as_posix()
        g.flash = bytes(image)
        self.lua.execute("""
            frame, dialog, flushes = 0, 0, 0
            local function rd(fmt) return function(a) return (string.unpack(fmt, flash, a + 1)) end end
            memory = {read_u32_le = rd("<I4"), read_u16_le = rd("<I2"), read_u8 = rd("<I1")}
            console = {log = function() end}
            joypad = {set = function() end}
            client = {screenshot = function() end, saveram = function() flushes = flushes + 1 end}
            emu = {framecount = function() return frame end,
                   frameadvance = function()
                       frame = frame + 1
                       if swap_at and frame >= swap_at then flash, swap_at = pending, nil end
                       if close_at and frame >= close_at then dialog = 0 end
                   end}
        """)
        self.G = self.lua.eval(f'dofile("{(ROOT / "lua/tests/gen3_boot_check.lua").as_posix()}")')
        self.G.title = title
        # The menu drive is stubbed at the predicate: callback2 always on the field, the
        # save dialog callback is the `dialog` global the frame hook controls.
        self.lua.execute("""
            local G = ...
            G.pred = function(cp, name)
                if name == "save_dialog_cb" then return dialog, 0 end
                return 1, 1
            end
        """, self.G)

    def sectors_at(self, ctr):
        return self.G.sectors_at(DOMAIN, ctr)

    def save(self, after: bytes, swap_at=200, close_at=None):
        g = self.lua.globals()
        g.dialog, g.pending, g.swap_at, g.close_at = 1, bytes(after), swap_at, close_at
        return self.G.save_via_menu(self.lua.table(), DOMAIN)


@pytest.mark.parametrize("build", [duplicate_ids, invalid_id, seven_per_slot, bad_checksum])
def test_countermodels_fail(build):
    image = bytes(build())
    assert old_expression(image, CTR) >= 14            # it fooled the old witness
    assert not codec.qualify_flash(image)[0]           # the codec refuses it
    n, why = World(image).sectors_at(CTR)
    assert n < 14 and why, (n, why)                    # and so does the fixed witness


@pytest.mark.parametrize("title,cfru", [("firered", False), ("radical_red", True)])
def test_valid_image_passes(title, cfru):
    image = bytes(valid(CTR, cfru))
    assert codec.qualify_flash(image, cfru=cfru) == (True, "ok")
    assert tuple(World(image, title).sectors_at(CTR)) == (14, None)


def test_checksum_table_follows_the_title():
    # A CFRU image judged with the vanilla chunk table must fail on checksums.
    n, why = World(bytes(valid(CTR, cfru=True)), "firered").sectors_at(CTR)
    assert n < 14 and "checksum" in why


def test_save_succeeds_and_flushes():
    w = World(bytes(valid(CTR - 1)))
    ok, before, after, why = w.save(valid(CTR), close_at=400)
    assert (ok, before, after, why) == (True, CTR - 1, CTR, None)
    assert w.lua.globals().flushes == 1


def test_dialog_timeout_returns_false():
    w = World(bytes(valid(CTR - 1)))
    ok, _, after, why = w.save(valid(CTR), close_at=None)
    assert ok is False and after == CTR and "never closed" in why
    assert w.lua.globals().flushes == 0


def test_flush_failure_returns_false():
    w = World(bytes(valid(CTR - 1)))
    w.lua.execute('client.saveram = function() error("disk full") end')
    ok, _, _, why = w.save(valid(CTR), close_at=400)
    assert ok is False and "flush failed" in why and "disk full" in why


def test_invalid_new_slot_returns_false():
    w = World(bytes(valid(CTR - 1)))
    ok, _, _, why = w.save(bad_checksum(), close_at=400)
    assert ok is False and "bad checksum" in why
