"""T3-R5 production-client withholding controls (native/storage MODEL seams)."""
import json

import pytest

from tests.unit.test_gen3_trade import durable_client, start_client_trade, swap_in_partner


def uncertain_client(monkeypatch):
    world, carrier, blob = durable_client(monkeypatch)
    start_client_trade(world, carrier, blob)
    swap_in_partner(world)
    carrier.ack(commit_entered=True, scene_done=True)
    world.step()
    return world, carrier


def test_uncertain_hello_tick_and_safe_are_explicitly_hidden(monkeypatch):
    world, carrier = uncertain_client(monkeypatch)
    world.connected = False
    world.step()
    world.connected = True
    world.client.pending_safe = True
    world.step(35)
    hello = world.events("hello")[-1]
    assert hello["party_hidden"] is True and hello["party"] == []
    assert hello["trade_outstanding"][0]["token"] == "t"
    assert hello["trade_outstanding"][0]["epoch"] > 0
    assert world.events("tick")[-1]["party_hidden"] is True
    assert world.events("safe")[-1]["party_hidden"] is True
    assert "pc_boxes" not in hello


def test_counter_rollback_never_publishes_the_unsaved_received_party(monkeypatch):
    world, _ = uncertain_client(monkeypatch)
    start = len(world.sent)
    world.frame = 1
    world.step(35)
    snapshots = [m for m in world.sent[start:] if m["event"] in ("hello", "tick", "safe")]
    assert snapshots and all(m.get("party_hidden") is True for m in snapshots)
    assert all(not m.get("party") for m in snapshots)


def test_terminal_server_bookkeeping_does_not_unhide_unsaved_ram(monkeypatch):
    world, carrier = uncertain_client(monkeypatch)
    record = carrier.journal_model.journal.outstanding(carrier.journal_model.journal)[1]
    # Feed the real command dispatcher; this is not a direct journal API shortcut.
    world.replies.append(json.dumps({"commands": [
        {"cmd": "trade_final", "token": "t", "epoch": record.epoch, "verdict": "resolved"}]}))
    world.step(35)
    assert carrier.journal_model.journal.hidden(carrier.journal_model.journal) is True
    assert world.events("tick")[-1].get("party_hidden") is True


@pytest.mark.parametrize("busy_before_command", (False, True))
def test_busy_terminal_notification_is_retried_after_the_next_frame(monkeypatch, busy_before_command):
    world, carrier = uncertain_client(monkeypatch)
    journal = carrier.journal_model.journal
    record = journal.outstanding(journal)[1]
    original = journal.final
    if busy_before_command:
        original_ready = journal.ready
        journal.busy = True
        journal.ready = lambda self: False if self.busy else original_ready(self)
    seen = []

    def busy_once(self, *args):
        seen.append(args)
        if len(seen) == 1:
            return None, "trade journal lock busy"
        journal.busy = None
        return original(self, *args)

    journal.final = busy_once
    world.replies.append(json.dumps({"commands": [
        {"cmd": "trade_final", "token": "t", "epoch": record.epoch, "verdict": "resolved"}]}))
    world.step(2)
    assert len(seen) >= 2, "a one-frame busy must not drop the terminal notification"
    assert journal.state.records[1].final == "resolved"
    assert journal.hidden(journal) is True  # bookkeeping never proves saved RAM


@pytest.mark.parametrize("rebound_run", ("model-run", "another-run"))
def test_queued_terminal_survives_disconnect_only_for_its_bound_run(monkeypatch, rebound_run):
    world, carrier = uncertain_client(monkeypatch)
    journal = carrier.journal_model.journal
    record = journal.outstanding(journal)[1]
    world.replies.append(json.dumps({"commands": [{"cmd": "config", "run_id": "model-run"}]}))
    world.step()
    original = journal.final
    seen = []

    def busy_once(self, *args):
        seen.append(args)
        if len(seen) == 1:
            return None, "trade journal lock busy"
        return original(self, *args)

    journal.final = busy_once
    world.replies.append(json.dumps({"commands": [
        {"cmd": "trade_final", "token": "t", "epoch": record.epoch, "verdict": "resolved"}]}))
    world.step()
    assert journal.state.records[1].final == ""
    world.connected = False
    world.step(2)
    assert journal.state.records[1].final == "", "a disconnected client cannot consume the queued final"
    world.connected = True
    world.replies.append(json.dumps({"commands": [{"cmd": "config", "run_id": rebound_run}]}))
    world.step(2)
    if rebound_run == "model-run":
        assert journal.state.records[1].final == "resolved" and len(seen) >= 2
    else:
        assert journal.state.records[1].final == ""
        assert any("pending trade_final discarded" in line for line in world.logs)


def test_busy_post_save_journal_result_retries_without_uncertain_report(monkeypatch):
    world, carrier, blob = durable_client(monkeypatch)
    start_client_trade(world, carrier, blob)
    journal = carrier.journal_model.journal
    original = journal.native_saved
    seen = []

    def busy_once(self, *args):
        seen.append(args)
        if len(seen) == 1:
            return None, "trade journal lock busy"
        return original(self, *args)

    journal.native_saved = busy_once
    swap_in_partner(world)
    carrier.ack(commit_entered=True, scene_done=True, save_success=True, final_result="committed")
    world.step(2)
    assert len(seen) >= 2, "the saved result must wait for a fresh journal read"
    assert not [m for m in world.events("trade_done") if m.get("uncertain")]
    assert world.events("trade_done")[-1].get("new_key")
    assert journal.hidden(journal) is False


@pytest.mark.parametrize("fault", (None, "raises", "false", "missing"))
def test_native_save_flushes_host_before_a_final_can_retire_the_intent(monkeypatch, fault):
    world, carrier, blob = durable_client(monkeypatch)
    start_client_trade(world, carrier, blob)
    journal = carrier.journal_model.journal
    world.replies.append(json.dumps({"commands": [
        {"cmd": "trade_final", "token": "t", "verdict": "resolved"}]}))
    world.step()
    assert journal.state.records[1].final == "resolved" and journal.hidden(journal)
    flushed = []

    def saveram():
        assert journal.hidden(journal) and len(journal.state.records) == 1
        flushed.append(True)
        if fault == "raises":
            raise OSError("MODEL host disk flush failed")
        if fault == "false":
            return False
        world._saveram()

    world.io.saveram = None if fault == "missing" else saveram
    swap_in_partner(world)
    carrier.ack(commit_entered=True, scene_done=True, save_success=True, final_result="committed")
    world.step()
    if fault is None:
        assert flushed == [True] and world.saveram_calls == 1
        assert len(journal.state.records) == 0
        assert not world.events("trade_done")[-1].get("uncertain")
    else:
        assert journal.hidden(journal) and len(journal.state.records) == 1
        assert world.events("trade_done")[-1]["uncertain"] is True
        assert world.events("trade_done")[-1]["after_reset"] is True


def test_production_client_sends_visible_tick_before_native_apply_ready(monkeypatch):
    from tests.unit.gen3_trade_journal_model import JournalModel
    from tests.unit.gen3_world import World
    from tests.unit.test_gen3_trade import KB, A, B, CartridgeModel, party

    class PreparingCarrier(CartridgeModel):
        def __call__(self, runtime):
            native = super().__call__(runtime)
            self.pending = []
            native.trade_authorized = lambda *_: True
            native.prepare_trade = lambda _, cmd, done, valid: (
                self.pending.append((cmd, done, valid)) or runtime.table())
            return native

    monkeypatch.setenv("SLINK_GEN3_BATTLE_NONCE", "0000BEEF")
    carrier = PreparingCarrier()
    world = World("gen3_rr", "radical_red", "companion", native=carrier, journal=JournalModel())
    world.set_party(party(A, B))
    world.step_to(60)
    visible = [False]
    original = world.client.driver.tick_fields

    def tick_fields():
        fields = original()
        if not visible[0]:
            fields.party_hidden = True
            fields.party = None
        return fields

    world.client.driver.tick_fields = tick_fields
    world.command(cmd="apply_prepare", token="t", slot=1, old_key=KB)
    world.step()
    assert carrier.pending
    before = len(world.sent)
    carrier.pending[0][1](None, world.lua.table(**carrier.visit, old_key=KB))
    assert not world.events("apply_ready")
    world.step()
    assert not world.events("apply_ready")
    visible[0] = True
    world.step()
    sent = world.sent[before:]
    assert [m["event"] for m in sent] == ["tick", "apply_ready"]
    assert "party_hidden" not in sent[0] and len(sent[0]["party"]) == 2
    assert sent[1]["ok"] is True


def test_apply_trade_waits_out_a_one_frame_journal_guard_collision(monkeypatch):
    from tests.unit.test_gen3_client import apply
    from tests.unit.test_gen3_trade import KB

    world, carrier, blob = durable_client(monkeypatch)
    world.command(cmd="apply_prepare", token="t", slot=1, old_key=KB)
    world.step()
    assert world.events("apply_ready")[-1]["ok"] is True
    journal = carrier.journal_model.journal
    original_ready, original_hidden = journal.ready, journal.hidden
    journal.busy = True
    journal.ready = lambda self: False if self.busy else original_ready(self)
    journal.hidden = lambda self: True if self.busy else original_hidden(self)
    apply(world, blob, token="t")
    world.step()
    assert not carrier.jobs and not world.events("trade_done")
    journal.busy = None
    world.step(2)
    assert [job["step"] for job in carrier.jobs] == ["enemy"]
    assert not world.events("trade_done")


def test_queued_apply_trade_does_not_cross_reset_and_new_preparation(monkeypatch):
    from tests.unit.test_gen3_client import apply
    from tests.unit.test_gen3_trade import KB

    world, carrier, blob = durable_client(monkeypatch)
    world.command(cmd="apply_prepare", token="t", slot=1, old_key=KB)
    world.step()
    assert world.events("apply_ready")[-1]["ok"] is True
    journal = carrier.journal_model.journal
    original_ready, original_hidden = journal.ready, journal.hidden
    journal.busy = True
    journal.ready = lambda self: False if self.busy else original_ready(self)
    journal.hidden = lambda self: True if self.busy else original_hidden(self)
    apply(world, blob, token="t")
    world.step()
    assert not carrier.jobs

    world.connected = False
    journal.busy = None
    world.client.driver.on_reset()
    world.step()
    world.connected = True
    world.client.hello_sent = False
    world.step(2)
    world.command(cmd="apply_prepare", token="new", slot=1, old_key=KB)
    world.step()
    assert world.events("apply_ready")[-1]["token"] == "new"
    assert world.events("apply_ready")[-1]["ok"] is True
    world.step(2)
    assert not carrier.jobs, "the old apply must not consume a later preparation"
    assert any("pending apply_trade discarded: preparation binding changed" in line for line in world.logs)


def test_frame_rewind_discards_queued_apply_before_any_native_stage(monkeypatch):
    from tests.unit.test_gen3_client import apply
    from tests.unit.test_gen3_trade import KB

    world, carrier, blob = durable_client(monkeypatch)
    world.command(cmd="apply_prepare", token="t", slot=1, old_key=KB)
    world.step()
    journal = carrier.journal_model.journal
    original_ready, original_hidden = journal.ready, journal.hidden
    journal.busy = True
    journal.ready = lambda self: False if self.busy else original_ready(self)
    journal.hidden = lambda self: True if self.busy else original_hidden(self)
    apply(world, blob, token="t")
    world.step()
    assert not carrier.jobs
    journal.busy = None
    world.frame = 1  # real driver frame rewind; do not call on_reset manually
    world.step()
    assert not carrier.jobs, "a pre-rewind apply cannot create a native stage"
    assert any("pending apply_trade discarded: preparation binding changed" in line for line in world.logs)


def test_frame_rewind_clears_local_save_allowance_before_queued_final(monkeypatch):
    world, carrier, _blob = durable_client(monkeypatch)
    journal = carrier.journal_model.journal
    epoch = journal.allocate(journal)
    assert journal.arm(journal, "t", epoch) is True
    assert journal.native_saved(journal, "t", epoch) is True
    assert journal.hidden(journal) is False  # same-episode local save allowance
    original_final = journal.final
    seen = []

    def busy_once(self, *args):
        seen.append(args)
        if len(seen) == 1:
            return None, "trade journal lock busy"
        return original_final(self, *args)

    journal.final = busy_once
    world.replies.append(json.dumps({"commands": [
        {"cmd": "trade_final", "token": "t", "epoch": epoch, "verdict": "resolved"}]}))
    world.step()
    assert carrier.journal_model.journal.state.records[1].final == ""
    world.frame = 1  # driver must detect this before replaying the queued final
    world.step()
    assert len(seen) >= 2
    assert carrier.journal_model.journal.state.records[1].final == "resolved"
    assert journal.hidden(journal) is True, "old local saved allowance must not survive reload"


def test_repeated_native_save_milestones_flush_the_host_once(monkeypatch):
    world, carrier, blob = durable_client(monkeypatch)
    start_client_trade(world, carrier, blob)
    swap_in_partner(world)
    progress = carrier.jobs[-1]["progress"]
    progress(carrier.lua.table(commit_entered=True, scene_done=True, save_success=True))
    progress(carrier.lua.table(save_success=True))
    carrier.ack(commit_entered=True, scene_done=True, save_success=True, final_result="committed")
    world.step()
    assert world.saveram_calls == 1
    assert not world.events("trade_done")[-1].get("uncertain")


def test_journal_without_a_server_run_identity_cannot_advertise_trade(monkeypatch):
    from tests.unit.gen3_trade_journal_model import JournalModel
    from tests.unit.gen3_world import World
    from tests.unit.test_gen3_trade import A, B, CartridgeModel, party

    monkeypatch.setenv("SLINK_GEN3_BATTLE_NONCE", "0000BEEF")
    model = JournalModel(run=None)
    world = World("gen3_rr", "radical_red", "companion", native=CartridgeModel(), journal=model)
    world.set_party(party(A, B))
    world.step_to(60)
    assert world.events("hello")[-1]["trade_prepare"] is False


@pytest.mark.parametrize("config", (None, "", 17, "another-run"))
def test_reconnect_cannot_accept_final_or_redeclare_until_run_is_reconfirmed(tmp_path, monkeypatch, config):
    world, model, _, _, token, _, _ = recovering_pair(tmp_path, monkeypatch)
    world.replies.clear()
    world.connected = False
    world.step()
    world.connected = True
    start = len(world.sent)
    commands = [] if config is None else [{"cmd": "config", "run_id": config}]
    commands.append({"cmd": "trade_final", "token": token, "verdict": "resolved"})
    world.replies.append(json.dumps({"commands": commands}))
    world.step(35)
    record = model.journal.state.records[1]
    assert record.final == "" and record.binding.run_id == "run-a"
    snapshots = [m for m in world.sent[start:] if m["event"] in ("hello", "tick", "safe")]
    assert snapshots and all(m.get("party_hidden") is True for m in snapshots)
    assert all(not m.get("trade_outstanding") for m in snapshots)
    assert not [m for m in world.sent[start:] if m["event"] == "trade_done"]
    world.replies.append(json.dumps({"commands": [
        {"cmd": "config", "run_id": "run-a"},
        {"cmd": "trade_final", "token": token, "verdict": "resolved"}]}))
    world.step(35)
    assert model.journal.state.records[1].final == "resolved"
    assert model.journal.hidden(model.journal) is True


def test_new_intent_cannot_reuse_an_earlier_boot_episode(monkeypatch):
    from tests.unit.gen3_trade_journal_model import JournalModel
    from tests.unit.gen3_world import SB1_ADDR, SB2_ADDR, World
    from tests.unit.test_gen3_trade import PARTNER, A, B, CartridgeModel, party

    monkeypatch.setenv("SLINK_GEN3_BATTLE_NONCE", "0000BEEF")
    carrier = CartridgeModel()
    world = World(native=carrier, journal=JournalModel(), model_companion=True)
    world.set_party(party(A, B))
    world.step_to(60)
    blob = world.encode(PARTNER).hex().upper()
    world.poke_int(world.ram["SB1_PTR_ADDR"], 0, 4)
    world.poke_int(world.ram["SB2_PTR_ADDR"], 0, 4)
    world.poke_int(world.ram["PARTY_COUNT_ADDR"], 0, 1)
    world.step(2)
    world.poke_int(world.ram["SB1_PTR_ADDR"], SB1_ADDR, 4)
    world.poke_int(world.ram["SB2_PTR_ADDR"], SB2_ADDR, 4)
    world.poke_int(world.ram["PARTY_COUNT_ADDR"], 2, 1)
    world.step(35)
    called = []
    world.io.trade_reload_proof = lambda *_: called.append(True)
    start_client_trade(world, carrier, blob)
    swap_in_partner(world)
    carrier.ack(commit_entered=True, scene_done=True)
    world.step(35)
    assert not called  # the boot observation predates this intent and proves nothing about it
    assert world.events("tick")[-1]["party_hidden"] is True
    world.poke_int(world.ram["SB1_PTR_ADDR"], 0, 4)
    world.poke_int(world.ram["SB2_PTR_ADDR"], 0, 4)
    world.poke_int(world.ram["PARTY_COUNT_ADDR"], 0, 1)
    world.step(2)
    world.poke_int(world.ram["SB1_PTR_ADDR"], SB1_ADDR, 4)
    world.poke_int(world.ram["SB2_PTR_ADDR"], SB2_ADDR, 4)
    world.poke_int(world.ram["PARTY_COUNT_ADDR"], 2, 1)
    world.step(35)
    assert called  # a later boot episode reaches the independent verifier


def recovering_pair(tmp_path, monkeypatch, corrupt=False):
    import lupa

    from server.server import SLinkServer
    from server.state import LinkEntry, LinkStatus, MonInfo
    from tests.unit.gen3_trade_journal_model import JournalModel
    from tests.unit.gen3_world import World, mon_record
    from tests.unit.test_gen3_trade import CartridgeModel
    from tests.unit.test_gen3_trade_server import KEYS, _hello

    monkeypatch.setenv("SLINK_GEN3_BATTLE_NONCE", "0000BEEF")
    server = SLinkServer(data_dir=str(tmp_path / "server"), run_id="run-a")
    for side, ot in (("a", "17"), ("b", "34")):
        server._dispatch(side, _hello(side, ot_id=ot))
    entry = LinkEntry(area_id="route_1", status=LinkStatus.ALIVE,
                      a=MonInfo(key=KEYS["a"], species=1, level=12),
                      b=MonInfo(key=KEYS["b"], species=4, level=12))
    server.state.links.append(entry)
    server.state._index_entry(entry)
    server._dispatch("a", {"event": "trade_request"})
    token = server.state.pending_trade["token"]
    for pid, event in (("a", {"event": "menu_result", "choice": 0}),
                       ("a", {"event": "mon_chosen", "slot": 0}),
                       ("b", {"event": "menu_result", "choice": 1})):
        server._dispatch(pid, {**event, "token": token})
    for side in ("a", "b"):
        server._dispatch(side, {"event": "apply_ready", "token": token, "ok": True})
    old = JournalModel(run="run-a", ot="00000011")
    journal = old(lupa.LuaRuntime(unpack_returned_tuples=True))
    epoch = journal.allocate(journal)
    journal.arm(journal, token, epoch)  # process died after its durable intent
    saved = old.data
    restored = JournalModel(run=None, ot="00000011", data="corrupt" if corrupt else saved)
    carrier = CartridgeModel()
    world = World(native=carrier, journal=restored, model_companion=True)
    world.set_trainer(17, "A")
    world.set_party([mon_record(2, 0x22, species=4)])  # possibly unsaved received RAM
    cursor = 0

    def pump(frames=1):
        nonlocal cursor
        for _ in range(frames):
            world.step()
            messages = world.sent[cursor:]
            cursor = len(world.sent)
            for message in messages:
                commands = server._dispatch("a", message)
                world.replies.append(json.dumps({"commands": commands}))
    pump(65)
    return world, restored, server, entry, token, epoch, pump


def test_cold_boot_witness_survives_pre_continue_save_clear_validation(tmp_path, monkeypatch):
    from tests.unit.gen3_world import SB1_ADDR, SB2_ADDR, mon_record

    world, _model, _server, _entry, _token, _epoch, _pump = recovering_pair(tmp_path, monkeypatch)
    called = []
    world.io.trade_reload_proof = lambda *_: called.append(True)
    world.set_party([])
    world.poke_int(world.ram["SB1_PTR_ADDR"], 0, 4)
    world.poke_int(world.ram["SB2_PTR_ADDR"], 0, 4)
    world.step(2)  # observed cold boot with cleared SaveBlocks and party
    world.poke_int(world.ram["SB1_PTR_ADDR"], SB1_ADDR, 4)
    world.poke_int(world.ram["SB2_PTR_ADDR"], SB2_ADDR, 4)
    world.set_trainer(0, "")
    world.step_to(120)  # core validation sees OT=0 and calls on_reset before CONTINUE
    before_live = len(called)  # a pre-field probe cannot qualify an empty saved party
    world.set_trainer(17, "A")
    world.set_party([mon_record(1, 0x11, species=1)])
    world.step(35)
    assert len(called) > before_live, "the early witness must survive pre-continue OT=0 validation"
    world.set_party([])
    world.set_trainer(0, "")
    world.step_to(180)  # a later save clear after live play must revoke the old witness
    after_clear = len(called)
    world.set_trainer(17, "A")
    world.set_party([mon_record(1, 0x11, species=1)])
    world.step(35)
    assert len(called) == after_clear, "a later clear needs a new observed boot episode"


def install_battery_readback(world, model, path):
    from server.adapters import gen3_codec as C
    from tests.unit.gen3_world import SB1_ADDR, SB2_ADDR
    layout = C.slot_layout(title="firered")
    count = world._read(world.ram["PARTY_COUNT_ADDR"], 1)
    party = bytes(world._byte(world.ram["PARTY_BASE"] + i) for i in range(count * 100))
    blocks = {"sb2": bytearray(C.SAVEBLOCK2_SIZE), "sb1": bytearray(C.SAVEBLOCK1_SIZE),
              "storage": bytearray(C.STORAGE_SIZE)}
    blocks["sb2"][10:14] = (17).to_bytes(4, "little")
    blocks["sb1"][0x34:0x38] = count.to_bytes(4, "little")
    blocks["sb1"][0x38:0x38+len(party)] = party
    flash = bytearray(b"\xff" * C.FLASH_SIZE)
    for row in layout:
        raw = blocks[row["object"]][row["offset"]:row["offset"]+row["size"]]
        at = row["id"] * C.SECTOR_SIZE
        flash[at:at+C.SECTOR_SIZE] = C.write_sector(raw, row["id"], 7, layout)
    path.write_bytes(flash)

    def proof(title, _profile, boot_seen):
        live = {"counter": world._read(0x03005390, 4), "ot_id": world._read(SB2_ADDR+10,4),
                "party_count": world._read(world.ram["PARTY_COUNT_ADDR"],1),
                "party": bytes(world._byte(world.ram["PARTY_BASE"]+i) for i in range(count*100)),
                "sb1": world._read(world.ram["SB1_PTR_ADDR"],4), "sb2": world._read(world.ram["SB2_PTR_ADDR"],4)}
        request = {"title": title, "rom_sha1": model.rom, "boot_seen": boot_seen,
                   "ram_before": live, "ram_after": dict(live),
                   "flash_before": path.read_bytes(), "flash_after": path.read_bytes()}
        return model.module.verify_reload(world.lua.table_from(request, recursive=True))
    world.io.trade_reload_proof = proof
    return party, SB1_ADDR, SB2_ADDR


def test_restart_redeclares_from_storage_and_never_uses_received_ram(tmp_path, monkeypatch):
    world, restored, server, entry, token, epoch, pump = recovering_pair(tmp_path, monkeypatch)
    hello = world.events("hello")[-1]
    assert hello["trade_outstanding"] == [{"token": token, "epoch": epoch}]
    assert hello["party_hidden"] is True and hello["party"] == []
    assert server.state.pending_trade["verdict"]["a"] == "await"
    assert entry.a.key == "00000001:00000011"
    world.frame = 1
    pump(35)
    assert restored.journal.hidden(restored.journal) is True
    assert server.state.pending_trade["verdict"]["a"] == "await"


def test_config_without_run_id_revokes_an_existing_connection_binding(tmp_path, monkeypatch):
    world, model, _, _, token, _, _ = recovering_pair(tmp_path, monkeypatch)
    assert model.journal.ready(model.journal) is True
    world.replies.append(json.dumps({"commands": [
        {"cmd": "config"}, {"cmd": "trade_final", "token": token, "verdict": "resolved"}]}))
    world.step(35)
    assert model.journal.ready(model.journal) is False
    assert model.journal.state.records[1].final == ""
    assert model.journal.hidden(model.journal) is True
    world.connected = False
    world.step()
    world.connected = True
    world.step(35)
    hello = world.events("hello")[-1]
    assert hello["party_hidden"] and not hello["trade_prepare"]
    assert not hello.get("trade_outstanding")


def test_qualified_battery_reload_orders_declaration_then_visible_hello_and_settles(tmp_path, monkeypatch):
    world, model, server, entry, token, epoch, pump = recovering_pair(tmp_path, monkeypatch)
    party, sb1, sb2 = install_battery_readback(world, model, tmp_path / "battery.SaveRAM")
    server._dispatch("b", {"event": "trade_done", "token": token,
                           "new_key": "00000001:00000011", "new_species": 1})
    before = len(world.sent)
    world.frame = 1
    world.poke_int(world.ram["SB1_PTR_ADDR"], 0, 4)
    world.poke_int(world.ram["SB2_PTR_ADDR"], 0, 4)
    world.poke_int(world.ram["PARTY_COUNT_ADDR"], 0, 1)
    pump(2)
    world.poke_int(world.ram["SB1_PTR_ADDR"], sb1, 4)
    world.poke_int(world.ram["SB2_PTR_ADDR"], sb2, 4)
    world.poke_int(world.ram["PARTY_COUNT_ADDR"], 1, 1)
    world.poke(world.ram["PARTY_BASE"], party)
    world.poke_int(0x03005390, 7, 4)
    pump(65)
    messages = world.sent[before:]
    assert any(m["event"] == "trade_done" and m.get("uncertain") for m in messages), (world.logs, messages)
    declared = next(i for i, m in enumerate(messages) if m["event"] == "trade_done" and m.get("uncertain"))
    visible = next(i for i, m in enumerate(messages) if m["event"] == "hello" and m.get("party"))
    assert declared < visible and not messages[visible].get("trade_outstanding")
    assert server.state.pending_trade is None
    assert (entry.a.key, entry.b.key) == ("00000002:00000022", "00000001:00000011")
    assert not server.state.party_hidden["a"] and not server.state.trade_recovery_pending["a"]
    assert len(model.journal.state.records) == 0  # real T4 trade_final retires the qualified entry


def test_corrupt_journal_keeps_real_server_snapshot_hidden(tmp_path, monkeypatch):
    world, model, server, entry, _, _, pump = recovering_pair(tmp_path, monkeypatch, corrupt=True)
    assert model.journal.failure
    assert world.events("hello")[-1]["party_hidden"] is True
    assert entry.a.key == "00000001:00000011"
    assert server.state.party_hidden["a"] is True
    pump(30)
    assert model.data == "corrupt" and world.events("tick")[-1]["party_hidden"] is True


def test_real_server_admin_final_does_not_release_the_client_reload_barrier(tmp_path, monkeypatch):
    world, model, server, entry, token, epoch, pump = recovering_pair(tmp_path, monkeypatch)
    server._dispatch("b", {"event": "trade_done", "token": token,
                           "new_key": "00000002:00000022", "new_species": 4})
    assert server.state.resolve_trade(token, "rollback")[0] is True
    pump(35)
    record = model.journal.state.records[1]
    assert record.final == "resolved" and record.epoch == epoch
    assert model.journal.hidden(model.journal) is True
    assert world.events("tick")[-1]["party_hidden"] is True
    assert entry.a.key == "00000001:00000011"


def test_unrecovered_party_does_not_generate_faint_or_capture_evidence(monkeypatch):
    from tests.unit.test_gen3_trade import PARTNER, A, party
    world, _ = uncertain_client(monkeypatch)
    world.step(40)
    start = len(world.sent)
    mons = party(A)
    mons.append({**PARTNER, "hp": 0})
    world.set_party(mons)
    world.fire("faint")
    world.fire("mon_given")
    world.step(40)
    assert not [m for m in world.sent[start:] if m["event"] in ("faint", "capture", "whiteout", "party_to_box", "box_to_party")]
    assert world.client.driver.checkpoint_ok()[0] is False


@pytest.mark.parametrize("signal", ("capture_wild", "mon_given", "pc_move"))
def test_empty_journal_one_frame_busy_replays_capture_once_after_visibility_returns(signal):
    """A real capture signal cannot be lost behind a transient empty-journal guard hold."""
    from tests.unit.gen3_trade_journal_model import JournalModel
    from tests.unit.gen3_world import World, mon_record

    model = JournalModel(player="a")
    world = World("gen3_rr", "radical_red", "companion", journal=model)
    lead = mon_record(1, 0xABCD, species=277)
    reserve = mon_record(2, 0xABCD, species=19)
    catch = mon_record(3, 0xABCD, species=52)
    world.set_party([lead, reserve])
    world.step_to(60)  # visible hello/known-party baseline
    assert model.journal.hidden(model.journal) is False
    assert len(model.journal.state.records) == 0

    journal = model.journal
    original_ready, original_hidden = journal.ready, journal.hidden
    journal.busy = True
    journal.ready = lambda self: False if self.busy else original_ready(self)
    journal.hidden = lambda self: True if self.busy else original_hidden(self)
    world.set_party([lead, reserve, catch])
    world.fire(signal)
    flushed = world.saveram_calls
    world.fire("save")
    world.step(2)
    assert world.events("capture") == []
    assert world.saveram_calls == flushed + 1
    journal.busy = None
    world.step(3)
    captures = world.events("capture")
    assert len(captures) == 1
    assert captures[0]["key"] == "00000003:0000ABCD" and captures[0]["species_id"] == 52
    world.step(35)
    assert len(world.events("capture")) == 1
    assert world.saveram_calls == flushed + 1
