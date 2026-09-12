"""Two independent deaths through real settlement/ACK handlers; acquisition is a fixture."""

import copy
import secrets

import pytest

from server.gen1_full_save import image
from server.gen1_memorial_runtime import COMPONENT, EVIDENCE, verify_operation
from server.gen1_party_codec import PartyCodec
from server.gen1_run_config import create_runtime, open_runtime
from server.gen1_starter_settlement import context, mon_info
from server.identity_registry import IdentityWitness
from server.protocol import digest
from tests.unit.rules_fixture import seed_link_half
from tests.unit.test_gen1_engine_signal_runtime import deliver
from tests.unit.test_gen1_faint_runtime import ack, paired, signal_batch
from tests.unit.test_gen1_held_faint import checkpoint
from tests.unit.test_gen1_inventory_observation import party_point
from tests.unit.test_gen1_memorial_runtime import completion, observe
from tests.unit.test_gen1_party_codec import make_blob
from tests.unit.test_gen1_sessions import contract


def second_pair(runtime):
    """Explicitly enroll a second linked pair and one unlinked physical spare."""
    stage = runtime.state()
    initials = stage.document()["components"]["gen1-initial-observations"]
    physical = {}
    members = []
    for player in ("a", "b"):
        codec = PartyCodec(runtime.contract["players"][player]["variant"])
        mon = codec.validate_blob(make_blob(codec, dv=0x4321, otid=0))
        identifier = secrets.token_hex(16)
        members.append(
            stage.identities.acquire(
                identifier,
                identifier,
                IdentityWitness(context(initials[player], player), mon.key, mon.sha256, 1),
            )["member_id"]
        )
        seed_link_half(stage.rules, player, "second-pair-fixture", mon_info(mon))
        spare = make_blob(codec, dv=0x7654, otid=0)
        physical[player] = [stage.rules.partner_blobs[player][0]["blob"], mon.raw, spare]
        stage.rules.party_size[player] = 3
        stage.rules.partner_blobs[player] = [
            {
                "slot": slot,
                "key": row.key,
                "species_id": row.species_id,
                "level": row.level,
                "blob": row.raw,
            }
            for slot, row in enumerate(codec.validate_party(physical[player]))
        ]
    stage.identities.create_link("b", secrets.token_hex(16), members)
    stage.barrier.set_history(stage.history_digest())
    runtime.journal.commit(
        "a",
        secrets.token_hex(16),
        {"event": "explicit-second-linked-pair-fixture"},
        expected_revision=stage.journal_revision,
        state=stage.document(),
        commands={"a": [], "b": []},
        result={"ack": "ACK"},
    )
    return physical


def zero_hp(raw):
    value = bytearray(raw)
    value[1:3] = b"\0\0"
    return bytes(value)


@pytest.mark.parametrize("variants", [("yellow", "yellow"), ("red", "blue"), ("blue", "yellow")])
def test_opposite_player_deaths_renew_preimage_after_real_force_faint_and_close_both(
    tmp_path, variants
):
    runtime = create_runtime(tmp_path, contract(*variants))
    try:
        owners = paired(runtime)
        physical = second_pair(runtime)
        last_point = {}

        def head(player):
            return runtime.journal.command(player, runtime.journal.pending_ids(player)[0])

        def faint(player, slot):
            physical[player][slot] = zero_hp(physical[player][slot])
            value = signal_batch(runtime, player)
            point = value["signals"][-1]["point"]
            point.update(
                party_hex=party_point(
                    runtime.contract["players"][player]["variant"], physical[player]
                )["fields"]["party"],
                active_slot=slot,
                battle_species=physical[player][slot][0],
                battle_hp=0,
            )
            deliver(runtime, player, owners[player], value)

        def force_faint(player):
            command = head(player)
            assert command["body"]["cmd"] == "force_faint"
            codec = PartyCodec(runtime.contract["players"][player]["variant"])
            slot = next(
                i
                for i, raw in enumerate(physical[player])
                if codec.validate_blob(raw).key == command["body"]["key"]
            )
            before = {
                "schema": "gen1-party-readback-v1",
                "variant": codec.variant,
                "save_id": "0000",
                "save_name": "SAME",
                "party_count": len(physical[player]),
                "party": [raw.hex().upper() for raw in physical[player]],
                "species_list": [raw[0] for raw in physical[player]] + [255],
                "battle_flag": 0,
                "active_slot": None,
                "battle_hp": None,
            }
            physical[player][slot] = zero_hp(physical[player][slot])
            after = {**before, "party": [raw.hex().upper() for raw in physical[player]]}
            ack(
                runtime,
                player,
                owners[player],
                {
                    "event": "command_ack",
                    "command_id": command["command_id"],
                    "command_sequence": command["command_sequence"],
                    "outcome": "ACK",
                    "receipt": {
                        "schema": "gen1-force-faint-receipt-v1",
                        "before": before,
                        "after": after,
                    },
                },
            )

        def read(player):
            command, message = observe(runtime, player)
            point = copy.deepcopy(last_point.get(player, message["receipt"]["point"]))
            point["fields"]["party"] = party_point(variants["ab".index(player)], physical[player])[
                "fields"
            ]["party"]
            point["cart_hex"] = image(point).hex().upper()
            message["receipt"]["point"] = point
            return command, message

        faint("a", 0)  # D1 -> real FF1 to b.
        force_faint("b")  # Real ACK schedules MO1 for both players.
        old_command, old_read = read("a")
        faint("b", 1)  # Independent D2 -> real FF2 to a, behind a's MO1.
        assert [row["cmd"] for row in runtime.journal.pending("a")] == [
            "memorial_observe",
            "force_faint",
        ]
        death_ids = set(runtime.state().document()["components"]["gen1-faint-settlement"]["deaths"])
        assert len(death_ids) == 2
        ack(runtime, "a", owners["a"], old_read)
        assert [row["cmd"] for row in runtime.journal.pending("a")] == [
            "force_faint",
            "memorial_observe",
        ]
        entry = runtime.state().document()["components"][COMPONENT]["entries"]["a"][0]
        assert entry["payload"] is None and len(entry["observations"]) == 1
        force_faint("a")  # Typed full-party ACK changes the second mon's HP.
        fresh_command, fresh_read = read("a")
        assert fresh_command["command_id"] != old_command["command_id"]
        assert fresh_read["receipt"]["point"] != old_read["receipt"]["point"]
        ack(runtime, "a", owners["a"], fresh_read)

        for _ in range(8):
            for player in ("a", "b"):
                if not runtime.journal.pending_ids(player):
                    continue
                command = head(player)
                if command["body"]["cmd"] == "memorial_observe":
                    _, message = read(player)
                    ack(runtime, player, owners[player], message)
                else:
                    assert command["body"]["cmd"] == "memorialize"
                    stage = runtime.state().document()
                    initial = stage["components"]["gen1-initial-observations"][player]
                    payload = stage["components"][COMPONENT]["entries"][player][-1]["payload"]
                    evidence = {
                        "schema": EVIDENCE,
                        "phase": "memorialize",
                        "command_id": command["command_id"],
                        "command_sequence": command["command_sequence"],
                        "context_generation": payload["context_generation"],
                        "final_sha1": payload["final_sha1"],
                        "host": {**initial["observation"]["host"], "frame": payload["frame"]},
                        "checkpoint": checkpoint(variants["ab".index(player)]),
                        "intent": {
                            "schema": "rby-memorial-intent-v1",
                            "body_digest": digest(command["body"]),
                        },
                        "current": payload["before"],
                    }
                    assert (
                        verify_operation(
                            player, command, evidence, stage, initial["binding"]
                        ).ttl_ms
                        == 1000
                    )
                    _, message = completion(runtime, player)
                    last_point[player] = copy.deepcopy(payload["after"])
                    physical[player] = [
                        raw
                        for raw in physical[player]
                        if PartyCodec(variants["ab".index(player)]).validate_blob(raw).key
                        != command["body"]["key"]
                    ]
                    ack(runtime, player, owners[player], message)
            if not any(runtime.journal.pending_ids(player) for player in ("a", "b")):
                break
        stage = runtime.state()
        assert not any(runtime.journal.pending_ids(player) for player in ("a", "b"))
        assert all(
            row["phase"] == "memorial_complete"
            for row in stage.document()["components"]["gen1-faint-settlement"]["deaths"].values()
        )
        assert death_ids.isdisjoint(stage.barrier.document()["blockers"])
        assert not any(stage.rules.pending_memorials.values())
        assert len(stage.document()["rules"]["memorial"]["retired_pairs"]) == 2
    finally:
        runtime.close()
    runtime = open_runtime(tmp_path)
    try:
        assert len(runtime.state().document()["rules"]["memorial"]["retired_pairs"]) == 2
    finally:
        runtime.close()
