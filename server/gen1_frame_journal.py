"""Atomic storage for RBY frame reservations and held returns.

Private integration API: no network dispatch or default gameplay policy is
installed here. A generation controller supplies the independently verified
grant proof. Completed observations remain blocked until their rule settlement.
"""

import copy
from types import SimpleNamespace

from server import frame_progress
from server.durable_runtime import TIMEOUT
from server.execution_window import VerifiedExecutionWindow, issue
from server.gen1_frame_runtime import COMPONENT, complete, reserve, seed, validate_state
from server.protocol import digest
from server.protocol_journal import JournalError


def key(player):
    return digest({"component": COMPONENT, "player": player})[:32]


GRANTS = COMPONENT + "-grants"
RETURNS = COMPONENT + "-returns"


def _issue(window, proof):
    try:
        return issue(window, proof)
    except (TypeError, ValueError) as error:
        raise JournalError("invalid frame execution challenge") from error


def _checked_record(runtime, player, record):
    if record is None:
        raise JournalError("frame transition has lost its retained authority record")
    value = record.value
    if not isinstance(value, dict) or set(value) != {
        "operation_id",
        "request_digest",
        "result_digest",
        "previous",
        "entry",
        "proof",
    }:
        raise JournalError("complete frame accounting record required")
    event = runtime.journal.event_snapshot(player, value["operation_id"])
    if (
        event is None
        or event.revision != record.revision
        or digest(event.request) != value["request_digest"]
        or digest(event.result) != value["result_digest"]
    ):
        raise JournalError("frame ledger lacks its exact committed event")
    if event.command_ids and (
        event.request.get("event") != "frame_complete"
        or event.result.get("observations_settled") is not True
    ):
        raise JournalError("unsettled frame event published physical commands")
    return {**value, "message": event.request, "result": event.result}


def _grant_value(value):
    message = value["message"]
    if (
        not isinstance(message, dict)
        or set(message) != {"event", "window", "evidence"}
        or message["event"] != "frame_grant"
    ):
        raise JournalError("stored grant has an invalid request shape")
    try:
        proof = VerifiedExecutionWindow(**value["proof"])
    except (TypeError, ValueError) as error:
        raise JournalError("stored frame policy proof is invalid") from error
    if (
        proof.scope["operation_id"] != value["operation_id"]
        or proof.scope["phase"] != "ordinary"
        or proof.state_digest is None
        or proof.proof_digest != digest(message["evidence"])
        or proof.scope["operation_digest"]
        != digest({"event": "frame_grant", "evidence": message["evidence"]})
    ):
        raise JournalError("stored grant differs from its operation/evidence proof")
    previous = value["previous"]
    if (
        not isinstance(previous, dict)
        or set(previous) != {"ledger", "pending_observation"}
        or previous["pending_observation"] is not None
    ):
        raise JournalError("grant bypassed unsettled source observations")
    expected = {
        "ledger": frame_progress.reserve(previous["ledger"], proof),
        "pending_observation": None,
    }
    expected_result = {
        "ack": "ACK",
        "frame_window": _issue(message["window"], proof),
        "ordinary_execution": False,
    }
    if expected != value["entry"] or expected_result != value["result"]:
        raise JournalError("original frame grant does not reproduce its state/result")
    return value


def _original_grant(runtime, player, operation):
    record = runtime.journal.record(GRANTS, operation)
    value = _grant_value(_checked_record(runtime, player, record))
    if (
        value["operation_id"] != operation
        or len(runtime.journal.record_history(GRANTS, operation, limit=2)) != 1
    ):
        raise JournalError("frame grant authority record is not immutable")
    previous = value["previous"]
    if previous["ledger"]["sequence"]:
        predecessor = runtime.journal.record(RETURNS, previous["ledger"]["previous_digest"][:32])
        prior = _checked_record(runtime, player, predecessor)
        if (
            predecessor.revision >= record.revision
            or prior["entry"] != previous
            or prior["result"].get("observations_settled") is not True
            or prior["message"].get("event") not in {"frame_complete", "native_frame_return", "native_frame_handoff"}
        ):
            raise JournalError("frame grant lacks its settled predecessor return")
        if prior["message"].get("event") in {"native_frame_return", "native_frame_handoff"}:
            from server.gen1_native_frame_accounting import verify_frame_head
            verify_frame_head(runtime, runtime.journal.snapshot().state, player, prior)
    return record, value


def retained_return(journal, player, fingerprint, anchor):
    """Read an exact retained ordinary return and its original grant authority."""
    frame_progress.identifier(fingerprint, 64)
    record = journal.record(RETURNS, fingerprint[:32])
    view = SimpleNamespace(journal=journal)
    value = _checked_record(view, player, record)
    message = value['message']
    if message.get('event') in {'native_frame_return', 'native_frame_handoff'}:
        from server.gen1_native_frame_accounting import verify_frame_head, HISTORY, key
        verify_frame_head(view, journal.snapshot().state, player, value)
        native = journal.record(HISTORY, key(player, value['operation_id']))
        closed = native.value['entry']['closed']
        if digest(closed) != fingerprint or closed['grant']['anchor_digest'] != digest(anchor):
            raise JournalError('native retained frame range differs')
        return closed
    if message.get('event') != 'frame_complete' or value['result'].get('observations_settled') is not True:
        raise JournalError('retained frame was not settled')
    previous = value['previous']
    _, closed = frame_progress.complete(previous['ledger'], message['receipt'])
    if (digest(closed) != fingerprint or closed['grant']['anchor_digest'] != digest(anchor)
            or value['entry']['ledger']['previous_digest'] != fingerprint
            or value['result'].get('closed_frame_digest') != fingerprint):
        raise JournalError('historical frame range differs from its retained return')
    original, granted = _original_grant(view, player, closed['grant']['scope']['operation_id'])
    if original.revision >= record.revision or granted['entry'] != previous:
        raise JournalError('retained frame return lost its original grant')
    return closed


def verify_journal(runtime, document):
    validate_state(document)
    entries = document["components"].get(COMPONENT, {})
    for player in ("a", "b"):
        record = runtime.journal.record(COMPONENT, key(player))
        entry = entries.get(player)
        if (record is None) != (entry is None):
            raise JournalError("frame accounting differs from its atomic record")
        if record is None:
            continue
        value = _checked_record(runtime, player, record)
        if value["entry"] != entry:
            raise JournalError("frame ledger differs from its checked journal record")
        message = value["message"]
        if message.get("event") in {"native_frame_return", "native_frame_handoff"}:
            from server.gen1_native_frame_accounting import verify_frame_head
            verify_frame_head(runtime, document, player, value)
            continue
        work = copy.deepcopy(document)
        if value["previous"] is None:
            if message != {"event": "frame_enrollment"} or value["proof"] is not None:
                raise JournalError("invalid initial frame accounting record")
            del work["components"][COMPONENT][player]
            expected = seed(work, player)
            expected_result = {
                "ack": "ACK",
                "frame_anchor_digest": digest(expected["ledger"]["anchor"]),
                "ordinary_execution": False,
            }
        else:
            previous = value["previous"]
            work["components"][COMPONENT][player] = copy.deepcopy(previous)
            validate_state(work)
            if message.get("event") == "frame_grant":
                original, checked = _original_grant(runtime, player, value["operation_id"])
                if original.revision != record.revision or original.value != record.value:
                    raise JournalError("current grant differs from retained authority")
                expected, expected_result = checked["entry"], checked["result"]
            elif message.get("event") == "frame_complete":
                if set(message) != {"event", "receipt", "bundle"} or value["proof"] is not None:
                    raise JournalError("completion cannot issue frame authority")
                pending = previous["ledger"]["pending"]
                if pending is None:
                    raise JournalError("frame completion lost its pending grant")
                original, checked = _original_grant(
                    runtime, player, pending["scope"]["operation_id"]
                )
                if original.revision >= record.revision or checked["entry"] != previous:
                    raise JournalError("frame completion does not follow its original grant")
                closed = complete(work, player, message["receipt"], message["bundle"])
                expected = work["components"][COMPONENT][player]
                expected_result = {
                    "ack": "ACK",
                    "closed_frame_digest": digest(closed),
                    "ordinary_execution": False,
                }
                if value["result"].get("observations_settled") is True:
                    expected["pending_observation"] = None
                    expected_result["observations_settled"] = True
                    from server.event_reference import make

                    origin = make(player, value["operation_id"], message)
                    if message["bundle"]["inventory"] is not None:
                        inventory = (
                            document["components"]
                            .get("gen1-inventory-observations", {})
                            .get(player)
                        )
                        if (
                            inventory is None
                            or inventory["operation_id"] != value["operation_id"]
                            or inventory.get("frame_origin") != origin
                        ):
                            raise JournalError("settled frame lost its inventory effect record")
                        expected_result["inventory_transition_digest"] = digest(inventory)
                    if message["bundle"]["engine_signals"] is not None:
                        engine = document["components"].get("gen1-engine-signals", {}).get(player)
                        if (
                            engine is None
                            or engine["operation_id"] != value["operation_id"]
                            or engine.get("frame_origin") != origin
                        ):
                            raise JournalError("settled frame lost its engine effect record")
                        expected_result["engine_evidence_digest"] = digest(engine)
                    acquisition = document['components'].get('gen1-acquisition-settlement',{}).get(player)
                    if (message['bundle'].get('acquisitions') or 'acquisition_digest' in value['result']
                            or acquisition is not None and acquisition['operation_id']==value['operation_id']):
                        if acquisition is None or acquisition['operation_id']!=value['operation_id'] or acquisition.get('frame_origin')!=origin:
                            raise JournalError('settled frame lost its acquisition effect record')
                        expected_result['acquisition_digest']=digest(acquisition)
                        from server.gen1_static_lifecycle import COMPONENT as STATIC, record_key as static_key
                        from server.gen1_npc_exchange_runtime import COMPONENT as EXCHANGE, record_key as exchange_key
                        for field, namespace, component_key in (
                                ('static_digest', STATIC, static_key(player)),
                                ('exchange_digest', EXCHANGE, exchange_key(player))):
                            rows = runtime.journal.record_history(namespace, component_key,
                                after_revision=record.revision-1, limit=1)
                            if not rows or rows[0].revision != record.revision:
                                raise JournalError('settled frame lost its source lifecycle record')
                            expected_result[field] = digest(rows[0].value)
                    from server.gen1_wild_encounter_runtime import COMPONENT as WILD, record_key as wild_key
                    wild = runtime.journal.record_history(WILD, wild_key(), after_revision=record.revision-1, limit=1)
                    if wild and wild[0].revision == record.revision:
                        expected_result['wild_encounter_digest'] = digest(wild[0].value)
                    elif 'wild_encounter_digest' in value['result'] or any(row['kind'] in ('wild_begin','wild_end','capture')
                            for row in message['bundle'].get('acquisitions') or []):
                        raise JournalError('settled frame lost its encounter lifecycle record')
                    if any(row['kind'] == 'evolution' for row in message['bundle'].get('acquisitions') or []):
                        from server.gen1_evolution_runtime import COMPONENT as EVOLUTION, record_key as evolution_key
                        evolved = runtime.journal.record_history(EVOLUTION, evolution_key(player),
                            after_revision=record.revision-1, limit=1)
                        if not evolved or evolved[0].revision != record.revision:
                            raise JournalError('settled frame lost its evolution lifecycle record')
                        expected_result['evolution_digest'] = digest(evolved[0].value)
                    if message['bundle'].get('native_checkpoint') is not None:
                        native = document['components'].get('gen1-native-observations', {}).get(player)
                        if native is None or native['origin'] != origin:
                            raise JournalError('settled frame lost its native checkpoint observation')
                        expected_result['native_checkpoint_digest'] = digest(native)
            else:
                raise JournalError("unknown frame accounting transition")
        if expected != entry or expected_result != value["result"]:
            raise JournalError("frame accounting transition does not reproduce its state")


def _persist(
    runtime,
    stage,
    document,
    player,
    operation,
    message,
    previous,
    result,
    proof=None,
    *,
    commands=None,
    extra_records=(),
):
    entry = document["components"][COMPONENT][player]
    record = {
        "operation_id": operation,
        "request_digest": digest(message),
        "result_digest": digest(result),
        "previous": copy.deepcopy(previous),
        "entry": copy.deepcopy(entry),
        "proof": proof,
    }
    records = [{"namespace": COMPONENT, "key": key(player), "value": record}]
    if message["event"] == "frame_grant":
        if runtime.journal.record(GRANTS, operation) is not None:
            raise JournalError("frame grant identity already has retained authority")
        records.append({"namespace": GRANTS, "key": operation, "value": record})
    if message["event"] == "frame_complete":
        return_key = entry["ledger"]["previous_digest"][:32]
        if runtime.journal.record(RETURNS, return_key) is not None:
            raise JournalError("frame return already has retained provenance")
        records.append({"namespace": RETURNS, "key": return_key, "value": record})
    records.extend(extra_records)
    return runtime.journal.commit(
        player,
        operation,
        message,
        expected_revision=stage.journal_revision,
        state=document,
        commands=commands if commands is not None else {"a": [], "b": []},
        result=result,
        records=records,
    ).result


def enroll(runtime, player, operation):
    message = {"event": "frame_enrollment"}
    stage = runtime.state()
    document = stage.document()
    verify_journal(runtime, document)
    old = runtime.journal.event(player, operation, message)
    if old is not None:
        return old.result
    entry = seed(document, player)
    return _persist(
        runtime,
        stage,
        document,
        player,
        operation,
        message,
        None,
        {
            "ack": "ACK",
            "frame_anchor_digest": digest(entry["ledger"]["anchor"]),
            "ordinary_execution": False,
        },
    )


def grant(runtime, player, operation, message, proof):
    stage = runtime.state()
    document = stage.document()
    verify_journal(runtime, document)
    now = runtime._now()
    if (
        runtime._failed is not None
        or set(runtime.gate.sessions) != {"a", "b"}
        or set(runtime._control_seen) != {"a", "b"}
        or any(now - seen >= TIMEOUT for seen in runtime._control_seen.values())
    ):
        raise JournalError("fresh paired connections required for frame authority")
    admission = document["components"]["gen1-runtime"]["admissions"].get(player)
    binding = runtime.gate.sessions[player].metadata["control_binding"]
    if admission is None or admission["binding"] != {
        k: binding[k] for k in ("binding_digest", "context_generation")
    }:
        raise JournalError("frame authority differs from the current session owner")
    old = runtime.journal.event(player, operation, message)
    if old is not None:
        return old.result  # Same nonce/scope; this never restarts a client permit's deadline.
    if runtime.journal.pending_ids(player):
        raise JournalError('physical commands must finish before ordinary frame authority')
    if (
        not isinstance(message, dict)
        or set(message) != {"event", "window", "evidence"}
        or message["event"] != "frame_grant"
    ):
        raise JournalError("typed frame grant request required")
    if not isinstance(proof, VerifiedExecutionWindow) or proof.scope["operation_id"] != operation:
        raise JournalError("private frame proof must identify this exact operation")
    if proof.proof_digest != digest(message["evidence"]) or proof.scope[
        "operation_digest"
    ] != digest({"event": "frame_grant", "evidence": message["evidence"]}):
        raise JournalError("private frame proof differs from the request evidence")
    previous = copy.deepcopy(document["components"].get(COMPONENT, {}).get(player))
    window = _issue(message["window"], proof)
    reserve(document, player, proof)
    fields = {
        "scope": dict(proof.scope),
        "proof_digest": proof.proof_digest,
        "frames": proof.frames,
        "ttl_ms": proof.ttl_ms,
        "state_digest": proof.state_digest,
    }
    return _persist(
        runtime,
        stage,
        document,
        player,
        operation,
        message,
        previous,
        {"ack": "ACK", "frame_window": window, "ordinary_execution": False},
        fields,
    )


def returned(runtime, player, operation, message, *, settle_observations=False):
    stage = runtime.state()
    document = stage.document()
    verify_journal(runtime, document)
    old = runtime.journal.event(player, operation, message)
    if old is not None:
        return old.result
    if (
        not isinstance(message, dict)
        or set(message) != {"event", "receipt", "bundle"}
        or message["event"] != "frame_complete"
    ):
        raise JournalError("typed held frame completion required")
    previous = copy.deepcopy(document["components"].get(COMPONENT, {}).get(player))
    closed = complete(document, player, message["receipt"], message["bundle"])
    result = {"ack": "ACK", "closed_frame_digest": digest(closed), "ordinary_execution": False}
    commands = {"a": [], "b": []}
    records = []
    if settle_observations:
        from server.event_reference import make
        from server.gen1_engine_signal_runtime import stage_observation as stage_engine
        from server.gen1_inventory_observation import stage_observation as stage_inventory

        origin = make(player, operation, message)
        engine = message["bundle"]["engine_signals"]
        if engine is not None:
            proposed = stage_engine(
                runtime,
                stage,
                document,
                player,
                operation,
                {"event": "engine_signals", "payload": engine},
                frame_origin=origin,
                frame_request=message,
            )
            records.extend(proposed["records"])
            for recipient in ("a", "b"):
                commands[recipient].extend(proposed["commands"][recipient])
            result["engine_evidence_digest"] = proposed["result"]["engine_evidence_digest"]
        if message["bundle"]["inventory"] is not None:
            old_inventory = (
                document["components"].get("gen1-inventory-observations", {}).get(player)
            )
            initial = document["components"]["gen1-initial-observations"][player]
            inventory_request = {
                "event": "inventory_observation",
                "payload": {
                    "sequence": old_inventory["sequence"] + 1 if old_inventory else 1,
                    "previous_operation_id": old_inventory["operation_id"]
                    if old_inventory
                    else initial["operation_id"],
                    "observation": message["bundle"]["inventory"],
                },
            }
            proposed = stage_inventory(
                runtime,
                stage,
                document,
                player,
                operation,
                inventory_request,
                frame_origin=origin,
                frame_request=message,
            )
            records.extend(proposed["records"])
            for recipient in ("a", "b"):
                commands[recipient].extend(proposed["commands"][recipient])
            result["inventory_transition_digest"] = proposed["result"][
                "inventory_transition_digest"
            ]
        from server.gen1_frame_acquisitions import stage as stage_acquisitions

        acquisition = stage_acquisitions(runtime,stage,document,player,operation,message,closed)
        if acquisition is not None:
            records.extend(acquisition['records'])
            for recipient in ('a','b'):
                commands[recipient].extend(acquisition['commands'][recipient])
            result['acquisition_digest']=acquisition['result']['acquisition_digest']
            result['static_digest']=acquisition['result']['static_digest']
            result['exchange_digest']=acquisition['result']['exchange_digest']
            if 'evolution_digest' in acquisition['result']:
                result['evolution_digest'] = acquisition['result']['evolution_digest']
        from server.gen1_wild_encounter_runtime import stage as stage_encounters
        encounter = stage_encounters(runtime, stage, document, player, operation, message,
                                     frame_origin=origin, frame_request=message)
        if encounter is not None:
            records.extend(encounter['records'])
            for recipient in ('a', 'b'):
                commands[recipient].extend(encounter['commands'][recipient])
            result['wild_encounter_digest'] = encounter['result']['wild_encounter_digest']
        from server.gen1_storage_runtime import stage as stage_storage
        storage = stage_storage(runtime, stage, document, player, operation, message)
        records.extend(storage['records'])
        for recipient in ('a', 'b'):
            commands[recipient].extend(storage['commands'][recipient])
        result["observations_settled"] = True
        from server.gen1_native_observation import stage as stage_native_checkpoint
        native = stage_native_checkpoint(document, player, operation, message)
        if native is not None:
            records.append(native['record'])
            result['native_checkpoint_digest'] = digest(native['entry'])
        document["components"][COMPONENT][player]["pending_observation"] = None
    return _persist(
        runtime,
        stage,
        document,
        player,
        operation,
        message,
        previous,
        result,
        commands=commands,
        extra_records=records,
    )
