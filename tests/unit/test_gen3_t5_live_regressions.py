"""Captured 832aaa05 native/wire/journal evidence replay, without an emulator."""

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

from server.adapters import gen3_codec as codec
from tests.unit.gen3_trade_journal_model import JournalModel
from tests.unit.gen3_world import World
from tests.unit.test_gen3_trade import CartridgeModel
from tools.gen3_trade_duo import completed_flushes, decode_witness, journal_state

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/fixtures/gen3/t5_832_failure"


def trace():
    return json.loads((FIXTURE / "trace.json").read_text())


def snapshot(side, kind, last=False):
    names = [
        name
        for name, meta in trace()["snapshots"].items()
        if meta["side"] == side and meta["kind"] == kind
    ]
    return (FIXTURE / names[-1 if last else 0]).read_bytes()


def party(raw):
    return [codec.decode_party_mon(raw[i : i + 100]) for i in range(0, len(raw), 100)]


def key(mon):
    return f"{mon['personality']:08X}:{mon['ot_id']:08X}"


def test_captured_byte_fixtures_retain_original_hashes():
    data = trace()
    files = dict(data["snapshots"])
    files.update({name: data[name] for name in ("slink_gen3_trade.log", "slink_gen3_trade.guard")})
    files[data["received_party"]["path"]] = data["received_party"]
    for name, meta in files.items():
        assert hashlib.sha256((FIXTURE / name).read_bytes()).hexdigest() == meta["sha256"], name


def test_captured_flushes_distinguish_presave_from_two_real_postsave_host_calls():
    data = trace()
    paths = {
        meta["source_path"]: (FIXTURE / name).read_bytes()
        for name, meta in data["snapshots"].items()
    }
    for side, want in (("a", 2), ("b", 0)):
        rows = data["events"][side]
        done = next(
            r for r in rows if r["kind"] == "tx" and r["message"].get("event") == "trade_done"
        )
        result = completed_flushes(rows, lambda row: paths[row["path"]], before=done)
        assert len(result) == want
        if result:
            assert all(flush["counter"] == 6 for flush, _, _ in result)


def test_captured_a_success_announces_visible_hello_before_trade_done(monkeypatch):
    monkeypatch.setenv("SLINK_GEN3_BATTLE_NONCE", "0000BEEF")
    data = trace()
    carrier = CartridgeModel()
    store = JournalModel(player="a")
    world = World(
        "gen3_frlg", "firered", "clean", native=carrier, journal=store, model_companion=True
    )
    original = party(snapshot("a", "boot_party"))
    received = party((FIXTURE / "a_received_party.bin").read_bytes())
    old = key(original[1])
    incoming = key(received[1])
    world.set_party(original)
    world.step_to(60)
    world.command(cmd="apply_prepare", token="t1", old_key=old, slot=1)
    world.step()
    command = next(
        row["message"]
        for row in data["events"]["a"]
        if row["kind"] == "rx" and row["message"].get("cmd") == "apply_trade"
    )
    world.command(**command)
    world.step(2)
    carrier.ack()
    world.step()
    assert carrier.jobs[-1]["step"] == "scene"
    world.step_to(90)
    assert any(row.get("party_hidden") for row in world.events("tick")), (
        "same hidden tick as the captured wire"
    )
    start = len(world.sent)
    world.set_party(received)
    native = decode_witness(snapshot("a", "flush_native", last=True))
    assert (
        native["bits"] == 31
        and native["result"] == 1
        and native["received"] == (received[1]["personality"], received[1]["ot_id"])
    )
    carrier.ack(commit_entered=True, scene_done=True, save_success=True, final_result="committed")
    world.step()
    messages = [m for m in world.sent[start:] if m["event"] in ("hello", "trade_done")]
    assert [m["event"] for m in messages] == ["hello", "trade_done"]
    assert not messages[0].get("party_hidden") and not messages[0].get("trade_outstanding")
    assert incoming in {m["key"] for m in messages[0]["party"]}
    assert messages[1]["new_key"] == incoming


def test_captured_journal_blocks_a_different_run_without_reconciliation():
    from lupa import lua54

    raw = (FIXTURE / "slink_gen3_trade.log").read_bytes()
    guard = (FIXTURE / "slink_gen3_trade.guard").read_bytes()
    state = journal_state(raw, guard)
    assert {(r["binding"]["player"], r["token"]) for r in state["records"]} == {
        ("a", "t1"),
        ("b", "t1"),
    }
    for side in "ab":
        ot = next(r["binding"]["ot_id"] for r in state["records"] if r["binding"]["player"] == side)
        model = JournalModel(
            player=side,
            rom=trace()["rom_sha1"],
            run="t5-dd07256bf70b4df98998676a8868eb91",
            ot=ot,
            data=raw.decode(),
        )
        journal = model(lua54.LuaRuntime(unpack_returned_tuples=True))
        assert not journal.ready(journal)
        assert journal.hidden(journal)
        assert model.data.encode() == raw, "diagnosis must not clear the old unresolved journal"


@pytest.mark.parametrize("expiry", ["none", "caller", "native"])
def test_captured_b_ready_scene_waits_for_a_safe_frame_without_losing_its_deadline(
    monkeypatch, expiry
):
    from lupa import lua54

    from tests.unit import test_gen3_native as model
    from tests.unit.test_gen3_native_trade import TradeNativeWorld

    monkeypatch.setattr(model, "lupa", lua54)
    w = TradeNativeWorld(capability=3, player="b", initial_seq=0, epoch=5)
    old_party = party(snapshot("b", "boot_party"))
    old = key(old_party[1])
    w.seed_party(*old_party)
    prepared = []
    pre = w.native.prepare_trade(
        w.native,
        w.lua.table(token="t1", old_key=old, slot=1),
        lambda *args: prepared.append(args),
        lambda: True,
    )
    w.service()
    assert bytes(pre.args.values()) == decode_witness(snapshot("b", "prepare"))["args"]
    # Exact native READY witness, captured immediately before B's WITHDRAW.
    raw = snapshot("b", "withdraw")
    for i, byte in enumerate(raw[0x50:]):
        w.put(w.n["BASE"] + 0x50 + i, byte)
    w.phase(2)
    w.ack()
    w.service()
    assert prepared[-1][0] is None
    command = next(
        r["message"]
        for r in trace()["events"]["b"]
        if r["kind"] == "rx" and r["message"].get("cmd") == "apply_trade"
    )
    stage = w.native.transfer(
        w.native,
        "enemy",
        w.lua.table(blobs_hex=w.lua.table(command["blob_hex"])),
        None,
        lambda: True,
    )
    w.service()
    assert not stage.posted
    # The real shared journal still contains B's valid intent; it is not a
    # reason to discard the queued scene in this replay.
    stored = JournalModel(
        player="b",
        rom=trace()["rom_sha1"],
        run=trace()["run_id"],
        ot="6621F275",
        data=(FIXTURE / "slink_gen3_trade.log").read_text(),
    )
    journal = stored(w.lua)
    assert journal.lease_open(journal, "t1", 1)
    deadline = w.frame + (3 if expiry == "caller" else 100)

    def valid():
        return (False, "guard:apply_expired") if w.frame > deadline else True

    done = []
    scene = w.native.transfer(
        w.native,
        "scene",
        w.lua.table(token="t1", old_key=old, slot=1, visit=1),
        lambda *args: done.append(args),
        valid,
        lambda *_: None,
    )
    w.safe = False
    w.frame += 1
    w.service()
    assert not scene.posted and done == [], "one unsafe frame must hold, not cancel, a valid scene"
    w.safe = True
    w.frame = deadline + 1 if expiry == "caller" else w.frame + (9 if expiry == "native" else 1)
    w.service()
    if expiry != "none":
        reason = "guard:apply_expired" if expiry == "caller" else "guard:field_expired"
        assert not scene.posted and done[0][0] == reason
    else:
        assert scene.posted and w.read(w.n["BASE"] + 6, 2) == 21 and scene.seq == 2


def test_captured_hidden_tick_explains_server_refusal_but_visible_hello_releases_it(tmp_path):
    from server.server import SLinkServer
    from server.state import LinkEntry, LinkStatus, MonInfo

    data = trace()

    def setup(path):
        server = SLinkServer(data_dir=str(path), run_id=data["run_id"])
        hellos = {
            side: deepcopy(
                [r["msg"] for r in data["wire"][side] if r["msg"]["event"] == "hello"][-1]
            )
            for side in "ab"
        }
        for side in "ab":
            server._dispatch(side, hellos[side])
        halves = {side: hellos[side]["party"][1] for side in "ab"}
        link = LinkEntry(
            area_id="duo",
            status=LinkStatus.ALIVE,
            a=MonInfo(key=halves["a"]["key"], species=64, level=4),
            b=MonInfo(key=halves["b"]["key"], species=64, level=4),
        )
        server.state.links.append(link)
        server.state._index_entry(link)
        for side, msg in [
            ("a", {"event": "trade_request"}),
            ("a", {"event": "menu_result", "token": "t1", "choice": 0}),
            ("a", {"event": "mon_chosen", "token": "t1", "slot": 1}),
            ("b", {"event": "menu_result", "token": "t1", "choice": 1}),
        ]:
            server._dispatch(side, msg)
        for side in "ab":
            server._dispatch(side, {"event": "apply_ready", "token": "t1", "ok": True})
        hidden = next(r["msg"] for r in data["wire"]["a"] if r["msg"].get("party_hidden"))
        server._dispatch("a", hidden)
        return server, hellos

    done = next(r["msg"] for r in data["wire"]["a"] if r["msg"]["event"] == "trade_done")
    old, _ = setup(tmp_path / "old")
    old._dispatch("a", done)
    assert old.state.pending_trade["verdict"]["a"] == "await"
    fixed, hellos = setup(tmp_path / "fixed")
    visible = hellos["a"]
    mon = visible["party"][1]
    mon.update(key=done["new_key"], species_id=done["new_species"])
    fixed._dispatch("a", visible)
    fixed._dispatch("a", done)
    assert fixed.state.pending_trade["verdict"]["a"] == "traded"
