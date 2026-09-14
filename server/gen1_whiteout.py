"""Whiteout detection from the faint engine signal (P5-whiteout-detection.md).

The post-battle checkpoint never sees a whiteout: HandleBlackOut heals the party before the
overworld loop is reached again (pokered home/overworld.asm:354-358, engine/events/black_out.asm),
so the only evidence is the party region the faint hook captured. The predicate is the engine
test itself, AnyPartyAlive (engine/battle/core.asm:1455-1470): OR the HP of every party slot
once the fainting slot carries its battle HP (the battle site RemoveFaintedPlayerMon+0 fires
before the copy-down at core.asm:1023, so the active slot may still show stale HP in party_hex;
validate_signal already pinned battle_hp to zero and the poison slot to zero).

Ordering (P5 section 5): faint first, then whiteout, over the same signal, so the whited-out
mon is already DEAD and _handle_whiteout cannot queue a second peer death for it -- a repeat
force_faint for that SAME mon is a genuine duplicate and still refused. Any OTHER still-alive
linked pair the whiteout also retires (CLAUDE.md "Whiteout": every partner of a remaining linked
party mon gets force-fainted) never got a faint signal of its own; settle_whiteout records that
collateral death as a real, ack-able obligation instead of discarding the whole batch.
"""

import copy
import logging

from server.adapters.gen1_rby import _MAP_ID_TO_AREA
from server.gen1_initial_observation import COMPONENT as INITIAL
from server.gen1_semantic_events import whiteout_event
from server.protocol_journal import JournalError

COMPONENT = "gen1-whiteout-settlement"
log = logging.getLogger(__name__)


def area_for_map(map_id):
    """wCurMap through the adapter area map; None for an unmapped map, as the sibling runtimes do."""
    return _MAP_ID_TO_AREA.get(int(map_id))


def whiteout_from_faint(previous_inventory, current_inventory, faint_signal, *, area_id):
    """dict | None: whiteout_event when no party HP is left after this faint.

    faint_signal: one validated engine signal {kind, frame, pc, bank, sp, point} of kind
    battle_faint or poison_faint. previous_inventory (the party keys of record) and
    current_inventory (the post-blackout witness, None until it exists) are corroboration
    only and never the trigger (P5 section 3); ponytail: unused until a consumer needs them.
    """
    point = faint_signal["point"]
    party = bytes.fromhex(point["party_hex"])
    count = party[0]
    if count == 0:
        return None
    hp = [int.from_bytes(party[9 + 44 * slot:11 + 44 * slot], "big") for slot in range(count)]
    if faint_signal["kind"] == "battle_faint":
        hp[point["active_slot"]] = point["battle_hp"]  # the copy-down the engine does at core.asm:1023
    else:
        hp[point["which"]] = 0
    if any(hp):
        return None
    return whiteout_event(area_id=area_id)


def settle_whiteout(stage, document, player, entry, index, signal, *, trigger_death_id, trigger_key):
    """Right after the faint of the signal settled: hand the engine the whiteout, drain what it
    queued the way P8 drains after the faint, and record it once under the death identifier.

    trigger_death_id/trigger_key identify the faint that was just settled (record_death_obligation
    in gen1_faint_runtime.py). Any force_faint/force_explode this whiteout also queues for a
    DIFFERENT still-alive linked pair (CLAUDE.md "Whiteout": every partner of a remaining linked
    party mon gets force-fainted) is a collateral death with no faint signal of its own -- recorded
    as a real obligation via record_death_obligation, anchored to trigger_death_id. A command that
    names the SAME mon as the trigger is a genuine duplicate (the faint settlement should already
    have killed it) and still raises.
    """
    from server.gen1_faint_runtime import (
        COMPONENT as FAINT_COMPONENT,
        identifier,
        record_death_obligation,
    )

    event = whiteout_from_faint(stage.rules.partner_blobs[player], None, signal,
                                area_id=area_for_map(signal["point"]["map_id"]))
    if event is None:
        return {"a": [], "b": []}
    immediate = stage.rules.handle_event(player, event)
    captured = stage.rules.take_commands(player, immediate)
    partner = "b" if player == "a" else "a"
    component = document["components"][FAINT_COMPONENT]
    collateral = {"a": [], "b": []}
    for command in captured[partner]:
        if command.get("cmd") not in ("force_faint", "force_explode"):
            continue
        link = stage.rules.find_link(partner, command["key"])
        if link is None:
            raise JournalError("whiteout collateral command names an unknown link")
        own_key = getattr(link, player).key
        if own_key == trigger_key:
            raise JournalError("whiteout found a linked party member its faint settlement left alive")
        record_death_obligation(
            stage, document, component, collateral, player=player, partner=partner, entry=entry,
            index=index, key=own_key, link=link, command=command, at=link.killed_at,
            collateral_of=trigger_death_id,
        )
        log.warning(f"[{player}] whiteout collateral: no faint signal fired for {own_key}; "
                    f"force-fainting {partner}:{command['key']} from party HP evidence")
    # The durable HUD closes its explicit game-over/rebuild transitions.  This
    # presentation path neither executes nor falsely acknowledges the engine's
    # legacy party_mon/memorialize commands; those require their own physical lane.
    from server.gen1_hud_feedback import classify_death

    labels = dict.fromkeys(("a", "b"), "WHITEOUT")
    feedback = classify_death(captured, member_labels=labels, whiteout=True)
    document["components"].setdefault(COMPONENT, {})[identifier(player, entry["operation_id"], index)] = {
        "player": player, "engine_record": copy.deepcopy(entry), "index": index, "area_id": event["area_id"]}
    for p in ("a", "b"):
        collateral[p].extend(feedback[p])
    return collateral


def verify_state(stage):
    """Recompute every whiteout record from its engine evidence; each needs its settled death."""
    document = stage.document()
    component = document["components"].get(COMPONENT)
    if component is None:
        return
    from server.gen1_faint_runtime import COMPONENT as FAINT, identifier, verified_source

    initials = document["components"].get(INITIAL, {})
    deaths = document["components"].get(FAINT, {}).get("deaths", {})
    if not isinstance(component, dict):
        raise JournalError("invalid whiteout settlement component")
    for whiteout_id, row in component.items():
        if (not isinstance(row, dict) or set(row) != {"player", "engine_record", "index", "area_id"}
                or row["player"] not in initials):
            raise JournalError("incomplete whiteout record")
        decoded = verified_source(row, initials[row["player"]])
        signal = row["engine_record"]["payload"]["signals"][row["index"]]
        expected = whiteout_from_faint(None, None, signal, area_id=area_for_map(signal["point"]["map_id"]))
        if (decoded["kind"] != "faint" or expected != whiteout_event(area_id=row["area_id"])
                or whiteout_id != identifier(row["player"], row["engine_record"]["operation_id"], row["index"])
                or whiteout_id not in deaths):
            raise JournalError("whiteout record differs from its settled faint evidence")
