"""Gen 1 bridge into the shared rule engine: the engine decides, RBY evidence stays around it.

Each function feeds ``SoulLinkState.handle_event`` the semantic event Gen 3 already sends
(``server/gen1_semantic_events.py``), then adapts the outcome to the record shapes the durable
runtime keeps. Three RBY policies are preserved on purpose: usability of a member is published
only by its proved physical disposition (callers own ``party_keys``), ball activation comes only
from the ``bag_received`` engine signal (the flag is restored), and physical effects are executed
by the held executors and runtimes from the rules state. Engine commands are captured before their
staged queues are cleared: physical effects stay with those runtimes, while explicitly classified
display commands become durable HUD notices.
"""
import copy
import time
from dataclasses import fields

from server.gen1_semantic_events import (
    capture_event,
    key_change_event,
    memorialize_done_event,
    no_catch_event,
)
from server.protocol_journal import JournalError
from server.state import AreaStatus, LinkStatus, MonInfo


def _capture_and_clear(rules, player, immediate):
    """Return both engine outboxes exactly once, then clear the staged legacy queues."""
    if player not in ("a", "b") or not isinstance(immediate, list):
        raise JournalError("invalid Gen 1 engine command capture")
    if callable(getattr(rules, "take_commands", None)):
        return rules.take_commands(player, immediate)
    captured = {side: copy.deepcopy(rules.queued_commands[side]) for side in ("a", "b")}
    captured[player] = copy.deepcopy(immediate) + captured[player]
    rules.queued_commands = {"a": [], "b": []}
    return captured


def starter_grant(rules, player, area, info):
    """A starter is a gift capture in the lab: pending for the first player, a link for the second,
    clauses applied unless the adapter declares the gift fixed-species (Gen 1: Yellow/Yellow only).
    Returns ``(link, rejection)``: the live link or None, and the clause rejection the engine decided
    (``{"player", "key", "reason"}``, the rejected starter stays pending for the other player) or None."""
    linked, rejection, _feedback = starter_grant_feedback(rules, player, area, info)
    return linked, rejection


def starter_grant_feedback(rules, player, area, info, *, now=time.time):
    """Starter settlement plus the explicitly classified durable presentation batch."""
    activated = dict(rules.pokeballs_obtained)
    # The engine returns the caller's own commands and queues only the partner's.
    own = rules.handle_event(player, capture_event(key=info.key, area_id=area, species_id=info.species,
                                                   level=info.level, nickname=info.nickname or "", gift=True))
    captured = _capture_and_clear(rules, player, own or [])
    rejection = None
    for pid, commands in captured.items():
        fainted = [c for c in commands if c.get("cmd") == "force_faint"]
        if not fainted:
            continue
        if len(fainted) != 1 or rejection is not None:
            raise JournalError("shared rule engine rejected more than one starter")
        prompts = [c.get("text", "") for c in commands if c.get("cmd") == "gui_prompt"]
        reason = prompts[0][4:] if prompts and prompts[0].startswith("[x] ") else "clause violation"
        # The engine books the burial (force_faint and memorialize). Gen 1 executes it as a retirement
        # job with the starter_clause cause (gen1_retirement_runtime), whose verified image reports
        # memorialize_done through memorial_completion below; the obligation stays booked until then.
        rejection = {"player": pid, "key": fainted[0]["key"], "reason": reason}
    rules.pokeballs_obtained = activated
    link = rules.find_link(player, info.key)
    linked = link if link is not None and link.status == LinkStatus.ALIVE else None
    from server.gen1_hud_feedback import classify_captured

    feedback = classify_captured(
        captured,
        linked=linked is not None,
        rejected=rejection is not None,
        rejection_text=rejection["reason"] if rejection is not None else None,
        now=now,
    )
    return linked, rejection, feedback


def allowed_starters(rules, player, area, species):
    """Which of ``species`` the engine would pair with the partner's starter still pending in
    ``area``: the clause check the rejection ran, over each candidate, recording nothing."""
    peer = "b" if player == "a" else "a"
    partner = rules.pending_captures.get(area, {}).get(peer)
    allowed = []
    for candidate in species:
        mon = MonInfo(key="", level=5, species=int(candidate))
        pair = (mon, partner) if player == "a" else (partner, mon)
        if partner is None or rules._check_link_violation(*pair) is None:
            allowed.append(int(candidate))
    return allowed


def no_catch(rules, player, area, species, level, *, activated, proved_peers, decision,
             now=time.time):
    """``decision`` is ``no_catch_rules.decision``, a pure function that names the outcome; the state
    change is the engine. ``retire`` names the partner catch the engine force-fainted (the retirement
    runtime executes it), ``at`` is the engine death timestamp, and ``feedback`` is best-effort HUD
    presentation captured from the same decision."""
    outcome = decision(rules, player, area, species, activated=activated, proved_peers=proved_peers)
    if outcome == "dupe_already_notified":
        rules.dupe_notified_areas[player].discard(area)
    if outcome != "dead_zone":
        feedback = {"a": [], "b": []}
        if outcome == "species_clause":
            from server.gen1_hud_feedback import best_effort_notice

            species_name = rules.adapter.species_name(species) if species else "Encounter"
            area_name = rules.adapter.area_display_name(area) or area.replace("_", " ").title()
            notice = best_effort_notice(
                "clause_retry",
                "prompt",
                f"{species_name} in {area_name} - retry",
                r=255,
                g=200,
                b=60,
                frames=360,
                now=now,
                source="no_catch:species_clause",
            )
            if notice is not None:
                feedback[player].append(notice)
        return {
            "outcome": outcome,
            "retire": None,
            "at": None,
            "feedback": feedback,
        }
    peer = "b" if player == "a" else "a"
    immediate = rules.handle_event(
        player, no_catch_event(area_id=area, species_id=species, level=level)
    )
    if rules.area_states.get(area) != AreaStatus.DEAD_ZONE:
        raise JournalError("shared rule engine did not settle the dead zone")
    captured = _capture_and_clear(rules, player, immediate or [])
    retired = [c for c in captured[peer] if c.get("cmd") == "force_faint"]
    if len(retired) > 1:
        raise JournalError("shared rule engine retired more than one partner catch")
    if retired:
        # The engine leaves the usable-party mask to the faint it queued; Gen 1 executes that faint as
        # a retirement job, so the rule mask drops the retired catch now, as the death path does. The
        # memorial the engine booked for it stays booked: the job's verified archive reports it
        # (memorial_completion), and the retired pair reaches MEMORIAL as in Gen 3.
        rules.party_keys[peer].discard(retired[0]["key"])
    dead = [link for link in rules.links if link.area_id == area and link.cause == "dead_zone"]
    from server.gen1_hud_feedback import classify_captured

    return {
        "outcome": outcome,
        "retire": {"player": peer, "key": retired[0]["key"]} if retired else None,
        "at": dead[-1].killed_at if dead else None,
        "feedback": classify_captured(captured, linked=False, rejected=True, now=now),
    }


def rekey(rules, player, outgoing, mon, *, reason):
    """Evolution or NPC exchange rewrote a member key. Returns ``(kind, area)`` exactly as
    ``member_identity_rules.rekey`` did: ``("link", area)``, ``("pending_capture", area)`` or
    ``("identity_only", None)``."""
    if player not in ("a", "b") or not isinstance(outgoing, str) or not outgoing or not isinstance(mon, MonInfo) or not mon.key:
        raise JournalError("owned rule-member replacement required")
    matches = []
    for link in rules.links:
        half = getattr(link, player)
        if half is not None and half.key == outgoing:
            matches.append(("link", link.area_id))
        elif half is not None and half.key == mon.key:
            raise JournalError("rule-member replacement collides with another link")
    for area, rows in rules.pending_captures.items():
        half = rows.get(player)
        if half is not None and half.key == outgoing:
            matches.append(("pending_capture", area))
        elif half is not None and half.key == mon.key:
            raise JournalError("rule-member replacement collides with another pending capture")
    if len(matches) > 1:
        raise JournalError("outgoing rule member is ambiguous")
    if not matches:
        return "identity_only", None
    kind, area = matches[0]
    immediate = rules.handle_event(
        player,
        key_change_event(
            old_key=outgoing,
            new_key=mon.key,
            reason=reason,
            new_species=mon.species,
            new_nickname=mon.nickname,
        ),
    )
    _capture_and_clear(rules, player, immediate or [])
    if kind == "link":
        moved = rules.find_link(player, mon.key)
        if moved is None or moved.area_id != area or rules.find_link(player, outgoing) is not None:
            raise JournalError("shared rule engine did not migrate the linked member")
        half = getattr(moved, player)
    else:
        half = rules.pending_captures.get(area, {}).get(player)
        if half is None or half.key != mon.key:
            raise JournalError("shared rule engine did not migrate the pending member")
    for field in fields(MonInfo):   # every field of the replacement is authoritative, as before
        setattr(half, field.name, getattr(mon, field.name))
    return kind, area


def memorial_completion(rules, player, key):
    """One physically verified memorial for a burial the engine booked: a linked death, a dead-zone
    casualty or a rejected starter. Refuses a second report (the obligation is gone). True when the
    engine closed the pair (MEMORIAL), or the key has no pair to close."""
    link = rules.find_link(player, key)
    if key not in rules.pending_memorials[player] or (link is not None and link.status != LinkStatus.DEAD):
        raise JournalError("exact pending memorial obligation required")
    immediate = rules.handle_event(player, memorialize_done_event(key=key))
    _capture_and_clear(rules, player, immediate or [])
    return link is None or link.status == LinkStatus.MEMORIAL
