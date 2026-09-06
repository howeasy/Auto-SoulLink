"""Legacy tokenless/watchdog-driven peer trades cannot mutate a Gen 1 run."""
import copy

import pytest

from server.adapters import get_adapter
from server.state import SoulLinkState


@pytest.mark.parametrize("variant", ["Red", "Blue", "Yellow", "red_ap", "blue_ap"])
@pytest.mark.parametrize("event", ["trade_request", "mon_chosen", "menu_result", "trade_done"])
def test_legacy_messages_cannot_start_progress_or_finish_gen1_trades(tmp_path, variant, event):
    state = SoulLinkState(data_dir=str(tmp_path), adapter=get_adapter("gen1_rby", rom_type=variant))
    record = {"phase": "applying", "age": 99999, "token": "old", "done": {"a": True, "b": False}}
    state.pending_trade = copy.deepcopy(record)
    replies = state.handle_event("b", {"event": event, "slot": 0, "choice": 0, "new_key": "ABCD:1234:01"})
    assert replies[0]["ack"] == "NACK"
    assert state.pending_trade == record and state.links == []
    assert state.queued_commands == {"a": [], "b": []}
    assert not list(tmp_path.glob("*.json"))


def test_gen1_watchdog_never_fills_in_a_missing_physical_result(tmp_path):
    state = SoulLinkState(data_dir=str(tmp_path), adapter=get_adapter("gen1_rby", rom_type="Red"))
    state.pending_trade = {"phase": "applying", "age": state.TRADE_WATCHDOG_EVENTS + 1}
    record = copy.deepcopy(state.pending_trade)
    state._commit_trade = lambda _: pytest.fail("timeout invented a successful physical trade")
    for _ in range(20):
        state._tick_pending_trade()
    assert state.pending_trade == record


def test_other_generations_keep_their_existing_trade_dispatch(tmp_path):
    state = SoulLinkState(data_dir=str(tmp_path), adapter=get_adapter("gen3_frlge"))
    replies = state.handle_event("a", {"event": "trade_request"})
    assert state.pending_trade["phase"] == "menu"
    assert replies[0]["cmd"] == "show_choices"


def test_command_nack_is_diagnostic_and_never_advances_or_drains_rule_state(tmp_path):
    from server.server import SLinkServer

    server = SLinkServer.__new__(SLinkServer)
    server.state = SoulLinkState(data_dir=str(tmp_path), adapter=get_adapter("gen1_rby", rom_type="Red"))
    server.battle_state = {"a": {"in_battle": False}}
    server.is_admitted = lambda _: True
    logged = []
    server._log_event = lambda *args: logged.append(args)
    server.state.queued_commands["a"] = [{"cmd": "box_mon", "key": "ABCD:1234:01"}]
    server.state.handle_event = lambda *_: pytest.fail("diagnostic refusal reached semantic processing")
    replies = server._dispatch("a", {"event": "command_nack", "command": "force_faint", "reason": "invalid party count"})
    assert replies == [{"cmd": "noop"}]
    assert server.state.queued_commands["a"] == [{"cmd": "box_mon", "key": "ABCD:1234:01"}]
    assert logged and logged[0][1] == "command_nack"
