"""Actual journal checkpoint provenance; modeled cartridge observations.

The native checkpoint reaches the server inside a native frame handoff (the one compound event
left). The loan itself is driven with the native accounting helpers.
"""

import copy
import secrets

import pytest

from server.gen1_initial_observation import inventory
from server.gen1_native_observation import (
    COMPONENT,
    candidate_checkpoints,
    checkpoints,
    key,
    stage,
    verify_journal,
)
from server.gen1_run_config import create_runtime, open_runtime
from server.protocol_journal import JournalError
from tests.unit.observation_fixture import ledger, starters
from tests.unit.test_gen1_native_frame_accounting import compose, grant, handoff, queue, returned, terminal
from tests.unit.test_gen1_sessions import contract


def handoff_message(value, player):
    """A native handoff carrying the latest checkpoint one frame on, as the native client returns it."""
    state = value.state().document()
    initial = state["components"]["gen1-initial-observations"][player]
    observation = copy.deepcopy(state["components"]["gen1-inventory-observations"][player]["observation"])
    observation["frame"] += 1
    source = observation["source"]
    raw = bytes.fromhex(source["fields"]["party"])
    members = inventory(source, initial["metadata"]["save_identity"])["members"]
    party = [member["blob_hex"] for member in members if member["location"] == "party"]
    save = initial["metadata"]["save_identity"]
    readback = {
        "schema": "gen1-party-readback-v1",
        "variant": source["variant"],
        "save_id": save["ot_id"],
        "save_name": save["trainer_name"],
        "party_count": len(party),
        "party": party,
        "species_list": list(raw[1 : 2 + len(party)]),
        "battle_flag": 0,
        "active_slot": None,
        "battle_hp": None,
    }
    return {"event": "native_frame_handoff", "payload": {
        "schema": "rby-native-frame-return-v1", "inventory": observation,
        "host": {**observation["host"], "frame": observation["frame"]},
        "native_checkpoint": {"party": readback}}}


@pytest.mark.parametrize("mutation", [None, "identity", "owner", "battle", "party", "missing_inventory"])
def test_handoff_checkpoint_stages_detached_and_refuses_bad_evidence(tmp_path, mutation):
    value = create_runtime(tmp_path, contract("yellow", "yellow"))
    try:
        starters(value)
        message = handoff_message(value, "a")
        party = message["payload"]["native_checkpoint"]["party"]
        if mutation == "identity":
            party["save_id"] = "FFFF"
        elif mutation == "owner":
            message["payload"]["inventory"]["host"]["process_id"] += 1
        elif mutation == "battle":
            party.update(battle_flag=1, active_slot=0, battle_hp=10)
        elif mutation == "party":
            party["party"][0] = "00" * 66
        elif mutation == "missing_inventory":
            message["payload"]["inventory"] = None
        document = value.state().document()
        before = value.journal.snapshot()
        if mutation is None:
            staged = stage(document, "a", secrets.token_hex(16), message)
            assert staged["entry"]["frame"] == message["payload"]["inventory"]["frame"]
            assert staged["entry"]["party"] == party and staged["record"]["key"] == key("a")
            assert document["components"][COMPONENT]["a"] == staged["entry"]
        else:
            with pytest.raises(JournalError):
                stage(document, "a", secrets.token_hex(16), message)
            assert COMPONENT not in document["components"]
        assert value.journal.snapshot() == before and value.journal.record(COMPONENT, key("a")) is None
    finally:
        value.close()


def test_paired_checkpoints_follow_both_handed_back_loans_and_reopen(tmp_path):
    value = create_runtime(tmp_path, contract("yellow", "yellow"))
    try:
        starters(value)
        ledger(value)
        compose(value, tmp_path)
        with pytest.raises(JournalError, match="both native"):
            checkpoints(value)
        for player in ("a", "b"):
            command = queue(value, player)
            grant(value, command, 110, player)
            message = terminal(value, command, 120, player)
            returned(value, player, secrets.token_hex(16), message)
            with pytest.raises(JournalError, match="both native"):
                checkpoints(value)
            handoff(value, player, secrets.token_hex(16), {"event": "native_frame_handoff", "payload": message["payload"]})
            entry = value.state().document()["components"][COMPONENT][player]
            assert entry["frame"] == 120 and value.journal.record(COMPONENT, key(player)).value == entry
        checked = checkpoints(value)
        checked["a"]["map"] ^= 1
        assert checkpoints(value)["a"]["map"] != checked["a"]["map"]  # detached copies
        assert set(candidate_checkpoints(value, "b")) == {"a", "b"}
        verify_journal(value.journal, value.state())
        saved = value.state().document()["components"][COMPONENT]
    finally:
        value.close()
    reopened = open_runtime(tmp_path)
    try:
        assert reopened.state().document()["components"][COMPONENT] == saved
        assert set(checkpoints(reopened)) == {"a", "b"}
    finally:
        reopened.close()
