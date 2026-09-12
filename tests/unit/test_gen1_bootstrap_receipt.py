import copy
import subprocess
import sys
from pathlib import Path

import pytest

from server.gen1_bootstrap_receipt import DATA, SCHEMA, projection, validate
from server.protocol_journal import JournalError
from tests.unit.test_gen1_initial_observation import source

ROOT = Path(__file__).resolve().parents[2]


def fixture(variant="yellow"):
    point = source(variant)
    profile = DATA["titles"][variant]
    receipt = {
        "schema": SCHEMA,
        "source_sha256": DATA["sha256"],
        "variant": variant,
        "context_generation": "a" * 32,
        "physical_instance": "1" * 32,
        "final_sha1": profile["clean_sha1"],
    }
    for kind, frame in [("begin", 100), ("end", 900)]:
        site = profile["sites"][kind]
        receipt[kind] = {"frame": frame, "pc": site["address"], "bank": site["bank"], "sp": 0xDFFE}
    receipt["end"]["point"] = projection(point)
    arguments = {
        "variant": variant,
        "identity": {"ot_id": "0000", "trainer_name": "SAME"},
        "context_generation": "a" * 32,
        "physical_instance": "1" * 32,
        "final_sha1": profile["clean_sha1"],
        "source": point,
        "frame": 950,
    }
    return receipt, arguments


@pytest.mark.parametrize("variant", ["red", "blue", "yellow"])
def test_normal_new_game_proof_is_read_only_and_bound_to_enrollment(variant):
    receipt, args = fixture(variant)
    before = copy.deepcopy((receipt, args))
    result = validate(receipt, **args)
    assert result["entry_frame"] < result["return_frame"] <= result["frame"]
    assert (receipt, args) == before


@pytest.mark.parametrize(
    "fault",
    [
        "missing_entry",
        "wrong_bank",
        "wrong_site",
        "same_frame",
        "future_frame",
        "stack",
        "context",
        "owner",
        "rom",
        "source_pin",
        "variant",
        "identity",
        "later_party",
        "later_box",
        "late_seen",
        "prior_seen",
        "prior_box",
        "boolean_frame",
    ],
)
def test_bootstrap_refuses_unproven_or_changed_initial_history(fault):
    receipt, args = fixture()
    if fault == "missing_entry":
        del receipt["begin"]
    elif fault == "wrong_bank":
        receipt["begin"]["bank"] += 1
    elif fault == "wrong_site":
        receipt["begin"]["pc"] += 5  # Debug entry bypasses normal entry.
    elif fault == "same_frame":
        receipt["end"]["frame"] = receipt["begin"]["frame"]
    elif fault == "future_frame":
        receipt["end"]["frame"] = args["frame"] + 1
    elif fault == "stack":
        receipt["end"]["sp"] -= 2
    elif fault == "context":
        receipt["context_generation"] = "b" * 32
    elif fault == "owner":
        receipt["physical_instance"] = "2" * 32
    elif fault == "rom":
        receipt["final_sha1"] = "f" * 40
    elif fault == "source_pin":
        receipt["source_sha256"] = "f" * 64
    elif fault == "variant":
        args["variant"] = "red"
    elif fault == "identity":
        args["identity"]["ot_id"] = "FFFF"
    elif fault in ("later_party", "later_box"):
        name = fault.removeprefix("later_")
        args["source"]["fields"][name] = "01" + args["source"]["fields"][name][2:]
    elif fault in ("late_seen", "prior_seen", "prior_box"):
        key = "current_box" if fault == "prior_box" else "seen"
        row = DATA["titles"]["yellow"]["fields"][key]
        from server.gen1_full_save import layout

        offset = row["address"] - layout("yellow")["regions"]["main"]["address"]
        raw = bytearray.fromhex(args["source"]["fields"]["main"])
        raw[offset] = 1
        args["source"]["fields"]["main"] = raw.hex().upper()
        if fault.startswith("prior_"):
            receipt["end"]["point"] = projection(args["source"])
    elif fault == "boolean_frame":
        receipt["begin"]["frame"] = True
    with pytest.raises(JournalError):
        validate(receipt, **args)


def test_bootstrap_does_not_claim_ownership_of_old_sram():
    receipt, args = fixture()
    first = validate(receipt, **args)
    args["source"]["cart_hex"] = "42" * 0x8000
    second = validate(receipt, **args)
    assert first["receipt_digest"] == second["receipt_digest"]
    assert first["enrollment_source_digest"] != second["enrollment_source_digest"]


def test_bootstrap_sites_regenerate_from_canonical_sources():
    subprocess.run(
        [sys.executable, str(ROOT / "tools/gen_gen1_bootstrap_sites.py"), "--check"],
        cwd=ROOT,
        check=True,
    )
