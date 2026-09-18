"""Unit tests for the pureRGB build lock — no network, no build.

Checks that data/purergb_sources.lock.json, data/purergb/build_provenance.json and the
committed data/purergb/*.sym|*.map agree with each other and with the pins recorded in
docs/purergb/PLAN.md (see tools/build_purergb_syms.py for how they were produced)."""
import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools"))
from _build_tools_bootstrap import RGBDS_PINS  # noqa: E402
from build_purergb_syms import load_lock  # noqa: E402

LOCK_PATH = REPO_ROOT / "data" / "purergb_sources.lock.json"
PROVENANCE_PATH = REPO_ROOT / "data" / "purergb" / "build_provenance.json"

PINNED_SHA1 = {
    "pokered": "2e94d09c1e16a57eb079404c030f26fdeeac949d",
    "pokeblue": "d419fe244fa17196f7df46ddab47c840e7573652",
    "pokegreen": "fe4c63a67c8b28770916cc7b1788f9eeb04ccf02",
}
PINNED_COMMIT = "7e7a46535ca332ad24ecb02e326ea2f75e79ebb9"


def _provenance() -> dict:
    return json.loads(PROVENANCE_PATH.read_text(encoding="utf-8"))


def test_load_lock_matches_plan_pins():
    lock = load_lock()
    assert lock["source"]["commit"] == PINNED_COMMIT
    assert lock["rgbds_version"] == "v1.0.3"
    assert lock["w64devkit_version"] == "2.10.0"
    for key, sha1 in PINNED_SHA1.items():
        assert lock["outputs"][key]["sha1"] == sha1


def test_lock_matches_build_provenance():
    lock = load_lock()
    provenance = _provenance()
    assert provenance["schema"] == "purergb-build-provenance-v1"
    assert provenance["source"]["commit"] == lock["source"]["commit"]
    for key, spec in lock["outputs"].items():
        assert provenance["roms"][key]["sha1"] == spec["sha1"]


def test_committed_sym_and_map_match_provenance_hashes():
    provenance = _provenance()
    for name, expected_sha256 in provenance["symbols"].items():
        data = (REPO_ROOT / "data" / "purergb" / name).read_bytes()
        assert hashlib.sha256(data).hexdigest() == expected_sha256, name


def test_bootstrap_has_both_rgbds_pins():
    assert RGBDS_PINS["v1.0.1"]["sha256"] == (
        "554187d717cca78136a81d167107ea15742e7f622797d0b339c0bfb7ab749097"
    )
    assert RGBDS_PINS["v1.0.3"]["sha256"] == (
        "b66c23cb6d073dd3866ea30ef1ca5164549e0dae9ebe771957aff25e2658b0e3"
    )
