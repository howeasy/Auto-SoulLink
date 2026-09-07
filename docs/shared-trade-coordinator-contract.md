# Journal-backed paired trade coordinator

server/trade_coordinator.py is a generation-neutral coordinator composed with
ProtocolJournal and IdentityRegistry. It operates on detached state and validated
policy outputs. It has no emulator, transport, UI renderer or frame actuator.
The production Gen1 dispatcher/client remains unbound to this component.

## State and publication

The explicit slink-coordinated-state-v1 aggregate contains rules, identities,
active_trade and components. initial_state is a pure constructor; the runtime
must supply authoritative bootstrap/reconciliation. It must not adopt raw HELLO
party observations as already committed rule history.

Each complete transaction is a versioned paired-trade record in the same SQLite
journal. Every phase revision remains available through record_history. The
main aggregate retains only the active transaction ID. State, record, event,
both command outboxes and any validated ACK publish together.

The normal phase sequence is:

    offered → accepted → preparing → both_prepared → commit_persisted
      → commit_dispatched → both_applied → both_verified → link_committed

Offers have a persisted five-minute pre-acceptance deadline based on an
independent wall-clock input. Clock rollback/failure refuses transitions.
Accepted preparation does not acquire a second implicit expiry deadline.

COMMIT and both native commit outboxes are stored atomically before any delivery
can be authorized. A dispatch observation is supplied by the transport owner;
it does not establish peer receipt or application. Validated native application
also establishes that dispatch occurred when a crash lost the transport record.
No timer or missing party slot can manufacture application or verification.

Applied evidence alone does not ACK a physical command. Each endpoint's
independently verified native/save result is persisted with that command's ACK.
IdentityRegistry.migrate_many and the staged rule callback run only after both
verified results exist. Their ownership/rule changes and both native release
commands commit in one transaction. Finalization replay creates neither another
migration nor another release command.

## Required policy boundary

The constructor requires all policy callbacks. A JSON field is not authority:
authorize receives the runtime's private owner/authority object separately from
the event payload. Authorization runs even before exact event replay and before
returning a stored command for delivery.

| Callback | Required responsibility |
| --- | --- |
| authorize | Current private connection/operation ownership, admission, freshness, holds and appropriate recovery authority. |
| offer | Construct a TradeProposal only for one live linked pair, distinct physical instances, party locations, exact blobs/keys/slots and compatible admitted cartridges. |
| prompt / prepare | Produce cartridge-specific, versioned command payloads from the persisted proposal. |
| decision | Validate the actual native partner decision and its durable receipt. |
| ready | Independently validate physical preparation and return PreparedTrade bound to the exact proposal, context and selected physical digest. |
| commit | Revalidate fresh paired preparation/execution authority and return its evidence before COMMIT publication. |
| applied | Validate operation-bound native completion; equal before/after bytes are insufficient. |
| verified | Validate exact cartridge poststate plus save durability and return TradeVerification containing a scoped MigrationWitness and separate native/save receipts. |
| auxiliary | Validate retired prompt/prepare or abort/release closure with no unsupported physical-success inference. |
| finalize | Update only a detached rule document consistently with both verified ownership migrations; perform no external effects. |

Callbacks must be free of external writes/sends. Their inputs are detached, but
the coordinator cannot prevent a policy implementation from performing its own
I/O. Such effects would violate the transaction contract.

The generic coordinator also checks participant/instance uniqueness, existing
logical pair membership, scoped member resolution before offer/COMMIT/finalize,
prepared proposal/context/digest binding, exact stored command-body hashes,
command player/ID/sequence and verified source/destination migration identities.
Raw booleans cannot replace typed proposal, preparation or verification outputs.

## Cancellation, replay and recovery

Cancellation/decline/expiry before COMMIT creates abort commands and leaves
logical ownership unchanged. Pending old prompt/prepare commands remain durable;
the client must provide a validated retirement/closure ACK. An active prepare
cannot be consumed through a generic auxiliary ACK to bypass READY.

After COMMIT, cancellation is refused. Interruption retains the same physical
command IDs and marks transaction-local recovery required. The authority policy
must block ordinary delivery/continuation until it validates the recovery
procedure. The coordinator never grants native recovery frames or ordinary play.

The current model tests cover reconnect/server reopen with preserved physical
identity contexts. A reset/load/core replacement that changes those contexts
requires a separately qualified rebind/reconciliation path; it is not silently
adopted by a new HELLO or by an old trade receipt.

status returns detached persisted facts. It does not renew liveness, reconcile,
grant a hold release, acknowledge commands or manufacture completion. Clearing
the transaction-local recovery flag at authorized finalization does not replace
the runtime's paired liveness/recovery barrier.

Event replies are immutable acknowledgements of that event's committed phase.
Replaying an old offer ACK does not make its phase current again; use status
for a fresh persisted-state view.

## Qualification limits

Tests use real SQLite, shared logical identities and the RBY result policy across
all nine ordered R/B/Y pairings and both initiation directions. Identical-key/
identical-blob Yellow/Yellow remains two distinct logical/physical participants.
The tests include wrong/stale authority, moved preparation, simultaneous offers,
expiry/decline/cancel, one-sided recovery, rollback at prepare/COMMIT/finalize,
real process death immediately before/after COMMIT, conflicting evidence and
uncertain finalization replay.

Native completion, host holds and save-file proofs in these coordinator tests
are explicit synthetic policy fixtures. They do not establish an actual paired
cartridge trade, production admission, host interlocks or file durability.
The new component still needs the qualified generation policy, client staging/
receipt binding and complete production runtime integration.

Current focused coverage is43 coordinator cases and24 atomic-record cases.
Together with the original journal/dispatcher/Gen1 receiver checks,116 cases
passed after the scoped-revision validation fix. Full unit/integration:
4,015 passed and the same two Windows file-symlink privilege skips. Portable CI:
3,709 passed with308 explicit deferrals; release approval remains false.
