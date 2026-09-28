"""T3-R5 journal crash/identity MODEL controls; no native target admission."""
from __future__ import annotations

import copy
from pathlib import Path

import lupa
import pytest

ROOT = Path(__file__).resolve().parents[2]


class Store:
    def __init__(self):
        self.data = None
        self.fail = False
        self.writes = 0

    def read(self):
        return self.data

    def update(self, transform):
        if self.fail:
            raise OSError("durable write failed")
        new, answer = transform(self.data)
        self.data = new
        self.writes += 1
        return answer


class Files:
    """An exclusive/durable OS seam, with deliberate commit-boundary failures."""
    def __init__(self):
        self.files = {}
        self.held = False
        self.fail = None

    def lock(self, path):
        if self.held:
            return None, False, "busy"
        self.held = True
        fresh = path not in self.files
        self.files.setdefault(path, "")
        return path, fresh

    def close(self, handle):
        self.held = False
        return True

    def write(self, path, value):
        if self.fail == "head":
            raise OSError("head flush failed")
        self.files[path] = value
        return True

    def create(self, path, value):
        assert path not in self.files
        self.files[path] = value
        return True

    def append(self, path, value):
        if self.fail == "append":
            self.files[path] += value[:7]
            raise OSError("append flush failed")
        self.files[path] += value
        return True

    def table(self, lua):
        return lua.table(lock=self.lock, close=self.close, read_handle=self.files.get,
                         write_handle=self.write, read_file=self.files.get,
                         create_file=self.create, append_file=self.append)


def journal(store, *, fresh=False, run="run-a", player="a", rom="a" * 40, logs=None):
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    module = lua.execute((ROOT / "lua/gen3/trade_journal.lua").read_text())
    codec = lua.execute((ROOT / "lua/json_codec.lua").read_text())
    if fresh:
        assert store.data is None
        store.data = module.initial(codec)
    obj = module.new(lua.table(json=codec, store=lua.table(read=store.read, update=store.update),
                               rom_sha1=rom, player=player, log=logs.append if logs is not None else None))
    assert obj.bind(obj, run, "12345678") is True
    return lua, module, obj


def arm(obj, token="t"):
    epoch = obj.allocate(obj)
    assert obj.arm(obj, token, epoch) is True
    return epoch


def test_restart_recovers_intent_and_preserves_originating_epoch():
    store = Store()
    _, _, first = journal(store, fresh=True)
    epoch = arm(first)
    assert first.hidden(first) is True
    _, _, second = journal(store)
    outstanding = second.outstanding(second)
    assert len(outstanding) == 1 and outstanding[1].token == "t" and outstanding[1].epoch == epoch
    assert second.allocate(second) > epoch
    assert second.hidden(second) is True


@pytest.mark.parametrize("bad", (None, "", "broken", '{"schema":1}', 'SLINK-TRADE-JOURNAL-1\npartial'))
def test_missing_or_corrupt_store_is_never_an_empty_journal(bad):
    store = Store()
    _, _, obj = journal(store, fresh=True)
    store.data = bad
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    module = lua.execute((ROOT / "lua/gen3/trade_journal.lua").read_text())
    codec = lua.execute((ROOT / "lua/json_codec.lua").read_text())
    broken = module.new(lua.table(json=codec, store=lua.table(read=store.read, update=store.update),
                                  rom_sha1="a" * 40, player="a"))
    assert broken.hidden(broken) is True
    assert broken.allocate(broken)[0] is None
    assert store.data == bad


def test_failed_write_cannot_authorize_a_scene():
    store = Store()
    _, _, obj = journal(store, fresh=True)
    epoch = obj.allocate(obj)
    before = store.data
    store.fail = True
    assert obj.arm(obj, "t", epoch)[0] is None
    assert obj.hidden(obj) is True and store.data == before


@pytest.mark.parametrize("fault", ("read", "write"))
def test_permanent_journal_fault_logs_its_reason_once_and_stays_closed(fault):
    store, logs = Store(), []
    _, _, obj = journal(store, fresh=True, logs=logs)
    saved = store.data
    if fault == "read":
        store.data = "broken"
        assert obj.hidden(obj) is True
    else:
        store.fail = True
        assert obj.allocate(obj)[0] is None
    assert len(logs) == 1 and logs[0] == obj.failure
    assert ("invalid trade journal" if fault == "read" else "durable write failed") in logs[0]
    store.data, store.fail = saved, False
    for _ in range(3):
        assert obj.hidden(obj) is True and obj.ready(obj) is False
        assert obj.allocate(obj)[0] is None
    assert len(logs) == 1


def test_server_final_is_bookkeeping_and_never_clears_a_reload_barrier():
    store = Store()
    _, _, obj = journal(store, fresh=True)
    epoch = arm(obj)
    assert obj.final(obj, "t", epoch, "resolved") is True
    assert obj.hidden(obj) is True and len(obj.outstanding(obj)) == 1
    _, _, restarted = journal(store)
    assert restarted.hidden(restarted) is True


def test_busy_final_retirement_cannot_mark_native_save_allowed_early():
    store = Store()
    _, _, obj = journal(store, fresh=True)
    epoch = arm(obj)
    assert obj.final(obj, "t", epoch, "resolved") is True
    original = obj.final
    seen = []

    def busy_once(self, *args):
        seen.append(args)
        if len(seen) == 1:
            return None, "trade journal lock busy"
        return original(self, *args)

    obj.final = busy_once
    assert obj.native_saved(obj, "t", epoch)[0] is None
    assert obj.hidden(obj) is True
    assert len(obj.state.records) == 1
    assert obj.native_saved(obj, "t", epoch) is True
    assert obj.hidden(obj) is False
    assert len(obj.state.records) == 0


def test_independent_writers_allocate_unique_monotonic_epochs():
    store = Store()
    _, _, one = journal(store, fresh=True)
    _, _, two = journal(store, player="b")
    assert [one.allocate(one), two.allocate(two), one.allocate(one)] == [1, 2, 3]


def test_record_is_never_rebound_to_another_run():
    store = Store()
    _, _, first = journal(store, fresh=True)
    arm(first)
    _, _, other = journal(store, run="run-b")
    assert len(other.outstanding(other)) == 0
    assert other.hidden(other) is True  # foreign unresolved intent is not permission to publish RAM


def test_two_prepared_runs_cannot_publish_conflicting_intents_from_stale_state():
    store = Store()
    _, _, one = journal(store, fresh=True)
    _, _, two = journal(store, run="run-b")
    first_epoch, second_epoch = one.allocate(one), two.allocate(two)
    assert one.arm(one, "first", first_epoch) is True
    assert two.arm(two, "second", second_epoch) is not True
    _, _, restarted = journal(store)
    assert len(restarted.outstanding(restarted)) == 1
    assert restarted.outstanding(restarted)[1].token == "first"


def flash_and_ram(title="emerald", counter=7, cfru=False):
    from server.adapters import gen3_codec as C
    layout = C.slot_layout(C.CHUNK_SIZE_CFRU if cfru else C.CHUNK_SIZE_VANILLA, title=title)
    blocks = {"sb2": bytearray(layout[0]["size"]), "sb1": bytearray(0x3D88 if title == "emerald" else 0x3D68),
              "storage": bytearray(C.STORAGE_SIZE)}
    blocks["sb2"][10:14] = (0x12345678).to_bytes(4, "little")
    count_at, party_at = (0x234, 0x238) if title == "emerald" else (0x34, 0x38)
    party = bytes(range(100))
    blocks["sb1"][count_at:count_at+4] = (1).to_bytes(4, "little")
    blocks["sb1"][party_at:party_at+100] = party
    blocks["sb1"][-0x10] = 0xA5  # past CFRU's id-4 chunk (0xD98), inside vanilla's (0xEE8)
    flash = bytearray(b"\xff" * C.FLASH_SIZE)
    for row in layout:
        data = blocks[row["object"]][row["offset"]:row["offset"]+row["size"]]
        at = row["id"] * C.SECTOR_SIZE
        flash[at:at+C.SECTOR_SIZE] = C.write_sector(data, row["id"], counter, layout)
    ram = {"counter": counter, "ot_id": 0x12345678, "party_count": 1, "party": party,
           "sb1": 0x02025000, "sb2": 0x02024000}
    return bytes(flash), ram


@pytest.mark.parametrize("fault", (None, "no_boot", "rollback", "party", "counter", "trainer", "torn_flash", "torn_ram", "checksum", "rr"))
def test_reload_needs_boot_and_stable_flash_counter_trainer_party(fault):
    store = Store()
    lua, module, obj = journal(store, fresh=True)
    epoch = arm(obj)
    flash, ram = flash_and_ram()
    after = copy.deepcopy(ram)
    request = {"title": "emerald", "rom_sha1": "a" * 40, "boot_seen": True, "flash_before": flash, "flash_after": flash,
               "ram_before": ram, "ram_after": after}
    if fault in ("no_boot", "rollback"):
        request["boot_seen"] = False
    elif fault == "party":
        ram["party"] = after["party"] = b"changed unsaved RAM".ljust(100, b"\0")
    elif fault == "counter":
        ram["counter"] = after["counter"] = 8
    elif fault == "trainer":
        ram["ot_id"] = after["ot_id"] = 9
    elif fault == "torn_flash":
        request["flash_after"] = flash[:-1] + b"\0"
    elif fault == "torn_ram":
        after["sb2"] += 4
    elif fault == "checksum":
        bad = bytes([flash[0] ^ 1]) + flash[1:]
        request["flash_before"] = request["flash_after"] = bad
    elif fault == "rr":
        request["title"] = "firered_rr"
    proof = module.verify_reload(lua.table_from(request, recursive=True))
    if fault:
        assert proof[0] is None
        assert obj.hidden(obj) is True
    else:
        assert proof.counter == 7
        assert obj.qualify(obj, proof) is True
        assert obj.hidden(obj) is True  # qualified bytes still need the ordered declaration
        assert obj.declared(obj, "t", epoch) is True
        assert obj.hidden(obj) is False
        assert obj.final(obj, "t", epoch, "committed") is True
        _, _, restarted = journal(store)
        assert restarted.hidden(restarted) is False


@pytest.mark.parametrize("fault", (None, "missing_log", "missing_guard", "rollback", "append", "head"))
def test_disk_store_refuses_missing_torn_or_mismatched_rollback(fault):
    files = Files()
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    module = lua.execute((ROOT / "lua/gen3/trade_journal.lua").read_text())
    codec = lua.execute((ROOT / "lua/json_codec.lua").read_text())
    backend = module.file_store(lua.table(json=codec, fs=files.table(lua), path="journal"))
    obj = module.new(lua.table(json=codec, store=backend, rom_sha1="a" * 40, player="a"))
    assert obj.bind(obj, "run-a", "12345678")
    initial = files.files["journal.log"]
    epoch = obj.allocate(obj)
    assert obj.arm(obj, "t", epoch)
    if fault == "missing_log":
        del files.files["journal.log"]
    elif fault == "missing_guard":
        del files.files["journal.guard"]
    elif fault == "rollback":
        files.files["journal.log"] = initial
    elif fault in ("append", "head"):
        files.fail = fault
        assert obj.allocate(obj)[0] is None
        files.fail = None
    other = module.new(lua.table(json=codec, store=backend, rom_sha1="a" * 40, player="a"))
    other.bind(other, "run-a", "12345678")
    assert other.hidden(other) is True
    if fault:
        assert other.failure and other.allocate(other)[0] is None
    else:
        assert other.allocate(other) > epoch
        assert len(other.outstanding(other)) == 1
    assert not files.held


@pytest.mark.parametrize("born_under_hold", (False, True))
def test_shared_guard_contention_recovers_on_next_frame_without_reissuing_epoch(born_under_hold):
    """A's temporary guard hold must not poison B for the rest of the emulator session."""
    files = Files()
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    module = lua.execute((ROOT / "lua/gen3/trade_journal.lua").read_text())
    codec = lua.execute((ROOT / "lua/json_codec.lua").read_text())
    backend = module.file_store(lua.table(json=codec, fs=files.table(lua), path="journal"))
    frame = [100]

    def client(player):
        obj = module.new(lua.table(json=codec, store=backend, rom_sha1="a" * 40,
                                   player=player, frame=lambda: frame[0]))
        assert obj.bind(obj, "run-a", "12345678")
        return obj

    a = client("a")
    assert a.allocate(a) == 1
    b = None if born_under_hold else client("b")
    if b is not None:
        frame[0] += 1  # the next emulator frame must perform its own exclusive read
    holder, fresh = files.lock("journal.guard")
    assert holder and fresh is False
    if b is None:
        b = client("b")
    assert b.hidden(b) is True  # no unverified party may be reported during contention
    assert b.ready(b) is False  # do not advertise native trade while the guard is unavailable
    assert b.failure is None, "a transient guard collision must not poison the session"
    assert b.allocate(b)[0] is None  # a command cannot spend an epoch without the guard
    assert files.close(holder)
    frame[0] += 1
    assert b.ready(b) is True
    assert b.hidden(b) is False
    assert b.allocate(b) == 2
    assert a.allocate(a) == 3
    assert files.held is False


def test_writer_contention_retries_later_without_spending_an_epoch():
    files = Files()
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    module = lua.execute((ROOT / "lua/gen3/trade_journal.lua").read_text())
    codec = lua.execute((ROOT / "lua/json_codec.lua").read_text())
    backend = module.file_store(lua.table(json=codec, fs=files.table(lua), path="journal"))
    frame = [10]
    a = module.new(lua.table(json=codec, store=backend, rom_sha1="a" * 40, player="a",
                             frame=lambda: frame[0]))
    assert a.bind(a, "run-a", "12345678")
    assert a.allocate(a) == 1
    b = module.new(lua.table(json=codec, store=backend, rom_sha1="a" * 40, player="b",
                             frame=lambda: frame[0]))
    assert b.bind(b, "run-a", "12345678")
    holder, _ = files.lock("journal.guard")
    frame[0] += 1
    assert b.allocate(b)[0] is None
    assert b.failure is None
    assert files.close(holder)
    frame[0] += 1
    assert b.allocate(b) == 2
    assert a.allocate(a) == 3


def test_busy_precommit_proof_does_not_publish_unchanged_until_retried():
    world, journal, _ = journaled_trade_world()
    world.deps.precommit_refusal_reasons = world.lua.table_from({"model_pre_commit_refused": True})
    world.trade = world.lua.execute((ROOT / "lua/gen3/trade.lua").read_text()).new(world.deps)
    scene = world.start()
    original = journal.precommit_unchanged
    seen = []

    def busy_once(self, *args):
        seen.append(args)
        if len(seen) == 1:
            return None, "trade journal lock busy"
        return original(self, *args)

    journal.precommit_unchanged = busy_once
    scene["done"]("native refused", 7, "model_pre_commit_refused")
    assert not [fields for event, fields in world.events if event == "trade_done"]
    assert journal.hidden(journal) is True
    world.tick()
    assert len(seen) >= 2
    assert len([fields for event, fields in world.events if event == "trade_done"]) == 1
    assert journal.hidden(journal) is False


def test_permanent_precommit_journal_failure_never_claims_certain_unchanged():
    world, journal, _ = journaled_trade_world()
    world.deps.precommit_refusal_reasons = world.lua.table_from({"model_pre_commit_refused": True})
    world.trade = world.lua.execute((ROOT / "lua/gen3/trade.lua").read_text()).new(world.deps)
    scene = world.start()
    journal.precommit_unchanged = lambda *_: (None, "trade journal: durable write failed")
    scene["done"]("native refused", 7, "model_pre_commit_refused")
    world.tick()
    reports = [fields for event, fields in world.events if event == "trade_done"]
    assert len(reports) == 1 and reports[0].get("uncertain") is True
    assert journal.hidden(journal) is True


def test_saved_result_waiting_on_guard_cannot_commit_in_a_new_session_epoch():
    world, journal, _ = journaled_trade_world()
    scene = world.start()
    original = journal.native_saved
    seen = []

    def busy_once(self, *args):
        seen.append(args)
        if len(seen) == 1:
            return None, "trade journal lock busy"
        return original(self, *args)

    journal.native_saved = busy_once
    world.progress(scene, commit_entered=True, scene_done=True, save_success=True,
                   final_result="committed")
    world.received()
    scene["done"](None, 0, None)
    assert not [fields for event, fields in world.events if event == "trade_done"]
    world.epoch += 1
    world.tick()
    reports = [fields for event, fields in world.events if event == "trade_done"]
    assert len(reports) == 1 and reports[0].get("uncertain") is True
    assert journal.hidden(journal) is True


@pytest.mark.parametrize("busy_at_capability", (False, True))
def test_busy_prepare_allocation_waits_without_refusal_or_duplicate_epoch(busy_at_capability):
    world, journal, store = journaled_trade_world()
    original = journal.allocate
    seen = []

    def busy_once(self):
        seen.append(True)
        if len(seen) == 1 and not busy_at_capability:
            return None, "trade journal lock busy"
        return original(self)

    journal.allocate = busy_once
    if busy_at_capability:
        original_ready = journal.ready
        journal.busy = True
        journal.ready = lambda self: False if self.busy else original_ready(self)
    world.prepare()
    assert not [fields for event, fields in world.events if event == "apply_ready"]
    journal.busy = None
    world.tick()
    assert len(seen) >= (1 if busy_at_capability else 2)
    assert [fields for event, fields in world.events if event == "apply_ready"] == [
        {"token": "t", "ok": True}]
    assert journal.state.counter == 1 and store.writes == 1


def test_busy_prepare_keeps_its_original_deadline_and_never_spends_an_epoch_after_expiry():
    world, journal, store = journaled_trade_world()
    journal.allocate = lambda *_: (None, "trade journal lock busy")
    world.prepare()
    assert not [fields for event, fields in world.events if event == "apply_ready"]
    world.frame += world.deps.prepare_frames + 1
    world.tick()
    assert [fields for event, fields in world.events if event == "apply_ready"] == [
        {"token": "t", "ok": False}]
    assert journal.state.counter == 0 and store.writes == 0 and world.jobs == []


def test_busy_intent_arm_retries_without_duplicate_native_staging():
    world, journal, _ = journaled_trade_world()
    world.prepare()
    world.command("apply", token="t", old_key=world.rows[0]["key"], slot=0, blob_hex="05" * 100)
    world.tick()
    stage = world.jobs[-1]
    world.dispatch(stage)
    original = journal.arm
    seen = []

    def busy_once(self, *args):
        seen.append(args)
        if len(seen) == 1:
            return None, "trade journal lock busy"
        return original(self, *args)

    journal.arm = busy_once
    stage["done"](None, 0, None)
    assert [job["step"] for job in world.jobs] == ["enemy"]
    assert not [fields for event, fields in world.events if event == "trade_done"]
    world.tick()
    assert len(seen) >= 2
    assert [job["step"] for job in world.jobs] == ["enemy", "scene"]
    assert journal.state.counter == 1 and len(journal.state.records) == 1


def test_scene_guard_retains_unposted_job_only_for_busy_lease_within_deadline():
    world, journal, _ = journaled_trade_world()
    scene = world.start()
    original = journal.lease_open
    journal.lease_open = lambda *_: (False, "trade journal lock busy")
    assert scene["valid"]() == (False, "guard:journal_busy", True)
    assert [job["step"] for job in world.jobs] == ["enemy", "scene"]
    assert journal.hidden(journal) is True
    journal.lease_open = original
    assert scene["valid"]() is True
    world.frame += world.deps.apply_frames + 1
    journal.lease_open = lambda *_: (False, "trade journal lock busy")
    assert scene["valid"]() == (False, "guard:apply_expired")


def test_saved_result_identity_is_latched_before_a_busy_journal_ack():
    world, journal, _ = journaled_trade_world()
    scene = world.start()
    original = journal.native_saved
    seen = []

    def busy_once(self, *args):
        seen.append(args)
        if len(seen) == 1:
            return None, "trade journal lock busy"
        return original(self, *args)

    journal.native_saved = busy_once
    world.progress(scene, commit_entered=True, scene_done=True, save_success=True,
                   final_result="committed")
    world.received()
    scene["done"](None, 0, None)
    assert not [fields for event, fields in world.events if event == "trade_done"]
    world.rows[0] = {"key": "later:unrelated", "slot": 0, "species": 1, "hp": 20}
    world.tick()
    reports = [fields for event, fields in world.events if event == "trade_done"]
    assert reports == [{"token": "t", "slot": 0, "new_key": "00000005:00000006", "new_species": 65}]
    assert journal.hidden(journal) is False


def test_unavailable_guard_for_a_non_contention_reason_stays_fail_closed():
    files = Files()
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    module = lua.execute((ROOT / "lua/gen3/trade_journal.lua").read_text())
    codec = lua.execute((ROOT / "lua/json_codec.lua").read_text())
    fs = files.table(lua)
    fs.lock = lambda _path: (None, False, "denied")
    backend = module.file_store(lua.table(json=codec, fs=fs, path="journal"))
    obj = module.new(lua.table(json=codec, store=backend, rom_sha1="a" * 40, player="a"))
    assert obj.failure is not None
    assert obj.hidden(obj) is True
    assert files.files == {}, "an unavailable guard must never create a new journal"


def journaled_trade_world():
    from tests.unit.test_gen3_trade import TradeWorld
    world = TradeWorld()
    module = world.lua.execute((ROOT / "lua/gen3/trade_journal.lua").read_text())
    codec = world.lua.execute((ROOT / "lua/json_codec.lua").read_text())
    store = Store()
    store.data = module.initial(codec)
    journal = module.new(world.lua.table(json=codec, store=world.lua.table(read=store.read, update=store.update),
                                         rom_sha1="a" * 40, player="a"))
    journal.bind(journal, "run-a", "00000002")
    world.deps.journal = journal
    world.trade = world.lua.execute((ROOT / "lua/gen3/trade.lua").read_text()).new(world.deps)
    return world, journal, store


def test_native_scene_is_never_enqueued_before_durable_intent():
    world, journal, store = journaled_trade_world()
    world.prepare()
    world.command("apply", token="t", old_key=world.rows[0]["key"], slot=0, blob_hex="05" * 100)
    world.tick()
    stage = world.jobs[-1]
    world.dispatch(stage)
    stage["done"](None, 0, None)
    assert world.jobs[-1]["step"] == "scene"
    records = journal.outstanding(journal)
    assert len(records) == 1 and records[1].token == "t"
    assert store.writes >= 2  # durable allocation and durable intent


def test_failed_write_ahead_intent_never_enqueues_or_publishes_scene():
    world, journal, store = journaled_trade_world()
    world.prepare()
    world.command("apply", token="t", old_key=world.rows[0]["key"], slot=0, blob_hex="05" * 100)
    world.tick()
    stage = world.jobs[-1]
    world.dispatch(stage)
    store.fail = True
    stage["done"](None, 0, None)
    assert [j["step"] for j in world.jobs] == ["enemy"]
    assert journal.hidden(journal) is True


def test_reset_is_discontinuity_and_not_qualified_reload():
    world, journal, _ = journaled_trade_world()
    world.start()
    world.trade.reset(world.trade)
    assert not world.trade.reloaded(world.trade, "t", world.epoch)
    assert journal.hidden(journal) is True


def test_a_missing_journal_refuses_native_trade_preparation():
    from tests.unit.test_gen3_trade import TradeWorld
    world = TradeWorld()
    world.deps.journal = None
    world.trade = world.lua.execute((ROOT / "lua/gen3/trade.lua").read_text()).new(world.deps)
    world.prepare()
    assert world.events[-1] == ("apply_ready", {"token": "t", "ok": False})


def test_uint32_epoch_boundary_never_wraps_or_resets():
    store = Store()
    lua, module, _ = journal(store, fresh=True)
    assert module.next_epoch(0) == 1
    assert module.next_epoch(0xFFFFFFFE) == 0xFFFFFFFF
    codec = lua.execute((ROOT / "lua/json_codec.lua").read_text())
    maximum = module.next_epoch(float(0xFFFFFFFE))
    assert lua.eval("math.type")(maximum) == "integer"
    assert codec.encode(maximum) == "4294967295"
    assert lua.eval("math.type")(codec.decode(codec.encode(maximum))) == "integer"
    for bad in (0xFFFFFFFF, 0x100000000, -1, True, 1.5):
        assert module.next_epoch(bad)[0] is None


def test_final_verdict_must_match_the_bound_token_and_epoch_and_is_idempotent():
    store = Store()
    _, _, obj = journal(store, fresh=True)
    epoch = arm(obj)
    before = store.data
    assert obj.final(obj, "other", epoch, "committed") is False
    assert obj.final(obj, "t", epoch+1, "committed") is False
    assert store.data == before
    assert obj.final(obj, "t", epoch, "committed") is True
    finalized = store.data
    assert obj.final(obj, "t", epoch, "committed") is True
    assert store.data == finalized and obj.hidden(obj) is True


def test_proof_for_another_cartridge_cannot_release_this_journal():
    store = Store()
    lua, module, obj = journal(store, fresh=True)
    arm(obj)
    flash, ram = flash_and_ram()
    proof = module.verify_reload(lua.table_from({"title": "emerald", "rom_sha1": "b"*40,
        "boot_seen": True, "flash_before": flash, "flash_after": flash,
        "ram_before": ram, "ram_after": dict(ram)}, recursive=True))
    assert proof.counter == 7
    assert obj.qualify(obj, proof)[0] is None and obj.hidden(obj) is True


@pytest.mark.parametrize("run", ("run-a", "run-b"))
def test_binding_again_invalidates_previously_qualified_reload_evidence(run):
    store = Store()
    lua, module, obj = journal(store, fresh=True)
    epoch = arm(obj)
    flash, ram = flash_and_ram()
    proof = module.verify_reload(lua.table_from({"title": "emerald", "rom_sha1": "a"*40,
        "boot_seen": True, "flash_before": flash, "flash_after": flash,
        "ram_before": ram, "ram_after": dict(ram)}, recursive=True))
    assert obj.qualify(obj, proof) is True
    assert obj.bind(obj, run, "12345678") is True
    if run != "run-a":
        assert obj.bind(obj, "run-a", "12345678") is True
    assert obj.declared(obj, "t", epoch)[0] is None
    assert obj.hidden(obj) is True


@pytest.mark.parametrize("field", ("run_id", "token"))
@pytest.mark.parametrize("bad", ("", "bad\x00id", "bad\nid", "bad\tid", "bad\x7fid", "café", b"bad\xffid"))
def test_server_identifiers_refuse_non_printable_ascii_by_name_without_writing(field, bad):
    store = Store()
    _, _, obj = journal(store, fresh=True)
    epoch = obj.allocate(obj)
    before = store.data
    refusal = obj.bind(obj, bad, "12345678") if field == "run_id" else obj.arm(obj, bad, epoch)
    assert refusal is not True
    assert refusal[0] is None and field in refusal[1] and "ASCII" in refusal[1]
    assert store.data == before


def test_printable_ascii_identifiers_keep_their_exact_json_escaped_value():
    store = Store()
    _, _, obj = journal(store, fresh=True)
    run, value = 'run !~ "\\', 'token !~ "\\'
    assert obj.bind(obj, run, "12345678") is True
    epoch = obj.allocate(obj)
    assert obj.arm(obj, value, epoch) is True
    _, _, restarted = journal(store, run=run)
    assert restarted.outstanding(restarted)[1].token == value


@pytest.mark.parametrize("floating", (False, True))
def test_originating_epoch_round_trips_as_integer_through_journal_and_wire_json(floating):
    store = Store()
    _, _, obj = journal(store, fresh=True)
    allocated = obj.allocate(obj)
    assert obj.arm(obj, "t", float(allocated) if floating else allocated) is True
    lua, module, restarted = journal(store)
    codec = lua.execute((ROOT / "lua/json_codec.lua").read_text())
    outstanding = restarted.outstanding(restarted)
    assert lua.eval("math.type")(outstanding[1].epoch) == "integer"
    wire = codec.decode(codec.encode(outstanding))
    assert lua.eval("math.type")(wire[1].epoch) == "integer"
    assert wire[1].epoch == allocated
    flash, ram = flash_and_ram()
    proof = module.verify_reload(lua.table_from({"title": "emerald", "rom_sha1": "a"*40,
        "boot_seen": True, "flash_before": flash, "flash_after": flash,
        "ram_before": ram, "ram_after": dict(ram)}, recursive=True))
    assert restarted.qualify(restarted, proof) is True
    assert restarted.declared(restarted, wire[1].token, wire[1].epoch) is True
    assert restarted.hidden(restarted) is False


@pytest.mark.parametrize("title", ("firered", "leafgreen", "emerald"))
def test_reload_counter_binding_matches_the_pinned_title_symbols(title):
    store = Store()
    _, module, _ = journal(store, fresh=True)
    rows = [line.split() for line in (ROOT / f"data/gen3/pret/poke{title}.sym").read_text().splitlines()]
    address, size = next((int(r[0],16),int(r[2],16)) for r in rows if len(r)==4 and r[3]=="gSaveCounter")
    assert module.RELOAD_LAYOUTS[title].counter == address and size == 4


def test_rr_reload_layout_is_the_cfru_chunk_table_and_rom_pinned_pointers():
    """RR is keyed by its wire rom_type. Its sectors use CFRU's 0xFF0 chunk
    (docs/gen3/research/rr_save_layout.md sec 1), and its SaveBlock pointers are the
    write_checkpoint's ROM-read pool words, not the profile's legacy SB1_PTR_ADDR."""
    import json
    _, module, _ = journal(Store(), fresh=True)
    rr = module.RELOAD_LAYOUTS["firered_rr"]
    assert rr is not None and rr.chunk == 0xFF0
    assert (rr.sb2_size, rr.sb1_size, rr.count_offset, rr.party_offset) == (0xF24, 0x3D68, 0x34, 0x38)
    pointers = json.loads((ROOT / "data/games/gen3_rr/write_checkpoint.json").read_text())["radical_red"]["pointers"]
    assert (rr.sb1_ptr, rr.sb2_ptr) == (pointers["gSaveBlock1Ptr"]["address"], pointers["gSaveBlock2Ptr"]["address"])
    assert module.RELOAD_LAYOUTS["firered"].chunk in (None, 0xF80)


def test_rr_save_counter_is_the_word_rrs_cfru_save_bodies_load():
    """[ROM] gSaveCounter: every FR save function's pool word, plus the two CFRU save
    bodies RR adds (0x090B8C70, 0x090B8DC4), name the same IWRAM word."""
    import os
    rom = Path(os.environ.get("SLINK_GEN3_ROMS", ROOT)) / "Pokemon - Radical Red.gba"
    if not rom.exists():
        pytest.skip("RR base ROM absent")
    data = rom.read_bytes()
    _, module, _ = journal(Store(), fresh=True)
    want = module.RELOAD_LAYOUTS["firered_rr"].counter
    for pool in (0x090B8C70, 0x090B8DC4, 0x080DA084):
        assert int.from_bytes(data[pool - 0x08000000:pool - 0x08000000 + 4], "little") == want


@pytest.mark.parametrize("fault", (None, "vanilla_chunk"))
def test_rr_reload_proof_accepts_only_a_cfru_chunked_battery(fault):
    store = Store()
    lua, module, obj = journal(store, fresh=True)
    epoch = arm(obj)
    flash, ram = flash_and_ram(title="firered", cfru=fault is None)
    request = {"title": "firered_rr", "rom_sha1": "a" * 40, "boot_seen": True, "flash_before": flash,
               "flash_after": flash, "ram_before": ram, "ram_after": copy.deepcopy(ram)}
    proof = module.verify_reload(lua.table_from(request, recursive=True))
    if fault:
        assert proof[0] is None and "checksum" in proof[1]
    else:
        assert proof.counter == 7 and obj.qualify(obj, proof) is True
        assert obj.declared(obj, "t", epoch) is True
