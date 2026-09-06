"""Selected native build evidence. No emulator; inputs must be explicit."""
import hashlib
import importlib.util
import json
import os
import struct
import subprocess
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def native_output():
    raw = os.environ.get("SLINK_RR_NATIVE_OUTPUT")
    if not raw:
        pytest.fail("set SLINK_RR_NATIVE_OUTPUT to the isolated candidate build directory", pytrace=False)
    path = Path(raw).resolve(strict=True)
    return path


def test_native_descriptor_and_artifact_hashes_match(native_output):
    manifest = json.loads((native_output / "native_manifest.json").read_text())
    rom = (native_output / "slink_RR.gba").read_bytes()
    patch = (native_output / "SLink-RR.ups").read_bytes()
    assert hashlib.sha256(rom).hexdigest() == manifest["rom_sha256"]
    assert hashlib.sha1(rom).hexdigest() == manifest["rom_sha1"]
    assert hashlib.sha256(patch).hexdigest() == manifest["patch_sha256"]
    offset = manifest["descriptor_address"] - 0x08000000
    descriptor = rom[offset:offset + 156]
    assert struct.unpack_from("<IHHIIIHH", descriptor) == (0x32444C53, 1, 2, 156, 31, 0x0203F800, 64, 0xA2)
    assert descriptor[24:89] == manifest["build_id"].encode() + b"\0"
    assert descriptor[89:154] == manifest["layout_sha256"].encode() + b"\0"
    assert manifest["arena_ownership"].startswith("UNRESOLVED")


def test_manifest_binds_current_native_inputs(native_output, rr_repo):
    manifest = json.loads((native_output / "native_manifest.json").read_text())
    for relative, expected in manifest["native_inputs"].items():
        source = (rr_repo / "patch" / relative).resolve(strict=True)
        assert source.is_relative_to(rr_repo)
        assert hashlib.sha256(source.read_bytes()).hexdigest() == expected, relative
        assert hashlib.sha256(source.read_bytes().replace(b"\r\n", b"\n")).hexdigest() == manifest["native_inputs_canonical"][relative]


def test_embedded_native_identity_normalizes_checkout_line_endings(rr_repo):
    source = (rr_repo / "patch/tools/build.py").read_text()
    start = source.index("def canonical_text_bytes(")
    end = source.index("\ndef md5(", start)
    namespace = {}
    exec(source[start:end], namespace)
    canonical = namespace["canonical_text_bytes"]
    lf = b"native definition\nsecond line\n"
    crlf = lf.replace(b"\n", b"\r\n")
    assert hashlib.sha256(lf).digest() != hashlib.sha256(crlf).digest()
    assert hashlib.sha256(canonical(lf)).digest() == hashlib.sha256(canonical(crlf)).digest()


def test_rr_presence_engine_entrypoints_match_binary_contract(rr_rom_path):
    rom = rr_rom_path.read_bytes()
    assert hashlib.md5(rom).hexdigest() == "8529f3a45d32bce4da637976fcf269d4"
    # Verified whole-call-chain landmarks, not an inference from a sane prologue alone.
    expected = {
        0x0805E7F4: "70b582b0051c",   # template-taking wrapper saves r0 template
        0x0805E752: "4878c9780906090c0843",  # template lower+upper graphics bytes
        0x0908FA18: "107051801806000e10bd",  # AddPalRef writes type/tag; returns slot
        0x0908F96E: "5a7801325a707047",      # refcount increment
        0x0908FB42: "4378002b01d0013b4370",  # guarded refcount decrement
        0x090425A0: "687900094df0cafa",      # DestroySprite consumes current palette slot
        0x0909001A: "0138032804d8",          # type >4 takes classifier default (type6 accepted)
    }
    for address, hex_bytes in expected.items():
        raw = bytes.fromhex(hex_bytes)
        offset = address - 0x08000000
        assert rom[offset:offset + len(raw)] == raw, hex(address)
    assert struct.unpack_from("<I", rom, 0x0908FB58 - 0x08000000)[0] == 0x0203B7D4


def test_ups_roundtrip_matches_exact_pinned_input(native_output, rr_repo, rr_rom_path):
    spec = importlib.util.spec_from_file_location("rr_native_make_ups", rr_repo / "patch/tools/make_ups.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    clean = rr_rom_path.read_bytes()
    assert hashlib.md5(clean).hexdigest() == "8529f3a45d32bce4da637976fcf269d4"
    patched = module.ups_apply(clean, (native_output / "SLink-RR.ups").read_bytes())
    assert patched == (native_output / "slink_RR.gba").read_bytes()


@pytest.mark.parametrize("declaration", ["int forbidden = 1;", "int forbidden;", "int forbidden __attribute__((common));"])
def test_linker_rejects_implicit_mutable_storage(rr_repo, tmp_path, declaration):
    raw = os.environ.get("SLINK_ARMGCC")
    if not raw:
        pytest.fail("set SLINK_ARMGCC to the pinned native toolchain", pytrace=False)
    toolchain = Path(raw)
    suffix = ".exe" if os.name == "nt" else ""
    source, obj, elf = (tmp_path / name for name in ("forbidden.c", "forbidden.o", "forbidden.elf"))
    source.write_text('void __attribute__((section(".text.entry"))) slink_hook(void) {}\n' + declaration)
    compile_result = subprocess.run([str(toolchain / ("arm-none-eabi-gcc" + suffix)), "-mthumb", "-mcpu=arm7tdmi",
                                     "-ffreestanding", "-c", str(source), "-o", str(obj)], capture_output=True, text=True)
    assert compile_result.returncode == 0, compile_result.stderr
    linked = subprocess.run([str(toolchain / ("arm-none-eabi-ld" + suffix)), "-T", str(rr_repo / "patch/src/slink.ld"),
                             str(obj), "-o", str(elf)], capture_output=True, text=True)
    assert linked.returncode != 0
    assert "forbidden" in linked.stderr
