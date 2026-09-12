"""Acquisition settlement: pending until stable, then identity, ordinal and staged rule.

Receipts are synthetic fixtures shaped as the engine leaves them (see the grant tests);
the runtime, journal, identity registry and staged rules are the real ones. Stable
checkpoints are the real inventory-observation handler. No live engine evidence here.
"""

import copy
import secrets

import pytest

from server.capture_rules import record_clause_checked_acquisition
from server.gen1_acquisition_runtime import (
    COMPONENT,
    EVENT,
    ORDINALS,
    SCHEMA,
    record,
    record_key,
    verify_journal,
    verify_state,
)
from server.gen1_party_codec import PartyCodec
from server.gen1_run_config import create_runtime, open_runtime
from server.gen1_runtime_state import Gen1RuntimeState
from server.protocol_journal import JournalError
from server.staged_state import StagedSoulLinkState
from server.state import AreaStatus, LinkStatus, MonInfo, SoulLinkState
from tests.unit.test_gen1_grant_receipt import fresh, receipt as grant_receipt
from tests.unit.test_gen1_initial_observation import admit, observation, send
from tests.unit.test_gen1_inventory_observation import deliver as deliver_inventory, party_point
from tests.unit.test_gen1_sessions import contract

INSTANCE = {"a": "1" * 32, "b": "2" * 32}


def enroll(runtime, player):
    owner = admit(runtime, player)
    initial = observation(runtime, player)  # empty save at frame 100
    first = secrets.token_hex(16)
    send(runtime, player, owner, initial, first)
    return owner, initial, first


def grant(runtime, player, source, **kw):
    variant = runtime.contract["players"][player]["variant"]
    value = grant_receipt(variant, source, ot_id="0000", existing=0, **kw)
    value["context_generation"] = player * 32
    value["physical_instance"] = INSTANCE[player]
    value["final_sha1"] = runtime.contract["players"][player]["final_rom_sha1"]
    return {"kind": "grant", "receipt": value}


def observe(runtime, player, receipts, sequence, operation=None):
    request = {"event": EVENT, "payload": {"schema": SCHEMA, "variant": runtime.contract["players"][player]["variant"],
               "context_generation": player * 32, "final_sha1": runtime.contract["players"][player]["final_rom_sha1"],
               "sequence": sequence, "receipts": receipts}}
    return record(runtime, player, operation or secrets.token_hex(16), request), request


def checkpoint(runtime, player, owner, initial, previous, party_hex, *, frame=200, sequence=1):
    point = copy.deepcopy(initial)
    point["frame"] = frame
    point["source"]["fields"]["party"] = party_hex
    return deliver_inventory(runtime, player, owner, {"sequence": sequence, "previous_operation_id": previous, "observation": point})


def entry(runtime, player):
    return runtime.state().document()["components"].get(COMPONENT, {}).get(player)


def ordinals(runtime):
    return runtime.state().document()["components"].get(ORDINALS, {})


@pytest.mark.parametrize("variants", [("yellow", "yellow"), ("red", "blue")], ids=lambda pair: "-".join(pair))
def test_grant_is_pending_until_stable_then_settles_identity_ordinal_rule_and_pairs(tmp_path, variants):
    runtime = create_runtime(tmp_path, contract(*variants))
    try:
        owners, initials, firsts, receipts = {}, {}, {}, {}
        for player in ("a", "b"):
            owners[player], initials[player], firsts[player] = enroll(runtime, player)
            receipts[player] = grant(runtime, player, "grant:eevee:0")
            observe(runtime, player, [receipts[player]], 1)
            row = entry(runtime, player)
            assert len(row["pending"]) == 1 and row["settled"] == [] and row["sequence"] == 1
            assert row["pending"][0]["source_ref"]["index"] == 0
        state = runtime.state().document()
        assert not state["identities"]["acquisitions"] and ORDINALS not in state["components"]
        assert not state["rules"]["core"]["pending_captures"]
        for player in ("a", "b"):
            party_hex = receipts[player]["receipt"]["return"]["point"]["party_hex"]
            checkpoint(runtime, player, owners[player], initials[player], firsts[player], party_hex)
            observe(runtime, player, [], 2)
            row = entry(runtime, player)
            assert row["pending"] == [] and len(row["settled"]) == 1 and row["sequence"] == 2
            settled = row["settled"][0]
            assert settled["kind"] == "grant" and settled["pairing_id"] == "grant:eevee:0"
            assert settled["ordinal"] == 1 and settled["pairing_key"] == "grant:eevee:0#1"
            assert settled["area"] == "celadon_mansion_roof" and settled["rule"] == "exempt_grant" and settled["violation"] is None
            document = runtime.state().document()
            record_id = player + ":" + settled["acquisition_id"]
            assert document["identities"]["acquisitions"][record_id]["member_id"] == settled["member_id"]
            assert not document["rules"]["core"]["pokeballs_obtained"][player]  # a gift proves no Pokeballs
        assert ordinals(runtime) == {"grant:eevee:0": {"a": 1, "b": 1}}
        state = runtime.state()
        document = state.document()
        assert entry(runtime, "a")["settled"][0]["link_id"] is None  # first half only pends
        link_id = entry(runtime, "b")["settled"][0]["link_id"]
        assert link_id is not None
        members = document["identities"]["links"][link_id]["members"]
        assert members == [entry(runtime, "a")["settled"][0]["member_id"], entry(runtime, "b")["settled"][0]["member_id"]]
        links = document["rules"]["core"]["links"]
        assert len(links) == 1 and links[0]["area_id"] == "celadon_mansion_roof" and links[0]["status"] == LinkStatus.ALIVE.value
        assert document["rules"]["core"]["area_states"]["celadon_mansion_roof"] == AreaStatus.LINKED.value
        assert not document["rules"]["core"]["pending_captures"]
        for player in ("a", "b"):
            assert entry(runtime, player)["settled"][0]["fact"]["key"] in document["rules"]["runtime"]["party_keys"][player]
        verify_state(state)
        verify_journal(runtime.journal, state)
        assert runtime.journal.record(COMPONENT, record_key("a")).value == entry(runtime, "a")
        saved = document["components"][COMPONENT]
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


def test_ordinals_are_per_source_and_only_consumed_by_stable_deliveries(tmp_path):
    runtime = create_runtime(tmp_path, contract("red", "blue"))
    try:
        owner, initial, first = enroll(runtime, "a")
        codec = PartyCodec("red")
        first_abra = grant(runtime, "a", "grant:game_corner_purchase:0", slot=0, dv=0x1111)
        dratini = grant(runtime, "a", "grant:game_corner_purchase:0", slot=3, dv=0x2222)
        second_abra = grant(runtime, "a", "grant:game_corner_purchase:0", slot=0, dv=0x3333)
        never = grant(runtime, "a", "grant:lapras:0", dv=0x4444)  # returned after the only checkpoint: not yet stable
        never["receipt"]["call"]["frame"], never["receipt"]["return"]["frame"] = 300, 340
        observe(runtime, "a", [first_abra, dratini, second_abra, never], 1)
        assert len(entry(runtime, "a")["pending"]) == 4 and ORDINALS not in runtime.state().document()["components"]
        stable = [fresh(codec, 0x94, 9, dv=0x1111, ot_id=0), fresh(codec, 0x58, 18, dv=0x2222, ot_id=0), fresh(codec, 0x94, 9, dv=0x3333, ot_id=0)]
        checkpoint(runtime, "a", owner, initial, first, party_point("red", stable)["fields"]["party"])
        observe(runtime, "a", [], 2)
        row = entry(runtime, "a")
        assert [r["fact"]["source_id"] for r in row["pending"]] == ["grant:lapras:0"]
        keys = [r["pairing_key"] for r in row["settled"]]
        assert keys == ["grant:game_corner_purchase#1", "grant:game_corner_purchase#2", "grant:game_corner_purchase#3"]
        assert [r["area"] for r in row["settled"]] == keys  # repeatable prizes pair under their own ordinal
        assert ordinals(runtime) == {"grant:game_corner_purchase": {"a": 3, "b": 0}}
        assert all(r["rule"] == "exempt_grant" and r["violation"] is None and r["link_id"] is None for r in row["settled"])
        document = runtime.state().document()
        assert set(document["rules"]["core"]["pending_captures"]) == set(keys)
        assert not document["rules"]["core"]["pokeballs_obtained"]["a"]
        verify_state(runtime.state())
        verify_journal(runtime.journal, runtime.state())
    finally:
        runtime.close()


def test_boxed_delivery_settles_identity_and_ordinal_but_defers_its_rule(tmp_path):
    runtime = create_runtime(tmp_path, contract("yellow", "yellow"))
    try:
        owner, initial, first = enroll(runtime, "a")
        boxed = grant(runtime, "a", "grant:lapras:0", delivery="box")
        observe(runtime, "a", [boxed], 1)
        point = copy.deepcopy(initial)
        point["frame"] = 200
        point["source"]["fields"]["party"] = boxed["receipt"]["return"]["point"]["party_hex"]
        point["source"]["fields"]["box"] = boxed["receipt"]["return"]["point"]["box_hex"]
        deliver_inventory(runtime, "a", owner, {"sequence": 1, "previous_operation_id": first, "observation": point})
        observe(runtime, "a", [], 2)
        settled = entry(runtime, "a")["settled"][0]
        assert settled["rule"] == "boxed_deferred" and settled["ordinal"] == 1 and settled["link_id"] is None
        document = runtime.state().document()
        assert "a:" + settled["acquisition_id"] in document["identities"]["acquisitions"]
        assert not document["rules"]["core"]["pending_captures"]
        verify_state(runtime.state())
        verify_journal(runtime.journal, runtime.state())
    finally:
        runtime.close()


@pytest.mark.parametrize("fault", ["sequence", "context", "repeat_key", "unknown_source", "malformed_row", "too_many"])
def test_hostile_observations_commit_nothing(tmp_path, fault):
    runtime = create_runtime(tmp_path, contract("yellow", "yellow"))
    try:
        enroll(runtime, "a")
        receipts = [grant(runtime, "a", "grant:eevee:0")]
        sequence = 1
        if fault == "sequence":
            sequence = 2
        elif fault == "context":
            receipts[0]["receipt"]["context_generation"] = "f" * 32
        elif fault == "repeat_key":
            observe(runtime, "a", receipts, 1)
            sequence = 2
        elif fault == "unknown_source":
            receipts[0]["receipt"]["source_id"] = "grant:mew:0"
        elif fault == "malformed_row":
            receipts = [{"kind": "grant"}]
        elif fault == "too_many":
            receipts = [copy.deepcopy(receipts[0]) for _ in range(17)]
        before = runtime.journal.snapshot()
        with pytest.raises(JournalError):
            observe(runtime, "a", receipts, sequence)
        assert runtime.journal.snapshot() == before
    finally:
        runtime.close()


def test_stable_checkpoint_that_contradicts_a_delivery_refuses_settlement(tmp_path):
    runtime = create_runtime(tmp_path, contract("red", "red"))
    try:
        owner, initial, first = enroll(runtime, "a")
        observe(runtime, "a", [grant(runtime, "a", "grant:eevee:0")], 1)
        empty = party_point("red", [])["fields"]["party"]
        checkpoint(runtime, "a", owner, initial, first, empty)  # after the return frame, no Eevee anywhere
        before = runtime.journal.snapshot()
        with pytest.raises(JournalError, match="lacks the delivered key"):
            observe(runtime, "a", [], 2)
        assert runtime.journal.snapshot() == before and ORDINALS not in runtime.state().document()["components"]
    finally:
        runtime.close()


def test_replay_returns_the_committed_result_and_restore_rechecks_evidence(tmp_path):
    runtime = create_runtime(tmp_path, contract("blue", "yellow"))
    try:
        owner, initial, first = enroll(runtime, "a")
        value = grant(runtime, "a", "grant:eevee:0")
        operation = secrets.token_hex(16)
        result, request = observe(runtime, "a", [value], 1, operation)
        snapshot = runtime.journal.snapshot()
        assert record(runtime, "a", operation, request) == result and runtime.journal.snapshot() == snapshot
        checkpoint(runtime, "a", owner, initial, first, value["receipt"]["return"]["point"]["party_hex"])
        observe(runtime, "a", [], 2)
        state = runtime.state()
        document = state.document()
        tampered = copy.deepcopy(document)
        tampered["components"][COMPONENT]["a"]["settled"][0]["fact"]["level"] += 1
        restored = Gen1RuntimeState.restore(tampered, data_dir=tmp_path)
        # The component/atomic-record equality fires first; the receipt re-decode is the
        # second line and runs on every row of the happy path above.
        with pytest.raises(JournalError, match="atomic journal record|authoritative receipt"):
            verify_journal(runtime.journal, restored)
        counted = copy.deepcopy(document)
        counted["components"][ORDINALS]["grant:eevee:0"]["a"] = 2
        with pytest.raises(JournalError, match="ordinals differ"):
            verify_state(Gen1RuntimeState.restore(counted, data_dir=tmp_path))
        broken = copy.deepcopy(document)
        broken["components"][COMPONENT]["a"]["settled"][0]["pairing_key"] = "grant:eevee:0#9"
        with pytest.raises(JournalError, match="pairing key"):
            verify_state(Gen1RuntimeState.restore(broken, data_dir=tmp_path))
    finally:
        runtime.close()


def staged_rules(tmp_path, *, species_lock=False):
    from server.adapters import get_adapter

    live = SoulLinkState(data_dir=str(tmp_path), adapter=get_adapter("gen1_rby", rom_type="red"))
    live.rom_type = "red"
    live.species_lock = species_lock
    return StagedSoulLinkState.from_live(live, {"retired_pairs": []})


def test_clause_checked_acquisition_pairs_or_records_the_violation_without_enforcing(tmp_path):
    rules = staged_rules(tmp_path)
    eevee_a = MonInfo(key="1111:0000:66", level=25, species=133, nickname="EEVEE")
    eevee_b = MonInfo(key="2222:0000:66", level=25, species=133, nickname="EEVEE")
    first = record_clause_checked_acquisition(rules, "a", "celadon_mansion_roof", eevee_a, gift=True)
    assert first == {"linked": None, "violation": None}
    assert rules.area_states["celadon_mansion_roof"] == AreaStatus.PENDING_B and not rules.pokeballs_obtained["a"]
    second = record_clause_checked_acquisition(rules, "b", "celadon_mansion_roof", eevee_b, gift=True)
    assert second["violation"] is None and second["linked"].status == LinkStatus.ALIVE
    assert rules.area_states["celadon_mansion_roof"] == AreaStatus.LINKED and "celadon_mansion_roof" not in rules.pending_captures
    with pytest.raises(JournalError, match="already resolved"):
        record_clause_checked_acquisition(rules, "a", "celadon_mansion_roof", MonInfo(key="3333:0000:66", level=25, species=133), gift=True)
    locked = staged_rules(tmp_path, species_lock=True)
    record_clause_checked_acquisition(locked, "a", "route_24", MonInfo(key="4444:0000:04", level=10, species=35), gift=False)
    assert locked.pokeballs_obtained["a"]  # a catch in an encounter area proves Pokeballs
    outcome = record_clause_checked_acquisition(locked, "b", "route_24", MonInfo(key="5555:0000:04", level=10, species=35), gift=False)
    assert outcome["linked"] is None and outcome["violation"][0].startswith("Species clause")
    assert set(locked.pending_captures["route_24"]) == {"a", "b"} and not locked.links
    with pytest.raises(JournalError, match="already has a pending"):
        record_clause_checked_acquisition(locked, "a", "route_3", MonInfo(key="4444:0000:04", level=10, species=35), gift=False)
