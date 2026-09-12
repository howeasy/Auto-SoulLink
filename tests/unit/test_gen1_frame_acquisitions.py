"""Compound acquisition transactions over real journals and synthetic cartridges.

Eligibility is a private typed test proof. Receipt data comes from the existing
source-shaped fixtures; these cases neither advance an emulator nor grant play.
"""

import copy
import hashlib
import secrets
import sqlite3
from types import SimpleNamespace

import pytest

from server.event_reference import make
from server.gen1_acquisition_runtime import (
    COMPONENT,
    CONSTRAINT_REASON,
    EVENT,
    ORDINALS,
    SCHEMA,
    decode_receipts,
    record_key,
    result_for,
    source_rom,
    stage_acquisitions,
    verify_journal,
    verify_state,
)
from server.gen1_capture_receipt import DATA as CAPTURE_DATA, SCHEMA as CAPTURE_SCHEMA
from server.gen1_frame_journal import RETURNS, enroll, returned
from server.gen1_frame_runtime import boundary_from_inventory
from server.gen1_grant_receipt import DATA as GRANT_DATA
from server.gen1_run_config import create_runtime, open_runtime
from server.protocol import digest
from server.protocol_journal import JournalError, ProtocolJournal
from server.state import LinkStatus
from tests.unit.test_gen1_acquisition_runtime import grant as grant_receipt
from tests.unit.test_gen1_atomic_frame_settlement import frame, window
from tests.unit.test_gen1_capture_receipt import receipt as capture_receipt
from tests.unit.test_gen1_frame_journal import setup
from tests.unit.test_gen1_inventory_observation import party_point
from tests.unit.test_gen1_sessions import contract


def start(runtime):
    setup(runtime)
    for player in ("a", "b"):
        enroll(runtime, player, secrets.token_hex(16))


def source(runtime, player, name="grant:eevee:0", *, call=110, finish=130, **options):
    row = grant_receipt(runtime, player, name, boxed_before=0, **options)
    receipt = row["receipt"]
    receipt["call"]["frame"] = call
    receipt["return"]["frame"] = finish
    if "paid" in receipt:
        receipt["paid"]["frame"] = finish + 1
    return row


def checkpoint(runtime, player, rows, after, *, party=None):
    document = runtime.state().document()
    old = document["components"].get("gen1-inventory-observations", {}).get(player)
    result = copy.deepcopy(
        old["observation"]
        if old
        else document["components"]["gen1-initial-observations"][player]["observation"]
    )
    result["frame"] = after
    if rows:
        row = rows[-1]
        point = (
            row["receipt"]["return"] if row["kind"] == "grant" else row["receipt"]["receipt"]["end"]
        )["point"]
        result["source"]["fields"]["party"] = point["party_hex"]
        result["source"]["fields"]["box"] = point["box_hex"]
    if party is not None:
        result["source"]["fields"]["party"] = party
    return result


def message(runtime, player, rows, *, after=140, sparse=False, point=None):
    point = point or checkpoint(runtime, player, rows, after)
    result = frame(runtime, player, point, None)
    result["bundle"]["acquisitions"] = rows
    if sparse:
        result["bundle"]["boundary"] = boundary_from_inventory(point)
        result["bundle"]["inventory"] = None
    result["receipt"]["observations_digest"] = digest(result["bundle"])
    return result


def commit(runtime, player, rows, *, after=140, sparse=False, point=None):
    window(runtime, player, frames=60)
    operation = secrets.token_hex(16)
    request = message(runtime, player, rows, after=after, sparse=sparse, point=point)
    result = returned(runtime, player, operation, request, settle_observations=True)
    return operation, request, result


def audit(runtime):
    state = runtime.state()
    verify_state(state)
    verify_journal(runtime.journal, state)
    return state.document()


@pytest.mark.parametrize("variants", [("yellow", "yellow"), ("red", "blue"), ("blue", "yellow")])
def test_frame_settles_typed_grants_once_after_inventory_and_reopens(tmp_path, variants):
    runtime = create_runtime(tmp_path, contract(*variants), rule_options={"species_lock": True})
    try:
        start(runtime)
        for player in ("a", "b"):
            operation, request, result = commit(runtime, player, [source(runtime, player)])
            document = audit(runtime)
            entry = document["components"][COMPONENT][player]
            assert entry["frame_origin"] == make(player, operation, request)
            assert result["acquisition_digest"] == digest(entry) and entry["pending"] == []
            assert entry["settled"][0]["rule"] == "exempt_grant"
            assert not runtime.state().rules.pokeballs_obtained[player]
            before = runtime.journal.snapshot()
            assert returned(runtime, player, operation, request, settle_observations=True) == result
            assert runtime.journal.snapshot() == before
        assert runtime.state().rules.links[0].status == LinkStatus.ALIVE
        assert runtime.state().barrier.ticket() is None
    finally:
        runtime.close()
    runtime = open_runtime(tmp_path)
    try:
        assert len(audit(runtime)["identities"]["links"]) == 1
    finally:
        runtime.close()


def test_sparse_delivery_waits_for_stable_inventory_without_consuming_an_ordinal(tmp_path):
    runtime = create_runtime(tmp_path, contract("yellow", "yellow"))
    try:
        start(runtime)
        row = source(runtime, "a")
        first, _, _ = commit(runtime, "a", [row], sparse=True)
        entry = audit(runtime)["components"][COMPONENT]["a"]
        assert len(entry["pending"]) == 1 and entry["settled"] == []
        assert ORDINALS not in runtime.state().document()["components"]
        point = checkpoint(runtime, "a", [row], 180)
        second, _, result = commit(runtime, "a", [], after=180, point=point)
        entry = audit(runtime)["components"][COMPONENT]["a"]
        assert (
            entry["operation_id"] == second
            and entry["settled"][0]["source_ref"]["event"]["operation_id"] == first
        )
        assert entry["pending"] == [] and entry["settled"][0]["ordinal"] == 1
        assert result["acquisition_digest"] == digest(entry)
    finally:
        runtime.close()


def party_blobs(raw):
    data = bytes.fromhex(raw)
    return [
        data[8 + 44 * i : 52 + 44 * i]
        + data[272 + 11 * i : 283 + 11 * i]
        + data[338 + 11 * i : 349 + 11 * i]
        for i in range(data[0])
    ]


def test_game_corner_pairs_by_global_successful_purchase_order_across_different_prizes(tmp_path):
    runtime = create_runtime(
        tmp_path, contract("yellow", "yellow"), rule_options={"species_lock": True}
    )
    try:
        start(runtime)
        for number, after in [(1, 140), (2, 180)]:
            for player, slot in [("a", 0 if number == 1 else 3), ("b", 3 if number == 1 else 0)]:
                row = source(
                    runtime,
                    player,
                    "grant:game_corner_purchase:0",
                    slot=slot,
                    dv=0x1100 + number,
                    call=110 if number == 1 else 150,
                    finish=130 if number == 1 else 170,
                )
                if number == 2:
                    old = runtime.state().document()["components"]["gen1-inventory-observations"][
                        player
                    ]["observation"]["source"]["fields"]["party"]
                    new = party_blobs(row["receipt"]["return"]["point"]["party_hex"])[-1]
                    row["receipt"]["call"]["point"]["party_hex"] = old
                    row["receipt"]["return"]["point"]["party_hex"] = party_point(
                        "yellow", party_blobs(old) + [new]
                    )["fields"]["party"]
                    row["receipt"]["paid"]["point"]["party_hex"] = row["receipt"]["return"][
                        "point"
                    ]["party_hex"]
                commit(runtime, player, [row], after=after)
        document = audit(runtime)
        assert document["components"][ORDINALS] == {"grant:game_corner_purchase": {"a": 2, "b": 2}}
        assert len(runtime.state().rules.links) == 2
        for player in ("a", "b"):
            settled = document["components"][COMPONENT][player]["settled"]
            assert [row["pairing_key"] for row in settled] == [
                "grant:game_corner_purchase#1",
                "grant:game_corner_purchase#2",
            ]
        commit(runtime, "a", [], after=220, sparse=True)
        assert audit(runtime)["components"][ORDINALS] == document["components"][ORDINALS]
    finally:
        runtime.close()


def test_call_may_span_verified_prior_windows_but_missing_history_refuses(tmp_path):
    runtime = create_runtime(tmp_path, contract("red", "blue"))
    try:
        start(runtime)
        commit(runtime, "a", [], after=140, sparse=True)
        row = source(runtime, "a", call=120, finish=165)
        commit(runtime, "a", [row], after=180)
        document = audit(runtime)
        entry = document["components"][COMPONENT]["a"]
        source_event = runtime.journal.event_snapshot("a", entry["operation_id"])
        saved = runtime.journal.record(RETURNS, source_event.result["closed_frame_digest"][:32])
        old_digest = saved.value["previous"]["ledger"]["pending"]["previous_digest"]
        runtime.journal._db.execute(
            "DELETE FROM records WHERE namespace=? AND record_key=?", (RETURNS, old_digest[:32])
        )
        with pytest.raises(JournalError):
            verify_journal(runtime.journal, runtime.state())
        assert document["components"][COMPONENT]["a"]["settled"][0]["fact"]["call_frame"] == 120
    finally:
        runtime.close()


@pytest.mark.parametrize(
    "fault", ["before-enrollment", "future-delivery", "old-payment", "duplicate", "wrong-context"]
)
def test_unaccounted_or_replayed_sources_never_mutate_identity_or_ordinals(tmp_path, fault):
    runtime = create_runtime(tmp_path, contract("yellow", "yellow"))
    try:
        start(runtime)
        row = source(runtime, "a", "grant:game_corner_purchase:0", slot=0)
        if fault == "before-enrollment":
            row["receipt"]["call"]["frame"] = 99
        elif fault == "future-delivery":
            row["receipt"]["return"]["frame"] = 160
            row["receipt"]["paid"]["frame"] = 161
        elif fault == "old-payment":
            row["receipt"]["call"]["frame"] = 95
            row["receipt"]["return"]["frame"] = 99
            row["receipt"]["paid"]["frame"] = 100
        elif fault == "wrong-context":
            row["receipt"]["context_generation"] = "f" * 32
        rows = [row, row] if fault == "duplicate" else [row]
        window(runtime, "a", frames=60)
        before = runtime.journal.snapshot()
        with pytest.raises(JournalError):
            returned(
                runtime,
                "a",
                secrets.token_hex(16),
                message(runtime, "a", rows),
                settle_observations=True,
            )
        assert runtime.journal.snapshot() == before
        assert COMPONENT not in runtime.state().document()["components"]
    finally:
        runtime.close()


@pytest.mark.parametrize("fault", ["event", "result", "source-index", "lost-hold"])
def test_current_acquisition_and_constraint_provenance_are_audited(tmp_path, fault):
    runtime = create_runtime(tmp_path, contract("yellow", "red"))
    try:
        start(runtime)
        site = next(
            name
            for name, data in GRANT_DATA["titles"]["yellow"]["sites"].items()
            if data["yellow_only"]
        )
        operation, _, _ = commit(runtime, "a", [source(runtime, "a", site)])
        stage = runtime.state()
        entry = stage.document()["components"][COMPONENT]["a"]
        assert entry["settled"][0]["rule"] == "retirement_required"
        assert entry["settled"][0]["retirement_reason"]
        assert entry["settled"][0]["fact"]["key"] not in stage.rules.party_keys["a"]
        assert CONSTRAINT_REASON in stage.barrier.document()["blockers"].values()
        if fault == "event":
            # Retirement now correctly originates a command from this event.
            # Simulate damaged storage past SQLite's normal FK protection.
            runtime.journal._db.execute('PRAGMA foreign_keys=OFF')
            runtime.journal._db.execute(
                "DELETE FROM events WHERE player=? AND operation_id=?", ("a", operation)
            )
            runtime.journal._db.execute('PRAGMA foreign_keys=ON')
            with pytest.raises(JournalError):
                verify_journal(runtime.journal, stage)
        elif fault == "result":
            runtime.journal._db.execute(
                "UPDATE events SET result_digest=? WHERE player=? AND operation_id=?",
                ("f" * 64, "a", operation),
            )
            with pytest.raises(JournalError):
                verify_journal(runtime.journal, stage)
        elif fault == "source-index":
            entry["settled"][0]["source_ref"]["index"] = True
            from server.gen1_runtime_state import Gen1RuntimeState

            doc = stage.document()
            doc["components"][COMPONENT]["a"] = entry
            with pytest.raises(JournalError):
                verify_state(Gen1RuntimeState.restore(doc, data_dir=tmp_path))
        else:
            blockers = {
                key: value
                for key, value in stage.barrier.document()["blockers"].items()
                if value != CONSTRAINT_REASON
            }
            stage.barrier.set_blockers(blockers)
            with pytest.raises(JournalError):
                verify_state(stage)
    finally:
        runtime.close()


def test_boxed_delivery_installs_a_hold_without_enabling_party_use(tmp_path):
    runtime = create_runtime(tmp_path, contract("yellow", "yellow"))
    try:
        start(runtime)
        row = source(runtime, "a", "grant:lapras:0", delivery="box")
        commit(runtime, "a", [row])
        document = audit(runtime)
        entry = document["components"][COMPONENT]["a"]
        assert entry["settled"][0]["rule"] == "boxed_deferred"
        assert entry["settled"][0]["fact"]["key"] not in runtime.state().rules.party_keys["a"]
        assert CONSTRAINT_REASON in runtime.state().barrier.document()["blockers"].values()
    finally:
        runtime.close()


def capture(runtime, player):
    raw = capture_receipt(
        runtime.contract["players"][player]["variant"], party_count=0, box_count=0
    )
    raw["begin"]["frame"] = 110
    raw["end"]["frame"] = 130
    for witness in ("begin", "end"):
        raw[witness]["point"]["player_id_hex"] = "0000"
    party = bytearray.fromhex(raw["end"]["point"]["party_hex"])
    party[20:22] = b"\0\0"
    raw["end"]["point"]["party_hex"] = party.hex().upper()
    return {
        "kind": "capture",
        "receipt": {
            "schema": CAPTURE_SCHEMA,
            "source_sha256": CAPTURE_DATA["sha256"],
            "variant": runtime.contract["players"][player]["variant"],
            "context_generation": player * 32,
            "final_sha1": runtime.contract["players"][player]["final_rom_sha1"],
            "receipt": raw,
        },
    }


def test_capture_never_infers_ball_activation_and_violation_holds_both_halves(tmp_path):
    runtime = create_runtime(
        tmp_path, contract("yellow", "yellow"), rule_options={"species_lock": True}
    )
    try:
        start(runtime)
        for player in ("a", "b"):
            commit(runtime, player, [capture(runtime, player)])
        document = audit(runtime)
        assert runtime.state().rules.pokeballs_obtained == {"a": False, "b": False}
        row = document["components"][COMPONENT]["b"]["settled"][0]
        assert row["violation"] and not runtime.state().rules.links
        assert CONSTRAINT_REASON in runtime.state().barrier.document()["blockers"].values()
        assert all(not runtime.state().rules.party_keys[p] for p in ("a", "b"))
    finally:
        runtime.close()


@pytest.mark.parametrize("phase", ["staging", "sql"])
def test_acquisition_failure_rolls_back_inventory_identity_rules_and_return_together(
    tmp_path, monkeypatch, phase
):
    runtime = create_runtime(tmp_path, contract("red", "blue"))
    try:
        start(runtime)
        row = source(runtime, "a")
        window(runtime, "a", frames=60)
        request = message(runtime, "a", [row])
        before = runtime.journal.snapshot()
        if phase == "sql":
            runtime.journal._db.execute(
                "CREATE TRIGGER fail_acquisitions BEFORE INSERT ON records BEGIN SELECT RAISE(ABORT,'fixture'); END"
            )
            error = sqlite3.DatabaseError
        else:
            import server.gen1_frame_acquisitions as module

            actual = module.stage_acquisitions

            def refuse(*args, **kwargs):
                actual(*args, **kwargs)
                raise JournalError("injected acquisition failure after detached mutation")

            monkeypatch.setattr(module, "stage_acquisitions", refuse)
            error = JournalError
        with pytest.raises(error):
            returned(runtime, "a", secrets.token_hex(16), request, settle_observations=True)
        assert runtime.journal.snapshot() == before
    finally:
        runtime.close()


@pytest.mark.parametrize("fault", ["missing-rom", "wrong-hash", "clean-fallback", "forged-fact"])
def test_randomized_scope_and_raw_fact_boundary_refuse_unsupported_inputs(tmp_path, fault):
    runtime = create_runtime(tmp_path, contract("yellow", "yellow"))
    try:
        start(runtime)
        initial = runtime.state().document()["components"]["gen1-initial-observations"]["a"]
        metadata = copy.deepcopy(initial["metadata"])
        metadata["gen1_metadata"]["cartridge"]["content_profile_schema"] = "gen1-rby-upr-fixture"
        rom = b"explicit-ROM-scope-fixture"
        metadata["gen1_metadata"]["cartridge"]["final_rom_sha1"] = hashlib.sha1(rom).hexdigest()
        if fault == "missing-rom":
            with pytest.raises(JournalError):
                source_rom(metadata, "a")
        elif fault == "wrong-hash":
            with pytest.raises(JournalError):
                source_rom(metadata, "a", lambda player: rom + b"changed")
        elif fault == "clean-fallback":
            row = source(runtime, "a")
            row["receipt"]["final_sha1"] = metadata["gen1_metadata"]["cartridge"]["final_rom_sha1"]
            with pytest.raises(JournalError):
                decode_receipts(
                    [row], metadata, initial["binding"], reference=make("a", "a" * 32, {})
                )
        else:
            window(runtime, "a", frames=60)
            operation = secrets.token_hex(16)
            request = message(runtime, "a", [source(runtime, "a")])
            state = runtime.state()
            doc = state.document()
            from server.gen1_frame_runtime import complete

            complete(doc, "a", request["receipt"], request["bundle"])
            reference = make("a", operation, request)
            facts = decode_receipts(
                request["bundle"]["acquisitions"],
                initial["metadata"],
                initial["binding"],
                reference=reference,
            )
            facts[0]["fact"]["level"] += 1
            before = runtime.journal.snapshot()
            with pytest.raises(JournalError, match="forged"):
                stage_acquisitions(
                    runtime,
                    state,
                    doc,
                    "a",
                    operation,
                    facts,
                    frame_origin=reference,
                    frame_request=request,
                )
            assert runtime.journal.snapshot() == before
    finally:
        runtime.close()


def test_changed_species_operand_is_used_during_decode_and_real_journal_reopen(tmp_path):
    runtime = create_runtime(tmp_path / "runtime", contract("yellow", "yellow"))
    try:
        start(runtime)
        initial = copy.deepcopy(
            runtime.state().document()["components"]["gen1-initial-observations"]["a"]
        )
        row = source(runtime, "a", species=4)
    finally:
        runtime.close()
    # Synthetic admitted metadata isolates this decoder/restore boundary. This
    # byte image is not a ROM-admission or UPR-randomizer qualification fixture.
    site = GRANT_DATA["titles"]["yellow"]["sites"]["grant:eevee:0"]
    rom = bytearray(max(site["species"]["rom_offsets"]) + 1)
    for offset in site["species"]["rom_offsets"]:
        rom[offset] = 4
    rom = bytes(rom)
    cartridge = initial["metadata"]["gen1_metadata"]["cartridge"]
    cartridge["content_profile_schema"] = "gen1-rby-upr-decoder-fixture"
    cartridge["final_rom_sha1"] = hashlib.sha1(rom).hexdigest()
    row["receipt"]["final_sha1"] = cartridge["final_rom_sha1"]
    operation = secrets.token_hex(16)
    request = {
        "event": EVENT,
        "payload": {
            "schema": SCHEMA,
            "variant": "yellow",
            "context_generation": "a" * 32,
            "final_sha1": cartridge["final_rom_sha1"],
            "sequence": 1,
            "receipts": [row],
        },
    }
    reference = make("a", operation, request)
    facts = decode_receipts(
        [row], initial["metadata"], initial["binding"], reference=reference, rom=rom
    )
    assert facts[0]["fact"]["species_index"] == 4
    entry = {
        "sequence": 1,
        "operation_id": operation,
        "previous_operation_id": initial["operation_id"],
        "pending": facts,
        "settled": [],
    }
    document = {
        "components": {"gen1-initial-observations": {"a": initial}, COMPONENT: {"a": entry}}
    }
    journal = ProtocolJournal(tmp_path / "evidence.sqlite3", contract_hash="b" * 64)
    try:
        journal.bootstrap({})
        journal.commit(
            "a",
            operation,
            request,
            expected_revision=0,
            state=document,
            commands={"a": [], "b": []},
            result=result_for(entry),
            records=[{"namespace": COMPONENT, "key": record_key("a"), "value": entry}],
        )
    finally:
        journal.close()
    journal = ProtocolJournal(tmp_path / "evidence.sqlite3", contract_hash="b" * 64)
    try:
        state = SimpleNamespace(document=lambda: journal.snapshot().state)
        verify_journal(journal, state, rom_provider=lambda player: rom)
        with pytest.raises(JournalError, match="ROM bytes"):
            verify_journal(journal, state)
        with pytest.raises(JournalError, match="admitted cartridge"):
            verify_journal(journal, state, rom_provider=lambda player: rom + b"changed")
    finally:
        journal.close()
