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
        assert not self.held, "concurrent owner"
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


def journal(store, *, fresh=False, run="run-a", player="a", rom="a" * 40):
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    module = lua.execute((ROOT / "lua/gen3/trade_journal.lua").read_text())
    codec = lua.execute((ROOT / "lua/json_codec.lua").read_text())
    if fresh:
        assert store.data is None
        store.data = module.initial(codec)
    obj = module.new(lua.table(json=codec, store=lua.table(read=store.read, update=store.update),
                               rom_sha1=rom, player=player))
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


def test_server_final_is_bookkeeping_and_never_clears_a_reload_barrier():
    store = Store()
    _, _, obj = journal(store, fresh=True)
    epoch = arm(obj)
    assert obj.final(obj, "t", epoch, "resolved") is True
    assert obj.hidden(obj) is True and len(obj.outstanding(obj)) == 1
    _, _, restarted = journal(store)
    assert restarted.hidden(restarted) is True


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


def flash_and_ram(title="emerald", counter=7):
    from server.adapters import gen3_codec as C
    layout = C.slot_layout(title=title)
    blocks = {"sb2": bytearray(layout[0]["size"]), "sb1": bytearray(0x3D88 if title == "emerald" else 0x3D68),
              "storage": bytearray(C.STORAGE_SIZE)}
    blocks["sb2"][10:14] = (0x12345678).to_bytes(4, "little")
    count_at, party_at = (0x234, 0x238) if title == "emerald" else (0x34, 0x38)
    party = bytes(range(100))
    blocks["sb1"][count_at:count_at+4] = (1).to_bytes(4, "little")
    blocks["sb1"][party_at:party_at+100] = party
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
def test_disk_store_never_recovers_missing_torn_or_rolled_back_storage_as_empty(fault):
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
    _, module, _ = journal(store, fresh=True)
    assert module.next_epoch(0) == 1
    assert module.next_epoch(0xFFFFFFFE) == 0xFFFFFFFF
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


@pytest.mark.parametrize("title", ("firered", "leafgreen", "emerald"))
def test_reload_counter_binding_matches_the_pinned_title_symbols(title):
    store = Store()
    _, module, _ = journal(store, fresh=True)
    rows = [line.split() for line in (ROOT / f"data/gen3/pret/poke{title}.sym").read_text().splitlines()]
    address, size = next((int(r[0],16),int(r[2],16)) for r in rows if len(r)==4 and r[3]=="gSaveCounter")
    assert module.RELOAD_LAYOUTS[title].counter == address and size == 4
    assert module.RELOAD_LAYOUTS["firered_rr"] is None
