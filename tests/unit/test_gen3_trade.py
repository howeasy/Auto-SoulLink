"""Durable trade MODEL falsifiers; native completion is not a save witness."""

from pathlib import Path

import lupa
import pytest

from tests.unit import gen3_world as gw
from tests.unit.gen3_world import World, lua_to_py
from tests.unit.test_gen3_client import (
    KA,
    KB,
    KC,
    KP,
    PARTNER,
    A,
    B,
    C,
    apply,
    mb_ack,
    party,
    swap_in_partner,
    trade_world,
)

ROOT = Path(__file__).resolve().parents[2]


class TradeWorld:
    """ABI-independent cartridge boundary; it publishes explicit typed milestones."""

    def __init__(self):
        self.lua = lupa.LuaRuntime(unpack_returned_tuples=True)
        self.frame = 100
        self.connected = True
        self.capable = True
        self.events, self.jobs = [], []
        self.rows = [{"key": "00000001:00000002", "slot": 0, "species": 4, "hp": 20},
                     {"key": "00000003:00000004", "slot": 1, "species": 7, "hp": 20}]
        self.visit = {"id": 7, "accepted": True, "pre_saved": True, "apply_open": True}

        def transfer(_, step, args, done, valid, progress=None):
            handle = self.lua.table()
            self.jobs.append({"step": step, "args": args, "done": done, "valid": valid,
                              "progress": progress, "handle": handle})
            return handle

        def cancel(_, handle):
            if handle.posted:
                return False
            handle.cancelled = True
            return True

        native = self.lua.table(trade_capable=lambda *_: self.capable,
                                trade_visit=lambda *_: self.lua.table_from(self.visit),
                                trade_eligible=lambda *_: True, transfer=transfer, cancel=cancel)
        self.native = native
        module = self.lua.execute((ROOT / "lua/gen3/trade.lua").read_text())
        self.trade = module.new(self.lua.table(
            native=native, frame=lambda: self.frame, eligible=lambda: self.connected,
            ready_to_send=lambda: self.connected, clear=lambda: True, capacity=6, mon_size=100,
            party=lambda: self.lua.table_from(self.rows, recursive=True), key=lambda m: m.key,
            send=lambda name, fields: self.events.append((name, lua_to_py(fields))) or True))

    def command(self, method, **fields):
        return getattr(self.trade, method)(self.trade, self.lua.table_from(fields))

    def tick(self):
        self.frame += 1
        self.trade.tick(self.trade)

    def prepare(self):
        self.command("prepare", token="t", slot=0, old_key=self.rows[0]["key"])

    def start(self):
        self.prepare()
        self.command("apply", token="t", slot=0, old_key=self.rows[0]["key"],
                     blob_hex="0500000006000000" + "00" * 92)
        self.tick()
        stage = self.jobs[-1]
        assert stage["step"] == "enemy"
        self.dispatch(stage)
        stage["done"](None, 0, None)
        scene = self.jobs[-1]
        assert scene["step"] == "scene"
        self.dispatch(scene)
        return scene

    def dispatch(self, job):
        result = job["valid"]()
        assert result is True
        job["handle"].posted = True

    def received(self):
        self.rows[0] = {"key": "00000005:00000006", "slot": 0, "species": 65, "hp": 20}

    def progress(self, job, **fields):
        job["progress"](self.lua.table_from(fields))


def test_late_apply_after_withdrawal_cannot_queue_a_native_operation():
    world = TradeWorld()
    world.prepare()
    assert ("apply_ready", {"token": "t", "ok": True}) in world.events
    world.command("withdraw", token="t")
    world.command("apply", token="t", slot=0, old_key=world.rows[0]["key"], blob_hex="05" * 100)
    world.tick()
    assert world.jobs == []
    assert any(name == "trade_done" and fields.get("new_key") == world.rows[0]["key"]
               for name, fields in world.events)


def test_prepared_apply_queues_partner_staging_through_native_owner():
    world = TradeWorld()
    world.prepare()
    world.command("apply", token="t", slot=0, old_key=world.rows[0]["key"], blob_hex="05" * 100)
    world.tick()
    assert [job["step"] for job in world.jobs] == ["enemy"]


def test_commit_and_scene_completion_without_native_save_is_uncertain_not_success():
    world = TradeWorld()
    job = world.start()
    world.progress(job, commit_entered=True, scene_done=True)
    world.received()
    job["done"](None, 0, None)
    world.tick()
    results = [f for n, f in world.events if n == "trade_done"]
    assert results == [{"token": "t", "uncertain": True, "after_reset": True}]
    assert world.trade.hide_party(world.trade) is True


def test_only_native_commit_scene_and_save_plus_final_readback_can_succeed():
    world = TradeWorld()
    job = world.start()
    world.progress(job, commit_entered=True, scene_done=True, save_success=True, final_result="committed")
    world.received()
    job["done"](None, 0, None)
    world.tick()
    assert ("trade_done", {"token": "t", "slot": 0, "new_key": "00000005:00000006", "new_species": 65}) in world.events
    assert [j["step"] for j in world.jobs] == ["enemy", "scene"]


def test_reset_keeps_committed_token_and_owes_uncertainty_after_hello():
    world = TradeWorld()
    job = world.start()
    world.progress(job, commit_entered=True)
    world.connected = False
    world.trade.reset(world.trade)
    world.tick()
    assert not [f for n, f in world.events if n == "trade_done"]
    world.connected = True
    world.tick()
    assert [f for n, f in world.events if n == "trade_done"] == [
        {"token": "t", "uncertain": True, "after_reset": True}]
    world.progress(job, commit_entered=True, scene_done=True, save_success=True)
    world.received()
    job["done"](None, 0, None)
    world.tick()
    assert not [f for n, f in world.events if n == "trade_done" and "new_key" in f]


def test_reset_before_unpicked_commit_withdraws_without_late_dispatch():
    world = TradeWorld()
    world.prepare()
    world.command("apply", token="t", old_key=world.rows[0]["key"], slot=0, blob_hex="05" * 100)
    world.tick()
    stage = world.jobs[-1]
    world.trade.reset(world.trade)
    stage["done"](None, 0, None)
    world.tick()
    assert len(world.jobs) == 1 and stage["handle"].cancelled is True
    assert ("trade_done", {"token": "t", "slot": 0, "new_key": "00000001:00000002", "new_species": 0}) in world.events


def test_native_failure_never_queues_raw_party_replacement():
    world = TradeWorld()
    job = world.start()
    world.progress(job, commit_entered=True)
    job["done"]("native refused", 0, None)
    world.tick()
    assert [j["step"] for j in world.jobs] == ["enemy", "scene"]
    assert [f for n, f in world.events if n == "trade_done"] == [
        {"token": "t", "uncertain": True, "after_reset": True}]


def test_post_save_without_tokened_final_result_is_not_success():
    world = TradeWorld()
    job = world.start()
    world.progress(job, commit_entered=True, scene_done=True, save_success=True)
    world.received()
    job["done"](None, 0, None)
    world.tick()
    assert not [f for n, f in world.events if n == "trade_done" and "new_key" in f]


def test_interrupted_scene_publication_is_not_claimed_unchanged():
    world = TradeWorld()
    world.prepare()
    world.command("apply", token="t", old_key=world.rows[0]["key"], slot=0, blob_hex="05" * 100)
    world.tick()
    stage = world.jobs[-1]
    world.dispatch(stage)
    stage["done"](None, 0, None)
    scene = world.jobs[-1]
    scene["handle"].publish_attempted = True  # sink failed after opcode low byte
    scene["done"]("native dispatch interrupted", 0, None)
    world.tick()
    assert [f for n, f in world.events if n == "trade_done"] == [
        {"token": "t", "uncertain": True, "after_reset": True}]


def test_prepare_replay_cannot_extend_expired_readiness():
    world = TradeWorld()
    world.prepare()
    world.frame += 601
    world.prepare()
    assert world.events[-1] == ("apply_ready", {"token": "t", "ok": False})


def test_prepare_waits_for_native_consent_and_presave_ack():
    world = TradeWorld()
    pending = []
    world.native.trade_authorized = lambda *_: True
    world.native.prepare_trade = lambda _, cmd, done, valid: pending.append((cmd, done, valid)) or world.lua.table()
    world.visit["pre_saved"] = False
    world.prepare()
    assert world.events == []
    assert len(pending) == 1
    world.visit["pre_saved"] = True
    pending[0][1](None, world.lua.table(**world.visit, old_key=world.rows[0]["key"]))
    assert world.events == [("apply_ready", {"token": "t", "ok": True})]


def test_reorder_at_scene_dispatch_relocates_identity_without_touching_bystander():
    world = TradeWorld()
    world.prepare()
    world.command("apply", token="t", old_key=world.rows[0]["key"], slot=0, blob_hex="05" * 100)
    world.tick()
    stage = world.jobs[-1]
    world.dispatch(stage)
    stage["done"](None, 0, None)
    old_scene = world.jobs[-1]
    world.rows[0]["slot"], world.rows[1]["slot"] = 1, 0
    valid, reason = old_scene["valid"]()
    assert valid is False and reason == "guard:moved"
    old_scene["done"](reason, 0, None)
    new_scene = world.jobs[-1]
    assert new_scene is not old_scene and new_scene["args"].slot == 1
    world.dispatch(new_scene)
    old_scene["progress"](world.lua.table(commit_entered=True, scene_done=True, save_success=True, final_result="committed"))
    new_scene["done"](None, 0, None)
    world.tick()
    assert not [f for n, f in world.events if n == "trade_done" and "new_key" in f]


@pytest.mark.parametrize("invalid", ["duplicate", "egg", "bad_checksum", "capacity", "lost_visit"])
def test_prepare_refuses_ineligible_identity_or_visit(invalid):
    world = TradeWorld()
    if invalid == "duplicate":
        world.rows.append(dict(world.rows[0], slot=2))
    elif invalid == "egg":
        world.rows[0]["is_egg"] = 1
    elif invalid == "bad_checksum":
        world.rows[0]["checksum_ok"] = False
    elif invalid == "capacity":
        world.rows += [dict(world.rows[1], slot=i) for i in range(2, 7)]
    else:
        world.visit["accepted"] = False
    world.prepare()
    assert world.events[-1] == ("apply_ready", {"token": "t", "ok": False})
    assert world.jobs == []


def test_scene_ack_and_received_ram_without_save_never_report_trade_success(monkeypatch):
    monkeypatch.setenv("SLINK_GEN3_BATTLE_NONCE", "0000BEEF")
    world, blob = trade_world()
    apply(world, blob)
    world.step(2)
    mb_ack(world)
    world.step()
    swap_in_partner(world)
    mb_ack(world)
    world.step()
    assert world.events("trade_done") == []


class CartridgeModel:
    """Cartridge protocol seam injected through Entry's documented native factory."""

    def __init__(self):
        self.jobs = []
        self.visit = {"id": 9, "accepted": True, "pre_saved": True, "apply_open": True}

    def __call__(self, runtime):
        self.lua = runtime

        def transfer(_, step, args, done, valid, progress=None):
            job = {"step": step, "args": args, "done": done, "valid": valid,
                   "progress": progress, "handle": runtime.table()}
            self.jobs.append(job)
            return job["handle"]

        def service(*_):
            for job in list(self.jobs):
                if job["handle"].posted or job["handle"].cancelled:
                    continue
                result = job["valid"]()
                ok, why = result if isinstance(result, tuple) else (result, None)
                if not ok:
                    job["handle"].cancelled = True
                    job["done"](why, 0, None)
                else:
                    job["handle"].posted = True
                break

        def cancel(_, handle):
            if handle.posted:
                return False
            handle.cancelled = True
            return True

        return runtime.table(trade_capable=lambda *_: True, trade_eligible=lambda *_: True,
                             trade_visit=lambda *_: runtime.table_from(self.visit),
                             transfer=transfer, service=service, cancel=cancel, idle=lambda *_: True)

    def ack(self, **milestones):
        job = self.jobs[-1]
        assert job["handle"].posted
        if job["progress"]:
            job["progress"](self.lua.table_from(milestones))
        job["done"](None, 0, None)


def durable_client(monkeypatch):
    monkeypatch.setenv("SLINK_GEN3_BATTLE_NONCE", "0000BEEF")
    carrier = CartridgeModel()
    world = World("gen3_rr", "radical_red", "companion", native=carrier)
    world.set_party(party(A, B))
    world.step_to(60)
    assert world.events("hello")[0]["trade_prepare"] is True
    return world, carrier, world.encode(PARTNER).hex().upper()


def start_client_trade(world, carrier, blob):
    world.command(cmd="apply_prepare", token="t", slot=1, old_key=KB)
    world.step()
    assert world.events("apply_ready")[-1]["ok"] is True
    apply(world, blob, token="t")
    world.step(2)
    assert carrier.jobs[-1]["step"] == "enemy"
    carrier.ack()
    world.step()
    assert carrier.jobs[-1]["step"] == "scene"


def test_client_success_requires_full_witness_and_reports_evolved_readback(monkeypatch):
    world, carrier, blob = durable_client(monkeypatch)
    start_client_trade(world, carrier, blob)
    swap_in_partner(world)
    carrier.ack(commit_entered=True, scene_done=True, save_success=True, final_result="committed")
    world.step()
    assert world.events("trade_done")[-1]["new_key"] == KP
    assert world.events("trade_done")[-1]["token"] == "t"
    assert [j["step"] for j in carrier.jobs] == ["enemy", "scene"]


def test_client_uncertainty_survives_disconnect_and_reset_hello_order(monkeypatch):
    world, carrier, blob = durable_client(monkeypatch)
    start_client_trade(world, carrier, blob)
    carrier.jobs[-1]["progress"](carrier.lua.table(commit_entered=True))
    world.connected = False
    world.client.driver.on_reset()
    world.client.hello_sent = False
    world.step()
    assert world.events("trade_done") == []
    world.connected = True
    start = len(world.sent)
    world.step(2)
    messages = world.sent[start:]
    assert [m["event"] for m in messages if m["event"] in ("hello", "trade_done")] == ["hello", "trade_done", "hello"]
    assert world.events("trade_done")[-1]["uncertain"] is True
    assert world.events("trade_done")[-1]["after_reset"] is True
    assert world.events("trade_done")[-1]["token"] == "t"


def test_uncertain_unsaved_party_never_becomes_reconnect_evidence(monkeypatch):
    world, carrier, blob = durable_client(monkeypatch)
    start_client_trade(world, carrier, blob)
    swap_in_partner(world)
    carrier.ack(commit_entered=True, scene_done=True)
    world.step()
    assert world.events("trade_done")[-1]["uncertain"] is True
    world.connected = False
    world.step()
    world.connected = True
    world.step()
    assert world.events("hello")[-1]["party"] == []
    assert "pc_boxes" not in world.events("hello")[-1]


def test_waiting_unposted_trade_does_not_hide_an_ordinary_acquisition(monkeypatch):
    world, _carrier, blob = durable_client(monkeypatch)
    world.command(cmd="apply_prepare", token="t", slot=1, old_key=KB)
    world.step()
    world.break_checkpoint()
    apply(world, blob, token="t")
    world.step()
    world.set_party(party(A, B, C))
    world.fire("mon_given")
    world.step(40)
    assert [e["key"] for e in world.events("capture")] == [KC]


def test_waiting_unposted_trade_does_not_hide_a_battle_faint(monkeypatch):
    world, _carrier, blob = durable_client(monkeypatch)
    world.command(cmd="apply_prepare", token="t", slot=1, old_key=KB)
    world.step()
    world.enter_battle([PARTNER])
    apply(world, blob, token="t")
    world.step()
    mons = party(A, B)
    mons[0]["hp"] = 0
    world.set_party(mons)
    world.fire("faint")
    world.step()
    assert [e["key"] for e in world.events("faint")] == [KA]


def test_verified_trade_purges_stale_box_command_only_after_success(monkeypatch):
    world, carrier, blob = durable_client(monkeypatch)
    start_client_trade(world, carrier, blob)
    world.command(cmd="box_mon", key=KB)
    world.step()
    assert world.client.deferred.size(world.client.deferred) == 1
    swap_in_partner(world)
    carrier.ack(commit_entered=True, scene_done=True, save_success=True, final_result="committed")
    world.step()
    assert world.client.deferred.size(world.client.deferred) == 0
    assert world.events("box_mon_failed") == []


def test_late_received_ram_cannot_upgrade_uncertainty_to_success():
    world = TradeWorld()
    job = world.start()
    job["done"]("native timeout", 0, None)
    world.tick()
    world.received()
    for _ in range(20):
        world.tick()
    assert [f for n, f in world.events if n == "trade_done"] == [
        {"token": "t", "uncertain": True, "after_reset": True}]


def test_clean_artifact_cannot_advertise_an_injected_companion(monkeypatch):
    monkeypatch.setenv("SLINK_GEN3_BATTLE_NONCE", "0000BEEF")
    world = World(native=CartridgeModel())
    world.set_party(party(A, B))
    world.step_to(60)
    assert world.events("hello")[0]["trade_prepare"] is False


@pytest.mark.parametrize("scenario", ["plain", "reordered", "battle", "missing_beacon"])
def test_legacy_companion_without_save_witness_refuses_trade(monkeypatch, scenario):
    monkeypatch.setenv("SLINK_GEN3_BATTLE_NONCE", "0000BEEF")
    world, blob = trade_world(present=scenario != "missing_beacon")
    if scenario == "reordered":
        world.set_party(party(B, A))
    elif scenario == "battle":
        world.enter_battle([PARTNER])
    world.command(cmd="apply_prepare", token="legacy", slot=1, old_key=KB)
    apply(world, blob, token="legacy")
    world.step(3)
    assert world.events("apply_ready")[-1]["ok"] is False
    assert world.events("trade_done") == [] and world.writes == []
    assert world.events("hello")[0]["trade_prepare"] is False


@pytest.mark.parametrize("pack,title", [("gen3_frlg", "firered"), ("gen3_frlg", "leafgreen"),
                                        ("gen3_emerald", "emerald"), ("gen3_rr", "radical_red")])
def test_clean_rom_never_advertises_companion_trade_prepare(pack, title, monkeypatch):
    monkeypatch.setenv("SLINK_GEN3_BATTLE_NONCE", "0000BEEF")
    monkeypatch.setitem(gw.PACK_DIRS, "gen3_emerald", ROOT / "data/games/gen3_emerald")
    world = World(pack, title, "clean")
    world.set_party(party(A, B))
    world.step_to(60)
    assert world.events("hello")[0]["trade_prepare"] is False
