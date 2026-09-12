"""Shared detached no-catch rule bookkeeping; physical retirement is caller-owned.

Policy follows SoulLinkState._handle_no_catch. No dialogue, sound, memory write,
or unqualified command is queued by this reusable operation.
"""

import copy
from datetime import datetime

from server.linked_death_rules import update_run_over
from server.protocol_journal import JournalError
from server.staged_state import StagedSoulLinkState
from server.state import AreaStatus, LinkEntry, LinkStatus, MonInfo


def _peers(state, player, proved_peers):
    peer = "b" if player == "a" else "a"
    result = {area: rows[peer] for area, rows in state.pending_captures.items() if peer in rows}
    if proved_peers is not None:
        if not isinstance(proved_peers, dict):
            raise JournalError("proved pending counterpart map required")
        for area, mon in proved_peers.items():
            if (
                not isinstance(area, str)
                or not isinstance(mon, MonInfo)
                or not mon.key
                or type(mon.species) is not int
                or mon.species < 1
                or type(mon.level) is not int
                or not 1 <= mon.level <= 100
            ):
                raise JournalError("proved pending counterpart required")
            if area in result and result[area] != mon:
                raise JournalError("proved counterpart conflicts with pending rule member")
            result[area] = mon
    return result


def decision(state, player, area, species, *, activated, proved_peers=None):
    if not isinstance(state, StagedSoulLinkState) or player not in ("a", "b"):
        raise JournalError("detached no-catch rule state required")
    if not isinstance(area, str) or not 1 <= len(area) <= 128 or not area.isprintable():
        raise JournalError("explicit no-catch area required")
    if type(species) is not int or species < 1 or type(activated) is not bool:
        raise JournalError("verified encounter species and activation required")
    peer = "b" if player == "a" else "a"
    pending_peers = _peers(state, player, proved_peers)
    if not activated:
        return "ball_gate"
    if state.adapter.is_gift_area(area):
        return "gift_area"
    if state.area_states.get(area, AreaStatus.UNSEEN) in (AreaStatus.LINKED, AreaStatus.DEAD_ZONE):
        return "resolved"
    if state.pending_captures.get(area, {}).get(player):
        return "already_captured"
    if area in state.retry_areas[player] or area in state.retry_areas[peer]:
        return "clause_retry"
    if area in state.dupe_notified_areas[player]:
        return "dupe_already_notified"
    if state.species_lock:
        family = state.adapter.evo_family(species)
        for link in state.links:
            if link.status != LinkStatus.ALIVE:
                continue
            for mon in (getattr(link, player), getattr(link, peer)):
                if mon and mon.species and state.adapter.evo_family(mon.species) == family:
                    return "species_clause"
        for mon in pending_peers.values():
            if mon and mon.species and state.adapter.evo_family(mon.species) == family:
                return "species_clause"
    return "dead_zone"


def record(state, player, area, species, level, *, activated, occurred_at, proved_peers=None):
    if type(level) is not int or not 1 <= level <= 100:
        raise JournalError("verified no-catch level required")
    try:
        datetime.fromisoformat(occurred_at)
    except (ValueError, TypeError) as error:
        raise JournalError("explicit no-catch timestamp required") from error
    outcome = decision(state, player, area, species, activated=activated, proved_peers=proved_peers)
    if outcome == "dupe_already_notified":
        state.dupe_notified_areas[player].discard(area)
    if outcome != "dead_zone":
        return {"outcome": outcome, "retire": None}
    if any(state.queued_commands.values()):
        raise JournalError("no-catch cannot replace unpublished commands")
    peer = "b" if player == "a" else "a"
    mon = copy.deepcopy(_peers(state, player, proved_peers).get(area))
    halves = {player: None, peer: mon}
    encountered = {player: MonInfo(key="", species=species, level=level), peer: None}
    link = LinkEntry(
        area_id=area,
        a=halves["a"],
        b=halves["b"],
        status=LinkStatus.DEAD,
        encounter_a=encountered["a"],
        encounter_b=encountered["b"],
        killed_at=occurred_at,
        cause="dead_zone",
        initiating_player=player,
    )
    state.links.append(link)
    state._index_entry(link)
    state._set_area_state(area, AreaStatus.DEAD_ZONE, player=player, reason="no_catch")
    state.pending_captures.pop(area, None)
    if mon:
        state.party_keys[peer].discard(mon.key)
    update_run_over(state)
    return {"outcome": outcome, "retire": {"player": peer, "key": mon.key} if mon else None}

