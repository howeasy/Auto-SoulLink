# New Game bootstrap enrollment

`server/gen1_bootstrap_runtime.py` records one normal New Game proof per player
in the durable RBY runtime. The client's read-only bootstrap observer publishes a
`bootstrap_observation` event carrying an `rby-bootstrap-receipt-v1`; the server
ties it, through the existing `gen1_bootstrap_receipt.validate`, to that player's
immutable initial observation: the same admitted physical instance, context
generation and cartridge, a `StartNewGame` entry and normal return witnessed at or
before the enrollment frame, and the same still-empty save. The proof is a
statement about enrollment time. It is never re-derived from live state.

The event is selected by the existing `initial_observations` flag and is additive
to held enrollment. The initial-observation and recovery blockers stay in force.
After both initial observations exist, each validated bootstrap schedules one
exact `initial_save` command through `gen1_initial_save_runtime`. An early
bootstrap waits for the peer's initial observation; that later event becomes the
explicit scheduling origin. No frames are granted. SaveRAM ownership and each
write/repair/flush permit are independently checked by the initial-save lifecycle.
The frame-authority binding may require the completed save; it owns any later grant.

## Component shape

`components['gen1-new-game-bootstrap']` holds at most one entry per player:

```
{'a'|'b': {'operation_id': <32 hex>,
           'payload':      <the receipt exactly as received>,
           'proof':        <validate(...) result, rby-bootstrap-proof-v1>}}
```

Each entry is also written as an atomic journal record under the same namespace,
keyed by `record_key(player)`, in the same commit as its event. The result carries
`bootstrap_proof_digest` and `ordinary_execution: False`.

## Refusals

- No initial observation, or changed physical/save/cartridge/context metadata:
  `JournalError`, nothing written. A transport-only reconnect is accepted.
- Receipt context/owner/ROM/source pin differs from the enrollment, entry/return
  site or stack differs, return is after the enrollment frame, or the returned
  point differs from the enrolled save: refused by `validate`, nothing written.
- A second proof for the same player, identical or different: "bootstrap
  enrollment is immutable; replacement requires reconciliation".
- Event delivered while `initial_observations` is not selected: `ProtocolError`.

## Restore and provenance

`verify_state` recomputes every proof from its payload and the player's initial
observation on each restore and refuses a tampered proof, payload or operation id,
an entry without its initial observation, or a player other than `a`/`b`.
`verify_journal` requires the component to equal its atomic record and the record
to share a revision with the committed event. A missing or foreign record refuses
`runtime.state()`. A SQL failure during commit publishes nothing, and reopen
restores the enrollment without it.

The proof is bound to the original physical context and immutable enrollment.
The shared `admission_context.same_admitted_context` predicate ignores only
session id, admission epoch and binding digest; context generation and every
other metadata field must still match. A same-core reconnect or server reopen
can therefore deliver the historical proof without replacing the enrollment.
A changed core, cartridge, save, player, or unknown context field still refuses.
This matches the held-faint/memorial policy; current session ownership and any
future execution grant remain separate checks. No blocker is cleared by this
transport tolerance.

## Evidence

`tests/unit/test_gen1_bootstrap_runtime.py`: all nine R/B/Y pairings including
Yellow/Yellow with replay and reopen; twelve hostile binding, replay, history and
selection refusals; replacement refusal; six restore faults; removed and foreign
atomic records; SQL rollback with reopen. Initial snapshots are the shared
synthetic empty-save fixture; receipts are derived from that fixture, not from
independent constants. Live evidence for the observer itself is recorded
separately; this component adds no cartridge claims. Three same-core reconnect
cases and successful retry after SQL rollback/reopen cover transport tolerance.
