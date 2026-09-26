"""Generation-neutral write permit contract under Lua; MODEL evidence only."""

from pathlib import Path

import lupa
import pytest

PERMIT = (Path(__file__).resolve().parents[2] / "lua/write_permit.lua").as_posix()


class World:
    def __init__(self, *, expiring=False):
        self.lua = lupa.LuaRuntime(unpack_returned_tuples=True)
        self.events = []
        self.fail_on = None
        self.on_write = None
        self.policy = self.lua.table(epoch=1, frame=4, expiring=expiring, mapped=True, stable=True)
        factory = self.lua.eval(f'dofile("{PERMIT}")')
        options = self.lua.eval("""function(p, emit)
            return {
                write_u8 = function(a, v, domain) emit(a, v, domain) end,
                domains = { memory = {
                    bounds = function(a, n) return a >= (p.low or 100) and a + n <= (p.high or 120) end,
                    mapped = function(a) return p.mapped and a ~= p.reject_mapped_at end,
                    pointer_stable = function(a) return p.stable and a ~= p.reject_pointer_at end,
                } },
                lifetime = { capture = function() return p.epoch end,
                             valid = function(token) return not p.expiring or token == p.epoch end },
                provenance = function(domain, addr, n, reason)
                    assert(not p.fail_receipt, 'receipt failed')
                    assert(addr ~= p.reject_receipt_at, 'later receipt failed')
                    local receipt = p.reuse_receipt and p.receipt or {}
                    receipt.domain, receipt.addr, receipt.n = domain, addr, n
                    receipt.why, receipt.frame = reason, p.frame
                    if p.reuse_receipt then p.receipt = receipt end
                    return receipt
                end,
            }
        end""")(self.policy, self.emit)
        self.permit = factory.new(options)

    def emit(self, address, value, domain):
        if self.fail_on == len(self.events) + 1:
            raise RuntimeError("device write failed")
        self.events.append((int(address), int(value), str(domain)))
        if self.on_write:
            self.on_write()

    def call(self, method, *args):
        return self.permit[method](self.permit, *args)

    def write(self, address, *values):
        return self.call("write_bytes", "memory", address, self.lua.table(*values))

    def batch(self, spans):
        return self.call("write_batch", self.lua.table_from(spans, recursive=True))


def test_unarmed_refusal_then_positive_write_preserves_explicit_disarm_lifetime():
    world = World()
    with pytest.raises(lupa.LuaError, match="no armed write window"):
        world.write(100, 1)
    assert world.events == []
    world.call("arm", "checkpoint")
    world.write(100, 1, 2)
    world.policy.frame = 99
    world.policy.epoch = 2
    world.write(103, 3)
    assert world.events == [(100, 1, "memory"), (101, 2, "memory"), (103, 3, "memory")]
    assert world.permit.log[2].frame == 99
    world.call("disarm")
    with pytest.raises(lupa.LuaError, match="no armed write window"):
        world.write(104, 4)


@pytest.mark.parametrize("payload", [{1: 1, 3: 2}, {0: 1}, {1: 1, 2: -1}, {1: 256}, {1: 1.5}])
def test_entire_dense_byte_payload_is_validated_before_first_write(payload):
    world = World()
    world.call("arm", "checkpoint")
    with pytest.raises(lupa.LuaError):
        world.call("write_bytes", "memory", 100, world.lua.table_from(payload))
    assert world.events == []
    assert world.permit.armed is None


@pytest.mark.parametrize("address,values", [(99, [1]), (119, [1, 2]), (100.5, [1]), (2**63 - 1, [1])])
def test_invalid_whole_interval_refuses_without_clipping(address, values):
    world = World()
    world.call("arm", "checkpoint")
    with pytest.raises(lupa.LuaError):
        world.write(address, *values)
    assert world.events == []
    assert world.permit.armed is None


def test_narrowing_applies_to_the_whole_interval_and_clears_after_failure():
    world = World()
    allow = world.lua.eval("function(domain, a, n) return domain == 'memory' and a >= 104 and a+n <= 108 end")
    world.call("arm", "panel", allow)
    with pytest.raises(lupa.LuaError, match="outside the panel window"):
        world.write(107, 1, 2)
    assert world.events == [] and world.permit.armed is None
    world.call("arm", "checkpoint")
    world.write(100, 9)
    assert world.events == [(100, 9, "memory")]


@pytest.mark.parametrize("address", [float(2**53), float(-(2**53)), 2**53])
def test_nonrepresentable_byte_interval_refuses_before_emission(address):
    world = World()
    world.policy.low, world.policy.high = address, address + 2
    allow = world.lua.eval("function(_, a, n) return n == 2 end")
    world.call("arm", "wide-domain", allow)
    with pytest.raises(lupa.LuaError, match="interval arithmetic"):
        world.write(address, 1, 2)
    assert world.events == []
    assert world.permit.armed is None
    assert len(world.permit.log) == 0


@pytest.mark.parametrize("address", [float(2**53 - 3), float(-(2**53 - 1))])
def test_large_exact_byte_interval_emits_only_its_two_addresses(address):
    world = World()
    world.policy.low, world.policy.high = address, address + 2
    world.call("arm", "wide-domain")
    world.write(address, 1, 2)
    assert world.events == [(int(address), 1, "memory"), (int(address) + 1, 2, "memory")]


def test_io_failure_disarms_and_reports_only_completed_calls():
    world = World()
    world.call("arm", "checkpoint")
    world.fail_on = 2
    with pytest.raises((RuntimeError, lupa.LuaError), match="device write failed"):
        world.write(100, 1, 2, 3)
    assert world.events == [(100, 1, "memory")]
    assert world.permit.armed is None
    assert world.permit.log[1].status == "error"
    assert world.permit.log[1].completed == 1 and world.permit.log[1].attempted == 2
    with pytest.raises(lupa.LuaError, match="no armed write window"):
        world.write(105, 8)


@pytest.mark.parametrize("policy", ["mapped", "stable"])
def test_explicit_mapping_and_pointer_policies_refuse_before_writing(policy):
    world = World()
    world.policy[policy] = False
    world.call("arm", "checkpoint")
    with pytest.raises(lupa.LuaError):
        world.write(100, 1)
    assert world.events == [] and world.permit.armed is None


def test_injected_epoch_lifetime_expires_without_a_game_branch():
    world = World(expiring=True)
    world.call("arm", "checkpoint")
    world.policy.epoch = 2
    with pytest.raises(lupa.LuaError, match="lifetime"):
        world.write(100, 1)
    assert world.events == [] and world.permit.armed is None


def test_validation_snapshot_cannot_be_changed_by_a_write_callback():
    world = World()
    payload = world.lua.table(1, 2)
    world.on_write = lambda: payload.__setitem__(2, 300)
    world.call("arm", "checkpoint")
    world.call("write_bytes", "memory", 100, payload)
    assert world.events == [(100, 1, "memory"), (101, 2, "memory")]


def test_guard_and_scope_disarm_when_a_binder_callback_throws():
    world = World()
    fail = world.lua.eval("function() error('binder rejected') end")
    world.call("arm", "checkpoint")
    with pytest.raises(lupa.LuaError, match="binder rejected"):
        world.call("guard", fail)
    assert world.permit.armed is None
    with pytest.raises(lupa.LuaError, match="binder rejected"):
        world.call("scope", "checkpoint", None, fail)
    assert world.permit.armed is None
    assert world.call("scope", "checkpoint", None, world.lua.eval("function() return 7 end")) == 7
    assert world.permit.armed is None


def test_provenance_failure_refuses_before_first_byte_and_disarms():
    world = World()
    world.policy.fail_receipt = True
    world.call("arm", "checkpoint")
    with pytest.raises(lupa.LuaError, match="receipt failed"):
        world.write(100, 1)
    assert world.events == [] and world.permit.armed is None


@pytest.mark.parametrize("field", ["mapped", "stable"])
def test_changed_mapping_or_pointer_during_emission_stops_before_next_byte(field):
    world = World()
    world.on_write = lambda: world.policy.__setitem__(field, False)
    world.call("arm", "checkpoint")
    with pytest.raises(lupa.LuaError):
        world.write(100, 1, 2)
    assert world.events == [(100, 1, "memory")] and world.permit.armed is None
    assert world.permit.log[1].status == "error" and world.permit.log[1].completed == 1


def test_unknown_domain_has_no_implicit_system_bus_fallback():
    world = World()
    world.call("arm", "checkpoint")
    with pytest.raises(lupa.LuaError, match="unknown domain"):
        world.call("write_bytes", "System Bus", 100, world.lua.table(1))
    assert world.events == [] and world.permit.armed is None


def test_constructor_refuses_omitted_binder_policies():
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    factory = lua.eval(f'dofile("{PERMIT}")')
    with pytest.raises(lupa.LuaError, match="write_u8 required"):
        factory.new(lua.table())
    with pytest.raises(lupa.LuaError, match="explicit domains required"):
        factory.new(lua.table(write_u8=lua.eval("function() end")))


def two_spans():
    return [{"domain": "memory", "addr": 100, "bytes": [1]},
            {"domain": "memory", "addr": 106, "bytes": [2, 3]}]


@pytest.mark.parametrize("failure", ["payload", "sparse_payload", "unknown_domain", "bounds", "narrowing",
                                    "mapping", "pointer", "provenance", "lifetime", "overflow", "span_shape"])
def test_batch_preflights_every_span_before_any_emission(failure):
    world = World(expiring=True)
    spans = two_spans()
    allow = None
    if failure == "payload":
        spans[1]["bytes"] = [2, 300]
    elif failure == "sparse_payload":
        spans[1]["bytes"] = {1: 2, 3: 3}
    elif failure == "unknown_domain":
        spans[1]["domain"] = "unbound-domain"
    elif failure == "bounds":
        spans[1]["addr"] = 119
    elif failure == "narrowing":
        allow = world.lua.eval("function(_,a) return a == 100 end")
    elif failure == "mapping":
        world.policy.reject_mapped_at = 106
    elif failure == "pointer":
        world.policy.reject_pointer_at = 106
    elif failure == "provenance":
        world.policy.reject_receipt_at = 106
    elif failure == "overflow":
        spans[1]["addr"] = 2**53
    elif failure == "span_shape":
        spans[1]["unexpected"] = True
    world.call("arm", "batch-control", allow)
    if failure == "lifetime":
        world.policy.epoch = 2
    with pytest.raises(lupa.LuaError):
        world.batch(spans)
    assert world.events == [] and world.permit.armed is None
    assert len(world.permit.log) == 0, "preflight cannot claim that an earlier span was written"


def test_sparse_batch_refuses_without_first_span_emission():
    world = World()
    world.call("arm", "batch-control")
    spans = two_spans()
    with pytest.raises(lupa.LuaError, match="hole"):
        world.batch({1: spans[0], 3: spans[1]})
    assert world.events == [] and world.permit.armed is None


def test_batch_snapshots_later_descriptors_and_payloads_before_first_emission():
    world = World()
    spans = world.lua.table_from(two_spans(), recursive=True)

    def mutate_later_input():
        spans[2].addr = 119
        spans[2].domain = "unbound-domain"
        spans[2]["bytes"][2] = 300

    world.on_write = mutate_later_input
    world.call("arm", "batch-control")
    world.call("write_batch", spans)
    assert world.events == [(100, 1, "memory"), (106, 2, "memory"), (107, 3, "memory")]
    assert world.permit.log[1].batch_index == 1 and world.permit.log[1].batch_size == 2
    assert world.permit.log[2].completed == 2 and world.permit.log[2].status == "written"


@pytest.mark.parametrize("change", ["mapping", "pointer", "lifetime", "bounds", "narrowing", "replacement"])
def test_batch_revalidates_after_an_earlier_span_has_emitted(change):
    world = World(expiring=True)
    world.policy.window_open = True
    allow = world.lua.eval("function(p) return function() return p.window_open end end")(world.policy)

    def change_policy():
        if change == "mapping":
            world.policy.reject_mapped_at = 106
        elif change == "pointer":
            world.policy.reject_pointer_at = 106
        elif change == "lifetime":
            world.policy.epoch = 2
        elif change == "bounds":
            world.policy.high = 101
        elif change == "narrowing":
            world.policy.window_open = False
        else:
            world.call("arm", "replacement")

    world.on_write = change_policy
    world.call("arm", "batch-control", allow)
    with pytest.raises(lupa.LuaError):
        world.batch(two_spans())
    assert world.events == [(100, 1, "memory")] and world.permit.armed is None
    assert world.permit.log[1].status == "written" and world.permit.log[1].completed == 1
    assert world.permit.log[2].status == "error"
    assert world.permit.log[2].completed == 0 and world.permit.log[2].attempted == 0


def test_batch_io_failure_reports_earlier_span_and_failed_attempt_without_rollback():
    world = World()
    world.fail_on = 2
    world.call("arm", "batch-control")
    spans = [*two_spans(), {"domain": "memory", "addr": 110, "bytes": [4]}]
    with pytest.raises((RuntimeError, lupa.LuaError), match="device write failed"):
        world.batch(spans)
    assert world.events == [(100, 1, "memory")] and world.permit.armed is None
    assert len(world.permit.log) == 2  # The tail span was not attempted.
    assert world.permit.log[1].status == "written" and world.permit.log[1].batch_size == 3
    assert world.permit.log[2].status == "error"
    assert world.permit.log[2].completed == 0 and world.permit.log[2].attempted == 1


def test_empty_singleton_payload_keeps_legacy_receipt_behavior():
    world = World()
    world.call("arm", "batch-control")
    world.write(100)
    assert world.events == [] and len(world.permit.log) == 1
    assert world.permit.log[1].status == "written" and world.permit.log[1].completed == 0


def test_batch_receipts_do_not_alias_a_reused_provenance_table():
    world = World()
    world.policy.reuse_receipt = True
    world.call("arm", "batch-control")
    world.batch(two_spans())
    assert world.permit.log[1].addr == 100 and world.permit.log[1].completed == 1
    assert world.permit.log[2].addr == 106 and world.permit.log[2].completed == 2
    assert world.permit.log[1].batch_index == 1 and world.permit.log[2].batch_index == 2


def test_empty_batch_still_requires_a_live_permit_but_emits_no_receipt():
    world = World(expiring=True)
    with pytest.raises(lupa.LuaError, match="no armed"):
        world.batch([])
    world.call("arm", "empty-batch")
    world.batch([])
    assert world.events == [] and len(world.permit.log) == 0
    world.policy.epoch = 2
    with pytest.raises(lupa.LuaError, match="lifetime"):
        world.batch([])
    assert world.permit.armed is None
