"""S-core: lua/gen1/signals.lua registers byte-verified bus-exec hooks and queues typed signals.

Driven under lupa with an injected `io`: the ROM domain is the real clean dump (skips loudly
without it), the System Bus is a dict, registers/frame are set per test. No BizHawk.
"""
from __future__ import annotations

import json
import pathlib

import lupa
import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
DATA = REPO / "data" / "games" / "gen1_rby"
PROFILE = json.loads((DATA / "profile.json").read_text(encoding="utf-8"))["titles"]
SITES = json.loads((DATA / "engine_signals.json").read_text(encoding="utf-8"))["titles"]
DUMPS = {"red": "gen1_red.gb", "blue": "gen1_blue.gb", "yellow": "gen1_yellow.gbc"}

SIGNALS_LUA = (REPO / "lua" / "gen1" / "signals.lua").as_posix()


def _rom(title: str) -> bytes:
    path = REPO / "patch" / "build" / DUMPS[title]
    if not path.exists():
        pytest.skip(f"{path.name} not present — copy the clean dump into patch/build/")
    return path.read_bytes()


class Harness:
    """A fake BizHawk: ROM bytes, a bus dict, registers, a frame counter, captured hooks."""

    def __init__(self, title: str):
        self.title = title
        self.rom = _rom(title)
        self.lua = lupa.LuaRuntime(unpack_returned_tuples=True)
        self.bus: dict[int, int] = {}
        self.regs = {"PC": 0, "SP": 0xDFF0, "H": 0, "L": 0, "F": 0}
        self.frame = 1000
        self.hooks: dict[int, tuple] = {}
        self.next_id = 1
        self.unregistered: list[int] = []
        profile = self.lua.eval("function(j) return j end")(self.lua.table_from(PROFILE[title], recursive=True))
        sites = self.lua.table_from(SITES[title]["sites"], recursive=True)
        io = self.lua.table(
            read_u8=self._read_u8, read_range=self._read_range, on_bus_exec=self._on_bus_exec,
            unregister=lambda i: self.unregistered.append(int(i)),
            framecount=lambda: self.frame, register=lambda name: self.regs[str(name)],
        )
        self.S = self.lua.eval(f'dofile("{SIGNALS_LUA}")')
        self._profile, self._sites, self._io = profile, sites, io

    def start(self):
        self.svc = self.S.new(self._profile, self._sites, self._io)
        return self.svc

    def _read_u8(self, addr, domain):
        addr = int(addr)
        if str(domain) == "ROM":
            return self.rom[addr]
        # System Bus: switchable bank window $4000-$7FFF follows hLoadedROMBank; bank 0 below
        if addr < 0x8000:
            bank = self.bus.get(PROFILE[self.title]["ram"]["hLoadedROMBank"], 1)
            flat = addr if addr < 0x4000 else bank * 0x4000 + (addr - 0x4000)
            return self.rom[flat] if flat < len(self.rom) else 0
        return self.bus.get(addr, 0)

    def _read_range(self, addr, length, domain):
        return self.lua.table(*[self._read_u8(int(addr) + i, domain) for i in range(int(length))])

    def _on_bus_exec(self, fn, addr, name, domain):
        hook_id = self.next_id
        self.next_id += 1
        self.hooks[hook_id] = (fn, int(addr), str(name))
        return hook_id

    # -- driving ------------------------------------------------------------------------
    def site(self, kind: str) -> dict:
        return SITES[self.title]["sites"][kind]

    def arrive(self, kind: str, *, wrong_pc=False, wrong_bank=False):
        """Pretend the CPU reached the site: set bank/PC, then fire its hook."""
        site = self.site(kind)
        pc = site["address"] + site.get("capture_offset", 0)
        self.bus[PROFILE[self.title]["ram"]["hLoadedROMBank"]] = site["bank"] + (1 if wrong_bank else 0)
        self.regs["PC"] = pc + (1 if wrong_pc else 0)
        for fn, _addr, name in self.hooks.values():
            if name == f"SLink-gen1-{kind}":
                fn()
                return
        raise AssertionError(f"no hook registered for {kind}")

    def status(self):
        return self.svc.status(self.svc)  # Lua method call: pass self explicitly from Python

    def drain(self) -> list[dict]:
        out = []
        for _, sig in sorted(self.svc.drain(self.svc).items()):
            d = dict(sig.items())
            if d.get("point") is not None:
                d["point"] = dict(d["point"].items())
            out.append(d)
        return out


@pytest.mark.parametrize("title", sorted(DUMPS))
def test_registers_one_hook_per_site_at_its_pc(title):
    h = Harness(title)
    h.start()
    names = {name for _, _, name in h.hooks.values()}
    assert names == {f"SLink-gen1-{k}" for k in SITES[title]["sites"]}
    for _, addr, name in h.hooks.values():
        site = h.site(name.removeprefix("SLink-gen1-"))
        assert addr == site["address"] + site.get("capture_offset", 0)


def test_refuses_to_start_when_the_rom_bytes_differ():
    h = Harness("red")
    h.rom = bytearray(h.rom)
    off = h.site("battle_faint")["rom_offset"]
    h.rom[off] ^= 0xFF
    with pytest.raises(lupa.LuaError, match="engine sites differ from the ROM: battle_faint"):
        h.start()


def test_faint_hook_queues_a_stamped_signal_with_the_party_snapshot():
    h = Harness("red")
    h.start()
    ram = PROFILE["red"]["ram"]
    h.bus[ram["wPartyCount"]] = 1
    h.bus[ram["wIsInBattle"]] = 1
    h.bus[ram["wBattleMonHP"]] = 0
    h.bus[ram["wBattleMonHP"] + 1] = 0
    h.bus[ram["wCurMap"]] = 0x0C
    h.frame = 4321
    h.arrive("battle_faint")
    sigs = h.drain()
    assert len(sigs) == 1
    s = sigs[0]
    assert s["kind"] == "battle_faint" and s["frame"] == 4321 and s["bank"] == 0x0F
    assert s["pc"] == h.site("battle_faint")["address"]
    assert s["point"]["in_battle"] == 1 and s["point"]["battle_hp"] == 0 and s["point"]["map"] == 0x0C
    assert len(s["point"]["party"]) == 404 and s["point"]["party"][1] == 1
    assert h.drain() == []  # drained


def test_wrong_bank_is_ignored_and_wrong_pc_is_a_failure():
    h = Harness("red")
    h.start()
    h.arrive("battle_faint", wrong_bank=True)
    assert h.drain() == [] and h.status().failed is None
    h.arrive("battle_faint", wrong_pc=True)
    assert h.drain() == []
    assert "callback PC differs" in str(h.status().failed)
    h.arrive("battle_faint")  # a failed service stays silent
    assert h.drain() == []


def test_bag_received_only_for_a_ball_added_with_carry_set():
    h = Harness("blue")
    h.start()
    ram = PROFILE["blue"]["ram"]
    h.regs["H"], h.regs["L"] = ram["wNumBagItems"] >> 8, ram["wNumBagItems"] & 0xFF
    h.regs["F"] = 0x10  # carry
    h.bus[ram["wCurItem"]] = 0x04  # POKE_BALL
    h.bus[ram["wItemQuantity"]] = 1
    h.arrive("bag_received")
    h.bus[ram["wCurItem"]] = 0x46  # OAKS_PARCEL: not a ball
    h.arrive("bag_received")
    h.bus[ram["wCurItem"]] = 0x04
    h.regs["F"] = 0x00  # no carry: not added
    h.arrive("bag_received")
    sigs = h.drain()
    assert [s["kind"] for s in sigs] == ["bag_received"]
    assert sigs[0]["point"]["item"] == 4 and sigs[0]["point"]["quantity"] == 1


def test_buffer_cap_fails_closed_and_close_unregisters():
    h = Harness("yellow")
    h.start()
    for _ in range(h.S.MAX_PENDING):
        h.arrive("save_witness")
    assert h.status().pending == h.S.MAX_PENDING and h.status().failed is None
    h.arrive("save_witness")
    assert "buffer full" in str(h.status().failed)
    h.svc.close(h.svc)
    assert sorted(h.unregistered) == sorted(h.hooks)
