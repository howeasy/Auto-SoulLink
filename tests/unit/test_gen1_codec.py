"""Independent pret-offset vectors and game checksum qualification for CODEC-1.

Pret citations refer to the revisions pinned in server.adapters.gen1_codec.
Fixtures qualify only the populated/initialized data actually present; synthetic
images exercise saved boxes even when town saves predate their initialization.
"""

import random
from pathlib import Path

import pytest

from server.adapters import gen1_codec as codec


@pytest.fixture(autouse=True)
def isolate_data_dir():
    """Override the repository's disk-creating fixture: this pure suite writes no state."""
    yield


# constants/pokemon_data_constants.asm:28-56; macros/ram.asm:7-36.
# All field values are independent test inputs, not copied decoder output.
MON = bytes.fromhex(
    "99"          # +00 internal species; dex_order.asm:155 = Bulbasaur
    "1234"        # +01 current HP (big endian)
    "07"          # +03 box level (deliberately different from party level)
    "08"          # +04 status
    "16 03"       # +05 types
    "C8"          # +07 catch rate
    "01 21 55 A5" # +08 moves
    "BEEF"        # +12 OT ID
    "012345"      # +14 24-bit exp
    "0000 0010 1234 4000 FFFF"  # +17 five stat-exp words
    "ABCD"        # +27 DVs
    "00 7F 85 FF" # +29 PP bytes
    "2A"          # +33 party level
    "0123 0234 0345 0456 0567"  # +34 five stored stats
)


def test_hand_placed_party_and_box_fields():
    mon = codec.decode_party_mon(MON)
    assert mon == {
        "box": False, "species": 0x99, "hp": 0x1234, "box_level": 7,
        "status": 8, "types": [0x16, 3], "catch_rate": 200,
        "moves": [1, 0x21, 0x55, 0xA5], "ot_id": 0xBEEF, "exp": 0x012345,
        "stat_exp": {"hp": 0, "atk": 16, "def": 0x1234, "spd": 0x4000, "spc": 65535},
        # home/move_mon.asm:109-153: A/B/C/D nibbles, HP=(0<<3)|(1<<2)|(0<<1)|1.
        "dvs": {"raw": 0xABCD, "atk": 10, "def": 11, "spd": 12, "spc": 13, "hp": 5},
        # constants/pokemon_data_constants.asm:100-102: high two bits are PP Ups.
        "pp": [0, 63, 5, 63], "pp_ups": [0, 1, 2, 3], "level": 42,
        "max_hp": 0x123, "atk": 0x234, "def": 0x345, "spd": 0x456, "spc": 0x567,
    }
    assert codec.encode_party_mon(mon) == MON
    assert codec.key(mon) == "ABCD:BEEF:99"
    box = codec.decode_party_mon(MON[:33], box=True)
    assert box["level"] == box["box_level"] == 7
    assert all(box[s] is None for s in ("max_hp", "atk", "def", "spd", "spc"))
    assert codec.encode_party_mon(box) == MON[:33]


@pytest.mark.parametrize("box,size", [(False, 44), (True, 33)])
def test_round_trip_arbitrary_raw_bytes(box, size):
    # Deterministic property sample includes every byte value at every position,
    # plus random records; no assumption that the raw data is a legal Pokemon.
    rng = random.Random(2369)
    records = [bytes([value]) * size for value in range(256)]
    records += [rng.randbytes(size) for _ in range(2000)]
    for raw in records:
        assert codec.encode_party_mon(codec.decode_party_mon(raw, box=box)) == raw


def test_encoder_rejects_contradictions_and_overflow():
    mon = codec.decode_party_mon(MON)
    mon["dvs"]["hp"] = 0
    with pytest.raises(ValueError, match="DV nibbles"):
        codec.encode_party_mon(mon)
    mon = codec.decode_party_mon(MON)
    mon["pp"][0] = 64
    with pytest.raises(ValueError, match="pp"):
        codec.encode_party_mon(mon)
    mon = codec.decode_party_mon(MON)
    mon["exp"] = 0x1000000
    with pytest.raises(ValueError, match="exp"):
        codec.encode_party_mon(mon)
    mon = codec.decode_party_mon(MON[:33], box=True)
    mon["level"] += 1
    with pytest.raises(ValueError, match="box level"):
        codec.encode_party_mon(mon)


@pytest.mark.parametrize("size,box", [(0, False), (43, False), (45, False), (32, True), (34, True)])
def test_struct_length_is_exact(size, box):
    with pytest.raises(ValueError, match="exactly"):
        codec.decode_party_mon(bytes(size), box=box)


def test_names_preserve_spaces_terminator_tokens_and_genderless_names():
    # constants/charmap.asm:12,63,92,105,153,161-162,179,185.
    assert codec.decode_name(bytes.fromhex("80 7F BA E1 E2 50 EF F5")) == "A é<PK><MN>"
    assert codec.encode_name("A é<PK><MN>") == bytes.fromhex("80 7F BA E1 E2") + b"\x50" * 6
    assert codec.decode_name(codec.encode_name("NIDORAN")) == "NIDORAN"
    assert codec.decode_name(codec.encode_name("NIDORAN♂")) == "NIDORAN♂"
    assert codec.decode_name(codec.encode_name("NIDORAN♀")) == "NIDORAN♀"
    assert codec.decode_name(codec.encode_name(" A ")) == " A "
    assert codec.encode_name("A@discarded") == b"\x80" + b"\x50" * 10
    assert codec.decode_name(b"\x50" * 11) == ""
    # constants/charmap.asm:154-165: contractions are ONE glyph each.
    assert codec.encode_name("'d'l's't'v'r'm")[:7] == bytes.fromhex("BB BC BD BE BF E4 E5")
    assert codec.decode_name(b"\x01\x50") == "<$01>"
    assert codec.encode_name("<$01>") == b"\x01" + b"\x50" * 10
    assert codec.decode_name(codec.encode_name("ABCDEFGHIJ")) == "ABCDEFGHIJ"
    with pytest.raises(ValueError, match="ten glyphs"):
        codec.encode_name("ABCDEFGHIJK")
    with pytest.raises(ValueError, match="unsupported"):
        codec.encode_name("🙂")
    with pytest.raises(ValueError, match="exceeds"):
        codec.decode_name(b"\x80" * 12)


@pytest.mark.parametrize("box", [False, True])
def test_collection_offsets_and_validation(box):
    # ram/wram.asm:1722-1744,2226-2248; Yellow:1903-1925,2491-2513.
    size, capacity, stride, mons, ots, nicks = (
        (1122, 20, 33, 22, 682, 902) if box else (404, 6, 44, 8, 272, 338)
    )
    decode = codec.decode_box if box else codec.decode_party
    b = bytearray(size)
    b[0] = capacity
    b[1:1 + capacity] = b"\x99" * capacity
    b[1 + capacity] = 255
    for slot in range(capacity):
        start = mons + slot * stride
        b[start:start + stride] = MON[:stride]
        b[ots + slot * 11:ots + (slot + 1) * 11] = codec.encode_name(f"OT{slot}")
        b[nicks + slot * 11:nicks + (slot + 1) * 11] = codec.encode_name(f"MON{slot}")
    decoded = decode(bytes(b))
    assert len(decoded) == capacity
    for slot, mon in enumerate(decoded):
        assert mon["ot_name"] == f"OT{slot}"
        assert mon["nickname"] == f"MON{slot}"
        assert mon["species_list_entry"] == 153
        assert mon["nickname_bytes"] == codec.encode_name(f"MON{slot}")
        assert codec.encode_party_mon(mon) == MON[:stride]
    with pytest.raises(ValueError, match="exactly"):
        decode(bytes(b[:-1]))
    b[1 + capacity] = 0
    with pytest.raises(ValueError, match="terminator"):
        decode(bytes(b))
    b[1 + capacity] = 255
    b[1] = 1
    with pytest.raises(ValueError, match="species-list mismatch"):
        decode(bytes(b))
    b[0] = capacity + 1
    with pytest.raises(ValueError, match="capacity"):
        decode(bytes(b))
    b[0], b[1] = 0, 255
    assert decode(bytes(b)) == []


@pytest.mark.parametrize("raw,expected", [
    (b"", 255), (b"\x00", 255), (b"\x01", 254), (b"\xff", 0),
    (b"\xff\x01", 255),  # sum 256 -> 0 mod 256 -> complement FF
    (b"\x01\x02\x03", 249),  # 1+2+3=6 -> FF-6=F9
    (bytes(range(256)), 127),  # 255*256/2=32640 -> 128 -> complement 127
])
def test_hand_checksum_vectors(raw, expected):
    # engine/menus/save.asm:297-310, not a host/emulator checksum.
    assert codec.sav_checksum(raw) == expected


def _synthetic_sram():
    # ram/sram.asm:14-24,37-49; layout.link:197-202; see codec SRAM_LAYOUT citations.
    b = bytearray(32768)
    b[0x284C] = 128  # ram/wram.asm:1897-1899: has changed boxes
    b[0x3523] = 127  # only nonzero byte in main range is 128; complement = 127
    for offset in (0x5A4C, 0x7A4C):
        b[offset:offset + 7] = b"\xff" * 7  # zero bank -> all checksums 255
    # First bank's first box sum=1; second bank's last box sum=2.
    b[0x4000], b[0x6000 + 5 * 1122] = 1, 2
    b[0x5A4C], b[0x5A4D] = 254, 254
    b[0x7A4C], b[0x7A4D + 5] = 253, 253
    return b


def test_checksum_ranges_and_individual_box_boundaries():
    b = _synthetic_sram()
    assert codec.verify_bank1(b)
    report = codec.verify_boxes(b)
    assert report["initialized"]
    assert all(v["valid"] for v in report["boxes"].values())
    assert all(v["valid"] for v in report["banks"].values())
    assert [i for i, v in report["boxes"].items() if v["populated"]] == [1, 12]
    # Endpoints from ram/sram.asm:16-24: the animations byte IS included.
    for offset in (0x2598, 0x25A3, 0x2D2C, 0x2F2C, 0x30C0, 0x3522, 0x3523):
        changed = b.copy()
        changed[offset] ^= 1
        assert not codec.verify_bank1(changed), hex(offset)
    for offset in (0x2597, 0x3524, 0x4000, 0x7FFF):
        changed = b.copy()
        changed[offset] ^= 1
        assert codec.verify_bank1(changed), hex(offset)
    # Checksum includes unused bytes at the very END of the last box too.
    b[0x7A4B] ^= 1
    broken = codec.verify_boxes(b)
    assert [i for i, v in broken["boxes"].items() if not v["valid"]] == [12]
    assert broken["banks"][2]["valid"] and not broken["banks"][3]["valid"]
    b = _synthetic_sram()
    b[0x5A4D + 2] ^= 1
    broken = codec.verify_boxes(b)
    assert [i for i, v in broken["boxes"].items() if not v["valid"]] == [3]
    assert all(v["valid"] for v in broken["banks"].values())


def test_erased_banks_are_not_reported_as_verified():
    b = bytearray(b"\xff" * 32768)
    b[0x284C] = 0
    # engine/menus/save.asm:365-367,529-565: banks are initialized on first change.
    report = codec.verify_boxes(b)
    assert not report["initialized"]
    assert all(v["populated"] is None for v in report["boxes"].values())
    assert all(not v["valid"] for v in report["boxes"].values())
    assert not codec.verify_bank1(b[:-1])
    with pytest.raises(ValueError, match="SRAM"):
        codec.verify_boxes(b[:-1])


def test_town_battery_save_qualification():
    """One fixture oracle over all R/B/Y; absence is the only permitted skip."""
    root = Path(__file__).resolve().parents[1] / "fixtures" / "gen1"
    files = [root / f"{title}_town.SaveRAM" for title in ("red", "blue", "yellow")]
    absent = [str(path) for path in files if not path.is_file()]
    if absent:
        pytest.skip("Gen 1 32 KiB battery saves absent: " + ", ".join(absent))
    for path in files:
        b = path.read_bytes()
        assert len(b) == 32768, path.name
        assert codec.verify_bank1(b), f"{path.name}: game's main checksum failed"
        report = codec.verify_boxes(b)
        if report["initialized"]:
            for number, box in report["boxes"].items():
                assert box["count"] <= 20, (path.name, number, box)
                if box["populated"]:
                    assert box["valid"], (path.name, number, box)
        else:
            assert all(box["populated"] is None for box in report["boxes"].values())
        # Active-box bytes are included in the main checksum, with no extra checksum.
        # ram/sram.asm:21; engine/menus/save.asm:281-284,365-387.
        assert b[0x30C0] <= 20, f"{path.name}: invalid active box count"


def test_three_published_pret_species_stat_examples():
    # Published base values: data/pokemon/base_stats/pikachu.asm:3,
    # bulbasaur.asm:3, mewtwo.asm:3; formula home/move_mon.asm:73-226.
    # Pikachu HP, level 50, DV 15, exp 65535: ceil sqrt=256 capped=255;
    # floor(((35+15)*2 + floor(255/4))*50/100)+50+10 = floor(163/2)+60 = 141.
    assert codec.calc_stat(35, 15, 65535, 50, hp=True) == 141
    # Bulbasaur attack, level 5, DV 0, exp 0:
    # floor(((49+0)*2 + 0)*5/100)+5 = floor(4.9)+5 = 9.
    assert codec.calc_stat(49, 0, 0, 5) == 9
    # Mewtwo special, level 100, DV 15, exp 65535:
    # ((154+15)*2 + floor(255/4))*100/100 + 5 = 338+63+5 = 406.
    assert codec.calc_stat(154, 15, 65535, 100) == 406


def test_stat_sqrt_boundary_cap_and_scanner_compatible_control():
    # home/move_mon.asm:73-92: 10 needs ceil sqrt=4, not floor sqrt=3.
    assert codec.calc_stat(35, 0, 9, 100) == 75
    assert codec.calc_stat(35, 0, 10, 100) == 76
    assert codec.calc_stat(255, 15, 65535, 255, hp=True) == 999
    # All five independent Bulbasaur base values from base_stats/bulbasaur.asm:3.
    # A/D/S/S DV=0 gives HP DV=0; no stat exp, level 5.
    b = bytearray(44)
    b[0], b[3], b[33] = 153, 5, 5
    # floor(2*base*5/100) + (15 for HP, 5 otherwise).
    expected = {"max_hp": 19, "atk": 9, "def": 9, "spd": 9, "spc": 11}
    for offset, value in zip((34, 36, 38, 40, 42), expected.values(), strict=True):
        b[offset:offset + 2] = value.to_bytes(2, "big")
    mon = codec.decode_party_mon(b)
    base = {"hp": 45, "attack": 49, "defense": 49, "speed": 45, "special": 65}
    assert codec.recompute_stats(mon, base) == expected
    assert all(mon[name] == value for name, value in codec.recompute_stats(mon, base).items())


@pytest.mark.parametrize("rate,at10,at100", [
    # data/growth_rates.asm:15-20: direct polynomial arithmetic at n=10 and n=100.
    (0, 1000, 1000000), (1, 1720, 849970), (2, 2680, 949930),
    (3, 560, 1059860), (4, 800, 800000), (5, 1250, 1250000),
])
def test_growth_tables_and_thresholds(rate, at10, at100):
    # Medium-slow at 100: 1200000 - 150000 + 10000 - 140 = 1059860.
    assert codec.exp_for_level(rate, 10) == at10
    assert codec.exp_for_level(rate, 100) == at100
    assert codec.level_from_exp(rate, at10 - 1) == 9
    assert codec.level_from_exp(rate, at10) == 10
    assert codec.level_from_exp(rate, at100) == 100
    assert codec.level_from_exp(rate, 0) == 1
    for level in range(2, 101):
        assert codec.level_from_exp(rate, codec.exp_for_level(rate, level)) == level


def test_growth_truncation_underflow_and_overlevel():
    # engine/pokemon/experience.asm:39-58,80-136: 6*27//5 - 15*9 + 300-140 = 57.
    assert codec.exp_for_level(3, 3) == 57
    assert codec.exp_for_level(3, 1) == 0xFFFFCA  # 1 - 15 + 100 - 140 = -54 mod 2^24
    assert codec.level_from_exp(0, 101**3) == 101  # engine/pokemon/experience.asm:6-27
    with pytest.raises(ValueError, match="wrap"):
        codec.level_from_exp(0, 0xFFFFFF)
    with pytest.raises(ValueError, match="growth_rate"):
        codec.level_from_exp(6, 0)


def test_complete_dex_bijection_and_holes():
    # data/pokemon/dex_order.asm:3,23,33,155,178,192.
    assert codec.internal_to_natdex(1) == 112
    assert codec.internal_to_natdex(21) == 151
    assert codec.internal_to_natdex(31) == 0
    assert codec.internal_to_natdex(153) == 1
    assert codec.internal_to_natdex(176) == 4
    assert codec.internal_to_natdex(190) == 71
    mapped = [codec.internal_to_natdex(i) for i in range(1, 191)]
    assert sorted(d for d in mapped if d) == list(range(1, 152))
    assert mapped.count(0) == 39
    for dex in range(1, 152):
        assert codec.internal_to_natdex(codec.natdex_to_internal(dex)) == dex
    for invalid in (0, 191, -1, True):
        with pytest.raises(ValueError):
            codec.internal_to_natdex(invalid)
    for invalid in (0, 152, -1, True):
        with pytest.raises(ValueError):
            codec.natdex_to_internal(invalid)


def test_species_zero_inside_the_count_is_refused():
    """A 0 species byte within the count is a torn list, never a Pokemon (same rule as Lua)."""
    mon = codec.decode_party_mon(bytes(44))
    mon["species"] = 0
    body = bytearray(codec.PARTY_LAYOUT["size"])
    body[codec.PARTY_LAYOUT["count"]] = 1
    body[codec.PARTY_LAYOUT["species"]] = 0
    body[codec.PARTY_LAYOUT["species"] + 1] = codec.SPECIES_END
    body[codec.PARTY_LAYOUT["mons"]:codec.PARTY_LAYOUT["mons"] + 44] = codec.encode_party_mon(mon)
    with pytest.raises(ValueError, match="species 0 inside the count"):
        codec.decode_party(bytes(body))


def _synthetic_bag(pairs, count=None):
    b = bytearray(32768)
    b[codec._BAG_COUNT] = len(pairs) if count is None else count
    offset = codec._BAG_COUNT + 1
    for item_id, qty in pairs:
        b[offset], b[offset + 1] = item_id, qty
        offset += 2
    b[offset] = 0xFF
    return bytes(b)


def test_decode_bag_reads_counted_pairs():
    sram = _synthetic_bag([(0x04, 5), (0x46, 1)])
    assert codec.decode_bag(sram) == [(0x04, 5), (0x46, 1)]
    assert codec.bag_quantity(sram, codec.POKE_BALL) == 5


def test_bag_quantity_absent_item_is_zero():
    sram = _synthetic_bag([(0x04, 5), (0x46, 1)])
    assert codec.bag_quantity(sram, 0x01) == 0


def test_decode_bag_stops_at_terminator_before_declared_count():
    # Declared count says 3, but $FF lands right after the first pair.
    sram = _synthetic_bag([(0x04, 5)], count=3)
    assert codec.decode_bag(sram) == [(0x04, 5)]


def test_decode_bag_real_battle_fixture():
    """docs/historical/gen1_resume.md: this scripted-play save holds exactly one Poke Ball."""
    path = Path(__file__).resolve().parents[1] / "fixtures" / "gen1" / "red_battle.SaveRAM"
    if not path.is_file():
        pytest.skip(f"Gen 1 battle save absent: {path}")
    sram = path.read_bytes()
    bag = codec.decode_bag(sram)
    assert bag, "expected a non-empty bag"
    assert all(isinstance(i, int) and isinstance(q, int) and 0 <= i <= 0xFE and 0 <= q <= 0xFF
               for i, q in bag)
    assert codec.bag_quantity(sram, codec.POKE_BALL) == 1
    OAKS_PARCEL = 0x46  # lua/tests/gen1_rb_point_fields.lua:6
    assert codec.bag_quantity(sram, OAKS_PARCEL) == 0, "parcel already delivered before this save"


def test_decode_bag_real_town_fixture():
    path = Path(__file__).resolve().parents[1] / "fixtures" / "gen1" / "red_town.SaveRAM"
    if not path.is_file():
        pytest.skip(f"Gen 1 town save absent: {path}")
    bag = codec.decode_bag(path.read_bytes())
    assert all(isinstance(i, int) and isinstance(q, int) and 0 <= i <= 0xFE and 0 <= q <= 0xFF
               for i, q in bag)
