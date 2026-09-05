# Shared runtime foundation

These interfaces separate reusable protocol/storage mechanics from cartridge policy.
The shared handoff itself does not activate a new generation binding; references to
the current RBY binding describe the separate, in-progress Gen1 worktree.
The journal and staged-state components are tested primitives; the production dispatcher
does not yet use them for durable event/command delivery. Existing AP and other-generation
bindings keep their current behavior until explicitly integrated and validated.

## Module boundaries

| Shared module | Responsibility | Cartridge-specific caller |
| --- | --- | --- |
| `lua/connector.lua` | Bounded TCP framing, FIFO/backpressure and exact partial-I/O offsets | Each client selects connection/reconnect policy |
| `lua/json_codec.lua` | Bounded JSON encoding/decoding, Unicode, nulls and explicit object/array kinds | No cartridge knowledge |
| `lua/wire_protocol.lua` | Decode complete command arrays without filtering malformed entries | Domain validators check command meaning |
| `lua/command_validation.lua` | Integer, text and contiguous-array shape checks | `gen1_commands.lua` supplies RBY commands/keys/codecs |
| `lua/platform_identity.lua` | OS-backed session identifiers through the BizHawk .NET host | Fails if the required API is unavailable |
| `lua/platform_storage.lua` | Exclusive file ownership, UTF-8/SHA256, flush and atomic replacement | Caller selects an isolated local path |
| `lua/state_store.lua` | Bound, checksummed/revisioned documents with publication readback | No cartridge knowledge |
| `lua/client_journal.lua` | Durable semantic outbox, command inbox and receipt/floor bookkeeping | Executors provide verified outcomes |
| `lua/command_executor.lua` | Persist preparation, classify recovery, execute and store verified receipts | Cartridge callbacks supply all memory policy |
| `lua/client_session.lua` | Session state, sequence/operation envelopes and response validation | `gen1_session.lua` supplies RBY ROM/profile/capability checks |
| `server/protocol.py` | Strict wire JSON, connection ownership, epochs and session-local retries | `gen1_admission.py` supplies the RBY HELLO validator |
| `server/protocol_journal.py` | Atomic state + event + both-player command outboxes | Coordinator supplies staged state and verified receipts |
| `server/durable_dispatch.py` | Stage rules and commit events, both outboxes and validated receipts together | Binding supplies event/physical receipt validators |
| `server/binary_codec.py` | Explicit binary values in JSON, with size and SHA-256 | Adapter supplies expected binary layout size |
| `server/staged_state.py` | Clone/restore rules and memorial history without filesystem writes | `gen1_staged_state.py` restricts eligibility to vanilla RBY |

## Session contracts

`SessionGate(protocol=..., hello_validator=...)` validates common HELLO fields before
calling `hello_validator(contract, player, message, saved_identity)`. The callback must
validate the actual cartridge, save identity, codec and capabilities and return trusted
metadata. It must not mutate rule state or execute commands.

The gate owns a shared admission epoch and separate player session IDs. The connection
owner is a private Python object; no JSON field grants ownership. Only the current owner
may send events or close that player's session. Contract change revokes both sessions.

`client_session.new(options)` requires `player`, `protocol`, `read_metadata` and
`metadata_matches`; `variant` and `new_nonce` are optional adapter hooks. The lifecycle is
`begin`, `decorate`, successful queueing, `queued`, `receive`, and `revoke`. Queue refusal
must not advance a delivery sequence. Use `wire_protocol.parse_commands` and the same
`json_codec` module instance so JSON kind/null identity is preserved.

Current production wire v1 uses `operation_id = client_nonce:sequence`. This is session-local and
is **not** a durable operation identity. The journal expects a separate 32-character
lowercase hexadecimal identifier. The planned durable protocol revision will generate
and persist that identifier once per semantic observation, keeping it across reconnects;
epoch/session/sequence identify delivery attempts. The shared session engines now expose
`durable_ids` and an optional server nonce registry for that revision; the RBY production
binding still uses v1. Do not hash or reinterpret v1 IDs to
claim durable replay, and do not activate the journal with an implicit conversion.

## Journal contracts

Construct `ProtocolJournal(path, run_id=..., contract_hash=...)` on a supported local
filesystem. The caller owns database lifetime and run/contract selection. The database
is bound to both identities and refuses unrelated schemas or changed bindings.

- `bootstrap(state)` initializes an empty journal once; it never overwrites authoritative state.
- `snapshot()` returns a detached state document and its revision.
- `register_session(player, nonce, epoch)` consumes a nonce durably and returns a session ID.
- `event(player, operation_id, request)` returns a committed result for an exact retry;
  changed content under the same ID is a conflict.
- `commit(..., expected_revision=..., state=..., commands={a: [...], b: [...]}, result=...)`
  commits the new state, event result and both outboxes in one SQLite transaction.
  A competing state revision refuses the staged transition.
- Optional `acknowledgements` commit validated command receipts in that same state/event/outbox transaction.
- `pending(player)` returns a bounded FIFO batch without acknowledging or deleting it.
- `acknowledge(player, command_id, outcome, receipt)` persists an explicit ACK/NACK;
  exact retries are idempotent and conflicting receipts refuse.

Only expose a successful response after commit returns or a subsequent lookup proves
the operation committed. An I/O exception does not establish whether a commit happened.
The tests include process death before and after commit and an exception after commit.

The journal stores receipts; it does not prove them. Native executors/coordinators must
validate identity, source/destination, unchanged unrelated data and required save/readback
evidence before acknowledging physical commands. A transport response, missing party slot,
timeout, or caller-supplied success Boolean is not that proof.

The local client journal persists each observation ID before it is eligible for delivery.
An accepted response removes the oldest event and stages every command in one checked
local publication. Command completion stores the executor's receipt and its outgoing ACK
event together. The confirmed command floor advances only across a contiguous completed
inbox prefix, so an immediate HUD receipt cannot erase an earlier deferred operation.
Storage failures latch the store until reopen; they never reset it to an empty outbox.
These components have not yet replaced the production client's in-memory queues.

`client_journal.append_many(payloads, observation)` publishes a complete set of
frame observations and their next detector baseline in one checked local commit.
Every semantic event receives its own stable ID for individual server delivery;
this does not introduce a server-side semantic batch. The method returns the ID
array only after publication is confirmed. Invalid payloads/IDs, duplicate IDs,
or insufficient remaining capacity publish none of the frame. An uncertain store
publication stays latched; reopen and inspect the persisted outbox/baseline before
resuming detection. An empty array may publish an explicitly supplied object
baseline; an empty batch without a baseline is refused. `append` preserves its
single-event/scalar-ID interface through the same implementation.

`get_command(command_id)` returns a detached inbox record. `prepare_command(command_id,
intent)` persists a versioned policy document before any physical effect. The intent
must have a nonempty `schema` string; exact preparation retries are idempotent, while
conflicting preparation refuses. `pending_commands()` includes that intent after reopen
or repeated server delivery. Completion preserves it until the server confirms the receipt.
This additive API retains the journal document schema; bindings requiring preparation
must use the new executor interface and must not fall back to an older unprepared executor.

`command_executor.new(journal, adapter)` requires four callbacks:

- `prepare(body)` returns a versioned intent or nil plus a refusal reason, without effects.
- `classify(body, intent)` freshly observes identity and physical state. It returns
  `before` or `after` plus the observation, or `diverged` plus a reason. The cartridge
  policy must also recheck the live admission and appropriate execution checkpoint.
- `apply(body, intent)` rechecks preconditions and performs the effect. Its Boolean
  return value is deliberately ignored; a separate readback must prove completion.
- `receipt(body, intent, observation)` validates the exact poststate and returns a
  nonempty receipt document for independent server validation.

`step(command_id)` returns success plus an explicit outcome/receipt only after the
receipt and outgoing ACK are persisted. An existing completed inbox record is replayed
without execution. A prepared command whose poststate is already present also avoids
another write. A before-state may be applied only when the cartridge classifier proves
that forward recovery is safe. Partial/divergent states stay pending. Exceptions return
failure plus a retryable NACK diagnostic (`phase`, `reason`); this is not a terminal
receipt and callers must not dequeue the command. Storage failure requires reopening
the checked store before retrying. Snapshot/rollback detection and gameplay suspension
remain binding responsibilities; this engine does not authorize emulator advancement.

## Rule staging and binary caches

`SoulLinkState.to_document()` exports detached persisted data. `from_document()` restores
without file reads and propagates errors instead of returning the legacy loader's partial
fallback. The existing file-based load/save APIs retain their current behavior.

`StagedSoulLinkState.from_live(state, memorial)` clones rules and the link-index alias graph.
Its `_save` and memorial operations stay in memory. `document()` includes canonicalized
sets, runtime party snapshots/queues and memorial history; `restore()` must reproduce the
document exactly. `take_commands(player, immediate)` drains both staged queues for one
atomic journal commit. Unclassified fields fail rather than silently disappearing.

Party caches contain real `bytes`, not JSON strings. Each cached blob is represented by
`hex-bytes-v1`: encoding, byte length, lowercase hex, and SHA-256. Restoration returns
`bytes` and checks the adapter's `party_blob_size()`. This is byte fidelity and size
validation, not proof of the cartridge's encryption/checksum/semantic validity.

`preserve_peer_session=True` is a trusted keyword to `SoulLinkState.handle_event`, supplied
by an admitted coordinator. A protocol name in JSON cannot grant it.

An admitted coordinator may also supply `save_identity=SaveIdentity(ot_id, trainer_name)`
on HELLO, including through `DurableDispatcher.dispatch`. The binding validates the
actual loaded save before constructing this immutable value; the rule engine does
not construct it from a JSON `save_identity` field. It takes precedence over legacy
payload/party-derived IDs. Legacy callers retain their existing explicit `ot_id`
and party-key fallback. Identity validation precedes party/cache updates and legacy
trade-watchdog progress; a rejected HELLO receives only its rejection notice while
pre-existing command queues are retained. Persisted `player_identity` documents keep
their existing `ot_id`/`trainer_name` shape. The session/admission gate must validate
each delivery before durable replay; this value is not a substitute for that gate.

Legacy `pending_trade` object graphs are refused. A new native coordinator should compose
its JSON transaction document beside the staged rules document in the journal state:
stable identities, phases, pre/post party data/digests and recovery obligations. Do not
persist a `LinkEntry` object reference or infer successful physical completion.

## Transient traffic and remaining integration

Ghost samples/relays are transient, session/epoch-bound, coalesced and expiring. Staging
rejects `ghost_pos` events or commands; they belong outside durable rules and outboxes.
Adapters can extend the class-level volatile event/command sets.

Live client inbox/outbox and dispatcher selection, pause/service scheduling, reset,
save/load rollback, backup/restore and physical forward recovery still need integration.
The RR binding owns its verified native executor/readback and pause policy. RBY owns its
cartridge rules, source registry, memory/patch gates and trade coordinator. Shared storage
tests cannot substitute for either cartridge's live evidence.
