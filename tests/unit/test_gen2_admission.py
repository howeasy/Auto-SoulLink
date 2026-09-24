"""P1 matrix falsifiers: source evidence never grants runtime admission."""
from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import gen_gen2_admission as admission  # noqa: E402


def digest(value):
    return hashlib.sha256((json.dumps(value, indent=2) + "\n").encode()).hexdigest()


@pytest.fixture
def lock():
    value = json.loads((ROOT / "data/gen2_sources.lock.json").read_text())
    for row in value["outputs"].values():
        row.update(state="UNBUILT", sym_sha256=None, map_sha256=None)
    return value


@pytest.fixture
def built(lock):
    """Synthetic SOURCE receipt, for the validator model only."""
    for name, row in lock["outputs"].items():
        row.update(state="BUILT", sym_sha256=hashlib.sha256(name.encode()).hexdigest(),
                   map_sha256=hashlib.sha256((name + " map").encode()).hexdigest())
    receipt = {
        "schema": "gen2-build-provenance-v1", "schema_version": 1,
        "evidence_level": "SOURCE", "lock_sha256": digest(lock),
        "sources": {name: {"url": row["url"], "commit": row["commit"], "make_targets": row["make_targets"], "clean": True}
                    for name, row in lock["sources"].items()},
        "toolchain": {
            "rgbds": {"version": "v1.0.3", "binaries": {
                name: {"version": name + " v1.0.3", "sha256": "1" * 64}
                for name in ("rgbasm", "rgblink", "rgbfix", "rgbgfx")}},
            "build_tools": {"binaries": {
                name: {"version": "fixture 1.0", "sha256": "2" * 64}
                for name in ("make", "gcc", "sh")}},
            "w64devkit_requested_version": "2.10.0",
        },
        "roms": {name: {key: row[key] for key in ("source", "filename", "sha1")}
                 for name, row in lock["outputs"].items()},
        "symbols": {f"{name}.{suffix}": row[f"{suffix}_sha256"]
                    for name, row in lock["outputs"].items() for suffix in ("sym", "map")},
    }
    return lock, receipt


def test_expected_pins_are_independent_title_facts(lock):
    assert lock["sources"]["pokecrystal"]["commit"] == "7a7881d0d62e0ddbd82dcf10e7116807487ac651"
    assert lock["sources"]["pokegold"]["commit"] == "656583c939d30f920a316177311a502dd222b57c"
    assert {k: v["sha1"] for k, v in lock["outputs"].items()} == {
        "pokecrystal": "f4cd194bdee0d04ca4eac29e09b8e4e9d818c133",
        "pokecrystal11": "f2f52230b536214ef7c9924f483392993e226cfb",
        "pokegold": "d8b8a3600a465308c9953dfa04f0081c05bdcb94",
        "pokesilver": "49b163f7e57702bc939d642a18f591de55d92dae",
    }


def test_initial_catalog_is_hashless_and_does_not_imply_admission(lock):
    matrices = admission.build_matrices(lock)
    assert set(matrices) == {"gen2_crystal", "gen2_gold", "gen2_silver"}
    for matrix in matrices.values():
        assert matrix["gate"] == {"id": "G1", "state": "PENDING"}
        assert all(r["status"] == "PLANNED" and "sha1" not in r for r in matrix["artifacts"])
        assert matrix["refused_kinds"] == ["archipelago", "randomized", "unknown"]
        admission.validate_matrix(matrix, lock)
    rows = matrices["gen2_crystal"]["artifacts"]
    assert [(r["revision"], r["selection"]) for r in rows if r["kind"] == "clean"] == [
        ("1.0", "SELECTED"), ("1.1", "BUILD_ONLY")]


def test_verified_source_receipt_builds_all_four_but_admits_none(built):
    lock, receipt = built
    matrices = admission.build_matrices(lock, receipt)
    clean = [r for m in matrices.values() for r in m["artifacts"] if r["kind"] == "clean"]
    assert len(clean) == 4
    assert all(r["status"] == "BUILT" and len(r["sha1"]) == 40 for r in clean)
    for matrix in matrices.values():
        admission.validate_matrix(matrix, lock, receipt)
        assert all(r["status"] == "PLANNED" and "sha1" not in r
                   for r in matrix["artifacts"] if r["kind"] != "clean")


@pytest.mark.parametrize("status", ["BUILT", "ADMITTED"])
def test_hashless_claimed_artifact_refused(lock, status):
    matrix = admission.build_matrices(lock)["gen2_crystal"]
    matrix["artifacts"][0]["status"] = status
    with pytest.raises(ValueError):
        admission.validate_matrix(matrix, lock)


@pytest.mark.parametrize("kind", ["clean", "overlay", "ghost"])
def test_planned_hash_refused(lock, kind):
    matrix = admission.build_matrices(lock)["gen2_gold"]
    next(r for r in matrix["artifacts"] if r["kind"] == kind)["sha1"] = "a" * 40
    with pytest.raises(ValueError, match="PLANNED"):
        admission.validate_matrix(matrix, lock)


@pytest.mark.parametrize("field,value", [("kind", "archipelago"), ("kind", "randomized"),
                                          ("revision", "1.1"), ("selection", "BUILD_ONLY")])
def test_selected_crystal_identity_is_not_inferred(lock, field, value):
    matrix = admission.build_matrices(lock)["gen2_crystal"]
    matrix["artifacts"][0][field] = value
    with pytest.raises(ValueError):
        admission.validate_matrix(matrix, lock)


def test_built_hash_requires_receipt_and_separate_g1_acceptance(built):
    lock, receipt = built
    matrix = admission.build_matrices(lock, receipt)["gen2_crystal"]
    with pytest.raises(ValueError, match="provenance"):
        admission.validate_matrix(matrix, lock)
    matrix["artifacts"][0]["status"] = "ADMITTED"
    with pytest.raises(ValueError, match="G1"):
        admission.validate_matrix(matrix, lock, receipt)


@pytest.mark.parametrize("mutation", ["dirty", "source", "rom", "symbols", "tool", "lock", "layer", "missing"])
def test_contradictory_provenance_refused(built, mutation):
    lock, receipt = built
    if mutation == "dirty":
        receipt["sources"]["pokegold"]["clean"] = False
    elif mutation == "source":
        receipt["sources"]["pokecrystal"]["commit"] = "0" * 40
    elif mutation == "rom":
        receipt["roms"]["pokesilver"]["sha1"] = lock["outputs"]["pokegold"]["sha1"]
    elif mutation == "symbols":
        receipt["symbols"]["pokecrystal.sym"] = "0" * 64
    elif mutation == "tool":
        receipt["toolchain"]["rgbds"]["binaries"]["rgbgfx"]["version"] = "rgbgfx v0.9.4"
    elif mutation == "lock":
        receipt["lock_sha256"] = "0" * 64
    elif mutation == "layer":
        receipt["evidence_level"] = "PHYSICAL"
    else:
        del receipt["roms"]["pokecrystal11"]
    with pytest.raises(ValueError):
        admission.build_matrices(lock, receipt)


@pytest.mark.parametrize("mutation", ["source", "rom", "tool", "state", "partial", "legacy"])
def test_unpinned_lock_refused(lock, mutation):
    if mutation == "source":
        lock["sources"]["pokecrystal"]["commit"] = "0" * 40
    elif mutation == "rom":
        lock["outputs"]["pokecrystal"]["sha1"] = "0" * 40
    elif mutation == "tool":
        lock["rgbds_version"] = "v0.9.4"
    elif mutation == "state":
        del lock["outputs"]["pokegold"]["state"]
    elif mutation == "partial":
        lock["outputs"]["pokegold"]["sym_sha256"] = "0" * 64
    else:
        lock = {"pret_syms": {"Crystal": {"wPartyCount": 1}}}
    with pytest.raises(ValueError):
        admission.build_matrices(lock)


def test_artifact_compatibility_is_separate_from_authorized_title_scope(lock):
    matrix = admission.build_matrices(lock)["gen2_crystal"]
    assert len(matrix["authorized_title_pairings"]) == 6
    assert matrix["artifact_kind_compatibility"]["clean"]["clean"] == "REQUIRES_G1"
    assert matrix["artifact_kind_compatibility"]["clean"]["overlay"] == "REFUSED"
    matrix["artifact_kind_compatibility"]["clean"]["overlay"] = "ALLOWED"
    with pytest.raises(ValueError):
        admission.validate_matrix(matrix, lock)


def test_check_and_failure_do_not_publish(tmp_path, lock):
    lock_path = tmp_path / "lock.json"
    lock_path.write_text(json.dumps(lock, indent=2) + "\n")
    args = ["--lock", str(lock_path), "--out-dir", str(tmp_path / "games")]
    assert admission.main([*args, "--check"]) == 1
    assert not (tmp_path / "games").exists()
    assert admission.main(args) == 0
    before = {p: p.read_bytes() for p in (tmp_path / "games").rglob("*.json")}
    assert admission.main([*args, "--check"]) == 0
    bad = copy.deepcopy(lock)
    bad["sources"]["pokegold"]["commit"] = "0" * 40
    lock_path.write_text(json.dumps(bad))
    assert admission.main(args) == 1
    assert before == {p: p.read_bytes() for p in before}


def _write_build(tmp_path, built):
    lock, receipt = built
    lock_path = tmp_path / "lock.json"
    lock_path.write_text(json.dumps(lock, indent=2) + "\n", newline="\n")
    receipt_path = tmp_path / "build_provenance.json"
    receipt_path.write_text(json.dumps(receipt))
    for name in lock["outputs"]:
        (tmp_path / f"{name}.sym").write_bytes(name.encode())
        (tmp_path / f"{name}.map").write_bytes((name + " map").encode())
    return ["--lock", str(lock_path), "--provenance", str(receipt_path),
            "--out-dir", str(tmp_path / "games")]


@pytest.mark.parametrize("formatting", ["lf", "crlf", "compact"])
def test_cli_accepts_receipt_for_exact_lock_serialization(tmp_path, built, formatting):
    args = _write_build(tmp_path, built)
    lock, receipt = built
    text = json.dumps(lock, separators=(",", ":")) if formatting == "compact" else json.dumps(lock, indent=2) + "\n"
    if formatting == "crlf":
        text = text.replace("\n", "\r\n")
    raw = text.encode("utf-8")
    (tmp_path / "lock.json").write_bytes(raw)
    receipt["lock_sha256"] = hashlib.sha256(raw).hexdigest()
    (tmp_path / "build_provenance.json").write_text(json.dumps(receipt))
    assert admission.main(args) == 0
    assert admission.main([*args, "--check"]) == 0
    for path in (tmp_path / "games").rglob("admission.json"):
        assert json.loads(path.read_text())["source_lock_sha256"] == receipt["lock_sha256"]


def test_cli_refuses_receipt_for_different_raw_lock_bytes(tmp_path, built):
    args = _write_build(tmp_path, built)
    lock, receipt = built
    raw = json.dumps(lock, separators=(",", ":")).encode("utf-8")
    assert hashlib.sha256(raw).hexdigest() != receipt["lock_sha256"]
    (tmp_path / "lock.json").write_bytes(raw)
    assert admission.main(args) == 1
    assert not (tmp_path / "games").exists()


def test_cli_parses_and_hashes_one_lock_snapshot(tmp_path, built, monkeypatch):
    args = _write_build(tmp_path, built)
    lock_path = tmp_path / "lock.json"
    original = Path.read_bytes
    reads = []

    def read_bytes(path):
        if path == lock_path:
            reads.append(path)
            assert len(reads) == 1, "lock must not be read again after parsing"
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    # Text-mode reads could silently normalize CRLF or parse a different file snapshot.
    original_text = Path.read_text

    def read_text(path, *args, **kwargs):
        assert path != lock_path, "lock must be parsed from its byte snapshot"
        return original_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read_text)
    assert admission.main(args) == 0
    assert len(reads) == 1


def test_byte_aware_api_refuses_snapshot_of_different_lock(built):
    lock, receipt = built
    other = copy.deepcopy(lock)
    other["outputs"]["pokegold"]["map_sha256"] = "0" * 64
    raw = json.dumps(other).encode("utf-8")
    receipt["lock_sha256"] = hashlib.sha256(raw).hexdigest()
    with pytest.raises(ValueError, match="snapshot differs"):
        admission.build_matrices(lock, receipt, lock_bytes=raw)


def test_cli_build_receipt_and_disk_bytes_are_both_required(tmp_path, built):
    args = _write_build(tmp_path, built)
    assert admission.main(args) == 0
    assert admission.main([*args, "--check"]) == 0
    before = {p: p.read_bytes() for p in (tmp_path / "games").rglob("*.json")}
    (tmp_path / "pokesilver.map").write_bytes(b"corrupt map")
    assert admission.main(args) == 1
    assert before == {p: p.read_bytes() for p in before}


def test_cli_refuses_to_downgrade_built_rows_without_provenance(tmp_path, built):
    args = _write_build(tmp_path, built)
    assert admission.main(args) == 0
    before = {p: p.read_bytes() for p in (tmp_path / "games").rglob("*.json")}
    assert admission.main(args[:2] + args[4:]) == 1
    assert before == {p: p.read_bytes() for p in before}


def test_cli_cannot_overwrite_future_g1_owner_state(tmp_path, built):
    args = _write_build(tmp_path, built)
    assert admission.main(args) == 0
    path = tmp_path / "games/gen2_silver/admission.json"
    matrix = json.loads(path.read_text())
    matrix["artifacts"][0]["status"] = "ADMITTED"
    path.write_text(json.dumps(matrix))
    before = {p: p.read_bytes() for p in (tmp_path / "games").rglob("*.json")}
    assert admission.main(args) == 1
    assert before == {p: p.read_bytes() for p in before}


def test_cli_refuses_duplicate_json_keys_without_publishing(tmp_path, lock):
    path = tmp_path / "lock.json"
    encoded = json.dumps(lock)
    path.write_text('{"schema_version": 999,' + encoded[1:])
    assert admission.main(["--lock", str(path), "--out-dir", str(tmp_path / "games")]) == 1
    assert not (tmp_path / "games").exists()


@pytest.mark.parametrize("mutation", ["rgbds_binary", "build_tool", "make_targets"])
def test_incomplete_build_identity_refused(built, mutation):
    lock, receipt = built
    if mutation == "rgbds_binary":
        del receipt["toolchain"]["rgbds"]["binaries"]["rgbgfx"]
    elif mutation == "build_tool":
        del receipt["toolchain"]["build_tools"]["binaries"]["sh"]
    else:
        receipt["sources"]["pokegold"]["make_targets"] = ["pokegold.gbc"]
    with pytest.raises(ValueError):
        admission.build_matrices(lock, receipt)


def test_existing_committed_matrices_are_valid():
    lock_bytes = (ROOT / "data/gen2_sources.lock.json").read_bytes()
    lock = json.loads(lock_bytes)
    for title in ("crystal", "gold", "silver"):
        matrix = json.loads((ROOT / f"data/games/gen2_{title}/admission.json").read_text())
        # Build evidence can be populated by the separate runner after this initial cut.
        receipt_path = ROOT / "data/gen2/build_provenance.json"
        receipt = json.loads(receipt_path.read_text()) if receipt_path.exists() else None
        # P4.1f: the overlay rows are BUILT from the SLink companion build receipt.
        overlay = json.loads((ROOT / "data/gen2/overlay_provenance.json").read_text())
        admission.validate_matrix(matrix, lock, receipt, lock_bytes=lock_bytes, overlay=overlay)


# --- P4.4 overlay promotion (--promote-overlays): ADMITTED only behind the G4 preconditions ---------

def _canonical_overlay_build(tmp_path, built, monkeypatch):
    """Build a disposable repository whose promotion paths are canonical for the tool."""
    repo = tmp_path / "repo"
    data = repo / "data/gen2"
    out_dir = repo / "data/games"
    dist = repo / "patch/dist"
    data.mkdir(parents=True)
    dist.mkdir(parents=True)
    monkeypatch.setattr(admission, "ROOT", repo)

    lock, receipt = built
    lock_path = repo / "data/gen2_sources.lock.json"
    lock_path.write_text(json.dumps(lock, indent=2) + "\n", newline="\n")
    receipt_path = data / "build_provenance.json"
    receipt_path.write_text(json.dumps(receipt), newline="\n")
    for name in lock["outputs"]:
        (data / f"{name}.sym").write_bytes(name.encode())
        (data / f"{name}.map").write_bytes((name + " map").encode())

    outputs = {}
    for title, rows in admission.TITLE_OUTPUTS.items():
        artifact = rows[0][0]
        raw_ups = f"UPS {title}".encode()
        ups_file = f"patch/dist/SLink-{title}.ups"
        (repo / ups_file).write_bytes(raw_ups)
        outputs[artifact] = {
            "slink_title": title,
            "base_sha1": lock["outputs"][artifact]["sha1"],
            "identical_to_clean": False,
            "sha1": hashlib.sha1(title.encode()).hexdigest(),
            "md5": hashlib.md5(title.encode()).hexdigest(),
            "ups": {"file": ups_file, "sha256": hashlib.sha256(raw_ups).hexdigest()},
        }
    overlay = {
        "schema": "gen2-overlay-provenance-v1",
        "sources": {name: {"commit": row["commit"]} for name, row in lock["sources"].items()},
        "outputs": outputs,
    }
    overlay_path = data / "overlay_provenance.json"
    overlay_path.write_text(json.dumps(overlay), newline="\n")
    args = ["--provenance", str(receipt_path), "--overlay-provenance", str(overlay_path)]
    paths = {"root": repo, "lock": lock_path, "provenance": receipt_path,
             "overlay": overlay_path, "out": out_dir}
    return args, paths


def _overlay_rows(out_dir):
    return {path.parent.name: next(row for row in json.loads(path.read_text())["artifacts"]
                                   if row["kind"] == "overlay")
            for path in out_dir.rglob("admission.json")}


def _overlay_statuses(out_dir):
    return {pack: row["status"] for pack, row in _overlay_rows(out_dir).items()}


def test_promotion_refuses_mutated_temp_overlay_provenance_without_writes(tmp_path, built, monkeypatch):
    args, paths = _canonical_overlay_build(tmp_path, built, monkeypatch)
    assert admission.main(args) == 0
    before = {path: path.read_bytes() for path in paths["out"].rglob("*.json")}

    mutated = json.loads(paths["overlay"].read_text())
    mutated["outputs"]["pokecrystal"]["sha1"] = "0" * 40
    mutated_path = tmp_path / "mutated-overlay-provenance.json"
    mutated_path.write_text(json.dumps(mutated), newline="\n")
    monkeypatch.setattr(admission, "promotion_blockers",
                        lambda: pytest.fail("non-canonical promotion input was not rejected first"))

    assert admission.main([*args[:-2], "--overlay-provenance", str(mutated_path),
                           "--promote-overlays"]) == 1
    assert before == {path: path.read_bytes() for path in before}
    assert set(_overlay_statuses(paths["out"]).values()) == {"BUILT"}


def test_promotion_is_refused_while_any_g4_precondition_is_open(tmp_path, built, monkeypatch):
    args, paths = _canonical_overlay_build(tmp_path, built, monkeypatch)
    assert admission.main(args) == 0
    before = {path: path.read_bytes() for path in paths["out"].rglob("*.json")}
    monkeypatch.setattr(admission, "promotion_blockers",
                        lambda: ["packet: docs/gen2/PLAN.md §6.1: the G4 ledger row carries no owner signature"])
    assert admission.main([*args, "--promote-overlays"]) == 1
    assert before == {path: path.read_bytes() for path in before}
    assert set(_overlay_statuses(paths["out"]).values()) == {"BUILT"}


def test_promotion_binds_one_grant_and_plain_regeneration_does_not_regrant(tmp_path, built, monkeypatch):
    args, paths = _canonical_overlay_build(tmp_path, built, monkeypatch)
    assert admission.main(args) == 0
    monkeypatch.setattr(admission, "promotion_blockers", lambda: [])
    assert admission.main([*args, "--promote-overlays"]) == 0
    rows = _overlay_rows(paths["out"])
    assert set(_overlay_statuses(paths["out"]).values()) == {"ADMITTED"}
    assert len({row["grant_fingerprint"] for row in rows.values()}) == 1

    # The promoted tree checks clean without the flag, and plain regeneration keeps this exact grant.
    monkeypatch.setattr(admission, "promotion_blockers", lambda: pytest.fail("no new grant is being made"))
    assert admission.main([*args, "--check"]) == 0
    assert admission.main(args) == 0
    assert rows == _overlay_rows(paths["out"])


@pytest.mark.parametrize("omitted", ["provenance", "overlay"])
def test_promotion_needs_both_canonical_build_receipts(tmp_path, built, monkeypatch, omitted):
    args, paths = _canonical_overlay_build(tmp_path, built, monkeypatch)
    assert admission.main(args) == 0
    monkeypatch.setattr(admission, "promotion_blockers", lambda: [])
    index = 0 if omitted == "provenance" else 2
    incomplete = args[:index] + args[index + 2:]
    assert admission.main([*incomplete, "--promote-overlays"]) == 1
    assert set(_overlay_statuses(paths["out"]).values()) == {"BUILT"}


def test_changed_overlay_identity_requires_a_new_g4_promotion(tmp_path, built, monkeypatch, capsys):
    args, paths = _canonical_overlay_build(tmp_path, built, monkeypatch)
    assert admission.main(args) == 0
    monkeypatch.setattr(admission, "promotion_blockers", lambda: [])
    assert admission.main([*args, "--promote-overlays"]) == 0
    before = {path: path.read_bytes() for path in paths["out"].rglob("*.json")}

    changed = json.loads(paths["overlay"].read_text())
    changed["outputs"]["pokecrystal"]["sha1"] = "0" * 40
    paths["overlay"].write_text(json.dumps(changed), newline="\n")
    monkeypatch.setattr(admission, "promotion_blockers", lambda: pytest.fail("stale grant was not rejected first"))

    assert admission.main(args) == 1
    assert "new G4 promotion is required" in capsys.readouterr().err
    assert before == {path: path.read_bytes() for path in before}
    assert set(_overlay_statuses(paths["out"]).values()) == {"ADMITTED"}


def test_a_partial_or_hand_edited_promotion_is_refused(tmp_path, built, monkeypatch):
    args, paths = _canonical_overlay_build(tmp_path, built, monkeypatch)
    assert admission.main(args) == 0
    path = paths["out"] / "gen2_gold/admission.json"
    matrix = json.loads(path.read_text())
    next(row for row in matrix["artifacts"] if row["kind"] == "overlay")["status"] = "ADMITTED"
    path.write_text(json.dumps(matrix, indent=2) + "\n", newline="\n")
    before = {candidate: candidate.read_bytes() for candidate in paths["out"].rglob("*.json")}
    monkeypatch.setattr(admission, "promotion_blockers", lambda: [])
    assert admission.main([*args, "--check"]) == 1
    assert admission.main([*args, "--promote-overlays"]) == 1
    assert before == {candidate: candidate.read_bytes() for candidate in before}


@pytest.mark.parametrize("failed_replace", [2, 3])
def test_interrupted_atomic_publish_is_completed_by_the_same_promotion(
        tmp_path, built, monkeypatch, failed_replace):
    args, paths = _canonical_overlay_build(tmp_path, built, monkeypatch)
    assert admission.main(args) == 0
    monkeypatch.setattr(admission, "promotion_blockers", lambda: [])
    real_replace = admission.os.replace
    replace_calls = 0

    def fail_one_publish(source, target):
        nonlocal replace_calls
        replace_calls += 1
        if replace_calls == failed_replace:
            raise OSError(f"injected replace failure {failed_replace}")
        return real_replace(source, target)

    monkeypatch.setattr(admission.os, "replace", fail_one_publish)
    assert admission.main([*args, "--promote-overlays"]) == 1
    assert sum(row["status"] == "ADMITTED" for row in _overlay_rows(paths["out"]).values()) == failed_replace - 1
    assert not (paths["out"].parent / ".games.gen2_admission.publish.lock").exists()
    assert not list(paths["out"].rglob("*.tmp"))

    monkeypatch.setattr(admission.os, "replace", real_replace)
    assert admission.main([*args, "--promote-overlays"]) == 0
    rows = _overlay_rows(paths["out"])
    assert set(_overlay_statuses(paths["out"]).values()) == {"ADMITTED"}
    assert len({row["grant_fingerprint"] for row in rows.values()}) == 1


def test_committed_tree_cannot_promote_until_the_owner_signs_g4():
    plan = (ROOT / "docs/gen2/PLAN.md").read_text(encoding="utf-8")
    if "| G4 | — |" in plan:
        blockers = admission.promotion_blockers()
        assert "packet: docs/gen2/PLAN.md §6.1: the G4 ledger row carries no owner signature" in blockers
        assert not any("not ADMITTED at the published overlay" in b for b in blockers)
