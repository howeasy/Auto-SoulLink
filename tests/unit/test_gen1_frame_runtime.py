"""Generation-specific binding of frame accounting; no policy grants live gameplay."""

import copy
import secrets

import pytest

from server.execution_window import VerifiedExecutionWindow
from server.frame_progress import RECEIPT
from server.gen1_bootstrap_receipt import validate as validate_bootstrap
from server.gen1_frame_runtime import (
    BOOTSTRAP,
    COMPONENT,
    complete,
    reserve,
    seed,
    validate_state,
    verified_held_frame,
)
from server.gen1_run_config import create_runtime
from server.protocol import digest
from server.protocol_journal import JournalError
from tests.unit.test_gen1_bootstrap_receipt import fixture
from tests.unit.test_gen1_engine_signal_runtime import payload
from tests.unit.test_gen1_sessions import contract
from tests.unit.test_gen1_starter_settlement import enroll


@pytest.fixture
def setup(tmp_path):
    runtime = create_runtime(tmp_path, contract("yellow", "yellow"))
    enroll(runtime)
    document = runtime.state().document()
    document["components"][BOOTSTRAP] = {}
    for player in ("a", "b"):
        initial = document["components"]["gen1-initial-observations"][player]
        observation = initial["observation"]
        metadata = initial["metadata"]
        receipt, args = fixture("yellow")
        receipt["begin"]["frame"] = 10
        receipt["end"]["frame"] = 90
        receipt.update(
            context_generation=initial["binding"]["context_generation"],
            physical_instance=metadata["gen1_metadata"]["physical_instance"],
            final_sha1=observation["final_sha1"],
        )
        args.update(
            context_generation=receipt["context_generation"],
            physical_instance=receipt["physical_instance"],
            final_sha1=receipt["final_sha1"],
            source=observation["source"],
            frame=observation["frame"],
        )
        document["components"][BOOTSTRAP][player] = {
            "operation_id": secrets.token_hex(16),
            "payload": receipt,
            "proof": validate_bootstrap(receipt, **args),
        }
        seed(document, player)
    try:
        yield runtime, document
    finally:
        runtime.close()


def proof(document, player="a"):
    binding = document["components"]["gen1-runtime"]["admissions"][player]["binding"]
    return VerifiedExecutionWindow(
        {
            "operation_id": secrets.token_hex(16),
            "operation_digest": "d" * 64,
            "context_generation": binding["context_generation"],
            "binding_digest": binding["binding_digest"],
            "phase": "ordinary",
        },
        "e" * 64,
        10,
        1000,
        digest(document),
    )


def returned(runtime, document):
    grant = document["components"][COMPONENT]["a"]["ledger"]["pending"]
    inventory = copy.deepcopy(
        document["components"]["gen1-initial-observations"]["a"]["observation"]
    )
    inventory["frame"] = grant["before"] + 5
    engine = payload(runtime, "a", ["battle_faint"])
    bundle = {"inventory": inventory, "engine_signals": engine}
    return {
        "schema": RECEIPT,
        "sequence": grant["sequence"],
        "scope": grant["scope"],
        "before": grant["before"],
        "after": inventory["frame"],
        "steps": 5,
        "observations_digest": digest(bundle),
    }, bundle


def test_verified_physical_range_closes_but_observations_must_settle_before_another_grant(setup):
    runtime, document = setup
    assert verified_held_frame(document, "a", 100)
    grant = reserve(document, "a", proof(document))
    assert grant["before"] == 100 and grant["limit"] == 110
    with pytest.raises(JournalError):
        verified_held_frame(document, "a", 100)
    receipt, bundle = returned(runtime, document)
    complete(document, "a", receipt, bundle)
    entry = document["components"][COMPONENT]["a"]
    assert entry["ledger"]["frame"] == 105 and entry["pending_observation"][
        "bundle_digest"
    ] == digest(bundle)
    with pytest.raises(JournalError, match="observations must settle"):
        reserve(document, "a", proof(document))
    with pytest.raises(JournalError):
        verified_held_frame(document, "a", 105)
    assert verified_held_frame(document, "b", 100)
    validate_state(document)


@pytest.mark.parametrize("frame", [99, 100, 106, 110, 111])
def test_monotonic_or_granted_but_unconsumed_source_frame_is_not_enough(setup, frame):
    runtime, document = setup
    reserve(document, "a", proof(document))
    receipt, bundle = returned(runtime, document)
    bundle["engine_signals"]["signals"][0]["frame"] = frame
    receipt["observations_digest"] = digest(bundle)
    before = copy.deepcopy(document)
    with pytest.raises(JournalError, match="outside consumed"):
        complete(document, "a", receipt, bundle)
    assert document == before


@pytest.mark.parametrize("fault", ["host", "frame", "hash", "owner", "cartridge"])
def test_return_cannot_replace_held_inventory_or_physical_owner(setup, fault):
    runtime, document = setup
    reserve(document, "a", proof(document))
    receipt, bundle = returned(runtime, document)
    point = bundle["inventory"]
    if fault == "host":
        point["host"]["process_id"] += 1
    elif fault == "frame":
        point["frame"] += 1
    elif fault == "hash":
        receipt["observations_digest"] = "0" * 64
    elif fault == "owner":
        point["context_generation"] = "b" * 32
    else:
        point["final_sha1"] = "f" * 40
    if fault != "hash":
        receipt["observations_digest"] = digest(bundle)
    before = copy.deepcopy(document)
    with pytest.raises(JournalError):
        complete(document, "a", receipt, bundle)
    assert document == before


def test_unauthorized_extra_frame_cannot_serve_a_held_write_boundary(setup):
    _, document = setup
    with pytest.raises(JournalError, match="step count"):
        verified_held_frame(document, "a", 101)


def test_only_current_typed_policy_proof_may_reserve(setup):
    _, document = setup
    with pytest.raises(JournalError):
        reserve(document, "a", {})
    old = proof(document)
    document["components"]["gen1-runtime"]["admissions"]["a"]["binding"]["binding_digest"] = (
        "f" * 64
    )
    with pytest.raises(JournalError):
        reserve(document, "a", old)


def test_frame_history_cannot_be_seeded_twice_or_rebound(setup):
    _, document = setup
    with pytest.raises(JournalError):
        seed(document, "a")
    document["components"][BOOTSTRAP]["a"]["operation_id"] = "f" * 32
    with pytest.raises(JournalError, match="physical enrollment"):
        validate_state(document)
