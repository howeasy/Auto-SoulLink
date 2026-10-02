"""Read-only NDS containers and a size-preserving, declared-span editor.

No ROM serialization or file-writing API is provided. Paths are mapped read-only;
apply() allocates one output bytes object, and no-op bytes inputs are reused.
"""
from __future__ import annotations

import hashlib
import mmap
import os
import struct
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import NamedTuple

CHUNK = 1024 * 1024
# NitroSDK module-params: seven u32 words then this 8-byte doubled magic (struct is 0x24 bytes).
MODULE_MAGIC = bytes.fromhex("2106c0dedec00621")
MODULE_WORDS = 0x1C  # magic - 0x1C = autoload_list_start


class ImageError(ValueError):
    """Malformed geometry, ambiguous ownership, or an unauthorized edit."""


def integer(value, name, minimum=0):
    if type(value) is not int or value < minimum:
        raise ImageError(f"{name}: integer >= {minimum} required")
    return value


def digest(data, algorithm="sha256", start=0, length=None):
    """Hash a bytes-like object without copying its complete contents."""
    length = len(data) - start if length is None else length
    if start < 0 or length < 0 or start + length > len(data):
        raise ImageError("hash outside image")
    h = hashlib.new(algorithm)
    view = memoryview(data)
    try:
        for pos in range(start, start + length, CHUNK):
            h.update(view[pos:min(start + length, pos + CHUNK)])
    finally:
        view.release()
    return h.hexdigest()


@dataclass(frozen=True)
class Extent:
    name: str
    offset: int
    length: int
    kind: str

    @property
    def end(self):
        return self.offset + self.length


@dataclass(frozen=True)
class Overlay:
    id: int
    processor: int
    entry_offset: int
    file_id: int
    ram_base: int
    ram_size: int
    bss_size: int
    flags: int

    @property
    def name(self):
        return f"overlay{self.processor}:{self.id}"

    @property
    def compressed(self):
        return bool(self.flags & 0x01000000)


@dataclass(frozen=True)
class ChangedSpan:
    offset: int
    length: int
    container: str
    before_sha1: str
    after_sha1: str
    reason: str

    def to_dict(self):
        return asdict(self)


def _crc16(data, init=0xFFFF):
    value = init
    for byte in data:
        value ^= byte
        for _ in range(8):
            value = (value >> 1) ^ (0xA001 if value & 1 else 0)
    return value


class AutoloadInfo(NamedTuple):
    ram_address: int
    size: int
    bss_size: int
    offset: int  # offset of the data inside the DECODED ARM9


class AutoloadBlock(bytes):
    """The autoload DATA bytes (bss excluded) plus where they live."""

    def __new__(cls, data, info, kind, index):
        obj = super().__new__(cls, data)
        obj.info, obj.kind, obj.index = info, kind, index
        return obj

    ram_address = property(lambda self: self.info.ram_address)
    size = property(lambda self: self.info.size)
    bss_size = property(lambda self: self.info.bss_size)
    offset = property(lambda self: self.info.offset)

    def as_tuple(self):
        return tuple(self.info)


def _autoload_kind(ram):
    if 0x01FF8000 <= ram < 0x02000000:
        return "itcm"
    if 0x027E0000 <= ram < 0x027E4000 or 0x02FE0000 <= ram < 0x02FE4000:  # Gen 4 / Gen 5
        return "dtcm"
    return None


class NdsImage:
    """An immutable input image plus a pending, explicitly checked edit plan."""

    @classmethod
    def load(cls, path_or_bytes):
        obj = cls.__new__(cls)
        obj._mapping = None
        obj._closed = False
        if isinstance(path_or_bytes, (str, Path)):
            with open(path_or_bytes, "rb") as source:
                if os.fstat(source.fileno()).st_size == 0:
                    raise ImageError("empty file")
                obj._mapping = mmap.mmap(source.fileno(), 0, access=mmap.ACCESS_READ)
            obj.data = obj._mapping
        elif isinstance(path_or_bytes, bytes):
            obj.data = path_or_bytes
        else:
            raise TypeError("load requires an immutable bytes object or path")
        obj._spans = []
        obj._logical = {}
        try:
            obj._parse()
        except Exception:
            obj.close()
            raise
        return obj

    def close(self):
        if self._mapping is not None:
            self._mapping.close()
            self._mapping = None
            self._closed = True

    def _open(self):
        if self._closed:
            raise ImageError("image is closed")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _u32(self, offset):
        return struct.unpack_from("<I", self.data, offset)[0]

    def _parse(self):
        if len(self.data) < 0x400:
            raise ImageError("truncated NDS header (minimum 0x400)")
        try:
            self.gamecode = bytes(self.data[0x0C:0x10]).decode("ascii", errors="strict")
        except UnicodeDecodeError:
            raise ImageError("non-ASCII gamecode") from None
        self.version = self.data[0x1E]
        self.unit_code = self.data[0x12]
        self.arm9_ram_base = self._u32(0x28)
        self.ntr_size = self._u32(0x80)
        self.header_size = self._u32(0x84)
        self.dsi_size = self._u32(0x210) if self.unit_code & 2 else 0
        if not 0x400 <= self.header_size <= len(self.data):
            raise ImageError("invalid declared header size")
        for size in (self.ntr_size, self.dsi_size):
            if size > len(self.data):
                raise ImageError("declared ROM size exceeds file")
        self.containers = {}
        self.overlays = {}
        self.fat = []

        def add(name, offset, length, kind="payload"):
            if not length:
                return
            if offset < 0 or length < 0 or offset + length > len(self.data):
                raise ImageError(f"{name}: extent outside image")
            self.containers[name] = Extent(name, offset, length, kind)

        add("header", 0, 0x400, "header")
        if self.header_size > 0x400:
            add("header_reserved", 0x400, self.header_size - 0x400, "reserved")
        for name, off, sz in (("arm9", 0x20, 0x2C), ("arm7", 0x30, 0x3C),
                              ("fnt", 0x40, 0x44), ("fat", 0x48, 0x4C),
                              ("y9", 0x50, 0x54), ("y7", 0x58, 0x5C)):
            add(name, self._u32(off), self._u32(sz))
        if "arm9" not in self.containers:
            raise ImageError("missing ARM9")
        banner = self._u32(0x68)
        if banner:
            if banner + 2 > len(self.data):
                raise ImageError("banner outside image")
            version = struct.unpack_from("<H", self.data, banner)[0]
            sizes = {1: 0x840, 2: 0x940, 3: 0x1240, 0x103: 0x23C0}
            if version not in sizes:
                raise ImageError("unsupported banner version")
            add("banner", banner, sizes[version])
        if self.unit_code & 2:
            for name, off, sz in (("dsi_arm9i", 0x1C0, 0x1CC),
                                  ("dsi_arm7i", 0x1D0, 0x1DC),
                                  ("dsi_sector_hashes", 0x1F0, 0x1F4),
                                  ("dsi_block_hashes", 0x1F8, 0x1FC)):
                add(name, self._u32(off), self._u32(sz))
        fat = self.containers.get("fat")
        if fat:
            if fat.length % 8:
                raise ImageError("FAT size is not a multiple of 8")
            for pos in range(fat.offset, fat.end, 8):
                start, end = struct.unpack_from("<II", self.data, pos)
                if start > end or end > len(self.data):
                    raise ImageError("invalid FAT range")
                self.fat.append((start, end))
        owners = {}
        for processor in (9, 7):
            table = self.containers.get(f"y{processor}")
            if not table:
                continue
            if table.length % 32:
                raise ImageError("overlay table size is not a multiple of 32")
            for pos in range(table.offset, table.end, 32):
                if not any(self.data[pos:pos + 32]):
                    continue  # all-zero entries are table padding, not overlays
                oid, ram, size, bss, _, _, fid, flags = struct.unpack_from("<8I", self.data, pos)
                ov = Overlay(oid, processor, pos, fid, ram, size, bss, flags)
                if ov.name in self.overlays or fid in owners or fid >= len(self.fat):
                    raise ImageError("duplicate overlay or invalid/shared overlay file id")
                if ram + size + bss > 0x100000000:
                    raise ImageError("overlay RAM extent overflow")
                start, end = self.fat[fid]
                if start == end or (ov.compressed and (flags & 0xFFFFFF) != end - start):
                    raise ImageError("overlay file size disagrees with table")
                if not ov.compressed and size != end - start:
                    raise ImageError("raw overlay RAM size disagrees with file")
                owners[fid] = ov.name
                self.overlays[ov.name] = ov
        for fid, (start, end) in enumerate(self.fat):
            add(owners.get(fid, f"file:{fid}"), start, end - start)
        used = sorted(self.containers.values(), key=lambda x: x.offset)
        end = 0
        self.extents = []
        for ext in used:
            if ext.offset < end:
                raise ImageError(f"overlapping extents at {ext.name}")
            if ext.offset > end:
                self.extents.append(self._gap(end, ext.offset))
            self.extents.append(ext)
            end = ext.end
        # Keep trailing FF distinct from any non-padding bytes after the last file.
        tail = len(self.data)
        while tail > end:
            lo = max(end, tail - CHUNK)
            block = bytes(self.data[lo:tail])
            stripped = block.rstrip(b"\xff")
            if stripped:
                tail = lo + len(stripped)
                break
            tail = lo
        if tail > end:
            self.extents.append(self._gap(end, tail))
        if tail < len(self.data):
            self.extents.append(Extent("trailing_ff", tail, len(self.data) - tail, "padding_ff"))
        self.extents = tuple(self.extents)

    def _gap(self, start, end):
        zero = ff = True
        for pos in range(start, end, CHUNK):
            block = bytes(self.data[pos:min(pos + CHUNK, end)])
            zero = zero and not block.strip(b"\0")
            ff = ff and not block.strip(b"\xff")
            if not zero and not ff:
                break
        kind = "padding_ff" if ff else "padding_zero" if zero else "unmapped"
        return Extent(f"{kind}@{start:x}", start, end - start, kind)

    def extent(self, name):
        try:
            return self.containers[name]
        except KeyError:
            raise ImageError(f"unknown container: {name}") from None

    def extent_at(self, offset, length):
        integer(offset, "offset")
        integer(length, "length", 1)
        for ext in self.extents:
            if ext.offset <= offset and offset + length <= ext.end:
                return ext
        raise ImageError("span crosses an extent boundary or lies outside image")

    def read(self, container):
        self._open()
        ext = self.extent(container)
        return bytes(self.data[ext.offset:ext.end])

    def decoded(self, container, *, arm9_compressed=None):
        raw = self.read(container)
        if container == "arm9":
            if type(arm9_compressed) is not bool:
                raise ImageError("ARM9 compression must be explicitly supplied")
            compressed = arm9_compressed
        else:
            compressed = self.overlays[container].compressed if container in self.overlays else False
        if not compressed:
            return raw
        from ndspy import codeCompression
        try:
            data = codeCompression.decompress(raw)
        except Exception as exc:
            raise ImageError(f"invalid BLZ in {container}: {exc}") from exc
        if len(data) <= len(raw):
            raise ImageError(f"{container}: compressed flag without a compressed stream")
        if container in self.overlays and len(data) != self.overlays[container].ram_size:
            raise ImageError("overlay decompressed size disagrees with y table")
        return bytes(data)

    def slack(self, container):
        """Only contiguous FF up to the next used extent can be consumed."""
        ext = self.extent(container)
        limit = min((e.offset for e in self.containers.values() if e.offset >= ext.end),
                    default=len(self.data))
        end = ext.end
        for pos in range(end, limit, CHUNK):
            block = bytes(self.data[pos:min(pos + CHUNK, limit)])
            n = len(block) - len(block.lstrip(b"\xff"))
            end += n
            if n != len(block):
                break
        return end - ext.end

    def _module_params(self, decoded):
        """(struct_offset, 7 words) of the unique NitroSDK module-params, else None."""
        pos = decoded.find(MODULE_MAGIC)
        if pos < 0:
            return None
        if pos < MODULE_WORDS or decoded.find(MODULE_MAGIC, pos + 1) >= 0:
            raise ImageError("ambiguous ARM9 module parameters")
        start = pos - MODULE_WORDS
        return start, struct.unpack_from("<7I", decoded, start)

    def _arm9_is_compressed(self):
        """Infer compression from compressed_static_end (0 = raw, ram+file length = BLZ)."""
        raw = self.read("arm9")
        pos = raw.find(MODULE_MAGIC)
        if pos < MODULE_WORDS:
            raise ImageError("ARM9 module parameters absent or not in the stored bytes; "
                             "pass arm9_compressed explicitly")
        pointer = struct.unpack_from("<I", raw, pos - 8)[0]
        if pointer == self.arm9_ram_base + len(raw):
            return True
        if pointer == 0:
            return False
        raise ImageError("cannot infer ARM9 compression from compressed_static_end; "
                         "pass arm9_compressed explicitly")

    def autoload_blocks(self, *, arm9_compressed=None, entry_size=None):
        """Autoload table in list order as AutoloadBlock (data bytes + info/kind/index).

        The table is located by the NitroSDK module-params magic inside the DECODED
        ARM9; data runs contiguously from autoload_start, so entry size (12 on the Gen 4
        SDK, 16 on Gen 5) is chosen by the contiguity check unless supplied.
        """
        self._open()
        if arm9_compressed is None:
            arm9_compressed = self._arm9_is_compressed()
        decoded = self.decoded("arm9", arm9_compressed=arm9_compressed)
        found = self._module_params(decoded)
        if found is None:
            raise ImageError("ARM9 module parameters absent")
        words = found[1]
        base = self.arm9_ram_base
        ls, le, auto = (words[0] - base, words[1] - base, words[2] - base)
        if not 0 <= auto <= ls <= le <= len(decoded):
            raise ImageError("autoload table outside decoded ARM9")
        if le == ls:
            return ()
        fits = []
        for width in ((entry_size,) if entry_size else (12, 16)):
            if (le - ls) % width:
                continue
            # {ram, size, ...}; bss is the LAST word (the 16-byte Gen 5 row has an SDK word between).
            rows = [(struct.unpack_from("<II", decoded, p) + struct.unpack_from("<I", decoded, p + width - 4))
                    for p in range(ls, le, width)]
            if sum(r[1] for r in rows) == ls - auto:
                fits.append(rows)
        if len(fits) != 1:
            raise ImageError("autoload table entry size is undecidable" if fits
                             else "autoload table does not tile the data before it")
        blocks, offset = [], auto
        for index, (ram, size, bss) in enumerate(fits[0]):
            info = AutoloadInfo(ram, size, bss, offset)
            blocks.append(AutoloadBlock(decoded[offset:offset + size], info, _autoload_kind(ram), index))
            offset += size
        return tuple(blocks)

    def autoload_block(self, kind, *, arm9_compressed=None):
        """The 'itcm'/'dtcm' autoload as bytes-with-info; None if absent, ImageError if no module params."""
        if kind not in ("itcm", "dtcm"):
            raise ImageError("autoload kind must be 'itcm' or 'dtcm'")
        hits = [b for b in self.autoload_blocks(arm9_compressed=arm9_compressed) if b.kind == kind]
        if len(hits) > 1:
            raise ImageError(f"ambiguous {kind} autoload")
        return hits[0] if hits else None

    def edit(self, *, expected_before, after, reason, offset=None, container=None,
             container_offset=0):
        """Stage one same-size physical span; coordinates are mutually exclusive."""
        self._open()
        if not isinstance(expected_before, bytes) or not isinstance(after, bytes):
            raise ImageError("edit payloads must be bytes")
        if (offset is None) == (container is None):
            raise ImageError("supply offset OR container")
        integer(container_offset, "container_offset")
        if offset is not None and container_offset:
            raise ImageError("container_offset without container")
        if container is not None:
            ext = self.extent(container)
            offset = ext.offset + container_offset
        ext_at = self.extent_at(offset, len(expected_before))
        if container is not None and ext_at.name != container:
            raise ImageError("edit outside named container")
        span = self._checked_span(offset, expected_before, after, ext_at.name, reason)
        for name in self._logical:
            ext = self.extent(name)
            if offset < ext.end + self.slack(name) and offset + len(after) > ext.offset:
                raise ImageError("physical edit overlaps decoded-container transaction")
        self._check_overlap(self._spans + [span])
        self._spans.append(span)

    edit_span = edit

    def _checked_span(self, offset, before, after, container, reason):
        integer(offset, "offset")
        if not isinstance(before, bytes) or not isinstance(after, bytes):
            raise ImageError("edit payloads must be bytes")
        if not before or len(before) != len(after) or offset + len(before) > len(self.data):
            raise ImageError("edits must be nonempty, same-size, in-image spans")
        if not isinstance(reason, str) or not reason.strip():
            raise ImageError("edit reason required")
        if self.data[offset:offset + len(before)] != before:
            raise ImageError(f"expected-before mismatch at {offset:#x}")
        return (offset, before, after, container, reason)

    @staticmethod
    def _check_overlap(spans):
        end = -1
        for start, before, *_ in sorted(spans):
            if start < end:
                raise ImageError("overlapping edit spans")
            end = start + len(before)

    def _edit_decoded(self, name, address, before, after, reason, compressed, ram):
        self._open()
        integer(address, "RAM address")
        if not isinstance(before, bytes) or not isinstance(after, bytes) or not before or len(before) != len(after):
            raise ImageError("decoded edit must be nonempty and same-size")
        if not isinstance(reason, str) or not reason.strip():
            raise ImageError("edit reason required")
        ext = self.extent(name)
        for off, old, *_ in self._spans:
            if off < ext.end + self.slack(name) and off + len(old) > ext.offset:
                raise ImageError("decoded edit overlaps physical edit")
        if name not in self._logical:
            decoded = self.decoded(name, arm9_compressed=compressed)
            self._logical[name] = (decoded, [], compressed, ram)
        decoded, edits, prior_comp, prior_ram = self._logical[name]
        if (compressed, ram) != (prior_comp, prior_ram):
            raise ImageError("inconsistent decoded edit configuration")
        offset = address - ram
        if offset < 0 or offset + len(before) > len(decoded):
            raise ImageError("RAM edit outside decoded container")
        if decoded[offset:offset + len(before)] != before:
            raise ImageError("decoded expected-before mismatch")
        candidate = (offset, before, after, name, reason)
        self._check_overlap(edits + [candidate])
        edits.append(candidate)

    def edit_arm9(self, address, expected_before, after, *, arm9_compressed,
                  arm9_ram_base, reason):
        if type(arm9_compressed) is not bool or arm9_ram_base != self.arm9_ram_base:
            raise ImageError("explicit ARM9 configuration disagrees with header")
        self._edit_decoded("arm9", address, expected_before, after, reason,
                           arm9_compressed, arm9_ram_base)

    def edit_overlay(self, overlay_id, address, expected_before, after, *, reason, processor=9):
        integer(overlay_id, "overlay id")
        name = f"overlay{processor}:{overlay_id}"
        if name not in self.overlays:
            raise ImageError("unknown overlay")
        ov = self.overlays[name]
        self._edit_decoded(name, address, expected_before, after, reason, ov.compressed, ov.ram_base)

    def _encoded_spans(self, arm9_lacks_module_params=False):
        self._open()
        from ndspy import codeCompression
        spans = list(self._spans)
        for name, (original, edits, compressed, ram) in self._logical.items():
            data = bytearray(original)
            for off, before, after, _, _ in edits:
                data[off:off + len(before)] = after
            if data == original:
                continue  # a logical no-op must not rewrite a different BLZ encoding
            ext = self.extent(name)
            encoded = codeCompression.compress(bytes(data), isArm9=name == "arm9") if compressed else bytes(data)
            if compressed and name == "arm9":
                # NitroSDK's compressed_static_end is in the uncompressed prefix.
                magic = MODULE_MAGIC
                pos = original.find(magic)
                if pos < 0 and len(encoded) != ext.length and not arm9_lacks_module_params:
                    raise ImageError("unmanaged ARM9 compressed_static_end: no NitroSDK module "
                                     "parameters; pass arm9_lacks_module_params=True only if the "
                                     "title genuinely has none")
                if pos >= 0:
                    if pos < 8 or original.find(magic, pos + 1) >= 0:
                        raise ImageError("ambiguous ARM9 module parameters")
                    pointer = pos - 8
                    if struct.unpack_from("<I", original, pointer)[0] != ram + ext.length:
                        raise ImageError("ARM9 compressed_static_end mismatch")
                    if any(off < pointer + 4 and off + len(old) > pointer for off, old, *_ in edits):
                        raise ImageError("manual edit overlaps managed compression pointer")
                    struct.pack_into("<I", data, pointer, ram + len(encoded))
                    revised = codeCompression.compress(bytes(data), isArm9=True)
                    if len(revised) != len(encoded):
                        raise ImageError("compression pointer changed compressed size")
                    encoded = revised
            if compressed and (codeCompression.decompress(encoded) != bytes(data) or len(encoded) >= len(data)):
                # ndspy compress(isArm9=True) may normalize the ARM9 first byte, so a title whose
                # ARM9 does not round-trip lands here (Gen 4 HG/SS is unmeasured).
                raise ImageError(f"{name}: edited container no longer has valid BLZ compression "
                                 "(ndspy compress may normalize the ARM9 first byte: this title's "
                                 "ARM9 may not round-trip)")
            if len(encoded) > ext.length + (self.slack(name) if compressed else 0):
                raise ImageError(f"{name}: recompression growth exceeds FF slack")
            why = "; ".join(e[4] for e in edits)
            spans.append(self._checked_span(ext.offset, bytes(self.data[ext.offset:ext.offset + len(encoded)]),
                                            bytes(encoded), name, why))
            if len(encoded) != ext.length:
                if name == "arm9":
                    metadata = [(0x2C, len(encoded), "header")]
                else:
                    ov = self.overlays[name]
                    metadata = [(self.extent("fat").offset + ov.file_id * 8 + 4,
                                 ext.offset + len(encoded), "fat"),
                                (ov.entry_offset + 28, (ov.flags & 0xFF000000) | len(encoded),
                                 f"y{ov.processor}")]
                    if len(encoded) > 0xFFFFFF:
                        raise ImageError("overlay compressed-size field overflow")
                for off, value, container in metadata:
                    spans.append(self._checked_span(off, bytes(self.data[off:off + 4]),
                                                    struct.pack("<I", value), container, why + ": encoded size"))
        self._check_overlap(spans)
        if any(off < 0x15E and before != after for off, before, after, *_ in spans):
            header = bytearray(self.data[:0x15E])
            for off, _, after, *_ in spans:
                if off < 0x15E:
                    n = min(len(after), 0x15E - off)
                    header[off:off + n] = after[:n]
            spans.append(self._checked_span(0x15E, bytes(self.data[0x15E:0x160]),
                                            struct.pack("<H", _crc16(header)), "header", "header CRC16"))
        self._check_overlap(spans)
        for off, before, *_ in spans:
            if self.data[off:off + len(before)] != before:
                raise ImageError("input preimage changed after staging")
        return sorted(s for s in spans if s[1] != s[2])

    def apply(self, *, arm9_lacks_module_params=False):
        """Return (bytes, tuple[ChangedSpan]); never save or modify the input.

        arm9_lacks_module_params: opt-in for a title with no NitroSDK module params whose
        encoded ARM9 length changes (otherwise that edit is refused).
        """
        spans = self._encoded_spans(arm9_lacks_module_params)
        if not spans:
            return (self.data if isinstance(self.data, bytes) else bytes(self.data)), ()
        view = memoryview(self.data)
        pieces, manifest, end = [], [], 0
        try:
            for off, before, after, container, reason in spans:
                pieces.extend((view[end:off], after))
                manifest.append(ChangedSpan(off, len(after), container,
                                            digest(before, "sha1"), digest(after, "sha1"), reason))
                end = off + len(after)
            pieces.append(view[end:])
            output = b"".join(pieces)
        finally:
            pieces.clear()
            view.release()
        return output, tuple(manifest)


def verify_only_declared_changes(original, patched, manifest):
    """Verify exact changed-span hashes AND all bytes outside those spans."""
    import re
    owner_image = original if isinstance(original, NdsImage) else NdsImage.load(bytes(original) if not isinstance(original, bytes) else original)
    original = original.data if isinstance(original, NdsImage) else original
    patched = patched.data if isinstance(patched, NdsImage) else patched
    if len(original) != len(patched):
        raise ImageError("image size changed; relocation/append not supported")
    rows = []
    for row in manifest:
        if isinstance(row, dict):
            if set(row) != set(ChangedSpan.__dataclass_fields__):
                raise ImageError("manifest keys differ from schema")
            row = ChangedSpan(**row)
        if not isinstance(row, ChangedSpan):
            raise ImageError("invalid manifest entry")
        integer(row.offset, "manifest offset")
        integer(row.length, "manifest length", 1)
        if row.offset + row.length > len(original):
            raise ImageError("manifest outside image")
        if not isinstance(row.container, str) or not row.container or not isinstance(row.reason, str) or not row.reason.strip():
            raise ImageError("manifest container/reason required")
        owner = next((e for e in owner_image.extents if e.name == row.container), None)
        if owner is None:
            raise ImageError("unknown manifest container")
        limit = owner.end
        # Deliberate: a row that STARTS at a container may extend into its FF slack (legitimate
        # recompression growth). The editor itself never stages such a row via edit().
        if row.container in owner_image.containers and row.offset == owner.offset:
            limit += owner_image.slack(row.container)
        if row.offset < owner.offset or row.offset + row.length > limit:
            raise ImageError("manifest span outside its container/slack")
        if any(not isinstance(h, str) or re.fullmatch(r"[0-9a-f]{40}", h) is None
               for h in (row.before_sha1, row.after_sha1)):
            raise ImageError("invalid manifest SHA1")
        rows.append(row)
    end = 0
    for row in sorted(rows, key=lambda r: r.offset):
        if row.offset < end:
            raise ImageError("overlapping manifest entries")
        _unchanged(original, patched, end, row.offset)
        for data, want in ((original, row.before_sha1), (patched, row.after_sha1)):
            if digest(data, "sha1", row.offset, row.length) != want:
                raise ImageError("manifest span hash mismatch")
        end = row.offset + row.length
    _unchanged(original, patched, end, len(original))
    return True


def _unchanged(before, after, start, end):
    a, b = memoryview(before), memoryview(after)
    try:
        for pos in range(start, end, CHUNK):
            limit = min(pos + CHUNK, end)
            if a[pos:limit] != b[pos:limit]:
                raise ImageError(f"undeclared difference in [{pos:#x}, {limit:#x})")
    finally:
        a.release()
        b.release()
