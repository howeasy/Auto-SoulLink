"""Gen 1 adapter translators: decoded RBY receipts and engine signals become the semantic
events that the shared rule engine already consumes for Gen 3 (SoulLinkState.handle_event).

Proposal P3 (docs/gen1_reference/proposals/P3-semantic-events.md). Pure functions, no journal
access, no decision. Field names match the handlers in server/state.py exactly:
_handle_capture (key, area_id, species_id, level, nickname, gift, in_box, maxHP),
_handle_no_catch (area_id, species_id, level), _handle_faint (key, _level),
_handle_whiteout (area_id), _handle_party_to_box (key, stats), _handle_box_to_party (key),
_handle_key_change (old_key, new_key, new_species, new_nickname, reason),
_handle_trainer_battle_start (trainer_id), _handle_memorialize_done (key).
"""

GIFT_KINDS = ("scripted_grant",)


def capture_event(*, key, area_id, species_id, level, nickname="", gift=False, in_box=False, max_hp=None):
    """One caught, granted or static-origin member delivered to the party or the box."""
    event = {"event": "capture", "key": key, "area_id": area_id, "species_id": int(species_id),
             "level": int(level), "nickname": nickname or "", "gift": bool(gift), "in_box": bool(in_box)}
    if max_hp is not None:
        event["maxHP"] = int(max_hp)
    return event


def capture_from_fact(fact, mon, area_id, *, gift=None):
    """fact: a decoded acquisition fact ({kind, key, destination, ...}); mon: a codec member
    (species_id, level, nickname, max_hp). Scripted grants are gifts unless the caller says otherwise."""
    is_gift = (fact.get("kind") in GIFT_KINDS) if gift is None else bool(gift)
    return capture_event(key=fact["key"], area_id=area_id, species_id=mon.species_id, level=mon.level,
                         nickname=getattr(mon, "nickname", "") or "", gift=is_gift,
                         in_box=fact.get("destination") == "box", max_hp=getattr(mon, "max_hp", None))


def no_catch_event(*, area_id, species_id, level):
    """A wild encounter ended without a delivery; the engine decides whether it is a dead zone."""
    return {"event": "no_catch", "area_id": area_id, "species_id": int(species_id), "level": int(level)}


def faint_event(*, key, level=0, cause="battle"):
    """An engine faint signal (RemoveFaintedPlayerMon or out-of-battle poison). ``_cause`` is
    informational until ``_propagate_faint`` reads it; today it records cause="battle" for every death."""
    return {"event": "faint", "key": key, "_level": int(level), "_cause": cause}


def whiteout_event(*, area_id):
    return {"event": "whiteout", "area_id": area_id}


def party_to_box_event(*, key, stats=None):
    event = {"event": "party_to_box", "key": key}
    if stats:
        event["stats"] = dict(stats)
    return event


def box_to_party_event(*, key):
    return {"event": "box_to_party", "key": key}


def key_change_event(*, old_key, new_key, reason, new_species=None, new_nickname=None):
    """Evolution or an NPC in-game exchange rewrote the physical key of a linked member."""
    event = {"event": "key_change", "old_key": old_key, "new_key": new_key, "reason": reason}
    if new_species is not None:
        event["new_species"] = int(new_species)
    if new_nickname is not None:
        event["new_nickname"] = new_nickname
    return event


def trainer_battle_start_event(*, trainer_id):
    return {"event": "trainer_battle_start", "trainer_id": int(trainer_id)}


def memorialize_done_event(*, key):
    return {"event": "memorialize_done", "key": key}
