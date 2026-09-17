"""Deferred writes must wait for a genuinely safe frame, not merely "not in battle".

SLink writes party and box memory directly. `not isInBattle()` was the only gate, but it is
equally true in the PC box UI, the party menu, the naming screen and mid-cutscene — every
place where the open UI holds its own copy of that memory and writes it back over ours.

Two cheap pret-verified predicates close the windows that actually corrupt state:
  wJoyIgnore  — nonzero while a script owns the joypad (cutscene, forced movement)
  wFontLoaded — bit 0 set while a text box / menu font is loaded, i.e. a UI is up

P8-2b: repointed from memory_gb.lua's isInOverworld to lua/gen1_write_safety.lua, which is
the checkpoint the new client actually arms on. It adds a CPU-parked-in-DelayFrame test on
top of those two bytes, so the refusals below are the ones a positive-path harness
(tests/unit/test_gen1_client.py's World.overworld_safe) can never exercise: each starts from
a fully accepted checkpoint and breaks exactly one thing.
"""
from __future__ import annotations

import json
import pathlib

import pytest

lupa = pytest.importorskip("lupa")

REPO = pathlib.Path(__file__).resolve().parents[2]
DATA = REPO / "data" / "games" / "gen1_rby"
PROFILE = json.loads((DATA / "profile.json").read_text(encoding="utf-8"))["titles"]
WS = json.loads((DATA / "write_checkpoint.json").read_text(encoding="utf-8"))
SAFETY = (REPO / "lua" / "gen1_write_safety.lua").as_posix()
DUMPS = {"red": "gen1_red.gb", "blue": "gen1_blue.gb", "yellow": "gen1_yellow.gbc"}


def _rom(title):
    path = REPO / "patch" / "build" / DUMPS[title]
    if not path.exists():
        pytest.skip(f"{path.name} not present — copy the clean dump into patch/build/")
    return path.read_bytes()


class Checkpoint:
    """The real lua/gen1_write_safety.lua over the real clean ROM and a fake WRAM.

    Built ACCEPTING, exactly as test_gen1_client.py's World does, so every test below is a
    single-variable falsification rather than a fresh guess at what a safe frame looks like.
    """

    def __init__(self, title="red"):
        self.rom = _rom(title)
        self.bus = bytearray(0x10000)
        self.p = WS[title]["write_safe"]
        self.profile = dict(WS[title])
        self.lua = lupa.LuaRuntime(unpack_returned_tuples=True)
        self.regs = {"PC": self.p["irq_vector"], "SP": 0xDFF0}
        self.io = self.lua.table(
            read_u8=self._read_u8,
            register=lambda name: self.regs[str(name)],
            domains=lambda: self.lua.table("System Bus", "ROM", "CartRAM"),
        )
        self.M = self.lua.eval(f'dofile("{SAFETY}")')
        # The accepting frame: main thread parked inside DelayFrame, called from OverworldLoop.
        sp = self.regs["SP"]
        self._word(sp, self.p["delay_frame"] + 5)
        self._word(sp + 2, self.p["overworld_loop"] + 3)
        self.bus[self.p["vblank_flag"]] = 1
        self.bus[self.p["serial_status"]] = self.p["disconnected_serial"]

    def _word(self, addr, value):
        self.bus[addr] = value % 256
        self.bus[addr + 1] = (value // 256) % 256

    def _read_u8(self, addr, domain=None):
        if str(domain) == "ROM":
            return self.rom[int(addr)]
        return self.bus[int(addr)]

    def check(self):
        return self.M.check(self.lua.table_from(self.profile, recursive=True), self.io)


def test_the_accepting_frame_really_is_accepted():
    """Load-bearing control: a gate that refuses everything would disable all writes, and
    every refusal below would pass for the wrong reason."""
    ok, why = Checkpoint().check()
    assert ok is True, f"the overworld checkpoint was rejected as {why!r}"
    assert "verified" in why


@pytest.mark.parametrize("title", sorted(DUMPS))
def test_every_title_has_a_verified_checkpoint(title):
    ok, why = Checkpoint(title).check()
    assert ok is True, f"{title}: {why}"


def test_battle_is_not_safe():
    c = Checkpoint()
    c.bus[c.profile["BATTLE_FLAG_ADDR"]] = 1
    ok, why = c.check()
    assert ok is False and "owns the game" in why


def test_script_holding_the_joypad_is_not_safe():
    """Cutscene / forced movement — writing here fights the script."""
    c = Checkpoint()
    c.bus[c.profile["JOY_IGNORE_ADDR"]] = 0xFF
    ok, why = c.check()
    assert ok is False and "owns the game" in why


def test_open_text_box_or_menu_is_not_safe():
    """The PC box UI and party menu both keep the font loaded; this is the window that
    actually corrupts box data, because the UI writes its own copy back."""
    c = Checkpoint()
    c.bus[c.profile["FONT_LOADED_ADDR"]] = 1
    ok, why = c.check()
    assert ok is False and "owns the game" in why


def test_font_loaded_checks_bit_zero_not_the_whole_byte():
    """wFontLoaded's other bits are unrelated; only bit 0 means 'font is up'."""
    c = Checkpoint()
    c.bus[c.profile["FONT_LOADED_ADDR"]] = 0x02
    assert c.check()[0] is True


def test_the_cable_club_owns_the_game_too():
    """Gen 1's own link code writes the same party bytes; a Cable Club frame is not ours."""
    c = Checkpoint()
    c.bus[c.p["entering_cable_club"]] = 1
    ok, why = c.check()
    assert ok is False and "Cable Club" in why


def test_the_cpu_must_be_parked_in_the_verified_loop():
    """`not in battle` is true in the naming screen too; only the stack says where we are."""
    c = Checkpoint()
    c.regs["PC"] = 0x1234
    ok, why = c.check()
    assert ok is False and "outside the verified checkpoint" in why

    c = Checkpoint()
    c._word(c.regs["SP"] + 2, 0x4242)      # returned into something that is not OverworldLoop
    ok, why = c.check()
    assert ok is False and "not waiting in the overworld loop" in why


def test_a_changed_cartridge_is_never_trusted_from_cache():
    """The ROM anchors are re-read on EVERY call: a cached positive must not survive a
    reset onto a different ROM."""
    c = Checkpoint()
    assert c.check()[0] is True
    patched = bytearray(c.rom)
    patched[c.p["delay_frame"]] ^= 0xFF
    c.rom = bytes(patched)
    ok, why = c.check()
    assert ok is False and "checkpoint instructions differ" in why


def test_a_profile_without_the_verified_version_refuses():
    """A profile that declares no verified main loop keeps writes off rather than guessing."""
    c = Checkpoint()
    c.profile = {**c.profile, "write_safe": {**c.p, "version": "something-else"}}
    ok, why = c.check()
    assert ok is False and "no verified main-loop profile" in why


def test_an_unavailable_byte_is_a_refusal_not_a_crash():
    """The client calls this every frame; an emulator hiccup must close the window, not
    take the client down with it."""
    c = Checkpoint()
    c.io = c.lua.table(read_u8=lambda a, d=None: None,
                       register=lambda name: c.regs[str(name)],
                       domains=lambda: c.lua.table("System Bus", "ROM", "CartRAM"))
    ok, why = c.check()
    assert ok is False and "evidence unavailable" in why
