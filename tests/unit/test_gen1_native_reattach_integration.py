"""The six B3 integration hooks on the merged source: the native reattach event is dispatched only on
the native-selected free service, its committed verdict rides the ACK response (byte-identical on
retry), the component is audited on every state read, native service continuity is offered again
but refused unless the player's held read was released at an idle terminal physical state, the
client settles the verdict through its own validator before any command executes, and the free
loop carries the same-frame native checkpoint beside its heartbeat inventory."""
import copy
import json
import os
import secrets
from pathlib import Path

import pytest

from server.gen1_native_reattach_runtime import COMPONENT, RESULT_SCHEMA
from server.gen1_run_config import create_runtime
from server.gen1_runtime_admission import PROTOCOL
from server.protocol import ProtocolError, digest
from server.protocol_journal import JournalError
from tests.unit.test_gen1_native_reattach_runtime import ARMED, TILES, read
from tests.unit.test_gen1_service_continuity import control, enroll_progress, proof, reconnect
from tests.unit.test_gen1_sessions import contract


def semantic(runtime, player, owner, event, payload, operation=None):
    session = runtime.gate.sessions[player]
    message = {"protocol": PROTOCOL, "player": player, "admission_epoch": runtime.gate.epoch, "session_id": session.session_id,
               "seq": session.last_seq + 1, "operation_id": operation or secrets.token_hex(16), "event": event, "payload": payload}
    return message, runtime.process(copy.deepcopy(message), owner)   # the runtime may mutate its own copy


def native_proof(runtime, player, **native):
    value = proof(runtime, player)
    value["native"] = {"lease_phase": "idle", "host_armed": False, "host_failure": None, **native}
    return value


def reattach_payload(runtime, player, **changes):
    binding = runtime.gate.sessions[player].metadata["control_binding"]
    cartridge = runtime.gate.sessions[player].metadata["gen1_metadata"]["cartridge"]
    physical = changes.pop("physical", "clean")
    value = read(**changes)
    value["host"]["owner_id"] = runtime.gate.sessions[player].metadata["gen1_metadata"]["physical_instance"]
    return {"schema": "rby-native-reattach-v1", "context_generation": binding["context_generation"],
            "final_sha1": cartridge["final_rom_sha1"], "physical": physical, "read": value}


@pytest.fixture
def native(tmp_path):
    """Dispatch-unit fixture ONLY: a free-service runtime with the native route flag set by attribute (as the
    native unit fixtures do). It proves the hooks' wiring and refusals, not the prepared-artifact path
    (Manager native route -> canonical companion pair -> launcher), which the selected-path live slice proves."""
    runtime = create_runtime(tmp_path, contract("yellow", "yellow"), free_service=True)
    runtime.native_trade = True
    try:
        yield runtime
    finally:
        runtime._writers.clear()
        runtime.close()


def test_reattach_event_is_dispatched_only_on_the_native_service_and_its_verdict_rides_the_ack(native, tmp_path):
    owners = enroll_progress(native)
    operation = secrets.token_hex(16)
    message, response = semantic(native, "a", owners["a"], "native_reattach", reattach_payload(native, "a"), operation)
    result = response["native_reattach_result"]
    assert result["schema"] == RESULT_SCHEMA and result["operation_id"] == operation and result["verdict"] == "released"
    assert result["read_digest"] == digest(message["payload"]["read"]) and result["class"] == "clean"
    assert native.gate.sessions["a"].last_response == response                     # re-cached with the verdict
    entry = native.state().document()["components"][COMPONENT]["a"]                 # audited on every state read
    assert entry["verdict"] == "released"
    # Exact retry (same envelope) returns the byte-identical enriched response and commits nothing new.
    revision = native.journal.snapshot().revision
    assert native.process(copy.deepcopy(message), owners["a"]) == response
    assert native.journal.snapshot().revision == revision
    # A forged payload under the same operation id is refused, not re-verdicted: at the same sequence the
    # session gate refuses the conflicting retry; at a new sequence the journal refuses the reused id.
    forged = copy.deepcopy(message)
    forged["payload"]["read"].update(overlay_hex=ARMED, published=True, phase=5, armed=True, token_hex="A1B2C3D4")
    forged["payload"]["physical"] = "armed"
    with pytest.raises(ProtocolError, match="conflicting"):
        native.process(copy.deepcopy(forged), owners["a"])
    forged["seq"] = native.gate.sessions["a"].last_seq + 1
    with pytest.raises(JournalError, match="reused"):
        native.process(forged, owners["a"])
    assert native.journal.snapshot().revision == revision
    # Not selected: the plain free service refuses the event before anything is read.
    plain = create_runtime(tmp_path / "plain", contract("yellow", "yellow"), free_service=True)
    try:
        plain_owners = enroll_progress(plain)
        with pytest.raises(ProtocolError, match="native-selected"):
            semantic(plain, "a", plain_owners["a"], "native_reattach", reattach_payload(plain, "a"))
    finally:
        plain._writers.clear()
        plain.close()


def test_native_continuity_is_refused_without_a_released_idle_reattach_read(native):
    owners = enroll_progress(native)
    native.disconnect("a", owners["a"])
    owners = reconnect(native)
    # Offered (the hello/control envelope now carries service_recovery for the native service) ...
    assert native._service_continuity_enabled() is True
    value = native_proof(native, "a")
    response = control(native, owners, "a", value)
    assert response["control"]["authority"] == "hold" and "held reattach read" in response["control"]["reason"]
    assert native.status()["service"]["continuity"]["a"] is False
    # ... a held read (APPLY-armed word) still refuses ...
    semantic(native, "a", owners["a"], "native_reattach",
             reattach_payload(native, "a", physical="armed", overlay_hex=ARMED, published=True, phase=5, armed=True, token_hex="A1B2C3D4"))
    response = control(native, owners, "a", native_proof(native, "a"))
    assert response["control"]["authority"] == "hold" and "released idle reattach read" in response["control"]["reason"]
    # ... a lease that is not idle refuses ...
    semantic(native, "a", owners["a"], "native_reattach",
             reattach_payload(native, "a", physical="lease_open",
                              lease={"phase": "armed", "command_id": "c" * 32, "intent_digest": "d" * 64, "token_hex": "A1B2C3D4", "receipt": False}))
    response = control(native, owners, "a", native_proof(native, "a"))
    assert response["control"]["authority"] == "hold" and "released idle reattach read" in response["control"]["reason"]
    # ... a released read whose client now states an armed lease, an armed host or a failed host refuses ...
    semantic(native, "a", owners["a"], "native_reattach", reattach_payload(native, "a"))
    for statement in ({"lease_phase": "armed"}, {"host_armed": True}, {"host_failure": "per-step authority is absent"}):
        response = control(native, owners, "a", native_proof(native, "a", **statement))
        assert response["control"]["authority"] == "hold" and "unarmed, unfailed native host" in response["control"]["reason"]
    # ... a proof without the native statement, or one on a non-native service, refuses ...
    response = control(native, owners, "a", proof(native, "a"))
    assert response["control"]["authority"] == "hold" and "unarmed, unfailed native host" in response["control"]["reason"]
    # ... and only the released clean read for THIS binding plus the idle statement lets the existing proof through.
    response = control(native, owners, "a", native_proof(native, "a"))
    assert native.status()["service"]["continuity"]["a"] is True      # a proved; the hold now waits only for b
    assert native.status()["service"]["continuity"]["b"] is False
    # A released read from an EARLIER session is not evidence about a reconnected client: the context
    # generation is reused by durable_runtime's re-HELLO but the control binding digest rotates, so the
    # persisted entry no longer matches and continuity is refused until the read is republished.
    native.disconnect("a", owners["a"])
    owners = reconnect(native)
    entry = native.state().document()["components"][COMPONENT]["a"]
    assert entry["verdict"] == "released" and entry["context_generation"] == native.gate.sessions["a"].metadata["control_binding"]["context_generation"]
    assert entry["binding_digest"] != native.gate.sessions["a"].metadata["control_binding"]["binding_digest"]
    response = control(native, owners, "a", native_proof(native, "a"))
    assert response["control"]["authority"] == "hold" and "current admission" in response["control"]["reason"]
    semantic(native, "a", owners["a"], "native_reattach", reattach_payload(native, "a"))   # republished under the new binding
    control(native, owners, "a", native_proof(native, "a"))
    assert native.status()["service"]["continuity"]["a"] is True


def test_client_settles_the_verdict_through_its_validator_before_any_command_executes():
    """durable_runtime hands a non-observation semantic reply to options.semantic_settlement; the entry's
    validator binds it to the event and the acknowledgement persists the post-callback baseline before
    the executor sees the delivered commands. A forged/stale verdict refuses the reply."""
    import hashlib
    import json
    from pathlib import Path

    from lupa.lua54 import LuaError, LuaRuntime
    root = Path(__file__).resolve().parents[2]
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.globals().package.path = (root / "lua/?.lua").as_posix() + ";" + lua.globals().package.path
    lua.globals().sha = lambda text: hashlib.sha256(text.encode()).hexdigest()
    lua.execute(r'''
        JSON=require('json_codec');Canonical=require('journal_document');R=require('gen1_native_reattach')
        read_value={schema='rby-native-reattach-read-v1',frame=1,overlay_hex=string.rep('23',16)}
        oldest={operation_id=string.rep('e',32),payload={event='native_reattach',payload={schema='rby-native-reattach-v1',read=read_value}}}
        dig=sha(Canonical.encode(read_value))
        function settle(packet)return R.settlement(oldest,packet,sha)end
        good={ack='ACK',native_reattach_result={schema='rby-native-reattach-result-v1',operation_id=string.rep('e',32),verdict='released',class='clean',read_digest=dig}}
        local r=settle(good);assert(r.verdict=='released')
    ''')
    for fault in ("packet.native_reattach_result.read_digest=string.rep('0',64)",
                  "packet.native_reattach_result.operation_id=string.rep('f',32)",
                  "packet.native_reattach_result=nil",
                  "packet.observation_result={schema='rby-observation-result-v1'};packet.native_reattach_result.verdict='released'"):
        with pytest.raises(LuaError):
            lua.execute("local packet=JSON.decode(JSON.encode(good));" + fault + ";settle(packet)")
    # The entry's callback (as wired into gen1_runtime.new) settles ONLY the typed event: an ordinary sync,
    # command_ack or trade event returns nil (their replies settle as before), and a verdict riding one of
    # those replies is unsolicited and refused, so a native client never revokes on its own idle traffic.
    lua.execute(r'''
        function entry_callback(oldest,packet)
            if type(oldest)~="table" or type(oldest.payload)~="table" or oldest.payload.event~="native_reattach" then
                assert(type(packet)~="table" or packet.native_reattach_result==nil,"unsolicited native reattach settlement")
                return nil
            end
            return R.settlement(oldest,packet,sha)
        end
        for _,name in ipairs({'sync','command_ack','native_frame_return','receptionist_entered'})do
            assert(entry_callback({operation_id=string.rep('1',32),payload={event=name}},{ack='ACK'})==nil)
        end
        assert(entry_callback(oldest,good).verdict=='released')
        local ok=pcall(entry_callback,{operation_id=string.rep('1',32),payload={event='sync'}},good);assert(not ok)
    ''')
    source = (root / "lua/gen1_client_entry.lua").read_text(encoding="utf-8")
    assert 'oldest.payload.event~="native_reattach" then' in source and '"unsolicited native reattach settlement"' in source
    # The runtime wiring: gen1_runtime forwards options.semantic_settlement and durable_runtime accepts only a function.
    entry = (root / "lua/gen1_runtime.lua").read_text(encoding="utf-8")
    assert "semantic_settlement=options.semantic_settlement" in entry
    durable = (root / "lua/durable_runtime.lua").read_text(encoding="utf-8")
    assert "semantic_result=options.semantic_settlement(copy(oldest),copy(packet))" in durable
    assert 'assert(semantic_result==nil,"unsolicited observation settlement")' in durable   # observation branch unchanged


def test_free_loop_carries_the_same_frame_native_checkpoint_beside_its_heartbeat_inventory():
    from lupa.lua54 import LuaRuntime

    import tests.unit.test_gen1_observation_loop as loop_test
    from tests.unit.test_gen1_observation_loop import HARNESS
    def harness(producer):
        value = LuaRuntime(unpack_returned_tuples=True)
        value.globals().root = loop_test.REPO.replace(os.sep, "/")
        value.execute("checkpoints={};native_checkpoint=" + producer)
        value.execute(HARNESS.replace("checkpoint=checkpoint}", "checkpoint=checkpoint,native_checkpoint=native_checkpoint}"))
        value.execute("build()")
        return value
    lua = harness("function(f)checkpoints[#checkpoints+1]=f;return {schema='rby-native-observation-v1',party={frame=f}}end")
    lua.globals().advance(21)                       # frame 120: heartbeat with inventory
    assert lua.eval("#appended") == 1
    assert lua.eval("appended[1].event.native_checkpoint.schema") == "rby-native-observation-v1"
    assert lua.eval("appended[1].event.native_checkpoint.party.frame") == lua.eval("appended[1].event.frame") == 120
    assert lua.eval("#checkpoints") == 1 and lua.eval("checkpoints[1]") == 120
    lua.globals().advance()                         # frame 121: quiet, no inventory, no checkpoint read
    assert lua.eval("#appended") == 1 and lua.eval("#checkpoints") == 1
    # Without the producer (no native manifest) the event has no native_checkpoint field at all.
    lua = harness("nil")
    lua.globals().advance(21)                       # frame 120: heartbeat without the producer
    assert lua.eval("#appended") == 1 and lua.eval("appended[1].event.native_checkpoint == nil") is True



def test_real_client_pump_settles_the_reattach_verdict_into_its_journal_before_execution_and_idle_traffic_never_revokes(tmp_path):
    """Actual Lua durable_runtime + client_journal + state_store against the actual Python Gen1Runtime
    (modeled transport/host only, as test_gen1_runtime_client): the native client publishes its read,
    the server's committed verdict rides the ACK, the entry's settlement validator accepts it and the
    acknowledgement callback persists the post-callback baseline (native_reattach) in the same journal
    commit; later sync/CONTROL/command traffic with the callback installed settles as before. Fails on
    old code at either end (no dispatch -> client revoke; no settlement hook -> no persisted verdict)."""
    from server.protocol import canonical_json, decode_frame
    from tests.unit.test_gen1_runtime_client import HARNESS, client
    from tests.unit.test_gen1_runtime_server import RuntimeCase

    case = RuntimeCase(tmp_path, ("yellow", "yellow"))
    case.runtime.free_service = True
    case.runtime.native_trade = True
    wired = HARNESS.replace(
        "journal=assert(Journal.open(store,function()ids=ids+1;return data.id_prefix..string.format('%030x',ids)end))",
        r"""
        settled={}
        journal=assert(Journal.open(store,function()ids=ids+1;return data.id_prefix..string.format('%030x',ids)end,{
            acknowledge_event=function(event,operation_id,baseline,result)
                if type(event)=="table" and event.event=="native_reattach" then
                    settled[#settled+1]={operation_id=operation_id,result=result}
                    baseline.native_reattach={read_digest=result and result.read_digest,verdict=result and result.verdict,class=result and result.class}
                    return baseline
                end
                return nil
            end}))
        Reattach=require('gen1_native_reattach')
        function entry_settlement(oldest,packet)
            if type(oldest)~="table" or type(oldest.payload)~="table" or oldest.payload.event~="native_reattach" then
                assert(type(packet)~="table" or packet.native_reattach_result==nil,"unsolicited native reattach settlement")
                return nil
            end
            return Reattach.settlement(oldest,packet,store.backend.sha256)
        end
        """).replace("read_context=function()return context end,",
                     "read_context=function()return context end,semantic_settlement=entry_settlement,")
    import tests.unit.test_gen1_runtime_client as harness_module
    original = harness_module.HARNESS
    harness_module.HARNESS = wired
    try:
        clients = {p: client(case, p) for p in ("a", "b")}
    finally:
        harness_module.HARNESS = original
    owners = {p: object() for p in clients}
    sent = []
    tick = 0

    def exchange(count):
        nonlocal tick
        for _ in range(count):
            tick += 1
            case.time = 10 + tick * 0.05
            for p, lua in clients.items():
                g = lua.globals()
                g.t = tick * 0.05
                assert g.step() is True, lua.eval("runtime:status().reason")
                while (line := g.pop()) is not None:
                    message = decode_frame(line.encode())
                    response = case.runtime.process(message, owners[p])
                    sent.append((p, message, response))
                    g.push(canonical_json(response))

    try:
        exchange(8)                                              # HELLO + first CONTROL for both
        payload = reattach_payload(case.runtime, "a")
        clients["a"].globals().reattach_json = json.dumps(payload)
        digest_expected = digest(payload["read"])
        clients["a"].execute("ids_before=ids;published=runtime:observe(JSON.array({{event='native_reattach',payload=assert(JSON.decode(reattach_json))}}),{schema='test-baseline-v1',hp=0})")
        exchange(8)
        replies = [(m, r) for p, m, r in sent if p == "a" and m["event"] == "native_reattach"]
        assert len(replies) == 1 and replies[0][1]["native_reattach_result"]["verdict"] == "released"
        assert replies[0][1]["native_reattach_result"]["read_digest"] == digest_expected
        state = json.loads(clients["a"].globals().state_json())
        assert state["observation"]["native_reattach"] == {"read_digest": digest_expected, "verdict": "released", "class": "clean"}
        assert not any(row["payload"]["event"] == "native_reattach" for row in state["outbox"])   # acknowledged and drained
        assert clients["a"].eval("#settled") == 1 and clients["a"].eval("settled[1].result.schema") == RESULT_SCHEMA
        assert case.runtime.state().document()["components"][COMPONENT]["a"]["verdict"] == "released"
        # Idle traffic with the settlement callback installed: CONTROLs keep flowing (the server's
        # pending_delivery=false hint quiets the syncs), nothing revokes.
        exchange(30)
        controls = [m for p, m, _ in sent if p == "a" and m["event"] == "control"]
        assert len(controls) >= 2 and clients["a"].eval("runtime:status().phase") != "failed"
        # A command delivered on a later reply (peer faint -> force_faint for a): the CONTROL hint turns the
        # sync on, the command is persisted through the same acknowledgement path, the callback returns nil
        # for the sync reply and nothing revokes; the executor never ran.
        clients["b"].globals().observe(json.dumps([{"event": "faint", "key": case.keys["b"]}]))
        exchange(16)
        assert any(p == "a" and m["event"] == "sync" for p, m, _ in sent)
        inbox = json.loads(clients["a"].globals().state_json())["inbox"]
        assert any(row["body"]["cmd"] == "force_faint" for row in inbox)
        assert clients["a"].eval("runtime:status().phase") != "failed"
        assert clients["a"].eval("#settled") == 1                  # only the typed event settled through the callback
    finally:
        case.close()
