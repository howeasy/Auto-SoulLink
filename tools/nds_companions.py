"""Manifest-driven NDS byte companion composition; all results stay in memory.

Uses the shared image, pins and ARMv5TE ISA modules. It is not a source builder,
linker, allocator, runtime qualification tool or production-admission registry.
"""
from __future__ import annotations

import json
import struct
from dataclasses import asdict, dataclass
from pathlib import Path

from tools import nds_image, nds_isa, nds_pins


class ComposeError(ValueError):
    def __init__(self, reason, detail=""):
        self.reason = reason
        super().__init__(reason + (": " + detail if detail else ""))


def _require(ok, reason, detail=""):
    if not ok:
        raise ComposeError(reason, detail)


def _keys(data, required, optional=()):
    _require(type(data) is dict, "manifest:object")
    _require(set(required) <= data.keys() and data.keys() <= set(required) | set(optional),
             "manifest:keys", f"expected {sorted(required)}, optional {sorted(optional)}")


def _uint(value):
    return type(value) is int and 0 <= value <= 0xFFFFFFFF


def _json(text):
    def pairs(items):
        out = {}
        for key, value in items:
            _require(key not in out, "manifest:duplicate_key", key)
            out[key] = value
        return out
    try:
        return json.loads(text, object_pairs_hook=pairs)
    except (ValueError, TypeError) as exc:
        if isinstance(exc, ComposeError):
            raise
        raise ComposeError("manifest:json", str(exc)) from exc


def _canonical(data):
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")


@dataclass(frozen=True)
class Payload:
    name: str
    size: int
    sha256: str


@dataclass(frozen=True)
class Operation:
    site: str
    kind: str                         # identity | payload | detour | replay
    payload: str | None = None
    target: int | None = None          # code pointer; bit 0 selects ISA
    form: str | None = None
    replay_of: str | None = None       # displaced detour site id
    cond: str | int | None = None


@dataclass(frozen=True)
class PatchManifest:
    pins: nds_pins.CompanionPin
    base_arm9_compressed: bool
    operations: tuple[Operation, ...]
    payloads: tuple[Payload, ...]
    reserved_sites: tuple[int, ...]
    schema_version: int = 1

    def to_dict(self):
        return asdict(self)


def load_manifest(path_or_dict):
    """Validate a per-title manifest. No implicit JSON defaults or unknown keys."""
    if isinstance(path_or_dict, PatchManifest):
        path_or_dict = path_or_dict.to_dict()  # validate even directly constructed dataclasses
    elif isinstance(path_or_dict, (str, Path)):
        path_or_dict = _json(Path(path_or_dict).read_text(encoding="utf-8"))
    data = path_or_dict
    _keys(data, {"schema_version", "pins", "base_arm9_compressed", "operations", "payloads", "reserved_sites"})
    _require(type(data["schema_version"]) is int and data["schema_version"] == 1, "manifest:version")
    _require(type(data["base_arm9_compressed"]) is bool, "manifest:compression_flag")
    try:
        pin_data = data["pins"]
        if isinstance(pin_data, nds_pins.CompanionPin):
            pin_data = json.loads(pin_data.to_json())
        else:
            # asdict uses tuples; the pins JSON contract requires arrays.
            pin_data = json.loads(json.dumps(pin_data))
        pins = nds_pins.CompanionPin.from_dict(pin_data)
    except (nds_pins.PinError, TypeError, ValueError) as exc:
        raise ComposeError("manifest:pins", str(exc)) from exc
    for key in ("operations", "payloads", "reserved_sites"):
        _require(type(data[key]) in (list, tuple), "manifest:array", key)
    payloads = []
    for row in data["payloads"]:
        _keys(row, {"name", "size", "sha256"})
        _require(type(row["name"]) is str and bool(row["name"].strip()) and _uint(row["size"]) and row["size"] > 0,
                 "payload:metadata")
        try:
            nds_pins.NamedHash(row["name"], row["sha256"])
        except nds_pins.PinError as exc:
            raise ComposeError("payload:metadata", str(exc)) from exc
        payloads.append(Payload(**row))
    _require(len({p.name for p in payloads}) == len(payloads), "payload:duplicate")
    sites = {s.id: s for s in pins.sites}
    operations = []
    for row in data["operations"]:
        _keys(row, {"site", "kind"}, {"payload", "target", "form", "replay_of", "cond"})
        _require(type(row["site"]) is str and row["site"] in sites, "site:unknown")
        _require(row["kind"] in ("identity", "payload", "detour", "replay"), "operation:kind")
        op = Operation(**row)
        if op.kind == "identity":
            _require(all(v is None for v in (op.payload, op.target, op.form, op.replay_of, op.cond)), "operation:fields")
        elif op.kind == "payload":
            _require(type(op.payload) is str and op.payload in {p.name for p in payloads}
                     and all(v is None for v in (op.target, op.form, op.replay_of, op.cond)), "operation:fields")
        elif op.kind == "detour":
            _require(_uint(op.target) and type(op.form) is str and op.payload is None and op.replay_of is None,
                     "operation:fields")
            _require(op.cond is None or type(op.cond) in (str, int), "operation:condition")
            # cond only exists in Thumb bcond; elsewhere it would be silently dropped.
            _require(not (sites[op.site].isa == "thumb" and op.form != "bcond") or op.cond in (None, "al"),
                     "operation:condition", "cond is only meaningful for a Thumb bcond detour")
        else:
            _require(type(op.replay_of) is str and op.replay_of in sites and op.form in ("b", "veneer")
                     and op.payload is None and op.target is None and op.cond is None, "operation:fields")
        operations.append(op)
    _require(len({op.site for op in operations}) == len(operations) and {op.site for op in operations} == set(sites),
             "operation:coverage", "exactly one operation per pinned site")
    _require({op.payload for op in operations if op.kind == "payload"} == {p.name for p in payloads}, "payload:unused")
    by_site = {o.site: o for o in operations}
    for op in operations:
        if op.kind == "detour":
            _require(sum(r.kind == "replay" and r.replay_of == op.site for r in operations) == 1,
                     "replay:required", op.site)
        if op.kind == "replay":
            _require(by_site[op.replay_of].kind == "detour" and sites[op.site].isa == sites[op.replay_of].isa,
                     "replay:binding")
    reserved = data["reserved_sites"]
    _require(all(_uint(v) and v % 2 == 0 for v in reserved) and len(set(reserved)) == len(reserved), "reserved:addresses")
    return PatchManifest(pins, data["base_arm9_compressed"], tuple(operations), tuple(payloads), tuple(reserved))


def _payloads(manifest, blobs):
    _require(type(blobs) is dict and blobs.keys() == {p.name for p in manifest.payloads}, "payload:keys")
    for p in manifest.payloads:
        blob = blobs[p.name]
        _require(type(blob) is bytes and len(blob) == p.size and nds_image.digest(blob) == p.sha256,
                 "payload:hash", p.name)


def distribution_artifact(manifest, payload_blobs):
    """Canonical custom artifact; omit Distribution to avoid self-hashing recursion."""
    manifest = load_manifest(manifest)
    _payloads(manifest, payload_blobs)
    data = manifest.to_dict()
    del data["pins"]["distribution"]
    return _canonical({"schema_version": 1, "manifest": data,
                       "payload_blobs": {k: v.hex() for k, v in payload_blobs.items()}})


def _mode(manifest):
    _require(manifest.pins.source_kind == "byte_patched", "source_built:refused",
             "source_built artifacts must be built by their source toolchain, never byte-patched here")
    _require(manifest.base_arm9_compressed == manifest.pins.output_arm9_compressed,
             "compression:mismatch", "this composer does not convert ARM9 storage format")
    _require(manifest.pins.distribution.format == "custom", "distribution:format", "custom recipe format required")
    _require(all(not c.source_provided for c in manifest.pins.containers), "container:source_provided",
             "overlay append/source builds are outside this composer")


def _header(data):
    _require(len(data) >= 0x400, "header:truncated")
    _require(struct.unpack_from("<H", data, 0x15E)[0] == nds_image._crc16(data[:0x15E]), "header:crc16")
    _require(0 < struct.unpack_from("<I", data, 0x80)[0] <= len(data), "header:ntr_size")
    if data[0x12] & 2:
        total = struct.unpack_from("<I", data, 0x210)[0]
        _require(0 < total <= len(data), "header:dsi_size")
        for off, sz in ((0x1C0, 0x1CC), (0x1D0, 0x1DC)):
            start, size = struct.unpack_from("<I", data, off)[0], struct.unpack_from("<I", data, sz)[0]
            _require(start + size <= total, "header:dsi_extent")


def _invariants(parent, output):
    _require(len(parent.data) == len(output.data), "image:size")
    _header(output.data)
    for offset, size in ((0x12, 1), (0x80, 4), (0x84, 4), (0x210, 4), (0x1C0, 4),
                         (0x1CC, 4), (0x1D0, 4), (0x1DC, 4)):
        _require(parent.data[offset:offset + size] == output.data[offset:offset + size],
                 "header:invariant", f"field {offset:#x}")
    if parent.unit_code & 2:
        _require(parent.data[0x180:0x400] == output.data[0x180:0x400], "dsi:header")
    for name, extent in parent.containers.items():
        if name.startswith("dsi_"):
            _require(output.containers.get(name) == extent and parent.read(name) == output.read(name), "dsi:payload", name)


def _before(parent, manifest):
    _mode(manifest)
    _require(nds_image.digest(parent.data, "sha1") == manifest.pins.parent.hashes.sha1, "base:not_pinned")
    _header(parent.data)
    try:
        nds_pins.verify_parent(parent, manifest.pins)
        verified, omitted = nds_pins.verify_sites_before(parent, manifest.pins)
        _require(not omitted and len(verified) == len(manifest.pins.sites), "site:omitted")
    except nds_pins.PinError as exc:
        if "expected-before" in str(exc):
            reason = "site:before"
        elif "compressed flag" in str(exc) or "invalid BLZ" in str(exc):
            reason = "compression:mismatch"
        else:
            reason = "base:pin"
        raise ComposeError(reason, str(exc)) from exc


def _reserved(address, length, reserved):
    _require(not any(address <= taken < address + length for taken in reserved), "site:reserved", f"{address:#x}")


def _replay(displaced, old_address, new_address, isa):
    try:
        plan = nds_isa.plan_replay(displaced, old_address, new_address, isa)
        _require(plan.ok, "isa:replay", "; ".join(plan.refusals))
        return plan.replay_bytes()
    except nds_isa.NdsIsaError as exc:
        raise ComposeError("isa:replay", str(exc)) from exc


def _encode(isa, address, target, form, cond=None):
    try:
        if isa == "thumb":
            encoded = nds_isa.thumb_detour(address, target, form, cond=cond)
        else:
            encoded = nds_isa.arm_detour(address, target, form, cond="al" if cond is None else cond)
        _decode_detour(encoded, isa, address, target, form)
        return encoded
    except nds_isa.NdsIsaError as exc:
        raise ComposeError("isa:detour", str(exc)) from exc


def _decode_detour(data, isa, address, target, form):
    """Check mode/form/target using the shared decoder; veneer literals are data."""
    decode = nds_isa.decode_thumb if isa == "thumb" else nds_isa.decode_arm
    instruction = decode(data, 0, address)
    target_isa, plain_target = nds_isa.classify_code_address(target)
    if form == "veneer":
        valid = len(data) == 8 and instruction.kind == "ldr_lit" and instruction.target == address + 4
        if isa == "thumb":
            second = decode(data, 2, address + 2)
            valid = valid and instruction.reg == 3 and second.kind == "bx" and second.reg == 3
        else:
            valid = valid and instruction.reg == 15
        valid = valid and int.from_bytes(data[4:], "little") == target
    else:
        valid = (instruction.kind == form and instruction.size == len(data)
                 and instruction.target == plain_target and instruction.target_isa == target_isa)
    _require(valid, "isa:mode", f"{isa} {form} at {address:#x}")


def _locations(parent, manifest):
    locations = {}
    decoded = {}
    for s in manifest.pins.sites:
        _require(not s.container.startswith("overlay7:"), "isa:processor", "ARMv5TE helpers target ARM9, not ARM7")
        c = next(c for c in manifest.pins.containers if c.name == s.container)
        offset = s.offset if s.offset is not None else s.address - c.ram_base
        address = c.ram_base + offset
        _reserved(address, len(bytes.fromhex(s.after)), manifest.reserved_sites)
        _require(s.expected_before is not None, "site:omitted", s.id)
        # RAM address used by edit_arm9 for an autoload's file data, not its runtime TCM address.
        if s.container in ("itcm", "dtcm"):
            if s.container not in decoded:
                decoded[s.container] = parent.autoload_block(s.container, arm9_compressed=manifest.base_arm9_compressed)
            block = decoded[s.container]
            _require(block is not None, "container:autoload", s.container)
            editor_address = parent.arm9_ram_base + block.offset + offset
        else:
            if s.container not in decoded:
                decoded[s.container] = parent.decoded(s.container, arm9_compressed=manifest.base_arm9_compressed)
            editor_address = address
        actual = decoded[s.container][offset:offset + len(bytes.fromhex(s.expected_before))]
        _require(actual == bytes.fromhex(s.expected_before), "site:before", s.id)
        # Replay consumes these verified BASE bytes, never the caller's hex or edited output.
        locations[s.id] = (s, address, editor_address, actual)
    return locations


def _run(parent, manifest, blobs):
    _before(parent, manifest)
    locations = _locations(parent, manifest)
    for op in manifest.operations:
        site, address, editor_address, before = locations[op.site]
        expected = bytes.fromhex(site.after)
        if op.kind == "identity":
            after = _replay(before, address, address, site.isa)
            _require(after == before, "identity:changed")
        elif op.kind == "payload":
            after = blobs[op.payload]
        elif op.kind == "detour":
            _require(site.continuation == address + len(before), "isa:continuation", site.id)
            _decode_detour(expected, site.isa, address, op.target, op.form)
            after = _encode(site.isa, address, op.target, op.form, op.cond)
        else:
            displaced, old_address, _, original = locations[op.replay_of]
            replay = _replay(original, old_address, address, site.isa)
            _require(site.continuation == displaced.continuation, "isa:continuation", site.id)
            target = nds_isa.code_pointer(site.isa, displaced.continuation)
            after = replay + _encode(site.isa, address + len(replay), target, op.form)
        _require(after == expected and len(after) == len(before), "site:after_plan", site.id)
        if site.container.startswith("overlay9:"):
            parent.edit_overlay(int(site.container.split(":")[1]), editor_address, before, after,
                                reason=f"{op.kind}:{site.id}")
        else:
            parent.edit_arm9(editor_address, before, after, arm9_compressed=manifest.base_arm9_compressed,
                             arm9_ram_base=manifest.pins.arm9_ram_base, reason=f"{op.kind}:{site.id}")
    try:
        return parent.apply()
    except nds_image.ImageError as exc:
        raise ComposeError("image:growth" if "growth exceeds" in str(exc) else "image:edit", str(exc)) from exc


def _audit(parent, output, manifest, spans):
    _invariants(parent, output)
    try:
        nds_image.verify_only_declared_changes(parent, output, spans)
        nds_pins.verify_output(output, manifest.pins, spans, parent=parent)
    except (nds_image.ImageError, nds_pins.PinError) as exc:
        raise ComposeError("output:verification", str(exc)) from exc


def _apply_artifact(data, artifact):
    """Injected apply callable for verify_distribution; never returns a cached output."""
    package = _json(artifact)
    _keys(package, {"schema_version", "manifest", "payload_blobs"})
    _require(type(package["schema_version"]) is int and package["schema_version"] == 1, "distribution:version")
    spec = package["manifest"]
    _require(type(spec) is dict and type(spec.get("pins")) is dict and "distribution" not in spec["pins"],
             "distribution:manifest")
    pin = spec["pins"]
    _require(type(pin.get("parent")) is dict and type(pin.get("output")) is dict, "distribution:manifest")
    pin["distribution"] = {"format": "custom", "artifact_sha256": nds_image.digest(artifact),
                           "input_sha1": pin["parent"]["hashes"]["sha1"], "output_sha1": pin["output"]["sha1"],
                           "roundtrip_verified": False}
    manifest = load_manifest(spec)
    _require(type(package["payload_blobs"]) is dict, "payload:keys")
    try:
        blobs = {k: bytes.fromhex(v) for k, v in package["payload_blobs"].items()}
    except (TypeError, ValueError) as exc:
        raise ComposeError("payload:hex", str(exc)) from exc
    _payloads(manifest, blobs)
    _require(distribution_artifact(manifest, blobs) == artifact, "distribution:canonical")
    # Borrow the caller's read-only mmap without copying a 512-MiB input; no ownership transfer.
    with nds_image.NdsImage._from_data(data) as parent:
        output, spans = _run(parent, manifest, blobs)
        with nds_image.NdsImage.load(output) as image:
            _audit(parent, image, manifest, spans)
        return output


@dataclass(frozen=True)
class CompositionReceipt:
    manifest: PatchManifest
    changed_spans: tuple[nds_image.ChangedSpan, ...]
    artifact: bytes
    determinism_verified: bool
    distribution_verified: bool
    schema_version: int = 1

    def to_dict(self):
        return {"schema_version": self.schema_version, "manifest": self.manifest.to_dict(),
                "changed_spans": [s.to_dict() for s in self.changed_spans], "artifact_hex": self.artifact.hex(),
                "determinism_verified": self.determinism_verified, "distribution_verified": self.distribution_verified}


def _receipt(value):
    if isinstance(value, CompositionReceipt):
        value = value.to_dict()
    _keys(value, {"schema_version", "manifest", "changed_spans", "artifact_hex", "determinism_verified", "distribution_verified"})
    _require(type(value["schema_version"]) is int and value["schema_version"] == 1, "receipt:version")
    _require(value["determinism_verified"] is True and value["distribution_verified"] is True, "receipt:unverified")
    _require(type(value["changed_spans"]) in (list, tuple), "receipt:spans")
    try:
        rows = []
        for row in value["changed_spans"]:
            _keys(row, nds_image.ChangedSpan.__dataclass_fields__)
            rows.append(nds_image.ChangedSpan(**row))
        artifact = bytes.fromhex(value["artifact_hex"])
    except (TypeError, ValueError) as exc:
        raise ComposeError("receipt:encoding", str(exc)) from exc
    return CompositionReceipt(load_manifest(value["manifest"]), tuple(rows), artifact, True, True)


def check(out, receipt, base):
    """Reverify the actual base/output, declared diff, invariants and distribution replay."""
    _require(isinstance(base, (bytes, str, Path)), "base:required", "actual parent bytes or path required")
    _require(isinstance(out, (bytes, str, Path)), "output:input")
    receipt = _receipt(receipt)
    _mode(receipt.manifest)
    package = _json(receipt.artifact)
    _keys(package, {"schema_version", "manifest", "payload_blobs"})
    try:
        blobs = {k: bytes.fromhex(v) for k, v in package["payload_blobs"].items()}
    except (TypeError, ValueError, AttributeError) as exc:
        raise ComposeError("distribution:payloads", str(exc)) from exc
    _require(distribution_artifact(receipt.manifest, blobs) == receipt.artifact, "receipt:artifact_binding")
    try:
        with nds_image.NdsImage.load(base) as parent:
            _before(parent, receipt.manifest)
            with nds_image.NdsImage.load(out) as output:
                _audit(parent, output, receipt.manifest, receipt.changed_spans)
            nds_pins.verify_distribution(parent, receipt.artifact, _apply_artifact, receipt.manifest.pins)
        return True
    except (nds_image.ImageError, nds_pins.PinError) as exc:
        raise ComposeError("check:verification", str(exc)) from exc


def _first_pass(base, manifest, blobs):
    with nds_image.NdsImage.load(base) as first:
        output, spans = _run(first, manifest, blobs)
        with nds_image.NdsImage.load(output) as image:
            _audit(first, image, manifest, spans)
        return nds_image.digest(output), spans


def compose(base_bytes_or_path, manifest, payload_blobs):
    """Return output bytes, changed spans and an independently replayable receipt."""
    manifest = load_manifest(manifest)
    _mode(manifest)
    _require(isinstance(base_bytes_or_path, (bytes, str, Path)), "base:required")
    _payloads(manifest, payload_blobs)
    artifact = distribution_artifact(manifest, payload_blobs)
    _require(nds_image.digest(artifact) == manifest.pins.distribution.artifact_sha256, "distribution:hash")
    try:
        # The first composition (and its audit image) die inside the helper; only its hash and
        # spans survive, so the second composition is the only retained 512-MiB result.
        first_hash, spans = _first_pass(base_bytes_or_path, manifest, payload_blobs)
        with nds_image.NdsImage.load(base_bytes_or_path) as second:
            output, repeat_spans = _run(second, manifest, payload_blobs)
        _require(nds_image.digest(output) == first_hash and repeat_spans == spans, "determinism:mismatch")
        receipt = CompositionReceipt(manifest, spans, artifact, True, True)
        check(output, receipt, base_bytes_or_path)
        return output, spans, receipt
    except (nds_image.ImageError, nds_pins.PinError, nds_isa.NdsIsaError) as exc:
        raise ComposeError("compose:verification", str(exc)) from exc
