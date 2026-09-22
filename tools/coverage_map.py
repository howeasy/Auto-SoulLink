#!/usr/bin/env python3
"""Validate coverage accounting against explicitly supplied obligations and artifacts.

This module neither runs lanes nor grants release/physical approval. Inventory,
mapping completeness, and evidence completeness are distinct results.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath

LAYERS = ("SOURCE", "MODEL", "PHYSICAL")
MODES = ("inventory", "mapping", "closure")
START = "<!-- COVERAGE_MAP_START -->"
END = "<!-- COVERAGE_MAP_END -->"


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _hash(value: object, lengths: tuple[int, ...] = (64,)) -> bool:
    return isinstance(value, str) and len(value) in lengths and re.fullmatch(r"[0-9a-f]+", value) is not None


def _artifact_digest(value: str | dict) -> str | None:
    return value if isinstance(value, str) else value["digest"]


def _validate_artifacts(artifacts: Mapping[str, str | dict]) -> None:
    _require(bool(artifacts) and all(_text(name) for name in artifacts),
             "artifacts must contain explicit current pins or planned target slots")
    for name, value in artifacts.items():
        if isinstance(value, str):
            _require(_hash(value, (40, 64)), f"{name}: invalid artifact digest")
            continue
        _require(isinstance(value, dict)
                 and set(value) == {"state", "digest", "base_artifact", "base_digest"},
                 f"{name}: malformed artifact target")
        _require(isinstance(value["state"], str) and value["state"] in {"PLANNED", "BUILT"},
                 f"{name}: unsupported artifact state")
        _require(value["digest"] is None if value["state"] == "PLANNED" else _hash(value["digest"], (40, 64)),
                 f"{name}: PLANNED must be unhashed; BUILT requires a digest")
        base = value["base_artifact"]
        _require(_text(base) and base in artifacts and _hash(artifacts[base], (40, 64))
                 and value["base_digest"] == artifacts[base], f"{name}: missing or stale pinned base artifact")


def _json(raw: bytes | str) -> dict:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            _require(key not in result, f"duplicate JSON key: {key}")
            result[key] = value
        return result

    result = json.loads(raw, object_pairs_hook=unique)
    _require(isinstance(result, dict), "JSON document must be an object")
    return result


@dataclass(frozen=True)
class Obligation:
    """Caller-owned evidence applicability; no identifier grants an exemption.

    All supplied artifacts apply unless artifact_ids explicitly narrows the scope.
    MODEL may supplement SOURCE/PHYSICAL but never replace a required layer.
    """

    required_layers: tuple[str, ...]
    artifact_ids: tuple[str, ...] | None = None

    def __post_init__(self):
        _require(bool(self.required_layers) and len(set(self.required_layers)) == len(self.required_layers)
                 and set(self.required_layers) <= set(LAYERS), "invalid obligation evidence layers")
        if self.artifact_ids is not None:
            _require(bool(self.artifact_ids) and len(set(self.artifact_ids)) == len(self.artifact_ids)
                     and all(_text(item) for item in self.artifact_ids), "invalid obligation artifacts")

    @property
    def allowed_layers(self) -> set[str]:
        return set(self.required_layers) | {"MODEL"}


def mapping_sha256(mapping: dict) -> str:
    """Receipt producers bind the exact mapping, independent of JSON key order."""
    return hashlib.sha256(json.dumps(mapping, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode("utf-8")).hexdigest()


def load_document(path: Path) -> dict:
    """Read exactly one marked JSON block from Markdown; ambiguity is fatal."""
    text = path.read_text(encoding="utf-8")
    _require(text.count(START) == text.count(END) == 1, "coverage map needs exactly one marked block")
    body = text.split(START, 1)[1].split(END, 1)[0].strip()
    match = re.fullmatch(r"```json\s*\n(.*?)\n```", body, re.DOTALL)
    _require(match is not None, "coverage map block must contain one JSON fence")
    return _json(match.group(1))


def requirements_from_markdown(text: str) -> dict[str, Obligation]:
    """Read explicit S/M/P tables and nonphysical Oracle-cell declarations.

    A P cell other than an em dash requires SOURCE+PHYSICAL. An em dash
    requires an explicit SOURCE-only or MODEL-only declaration; no id whitelist.
    """
    obligations = {}
    header = None
    for line in text.splitlines():
        if not line.startswith("|"):
            header = None
            continue
        cells = [cell.strip() for cell in re.split(r"(?<!\\)\|", line.strip().strip("|"))]
        lowered = [cell.lower() for cell in cells]
        if {"id", "requirement", "oracle", "s", "m", "p"} <= set(lowered):
            _require(len(set(lowered)) == len(lowered), "duplicate requirement table header")
            header = lowered
            continue
        if header is None or all(re.fullmatch(r":?-+:?", cell) for cell in cells):
            continue
        _require(len(cells) == len(header), "malformed requirement table row")
        row = dict(zip(header, cells, strict=True))
        _require(_text(row["id"]) and _text(row["requirement"]), "empty requirement identity/text")
        identifier = f"requirement:{row['id']}"
        _require(identifier not in obligations, f"duplicate obligation: {identifier}")
        if row["p"] == "—":
            declarations = {"— (SOURCE-only, P = —)": ("SOURCE",),
                            "— (MODEL-only by design)": ("MODEL",)}
            _require(row["oracle"] in declarations, f"{identifier}: missing explicit nonphysical declaration")
            layers = declarations[row["oracle"]]
            _require(row["s" if layers == ("SOURCE",) else "m"] != "—",
                     f"{identifier}: evidence cells contradict declaration")
        else:
            _require(_text(row["p"]) and row["s"] != "—" and _text(row["oracle"])
                     and not row["oracle"].startswith("—"), f"{identifier}: contradictory physical declaration")
            layers = ("SOURCE", "PHYSICAL")
        obligations[identifier] = Obligation(layers)
    _require(bool(obligations), "no requirements found in explicit S/M/P tables")
    return obligations


def protocol_from_markdown(text: str, *, section: str, layers: Sequence[str]) -> dict[str, Obligation]:
    """Read every numbered assertion in a selected section with caller-supplied layers."""
    policy = Obligation(tuple(layers))
    obligations = {}
    active_level = None
    found = False
    for line in text.splitlines():
        heading = re.match(r"^(#{1,6})\s+(.+)$", line)
        if heading:
            if re.match(rf"{re.escape(section)}\.?(?:\s|$)", heading[2]):
                _require(not found, "duplicate protocol section")
                active_level, found = len(heading[1]), True
                continue
            if active_level is not None and len(heading[1]) <= active_level:
                active_level = None
        if active_level is not None:
            item = re.match(r"^([0-9]+[a-z]?)\.\s+\S", line)
            if item:
                identifier = f"protocol:{section}.{item[1]}"
                _require(identifier not in obligations, f"duplicate protocol assertion: {identifier}")
                obligations[identifier] = policy
    _require(found and bool(obligations), "protocol section missing or contains no assertions")
    return obligations


def _mapping(mapping: object, policy: Obligation, artifacts: Mapping[str, str | dict]) -> bool:
    _require(isinstance(mapping, dict), "mapping must be an object")
    if mapping.get("status") == "UNMAPPED":
        _require(set(mapping) == {"status", "reason"} and _text(mapping["reason"]),
                 "UNMAPPED needs an explicit reason and no claimed mapping")
        return False
    fields = {"status", "stimulus", "artifacts", "positive_control", "refusal_control",
              "oracle", "receipt_marker", "lane"}
    _require(set(mapping) == fields and mapping["status"] == "MAPPED", "unsupported/incomplete mapping")
    stimulus = mapping["stimulus"]
    _require(isinstance(stimulus, dict) and set(stimulus) == {"kind", "description"}
             and stimulus["kind"] in {"NATURAL", "COMMAND", "SOURCE", "MODEL"}
             and _text(stimulus["description"]), "missing stimulus kind/description")
    if "PHYSICAL" in policy.required_layers:
        _require(stimulus["kind"] in {"NATURAL", "COMMAND"},
                 "PHYSICAL obligation requires a natural or command stimulus, not MODEL/SOURCE execution")
    for field in fields - {"status", "stimulus", "artifacts"}:
        _require(_text(mapping[field]), f"missing mapping {field}")
    wanted = policy.artifact_ids if policy.artifact_ids is not None else artifacts
    expected = {identifier: artifacts[identifier] for identifier in wanted}
    _require(mapping["artifacts"] == expected, "mapping artifact inventory/hash differs from current policy")
    return True


def _receipt(evidence: dict, *, identifier: str, layer: str, mapping: dict,
             inputs: Mapping[str, str], read_receipt: Callable[[str], bytes]) -> None:
    _require(all(_artifact_digest(value) is not None for value in mapping["artifacts"].values()),
             "unbuilt or unhashed artifact target cannot support CLOSED evidence")
    _require(set(evidence) == {"status", "receipt"}, "CLOSED evidence needs exactly one receipt")
    reference = evidence["receipt"]
    _require(isinstance(reference, dict) and set(reference) == {"path", "sha256"}
             and _text(reference["path"]) and _hash(reference["sha256"]), "invalid receipt reference")
    path = reference["path"]
    _require(not PurePosixPath(path).is_absolute() and ".." not in PurePosixPath(path).parts
             and "\\" not in path and ":" not in path, "receipt path must stay relative to its evidence root")
    raw = read_receipt(path)
    _require(isinstance(raw, bytes) and hashlib.sha256(raw).hexdigest() == reference["sha256"],
             "receipt bytes do not match pinned SHA256")
    receipt = _json(raw)
    _require(type(receipt.get("schema_version")) is int and receipt["schema_version"] == 1,
             "unsupported receipt schema")
    expected = {
        "obligation_id": identifier, "layer": layer, "verdict": "PASS",
        "input_sha256": dict(inputs), "mapping_sha256": mapping_sha256(mapping),
        "artifacts": mapping["artifacts"], "lane": mapping["lane"],
        "marker": mapping["receipt_marker"], "controls": {"positive": "PASS", "refusal": "PASS"},
    }
    for field, value in expected.items():
        _require(receipt.get(field) == value, f"receipt {field} is stale, missing, or contradictory")


def validate_coverage(document: dict, *, obligations: Mapping[str, Obligation],
                      artifacts: Mapping[str, str | dict], inputs: Mapping[str, str],
                      read_receipt: Callable[[str], bytes], mode: str = "mapping") -> dict:
    """Check metadata against injected policy; never execute tests or infer exemptions.

    Invalid caller policy raises ValueError. Invalid coverage/receipts produce a
    report with ok=False. Inventory mode permits honest UNMAPPED/OPEN entries.
    Every CLOSED claim is validated in every mode, even if another layer is OPEN.
    """
    _require(mode in MODES, "unsupported coverage mode")
    _require(bool(obligations) and all(_text(k) and isinstance(v, Obligation) for k, v in obligations.items()),
             "obligations must be a nonempty, explicit caller inventory")
    _validate_artifacts(artifacts)
    _require(bool(inputs) and all(_text(k) and _hash(v) for k, v in inputs.items()),
             "inputs must contain explicit document SHA256 pins")
    for policy in obligations.values():
        _require(policy.artifact_ids is None or set(policy.artifact_ids) <= set(artifacts),
                 "obligation references an artifact outside supplied policy")
    report = {"schema_version": 1, "mode": mode, "ok": False, "mapping_complete": False,
              "evidence_complete": False, "unmapped": [], "open": {layer: [] for layer in LAYERS},
              "errors": [], "unbuilt_artifacts": [], "obligations": len(obligations)}
    errors = report["errors"]
    try:
        _require(isinstance(document, dict) and set(document) == {"schema_version", "input_sha256", "rows"},
                 "unsupported coverage document fields")
        _require(type(document["schema_version"]) is int and document["schema_version"] == 1,
                 "unsupported coverage schema")
        _require(document["input_sha256"] == dict(inputs), "coverage input pins are stale or incomplete")
        _require(isinstance(document["rows"], list), "coverage rows must be a list")
    except ValueError as exc:
        errors.append(str(exc))
        return report
    seen = set()
    for row in document["rows"]:
        identifier = row.get("id") if isinstance(row, dict) else None
        try:
            _require(_text(identifier) and identifier in obligations, f"unknown obligation: {identifier}")
            _require(identifier not in seen, f"duplicate obligation: {identifier}")
            seen.add(identifier)
            policy = obligations[identifier]
            _require(set(row) == {"id", "required_layers", "mapping", "evidence"}, "unsupported row fields")
            _require(row["required_layers"] == list(policy.required_layers),
                     "required layers differ from caller policy; no automatic exemptions")
            mapped = _mapping(row["mapping"], policy, artifacts)
            if not mapped:
                report["unmapped"].append(identifier)
            else:
                for name, artifact in row["mapping"]["artifacts"].items():
                    if _artifact_digest(artifact) is None and name not in report["unbuilt_artifacts"]:
                        report["unbuilt_artifacts"].append(name)
            evidence = row["evidence"]
            _require(isinstance(evidence, dict) and set(policy.required_layers) <= set(evidence)
                     and set(evidence) <= policy.allowed_layers, "missing or inapplicable evidence layer")
            for layer, claim in evidence.items():
                _require(isinstance(claim, dict), f"{layer}: malformed evidence")
                if claim.get("status") == "OPEN":
                    _require(set(claim) == {"status", "reason"} and _text(claim["reason"]),
                             f"{layer}: OPEN needs an explicit reason")
                    if layer in policy.required_layers:
                        report["open"][layer].append(identifier)
                else:
                    _require(claim.get("status") == "CLOSED" and mapped,
                             f"{layer}: unknown evidence status or closed UNMAPPED obligation")
                    _receipt(claim, identifier=identifier, layer=layer, mapping=row["mapping"],
                             inputs=inputs, read_receipt=read_receipt)
        except (ValueError, OSError, KeyError, TypeError) as exc:
            errors.append(f"{identifier}: {exc}")
    for identifier in sorted(set(obligations) - seen):
        errors.append(f"missing obligation: {identifier}")
    report["mapping_complete"] = not errors and not report["unmapped"]
    report["unbuilt_artifacts"].sort()
    report["evidence_complete"] = (report["mapping_complete"] and not any(report["open"].values())
                                   and not report["unbuilt_artifacts"])
    if mode != "inventory" and report["unmapped"]:
        errors.append(f"mapping incomplete: {len(report['unmapped'])} UNMAPPED obligations")
    if mode == "closure" and any(report["open"].values()):
        errors.append("evidence incomplete: required layers remain OPEN; mapping is not behavioral proof")
    if mode == "closure" and report["unbuilt_artifacts"]:
        errors.append("evidence incomplete: unbuilt or unhashed artifact targets remain")
    report["ok"] = not errors
    return report


def _artifacts(raw: bytes, collection: str, digest_field: str, selected: list[str]) -> dict[str, str]:
    value = _json(raw)
    for component in collection.split("."):
        _require(isinstance(value, dict) and component in value, "artifact collection missing")
        value = value[component]
    _require(isinstance(value, dict) and len(set(selected)) == len(selected), "invalid artifact selection")
    result = {}
    for identifier in selected:
        _require(identifier in value and isinstance(value[identifier], dict), f"artifact missing: {identifier}")
        _require(value[identifier].get("state", "BUILT") == "BUILT",
                 f"unbuilt artifact cannot be selected as a pinned base: {identifier}")
        digest = value[identifier].get(digest_field)
        _require(_hash(digest, (40, 64)), f"artifact digest missing: {identifier}")
        result[identifier] = digest
    return result


def _bind_targets(obligations: dict[str, Obligation], artifacts: dict[str, str | dict],
                  planned: list[str], bindings: list[str]) -> None:
    """Apply explicit CLI policy; target definitions never come from the map."""
    if not planned and not bindings:
        return
    bases = tuple(artifacts)
    targets = set()
    for specification in planned:
        parts = specification.split("=")
        _require(len(parts) == 2 and all(_text(part) for part in parts), "planned target requires SLOT=BASE")
        name, base = parts
        _require(name not in artifacts and base in bases, "duplicate planned target or unknown selected base")
        artifacts[name] = {"state": "PLANNED", "digest": None,
                           "base_artifact": base, "base_digest": artifacts[base]}
        targets.add(name)
    for name, obligation in obligations.items():
        obligations[name] = replace(obligation, artifact_ids=bases)
    bound = set()
    used = set()
    for specification in bindings:
        parts = specification.split("=")
        _require(len(parts) == 2, "target binding requires OBLIGATION[,OBLIGATION]=TARGET[,TARGET]")
        identifiers, wanted = parts[0].split(","), tuple(parts[1].split(","))
        _require(bool(wanted) and len(set(wanted)) == len(wanted) and set(wanted) <= targets,
                 "target binding needs declared, unique planned targets")
        for identifier in identifiers:
            _require(identifier in obligations and identifier not in bound, "unknown or duplicate target-bound obligation")
            obligations[identifier] = replace(obligations[identifier], artifact_ids=wanted)
            bound.add(identifier)
        used.update(wanted)
    _require(used == targets, "planned target is not bound to an obligation")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("map", "requirements", "protocol", "artifact-policy"):
        parser.add_argument(f"--{flag}", type=Path, required=True)
    parser.add_argument("--protocol-section", required=True)
    parser.add_argument("--protocol-layers", nargs="+", choices=LAYERS, required=True)
    parser.add_argument("--artifact-collection", required=True)
    parser.add_argument("--artifact-digest-field", required=True)
    parser.add_argument("--artifact-id", action="append", required=True)
    parser.add_argument("--planned-target", action="append", default=[], metavar="SLOT=BASE")
    parser.add_argument("--target-binding", action="append", default=[],
                        metavar="OBLIGATION[,OBLIGATION]=TARGET[,TARGET]")
    parser.add_argument("--mode", choices=MODES, default="mapping")
    parser.add_argument("--receipt-root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    try:
        requirement_bytes = args.requirements.read_bytes()
        protocol_bytes = args.protocol.read_bytes()
        artifact_bytes = args.artifact_policy.read_bytes()
        obligations = requirements_from_markdown(requirement_bytes.decode("utf-8"))
        obligations.update(protocol_from_markdown(protocol_bytes.decode("utf-8"),
                                                 section=args.protocol_section, layers=args.protocol_layers))
        artifacts = _artifacts(artifact_bytes, args.artifact_collection, args.artifact_digest_field, args.artifact_id)
        _bind_targets(obligations, artifacts, args.planned_target, args.target_binding)
        inputs = {name: hashlib.sha256(raw).hexdigest() for name, raw in (
            ("requirements", requirement_bytes), ("protocol", protocol_bytes), ("artifact_policy", artifact_bytes))}
        evidence_root = args.receipt_root.resolve()

        def read_receipt(path):
            target = (evidence_root / path).resolve()
            _require(target.is_relative_to(evidence_root), "receipt escapes evidence root")
            return target.read_bytes()

        result = validate_coverage(load_document(args.map), obligations=obligations, artifacts=artifacts,
                                   inputs=inputs, read_receipt=read_receipt, mode=args.mode)
        print(json.dumps(result, indent=2))
        return 0 if result["ok"] else 1
    except (OSError, ValueError) as exc:
        print(f"Coverage map refused: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
