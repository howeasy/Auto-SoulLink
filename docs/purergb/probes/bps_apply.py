"""Minimal BPS (beat) patch applier for research only. Spec: byuu's BPS format v1.
Usage: python bps_apply.py <source.rom> <patch.bps> <out.rom>
Writes only to the scratchpad output path given."""
import hashlib
import struct
import sys
import zlib


def read_vlq(data, pos):
    result = 0
    shift = 1
    while True:
        x = data[pos]
        pos += 1
        result += (x & 0x7F) * shift
        if x & 0x80:
            break
        shift <<= 7
        result += shift
    return result, pos


def apply(source, patch):
    assert patch[:4] == b"BPS1", "not a BPS patch"
    pos = 4
    src_size, pos = read_vlq(patch, pos)
    tgt_size, pos = read_vlq(patch, pos)
    meta_size, pos = read_vlq(patch, pos)
    pos += meta_size
    assert len(source) == src_size, f"source size {len(source)} != {src_size}"
    target = bytearray(tgt_size)
    out = 0
    src_rel = 0
    tgt_rel = 0
    end = len(patch) - 12
    while pos < end:
        data, pos = read_vlq(patch, pos)
        action = data & 3
        length = (data >> 2) + 1
        if action == 0:  # SourceRead
            target[out:out + length] = source[out:out + length]
            out += length
        elif action == 1:  # TargetRead
            target[out:out + length] = patch[pos:pos + length]
            pos += length
            out += length
        elif action == 2:  # SourceCopy
            d, pos = read_vlq(patch, pos)
            src_rel += (-1 if d & 1 else 1) * (d >> 1)
            target[out:out + length] = source[src_rel:src_rel + length]
            src_rel += length
            out += length
        else:  # TargetCopy
            d, pos = read_vlq(patch, pos)
            tgt_rel += (-1 if d & 1 else 1) * (d >> 1)
            for _ in range(length):
                target[out] = target[tgt_rel]
                out += 1
                tgt_rel += 1
    src_crc, tgt_crc, patch_crc = struct.unpack("<III", patch[-12:])
    assert zlib.crc32(source) & 0xFFFFFFFF == src_crc, "source CRC mismatch"
    assert zlib.crc32(patch[:-4]) & 0xFFFFFFFF == patch_crc, "patch CRC mismatch"
    assert zlib.crc32(bytes(target)) & 0xFFFFFFFF == tgt_crc, "target CRC mismatch"
    return bytes(target)


if __name__ == "__main__":
    src_path, bps_path, out_path = sys.argv[1:4]
    source = open(src_path, "rb").read()
    patch = open(bps_path, "rb").read()
    target = apply(source, patch)
    open(out_path, "wb").write(target)
    print(f"source sha1 {hashlib.sha1(source).hexdigest()} size {len(source)}")
    print(f"target sha1 {hashlib.sha1(target).hexdigest()} md5 {hashlib.md5(target).hexdigest()} size {len(target)}")
