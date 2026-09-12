"""Durable both-peer native preparation: the verified ready evidence, in the trade's own commit.

`NativeTradePolicy.ready` verifies a player's ``rby-saved-ready-v1`` receipt (the read-only
trade checkpoint, the full original save point, the closed partner prompt) and the
coordinator journals only the derived ``PreparedTrade`` (digests, boxed keys). The full
checkpoint the COMMIT windows and the verified-file check need lived in the policy's
in-memory cache, so a reopen between ready and finalize had "no cache and requires
recovery" with nothing to recover from.

This component retains what `ready` verified, per transaction and player, written by the
trade composition hook in the same commit as the ``trade_ready`` acknowledgement, and
dropped when the transaction reaches a terminal phase with nothing pending. It is evidence
of preparation only: it never authorizes a window and never stands in for a receipt.
"""

import copy

from server.protocol import digest
from server.protocol_journal import JournalError, _identifier
from server.trade_coordinator import NAMESPACE, TERMINAL

COMPONENT = "gen1-native-preparation"
ENTRY = frozenset({"command_id", "checkpoint_digest", "checkpoint", "save", "prompt"})


def retain(components, trade, acknowledgements, policy, *, pending=None):
    """Detached update of ``components`` for one coordinator commit.

    ``policy`` is the trade policy in force. A policy that carries a preparation cache
    (``prepared``: NativeTradePolicy) is bound by it: every trade_ready acknowledgement being
    committed must have its exact verified stages in that cache, else this raises BEFORE the
    journal commit, so both_prepared can never persist without durable full stages. A policy
    without a cache (no native preparation) retains nothing. Evidence is dropped only once the
    transaction is terminal AND no native command of it is still pending (``pending`` is the
    per-player pending map gen1_trade_recovery computes for the same commit).
    """
    if not hasattr(policy, "prepared"):
        return components
    cache = policy.prepared
    transactions = components.get(COMPONENT, {})
    if trade["phase"] in TERMINAL and not any((pending or {}).values()):
        transactions.pop(trade["id"], None)
        if not transactions:
            components.pop(COMPONENT, None)
        return components
    for row in acknowledgements:
        player = row["player"]
        ready = trade["ready"].get(player)
        if row["outcome"] != "ACK" or ready is None or row["receipt"] != ready:
            continue
        if not isinstance(cache, dict) or cache.get("transaction_id") != trade["id"]:
            raise JournalError("native preparation cache is missing for the ready being acknowledged")
        stage = cache.get("players", {}).get(player)
        if not isinstance(stage, dict) or "checkpoint" not in stage:
            raise JournalError("native preparation stages are missing for the ready being acknowledged")
        checkpoint = stage["checkpoint"]
        expected = ready["details"]["checkpoint_digest"]
        if digest(checkpoint) != expected:
            raise JournalError("native preparation cache differs from the acknowledged proof")
        entry = {
            "command_id": row["command_id"],
            "checkpoint_digest": expected,
            "checkpoint": copy.deepcopy(checkpoint),
            "save": copy.deepcopy(stage.get("save")),
            "prompt": copy.deepcopy(stage.get("prompt")),
        }
        transactions = components.setdefault(COMPONENT, transactions)
        previous = transactions.setdefault(trade["id"], {}).get(player)
        if previous is not None and previous != entry:
            raise JournalError("conflicting native preparation evidence for one player")
        transactions[trade["id"]][player] = entry
    return components


def stored(document, transaction_id, player):
    """The retained preparation for a player of a transaction, or None (detached)."""
    entry = document["components"].get(COMPONENT, {}).get(transaction_id, {}).get(player)
    return copy.deepcopy(entry) if entry is not None else None


def verify_state(stage):
    transactions = stage.document()["components"].get(COMPONENT, {})
    if not isinstance(transactions, dict):
        raise JournalError("invalid native preparation component")
    for transaction_id, players in transactions.items():
        _identifier(transaction_id)
        if not isinstance(players, dict) or set(players) - {"a", "b"}:
            raise JournalError("native preparation must be keyed by player")
        for entry in players.values():
            if not isinstance(entry, dict) or set(entry) != ENTRY:
                raise JournalError("complete native preparation entry required")
            _identifier(entry["command_id"])
            if digest(entry["checkpoint"]) != entry["checkpoint_digest"]:
                raise JournalError("native preparation checkpoint differs from its digest")


def verify_journal(journal, stage):
    verify_state(stage)
    for transaction_id, players in stage.document()["components"].get(COMPONENT, {}).items():
        record = journal.record(NAMESPACE, transaction_id)
        if record is None:
            raise JournalError("native preparation names a transaction the journal never persisted")
        trade = record.value
        if trade["phase"] in TERMINAL and not any(
                journal.command(p, identifier)["body"].get("transaction_id") == transaction_id
                for p in ("a", "b") for identifier in journal.pending_ids(p)):
            raise JournalError("native preparation retained past a terminal trade with nothing pending")
        for player, entry in players.items():
            ready = trade["ready"].get(player)
            if ready is None or ready["details"]["checkpoint_digest"] != entry["checkpoint_digest"]:
                raise JournalError("native preparation differs from the acknowledged prepared proof")
            command = journal.command(player, entry["command_id"])
            if command["body"].get("cmd") != "native_trade_prepare" or command["outcome"] != "ACK" or command["receipt"] != ready:
                raise JournalError("native preparation names a command that did not acknowledge it")
