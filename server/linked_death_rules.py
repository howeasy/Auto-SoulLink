"""Stage a verified linked death without scheduling unqualified UI/storage effects."""
from datetime import datetime

from server.protocol_journal import JournalError
from server.staged_state import StagedSoulLinkState
from server.state import LinkStatus


def update_run_over(state):
    if (all(state.pokeballs_obtained.values()) and not state.pending_captures
            and any(link.a and link.b for link in state.links)
            and not any(link.status==LinkStatus.ALIVE for link in state.links)):
        state.run_over=True


def record_memorial_completion(state, player, key):
    """Stage one physically verified completion; the caller owns receipt proof.

    Replay is handled by the journal before calling this. No files or commands
    are emitted. The second endpoint archives the pair in the same document.
    """
    if not isinstance(state, StagedSoulLinkState) or player not in ('a', 'b'):
        raise JournalError('detached paired rule state required')
    matches = [entry for entry in state.links if getattr(entry, player) is not None
               and getattr(entry, player).key == key]
    if (len(matches) != 1 or matches[0].a is None or matches[0].b is None
            or matches[0].status != LinkStatus.DEAD or key not in state.pending_memorials[player]):
        raise JournalError('exact pending linked memorial required')
    link = matches[0]
    state.pending_memorials[player].remove(key)
    state.party_keys[player].discard(key)
    complete = all(getattr(link, p).key not in state.pending_memorials[p] for p in ('a', 'b'))
    if complete:
        link.status = LinkStatus.MEMORIAL
        state._write_memorial(link)
    return complete


def record_linked_death(state,player,key,*,cause,level,at,partner_command):
    if not isinstance(state,StagedSoulLinkState) or player not in ('a','b'):
        raise JournalError('detached paired rule state required')
    if cause not in ('battle','poison') or type(level) is not int or not 1<=level<=100:
        raise JournalError('verified death cause and level required')
    if not isinstance(at,str) or datetime.fromisoformat(at).tzinfo is None:
        raise JournalError('explicit death timestamp required')
    if partner_command not in ('force_faint','force_explode'):
        raise JournalError('qualified partner faint command required')
    if not state.pokeballs_obtained[player]:
        return None  # Do not remove a still-owned starter from party caches.
    matches=[entry for entry in state.links if getattr(entry,player) is not None and getattr(entry,player).key==key]
    if len(matches)>1:raise JournalError('ambiguous player-scoped death key')
    link=matches[0] if matches else None
    if link is None or link.a is None or link.b is None:
        raise JournalError('active faint lacks a complete qualified link')
    if link.status!=LinkStatus.ALIVE:return None
    partner='b' if player=='a' else 'a';own=getattr(link,player);peer=getattr(link,partner)
    if any(state.queued_commands.values()):raise JournalError('unpublished commands precede linked death')
    link.status=LinkStatus.DEAD;link.cause=cause;link.killed_at=at;link.initiating_player=player
    own.level=level
    for p,mon in ((player,own),(partner,peer)):
        state.party_keys[p].discard(mon.key)
        state.pending_memorials[p].add(mon.key)
    update_run_over(state)
    return {'player':partner,'command':{'cmd':partner_command,'key':peer.key,'nickname':peer.nickname or ''}}
