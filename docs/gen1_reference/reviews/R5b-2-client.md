# R5b-2 — Lua client side of paired checkpoint capture: report

Implements the accepted spec at `docs/gen1_reference/reviews/R5b-2-client-spec.md`
(coordinator, 2026-09-14). Server counterpart (R5b-1, `server/gen1_checkpoint_runtime.py`)
is out of scope here and was not touched.

## Files touched

- NEW `lua/gen1_checkpoint_client.lua` (157 lines, sha256
  `01909e084174eb6c945783a142d0c9f562b8c2dc44d40d26c4632013861107f9`)
- `lua/gen1_client_entry.lua`: registration, `completion_event` composition, dedicated
  hold integration in `writer_pending` (+22/-0 lines; see `git diff --stat` below)
- `server/gen1_launcher.py`: added the new file to `OBSERVATION_FILES`
- NEW `tests/unit/test_gen1_checkpoint_client.py` (14 tests)
- This report

No other files were created or edited (concurrently-owned files listed in the task
brief were left untouched; verified by `git status` below).

## Seams touched in `gen1_client_entry.lua`

1. `local CheckpointClient=Observation and require("gen1_checkpoint_client") or nil` —
   Observation-gated require, alongside the existing `Native`/`Observation` locals
   (:187-189 originally). Named `CheckpointClient` (not `Checkpoint`) to avoid colliding
   with the pre-existing `gen1_inventory_checkpoint` local also named `Checkpoint`
   inside the free-run block further down.
2. Callback composition, inserted between the existing native `acknowledge_event`
   composition block and `Journal.open` (was :212): if `CheckpointClient` is present,
   OR-compose its `completion_event` on top of whatever `callbacks` already holds
   (native+observation, or bare observation, or nil), asserting at most one claims any
   given event — the same shape as `gen1_native_runtime.journal_options`'s composition
   (:20-34), preserving native/observation fallthrough exactly as instructed.
3. Service construction, alongside `faint` (was :250-252): `local checkpoint=
   CheckpointClient and CheckpointClient.new({journal=journal,memory=memory,
   player=launch.player,variant=launch.cartridge.variant,owned=free and source_owned or
   owned,host=self.host})or nil` — same `owned` expression as `faint`.
4. `if checkpoint then services[#services+1]=checkpoint end` alongside the existing
   `if faint then ...` line, registering it with `command_service_router` BEFORE
   construction (per the spec's "beside HUD/faint, BEFORE `command_service_router.new`").
5. `writer_pending()` (was :433-434) gained one more disjunct:
   `or (checkpoint~=nil and checkpoint.pending())`. This is the ENTIRE hold-servicing
   change: `writer.service()` (:457-473, untouched) already loops `self.runtime:step()`
   generically for whatever is pending under the "writer" hold-mux owner, so adding our
   own service to `writer_pending()`'s disjunction is sufficient to give it the same
   dedicated hold-and-drain window `gen1_held_faint` uses — no new hold owner, no new
   servicing loop.

## Design notes / how the falsifiers map to the implementation

- **Exactly one command, no write permit, no cartridge write.** `M.handles` claims only
  `checkpoint_upload`. `operations.request` always returns `nil` (never asks for a
  permit window, like `gen1_hud_service`). `classify` always returns `"after"` once an
  intent exists (there is no "before" state for a pure read), so `command_executor`
  never calls `adapter.apply`; the function that WOULD be called there is defined to
  `error(...)` unconditionally, and `operations.authorize_apply` always refuses, as a
  second line of defense in case anything ever tries.
- **The read happens exactly once, in `prepare`.** `prepare` re-verifies
  `#journal:pending_events()==0` and `safe()` (== `mem.isPartyWriteSafe() and
  host.status().physical_stop_verified`) before calling `gen1_full_save.capture` — the
  same bulk-CartRAM pattern `gen1_held_faint` already reuses elsewhere — then hashes
  `cart_hex:sub(0x498*2+1)` with the journal's own `sha256` and compares it to
  `body.witness.digest`, refusing (via `assert`, surfacing as NACK + revoke, matching
  "refuse... no send") on any mismatch. The sampled bytes are persisted directly into
  the durable intent. `classify` then just returns that intent unchanged: a retry (or a
  process restart resuming from `journal:prepare_command`'s persisted intent) never
  calls `prepare` again and never resamples.
- **Duplicate delivery.** Handled entirely by the existing generic mechanism in
  `command_executor.step` (`if entry.outcome then return {...,replayed=true} end`) and
  `client_journal.complete_command`'s own idempotency check — no special-case code was
  needed in the adapter; a test proves the receipt (frame + cart_hex) is unchanged even
  after mutating the fake CartRAM and frame counter between the two `executor:step`
  calls, and that the CartRAM-read counter stays at 1.
- **Readiness never reads CartRAM.** `self.pending` (polled by `writer_pending`) and
  `self.ready` (gating `durable_runtime`'s `execute_one` before `command_executor.step`
  is even called) both only inspect `mem.isPartyWriteSafe()`, `host.status()`, and
  `journal:pending_events()` — none of which touch the `"CartRAM"` memory domain. Tests
  assert `cart_reads==0` after every refusal path, at both the `ready()` layer and by
  calling `adapter.prepare` directly under each bad condition (defense in depth: prepare
  re-checks safety/drainedness itself rather than trusting the caller).
- **The typed completion.** `M.completion_event(entry,outcome,receipt)` mirrors
  `gen1_trade_events.completion_event`'s shape exactly: reads `entry.body.body or
  entry.body`, claims only `checkpoint_upload`, asserts no terminal NACK, and returns
  `{event="save_upload",command_id,command_sequence,receipt}` — `receipt` is passed
  through verbatim (already `{request_id,witness,frame,context_generation,
  physical_instance,final_sha1,cart_hex}` from `adapter.receipt`), so
  `client_journal.completion()`'s validator (which requires the payload's `receipt` to
  equal the stored `entry.receipt` exactly) is satisfied for free.
- **Bounded hold, visible refusal.** No new timeout mechanism was added: the existing
  `M.WRITE_SERVICE_SECONDS` (2s) bound in `writer.service()` already bounds how long the
  "writer" hold is taken per attempt, and `ready`'s reason string surfaces through
  `durable_runtime`'s existing `state.deferred`/`runtime:status()` machinery the same
  way every other service's refusal does.

## Test output

```
python -m pytest tests/unit/test_gen1_checkpoint_client.py -q -o addopts= -p no:cacheprovider
..............
14 passed in 0.82s
```

Regression pass (router, executor, held-faint, full-save, journal/store, HUD, launcher,
native-runtime injection — everything sharing a seam with this change):

```
python -m pytest tests/unit/test_gen1_launcher.py tests/unit/test_command_service_router.py \
  tests/unit/test_command_executor.py tests/unit/test_gen1_held_faint.py \
  tests/unit/test_gen1_held_faint_client.py tests/unit/test_gen1_full_save.py \
  tests/unit/test_gen1_full_save_authority.py tests/unit/test_client_journal.py \
  tests/unit/test_client_state_store.py tests/unit/test_shared_hud_transients.py \
  tests/unit/test_gen1_native_runtime_injection.py -q -o addopts= -p no:cacheprovider
219 passed   # (14 new + 205 pre-existing)
```

A full `tests/unit` background run was also kicked off as a broader sanity check; the
targeted regression pass above already covers every module this card's diff touches or
composes with (router, executor, journal/store, held-faint, full-save, HUD, launcher,
native-runtime injection) and found nothing.

## lupa syntax check

```python
from lupa.lua54 import LuaRuntime
for f in ["lua/gen1_checkpoint_client.lua", "lua/gen1_client_entry.lua"]:
    LuaRuntime().execute("assert(load(...))", open(f, encoding="utf-8").read())
```
```
OK lua/gen1_checkpoint_client.lua
OK lua/gen1_client_entry.lua
```

## `git diff --stat`

```
 lua/gen1_client_entry.lua | 22 ++++++++++++++++++++++
 server/gen1_launcher.py   |  3 ++-
 2 files changed, 24 insertions(+), 1 deletion(-)
```

plus two new untracked files: `lua/gen1_checkpoint_client.lua`,
`tests/unit/test_gen1_checkpoint_client.py` (and this report).

## Deviations from the spec

1. **Witness field-set validation dropped in favor of R5b-1's real shape.** R5b-1
   (`server/gen1_checkpoint_runtime.py`) was still a concurrently-owned, in-progress file
   when this card started, but it materialized on disk partway through this work (a
   sibling worktree worker's uncommitted output, per `git status`). Reading it changed
   the implementation: the server pins `witness = document["components"]["gen1-save-witness"][player]`
   (`server/gen1_engine_signal_runtime.py:20`), whose real shape is
   `{frame, digest, projection, index, operation_id}` — five fields, not the two
   `{digest, projection}` I had validated against an exact whitelist in an earlier pass.
   `gen1_checkpoint_runtime.record` compares the uploaded receipt's witness to the pinned
   one for exact equality (`:163`), so an exact-field-set client-side check would have
   rejected every real command with "unknown checkpoint witness field: frame" the moment
   R5b-1 started sending it. Fixed: `M.validate` now checks only the two fields this
   client actually acts on (`digest`, `projection`); everything else is opaque and
   already round-tripped byte-for-byte by `copy(body.witness)` in `adapter.prepare`
   regardless. `test_receipt_echoes_the_real_five_field_server_witness_verbatim` pins
   this against the real shape.
2. **`request_id` validated as a bounded non-empty string** (1..256 bytes), matching
   `gen1_checkpoint_runtime.start`'s own check ("must be a non-empty string", `:112-113`)
   rather than the 32-hex-token pattern used by most other `*_id` fields in this client
   (`death_id`, `job_id`, `command_id`) — R5b-1 places no format constraint on it beyond
   non-empty, and being stricter here would risk rejecting a legitimate request_id.
3. **Projection literal duplicated as a local constant** (`"cartram-0498-8000-v1"`)
   rather than `require("gen1_engine_signals")` for the one constant, matching the
   existing precedent of hardcoding this same literal in `gen1_client_entry.lua:43`
   (the resume contract) instead of adding a cross-module require for a single string.
4. Card brief said "may create/edit ONLY... `lua/gen1_client_entry.lua`... in
   `writer_pending`" — the diff there also renames the pre-existing local `Checkpoint`
   (the required `gen1_checkpoint_client` module) to `CheckpointClient` at its two other
   use sites, to avoid shadowing the pre-existing `local Checkpoint=
   require("gen1_inventory_checkpoint")` a few dozen lines further down in the same
   function. This is a same-file, same-scope naming fix, not a new file; called out
   explicitly since it touches lines outside the three named regions (registration,
   composition, `writer_pending`).
5. No change was made to `lua/gen1_held_faint.lua` (the card brief said not to; the spec
   agrees no router change is needed there since routing composition lives in
   `gen1_client_entry.lua`).
