"""Resumed enrollment: each player of a run resumed from a closed predecessor must present the
witnessed save and a witnessed CONTINUE before the inherited rules history is allowed to stand."""
import copy
import hashlib
import json
import secrets
from pathlib import Path

import pytest

from server.gen1_faint_runtime import COMPONENT as FAINTS, verify_state as verify_faints
from server.gen1_run_config import create_runtime, open_runtime
from server.gen1_run_resume import COMPONENT, audit_predecessor
from server.gen1_runtime_state import Gen1RuntimeState
from server.gen1_wild_encounter_runtime import _activation
from server.protocol_journal import JournalError
from tests.unit.test_gen1_initial_observation import admit, observation, send
from tests.unit.test_gen1_run_resume import entry, predecessor
from tests.unit.test_gen1_sessions import contract

CONTINUE = json.loads((Path(__file__).resolve().parents[2] / "data/games/gen1_rby/continue_sites.json").read_text())


def continue_witness(runtime, player, *, frame=90):
    variant = runtime.contract["players"][player]["variant"]
    sites = CONTINUE["titles"][variant]["sites"]
    stages = {}
    for offset, kind in enumerate(("load", "loaded", "chose", "pressed", "enter")):
        stages[kind] = {"frame": frame - 10 + 2 * offset, "pc": sites[kind]["address"], "bank": sites[kind]["bank"], "sp": 0xDFF0}
    stages["loaded"]["status"] = 2
    return {"schema": "rby-continue-receipt-v1", "source_sha256": CONTINUE["sha256"], "variant": variant,
            "context_generation": player * 32, "physical_instance": ("1" if player == "a" else "2") * 32,
            "final_sha1": runtime.contract["players"][player]["final_rom_sha1"], **stages}


def resumed_payload(runtime, player, *, cart_hex=None):
    payload = observation(runtime, player)
    if cart_hex is not None:
        payload["source"]["cart_hex"] = cart_hex
    payload["continue_witness"] = continue_witness(runtime, player)
    return payload


def digest_of(cart_hex):
    return hashlib.sha256(cart_hex[0x498 * 2:].encode("ascii")).hexdigest()


def build_successor(tmp_path):
    """A predecessor whose witnessed saves are exactly the fixture observation's CartRAM image."""
    cart_hex = "FF" * 0x8000  # tests.unit.test_gen1_initial_observation.source()
    pred = tmp_path / "pred"
    predecessor(pred, digests={"a": digest_of(cart_hex), "b": digest_of(cart_hex)})
    audit = audit_predecessor(pred, registry_entry=entry())
    assert audit.ok, audit.reasons
    return create_runtime(tmp_path / "next", contract("red", "blue"), resume=audit.resume_record())


@pytest.fixture
def successor(tmp_path):
    runtime = build_successor(tmp_path)
    try:
        yield runtime
    finally:
        runtime.close()


def test_creation_seeds_rules_resume_contract_and_inherited_activation(successor):
    document = successor.state().document()
    assert document["rules"]["core"]["links"][0]["area_id"] == "oaks_lab"
    assert document["rules"]["core"]["pokeballs_obtained"] == {"a": True, "b": True}
    resume = document["components"][COMPONENT]
    assert resume["from_run"] == "run_20260913_000000_abcdef" and resume["pending"] == {"a": True, "b": True}
    assert set(resume["required"]) == {"a", "b"} and set(resume) >= {"from_run", "required", "pending", "imported_at"}
    for player in ("a", "b"):
        activation = document["components"][FAINTS]["activations"][player]
        assert activation["index"] is None and activation["engine_record"] is None
        assert activation["inherited"]["from_run"] == "run_20260913_000000_abcdef"
        assert activation["inherited"]["digest"] == resume["required"][player]["digest"]
        assert _activation(document, player, 10 ** 6) is False  # no enrollment yet: not effective
    assert not successor.journal.pending_ids("a") and not successor.journal.pending_ids("b")
    spec = json.loads((Path(successor.data_dir) / "gen1_runtime.json").read_text())
    assert spec["initial_observations"] is True


def test_missing_continue_witness_is_refused(successor):
    owner = admit(successor, "a")
    before = successor.journal.snapshot()
    with pytest.raises(JournalError, match="witnessed CONTINUE"):
        send(successor, "a", owner, observation(successor, "a"))
    assert successor.journal.snapshot() == before


@pytest.mark.parametrize("fault", ["schema", "status", "order", "site", "context", "late"])
def test_malformed_or_new_game_witness_is_refused(successor, fault):
    owner = admit(successor, "a")
    payload = resumed_payload(successor, "a")
    witness = payload["continue_witness"]
    if fault == "schema":
        witness["schema"] = "rby-bootstrap-receipt-v1"
    elif fault == "status":
        witness["loaded"]["status"] = 1
    elif fault == "order":
        witness["enter"]["frame"] = witness["load"]["frame"] - 1
    elif fault == "site":
        witness["chose"]["pc"] += 1
    elif fault == "context":
        witness["context_generation"] = "f" * 32
    else:
        witness["enter"]["frame"] = payload["frame"] + 1
    before = successor.journal.snapshot()
    with pytest.raises(JournalError, match="witnessed CONTINUE"):
        send(successor, "a", owner, payload)
    assert successor.journal.snapshot() == before


def test_digest_mismatch_is_refused(successor):
    owner = admit(successor, "a")
    before = successor.journal.snapshot()
    with pytest.raises(JournalError, match="save projection differs"):
        send(successor, "a", owner, resumed_payload(successor, "a", cart_hex="FE" * 0x8000))
    assert successor.journal.snapshot() == before


def test_matching_save_and_continue_enroll_and_journal_the_resume(successor):
    owner = admit(successor, "a")
    operation = secrets.token_hex(16)
    result = send(successor, "a", owner, resumed_payload(successor, "a"), operation)
    assert result["ack"] == "ACK"
    document = successor.state().document()
    resume = document["components"][COMPONENT]
    assert resume["pending"] == {"a": False, "b": True}
    record = resume["enrolled"]["a"]
    assert record["from_run"] == "run_20260913_000000_abcdef" and record["digest"] == resume["required"]["a"]["digest"]
    assert record["witness_index"] == resume["required"]["a"]["witness_index"]
    assert record["binding"] == document["components"]["gen1-initial-observations"]["a"]["binding"]
    assert record["continue_witness"]["loaded"]["status"] == 2
    assert successor.journal.record(COMPONENT, record["record_key"]).value == record
    # The inherited history stands: links and ball activation survive the enrollment.
    assert document["rules"]["core"]["links"][0]["status"] == "alive"
    assert document["rules"]["core"]["pokeballs_obtained"]["a"] is True
    assert _activation(document, "a", 100) is True and _activation(document, "a", 99) is False
    assert _activation(document, "b", 100) is False
    # Replay is idempotent; a second attempt is immutable like any enrollment.
    before = successor.journal.snapshot()
    send(successor, "a", owner, resumed_payload(successor, "a"), operation)
    assert successor.journal.snapshot() == before
    with pytest.raises(JournalError, match="immutable"):
        send(successor, "a", owner, resumed_payload(successor, "a"))
    # The committed state restores through every verifier, including the faint activation shape.
    restored = Gen1RuntimeState.restore(document, data_dir=successor.data_dir)
    verify_faints(restored)
    for damage in ("activation", "witness", "save"):
        damaged = copy.deepcopy(document)
        if damage == "activation":
            damaged["components"][FAINTS]["activations"]["a"]["inherited"]["digest"] = "0" * 64
        elif damage == "witness":
            damaged["components"][COMPONENT]["enrolled"]["a"]["continue_witness"]["loaded"]["status"] = 1
        else:
            damaged["components"][COMPONENT]["required"]["a"]["digest"] = "0" * 64
            damaged["components"][COMPONENT]["enrolled"]["a"]["digest"] = "0" * 64
            damaged["components"][FAINTS]["activations"]["a"]["inherited"]["digest"] = "0" * 64
        with pytest.raises(JournalError):
            Gen1RuntimeState.restore(damaged, data_dir=successor.data_dir)


def test_both_players_resume_and_the_run_reopens(tmp_path):
    successor = build_successor(tmp_path)
    try:
        for player in ("a", "b"):
            owner = admit(successor, player)
            send(successor, player, owner, resumed_payload(successor, player))
        document = successor.state().document()
        assert document["components"][COMPONENT]["pending"] == {"a": False, "b": False}
        assert set(document["components"]["gen1-initial-observations"]) == {"a", "b"}
        directory = successor.data_dir
    finally:
        successor.close()
    reopened = open_runtime(directory)
    try:
        assert reopened.state().document()["components"][COMPONENT] == document["components"][COMPONENT]
    finally:
        reopened.close()


def test_fresh_run_refuses_a_continue_witness_and_keeps_its_guards(tmp_path):
    runtime = create_runtime(tmp_path, contract("red", "blue"))
    try:
        owner = admit(runtime, "a")
        payload = resumed_payload(runtime, "a")
        with pytest.raises(JournalError, match="continue witness"):
            send(runtime, "a", owner, payload)
        assert COMPONENT not in runtime.state().document()["components"]
    finally:
        runtime.close()
