"""T4 protocol/model controls. Snapshots cannot prove a native save completed."""

from copy import deepcopy
import json

import pytest
from aiohttp.test_utils import TestClient, TestServer

from server.server import SLinkServer, build_app
from server.state import LinkEntry, LinkStatus, MonInfo


KEYS = {"a": "00000001:00000011", "b": "00000002:00000022"}
TITLES = {"a": "firered", "b": "leafgreen"}


def _mon(pid, **extra):
    return {"key": KEYS[pid], "species_id": 1 if pid == "a" else 4,
            "level": 12, "slot": 0, "hp": 20, "maxHP": 20,
            "blob_hex": (bytes([1 if pid == "a" else 2]) * 100).hex(), **extra}


def _hello(pid, **extra):
    return {"event": "hello", "player": pid, "rom_type": TITLES[pid],
            "artifact_kind": "companion", "trainer_name": pid.upper(),
            "ot_id": "00000011" if pid == "a" else "00000022",
            "party": [_mon(pid)], "pc_boxes": [], "pc_boxes_generation": 1,
            "trade_prepare": True, **extra}


@pytest.mark.parametrize("title,opted_in", [("firered", True), ("emerald", True),
                                            ("firered_rr", True), ("Red", False), ("Crystal", False)])
def test_config_exposes_existing_run_id_only_to_recovery_clients(tmp_path, title, opted_in):
    srv = SLinkServer(data_dir=str(tmp_path), run_id="run_journal_42")
    commands = srv._dispatch("a", _hello("a", rom_type=title, artifact_kind="clean", party=[]))
    config = next(c for c in commands if c["cmd"] == "config")
    if opted_in:
        assert config["run_id"] == "run_journal_42"
    else:
        assert "run_id" not in config


def test_unmanaged_config_does_not_invent_a_run_identity(tmp_path):
    srv = SLinkServer(data_dir=str(tmp_path))
    config = next(c for c in srv._dispatch("a", _hello("a")) if c["cmd"] == "config")
    assert config["run_id"] == ""


def _server(tmp_path, title=None):
    srv = SLinkServer(data_dir=str(tmp_path))
    for pid in ("a", "b"):
        srv._dispatch(pid, _hello(pid, rom_type=title or TITLES[pid], pc_boxes=[{"key": "00000003:" + pid * 8,
                                                "species_id": 25, "box": 0, "slot": 0}]))
        assert srv.is_admitted(pid) and not srv.state.identity_error.get(pid)
    return srv


def _applying(tmp_path, *, prepare_only=False, title=None):
    srv = _server(tmp_path, title)
    entry = LinkEntry(area_id="route_1", status=LinkStatus.ALIVE,
                      a=MonInfo(key=KEYS["a"], species=1, level=12),
                      b=MonInfo(key=KEYS["b"], species=4, level=12))
    srv.state.links.append(entry)
    srv.state._index_entry(entry)
    srv._dispatch("a", {"event": "trade_request"})
    token = srv.state.pending_trade["token"]
    srv._dispatch("a", {"event": "menu_result", "token": token, "choice": 0})
    srv._dispatch("a", {"event": "mon_chosen", "token": token, "slot": 0})
    srv._dispatch("b", {"event": "menu_result", "token": token, "choice": 1})
    assert srv.state.pending_trade["phase"] == "preparing"
    if prepare_only:
        return srv, entry, token
    for pid in ("a", "b"):
        srv._dispatch(pid, {"event": "apply_ready", "token": token, "ok": True})
    assert srv.state.pending_trade["phase"] == "applying"
    return srv, entry, token


@pytest.mark.parametrize("event", ["hello", "tick", "safe"])
@pytest.mark.parametrize("title", ["firered", "emerald", "firered_rr"])
def test_hidden_snapshot_preserves_last_good_party_and_display(tmp_path, event, title):
    srv = _server(tmp_path, title)
    state = srv.state
    before = deepcopy((state.party_keys["a"], state.party_size["a"],
                       state.partner_blobs["a"], state.party_key_census["a"],
                       state.party_slots["a"], state.snapshot_no["a"],
                       srv.party_details["a"], srv.pc_boxes["a"]))
    msg = _hello("a", rom_type=title, party=[], pc_boxes=[], pc_boxes_generation=2, party_hidden=True)
    msg["event"] = event
    srv._dispatch("a", msg)
    after = (state.party_keys["a"], state.party_size["a"],
             state.partner_blobs["a"], state.party_key_census["a"],
             state.party_slots["a"], state.snapshot_no["a"],
             srv.party_details["a"], srv.pc_boxes["a"])
    assert after == before
    # Retained display is not a fresh census for identity migration.
    assert srv._presentation_key_in_use("not-present", "a", party=False) is None


def test_outstanding_hello_declares_before_any_party_evidence(tmp_path):
    srv, entry, token = _applying(tmp_path)
    before = deepcopy(srv.party_details["a"])
    declaration = [{"token": token, "epoch": 7}]
    for _ in range(2):
        srv._dispatch("a", _hello("a", party=[_mon("b")], trade_outstanding=declaration))
        problem = srv.state.trade_problem()
        assert problem and problem["verdict"]["a"] == "await"
        assert srv.state.pending_trade["hello_only"]["a"] is True
        assert srv.party_details["a"] == before
        assert (entry.a.key, entry.b.key) == (KEYS["a"], KEYS["b"])
    # A recovery declaration latches until a later visible HELLO; ticks/safe cannot lift it.
    srv._dispatch("a", {"event": "tick", "party": [_mon("b")]})
    srv._dispatch("a", {"event": "safe"})
    assert srv.state.trade_problem()["verdict"]["a"] == "await"
    assert srv.party_details["a"] == before
    srv._dispatch("a", _hello("a", party=[_mon("b")]))
    assert srv.state.trade_problem()["verdict"]["a"] == "traded"
    assert entry.a.key == KEYS["a"], "one side cannot settle a pair"
    srv._dispatch("b", {"event": "trade_done", "token": token,
                         "new_key": KEYS["a"], "new_species": 1})
    assert srv.state.pending_trade is None
    assert (entry.a.key, entry.b.key) == (KEYS["b"], KEYS["a"])


@pytest.mark.parametrize("change", [{"ot_id": "WRONG"}, {"ot_id": None}])
def test_refused_recovery_hello_cannot_tick_or_modify_the_pending_trade(tmp_path, change):
    srv, entry, token = _applying(tmp_path)
    srv.state.pending_trade["age"] = srv.state.TRADE_WATCHDOG_EVENTS
    before = deepcopy(srv.state.pending_trade)
    census = deepcopy(srv.box_census["a"])
    msg = _hello("a", trade_outstanding=[{"token": token, "epoch": 7}])
    msg.update(change)
    srv._dispatch("a", msg)
    assert msg.get("_rejected") and srv.state.identity_error["a"]
    assert srv.state.pending_trade == before
    assert srv.box_census["a"] == census
    assert not srv.state.trade_recovery_pending["a"]
    assert entry.a.key == KEYS["a"]


@pytest.mark.parametrize("epoch", [None, True, False, 0, -1, 1.5, "7", 2**32, float("nan"), float("inf")])
def test_invalid_epoch_holds_snapshot_without_refusing_identity(tmp_path, epoch):
    srv, entry, token = _applying(tmp_path)
    before = deepcopy((srv.party_details, srv.state.player_identity))
    msg = _hello("a", party=[_mon("b")], trade_outstanding=[{"token": token, "epoch": epoch}])
    commands = srv._dispatch("a", msg)
    assert not any(c.get("refused") or c["cmd"] == "apply_trade" for c in commands)
    assert (srv.party_details, srv.state.player_identity) == before
    assert not msg.get("_rejected") and not srv.state.identity_error.get("a")
    assert srv.state.pending_trade["verdict"]["a"] == "await"
    assert srv.state.party_hidden["a"] and srv.state.trade_recovery_pending["a"]
    assert entry.a.key == KEYS["a"]


@pytest.mark.parametrize("records", [None, {}, "t1", [None], [{}],
                                      [{"token": "", "epoch": 1}],
                                      [{"token": 1, "epoch": 1}]])
def test_malformed_journal_is_not_an_empty_recovery(tmp_path, records):
    srv = _server(tmp_path)
    before = deepcopy(srv.party_details)
    msg = _hello("a", party=[], trade_outstanding=records)
    commands = srv._dispatch("a", msg)
    assert not any(c.get("refused") for c in commands)
    assert srv.party_details == before and not msg.get("_rejected")
    assert srv.state.party_hidden["a"] and srv.state.trade_recovery_pending["a"]


@pytest.mark.parametrize("swapped", [False, True])
def test_both_hello_only_sides_need_separate_visible_hellos(tmp_path, swapped):
    srv, entry, token = _applying(tmp_path)
    for pid, epoch in (("a", 1), ("b", 0xFFFFFFFF)):
        srv._dispatch(pid, _hello(pid, trade_outstanding=[{"token": token, "epoch": epoch}]))
    assert srv.state.trade_problem()["verdict"] == {"a": "await", "b": "await"}
    for pid in ("a", "b"):
        partner = "b" if pid == "a" else "a"
        party = [_mon(partner if swapped else pid)]
        srv._dispatch(pid, {"event": "tick", "party": party})
        assert srv.state.trade_problem()["verdict"][pid] == "await"
        srv._dispatch(pid, _hello(pid, party=party))
        if pid == "a":
            assert srv.state.pending_trade and entry.a.key == KEYS["a"]
    assert srv.state.pending_trade is None
    assert (entry.a.key, entry.b.key) == ((KEYS["b"], KEYS["a"]) if swapped
                                        else (KEYS["a"], KEYS["b"]))


def test_outstanding_journal_survives_server_restart_without_inventing_a_snapshot(tmp_path):
    srv, _entry, token = _applying(tmp_path)
    declaration = [{"token": token, "epoch": 91}]
    for _ in range(2):
        srv._dispatch("a", _hello("a", trade_outstanding=declaration))
    saved = json.loads((tmp_path / "links.json").read_text())
    assert saved["pending_trade"]["recovery_epochs"] == {"a": [91]}
    restarted = SLinkServer(data_dir=str(tmp_path))
    assert restarted.state.pending_trade["hello_only"] == {"a": True}
    assert not restarted.party_details["a"]
    restarted._dispatch("a", _hello("a", trade_outstanding=declaration, party=[_mon("b")]))
    restarted._dispatch("a", {"event": "tick", "party": [_mon("b")]})
    assert restarted.state.trade_problem()["verdict"]["a"] == "await"
    assert not restarted.party_details["a"]
    restarted._dispatch("a", _hello("a", party=[_mon("b")]))
    assert restarted.state.trade_problem()["verdict"]["a"] == "traded"


@pytest.mark.parametrize("action", ["commit", "rollback"])
def test_admin_resolution_does_not_release_hidden_ram_or_send_forget(tmp_path, action):
    srv, entry, token = _applying(tmp_path)
    for pid in ("a", "b"):
        srv._dispatch(pid, _hello(pid, trade_outstanding=[{"token": token, "epoch": 3}]))
    before = deepcopy(srv.party_details)
    assert srv.state.resolve_trade(token, action) == (True, "")
    assert srv.state.pending_trade is None
    for pid in ("a", "b"):
        commands = srv._dispatch(pid, {"event": "tick", "party": [_mon("b")]})
        assert not any(c["cmd"] in ("trade_cleared", "forget_trade", "withdraw_trade") for c in commands)
    assert srv.party_details == before
    assert all(srv.state.party_hidden.values())
    assert entry.a.key == KEYS["b" if action == "commit" else "a"]
    # The server may already have forgotten the token; local durable reload still precedes this.
    srv._dispatch("a", _hello("a", party=[_mon("b" if action == "commit" else "a")]))
    assert not srv.state.party_hidden["a"]


def test_stale_token_cannot_declare_the_new_pending_trade_uncertain(tmp_path):
    srv, _entry, token = _applying(tmp_path)
    before = deepcopy(srv.state.pending_trade)
    srv._dispatch("a", _hello("a", trade_outstanding=[{"token": token + "-old", "epoch": 3}]))
    # A withheld hello does not supply party evidence, including for a different pending token.
    assert srv.state.pending_trade["verdict"] == before["verdict"]
    assert "hello_only" not in srv.state.pending_trade
    assert "recovery_epochs" not in srv.state.pending_trade
    assert srv.state.pending_trade["phase"] == "applying"


def test_hidden_borrowed_party_is_not_a_faint_and_snapshot_free_safe_keeps_it_hidden(tmp_path):
    srv, entry, token = _applying(tmp_path)
    before = deepcopy(srv.party_details)
    srv._dispatch("a", _hello("a", party=[_mon("a", hp=0)], party_hidden=True))
    srv._dispatch("a", {"event": "safe"})
    assert srv.state.party_hidden["a"] and srv.party_details == before
    assert entry.status == LinkStatus.ALIVE
    assert srv.state.pending_trade["verdict"]["a"] is None
    # Return from a borrowed-party episode: a visible snapshot is fresh again.
    srv._dispatch("a", {"event": "tick", "party": [_mon("a")]})
    assert not srv.state.party_hidden["a"]


def test_preserved_cache_cannot_authorize_a_second_trade_while_hidden(tmp_path):
    srv, _entry, token = _applying(tmp_path)
    for pid in ("a", "b"):
        srv._dispatch(pid, _hello(pid, trade_outstanding=[{"token": token, "epoch": 1}]))
    assert srv.state.resolve_trade(token, "rollback") == (True, "")
    srv._dispatch("b", {"event": "trade_request"})
    token2 = srv.state.pending_trade["token"]
    commands = srv._dispatch("b", {"event": "menu_result", "token": token2, "choice": 0})
    assert any("party withheld" in c.get("text", "") for c in commands)
    assert not any(c["cmd"] == "choose_mon" for c in commands)


def test_recovery_does_not_deliver_an_apply_that_was_still_queued(tmp_path):
    srv, _entry, token = _applying(tmp_path)
    commands = srv._dispatch("a", _hello("a", trade_outstanding=[{"token": token, "epoch": 5}]))
    assert not any(c["cmd"] in ("apply_trade", "apply_prepare") for c in commands)
    assert srv.state.trade_problem()["verdict"]["a"] == "await"


@pytest.mark.parametrize("barrier", ["journal", "hidden", "hello_only"])
@pytest.mark.parametrize("outcome", ["traded", "unchanged"])
def test_barred_terminal_report_waits_for_visible_hello(tmp_path, barrier, outcome):
    srv, entry, token = _applying(tmp_path)
    if barrier == "journal":
        srv._dispatch("a", _hello("a", trade_outstanding=[{"token": token, "epoch": 9}]))
    elif barrier == "hidden":
        srv._dispatch("a", _hello("a", party_hidden=True, party=[]))
    else:
        srv._dispatch("a", {"event": "trade_done", "token": token,
                             "uncertain": True, "after_reset": True})
    donor = "b" if outcome == "traded" else "a"
    srv._dispatch("a", {"event": "trade_done", "token": token,
                         "new_key": KEYS[donor], "new_species": _mon(donor)["species_id"]})
    srv._dispatch("b", {"event": "trade_done", "token": token,
                         "new_key": KEYS["a" if outcome == "traded" else "b"], "new_species": 1})
    assert srv.state.pending_trade and srv.state.pending_trade["verdict"]["a"] == "await"
    assert entry.a.key == KEYS["a"] and entry.b.key == KEYS["b"]
    srv._dispatch("a", _hello("a", party=[_mon(donor)]))
    assert srv.state.pending_trade is None
    assert entry.a.key == KEYS[donor]


@pytest.mark.parametrize("kind", ["admin_resolved", "older_token", "borrowed"])
def test_hidden_barrier_survives_restart_without_a_matching_pending_trade(tmp_path, kind):
    if kind == "admin_resolved":
        srv, _entry, token = _applying(tmp_path)
        for pid in ("a", "b"):
            srv._dispatch(pid, _hello(pid, trade_outstanding=[{"token": token, "epoch": 4}]))
        assert srv.state.resolve_trade(token, "rollback") == (True, "")
    else:
        srv = _server(tmp_path)
        fields = ({"trade_outstanding": [{"token": "old-token", "epoch": 4}]}
                  if kind == "older_token" else {"party_hidden": True})
        srv._dispatch("a", _hello("a", **fields))
    restarted = SLinkServer(data_dir=str(tmp_path))
    assert restarted.state.pending_trade is None
    assert restarted.state.party_hidden["a"]
    assert restarted.state.trade_recovery_pending["a"] is (kind != "borrowed")
    restarted._dispatch("a", {"event": "safe"})
    assert restarted.state.party_hidden["a"]
    if kind != "borrowed":
        restarted._dispatch("a", {"event": "tick", "party": [_mon("b")]})
        assert not restarted.party_details["a"]
    restarted._dispatch("a", _hello("a"))
    again = SLinkServer(data_dir=str(tmp_path))
    assert not again.state.party_hidden["a"] and not again.state.trade_recovery_pending["a"]


@pytest.mark.asyncio
async def test_malformed_recovery_stays_connected_hidden_and_visible_on_board(tmp_path):
    srv, _entry, _token = _applying(tmp_path)
    before = deepcopy(srv.party_details["a"])
    msg = _hello("a", party=[_mon("b")], trade_outstanding=None)
    commands = srv._dispatch("a", msg)
    assert not msg.get("_rejected") and not srv.state.identity_error.get("a")
    assert not any(c.get("refused") or c["cmd"] == "apply_trade" for c in commands)
    assert srv.party_details["a"] == before
    assert srv.state.trade_last and srv.state.trade_last["outcome"] == "uncertain"
    recovery = srv._build_status_dict()["players"]["a"]["trade_recovery"]
    assert recovery["hidden"] and recovery["pending"] and recovery["problem"]
    async with TestClient(TestServer(build_app(srv))) as client:
        response = await client.get("/")
        html = await response.text()
        assert response.status == 200
        assert "Player A: party withheld" in html and recovery["problem"] in html
    restarted = SLinkServer(data_dir=str(tmp_path))
    assert restarted.state.trade_recovery_errors["a"] == recovery["problem"]


@pytest.mark.parametrize("epoch", [1.0, 4294967295.0])
def test_integral_float_epoch_is_accepted_and_persisted_as_an_integer(tmp_path, epoch):
    srv, _entry, token = _applying(tmp_path)
    msg = _hello("a", trade_outstanding=[{"token": token, "epoch": epoch}])
    srv._dispatch("a", msg)
    assert not msg.get("_rejected") and not srv.state.identity_error.get("a")
    assert srv.state.pending_trade["recovery_epochs"] == {"a": [int(epoch)]}
    saved = json.loads((tmp_path / "links.json").read_text())
    assert type(saved["pending_trade"]["recovery_epochs"]["a"][0]) is int


def test_malformed_recovery_does_not_deliver_a_queued_prepare(tmp_path):
    srv, _entry, _token = _applying(tmp_path, prepare_only=True)
    commands = srv._dispatch("a", _hello("a", trade_outstanding=None))
    assert not any(c["cmd"] in ("apply_trade", "apply_prepare") for c in commands)
    assert srv.state.party_hidden["a"] and not srv.state.identity_error.get("a")


def test_hidden_hello_does_not_requeue_memorial_writes(tmp_path):
    srv = _server(tmp_path)
    srv.state.pending_memorials["a"].add("00000008:00000011")
    commands = srv._dispatch("a", _hello("a", party_hidden=True))
    assert not any(c["cmd"] == "memorialize" for c in commands)
    commands = srv._dispatch("a", _hello("a"))
    assert any(c["cmd"] == "memorialize" and c["key"] == "00000008:00000011" for c in commands)


def test_abandoned_prepare_drops_queued_apply_commands_for_its_token(tmp_path):
    srv, _entry, token = _applying(tmp_path, prepare_only=True)
    # Delayed queue residue must be retired together, regardless of opcode.
    srv.state.queued_commands["a"].append({"cmd": "apply_trade", "token": token})
    srv.state.queued_commands["a"].append({"cmd": "hud_show", "text": "unrelated"})
    srv.state.pending_trade["age"] = srv.state.TRADE_WATCHDOG_EVENTS
    commands = srv._dispatch("a", {"event": "tick"})
    assert srv.state.pending_trade is None
    assert not any(c["cmd"] in ("apply_trade", "apply_prepare") and c.get("token") == token
                   for c in commands + srv.state.queued_commands["b"])
    assert {"cmd": "hud_show", "text": "unrelated"} in commands


@pytest.mark.parametrize("title", ["firered_ap", "leafgreen_ap"])
def test_ap_adapter_consumes_recovery_extension(tmp_path, title):
    srv = SLinkServer(data_dir=str(tmp_path))
    msg = _hello("a", rom_type=title, party_hidden=True)
    srv._dispatch("a", msg)
    assert not msg.get("_rejected") and srv.state.party_hidden["a"]
    assert not srv.party_details["a"]


def test_expansion_adapter_refuses_unsupported_recovery_extension_by_name(tmp_path):
    srv = SLinkServer(data_dir=str(tmp_path))
    msg = _hello("a", rom_type="emerald_expansion_28877d73", party_hidden=True)
    commands = srv._dispatch("a", msg)
    assert msg.get("_rejected")
    assert "Trade recovery extension unavailable" in srv.state.identity_error["a"]
    assert commands == [{"cmd": "noop", "refused": "trade_recovery"}]


def test_partner_confirm_names_the_withheld_party(tmp_path):
    srv, _entry, token = _applying(tmp_path, prepare_only=True)
    srv._dispatch("a", _hello("a", party_hidden=True))
    srv._dispatch("a", {"event": "apply_ready", "token": token, "ok": True})
    commands = srv._dispatch("b", {"event": "apply_ready", "token": token, "ok": True})
    assert srv.state.pending_trade is None
    assert any("party withheld" in c.get("text", "") for c in commands)
    assert not any("no longer available" in c.get("text", "") for c in commands)


@pytest.mark.parametrize("traded,verdict", [(True, "committed"), (False, "rolled_back")])
def test_final_settlement_sends_bookkeeping_receipt_to_both_sides(tmp_path, traded, verdict):
    srv, _entry, token = _applying(tmp_path)
    replies = {}
    for pid in ("a", "b"):
        donor = ("b" if pid == "a" else "a") if traded else pid
        replies[pid] = srv._dispatch(pid, {"event": "trade_done", "token": token,
                                           "new_key": KEYS[donor], "new_species": _mon(donor)["species_id"]})
    replies["a"] += srv._dispatch("a", {"event": "tick"})
    for pid in ("a", "b"):
        assert [c for c in replies[pid] if c["cmd"] == "trade_final"] == [
            {"cmd": "trade_final", "token": token, "verdict": verdict}]
    saved = json.loads((tmp_path / "links.json").read_text())
    assert saved["trade_finals"] == {
        pid: [{"token": token, "verdict": verdict}] for pid in ("a", "b")}


@pytest.mark.parametrize("action", ["commit", "rollback", "split"])
def test_admin_final_receipt_preserves_barrier_and_replays_after_restart(tmp_path, action):
    srv, _entry, token = _applying(tmp_path)
    for pid, epoch in (("a", 11), ("b", 22)):
        srv._dispatch(pid, _hello(pid, trade_outstanding=[{"token": token, "epoch": epoch}]))
    sides = {"a": "traded", "b": "none"} if action == "split" else None
    assert srv.state.resolve_trade(token, "adopt" if sides else action, sides) == (True, "")
    for pid, epoch in (("a", 11), ("b", 22)):
        commands = srv._dispatch(pid, {"event": "tick"})
        assert {"cmd": "trade_final", "token": token, "epoch": epoch, "verdict": "resolved"} in commands
        assert srv.state.party_hidden[pid] and srv.state.trade_recovery_pending[pid]
    restarted = SLinkServer(data_dir=str(tmp_path), run_id="run_journal_42")
    for _ in range(2):
        commands = restarted._dispatch("a", _hello("a", trade_outstanding=[{"token": token, "epoch": 11}]))
        receipt = {"cmd": "trade_final", "token": token, "epoch": 11, "verdict": "resolved"}
        assert commands.count(receipt) == 1
        assert next(i for i,c in enumerate(commands) if c["cmd"] == "config") < commands.index(receipt)
        assert restarted.state.party_hidden["a"] and restarted.state.trade_recovery_pending["a"]


def test_direct_split_emits_split_bookkeeping_receipts(tmp_path):
    srv, _entry, token = _applying(tmp_path)
    srv.state._split_trade(srv.state.pending_trade, "a")
    for pid in ("a", "b"):
        assert {"cmd": "trade_final", "token": token, "verdict": "split"} in srv._dispatch(pid, {"event": "tick"})


def test_final_history_is_bounded_and_replay_is_per_side(tmp_path):
    srv = _server(tmp_path)
    saved = json.loads((tmp_path / "links.json").read_text())
    limit = srv.state.TRADE_FINAL_LIMIT
    saved["trade_finals"] = {
        "a": [{"token": f"old-{i}", "verdict": "committed"} for i in range(limit + 1)],
        "b": [{"token": "only-b", "verdict": "rolled_back"}]}
    (tmp_path / "links.json").write_text(json.dumps(saved))
    srv, _entry, token = _applying(tmp_path)
    for pid in ("a", "b"):
        srv._dispatch(pid, {"event": "trade_done", "token": token, "new_key": KEYS[pid], "new_species": 0})
    restarted = SLinkServer(data_dir=str(tmp_path))
    assert len(restarted.state.trade_finals["a"]) == limit
    assert "old-0" not in restarted.state.trade_finals["a"] and "old-1" not in restarted.state.trade_finals["a"]
    records = [{"token": value, "epoch": 17} for value in ("old-0", "old-1", "only-b", token, "unknown", token)]
    commands = restarted._dispatch("a", _hello("a", trade_outstanding=records))
    assert [c for c in commands if c["cmd"] == "trade_final"] == [
        {"cmd": "trade_final", "token": token, "verdict": "rolled_back", "epoch": 17}]
    assert restarted.state.party_hidden["a"]
    commands = restarted._dispatch("b", _hello("b", trade_outstanding=[{"token": "only-b", "epoch": 19}]))
    assert {"cmd": "trade_final", "token": "only-b", "epoch": 19, "verdict": "rolled_back"} in commands


def test_no_final_receipt_before_final_record_is_durable(tmp_path, monkeypatch):
    srv, _entry, token = _applying(tmp_path)
    write = srv.state._atomic_write_json
    def fail(*_args):
        raise OSError("write unavailable")
    monkeypatch.setattr(srv.state, "_atomic_write_json", fail)
    for pid in ("a", "b"):
        commands = srv._dispatch(pid, {"event": "trade_done", "token": token,
                                      "new_key": KEYS[pid], "new_species": 0})
        assert not any(c["cmd"] == "trade_final" for c in commands)
    assert srv.state.save_failed and srv.state.pending_trade is None
    disk = json.loads((tmp_path / "links.json").read_text())
    assert not disk.get("trade_finals", {}).get("a")
    monkeypatch.setattr(srv.state, "_atomic_write_json", write)
    commands = srv._dispatch("a", _hello("a", trade_outstanding=[{"token": token, "epoch": 7}]))
    assert {"cmd": "trade_final", "token": token, "epoch": 7, "verdict": "rolled_back"} in commands
    assert not srv.state.save_failed and srv.state.party_hidden["a"]


def test_wrong_save_cannot_receive_queued_or_replayed_final_receipt(tmp_path):
    srv, _entry, token = _applying(tmp_path)
    for pid in ("a", "b"):
        srv._dispatch(pid, {"event": "trade_done", "token": token, "new_key": KEYS[pid], "new_species": 0})
    commands = srv._dispatch("a", _hello("a", ot_id="WRONG", trade_outstanding=[{"token": token, "epoch": 7}]))
    assert not any(c["cmd"] == "trade_final" for c in commands)
    assert srv.state.identity_error["a"]
    commands = srv._dispatch("a", _hello("a", trade_outstanding=[{"token": token, "epoch": 7}]))
    assert [c for c in commands if c["cmd"] == "trade_final"] == [
        {"cmd": "trade_final", "token": token, "epoch": 7, "verdict": "rolled_back"}]


def test_old_final_receipt_does_not_settle_a_new_trade_or_clear_recovery(tmp_path):
    srv, entry, old_token = _applying(tmp_path)
    for pid in ("a", "b"):
        srv._dispatch(pid, {"event": "trade_done", "token": old_token, "new_key": KEYS[pid], "new_species": 0})
        srv._dispatch(pid, _hello(pid))
    srv._dispatch("a", {"event": "trade_request"})
    token = srv.state.pending_trade["token"]
    srv._dispatch("a", {"event": "menu_result", "token": token, "choice": 0})
    srv._dispatch("a", {"event": "mon_chosen", "token": token, "slot": 0})
    srv._dispatch("b", {"event": "menu_result", "token": token, "choice": 1})
    for pid in ("a", "b"):
        srv._dispatch(pid, {"event": "apply_ready", "token": token, "ok": True})
    commands = srv._dispatch("a", _hello("a", party=[_mon("b")],
                                         trade_outstanding=[{"token": old_token, "epoch": 5}]))
    assert {"cmd": "trade_final", "token": old_token, "epoch": 5, "verdict": "rolled_back"} in commands
    assert srv.state.pending_trade["token"] == token
    assert srv.state.pending_trade["verdict"] == {"a": None, "b": None}
    assert (entry.a.key, entry.b.key) == (KEYS["a"], KEYS["b"])
    assert srv.state.party_hidden["a"] and srv.state.trade_recovery_pending["a"]


def test_final_receipt_is_one_way_bookkeeping_with_a_bounded_epoch():
    from tests.unit import protocol_schema as schema
    assert "trade_final" not in schema.ACKS and "trade_final" not in schema.DEFERRED
    for verdict in ("committed", "rolled_back", "split", "resolved"):
        assert not schema.validate_command({"cmd": "trade_final", "token": "t1", "verdict": verdict})
        assert not schema.validate_command({"cmd": "trade_final", "token": "t1", "verdict": verdict,
                                            "epoch": 0xFFFFFFFF})
    for fields in ({"token": ""}, {"verdict": "await"}, {"epoch": True}, {"epoch": 0},
                   {"epoch": 1.5}, {"epoch": None}, {"epoch": 2**32}):
        assert schema.validate_command({"cmd": "trade_final", "token": "t1", "verdict": "committed", **fields})


@pytest.mark.parametrize("title", ["firered", "emerald", "firered_rr"])
@pytest.mark.parametrize("via", ["state", "server"])
@pytest.mark.parametrize("event", ["capture", "faint", "party_to_box", "box_to_party",
                                    "key_change", "whiteout", "release"])
def test_hidden_player_cannot_mutate_game_state(tmp_path, caplog, title, via, event):
    srv, _entry, _token = _applying(tmp_path, title=title)
    srv._dispatch("a", _hello("a", rom_type=title, party_hidden=True))
    state = srv.state
    snapshot = lambda: deepcopy((state.links, state.party_keys, state.pending_captures,
                                 state.pending_trade, state.queued_commands, state.sync_inflight,
                                 srv.party_details, srv.pc_boxes, srv._mon_cache))
    before = snapshot()
    msg = {"event": event, "key": KEYS["a"], "old_key": KEYS["a"],
           "new_key": "00000009:00000011", "new_species": 25, "reason": "npc_trade",
           "area_id": "route_2", "species_id": 25, "level": 10, "hp": 20, "maxHP": 20}
    if event == "capture":
        msg["key"] = "00000009:00000011"
    elif event == "whiteout":
        msg = {"event": event}
    call = state.handle_event if via == "state" else srv._dispatch
    assert call("a", msg) == [{"cmd": "noop", "refused": "party_hidden"}]
    assert snapshot() == before
    assert event in caplog.text and "party hidden" in caplog.text


def test_empty_visible_hello_releases_visibility_but_is_not_trade_evidence(tmp_path):
    srv, entry, token = _applying(tmp_path)
    srv._dispatch("a", _hello("a", trade_outstanding=[{"token": token, "epoch": 7}]))
    srv._dispatch("a", _hello("a", party=[]))
    assert not srv.state.party_hidden["a"] and not srv.state.trade_recovery_pending["a"]
    assert srv.state.pending_trade["verdict"]["a"] == "await"
    assert srv.state.pending_trade["hello_only"]["a"] is True
    assert srv.state.party_keys["a"] == set() and srv.state.party_size["a"] == 0
    assert srv.state.partner_blobs["a"] == [] and srv.party_details["a"] == {}
    assert entry.a.key == KEYS["a"] and entry.b.key == KEYS["b"]


def test_recovery_capability_refusal_is_not_reported_as_wrong_save(tmp_path):
    from server.board import connection_state
    srv = SLinkServer(data_dir=str(tmp_path))
    srv._dispatch("a", _hello("a", rom_type="emerald_expansion_28877d73", party_hidden=True))
    connection = connection_state(srv._build_status_dict()["players"]["a"], live=True)
    assert connection["slug"] == "wrong_game"
    assert connection["label"] == "Unsupported recovery"
    assert "Trade recovery extension unavailable" in connection["line"]
    assert "Wrong save" not in connection["line"] and "different trainer" not in connection["line"]


@pytest.mark.asyncio
async def test_recovery_banner_displays_and_escapes_the_actual_problem(tmp_path):
    srv = _server(tmp_path)
    srv._dispatch("a", _hello("a", party_hidden=True))
    srv.state.trade_recovery_errors["a"] = "Unreadable <journal> & lease"
    async with TestClient(TestServer(build_app(srv))) as client:
        html = await (await client.get("/")).text()
    assert "Unreadable &lt;journal&gt; &amp; lease" in html
    assert "Unreadable <journal>" not in html


def _legacy_trace(path, title, decorated, rejected=False):
    """Protocol replies + persisted state bytes for the accepted GB trade flow."""
    srv = SLinkServer(data_dir=str(path))
    kind = "overlay" if title in ("Crystal", "Gold", "Silver") else "companion"
    keys = {"a": "AAAA:1111:01", "b": "BBBB:2222:04"}
    replies = []

    def send(pid, **msg):
        if decorated and msg["event"] in ("hello", "tick", "safe"):
            # Neither a valid marker nor an invalid Gen 3 journal affects an older protocol.
            msg.update(party_hidden=True, trade_outstanding=[{"token": "t1", "epoch": False}])
        replies.append(srv._dispatch(pid, msg))

    def hello(pid, partner=None):
        donor = partner or pid
        blob_size = srv.adapter.party_blob_size()
        return {"event": "hello", "rom_type": title, "artifact_kind": kind,
                "ot_id": "1111" if pid == "a" else "2222", "trainer_name": pid.upper(),
                "trade_prepare": True, "party": [{"key": keys[donor], "slot": 0,
                    "hp": 20, "maxHP": 20, "level": 12, "species_id": 1 if donor == "a" else 4,
                    "blob_hex": (bytes([1 if donor == "a" else 4]) * blob_size).hex()}]}

    # Establish the adapter before choosing its record size.
    send("a", event="hello", rom_type=title, artifact_kind=kind, ot_id="1111", party=[])
    for pid in ("a", "b"):
        send(pid, **hello(pid))
    if rejected:
        wrong = hello("a")
        wrong["ot_id"] = "WRONG"
        send("a", **wrong)
        assert srv.state.identity_error.get("a")
        send("a", **hello("a"))
        assert not srv.state.identity_error.get("a")
    entry = LinkEntry(area_id="route_1", status=LinkStatus.ALIVE,
                      a=MonInfo(key=keys["a"], species=1), b=MonInfo(key=keys["b"], species=4))
    srv.state.links.append(entry)
    srv.state._index_entry(entry)
    send("a", event="trade_query")
    send("a", event="trade_offer", slot=0)
    token = srv.state.pending_trade["token"]
    send("b", event="menu_result", token=token, choice=1)
    for pid in ("a", "b"):
        send(pid, event="apply_ready", token=token, ok=True)
    send("a", event="trade_done", token=token, uncertain=True, after_reset=True)
    send("a", event="tick", party=hello("a", "b")["party"])
    assert srv.state.pending_trade["verdict"]["a"] == "await"
    send("a", **hello("a", "b"))
    send("b", event="trade_done", token=token, new_key=keys["a"], new_species=1)
    assert srv.state.pending_trade is None and entry.a.key == keys["b"]
    send("b", event="safe")
    # Text serialization checks command key order and values, not just dict equality.
    return json.dumps(replies, ensure_ascii=False).encode() + b"\n" + (path / "links.json").read_bytes()


@pytest.mark.parametrize("title", ["Red", "Blue", "Crystal", "Gold", "Silver"])
@pytest.mark.parametrize("rejected", [False, True])
def test_gen1_gen2_trade_bytes_ignore_the_gen3_recovery_extension(tmp_path, monkeypatch, title, rejected):
    monkeypatch.setattr("time.time", lambda: 1_800_000_000.25)
    original = _legacy_trace(tmp_path / "original", title, False, rejected)
    extended = _legacy_trace(tmp_path / "extended", title, True, rejected)
    assert extended == original
