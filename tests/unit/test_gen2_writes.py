"""Gen 2 write binder controls; synthetic WRAM, SOURCE/MODEL only."""

import copy
import json
from pathlib import Path

import pytest
from lupa.lua54 import LuaError, LuaRuntime

ROOT = Path(__file__).resolve().parents[2]


class World:
    def __init__(self, title="crystal", profile=None):
        self.profile = profile or json.loads(
            (ROOT / f"data/games/gen2_{title}/profile.json").read_text()
        )["titles"][title]
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.memory = bytearray([0xA5] * 65536)
        self.writes = []
        self.bank_checks = []
        self.bank = 1
        self.reject_bank_at = None
        self.fail_on = None
        self.state = self.lua.table(epoch=1, frame=10, authorized=True, pointer_ok=True)
        factory = self.lua.eval("dofile")((ROOT / "lua/write_permit.lua").as_posix())
        module = self.lua.eval("dofile")((ROOT / "lua/gen2/writes.lua").as_posix())
        io = self.lua.eval("""function(emit, bank)
            return {write_u8=function(a,v,d) return emit(a,v,d) end,
                    bank_valid=function(b,a,n) return bank(b,a,n) end}
        end""")(self.emit, self.bank_valid)
        policy = self.lua.eval("""function(state)
            return {
                authorize=function(operation, request, reason) return state.authorized end,
                pointer_stable=function(token, addr, n)
                    return state.pointer_ok and addr ~= state.reject_pointer_at
                end,
                lifetime={capture=function() return state.epoch end,
                          valid=function(token) return token == state.epoch end},
                provenance=function(domain, addr, n)
                    assert(addr ~= state.reject_provenance_at, 'address-specific provenance refused')
                    return {site='MODEL checkpoint', frame=state.frame}
                end,
            }
        end""")(self.state)
        self.binder = module.new(self.lua.table_from(self.profile, recursive=True), io, factory, policy)

    def emit(self, address, value, domain):
        if self.fail_on == len(self.writes) + 1:
            raise RuntimeError("injected byte-write failure")
        assert domain == "System Bus"
        self.memory[int(address)] = int(value)
        self.writes.append((int(address), int(value), domain))

    def bank_valid(self, bank, address, length):
        self.bank_checks.append((int(bank), int(address), int(length)))
        return bank == self.bank and address != self.reject_bank_at

    def call(self, name, *args):
        return self.binder[name](self.binder, *args)

    def snapshot(self, *, mode=0, active=None, battle_type=0, link_mode=0):
        return self.lua.table(mode=mode, active_slot=active, battle_type=battle_type, link_mode=link_mode)


@pytest.mark.parametrize("title", ["crystal", "gold", "silver"])
def test_proven_party_faint_changes_only_hp_and_status_and_keeps_unused_byte(title):
    world = World(title)
    base = world.profile["ram"]["wPartyMons"] + 48
    before = bytes(world.memory)
    world.call("arm", "model_overworld")
    world.call("faint_party_slot", 1, world.snapshot())
    assert world.memory[base + 32] == 0
    assert world.memory[base + 34:base + 36] == b"\0\0"
    assert world.memory[base + 33] == 0xA5
    assert {a for a, _v, _d in world.writes} == {base + 32, base + 34, base + 35}
    assert bytes(world.memory[:base]) == before[:base]
    assert bytes(world.memory[base + 48:]) == before[base + 48:]
    assert world.binder.log[1].rom_sha1 == world.profile["rom_sha1"]
    assert world.binder.log[1].title == title
    assert world.binder.log[1].site == "MODEL checkpoint"


def test_unarmed_and_expired_scope_refuse_without_writes():
    world = World()
    with pytest.raises(LuaError, match="no armed"):
        world.call("faint_party_slot", 0, world.snapshot())
    assert world.writes == []
    world.call("arm", "model_overworld")
    world.state.epoch = 2
    with pytest.raises(LuaError, match="lifetime"):
        world.call("faint_party_slot", 0, world.snapshot())
    assert world.writes == [] and world.binder.armed is None


@pytest.mark.parametrize("control", ["bank", "pointer", "authority"])
def test_wrong_bank_unstable_pointer_or_missing_ownership_refuses_whole_write(control):
    world = World()
    world.call("arm", "model_overworld")
    if control == "bank":
        world.bank = 2
    elif control == "pointer":
        world.state.pointer_ok = False
    else:
        world.state.authorized = False
    with pytest.raises(LuaError):
        world.call("faint_party_slot", 0, world.snapshot())
    assert world.writes == [] and world.binder.armed is None


@pytest.mark.parametrize("payload", [{1: 1, 3: 2}, {1: 1, 2: 256}, {1: -1}, {0: 1}])
def test_malformed_full_party_payload_refuses_before_any_byte(payload):
    world = World()
    world.call("arm", "model_record")
    with pytest.raises(LuaError):
        world.call("write_party_bytes", 0, 0, world.lua.table_from(payload))
    assert world.writes == [] and world.binder.armed is None


@pytest.mark.parametrize("slot,offset,count", [(-1, 0, 1), (6, 0, 1), (0.5, 0, 1),
                                               (0, -1, 1), (0, 47, 2), (0, 48, 1)])
def test_party_interval_never_crosses_record_or_capacity_bounds(slot, offset, count):
    world = World()
    world.call("arm", "model_record")
    with pytest.raises(LuaError):
        world.call("write_party_bytes", slot, offset, world.lua.table(*([1] * count)))
    assert world.writes == [] and world.binder.armed is None


def test_positive_raw_party_span_uses_generated_bank_and_explicit_receipt():
    world = World("silver")
    world.call("arm", "model_record")
    world.call("write_party_bytes", 2, 21, world.lua.table(0x12, 0x34))
    address = world.profile["ram"]["wPartyMons"] + 2 * 48 + 21
    assert world.writes == [(address, 0x12, "System Bus"), (address + 1, 0x34, "System Bus")]
    assert world.bank_checks and all(bank == world.profile["ram_bank"]["wPartyMons"]
                                     for bank, _a, _n in world.bank_checks)


def test_bench_faint_allows_normal_battle_but_refuses_active_or_unclassified_target():
    world = World()
    world.call("arm", "model_battle")
    world.call("faint_party_slot", 1, world.snapshot(mode=2, active=0))
    assert len(world.writes) == 3
    before = list(world.writes)
    for snapshot in (world.snapshot(mode=2, active=1), world.snapshot(mode=2),
                     world.snapshot(mode=2, active=0, battle_type=3),
                     world.snapshot(mode=2, active=0, link_mode=1)):
        world.call("arm", "model_battle")
        with pytest.raises(LuaError):
            world.call("faint_party_slot", 1, snapshot)
        assert world.writes == before and world.binder.armed is None


def test_narrowed_faint_checks_both_discontiguous_fields_before_first_write():
    world = World()
    status = world.profile["ram"]["wPartyMon1Status"]
    allow = world.lua.eval("function(status) return function(d,a,n) return a==status and n==1 end end")(status)
    world.call("arm", "model_narrow", allow)
    with pytest.raises(LuaError, match="outside"):
        world.call("faint_party_slot", 0, world.snapshot())
    assert world.writes == [] and world.binder.armed is None


@pytest.mark.parametrize("policy", ["bank", "pointer", "provenance"])
def test_second_faint_span_policy_refusal_never_emits_status(policy):
    world = World()
    hp = world.profile["ram"]["wPartyMon1HP"]
    if policy == "bank":
        world.reject_bank_at = hp
    elif policy == "pointer":
        world.state.reject_pointer_at = hp
    else:
        world.state.reject_provenance_at = hp
    before = bytes(world.memory)
    world.call("arm", "model_two_span")
    with pytest.raises(LuaError):
        world.call("faint_party_slot", 0, world.snapshot())
    assert world.writes == [], "status must not be emitted before an already-invalid HP span is checked"
    assert bytes(world.memory) == before
    assert world.binder.armed is None and len(world.binder.log) == 0


@pytest.mark.parametrize("operation", ["faint_active_battler", "explode_active_battler"])
def test_unproved_active_action_path_is_explicitly_disabled(operation):
    world = World()
    world.call("arm", "battle_loop_head")
    with pytest.raises(LuaError, match="not qualified"):
        world.call(operation, 0)
    assert world.writes == [] and world.binder.armed is None


def test_partial_io_error_disarms_without_claiming_rollback():
    world = World()
    world.call("arm", "model_record")
    world.fail_on = 2
    with pytest.raises((RuntimeError, LuaError), match="byte-write failure"):
        world.call("write_party_bytes", 0, 21, world.lua.table(1, 2))
    assert len(world.writes) == 1 and world.binder.armed is None
    assert world.binder.log[1].status == "error" and world.binder.log[1].completed == 1


def test_faint_io_failure_after_status_reports_partial_batch_without_rollback():
    world = World()
    world.call("arm", "model_two_span")
    world.fail_on = 2
    with pytest.raises((RuntimeError, LuaError), match="byte-write failure"):
        world.call("faint_party_slot", 0, world.snapshot())
    status, hp = world.profile["ram"]["wPartyMon1Status"], world.profile["ram"]["wPartyMon1HP"]
    assert world.writes == [(status, 0, "System Bus")]
    assert world.memory[hp:hp + 2] == bytes([0xA5, 0xA5])
    assert world.binder.armed is None and len(world.binder.log) == 2
    assert world.binder.log[1].status == "written" and world.binder.log[1].completed == 1
    assert world.binder.log[2].status == "error" and world.binder.log[2].batch_index == 2
    assert world.binder.log[2].completed == 0 and world.binder.log[2].attempted == 1


def test_profile_field_or_bank_contradictions_have_no_guessed_fallback():
    original = World().profile
    for change in ("offset", "bank", "missing"):
        profile = copy.deepcopy(original)
        if change == "offset":
            profile["constants"]["MON_HP"] = 1
        elif change == "bank":
            profile["ram_bank"]["wPartyMon1HP"] = 2
        else:
            del profile["ram"]["wPartyMon1HP"]
        with pytest.raises(LuaError):
            World(profile=profile)


@pytest.mark.parametrize("title", ["crystal", "gold", "silver"])
def test_party_block_rewrite_covers_exactly_wpartycount_through_the_nicknames(title):
    """box ops rewrite the whole party collection (count, species list, records, OTs, nicknames):
    permit operation party_collection, never one byte past wPartyMonNicknamesEnd."""
    world = World(title)
    ram = world.profile["ram"]
    start, end = ram["wPartyCount"], ram["wPartyMonNicknamesEnd"]
    assert end - start == 428
    seen = []
    world.binder = world.lua.eval("dofile")((ROOT / "lua/gen2/writes.lua").as_posix()).new(
        world.lua.table_from(world.profile, recursive=True),
        world.lua.eval("function(e, b) return {write_u8=function(a,v,d) return e(a,v,d) end, bank_valid=function(k,a,n) return b(k,a,n) end} end")(
            world.emit, world.bank_valid),
        world.lua.eval("dofile")((ROOT / "lua/write_permit.lua").as_posix()),
        world.lua.eval("""function(seen) return {
            authorize=function(operation) seen(operation) return true end,
            pointer_stable=function() return true end,
            lifetime={capture=function() return 1 end, valid=function() return true end},
            provenance=function() return {site='MODEL'} end} end""")(seen.append))
    world.call("arm", "model_block")
    world.call("write_party_block", world.lua.table(*[i % 256 for i in range(428)]))
    assert seen == ["party_collection"]
    assert [a for a, _v, _d in world.writes] == list(range(start, end))
    world.call("arm", "model_block")
    for bad in (world.lua.table(*([0] * 427)), world.lua.table(*([0] * 429))):
        with pytest.raises(LuaError):
            world.call("write_party_block", bad)
        world.call("arm", "model_block")
    assert len(world.writes) == 428
