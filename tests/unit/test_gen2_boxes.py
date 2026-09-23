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


# ── the box executor (box_mon / party_mon / memorialize) over reads + writes + the CartRAM gate ──
# SOURCE: C/G engine/pokemon/move_mon.asm SendGetMonIntoFromBox :480-710 (withdraw: CalcMonStats,
# status 0, HP = max HP; deposit: RestorePPOfDepositedPokemon :711-775), RemoveMonFromPartyOrBox
# :1222-1370, CalcMonStatC :1424-1618, GetSquareRoot engine/math/get_square_root.asm, ComputeMaxPP
# engine/items/item_effects.asm:2752-2798. The stat/PP oracle below is independent Python.
EXEC = r"""
return function(root, profile, sys, cart, covers, held, base, pp, mail)
    local Permit = dofile(root .. "/lua/write_permit.lua")
    local B = dofile(root .. "/lua/gen2/boxes.lua")
    local io = {cart_ram_linear = true}
    function io.read_range(a, n, d)
        local src = d == "CartRAM" and cart or sys
        local out = {}
        for i = 1, n do out[i] = src[a + i - 1] end
        return out
    end
    function io.write_u8(a, v, d) (d == "CartRAM" and cart or sys)[a] = v end
    function io.bank_valid(bank, a, n) return (a < 0xD000 and bank == 0) or (a >= 0xD000 and bank == 1) end
    function io.domain_size(d) return d == "CartRAM" and 0x8000 or 0x10000 end
    local reads = assert(dofile(root .. "/lua/gen2/reads.lua").new(profile, io))
    local lifetime = {capture = function() return 1 end, valid = function() return held() end}
    local writes = dofile(root .. "/lua/gen2/writes.lua").new(profile, io, Permit, {
        authorize = function(op) return held() and op == "party_collection" and covers("party_collection") end,
        pointer_stable = function() return true end, lifetime = lifetime,
        provenance = function() return {site = "test"} end})
    local gate = B.cart_gate({Permit = Permit, profile = profile, io = io, lifetime = lifetime,
        check = function(kind) return held() and covers(kind) end,
        provenance = function() return {site = "test"} end})
    local box = B.new(profile, gate)
    local key = function(m) return string.format("%04X:%04X:%02X", m.dv_word, m.ot_id, m.species_id) end
    return B.executor({profile = profile, reads = reads, key = key, writes = writes, box = box, io = io,
        base_stats = function(s) return base end, move_pp = function(m) return pp end, mail = mail,
        covers = covers})
end
"""


def mon48(species=25, dvs=0x2AAA, ot=0x1234, level=20, item=0, moves=(33, 45, 0, 0), pp=(3, 0x41, 0, 0),
          exp=8000, statexp=(100, 200, 300, 400, 500)):
    raw = bytearray(48)
    raw[0], raw[1], raw[31] = species, item, level
    raw[2:6] = bytes(moves)
    raw[6:8] = ot.to_bytes(2, "big")
    raw[8:11] = exp.to_bytes(3, "big")
    for i, value in enumerate(statexp):
        raw[11 + 2 * i:13 + 2 * i] = value.to_bytes(2, "big")
    raw[21:23] = dvs.to_bytes(2, "big")
    raw[23:27] = bytes(pp)
    raw[34:36], raw[36:38] = (7).to_bytes(2, "big"), (60).to_bytes(2, "big")
    return bytes(raw)


def sqrt_ceil(value):
    return next((b for b in range(1, 255) if b * b >= value), 255)


def oracle_stats(raw, base, level):
    dvs = int.from_bytes(raw[21:23], "big")
    atk, dfn, spd, spc = dvs >> 12, (dvs >> 8) & 15, (dvs >> 4) & 15, dvs & 15
    hp_dv = (atk & 1) << 3 | (dfn & 1) << 2 | (spd & 1) << 1 | (spc & 1)
    exps = [int.from_bytes(raw[11 + 2 * i:13 + 2 * i], "big") for i in range(5)]
    rows = [(base[0], hp_dv, exps[0]), (base[1], atk, exps[1]), (base[2], dfn, exps[2]),
            (base[3], spd, exps[3]), (base[4], spc, exps[4]), (base[5], spc, exps[4])]
    out = []
    for i, (b, dv, e) in enumerate(rows):
        v = ((b + dv) * 2 + sqrt_ceil(e) // 4) * level // 100
        out.append(min(999, v + (level + 10 if i == 0 else 5)))
    return out


class Exec:
    BASE = (45, 49, 65, 45, 65, 65)

    def __init__(self, title="crystal", party=(), boxes=None, current=0, saved=1, kinds=None, pp=35):
        self.profile = json.loads((ROOT / f"data/games/gen2_{title}/profile.json").read_text())["titles"][title]
        p, d = self.profile, self.profile["derived"]
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.sys, self.cart = self.lua.table(), self.lua.table()
        for a in range(0xC000, 0xE000):
            self.sys[a] = 0
        for a in range(0x8000):
            self.cart[a] = 0
        self.kinds = set(kinds if kinds is not None else
                         ("party_collection", "box_deposit", "box_withdraw", "backing_box"))
        self.held = True
        self.sys[p["ram"]["wCurBox"]], self.sys[p["ram"]["wSavedAtLeastOnce"]] = current, saved
        self.poke_sys(p["ram"]["wPartyCount"], self.party_block(list(party)))
        self.current = current
        for index in range(14):
            mons = (boxes or {}).get(index, [])
            if index == current:
                self.poke_cart(d["active_box_flat"], self.box_block(mons)[:1102])
            else:
                self.poke_cart(p["storage_boxes"][index]["flat"], self.box_block(mons))
        self.base = self.lua.table_from(dict(zip(
            ("hp", "attack", "defense", "speed", "special_attack", "special_defense"), self.BASE)))
        self.ex = self.lua.execute(EXEC)(ROOT.as_posix(), self.lua.table_from(p, recursive=True), self.sys,
                                         self.cart, lambda k: k in self.kinds, lambda: self.held, self.base, pp,
                                         self.lua.table_from({0x9E: True}))

    def poke_sys(self, a, data):
        for i, b in enumerate(data):
            self.sys[a + i] = b

    def poke_cart(self, a, data):
        for i, b in enumerate(data):
            self.cart[a + i] = b

    @staticmethod
    def names(i):
        return bytes([0x80 + i, 0x50] + [0] * 9), bytes([0x90 + i, 0x50] + [0] * 9)

    def party_block(self, mons):
        raw = bytearray(428)
        raw[0], raw[len(mons) + 1] = len(mons), 255
        for i, m in enumerate(mons):
            raw[1 + i] = m[0]
            raw[8 + 48 * i:56 + 48 * i] = m
            ot, nick = self.names(m[0] % 16)
            raw[296 + 11 * i:307 + 11 * i], raw[362 + 11 * i:373 + 11 * i] = ot, nick
        return raw

    def box_block(self, mons):
        raw = bytearray([0] * 1104)
        raw[0], raw[len(mons) + 1] = len(mons), 255
        for i, m in enumerate(mons):
            raw[1 + i] = m[0]
            raw[22 + 32 * i:54 + 32 * i] = m[:32]
            ot, nick = self.names(m[0] % 16)
            raw[662 + 11 * i:673 + 11 * i], raw[882 + 11 * i:893 + 11 * i] = ot, nick
        return raw

    def snapshot(self):
        return (bytes(self.sys[a] for a in range(0xC000, 0xE000)), bytes(self.cart[a] for a in range(0x8000)))

    def party(self):
        a = self.profile["ram"]["wPartyCount"]
        return bytes(self.sys[a + i] for i in range(428))

    def box(self, index):
        d = self.profile
        flat = d["derived"]["active_box_flat"] if index == self.current else d["storage_boxes"][index]["flat"]
        return bytes(self.cart[flat + i] for i in range(1102))

    def run(self, op, m):
        key = "%04X:%04X:%02X" % (int.from_bytes(m[21:23], "big"), int.from_bytes(m[6:8], "big"), m[0])
        result = self.ex[op](key)
        return result if isinstance(result, tuple) else (result, None)


def test_box_mon_deposits_into_the_current_box_with_native_pp_and_compacts_the_party():
    lead, catch = mon48(), mon48(species=19, dvs=0x7AAA, pp=(0x41, 0x02, 0, 0))
    w = Exec(party=[lead, catch], boxes={0: [mon48(species=16)]})
    assert w.run("deposit", catch) == (True, None)
    party, box = w.party(), w.box(0)
    assert party[0] == 1 and party[1:3] == bytes([25, 255]) and party[8:56] == lead
    assert box[0] == 2 and box[1:4] == bytes([16, 19, 255])
    expected = bytearray(catch[:32])
    expected[23:27] = bytes([0x40 | (35 + 7), 35, 0, 0])   # ComputeMaxPP: base + ups*min(base//5, 7)
    assert box[54:86] == bytes(expected)
    assert box[673:684] == Exec.names(19 % 16)[0] and box[893:904] == Exec.names(19 % 16)[1]


def test_party_mon_withdraws_from_the_active_box_with_native_stats_full_hp_and_status_0():
    lead, boxed = mon48(), mon48(species=19, dvs=0xF3C5, level=37)
    w = Exec(party=[lead], boxes={0: [mon48(species=16), boxed]})
    assert w.run("withdraw", boxed) == (True, None)
    party, box = w.party(), w.box(0)
    assert party[0] == 2 and party[1:4] == bytes([25, 19, 255])
    record = party[56:104]
    stats = oracle_stats(boxed, Exec.BASE, 37)
    assert record[:32] == boxed[:32] and record[32:34] == b"\0\0"
    assert int.from_bytes(record[34:36], "big") == stats[0]
    assert [int.from_bytes(record[36 + 2 * i:38 + 2 * i], "big") for i in range(6)] == stats
    assert box[0] == 1 and box[1:3] == bytes([16, 255])


def test_party_mon_from_another_box_writes_only_that_backing_box():
    lead, boxed = mon48(), mon48(species=19, dvs=0x7AAA)
    w = Exec(party=[lead], boxes={4: [boxed]}, kinds={"party_collection", "backing_box"})
    active_before = w.box(0)
    assert w.run("withdraw", boxed) == (True, None)
    assert w.box(4)[0] == 0 and w.box(0) == active_before and w.party()[0] == 2


def test_memorialize_goes_to_sbox14_or_to_the_active_copy_when_box_14_is_current():
    lead, dead = mon48(), mon48(species=19, dvs=0x7AAA)
    w = Exec(party=[lead, dead], kinds={"party_collection", "backing_box"})
    assert w.run("memorialize", dead) == (True, None)
    assert w.box(13)[0] == 1 and w.box(13)[1] == 19 and w.party()[0] == 1
    w = Exec(party=[lead, dead], current=13, kinds={"party_collection", "box_deposit"})
    assert w.run("memorialize", dead) == (True, None)
    assert w.box(13)[0] == 1 and w.party()[0] == 1


def test_memorialize_after_a_reset_finishes_by_removing_only_the_party_copy():
    """Reset before save: sBox14 kept the memorial (plain SRAM) while the party reverted. A full-record
    match completes it with a party-only write; any other record under the same key refuses."""
    lead, dead = mon48(), mon48(species=19, dvs=0x7AAA)
    stored = bytearray(dead)
    stored[23:27] = bytes([35, 0x40 | 42, 0, 0])          # the deposit transform (PP restored, PP Up kept)
    w = Exec(party=[lead, dead], boxes={13: [bytes(stored)]}, kinds={"party_collection"})
    cart = w.snapshot()[1]
    assert w.run("memorialize", dead) == (True, None)
    assert w.party()[0] == 1 and w.snapshot()[1] == cart
    other = bytearray(stored)
    other[1] = 0x10                                       # same key, another held item
    w = Exec(party=[lead, dead], boxes={13: [bytes(other)]})
    before = w.snapshot()
    ok, why = w.run("memorialize", dead)
    assert ok is None and "both" in why and w.snapshot() == before


@pytest.mark.parametrize("op,party,boxes,reason", [
    ("deposit", "lead", {}, "last party mon"),
    ("memorialize", "lead", {}, "last party mon"),
    ("deposit", "mail", {}, "mail"),
    ("deposit", "two", {0: ["x"] * 20}, "current box full"),
    ("memorialize", "two", {13: ["x"] * 20}, "memorial box full"),
    ("withdraw", "six", {0: ["catch"]}, "party full"),
    ("withdraw", "lead", {}, "key not boxed"),
])
def test_refusals_write_nothing(op, party, boxes, reason):
    lead, catch = mon48(), mon48(species=19, dvs=0x7AAA)
    mail = mon48(species=19, dvs=0x7AAA, item=0x9E)
    parties = {"lead": [lead], "two": [lead, catch], "mail": [lead, mail],
               "six": [lead] + [mon48(species=20 + i, dvs=0x1000 * i) for i in range(5)]}
    fill = {k: [catch if v == "catch" else mon48(species=40 + i, dvs=0x2000 + i) for i, v in enumerate(vs)]
            for k, vs in boxes.items()}
    w = Exec(party=parties[party], boxes=fill)
    before = w.snapshot()
    target = mail if party == "mail" else lead if party == "lead" and op != "withdraw" else catch
    ok, why = w.run(op, target)
    assert ok is None and reason in why and w.snapshot() == before


@pytest.mark.parametrize("op,kind", [("deposit", "box_deposit"), ("withdraw", "box_withdraw"),
                                     ("withdraw", "backing_box"), ("memorialize", "backing_box"),
                                     ("deposit", "party_collection")])
def test_an_unproven_write_kind_refuses_before_any_byte(op, kind):
    lead, catch = mon48(), mon48(species=19, dvs=0x7AAA)
    party = [lead] if op == "withdraw" else [lead, catch]
    boxes = {4 if kind == "backing_box" else 0: [catch]} if op == "withdraw" else {}
    kinds = {"party_collection", "box_deposit", "box_withdraw", "backing_box"} - {kind}
    w = Exec(party=party, boxes=boxes, kinds=kinds)
    before = w.snapshot()
    ok, why = w.run(op, catch)
    assert ok is None and kind in why and w.snapshot() == before


def test_outside_the_held_checkpoint_nothing_is_written():
    lead, catch = mon48(), mon48(species=19, dvs=0x7AAA)
    w = Exec(party=[lead, catch])
    w.held = False
    before = w.snapshot()
    ok, _ = w.run("deposit", catch)
    assert ok is None and w.snapshot() == before


def test_repeats_are_idempotent_and_touch_nothing():
    lead, catch = mon48(), mon48(species=19, dvs=0x7AAA)
    w = Exec(party=[lead], boxes={0: [catch]})
    before = w.snapshot()
    assert w.run("deposit", catch) == (True, None) and w.snapshot() == before
    w = Exec(party=[lead, catch])
    before = w.snapshot()
    assert w.run("withdraw", catch) == (True, None) and w.snapshot() == before


def test_party_mon_after_a_reset_finishes_by_removing_only_the_box_copy():
    lead, catch = mon48(), mon48(species=19, dvs=0x7AAA)
    w = Exec(party=[lead, catch], boxes={4: [catch]})
    party = w.party()
    assert w.run("withdraw", catch) == (True, None)
    assert w.box(4)[0] == 0 and w.party() == party


@pytest.mark.parametrize("slot", [0, 1, 5])
def test_party_removal_compacts_like_remove_mon_from_party_or_box(slot):
    """Records/OTs/nicknames shift through the fixed arrays; removing slot 5 only marks its OT $FF."""
    mons = [mon48(species=20 + i, dvs=0x1111 * (i + 1)) for i in range(6)]
    w = Exec(party=mons)
    before = w.party()
    assert w.run("deposit", mons[slot]) == (True, None)
    after = w.party()
    expect = bytearray(before)
    expect[0] = 5
    species = list(before[1:8])
    del species[slot]
    expect[1:7] = bytes(species)
    if slot == 5:
        expect[296 + 55] = 0xFF
        expect[6] = 255
    else:
        for base, width in ((8, 48), (296, 11), (362, 11)):
            region = bytearray(before[base:base + 6 * width])
            region[slot * width:5 * width] = before[base + (slot + 1) * width:base + 6 * width]
            expect[base:base + 6 * width] = region
    assert after == bytes(expect)
