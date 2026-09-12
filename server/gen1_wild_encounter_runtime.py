"""Journaled wild encounter ordering and paired no-catch retirement obligations.

Successful source delivery consumes the encounter immediately, before stable
inventory or logical identity settlement. Peer delivery pending stabilization
defers no-catch rules: a later stable point can change the species-clause result
and supplies the exact identity required by the shared retirement executor.
"""

import copy
from datetime import UTC, datetime

from server import event_reference, gen1_engine_bridge, no_catch_rules
from server.adapters.gen1_rby import _MAP_ID_TO_AREA
from server.admission_context import same_admitted_context
from server.gen1_capture_receipt import validate_receipt as capture_receipt
from server.gen1_faint_runtime import synchronize
from server.gen1_initial_observation import COMPONENT as INITIAL
from server.gen1_wild_encounter_receipt import validate as encounter_receipt
from server.protocol import digest
from server.protocol_journal import JournalError, _identifier, _player

COMPONENT = "gen1-wild-encounters"
EVENT = "wild_encounter_observation"
SCHEMA = "rby-wild-encounter-observation-v1"
REASON = "No-catch partner retirement requires verified physical archive and save"
ACQUISITIONS = "gen1-acquisition-settlement"
KINDS = ("wild_begin", "wild_end", "capture")


def record_key():
    return digest({"component": COMPONENT})[:32]


def receipts_of(message):
    if not isinstance(message, dict):
        raise JournalError("typed encounter source event required")
    if message.get("event") == "frame_complete":
        return message.get("bundle", {}).get("acquisitions") or []
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
        raise JournalError("complete encounter observation required")
    return payload["receipts"]


def decode_rows(rows, initial, reference):
    if not isinstance(rows, list) or len(rows) > 64:
        raise JournalError("bounded encounter source rows required")
    metadata = initial["metadata"]
    cartridge = metadata["gen1_metadata"]["cartridge"]
    result = []
    for index, row in enumerate(rows):
        if (
            not isinstance(row, dict)
            or set(row) != {"kind", "receipt"}
            or not isinstance(row["kind"], str)
        ):
            raise JournalError("typed encounter source row required")
        if row["kind"] in ("grant", "static_origin", "static_battle_end", "npc_exchange", "evolution"):
            continue  # The shared source dispatcher validates these; they grant no no-catch fact.
        if row["kind"] not in KINDS:
            raise JournalError("unknown encounter source kind")
        if row["kind"] == "capture":
            fact = capture_receipt(row["receipt"], metadata)
        else:
            fact = encounter_receipt(
                row["receipt"],
                variant=cartridge["variant"],
                identity=metadata["save_identity"],
                context_generation=initial["binding"]["context_generation"],
                physical_instance=metadata["gen1_metadata"]["physical_instance"],
                final_sha1=cartridge["final_rom_sha1"],
            )
            if fact["kind"] != row["kind"]:
                raise JournalError("encounter row and boundary kind differ")
        result.append(
            {
                "kind": row["kind"],
                "fact": fact,
                "source_ref": {"event": copy.deepcopy(reference), "index": index},
            }
        )
    return result


def _frame(row):
    return row["fact"]["return_frame"] if row["kind"] == "capture" else row["fact"]["frame"]


def _activation(document, player, frame):
    proof = (
        document["components"].get("gen1-faint-settlement", {}).get("activations", {}).get(player)
    )
    if not proof:
        return False
    signal = proof["engine_record"]["payload"]["signals"][proof["index"]]
    from server.gen1_engine_signals import validate_signal

    initial = document["components"][INITIAL][player]
    decoded = validate_signal(
        signal,
        initial["metadata"]["gen1_metadata"]["cartridge"]["variant"],
        initial["metadata"]["save_identity"],
    )
    if decoded["kind"] != "pokeballs_obtained":
        raise JournalError("encounter activation is not a validated ball source")
    return signal["frame"] <= frame


def _matches(begin, fact):
    return (
        all(begin[k] == fact[k] for k in ("map_id", "species_index", "level", "battle_type"))
        and fact.get("call_frame", fact.get("frame")) >= begin["frame"]
    )


def _encounter_area(document, player, begin):
    matches = [
        row["static_id"]
        for row in document["components"]
        .get("gen1-static-origins", {})
        .get(player, {})
        .get("origins", [])
        if row["fact"]["began_frame"] == begin["frame"]
        and _matches(begin, {**row["fact"], "frame": row["fact"]["began_frame"]})
    ]
    if len(matches) > 1:
        raise JournalError("wild encounter has ambiguous static source ownership")
    return matches[0] if matches else _MAP_ID_TO_AREA.get(begin["map_id"])


def _source_area(document, player, fact):
    attributed = (
        document["components"]
        .get("gen1-static-origins", {})
        .get(player, {})
        .get("attributions", {})
    )
    return attributed.get(fact["key"], _MAP_ID_TO_AREA.get(fact["map_id"]))


def _own_capture(document, player, area):
    entry = document["components"].get(ACQUISITIONS, {}).get(player, {})
    return any(
        row["fact"]["kind"] == "capture" and _source_area(document, player, row["fact"]) == area
        for row in entry.get("pending", []) + entry.get("settled", [])
    )


def _peer_unsettled(document, rules, player, area, species):
    peer = "b" if player == "a" else "a"
    from server.gen1_party_codec import PartyCodec

    variant = document["components"][INITIAL][peer]["metadata"]["gen1_metadata"]["cartridge"][
        "variant"
    ]
    codec = PartyCodec(variant)
    if any(
        row["fact"]["kind"] == "capture" and row["area"] == area and row["violation"] is not None
        for row in document["components"].get(ACQUISITIONS, {}).get(peer, {}).get("settled", [])
    ):
        return True
    for row in document["components"].get(ACQUISITIONS, {}).get(peer, {}).get("pending", []):
        fact = row["fact"]
        if fact["kind"] != "capture":
            continue
        if _source_area(document, peer, fact) == area:
            return True
        dex = codec.profile["species"][str(fact["species_index"])]["dex"]
        if rules.species_lock and rules.adapter.evo_family(dex) == rules.adapter.evo_family(
            species
        ):
            return True
    return False


def _boxed_peers(document, player):
    from server.gen1_acquisition_runtime import _mon_info
    from server.gen1_party_codec import PartyCodec
    from server.gen1_retirement_runtime import completed

    peer = "b" if player == "a" else "a"
    codec = PartyCodec(
        document["components"][INITIAL][peer]["metadata"]["gen1_metadata"]["cartridge"]["variant"]
    )
    result = {}
    for row in document["components"].get(ACQUISITIONS, {}).get(peer, {}).get("settled", []):
        if (
            row["fact"]["kind"] != "capture"
            or row["rule"] != "boxed_deferred"
            or completed(document, peer, row["acquisition_id"])
        ):
            continue
        if row["area"] in result:
            raise JournalError("multiple unresolved boxed counterparts in one area")
        mon, _ = _mon_info(codec, row["fact"], bytes.fromhex(row["fact"]["blob_hex"]))
        member = document["identities"]["members"][row["member_id"]]["current"]
        if member["player"] != peer:
            raise JournalError("boxed counterpart transferred before disposition")
        mon.key = member["key"]
        result[row["area"]] = mon
    return result


def retirement_source(document, target_player, obligation_id):
    _player(target_player)
    _identifier(obligation_id)
    value = document["components"].get(COMPONENT, {}).get("obligations", {}).get(obligation_id)
    if (
        not value
        or value["target_player"] != target_player
        or value["phase"] not in ("pending", "complete")
    ):
        raise JournalError("exact no-catch retirement obligation required")
    initial = document["components"][INITIAL][target_player]
    rows = [
        row
        for row in document["components"]
        .get(ACQUISITIONS, {})
        .get(target_player, {})
        .get("settled", [])
        if row["acquisition_id"] == value["acquisition_id"]
        and row["member_id"] == value["member_id"]
        and row["area"] == value["area"]
    ]
    if len(rows) != 1 or rows[0]["fact"]["kind"] != "capture" or rows[0]["link_id"] is not None:
        raise JournalError("no-catch retirement lacks its exact unpaired captured identity")
    source = document["components"][COMPONENT]["players"][value["source_player"]]["encounters"][
        value["encounter_id"]
    ]
    if (
        source["phase"] != "no_catch"
        or source["decision"]["outcome"] != "dead_zone"
        or source["retirement_id"] != obligation_id
    ):
        raise JournalError("retirement lacks its failed counterpart encounter")
    if (
        obligation_id
        != digest(
            {"component": COMPONENT, "encounter": value["encounter_id"], "target": target_player}
        )[:32]
        or value["source_player"] == target_player
        or value["area"]
        != _encounter_area(document, value["source_player"], source["begin"]["fact"])
        or value["end_source_ref"] != source["end"]["source_ref"]
        or value["reason"] != "paired_no_catch"
        or value["hold_id"] != obligation_id
        or value["hold_reason"] != REASON
        or source["decision"]["retire"] != {"player": target_player, "key": value["key"]}
    ):
        raise JournalError("no-catch retirement scope differs from its exact source decision")
    if initial["metadata"]["gen1_metadata"]["cartridge"]["variant"] not in (
        "red",
        "blue",
        "yellow",
    ):
        raise JournalError("RBY retirement source required")
    from server.gen1_starter_settlement import context
    from server.identity_registry import IdentityRegistry

    registry = IdentityRegistry.restore(
        document["identities"], run_id=document["identities"]["run_id"]
    )
    if registry.resolve(context(initial, target_player), value["key"]) != value["member_id"]:
        raise JournalError("no-catch retirement target differs from its current logical member")
    return {
        name: value[name]
        for name in ("acquisition_id", "key", "member_id", "reason", "hold_id", "hold_reason")
    }


def complete_retirement(stage, document, target_player, obligation_id, receipt_ref):
    source = retirement_source(document, target_player, obligation_id)
    event_reference.validate(receipt_ref)
    if receipt_ref["player"] != target_player:
        raise JournalError("no-catch retirement receipt belongs to another player")
    value = document["components"][COMPONENT]["obligations"][obligation_id]
    if value["phase"] != "pending":
        raise JournalError("no-catch retirement is already complete")
    blockers = stage.barrier.document()["blockers"]
    if blockers.get(source["hold_id"]) != REASON:
        raise JournalError("no-catch retirement lost its exact hold")
    del blockers[source["hold_id"]]
    from server.gen1_acquisition_runtime import CONSTRAINT_REASON, constraint_id

    captured = next(
        row
        for row in document["components"][ACQUISITIONS][target_player]["settled"]
        if row["acquisition_id"] == source["acquisition_id"]
    )
    if captured["rule"] == "boxed_deferred" and captured["violation"] is None:
        original = constraint_id(target_player, source["acquisition_id"])
        if blockers.get(original) != CONSTRAINT_REASON:
            raise JournalError("boxed retirement lost its source acquisition hold")
        del blockers[original]
    stage.barrier.set_blockers(blockers)
    value["phase"] = "complete"
    value["receipt_ref"] = copy.deepcopy(receipt_ref)
    return {
        "namespace": COMPONENT,
        "key": record_key(),
        "value": copy.deepcopy(document["components"][COMPONENT]),
    }


def _resolve(runtime, stage, document, component, event):
    commands, records = {"a": [], "b": []}, []
    for player, entry in component["players"].items():
        for encounter_id, row in entry["encounters"].items():
            if row["phase"] not in ("ended", "awaiting_peer"):
                continue
            begin = row["begin"]["fact"]
            area = _encounter_area(document, player, begin)
            if row["captures"]:
                row["phase"] = "captured"
                continue
            if begin["exclusion"]:
                row["phase"] = "excluded"
                continue
            if area is None:
                raise JournalError("encounter map has no rule area; reconciliation required")
            if _own_capture(document, player, area):
                row.update(
                    phase="no_catch",
                    decision={"outcome": "already_captured_source", "retire": None},
                    occurred_at=datetime.now(UTC).isoformat(),
                )
                continue
            if _peer_unsettled(document, stage.rules, player, area, begin["species_id"]):
                row["phase"] = "awaiting_peer"
                continue
            at = datetime.now(UTC).isoformat()
            outcome = gen1_engine_bridge.no_catch(
                stage.rules,
                player,
                area,
                begin["species_id"],
                begin["level"],
                activated=row["activated"],
                proved_peers=_boxed_peers(document, player),
                decision=no_catch_rules.decision,
            )
            at = outcome.pop("at") or at
            row.update(phase="no_catch", decision=outcome, occurred_at=at)
            if outcome["retire"]:
                peer, key = outcome["retire"]["player"], outcome["retire"]["key"]
                from server.gen1_starter_settlement import context

                member = stage.identities.resolve(
                    context(document["components"][INITIAL][peer], peer), key
                )
                matches = [
                    r
                    for r in document["components"]
                    .get(ACQUISITIONS, {})
                    .get(peer, {})
                    .get("settled", [])
                    if r["member_id"] == member and r["area"] == area and r["link_id"] is None
                ]
                if len(matches) != 1:
                    raise JournalError(
                        "failed encounter partner lacks its settled acquisition identity"
                    )
                captured = matches[0]
                identifier = digest(
                    {"component": COMPONENT, "encounter": encounter_id, "target": peer}
                )[:32]
                row["retirement_id"] = identifier
                obligation = {
                    "source_player": player,
                    "encounter_id": encounter_id,
                    "area": area,
                    "end_source_ref": copy.deepcopy(row["end"]["source_ref"]),
                    "target_player": peer,
                    "acquisition_id": captured["acquisition_id"],
                    "key": key,
                    "member_id": captured["member_id"],
                    "reason": "paired_no_catch",
                    "hold_id": identifier,
                    "hold_reason": REASON,
                    "phase": "pending",
                    "receipt_ref": None,
                }
                component["obligations"][identifier] = obligation
                blockers = stage.barrier.document()["blockers"]
                blockers[identifier] = REASON
                stage.barrier.set_blockers(blockers)
                from server.gen1_retirement_runtime import schedule_job

                added, extra = schedule_job(
                    document,
                    peer,
                    event,
                    cause={"kind": "paired_no_catch", "obligation_id": identifier},
                )
                for p in ("a", "b"):
                    commands[p].extend(added[p])
                records.extend(extra)
    return commands, records


def stage(
    runtime, state, document, player, operation, message, *, frame_origin=None, frame_request=None
):
    """Stage ordered raw source rows, then revisit either player's deferred end.

    Root supplies its proved compound frame and calls this after source acquisition
    staging, including on later inventory-only frames while a peer end is deferred.
    """
    _player(player)
    _identifier(operation)
    initial = document["components"].get(INITIAL, {}).get(player)
    session = runtime.gate.sessions.get(player)
    if (
        initial is None
        or set(document["components"].get(INITIAL, {})) != {"a", "b"}
        or session is None
        or not same_admitted_context(session.metadata, initial["metadata"])
    ):
        raise JournalError("wild encounter requires the same admitted source owner")
    raw_message = frame_request or message
    reference = event_reference.make(player, operation, raw_message)
    if frame_origin is not None:
        from server.gen1_observation_provenance import stage_origin

        stage_origin(
            document,
            player,
            operation,
            {"event": "acquisition_observation", "payload": {"receipts": receipts_of(raw_message)}},
            frame_origin=frame_origin,
            frame_request=raw_message,
        )
    elif player in document["components"].get("gen1-frame-progress", {}):
        raise JournalError("frame-accounted encounters require their compound frame origin")
    if document["active_trade"]:
        raise JournalError("native trade owns encounter settlement")
    rows = decode_rows(receipts_of(raw_message), initial, reference)
    prior = document["components"].get(COMPONENT, {})
    deferred = any(
        r["phase"] == "awaiting_peer"
        for p in prior.get("players", {}).values()
        for r in p["encounters"].values()
    )
    if frame_request is not None and not rows and not deferred:
        return None
    component = document["components"].setdefault(COMPONENT, {"players": {}, "obligations": {}})
    entry = component["players"].setdefault(
        player, {"sequence": 0, "operation_id": initial["operation_id"], "encounters": {}}
    )
    if frame_request is None and message["payload"]["sequence"] != entry["sequence"] + 1:
        raise JournalError("encounter source sequence skipped or repeated")
    entry["sequence"] += 1
    entry["operation_id"] = operation
    live = next((r for r in entry["encounters"].values() if r["end"] is None), None)
    last_frame = max(
        (_frame(r["end"] or r["begin"]) for r in entry["encounters"].values()),
        default=initial["observation"]["frame"],
    )
    # A capture call and EndOfBattle can finish in the same returned frame.
    # Preserve raw source indices, but consume delivery before absence inference.
    rows.sort(key=lambda r: (_frame(r), {"wild_begin": 0, "capture": 1, "wild_end": 2}[r["kind"]]))
    for source in rows:
        fact = source["fact"]
        frame = _frame(source)
        if frame < last_frame or frame < initial["observation"]["frame"]:
            raise JournalError("wild source frames moved backwards")
        last_frame = frame
        if source["kind"] == "wild_begin":
            if live is not None:
                raise JournalError("wild encounter began before its prior end was observed")
            identifier = digest(source["source_ref"])[:32]
            live = {
                "begin": source,
                "end": None,
                "captures": [],
                "phase": "live",
                "activated": _activation(document, player, frame),
                "decision": None,
                "occurred_at": None,
                "retirement_id": None,
            }
            entry["encounters"][identifier] = live
        elif source["kind"] == "capture":
            if live is not None:
                if not _matches(live["begin"]["fact"], fact):
                    raise JournalError("capture does not belong to the open wild encounter")
                if live["captures"]:
                    raise JournalError("wild encounter delivered more than one capture")
                live["captures"].append(source)
        else:
            if live is None or not _matches(live["begin"]["fact"], fact):
                raise JournalError("wild encounter end lacks its exact observed begin")
            live["end"] = source
            live["phase"] = "ended"
            live = None
    commands, extra = _resolve(
        runtime,
        state,
        document,
        component,
        {"player": player, "operation_id": operation, "message": raw_message},
    )
    synchronize(state, document)
    value = copy.deepcopy(component)
    return {
        "result": {
            "ack": "ACK",
            "wild_encounter_digest": digest(value),
            "ordinary_execution": False,
        },
        "commands": commands,
        "records": [{"namespace": COMPONENT, "key": record_key(), "value": value}, *extra],
    }


def record(runtime, player, operation, message):
    prior = runtime.journal.event(player, operation, message)
    if prior is not None:
        return prior.result
    state = runtime.state()
    document = state.document()
    result = stage(runtime, state, document, player, operation, message)
    return runtime.journal.commit(
        player,
        operation,
        message,
        expected_revision=state.journal_revision,
        state=document,
        result=result["result"],
        commands=result["commands"],
        records=result["records"],
    ).result


def verify_state(state):
    document = state.document()
    component = document["components"].get(COMPONENT)
    if component is None:
        return
    if (
        not isinstance(component, dict)
        or set(component) != {"players", "obligations"}
        or not isinstance(component["players"], dict)
        or not isinstance(component["obligations"], dict)
        or set(component["players"]) - {"a", "b"}
    ):
        raise JournalError("invalid wild encounter component")
    for player, entry in component["players"].items():
        if (
            not isinstance(entry, dict)
            or set(entry) != {"sequence", "operation_id", "encounters"}
            or not isinstance(entry["encounters"], dict)
            or type(entry["sequence"]) is not int
            or entry["sequence"] < 1
        ):
            raise JournalError("invalid wild encounter source head")
        _identifier(entry["operation_id"])
        live = 0
        for identifier, row in entry["encounters"].items():
            if not isinstance(row, dict) or set(row) != {
                "begin",
                "end",
                "captures",
                "phase",
                "activated",
                "decision",
                "occurred_at",
                "retirement_id",
            }:
                raise JournalError("invalid wild encounter lifecycle row")
            if not isinstance(row["captures"], list) or len(row["captures"]) > 1:
                raise JournalError("bounded encounter capture references required")
            for source in [
                row["begin"],
                *row["captures"],
                *([row["end"]] if row["end"] is not None else []),
            ]:
                if (
                    not isinstance(source, dict)
                    or set(source) != {"kind", "fact", "source_ref"}
                    or source["kind"] not in KINDS
                    or not isinstance(source["fact"], dict)
                    or source["fact"].get("kind") != source["kind"]
                ):
                    raise JournalError("typed encounter fact required")
                ref = source["source_ref"]
                if (
                    not isinstance(ref, dict)
                    or set(ref) != {"event", "index"}
                    or type(ref["index"]) is not int
                    or ref["index"] < 0
                ):
                    raise JournalError("indexed encounter source required")
                if event_reference.validate(ref["event"])["player"] != player:
                    raise JournalError("encounter source belongs to another player")
                required = (
                    {
                        "map_id",
                        "species_index",
                        "level",
                        "battle_type",
                        "call_frame",
                        "return_frame",
                    }
                    if source["kind"] == "capture"
                    else {"map_id", "species_index", "level", "battle_type", "frame"}
                )
                if any(type(source["fact"].get(key)) is not int for key in required):
                    raise JournalError("encounter fact lost its exact source fields")
            if (
                identifier != digest(row["begin"]["source_ref"])[:32]
                or row["begin"]["kind"] != "wild_begin"
            ):
                raise JournalError("encounter identity differs from its begin source")
            begin = row["begin"]["fact"]
            if row["end"] is not None and (
                row["end"]["kind"] != "wild_end" or not _matches(begin, row["end"]["fact"])
            ):
                raise JournalError("encounter end differs from its begin")
            if any(
                c["kind"] != "capture"
                or not _matches(begin, c["fact"])
                or row["end"] is not None
                and _frame(c) > _frame(row["end"])
                for c in row["captures"]
            ):
                raise JournalError("capture source lies outside its encounter")
            if (
                row["phase"] not in ("live", "captured", "excluded", "no_catch", "awaiting_peer")
                or type(row["activated"]) is not bool
            ):
                raise JournalError("invalid encounter resolution")
            if (row["end"] is None) != (row["phase"] == "live"):
                raise JournalError("encounter end differs from resolution")
            live += row["end"] is None
            if (
                row["phase"] == "captured"
                and len(row["captures"]) != 1
                or row["phase"] in ("no_catch", "awaiting_peer")
                and row["captures"]
            ):
                raise JournalError("successful delivery cannot become no-catch")
            if row["phase"] == "no_catch" and not isinstance(row["decision"], dict):
                raise JournalError("no-catch resolution lacks its policy decision")
            if row["decision"] is not None:
                decision = row["decision"]
                if (
                    row["phase"] != "no_catch"
                    or set(decision) != {"outcome", "retire"}
                    or decision["outcome"]
                    not in (
                        "already_captured_source",
                        "ball_gate",
                        "gift_area",
                        "resolved",
                        "already_captured",
                        "clause_retry",
                        "dupe_already_notified",
                        "species_clause",
                        "dead_zone",
                    )
                ):
                    raise JournalError("invalid no-catch policy decision")
                if decision["outcome"] == "dead_zone":
                    from server.state import AreaStatus, LinkStatus

                    area = _encounter_area(document, player, begin)
                    links = [
                        link
                        for link in state.rules.links
                        if link.area_id == area
                        and link.cause == "dead_zone"
                        and link.initiating_player == player
                        and link.killed_at == row["occurred_at"]
                        and link.status == LinkStatus.DEAD
                    ]
                    if state.rules.area_states.get(area) != AreaStatus.DEAD_ZONE or len(links) != 1:
                        raise JournalError("no-catch decision lacks its exact dead-zone rule entry")
                if (decision["retire"] is not None) != (row["retirement_id"] is not None):
                    raise JournalError("no-catch disposition differs from its physical obligation")
        if live > 1:
            raise JournalError("overlapping wild encounters")
    for identifier, value in component["obligations"].items():
        if not isinstance(value, dict) or set(value) != {
            "source_player",
            "encounter_id",
            "area",
            "end_source_ref",
            "target_player",
            "acquisition_id",
            "key",
            "member_id",
            "reason",
            "hold_id",
            "hold_reason",
            "phase",
            "receipt_ref",
        }:
            raise JournalError("complete no-catch retirement obligation required")
        source = retirement_source(document, value["target_player"], identifier)
        blockers = state.barrier.document()["blockers"]
        if (value["phase"] == "pending") != (blockers.get(source["hold_id"]) == REASON):
            raise JournalError("no-catch retirement hold differs from physical completion")
        if value["phase"] == "complete":
            event_reference.validate(value["receipt_ref"])


def verify_journal(journal, state):
    verify_state(state)
    document = state.document()
    component = document["components"].get(COMPONENT)
    if component is None:
        return
    stored = journal.record(COMPONENT, record_key())
    if stored is None or stored.value != component:
        raise JournalError("wild encounter component differs from atomic journal record")
    for player, entry in component["players"].items():
        initial = document["components"][INITIAL][player]
        for row in entry["encounters"].values():
            for source in [row["begin"], *row["captures"], *([row["end"]] if row["end"] else [])]:
                ref = source["source_ref"]
                event = event_reference.resolve(journal, ref["event"])
                if (
                    ref["event"]["player"] != player
                    or type(ref["index"]) is not int
                    or not 0 <= ref["index"] < len(receipts_of(event.request))
                ):
                    raise JournalError("wild encounter source row belongs to another event")
                actual = decode_rows(receipts_of(event.request), initial, ref["event"])
                matches = [item for item in actual if item["source_ref"]["index"] == ref["index"]]
                if matches != [source]:
                    raise JournalError("wild encounter source differs from its checked receipt")
                if event.request.get("event") == "frame_complete":
                    from server.gen1_frame_acquisitions import verify_frames
                    from server.gen1_frame_journal import retained_return

                    anchor = document["components"]["gen1-frame-progress"][player]["ledger"][
                        "anchor"
                    ]
                    closed = retained_return(
                        journal, player, event.result.get("closed_frame_digest"), anchor
                    )
                    if closed["receipt"] != event.request["receipt"]:
                        raise JournalError("wild source differs from its retained frame receipt")
                    verify_frames(
                        journal,
                        player,
                        anchor,
                        closed,
                        [receipts_of(event.request)[ref["index"]]],
                        [source],
                    )
            if row["activated"] != _activation(document, player, row["begin"]["fact"]["frame"]):
                raise JournalError("encounter ball gate differs from its source ordering")
    for value in component["obligations"].values():
        if value["phase"] == "complete":
            event_reference.resolve(journal, value["receipt_ref"])
