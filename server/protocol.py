"""Shared bounded JSON, connection ownership and session envelopes.

Generation-specific admission validates cartridges, save identity and capabilities
through hello_validator. This module owns byte-independent transport semantics.
Session-local response retry is not a durable operation/command journal.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import secrets
from dataclasses import dataclass

MAX_SEQUENCE = 2**53 - 1


class ProtocolError(ValueError):
    pass


def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical_json(value).encode("ascii")).hexdigest()


def decode_frame(raw):
    """Reject ambiguous JSON before selecting a player or touching a session."""
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ProtocolError("duplicate JSON object key")
            result[key] = value
        return result

    def invalid(value):
        raise ProtocolError("non-finite JSON number")

    try:
        result = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=invalid)
        if not isinstance(result, dict):
            raise ProtocolError("protocol frame must be an object")
        if any(key.startswith("_") for key in result):
            raise ProtocolError("reserved internal protocol field")
        pending = [(result, 0)]
        count = 0
        while pending:
            value, depth = pending.pop()
            count += 1
            if count > 100000 or depth > 32:
                raise ProtocolError("JSON structure exceeds protocol limits")
            if isinstance(value, (dict, list)):
                pending.extend((v, depth + 1) for v in (value.values() if isinstance(value, dict) else value))
                if isinstance(value, dict):
                    pending.extend((key, depth + 1) for key in value)
            elif isinstance(value, str):
                if len(value.encode("utf-8")) > 1024 * 1024:
                    raise ProtocolError("JSON string exceeds protocol limit")
            elif type(value) in (int, float) and not -MAX_SEQUENCE <= value <= MAX_SEQUENCE:
                raise ProtocolError("JSON number exceeds exact protocol range")
        return result
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise ProtocolError(str(exc)) from exc


@dataclass
class Session:
    owner: object
    nonce: str
    session_id: str
    metadata: dict
    last_seq: int = 0
    last_operation: str = ""
    last_digest: str = ""
    last_response: dict | None = None


class SessionGate:
    def __init__(self, *, protocol, hello_validator, durable_ids=False, nonce_registry=None):
        if not isinstance(protocol, str) or not protocol or len(protocol) > 64 or not callable(hello_validator):
            raise ProtocolError("a protocol identifier and cartridge validator are required")
        self.protocol = protocol
        self.hello_validator = hello_validator
        self.durable_ids = durable_ids
        self.nonce_registry = nonce_registry
        self.epoch = secrets.token_hex(16)
        self.contract_digest = None
        self.sessions = {}
        self._nonces = set()

    def refresh(self, contract):
        signature = digest(contract)
        if signature != self.contract_digest:
            self.contract_digest = signature
            self.epoch = secrets.token_hex(16)
            self.sessions.clear()
            return True
        return False

    def owns(self, player, owner):
        session = self.sessions.get(player)
        return session is not None and session.owner is owner

    def close(self, player, owner):
        if self.owns(player, owner):
            del self.sessions[player]
            return True
        return False

    def admit(self, contract, player, msg, owner, identity=None):
        self.refresh(contract)
        if player not in ("a", "b") or msg.get("player") != player:
            raise ProtocolError("HELLO player differs from its connection slot")
        if msg.get("protocol") != self.protocol or msg.get("event") != "hello":
            raise ProtocolError("the current admission protocol and HELLO are required")
        nonce = msg.get("client_nonce")
        if not isinstance(nonce, str) or not re.fullmatch(r"[0-9a-f]{32}", nonce):
            raise ProtocolError("a fresh 128-bit client session identifier is required")
        hello_id = nonce if self.durable_ids else nonce + ":hello"
        if type(msg.get("seq")) is not int or msg["seq"] != 0 or msg.get("operation_id") != hello_id:
            raise ProtocolError("invalid HELLO sequence or operation ID")
        metadata = self.hello_validator(contract, player, msg, identity)
        if not isinstance(metadata, dict):
            raise ProtocolError("cartridge validator must return explicit metadata")
        canonical_json(metadata)
        if nonce in self._nonces:
            raise ProtocolError("client nonce was already used; start a fresh connection handshake")
        # Refuse further admissions instead of allowing an unbounded nonce table or
        # forgetting a nonce and accepting stale HELLOs. Server restart has a new epoch.
        if len(self._nonces) >= 8192:
            raise ProtocolError("session history limit reached; restart the run server")
        self._nonces.add(nonce)
        session_id = (self.nonce_registry(player, nonce, self.epoch) if self.nonce_registry
                      else secrets.token_hex(16))
        session = Session(owner, nonce, session_id, metadata)
        self.sessions[player] = session
        return session

    def accept(self, player, msg, owner):
        if not self.owns(player, owner):
            raise ProtocolError("connection does not own this player session")
        if msg.get("player") != player:
            raise ProtocolError("event player differs from its connection slot")
        if not isinstance(msg.get("event"), str) or not 1 <= len(msg["event"]) <= 64:
            raise ProtocolError("invalid semantic event name")
        session = self.sessions[player]
        if (msg.get("protocol") != self.protocol or msg.get("admission_epoch") != self.epoch
                or msg.get("session_id") != session.session_id):
            raise ProtocolError("stale admission epoch or session ID")
        seq = msg.get("seq")
        operation = msg.get("operation_id")
        if type(seq) is not int or not 1 <= seq <= MAX_SEQUENCE:
            raise ProtocolError("invalid event sequence")
        if self.durable_ids:
            if not isinstance(operation, str) or not re.fullmatch(r"[0-9a-f]{32}", operation):
                raise ProtocolError("a persisted semantic operation ID is required")
        elif operation != session.nonce + ":" + str(seq):
            raise ProtocolError("operation ID does not match this session sequence")
        fingerprint = digest(msg)
        if seq == session.last_seq and operation == session.last_operation:
            if fingerprint != session.last_digest or session.last_response is None:
                raise ProtocolError("conflicting or unfinished operation retry")
            return copy.deepcopy(session.last_response)
        if seq != session.last_seq + 1:
            raise ProtocolError("out-of-order event; a new handshake is required")
        session.last_seq, session.last_operation, session.last_digest = seq, operation, fingerprint
        session.last_response = None
        return None

    def response(self, player, msg, commands, *, hello=False):
        session = self.sessions[player]
        envelope = {"protocol": self.protocol, "player": player, "admission_epoch": self.epoch,
                    "session_id": session.session_id, "seq": msg["seq"], "operation_id": msg["operation_id"]}
        response = {**envelope, "ack": "ACK", "commands": [
            {**command, **envelope, "command_index": index} for index, command in enumerate(commands, 1)]}
        if hello:
            response["admission"] = {"state": "admitted", "client_nonce": session.nonce, **session.metadata}
        else:
            session.last_response = copy.deepcopy(response)
        return response


def nack(msg, reason, *, pending=False, protocol="slink-control-v1"):
    return {"protocol": protocol, "player": msg.get("player"), "ack": "NACK",
            "admission_epoch": msg.get("admission_epoch"), "session_id": msg.get("session_id"),
            "seq": msg.get("seq"), "operation_id": msg.get("operation_id"),
            "admission": {"state": "contract_pending" if pending else "rejected", "reason": reason,
                          "client_nonce": msg.get("client_nonce")}, "commands": []}
