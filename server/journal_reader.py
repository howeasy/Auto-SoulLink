"""Read an existing journal snapshot without initializing, repairing or migrating it."""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from server.protocol_journal import (
    APPLICATION_ID,
    MAX_JSON_BYTES,
    SCHEMA_VERSION,
    JournalError,
    Snapshot,
    _decode,
)


@dataclass(frozen=True)
class JournalRead:
    run_id: str
    contract_hash: str
    snapshot: Snapshot


def read_journal(path, *, run_id=None, contract_hash=None):
    path = Path(path).resolve()
    if not path.is_file():
        raise JournalError("existing durable journal required")
    try:
        db = sqlite3.connect(path.as_uri()+"?mode=ro", uri=True, isolation_level=None, timeout=2.5)
    except sqlite3.Error as error:
        raise JournalError("durable journal could not be opened for reading") from error
    try:
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")
        if (db.execute("PRAGMA application_id").fetchone()[0] != APPLICATION_ID
                or db.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION):
            raise JournalError("unsupported durable journal; no initialization was attempted")
        rows = db.execute("SELECT name,value FROM metadata LIMIT 5").fetchall()
        metadata = dict(rows)
        if set(metadata) not in ({"run_id", "contract_hash"}, {"run_id", "contract_hash", "atomic_records"}):
            raise JournalError("unsupported journal metadata")
        if metadata.get("atomic_records", "v1") != "v1":
            raise JournalError("unsupported atomic record schema")
        if not re.fullmatch(r"[0-9a-f]{32}", metadata["run_id"]) or not re.fullmatch(r"[0-9a-f]{64}", metadata["contract_hash"]):
            raise JournalError("invalid journal run/contract identity")
        if (run_id is not None and metadata["run_id"] != run_id
                or contract_hash is not None and metadata["contract_hash"] != contract_hash):
            raise JournalError("journal belongs to a different run/contract")
        row = db.execute("SELECT revision,length(body) FROM snapshot WHERE singleton=1").fetchone()
        if row is None or type(row[0]) is not int or not 0 <= row[0] <= 2**53-1 or not 0 < row[1] <= MAX_JSON_BYTES:
            raise JournalError("valid committed journal snapshot required")
        body, digest = db.execute("SELECT body,digest FROM snapshot WHERE singleton=1").fetchone()
        return JournalRead(metadata["run_id"], metadata["contract_hash"], Snapshot(row[0], _decode(body, digest)))
    except sqlite3.Error as error:
        raise JournalError("durable journal could not be read") from error
    finally:
        db.close()
