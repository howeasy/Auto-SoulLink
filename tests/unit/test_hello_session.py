"""Neutral connection/hello scheduler controls; synchronous MODEL callbacks only."""

from pathlib import Path

import pytest
from lupa.lua54 import LuaRuntime

ROOT = Path(__file__).resolve().parents[2]


class World:
    def __init__(self, retry=1, clock_rewind="invalidate", callback_error="invalidate"):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.factory = self.lua.eval("dofile")((ROOT / "lua/hello_session.lua").as_posix())
        self.state = self.lua.table(connected=True, identity="save-a", live=True, sent=True,
                                    fail_stage="", retry=retry, attempts=0, invalidations=0, errors=0)
        policy = self.lua.eval("""function(s, clock_rewind, callback_error)
            local function check(stage) if s.fail_stage == stage then error(stage .. ' unavailable') end end
            return {
                clock_rewind=clock_rewind, callback_error=callback_error,
                connected=function() check('connected'); return s.connected end,
                identity=function() check('identity'); return s.identity end,
                ready=function() check('ready'); return s.live, 'game hold' end,
                send=function(identity)
                    check('send'); s.attempts=s.attempts+1; s.last_identity=identity
                    if s.drop_during_send then s.connected=false end
                    if s.change_during_send then s.identity='save-b' end
                    return s.sent, 'send refused'
                end,
                retry_delay=function() check('retry'); return s.retry end,
                on_invalidate=function(reason, identity)
                    s.invalidations=s.invalidations+1; s.last_reason=reason; check('invalidate')
                end,
                on_error=function(stage, why) s.errors=s.errors+1; s.last_error=stage .. ':' .. why end,
            }
        end""")(self.state, clock_rewind, callback_error)
        self.policy = policy
        self.scheduler = self.factory.new(policy)

    def step(self, now):
        result = self.scheduler.step(self.scheduler, now)
        return result[0] if isinstance(result, tuple) else result

    def send_now(self, now):
        result = self.scheduler.send_now(self.scheduler, now)
        return result[0] if isinstance(result, tuple) else result

    def status(self):
        return self.scheduler.status(self.scheduler)


def test_one_hello_for_stable_identity_and_no_rehello_just_because_a_menu_opens():
    world = World()
    assert world.step(1) is True
    world.state.live = False
    assert world.step(2) is True
    assert world.state.attempts == 1
    status = world.status()
    status.ready = False
    assert world.status().ready is True


def test_disconnection_revokes_readiness_and_reconnect_sends_again():
    world = World()
    assert world.step(1) is True
    world.state.connected = False
    assert world.step(2) is False
    assert world.status().ready is False
    world.state.connected = True
    assert world.step(3) is True
    assert world.state.attempts == 2


def test_injected_readiness_blocks_sending_and_retries_at_the_injected_delay():
    world = World(retry=5)
    world.state.live = False
    assert world.step(10) is False and world.state.attempts == 0
    world.state.live = True
    assert world.step(14) is False and world.state.attempts == 0
    assert world.step(15) is True and world.state.attempts == 1


def test_explicit_reset_same_identity_and_changed_identity_each_require_a_new_hello():
    world = World()
    assert world.step(1) is True
    world.scheduler.invalidate(world.scheduler, "save_reset")
    assert world.status().ready is False
    assert world.step(2) is True
    world.state.identity = "save-b"
    assert world.step(3) is True
    assert world.state.attempts == 3 and world.state.last_identity == "save-b"
    assert world.state.last_reason == "identity_changed"


def test_clock_rewind_invalidates_the_previous_session():
    world = World()
    assert world.step(100) is True
    assert world.step(1) is True
    assert world.state.attempts == 2 and world.state.last_reason == "clock_rewound"


@pytest.mark.parametrize("result", [False, None])
def test_unsuccessful_send_never_marks_ready_and_retries(result):
    world = World()
    world.state.sent = result
    assert world.step(1) is False
    assert world.status().ready is False
    world.state.sent = True
    assert world.step(2) is True
    assert world.state.attempts == 2


@pytest.mark.parametrize("stage", ["connected", "identity", "ready", "send", "retry"])
def test_callback_error_refuses_without_stale_readiness(stage):
    world = World()
    if stage in {"connected", "identity"}:
        assert world.step(1) is True
    elif stage == "retry":
        world.state.live = False
    world.state.fail_stage = stage
    assert world.step(2) is False
    assert world.status().ready is False and world.state.errors >= 1
    world.state.fail_stage = ""
    world.state.live = True
    assert world.step(3) is True


@pytest.mark.parametrize("change", ["drop_during_send", "change_during_send"])
def test_send_cannot_publish_readiness_for_a_changed_connection_or_identity(change):
    world = World()
    world.state[change] = True
    assert world.step(1) is False
    assert world.status().ready is False


def test_missing_identity_and_failed_invalidation_cleanup_remain_held():
    world = World()
    assert world.step(1) is True
    world.state.identity = None
    assert world.step(2) is False
    world.state.fail_stage = "invalidate"
    world.scheduler.invalidate(world.scheduler, "reset")
    world.state.identity = "save-a"
    assert world.step(3) is False
    world.state.fail_stage = ""
    assert world.step(4) is True


def test_identity_change_across_disconnection_still_notifies_the_binder():
    world = World()
    assert world.step(1) is True
    world.state.connected = False
    assert world.step(2) is False
    world.state.identity = "save-b"
    world.state.connected = True
    assert world.step(3) is True
    assert world.state.last_reason == "identity_changed"


def test_throwing_send_uses_the_injected_retry_delay_too():
    world = World(retry=5)
    world.state.fail_stage = "send"
    assert world.step(10) is False
    world.state.fail_stage = ""
    assert world.step(14) is False and world.state.attempts == 0
    assert world.step(15) is True and world.state.attempts == 1


@pytest.mark.parametrize("field", ["clock_rewind", "callback_error"])
def test_rewind_and_callback_error_policies_are_explicit(field):
    world = World()
    world.policy[field] = None
    with pytest.raises(Exception, match=field):
        world.factory.new(world.policy)


def test_keep_policy_survives_a_clock_rewind_with_one_hello_and_no_stale_deadline():
    world = World(retry=50, clock_rewind="keep")
    assert world.step(100) is True
    assert world.step(1) is True
    assert world.state.attempts == 1 and world.state.invalidations == 0
    world.scheduler.invalidate(world.scheduler, "save_reset")
    world.state.live = False
    assert world.step(200) is False  # deadline 250 on this timeline
    world.state.live = True
    assert world.step(10) is True  # a rewind drops the old deadline instead of waiting it out


def test_raise_policy_propagates_a_callback_error_and_keeps_the_session():
    world = World(callback_error="raise")
    assert world.step(1) is True
    world.state.fail_stage = "connected"
    with pytest.raises(Exception, match="connected unavailable"):
        world.step(2)
    assert world.status().ready is True and world.state.invalidations == 0
    world.state.fail_stage = ""
    assert world.step(3) is True and world.state.attempts == 1


def test_send_now_skips_the_ready_gate_and_existing_readiness_but_not_the_connection():
    world = World()
    world.state.live = False
    assert world.send_now(1) is True and world.state.attempts == 1
    assert world.send_now(2) is True and world.state.attempts == 2
    assert world.status().ready is True
    assert world.step(3) is True and world.state.attempts == 2
    world.state.connected = False
    assert world.send_now(4) is False and world.state.attempts == 2
