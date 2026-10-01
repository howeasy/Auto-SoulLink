"""lua/gen4/safety.lua: the read-only checkpoint predicate over a fake main RAM.

The title object is the REAL HG pack row (offsets, symbols); only the RAM contents are modelled
(MODEL: heap addresses below are arbitrary in-RAM cells; the structure follows
docs/gen4/research/checkpoint.md section 3). Every clause is flipped individually from one positive
idle frame and must name itself; the guards are revert-tested by mutating the source text.
"""

from __future__ import annotations

import json
import struct
from pathlib import Path

import lupa
import pytest

ROOT = Path(__file__).resolve().parents[2]
SAFETY = ROOT / "lua/gen4/safety.lua"
READS = ROOT / "lua/gen4/reads.lua"
PACK = json.loads((ROOT / "data/games/gen4_hgss/profile.json").read_text(encoding="utf-8"))
HG = PACK["titles"]["heartgold"]
PF = HG["profile"]["probe_field"]
GSYS = HG["symbols"]["gSystem"]["address"]
FS_PTR = HG["profile"]["fieldsys_ptr"]["address"]
SD_PTR = HG["profile"]["save_ptr"]["address"]
VB = GSYS + HG["profile"]["system"]["vblank_counter_off"]
# MODEL heap cells
FS, SUB, SD, DRV, DATA = 0x02200000, 0x02210000, 0x02220000, 0x02230000, 0x02240000
RAM_LO = 0x02000000


class Ram:
    def __init__(self):
        self.mem = bytearray(0x400000)
        self.holes: list[int] = []  # addresses whose reads fail (unmapped)

    def u(self, addr, value, size=4):
        self.mem[addr - RAM_LO : addr - RAM_LO + size] = struct.pack("<I", value)[:size]

    def get(self, addr, size=4):
        return int.from_bytes(self.mem[addr - RAM_LO : addr - RAM_LO + size], "little")

    def idle(self):
        """One positive idle overworld frame."""
        self.u(VB, 100)
        self.u(FS_PTR, FS)
        self.u(SD_PTR, SD)
        self.u(FS + PF["sub"], SUB)
        self.u(FS + PF["save"], SD)
        self.u(FS + PF["live"], 1)
        self.u(FS + PF["task"], 0)
        self.u(SUB + PF["paused"], 0)
        self.u(SUB + PF["field_app"], 0x02250000)
        self.u(SUB + PF["launched_app"], 0)
        self.u(FS + PF["save_driver"], DRV)
        self.u(DRV + PF["save_driver_data_off"], DATA)
        self.u(DATA + PF["save_state"], 1, 1)
        return self

    def adapter(self, lua):
        def rd(size):
            def f(addr):
                if any(addr <= h < addr + size for h in self.holes):
                    return None
                return self.get(addr, size)
            return f
        return lua.table_from({"u8": rd(1), "u16": rd(2), "u32": rd(4)})


def to_lua(lua, v):
    if isinstance(v, dict):
        return lua.table_from({k: to_lua(lua, x) for k, x in v.items() if x is not None})
    if isinstance(v, list):
        return lua.table_from([to_lua(lua, x) for x in v])
    return v


def make(ram: Ram, active=lambda: False, src: str | None = None, title=None):
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    load = lua.eval("function(s, n) return assert(load(s, n))() end")
    reads = load(READS.read_text(encoding="utf-8"), "=reads")
    safety = load(src if src is not None else SAFETY.read_text(encoding="utf-8"), "=safety")
    opts = lua.table_from({"reads": reads, "encounter_active": active})
    return safety.new(to_lua(lua, title or HG), ram.adapter(lua), opts)


def poll(s, ram: Ram, advance=True):
    """One frame: bump the vblank counter then ask."""
    if advance:
        ram.u(VB, (ram.get(VB) + 1) & 0xFFFFFFFF)
    return s.checkpoint(s)


def primed(ram: Ram, **kw):
    s = make(ram, **kw)
    assert poll(s, ram) == (False, "no_new_frame")  # baseline poll
    return s


def test_positive_idle_frame():
    ram = Ram().idle()
    s = primed(ram)
    assert poll(s, ram) is True
    assert poll(s, ram) is True  # stays true on later frames


def test_first_call_only_baselines():
    ram = Ram().idle()
    s = make(ram)
    assert s.checkpoint(s) == (False, "no_new_frame")


def test_stale_vblank_counter_is_not_a_new_frame():
    ram = Ram().idle()
    s = primed(ram)
    assert poll(s, ram) is True
    assert poll(s, ram, advance=False) == (False, "no_new_frame")
    assert poll(s, ram) is True  # resumes with the next frame


def test_vblank_wrap_counts_as_new_frame():
    ram = Ram().idle()
    ram.u(VB, 0xFFFFFFFF)
    s = primed(ram)  # primed bumps to 0 (wrap)
    assert poll(s, ram) is True


FLIPS = [
    ("field_not_live", lambda r: r.u(FS + PF["live"], 0)),
    ("paused", lambda r: r.u(SUB + PF["paused"], 1)),
    ("task_running", lambda r: r.u(FS + PF["task"], 0x02260000)),
    ("field_app_null", lambda r: r.u(SUB + PF["field_app"], 0)),
    ("app_launched", lambda r: r.u(SUB + PF["launched_app"], 0x02270000)),
    ("save_busy", lambda r: r.u(DATA + PF["save_state"], 2, 1)),
    ("save_busy", lambda r: r.u(DATA + PF["save_state"], 0, 1)),  # init is not idle either
    ("save_driver_null", lambda r: r.u(FS + PF["save_driver"], 0)),
    ("save_driver_null", lambda r: r.u(DRV + PF["save_driver_data_off"], 0)),
    ("save_data_mismatch", lambda r: r.u(SD_PTR, SD + 0x100)),
    ("save_data_mismatch", lambda r: (r.u(SD_PTR, 0), r.u(FS + PF["save"], 0))),  # both null != agree
    ("fieldsys_null", lambda r: r.u(FS_PTR, 0)),
    ("fieldsys_null", lambda r: r.u(FS + PF["sub"], 0)),
    ("fieldsys_range", lambda r: r.u(FS_PTR, 0x023FFFF0)),  # extent runs past main RAM
    ("fieldsys_range", lambda r: r.u(FS_PTR, 0x01000000)),
]


@pytest.mark.parametrize("reason,flip", FLIPS, ids=[f"{r}-{i}" for i, (r, _) in enumerate(FLIPS)])
def test_each_clause_flipped_names_itself(reason, flip):
    ram = Ram().idle()
    s = primed(ram)
    assert poll(s, ram) is True
    flip(ram)
    assert poll(s, ram) == (False, reason)


def test_encounter_active_refuses_then_clears():
    flag = {"on": True}
    ram = Ram().idle()
    s = primed(ram, active=lambda: flag["on"])
    assert poll(s, ram) == (False, "encounter_active")
    flag["on"] = False
    assert poll(s, ram) is True


def test_throwing_encounter_predicate_fails_closed():
    def boom():
        raise RuntimeError("lifecycle unavailable")
    ram = Ram().idle()
    s = primed(ram, active=boom)
    assert poll(s, ram) == (False, "encounter_unknown")


def test_unreadable_cell_names_its_clause():
    ram = Ram().idle()
    s = primed(ram)
    ram.holes.append(FS + PF["task"])
    assert poll(s, ram) == (False, "task_running_unreadable")
    ram.holes.clear()
    ram.holes.append(VB)
    assert poll(s, ram) == (False, "vblank_unreadable")


def test_first_failing_clause_wins_in_order():
    ram = Ram().idle()
    s = primed(ram)
    ram.u(FS + PF["task"], 1)   # clause 6
    ram.u(SUB + PF["paused"], 1)  # clause 5 comes first
    assert poll(s, ram) == (False, "paused")
    assert poll(s, ram, advance=False) == (False, "no_new_frame")  # frame clause beats everything


def test_pc_is_not_a_clause():
    # checkpoint.md section 5 clause 1: frame-end PC is never in OS_WaitIrq, so no register is consulted.
    assert "register" not in SAFETY.read_text(encoding="utf-8").lower()


def test_pack_gap_refuses_by_name():
    ram = Ram().idle()
    bare = json.loads(json.dumps(HG))
    del bare["profile"]["system"]["vblank_counter_off"]
    s = make(ram, title=bare)
    assert poll(s, ram) == (False, "pack_gap:system.vblank_counter_off")
    nosym = json.loads(json.dumps(HG))
    del nosym["symbols"]["gSystem"]
    assert poll(make(ram, title=nosym), ram) == (False, "pack_gap:symbols.gSystem")
    pt = json.loads((ROOT / "data/games/gen4_pt/profile.json").read_text(encoding="utf-8"))["titles"]["platinum"]
    assert poll(make(ram, title=pt), ram)[1].startswith("pack_gap:")


def test_in_battle_write_gate_is_a_stub():
    s = make(Ram().idle())
    assert s.in_battle_write_ok(s) == (False, "not_implemented")


# -- revert tests: each guard is load-bearing --------------------------------------------------
def _mutate(old: str, new: str) -> str:
    src = SAFETY.read_text(encoding="utf-8")
    assert src.count(old) == 1, old
    return src.replace(old, new)


def test_revert_new_frame_guard_goes_red():
    src = _mutate('if last == nil or vb == last then return false, "no_new_frame" end', "")
    ram = Ram().idle()
    s = make(ram, src=src)
    poll(s, ram)
    assert poll(s, ram, advance=False) is True  # the mutant passes a stale frame: the real one refuses


def test_revert_task_guard_goes_red():
    src = _mutate('if task ~= 0 then return false, "task_running" end', "")
    ram = Ram().idle()
    s = make(ram, src=src)
    poll(s, ram)
    ram.u(FS + PF["task"], 0x02260000)
    assert poll(s, ram) is True  # mutant ignores a running field task: the real one refuses
