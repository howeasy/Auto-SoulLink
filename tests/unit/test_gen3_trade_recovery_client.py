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
