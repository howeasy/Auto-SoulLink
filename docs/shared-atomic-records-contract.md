# Atomic component records in ProtocolJournal

This additive storage API keeps component documents in the existing journal
transaction alongside the state snapshot, semantic event, both outboxes and
validated command ACKs. It performs no cartridge/network I/O, grants no execution
authority and does not activate a production generation binding.

The first caller is the paired trade coordinator. Larger prepared/verified
transaction data can remain individually addressable after completion instead
of accumulating inside the main runtime snapshot.

## Write and read interfaces

ProtocolJournal.commit accepts an optional records sequence:

    records=[{
        "namespace": "paired-trade",
        "key": transaction_id,
        "value": complete_versioned_document,
    }]

Each namespace is1–64 characters matching a lowercase identifier with dots,
dashes or underscores. Keys are32 lowercase hexadecimal characters. A commit
contains at most128 records, no duplicate namespace/key pair, and at most the
existing4 MiB JSON limit across its complete record batch.

Every record revision is inserted, never overwritten or deleted. The revision
equals the state snapshot revision of the same committed transition.
Optimistic state revision checks therefore cover record writes as well.

record(namespace, key) returns a detached RecordSnapshot(revision, value), or
None when absent. record_history(namespace, key, after_revision=0, limit=128)
returns a bounded ascending list with the same checked objects.
Reads validate canonical encoding, stored SHA-256, capability binding and that
no record is newer than the current state snapshot.

Exact semantic operation replay returns the original event receipt without
appending another record or command. A failed ACK, outbox-capacity check, record
insert or SQLite commit rolls back all parts of the transition. If commit returns
uncertainly after becoming durable, inspect the original semantic event; do not
mint another operation to infer or repeat its effect.

## Compatibility boundary

Fresh/base journals retain the original run_id and contract_hash metadata.
On the first committed record write, the same atomic transaction adds the
atomic_records=v1 capability marker. This implementation accepts that exact
optional marker; unknown values are refused.

Older implementations require exactly the original metadata dictionary and
will refuse to reopen a record-enabled database. This is not protection against
an already-open older writer. Mixed-version concurrent writers remain unsupported;
the runtime must own its writer/version selection. The coordinator also uses an
explicit aggregate schema that the old staged-rule loader cannot adopt.

Existing callers that omit records retain their existing state/event/outbox
semantics. The storage addition does not make legacy runtime delivery durable,
migrate a rule state, release a hold or certify a native save.

## Evidence

tests/unit/test_protocol_records.py runs actual SQLite reopen, historical reads,
hash/capability corruption, invalid writes, revision/outbox/record rollback and
an exception immediately after commit. The original journal, dispatcher,
Gen1 durable receiver, identity and paired-recovery tests are also exercised
alongside the new coordinator. These are storage/model proofs, not live
cartridge or production-control qualification.
