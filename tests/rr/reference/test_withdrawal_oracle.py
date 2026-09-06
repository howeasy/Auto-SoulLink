"""Pure formula tests and exact-ROM anchors; no native ARM execution or emulator."""

import hashlib
import json
import struct

import pytest
from lupa import LuaRuntime

ROM_SHA256 = "679d112cdfe699c2793d82c7e7999ac9dfca9e222ad5a85d4f8f1e457cd0283f"
BASE_STATS = 0x17B98EC
EXPERIENCE = 0x115514C
MOVES = 0x11521D0
NATURE = 0x252B48


@pytest.fixture(scope="module")
def oracle_rom(rr_rom_path):
    rom = rr_rom_path.read_bytes()
    assert hashlib.sha256(rom).hexdigest() == ROM_SHA256, "wrong RR base ROM"
    return rom


@pytest.fixture
def oracle(rr_repo):
    lua = LuaRuntime(encoding=None, unpack_returned_tuples=True)
    source = rr_repo / "lua/rr/withdrawal_oracle.lua"
    module = lua.execute(source.read_bytes(), name=b"@" + str(source).encode())
    return lua, module


def compressed(species=25, *, pid=1, exp=125000, ivs=(0, 1, 2, 3, 4, 5), evs=None):
    raw = bytearray(58)
    struct.pack_into("<II", raw, 0, pid, 222)
    raw[8:18] = bytes([0xBB] + [0xFF] * 9)
    raw[0x12] = 2
    struct.pack_into("<HHI", raw, 0x1C, species, 173, exp)
    raw[0x24] = 0xE4  # Move slots have PP-up counts 0,1,2,3.
    raw[0x25] = 70
    packed_moves = sum(move << (10 * index) for index, move in enumerate([0, 85, 120, 237]))
    raw[0x27:0x2C] = packed_moves.to_bytes(5, "little")
    raw[0x2C:0x32] = bytes(evs if evs is not None else [0, 4, 8, 12, 16, 20])
    raw[0x32:0x36] = bytes([0x41, 23, 12, 3])
    struct.pack_into("<I", raw, 0x36, sum(value << (5 * i) for i, value in enumerate(ivs)))
    return bytes(raw)


def evidence(lua, rom, raw):
    species = int.from_bytes(raw[0x1C:0x1E], "little")
    base = rom[BASE_STATS + species * 28 : BASE_STATS + (species + 1) * 28]
    growth = base[19]
    packed = int.from_bytes(raw[0x27:0x2C], "little")
    move_ids = [(packed >> (10 * i)) & 1023 for i in range(4)]
    return lua.table_from(
        {
            b"species_id": species,
            b"growth_rate": growth,
            b"base_stats": base,
            b"experience": rom[EXPERIENCE + growth * 1024 : EXPERIENCE + (growth + 1) * 1024],
            b"nature": rom[NATURE : NATURE + 125],
            b"move_pp": lua.table_from({move: rom[MOVES + move * 12 + 4] for move in move_ids}),
        }
    )


def context(lua, mgm):
    return lua.table_from(
        {b"mode": b"default", b"minimal_grinding": mgm, b"frontier_active": False}
    )


def independent_stats(rom, raw):
    """Separate arithmetic model using nature row/column rules, not Lua outputs."""
    species = struct.unpack_from("<H", raw, 0x1C)[0]
    base = rom[BASE_STATS + species * 28 : BASE_STATS + (species + 1) * 28]
    thresholds = struct.unpack_from("<256I", rom, EXPERIENCE + base[19] * 1024)
    exp = struct.unpack_from("<I", raw, 0x20)[0]
    level = next((candidate - 1 for candidate in range(1, 251) if thresholds[candidate] > exp), 250)
    ivs = struct.unpack_from("<I", raw, 0x36)[0]
    nature = struct.unpack_from("<I", raw, 0)[0] % 25
    result = []
    for stat in range(6):
        iv = (ivs // (32**stat)) % 32
        scaled = (2 * base[stat] + iv + raw[0x2C + stat] // 4) * level // 100
        value = scaled + (level + 10 if stat == 0 else 5)
        if stat == 0 and species == 303:
            value = 1
        elif stat and nature // 5 != nature % 5:
            if stat - 1 == nature // 5:
                value = ((value * 11) % 65536) // 10
            elif stat - 1 == nature % 5:
                value = ((value * 9) % 65536) // 10
        result.append(value)
    return level, result


def test_pinned_withdrawal_call_chain_and_reconstructed_fields(oracle_rom):
    # Each anchor was disassembled on the exact ROM; changed code fails this lane.
    anchors = {
        0x10B6A24: "10b50c0094b001006846fff779ff21006846024b00f01efc14b010bd75e70308",
        0x03E47C: "00490847fd880709",  # Stat calculator detour to090788FC.
        0x10B696A: "220080234632517a5b420b435372",  # Builder marks+4F bit7.
        0x10B69C6: "6b002a06e318988d120e074b317800f050fc2b0001353433e054042df0d1",
        0x10B69F0: "1d100408",  # PP callee0804101C.
        0x041026: "0d4c43001b189b001b191c79",  # move*12, PP byte+4.
        0x04105C: "d0211509a1de2508",  # moves and PP masks pointers.
        0x03E7F0: "c87c20256d0168430430801900689842",  # growth*1024.
        0x03E804: "0132fa2a07dc",  # scan limit250, not100.
        0x03E828: "4c511509ec987b09",  # EXP and BaseStats pointers.
        0x042EA6: "1921a1f1ecfb",  # Nature from PID modulo25.
        0x0436D4: "0b2002e0482b2508092058430004000c0a21",  # patched9/11 and /10.
    }
    # EV getters are raw byte loads followed by jumps; no MGM branch.
    for address, expected in anchors.items():
        expected_bytes = bytes.fromhex(expected)
        assert oracle_rom[address : address + len(expected_bytes)] == expected_bytes, hex(address)
    assert [oracle_rom[0x40074 + i * 4 : 0x40076 + i * 4].hex() for i in range(6)] == [
        "3c78",
        "7c78",
        "bc78",
        "fc78",
        "3c79",
        "7c79",
    ]
    # Native nature-table order matches the independent quotient/remainder rule.
    for nature in range(25):
        for stat in range(5):
            expected = (
                0
                if nature // 5 == nature % 5
                else 1
                if stat == nature // 5
                else 255
                if stat == nature % 5
                else 0
            )
            assert oracle_rom[NATURE + nature * 5 + stat] == expected


@pytest.mark.parametrize("mgm", [False, True])
def test_exact_golden_withdrawal_including_empty_move_pp(oracle, oracle_rom, mgm):
    lua, module = oracle
    raw = compressed()
    result = module.derive(raw, evidence(lua, oracle_rom, raw), context(lua, mgm))
    assert result[b"level"] == 50
    assert list(result[b"stats"].values()) == [95, 67, 42, 98, 59, 60]
    assert list(result[b"pp"].values()) == [35, 18, 7, 24]
    actual = result[b"party_bytes"]
    assert len(actual) == 100
    assert actual[:28] == raw[:28]
    assert actual[0x20:0x2B] == raw[0x1C:0x27]
    assert actual[0x38:0x3E] == raw[0x2C:0x32]
    assert actual[0x44:0x4C] == raw[0x32:0x3A]
    assert actual[0x1C:0x20] == bytes(4) and actual[0x2B] == 0
    assert actual[0x3E:0x44] == bytes(6) and actual[0x4C:0x50] == bytes([0, 0, 0, 128])
    assert actual[0x50:0x58] == bytes([0, 0, 0, 0, 50, 255, 95, 0])


@pytest.mark.parametrize("species", [25, 303, 1, 113, 1356, 1375])
def test_all_natures_and_level_boundaries_match_independent_math(oracle, oracle_rom, species):
    lua, module = oracle
    base = oracle_rom[BASE_STATS + species * 28 : BASE_STATS + (species + 1) * 28]
    growth = struct.unpack_from("<256I", oracle_rom, EXPERIENCE + base[19] * 1024)
    for nature in range(25):
        for level in [1, 2, 49, 50, 99, 100, 101, 250]:
            for exp in [growth[level] - 1, growth[level]]:
                raw = compressed(
                    species, pid=0xFFFFFFE1 + nature, exp=exp, ivs=(31,) * 6, evs=(255,) * 6
                )
                result = module.derive(raw, evidence(lua, oracle_rom, raw), context(lua, True))
                expected_level, expected_stats = independent_stats(oracle_rom, raw)
                assert result[b"level"] == expected_level
                assert list(result[b"stats"].values()) == expected_stats
                assert result[b"hp"] == expected_stats[0] == result[b"max_hp"]


def test_all_growth_rows_and_pp_bonus_bits(oracle, oracle_rom):
    lua, module = oracle
    species_by_growth = {}
    for species in range(1, 1376):
        base = oracle_rom[BASE_STATS + species * 28 : BASE_STATS + (species + 1) * 28]
        if base[0] and base[19] not in species_by_growth:
            species_by_growth[base[19]] = species
    assert set(species_by_growth) == set(range(6))
    for species in species_by_growth.values():
        for bonuses in range(256):
            raw = bytearray(compressed(species))
            raw[0x24] = bonuses
            raw = bytes(raw)
            result = module.derive(raw, evidence(lua, oracle_rom, raw), context(lua, False))
            expected_level, expected_stats = independent_stats(oracle_rom, raw)
            assert result[b"level"] == expected_level
            assert list(result[b"stats"].values()) == expected_stats
            assert list(result[b"pp"].values()) == [
                base + base * ((bonuses // (4**index)) % 4) // 5
                for index, base in enumerate([35, 15, 5, 15])
            ]


def test_item_ot_ability_parity_and_mgm_do_not_replace_stored_inputs(oracle, oracle_rom):
    lua, module = oracle
    raw = compressed()
    baseline = module.derive(raw, evidence(lua, oracle_rom, raw), context(lua, False))
    changed = bytearray(raw)
    struct.pack_into("<II", changed, 0, 26, 0xFFFFFFFF)  # Same nature; opposite PID parity.
    struct.pack_into("<H", changed, 0x1E, 255)
    changed[0x1B] = 255
    changed = bytes(changed)
    result = module.derive(changed, evidence(lua, oracle_rom, changed), context(lua, True))
    assert list(result[b"stats"].values()) == list(baseline[b"stats"].values())
    assert list(result[b"pp"].values()) == list(baseline[b"pp"].values())
    perfect = compressed(ivs=(31,) * 6, evs=(0,) * 6)
    perfect_result = module.derive(perfect, evidence(lua, oracle_rom, perfect), context(lua, True))
    assert list(result[b"stats"].values()) != list(perfect_result[b"stats"].values())


def test_observed_field_party_corroborates_stats_and_pp_only(oracle, oracle_rom, rr_repo):
    # Independently captured by root after actual Continue-to-field, frame1657.
    # This is not a withdrawal or native conversion gate and must stay labeled so.
    path = rr_repo / "tests/rr/reference/fixtures/field_party_08_a.json"
    fixture = json.loads(path.read_text())
    observed = bytes.fromhex(fixture["raw_hex"])
    assert hashlib.sha256(observed).hexdigest() == fixture["raw_sha256"]
    assert (
        fixture["source_result_sha256"]
        == "ea361ac601b2902b6de66f376e2abb91a8cffb79eefb80ca0d8b60629774fb60"
    )
    raw = bytearray(observed[:28] + observed[0x20:0x2B])
    moves = struct.unpack_from("<4H", observed, 0x2C)
    packed = sum(move << (10 * index) for index, move in enumerate(moves))
    raw.extend(packed.to_bytes(5, "little"))
    raw.extend(observed[0x38:0x3E])
    raw.extend(observed[0x44:0x4C])
    raw = bytes(raw)
    lua, module = oracle
    result = module.derive(raw, evidence(lua, oracle_rom, raw), context(lua, True))
    assert result[b"species_id"] == 277 and result[b"level"] == 6
    assert list(result[b"stats"].values()) == [22, 12, 12, 15, 14, 11]
    assert list(result[b"pp"].values()) == [35, 30, 25, 35]
    assert result[b"party_bytes"][0x50:] == observed[0x50:]
    assert result[b"party_bytes"][0x34:0x38] == observed[0x34:0x38]
    # The withdrawal builder adds this opaque marker; the observed field mon
    # lacks it. Never report full-byte equality or claim it was withdrawn.
    assert observed[0x4F] == 0 and result[b"party_bytes"][0x4F] == 128


@pytest.mark.parametrize(
    "invalid", ["mode", "frontier", "mgm_unknown", "species", "growth", "pp", "bad_egg"]
)
def test_unestablished_context_or_evidence_refuses_an_oracle(oracle, oracle_rom, invalid):
    lua, module = oracle
    raw = compressed()
    facts = evidence(lua, oracle_rom, raw)
    current = context(lua, False)
    if invalid == "mode":
        current[b"mode"] = b"hardcore"
    elif invalid == "frontier":
        current[b"frontier_active"] = True
    elif invalid == "mgm_unknown":
        current[b"minimal_grinding"] = None
    elif invalid == "species":
        facts[b"species_id"] = 1
    elif invalid == "growth":
        facts[b"growth_rate"] = 5
    elif invalid == "pp":
        facts[b"move_pp"][0] = None
    else:
        raw = raw[:0x13] + b"\x01" + raw[0x14:]
    result, reason = module.derive(raw, facts, current)
    assert result is None and reason
