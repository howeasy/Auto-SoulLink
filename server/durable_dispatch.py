"""Cartridge-independent staged rule dispatch, atomically backed by ProtocolJournal.

Bindings supply event and receipt validation and decide when a session may call
this service. No transport, presentation, emulator pause or memory write occurs here.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass

from server.protocol_journal import JournalError, ProtocolJournal
from server.staged_state import StagedSoulLinkState


@dataclass(frozen=True)
class DispatchResult:
    revision: int
    result: dict
    replayed: bool


class DurableDispatcher:
    def __init__(self, journal: ProtocolJournal, *, data_dir, staged_type=StagedSoulLinkState,
                 validate_event, validate_receipt):
        if not callable(validate_event) or not callable(validate_receipt):
            raise JournalError("event and physical receipt validators are required")
        self.journal = journal
        self.data_dir = str(data_dir)
        self.staged_type = staged_type
        self.validate_event = validate_event
        self.validate_receipt = validate_receipt

    def state(self):
        return self.staged_type.restore(self.journal.snapshot().state, data_dir=self.data_dir)

    def dispatch(self, player, operation_id, payload, *, preserve_peer_session=False):
        existing = self.journal.event(player, operation_id, payload)
        if existing is not None:
            return DispatchResult(existing.revision, existing.result, True)
        snapshot = self.journal.snapshot()
        staged = self.staged_type.restore(snapshot.state, data_dir=self.data_dir)
        request = copy.deepcopy(payload)
        acknowledgements = []
        if request.get("event") == "command_ack":
            command = self.journal.command(player, request.get("command_id"))
            if request.get("command_sequence") != command["command_sequence"]:
                raise JournalError("command receipt sequence mismatch")
            # Validation returns the rule follow-up event(s), if any. It must
            # prove the physical poststate before returning an ACK follow-up.
            followups = self.validate_receipt(player, command, copy.deepcopy(request), staged)
            if not isinstance(followups, list) or any(not isinstance(event, dict) for event in followups):
                raise JournalError("receipt validator must return explicit follow-up events")
            acknowledgements.append({"player": player, "command_id": command["command_id"],
                                     "outcome": request.get("outcome"), "receipt": request.get("receipt")})
            immediate = []
            if command["outcome"] is None:
                for event in followups:
                    self.validate_event(player, event, staged)
                    immediate.extend(staged.handle_event(player, event, preserve_peer_session=preserve_peer_session))
        else:
            self.validate_event(player, request, staged)
            immediate = staged.handle_event(player, request, preserve_peer_session=preserve_peer_session)
        commands = staged.take_commands(player, immediate)
        # noop is the legacy transport's empty reply, not a game-side operation.
        commands = {p: [command for command in batch if command.get("cmd") != "noop"] for p, batch in commands.items()}
        receipt = self.journal.commit(player, operation_id, payload, expected_revision=snapshot.revision,
                                      state=staged.document(), commands=commands, result={"ack": "ACK"},
                                      acknowledgements=acknowledgements)
        return DispatchResult(receipt.revision, receipt.result, False)
