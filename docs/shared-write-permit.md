# Shared validated write permit

`lua/write_permit.lua` owns the armed permit, dense byte validation, complete
interval narrowing, immutable payload snapshots, whole-batch preflight,
provenance and error cleanup.
It has no platform address, memory domain, game identifier or implicit lifetime.
This is the PLAN 5.15b extraction; Gen 1 is rebound in the same cut through
`lua/gen1/entry.lua` and the required player-bundle manifest.

## Required binder interface

`Permit.new(policy)` requires every field below; omission is a constructor error.

| Field | Contract |
| --- | --- |
| `write_u8(addr, value, domain)` | Performs one byte write or raises. |
| `domains[name].bounds(addr, n, reason, token)` | Allows the complete interval in that named domain. |
| `domains[name].mapped(addr, n, reason, token)` | Verifies the currently mapped bank or corresponding platform ownership. |
| `domains[name].pointer_stable(addr, n, reason, token)` | Verifies pointer/address stability for the attempted write. |
| `lifetime.capture(reason)` | Returns a non-nil token at arm time. |
| `lifetime.valid(token, reason)` | Checks whether the token still authorizes writing. |
| `provenance(domain, addr, n, reason, token)` | Produces each span's receipt before any batch byte; may raise to refuse. |

Policies are trusted binder code and must be side-effect-free except for the byte
writer. No policy may mutate another policy during a call. The core checks
permit identity, lifetime, bounds, narrowing, mapping and pointer stability for
every complete span before emission and again for the current span before each
byte. Policy callbacks can therefore be invoked multiple times; they are not
one-shot actions.

`arm(reason, allow)` replaces any old permit. `reason` is a nonempty string;
optional `allow(domain, addr, n)` narrows the complete interval, never clips it.
`disarm()` is idempotent. `write_bytes(domain, addr, bytes)` requires an armed
permit, a known domain, an integer address, an exactly representable non-wrapping
interval, and a plain dense one-based table of integer bytes. Empty arrays preserve legacy no-byte behavior; absent trailing
elements cannot encode an intended length. Fixed-size builders must separately
validate their expected lengths.

`write_batch(spans)` accepts a plain dense one-based array of plain descriptors:

```lua
gate:write_batch({
    {domain="memory", addr=first_address, bytes={first_value}},
    {domain="memory", addr=second_address, bytes={second_value, third_value}},
})
```

Each descriptor contains only `domain`, `addr`, and `bytes`. The core first
validates and snapshots **all** descriptors, payloads, and exact intervals. It
then checks **all** complete spans against the private permit, bounds, narrowing,
mapping, pointer and lifetime policies; prepares **all** provenance receipts;
and rechecks the whole batch before emitting its first byte. An already-invalid
second/later span therefore cannot follow an earlier emission. A preflight
failure adds no write receipt, emits no byte, and disarms the permit.

Emission uses the snapshots in descriptor order, with current-policy validation
before each byte. The core does not infer game-specific span ownership or
transaction semantics. `write_bytes(domain, addr, bytes)` delegates to a
singleton batch, preserving existing binder calls and empty-payload receipt
behavior. An empty batch performs no I/O and adds no receipt, but still requires
an armed, live permit. Callers cannot mutate later descriptors or payloads from
a write callback to change what the validated batch will emit.

`guard(callback, ...)` executes a binder operation and disarms if it raises;
success retains the configured lifetime. `scope(reason, allow, callback, ...)`
arms, invokes the callback and always disarms, on both success and error.
`Permit.sequence_length(values, label)` validates a plain dense array for a
binder's higher-level payload before its first write.
Guards and scopes do not collect future writes into a batch. A compound builder
must submit all its spans in one `write_batch` call; separate `write_bytes` calls
remain separately preflighted operations.

The public `armed` and `allow` fields are compatibility observations. They do not
grant authority: the core retains private permit state. `log` contains receipts.
Errors from validation, policies, provenance, binder guards or I/O close the
permit. A later operation requires an explicit new `arm`.

## I/O errors and receipts

Each span receives a separate top-level copy of its prepared provenance table,
so a binder reusing the same table cannot alias the core's per-span fields.
Nested binder metadata remains binder-owned. Successful span receipts retain
the binder's fields and add `status="written"`, `completed`, `attempted`,
`batch_index`, and `batch_size`. Indices are one-based within this operation.
A written span does **not** mean that the entire batch completed.

An emission or per-byte revalidation error records `status="error"` for the
current span and its error text, then disarms and rethrows. Earlier completed
span receipts stay written; unattempted tail spans receive no write receipt.
`completed` counts byte-write calls that returned within that span; `attempted`
includes the call that failed. A policy failure before that span's first call
records zero attempted/completed calls. A failing platform call might have
changed memory before raising. These counts are neither independent memory
readback nor a rollback claim. Batch preflight prevents already-known refusal
from causing a partial operation; it does not make platform I/O atomic or undo
earlier writes if policy or I/O fails after emission has begun.

## Other Gen 2 binders

`lua/gen2/panel.lua:64-79` and `lua/gen2/trade_overlay.lua:68` each construct
their own independent `Permit.new(...)` instance — the panel's over WRAM0 only,
armed by `gb_panel`'s `allow()` predicate under `reason == "panel"` (and one
`phone` byte, `:71-73`) — and never share a permit with the party/box writers
described below.

## Gen 2 discontiguous party-faint binding

`lua/gen2/writes.lua` retains game-owned slot, record geometry, battle-context and
ownership checks. Its bench party-faint payload (`faint_party_slot`, wired only
outside the active battler) is one shared batch: status byte, then the two HP bytes. The
unused intervening byte is not targeted. The binder no longer duplicates an
allow-only approximation of shared preflight; a bad HP mapping, unstable pointer
or failed HP provenance is found before status emits.

**Active-battler action suppression now ships** (`faint_active_battler`,
`:182-197`; called from `lua/gen2/client.lua:1487`): behind `gate.armed ==
"battle_hold"` (itself gated by the checkpoint's proven `battle_faint` receipt
coverage, see `docs/shared-gb-checkpoint.md`), it writes a four-span batch —
battle-struct HP, party-mirror status, party-mirror HP, then
`wBattlePlayerAction = skip_action` last, so `DetermineMoveOrder`/`DoPlayerTurn`
still let the native `HasPlayerFainted` handler run before the foe moves
(`:176-181`). Conditional explode remains unqualified and disabled:
`explode_active_battler` (`:198-199`) unconditionally errors
"conditional explode action-selection path is not qualified". This change
supplies no checkpoint or physical write authority beyond what the battle_hold
receipt already proved.

## Gen 1 binder and compatibility

`W.new(profile, io, Permit)` requires the shared factory explicitly. Entry loads
it from `lua/write_permit.lua`; there is no hidden require or fallback copy.
The Gen 1 binder keeps the outward `arm`, `disarm`, `write_bytes`, faint/explode,
APEX and transformation methods. Both System Bus and Entry's CartRAM door now
use the same permit. Domain bounds, receipt fields and the panel's CartRAM
refusal stay in Gen 1. Narrowed Gen 1 windows speak System Bus addresses and
cannot authorize CartRAM.

The System Bus bound is the GB 16-bit bus. Flat CartRAM uses GB $2000-byte banks
through the highest native SRAM box bank recorded in the generated profile.
The CGB `$D000-$DFFF` rule remains in `lua/gen1/writes.lua`: when the profile
enables it, only register values 0 and 1 are accepted; Lua never switches banks.
The pointer policy is explicit because these builders pass fixed numeric
addresses/flat offsets, not re-resolved indirect pointers. Hook and party-range
validation remain in the game-specific builders.

Gen 1's lifetime is **until explicit disarm**, including across framecount
changes. Framecount labels receipts; it does not expire a permit. This corrects
the old comment's unsupported current-frame claim without shortening valid
Gen 1 operations. New refusal behavior is intentional: malformed/sparse/out-of-
bounds writes, invalid active party slots and any operation error disarm. The
CartRAM door now validates its whole byte payload before its first byte.

## Verification and qualification

`test_write_permit.py` exercises neutral domains with both persistent and epoch
lifetimes, holes, whole-interval and whole-batch refusal, mapping/pointer policies,
later-span payload/descriptor mutation, reused receipt tables, partial I/O errors
and guarded/synchronous cleanup. `test_gen2_writes.py` reproduces the real
status-before-invalid-HP defect through the public binder operation and
distinguishes initial refusal from a mid-emission device failure. Gen 1 tests run the
actual `Entry.build` graph, verify both write domains, retained lifetime and
bank rules, and exercise the built player ZIP's launcher-rooted dependency
closure. These checks provide MODEL evidence only.

The second binder uses this interface with its own explicit policies and runs
the neutral contract tests. Sharing the implementation does not transfer any
Gen 1 evidence. Gen 2 runtime activation is outside this extraction.

Non-author review and unchanged independent Gen 1 physical receipts remain
required before accepting the rebind. Affected lanes are `live-new-gates`,
`duo-pairs`, `inspect-purergb-overlay` and `duo-pairs-purergb`. Rollback must restore
the Gen 1 writes/Entry loading changes and bundle manifest together; leaving a
consumer pointed at an omitted module is not a valid rollback.
