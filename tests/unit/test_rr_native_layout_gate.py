"""Synthetic manifest/ROM closure checks; no emulator or release proof."""
import hashlib
import json
import struct
from dataclasses import replace

import pytest

from patch.tools import native_layout as layout
from tests.unit.test_rr_native_gate import spec  # noqa: F401
from tools.emulator_sandbox import SandboxError
from tools.rr import native_gate as gate


@pytest.fixture
def selected(spec):  # noqa: F811
    d = layout.load()
    files = ("lua/rr/native_layout.lua", "patch/layout/rr_v2.json")
    raw = {files[0]: layout.render(d)[layout.OUTPUTS[1]].encode(), files[1]: layout.canonical(d) + b"\n"}
    for relative, data in raw.items():
        path = spec.source_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    address, build = d["rom"]["code_base"], "a" * 64
    descriptor = struct.pack("<IHHIIIHH", 0x32444C53, 1, 2, 156, 31, 0x0203F800, 64, 0xA2)
    descriptor += build.encode() + b"\0" + layout.fingerprint(d).encode() + bytes(3)
    rom = bytes(address - d["rom"]["base"]) + descriptor
    keys = {files[0]: "../lua/rr/native_layout.lua", files[1]: "layout/rr_v2.json"}
    hashes = {keys[k]: hashlib.sha256(v).hexdigest() for k, v in raw.items()}
    manifest = {"layout_contract_schema": d["schema"], "layout_fingerprint_kind": "canonical_complete_layout_json_v1",
                "text_eol_policy": "CRLF normalized to LF for embedded build/layout identity; raw native_inputs are provenance",
                "native_inputs": hashes.copy(), "native_inputs_canonical": hashes.copy(),
                "layout_sha256": layout.fingerprint(d), "descriptor_address": address, "build_id": build,
                "rom_sha256": hashlib.sha256(rom).hexdigest(), "descriptor_size": len(descriptor)}
    return replace(spec, source_files=files), manifest, rom


def test_generated_layout_requires_complete_consistent_selected_source(selected):
    selected_spec, manifest, rom = selected
    gate._validate_generated_layout_closure(selected_spec, manifest, rom)


@pytest.mark.parametrize("fault", ["closure", "raw_hash", "canonical_hash", "policy", "layout_hash", "lua", "rom", "schema", "schema_missing"])
def test_generated_layout_rejects_each_unbound_component(selected, fault):
    selected_spec, manifest, rom = selected
    if fault == "closure":
        selected_spec = replace(selected_spec, source_files=selected_spec.source_files[:1])
    elif fault in ("raw_hash", "canonical_hash"):
        field = "native_inputs" if fault == "raw_hash" else "native_inputs_canonical"
        manifest[field]["../lua/rr/native_layout.lua"] = "0" * 64
    elif fault == "policy":
        manifest.pop("text_eol_policy")
    elif fault == "layout_hash":
        manifest["layout_sha256"] = "0" * 64
    elif fault == "schema":
        manifest["layout_contract_schema"] = "unknown"
    elif fault == "schema_missing":
        manifest.pop("layout_contract_schema")
    elif fault == "lua":
        raw = b"return {}\n"
        (selected_spec.source_root / selected_spec.source_files[0]).write_bytes(raw)
        for key in ("native_inputs", "native_inputs_canonical"):
            manifest[key]["../lua/rr/native_layout.lua"] = hashlib.sha256(raw).hexdigest()
    elif fault == "rom":
        rom = rom[:-1] + b"x"  # even descriptor padding is bound
    with pytest.raises(SandboxError):
        gate._validate_generated_layout_closure(selected_spec, manifest, rom)


def test_crlf_requires_exact_raw_provenance_and_equal_canonical_hash(selected):
    selected_spec, manifest, rom = selected
    path = selected_spec.source_root / selected_spec.source_files[0]
    raw = path.read_bytes().replace(b"\n", b"\r\n")
    path.write_bytes(raw)
    with pytest.raises(SandboxError, match="native_inputs hash"):
        gate._validate_generated_layout_closure(selected_spec, manifest, rom)
    manifest["native_inputs"]["../lua/rr/native_layout.lua"] = hashlib.sha256(raw).hexdigest()
    gate._validate_generated_layout_closure(selected_spec, manifest, rom)


def test_legacy_manifest_does_not_silently_adopt_current_layout(spec):  # noqa: F811
    gate._validate_generated_layout_closure(spec, {"layout_sha256": "legacy-header-only"}, b"old")
    assert not (spec.source_root / "lua/rr/native_layout.lua").exists()


@pytest.mark.parametrize("hash_map", ["native_inputs", "native_inputs_canonical"])
@pytest.mark.parametrize("marker", ["layout/rr_v2.json", "../lua/rr/native_layout.lua",
                                    "src/native_layout_generated.h", "tools/native_layout.py"])
def test_any_new_layout_indicator_in_either_hash_map_prevents_legacy_downgrade(spec, hash_map, marker):  # noqa: F811
    manifest = {"layout_sha256": "legacy-header-only", "native_inputs": {}, "native_inputs_canonical": {}}
    manifest[hash_map][marker] = "a" * 64
    with pytest.raises(SandboxError, match="cannot omit"):
        gate._validate_generated_layout_closure(spec, manifest, b"old")


@pytest.mark.parametrize("marker", ["./src/native_layout_generated.h", "src/../src/native_layout_generated.h",
                                    "src\\native_layout_generated.h", "TOOLS/NATIVE_LAYOUT.PY"])
def test_generated_indicator_path_alias_does_not_allow_downgrade(spec, marker):  # noqa: F811
    with pytest.raises(SandboxError, match="cannot omit"):
        gate._validate_generated_layout_closure(spec, {"native_inputs_canonical": {marker: "a" * 64}}, b"old")


@pytest.mark.parametrize("indicator", ["layout_contract_schema", "layout_fingerprint_kind"])
def test_null_generated_metadata_is_not_an_absent_legacy_contract(spec, indicator):  # noqa: F811
    with pytest.raises(SandboxError, match="cannot omit"):
        gate._validate_generated_layout_closure(spec, {indicator: None}, b"old")


def test_historical_linker_and_mailbox_inputs_still_use_legacy_path(spec):  # noqa: F811
    manifest = {key: {"src/slink.ld": "a" * 64, "src/native_mailbox.h": "b" * 64}
                for key in ("native_inputs", "native_inputs_canonical")}
    gate._validate_generated_layout_closure(spec, manifest, b"old")


def test_native_descriptor_entry_enforces_new_contract(selected, tmp_path):
    selected_spec, manifest, rom = selected
    path = tmp_path / "native.json"
    path.write_text(json.dumps(manifest))
    with pytest.raises(SandboxError, match="explicit"):
        gate._native_descriptor(replace(selected_spec, native_manifest=path, source_files=()), rom)
