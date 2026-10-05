"""The INSTALLED C-5 packet: tools/verify_gen2_release.py c5_gate_errors + tools/c5_install_receipts.py.

MODEL trees in tmp_path; no lane, no EmuHawk, no real receipt. The point of this file is the refusal
path: C-5 only counts as a gate if an UNINSTALLED packet is RED, so that is the first test and it
asserts the named error, not merely that some error appeared.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "tests" / "unit"))

import c5_install_receipts as installer  # noqa: E402
import verify_gen2_release as gate  # noqa: E402
from test_verify_gen2_c5 import HEAD, JAR, _cell, _write  # noqa: E402

DEST = gate.C5_RECEIPTS


def _tree(tmp_path: Path) -> tuple[Path, Path]:
    """A model root with the requirements and jar pins, and a populated source packet in a lane."""
    root = tmp_path / "model"
    (root / "tests").mkdir(parents=True)
    shutil.copyfile(REPO / gate.C5_REQUIREMENTS, root / gate.C5_REQUIREMENTS)
    (root / "data").mkdir()
    (root / "data/upr_jars.json").write_text(json.dumps({"MODEL jar": JAR}), encoding="utf-8")
    return root, _packet(tmp_path / "lane", HEAD)


def _packet(lane: Path, digest: str) -> Path:
    """Populate a model lane and return its ROOT (installer.install takes the lane, not the packet)."""
    out = lane / "out" / digest[:12]
    folder = out / "receipts" / "c5"
    folder.mkdir(parents=True)
    for cid in gate.C5_CELLS:
        _cell(folder, cid)
    (out / "summary.json").write_text(json.dumps({"sha": "MODEL", "code_digest": digest}), encoding="utf-8")
    return lane


def _install(root: Path, lane: Path, digest: str = HEAD) -> Path:
    dest = root / DEST
    installer.install(lane, dest, digest)
    return dest


# ── the gate: an absent packet is RED, never a skip ───────────────────────────

def test_absent_packet_is_a_named_red_never_a_skip(tmp_path):
    root, _lane = _tree(tmp_path)
    errors = gate.c5_gate_errors(root=root, head=HEAD)
    assert errors == [gate.C5_NOT_INSTALLED]
    assert "NOT installed" in errors[0] and "c5_runner.py run" in errors[0]


def test_release_evidence_reports_c5_with_its_own_prefix(tmp_path, monkeypatch):
    """The gate is reached from the release-evidence LANE (tools/verify_gen2_release.py:203), so a
    missing packet must surface there prefixed `c5:`, not be absent from the lane."""
    root, _lane = _tree(tmp_path)
    monkeypatch.setattr(gate, "ROOT", root)
    stub = lambda *a, **k: []            # noqa: E731  every other part is exercised elsewhere
    for name in ("g4_packet_errors", "stale_errors", "fixtures_errors", "inspect_run_errors",
                 "new_gates_errors", "live_gates_errors", "trade_gates_errors", "duo_pairs_errors"):
        monkeypatch.setattr(gate, name, stub)
    lines = gate.release_evidence_errors(root=root, head=HEAD)
    assert lines == [f"c5: {gate.C5_NOT_INSTALLED}"]


def test_a_dir_with_receipts_but_no_install_manifest_is_still_red(tmp_path):
    """Copying the packet without the manifest must not buy a pass: the manifest is what pins it."""
    root, lane = _tree(tmp_path)
    dest = root / DEST
    dest.mkdir(parents=True)
    for source in installer.source_dir(lane, HEAD).iterdir():
        shutil.copy2(source, dest / source.name)
    errors = gate.c5_gate_errors(root=root, head=HEAD)
    assert any("install.json" in e for e in errors)


# ── the gate: green on a complete, current, untampered packet ─────────────────

def test_installed_current_valid_packet_is_green(tmp_path):
    root, lane = _tree(tmp_path)
    dest = _install(root, lane)
    manifest = json.loads((dest / gate.C5_INSTALL_MANIFEST).read_text(encoding="utf-8"))
    assert manifest["schema"] == gate.C5_INSTALL_SCHEMA
    assert manifest["code_digest"] == HEAD
    assert sorted(manifest["cells"]) == sorted(gate.C5_CELLS)
    assert gate.c5_gate_errors(root=root, head=HEAD) == []


# ── red controls: the three ways a packet must be refused ─────────────────────

def test_red_tampered_receipt_fails_its_install_pin(tmp_path):
    root, lane = _tree(tmp_path)
    dest = _install(root, lane)
    victim = sorted(p for p in dest.iterdir() if p.name.endswith("_result.txt"))[0]
    victim.write_text(victim.read_text(encoding="utf-8") + "PYDEC: PASS forged\n", encoding="utf-8")
    errors = gate.c5_gate_errors(root=root, head=HEAD)
    assert any(f"installed receipt tampered: {victim.name}" in e for e in errors), errors


def test_red_tampered_manifest_fails_its_install_pin(tmp_path):
    root, lane = _tree(tmp_path)
    dest = _install(root, lane)
    victim = sorted(p for p in dest.iterdir() if p.name.endswith(".manifest.json"))[0]
    doc = json.loads(victim.read_text(encoding="utf-8"))
    doc["evidence_level"] = "SYNTH"
    victim.write_text(json.dumps(doc), encoding="utf-8")
    errors = gate.c5_gate_errors(root=root, head=HEAD)
    assert any("installed receipt tampered" in e for e in errors), errors


def test_red_a_deleted_installed_receipt_is_named(tmp_path):
    root, lane = _tree(tmp_path)
    dest = _install(root, lane)
    victim = sorted(p for p in dest.iterdir() if p.name.endswith("_result.txt"))[0]
    victim.unlink()
    errors = gate.c5_gate_errors(root=root, head=HEAD)
    assert any(f"installed receipt missing: {victim.name}" in e for e in errors), errors


def test_red_a_stale_digest_is_refused_by_the_gate_and_by_the_installer(tmp_path):
    root, lane = _tree(tmp_path)
    dest = _install(root, lane)
    # the packet is byte-valid but was earned on other production code: move the digest under it
    install = json.loads((dest / gate.C5_INSTALL_MANIFEST).read_text(encoding="utf-8"))
    install["code_digest"] = "e" * 64
    _write(dest / gate.C5_INSTALL_MANIFEST, json.dumps(install, indent=2) + "\n")
    errors = gate.c5_gate_errors(root=root, head=HEAD)
    assert any("STALE" in e and "current production digest" in e for e in errors), errors
    # and the installer refuses to produce that packet from scratch, because no run exists at that digest
    with pytest.raises(installer.InstallError, match="no C-5 packet at this code digest"):
        installer.install(lane, root / DEST, "e" * 64)


def test_red_the_installer_refuses_a_packet_whose_summary_predates_the_code_change(tmp_path):
    root, lane = _tree(tmp_path)
    summary = lane / "out" / HEAD[:12] / "summary.json"
    summary.write_text(json.dumps({"code_digest": "e" * 64}), encoding="utf-8")
    with pytest.raises(installer.InstallError, match="STALE"):
        installer.install(lane, root / DEST, HEAD)


def test_red_the_installer_refuses_a_missing_packet(tmp_path):
    root, _tree_parts = _tree(tmp_path)
    with pytest.raises(installer.InstallError, match="no C-5 packet"):
        installer.install(tmp_path / "empty-lane", root / DEST, HEAD)


def test_red_the_installer_refuses_a_packet_with_no_manifests(tmp_path):
    root, _tree_parts = _tree(tmp_path)
    folder = tmp_path / "bare" / "out" / HEAD[:12] / "receipts" / "c5"
    folder.mkdir(parents=True)
    with pytest.raises(installer.InstallError, match="no \\*.manifest.json"):
        installer.install(tmp_path / "bare", root / DEST, HEAD)


def test_red_the_installer_refuses_a_cell_this_release_does_not_require(tmp_path):
    """An install must not smuggle in a cell the release does not pin -- it would be judged by
    c5_errors as 'not a required C-5 cell', but it should never have been installed at all."""
    root, lane = _tree(tmp_path)
    folder = lane / "out" / HEAD[:12] / "receipts" / "c5"
    smuggled = json.loads((folder / "c5__cc__link.manifest.json").read_text(encoding="utf-8"))
    smuggled["cell"] = "c5/xx/gen2_smuggled"
    _write(folder / "c5__xx__gen2_smuggled.manifest.json", json.dumps(smuggled, indent=1) + "\n")
    assert folder.is_dir()
    with pytest.raises(installer.InstallError, match="does not require"):
        installer.install(lane, root / DEST, HEAD)


def test_red_a_stale_manifest_in_a_packet_with_a_current_summary_is_refused(tmp_path):
    """The summary digest is optional and only one witness; each manifest's own code_digest is the
    evidence. A current summary must not launder a manifest earned on other production code."""
    root, lane = _tree(tmp_path)
    victim = installer.source_dir(lane, HEAD) / "c5__cc__link.manifest.json"
    doc = json.loads(victim.read_text(encoding="utf-8"))
    doc["code_digest"] = "e" * 64
    _write(victim, json.dumps(doc, indent=1) + "\n")
    with pytest.raises(installer.InstallError, match=r"STALE: c5__cc__link\.manifest\.json"):
        installer.install(lane, root / DEST, HEAD)
    assert not (root / DEST).exists()
    # and with no summary at all, the manifest alone still decides
    (lane / "out" / HEAD[:12] / "summary.json").unlink()
    with pytest.raises(installer.InstallError, match="STALE"):
        installer.install(lane, root / DEST, HEAD)


@pytest.mark.parametrize("pinned", [False, True], ids=["loose-file", "pinned-by-a-manifest"])
def test_red_a_packet_containing_the_reserved_install_manifest_name_is_refused(tmp_path, pinned):
    """install.json is the generated install manifest; a receipt of that name would be hashed and then
    silently overwritten, so the packet is refused instead."""
    root, lane = _tree(tmp_path)
    folder = installer.source_dir(lane, HEAD)
    _write(folder / gate.C5_INSTALL_MANIFEST, "{}\n")
    if pinned:
        victim = folder / "c5__cc__link.manifest.json"
        doc = json.loads(victim.read_text(encoding="utf-8"))
        doc["receipts"][f"receipts/c5/{gate.C5_INSTALL_MANIFEST}"] = "0" * 64
        _write(victim, json.dumps(doc, indent=1) + "\n")
    with pytest.raises(installer.InstallError, match="reserved"):
        installer.install(lane, root / DEST, HEAD)
    assert not (root / DEST).exists()


def test_a_source_changed_between_plan_and_copy_never_yields_a_mismatched_pin(tmp_path, monkeypatch):
    """plan() hashes the sources; install() copies them later. The pins must describe the bytes that
    were actually installed, whatever happened to the source in between."""
    root, lane = _tree(tmp_path)
    real_copy = installer.shutil.copy2
    mutated = []

    def racing_copy(src, dst, *a, **k):
        src = Path(src)
        if not mutated and src.name.endswith("_result.txt"):
            src.write_text(src.read_text(encoding="utf-8") + "RACED\n", encoding="utf-8")
            mutated.append(src.name)
        return real_copy(src, dst, *a, **k)

    monkeypatch.setattr(installer.shutil, "copy2", racing_copy)
    dest = root / DEST
    installer.install(lane, dest, HEAD)
    assert mutated, "the race was never injected"
    pins = json.loads((dest / gate.C5_INSTALL_MANIFEST).read_text(encoding="utf-8"))["files"]
    assert pins[mutated[0]] == installer.c5_runner.lf_sha256(dest / mutated[0])
    assert all(installer.c5_runner.lf_sha256(dest / n) == sha for n, sha in pins.items())
    assert "RACED" in (dest / mutated[0]).read_text(encoding="utf-8")


# ── the installer's own contract ──────────────────────────────────────────────

def test_dry_run_writes_nothing(tmp_path):
    root, lane = _tree(tmp_path)
    dest = root / DEST
    manifest = installer.install(lane, dest, HEAD, dry_run=True)
    assert not dest.exists(), "--dry-run must not create the destination"
    assert manifest["cells"] and manifest["files"]


def test_dry_run_and_the_real_install_agree_on_every_pin(tmp_path):
    root, lane = _tree(tmp_path)
    plan = installer.install(lane, root / DEST, HEAD, dry_run=True)
    dest = _install(root, lane)
    installed = json.loads((dest / gate.C5_INSTALL_MANIFEST).read_text(encoding="utf-8"))
    assert plan["files"] == installed["files"]
    assert plan["code_digest"] == installed["code_digest"]


def test_a_reinstall_replaces_rather_than_accumulates(tmp_path):
    """A second install must not leave a retired cell behind as an unreferenced file."""
    root, lane = _tree(tmp_path)
    dest = _install(root, lane)
    (dest / "c5__cc__link.manifest.json").unlink()
    (dest / "leftover.txt").write_text("stale\n", encoding="utf-8")
    _install(root, lane)
    assert (dest / "c5__cc__link.manifest.json").is_file()
    assert not (dest / "leftover.txt").exists()


def test_the_installed_names_are_flat_and_keyed_by_file_name(tmp_path):
    """`_c5_manifest_errors` resolves a pinned receipt as `folder / Path(rel).name`, so the installed
    packet must be flat or a valid install would not read back."""
    root, lane = _tree(tmp_path)
    dest = _install(root, lane)
    for path in dest.iterdir():
        assert "/" not in path.name and "\\" not in path.name
    assert all(Path(name).name == name for name in
               json.loads((dest / gate.C5_INSTALL_MANIFEST).read_text(encoding="utf-8"))["files"])


def test_the_installer_pins_lf_bytes_the_way_the_verifier_hashes_them(tmp_path):
    """c5_runner.lf_sha256 normalises line endings; a CRLF rewrite of an installed receipt must
    therefore still pass, while a content change must not."""
    root, lane = _tree(tmp_path)
    dest = _install(root, lane)
    victim = sorted(p for p in dest.iterdir() if p.name.endswith("_result.txt"))[0]
    victim.write_bytes(victim.read_bytes().replace(b"\n", b"\r\n"))
    assert not [e for e in gate.c5_gate_errors(root=root, head=HEAD) if "installed receipt tampered" in e]
    victim.write_text("PYDEC: PASS changed\n", encoding="utf-8")
    assert [e for e in gate.c5_gate_errors(root=root, head=HEAD) if "installed receipt tampered" in e]


def test_the_committed_tree_has_no_installed_c5_packet_yet(tmp_path):
    """Documents the red the coordinator will see at freeze, and pins the fact that the gate really
    is wired (a green here would mean the packet is installed, which is not true until it is)."""
    assert not (REPO / DEST).exists()
    assert gate.C5_NOT_INSTALLED in gate.c5_gate_errors(root=REPO, head=HEAD)
