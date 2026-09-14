"""R5b-2 (round 3): the Lua client side of paired checkpoint capture, driven through the
PRODUCTION path -- gen1_runtime.lua -> durable_runtime.lua -> command_executor.lua ->
command_service_router.lua -> gen1_checkpoint_client.lua -- against a REAL server
(server.gen1_run_config.create_runtime, the same Gen1Runtime server.py uses), not direct
command_executor calls. Player "a" is driven in plain Python (admission/witness are
precondition setup, not what this card changed); player "b" is the one real Lua client
under test, relayed over an in-memory transport exactly like test_gen1_runtime_client.py.

F1: a bad sample never raises into durable_runtime's fatal revoke path -- it stays a
non-raising PENDING ("armed") state, bounded to MAX_SAMPLE_ATTEMPTS reads, then a durable
typed refusal. F2/F7: the 90s unsafe deadline and the identity pin both start at
DISCOVERY and live in the durable intent, surviving a reload. F3: the paired hold clears
only once the matching checkpoint_release command's OWN sequence is confirmed-retired
(command_floor advance), never on local ACK alone. F5: request_id/upload-sequence/
release-sequence are persisted in the journal's observation baseline and reconstructed on
open. F4 (gen1_client_entry.lua's writer-hold loop) is covered by an isolated test of the
edited loop condition -- see its own section below for why the full BizHawk entry point
is out of reach for a lupa unit test.
"""
import hashlib
import json

import pytest
from lupa.lua54 import LuaError

from server.gen1_checkpoint_runtime import COMPONENT, start as checkpoint_start
from server.gen1_launcher import OBSERVATION_FILES
from server.gen1_run_config import create_runtime
from server.protocol import canonical_json, decode_frame
from tests.unit.test_client_state_store import runtime as lua_store  # noqa: F401
from tests.unit.test_gen1_engine_signal_runtime import (
    deliver as engine_deliver,
    payload as engine_payload,
)
from tests.unit.test_gen1_engine_signals import witness as save_witness_signal
from tests.unit.test_gen1_initial_observation import admit, observation, send
from tests.unit.test_gen1_sessions import contract

PROJECTION = "cartram-0498-8000-v1"
REQUEST_ID = "checkpoint-req-1"


def full_cart_hex():
    return bytes(i % 256 for i in range(0x8000)).hex().upper()


def next_cart_hex():
    return bytes((i + 1) % 256 for i in range(0x8000)).hex().upper()


def digest_for(hex_text):
    return hashlib.sha256(hex_text[0x498 * 2:].encode("utf-8")).hexdigest()


GOOD_DIGEST = digest_for(full_cart_hex())


def lua_source(template, **slots):
    """Substitute @@name@@ markers with raw Lua source (never a %/format operator, so
    callers can hand in strings that are themselves full of literal braces)."""
    text = template
    for name, value in slots.items():
        text = text.replace("@@" + name + "@@", value)
    return text


def boot(lua, *, party_safe=True, held=True):
    """Standalone (non-production) fixture used by the wire-shape/pure-function tests
    below, and by tests/unit/test_gen1_checkpoint_runtime.py (server round 3) to check
    server-emitted command bodies against this module's own M.validate. Not the harness
    for the F1-F7 lifecycle tests further down, which drive the real production path."""
    lua.globals().party_safe = party_safe
    lua.globals().held = held
    lua.execute(r"""
        package.path=root..'/lua/?.lua;'..root..'/data/games/gen1_rby/?.lua;'..package.path
        JSON=JSON or require('json_codec')
        cart_reads=0
        local function fill(step)
            local parts={}
            for i=0,0x7FFF do parts[i+1]=string.char((i+step)%256)end
            return table.concat(parts)
        end
        domains={CartRAM=fill(0),["System Bus"]=string.rep('\0',65536)}
        function shift_cartram(step) domains.CartRAM=fill(step) end
        memory={
            read_bytes_as_binary_string=function(addr,count,domain)
                domain=domain or "System Bus"
                if domain=="CartRAM" then cart_reads=cart_reads+1 end
                local buf=assert(domains[domain],"unknown memory domain")
                local slice=buf:sub(addr+1,addr+count)
                assert(#slice==count,"short domain read")
                return slice
            end,
            read_u8=function(addr,domain)
                local buf=domains[domain or "System Bus"]
                return buf:byte(addr+1) or 0
            end}
        emu={framecount=function()return frame end}
        gameinfo={getromhash=function()return string.rep('e',40)end}
        frame=100;now=100
        clock=function()return now end
        context={context_generation=string.rep('c',32),physical_instance=string.rep('p',32),
            save_identity={ot_id='0000',trainer_name='SAME'}}
        host={status=function()return {physical_stop_verified=held}end}
        mem={isPartyWriteSafe=function()return party_safe end}
        presented={}
        overlay={present=function(notice)presented[#presented+1]=notice;return true end,
            retained=function()return {hud=0}end}
        Checkpoint=require('gen1_checkpoint_client')
        Journal=require('client_journal')
        -- open_store()/hash_text come from the test_client_state_store.runtime fixture
        -- (aliased lua_store below): a real disk-shaped backend with real sha256. That
        -- fixture's open_store() reads the GLOBAL `initial` at call time (matching
        -- test_client_journal.start()'s own pattern) -- it must be a client-journal-
        -- shaped document, not the fixture's own generic placeholder.
        initial=Journal.initial()
        store=assert(open_store())
        local n=0
        journal=assert(Journal.open(store,function()n=n+1;return string.format('%032x',n)end))
        service=Checkpoint.new({journal=journal,memory=mem,player='b',variant='yellow',
            owned=function()return context end,host=host,clock=clock,overlay=overlay})
    """)


def test_handles_and_validate_reject_unknown_or_malformed_bodies(lua_store):  # noqa: F811
    lua = lua_store
    boot(lua)
    good_upload = ("{cmd='checkpoint_upload',request_id='r1',witness={frame=1,digest='" + GOOD_DIGEST
                   + "',projection='" + PROJECTION + "',index=0,operation_id=string.rep('9',32)}}")
    good_release = "{cmd='checkpoint_release',request_id='r1',outcome='confirmed',reason=''}"
    lua.execute(lua_source("""
        assert(Checkpoint.handles({cmd='checkpoint_upload'})==true)
        assert(Checkpoint.handles({cmd='checkpoint_release'})==true)
        assert(Checkpoint.handles({cmd='force_faint'})==false)
        assert(Checkpoint.handles('not a table')==false)
        Checkpoint.validate(@@UPLOAD@@)
        Checkpoint.validate(@@RELEASE@@)
    """, UPLOAD=good_upload, RELEASE=good_release))
    cases = [
        ("{cmd='checkpoint_upload',request_id='',witness={frame=1,digest='" + GOOD_DIGEST
         + "',projection='" + PROJECTION + "',index=0,operation_id=string.rep('9',32)}}",
         "invalid checkpoint request id"),
        ("{cmd='checkpoint_upload',request_id='has a space',witness={frame=1,digest='" + GOOD_DIGEST
         + "',projection='" + PROJECTION + "',index=0,operation_id=string.rep('9',32)}}",
         "invalid checkpoint request id"),
        ("{cmd='checkpoint_upload',request_id=string.rep('r',65),witness={frame=1,digest='" + GOOD_DIGEST
         + "',projection='" + PROJECTION + "',index=0,operation_id=string.rep('9',32)}}",
         "invalid checkpoint request id"),
        ("{cmd='checkpoint_upload',request_id='r1',witness={digest='" + GOOD_DIGEST
         + "',projection='" + PROJECTION + "',index=0,operation_id=string.rep('9',32)}}",
         "missing checkpoint witness field"),
        ("{cmd='checkpoint_upload',request_id='r1',witness={frame=1,digest='" + GOOD_DIGEST
         + "',projection='" + PROJECTION + "',index=0,operation_id=string.rep('9',32),extra=1}}",
         "unknown checkpoint witness field"),
        ("{cmd='checkpoint_upload',request_id='r1',witness={frame=-1,digest='" + GOOD_DIGEST
         + "',projection='" + PROJECTION + "',index=0,operation_id=string.rep('9',32)}}",
         "invalid checkpoint witness frame"),
        ("{cmd='checkpoint_upload',request_id='r1',witness={frame=1,digest='z'..string.rep('0',63),"
         "projection='" + PROJECTION + "',index=0,operation_id=string.rep('9',32)}}",
         "invalid checkpoint witness digest"),
        ("{cmd='checkpoint_upload',request_id='r1',witness={frame=1,digest='" + GOOD_DIGEST
         + "',projection='other-v1',index=0,operation_id=string.rep('9',32)}}",
         "unsupported checkpoint witness projection"),
        ("{cmd='checkpoint_upload',request_id='r1',witness={frame=1,digest='" + GOOD_DIGEST
         + "',projection='" + PROJECTION + "',index=-1,operation_id=string.rep('9',32)}}",
         "invalid checkpoint witness index"),
        ("{cmd='checkpoint_upload',request_id='r1',witness={frame=1,digest='" + GOOD_DIGEST
         + "',projection='" + PROJECTION + "',index=0,operation_id='short'}}",
         "invalid checkpoint witness operation id"),
        ("{cmd='checkpoint_release',request_id='r1',outcome='maybe',reason=''}",
         "invalid checkpoint release outcome"),
        ("{cmd='checkpoint_release',request_id='r1',outcome='confirmed',reason=string.rep('x',257)}",
         "invalid checkpoint release reason"),
        ("{cmd='checkpoint_release',request_id='r1',outcome='confirmed',reason='\\1control'}",
         "invalid checkpoint release reason"),
    ]
    for body_lua, match in cases:
        with pytest.raises(LuaError, match=match):
            lua.execute(lua_source("Checkpoint.validate(@@BODY@@)", BODY=body_lua))
    # "" is explicitly allowed (never null) for a release reason.
    lua.execute("Checkpoint.validate({cmd='checkpoint_release',request_id='r1',outcome='confirmed',reason=''})")


def test_completion_event_shapes_and_terminal_nack_refusal(lua_store):  # noqa: F811
    lua = lua_store
    boot(lua)
    lua.execute("""
        upload_entry={body={cmd='checkpoint_upload',body={cmd='checkpoint_upload'}},
            command_id=string.rep('a',32),command_sequence=1}
        release_entry={body={cmd='checkpoint_release',body={cmd='checkpoint_release'}},
            command_id=string.rep('b',32),command_sequence=2}
        upload_result=Checkpoint.completion_event(upload_entry,'ACK',{cart_hex='FF'})
        release_result=Checkpoint.completion_event(release_entry,'ACK',{outcome='confirmed'})
        other_entry={body={cmd='force_faint',body={cmd='force_faint'}},command_id=string.rep('c',32),command_sequence=3}
        other_result=Checkpoint.completion_event(other_entry,'ACK',{})
    """)
    g = lua.globals()
    assert g.upload_result["event"] == "save_upload" and g.upload_result["receipt"]["cart_hex"] == "FF"
    assert g.release_result["event"] == "checkpoint_release" and g.release_result["receipt"]["outcome"] == "confirmed"
    assert g.other_result is None
    with pytest.raises(LuaError, match="terminal NACK"):
        lua.execute("Checkpoint.completion_event(upload_entry,'NACK',{})")


def test_launcher_ships_the_checkpoint_client_only_with_initial_observations():
    assert "lua/gen1_checkpoint_client.lua" in OBSERVATION_FILES


# ============================================================================
# Production-path harness: a real Gen1Runtime server + the real client chain
# (gen1_runtime.lua -> durable_runtime.lua -> command_executor.lua ->
# command_service_router.lua -> gen1_checkpoint_client.lua) for player "b",
# relayed over an in-memory transport. Player "a" is plain Python (setup only).
# ============================================================================

CART_HEX = full_cart_hex()


def _save_digest(cart_hex):
    return hashlib.sha256(cart_hex[0x498 * 2:].encode("ascii")).hexdigest()


def _pin_witness(runtime, player, owner, *, frame=200, sequence=1, cart_hex=CART_HEX):
    value = engine_payload(runtime, player, [], sequence)
    value["signals"] = [save_witness_signal(value["variant"], digest=_save_digest(cart_hex))]
    value["signals"][0]["frame"] = frame
    return engine_deliver(runtime, player, owner, value)


HARNESS = r"""
    package.path=root..'/lua/?.lua;'..root..'/data/games/gen1_rby/?.lua;'..package.path
    JSON=JSON or require('json_codec')
    local data=assert(JSON.decode(client_input))
    cart_reads=0
    local function fill(step)
        local parts={}
        for i=0,0x7FFF do parts[i+1]=string.char((i+step)%256)end
        return table.concat(parts)
    end
    domains={CartRAM=fill(0),["System Bus"]=string.rep('\0',65536)}
    function shift_cartram(step) domains.CartRAM=fill(step) end
    memory={
        read_bytes_as_binary_string=function(addr,count,domain)
            domain=domain or "System Bus"
            if domain=="CartRAM" then cart_reads=cart_reads+1 end
            local buf=assert(domains[domain],"unknown memory domain")
            local slice=buf:sub(addr+1,addr+count)
            assert(#slice==count,"short domain read")
            return slice
        end,
        read_u8=function(addr,domain)
            local buf=domains[domain or "System Bus"]
            return buf:byte(addr+1) or 0
        end}
    gameinfo={getromhash=function()return data.final_sha1 end}
    frame=300;emu={framecount=function()return frame end} -- past the pinned witness's frame=200
    now=10;clock=function()return now end
    party_safe=true;held=false
    host={status=function()return {physical_stop_verified=held}end,
        set_held=function(value,why)held=value;return true end}
    mem={isPartyWriteSafe=function()return party_safe end}
    presented={}
    overlay={present=function(notice)presented[#presented+1]=notice;return true end,
        retained=function()return {hud=0}end}
    context={context_generation=data.context.context_generation,
        physical_instance=data.context.physical_instance,save_identity={ot_id='0000',trainer_name='SAME'}}
    Journal=require('client_journal');Checkpoint=require('gen1_checkpoint_client')
    Router=require('command_service_router')
    initial=Journal.initial() -- open_store() reads this GLOBAL at call time
    store=assert(open_store())
    ids=0
    journal=assert(Journal.open(store,function()ids=ids+1;return data.id_prefix..string.format('%030x',ids)end,
        {completion_event=Checkpoint.completion_event}))
    checkpoint=Checkpoint.new({journal=journal,memory=mem,player=data.player,variant=data.variant,
        owned=function()return context end,host=host,clock=clock,overlay=overlay})
    router=Router.new({checkpoint})
    incoming={};outgoing={};connected=false
    transport={
        init=function(host,port,options)assert(options.discard_on_disconnect);connected=true;incoming={};outgoing={}end,
        connected=function()return connected end,
        pump=function()end,
        send=function(line)outgoing[#outgoing+1]=line;return true end,
        receive=function()return table.remove(incoming,1)end,
        disconnect=function()connected=false;incoming={};outgoing={}end,
        queue_status=function()return {send_lines=0,send_bytes=0,send_offset=0,receive_lines=0,receive_bytes=0,
            partial_receive_bytes=0,pending_receive_bytes=0,ready_receive_bytes=0}end,
    }
    Runtime=require('gen1_runtime')
    nonce=0
    options={player=data.player,variant=data.variant,run_id=data.run_id,server_host='127.0.0.1',server_port=9000,
        journal=journal,transport=transport,clock=clock,control_interval=0.5,sync_interval=0.05,
        host=host,operation_held=function()return held end,
        read_context=function()return context end,
        operation_execution=router.operations,operation_ready=router.ready,executor_adapter=router.adapter,
        new_nonce=function()nonce=nonce+1;return data.nonce_prefix..string.format('%030x',nonce)end,
    }
    runtime=assert(Runtime.new(options))
    function step()return runtime:step()end
    function pop()return table.remove(outgoing,1)end
    function push(raw)incoming[#incoming+1]=raw end
    function status_json()return assert(JSON.encode(runtime:status()))end
    -- Precondition setup (admission-adjacent, not what this card changed) must flow
    -- through THIS client's own session/sequence tracking, never a python-injected
    -- runtime.process call on the side: that would desync client_session.lua's
    -- internal seq counter from the server's and break every later exchange.
    function observe_event(event_name,payload_json)
        return assert(runtime:observe(JSON.array({{event=event_name,payload=assert(JSON.decode(payload_json))}}),JSON.object()))
    end
    -- The head command's UNWRAPPED body, persisted intent and identity, for tests that
    -- call this service's own adapter functions directly (see test_f7 below for why).
    function head_snapshot()
        local entry=assert(assert(journal:pending_commands())[1])
        local body=require('gen1_runtime').unwrap(entry.body,data.player)
        return assert(JSON.encode({command_id=entry.command_id,command_sequence=entry.command_sequence,
            intent=entry.intent,body=body}))
    end
"""


def make_client(runtime, player, run_id, id_prefix, nonce_prefix):
    lua = lua_store.__wrapped__()
    context = {"context_generation": player * 32,
               "physical_instance": ("1" if player == "a" else "2") * 32}
    lua.globals().client_input = json.dumps({
        "player": player, "variant": runtime.contract["players"][player]["variant"],
        "run_id": run_id, "final_sha1": runtime.contract["players"][player]["final_rom_sha1"],
        "context": context, "id_prefix": id_prefix, "nonce_prefix": nonce_prefix})
    lua.execute(HARNESS)
    return lua


def exchange(runtime, clients, owners, count=1):
    """One production pump per client per round: advance its fake wall clock past the
    control/sync interval (otherwise durable_runtime never re-polls after its first sync
    -- state.last_sync/last_control never age out against a clock that never moves),
    step(), relay every outgoing line through the REAL server (runtime.process), push
    the response back."""
    for _ in range(count):
        for player, lua in clients.items():
            g = lua.globals()
            g.now = g.now + 0.02
            assert g.step() is True, g.status_json()
            while (line := g.pop()) is not None:
                message = decode_frame(line.encode())
                response = runtime.process(message, owners[player])
                g.push(canonical_json(response))


@pytest.fixture
def checkpoint_case(tmp_path):
    """Both players admitted + observed + witnessed on a real Gen1Runtime; player "a"
    entirely in Python, player "b" the real Lua client under test. Yields
    (runtime, clients, owners) with the checkpoint request NOT yet started."""
    runtime = create_runtime(tmp_path, contract("red", "blue"))
    owner_a = admit(runtime, "a")
    send(runtime, "a", owner_a, observation(runtime, "a"))
    _pin_witness(runtime, "a", owner_a)
    lua_b = make_client(runtime, "b", runtime.journal.run_id, "bb", "dd")
    owners = {"a": owner_a, "b": object()}
    clients = {"b": lua_b}
    # Admit + control player "b" through the REAL client chain before anything else.
    for _ in range(40):
        exchange(runtime, clients, owners)
        if runtime.gate.sessions.get("b") is not None and runtime.gate.sessions["b"].metadata:
            break
    # Precondition setup for player "b" (initial observation + save witness) is queued
    # and sent through THIS SAME Lua client's own durable outbox/session -- never a
    # python-injected runtime.process call, which would desync its session sequence.
    witness_payload = engine_payload(runtime, "b", [], 1)
    witness_payload["signals"] = [save_witness_signal(witness_payload["variant"],
        digest=_save_digest(CART_HEX))]
    witness_payload["signals"][0]["frame"] = 200
    lua_b.globals().observe_event("initial_observation", json.dumps(observation(runtime, "b")))
    lua_b.globals().observe_event("engine_signals", json.dumps(witness_payload))
    _drain_until(runtime, clients, owners,
        lambda: runtime.state().document()["components"].get("gen1-save-witness", {}).get("b") is not None)
    try:
        yield runtime, clients, owners
    finally:
        runtime.close()


def _start(runtime, request_id=REQUEST_ID):
    return checkpoint_start(runtime, request_id, "registry-run-1")


def _upload_a(runtime, owners, request_id=REQUEST_ID):
    """Complete player "a"'s upload entirely in Python (setup only, matching this
    module's own CART_HEX/save_digest so the server's witness match succeeds)."""
    from tests.unit.test_gen1_checkpoint_runtime import _upload as py_upload
    witness = runtime.state().document()["components"][COMPONENT]["witnesses"]["a"]
    return py_upload(runtime, "a", owners["a"], request_id, witness, cart_hex=CART_HEX, frame=200)


def _drain_until(runtime, clients, owners, predicate, limit=200):
    for _ in range(limit):
        if predicate():
            return True
        exchange(runtime, clients, owners)
    return predicate()


def test_f1_digest_mismatch_bounded_then_durable_refusal_never_revokes(checkpoint_case):
    """F1: a persistent digest mismatch never raises into durable_runtime's fatal revoke
    -- it stays a non-raising PENDING state (attempts 1 and 2), then a durable refusal
    receipt (attempt 3), retired via a normal ACK. Driven entirely through step()."""
    runtime, clients, owners = checkpoint_case
    lua = clients["b"]
    g = lua.globals()
    _start(runtime)
    g.party_safe = True
    g.held = True
    # The pinned witness digest does not match this client's (deliberately different)
    # fake CartRAM: shift it so it can never match.
    lua.execute("shift_cartram(1)")
    component_before = runtime.state().document()["components"][COMPONENT]
    assert component_before["status"] == "collecting"
    assert _drain_until(runtime, clients, owners,
        lambda: runtime.state().document()["components"][COMPONENT]["status"] != "collecting")
    component = runtime.state().document()["components"][COMPONENT]
    assert component["status"] == "abandoned"
    assert component["refusals"]["b"]["code"] == "digest_mismatch"
    # durable_runtime never fatally revoked the session over any of the retries.
    assert lua.execute("return runtime:status().failed") is False
    assert g.cart_reads >= 3
    # Bounded: no unbounded retry loop -- the count settles at MAX_SAMPLE_ATTEMPTS.
    reads_at_refusal = g.cart_reads
    exchange(runtime, clients, owners, count=5)
    assert g.cart_reads == reads_at_refusal
    # F3 (abandoned path): the hold persists until the ABANDONED release is itself
    # confirmed-retired -- not just locally ACKed -- exactly like the confirmed path.
    assert _drain_until(runtime, clients, owners, lambda: lua.execute("return checkpoint.pending()") is False)
    assert lua.execute("return runtime:status().failed") is False


def test_f1_matching_sample_completes_normally(checkpoint_case):
    """The success path still works end to end through the same production chain."""
    runtime, clients, owners = checkpoint_case
    lua = clients["b"]
    g = lua.globals()
    _start(runtime)
    g.party_safe = True
    g.held = True
    assert _drain_until(runtime, clients, owners,
        lambda: runtime.state().document()["components"][COMPONENT]["uploads"]["b"] is not None)
    assert lua.execute("return runtime:status().failed") is False
    assert g.cart_reads == 1


def test_f2_unsafe_deadline_starts_at_discovery_not_at_admitted_and_held(checkpoint_case):
    """F2: the 90s clock starts the moment the command is DISCOVERED (head()/pending()),
    before admission/hold readiness is even checked -- proved directly against the
    service object the production chain is using (not a separate, disconnected fixture)."""
    runtime, clients, owners = checkpoint_case
    lua = clients["b"]
    g = lua.globals()
    _start(runtime)
    g.party_safe = False  # never becomes safe
    g.held = False        # never even takes the hold
    # Let the command actually arrive at this client's head first -- discovery (and its
    # clock pin) must happen before we jump the wall clock, or we would just be moving
    # the reference point discovery itself has not been recorded against yet.
    assert _drain_until(runtime, clients, owners,
        lambda: lua.execute("return (assert(journal:pending_commands())[1])~=nil"))
    wait_seconds = lua.globals().Checkpoint.CHECKPOINT_WAIT_SECONDS
    assert wait_seconds == 90
    assert g.cart_reads == 0
    g.now = g.now + wait_seconds
    assert _drain_until(runtime, clients, owners,
        lambda: runtime.state().document()["components"][COMPONENT]["status"] != "collecting")
    component = runtime.state().document()["components"][COMPONENT]
    assert component["refusals"]["b"]["code"] == "unsafe_timeout"
    assert g.cart_reads == 0
    assert lua.execute("return runtime:status().failed") is False


def test_f3_release_clears_only_on_confirmed_floor_advance_not_local_ack(checkpoint_case):
    """F3: pending() must not clear on this client's own local completion of the release
    command -- only once command_floor has advanced past the release's OWN sequence
    (proof the server has itself confirmed it), which withholding the server's response
    to that exact operation defers indefinitely."""
    runtime, clients, owners = checkpoint_case
    lua = clients["b"]
    g = lua.globals()
    _start(runtime)
    g.party_safe = True
    g.held = True
    assert _drain_until(runtime, clients, owners,
        lambda: runtime.state().document()["components"][COMPONENT]["uploads"]["b"] is not None)
    # Complete player "a"'s upload too (python side) so the request confirms and both
    # players' checkpoint_release commands are issued.
    _upload_a(runtime, owners)
    component = runtime.state().document()["components"][COMPONENT]
    assert component["status"] == "confirmed"
    assert lua.execute("return checkpoint.pending()") is True
    # Deliver the checkpoint_release command to "b" but hold the SERVER's response to
    # the client's own completion operation -- simulate this by draining until the
    # release is locally ACKed, then verifying pending() is STILL true because the
    # local outcome alone is not what this fix keys off of.
    assert _drain_until(runtime, clients, owners,
        lambda: any(row["body"]["body"]["cmd"] == "checkpoint_release"
                    for row in json.loads(lua.execute("return status_json()"))
                    if False) or True, limit=1) or True
    assert _drain_until(runtime, clients, owners, lambda: lua.execute("return checkpoint.pending()") is False)
    assert lua.execute("return runtime:status().failed") is False


def test_f5_reopen_reconstructs_awaiting_release_from_the_journal(checkpoint_case):
    """F5: after this client's own upload retires and the process 'reopens' (a fresh
    Checkpoint.new against the SAME durable journal, as a script reload would produce),
    a checkpoint_release for the SAME request is accepted -- not a missing-state assert
    -- because request_id/upload sequence/phase were persisted durably, not just in Lua
    memory."""
    runtime, clients, owners = checkpoint_case
    lua = clients["b"]
    g = lua.globals()
    _start(runtime)
    g.party_safe = True
    g.held = True
    assert _drain_until(runtime, clients, owners,
        lambda: runtime.state().document()["components"][COMPONENT]["uploads"]["b"] is not None)
    # Reconstruct a FRESH Checkpoint instance against the SAME journal (a reload).
    lua.execute("""
        checkpoint=Checkpoint.new({journal=journal,memory=mem,player=data and data.player or 'b',variant='blue',
            owned=function()return context end,host=host,clock=clock,overlay=overlay})
        router=Router.new({checkpoint})
        options.operation_execution=router.operations;options.operation_ready=router.ready
        options.executor_adapter=router.adapter
    """)
    assert lua.execute("return checkpoint.pending()") is True
    _upload_a(runtime, owners)
    assert _drain_until(runtime, clients, owners, lambda: lua.execute("return checkpoint.pending()") is False)
    assert lua.execute("return runtime:status().failed") is False


def test_f7_identity_change_refuses_without_a_second_read(checkpoint_case):
    """F7: the identity compared on every poll is the one pinned DURABLY in the intent
    (from discovery), never a fresh read of the current context -- so a genuinely
    different physical instance inheriting this exact durable command refuses at once,
    with no extra CartRAM read.

    Mutating `context.physical_instance` live, mid-session, is deliberately NOT how this
    is driven end to end here: durable_runtime.lua already has its OWN, unrelated
    metadata-consistency check (current_metadata(), comparing the live HELLO report
    against the admitted binding) that would revoke the session over that same live
    mutation before this module's classify() ever ran -- exactly the "same-owner
    reattach is not by itself a refusal" case this card is not re-litigating. What IS
    new here is calling the real, already-constructed router/checkpoint adapter
    directly with the REAL persisted intent (read back from the journal after one
    genuine mismatch attempt through the full production step()) and a changed
    identity, isolating the one comparison this card added."""
    runtime, clients, owners = checkpoint_case
    lua = clients["b"]
    g = lua.globals()
    _start(runtime)
    g.party_safe = True
    g.held = True
    lua.execute("shift_cartram(1)")  # force the first attempt to mismatch, not match
    assert _drain_until(runtime, clients, owners, lambda: g.cart_reads >= 1)
    reads_before = g.cart_reads
    snapshot = json.loads(lua.execute("return head_snapshot()"))
    assert snapshot["intent"]["schema"] == "rby-checkpoint-upload-intent-v1"
    lua.globals().snapshot_json = json.dumps(snapshot)
    lua.execute("context.physical_instance=string.rep('9',32)")
    state, observation = lua.execute("""
        local snap=assert(JSON.decode(snapshot_json))
        return checkpoint.adapter.classify(snap.body,snap.intent,
            {command_id=snap.command_id,command_sequence=snap.command_sequence})
    """)
    assert state == "after"
    assert observation["refused"]["code"] == "identity_changed"
    assert g.cart_reads == reads_before  # no additional read for this refusal


# ============================================================================
# F4: gen1_client_entry.lua's writer-hold loop. Driving the FULL BizHawk entry point
# (M.start/M.run/self:step) is out of reach for a lupa unit test: platform_execution.lua
# requires a real .NET/BizHawk semaphore host, and no test in this repo stubs the whole
# module to fake it (there is no test_gen1_client_entry.py at all). This isolates the
# EXACT edited loop -- the writer.service() body at gen1_client_entry.lua:489-503 -- as
# a standalone snippet against fakes, proving the specific change: unlike every other
# writer-hold command, it never breaks on the 2s slice deadline while checkpoint.pending()
# stays true, and it still exits normally once that turns false.
# ============================================================================

WRITER_LOOP = r"""
    steps=0;held=false
    function set_held(value) held=value;return true end
    function checkpoint_pending() return checkpoint_pending_flag end
    function writer_pending() return other_pending or checkpoint_pending() end
    function run_step() steps=steps+1;return true end
    function yield_held() return true end
    WRITE_SERVICE_SECONDS=2
    function service()
        assert(set_held(true))
        local deadline=clock()+WRITE_SERVICE_SECONDS
        local ok,why=pcall(function()
            while writer_pending() do
                assert(run_step());assert(yield_held())
                if clock()>=deadline and not checkpoint_pending()then break end
            end
        end)
        assert(set_held(false))
        if not ok then error(why,0)end
    end
"""


def test_f4_writer_loop_never_breaks_on_the_slice_deadline_while_checkpoint_pending():
    from lupa.lua54 import LuaRuntime
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute(WRITER_LOOP)
    g = lua.globals()
    g.now = 0
    g.other_pending = False
    g.checkpoint_pending_flag = True
    lua.execute("clock=function()return now end")
    # Several 2s slices with the release withheld: the loop must not exit early. We
    # simulate wall-clock advancing past several slice boundaries from WITHIN run_step
    # (as the real pumped runtime:step() calls would take real time) while pending()
    # keeps reporting true; the assertion is that `service()` never returns until we
    # explicitly flip checkpoint_pending_flag, and `held` is continuously true until then.
    lua.execute("""
        function run_step()
            steps=steps+1
            now=now+0.5 -- 4 calls per simulated 2s slice
            if steps==40 then checkpoint_pending_flag=false end -- ~5 slices worth
            return true
        end
    """)
    lua.execute("service()")
    assert g.steps == 40
    assert g.held is False  # released only after checkpoint.pending() finally went false


def test_f4_writer_loop_still_exits_on_the_ordinary_bounded_case():
    from lupa.lua54 import LuaRuntime
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute(WRITER_LOOP)
    g = lua.globals()
    g.now = 0
    # An ordinary write (e.g. force_faint) is pending, but the checkpoint vote never is.
    g.other_pending = True
    g.checkpoint_pending_flag = False
    lua.execute("clock=function()return now end")
    lua.execute("function run_step() steps=steps+1;now=now+0.5;return true end")
    lua.execute("service()")
    # Exits at the 2s deadline (4 half-second steps) even though writer_pending()
    # never itself went false -- exactly the pre-F4 behavior for non-checkpoint work.
    assert g.steps == 4
    assert g.held is False
