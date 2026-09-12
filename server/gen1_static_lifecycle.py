"""At most one live static-battle origin per player, consumed once or invalidated at battle end.

`gen1_static_receipt.attribute` joins a capture to an origin by map, species, level and
frame order; it cannot tell the static's own battle from a later wild battle of the same
kind on the same map. This component can, by order: an origin opens when its `began`
receipt decodes, is consumed by the first joining capture whose call precedes the battle's
end, and is closed by the battle_end fact whatever wBattleResult says (win, loss, RUN, or a
capture that was already consumed). A ball that breaks free is not a battle end (the engine
returns to the battle loop with carry clear), so it neither consumes nor closes. A second
`began` while one origin is live supersedes it: battles never nest, so the earlier one ended
unobserved (reset, state load) and must never attribute anything.

Evidence that matches a battle's operands without proving it is that battle (a call before
the live origin began, or two origins that both join) is HELD: the capture is neither
attributed nor treated as wild, and `gen1_frame_acquisitions` keeps it out of acquisition
settlement until reconciliation. Every row keeps `source_ref = {event, index}` to the raw
receipt inside its committed event, as acquisition facts do. `stage` mutates only the
detached document it is given and returns the journal record for root's atomic commit.
"""

import copy

from server import event_reference
from server.gen1_static_receipt import DATA, attribute
from server.protocol import digest
from server.protocol_journal import JournalError

COMPONENT = "gen1-static-origins"
SITES = DATA["titles"]["red"]["sites"]  # static ids are title-neutral (asserted by the generator)
STATES = ("live", "consumed", "ended", "superseded")
ORIGIN = {"static_id", "fact", "source_ref", "state", "capture", "end", "superseded_by"}
ROW = {"origins", "attributions", "held"}
OPERANDS = ("map_id", "battle_type", "species_index", "level")
HOLD = "hold"  # consume()'s answer for evidence that is neither this static's nor provably wild
HOLD_REASON = 'Static capture source is ambiguous; reconciliation required'
MAX_FACTS = 64


def held_blockers(document):
    return {digest({'static_hold': player, 'source': row['source_ref']})[:32]: HOLD_REASON
            for player, entry in document['components'].get(COMPONENT, {}).items() for row in entry['held']}


def record_key(player):
    return digest({"component": COMPONENT, "player": player})[:32]


def new_row():
    return {"origins": [], "attributions": {}, "held": []}


def _ref(value):
    if not isinstance(value, dict) or set(value) != {"event", "index"} or type(value["index"]) is not int or value["index"] < 0:
        raise JournalError("static fact lacks its exact source row")
    event_reference.validate(value["event"])
    return copy.deepcopy(value)


def _live(row):
    live = [origin for origin in row["origins"] if origin["state"] == "live"]
    if len(live) > 1:
        raise JournalError("more than one live static origin")
    return live[0] if live else None


def open(row, origin_fact, source_ref):
    """Open the origin; a live one is superseded (never refused: the new battle's evidence is real)."""
    if not isinstance(origin_fact, dict) or origin_fact.get("kind") != "static_origin" or origin_fact.get("static_id") not in SITES:
        raise JournalError("static origin fact required")
    if type(origin_fact.get("began_frame")) is not int:
        raise JournalError("static origin fact lacks its began frame")
    reference = _ref(source_ref)
    live = _live(row)
    if live is not None:
        live["state"], live["superseded_by"] = "superseded", reference
    row["origins"].append({"static_id": origin_fact["static_id"], "fact": copy.deepcopy(origin_fact), "source_ref": reference,
                           "state": "live", "capture": None, "end": None, "superseded_by": None})
    return origin_fact["static_id"]


def consume(row, capture_fact, source_ref, *, variant):
    """The static this capture came from, consumed once; None for an ordinary wild capture; HOLD when unsure.

    Eligible origins are the live one and an ended one whose battle_end frame is at or after
    the capture call (root may list the end before the capture within one bundle); a consumed
    or superseded origin never joins again. A capture with an eligible origin's exact operands
    whose call precedes that battle's `began`, or one that two eligible origins both join, is
    held: it is recorded under `held` and settles nothing until reconciliation.
    """
    if (not isinstance(capture_fact, dict) or capture_fact.get("kind") != "capture" or not isinstance(capture_fact.get("key"), str)
            or type(capture_fact.get("call_frame")) is not int):
        raise JournalError("decoded capture fact required")
    reference = _ref(source_ref)
    key = capture_fact["key"]
    if key in row["attributions"] or any(item["fact"]["key"] == key for item in row["held"]):
        raise JournalError("capture key already attributed to a static")
    matches, ambiguous = [], False
    for origin in row["origins"]:
        if not (origin["state"] == "live" or (origin["state"] == "ended" and capture_fact["call_frame"] <= origin["end"]["frame"])):
            continue
        try:
            matches.append((origin, attribute(capture_fact, origin["fact"], variant=variant)))
        except JournalError:
            # Another map/species/level: not this static. The same operands out of order: unknown, never wild by default.
            ambiguous = ambiguous or all(capture_fact[field] == origin["fact"][field] for field in OPERANDS)
    if ambiguous or len(matches) > 1:
        row["held"].append({"kind": "capture", "fact": copy.deepcopy(capture_fact), "source_ref": reference})
        return HOLD
    if not matches:
        return None
    origin, static_id = matches[0]
    origin["state"] = "consumed"
    origin["capture"] = {"source_ref": reference, "key": key, "call_frame": capture_fact["call_frame"]}
    row["attributions"][key] = static_id
    return static_id


def close(row, end_fact, source_ref):
    """Invalidate the live origin, whatever the result; nothing live is a no-op (already consumed)."""
    if (not isinstance(end_fact, dict) or end_fact.get("kind") != "static_battle_end" or type(end_fact.get("frame")) is not int
            or end_fact.get("battle_result") not in (0, 1, 2)):
        raise JournalError("static battle end fact required")
    reference = _ref(source_ref)
    live = _live(row)
    if live is None:
        return None
    live["state"] = "ended"
    live["end"] = {"source_ref": reference, "frame": end_fact["frame"], "battle_result": end_fact["battle_result"]}
    return live["static_id"]


def stage(target, player, facts, frame_origin, *, variant=None):
    """Apply decoded `{kind, fact, source_ref}` rows in list order; return root's journal record.

    `target` is the detached document (its component row is created on demand and the
    variant read from the initial observation) or a bare component row. Rows of kind
    `static_origin` open, `capture` consume, `static_battle_end` close; `grant` rows are
    skipped so root may pass its whole decoded acquisition list. Order within the list is
    root's: origins before captures of the same bundle. `attributions` in the answer are the
    row's cumulative capture->static map; `held` lists the capture keys this call held.
    """
    origin = event_reference.validate(frame_origin)
    if origin["player"] != player:
        raise JournalError("static frame origin belongs to another player")
    if isinstance(target, dict) and "components" in target:
        row = target["components"].setdefault(COMPONENT, {}).setdefault(player, new_row())
        if variant is None:
            variant = target["components"]["gen1-initial-observations"][player]["metadata"]["gen1_metadata"]["cartridge"]["variant"]
    else:
        row = target
    if variant not in DATA["titles"]:
        raise JournalError("RBY static variant required")
    if not isinstance(facts, list) or len(facts) > MAX_FACTS:
        raise JournalError("bounded static lifecycle facts required")
    held = []
    for item in facts:
        if not isinstance(item, dict) or set(item) != {"kind", "fact", "source_ref"} or _ref(item["source_ref"])["event"] != origin:
            raise JournalError("static lifecycle fact is not a row of this frame")
        if item["kind"] == "static_origin":
            open(row, item["fact"], item["source_ref"])
        elif item["kind"] == "capture":
            if consume(row, item["fact"], item["source_ref"], variant=variant) == HOLD:
                held.append(item["fact"]["key"])
        elif item["kind"] == "static_battle_end":
            close(row, item["fact"], item["source_ref"])
        elif item["kind"] != "grant":
            raise JournalError("unknown static lifecycle fact kind")
    return {"records": [{"namespace": COMPONENT, "key": record_key(player), "value": copy.deepcopy(row)}],
            "attributions": copy.deepcopy(row["attributions"]), "held": held}


def verify_state(component):
    """Re-derive the invariants of a restored `{player: row}` component."""
    if not isinstance(component, dict) or set(component) - {"a", "b"}:
        raise JournalError("invalid static origin component")
    for player, row in component.items():
        if not isinstance(row, dict) or set(row) != ROW or not isinstance(row["origins"], list) \
                or not isinstance(row["attributions"], dict) or not isinstance(row["held"], list):
            raise JournalError("invalid static origin row")
        live, expected = 0, {}
        for origin in row["origins"]:
            if not isinstance(origin, dict) or set(origin) != ORIGIN or origin["state"] not in STATES:
                raise JournalError("invalid static origin record")
            fact, state = origin["fact"], origin["state"]
            if (not isinstance(fact, dict) or fact.get("kind") != "static_origin" or fact.get("static_id") != origin["static_id"]
                    or origin["static_id"] not in SITES or type(fact.get("began_frame")) is not int):
                raise JournalError("static origin record differs from its fact")
            if _ref(origin["source_ref"])["event"]["player"] != player:
                raise JournalError("static origin source belongs to another player")
            capture, end, superseded = origin["capture"], origin["end"], origin["superseded_by"]
            if ((capture is not None) != (state == "consumed") or (superseded is not None) != (state == "superseded")
                    or (end is None) == (state == "ended") and state != "consumed" or state == "superseded" and end is not None):
                raise JournalError("static origin resolution differs from its state")
            live += state == "live"
            if superseded is not None:
                _ref(superseded)
            if end is not None:
                if set(end) != {"source_ref", "frame", "battle_result"} or type(end["frame"]) is not int or end["battle_result"] not in (0, 1, 2):
                    raise JournalError("invalid static battle end record")
                _ref(end["source_ref"])
            if capture is not None:
                if (set(capture) != {"source_ref", "key", "call_frame"} or not isinstance(capture["key"], str)
                        or type(capture["call_frame"]) is not int or capture["call_frame"] < fact["began_frame"]
                        or end is not None and capture["call_frame"] > end["frame"] or capture["key"] in expected):
                    raise JournalError("static consumption is not inside its battle")
                _ref(capture["source_ref"])
                expected[capture["key"]] = origin["static_id"]
        if live > 1:
            raise JournalError("more than one live static origin")
        if row["attributions"] != expected:
            raise JournalError("static attributions differ from consumed origins")
        held = set()
        for item in row["held"]:
            fact = item.get("fact") if isinstance(item, dict) else None
            if (not isinstance(item, dict) or set(item) != {"kind", "fact", "source_ref"} or item["kind"] != "capture"
                    or not isinstance(fact, dict) or fact.get("kind") != "capture" or not isinstance(fact.get("key"), str)
                    or fact["key"] in expected or fact["key"] in held):
                raise JournalError("invalid held static capture")
            if _ref(item["source_ref"])["event"]["player"] != player:
                raise JournalError("held static capture belongs to another player")
            held.add(fact["key"])


def _source_fact(journal, stage, player, reference, kind, revision, rom_provider):
    """Re-decode the raw row a source_ref names (refusing any other kind) and re-verify its witness frames."""
    from server.gen1_acquisition_runtime import source_rom
    from server.gen1_frame_acquisitions import retained_return, verify_frames
    from server.gen1_frame_runtime import anchor
    from server.gen1_source_receipts import decode

    document = stage.document()
    initial = document["components"]["gen1-initial-observations"][player]
    snapshot = event_reference.resolve(journal, reference["event"])
    rows = snapshot.request.get("bundle", {}).get("acquisitions") or []
    if (reference["event"]["player"] != player or snapshot.request.get("event") != "frame_complete"
            or type(reference["index"]) is not int or not 0 <= reference["index"] < len(rows) or snapshot.revision > revision):
        raise JournalError("static source reference leaves its receipt list")
    row = rows[reference["index"]]
    rom = source_rom(initial["metadata"], player, rom_provider)
    decoded = decode([row], initial["metadata"], initial["binding"], reference=reference["event"], rom=rom, kinds=(kind,))[0]
    bound = anchor(document, player)
    closed = retained_return(journal, player, snapshot.result.get("closed_frame_digest", ""), bound)
    if closed["receipt"] != snapshot.request["receipt"]:
        raise JournalError("static source differs from retained frame receipt")
    verify_frames(journal, player, bound, closed, [row], [decoded])
    return decoded["fact"]


def verify_journal(journal, stage, *, rom_provider=None):
    """Every origin, consumption, end and held capture re-decodes from the raw row its source_ref names."""
    document = stage.document()
    component = document["components"].get(COMPONENT, {})
    for player in ("a", "b"):
        stored = journal.record(COMPONENT, record_key(player))
        row = component.get(player)
        if (stored is None) != (row is None) or stored is not None and stored.value != row:
            raise JournalError("static origin component differs from its atomic journal record")
        if row is None:
            continue
        for origin in row["origins"]:
            if _source_fact(journal, stage, player, origin["source_ref"], "static_origin", stored.revision, rom_provider) != origin["fact"]:
                raise JournalError("static origin differs from its authoritative receipt")
            if origin["superseded_by"] is not None:
                _source_fact(journal, stage, player, origin["superseded_by"], "static_origin", stored.revision, rom_provider)
            if origin["capture"] is not None:
                fact = _source_fact(journal, stage, player, origin["capture"]["source_ref"], "capture", stored.revision, rom_provider)
                if fact["key"] != origin["capture"]["key"] or fact["call_frame"] != origin["capture"]["call_frame"]:
                    raise JournalError("static consumption differs from its authoritative capture receipt")
            if origin["end"] is not None:
                fact = _source_fact(journal, stage, player, origin["end"]["source_ref"], "static_battle_end", stored.revision, rom_provider)
                if fact["frame"] != origin["end"]["frame"] or fact["battle_result"] != origin["end"]["battle_result"]:
                    raise JournalError("static battle end differs from its authoritative receipt")
        for item in row["held"]:
            if _source_fact(journal, stage, player, item["source_ref"], "capture", stored.revision, rom_provider) != item["fact"]:
                raise JournalError("held static capture differs from its authoritative receipt")
