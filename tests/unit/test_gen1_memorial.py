"""Independent Python transform versus the existing Lua storage implementation."""

import copy
import hashlib

import pytest
from lupa.lua54 import LuaRuntime

from server.gen1_full_save import SYMBOLS, image, layout
from server.gen1_initial_observation import display_name
from server.gen1_memorial import SCHEMA, expected, reservation, verify_receipt
from server.gen1_party_codec import PartyCodec
from server.protocol import digest
from server.protocol_journal import JournalError
from tests.unit.test_gen1_party_codec import ROOT, make_blob


def runtime(variant):
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute("""
        bus={};cart={};writes=0;print=function()end
        local function pick(domain)return domain=="CartRAM" and cart or bus end
        memory={getmemorydomainlist=function()return {"System Bus","CartRAM"}end,
            read_u8=function(a,d)return pick(d)[a] or 0 end,
            write_u8=function(a,v,d)writes=writes+1;pick(d)[a]=v end,
            read_u16_le=function(a,d)return (pick(d)[a] or 0)+(pick(d)[a+1] or 0)*256 end,
            write_u16_le=function(a,v,d)writes=writes+1;pick(d)[a]=v%256;pick(d)[a+1]=math.floor(v/256)end}
    """)
    mem = lua.execute((ROOT / "lua/memory_gb.lua").read_text(encoding="utf-8"))
    game = lua.execute((ROOT / "lua/games/gen1_rby.lua").read_text(encoding="utf-8"))
    mem.initProfile(game, variant)
    return lua, mem


def fixture(variant, count=3, slot=1, initialized=True, current=0, pikachu=False, happiness=201):
    info = layout(variant)
    symbols = SYMBOLS["pokeyellow" if variant == "yellow" else "pokered"]
    fields = {name: bytearray(region["length"]) for name, region in info["regions"].items()}
    main, party = fields["main"], fields["party"]
    name = bytes.fromhex("918483500051A5FF020304")
    fields["name"][:] = name

    def off(key):
        return symbols[key] - symbols["wMainDataStart"]

    main[off("wPlayerID") : off("wPlayerID") + 2] = bytes.fromhex("1234")
    main[off("wCurrentBoxNum")] = current + (128 if initialized else 0)
    fields["box"][1] = 255
    codec = PartyCodec(variant)
    blobs = []
    for i in range(count):
        raw = bytearray(
            make_blob(codec, species=84 if pikachu and i == slot else 153, dv=0x1000 + i)
        )
        if i == slot:
            raw[1:3] = b"\0\0"
        blobs.append(bytes(raw))
        for base, segment in (
            (8 + 44 * i, raw[:44]),
            (272 + 11 * i, raw[44:55]),
            (338 + 11 * i, raw[55:66]),
        ):
            party[base : base + len(segment)] = segment
    party[: count + 2] = bytes([count, *(raw[0] for raw in blobs), 255])
    if variant == "yellow":
        main[off("wPikachuHappiness")] = happiness
        main[off("wPikachuMood")] = 150
    cart = bytearray((i * 13 + 7) % 256 for i in range(0x8000))
    for bank in (2, 3):
        for index in range(6):
            start = bank * 0x2000 + index * 1122
            cart[start : start + 1122] = bytes(1122)
            cart[start + 1] = 255
    point = {
        "schema": "rby-full-save-point-v1",
        "variant": variant,
        "save_status": 1,
        "cart_hex": bytes(cart).hex().upper(),
        "fields": {name: bytes(raw).hex().upper() for name, raw in fields.items()},
    }
    point["cart_hex"] = image(point).hex().upper()
    identity = {"ot_id": "1234", "trainer_name": display_name(name)}
    return point, codec.validate_blob(blobs[slot]).key, identity


def load_point(point):
    lua, mem = runtime(point["variant"])
    bus, cart = lua.globals().bus, lua.globals().cart
    info = layout(point["variant"])
    for name, region in info["regions"].items():
        for i, value in enumerate(bytes.fromhex(point["fields"][name])):
            bus[region["address"] + i] = value
    for i, value in enumerate(bytes.fromhex(point["cart_hex"])):
        cart[i] = value
    return lua, mem


def lua_deposit(point, slot):
    lua, mem = load_point(point)
    bus, cart = lua.globals().bus, lua.globals().cart
    info = layout(point["variant"])
    result = mem.depositMemorialMon(slot)
    assert result is True, result
    after = copy.deepcopy(point)
    after["fields"] = {
        name: bytes(bus[region["address"] + i] or 0 for i in range(region["length"])).hex().upper()
        for name, region in info["regions"].items()
    }
    after["cart_hex"] = bytes(cart[i] or 0 for i in range(0x8000)).hex().upper()
    # Full save is a separate qualified phase, following the storage primitive.
    after["cart_hex"] = image(after).hex().upper()
    after["save_status"] = 2
    return after


@pytest.mark.parametrize("variant", ["red", "blue", "yellow"])
@pytest.mark.parametrize("location", ["party", "grave", "current", "inactive"])
def test_legacy_deposit_refuses_identity_collision_before_any_write(variant, location):
    point, _, _ = fixture(variant, slot=0)
    lua, mem = load_point(point)
    bus, cart = lua.globals().bus, lua.globals().cart
    raw = bytes.fromhex(point["fields"]["party"])
    if location == "party":
        for i in range(44):
            bus[int(mem.PARTY_BASE_ADDR) + 44 + i] = raw[8 + i]
    else:
        target = bus if location == "current" else cart
        start = (
            int(mem.BOX_COUNT_ADDR)
            if location == "current"
            else 0x75EA
            if location == "grave"
            else 0x4000 + 1122
        )
        target[start], target[start + 1], target[start + 2] = 1, raw[8], 255
        for i in range(33):
            target[start + 22 + i] = raw[8 + i]
    prior = dict(bus), dict(cart)
    lua.execute("writes=0")
    result = mem.depositMemorialMon(0)
    assert result[0] is False and "collision" in result[1]
    assert (dict(bus), dict(cart)) == prior and lua.globals().writes == 0


@pytest.mark.parametrize("variant", ["red", "blue", "yellow"])
@pytest.mark.parametrize("initialized", [False, True])
@pytest.mark.parametrize("count,slot", [(2, 0), (3, 1), (6, 5)])
@pytest.mark.parametrize("current", [0, 5, 10])
def test_every_saved_byte_matches_existing_lua_storage(variant, initialized, count, slot, current):
    point, key, identity = fixture(variant, count, slot, initialized, current)
    original = copy.deepcopy(point)
    assert expected(point, key, identity=identity) == lua_deposit(point, slot)
    assert point == original


@pytest.mark.parametrize("happiness", [0, 2, 3, 99, 100, 199, 200, 255])
def test_yellow_starter_side_effects_match_verified_policy(happiness):
    point, key, identity = fixture("yellow", pikachu=True, happiness=happiness)
    assert expected(point, key, identity=identity) == lua_deposit(point, 1)


@pytest.mark.parametrize(
    "defect",
    [
        "alive",
        "last",
        "active",
        "save_checksum",
        "save_identity",
        "box_index",
        "sleeping",
        "hidden_live",
        "wrong_key",
        "reservation",
    ],
)
def test_unsafe_memorial_refused_without_mutating_input(defect):
    point, key, identity = fixture(
        "yellow",
        count=1 if defect == "last" else 3,
        slot=0 if defect == "last" else 1,
        pikachu=True,
        current=11 if defect == "active" else 0,
    )
    info, symbols = layout("yellow"), SYMBOLS["pokeyellow"]
    if defect == "alive":
        raw = bytearray.fromhex(point["fields"]["party"])
        raw[8 + 44 + 2] = 10
        point["fields"]["party"] = raw.hex().upper()
    if defect == "sleeping":
        raw = bytearray.fromhex(point["fields"]["main"])
        raw[symbols["wPikachuOverworldStateFlags"] - symbols["wMainDataStart"]] = 2
        point["fields"]["main"] = raw.hex().upper()
    if defect in {"save_checksum", "save_identity", "box_index", "hidden_live"}:
        raw = bytearray.fromhex(point["cart_hex"])
        address = {
            "save_checksum": info["checksum"],
            "save_identity": info["start"],
            "box_index": info["regions"]["main"]["target"]
            + symbols["wCurrentBoxNum"]
            - symbols["wMainDataStart"],
            "hidden_live": 0x75EA + 22,
        }[defect]
        raw[address] ^= 1
        if defect == "hidden_live":
            raw[address + 2] = 10
        if defect != "save_checksum":
            raw[info["checksum"]] = (255 - sum(raw[info["start"] : info["checksum"]])) & 255
        point["cart_hex"] = raw.hex().upper()
    original = copy.deepcopy(point)
    with pytest.raises(JournalError):
        expected(
            point,
            "bad" if defect == "wrong_key" else key,
            identity=identity,
            reserved_digest="0" * 64 if defect == "reservation" else None,
        )
    assert point == original


def receipt_fixture():
    before, key, identity = fixture("yellow")
    after = expected(before, key, identity=identity)
    command = {
        "command_id": "a" * 32,
        "command_sequence": 3,
        "body": {"cmd": "memorialize", "death_id": "d" * 32, "key": key},
    }
    receipt = {
        "schema": SCHEMA,
        "command_id": command["command_id"],
        "command_sequence": 3,
        "body_digest": digest(command["body"]),
        "context_generation": "c" * 32,
        "final_sha1": "f" * 40,
        "before_digest": digest(before),
        "after": after,
        "file": {
            "schema": "slink-saveram-file-v1",
            "path": "owned.sav",
            "sha256": hashlib.sha256(bytes.fromhex(after["cart_hex"])).hexdigest(),
            "byte_length": 0x8000,
            "host_profile": "bizhawk-2.11.1-gambatte-exclusive-hold-v1",
            "frame": 10,
            "flushed": True,
            "readback": True,
        },
    }
    options = {
        "before": before,
        "identity": identity,
        "context_generation": "c" * 32,
        "final_sha1": "f" * 40,
        "frame": 10,
    }
    return command, receipt, options


def test_complete_command_bound_receipt_verifies():
    command, receipt, options = receipt_fixture()
    result = verify_receipt(command, receipt, **options)
    assert result["key"] == command["body"]["key"]
    assert result["reservation_digest"] == reservation(receipt["after"])


def test_full_owned_memorial_refuses_instead_of_using_an_ordinary_box():
    point, key, identity = fixture("yellow")
    cart = bytearray.fromhex(point["cart_hex"])
    cart[0x75EA] = 20
    for slot in range(20):
        raw = bytearray(make_blob(PartyCodec("yellow"), dv=0x8000 + slot))
        raw[1:3] = b"\0\0"
        raw[3] = raw[33]
        cart[0x75EB + slot] = raw[0]
        for base, value in (
            (0x7600 + 33 * slot, raw[:33]),
            (0x75EA + 682 + 11 * slot, raw[44:55]),
            (0x75EA + 902 + 11 * slot, raw[55:66]),
        ):
            cart[base : base + len(value)] = value
    cart[0x75EB + 20] = 255
    point["cart_hex"] = cart.hex().upper()
    original = copy.deepcopy(point)
    with pytest.raises(JournalError, match="memorial box full"):
        expected(point, key, identity=identity, reserved_digest=reservation(point))
    assert point == original


@pytest.mark.parametrize("variant", ["red", "blue", "yellow"])
def test_second_memorial_requires_the_exact_durable_reservation(variant):
    point, key, identity = fixture(variant, count=3, slot=0)
    raw = bytearray.fromhex(point["fields"]["party"])
    raw[8 + 44 + 1 : 8 + 44 + 3] = b"\0\0"
    point["fields"]["party"] = raw.hex().upper()
    first = expected(point, key, identity=identity)
    party = bytes.fromhex(first["fields"]["party"])
    next_key = f"{party[8 + 27 : 8 + 29].hex().upper()}:{party[8 + 12 : 8 + 14].hex().upper()}:{party[8]:02X}"
    with pytest.raises(JournalError, match="owned reservation"):
        expected(first, next_key, identity=identity)
    second = expected(first, next_key, identity=identity, reserved_digest=reservation(first))
    assert bytes.fromhex(second["cart_hex"])[0x75EA] == 2
    assert bytes.fromhex(second["fields"]["party"])[0] == 1
    assert reservation(second) != reservation(first)


@pytest.mark.parametrize(
    "defect",
    ["level_zero", "level_101", "grave_terminator", "grave_list", "grave_species", "duplicate_key"],
)
def test_prepared_validator_rejects_malformed_party_and_reserved_grave(defect):
    point, key, identity = fixture("yellow", count=3, slot=0)
    raw = bytearray.fromhex(point["fields"]["party"])
    raw[8 + 44 + 1 : 8 + 44 + 3] = b"\0\0"
    point["fields"]["party"] = raw.hex().upper()
    first = expected(point, key, identity=identity)
    party = bytearray.fromhex(first["fields"]["party"])
    next_key = f"{party[35:37].hex().upper()}:{party[20:22].hex().upper()}:{party[8]:02X}"
    if defect.startswith("level"):
        party[8 + 33] = 0 if defect == "level_zero" else 101
        first["fields"]["party"] = party.hex().upper()
    else:
        cart = bytearray.fromhex(first["cart_hex"])
        if defect == "grave_terminator":
            cart[0x75EC] = 0
        elif defect == "grave_list":
            cart[0x75EB] ^= 1
        elif defect == "grave_species":
            cart[0x75EB] = cart[0x7600] = 0
        else:
            cart[0x7600 + 27 : 0x7600 + 29] = party[35:37]
        first["cart_hex"] = cart.hex().upper()
    with pytest.raises(JournalError):
        expected(first, next_key, identity=identity, reserved_digest=reservation(first))


@pytest.mark.parametrize(
    "defect",
    [
        "command_id",
        "command_sequence",
        "body_digest",
        "context_generation",
        "final_sha1",
        "before_digest",
        "file_hash",
        "file_frame",
        "file_flush",
        "unrelated_sram",
        "unrelated_wram",
        "missing_grave",
        "extra",
    ],
)
def test_receipt_cannot_promote_partial_foreign_or_unsaved_poststate(defect):
    command, receipt, options = receipt_fixture()
    if defect in {"command_id", "body_digest", "context_generation", "final_sha1", "before_digest"}:
        receipt[defect] = "0" * len(receipt[defect])
    elif defect == "command_sequence":
        receipt[defect] = True
    elif defect == "file_hash":
        receipt["file"]["sha256"] = "0" * 64
    elif defect == "file_frame":
        receipt["file"]["frame"] += 1
    elif defect == "file_flush":
        receipt["file"]["flushed"] = False
    elif defect in {"unrelated_sram", "missing_grave"}:
        raw = bytearray.fromhex(receipt["after"]["cart_hex"])
        raw[17 if defect == "unrelated_sram" else 0x75EA] ^= 1
        receipt["after"]["cart_hex"] = raw.hex().upper()
    elif defect == "unrelated_wram":
        receipt["after"]["fields"]["tiles"] = "FF"
    else:
        receipt["assert_success"] = True
    with pytest.raises(JournalError):
        verify_receipt(command, receipt, **options)


@pytest.mark.parametrize('initialized',[False,True])
def test_saved_box_initialization_must_agree_before_any_grave_change(initialized):
    point,key,identity=fixture('yellow',initialized=initialized)
    symbols=SYMBOLS['pokeyellow'];info=layout('yellow');cart=bytearray.fromhex(point['cart_hex'])
    offset=info['regions']['main']['target']+symbols['wCurrentBoxNum']-symbols['wMainDataStart']
    cart[offset]^=128
    cart[info['checksum']]=(255-sum(cart[info['start']:info['checksum']]))&255
    point['cart_hex']=cart.hex().upper();before=copy.deepcopy(point)
    with pytest.raises(JournalError,match='saved trainer and current box'):
        expected(point,key,identity=identity)
    assert point==before
