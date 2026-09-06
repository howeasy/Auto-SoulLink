"""Detached paired-recovery state for inclusion in the coordinator's journal commit.

No transport, clock, cartridge reads or effects occur here. A resume ticket is a
description, not a credential: session ownership and fresh paired liveness must
still be checked at delivery. Physical bindings construct VerifiedReconciliation
only after replay, physical obligations and rollback evidence have been checked.
"""
from __future__ import annotations

import copy
import re
import secrets
from dataclasses import asdict, dataclass

from server.protocol import digest
from server.protocol_journal import JournalError, _encode

SCHEMA = "slink-paired-recovery-v1"
PLAYERS = ("a", "b")


def _hex(value, size, name):
    if not isinstance(value, str) or not re.fullmatch(rf"[0-9a-f]{{{size}}}", value):
        raise JournalError(f"invalid recovery {name}")
    return value


def _reason(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 256 or not value.isprintable():
        raise JournalError("recovery needs an explicit bounded reason")
    return value


def _player(player):
    if player not in PLAYERS:
        raise JournalError("invalid recovery player")


@dataclass(frozen=True)
class VerifiedReconciliation:
    """Trusted binding result, never directly constructed from an unvalidated JSON claim.

    checkpoint_digest identifies observed live-memory evidence. It does not mean
    that a battery save exists; save/checkpoint persistence belongs in that evidence.
    """

    player: str
    epoch: str
    binding_digest: str
    context_generation: str
    history_digest: str
    checkpoint_digest: str

    def __post_init__(self):
        _player(self.player)
        for name in ("epoch", "context_generation"):
            _hex(getattr(self, name), 32, name)
        for name in ("binding_digest", "history_digest", "checkpoint_digest"):
            _hex(getattr(self, name), 64, name)


class RecoveryBarrier:
    """Mutate only a staged instance; publish document() with rules and both outboxes.

    The history digest covers semantic rules/transactions, excluding this recovery
    document and transient telemetry. Changing it, either binding, or any blocking
    obligation invalidates BOTH reconciliation proofs. Same-value updates are inert.
    """

    def __init__(self, history_digest, *, new_epoch=None):
        self._new_epoch = new_epoch or (lambda: secrets.token_hex(16))
        self._state = {
            "schema": SCHEMA, "epoch": self._epoch(),
            "history_digest": _hex(history_digest, 64, "history digest"),
            "bindings": dict.fromkeys(PLAYERS), "proofs": dict.fromkeys(PLAYERS),
            "blockers": {}, "reason": "waiting for paired admission and reconciliation",
        }

    def _epoch(self):
        return _hex(self._new_epoch(), 32, "epoch")

    def document(self):
        return copy.deepcopy(self._state)

    @classmethod
    def restore(cls, document, *, new_epoch=None):
        _encode(document)
        expected = {"schema", "epoch", "history_digest", "bindings", "proofs", "blockers", "reason"}
        if set(document) != expected or document["schema"] != SCHEMA:
            raise JournalError("unsupported recovery document")
        _hex(document["epoch"], 32, "epoch")
        _hex(document["history_digest"], 64, "history digest")
        _reason(document["reason"])
        for field in ("bindings", "proofs"):
            if not isinstance(document[field], dict) or set(document[field]) != set(PLAYERS):
                raise JournalError(f"incomplete recovery {field}")
        if document["bindings"]["a"] is not None and document["bindings"]["a"] == document["bindings"]["b"]:
            raise JournalError("paired recovery requires distinct player and physical-instance bindings")
        cls._validate_blockers(document["blockers"])
        obj = cls.__new__(cls)
        obj._new_epoch = new_epoch or (lambda: secrets.token_hex(16))
        obj._state = copy.deepcopy(document)
        for player, binding in document["bindings"].items():
            if binding is not None:
                cls._validate_binding(binding)
            proof = document["proofs"][player]
            if proof is not None:
                if not isinstance(proof, dict) or set(proof) != set(VerifiedReconciliation.__dataclass_fields__):
                    raise JournalError("invalid persisted reconciliation proof")
                obj._check_proof(player, VerifiedReconciliation(**proof))
        return obj

    @staticmethod
    def _validate_binding(binding):
        if not isinstance(binding, dict) or set(binding) != {"binding_digest", "context_generation"}:
            raise JournalError("invalid recovery binding")
        _hex(binding["binding_digest"], 64, "binding digest")
        _hex(binding["context_generation"], 32, "context generation")

    @staticmethod
    def _validate_blockers(blockers):
        if not isinstance(blockers, dict) or len(blockers) > 4096:
            raise JournalError("invalid recovery obligations")
        for identifier, reason in blockers.items():
            _hex(identifier, 32, "obligation identifier")
            _reason(reason)

    def invalidate(self, reason):
        reason = _reason(reason)
        epoch = self._epoch()
        if epoch == self._state["epoch"]:
            raise JournalError("recovery epoch source repeated its current value")
        self._state.update(epoch=epoch, proofs=dict.fromkeys(PLAYERS), reason=reason)

    def bind(self, player, binding_digest, context_generation):
        _player(player)
        binding = {"binding_digest": binding_digest, "context_generation": context_generation}
        self._validate_binding(binding)
        peer = "b" if player == "a" else "a"
        if self._state["bindings"][peer] == binding:
            raise JournalError("paired recovery requires distinct player and physical-instance bindings")
        if self._state["bindings"][player] == binding:
            return False
        self.invalidate(f"player {player} binding or context changed")
        self._state["bindings"][player] = binding
        return True

    def set_history(self, history_digest):
        history_digest = _hex(history_digest, 64, "history digest")
        if history_digest == self._state["history_digest"]:
            return False
        self.invalidate("committed semantic history changed; paired reconciliation required")
        self._state["history_digest"] = history_digest
        return True

    def set_blockers(self, blockers):
        self._validate_blockers(blockers)
        if blockers == self._state["blockers"]:
            return False
        self.invalidate("pending obligations changed; paired reconciliation required")
        self._state["blockers"] = copy.deepcopy(blockers)
        return True

    def _check_proof(self, player, proof):
        _player(player)
        if not isinstance(proof, VerifiedReconciliation):
            raise JournalError("reconciliation requires trusted binding evidence")
        if proof.player != player:
            raise JournalError("reconciliation proof belongs to the other player")
        if self._state["blockers"]:
            raise JournalError("pending obligations prohibit ordinary gameplay reconciliation")
        binding = self._state["bindings"][player]
        if binding is None or any(getattr(proof, name) != value for name, value in binding.items()):
            raise JournalError("reconciliation proof differs from the admitted context")
        if proof.epoch != self._state["epoch"] or proof.history_digest != self._state["history_digest"]:
            raise JournalError("reconciliation proof refers to stale history or recovery epoch")

    def reconcile(self, player, proof):
        self._check_proof(player, proof)
        value = asdict(proof)
        old = self._state["proofs"][player]
        if old is not None and old != value:
            # Physical evidence changed without a context/history transition.
            # The binding must invalidate first, not silently replace one half.
            raise JournalError("conflicting reconciliation evidence; invalidate the pair first")
        self._state["proofs"][player] = value
        if all(self._state["proofs"].values()):
            self._state["reason"] = "paired reconciliation complete; fresh session liveness still required"

    def ticket(self):
        if self._state["blockers"] or not all(self._state["proofs"].values()):
            return None
        body = {name: copy.deepcopy(self._state[name])
                for name in ("epoch", "history_digest", "bindings", "proofs")}
        return {"schema": "slink-resume-ticket-v1", **body, "digest": digest(body)}

    def status(self):
        """Detached lifecycle facts for the UI's additive projection adapter."""
        return {"epoch": self._state["epoch"], "reason": self._state["reason"],
                "paired_reconciled": self.ticket() is not None,
                "pending_obligations": copy.deepcopy(self._state["blockers"]),
                "players": {p: {"admitted_binding": self._state["bindings"][p] is not None,
                                "reconciled": self._state["proofs"][p] is not None}
                            for p in PLAYERS}}
