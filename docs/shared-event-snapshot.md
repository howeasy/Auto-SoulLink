# Checked event snapshots

`ProtocolJournal.event_snapshot(player, operation_id)` returns `None` when that
exact event is absent, or a frozen `EventSnapshot` dataclass with these fields:

| Field | Type | Meaning |
| --- | --- | --- |
| `revision` | `int` | The event's committed state revision |
| `request` | `dict` | The complete stored request, freshly decoded |
| `result` | `dict` | The complete stored result, freshly decoded |
| `command_ids` | `tuple[str, ...]` | All commands originating at this event, in insertion order, including acknowledged commands |

Both input identifiers are validated. Reads check request and result SHA-256
digests, canonical JSON encoding and shared document bounds. The event revision
must be an integer from 1 through the current committed snapshot revision, which
must itself be a nonnegative integer. A missing snapshot or invalid stored
command identifier refuses with `JournalError`. The event and revision ceiling
are selected together; the separate command lookup reads the immutable origin
association established by the event's atomic commit.

Each call decodes new dictionaries. They are mutable for caller convenience but
detached from journal storage and other reads; mutating them commits nothing.
The dataclass fields themselves are frozen. No schema migration is needed.

This API is evidence retrieval only. It neither validates a new caller request
as a retry nor grants execution authority. Existing
`event(player, operation_id, request)` retains its semantic replay check and
refuses reuse of an operation ID with different request content. Generation
adapters must still validate event provenance and their own receipt semantics.
They may retain an operation reference instead of another complete request copy.

The API does not decode or validate the entire current state document, nor the
bodies of originating commands. Use the corresponding checked state/command
reads when those contents are needed.

Regression coverage lives in `tests/unit/test_protocol_event_snapshot.py`:
found/missing reads, detached mutation, no writes, malformed and corrupted
documents and hashes, revision bounds, command identifiers, acknowledged command
retention, reopen, and unchanged semantic replay refusal.
