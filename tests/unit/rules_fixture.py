"""Detached rule-state fixtures shared by the Gen 1 unit tests.

`seed_link_half` is the fixture counterpart of the runtime bridges (server/gen1_engine_bridge.py):
the shared engine records the capture and decides pending/link/violation; the commands it queues
are drained (tests execute no physical effects), the ball flag is restored (activation comes only
from the bag_received signal) and usability is published the way the proved disposition would
(`party_keys` is caller-owned). Returns the live link, or None while the half pends.
"""
from server.adapters import get_adapter
from server.gen1_semantic_events import capture_event
from server.staged_state import StagedSoulLinkState
from server.state import LinkStatus, SoulLinkState


def staged(tmp_path, **options):
    state = SoulLinkState(data_dir=str(tmp_path), adapter=get_adapter("gen1_rby", rom_type="yellow"), **options)
    state.rom_type = "yellow"
    return StagedSoulLinkState.from_live(state, {"retired_pairs": []})


def seed_link_half(rules, player, area, mon, *, gift=False, in_box=False):
    activated = dict(rules.pokeballs_obtained)
    rules.handle_event(player, capture_event(key=mon.key, area_id=area, species_id=mon.species, level=mon.level,
                                             nickname=mon.nickname or "", gift=gift, in_box=in_box))
    rules.queued_commands = {"a": [], "b": []}
    rules.pokeballs_obtained = activated
    rules.party_keys[player].add(mon.key)
    link = rules.find_link(player, mon.key)
    return link if link is not None and link.status == LinkStatus.ALIVE else None
