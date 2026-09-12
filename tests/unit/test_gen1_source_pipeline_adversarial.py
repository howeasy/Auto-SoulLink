"""Every source kind through one free-run observation batch: statics first, acquisitions, exchanges, wild.

Multi-event checks of the actual composed handlers (`gen1_observation_runtime.stage_observation`):
no emulator, no root hook mocks. Receipts are the synthetic fixtures of the receipt tests; the
runtime, journal, identity registry and rules are real. Restored from the frame-credit suites
(`test_gen1_frame_source_receipts.py` and this file's two adversarial cases) onto the batch.
"""

import copy
import secrets
from types import SimpleNamespace

import pytest

from server import event_reference
from server.gen1_acquisition_runtime import (
    COMPONENT as ACQUISITIONS,
    ORDINALS,
    decode_receipts as decode_acquisitions,
    verify_journal as verify_acquisition_journal,
    verify_state as verify_acquisition_state,
)
from server.gen1_capture_receipt import DATA as CAPTURE_DATA, SCHEMA as CAPTURE_SCHEMA
from server.gen1_npc_exchange_runtime import (
    COMPONENT as EXCHANGES,
    decode_receipts as decode_exchanges,
    verify_journal as verify_exchange_journal,
    verify_state as verify_exchange_state,
)
from server.gen1_observation_runtime import record
from server.gen1_run_config import create_runtime
from server.gen1_source_receipts import (
    ACQUISITION_KINDS,
    ENCOUNTER_KINDS,
    EXCHANGE_KINDS,
    LIFECYCLE_KINDS,
    decode,
)
from server.gen1_static_lifecycle import (
    COMPONENT as STATICS,
    HOLD,
    consume,
    new_row,
    open,
    verify_journal as verify_static_journal,
    verify_state as verify_static_state,
)
from server.gen1_static_receipt import DATA as STATIC_DATA
from server.gen1_wild_encounter_runtime import COMPONENT as WILD, verify_journal as verify_wild_journal
from server.protocol import digest
from server.protocol_journal import JournalError, RecordSnapshot, _encode
from server.state import AreaStatus
from tests.unit.observation_fixture import checkpoint, commit, message, observe, party_after, party_blobs, source, start
from tests.unit.test_gen1_acquisition_runtime import INSTANCE
from tests.unit.test_gen1_capture_receipt import receipt as capture_receipt
from tests.unit.test_gen1_engine_signal_runtime import payload as engine_payload
from tests.unit.test_gen1_faint_runtime import bag
from tests.unit.test_gen1_inventory_observation import party_point
from tests.unit.test_gen1_npc_exchange_runtime import exchange
from tests.unit.test_gen1_sessions import contract
from tests.unit.test_gen1_static_lifecycle import caught
from tests.unit.test_gen1_static_receipt import end_receipt, receipt as origin_receipt
from tests.unit.test_gen1_storage_runtime import complete_storage
from tests.unit.test_gen1_wild_encounter import receipt as wild_receipt

SNORLAX = "static:route12_snorlax"
PAIRS = [("red", "blue"), ("yellow", "yellow"), ("blue", "yellow")]
BATCH = {"event": "observation", "acquisitions": []}  # the committing event shape a source_ref points into


def variant_of(runtime, player):
    return runtime.contract["players"][player]["variant"]


def _scoped(runtime, player, kind, value, witnesses):
    value["context_generation"] = player * 32
    value["physical_instance"] = INSTANCE[player]
    value["final_sha1"] = runtime.contract["players"][player]["final_rom_sha1"]
    for witness in witnesses:
        value[witness]["point"]["player_id_hex"] = "0000"
    return {"kind": kind, "receipt": value}


def origin(runtime, player, source_id=SNORLAX, *, arm=105, began=106):
    return _scoped(runtime, player, "static_origin", origin_receipt(variant_of(runtime, player), source_id, arm_frame=arm, began_frame=began),
                   ("arm", "began"))


def battle_end(runtime, player, source_id=SNORLAX, *, frame=135, result=2):
    return _scoped(runtime, player, "static_battle_end", end_receipt(variant_of(runtime, player), source_id, frame=frame, battle_result=result),
                   ("end",))


def wild(runtime, player, kind, *, frame, **changes):
    """A wild-encounter boundary (`begin`/`end`) of this save, as the wild observer publishes it."""
    value = wild_receipt(variant_of(runtime, player), kind, frame, **changes)
    value["witness"]["point"]["player_id_hex"] = "0000"
    return _scoped(runtime, player, "wild_" + kind, value, ())


def static_capture(runtime, player, source_id=SNORLAX, *, begin=110, end=130, dv=0xABCD, party=()):
    """A delivering wild capture of the static's clean operands on its map; `party` are the blobs already owned."""
    variant = variant_of(runtime, player)
    site = STATIC_DATA["titles"][variant]["sites"][source_id]
    raw = capture_receipt(variant, party_count=0, box_count=0, species=site["species"]["clean"][0], level=site["level"]["values"][0],
                          map_id=site["map_id"], dv=dv)
    raw["begin"]["frame"], raw["end"]["frame"] = begin, end
    caught_blob = bytearray(party_blobs(raw["end"]["point"]["party_hex"])[0])
    caught_blob[12:14] = b"\0\0"  # the save's OT id, as the fixture's player id is
    party = list(party)
    raw["begin"]["point"]["party_hex"] = party_point(variant, party)["fields"]["party"]
    raw["end"]["point"]["party_hex"] = party_point(variant, party + [bytes(caught_blob)])["fields"]["party"]
    for witness in ("begin", "end"):
        raw[witness]["point"]["player_id_hex"] = "0000"
    return {"kind": "capture", "receipt": {"schema": CAPTURE_SCHEMA, "source_sha256": CAPTURE_DATA["sha256"], "variant": variant,
                                          "context_generation": player * 32, "final_sha1": runtime.contract["players"][player]["final_rom_sha1"],
                                          "receipt": raw}}


def settle(runtime, player, rows, *, after, party=None):
    """One batch carrying `rows` and the checkpoint at `after`, on the physical image storage left behind (if any)."""
    physical = complete_storage(runtime)
    point = checkpoint(runtime, player, [], after, party=party or party_after(rows))
    if player in physical:
        latest = copy.deepcopy(physical[player])
        latest["fields"]["party"] = point["source"]["fields"]["party"]
        point["source"] = latest
        # The next observed frame becomes the new modelled physical baseline.
        del physical[player]
    return commit(runtime, player, rows, after=after, point=point)


def audit(runtime):
    state = runtime.state()
    verify_acquisition_state(state)
    verify_acquisition_journal(runtime.journal, state)
    verify_static_state(state.document()["components"].get(STATICS, {}))
    verify_static_journal(runtime.journal, state)
    verify_exchange_state(state)
    verify_exchange_journal(runtime.journal, state)
    verify_wild_journal(runtime.journal, state)
    return state.document()


def components(runtime, player):
    document = runtime.state().document()["components"]
    return document.get(STATICS, {}).get(player), document.get(ACQUISITIONS, {}).get(player), document.get(EXCHANGES, {}).get(player)


def test_one_mixed_wire_list_keeps_raw_indices_and_a_subset_enumeration_would_not(tmp_path):
    runtime = create_runtime(tmp_path, contract("red", "blue"))
    try:
        start(runtime)
        initial = runtime.state().document()["components"]["gen1-initial-observations"]["a"]
        abra = party_blobs(source(runtime, "a", "grant:game_corner_purchase:0", slot=0)["receipt"]["return"]["point"]["party_hex"])
        rows = [static_capture(runtime, "a", dv=0x1111), origin(runtime, "a"), exchange(runtime, "a", abra, slot=0, frames=(110, 120, 130), level=abra[0][33]),
                static_capture(runtime, "a", dv=0x2222), wild(runtime, "a", "begin", frame=108), wild(runtime, "a", "end", frame=138)]
        reference = event_reference.make("a", "a" * 32, {**BATCH, "acquisitions": rows})
        facts = decode(rows, initial["metadata"], initial["binding"], reference=reference)
        assert [(fact["kind"], fact["source_ref"]["index"]) for fact in facts] == [("capture", 0), ("static_origin", 1), ("npc_exchange", 2), ("capture", 3),
                                                                                    ("wild_begin", 4), ("wild_end", 5)]
        assert facts[4]["fact"]["kind"] == "wild_begin" and facts[5]["fact"]["battle_result"] == 2
        assert all(fact["source_ref"]["event"] == reference for fact in facts)
        # The bug this guards against: enumerating a filtered subset renumbers rows 0 and 3 as 0 and 1.
        subset = [row for row in rows if row["kind"] == "capture"]
        renumbered = decode_acquisitions(subset, initial["metadata"], initial["binding"], reference=reference)
        assert [fact["source_ref"]["index"] for fact in renumbered] == [0, 1]
        assert rows[renumbered[1]["source_ref"]["index"]]["kind"] == "static_origin"  # index 1 names the wrong raw row
        # Re-decoding the raw row a kept index names yields the same fact; a foreign kind at that index is refused.
        for fact in facts:
            row = rows[fact["source_ref"]["index"]]
            assert decode([row], initial["metadata"], initial["binding"], reference=reference, kinds=(fact["kind"],))[0]["fact"] == fact["fact"]
        with pytest.raises(JournalError, match="not admitted"):
            decode_acquisitions([rows[1]], initial["metadata"], initial["binding"], reference=reference)
        with pytest.raises(JournalError, match="not admitted"):
            decode_exchanges([rows[0]], initial["metadata"], initial["binding"], reference=reference)
        with pytest.raises(JournalError, match="typed source receipt"):
            decode([{"kind": "trade", "receipt": {}}], initial["metadata"], initial["binding"], reference=reference)
        # Wild rows are transport for the settling decoders: neither admits them, and the wire kind must match the receipt's.
        assert ENCOUNTER_KINDS == ("wild_begin", "wild_end") and not set(ENCOUNTER_KINDS) & set(ACQUISITION_KINDS + LIFECYCLE_KINDS + EXCHANGE_KINDS)
        for index in (4, 5):
            for refused in (decode_acquisitions, decode_exchanges):
                with pytest.raises(JournalError, match="not admitted"):
                    refused([rows[index]], initial["metadata"], initial["binding"], reference=reference)
        with pytest.raises(JournalError, match="row kind differs"):
            decode([{"kind": "wild_end", "receipt": rows[4]["receipt"]}], initial["metadata"], initial["binding"], reference=reference)
        with pytest.raises(JournalError, match="row kind differs"):
            decode([{"kind": "wild_begin", "receipt": rows[5]["receipt"]}], initial["metadata"], initial["binding"], reference=reference)
    finally:
        runtime.close()


def test_wild_boundaries_ride_the_batch_and_settle_in_their_own_stage(tmp_path):
    runtime = create_runtime(tmp_path, contract("red", "blue"))
    try:
        start(runtime)
        capture = static_capture(runtime, "a")
        point = capture["receipt"]["receipt"]["begin"]["point"]
        battle = {"map_id": point["map_id"], "species_index": point["cur_species"], "level": point["cur_level"]}
        rows = [wild(runtime, "a", "begin", frame=108, **battle), origin(runtime, "a"), capture, wild(runtime, "a", "end", frame=138, **battle),
                battle_end(runtime, "a")]
        operation, request, result = settle(runtime, "a", rows, after=140)
        reference = event_reference.make("a", operation, request)
        # One batch result names every stage that ran; nothing was staged for the kinds the list lacked.
        assert {"inventory_transition_digest", "static_digest", "acquisition_digest", "wild_encounter_digest", "observation_digest"} <= set(result)
        assert "exchange_digest" not in result and "evolution_digest" not in result
        encounter = next(iter(runtime.state().document()["components"][WILD]["players"]["a"]["encounters"].values()))
        assert encounter["phase"] == "captured" and encounter["decision"] is None
        listed = [encounter["begin"], *encounter["captures"], encounter["end"]]
        assert [(row["kind"], row["fact"]["kind"], row["source_ref"]["index"]) for row in listed] == [("wild_begin", "wild_begin", 0), ("capture", "capture", 2),
                                                                                                    ("wild_end", "wild_end", 3)]
        assert all(row["source_ref"]["event"] == reference for row in listed)
        assert (encounter["begin"]["fact"]["frame"], encounter["end"]["fact"]["frame"], encounter["end"]["fact"]["battle_result"]) == (108, 138, 2)
        statics, acquisitions, exchanges = components(runtime, "a")
        assert [o["source_ref"]["index"] for o in statics["origins"]] == [1] and statics["origins"][0]["capture"]["source_ref"]["index"] == 2
        assert len(acquisitions["settled"]) == 1 and acquisitions["pending"] == [] and exchanges is None
        assert result["wild_encounter_digest"] == digest(runtime.state().document()["components"][WILD])
        audit(runtime)
    finally:
        runtime.close()


@pytest.mark.parametrize("variants", PAIRS, ids=lambda pair: "-".join(pair))
def test_a_static_capture_pairs_under_its_static_and_a_later_same_species_wild_does_not(tmp_path, variants):
    runtime = create_runtime(tmp_path, contract(*variants))
    try:
        start(runtime)
        for player in ("a", "b"):
            rows = [origin(runtime, player), static_capture(runtime, player), battle_end(runtime, player)]
            operation, request, result = settle(runtime, player, rows, after=140)
            statics, acquisitions, exchanges = components(runtime, player)
            reference = event_reference.make(player, operation, request)
            assert [o["state"] for o in statics["origins"]] == ["consumed"]
            assert statics["origins"][0]["source_ref"] == {"event": reference, "index": 0}
            assert statics["origins"][0]["capture"]["source_ref"] == {"event": reference, "index": 1}
            assert statics["origins"][0]["end"] is None  # consumed before its end row: the end is a no-op
            settled = acquisitions["settled"][0]
            assert statics["attributions"] == {settled["fact"]["key"]: SNORLAX} and statics["held"] == []
            assert settled["area"] == SNORLAX and settled["rule"] == "clause_checked" and settled["violation"] is None
            assert settled["pairing_id"] == "capture:route_12" and settled["ordinal"] == 1
            assert result["static_digest"] == digest(statics) and result["acquisition_digest"] == digest(acquisitions)
            assert exchanges is None and "exchange_digest" not in result
        document = audit(runtime)
        links = document["rules"]["core"]["links"]
        assert len(links) == 1 and links[0]["area_id"] == SNORLAX  # the two statics linked each other, not a Route 12 wild
        first = {player: party_blobs(party_after([static_capture(runtime, player)]))[0] for player in ("a", "b")}
        for player in ("a", "b"):
            owned = [bytes(bytearray(first[player][:12]) + b"\0\0" + first[player][14:])]
            rows = [static_capture(runtime, player, begin=150, end=170, dv=0x2222, party=owned)]
            settle(runtime, player, rows, after=180)
            statics, acquisitions, _ = components(runtime, player)
            assert [o["state"] for o in statics["origins"]] == ["consumed"] and len(statics["attributions"]) == 1
            assert acquisitions["settled"][1]["area"] == "route_12" and acquisitions["settled"][1]["ordinal"] == 2
        document = audit(runtime)
        assert document["components"][ORDINALS] == {"capture:route_12": {"a": 2, "b": 2}}
        assert {link["area_id"] for link in document["rules"]["core"]["links"]} == {SNORLAX, "route_12"}
    finally:
        runtime.close()


@pytest.mark.parametrize("order", [(0, 1, 2), (0, 2, 1), (1, 0, 2), (1, 2, 0), (2, 0, 1), (2, 1, 0)], ids=lambda o: "".join("OCE"[i] for i in o))
def test_origin_capture_and_end_in_one_batch_in_every_order(tmp_path, order):
    runtime = create_runtime(tmp_path, contract("red", "blue"))
    try:
        start(runtime)
        rows = [origin(runtime, "a"), static_capture(runtime, "a"), battle_end(runtime, "a")]
        listed = [rows[i] for i in order]
        settle(runtime, "a", listed, after=140)
        statics, acquisitions, _ = components(runtime, "a")
        attributed = order.index(0) < order.index(1)  # source-faithful list order: the origin must be listed before its capture
        settled = acquisitions["settled"][0]
        assert (settled["area"] == SNORLAX) is attributed and (statics["attributions"] != {}) is attributed
        assert statics["held"] == []
        if attributed:
            assert statics["origins"][0]["state"] == "consumed"
        else:
            assert statics["origins"][0]["state"] == ("ended" if order.index(0) < order.index(2) else "live")
        assert statics["origins"][0]["source_ref"]["index"] == order.index(0)
        audit(runtime)
    finally:
        runtime.close()


def test_ambiguous_evidence_is_held_not_attributed_and_not_refused(tmp_path):
    runtime = create_runtime(tmp_path, contract("yellow", "yellow"))
    try:
        start(runtime)
        rows = [origin(runtime, "a", arm=119, began=120), static_capture(runtime, "a", begin=110, end=130)]  # call 110 precedes began 120
        before = runtime.state().document()
        settle(runtime, "a", rows, after=140)
        statics, acquisitions, _ = components(runtime, "a")
        key = decode([rows[1]], before["components"]["gen1-initial-observations"]["a"]["metadata"],
                     before["components"]["gen1-initial-observations"]["a"]["binding"], reference=None)[0]["fact"]["key"]
        assert statics["origins"][0]["state"] == "live" and statics["attributions"] == {}
        assert [item["fact"]["key"] for item in statics["held"]] == [key] and statics["held"][0]["source_ref"]["index"] == 1
        assert acquisitions["pending"] == [] and acquisitions["settled"] == []
        assert ORDINALS not in runtime.state().document()["components"]
        from server.gen1_static_lifecycle import HOLD_REASON
        assert HOLD_REASON in runtime.state().barrier.document()["blockers"].values()
        assert {k: v for k, v in runtime.state().document()["rules"]["core"].items() if k != "mon_stats"} == {
            k: v for k, v in before["rules"]["core"].items() if k != "mon_stats"}
        audit(runtime)
    finally:
        runtime.close()


def test_two_eligible_origins_hold_the_capture():
    row = new_row()
    frame = event_reference.make("a", "1" * 32, BATCH)
    from tests.unit.test_gen1_static_lifecycle import origin as origin_fact
    open(row, origin_fact("red", SNORLAX, began=20), {"event": frame, "index": 0})
    row["origins"][0]["state"], row["origins"][0]["end"] = "ended", {"source_ref": {"event": frame, "index": 1}, "frame": 150, "battle_result": 2}
    open(row, origin_fact("red", SNORLAX, began=90), {"event": frame, "index": 2})
    assert consume(row, caught("red", SNORLAX), {"event": frame, "index": 3}, variant="red") == HOLD
    verify_static_state({"a": row})


@pytest.mark.parametrize("variant", ["red", "blue", "yellow"])
def test_excluded_scripted_battles_never_attribute(variant):
    profile = STATIC_DATA["titles"][variant]
    excluded = {site["map_id"] for site in profile["excluded"].values() if "map_id" in site}
    excluded |= {map_id for site in profile["excluded"].values() for map_id in site.get("map_ids", [])}
    excluded |= set(profile["tower_map_ids"])
    assert excluded and not {site["map_id"] for site in profile["sites"].values()} & excluded
    row = new_row()
    frame = event_reference.make("a", "1" * 32, BATCH)
    from tests.unit.test_gen1_static_lifecycle import origin as origin_fact
    for index, source_id in enumerate(profile["sites"]):  # every catchable static live at some point never claims these maps
        open(row, origin_fact(variant, source_id, began=20), {"event": frame, "index": index})
        for map_id in sorted(excluded):
            fact = caught(variant, source_id, map_id=map_id)
            assert consume(row, fact, {"event": frame, "index": 100 + map_id}, variant=variant) is None
        row["attributions"], row["held"] = {}, []
    for source_id in profile["excluded"]:
        with pytest.raises(JournalError, match="origin fact required"):
            open(new_row(), {"kind": "static_origin", "static_id": source_id, "began_frame": 20}, {"event": frame, "index": 0})


@pytest.mark.parametrize("variants", [("red", "blue"), ("blue", "red")], ids=lambda pair: "-".join(pair))
def test_exchange_of_a_granted_mon_keeps_the_grant_pairing_and_ordinals_byte_identical(tmp_path, variants):
    runtime = create_runtime(tmp_path, contract(*variants))
    try:
        start(runtime)
        for player in ("a", "b"):  # Game Corner Abra, prize slot 0 in every title: the only granted species an NPC trade takes
            settle(runtime, player, [source(runtime, player, "grant:game_corner_purchase:0", slot=0)], after=140)
        before = audit(runtime)
        link = before["rules"]["core"]["links"][0]
        assert link["area_id"] == "grant:game_corner_purchase#1"
        grant_row = before["components"][ACQUISITIONS]["a"]["settled"][0]
        party = party_blobs(before["components"]["gen1-inventory-observations"]["a"]["observation"]["source"]["fields"]["party"])
        assert len(party) == 1 and party[0][0] == 148
        rows = [exchange(runtime, "a", party, slot=0, frames=(150, 165, 170), level=party[0][33])]
        _, _, result = settle(runtime, "a", rows, after=180)
        after = audit(runtime)
        statics, acquisitions, exchanges = components(runtime, "a")
        settled = exchanges["settled"][0]
        assert result["exchange_digest"] == digest(exchanges) and "acquisition_digest" not in result  # nothing was pending
        assert settled["rule"] == "link" and settled["area"] == "grant:game_corner_purchase#1"
        assert settled["fact"]["outgoing"]["key"] == grant_row["fact"]["key"] and settled["source_ref"]["index"] == 0
        assert acquisitions["settled"] == before["components"][ACQUISITIONS]["a"]["settled"]
        assert _encode(after["components"][ORDINALS]) == _encode(before["components"][ORDINALS])
        assert after["components"][ORDINALS] == {"grant:game_corner_purchase": {"a": 1, "b": 1}}
        link = after["rules"]["core"]["links"][0]
        assert link["area_id"] == "grant:game_corner_purchase#1" and link["a"]["key"] == settled["fact"]["incoming"]["key"]
        assert link["b"] == before["rules"]["core"]["links"][0]["b"]
        assert after["identities"]["acquisitions"] == before["identities"]["acquisitions"]
        assert set(after["identities"]["members"]) == set(before["identities"]["members"])
        assert settled["fact"]["incoming"]["key"] not in {row["fact"]["key"] for row in acquisitions["settled"] + acquisitions["pending"]}
        # The grant coverage audit: moving the migrated half off the grant's pairing area is refused on restore.
        from server.gen1_runtime_state import Gen1RuntimeState
        tampered = copy.deepcopy(after)
        tampered["components"][EXCHANGES]["a"]["settled"][0]["area"] = "route_2"
        with pytest.raises(JournalError, match="pairing area"):
            verify_exchange_state(Gen1RuntimeState.restore(tampered, data_dir=tmp_path))
    finally:
        runtime.close()


@pytest.mark.parametrize("sparse", [False, True], ids=["settled", "pending"])
def test_npc_exchange_audit_re_decodes_the_committed_batch(tmp_path, sparse):
    """A pending or settled exchange is proved by re-decoding the raw row inside its committed batch."""
    runtime = create_runtime(tmp_path, contract("red", "blue"))
    try:
        start(runtime)
        gift = source(runtime, "a", "grant:game_corner_purchase:0", slot=0)
        settle(runtime, "a", [gift], after=140)
        party = party_blobs(gift["receipt"]["return"]["point"]["party_hex"])
        commit(runtime, "a", [], after=180, sparse=True)
        commit(runtime, "a", [], after=220, sparse=True)
        outgoing = exchange(runtime, "a", party, slot=0, frames=(170, 175, 250), level=party[0][33])
        if sparse:
            point = checkpoint(runtime, "a", [], 260, party=outgoing["receipt"]["return"]["point"]["party_hex"])
            operation, request, _ = commit(runtime, "a", [outgoing], after=260, sparse=True, point=point)
        else:
            operation, request, _ = settle(runtime, "a", [outgoing], after=260)
        stage = runtime.state()
        verify_exchange_journal(runtime.journal, stage)
        entry = stage.document()["components"][EXCHANGES]["a"]
        assert (len(entry["pending"]), len(entry["settled"])) == ((1, 0) if sparse else (0, 1))
        assert entry["operation_id"] == operation and "frame_origin" not in entry
        # Raw event corruption: the journaled receipt bytes change under a consistent digest.
        corrupt = copy.deepcopy(request)
        corrupt["acquisitions"][0]["receipt"]["return"]["frame"] += 1
        text, fingerprint = _encode(corrupt)
        runtime.journal._db.execute("UPDATE events SET request=?, request_digest=? WHERE player=? AND operation_id=?",
                                    (text, fingerprint, "a", operation))
        with pytest.raises(JournalError, match="referenced event request differs"):
            verify_exchange_journal(runtime.journal, stage)
    finally:
        runtime.close()


@pytest.mark.parametrize("variants", PAIRS, ids=lambda pair: "-".join(pair))
def test_failed_static_spends_its_own_area_without_spending_the_wild_route(tmp_path, variants):
    """A fled static (origin, wild begin, battle end, wild end, no capture) dead-zones the static's own area
    through the engine bridge; Route 12 keeps its encounter (the RC rule statics resolve their own area)."""
    runtime = create_runtime(tmp_path, contract(*variants))
    try:
        start(runtime)
        static = STATIC_DATA["titles"][variants[0]]["sites"][SNORLAX]
        operands = {"map_id": static["map_id"], "species_index": static["species"]["clean"][0], "level": static["level"]["values"][0],
                    "cur_opponent": static["species"]["clean"][0]}
        rows = [origin(runtime, "a", arm=125, began=130), wild(runtime, "a", "begin", frame=130, **operands),
                battle_end(runtime, "a", frame=150, result=2), wild(runtime, "a", "end", frame=150, **operands)]
        engine = engine_payload(runtime, "a", [], 1)
        engine["signals"] = [bag(variants[0])]  # ball activation rides the same batch, ahead of the encounter
        _, _, result = observe(runtime, "a", signals=engine, acquisitions=rows, inventory=checkpoint(runtime, "a", [], 160))
        from server.adapters.gen1_rby import _MAP_ID_TO_AREA

        state = runtime.state()
        assert state.rules.area_states.get(SNORLAX) == AreaStatus.DEAD_ZONE
        assert state.rules.area_states.get(_MAP_ID_TO_AREA[static["map_id"]], AreaStatus.UNSEEN) == AreaStatus.UNSEEN
        encounter = next(iter(state.document()["components"][WILD]["players"]["a"]["encounters"].values()))
        assert encounter["phase"] == "no_catch" and encounter["decision"] == {"outcome": "dead_zone", "retire": None}
        assert {"engine_evidence_digest", "static_digest", "wild_encounter_digest"} <= set(result) and "acquisition_digest" not in result
        assert [o["state"] for o in components(runtime, "a")[0]["origins"]] == ["ended"]
        audit(runtime)
    finally:
        runtime.close()


@pytest.mark.parametrize("fault", ["unknown-kind", "static-index", "capture-index", "range-index", "corrupt-origin-row", "corrupt-capture-row",
                                   "corrupt-end-row"])
def test_hostile_kinds_and_provenance_faults_are_refused(tmp_path, monkeypatch, fault):
    runtime = create_runtime(tmp_path, contract("red", "yellow"))
    try:
        start(runtime)
        rows = [origin(runtime, "a"), battle_end(runtime, "a"), static_capture(runtime, "a")]  # end before its capture: tolerated by frame
        if fault == "unknown-kind":
            request = message(runtime, "a", rows + [{"kind": "trade", "receipt": {}}], point=checkpoint(runtime, "a", [], 140, party=party_after(rows)))
            before = runtime.journal.snapshot()
            with pytest.raises(JournalError, match="unknown observation receipt kind"):
                record(runtime, "a", secrets.token_hex(16), request)
            assert runtime.journal.snapshot() == before
            assert STATICS not in runtime.state().document()["components"]
            return
        operation, request, _ = settle(runtime, "a", rows, after=140)
        state = runtime.state()
        audit(runtime)
        document = state.document()
        row = document["components"][STATICS]["a"]
        assert row["origins"][0]["state"] == "consumed" and row["origins"][0]["end"]["source_ref"]["index"] == 1
        if fault.endswith("-index"):
            # A wrong index that still points inside the raw list names a row of another kind; one outside leaves the list.
            target, index, match = {"static-index": (row["origins"][0]["source_ref"], 2, "not admitted"),
                                    "capture-index": (row["origins"][0]["capture"]["source_ref"], 0, "not admitted"),
                                    "range-index": (row["origins"][0]["end"]["source_ref"], 9, "leaves its receipt list")}[fault]
            target["index"] = index
            real = runtime.journal.record
            monkeypatch.setattr(runtime.journal, "record",
                                lambda namespace, key: RecordSnapshot(real(namespace, key).revision, row) if namespace == STATICS else real(namespace, key))
            with pytest.raises(JournalError, match=match):
                verify_static_journal(runtime.journal, SimpleNamespace(document=lambda: document))
        else:
            corrupt = copy.deepcopy(request)
            index = {"corrupt-origin-row": 0, "corrupt-end-row": 1, "corrupt-capture-row": 2}[fault]
            receipt = corrupt["acquisitions"][index]["receipt"]
            if fault == "corrupt-origin-row":
                receipt["began"]["frame"] += 1
            elif fault == "corrupt-capture-row":
                receipt["receipt"]["begin"]["frame"] += 1
            else:
                receipt["end"]["point"]["battle_result"] = 0
            text, fingerprint = _encode(corrupt)
            runtime.journal._db.execute("UPDATE events SET request=?, request_digest=? WHERE player=? AND operation_id=?", (text, fingerprint, "a", operation))
            with pytest.raises(JournalError, match="referenced event request differs"):
                verify_static_journal(runtime.journal, state)
            with pytest.raises(JournalError, match="referenced event request differs"):
                verify_acquisition_journal(runtime.journal, state)
    finally:
        runtime.close()


def test_generic_dispatch_keeps_raw_indices_and_refuses_unknown_or_unadmitted_kinds():
    from server import source_receipts as generic
    seen = []
    rows = [{"kind": "x", "receipt": 1}, {"kind": "y", "receipt": 2}, {"kind": "x", "receipt": 3}]
    facts = generic.decode_rows(rows, reference={"e": 1}, decoder=lambda k, r: seen.append((k, r)) or {"v": r}, catalog=("x", "y"))
    assert [(f["kind"], f["fact"]["v"], f["source_ref"]["index"]) for f in facts] == [("x", 1, 0), ("y", 2, 1), ("x", 3, 2)]
    assert facts[0]["source_ref"]["event"] == {"e": 1} and facts[0]["source_ref"]["event"] is not facts[1]["source_ref"]["event"]
    with pytest.raises(JournalError, match="not admitted here"):
        generic.decode_rows(rows, reference={}, decoder=lambda k, r: r, catalog=("x", "y"), kinds=("x",))
    with pytest.raises(JournalError, match="typed source receipt required"):
        generic.decode_rows([{"kind": "z", "receipt": 1}], reference={}, decoder=lambda k, r: r, catalog=("x", "y"))
    with pytest.raises(JournalError, match="typed source receipt required"):
        generic.decode_rows([{"kind": "x"}], reference={}, decoder=lambda k, r: r, catalog=("x",))
    with pytest.raises(JournalError, match="list required"):
        generic.decode_rows({"kind": "x"}, reference={}, decoder=lambda k, r: r, catalog=("x",))
    assert generic.frames_of({"kind": "x", "receipt": {"f": 7}}, {"first": "f"}, {"x": lambda r, f: ([r["f"]], f["first"])}) == ([7], "f")
    assert not hasattr(generic, "KINDS")  # Generation catalogs belong to their bindings.
