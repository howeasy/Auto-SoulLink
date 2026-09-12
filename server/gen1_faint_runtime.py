"""Ordered ball activation and linked death/receipt settlement for owned RBY signals."""

import copy
import re

from server import battle_force_authority as instruction, event_reference
from server.gen1_command_receipts import verify_force_faint_receipt
from server.gen1_initial_observation import COMPONENT as INITIAL
from server.gen1_observation_provenance import semantic_receipt
from server.gen1_party_codec import PartyCodec
from server.gen1_semantic_events import faint_event
from server.gen1_starter_settlement import context
from server.gen1_whiteout import settle_whiteout
from server.linked_death_rules import update_run_over
from server.protocol import digest
from server.protocol_journal import JournalError, _identifier
from server.state import DEATH_COMMANDS

COMPONENT = "gen1-faint-settlement"
REASON = "Linked death requires verified physical faint and memorial closure"


def identifier(player, operation, index):
    return digest({"player": player, "engine_operation": operation, "signal": index})[:32]


def source_result(entry):
    return {"ack": "ACK", "engine_evidence_digest": digest(entry), "ordinary_execution": False}


def synchronize(stage, document):
    from server.gen1_runtime_state import recovery_history

    document["rules"] = stage.rules.document()
    document["identities"] = stage.identities.document()
    stage.barrier.set_history(
        recovery_history(
            document["rules"],
            document["identities"],
            document["active_trade"],
            document["components"].get("gen1-trade"),
        )
    )
    document["components"]["gen1-runtime"]["recovery"] = stage.barrier.document()


def _storage_jobs(document, players):
    from server.gen1_storage_runtime import COMPONENT as STORAGE, busy

    if not busy(document, players):
        return []
    return sorted(
        identifier
        for identifier, job in document["components"][STORAGE]["jobs"].items()
        if not job["complete"] and set(job["keys"]) & set(players)
    )


def schedule_deferred(runtime, stage, document, event):
    """Publish deferred FF only in the actual final storage ACK transaction.

    Original engine/death provenance is immutable. The later issuer is retained
    separately so neither replay nor ACK pretends the source event issued it.
    """
    reference = event_reference.make(event["player"], event["operation_id"], event["message"])
    commands = {"a": [], "b": []}
    jobs = document["components"].get("gen1-storage-settlement", {}).get("jobs", {})
    for death in document["components"].get(COMPONENT, {}).get("deaths", {}).values():
        if death["phase"] != "pending_issue" or _storage_jobs(
            document, (death["player"], death["peer"])
        ):
            continue
        deferred = death["deferred"]
        if any(
            identifier not in jobs or not jobs[identifier]["complete"]
            for identifier in deferred["jobs"]
        ):
            raise JournalError("deferred faint lost its complete storage predecessors")
        if not any(
            reference in jobs[identifier]["writes"].values() for identifier in deferred["jobs"]
        ):
            raise JournalError("deferred faint requires the actual terminal storage ACK")
        deferred["origin"] = reference
        death["phase"] = "pending_faint"
        commands[death["peer"]].append(copy.deepcopy(deferred["command"]))
    synchronize(stage, document)
    return commands, []


def _command_origin(journal, death):
    deferred = death.get("deferred")
    if deferred is not None:
        if deferred["origin"] is None:
            raise JournalError("physical faint was not issued yet")
        return event_reference.resolve(journal, deferred["origin"])
    return semantic_receipt(journal, death["player"], death["engine_record"], "engine_signals")


def _recipient_commands(journal, issued, recipient):
    """A compound death event has A/B HUD commands as well as the peer write."""
    rows = []
    for identifier in issued.command_ids:
        found = []
        for player in ("a", "b"):
            try:
                found.append((player, journal.command(player, identifier)))
            except JournalError as error:
                if str(error) != "unknown command or wrong player":
                    raise
        if len(found) != 1:
            raise JournalError("linked death command has no unique recipient")
        if found[0][0] == recipient:
            rows.append(found[0][1])
    return rows


def settle(runtime, stage, document, player, entry):
    commands = {"a": [], "b": []}
    relevant = [
        row for row in entry["transactions"] if row["kind"] in ("pokeballs_obtained", "faint")
    ]
    if not relevant:
        return commands
    component = document["components"].setdefault(COMPONENT, {"activations": {}, "deaths": {}})
    initials = document["components"][INITIAL]
    for index, signal in enumerate(entry["payload"]["signals"]):
        from server.gen1_engine_signals import validate_signal

        row = validate_signal(
            signal, entry["payload"]["variant"], initials[player]["metadata"]["save_identity"]
        )
        if row["kind"] == "pokeballs_obtained":
            if set(initials) != {"a", "b"}:
                raise JournalError("paired enrollment required before rule activation")
            if player not in component["activations"]:
                component["activations"][player] = {
                    "engine_record": copy.deepcopy(entry),
                    "index": index,
                }
                stage.rules.pokeballs_obtained[player] = True
                was_over = stage.rules.run_over
                update_run_over(stage.rules)
                if not was_over and stage.rules.run_over:
                    # A previously settled linked death can become terminal when
                    # the second owner's Pokeballs are observed.  update_run_over
                    # changes the flag directly, not via the shared engine queue.
                    from server.gen1_hud_feedback import build_state

                    for recipient in ("a", "b"):
                        commands[recipient].append(build_state({"cmd": "game_over"}))
            continue
        if row["kind"] != "faint" or not stage.rules.pokeballs_obtained[player]:
            continue
        if player not in component["activations"]:
            raise JournalError("active faint has no qualified ball activation history")
        link = stage.rules.find_link(player, row["key"])
        if link is None or link.a is None or link.b is None:
            raise JournalError("active faint requires a qualified linked identity")
        from server.state import LinkStatus

        if link.status != LinkStatus.ALIVE:
            continue
        if document["active_trade"]:
            raise JournalError("trade owns the party until verified closure")
        partner = "b" if player == "a" else "a"
        members = [
            stage.identities.resolve(context(initials[p], p), getattr(link, p).key)
            for p in ("a", "b")
        ]
        matches = [
            key
            for key, value in stage.identities.document()["links"].items()
            if set(value["members"]) == set(members)
        ]
        if None in members or len(matches) != 1:
            raise JournalError("faint rule pair differs from logical identity linkage")
        death_id = identifier(player, entry["operation_id"], index)
        mon = PartyCodec(entry["payload"]["variant"]).validate_blob(bytes.fromhex(row["blob_hex"]))
        # The shared rule engine decides the death exactly as it does for Gen 3 (_handle_faint ->
        # _propagate_faint): pair DEAD, both party keys released, both memorial obligations, the
        # peer command selected (force_faint, or force_explode when the run and adapter opt in),
        # run-over checked. Gen 1 supplies the evidence around it, nothing else.
        immediate = stage.rules.handle_event(player, faint_event(key=row["key"], level=mon.level, cause=row["cause"]))
        if link.status != LinkStatus.DEAD:
            raise JournalError("shared rule engine did not settle the linked death")
        link.cause = row["cause"]  # RBY knows battle versus poison; _propagate_faint records "battle" for every generation
        at = link.killed_at
        captured = stage.rules.take_commands(player, immediate)
        physical = [c for c in captured[partner] if c.get("cmd") in ("force_faint", "force_explode") and c.get("key") == getattr(link, partner).key]
        if len(physical) != 1:
            raise JournalError("shared rule engine did not select exactly one peer death command")
        from server.gen1_hud_feedback import classify_death

        labels = {p: getattr(link, p).nickname or stage.rules.adapter.species_name(getattr(link, p).species)
                  or getattr(link, p).key[:8] for p in ("a", "b")}
        feedback = classify_death(captured, member_labels=labels)
        effect = {"player": partner, "command": dict(physical[0])}
        effect["command"]["death_id"] = death_id
        component["deaths"][death_id] = {
            "player": player,
            "engine_record": copy.deepcopy(entry),
            "index": index,
            "link_id": matches[0],
            "members": members,
            "key": row["key"],
            "peer": partner,
            "peer_key": getattr(link, partner).key,
            "at": at,
            "command": physical[0]["cmd"],
            "phase": "pending_faint",
            "receipt_event": None,
        }
        jobs = _storage_jobs(document, (player, partner))
        if jobs:
            component["deaths"][death_id].update(
                phase="pending_issue",
                deferred={
                    "jobs": jobs,
                    "command": copy.deepcopy(effect["command"]),
                    "origin": None,
                },
            )
        else:
            commands[partner].append(effect["command"])
        blockers = stage.barrier.document()["blockers"]
        blockers[death_id] = REASON
        stage.barrier.set_blockers(blockers)
        # P5-whiteout: AnyPartyAlive over the same signal, only after the faint settled, so the
        # whited-out pair is already DEAD and the engine cannot queue a second peer death for it.
        whiteout_feedback = settle_whiteout(stage, document, player, entry, index, signal)
        for recipient in ("a", "b"):
            commands[recipient].extend(feedback[recipient])
            commands[recipient].extend(whiteout_feedback[recipient])
    synchronize(stage, document)
    from server.gen1_hud_feedback import feedback_last

    return feedback_last(commands)


def acknowledge(runtime, player, operation, message):
    stage = runtime.state()
    old = runtime.journal.event(player, operation, message)
    if old is not None:
        return old.result
    if (
        set(message) != {"event", "command_id", "command_sequence", "outcome", "receipt"}
        or message["outcome"] != "ACK"
    ):
        raise JournalError("exact physical faint acknowledgement required")
    command = runtime.journal.command(player, message["command_id"])
    body = command["body"]
    document = stage.document()
    death = document["components"].get(COMPONENT, {}).get("deaths", {}).get(body.get("death_id"))
    if body.get("cmd") == instruction.COMMAND:
        return _acknowledge_instruction(runtime, stage, document, player, operation, message, command, death)
    if (
        death is None
        or death["peer"] != player
        or body.get("cmd") not in DEATH_COMMANDS
        or body.get("key") != death["peer_key"]
        or message["command_sequence"] != command["command_sequence"]
    ):
        raise JournalError("faint acknowledgement differs from its owned obligation")
    origin = _command_origin(runtime.journal, death)
    if message["command_id"] not in origin.command_ids:
        raise JournalError("faint acknowledgement is not for the original command")
    pending = runtime.journal.pending_ids(player)
    if command["outcome"] is None and (not pending or pending[0] != message["command_id"]):
        raise JournalError("faint acknowledgement must own the oldest pending command")
    verify_force_faint_receipt(
        body,
        message["receipt"],
        variant=runtime.contract["players"][player]["variant"],
        identity=stage.rules.player_identity[player],
    )
    if death["phase"] != "pending_faint" or command["outcome"] is not None:
        raise JournalError("completed faint requires replay of its original acknowledgement")
    death["phase"] = "pending_memorial"
    death["receipt_event"] = {"operation_id": operation, "message": copy.deepcopy(message)}
    from server.gen1_command_receipts import validate_party_snapshot

    party = validate_party_snapshot(
        message["receipt"]["after"], variant=runtime.contract["players"][player]["variant"]
    )
    stage.rules.party_size[player] = len(party)
    stage.rules.partner_blobs[player] = [
        {
            "slot": slot,
            "key": mon.key,
            "species_id": mon.species_id,
            "level": mon.level,
            "blob": mon.raw,
        }
        for slot, mon in enumerate(party)
    ]
    synchronize(stage, document)
    from server.gen1_memorial_runtime import schedule

    commands = schedule(
        document, {"player": player, "operation_id": operation, "message": copy.deepcopy(message)}
    )
    # Physical ACK starts read-only preparation; it does not imply a saved grave.
    return runtime.journal.commit(
        player,
        operation,
        message,
        expected_revision=stage.journal_revision,
        state=document,
        commands=commands,
        result={"ack": "ACK"},
        acknowledgements=[
            {
                "player": player,
                "command_id": message["command_id"],
                "outcome": "ACK",
                "receipt": message["receipt"],
            }
        ],
    ).result


def enforce(death, verdict, *, origin):
    """Record a verified terminal window verdict (fainted / benched) on its death exactly once.

    The death stays ``pending_faint``: the peer's overworld held faint later finds HP already
    ``0000`` and its proven no-op receipt closes the death through ``acknowledge``. Non-terminal
    verdicts (refused, not_reached, explode_armed, declined) record nothing; the next window re-issues.
    """
    if verdict["outcome"] not in instruction.TERMINAL:
        return None
    if death["phase"] != "pending_faint":
        raise JournalError("battle enforcement requires a pending physical faint")
    if "enforcement" in death:
        raise JournalError("linked death was already enforced in battle")
    row = verdict["row"]
    death["enforcement"] = {"origin": origin, "frame": row["frame"], "step": row["step"], "site": row["site"],
                            "outcome": verdict["outcome"], "evidence_digest": digest(row)}
    return death["enforcement"]


def _acknowledge_instruction(runtime, stage, document, player, operation, message, command, death):
    """Close one battle_instruction window: verify its rows against the issued authority, enforce a terminal
    verdict once, and re-issue in the same transaction while the peer reports a battle and the death is
    still pending. Never the oldest pending command: that is the death command it serves."""
    body = command["body"]
    receipt = message["receipt"]
    if (death is None or death["peer"] != player or body.get("key") != death["peer_key"]
            or message["command_sequence"] != command["command_sequence"]):
        raise JournalError("instruction acknowledgement differs from its owned obligation")
    if command["outcome"] is not None:
        raise JournalError("completed instruction window requires replay of its original acknowledgement")
    authority = body.get("authority")
    if (not isinstance(receipt, dict) or set(receipt) != {"schema", "challenge", "frame", "battle", "rows"}
            or receipt["schema"] != instruction.RECEIPT or not isinstance(authority, dict)
            or receipt["challenge"] != authority.get("challenge") or type(receipt["frame"]) is not int
            or type(receipt["battle"]) is not int or not 0 <= receipt["battle"] <= 255 or not isinstance(receipt["rows"], list)):
        raise JournalError("exact instruction window receipt required")
    binding = runtime.gate.sessions[player].metadata["control_binding"]
    original = runtime.journal.command(player, authority.get("scope", {}).get("operation_id"))
    if original["body"].get("death_id") != body.get("death_id"):
        raise JournalError("instruction window names another death command")
    initial = document["components"][INITIAL][player]
    instruction.verify_issued(authority, original, binding, player=player, anchor=initial["observation"]["frame"],
                              owner_id=initial["metadata"]["gen1_metadata"]["physical_instance"])
    verdict = instruction.verify_window(authority, receipt["rows"]) if receipt["rows"] else {"covered": None, "outcome": "declined", "row": None}
    if verdict["outcome"] in instruction.TERMINAL and death["phase"] != "pending_faint":
        raise JournalError("battle enforcement arrived after the physical faint closed")
    result = {"ack": "ACK", "instruction_outcome": verdict["outcome"]}
    enforced = enforce(death, verdict, origin=event_reference.make(player, operation, message))
    if enforced is not None:
        result["instruction_digest"] = digest(enforced)
    commands = {"a": [], "b": []}
    if receipt["battle"] != 0:
        following = instruction.pending_instruction(runtime, stage, document, player, frame=receipt["frame"] + 1, seed=operation,
                                                    binding=binding, ignore=message["command_id"])
        if following is not None:
            commands[player].append(following)
    return runtime.journal.commit(
        player, operation, message, expected_revision=stage.journal_revision, state=document, commands=commands, result=result,
        acknowledgements=[{"player": player, "command_id": message["command_id"], "outcome": "ACK", "receipt": receipt}],
    ).result


def _verify_enforcement(journal, death_id, death):
    enforcement = death["enforcement"]
    issued = event_reference.resolve(journal, enforcement["origin"])
    message = issued.request
    closed = journal.command(death["peer"], message.get("command_id")) if message.get("event") == "command_ack" else None
    if (closed is None or closed["body"].get("cmd") != instruction.COMMAND or closed["body"].get("death_id") != death_id
            or closed["outcome"] != "ACK" or closed["receipt"] != message.get("receipt")
            or issued.result.get("instruction_outcome") != enforcement["outcome"]
            or issued.result.get("instruction_digest") != digest(enforcement)):
        raise JournalError("battle enforcement lacks its verified instruction window receipt")


def verified_source(proof, initial):
    from server.gen1_engine_signals import validate_batch

    entry = proof["engine_record"]
    _identifier(entry["operation_id"])
    decoded = validate_batch(entry["payload"], initial["metadata"])
    index = proof["index"]
    if type(index) is not int or not 0 <= index < len(decoded):
        raise JournalError("invalid engine evidence index")
    if entry["payload"]["signals"][index]["frame"] < initial["observation"]["frame"]:
        raise JournalError("rule evidence predates enrollment")
    return decoded[index]


def verify_state(stage):
    document = stage.document()
    component = document["components"].get(COMPONENT)
    if component is None:
        return
    if (
        not isinstance(component, dict)
        or set(component) != {"activations", "deaths"}
        or not isinstance(component["activations"], dict)
        or not isinstance(component["deaths"], dict)
    ):
        raise JournalError("invalid faint settlement component")
    initials = document["components"].get(INITIAL, {})
    if set(component["activations"]) - {"a", "b"}:
        raise JournalError("invalid activation player")
    for player, proof in component["activations"].items():
        if (
            set(initials) != {"a", "b"}
            or set(proof) != {"engine_record", "index"}
            or verified_source(proof, initials[player])["kind"] != "pokeballs_obtained"
        ):
            raise JournalError("invalid persisted ball activation")
        if stage.rules.pokeballs_obtained[player] is not True:
            raise JournalError("ball activation lost its permanent rule credit")
    for death_id, death in component["deaths"].items():
        _identifier(death_id)
        if set(death) - {"deferred", "enforcement"} != {
            "player",
            "engine_record",
            "index",
            "link_id",
            "members",
            "key",
            "peer",
            "peer_key",
            "at",
            "command",
            "phase",
            "receipt_event",
        } or death["command"] not in DEATH_COMMANDS:
            raise JournalError("incomplete linked death record")
        player = death["player"]
        peer = death["peer"]
        if player not in component["activations"] or peer != ("b" if player == "a" else "a"):
            raise JournalError("linked death lacks rule activation or peer")
        row = verified_source(death, initials[player])
        activation = component["activations"][player]
        if (activation["engine_record"]["payload"]["sequence"], activation["index"]) >= (
            death["engine_record"]["payload"]["sequence"],
            death["index"],
        ):
            raise JournalError("faint precedes its activation evidence")
        if (
            row["kind"] != "faint"
            or row["key"] != death["key"]
            or death_id
            != identifier(player, death["engine_record"]["operation_id"], death["index"])
        ):
            raise JournalError("linked death differs from source evidence")
        if death["phase"] not in (
            "pending_issue",
            "pending_faint",
            "pending_memorial",
            "memorial_complete",
        ) or (death["receipt_event"] is None) != (
            death["phase"] in ("pending_issue", "pending_faint")
        ):
            raise JournalError("invalid faint completion phase")
        if "deferred" in death:
            deferred = death["deferred"]
            if (
                not isinstance(deferred, dict)
                or set(deferred) != {"jobs", "command", "origin"}
                or not isinstance(deferred["jobs"], list)
                or not deferred["jobs"]
                or any(not isinstance(job, str) for job in deferred["jobs"])
                or deferred["jobs"] != sorted(set(deferred["jobs"]))
            ):
                raise JournalError("complete ordered faint deferral required")
            for job in deferred["jobs"]:
                _identifier(job)
            command = deferred["command"]
            if (
                not isinstance(command, dict)
                or set(command) != {"cmd", "death_id", "key", "nickname"}
                or command["cmd"] not in DEATH_COMMANDS
                or command["cmd"] != death["command"]
                or command["death_id"] != death_id
                or command["key"] != death["peer_key"]
                or not isinstance(command["nickname"], str)
            ):
                raise JournalError("deferred faint command differs from original death")
            if (deferred["origin"] is None) != (death["phase"] == "pending_issue"):
                raise JournalError("deferred faint issuance differs from its phase")
            if deferred["origin"] is not None:
                event_reference.validate(deferred["origin"])
        elif death["phase"] == "pending_issue":
            raise JournalError("unissued faint lacks its storage deferral")
        if "enforcement" in death:
            enforcement = death["enforcement"]
            if (
                not isinstance(enforcement, dict)
                or set(enforcement) != {"origin", "frame", "step", "site", "outcome", "evidence_digest"}
                or enforcement["outcome"] not in instruction.TERMINAL
                or enforcement["site"] not in instruction.SITES
                or any(type(enforcement[name]) is not int or enforcement[name] < 0 for name in ("frame", "step"))
                or not isinstance(enforcement["evidence_digest"], str)
                or not re.fullmatch("[0-9a-f]{64}", enforcement["evidence_digest"])
                or death["phase"] == "pending_issue"
            ):
                raise JournalError("invalid battle enforcement record")
            event_reference.validate(enforcement["origin"])
        link = stage.rules.find_link(player, death["key"])
        from server.state import LinkStatus

        expected_status = (
            LinkStatus.MEMORIAL if death["phase"] == "memorial_complete" else LinkStatus.DEAD
        )
        if (
            link is None
            or link.status != expected_status
            or link.cause != row["cause"]
            or link.killed_at != death["at"]
        ):
            raise JournalError("linked death differs from committed rules")
        if (
            stage.identities.document()["links"].get(death["link_id"], {}).get("members")
            != death["members"]
        ):
            raise JournalError("death logical linkage differs")
        completions = []
        for p, k in ((player, death["key"]), (peer, death["peer_key"])):
            entries = (
                document["components"]
                .get("gen1-memorial-settlement", {})
                .get("entries", {})
                .get(p, [])
            )
            done = any(
                e["death_id"] == death_id
                and (
                    e.get("schema") == "rby-memorial-completed-ref-v1"
                    or e.get("receipt_event") is not None
                )
                for e in entries
            )
            completions.append(done)
            if (k not in stage.rules.pending_memorials[p]) != done or k in stage.rules.party_keys[
                p
            ]:
                raise JournalError("death lost its party/memorial rule obligation")
            if death["phase"] == "memorial_complete" and not done:
                raise JournalError("paired memorial completion lacks both receipts")
        if all(completions) != (death["phase"] == "memorial_complete"):
            raise JournalError("paired memorial receipts differ from death phase")
        if death["receipt_event"] is not None:
            event = death["receipt_event"]
            _identifier(event["operation_id"])
            verify_force_faint_receipt(
                {"cmd": death["command"], "key": death["peer_key"]},
                event["message"]["receipt"],
                variant=initials[peer]["observation"]["source"]["variant"],
                identity=initials[peer]["metadata"]["save_identity"],
            )
    actual = {
        key: value for key, value in stage.barrier.document()["blockers"].items() if value == REASON
    }
    if actual != {
        key: REASON
        for key, death in component["deaths"].items()
        if death["phase"] != "memorial_complete"
    }:
        raise JournalError("linked death obligations lost their recovery holds")


def verify_journal(journal, stage):
    component = stage.document()["components"].get(COMPONENT)
    if component is None:
        return
    for player, proof in list(component["activations"].items()) + [
        (row["player"], row) for row in component["deaths"].values()
    ]:
        entry = proof["engine_record"]
        receipt = semantic_receipt(journal, player, entry, "engine_signals")
        if receipt is None or receipt.result != source_result(entry):
            raise JournalError("rule transition lacks its committed source event")
    for death_id, death in component["deaths"].items():
        entry = death["engine_record"]
        receipt = semantic_receipt(journal, death["player"], entry, "engine_signals")
        if "deferred" in death:
            deferred = death["deferred"]
            jobs = stage.document()["components"].get("gen1-storage-settlement", {}).get("jobs", {})
            original = _recipient_commands(journal, receipt, death["peer"])
            if any(command["body"].get("death_id") == death_id for command in original):
                raise JournalError("deferred death already published its physical mutation")
            terminal = []
            for identifier in deferred["jobs"]:
                job = jobs.get(identifier)
                if job is None or not set(job["keys"]) & {death["player"], death["peer"]}:
                    raise JournalError("deferred faint lost its storage owner")
                beginning = event_reference.resolve(journal, job["origin"])
                if beginning.revision >= receipt.revision:
                    raise JournalError("deferred faint borrowed a later storage job")
                if job["complete"]:
                    writes = [
                        event_reference.resolve(journal, ref) for ref in job["writes"].values()
                    ]
                    if not writes or max(event.revision for event in writes) <= receipt.revision:
                        raise JournalError("faint was deferred behind already completed storage")
                    terminal.extend(job["writes"].values())
            if death["phase"] == "pending_issue":
                if all(
                    jobs[identifier]["complete"] for identifier in deferred["jobs"]
                ) and not _storage_jobs(stage.document(), (death["player"], death["peer"])):
                    raise JournalError("completed storage left its physical faint unissued")
                continue
            issued = _command_origin(journal, death)
            if issued.revision <= receipt.revision or deferred["origin"] not in terminal:
                raise JournalError("deferred faint lacks its later storage completion issuer")
            for identifier in deferred["jobs"]:
                job = jobs[identifier]
                if not job["complete"] or any(
                    event_reference.resolve(journal, ref).revision > issued.revision
                    for ref in job["writes"].values()
                ):
                    raise JournalError("deferred faint preceded storage completion")
            receipt = issued
        commands = _recipient_commands(journal, receipt, death["peer"])
        matches = [command for command in commands if command["body"].get("death_id") == death_id]
        if len(matches) != 1 or matches[0]["body"].get("key") != death["peer_key"]:
            raise JournalError("death lacks exactly one physical obligation")
        command = matches[0]
        if command["body"].get("cmd") != death["command"]:
            raise JournalError("death lost its selected physical command")
        if "deferred" in death and command["body"] != death["deferred"]["command"]:
            raise JournalError("issued faint differs from its retained source command")
        if "enforcement" in death:
            _verify_enforcement(journal, death_id, death)
        if death["phase"] == "pending_faint":
            if command["outcome"] is not None:
                raise JournalError("unrecorded faint completion")
        else:
            acknowledged = death["receipt_event"]
            event = journal.event(
                death["peer"], acknowledged["operation_id"], acknowledged["message"]
            )
            if (
                event is None
                or command["outcome"] != "ACK"
                or command["receipt"] != acknowledged["message"]["receipt"]
            ):
                raise JournalError("faint completion differs from its physical receipt")
