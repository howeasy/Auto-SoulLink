"""Actual frame/storage/retirement journal composition; physical proofs are modeled."""

import copy
import hashlib
import secrets

import pytest

from server import gen1_retirement_runtime as retirement, gen1_wild_encounter_runtime as wild
from server.gen1_frame_journal import returned
from server.gen1_initial_observation import inventory
from server.gen1_retirement import SCHEMA
from server.gen1_run_config import create_runtime, open_runtime
from server.protocol import digest
from server.protocol_journal import JournalError
from tests.unit.test_gen1_atomic_frame_settlement import frame, starters, window
from tests.unit.test_gen1_engine_signal_runtime import payload as engine_payload
from tests.unit.test_gen1_faint_runtime import bag
from tests.unit.test_gen1_frame_acquisitions import checkpoint, commit, party_blobs
from tests.unit.test_gen1_held_faint import checkpoint as held_checkpoint
from tests.unit.test_gen1_inventory_observation import party_point
from tests.unit.test_gen1_sessions import contract
from tests.unit.test_gen1_storage_runtime import complete_storage
from tests.unit.test_gen1_wild_encounter import capture, row


def consume(runtime, player, rows, point):
    variant = runtime.contract["players"][player]["variant"]
    engine = engine_payload(runtime, player, [], 2)
    engine["signals"] = [bag(variant)]
    window(runtime, player, frames=60)
    message = frame(runtime, player, point, engine)
    message["bundle"]["acquisitions"] = rows
    message["receipt"]["observations_digest"] = digest(message["bundle"])
    return returned(runtime, player, secrets.token_hex(16), message, settle_observations=True)


def ack(runtime, receipt):
    message = {
        "event": "command_ack",
        "command_id": receipt["command_id"],
        "command_sequence": receipt["command_sequence"],
        "outcome": "ACK",
        "receipt": receipt,
    }
    operation = secrets.token_hex(16)
    return operation, message, retirement.acknowledge(runtime, "a", operation, message)


@pytest.mark.parametrize("variants", [("yellow", "yellow"), ("red", "blue"), ("blue", "yellow")])
def test_quarantined_capture_is_archived_after_peer_no_catch_and_reopens(tmp_path, variants):
    runtime = create_runtime(tmp_path, contract(*variants))
    try:
        starters(runtime)
        caught = capture(runtime, "a")
        raw = caught["receipt"]["receipt"]
        old = checkpoint(runtime, "a", [], 150)
        prior = old["source"]["fields"]["party"]
        new = party_blobs(raw["end"]["point"]["party_hex"])[0]
        raw["begin"]["frame"], raw["end"]["frame"] = 125, 135
        raw["begin"]["point"]["party_hex"] = prior
        raw["end"]["point"]["party_hex"] = party_point(variants[0], party_blobs(prior) + [new])[
            "fields"
        ]["party"]
        old["source"]["fields"]["party"] = raw["end"]["point"]["party_hex"]
        rows = [row(runtime, "a", "begin", 120), caught, row(runtime, "a", "end", 140)]
        consume(runtime, "a", rows, old)
        physical = complete_storage(runtime)
        assert "a" in physical
        point = checkpoint(runtime, "a", [], 151)
        point["source"] = copy.deepcopy(physical["a"])
        commit(runtime, "a", [], point=point)
        quarantine_transition = runtime.state().document()["components"][
            "gen1-inventory-observations"
        ]["a"]["transition"]
        assert [r["kind"] for r in quarantine_transition["authorized_writes"]] == ["storage_apply"]
        assert all(
            not quarantine_transition[k]
            for k in ("added", "removed", "movements", "party_hp_zero", "changed")
        )
        before = copy.deepcopy(point)

        consume(
            runtime,
            "b",
            [row(runtime, "b", "begin", 120), row(runtime, "b", "end", 140)],
            checkpoint(runtime, "b", [], 150),
        )
        state = runtime.state()
        obligation = next(
            iter(state.document()["components"][wild.COMPONENT]["obligations"].values())
        )
        assert obligation["phase"] == "pending" and obligation["reason"] == "paired_no_catch"
        logical_links = copy.deepcopy(state.rules.links)
        key = obligation["key"]
        assert key not in state.rules.party_keys["a"]
        assert (
            next(
                m
                for m in inventory(point["source"], state.rules.player_identity["a"])["members"]
                if m["key"] == key
            )["location"]
            == "box"
        )
        command = runtime.journal.command("a", runtime.journal.pending_ids("a")[0])
        assert command["body"]["cmd"] == "retirement_observe"
        ack(
            runtime,
            {
                "schema": retirement.OBSERVE,
                "command_id": command["command_id"],
                "command_sequence": command["command_sequence"],
                "context_generation": "a" * 32,
                "final_sha1": point["final_sha1"],
                "host": {**point["host"], "frame": point["frame"]},
                "checkpoint": held_checkpoint(variants[0]),
                "point": copy.deepcopy(point["source"]),
            },
        )
        command = runtime.journal.command("a", runtime.journal.pending_ids("a")[0])
        entry = runtime.state().document()["components"][retirement.COMPONENT]["a"][0]
        prepared = entry["payload"]
        receipt = {
            "schema": SCHEMA,
            "command_id": command["command_id"],
            "command_sequence": command["command_sequence"],
            "body_digest": digest(command["body"]),
            "context_generation": prepared["context_generation"],
            "final_sha1": prepared["final_sha1"],
            "before_digest": digest(prepared["before"]),
            "after": copy.deepcopy(prepared["after"]),
            "file": {
                "schema": "slink-saveram-file-v1",
                "path": "owned/a/SaveRAM/game.sav",
                "byte_length": 0x8000,
                "sha256": hashlib.sha256(bytes.fromhex(prepared["after"]["cart_hex"])).hexdigest(),
                "host_profile": "bizhawk-2.11.1-gambatte-exclusive-hold-v1",
                "frame": prepared["frame"],
                "flushed": True,
                "readback": True,
            },
        }
        bad = copy.deepcopy(receipt)
        bad["file"]["sha256"] = "f" * 64
        snapshot = runtime.journal.snapshot()
        with pytest.raises(JournalError):
            ack(runtime, bad)
        assert runtime.journal.snapshot() == snapshot
        operation, message, result = ack(runtime, receipt)
        snapshot = runtime.journal.snapshot()
        assert retirement.acknowledge(runtime, "a", operation, message) == result
        assert runtime.journal.snapshot() == snapshot
        state = runtime.state()
        assert wild.REASON not in state.barrier.document()["blockers"].values()
        assert state.rules.links == logical_links and not state.rules.pending_memorials["a"]
        archive = next(
            m
            for m in inventory(prepared["after"], state.rules.player_identity["a"])["members"]
            if m["key"] == key
        )
        assert archive["location"] == "box" and archive["box"] == 11
        before["frame"] = 152
        before["source"] = copy.deepcopy(prepared["after"])
        commit(runtime, "a", [], point=before)
        transition = runtime.state().document()["components"]["gen1-inventory-observations"]["a"][
            "transition"
        ]
        assert [r["kind"] for r in transition["authorized_writes"]] == ["acquisition_retire"]
        assert all(
            not transition[k] for k in ("added", "removed", "movements", "party_hp_zero", "changed")
        )
    finally:
        runtime.close()
    runtime = open_runtime(tmp_path)
    try:
        state = runtime.state()
        wild.verify_journal(runtime.journal, state)
        retirement.verify_journal(runtime.journal, state)
        assert (
            next(iter(state.document()["components"][wild.COMPONENT]["obligations"].values()))[
                "phase"
            ]
            == "complete"
        )
        assert not runtime.journal.pending_ids("a") and not runtime.journal.pending_ids("b")
    finally:
        runtime.close()
