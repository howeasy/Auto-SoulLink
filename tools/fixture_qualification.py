"""Bounded fixture enumeration and qualification orchestration, without game oracles.

Callbacks own checksum, record, boot, re-save and independent readback semantics.
This module reads artifacts and invokes explicitly registered callbacks; it never
launches an emulator, generates fixture bytes, or assigns physical qualification.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType

FULL_CHAIN = ("qualify", "boot", "resave", "post_oracle")
STATIC_CHAIN = ("qualify",)


@dataclass(frozen=True)
class FixtureCase:
    name: str
    paths: Mapping[str, Path | None]
    provenance: Mapping[str, str]


@dataclass(frozen=True)
class StageReceipt:
    stage: str
    fingerprint: str
    status: str
    problems: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    evidence: Mapping[str, str] = field(default_factory=dict)
    outputs: Mapping[str, Path] = field(default_factory=dict)


@dataclass(frozen=True)
class StageContext:
    fixture: str
    stage: str
    fingerprint: str
    artifacts: Mapping[str, bytes]
    provenance: Mapping[str, str]
    previous: tuple[dict, ...]


def enumerate_fixtures(directory: Path, *, suffix: str, max_fixtures: int = 64) -> list[Path]:
    """Enumerate one directory, rejecting absent/empty/excessive inventories."""
    if type(max_fixtures) is not int or max_fixtures < 1 or not suffix or any(c in suffix for c in "/\\"):
        raise ValueError("invalid fixture enumeration bounds/suffix")
    directory = Path(directory).resolve()
    try:
        result = []
        for path in directory.iterdir():
            if not path.name.endswith(suffix):
                continue
            if not path.is_file() or path.resolve().parent != directory:
                raise ValueError(f"fixture is not a contained regular file: {path.name}")
            result.append(path)
            if len(result) > max_fixtures:
                raise ValueError("fixture inventory exceeds declared bound")
    except OSError as exc:
        raise ValueError(f"fixture inventory unavailable: {exc}") from exc
    if not result:
        raise ValueError("fixture inventory is empty")
    return sorted(result, key=lambda path: path.name)


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _strings(value: Mapping[str, str], label: str) -> dict[str, str]:
    if not isinstance(value, Mapping) or any(not isinstance(k, str) or not k or not isinstance(v, str) or not v.strip()
                                             for k, v in value.items()):
        raise ValueError(f"{label} must be string-keyed textual facts")
    return dict(value)


class _MissingArtifact(ValueError):
    def __init__(self, role: str):
        self.role = role
        super().__init__(f"missing artifact: {role}")


def _snapshot(paths: Mapping[str, Path | None], limit: int) -> tuple[dict, dict]:
    if not isinstance(paths, Mapping) or not paths or len(paths) > 64:
        raise ValueError("one to 64 explicitly named artifacts required")
    records, contents = {}, {}
    for role, path in paths.items():
        if not isinstance(role, str) or not role:
            raise ValueError("artifact role must be a nonempty string")
        if path is None or not Path(path).is_file():
            raise _MissingArtifact(role)
        path = Path(path).resolve()
        with path.open("rb") as stream:
            data = stream.read(limit + 1)
        if len(data) > limit:
            raise ValueError(f"artifact exceeds declared byte bound: {role}")
        records[role] = {"path": str(path), "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        contents[role] = data
    return records, contents


def _receipt(receipt: StageReceipt, stage: str, fingerprint: str) -> dict:
    if not isinstance(receipt, StageReceipt):
        raise ValueError("callback must return an explicit StageReceipt")
    if receipt.stage != stage or receipt.fingerprint != fingerprint:
        raise ValueError("stale or misbound stage receipt")
    if receipt.status not in ("PASS", "FAIL", "SKIP"):
        raise ValueError("unrecognized stage status")
    if any(not isinstance(values, (tuple, list)) or any(not isinstance(v, str) for v in values)
           for values in (receipt.problems, receipt.notes)):
        raise ValueError("stage problems/notes must be text sequences")
    evidence = _strings(receipt.evidence, "stage evidence")
    if receipt.status == "PASS" and (receipt.problems or not evidence):
        raise ValueError("PASS requires evidence and no failed oracle problems")
    return {"stage": stage, "fingerprint": fingerprint, "status": receipt.status,
            "problems": list(receipt.problems), "notes": list(receipt.notes), "evidence": evidence}


def qualify_fixtures(
    cases: Iterable[FixtureCase], callbacks: Mapping[str, Callable[[StageContext], StageReceipt]], *,
    scope: str, attempt_id: str | None = None, max_fixtures: int = 64,
    max_artifact_bytes: int = 64 * 1024 * 1024,
) -> dict:
    """Run exactly the static or full required chain; a false/absent stage refuses.

    Every receipt binds this attempt, source facts, current artifact bytes, ordered
    chain and preceding receipts. Re-save outputs become hashed inputs to the
    independent post-oracle. Input changes during/between callbacks refuse.
    """
    chain = FULL_CHAIN if scope == "full" else STATIC_CHAIN
    report = {"schema": "fixture-qualification-v1", "scope": scope, "required_stages": list(chain),
              "attempt_id": attempt_id if attempt_id is not None else uuid.uuid4().hex,
              "fixtures": [], "errors": [], "passed": False}
    try:
        if scope not in ("static", "full") or not isinstance(report["attempt_id"], str) or not report["attempt_id"]:
            raise ValueError("explicit scope and nonempty attempt identifier required")
        if type(max_fixtures) is not int or max_fixtures < 1 or type(max_artifact_bytes) is not int or max_artifact_bytes < 1:
            raise ValueError("invalid qualification bounds")
        if not isinstance(callbacks, Mapping):
            raise ValueError("required stage callbacks missing")
        missing = [name for name in chain if not callable(callbacks.get(name))]
        if missing:
            raise ValueError("required stage callbacks missing: " + ", ".join(missing))
        inventory, names = [], set()
        for case in cases:
            if not isinstance(case, FixtureCase) or not isinstance(case.name, str) or not case.name:
                raise ValueError("invalid fixture descriptor")
            if case.name.casefold() in names:
                raise ValueError(f"duplicate fixture name: {case.name}")
            names.add(case.name.casefold())
            inventory.append(case)
            if len(inventory) > max_fixtures:
                raise ValueError("fixture inventory exceeds declared bound")
        if not inventory:
            raise ValueError("fixture inventory is empty")
        seen_artifacts = {}
        for case in inventory:
            row = {"name": case.name, "passed": False, "artifacts": {}, "provenance": {},
                   "stages": [], "problems": []}
            report["fixtures"].append(row)
            stage = "inputs"
            try:
                paths = dict(case.paths)
                provenance = _strings(case.provenance, "fixture provenance")
                if not provenance:
                    raise ValueError("fixture source provenance is required")
                row["provenance"] = provenance
                snapshot, contents = _snapshot(paths, max_artifact_bytes)
                for record in snapshot.values():
                    path, digest = record["path"], record["sha256"]
                    if path in seen_artifacts and seen_artifacts[path] != digest:
                        raise ValueError("shared artifact changed across fixture inventory")
                    seen_artifacts[path] = digest
                row["artifacts"] = snapshot
                for stage in chain:
                    current, _ = _snapshot(paths, max_artifact_bytes)
                    if current != snapshot:
                        raise ValueError("artifact inputs changed before stage")
                    fingerprint = _digest({"attempt": report["attempt_id"], "fixture": case.name,
                        "scope": scope, "chain": chain, "stage": stage, "provenance": provenance,
                        "artifacts": snapshot, "previous": row["stages"]})
                    context = StageContext(case.name, stage, fingerprint,
                        MappingProxyType(dict(contents)), MappingProxyType(dict(provenance)),
                        tuple(json.loads(json.dumps(row["stages"]))))
                    receipt = callbacks[stage](context)
                    record = _receipt(receipt, stage, fingerprint)
                    current, _ = _snapshot(paths, max_artifact_bytes)
                    if current != snapshot:
                        raise ValueError("artifact inputs changed during stage")
                    if receipt.status != "PASS":
                        row["stages"].append(record)
                        row["problems"].extend(receipt.problems or (f"{stage} returned {receipt.status}",))
                        break
                    if not isinstance(receipt.outputs, Mapping):
                        raise ValueError("stage output descriptors must be a mapping")
                    if stage == "resave" and not receipt.outputs:
                        raise ValueError("resave stage returned no output artifact")
                    if receipt.outputs:
                        if any(not isinstance(name, str) or not name for name in receipt.outputs):
                            raise ValueError("stage output artifact roles must be named")
                        output_paths = {stage + ":" + name: path for name, path in receipt.outputs.items()}
                        if set(output_paths) & set(paths):
                            raise ValueError("duplicate stage output artifact role")
                        if len(paths) + len(output_paths) > 64:
                            raise ValueError("combined input/output artifact roles exceed bound")
                        output_records, output_bytes = _snapshot(output_paths, max_artifact_bytes)
                        for output in output_records.values():
                            path, digest = output["path"], output["sha256"]
                            if path in seen_artifacts and seen_artifacts[path] != digest:
                                raise ValueError(f"stage output replaced a prior artifact: {path}")
                        for output in output_records.values():
                            seen_artifacts[output["path"]] = output["sha256"]
                        record["outputs"] = output_records
                        paths.update(output_paths)
                        snapshot = {**snapshot, **output_records}
                        contents.update(output_bytes)
                        row["artifacts"] = snapshot
                    row["stages"].append(record)
                else:
                    row["passed"] = True
            except Exception as exc:
                row["problems"].append(str(exc))
                if isinstance(exc, _MissingArtifact):
                    row["missing_artifact"] = exc.role
                row["stages"].append({"stage": stage, "status": "REFUSED", "problems": [str(exc)]})
        # A later callback may overwrite another case's output without touching
        # its own inputs. No earlier PASS may survive with stale final artifacts.
        for row in report["fixtures"]:
            if not row["artifacts"]:
                continue
            try:
                paths = {role: Path(record["path"]) for role, record in row["artifacts"].items()}
                final, _ = _snapshot(paths, max_artifact_bytes)
                if final != row["artifacts"]:
                    raise ValueError("artifact provenance changed before final report")
            except (ValueError, OSError) as exc:
                row["passed"] = False
                problem = f"final artifact validation refused: {exc}"
                row["problems"].append(problem)
                row["stages"].append({"stage": "final_artifacts", "status": "REFUSED", "problems": [problem]})
        report["passed"] = bool(report["fixtures"]) and all(row["passed"] for row in report["fixtures"])
    except (ValueError, OSError, TypeError) as exc:
        report["errors"].append(str(exc))
    return report
