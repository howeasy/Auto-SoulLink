"""Real retirement journal transitions with synthetic owned cartridge/file proofs."""

import copy
import hashlib
import secrets
import sqlite3

import pytest

from server.gen1_acquisition_runtime import COMPONENT as ACQUISITIONS, CONSTRAINT_REASON
from server.gen1_full_save import SYMBOLS, image
from server.gen1_grave_reservations import COMPONENT as GRAVES
from server.gen1_initial_observation import inventory
from server.gen1_initial_save_runtime import prepared as initial_saved
from server.gen1_retirement import SCHEMA
from server.gen1_retirement_runtime import (
    COMPONENT,
    EVIDENCE,
    OBSERVE,
    acknowledge,
    expand_entry,
    verify_journal,
    verify_operation,
    verify_state,
)
from server.gen1_run_config import create_runtime, open_runtime
from server.protocol import digest
from server.protocol_journal import JournalError
from tests.unit.observation_fixture import checkpoint as inventory_point, commit, start
from tests.unit.test_gen1_grant_receipt import DATA, receipt as grant_receipt
from tests.unit.test_gen1_held_faint import checkpoint


def acquired(runtime, where="party"):
    start(runtime)
    site = next(
        name for name, row in DATA["titles"]["yellow"]["sites"].items() if row["yellow_only"]
    )
    receipt = grant_receipt(
        "yellow",
        site,
        ot_id="0000",
        existing=1,
        boxed_before=0,
        delivery="box" if where == "grave" else where,
    )
    receipt.update(
        context_generation="a" * 32,
        physical_instance="1" * 32,
        final_sha1=runtime.contract["players"]["a"]["final_rom_sha1"],
    )
    receipt["call"]["frame"] = 110
    receipt["return"]["frame"] = 130
    row = {"kind": "grant", "receipt": receipt}
    point = inventory_point(runtime, "a", [row], 140)
    point["source"]["cart_hex"] = initial_saved(runtime.state().document(), "a")["after"][
        "cart_hex"
    ]
    point["source"]["save_status"] = 2
    if where == "grave":
        from server.gen1_grave_storage import checksum_banks

        for witness in ("call", "return"):
            receipt[witness]["point"]["current_box"] = 139
        main = bytearray.fromhex(point["source"]["fields"]["main"])
        symbols = SYMBOLS["pokeyellow"]
        main[symbols["wCurrentBoxNum"] - symbols["wMainDataStart"]] = 139
        point["source"]["fields"]["main"] = main.hex().upper()
        cart = bytearray.fromhex(point["source"]["cart_hex"])
        for bank in (2, 3):
            for index in range(6):
                cart[bank * 0x2000 + index * 1122 : bank * 0x2000 + index * 1122 + 2] = b"\0\xff"
        checksum_banks(cart, {2, 3})
        saved = copy.deepcopy(point["source"])
        saved["cart_hex"] = cart.hex().upper()
        saved["fields"]["box"] = receipt["call"]["point"]["box_hex"]
        point["source"]["cart_hex"] = image(saved).hex().upper()
    commit(runtime, "a", [row], point=point)
    return runtime.state().document()["components"][COMPONENT]["a"][0]


def observed(runtime):
    command = runtime.journal.command("a", runtime.journal.pending_ids("a")[0])
    document = runtime.state().document()
    source = document["components"]["gen1-inventory-observations"]["a"]["observation"]
    receipt = {
        "schema": OBSERVE,
        "command_id": command["command_id"],
        "command_sequence": command["command_sequence"],
        "context_generation": "a" * 32,
        "final_sha1": source["final_sha1"],
        "host": {**source["host"], "frame": source["frame"]},
        "checkpoint": checkpoint("yellow"),
        "point": copy.deepcopy(source["source"]),
    }
    return command, {
        "event": "command_ack",
        "command_id": command["command_id"],
        "command_sequence": command["command_sequence"],
        "outcome": "ACK",
        "receipt": receipt,
    }


def written(runtime):
    command = runtime.journal.command("a", runtime.journal.pending_ids("a")[0])
    row = runtime.state().document()["components"][COMPONENT]["a"][0]
    p = row["payload"]
    receipt = {
        "schema": SCHEMA,
        "command_id": command["command_id"],
        "command_sequence": command["command_sequence"],
        "body_digest": digest(command["body"]),
        "context_generation": p["context_generation"],
        "final_sha1": p["final_sha1"],
        "before_digest": digest(p["before"]),
        "after": copy.deepcopy(p["after"]),
        "file": {
            "schema": "slink-saveram-file-v1",
            "path": "owned/a/SaveRAM/game.sav",
            "byte_length": 0x8000,
            "sha256": hashlib.sha256(bytes.fromhex(p["after"]["cart_hex"])).hexdigest(),
            "host_profile": "bizhawk-2.11.1-gambatte-exclusive-hold-v1",
            "frame": p["frame"],
            "flushed": True,
            "readback": True,
        },
    }
    return command, {
        "event": "command_ack",
        "command_id": command["command_id"],
        "command_sequence": command["command_sequence"],
        "outcome": "ACK",
        "receipt": receipt,
    }


def contract(peer="red"):
    from tests.unit.test_gen1_sessions import contract as base

    return base("yellow", peer)


@pytest.mark.parametrize("where", ["party", "box", "grave"])
@pytest.mark.parametrize("peer", ["red", "blue"])
def test_retirement_preserves_unlinked_gift_in_grave_and_clears_only_its_constraint_after_file_ack(
    tmp_path, where, peer
):
    runtime = create_runtime(tmp_path, contract(peer))
    try:
        first = acquired(runtime, where)
        assert CONSTRAINT_REASON in runtime.state().barrier.document()["blockers"].values()
        _, read = observed(runtime)
        acknowledge(runtime, "a", secrets.token_hex(16), read)
        stage = runtime.state()
        verify_state(stage)
        verify_journal(runtime.journal, stage)
        command, message = written(runtime)
        operation = secrets.token_hex(16)
        ack = acknowledge(runtime, "a", operation, message)
        saved = runtime.journal.snapshot()
        assert acknowledge(runtime, "a", operation, message) == ack
        assert runtime.journal.snapshot() == saved
        state = runtime.state()
        verify_state(state)
        verify_journal(runtime.journal, state)
        compact = state.document()["components"][COMPONENT]["a"][0]
        assert "retained" in compact and "payload" not in compact
        row = expand_entry(runtime.journal, compact)
        assert row["reason"] == first["reason"] and row["receipt_operation"] == operation
        assert not state.rules.links and not state.rules.pending_memorials["a"]
        assert CONSTRAINT_REASON not in state.barrier.document()["blockers"].values()
        assert state.barrier.ticket() is None and not runtime.journal.pending_ids("a")
        archive = next(
            m
            for m in inventory(row["payload"]["after"], state.rules.player_identity["a"])["members"]
            if m["key"] == row["key"]
        )
        assert (
            archive["location"] == "box"
            and archive["box"] == 11
            and bytes.fromhex(archive["box_blob_hex"])[1:3] == b"\0\0"
        )
        assert state.document()["components"][GRAVES]["a"]["kind"] == "retirement"
        assert (
            state.document()["components"][ACQUISITIONS]["a"]["settled"][0]["rule"]
            == "retirement_required"
        )
    finally:
        runtime.close()
    runtime = open_runtime(tmp_path)
    try:
        verify_journal(runtime.journal, runtime.state())
    finally:
        runtime.close()


@pytest.mark.parametrize("fault", ["file", "image", "key", "frame", "before", "scope"])
def test_bad_completion_or_scope_never_clears_retirement_hold(tmp_path, fault):
    runtime = create_runtime(tmp_path, contract())
    try:
        acquired(runtime)
        _, read = observed(runtime)
        acknowledge(runtime, "a", secrets.token_hex(16), read)
        command, message = written(runtime)
        if fault == "file":
            message["receipt"]["file"]["sha256"] = "f" * 64
        elif fault == "image":
            message["receipt"]["after"]["fields"]["party"] = (
                "00" + message["receipt"]["after"]["fields"]["party"][2:]
            )
        elif fault == "key":
            message["command_id"] = "f" * 32
        elif fault == "frame":
            message["receipt"]["file"]["frame"] += 1
        elif fault == "before":
            message["receipt"]["before_digest"] = "f" * 64
        else:
            message["receipt"]["context_generation"] = "f" * 32
        before = runtime.journal.snapshot()
        with pytest.raises(JournalError):
            acknowledge(runtime, "a", secrets.token_hex(16), message)
        assert (
            runtime.journal.snapshot() == before
            and CONSTRAINT_REASON in runtime.state().barrier.document()["blockers"].values()
        )
    finally:
        runtime.close()


@pytest.mark.parametrize("phase", ["acquisition_retire", "retirement_repair", "retirement_save"])
def test_retirement_uses_exact_single_use_held_image_phase(tmp_path, phase):
    runtime = create_runtime(tmp_path, contract())
    try:
        acquired(runtime)
        _, read = observed(runtime)
        acknowledge(runtime, "a", secrets.token_hex(16), read)
        command, _ = written(runtime)
        p = runtime.state().document()["components"][COMPONENT]["a"][0]["payload"]
        current = copy.deepcopy(p["after"] if phase == "retirement_save" else p["before"])
        if phase == "retirement_repair":
            change = command["body"]["payload"]["changes"]["cart"]["runs"][0]
            raw = bytearray.fromhex(current["cart_hex"])
            raw[change["offset"]] = bytes.fromhex(change["after"])[0]
            current["cart_hex"] = raw.hex().upper()
        evidence = {
            "schema": EVIDENCE,
            "command_id": command["command_id"],
            "command_sequence": command["command_sequence"],
            "context_generation": p["context_generation"],
            "final_sha1": p["final_sha1"],
            "host": read["receipt"]["host"],
            "checkpoint": read["receipt"]["checkpoint"],
            "intent": {
                "schema": "rby-retirement-intent-v1",
                "body_digest": digest(command["body"]),
            },
            "current": current,
            "phase": phase,
        }
        proof = verify_operation(
            "a",
            command,
            evidence,
            runtime.state().document(),
            runtime.gate.sessions["a"].metadata["control_binding"],
        )
        assert proof.scope["phase"] == phase and proof.ttl_ms == 1000
    finally:
        runtime.close()


def test_sql_failure_leaves_physical_ack_and_constraint_uncommitted(tmp_path):
    runtime = create_runtime(tmp_path, contract())
    try:
        acquired(runtime)
        _, read = observed(runtime)
        acknowledge(runtime, "a", secrets.token_hex(16), read)
        _, message = written(runtime)
        before = runtime.journal.snapshot()
        runtime.journal._db.execute(
            "CREATE TRIGGER fail_retirement BEFORE INSERT ON records BEGIN SELECT RAISE(ABORT,'fixture'); END"
        )
        with pytest.raises(sqlite3.DatabaseError):
            acknowledge(runtime, "a", secrets.token_hex(16), message)
        assert runtime.journal.snapshot() == before
    finally:
        runtime.close()
    runtime = open_runtime(tmp_path)
    try:
        assert CONSTRAINT_REASON in runtime.state().barrier.document()["blockers"].values()
        verify_journal(runtime.journal, runtime.state())
    finally:
        runtime.close()


@pytest.mark.parametrize("where", ["party", "box"])
def test_completed_retirement_is_attributed_by_next_ordinary_inventory(tmp_path, where):
    from server.gen1_authorized_inventory import replay
    from server.gen1_inventory_observation import COMPONENT as INVENTORY
    from server.gen1_inventory_transition import transition

    runtime = create_runtime(tmp_path, contract())
    try:
        acquired(runtime, where)
        before = copy.deepcopy(
            runtime.state().document()["components"][INVENTORY]["a"]["observation"]
        )
        _, read = observed(runtime)
        acknowledge(runtime, "a", secrets.token_hex(16), read)
        _, write = written(runtime)
        acknowledge(runtime, "a", secrets.token_hex(16), write)
        after = copy.deepcopy(before)
        after["source"] = copy.deepcopy(write["receipt"]["after"])
        after["frame"] += 1
        assert transition(
            before["source"], after["source"], runtime.state().rules.player_identity["a"]
        )["movements"]
        commit(runtime, "a", [], point=after)
        entry = runtime.state().document()["components"][INVENTORY]["a"]
        assert [row["kind"] for row in entry["transition"]["authorized_writes"]] == [
            "acquisition_retire"
        ]
        for key in ("added", "removed", "movements", "party_hp_zero", "changed"):
            assert not entry["transition"][key]
        _, baseline = replay(before["source"], entry["write_attribution"])
        assert baseline == after["source"]
    finally:
        runtime.close()
    runtime = open_runtime(tmp_path)
    try:
        assert runtime.state().document()["components"][INVENTORY]["a"] == entry
    finally:
        runtime.close()


@pytest.mark.parametrize("fault", ["missing", "revision", "digest", "summary"])
def test_compact_retirement_requires_its_exact_retained_proof(tmp_path, fault):
    from server.protocol import canonical_json

    runtime = create_runtime(tmp_path, contract())
    try:
        acquired(runtime)
        _, read = observed(runtime)
        acknowledge(runtime, "a", secrets.token_hex(16), read)
        _, write = written(runtime)
        acknowledge(runtime, "a", secrets.token_hex(16), write)
        compact = runtime.state().document()["components"][COMPONENT]["a"][0]
        full = expand_entry(runtime.journal, compact)
        assert len(canonical_json(compact)) < 2048
        assert len(canonical_json(full)) > 100 * len(canonical_json(compact))
        changed = copy.deepcopy(compact)
        reference = changed["retained"]
        if fault == "missing":
            runtime.journal._db.execute(
                "DELETE FROM records WHERE namespace=? AND record_key=?",
                (reference["namespace"], reference["record_key"]),
            )
        elif fault == "revision":
            reference["record_revision"] += 1
        elif fault == "digest":
            reference["record_digest"] = "f" * 64
        else:
            changed["reason"] = "a different retirement cause"
        with pytest.raises(JournalError):
            expand_entry(runtime.journal, changed)
    finally:
        runtime.close()
