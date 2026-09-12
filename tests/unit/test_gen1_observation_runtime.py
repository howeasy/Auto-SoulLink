"""Free-run observation batches (P10) settle through the modules that own each part.

The runtime, journal, identity registry and staged rules are real; signals, receipts and
checkpoints are the engine-shaped fixtures the standalone event tests already use, so every
assertion here is about composition and ordering, not about decoding.
"""
import copy
import secrets

import pytest

from server import battle_force_authority as auth, instruction_authority as generic
from server.gen1_acquisition_runtime import (
    COMPONENT as ACQUISITIONS,
    ORDINALS,
    verify_journal as verify_acquisitions,
    verify_state as verify_acquisition_state,
)
from server.gen1_faint_runtime import COMPONENT as FAINTS
from server.gen1_inventory_observation import COMPONENT as INVENTORY, record_key as inventory_key
from server.gen1_launcher import FREE_FILES, configuration
from server.gen1_observation_runtime import COMPONENT, EVENT, SCHEMA, key, record, verify_journal
from server.gen1_run_config import create_runtime, open_runtime, read_configuration
from server.gen1_starter_settlement import COMPONENT as STARTERS
from server.protocol import ProtocolError, digest
from server.protocol_journal import JournalError
from server.state import LinkStatus
from tests.unit.test_gen1_acquisition_runtime import grant
from tests.unit.test_gen1_engine_signal_runtime import deliver as deliver_signals
from tests.unit.test_gen1_faint_runtime import ack, acknowledgement, paired, signal_batch
from tests.unit.test_gen1_hud_feedback import acknowledge_hud
from tests.unit.test_gen1_initial_observation import admit, observation, send
from tests.unit.test_gen1_inventory_observation import deliver as deliver_inventory
from tests.unit.test_gen1_sessions import contract
from tests.unit.test_gen1_starter_settlement import enroll, source_and_checkpoint

INSTANCE = {"a": "1" * 32, "b": "2" * 32}


def batch(runtime, player, sequence, *, frame, signals=None, acquisitions=(), inventory=None):
    return {"schema": SCHEMA, "event": EVENT, "frame": frame, "sequence": sequence,
            "context": {"context_generation": player * 32, "physical_instance": INSTANCE[player],
                        "save_identity": {"ot_id": "0000", "trainer_name": "SAME"}},
            "rom": runtime.contract["players"][player]["final_rom_sha1"],
            "signals": signals, "acquisitions": list(acquisitions), "inventory": inventory}


def deliver(runtime, player, owner, request, operation=None):
    session = runtime.gate.sessions[player]
    return runtime.process({"protocol": runtime.protocol, "player": player, "session_id": session.session_id,
        "admission_epoch": runtime.gate.epoch, "seq": session.last_seq + 1,
        "operation_id": operation or secrets.token_hex(16), **request}, owner)


def publish(runtime, player, owner, request):
    """Deliver one batch and return its committed result."""
    operation = secrets.token_hex(16)
    deliver(runtime, player, owner, request, operation)
    return operation, runtime.journal.event_snapshot(player, operation).result


def test_transport_binds_inventory_outcome_to_exact_observation_and_replay(tmp_path):
    runtime = create_runtime(tmp_path, contract("yellow", "yellow"), free_service=True)
    try:
        owner, initial, _ = enrolled(runtime, "a")
        request = batch(runtime, "a", 1, frame=130, inventory=checkpoint(initial, 130))
        operation = secrets.token_hex(16)
        session = runtime.gate.sessions["a"]
        packet = {"protocol": runtime.protocol, "player": "a", "session_id": session.session_id,
                  "admission_epoch": runtime.gate.epoch, "seq": session.last_seq + 1,
                  "operation_id": operation, **request}
        response = runtime.process(packet, owner)
        assert response["observation_result"] == {"schema": "rby-observation-result-v1",
            "operation_id": operation, "sequence": 1, "frame": 130, "inventory_status": "recorded"}
        assert runtime.process(packet, owner) == response
        no_inventory = batch(runtime, "a", 2, frame=160)
        answer = deliver(runtime, "a", owner, no_inventory)
        assert answer["observation_result"]["inventory_status"] == "absent"
    finally:
        runtime.close()


def enrolled(runtime, player, *, occupied=False):
    owner = admit(runtime, player)
    initial = observation(runtime, player, occupied=occupied)
    first = secrets.token_hex(16)
    send(runtime, player, owner, initial, first)
    return owner, initial, first


def checkpoint(initial, frame, party_hex=None):
    point = copy.deepcopy(initial)
    point["frame"] = frame
    if party_hex is not None:
        point["source"]["fields"]["party"] = party_hex
    return point


def progress(runtime, player):
    return runtime.state().document()["components"].get(COMPONENT, {}).get(player)


def acquisitions(runtime, player):
    return runtime.state().document()["components"].get(ACQUISITIONS, {}).get(player)


def test_sequence_must_be_contiguous_and_a_refused_batch_commits_nothing(tmp_path):
    runtime = create_runtime(tmp_path, contract("yellow", "yellow"), free_service=True)
    try:
        owner, initial, _ = enrolled(runtime, "a")
        operation = secrets.token_hex(16)
        deliver(runtime, "a", owner, batch(runtime, "a", 1, frame=130, inventory=checkpoint(initial, 130)), operation)
        assert progress(runtime, "a") == {"sequence": 1, "operation_id": operation, "frame": 130}
        assert runtime.journal.record(COMPONENT, key("a")).value == progress(runtime, "a")
        before = runtime.journal.snapshot()
        with pytest.raises(JournalError, match="sequence skipped or repeated"):
            record(runtime, "a", secrets.token_hex(16), batch(runtime, "a", 3, frame=160))
        with pytest.raises(JournalError, match="sequence skipped or repeated"):
            record(runtime, "a", secrets.token_hex(16), batch(runtime, "a", 1, frame=160))
        with pytest.raises(JournalError, match="frame moved backwards"):
            record(runtime, "a", secrets.token_hex(16), batch(runtime, "a", 2, frame=130))
        assert runtime.journal.snapshot() == before
        deliver(runtime, "a", owner, batch(runtime, "a", 2, frame=160))
        assert progress(runtime, "a")["sequence"] == 2 and progress(runtime, "b") is None
        verify_journal(runtime.journal, runtime.state())
    finally:
        runtime.close()


def test_replay_returns_the_committed_result_without_a_second_commit(tmp_path):
    runtime = create_runtime(tmp_path, contract("red", "blue"), free_service=True)
    try:
        owner, initial, _ = enrolled(runtime, "a", occupied=True)
        operation = secrets.token_hex(16)
        request = batch(runtime, "a", 1, frame=130, inventory=checkpoint(initial, 130))
        first = deliver(runtime, "a", owner, request, operation)
        snapshot = runtime.journal.snapshot()
        again = deliver(runtime, "a", owner, request, operation)  # a fresh transport seq, the same semantic event
        assert {k: v for k, v in again.items() if k != "seq"} == {k: v for k, v in first.items() if k != "seq"}
        assert runtime.journal.snapshot() == snapshot
        entry = runtime.journal.record(INVENTORY, inventory_key("a")).value
        assert record(runtime, "a", operation, request) == {
            "ack": "ACK", "ordinary_execution": False, "inventory_transition_digest": digest(entry),
            "observation_digest": digest(progress(runtime, "a"))}
        with pytest.raises(JournalError, match="different semantic content"):
            record(runtime, "a", operation, {**request, "frame": 131})
        assert runtime.journal.snapshot() == snapshot
    finally:
        runtime.close()


@pytest.mark.parametrize("cause", ["battle_faint", "poison_faint"])
def test_faint_signal_settles_exactly_as_the_standalone_engine_event(tmp_path, cause):
    def settle(directory, publish):
        runtime = create_runtime(directory, contract("red", "blue"), free_service=True)
        try:
            owners = paired(runtime)
            value = signal_batch(runtime, "a", cause=cause)
            publish(runtime, owners["a"], value)
            document = runtime.state().document()
            deaths = document["components"][FAINTS]["deaths"]
            assert len(deaths) == 1
            death = next(iter(deaths.values()))
            engine = death.pop("engine_record")
            assert engine["payload"] == value and [row["kind"] for row in engine["transactions"]] == ["pokeballs_obtained", "faint"]
            pending = [runtime.journal.command("b", row["command_id"])["body"] for row in runtime.journal.pending("b")]
            links = [(link["status"], link["area_id"], link["a"]["key"], link["b"]["key"]) for link in document["rules"]["core"]["links"]]
            party = document["rules"]["runtime"]["party_keys"]
            fixed = {name: death[name] for name in death if name not in ("at", "link_id", "members")}
            return fixed, links, party, [(body["cmd"], body.get("key"), body.get("player")) for body in pending]
        finally:
            runtime.close()

    standalone = settle(tmp_path / "standalone", lambda runtime, owner, value: deliver_signals(runtime, "a", owner, value))
    observed = settle(tmp_path / "observed",
                      lambda runtime, owner, value: deliver(runtime, "a", owner, batch(runtime, "a", 1, frame=121, signals=value)))
    assert observed == standalone
    death, links, party, commands = observed
    assert death["phase"] == "pending_faint" and death["peer"] == "b"
    assert links[0][0] == LinkStatus.DEAD.value and not party["a"] and not party["b"]
    assert [command[0] for command in commands] == ["force_faint", "hud_notice", "hud_notice"]


def test_heartbeat_inventory_records_the_checkpoint_and_chains_from_the_previous_batch(tmp_path):
    runtime = create_runtime(tmp_path, contract("yellow", "red"), free_service=True)
    try:
        owner, initial, first = enrolled(runtime, "a", occupied=True)
        point = checkpoint(initial, 130)
        party = bytearray.fromhex(point["source"]["fields"]["party"])
        party[9:11] = b"\0\0"
        point["source"]["fields"]["party"] = party.hex().upper()
        operation, result = publish(runtime, "a", owner, batch(runtime, "a", 1, frame=130, inventory=point))
        entry = runtime.state().document()["components"][INVENTORY]["a"]
        assert entry["sequence"] == 1 and entry["previous_operation_id"] == first and entry["observation"] == point
        assert len(entry["transition"]["party_hp_zero"]) == 1
        assert runtime.journal.record(INVENTORY, inventory_key("a")).value == entry
        assert result["inventory_transition_digest"] == digest(entry) and "inventory_deferred" not in result
        deliver(runtime, "a", owner, batch(runtime, "a", 2, frame=160, inventory=checkpoint(point, 160)))
        entry = runtime.state().document()["components"][INVENTORY]["a"]
        assert entry["sequence"] == 2 and entry["previous_operation_id"] == operation  # chained through the batch
        assert entry["transition"]["party_hp_zero"] == []
        assert len(runtime.journal.record_history(INVENTORY, inventory_key("a"))) == 2
        state = runtime.state()
        verify_journal(runtime.journal, state)
        saved = state.document()["components"]
    finally:
        runtime.close()
    reopened = open_runtime(tmp_path)
    try:
        components = reopened.state().document()["components"]
        assert components[INVENTORY] == saved[INVENTORY] and components[COMPONENT] == saved[COMPONENT]
    finally:
        reopened.close()


def test_acquisition_receipt_settles_pending_or_in_the_same_batch_as_its_checkpoint(tmp_path):
    runtime = create_runtime(tmp_path, contract("yellow", "yellow"), free_service=True)
    try:
        owners, initials, receipts = {}, {}, {}
        for player in ("a", "b"):
            owners[player], initials[player], _ = enrolled(runtime, player)
            receipts[player] = grant(runtime, player, "grant:eevee:0")

        def stable(player, frame):
            return checkpoint(initials[player], frame, receipts[player]["receipt"]["return"]["point"]["party_hex"])

        # a: the receipt arrives first and stays pending until a checkpoint at or after its return frame.
        deliver(runtime, "a", owners["a"], batch(runtime, "a", 1, frame=150, acquisitions=[receipts["a"]]))
        row = acquisitions(runtime, "a")
        assert len(row["pending"]) == 1 and row["settled"] == [] and ORDINALS not in runtime.state().document()["components"]
        deliver(runtime, "a", owners["a"], batch(runtime, "a", 2, frame=200, inventory=stable("a", 200)))
        row = acquisitions(runtime, "a")
        assert row["pending"] == [] and len(row["settled"]) == 1 and row["settled"][0]["link_id"] is None
        acknowledge_hud(runtime)
        # b: receipt and heartbeat checkpoint in ONE batch; inventory is staged first, so it settles at once.
        # (A checkpoint committed before its receipt cannot prove it: the verifier orders them by revision.)
        _, result = publish(runtime, "b", owners["b"], batch(runtime, "b", 1, frame=200, acquisitions=[receipts["b"]],
                                                              inventory=stable("b", 200)))
        assert {"inventory_transition_digest", "acquisition_digest", "observation_digest"} <= set(result)
        row = acquisitions(runtime, "b")
        assert row["pending"] == [] and len(row["settled"]) == 1 and row["settled"][0]["link_id"] is not None
        for player in ("a", "b"):
            settled = acquisitions(runtime, player)["settled"][0]
            assert settled["pairing_key"] == "grant:eevee:0#1" and settled["area"] == "celadon_mansion_roof"
            assert settled["violation"] is None and settled["inventory_operation"] == progress(runtime, player)["operation_id"]
        state = runtime.state()
        document = state.document()
        assert document["components"][ORDINALS] == {"grant:eevee:0": {"a": 1, "b": 1}}
        links = document["rules"]["core"]["links"]
        assert len(links) == 1 and links[0]["status"] == LinkStatus.ALIVE.value and links[0]["area_id"] == "celadon_mansion_roof"
        verify_acquisition_state(state)
        verify_acquisitions(runtime.journal, state)
        verify_journal(runtime.journal, state)
        saved = document["components"]
    finally:
        runtime.close()
    reopened = open_runtime(tmp_path)
    try:
        stage = reopened.state()
        components = stage.document()["components"]
        assert components[ACQUISITIONS] == saved[ACQUISITIONS] and components[COMPONENT] == saved[COMPONENT]
        verify_acquisitions(reopened.journal, stage)
    finally:
        reopened.close()


def test_starter_source_and_checkpoint_settle_through_observation_batches(tmp_path):
    runtime = create_runtime(tmp_path, contract("red", "yellow"), free_service=True)
    try:
        instant = runtime.clock()
        runtime.clock = lambda: instant
        owners, initials, operations = enroll(runtime)
        for player in ("a", "b"):
            source, stable = source_and_checkpoint(runtime, player, initials[player], operations[player])
            deliver(runtime, player, owners[player], batch(runtime, player, 1, frame=105, signals=source))
            assert player in runtime.state().document()["components"][STARTERS]["sources"]
            deliver(runtime, player, owners[player], batch(runtime, player, 2, frame=110, inventory=stable["observation"]))
            acknowledge_hud(runtime)
        state = runtime.state()
        assert set(state.document()["components"][STARTERS]["settled"]) == {"a", "b"}
        assert len(state.rules.links) == 1 and state.rules.links[0].status == LinkStatus.ALIVE
        assert state.barrier.ticket() is None
    finally:
        runtime.close()


def test_heartbeat_inventory_is_deferred_while_any_physical_obligation_is_open(tmp_path):
    runtime = create_runtime(tmp_path, contract("yellow", "yellow"), free_service=True)
    try:
        instant = runtime.clock()
        runtime.clock = lambda: instant
        owners, initials, operations = enroll(runtime)
        points = {}
        for player in ("a", "b"):
            source, stable = source_and_checkpoint(runtime, player, initials[player], operations[player])
            deliver_signals(runtime, player, owners[player], source)
            deliver_inventory(runtime, player, owners[player], stable)
            points[player] = stable["observation"]
            acknowledge_hud(runtime)
        deliver(runtime, "a", owners["a"], batch(runtime, "a", 1, frame=121, signals=signal_batch(runtime, "a")))
        assert [c["cmd"] for c in runtime.journal.pending("b")] == ["force_faint", "hud_notice", "hud_notice"]
        assert [c["cmd"] for c in runtime.journal.pending("a")] == ["hud_notice", "hud_notice"]
        sequences = {p: runtime.state().document()["components"][INVENTORY][p]["sequence"] for p in ("a", "b")}
        for player, frame in (("b", 125), ("a", 126)):
            request = batch(runtime, player, 1 if player == "b" else 2, frame=frame,
                            inventory=checkpoint(points[player], frame))
            response = deliver(runtime, player, owners[player], request)
            assert response["observation_result"]["inventory_status"] == "deferred"
            result = runtime.journal.event_snapshot(player, response["operation_id"]).result
            assert result["inventory_deferred"] is True and "inventory_transition_digest" not in result
        assert {p: runtime.state().document()["components"][INVENTORY][p]["sequence"] for p in ("a", "b")} == sequences
        command = runtime.journal.command("b", runtime.journal.pending_ids("b")[0])
        ack(runtime, "b", owners["b"], acknowledgement(runtime, "b", command))
        # The physical faint closed, but its memorial obligations opened: the checkpoint stays deferred
        # until every obligation has its receipt, exactly as the standalone stream would refuse it.
        pending = [runtime.journal.command("b", identifier)["body"] for identifier in runtime.journal.pending_ids("b")]
        assert pending and [body["cmd"] for body in pending] == ["hud_notice", "hud_notice", "memorial_observe"]
        fainted = checkpoint(points["b"], 140)
        party = bytearray.fromhex(fainted["source"]["fields"]["party"])
        party[9:11] = b"\0\0"
        fainted["source"]["fields"]["party"] = party.hex().upper()
        _, result = publish(runtime, "b", owners["b"], batch(runtime, "b", 2, frame=140, inventory=fainted))
        assert result["inventory_deferred"] is True
        assert runtime.state().document()["components"][INVENTORY]["b"]["sequence"] == sequences["b"]
        verify_journal(runtime.journal, runtime.state())
    finally:
        runtime.close()


@pytest.mark.parametrize("fault", ["rom", "generation", "instance", "identity", "kind", "malformed", "shape", "enrollment"])
def test_hostile_batches_commit_nothing(tmp_path, fault):
    runtime = create_runtime(tmp_path, contract("blue", "yellow"), free_service=True)
    try:
        owner, initial, _ = enrolled(runtime, "a")
        request = batch(runtime, "a", 1, frame=130, inventory=checkpoint(initial, 130))
        player = "a"
        if fault == "rom":
            request["rom"] = "f" * 40
        elif fault == "generation":
            request["context"]["context_generation"] = "f" * 32
        elif fault == "instance":
            request["context"]["physical_instance"] = "f" * 32
        elif fault == "identity":
            request["context"]["save_identity"]["ot_id"] = "0001"
        elif fault == "kind":  # not in the source catalog: fails closed before any decoder runs
            request["acquisitions"] = [{"kind": "trade", "receipt": {}}]
        elif fault == "malformed":  # a catalogued kind whose receipt its decoder refuses
            request["acquisitions"] = [{"kind": "wild_begin", "receipt": {}}]
        elif fault == "shape":
            del request["inventory"]
        else:
            admit(runtime, "b")
            player = "b"
            request = batch(runtime, "b", 1, frame=130)
        before = runtime.journal.snapshot()
        with pytest.raises(JournalError):
            record(runtime, player, secrets.token_hex(16), request)
        assert runtime.journal.snapshot() == before and progress(runtime, "a") is None
    finally:
        runtime.close()


def test_free_service_selection_persists_routes_and_ships_the_loop(tmp_path):
    runtime = create_runtime(tmp_path / "free", contract("red", "red"), free_service=True)
    try:
        assert runtime.free_service and read_configuration(tmp_path / "free")["free_service"] is True
        config = configuration(runtime, "a")
        files = {row["path"] for row in config["files"]}
        assert config["mode"] == "free_service" and set(FREE_FILES) <= files
        assert "lua/gen1_observation_loop.lua" in files
    finally:
        runtime.close()
    reopened = open_runtime(tmp_path / "free")
    try:
        assert reopened.free_service is True
        assert configuration(reopened, "b")["mode"] == "free_service"
    finally:
        reopened.close()
    held = create_runtime(tmp_path / "held", contract("red", "red"))
    try:
        assert held.free_service is False and "free_service" not in read_configuration(tmp_path / "held")
        assert configuration(held, "a")["mode"] == "held_service" and "lua/gen1_observation_loop.lua" not in {
            row["path"] for row in configuration(held, "a")["files"]}
        owner, initial, _ = enrolled(held, "a")
        before = held.journal.snapshot()
        with pytest.raises(ProtocolError, match="not selected"):
            deliver(held, "a", owner, batch(held, "a", 1, frame=130, inventory=checkpoint(initial, 130)))
        assert held.journal.snapshot() == before
    finally:
        held.close()
    # A run prepared for the retired frame-credit mode cannot be served any more.
    from server.gen1_run_config import FILENAME
    from server.json_files import atomic_write_json

    stale = read_configuration(tmp_path / "held")
    stale["ordinary_frames"] = True
    atomic_write_json(tmp_path / "held" / FILENAME, stale)
    with pytest.raises(JournalError, match="unsupported prepared"):
        open_runtime(tmp_path / "held")


# ---------------------------------------------------------------- polled battle state: trainer engagement (task 1) and the in-battle window (task 2)


def armed_batch(runtime, player, sequence, *, frame, battle=1, trainer=None, **rest):
    """A batch as the loop publishes it since the battle probe: the wIsInBattle byte and the debounced trainer row."""
    request = batch(runtime, player, sequence, frame=frame, **rest)
    request["battle"] = battle
    request["trainer"] = trainer
    return request


def window_command(runtime, player):
    """The one outstanding battle_instruction command of ``player``, or None."""
    for identifier in runtime.journal.pending_ids(player):
        command = runtime.journal.command(player, identifier)
        if command["body"].get("cmd") == auth.COMMAND:
            return command
    return None


def unreached_row(a, frame):
    return {"schema": generic.EVIDENCE, "challenge": a["challenge"], "owner_id": a["owner_id"], "frame": frame, "step": a["step"] + (frame - a["frame"]),
            "held": False, "site": None, "pc": None, "bank": None, "sp": None, "stack_hex": None, "hook_frame": None, "state": None, "writes": [], "refusal": None}


def reached_row(a, frame, site="player_action", **over):
    """The executor's row for the peer's linked mon (party slot 0 of the paired fixture), active and healthy unless ``over`` says otherwise."""
    member = a["member"]
    variant = member["variant"]
    anchors = auth.ANCHORS[variant]
    st = {"is_in_battle": 1, "battle_type": 0, "link_state": 0, "player_mon_number": 0, "status3": 0, "battle_species": member["species"],
          "battle_dvs_hex": member["dvs_hex"], "party_species": member["species"], "party_dvs_hex": member["dvs_hex"],
          "party_ot_id_hex": member["ot_id_hex"], "party_hp_hex": "0014", "party_status": 0, "hp_hex": "0014", "enemy_hp_hex": "0012",
          "action_result": 0, "selected_move": 0x21, "moves_hex": "21270000", "pp_hex": "231e0000"}
    st.update(over)
    addr = a["addresses"]
    decision = auth.decide(st, member, variant, site)
    before = {addr["wBattleMonHP"]: int(st["hp_hex"][:2], 16), addr["wBattleMonHP"] + 1: int(st["hp_hex"][2:], 16),
              addr["wPlayerSelectedMove"]: st["selected_move"], addr["wPartyMon1HP"]: int(st["party_hp_hex"][:2], 16),
              addr["wPartyMon1HP"] + 1: int(st["party_hp_hex"][2:], 16), addr["wPartyMon1Status"]: st["party_status"]}
    row = unreached_row(a, frame)
    row.update(site=site, pc=anchors[site]["pc"], bank=anchors["bank"], sp=0xDFF0, hook_frame=frame, state=st,
               stack_hex=("64430000" if variant != "yellow" else "7a430000") if site == "player_action" else "12345678",
               writes=[{"address": w["address"], "before_hex": f"{before[w['address']]:02x}", "after_hex": f"{w['value']:02x}"} for w in decision["writes"]],
               refusal=decision["refusal"])
    return row


def window_ack(runtime, player, owner, command, rows, *, frame, battle=1):
    """Close one battle_instruction command with its window receipt; returns (operation, message, committed result)."""
    message = {"event": "command_ack", "command_id": command["command_id"], "command_sequence": command["command_sequence"], "outcome": "ACK",
               "receipt": {"schema": auth.RECEIPT, "challenge": command["body"]["authority"]["challenge"], "frame": frame, "battle": battle, "rows": rows}}
    operation = secrets.token_hex(16)
    ack(runtime, player, owner, message, operation)
    return operation, message, runtime.journal.event_snapshot(player, operation).result


def dead_pair(runtime):
    """Both players enrolled with starters; a faints in battle; b holds the pending force_faint."""
    owners = paired(runtime)
    deliver_signals(runtime, "a", owners["a"], signal_batch(runtime, "a"))
    death_id = next(iter(runtime.state().document()["components"][FAINTS]["deaths"]))
    return owners, death_id


def death(runtime, death_id):
    return runtime.state().document()["components"][FAINTS]["deaths"][death_id]


def test_trainer_engagement_reaches_the_engine_and_queues_the_rival_team_swap(tmp_path):
    runtime = create_runtime(tmp_path / "on", contract("red", "blue"), free_service=True, rule_options={"rival_team_swap": True})
    try:
        owners = paired(runtime)
        blobs = runtime.state().rules.partner_blobs["b"]
        _, result = publish(runtime, "a", owners["a"], armed_batch(runtime, "a", 1, frame=121, battle=2, trainer={"trainer_id": 201, "frame": 118}))
        assert result["trainer_battle"] == {"trainer_id": 201, "rival_team": 0} and not runtime.journal.pending_ids("a")  # not a rival class
        request = armed_batch(runtime, "a", 2, frame=150, battle=2, trainer={"trainer_id": 225, "frame": 147})
        operation, result = publish(runtime, "a", owners["a"], request)
        assert result["trainer_battle"] == {"trainer_id": 225, "rival_team": 1}
        [command] = [runtime.journal.command("a", i) for i in runtime.journal.pending_ids("a")]
        assert command["body"] == {"cmd": "replace_rival_team", "trainer_id": 225, "source_frame": 147,
                                   "n": 1, "blobs_hex": [b["blob"].hex() for b in blobs], "source": "auto"}
        assert record(runtime, "a", operation, request) == result, "replay returns the committed result"
        verify_journal(runtime.journal, runtime.state())
    finally:
        runtime.close()
    runtime = create_runtime(tmp_path / "off", contract("red", "blue"), free_service=True)
    try:
        owners = paired(runtime)
        _, result = publish(runtime, "a", owners["a"], armed_batch(runtime, "a", 1, frame=121, battle=2, trainer={"trainer_id": 225, "frame": 118}))
        assert result["trainer_battle"] == {"trainer_id": 225, "rival_team": 0} and not runtime.journal.pending_ids("a")  # the run has no Rival Swap
    finally:
        runtime.close()


def test_in_battle_batch_issues_the_window_and_its_receipt_enforces_the_death_once(tmp_path):
    runtime = create_runtime(tmp_path, contract("yellow", "yellow"), free_service=True)
    try:
        owners, death_id = dead_pair(runtime)
        assert window_command(runtime, "b") is None
        _, result = publish(runtime, "a", owners["a"], armed_batch(runtime, "a", 1, frame=125, battle=1))
        assert "instruction_issued" not in result and window_command(runtime, "a") is None  # the killer has nothing pending
        _, result = publish(runtime, "b", owners["b"], armed_batch(runtime, "b", 1, frame=125, battle=0))
        assert "instruction_issued" not in result  # out of battle the overworld held faint owns the death
        operation, result = publish(runtime, "b", owners["b"], armed_batch(runtime, "b", 2, frame=130, battle=1))
        command = window_command(runtime, "b")
        a = command["body"]["authority"]
        assert result["instruction_issued"] == a["challenge"] == auth.challenge_for(operation, death_id)
        assert command["body"]["death_id"] == death_id and a["frame"] == 131 and a["frames"] == {"first": 131, "count": auth.WINDOW_FRAMES}
        assert runtime.journal.pending_ids("b")[0] != command["command_id"], "the death command stays the oldest pending command"
        _, result = publish(runtime, "b", owners["b"], armed_batch(runtime, "b", 3, frame=160, battle=1))
        assert "instruction_issued" not in result and window_command(runtime, "b")["command_id"] == command["command_id"]  # one window at a time
        rows = [unreached_row(a, f) for f in (140, 141, 142)] + [reached_row(a, 143)]
        operation, message, result = window_ack(runtime, "b", owners["b"], command, rows, frame=144, battle=1)
        record_ = death(runtime, death_id)
        assert result["instruction_outcome"] == "fainted" and result["instruction_digest"] == digest(record_["enforcement"])
        assert record_["phase"] == "pending_faint" and record_["enforcement"]["site"] == "player_action" and record_["enforcement"]["frame"] == 143
        assert record_["enforcement"]["outcome"] == "fainted" and record_["enforcement"]["evidence_digest"] == digest(rows[3])
        assert window_command(runtime, "b") is None, "an enforced death is not re-issued"
        assert runtime.journal.command("b", command["command_id"])["outcome"] == "ACK"
        ack(runtime, "b", owners["b"], message, operation)  # replay
        assert runtime.journal.event_snapshot("b", operation).result == result
        _, result = publish(runtime, "b", owners["b"], armed_batch(runtime, "b", 4, frame=200, battle=1))
        assert "instruction_issued" not in result
        # the overworld held faint finds HP already 0000: its proven no-op receipt closes the death
        force = runtime.journal.command("b", runtime.journal.pending_ids("b")[0])
        message = acknowledgement(runtime, "b", force)
        message["receipt"]["before"] = copy.deepcopy(message["receipt"]["after"])
        for side in ("before", "after"):  # an overworld readback: no battle, no active battler
            message["receipt"][side].update(battle_flag=0, active_slot=None, battle_hp=None)
        ack(runtime, "b", owners["b"], message)
        record_ = death(runtime, death_id)
        assert record_["phase"] == "pending_memorial" and record_["enforcement"]["outcome"] == "fainted"
        verify_journal(runtime.journal, runtime.state())
    finally:
        runtime.close()
    reopened = open_runtime(tmp_path)
    try:
        assert death(reopened, death_id)["enforcement"]["site"] == "player_action"
    finally:
        reopened.close()


def test_late_peer_death_needs_only_the_next_null_inventory_battle_heartbeat(tmp_path):
    runtime = create_runtime(tmp_path, contract("yellow", "yellow"), free_service=True)
    try:
        owners, death_id = dead_pair(runtime)
        assert window_command(runtime, "b") is None
        request = armed_batch(runtime, "b", 1, frame=150, battle=1)
        assert request["inventory"] is None and request["signals"] is None and request["acquisitions"] == []
        response = deliver(runtime, "b", owners["b"], request)
        assert response["observation_result"]["inventory_status"] == "absent"
        command = window_command(runtime, "b")
        assert command is not None and command["body"]["death_id"] == death_id
        assert command["body"]["authority"]["frame"] == 151
    finally:
        runtime.close()


def test_non_terminal_windows_leave_the_death_pending_and_re_issue_only_while_in_battle(tmp_path):
    runtime = create_runtime(tmp_path, contract("red", "blue"), free_service=True)
    try:
        owners, death_id = dead_pair(runtime)
        publish(runtime, "b", owners["b"], armed_batch(runtime, "b", 1, frame=130, battle=1))
        first = window_command(runtime, "b")
        a = first["body"]["authority"]
        operation, _, result = window_ack(runtime, "b", owners["b"], first, [unreached_row(a, f) for f in (138, 139, 140)], frame=141, battle=1)
        assert result["instruction_outcome"] == "not_reached" and "instruction_digest" not in result and "enforcement" not in death(runtime, death_id)
        second = window_command(runtime, "b")
        assert second is not None and second["command_id"] != first["command_id"]
        b = second["body"]["authority"]
        assert b["frame"] == 142 and b["challenge"] == auth.challenge_for(operation, death_id) != a["challenge"]
        refused = reached_row(b, 150, site="loop_head", hp_hex="0000")  # already fainted: refused, nothing written
        assert refused["refusal"] == "already fainted" and refused["writes"] == []
        _, _, result = window_ack(runtime, "b", owners["b"], second, [unreached_row(b, 149), refused], frame=151, battle=0)
        assert result["instruction_outcome"] == "refused" and window_command(runtime, "b") is None  # the battle ended: no re-issue
        publish(runtime, "b", owners["b"], armed_batch(runtime, "b", 2, frame=160, battle=0))
        assert window_command(runtime, "b") is None
        publish(runtime, "b", owners["b"], armed_batch(runtime, "b", 3, frame=170, battle=2))
        third = window_command(runtime, "b")
        assert third is not None and third["body"]["authority"]["frame"] == 171
        _, _, result = window_ack(runtime, "b", owners["b"], third, [], frame=172, battle=1)  # declined: it arrived too late to arm
        assert result["instruction_outcome"] == "declined" and window_command(runtime, "b") is not None  # still in battle: re-issued
        assert death(runtime, death_id)["phase"] == "pending_faint" and "enforcement" not in death(runtime, death_id)
        verify_journal(runtime.journal, runtime.state())
    finally:
        runtime.close()


@pytest.mark.parametrize("fault", ["challenge", "start", "order", "schema", "step", "late", "closed"])
def test_hostile_window_receipts_commit_nothing(tmp_path, fault):
    runtime = create_runtime(tmp_path, contract("yellow", "red"), free_service=True)
    try:
        owners, death_id = dead_pair(runtime)
        publish(runtime, "b", owners["b"], armed_batch(runtime, "b", 1, frame=130, battle=1))
        command = window_command(runtime, "b")
        a = command["body"]["authority"]
        rows = [unreached_row(a, 140), reached_row(a, 141)]
        receipt = {"schema": auth.RECEIPT, "challenge": a["challenge"], "frame": 142, "battle": 1, "rows": rows}
        if fault == "challenge":
            receipt["challenge"] = "0" * 32
        elif fault == "start":
            receipt["rows"] = [unreached_row(a, 130), reached_row(a, 131)]  # the window starts at 131
        elif fault == "order":
            receipt["rows"] = rows[::-1]
        elif fault == "schema":
            receipt["schema"] = "rby-held-faint-evidence-v1"
        elif fault == "step":
            receipt["rows"][1]["step"] += 1
        elif fault == "late":
            receipt["rows"] = [unreached_row(a, 131 + auth.WINDOW_FRAMES)]
        else:
            # the overworld receipt closed the death first: a terminal window arriving afterwards is contradictory
            force = runtime.journal.command("b", runtime.journal.pending_ids("b")[0])
            message = acknowledgement(runtime, "b", force)
            ack(runtime, "b", owners["b"], message)
            assert death(runtime, death_id)["phase"] == "pending_memorial"
        message = {"event": "command_ack", "command_id": command["command_id"], "command_sequence": command["command_sequence"], "outcome": "ACK",
                   "receipt": receipt}
        before = runtime.journal.snapshot()
        with pytest.raises(JournalError):
            ack(runtime, "b", owners["b"], message)
        assert runtime.journal.snapshot() == before and "enforcement" not in death(runtime, death_id)
    finally:
        runtime.close()


@pytest.mark.parametrize("corrupt", [lambda e: e.update(site="poison_tail"), lambda e: e.update(outcome="refused"), lambda e: e.pop("evidence_digest"),
                                     lambda e: e.update(evidence_digest="0" * 64)])
def test_corrupt_enforcement_records_refuse_restore(tmp_path, corrupt):
    runtime = create_runtime(tmp_path, contract("blue", "blue"), free_service=True)
    try:
        owners, death_id = dead_pair(runtime)
        publish(runtime, "b", owners["b"], armed_batch(runtime, "b", 1, frame=130, battle=1))
        command = window_command(runtime, "b")
        a = command["body"]["authority"]
        window_ack(runtime, "b", owners["b"], command, [reached_row(a, 140, site="loop_head")], frame=141)
        snapshot = runtime.journal.snapshot()
        state = copy.deepcopy(snapshot.state)
        corrupt(state["components"][FAINTS]["deaths"][death_id]["enforcement"])
        runtime.journal.commit("a", secrets.token_hex(16), {"event": "corrupt-enforcement-fixture"}, expected_revision=snapshot.revision,
                               state=state, commands={"a": [], "b": []}, result={"ack": "ACK"})
        with pytest.raises(JournalError, match="enforcement"):
            runtime.state()
    finally:
        runtime.close()


@pytest.mark.parametrize("mutate", [lambda r: r.update(battle=256), lambda r: r.update(battle="1"), lambda r: r.update(trainer={"trainer_id": 0, "frame": 100}),
                                    lambda r: r.update(trainer={"trainer_id": 225}), lambda r: r.update(trainer={"trainer_id": 225, "frame": 131}),
                                    lambda r: r.update(trainer=[225])])
def test_polled_battle_fields_are_typed(tmp_path, mutate):
    runtime = create_runtime(tmp_path, contract("blue", "yellow"), free_service=True)
    try:
        owner, initial, _ = enrolled(runtime, "a")
        request = armed_batch(runtime, "a", 1, frame=130)
        mutate(request)
        before = runtime.journal.snapshot()
        with pytest.raises(JournalError):
            record(runtime, "a", secrets.token_hex(16), request)
        assert runtime.journal.snapshot() == before
        assert record(runtime, "a", secrets.token_hex(16), armed_batch(runtime, "a", 1, frame=130, battle=255))["ack"] == "ACK"
    finally:
        runtime.close()
