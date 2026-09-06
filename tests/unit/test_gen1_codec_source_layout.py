"""The codec's offsets must decode records assembled using pret's symbol offsets."""
import json
from pathlib import Path

import pytest
from lupa import LuaRuntime

from server.gen1_party_codec import PartyCodec

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("variant,source", [("red", "pokered"), ("blue", "pokered"), ("yellow", "pokeyellow")])
def test_codec_layout_is_anchored_to_canonical_structure_symbols(variant, source):
    symbols = json.loads((ROOT / "data/pret_syms.json").read_text())[source]
    base = symbols["wPartyMon1"]
    length = symbols["wPartyMon2"] - base
    name_length = symbols["wPartyMon2OT"] - symbols["wPartyMon1OT"]
    raw = bytearray(length + 2 * name_length)

    def field(name, value, size=1):
        offset = symbols["wPartyMon1" + name] - base
        data = value if isinstance(value, bytes) else value.to_bytes(size, "big")
        raw[offset:offset + len(data)] = data

    for name, value in (("Species", 153), ("BoxLevel", 0), ("Status", 64),
                        ("Type1", 22), ("Type2", 3), ("CatchRate", 45), ("Level", 5)):
        field(name, value)
    field("HP", 10, 2)
    field("Moves", bytes((1, 2, 3, 4)))
    field("PP", bytes((248, 25, 0, 0)))
    field("OTID", 0x1234, 2)
    field("DVs", 0x9876, 2)
    field("Exp", 135, 3)  # canonical medium-slow level5 threshold
    for name, value in zip(("HPExp", "AttackExp", "DefenseExp", "SpeedExp", "SpecialExp"),
                            (1, 255, 256, 65024, 65535), strict=True):
        field(name, value, 2)
    for name, value in zip(("MaxHP", "Attack", "Defense", "Speed", "Special"),
                            (20, 11, 12, 13, 14), strict=True):
        field(name, value, 2)
    raw[length:length + name_length] = bytes((0x91, 0x50)) + bytes(name_length - 2)
    raw[length + name_length:] = bytes((0x92, 0x50)) + bytes(name_length - 2)

    python = PartyCodec(variant).validate_blob(raw, expected_key="9876:1234:99")
    assert python.species_id == 1 and python.hp == 10 and python.status == 64
    assert python.experience == 135 and python.stat_experience == (1, 255, 256, 65024, 65535)
    assert python.computed_stats == (20, 11, 12, 13, 14)
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.globals().SLINK_ROOT = ROOT.as_posix()
    codec = lua.execute((ROOT / "lua/gen1_party_codec.lua").read_text())
    result = codec.validateBlob(lua.table_from(list(raw)), variant, "9876:1234:99")
    assert not isinstance(result, tuple), result
    assert result.hp == python.hp and result.experience == python.experience
    assert tuple(result.stat_experience.values()) == python.stat_experience
    assert tuple(result.computed_stats.values()) == python.computed_stats
    assert bytes(result.blob.values()) == bytes(raw)
