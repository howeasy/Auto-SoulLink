"""Journal-owned memorial preparation, serialized storage and paired closure."""

import copy
import re

from server.gen1_engine_bridge import memorial_completion as record_memorial_completion
from server.gen1_faint_runtime import COMPONENT as FAINT, synchronize
from server.gen1_full_save import layout
from server.gen1_held_faint import verify_owned_checkpoint
from server.gen1_initial_observation import inventory
from server.gen1_memorial import expected, reservation, verify_receipt
from server.gen1_party_codec import PartyCodec
from server.held_write_permit import VerifiedHeldWrite
from server.operation_scope import command_scope
from server.protocol import digest
from server.protocol_journal import JournalError, _identifier

COMPONENT = "gen1-memorial-settlement"
OBSERVE = "rby-memorial-observation-v1"
EVIDENCE = "rby-held-memorial-evidence-v1"
COMPLETED = 'rby-memorial-completed-ref-v1'
RETAINED = 'rby-terminal-memorial-retained-v1'


def is_complete(entry):
    return entry.get('schema')==COMPLETED or entry.get('receipt_event') is not None


def expand_entry(journal, entry):
    if entry.get('schema')!=COMPLETED:
        return entry
    record=journal.record(COMPONENT,entry['record_key'])
    if (record is None or set(record.value)!={'death_id','origin','observations','observation_event','payload','receipt_event'}
            or not isinstance(record.value['payload'],dict) or not isinstance(record.value['receipt_event'],dict)
            or record.revision!=entry['record_revision'] or digest(record.value)!=entry['record_digest']
            or record.value.get('death_id')!=entry['death_id'] or not is_complete(record.value)
            or reservation(record.value['payload']['after'])!=entry['reservation_digest']):
        raise JournalError('completed memorial evidence reference differs from its atomic record')
    return record.value


def archive_entry(player,entry,revision):
    key=digest({'component':COMPONENT,'player':player,'death_id':entry['death_id']})[:32]
    reference={'schema':COMPLETED,'death_id':entry['death_id'],'record_key':key,'record_revision':revision,
        'record_digest':digest(entry),'reservation_digest':reservation(entry['payload']['after'])}
    return reference,{'namespace':COMPONENT,'key':key,'value':copy.deepcopy(entry)}


def key_for(death, player):
    return death["key"] if player == death["player"] else death["peer_key"]


def schedule(document, operation, rules=None):
    """rules (stage.rules, optional): when given, arbitrate against a pending whiteout rebuild
    (C3 spec (3)). While this player has an ACTIVE rebuild_pending (state.py's own whiteout
    auto-rebuild pick, not yet finished) and currently has at most one physical party member,
    a memorial_observe for that last member is deferred -- gen1_memorial.py's own kernel refuses
    to bury the last party member outright (party[0]<=1 raises), and a queued memorial_observe
    would otherwise sit at the head of this player's obligation queue and block the rebuild
    retrieval that could bring a survivor in first. Scoped to an active rebuild only: outside
    one, a lone surviving party member's own death is memorialized exactly as before (this is
    the ordinary, frequently-exercised case -- most Gen 1 single-link fixtures have no rebuild
    in play at all). Every caller should pass rules; one caller (gen1_retirement_runtime.py) is
    out of this card's write scope and still omits it, so the default preserves its exact
    previous behaviour."""
    if FAINT not in document['components']:
        return {'a':[],'b':[]}
    component = document["components"].setdefault(COMPONENT, {"entries": {"a": [], "b": []}})
    commands = {"a": [], "b": []}
    for player in ("a", "b"):
        from server.gen1_grave_reservations import retirement_busy
        if retirement_busy(document,player):
            continue
        entries = component["entries"][player]
        if entries and not is_complete(entries[-1]):
            continue
        known = {entry["death_id"] for entry in entries}
        for death_id, death in document["components"][FAINT]["deaths"].items():
            if death["phase"] != "pending_memorial" or death_id in known:
                continue
            if (
                rules is not None
                and rules.rebuild_pending.get(player)
                and rules.party_size.get(player, 0) <= 1
            ):
                continue
            entries.append(
                {
                    "death_id": death_id,
                    "origin": copy.deepcopy(operation),
                    "observation_event": None,
                    "observations": [],
                    "payload": None,
                    "receipt_event": None,
                }
            )
            commands[player].append(
                {"cmd": "memorial_observe", "death_id": death_id, "key": key_for(death, player)}
            )
            break
    return commands


def entry_for(document, player, death_id):
    entries = document["components"].get(COMPONENT, {}).get("entries", {}).get(player, [])
    matches = [entry for entry in entries if entry["death_id"] == death_id]
    if len(matches) != 1:
        raise JournalError("memorial requires exactly one owned obligation")
    return matches[0]


def previous_reservation(document, player, entry):
    if entry.get('payload') is not None and 'grave_head' in entry['payload']:
        head=entry['payload']['grave_head']
        return head['reservation_digest'] if head is not None else None
    entries = document["components"][COMPONENT]["entries"][player]
    index = next(i for i,row in enumerate(entries) if row['death_id']==entry['death_id'])
    if index == 0:
        return None
    previous = entries[index - 1]
    if not is_complete(previous):
        raise JournalError("previous memorial must finish before another preparation")
    return previous['reservation_digest'] if previous.get('schema')==COMPLETED else reservation(previous["payload"]["after"])


def observation_metadata(command, receipt, document, player, binding, *, historical=False):
    fields = {
        "schema",
        "command_id",
        "command_sequence",
        "context_generation",
        "final_sha1",
        "host",
        "checkpoint",
        "point",
    }
    if not isinstance(receipt, dict) or set(receipt) != fields or receipt["schema"] != OBSERVE:
        raise JournalError("complete command-bound memorial observation required")
    metadata = verify_owned_checkpoint(
        player, command, receipt, document, binding, historical=historical
    )
    point = receipt["point"]
    if (
        not isinstance(point, dict)
        or point.get("variant") != metadata["gen1_metadata"]["cartridge"]["variant"]
    ):
        raise JournalError("memorial observation cartridge differs")
    return metadata


def preparation(command, receipt, document, player, binding, *, historical=False, journal=None):
    from server import gen1_grave_reservations as graves
    from server.gen1_memorial_policy import storage_policy

    metadata = observation_metadata(command, receipt, document, player, binding, historical=historical)
    point = receipt['point']
    entry = entry_for(document, player, command["body"]["death_id"])
    stored = expand_entry(journal, entry) if entry.get('schema') == COMPLETED else entry
    legacy = historical and stored.get('payload') is not None and 'storage_policy' not in stored['payload']
    shared = not historical or stored.get('payload') is not None and 'grave_head' in stored['payload']
    head = (stored['payload']['grave_head'] if historical else graves.latest(journal,document,player)) if shared else None
    reserved = head['reservation_digest'] if head is not None else None
    if not shared:reserved=previous_reservation(document,player,entry)
    policy = None if legacy else storage_policy(point, reserved_digest=reserved)
    after = expected(
        point, command["body"]["key"], identity=metadata["save_identity"], reserved_digest=reserved,
        storage_policy=policy,
    )
    if shared:
        source=graves.check_preimage(journal,document,player,point,head,
            source=stored['payload']['source_anchor'] if historical else None)
    else:
        entries = document["components"][COMPONENT]["entries"][player]
        index = next(i for i,row in enumerate(entries) if row['death_id']==entry['death_id'])
        anchor = (expand_entry(journal,entries[index - 1])["payload"]["after"] if index
            else document["components"]["gen1-initial-observations"][player]["observation"]["source"])
        saved, original = bytes.fromhex(point["cart_hex"]), bytes.fromhex(anchor["cart_hex"])
        info = layout(point["variant"])
        if saved[:info['start']]!=original[:info['start']] or saved[info['checksum']+1:]!=original[info['checksum']+1:]:
            raise JournalError('memorial SRAM differs outside the owned save-data region')
    result = {
        "before": copy.deepcopy(point),
        "after": after,
        "reserved_digest": reserved,
        "context_generation": binding["context_generation"],
        "final_sha1": receipt["final_sha1"],
        "frame": receipt["host"]["frame"],
    }
    if not legacy:
        result['storage_policy'] = policy
    if shared:
        result.update(grave_head=head,source_anchor=source)
    return result


def wire_payload(payload):
    from server.gen1_save_delta import wire_payload as encode_delta

    return encode_delta(payload)


def acknowledge(runtime, player, operation, message):
    old = runtime.journal.event(player, operation, message)
    if old is not None:
        return old.result
    stage = runtime.state()
    document = stage.document()
    if (
        set(message) != {"event", "command_id", "command_sequence", "outcome", "receipt"}
        or message["outcome"] != "ACK"
    ):
        raise JournalError("exact memorial acknowledgement required")
    command = runtime.journal.command(player, message["command_id"])
    body = command["body"]
    entry = entry_for(document, player, body.get("death_id"))
    if (
        command["outcome"] is not None
        or type(message["command_sequence"]) is not int
        or message["command_sequence"] != command["command_sequence"]
        or runtime.journal.pending_ids(player)[0] != command["command_id"]
    ):
        raise JournalError("memorial acknowledgement must own the oldest command")
    death = document["components"][FAINT]["deaths"][body["death_id"]]
    if death["phase"] != "pending_memorial" or body.get("key") != key_for(death, player):
        raise JournalError("memorial death obligation differs")
    event = {"player": player, "operation_id": operation, "message": copy.deepcopy(message)}
    commands = {"a": [], "b": []}
    records=[]
    if body["cmd"] == "memorial_observe":
        if entry["observation_event"] is not None:
            raise JournalError("memorial observation already prepared")
        binding = runtime.gate.sessions[player].metadata["control_binding"]
        observation_metadata(command, message['receipt'], document, player, binding)
        if bytes.fromhex(message['receipt']['point']['fields']['party'])[0] == 1:
            from server.gen1_memorial_policy import terminal_retention

            retained = terminal_retention(stage, player, body['death_id'], message['receipt']['point'])
            entry.update(schema=RETAINED, observation_event=event, retention=retained)
            # No physical write, no false file receipt, no memorial completion.
            # The exact death blocker and pending rule obligation remain.
            synchronize(stage, document)
            return runtime.journal.commit(
                player, operation, message, expected_revision=stage.journal_revision,
                state=document, commands=commands, result={'ack': 'ACK'},
                acknowledgements=[{'player': player, 'command_id': message['command_id'],
                                   'outcome': 'ACK', 'receipt': message['receipt']}],
            ).result
        prepared = preparation(
            command,
            message["receipt"],
            document,
            player,
            binding,
            journal=runtime.journal,
        )
        from server.gen1_hud_feedback import pending_physical_ids

        if len(pending_physical_ids(runtime.journal, player)) > 1:
            # A queued faint will precede a newly appended apply. Read again
            # after it instead of preparing a poststate that it will invalidate.
            entry["observations"].append(event)
            commands[player].append(
                {"cmd": "memorial_observe", "death_id": body["death_id"], "key": body["key"]}
            )
        else:
            entry["payload"] = prepared
            entry["observation_event"] = event
            commands[player].append(
                {
                    "cmd": "memorialize",
                    "death_id": body["death_id"],
                    "key": body["key"],
                    "payload": wire_payload(prepared),
                }
            )
    elif body["cmd"] == "memorialize":
        if (
            entry["payload"] is None
            or body.get("payload") != wire_payload(entry["payload"])
            or entry["receipt_event"] is not None
        ):
            raise JournalError("memorial apply command differs from durable preparation")
        verify_receipt(
            command,
            message["receipt"],
            identity=stage.rules.player_identity[player],
            storage_policy=entry['payload'].get('storage_policy'),
            **{
                key: entry["payload"][key]
                for key in (
                    "before",
                    "context_generation",
                    "final_sha1",
                    "frame",
                    "reserved_digest",
                )
            },
        )
        if 'grave_head' in entry['payload']:
            from server.gen1_grave_reservations import advance
            records.append(advance(runtime.journal,document,player,operation,message,entry['payload']['after'],
                kind='memorial',target=entry['death_id'],previous=entry['payload']['grave_head'],revision=stage.journal_revision+1))
        entry["receipt_event"] = event
        complete = record_memorial_completion(stage.rules, player, body["key"])
        roster = inventory(entry["payload"]["after"], stage.rules.player_identity[player])
        party = [
            PartyCodec(entry["payload"]["after"]["variant"]).validate_blob(
                bytes.fromhex(mon["blob_hex"])
            )
            for mon in roster["members"]
            if mon["location"] == "party"
        ]
        stage.rules.party_size[player] = len(party)
        stage.rules.partner_blobs[player] = [
            {
                "slot": i,
                "key": mon.key,
                "species_id": mon.species_id,
                "level": mon.level,
                "blob": mon.raw,
            }
            for i, mon in enumerate(party)
        ]
        if complete:
            death["phase"] = "memorial_complete"
            blockers = stage.barrier.document()["blockers"]
            blockers.pop(body["death_id"])
            stage.barrier.set_blockers(blockers)
        entries=document['components'][COMPONENT]['entries'][player]
        reference,record=archive_entry(player,entry,stage.journal_revision+1)
        entries[entries.index(entry)]=reference;records.append(record)
        commands = schedule(document, event)
        from server.gen1_retirement_runtime import schedule as schedule_retirement
        extra, more = schedule_retirement(document,player,event)
        for p in ('a','b'):commands[p].extend(extra[p])
        records.extend(more)
    else:
        raise JournalError("unknown memorial command")
    synchronize(stage, document)
    return runtime.journal.commit(
        player,
        operation,
        message,
        expected_revision=stage.journal_revision,
        state=document,
        commands=commands,
        result={"ack": "ACK"},
        records=records,
        acknowledgements=[
            {
                "player": player,
                "command_id": message["command_id"],
                "outcome": "ACK",
                "receipt": message["receipt"],
            }
        ],
    ).result


def verify_operation(player, command, evidence, state, binding):
    if command["body"].get("cmd") != "memorialize":
        return None
    if (
        not isinstance(evidence, dict)
        or set(evidence)
        != {
            "schema",
            "command_id",
            "command_sequence",
            "context_generation",
            "final_sha1",
            "host",
            "checkpoint",
            "intent",
            "current",
            "phase",
        }
        or evidence["schema"] != EVIDENCE
    ):
        raise JournalError("complete held memorial evidence required")
    verify_owned_checkpoint(player, command, evidence, state, binding)
    entry = entry_for(state, player, command["body"].get("death_id"))
    payload = entry.get("payload")
    if (
        payload is None
        or is_complete(entry)
        or command["body"].get("payload") != wire_payload(payload)
        or evidence["intent"]
        != {"schema": "rby-memorial-intent-v1", "body_digest": digest(command["body"])}
        or evidence["phase"] not in ("memorialize", "memorial_save", "memorial_repair")
    ):
        raise JournalError("held memorial differs from its prepared command/poststate")
    current = evidence["current"]
    if evidence["phase"] == "memorial_repair":
        recover_point(current, wire_payload(payload))
    elif current != payload["after" if evidence["phase"] == "memorial_save" else "before"]:
        raise JournalError("memorial phase differs from current physical state")
    return VerifiedHeldWrite(
        command_scope(command, binding, phase=evidence["phase"]),
        digest(evidence),
        1000,
        digest(state),
    )


def recover_point(current, payload):
    from server.gen1_save_delta import recover_point as recover_delta

    return recover_delta(current, payload)


def verify_state(stage):
    document = stage.document()
    component = document["components"].get(COMPONENT)
    if component is None:
        return
    if (
        not isinstance(component, dict)
        or set(component) != {"entries"}
        or set(component["entries"]) != {"a", "b"}
    ):
        raise JournalError("invalid memorial component")
    for player, entries in component["entries"].items():
        if not isinstance(entries, list):
            raise JournalError("ordered memorial entries required")
        seen = set()
        for index, entry in enumerate(entries):
            if not isinstance(entry,dict):raise JournalError('memorial entry must be an object')
            if entry.get('schema') == RETAINED:
                from server.gen1_memorial_policy import terminal_retention

                if set(entry) != {'schema','death_id','origin','observations','observation_event','payload','receipt_event','retention'}:
                    raise JournalError('complete retained terminal memorial evidence required')
                _identifier(entry['death_id'])
                observed = entry['observation_event']
                if (not isinstance(entry['observations'], list) or not isinstance(observed, dict)
                        or not isinstance(observed.get('message'), dict)
                        or not isinstance(observed['message'].get('receipt'), dict)
                        or not isinstance(observed['message']['receipt'].get('point'), dict)):
                    raise JournalError('terminal retention requires its complete owned read point')
                if entry['payload'] is not None or entry['receipt_event'] is not None or entry['observation_event'] is None:
                    raise JournalError('terminal retention cannot assert a deposit or saved receipt')
                if entry['death_id'] in seen or index != len(entries)-1:
                    raise JournalError('terminal retention must end the player memorial queue')
                if terminal_retention(stage, player, entry['death_id'], entry['observation_event']['message']['receipt']['point']) != entry['retention']:
                    raise JournalError('terminal retention differs from exact fainted disposition')
                seen.add(entry['death_id'])
                continue
            if entry.get('schema')==COMPLETED:
                if set(entry)!={'schema','death_id','record_key','record_revision','record_digest','reservation_digest'}:
                    raise JournalError('complete archived memorial reference required')
                _identifier(entry['death_id']);_identifier(entry['record_key'])
                for key in ('record_digest','reservation_digest'):
                    if not isinstance(entry[key],str) or not re.fullmatch('[0-9a-f]{64}',entry[key]):
                        raise JournalError('archived memorial digest required')
                if type(entry['record_revision']) is not int or entry['record_revision']<1:
                    raise JournalError('archived memorial revision required')
                expected_key=digest({'component':COMPONENT,'player':player,'death_id':entry['death_id']})[:32]
                death=document['components'][FAINT]['deaths'].get(entry['death_id'])
                if (entry['record_key']!=expected_key or death is None or entry['death_id'] in seen
                        or key_for(death,player) in stage.rules.pending_memorials[player]
                        or index and not is_complete(entries[index-1])):
                    raise JournalError('archived memorial differs from its completed obligation')
                seen.add(entry['death_id'])
                link=stage.rules.find_link(player,key_for(death,player))
                count=stage.rules.document()['memorial']['retired_pairs'].count(stage.rules._memorial_record(link))
                if count!=(1 if death['phase']=='memorial_complete' else 0):
                    raise JournalError('archived memorial history differs')
                continue
            if set(entry) != {
                "death_id",
                "origin",
                "observation_event",
                "observations",
                "payload",
                "receipt_event",
            }:
                raise JournalError("incomplete memorial obligation")
            if not isinstance(entry["observations"], list):
                raise JournalError("ordered memorial observations required")
            for event in [
                entry["origin"],
                *entry["observations"],
                entry["observation_event"],
                entry["receipt_event"],
            ]:
                if event is None:
                    continue
                if (
                    not isinstance(event, dict)
                    or set(event) != {"player", "operation_id", "message"}
                    or event["player"] not in ("a", "b")
                ):
                    raise JournalError("complete memorial journal event required")
                _identifier(event["operation_id"])
                message = event["message"]
                if (
                    not isinstance(message, dict)
                    or set(message)
                    != {"event", "command_id", "command_sequence", "outcome", "receipt"}
                    or message["event"] != "command_ack"
                    or message["outcome"] != "ACK"
                    or not isinstance(message["receipt"], dict)
                    or type(message["command_sequence"]) is not int
                    or message["command_sequence"] < 1
                ):
                    raise JournalError("typed memorial source acknowledgement required")
                _identifier(message["command_id"])
            _identifier(entry["origin"]["operation_id"])
            _identifier(entry["death_id"])
            death = document["components"][FAINT]["deaths"].get(entry["death_id"])
            if (
                death is None
                or entry["death_id"] in seen
                or index < len(entries) - 1
                and entry["receipt_event"] is None
            ):
                raise JournalError("memorial serialization/death history differs")
            seen.add(entry["death_id"])
            link = stage.rules.find_link(player, key_for(death, player))
            count = stage.rules.document()["memorial"]["retired_pairs"].count(
                stage.rules._memorial_record(link)
            )
            if count != (1 if death["phase"] == "memorial_complete" else 0):
                raise JournalError("memorial history differs from paired receipt completion")
            done = entry["receipt_event"] is not None
            if (key_for(death, player) not in stage.rules.pending_memorials[player]) != done:
                raise JournalError("memorial receipt differs from rule obligation")
            if (
                (entry["observation_event"] is None) != (entry["payload"] is None)
                or done
                and entry["payload"] is None
            ):
                raise JournalError("memorial phase lacks preparation")
            if entry["payload"] is not None:
                p = entry["payload"]
                reserved = previous_reservation(document, player, entry)
                if (
                    set(p) not in ({
                        "before",
                        "after",
                        "reserved_digest",
                        "context_generation",
                        "final_sha1",
                        "frame",
                    }, {
                        "before", "after", "reserved_digest", "context_generation",
                        "final_sha1", "frame", "storage_policy",
                    }, {
                        "before", "after", "reserved_digest", "context_generation",
                        "final_sha1", "frame", "storage_policy", "grave_head", "source_anchor",
                    })
                    or p["reserved_digest"] != reserved
                ):
                    raise JournalError("memorial reservation chain differs")
                if p["after"] != expected(
                    p["before"],
                    key_for(death, player),
                    identity=stage.rules.player_identity[player],
                    reserved_digest=reserved,
                    storage_policy=p.get('storage_policy'),
                ):
                    raise JournalError("memorial prepared image differs")


def verify_retained(journal, stage, player, entry):
    """Bind terminal physical disposition to the exact read-command lineage."""
    document = stage.document()
    death = document['components'][FAINT]['deaths'][entry['death_id']]
    current = None
    for origin in [entry['origin'], *entry['observations']]:
        if not isinstance(origin, dict) or set(origin) != {'player','operation_id','message'}:
            raise JournalError('terminal memorial lacks a typed issuing event')
        event = journal.event(origin['player'], origin['operation_id'], origin['message'])
        if event is None or event.result != {'ack':'ACK'}:
            raise JournalError('terminal memorial has lost its issuing event')
        if current is not None:
            message = origin['message']
            if (message.get('command_id') != current['command_id'] or current['outcome'] != 'ACK'
                    or current['receipt'] != message.get('receipt')):
                raise JournalError('terminal memorial has lost a renewed read receipt')
        matches = []
        for identifier in event.command_ids:
            try:
                candidate = journal.command(player, identifier)
            except JournalError:
                continue
            if candidate['body'] == {'cmd':'memorial_observe','death_id':entry['death_id'],'key':key_for(death,player)}:
                matches.append(candidate)
        if len(matches) != 1:
            raise JournalError('terminal memorial needs its exact issued read command')
        current = matches[0]
    observed = entry['observation_event']
    if not isinstance(observed, dict) or set(observed) != {'player','operation_id','message'} or observed['player'] != player:
        raise JournalError('terminal memorial needs its owned observation event')
    message = observed['message']
    if (not isinstance(message, dict) or set(message) != {'event','command_id','command_sequence','outcome','receipt'}
            or message['event'] != 'command_ack' or message['outcome'] != 'ACK'
            or current is None or current['command_id'] != message['command_id']
            or type(message['command_sequence']) is not int or current['command_sequence'] != message['command_sequence']
            or current['outcome'] != 'ACK' or current['receipt'] != message['receipt']):
        raise JournalError('terminal disposition differs from its read acknowledgement')
    event = journal.event(player, observed['operation_id'], message)
    if event is None or event.result != {'ack':'ACK'} or event.command_ids:
        raise JournalError('terminal disposition cannot issue physical write commands')
    initial = document['components']['gen1-initial-observations'][player]
    observation_metadata(current, message['receipt'], document, player, initial['binding'], historical=True)


def verify_journal(journal, stage, cache=None):
    document = stage.document()
    component = document["components"].get(COMPONENT)
    if component is None:
        return
    from server.gen1_grave_reservations import verify_journal as verify_graves
    verify_graves(journal,document)
    for player, entries in component["entries"].items():
        for index, reference in enumerate(entries):
            entry=expand_entry(journal,reference)
            if entry.get('schema') == RETAINED:
                verify_retained(journal, stage, player, entry)
                continue
            cache_key=None
            if reference.get('schema')==COMPLETED:
                previous=entries[index-1] if index else None
                anchor=(previous.get('record_digest') or digest(previous)) if previous else document['components']['gen1-initial-observations'][player]['inventory']['source_digest']
                initial=document['components']['gen1-initial-observations'][player]
                context=digest({'binding':initial['binding'],'host':initial['observation']['host'],'frame':initial['observation']['frame']})
                cache_key=(player,reference['record_key'],reference['record_digest'],anchor,context)
            trusted=cache is not None and cache_key is not None and cache_key in cache
            issued = {}
            for origin, kind in [
                (entry["origin"], "memorial_observe"),
                *((event, "memorial_observe") for event in entry["observations"]),
                (entry["observation_event"], "memorialize"),
            ]:
                if origin is None:
                    continue
                event = journal.event(origin["player"], origin["operation_id"], origin["message"])
                if event is None or event.result!={'ack':'ACK'}:
                    raise JournalError("memorial obligation lacks its issuing event")
                matches = []
                for identifier in event.command_ids:
                    try:
                        command = journal.command(player, identifier)
                    except JournalError:
                        continue
                    if (
                        command["body"].get("death_id") == entry["death_id"]
                        and command["body"].get("cmd") == kind
                    ):
                        matches.append(command)
                death = document["components"][FAINT]["deaths"][entry["death_id"]]
                if len(matches) != 1 or matches[0]["body"].get("key") != key_for(death, player):
                    raise JournalError("memorial lacks its exact issued physical command")
                if kind == "memorialize" and matches[0]["body"].get("payload") != wire_payload(
                    entry["payload"]
                ):
                    raise JournalError("issued memorial differs from prepared image")
                if origin in entry["observations"]:
                    prior_command = journal.command(player, origin["message"]["command_id"])
                    if (
                        prior_command["command_id"] != issued.get("memorial_observe")
                        or prior_command["outcome"] != "ACK"
                        or prior_command["receipt"] != origin["message"]["receipt"]
                    ):
                        raise JournalError(
                            "renewed memorial observation lacks its prior exact read receipt"
                        )
                    initial = document["components"]["gen1-initial-observations"][player]
                    if not trusted:
                        preparation(prior_command,origin["message"]["receipt"],document,player,
                            initial["binding"],historical=True,journal=journal)
                issued[kind] = matches[0]["command_id"]
            for field, kind in (
                ("observation_event", "memorial_observe"),
                ("receipt_event", "memorialize"),
            ):
                event = entry[field]
                if event is None:
                    continue
                message = event["message"]
                command = journal.command(player, message["command_id"])
                committed = journal.event(player, event["operation_id"], message)
                if (
                    event["player"] != player
                    or message["command_id"] != issued[kind]
                    or committed is None
                    or committed.result!={'ack':'ACK'}
                    or command["outcome"] != "ACK"
                    or command["receipt"] != message["receipt"]
                    or command["body"]["cmd"] != kind
                    or command["body"]["death_id"] != entry["death_id"]
                ):
                    raise JournalError("memorial evidence lacks its exact journal command/event")
                if trusted:
                    continue
                if kind == "memorial_observe":
                    initial = document["components"]["gen1-initial-observations"][player]
                    if 'grave_head' in entry['payload']:
                        from server.gen1_grave_reservations import before_preparation
                        before_preparation(journal,entry['payload']['grave_head'],entry['payload']['source_anchor'],committed.revision)
                    if (
                        preparation(
                            command,
                            message["receipt"],
                            document,
                            player,
                            initial["binding"],
                            historical=True,
                            journal=journal,
                        )
                        != entry["payload"]
                    ):
                        raise JournalError("memorial journal preparation differs")
                else:
                    verify_receipt(
                        command,
                        message["receipt"],
                        identity=stage.rules.player_identity[player],
                        storage_policy=entry['payload'].get('storage_policy'),
                        **{
                            key: entry["payload"][key]
                            for key in (
                                "before",
                                "context_generation",
                                "final_sha1",
                                "frame",
                                "reserved_digest",
                            )
                        },
                    )
            if cache_key is not None and cache is not None:
                if len(cache)>=256:cache.clear()
                cache.add(cache_key)
