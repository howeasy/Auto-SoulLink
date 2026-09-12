"""Actual shared Lua executor/journal with synthetic independently observed native state."""
import pytest

from tests.unit.test_client_state_store import runtime  # noqa: F401
from tests.unit.test_command_executor import start_executor


def native_executor(lua):
    start_executor(lua)
    lua.execute("""
        native_state='idle';native_context='current';prepare_calls=0;frames_advanced=0
        adapter.prepare=function(body,metadata)
            prepare_calls=prepare_calls+1
            return {schema='native-fixture-intent-v1',before=20,after=0,
                command_id=metadata.command_id,command_sequence=metadata.command_sequence,
                native_id=metadata.command_id:sub(17),context='current'}
        end
        adapter.classify=function(body,intent,metadata)
            assert(metadata.command_id==intent.command_id)
            assert(metadata.command_sequence==intent.command_sequence)
            if native_context~=intent.context then return 'diverged','native context changed' end
            if native_state=='busy' then
                return 'armed',{schema='native-fixture-armed-v1',command_id=metadata.command_id,
                    native_id=intent.native_id,context=native_context}
            end
            if native_state=='done' and effect==0 then return 'after',{hp=0} end
            if native_state=='idle' and effect==20 then return 'before',{hp=20} end
            return 'diverged','native ownership or effect is uncertain'
        end
        adapter.apply=function(body,intent,metadata)
            assert(metadata.command_id==intent.command_id)
            applied=applied+1;native_state='busy'
            if fail_at=='after_arm' then error('exception after native opcode publication') end
        end
    """)


def test_armed_operation_survives_reopen_without_reapply_receipt_or_frame_permission(runtime):  # noqa: F811
    lua = runtime
    native_executor(lua)
    ok, pending = lua.globals().run()
    assert ok is False and pending.outcome == "PENDING" and pending.pending is True
    assert pending.phase == "armed" and pending.native_execution_permitted is False
    assert lua.globals().applied == 1 and lua.globals().frames_advanced == 0
    state = lua.globals().state()
    assert len(state.outbox) == 0 and state.inbox[1].outcome is None
    assert state.inbox[1].intent.command_id == lua.globals().command_id
    lua.globals().restart_executor()
    for _ in range(20):
        ok, pending = lua.globals().run()
        assert ok is False and pending.outcome == "PENDING"
    assert lua.globals().applied == 1 and lua.globals().prepare_calls == 1
    assert len(lua.globals().state().outbox) == 0
    # Only an independently observed finished native effect allows the ACK.
    lua.globals().native_state = "done"
    lua.globals().effect = 0
    ok, result = lua.globals().run()
    assert ok is True and result.outcome == "ACK"
    assert len(lua.globals().state().outbox) == 1
    assert lua.globals().run()[1].replayed is True
    assert lua.globals().applied == 1


def test_exception_after_arming_recovers_as_pending_instead_of_applying_again(runtime):  # noqa: F811
    lua = runtime
    native_executor(lua)
    lua.globals().fail_at = "after_arm"
    ok, failed = lua.globals().run()
    assert ok is False and failed.outcome == "NACK" and failed.phase == "apply"
    lua.globals().fail_at = None
    lua.globals().restart_executor()
    ok, pending = lua.globals().run()
    assert ok is False and pending.outcome == "PENDING"
    assert lua.globals().applied == 1


@pytest.mark.parametrize("changed", ["native_context", "native_state"])
def test_restart_or_context_uncertainty_does_not_claim_armed_or_reapply(runtime, changed):  # noqa: F811
    lua = runtime
    native_executor(lua)
    lua.globals().run()
    setattr(lua.globals(), changed, "unknown")
    lua.globals().restart_executor()
    ok, diagnostic = lua.globals().run()
    assert ok is False and diagnostic.outcome == "NACK"
    assert lua.globals().applied == 1
    state = lua.globals().state()
    assert state.inbox[1].intent is not None and state.inbox[1].outcome is None
    assert len(state.outbox) == 0


@pytest.mark.parametrize("evidence", ["nil", "false", "'busy'", "{}", "{schema='armed-v1'}",
                                       "{schema='armed-v1',command_id=string.rep('f',32)}",
                                       "{schema='',command_id=command_id}"])
def test_unbound_or_malformed_armed_claim_is_uncertain_without_completion(runtime, evidence):  # noqa: F811
    lua = runtime
    native_executor(lua)
    lua.execute("adapter.classify=function() return 'armed'," + evidence + " end")
    ok, diagnostic = lua.globals().run()
    assert ok is False and diagnostic.outcome == "NACK"
    assert lua.globals().applied == 0
    assert len(lua.globals().state().outbox) == 0


@pytest.mark.parametrize("field,value", [("command_id", "'bad'"), ("command_id", "string.rep('f',32)"),
                                         ("command_sequence", "true"), ("command_sequence", "0"),
                                         ("command_sequence", "1.5"), ("command_sequence", "9007199254740992")])
def test_malformed_inbox_metadata_is_rejected_before_adapter_or_effect(runtime, field, value):  # noqa: F811
    lua = runtime
    native_executor(lua)
    lua.execute("""
        real_get=journal.get_command
        journal.get_command=function(self,id)
            local entry=real_get(self,id)
    """ + f"entry.{field}={value};return entry end")
    ok, diagnostic = lua.globals().run()
    assert ok is False and diagnostic.phase == "read"
    assert lua.globals().prepare_calls == 0 and lua.globals().applied == 0
    assert len(lua.globals().state().outbox) == 0


def test_inbox_identity_is_rechecked_after_preparation_publication(runtime):  # noqa: F811
    lua = runtime
    native_executor(lua)
    lua.execute("""
        real_get=journal.get_command;gets=0
        journal.get_command=function(self,id)
            gets=gets+1;local entry=real_get(self,id)
            if gets==2 then entry.command_sequence=entry.command_sequence+1 end
            return entry
        end
    """)
    ok, diagnostic = lua.globals().run()
    assert ok is False and diagnostic.phase == "persist_intent"
    assert "sequence changed" in diagnostic.reason
    assert lua.globals().applied == 0


def test_each_callback_receives_detached_trusted_command_metadata(runtime):  # noqa: F811
    lua = runtime
    start_executor(lua)
    lua.execute("""
        seen={}
        local function check(name,metadata)
            assert(metadata.command_id==command_id and metadata.command_sequence==1)
            seen[name]=true;metadata.command_id='mutated adapter copy'
        end
        for _,name in ipairs({'prepare','classify','apply','receipt'}) do
            local original=adapter[name]
            if name=='prepare' then
                adapter[name]=function(body,metadata) check(name,metadata);return original(body) end
            elseif name=='receipt' then
                adapter[name]=function(body,intent,observation,metadata)
                    check(name,metadata);return original(body,intent,observation)
                end
            else
                adapter[name]=function(body,intent,metadata) check(name,metadata);return original(body,intent) end
            end
        end
    """)
    assert lua.globals().run()[0] is True
    assert set(lua.globals().seen) == {"prepare", "classify", "apply", "receipt"}
    assert lua.globals().state().inbox[1].command_id == lua.globals().command_id
