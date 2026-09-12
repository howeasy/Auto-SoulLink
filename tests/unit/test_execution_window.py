"""Command credits never stand in for ordinary/recovery authority or host control."""

import json
from pathlib import Path

import pytest
from lupa.lua54 import LuaRuntime

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def lua():
    runtime = LuaRuntime(unpack_returned_tuples=True)
    runtime.globals().package.path = (
        (ROOT / "lua/?.lua").as_posix() + ";" + runtime.globals().package.path
    )
    runtime.execute("""
        JSON=require('json_codec');Window=require('execution_window')
        time=0;serial=0;verify=true;delay=0;scope_delay=0;change=false;revoke_in_verify=false
        current={operation_id=string.rep('a',32),operation_digest=string.rep('b',64),
            context_generation=string.rep('c',32),binding_digest=string.rep('d',64),phase='native_commit'}
        function make_window(limit)return Window.new({max_operation_frames=limit,clock=function()return time end,current_scope=function()time=time+scope_delay;return current end,
            new_nonce=function()serial=serial+1;return string.format('%032x',serial)end,
            verify_grant=function()
                time=time+delay;if change then current.phase='native_release'end
                if revoke_in_verify then window:revoke('context invalidated during proof')end
                return verify
            end})end
        window=make_window()
        function challenge()return JSON.encode(assert(window:challenge()))end
        function accept(text)return window:accept(assert(JSON.decode(text)))end
        function consume()return window:consume(current)end
    """)
    return runtime


def packet(lua, **changes):
    return (
        json.loads(lua.globals().challenge())
        | {"frames": 3, "ttl_ms": 1000, "proof_digest": "e" * 64}
        | changes
    )


def accept(lua, value):
    return lua.globals().accept(json.dumps(value))


def test_command_budget_is_finite_and_never_grants_ordinary_or_recovery_execution(lua):
    assert not lua.eval("window:ready()")
    assert accept(lua, packet(lua))
    assert [lua.globals().consume() for _ in range(5)] == [True, True, True, False, False]
    status = dict(lua.eval("window:status()"))
    assert status["remaining"] == 0 and status["consumed"] == 3
    assert status["ordinary_execution"] is False and status["native_recovery_execution"] is False


def test_replayed_response_cannot_restore_spent_credits(lua):
    value = packet(lua)
    assert accept(lua, value) and lua.globals().consume()
    assert accept(lua, value)[0] is False
    assert not lua.globals().consume()


@pytest.mark.parametrize("age", [1, 2, 100])
def test_expiry_is_measured_from_challenge_not_response_receipt(lua, age):
    value = packet(lua)
    lua.globals().time = age
    assert accept(lua, value)[0] is False
    assert not lua.globals().consume()


@pytest.mark.parametrize(
    "field", ["operation_id", "operation_digest", "context_generation", "binding_digest", "phase"]
)
def test_operation_body_context_binding_and_phase_changes_revoke_the_window(lua, field):
    assert accept(lua, packet(lua))
    lua.globals().current[field] = (
        "replacement" if field == "phase" else "f" * (64 if field.endswith("digest") else 32)
    )
    assert not lua.globals().consume()


@pytest.mark.parametrize(
    "changes",
    [
        {"frames": 0},
        {"frames": 121},
        {"frames": True},
        {"frames": 1.5},
        {"ttl_ms": 0},
        {"ttl_ms": 2001},
        {"ttl_ms": True},
        {"proof_digest": "bad"},
        {"ordinary_execution": True},
        {"challenge": "f" * 32},
        {"schema": "ordinary-run"},
    ],
)
def test_unverified_or_unbounded_grants_are_refused(lua, changes):
    assert accept(lua, packet(lua, **changes))[0] is False
    assert not lua.globals().consume()


@pytest.mark.parametrize("fault", ["denied", "slow", "changed"])
def test_private_verifier_must_finish_with_fresh_matching_authority(lua, fault):
    if fault == "denied":
        lua.globals().verify = False
    elif fault == "slow":
        lua.globals().delay = 1
    else:
        lua.globals().change = True
    assert accept(lua, packet(lua))[0] is False
    assert not lua.globals().consume()


def test_renewal_uses_a_new_challenge_and_keeps_a_finite_new_budget(lua):
    first = packet(lua)
    assert accept(lua, first)
    assert lua.globals().consume()
    second = packet(lua, frames=2)
    assert second["challenge"] != first["challenge"]
    assert accept(lua, second)
    assert [lua.globals().consume() for _ in range(3)] == [True, True, False]


def test_clock_rollback_latches_failure_and_cannot_be_repaired_by_a_packet(lua):
    value = packet(lua)
    assert accept(lua, value)
    lua.globals().time = 0.5
    assert lua.globals().consume()
    lua.globals().time = 0.4
    assert lua.globals().consume()[0] is False
    lua.globals().time = 0.6
    assert accept(lua, value)[0] is False
    assert lua.eval("window:status().failed")


def test_no_operation_or_explicit_revocation_removes_all_credits(lua):
    assert accept(lua, packet(lua))
    lua.execute("current=nil")
    assert not lua.eval("window:ready()")
    assert lua.eval("window:status().remaining") == 0


def test_clock_failure_during_accept_also_latches_the_service(lua):
    value = packet(lua)
    lua.globals().time = -1
    assert accept(lua, value)[0] is False
    lua.globals().time = 0
    assert accept(lua, value)[0] is False
    assert lua.eval("window:status().failed")


def test_slow_owned_scope_read_cannot_spend_an_expired_window(lua):
    assert accept(lua, packet(lua))
    lua.globals().scope_delay = 1
    assert not lua.globals().consume()
    assert lua.eval("window:status().consumed") == 0


def test_renewal_cannot_extend_the_operation_wide_frame_ceiling(lua):
    lua.execute("window=make_window(5)")
    assert accept(lua, packet(lua, frames=3))
    assert lua.globals().consume() and lua.globals().consume()
    assert accept(lua, packet(lua, frames=3))
    assert all(lua.globals().consume() for _ in range(3))
    assert not lua.globals().consume()
    assert accept(lua, packet(lua, frames=1))[0] is False
    assert lua.eval("window:status().consumed") == 5


def test_explicit_revocation_does_not_refund_spent_operation_credits(lua):
    lua.execute("window=make_window(3)")
    assert accept(lua, packet(lua, frames=3)) and lua.globals().consume()
    lua.execute("window:revoke('test interruption')")
    assert accept(lua, packet(lua, frames=3))[0] is False
    assert accept(lua, packet(lua, frames=2))


def test_revocation_inside_verification_cannot_resurrect_a_grant(lua):
    value = packet(lua)
    lua.globals().revoke_in_verify = True
    assert accept(lua, value)[0] is False
    assert not lua.globals().consume()


@pytest.mark.parametrize(
    "field,value",
    [("extra", "a"), ("phase", True), ("operation_id", {}), ("binding_digest", "e" * 63)],
)
def test_scope_validation_still_refuses_extra_or_malformed_fields(lua, field, value):
    grant = packet(lua)
    grant["scope"][field] = value
    assert accept(lua, grant)[0] is False
    assert not lua.globals().consume()


def test_mutating_returned_challenge_cannot_change_the_private_pending_scope(lua):
    lua.execute("returned=assert(window:challenge());returned.scope.phase='native_release'")
    value = json.loads(lua.eval("JSON.encode(returned)")) | {
        "frames": 3,
        "ttl_ms": 1000,
        "proof_digest": "e" * 64,
    }
    lua.globals().current.phase = "native_release"
    assert accept(lua, value)[0] is False
    assert not lua.globals().consume()


@pytest.mark.parametrize("expression", ["setmetatable(current,{})", "JSON.array(current)"])
def test_scope_cannot_bypass_json_container_validation(lua, expression):
    assert accept(lua, packet(lua))
    lua.execute("current=" + expression)
    assert lua.globals().consume()[0] is False


@pytest.mark.parametrize(
    "field", ["phase", "operation_digest", "context_generation", "binding_digest"]
)
def test_scope_rebinding_does_not_refund_the_same_operation_budget(lua, field):
    lua.execute("window=make_window(2)")
    assert accept(lua, packet(lua, frames=2))
    assert lua.globals().consume() and lua.globals().consume()
    lua.execute("window:revoke('phase or context transition')")
    lua.globals().current[field] = (
        "native_release" if field == "phase" else "f" * (64 if field.endswith("digest") else 32)
    )
    assert accept(lua, packet(lua, frames=1))[0] is False
    assert not lua.globals().consume()
    assert lua.eval("window:status().consumed") == 2
