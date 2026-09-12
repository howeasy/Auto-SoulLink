"""Names the no-catch outcome the shared engine records (SoulLinkState._handle_no_catch).

A pure decision: `gen1_engine_bridge.no_catch` makes the state change through the engine.
"""

from server.protocol_journal import JournalError
from server.staged_state import StagedSoulLinkState
from server.state import AreaStatus, LinkStatus, MonInfo


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
