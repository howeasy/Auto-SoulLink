"""NPC exchange settlement: pending until stable, then one identity migration and an in-place rule rekey.

Exchange receipts are the synthetic fixtures of the receipt tests; the runtime, journal,
identity registry, staged rules and inventory checkpoints are the real ones. Links and
pending captures are seeded through the same detached-stage commit the faint fixtures use.
"""

import copy
import secrets

import pytest

from server import event_reference
from server.capture_rules import record_clause_checked_acquisition
from server.gen1_acquisition_runtime import COMPONENT as ACQUISITIONS, ORDINALS
from server.gen1_npc_exchange_receipt import records
from server.gen1_npc_exchange_runtime import (
    COMPONENT,
    EVENT,
    SCHEMA,
    decode_receipts,
    record,
    record_key,
    stage_exchanges,
    verify_journal,
    verify_state,
)
from server.gen1_party_codec import PartyCodec
from server.gen1_run_config import create_runtime, open_runtime
from server.gen1_runtime_state import Gen1RuntimeState
from server.gen1_starter_settlement import context, mon_info
from server.identity_registry import IdentityWitness
from server.protocol_journal import JournalError, _encode
from server.state import AreaStatus, LinkStatus
from tests.unit.test_gen1_acquisition_runtime import (
    INSTANCE,
    checkpoint,
    enroll,
    grant,
    observe as observe_acquisitions,
)
from tests.unit.test_gen1_inventory_observation import party_point
from tests.unit.test_gen1_npc_exchange_receipt import DATA, receipt as exchange_receipt
from tests.unit.test_gen1_party_codec import make_blob
from tests.unit.test_gen1_sessions import contract

SOURCE = "npc:route_2_trade_house:1"  # every title: Mr. Mime for Abra (R/B) or Clefairy (Y)
AREA = "route_24"


def variant_of(runtime, player):
    return runtime.contract["players"][player]["variant"]


def give_species(runtime, player):
    return DATA["titles"][variant_of(runtime, player)]["sites"][SOURCE]["give_species"]


def party_for(runtime, player, *, level=20, seed=0):
    """[kept, outgoing, kept] with per-player distinct DVs; returns (blobs, outgoing blob)."""
    codec = PartyCodec(variant_of(runtime, player))
    kept = [make_blob(codec, level=10, dv=0x1000 + seed * 16 + index) for index in range(3)]
    outgoing = make_blob(codec, species=give_species(runtime, player), level=level, dv=0x1111 + seed)
    return [kept[0], outgoing, kept[2]], outgoing


def exchange(runtime, player, party_before, *, slot=1, frames=(100, 130, 140), seed=0, **kw):
    value = exchange_receipt(variant_of(runtime, player), SOURCE, slot=slot, party_before=party_before,
                             dv=0x5A5A + seed, ot_id=0xBEEF - seed, **kw)
    for witness, frame in zip(("call", "remove", "return"), frames, strict=True):
        value[witness]["point"]["player_id_hex"] = "0000"
        value[witness]["frame"] = frame
    value["context_generation"] = player * 32
    value["physical_instance"] = INSTANCE[player]
    value["final_sha1"] = runtime.contract["players"][player]["final_rom_sha1"]
    return {"kind": "npc_exchange", "receipt": value}


def observe(runtime, player, receipts, sequence, operation=None):
    request = {"event": EVENT, "payload": {"schema": SCHEMA, "variant": variant_of(runtime, player),
               "context_generation": player * 32, "final_sha1": runtime.contract["players"][player]["final_rom_sha1"],
               "sequence": sequence, "receipts": receipts}}
    return record(runtime, player, operation or secrets.token_hex(16), request), request


def seed(runtime, blobs, *, rule=True):
    """Give each player in `blobs` a logical identity for its blob and, if `rule`, a clause-checked half at AREA."""
    stage = runtime.state()
    initials = stage.document()["components"]["gen1-initial-observations"]
    for player, blob in blobs.items():
        mon = PartyCodec(variant_of(runtime, player)).validate_blob(blob)
        identifier = secrets.token_hex(16)
        stage.identities.acquire(identifier, identifier, IdentityWitness(context(initials[player], player), mon.key, mon.sha256, 1))
        if rule:
            record_clause_checked_acquisition(stage.rules, player, AREA, mon_info(mon), gift=False, activate_from_capture=False)
    stage.barrier.set_history(stage.history_digest())
    runtime.journal.commit("a", secrets.token_hex(16), {"event": "explicit-exchange-seed-fixture"},
        expected_revision=stage.journal_revision, state=stage.document(), commands={"a": [], "b": []}, result={"ack": "ACK"})


def entry(runtime, player):
    return runtime.state().document()["components"].get(COMPONENT, {}).get(player)


def party_hex(runtime, player, blobs):
    return party_point(variant_of(runtime, player), blobs)["fields"]["party"]


def key_of(runtime, player, blob):
    return PartyCodec(variant_of(runtime, player)).validate_blob(blob).key


def last_checkpoint(runtime, player):
    return runtime.state().document()["components"]["gen1-inventory-observations"][player]["operation_id"]


@pytest.mark.parametrize("variants", [("red", "blue"), ("yellow", "yellow"), ("blue", "red")], ids=lambda pair: "-".join(pair))
def test_exchange_is_pending_until_stable_then_migrates_identity_and_rewrites_the_link_half(tmp_path, variants):
    runtime = create_runtime(tmp_path, contract(*variants))
    try:
        owners, initials, firsts, parties, outgoing = {}, {}, {}, {}, {}
        for player in ("a", "b"):
            owners[player], initials[player], firsts[player] = enroll(runtime, player)
            parties[player], outgoing[player] = party_for(runtime, player, seed=ord(player))
        seed(runtime, outgoing)
        before = runtime.state().document()
        assert len(before["rules"]["core"]["links"]) == 1 and before["rules"]["core"]["links"][0]["area_id"] == AREA
        members_before = set(before["identities"]["members"])
        acquisitions_before = copy.deepcopy(before["identities"]["acquisitions"])
        for index, player in enumerate(("a", "b")):
            receipts = [exchange(runtime, player, parties[player], seed=ord(player))]
            initial_row = runtime.state().document()["components"]["gen1-initial-observations"][player]
            fact = decode_receipts(receipts, initial_row["metadata"], initial_row["binding"], reference=None)[0]["fact"]
            observe(runtime, player, receipts, 1)
            row = entry(runtime, player)
            assert len(row["pending"]) == 1 and row["settled"] == [] and row["sequence"] == 1
            assert row["pending"][0]["source_ref"]["index"] == 0 and row["pending"][0]["fact"] == fact
            # A checkpoint before the return frame settles nothing, even though it still shows the outgoing mon.
            checkpoint(runtime, player, owners[player], initials[player], firsts[player], party_hex(runtime, player, parties[player]), frame=120)
            observe(runtime, player, [], 2)
            row = entry(runtime, player)
            assert len(row["pending"]) == 1 and row["settled"] == []
            document = runtime.state().document()
            link = document["rules"]["core"]["links"][0]
            assert link[player]["key"] == fact["outgoing"]["key"] and set(document["identities"]["members"]) == members_before
            after_hex = receipts[0]["receipt"]["return"]["point"]["party_hex"]
            checkpoint(runtime, player, owners[player], initials[player], last_checkpoint(runtime, player), after_hex, frame=200, sequence=2)
            stable_operation = last_checkpoint(runtime, player)
            observe(runtime, player, [], 3)
            row = entry(runtime, player)
            assert row["pending"] == [] and len(row["settled"]) == 1 and row["sequence"] == 3
            settled = row["settled"][0]
            assert settled["kind"] == "npc_exchange" and settled["fact"] == fact and settled["rule"] == "link" and settled["area"] == AREA
            assert settled["inventory_operation"] == stable_operation
            document = runtime.state().document()
            incoming = fact["incoming"]["key"]
            link = document["rules"]["core"]["links"][0]
            partner = "b" if player == "a" else "a"
            assert link["area_id"] == AREA and link["status"] == LinkStatus.ALIVE.value
            assert link[player] == {"key": incoming, "level": 20, "species": 122, "nickname": fact["incoming"]["nickname"], "is_shiny": False}
            expected_partner = before["rules"]["core"]["links"][0][partner] if index == 0 else document["rules"]["core"]["links"][0][partner]
            assert link[partner] == expected_partner
            assert document["rules"]["core"]["area_states"][AREA] == AreaStatus.LINKED.value
            keys = document["rules"]["runtime"]["party_keys"][player]
            assert incoming in keys and fact["outgoing"]["key"] not in keys
            member = document["identities"]["members"][settled["member_id"]]
            assert member["current"]["key"] == incoming and len(member["history"]) == 2
            assert member["history"][1]["before_evidence_digest"] == settled["before_evidence_digest"]
            assert member["history"][1]["evidence_digest"] == settled["evidence_digest"]
            assert member["history"][1]["event"] == player + ":" + settled["exchange_event"]
            assert set(document["identities"]["members"]) == members_before  # migration, never acquisition
            assert document["identities"]["acquisitions"] == acquisitions_before
            assert ORDINALS not in document["components"] and ACQUISITIONS not in document["components"]
            state = runtime.state()
            verify_state(state)
            verify_journal(runtime.journal, state)
            assert runtime.journal.record(COMPONENT, record_key(player)).value == row
        saved = runtime.state().document()["components"][COMPONENT]
    finally:
        runtime.close()
    reopened = open_runtime(tmp_path)
    try:
        stage = reopened.state()
        assert stage.document()["components"][COMPONENT] == saved
        verify_state(stage)
        verify_journal(reopened.journal, stage)
    finally:
        reopened.close()


def test_pending_capture_keeps_its_original_area(tmp_path):
    runtime = create_runtime(tmp_path, contract("red", "yellow"))
    try:
        owner, initial, first = enroll(runtime, "a")
        party, outgoing = party_for(runtime, "a")
        seed(runtime, {"a": outgoing})
        receipts = [exchange(runtime, "a", party)]
        observe(runtime, "a", receipts, 1)
        checkpoint(runtime, "a", owner, initial, first, receipts[0]["receipt"]["return"]["point"]["party_hex"])
        observe(runtime, "a", [], 2)
        settled = entry(runtime, "a")["settled"][0]
        document = runtime.state().document()
        pending = document["rules"]["core"]["pending_captures"]
        assert settled["rule"] == "pending_capture" and settled["area"] == AREA
        assert set(pending) == {AREA} and set(pending[AREA]) == {"a"}
        assert pending[AREA]["a"]["key"] == settled["fact"]["incoming"]["key"] and pending[AREA]["a"]["species"] == 122
        assert document["rules"]["core"]["area_states"][AREA] == AreaStatus.PENDING_B.value and not document["rules"]["core"]["links"]
        verify_state(runtime.state())
        verify_journal(runtime.journal, runtime.state())
    finally:
        runtime.close()


def test_exchange_consumes_no_ordinal_creates_no_acquisition_and_leaves_unruled_identities_alone(tmp_path):
    runtime = create_runtime(tmp_path, contract("red", "red"))
    try:
        owner, initial, first = enroll(runtime, "a")
        eevee = grant(runtime, "a", "grant:eevee:0")
        observe_acquisitions(runtime, "a", [eevee], 1)
        eevee_blob = records(bytes.fromhex(eevee["receipt"]["return"]["point"]["party_hex"]))[0]
        codec = PartyCodec("red")
        outgoing = make_blob(codec, species=give_species(runtime, "a"), level=20, dv=0x1111)
        party = [eevee_blob, outgoing]
        checkpoint(runtime, "a", owner, initial, first, party_hex(runtime, "a", party), frame=200)
        observe_acquisitions(runtime, "a", [], 2)
        seed(runtime, {"a": outgoing}, rule=False)  # a logical identity that no link or pending capture holds
        before = runtime.state().document()
        assert before["components"][ORDINALS] == {"grant:eevee:0": {"a": 1, "b": 0}}
        receipts = [exchange(runtime, "a", party, frames=(300, 330, 340))]
        observe(runtime, "a", receipts, 1)
        checkpoint(runtime, "a", owner, initial, last_checkpoint(runtime, "a"), receipts[0]["receipt"]["return"]["point"]["party_hex"], frame=400, sequence=2)
        observe(runtime, "a", [], 2)
        after = runtime.state().document()
        settled = entry(runtime, "a")["settled"][0]
        assert settled["rule"] == "identity_only" and settled["area"] is None
        assert _encode(after["components"][ORDINALS]) == _encode(before["components"][ORDINALS])
        assert after["components"][ACQUISITIONS] == before["components"][ACQUISITIONS]
        assert after["identities"]["acquisitions"] == before["identities"]["acquisitions"]
        assert set(after["identities"]["members"]) == set(before["identities"]["members"])
        # The owned inventory also refreshes display/stat caches for already
        # qualified party members; that is not an exchange rule mutation.
        assert {k: v for k, v in after['rules']['core'].items() if k != 'mon_stats'} == {
            k: v for k, v in before['rules']['core'].items() if k != 'mon_stats'}
        assert after['rules']['runtime']['party_keys'] == before['rules']['runtime']['party_keys']
        assert after["identities"]["members"][settled["member_id"]]["current"]["key"] == settled["fact"]["incoming"]["key"]
        verify_state(runtime.state())
        verify_journal(runtime.journal, runtime.state())
    finally:
        runtime.close()


def test_outgoing_mon_without_a_logical_identity_is_refused(tmp_path):
    runtime = create_runtime(tmp_path, contract("blue", "blue"))
    try:
        owner, initial, first = enroll(runtime, "a")
        party, _ = party_for(runtime, "a")
        receipts = [exchange(runtime, "a", party)]
        observe(runtime, "a", receipts, 1)
        checkpoint(runtime, "a", owner, initial, first, receipts[0]["receipt"]["return"]["point"]["party_hex"])
        before = runtime.journal.snapshot()
        with pytest.raises(JournalError, match="no logical identity"):
            observe(runtime, "a", [], 2)
        assert runtime.journal.snapshot() == before
    finally:
        runtime.close()


@pytest.mark.parametrize("fault", ["outgoing_kept", "incoming_missing"])
def test_stable_checkpoint_that_contradicts_the_exchange_refuses_settlement(tmp_path, fault):
    runtime = create_runtime(tmp_path, contract("yellow", "red"))
    try:
        owner, initial, first = enroll(runtime, "a")
        party, outgoing = party_for(runtime, "a")
        seed(runtime, {"a": outgoing})
        observe(runtime, "a", [exchange(runtime, "a", party)], 1)
        shown = party if fault == "outgoing_kept" else [party[0], party[2]]
        checkpoint(runtime, "a", owner, initial, first, party_hex(runtime, "a", shown))
        before = runtime.journal.snapshot()
        with pytest.raises(JournalError, match="still holds the outgoing key|lacks the incoming"):
            observe(runtime, "a", [], 2)
        assert runtime.journal.snapshot() == before
        assert runtime.state().document()["rules"]["core"]["pending_captures"][AREA]["a"]["key"] == key_of(runtime, "a", outgoing)
    finally:
        runtime.close()


@pytest.mark.parametrize("fault", ["sequence", "context", "repeat_receipt", "repeat_key", "unknown_source", "wrong_kind", "malformed_row", "too_many", "forged_fact"])
def test_hostile_observations_commit_nothing(tmp_path, fault):
    runtime = create_runtime(tmp_path, contract("red", "blue"))
    try:
        enroll(runtime, "a")
        party, _ = party_for(runtime, "a")
        receipts = [exchange(runtime, "a", party)]
        sequence = 1
        if fault == "sequence":
            sequence = 2
        elif fault == "context":
            receipts[0]["receipt"]["context_generation"] = "f" * 32
        elif fault == "repeat_receipt":
            observe(runtime, "a", copy.deepcopy(receipts), 1)
            sequence = 2
        elif fault == "repeat_key":
            observe(runtime, "a", copy.deepcopy(receipts), 1)
            receipts = [exchange(runtime, "a", party, frames=(300, 330, 340))]  # same incoming key, later frames
            sequence = 2
        elif fault == "unknown_source":
            receipts[0]["receipt"]["source_id"] = "npc:route_2_trade_house:2"
        elif fault == "wrong_kind":
            receipts[0]["kind"] = "grant"
        elif fault == "malformed_row":
            receipts = [{"kind": "npc_exchange"}]
        elif fault == "too_many":
            receipts = [copy.deepcopy(receipts[0]) for _ in range(17)]
        before = runtime.journal.snapshot()
        if fault == "forged_fact":
            stage = runtime.state()
            document = stage.document()
            initial = document["components"]["gen1-initial-observations"]["a"]
            operation = secrets.token_hex(16)
            request = {"event": EVENT, "payload": {"schema": SCHEMA, "variant": "red", "context_generation": "a" * 32,
                       "final_sha1": runtime.contract["players"]["a"]["final_rom_sha1"], "sequence": 1, "receipts": receipts}}
            facts = decode_receipts(receipts, initial["metadata"], initial["binding"], reference=event_reference.make("a", operation, request))
            facts[0]["fact"]["incoming"]["level"] += 1
            with pytest.raises(JournalError, match="caller-forged"):
                stage_exchanges(runtime, stage, document, "a", operation, facts, frame_request=request)
        else:
            with pytest.raises(JournalError):
                observe(runtime, "a", receipts, sequence)
        assert runtime.journal.snapshot() == before
    finally:
        runtime.close()


def test_replay_returns_the_committed_result_and_corrupt_evidence_or_tampered_rows_are_refused(tmp_path):
    runtime = create_runtime(tmp_path, contract("blue", "yellow"))
    try:
        owner, initial, first = enroll(runtime, "a")
        party, outgoing = party_for(runtime, "a")
        seed(runtime, {"a": outgoing})
        receipts = [exchange(runtime, "a", party)]
        operation = secrets.token_hex(16)
        result, request = observe(runtime, "a", receipts, 1, operation)
        snapshot = runtime.journal.snapshot()
        assert record(runtime, "a", operation, request) == result and runtime.journal.snapshot() == snapshot
        checkpoint(runtime, "a", owner, initial, first, receipts[0]["receipt"]["return"]["point"]["party_hex"])
        observe(runtime, "a", [], 2)
        state = runtime.state()
        document = state.document()
        verify_state(state)
        verify_journal(runtime.journal, state)
        settled = document["components"][COMPONENT]["a"]["settled"][0]
        # Restore validation: a settled row whose incoming key the registry never migrated to.
        tampered = copy.deepcopy(document)
        tampered["components"][COMPONENT]["a"]["settled"][0]["fact"]["incoming"]["key"] = "0000:0000:2A"
        with pytest.raises(JournalError, match="identity migration lineage"):
            verify_state(Gen1RuntimeState.restore(tampered, data_dir=tmp_path))
        unknown = copy.deepcopy(document)
        unknown["components"][COMPONENT]["a"]["settled"][0]["member_id"] = "f" * 32
        with pytest.raises(JournalError, match="identity migration lineage"):
            verify_state(Gen1RuntimeState.restore(unknown, data_dir=tmp_path))
        # Raw event corruption: the journaled receipt bytes change under a consistent digest.
        corrupt = copy.deepcopy(request)
        corrupt["payload"]["receipts"][0]["receipt"]["return"]["frame"] += 1
        text, fingerprint = _encode(corrupt)
        runtime.journal._db.execute("UPDATE events SET request=?, request_digest=? WHERE player=? AND operation_id=?",
                                    (text, fingerprint, "a", settled["source_ref"]["event"]["operation_id"]))
        with pytest.raises(JournalError, match="referenced event request differs"):
            verify_journal(runtime.journal, state)
    finally:
        runtime.close()
