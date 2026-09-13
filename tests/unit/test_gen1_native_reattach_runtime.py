"""Server acceptance of the native client's held start-of-script read: durable, idempotent, bound
to the current admission, and a verdict from the server's own view of obligations. `released`
only for a clean read with nothing owed; every hold names its class; nothing is mutated."""
import copy
import secrets

import pytest

from server.gen1_native_reattach_runtime import COMPONENT, EVENT, classify, key, record, verify_journal, verify_state
from server.protocol import digest
from server.protocol_journal import JournalError
from tests.unit.test_gen1_runtime_trade import TradeCase

TILES = "2A2B2C2C" + "23" * 12
ARMED = "534C54310105070600000000A1B2C3D4"


def read(**changes):
    value = {"schema": "rby-native-reattach-read-v1", "frame": 4242, "pc": 0x40, "sp": 0xDFF7, "bank": 1,
             "overlay_hex": TILES, "published": False, "phase": None, "armed": False, "done": False, "token_hex": None,
             "lease": {"phase": "idle", "command_id": None, "intent_digest": None, "token_hex": None, "receipt": False},
             "host": {"owner_id": "1" * 32, "process_id": 7, "capability_id": "bizhawk-2.11.1-gambatte-exclusive-hold-v1", "held": True}}
    value.update(changes)
    return value


def request(case, player="a", physical="clean", **changes):
    binding = case.runtime.gate.sessions[player].metadata["control_binding"]
    cartridge = case.runtime.gate.sessions[player].metadata["gen1_metadata"]["cartridge"]
    return {"event": EVENT, "payload": {"schema": "rby-native-reattach-v1", "context_generation": binding["context_generation"],
                                        "final_sha1": cartridge["final_rom_sha1"], "physical": physical, "read": read(**changes)}}


@pytest.fixture
def case(tmp_path):
    value = TradeCase(tmp_path)
    value.admit("a"); value.admit("b"); value.control("a"); value.control("b")
    yield value
    value.close()


def test_a_clean_read_with_nothing_owed_is_released_durably_and_replays_without_a_second_commit(case):
    run = case.runtime
    before = run.journal.snapshot()
    operation = secrets.token_hex(16)
    message = request(case)
    result = record(run, "a", operation, message)
    assert result == {"ack": "ACK", "native_reattach": {"verdict": "released", "class": "clean", "read_digest": digest(message["payload"]["read"])}}
    document = run.state().document()
    entry = document["components"][COMPONENT]["a"]
    assert entry["verdict"] == "released" and entry["class"] == "clean" and entry["frame"] == 4242 and entry["lease_phase"] == "idle"
    assert run.journal.record(COMPONENT, key("a")).value == entry
    assert run.journal.snapshot().revision == before.revision + 1
    verify_journal(run.journal, run.state())
    # Exact replay: the committed verdict, no new commit.
    assert record(run, "a", operation, copy.deepcopy(message)) == result
    assert run.journal.snapshot().revision == before.revision + 1
    # A different payload under the same operation id is a conflict, not a fresh verdict.
    forged = request(case, overlay_hex=ARMED, published=True, phase=5, armed=True, token_hex="A1B2C3D4")
    with pytest.raises(JournalError):
        record(run, "a", operation, forged)
    assert run.journal.snapshot().revision == before.revision + 1


@pytest.mark.parametrize("state", ["armed", "done", "mid_routine", "lease_armed", "lease_complete", "pending_native", "active_trade"])
def test_every_obligation_or_physical_arming_holds_with_its_class(case, state):
    run = case.runtime
    message = request(case)
    if state == "armed":
        message = request(case, physical="armed", overlay_hex=ARMED, published=True, phase=5, armed=True, token_hex="A1B2C3D4")
    elif state == "done":
        message = request(case, physical="armed", overlay_hex="534C54310107060600000000A1B2C3D4", published=True, phase=7, done=True, token_hex="A1B2C3D4")
    elif state == "mid_routine":
        message = request(case, physical="mid_routine")
    elif state == "lease_armed":
        message = request(case, physical="lease_open", lease={"phase": "armed", "command_id": "c" * 32, "intent_digest": "d" * 64, "token_hex": "A1B2C3D4", "receipt": False})
    elif state == "lease_complete":
        message = request(case, physical="lease_open", lease={"phase": "complete", "command_id": "c" * 32, "intent_digest": "d" * 64, "token_hex": "A1B2C3D4", "receipt": True})
    elif state in {"pending_native", "active_trade"}:
        case.offer(); case.accept(); case.trade_control("prepare")   # native_trade_prepare pending on both, trade active
        message = request(case)
    before = run.journal.snapshot()
    result = record(run, "a", secrets.token_hex(16), message)
    expected = {"armed": "armed", "done": "done_unreleased", "mid_routine": "mid_routine", "lease_armed": "lease_open",
                "lease_complete": "lease_open", "pending_native": "pending_native_command", "active_trade": "pending_native_command"}[state]
    assert result["native_reattach"]["verdict"] == "held" and result["native_reattach"]["class"] == expected
    assert run.journal.snapshot().revision == before.revision + 1
    entry = run.state().document()["components"][COMPONENT]["a"]
    assert entry["verdict"] == "held" and entry["class"] == expected
    verify_journal(run.journal, run.state())
    if state in {"pending_native", "active_trade"}:
        # The trade itself is untouched by the read.
        from server.trade_coordinator import NAMESPACE
        assert run.journal.record(NAMESPACE, case.tx).value["phase"] == "preparing"


@pytest.mark.parametrize("fault", ["context", "cartridge", "owner", "unheld", "unpublished_but_armed", "published_without_token",
                                   "lease_phase", "extra_field", "physical_word", "no_session",
                                   "raw_armed_flagged_clean", "raw_tiles_flagged_armed", "raw_done_flagged_armed", "wrong_token", "wrong_phase"])
def test_a_read_that_is_not_the_current_admission_or_not_well_typed_is_refused_before_any_commit(case, fault):
    run = case.runtime
    message = request(case)
    payload = message["payload"]
    player = "a"
    if fault == "context":
        payload["context_generation"] = "f" * 32
    elif fault == "cartridge":
        payload["final_sha1"] = "f" * 40
    elif fault == "owner":
        payload["read"]["host"]["owner_id"] = "9" * 32
    elif fault == "unheld":
        payload["read"]["host"]["held"] = False
    elif fault == "unpublished_but_armed":
        payload["read"]["armed"] = True
    elif fault == "published_without_token":
        payload["read"].update(published=True, phase=5, armed=True)
    elif fault == "lease_phase":
        payload["read"]["lease"]["phase"] = "other"
    elif fault == "extra_field":
        payload["read"]["extra"] = 1
    elif fault == "physical_word":
        payload["physical"] = "released"
    elif fault == "raw_armed_flagged_clean":
        payload["read"]["overlay_hex"] = ARMED                      # SLT1, byte4=1, byte5=5, gen 7!=6: APPLY-armed bytes, flagged clean
    elif fault == "raw_tiles_flagged_armed":
        payload["read"].update(published=True, phase=5, armed=True, token_hex="A1B2C3D4")   # tile bytes, flagged armed
    elif fault == "raw_done_flagged_armed":
        payload["read"].update(overlay_hex="534C54310107060600000000A1B2C3D4", published=True, phase=7, armed=True, token_hex="A1B2C3D4")
    elif fault == "wrong_token":
        payload["read"].update(overlay_hex=ARMED, published=True, phase=5, armed=True, token_hex="00000000")
    elif fault == "wrong_phase":
        payload["read"].update(overlay_hex=ARMED, published=True, phase=3, armed=True, token_hex="A1B2C3D4")
    else:
        player = "b"
        run.gate.sessions.pop("b")
    before = run.journal.snapshot()
    with pytest.raises(JournalError):
        record(run, player, secrets.token_hex(16), message)
    assert run.journal.snapshot() == before and COMPONENT not in run.state().document()["components"]


def test_the_entry_survives_reopen_and_the_audits_catch_a_tampered_record(case):
    run = case.runtime
    record(run, "a", secrets.token_hex(16), request(case))
    case.close(); case.open(); run = case.runtime
    entry = run.state().document()["components"][COMPONENT]["a"]
    assert entry["verdict"] == "released"
    verify_journal(run.journal, run.state())
    document = run.state().document()
    document["components"][COMPONENT]["a"]["verdict"] = "held"
    stage = type("S", (), {"document": staticmethod(lambda: document)})()
    with pytest.raises(JournalError):
        verify_state(stage)
    document["components"][COMPONENT]["a"].update(verdict="released", class_="clean")
    document["components"][COMPONENT]["a"]["read_digest"] = "0" * 64
    document["components"][COMPONENT]["a"].pop("class_")
    with pytest.raises(JournalError):
        verify_journal(run.journal, stage)


def test_classify_is_a_pure_view_of_read_and_obligations(case):
    run = case.runtime
    document = run.state().document()
    assert classify(document, run.journal, "a", request(case)["payload"]) == ("released", "clean")
    case.offer(); case.accept()
    with_trade = run.state().document()
    assert classify(with_trade, run.journal, "a", request(case)["payload"]) == ("held", "active_trade")   # accepted, no native command yet
    # An entry whose record is not linkable (digest/phase differ from the verified document) is refused, not decided.
    unlinked = copy.deepcopy(with_trade)
    unlinked["components"]["gen1-trade"]["transactions"][case.tx]["record_digest"] = "0" * 64
    with pytest.raises(JournalError, match="not the one the verified state links"):
        classify(unlinked, run.journal, "a", request(case)["payload"])


def test_a_same_revision_trade_record_swap_between_snapshot_and_classify_is_refused_not_decided(case, monkeypatch):
    run = case.runtime
    case.offer(); case.accept()                                   # a non-terminal trade with a linked gen1-trade entry
    document = run.state().document()                             # verified snapshot read BEFORE the swap
    assert document["components"]["gen1-trade"]["transactions"]
    real = run.journal.record
    from server.trade_coordinator import NAMESPACE as TRADES
    def swapped(namespace, identifier):
        record_ = real(namespace, identifier)
        if namespace == TRADES and identifier == case.tx:
            import dataclasses
            body = copy.deepcopy(record_.value)
            body["phase"] = "link_committed"; body["recovery_required"] = False   # a terminal-looking substitute
            return dataclasses.replace(record_, value=body)
        return record_
    monkeypatch.setattr(run.journal, "record", swapped)
    with pytest.raises(JournalError, match="not the one the verified state links"):
        classify(document, run.journal, "a", request(case)["payload"])


def test_attach_result_exposes_the_committed_verdict_on_the_ack_and_caches_it_for_retry(case):
    """Root's second server hook: DurableRuntime ignores the dispatch result, so the verdict must ride the
    ACK response explicitly (as observation_result does), identical on a session-local retry."""
    from server.gen1_native_reattach_runtime import RESULT_SCHEMA, attach_result
    run = case.runtime
    operation = secrets.token_hex(16)
    message = {**request(case), "operation_id": operation, "player": "a", "seq": 9}
    semantic = {"event": message["event"], "payload": message["payload"]}
    committed = record(run, "a", operation, semantic)
    response = attach_result(run, "a", message, {"ack": "ACK"})
    assert response["native_reattach_result"] == {"schema": RESULT_SCHEMA, "operation_id": operation, **committed["native_reattach"]}
    assert run.gate.sessions["a"].last_response == response
    assert attach_result(run, "a", message, {"ack": "ACK"}) == response                    # retry: byte-identical
    assert attach_result(run, "a", message, {"ack": "NACK"}) == {"ack": "NACK"}             # only an ACK carries a verdict
    assert attach_result(run, "a", {**message, "event": "observation"}, {"ack": "ACK"}) == {"ack": "ACK"}
    with pytest.raises(JournalError, match="lacks its committed verdict"):
        attach_result(run, "a", {**message, "operation_id": secrets.token_hex(16)}, {"ack": "ACK"})  # never recorded


def test_client_settlement_accepts_only_the_exact_verdict_for_its_event():
    """Root's client hook: durable_runtime's non-observation semantic branch hands the oldest event and the
    packet to this validator; anything but the exact committed verdict for this operation and read is refused."""
    import hashlib
    import json
    from pathlib import Path

    from lupa.lua54 import LuaError, LuaRuntime
    root = Path(__file__).resolve().parents[2]
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.globals().package.path = (root / "lua/?.lua").as_posix() + ";" + lua.globals().package.path
    lua.globals().sha = lambda text: hashlib.sha256(text.encode()).hexdigest()
    lua.execute("""
        R=require('gen1_native_reattach');Canonical=require('journal_document')
        read_value={schema='rby-native-reattach-read-v1',frame=1,overlay_hex=string.rep('23',16)}
        oldest={operation_id=string.rep('e',32),payload={event='native_reattach',payload={schema='rby-native-reattach-v1',read=read_value}}}
        digest=sha(Canonical.encode(read_value))
        good={native_reattach_result={schema='rby-native-reattach-result-v1',operation_id=string.rep('e',32),verdict='released',class='clean',read_digest=digest}}
        local r=R.settlement(oldest,good,sha);assert(r.verdict=='released' and r.read_digest==digest)
        r.verdict='held';assert(good.native_reattach_result.verdict=='released')   -- detached copy
    """)
    from server.protocol import digest as server_digest
    assert lua.globals().digest == server_digest(json.loads(lua.eval("require('json_codec').encode(read_value)")))
    for fault in ("good.native_reattach_result.operation_id=string.rep('f',32)",
                  "good.native_reattach_result.read_digest=string.rep('0',64)",
                  "good.native_reattach_result.verdict='maybe'",
                  "good.native_reattach_result.extra=1",
                  "good.native_reattach_result=nil",
                  "oldest.payload.event='observation'"):
        with pytest.raises(LuaError):
            lua.execute(fault + ";R.settlement(oldest,good,sha)")
        lua.execute("good={native_reattach_result={schema='rby-native-reattach-result-v1',operation_id=string.rep('e',32),verdict='released',class='clean',read_digest=digest}};oldest.payload.event='native_reattach'")
