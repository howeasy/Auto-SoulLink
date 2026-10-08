"""Guarded native whiteout reporting, composed client on the real overlay (MODEL; no emulator)."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from tests.unit import test_polished_faint_signals as fs, test_polished_write_path as wp

ROOT = Path(__file__).resolve().parents[2]
SIGNALS = "lua/gen2/signals.lua"
BASELINE = "7608da00651902c0bbb1468a0d888cd7ded9899a"
ROW = json.loads((ROOT / "data/games/polished_crystal/engine_signals.json").read_text())["titles"]["polished_crystal"]["sites"]["whiteout_before_heal"]
HOOK = "SLink-gen2-polished:whiteout_before_heal"


def setup(*, hp=0, source=None):
    overrides = {SIGNALS: source} if source else None
    rig, mons, _ = fs.build(overrides=overrides)
    rig.put("wBattleMode", 0)
    snapshots = []
    rig.lua.globals().whiteout_snapshot = lambda party: snapshots.append([
        (m.slot, m.hp, m.is_egg, m.key) for m in party.mons.values()])
    rig.lua.execute("""return function(c)
        local original=c.on_event
        c.on_event=function(self,e)
            if e.kind == 'whiteout' then whiteout_snapshot(e.party) end
            return original(self,e)
        end
    end""")(rig.client)
    set_hp(rig, hp)
    for condition in ROW["guards"]["memory_equals"]:
        for i in range(condition["width"]):
            rig.mem[condition["addr"]+i] = (condition["value"] >> (8*i)) & 255
    rom = wp.overlay()[1]
    for point in (ROW, ROW["guards"]["script_context"]):
        offset = point["bank"]*0x4000 + point["addr"]-0x4000
        for i in range(len(point["expected_hex"])//2):
            rig.mem[point["addr"]+i] = rom[offset+i]
    return rig, snapshots


def set_hp(rig, hp):
    for slot in range(rig.count()):
        at = wp.SYM["wPartyMons"][1] + slot*48 + 34
        rig.mem[at], rig.mem[at+1] = hp//256, hp%256


def fire(rig, bank=None):
    rig.put("hROMBank", ROW["bank"] if bank is None else bank)
    rig.io.register = rig.lua.eval(f"function(name) return name == 'PC' and {ROW['addr']} or 0xC100 end")
    callback = rig.log.hook_fn[HOOK]
    assert callback is not None, "whiteout hook absent"
    callback()


def test_guarded_wipe_emits_once_and_freezes_preheal_party():
    rig, snapshots = setup()
    fire(rig)
    fire(rig)
    set_hp(rig, 100)  # native HealParty may run before the queued event is drained
    rig.frame(1)
    assert len(snapshots) == 1 and all(row[1] == 0 for row in snapshots[0])
    assert len(rig.sent("whiteout")) == 1
    assert all(m.hp == 100 for m in rig.parts.reads.read_party().mons.values())
    assert rig.writes() == []


def forfeit(source=None):
    rig, snapshots = setup(hp=100, source=source)
    fire(rig)
    rig.frame(2)
    assert snapshots == [] and rig.sent("whiteout") == []
    assert rig.writes() == []


def test_trainer_forfeit_is_not_a_soul_link_whiteout():
    forfeit()


def guard_refusal(which, source=None):
    rig, snapshots = setup(source=source)
    if which == "script":
        at = ROW["guards"]["script_context"]["addr"]
    else:
        condition = next(c for c in ROW["guards"]["memory_equals"] if c["symbol"] == which)
        at = condition["addr"]
    rig.mem[at] = (rig.mem[at]+1)%256
    fire(rig)
    rig.frame(1)
    assert snapshots == [] and rig.sent("whiteout") == [] and rig.writes() == []
    status = rig.client.signals.status(rig.client.signals)
    assert status.failed is None and status.refusals.whiteout_before_heal is not None


@pytest.mark.parametrize("which", ["hScriptBank", "hScriptPos", "script"], ids=["script-bank", "script-position", "script-bytes"])
def test_each_callback_guard_is_enforced(which):
    guard_refusal(which)


def test_wrong_rom_bank_never_reports():
    rig, snapshots = setup()
    fire(rig, bank=ROW["bank"]+1)
    rig.frame(1)
    assert snapshots == [] and rig.sent("whiteout") == []
    assert rig.client.signals.status(rig.client.signals).failed is None


def test_native_anchor_matches_current_overlay():
    rom = wp.overlay()[1]
    assert hashlib.sha1(rom).hexdigest() == "688945795e2656019247f5aaceb7b1d8791e900a"
    assert rom[ROW["rom_offset"]:ROW["rom_offset"]+ROW["hex_len"]].hex().upper() == ROW["expected_hex"] == ROW["find_hex"]



def test_repeat_whiteout_waits_for_heal_before_rearming():
    rig, snapshots = setup()
    fire(rig)
    rig.frame(1)
    fire(rig)
    rig.frame(1)
    assert len(snapshots) == len(rig.sent("whiteout")) == 1
    set_hp(rig, 100)
    rig.frame(1)  # observed native heal is a new episode boundary
    set_hp(rig, 0)
    fire(rig)
    rig.frame(1)
    assert len(snapshots) == len(rig.sent("whiteout")) == 2


def test_captured_snapshot_survives_a_later_reader_failure():
    rig, _ = setup()
    fire(rig)
    saved = rig.parts.reads.read_party
    rig.parts.reads.read_party = rig.lua.eval("function() error('reader unavailable after capture') end")
    batches = list(rig.client.signals.drain(rig.client.signals).values())
    rig.parts.reads.read_party = saved
    assert len(batches) == 1 and batches[0].events[1].kind == "whiteout"
    assert all(m.hp == 0 for m in batches[0].events[1].party.mons.values())


def test_living_egg_is_ignored_but_living_non_egg_blocks():
    rig, snapshots = setup()
    at = wp.SYM["wPartyMons"][1]
    rig.mem[at+21] = rig.mem[at+21] | 0x40
    rig.mem[at+35] = 1
    fire(rig)
    rig.frame(1)
    assert len(snapshots) == 1 and snapshots[0][0][2] is True
    assert len(rig.sent("whiteout")) == 1
    forfeit()


def with_pack_edit(code):
    source = (ROOT / SIGNALS).read_text()
    anchor = "function S.new_polished(options)"
    assert source.count(anchor) == 1
    return source.replace(anchor, anchor + "\n    local row=options.pack.titles.polished_crystal.sites.whiteout_before_heal\n    " + code)


@pytest.mark.parametrize("edit,reason", [
    ("row.guards.required=false", "required whiteout guards"),
    ('row.guards.combine="ANY"', "required whiteout guards"),
    ("row.guards.memory_equals[2]=nil", "caller guards disagree"),
    ("row.guards.memory_equals[2].byte_order='big'", "invalid whiteout memory guard"),
    ("row.guards.memory_equals[1].addr=row.guards.memory_equals[1].addr-1", "guard/point mismatch"),
    ("row.guards.script_context=nil", "script context missing"),
    ("row.guards.script_context.expected_hex='0F04B95E'", "whiteout_before_heal_script_data"),
    ("row.guards.flags={Z=1}", "unsupported whiteout guard"),
], ids=["required", "all", "missing-position", "endian", "address", "missing-script", "script-load-pin", "unsupported-guard"])
def test_partial_or_inconsistent_guard_family_refuses_at_load(edit, reason):
    rig, _ = setup(source=with_pack_edit(edit))
    assert rig.log.hook_fn[HOOK] is None
    assert any(reason in line for line in rig.lines()), rig.lines()


def test_every_memory_equals_guard_is_enforced():
    source = with_pack_edit("""local p=row.point_symbols.wPartyCount
        row.guards.memory_equals[3]={symbol='wPartyCount',bank=p.bank,addr=p.addr,width=1,value=4}""")
    rig, snapshots = setup(source=source)
    assert rig.count() == 3
    fire(rig)
    rig.frame(1)
    assert snapshots == [] and rig.sent("whiteout") == []
    assert "wPartyCount" in rig.client.signals.status(rig.client.signals).refusals.whiteout_before_heal


@pytest.mark.parametrize("guard", ["guards", "hp"], ids=["drop-guards", "drop-all-hp-zero"])
def test_source_copy_mutants_are_red(guard):
    source = (ROOT / SIGNALS).read_text()
    if guard == "guards":
        old, new = "            whiteout_guards(prepared)", "            -- mutant drops guards"
        def check(mutant):
            return guard_refusal("hScriptPos", mutant)
    else:
        old, new = "if not (mon.is_egg or mon.hp == 0) then", "if false then"
        check = forfeit
    assert source.count(old) == 1
    with pytest.raises(AssertionError):
        check(source.replace(old, new))


@pytest.mark.parametrize("title", ["gold", "silver"], ids=["gold", "silver"])
def test_vanilla_composition_wire_unchanged(title):
    import subprocess

    from tests.unit import test_gen2_client as vanilla
    profile = json.loads((ROOT / f"data/games/gen2_{title}/profile.json").read_text())["titles"][title]
    if not (ROOT / f".cache/gen2-build/pokegold/{profile['artifact']}.gbc").exists():
        pytest.skip("vanilla ROM input absent")
    original = subprocess.check_output(["git", "show", BASELINE+":"+SIGNALS], cwd=ROOT).decode()
    observations = []
    for source in (original, (ROOT / SIGNALS).read_text()):
        w = vanilla.World(title, swaps={SIGNALS: source})
        w.checkpoint_ok = True
        w.frames(65)
        observations.append((w.sent(), w.written(), sorted(w.emu.callbacks.keys())))
    assert observations[0] == observations[1]


def test_whiteout_modules_compile_in_lua55():
    from lupa.lua55 import LuaRuntime
    lua = LuaRuntime(unpack_returned_tuples=True)
    for path in (SIGNALS, "lua/gen2/entry.lua"):
        assert lua.eval("function(s) return assert(load(s)) ~= nil end")((ROOT / path).read_text())
