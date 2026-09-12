"""Compare both codec implementations on canonical facts and hostile whole blobs."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from lupa import LuaRuntime

from server.gen1_party_codec import PartyCodec, PartyCodecError
from tools.gen_gen1_codec_data import build_tables, outputs

ROOT = Path(__file__).resolve().parents[2]
DATA = json.loads((ROOT / "data/games/gen1_rby/party_codec.json").read_text())


def make_blob(codec, species=153, level=5, otid=0x1234, dv=0x9876):
    """A legal record with distinctive padding, PP-Up bits, and immutable raw bytes."""
    facts = codec.profile["species"][str(species)]
    raw = bytearray(66)
    raw[0] = species
    raw[1:3] = (10).to_bytes(2, "big")
    raw[3] = 0  # canonical AddPartyMon starts BoxLevel at zero
    raw[5:7] = bytes(facts["types"])
    raw[7] = 45
    raw[8:12] = bytes((1, 2, 0, 0))
    raw[12:14] = otid.to_bytes(2, "big")
    xp = codec.experience_for_level(facts["growth_rate"], level) if level > 1 else 0
    raw[14:17] = xp.to_bytes(3, "big")
    raw[17:27] = bytes.fromhex("000100ff0100fe00ffff")
    raw[27:29] = dv.to_bytes(2, "big")
    raw[29:33] = bytes((0xC0 | codec.max_pp(1, 3), codec.max_pp(2, 0), 0, 0))
    raw[33] = level
    # Legal cached stats need not equal a fresh CalcStats result after stat-exp growth.
    for offset, value in zip(range(34, 44, 2), (20, 11, 12, 13, 14), strict=True):
        raw[offset:offset + 2] = value.to_bytes(2, "big")
    raw[44:55] = bytes((0x91, 0x84, 0x83, 0x50, 0, 0x51, 0xA5, 0xFF, 2, 3, 4))
    raw[55:66] = bytes((0x85, 0x88, 0x92, 0x87, 0x50, 0x52, 0, 0xFF, 6, 7, 8))
    return bytes(raw)


@pytest.fixture(scope="module")
def lua_codec():
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.globals().SLINK_ROOT = ROOT.as_posix()
    module = lua.execute((ROOT / "lua/gen1_party_codec.lua").read_text())
    return lua, module


def lua_result(runtime, raw, variant="red", key=None):
    lua, module = runtime
    value = lua.table_from(list(raw)) if isinstance(raw, (bytes, bytearray, list, tuple)) else raw
    result = module.validateBlob(value, variant, key)
    return result if isinstance(result, tuple) else (result, None)


def test_generated_facts_reproduce_from_all_three_canonical_builds():
    for path, content in outputs(build_tables()).items():
        assert path.read_text(encoding="utf-8") == content


@pytest.mark.parametrize("variant", ["red", "blue", "yellow"])
def test_all_canonical_species_at_level_boundaries_agree_between_codecs(lua_codec, variant):
    codec = PartyCodec(variant)
    checked = 0
    for species in codec.profile["species"]:
        for level in (1, 5, 50, 100):
            raw = make_blob(codec, int(species), level)
            python = codec.validate_blob(raw)
            lua, error = lua_result(lua_codec, raw, variant)
            assert lua is not None, error
            assert lua.key == python.key
            assert lua.species_id == python.species_id
            assert lua.level == python.level
            assert bytes(lua.blob.values()) == raw
            assert tuple(lua.pp.values()) == python.pp
            assert tuple(lua.pp_ups.values()) == python.pp_ups
            assert lua.ot_id == python.ot_id == 0x1234
            assert lua.dv_word == python.dv_word == 0x9876
            assert lua.experience == python.experience
            assert tuple(lua.stat_experience.values()) == python.stat_experience == (1, 255, 256, 65024, 65535)
            assert tuple(lua.computed_stats.values()) == python.computed_stats
            assert bytes(lua.ot_name.values()) == python.ot_name
            assert bytes(lua.nickname.values()) == python.nickname
            checked += 1
    assert checked == 151 * 4


@pytest.mark.parametrize("status", [0, 1, 2, 3, 4, 5, 6, 7, 8, 16, 32, 64])
def test_every_canonical_status_preserves_its_raw_bits(lua_codec, status):
    codec = PartyCodec("red")
    raw = bytearray(make_blob(codec))
    raw[4] = status
    assert codec.validate_blob(raw).status == status
    assert lua_result(lua_codec, raw)[0].status == status


@pytest.mark.parametrize("offset,value", [
    (0, 0), (0, 31), (0, 191), (3, 101), (4, 9), (4, 24), (4, 128),
    (5, 6), (6, 26), (8, 166), (10, 0), (11, 5), (31, 1),
    (33, 0), (33, 101), (34, 4), (35, 0), (36, 4),
    (44, 0x50), (44, 0x52), (55, 0x4E), (15, 255),
])
def test_malformed_fields_reject_the_entire_blob(lua_codec, offset, value):
    codec = PartyCodec("red")
    raw = bytearray(make_blob(codec))
    # Offset10 is normally empty: make the following move nonzero for the gap case.
    if offset == 10:
        raw[10] = 3
        raw[11] = 4
    raw[offset] = value
    if offset == 35:
        raw[34] = 0
    before = bytes(raw)
    with pytest.raises(PartyCodecError):
        codec.validate_blob(raw)
    assert lua_result(lua_codec, raw)[0] is None
    assert bytes(raw) == before


@pytest.mark.parametrize("raw", [[], [0] * 65, [0] * 67, "not bytes", 66, None])
def test_wrong_shapes_are_rejected(lua_codec, raw):
    with pytest.raises(PartyCodecError):
        PartyCodec("red").validate_blob(raw)
    assert lua_result(lua_codec, raw)[0] is None


@pytest.mark.parametrize("value", [True, -1, 256, 1.5, None])
def test_non_byte_array_values_are_rejected(lua_codec, value):
    raw = list(make_blob(PartyCodec("red")))
    raw[21] = value
    with pytest.raises(PartyCodecError):
        PartyCodec("red").validate_blob(raw)
    assert lua_result(lua_codec, raw)[0] is None


def test_names_require_termination_but_preserve_padding(lua_codec):
    codec = PartyCodec("red")
    raw = make_blob(codec)
    assert codec.validate_blob(raw).raw == raw
    assert bytes(lua_result(lua_codec, raw)[0].blob.values()) == raw
    for offset in (44, 55):
        invalid = bytearray(raw)
        invalid[offset:offset + 11] = b"\x80" * 11
        with pytest.raises(PartyCodecError, match="terminator"):
            codec.validate_blob(invalid)
        assert lua_result(lua_codec, invalid)[0] is None


NPC_TRADE_OT = bytes.fromhex("5D" + "50" * 10)  # InGameTrade_TrainerString: <TRAINER> then "@" padding


@pytest.mark.parametrize("variant", ["red", "blue", "yellow"])
def test_npc_traded_ot_string_is_the_only_legal_text_control_and_only_as_ot(lua_codec, variant):
    codec = PartyCodec(variant)
    assert codec.npc_trade_ot == NPC_TRADE_OT == bytes(DATA["npc_trade_ot"])
    assert 0x5D not in codec.names
    raw = bytearray(make_blob(codec))
    raw[44:55] = NPC_TRADE_OT
    assert codec.validate_blob(raw).ot_name == NPC_TRADE_OT
    assert bytes(lua_result(lua_codec, raw, variant)[0].ot_name.values()) == NPC_TRADE_OT
    for label, offset, field in (
        ("nickname", 55, NPC_TRADE_OT),  # the same bytes as a nickname
        ("nickname glyph", 55, b"\x91\x5d\x50" + bytes(8)),  # $5D inside a nickname
        ("OT glyph", 44, b"\x91\x5d\x50" + bytes(8)),  # $5D anywhere else in an OT
        ("OT tail", 44, b"\x5d" + b"\x50" * 9 + b"\x00"),  # wrong tail byte
        ("OT terminator", 44, b"\x5d\x5d" + b"\x50" * 9),  # not terminated right after <TRAINER>
        ("OT twice", 44, b"\x5d\x50\x5d" + b"\x50" * 8),
    ):
        invalid = bytearray(make_blob(codec))
        invalid[offset:offset + 11] = field
        with pytest.raises(PartyCodecError, match="glyph|terminator"):
            codec.validate_blob(invalid)
        assert lua_result(lua_codec, invalid, variant)[0] is None, label
    with pytest.raises(PartyCodecError, match="glyph"):
        codec._name(NPC_TRADE_OT, "player name")  # save/player names never accept the trade OT


def test_forty_pp_moves_gain_seven_per_pp_up_not_eight(lua_codec):
    codec = PartyCodec("red")
    move = next(int(k) for k, pp in codec.profile["move_pp"].items() if pp == 40)
    raw = bytearray(make_blob(codec))
    raw[8], raw[29] = move, 0xC0 | 61
    assert codec.validate_blob(raw).pp[0] == 61
    assert lua_result(lua_codec, raw)[0].pp[1] == 61
    raw[29] = 0xFF  # 63 encoded PP is above the cartridge's 61 maximum.
    with pytest.raises(PartyCodecError, match="PP"):
        codec.validate_blob(raw)
    assert lua_result(lua_codec, raw)[0] is None


def test_keys_and_duplicate_party_records_cannot_alias(lua_codec):
    codec = PartyCodec("red")
    raw = make_blob(codec)
    key = codec.validate_blob(raw).key
    with pytest.raises(PartyCodecError, match="key"):
        codec.validate_blob(raw, expected_key="FFFF:1234:99")
    assert lua_result(lua_codec, raw, key="FFFF:1234:99")[0] is None
    with pytest.raises(PartyCodecError, match="duplicate"):
        codec.validate_party([raw, raw])
    with pytest.raises(PartyCodecError, match="boxed"):
        codec.validate_party([raw], boxed_keys=[key])
    lua, module = lua_codec
    party = lua.table_from([lua.table_from(list(raw)), lua.table_from(list(raw))])
    assert module.validateParty(party, "red")[0] is None


@pytest.mark.parametrize("count", range(1, 7))
def test_every_trade_slot_removes_then_appends_with_full_fidelity(lua_codec, count):
    codec = PartyCodec("red")
    party = [make_blob(codec, otid=slot + 1) for slot in range(count)]
    incoming = make_blob(codec, otid=100)
    incoming_key = codec.validate_blob(incoming).key
    lua, module = lua_codec
    for slot in range(count):
        key = codec.validate_blob(party[slot]).key
        result, predicted = codec.prepare_exchange(party, slot, incoming,
            expected_key=key, incoming_key=incoming_key, evolved_species=153, boxed_keys=())
        assert result == tuple(party[:slot] + party[slot + 1:] + [incoming])
        assert predicted == incoming_key
        actual = module.prepareExchange(lua.table_from([lua.table_from(list(raw)) for raw in party]),
            "red", slot, lua.table_from(list(incoming)), key, incoming_key, 153, lua.table_from({}))
        assert not isinstance(actual, tuple), actual
        assert [bytes(blob.values()) for blob in actual.blobs.values()] == list(result)
        assert actual.predicted_key == predicted


def test_predicted_evolution_collision_blocks_prepare_without_mutation(lua_codec):
    codec = PartyCodec("red")
    outgoing = make_blob(codec, otid=1)
    incoming = make_blob(codec, species=38, otid=2)  # Kadabra
    occupied = make_blob(codec, species=149, otid=2)  # Alakazam with same DVs/OTID
    before = (outgoing, occupied, incoming)
    args = {"expected_key": codec.validate_blob(outgoing).key,
            "incoming_key": codec.validate_blob(incoming).key, "evolved_species": 149, "boxed_keys": ()}
    with pytest.raises(PartyCodecError, match="collision"):
        codec.prepare_exchange([outgoing, occupied], 0, incoming, **args)
    assert before == (outgoing, occupied, incoming)


def test_corrupted_generated_facts_are_not_silently_loaded():
    data = copy.deepcopy(DATA)
    data["titles"]["red"]["species"]["153"]["growth_rate"] = 5
    with pytest.raises(PartyCodecError, match="checksum"):
        PartyCodec("red", data)


@pytest.mark.parametrize("problem", ["missing_inventory", "bad_inventory", "missing_key", "unrelated_evolution"])
def test_trade_preparation_requires_complete_identity_and_prediction_inputs(lua_codec, problem):
    codec = PartyCodec("red")
    outgoing = make_blob(codec, otid=1)
    incoming = make_blob(codec, otid=2)
    key, incoming_key = codec.validate_blob(outgoing).key, codec.validate_blob(incoming).key
    boxes, evolved = (), 153
    if problem == "missing_inventory":
        boxes = None
    elif problem == "bad_inventory":
        boxes = "FFFF:FFFF:FF"
    elif problem == "missing_key":
        incoming_key = None
    else:
        evolved = 149
    with pytest.raises(PartyCodecError):
        codec.prepare_exchange([outgoing], 0, incoming, expected_key=key,
            incoming_key=incoming_key, evolved_species=evolved, boxed_keys=boxes)
    lua, module = lua_codec
    lua_boxes = lua.table_from({}) if boxes == () else boxes
    result = module.prepareExchange(lua.table_from([lua.table_from(list(outgoing))]), "red", 0,
        lua.table_from(list(incoming)), key, incoming_key, evolved, lua_boxes)
    assert result[0] is None


def test_duplicate_boxed_inventory_cannot_be_silently_collapsed():
    codec = PartyCodec("red")
    raw = make_blob(codec)
    with pytest.raises(PartyCodecError, match="duplicate boxed"):
        codec.validate_party([raw], boxed_keys=["FFFF:0000:99", "FFFF:0000:99"])


@pytest.mark.parametrize("variant", ["red", "blue", "yellow"])
@pytest.mark.parametrize("count", range(1, 7))
@pytest.mark.parametrize("identical_blob", [False, True])
def test_equal_cross_player_key_replaces_only_the_selected_local_slot(lua_codec, variant, count, identical_blob):
    codec = PartyCodec(variant)
    members = [make_blob(codec, dv=0x1000 + i) for i in range(count)]
    lua, module = lua_codec
    for slot in range(count):
        incoming = bytearray(members[slot])
        if not identical_blob:
            incoming[2] = 9  # same DVs/OTID/species key, independently different physical data
        incoming = bytes(incoming)
        key = codec.validate_blob(incoming).key
        expected = tuple(members[:slot] + members[slot + 1:] + [incoming])
        prepared, predicted = codec.prepare_exchange(members, slot, incoming, expected_key=key,
            incoming_key=key, evolved_species=153, boxed_keys=())
        assert prepared == expected and predicted == key
        result = module.prepareExchange(lua.table_from([lua.table_from(list(raw)) for raw in members]),
            variant, slot, lua.table_from(list(incoming)), key, key, 153, lua.table_from({}))
        assert not isinstance(result, tuple), result
        assert tuple(bytes(blob.values()) for blob in result.blobs.values()) == expected
        assert result.predicted_key == key


@pytest.mark.parametrize("variant", ["red", "blue", "yellow"])
@pytest.mark.parametrize("where", ["party", "box", "evolved-party", "evolved-box"])
def test_recipient_party_and_box_collisions_still_refuse_both_codecs(lua_codec, variant, where):
    codec = PartyCodec(variant)
    incoming = make_blob(codec, species=38, otid=2)  # Kadabra
    occupied = make_blob(codec, species=149 if where.startswith("evolved") else 38, otid=2)
    outgoing = incoming if where.startswith("evolved") else make_blob(codec, otid=1)
    members = [outgoing, occupied] if where.endswith("party") else [outgoing]
    boxes = () if where.endswith("party") else (codec.validate_blob(occupied).key,)
    key, incoming_key = codec.validate_blob(outgoing).key, codec.validate_blob(incoming).key
    evolved = 149 if where.startswith("evolved") else 38
    before = tuple(members)
    with pytest.raises(PartyCodecError, match="collision"):
        codec.prepare_exchange(members, 0, incoming, expected_key=key, incoming_key=incoming_key,
                               evolved_species=evolved, boxed_keys=boxes)
    lua, module = lua_codec
    result = module.prepareExchange(lua.table_from([lua.table_from(list(raw)) for raw in members]), variant, 0,
        lua.table_from(list(incoming)), key, incoming_key, evolved, lua.table_from({key: True for key in boxes}))
    assert isinstance(result, tuple) and result[0] is None and "collision" in result[1]
    assert tuple(members) == before


@pytest.mark.parametrize("species_list", [[153, 255], [153, 255, 0, 0, 0, 0, 0], [153, 0], [153], [153, 255, 0]])
def test_party_species_count_and_terminator_match_in_both_codecs(lua_codec, species_list):
    codec = PartyCodec("red")
    raw = make_blob(codec)
    valid = species_list in ([153, 255], [153, 255, 0, 0, 0, 0, 0])
    if valid:
        assert codec.validate_party([raw], species_list=species_list)
    else:
        with pytest.raises(PartyCodecError):
            codec.validate_party([raw], species_list=species_list)
    lua, module = lua_codec
    result = module.validateParty(lua.table_from([lua.table_from(list(raw))]), "red", lua.table_from(species_list))
    assert (not isinstance(result, tuple)) is valid
