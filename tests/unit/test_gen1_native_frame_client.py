"""Real shared journal ACK projection; host and cartridge snapshots are modeled."""

import json

import pytest
from lupa.lua54 import LuaError

from tests.unit.test_gen1_memorial import fixture
from tests.unit.test_gen1_native_runtime_injection import lua  # noqa: F401


@pytest.fixture
def client(lua):  # noqa: F811
    point, _, _ = fixture("yellow", count=2)
    lua.globals().point_json = json.dumps(point)
    lua.execute("""
        FrameNative=require('gen1_native_frame_client')
        package.loaded.gen1_full_save={capture=function()return JSON.decode(point_json)end}
        package.loaded.gen1_write_checkpoint={capture=function()return {fixture='held checkpoint'}end}
        package.loaded.gen1_trade_preparation={capture=function()return {fixture='native checkpoint'}end}
        host_state.host.failed=false;host_state.host.closed=false
        local data=shared_store:read()
        data.observation.frame_progress={schema='rby-client-frame-progress-v1',phase='idle',sequence=4,frame=100,
            inventory_frame=100,context_generation=context.context_generation,last_operation_id=string.rep('b',32)}
        assert(shared_store:commit(data))
        owner={}
        journal=assert(Journal.open(shared_store,nil,Service.journal_options({},function()return owner end)))
        publications=0
        collector=FrameNative.new({journal=journal,host=shared_host,memory=mem,manifest=manifest,
            owned=function()return context end,observe=function(events,baseline)
                publications=publications+1;return journal:append_many(events,baseline)
            end})
        owner.frame_accounting=collector
        function state()return shared_store:read().observation.native_frame_accounting end
        function accept(challenge)
            collector:accepted_grant({schema='slink-operation-execution-window-v1',challenge=challenge,
                scope={operation_id=id},frames=60,ttl_ms=1000,proof_digest=string.rep('f',64)},1)
        end
        function acknowledge()
            local event=journal:pending_events()[1]
            assert(event);assert(journal:accept_response(event.operation_id,JSON.array()))
            return event.operation_id
        end
        function completed_command()
            command('native_receptionist');accept(string.rep('f',32))
            steps=20;host_state.steps=20;host_state.expected_frame=120
            assert(journal:complete_command(id,'ACK',{schema='rby-receptionist-return-v1'}))
            acknowledge()
        end
        function ready()
            local request=assert(collector:request());local packet=request.evidence;packet.ready=true
            assert(collector:accept(packet))
        end
    """)
    return lua


def test_typed_ack_captures_return_then_outer_observe_publishes_and_handoff_adopts_exact_counts(
    client,
):
    client.execute("completed_command()")
    g = client.globals()
    assert g.state()["returning"]["phase"] == "captured"
    assert g.publications == 0
    assert client.eval("#journal:pending_events()") == 0
    assert g.state()["returning"]["payload"]["payload"]["accounting"]["host"]["frame"] == 100
    client.execute("collector:pump()")
    assert g.publications == 1 and g.state()["returning"]["phase"] == "queued"
    client.execute("acknowledge();ready();collector:pump()")
    assert g.publications == 2 and g.state()["handoff"]["phase"] == "queued"
    assert client.eval("FrameNative.borrowed(shared_store:read().observation)")
    client.execute("acknowledge()")
    assert not client.eval("FrameNative.borrowed(shared_store:read().observation)")
    assert client.eval("shared_store:read().observation.frame_progress.frame") == 120
    assert client.eval("shared_store:read().observation.frame_progress.inventory_frame") == 120
    assert client.eval("shared_store:read().observation.frame_progress.sequence") == 5


def test_response_boundary_records_old_credit_frames_before_switching_to_new_window(client):
    client.execute("""
        command('native_receptionist');accept(string.rep('f',32))
        steps=30;host_state.steps=30;host_state.expected_frame=130
        accept(string.rep('a',32))
    """)
    state = client.globals().state()
    assert state["sequence"] == 6
    assert state["acceptance"]["host"]["frame"] == 130
    assert state["acceptance"]["host"]["steps"] == 30


def test_unowned_frame_advance_is_not_hidden_by_borrowed_ordinary_progress(client):
    client.execute("command('native_receptionist');accept(string.rep('f',32))")
    assert client.execute(
        "return FrameNative.validate_marker(shared_store:read().observation,context,host_state,100)"
    )
    with pytest.raises(LuaError, match="physical boundary"):
        client.execute(
            "FrameNative.validate_marker(shared_store:read().observation,context,host_state,101)"
        )


@pytest.mark.parametrize("fault", ["frame", "source"])
def test_terminal_source_cannot_change_before_return_publication(client, fault):
    client.execute("completed_command()")
    if fault == "frame":
        client.execute("steps=21;host_state.steps=21;host_state.expected_frame=121")
    else:
        client.execute(
            "local p=JSON.decode(point_json);p.cart_hex='00'..p.cart_hex:sub(3);point_json=JSON.encode(p)"
        )
    with pytest.raises(LuaError, match="changed before"):
        client.execute("collector:pump()")
    assert client.globals().publications == 0


@pytest.mark.parametrize("fault", ["not_acknowledged", "active", "sequence", "context"])
def test_unacknowledged_or_foreign_marker_cannot_adopt_an_ordinary_ledger(client, fault):
    client.execute(
        "completed_command();collector:pump();acknowledge();ready();collector:pump();acknowledge()"
    )
    client.execute("marker=state();progress=JSON.decode(JSON.encode(marker.baseline))")
    if fault == "not_acknowledged":
        client.execute("marker.handoff.phase='queued'")
    elif fault == "active":
        client.execute("progress.phase='active'")
    elif fault == "sequence":
        client.execute("marker.sequence=marker.sequence+1")
    else:
        client.execute("context.context_generation=string.rep('a',32)")
    with pytest.raises(LuaError):
        client.execute("FrameNative.adopt(marker,progress,context,120)")


def test_applied_handoff_marker_is_idempotent(client):
    client.execute(
        "completed_command();collector:pump();acknowledge();ready();collector:pump();acknowledge()"
    )
    assert client.execute("""
        local progress=shared_store:read().observation.frame_progress
        return Canonical.encode(FrameNative.adopt(state(),progress,context,120))==Canonical.encode(progress)
    """)
