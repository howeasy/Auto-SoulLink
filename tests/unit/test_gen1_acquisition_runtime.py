"""Acquisition settlement: pending until stable, then identity, ordinal and staged rule.

Receipts are synthetic fixtures shaped as the engine leaves them (see the grant tests);
the runtime, journal, identity registry and staged rules are the real ones. Stable
checkpoints are the real inventory-observation handler. No live engine evidence here.
"""

import copy
import secrets

import pytest

from server.gen1_acquisition_runtime import (
    COMPONENT,
    CONSTRAINT_REASON,
    EVENT,
    ORDINALS,
    SCHEMA,
    constraint_id,
    record,
    record_key,
    verify_journal,
    verify_state,
)
from server.gen1_party_codec import PartyCodec
from server.gen1_run_config import create_runtime, open_runtime
from server.gen1_runtime_state import Gen1RuntimeState
from server.protocol_journal import JournalError
from server.state import AreaStatus, LinkStatus
from tests.unit.test_gen1_grant_receipt import fresh, receipt as grant_receipt
from tests.unit.test_gen1_hud_feedback import acknowledge_hud
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
    acknowledge_hud(runtime, player)
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
        notices = {
            player: [
                runtime.journal.command(player, command_id)["body"]
                for command_id in runtime.journal.pending_ids(player)
            ]
            for player in ("a", "b")
        }
        assert [body["kind"] for body in notices["a"]] == ["link_formed"]
        assert [body["kind"] for body in notices["b"]] == ["link_formed"]
        assert all(body["cmd"] == "hud_notice" for batch in notices.values() for body in batch)
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


def test_boxed_delivery_settles_as_an_exempt_grant_whose_half_pends_for_the_partner(tmp_path):
    """A grant delivered to the box is a capture like any other to the shared engine: the half pends
    and links once both halves exist, boxed or not. Usability follows the proved physical disposition,
    so the key is not a usable party member and no recovery hold is needed."""
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
        assert settled["rule"] == "exempt_grant" and settled["violation"] is None
        assert settled["ordinal"] == 1 and settled["link_id"] is None
        state = runtime.state()
        document = state.document()
        assert "a:" + settled["acquisition_id"] in document["identities"]["acquisitions"]
        pending = document["rules"]["core"]["pending_captures"][settled["area"]]
        assert set(pending) == {"a"} and pending["a"]["key"] == settled["fact"]["key"]
        assert settled["fact"]["key"] not in document["rules"]["runtime"]["party_keys"]["a"]
        assert CONSTRAINT_REASON not in state.barrier.document()["blockers"].values()
        verify_state(state)
        verify_journal(runtime.journal, state)
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


def test_game_corner_purchases_pair_by_ordinal_and_the_same_prize_on_both_sides_is_the_species_clause_violation(tmp_path):
    """Each player's Nth stable purchase pairs with the partner's Nth on the per-purchase ordinal area.
    Prizes are player-choice gifts, so the clauses apply exactly as the shared engine applies them:
    Abra against Dratini satisfies the species lock and links; Clefairy against Clefairy is the
    violation, recorded against the half that settled second. The engine force-faints that half
    (the runtime drains the command: Gen 1 executes physical consequences from the rules state) and
    the recovery hold stays as the visible consequence (P9)."""
    runtime = create_runtime(tmp_path, contract("red", "red"), rule_options={"species_lock": True})
    try:
        codec = PartyCodec("red")
        prizes = {0: (0x94, 9), 1: (0x04, 8), 3: (0x58, 18)}  # red prize table slot -> species index, level
        purchases = {"a": [(0, 0x1111), (1, 0x2222)], "b": [(3, 0x3333), (1, 0x4444)]}  # (slot, dv)
        enrolled = {player: enroll(runtime, player) for player in ("a", "b")}  # before any history exists
        for player in ("a", "b"):
            owner, initial, first = enrolled[player]
            observe(runtime, player, [grant(runtime, player, "grant:game_corner_purchase:0", slot=slot, dv=dv)
                                      for slot, dv in purchases[player]], 1)
            stable = [fresh(codec, *prizes[slot], dv=dv, ot_id=0) for slot, dv in purchases[player]]
            checkpoint(runtime, player, owner, initial, first, party_point("red", stable)["fields"]["party"])
            observe(runtime, player, [], 2)
        state = runtime.state()
        document = state.document()
        assert document["components"][ORDINALS] == {"grant:game_corner_purchase": {"a": 2, "b": 2}}
        settled = {player: entry(runtime, player)["settled"] for player in ("a", "b")}
        first_area, second_area = "grant:game_corner_purchase#1", "grant:game_corner_purchase#2"
        for player in ("a", "b"):
            assert [row["pairing_key"] for row in settled[player]] == [first_area, second_area]
            assert [row["area"] for row in settled[player]] == [first_area, second_area]
            assert all(row["rule"] == "exempt_grant" for row in settled[player])
        core = document["rules"]["core"]
        # First purchases: Abra and Dratini satisfy the species lock and link on the #1 area.
        assert settled["a"][0]["violation"] is None and settled["b"][0]["violation"] is None
        assert settled["a"][0]["link_id"] is None  # the earlier half only pends; the link settles with the later one
        link_id = settled["b"][0]["link_id"]
        assert document["identities"]["links"][link_id]["members"] == [settled["a"][0]["member_id"], settled["b"][0]["member_id"]]
        assert len(core["links"]) == 1 and core["links"][0]["area_id"] == first_area
        assert core["links"][0]["status"] == LinkStatus.ALIVE.value and core["area_states"][first_area] == AreaStatus.LINKED.value
        # Second purchases: two Clefairy under the species lock. The engine rejects the later half.
        assert settled["a"][1]["violation"] is None and settled["a"][1]["link_id"] is None
        assert settled["b"][1]["violation"][0].startswith("Species clause") and settled["b"][1]["link_id"] is None
        assert set(core["pending_captures"]) == {second_area} and set(core["pending_captures"][second_area]) == {"a"}
        assert core["area_states"][second_area] == AreaStatus.PENDING_B.value and second_area in core["retry_areas"]["b"]
        assert not any(document["rules"]["runtime"]["queued_commands"].values())  # force_faint drained, never published
        for player in ("a", "b"):
            assert settled[player][1]["fact"]["key"] not in document["rules"]["runtime"]["party_keys"][player]
        holds = {key for key, reason in state.barrier.document()["blockers"].items() if reason == CONSTRAINT_REASON}
        assert holds == {constraint_id("b", settled["b"][1]["acquisition_id"])}
        verify_state(state)
        verify_journal(runtime.journal, state)
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


def test_engine_precheck_rejection_of_a_single_half_is_recorded_as_a_violation_with_its_hold(tmp_path):
    """b's first purchase (Dratini) links with a's first (Abra). a's second purchase is another Dratini:
    no partner half pends on its ordinal area, but the engine's own species pre-check finds the family in
    the alive link and rejects the half before it pends (_handle_capture queues force_faint + memorialize
    and returns). The settled row records the violation, the constraint hold, the retry area and the
    consumed ordinal exactly as the pair path does; the memorial obligation stays, as it does there."""
    runtime = create_runtime(tmp_path, contract("red", "red"), rule_options={"species_lock": True})
    try:
        codec = PartyCodec("red")
        prizes = {0: (0x94, 9), 3: (0x58, 18)}  # Abra, Dratini
        purchases = {"b": [(3, 0x3333)], "a": [(0, 0x1111), (3, 0x2222)]}
        enrolled = {player: enroll(runtime, player) for player in ("a", "b")}
        for player in ("b", "a"):  # b first, so a's second half meets an ALIVE link rather than a pending half
            owner, initial, first = enrolled[player]
            observe(runtime, player, [grant(runtime, player, "grant:game_corner_purchase:0", slot=slot, dv=dv)
                                      for slot, dv in purchases[player]], 1)
            stable = [fresh(codec, *prizes[slot], dv=dv, ot_id=0) for slot, dv in purchases[player]]
            checkpoint(runtime, player, owner, initial, first, party_point("red", stable)["fields"]["party"])
            observe(runtime, player, [], 2)
        state = runtime.state()
        document = state.document()
        core = document["rules"]["core"]
        first_area, second_area = "grant:game_corner_purchase#1", "grant:game_corner_purchase#2"
        assert document["components"][ORDINALS] == {"grant:game_corner_purchase": {"a": 2, "b": 1}}
        linked, rejected = entry(runtime, "a")["settled"]
        assert linked["area"] == first_area and linked["violation"] is None
        assert [(link["area_id"], link["status"]) for link in core["links"]] == [(first_area, LinkStatus.ALIVE.value)]
        assert rejected["area"] == second_area and rejected["rule"] == "exempt_grant" and rejected["link_id"] is None
        assert rejected["violation"][0].startswith("Species clause") and rejected["violation"][1] == ""
        assert second_area not in core["pending_captures"] and second_area in core["retry_areas"]["a"]
        assert rejected["fact"]["key"] in core["pending_memorials"]["a"]
        assert rejected["fact"]["key"] not in document["rules"]["runtime"]["party_keys"]["a"]
        assert not any(document["rules"]["runtime"]["queued_commands"].values())
        holds = {key for key, reason in state.barrier.document()["blockers"].items() if reason == CONSTRAINT_REASON}
        assert holds == {constraint_id("a", rejected["acquisition_id"])}
        verify_state(state)
        verify_journal(runtime.journal, state)
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

