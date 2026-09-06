"""Candidate layout/ABI extraction proof; no emulator or free-memory claim."""
import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

from patch.tools import native_layout as layout
from tests.rr.native.test_native_build import native_output  # noqa: F401


def test_preserved_layout_extraction_changed_only_two_fingerprint_strings():
    # This historical equivalence proves the layout-only extraction. Later
    # functional native candidates are checked by the remaining native suite;
    # their code is expected to differ and cannot stand in for this artifact.
    extraction = os.environ.get("SLINK_RR_LAYOUT_EQUIVALENCE_OUTPUT")
    if not extraction:
        pytest.fail("set SLINK_RR_LAYOUT_EQUIVALENCE_OUTPUT to preserved layout-contract-05-review", pytrace=False)
    extraction_output = Path(extraction).resolve(strict=True)
    name = os.environ.get("SLINK_RR_NATIVE_BASELINE")
    if not name:
        pytest.fail("set SLINK_RR_NATIVE_BASELINE to the preserved frozen03 build directory", pytrace=False)
    baseline = Path(name).resolve(strict=True)
    assert baseline != extraction_output
    original = bytearray((baseline / "slink_RR.gba").read_bytes())
    assert hashlib.sha256(original).hexdigest() == "3b69f1c2518fb4487d53f56d6003f328f91d05a9603de7278d9bbce488546301"
    candidate = bytearray((extraction_output / "slink_RR.gba").read_bytes())
    assert hashlib.sha256(candidate).hexdigest() == "f497e6fc575b303b4c8ece83fa300b951e5741a987b29778941e8944054503a4"
    before = json.loads((baseline / "native_manifest.json").read_text())
    after = json.loads((extraction_output / "native_manifest.json").read_text())
    assert before["descriptor_address"] == after["descriptor_address"] == 0x0837BF04
    assert len(original) == len(candidate) == 0x02000000 and original != candidate
    offset = after["descriptor_address"] - 0x08000000
    # Mask only the 64 text bytes, not terminators, struct padding, or any code.
    for start in (24, 89):
        original[offset + start:offset + start + 64] = bytes(64)
        candidate[offset + start:offset + start + 64] = bytes(64)
    assert original == candidate


def test_candidate_embeds_complete_schema_and_all_generated_inputs(native_output):  # noqa: F811
    d = layout.load()
    manifest = json.loads((native_output / "native_manifest.json").read_text())
    emitted = json.loads((native_output / "native_layout.json").read_text())
    assert emitted == d
    assert manifest["layout_contract_schema"] == d["schema"]
    assert manifest["layout_fingerprint_kind"] == "canonical_complete_layout_json_v1"
    assert manifest["layout_sha256"] == layout.fingerprint(d)
    for relative in ("layout/rr_v2.json", "tools/native_layout.py", "src/native_layout_generated.h", "src/slink.ld", "../lua/rr/native_layout.lua"):
        assert relative in manifest["native_inputs"] and relative in manifest["native_inputs_canonical"]
    rom = (native_output / "slink_RR.gba").read_bytes()
    layout.verify_descriptor(rom, manifest["descriptor_address"], manifest["build_id"], d)


@pytest.mark.parametrize("change", ["none", "offset", "signedness", "dimensions"])
def test_generated_assertions_detect_same_size_native_field_drift(rr_repo, tmp_path, change):
    raw = os.environ.get("SLINK_ARMGCC")
    if not raw:
        pytest.fail("set SLINK_ARMGCC to the pinned toolchain", pytrace=False)
    handlers = (rr_repo / "patch/src/handlers.c").read_text()
    name = "SlinkInfo" if change == "dimensions" else "GhostState"
    end = handlers.index("} " + name + ";") + len("} " + name + ";")
    declaration = handlers[handlers.rfind("typedef struct {", 0, end):end]
    if change == "offset":
        declaration = declaration.replace("s16 wx;", "s16 temporary;").replace("s16 wy;", "s16 wx;").replace("s16 temporary;", "s16 wy;")
    elif change == "signedness":
        declaration = declaration.replace("s16 wx;", "u16 wx;")
    elif change == "dimensions":
        declaration = declaration.replace("line[8][32]", "line[4][64]")
    source = tmp_path / "layout.c"
    source.write_text('#include "native_mailbox.h"\n' + declaration + f'\nSLINK_ASSERT_{layout.macro(name)}({name});\n')
    compiler = Path(raw) / ("arm-none-eabi-gcc.exe" if os.name == "nt" else "arm-none-eabi-gcc")
    result = subprocess.run([str(compiler), "-mthumb", "-mcpu=arm7tdmi", "-std=c11", "-ffreestanding",
                             "-I", str(rr_repo / "patch/src"), "-c", str(source), "-o", str(tmp_path / "layout.o")],
                            capture_output=True, text=True)
    assert (result.returncode != 0) == (change != "none"), result.stderr
    if change == "offset":
        assert "GhostState.wx offset drift" in result.stderr
    elif change != "none":
        assert "type/shape drift" in result.stderr
