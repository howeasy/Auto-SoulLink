"""The physical trade lane's private admission grant must fail closed."""
from __future__ import annotations

import copy
import hashlib
import inspect
import json
from pathlib import Path

import pytest

from server import server as server_module
from tests.unit.test_mixed_foundations import _hello, _session, _snapshot

ROOT = Path(__file__).resolve().parents[2]


def lane_module():
    from tools import gen2_trade_lane
    return gen2_trade_lane


def manifest(titles=("crystal", "gold")):
    provenance = ROOT / "data/gen2/overlay_provenance.json"
    outputs = json.loads(provenance.read_text())["outputs"]
    players = {}
    for side, title in zip(("a", "b"), titles, strict=True):
        out = outputs[f"poke{title}"]
        profile = json.loads((ROOT / f"data/games/gen2_{title}/profile.json").read_text())["titles"][title]["overlay"]
        players[side] = {"title": title, "rom_type": title.title(), "foundation": "gen2_gsc", "artifact_kind": "overlay",
                         "rom_sha1": out["sha1"], "base_sha1": out["base_sha1"],
                         "ups_sha256": out["ups"]["sha256"], "sym_sha256": profile["sym_sha256"]}
    return {"schema": "gen2-trade-lane-v1", "run_id": "trade-model-1", "scenario": "gen2_trade_new",
            "evidence_class": "HARNESS_ONLY_OVERLAY", "provenance_sha256": hashlib.sha256(provenance.read_bytes()).hexdigest(),
            "players": players}


def hello(doc, side):
    row = doc["players"][side]
    return _hello(side, {key: row[key] for key in ("rom_type", "foundation", "artifact_kind", "rom_sha1")})


def snapshot(srv):
    return {**_snapshot(srv), "identity": copy.deepcopy(srv.state.player_identity),
            "bindings": {key: id(value) for key, value in srv._player_adapters.items()}}


@pytest.mark.parametrize("titles", [("crystal", "crystal"), ("gold", "silver"), ("crystal", "gold")])
def test_manifest_binds_current_overlay_artifacts(titles):
    doc = manifest(titles)
    assert lane_module().validate_manifest(doc) == doc


@pytest.mark.parametrize("mutation", ["schema", "scenario", "run_id", "attribution", "extra", "missing",
    "player", "title", "rom_type", "kind", "foundation", "rom_sha1", "base_sha1", "ups_sha256", "sym_sha256", "provenance"])
def test_manifest_refuses_unpinned_or_unknown_inputs(mutation):
    doc = manifest()
    if mutation in ("schema", "scenario", "run_id"):
        doc[mutation] = ""
    elif mutation == "attribution":
        doc["evidence_class"] = "PHYSICAL_ADMITTED"
    elif mutation == "extra":
        doc["future_option"] = True
    elif mutation == "missing":
        del doc["players"]["a"]["rom_sha1"]
    elif mutation == "player":
        doc["players"]["c"] = doc["players"].pop("b")
    elif mutation == "provenance":
        doc["provenance_sha256"] = "0" * 64
    else:
        key = "artifact_kind" if mutation == "kind" else mutation
        doc["players"]["a"][key] = "0" * 40 if key.endswith("sha1") else "wrong"
    with pytest.raises(ValueError):
        lane_module().validate_manifest(doc)


@pytest.mark.parametrize("artifact", ["ups", "sym", "base"])
def test_manifest_validates_actual_bytes_not_only_declared_hashes(monkeypatch, artifact):
    doc = manifest()
    out = json.loads((ROOT / "data/gen2/overlay_provenance.json").read_text())["outputs"]["pokecrystal"]
    target = {"ups": ROOT / out["ups"]["file"], "sym": ROOT / "data/gen2/crystal_slink.sym",
              "base": ROOT / ".cache/gen2-build/pokecrystal/pokecrystal.gbc"}[artifact]
    original = Path.read_bytes

    def changed(path):
        raw = original(path)
        return bytes([raw[0] ^ 1]) + raw[1:] if path == target else raw

    monkeypatch.setattr(Path, "read_bytes", changed)
    with pytest.raises(ValueError, match="differ"):
        lane_module().validate_manifest(doc)


def test_manifest_path_rejects_duplicate_keys(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest()).replace('"players":', '"run_id":"duplicate","players":'), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate JSON key"):
        lane_module().validate_manifest(path)


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["hash", "missing_hash", "title", "alias_other_title", "kind", "missing_kind",
                                     "foundation", "player", "ap", "unknown"])
@pytest.mark.parametrize("accepted_first", [False, True])
async def test_real_hello_refusal_preserves_state_and_bindings(tmp_path, mutation, accepted_first):
    doc = manifest()
    restore = lane_module().install_server_gate(server_module, doc)
    srv = server_module.SLinkServer(data_dir=str(tmp_path), run_id=doc["run_id"])
    send, close = await _session(srv)
    send_b, close_b = await _session(srv)
    try:
        if accepted_first:
            await send(hello(doc, "a"))
            await send_b(hello(doc, "b"))
            assert srv.is_admitted("a") and srv.is_admitted("b")
        before = snapshot(srv)
        bad = hello(doc, "a")
        if mutation == "hash":
            bad["rom_sha1"] = "0" * 40
        elif mutation == "missing_hash":
            del bad["rom_sha1"]
        elif mutation == "title":
            bad["title"] = "gold"
        elif mutation == "alias_other_title":
            bad["rom_type"] = "gold"
        elif mutation == "kind":
            bad["artifact_kind"] = "clean"
        elif mutation == "missing_kind":
            del bad["artifact_kind"]
        elif mutation == "foundation":
            bad["foundation"] = "gen1_rby"
        elif mutation == "player":
            bad["player"] = "c"
        else:
            bad["rom_type"] = "crystal_ap" if mutation == "ap" else "unknown"
        result = await send(bad)
        assert result["commands"] == [{"cmd": "noop"}]
        assert snapshot(srv) == before
        if mutation != "player":
            assert not srv.is_admitted("a")
            assert "HARNESS_ONLY_OVERLAY" in srv.admission["a"]["reason"]
        assert (await send({"event": "capture", "player": "a", "key": "1234:30B8:10",
                            "area_id": "route_29", "species": 16, "level": 5}))["commands"] == [{"cmd": "noop"}]
        assert snapshot(srv) == before
        await send(hello(doc, "a"))
        assert srv.is_admitted("a")
    finally:
        await close()
        await close_b()
        restore()


@pytest.mark.asyncio
@pytest.mark.parametrize("titles", [("crystal", "crystal"), ("gold", "silver"), ("crystal", "gold")])
async def test_real_pairing_accepts_title_aliases_with_exact_overlay_pins(tmp_path, titles):
    doc = manifest(titles)
    restore = lane_module().install_server_gate(server_module, doc)
    srv = server_module.SLinkServer(data_dir=str(tmp_path), run_id=doc["run_id"])
    sessions = {side: await _session(srv) for side in ("a", "b")}
    try:
        for side in ("b", "a"):
            msg = hello(doc, side)
            msg["rom_type"] = msg["rom_type"].lower()
            await sessions[side][0](msg)
            assert srv.is_admitted(side)
        assert srv.state.artifact_kind == "overlay"
        assert srv.adapter.native_trade_ui()
    finally:
        for _, close in sessions.values():
            await close()
        restore()


@pytest.mark.asyncio
async def test_a_socket_cannot_spoof_an_admitted_partner(tmp_path):
    doc = manifest()
    restore = lane_module().install_server_gate(server_module, doc)
    srv = server_module.SLinkServer(data_dir=str(tmp_path))
    a, close_a = await _session(srv)
    b, close_b = await _session(srv)
    try:
        await a(hello(doc, "a"))
        await b(hello(doc, "b"))
        assert srv.is_admitted("b")
        before = snapshot(srv)
        capture = {"event": "capture", "player": "b", "key": "1234:7B0B:13",
                   "area_id": "route_29", "species": 19, "level": 5}
        assert (await a(capture))["commands"] == [{"cmd": "noop"}]
        assert snapshot(srv) == before
        assert srv.is_admitted("b"), "the attack must not revoke the real partner's admission"
        assert (await a(hello(doc, "b")))["commands"] == [{"cmd": "noop"}]
        assert snapshot(srv) == before
    finally:
        await close_a()
        await close_b()
        restore()


@pytest.mark.asyncio
async def test_valid_cartridge_does_not_bypass_wrong_save_identity(tmp_path):
    doc = manifest()
    restore = lane_module().install_server_gate(server_module, doc)
    srv = server_module.SLinkServer(data_dir=str(tmp_path))
    send, close = await _session(srv)
    try:
        await send(hello(doc, "a"))
        before = snapshot(srv)
        wrong = hello(doc, "a")
        wrong["ot_id"] = "FFFF"
        reply = await send(wrong)
        assert any("WRONG SAVE" in cmd.get("text", "") for cmd in reply["commands"])
        assert srv.state.identity_error.get("a")
        assert snapshot(srv) == before
        await send({"event": "capture", "player": "a", "key": "1234:FFFF:10",
                    "area_id": "route_29", "species": 16, "level": 5})
        assert snapshot(srv) == before
    finally:
        await close()
        restore()


def test_delegate_rejections_and_restore_original_methods(tmp_path, monkeypatch):
    doc = manifest()
    original_handle = server_module.SLinkServer.handle_client
    calls = []

    def refused(self, player, msg):
        calls.append((player, msg))
        return {"state": "rejected", "reason": "original contract refused"}

    monkeypatch.setattr(server_module.SLinkServer, "_decide_admission", refused)
    restore = lane_module().install_server_gate(server_module, doc)
    try:
        srv = server_module.SLinkServer(data_dir=str(tmp_path))
        assert srv._decide_admission("a", hello(doc, "a"))["state"] == "rejected"
        assert len(calls) == 1
        assert srv._decide_admission("c", hello(doc, "a"))["state"] == "rejected"
        assert len(calls) == 1
    finally:
        restore()
    assert server_module.SLinkServer._decide_admission is refused
    assert server_module.SLinkServer.handle_client is original_handle


def test_cli_calls_the_same_imported_server_with_original_argument_names(tmp_path, monkeypatch, capsys):
    module = lane_module()
    doc = manifest()
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    original = server_module.SLinkServer._decide_admission
    called = []

    async def main(**kwargs):
        assert server_module.SLinkServer._decide_admission is not original
        called.append(kwargs)

    signature = inspect.signature(server_module.main)
    monkeypatch.setattr(server_module, "main", main)
    assert module.main(["--manifest", str(path), "--", "--data-dir", str(tmp_path), "--port", "54329",
                        "--http-port", "8089", "--gender-clause", "--no-battle-calc", "--verbose"]) == 0
    assert len(called) == 1
    signature.bind(**called[0])
    assert called[0]["run_id"] == doc["run_id"] and called[0]["gender_lock"] is True
    assert called[0]["battle_calc"] is False and called[0]["port"] == 54329
    assert server_module.SLinkServer._decide_admission is original
    assert "HARNESS_ONLY_OVERLAY" in capsys.readouterr().out
    assert (tmp_path / "trade_lane_events.jsonl").read_bytes() == b""


def test_cli_refuses_a_different_run_before_installing_the_gate(tmp_path):
    module = lane_module()
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest()), encoding="utf-8")
    original = server_module.SLinkServer._decide_admission
    with pytest.raises(ValueError, match="run_id differs"):
        module.main(["--manifest", str(path), "--", "--data-dir", str(tmp_path), "--run-id", "another-run"])
    assert server_module.SLinkServer._decide_admission is original


@pytest.mark.asyncio
async def test_audit_records_original_dispatched_trade_messages_not_acceptance(tmp_path):
    doc = manifest()
    audit = tmp_path / "wire.jsonl"
    original_dispatch = server_module.SLinkServer._dispatch
    restore = lane_module().install_server_gate(server_module, doc, audit_path=audit)
    srv = server_module.SLinkServer(data_dir=str(tmp_path))
    send, close = await _session(srv)
    try:
        await send(hello(doc, "a"))
        messages = [
            {"event": "trade_query", "player": "a", "seq": 101},
            {"event": "trade_offer", "player": "a", "slot": 0, "seq": 102},
            {"event": "menu_result", "player": "a", "token": "no-pending-trade", "choice": 0, "seq": 103},
            {"event": "trade_done", "player": "a", "token": "no-pending-trade", "slot": 0,
             "new_key": "1234:30B8:10", "new_species": 16, "seq": 104},
        ]
        for message in messages:
            await send(message)
        rows = [json.loads(line) for line in audit.read_text().splitlines()]
        assert len(rows) == 4 and [row["seq"] for row in rows] == [1, 2, 3, 4]
        assert [row["message"] for row in rows] == messages
        assert all(row["source"] == "server_dispatch" and row["player"] == "a"
                   and row["evidence_class"] == "HARNESS_ONLY_OVERLAY"
                   and row["run_id"] == doc["run_id"] and row["scenario"] == doc["scenario"] for row in rows)
        assert all(row["outcome"]["dispatch"] == "returned" and "accepted" not in row["outcome"] for row in rows)
        assert not srv.state.links, "ignored no-session reports are evidence of dispatch, not a completed trade"
    finally:
        await close()
        restore()
    assert server_module.SLinkServer._dispatch is original_dispatch


@pytest.mark.asyncio
async def test_audit_omits_rejected_prefilter_trade_traffic(tmp_path):
    doc = manifest()
    audit = tmp_path / "wire.jsonl"
    restore = lane_module().install_server_gate(server_module, doc, audit_path=audit)
    srv = server_module.SLinkServer(data_dir=str(tmp_path))
    send, close = await _session(srv)
    try:
        bad = hello(doc, "a")
        bad["rom_sha1"] = "0" * 40
        await send(bad)
        await send({"event": "trade_query", "player": "a"})
        await send({"event": "trade_offer", "player": "a", "slot": 0})
        assert audit.read_bytes() == b""
        await send(hello(doc, "a"))
        await send({"event": "trade_query", "player": "b"})
        assert audit.read_bytes() == b""
    finally:
        await close()
        restore()


def test_audit_creation_is_exclusive_before_any_method_is_changed(tmp_path):
    audit = tmp_path / "wire.jsonl"
    audit.write_bytes(b"previous evidence\n")
    before = (server_module.SLinkServer._decide_admission, server_module.SLinkServer.handle_client,
              server_module.SLinkServer._dispatch)
    with pytest.raises(FileExistsError):
        lane_module().install_server_gate(server_module, manifest(), audit_path=audit)
    assert audit.read_bytes() == b"previous evidence\n"
    assert before == (server_module.SLinkServer._decide_admission, server_module.SLinkServer.handle_client,
                      server_module.SLinkServer._dispatch)


def test_audit_records_failure_and_does_not_swallow_original_exception(tmp_path, monkeypatch):
    def explode(self, player, msg):
        msg["_rejected"] = True
        raise RuntimeError("native dispatch failure")

    monkeypatch.setattr(server_module.SLinkServer, "_dispatch", explode)
    audit = tmp_path / "wire.jsonl"
    restore = lane_module().install_server_gate(server_module, manifest(), audit_path=audit)
    srv = server_module.SLinkServer(data_dir=str(tmp_path))
    message = {"event": "trade_done", "player": "a", "token": "X"}
    try:
        with pytest.raises(RuntimeError, match="native dispatch failure"):
            srv._dispatch("a", message)
        row = json.loads(audit.read_text())
        assert row["message"] == {"event": "trade_done", "player": "a", "token": "X"}
        assert row["outcome"] == {"dispatch": "raised", "exception": "RuntimeError", "pending_trade": None,
                                  "pending_trade_before": None, "trade_problem": None, "trade_last": None,
                                  "watchdog_observed": False, "pending_trade_after_watchdog": None,
                                  "trade_problem_after_watchdog": None, "trade_last_after_watchdog": None}
        assert message["_rejected"] is True, "wrapper must not alter the original dispatch behavior"
    finally:
        restore()
    assert server_module.SLinkServer._dispatch is explode


@pytest.mark.asyncio
async def test_audit_captures_server_generated_offer_token_and_clear(tmp_path):
    from server.state import LinkEntry, LinkStatus, MonInfo

    doc = manifest()
    audit = tmp_path / "wire.jsonl"
    restore = lane_module().install_server_gate(server_module, doc, audit_path=audit)
    srv = server_module.SLinkServer(data_dir=str(tmp_path))
    send_a, close_a = await _session(srv)
    send_b, close_b = await _session(srv)
    try:
        await send_a(hello(doc, "a"))
        await send_b(hello(doc, "b"))
        entry = LinkEntry(area_id="route_29", a=MonInfo(key="1234:30B8:10", species=16, level=5),
                          b=MonInfo(key="5678:7B0B:13", species=19, level=5), status=LinkStatus.ALIVE)
        srv.state.links.append(entry)
        srv.state._index_entry(entry)
        for side, mon in (("a", entry.a), ("b", entry.b)):
            srv.state.party_keys[side].add(mon.key)
            srv.state.partner_blobs[side] = [{"slot": 0, "key": mon.key, "blob": bytes(70),
                                              "species_id": mon.species, "level": mon.level}]
        offer = {"event": "trade_offer", "player": "a", "slot": 0}
        await send_a(offer)
        pending = srv.state.pending_trade
        assert pending and pending["token"] == "t1" and pending["phase"] == "confirming"
        first = json.loads(audit.read_text().splitlines()[0])
        assert first["message"] == offer and "token" not in offer
        expected = {"token": "t1", "phase": "confirming", "a_key": entry.a.key, "b_key": entry.b.key}
        assert first["outcome"]["pending_trade"] == expected
        assert "accepted" not in first["outcome"]
        assert "link" in pending, "the real pending object includes a LinkEntry that must not be serialized"
        await send_b({"event": "menu_result", "player": "b", "token": "t1", "choice": 0})
        rows = [json.loads(line) for line in audit.read_text().splitlines()]
        assert rows[-1]["outcome"]["pending_trade"] is None
        assert rows[0]["outcome"]["pending_trade"] == expected
    finally:
        await close_a()
        await close_b()
        restore()


@pytest.mark.asyncio
@pytest.mark.parametrize("conflict", [False, True])
async def test_journal_distinguishes_preawait_party_watchdog_and_later_evidence(tmp_path, conflict):
    from server.state import LinkEntry, LinkStatus, MonInfo

    doc = manifest()
    audit = tmp_path / "wire.jsonl"
    restore = lane_module().install_server_gate(server_module, doc, audit_path=audit)
    srv = server_module.SLinkServer(data_dir=str(tmp_path))
    send_a, close_a = await _session(srv)
    send_b, close_b = await _session(srv)
    a_key, b_key = "1234:30B8:10", "5678:7B0B:13"

    def mon(key, species):
        return {"key": key, "species_id": species, "hp": 10, "maxHP": 10, "slot": 0, "level": 5}

    try:
        await send_a(hello(doc, "a"))
        await send_b(hello(doc, "b"))
        entry = LinkEntry(area_id="route_29", a=MonInfo(key=a_key, species=16, level=5),
                          b=MonInfo(key=b_key, species=19, level=5), status=LinkStatus.ALIVE)
        srv.state.links.append(entry)
        srv.state._index_entry(entry)
        for side, half in (("a", entry.a), ("b", entry.b)):
            srv.state.party_keys[side].add(half.key)
            srv.state.partner_blobs[side] = [{"slot": 0, "key": half.key, "blob": bytes(70),
                                              "species_id": half.species, "level": half.level}]
        await send_a({"event": "trade_offer", "player": "a", "slot": 0})
        token = srv.state.pending_trade["token"]
        await send_b({"event": "menu_result", "player": "b", "token": token, "choice": 1})
        assert srv.state.pending_trade["phase"] == "applying"
        before_await = {"event": "tick", "player": "b", "party": [mon(b_key, 19)]}
        await send_b(before_await)
        assert srv.state.pending_trade["verdict"]["b"] is None
        # Advance to the real watchdog boundary without thousands of identical transport messages.
        srv.state.pending_trade["age"] = srv.state.TRADE_WATCHDOG_EVENTS
        await send_a({"event": "noop", "player": "a"})
        assert srv.state.pending_trade["phase"] == "uncertain"
        assert srv.state.pending_trade["verdict"] == {"a": "await", "b": "await"}
        await send_a({"event": "tick", "player": "a", "party": [mon(a_key, 16)]})
        later = hello(doc, "b")
        later["party"] = [mon(b_key, 19)] + ([mon(a_key, 16)] if conflict else [])
        await send_b(later)
        rows = [json.loads(line) for line in audit.read_text().splitlines()]
        prior = next(row for row in rows if row["message"] == before_await)
        assert prior["outcome"]["pending_trade_before"]["phase"] == "applying"
        assert prior["outcome"]["pending_trade_before"]["verdict"]["b"] is None
        assert prior["outcome"]["pending_trade"]["verdict"]["b"] is None
        transition = next(row for row in rows if row["message"]["event"] == "noop")
        assert transition["outcome"]["pending_trade_before"]["verdict"]["b"] is None
        assert transition["outcome"]["pending_trade"]["verdict"] == {"a": "await", "b": "await"}
        assert transition["outcome"]["trade_problem"]["phase"] == "uncertain"
        assert transition["outcome"]["trade_last"]["outcome"] == "uncertain"
        final = rows[-1]
        assert final["message"] == later and prior["seq"] < transition["seq"] < final["seq"]
        assert final["outcome"]["pending_trade_before"]["verdict"]["b"] == "await"
        assert final["outcome"]["trade_problem"] == srv.state.trade_problem()
        assert final["outcome"]["trade_last"] == srv.state.trade_last
        if conflict:
            assert final["outcome"]["pending_trade"]["phase"] == "conflict"
            assert final["outcome"]["trade_problem"]["problem"]
        else:
            assert final["outcome"]["pending_trade"] is None
            assert srv.state.trade_last["outcome"] == "rolled_back"
        allowed = {"token", "phase", "a_key", "b_key", "verdict", "problem"}
        for row in rows:
            for name in ("pending_trade_before", "pending_trade"):
                pending = row["outcome"][name]
                assert pending is None or set(pending) <= allowed
            assert "accepted" not in row["outcome"]
    finally:
        await close_a()
        await close_b()
        restore()


@pytest.mark.asyncio
@pytest.mark.parametrize("event", ["hello", "tick", "safe"])
async def test_journal_observes_watchdog_await_before_same_dispatch_commit(tmp_path, event):
    from server.state import LinkEntry, LinkStatus, MonInfo

    doc = manifest()
    audit = tmp_path / "wire.jsonl"
    original_watchdog = server_module.SoulLinkState._tick_pending_trade
    restore = lane_module().install_server_gate(server_module, doc, audit_path=audit)
    srv = server_module.SLinkServer(data_dir=str(tmp_path))
    send_a, close_a = await _session(srv)
    send_b, close_b = await _session(srv)
    a_key, b_key = "1234:30B8:10", "5678:7B0B:13"
    try:
        await send_a(hello(doc, "a"))
        await send_b(hello(doc, "b"))
        entry = LinkEntry(area_id="route_29", a=MonInfo(key=a_key, species=16, level=5),
                          b=MonInfo(key=b_key, species=19, level=5), status=LinkStatus.ALIVE)
        srv.state.links.append(entry)
        srv.state._index_entry(entry)
        for side, half in (("a", entry.a), ("b", entry.b)):
            srv.state.party_keys[side].add(half.key)
            srv.state.partner_blobs[side] = [{"slot": 0, "key": half.key, "blob": bytes(70),
                                              "species_id": half.species, "level": half.level}]
        await send_a({"event": "trade_offer", "player": "a", "slot": 0})
        token = srv.state.pending_trade["token"]
        await send_b({"event": "menu_result", "player": "b", "token": token, "choice": 1})
        await send_a({"event": "trade_done", "player": "a", "token": token, "new_key": b_key, "new_species": 19})
        assert srv.state.pending_trade["verdict"] == {"a": "traded", "b": None}
        srv.state.pending_trade["age"] = srv.state.TRADE_WATCHDOG_EVENTS
        final = hello(doc, "b") if event == "hello" else {"event": event, "player": "b"}
        final["party"] = [{"key": a_key, "species_id": 16, "hp": 10, "maxHP": 10, "slot": 0, "level": 5}]
        await send_b(final)
        assert srv.state.pending_trade is None and srv.state.trade_last["outcome"] == "committed"
        assert entry.a.key == b_key and entry.b.key == a_key
        rows = [json.loads(line) for line in audit.read_text().splitlines()]
        row = next(row for row in rows if row["message"] == final)
        out = row["outcome"]
        assert out["pending_trade_before"]["phase"] == "applying"
        assert out["pending_trade_before"]["verdict"]["b"] is None
        assert out["watchdog_observed"] is True
        assert out["pending_trade_after_watchdog"]["phase"] == "uncertain"
        assert out["pending_trade_after_watchdog"]["verdict"] == {"a": "traded", "b": "await"}
        assert out["trade_problem_after_watchdog"]["verdict"]["b"] == "await"
        assert out["trade_last_after_watchdog"]["outcome"] == "uncertain"
        assert out["trade_last_after_watchdog"]["verdict"]["b"] == "await"
        assert out["pending_trade"] is None and out["trade_problem"] is None
        assert out["trade_last"]["outcome"] == "committed"
    finally:
        await close_a()
        await close_b()
        restore()
    assert server_module.SoulLinkState._tick_pending_trade is original_watchdog


@pytest.mark.parametrize("mode", ["own", "foreign", "raises"])
def test_watchdog_observation_is_scoped_and_restored(tmp_path, monkeypatch, mode):
    audit = tmp_path / "wire.jsonl"
    srv = server_module.SLinkServer(data_dir=str(tmp_path / "own"))
    foreign = server_module.SLinkServer(data_dir=str(tmp_path / "foreign"))
    original_watchdog = server_module.SoulLinkState._tick_pending_trade

    def original_dispatch(self, player, msg):
        state = foreign.state if mode == "foreign" else self.state
        state._tick_pending_trade()
        if mode == "raises":
            raise RuntimeError("after observed watchdog")
        return [{"cmd": "noop"}]

    monkeypatch.setattr(server_module.SLinkServer, "_dispatch", original_dispatch)
    restore = lane_module().install_server_gate(server_module, manifest(), audit_path=audit)
    try:
        message = {"event": "trade_query", "player": "a"}
        if mode == "raises":
            with pytest.raises(RuntimeError, match="after observed watchdog"):
                srv._dispatch("a", message)
        else:
            assert srv._dispatch("a", message) == [{"cmd": "noop"}]
        row = json.loads(audit.read_text())
        assert row["outcome"]["watchdog_observed"] is (mode != "foreign")
        assert row["outcome"]["pending_trade_after_watchdog"] is None
        previous = audit.read_bytes()
        srv.state._tick_pending_trade()  # Outside dispatch: no matching observation scope.
        foreign.state._tick_pending_trade()
        assert audit.read_bytes() == previous
    finally:
        restore()
    assert server_module.SLinkServer._dispatch is original_dispatch
    assert server_module.SoulLinkState._tick_pending_trade is original_watchdog
