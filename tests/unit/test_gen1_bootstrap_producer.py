"""The held client publishes one raw New Game receipt after initial enrollment is ACKed.

Hooks use the stable pre-admission scope, so they survive an unheld frame; publication
and its baseline still require a hold. A launch that never witnesses New Game (the
legacy overworld fixtures) publishes nothing and keeps its hold.
"""

import json

import pytest

from server.gen1_bootstrap_receipt import DATA
from tests.unit.test_client_journal import start
from tests.unit.test_client_state_store import runtime  # noqa: F401


def saved(lua):
    return json.loads(lua.globals().disk)["document"]["payload"]


def events(lua):
    return [row["payload"] for row in saved(lua)["outbox"]]


def bootstrap_events(lua):
    return [row for row in events(lua) if row["event"] == "bootstrap_observation"]


@pytest.fixture
def probe(runtime):  # noqa: F811
    lua = runtime
    start(lua)
    lua.globals().sites_json = json.dumps(DATA)
    lua.execute("""
        package.loaded.gen1_bootstrap_sites=assert(JSON.decode(sites_json))
        profile=JSON.decode(sites_json).titles.yellow
        rom={};bus={};hooks={};frame=100;pc=0;sp=0xDFFE;held=true
        -- Stable pre-admission scope (what the client mints before New Game) and the
        -- held owner context the initial-observation path validates.
        scope={context_generation=string.rep('a',32),physical_instance=string.rep('1',32)}
        context={context_generation=scope.context_generation}
        hash=profile.clean_sha1
        memory={read_u8=function(a,d)return (d=='ROM' and rom[a] or bus[a])or 0 end,
            isPartyWriteSafe=function()return true end}
        gameinfo={getromhash=function()return hash end}
        emu={framecount=function()return frame end,getregister=function(k)return k=='PC' and pc or sp end}
        event={on_bus_exec=function(fn,a,name)hooks[name]=fn;return name end,
            unregisterbyid=function(name)hooks[name]=nil end}
        for _,site in pairs(profile.sites)do
            for i=1,#site.expected_hex,2 do
                local v=tonumber(site.expected_hex:sub(i,i+1),16)
                rom[site.rom_offset+(i-1)/2]=v;bus[site.address+(i-1)/2]=v
            end
        end
        bootstrap=require('gen1_bootstrap_observer').new({variant='yellow',final_sha1=hash,
            owned=function()return scope end,held=function()return held end})
        function fire(kind)
            local site=profile.sites[kind];pc=site.address;bus[profile.bank_address]=site.bank
            hooks['slink-bootstrap-'..kind]()
        end
        function witness()frame=40;fire('begin');frame=90;fire('end');frame=100 end
        package.loaded.gen1_full_save={capture=function()return {fixture=true}end}
        Observe=require('gen1_initial_observation')
        journal=assert(Journal.open(store,new_id,Observe))  -- production acknowledge hook
        local baseline=journal.store:read().observation
        baseline.initial_inventory={phase='acknowledged',operation_id=string.rep('9',32),
            payload={event='initial_observation',payload={context_generation=context.context_generation,frame=frame}}}
        assert(journal:append({event='explicit-initial-ack-fixture'},baseline))
        function owned()assert(held,'held reader called inside frame');return context end
        function compose(with_bootstrap)
            composite=Observe.new({journal=journal,variant='yellow',memory=memory,owned=owned,
                source_owned=function()return context end,
                bootstrap=with_bootstrap~=false and bootstrap or nil,
                host={status=function()return {physical_stop_verified=held,owner_id='fixture',process_id=1,capability_id='fixture'}end}})
        end
        function step()return pcall(function()return composite:step(true)end)end
        function baseline_bootstrap()return journal.store:read().observation.bootstrap end
        function ack_bootstrap()
            -- The server acknowledges the durable outbox strictly FIFO.
            for _,entry in ipairs(saved_outbox())do
                local ok,why=journal:accept_response(entry.operation_id,JSON.array())
                assert(ok==true,why)
            end
            return true
        end
        function saved_outbox()return journal.store:read().outbox end
        compose()
    """)
    return lua


def test_exactly_one_raw_receipt_is_published_after_initial_ack_and_survives_replay(probe):
    lua = probe
    # Hooks fire inside an unheld frame; the stable scope keeps them alive (F2).
    lua.execute("held=false;witness();held=true")
    assert lua.globals().bootstrap.status()["failed"] is None
    assert lua.globals().bootstrap.status()["complete"] is True
    assert lua.globals().step() == (True, True)
    published = bootstrap_events(lua)
    assert len(published) == 1
    raw = json.loads(lua.eval("JSON.encode(bootstrap.peek())"))
    assert published[0]["payload"] == raw  # the receipt, byte-for-byte, no wrapper
    assert raw["schema"] == "rby-bootstrap-receipt-v1"
    assert raw["context_generation"] == "a" * 32 and raw["physical_instance"] == "1" * 32
    assert raw["begin"]["frame"] == 40 and raw["end"]["frame"] == 90
    cursor = lua.globals().baseline_bootstrap()
    assert cursor["phase"] == "queued" and json.loads(lua.eval("JSON.encode(baseline_bootstrap().payload)")) == published[0]
    for _ in range(3):
        assert lua.globals().step()[0] is True
    assert len(bootstrap_events(lua)) == 1  # replaying steps never appends a second
    # The server ACK flips the durable cursor; nothing further is published.
    assert lua.globals().ack_bootstrap()
    cursor = lua.globals().baseline_bootstrap()
    assert cursor["phase"] == "acknowledged" and len(cursor["operation_id"]) == 32
    for _ in range(3):
        assert lua.globals().step()[0] is True
    assert bootstrap_events(lua) == []  # consumed from the outbox exactly once


def test_queued_receipt_is_not_republished_after_reopen(probe):
    lua = probe
    lua.execute("held=false;witness();held=true;assert(step())")
    assert len(bootstrap_events(lua)) == 1
    lua.execute("""
        store:close();store=assert(open_store());journal=assert(Journal.open(store,new_id,Observe));compose()
    """)
    for _ in range(3):
        assert lua.globals().step()[0] is True
    assert len(bootstrap_events(lua)) == 1
    assert lua.globals().baseline_bootstrap()["phase"] == "queued"


def test_legacy_fixture_launch_without_new_game_publishes_nothing_and_keeps_the_hold(probe):
    lua = probe
    before = lua.globals().disk
    for _ in range(5):
        assert lua.globals().step()[0] is True
    assert lua.globals().disk == before
    assert bootstrap_events(lua) == []
    assert lua.globals().baseline_bootstrap() is None
    status = lua.globals().bootstrap.status()
    assert status["started"] is False and status["complete"] is False and status["failed"] is None
    assert lua.globals().held is True


def test_receipt_waits_for_the_initial_inventory_ack(probe):
    lua = probe
    lua.execute("""
        local baseline=journal.store:read().observation
        baseline.initial_inventory.phase='queued'
        assert(journal:append({event='explicit-requeue-fixture'},baseline))
        held=false;witness();held=true
    """)
    assert lua.globals().step()[0] is True
    assert bootstrap_events(lua) == []
    assert lua.globals().baseline_bootstrap() is None


def test_failed_observer_publishes_nothing_and_does_not_fail_the_client(probe):
    lua = probe
    lua.execute("held=false;witness();fire('begin');held=true")  # restart after completion
    assert "restarted" in lua.globals().bootstrap.status()["failed"]
    assert lua.globals().step()[0] is True
    assert bootstrap_events(lua) == []
    assert lua.globals().baseline_bootstrap() is None


def test_publication_requires_a_held_frame(probe):
    lua = probe
    lua.execute("held=false;witness()")
    before = lua.globals().disk
    ok, reason = lua.globals().step()
    assert ok is False and "held" in str(reason)
    assert lua.globals().disk == before and bootstrap_events(lua) == []


def test_acknowledgement_must_match_the_queued_receipt_exactly(probe):
    lua = probe
    lua.execute("held=false;witness();held=true;assert(step())")
    result = lua.execute("""
        local baseline=journal.store:read().observation
        local other=JSON.decode(JSON.encode(baseline.bootstrap.payload));other.payload.begin.frame=41
        local same=Observe.acknowledge_event(other,string.rep('7',32),baseline)
        local stray=Observe.acknowledge_event({event='bootstrap_observation',payload={}},string.rep('7',32),baseline)
        return same==nil and stray==nil and baseline.bootstrap.phase=='queued'
    """)
    assert result is True


def test_observer_is_optional_for_existing_callers(probe):
    lua = probe
    lua.execute("compose(false);held=false;witness();held=true")
    for _ in range(3):
        assert lua.globals().step()[0] is True
    assert bootstrap_events(lua) == []
    assert lua.globals().baseline_bootstrap() is None


# --- P2A-2C: resumed runs carry the CONTINUE witness inside the initial observation ---
@pytest.fixture
def resumed(runtime):  # noqa: F811
    lua = runtime
    start(lua)
    lua.execute("""
        frame=100;held=true
        scope={context_generation=string.rep('a',32),physical_instance=string.rep('1',32)}
        context={context_generation=scope.context_generation}
        memory={isPartyWriteSafe=function()return true end}
        gameinfo={getromhash=function()return string.rep('b',40)end}
        emu={framecount=function()return frame end}
        package.loaded.gen1_full_save={capture=function()return {fixture=true}end}
        Observe=require('gen1_initial_observation')
        journal=assert(Journal.open(store,new_id,Observe))
        witness={complete=false,failed=nil}
        receipt={schema='rby-continue-receipt-v1',context_generation=scope.context_generation,load={frame=1},loaded={frame=2,status=2},
            chose={frame=3},pressed={frame=4},enter={frame=5}}
        continue_observer={status=function()return witness end,peek=function()assert(held);return witness.complete and receipt or nil end,close=function()end}
        function owned()assert(held,'held reader called inside frame');return context end
        function compose(free)
            composite=Observe.new({journal=journal,variant='yellow',memory=memory,owned=owned,source_owned=function()return context end,
                continue_observer=continue_observer,free_service=free,
                host={status=function()return {physical_stop_verified=held,owner_id='fixture',process_id=1,capability_id='fixture'}end}})
        end
        function step()return pcall(function()return composite:step(true)end)end
        function ack_all()for _,entry in ipairs(journal.store:read().outbox)do assert(journal:accept_response(entry.operation_id,JSON.array()))end end
        compose(false)
    """)
    return lua


def test_resumed_initial_observation_waits_for_the_continue_witness_then_carries_it(resumed):
    lua = resumed
    assert lua.globals().step() == (True, False) and events(lua) == []   # CONTINUE not yet witnessed: nothing published
    lua.execute("witness.complete=true")
    assert lua.globals().step() == (True, True)
    published = events(lua)
    assert [row["event"] for row in published] == ["initial_observation"]
    assert published[0]["payload"]["continue_witness"] == json.loads(lua.eval("JSON.encode(receipt)"))
    assert "bootstrap" not in published[0]["payload"]
    assert lua.globals().ack_all() is None
    for _ in range(3):
        assert lua.globals().step()[0] is True
    assert bootstrap_events(lua) == []
    assert saved(lua)["observation"].get("bootstrap") is None  # the New Game receipt is never queued in resume mode


def test_resumed_free_service_enrolls_on_the_initial_ack_alone(resumed):
    lua = resumed
    lua.execute("compose(true);witness.complete=true;assert(step());ack_all()")
    assert lua.globals().step() == (True, False)
    assert lua.globals().composite.enrolled is True and saved(lua)["observation"].get("bootstrap") is None


def test_resumed_initial_observation_fails_loudly_on_a_failed_continue_witness(resumed):
    lua = resumed
    lua.execute("witness.failed='resumed save differs from the required predecessor witness'")
    ok, why = lua.globals().step()
    assert ok is False and "resumed save differs" in str(why) and events(lua) == []
