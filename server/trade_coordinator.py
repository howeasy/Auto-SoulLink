"""Generation-neutral, journal-backed paired trade coordination.

Cartridge/host policy callbacks validate admission, readiness, native execution,
save durability and recovery authority. This module never reads/writes a game,
sends a packet, grants frames, or accepts raw success booleans as physical proof.
All callbacks operate on detached values and must be free of external effects.
"""
from __future__ import annotations

import copy
import json
import secrets
import time
from dataclasses import asdict, dataclass

from server.identity_registry import (
    IdentityContext,
    IdentityRegistry,
    IdentityWitness,
    MigrationWitness,
)
from server.paired_recovery import _hex, _player
from server.protocol_journal import JournalError, ProtocolJournal, RevisionConflict, _encode
from server.save_identity import SaveIdentity

SCHEMA = "slink-coordinated-state-v1"
TRADE_SCHEMA = "slink-paired-trade-v1"
NAMESPACE = "paired-trade"
PLAYERS = ("a", "b")
TERMINAL = {"cancelled", "declined", "expired", "link_committed"}
COMMITTED = {"commit_persisted", "commit_dispatched", "both_applied", "both_verified", "link_committed"}
PHASES = TERMINAL | COMMITTED | {"offered", "accepted", "preparing", "both_prepared"}
COMMANDS = {"native_trade_prompt", "native_trade_prepare", "native_trade_commit",
            "native_trade_abort", "native_trade_release"}


def _clone(value):
    return json.loads(_encode(value)[0])


def _proof(value):
    if not isinstance(value, dict) or not isinstance(value.get("schema"), str) or not value["schema"]:
        raise JournalError("versioned, independently validated evidence required")
    return _clone(value)


def _context(document):
    value = copy.deepcopy(document)
    value["save_identity"] = SaveIdentity(**value["save_identity"])
    return IdentityContext(**value)


def _migration(document):
    value = copy.deepcopy(document)
    value["source_context"] = _context(value["source_context"])
    value["after"]["context"] = _context(value["after"]["context"])
    value["after"] = IdentityWitness(**value["after"])
    return MigrationWitness(**value)


@dataclass(frozen=True)
class TradeParticipant:
    context: IdentityContext
    member_id: str
    key: str
    slot: int
    evidence_digest: str
    snapshot: dict

    def __post_init__(self):
        if not isinstance(self.context, IdentityContext):
            raise JournalError("validated participant context required")
        _hex(self.member_id, 32, "member")
        _hex(self.evidence_digest, 64, "selected physical evidence")
        if not isinstance(self.key, str) or not 1 <= len(self.key) <= 256:
            raise JournalError("selected physical key required")
        if type(self.slot) is not int or not 0 <= self.slot < 6:
            raise JournalError("selected party slot required")
        _proof(self.snapshot)


@dataclass(frozen=True)
class TradeProposal:
    link_id: str
    a: TradeParticipant
    b: TradeParticipant

    def __post_init__(self):
        _hex(self.link_id, 32, "link")
        if not isinstance(self.a, TradeParticipant) or not isinstance(self.b, TradeParticipant):
            raise JournalError("both validated trade participants required")
        if self.a.context.player != "a" or self.b.context.player != "b":
            raise JournalError("trade participants have the wrong player scope")
        if self.a.context.physical_instance == self.b.context.physical_instance or self.a.member_id == self.b.member_id:
            raise JournalError("trade needs two distinct physical participants and logical members")

    def document(self):
        return _clone({"link_id": self.link_id, "participants": {"a": asdict(self.a), "b": asdict(self.b)}})


@dataclass(frozen=True)
class PreparedTrade:
    proposal_digest: str
    context_generation: str
    evidence_digest: str
    details: dict

    def __post_init__(self):
        _hex(self.proposal_digest, 64, "proposal")
        _hex(self.context_generation, 32, "prepared context")
        _hex(self.evidence_digest, 64, "prepared physical evidence")
        _proof(self.details)


@dataclass(frozen=True)
class TradeVerification:
    migration: MigrationWitness
    native_receipt: dict
    save_receipt: dict

    def __post_init__(self):
        if not isinstance(self.migration, MigrationWitness):
            raise JournalError("verified ownership migration required")
        _proof(self.native_receipt)
        _proof(self.save_receipt)


class TradeCoordinator:
    REQUIRED_POLICY = ("authorize", "offer", "prompt", "decision", "prepare", "ready",
                       "commit", "applied", "verified", "auxiliary", "finalize")

    def __init__(self, journal: ProtocolJournal, policy, *, clock=None, new_id=None, compose_components=None):
        if any(not callable(getattr(policy, name, None)) for name in self.REQUIRED_POLICY):
            raise JournalError("complete trade validation policy required")
        self.journal, self.policy = journal, policy
        self.clock = clock or (lambda: time.time_ns() // 1_000_000)
        self.new_id = new_id or (lambda: secrets.token_hex(16))
        if compose_components is not None and not callable(compose_components):
            raise JournalError("trade component composition must be callable")
        self.compose_components = compose_components

    @staticmethod
    def initial_state(rules, identities, *, components=None):
        """Explicit new aggregate; never bootstrap from raw HELLO observations."""
        return _clone({"schema": SCHEMA, "rules": rules, "identities": identities,
                       "active_trade": None, "components": components or {}})

    def _load(self, transaction_id=None):
        snapshot = self.journal.snapshot()
        state = snapshot.state
        if (set(state) != {"schema", "rules", "identities", "active_trade", "components"}
                or state["schema"] != SCHEMA or not isinstance(state["rules"], dict)
                or not isinstance(state["components"], dict)):
            raise JournalError("coordinated runtime aggregate required")
        registry = IdentityRegistry.restore(state["identities"], run_id=self.journal.run_id)
        if state["active_trade"] is not None:
            _hex(state["active_trade"], 32, "active trade")
        trade = None
        if transaction_id is not None:
            _hex(transaction_id, 32, "transaction")
            record = self.journal.record(NAMESPACE, transaction_id)
            if record is None:
                raise JournalError("unknown trade transaction")
            if record.revision > snapshot.revision:
                raise RevisionConflict("trade changed while reading its state; reload")
            trade = record.value
            if (trade.get("schema") != TRADE_SCHEMA or trade.get("id") != transaction_id
                    or trade.get("run_id") != self.journal.run_id):
                raise JournalError("trade record binding differs")
            self._validate_trade(trade)
            if trade["phase"] not in TERMINAL and state["active_trade"] != transaction_id:
                raise JournalError("nonterminal trade is not the active transaction")
        return snapshot.revision, state, registry, trade

    @staticmethod
    def _validate_trade(trade):
        required = {"schema", "id", "run_id", "initiator", "proposal", "proposal_digest", "phase",
                    "created_ms", "expires_ms", "last_clock_ms", "history", "ready", "applied", "verified",
                    "dispatched", "recovery_required", "command_digests"}
        if set(trade) - required - {"commit_evidence", "interruption"} or not required <= set(trade):
            raise JournalError("trade record has unknown or missing fields")
        _player(trade["initiator"])
        _hex(trade["proposal_digest"], 64, "proposal digest")
        if _encode(trade["proposal"])[1] != trade["proposal_digest"]:
            raise JournalError("trade proposal digest differs")
        if trade["phase"] not in PHASES or type(trade["recovery_required"]) is not bool:
            raise JournalError("invalid persisted trade phase")
        if any(type(trade[k]) is not int or not 0 <= trade[k] <= 2**53-1 for k in ("created_ms", "expires_ms", "last_clock_ms")):
            raise JournalError("invalid persisted trade clock")
        if trade["expires_ms"] != trade["created_ms"]+300_000 or trade["last_clock_ms"] < trade["created_ms"]:
            raise JournalError("persisted offer deadline differs")
        proposal = trade["proposal"]
        if set(proposal) != {"link_id", "participants"} or set(proposal["participants"]) != set(PLAYERS):
            raise JournalError("incomplete persisted trade proposal")
        participants = []
        for player in PLAYERS:
            value = copy.deepcopy(proposal["participants"][player])
            value["context"] = _context(value["context"])
            participants.append(TradeParticipant(**value))
        TradeProposal(proposal["link_id"], *participants)
        for field in ("ready", "applied", "verified", "dispatched"):
            if not isinstance(trade[field], dict) or not set(trade[field]) <= set(PLAYERS):
                raise JournalError("invalid persisted participant evidence")
        if not set(trade["verified"]) <= set(trade["applied"]):
            raise JournalError("verified result has no native application")
        if trade["phase"] in COMMITTED:
            if set(trade["ready"]) != set(PLAYERS) or "commit_evidence" not in trade:
                raise JournalError("persisted COMMIT lacks both prepared records")
            _proof(trade["commit_evidence"])
        elif trade["applied"] or trade["verified"] or "commit_evidence" in trade:
            raise JournalError("pre-COMMIT trade contains physical completion")
        if trade["phase"] == "both_prepared" and set(trade["ready"]) != set(PLAYERS):
            raise JournalError("both-prepared phase lacks a participant")
        if trade["phase"] in {"both_applied", "both_verified", "link_committed"} and set(trade["applied"]) != set(PLAYERS):
            raise JournalError("both-applied phase lacks a participant")
        if trade["phase"] in {"both_verified", "link_committed"} and set(trade["verified"]) != set(PLAYERS):
            raise JournalError("both-verified phase lacks a participant")
        if not isinstance(trade["command_digests"], dict) or set(trade["command_digests"]) != set(PLAYERS):
            raise JournalError("command-body bindings are incomplete")
        for entries in trade["command_digests"].values():
            if not isinstance(entries, dict) or not set(entries) <= COMMANDS:
                raise JournalError("invalid command-body binding")
            for value in entries.values():
                _hex(value, 64, "command body")
        if (not isinstance(trade["history"], list) or not trade["history"]
                or trade["history"][0]["phase"] != "offered" or trade["history"][-1]["phase"] != trade["phase"]):
            raise JournalError("trade phase history differs")

    @staticmethod
    def _registered_pair(registry, proposal):
        link = registry.document()["links"].get(proposal["link_id"])
        participants = proposal["participants"]
        if link is None or set(link["members"]) != {participants[p]["member_id"] for p in PLAYERS}:
            raise JournalError("the prepared logical pair changed")
        for participant in participants.values():
            if registry.resolve(_context(participant["context"]), participant["key"]) != participant["member_id"]:
                raise JournalError("prepared participant identity changed")

    def _authorize(self, action, player, authority, state, trade):
        if self.policy.authorize(action, player, authority, _clone(state), None if trade is None else _clone(trade)) is not True:
            raise JournalError("trade authority is unavailable or stale")

    def _now(self, trade=None):
        value = self.clock()
        if type(value) is not int or not 0 <= value <= 2**53-1:
            raise JournalError("valid independent wall-clock time required")
        if trade is not None and value < trade["last_clock_ms"]:
            raise JournalError("trade clock moved backwards; authority must be revoked")
        return value

    @staticmethod
    def _phase(trade, phase, operation_id, now, reason=None):
        if trade["phase"] != phase:
            trade["phase"] = phase
            trade["history"].append({"phase": phase, "event_id": operation_id, "time_ms": now, "reason": reason})
        trade["last_clock_ms"] = now

    @staticmethod
    def _body(trade, command, player, payload=None):
        body = {"cmd": command, "transaction_id": trade["id"], "proposal_digest": trade["proposal_digest"],
                "player": player, "payload": _clone(payload or {"schema": "trade-control-v1"})}
        fingerprint = _encode(body)[1]
        existing = trade["command_digests"][player].get(command)
        if existing is not None and existing != fingerprint:
            raise JournalError("a persisted trade command cannot change its body")
        trade["command_digests"][player][command] = fingerprint
        return body

    def _save(self, issuer, operation_id, message, revision, state, trade, commands, acknowledgements=()):
        self._validate_trade(trade)
        if self.compose_components is not None:
            # The binding may update only components. All inputs are detached;
            # rules, identities, trade evidence and outboxes remain coordinator-owned.
            components = self.compose_components(_clone(state), _clone(trade),
                _clone(commands), [_clone(row) for row in acknowledgements])
            if not isinstance(components, dict):
                raise JournalError("trade composition must return a component dictionary")
            state["components"] = _clone(components)
        receipt = self.journal.commit(issuer, operation_id, message, expected_revision=revision,
            state=state, commands=commands,
            result={"ack": "ACK", "transaction_id": trade["id"], "phase": trade["phase"]},
            acknowledgements=acknowledgements,
            records=[{"namespace": NAMESPACE, "key": trade["id"], "value": trade}])
        return copy.deepcopy(receipt.result)

    def _cancel(self, state, trade, phase, operation_id, now, reason, commands):
        if trade["phase"] in COMMITTED:
            raise JournalError("persisted COMMIT is forward-only and cannot be cancelled")
        if trade["phase"] in TERMINAL:
            return
        self._phase(trade, phase, operation_id, now, reason)
        state["active_trade"] = None
        for player in PLAYERS:
            commands[player].append(self._body(trade, "native_trade_abort", player,
                {"schema": "trade-abort-v1", "reason": reason, "terminal_phase": phase}))

    def _command(self, player, message, trade, expected):
        command = self.journal.command(player, message["command_id"])
        if type(message["command_sequence"]) is not int or message["command_sequence"] != command["command_sequence"]:
            raise JournalError("trade command sequence differs")
        body = command["body"]
        if (body.get("cmd") not in expected or body.get("transaction_id") != trade["id"]
                or body.get("proposal_digest") != trade["proposal_digest"] or body.get("player") != player):
            raise JournalError("receipt is not bound to this player's trade command")
        if _encode(body)[1] != trade["command_digests"][player].get(body["cmd"]):
            raise JournalError("command body differs from its persisted trade phase")
        return command

    def handle(self, player, operation_id, message, *, owner):
        _player(player)
        _hex(operation_id, 32, "event")
        message = _clone(message)
        event = message.get("event")
        fields = {
            "trade_offer": {"event", "payload"},
            "trade_cancel": {"event", "transaction_id", "reason"},
            **{kind: {"event", "transaction_id", "command_id", "command_sequence", "receipt"}
               for kind in ("trade_decision", "trade_ready", "trade_applied", "trade_verified", "trade_ack")},
        }
        if event not in fields or set(message) != fields[event]:
            raise JournalError("unsupported or incomplete trade event")
        revision, state, registry, trade = self._load(message.get("transaction_id"))
        self._authorize(event, player, owner, state, trade)
        previous = self.journal.event(player, operation_id, message)
        if previous is not None:
            return copy.deepcopy(previous.result)
        now = self._now(trade)
        commands, acknowledgements = {"a": [], "b": []}, []
        if event == "trade_offer":
            if state["active_trade"] is not None:
                raise JournalError("a linked-pair trade is already active")
            proposal = self.policy.offer(player, _clone(message["payload"]), _clone(state))
            if not isinstance(proposal, TradeProposal):
                raise JournalError("offer requires a validated linked-pair proposal")
            document = proposal.document()
            link = registry.document()["links"].get(proposal.link_id)
            if link is None or set(link["members"]) != {proposal.a.member_id, proposal.b.member_id}:
                raise JournalError("proposal does not name one existing linked pair")
            for participant in (proposal.a, proposal.b):
                if registry.resolve(participant.context, participant.key) != participant.member_id:
                    raise JournalError("proposal's scoped physical identity differs from its logical member")
            identifier = _hex(self.new_id(), 32, "new transaction")
            if self.journal.record(NAMESPACE, identifier) is not None:
                raise JournalError("transaction identifier was reused")
            trade = {"schema": TRADE_SCHEMA, "id": identifier, "run_id": self.journal.run_id,
                "initiator": player, "proposal": document, "proposal_digest": _encode(document)[1],
                "phase": "offered", "created_ms": now, "expires_ms": now+300_000, "last_clock_ms": now,
                "history": [{"phase": "offered", "event_id": operation_id, "time_ms": now, "reason": None}],
                "ready": {}, "applied": {}, "verified": {}, "dispatched": {}, "recovery_required": False,
                "command_digests": {"a": {}, "b": {}}}
            state["active_trade"] = identifier
            peer = "b" if player == "a" else "a"
            payload = _proof(self.policy.prompt(_clone(trade), peer))
            commands[peer].append(self._body(trade, "native_trade_prompt", peer, payload))
        elif event == "trade_cancel":
            if not isinstance(message["reason"], str) or not 1 <= len(message["reason"]) <= 256:
                raise JournalError("explicit bounded cancellation reason required")
            self._cancel(state, trade, "cancelled", operation_id, now, message["reason"], commands)
        else:
            expected = {
                "trade_decision": {"native_trade_prompt"}, "trade_ready": {"native_trade_prepare"},
                "trade_applied": {"native_trade_commit"}, "trade_verified": {"native_trade_commit"},
                "trade_ack": COMMANDS - {"native_trade_commit"},
            }[event]
            command = self._command(player, message, trade, expected)
            wire = _proof(message["receipt"])
            if event == "trade_ack":
                if (command["body"]["cmd"] in {"native_trade_prompt", "native_trade_prepare"}
                        and trade["phase"] not in {"cancelled", "declined", "expired"}):
                    raise JournalError("active prompt/prepare requires its typed decision/readiness receipt")
                verified = _proof(self.policy.auxiliary(_clone(trade), player, copy.deepcopy(command), wire))
                acknowledgements.append({"player": player, "command_id": command["command_id"],
                                         "outcome": "ACK", "receipt": verified})
            elif event == "trade_decision":
                if player == trade["initiator"]:
                    raise JournalError("only the partner may answer this offer")
                decision = self.policy.decision(_clone(trade), player, copy.deepcopy(command), wire)
                if not isinstance(decision, tuple) or len(decision) != 2 or type(decision[0]) is not bool:
                    raise JournalError("validated native decision and receipt required")
                acknowledgements.append({"player": player, "command_id": command["command_id"],
                                         "outcome": "ACK", "receipt": _proof(decision[1])})
                if trade["phase"] == "offered":
                    if now >= trade["expires_ms"]:
                        self._cancel(state, trade, "expired", operation_id, now, "offer_expired", commands)
                    elif decision[0]:
                        self._phase(trade, "accepted", operation_id, now)
                    else:
                        self._cancel(state, trade, "declined", operation_id, now, "partner_declined", commands)
                elif trade["phase"] not in TERMINAL and command["outcome"] is None:
                    raise JournalError("offer decision arrived in the wrong phase")
            elif event == "trade_ready":
                if trade["phase"] not in {"preparing", "both_prepared"}:
                    raise JournalError("trade is not accepting preparation; retired commands need a no-effect ACK")
                prepared = self.policy.ready(_clone(trade), player, copy.deepcopy(command), wire)
                participant = trade["proposal"]["participants"][player]
                if (not isinstance(prepared, PreparedTrade) or prepared.proposal_digest != trade["proposal_digest"]
                        or prepared.context_generation != participant["context"]["context_generation"]
                        or prepared.evidence_digest != participant["evidence_digest"]):
                    raise JournalError("prepared party/context differs from the persisted proposal")
                document = _clone(asdict(prepared))
                if player in trade["ready"] and trade["ready"][player] != document:
                    raise JournalError("conflicting prepared receipt")
                trade["ready"][player] = document
                acknowledgements.append({"player": player, "command_id": command["command_id"],
                                         "outcome": "ACK", "receipt": document})
                if set(trade["ready"]) == set(PLAYERS):
                    self._phase(trade, "both_prepared", operation_id, now)
            elif event == "trade_applied":
                if trade["phase"] not in COMMITTED:
                    raise JournalError("physical application cannot precede persisted COMMIT")
                applied = _proof(self.policy.applied(_clone(trade), player, copy.deepcopy(command), wire))
                if player in trade["applied"] and trade["applied"][player] != applied:
                    raise JournalError("conflicting native application evidence")
                trade["applied"][player] = applied
                if trade["phase"] == "commit_persisted":
                    self._phase(trade, "commit_dispatched", operation_id, now, "validated_application_evidence")
                if set(trade["applied"]) == set(PLAYERS) and trade["phase"] == "commit_dispatched":
                    self._phase(trade, "both_applied", operation_id, now)
            elif event == "trade_verified":
                if trade["phase"] not in COMMITTED or player not in trade["applied"]:
                    raise JournalError("verification needs persisted native application evidence")
                verified = self.policy.verified(_clone(trade), player, copy.deepcopy(command), wire)
                if not isinstance(verified, TradeVerification):
                    raise JournalError("independent native and save verification required")
                donor = trade["proposal"]["participants"]["b" if player == "a" else "a"]
                recipient = trade["proposal"]["participants"][player]
                witness = verified.migration
                if (witness.member_id != donor["member_id"] or asdict(witness.source_context) != donor["context"]
                        or witness.before_key != donor["key"] or witness.before_evidence_digest != donor["evidence_digest"]
                        or asdict(witness.after.context) != recipient["context"]):
                    raise JournalError("verified migration differs from prepared ownership/context")
                document = _clone(asdict(verified))
                if player in trade["verified"] and trade["verified"][player] != document:
                    raise JournalError("conflicting verified trade receipt")
                trade["verified"][player] = document
                acknowledgements.append({"player": player, "command_id": command["command_id"],
                                         "outcome": "ACK", "receipt": document})
                if set(trade["verified"]) == set(PLAYERS) and trade["phase"] != "link_committed":
                    self._phase(trade, "both_verified", operation_id, now)
        trade["last_clock_ms"] = now
        return self._save(player, operation_id, message, revision, state, trade, commands, acknowledgements)

    def control(self, action, transaction_id, operation_id, *, authority, details=None):
        """Internal server transitions; never dispatch this from a client event."""
        if action not in {"prepare", "commit", "dispatched", "finalize", "expire", "interrupt"}:
            raise JournalError("unsupported trade control transition")
        _hex(operation_id, 32, "control event")
        details = _clone(details or {})
        message = {"event": "trade_control", "action": action, "transaction_id": transaction_id, "details": details}
        revision, state, registry, trade = self._load(transaction_id)
        self._authorize(action, None, authority, state, trade)
        issuer = trade["initiator"]
        old = self.journal.event(issuer, operation_id, message)
        if old is not None:
            return copy.deepcopy(old.result)
        now = self._now(trade)
        commands = {"a": [], "b": []}
        if action == "prepare":
            if trade["phase"] != "accepted":
                raise JournalError("accepted offer required before preparation")
            for player in PLAYERS:
                payload = _proof(self.policy.prepare(_clone(trade), player))
                commands[player].append(self._body(trade, "native_trade_prepare", player, payload))
            self._phase(trade, "preparing", operation_id, now)
        elif action == "commit":
            if trade["phase"] != "both_prepared" or set(trade["ready"]) != set(PLAYERS):
                raise JournalError("both current prepared receipts required before COMMIT")
            self._registered_pair(registry, trade["proposal"])
            evidence = _proof(self.policy.commit(_clone(trade), _clone(state), authority))
            trade["commit_evidence"] = evidence
            self._phase(trade, "commit_persisted", operation_id, now)
            for player in PLAYERS:
                commands[player].append(self._body(trade, "native_trade_commit", player,
                    {"schema": "paired-native-commit-v1", "prepared_digest": _encode(trade["ready"][player])[1],
                     "proposal": trade["proposal"], "prepared": trade["ready"][player]}))
        elif action == "dispatched":
            if trade["phase"] not in COMMITTED or set(details) != {"player", "command_id", "command_sequence"}:
                raise JournalError("persisted COMMIT and exact dispatch observation required")
            player = details["player"]
            _player(player)
            command = self._command(player, details, trade, {"native_trade_commit"})
            trade["dispatched"][player] = command["command_id"]
            if trade["phase"] == "commit_persisted":
                self._phase(trade, "commit_dispatched", operation_id, now)
        elif action == "finalize":
            if trade["phase"] != "both_verified" or set(trade["verified"]) != set(PLAYERS):
                raise JournalError("both independently verified results required before link commit")
            self._registered_pair(registry, trade["proposal"])
            witnesses = [_migration(trade["verified"][p]["migration"]) for p in PLAYERS]
            registry.migrate_many(issuer, operation_id, witnesses)
            rules = self.policy.finalize(_clone(state["rules"]), _clone(trade), tuple(witnesses))
            state["rules"] = _clone(rules)
            state["identities"] = registry.document()
            state["active_trade"] = None
            trade["recovery_required"] = False  # transaction-local obligation; no ordinary frame grant
            self._phase(trade, "link_committed", operation_id, now)
            for player in PLAYERS:
                commands[player].append(self._body(trade, "native_trade_release", player,
                    {"schema": "paired-trade-release-v1", "finalization_event": operation_id}))
        elif action == "expire":
            if trade["phase"] != "offered" or now < trade["expires_ms"]:
                raise JournalError("offer is not eligible for expiry")
            self._cancel(state, trade, "expired", operation_id, now, "offer_expired", commands)
        elif action == "interrupt":
            reason = details.get("reason")
            if not isinstance(reason, str) or not 1 <= len(reason) <= 256:
                raise JournalError("bounded interruption reason required")
            if trade["phase"] in COMMITTED and trade["phase"] != "link_committed":
                trade["recovery_required"] = True
                trade["interruption"] = {"reason": reason, "event_id": operation_id, "time_ms": now}
            elif trade["phase"] not in TERMINAL:
                self._cancel(state, trade, "cancelled", operation_id, now, reason, commands)
        trade["last_clock_ms"] = now
        return self._save(issuer, operation_id, message, revision, state, trade, commands)

    def authorize_delivery(self, player, command_id, *, owner):
        """Gate a stored command; does not dequeue, mark sent, ACK, or grant frames."""
        command = self.journal.command(player, command_id)
        if command["body"].get("cmd") not in COMMANDS:
            raise JournalError("not a coordinated trade command")
        _, state, _, trade = self._load(command["body"]["transaction_id"])
        self._authorize("deliver", player, owner, state, trade)
        if _encode(command["body"])[1] != trade["command_digests"][player].get(command["body"]["cmd"]):
            raise JournalError("delivery body differs from its persisted trade phase")
        if command["body"]["cmd"] == "native_trade_commit" and trade["phase"] not in COMMITTED:
            raise JournalError("COMMIT has no persisted authority")
        return copy.deepcopy(command)

    def status(self, transaction_id):
        """Detached persisted facts; no renewed authority or inferred liveness."""
        _, _, _, trade = self._load(transaction_id)
        return {"transaction_id": trade["id"], "phase": trade["phase"],
                "recovery_required": trade["recovery_required"],
                "owns_parties": trade["phase"] not in TERMINAL | {"offered"},
                "prepared_players": sorted(trade["ready"]), "applied_players": sorted(trade["applied"]),
                "verified_players": sorted(trade["verified"])}
