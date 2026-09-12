"""Free-run observation batches (P10) settle through the modules that own each part.

The runtime, journal, identity registry and staged rules are real; signals, receipts and
checkpoints are the engine-shaped fixtures the standalone event tests already use, so every
assertion here is about composition and ordering, not about decoding.
"""
import copy
import secrets

import pytest

from server.gen1_acquisition_runtime import (
    COMPONENT as ACQUISITIONS,
    ORDINALS,
    verify_journal as verify_acquisitions,
    verify_state as verify_acquisition_state,
)
from server.gen1_faint_runtime import COMPONENT as FAINTS
from server.gen1_inventory_observation import COMPONENT as INVENTORY, record_key as inventory_key
from server.gen1_launcher import FREE_FILES, configuration
from server.gen1_observation_runtime import COMPONENT, EVENT, SCHEMA, key, record, verify_journal
from server.gen1_run_config import create_runtime, open_runtime, read_configuration
from server.gen1_starter_settlement import COMPONENT as STARTERS
from server.protocol import ProtocolError, digest
from server.protocol_journal import JournalError
from server.state import LinkStatus
from tests.unit.test_gen1_acquisition_runtime import grant
from tests.unit.test_gen1_engine_signal_runtime import deliver as deliver_signals
from tests.unit.test_gen1_faint_runtime import ack, acknowledgement, paired, signal_batch
from tests.unit.test_gen1_initial_observation import admit, observation, send
from tests.unit.test_gen1_inventory_observation import deliver as deliver_inventory
from tests.unit.test_gen1_sessions import contract
from tests.unit.test_gen1_starter_settlement import enroll, source_and_checkpoint

INSTANCE = {"a": "1" * 32, "b": "2" * 32}


def batch(runtime, player, sequence, *, frame, signals=None, acquisitions=(), inventory=None):
    return {"schema": SCHEMA, "event": EVENT, "frame": frame, "sequence": sequence,
            "context": {"context_generation": player * 32, "physical_instance": INSTANCE[player],
                        "save_identity": {"ot_id": "0000", "trainer_name": "SAME"}},
            "rom": runtime.contract["players"][player]["final_rom_sha1"],
            "signals": signals, "acquisitions": list(acquisitions), "inventory": inventory}


def deliver(runtime, player, owner, request, operation=None):
    session = runtime.gate.sessions[player]
    return runtime.process({"protocol": runtime.protocol, "player": player, "session_id": session.session_id,
        "admission_epoch": runtime.gate.epoch, "seq": session.last_seq + 1,
        "operation_id": operation or secrets.token_hex(16), **request}, owner)


def publish(runtime, player, owner, request):
    """Deliver one batch and return its committed result; the transport reply carries no result."""
    operation = secrets.token_hex(16)
    deliver(runtime, player, owner, request, operation)
    return operation, runtime.journal.event_snapshot(player, operation).result


def enrolled(runtime, player, *, occupied=False):
    owner = admit(runtime, player)
    initial = observation(runtime, player, occupied=occupied)
    first = secrets.token_hex(16)
    send(runtime, player, owner, initial, first)
    return owner, initial, first


def checkpoint(initial, frame, party_hex=None):
    point = copy.deepcopy(initial)
    point["frame"] = frame
    if party_hex is not None:
        point["source"]["fields"]["party"] = party_hex
    return point


def progress(runtime, player):
    return runtime.state().document()["components"].get(COMPONENT, {}).get(player)


def acquisitions(runtime, player):
    return runtime.state().document()["components"].get(ACQUISITIONS, {}).get(player)


def test_sequence_must_be_contiguous_and_a_refused_batch_commits_nothing(tmp_path):
    runtime = create_runtime(tmp_path, contract("yellow", "yellow"), free_service=True)
    try:
        owner, initial, _ = enrolled(runtime, "a")
        operation = secrets.token_hex(16)
        deliver(runtime, "a", owner, batch(runtime, "a", 1, frame=130, inventory=checkpoint(initial, 130)), operation)
        assert progress(runtime, "a") == {"sequence": 1, "operation_id": operation, "frame": 130}
        assert runtime.journal.record(COMPONENT, key("a")).value == progress(runtime, "a")
        before = runtime.journal.snapshot()
        with pytest.raises(JournalError, match="sequence skipped or repeated"):
            record(runtime, "a", secrets.token_hex(16), batch(runtime, "a", 3, frame=160))
        with pytest.raises(JournalError, match="sequence skipped or repeated"):
            record(runtime, "a", secrets.token_hex(16), batch(runtime, "a", 1, frame=160))
        with pytest.raises(JournalError, match="frame moved backwards"):
            record(runtime, "a", secrets.token_hex(16), batch(runtime, "a", 2, frame=130))
        assert runtime.journal.snapshot() == before
        deliver(runtime, "a", owner, batch(runtime, "a", 2, frame=160))
        assert progress(runtime, "a")["sequence"] == 2 and progress(runtime, "b") is None
        verify_journal(runtime.journal, runtime.state())
    finally:
        runtime.close()


def test_replay_returns_the_committed_result_without_a_second_commit(tmp_path):
    runtime = create_runtime(tmp_path, contract("red", "blue"), free_service=True)
    try:
        owner, initial, _ = enrolled(runtime, "a", occupied=True)
        operation = secrets.token_hex(16)
        request = batch(runtime, "a", 1, frame=130, inventory=checkpoint(initial, 130))
        first = deliver(runtime, "a", owner, request, operation)
        snapshot = runtime.journal.snapshot()
        again = deliver(runtime, "a", owner, request, operation)  # a fresh transport seq, the same semantic event
        assert {k: v for k, v in again.items() if k != "seq"} == {k: v for k, v in first.items() if k != "seq"}
        assert runtime.journal.snapshot() == snapshot
        entry = runtime.journal.record(INVENTORY, inventory_key("a")).value
        assert record(runtime, "a", operation, request) == {
            "ack": "ACK", "ordinary_execution": False, "inventory_transition_digest": digest(entry),
            "observation_digest": digest(progress(runtime, "a"))}
        with pytest.raises(JournalError, match="different semantic content"):
            record(runtime, "a", operation, {**request, "frame": 131})
        assert runtime.journal.snapshot() == snapshot
    finally:
        runtime.close()


@pytest.mark.parametrize("cause", ["battle_faint", "poison_faint"])
def test_faint_signal_settles_exactly_as_the_standalone_engine_event(tmp_path, cause):
    def settle(directory, publish):
        runtime = create_runtime(directory, contract("red", "blue"), free_service=True)
        try:
            owners = paired(runtime)
            value = signal_batch(runtime, "a", cause=cause)
            publish(runtime, owners["a"], value)
            document = runtime.state().document()
            deaths = document["components"][FAINTS]["deaths"]
            assert len(deaths) == 1
            death = next(iter(deaths.values()))
            engine = death.pop("engine_record")
            assert engine["payload"] == value and [row["kind"] for row in engine["transactions"]] == ["pokeballs_obtained", "faint"]
            pending = [runtime.journal.command("b", row["command_id"])["body"] for row in runtime.journal.pending("b")]
            links = [(link["status"], link["area_id"], link["a"]["key"], link["b"]["key"]) for link in document["rules"]["core"]["links"]]
            party = document["rules"]["runtime"]["party_keys"]
            fixed = {name: death[name] for name in death if name not in ("at", "link_id", "members")}
            return fixed, links, party, [(body["cmd"], body["key"], body.get("player")) for body in pending]
        finally:
            runtime.close()

    standalone = settle(tmp_path / "standalone", lambda runtime, owner, value: deliver_signals(runtime, "a", owner, value))
    observed = settle(tmp_path / "observed",
                      lambda runtime, owner, value: deliver(runtime, "a", owner, batch(runtime, "a", 1, frame=121, signals=value)))
    assert observed == standalone
    death, links, party, commands = observed
    assert death["phase"] == "pending_faint" and death["peer"] == "b"
    assert links[0][0] == LinkStatus.DEAD.value and not party["a"] and not party["b"]
    assert [command[0] for command in commands] == ["force_faint"]


def test_heartbeat_inventory_records_the_checkpoint_and_chains_from_the_previous_batch(tmp_path):
    runtime = create_runtime(tmp_path, contract("yellow", "red"), free_service=True)
    try:
        owner, initial, first = enrolled(runtime, "a", occupied=True)
        point = checkpoint(initial, 130)
        party = bytearray.fromhex(point["source"]["fields"]["party"])
        party[9:11] = b"\0\0"
        point["source"]["fields"]["party"] = party.hex().upper()
        operation, result = publish(runtime, "a", owner, batch(runtime, "a", 1, frame=130, inventory=point))
        entry = runtime.state().document()["components"][INVENTORY]["a"]
        assert entry["sequence"] == 1 and entry["previous_operation_id"] == first and entry["observation"] == point
        assert len(entry["transition"]["party_hp_zero"]) == 1
        assert runtime.journal.record(INVENTORY, inventory_key("a")).value == entry
        assert result["inventory_transition_digest"] == digest(entry) and "inventory_deferred" not in result
        deliver(runtime, "a", owner, batch(runtime, "a", 2, frame=160, inventory=checkpoint(point, 160)))
        entry = runtime.state().document()["components"][INVENTORY]["a"]
        assert entry["sequence"] == 2 and entry["previous_operation_id"] == operation  # chained through the batch
        assert entry["transition"]["party_hp_zero"] == []
        assert len(runtime.journal.record_history(INVENTORY, inventory_key("a"))) == 2
        state = runtime.state()
        verify_journal(runtime.journal, state)
        saved = state.document()["components"]
    finally:
        runtime.close()
    reopened = open_runtime(tmp_path)
    try:
        components = reopened.state().document()["components"]
        assert components[INVENTORY] == saved[INVENTORY] and components[COMPONENT] == saved[COMPONENT]
    finally:
        reopened.close()


def test_acquisition_receipt_settles_pending_or_in_the_same_batch_as_its_checkpoint(tmp_path):
    runtime = create_runtime(tmp_path, contract("yellow", "yellow"), free_service=True)
    try:
        owners, initials, receipts = {}, {}, {}
        for player in ("a", "b"):
            owners[player], initials[player], _ = enrolled(runtime, player)
            receipts[player] = grant(runtime, player, "grant:eevee:0")

        def stable(player, frame):
            return checkpoint(initials[player], frame, receipts[player]["receipt"]["return"]["point"]["party_hex"])

        # a: the receipt arrives first and stays pending until a checkpoint at or after its return frame.
        deliver(runtime, "a", owners["a"], batch(runtime, "a", 1, frame=150, acquisitions=[receipts["a"]]))
        row = acquisitions(runtime, "a")
        assert len(row["pending"]) == 1 and row["settled"] == [] and ORDINALS not in runtime.state().document()["components"]
        deliver(runtime, "a", owners["a"], batch(runtime, "a", 2, frame=200, inventory=stable("a", 200)))
        row = acquisitions(runtime, "a")
        assert row["pending"] == [] and len(row["settled"]) == 1 and row["settled"][0]["link_id"] is None
        # b: receipt and heartbeat checkpoint in ONE batch; inventory is staged first, so it settles at once.
        # (A checkpoint committed before its receipt cannot prove it: the verifier orders them by revision.)
        _, result = publish(runtime, "b", owners["b"], batch(runtime, "b", 1, frame=200, acquisitions=[receipts["b"]],
                                                              inventory=stable("b", 200)))
        assert {"inventory_transition_digest", "acquisition_digest", "observation_digest"} <= set(result)
        row = acquisitions(runtime, "b")
        assert row["pending"] == [] and len(row["settled"]) == 1 and row["settled"][0]["link_id"] is not None
        for player in ("a", "b"):
            settled = acquisitions(runtime, player)["settled"][0]
            assert settled["pairing_key"] == "grant:eevee:0#1" and settled["area"] == "celadon_mansion_roof"
            assert settled["violation"] is None and settled["inventory_operation"] == progress(runtime, player)["operation_id"]
        state = runtime.state()
        document = state.document()
        assert document["components"][ORDINALS] == {"grant:eevee:0": {"a": 1, "b": 1}}
        links = document["rules"]["core"]["links"]
        assert len(links) == 1 and links[0]["status"] == LinkStatus.ALIVE.value and links[0]["area_id"] == "celadon_mansion_roof"
        verify_acquisition_state(state)
        verify_acquisitions(runtime.journal, state)
        verify_journal(runtime.journal, state)
        saved = document["components"]
    finally:
        runtime.close()
    reopened = open_runtime(tmp_path)
    try:
        stage = reopened.state()
        components = stage.document()["components"]
        assert components[ACQUISITIONS] == saved[ACQUISITIONS] and components[COMPONENT] == saved[COMPONENT]
        verify_acquisitions(reopened.journal, stage)
    finally:
        reopened.close()


def test_starter_source_and_checkpoint_settle_through_observation_batches(tmp_path):
    runtime = create_runtime(tmp_path, contract("red", "yellow"), free_service=True)
    try:
        instant = runtime.clock()
        runtime.clock = lambda: instant
        owners, initials, operations = enroll(runtime)
        for player in ("a", "b"):
            source, stable = source_and_checkpoint(runtime, player, initials[player], operations[player])
            deliver(runtime, player, owners[player], batch(runtime, player, 1, frame=105, signals=source))
            assert player in runtime.state().document()["components"][STARTERS]["sources"]
            deliver(runtime, player, owners[player], batch(runtime, player, 2, frame=110, inventory=stable["observation"]))
        state = runtime.state()
        assert set(state.document()["components"][STARTERS]["settled"]) == {"a", "b"}
        assert len(state.rules.links) == 1 and state.rules.links[0].status == LinkStatus.ALIVE
        assert state.barrier.ticket() is None
    finally:
        runtime.close()


def test_heartbeat_inventory_is_deferred_while_any_physical_obligation_is_open(tmp_path):
    runtime = create_runtime(tmp_path, contract("yellow", "yellow"), free_service=True)
    try:
        instant = runtime.clock()
        runtime.clock = lambda: instant
        owners, initials, operations = enroll(runtime)
        points = {}
        for player in ("a", "b"):
            source, stable = source_and_checkpoint(runtime, player, initials[player], operations[player])
            deliver_signals(runtime, player, owners[player], source)
            deliver_inventory(runtime, player, owners[player], stable)
            points[player] = stable["observation"]
        deliver(runtime, "a", owners["a"], batch(runtime, "a", 1, frame=121, signals=signal_batch(runtime, "a")))
        assert runtime.journal.pending_ids("b") and not runtime.journal.pending_ids("a")
        sequences = {p: runtime.state().document()["components"][INVENTORY][p]["sequence"] for p in ("a", "b")}
        for player, frame in (("b", 125), ("a", 126)):
            _, result = publish(runtime, player, owners[player], batch(runtime, player, 1 if player == "b" else 2, frame=frame,
                                                                      inventory=checkpoint(points[player], frame)))
            assert result["inventory_deferred"] is True and "inventory_transition_digest" not in result
        assert {p: runtime.state().document()["components"][INVENTORY][p]["sequence"] for p in ("a", "b")} == sequences
        command = runtime.journal.command("b", runtime.journal.pending_ids("b")[0])
        ack(runtime, "b", owners["b"], acknowledgement(runtime, "b", command))
        # The physical faint closed, but its memorial obligations opened: the checkpoint stays deferred
        # until every obligation has its receipt, exactly as the standalone stream would refuse it.
        pending = [runtime.journal.command("b", identifier)["body"] for identifier in runtime.journal.pending_ids("b")]
        assert pending and all("death_id" in body and body["cmd"] != "force_faint" for body in pending)
        fainted = checkpoint(points["b"], 140)
        party = bytearray.fromhex(fainted["source"]["fields"]["party"])
        party[9:11] = b"\0\0"
        fainted["source"]["fields"]["party"] = party.hex().upper()
        _, result = publish(runtime, "b", owners["b"], batch(runtime, "b", 2, frame=140, inventory=fainted))
        assert result["inventory_deferred"] is True
        assert runtime.state().document()["components"][INVENTORY]["b"]["sequence"] == sequences["b"]
        verify_journal(runtime.journal, runtime.state())
    finally:
        runtime.close()


@pytest.mark.parametrize("fault", ["rom", "generation", "instance", "identity", "kind", "shape", "enrollment"])
def test_hostile_batches_commit_nothing(tmp_path, fault):
    runtime = create_runtime(tmp_path, contract("blue", "yellow"), free_service=True)
    try:
        owner, initial, _ = enrolled(runtime, "a")
        request = batch(runtime, "a", 1, frame=130, inventory=checkpoint(initial, 130))
        player = "a"
        if fault == "rom":
            request["rom"] = "f" * 40
        elif fault == "generation":
            request["context"]["context_generation"] = "f" * 32
        elif fault == "instance":
            request["context"]["physical_instance"] = "f" * 32
        elif fault == "identity":
            request["context"]["save_identity"]["ot_id"] = "0001"
        elif fault == "kind":
            request["acquisitions"] = [{"kind": "wild_begin", "receipt": {}}]
        elif fault == "shape":
            del request["inventory"]
        else:
            admit(runtime, "b")
            player = "b"
            request = batch(runtime, "b", 1, frame=130)
        before = runtime.journal.snapshot()
        with pytest.raises(JournalError):
            record(runtime, player, secrets.token_hex(16), request)
        assert runtime.journal.snapshot() == before and progress(runtime, "a") is None
    finally:
        runtime.close()


def test_free_service_selection_persists_routes_and_ships_the_loop(tmp_path):
    runtime = create_runtime(tmp_path / "free", contract("red", "red"), free_service=True)
    try:
        assert runtime.free_service and read_configuration(tmp_path / "free")["free_service"] is True
        config = configuration(runtime, "a")
        files = {row["path"] for row in config["files"]}
        assert config["mode"] == "free_service" and set(FREE_FILES) <= files
        assert "lua/gen1_observation_loop.lua" in files
    finally:
        runtime.close()
    reopened = open_runtime(tmp_path / "free")
    try:
        assert reopened.free_service is True
        assert configuration(reopened, "b")["mode"] == "free_service"
    finally:
        reopened.close()
    held = create_runtime(tmp_path / "held", contract("red", "red"))
    try:
        assert held.free_service is False and "free_service" not in read_configuration(tmp_path / "held")
        assert configuration(held, "a")["mode"] == "held_service" and "lua/gen1_observation_loop.lua" not in {
            row["path"] for row in configuration(held, "a")["files"]}
        owner, initial, _ = enrolled(held, "a")
        before = held.journal.snapshot()
        with pytest.raises(ProtocolError, match="not selected"):
            deliver(held, "a", owner, batch(held, "a", 1, frame=130, inventory=checkpoint(initial, 130)))
        assert held.journal.snapshot() == before
    finally:
        held.close()
    # A run prepared for the retired frame-credit mode cannot be served any more.
    from server.json_files import atomic_write_json
    from server.gen1_run_config import FILENAME

    stale = read_configuration(tmp_path / "held")
    stale["ordinary_frames"] = True
    atomic_write_json(tmp_path / "held" / FILENAME, stale)
    with pytest.raises(JournalError, match="unsupported prepared"):
        open_runtime(tmp_path / "held")
