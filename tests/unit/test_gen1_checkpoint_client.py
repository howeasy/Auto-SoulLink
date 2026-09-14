"""R5b-2: the Lua client side of paired checkpoint capture.

gen1_checkpoint_client is a read-only command_service_router service: it claims
checkpoint_upload alone, never requests a write permit, never touches cartridge
memory, and samples exactly one coherent CartRAM image -- under the same dedicated
writer-hold window gen1_held_faint already uses -- once the durable outbox is fully
drained and the local digest matches the server's pinned witness.
"""
import hashlib
from pathlib import Path

import pytest
from lupa.lua54 import LuaError

from server.gen1_launcher import OBSERVATION_FILES
from tests.unit.test_client_journal import start
from tests.unit.test_client_state_store import runtime  # noqa: F401

ROOT = Path(__file__).resolve().parents[2]
PROJECTION = "cartram-0498-8000-v1"
REQUEST_ID = "1" * 32
COMMAND_ID = "2" * 32


def full_cart_hex():
    return bytes(i % 256 for i in range(0x8000)).hex().upper()


def next_cart_hex():
    return bytes((i + 1) % 256 for i in range(0x8000)).hex().upper()


def digest_for(hex_text):
    return hashlib.sha256(hex_text[0x498 * 2:].encode("utf-8")).hexdigest()


GOOD_DIGEST = digest_for(full_cart_hex())
BODY_LUA = ("{cmd='checkpoint_upload',request_id='" + REQUEST_ID + "',"
            "witness={digest='" + GOOD_DIGEST + "',projection='" + PROJECTION + "'}}")
BAD_WITNESS_BODY_LUA = ("{cmd='checkpoint_upload',request_id='" + REQUEST_ID + "',"
                         "witness={digest='" + "0" * 64 + "',projection='" + PROJECTION + "'}}")
# The real shape server/gen1_engine_signal_runtime.py's SAVE_WITNESS component carries
# (frame/digest/projection/index/operation_id) -- gen1_checkpoint_runtime.py's record()
# requires the receipt to echo this back byte-for-byte.
REAL_WITNESS_BODY_LUA = ("{cmd='checkpoint_upload',request_id='" + REQUEST_ID + "',"
                          "witness={digest='" + GOOD_DIGEST + "',projection='" + PROJECTION + "',"
                          "frame=42,index=0,operation_id='" + ("9" * 32) + "'}}")


def lua_source(template, **slots):
    """Substitute @@name@@ markers with raw Lua source (never a %/format operator,
    so callers can hand in strings that are themselves full of literal braces)."""
    text = template
    for name, value in slots.items():
        text = text.replace("@@" + name + "@@", value)
    return text


def boot(lua, *, party_safe=True, held=True):
    """Open the real journal (test_client_journal.start) and load the checkpoint
    client against a fake BizHawk/memory_gb environment: a deterministic 32 KiB
    CartRAM buffer (byte i is i%256, matching full_cart_hex/GOOD_DIGEST above), a
    zero-filled System Bus buffer wide enough for gen1_full_save_layout's field
    regions, and counters proving exactly which domain was actually read."""
    start(lua)
    lua.globals().party_safe = party_safe
    lua.globals().held = held
    lua.execute(r"""
        package.path=root..'/data/games/gen1_rby/?.lua;'..package.path
        cart_reads=0;bus_reads=0
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
                if domain=="CartRAM" then cart_reads=cart_reads+1 else bus_reads=bus_reads+1 end
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
        frame=100
        context={context_generation=string.rep('c',32),physical_instance=string.rep('p',32)}
        host={status=function()return {physical_stop_verified=held}end}
        mem={isPartyWriteSafe=function()return party_safe end}
        Checkpoint=require('gen1_checkpoint_client')
        -- test_client_journal.start() opens the journal with no callbacks; reopen it
        -- with the SAME completion_event composition client_entry.lua wires in, so the
        -- round trip test proves the typed save_upload envelope, not the generic ACK.
        store:close();store=assert(open_store())
        journal=assert(Journal.open(store,new_id,{completion_event=Checkpoint.completion_event}))
        service=Checkpoint.new({journal=journal,memory=mem,player='b',variant='yellow',
            owned=function()return context end,host=host})
        Router=require('command_service_router');router=Router.new({service})
        -- Production's gen1_runtime.lua unwraps {cmd,body} before calling the router
        -- adapter; reproduce that one layer so a real durable journal entry (always
        -- stored wrapped, per accept_response below) reaches the service unwrapped.
        local function unwrapped_adapter(inner)
            local wrapped={}
            for _,name in ipairs({'prepare','classify','apply','receipt'})do
                wrapped[name]=function(body,...)
                    return inner[name](require('gen1_runtime').unwrap(body,'b'),...)
                end
            end
            return wrapped
        end
        executor=require('command_executor').new(journal,unwrapped_adapter(router.adapter))
        function step() return executor:step(COMMAND_ID) end
        function ready(body_lua)
            local body=assert(load('return '..body_lua))()
            local ok,why=service.ready(body,nil,{admitted=true,operation_held=true})
            return ok,why
        end
        function try_prepare(body_lua)
            local body=assert(load('return '..body_lua))()
            local ok,err=pcall(service.adapter.prepare,body,{command_id=COMMAND_ID,command_sequence=1})
            return ok,tostring(err)
        end
    """)
    lua.globals().COMMAND_ID = COMMAND_ID


def admit(lua, body_lua):
    lua.execute(lua_source("""
        do
            local body=@@BODY@@
            local event=assert(journal:append({event='fixture'}))
            assert(journal:accept_response(event,JSON.array({
                {command_id=COMMAND_ID,command_sequence=1,body={cmd=body.cmd,body=body}}})))
        end
    """, BODY=body_lua))


def test_handles_and_validate_reject_unknown_or_malformed_bodies(runtime):  # noqa: F811
    lua = runtime
    boot(lua)
    lua.execute(lua_source("""
        assert(Checkpoint.handles({cmd='checkpoint_upload'})==true)
        assert(Checkpoint.handles({cmd='force_faint'})==false)
        assert(Checkpoint.handles('not a table')==false)
        Checkpoint.validate(@@BODY@@) -- does not raise
    """, BODY=BODY_LUA))
    cases = [
        ("{cmd='checkpoint_upload',request_id='" + REQUEST_ID + "',witness={digest='" + GOOD_DIGEST
         + "',projection='" + PROJECTION + "'},extra=1}", "unknown checkpoint_upload field"),
        ("{cmd='checkpoint_upload',request_id='" + REQUEST_ID + "'}", "missing checkpoint_upload field"),
        ("{cmd='checkpoint_upload',request_id='',witness={digest='" + GOOD_DIGEST
         + "',projection='" + PROJECTION + "'}}", "invalid checkpoint request id"),
        ("{cmd='checkpoint_upload',request_id='" + REQUEST_ID + "',witness={projection='" + PROJECTION + "'}}",
         "invalid checkpoint witness digest"),
        ("{cmd='checkpoint_upload',request_id='" + REQUEST_ID
         + "',witness={digest='z'..string.rep('0',63),projection='" + PROJECTION + "'}}",
         "invalid checkpoint witness digest"),
        ("{cmd='checkpoint_upload',request_id='" + REQUEST_ID + "',witness={digest='" + GOOD_DIGEST + "'}}",
         "unsupported checkpoint witness projection"),
        ("{cmd='checkpoint_upload',request_id='" + REQUEST_ID + "',witness={digest='" + GOOD_DIGEST
         + "',projection='other-v1'}}", "unsupported checkpoint witness projection"),
    ]
    for body_lua, match in cases:
        with pytest.raises(LuaError, match=match):
            lua.execute(lua_source("Checkpoint.validate(@@BODY@@)", BODY=body_lua))
    # The real server witness (server/gen1_engine_signal_runtime.py's SAVE_WITNESS
    # component) carries frame/index/operation_id too; validate accepts it as opaque
    # extra data rather than rejecting fields this client does not itself act on.
    lua.execute(lua_source("""
        Checkpoint.validate({cmd='checkpoint_upload',request_id='""" + REQUEST_ID + """',
            witness={digest='""" + GOOD_DIGEST + """',projection='""" + PROJECTION + """',
            frame=42,index=0,operation_id=string.rep('9',32)}})
    """))


def test_router_claims_checkpoint_upload_exactly_once_and_leaves_unknown_unclaimed(runtime):  # noqa: F811
    lua = runtime
    boot(lua)
    admit(lua, BODY_LUA)
    ok, why = lua.execute(lua_source(
        "local ok,why=router.ready(@@BODY@@,nil,{admitted=true,operation_held=true});return ok,why",
        BODY=BODY_LUA))
    assert ok is True and why is None
    ok, why = lua.execute("return router.ready({cmd='unknown'})")
    assert ok is False and why == "command has no selected service"
    lua.execute("""
        local rogue={handles=function(body)return body.cmd=='checkpoint_upload'end,
            ready=function()return true end,adapter={},operations={
                request=function()return nil end,accept=function()return true end,
                authorize_apply=function()return false end,revoke=function()end,status=function()return{}end}}
        for _,name in ipairs({'prepare','classify','apply','receipt'})do rogue.adapter[name]=function()end end
        conflict=Router.new({service,rogue})
    """)
    with pytest.raises(LuaError, match="multiple services"):
        lua.execute("conflict.adapter.apply({cmd='checkpoint_upload'})")


def test_ready_defers_without_reading_when_unsafe_or_unheld(runtime):  # noqa: F811
    lua = runtime
    boot(lua)
    admit(lua, BODY_LUA)
    lua.globals().party_safe = False
    ok, why = lua.globals().ready(BODY_LUA)
    assert ok is False and isinstance(why, str)
    lua.globals().party_safe = True
    lua.globals().held = False
    ok, why = lua.globals().ready(BODY_LUA)
    assert ok is False and isinstance(why, str)
    assert lua.globals().cart_reads == 0


def test_ready_defers_while_not_admitted_and_while_events_are_pending(runtime):  # noqa: F811
    lua = runtime
    boot(lua)
    admit(lua, BODY_LUA)
    ok, why = lua.execute(lua_source(
        "return service.ready(@@BODY@@,nil,{admitted=false,operation_held=true})", BODY=BODY_LUA))
    assert ok is False and isinstance(why, str)
    ok, why = lua.execute(lua_source(
        "return service.ready(@@BODY@@,nil,{admitted=true,operation_held=false})", BODY=BODY_LUA))
    assert ok is False and isinstance(why, str)
    lua.execute("assert(journal:append({event='undrained'}))")
    ok, why = lua.globals().ready(BODY_LUA)
    assert ok is False and isinstance(why, str)
    assert lua.globals().cart_reads == 0


def test_ready_is_true_once_matched_admitted_held_safe_and_drained(runtime):  # noqa: F811
    lua = runtime
    boot(lua)
    admit(lua, BODY_LUA)
    ok, why = lua.globals().ready(BODY_LUA)
    assert ok is True and why is None
    assert lua.globals().cart_reads == 0  # readiness alone never reads CartRAM


def test_prepare_refuses_and_reads_no_cartram_when_unsafe_unheld_or_undrained(runtime):  # noqa: F811
    lua = runtime
    boot(lua)
    admit(lua, BODY_LUA)
    lua.globals().party_safe = False
    ok, err = lua.globals().try_prepare(BODY_LUA)
    assert ok is False and "party write-safe" in err
    assert lua.globals().cart_reads == 0
    lua.globals().party_safe = True
    lua.globals().held = False
    ok, err = lua.globals().try_prepare(BODY_LUA)
    assert ok is False and "party write-safe" in err  # safe() folds both conditions
    assert lua.globals().cart_reads == 0
    lua.globals().held = True
    lua.execute("assert(journal:append({event='undrained'}))")
    ok, err = lua.globals().try_prepare(BODY_LUA)
    assert ok is False and "drain" in err
    assert lua.globals().cart_reads == 0


def test_prepare_refuses_on_digest_mismatch_and_never_completes(runtime):  # noqa: F811
    lua = runtime
    boot(lua)
    admit(lua, BAD_WITNESS_BODY_LUA)
    done, result = lua.globals().step()
    assert done is False
    assert result["outcome"] == "NACK" and "digest" in result["reason"]
    assert lua.globals().cart_reads == 1  # one sample taken to compute the digest that then refused
    entry = lua.globals().state().inbox[1]
    assert entry.outcome is None  # never completed; no receipt persisted


def test_full_round_trip_produces_exact_hex_and_survives_reopen(runtime):  # noqa: F811
    lua = runtime
    boot(lua)
    admit(lua, BODY_LUA)
    done, result = lua.globals().step()
    assert done is True and result["outcome"] == "ACK"
    receipt = result["receipt"]
    assert receipt["request_id"] == REQUEST_ID
    assert receipt["cart_hex"] == full_cart_hex()
    assert len(receipt["cart_hex"]) == 65536 and receipt["cart_hex"] == receipt["cart_hex"].upper()
    assert receipt["frame"] == 100
    assert receipt["context_generation"] == "c" * 32
    assert receipt["physical_instance"] == "p" * 32
    assert receipt["final_sha1"] == "e" * 40
    assert lua.globals().cart_reads == 1
    outbox = lua.globals().state().outbox
    payload = outbox[len(outbox)].payload
    assert payload["event"] == "save_upload" and payload["command_id"] == COMMAND_ID
    assert payload["command_sequence"] == 1
    assert payload["receipt"]["cart_hex"] == full_cart_hex()
    lua.globals().reopen()
    state = lua.globals().state()
    stored = state.inbox[1]
    assert stored.outcome == "ACK" and stored.receipt["cart_hex"] == full_cart_hex()
    reopened_outbox = state.outbox
    reopened_payload = reopened_outbox[len(reopened_outbox)].payload
    assert reopened_payload["receipt"]["cart_hex"] == full_cart_hex()


def test_receipt_echoes_the_real_five_field_server_witness_verbatim(runtime):  # noqa: F811
    lua = runtime
    boot(lua)
    admit(lua, REAL_WITNESS_BODY_LUA)
    done, result = lua.globals().step()
    assert done is True and result["outcome"] == "ACK"
    witness = result["receipt"]["witness"]
    assert witness["digest"] == GOOD_DIGEST
    assert witness["projection"] == PROJECTION
    assert witness["frame"] == 42
    assert witness["index"] == 0
    assert witness["operation_id"] == "9" * 32


def test_duplicate_delivery_replays_the_stored_receipt_without_resampling(runtime):  # noqa: F811
    lua = runtime
    boot(lua)
    admit(lua, BODY_LUA)
    done, first = lua.globals().step()
    assert done is True and first["outcome"] == "ACK"
    assert lua.globals().cart_reads == 1
    # Change the physical world after the ACK: a resample, if one happened, would differ.
    lua.globals().frame = 999
    lua.execute("shift_cartram(1)")
    assert next_cart_hex() != full_cart_hex()
    done, second = lua.globals().step()
    assert done is True and second["replayed"] is True
    assert second["receipt"]["cart_hex"] == first["receipt"]["cart_hex"] == full_cart_hex()
    assert second["receipt"]["frame"] == first["receipt"]["frame"] == 100
    assert lua.globals().cart_reads == 1  # no second CartRAM read for the duplicate delivery


def test_apply_is_unreachable_and_authorize_apply_always_refuses(runtime):  # noqa: F811
    lua = runtime
    boot(lua)
    admit(lua, BODY_LUA)
    with pytest.raises(LuaError, match="never writes cartridge memory"):
        lua.execute("service.adapter.apply()")
    allowed, why = lua.execute(lua_source("return service.operations.authorize_apply(@@BODY@@)", BODY=BODY_LUA))
    assert allowed is False and isinstance(why, str)
    assert lua.execute("return service.operations.request()") is None
    assert lua.execute("return service.operations.accept(nil)") is True
    with pytest.raises(LuaError, match="takes no operation grant"):
        lua.execute("service.operations.accept({grant=true})")


def test_completion_event_composes_with_a_prior_callback_and_rejects_double_claims(runtime):  # noqa: F811
    lua = runtime
    boot(lua)
    lua.execute(lua_source("""
        local function compose(previous)
            return function(entry,outcome,receipt)
                local first=previous and previous(entry,outcome,receipt)or nil
                local second=Checkpoint.completion_event(entry,outcome,receipt)
                assert(first==nil or second==nil,'multiple journal projections claimed one event')
                return first or second
            end
        end
        local other_cmd_entry={body={cmd='force_faint',body={cmd='force_faint'}},
            command_id=string.rep('a',32),command_sequence=1}
        local checkpoint_entry={body={cmd='checkpoint_upload',body=@@BODY@@},
            command_id=string.rep('b',32),command_sequence=2}
        local previous=function(entry)if entry.body.body.cmd=='force_faint'then return {event='command_ack'}end end
        local composed=compose(previous)
        other_result=composed(other_cmd_entry,'ACK',{})
        checkpoint_result=composed(checkpoint_entry,'ACK',{cart_hex='FF'})
        local greedy=function()return {event='rogue'}end
        greedy_composed=compose(greedy)
        function trigger_conflict()
            local entry={body={cmd='checkpoint_upload',body=@@BODY@@},command_id=string.rep('b',32),command_sequence=2}
            greedy_composed(entry,'ACK',{})
        end
    """, BODY=BODY_LUA))
    g = lua.globals()
    assert g.other_result["event"] == "command_ack"
    assert g.checkpoint_result["event"] == "save_upload"
    assert g.checkpoint_result["command_id"] == "b" * 32
    assert g.checkpoint_result["command_sequence"] == 2
    assert g.checkpoint_result["receipt"]["cart_hex"] == "FF"
    with pytest.raises(LuaError, match="multiple journal projections"):
        lua.execute("trigger_conflict()")


def test_completion_event_refuses_a_terminal_nack(runtime):  # noqa: F811
    lua = runtime
    boot(lua)
    lua.execute(lua_source(
        "entry={body={cmd='checkpoint_upload',body=@@BODY@@},command_id=string.rep('b',32),command_sequence=1}",
        BODY=BODY_LUA))
    with pytest.raises(LuaError, match="terminal NACK"):
        lua.execute("Checkpoint.completion_event(entry,'NACK',{})")


def test_launcher_ships_the_checkpoint_client_only_with_initial_observations():
    assert "lua/gen1_checkpoint_client.lua" in OBSERVATION_FILES
