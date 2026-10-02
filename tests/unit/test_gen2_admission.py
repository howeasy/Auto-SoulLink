"""P1 matrix falsifiers: source evidence never grants runtime admission."""
from __future__ import annotations

import contextlib
import copy
import hashlib
import json
import shutil
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
    for title in admission.TITLE_OUTPUTS:   # D2: the generated binding sidecar of each overlay (tools/gen2_artifacts.py)
        out = outputs[admission.TITLE_OUTPUTS[title][0][0]]
        sidecar = out_dir / f"gen2_{title}" / "overlay" / "binding.json"
        sidecar.parent.mkdir(parents=True)
        sidecar.write_text(json.dumps({"schema": "gen2-overlay-binding-v1", "title": title, "kind": "overlay",
                                       "rom_sha1": out["sha1"], "base_sha1": out["base_sha1"],
                                       "ups_sha256": out["ups"]["sha256"]}, sort_keys=True), newline="\n")
    args = ["--provenance", str(receipt_path), "--overlay-provenance", str(overlay_path)]
    paths = {"root": repo, "lock": lock_path, "provenance": receipt_path,
             "overlay": overlay_path, "out": out_dir}
    return args, paths


def _open_activation(monkeypatch):
    """The two production-side checks (the G4 packet, the overlay receipts under the Lua validators) are exercised by
    their own tests; here they are open so the catalog mechanics can be tested on a disposable tree."""
    monkeypatch.setattr(admission, "g4_packet_errors", lambda: [])
    monkeypatch.setattr(admission, "overlay_proof_errors", lambda matrices: [])


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
    monkeypatch.setattr(admission, "activation_blockers",
                        lambda *a: pytest.fail("non-canonical promotion input was not rejected first"))

    assert admission.main([*args[:-2], "--overlay-provenance", str(mutated_path),
                           "--promote-overlays"]) == 1
    assert before == {path: path.read_bytes() for path in before}
    assert set(_overlay_statuses(paths["out"]).values()) == {"BUILT"}


def test_promotion_is_refused_while_any_g4_precondition_is_open(tmp_path, built, monkeypatch):
    args, paths = _canonical_overlay_build(tmp_path, built, monkeypatch)
    assert admission.main(args) == 0
    before = {path: path.read_bytes() for path in paths["out"].rglob("*.json")}
    monkeypatch.setattr(admission, "g4_packet_errors",
                        lambda: ["docs/gen2/PLAN.md §6.1: the G4 ledger row carries no owner signature"])
    assert admission.main([*args, "--promote-overlays"]) == 1
    assert before == {path: path.read_bytes() for path in before}
    assert set(_overlay_statuses(paths["out"]).values()) == {"BUILT"}


def test_promotion_binds_one_grant_and_plain_regeneration_does_not_regrant(tmp_path, built, monkeypatch):
    args, paths = _canonical_overlay_build(tmp_path, built, monkeypatch)
    assert admission.main(args) == 0
    _open_activation(monkeypatch)
    assert admission.main([*args, "--promote-overlays"]) == 0
    rows = _overlay_rows(paths["out"])
    assert set(_overlay_statuses(paths["out"]).values()) == {"ADMITTED"}
    assert len({row["runtime_gate"]["grant_fingerprint"] for row in rows.values()}) == 1

    # The promoted tree checks clean without the flag, and plain regeneration keeps this exact grant. Both re-run the
    # activation preconditions (an ADMITTED catalog is never blessed on self-consistency alone), neither re-grants.
    real_blockers, asked = admission.activation_blockers, []
    monkeypatch.setattr(admission, "activation_blockers", lambda *a: asked.append(a) or real_blockers(*a))
    assert admission.main([*args, "--check"]) == 0
    assert admission.main(args) == 0
    assert len(asked) == 2
    assert rows == _overlay_rows(paths["out"])


@pytest.mark.parametrize("omitted", ["provenance", "overlay"])
def test_promotion_needs_both_canonical_build_receipts(tmp_path, built, monkeypatch, omitted):
    args, paths = _canonical_overlay_build(tmp_path, built, monkeypatch)
    assert admission.main(args) == 0
    _open_activation(monkeypatch)
    index = 0 if omitted == "provenance" else 2
    incomplete = args[:index] + args[index + 2:]
    assert admission.main([*incomplete, "--promote-overlays"]) == 1
    assert set(_overlay_statuses(paths["out"]).values()) == {"BUILT"}


def test_changed_overlay_identity_requires_a_new_g4_promotion(tmp_path, built, monkeypatch, capsys):
    args, paths = _canonical_overlay_build(tmp_path, built, monkeypatch)
    assert admission.main(args) == 0
    _open_activation(monkeypatch)
    assert admission.main([*args, "--promote-overlays"]) == 0
    before = {path: path.read_bytes() for path in paths["out"].rglob("*.json")}

    changed = json.loads(paths["overlay"].read_text())
    changed["outputs"]["pokecrystal"]["sha1"] = "0" * 40
    paths["overlay"].write_text(json.dumps(changed), newline="\n")
    monkeypatch.setattr(admission, "activation_blockers", lambda *a: pytest.fail("stale grant was not rejected first"))

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
    _open_activation(monkeypatch)
    assert admission.main([*args, "--check"]) == 1
    assert admission.main([*args, "--promote-overlays"]) == 1
    assert before == {candidate: candidate.read_bytes() for candidate in before}


@pytest.mark.parametrize("failed_replace", [2, 3])
def test_interrupted_atomic_publish_is_completed_by_the_same_promotion(
        tmp_path, built, monkeypatch, failed_replace):
    args, paths = _canonical_overlay_build(tmp_path, built, monkeypatch)
    assert admission.main(args) == 0
    _open_activation(monkeypatch)
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
    assert len({row["runtime_gate"]["grant_fingerprint"] for row in rows.values()}) == 1


def _blank_g4(plan):
    """PLAN with the G4 ledger row's Signed cell blanked (the unsigned state the old test looked for)."""
    lines = []
    for line in plan.splitlines(keepends=True):
        if line.replace(" ", "").startswith("|G4|"):
            cells = line.strip().strip("|").split("|")
            cells[1] = " — "
            line = "|" + "|".join(cells) + "|\n"
        lines.append(line)
    blank = "".join(lines)
    assert blank != plan, "the G4 row was not found to blank"
    return blank


def _packet_root(path, plan):
    """The files tools/verify_gen2_release.py g4_packet_errors reads, copied from the committed tree, with this PLAN."""
    overlay = json.loads((ROOT / "data/gen2/overlay_provenance.json").read_text())
    files = ["data/gen2_sources.lock.json", "data/gen2/build_provenance.json", "data/gen2/overlay_provenance.json",
             *(out["ups"]["file"] for out in overlay["outputs"].values())]
    for title in ("crystal", "gold", "silver"):
        files += [f"data/gen2/{title}_slink.sym", f"data/gen2/{title}_slink.map",
                  f"data/games/gen2_{title}/admission.json", f"data/games/gen2_{title}/overlay/binding.json"]
    for relative in files:
        (path / relative).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, path / relative)
    (path / "docs/gen2").mkdir(parents=True, exist_ok=True)
    (path / "docs/gen2/PLAN.md").write_text(plan, encoding="utf-8", newline="\n")
    return path


def test_committed_tree_cannot_promote_until_the_owner_signs_g4(tmp_path, monkeypatch, capsys):
    import verify_gen2_release as release
    plan = (ROOT / "docs/gen2/PLAN.md").read_text(encoding="utf-8")
    monkeypatch.setattr(release, "ROOT", _packet_root(tmp_path / "signed", plan))
    assert not any("owner signature" in e for e in admission.g4_packet_errors())      # the control: G4 is signed now

    # G4 blanked in a COPY of PLAN.md: the production wrapper (require_admitted=False) names the signature, and nothing
    # about the not-yet-written ADMITTED rows
    monkeypatch.setattr(release, "ROOT", _packet_root(tmp_path / "blank", _blank_g4(plan)))
    errors = admission.g4_packet_errors()
    assert "docs/gen2/PLAN.md §6.1: the G4 ledger row carries no owner signature" in errors
    assert not any("not ADMITTED at the published overlay" in e for e in errors)

    # ... and --promote-overlays on the committed tree refuses with that blocker, writing nothing. Everything but the
    # PLAN is the committed tree, so a promotion that ignored the blocker could only refuse later for another reason:
    # the refusal text is what proves the G4 gate fired.
    games = ROOT / "data/games"
    before = {p: p.read_bytes() for p in games.rglob("*.json")}
    monkeypatch.setattr(admission, "_publish", lambda pending: pytest.fail("a blanked G4 was published"))
    monkeypatch.setattr(admission, "_exclusive_publication_lock", lambda out_dir: contextlib.nullcontext())
    overlay = json.loads((ROOT / "data/gen2/overlay_provenance.json").read_text())
    assert "packet: docs/gen2/PLAN.md §6.1: the G4 ledger row carries no owner signature" in \
        admission.activation_blockers(games, overlay)
    assert admission.main(["--lock", str(ROOT / "data/gen2_sources.lock.json"),
                           "--provenance", str(ROOT / "data/gen2/build_provenance.json"),
                           "--overlay-provenance", str(ROOT / "data/gen2/overlay_provenance.json"),
                           "--out-dir", str(games), "--promote-overlays"]) == 1
    err = capsys.readouterr().err
    assert "G4 activation refused" in err and "blocker(s)" in err
    assert before == {p: p.read_bytes() for p in before}


# --- schema v2 (OVERLAY_ADMISSION D1/D6): activation is its own gate, not the full release-evidence -------------------

def test_every_committed_matrix_is_schema_v2_and_the_unactivated_overlay_is_future_built():
    for title in ("crystal", "gold", "silver"):
        matrix = json.loads((ROOT / f"data/games/gen2_{title}/admission.json").read_text())
        assert matrix["schema_version"] == 2
        row = next(r for r in matrix["artifacts"] if r["kind"] == "overlay")
        if row["status"] == "BUILT":      # not activated yet: an identity, never runtime eligible
            assert (row["selection"], "runtime_gate" not in row, "binding_sha256" not in row) == ("FUTURE", True, True)


def test_an_activated_row_is_selected_admitted_behind_its_own_g4_grant_and_binding_pin(tmp_path, built, monkeypatch):
    args, paths = _canonical_overlay_build(tmp_path, built, monkeypatch)
    assert admission.main(args) == 0
    clean_before = {p.parent.name: json.loads(p.read_text())["artifacts"][0] for p in paths["out"].rglob("admission.json")}
    _open_activation(monkeypatch)
    assert admission.main([*args, "--promote-overlays"]) == 0
    rows = _overlay_rows(paths["out"])
    for pack, row in rows.items():
        sidecar = paths["out"] / pack / "overlay" / "binding.json"
        assert (row["selection"], row["status"]) == ("SELECTED", "ADMITTED")
        assert row["runtime_gate"] == {"id": "G4", "state": "ADMITTED",
                                       "grant_fingerprint": row["runtime_gate"]["grant_fingerprint"]}
        assert row["binding_sha256"] == hashlib.sha256(sidecar.read_bytes()).hexdigest()
        assert "grant_fingerprint" not in row
    for path in paths["out"].rglob("admission.json"):       # the clean grant is untouched and never grants the overlay
        matrix = json.loads(path.read_text())
        assert matrix["gate"]["id"] == "G1" and matrix["artifacts"][0] == clean_before[path.parent.name]


def test_activation_needs_the_binding_sidecars_not_the_full_release_evidence(tmp_path, built, monkeypatch):
    import verify_gen2_release as release
    args, paths = _canonical_overlay_build(tmp_path, built, monkeypatch)
    assert admission.main(args) == 0
    overlay = json.loads(paths["overlay"].read_text())
    monkeypatch.setattr(admission, "g4_packet_errors", lambda: [])
    monkeypatch.setattr(release, "release_evidence_errors",
                        lambda *a, **k: pytest.fail("activation must not require the full release-evidence"))
    assert admission.activation_blockers(paths["out"], overlay) == []
    (paths["out"] / "gen2_gold" / "overlay" / "binding.json").unlink()
    assert any("gold" in b and "binding sidecar missing" in b for b in admission.activation_blockers(paths["out"], overlay))


@pytest.mark.parametrize("field,value", [("rom_sha1", "0" * 40), ("base_sha1", "0" * 40), ("ups_sha256", "0" * 64),
                                         ("kind", "clean"), ("title", "gold")])
def test_a_binding_sidecar_that_is_not_the_published_overlay_blocks_activation(tmp_path, built, monkeypatch, field, value):
    args, paths = _canonical_overlay_build(tmp_path, built, monkeypatch)
    assert admission.main(args) == 0
    monkeypatch.setattr(admission, "g4_packet_errors", lambda: [])
    sidecar = paths["out"] / "gen2_crystal" / "overlay" / "binding.json"
    binding = json.loads(sidecar.read_text())
    binding[field] = value
    sidecar.write_text(json.dumps(binding), newline="\n")
    blockers = admission.activation_blockers(paths["out"], json.loads(paths["overlay"].read_text()))
    assert any("crystal" in b and field in b for b in blockers), blockers
    before = {p: p.read_bytes() for p in paths["out"].rglob("admission.json")}
    assert admission.main([*args, "--promote-overlays"]) == 1
    assert before == {p: p.read_bytes() for p in before}


def test_a_missing_binding_sidecar_refuses_activation_without_writes(tmp_path, built, monkeypatch):
    args, paths = _canonical_overlay_build(tmp_path, built, monkeypatch)
    assert admission.main(args) == 0
    _open_activation(monkeypatch)
    (paths["out"] / "gen2_silver" / "overlay" / "binding.json").unlink()
    before = {p: p.read_bytes() for p in paths["out"].rglob("admission.json")}
    assert admission.main([*args, "--promote-overlays"]) == 1
    assert before == {p: p.read_bytes() for p in before}


def test_overlay_receipts_that_fail_the_production_validators_refuse_activation_without_writes(
        tmp_path, built, monkeypatch, capsys):
    args, paths = _canonical_overlay_build(tmp_path, built, monkeypatch)
    assert admission.main(args) == 0
    _open_activation(monkeypatch)
    monkeypatch.setattr(admission, "overlay_proof_errors", lambda matrices: ["gold: overlay proofs refused: U1 stale"])
    before = {p: p.read_bytes() for p in paths["out"].rglob("admission.json")}
    assert admission.main([*args, "--promote-overlays"]) == 1
    assert "overlay proofs" in capsys.readouterr().err
    assert before == {p: p.read_bytes() for p in before}


def test_a_changed_binding_sidecar_needs_a_new_promotion_not_a_regeneration(tmp_path, built, monkeypatch, capsys):
    args, paths = _canonical_overlay_build(tmp_path, built, monkeypatch)
    assert admission.main(args) == 0
    _open_activation(monkeypatch)
    assert admission.main([*args, "--promote-overlays"]) == 0
    before = {p: p.read_bytes() for p in paths["out"].rglob("admission.json")}
    sidecar = paths["out"] / "gen2_crystal" / "overlay" / "binding.json"
    sidecar.write_text(sidecar.read_text() + " ", newline="\n")
    assert admission.main(args) == 1
    assert "binding pin" in capsys.readouterr().err
    assert admission.main([*args, "--check"]) == 1
    assert before == {p: p.read_bytes() for p in before}


def test_the_real_overlay_proof_check_runs_the_lua_entry_and_refuses_an_unbound_row():
    # lua/gen2/entry.lua Entry.activation_proof on the committed (not activated) tree: the prospective row has no
    # binding sidecar yet, so the production validators must refuse it instead of passing it
    matrices = {}
    for title in ("crystal", "gold", "silver"):
        matrix = json.loads((ROOT / f"data/games/gen2_{title}/admission.json").read_text())
        row = next(r for r in matrix["artifacts"] if r["kind"] == "overlay")
        row.update(selection="SELECTED", status="ADMITTED", binding_sha256="0" * 64,
                   runtime_gate={"id": "G4", "state": "ADMITTED", "grant_fingerprint": "1" * 64})
        matrices[title] = matrix
    errors = admission.overlay_proof_errors(matrices)
    assert len(errors) == 3 and all("overlay proofs refused" in e for e in errors)


# --- an ADMITTED catalog is re-proven by --check and by regeneration (review M1; OVERLAY_ADMISSION D6) -------------------

def _promoted_tree(tmp_path, built, monkeypatch):
    """A disposable tree promoted for real (the production checks open); returns the two production checks."""
    args, paths = _canonical_overlay_build(tmp_path, built, monkeypatch)
    assert admission.main(args) == 0
    real = (admission.g4_packet_errors, admission.overlay_proof_errors)
    _open_activation(monkeypatch)
    assert admission.main([*args, "--promote-overlays"]) == 0
    assert set(_overlay_statuses(paths["out"]).values()) == {"ADMITTED"}
    return args, paths, real


def test_check_of_an_admitted_catalog_reruns_the_overlay_proofs_and_refuses_unproven_rows(
        tmp_path, built, monkeypatch, capsys):
    args, paths, _real = _promoted_tree(tmp_path, built, monkeypatch)
    asked = []
    monkeypatch.setattr(admission, "overlay_proof_errors", lambda matrices: asked.append(sorted(matrices)) or [])
    assert admission.main([*args, "--check"]) == 0
    assert asked == [["gen2_crystal", "gen2_gold", "gen2_silver"]]
    capsys.readouterr()
    monkeypatch.setattr(admission, "overlay_proof_errors",
                        lambda matrices: ["gold: overlay proofs refused: no receipts"])
    before = {p: p.read_bytes() for p in paths["out"].rglob("admission.json")}
    for argv in ([*args, "--check"], args):         # regeneration is held to the same preconditions
        assert admission.main(argv) == 1
        assert "overlay proofs" in capsys.readouterr().err
    assert before == {p: p.read_bytes() for p in before}


def test_check_of_an_admitted_catalog_with_a_valid_grant_and_binding_but_no_receipts_fails(
        tmp_path, built, monkeypatch, capsys):
    # the production Lua validators (Entry.activation_proof), run on a hand-built ADMITTED catalog that has a valid grant
    # and binding pin but no overlay receipts anywhere
    args, paths, (_packet, proofs) = _promoted_tree(tmp_path, built, monkeypatch)
    repo = paths["root"]

    def production_proofs(matrices):
        monkeypatch.setattr(admission, "ROOT", ROOT)       # the committed pack and validators; no overlay receipts
        try:
            return proofs(matrices)
        finally:
            monkeypatch.setattr(admission, "ROOT", repo)
    monkeypatch.setattr(admission, "overlay_proof_errors", production_proofs)
    capsys.readouterr()
    assert admission.main([*args, "--check"]) == 1
    assert "overlay proofs refused" in capsys.readouterr().err


def test_check_of_an_admitted_catalog_refuses_a_blanked_g4(tmp_path, built, monkeypatch, capsys):
    import verify_gen2_release as release
    args, paths, _real = _promoted_tree(tmp_path, built, monkeypatch)
    assert admission.main([*args, "--check"]) == 0
    blank = _blank_g4((ROOT / "docs/gen2/PLAN.md").read_text(encoding="utf-8"))
    monkeypatch.setattr(admission, "g4_packet_errors", lambda: [
        f"docs/gen2/PLAN.md §6.1: {e}" for e in release.g4_signature_errors(blank)])
    capsys.readouterr()
    before = {p: p.read_bytes() for p in paths["out"].rglob("admission.json")}
    for argv in ([*args, "--check"], args):
        assert admission.main(argv) == 1
        err = capsys.readouterr().err
        assert "G4 activation refused" in err and "carries no owner signature" in err
    assert before == {p: p.read_bytes() for p in before}


def test_a_complete_looking_but_partial_promotion_is_refused_even_with_a_valid_grant(
        tmp_path, built, monkeypatch, capsys):
    args, paths = _canonical_overlay_build(tmp_path, built, monkeypatch)
    assert admission.main(args) == 0
    built_catalogs = {p: p.read_bytes() for p in paths["out"].rglob("admission.json")}
    _open_activation(monkeypatch)
    assert admission.main([*args, "--promote-overlays"]) == 0
    gold = paths["out"] / "gen2_gold" / "admission.json"
    gold.write_bytes(built_catalogs[gold])       # Crystal and Silver keep their genuine grant; Gold is back to BUILT
    assert sorted(pack for pack, status in _overlay_statuses(paths["out"]).items() if status == "ADMITTED") == [
        "gen2_crystal", "gen2_silver"]
    partial = {p: p.read_bytes() for p in paths["out"].rglob("admission.json")}
    capsys.readouterr()
    for argv in ([*args, "--check"], args):
        assert admission.main(argv) == 1
        assert "partial G4 promotion" in capsys.readouterr().err
    assert partial == {p: p.read_bytes() for p in partial}


@pytest.mark.parametrize("ext", ["sym", "map"])
def test_a_binding_sidecar_must_carry_the_published_symbol_hashes(tmp_path, built, monkeypatch, ext):
    args, paths = _canonical_overlay_build(tmp_path, built, monkeypatch)
    assert admission.main(args) == 0
    monkeypatch.setattr(admission, "g4_packet_errors", lambda: [])
    overlay = json.loads(paths["overlay"].read_text())
    overlay["symbols"] = {f"{title}_slink.{e}": hashlib.sha256(f"{title}.{e}".encode()).hexdigest()
                          for title in admission.TITLE_OUTPUTS for e in ("sym", "map")}
    for title in admission.TITLE_OUTPUTS:
        sidecar = paths["out"] / f"gen2_{title}" / "overlay" / "binding.json"
        binding = json.loads(sidecar.read_text())
        binding.update({f"{e}_sha256": overlay["symbols"][f"{title}_slink.{e}"] for e in ("sym", "map")})
        sidecar.write_text(json.dumps(binding, sort_keys=True), newline="\n")
    assert admission.activation_blockers(paths["out"], overlay) == []
    sidecar = paths["out"] / "gen2_crystal" / "overlay" / "binding.json"
    binding = json.loads(sidecar.read_text())
    for tampered in ("0" * 64, None):         # a different hash, and the pin left out altogether
        changed = dict(binding)
        if tampered is None:
            changed.pop(f"{ext}_sha256")
        else:
            changed[f"{ext}_sha256"] = tampered
        sidecar.write_text(json.dumps(changed, sort_keys=True), newline="\n")
        assert admission.activation_blockers(paths["out"], overlay) == [
            f"crystal: overlay binding {ext}_sha256 differs from the published overlay build"]
