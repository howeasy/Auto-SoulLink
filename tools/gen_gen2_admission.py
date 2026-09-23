#!/usr/bin/env python3
"""Generate/validate P1 artifact facts; this is not a runtime admission boundary.

Without --provenance, generate hashless PLANNED rows. Passing a verified builder
receipt explicitly promotes the four clean rows to BUILT after checking the
adjacent .sym/.map files; --overlay-provenance (P4.1f) likewise promotes the three
overlay rows to BUILT from the SLink companion build receipt (still FUTURE: BUILT is
an identity, never a runtime admission). Neither mode emits ADMITTED artifacts. G1 opens only for a
title in G1_ADMITTED (an owner ruling), only once its rows are BUILT, and the gate row
is the grant, never the proof: lua/gen2/entry.lua re-validates that title's shipped
PHYSICAL receipts at every load. Overlay/ghost qualification belongs to later owners.

    python tools/gen_gen2_admission.py
    python tools/gen_gen2_admission.py --provenance data/gen2/build_provenance.json
    python tools/gen_gen2_admission.py --provenance data/gen2/build_provenance.json --check
    python tools/gen_gen2_admission.py --provenance data/gen2/build_provenance.json         --overlay-provenance data/gen2/overlay_provenance.json --check
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_PINS = {
    "pokecrystal": ("7a7881d0d62e0ddbd82dcf10e7116807487ac651",
                    ["pokecrystal.gbc", "pokecrystal11.gbc"]),
    "pokegold": ("656583c939d30f920a316177311a502dd222b57c",
                 ["pokegold.gbc", "pokesilver.gbc"]),
}
OUTPUT_PINS = {
    "pokecrystal": ("pokecrystal", "f4cd194bdee0d04ca4eac29e09b8e4e9d818c133"),
    "pokecrystal11": ("pokecrystal", "f2f52230b536214ef7c9924f483392993e226cfb"),
    "pokegold": ("pokegold", "d8b8a3600a465308c9953dfa04f0081c05bdcb94"),
    "pokesilver": ("pokegold", "49b163f7e57702bc939d642a18f591de55d92dae"),
}
TITLE_OUTPUTS = {
    "crystal": [("pokecrystal", "1.0", "SELECTED"), ("pokecrystal11", "1.1", "BUILD_ONLY")],
    "gold": [("pokegold", "US", "SELECTED")],
    "silver": [("pokesilver", "US", "SELECTED")],
}
RGBDS_BINARIES = ("rgbasm", "rgblink", "rgbfix", "rgbgfx")
# Owner ruling O-22 (docs/gen2/REVIEW_RECORD.md): a title's G1 gate opens only after its U1
# engine-site and U2 write-window receipts pass PHYSICAL (data/games/<pack>/receipts/).
# O-23: Silver's U2 gate is Gold's write-window receipt while the checkpoint rows stay identical.
G1_ADMITTED = {"crystal": "O-22", "gold": "O-22", "silver": "O-22+O-23"}


def _gate(title: str, built: bool) -> dict:
    if built and title in G1_ADMITTED:
        return {"id": "G1", "state": "ADMITTED", "authority": G1_ADMITTED[title]}
    return {"id": "G1", "state": "PENDING"}


def render(value: dict) -> str:
    return json.dumps(value, indent=2) + "\n"


def content_sha256(value: dict) -> str:
    """Hash generated JSON content (indent 2, LF, insertion order)."""
    return hashlib.sha256(render(value).encode("utf-8")).hexdigest()


def lock_sha256(lock: dict, lock_bytes: bytes | None = None) -> str:
    """File consumers supply the exact bytes parsed; dict-only callers use render()."""
    if lock_bytes is None:
        return content_sha256(lock)
    require(isinstance(lock_bytes, bytes), "lock snapshot must be bytes")
    require(_parse_json(lock_bytes, "lock snapshot") == lock,
            "lock snapshot differs from supplied lock data")
    return hashlib.sha256(lock_bytes).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def object_at(value: object, label: str) -> dict:
    require(isinstance(value, dict), f"{label}: expected an object")
    return value


def is_hash(value: object, width: int) -> bool:
    return isinstance(value, str) and re.fullmatch(rf"[0-9a-f]{{{width}}}", value) is not None


def validate_lock(lock: dict) -> None:
    object_at(lock, "lock")
    require(type(lock.get("schema_version")) is int and lock["schema_version"] == 1,
            "lock: unsupported schema_version")
    require(lock.get("rgbds_version") == "v1.0.3", "lock: unpinned RGBDS version")
    require(lock.get("w64devkit_version") == "2.10.0", "lock: unpinned w64devkit version")
    sources = object_at(lock.get("sources"), "lock.sources")
    require(set(sources) == set(SOURCE_PINS), "lock: incorrect source inventory")
    for name, (commit, targets) in SOURCE_PINS.items():
        source = object_at(sources[name], name)
        require(source.get("url") == f"https://github.com/pret/{name}", f"{name}: wrong source URL")
        require(source.get("commit") == commit, f"{name}: unpinned source commit")
        require(source.get("make_targets") == targets, f"{name}: wrong make targets")
    outputs = object_at(lock.get("outputs"), "lock.outputs")
    require(set(outputs) == set(OUTPUT_PINS), "lock: incorrect output inventory")
    for name, (source, sha1) in OUTPUT_PINS.items():
        row = object_at(outputs[name], name)
        require(row.get("source") == source and row.get("filename") == name + ".gbc",
                f"{name}: wrong source/output mapping")
        require(row.get("sha1") == sha1, f"{name}: wrong pinned ROM SHA1")
        require("sym_sha256" in row and "map_sha256" in row, f"{name}: missing artifact hash fields")
        if row.get("state") == "UNBUILT":
            require(row["sym_sha256"] is None and row["map_sha256"] is None,
                    f"{name}: UNBUILT must have null symbol/map hashes")
        else:
            require(row.get("state") == "BUILT", f"{name}: explicit UNBUILT/BUILT state required")
            require(is_hash(row["sym_sha256"], 64) and is_hash(row["map_sha256"], 64),
                    f"{name}: BUILT requires both symbol/map hashes")


def validate_provenance(lock: dict, provenance: dict, *, lock_bytes: bytes | None = None) -> None:
    validate_lock(lock)
    receipt = object_at(provenance, "provenance")
    require(receipt.get("schema") == "gen2-build-provenance-v1"
            and type(receipt.get("schema_version")) is int and receipt["schema_version"] == 1,
            "provenance: unsupported schema")
    require(receipt.get("evidence_level") == "SOURCE", "provenance: build evidence must be SOURCE")
    require(receipt.get("lock_sha256") == lock_sha256(lock, lock_bytes), "provenance: lock hash mismatch")
    sources = object_at(receipt.get("sources"), "provenance.sources")
    require(set(sources) == set(SOURCE_PINS), "provenance: source inventory mismatch")
    for name, expected in lock["sources"].items():
        observed = object_at(sources[name], f"provenance.sources.{name}")
        require(all(observed.get(key) == expected[key] for key in ("url", "commit", "make_targets"))
                and observed.get("clean") is True, f"provenance: {name} source mismatch or dirty tree")
    toolchain = object_at(receipt.get("toolchain"), "provenance.toolchain")
    require(toolchain.get("w64devkit_requested_version") == lock["w64devkit_version"],
            "provenance: requested build-tool version mismatch")
    rgbds = object_at(toolchain.get("rgbds"), "provenance.rgbds")
    require(rgbds.get("version") == lock["rgbds_version"], "provenance: RGBDS version mismatch")
    binaries = object_at(rgbds.get("binaries"), "provenance.rgbds.binaries")
    require(set(binaries) == set(RGBDS_BINARIES), "provenance: missing RGBDS binary")
    for name in RGBDS_BINARIES:
        binary = object_at(binaries[name], f"provenance.{name}")
        version = binary.get("version")
        require(isinstance(version, str)
                and re.fullmatch(rf"{name} v1\.0\.3", version.strip()) is not None,
                f"provenance: {name} version mismatch")
        require(is_hash(binary.get("sha256"), 64), f"provenance: {name} binary hash missing")
    build_tools = object_at(toolchain.get("build_tools"), "provenance.build_tools")
    binaries = object_at(build_tools.get("binaries"), "provenance.build_tools.binaries")
    require(set(binaries) >= {"make", "gcc", "sh"}, "provenance: missing required build tools")
    for name, value in binaries.items():
        binary = object_at(value, f"provenance.{name}")
        require(isinstance(binary.get("version"), str) and bool(binary["version"].strip())
                and is_hash(binary.get("sha256"), 64), f"provenance: {name} identity missing")
    roms = object_at(receipt.get("roms"), "provenance.roms")
    symbols = object_at(receipt.get("symbols"), "provenance.symbols")
    require(set(roms) == set(OUTPUT_PINS), "provenance: ROM inventory mismatch")
    require(set(symbols) == {f"{name}.{ext}" for name in OUTPUT_PINS for ext in ("sym", "map")},
            "provenance: symbol/map inventory mismatch")
    for name, expected in lock["outputs"].items():
        require(expected["state"] == "BUILT", f"provenance: {name} still UNBUILT")
        observed = object_at(roms[name], f"provenance.roms.{name}")
        require(all(observed.get(key) == expected[key] for key in ("source", "filename", "sha1")),
                f"provenance: {name} ROM mismatch")
        for ext in ("sym", "map"):
            require(symbols[f"{name}.{ext}"] == expected[f"{ext}_sha256"],
                    f"provenance: {name}.{ext} hash mismatch")


def overlay_row(title: str, lock: dict, overlay: dict) -> dict:
    """The BUILT identity of one title's SLink companion build (data/gen2/overlay_provenance.json).

    The null (mailbox-only) build is byte-identical to the clean ROM and is refused: one hash
    must never name two artifact kinds.
    """
    object_at(overlay, "overlay provenance")
    require(overlay.get("schema") == "gen2-overlay-provenance-v1", "overlay provenance: unsupported schema")
    artifact = TITLE_OUTPUTS[title][0][0]
    sources = object_at(overlay.get("sources"), "overlay provenance.sources")
    source = lock["outputs"][artifact]["source"]
    require(object_at(sources.get(source), f"overlay {source}").get("commit") == lock["sources"][source]["commit"],
            f"overlay provenance: {source} commit differs from the lock")
    out = object_at(object_at(overlay.get("outputs"), "overlay provenance.outputs").get(artifact),
                    f"overlay {artifact}")
    clean = lock["outputs"][artifact]["sha1"]
    require(out.get("slink_title") == title and out.get("base_sha1") == clean,
            f"overlay provenance: {artifact} title/base differs from the clean pin")
    require(out.get("identical_to_clean") is False and is_hash(out.get("sha1"), 40) and out["sha1"] != clean,
            f"overlay provenance: {artifact} is the null overlay (identical to clean); nothing to promote")
    require(is_hash(out.get("md5"), 32), f"overlay provenance: {artifact} md5 missing")
    ups = object_at(out.get("ups"), f"overlay {artifact}.ups")
    require(isinstance(ups.get("file"), str) and is_hash(ups.get("sha256"), 64),
            f"overlay provenance: {artifact} UPS identity missing")
    return {"id": f"{title}_overlay", "kind": "overlay", "revision": TITLE_OUTPUTS[title][0][1],
            "selection": "FUTURE", "status": "BUILT", "sha1": out["sha1"], "md5": out["md5"],
            "base_sha1": clean, "ups": {"file": ups["file"], "sha256": ups["sha256"]}}


def _planned_matrix(title: str, source_lock_sha256: str) -> dict:
    rows = [{"id": name, "kind": "clean", "revision": revision, "selection": selection,
             "lock_output": name, "status": "PLANNED"}
            for name, revision, selection in TITLE_OUTPUTS[title]]
    rows += [{"id": f"{title}_{kind}", "kind": kind, "revision": TITLE_OUTPUTS[title][0][1],
              "selection": "FUTURE", "status": "PLANNED"} for kind in ("overlay", "ghost")]
    kinds = ("clean", "overlay", "ghost")
    return {
        "schema_version": 1, "purpose": "P1_ARTIFACT_MATRIX_ONLY", "foundation": "gen2_gsc",
        "title": title, "pack": f"gen2_{title}", "selected_revision": TITLE_OUTPUTS[title][0][1],
        "source_lock_sha256": source_lock_sha256, "gate": _gate(title, False),
        "unknown_hash_policy": "REFUSE", "refused_kinds": ["archipelago", "randomized", "unknown"],
        "authorized_title_pairings": [["crystal", "crystal"], ["crystal", "gold"],
                                      ["crystal", "silver"], ["gold", "gold"],
                                      ["gold", "silver"], ["silver", "silver"]],
        "artifact_kind_compatibility": {
            left: {right: "REQUIRES_G1" if left == right == "clean" else "REFUSED"
                   for right in kinds} for left in kinds},
        "artifacts": rows,
    }


def build_matrices(lock: dict, provenance: dict | None = None, *,
                   lock_bytes: bytes | None = None, overlay: dict | None = None) -> dict[str, dict]:
    validate_lock(lock)
    source_lock_sha256 = lock_sha256(lock, lock_bytes)
    if provenance is not None:
        validate_provenance(lock, provenance, lock_bytes=lock_bytes)
    matrices = {f"gen2_{title}": _planned_matrix(title, source_lock_sha256) for title in TITLE_OUTPUTS}
    if provenance is not None:
        for matrix in matrices.values():
            matrix["gate"] = _gate(matrix["title"], True)
            for row in matrix["artifacts"]:
                if row["kind"] == "clean":
                    row.update(status="BUILT", sha1=lock["outputs"][row["id"]]["sha1"],
                               build_provenance_sha256=content_sha256(provenance))
    if overlay is not None:
        require(provenance is not None, "overlay rows require the clean build provenance")
        for matrix in matrices.values():
            rows = matrix["artifacts"]
            index = next(i for i, row in enumerate(rows) if row["kind"] == "overlay")
            rows[index] = overlay_row(matrix["title"], lock, overlay)
    return matrices


def validate_matrix(matrix: dict, lock: dict, provenance: dict | None = None, *,
                    lock_bytes: bytes | None = None, overlay: dict | None = None) -> None:
    validate_lock(lock)
    object_at(matrix, "matrix")
    require(isinstance(matrix.get("title"), str) and matrix["title"] in TITLE_OUTPUTS,
            "matrix: unsupported title")
    expected = _planned_matrix(matrix["title"], lock_sha256(lock, lock_bytes))
    rows = matrix.get("artifacts")
    expected["gate"] = _gate(matrix["title"], isinstance(rows, list) and any(
        isinstance(row, dict) and row.get("status") == "BUILT" for row in rows))
    require(set(matrix) == set(expected), "matrix: missing or unsupported fields")
    for key in expected.keys() - {"artifacts"}:
        require(matrix[key] == expected[key], f"matrix: {key} differs from P1 contract")
    rows = matrix["artifacts"]
    require(isinstance(rows, list) and len(rows) == len(expected["artifacts"]),
            "matrix: incorrect artifact inventory")
    if any(isinstance(row, dict) and row.get("status") == "BUILT" for row in rows):
        require(provenance is not None, "matrix: BUILT rows require build provenance")
        validate_provenance(lock, provenance, lock_bytes=lock_bytes)
    for row, planned in zip(rows, expected["artifacts"], strict=True):
        object_at(row, "matrix artifact")
        status = row.get("status")
        require(status != "ADMITTED", "matrix: ADMITTED requires separate owner G1 acceptance; P1 cannot grant it")
        if status == "PLANNED":
            require(row == planned, "matrix: PLANNED row must match selected facts and carry no hash")
        elif planned["kind"] == "overlay":
            require(status == "BUILT" and overlay is not None,
                    "matrix: a BUILT overlay row requires the overlay provenance")
            require(row == overlay_row(matrix["title"], lock, overlay), "matrix: BUILT overlay identity mismatch")
        else:
            require(status == "BUILT" and planned["kind"] == "clean", "matrix: unsupported artifact state/kind")
            built = {**planned, "status": "BUILT", "sha1": lock["outputs"][planned["id"]]["sha1"],
                     "build_provenance_sha256": content_sha256(provenance)}
            require(row == built, "matrix: BUILT identity/hash/provenance mismatch")


def _parse_json(raw: bytes, label: str) -> dict:
    # Reject duplicate keys rather than silently accepting a contradictory catalog.
    def unique(pairs):
        value = {}
        for key, item in pairs:
            require(key not in value, f"{label}: duplicate JSON key {key}")
            value[key] = item
        return value
    return object_at(json.loads(raw.decode("utf-8"), object_pairs_hook=unique), label)


def _load(path: Path) -> dict:
    return _parse_json(path.read_bytes(), str(path))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, default=ROOT / "data/gen2_sources.lock.json")
    parser.add_argument("--out-dir", type=Path, default=ROOT / "data/games")
    parser.add_argument("--provenance", type=Path, help="explicitly promote verified clean builds to BUILT")
    parser.add_argument("--overlay-provenance", type=Path,
                        help="explicitly promote the SLink companion builds' overlay rows to BUILT")
    parser.add_argument("--check", action="store_true", help="validate exact current files without writing")
    args = parser.parse_args(argv)
    try:
        lock_bytes = args.lock.read_bytes()
        lock = _parse_json(lock_bytes, str(args.lock))
        provenance = _load(args.provenance) if args.provenance else None
        overlay = _load(args.overlay_provenance) if args.overlay_provenance else None
        matrices = build_matrices(lock, provenance, lock_bytes=lock_bytes, overlay=overlay)
        if provenance is not None:
            for name, expected in provenance["symbols"].items():
                artifact = args.provenance.parent / name
                require(hashlib.sha256(artifact.read_bytes()).hexdigest() == expected,
                        f"provenance: on-disk {name} hash mismatch")
        pending = []
        for pack, matrix in matrices.items():
            path = args.out_dir / pack / "admission.json"
            generated = render(matrix)
            if path.exists():
                current = _load(path)
                rows = current.get("artifacts", [])
                require(isinstance(rows, list) and all(isinstance(row, dict) for row in rows),
                        "existing matrix: malformed artifacts")
                require(all(row.get("status") != "ADMITTED" for row in rows),
                        "existing ADMITTED matrix belongs to G1 owner; P1 cannot overwrite it")
                if provenance is None:
                    require(all(row.get("status") == "PLANNED" for row in rows),
                            "existing BUILT/ADMITTED matrix requires explicit provenance; refusing downgrade")
                if overlay is None:
                    require(all(row.get("status") == "PLANNED" for row in rows if row.get("kind") == "overlay"),
                            "existing BUILT overlay row requires --overlay-provenance; refusing downgrade")
                if args.check:
                    validate_matrix(current, lock, provenance, lock_bytes=lock_bytes, overlay=overlay)
            if args.check:
                require(path.exists() and path.read_bytes() == generated.encode("utf-8"),
                        f"{path}: stale or missing; regenerate the artifact matrix")
            else:
                pending.append((path, generated))
        # Validate every input and existing catalog before any publication.
        for path, generated in pending:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(generated, encoding="utf-8", newline="\n")
        print("Gen 2 artifact matrices are current; G1: " + ", ".join(
            f"{m['title']} {m['gate']['state']}" for m in matrices.values()))
        return 0
    except (OSError, ValueError) as exc:
        print(f"Gen 2 artifact matrix refused: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
