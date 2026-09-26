"""FRLG-R2b: real Lua ROM transport -> sparse Python decode, with failure controls.

The fake IO uses the same GBA bus addresses as gen3_world.World, but missing ROM
bytes return None instead of zero. No emulator or hello wiring is exercised here.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import struct
from collections import Counter
from pathlib import Path

import lupa
import pytest

from server.adapters import gen3_rom_tables as decoder
from tools.gen3_final_cut import STAGED, rom_pins

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "lua/gen3/rom_content.lua"
BASE = 0x08000000
STRIDES = {"gTrainers": 40, "gWildMonHeaders": 20, "gEvolutionTable": 40,
           "gSpeciesInfo": 28, "gTrainerClassNames": 13}
SCRATCH = Path(
    "C:/Users/howar/AppData/Local/Temp/claude/"
    "E--Google-Drive-SLink--claude-worktrees-gen3-migration-planning-5d8e45/"
    "30c21a7a-9a9b-44db-b573-10e09226bcc8/scratchpad"
)


def symbols(title, rom_size):
    result = {"rom_size": rom_size}
    for line in (ROOT / f"data/gen3/pret/poke{title}.sym").read_text().splitlines():
        fields = line.split()
        if len(fields) == 4 and fields[-1] in STRIDES:
            size = int(fields[2], 16)
            assert size % STRIDES[fields[-1]] == 0
            result[fields[-1]] = {"address": int(fields[0], 16), "size": size,
                                  "count": size // STRIDES[fields[-1]]}
    assert set(result) == {*STRIDES, "rom_size"}
    return result


class RomIO:
    def __init__(self, raw):
        self.raw, self.calls = raw, Counter()

    def read_u8(self, address):
        self.calls[address] += 1
        offset = address - BASE
        return self.raw[offset] if 0 <= offset < len(self.raw) else None

    def read_le(self, address, size):
        values = [self.read_u8(address + i) for i in range(size)]
        return None if None in values else int.from_bytes(bytes(values), "little")


def collector(rom, tbl, *, reader=None):
    reader = reader or RomIO(rom)
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    module = lua.eval("dofile")(MODULE.as_posix())
    io = lua.table(read_u8=reader.read_u8,
                   read_u16_le=lambda a: reader.read_le(a, 2),
                   read_u32_le=lambda a: reader.read_le(a, 4))
    obj = module.new(lua.table_from(tbl, recursive=True), io)
    return lua, obj, reader


def payload_from(obj):
    result = obj.payload(obj)
    assert not isinstance(result, tuple), f"Lua collector refused: {result}"
    return {"tables": [{"addr": result.tables[i].addr, "hex": result.tables[i].hex}
                       for i in range(1, len(result.tables) + 1)],
            "fingerprint": result.fingerprint}


def verify_payload(payload, rom):
    """Independent wire conversion/hash; regions may not overlap or omit bytes."""
    sparse, previous_end = {}, -1
    for row in payload["tables"]:
        address, text = row["addr"], row["hex"]
        assert address > previous_end, "regions must be sorted and coalesced, with real gaps"
        assert re.fullmatch(r"(?:[0-9a-f]{2})+", text)
        raw = bytes.fromhex(text)
        assert raw == bytes(rom[address - BASE:address - BASE + len(raw)])
        sparse[address] = raw
        previous_end = address + len(raw)
    assert sparse
    assert payload["fingerprint"] == hashlib.sha1(b"".join(sparse.values())).hexdigest()
    return sparse


def decode_at(raw, tbl):
    return {"trainers": decoder.decode_trainers(
                raw, tbl["gTrainers"]["address"], tbl["gTrainers"]["count"]),
            "wild_encounters": decoder.decode_wild_encounters(
                raw, tbl["gWildMonHeaders"]["address"], tbl["gWildMonHeaders"]["count"]),
            "evolutions": decoder.decode_evolutions(
                raw, tbl["gEvolutionTable"]["address"], tbl["gEvolutionTable"]["count"])}


def synthetic():
    rom = bytearray(0x2000)
    tbl = {name: {"address": BASE + offset, "count": count}
           for name, offset, count in (
               ("gTrainers", 0x100, 4), ("gWildMonHeaders", 0x200, 3),
               ("gEvolutionTable", 0x280, 4), ("gSpeciesInfo", 0x340, 4),
               ("gTrainerClassNames", 0x3C0, 2),
           )}
    tbl["rom_size"] = len(rom)
    for flags in range(4):
        head, party = 0x100 + flags * 40, 0x1000 + flags * 32
        rom[head:head + 2] = bytes((flags, 1))
        rom[head + 4:head + 16] = b"\xBB\xFF" + bytes(10)
        rom[head + 32] = 2
        struct.pack_into("<I", rom, head + 36, BASE + party)
        stride = 16 if flags & 1 else 8
        for slot in range(2):
            at = party + slot * stride
            rom[at:at + stride] = b"\xA5" * stride
            struct.pack_into("<HBxH", rom, at, 200, 12 + slot, 0x123 + flags + slot)
            if flags & 2:
                struct.pack_into("<H", rom, at + 6, 0x134)
            if flags & 1:
                struct.pack_into("<4H", rom, at + (8 if flags & 2 else 6), 1, 0x145, 3, 0)
    rom[0x200:0x202] = rom[0x214:0x216] = bytes((3, 19))
    for index, count in enumerate((12, 5, 5, 10)):
        info, slots = 0x1100 + index * 0x40, 0x1400 + index * 0x50
        struct.pack_into("<I", rom, 0x204 + index * 4, BASE + info)
        rom[info] = 21 + index
        struct.pack_into("<I", rom, info + 4, BASE + slots)
        for slot in range(count):
            struct.pack_into("<BBH", rom, slots + slot * 4, 2, 5, 0x156 + slot)
    # Shared pointed data and duplicate map IDs must survive without duplicate blobs.
    struct.pack_into("<I", rom, 0x218, BASE + 0x1100)
    rom[0x228:0x22A] = b"\xFF\xFF"
    struct.pack_into("<HHHH", rom, 0x280 + 40, 4, 16, 2, 0xEEEE)
    for name in ("gSpeciesInfo", "gTrainerClassNames"):
        at = tbl[name]["address"] - BASE
        size = tbl[name]["count"] * STRIDES[name]
        rom[at:at + size] = bytes(i % 256 for i in range(size))
    return rom, tbl


def test_synthetic_repointed_tables_match_full_rom_and_capture_every_byte_once():
    rom, tbl = synthetic()
    _, obj, reader = collector(rom, tbl)
    payload = payload_from(obj)
    sparse = verify_payload(payload, rom)
    assert decode_at(sparse, tbl) == decode_at(bytes(rom), tbl)
    assert len(decode_at(sparse, tbl)["wild_encounters"][(3, 19)]) == 2
    assert set(reader.calls.values()) == {1}
    assert sum(map(len, sparse.values())) == len(reader.calls)


def test_payload_is_cached_even_when_the_io_later_fails():
    rom, tbl = synthetic()
    _, obj, reader = collector(rom, tbl)
    first = payload_from(obj)
    calls = reader.calls.copy()
    reader.raw = b""
    assert payload_from(obj) == first
    assert reader.calls == calls


@pytest.mark.parametrize("names,remainder", ((36, 0), (41, 1), (55, 55), (60, 56), (1, 57), (31, 63)))
def test_sha1_matches_hashlib_across_padding_boundaries(names, remainder):
    rom, tbl = synthetic()
    tbl["gTrainerClassNames"]["count"] = names
    _, obj, _ = collector(rom, tbl)
    sparse = verify_payload(payload_from(obj), rom)
    assert sum(map(len, sparse.values())) % 64 == remainder


@pytest.mark.parametrize("offset", (0x124, 0x204, 0x1104), ids=("party", "wild_info", "wild_slots"))
@pytest.mark.parametrize("pointer", (0x02000000, BASE + 0x1FFF, 0x0A000000, 0xFFFFFFFF))
def test_bad_pointer_returns_no_payload_and_a_reason(offset, pointer):
    rom, tbl = synthetic()
    struct.pack_into("<I", rom, offset, pointer)
    _, obj, reader = collector(rom, tbl)
    result, reason = obj.payload(obj)
    assert result is None
    assert "out-of-range ROM pointer" in reason and f"0x{pointer:08x}" in reason
    calls = reader.calls.copy()
    # Failures are cached too: a retry cannot expose an earlier partial payload.
    assert obj.payload(obj) == (None, reason)
    assert reader.calls == calls


@pytest.mark.parametrize("offset,value,reason", (
    (0x100, 4, "invalid flags/count"), (0x120, 7, "invalid flags/count"),
    (0x228, 3, "missing 0xFF map-group sentinel"),
))
def test_invalid_layout_and_unterminated_walk_fail(offset, value, reason):
    rom, tbl = synthetic()
    rom[offset] = value
    _, obj, _ = collector(rom, tbl)
    result, why = obj.payload(obj)
    assert result is None and reason in why


@pytest.mark.parametrize("value", (None, -1, 256, 1.5, False))
def test_missing_or_invalid_rom_byte_never_becomes_zero(value):
    rom, tbl = synthetic()
    reader = RomIO(rom)
    real_read = reader.read_u8
    reader.read_u8 = lambda address: value if address == BASE + 0x1400 else real_read(address)
    _, obj, _ = collector(rom, tbl, reader=reader)
    result, reason = obj.payload(obj)
    assert result is None and "ROM byte unavailable at 0x08001400" in reason


def test_io_exception_returns_a_reason_without_a_partial_payload():
    rom, tbl = synthetic()
    reader = RomIO(rom)

    def broken(_address):
        raise RuntimeError("ROM domain unavailable")

    reader.read_u8 = broken
    _, obj, _ = collector(rom, tbl, reader=reader)
    result, reason = obj.payload(obj)
    assert result is None and "ROM domain unavailable" in reason


@pytest.mark.parametrize("change", ("missing", "negative", "huge", "fractional", "size", "address"))
def test_bad_table_descriptors_are_rejected_before_io(change):
    rom, tbl = synthetic()
    row = tbl["gTrainers"]
    if change == "missing":
        del tbl["gTrainers"]
    elif change in ("negative", "huge", "fractional"):
        row["count"] = {"negative": -1, "huge": 2**40, "fractional": 1.5}[change]
    elif change == "size":
        row["size"] = 41
    else:
        row["address"] = 0x02000000
    _, obj, reader = collector(rom, tbl)
    result, reason = obj.payload(obj)
    assert result is None and "gTrainers" in reason
    assert not reader.calls


@pytest.fixture(scope="module", params=("firered", "leafgreen"))
def clean(request):
    title = request.param
    candidates = [base / STAGED[title] for base in (ROOT, *ROOT.parents)]
    path = next((p for p in candidates if p.exists()), candidates[0])
    if not path.exists():
        pytest.skip(f"pinned clean {title} ROM absent: {path}")
    rom = path.read_bytes()
    expected = rom_pins(str(ROOT))[title]
    digest = hashlib.sha1(rom).hexdigest()
    assert digest == expected, f"{path} present but wrong {title} SHA-1: {digest} != {expected}"
    return title, rom


def test_pinned_clean_payload_decodes_exactly_like_the_full_rom(clean):
    title, rom = clean
    tbl = symbols(title, len(rom))
    _, obj, reader = collector(rom, tbl)
    payload = payload_from(obj)
    sparse = verify_payload(payload, rom)
    assert decoder.decode_rom_tables(sparse, title) == decoder.decode_rom_tables(rom, title)
    assert set(reader.calls.values()) == {1}
    # The two newly transported tables are raw controls for the next ingest card.
    for name in ("gSpeciesInfo", "gTrainerClassNames"):
        head = tbl[name]
        blob = next(raw[head["address"] - address:head["address"] - address + head["size"]]
                    for address, raw in sparse.items()
                    if address <= head["address"] and head["address"] + head["size"] <= address + len(raw))
        assert blob == rom[head["address"] - BASE:head["address"] - BASE + head["size"]]
    # This is the compact JSON payload, before embedding it in a hello envelope.
    assert len(json.dumps(payload, separators=(",", ":")).encode()) < 4 * 1024 * 1024


def test_scratch_allowed_randomized_rom_uses_its_own_parties(clean):
    title, clean_rom = clean
    name = "FireRed" if title == "firered" else "LeafGreen"
    path = SCRATCH / f"{name}_allowed.gba"
    if not path.exists():
        pytest.skip(f"UPR scratch {name}_allowed.gba absent: {path}")
    rom = path.read_bytes()
    assert rom[0xAC:0xB0] == (b"BPRE" if title == "firered" else b"BPGE")
    _, obj, _ = collector(rom, symbols(title, len(rom)))
    sparse = verify_payload(payload_from(obj), rom)
    decoded = decoder.decode_rom_tables(sparse, title)
    assert decoded == decoder.decode_rom_tables(rom, title)
    baseline = decoder.decode_rom_tables(clean_rom, title)["trainers"]
    assert any(row["party"] != baseline[tid]["party"] for tid, row in decoded["trainers"].items())


def test_relocated_table_heads_are_arguments_not_literals():
    rom, tbl = synthetic()
    moved = copy.deepcopy(tbl)
    # Move the trainer table independently of its already-repointed parties.
    rom[0x1800:0x18A0] = rom[0x100:0x1A0]
    rom[0x100:0x1A0] = b"\xEE" * 160
    moved["gTrainers"]["address"] = BASE + 0x1800
    _, obj, _ = collector(rom, moved)
    sparse = verify_payload(payload_from(obj), rom)
    assert decode_at(sparse, moved) == decode_at(bytes(rom), moved)
