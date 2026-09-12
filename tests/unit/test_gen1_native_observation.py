"""Actual journal checkpoint provenance; modeled cartridge observations."""

import copy
import secrets

import pytest

from server.gen1_frame_journal import returned
from server.gen1_full_save import SYMBOLS
from server.gen1_initial_observation import inventory
from server.gen1_native_observation import COMPONENT, candidate_checkpoints, checkpoints, key
from server.gen1_run_config import create_runtime, open_runtime
from server.protocol import digest
from server.protocol_journal import JournalError
from tests.unit.test_gen1_atomic_frame_settlement import frame, starters, window
from tests.unit.test_gen1_sessions import contract


def candidate(runtime, player):
    state = runtime.state().document()
    initial = state["components"]["gen1-initial-observations"][player]
    observation = copy.deepcopy(
        state["components"]["gen1-inventory-observations"][player]["observation"]
    )
    observation["frame"] += 1
    source = observation["source"]
    variant = source["variant"]
    members = inventory(source, initial["metadata"]["save_identity"])["members"]
    party = [member["blob_hex"] for member in members if member["location"] == "party"]
    raw = bytes.fromhex(source["fields"]["party"])
    symbols = SYMBOLS["pokeyellow" if variant == "yellow" else "pokered"]
    main = bytes.fromhex(source["fields"]["main"])
    save = initial["metadata"]["save_identity"]
    checkpoint = {
        "schema": "rby-trade-checkpoint-v1",
        "final_sha1": observation["final_sha1"],
        "party": {
            "schema": "gen1-party-readback-v1",
            "variant": variant,
            "save_id": save["ot_id"],
            "save_name": save["trainer_name"],
            "party_count": len(party),
            "party": party,
            "species_list": list(raw[1 : 2 + len(party)]),
            "battle_flag": 0,
            "active_slot": None,
            "battle_hp": None,
        },
        "party_storage_hex": source["fields"]["party"],
        "name_hex": source["fields"]["name"],
        "map": main[symbols["wCurMap"] - symbols["wMainDataStart"]],
        "current_box": main[symbols["wCurrentBoxNum"] - symbols["wMainDataStart"]],
        "active_box_hex": source["fields"]["box"],
        "cart_hex": source["cart_hex"],
    }
    window(runtime, player)
    message = frame(runtime, player, observation, None)
    message["bundle"]["native_checkpoint"] = {
        "schema": "rby-native-observation-v1",
        "party": checkpoint["party"],
    }
    message["receipt"]["observations_digest"] = digest(message["bundle"])
    return message


@pytest.mark.parametrize("variants", [("yellow", "yellow"), ("red", "blue"), ("blue", "yellow")])
def test_paired_checkpoint_is_atomic_detached_and_requires_current_closed_frames(
    tmp_path, variants
):
    runtime = create_runtime(tmp_path, contract(*variants))
    try:
        starters(runtime)
        with pytest.raises(JournalError, match="both native"):
            checkpoints(runtime)
        for player in ("a", "b"):
            message = candidate(runtime, player)
            operation = secrets.token_hex(16)
            result = returned(runtime, player, operation, message, settle_observations=True)
            entry = runtime.state().document()["components"][COMPONENT][player]
            assert result["native_checkpoint_digest"] == digest(entry)
            assert (
                runtime.journal.event_snapshot(player, operation).revision
                == runtime.journal.record(COMPONENT, key(player)).revision
            )
        checked = checkpoints(runtime)
        checked["a"]["map"] ^= 1
        assert checkpoints(runtime)["a"]["map"] != checked["a"]["map"]
        # A new grant invalidates using the old held checkpoint immediately.
        window(runtime, "a")
        with pytest.raises(JournalError, match="unclosed"):
            checkpoints(runtime)
        assert set(candidate_checkpoints(runtime, "b")) == {"a", "b"}
        with pytest.raises(JournalError, match="unclosed"):
            candidate_checkpoints(runtime, "a")
    finally:
        runtime.close()
    runtime = open_runtime(tmp_path)
    try:
        assert set(runtime.state().document()["components"][COMPONENT]) == {"a", "b"}
        with pytest.raises(JournalError, match="unclosed"):
            checkpoints(runtime)
    finally:
        runtime.close()


@pytest.mark.parametrize("mutation", ["identity", "owner", "battle", "party", "missing_inventory"])
def test_bad_native_checkpoint_rolls_back_whole_frame(tmp_path, mutation):
    runtime = create_runtime(tmp_path, contract("yellow", "yellow"))
    try:
        starters(runtime)
        message = candidate(runtime, "a")
        checkpoint = message["bundle"]["native_checkpoint"]
        if mutation == "identity":
            checkpoint["party"]["save_id"] = "FFFF"
        elif mutation == "owner":
            message["bundle"]["inventory"]["host"]["process_id"] += 1
        elif mutation == "battle":
            checkpoint["party"].update(battle_flag=1, active_slot=0, battle_hp=10)
        elif mutation == "party":
            checkpoint["party"]["party"][0] = "00" * 66
        else:
            message["bundle"]["inventory"] = None
        message["receipt"]["observations_digest"] = digest(message["bundle"])
        snapshot = runtime.journal.snapshot()
        with pytest.raises(JournalError):
            returned(runtime, "a", secrets.token_hex(16), message, settle_observations=True)
        assert runtime.journal.snapshot() == snapshot
        assert runtime.journal.record(COMPONENT, key("a")) is None
    finally:
        runtime.close()
