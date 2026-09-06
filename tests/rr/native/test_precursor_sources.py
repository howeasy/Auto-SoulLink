"""Bounded RR wild-source domains and actual clock/override selection.

No campaign acquisition or taxonomy verdict. No game emulator or routine stubs.
"""
import hashlib
import json
import struct
from collections import Counter

import pytest
from unicorn import UC_HOOK_CODE

from tests.rr.native.test_regional_precursor_cpu import (
    ROM,
    STACK,
    PrecursorsCPU,
    pinned,  # noqa: F401
)

UNKNOWN = {1038, 1214, 1224}
METHODS = (("land", 12), ("water", 5), ("rock", 5), ("fish", 10))
DOMAINS = (
    ("legacy", 0x0872C984, 142, 2338, "37fdf482b90ab2030525773d6a677bdffc8dc3fb0b1a790d5d13a60b9b998cc2"),
    ("night_evening", 0x09166428, 83, 1403, "3365dca3c90137f0ceb61e0e501204791d7aa815b58fdc41c09a0f541294a6f4"),
    ("day", 0x09166AB8, 83, 1398, "ab91dcc319183d6ec9f1e85971b75b4daf0ca9e06c217e64bed53c3c772aff2f"),
)
LOADER, LEGACY_LOADER = 0x090C3550, 0x090C262C
NIGHT, EVENING, CLOCK_HOUR = 0x0908CC04, 0x0908CFDC, 0x03005EA6
WILD_OVERRIDE = 0x0203C758
LEGACY_TOWER = {
    90: (0x0872CC2C, 5, 0x083C7E08), 91: (0x0872CC40, 5, 0x083C7E40),
    92: (0x0872CC54, 5, 0x083C7E78), 93: (0x0872CC68, 3, 0x083C7EA8),
    94: (0x0872CC7C, 5, 0x083C7EE8),
}


def read(rom, address, length):
    assert ROM <= address < address + length <= ROM + len(rom), (hex(address), length)
    return rom[address - ROM:address - ROM + length]


def scan_headers(rom, address):
    """Walk header -> method info -> fixed-size slot records, retaining zero IDs.

    No species-name matching, suffix inference, level normalization or filtering.
    """
    headers, slots = [], []
    for index in range(512):
        header_address = address + index * 20
        raw = read(rom, header_address, 20)
        if raw[0] == 255:
            return headers, slots, header_address + 20
        group, number, padding, *infos = struct.unpack("<BBH4I", raw)
        assert padding == 0
        headers.append({"address": header_address, "map": (group, number), "infos": infos})
        for (method, count), info in zip(METHODS, infos, strict=True):
            if info == 0:
                continue
            assert info % 4 == 0
            rate, data = struct.unpack("<B3xI", read(rom, info, 8))
            assert data % 4 == 0
            entries = read(rom, data, count * 4)
            for slot, offset in enumerate(range(0, len(entries), 4)):
                minimum, maximum, species = struct.unpack_from("<BBH", entries, offset)
                assert 0 <= species <= 1375
                slots.append({"map": (group, number), "method": method, "slot": slot,
                              "minimum": minimum, "maximum": maximum, "species": species,
                              "address": data + offset, "info": info, "rate": rate})
    raise AssertionError("wild-header terminator not found within bounded walk")


def unique_header(headers, group, number):
    found = [row for row in headers if row["map"] == (group, number)]
    assert len(found) == 1
    return found[0]


def machine_for(rom, group, number, hour, override=0):
    machine = PrecursorsCPU(rom)
    machine.cpu.mem_write(0x03005008, struct.pack("<I", 0x02020000))
    machine.cpu.mem_write(0x02020004, bytes([group, number]))
    machine.cpu.mem_write(CLOCK_HOUR, bytes([hour]))
    machine.cpu.mem_write(WILD_OVERRIDE, struct.pack("<I", override))
    for entry in (LOADER, LEGACY_LOADER, NIGHT, EVENING):
        machine.cpu.hook_add(UC_HOOK_CODE, machine._entry, begin=entry, end=entry)
    return machine


def test_actual_loader_and_script_override_bindings(pinned):  # noqa: F811
    assert read(pinned, 0x08082990, 4) == struct.pack("<I", DOMAINS[0][1])
    assert read(pinned, 0x090C3600, 12) == struct.pack("<III", DOMAINS[1][1], 0x03005008, DOMAINS[2][1])
    for address, length, digest in (
        (LOADER, 188, "33b84bea16a0caea497fb2acbe6ec04d5b8411d05d3c141790258c15705fa062"),
        (LEGACY_LOADER, 196, "9e8deda127bcd9eab37e421b4541e4c0250a0e1d29bb9cc5e5d7cdec633f2661"),
        (NIGHT, 24, "c7f4533e58dfacbcaa22d52bdae028f8e4b43d25c2beae83b5e918e3e6a1476a"),
        (EVENING, 24, "a6fd5e0ce2b8dbc72f6da2cf87476bac47160fcf5dacfec0227c2e107f312ad0"),
    ):
        assert hashlib.sha256(read(pinned, address, length)).hexdigest() == digest
    assert read(pinned, 0x0908CC18, 4) == struct.pack("<I", CLOCK_HOUR - 6)
    assert read(pinned, 0x090003C4, 18) == bytes.fromhex("02b4714649084900095c49008e4402bc7047")
    # Actual StandardWildEncounter detour and its land-data call.
    assert read(pinned, 0x08082CBC, 8) == bytes.fromhex("004a10475f380c09")
    assert read(pinned, 0x090C389E, 6) == bytes.fromhex("0020fff756fe")
    # Override set/cancel functions and their actual function-table entries.
    assert read(pinned, 0x090BA950, 20) == bytes.fromhex("024b1a68024b1a607047c046140f000358c70302")
    assert read(pinned, 0x090BA964, 12) == bytes.fromhex("0022014b1a60704758c70302")
    assert read(pinned, 0x0815FEC8, 8) == struct.pack("<II", 0x090BA951, 0x090BA965)
    # Generic gift/egg constructors are present; their campaign argument domains
    # are not established by these bindings.
    assert read(pinned, 0x080A011C, 8) == bytes.fromhex("004b18477d760709")
    assert read(pinned, 0x08046150, 8) == bytes.fromhex("004a10479d780809")
    assert read(pinned, 0x090777F8, 4) == struct.pack("<I", 0x0803DA55)
    assert read(pinned, 0x09087A0C, 4) == struct.pack("<I", 0x0803DA55)


@pytest.mark.parametrize("name,address,count,slot_count,digest", DOMAINS, ids=[row[0] for row in DOMAINS])
def test_structural_wild_domains_retain_legacy_counterexamples(pinned, name, address, count, slot_count, digest):  # noqa: F811
    headers, slots, end = scan_headers(pinned, address)
    assert len(headers) == count and len(slots) == slot_count
    assert hashlib.sha256(read(pinned, address, end - address)).hexdigest() == digest
    hits = [row for row in slots if row["species"] in UNKNOWN]
    if name == "legacy":
        assert [(row["map"], row["slot"], row["species"], row["address"]) for row in hits] == [
            ((1, number), slot, 1038, slot_address) for number, (_, slot, slot_address) in LEGACY_TOWER.items()]
        assert Counter(row["species"] for row in slots)[109] == 1  # Normal Koffing control.
    else:
        assert hits == []
        assert Counter(row["species"] for row in slots)[104] == (6 if name == "night_evening" else 5)
    for number in LEGACY_TOWER:
        assert unique_header(headers, 1, number)["infos"][0] != 0


@pytest.mark.parametrize("number", range(90, 95), ids=lambda value: "tower_map_1_" + str(value))
def test_actual_all_hours_select_current_tower_data_without_override(pinned, number, record_property):  # noqa: F811
    current = {name: unique_header(scan_headers(pinned, address)[0], 1, number)
               for name, address, *_ in DOMAINS[1:]}
    observations = []
    for hour in range(24):
        machine = machine_for(pinned, 1, number, hour)
        info = machine.call(LOADER, 0)  # Actual LAND_MONS_HEADER selector.
        mode = "day" if 4 <= hour <= 16 else "night_evening"
        assert info == current[mode]["infos"][0]
        entries = {LOADER, NIGHT} | ({EVENING} if 4 <= hour <= 19 else set())
        assert machine.entries == entries  # No legacy fallback call was executed.
        assert machine.writes == {(STACK - offset, 4) for offset in (4, 8, 12, 16, 20)}
        outside = {(a, n) for a, n in machine.reads if not ROM <= a < ROM + len(pinned) and not STACK - 20 <= a < STACK}
        assert outside == {(0x02020004, 1), (0x02020005, 1), (WILD_OVERRIDE, 4), (0x03005008, 4), (CLOCK_HOUR, 1)}
        slot_pointer = struct.unpack("<I", read(pinned, info + 4, 4))[0]
        species = [struct.unpack("<H", read(pinned, slot_pointer + i * 4 + 2, 2))[0] for i in range(12)]
        assert species[5] == 104 and not UNKNOWN.intersection(species)
        assert bytes(machine.cpu.mem_read(WILD_OVERRIDE, 4)) == bytes(4)
        observations.append({"hour": hour, "info": hex(info), "species": species})
    record_property("classification", "actual_clock_loader_with_null_override_not_campaign_acquisition")
    record_property("rom_sha256", hashlib.sha256(pinned).hexdigest())
    record_property("hours", json.dumps(observations))


def test_explicit_override_can_select_legacy_precursor_data_but_is_not_acquisition(pinned):  # noqa: F811
    header, slot, address = LEGACY_TOWER[90]
    expected_info = struct.unpack("<I", read(pinned, header + 4, 4))[0]
    machine = machine_for(pinned, 1, 90, 12, override=header)
    assert machine.call(LOADER, 0) == expected_info
    assert machine.entries == {LOADER}  # Override bypasses both clock predicates.
    data = struct.unpack("<I", read(pinned, expected_info + 4, 4))[0]
    assert data + slot * 4 == address
    assert struct.unpack("<H", read(pinned, address + 2, 2))[0] == 1038
    assert machine.writes == {(STACK - offset, 4) for offset in (4, 8, 12, 16, 20)}
    assert bytes(machine.cpu.mem_read(WILD_OVERRIDE, 4)) == struct.pack("<I", header)
