"""Source-proved ordinary evolution migrates one existing logical member.

The publication witness follows final party/list/name/move/dex writes. It is a
complete physical result, so it can migrate immediately even before an overworld
inventory checkpoint. Acquisition ordinals and original rule areas never change.
"""

import copy
import hashlib

from server import event_reference
from server.admission_context import same_admitted_context
from server.gen1_faint_runtime import synchronize
from server.gen1_initial_observation import COMPONENT as INITIAL, display_name
from server.gen1_party_codec import PartyCodec
from server.gen1_starter_settlement import context
from server.identity_registry import IdentityWitness, MigrationWitness
from server.gen1_engine_bridge import rekey as _rekey
from server.protocol import digest
from server.protocol_journal import JournalError, _identifier, _player
from server.state import MonInfo

COMPONENT = "gen1-ordinary-evolutions"
EVENT = "evolution_observation"
SCHEMA = "rby-evolution-observation-v1"


def record_key(player):
    _player(player)
    return digest({"component": COMPONENT, "player": player})[:32]


def result_for(entry):
    return {"ack": "ACK", "evolution_digest": digest(entry), "ordinary_execution": False}


def receipts_of(message):
    from server.gen1_observation_provenance import contained_receipts

    rows = contained_receipts(message)  # a free-run batch (or a compound frame): one wire list, raw indices kept
    if rows is not None:
        return rows
    payload = message.get("payload")
    if (
        set(message) != {"event", "payload"}
        or message["event"] != EVENT
        or not isinstance(payload, dict)
        or set(payload) != {"schema", "sequence", "receipts"}
        or payload["schema"] != SCHEMA
        or type(payload["sequence"]) is not int
        or payload["sequence"] < 1
    ):
        raise JournalError("typed sequential evolution observation required")
    return payload["receipts"]


def decode_receipts(rows, initial, reference, *, rom=None):
    from server.gen1_source_receipts import decode

    # Decode the complete generation-owned wire list before selecting our facts;
    # raw source indices must not be renumbered by filtering input rows.
    return [
        row
        for row in decode(
            rows, initial["metadata"], initial["binding"], reference=reference, rom=rom
        )
        if row["kind"] == "evolution"
    ]


def _checked(runtime, document, player, row, current, request, rom):
    if (
        not isinstance(row, dict)
        or set(row) != {"kind", "fact", "source_ref"}
        or row["kind"] != "evolution"
    ):
        raise JournalError("typed evolution fact required")
    ref = row["source_ref"]
    if (
        not isinstance(ref, dict)
        or set(ref) != {"event", "index"}
        or type(ref["index"]) is not int
        or ref["index"] < 0
        or event_reference.validate(ref["event"])["player"] != player
    ):
        raise JournalError("owned evolution source row required")
    message = (
        request
        if ref["event"] == current
        else event_reference.resolve(runtime.journal, ref["event"]).request
    )
    rows = receipts_of(message)
    if ref["index"] >= len(rows):
        raise JournalError("evolution source index leaves its event")
    raw = rows[ref["index"]]
    decoded = decode_receipts([raw], document["components"][INITIAL][player], ref["event"], rom=rom)
    if len(decoded) != 1:
        raise JournalError("evolution source reference names another kind")
    result = decoded[0]
    if result["kind"] != row["kind"] or result["fact"] != row["fact"]:
        raise JournalError("evolution fact differs from its raw source receipt")
    return raw


def stage_evolutions(
    runtime,
    stage,
    document,
    player,
    operation,
    facts,
    frame_origin=None,
    *,
    frame_request=None,
    rom=None,
):
    _player(player)
    _identifier(operation)
    if not isinstance(facts, list) or not 1 <= len(facts) <= 16:
        raise JournalError("nonempty bounded evolution facts required")
    initial = document["components"].get(INITIAL, {}).get(player)
    session = runtime.gate.sessions.get(player)
    if (
        initial is None
        or session is None
        or not same_admitted_context(initial["metadata"], session.metadata)
    ):
        raise JournalError("evolution needs its same admitted physical owner")
    if document["active_trade"] is not None:
        raise JournalError("native trade owns evolution migration")
    from server.gen1_native_frame_accounting import borrowed

    if borrowed(document, player):
        raise JournalError("borrowed native frames cannot produce ordinary evolution")
    current = (
        event_reference.make(player, operation, frame_request)
        if frame_request is not None
        else None
    )
    if frame_origin is not None:
        from server.gen1_observation_provenance import stage_origin

        stage_origin(
            document,
            player,
            operation,
            {
                "event": "acquisition_observation",
                "payload": {"receipts": receipts_of(frame_request)},
            },
            frame_origin=frame_origin,
            frame_request=frame_request,
        )
    elif player in document["components"].get("gen1-frame-progress", {}):
        raise JournalError("frame-accounted evolution needs its compound source origin")
    entries = document["components"].setdefault(COMPONENT, {})
    prior = entries.get(player)
    entry = {
        "sequence": prior["sequence"] + 1 if prior else 1,
        "operation_id": operation,
        "previous_operation_id": prior["operation_id"] if prior else initial["operation_id"],
        "settled": copy.deepcopy(prior["settled"]) if prior else [],
    }
    if frame_origin is not None:
        entry["frame_origin"] = copy.deepcopy(frame_origin)
    known = {r["fact"]["receipt_digest"] for r in entry["settled"]}
    last = max(
        (r["fact"]["return_frame"] for r in entry["settled"]),
        default=initial["observation"]["frame"],
    )
    codec = PartyCodec(initial["metadata"]["gen1_metadata"]["cartridge"]["variant"])
    own = context(initial, player)
    for row in facts:
        raw = _checked(runtime, document, player, row, current, frame_request, rom)
        fact = row["fact"]
        if fact["receipt_digest"] in known or fact["call_frame"] < last:
            raise JournalError("evolution repeats or reorders prior source history")
        known.add(fact["receipt_digest"])
        last = fact["return_frame"]
        saved = {
            **copy.deepcopy(row),
            "migration_id": None,
            "member_id": None,
            "rule": "cancelled",
            "area": None,
            "usable": False,
        }
        if fact["outcome"] == "evolved":
            before = codec.validate_blob(bytes.fromhex(fact["outgoing"]["blob_hex"]))
            after = codec.validate_blob(bytes.fromhex(fact["incoming"]["blob_hex"]))
            member = stage.identities.resolve(own, before.key)
            if member is None:
                raise JournalError("ordinary evolution has no existing logical member")
            if before.key in stage.rules.pending_memorials[player]:
                raise JournalError("evolution of a retiring member requires reconciliation")
            identifier = digest(
                {"component": COMPONENT, "run": runtime.journal.run_id, "source": row["source_ref"]}
            )[:32]
            stage.identities.migrate_many(
                player,
                identifier,
                [
                    MigrationWitness(
                        member,
                        own,
                        before.key,
                        before.sha256,
                        IdentityWitness(own, after.key, after.sha256, 1),
                    )
                ],
            )
            usable = before.key in stage.rules.party_keys[player]
            rule, area = _rekey(
                stage.rules,
                player,
                before.key,
                MonInfo(
                    key=after.key,
                    species=after.species_id,
                    level=after.level,
                    nickname=display_name(after.nickname),
                ),
                reason="evolution",
            )
            if usable:
                stage.rules.party_keys[player].discard(before.key)
                stage.rules.party_keys[player].add(after.key)
            if before.key in stage.rules.bonus_keys[player]:
                stage.rules.bonus_keys[player].discard(before.key)
                stage.rules.bonus_keys[player].add(after.key)
            stage.rules.mon_stats.pop(stage.rules.cache_key(player, before.key), None)
            hp, attack, defense, speed, special = after.computed_stats
            stage.rules.cache_stats(
                player,
                after.key,
                {
                    "level": after.level,
                    "maxHP": hp,
                    "attack": attack,
                    "defense": defense,
                    "speed": speed,
                    "spAtk": special,
                    "spDef": special,
                },
            )
            saved.update(
                migration_id=identifier, member_id=member, rule=rule, area=area, usable=usable
            )
            # Update the cache only if this source follows its existing inventory.
            # A same-frame later inventory may include another legitimate action.
            observed = document["components"].get("gen1-inventory-observations", {}).get(player)
            if observed is None or observed["observation"]["frame"] <= fact["return_frame"]:
                from server.gen1_capture_receipt import party_mons

                party = party_mons(
                    codec, bytes.fromhex(raw["receipt"]["after"]["point"]["party_hex"])
                )
                stage.rules.party_size[player] = len(party)
                stage.rules.partner_blobs[player] = [
                    {
                        "slot": i,
                        "key": m.key,
                        "species_id": m.species_id,
                        "level": m.level,
                        "blob": m.raw,
                    }
                    for i, m in enumerate(party)
                ]
        entry["settled"].append(saved)
    entries[player] = entry
    synchronize(stage, document)
    return {
        "entry": entry,
        "result": result_for(entry),
        "commands": {"a": [], "b": []},
        "records": [
            {"namespace": COMPONENT, "key": record_key(player), "value": copy.deepcopy(entry)}
        ],
    }


def record(runtime, player, operation, message):
    prior = runtime.journal.event(player, operation, message)
    if prior is not None:
        return prior.result
    stage = runtime.state()
    document = stage.document()
    rows = receipts_of(message)
    if not isinstance(rows, list) or any(
        not isinstance(row, dict) or row.get("kind") != "evolution" for row in rows
    ):
        raise JournalError("standalone evolution event accepts only evolution rows")
    initial = document["components"][INITIAL][player]
    from server.gen1_acquisition_runtime import source_rom

    provider = getattr(runtime, "prepared_cartridges", None)
    rom = source_rom(initial["metadata"], player, provider.rom if provider is not None else None)
    facts = decode_receipts(
        rows, initial, event_reference.make(player, operation, message), rom=rom
    )
    result = stage_evolutions(
        runtime, stage, document, player, operation, facts, frame_request=message, rom=rom
    )
    if message["payload"]["sequence"] != result["entry"]["sequence"]:
        raise JournalError("evolution sequence skipped or repeated")
    return runtime.journal.commit(
        player,
        operation,
        message,
        expected_revision=stage.journal_revision,
        state=document,
        result=result["result"],
        commands=result["commands"],
        records=result["records"],
    ).result


def verify_state(stage):
    document = stage.document()
    entries = document["components"].get(COMPONENT, {})
    if not isinstance(entries, dict) or set(entries) - {"a", "b"}:
        raise JournalError("invalid evolution component")
    for player, entry in entries.items():
        if not isinstance(entry, dict) or set(entry) - {"frame_origin"} != {
            "sequence",
            "operation_id",
            "previous_operation_id",
            "settled",
        }:
            raise JournalError("complete evolution state required")
        _identifier(entry["operation_id"])
        _identifier(entry["previous_operation_id"])
        if (
            type(entry["sequence"]) is not int
            or entry["sequence"] < 1
            or not isinstance(entry["settled"], list)
        ):
            raise JournalError("ordered evolution history required")
        if "frame_origin" in entry:
            origin = event_reference.validate(entry["frame_origin"])
            if origin["player"] != player or origin["operation_id"] != entry["operation_id"]:
                raise JournalError("evolution origin belongs to another player/event")
        known = set()
        for row in entry["settled"]:
            if (
                not isinstance(row, dict)
                or set(row)
                != {
                    "kind",
                    "fact",
                    "source_ref",
                    "migration_id",
                    "member_id",
                    "rule",
                    "area",
                    "usable",
                }
                or row["kind"] != "evolution"
            ):
                raise JournalError("complete settled evolution required")
            ref = row["source_ref"]
            fact = row["fact"]
            if (
                not isinstance(ref, dict)
                or set(ref) != {"event", "index"}
                or type(ref["index"]) is not int
                or ref["index"] < 0
                or event_reference.validate(ref["event"])["player"] != player
                or not isinstance(fact, dict)
                or fact.get("receipt_digest") in known
            ):
                raise JournalError("unique owned evolution source required")
            known.add(fact["receipt_digest"])
            if type(row["usable"]) is not bool:
                raise JournalError("evolution usability must preserve an explicit rule mask")
            if fact["outcome"] == "cancelled":
                if (
                    row["migration_id"] is not None
                    or row["member_id"] is not None
                    or row["rule"] != "cancelled"
                ):
                    raise JournalError("cancelled evolution manufactured a migration")
                continue
            if fact["outcome"] != "evolved" or row["rule"] not in (
                "link",
                "pending_capture",
                "identity_only",
            ):
                raise JournalError("invalid evolution disposition")
            _identifier(row["migration_id"])
            _identifier(row["member_id"])
            expected = digest(
                {"component": COMPONENT, "run": document["identities"]["run_id"], "source": ref}
            )[:32]
            if row["migration_id"] != expected:
                raise JournalError("evolution migration id differs from its source event")
            event = document["identities"]["events"].get(player + ":" + str(row["migration_id"]))
            if event is None or event["kind"] != "identity_migration":
                raise JournalError("evolution lost its identity migration")
            witnesses = event["request"]["witnesses"]
            if (
                len(witnesses) != 1
                or witnesses[0]["member_id"] != row["member_id"]
                or witnesses[0]["before_key"] != fact["outgoing"]["key"]
                or witnesses[0]["after"]["key"] != fact["incoming"]["key"]
                or witnesses[0]["before_evidence_digest"]
                != hashlib.sha256(bytes.fromhex(fact["outgoing"]["blob_hex"])).hexdigest()
                or witnesses[0]["after"]["evidence_digest"]
                != hashlib.sha256(bytes.fromhex(fact["incoming"]["blob_hex"])).hexdigest()
            ):
                raise JournalError("evolution migration differs from complete source bytes")


def verify_journal(journal, stage, *, rom_provider=None):
    verify_state(stage)
    document = stage.document()
    from server.gen1_acquisition_runtime import source_rom

    for player, entry in document["components"].get(COMPONENT, {}).items():
        stored = journal.record(COMPONENT, record_key(player))
        event = journal.event_snapshot(player, entry["operation_id"])
        if (
            stored is None
            or stored.value != entry
            or event is None
            or stored.revision != event.revision
        ):
            raise JournalError("evolution lost its atomic event/record")
        if event.result.get("evolution_digest") != digest(entry):
            raise JournalError("evolution result differs from its stored history")
        from server.gen1_observation_provenance import batch_origin

        if "frame_origin" in entry:
            if (
                event_reference.resolve(journal, entry["frame_origin"]) != event
                or event.request.get("event") != "frame_complete"
                or event.result.get("observations_settled") is not True
            ):
                raise JournalError("evolution lost its settled containing frame")
        elif not batch_origin(event, entry, "evolution_digest") and (
            event.request.get("event") != EVENT
            or event.result != result_for(entry)
            or event.request["payload"]["sequence"] != entry["sequence"]
        ):
            raise JournalError("evolution standalone event differs from its sequence/result")
        initial = document["components"][INITIAL][player]
        rom = source_rom(initial["metadata"], player, rom_provider)
        for row in entry["settled"]:
            ref = row["source_ref"]
            source = event_reference.resolve(journal, ref["event"])
            rows = receipts_of(source.request)
            if not 0 <= ref["index"] < len(rows) or source.revision > stored.revision:
                raise JournalError("evolution source leaves its committed history")
            raw = rows[ref["index"]]
            facts = decode_receipts([raw], initial, ref["event"], rom=rom)
            if len(facts) != 1:
                raise JournalError("evolution history source names another kind")
            decoded = facts[0]
            if decoded["fact"] != row["fact"]:
                raise JournalError("evolution differs from its authoritative source result")
