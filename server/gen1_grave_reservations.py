"""One per-player grave ownership chain shared by non-linked and linked archives.

Heads reference exact committed physical/file ACKs; they do not own storage by
label. Qualified frame inventory can refresh unrelated SRAM preimages while
the grave's reservation still has to match its prior owned bytes.
"""

import copy
import re

from server.event_reference import make, resolve
from server.gen1_full_save import layout
from server.gen1_memorial_policy import grave_digest
from server.protocol import digest
from server.protocol_journal import JournalError

COMPONENT = "gen1-grave-reservations"


def record_key(player):
    return digest({"component": COMPONENT, "player": player})[:32]


def checked(journal, player, head):
    if head is None:
        return None
    if (
        not isinstance(head, dict)
        or set(head)
        != {"event", "kind", "target", "revision", "after_digest", "reservation_digest"}
        or head["kind"] not in ("memorial", "retirement", "storage_compensation")
    ):
        raise JournalError("complete grave ownership head required")
    if (
        head["event"]["player"] != player
        or type(head["revision"]) is not int
        or head["revision"] < 1
    ):
        raise JournalError("grave head belongs to another owner/revision")
    for field in ("after_digest", "reservation_digest"):
        if not isinstance(head[field], str) or not re.fullmatch("[0-9a-f]{64}", head[field]):
            raise JournalError("grave head digest required")
    event = resolve(journal, head["event"])
    message = event.request
    if (
        event.revision != head["revision"]
        or event.result != {"ack": "ACK"}
        or message.get("event") != "command_ack"
        or message.get("outcome") != "ACK"
    ):
        raise JournalError("grave ownership lacks its committed physical ACK")
    command = journal.command(player, message["command_id"])
    kind, field = {
        "memorial": ("memorialize", "death_id"),
        "retirement": ("acquisition_retire", "acquisition_id"),
        "storage_compensation": ("storage_apply", "job_id"),
    }[head["kind"]]
    receipt = command["receipt"]
    if (
        command["outcome"] != "ACK"
        or command["body"].get("cmd") != kind
        or command["body"].get(field) != head["target"]
        or receipt != message.get("receipt")
        or digest(receipt["after"]) != head["after_digest"]
        or grave_digest(receipt["after"]) != head["reservation_digest"]
    ):
        raise JournalError("grave head differs from its exact archived image")
    return copy.deepcopy(receipt["after"])


def latest(journal, document, player):
    head = document["components"].get(COMPONENT, {}).get(player)
    if head is not None:
        checked(journal, player, head)
        return copy.deepcopy(head)
    # Explicit migration of older completed memorial evidence, never a raw box.
    from server.gen1_memorial_runtime import COMPONENT as MEMORIAL, expand_entry, is_complete

    entries = document["components"].get(MEMORIAL, {}).get("entries", {}).get(player, [])
    for entry in reversed(entries):
        if not is_complete(entry):
            continue
        value = expand_entry(journal, entry)
        event = value["receipt_event"]
        ref = make(player, event["operation_id"], event["message"])
        stored = resolve(journal, ref)
        after = value["payload"]["after"]
        result = {
            "event": ref,
            "kind": "memorial",
            "target": value["death_id"],
            "revision": stored.revision,
            "after_digest": digest(after),
            "reservation_digest": grave_digest(after),
        }
        checked(journal, player, result)
        return result
    return None


def source_point(journal, document, player, source):
    if source == {"kind": "initial"}:
        return document["components"]["gen1-initial-observations"][player]["observation"]["source"]
    if not isinstance(source, dict):
        raise JournalError("owned archive source reference required")
    if set(source) == {"kind", "head"} and source["kind"] == "grave":
        return checked(journal, player, source["head"])
    if set(source) == {"kind", "event"} and source["kind"] == "frame":
        # A checkpoint the owner published inside a containing event: a free-run observation
        # batch (P10) or a handed-back native loan settling its final inventory.
        event = resolve(journal, source["event"])
        if source["event"]["player"] != player:
            raise JournalError("archive source is not a settled owned frame")
        from server.gen1_initial_observation import validate

        initial = document["components"]["gen1-initial-observations"][player]
        if event.request.get("event") == "observation":
            observed = event.request.get("inventory")
            if observed is None or event.result.get("inventory_transition_digest") is None:
                raise JournalError("archive source batch recorded no checkpoint")
            validate(observed, initial["metadata"], initial["binding"])
            return observed["source"]
        if (
            event.request.get("event") != "native_frame_handoff"
            or event.result.get("observations_settled") is not True
        ):
            raise JournalError("archive source is not a settled owned frame")
        from server.gen1_native_frame_accounting import FRAMES, retained_return
        from server.gen1_observation_provenance import observation_bundle

        observed = observation_bundle(event.request)["inventory"]
        validate(observed, initial["metadata"], initial["binding"])
        closed = retained_return(
            journal, player, event.result.get("closed_frame_digest", ""),
            document["components"][FRAMES][player]["ledger"]["anchor"],
        )
        if closed["receipt"]["after"] != observed["frame"]:
            raise JournalError("archive source differs from its retained frame")
        return observed["source"]
    raise JournalError("unknown archive source reference")


def before_preparation(journal, head, source, revision):
    """An archive cannot borrow ownership from an event it caused later."""
    if head is not None and head["revision"] >= revision:
        raise JournalError("grave ownership does not precede its preparation")
    if source.get("kind") == "frame" and resolve(journal, source["event"]).revision >= revision:
        raise JournalError("archive source does not precede its preparation")
    if source.get("kind") == "grave" and source["head"]["revision"] >= revision:
        raise JournalError("archive source grave does not precede its preparation")


def check_preimage(journal, document, player, point, head, *, source=None):
    """Use the newest already-owned source, never the incoming point itself."""
    candidates = [(0, {"kind": "initial"})]
    if head is not None:
        candidates.append((head["revision"], {"kind": "grave", "head": copy.deepcopy(head)}))
    entry = document["components"].get("gen1-inventory-observations", {}).get(player)
    outer = None if entry is None else journal.event_snapshot(player, entry["operation_id"])
    if entry is not None and (entry.get("frame_origin") is not None
                              or outer is not None and outer.request.get("event") == "observation"):
        from server.event_reference import make
        from server.gen1_observation_provenance import semantic_receipt

        event = semantic_receipt(journal, player, entry, "inventory_observation")
        reference = (copy.deepcopy(entry["frame_origin"]) if entry.get("frame_origin") is not None
                     else make(player, entry["operation_id"], outer.request))
        candidates.append((event.revision, {"kind": "frame", "event": reference}))
    if source is None:
        _, source = max(candidates, key=lambda row: row[0])
    anchor_point = source_point(journal, document, player, source)
    info = layout(point["variant"])
    before = bytes.fromhex(point["cart_hex"])
    old = bytes.fromhex(anchor_point["cart_hex"])
    if (
        before[: info["start"]] != old[: info["start"]]
        or before[info["checksum"] + 1 :] != old[info["checksum"] + 1 :]
    ):
        raise JournalError("archive SRAM differs outside its owned source-preimage chain")
    return copy.deepcopy(source)


def advance(
    journal, document, player, operation, message, after, *, kind, target, previous, revision
):
    if latest(journal, document, player) != previous:
        raise JournalError("another archive advanced the grave reservation during preparation")
    head = {
        "event": make(player, operation, message),
        "kind": kind,
        "target": target,
        "revision": revision,
        "after_digest": digest(after),
        "reservation_digest": grave_digest(after),
    }
    document["components"].setdefault(COMPONENT, {})[player] = head
    return {"namespace": COMPONENT, "key": record_key(player), "value": copy.deepcopy(head)}


def verify_journal(journal, document):
    heads = document["components"].get(COMPONENT, {})
    if not isinstance(heads, dict) or set(heads) - {"a", "b"}:
        raise JournalError("invalid per-player grave ownership heads")
    for player in ("a", "b"):
        head = heads.get(player)
        record = journal.record(COMPONENT, record_key(player))
        if (
            (head is None) != (record is None)
            or head is not None
            and (record.value != head or record.revision != head["revision"])
        ):
            raise JournalError("grave ownership differs from its atomic head record")
        checked(journal, player, head)


def memorial_busy(document, player):
    from server.gen1_memorial_runtime import COMPONENT as MEMORIAL, is_complete

    entries = document["components"].get(MEMORIAL, {}).get("entries", {}).get(player, [])
    return bool(entries and not is_complete(entries[-1]))


def retirement_busy(document, player):
    return any(
        row["receipt_operation"] is None
        for row in document["components"].get("gen1-acquisition-retirement", {}).get(player, [])
    ) or any(
        not row["complete"] and player in row["keys"]
        for row in document["components"]
        .get("gen1-storage-settlement", {})
        .get("jobs", {})
        .values()
    )
