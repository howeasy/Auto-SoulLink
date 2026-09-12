"""Actual source/PC/observation/held-ACK interleavings; synthetic cartridge and file proofs."""

import copy
import secrets

import pytest

from server.gen1_faint_runtime import (
    COMPONENT,
    acknowledge as acknowledge_faint,
    verify_journal,
    verify_state,
)
from server.gen1_run_config import create_runtime, open_runtime
from server.gen1_storage import expected
from server.protocol_journal import JournalError
from tests.unit.observation_fixture import commit, observe, starters
from tests.unit.test_gen1_faint_runtime import signal_batch
from tests.unit.test_gen1_hud_feedback import acknowledge_hud
from tests.unit.test_gen1_sessions import contract
from tests.unit.test_gen1_storage_runtime import COMPONENT as STORAGE, read, source, spare, write


def finish_faint(runtime, command, job_id):
    from server.gen1_held_faint import SCHEMA, verify
    from server.gen1_initial_observation import inventory
    from server.gen1_party_codec import PartyCodec
    from tests.unit.test_gen1_held_faint import checkpoint

    document = runtime.state().document()
    initial = document["components"]["gen1-initial-observations"]["b"]
    from server.gen1_storage_runtime import expand_entry
    saved = expand_entry(runtime.journal, document["components"][STORAGE]["jobs"][job_id])["prepared"]["b"]
    variant = saved["after"]["variant"]
    codec = PartyCodec(variant)
    party = [
        row["blob_hex"]
        for row in inventory(saved["after"], runtime.state().rules.player_identity["b"])["members"]
        if row["location"] == "party"
    ]
    slot = next(
        i
        for i, blob in enumerate(party)
        if codec.validate_blob(bytes.fromhex(blob)).key == command["body"]["key"]
    )
    assert slot == 1  # Canonical withdrawal appended it after the surviving spare.
    before = {
        "schema": "gen1-party-readback-v1",
        "variant": variant,
        "save_id": "0000",
        "save_name": "SAME",
        "party_count": len(party),
        "party": party,
        "species_list": [bytes.fromhex(blob)[0] for blob in party] + [255],
        "battle_flag": 0,
        "active_slot": None,
        "battle_hp": None,
    }
    after = copy.deepcopy(before)
    raw = bytearray.fromhex(after["party"][slot])
    raw[1:3] = bytes(2)
    after["party"][slot] = raw.hex().upper()
    evidence = {
        "schema": SCHEMA,
        "command_id": command["command_id"],
        "command_sequence": command["command_sequence"],
        "context_generation": "b" * 32,
        "final_sha1": initial["observation"]["final_sha1"],
        "host": {**initial["observation"]["host"], "frame": saved["frame"]},
        "checkpoint": checkpoint(variant),
        "intent": {
            "schema": "gen1-force-faint-intent-v1",
            "before": before,
            "after": after,
            "slot": slot,
        },
        "current": before,
    }
    assert verify(
        "b", command, evidence, document, runtime.gate.sessions["b"].metadata["control_binding"]
    )
    message = {
        "event": "command_ack",
        "command_id": command["command_id"],
        "command_sequence": command["command_sequence"],
        "outcome": "ACK",
        "receipt": {"schema": "gen1-force-faint-receipt-v1", "before": before, "after": after},
    }
    operation = secrets.token_hex(16)
    result = acknowledge_faint(runtime, "b", operation, message)
    snapshot = runtime.journal.snapshot()
    assert (
        acknowledge_faint(runtime, "b", operation, message) == result
        and runtime.journal.snapshot() == snapshot
    )
    # Build the exact reconciliation baseline while memorial still holds frames.
    # The deferred FF belongs to the storage ACK issuer, not the engine event.
    from server.gen1_authorized_inventory import build, predecessor_receipt, replay

    document = runtime.state().document()
    previous = document["components"]["gen1-inventory-observations"]["b"]
    observed = copy.deepcopy(previous["observation"])
    observed["source"] = copy.deepcopy(saved["after"])
    observed["frame"] = saved["frame"]
    raw = bytearray.fromhex(observed["source"]["fields"]["party"])
    raw[8 + slot * 44 + 1 : 8 + slot * 44 + 3] = bytes(2)
    observed["source"]["fields"]["party"] = raw.hex().upper()
    prior = predecessor_receipt(runtime.journal, "b", initial, previous)
    plan = build(
        runtime.journal,
        document,
        "b",
        previous["observation"],
        observed,
        after_revision=prior.revision,
        through_revision=runtime.journal.snapshot().revision,
    )
    assert [r["reference"]["kind"] for r in plan["writes"]] == ["storage_apply", "force_faint"]
    assert replay(previous["observation"]["source"], plan)[1] == observed["source"]


def in_flight(runtime):
    starters(runtime)
    spare(runtime, "a")
    spare(runtime, "b")
    keys = {p: getattr(runtime.state().rules.links[0], p).key for p in ("a", "b")}
    point = source(runtime, "b")
    point["frame"] += 1
    point["source"] = expected(
        point["source"], keys["b"], "deposit", identity=runtime.state().rules.player_identity["b"]
    )
    commit(runtime, "b", [], point=point)
    job = next(iter(runtime.state().document()["components"][STORAGE]["jobs"].values()))
    return keys, job["id"]


def close_faint(runtime, cause="poison_faint"):
    """The source faint arrives while both storage reads are open: signals settle, the heartbeat waits."""
    payload = signal_batch(runtime, "a", cause=cause)
    payload["signals"][0]["frame"] = 125
    payload["signals"][1]["frame"] = 126
    point = source(runtime, "a")
    party = bytearray.fromhex(point["source"]["fields"]["party"])
    party[9:11] = bytes(2)
    if cause == "poison_faint":
        party[12] = 8
    payload["signals"][1]["point"]["party_hex"] = party.hex().upper()
    return observe(runtime, "a", signals=payload, frame=130)


@pytest.mark.parametrize("read_receiver_first", [False, True])
def test_real_death_is_recorded_but_force_faint_waits_for_storage_compensation(
    tmp_path, read_receiver_first
):
    runtime = create_runtime(tmp_path, contract("yellow", "yellow"))
    try:
        keys, job_id = in_flight(runtime)
        if read_receiver_first:
            read(runtime, "b")
        source_operation, _, _ = close_faint(runtime)
        document = runtime.state().document()
        death_id, death = next(iter(document["components"][COMPONENT]["deaths"].items()))
        assert death["phase"] == "pending_issue"
        assert not any(
            runtime.journal.command(p, key)["body"]["cmd"] == "force_faint"
            for p in ("a", "b")
            for key in runtime.journal.pending_ids(p)
        )
        if not read_receiver_first:
            read(runtime, "b")
        read(runtime, "a")
        job = runtime.state().document()["components"][STORAGE]["jobs"][job_id]
        assert (
            job["death_abort"] == death_id
            and job["resolution"]["refusal"] == "linked-death-before-storage-write"
        )
        acknowledge_hud(runtime)  # no-write UI can settle before the newly queued storage writes
        write(runtime, "a")
        assert (
            runtime.state().document()["components"][COMPONENT]["deaths"][death_id]["phase"]
            == "pending_issue"
        )
        write(runtime, "b")
        document = runtime.state().document()
        death = document["components"][COMPONENT]["deaths"][death_id]
        assert death["phase"] == "pending_faint"
        command = runtime.journal.command("b", runtime.journal.pending_ids("b")[0])
        assert command["body"]["cmd"] == "force_faint" and command["body"]["key"] == keys["b"]
        assert (
            command["command_id"]
            not in runtime.journal.event_snapshot("a", source_operation).command_ids
        )
        assert (
            death["deferred"]["origin"]
            == document["components"][STORAGE]["jobs"][job_id]["writes"]["b"]
        )
        assert all(keys[p] not in runtime.state().rules.party_keys[p] for p in ("a", "b"))
        verify_state(runtime.state())
        verify_journal(runtime.journal, runtime.state())
        from server import event_reference
        from server.gen1_runtime_state import Gen1RuntimeState

        for fault in ("original_source_as_issuer", "erased_issuance"):
            changed = copy.deepcopy(document)
            row = changed["components"][COMPONENT]["deaths"][death_id]
            if fault == "original_source_as_issuer":
                original = runtime.journal.event_snapshot("a", source_operation)
                row["deferred"]["origin"] = event_reference.make(
                    "a", source_operation, original.request
                )
            else:
                row["phase"] = "pending_issue"
                row["deferred"]["origin"] = None
            with pytest.raises(JournalError):
                forged = Gen1RuntimeState(changed, data_dir=runtime.data_dir)
                verify_journal(runtime.journal, forged)
        finish_faint(runtime, command, job_id)
        assert (
            runtime.state().document()["components"][COMPONENT]["deaths"][death_id]["phase"]
            == "pending_memorial"
        )
    finally:
        runtime.close()
    reopened = open_runtime(tmp_path)
    try:
        verify_journal(reopened.journal, reopened.state())
    finally:
        reopened.close()


def test_open_storage_reads_and_writes_defer_the_heartbeat_checkpoint(tmp_path):
    runtime = create_runtime(tmp_path, contract("red", "blue"))
    try:
        _, job_id = in_flight(runtime)
        point = source(runtime, "a")
        point["frame"] = 130
        _, _, result = observe(runtime, "a", inventory=point, allow_deferred=True)
        assert result["inventory_deferred"] is True and "inventory_transition_digest" not in result
        read(runtime, "b")
        read(runtime, "a")
        assert runtime.state().document()["components"][STORAGE]["jobs"][job_id]["prepared"]
        point["frame"] = 131
        _, _, result = observe(runtime, "a", inventory=point, allow_deferred=True)
        assert result["inventory_deferred"] is True  # the storage_apply commands are still open
        assert runtime.state().document()["components"]["gen1-inventory-observations"]["a"]["observation"]["frame"] < 130
    finally:
        runtime.close()
