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
                                   "lease_phase", "extra_field", "physical_word", "no_session"])
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
    trade_open = copy.deepcopy(document)
    trade_open["components"]["gen1-trade"] = {"schema": "slink-gen1-trade-recovery-v1", "transactions": {"e" * 32: {"phase": "commit_persisted", "record_digest": "0" * 64, "pending": {"a": [], "b": []}}}}
    assert classify(trade_open, run.journal, "a", request(case)["payload"]) == ("held", "trade_open")
