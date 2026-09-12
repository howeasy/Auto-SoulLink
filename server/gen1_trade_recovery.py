"""RBY trade obligations composed into the same journal commit as each phase."""

from __future__ import annotations

import copy

from server.paired_recovery import RecoveryBarrier, _hex
from server.protocol_journal import JournalError, _encode
from server.trade_coordinator import COMMANDS, NAMESPACE, PHASES, TERMINAL

COMPONENT = "gen1-trade"
SCHEMA = "slink-gen1-trade-recovery-v1"
REASON = "RBY native trade awaiting verified closure"


def transactions(document):
    component = document["components"].get(COMPONENT)
    if component is None:
        if document["active_trade"] is not None:
            raise JournalError("active RBY trade lacks atomic recovery composition")
        return {}
    if (
        not isinstance(component, dict)
        or set(component) != {"schema", "transactions"}
        or component["schema"] != SCHEMA
        or not isinstance(component["transactions"], dict)
        or len(component["transactions"]) > 1
    ):
        raise JournalError("invalid RBY trade recovery component")
    entries = component["transactions"]
    for identifier, entry in entries.items():
        _hex(identifier, 32, "trade obligation")
        if (
            not isinstance(entry, dict)
            or set(entry) != {"phase", "record_digest", "pending"}
            or entry["phase"] not in PHASES
            or not isinstance(entry["pending"], dict)
            or set(entry["pending"]) != {"a", "b"}
        ):
            raise JournalError("invalid RBY trade obligation")
        _hex(entry["record_digest"], 64, "trade record")
        for batch in entry["pending"].values():
            if (
                not isinstance(batch, list)
                or any(not isinstance(name, str) or name not in COMMANDS for name in batch)
                or batch != sorted(set(batch))
            ):
                raise JournalError("invalid RBY pending trade commands")
        if entry["phase"] not in TERMINAL and document["active_trade"] != identifier:
            raise JournalError("RBY trade obligation differs from active transaction")
        if entry["phase"] in TERMINAL and document["active_trade"] is not None:
            raise JournalError("prior RBY trade closure must finish before another offer")
    if document["active_trade"] is not None and document["active_trade"] not in entries:
        raise JournalError("active RBY trade lacks atomic recovery composition")
    return entries


def blockers(document):
    # An offer owns no party: the partner may still leave a battle to reach the
    # native prompt after ordinary paired reconciliation. Acceptance owns both
    # parties. Terminal status alone does not prove native UI/lease closure.
    return {
        identifier: REASON
        for identifier, entry in transactions(document).items()
        if entry["phase"] != "offered"
    }


def pending_commands(journal, identifier, commands=None, acknowledgements=()):
    retired = {(row["player"], row["command_id"]) for row in acknowledgements}
    pending = {"a": [], "b": []}
    for player in pending:
        for command_id in journal.pending_ids(player):
            body = journal.command(player, command_id)["body"]
            if body.get("transaction_id") == identifier and (player, command_id) not in retired:
                if body.get("cmd") not in COMMANDS:
                    raise JournalError("unexpected command owns an RBY trade transaction")
                pending[player].append(body["cmd"])
        pending[player].extend(
            row["cmd"]
            for row in (commands or {}).get(player, [])
            if row.get("transaction_id") == identifier
        )
        pending[player] = sorted(set(pending[player]))
    return pending


def compose(journal, state, trade, commands, acknowledgements, *, data_dir,state_type=None, native=None):
    # No writes here. Journal CAS makes these reads and the detached projection
    # conditional on the coordinator's original revision at the single commit.
    from server.gen1_runtime_state import COMPONENT as RUNTIME, Gen1RuntimeState, recovery_history

    components = state["components"]
    if native is not None:
        # The native policy's verified ready evidence rides this same commit (durable both-peer
        # preparation); it is dropped once the transaction is terminal with nothing pending.
        from server.gen1_native_preparation import retain

        retain(components, trade, acknowledgements, native,
               pending=pending_commands(journal, trade["id"], commands, acknowledgements))
    previous = copy.deepcopy(components.get(COMPONENT, {"schema": SCHEMA, "transactions": {}}))
    entries = previous["transactions"]
    pending = pending_commands(journal, trade["id"], commands, acknowledgements)
    if trade["phase"] in TERMINAL and not any(pending.values()):
        entries.pop(trade["id"], None)
    else:
        entries[trade["id"]] = {
            "phase": trade["phase"],
            "record_digest": _encode(trade)[1],
            "pending": pending,
        }
    components[COMPONENT] = previous
    barrier = RecoveryBarrier.restore(components[RUNTIME]["recovery"])
    obligations = {
        key: reason for key, reason in barrier.document()["blockers"].items() if reason != REASON
    }
    obligations.update(blockers(state))
    barrier.set_blockers(obligations)
    barrier.set_history(
        recovery_history(state["rules"], state["identities"], state["active_trade"], previous)
    )
    components[RUNTIME]["recovery"] = barrier.document()
    (state_type or Gen1RuntimeState).restore(state, data_dir=data_dir)
    return components


def verify_journal(journal, document):
    for identifier, entry in transactions(document).items():
        record = journal.record(NAMESPACE, identifier)
        if (
            record is None
            or _encode(record.value)[1] != entry["record_digest"]
            or record.value["phase"] != entry["phase"]
            or pending_commands(journal, identifier) != entry["pending"]
        ):
            raise JournalError("RBY trade recovery differs from its committed record/outboxes")
