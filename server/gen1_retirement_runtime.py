"""Non-linked acquisition retirement with typed causes, observations and file ACKs."""

import copy
import hashlib

from server import event_reference, gen1_grave_reservations as graves
from server.gen1_acquisition_runtime import (
    COMPONENT as ACQUISITIONS,
    CONSTRAINT_REASON,
    RETIREMENT_REASON,
    constraint_id,
    receipts_of,
)
from server.gen1_full_save import image
from server.gen1_held_faint import verify_owned_checkpoint
from server.gen1_initial_observation import inventory
from server.gen1_retirement import prepare, verify_receipt, wire_payload
from server.gen1_save_delta import recover_point
from server.held_write_permit import VerifiedHeldWrite
from server.issued_command import issued as issued
from server.operation_scope import command_scope
from server.protocol import digest
from server.protocol_journal import JournalError, _identifier

COMPONENT = "gen1-acquisition-retirement"
OBSERVE = "rby-retirement-observation-v1"
EVIDENCE = "rby-held-retirement-evidence-v1"
FIELDS = {
    "acquisition_id",
    "key",
    "reason",
    "cause",
    "origin",
    "observations",
    "observation_event",
    "payload",
    "receipt_operation",
    "receipt_digest",
}
SUMMARY_FIELDS = {
    "acquisition_id",
    "key",
    "reason",
    "cause",
    "origin",
    "receipt_operation",
    "receipt_digest",
}


def summary(row):
    return {name: copy.deepcopy(row[name]) for name in SUMMARY_FIELDS}


def expand_entry(journal, row):
    from server.retained_physical_record import expand, is_retained

    if not is_retained(row):
        return row
    value = expand(journal, row, namespace=COMPONENT, summarize=summary)
    if not isinstance(value, dict) or set(value) != FIELDS or value["receipt_operation"] is None:
        raise JournalError("retained retirement must name a complete physical lifecycle")
    return value


def record_key(player, acquisition):
    return digest({"component": COMPONENT, "player": player, "acquisition": acquisition})[:32]


def acquisition(document, player, identifier):
    rows = [
        r
        for r in document["components"].get(ACQUISITIONS, {}).get(player, {}).get("settled", [])
        if r["acquisition_id"] == identifier
    ]
    if len(rows) != 1:
        raise JournalError("one exact settled retirement source required")
    row = rows[0]
    profiles = document["components"]["gen1-runtime"]["contract"]["players"]
    if (
        row["rule"] != "retirement_required"
        or row.get("retirement_reason") != RETIREMENT_REASON
        or row["fact"]["kind"] != "scripted_grant"
        or row["fact"]["yellow_only"] is not True
        or profiles[player]["variant"] != "yellow"
        or profiles["b" if player == "a" else "a"]["variant"] == "yellow"
        or row["link_id"] is not None
    ):
        raise JournalError("retirement lacks its Yellow-only mixed-title source policy")
    return row


def entry_for(document, player, identifier):
    rows = [
        r
        for r in document["components"].get(COMPONENT, {}).get(player, [])
        if r["acquisition_id"] == identifier
    ]
    if len(rows) != 1:
        raise JournalError("one exact pending retirement obligation required")
    return rows[0]


def policy_source(document, player, cause):
    if not isinstance(cause, dict):
        raise JournalError("typed retirement cause required")
    if set(cause) == {"kind", "acquisition_id"} and cause["kind"] == "yellow_only_grant":
        source = acquisition(document, player, cause["acquisition_id"])
        return {
            "acquisition_id": source["acquisition_id"],
            "key": source["fact"]["key"],
            "member_id": source["member_id"],
            "reason": RETIREMENT_REASON,
            "hold_id": constraint_id(player, source["acquisition_id"]),
            "hold_reason": CONSTRAINT_REASON,
        }
    if set(cause) == {"kind", "obligation_id"} and cause["kind"] == "paired_no_catch":
        from server.gen1_wild_encounter_runtime import retirement_source

        return retirement_source(document, player, cause["obligation_id"])
    raise JournalError("unknown retirement cause adapter")


def schedule_job(document, player, event, *, cause):
    source = policy_source(document, player, cause)
    commands, records = {"a": [], "b": []}, []
    rows = document["components"].get(COMPONENT, {}).get(player, [])
    same = [r for r in rows if r["acquisition_id"] == source["acquisition_id"]]
    if same:
        if len(same) != 1 or same[0]["cause"] != cause:
            raise JournalError("retirement acquisition already has another cause")
        return commands, records
    if graves.memorial_busy(document, player) or graves.retirement_busy(document, player):
        return commands, records
    row = {
        "acquisition_id": source["acquisition_id"],
        "key": source["key"],
        "reason": source["reason"],
        "cause": copy.deepcopy(cause),
        "origin": event_reference.make(event["player"], event["operation_id"], event["message"]),
        "observations": [],
        "observation_event": None,
        "payload": None,
        "receipt_operation": None,
        "receipt_digest": None,
    }
    document["components"].setdefault(COMPONENT, {}).setdefault(player, []).append(row)
    commands[player].append(read_body(row))
    records.append(
        {
            "namespace": COMPONENT,
            "key": record_key(player, row["acquisition_id"]),
            "value": copy.deepcopy(row),
        }
    )
    return commands, records


def read_body(row):
    return {
        "cmd": "retirement_observe",
        "acquisition_id": row["acquisition_id"],
        "key": row["key"],
        "reason": row["reason"],
    }


def write_body(row):
    return {
        "cmd": "acquisition_retire",
        "acquisition_id": row["acquisition_id"],
        "key": row["key"],
        "reason": row["reason"],
        "payload": wire_payload(row["payload"]),
    }


def schedule(document, player, event):
    commands, records = {"a": [], "b": []}, []
    if graves.memorial_busy(document, player) or graves.retirement_busy(document, player):
        return commands, records
    old = document["components"].get(COMPONENT, {}).get(player, [])
    known = {r["acquisition_id"] for r in old}
    for source in document["components"].get(ACQUISITIONS, {}).get(player, {}).get("settled", []):
        if source["rule"] != "retirement_required" or source["acquisition_id"] in known:
            continue
        return schedule_job(
            document,
            player,
            event,
            cause={"kind": "yellow_only_grant", "acquisition_id": source["acquisition_id"]},
        )
    # No-catch owns the source policy; archive mechanics remain the same.
    for identifier, obligation in (
        document["components"].get("gen1-wild-encounters", {}).get("obligations", {}).items()
    ):
        if obligation.get("target_player") == player and obligation.get("phase") == "pending":
            return schedule_job(
                document,
                player,
                event,
                cause={"kind": "paired_no_catch", "obligation_id": identifier},
            )
    return commands, records


def observation(command, receipt, document, player, binding, *, historical=False):
    if (
        not isinstance(receipt, dict)
        or set(receipt)
        != {
            "schema",
            "command_id",
            "command_sequence",
            "context_generation",
            "final_sha1",
            "host",
            "checkpoint",
            "point",
        }
        or receipt["schema"] != OBSERVE
    ):
        raise JournalError("complete retirement observation required")
    metadata = verify_owned_checkpoint(
        player, command, receipt, document, binding, historical=historical
    )
    if receipt["point"].get("variant") != metadata["gen1_metadata"]["cartridge"]["variant"]:
        raise JournalError("retirement observation cartridge changed")
    image(receipt["point"])
    return metadata


def preparation(journal, document, player, command, receipt, binding, *, historical=False):
    metadata = observation(command, receipt, document, player, binding, historical=historical)
    row = expand_entry(journal, entry_for(document, player, command["body"]["acquisition_id"]))
    policy = policy_source(document, player, row["cause"])
    point = receipt["point"]
    sources = [
        r
        for r in document["components"].get(ACQUISITIONS, {}).get(player, {}).get("settled", [])
        if r["acquisition_id"] == row["acquisition_id"]
    ]
    if len(sources) != 1:
        raise JournalError("retirement target lacks its settled acquisition provenance")
    source = sources[0]
    roster = inventory(point, metadata["save_identity"])
    members = [m for m in roster["members"] if m["key"] == row["key"]]
    if len(members) != 1:
        raise JournalError("retirement lost its exact physical target")
    member = members[0]
    blob = bytes.fromhex(
        member["blob_hex"] if member["location"] == "party" else member["box_blob_hex"]
    )
    if row["cause"]["kind"] == "yellow_only_grant":
        identity_event = document["identities"]["events"][player + ":" + row["acquisition_id"]]
        if (
            hashlib.sha256(blob).hexdigest()
            != identity_event["request"]["witness"]["evidence_digest"]
        ):
            raise JournalError("retirement target changed after its stable source proof")
    else:
        from server.gen1_starter_settlement import context

        initial = document["components"]["gen1-initial-observations"][player]
        from server.identity_registry import IdentityRegistry

        registry = IdentityRegistry.restore(
            document["identities"], run_id=document["identities"]["run_id"]
        )
        if registry.resolve(context(initial, player), row["key"]) != policy["member_id"]:
            raise JournalError("no-catch retirement target changed logical identity")
    head = row["payload"]["grave_head"] if historical else graves.latest(journal, document, player)
    anchor = graves.check_preimage(
        journal,
        document,
        player,
        point,
        head,
        source=row["payload"]["source_anchor"] if historical else None,
    )
    birth = None
    if member["location"] == "box" and member["box"] == 11:
        birth_event = event_reference.resolve(journal, source["source_ref"]["event"])
        raw = receipts_of(birth_event.request)[source["source_ref"]["index"]]
        if row["cause"]["kind"] != "yellow_only_grant" or raw["kind"] != "grant":
            raise JournalError("active-grave retirement needs its source-specific birth proof")
        if head is not None and head["revision"] > birth_event.revision:
            raise JournalError("grave changed after the boxed gift birth")
        birth = {
            "before": raw["receipt"]["call"]["point"]["box_hex"],
            "after": raw["receipt"]["return"]["point"]["box_hex"],
        }
    payload = prepare(
        point,
        row["key"],
        identity=metadata["save_identity"],
        context_generation=binding["context_generation"],
        final_sha1=metadata["gen1_metadata"]["cartridge"]["final_rom_sha1"],
        frame=receipt["host"]["frame"],
        reserved_digest=head["reservation_digest"] if head else None,
        birth_box=birth,
    )
    payload.update(grave_head=head, source_anchor=anchor)
    return payload


def completed(document, player, acquisition_id):
    matches = [
        r
        for r in document["components"].get(COMPONENT, {}).get(player, [])
        if r["acquisition_id"] == acquisition_id
    ]
    return len(matches) == 1 and matches[0]["receipt_operation"] is not None


def acknowledge(runtime, player, operation, message):
    previous = runtime.journal.event(player, operation, message)
    if previous is not None:
        return previous.result
    if (
        not isinstance(message, dict)
        or set(message) != {"event", "command_id", "command_sequence", "outcome", "receipt"}
        or message["outcome"] != "ACK"
    ):
        raise JournalError("typed retirement ACK required")
    stage = runtime.state()
    document = stage.document()
    command = runtime.journal.command(player, message["command_id"])
    row = entry_for(document, player, command["body"].get("acquisition_id"))
    source = policy_source(document, player, row["cause"])
    pending = runtime.journal.pending_ids(player)
    if (
        not pending
        or pending[0] != command["command_id"]
        or command["outcome"] is not None
        or type(message["command_sequence"]) is not int
        or command["command_sequence"] != message["command_sequence"]
        or row["receipt_operation"] is not None
    ):
        raise JournalError("retirement must own its oldest exact pending command")
    event = {"player": player, "operation_id": operation, "message": copy.deepcopy(message)}
    reference = event_reference.make(player, operation, message)
    commands = {"a": [], "b": []}
    records = []
    if command["body"] == read_body(row):
        if row["observation_event"] is not None:
            raise JournalError("retirement already prepared")
        prepared = preparation(
            runtime.journal,
            document,
            player,
            command,
            message["receipt"],
            runtime.gate.sessions[player].metadata["control_binding"],
        )
        if len(pending) > 1:
            row["observations"].append(reference)
            commands[player].append(read_body(row))
        else:
            row["observation_event"] = reference
            row["payload"] = prepared
            commands[player].append(write_body(row))
    elif row["payload"] is not None and command["body"] == write_body(row):
        verify_receipt(
            command,
            message["receipt"],
            row["payload"],
            identity=stage.rules.player_identity[player],
        )
        after = row["payload"]["after"]
        records.append(
            graves.advance(
                runtime.journal,
                document,
                player,
                operation,
                message,
                after,
                kind="retirement",
                target=row["acquisition_id"],
                previous=row["payload"]["grave_head"],
                revision=stage.journal_revision + 1,
            )
        )
        # Container/HP disposition is recorded here. Logical key and save owner
        # do not change, so this must not manufacture an identity migration.
        after_roster = inventory(after, stage.rules.player_identity[player])
        row["receipt_operation"] = operation
        row["receipt_digest"] = digest(message["receipt"])
        if row["cause"]["kind"] == "yellow_only_grant":
            blockers = stage.barrier.document()["blockers"]
            if blockers.get(source["hold_id"]) != source["hold_reason"]:
                raise JournalError("retirement lost its source constraint hold")
            del blockers[source["hold_id"]]
            stage.barrier.set_blockers(blockers)
        else:
            from server.gen1_wild_encounter_runtime import complete_retirement

            records.append(
                complete_retirement(
                    stage, document, player, row["cause"]["obligation_id"], reference
                )
            )
        stage.rules.party_keys[player].discard(row["key"])
        from server.gen1_party_codec import PartyCodec

        party = [
            PartyCodec(after["variant"]).validate_blob(bytes.fromhex(m["blob_hex"]))
            for m in after_roster["members"]
            if m["location"] == "party"
        ]
        stage.rules.party_size[player] = len(party)
        stage.rules.partner_blobs[player] = [
            {"slot": i, "key": m.key, "species_id": m.species_id, "level": m.level, "blob": m.raw}
            for i, m in enumerate(party)
        ]
        from server.gen1_memorial_runtime import schedule as memorial_schedule

        commands = memorial_schedule(document, event)
        extra, more = schedule(document, player, event)
        for p in ("a", "b"):
            commands[p].extend(extra[p])
        records.extend(more)
    else:
        raise JournalError("retirement command differs from its durable phase")
    if row["receipt_operation"] is not None:
        from server.retained_physical_record import retain

        compact, retained = retain(
            COMPONENT,
            record_key(player, row["acquisition_id"]),
            stage.journal_revision + 1,
            row,
            summary(row),
        )
        rows = document["components"][COMPONENT][player]
        index = next(
            i
            for i, current in enumerate(rows)
            if current["acquisition_id"] == row["acquisition_id"]
        )
        rows[index] = compact
        records.append(retained)
    else:
        records.append(
            {
                "namespace": COMPONENT,
                "key": record_key(player, row["acquisition_id"]),
                "value": copy.deepcopy(row),
            }
        )
    from server.gen1_faint_runtime import synchronize

    synchronize(stage, document)
    return runtime.journal.commit(
        player,
        operation,
        message,
        expected_revision=stage.journal_revision,
        state=document,
        commands=commands,
        result={"ack": "ACK"},
        records=records,
        acknowledgements=[
            {
                "player": player,
                "command_id": command["command_id"],
                "outcome": "ACK",
                "receipt": message["receipt"],
            }
        ],
    ).result


def verify_state(stage):
    from server.retained_physical_record import is_retained, validate_reference

    document = stage.document()
    entries = document["components"].get(COMPONENT, {})
    if not isinstance(entries, dict) or set(entries) - {"a", "b"}:
        raise JournalError("invalid retirement component")
    for player, rows in entries.items():
        if not isinstance(rows, list):
            raise JournalError("retirement entry list required")
        active = 0
        seen = set()
        for row in rows:
            retained = is_retained(row)
            expected_fields = SUMMARY_FIELDS | {"retained"} if retained else FIELDS
            if (
                not isinstance(row, dict)
                or set(row) != expected_fields
                or row["acquisition_id"] in seen
            ):
                raise JournalError("complete unique retirement entry required")
            seen.add(row["acquisition_id"])
            source = policy_source(document, player, row["cause"])
            if (
                row["key"] != source["key"]
                or row["reason"] != source["reason"]
                or row["key"] in stage.rules.party_keys[player]
            ):
                raise JournalError("retirement source, reason or unusable key differs")
            event_reference.validate(row["origin"])
            if retained:
                ref = row["retained"]
                validate_reference(ref)
                if ref["namespace"] != COMPONENT or ref["record_key"] != record_key(
                    player, row["acquisition_id"]
                ):
                    raise JournalError("retirement reference belongs to another lifecycle")
                _identifier(row["receipt_operation"])
                from server.frame_progress import identifier

                identifier(row["receipt_digest"], 64)
                continue
            if (row["observation_event"] is None) != (row["payload"] is None):
                raise JournalError("retirement preparation phase differs")
            if row["receipt_operation"] is None:
                active += 1
            else:
                _identifier(row["receipt_operation"])
                if row["payload"] is None or row["receipt_digest"] is None:
                    raise JournalError("retirement completion lacks exact image evidence")
            if row["payload"] is not None:
                p = row["payload"]
                expected = prepare(
                    p["before"],
                    row["key"],
                    identity=stage.rules.player_identity[player],
                    context_generation=p["context_generation"],
                    final_sha1=p["final_sha1"],
                    frame=p["frame"],
                    reserved_digest=p["reserved_digest"],
                    birth_box=p["birth_box"],
                )
                if any(p[k] != value for k, value in expected.items()):
                    raise JournalError("retirement prepared image changed")
        if active > 1:
            raise JournalError("retirement operations must serialize per cartridge")


def verify_journal(journal, stage):
    document = stage.document()
    entries = document["components"].get(COMPONENT, {})
    if not entries:
        return
    graves.verify_journal(journal, document)
    for player, rows in entries.items():
        for stored_row in rows:
            row = expand_entry(journal, stored_row)
            record = journal.record(COMPONENT, record_key(player, row["acquisition_id"]))
            if record is None or record.value != row:
                raise JournalError("retirement differs from its atomic record")
            origin = row["origin"]
            read = None
            for current in [*row["observations"], row["observation_event"]]:
                read = issued(journal, player, origin, read_body(row))
                if current is None:
                    break
                event = event_reference.resolve(journal, current)
                message = event.request
                if (
                    read["outcome"] != "ACK"
                    or message.get("command_id") != read["command_id"]
                    or read["receipt"] != message.get("receipt")
                    or event.result != {"ack": "ACK"}
                ):
                    raise JournalError("retirement read receipt differs")
                initial = document["components"]["gen1-initial-observations"][player]
                observation(
                    read, read["receipt"], document, player, initial["binding"], historical=True
                )
                origin = current
            if row["payload"] is None:
                if read["outcome"] is not None:
                    raise JournalError("pending retirement read was already acknowledged")
                continue
            initial = document["components"]["gen1-initial-observations"][player]
            graves.before_preparation(
                journal,
                row["payload"]["grave_head"],
                row["payload"]["source_anchor"],
                event_reference.resolve(journal, row["observation_event"]).revision,
            )
            if (
                preparation(
                    journal,
                    document,
                    player,
                    read,
                    read["receipt"],
                    initial["binding"],
                    historical=True,
                )
                != row["payload"]
            ):
                raise JournalError("retirement journal preparation differs from its source")
            write = issued(journal, player, row["observation_event"], write_body(row))
            if row["receipt_operation"] is None:
                if write["outcome"] is not None:
                    raise JournalError("unrecorded retirement completion")
                continue
            event = journal.event_snapshot(player, row["receipt_operation"])
            if (
                event is None
                or event.revision != record.revision
                or event.result != {"ack": "ACK"}
                or write["outcome"] != "ACK"
                or event.request.get("command_id") != write["command_id"]
                or event.request.get("receipt") != write["receipt"]
                or digest(write["receipt"]) != row["receipt_digest"]
            ):
                raise JournalError("retirement file completion lost its exact ACK")
            verify_receipt(
                write,
                write["receipt"],
                row["payload"],
                identity=stage.rules.player_identity[player],
            )


def verify_operation(player, command, evidence, document, binding):
    if (
        not isinstance(evidence, dict)
        or set(evidence)
        != {
            "schema",
            "command_id",
            "command_sequence",
            "context_generation",
            "final_sha1",
            "host",
            "checkpoint",
            "intent",
            "current",
            "phase",
        }
        or evidence["schema"] != EVIDENCE
    ):
        raise JournalError("complete held retirement evidence required")
    verify_owned_checkpoint(player, command, evidence, document, binding)
    row = entry_for(document, player, command["body"].get("acquisition_id"))
    if (
        row["receipt_operation"] is not None
        or row["payload"] is None
        or command["body"] != write_body(row)
        or evidence["intent"]
        != {"schema": "rby-retirement-intent-v1", "body_digest": digest(command["body"])}
        or document["components"].get(graves.COMPONENT, {}).get(player) is not None
        and document["components"][graves.COMPONENT][player] != row["payload"]["grave_head"]
    ):
        raise JournalError("retirement permit differs from its owned prepared phase")
    p = row["payload"]
    phase = evidence["phase"]
    if evidence["host"]["frame"] != p["frame"]:
        raise JournalError("retirement held frame changed after preparation")
    if phase == "retirement_repair":
        recover_point(evidence["current"], wire_payload(p))
    elif phase in ("acquisition_retire", "retirement_save"):
        if evidence["current"] != p["before" if phase == "acquisition_retire" else "after"]:
            raise JournalError("retirement current image differs")
    else:
        raise JournalError("unknown retirement permission phase")
    return VerifiedHeldWrite(
        command_scope(command, binding, phase=phase), digest(evidence), 1000, digest(document)
    )
