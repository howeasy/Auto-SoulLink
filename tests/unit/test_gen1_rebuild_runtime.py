"""C3: whiteout automatic rebuild through the storage-job machinery.

plan()/schedule_rebuild()/plan_reserved() are exercised with a real starter (L1) for identity
and initials, plus hand-built boxed ALIVE pairs (LinkEntry objects never added to party_keys --
"boxed" per Soul Link co-location) standing in for a second real acquisition, exactly as
tests/unit/test_gen1_whiteout.py's own collateral fixture does for C1. completed() is exercised
against a hand-completed "rebuild" storage job (a real, decodable save point showing both
targets in party) rather than driving the full storage_observe/storage_apply ACK round trip --
that full production path (a second REAL registered linked pair, its storage "linked" job
settled) is exercised once, end to end, in test_gen1_whiteout.py's real two-link tests; this file
is about the rebuild scheduler's OWN logic, not re-proving link/storage formation.
"""
import copy
import secrets

import pytest

from server import gen1_rebuild_runtime as rebuild, gen1_semantic_events as ev, gen1_whiteout as wo
from server.gen1_faint_runtime import COMPONENT as FAINT, record_death_obligation
from server.gen1_initial_observation import COMPONENT as INITIAL
from server.gen1_party_codec import PartyCodec
from server.gen1_run_config import create_runtime
from server.protocol_journal import JournalError
from server.state import LinkEntry, LinkStatus, MonInfo
from tests.unit.test_gen1_faint_runtime import paired, signal_batch
from tests.unit.test_gen1_inventory_observation import party_point
from tests.unit.test_gen1_party_codec import make_blob
from tests.unit.test_gen1_sessions import contract
from tests.unit.test_gen1_whiteout import _FakeBlockers, _FakeIdentities, _real_initials


def _fixture(tmp_path, *, num_boxed=1):
    """L1: real starter, real identity, ALIVE, sole party member. num_boxed ALIVE linked pairs,
    boxed on both sides (never added to party_keys). L1 alone faints: a real whiteout with
    nothing to retire as collateral and (if num_boxed) a real rebuild opportunity.

    Each boxed pair's keys are real PartyCodec-decoded keys (from make_blob), not arbitrary
    strings, so a hand-completed job's "after" save point can later be decoded back to them
    (test_completed_* below) exactly as gen1_storage_policy.location() requires.
    """
    runtime = create_runtime(tmp_path, contract("red", "red"))
    paired(runtime)
    stage = runtime.state()
    initials = _real_initials(runtime)
    rules = stage.rules
    link1 = rules.links[0]
    trigger_key = link1.a.key
    rules.pokeballs_obtained["a"] = rules.pokeballs_obtained["b"] = True

    codec = PartyCodec("red")
    boxed_pairs = []
    boxed_blobs = []
    identity_links = {"1" * 32: {"members": [link1.a.key, link1.b.key]}}
    for i in range(num_boxed):
        blob_a = make_blob(codec, dv=0x7000 + i, otid=0x1000 + i, species=0x07)
        blob_b = make_blob(codec, dv=0x8000 + i, otid=0x2000 + i, species=0x6A)
        key_a, key_b = codec.validate_blob(blob_a).key, codec.validate_blob(blob_b).key
        entry = LinkEntry(area_id=f"route_{i + 2}", a=MonInfo(key=key_a, level=5, species=0x07),
                           b=MonInfo(key=key_b, level=7, species=0x6A), status=LinkStatus.ALIVE)
        rules.links.append(entry)
        rules._index_entry(entry)
        boxed_pairs.append((key_a, key_b))
        boxed_blobs.append((blob_a, blob_b))
        identity_links[f"{i + 2}" * 32] = {"members": [key_a, key_b]}

    batch = signal_batch(runtime, "a")  # activation + battle_faint on the sole party mon
    entry = {"operation_id": secrets.token_hex(16), "payload": batch}
    index = 1
    signal_row = batch["signals"][index]

    immediate = rules.handle_event("a", ev.faint_event(key=trigger_key, level=link1.a.level))
    assert link1.status == LinkStatus.DEAD
    drained = rules.take_commands("a", immediate)
    trigger_command = next(c for c in drained["b"] if c.get("cmd") == "force_faint")

    identities = _FakeIdentities(identity_links)
    document = {
        "components": {
            INITIAL: initials,
            FAINT: {"activations": {"a": {"engine_record": entry, "index": 0}}, "deaths": {}},
        },
        "identities": identities.document(),
    }
    component = document["components"][FAINT]

    class _Stage:
        def document(self):
            return document

    fake = _Stage()
    fake.rules = rules
    fake.identities = identities
    fake.barrier = _FakeBlockers()

    trigger_death_id = record_death_obligation(
        fake, document, component, {"a": [], "b": []}, player="a", partner="b", entry=entry,
        index=index, key=trigger_key, link=link1, command=trigger_command, at=link1.killed_at,
    )
    # _busy() (gen1_storage_runtime.py) holds any rebuild job while the trigger's own force_faint
    # is still pending_issue/pending_faint (spec (3): finish collaterals first). This fixture is
    # about the rebuild scheduler's own logic, not faint-ACK verification (covered elsewhere), so
    # simulate "already ACKed" directly rather than driving the full receipt/verification cycle.
    component["deaths"][trigger_death_id]["phase"] = "pending_memorial"
    return {
        "runtime": runtime, "fake": fake, "document": document, "entry": entry, "index": index,
        "signal": signal_row, "trigger_key": trigger_key, "trigger_death_id": trigger_death_id,
        "boxed_pairs": boxed_pairs, "boxed_blobs": boxed_blobs, "initials": initials,
    }


def _trigger_whiteout(f):
    """Populate rules.rebuild_pending["a"] the way settle_whiteout would, without also running
    its auto-schedule_rebuild call -- for tests that want to drive plan()/schedule_rebuild()
    themselves, one step at a time."""
    from server.gen1_semantic_events import whiteout_event

    f["fake"].rules.handle_event("a", whiteout_event(area_id="oaks_lab"))


def test_plan_captures_the_shared_engines_rebuild_pick(tmp_path):
    f = _fixture(tmp_path, num_boxed=2)
    try:
        feedback = wo.settle_whiteout(
            f["fake"], f["document"], "a", f["entry"], f["index"], f["signal"],
            trigger_death_id=f["trigger_death_id"], trigger_key=f["trigger_key"],
        )
        component = f["document"]["components"][rebuild.COMPONENT]
        assert len(component["plans"]) == 1
        plan_row = next(iter(component["plans"].values()))
        assert plan_row["initiator"] == "a" and plan_row["phase"] == "pending"
        assert [p["keys"]["a"] for p in plan_row["ordered_pairs"]] == [k for k, _ in f["boxed_pairs"]]
        assert [p["keys"]["b"] for p in plan_row["ordered_pairs"]] == [k for _, k in f["boxed_pairs"]]
        for pair in plan_row["ordered_pairs"]:
            assert pair["completed_ref"] is None
        # The first pair got a real storage "rebuild" job started in the same call.
        assert plan_row["ordered_pairs"][0]["job_id"] is not None
        assert plan_row["ordered_pairs"][1]["job_id"] is None  # one pair job at a time
        storage = f["document"]["components"]["gen1-storage-settlement"]["jobs"]
        assert len(storage) == 1
        job = next(iter(storage.values()))
        assert job["kind"] == "rebuild" and set(job["keys"].values()) == set(f["boxed_pairs"][0])
        # Both sides get a storage_observe -- surfaced through settle_whiteout's own return.
        b_observes = [c for c in feedback["b"] if c.get("cmd") == "storage_observe"]
        assert len(b_observes) == 1 and b_observes[0]["job_id"] == job["id"]
    finally:
        f["runtime"].close()


def test_plan_rejects_a_pick_that_differs_from_the_shared_engines_queue(tmp_path):
    f = _fixture(tmp_path, num_boxed=1)
    try:
        _trigger_whiteout(f)
        rb = f["fake"].rules.rebuild_pending["a"]
        assert rb  # a real pick exists
        bogus = {"a": [{"cmd": "party_mon", "key": "WRONG:0000:01"}], "b": []}
        with pytest.raises(JournalError, match="differs from the shared engine's queued picks"):
            rebuild.plan(f["fake"], f["document"], "a", f["entry"], f["index"], bogus,
                         whiteout_id="1" * 32)
    finally:
        f["runtime"].close()


def test_plan_never_reselects_for_the_same_whiteout(tmp_path):
    f = _fixture(tmp_path, num_boxed=1)
    try:
        _trigger_whiteout(f)
        rb = f["fake"].rules.rebuild_pending["a"]
        captured = {
            "a": [{"cmd": "party_mon", "key": k} for k in rb["queued_keys"]],
            "b": [{"cmd": "party_mon", "key": k} for k in rb["queued_partner_keys"]],
        }
        whiteout_id = "9" * 32
        rebuild.plan(f["fake"], f["document"], "a", f["entry"], f["index"], captured,
                     whiteout_id=whiteout_id)
        component = f["document"]["components"][rebuild.COMPONENT]
        before = copy.deepcopy(component["plans"][whiteout_id])
        # Same pick, same whiteout_id: idempotent no-op, never reselected.
        rebuild.plan(f["fake"], f["document"], "a", f["entry"], f["index"], captured,
                     whiteout_id=whiteout_id)
        assert component["plans"][whiteout_id] == before
        # The persisted plan now differs from a fresh pick under the SAME whiteout_id (e.g. a
        # tampered/replayed document) -- refused outright, never silently reselected.
        component["plans"][whiteout_id]["ordered_pairs"][0]["keys"]["a"] = "TAMPERED:0000:01"
        with pytest.raises(JournalError, match="cannot be reselected"):
            rebuild.plan(f["fake"], f["document"], "a", f["entry"], f["index"], captured,
                         whiteout_id=whiteout_id)
    finally:
        f["runtime"].close()


def test_plan_reserved_blocks_unrelated_storage_from_taking_ownership(tmp_path):
    f = _fixture(tmp_path, num_boxed=1)
    try:
        _trigger_whiteout(f)
        rb = f["fake"].rules.rebuild_pending["a"]
        captured = {
            "a": [{"cmd": "party_mon", "key": k} for k in rb["queued_keys"]],
            "b": [{"cmd": "party_mon", "key": k} for k in rb["queued_partner_keys"]],
        }
        # plan() only -- no schedule_rebuild call, so the pair is reserved but has no job yet
        # and nothing else is _busy.
        rebuild.plan(f["fake"], f["document"], "a", f["entry"], f["index"], captured,
                     whiteout_id="9" * 32)
        key_a, key_b = f["boxed_pairs"][0]
        assert rebuild.plan_reserved(f["document"], [key_a]) is True
        assert rebuild.plan_reserved(f["document"], ["unrelated:0000:00"]) is False

        from server.gen1_storage_runtime import _job

        with pytest.raises(JournalError, match="reserved for a pending rebuild"):
            _job(f["fake"], f["document"], {"fake": "origin"}, "pc", {"a": key_a}, actor="a")
    finally:
        f["runtime"].close()


def _real_point_with(initials, player, extra_blob):
    """A real, decodable save point for `player` whose party gains one more slot (`extra_blob`,
    a 66-byte make_blob-shaped record) -- exactly the shape gen1_storage_runtime's own "after"
    receipts carry, built without driving the full storage_observe/storage_apply ACK cycle.
    """
    point = copy.deepcopy(initials[player]["observation"]["source"])
    variant = point["variant"]
    raw = bytes.fromhex(point["fields"]["party"])
    existing = [
        raw[8 + 44 * i : 52 + 44 * i] + raw[272 + 11 * i : 283 + 11 * i] + raw[338 + 11 * i : 349 + 11 * i]
        for i in range(raw[0])
    ]
    point["fields"]["party"] = party_point(variant, [*existing, extra_blob])["fields"]["party"]
    return point


def test_completed_feeds_sync_retrieve_done_and_advances_to_the_next_pair(tmp_path):
    f = _fixture(tmp_path, num_boxed=2)
    document, fake = f["document"], f["fake"]
    try:
        wo.settle_whiteout(fake, document, "a", f["entry"], f["index"], f["signal"],
                           trigger_death_id=f["trigger_death_id"], trigger_key=f["trigger_key"])
        component = document["components"][rebuild.COMPONENT]
        plan_row = next(iter(component["plans"].values()))
        pair0 = plan_row["ordered_pairs"][0]
        job = document["components"]["gen1-storage-settlement"]["jobs"][pair0["job_id"]]

        key_a, key_b = f["boxed_pairs"][0]
        extra_a, extra_b = f["boxed_blobs"][0]
        point_a = _real_point_with(f["initials"], "a", extra_a)
        point_b = _real_point_with(f["initials"], "b", extra_b)
        job["prepared"] = {
            "a": {"after": point_a, "before": point_a, "frame": 300, "reserved_boxes": [],
                  "context_generation": "a" * 32, "final_sha1": "0" * 40},
            "b": {"after": point_b, "before": point_b, "frame": 300, "reserved_boxes": [],
                  "context_generation": "b" * 32, "final_sha1": "0" * 40},
        }
        job["writes"] = {"a": {"fake": "ref-a"}, "b": {"fake": "ref-b"}}
        job["resolution"] = {"refusal": None, "directions": {"a": "withdraw", "b": "withdraw"}}
        job["complete"] = True

        before_party = {p: set(fake.rules.party_keys[p]) for p in ("a", "b")}
        commands = rebuild.completed(fake, document, job)

        assert key_a in fake.rules.party_keys["a"] and key_b in fake.rules.party_keys["b"]
        assert fake.rules.party_keys["a"] - before_party["a"] == {key_a}
        assert pair0["completed_ref"] == {"a": {"fake": "ref-a"}, "b": {"fake": "ref-b"}}
        assert plan_row["phase"] == "pending"  # pair 1 is still outstanding
        # completed() tried to advance the plan: pair 1 now has its own job.
        assert plan_row["ordered_pairs"][1]["job_id"] is not None
        assert any(c.get("cmd") == "storage_observe" for c in commands["a"] + commands["b"])
    finally:
        f["runtime"].close()


def test_completed_refuses_an_unresolved_or_partial_job(tmp_path):
    f = _fixture(tmp_path, num_boxed=1)
    document, fake = f["document"], f["fake"]
    try:
        wo.settle_whiteout(fake, document, "a", f["entry"], f["index"], f["signal"],
                           trigger_death_id=f["trigger_death_id"], trigger_key=f["trigger_key"])
        component = document["components"][rebuild.COMPONENT]
        plan_row = next(iter(component["plans"].values()))
        pair0 = plan_row["ordered_pairs"][0]
        job = document["components"]["gen1-storage-settlement"]["jobs"][pair0["job_id"]]
        job["prepared"] = {"a": {"after": {}}}  # missing "b": not both sides confirmed
        job["resolution"] = {"refusal": None}
        with pytest.raises(JournalError, match="requires both targets confirmed"):
            rebuild.completed(fake, document, job)
    finally:
        f["runtime"].close()
