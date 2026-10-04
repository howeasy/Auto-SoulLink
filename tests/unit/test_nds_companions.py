"""Composer contract: real shared editor/ISA/pins, synthetic and read-only retail inputs."""
from __future__ import annotations

import gc
import json
import os
import struct
from dataclasses import replace
from pathlib import Path

import pytest
from ndspy import codeCompression, rom

from tests.unit.test_nds_image import synthetic
from tools import nds_companions as composer, nds_image, nds_isa, nds_pins


def container_pin(image, name="arm9", compressed=True):
    if name in ("itcm", "dtcm"):
        decoded = image.autoload_block(name, arm9_compressed=compressed)
        return nds_pins.ContainerPin(name, nds_image.digest(decoded), nds_image.digest(decoded), None,
                                     decoded.ram_address, len(decoded), False)
    decoded = image.decoded(name, arm9_compressed=compressed)
    ov = image.overlays.get(name)
    return nds_pins.ContainerPin(name, nds_image.digest(image.read(name)), nds_image.digest(decoded),
                                 ov.file_id if ov else None, ov.ram_base if ov else image.arm9_ram_base,
                                 len(decoded), ov.compressed if ov else compressed)


def seal(manifest, blobs=None):
    blobs = {} if blobs is None else blobs
    manifest = composer.load_manifest(manifest)
    artifact = composer.distribution_artifact(manifest, blobs)
    distribution = replace(manifest.pins.distribution, artifact_sha256=nds_image.digest(artifact))
    return replace(manifest, pins=replace(manifest.pins, distribution=distribution))


def manifest_for(base, output, sites, ops, *, compressed=True, blobs=None, containers=None, reserved=()):
    blobs = {} if blobs is None else blobs
    pins = nds_pins.CompanionPin(
        schema_version=1, title="synthetic", source_kind="byte_patched",
        parent=nds_pins.ParentPin.of(base), source_build=None, output_arm9_compressed=compressed,
        arm9_ram_base=base.arm9_ram_base, containers=containers or (container_pin(output, compressed=compressed),),
        sites=tuple(sites), no_touch_spans=(), dsi_preserved=True, output=nds_pins.Hashes.of(output),
        distribution=nds_pins.Distribution("custom", "0" * 64, nds_image.digest(base.data, "sha1"),
                                           nds_image.digest(output.data, "sha1"), False),
        generator_hashes=(nds_pins.NamedHash("generator", "1" * 64),),
        source_hashes=(nds_pins.NamedHash("source", "2" * 64),), native_abi=3, capabilities=0)
    data = {"schema_version": 1, "pins": json.loads(pins.to_json()), "base_arm9_compressed": compressed,
            "operations": ops, "payloads": [{"name": k, "size": len(v), "sha256": nds_image.digest(v)}
                                            for k, v in blobs.items()], "reserved_sites": list(reserved)}
    return seal(data, blobs)


def fixture(*, isa="thumb", compressed=True, dsi=True, kind="detour", arm9_slack=512, unsafe_literal=False):
    seed = nds_image.NdsImage.load(synthetic(compressed=compressed, dsi=dsi, arm9_slack=arm9_slack))
    decoded = seed.decoded("arm9", arm9_compressed=compressed)
    old = bytes.fromhex("c046") * 4 if isa == "thumb" else bytes.fromhex("0000a0e1") * 2
    start = seed.arm9_ram_base + 0x4400
    if unsafe_literal:
        old = nds_isa.thumb_ldr_literal(start, 0, start + 32) + old[2:]
    seed.edit_arm9(start, decoded[0x4400:0x4408], old, arm9_compressed=compressed,
                   arm9_ram_base=seed.arm9_ram_base, reason="synthetic instructions")
    base = nds_image.NdsImage.load(seed.apply()[0])
    if kind == "identity":
        site = nds_pins.SitePin("site", "arm9", isa, old.hex(), old.hex(), start + 8, "FILE", address=start)
        return base, base.data, manifest_for(base, base, [site], [{"site": "site", "kind": "identity"}], compressed=compressed)
    replay = start + 0x100
    encode = nds_isa.thumb_detour if isa == "thumb" else nds_isa.arm_detour
    branch = encode(start, nds_isa.code_pointer(isa, replay), "veneer")
    # Independent fixed PI vector: these MOV no-ops replay verbatim.
    trampoline = old + encode(replay + 8, nds_isa.code_pointer(isa, start + 8), "veneer")
    before_replay = base.decoded("arm9", arm9_compressed=compressed)[0x4500:0x4510]
    sites = [nds_pins.SitePin("entry", "arm9", isa, old.hex(), branch.hex(), start + 8, "FILE", address=start),
             nds_pins.SitePin("replay", "arm9", isa, before_replay.hex(), trampoline.hex(), start + 8, "FILE", address=replay)]
    editor = nds_image.NdsImage.load(base.data)
    editor.edit_arm9(start, old, branch, arm9_compressed=compressed, arm9_ram_base=base.arm9_ram_base, reason="reference entry")
    editor.edit_arm9(replay, before_replay, trampoline, arm9_compressed=compressed,
                     arm9_ram_base=base.arm9_ram_base, reason="reference replay")
    output = nds_image.NdsImage.load(editor.apply()[0])
    ops = [{"site": "entry", "kind": "detour", "target": nds_isa.code_pointer(isa, replay), "form": "veneer"},
           {"site": "replay", "kind": "replay", "replay_of": "entry", "form": "veneer"}]
    return base, output.data, manifest_for(base, output, sites, ops, compressed=compressed)


@pytest.mark.parametrize("isa,compressed", [("thumb", True), ("arm", True), ("thumb", False), ("arm", False)])
def test_compose_real_detour_replay_and_roundtrip_receipt(isa, compressed):
    base, expected, manifest = fixture(isa=isa, compressed=compressed)
    output, spans, receipt = composer.compose(base.data, manifest, {})
    assert output == expected and spans
    assert composer.check(output, json.loads(json.dumps(receipt.to_dict())), base.data)
    assert receipt.determinism_verified and receipt.distribution_verified
    assert composer.compose(base.data, manifest, {}) == (output, spans, receipt)
    with nds_image.NdsImage.load(output) as after:
        for name in ("arm7", "fnt", "banner", "dsi_arm9i", "dsi_arm7i", "file:3"):
            assert base.read(name) == after.read(name)


@pytest.mark.parametrize("isa", ["thumb", "arm"])
def test_non_dsi_profile_composes_and_checks(isa):
    # HG/SS-style unit code 0: no DSi payload containers at all.
    base, expected, manifest = fixture(isa=isa, dsi=False)
    assert base.unit_code == 0 and not any(name.startswith("dsi_") for name in base.containers)
    output, spans, receipt = composer.compose(base.data, manifest, {})
    assert output == expected and spans
    assert composer.check(output, json.loads(json.dumps(receipt.to_dict())), base.data)
    for offset in (0x210, 0x1CC, 0x1DC):
        assert base.data[offset:offset + 4] == output[offset:offset + 4]
    with nds_image.NdsImage.load(output) as after:
        assert after.unit_code == 0 and not any(name.startswith("dsi_") for name in after.containers)
    assert composer.compose(base.data, manifest, {}) == (output, spans, receipt)


def test_check_refuses_emptied_changed_spans():
    base, _, manifest = fixture()
    output, spans, receipt = composer.compose(base.data, manifest, {})
    assert spans
    emptied = receipt.to_dict() | {"changed_spans": []}
    with pytest.raises(composer.ComposeError, match="undeclared difference"):
        composer.check(output, emptied, base.data)


def test_cond_on_thumb_non_bcond_detour_is_rejected():
    _, _, manifest = fixture()
    data = manifest.to_dict()
    data["operations"] = [dict(op) for op in data["operations"]]
    data["operations"][0]["cond"] = "eq"
    with pytest.raises(composer.ComposeError, match="operation:condition"):
        composer.load_manifest(data)
    data["operations"][0]["cond"] = "al"
    assert composer.load_manifest(data)


def test_unknown_base_and_mutated_site_are_refused():
    base, _, manifest = fixture(compressed=False)
    offset = base.extent("arm9").offset + 0x4400
    wrong = bytearray(base.data)
    wrong[offset] ^= 1
    with pytest.raises(composer.ComposeError, match="base:not_pinned"):
        composer.compose(bytes(wrong), manifest, {})
    # Even rebinding all parent hashes cannot turn a mismatched site into approval.
    wrong_image = nds_image.NdsImage.load(bytes(wrong))
    pin = replace(manifest.pins, parent=nds_pins.ParentPin.of(wrong_image),
                  distribution=replace(manifest.pins.distribution, input_sha1=nds_image.digest(wrong, "sha1")))
    rebound = seal(replace(manifest, pins=pin))
    with pytest.raises(composer.ComposeError, match="site:before"):
        composer.compose(bytes(wrong), rebound, {})


def test_reserved_sites_block_entire_detour_window():
    base, _, manifest = fixture()
    at = manifest.pins.sites[0].address
    for reserved in (at, at + 2):
        blocked = seal(replace(manifest, reserved_sites=(reserved,)))
        with pytest.raises(composer.ComposeError, match="site:reserved"):
            composer.compose(base.data, blocked, {})


def test_hge_reserved_main_call_address_is_respected():
    base, _, manifest = fixture(compressed=False, kind="identity")
    # A raw synthetic ARM9 based at zero covers this illustrative game address.
    raw = bytearray(base.data)
    struct.pack_into("<I", raw, 0x28, 0x02000000)
    at = base.extent("arm9").offset + 0xCD0
    raw[at:at + 8] = bytes.fromhex("c046") * 4
    struct.pack_into("<H", raw, 0x15E, nds_image._crc16(raw[:0x15E]))
    image = nds_image.NdsImage.load(bytes(raw))
    site = nds_pins.SitePin("main", "arm9", "thumb", raw[at:at + 8].hex(), raw[at:at + 8].hex(),
                            0x02000CD8, "FILE", address=0x02000CD0)
    spec = manifest_for(image, image, [site], [{"site": "main", "kind": "identity"}],
                        compressed=False, reserved=(0x02000CD0,))
    with pytest.raises(composer.ComposeError, match="site:reserved"):
        composer.compose(image.data, spec, {})


def test_raw_flag_skips_blz_and_mismatched_declarations_refuse(monkeypatch):
    base, expected, manifest = fixture(compressed=False)
    def forbidden(*args, **kwargs):
        pytest.fail("raw ARM9 went through BLZ")
    monkeypatch.setattr(codeCompression, "compress", forbidden)
    monkeypatch.setattr(codeCompression, "decompress", forbidden)
    assert composer.compose(base.data, manifest, {})[0] == expected
    mismatch = seal(replace(manifest, base_arm9_compressed=True))
    with pytest.raises(composer.ComposeError, match="compression:mismatch"):
        composer.compose(base.data, mismatch, {})


def test_source_built_is_never_byte_patched():
    base, _, manifest = fixture(kind="identity")
    build = nds_pins.SourceBuild("source", "a" * 40, "compiler", "b" * 64,
                                 nds_image.digest(base.data, "sha1"), nds_pins.PatchSet("c" * 40, "d" * 64),
                                 base_arm9_compressed=True, vanilla_reproduction_waived="synthetic")
    pins = replace(manifest.pins, source_kind="source_built", parent=None, source_build=build, distribution=None)
    with pytest.raises(composer.ComposeError, match="source_built:refused"):
        composer.compose(base.data, replace(manifest, pins=pins), {})


def test_no_touch_overlapping_compressed_edit_fails_check_and_compose():
    base, output, manifest = fixture()
    _, _, receipt = composer.compose(base.data, manifest, {})
    at = base.extent("arm9").offset
    no_touch = nds_pins.NoTouchSpan(at, 4, nds_image.digest(base.data, start=at, length=4))
    blocked = seal(replace(manifest, pins=replace(manifest.pins, no_touch_spans=(no_touch,))))
    with pytest.raises(composer.ComposeError, match="no-touch"):
        composer.compose(base.data, blocked, {})
    blocked_receipt = replace(receipt, manifest=blocked, artifact=composer.distribution_artifact(blocked, {}))
    with pytest.raises(composer.ComposeError, match="no-touch"):
        composer.check(output, blocked_receipt, base.data)
    with pytest.raises(composer.ComposeError, match="base:required"):
        composer.check(output, blocked_receipt, None)


def test_declared_compressed_input_must_actually_decode():
    base, _, manifest = fixture(compressed=False, kind="identity")
    pins = replace(manifest.pins, output_arm9_compressed=True,
                   containers=(replace(manifest.pins.containers[0], compressed=True),))
    bad = seal(replace(manifest, pins=pins, base_arm9_compressed=True))
    with pytest.raises(composer.ComposeError, match="compression:mismatch"):
        composer.compose(base.data, bad, {})


@pytest.mark.parametrize("field", [0x15E, 0x80, 0x210, 0x1CC, 0x1DC])
def test_header_invariants_are_rechecked(field):
    base, _, manifest = fixture(kind="identity")
    output, _, receipt = composer.compose(base.data, manifest, {})
    damaged = bytearray(output)
    damaged[field] ^= 1
    if field < 0x15E:
        struct.pack_into("<H", damaged, 0x15E, nds_image._crc16(damaged[:0x15E]))
    with pytest.raises(composer.ComposeError):
        composer.check(bytes(damaged), receipt, base.data)


def test_dsi_payload_and_undeclared_byte_refuse_check():
    base, _, manifest = fixture(kind="identity")
    output, _, receipt = composer.compose(base.data, manifest, {})
    for name in ("dsi_arm9i", "dsi_arm7i", "file:3"):
        damaged = bytearray(output)
        damaged[base.extent(name).offset] ^= 1
        with pytest.raises(composer.ComposeError, match="dsi:payload|undeclared difference"):
            composer.check(bytes(damaged), receipt, base.data)


def test_replay_refusal_cannot_be_bypassed_by_identity_noop():
    base, _, manifest = fixture(compressed=False, kind="identity")
    # Thumb ADD r0,PC reads PC through a register: not a relocatable PI assertion.
    at = base.extent("arm9").offset + 0x4400
    raw = bytearray(base.data)
    bad = bytes.fromhex("7844") + bytes.fromhex("c046") * 3
    raw[at:at + 8] = bad
    image = nds_image.NdsImage.load(bytes(raw))
    site = replace(manifest.pins.sites[0], expected_before=bad.hex(), after=bad.hex())
    spec = manifest_for(image, image, [site], [{"site": site.id, "kind": "identity"}], compressed=False)
    with pytest.raises(composer.ComposeError, match="isa:replay"):
        composer.compose(image.data, spec, {})


def test_nondeterministic_second_output_is_refused(monkeypatch):
    base, _, manifest = fixture(kind="identity")
    original = nds_image.NdsImage.apply
    calls = 0
    def changed(self, *args, **kwargs):
        nonlocal calls
        calls += 1
        output, spans = original(self, *args, **kwargs)
        if calls == 2:
            output = output[:-1] + bytes([output[-1] ^ 1])
        return output, spans
    monkeypatch.setattr(nds_image.NdsImage, "apply", changed)
    with pytest.raises(composer.ComposeError, match="determinism:mismatch"):
        composer.compose(base.data, manifest, {})


def test_manifest_and_payload_pins_are_strict(tmp_path):
    base, _, manifest = fixture(kind="identity")
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest.to_dict()), encoding="utf-8")
    assert composer.load_manifest(path) == manifest
    for change in ({"extra": 1}, {"schema_version": True}, {"reserved_sites": [True]}):
        with pytest.raises(composer.ComposeError):
            composer.load_manifest(manifest.to_dict() | change)
    with pytest.raises(composer.ComposeError, match="payload:keys"):
        composer.compose(base.data, manifest, {"undeclared": b"x"})
    with pytest.raises(composer.ComposeError, match="distribution:hash"):
        bad = replace(manifest, pins=replace(manifest.pins,
                      distribution=replace(manifest.pins.distribution, artifact_sha256="f" * 64)))
        composer.compose(base.data, bad, {})


def test_replay_uses_base_bytes_and_its_own_pinned_destination(monkeypatch):
    base, _, manifest = fixture()
    original = composer._replay
    def wrong_displacement(displaced, old, new, isa):
        if old != new:
            displaced = bytes.fromhex("0046") + displaced[2:]
        return original(displaced, old, new, isa)
    monkeypatch.setattr(composer, "_replay", wrong_displacement)
    with pytest.raises(composer.ComposeError, match="site:after_plan"):
        composer.compose(base.data, manifest, {})


def test_detour_after_must_decode_in_its_declared_mode():
    base, _, manifest = fixture()
    entry, replay = manifest.pins.sites
    wrong_mode = nds_isa.arm_detour(entry.address, manifest.operations[0].target, "veneer")
    try:
        pins = replace(manifest.pins, sites=(replace(entry, after=wrong_mode.hex()), replay))
        bad = seal(replace(manifest, pins=pins))
        composer.compose(base.data, bad, {})
    except (composer.ComposeError, nds_pins.PinError) as exc:
        assert any(word in str(exc) for word in ("mode", "isa", "decode", "not a thumb instruction"))
    else:
        pytest.fail("ARM detour admitted as Thumb")


def test_continuation_matches_exact_displaced_length():
    base, _, manifest = fixture()
    entry, replay = manifest.pins.sites
    pins = replace(manifest.pins, sites=(replace(entry, continuation=entry.continuation + 2), replay))
    bad = seal(replace(manifest, pins=pins))
    with pytest.raises(composer.ComposeError, match="isa:continuation"):
        composer.compose(base.data, bad, {})


def test_growth_over_actual_ff_slack_is_refused():
    base, expected, manifest = fixture()
    old_size = base.extent("arm9").length
    assert nds_image.NdsImage.load(expected).extent("arm9").length > old_size
    blocked = bytearray(base.data)
    blocked[base.extent("arm9").end] = 0x42
    blocked = nds_image.NdsImage.load(bytes(blocked))
    pin = replace(manifest.pins, parent=nds_pins.ParentPin.of(blocked),
                  distribution=replace(manifest.pins.distribution, input_sha1=nds_image.digest(blocked.data, "sha1")))
    spec = seal(replace(manifest, pins=pin))
    assert blocked.slack("arm9") == 0
    with pytest.raises(composer.ComposeError, match="image:growth"):
        composer.compose(blocked.data, spec, {})


def test_payload_into_autoload_data_uses_the_shared_accessor():
    base = nds_image.NdsImage.load(synthetic(autoloads=16))
    block = base.autoload_block("itcm", arm9_compressed=True)
    blob = bytes.fromhex("c046") * 4
    editor = nds_image.NdsImage.load(base.data)
    editor.edit_arm9(base.arm9_ram_base + block.offset, bytes(block[:8]), blob, arm9_compressed=True,
                     arm9_ram_base=base.arm9_ram_base, reason="reference ITCM payload")
    output = nds_image.NdsImage.load(editor.apply()[0])
    site = nds_pins.SitePin("itcm-payload", "itcm", "thumb", block[:8].hex(), blob.hex(),
                            block.ram_address + 8, "FILE", address=block.ram_address)
    blobs = {"code": blob}
    spec = manifest_for(base, output, [site], [{"site": site.id, "kind": "payload", "payload": "code"}],
                        blobs=blobs, containers=(container_pin(output), container_pin(output, "itcm")))
    assert composer.compose(base.data, spec, blobs)[0] == output.data
    with pytest.raises(composer.ComposeError, match="payload:hash"):
        composer.compose(base.data, spec, {"code": blob[:-1] + b"\0"})


def require_refusal(base, spec, reason):
    try:
        composer.compose(base.data, spec, {})
    except composer.ComposeError as exc:
        assert exc.reason == reason
        return
    raise AssertionError(f"missing refusal {reason}")


def test_reserved_guard_is_load_bearing(monkeypatch):
    base, _, manifest = fixture()
    spec = seal(replace(manifest, reserved_sites=(manifest.pins.sites[0].address,)))
    require_refusal(base, spec, "site:reserved")
    monkeypatch.setattr(composer, "_reserved", lambda *args: None)
    with pytest.raises(AssertionError, match="missing refusal site:reserved"):
        require_refusal(base, spec, "site:reserved")


def test_replay_guard_is_load_bearing(monkeypatch):
    base, _, manifest = fixture(unsafe_literal=True)
    require_refusal(base, manifest, "isa:replay")
    monkeypatch.setattr(composer, "_replay", lambda displaced, *args: displaced)
    with pytest.raises(AssertionError, match="missing refusal isa:replay"):
        require_refusal(base, manifest, "isa:replay")


@pytest.mark.parametrize("title,sha1,slack", [
    ("Black", "e51e6dfb8678a3d19dcd2a10691b96a569ca0abb", 348),
    ("White", "b5d7490be7b415b8f1e672a53e978a9cc667e56a", 308),
])
def test_retail_eight_byte_identity_detour_window_and_ndspy_counterexample(title, sha1, slack):
    root = Path(os.environ.get("SLINK_NDS_ROMS", "E:/Google Drive/SLink"))
    path = root / f"Pokemon - {title} Version 2 (USA, Europe) (NDSi Enhanced).nds"
    if not path.is_file():
        pytest.skip(f"NDS_COMPANION_RETAIL_ABSENT: {path.name}; set SLINK_NDS_ROMS")
    with nds_image.NdsImage.load(path) as base:
        assert nds_image.digest(base.data, "sha1") == sha1, "NDS_COMPANION_RETAIL_WRONG_HASH"
        decoded = base.decoded("arm9", arm9_compressed=True)
        # C2D6 cuts the next BL at +6. C2D4 covers MOV / complete BL / MOV.
        address = 0x0200C2D4
        before = decoded[address - base.arm9_ram_base:address - base.arm9_ram_base + 8]
        site = nds_pins.SitePin("identity-window", "arm9", "thumb", before.hex(), before.hex(),
                                address + 8, "FILE", address=address, evidence_ref="read-only ROM bytes near C2D6")
        spec = manifest_for(base, base, [site], [{"site": site.id, "kind": "identity"}])
        output, spans, receipt = composer.compose(path, spec, {})
        assert nds_image.digest(output, "sha1") == sha1 and spans == ()
        assert composer.check(output, receipt, path)
        assert len(codeCompression.compress(decoded, isArm9=True)) <= base.extent("arm9").length + slack
        assert base.slack("arm9") == slack
        # ndspy is used only to READ and independently compare every FAT payload.
        before_rom = rom.NintendoDSRom.fromFile(path)
        file_hashes = [nds_image.digest(blob) for blob in before_rom.files]
        repacked = before_rom.save()  # intentional in-memory negative control; never saved to disk
        del before_rom
        gc.collect()
        assert len(repacked) < len(base.data) and repacked[0x12] == 2
        assert all(base.extent(name).end > len(repacked) for name in ("dsi_arm9i", "dsi_arm7i"))
        with pytest.raises(composer.ComposeError):
            composer.check(repacked, receipt, path)
        del repacked
        after_rom = rom.NintendoDSRom(output)
        assert [nds_image.digest(blob) for blob in after_rom.files] == file_hashes
        del after_rom, output
        gc.collect()
        split = decoded[0xC2D6 - 0x4000:0xC2D6 - 0x4000 + 8]
        assert not nds_isa.plan_replay(split, 0x0200C2D6, 0x0200C2D6, "thumb").ok
        # The same control through the composer: an identity pinned at the BL-cutting address refuses.
        cut = nds_pins.SitePin("identity-cut", "arm9", "thumb", split.hex(), split.hex(), 0x0200C2DE, "FILE",
                               address=0x0200C2D6, evidence_ref="read-only ROM bytes near C2D6")
        cut_spec = manifest_for(base, base, [cut], [{"site": cut.id, "kind": "identity"}])
        with pytest.raises(composer.ComposeError) as refused:
            composer.compose(path, cut_spec, {})
        assert refused.value.reason == "isa:replay"
