import json
import random

import pytest

from tests.rr.runtime.rr_harness import RRHarness


def adapter(h):
    context_module = h.lua.eval('require("rr.context")')
    storage_module = h.lua.eval('require("rr.storage")')
    if isinstance(context_module, tuple):
        context_module = context_module[0]
    if isinstance(storage_module, tuple):
        storage_module = storage_module[0]
    context = context_module.new(h.M, h.MB, h.lua.globals().memory)
    return storage_module.new(h.M, h.MB, h.lua.globals().memory, context)


def test_prepare_has_no_effect_and_refuses_changed_unrelated_party(rr_repo):
    h = RRHarness(rr_repo, party=(111, 333))
    h.step()
    storage = adapter(h)
    body = h.lua.table_from({"cmd": "box_mon", "key": h.key(111), "slot": 0, "box": 0, "pos": 0})
    before = len(h.lua.globals()._RR_WRITES)
    intent = storage.prepare(body)
    assert intent.schema == "rr-storage-intent-v1"
    assert len(h.lua.globals()._RR_WRITES) == before
    assert storage.classify(body, intent)[0] == "before"
    # A different member's item changed: old intent may not overwrite the new state.
    h.seed_u16(int(h.M.PARTY_BASE) + 100 + 0x22, 42)
    state, reason = storage.classify(body, intent)
    assert state == "diverged", reason
    assert storage.apply(body, intent)[0] is None
    assert h.pending_native()["opcode"] == 0


def test_prepared_compressed_projection_matches_existing_rr_codec(rr_repo):
    h = RRHarness(rr_repo, party=(111, 333))
    storage = adapter(h)
    body = h.lua.table_from({"cmd": "box_mon", "key": h.key(111), "slot": 0, "box": 0, "pos": 0})
    rng = random.Random(418)
    scratch = 0x02001000
    guards = [h.canary(scratch - 1, 1), h.canary(scratch + 58, 1)]
    for _ in range(64):
        raw = bytearray(h.bytes(int(h.M.PARTY_BASE), 100))
        for first, last in [(0x22, 0x2B), (0x38, 0x3E), (0x44, 0x50)]:
            raw[first:last] = bytes(rng.randrange(256) for _ in range(last - first))
        for index in range(4):
            move = rng.choice([0, 1, 255, 256, 511, 512, 1023])
            raw[0x2C + index * 2 : 0x2E + index * 2] = move.to_bytes(2, "little")
        h.seed(int(h.M.PARTY_BASE), raw)
        intent = storage.prepare(body)
        h.M.createCompressedMon(h.M.PARTY_BASE, scratch)
        assert intent.after_box.lower() == h.bytes(scratch, 58).hex()
        h.check_canaries(*guards)


def test_verified_native_deposit_and_withdraw_keep_represented_data(rr_repo):
    h = RRHarness(rr_repo, party=(111, 333))
    h.step()
    original = h.bytes(int(h.M.PARTY_BASE), 100)
    survivor = h.bytes(int(h.M.PARTY_BASE) + 100, 100)
    h.command("box_mon", key=h.key(111))
    h.step()
    assert h.pending_native()["opcode"] == 24
    h.engine_storage_effect()
    h.step()
    assert h.bytes(int(h.M.PARTY_BASE), 100) == survivor
    assert h.M.boxMonKey(0, 0) == h.key(111)
    assert not any("UNRESOLVED" in line for line in h.logs())
    h.command("party_mon", key=h.key(111))
    h.step()
    assert h.pending_native()["opcode"] == 25
    h.engine_storage_effect(withdrawn_party=original)
    h.step()
    assert h.bytes(int(h.M.PARTY_BASE) + 100, 100) == original
    assert h.M.boxMonKey(0, 0) is None
    assert [e["key"] for e in h.events("sync_retrieve_done")] == [h.key(111)]
    assert not h.events("capture")


@pytest.mark.parametrize("corrupt_survivor", [False, True])
def test_memorial_success_requires_complete_source_destination_and_survivor_proof(
    rr_repo, corrupt_survivor
):
    h = RRHarness(rr_repo, party=(111, 333))
    h.set_mon(0, 111, 0)
    h.step()
    h.command("memorialize", key=h.key(111))
    h.step()
    assert h.pending_native()["opcode"] == 26
    h.engine_storage_effect()
    # Correct target key alone is insufficient if an unrelated survivor was corrupted.
    if corrupt_survivor:
        h.seed_u16(int(h.M.PARTY_BASE) + 0x22, 42)
    h.step()
    assert len(h.events("memorialize_done")) == (0 if corrupt_survivor else 1)
    assert any("MEMORIAL UNRESOLVED" in line for line in h.logs()) == corrupt_survivor
    assert h.M.boxMonKey(24, 0) == h.key(111)


@pytest.mark.parametrize("owner", ["script", "menu", "writer", "borrowed"])
def test_storage_waits_for_its_specific_owner_prerequisites(rr_repo, owner):
    h = RRHarness(rr_repo, party=(111, 333))
    h.step()
    if owner == "script":
        h.seed_u8(0x03000F9C, 1)
    elif owner == "menu":
        h.seed_u32(0x030030F4, 0x080567DD)
    elif owner == "writer":
        h.seed_u32(h.M.TASKS_BASE_ADDR, h.M.POST_BATTLE_WRITER_TASKS[1])
        h.seed(h.M.TASKS_BASE_ADDR + 4, bytes([1, 0xFE, 0xFF, 10]))
    else:
        h.seed_u8(0x0203F840, 1)
    h.command("box_mon", key=h.key(111))
    h.step()
    assert h.pending_native()["opcode"] == 0
    assert h.u8(h.M.PARTY_COUNT_ADDR) == 2


def test_borrowed_reload_reseeds_real_party_without_new_capture(rr_repo):
    h = RRHarness(rr_repo, party=(111,), load=False)
    h.seed(int(h.M.REAL_PARTY_BACKUP_ADDR), h.bytes(int(h.M.PARTY_BASE), 100))
    h.set_mon(0, 999)
    h.set_battler(0, 999)
    h.set_battle(True, flags=12)
    h.seed_u8(0x0203F840, 1)
    h.seed_u8(0x0203F841, 7)
    h.seed_u32(0x0203F844, 111)
    h.load_client()
    h.step(31)
    h.set_mon(0, 111)
    h.set_battle(False)
    h.seed_u8(0x0203F840, 0)
    h.step(90)
    assert not h.events("capture")
    assert not h.events("faint")
    assert any(e.get("party") and e["party"][0]["key"] == h.key(111) for e in h.events("tick"))


def test_context_modules_are_in_source_manifest(rr_repo):
    h = RRHarness(rr_repo)
    manifest = h.manifest()
    assert "lua/rr/context.lua" in manifest and "lua/rr/storage.lua" in manifest
    assert json.dumps(manifest)


def test_menu_frames_preserve_the_manual_deposit_baseline(rr_repo):
    h = RRHarness(rr_repo, party=(111, 333))
    h.step()
    first = h.bytes(int(h.M.PARTY_BASE), 100)
    second = h.bytes(int(h.M.PARTY_BASE) + 100, 100)
    h.seed_u32(0x030030F4, 0x080567DD)
    h.seed(int(h.M.boxMonAddr(0, 0)), h.compressed_fixture(first))
    h.seed(int(h.M.PARTY_BASE), second)
    h.seed(int(h.M.PARTY_BASE) + 100, bytes(100))
    h.seed_u8(h.M.PARTY_COUNT_ADDR, 1)
    h.step(3)
    assert not h.events("party_to_box")
    h.seed_u32(0x030030F4, 0x080565B5)
    h.step(7)
    assert [event["key"] for event in h.events("party_to_box")] == [h.key(111)]


def test_uncertain_storage_does_not_publish_an_authoritative_party(rr_repo):
    h = RRHarness(rr_repo, party=(111, 333))
    h.step()
    h.command("box_mon", key=h.key(111))
    h.step()
    h.engine_ack(ok=False, reason=23)
    h.step(35)
    assert any("STORAGE UNRESOLVED" in line for line in h.logs())
    assert h.events("tick")
    assert all("party" not in event for event in h.events("tick"))
    assert not h.events("sync_retrieve_done")


@pytest.mark.parametrize(
    "name", [bytes([0, 0xBB, 0xFF]), bytes([0, 0, 0xBB, 0xFF]), bytes([0xBB] * 7 + [0xFF])]
)
def test_complete_loaded_name_accepts_leading_space(rr_repo, name):
    # Pinned RR SaveInputText0809F7EC scans for non00/nonFF, then StringCopyN
    # uses the buffer BASE (0809F82E), preserving spaces before later letters.
    h = RRHarness(rr_repo, load=False)
    h.seed(h.SB2, name + bytes([0xFF]) * (8 - len(name)))
    assert h.M.hasLoadedTrainerName(h.SB2)
    h.load_client()
    h.step()
    assert h.events("hello")
    assert h.events("hello")[0]["trainer_name"].lstrip() == "A" * (7 if len(name) == 8 else 1)


@pytest.mark.parametrize(
    "name", [bytes(8), bytes([0xFF] * 8), bytes([0] * 7 + [0xFF]), bytes([0xBB] * 8)]
)
def test_blank_or_unterminated_name_does_not_establish_loaded_context(rr_repo, name):
    h = RRHarness(rr_repo, load=False)
    h.seed(h.SB2, name)
    assert not h.M.hasLoadedTrainerName(h.SB2)
    context_module = h.lua.eval('require("rr.context")')
    if isinstance(context_module, tuple):
        context_module = context_module[0]
    # The marker is already seeded and game pointers/count are otherwise valid.
    context = context_module.new(h.M, h.MB, h.lua.globals().memory)
    assert context.sample().party_observable is False


def test_destroyed_writer_pointer_does_not_block_storage(rr_repo):
    h = RRHarness(rr_repo, party=(111, 333))
    h.step()
    task = int(h.M.TASKS_BASE_ADDR)
    writer = h.M.POST_BATTLE_WRITER_TASKS[1]
    h.seed_u32(task, writer)
    h.seed(task + 4, bytes([1, 0xFE, 0xFF, 10]))
    assert h.M.isPostBattleSettled() is False
    h.command("box_mon", key=h.key(111))
    h.step()
    assert h.pending_native()["opcode"] == 0
    # Actual RR DestroyTask08077520 clears isActive(+4), leaving func untouched.
    h.seed_u8(task + 4, 0)
    assert h.u16(task) == writer & 0xFFFF
    assert h.M.isPostBattleSettled() is True
    h.step()
    assert h.pending_native()["opcode"] == 24


@pytest.mark.parametrize("invalid", ["vacant", "missing_flag", "zero_max_hp"])
def test_counted_invalid_slot_withholds_party_until_complete(rr_repo, invalid):
    h = RRHarness(rr_repo, party=(111, 333, 555), load=False)
    address = int(h.M.PARTY_BASE) + 100
    original = h.bytes(address, 100)
    if invalid == "vacant":
        h.seed(address, bytes(100))
    elif invalid == "missing_flag":
        h.seed_u8(address + h.M.OFF_FLAGS, 0)
    else:
        h.seed_u16(address + h.M.OFF_MAX_HP, 0)
    h.load_client()
    context_module = h.lua.eval('require("rr.context")')
    context = context_module.new(h.M, h.MB, h.lua.globals().memory)
    sample = context.sample()
    assert sample.owner == "invalid_party" and sample.party_observable is False
    assert context.storage_prerequisite("deposit", sample)[0] is False
    h.command("box_mon", key=h.key(111))
    h.step(35)
    assert not h.events("hello") and not h.events("capture") and not h.events("faint")
    assert not h.events("party_to_box") and not h.events("whiteout")
    assert all("party" not in event for event in h.events("tick"))
    assert h.pending_native()["opcode"] == 0
    # A repaired first owned snapshot is seeded as existing members, not captures.
    h.seed(address, original)
    h.step()
    assert h.events("hello") and not h.events("capture")


def test_counted_slot_validation_preserves_borrowed_precedence_and_unused_tail(rr_repo):
    h = RRHarness(rr_repo, party=(111,), load=False)
    context_module = h.lua.eval('require("rr.context")')
    if isinstance(context_module, tuple):
        context_module = context_module[0]
    context = context_module.new(h.M, h.MB, h.lua.globals().memory)
    # A duplicate and an invalid record beyond count are not owned party members.
    h.set_mon(1, 111)
    assert context.sample().party_observable is True
    h.seed_u8(h.M.PARTY_COUNT_ADDR, 3)
    h.seed(int(h.M.PARTY_BASE) + 100, bytes(100))
    h.seed_u8(0x0203F840, 1)
    sample = context.sample()
    assert sample.owner == "borrowed_party" and sample.party_observable is False
    assert sample.party_invalid is None
