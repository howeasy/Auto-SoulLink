"""Gen 1 bridge into the shared rule engine: the engine decides, RBY evidence stays around it.

Each function feeds ``SoulLinkState.handle_event`` the semantic event Gen 3 already sends
(``server/gen1_semantic_events.py``), then adapts the outcome to the record shapes the durable
runtime keeps. Three RBY policies are preserved on purpose: usability of a member is published
only by its proved physical disposition (callers own ``party_keys``), ball activation comes only
from the ``bag_received`` engine signal (the flag is restored), and physical effects are executed
by the held executors and runtimes from the rules state, so the commands the engine queues
(sounds, prompts, box moves, memorials) are drained here. The executor map of handoff item 4
replaces those drains one command kind at a time.
"""
from dataclasses import fields

from server.gen1_semantic_events import capture_event, key_change_event, memorialize_done_event, no_catch_event
from server.protocol_journal import JournalError
from server.state import AreaStatus, LinkStatus, MonInfo


def _drain(rules):
    rules.queued_commands = {"a": [], "b": []}


def starter_grant(rules, player, area, info):
    """A starter is a gift capture in the lab: pending for the first player, a link for the second,
    clauses applied unless the adapter declares the gift fixed-species. Returns the live link or None."""
    activated = dict(rules.pokeballs_obtained)
    rules.handle_event(player, capture_event(key=info.key, area_id=area, species_id=info.species, level=info.level,
                                             nickname=info.nickname or "", gift=True))
    _drain(rules)
    rules.pokeballs_obtained = activated
    link = rules.find_link(player, info.key)
    return link if link is not None and link.status == LinkStatus.ALIVE else None


def no_catch(rules, player, area, species, level, *, activated, proved_peers, decision):
    """``decision`` is ``no_catch_rules.decision``, a pure function that names the outcome; the state
    change is the engine. Returns ``{"outcome", "retire", "at"}``: ``retire`` names the partner catch
    the engine force-fainted (the retirement runtime executes it), ``at`` is the engine death timestamp
    when a dead zone was recorded."""
    outcome = decision(rules, player, area, species, activated=activated, proved_peers=proved_peers)
    if outcome == "dupe_already_notified":
        rules.dupe_notified_areas[player].discard(area)
    if outcome != "dead_zone":
        return {"outcome": outcome, "retire": None, "at": None}
    peer = "b" if player == "a" else "a"
    rules.handle_event(player, no_catch_event(area_id=area, species_id=species, level=level))
    if rules.area_states.get(area) != AreaStatus.DEAD_ZONE:
        raise JournalError("shared rule engine did not settle the dead zone")
    retired = [c for c in rules.queued_commands[peer] if c.get("cmd") == "force_faint"]
    _drain(rules)
    if len(retired) > 1:
        raise JournalError("shared rule engine retired more than one partner catch")
    if retired:
        # The engine leaves the usable-party mask to the faint it queued; Gen 1 executes that faint as
        # a retirement job, so the rule mask drops the retired catch now, as the death path does.
        rules.party_keys[peer].discard(retired[0]["key"])
        # The engine also books a memorial for the retired catch (Gen 3 buries it). Gen 1 archives it
        # through the retirement job, which keeps its own completion accounting today; reporting that
        # completion back as memorialize_done, so the retired pair reaches MEMORIAL as in Gen 3, is the
        # handoff item 4 follow-up. Until then the obligation is released here, not left dangling.
        rules.pending_memorials[peer].discard(retired[0]["key"])
    dead = [link for link in rules.links if link.area_id == area and link.cause == "dead_zone"]
    return {"outcome": outcome, "retire": {"player": peer, "key": retired[0]["key"]} if retired else None,
            "at": dead[-1].killed_at if dead else None}


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
    rules.handle_event(player, key_change_event(old_key=outgoing, new_key=mon.key, reason=reason,
                                                new_species=mon.species, new_nickname=mon.nickname))
    _drain(rules)
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
    """One physically verified memorial; True when both halves are done and the pair is MEMORIAL."""
    link = rules.find_link(player, key)
    if (link is None or link.a is None or link.b is None or link.status != LinkStatus.DEAD
            or key not in rules.pending_memorials[player]):
        raise JournalError("exact pending linked memorial required")
    rules.handle_event(player, memorialize_done_event(key=key))
    _drain(rules)
    return link.status == LinkStatus.MEMORIAL
