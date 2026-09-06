"""Session-bound, challenge/response liveness; never persisted or inferred from TCP.

Bindings validate connection ownership before calling open/answer. Both the server
and clients need watchdogs: this server-side fact cannot stop a disconnected host.
Old buffered answers expire from challenge ISSUE time, not their late arrival.
"""
from __future__ import annotations

import math
import secrets
import time

from server.paired_recovery import PLAYERS, _hex, _player
from server.protocol_journal import JournalError


class PairedLiveness:
    def __init__(self, *, timeout=2.0, clock=time.monotonic, new_nonce=None):
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
            raise JournalError("invalid liveness timeout")
        self.timeout = timeout
        self.clock = clock
        self.new_nonce = new_nonce or (lambda: secrets.token_hex(16))
        self._sessions = {}
        self._last_clock = None

    def _now(self):
        try:
            now = self.clock()
        except Exception as exc:
            self._sessions.clear()
            raise JournalError("monotonic liveness clock failed; all sessions revoked") from exc
        if (type(now) not in (int, float) or not math.isfinite(now) or now < 0
                or self._last_clock is not None and now < self._last_clock):
            self._sessions.clear()
            raise JournalError("monotonic liveness clock failed; all sessions revoked")
        self._last_clock = now
        for session in self._sessions.values():
            started = session["last_started"]
            if started is not None and now - started >= self.timeout:
                session["expired"] = True
        return now

    def open(self, player, session_id):
        _player(player)
        _hex(session_id, 32, "liveness session")
        self._now()
        if player in self._sessions and self._sessions[player]["session_id"] == session_id:
            raise JournalError("liveness reopen requires a newly admitted session")
        self._sessions[player] = {"session_id": session_id, "pending": None,
                                  "last_started": None, "last_nonce": None, "expired": False}

    def close(self, player, session_id):
        _player(player)
        session = self._sessions.get(player)
        if session is None or session["session_id"] != session_id:
            return False
        del self._sessions[player]
        return True

    def challenge(self, player, session_id):
        _player(player)
        now = self._now()
        session = self._sessions.get(player)
        if session is None or session["session_id"] != session_id:
            raise JournalError("liveness challenge has no current session")
        if session["expired"]:
            raise JournalError("liveness expired; fresh admission and paired reconciliation required")
        pending = session["pending"]
        if pending is None or now - pending["issued"] >= self.timeout:
            nonce = _hex(self.new_nonce(), 32, "liveness challenge")
            if nonce == session["last_nonce"]:
                raise JournalError("liveness nonce repeated")
            session["last_nonce"] = nonce
            session["pending"] = {"nonce": nonce, "issued": now}
        return {"session_id": session_id, "challenge": session["pending"]["nonce"]}

    def answer(self, player, session_id, challenge):
        _player(player)
        now = self._now()
        session = self._sessions.get(player)
        if session is None or session["session_id"] != session_id or session["expired"]:
            return False
        pending = session["pending"]
        if pending is None or challenge != pending["nonce"]:
            return False
        session["pending"] = None
        if now - pending["issued"] >= self.timeout:
            return False
        session["last_started"] = pending["issued"]
        return True

    def status(self):
        now = self._now()
        players = {}
        for player in PLAYERS:
            session = self._sessions.get(player)
            started = session["last_started"] if session else None
            players[player] = {"connected_session": session is not None,
                               "roundtrip_age_seconds": None if started is None else now - started,
                               "requires_readmission": bool(session and session["expired"]),
                               "live": started is not None and not session["expired"] and now - started < self.timeout}
        return {"timeout_seconds": self.timeout, "players": players,
                "paired_live": all(player["live"] for player in players.values())}
