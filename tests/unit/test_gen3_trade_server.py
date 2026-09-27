"""T4 protocol/model controls. Snapshots cannot prove a native save completed."""

from copy import deepcopy
import json

import pytest

from server.server import SLinkServer
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


def _server(tmp_path):
    srv = SLinkServer(data_dir=str(tmp_path))
    for pid in ("a", "b"):
        srv._dispatch(pid, _hello(pid, pc_boxes=[{"key": "00000003:" + pid * 8,
                                                "species_id": 25, "box": 0, "slot": 0}]))
        assert srv.is_admitted(pid) and not srv.state.identity_error.get(pid)
    return srv


def _applying(tmp_path):
    srv = _server(tmp_path)
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
    for pid in ("a", "b"):
        srv._dispatch(pid, {"event": "apply_ready", "token": token, "ok": True})
    assert srv.state.pending_trade["phase"] == "applying"
    return srv, entry, token


@pytest.mark.parametrize("event", ["hello", "tick", "safe"])
def test_hidden_snapshot_preserves_last_good_party_and_display(tmp_path, event):
    srv = _server(tmp_path)
    state = srv.state
    before = deepcopy((state.party_keys["a"], state.party_size["a"],
                       state.partner_blobs["a"], state.party_key_census["a"],
                       state.party_slots["a"], state.snapshot_no["a"],
                       srv.party_details["a"], srv.pc_boxes["a"]))
    msg = _hello("a", party=[], pc_boxes=[], pc_boxes_generation=2, party_hidden=True)
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


@pytest.mark.parametrize("change", [{"ot_id": "WRONG"}, {"ot_id": None},
                                    {"trade_outstanding": [{"token": "t1", "epoch": True}]}])
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


@pytest.mark.parametrize("epoch", [None, True, False, 0, -1, 1.0, 1.5, "7", 2**32])
def test_invalid_epoch_refuses_the_entire_hello_without_adoption(tmp_path, epoch):
    srv, entry, token = _applying(tmp_path)
    before = deepcopy((srv.state.pending_trade, srv.party_details, srv.state.player_identity))
    msg = _hello("a", party=[_mon("b")], trade_outstanding=[{"token": token, "epoch": epoch}])
    commands = srv._dispatch("a", msg)
    assert commands == [{"cmd": "noop", "refused": "trade_recovery"}]
    assert (srv.state.pending_trade, srv.party_details, srv.state.player_identity) == before
    assert msg.get("_rejected") and entry.a.key == KEYS["a"]


@pytest.mark.parametrize("records", [None, {}, "t1", [None], [{}],
                                      [{"token": "", "epoch": 1}],
                                      [{"token": 1, "epoch": 1}]])
def test_malformed_journal_is_not_an_empty_recovery(tmp_path, records):
    srv = _server(tmp_path)
    before = deepcopy(srv.party_details)
    msg = _hello("a", party=[], trade_outstanding=records)
    assert srv._dispatch("a", msg) == [{"cmd": "noop", "refused": "trade_recovery"}]
    assert srv.party_details == before and msg.get("_rejected")


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
    assert any("No linked pair" in c.get("text", "") for c in commands)
    assert not any(c["cmd"] == "choose_mon" for c in commands)


def test_recovery_does_not_deliver_an_apply_that_was_still_queued(tmp_path):
    srv, _entry, token = _applying(tmp_path)
    commands = srv._dispatch("a", _hello("a", trade_outstanding=[{"token": token, "epoch": 5}]))
    assert not any(c["cmd"] in ("apply_trade", "apply_prepare") for c in commands)
    assert srv.state.trade_problem()["verdict"]["a"] == "await"


def _legacy_trace(path, title, decorated):
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
def test_gen1_gen2_trade_bytes_ignore_the_gen3_recovery_extension(tmp_path, monkeypatch, title):
    monkeypatch.setattr("time.time", lambda: 1_800_000_000.25)
    original = _legacy_trace(tmp_path / "original", title, False)
    extended = _legacy_trace(tmp_path / "extended", title, True)
    assert extended == original
