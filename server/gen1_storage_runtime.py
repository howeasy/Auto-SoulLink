"""Source-qualified PC/quarantine jobs with read-both, saved ACK and compensation.

Rule eligibility and geometry stay in their own modules. This coordinator never
uses a client label as a successful disposition or changes logical identities.
"""

import copy

from server import event_reference, gen1_grave_reservations as graves
from server.gen1_faint_runtime import synchronize
from server.gen1_held_faint import verify_checkpoint, verify_owned_checkpoint, verify_owned_host
from server.gen1_initial_observation import inventory
from server.gen1_inventory_observation import verify_entry
from server.gen1_observation_provenance import semantic_receipt
from server.gen1_save_delta import recover_point
from server.gen1_storage import StorageRefusal, expected, prepare, verify_receipt, wire_payload
from server.gen1_storage_policy import invalid_box_party, location, quarantine_box, resolve
from server.held_write_permit import VerifiedHeldWrite
from server.issued_command import issued
from server.operation_scope import command_scope
from server.protocol import digest
from server.protocol_journal import JournalError
from server.retained_physical_record import expand, is_retained, retain, validate_reference
from server.state import LinkStatus

COMPONENT = "gen1-storage-settlement"
REASON = "Synchronized storage requires verified disposition and save"
INVALID_REASON = "Invalid partner box selector requires verified recovery; initiator was restored"
OBSERVE = "rby-storage-observation-v1"
EVIDENCE = "rby-held-storage-evidence-v1"
KEY = digest({"component": COMPONENT})[:32]


def _summary(job):
    if job["complete"] is not True:
        raise JournalError("only physically completed storage can be retained")
    result = {
        k: copy.deepcopy(v) for k, v in job.items() if k not in ("source", "reads", "prepared")
    }
    result["frames"] = {p: row["receipt"]["host"]["frame"] for p, row in job["reads"].items()}
    return result


def expand_entry(journal, entry):
    return expand(journal, entry, namespace=COMPONENT, summarize=_summary)


def _completion_revision(journal, job):
    value = job.get("completed_revision")
    return (
        value
        if value is not None
        else max(event_reference.resolve(journal, ref).revision for ref in job["writes"].values())
    )


def _frame(job, player):
    return (
        job["frames"][player]
        if is_retained(job)
        else job["reads"][player]["receipt"]["host"]["frame"]
    )


def read_body(job, player):
    return {"cmd": "storage_observe", "job_id": job["id"], "key": job["keys"][player]}


def write_body(job, player):
    return {
        "cmd": "storage_apply",
        "job_id": job["id"],
        "key": job["keys"][player],
        "payload": wire_payload(job["prepared"][player]),
    }


def blocker(identifier):
    return digest({"storage_job": identifier})[:32]


def _retired(document, player, key):
    return any(
        row["key"] == key and row["receipt_operation"] is not None
        for row in document["components"].get("gen1-acquisition-retirement", {}).get(player, [])
    )


def _component(document):
    return document["components"].setdefault(COMPONENT, {"jobs": {}, "handled": []})


def _point(journal, document, player):
    observed = document["components"]["gen1-inventory-observations"][player]["observation"]
    result = observed["source"]
    jobs = [
        job
        for job in document["components"].get(COMPONENT, {}).get("jobs", {}).values()
        if job["complete"] and player in job["writes"] and _frame(job, player) >= observed["frame"]
    ]
    if jobs:
        job = max(jobs, key=lambda value: _completion_revision(journal, value))
        result = expand_entry(journal, job)["prepared"][player]["after"]
    return result


def _source_anchor(journal, document, player, point, head, *, anchor=None):
    if anchor is None:
        observed = document["components"]["gen1-inventory-observations"][player]["observation"][
            "frame"
        ]
        jobs = [
            job
            for job in document["components"].get(COMPONENT, {}).get("jobs", {}).values()
            if job["complete"] and player in job["writes"] and _frame(job, player) >= observed
        ]
        for reference in sorted(
            jobs, key=lambda value: _completion_revision(journal, value), reverse=True
        ):
            job = expand_entry(journal, reference)
            if point == job["prepared"][player]["after"]:
                anchor = {"kind": "storage", "job_id": job["id"], "event": job["writes"][player]}
                break
    if anchor is not None and anchor.get("kind") == "storage":
        job = document["components"][COMPONENT]["jobs"].get(anchor["job_id"])
        if job is not None:
            job = expand_entry(journal, job)
        event = event_reference.resolve(journal, anchor["event"])
        if (
            job is None
            or not job["complete"]
            or job["writes"].get(player) != anchor["event"]
            or event.request.get("receipt", {}).get("after") != point
            or point != job["prepared"][player]["after"]
        ):
            raise JournalError("storage successor preimage differs from prior saved ACK")
        return copy.deepcopy(anchor)
    return graves.check_preimage(journal, document, player, point, head, source=anchor)


def _verify_pc(entry, key, identity):
    moves = [m for m in entry["transition"]["movements"] if m["key"] == key]
    if len(moves) != 1:
        raise JournalError("one canonical PC source movement required")
    direction = "deposit" if moves[0]["after"]["location"] == "box" else "withdraw"
    projected = expected(
        entry["before"]["source"],
        key,
        direction,
        identity=identity,
        reserved_boxes=(),
        destination_box=moves[0]["after"]["box"] if direction == "deposit" else None,
    )

    def members(point):
        return inventory(point, identity)["members"]

    if members(projected) != members(entry["observation"]["source"]):
        raise JournalError("observed PC containers differ from canonical source transformation")
    if projected["variant"] == "yellow" and direction == "deposit":
        from server.gen1_full_save import SYMBOLS

        symbols = SYMBOLS["pokeyellow"]
        after = bytes.fromhex(entry["observation"]["source"]["fields"]["main"])
        predicted = bytes.fromhex(projected["fields"]["main"])
        for name in ("wPikachuHappiness", "wPikachuMood"):
            offset = symbols[name] - symbols["wMainDataStart"]
            if after[offset] != predicted[offset]:
                raise JournalError("observed Yellow deposit effect differs")


def _busy(document, players):
    return (
        any(
            not j["complete"] and set(j["keys"]) & set(players)
            for j in document["components"].get(COMPONENT, {}).get("jobs", {}).values()
        )
        or any(
            graves.memorial_busy(document, p) or graves.retirement_busy(document, p)
            for p in players
        )
        or any(
            death["phase"] in ("pending_issue", "pending_faint")
            and {death["player"], death["peer"]} & set(players)
            for death in document["components"]
            .get("gen1-faint-settlement", {})
            .get("deaths", {})
            .values()
        )
    )


def busy(document, players):
    """Unfinished source/write ownership for other physical job coordinators."""
    return any(
        not j["complete"] and set(j["keys"]) & set(players)
        for j in document["components"].get(COMPONENT, {}).get("jobs", {}).values()
    )


def _job(stage, document, origin, kind, keys, *, actor=None, destination=None, source=None):
    identifier = digest({"origin": origin, "kind": kind, "keys": keys})[:32]
    component = _component(document)
    if identifier in component["jobs"]:
        return {"a": [], "b": []}
    if _busy(document, keys):
        raise JournalError("physical storage ownership is already busy")
    if kind != "rebuild":
        # Plan priority gate (C3): unrelated PC/acquisition storage must not take ownership of a
        # key a pending rebuild plan is about to move.
        from server.gen1_rebuild_runtime import plan_reserved

        if plan_reserved(document, keys.values()):
            raise JournalError("physical storage ownership is reserved for a pending rebuild")
    from server.gen1_starter_settlement import context

    members = {
        p: stage.identities.resolve(
            context(document["components"]["gen1-initial-observations"][p], p), key
        )
        for p, key in keys.items()
    }
    if None in members.values():
        raise JournalError("storage target lacks its source-acquired logical identity")
    links = [
        identifier
        for identifier, link in document["identities"]["links"].items()
        if set(link["members"]) == set(members.values())
    ]
    if len(keys) == 2 and len(links) != 1:
        raise JournalError("paired storage target differs from logical linkage")
    job = {
        "id": identifier,
        "origin": copy.deepcopy(origin),
        "kind": kind,
        "keys": copy.deepcopy(keys),
        "actor": actor,
        "destination": destination,
        "source": copy.deepcopy(source),
        "reads": {},
        "prepared": {},
        "resolution": None,
        "write_origin": None,
        "writes": {},
        "complete": False,
        "death_abort": None,
        "members": members,
        "link_id": links[0] if len(keys) == 2 else None,
        "blocked_reason": None,
        "completed_revision": None,
    }
    component["jobs"][identifier] = job
    holds = stage.barrier.document()["blockers"]
    holds[blocker(identifier)] = REASON
    stage.barrier.set_blockers(holds)
    for p, key in keys.items():
        stage.rules.party_keys[p].discard(key)
    return {p: [read_body(job, p)] if p in keys else [] for p in ("a", "b")}


def stage(runtime, state, document, player, operation, message):
    """Call once after inventory/acquisition rules inside the same observation batch commit."""
    if message.get("event") != "observation":
        raise JournalError("storage requires a settled observation batch")
    checkpoint = document["components"].get("gen1-inventory-observations", {}).get(player)
    if checkpoint is None or checkpoint["operation_id"] != operation:
        return {"commands": {"a": [], "b": []}, "records": []}
    origin = event_reference.make(player, operation, message)
    if checkpoint["observation"] != message["inventory"]:
        raise JournalError("storage batch differs from its staged inventory")
    commands = {"a": [], "b": []}
    component = _component(document)
    movements = checkpoint["transition"]["movements"]
    relevant = []
    for movement in movements:
        if movement["before"]["location"] == movement["after"]["location"]:
            continue
        key = movement["key"]
        linked = state.rules.find_link(player, key)
        pending = any(
            rows.get(player) is not None and rows[player].key == key
            for rows in state.rules.pending_captures.values()
        )
        if (
            linked is not None
            and (
                linked.status == LinkStatus.ALIVE
                or movement["after"]["location"] == "party"
                and linked.status in (LinkStatus.DEAD, LinkStatus.MEMORIAL)
            )
            or pending
            or movement["after"]["location"] == "party"
            and _retired(document, player, key)
        ):
            relevant.append((movement, linked, pending))
    if relevant:
        if (
            len(relevant) != 1
            or checkpoint["transition"]["added"]
            or checkpoint["transition"]["removed"]
        ):
            raise JournalError("ambiguous PC container changes require reconciliation")
        movement, linked, pending = relevant[0]
        _verify_pc(checkpoint, movement["key"], state.rules.player_identity[player])
        keys = {player: movement["key"]}
        destination = movement["after"]["location"]
        archive_return = (
            linked is not None and linked.status in (LinkStatus.DEAD, LinkStatus.MEMORIAL)
        ) or _retired(document, player, movement["key"])
        if linked is not None and not archive_return:
            keys = {p: getattr(linked, p).key for p in ("a", "b")}
        elif destination != "party":
            # An already observed pending deposit is its own physical quarantine.
            state.rules.party_keys[player].discard(movement["key"])
            relevant = []
        if relevant:
            commands = _job(
                state,
                document,
                origin,
                "archive_return" if archive_return else "pc",
                keys,
                actor=player,
                destination=destination,
                source=checkpoint,
            )
    if not relevant:
        commands = schedule_pending(runtime, state, document, origin, request=message)
    synchronize(state, document)
    return {
        "commands": commands,
        "records": [{"namespace": COMPONENT, "key": KEY, "value": copy.deepcopy(component)}],
    }


def _birth(journal, row, *, origin=None, request=None):
    from server.gen1_acquisition_runtime import receipts_of

    ref = row["source_ref"]
    source = (
        request
        if ref["event"] == origin
        else event_reference.resolve(journal, ref["event"]).request
    )
    wire = receipts_of(source)[ref["index"]]
    if wire["kind"] == "grant":
        before, after = wire["receipt"]["call"]["point"], wire["receipt"]["return"]["point"]
    elif wire["kind"] == "capture":
        before, after = (
            wire["receipt"]["receipt"]["begin"]["point"],
            wire["receipt"]["receipt"]["end"]["point"],
        )
    else:
        raise JournalError("boxed reserved acquisition lacks capture/grant birth source")
    if before["current_box"] & 127 != 11 or after["current_box"] & 127 != 11:
        raise JournalError("reserved acquisition birth was in another box")
    return {"before": before["box_hex"], "after": after["box_hex"]}


def schedule_pending(runtime, state, document, origin, *, request=None):
    commands = {"a": [], "b": []}
    component = _component(document)
    entries = document["components"].get("gen1-acquisition-settlement", {})
    for p, entry in entries.items():
        for row in entry["settled"]:
            token = p + ":" + row["acquisition_id"]
            if token in component["handled"] or row["rule"] not in (
                "exempt_grant",
                "clause_checked",
            ):
                continue
            if row["violation"] is not None:
                component["handled"].append(token)
                continue
            key = row["fact"]["key"]
            if not _busy(document, [p]):
                place, roster = location(
                    _point(runtime.journal, document, p), key, state.rules.player_identity[p]
                )
                target = next(m for m in roster["members"] if m["key"] == key)
                if place == "box" and target["box"] == 11:
                    more = _job(
                        state,
                        document,
                        origin,
                        "grave_evict",
                        {p: key},
                        actor=p,
                        source={
                            "acquisition": token,
                            "birth": _birth(runtime.journal, row, origin=origin, request=request),
                        },
                    )
                    for side in ("a", "b"):
                        commands[side].extend(more[side])
                    continue
            link = state.rules.find_link(p, key)
            if link is not None and link.status == LinkStatus.ALIVE:
                keys = {side: getattr(link, side).key for side in ("a", "b")}
                if _busy(document, keys):
                    continue
                more = _job(state, document, origin, "linked", keys, source={"acquisition": token})
                # One physical synchronization handles both acquisition rows.
                for side, other in entries.items():
                    for candidate in other["settled"]:
                        if candidate["fact"]["key"] == keys[side]:
                            other_token = side + ":" + candidate["acquisition_id"]
                            if other_token not in component["handled"]:
                                component["handled"].append(other_token)
            else:
                if _busy(document, [p]):
                    continue
                place, roster = location(
                    _point(runtime.journal, document, p), key, state.rules.player_identity[p]
                )
                if place == "box":
                    state.rules.party_keys[p].discard(key)
                    more = {"a": [], "b": []}
                elif row["rule"] == "exempt_grant" or roster["party_count"] == 1:
                    state.rules.party_keys[p].add(key)
                    more = {"a": [], "b": []}
                else:
                    more = _job(
                        state,
                        document,
                        origin,
                        "quarantine",
                        {p: key},
                        source={"acquisition": token},
                    )
                component["handled"].append(token)
            for side in ("a", "b"):
                commands[side].extend(more[side])
    return commands


def _observation(command, receipt, document, player, *, historical=False):
    fields = {
        "schema",
        "command_id",
        "command_sequence",
        "context_generation",
        "final_sha1",
        "host",
        "checkpoint",
        "point",
    }
    if not isinstance(receipt, dict) or set(receipt) != fields or receipt["schema"] != OBSERVE:
        raise JournalError("complete held storage observation required")
    initial = document["components"]["gen1-initial-observations"][player]
    verify_owned_host(player, command, receipt, document, initial["binding"], historical=historical)
    if receipt["point"]["variant"] != initial["observation"]["source"]["variant"]:
        raise JournalError("storage cartridge changed")
    checkpoint = receipt["checkpoint"]
    if (
        not isinstance(checkpoint, dict)
        or set(checkpoint) != {"pc", "sp", "rom", "system"}
        or any(
            type(checkpoint[k]) is not int or not 0 <= checkpoint[k] <= 65535 for k in ("pc", "sp")
        )
        or any(
            not isinstance(checkpoint[k], dict)
            or not 1 <= len(checkpoint[k]) <= 64
            or any(
                not isinstance(a, str)
                or not a.isdecimal()
                or not 0 <= int(a) <= 65535
                or type(v) is not int
                or not 0 <= v <= 255
                for a, v in checkpoint[k].items()
            )
            for k in ("rom", "system")
        )
    ):
        raise JournalError("bounded raw storage read checkpoint required")
    if (
        invalid_box_party(
            receipt["point"], command["body"]["key"], initial["metadata"]["save_identity"]
        )
        is None
    ):
        inventory(receipt["point"], initial["metadata"]["save_identity"])


def _prepare(job, document):
    points = {p: row["receipt"]["point"] for p, row in job["reads"].items()}
    identities = {
        p: document["components"]["gen1-initial-observations"][p]["metadata"]["save_identity"]
        for p in points
    }
    archive_box = None
    if job["kind"] == "archive_return":
        moves = [
            m
            for m in job["source"]["transition"]["movements"]
            if m["key"] == job["keys"][job["actor"]]
        ]
        if len(moves) != 1 or moves[0]["before"]["location"] != "box":
            raise JournalError("archive return requires its exact original box")
        archive_box = moves[0]["before"]["box"]
    if (
        job["kind"] in ("pc", "archive_return")
        and points[job["actor"]] != job["source"]["observation"]["source"]
    ):
        raise JournalError("PC initiator no longer matches its observed complete preimage")
    if job["kind"] in ("pc", "archive_return"):
        actor = job["actor"]
        source = job["source"]["before"]["source"]
        if (
            archive_box == 11
            or inventory(job["source"]["observation"]["source"], identities[actor])["current_box"]
            == 11
        ) and job["reads"][actor]["grave_head"] is not None:
            from server.gen1_memorial_policy import grave_digest

            if grave_digest(source) != job["reads"][actor]["grave_head"]["reservation_digest"]:
                raise JournalError("reserved-box deposit lost its exact prior reservation")
    if job["kind"] == "grave_evict":
        from server.gen1_memorial_policy import grave_digest
        from server.gen1_retirement import prepend_box

        actor = job["actor"]
        birth = job["source"]["birth"]
        target = next(
            m
            for m in inventory(points[actor], identities[actor])["members"]
            if m["key"] == job["keys"][actor]
        )
        if (
            target["location"] != "box"
            or target["box"] != 11
            or target["slot"] != 0
            or points[actor]["fields"]["box"] != birth["after"]
            or prepend_box(birth["before"], bytes.fromhex(target["box_blob_hex"])).hex().upper()
            != birth["after"]
        ):
            raise JournalError("reserved boxed acquisition differs from exact birth preimage")
        head = job["reads"][actor]["grave_head"]
        if head is not None:
            before = copy.deepcopy(points[actor])
            before["fields"]["box"] = birth["before"]
            if grave_digest(before) != head["reservation_digest"]:
                raise JournalError("reserved boxed birth replaced prior archive ownership")
    directions, refusal = resolve(job, points, identities)
    if job.get("death_abort") is not None:
        directions = dict.fromkeys(job["keys"], "confirm")
        directions[job["actor"]] = "withdraw" if job["destination"] == "box" else "deposit"
        refusal = "linked-death-before-storage-write"
    for p in points:
        if refusal == "invalid-current-box" and p != job["actor"]:
            continue
        try:
            verify_checkpoint(job["reads"][p]["receipt"]["checkpoint"], points[p]["variant"])
        except JournalError as exc:
            if job["kind"] != "pc" or p == job["actor"]:
                raise JournalError(
                    "storage actor requires a safe context for compensation"
                ) from exc
            directions = {job["actor"]: "withdraw" if job["destination"] == "box" else "deposit"}
            refusal = "unsafe-peer-context"
    prepared = {
        p: prepare(
            points[p],
            job["keys"][p],
            direction,
            identity=identities[p],
            context_generation=job["reads"][p]["receipt"]["context_generation"],
            final_sha1=job["reads"][p]["receipt"]["final_sha1"],
            frame=job["reads"][p]["receipt"]["host"]["frame"],
            reserved_boxes=()
            if job["kind"] == "grave_evict"
            or job["kind"] in ("pc", "archive_return")
            and p == job["actor"]
            and (
                archive_box == 11
                or inventory(job["source"]["observation"]["source"], identities[p])["current_box"]
                == 11
            )
            else (11,),
            destination_box=archive_box
            if job["kind"] == "archive_return"
            else quarantine_box(points[p], job["keys"][p], identities[p], direction="relocate")
            if job["kind"] == "grave_evict"
            else quarantine_box(points[p], job["keys"][p], identities[p])
            if job["kind"] == "quarantine" and direction == "deposit"
            else None,
        )
        for p, direction in directions.items()
    }
    return prepared, {"directions": directions, "refusal": refusal}


def acknowledge(runtime, player, operation, message):
    replay = runtime.journal.event(player, operation, message)
    if replay is not None:
        return replay.result
    state = runtime.state()
    document = state.document()
    if (
        set(message) != {"event", "command_id", "command_sequence", "outcome", "receipt"}
        or message["outcome"] != "ACK"
    ):
        raise JournalError("typed storage command ACK required")
    pending = runtime.journal.pending_ids(player)
    if not pending or pending[0] != message["command_id"]:
        raise JournalError("storage ACK must own its oldest command")
    command = runtime.journal.command(player, message["command_id"])
    if command["command_sequence"] != message["command_sequence"]:
        raise JournalError("storage ACK sequence differs")
    component = _component(document)
    job = component["jobs"].get(command["body"].get("job_id"))
    if job is None or job["complete"] or player not in job["keys"]:
        raise JournalError("pending owned storage job required")
    reference = event_reference.make(player, operation, message)
    commands = {"a": [], "b": []}
    extra_records = []
    if command["body"] == read_body(job, player) and player not in job["reads"]:
        _observation(command, message["receipt"], document, player)
        # A prepared read cannot survive an intervening authorized party write.
        from server.gen1_hud_feedback import pending_physical_ids

        if len(pending_physical_ids(runtime.journal, player)) != 1:
            raise JournalError("storage read must close after other physical obligations")
        head = graves.latest(runtime.journal, document, player)
        anchor = _source_anchor(
            runtime.journal, document, player, message["receipt"]["point"], head
        )
        job["reads"][player] = {
            "event": reference,
            "receipt": copy.deepcopy(message["receipt"]),
            "grave_head": head,
            "source_anchor": anchor,
        }
        if set(job["reads"]) == set(job["keys"]):
            for side, prior in job["reads"].items():
                expected_pending = (command["command_id"],) if side == player else ()
                if pending_physical_ids(runtime.journal, side) != expected_pending:
                    raise JournalError("storage plan cannot overtake pending physical commands")
                original = issued(runtime.journal, side, job["origin"], read_body(job, side))
                _observation(original, prior["receipt"], document, side)
            if job["kind"] == "pc":
                matches = [
                    identifier
                    for identifier, death in document["components"]
                    .get("gen1-faint-settlement", {})
                    .get("deaths", {})
                    .items()
                    if job["keys"].get(death["player"]) == death["key"]
                    and job["keys"].get(death["peer"]) == death["peer_key"]
                ]
                if matches:
                    job["death_abort"] = matches[-1]
            try:
                job["prepared"], job["resolution"] = _prepare(job, document)
            except StorageRefusal as exc:
                job["blocked_reason"] = exc.reason
                job["prepared"] = {}
                job["resolution"] = None
            job["write_origin"] = reference
            commands = {p: [write_body(job, p)] if p in job["prepared"] else [] for p in ("a", "b")}
    elif (
        player in job["prepared"]
        and command["body"] == write_body(job, player)
        and player not in job["writes"]
    ):
        verify_receipt(
            command,
            message["receipt"],
            job["prepared"][player],
            identity=state.rules.player_identity[player],
        )
        p = job["prepared"][player]
        if p["reserved_boxes"] == [] and job["reads"][player]["grave_head"] is not None:
            extra_records.append(
                graves.advance(
                    runtime.journal,
                    document,
                    player,
                    operation,
                    message,
                    p["after"],
                    kind="storage_compensation",
                    target=job["id"],
                    previous=job["reads"][player]["grave_head"],
                    revision=state.journal_revision + 1,
                )
            )
        job["writes"][player] = reference
        if set(job["writes"]) == set(job["prepared"]):
            holds = state.barrier.document()["blockers"]
            if holds.get(blocker(job["id"])) != REASON:
                raise JournalError("storage job lost its exact recovery hold")
            if job["resolution"]["refusal"] == "invalid-current-box":
                holds[blocker(job["id"])] = INVALID_REASON
            else:
                del holds[blocker(job["id"])]
            state.barrier.set_blockers(holds)
            job["complete"] = True
            job["completed_revision"] = state.journal_revision + 1
            for side, key in job["keys"].items():
                if side not in job["prepared"]:
                    if (
                        job["resolution"]["refusal"] == "unsafe-peer-context"
                        and key not in state.rules.pending_memorials[side]
                    ):
                        state.rules.party_keys[side].add(key)
                    continue
                place, _roster = location(
                    job["prepared"][side]["after"], key, state.rules.player_identity[side]
                )
                if (
                    place == "party"
                    and job["kind"] not in ("quarantine", "archive_return", "grave_evict")
                    and key not in state.rules.pending_memorials[side]
                ):
                    state.rules.party_keys[side].add(key)
                else:
                    state.rules.party_keys[side].discard(key)
                from server.gen1_party_codec import PartyCodec

                source = job["prepared"][side]["after"]
                party = [
                    PartyCodec(source["variant"]).validate_blob(bytes.fromhex(r["blob_hex"]))
                    for r in inventory(source, state.rules.player_identity[side])["members"]
                    if r["location"] == "party"
                ]
                state.rules.party_size[side] = len(party)
                state.rules.partner_blobs[side] = [
                    {
                        "slot": i,
                        "key": m.key,
                        "species_id": m.species_id,
                        "level": m.level,
                        "blob": m.raw,
                    }
                    for i, m in enumerate(party)
                ]
            from server.gen1_faint_runtime import schedule_deferred

            deferred, deferred_records = schedule_deferred(
                runtime,
                state,
                document,
                {"player": player, "operation_id": operation, "message": message},
            )
            extra_records.extend(deferred_records)
            commands = schedule_pending(runtime, state, document, reference)
            for side in ("a", "b"):
                commands[side] = deferred[side] + commands[side]
            if job["kind"] == "rebuild":
                from server.gen1_rebuild_runtime import completed as rebuild_completed

                more = rebuild_completed(state, document, job)
            else:
                from server.gen1_rebuild_runtime import schedule_rebuild

                # A completed non-rebuild job may have just cleared the physical ownership a
                # deferred rebuild plan was waiting on (spec (2)/(3)): try to advance it.
                more = schedule_rebuild(state, document, reference)
            for side in ("a", "b"):
                commands[side] = commands[side] + more[side]
    else:
        raise JournalError("storage ACK differs from its durable phase")
    if job["complete"]:
        key = digest({"component": COMPONENT, "completed_job": job["id"]})[:32]
        compact, record = retain(COMPONENT, key, state.journal_revision + 1, job, _summary(job))
        component["jobs"][job["id"]] = compact
        extra_records.append(record)
    synchronize(state, document)
    return runtime.journal.commit(
        player,
        operation,
        message,
        expected_revision=state.journal_revision,
        state=document,
        commands=commands,
        result={"ack": "ACK"},
        records=[
            {"namespace": COMPONENT, "key": KEY, "value": copy.deepcopy(component)},
            *extra_records,
        ],
        acknowledgements=[
            {
                "player": player,
                "command_id": command["command_id"],
                "outcome": "ACK",
                "receipt": message["receipt"],
            }
        ],
    ).result


def verify_state(state):
    document = state.document()
    component = document["components"].get(COMPONENT)
    if component is None:
        return
    if set(component) != {"jobs", "handled"} or len(component["handled"]) != len(
        set(component["handled"])
    ):
        raise JournalError("invalid storage settlement component")
    expected_holds = {}
    for identifier, job in component["jobs"].items():
        if (
            identifier != job["id"]
            or identifier
            != digest({"origin": job["origin"], "kind": job["kind"], "keys": job["keys"]})[:32]
        ):
            raise JournalError("storage job identity differs from source")
        event_reference.validate(job["origin"])
        if job["kind"] == "archive_return":
            actor = job["actor"]
            key = job["keys"][actor]
            link = state.rules.find_link(actor, key)
            if (
                (link is None or link.status not in (LinkStatus.DEAD, LinkStatus.MEMORIAL))
                and not _retired(document, actor, key)
                or key in state.rules.party_keys[actor]
            ):
                raise JournalError("archive return lost its dead logical member policy")
        if set(job["members"]) != set(job["keys"]) or any(
            member not in state.identities.historical_members(p, job["keys"][p])
            for p, member in job["members"].items()
        ):
            raise JournalError("storage key differs from its logical member lineage")
        if len(job["keys"]) == 2:
            link = document["identities"]["links"].get(job["link_id"])
            if link is None or not any(
                set(row) == set(job["members"].values())
                for row in [link["members"], *(h["members"] for h in link["history"])]
            ):
                raise JournalError("storage pair lacks shared logical link history")
        if is_retained(job):
            reference = validate_reference(job["retained"])
            fields = {
                "id",
                "origin",
                "kind",
                "keys",
                "actor",
                "destination",
                "resolution",
                "write_origin",
                "writes",
                "complete",
                "death_abort",
                "members",
                "link_id",
                "blocked_reason",
                "completed_revision",
                "frames",
                "retained",
            }
            if (
                set(job) != fields
                or job["complete"] is not True
                or job["blocked_reason"] is not None
                or reference["namespace"] != COMPONENT
                or reference["record_key"]
                != digest({"component": COMPONENT, "completed_job": identifier})[:32]
                or job["completed_revision"] != reference["record_revision"]
                or set(job["frames"]) != set(job["keys"])
                or any(type(frame) is not int or frame < 0 for frame in job["frames"].values())
                or not job["writes"]
                or set(job["writes"]) != set(job["resolution"]["directions"])
            ):
                raise JournalError("compact storage completion lost its exact phase/reference")
            for player, ref in job["writes"].items():
                if event_reference.validate(ref)["player"] != player:
                    raise JournalError("compact storage receipt belongs to another owner")
            if job["resolution"]["refusal"] == "invalid-current-box":
                expected_holds[blocker(identifier)] = INVALID_REASON
            continue
        if (
            not job["keys"]
            or set(job["keys"]) - {"a", "b"}
            or set(job["reads"]) - set(job["keys"])
            or set(job["writes"]) - set(job["keys"])
        ):
            raise JournalError("storage job has foreign participant")
        if job["prepared"]:
            prepared, resolution = _prepare(job, document)
            if prepared != job["prepared"] or resolution != job["resolution"]:
                raise JournalError("storage policy or prepared image differs")
        elif job.get("blocked_reason") is not None:
            try:
                _prepare(job, document)
            except StorageRefusal as exc:
                if exc.reason != job["blocked_reason"]:
                    raise JournalError("storage capacity refusal changed") from exc
            else:
                raise JournalError("storage blocked without a proved refusal")
        if job["complete"] != (
            bool(job["prepared"]) and set(job["writes"]) == set(job["prepared"])
        ):
            raise JournalError("storage completion lacks both physical ACKs")
        if not job["complete"]:
            expected_holds[blocker(identifier)] = REASON
            if any(key in state.rules.party_keys[p] for p, key in job["keys"].items()):
                raise JournalError("pending storage key remains usable")
        elif job["resolution"]["refusal"] == "invalid-current-box":
            expected_holds[blocker(identifier)] = INVALID_REASON
    actual = {
        k: v
        for k, v in state.barrier.document()["blockers"].items()
        if v in (REASON, INVALID_REASON)
    }
    if actual != expected_holds:
        raise JournalError("storage recovery holds differ from pending jobs")


def verify_journal(journal, state):
    document = state.document()
    component = document["components"].get(COMPONENT)
    if component is None:
        return
    graves.verify_journal(journal, document)
    record = journal.record(COMPONENT, KEY)
    if record is None or record.value != component:
        raise JournalError("storage component differs from atomic journal record")
    for reference in component["jobs"].values():
        job = expand_entry(journal, reference)
        if is_retained(reference):
            if (
                max(
                    event_reference.resolve(journal, ref).revision for ref in job["writes"].values()
                )
                != reference["retained"]["record_revision"]
            ):
                raise JournalError("retained storage record is not its final physical ACK revision")
            prepared, resolution = _prepare(job, document)
            if prepared != job["prepared"] or resolution != job["resolution"]:
                raise JournalError("retained storage policy differs from original evidence")
        origin = event_reference.resolve(journal, job["origin"])
        if origin.request.get("event") == "observation":
            if origin.result.get("inventory_transition_digest") is None:
                raise JournalError("storage source batch recorded no checkpoint")
        elif origin.request.get("event") == "command_ack":
            prior = journal.command(job["origin"]["player"], origin.request.get("command_id"))
            prior_job = component["jobs"].get(prior["body"].get("job_id"))
            if (
                prior["body"].get("cmd") != "storage_apply"
                or prior_job is None
                or not prior_job["complete"]
                or prior_job["writes"].get(job["origin"]["player"]) != job["origin"]
            ):
                raise JournalError("storage follow-on lacks prior physical completion")
        else:
            raise JournalError(
                "storage source was not an accounted observation or saved continuation"
            )
        if job.get("death_abort") is not None:
            death = (
                document["components"]
                .get("gen1-faint-settlement", {})
                .get("deaths", {})
                .get(job["death_abort"])
            )
            if (
                death is None
                or job["keys"].get(death["player"]) != death["key"]
                or job["keys"].get(death["peer"]) != death["peer_key"]
            ):
                raise JournalError("storage compensation lacks its exact linked death")
            death_event = semantic_receipt(
                journal, death["player"], death["engine_record"], "engine_signals"
            )
            if (
                job["write_origin"] is None
                or death_event.revision
                >= event_reference.resolve(journal, job["write_origin"]).revision
            ):
                raise JournalError("storage compensation borrowed a later linked death")
        if job["kind"] in ("pc", "archive_return"):
            actor = job["actor"]
            entry = job["source"]
            initial = document["components"]["gen1-initial-observations"][actor]
            verify_entry(entry, initial)
            semantic_receipt(journal, actor, entry, "inventory_observation")
            _verify_pc(entry, job["keys"][actor], initial["metadata"]["save_identity"])
            moves = [m for m in entry["transition"]["movements"] if m["key"] == job["keys"][actor]]
            if len(moves) != 1 or moves[0]["after"]["location"] != job["destination"]:
                raise JournalError("storage PC source lacks its exact movement")
        else:
            token = job["source"]["acquisition"]
            player, identifier = token.split(":")
            rows = document["components"]["gen1-acquisition-settlement"][player]["settled"]
            matched = [r for r in rows if r["acquisition_id"] == identifier]
            if len(matched) != 1 or matched[0]["fact"]["key"] != job["keys"][player]:
                raise JournalError("storage acquisition source differs")
            if (
                job["kind"] == "grave_evict"
                and _birth(journal, matched[0]) != job["source"]["birth"]
            ):
                raise JournalError("reserved relocation lost its exact source receipt")
        for player in job["keys"]:
            command = issued(journal, player, job["origin"], read_body(job, player))
            read = job["reads"].get(player)
            if read is None:
                if command["outcome"] is not None:
                    raise JournalError("unrecorded storage read")
                continue
            event = event_reference.resolve(journal, read["event"])
            if (
                event.request.get("command_id") != command["command_id"]
                or command["outcome"] != "ACK"
                or command["receipt"] != read["receipt"]
                or event.request.get("receipt") != read["receipt"]
                or event.result != {"ack": "ACK"}
            ):
                raise JournalError("storage read lost its exact ACK")
            _observation(command, read["receipt"], document, player, historical=True)
            if read["source_anchor"].get("kind") == "storage":
                if (
                    event_reference.resolve(journal, read["source_anchor"]["event"]).revision
                    >= event.revision
                ):
                    raise JournalError("storage preimage borrows a future completion")
            else:
                graves.before_preparation(
                    journal, read["grave_head"], read["source_anchor"], event.revision
                )
            _source_anchor(
                journal,
                document,
                player,
                read["receipt"]["point"],
                read["grave_head"],
                anchor=read["source_anchor"],
            )
            if player not in job["prepared"]:
                continue
            command = issued(journal, player, job["write_origin"], write_body(job, player))
            if player not in job["writes"]:
                if command["outcome"] is not None:
                    raise JournalError("unrecorded storage write")
                continue
            event = event_reference.resolve(journal, job["writes"][player])
            if (
                event.request.get("command_id") != command["command_id"]
                or command["outcome"] != "ACK"
                or event.request.get("receipt") != command["receipt"]
                or event.result != {"ack": "ACK"}
            ):
                raise JournalError("storage write lost its exact ACK")
            verify_receipt(
                command,
                command["receipt"],
                job["prepared"][player],
                identity=state.rules.player_identity[player],
            )


def verify_operation(player, command, evidence, document, binding):
    if not isinstance(evidence, dict) or evidence.get("schema") != EVIDENCE:
        raise JournalError("typed held storage evidence required")
    verify_owned_checkpoint(player, command, evidence, document, binding)
    job = document["components"][COMPONENT]["jobs"].get(command["body"].get("job_id"))
    if job is None or job["complete"] or command["body"] != write_body(job, player):
        raise JournalError("held storage command differs from owned job")
    if evidence.get("intent") != {
        "schema": "rby-storage-intent-v1",
        "body_digest": digest(command["body"]),
    }:
        raise JournalError("storage durable intent differs")
    p = job["prepared"][player]
    phase = evidence.get("phase")
    if evidence["host"]["frame"] != p["frame"]:
        raise JournalError("storage frame changed after read")
    if phase == "storage_repair":
        recover_point(evidence["current"], wire_payload(p))
    elif phase in ("storage_apply", "storage_save"):
        if evidence["current"] != p["before" if phase == "storage_apply" else "after"]:
            raise JournalError("held storage current image differs")
    else:
        raise JournalError("unknown held storage phase")
    return VerifiedHeldWrite(
        command_scope(command, binding, phase=phase), digest(evidence), 1000, digest(document)
    )
