"""Pin the staged route/event/animation data to actual RR; no game input here."""
import hashlib
import json
import struct

from tests.rr.reference.test_withdrawal_oracle import ROM_SHA256


def test_running_corridor_has_no_pinned_coordinate_script_or_warp(rr_repo, rr_rom_path):
    rom = rr_rom_path.read_bytes()
    assert hashlib.sha256(rom).hexdigest() == ROM_SHA256
    route = json.loads((rr_repo / "lua/tests/rr/viridian_west_running_route.json").read_text())

    def u32(address):
        return struct.unpack_from("<I", rom, address - 0x08000000)[0]

    group = u32(0x083526A8 + route["map_group"] * 4)
    header = u32(group + route["map_num"] * 4)
    assert u32(header) == route["layout"]
    assert u32(header + 4) == route["map_events"]
    assert u32(u32(route["layout"] + 16) + 20) == route["primary_attributes"]
    for index, word in enumerate(route["corridor_words"]):
        x = route["corridor_first_x"] + index
        assert 26 <= x <= 45 and word != 0x03FF and word >> 12 == 3 and (word >> 10) & 3 == 0
        metatile = word & 1023
        assert route["metatile_attributes"][str(metatile)] == 0
        assert u32(route["primary_attributes"] + metatile * 4) == 0
    for kind, stride in [("warp", 8), ("coord", 16)]:
        offset = route[kind + "_pointer"] - 0x08000000
        raw = rom[offset:offset + route[kind + "_count"] * stride]
        assert raw.hex() == route[kind + "_hex"]
        for index in range(route[kind + "_count"]):
            x, y = struct.unpack_from("<hh", raw, index * stride)
            assert y + 7 != route["row"] or not route["end_x"] <= x + 7 <= route["start_x"]
    # Real RR GetRunningDirectionAnimNum loads this table; left is direction3.
    assert rom[0x63520:0x6352C] == bytes.fromhex("0006000e0149401800787047")
    assert u32(0x0806352C) == 0x083A6493
    assert rom[0x3A6493 + 3] == route["running_animation_west"] == 22
