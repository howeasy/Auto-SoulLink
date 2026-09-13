"""Gen1-only CONTROL hint may schedule, but never deliver, durable commands."""

import json

import pytest

from server.protocol import canonical_json, decode_frame
from server.protocol_journal import JournalError
from tests.unit.test_gen1_runtime_client import client
from tests.unit.test_gen1_runtime_server import RuntimeCase


class PairedHintCase:
    def __init__(self, path):
        self.case = RuntimeCase(path)
        self.clients = {
            player: client(self.case, player, control_interval=0.5, sync_interval=0.5)
            for player in ("a", "b")
        }
        self.owners = {player: object() for player in self.clients}
        self.sent = []
        self.ticks = 0
        self.response_hook = None

    def tick(self):
        self.ticks += 1
        self.case.time = 10 + self.ticks * 0.05
        for player, lua in self.clients.items():
            globals_ = lua.globals()
            globals_.t = self.ticks * 0.05
            assert globals_.step() is True
            while (line := globals_.pop()) is not None:
                message = decode_frame(line.encode())
                response = self.case.runtime.process(message, self.owners[player])
                self.sent.append((player, message, response))
                if self.response_hook is not None:
                    response = self.response_hook(player, message, response)
                if response is not None:
                    globals_.push(canonical_json(response))

    def run(self, count):
        for _ in range(count):
            self.tick()

    def messages(self, player, event):
        return [row for row in self.sent if row[0] == player and row[1]["event"] == event]

    def state(self, player):
        return json.loads(self.clients[player].globals().state_json())

    def status(self, player):
        return json.loads(self.clients[player].globals().status_json())

    def close(self):
        self.case.close()


@pytest.fixture
def pair(tmp_path):
    value = PairedHintCase(tmp_path)
    yield value
    value.close()


def test_gen1_control_hint_is_current_boolean_and_tracks_new_pending_command(tmp_path):
    case = RuntimeCase(tmp_path)
    try:
        case.admit("a")
        case.admit("b")
        before = case.control("b")[1]
        assert before["pending_delivery"] is False and before["commands"] == []
        assert case.control("a")[1]["pending_delivery"] is False
        case.send("a", {"event": "faint", "key": case.keys["a"]})
        assert case.runtime.journal.pending_ids("b")
        after = case.control("b")[1]
        assert after["pending_delivery"] is True and after["commands"] == []
    finally:
        case.close()


def test_hint_reads_pending_index_after_gen1_control_side_effects(tmp_path, monkeypatch):
    case = RuntimeCase(tmp_path)
    try:
        case.admit("a")
        case.admit("b")
        trace = []
        checked = case.runtime._control_checked
        pending = case.runtime.journal.pending_ids

        def checked_control(player, message):
            response = checked(player, message)
            trace.append("control_complete")
            return response

        def fresh_pending(player):
            result = pending(player)
            trace.append("pending_index")
            return result

        monkeypatch.setattr(case.runtime, "_control_checked", checked_control)
        monkeypatch.setattr(case.runtime.journal, "pending_ids", fresh_pending)
        assert case.control("a")[1]["pending_delivery"] is False
        assert trace[-2:] == ["control_complete", "pending_index"]
    finally:
        case.close()


def test_corrupt_pending_index_refuses_control_instead_of_sending_zero_hint(tmp_path, monkeypatch):
    case = RuntimeCase(tmp_path)
    try:
        case.admit("a")
        case.admit("b")
        checked = case.runtime._control_checked
        complete = False

        def checked_control(player, message):
            nonlocal complete
            response = checked(player, message)
            complete = True
            return response

        def broken_index(_player):
            if complete:
                raise JournalError("corrupt pending index")
            return ()

        monkeypatch.setattr(case.runtime, "_control_checked", checked_control)
        monkeypatch.setattr(case.runtime.journal, "pending_ids", broken_index)
        revision = case.runtime.journal.snapshot().revision
        with pytest.raises(JournalError, match="corrupt pending index"):
            case.control("a")
        assert case.runtime.journal.snapshot().revision == revision
    finally:
        case.close()


def test_current_zero_hint_skips_idle_sync_but_keeps_repeated_control(pair):
    initial_writes = {player: lua.globals().writes for player, lua in pair.clients.items()}
    pair.run(40)
    for player, lua in pair.clients.items():
        assert len(pair.messages(player, "control")) >= 3
        assert pair.messages(player, "sync") == []
        assert lua.globals().writes == initial_writes[player]
        assert pair.state(player)["outbox"] == []
        assert pair.status(player)["pending_events"] == 0
        assert pair.status(player)["failed"] is False


def test_peer_command_after_zero_hint_uses_one_durable_sync_and_persists_inbox(pair):
    pair.run(4)
    assert pair.messages("b", "sync") == []
    assert pair.messages("b", "control")[-1][2]["pending_delivery"] is False
    pair.clients["a"].globals().observe(json.dumps([{"event": "faint", "key": pair.case.keys["a"]}]))
    pair.tick()
    assert pair.case.runtime.journal.pending_ids("b")
    assert pair.messages("b", "sync") == []
    for _ in range(20):
        pair.tick()
        if pair.state("b")["inbox"]:
            break
    else:
        pytest.fail("peer command did not reach the durable client inbox")
    syncs = pair.messages("b", "sync")
    assert len(syncs) == 1
    assert pair.messages("b", "control")[-1][2]["pending_delivery"] is True
    assert pair.state("b")["outbox"] == []
    assert pair.state("b")["inbox"][0]["body"]["cmd"] == "force_faint"
    assert pair.clients["b"].globals().applied == 0


def test_positive_hint_is_consumed_by_one_sync_not_an_idle_sync_loop(pair):
    def alter(player, message, response):
        if player == "b" and message["event"] == "control":
            response = dict(response)
            response["pending_delivery"] = True
        return response

    pair.response_hook = alter
    pair.run(9)  # Before another 0.5-second CONTROL can legitimately refresh the hint.
    assert len(pair.messages("b", "control")) == 1
    assert len(pair.messages("b", "sync")) == 1
    assert pair.messages("a", "sync") == []
    assert pair.state("b")["outbox"] == []


@pytest.mark.parametrize("kind", ["missing", "malformed"])
def test_missing_or_malformed_hint_resets_to_old_idle_sync_cadence(pair, kind):
    controls = 0

    def alter(player, message, response):
        nonlocal controls
        if player == "b" and message["event"] == "control":
            controls += 1
            if controls == 2:
                response = dict(response)
                if kind == "missing":
                    response.pop("pending_delivery", None)
                else:
                    response["pending_delivery"] = "false"
        return response

    pair.response_hook = alter
    pair.run(25)
    assert controls >= 2
    assert pair.messages("b", "sync")
    assert pair.messages("a", "sync") == []
    assert pair.status("b")["failed"] is False


def test_stale_control_response_cannot_preserve_zero_hint_or_grant_execution(pair):
    controls = 0

    def alter(player, message, response):
        nonlocal controls
        if player == "b" and message["event"] == "control":
            controls += 1
            if controls == 2:
                response = dict(response)
                response["session_id"] = "f" * 32
        return response

    pair.response_hook = alter
    for _ in range(20):
        pair.tick()
        if controls == 2 and not pair.status("b")["connected"]:
            break
    else:
        pytest.fail("stale CONTROL did not revoke the client")
    assert pair.clients["b"].globals().held is True
    assert pair.state("b")["outbox"] == []
    assert pair.clients["b"].globals().applied == 0


def test_lost_sync_ack_replays_exact_id_after_local_reopen(pair):
    pair.run(4)
    pair.clients["a"].globals().observe(json.dumps([{"event": "faint", "key": pair.case.keys["a"]}]))
    pair.tick()
    lost = []

    def drop(player, message, response):
        if player == "b" and message["event"] == "sync":
            lost.append((message, response))
            return None
        return response

    pair.response_hook = drop
    for _ in range(20):
        pair.tick()
        if lost:
            break
    assert len(lost) == 1
    message, original = lost[0]
    operation_id = message["operation_id"]
    before = pair.state("b")
    assert before["outbox"][0]["operation_id"] == operation_id
    revision = pair.case.runtime.journal.snapshot().revision
    lua = pair.clients["b"]
    lua.execute("store:close();store=assert(open_store());journal=assert(Journal.open(store,function()return string.rep('e',32)end))")
    assert pair.state("b")["outbox"][0]["operation_id"] == operation_id
    assert pair.case.runtime.process(message, pair.owners["b"]) == original
    assert pair.case.runtime.journal.snapshot().revision == revision
    command = original["commands"][0]
    durable = [{"command_id": command["command_id"], "command_sequence": command["command_sequence"],
                "body": {"cmd": command["cmd"], "body": command["body"]}}]
    lua.globals().durable_json = json.dumps(durable)
    lua.globals().replay_id = operation_id
    lua.execute("assert(journal:accept_response(replay_id,assert(JSON.decode(durable_json))))")
    lua.execute("store:close();store=assert(open_store());journal=assert(Journal.open(store,function()return string.rep('e',32)end))")
    assert pair.state("b")["outbox"] == []
    assert pair.state("b")["inbox"][0]["command_id"] == command["command_id"]
    assert lua.globals().applied == 0


def test_failed_sync_publication_latches_and_reopen_keeps_server_obligation(pair):
    pair.run(4)
    pair.clients["a"].globals().observe(json.dumps([{"event": "faint", "key": pair.case.keys["a"]}]))
    pair.tick()
    pending = pair.case.runtime.journal.pending_ids("b")
    assert pending

    def fail_next_sync(player, message, response):
        if player == "b" and message["event"] == "control" and response["pending_delivery"]:
            pair.clients["b"].globals().mode = "before"
        return response

    pair.response_hook = fail_next_sync
    for _ in range(20):
        pair.tick()
        if pair.clients["b"].globals().mode == "before":
            break
    else:
        pytest.fail("pending-command CONTROL hint was not issued")
    pair.ticks += 1
    pair.case.time = 10 + pair.ticks * 0.05
    lua = pair.clients["b"]
    lua.globals().t = pair.ticks * 0.05
    result = lua.globals().step()
    assert result[0] is False
    assert pair.status("b")["failed"] is True and lua.globals().held is True
    assert pair.messages("b", "sync") == []
    assert pair.case.runtime.journal.pending_ids("b") == pending
    lua.execute("store:close();mode='ok';store=assert(open_store());journal=assert(Journal.open(store,function()return string.rep('e',32)end))")
    assert pair.state("b")["outbox"] == []
