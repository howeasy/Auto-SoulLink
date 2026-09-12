"""Durable native frame loans against the ordinary owner's anchored ledger.

Control integration must persist_grant after native verification and BEFORE
delivery. A native_frame_return follows the command's already-verified ACK.
The first return retains borrowed ownership. Final handoff validates the exact
post-source and stages inventory/native observations before clearing that hold
atomically. Frame counts alone never authorize ordinary gameplay.
"""

import copy
from types import SimpleNamespace

from server import frame_progress
from server.execution_window import VerifiedExecutionWindow, issue
from server.gen1_bootstrap_receipt import validate as validate_bootstrap
from server.protocol import digest
from server.protocol_journal import JournalError

COMPONENT = "gen1-native-frame-accounting"
HISTORY = COMPONENT + "-events"
RETURN_SCHEMA = "rby-native-frame-return-v1"
# The ordinary baseline ledger a native loan borrows against. The frame-credit loop that used
# to seed (frame_enrollment) and advance (frame_complete) it is retired; free-run observation
# (gen1_observation_runtime) keeps no ledger, so only a handed-back loan writes this now.
FRAMES = "gen1-frame-progress"
FRAME_RETURNS = FRAMES + "-returns"
BOOTSTRAP = "gen1-new-game-bootstrap"
COMMANDS = {
    "native_receptionist",
    "native_trade_prompt",
    "native_trade_prepare",
    "native_trade_commit",
    "native_trade_release",
    "native_trade_abort",
}
EVENTS = {
    "native_receptionist": "command_ack",
    "native_trade_prompt": "trade_decision",
    "native_trade_prepare": "trade_ready",
    "native_trade_commit": "trade_verified",
    "native_trade_release": "trade_ack",
    "native_trade_abort": "trade_ack",
}


def key(player, operation=None):
    return digest({"component": COMPONENT, "player": player, "operation": operation})[:32]


def borrowed(document, player):
    entry = document["components"].get(COMPONENT, {}).get(player)
    return entry is not None and entry["phase"] == "borrowed"


def _handed_back_predecessor(journal, player, baseline):
    """The loan this baseline was handed back from, when the ordinary ledger retains one.

    The frame-credit loop used to record an inventory checkpoint between two loans, so one
    loan's chain always covered an attribution interval; without it the walk follows the
    retained ordinary return of the previous handoff instead.
    """
    if not baseline["ledger"]["sequence"]:
        return None
    retained = journal.record(FRAME_RETURNS, baseline["ledger"]["previous_digest"][:32])
    if retained is None:
        return None
    head, _ = _checked_event(journal, player, retained)
    row, _ = _checked_event(journal, player, journal.record(HISTORY, key(player, head["operation_id"])))
    if row["entry"]["phase"] != "handed_back":
        raise JournalError("native loan predecessor was not handed back")
    return row["entry"]


def completed_commands(journal, player, low, high):
    """Checked native command returns in this loan; no full points duplicated in state."""
    record = journal.record(COMPONENT, key(player))
    if record is None:
        return []
    current, _ = _checked_event(journal, player, record)
    entry, grants, returns, seen = current["entry"], {}, [], set()
    while entry is not None:
        operation = entry["head"]["operation_id"]
        if operation in seen:
            raise JournalError("native attribution history cycle")
        seen.add(operation)
        row, event = _checked_event(
            journal, player, journal.record(HISTORY, key(player, operation))
        )
        if row["entry"] != entry:
            raise JournalError("native attribution history differs")
        if event.request.get("event") == "native_frame_grant":
            command_id = event.request["evidence"]["command_id"]
            grants[command_id] = event.request["evidence"]["native"]
        elif event.request.get("event") == "native_frame_return" and event.revision <= high:
            payload = event.request["payload"]
            command, ack = _terminal(journal, player, payload)
            if low < ack.revision <= high:
                returns.append(
                    (ack.revision, command["body"]["cmd"], ack, command, {"native_return": payload})
                )
        entry = row["previous"]
        if entry is None:
            entry = _handed_back_predecessor(journal, player, row["entry"]["baseline"])
    for _revision, _kind, _event, command, source in returns:
        source["native_initial"] = grants.get(command["command_id"])
    return returns


def _host(host, initial, progress):
    if not isinstance(host, dict) or set(host) != {
        "owner_id",
        "capability_id",
        "process_id",
        "frame",
        "steps",
        "held",
        "bounded",
        "failed",
    }:
        raise JournalError("complete borrowed native host evidence required")
    owner = initial["observation"]["host"]
    if (
        any(host[name] != owner[name] for name in ("owner_id", "capability_id", "process_id"))
        or type(host["process_id"]) is not int
        or host["held"] is not True
        or host["bounded"] is not True
        or host["failed"] is not False
    ):
        raise JournalError("native frame loan changed physical owner")
    frame_progress.integer(host["frame"])
    frame_progress.integer(host["steps"])
    if host["frame"] != progress["anchor"]["frame"] + host["steps"]:
        raise JournalError("native host count differs from the ordinary physical anchor")


def _close(progress, host, observation_digest):
    pending = progress["pending"]
    if pending is None:
        if host["frame"] != progress["frame"] or host["steps"] != progress["steps"]:
            raise JournalError("native frames advanced without an outstanding grant")
        return copy.deepcopy(progress), None
    receipt = {
        "schema": frame_progress.RECEIPT,
        "sequence": pending["sequence"],
        "scope": pending["scope"],
        "before": pending["before"],
        "after": host["frame"],
        "steps": host["frame"] - pending["before"],
        "observations_digest": observation_digest,
    }
    return frame_progress.complete(progress, receipt)


def validate_state(document):
    entries = document["components"].get(COMPONENT, {})
    if not isinstance(entries, dict) or set(entries) - {"a", "b"}:
        raise JournalError("invalid native frame loan component")
    for player, entry in entries.items():
        if not isinstance(entry, dict) or set(entry) != {
            "baseline",
            "progress",
            "phase",
            "head",
            "challenge",
            "closed",
            "command_id",
            "offered",
            "accepted",
            "seen",
        }:
            raise JournalError("complete native frame loan required")
        if entry["phase"] not in ("borrowed", "handed_back"):
            raise JournalError("unknown native frame loan phase")
        baseline = entry["baseline"]
        if (
            not isinstance(baseline, dict)
            or set(baseline) != {"ledger", "pending_observation"}
            or baseline["pending_observation"] is not None
        ):
            raise JournalError("native loan requires a settled ordinary baseline")
        frame_progress.validate(baseline["ledger"])
        progress = frame_progress.validate(entry["progress"])
        if (
            baseline["ledger"]["pending"] is not None
            or progress["anchor"] != baseline["ledger"]["anchor"]
            or progress["frame"] < baseline["ledger"]["frame"]
        ):
            raise JournalError("native loan differs from its ordinary anchor")
        offered = entry["offered"]
        if offered is not None:
            if not isinstance(offered, dict) or set(offered) != {
                "challenge",
                "proof",
                "host",
                "revision",
            }:
                raise JournalError("complete offered native renewal required")
            frame_progress.identifier(offered["challenge"])
            frame_progress.integer(offered["revision"], 1)
            try:
                VerifiedExecutionWindow(**offered["proof"])
            except (TypeError, ValueError) as error:
                raise JournalError("invalid offered native renewal") from error
        frame_progress.integer(entry["seen"])
        frame_progress.identifier(entry["challenge"])
        frame_progress.identifier(entry["command_id"])
        if not isinstance(entry["head"], dict) or set(entry["head"]) != {
            "operation_id",
            "revision",
        }:
            raise JournalError("native loan needs its committed head reference")
        frame_progress.identifier(entry["head"]["operation_id"])
        frame_progress.integer(entry["head"]["revision"], 1)
        if entry["closed"] is not None:
            frame_progress.verify_closed(entry["closed"], anchor=progress["anchor"])
        ordinary = document["components"].get(FRAMES, {}).get(player)
        if entry["phase"] == "borrowed" and ordinary != baseline:
            raise JournalError("ordinary ledger moved while native execution owns it")


def _activate(entry, acceptance, initial):
    """Close the old range at RESPONSE acceptance, not request observation time."""
    offered = entry["offered"]
    if offered is None:
        if acceptance != entry["accepted"]:
            raise JournalError("native acceptance differs from its accounted boundary")
        return
    if (
        not isinstance(acceptance, dict)
        or set(acceptance) != {"schema", "challenge", "host"}
        or acceptance["schema"] != "rby-native-grant-acceptance-v1"
        or acceptance["challenge"] != offered["challenge"]
    ):
        raise JournalError("offered native renewal needs its exact response boundary")
    boundary = acceptance["host"]
    _host(boundary, initial, entry["progress"])
    if boundary["frame"] < offered["host"]["frame"] or boundary["frame"] < entry["seen"]:
        raise JournalError("native grant acceptance predates its request observation")
    progress, closed = _close(entry["progress"], boundary, digest(acceptance))
    proof = VerifiedExecutionWindow(**offered["proof"])
    entry.update(
        progress=frame_progress.reserve(progress, proof),
        closed=closed,
        accepted=copy.deepcopy(acceptance),
        offered=None,
        seen=boundary["frame"],
    )


def _prefix(entry, host, initial):
    _host(host, initial, entry["progress"])
    if host["frame"] < entry["seen"]:
        raise JournalError("native observed consumption moved backwards")
    _close(entry["progress"], host, digest(host))  # Validate without retiring the active grant.
    entry["seen"] = host["frame"]


def _grant_transition(document, player, request, response, evidence, proof, *, operation, revision):
    entries = document["components"].setdefault(COMPONENT, {})
    old = entries.get(player)
    entry = copy.deepcopy(old) if old and old["phase"] == "borrowed" else None
    if entry is None:
        baseline = document["components"].get(FRAMES, {}).get(player)
        if (
            baseline is None
            or baseline["ledger"]["pending"] is not None
            or baseline["pending_observation"] is not None
        ):
            raise JournalError("native frames require a settled ordinary handoff")
        entry = {
            "baseline": copy.deepcopy(baseline),
            "progress": copy.deepcopy(baseline["ledger"]),
            "phase": "borrowed",
            "head": None,
            "challenge": None,
            "closed": None,
            "command_id": None,
            "offered": None,
            "accepted": None,
            "seen": baseline["ledger"]["frame"],
        }
        old = None
    initial = document["components"]["gen1-initial-observations"][player]
    _activate(entry, evidence.get("accounting"), initial)
    command_id = proof.scope["operation_id"]
    if entry["progress"]["pending"] is not None and entry["command_id"] != command_id:
        raise JournalError("next native command requires the previous frame-return ACK")
    _prefix(entry, evidence["host"], initial)
    try:
        if issue(request, proof) != response:
            raise JournalError("native frame response differs from its verified policy")
    except (TypeError, ValueError) as error:
        raise JournalError("invalid native frame challenge") from error
    if proof.proof_digest != digest(evidence) or proof.scope["phase"] == "ordinary":
        raise JournalError("native frame policy evidence differs")
    fields = {
        "scope": dict(proof.scope),
        "proof_digest": proof.proof_digest,
        "frames": proof.frames,
        "ttl_ms": proof.ttl_ms,
        "state_digest": proof.state_digest,
    }
    entry.update(
        offered={
            "challenge": request["challenge"],
            "proof": fields,
            "host": copy.deepcopy(evidence["host"]),
            "revision": revision,
        },
        challenge=request["challenge"],
        command_id=command_id,
        head={"operation_id": operation, "revision": revision},
    )
    entries[player] = entry
    validate_state(document)
    return old, entry


def _proof_command(journal, document, player, proof, evidence):
    from server.operation_scope import command_scope

    command = journal.command(player, proof.scope["operation_id"])
    kind = command["body"].get("cmd")
    expected_phase = (
        "native_trade_prepare_save"
        if kind == "native_trade_prepare" and evidence.get("native", {}).get("phase") == "full_save"
        else kind
    )
    binding = {name: proof.scope[name] for name in ("context_generation", "binding_digest")}
    initial = document["components"]["gen1-initial-observations"][player]
    if (
        kind not in COMMANDS
        or proof.scope["phase"] != expected_phase
        or dict(proof.scope) != command_scope(command, binding, phase=expected_phase)
        or evidence.get("command_id") != command["command_id"]
        or type(evidence.get("command_sequence")) is not int
        or evidence["command_sequence"] != command["command_sequence"]
        or evidence.get("context_generation") != initial["binding"]["context_generation"]
        or evidence.get("final_sha1")
        != initial["metadata"]["gen1_metadata"]["cartridge"]["final_rom_sha1"]
    ):
        raise JournalError("native frame proof differs from its exact admitted command")


def _checked_event(journal, player, record):
    if record is None:
        raise JournalError("native frame provenance record is missing")
    value = record.value
    if not isinstance(value, dict) or set(value) != {
        "operation_id",
        "request_digest",
        "result_digest",
        "previous",
        "entry",
        "proof",
    }:
        raise JournalError("complete native frame provenance record required")
    event = journal.event_snapshot(player, value["operation_id"])
    if (
        event is None
        or event.revision != record.revision
        or event.command_ids
        or digest(event.request) != value["request_digest"]
        or digest(event.result) != value["result_digest"]
    ):
        raise JournalError("native frame provenance lost its exact event")
    return value, event


def _terminal(journal, player, payload):
    event = journal.event_snapshot(player, payload["receipt_operation_id"])
    if event is None:
        raise JournalError("native frame return lacks its committed command receipt")
    command = journal.command(player, payload["command_id"])
    body = command["body"]
    if (
        body.get("cmd") not in COMMANDS
        or command["outcome"] != "ACK"
        or type(payload["command_sequence"]) is not int
        or payload["command_sequence"] != command["command_sequence"]
        or event.request.get("event") != EVENTS[body["cmd"]]
        or event.request.get("command_id") != command["command_id"]
        or event.request.get("command_sequence") != command["command_sequence"]
        or event.request.get("receipt") != command["receipt"]
        or payload["receipt_digest"] != digest(command["receipt"])
        or event.result.get("ack") != "ACK"
    ):
        raise JournalError("native frame return differs from the validated command ACK")
    return command, event


def _post_source(journal, player, command, source):
    """Bind the full supplied point to every available validated native footprint.

    Unmodeled source fields remain explicit gaps during handoff observation
    settlement. They are not silently attributed to the native mutation.
    """
    receipt = command["receipt"]
    from server.gen1_full_save import SYMBOLS, matches_checkpoint

    if "checkpoint" in receipt:
        matches_checkpoint(source, receipt["checkpoint"])
        return
    after = receipt.get("after")
    if not isinstance(after, dict) or source["fields"]["party"] != after.get("party_storage_hex"):
        raise JournalError("native handoff party differs from its command receipt")
    symbols = SYMBOLS["pokeyellow" if source["variant"] == "yellow" else "pokered"]
    main = bytes.fromhex(source["fields"]["main"])
    if main[symbols["wCurMap"] - symbols["wMainDataStart"]] != after.get("map"):
        raise JournalError("native handoff map differs from its receipt")
    if command["body"]["cmd"] == "native_trade_release":
        original = journal.command(player, receipt["native_command_id"])
        saved = original["receipt"]
        if (
            original["outcome"] != "ACK"
            or not isinstance(saved, dict)
            or saved.get("schema") != "rby-file-backed-v1"
            or saved.get("native", {}).get("after") != after
            or saved.get("save_image_hex") != source["cart_hex"]
            or after.get("save_name_hex") != source["fields"]["name"]
        ):
            raise JournalError("native handoff differs from the verified complete trade file")
        start = symbols["wPokedexOwned"] - symbols["wMainDataStart"]
        if main[start : start + 38].hex().upper() != after.get("dex_hex"):
            raise JournalError("native handoff dex differs from the verified trade")
    elif command["body"]["cmd"] == "native_trade_abort":
        import hashlib

        if hashlib.sha256(source["cart_hex"].encode("ascii")).hexdigest() != after.get(
            "cart_digest"
        ):
            raise JournalError("native prompt closure changed its verified cartridge image")
    else:
        raise JournalError("native command has no qualified ordinary handoff footprint")


def _return_transition(journal, document, player, message, *, operation, revision, handoff):
    if (
        not isinstance(message, dict)
        or set(message) != {"event", "payload"}
        or message["event"] not in {"native_frame_return", "native_frame_handoff"}
    ):
        raise JournalError("typed native frame return required")
    payload = message["payload"]
    if (
        not isinstance(payload, dict)
        or set(payload)
        != {
            "schema",
            "command_id",
            "command_sequence",
            "receipt_operation_id",
            "receipt_digest",
            "grant_challenge",
            "host",
            "inventory",
            "checkpoint",
            "native_checkpoint",
            "ledger_sequence",
            "accounting",
        }
        or payload["schema"] != RETURN_SCHEMA
    ):
        raise JournalError("complete native frame return evidence required")
    frame_progress.identifier(payload["receipt_operation_id"])
    frame_progress.identifier(payload["receipt_digest"], 64)
    entry = document["components"].get(COMPONENT, {}).get(player)
    if entry is None or entry["phase"] != "borrowed":
        raise JournalError("native frame return has no borrowed ownership")
    previous = copy.deepcopy(entry)
    entry = copy.deepcopy(entry)
    document["components"][COMPONENT][player] = entry
    initial = document["components"]["gen1-initial-observations"][player]
    closing = entry["progress"]["pending"] is not None or entry["offered"] is not None
    if message["event"] == "native_frame_handoff":
        if not handoff or closing:
            raise JournalError("final native handoff requires an acknowledged frame return")
        previous_return = journal.event_snapshot(player, entry["head"]["operation_id"])
        if (
            previous_return is None
            or previous_return.request != {"event": "native_frame_return", "payload": payload}
            or entry["closed"] is None
        ):
            raise JournalError("native handoff changed its exact terminal return evidence")
    elif not closing:
        # An idle abort can finish without a frame window. It cannot move the
        # borrowed physical point or manufacture new credits.
        readonly = journal.command(player, payload["command_id"])
        prior_return = journal.event_snapshot(player, entry["head"]["operation_id"])
        if (
            readonly["body"].get("cmd") != "native_trade_abort"
            or not isinstance(readonly["receipt"], dict)
            or readonly["receipt"].get("schema") != "rby-trade-abort-v1"
            or prior_return is None
            or prior_return.request.get("event") != "native_frame_return"
            or prior_return.request["payload"]["inventory"] != payload["inventory"]
        ):
            raise JournalError("ungranted native return is not an unchanged readonly abort")
    if (
        payload["grant_challenge"] != entry["challenge"]
        or closing
        and payload["command_id"] != entry["command_id"]
    ):
        raise JournalError("native return belongs to another grant or command")
    _activate(entry, payload["accounting"], initial)
    command, acknowledgement = _terminal(journal, player, payload)
    if (
        not acknowledgement.revision < revision
        or closing
        and entry["head"]["revision"] > acknowledgement.revision
    ):
        raise JournalError("native command ACK does not follow its granted execution")
    initial = document["components"]["gen1-initial-observations"][player]
    _host(payload["host"], initial, entry["progress"])
    if (
        type(payload["ledger_sequence"]) is not int
        or payload["ledger_sequence"] != entry["progress"]["sequence"]
    ):
        raise JournalError("native return sequence differs from issued grants")
    from server.gen1_initial_observation import validate

    validate(payload["inventory"], initial["metadata"], initial["binding"])
    if (
        payload["inventory"]["host"] != initial["observation"]["host"]
        or payload["inventory"]["frame"] != payload["host"]["frame"]
    ):
        raise JournalError("native post-inventory differs from the held physical boundary")
    progress, closed = _close(entry["progress"], payload["host"], digest(message))
    if closed is None:
        closed = copy.deepcopy(entry["closed"])
    entry.update(
        progress=progress,
        closed=closed,
        seen=payload["host"]["frame"],
        command_id=payload["command_id"],
        head={"operation_id": operation, "revision": revision},
    )
    if handoff:
        if document["active_trade"] is not None or command["body"]["cmd"] not in {
            "native_trade_release",
            "native_trade_abort",
            "native_receptionist",
        }:
            raise JournalError("native transaction still owns the ordinary return")
        from server.gen1_held_faint import verify_checkpoint

        verify_checkpoint(payload["checkpoint"], payload["inventory"]["source"]["variant"])
        from server.gen1_native_observation import validate as validate_native_checkpoint

        validate_native_checkpoint(payload["native_checkpoint"], payload["inventory"], initial)
        _post_source(journal, player, command, payload["inventory"]["source"])
        document["components"][FRAMES][player] = {
            "ledger": copy.deepcopy(progress),
            "pending_observation": {
                "closed": copy.deepcopy(closed),
                "bundle_digest": closed["receipt"]["observations_digest"],
            },
        }
        entry["phase"] = "handed_back"
    validate_state(document)
    return previous, entry


def _persist(
    runtime,
    stage,
    document,
    player,
    operation,
    message,
    previous,
    entry,
    result,
    proof=None,
    *,
    handoff=False,
    extra_records=(),
    commands=None,
):
    record = {
        "operation_id": operation,
        "request_digest": digest(message),
        "result_digest": digest(result),
        "previous": previous,
        "entry": copy.deepcopy(entry),
        "proof": proof,
    }
    if runtime.journal.record(HISTORY, key(player, operation)) is not None:
        raise JournalError("native frame event identity already has retained provenance")
    records = [
        {"namespace": COMPONENT, "key": key(player), "value": record},
        {"namespace": HISTORY, "key": key(player, operation), "value": record},
    ]
    if handoff:
        head = {
            **record,
            "previous": previous["baseline"],
            "entry": copy.deepcopy(document["components"][FRAMES][player]),
            "proof": None,
        }
        records += [
            {"namespace": FRAMES, "key": frame_key(player), "value": head},
            {"namespace": FRAME_RETURNS, "key": entry["progress"]["previous_digest"][:32], "value": head},
        ]
    records.extend(extra_records)
    return runtime.journal.commit(
        player,
        operation,
        message,
        expected_revision=stage.journal_revision,
        state=document,
        commands=commands or {"a": [], "b": []},
        result=result,
        records=records,
    ).result


def persist_grant(runtime, player, request, response, evidence):
    """Called after issue_for_control succeeds, before delivering its response."""
    if player not in runtime.journal.snapshot().state["components"].get(FRAMES, {}):
        # No frame ledger (free_service): the window is retained by gen1_native_windows instead.
        from server.gen1_native_windows import persist

        return persist(runtime, player, request, response, evidence)
    operation = request["challenge"]
    message = {
        "event": "native_frame_grant",
        "request": request,
        "grant": response,
        "evidence": evidence,
    }
    old = runtime.journal.event(player, operation, message)
    if old is not None:
        return old.result
    stage = runtime.state()
    document = stage.document()
    policy = runtime.verify_operation_execution
    from server.gen1_native_execution import NativeExecutionPolicy

    if not isinstance(policy, NativeExecutionPolicy) or policy.runtime is not runtime:
        raise JournalError("owned native execution verifier required before frame publication")
    binding = runtime.gate.sessions[player].metadata["control_binding"]
    proof = policy.published.get(
        (player, response["scope"]["operation_id"], binding["binding_digest"])
    )
    if not isinstance(proof, VerifiedExecutionWindow) or proof.state_digest != digest(document):
        raise JournalError("native grant lost its independently verified state binding")
    _proof_command(runtime.journal, document, player, proof, evidence)
    previous, entry = _grant_transition(
        document,
        player,
        request,
        response,
        evidence,
        proof,
        operation=operation,
        revision=stage.journal_revision + 1,
    )
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
        entry,
        {"ack": "ACK", "native_frame_grant": request["challenge"], "ordinary_execution": False},
        fields,
    )


def returned(runtime, player, operation, message, *, handoff=False):
    old = runtime.journal.event(player, operation, message)
    if old is not None:
        if old.result.get("native_handoff") is not handoff:
            raise JournalError("native return replay changed its handoff policy")
        return old.result
    stage = runtime.state()
    document = stage.document()
    from server.admission_context import same_admitted_context

    initial = document["components"]["gen1-initial-observations"][player]
    if not same_admitted_context(initial["metadata"], runtime.gate.sessions[player].metadata):
        raise JournalError("native frame return belongs to a replaced physical context")
    previous, entry = _return_transition(
        runtime.journal,
        document,
        player,
        message,
        operation=operation,
        revision=stage.journal_revision + 1,
        handoff=handoff,
    )
    result = {
        "ack": "ACK",
        "native_handoff": handoff,
        "native_frame_digest": digest(entry["progress"]),
        "ordinary_execution": False,
        "observations_settled": False,
    }
    records = []
    if handoff:
        from server import event_reference
        from server.gen1_inventory_observation import stage_observation
        from server.gen1_native_observation import stage as stage_native

        old_inventory = document["components"].get("gen1-inventory-observations", {}).get(player)
        initial = document["components"]["gen1-initial-observations"][player]
        request = {
            "event": "inventory_observation",
            "payload": {
                "sequence": old_inventory["sequence"] + 1 if old_inventory else 1,
                "previous_operation_id": old_inventory["operation_id"]
                if old_inventory
                else initial["operation_id"],
                "observation": message["payload"]["inventory"],
            },
        }
        staged = stage_observation(
            runtime,
            stage,
            document,
            player,
            operation,
            request,
            frame_origin=event_reference.make(player, operation, message),
            frame_request=message,
        )
        if any(staged["commands"].values()):
            raise JournalError("native handoff unexpectedly created a physical command")
        records.extend(staged["records"])
        native = stage_native(document, player, operation, message)
        if native is None:
            raise JournalError("native handoff lost its qualified post-checkpoint")
        records.append(native["record"])
        result.update(
            observations_settled=True,
            closed_frame_digest=digest(entry["closed"]),
            inventory_transition_digest=staged["result"]["inventory_transition_digest"],
            native_checkpoint_digest=digest(native["entry"]),
        )
        document["components"][FRAMES][player]["pending_observation"] = None
    return _persist(
        runtime,
        stage,
        document,
        player,
        operation,
        message,
        previous,
        entry,
        result,
        handoff=handoff,
        extra_records=records,
    )


def verify_journal(runtime, document):
    validate_state(document)
    for player, current in document["components"].get(COMPONENT, {}).items():
        record = runtime.journal.record(COMPONENT, key(player))
        value, _ = _checked_event(runtime.journal, player, record)
        if value["entry"] != current:
            raise JournalError("native frame component differs from its checked head")
        _audit_chain(runtime, document, player, current)


def _audit_chain(runtime, document, player, current):
    expected = current
    seen = set()
    while expected is not None:
        head = expected["head"]
        if head["operation_id"] in seen:
            raise JournalError("native frame provenance cycle")
        seen.add(head["operation_id"])
        record = runtime.journal.record(HISTORY, key(player, head["operation_id"]))
        value, event = _checked_event(runtime.journal, player, record)
        if record.revision != head["revision"] or value["entry"] != expected:
            raise JournalError("native frame history differs from its predecessor")
        work = copy.deepcopy(document)
        prior = value["previous"]
        if prior is None:
            work["components"].setdefault(COMPONENT, {}).pop(player, None)
            work["components"][FRAMES][player] = copy.deepcopy(expected["baseline"])
        else:
            work["components"][COMPONENT][player] = copy.deepcopy(prior)
            work["components"][FRAMES][player] = copy.deepcopy(prior["baseline"])
            if prior["head"]["revision"] >= record.revision:
                raise JournalError("native frame history moved backwards")
        message = event.request
        if message.get("event") == "native_frame_grant":
            try:
                proof = VerifiedExecutionWindow(**value["proof"])
            except (TypeError, ValueError) as error:
                raise JournalError("stored native policy proof is invalid") from error
            _proof_command(runtime.journal, work, player, proof, message["evidence"])
            _, checked = _grant_transition(
                work,
                player,
                message["request"],
                message["grant"],
                message["evidence"],
                proof,
                operation=value["operation_id"],
                revision=record.revision,
            )
            result = {
                "ack": "ACK",
                "native_frame_grant": message["request"]["challenge"],
                "ordinary_execution": False,
            }
        elif message.get("event") in {"native_frame_return", "native_frame_handoff"}:
            handoff = event.result.get("native_handoff")
            if type(handoff) is not bool or value["proof"] is not None:
                raise JournalError("invalid native frame return policy")
            if handoff:
                work["active_trade"] = None  # Historical completion preceded later transactions.
            _, checked = _return_transition(
                runtime.journal,
                work,
                player,
                message,
                operation=value["operation_id"],
                revision=record.revision,
                handoff=handoff,
            )
            result = {
                "ack": "ACK",
                "native_handoff": handoff,
                "native_frame_digest": digest(checked["progress"]),
                "ordinary_execution": False,
                "observations_settled": False,
            }
            if handoff:
                from server import event_reference
                from server.gen1_inventory_observation import (
                    COMPONENT as INV,
                    record_key as inventory_key,
                    verify_entry,
                )
                from server.gen1_native_observation import COMPONENT as NATIVE, key as native_key

                inv = runtime.journal.record_history(
                    INV, inventory_key(player), after_revision=record.revision - 1, limit=1
                )
                point = runtime.journal.record_history(
                    NATIVE, native_key(player), after_revision=record.revision - 1, limit=1
                )
                if (
                    not inv
                    or not point
                    or inv[0].revision != record.revision
                    or point[0].revision != record.revision
                ):
                    raise JournalError("native handoff lost its atomic observation records")
                initial = document["components"]["gen1-initial-observations"][player]
                verify_entry(inv[0].value, initial)
                origin = event_reference.make(player, value["operation_id"], message)
                if (
                    inv[0].value.get("frame_origin") != origin
                    or inv[0].value["observation"] != message["payload"]["inventory"]
                    or point[0].value.get("origin") != origin
                    or point[0].value.get("party")
                    != message["payload"]["native_checkpoint"]["party"]
                ):
                    raise JournalError("native handoff observations differ from their event")
                result.update(
                    observations_settled=True,
                    closed_frame_digest=digest(checked["closed"]),
                    inventory_transition_digest=digest(inv[0].value),
                    native_checkpoint_digest=digest(point[0].value),
                )

        else:
            raise JournalError("unknown native frame provenance event")
        if checked != expected or event.result != result:
            raise JournalError("native frame transition does not reproduce its committed state")
        expected = prior


def verify_frame_head(runtime, document, player, value):
    """Audit a current OR historical native predecessor using its immutable record."""
    record = runtime.journal.record(HISTORY, key(player, value["operation_id"]))
    native, event = _checked_event(runtime.journal, player, record)
    entry = native["entry"]
    _audit_chain(runtime, document, player, entry)
    expected = {"ledger": entry["progress"], "pending_observation": None}
    if (
        entry["phase"] != "handed_back"
        or value["previous"] != entry["baseline"]
        or value["entry"] != expected
        or value["result"] != event.result
        or event.result.get("native_handoff") is not True
        or event.result.get("observations_settled") is not True
    ):
        raise JournalError("ordinary frame head lacks its proved native handoff")
    return True


def handoff(runtime, player, operation, message):
    """Retryable final handoff after peer closure, with the identical held evidence."""
    if message.get("event") != "native_frame_handoff":
        raise JournalError("explicit native handoff event required")
    return returned(runtime, player, operation, message, handoff=True)


def handoff_status(runtime, player, request):
    """Authenticated read-only readiness; no frame/write authority is returned."""
    from server.admission_context import same_admitted_context

    schema = "rby-native-handoff-query-v1"
    if not isinstance(request, dict) or set(request) != {"window", "evidence"}:
        raise JournalError("typed native handoff query required")
    window, evidence = request["window"], request["evidence"]
    if (
        not isinstance(window, dict)
        or set(window) != {"schema", "challenge"}
        or window["schema"] != schema
        or not isinstance(evidence, dict)
        or set(evidence) != {"schema", "challenge", "return_operation_id", "context_generation"}
        or evidence["schema"] != schema
        or evidence["challenge"] != window["challenge"]
    ):
        raise JournalError("native handoff query differs")
    frame_progress.identifier(window["challenge"])
    frame_progress.identifier(evidence["return_operation_id"])
    document = runtime.state().document()
    initial = document["components"]["gen1-initial-observations"][player]
    if (
        not same_admitted_context(initial["metadata"], runtime.gate.sessions[player].metadata)
        or evidence["context_generation"] != initial["binding"]["context_generation"]
    ):
        raise JournalError("native handoff query belongs to another physical context")
    entry = document["components"].get(COMPONENT, {}).get(player)
    ready = False
    if (
        entry
        and entry["phase"] == "borrowed"
        and entry["progress"]["pending"] is None
        and entry["offered"] is None
    ):
        terminal = runtime.journal.event_snapshot(player, evidence["return_operation_id"])
        command = runtime.journal.command(player, entry["command_id"])
        ready = (
            entry["head"]["operation_id"] == evidence["return_operation_id"]
            and terminal is not None
            and terminal.request.get("event") == "native_frame_return"
            and document["active_trade"] is None
            and command["body"]["cmd"]
            in {"native_receptionist", "native_trade_abort", "native_trade_release"}
            and terminal.request["payload"]["checkpoint"] is not None
            and terminal.request["payload"]["native_checkpoint"] is not None
            and not any(
                runtime.journal.command(player, identifier)["body"].get("cmd") in COMMANDS
                for identifier in runtime.journal.pending_ids(player)
            )
        )
    return {**copy.deepcopy(evidence), "ready": bool(ready)}



# ---------------------------------------------------------------------------------------------
# Ordinary baseline ledger (moved from the retired gen1_frame_runtime / gen1_frame_journal).


def frame_key(player):
    return digest({"component": FRAMES, "player": player})[:32]


def anchor(document, player):
    if player not in ("a", "b"):
        raise JournalError("RBY frame player required")
    initial = document["components"].get("gen1-initial-observations", {}).get(player)
    bootstrap = document["components"].get(BOOTSTRAP, {}).get(player)
    if not isinstance(initial, dict) or not isinstance(bootstrap, dict):
        raise JournalError("normal new-game enrollment required before frame accounting")
    metadata = initial["metadata"]
    observation = initial["observation"]
    gen1 = metadata["gen1_metadata"]
    proof = validate_bootstrap(
        bootstrap["payload"],
        variant=gen1["cartridge"]["variant"],
        identity=metadata["save_identity"],
        context_generation=initial["binding"]["context_generation"],
        physical_instance=gen1["physical_instance"],
        final_sha1=gen1["cartridge"]["final_rom_sha1"],
        source=observation["source"],
        frame=observation["frame"],
    )
    if bootstrap["proof"] != proof:
        raise JournalError("frame bootstrap differs from its source receipt")
    return frame_progress.initial(
        context_generation=initial["binding"]["context_generation"],
        physical_digest=digest(
            {
                "metadata": {k: v for k, v in metadata.items() if k != "control_binding"},
                "host": observation["host"],
                "bootstrap": bootstrap["operation_id"],
            }
        ),
        frame=observation["frame"],
    )["anchor"]


def seed_ledger(document, player):
    """An unused ledger at the enrollment anchor; nothing in production calls this any more."""
    expected = frame_progress.initial(**anchor(document, player))
    entries = document["components"].setdefault(FRAMES, {})
    if player in entries:
        raise JournalError("frame accounting cannot replace an existing history")
    entries[player] = {"ledger": expected, "pending_observation": None}
    return entries[player]


def validate_ledger(document):
    entries = document["components"].get(FRAMES, {})
    if not isinstance(entries, dict) or set(entries) - {"a", "b"}:
        raise JournalError("invalid RBY frame ledger component")
    for player, entry in entries.items():
        if not isinstance(entry, dict) or set(entry) != {"ledger", "pending_observation"}:
            raise JournalError("complete RBY frame ledger entry required")
        ledger = frame_progress.validate(entry["ledger"])
        if ledger["anchor"] != anchor(document, player):
            raise JournalError("frame progress physical enrollment changed")
        pending = entry["pending_observation"]
        if pending is not None:
            if not isinstance(pending, dict) or set(pending) != {"closed", "bundle_digest"}:
                raise JournalError("complete pending frame observation required")
            closed = frame_progress.verify_closed(pending["closed"], anchor=ledger["anchor"])
            if (
                ledger["pending"] is not None
                or digest(closed) != ledger["previous_digest"]
                or closed["receipt"]["after"] != ledger["frame"]
                or pending["bundle_digest"] != closed["receipt"]["observations_digest"]
            ):
                raise JournalError("unsettled observation differs from the consumed frame range")


def verified_held_frame(document, player, frame, *, historical=False):
    """Only a settled, closed boundary can serve a later physical-write policy."""
    validate_ledger(document)
    entry = document["components"].get(FRAMES, {}).get(player)
    if historical:
        if (entry is None or type(frame) is not int
                or not entry["ledger"]["anchor"]["frame"] <= frame <= entry["ledger"]["frame"]):
            raise JournalError("historical frame is outside accounted execution")
        return True
    if (
        entry is None
        or entry["ledger"]["pending"] is not None
        or entry["pending_observation"] is not None
    ):
        raise JournalError("held frame still has unclosed execution or observation obligations")
    if type(frame) is not int or frame != entry["ledger"]["frame"]:
        raise JournalError("held frame differs from the server-accounted step count")
    return True


def retained_return(journal, player, fingerprint, anchor):
    """The closed range a handed-back loan retained under the ordinary return key."""
    frame_progress.identifier(fingerprint, 64)
    record = journal.record(FRAME_RETURNS, fingerprint[:32])
    value, event = _checked_event(journal, player, record)
    if event.request.get("event") not in {"native_frame_return", "native_frame_handoff"}:
        raise JournalError("retained frame return is not a native handoff")
    head = {**value, "message": event.request, "result": event.result}
    verify_frame_head(SimpleNamespace(journal=journal), journal.snapshot().state, player, head)
    native = journal.record(HISTORY, key(player, value["operation_id"]))
    closed = native.value["entry"]["closed"]
    if digest(closed) != fingerprint or closed["grant"]["anchor_digest"] != digest(anchor):
        raise JournalError("native retained frame range differs")
    return closed
