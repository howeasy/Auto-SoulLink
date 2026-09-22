"""Pure box-side plans and injected gate MODEL controls; no emulator memory."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from lupa.lua54 import LuaError, LuaRuntime

ROOT = Path(__file__).resolve().parents[2]


def record(species=25, marker=None):
    raw = bytearray(range(32))
    raw[0], raw[31] = species, 50
    return {"bytes": list(raw), "species_marker": species if marker is None else marker,
            "ot": [0x80, 0x50] + [0xAA] * 9, "nickname": [0x81, 0x50] + [0xBB] * 9}


def box(count=1, *, backing=False):
    raw = bytearray([0xE7] * (1104 if backing else 1102))
    raw[0] = count
    for slot in range(count):
        mon = record(25 + slot)
        raw[slot + 1] = mon["species_marker"]
        raw[22 + slot * 32:54 + slot * 32] = bytes(mon["bytes"])
        raw[662 + slot * 11:673 + slot * 11] = bytes(mon["ot"])
        raw[882 + slot * 11:893 + slot * 11] = bytes(mon["nickname"])
    raw[count + 1] = 255
    return list(raw)


class World:
    def __init__(self, title="crystal"):
        self.profile = json.loads((ROOT / f"data/games/gen2_{title}/profile.json").read_text())["titles"][title]
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        module = self.lua.eval("dofile")((ROOT / "lua/gen2/boxes.lua").as_posix())
        self.state = self.lua.table(mapping=True, armed=True, stale=False, writes=0, preflights=0)
        self.gate = self.lua.eval("""function(s)
            return {
                preflight=function(requirements)
                    s.preflights=s.preflights+1
                    if not s.mapping or not s.armed or s.stale then return nil, 'gate refused' end
                    return {mapping_qualified=true, domain='CartRAM', domain_size=32768, requirements=requirements}
                end,
                execute=function(ticket,spans)
                    assert(s.mapping and s.armed and not s.stale, 'expired gate')
                    s.last=spans
                    local total=0
                    for _,span in ipairs(spans) do total=total+#span.bytes end
                    s.writes=s.writes+total
                    return {status='written',completed=total,physical=false}
                end,
            }
        end""")(self.state)
        self.obj = module.new(self.table(self.profile), self.gate)

    def table(self, value):
        return self.lua.table_from(value, recursive=True)

    def plan(self, operation="deposit", *, current=0, target=0, saved=1, count=1, mon=None, slot=0):
        state = self.lua.table(current_box=current, saved_at_least_once=saved)
        before = self.table(box(count, backing=target != current))
        if operation == "withdraw":
            return self.obj.plan_withdraw(state, target, before, slot)
        if operation == "memorial":
            return self.obj.plan_memorial(state, before, self.table(mon or record()))
        return self.obj.plan_deposit(state, target, before, self.table(mon or record(175, 253)))


@pytest.mark.parametrize("title", ["crystal", "gold", "silver"])
def test_current_box_deposit_and_withdraw_are_positive_and_only_plan_active_payload(title):
    w = World(title)
    plan = w.plan()
    assert plan.owner == "active" and plan.after[1] == 2
    assert plan.after[3] == 253 and plan.after[4] == 255
    assert len(plan.spans) == 1 and len(plan.spans[1].bytes) == 1102
    assert plan.spans[1].address == w.profile["derived"]["active_box_flat"]
    assert plan.copyback.length == 1102 and plan.copyback.mode == "ENGINE_SAVEBOX_DEFERRED"
    assert plan.copyback.to_address == 0x4000
    assert w.state.writes == 0
    result = w.obj.commit(plan)
    assert result.status == "written" and w.state.writes == 1102
    take = w.plan("withdraw")
    assert take.after[1] == 0 and take.after[2] == 255
    assert take.removed.bytes[1] == 25 and take.removed.ot[1] == 0x80


def test_inactive_box_writes_never_touch_padding_and_memorial_has_no_hp_patch():
    w = World()
    plan = w.plan("memorial", current=0, target=13)
    assert plan.owner == "backing" and plan.box_index == 13
    assert plan.spans[1].address == 0x79E0 and len(plan.spans[1].bytes) == 1102
    assert len(plan.after) == 1104 and plan.after[1103] == plan.before[1103] == 0xE7
    assert plan.after[1104] == plan.before[1104] == 0xE7
    assert [plan.after[i] for i in range(55, 87)] == record()["bytes"]
    assert plan.obligations.memorial_record == "EXTERNAL_REQUIRED"
    assert plan.obligations.reassert_after_full_save is True


@pytest.mark.parametrize("title", ["crystal", "gold", "silver"])
@pytest.mark.parametrize("operation", ["deposit", "withdraw"])
def test_current_box_plans_carry_reassert_after_full_save(title, operation):
    """Continue runs LoadBox (C engine/menus/save.asm:601, G :543), copying the stored
    box over sBox; only SaveBox (C :275, G :282) syncs back. A reset before the next
    SAVE silently reverts an active-box edit, so every active plan must say so."""
    w = World(title)
    active = w.plan(operation, current=3, target=3)
    assert active.owner == "active" and active.copyback.mode == "ENGINE_SAVEBOX_DEFERRED"
    assert active.obligations.reassert_after_full_save is True
    assert active.obligations.reset_before_save == "LOADBOX_REVERTS_ACTIVE_EDIT"
    # Control: a backing-box plan is durable in SRAM without the engine copy-back.
    backing = w.plan(operation, current=3, target=4)
    assert backing.owner == "backing"
    assert backing.obligations.reassert_after_full_save is False
    assert backing.obligations.reset_before_save == "NOT_APPLICABLE"


@pytest.mark.parametrize("operation", ["deposit", "withdraw", "memorial"])
def test_before_first_save_refuses_all_plans(operation):
    w = World()
    with pytest.raises(LuaError, match="first SAVE"):
        w.plan(operation, saved=0, target=13 if operation == "memorial" else 0)
    assert w.state.writes == w.state.preflights == 0


def test_memorial_current14_refusal_does_not_ban_ordinary_current14_edits():
    w = World()
    with pytest.raises(LuaError, match="memorial"):
        w.plan("memorial", current=13, target=13)
    assert w.plan(current=13, target=13).owner == "active"
    assert w.plan("withdraw", current=13, target=13).owner == "active"


def test_nonfinal_withdraw_compacts_records_and_names_like_source():
    w = World()
    plan = w.plan("withdraw", count=3, slot=1)
    assert plan.removed.bytes[1] == 26
    assert plan.after[1] == 2 and plan.after[3] == 27 and plan.after[4] == 255
    assert plan.after[55] == 27
    assert [plan.after[i] for i in range(674, 685)] == record(27)["ot"]


def test_twentieth_slot_withdraw_preserves_structs_and_marks_last_ot_byte():
    w = World()
    plan = w.plan("withdraw", count=20, slot=19)
    assert plan.after[1] == 19 and plan.after[21] == 255
    assert plan.after[662 + 19 * 11 + 1] == 255
    assert [plan.after[i] for i in range(23, 663)] == [plan.before[i] for i in range(23, 663)]


@pytest.mark.parametrize("mutation", ["record_length", "egg_marker", "sparse", "name", "byte"])
def test_complete_payload_validation_precedes_any_gate_call(mutation):
    w = World()
    mon = record()
    if mutation == "record_length":
        mon["bytes"] += [0] * 16
    elif mutation == "egg_marker":
        mon["species_marker"] = 26
    elif mutation == "sparse":
        mon["bytes"] = {1: 25, 32: 50}
    elif mutation == "name":
        mon["ot"] = [0] * 10
    else:
        mon["bytes"][9] = 256
    with pytest.raises(LuaError):
        w.plan(mon=mon)
    assert w.state.writes == w.state.preflights == 0


@pytest.mark.parametrize("control", ["mapping", "armed", "stale"])
def test_gate_refusal_has_zero_writes(control):
    w = World()
    plan = w.plan()
    w.state[control] = control == "stale"
    with pytest.raises(LuaError, match="gate"):
        w.obj.commit(plan)
    assert w.state.writes == 0


@pytest.mark.parametrize("control", ["address", "payload", "state"])
def test_mutated_plan_refuses_before_gate(control):
    w = World()
    plan = w.plan()
    if control == "address":
        plan.spans[1].address = 0
    elif control == "payload":
        plan.spans[1].bytes[1102] = 256
    else:
        plan.state.current_box = 13
    with pytest.raises(LuaError, match="plan"):
        w.obj.commit(plan)
    assert w.state.writes == w.state.preflights == 0


def test_missing_generated_flat_mapping_refuses_and_input_profile_is_not_mutated():
    w = World()
    profile = copy.deepcopy(w.profile)
    del profile["derived"]["active_box_flat"]
    module = w.lua.eval("dofile")((ROOT / "lua/gen2/boxes.lua").as_posix())
    with pytest.raises(LuaError, match="flat"):
        module.new(w.table(profile), w.gate)


def test_capacity_and_collection_corruption_fail_before_preflight():
    w = World()
    with pytest.raises(LuaError, match="full"):
        w.plan(count=20)
    with pytest.raises(LuaError, match="slot"):
        w.plan("withdraw", count=0)
    state = w.lua.table(current_box=0, saved_at_least_once=1)
    raw = box()
    raw[2] = 0
    with pytest.raises(LuaError, match="terminator"):
        w.obj.plan_deposit(state, 0, w.table(raw), w.table(record()))
    assert w.state.writes == w.state.preflights == 0


@pytest.mark.parametrize("current,target", [(0, 0), (0, 5), (0, 13)])
def test_plan_spans_preserve_every_cart_ram_byte_outside_exact_payload(current, target):
    w = World()
    plan = w.plan("memorial" if target == 13 else "deposit", current=current, target=target)
    memory = bytearray([0x69] * 32768)
    address = plan.spans[1].address
    source = bytes(plan.before[i] for i in range(1, len(plan.before) + 1))
    memory[address:address + len(source)] = source
    before = bytes(memory)
    payload = bytes(plan.spans[1].bytes[i] for i in range(1, 1103))
    memory[address:address + 1102] = payload
    assert bytes(memory[:address]) == before[:address]
    assert bytes(memory[address + 1102:]) == before[address + 1102:]
    untouched = plan.untouched
    assert untouched[1].address == 0 and untouched[1].length == address
    assert untouched[2].address == address + 1102 and untouched[2].length == 32768 - address - 1102
    requirements = plan.requirements
    assert requirements.observed_state.current_box == current
    assert requirements.before_spans[1].address == address
    assert requirements.state_sources.current_box.address == w.profile["ram"]["wCurBox"]


def test_gate_mapping_receipt_and_completed_count_are_required():
    w = World()
    w.gate.preflight = w.lua.eval("function(r) return {domain='CartRAM',domain_size=32768} end")
    with pytest.raises(LuaError, match="unqualified"):
        w.obj.commit(w.plan())
    assert w.state.writes == 0
    w = World()
    w.gate.execute = w.lua.eval("function(t,s) return {status='written',completed=5} end")
    with pytest.raises(LuaError, match="no rollback"):
        w.obj.commit(w.plan())


def test_plan_cannot_replay_and_external_write_error_is_not_called_rollback():
    w = World()
    plan = w.plan()
    w.obj.commit(plan)
    with pytest.raises(LuaError, match="consumed"):
        w.obj.commit(plan)
    assert w.state.writes == 1102
    w = World()
    w.gate.execute = w.lua.eval("function(s) return function(t,spans) s.writes=5; error('sink failed after five') end end")(w.state)
    plan = w.plan()
    with pytest.raises(LuaError, match="sink failed"):
        w.obj.commit(plan)
    assert w.state.writes == 5
    with pytest.raises(LuaError, match="consumed"):
        w.obj.commit(plan)


@pytest.mark.parametrize("title", ["crystal", "gold", "silver"])
def test_generated_flat_facts_match_independent_pinned_symbol_oracle(title):
    from tools.gen2_source_data import load_context

    context = load_context(title)
    w = World(title)
    # Independent test arithmetic; production plans consume generated flats and
    # never duplicate bank conversion or switch SRAM banks.
    for number, row in enumerate(w.profile["storage_boxes"], 1):
        symbol = context.symbol(f"sBox{number}")
        assert row["flat"] == symbol.bank * 8192 + symbol.address - 0xA000
    active = context.symbol("sBox")
    assert w.profile["derived"]["active_box_flat"] == active.bank * 8192 + active.address - 0xA000
    assert w.profile["derived"]["active_box_copy_length"] == context.symbol("sBoxEnd").address - active.address == 1102


@pytest.mark.parametrize("mutation", ["current_box", "saved", "before_byte"])
def test_preflight_cannot_mutate_sealed_requirements_before_execute(mutation):
    w = World()
    w.gate.preflight = w.lua.eval("""function(mutation)
        return function(r)
            if mutation == 'current_box' then r.observed_state.current_box=13
            elseif mutation == 'saved' then r.observed_state.saved_at_least_once=0
            else r.before_spans[1].bytes[1]=42 end
            return {mapping_qualified=true,domain='CartRAM',domain_size=32768}
        end
    end""")(mutation)
    plan = w.plan("memorial", current=0, target=13)
    with pytest.raises(LuaError, match="preflight.*requirements"):
        w.obj.commit(plan)
    assert w.state.writes == 0
    assert plan.requirements.observed_state.current_box == 0
    assert plan.requirements.observed_state.saved_at_least_once == 1
    assert plan.requirements.before_spans[1].bytes[1] == 1


def test_inspect_only_preflight_succeeds_and_execute_receives_fresh_sealed_copy():
    w = World()
    w.gate.preflight = w.lua.eval("""function(s)
        return function(r)
            s.inspected=r
            assert(r.observed_state.current_box==0 and r.observed_state.saved_at_least_once==1)
            return {mapping_qualified=true,domain='CartRAM',domain_size=32768}
        end
    end""")(w.state)
    w.gate.execute = w.lua.eval("""function(s)
        return function(ticket,spans,r)
            assert(r~=s.inspected and r.observed_state~=s.inspected.observed_state)
            assert(r.observed_state.current_box==0 and r.observed_state.saved_at_least_once==1)
            assert(r.before_spans[1].bytes[1]==1)
            s.writes=1102
            return {status='written',completed=1102}
        end
    end""")(w.state)
    assert w.obj.commit(w.plan("memorial", current=0, target=13)).status == "written"
    assert w.state.writes == 1102
