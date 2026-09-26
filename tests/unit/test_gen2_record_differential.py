"""Independent Python/Lua record equality on MODEL memory, never played fixtures.

Decoders were independently frozen before this comparison: Python 535e187a8c8c,
Lua E923EEC6817B. Neither encoder constructs the buffers. Handwritten record order
comes from C7a7881d/G656583c macros/ram.asm box_struct/party_struct and box macros;
all bus/bank locations and collection offsets use actual generated C/G/S profiles.
These checks grant no snapshot, admission, save-durability or PHYSICAL authority.
"""

from __future__ import annotations

import copy
import hashlib
import json
import struct
from pathlib import Path

import pytest
from lupa.lua54 import LuaRuntime

from server.adapters import gen2_codec as codec

ROOT = Path(__file__).resolve().parents[2]
READS = ROOT / "lua/gen2/reads.lua"


def native(value):
    if not hasattr(value, "items"):
        return value
    keys = list(value.keys())
    if not keys or all(isinstance(key, int) for key in keys):
        assert sorted(keys) == list(range(1, len(keys) + 1))
        return [native(value[index]) for index in range(1, len(keys) + 1)]
    return {key: native(value[key]) for key in keys}


def model_record(seed=0, *, species=None, dv_word=None, pp=None):
    """48 bytes in native source order, with distinct fields and reserved bytes."""
    species = species if species is not None else (25, 81, 133, 201, 243, 251)[seed % 6]
    dvs = dv_word if dv_word is not None else (0x0000, 0xFFFF, 0x1A2B, 0xC0DE, 0xAABB, 0xFACE)[seed % 6]
    packed_pp = pp if pp is not None else bytes((0, 0x7F, 0x80, 0xC5))
    prefix = (
        bytes((species, 140 + seed, 33, 45, 0, 237))
        + (0x2468 + seed).to_bytes(2, "big")
        + (0x010203 + seed * 263).to_bytes(3, "big")
        + struct.pack(">5H", 1 + seed, 0x0203 + seed, 0x0405 + seed, 0x0607 + seed, 0x0809 + seed)
        + dvs.to_bytes(2, "big") + packed_pp
        + bytes((220 - seed, 0x21 + seed, 0x81 + seed, 0x30 + seed, 40 + seed))
    )
    assert len(prefix) == 32
    return prefix + bytes((8, 0xA0 + seed)) + struct.pack(
        ">7H", 300 + seed, 450 + seed, 101 + seed, 202 + seed, 303 + seed, 404 + seed, 505 + seed,
    )


def model_names(seed=0):
    # Eleven-byte buffers include data after the $50 terminator. Preservation of
    # those tails is part of the transfer/box contract, not text interpretation.
    return (
        bytes((0x80 + seed, 0x81, 0x50, *range(seed, seed + 8))),
        bytes((0x82, 0x83 + seed, 0x50, *range(seed + 8, seed + 16))),
    )


@pytest.fixture(scope="module", params=("crystal", "gold", "silver"))
def foundation(request):
    title = request.param
    wrapper = json.loads((ROOT / f"data/games/gen2_{title}/profile.json").read_text(encoding="utf-8"))
    assert wrapper["schema"] == "gen2-profile-v1" and set(wrapper["titles"]) == {title}
    # The profile itself must still name the current verified build receipt.
    assert wrapper["source"]["lock_sha256"] == hashlib.sha256(
        (ROOT / "data/gen2_sources.lock.json").read_bytes()
    ).hexdigest()
    assert wrapper["source"]["build_provenance_sha256"] == hashlib.sha256(
        (ROOT / "data/gen2/build_provenance.json").read_bytes()
    ).hexdigest()
    selected = wrapper["titles"][title]
    # No supplemental symbols/save constants: this exercises the reviewed profile
    # save-facts delta as the actual common interface to both independent readers.
    layout = codec.Gen2Layout.from_profile(wrapper, title)
    return selected, layout


class ModelMemory:
    """In-memory IO stand-in. No emulator, files, game globals or runtime writes."""

    def __init__(self, selected, *, decode_name=None):
        self.selected = selected
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        module = self.lua.execute(READS.read_text(encoding="utf-8"))
        self.bus, self.cart = bytearray(65536), bytearray(32768)
        self.calls, self.bank_calls = [], []
        self.bank_answers = []
        self.valid_bank = True
        self.diverge = None
        bind = self.lua.eval("""function(read, bank, size)
            return {read_range=function(a,n,d) return read(a,n,d) end,
                    bank_valid=function(b,a,n) return bank(b,a,n) end,
                    domain_size=function(d) return size(d) end, cart_ram_linear=true}
        end""")
        self.io = bind(self.read, self.bank, self.size)
        decode = None
        if decode_name is not None:
            decode = self.lua.eval("function(f) return function(raw) return f(raw) end end")(
                lambda raw: decode_name(bytes(native(raw)))
            )
        result = module.new(self.lua.table_from(selected, recursive=True), self.io, decode)
        assert not isinstance(result, tuple), f"generated profile rejected: {result}"
        self.reader = result

    def bytes(self, raw):
        return self.lua.table_from(list(raw))

    def read(self, address, length, domain):
        self.calls.append((domain, address, length))
        data = {"System Bus": self.bus, "CartRAM": self.cart}[domain]
        assert 0 <= address <= address + length <= len(data)
        raw = bytearray(data[address:address + length])
        if self.diverge is not None:
            target_domain, target_address = self.diverge
            if domain == target_domain and address <= target_address < address + length:
                raw[target_address - address] += 1
        return self.bytes(raw)

    def bank(self, bank, address, length):
        self.bank_calls.append((bank, address, length))
        return self.bank_answers.pop(0) if self.bank_answers else self.valid_bank

    def size(self, domain):
        assert domain == "CartRAM"
        return len(self.cart)

    def put_party(self, raw):
        address = self.selected["ram"]["wPartyCount"]
        self.bus[address:address + len(raw)] = raw

    def put_box(self, raw, index=None):
        if index is None:
            flat = self.selected["derived"]["active_box_flat"]
        else:
            flat = self.selected["storage_boxes"][index]["flat"]
        self.cart[flat:flat + len(raw)] = raw
        return flat


def model_collection(selected, kind, count, *, seed=0, egg_mix=True):
    c, a = selected["constants"], selected["ram"]
    party = kind == "party"
    prefix, base = ("wParty", a["wPartyCount"]) if party else ("sBox", a["sBox"])
    capacity = c["PARTY_LENGTH"] if party else c["MONS_PER_BOX"]
    stride = c["PARTYMON_STRUCT_LENGTH"] if party else c["BOXMON_STRUCT_LENGTH"]
    length = (a["wPartyMonNicknamesEnd"] - base) if party else (
        a["sBoxEnd"] - base if kind == "active" else c["BOX_LENGTH"]
    )
    assert 0 <= count <= capacity
    raw = bytearray([0xEE] * length)
    raw[0] = count
    markers, records = a[prefix + "Species"] - base, a[prefix + "Mon1"] - base
    ots, nicknames = a[prefix + "MonOTs"] - base, a[prefix + "MonNicknames"] - base
    raw[markers + count] = 255
    for slot in range(count):
        record = model_record(seed + slot, species=seed + slot + 1)[:stride]
        ot, nickname = model_names(seed + slot)
        raw[markers + slot] = 253 if egg_mix and slot % 2 else record[0]
        start = records + slot * stride
        raw[start:start + stride] = record
        start = ots + slot * c["NAME_LENGTH"]
        raw[start:start + c["NAME_LENGTH"]] = ot
        start = nicknames + slot * c["MON_NAME_LENGTH"]
        raw[start:start + c["MON_NAME_LENGTH"]] = nickname
    return bytes(raw)


def assert_record_equal(lua_record, python_record):
    # Check decoded semantics first so the red control cannot pass merely because
    # a raw-buffer digest/hex witness notices different bytes.
    lua_fields = {key: value for key, value in lua_record.items() if key != "raw_hex"}
    python_fields = {key: value for key, value in python_record.items() if key != "raw_hex"}
    assert lua_fields == python_fields, "decoded record fields differ"
    assert lua_record["raw_hex"] == python_record["raw_hex"], "raw record bytes differ"


def assert_collection_equal(lua_result, python_result, *, kind, metadata=None):
    left, right = dict(lua_result), dict(python_result)
    assert left.pop("snapshot_qualified") is False
    if kind != "party":
        assert right.pop("checksummed") is False
        assert left.pop("copy_length") == 1102
        if kind == "box":
            assert left.pop("padding_hex") == right["raw_hex"][-4:]
        else:
            assert "padding_hex" not in left
    for key, value in (metadata or {}).items():
        assert left.pop(key) == value, f"unexpected Lua qualification metadata: {key}"
    assert set(left) == set(right) == {"count", "mons", "raw_hex"}
    assert left["count"] == right["count"] == len(left["mons"]) == len(right["mons"])
    for lua_record, python_record in zip(left["mons"], right["mons"], strict=True):
        assert_record_equal(lua_record, python_record)
    assert left["raw_hex"] == right["raw_hex"]


def assert_refused(result, message):
    assert isinstance(result, tuple) and result[0] is None and message in result[1]


def test_party_box_transfer_records_names_and_eggs_agree(foundation):
    selected, layout = foundation
    world = ModelMemory(selected)
    assert world.reader.transfer_blob_size == 70
    for seed in range(6):
        raw = model_record(seed)
        marker = 253 if seed % 2 else raw[0]
        ot, nickname = model_names(seed)
        for kind, length, decode in (
            ("party", 48, codec.decode_party_mon), ("box", 32, codec.decode_box_mon),
        ):
            expected = decode(raw[:length], layout, species_marker=marker, ot=ot, nickname=nickname)
            actual = native(world.reader.decode_record(
                world.bytes(raw[:length]), kind, marker, world.bytes(ot), world.bytes(nickname),
            ))
            assert_record_equal(actual, expected)
            assert actual["is_egg"] is (marker == 253)
            assert actual["ot_raw_hex"] == ot.hex() and actual["nickname_raw_hex"] == nickname.hex()
            assert ("hp" in actual) is (kind == "party")
        blob = raw + ot + nickname
        assert len(blob) == 70
        assert_record_equal(
            native(world.reader.decode_transfer_blob(world.bytes(blob), marker)),
            codec.decode_party_blob(blob, layout, species_marker=marker),
        )
    assert world.calls == []  # Pure byte decoding did not read memory domains.


def test_dv_parity_and_pp_boundaries_agree(foundation):
    selected, layout = foundation
    world = ModelMemory(selected)
    for parity in range(16):
        dvs = sum((8 + ((parity >> (3 - nibble)) & 1)) << (12 - 4 * nibble) for nibble in range(4))
        raw = model_record(dv_word=dvs)
        expected = codec.decode_party_mon(raw, layout, species_marker=25)
        actual = native(world.reader.decode_record(world.bytes(raw), "party", 25))
        assert_record_equal(actual, expected)
        assert actual["dvs"]["hp"] == parity
    for packed in (0, 63, 64, 127, 128, 191, 192, 255):
        raw = model_record(pp=bytes([packed] * 4))
        expected = codec.decode_party_mon(raw, layout, species_marker=25)
        actual = native(world.reader.decode_record(world.bytes(raw), "party", 25))
        assert_record_equal(actual, expected)
        assert actual["pp"] == [packed & 63] * 4
        assert actual["pp_ups"] == [packed >> 6] * 4


def test_empty_mixed_and_full_collections_agree_without_qualification(foundation):
    selected, layout = foundation
    world = ModelMemory(selected)
    for kind, capacity, method in (
        ("party", 6, world.reader.decode_party_block),
        ("box", 20, world.reader.decode_box_block),
        ("active", 20, world.reader.decode_active_box_block),
    ):
        for count in (0, 2, capacity):
            raw = model_collection(selected, kind, count)
            expected = (codec.decode_party if kind == "party" else codec.decode_box)(raw, layout)
            assert_collection_equal(native(method(world.bytes(raw))), expected, kind=kind)


def test_injected_name_decoder_receives_complete_buffers(foundation):
    selected, layout = foundation
    calls_python, calls_lua = [], []

    def display(raw, calls):
        calls.append(raw)
        return "model-name:" + raw.hex()

    world = ModelMemory(selected, decode_name=lambda raw: display(raw, calls_lua))
    raw = model_record()
    ot, nickname = model_names()
    blob = raw + ot + nickname
    expected = codec.decode_party_blob(blob, layout, species_marker=253,
                                       name_decoder=lambda raw: display(raw, calls_python))
    actual = native(world.reader.decode_transfer_blob(world.bytes(blob), 253))
    assert_record_equal(actual, expected)
    assert calls_lua == calls_python == [ot, nickname]


def test_live_party_read_requires_stable_explicit_bank(foundation):
    selected, layout = foundation
    world = ModelMemory(selected)
    raw = model_collection(selected, "party", 2)
    world.put_party(raw)
    actual = native(world.reader.read_party())
    assert_collection_equal(actual, codec.decode_party(raw, layout), kind="party",
                            metadata={"ownership": "live_party_wram"})
    address = selected["ram"]["wPartyCount"]
    bank = selected["ram_bank"]["wPartyCount"]
    assert world.calls == [("System Bus", address, len(raw))]
    assert world.bank_calls == [(bank, address, len(raw))] * 2
    world.calls.clear()
    world.valid_bank = False
    assert_refused(world.reader.read_party(), "bank unavailable")
    assert world.calls == []
    world.valid_bank = True
    world.bank_answers = [True, False]
    assert_refused(world.reader.read_party(), "bank changed")


def test_all_backing_banks_and_active_shadow_match_offline_box_decode(foundation):
    selected, layout = foundation
    world = ModelMemory(selected)
    current = selected["ram"]["wCurBox"]
    world.bus[current] = 13
    active = model_collection(selected, "active", 2, seed=20)
    active_flat = world.put_box(active)
    for index, row in enumerate(selected["storage_boxes"]):
        raw = model_collection(selected, "box", 1, seed=index)
        flat = world.put_box(raw, index)
        assert (flat, len(raw)) == layout.storage_boxes[index]
        actual = native(world.reader.read_storage_box(index))
        assert_collection_equal(actual, codec.decode_box(raw, layout), kind="box", metadata={
            "ownership": "backing_sram_box", "bank": row["bank"], "address": row["addr"],
            "box_index": index, "is_current": index == 13,
            "active_shadow_authoritative": index == 13, "durable_save_verified": False,
        })
        assert ("CartRAM", flat, 1104) in world.calls
    actual = native(world.reader.read_active_box())
    assert_collection_equal(actual, codec.decode_box(active, layout), kind="active", metadata={
        "ownership": "active_sram_shadow", "bank": 1, "address": selected["ram"]["sBox"],
        "box_index": 13, "is_current": True,
        "active_shadow_authoritative": True, "durable_save_verified": False,
    })
    assert ("CartRAM", active_flat, 1102) in world.calls
    assert ("CartRAM", active_flat, 1104) not in world.calls
    assert selected["storage_boxes"][6]["bank"] == 2
    assert selected["storage_boxes"][7]["bank"] == 3
    assert layout.storage_boxes[13][0] == 0x79E0  # Source-pinned Box14, distinct from sBox.
    world.io.cart_ram_linear = False
    assert_refused(world.reader.read_storage_box(13), "linear CartRAM")


def test_bad_record_or_collection_refused_by_both(foundation):
    selected, layout = foundation
    world = ModelMemory(selected)
    raw = model_record()
    for bad, marker in ((raw[:-1], 25), (bytes([253]) + raw[1:], 253), (raw, 26)):
        with pytest.raises(ValueError):
            codec.decode_party_mon(bad, layout, species_marker=marker)
        result = world.reader.decode_record(world.bytes(bad), "party", marker)
        assert isinstance(result, tuple) and result[0] is None
    for kind, method in (("party", world.reader.decode_party_block), ("box", world.reader.decode_box_block)):
        raw = bytearray(model_collection(selected, kind, 2))
        raw[3] = 0  # Break the terminator following the two valid species markers.
        with pytest.raises(ValueError):
            (codec.decode_party if kind == "party" else codec.decode_box)(bytes(raw), layout)
        assert_refused(method(world.bytes(raw)), "terminator")


def test_unknown_egg_marker_cannot_be_inferred_from_record_alone(foundation):
    selected, layout = foundation
    world = ModelMemory(selected)
    raw = model_record()
    for kind, length, decode in (
        ("party", 48, codec.decode_party_mon), ("box", 32, codec.decode_box_mon),
    ):
        with pytest.raises(ValueError):
            decode(raw[:length], layout)
        assert_refused(world.reader.decode_record(world.bytes(raw[:length]), kind), "marker")
    ot, nickname = model_names()
    with pytest.raises(ValueError):
        codec.decode_party_blob(raw + ot + nickname, layout)
    assert_refused(world.reader.decode_transfer_blob(world.bytes(raw + ot + nickname)), "marker")


def test_invalid_record_levels_refused_by_both(foundation):
    selected, layout = foundation
    world = ModelMemory(selected)
    for level in (1, 100):
        raw = bytearray(model_record())
        raw[selected["constants"]["MON_LEVEL"]] = level
        for kind, length, decode in (
            ("party", 48, codec.decode_party_mon), ("box", 32, codec.decode_box_mon),
        ):
            expected = decode(bytes(raw[:length]), layout, species_marker=25)
            actual = native(world.reader.decode_record(world.bytes(raw[:length]), kind, 25))
            assert_record_equal(actual, expected)
    for level in (0, 101, 255):
        raw = bytearray(model_record())
        raw[selected["constants"]["MON_LEVEL"]] = level
        for kind, length, decode in (
            ("party", 48, codec.decode_party_mon), ("box", 32, codec.decode_box_mon),
        ):
            with pytest.raises(ValueError, match="level"):
                decode(bytes(raw[:length]), layout, species_marker=25)
            assert_refused(world.reader.decode_record(world.bytes(raw[:length]), kind, 25), "level")


def test_equality_oracle_rejects_one_valid_decoded_hp_divergence(foundation):
    selected, layout = foundation
    world = ModelMemory(selected)
    raw = model_collection(selected, "party", 2)
    world.put_party(raw)
    expected = codec.decode_party(raw, layout)
    positive = native(world.reader.read_party())
    metadata = {"ownership": "live_party_wram"}
    assert_collection_equal(positive, expected, kind="party", metadata=metadata)
    # Only the low HP byte seen by Lua changes: 300 -> 301 is still a valid
    # decoded value. Profiles, record species, dimensions and bank proofs pass.
    world.diverge = ("System Bus", selected["ram"]["wPartyMon1HP"] + 1)
    changed = native(world.reader.read_party())
    assert changed["mons"][0]["hp"] == positive["mons"][0]["hp"] + 1
    def fields(mon):
        return {key: value for key, value in mon.items() if key != "raw_hex"}

    restored = copy.deepcopy(changed["mons"][0])
    restored["hp"] = positive["mons"][0]["hp"]
    assert fields(restored) == fields(positive["mons"][0])
    with pytest.raises(AssertionError, match="decoded record fields differ"):
        assert_collection_equal(changed, expected, kind="party", metadata=metadata)
