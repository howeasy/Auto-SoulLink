"""Disposition decisions use proved locations; this module grants no writes."""

from server.gen1_initial_observation import inventory
from server.gen1_storage import StorageRefusal, expected
from server.protocol_journal import JournalError


def invalid_box_party(point, key, identity):
    """Read-only proof of a valid party target despite a corrupt box selector."""
    from server.gen1_full_save import SYMBOLS, image
    from server.gen1_initial_observation import display_name
    from server.gen1_party_codec import PartyCodec

    image(point)
    symbols = SYMBOLS["pokeyellow" if point["variant"] == "yellow" else "pokered"]
    main = bytes.fromhex(point["fields"]["main"])
    base = symbols["wMainDataStart"]
    if main[symbols["wCurrentBoxNum"] - base] & 127 < 12:
        return None
    own = symbols["wPlayerID"] - base
    if identity != {
        "ot_id": main[own : own + 2].hex().upper(),
        "trainer_name": display_name(bytes.fromhex(point["fields"]["name"])),
    }:
        raise JournalError("invalid-box read changed save identity")
    raw = bytes.fromhex(point["fields"]["party"])
    count = raw[0]
    blobs = [
        raw[8 + i * 44 : 8 + (i + 1) * 44]
        + raw[272 + i * 11 : 272 + (i + 1) * 11]
        + raw[338 + i * 11 : 338 + (i + 1) * 11]
        for i in range(min(count, 6))
    ]
    party = PartyCodec(point["variant"]).validate_party(
        blobs, species_list=list(raw[1 : count + 2])
    )
    if sum(m.key == key for m in party) != 1:
        raise JournalError("invalid-box read lost its exact valid party target")
    return party


def location(point, key, identity):
    roster = inventory(point, identity)
    rows = [r for r in roster["members"] if r["key"] == key]
    if len(rows) != 1:
        raise JournalError("storage policy requires one exact physical member")
    return rows[0]["location"], roster


def quarantine_box(point, key, identity, *, direction="deposit"):
    """Current box first, then deterministic legal capacity; never Box12."""
    roster = inventory(point, identity)
    for index in [roster["current_box"], *range(11)]:
        if index == 11:
            continue
        try:
            expected(point, key, direction, identity=identity, destination_box=index)
            return index
        except StorageRefusal as exc:
            if exc.reason not in ("current-box-full", "unowned-uninitialized-storage"):
                raise
    raise StorageRefusal("no-proved-storage-capacity")


def resolve(job, points, identities):
    """Return directions plus exact refusal; compensation restores disposition."""
    keys = job["keys"]
    if job["kind"] == "grave_evict":
        return {job["actor"]: "relocate"}, "acquisition-born-in-reserved-box"
    if job["kind"] == "archive_return":
        return {job["actor"]: "deposit"}, "dead-archive-withdrawal"
    if job["kind"] == "pc":
        actor = job["actor"]
        partner = "b" if actor == "a" else "a"
        if (
            partner in keys
            and invalid_box_party(points[partner], keys[partner], identities[partner]) is not None
        ):
            inverse = "withdraw" if job["destination"] == "box" else "deposit"
            return {actor: inverse}, "invalid-current-box"
    places = {p: location(points[p], key, identities[p]) for p, key in keys.items()}
    if job["kind"] == "pc" and job["destination"] == "box":
        actor = job["actor"]
        if places[actor][1]["current_box"] == 11:
            return {
                p: "withdraw" if p == actor else "confirm" for p in keys
            }, "reserved-archive-deposit"
    if job["kind"] == "quarantine":
        p = next(iter(keys))
        # The legacy last-member exception must not create a zero-party save.
        return {
            p: "deposit"
            if places[p][0] == "party" and places[p][1]["party_count"] > 1
            else "confirm"
        }, None
    if job["kind"] == "linked":
        room = all(r["party_count"] + (place == "box") <= 6 for place, r in places.values())
        desired = "party" if room else "box"
        return {
            p: "confirm" if place == desired else "withdraw" if desired == "party" else "deposit"
            for p, (place, _roster) in places.items()
        }, None
    if job["kind"] == "rebuild":
        # A rebuild's own targets are never sent back to the box: each side's target is either
        # already in party (confirm) or withdrawn from the box, exactly. A boxed target whose
        # side is already at capacity is an explicit HOLD -- the "linked" fallback above (move
        # the whole pair to whichever side has room) is unsuitable here; a rebuild target the
        # party cannot fit is never silently kept boxed either. A full side whose OWN target is
        # already in party still needs confirm, not a capacity refusal.
        directions = {}
        for p, (place, roster) in places.items():
            if place == "party":
                directions[p] = "confirm"
            elif roster["party_count"] >= 6:
                raise StorageRefusal("rebuild-capacity")
            else:
                directions[p] = "withdraw"
        return directions, None
    if job["kind"] != "pc":
        raise JournalError("unknown synchronized storage policy")
    actor = job["actor"]
    partner = "b" if actor == "a" else "a"
    desired = job["destination"]
    if places[actor][0] != desired:
        raise JournalError("observed PC initiator changed containers before settlement")
    directions = {actor: "confirm"}
    if partner not in keys:
        # Pending nongift withdrawal is never admitted as usable party access.
        return {actor: "deposit"}, "pending-acquisition-quarantine"
    directions[partner] = (
        "confirm"
        if places[partner][0] == desired
        else "deposit"
        if desired == "box"
        else "withdraw"
    )
    try:
        expected(points[partner], keys[partner], directions[partner], identity=identities[partner])
    except StorageRefusal as exc:
        # Opposite canonical operation, not stale-slot restoration.
        return {
            actor: "withdraw" if desired == "box" else "deposit",
            partner: "confirm",
        }, exc.reason
    return directions, None
