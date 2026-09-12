"""Source-container projections; no emulator or physical-write authority claimed."""

import copy

import pytest

from server.gen1_full_save import SYMBOLS
from server.gen1_initial_observation import inventory
from server.gen1_storage import StorageRefusal, expected, withdraw_blob
from server.protocol_journal import JournalError
from tests.unit.test_gen1_memorial import fixture


@pytest.mark.parametrize("variant", ["red", "blue", "yellow"])
@pytest.mark.parametrize("count,slot", [(n, s) for n in range(2, 7) for s in range(n)])
def test_deposit_then_withdraw_preserves_identity_hp_status_and_names(variant, count, slot):
    before, key, identity = fixture(variant, count=count, slot=slot)
    before_copy = copy.deepcopy(before)
    deposited = expected(before, key, "deposit", identity=identity)
    assert before == before_copy
    roster = inventory(deposited, identity)
    boxed = next(r for r in roster["members"] if r["key"] == key)
    assert boxed["location"] == "box" and roster["party_count"] == count - 1
    retrieved = expected(deposited, key, "withdraw", identity=identity)
    row = next(r for r in inventory(retrieved, identity)["members"] if r["key"] == key)
    old = next(r for r in inventory(before, identity)["members"] if r["key"] == key)
    actual = bytes.fromhex(row["blob_hex"])
    prior = bytes.fromhex(old["blob_hex"])
    assert actual[:3] == prior[:3] and actual[4:33] == prior[4:33] and actual[44:] == prior[44:]
    assert row["slot"] == count - 1
    assert actual == withdraw_blob(bytes.fromhex(boxed["box_blob_hex"]), variant)


@pytest.mark.parametrize("variant", ["red", "blue", "yellow"])
def test_last_party_and_full_party_refuse_without_mutation(variant):
    point, key, identity = fixture(variant, count=1, slot=0)
    old = copy.deepcopy(point)
    with pytest.raises(StorageRefusal, match="last-party"):
        expected(point, key, "deposit", identity=identity)
    assert point == old


@pytest.mark.parametrize("variant", ["red", "blue", "yellow"])
def test_reserved_archive_and_invalid_current_box_never_receive_live_storage(variant):
    point, key, identity = fixture(variant, count=2, slot=0)
    symbols = SYMBOLS["pokeyellow" if variant == "yellow" else "pokered"]
    at = symbols["wCurrentBoxNum"] - symbols["wMainDataStart"]
    main = bytearray.fromhex(point["fields"]["main"])
    main[at] = 139
    point["fields"]["main"] = main.hex().upper()
    with pytest.raises(StorageRefusal, match="reserved-archive"):
        expected(point, key, "deposit", identity=identity)


def test_withdraw_rebuilds_level_from_xp_instead_of_stale_box_level():
    point, key, identity = fixture("red", count=2, slot=0)
    boxed = expected(point, key, "deposit", identity=identity)
    raw = bytearray.fromhex(boxed["fields"]["box"])
    raw[25] = 1
    boxed["fields"]["box"] = raw.hex().upper()
    after = expected(boxed, key, "withdraw", identity=identity)
    record = next(r for r in inventory(after, identity)["members"] if r["key"] == key)
    assert bytes.fromhex(record["blob_hex"])[33] == 5


@pytest.mark.parametrize("variant", ["red", "blue", "yellow"])
@pytest.mark.parametrize("box", range(11))
def test_withdraw_from_inactive_box_preserves_all_other_boxes(variant, box):
    from server.gen1_full_save import image
    from server.gen1_grave_storage import checksum_banks
    from server.gen1_memorial_policy import box_offset

    point, key, identity = fixture(variant, count=2, slot=0)
    deposited = expected(point, key, "deposit", identity=identity)
    stored = deposited["fields"]["box"]
    symbols = SYMBOLS["pokeyellow" if variant == "yellow" else "pokered"]
    main = bytearray.fromhex(deposited["fields"]["main"])
    main[symbols["wCurrentBoxNum"] - symbols["wMainDataStart"]] = 128 + ((box + 1) % 11)
    deposited["fields"]["main"] = main.hex().upper()
    deposited["fields"]["box"] = (b"\0\xff" + bytes(1120)).hex().upper()
    cart = bytearray.fromhex(deposited["cart_hex"])
    start = box_offset(box)
    cart[start : start + 1122] = bytes.fromhex(stored)
    checksum_banks(cart, {2 + box // 6})
    deposited["cart_hex"] = cart.hex().upper()
    deposited["cart_hex"] = image(deposited).hex().upper()
    after = expected(deposited, key, "withdraw", identity=identity)
    for other in set(range(12)) - {box}:
        begin = box_offset(other)
        assert (
            bytes.fromhex(after["cart_hex"])[begin : begin + 1122]
            == bytes.fromhex(deposited["cart_hex"])[begin : begin + 1122]
        )
    assert inventory(after, identity)["party_count"] == 2


@pytest.mark.parametrize("level", [2, 5, 50, 100])
@pytest.mark.parametrize("exp", [0, 15, 16, 17, 65024, 65025, 65535])
def test_withdraw_stats_match_independent_pinned_source_formula(level, exp):
    from server.gen1_party_codec import PartyCodec
    from tests.unit.test_gen1_stat_formula import FIELDS, calc_stats

    point, key, identity = fixture("red", count=2, slot=0)
    deposited = expected(point, key, "deposit", identity=identity)
    mon = next(m for m in inventory(deposited, identity)["members"] if m["key"] == key)
    raw = bytearray.fromhex(mon["box_blob_hex"])
    codec = PartyCodec("red")
    facts = codec.profile["species"][str(raw[0])]
    raw[14:17] = codec.experience_for_level(facts["growth_rate"], level).to_bytes(3, "big")
    raw[17:27] = exp.to_bytes(2, "big") * 5
    expected_stats = calc_stats(
        dict(zip(FIELDS, facts["base_stats"], strict=True)),
        level,
        int.from_bytes(raw[27:29], "big"),
        dict.fromkeys(FIELDS, exp),
    )
    blob = withdraw_blob(bytes(raw), "red")
    assert [int.from_bytes(blob[i : i + 2], "big") for i in range(34, 44, 2)] == list(
        expected_stats.values()
    )


@pytest.mark.parametrize("variant", ["red", "blue", "yellow"])
def test_slot19_reserved_undo_preserves_cartridge_tail_then_owned_memorial_overwrites_unused_copy(
    variant,
):
    from server.gen1_full_save import image
    from server.gen1_memorial import expected as memorial, reservation
    from server.gen1_memorial_policy import storage_policy
    from tests.unit.test_gen1_memorial_policy import full_grave

    point, dead, identity = full_grave(variant, active=True)
    raw = bytearray.fromhex(point["fields"]["box"])
    raw[0] = 19
    raw[20] = 255
    point["fields"]["box"] = raw.hex().upper()
    point["cart_hex"] = image(point).hex().upper()
    before_reservation = reservation(point)
    live = next(
        m["key"]
        for m in inventory(point, identity)["members"]
        if m["location"] == "party" and m["key"] != dead
    )
    deposited = expected(point, live, "deposit", identity=identity, reserved_boxes=())
    restored = expected(deposited, live, "withdraw", identity=identity, reserved_boxes=())
    grave = bytes.fromhex(restored["fields"]["box"])
    assert grave[0] == 19 and grave[22 + 19 * 33 + 1 : 22 + 19 * 33 + 3] != b"\0\0"
    assert grave[682 + 19 * 11] == 255
    with pytest.raises(JournalError, match="reservation changed"):
        memorial(
            restored,
            dead,
            identity=identity,
            reserved_digest=before_reservation,
            storage_policy=storage_policy(restored, reserved_digest=before_reservation),
        )
    owned = reservation(restored)
    archived = memorial(
        restored,
        dead,
        identity=identity,
        reserved_digest=owned,
        storage_policy=storage_policy(restored, reserved_digest=owned),
    )
    final = bytes.fromhex(archived["fields"]["box"])
    assert final[0] == 20 and final[22 + 19 * 33 + 1 : 22 + 19 * 33 + 3] == b"\0\0"
    assert final[22 : 22 + 19 * 33] == grave[22 : 22 + 19 * 33]


@pytest.mark.parametrize("variant", ["red", "blue", "yellow"])
def test_quarantine_uses_first_legal_inactive_capacity_and_preserves_full_current_box(variant):
    from server.gen1_full_save import image
    from server.gen1_storage_policy import quarantine_box
    from tests.unit.test_gen1_memorial_policy import full_grave

    point, key, identity = fixture(variant, count=3, slot=1)
    full, _, _ = full_grave(variant, active=True)
    point["fields"]["box"] = full["fields"]["box"]
    point["cart_hex"] = image(point).hex().upper()
    chosen = quarantine_box(point, key, identity)
    assert chosen == 1
    after = expected(point, key, "deposit", identity=identity, destination_box=chosen)
    assert after["fields"]["box"] == point["fields"]["box"]
    moved = next(m for m in inventory(after, identity)["members"] if m["key"] == key)
    assert moved["location"] == "box" and moved["box"] == chosen
