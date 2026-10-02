"""Synthetic geometry/edit controls plus optional, read-only retail measurements."""
import gc
import os
import random
import struct
from pathlib import Path

import pytest
from ndspy import codeCompression as blz

import tools.nds_image as nds_image
from tools.nds_image import (
    ChangedSpan,
    ImageError,
    NdsImage,
    _crc16,
    digest,
    verify_only_declared_changes,
)


def synthetic(*, compressed=True, dsi=True, arm9_slack=512, overlay_slack=128,
              module_params=True, autoloads=None, arm9_noise=False):
    """Build all bytes in memory: real header fields, FNT/FAT, y9/y7 and BLZ.

    module_params=False omits the NitroSDK magic; autoloads=12|16 adds an ITCM+DTCM autoload
    table of that entry width; arm9_noise makes the compressed tail incompressible so a later
    edit can shrink the encoded ARM9.
    """
    ram = 0x02004000
    arm9 = bytearray(bytes(range(256)) * 72)  # 0x4800 bytes
    if arm9_noise:
        arm9[0x4000:0x4400] = random.Random(7).randbytes(0x400)
    magic = 0x1000
    end = ram + len(arm9)
    list_start = list_end = auto = end
    if autoloads:
        auto = ram + 0x4600
        list_start = ram + 0x4660
        list_end = list_start + 2 * autoloads
        rows = ((0x01FF8000, 0x40, 0x01FF8000, 0), (0x02FE0000, 0x20, 0x02FE0000, 0x10))
        for i, row in enumerate(rows):
            fields = row[:2] + ((row[2],) if autoloads == 16 else ()) + (row[3],)
            struct.pack_into(f"<{autoloads // 4}I", arm9, 0x4660 + i * autoloads, *fields)
        arm9[0x4600:0x4640] = b"I" * 0x40
        arm9[0x4640:0x4660] = b"D" * 0x20
    struct.pack_into("<7I", arm9, magic - 28, list_start, list_end,
                     auto, end, end + 128, 0, 0x0503757C)
    if module_params:
        struct.pack_into("<II", arm9, magic, 0xDEC00621, 0x2106C0DE)
    if compressed:
        encoded = blz.compress(bytes(arm9), isArm9=True)
        struct.pack_into("<I", arm9, magic - 8, ram + len(encoded))
        encoded = blz.compress(bytes(arm9), isArm9=True)
    else:
        encoded = bytes(arm9)
    data = bytearray(b"\xff" * 0x4000)
    data[:0x400] = b"\0" * 0x400
    data[:12] = b"SYNTHETICNDS"
    data[0x0C:0x10] = b"TEST"
    data[0x12] = 2 if dsi else 0

    def put(blob, padding=0):
        start = len(data)
        data.extend(blob)
        data.extend(b"\xff" * padding)
        return start

    def pair(off, start, size):
        struct.pack_into("<II", data, off, start, size)

    a9 = put(encoded, arm9_slack)
    struct.pack_into("<4I", data, 0x20, a9, ram + 0x800, ram, len(encoded))
    y9 = put(b"\0" * 64)
    y7 = put(b"\0" * 32)
    a7 = put(b"ARM7" * 32)
    struct.pack_into("<4I", data, 0x30, a7, 0x02380000, 0x02380000, 128)
    fnt_data = struct.pack("<IHH", 8, 0, 1) + b"\x03ov0\x03ov1\x03ov7\x04data\0"
    fnt = put(fnt_data)
    fat = put(b"\0" * 32)
    banner = put(b"\x01\0" + b"\0" * (0x840 - 2))
    struct.pack_into("<I", data, 0x68, banner)
    ov0 = bytes(range(64)) * 8
    ov0raw = blz.compress(ov0)
    files = []
    for content, padding in ((ov0raw, overlay_slack), (b"RAW!" * 32, 16),
                             (b"SEVEN" * 16, 16), (b"file-data-kept", 0)):
        start = put(content, padding)
        files.append((start, start + len(content)))
    for i, (start, end) in enumerate(files):
        struct.pack_into("<II", data, fat + 8 * i, start, end)
    struct.pack_into("<8I", data, y9, 0, 0x02150000, len(ov0), 32, 0, 0, 0,
                     0x03000000 | len(ov0raw))
    struct.pack_into("<8I", data, y9 + 32, 1, 0x02150000, 128, 0, 0, 0, 1, 0x02000000)
    struct.pack_into("<8I", data, y7, 0, 0x02390000, 80, 0, 0, 0, 2, 0)
    pair(0x40, fnt, len(fnt_data))
    pair(0x48, fat, 32)
    pair(0x50, y9, 64)
    pair(0x58, y7, 32)
    struct.pack_into("<II", data, 0x80, len(data), 0x4000)
    put(b"OPAQUE-NON-FAT-DATA", 128)
    if dsi:
        for off, szoff, payload in ((0x1C0, 0x1CC, b"9i" * 32),
                                     (0x1D0, 0x1DC, b"7i" * 16),
                                     (0x1F0, 0x1F4, b"SECT" * 16),
                                     (0x1F8, 0x1FC, b"HASH" * 8)):
            start = put(payload)
            struct.pack_into("<I", data, off, start)
            struct.pack_into("<I", data, szoff, len(payload))
        struct.pack_into("<I", data, 0x210, len(data))
    put(b"", 512)
    # Independent header CRC implementation for the fixture.
    crc = 0xFFFF
    for byte in data[:0x15E]:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ (0xA001 if crc & 1 else 0)
    struct.pack_into("<H", data, 0x15E, crc)
    return bytes(data)


@pytest.mark.parametrize("compressed,dsi", [(False, False), (True, False), (True, True)])
def test_every_byte_has_one_extent_and_noop_is_exact(compressed, dsi):
    raw = synthetic(compressed=compressed, dsi=dsi)
    image = NdsImage.load(raw)
    end = 0
    for e in image.extents:
        assert e.offset == end
        end = e.end
    assert end == len(raw)
    assert {"header", "header_reserved", "arm9", "arm7", "y9", "y7", "fat", "fnt", "banner",
            "overlay9:0", "overlay9:1", "overlay7:0", "file:3"} <= image.containers.keys()
    assert ("dsi_arm9i" in image.containers) is dsi
    assert any(e.kind == "unmapped" for e in image.extents)
    assert image.extents[-1].name == "trailing_ff"
    output, manifest = image.apply()
    assert output is raw
    assert manifest == ()
    assert verify_only_declared_changes(raw, output, manifest)


def test_edit_manifest_and_undeclared_difference():
    image = NdsImage.load(synthetic())
    image.edit(container="file:3", container_offset=5, expected_before=b"data", after=b"TEST", reason="fixture edit")
    output, manifest = image.apply()
    assert image.read("file:3") == b"file-data-kept"
    assert NdsImage.load(output).read("file:3") == b"file-TEST-kept"
    assert verify_only_declared_changes(image, output, [m.to_dict() for m in manifest])
    damaged = bytearray(output)
    damaged[image.extent("dsi_arm7i").offset] ^= 1
    with pytest.raises(ImageError, match="undeclared"):
        verify_only_declared_changes(image, damaged, manifest)
    bad = manifest[0].to_dict() | {"after_sha1": "0" * 40}
    with pytest.raises(ImageError, match="hash"):
        verify_only_declared_changes(image, output, [bad])
    with pytest.raises(ImageError, match="keys"):
        verify_only_declared_changes(image, output, [manifest[0].to_dict() | {"ignored": True}])
    with pytest.raises(ImageError, match="container"):
        verify_only_declared_changes(image, output, [manifest[0].to_dict() | {"container": "header"}])


def test_span_rejections():
    image = NdsImage.load(synthetic())
    with pytest.raises(ImageError, match="expected-before"):
        image.edit(container="file:3", expected_before=b"NOPE", after=b"TEST", reason="bad")
    image.edit(container="file:3", expected_before=b"file", after=b"EDIT", reason="good")
    with pytest.raises(ImageError, match="overlapping"):
        image.edit(container="file:3", expected_before=b"fi", after=b"xx", reason="overlap")
    with pytest.raises(ImageError, match="outside|boundary"):
        image.edit(offset=len(image.data) - 1, expected_before=b"\xff\xff", after=b"aa", reason="bounds")
    with pytest.raises(ImageError, match="same-size"):
        image.edit(container="file:3", expected_before=b"file", after=b"larger", reason="size")
    with pytest.raises(ImageError, match="outside named"):
        image.edit(container="file:3", container_offset=100, expected_before=b"x", after=b"y", reason="escape")


@pytest.mark.parametrize("compressed", [False, True])
def test_arm9_edit_and_managed_metadata(compressed):
    image = NdsImage.load(synthetic(compressed=compressed))
    original = image.decoded("arm9", arm9_compressed=compressed)
    offset = 0x4400
    image.edit_arm9(image.arm9_ram_base + offset, original[offset:offset + 8], b"PATCHED!",
                    arm9_compressed=compressed, arm9_ram_base=image.arm9_ram_base, reason="detour")
    output, manifest = image.apply()
    new = NdsImage.load(output)
    decoded = new.decoded("arm9", arm9_compressed=compressed)
    assert decoded[offset:offset + 8] == b"PATCHED!"
    assert new.read("dsi_arm9i") == image.read("dsi_arm9i")
    assert new.read("dsi_arm7i") == image.read("dsi_arm7i")
    if compressed:
        assert struct.unpack_from("<I", decoded, 0xFF8)[0] == new.arm9_ram_base + new.extent("arm9").length
    else:
        assert new.extent("arm9").length == image.extent("arm9").length
    assert verify_only_declared_changes(image, output, manifest)


def test_multiple_decoded_edits_recompress_once_and_conflicts_refuse():
    image = NdsImage.load(synthetic())
    raw = image.decoded("arm9", arm9_compressed=True)
    for offset in (0x4400, 0x4500):
        image.edit_arm9(image.arm9_ram_base + offset, raw[offset:offset + 4], b"test",
                        arm9_compressed=True, arm9_ram_base=image.arm9_ram_base, reason="site")
    with pytest.raises(ImageError, match="overlapping"):
        image.edit_arm9(image.arm9_ram_base + 0x4400, raw[0x4400:0x4404], b"xxxx",
                        arm9_compressed=True, arm9_ram_base=image.arm9_ram_base, reason="duplicate")
    with pytest.raises(ImageError, match="overlaps decoded"):
        image.edit(container="arm9", expected_before=image.read("arm9")[:4], after=b"ABCD", reason="mix")
    output, manifest = image.apply()
    assert sum(m.container == "arm9" for m in manifest) == 1
    assert verify_only_declared_changes(image, output, manifest)


def test_compression_overflow_and_wrong_configuration_refuse():
    image = NdsImage.load(synthetic(arm9_slack=0))
    raw = image.decoded("arm9", arm9_compressed=True)
    with pytest.raises(ImageError, match="configuration"):
        image.edit_arm9(image.arm9_ram_base, raw[:4], b"abcd", arm9_compressed=True,
                        arm9_ram_base=0x02000000, reason="wrong base")
    image.edit_arm9(image.arm9_ram_base + 0x4400, raw[0x4400:0x4408], b"PATCHED!",
                    arm9_compressed=True, arm9_ram_base=image.arm9_ram_base, reason="overflow")
    with pytest.raises(ImageError, match="growth"):
        image.apply()
    with pytest.raises(ImageError, match="explicit"):
        image.decoded("arm9")
    with pytest.raises(ImageError, match="compressed flag"):
        NdsImage.load(synthetic(compressed=False)).decoded("arm9", arm9_compressed=True)


@pytest.mark.parametrize("oid", [0, 1])
def test_overlay_edit_updates_only_declared_fields_and_disambiguates_alias(oid):
    image = NdsImage.load(synthetic())
    ov = image.overlays[f"overlay9:{oid}"]
    old = image.decoded(ov.name)
    image.edit_overlay(oid, ov.ram_base + 16, old[16:24], b"ABCDEFGH", reason="overlay detour")
    output, manifest = image.apply()
    new = NdsImage.load(output)
    assert new.decoded(ov.name)[16:24] == b"ABCDEFGH"
    assert new.read(f"overlay9:{1-oid}") == image.read(f"overlay9:{1-oid}")
    assert new.data[ov.entry_offset:ov.entry_offset + 28] == image.data[ov.entry_offset:ov.entry_offset + 28]
    assert verify_only_declared_changes(image, output, manifest)


def test_overlay_zero_slack_and_decoded_noop():
    image = NdsImage.load(synthetic(overlay_slack=0))
    ov = image.overlays["overlay9:0"]
    before = image.decoded(ov.name)
    image.edit_overlay(0, ov.ram_base, before[:8], b"UNIQUE!!", reason="growth")
    with pytest.raises(ImageError, match="growth"):
        image.apply()
    image = NdsImage.load(synthetic())
    data = image.decoded("arm9", arm9_compressed=True)
    image.edit_arm9(image.arm9_ram_base, data[:4], data[:4], arm9_compressed=True,
                    arm9_ram_base=image.arm9_ram_base, reason="no-op")
    assert image.apply() == (image.data, ())


@pytest.mark.parametrize("offset,value,match", [(0x20, 0x10, "overlapping"),
                                                   (0x4C, 7, "multiple"),
                                                   (0x54, 31, "multiple"),
                                                   (0x1C0, 0xFFFFFF00, "outside"),
                                                   (0x210, 0xFFFFFF00, "size")])
def test_bad_container_geometry_fails_closed(offset, value, match):
    raw = bytearray(synthetic())
    struct.pack_into("<I", raw, offset, value)
    with pytest.raises(ImageError, match=match):
        NdsImage.load(bytes(raw))


def _shrink_arm9(image):
    d = image.decoded("arm9", arm9_compressed=True)
    image.edit_arm9(image.arm9_ram_base + 0x4000, d[0x4000:0x4400], bytes(0x400),
                    arm9_compressed=True, arm9_ram_base=image.arm9_ram_base, reason="shrink")


def _partition_complete(image):
    end = 0
    for e in image.extents:
        assert e.offset == end
        end = e.end
    assert end == len(image.data)


def test_no_module_params_fails_closed_unless_opted_in():
    raw = synthetic(module_params=False, arm9_noise=True)
    image = NdsImage.load(raw)
    _shrink_arm9(image)
    with pytest.raises(ImageError, match="unmanaged ARM9 compressed_static_end"):
        image.apply()
    output, manifest = image.apply(arm9_lacks_module_params=True)
    new = NdsImage.load(output)
    assert struct.unpack_from("<I", output, 0x2C)[0] == new.extent("arm9").length < image.extent("arm9").length
    assert verify_only_declared_changes(image, output, manifest)
    # A same-length encoding needs no pointer, so absent params is not an error there.
    same = NdsImage.load(synthetic(module_params=False, compressed=False))
    same.edit_arm9(same.arm9_ram_base + 0x4400, bytes(range(8)), b"PATCHED!", arm9_compressed=False,
                   arm9_ram_base=same.arm9_ram_base, reason="raw")
    assert same.apply()[1]


def test_arm9_shrink_reload_partition_header_and_vacated_bytes():
    raw = synthetic(arm9_noise=True, autoloads=16)
    image = NdsImage.load(raw)
    old = image.extent("arm9")
    old_slack = image.slack("arm9")
    _shrink_arm9(image)
    output, manifest = image.apply()
    new = NdsImage.load(output)
    n = new.extent("arm9")
    assert n.length < old.length
    _partition_complete(new)
    assert struct.unpack_from("<I", output, 0x2C)[0] == n.length
    decoded = new.decoded("arm9", arm9_compressed=True)
    assert struct.unpack_from("<I", decoded, 0xFF8)[0] == new.arm9_ram_base + n.length
    assert struct.unpack_from("<H", output, 0x15E)[0] == _crc16(output[:0x15E])
    assert output[n.end:old.end] == raw[n.end:old.end]  # vacated bytes are untouched
    assert verify_only_declared_changes(image, output, manifest)
    # Vacated junk + the old FF slack is mixed, so it reparses as unmapped, NOT padding_ff,
    # and it no longer counts as slack (the first vacated byte is not FF).
    gap = next(e for e in new.extents if e.offset == n.end)
    assert gap.kind == "unmapped" and gap.end == old.end + old_slack
    assert new.slack("arm9") == 0
    for kind in ("itcm", "dtcm"):  # data AND info (ram, size, bss, decoded offset) survive the shrink
        assert new.autoload_block(kind) == image.autoload_block(kind)
        assert new.autoload_block(kind).as_tuple() == image.autoload_block(kind).as_tuple()


def test_overlay_shrink_reload_fat_y9_and_vacated_bytes():
    raw = synthetic()
    image = NdsImage.load(raw)
    ov = image.overlays["overlay9:0"]
    old = image.extent(ov.name)
    before = image.decoded(ov.name)
    image.edit_overlay(0, ov.ram_base, before[:512], bytes(512), reason="shrink")
    output, manifest = image.apply()
    new = NdsImage.load(output)
    n = new.extent(ov.name)
    assert n.length < old.length
    _partition_complete(new)
    assert new.fat[ov.file_id] == (n.offset, n.end)
    assert new.overlays[ov.name].flags == (ov.flags & 0xFF000000) | n.length
    assert output[n.end:old.end] == raw[n.end:old.end]
    assert next(e for e in new.extents if e.offset == n.end).kind == "unmapped"
    assert new.decoded(ov.name) == bytes(512)
    assert verify_only_declared_changes(image, output, manifest)


def test_zero_overlay_table_entries_are_skipped_and_aliased_fat_cannot_open():
    raw = bytearray(synthetic())
    y7 = NdsImage.load(bytes(raw)).extent("y7")
    raw[y7.offset:y7.end] = bytes(y7.length)
    image = NdsImage.load(bytes(raw))
    assert "overlay7:0" not in image.overlays and "file:2" in image.containers
    raw = bytearray(synthetic())
    fat = NdsImage.load(bytes(raw)).extent("fat")
    raw[fat.offset + 24:fat.offset + 32] = raw[fat.offset + 16:fat.offset + 24]  # alias file 3 to 2
    with pytest.raises(ImageError, match="overlapping"):
        NdsImage.load(bytes(raw))


def test_every_refusal_is_an_image_error(tmp_path):
    empty = tmp_path / "empty.nds"
    empty.write_bytes(b"")
    with pytest.raises(ImageError, match="empty"):
        NdsImage.load(empty)
    raw = bytearray(synthetic())
    raw[0x0C] = 0xE9
    with pytest.raises(ImageError, match="gamecode"):
        NdsImage.load(bytes(raw))
    path = tmp_path / "synthetic.nds"
    path.write_bytes(synthetic())
    with NdsImage.load(path) as image:
        pass
    with pytest.raises(ImageError, match="closed"):
        image.apply()
    with pytest.raises(ImageError, match="closed"):
        image.read("arm9")
    image = NdsImage.load(synthetic())
    for kwargs in ({"expected_before": None, "after": b"x"}, {"expected_before": b"x", "after": None}):
        with pytest.raises(ImageError, match="bytes"):
            image.edit(offset=0, reason="r", **kwargs)


def test_verifier_accepts_slack_growth_rows_but_the_editor_cannot_stage_them():
    raw = synthetic()
    image = NdsImage.load(raw)
    ext = image.extent("arm9")
    patched = bytearray(raw)
    patched[ext.end:ext.end + 6] = b"GROWTH"  # legitimate recompression growth lands in FF slack
    span = (ext.offset, ext.length + 6)
    row = {"offset": span[0], "length": span[1], "container": "arm9", "reason": "growth",
           "before_sha1": digest(raw, "sha1", *span), "after_sha1": digest(bytes(patched), "sha1", *span)}
    assert verify_only_declared_changes(image, bytes(patched), [row])
    with pytest.raises(ImageError, match="boundary"):
        image.edit(container="arm9", container_offset=ext.length - 2,
                   expected_before=raw[ext.end - 2:ext.end + 2], after=b"ABCD", reason="grow")


def test_blz_roundtrip_refusal_names_the_first_byte_normalization(monkeypatch):
    from ndspy import codeCompression
    image = NdsImage.load(synthetic(arm9_noise=True))
    _shrink_arm9(image)
    monkeypatch.setattr(codeCompression, "compress", lambda data, **kw: bytes(data))
    with pytest.raises(ImageError, match="first byte"):
        image.apply()


@pytest.mark.parametrize("width", [12, 16])
@pytest.mark.parametrize("compressed", [False, True])
def test_autoload_blocks_synthetic(width, compressed):
    image = NdsImage.load(synthetic(compressed=compressed, autoloads=width))
    for arm9_compressed in (compressed, None):  # None infers from compressed_static_end
        itcm = image.autoload_block("itcm", arm9_compressed=arm9_compressed)
        dtcm = image.autoload_block("dtcm", arm9_compressed=arm9_compressed)
        assert itcm.as_tuple() == (0x01FF8000, 0x40, 0, 0x4600) and bytes(itcm) == b"I" * 0x40
        assert dtcm.as_tuple() == (0x02FE0000, 0x20, 0x10, 0x4640) and bytes(dtcm) == b"D" * 0x20
        assert [b.index for b in image.autoload_blocks(arm9_compressed=arm9_compressed)] == [0, 1]
    # No table at all: absent kinds are None; no module params at all is an error.
    assert NdsImage.load(synthetic()).autoload_block("itcm") is None
    with pytest.raises(ImageError, match="module parameters"):
        NdsImage.load(synthetic(module_params=False)).autoload_block("itcm", arm9_compressed=True)
    with pytest.raises(ImageError, match="kind"):
        image.autoload_block("vram")
    with pytest.raises(ImageError, match="undecidable|tile"):
        image.autoload_blocks(arm9_compressed=compressed, entry_size=8)


def _bad_autoload(mutate, width=16):
    raw = bytearray(synthetic(compressed=False, autoloads=width))
    base = NdsImage.load(bytes(raw)).extent("arm9").offset + 0x4660
    mutate(raw, base)
    return NdsImage.load(bytes(raw))


@pytest.mark.parametrize("name,mutate,match", [
    ("zero ram", lambda r, b: struct.pack_into("<I", r, b, 0), "zero RAM"),
    ("zero size", lambda r, b: (struct.pack_into("<I", r, b + 4, 0), struct.pack_into("<I", r, b + 20, 0x60)),
     "zero RAM address or zero size"),
    ("third word != ram", lambda r, b: struct.pack_into("<I", r, b + 8, 1), "third word"),
])
def test_autoload_rows_refuse_malformed_16_byte_entries(name, mutate, match):
    image = _bad_autoload(mutate)
    with pytest.raises(ImageError, match=match):
        image.autoload_blocks(arm9_compressed=False)
    with pytest.raises(ImageError, match=match):
        image.autoload_blocks(arm9_compressed=False, entry_size=16)  # explicit width still refuses
    assert len(_bad_autoload(lambda r, b: None).autoload_blocks(arm9_compressed=False)) == 2  # control


def test_autoload_12_byte_rows_refuse_zero_ram_or_size():
    image = _bad_autoload(lambda r, b: struct.pack_into("<I", r, b, 0), width=12)
    with pytest.raises(ImageError, match="zero RAM"):
        image.autoload_blocks(arm9_compressed=False)


def test_header_crc16_cannot_be_edited_directly_and_verifier_checks_it():
    raw = synthetic()
    image = NdsImage.load(raw)
    for offset, n in ((0x15E, 2), (0x15C, 4), (0x15F, 1)):
        with pytest.raises(ImageError, match="CRC16"):
            image.edit(offset=offset, expected_before=raw[offset:offset + n], after=bytes(n), reason="crc")
    # The module's own recomputation is fine, and the verifier accepts that output.
    image.edit(container="header", container_offset=0x14, expected_before=b"\x00", after=b"\x01", reason="hdr")
    output, manifest = image.apply()
    assert {m.offset for m in manifest} == {0x14, 0x15E}
    assert verify_only_declared_changes(raw, output, manifest)
    # A header edit whose CRC was left stale (or wrong) is refused even though every byte is declared.
    stale = bytearray(raw)
    stale[0x14] = 1
    row = ChangedSpan(0x14, 1, "header", digest(raw, "sha1", 0x14, 1), digest(bytes(stale), "sha1", 0x14, 1), "hdr")
    with pytest.raises(ImageError, match="CRC16"):
        verify_only_declared_changes(raw, bytes(stale), [row])
    wrong = bytearray(output)
    wrong[0x15E] ^= 1
    crc = ChangedSpan(0x15E, 2, "header", digest(raw, "sha1", 0x15E, 2), digest(bytes(wrong), "sha1", 0x15E, 2), "crc")
    with pytest.raises(ImageError, match="CRC16"):
        verify_only_declared_changes(raw, bytes(wrong), [manifest[0], crc])


def test_verifier_accepts_bytes_like_and_paths_and_refuses_other_types(tmp_path):
    raw = synthetic()
    image = NdsImage.load(raw)
    image.edit(container="file:3", container_offset=5, expected_before=b"data", after=b"TEST", reason="e")
    output, manifest = image.apply()
    path = tmp_path / "orig.nds"
    path.write_bytes(raw)
    for original in (bytearray(raw), memoryview(raw), path, str(path)):
        assert verify_only_declared_changes(original, bytearray(output), manifest)
    mutable = bytearray(raw)
    assert verify_only_declared_changes(mutable, output, manifest)
    mutable[0] ^= 1  # still the caller's own mutable buffer, never copied or frozen by the verifier
    for bad in (None, 5, [1, 2]):
        with pytest.raises(ImageError, match="NdsImage, bytes-like"):
            verify_only_declared_changes(bad, output, manifest)
    with pytest.raises(TypeError, match="immutable bytes"):  # documented: load() is bytes/path only
        NdsImage.load(bytearray(raw))


RETAIL = [
    ("Black", "", "26ad0b9967aa279c4a266ee69f52b9b2332399a5", 0x6F898, 360),
    ("White", "", "bc696a0dfb448c7b3a8a206f0f8214411a039208", 0x6F8A4, 348),
    ("Black", " 2", "e51e6dfb8678a3d19dcd2a10691b96a569ca0abb", 0x736A4, 348),
    ("White", " 2", "b5d7490be7b415b8f1e672a53e978a9cc667e56a", 0x736CC, 308),
]


# One ROM-directory convention for every NDS retail test (test_nds_isa/test_nds_pkm45 use the same).
ROM_DIR = Path(os.environ.get("SLINK_NDS_ROMS") or "E:/Google Drive/SLink")


def _retail(title, suffix):
    path = ROM_DIR / f"Pokemon - {title} Version{suffix} (USA, Europe) (NDSi Enhanced).nds"
    if not path.is_file():
        pytest.skip(f"NDS_RETAIL_INPUT_ABSENT: {path.name}; set SLINK_NDS_ROMS")
    return path


@pytest.mark.parametrize("title,suffix,sha1,encoded_size,slack", RETAIL)
def test_retail_ndspy_counterexample_and_exact_noop(title, suffix, sha1, encoded_size, slack):
    from ndspy.rom import NintendoDSRom
    path = _retail(title, suffix)
    with NdsImage.load(path) as image:
        assert digest(image.data, "sha1") == sha1, "NDS_RETAIL_INPUT_WRONG_HASH"
        assert image.slack("arm9") == slack
        decoded = image.decoded("arm9", arm9_compressed=True)
        recompressed = blz.compress(decoded, isArm9=True)
        assert len(recompressed) == encoded_size == image.extent("arm9").length
        assert blz.decompress(recompressed) == decoded
        output, manifest = image.apply()
        assert digest(output, "sha1") == sha1
        assert verify_only_declared_changes(image, output, manifest)
        del output
        gc.collect()
        # Deliberately invoke the UNSAFE serializer in this counterexample only.
        # No saveToFile(), no output path, and release the model before proceeding.
        rom = NintendoDSRom.fromFile(path)
        repacked = rom.save()
        del rom
        assert len(repacked) < len(image.data)
        assert repacked[0x12] == image.unit_code == 2
        for name in ("dsi_arm9i", "dsi_arm7i"):
            ext = image.extent(name)
            assert ext.end > len(repacked)
        del repacked
        gc.collect()


# Measured on all four ROMs: (autoload_start, itcm data size) in the DECODED ARM9. The
# Gen 5 SDK table has 16-byte rows {ram, size, sdk word == ram, bss}; the rest is common.
AUTOLOADS = {
    ("Black", ""): (0xA5E80, 0x820), ("White", ""): (0xA5EA0, 0x820),
    ("Black", " 2"): (0x99740, 0x13A0), ("White", " 2"): (0x99780, 0x13A0),
}
MAGIC = bytes.fromhex("2106c0dedec00621")


@pytest.mark.parametrize("title,suffix,sha1,encoded_size,slack", RETAIL)
def test_retail_module_params_header_crc_and_autoloads(title, suffix, sha1, encoded_size, slack):
    with NdsImage.load(_retail(title, suffix)) as image:
        assert digest(image.data, "sha1") == sha1, "NDS_RETAIL_INPUT_WRONG_HASH"
        decoded = image.decoded("arm9", arm9_compressed=True)
        base = image.arm9_ram_base
        # The doubled magic occurs exactly once, at 0xFCC; the struct starts 0x1C before it.
        assert decoded.count(MAGIC) == 1 and decoded.find(MAGIC) == 0xFCC
        # MEASURED: the verbatim 16 KiB prefix carries no size fields; its first 3 words are the
        # secure-area filler, so compressed_static_end (module params) is the only size to maintain.
        assert struct.unpack_from("<3I", decoded, 0) == (0xE7FFDEFF,) * 3
        words = struct.unpack_from("<7I", decoded, 0xFCC - 0x1C)
        assert words[5] == base + encoded_size == base + image.extent("arm9").length
        assert words[6] == 0x0503757C  # SDK version word
        # Header CRC16 of the REAL header is the oracle; the wrong range / init must fail.
        stored = struct.unpack_from("<H", image.data, 0x15E)[0]
        assert _crc16(image.data[:0x15E]) == stored
        assert _crc16(image.data[:0x160]) != stored and _crc16(image.data[:0x15E], init=0) != stored
        auto_start, itcm_size = AUTOLOADS[(title, suffix)]
        assert [w - base for w in words[:3]] == [auto_start + itcm_size + 0xA0 + 0x20 + 0x20,
                                                 auto_start + itcm_size + 0xA0 + 0x20 + 0x20 + 0x40, auto_start]
        blocks = image.autoload_blocks(arm9_compressed=True)
        assert [b.as_tuple()[:3] for b in blocks] == [
            (0x01FF8000, itcm_size, 0), (0x02FE0000, 0xA0, 0x20), (0x02400000, 0x20, 0), (0x06898000, 0x20, 0)]
        assert [b.kind for b in blocks] == ["itcm", "dtcm", None, None]
        assert blocks[0].offset == auto_start and blocks[1].offset == auto_start + itcm_size
        assert image.autoload_block("itcm") == decoded[auto_start:auto_start + itcm_size]  # compression inferred
        assert image.autoload_block("dtcm").bss_size == 0x20


def _edit_site(image):
    decoded = image.decoded("arm9", arm9_compressed=True)
    offset = 0x20000  # ordinary ARM9 code, far from module params and autoloads
    before = decoded[offset:offset + 4]
    after = bytes(b ^ 0xFF for b in before)
    image.edit_arm9(image.arm9_ram_base + offset, before, after, arm9_compressed=True,
                    arm9_ram_base=image.arm9_ram_base, reason="retail edit-path control")
    return decoded, offset, after


def _mutated_module(tmp_path):
    """tools.nds_image with every isArm9 flag flipped, loaded from a temp copy."""
    import importlib.util
    import sys
    source = (Path(__file__).resolve().parents[2] / "tools" / "nds_image.py").read_text(encoding="utf-8")
    flipped = source.replace('isArm9=name == "arm9"', "isArm9=False").replace("isArm9=True", "isArm9=False")
    assert flipped.count("isArm9=False") >= 2 and "isArm9=True" not in flipped
    path = tmp_path / "nds_image_mut.py"
    path.write_text(flipped, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("nds_image_mut", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["nds_image_mut"] = module  # dataclasses resolve annotations through sys.modules
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop("nds_image_mut", None)
    return module


def _arm9_prefix_consistent(module, path):
    """True iff the staged ARM9 span keeps the first 0x4000 bytes uncompressed (BLZ for ARM9)."""
    with module.NdsImage.load(path) as image:
        decoded, offset, after = _edit_site(image)
        try:
            spans = image._encoded_spans()
        except module.ImageError:
            return False
        arm9 = next(s for s in spans if s[3] == "arm9")
        patched = bytearray(decoded)
        patched[offset:offset + 4] = after
        struct.pack_into("<I", patched, 0xFCC - 8, image.arm9_ram_base + len(arm9[2]))  # managed pointer
        return arm9[2][:0x4000] == bytes(patched[:0x4000])


@pytest.mark.parametrize("title,suffix,sha1,encoded_size,slack", RETAIL[:1] + RETAIL[2:3])
def test_retail_real_arm9_edit_path_is_self_consistent(monkeypatch, tmp_path, title, suffix, sha1,
                                                       encoded_size, slack):
    from ndspy import codeCompression
    path = _retail(title, suffix)
    calls = []
    real = codeCompression.compress
    monkeypatch.setattr(codeCompression, "compress",
                        lambda data, *a, **kw: calls.append(kw.get("isArm9")) or real(data, *a, **kw))
    with NdsImage.load(path) as image:  # one image at a time; output lives in memory only
        assert digest(image.data, "sha1") == sha1, "NDS_RETAIL_INPUT_WRONG_HASH"
        decoded, offset, after = _edit_site(image)
        old = image.extent("arm9")
        output, manifest = image.apply()
        assert calls and set(calls) == {True}
        new = NdsImage.load(output)
        n = new.extent("arm9")
        assert n.length - old.length <= image.slack("arm9")
        redecoded = new.decoded("arm9", arm9_compressed=True)
        expected = bytearray(decoded)  # only the edit and the managed pointer may differ
        expected[offset:offset + 4] = after
        struct.pack_into("<I", expected, 0xFCC - 8, new.arm9_ram_base + n.length)
        assert redecoded == bytes(expected)
        assert struct.unpack_from("<I", output, 0x2C)[0] == n.length
        pos = redecoded.find(MAGIC)
        assert struct.unpack_from("<I", redecoded, pos - 8)[0] == new.arm9_ram_base + n.length
        assert struct.unpack_from("<H", output, 0x15E)[0] == _crc16(output[:0x15E])
        assert verify_only_declared_changes(image, output, manifest)
        del new, output
        gc.collect()
    monkeypatch.undo()
    assert _arm9_prefix_consistent(nds_image, path)  # positive control for the probe
    # Mutation control: flipping isArm9 in a temp copy must go red.
    assert not _arm9_prefix_consistent(_mutated_module(tmp_path), path)



@pytest.mark.parametrize("title,suffix,sha1,encoded_size,slack", RETAIL[2:3])
def test_retail_arm9_shrink_updates_every_size_field(title, suffix, sha1, encoded_size, slack):
    """Zero >=0x20000 bytes of real code: the encoded ARM9 must shrink and ALL size metadata follow."""
    with NdsImage.load(_retail(title, suffix)) as image:
        assert digest(image.data, "sha1") == sha1, "NDS_RETAIL_INPUT_WRONG_HASH"
        decoded = image.decoded("arm9", arm9_compressed=True)
        old = image.extent("arm9")
        offset, size = 0x20000, 0x20000  # ordinary code, clear of module params (0xFCC) and autoloads
        image.edit_arm9(image.arm9_ram_base + offset, decoded[offset:offset + size], bytes(size),
                        arm9_compressed=True, arm9_ram_base=image.arm9_ram_base, reason="retail shrink control")
        output, manifest = image.apply()
        new = NdsImage.load(output)
        n = new.extent("arm9")
        assert n.length < old.length  # a shrink; the stability gate also bounds any growth by the FF slack
        assert n.length - old.length <= image.slack("arm9")
        assert struct.unpack_from("<I", output, 0x2C)[0] == n.length  # NDS header ARM9 size
        redecoded = new.decoded("arm9", arm9_compressed=True)
        expected = bytearray(decoded)
        expected[offset:offset + size] = bytes(size)
        struct.pack_into("<I", expected, 0xFCC - 8, new.arm9_ram_base + n.length)  # compressed_static_end
        assert redecoded == bytes(expected)
        assert struct.unpack_from("<H", output, 0x15E)[0] == _crc16(output[:0x15E])  # real-header oracle
        assert new.autoload_block("itcm").as_tuple() == image.autoload_block("itcm").as_tuple()
        assert verify_only_declared_changes(image, output, manifest)
        del new, output
        gc.collect()
