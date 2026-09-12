"""Attribute RBY inventory changes to checked command ACKs, never client claims.

Compact deltas preserve raw observations and every unattributed gap around known
writes. Force-faint proves only a party footprint; full-save operations prove a
complete save point. Journal revision orders writes even at one emulated frame.
"""

import copy

from server.frame_progress import identifier, integer
from server.gen1_full_save import image
from server.hex_delta import apply, between
from server.protocol import digest
from server.protocol_journal import JournalError

SCHEMA = "rby-authorized-inventory-v1"
NATIVE = {
    "native_receptionist",
    "native_trade_prompt",
    "native_trade_prepare",
    "native_trade_commit",
    "native_trade_release",
    "native_trade_abort",
}
INVENTORY = "gen1-inventory-observations"
INITIAL = "gen1-initial-observations"


def predecessor_receipt(journal, player, initial, old):
    """Resolve the actual prior semantic commit, including compound frame events."""
    if old is None:
        event = journal.event_snapshot(player, initial["operation_id"])
        if (
            event is None
            or event.request != {"event": "initial_observation", "payload": initial["observation"]}
            or event.result
            != {
                "ack": "ACK",
                "inventory_digest": digest(initial["inventory"]),
                "ordinary_execution": False,
            }
        ):
            raise JournalError("inventory lacks its original initial-observation event")
        return event
    from server.gen1_inventory_observation import result
    from server.gen1_observation_provenance import semantic_receipt

    event = semantic_receipt(journal, player, old, "inventory_observation")
    if event is None or event.result != result(old):
        raise JournalError("inventory predecessor lacks its exact semantic result")
    return event


def delta(before, after):
    image(before)
    image(after)
    if before["variant"] != after["variant"]:
        raise JournalError("inventory write changed cartridge variant")
    return {
        "before_digest": digest(before),
        "after_digest": digest(after),
        "cart": between(before["cart_hex"], after["cart_hex"]),
        "fields": {
            name: between(before["fields"][name], value)
            for name, value in after["fields"].items()
            if value != before["fields"][name]
        },
        "save_status": after["save_status"],
    }


def _apply(point, change):
    if not isinstance(change, dict) or set(change) != {
        "before_digest",
        "after_digest",
        "cart",
        "fields",
        "save_status",
    }:
        raise JournalError("complete authorized-inventory point delta required")
    if digest(point) != change["before_digest"] or not isinstance(change["fields"], dict):
        raise JournalError("inventory delta differs from its exact preimage")
    after = copy.deepcopy(point)
    after["cart_hex"] = apply(point["cart_hex"], change["cart"])
    for name, value in change["fields"].items():
        if name not in point["fields"]:
            raise JournalError("unknown authorized inventory memory field")
        after["fields"][name] = apply(point["fields"][name], value)
    after["save_status"] = change["save_status"]
    image(after)
    if digest(after) != change["after_digest"]:
        raise JournalError("inventory delta postimage differs")
    return after


def replay(before, plan):
    """Pure structural replay; only verify_journal establishes ACK provenance."""
    if (
        not isinstance(plan, dict)
        or set(plan) != {"schema", "after_revision", "through_revision", "writes"}
        or plan["schema"] != SCHEMA
    ):
        raise JournalError("typed authorized-inventory replay plan required")
    low, high = integer(plan["after_revision"]), integer(plan["through_revision"])
    if low > high or not isinstance(plan["writes"], list) or len(plan["writes"]) > 128:
        raise JournalError("bounded ordered inventory write interval required")
    current, steps, last_revision, last_sequence = copy.deepcopy(before), [], low, 0
    for row in plan["writes"]:
        if not isinstance(row, dict) or set(row) != {"reference", "gap", "effect"}:
            raise JournalError("complete attributed inventory write required")
        ref = row["reference"]
        if (
            not isinstance(ref, dict)
            or set(ref)
            != {
                "kind",
                "player",
                "operation_id",
                "revision",
                "command_id",
                "command_sequence",
                "context_generation",
                "command_digest",
                "receipt_digest",
            }
            or ref["kind"] not in {"initial_save", "force_faint", "memorialize", "acquisition_retire", "storage_apply"} | NATIVE
            or ref["player"] not in ("a", "b")
        ):
            raise JournalError("typed inventory command reference required")
        for name in ("operation_id", "command_id", "context_generation"):
            identifier(ref[name])
        for name in ("command_digest", "receipt_digest"):
            identifier(ref[name], 64)
        revision, sequence = integer(ref["revision"], 1), integer(ref["command_sequence"], 1)
        if not last_revision < revision <= high or sequence <= last_sequence:
            raise JournalError("inventory command ACK order differs")
        pre = _apply(current, row["gap"])
        post = _apply(pre, row["effect"])
        steps.append((current, pre, post, ref))
        current, last_revision, last_sequence = post, revision, sequence
    return steps, current


def _ack(journal, player, operation):
    event = journal.event_snapshot(player, operation)
    if event is None:
        raise JournalError("authorized inventory write lost its command ACK event")
    request = event.request
    if (
        set(request) != {"event", "command_id", "command_sequence", "outcome", "receipt"}
        or request["event"] != "command_ack"
        or request["outcome"] != "ACK"
    ):
        raise JournalError("exact inventory mutation ACK required")
    command = journal.command(player, request["command_id"])
    if (
        command["outcome"] != "ACK"
        or type(request["command_sequence"]) is not int
        or request["command_sequence"] != command["command_sequence"]
        or command["receipt"] != request["receipt"]
        or event.result != {"ack": "ACK"}
    ):
        raise JournalError("inventory mutation differs from its checked command receipt")
    return event, command


def _party(point, snapshot):
    """Replace only snapshot-proved party bytes; preserve unwitnessed unused tails."""
    result = copy.deepcopy(point)
    raw = bytearray.fromhex(point["fields"]["party"])
    count = snapshot["party_count"]
    raw[0] = count
    raw[1 : count + 2] = bytes(snapshot["species_list"])
    for slot, text in enumerate(snapshot["party"]):
        blob = bytes.fromhex(text)
        raw[8 + 44 * slot : 52 + 44 * slot] = blob[:44]
        raw[272 + 11 * slot : 283 + 11 * slot] = blob[44:55]
        raw[338 + 11 * slot : 349 + 11 * slot] = blob[55:]
    result["fields"]["party"] = raw.hex().upper()
    return result


def _native_snapshot(point, snapshot):
    from server.gen1_full_save import SYMBOLS

    result = copy.deepcopy(point)
    result["fields"]["party"] = snapshot["party_storage_hex"]
    if "save_name_hex" in snapshot:
        result["fields"]["name"] = snapshot["save_name_hex"]
    symbols = SYMBOLS["pokeyellow" if point["variant"] == "yellow" else "pokered"]
    main = bytearray.fromhex(result["fields"]["main"])
    main[symbols["wCurMap"] - symbols["wMainDataStart"]] = snapshot["map"]
    for field, symbol, size in (
        ("dex_hex", "wPokedexOwned", 38),
        ("pikachu_hex", "wPikachuHappiness", 2),
    ):
        if field in snapshot:
            raw = bytes.fromhex(snapshot[field])
            if len(raw) != size:
                raise JournalError("native inventory footprint has invalid width")
            start = symbols[symbol] - symbols["wMainDataStart"]
            main[start : start + size] = raw
    result["fields"]["main"] = main.hex().upper()
    image(result)
    return result


def _native_points(journal, player, current, command, receipt, entry):
    from server.gen1_full_save import matches_checkpoint
    from server.gen1_native_frame_accounting import _post_source

    kind = command["body"]["cmd"]
    observed = entry["native_return"]["inventory"]["source"]
    if kind == "native_trade_prepare":
        saved = receipt["stages"]["save"]
        pre = saved["point"]
        expected = image(pre).hex().upper()
        if saved["image_hex"] != expected:
            raise JournalError("native preparation save image changed")
        post = {**copy.deepcopy(pre), "cart_hex": expected, "save_status": 2}
        matches_checkpoint(observed, receipt["stages"]["ready"]["checkpoint"])
        if observed != post:
            raise JournalError("native preparation changed its held full-save fields")
        return pre, post
    if kind == "native_trade_commit":
        first = entry["native_initial"]
        if (
            not isinstance(first, dict)
            or first.get("phase") != "before"
            or "checkpoint" not in first
        ):
            raise JournalError("native trade lost its original preimage window")
        native = receipt["native"]
        pre = _native_snapshot(current, native["before"])
        pre["cart_hex"] = first["checkpoint"]["cart_hex"]
        matches_checkpoint(pre, first["checkpoint"])
        post = _native_snapshot(pre, native["after"])
        post["cart_hex"] = receipt["save_image_hex"]
        footprint = _native_snapshot(observed, native["after"])
        if footprint != observed or observed["cart_hex"] != post["cart_hex"]:
            raise JournalError("native trade return differs from its verified mutation footprint")
        return pre, post
    if kind == "native_trade_prompt":
        import hashlib

        after = receipt["after"]
        if (
            observed["fields"]["party"] != after["party_storage_hex"]
            or hashlib.sha256(observed["cart_hex"].encode("ascii")).hexdigest()
            != after["cart_digest"]
        ):
            raise JournalError("native prompt changed its verified inventory")
    else:
        _post_source(journal, player, command, observed)
    # UI/closure does not authorize a party or save mutation. Its observed
    # clock/UI/source drift remains in the explicit unattributed gap.
    return observed, observed


def _candidates(journal, document, player, low, high):
    """Return checked events and source-owned evidence without scanning SQL rows."""
    components = document["components"]
    entries = []
    initial_save = components.get("gen1-initial-save", {}).get(player)
    if initial_save and initial_save["receipt_operation"]:
        entries.append(("initial_save", initial_save["receipt_operation"], initial_save))
    for entry in components.get('gen1-acquisition-retirement', {}).get(player, []):
        if entry['receipt_operation'] is not None:
            entries.append(('acquisition_retire', entry['receipt_operation'], entry))
    for entry in components.get('gen1-storage-settlement', {}).get('jobs', {}).values():
        reference = entry['writes'].get(player)
        if reference is not None:
            entries.append(('storage_apply', reference['operation_id'], entry))
    for death in components.get("gen1-faint-settlement", {}).get("deaths", {}).values():
        if death["peer"] == player and death.get("receipt_event"):
            entries.append(("force_faint", death["receipt_event"]["operation_id"], death))
    from server.gen1_memorial_runtime import COMPLETED, expand_entry, is_complete

    for entry in components.get("gen1-memorial-settlement", {}).get("entries", {}).get(player, []):
        if not is_complete(entry):
            continue
        if entry.get("schema") == COMPLETED and not low < entry["record_revision"] <= high:
            continue
        expanded = expand_entry(journal, entry)
        entries.append(("memorialize", expanded["receipt_event"]["operation_id"], expanded))
    result = []
    for kind, operation, entry in entries:
        event, command = _ack(journal, player, operation)
        if low < event.revision <= high:
            if command["body"].get("cmd") != kind:
                raise JournalError("inventory mutation component names another command kind")
            if kind == 'acquisition_retire':
                from server.gen1_retirement_runtime import expand_entry
                entry = expand_entry(journal, entry)
            result.append((event.revision, kind, event, command, entry))
    from server.gen1_native_frame_accounting import completed_commands

    result.extend(completed_commands(journal, player, low, high))
    return sorted(result, key=lambda row: row[0])


def build(
    journal, document, player, before, after, *, after_revision, through_revision, historical=False
):
    """Build trusted replay segments from raw observations and retained ACKs."""
    if player not in ("a", "b") or document["active_trade"] and not historical:
        raise JournalError("owned non-trade inventory stream required")
    initial = document["components"][INITIAL][player]
    from server.gen1_initial_observation import validate

    for point in (before, after):
        validate(point, initial["metadata"], initial["binding"])
        if point["host"] != initial["observation"]["host"]:
            raise JournalError("inventory mutation belongs to another physical owner")
    plan = {
        "schema": SCHEMA,
        "after_revision": after_revision,
        "through_revision": through_revision,
        "writes": [],
    }
    replay(before["source"], plan)
    current = copy.deepcopy(before["source"])
    identity = initial["metadata"]["save_identity"]
    for revision, kind, event, command, entry in _candidates(
        journal, document, player, after_revision, through_revision
    ):
        receipt = event.request["receipt"]
        if kind == "initial_save":
            from server.gen1_initial_save import verify_receipt
            from server.gen1_initial_save_runtime import arguments, original_command, prepared

            if (
                command != original_command(journal, player, entry)
                or digest(receipt) != entry["receipt_digest"]
            ):
                raise JournalError("initial inventory save is not its original command")
            value = prepared(document, player)
            verify_receipt(command, receipt, value["before"], **arguments(document, player))
            pre, post = value["before"], value["after"]
        elif kind == 'acquisition_retire':
            from server.gen1_retirement_runtime import verify_write_receipt, write_body
            from server.issued_command import issued
            value = entry['payload']
            if (value is None or command != issued(journal, player, entry['observation_event'], write_body(entry))
                    or digest(receipt) != entry['receipt_digest']
                    or value['context_generation'] != initial['binding']['context_generation']
                    or value['final_sha1'] != initial['metadata']['gen1_metadata']['cartridge']['final_rom_sha1']):
                raise JournalError('inventory retirement is not its original owned image')
            # The runtime verifier knows every retirement shape (archive, and the in-place starter_clause faint).
            verify_write_receipt(command, receipt, entry, identity=identity)
            pre, post = value['before'], value['after']
        elif kind == 'storage_apply':
            from server import event_reference
            from server.issued_command import issued
            from server.gen1_storage import verify_receipt
            from server.gen1_storage_runtime import expand_entry, write_body

            entry=expand_entry(journal,entry)
            value = entry['prepared'].get(player)
            if (value is None or event_reference.resolve(journal, entry['writes'][player]) != event
                    or command != issued(journal, player, entry['write_origin'], write_body(entry, player))
                    or value['context_generation'] != initial['binding']['context_generation']
                    or value['final_sha1'] != initial['metadata']['gen1_metadata']['cartridge']['final_rom_sha1']):
                raise JournalError('inventory storage is not its original owned image')
            verify_receipt(command, receipt, value, identity=identity)
            pre, post = value['before'], value['after']
        elif kind == "force_faint":
            from server.gen1_command_receipts import verify_force_faint_receipt
            from server.gen1_faint_runtime import _command_origin, identifier as death_identifier

            origin = _command_origin(journal, entry)
            death_id = death_identifier(
                entry["player"], entry["engine_record"]["operation_id"], entry["index"]
            )
            if (
                origin is None
                or command["command_id"] not in origin.command_ids
                or command["body"].get("key") != entry["peer_key"]
                or command["body"].get("death_id") != death_id
                or event.request != entry["receipt_event"]["message"]
            ):
                raise JournalError("forced inventory faint lacks its original death command")
            verify_force_faint_receipt(
                command["body"], receipt, variant=current["variant"], identity=identity
            )
            pre = _party(current, receipt["before"])
            post = _party(pre, receipt["after"])
        elif kind in NATIVE:
            native_return = entry["native_return"]
            if (
                native_return["inventory"]["context_generation"]
                != initial["binding"]["context_generation"]
                or native_return["inventory"]["final_sha1"]
                != initial["metadata"]["gen1_metadata"]["cartridge"]["final_rom_sha1"]
            ):
                raise JournalError("native mutation belongs to another admitted context")
            pre, post = _native_points(journal, player, current, command, receipt, entry)
            value = {"frame": native_return["inventory"]["frame"]}
        else:
            from server.gen1_memorial import verify_receipt
            from server.gen1_memorial_runtime import wire_payload

            value = entry["payload"]
            if (
                command["body"].get("payload") != wire_payload(value)
                or command["body"].get("death_id") != entry["death_id"]
                or event.request != entry["receipt_event"]["message"]
                or entry["receipt_event"]["player"] != player
                or value["context_generation"] != initial["binding"]["context_generation"]
                or value["final_sha1"]
                != initial["metadata"]["gen1_metadata"]["cartridge"]["final_rom_sha1"]
            ):
                raise JournalError("inventory memorial is not its original prepared image")
            verify_receipt(
                command,
                receipt,
                identity=identity,
                **{
                    key: value[key]
                    for key in (
                        "before",
                        "context_generation",
                        "final_sha1",
                        "frame",
                        "reserved_digest",
                    )
                },
            )
            pre, post = value["before"], value["after"]
        if kind != "force_faint" and not before["frame"] <= value["frame"] <= after["frame"]:
            raise JournalError("saved inventory mutation lies outside its observed frame interval")
        ref = {
            "kind": kind,
            "player": player,
            "operation_id": entry["native_return"]["receipt_operation_id"]
            if kind in NATIVE
            else (
                entry["receipt_operation"]
                if kind in {"initial_save", "acquisition_retire"}
                else entry['writes'][player]['operation_id'] if kind == 'storage_apply'
                else entry["receipt_event"]["operation_id"]
            ),
            "revision": revision,
            "command_id": command["command_id"],
            "command_sequence": command["command_sequence"],
            "context_generation": initial["binding"]["context_generation"],
            "command_digest": digest(command["body"]),
            "receipt_digest": digest(receipt),
        }
        plan["writes"].append(
            {"reference": ref, "gap": delta(current, pre), "effect": delta(pre, post)}
        )
        current = copy.deepcopy(post)
    replay(before["source"], plan)
    return plan
