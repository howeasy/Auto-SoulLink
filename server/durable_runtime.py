"""Shared configured session, journal, rule and paired-control service.

Extracted from the published RR runtime at120c80d. Generation bindings supply
semantic/native/reconciliation validation; this service never treats a JSON
success flag as physical evidence and never imports a legacy run implicitly.
"""
from __future__ import annotations

import asyncio
import contextlib
import copy
import logging
import re
import secrets
import sqlite3
import time

from server.durable_dispatch import DurableDispatcher
from server.paired_recovery import VerifiedReconciliation, _hex
from server.protocol import ProtocolError, canonical_json, decode_frame, digest, nack
from server.protocol_journal import JournalError, ProtocolJournal
from server.save_identity import SaveIdentity

ENVELOPE = {"protocol", "player", "admission_epoch", "session_id", "seq", "operation_id", "client_nonce"}
TIMEOUT = 2.0
MAX_CONTROL_CHALLENGES = 65536
log = logging.getLogger(__name__)


class DurableRuntime:
    def __init__(self, path, *, contract, data_dir, protocol, hold_event, stage_type, new_session_gate,
                 validate_event, validate_receipt,
                 verify_reconciliation, initial_state=None, run_id=None, clock=time.monotonic):
        if not all(callable(fn) for fn in (validate_event, validate_receipt, verify_reconciliation, clock)):
            raise JournalError("complete generation validation and monotonic clock bindings required")
        if any(not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_.-]{0,63}", name)
               for name in (protocol, hold_event)) or hold_event in {"hello", "control", "sync", "command_ack"}:
            raise JournalError("explicit protocol and distinct hold-event names required")
        if not callable(new_session_gate) or not callable(getattr(stage_type, "restore", None)):
            raise JournalError("generation session-gate and stage factories required")
        self.protocol, self.hold_event = protocol, hold_event
        self.contract, self.data_dir = copy.deepcopy(contract), str(data_dir)
        self.validate_event, self.validate_receipt = validate_event, validate_receipt
        self.verify_reconciliation, self.clock = verify_reconciliation, clock
        self._clock = None
        self._failed = None
        self._control_seen = {}
        self._control_challenges = {}
        self._wall_seen = {}
        self._writers = {}
        self._lock = asyncio.Lock()
        self.journal = ProtocolJournal(path, run_id=run_id, contract_hash=digest(contract))
        try:
            if initial_state is not None:
                self.journal.bootstrap(initial_state)
            self.gate = new_session_gate(nonce_registry=self.journal.register_session)
            if self.gate.protocol != protocol or not self.gate.durable_ids:
                raise JournalError("generation gate does not use the configured durable protocol")
            self.gate.refresh(self.contract)
            runtime = self

            class BoundStage:
                @staticmethod
                def restore(document, *, data_dir):
                    stage = stage_type.restore(document, data_dir=data_dir)
                    if (canonical_json(stage.component["contract"]) != canonical_json(runtime.contract)
                            or stage.identities.document()["run_id"] != runtime.journal.run_id):
                        raise JournalError("Durable state differs from its journal/run contract")
                    return stage

            self._stage_type = BoundStage
            self.dispatcher = DurableDispatcher(self.journal, data_dir=data_dir, staged_type=BoundStage,
                validate_event=self._validate_event, validate_receipt=self._validate_receipt)
            stage = self.state()
            stage.barrier.invalidate("Durable runtime opened; fresh paired admission required")
            self._commit_system(stage, "runtime_opened")
        except Exception:
            self.journal.close()
            raise

    def state(self):
        snapshot = self.journal.snapshot()
        stage = self._stage_type.restore(snapshot.state, data_dir=self.data_dir)
        stage.journal_revision = snapshot.revision
        return stage

    def rule_state(self):
        return self.state().rules

    def _now(self):
        try:
            value = self.clock()
            if (type(value) not in (int, float) or not 0 <= value < float("inf")
                    or (self._clock is not None and value < self._clock)):
                raise JournalError("Durable monotonic clock failed")
        except Exception as error:
            self._failed = "Durable monotonic clock failed; reopen and reconcile"
            self._notify_holds(self._failed)
            self.gate.sessions.clear()
            self._control_seen.clear()
            self._control_challenges.clear()
            raise JournalError(self._failed) from error
        self._clock = value
        return value

    def _commit_system(self, stage, event):
        return self.journal.commit("a", secrets.token_hex(16), {"event": event},
            expected_revision=stage.journal_revision, state=stage.document(), commands={"a": [], "b": []},
            result={"ack": "ACK"})

    def _validate_event(self, player, payload, stage):
        session = self.gate.sessions[player]
        if payload["event"] == "hello":
            metadata = {k: v for k, v in session.metadata.items() if k != "control_binding"}
            control = session.metadata["control_binding"]
            stage.admit(player, metadata, {k: control[k] for k in ("binding_digest", "context_generation")})
        if payload["event"] != "sync":
            self.validate_event(player, payload, stage.rules)

    def _validate_receipt(self, player, command, payload, stage):
        return self.validate_receipt(player, command, payload, stage.rules)

    def _semantic(self, message):
        return {k: copy.deepcopy(v) for k, v in message.items() if k not in ENVELOPE}

    def _admit(self, player, message, owner):
        if player in self.gate.sessions:
            raise ProtocolError("Durable player already has an owning connection")
        generation = _hex(message.get("context_generation"), 32, "Durable host context generation")
        stored = self.state().component["admissions"][player]
        identity = stored["metadata"]["save_identity"] if stored else None
        session = self.gate.admit(self.contract, player, message, owner, identity=identity)
        binding = {"session_id": session.session_id, "admission_epoch": self.gate.epoch,
                   "context_generation": generation}
        binding["binding_digest"] = digest({"player": player, "metadata": session.metadata, **binding})
        session.metadata["control_binding"] = binding
        payload = self._semantic(message)
        payload.pop("context_generation", None)
        self.dispatcher.dispatch(player, message["operation_id"], payload, preserve_peer_session=True,
                                 save_identity=SaveIdentity(**session.metadata["save_identity"]))
        self._control_seen[player] = self._now()  # Initial heartbeat deadline; HELLO grants no ticket.
        self._control_challenges[player] = set()
        # Durable commands are fetched through a journaled sync/semantic response,
        # never accepted as an unjournaled HELLO command batch by the client.
        response = self.gate.response(player, message, [], hello=True)
        response["recovery"] = self.state().barrier.document()
        # The barrier now requires fresh paired proofs. Initial peers are already
        # held; sending a disconnect notice here would create a HELLO/reconnect
        # loop in which the second arrival always evicts the first.
        return response

    def _control(self, player, message):
        session = self.gate.sessions[player]
        packet = message.get("control")
        binding = session.metadata["control_binding"]
        if (not isinstance(packet, dict) or set(packet) != {*binding, "challenge"}
                or any(packet[k] != value for k, value in binding.items())):
            raise ProtocolError("Durable control challenge differs from its admitted binding")
        challenge = _hex(packet["challenge"], 32, "control challenge")
        if message["operation_id"] != challenge:
            raise ProtocolError("Durable control operation must identify its fresh challenge")
        seen_challenges = self._control_challenges[player]
        if challenge in seen_challenges:
            raise ProtocolError("Durable control challenge replay requires a fresh challenge")
        if len(seen_challenges) >= MAX_CONTROL_CHALLENGES:
            raise ProtocolError("Durable control challenge history is full; reconnect required")
        seen_challenges.add(challenge)
        now = self._now()
        if any(now - seen >= TIMEOUT for seen in self._control_seen.values()):
            self.suspend("paired heartbeat expired; reconnect required")
            raise ProtocolError("paired heartbeat expired; reconnect required")
        self._control_seen[player] = now
        stage = self.state()
        evidence = message.get("reconciliation")
        if evidence is not None:
            verification_view = self._stage_type.restore(stage.document(), data_dir=self.data_dir)
            verification_view.journal_revision = stage.journal_revision
            proof = self.verify_reconciliation(player, copy.deepcopy(evidence), verification_view,
                                               copy.deepcopy(binding))
            if proof is None and stage.barrier.document()["proofs"][player] is not None:
                stage.barrier.invalidate("Durable reconciliation evidence is no longer verified")
                self._commit_system(stage, "runtime_reconciliation_refused")
            elif proof is not None:
                if not isinstance(proof, VerifiedReconciliation):
                    raise JournalError("Durable reconciliation binding returned unvalidated proof")
                before = stage.document()
                stage.barrier.reconcile(player, proof)
                if stage.document() != before:
                    self.journal.commit(player, challenge, self._semantic(message),
                        expected_revision=stage.journal_revision, state=stage.document(),
                        commands={"a": [], "b": []}, result={"ack": "ACK"})
        ticket = stage.barrier.ticket()
        both_live = (set(self.gate.sessions) == {"a", "b"}
                     and set(self._control_seen) == {"a", "b"}
                     and all(now - seen < TIMEOUT for seen in self._control_seen.values()))
        authority = {**binding, "challenge": challenge, "authority": "hold",
                     "reason": stage.barrier.status()["reason"]}
        if ticket is not None and both_live and self._failed is None:
            authority = {**binding, "challenge": challenge, "authority": "run",
                         "recovery_epoch": ticket["epoch"], "ticket_digest": ticket["digest"]}
        response = self.gate.response(player, message, [])
        response.update(control=authority, recovery=stage.barrier.document())
        return response

    def process(self, message, owner):
        try:
            response = self._process(message, owner)
            self._wall_seen[message["player"]] = time.time()
            return response
        except (OSError, sqlite3.DatabaseError):
            self._failed = "Durable durable persistence failed; reopen and reconcile"
            self._notify_holds(self._failed)
            self.gate.sessions.clear()
            self._control_seen.clear()
            self._control_challenges.clear()
            raise

    def _process(self, message, owner):
        """One decoded request on its private connection owner; no awaits inside."""
        if self._failed:
            raise JournalError("Durable runtime requires reopen after persistence/control failure")
        player = message.get("player")
        if player not in ("a", "b") or message.get("protocol") != self.protocol:
            raise ProtocolError("configured durable runtime requires its own player/protocol")
        event = message.get("event")
        now = self._now()
        if any(now - seen >= TIMEOUT for seen in self._control_seen.values()):
            self.suspend("paired heartbeat expired; reconnect required")
            if event != "hello":
                raise ProtocolError("paired heartbeat expired; reconnect required")
        if event == "hello":
            try:
                return self._admit(player, message, owner)
            except Exception:
                # Admission and rule publication must both finish before this
                # owner can send events. Do not evict a different live owner.
                if self.gate.close(player, owner):
                    self._control_seen.pop(player, None)
                    self._control_challenges.pop(player, None)
                raise
        prior = self.gate.accept(player, message, owner)
        if prior is not None:
            # Delivery retry is not a heartbeat renewal or new control authority.
            if event == "control":
                raise ProtocolError("control challenge replay requires a fresh connection")
            return prior
        if event == "control":
            return self._control(player, message)
        if event in {"ghost_pos", self.hold_event, "runtime_opened", "runtime_suspended", "runtime_reconciliation_refused"}:
            raise ProtocolError("Durable transient/internal traffic cannot enter durable rules")
        self._dispatch_semantic(player, message, owner)
        return self.gate.response(player, message, self.delivery_commands(player))

    def _dispatch_semantic(self, player, message, owner):
        """Generation extension after ownership/replay/control checks, before reply.

        Overrides must journal exactly one semantic event before returning. This
        seam grants no physical authority and does not replace the session gate.
        """
        return self.dispatcher.dispatch(player, message["operation_id"], self._semantic(message),
                                        preserve_peer_session=True)

    def delivery_commands(self, player):
        # A native command can itself contain player/seq/operation_id. Preserve
        # that exact body beneath the transport envelope instead of overwriting
        # it in SessionGate.response or stripping it in the client pump.
        commands = []
        for command in self.journal.pending(player):
            body = self.journal.command(player, command["command_id"])["body"]
            commands.append({"cmd": body["cmd"], "body": body,
                             "command_id": command["command_id"], "command_sequence": command["command_sequence"]})
        return commands

    def _notify_holds(self, reason, *, except_owner=None):
        for player, (owner, writer) in tuple(self._writers.items()):
            if owner is except_owner or not self.gate.owns(player, owner):
                continue
            session = self.gate.sessions[player]
            notice = {"protocol": self.protocol, "player": player, "session_id": session.session_id,
                      "admission_epoch": self.gate.epoch, "event": self.hold_event, "reason": reason,
                      "commands": []}
            # Its closure/watchdog revokes the client even if the notice cannot
            # be delivered. No successful write is treated as peer receipt.
            with contextlib.suppress(ConnectionError, RuntimeError):
                writer.write(canonical_json(notice).encode("ascii") + b"\n")

    def _before_suspend(self, reason):
        """Generation binding may journal owned obligations after the hold notice.

        Called under the same serialized lifecycle as suspend. Failure still
        clears all connection authority in suspend's finally block.
        """

    def suspend(self, reason):
        self._notify_holds(reason)
        try:
            self._before_suspend(reason)
            stage = self.state()
            stage.barrier.invalidate(reason)
            self._commit_system(stage, "runtime_suspended")
        except Exception:
            self._failed = "could not persist durable suspension"
            raise
        finally:
            self.gate.sessions.clear()
            self._control_seen.clear()
            self._control_challenges.clear()

    def disconnect(self, player, owner):
        if not self.gate.owns(player, owner):
            return False
        self.suspend(f"player {player} disconnected; paired reconciliation required")
        return True

    def status(self):
        return self._status_from_stage(self.state())

    def _status_from_stage(self, stage):
        return {"recovery": stage.barrier.status(), "failed": self._failed,
                "connections": {p: {"connected": p in self.gate.sessions, "rom_type": self.gate.sessions[p].metadata.get("rom_type") if p in self.gate.sessions else None,
                    "last_event": "durable_session", "last_seen_ts": self._wall_seen.get(p)} for p in ("a", "b")},
                "scope": "configured_runtime_requires_qualified_generation_bindings"}

    def _presentation_state(self):
        """Detached display projection; generation bindings may avoid proof replay.

        This hook is never used for admission, command execution or authority.
        """
        return self.state()

    def _publish(self, callback):
        if callback is not None:
            try:
                stage = self._presentation_state()
                callback(stage.rules, self._status_from_stage(stage))
            except Exception:
                # Presentation failure cannot roll back a committed event or
                # cause another physical command to be generated.
                log.exception("Durable committed presentation could not be published")

    async def handle_client(self, reader, writer, *, first_frame=None, on_change=None):
        owner, player = object(), None
        message = {}
        try:
            raw = first_frame
            while True:
                if raw is None:
                    raw = await asyncio.wait_for(reader.readuntil(b"\n"), TIMEOUT)
                message = decode_frame(raw)
                if player is None:
                    if message.get("event") != "hello" or message.get("player") not in ("a", "b"):
                        raise ProtocolError("Durable connection must start with HELLO")
                    player = message["player"]
                elif message.get("player") != player:
                    raise ProtocolError("Durable connection cannot change player")
                async with self._lock:
                    response = self.process(message, owner)
                    self._writers[player] = (owner, writer)
                    # Commit and validate first, then expose the response before
                    # presentation work. Rendering cannot consume a live permit's
                    # response budget or delay an already committed ACK.
                    writer.write(canonical_json(response).encode("ascii") + b"\n")
                    self._publish(on_change)
                await writer.drain()
                raw = None
        except (asyncio.IncompleteReadError, ConnectionError, TimeoutError):
            pass
        except Exception as error:
            if not isinstance(error, (ProtocolError, JournalError, ValueError, OSError,
                                      sqlite3.DatabaseError, asyncio.LimitOverrunError)):
                log.exception("Durable connection callback failed; revoking its owner")
            response = nack(message, str(error)[:200], pending=True, protocol=self.protocol)
            with contextlib.suppress(ConnectionError):
                writer.write(canonical_json(response).encode("ascii") + b"\n")
                await writer.drain()
        finally:
            try:
                async with self._lock:
                    if player is not None:
                        self.disconnect(player, owner)
                        self._publish(on_change)
            finally:
                if player is not None and self._writers.get(player, (None,))[0] is owner:
                    self._writers.pop(player, None)
                writer.close()
                with contextlib.suppress(ConnectionError):
                    await writer.wait_closed()

    def close(self):
        if self._writers:
            raise JournalError("close runtime connections before closing their journal")
        self.journal.close()
