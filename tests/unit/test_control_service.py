import json
from pathlib import Path

import pytest
from lupa import LuaRuntime

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def runtime():
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.globals().package.path = (ROOT / "lua/?.lua").as_posix() + ";" + lua.globals().package.path
    lua.execute("""
        JSON=require('json_codec');Control=require('control_service')
        clock=0;nonce=0;held=nil;user_paused=false;hold_failed=false;hold_refused=false;serviced=0
        function make_control(service_execution)
            return Control.new({clock=function() return clock end,
                service_execution=service_execution,
                new_nonce=function() nonce=nonce+1;return string.format('%032x',nonce) end,
                host={set_held=function(value,why)
                    if hold_failed then error('injected actuator failure') end
                    if hold_refused then return false end
                    held=value;hold_reason=why
                    return true
                end}})
        end
        control=make_control()
        function bind(text) control:bind(assert(JSON.decode(text))) end
        function accept(text) return control:accept(assert(JSON.decode(text))) end
        function service() serviced=serviced+1 end
    """)
    return lua


def bind(lua, session="a"):
    binding = {"session_id": session * 32, "admission_epoch": "b" * 32,
               "context_generation": "c" * 32, "binding_digest": "d" * 64}
    lua.globals().bind(json.dumps(binding))
    return binding


def challenge(lua):
    return dict(lua.globals().control.challenge(lua.globals().control))


def permit(lua, packet=None, epoch="e"):
    packet = (packet or challenge(lua)) | {
        "authority": "run", "service_epoch": epoch * 32, "service_digest": epoch * 64,
        "recovery_epoch": epoch * 32, "ticket_digest": "f" * 64,
    }
    return lua.globals().accept(json.dumps(packet))


def step(lua):
    return lua.globals().control.step(lua.globals().control, lua.globals().service)


def test_admission_connection_and_semantic_ack_are_not_execution_permission(runtime):
    lua = runtime
    assert lua.globals().held is True
    bind(lua)
    step(lua)
    assert lua.globals().held is True
    assert not lua.globals().accept('{"ack":"ACK"}')
    assert lua.globals().held is True
    assert permit(lua)
    assert lua.globals().held is True  # no actuator release from the packet handler
    assert step(lua)
    assert lua.globals().held is False


@pytest.mark.parametrize("user_pause", [False, True])
def test_independent_hold_preserves_user_pause_and_services_without_frames(runtime, user_pause):
    lua = runtime
    lua.globals().user_paused = user_pause
    bind(lua)
    for _ in range(20):
        step(lua)
    assert lua.globals().serviced == 20
    assert lua.globals().held is True
    assert lua.globals().user_paused is user_pause
    assert permit(lua)
    step(lua)
    assert lua.globals().held is False
    assert lua.globals().user_paused is user_pause


@pytest.mark.parametrize("age,held", [(0, False), (1.999, False), (2, True), (10, True)])
def test_two_second_timeout_is_wall_clock_based(runtime, age, held):
    lua = runtime
    bind(lua)
    permit(lua)
    step(lua)
    lua.globals().clock = age
    step(lua)
    assert lua.globals().held is held
    if held:
        assert not lua.globals().control.status(lua.globals().control).admitted


def test_timeout_revokes_inflight_reply_and_requires_new_epoch_after_readmission(runtime):
    lua = runtime
    bind(lua)
    permit(lua)
    step(lua)
    lua.globals().clock = 0.5
    late = challenge(lua)
    lua.globals().clock = 2.01
    step(lua)
    assert lua.globals().held
    assert not permit(lua, late)
    bind(lua, "1")
    assert not permit(lua, epoch="e")
    assert permit(lua, epoch="2")
    step(lua)
    assert not lua.globals().held


def test_delayed_response_ttl_starts_at_request_issue_not_receipt(runtime):
    lua = runtime
    bind(lua)
    packet = challenge(lua)
    lua.globals().clock = 1.9
    assert permit(lua, packet)
    step(lua)
    lua.globals().clock = 2
    step(lua)
    assert lua.globals().held
    assert not permit(lua, packet)


def test_service_crossing_old_deadline_cannot_renew_with_younger_inflight_reply(runtime):
    lua = runtime
    bind(lua)
    permit(lua)
    step(lua)
    lua.globals().clock = 1.5
    packet = challenge(lua) | {"authority": "run", "service_epoch": "e" * 32,
                               "service_digest": "e" * 64,
                               "recovery_epoch": "e" * 32, "ticket_digest": "f" * 64}
    lua.globals().reply_text = json.dumps(packet)
    lua.execute("""
        function service()
            clock=2.1
            accepted=control:accept(assert(JSON.decode(reply_text)))
        end
    """)
    lua.globals().clock = 1.9
    assert step(lua)
    assert lua.globals().accepted is False
    assert lua.globals().held is True
    assert not lua.globals().control.status(lua.globals().control).admitted


def test_challenge_creation_after_timeout_revokes_instead_of_refreshing_lease(runtime):
    lua = runtime
    bind(lua)
    permit(lua)
    step(lua)
    lua.globals().clock = 2
    with pytest.raises(Exception, match="no active control binding"):
        challenge(lua)
    assert lua.globals().held is True
    assert not lua.globals().control.status(lua.globals().control).admitted


@pytest.mark.parametrize("field", ["session_id", "admission_epoch", "context_generation", "binding_digest", "challenge"])
def test_stale_binding_or_challenge_cannot_grant_execution(runtime, field):
    lua = runtime
    bind(lua)
    packet = challenge(lua)
    packet[field] = "0" * len(packet[field])
    assert not permit(lua, packet)
    step(lua)
    assert lua.globals().held


@pytest.mark.parametrize("why", ["disconnect", "admission rejected", "reset", "loadstate", "uncertain mutation"])
def test_explicit_revocation_is_immediate_and_stale_reply_is_inert(runtime, why):
    lua = runtime
    bind(lua)
    permit(lua)
    step(lua)
    packet = challenge(lua)
    lua.globals().control.revoke(lua.globals().control, why)
    assert lua.globals().held
    assert not permit(lua, packet)


def test_server_hold_cannot_be_undone_by_old_reconciliation_ticket(runtime):
    lua = runtime
    bind(lua)
    permit(lua)
    step(lua)
    packet = challenge(lua) | {"authority": "hold", "reason": "partner uncertain mutation"}
    assert lua.globals().accept(json.dumps(packet))
    assert lua.globals().held
    assert not permit(lua)
    assert permit(lua, epoch="2")
    step(lua)
    assert not lua.globals().held


@pytest.mark.parametrize("failure", ["clock", "network", "persistence", "readback"])
def test_runtime_failure_latches_hold_and_does_not_dequeue_uncertain_work(runtime, failure):
    lua = runtime
    bind(lua)
    permit(lua)
    step(lua)
    if failure == "clock":
        lua.globals().clock = -1
    else:
        lua.execute(f"function service() error('{failure} failed') end")
    ok, why = step(lua)
    assert ok is False
    assert why
    assert lua.globals().held
    assert lua.globals().control.status(lua.globals().control).failed
    with pytest.raises(Exception, match="requires reopening"):
        bind(lua)


def test_unavailable_hold_actuator_is_reported_not_claimed_safe(runtime):
    lua = runtime
    lua.globals().hold_failed = True
    with pytest.raises(Exception, match="actuator failure"):
        lua.globals().make_control()
    ok, reason = step(lua)
    assert ok is False
    assert "execution hold failed" in reason


def test_clock_failure_in_external_packet_callback_holds_immediately(runtime):
    lua = runtime
    bind(lua)
    permit(lua)
    step(lua)
    packet = challenge(lua)
    lua.globals().clock = -1
    with pytest.raises(Exception, match="clock failed"):
        permit(lua, packet)
    assert lua.globals().held
    assert lua.globals().control.status(lua.globals().control).failed


def test_false_return_from_actuator_is_not_accepted_as_verified_hold(runtime):
    lua = runtime
    lua.globals().hold_refused = True
    with pytest.raises(Exception, match="not verified"):
        lua.globals().make_control()
    ok, why = step(lua)
    assert ok is False
    assert "execution hold failed" in why


def test_bounded_recovery_frames_are_never_inferred_from_ordinary_ticket(runtime):
    lua = runtime
    bind(lua)
    permit(lua)
    step(lua)
    status = lua.globals().control.status(lua.globals().control)
    assert status.ordinary_execution
    assert status.native_recovery_execution is False


def test_service_authority_releases_only_a_service_selected_client(runtime):
    lua = runtime
    lua.execute("control=make_control(true)")
    bind(lua)
    packet = challenge(lua) | {
        "authority": "service", "service_epoch": "e" * 32,
        "service_digest": "f" * 64, "reason": "recovery proof is still pending",
    }
    assert lua.globals().accept(json.dumps(packet))
    assert lua.globals().held is True
    assert step(lua)
    status = lua.globals().control.status(lua.globals().control)
    assert status.authority == "service" and status.service_execution
    assert not status.ordinary_execution and not status.native_recovery_execution
    assert lua.globals().held is False


def test_revocation_bars_a_stale_service_epoch(runtime):
    lua = runtime
    lua.execute("control=make_control(true)")
    bind(lua)
    packet = challenge(lua) | {
        "authority": "service", "service_epoch": "e" * 32,
        "service_digest": "f" * 64, "reason": "service ready",
    }
    assert lua.globals().accept(json.dumps(packet))
    step(lua)
    lua.globals().control.revoke(lua.globals().control, "disconnect")
    assert lua.globals().held is True
    assert lua.globals().control.status(lua.globals().control).barred_service_epoch == "e" * 32
    bind(lua, "1")
    stale = challenge(lua) | {
        "authority": "service", "service_epoch": "e" * 32,
        "service_digest": "f" * 64, "reason": "stale service",
    }
    assert not lua.globals().accept(json.dumps(stale))
    assert lua.globals().control.status(lua.globals().control).authority == "hold"


def test_temporary_server_hold_allows_same_service_epoch_to_resume(runtime):
    lua = runtime
    lua.execute("control=make_control(true)")
    bind(lua)
    service = {"authority": "service", "service_epoch": "e" * 32,
               "service_digest": "f" * 64, "reason": "service ready"}
    assert lua.globals().accept(json.dumps(challenge(lua) | service))
    step(lua)
    assert lua.globals().held is False
    held = challenge(lua) | {"authority": "hold", "reason": "startup peer still settling"}
    assert lua.globals().accept(json.dumps(held))
    status = lua.globals().control.status(lua.globals().control)
    assert lua.globals().held is True and status.barred_service_epoch is None
    assert lua.globals().accept(json.dumps(challenge(lua) | service))
    step(lua)
    assert lua.globals().held is False


def test_owner_keyed_mux_keeps_startup_and_writer_holds_independent(runtime):
    lua = runtime
    lua.execute("""
        physical=false;writes=0
        mux=require('hold_mux').new({owners={'startup','control','writer','lifecycle'},
            host={set_held=function(value)physical=value;writes=writes+1;return true end}})
        assert(mux:set('startup',true,'atomic startup'))
        assert(mux:set('control',true,'control hold'))
        assert(mux:set('control',false,'service lease current'))
        assert(physical and mux:held('startup'))
        assert(mux:set('writer',true,'held writer'))
        assert(mux:set('startup',false,'startup complete'))
        assert(physical and mux:held('writer'))
        assert(mux:set('writer',false,'writer complete'))
        assert(not physical)
    """)


def test_mux_construction_never_releases_startup_on_stale_lease_or_builder_failure(runtime):
    lua = runtime
    lua.execute("""
        physical=false;current=true
        mux=require('hold_mux').new({owners={'startup','control','writer','lifecycle'},
            host={set_held=function(value)physical=value;return true end}})
        assert(mux:set('startup',true,'atomic startup'))
        local ok=pcall(function()mux:construct_and_release('startup','constructed',
            function()return current end,function()current=false;return {}end)end)
        assert(not ok and physical and mux:held('startup'))
        current=true
        ok=pcall(function()mux:construct_and_release('startup','constructed',
            function()return current end,function()error('builder failed')end)end)
        assert(not ok and physical and mux:held('startup'))
        local built=mux:construct_and_release('startup','constructed',function()return current end,
            function()assert(physical);return {ready=true}end)
        assert(built.ready and not physical and not mux:held('startup'))
    """)


def test_mux_rolls_back_an_unverified_owner_release(runtime):
    lua = runtime
    lua.execute("""
        physical=false;refuse_release=false
        mux=require('hold_mux').new({owners={'writer'},host={set_held=function(value)
            if not value and refuse_release then return false,'injected refusal'end
            physical=value;return true
        end}})
        assert(mux:set('writer',true,'write begins'))
        refuse_release=true
        local ok,why=mux:set('writer',false,'write ends')
        assert(not ok and why=='injected refusal' and mux:held('writer') and physical)
    """)
