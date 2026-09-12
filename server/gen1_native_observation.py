"""Native trade checkpoints retained with their accounted inventory frame.

The client supplies the real party readback, including its battle flag. Never
invent that flag from the full-save point, which does not include battle WRAM.
These observations do not grant native execution or verify a SaveRAM flush.
"""

import copy

from server import event_reference
from server.gen1_command_receipts import validate_party_snapshot
from server.gen1_full_save import SYMBOLS, matches_checkpoint
from server.gen1_initial_observation import validate as validate_inventory
from server.gen1_native_trade_receipts import validate_party_storage
from server.gen1_party_codec import PartyCodec, PartyCodecError
from server.gen1_trade_preparation import FIELDS, SCHEMA, boxed_keys
from server.protocol import digest
from server.protocol_journal import JournalError

COMPONENT = "gen1-native-observations"
OBSERVATION = "rby-native-observation-v1"


def key(player):
    return digest({"component": COMPONENT, "player": player})[:32]


def validate(checkpoint, observation, initial):
    if observation is None:
        raise JournalError("native checkpoint requires its same-frame full inventory")
    validate_inventory(observation, initial["metadata"], initial["binding"])
    if observation["host"] != initial["observation"]["host"]:
        raise JournalError("native checkpoint replaced its enrolled physical owner")
    if (
        not isinstance(checkpoint, dict)
        or set(checkpoint) != FIELDS
        or checkpoint["schema"] != SCHEMA
        or checkpoint["final_sha1"] != observation["final_sha1"]
    ):
        raise JournalError("complete admitted native checkpoint required")
    variant = initial["metadata"]["gen1_metadata"]["cartridge"]["variant"]
    party = validate_party_snapshot(checkpoint["party"], variant=variant)
    identity = initial["metadata"]["save_identity"]
    if (
        checkpoint["party"]["battle_flag"] != 0
        or checkpoint["party"]["save_id"] != identity["ot_id"]
        or checkpoint["party"]["save_name"] != identity["trainer_name"]
    ):
        raise JournalError("native observation needs the enrolled overworld party")
    for field in ("map", "current_box"):
        if type(checkpoint[field]) is not int or not 0 <= checkpoint[field] <= 255:
            raise JournalError("native checkpoint map/box byte required")
    matches_checkpoint(observation["source"], checkpoint)
    validate_party_storage(checkpoint["party_storage_hex"], party)
    try:
        codec = PartyCodec(variant)
        codec.validate_party([mon.raw for mon in party], boxed_keys=boxed_keys(checkpoint, codec))
    except PartyCodecError as error:
        raise JournalError(str(error)) from error
    return checkpoint


def checkpoint_from(party, observation):
    """Join actual party readback with bytes already retained in the same frame."""
    source = observation["source"]
    symbols = SYMBOLS["pokeyellow" if source["variant"] == "yellow" else "pokered"]
    main = bytes.fromhex(source["fields"]["main"])
    return {
        "schema": SCHEMA,
        "final_sha1": observation["final_sha1"],
        "party": copy.deepcopy(party),
        "party_storage_hex": source["fields"]["party"],
        "name_hex": source["fields"]["name"],
        "map": main[symbols["wCurMap"] - symbols["wMainDataStart"]],
        "current_box": main[symbols["wCurrentBoxNum"] - symbols["wMainDataStart"]],
        "active_box_hex": source["fields"]["box"],
        "cart_hex": source["cart_hex"],
    }


def stage(document, player, operation, message):
    from server.gen1_observation_provenance import observation_bundle

    bundle = observation_bundle(message)
    evidence = bundle.get("native_checkpoint")
    if evidence is None:
        return None
    if (
        not isinstance(evidence, dict)
        or set(evidence) != {"schema", "party"}
        or evidence["schema"] != OBSERVATION
    ):
        raise JournalError("typed native party observation required")
    observation = bundle["inventory"]
    initial = document["components"]["gen1-initial-observations"][player]
    validate_inventory(observation, initial["metadata"], initial["binding"])
    checkpoint = checkpoint_from(evidence["party"], observation)
    validate(checkpoint, observation, initial)
    entry = {
        "origin": event_reference.make(player, operation, message),
        "frame": observation["frame"],
        "party": copy.deepcopy(evidence["party"]),
    }
    document["components"].setdefault(COMPONENT, {})[player] = entry
    return {"entry": entry, "record": {"namespace": COMPONENT, "key": key(player), "value": entry}}


def verify_state(stage):
    entries = stage.document()["components"].get(COMPONENT, {})
    if not isinstance(entries, dict) or set(entries) - {"a", "b"}:
        raise JournalError("invalid native observation component")
    for player, entry in entries.items():
        if not isinstance(entry, dict) or set(entry) != {"origin", "frame", "party"}:
            raise JournalError("complete native observation entry required")
        if event_reference.validate(entry["origin"])["player"] != player:
            raise JournalError("native observation reference changed player")
        if type(entry["frame"]) is not int or not 0 <= entry["frame"] <= 2**53 - 1:
            raise JournalError("invalid native observation frame")


def verify_journal(journal, stage):
    verify_state(stage)
    document = stage.document()
    entries = document["components"].get(COMPONENT, {})
    for player in ("a", "b"):
        entry = entries.get(player)
        record = journal.record(COMPONENT, key(player))
        if (entry is None) != (record is None) or record is not None and record.value != entry:
            raise JournalError("native observation differs from its atomic record")
        if entry is None:
            continue
        event = event_reference.resolve(journal, entry["origin"])
        if (
            event.revision != record.revision
            or event.request.get("event") not in {"frame_complete", "native_frame_handoff"}
            or event.result.get("observations_settled") is not True
            or event.result.get("native_checkpoint_digest") != digest(entry)
        ):
            raise JournalError("native observation lost its settled frame event/result")
        from server.gen1_observation_provenance import observation_bundle

        bundle = observation_bundle(event.request)
        if (
            bundle.get("native_checkpoint") != {"schema": OBSERVATION, "party": entry["party"]}
            or bundle["inventory"]["frame"] != entry["frame"]
        ):
            raise JournalError("native observation differs from its actual frame source")
        from server.gen1_frame_journal import retained_return

        anchor = document["components"]["gen1-frame-progress"][player]["ledger"]["anchor"]
        closed = retained_return(
            journal, player, event.result.get("closed_frame_digest", ""), anchor
        )
        if (
            event.request["event"] == "frame_complete"
            and closed["receipt"] != event.request["receipt"]
        ) or closed["receipt"]["after"] != entry["frame"]:
            raise JournalError("native observation lost its original consumed frame range")
        initial = document["components"]["gen1-initial-observations"][player]
        validate_inventory(bundle["inventory"], initial["metadata"], initial["binding"])
        validate(checkpoint_from(entry["party"], bundle["inventory"]), bundle["inventory"], initial)


def _read_checkpoints(runtime, current_players):
    from server.gen1_observation_provenance import observation_bundle

    stage = runtime.state()
    document = stage.document()
    entries = document["components"].get(COMPONENT, {})
    if set(entries) != {"a", "b"}:
        raise JournalError("both native checkpoint observations are required")
    for player in current_players:
        entry = entries[player]
        from server.gen1_frame_runtime import verified_held_frame

        verified_held_frame(document, player, entry["frame"])
    return {
        player: checkpoint_from(
            entry["party"],
            observation_bundle(event_reference.resolve(runtime.journal, entry["origin"]).request)[
                "inventory"
            ],
        )
        for player, entry in entries.items()
    }


def checkpoints(runtime):
    """Both current held checkpoints: required for an actual trade proposal."""
    return _read_checkpoints(runtime, ("a", "b"))


def candidate_checkpoints(runtime, actor):
    """UI eligibility only, allowing the peer to finish its already granted range.

    Issuing the receptionist obligation prevents subsequent ordinary grants.
    The eventual offer must still call checkpoints and revalidate both members.
    """
    if actor not in ("a", "b"):
        raise JournalError("receptionist actor required")
    return _read_checkpoints(runtime, (actor,))
