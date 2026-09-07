# Shared logical identity and witnessed migration

`server.identity_registry` is an inactive, detached domain primitive. It supplies
logical member/link IDs and acquisition duplicate bookkeeping for the journaled
coordinator. It does not select an RR/RBY/Gen2 runtime, read memory, grant execution,
award a capture/bonus, evaluate clauses, or retire death/archive obligations.

## Scope and evidence

`IdentityContext` binds a player, adapter game ID, validated `SaveIdentity`, current
admission digest, context generation and independently validated physical instance.
The physical instance identifies a cartridge participant, not merely an OS PID.
Changing context/build evidence for the same save requires a new admitted binding;
replacing that player's save or sharing one physical instance across both players
is refused. Retired context bindings are retained and cannot be reactivated; a new
admission requires fresh context evidence. Binding here is bookkeeping, not permission
to resume gameplay.

`IdentityWitness` carries the context, exact compatibility key, evidence digest and
explicit observed count. Only count 1 is accepted. Cartridge validation must establish
that uniqueness from coherent permitted observations; constructing a dataclass does
not prove it. JSON lookalikes cannot call the witness-requiring methods.

Current keys are indexed by player/save/key. The same raw key in different players
can name different members. Keys are retained exactly, without case normalization
or a generation-specific parser. Logical IDs are independently generated 128-bit
values, never party slots, PID/OT values or transport/native sequence numbers.

## Atomic domain actions

Each action has a player-scoped durable action ID. Persist these IDs with the outer
semantic transition; they are independent of connection delivery metadata. A rule
transition that both acquires a member and creates a link supplies separate stable
action IDs for those two pieces of bookkeeping. Exact retries return the same IDs
with `replayed=true`; acquisition retries also return `created=false` so a caller
cannot mistake replay for creation. Changed content/meaning under one action ID fails.

Every method validates a detached candidate before replacing this staged registry.
A failure in any migration member or link assignment publishes none of that action.
Action requests, their digests and ordered provenance are persisted with results.
Restore cross-checks creating acquisitions, migration participants/chains and link
creation/assignment histories, so a result cannot be retargeted to another known ID.
It then replays context activations and domain actions in one global transition order
using the recorded IDs and the normal transition preconditions. Final-state uniqueness
alone cannot hide a temporary duplicate, a stale context, or an unconfirmed alias.
The application then commits the complete registry document beside rules, native
transactions, recovery and both outboxes in ONE `ProtocolJournal.commit`. No side
file or separate identity commit may become authoritative first.

- `acquire(event_id, acquisition_id, witness)` creates one member per scoped
  acquisition transaction. Different detector observations can share that transaction.
  A new acquisition ID for a currently owned raw key is refused unless the binding
  explicitly supplies the matching `existing_member_id` to confirm a duplicate. An
  alias/retry creates no new member and does not itself award anything.
- `migrate_many(issuer, event_id, witnesses)` preserves member and acquisition IDs
  while changing raw keys or ownership. A `MigrationWitness` names the logical
  member, current admitted source participant, prepared before key/evidence and
  freshly validated after observation. The binding may validate historical before
  bytes from a journaled intent; it must not claim those bytes are still in RAM.
  Both participant contexts must be current. Final uniqueness is checked for the
  entire batch, so a legitimate swap needs no unsafe intermediate vacancy.
- `create_link` assigns a stable ID to explicit zero-to-two members. Empty links
  can identify a rule record without a Pokémon. Pairing eligibility, player roles
  and game compatibility are decisions of the rule coordinator.
- `replace_link_members` stages explicit coordinated pairing changes without
  replacing link IDs and retains previous membership. It cannot place a member in
  two current links. The coordinator must commit this with the corresponding native
  transaction and identity migrations, rather than expose an intermediate pairing.
- `resolve(context, key)` resolves ONLY the current admitted physical association.
  `historical_members(player, key)` is a diagnostic history lookup, never execution
  authority. A witnessed new acquisition can reuse a no-longer-current historical
  raw key without retargeting the older member's pending obligations.

Exact action replay is a read-only lookup and may describe an earlier context. The
outer session gate MUST validate current delivery ownership/admission before replay,
as it does for the shared durable dispatcher. New actions and physical lookups require
the current identity context. Replay does not authorize an old native operation.

## Persistence, migration and limits

`document()` returns a detached JSON value. `restore(document, run_id=...)` requires
the expected journal run ID and validates complete contexts, acquisitions, current
uniqueness, histories, link memberships and action results. It does not read a file,
coerce a legacy `LinkEntry` object graph or silently drop unknown fields. The shared
bounded JSON representation applies; capacity/encoding failure leaves the old stage.

This slice has no legacy-run import adapter. That adapter still needs the consistent
backup/checkpoint evidence, explicit active-versus-historical associations and handling
of legacy pending trades required by the release plan. Insufficient or duplicate
legacy identities must enter reconciliation; they cannot be guessed from matching
keys or names. Existing runs and their link/memorial histories remain unchanged until
that separate atomic migration is implemented and validated.

Death, memorialization, retirement, archive and native execution have their own
obligation IDs and lifecycles. They reference `member_id`; changing a key/owner
does not mark them complete or erase their history. The journal composition test
retains a pending death reference through rekey and reopen. No physical death or
retirement is inferred by this registry.

RR's selected cosmetic/battle-form grouping and regional separation belong to the
RR catalog, not this module. A family/type/species change cannot replace a Pokémon's
logical identity merely because a rule projection changes.
