"""Real Lua assembly and persist-before-drain contracts; source callbacks modeled."""

import json

import pytest
from lupa.lua54 import LuaError

from server.gen1_capture_receipt import DATA, decode_capture
from tests.unit.test_client_journal import start
from tests.unit.test_client_state_store import runtime as runtime
from tests.unit.test_gen1_capture_receipt import SAVE, receipt


def setup(lua):
    start(lua)
    source = receipt("yellow", party_count=0, box_count=0)
    source["begin"]["frame"] = 101
    source["end"]["frame"] = 102
    lua.globals().capture_json = json.dumps(source)
    lua.globals().capture_data_json = json.dumps(DATA)
    lua.execute("""
        package.loaded.gen1_capture_sites=assert(JSON.decode(capture_data_json))
        Acquisitions=require('gen1_acquisition_observers');Canonical=require('journal_document')
        frame=100;held=true;capture_pending=JSON.array();grant_pending=JSON.array();grant_open=0;drains=0;nonce=0
        context={context_generation=string.rep('a',32),physical_instance=string.rep('1',32)}
        emu={framecount=function()return frame end};gameinfo={getromhash=function()return string.rep('b',40)end}
        capture_fixture=assert(JSON.decode(capture_json))
        function detached(v)return assert(JSON.decode(assert(JSON.encode(v))))end
        capture_hooks={status=function()return {pending=#capture_pending}end,peek=function()return detached(capture_pending)end,
            acknowledge=function(expected)
                assert(Canonical.encode(expected)==Canonical.encode(capture_pending));drains=drains+1;capture_pending=JSON.array();return true
            end,close=function()end}
        grant_hooks={status=function()return {pending=#grant_pending,in_flight=grant_open}end,peek=function()return detached(grant_pending)end,
            acknowledge=function(expected)
                assert(Canonical.encode(expected)==Canonical.encode(grant_pending));drains=drains+1;grant_pending=JSON.array();return true
            end,close=function()end}
        function idle_hooks()
            return {status=function()return {pending=0,in_flight=0}end,peek=function()return JSON.array()end,
                acknowledge=function(expected)assert(#expected==0);return true end,close=function()end}
        end
        evolution_pending=JSON.array();evolution_open=0
        evolution_hooks={status=function()return {pending=#evolution_pending,in_flight=evolution_open}end,
            peek=function()return detached(evolution_pending)end,
            acknowledge=function(expected)
                assert(Canonical.encode(expected)==Canonical.encode(evolution_pending));evolution_pending=JSON.array();return true
            end,close=function()end}
        function construct()
            return Acquisitions.new({variant='yellow',final_sha1=string.rep('b',40),owned=function()return context end,
                held=function()return held end,capture=capture_hooks,grants=grant_hooks,static=idle_hooks(),npc_exchange=idle_hooks(),wild=idle_hooks(),evolution=evolution_hooks,
                new_nonce=function()nonce=nonce+1;return string.format('%032x',nonce)end})
        end
        collector=construct();state=collector:initial(frame)
        function capture_step(kind)
            assert(collector:ready(state));frame=frame+1
            local row=detached(capture_fixture[kind]);row.kind=kind=='begin'and'party_begin'or'party_end'
            row.frame=frame;capture_pending[#capture_pending+1]=row
            return collector:prepare(state)
        end
        function persist_and_drain(prepared)
            -- The real state-store commit owns durable publication. Failing it
            -- leaves the source buffers untouched for held recovery.
            assert(store:commit({source=prepared.state,receipts=prepared.receipts}))
            state=prepared.state;assert(collector:drain(prepared))
        end
    """)


def test_evolution_requires_retained_live_call_and_durable_completion_before_drain(runtime):
    lua = runtime
    setup(lua)
    lua.execute("""
        frame=101;evolution_open=1
        first=collector:prepare(state);persist_and_drain(first)
        assert(state.evolution_open==1 and collector:ready(state))
        replacement=construct()
    """)
    with pytest.raises(LuaError, match="open evolution call was lost"):
        lua.execute("replacement:ready(state)")
    lua.execute("""
        assert(collector:ready(state));frame=102;evolution_open=0
        evolution_pending=JSON.array({{outcome='evolved',before={frame=101},after={frame=102}}})
        second=collector:prepare(state)
        assert(#second.receipts==1 and second.receipts[1].kind=='evolution')
        assert(#evolution_pending==1 and second.state.evolution_open==0)
        persist_and_drain(second)
        assert(#evolution_pending==0 and collector:ready(state))
    """)


def test_capture_open_is_persisted_and_reconstruction_completes_the_same_receipt(runtime):
    lua = runtime
    setup(lua)
    lua.execute("""
        first=capture_step('begin');assert(#first.receipts==0 and first.state.capture_open.kind=='party_begin')
        assert(#capture_pending==1 and drains==0);persist_and_drain(first)
        assert(collector:ready(state));collector=construct() -- all needed capture-call data is in state
        second=capture_step('end');assert(#second.receipts==1 and second.state.capture_open==JSON.null)
        assert(#capture_pending==1);persist_and_drain(second);assert(collector:ready(state))
    """)
    wrapped = json.loads(lua.eval("JSON.encode(second.receipts[1])"))
    assert wrapped["kind"] == "capture" and wrapped["receipt"]["source_sha256"] == DATA["sha256"]
    fact = decode_capture(wrapped["receipt"]["receipt"], "yellow", SAVE)
    assert fact["call_frame"] == 101 and fact["return_frame"] == 102
    assert lua.globals().drains == 4


def test_open_grant_is_explicitly_nonresumable_after_observer_reconstruction(runtime):
    lua = runtime
    setup(lua)
    lua.execute("""
        assert(collector:ready(state));frame=101;grant_open=1
        prepared=collector:prepare(state);persist_and_drain(prepared)
        assert(state.grant_open==1 and collector:ready(state))
        replacement=construct()
    """)
    with pytest.raises(LuaError, match="open grant call was lost"):
        lua.execute("replacement:ready(state)")
    assert lua.globals().frame == 101


def test_same_live_grant_observer_survives_transport_reconnect_and_emits_paid_receipt(runtime):
    lua = runtime
    setup(lua)
    lua.execute("""
        frame=101;grant_open=1;persist_and_drain(collector:prepare(state))
        -- Transport has no authority to reconstruct or discard the source owner.
        assert(collector:ready(state));frame=102;grant_open=0
        grant_pending=JSON.array({{schema='rby-grant-receipt-v1',source_id='fixture',
            call={frame=101},['return']={frame=102},paid={frame=102}}})
        prepared=collector:prepare(state)
        assert(#prepared.receipts==1 and prepared.receipts[1].kind=='grant')
        assert(prepared.state.grant_open==0 and #grant_pending==1)
        persist_and_drain(prepared);assert(collector:ready(state))
    """)


@pytest.mark.parametrize(
    "fault",
    [
        "return-only",
        "wrong-return",
        "outside-frame",
        "overlap",
        "too-many-grants",
        "unheld",
        "context",
    ],
)
def test_ambiguous_or_unowned_sources_never_drain(runtime, fault):
    lua = runtime
    setup(lua)
    before = lua.globals().disk
    code = {
        "return-only": "frame=101;capture_fixture['end'].frame=101;capture_fixture['end'].kind='party_end';capture_pending=JSON.array({capture_fixture['end']})",
        "wrong-return": "first=capture_step('begin');persist_and_drain(first);frame=102;capture_fixture['end'].kind='box_end';capture_pending=JSON.array({capture_fixture['end']})",
        "outside-frame": "frame=101;capture_fixture['begin'].kind='party_begin';capture_fixture['begin'].frame=100;capture_pending=JSON.array({capture_fixture['begin']})",
        "overlap": "frame=101;capture_fixture['begin'].kind='party_begin';capture_pending=JSON.array({capture_fixture['begin'],capture_fixture['begin']})",
        "too-many-grants": "frame=101;for i=1,17 do grant_pending[i]={call={frame=101},['return']={frame=101}}end",
        "unheld": "frame=101;held=false",
        "context": "frame=101;context.context_generation=string.rep('c',32)",
    }[fault]
    lua.execute(code)
    previous = lua.globals().drains
    if fault == "wrong-return":
        before = lua.globals().disk
    with pytest.raises(LuaError):
        lua.execute("collector:prepare(state)")
    assert lua.globals().drains == previous and lua.globals().disk == before


def test_unpersisted_capture_prevents_another_frame_and_failed_commit_keeps_buffer(runtime):
    lua = runtime
    setup(lua)
    lua.execute("prepared=capture_step('begin')")
    with pytest.raises(LuaError):
        lua.execute("collector:ready(state)")
    lua.execute("mode='before'")
    with pytest.raises(LuaError):
        lua.execute("persist_and_drain(prepared)")
    assert lua.eval("#capture_pending") == 1 and lua.globals().drains == 0


def test_failed_or_cancelled_grant_consumes_no_receipt(runtime):
    lua = runtime
    setup(lua)
    lua.execute("""
        frame=101;grant_open=1;persist_and_drain(collector:prepare(state))
        frame=102;grant_open=0;prepared=collector:prepare(state)
        assert(#prepared.receipts==0 and prepared.state.grant_open==0)
        persist_and_drain(prepared);assert(collector:ready(state))
    """)


def frame_integration(lua, *, auxiliary):
    from tests.unit.test_gen1_frame_client import setup as frame_setup

    frame_setup(lua, auxiliary=auxiliary)
    value = receipt("yellow", party_count=0, box_count=0)
    value["begin"]["frame"] = 101
    value["begin"]["kind"] = "party_begin"
    value["end"]["frame"] = 102
    value["end"]["kind"] = "party_end"
    lua.globals().capture_json = json.dumps(value)
    lua.globals().capture_data_json = json.dumps(DATA)
    lua.execute("""
        package.loaded.gen1_capture_sites=assert(JSON.decode(capture_data_json))
        Acquisitions=require('gen1_acquisition_observers')
        local raw=assert(JSON.decode(capture_json));capture_pending=JSON.array();acquisition_drains=0
        gameinfo={getromhash=function()return string.rep('e',40)end}
        local capture={status=function()return {pending=#capture_pending}end,
            peek=function()return assert(JSON.decode(JSON.encode(capture_pending)))end,
            acknowledge=function(expected)
                assert(Canonical.encode(expected)==Canonical.encode(capture_pending));capture_pending=JSON.array();return true
            end,close=function()end}
        local grants={status=function()return {pending=0,in_flight=0}end,peek=function()return JSON.array()end,
            acknowledge=function()return true end,close=function()end}
        local function idle()
            return {status=function()return {pending=0,in_flight=0}end,peek=function()return JSON.array()end,
                acknowledge=function()return true end,close=function()end}
        end
        collector=Acquisitions.new({variant='yellow',final_sha1=string.rep('e',40),owned=function()return context end,
            held=function()return true end,capture=capture,grants=grants,static=idle(),npc_exchange=idle(),wild=idle(),evolution=idle(),new_nonce=new_id})
        function source_progress()return progress_store and progress_store:read().progress or store:read().observation.frame_progress end
        local drain=collector.drain
        collector.drain=function(self,prepared)
            local p=source_progress()
            assert(Canonical.encode(p.acquisition_source)==Canonical.encode(prepared.state),'source drained before state persistence')
            assert(#p.active.acquisitions>=#prepared.receipts,'source drained before receipt persistence')
            acquisition_drains=acquisition_drains+1;return drain(self,prepared)
        end
        frame_options.acquisitions=function()return collector end
        local physical=frame_options.step_one
        frame_options.step_one=function(scope)
            assert(physical(scope))
            capture_pending[#capture_pending+1]=frame==101 and raw.begin or raw['end']
            if fail_source_commit then if progress_store then aux_mode='before'else mode='before'end end
            return true
        end
        native_calls=0
        frame_options.native_checkpoint=function(point)
            assert(point.frame==frame);native_calls=native_calls+1
            return {schema='rby-native-observation-v1',party={fixture=true}}
        end
        client=Frame.new(frame_options)
    """)


@pytest.mark.parametrize("auxiliary", [False, True])
@pytest.mark.parametrize("sparse", [False, True])
def test_frame_client_persists_capture_assembly_before_drain_and_closes_once_on_delivery(
    runtime, auxiliary, sparse
):
    lua = runtime
    frame_integration(lua, auxiliary=auxiliary)
    lua.globals().safe = not sparse
    lua.execute("""
        grant(5);assert(tick() and frame==101)
        local p=source_progress();assert(p.phase=='active'and p.acquisition_source.capture_open~=JSON.null)
        assert(#p.active.acquisitions==0 and acquisition_drains==1)
        assert(tick() and frame==102)
        local event=assert(completion());local rows=event.payload.bundle.acquisitions
        assert(#rows==1 and rows[1].kind=='capture'and rows[1].receipt.receipt.begin.frame==101)
        assert(rows[1].receipt.receipt['end'].frame==102 and acquisition_drains==2)
        assert(source_progress().phase=='queued'and client:request(binding,{admitted=true,held=true})==nil)
        assert(event.payload.receipt.observations_digest==hash_text(Canonical.encode(event.payload.bundle)))
        assert(journal:accept_response(event.operation_id,JSON.array()))
        assert(tick() and frame==102)
    """)
    assert lua.globals().native_calls == (0 if sparse else 1)
    if sparse:
        assert lua.eval("completion()==nil")


@pytest.mark.parametrize("auxiliary", [False, True])
def test_frame_publication_failure_keeps_acquisition_callbacks_and_stops_next_frame(
    runtime, auxiliary
):
    lua = runtime
    frame_integration(lua, auxiliary=auxiliary)
    lua.execute("grant(5);fail_source_commit=true")
    result = lua.globals().tick()
    assert result[0] is False
    assert lua.globals().frame == 101 and lua.globals().acquisition_drains == 0
    assert lua.eval("#capture_pending") == 1
    assert lua.globals().tick()[0] is False and lua.globals().frame == 101


def source_native_marker(lua):
    lua.execute("""
        marker={schema='rby-client-native-frame-accounting-v1',phase='handed_back',
            context_generation=context.context_generation,sequence=9,
            baseline={phase='idle',sequence=7,frame=state.frame,acquisition_source=detached(state)}}
        frame=state.frame+4
        marker.handoff={phase='acknowledged',operation_id=string.rep('d',32),payload={event='native_frame_handoff',
            payload={schema='rby-native-frame-return-v1',ledger_sequence=9,
                host={frame=frame,owner_id=context.physical_instance,held=true},
                inventory={frame=frame,context_generation=context.context_generation,final_sha1=string.rep('b',40)}}}}
    """)


def test_source_native_adoption_is_exact_acknowledged_and_idempotent(runtime):
    lua = runtime
    setup(lua)
    source_native_marker(lua)
    with pytest.raises(LuaError):
        lua.execute("collector:ready(state)")
    lua.execute("""
        adopted=collector:adopt_native_handoff(state,marker)
        assert(state.frame==100 and adopted.frame==104 and adopted.native_handoff_operation_id==marker.handoff.operation_id)
        assert(collector:ready(adopted))
        assert(Canonical.encode(collector:adopt_native_handoff(adopted,marker))==Canonical.encode(adopted))
        assert(drains==0)
    """)


@pytest.mark.parametrize(
    "fault",
    [
        "unacknowledged",
        "context",
        "physical",
        "frame",
        "baseline",
        "capture-open",
        "grant-open",
        "capture-pending",
        "grant-pending",
    ],
)
def test_source_native_handoff_never_discards_unresolved_hooks_or_changes_scope(runtime, fault):
    lua = runtime
    setup(lua)
    if fault == "capture-open":
        lua.execute("persist_and_drain(capture_step('begin'))")
    elif fault == "grant-open":
        lua.execute("state.grant_open=1;grant_open=1")
    source_native_marker(lua)
    lua.execute(
        {
            "unacknowledged": "marker.handoff.phase='queued'",
            "context": "marker.context_generation=string.rep('f',32)",
            "physical": "marker.handoff.payload.payload.host.owner_id=string.rep('f',32)",
            "frame": "frame=frame+1",
            "baseline": "marker.baseline.acquisition_source.frame=99",
            "capture-open": "",
            "grant-open": "",
            "capture-pending": "capture_pending=JSON.array({{kind='party_begin',frame=frame}})",
            "grant-pending": "grant_pending=JSON.array({{source_id='native-period-gift'}})",
        }[fault]
    )
    before = lua.globals().drains
    with pytest.raises(LuaError):
        lua.execute("collector:adopt_native_handoff(state,marker)")
    assert lua.globals().drains == before


def frame_native_loan(lua, auxiliary):
    frame_integration(lua, auxiliary=auxiliary)
    lua.execute("""
        grant(2);assert(tick());assert(tick())
        local completed=assert(completion());assert(journal:accept_response(completed.operation_id,JSON.array()))
        assert(client:status().phase=='idle')
        Native=require('gen1_native_frame_client')
        local data=assert(store:read());local before=data.observation.frame_progress
        loan={schema=Native.SCHEMA,phase='borrowed',context_generation=context.context_generation,
            baseline=assert(JSON.decode(JSON.encode(before))),sequence=before.sequence+3}
        data.observation.native_frame_accounting=loan;assert(store:commit(data))
        frame=107;native_expected=frame
        frame_options.native_host={status=function()return {expected_frame=native_expected,
            host={owner_id=context.physical_instance,physical_stop_verified=true,failed=false,closed=false}}end}
        function complete_loan()
            local data=assert(store:read());local marker=data.observation.native_frame_accounting
            marker.phase='handed_back'
            marker.handoff={phase='acknowledged',operation_id=string.rep('9',32),payload={event='native_frame_handoff',
                payload={schema='rby-native-frame-return-v1',ledger_sequence=marker.sequence,
                    host={frame=frame,owner_id=context.physical_instance,held=true},inventory=inventory()}}}
            local previous=data.observation.frame_progress
            data.observation.frame_progress=Native.adopt(marker,previous,context,frame)
            data.observation.frame_progress.acquisition_source=collector:adopt_native_handoff(previous.acquisition_source,marker)
            assert(store:commit(data))
        end
    """)


@pytest.mark.parametrize("auxiliary", [False, True])
def test_native_borrow_freezes_ordinary_and_source_progress_until_exact_main_ack(
    runtime, auxiliary
):
    lua = runtime
    frame_native_loan(lua, auxiliary)
    lua.execute("""
        local status=client:status()
        assert(status.phase=='native_borrowed'and status.frame==102 and status.sequence==1 and client:blocks_commands())
        assert(client:request(binding,{admitted=true,held=true})==nil)
        assert(not client:authorize({}, {frame=frame}))
        assert(tick()and frame==107 and client:flush_closed_after_response())
        assert(source_progress().acquisition_source.frame==102)
        complete_loan()
        status=client:status();assert(status.phase=='idle'and status.frame==107 and status.sequence==4)
        assert(not client:blocks_commands())
        assert(source_progress().frame==107 and source_progress().acquisition_source.frame==107)
        assert(collector:ready(source_progress().acquisition_source))
        local again=client:status();assert(again.frame==107 and again.sequence==4)
    """)


@pytest.mark.parametrize(
    "fault", ["unowned-frame", "unacknowledged-jump", "unfinished-ordinary", "source-not-adopted"]
)
def test_native_marker_does_not_allow_unproved_ordinary_or_source_frame_jumps(runtime, fault):
    lua = runtime
    frame_native_loan(lua, True)
    if fault == "unowned-frame":
        lua.execute("frame=108")
    elif fault == "unacknowledged-jump":
        lua.execute(
            "local d=store:read();d.observation.native_frame_accounting.phase='handed_back';assert(store:commit(d))"
        )
    elif fault == "unfinished-ordinary":
        lua.execute(
            "local d=store:read();d.observation.frame_progress.phase='active';assert(store:commit(d))"
        )
    else:
        lua.execute("""
            complete_loan()
            local d=store:read();d.observation.frame_progress.acquisition_source=d.observation.native_frame_accounting.baseline.acquisition_source
            assert(store:commit(d))
        """)
    with pytest.raises(LuaError):
        lua.execute("client:status()")


def test_stop_after_step_runs_after_durable_source_drain_and_consumes_no_extra_frame(runtime):
    from tests.unit.test_gen1_frame_client import setup as frame_setup

    lua = runtime
    frame_setup(lua, auxiliary=True)
    lua.execute("""
        stop_calls=0
        frame_options.stop_after_step=function()
            local stored=progress_store:read().progress
            assert(stored.frame==frame and stored.active.steps==1 and drains==1)
            stop_calls=stop_calls+1;return true
        end
        client=Frame.new(frame_options)
        grant(5);assert(tick()and frame==101)
        local event=assert(completion());assert(event.payload.receipt.steps==1 and stop_calls==1)
        assert(tick()and frame==101 and stop_calls==1)
    """)
