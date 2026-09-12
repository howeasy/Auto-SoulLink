"""Owned storage policy with synthetic images; no new moving-engine claim."""

import copy
import json

import pytest

from server.gen1_full_save import SYMBOLS, image
from server.gen1_initial_observation import inventory
from server.gen1_memorial import expected, reservation
from server.gen1_memorial_policy import (
    BOX_SIZE,
    MemorialRecoveryRequired,
    box_image,
    box_offset,
    empty_archive_candidates,
    entirely_empty,
    storage_policy,
)
from server.gen1_memorial_runtime import COMPONENT, RETAINED
from server.gen1_party_codec import PartyCodec
from server.gen1_run_config import create_runtime, open_runtime
from server.protocol_journal import JournalError
from server.state import LinkStatus
from tests.unit.test_gen1_engine_signal_runtime import deliver, payload
from tests.unit.test_gen1_faint_runtime import ack, acknowledgement, bag, paired, signal_batch
from tests.unit.test_gen1_memorial import fixture
from tests.unit.test_gen1_memorial_runtime import completion, observe, start
from tests.unit.test_gen1_party_codec import make_blob
from tests.unit.test_gen1_sessions import contract


def full_grave(variant, active=False):
    point, key, identity = fixture(variant, current=11 if active else 0)
    raw = bytearray(BOX_SIZE)
    raw[0] = 20
    raw[21] = 255
    for slot in range(20):
        mon = bytearray(make_blob(PartyCodec(variant), dv=0x8000 + slot))
        mon[1:3] = b"\0\0"
        mon[3] = mon[33]
        raw[1 + slot] = mon[0]
        for base, value in (
            (22 + 33 * slot, mon[:33]),
            (682 + 11 * slot, mon[44:55]),
            (902 + 11 * slot, mon[55:]),
        ):
            raw[base : base + len(value)] = value
    if active:
        point["fields"]["box"] = raw.hex().upper()
    else:
        cart = bytearray.fromhex(point["cart_hex"])
        cart[box_offset(11) : box_offset(11) + BOX_SIZE] = raw
        point["cart_hex"] = cart.hex().upper()
    point["cart_hex"] = image(point).hex().upper()
    return point, key, identity


@pytest.mark.parametrize("variant", ["red", "blue", "yellow"])
def test_active_grave_uses_authoritative_wram_and_preserves_its_stale_sram_slot(variant):
    point, key, identity = fixture(variant, current=11)
    before = copy.deepcopy(point)
    policy = storage_policy(point)
    assert policy["active_grave"] and policy["rotation"] is None
    after = expected(point, key, identity=identity, storage_policy=policy)
    assert point == before and after["fields"]["box"][:2] == "01"
    offset = box_offset(11)
    assert (
        bytes.fromhex(after["cart_hex"])[offset : offset + BOX_SIZE]
        == bytes.fromhex(point["cart_hex"])[offset : offset + BOX_SIZE]
    )
    members = inventory(after, identity)["members"]
    target = next(mon for mon in members if mon["key"] == key)
    assert (target["location"], target["box"], target["slot"]) == ("box", 11, 0)
    assert reservation(after) != reservation(point)
    assert after["cart_hex"] == image(after).hex().upper()


@pytest.mark.parametrize("variant", ["red", "blue", "yellow"])
@pytest.mark.parametrize("active", [False, True])
def test_full_owned_grave_rotates_all_twenty_exact_records_then_deposits_one(variant, active):
    point, key, identity = full_grave(variant, active)
    before = copy.deepcopy(point)
    original_grave = box_image(point, 11)
    owned = reservation(point)
    policy = storage_policy(point, reserved_digest=owned)
    destination = policy["rotation"]["box"]
    assert destination not in (11, 11 if active else 0)
    assert entirely_empty(box_image(point, destination))
    after = expected(point, key, identity=identity, reserved_digest=owned, storage_policy=policy)
    assert point == before
    assert box_image(after, destination) == original_grave
    assert box_image(after, destination)[0] == 20 and box_image(after, 11)[0] == 1
    before_keys = {m["key"] for m in inventory(point, identity)["members"]}
    after_keys = {m["key"] for m in inventory(after, identity)["members"]}
    assert before_keys == after_keys
    assert inventory(after, identity)["party_count"] == 2
    for bank in {2 + destination // 6} if active else {3, 2 + destination // 6}:
        cart = bytes.fromhex(after["cart_hex"])
        sums = [
            sum(cart[bank * 0x2000 + i * BOX_SIZE : bank * 0x2000 + (i + 1) * BOX_SIZE])
            for i in range(6)
        ]
        assert cart[bank * 0x2000 + 0x1A4C : bank * 0x2000 + 0x1A53] == bytes(
            [(255 - sum(sums)) & 255, *((255 - value) & 255 for value in sums)]
        )


@pytest.mark.parametrize(
    "fault", ["unowned", "changed-reservation", "changed-policy", "hidden-live"]
)
def test_overflow_never_adopts_unowned_grave_or_uses_a_forged_storage_plan(fault):
    point, key, identity = full_grave("yellow")
    owned = reservation(point)
    if fault == "hidden-live":
        cart = bytearray.fromhex(point["cart_hex"])
        cart[box_offset(11) + 24] = 1
        point["cart_hex"] = cart.hex().upper()
        owned = reservation(point)
    before = copy.deepcopy(point)
    with pytest.raises(JournalError):
        policy = storage_policy(
            point,
            reserved_digest=None
            if fault == "unowned"
            else "f" * 64
            if fault == "changed-reservation"
            else owned,
        )
        if fault == "changed-policy":
            policy["rotation"]["box"] = 11
        expected(point, key, identity=identity, reserved_digest=owned, storage_policy=policy)
    assert point == before


def test_nonempty_or_hidden_destination_is_never_reserved_and_no_space_is_explicit():
    point, _, _ = full_grave("yellow")
    cart = bytearray.fromhex(point["cart_hex"])
    for index in range(1, 11):
        # Even a stale nonzero name tail in a count-zero box refuses reservation.
        cart[box_offset(index) + BOX_SIZE - 1] = 0x80
    point["cart_hex"] = cart.hex().upper()
    before = copy.deepcopy(point)
    assert empty_archive_candidates(point) == []
    with pytest.raises(MemorialRecoveryRequired) as failure:
        storage_policy(point, reserved_digest=reservation(point))
    assert failure.value.code == "no-empty-archive-box" and point == before


@pytest.mark.parametrize("active", [False, True])
def test_first_reservation_checks_entire_grave_not_only_zero_count(active):
    point, _, _ = fixture("yellow", current=11 if active else 0)
    raw = bytearray(box_image(point, 11))
    raw[-1] = 0x80  # Count is zero, but an unowned name tail is still present.
    if active:
        point["fields"]["box"] = raw.hex().upper()
    else:
        cart = bytearray.fromhex(point["cart_hex"])
        cart[box_offset(11) : box_offset(11) + BOX_SIZE] = raw
        point["cart_hex"] = cart.hex().upper()
    before = copy.deepcopy(point)
    with pytest.raises(JournalError, match="unowned bytes"):
        storage_policy(point)
    assert point == before


@pytest.mark.parametrize("variant", ["red", "blue", "yellow"])
@pytest.mark.parametrize("active", [False, True])
def test_actual_lua_executor_repairs_archive_rotation_and_flushes_exactly_once(
    monkeypatch, variant, active
):
    from tests.unit import test_gen1_memorial_executor as executor_fixture

    before, key, identity = full_grave(variant, active)
    reserved = reservation(before)
    policy = storage_policy(before, reserved_digest=reserved)
    after = expected(
        before, key, identity=identity, reserved_digest=reserved, storage_policy=policy
    )
    # Replace only that harness's initial point construction; the actual journal,
    # held permit, compact deltas, memory adapter and prepared executor are real Lua.
    monkeypatch.setattr(
        executor_fixture, "fixture", lambda *args, **kwargs: (before, key, identity)
    )
    monkeypatch.setattr(executor_fixture, "expected", lambda *args, **kwargs: after)
    lua, _, _ = executor_fixture.client(variant, fail_after=80)
    globals_ = lua.globals()
    assert globals_.step()[0] is False and globals_.writes == 0
    phases = []
    for _ in range(5):
        phases.append(globals_.grant())
        done, result = globals_.step()
        if done:
            break
    assert done and result["outcome"] == "ACK"
    assert "memorial_repair" in phases and phases[-1] == "memorial_save"
    assert json.loads(globals_.point_json()) == after and globals_.file_writes == 1
    writes = globals_.writes
    assert globals_.step()[0] and globals_.writes == writes and globals_.file_writes == 1


@pytest.mark.parametrize("variant", ["red", "blue", "yellow"])
def test_strict_legacy_kernel_does_not_silently_opt_into_new_storage_policy(variant):
    active, key, identity = fixture(variant, current=11)
    with pytest.raises(JournalError, match="active memorial"):
        expected(active, key, identity=identity)
    full, key, identity = full_grave(variant)
    with pytest.raises(JournalError, match="memorial box full"):
        expected(full, key, identity=identity, reserved_digest=reservation(full))


def last_point(message):
    point = message["receipt"]["point"]
    party = bytearray.fromhex(point["fields"]["party"])
    party[0] = 1
    party[2] = 255
    party[3:8] = bytes(5)
    for base, width in ((8, 44), (272, 11), (338, 11)):
        party[base + width : base + 6 * width] = bytes(5 * width)
    point["fields"]["party"] = party.hex().upper()
    point["cart_hex"] = image(point).hex().upper()
    return point


def terminal_start(runtime):
    owners = paired(runtime)
    peer_activation = payload(runtime, "b", ["battle_faint"], 2)
    peer_activation["signals"] = [bag(runtime.contract["players"]["b"]["variant"])]
    deliver(runtime, "b", owners["b"], peer_activation)
    deliver(runtime, "a", owners["a"], signal_batch(runtime, "a"))
    command = runtime.journal.command("b", runtime.journal.pending_ids("b")[0])
    ack(runtime, "b", owners["b"], acknowledgement(runtime, "b", command))
    return owners


@pytest.mark.parametrize("variants", [("yellow", "yellow"), ("red", "blue"), ("blue", "yellow")])
def test_production_preparation_records_active_box_policy_and_exact_saved_completion(
    tmp_path, variants
):
    runtime = create_runtime(tmp_path, contract(*variants))
    try:
        owners = start(runtime)
        for player in ("a", "b"):
            _, message = observe(runtime, player)
            point = message["receipt"]["point"]
            symbols = SYMBOLS["pokeyellow" if point["variant"] == "yellow" else "pokered"]
            main = bytearray.fromhex(point["fields"]["main"])
            main[symbols["wCurrentBoxNum"] - symbols["wMainDataStart"]] = 11
            point["fields"]["main"] = main.hex().upper()
            point["cart_hex"] = image(point).hex().upper()
            ack(runtime, player, owners[player], message)
            prepared = runtime.state().document()["components"][COMPONENT]["entries"][player][-1][
                "payload"
            ]
            assert prepared["storage_policy"]["active_grave"]
            assert prepared["after"]["fields"]["box"][:2] == "01"
            _, completed = completion(runtime, player)
            ack(runtime, player, owners[player], completed)
        assert runtime.state().rules.links[0].status == LinkStatus.MEMORIAL
        assert runtime.state().barrier.ticket() is None
    finally:
        runtime.close()
    runtime = open_runtime(tmp_path)
    try:
        assert runtime.state().rules.links[0].status == LinkStatus.MEMORIAL
    finally:
        runtime.close()


def test_last_party_without_terminal_run_state_is_not_declared_retained(tmp_path):
    runtime = create_runtime(tmp_path, contract("yellow", "yellow"))
    try:
        owners = start(runtime)
        _, message = observe(runtime, "a")
        last_point(message)
        before = runtime.journal.snapshot()
        assert runtime.state().rules.run_over is False
        with pytest.raises(JournalError, match="no live linked pair"):
            ack(runtime, "a", owners["a"], message)
        assert runtime.journal.snapshot() == before
        assert runtime.journal.pending_ids("a")
    finally:
        runtime.close()


@pytest.mark.parametrize("variants", [("yellow", "yellow"), ("red", "blue"), ("blue", "yellow")])
def test_terminal_last_party_is_durably_retained_without_zero_party_or_false_saved_completion(
    tmp_path, variants
):
    runtime = create_runtime(tmp_path, contract(*variants))
    try:
        owners = terminal_start(runtime)
        before_rules = runtime.state().rules.document()
        holds = runtime.state().barrier.document()["blockers"]
        assert runtime.state().rules.run_over
        for player in ("a", "b"):
            _, message = observe(runtime, player)
            original = copy.deepcopy(last_point(message))
            ack(runtime, player, owners[player], message)
            entry = runtime.state().document()["components"][COMPONENT]["entries"][player][-1]
            assert entry["schema"] == RETAINED
            assert entry["retention"]["disposition"] == "retained-dead-party"
            assert (
                entry["retention"]["saved"] is False
                and entry["retention"]["memorial_complete"] is False
            )
            assert entry["payload"] is None and entry["receipt_event"] is None
            assert entry["observation_event"]["message"]["receipt"]["point"] == original
            assert not runtime.journal.pending_ids(player)
        assert runtime.state().rules.document() == before_rules
        assert runtime.state().barrier.document()["blockers"] == holds
        assert runtime.state().barrier.ticket() is None
        assert runtime.state().rules.links[0].status == LinkStatus.DEAD
    finally:
        runtime.close()
    restored = open_runtime(tmp_path)
    try:
        assert restored.state().rules.run_over and restored.state().barrier.ticket() is None
    finally:
        restored.close()


@pytest.mark.parametrize("fault", ["alive-target", "point-digest", "read-event"])
def test_terminal_disposition_cannot_hide_live_target_or_lost_read_provenance(tmp_path, fault):
    runtime = create_runtime(tmp_path, contract("yellow", "yellow"))
    try:
        owners = terminal_start(runtime)
        _, message = observe(runtime, "a")
        point = last_point(message)
        before = runtime.journal.snapshot()
        if fault == "alive-target":
            party = bytearray.fromhex(point["fields"]["party"])
            party[10] = 1
            point["fields"]["party"] = party.hex().upper()
            with pytest.raises(JournalError, match="physically fainted"):
                ack(runtime, "a", owners["a"], message)
            assert runtime.journal.snapshot() == before
            return
        ack(runtime, "a", owners["a"], message)
        entry = runtime.state().document()["components"][COMPONENT]["entries"]["a"][-1]
        if fault == "point-digest":
            stage = runtime.state()
            from server.gen1_runtime_state import Gen1RuntimeState

            bad = stage.document()
            bad["components"][COMPONENT]["entries"]["a"][-1]["retention"]["point_digest"] = "f" * 64
            with pytest.raises(JournalError):
                Gen1RuntimeState.restore(bad, data_dir=tmp_path)
        else:
            runtime.journal._db.execute(
                "DELETE FROM events WHERE player=? AND operation_id=?",
                ("a", entry["observation_event"]["operation_id"]),
            )
            with pytest.raises(JournalError):
                runtime.state()
    finally:
        runtime.close()
