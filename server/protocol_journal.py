"""Generation-independent atomic state/event/command storage.

No cartridge or network I/O occurs here. A caller must stage a rule transition,
commit its complete state and both players' commands, THEN expose a response.
Physical command receipts must be validated by the executor/coordinator before
acknowledge is called. This primitive does not make the existing dispatcher durable.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
import sqlite3
from dataclasses import dataclass
from pathlib import Path

APPLICATION_ID = 0x534C504A  # SLPJ; never initialize over an unrelated SQLite DB.
SCHEMA_VERSION = 1
MAX_JSON_BYTES = 4 * 1024 * 1024
ENVELOPE_RESERVE = 2048


class JournalError(RuntimeError):
    pass


class RevisionConflict(JournalError):
    pass


def _identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{32}", value):
        raise JournalError("journal identifiers must be 32 lowercase hexadecimal characters")
    return value


def _player(value):
    if value not in ("a", "b"):
        raise JournalError("invalid journal player")
    return value


def _encode(value, *, limit=MAX_JSON_BYTES):
    if not isinstance(value, dict):
        raise JournalError("journal documents must be JSON objects")
    try:
        pending, visited = [(value, 0)], 0
        while pending:
            item, depth = pending.pop()
            visited += 1
            if depth > 32 or visited > 100000:
                raise JournalError("journal JSON exceeds structure bounds")
            if isinstance(item, dict):
                if any(not isinstance(key, str) for key in item):
                    raise JournalError("journal object keys must be strings")
                pending.extend((entry, depth + 1) for entry in item.values())
                pending.extend((key, depth + 1) for key in item)
            elif isinstance(item, list):
                pending.extend((entry, depth + 1) for entry in item)
            elif isinstance(item, str):
                if len(item.encode("utf-8")) > 1024 * 1024:
                    raise JournalError("journal string exceeds byte bound")
            elif type(item) in (int, float):
                if not -(2**53 - 1) <= item <= 2**53 - 1:
                    raise JournalError("journal number exceeds exact range")
            elif item is not None and type(item) is not bool:
                raise JournalError("unsupported journal value")
        text = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
        raw = text.encode("ascii")
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise JournalError("invalid journal JSON") from exc
    if len(raw) > limit:
        raise JournalError("journal document exceeds the byte limit")
    return text, hashlib.sha256(raw).hexdigest()


def _decode(text, expected_hash):
    if hashlib.sha256(text.encode("ascii")).hexdigest() != expected_hash:
        raise JournalError("journal document checksum mismatch; recovery required")
    try:
        value = json.loads(text)
    except ValueError as exc:
        raise JournalError("invalid stored journal JSON") from exc
    # Validate representation and canonical encoding as well as the digest.
    canonical, _ = _encode(value)
    if canonical != text:
        raise JournalError("journal contains a noncanonical document")
    return value


@dataclass(frozen=True)
class Snapshot:
    revision: int
    state: dict


@dataclass(frozen=True)
class EventReceipt:
    revision: int
    result: dict
    command_ids: tuple[str, ...]


@dataclass(frozen=True)
class RecordSnapshot:
    revision: int
    value: dict


def _record_key(namespace, key):
    if not isinstance(namespace, str) or not re.fullmatch(r"[a-z][a-z0-9_.-]{0,63}", namespace):
        raise JournalError("invalid record namespace")
    _identifier(key)


class ProtocolJournal:
    def __init__(self, path, *, contract_hash, run_id=None, max_pending=4096):
        if run_id is not None:
            _identifier(run_id)
        if not isinstance(contract_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", contract_hash):
            raise JournalError("a complete contract digest is required")
        if type(max_pending) is not int or not 1 <= max_pending <= 4096:
            raise JournalError("invalid pending-command bound")
        self.path = Path(path)
        self.max_pending = max_pending
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.path, isolation_level=None, timeout=2.5)
        self._db.row_factory = sqlite3.Row
        try:
            version = self._db.execute("PRAGMA user_version").fetchone()[0]
            app = self._db.execute("PRAGMA application_id").fetchone()[0]
            tables = self._db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            if (app, version) != (APPLICATION_ID, SCHEMA_VERSION) and (app or version or tables):
                raise JournalError("unsupported journal database; no migration or reset was performed")
            if self._db.execute("PRAGMA journal_mode=WAL").fetchone()[0].lower() != "wal":
                raise JournalError("journal filesystem does not support WAL")
            self._db.execute("PRAGMA synchronous=FULL")
            self._db.execute("PRAGMA foreign_keys=ON")
            self._db.execute("BEGIN IMMEDIATE")
            self._db.execute("CREATE TABLE IF NOT EXISTS metadata (name TEXT PRIMARY KEY, value TEXT NOT NULL)")
            self._db.execute("""CREATE TABLE IF NOT EXISTS snapshot (
                singleton INTEGER PRIMARY KEY CHECK(singleton=1), revision INTEGER NOT NULL,
                body TEXT NOT NULL, digest TEXT NOT NULL)""")
            self._db.execute("""CREATE TABLE IF NOT EXISTS events (
                player TEXT NOT NULL CHECK(player IN ('a','b')), operation_id TEXT NOT NULL,
                request TEXT NOT NULL, request_digest TEXT NOT NULL, revision INTEGER NOT NULL,
                result TEXT NOT NULL, result_digest TEXT NOT NULL,
                PRIMARY KEY(player,operation_id))""")
            self._db.execute("""CREATE TABLE IF NOT EXISTS commands (
                position INTEGER PRIMARY KEY AUTOINCREMENT, command_id TEXT NOT NULL UNIQUE,
                player TEXT NOT NULL CHECK(player IN ('a','b')), origin_player TEXT NOT NULL,
                origin_operation TEXT NOT NULL, body TEXT NOT NULL, digest TEXT NOT NULL,
                outcome TEXT CHECK(outcome IN ('ACK','NACK')), receipt TEXT, receipt_digest TEXT,
                FOREIGN KEY(origin_player,origin_operation) REFERENCES events(player,operation_id))""")
            self._db.execute("CREATE INDEX IF NOT EXISTS command_delivery ON commands(player,outcome,position)")
            self._db.execute("""CREATE TABLE IF NOT EXISTS sessions (
                client_nonce TEXT PRIMARY KEY, player TEXT NOT NULL CHECK(player IN ('a','b')),
                admission_epoch TEXT NOT NULL, session_id TEXT NOT NULL UNIQUE)""")
            self._db.execute("""CREATE TABLE IF NOT EXISTS records (
                namespace TEXT NOT NULL, record_key TEXT NOT NULL, revision INTEGER NOT NULL,
                body TEXT NOT NULL, digest TEXT NOT NULL,
                PRIMARY KEY(namespace,record_key,revision))""")
            actual = dict(self._db.execute("SELECT name,value FROM metadata"))
            run_id = run_id or actual.get("run_id") or secrets.token_hex(16)
            _identifier(run_id)
            expected = {"run_id": run_id, "contract_hash": contract_hash}
            if "atomic_records" in actual:
                expected["atomic_records"] = "v1"
            if actual and actual != expected:
                raise JournalError("journal belongs to a different run or cartridge contract")
            if not actual:
                self._db.executemany("INSERT INTO metadata VALUES (?,?)", expected.items())
            self.run_id = run_id
            self._db.execute(f"PRAGMA application_id={APPLICATION_ID}")
            self._db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            self._db.commit()
            if self._db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise JournalError("journal integrity check failed")
        except Exception:
            self._db.rollback()
            self._db.close()
            raise

    def close(self):
        self._db.close()

    def register_session(self, player, client_nonce, admission_epoch):
        """Consume a validated HELLO nonce durably, including across server restarts."""
        _player(player)
        _identifier(client_nonce)
        _identifier(admission_epoch)
        session_id = secrets.token_hex(16)
        try:
            self._db.execute("BEGIN IMMEDIATE")
            if self._db.execute("SELECT 1 FROM sessions WHERE client_nonce=?", (client_nonce,)).fetchone():
                raise JournalError("client session nonce was already used")
            self._db.execute("INSERT INTO sessions VALUES (?,?,?,?)", (client_nonce, player, admission_epoch, session_id))
            self._db.commit()
        except Exception:
            self._db.rollback()
            raise
        return session_id

    def bootstrap(self, state):
        """Seed an empty journal once. Existing authoritative state is never replaced."""
        body, fingerprint = _encode(state)
        try:
            self._db.execute("BEGIN IMMEDIATE")
            row = self._db.execute("SELECT * FROM snapshot WHERE singleton=1").fetchone()
            if row is None:
                self._db.execute("INSERT INTO snapshot VALUES (1,0,?,?)", (body, fingerprint))
            self._db.commit()
        except Exception:
            self._db.rollback()
            raise
        return self.snapshot()

    def snapshot(self):
        row = self._db.execute("SELECT * FROM snapshot WHERE singleton=1").fetchone()
        if row is None:
            raise JournalError("journal has not been bootstrapped")
        return Snapshot(row["revision"], _decode(row["body"], row["digest"]))

    def event(self, player, operation_id, request):
        _player(player)
        _identifier(operation_id)
        _text, fingerprint = _encode(request)
        row = self._db.execute("SELECT * FROM events WHERE player=? AND operation_id=?", (player, operation_id)).fetchone()
        if row is None:
            return None
        _decode(row["request"], row["request_digest"])
        if fingerprint != row["request_digest"]:
            raise JournalError("operation ID was reused with different semantic content")
        ids = tuple(r[0] for r in self._db.execute(
            "SELECT command_id FROM commands WHERE origin_player=? AND origin_operation=? ORDER BY position", (player, operation_id)))
        return EventReceipt(row["revision"], _decode(row["result"], row["result_digest"]), ids)

    def commit(self, player, operation_id, request, *, expected_revision, state, commands, result,
               acknowledgements=(), records=()):
        """Commit a staged transition plus BOTH outboxes, or change nothing.

        A complete retry returns the previous receipt. A different payload under
        the same operation ID is a conflict, even after every command was ACKed.
        """
        _player(player)
        _identifier(operation_id)
        if type(expected_revision) is not int or expected_revision < 0:
            raise JournalError("invalid expected state revision")
        request_text, request_hash = _encode(request)
        state_text, state_hash = _encode(state)
        result_text, result_hash = _encode(result)
        if not isinstance(records, (tuple, list)) or len(records) > 128:
            raise JournalError("bounded atomic record writes required")
        record_rows, record_keys, record_bytes = [], set(), 0
        for record in records:
            if not isinstance(record, dict) or set(record) != {"namespace", "key", "value"}:
                raise JournalError("invalid atomic record write")
            namespace, key = record["namespace"], record["key"]
            _record_key(namespace, key)
            if (namespace, key) in record_keys:
                raise JournalError("duplicate record write in one transition")
            record_keys.add((namespace, key))
            body, fingerprint = _encode(record["value"])
            record_bytes += len(body.encode("ascii")) + len(namespace) + len(key) + 128
            if record_bytes > MAX_JSON_BYTES:
                raise JournalError("atomic record batch exceeds the byte limit")
            record_rows.append((namespace, key, expected_revision+1, body, fingerprint))
        if not isinstance(commands, dict) or set(commands) != {"a", "b"}:
            raise JournalError("both command outboxes are required")
        staged = []
        for recipient in ("a", "b"):
            rows = commands[recipient]
            if not isinstance(rows, list) or len(rows) > self.max_pending:
                raise JournalError("invalid command batch")
            for command in rows:
                if (not isinstance(command, dict) or not isinstance(command.get("cmd"), str)
                        or not command["cmd"] or "command_id" in command):
                    raise JournalError("invalid staged command")
                body, fingerprint = _encode(command, limit=MAX_JSON_BYTES - ENVELOPE_RESERVE - 512)
                staged.append((secrets.token_hex(16), recipient, player, operation_id, body, fingerprint))
        try:
            self._db.execute("BEGIN IMMEDIATE")
            existing = self.event(player, operation_id, request)
            if existing is not None:
                self._db.rollback()
                return existing
            current = self.snapshot()
            if current.revision != expected_revision:
                raise RevisionConflict("another state transition committed; reload before dispatching")
            for acknowledgement in acknowledgements:
                self._acknowledge(**acknowledgement)
            pending = self._db.execute("SELECT count(*) FROM commands WHERE outcome IS NULL").fetchone()[0]
            if pending + len(staged) > self.max_pending:
                raise JournalError("durable command outbox is full")
            revision = expected_revision + 1
            self._db.execute("UPDATE snapshot SET revision=?,body=?,digest=? WHERE singleton=1",
                             (revision, state_text, state_hash))
            self._db.execute("INSERT INTO events VALUES (?,?,?,?,?,?,?)",
                             (player, operation_id, request_text, request_hash, revision, result_text, result_hash))
            self._db.executemany("""INSERT INTO commands
                (command_id,player,origin_player,origin_operation,body,digest) VALUES (?,?,?,?,?,?)""", staged)
            if record_rows:
                # Older journal implementations require exactly the original
                # two metadata fields and will refuse to reopen this database.
                marker = self._db.execute("SELECT value FROM metadata WHERE name='atomic_records'").fetchone()
                if marker is not None and marker[0] != "v1":
                    raise JournalError("unsupported atomic record capability")
                self._db.execute("INSERT OR IGNORE INTO metadata VALUES ('atomic_records','v1')")
                self._db.executemany("INSERT INTO records VALUES (?,?,?,?,?)", record_rows)
            self._db.commit()
        except Exception:
            self._db.rollback()
            raise
        return EventReceipt(revision, json.loads(result_text), tuple(row[0] for row in staged))

    def record(self, namespace, key):
        """Latest checked component record; every prior revision is retained."""
        _record_key(namespace, key)
        row = self._db.execute(
            "SELECT * FROM records WHERE namespace=? AND record_key=? ORDER BY revision DESC LIMIT 1",
            (namespace, key)).fetchone()
        if row is None:
            return None
        current = self._record_revision_limit(namespace, key)
        return self._checked_record(row, current)

    @staticmethod
    def _checked_record(row, current):
        if type(row["revision"]) is not int or not 1 <= row["revision"] <= current:
            raise JournalError("component record has an invalid committed revision")
        return RecordSnapshot(row["revision"], _decode(row["body"], row["digest"]))

    def _record_revision_limit(self, namespace, key):
        # Validate the entire scoped history before pagination can hide a bad
        # revision. SQLite INTEGER affinity still permits REAL or TEXT values.
        bounds = self._db.execute("""SELECT MAX(revision) AS latest,
            MAX(CASE WHEN typeof(revision) != 'integer' OR revision < 1 THEN 1 ELSE 0 END) AS invalid
            FROM records WHERE namespace=? AND record_key=?""", (namespace, key)).fetchone()
        if bounds["invalid"]:
            raise JournalError("component record has an invalid committed revision")
        current = self.snapshot().revision
        if type(current) is not int or current < 0:
            raise JournalError("invalid committed state revision")
        if bounds["latest"] is not None:
            marker = self._db.execute("SELECT value FROM metadata WHERE name='atomic_records'").fetchone()
            if marker is None or marker[0] != "v1":
                raise JournalError("atomic record capability marker is missing or unsupported")
            if bounds["latest"] > current:
                raise JournalError("component record is newer than its state snapshot")
        return current

    def record_history(self, namespace, key, *, after_revision=0, limit=128):
        """Bounded checked audit reads; never remove old component revisions."""
        _record_key(namespace, key)
        if (type(after_revision) is not int or after_revision < 0
                or type(limit) is not int or not 1 <= limit <= 128):
            raise JournalError("invalid record history bounds")
        rows = self._db.execute(
            "SELECT * FROM records WHERE namespace=? AND record_key=? AND revision>? ORDER BY revision LIMIT ?",
            (namespace, key, after_revision, limit)).fetchall()
        current = self._record_revision_limit(namespace, key)
        return [self._checked_record(row, current) for row in rows]

    def pending_ids(self, player):
        """Complete bounded obligation index, independent of delivery pagination.

        Use command() for checked bodies. A transport batch can omit obligations
        due to its count/byte limit and must not be used as a completion proof.
        """
        _player(player)
        rows = self._db.execute(
            "SELECT command_id FROM commands WHERE player=? AND outcome IS NULL ORDER BY position LIMIT 4097",
            (player,)).fetchall()
        if len(rows) > 4096:
            raise JournalError("durable obligation index exceeds the journal bound")
        return tuple(_identifier(row["command_id"]) for row in rows)

    def pending(self, player, *, limit=128, max_bytes=MAX_JSON_BYTES):
        _player(player)
        if type(limit) is not int or not 1 <= limit <= 128 or type(max_bytes) is not int or not ENVELOPE_RESERVE <= max_bytes <= MAX_JSON_BYTES:
            raise JournalError("invalid delivery bounds")
        batch, size = [], ENVELOPE_RESERVE
        for row in self._db.execute("SELECT * FROM commands WHERE player=? AND outcome IS NULL ORDER BY position LIMIT ?", (player, limit)):
            cost = len(row["body"].encode("ascii")) + 512
            if size + cost > max_bytes:
                if not batch:
                    raise JournalError("first pending command cannot fit the requested frame bound")
                break
            payload = _decode(row["body"], row["digest"])
            batch.append({**payload, "command_id": row["command_id"], "command_sequence": row["position"]})
            size += cost
        return batch

    def command(self, player, command_id):
        _player(player)
        _identifier(command_id)
        row = self._db.execute("SELECT * FROM commands WHERE command_id=? AND player=?", (command_id, player)).fetchone()
        if row is None:
            raise JournalError("unknown command or wrong player")
        receipt = None if row["outcome"] is None else _decode(row["receipt"], row["receipt_digest"])
        return {"command_id": command_id, "command_sequence": row["position"],
                "body": _decode(row["body"], row["digest"]), "outcome": row["outcome"], "receipt": receipt}

    def _acknowledge(self, player, command_id, outcome, receipt):
        _player(player)
        _identifier(command_id)
        if outcome not in ("ACK", "NACK") or not isinstance(receipt, dict) or not receipt:
            raise JournalError("an explicit outcome and verified receipt are required")
        text, fingerprint = _encode(receipt)
        existing = self.command(player, command_id)
        if existing["outcome"] is not None:
            if existing["outcome"] != outcome or _encode(existing["receipt"])[1] != fingerprint:
                raise JournalError("conflicting command receipt")
            return False
        self._db.execute("UPDATE commands SET outcome=?,receipt=?,receipt_digest=? WHERE command_id=?",
                         (outcome, text, fingerprint, command_id))
        return True

    def acknowledge(self, player, command_id, outcome, receipt):
        """Persist a coordinator-validated physical/UI receipt; never infer one."""
        try:
            self._db.execute("BEGIN IMMEDIATE")
            changed = self._acknowledge(player, command_id, outcome, receipt)
            self._db.commit()
            return changed
        except Exception:
            self._db.rollback()
            raise
