"""Shared persistence with one captured RR record and synthetic rule/transport events.

No emulator or physical command runs here. The partner link is a rule fixture,
not a claim that a second game was captured or that this Pokémon fainted.
"""
import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from server.adapters import get_adapter
from server.binary_codec import decode_bytes, encode_bytes
from server.durable_dispatch import DurableDispatcher
from server.protocol_journal import JournalError, ProtocolJournal
from server.staged_state import StagedSoulLinkState
from server.state import AreaStatus, LinkEntry, LinkStatus, MonInfo, SoulLinkState
from tests.unit.test_client_journal import accepted, start
from tests.unit.test_client_state_store import runtime  # noqa: F401

FIXTURE = Path(__file__).resolve().parents[1] / "rr/reference/fixtures/field_party_08_a.json"
A, B = "EBEF11DA:2BDDC8BF", "00000002:00000003"


@pytest.fixture
def captured():
    evidence = json.loads(FIXTURE.read_text(encoding="utf8"))
    raw = bytes.fromhex(evidence["raw_hex"])
    assert len(raw) == 100
    assert hashlib.sha256(raw).hexdigest() == evidence["raw_sha256"] == (
        "b9133a60d0c484c4477aadf5e2acd18082c4ce84b735afa285ed2ec98be2490c")
    assert int.from_bytes(raw[:4], "little") == 0xEBEF11DA
    assert int.from_bytes(raw[4:8], "little") == 0x2BDDC8BF
    assert int.from_bytes(raw[0x20:0x22], "little") == 277
    assert evidence["observed_scene"]["callback2"] == 0x080565B5
    assert evidence["release_ready"] is False
    return raw


def initial_state(tmp_path, raw):
    state = SoulLinkState(data_dir=str(tmp_path), adapter=get_adapter("gen3_frlge", is_rr=True), is_rr=True)
    state.rom_type = "firered_rr"
    pair = LinkEntry("route_1", MonInfo(A, 6, 277, "Treecko"), MonInfo(B, 6, 280, "Synthetic peer"), LinkStatus.ALIVE)
    state.links.append(pair)
    state._index_entry(pair)
    state.area_states["route_1"] = AreaStatus.LINKED
    state.party_keys = {"a": {A}, "b": {B}}
    state.party_size = {"a": 1, "b": 1}
    state._has_helld = {"a", "b"}
    state.pokeballs_obtained = {"a": True, "b": True}
    # The actual ingestion path produces a bytes-valued RR party cache.
    state._ingest_party_blobs("a", [{"slot": 0, "key": A, "species_id": 277,
                                     "level": 6, "blob_hex": raw.hex()}])
    return StagedSoulLinkState.from_live(state, {"retired_pairs": []})


def dispatcher_for(journal, tmp_path):
    def event_validator(player, event, state):
        if player != "a" or event != {"event": "faint", "key": A}:
            raise JournalError("synthetic RR rule fixture refused event")
    def receipt_validator(*args):
        raise JournalError("this byte-fidelity test has no physical receipt evidence")
    return DurableDispatcher(journal, data_dir=tmp_path,
                             validate_event=event_validator, validate_receipt=receipt_validator)


def test_captured_rr_record_survives_staging_rule_commit_restart_and_exact_retry(tmp_path, captured):
    initial = initial_state(tmp_path, captured)
    document = initial.document()
    encoded = document["runtime"]["partner_blobs"]["a"][0]["blob"]
    assert decode_bytes(encoded, expected_size=100) == captured
    journal = ProtocolJournal(tmp_path / "rr.db", run_id="a" * 32, contract_hash="b" * 64)
    try:
        journal.bootstrap(document)
        dispatcher = dispatcher_for(journal, tmp_path)
        event = {"event": "faint", "key": A}
        dispatcher.dispatch("a", "c" * 32, event)
        outboxes = {p: journal.pending(p) for p in ("a", "b")}
        assert outboxes["a"] and outboxes["b"]
        assert any(c["cmd"] == "force_faint" and c["key"] == B for c in outboxes["b"])
        assert dispatcher.state().links[0].status == LinkStatus.DEAD
        assert dispatcher.state().partner_blobs["a"][0]["blob"] == captured
        journal.close()
        journal = ProtocolJournal(tmp_path / "rr.db", run_id="a" * 32, contract_hash="b" * 64)
        dispatcher = dispatcher_for(journal, tmp_path)
        dispatcher.validate_event = lambda *_: pytest.fail("exact retry repeated RR rules")
        assert dispatcher.dispatch("a", "c" * 32, event).replayed
        assert {p: journal.pending(p) for p in ("a", "b")} == outboxes
        assert dispatcher.state().partner_blobs["a"][0]["blob"] == captured
        assert type(dispatcher.state().partner_blobs["a"][0]["blob"]) is bytes
        assert not (tmp_path / "links.json").exists()
    finally:
        journal.close()


def test_rr_payload_and_both_outboxes_are_not_published_on_failed_commit(tmp_path, captured):
    journal = ProtocolJournal(tmp_path / "rr.db", contract_hash="b" * 64)
    try:
        journal.bootstrap(initial_state(tmp_path, captured).document())
        before = journal.snapshot()
        journal._db.execute("CREATE TEMP TRIGGER fail_rr BEFORE INSERT ON events BEGIN SELECT RAISE(ABORT,'injected');END")
        with pytest.raises(sqlite3.IntegrityError):
            dispatcher_for(journal, tmp_path).dispatch("a", "c" * 32, {"event": "faint", "key": A})
        assert journal.snapshot() == before
        assert not journal.pending("a") and not journal.pending("b")
        assert dispatcher_for(journal, tmp_path).state().partner_blobs["a"][0]["blob"] == captured
    finally:
        journal.close()


def test_exception_after_rr_commit_recovers_without_repeating_transition(tmp_path, captured):
    journal = ProtocolJournal(tmp_path / "rr.db", contract_hash="b" * 64)
    try:
        journal.bootstrap(initial_state(tmp_path, captured).document())
        original = journal.commit
        def uncertain(*args, **kwargs):
            original(*args, **kwargs)
            raise OSError("response lost after RR state commit")
        journal.commit = uncertain
        dispatcher = dispatcher_for(journal, tmp_path)
        event = {"event": "faint", "key": A}
        with pytest.raises(OSError):
            dispatcher.dispatch("a", "c" * 32, event)
        journal.commit = original
        assert dispatcher.dispatch("a", "c" * 32, event).replayed
        assert journal.snapshot().revision == 1
        assert dispatcher.state().partner_blobs["a"][0]["blob"] == captured
    finally:
        journal.close()


def test_stored_refusal_can_retain_exact_rr_bytes_without_claiming_game_effect(tmp_path, captured):
    journal = ProtocolJournal(tmp_path / "rr.db", contract_hash="b" * 64)
    try:
        journal.bootstrap(initial_state(tmp_path, captured).document())
        dispatcher_for(journal, tmp_path).dispatch("a", "c" * 32, {"event": "faint", "key": A})
        command = journal.pending("b")[0]
        receipt = {"schema": "synthetic-storage-kernel-fixture-v1", "record": encode_bytes(captured),
                   "reason": "unit fixture did not execute the physical operation"}
        journal.acknowledge("b", command["command_id"], "NACK", receipt)
        stored = journal.command("b", command["command_id"])
        assert stored["outcome"] == "NACK"
        assert decode_bytes(stored["receipt"]["record"], expected_size=100) == captured
        journal.acknowledge("b", command["command_id"], "NACK", receipt)
        with pytest.raises(JournalError):
            journal.acknowledge("b", command["command_id"], "NACK", receipt | {"reason": "changed"})
    finally:
        journal.close()


def test_captured_rr_bytes_cross_atomic_client_observation_baseline_inbox_and_receipt(runtime, captured):  # noqa: F811
    lua = runtime
    start(lua)
    raw_hex = captured.hex()
    lua.globals().events_json = json.dumps([{"event": "party_observed", "key": A, "blob_hex": raw_hex}])
    lua.globals().baseline_json = json.dumps({"party": {A: {"blob_hex": raw_hex}}})
    lua.execute("ids=assert(journal:append_many(assert(JSON.decode(events_json)),assert(JSON.decode(baseline_json))))")
    operation = lua.globals().ids[1]
    lua.globals().reopen()
    state = lua.globals().state()
    assert state.outbox[1].payload.blob_hex == raw_hex
    assert state.observation.party[A].blob_hex == raw_hex
    echo = {"command_id": "d" * 32, "command_sequence": 1,
            "body": {"cmd": "synthetic_byte_echo", "blob_hex": raw_hex}}
    assert accepted(lua.globals().accept(operation, json.dumps([echo])))
    lua.globals().reopen()
    assert lua.globals().state().inbox[1].body.blob_hex == raw_hex
    proof = {"schema": "byte-echo-only-v1", "blob_hex": raw_hex, "game_effect_executed": False}
    assert accepted(lua.globals().complete("d" * 32, "ACK", json.dumps(proof)))
    lua.globals().reopen()
    state = lua.globals().state()
    assert state.inbox[1].receipt.blob_hex == raw_hex
    assert state.outbox[1].payload.receipt.blob_hex == raw_hex
    assert state.outbox[1].payload.receipt.game_effect_executed is False
