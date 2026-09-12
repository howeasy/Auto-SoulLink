"""RBY UI/receipt bindings with explicitly modeled native evidence."""

import copy
import json

import pytest

from server.gen1_trade_ui_receipts import verify_partner_prompt, verify_receptionist_offer
from server.protocol_journal import JournalError
from tests.unit.test_client_journal import accepted, command, start
from tests.unit.test_client_state_store import runtime  # noqa: F401
from tests.unit.test_gen1_runtime_trade import TradeCase


def test_receptionist_ack_projection_preserves_other_observers_and_exact_offer(runtime):  # noqa: F811
    lua = runtime
    start(lua)
    lua.execute("""
        callbacks=require('gen1_trade_events');journal=assert(Journal.open(store,new_id,callbacks))
        payload={event='trade_offer',payload={schema='test',token_hex='12345678'}}
        offer_id=assert(journal:append(payload,{walking={x=2},gen1_receptionist={phase='queued',payload=payload}}))
        assert(journal:accept_response(offer_id,JSON.array()))
    """)
    state = lua.globals().state()
    assert state.observation.walking.x == 2
    assert state.observation.gen1_receptionist.phase == "acknowledged"
    assert state.observation.gen1_receptionist.operation_id == lua.globals().offer_id


@pytest.fixture
def evidence(tmp_path):
    case = TradeCase(tmp_path)
    case.admit("a")
    case.admit("b")
    case.policy.prompt = lambda trade, player: {
        "schema": "rby-native-prompt-v1",
        "proposal": trade["proposal"],
    }
    case.offer()
    issued = case.runtime.journal.command(
        "b", case.command("b", "native_trade_prompt")["command_id"]
    )
    party = case.policy.observed("b", case.blobs["b"])
    storage = bytearray(404)
    blob = case.blobs["b"]
    storage[:3] = bytes((1, blob[0], 255))
    storage[8:52], storage[272:283], storage[338:349] = blob[:44], blob[44:55], blob[55:]
    before = {
        "party": party,
        "map": 1,
        "fields": {"wTestControl": 0},
        "party_storage_hex": storage.hex().upper(),
        "tiles_hex": "00" * 360,
        "cart_digest": "0" * 64,
    }
    manifest = {
        "variant": "yellow",
        "final_sha1": "c" * 40,
        "receptionist": {"partner_prompt": {"saved_fields": {"wTestControl": 1}}},
    }
    receipt = {
        "schema": "rby-native-prompt-v1",
        "command_id": issued["command_id"],
        "command_sequence": issued["command_sequence"],
        "transaction_id": case.tx,
        "proposal_digest": issued["body"]["proposal_digest"],
        "context_generation": "b" * 32,
        "final_sha1": manifest["final_sha1"],
        "result": 0,
        "token_hex": "12345678",
        "generation": 1,
        "before": before,
        "after": copy.deepcopy(before),
        "sequence": ["service", "prompt", "choice"],
        "counts": {"service": 1, "prompt": 1, "choice": 1},
    }
    yield case, manifest, issued, receipt
    case.close()


@pytest.mark.parametrize("result", [0, 1, 3])
def test_native_decision_requires_exact_prompt_path_and_unchanged_complete_view(evidence, result):
    _, manifest, command, receipt = evidence
    receipt["result"] = result
    if result == 3:
        receipt["sequence"].pop()
        receipt["counts"].pop("choice")
    original = copy.deepcopy(receipt)
    assert verify_partner_prompt(command, receipt, manifest=manifest) == (result == 0)
    assert receipt == original


@pytest.mark.parametrize(
    "change",
    [
        "command",
        "context",
        "party",
        "map",
        "fields",
        "save",
        "sequence",
        "counts",
        "result",
        "token",
        "storage",
    ],
)
def test_wrong_or_mutated_native_prompt_evidence_is_refused(evidence, change):
    _, manifest, command, receipt = evidence
    if change == "command":
        receipt["command_sequence"] = True
    elif change == "context":
        receipt["context_generation"] = "f" * 32
    elif change == "sequence":
        receipt["sequence"].append("InternalClockTradeAnim")
    elif change == "counts":
        receipt["counts"]["choice"] = True
    elif change == "result":
        receipt["result"] = 2
    elif change == "token":
        receipt["token_hex"] = "00000000"
    elif change == "storage":
        for observed in (receipt["before"], receipt["after"]):
            observed["party_storage_hex"] = "00" * 404
    elif change == "party":
        receipt["after"]["party"]["party_count"] = 2
    elif change == "fields":
        receipt["after"]["fields"]["wTestControl"] = 1
    elif change == "save":
        receipt["after"]["cart_digest"] = "f" * 64
    else:
        receipt["after"]["map"] = 2
    with pytest.raises(JournalError):
        verify_partner_prompt(command, receipt, manifest=manifest)


@pytest.mark.parametrize("change", [None, "generation", "slot", "token", "save", "context"])
def test_receptionist_offer_matches_owned_current_snapshot_and_native_selection(evidence, change):
    case, manifest, _, _ = evidence
    snapshot = case.policy.observed("a", case.blobs["a"])
    payload = {
        "schema": "rby-receptionist-offer-v1",
        "final_sha1": manifest["final_sha1"],
        "context_generation": "a" * 32,
        "query_generation": 10,
        "offer_generation": 20,
        "token_hex": "12345678",
        "slot": 0,
        "key": case.keys["a"],
        "snapshot": copy.deepcopy(snapshot),
    }
    if change == "generation":
        payload["query_generation"] = True
    elif change == "slot":
        payload["slot"] = 1
    elif change == "token":
        payload["token_hex"] = "00000000"
    elif change == "save":
        payload["snapshot"]["save_id"] = "FFFF"
    elif change == "context":
        payload["context_generation"] = "b" * 32
    if change:
        with pytest.raises(JournalError):
            verify_receptionist_offer(
                payload, manifest=manifest, context=case.policy.contexts["a"], snapshot=snapshot
            )
    else:
        assert (
            verify_receptionist_offer(
                payload, manifest=manifest, context=case.policy.contexts["a"], snapshot=snapshot
            )
            == case.keys["a"]
        )


def test_save_failure_retains_native_applied_event_without_terminal_completion_or_reapply(runtime):  # noqa: F811
    lua = runtime
    start(lua)
    event = lua.globals().append('{"event":"sync"}')
    issued = command(1, cmd="native_trade_commit", player="a", transaction_id="a" * 32)
    assert accepted(lua.globals().accept(event, json.dumps([issued])))
    lua.execute("""
        journal=assert(Journal.open(store,new_id,require('gen1_trade_events')))
        file_ready=false;physical_apply=0
        native={prepare=function()return {schema='intent'}end,
            classify=function()return 'after',{schema='native'}end,
            apply=function()physical_apply=physical_apply+1 end,
            receipt=function(body,intent,observed)return observed end}
        adapter=require('gen1_saved_trade_executor').new({native=native,journal=journal,
            persist_save=function()
                assert(file_ready,'file readback failed')
                return {schema='slink-saveram-file-v1',flushed=true,readback=true,sha256=string.rep('1',64)}
            end})
        executor=require('command_executor').new(journal,adapter)
    """)
    ok, diagnostic = lua.globals().executor.step(lua.globals().executor, issued["command_id"])
    assert not ok and diagnostic.phase == "receipt"
    state = lua.globals().state()
    assert state.inbox[1].outcome is None and state.outbox[1].payload.event == "trade_applied"
    applied_id = state.outbox[1].operation_id
    lua.globals().file_ready = True
    ok, _ = lua.globals().executor.step(lua.globals().executor, issued["command_id"])
    assert ok and lua.globals().physical_apply == 0
    state = lua.globals().state()
    assert state.outbox[1].operation_id == applied_id and len(state.outbox) == 2
    assert state.outbox[2].payload.event == "trade_verified"
    assert state.inbox[1].receipt.schema == "rby-file-backed-v1"
    assert accepted(lua.globals().accept(applied_id, "[]"))
    assert lua.globals().state().command_floor == 0
    assert accepted(lua.globals().accept(lua.globals().state().outbox[1].operation_id, "[]"))
    assert lua.globals().state().command_floor == 1
