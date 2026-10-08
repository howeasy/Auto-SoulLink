"""Natural battle-faint producer through the composed client and real overlay copyback.
MODEL only: callbacks/WRAM are controlled; UpdateBattleMonInParty executes SM83 ROM bytes.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.unit import (
    test_polished_explode_path as br,
    test_polished_faint_client as fc,
    test_polished_faint_observer as fo,
    test_polished_write_path as wp,
)

ROOT = Path(__file__).resolve().parents[2]
ENTRY, SIGNALS = "lua/gen2/entry.lua", "lua/gen2/signals.lua"
HOOK = "SLink-gen2-polished:battle_faint"
PC = 0x44C8
BASELINE = "96d87afcfecc71a914de1b18b3f1a6c7e39a01ca"


def build(*, interface=False, observer=False, overrides=None):
    rig, mons = fo.build(enabled=observer, interface=interface, overrides=overrides)
    events = []
    rig.lua.globals().natural_event = lambda kind, key: events.append((kind, key))
    rig.lua.execute("""return function(c)
        local original=c.on_event
        c.on_event=function(self,e)
            natural_event(e.kind,e.mon and e.mon.key)
            return original(self,e)
        end
    end""")(rig.client)
    return rig, mons, events


def fire(rig, bank=15):
    fo.fire(rig, name=HOOK, pc=PC, bank=bank)


def natural(overrides=None):
    rig, mons, events = build(overrides=overrides)
    rig.put("wBattleMonHP", 0)
    rig.put("wBattleMonHP", 0, 1)
    assert rig.parts.reads.read_party().mons[1].hp > 0
    fire(rig)
    fire(rig)  # repeated zero-HP callbacks cannot duplicate the notification
    rig.frame(1)
    assert [e for e in events if e[0] == "faint"] == [("faint", wp.key_of(mons[0]))]
    assert rig.sent("faint") == [] and len(rig.client.faint_latches) == 1
    fo.native_copy(rig)
    rig.frame(1)
    assert len(rig.sent("faint")) == 1 and rig.sent("faint")[0]["key"] == wp.key_of(mons[0])
    fire(rig)
    rig.frame(2)
    assert len(rig.sent("faint")) == 1 and rig.writes() == []


def test_natural_player_faint_waits_for_native_copyback_and_reports_once():
    natural()


def alive(overrides=None):
    rig, _, events = build(overrides=overrides)
    fire(rig)
    rig.frame(1)
    assert not [e for e in events if e[0] == "faint"]
    assert rig.sent("faint") == [] and len(rig.client.faint_latches) == 0
    assert any(e[0] == "observation" for e in events)  # old boundary observation is preserved


def test_enemy_only_faint_with_player_alive_emits_no_faint():
    alive()


@pytest.mark.parametrize("interface", [False, True], ids=["legacy-commanded", "fs-commanded"])
def test_commanded_death_is_not_echoed(interface):
    rig, mons, events = build(interface=interface, observer=interface)
    br.order(rig, "force_faint" if interface else "force_explode", mons)
    br.at_hold(rig)
    ob = fc.owner(rig) if interface else None
    rig.put("wBattleMonHP", 0)
    rig.put("wBattleMonHP", 0, 1)
    rig.put("wPlayerSubStatus2", 4)
    fire(rig)
    rig.frame(1)
    assert len([e for e in events if e[0] == "faint"]) == 1
    assert rig.sent("faint") == [] and len(rig.client.faint_latches) == 0
    assert any("faint echo of a commanded death dropped" in line for line in rig.lines())
    fo.native_copy(rig)
    if interface:
        fo.fire(rig)
        rig.frame(1)
        fc.tick(rig)
        assert ob.state == "done"
    fire(rig)
    rig.frame(1)
    assert rig.sent("faint") == []


def test_wrong_bank_at_callback_does_not_emit():
    rig, _, events = build()
    rig.put("wBattleMonHP", 0)
    rig.put("wBattleMonHP", 0, 1)
    fire(rig, bank=14)
    rig.frame(1)
    assert events == [] and rig.sent("faint") == []
    assert rig.client.signals.status(rig.client.signals).failed is None


def test_poison_stays_unregistered_and_guarded_whiteout_is_registered():
    rig, _, _ = build()
    hooks = dict(rig.log.hook_at.items())
    assert HOOK in hooks
    assert not any("poison_faint" in k for k in hooks)
    assert "SLink-gen2-polished:whiteout_before_heal" in hooks
    row = json.loads((ROOT / "data/games/polished_crystal/engine_signals.json").read_text())["titles"]["polished_crystal"]["sites"]["battle_faint"]
    assert (row["status"], row["kind"], row["maturity"], row["runtime_enabled"], row["physical_firing"]) == (
        "RESOLVED", "CPU_INSTRUCTION", "SOURCE_CANDIDATE", False, "OPEN")
    assert row["expected_hex"] == row["find_hex"] == "E0D1"


@pytest.mark.parametrize("species,form", [(291, 1), (52, 2)], ids=["nine-bit", "regional-form"])
def test_natural_faint_uses_polished_party_identity(species, form):
    from server.adapters import polished_codec as pc
    rig, mons, events = build()
    mon = dict(mons[0], species_id=species, form=form)
    record = pc.encode_party_mon(mon)
    for i, byte in enumerate(record):
        rig.mem[wp.SYM["wPartyMons"][1]+i] = byte
    rig.put("wBattleMonHP", 0)
    rig.put("wBattleMonHP", 0, 1)
    fire(rig)
    rig.frame(1)
    assert [e for e in events if e[0] == "faint"] == [("faint", wp.key_of(mon))]
    fo.native_copy(rig)
    rig.frame(1)
    assert rig.sent("faint")[0]["key"] == wp.key_of(mon)


@pytest.mark.parametrize("guard", ["registration", "hp"], ids=["drop-registration", "drop-hp-check"])
def test_source_copy_mutants_turn_natural_event_contract_red(guard):
    if guard == "registration":
        path = ENTRY
        old = 'or {"battle_faint", "whiteout_before_heal"},'
        new = 'or {"whiteout_before_heal"},'
        check = natural
    else:
        path = SIGNALS
        old = 'if hp == 0 and link == 0 then'
        new = 'if link == 0 then'
        check = alive
    source = (ROOT / path).read_text()
    assert source.count(old) == 1
    with pytest.raises(AssertionError):
        check({path: source.replace(old, new)})


@pytest.mark.parametrize("title", ["gold", "silver"], ids=["gold", "silver"])
def test_vanilla_signal_and_faint_wire_unchanged(title):
    import subprocess

    from tests.unit import test_gen2_client as vanilla
    profile = json.loads((ROOT / f"data/games/gen2_{title}/profile.json").read_text())["titles"][title]
    if not (ROOT / f".cache/gen2-build/pokegold/{profile['artifact']}.gbc").exists():
        pytest.skip("vanilla ROM input absent")
    old = subprocess.check_output(["git", "show", BASELINE+":"+SIGNALS], cwd=ROOT).decode()
    outputs = []
    for source in (old, (ROOT / SIGNALS).read_text()):
        w = vanilla.World(title, swaps={SIGNALS: source})
        w.checkpoint_ok = True
        w.frames(65)
        w.field("wBattleMode", 1)
        w.field("wCurBattleMon", 0)
        w.field("wBattleMonHP", 0, 2)
        w.fire("battle_faint")
        w.frames(1)
        assert w.sent("faint") == []
        w.party([vanilla.mon(hp=0)])
        w.frames(1)
        assert len(w.sent("faint")) == 1
        outputs.append((w.sent(), sorted(w.emu.callbacks.keys()), w.written()))
    assert outputs[0] == outputs[1]


def test_changed_modules_compile_in_lua55():
    from lupa.lua55 import LuaRuntime
    lua = LuaRuntime(unpack_returned_tuples=True)
    for path in (ENTRY, SIGNALS):
        assert lua.eval("function(s) return assert(load(s)) ~= nil end")((ROOT / path).read_text())
