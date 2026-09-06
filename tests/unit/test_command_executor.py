"""Crash boundaries for generic execution, independent of any cartridge layout."""
import json

import pytest

from tests.unit.test_client_journal import accepted, command, start
from tests.unit.test_client_state_store import runtime  # noqa: F401


def start_executor(lua):
    start(lua)
    event = lua.globals().append('{"event":"tick"}')
    assert accepted(lua.globals().accept(event, json.dumps([command(1)])))
    lua.globals().command_id = command(1)["command_id"]
    lua.execute("""
        Executor=require('command_executor');effect=20;applied=0;fail_at=nil
        adapter={
            prepare=function()
                if fail_at=='prepare' then error('preparation exception') end
                return {schema='fixture-v1',before=20,after=0}
            end,
            classify=function(body,intent)
                if fail_at=='classify' then error('readback exception') end
                if effect==intent.after then return 'after',{hp=effect} end
                if effect==intent.before then return 'before',{hp=effect} end
                return 'diverged','unexpected physical state'
            end,
            apply=function()
                applied=applied+1
                if fail_at=='before_effect' then error('before effect') end
                if fail_at=='partial' then effect=10;error('partial effect') end
                if fail_at=='no_effect' then return true end
                effect=0
                if fail_at=='after_effect' then error('after effect') end
                if fail_at=='receipt_before' then mode='before' end
                if fail_at=='receipt_after' then mode='after' end
                return false -- return codes cannot prove or disprove the effect
            end,
            receipt=function(body,intent,observation)
                if fail_at=='receipt' then error('receipt exception') end
                return {schema='fixture-receipt-v1',hp=observation.hp}
            end,
        }
        executor=Executor.new(journal,adapter)
        function run()return executor:step(command_id)end
        function restart_executor()reopen();executor=Executor.new(journal,adapter)end
    """)


@pytest.mark.parametrize("mode,prepared", [("before", False), ("after", True)])
def test_no_effect_before_confirmed_preparation_publication(runtime, mode, prepared):  # noqa: F811
    lua = runtime
    start_executor(lua)
    lua.globals().mode = mode
    ok, diagnostic = lua.globals().run()
    assert ok is False and diagnostic.phase == "persist_intent" and diagnostic.retryable is True
    assert lua.globals().effect == 20 and lua.globals().applied == 0
    lua.globals().mode = "ok"
    lua.globals().restart_executor()
    assert (lua.globals().state().inbox[1].intent is not None) is prepared
    assert lua.globals().run()[0] is True
    assert lua.globals().applied == 1 and lua.globals().effect == 0


@pytest.mark.parametrize("failure,changed", [("before_effect", False), ("after_effect", True),
                                            ("receipt", True), ("receipt_before", True), ("receipt_after", True)])
def test_restart_classifies_effect_and_never_repeats_a_proven_poststate(runtime, failure, changed):  # noqa: F811
    lua = runtime
    start_executor(lua)
    lua.globals().fail_at = failure
    ok, diagnostic = lua.globals().run()
    assert ok is False and diagnostic.outcome == "NACK" and diagnostic.retryable is True
    assert lua.globals().effect == (0 if changed else 20)
    before_recovery = lua.globals().applied
    lua.globals().mode = "ok"
    lua.globals().fail_at = None
    lua.globals().restart_executor()
    assert lua.globals().run()[0] is True
    assert lua.globals().applied == before_recovery + int(not changed)
    assert len(lua.globals().state().outbox) == 1
    assert lua.globals().run()[0] is True
    assert len(lua.globals().state().outbox) == 1


def test_partial_effect_refuses_retry_and_retains_intent_without_terminal_receipt(runtime):  # noqa: F811
    lua = runtime
    start_executor(lua)
    lua.globals().fail_at = "partial"
    assert lua.globals().run()[0] is False
    lua.globals().fail_at = None
    lua.globals().restart_executor()
    ok, diagnostic = lua.globals().run()
    assert ok is False and "unexpected physical state" in diagnostic.reason
    assert lua.globals().applied == 1 and lua.globals().effect == 10
    state = lua.globals().state()
    assert state.inbox[1].intent is not None and state.inbox[1].outcome is None and len(state.outbox) == 0


@pytest.mark.parametrize("failure", ["prepare", "classify", "no_effect"])
def test_callback_failure_or_success_without_effect_cannot_ack(runtime, failure):  # noqa: F811
    lua = runtime
    start_executor(lua)
    lua.globals().fail_at = failure
    ok, diagnostic = lua.globals().run()
    assert ok is False and diagnostic.retryable is True
    assert len(lua.globals().state().outbox) == 0 and lua.globals().state().inbox[1].outcome is None
    lua.globals().fail_at = None
    assert lua.globals().run()[0] is True


def test_outbox_full_after_effect_retains_prepared_command_for_readback_recovery(runtime):  # noqa: F811
    lua = runtime
    start_executor(lua)
    lua.execute("Journal.MAX_EVENTS=1")
    pending = lua.globals().append('{"event":"tick"}')
    ok, diagnostic = lua.globals().run()
    assert ok is False and diagnostic.phase == "persist_receipt"
    assert lua.globals().effect == 0 and lua.globals().applied == 1
    assert accepted(lua.globals().accept(pending, "[]"))
    assert lua.globals().run()[0] is True
    assert lua.globals().applied == 1
