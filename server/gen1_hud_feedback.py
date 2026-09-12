"""Strict, durable Gen 1 HUD notices and their no-write receipts."""

from __future__ import annotations

import logging
import math
import re
import time
import unicodedata

from server.protocol import digest
from server.protocol_journal import JournalError

COMMAND_SCHEMA = "slink-gen1-hud-notice-v1"
RECEIPT_SCHEMA = "slink-gen1-hud-receipt-v1"
KINDS = frozenset({"link_pending", "link_formed", "violation", "clause_retry"})
SURFACES = frozenset({"hud", "prompt"})
BODY_FIELDS = frozenset(
    {"cmd", "schema", "kind", "surface", "text", "r", "g", "b", "frames", "issued_at", "expires_at"}
)
RECEIPT_FIELDS = frozenset(
    {"schema", "command_id", "command_sequence", "body_digest", "disposition", "frame"}
)
SOURCE_COMMANDS = frozenset({"hud_show", "msgbox", "gui_prompt"})
MAX_TEXT = 30
MAX_FRAMES = 600
TTL_SECONDS = 30
MAX_TTL_SECONDS = 120
MAX_INT = 2**53 - 1
log = logging.getLogger(__name__)


def _integer(value, low, high, label):
    if type(value) is not int or not low <= value <= high:
        raise JournalError("invalid Gen 1 HUD " + label)
    return value


def _wall_seconds(now):
    if not callable(now):
        raise JournalError("Gen 1 HUD wall clock must be callable")
    try:
        value = now()
    except Exception as error:
        raise JournalError("Gen 1 HUD wall clock failed") from error
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise JournalError("finite Gen 1 HUD wall clock required")
    return math.floor(value)


def compact_text(value):
    """Convert legacy display copy to one bounded printable ASCII line."""
    if not isinstance(value, str):
        raise JournalError("Gen 1 HUD text must be a string")
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    normalized = re.sub(r"\s+", " ", normalized).strip()
    prefixes = (
        r"\[(?:x|!)\]\s*",
        r"(?:species|gender|type|dupes?|area)\s+clause:\s*",
        r"(?:dead\s+zone|linked|dz|2nd):\s*",
    )
    changed = True
    while changed:
        changed = False
        for prefix in prefixes:
            cleaned = re.sub(r"^" + prefix, "", normalized, count=1, flags=re.IGNORECASE)
            if cleaned != normalized:
                normalized, changed = cleaned.strip(), True
    if not normalized:
        raise JournalError("Gen 1 HUD text must not be empty")
    return normalized if len(normalized) <= MAX_TEXT else normalized[: MAX_TEXT - 3].rstrip() + "..."


def validate_body(body):
    if (
        not isinstance(body, dict)
        or set(body) != BODY_FIELDS
        or body.get("cmd") != "hud_notice"
        or body.get("schema") != COMMAND_SCHEMA
        or body.get("kind") not in KINDS
        or body.get("surface") not in SURFACES
    ):
        raise JournalError("complete versioned Gen 1 HUD notice required")
    text = body.get("text")
    if (
        not isinstance(text, str)
        or not 1 <= len(text) <= MAX_TEXT
        or any(not 32 <= ord(char) <= 126 for char in text)
    ):
        raise JournalError("Gen 1 HUD text must be 1..30 printable ASCII characters")
    for field in ("r", "g", "b"):
        _integer(body.get(field), 0, 255, field + " channel")
    _integer(body.get("frames"), 1, MAX_FRAMES, "frame duration")
    issued = _integer(body.get("issued_at"), 0, MAX_INT, "issued time")
    expires = _integer(body.get("expires_at"), 0, MAX_INT, "expiry time")
    if not issued <= expires <= issued + MAX_TTL_SECONDS:
        raise JournalError("Gen 1 HUD expiry must be within 120 seconds of issue")
    return body


def build_notice(kind, surface, text, *, r, g, b, frames, now=time.time):
    """Build one strict notice with a deterministic injectable wall clock."""
    issued = _wall_seconds(now)
    body = {
        "cmd": "hud_notice",
        "schema": COMMAND_SCHEMA,
        "kind": kind,
        "surface": surface,
        "text": text,
        "r": r,
        "g": g,
        "b": b,
        "frames": frames,
        "issued_at": issued,
        "expires_at": issued + TTL_SECONDS,
    }
    return validate_body(body)


def project(command, *, kind, surface, text=None, now=time.time):
    """Project an explicitly classified legacy presentation command into a notice."""
    if not isinstance(command, dict) or command.get("cmd") not in SOURCE_COMMANDS:
        raise JournalError("eligible Gen 1 presentation command required")
    defaults = {
        "link_pending": (100, 180, 255, 300),
        "link_formed": (100, 255, 160, 300),
        "violation": (255, 80, 80, 360),
        "clause_retry": (255, 200, 60, 360),
    }
    if kind not in defaults:
        raise JournalError("explicit Gen 1 HUD notice purpose required")
    fallback = defaults[kind]

    def style(field, index, low, high):
        value = command.get(field, fallback[index])
        return value if type(value) is int and low <= value <= high else fallback[index]

    return build_notice(
        kind,
        surface,
        compact_text(command.get("text") if text is None else text),
        r=style("r", 0, 0, 255),
        g=style("g", 1, 0, 255),
        b=style("b", 2, 0, 255),
        frames=style("frames", 3, 1, MAX_FRAMES),
        now=now,
    )


def best_effort_notice(kind, surface, text, *, r, g, b, frames, now=time.time, source="explicit"):
    """Build one notice without allowing presentation failure to revoke its source event."""
    try:
        return build_notice(
            kind,
            surface,
            compact_text(text),
            r=r,
            g=g,
            b=b,
            frames=frames,
            now=now,
        )
    except Exception as error:
        log.warning(
            "dropping Gen 1 HUD notice kind=%s surface=%s source=%s: %s",
            kind,
            surface,
            source,
            error,
        )
        return None


def project_best_effort(command, *, kind, surface, text=None, now=time.time):
    """Project a legacy command, auditing and dropping only a malformed notice."""
    try:
        return project(command, kind=kind, surface=surface, text=text, now=now)
    except Exception as error:
        source = command.get("cmd") if isinstance(command, dict) else type(command).__name__
        log.warning(
            "dropping Gen 1 HUD notice kind=%s surface=%s source=%s: %s",
            kind,
            surface,
            source,
            error,
        )
        return None


def classify_captured(captured, *, linked, rejected, rejection_text=None, now=time.time):
    """Classify captured engine presentation commands from explicit rule outcomes."""
    if not isinstance(captured, dict) or set(captured) != {"a", "b"}:
        raise JournalError("complete captured Gen 1 engine outboxes required")
    feedback = {"a": [], "b": []}
    for player in ("a", "b"):
        if not isinstance(captured[player], list):
            raise JournalError("ordered captured Gen 1 engine outbox required")
        for command in captured[player]:
            source = command.get("cmd") if isinstance(command, dict) else None
            if source == "gui_prompt":
                kind, surface = "clause_retry", "prompt"
            elif source == "msgbox" and linked:
                kind, surface = "link_formed", "prompt"
            elif source in ("hud_show", "msgbox") and rejected:
                kind, surface = "violation", "prompt"
            elif source == "hud_show":
                kind, surface = "link_pending", "hud"
            else:
                continue  # Physical commands and every play_sound remain unprojected.
            detail = rejection_text if rejected and source in SOURCE_COMMANDS else None
            body = project_best_effort(
                command, kind=kind, surface=surface, text=detail, now=now
            )
            if body is not None:
                feedback[player].append(body)
    return coalesce(feedback)


def coalesce(feedback):
    """Drop stale pending-link copy when the same atomic batch also forms a link."""
    if not isinstance(feedback, dict) or set(feedback) != {"a", "b"}:
        raise JournalError("complete Gen 1 HUD feedback batch required")
    result = {}
    for player in ("a", "b"):
        if not isinstance(feedback[player], list):
            raise JournalError("ordered Gen 1 HUD feedback batch required")
        for body in feedback[player]:
            validate_body(body)
        formed = any(body["kind"] == "link_formed" for body in feedback[player])
        result[player] = [
            body
            for body in feedback[player]
            if not (formed and body["kind"] == "link_pending")
        ]
    return result


def append_after_physical(commands, feedback):
    """Append presentation only after every physical command for each recipient."""
    if (
        not isinstance(commands, dict)
        or not isinstance(feedback, dict)
        or set(commands) != {"a", "b"}
        or set(feedback) != {"a", "b"}
    ):
        raise JournalError("complete Gen 1 command and feedback batches required")
    result = {}
    for player in ("a", "b"):
        if not isinstance(commands[player], list) or not isinstance(feedback[player], list):
            raise JournalError("ordered Gen 1 command and feedback batches required")
    feedback = coalesce(feedback)
    for player in ("a", "b"):
        result[player] = [*commands[player], *feedback[player]]
    return result


def feedback_last(commands):
    """Stable-partition a compound commit so HUD notices never precede writes."""
    if not isinstance(commands, dict) or set(commands) != {"a", "b"}:
        raise JournalError("complete Gen 1 command batch required")
    result = {}
    for player in ("a", "b"):
        if not isinstance(commands[player], list):
            raise JournalError("ordered Gen 1 command batch required")
        if any(not isinstance(body, dict) for body in commands[player]):
            raise JournalError("Gen 1 command batch entries must be objects")
        notices = [body for body in commands[player] if body.get("cmd") == "hud_notice"]
        coalesced = coalesce({player: notices, ("b" if player == "a" else "a"): []})[player]
        result[player] = [
            body for body in commands[player] if body.get("cmd") != "hud_notice"
        ] + coalesced
    return result


def verify_receipt(command, receipt):
    """Verify an ACK for drawing, or intentionally expiring, one exact notice."""
    if not isinstance(command, dict) or not {"command_id", "command_sequence", "body"} <= set(command):
        raise JournalError("authoritative Gen 1 HUD command required")
    body = validate_body(command["body"])
    command_id = command.get("command_id")
    sequence = command.get("command_sequence")
    if not isinstance(command_id, str) or not re.fullmatch(r"[0-9a-f]{32}", command_id):
        raise JournalError("Gen 1 HUD receipt needs its command id")
    _integer(sequence, 1, MAX_INT, "command sequence")
    if (
        not isinstance(receipt, dict)
        or set(receipt) != RECEIPT_FIELDS
        or receipt.get("schema") != RECEIPT_SCHEMA
        or receipt.get("command_id") != command_id
        or receipt.get("command_sequence") != sequence
        or receipt.get("body_digest") != digest(body)
        or receipt.get("disposition") not in {"drawn", "expired"}
    ):
        raise JournalError("complete matching Gen 1 HUD receipt required")
    frame = receipt.get("frame")
    if receipt["disposition"] == "drawn":
        _integer(frame, 0, MAX_INT, "draw frame")
    elif frame != -1:
        raise JournalError("expired Gen 1 HUD receipt must use frame -1")
    return {"disposition": receipt["disposition"], "frame": frame}
