"""Whiteout automatic rebuild through the storage-job machinery (C3).

state.py's shared engine already DECIDES which alive boxed pairs to restore after a whiteout
(``SoulLinkState._plan_rebuild``/``_queue_rebuild_commands``, persisted as ``rebuild_pending``)
and already owns the *finish* line (``sync_retrieve_done`` -> ``party_keys``/``_maybe_finish_rebuild``
-> ``rebuild_done``). That legacy path assumes the Lua client executes the party-swap itself and
reports back; this module does not re-decide anything it plans -- it wraps the shared pick in a
durable, replay-safe plan and drives the ACTUAL physical retrieval through the same held
storage-job machinery every other PC operation uses (``gen1_storage_runtime._job``), so a rebuild
is a real, verified, two-sided write instead of a trusted client claim. Only once both writes are
verified does it feed the shared engine its own ``sync_retrieve_done`` signal.

Boundary (explicit, not solved here): blackout heals a fainted party to 1 HP before the overworld
loop resumes, and a freshly healed but logically DEAD target refuses memorial
(``gen1_memorial.py:57-58,68-69``). Re-fainting a healed dead target, or intercepting the heal
itself, is a separate authority and is not covered by this module's ordering.
"""
from server.gen1_faint_runtime import _link_identity
from server.gen1_initial_observation import COMPONENT as INITIAL
from server.protocol import digest
from server.protocol_journal import JournalError

COMPONENT = "gen1-rebuild"
SCHEMA = "gen1-rebuild-plan-v1"
PAIR_FIELDS = frozenset({"ordinal", "keys", "link_id", "members", "source_refs", "job_id", "completed_ref"})
PLAN_FIELDS = frozenset({"schema", "initiator", "source", "ordered_pairs", "phase", "blocked_reason"})


def _partner(player):
    return "b" if player == "a" else "a"


def _component(document):
    return document["components"].setdefault(COMPONENT, {"plans": {}})


def plan(stage, document, player, entry, index, captured, *, whiteout_id):
    """Persist the shared engine's own rebuild pick as a durable, replay-safe plan.

    ``stage.rules.rebuild_pending[player]`` is set by ``state.py``'s ``_handle_whiteout``
    (already invoked by ``settle_whiteout`` before this call) whenever any alive boxed pair could
    be restored. This wraps that exact pick with identity/link metadata; it never re-decides
    WHICH pairs to restore -- that stays the shared engine's call, and a mismatch between the
    captured ``party_mon`` commands and ``rebuild_pending`` is refused, never silently reselected.
    Call once, right after the collateral loop, before ``settle_whiteout`` returns.
    """
    rb = stage.rules.rebuild_pending.get(player)
    if not rb:
        return
    component = _component(document)
    partner = _partner(player)
    queued = list(rb["queued_keys"])
    queued_partner = list(rb["queued_partner_keys"])
    party_mon_player = [c["key"] for c in captured.get(player, []) if c.get("cmd") == "party_mon"]
    party_mon_partner = [c["key"] for c in captured.get(partner, []) if c.get("cmd") == "party_mon"]
    if party_mon_player != queued or party_mon_partner != queued_partner:
        raise JournalError("rebuild plan differs from the shared engine's queued picks")
    existing = component["plans"].get(whiteout_id)
    if existing is not None:
        if [row["keys"][player] for row in existing["ordered_pairs"]] != queued:
            raise JournalError("rebuild plan cannot be reselected for the same whiteout")
        return
    initials = document["components"][INITIAL]
    ordered_pairs = []
    for ordinal, (my_key, partner_key) in enumerate(zip(queued, queued_partner, strict=True)):
        link = stage.rules.find_link(player, my_key)
        if link is None or getattr(link, partner).key != partner_key:
            raise JournalError("rebuild plan pair lacks its live link")
        link_id, members = _link_identity(stage, initials, link)
        ordered_pairs.append({
            "ordinal": ordinal,
            "keys": {"a": link.a.key, "b": link.b.key},
            "link_id": link_id,
            "members": {"a": members[0], "b": members[1]},
            # Optional observed metadata only -- never authority (spec (1)); box/slot ownership
            # is decided fresh by gen1_storage_policy.resolve at job-preparation time.
            "source_refs": {"whiteout_id": whiteout_id},
            "job_id": None,
            "completed_ref": None,
        })
    component["plans"][whiteout_id] = {
        "schema": SCHEMA,
        "initiator": player,
        "source": {
            "player": player,
            "operation_id": entry["operation_id"],
            "index": index,
            "whiteout_id": whiteout_id,
        },
        "ordered_pairs": ordered_pairs,
        "phase": "pending",
        "blocked_reason": None,
    }


def plan_reserved(document, players):
    """Plan priority gate (spec (3)): True if any key in ``players`` belongs to a not-yet-
    completed rebuild pair. Unrelated PC/acquisition storage must not take ownership of a key a
    rebuild plan is about to move; ``gen1_storage_runtime._job`` consults this for every kind
    except ``"rebuild"`` itself."""
    component = document["components"].get(COMPONENT)
    if not component:
        return False
    players = set(players)
    for plan_row in component["plans"].values():
        if plan_row["phase"] == "complete":
            continue
        for pair in plan_row["ordered_pairs"]:
            if pair["completed_ref"] is None and players & set(pair["keys"].values()):
                return True
    return False


def schedule_rebuild(state, document, origin):
    """Try to advance exactly one pending rebuild pair (spec (2)): the first pair in plan order
    lacking a ``job_id``/``completed_ref``, if its keys are not otherwise physically busy, gets a
    storage "rebuild" job. One pair job active at a time, across all plans. Safe -- and meant --
    to be called redundantly from any settlement that might have just cleared ``_busy``: a
    completed storage job, a faint ACK, a memorial completion.
    """
    from server.gen1_storage_runtime import _busy, _job

    component = document["components"].get(COMPONENT)
    commands = {"a": [], "b": []}
    if not component:
        return commands
    for whiteout_id, plan_row in component["plans"].items():
        if plan_row["phase"] == "complete":
            continue
        for pair in plan_row["ordered_pairs"]:
            if pair["completed_ref"] is not None:
                continue
            if pair["job_id"] is not None:
                return commands  # already scheduled; wait for its own completion
            keys = pair["keys"]
            if _busy(document, keys):
                plan_row["blocked_reason"] = "busy"
                return commands
            more = _job(state, document, origin, "rebuild", keys,
                        source={"rebuild_id": whiteout_id, "ordinal": pair["ordinal"]})
            pair["job_id"] = digest({"origin": origin, "kind": "rebuild", "keys": keys})[:32]
            plan_row["blocked_reason"] = None
            for side in ("a", "b"):
                commands[side].extend(more[side])
            return commands  # one pair job at a time
    return commands


def completed(state, document, job):
    """Called from ``gen1_storage_runtime.acknowledge`` right after a ``"rebuild"`` job's BOTH
    writes are verified and ``job["complete"]`` is True. Feeds the shared engine's own
    ``sync_retrieve_done`` for each side -- the exact signal the legacy Lua-trusted path used,
    now gated on a real verified write instead of a client claim -- marks the pair completed with
    its write references, and tries to advance the next pair. Never ``sync_retrieve_failed``: a
    job this function is ever called for has, by construction (``gen1_storage_policy.resolve``
    raises ``StorageRefusal`` instead of completing on a capacity HOLD), already proved both
    writes landed the targets in party.
    """
    component = document["components"].get(COMPONENT)
    if component is None:
        return {"a": [], "b": []}
    whiteout_id = job["source"].get("rebuild_id")
    plan_row = component["plans"].get(whiteout_id)
    if plan_row is None:
        return {"a": [], "b": []}
    pair = next((p for p in plan_row["ordered_pairs"] if p["ordinal"] == job["source"]["ordinal"]), None)
    if pair is None or pair["completed_ref"] is not None:
        return {"a": [], "b": []}
    if set(job["prepared"]) != {"a", "b"} or job.get("resolution", {}).get("refusal") is not None:
        raise JournalError("rebuild completion requires both targets confirmed in party")
    from server.gen1_storage_policy import location

    for side, key in pair["keys"].items():
        place, _roster = location(job["prepared"][side]["after"], key, state.rules.player_identity[side])
        if place != "party":
            raise JournalError("rebuild completion requires both targets physically in party")
    commands = {"a": [], "b": []}
    for side, key in pair["keys"].items():
        immediate = state.rules.handle_event(side, {"event": "sync_retrieve_done", "key": key})
        drained = state.rules.take_commands(side, immediate)
        for p in ("a", "b"):
            commands[p].extend(drained[p])
    pair["completed_ref"] = {p: job["writes"][p] for p in ("a", "b")}
    if all(row["completed_ref"] is not None for row in plan_row["ordered_pairs"]):
        plan_row["phase"] = "complete"
    more = schedule_rebuild(state, document, job["write_origin"])
    for p in ("a", "b"):
        commands[p].extend(more[p])
    return commands


def verify_state(stage):
    """Restart reconciliation (spec (4)): the persisted plan is authority. Never regenerate a
    completed pair's job or repeat its ``sync_retrieve_done``; the ordered picks, identities and
    completion refs must agree with the shared rules and identity registry exactly as replayed.
    """
    document = stage.document()
    component = document["components"].get(COMPONENT)
    if component is None:
        return
    if set(component) != {"plans"}:
        raise JournalError("invalid rebuild settlement component")
    initials = document["components"].get(INITIAL, {})
    for whiteout_id, plan_row in component["plans"].items():
        if (
            not isinstance(plan_row, dict)
            or set(plan_row) != PLAN_FIELDS
            or plan_row["schema"] != SCHEMA
            or plan_row["initiator"] not in ("a", "b")
            or plan_row["source"]["whiteout_id"] != whiteout_id
            or plan_row["phase"] not in ("pending", "complete")
        ):
            raise JournalError("invalid rebuild plan record")
        seen_ordinals = set()
        for pair in plan_row["ordered_pairs"]:
            if (
                not isinstance(pair, dict)
                or set(pair) != PAIR_FIELDS
                or pair["ordinal"] in seen_ordinals
                or set(pair["keys"]) != {"a", "b"}
                or set(pair["members"]) != {"a", "b"}
            ):
                raise JournalError("invalid rebuild plan pair")
            seen_ordinals.add(pair["ordinal"])
            for side, key in pair["keys"].items():
                link = stage.rules.find_link(side, key)
                if link is None:
                    raise JournalError("rebuild plan pair lost its live link")
                _, members = _link_identity(stage, initials, link)
                expected_members = {"a": members[0], "b": members[1]}
                if expected_members != pair["members"]:
                    raise JournalError("rebuild plan pair differs from its logical identity")
            if pair["completed_ref"] is not None:
                if set(pair["completed_ref"]) != {"a", "b"}:
                    raise JournalError("invalid rebuild completion reference")
                for side, key in pair["keys"].items():
                    if key not in stage.rules.party_keys[side]:
                        raise JournalError("completed rebuild pair lost its restored party membership")
        if plan_row["phase"] == "complete" and not all(
            row["completed_ref"] is not None for row in plan_row["ordered_pairs"]
        ):
            raise JournalError("rebuild plan marked complete without every pair completed")


def verify_journal(journal, stage):
    """Cross-check each completed pair's write references actually resolve in the journal and
    belong to a ``"rebuild"`` storage job naming this exact pair."""
    document = stage.document()
    component = document["components"].get(COMPONENT)
    if component is None:
        return
    from server import event_reference
    from server.gen1_storage_runtime import COMPONENT as STORAGE

    jobs = document["components"].get(STORAGE, {}).get("jobs", {})
    for whiteout_id, plan_row in component["plans"].items():
        if document["components"].get("gen1-whiteout-settlement", {}).get(whiteout_id) is None:
            raise JournalError("rebuild plan lacks its triggering durable whiteout record")
        for pair in plan_row["ordered_pairs"]:
            if pair["completed_ref"] is None:
                continue
            job = None
            for candidate in jobs.values():
                if (
                    candidate["kind"] == "rebuild"
                    and candidate.get("source", {}).get("rebuild_id") == whiteout_id
                    and candidate.get("source", {}).get("ordinal") == pair["ordinal"]
                ):
                    job = candidate
                    break
            if job is None or not job["complete"]:
                raise JournalError("completed rebuild pair lacks its exact completed storage job")
            for ref in pair["completed_ref"].values():
                if event_reference.resolve(journal, ref).request.get("command_id") is None:
                    raise JournalError("rebuild completion reference does not resolve")
