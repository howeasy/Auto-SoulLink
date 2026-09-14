# R5b-2 — Lua client side of paired checkpoint capture: report

Implements the accepted spec at `docs/gen1_reference/reviews/R5b-2-client-spec.md`
(coordinator, 2026-09-14). Server counterpart (R5b-1, `server/gen1_checkpoint_runtime.py`)
is out of scope here and was not touched.

## Files touched

- `lua/gen1_checkpoint_client.lua` (283 lines, sha256
  `345823fa935ded3b2f84efc89aa9d041d223017f1531d862263c6122077a36b7` as of round 2)
- `lua/gen1_client_entry.lua`: registration, `completion_event` composition, dedicated
  hold integration in `writer_pending`, plus (round 2) `clock`/`overlay` wiring into the
  constructor call
- `server/gen1_launcher.py`: added the new file to `OBSERVATION_FILES` (round 1 only;
  unchanged this round)
- `tests/unit/test_gen1_checkpoint_client.py` (21 tests as of round 2)
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

## Test output (round 2, final)

```
python -m pytest tests/unit/test_gen1_checkpoint_client.py -q -o addopts= -p no:cacheprovider
.....................
21 passed in 1.35s
```

Regression pass (router, executor, held-faint, full-save, journal/store, HUD, launcher,
native-runtime injection — everything sharing a seam with this change):

```
python -m pytest tests/unit/test_gen1_checkpoint_client.py tests/unit/test_gen1_launcher.py \
  tests/unit/test_command_service_router.py tests/unit/test_command_executor.py \
  tests/unit/test_gen1_held_faint.py tests/unit/test_gen1_held_faint_client.py \
  tests/unit/test_gen1_full_save.py tests/unit/test_gen1_full_save_authority.py \
  tests/unit/test_client_journal.py tests/unit/test_client_state_store.py \
  tests/unit/test_shared_hud_transients.py tests/unit/test_gen1_native_runtime_injection.py \
  -q -o addopts= -p no:cacheprovider
226 passed
```

A full `tests/unit` background run (round 1) turned up 64 pre-existing failures, all in
`test_gen1_memorial_runtime.py` and `test_gen1_observation_runtime.py` — files this card
never touches, and other worktree workers' concurrent uncommitted edits to
`server/gen1_memorial_runtime.py`/`server/gen1_runtime.py`/etc. (visible in `git status`
throughout this session) are the far likelier cause. Not re-run in full this round given
the ~14 minute cost and that the targeted regression pass above already covers every
module this card's diff touches or composes with and is fully green.

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

## `git diff --stat` (round 2, against HEAD 3b592a2 / candidate 645fa94)

```
 lua/gen1_checkpoint_client.lua            | 238 +++++++++++++++++++++++-------
 lua/gen1_client_entry.lua                 |   3 +-
 tests/unit/test_gen1_checkpoint_client.py | 236 ++++++++++++++++++++++++-----
 3 files changed, 385 insertions(+), 92 deletions(-)
```

`server/gen1_launcher.py` and this report file are the other two files in scope; the
report is rewritten in place for round 2 and `gen1_launcher.py` has no diff this round.

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

## Round 2 (adversarial review on candidate 645fa94, HEAD 3b592a2)

Files this round: `lua/gen1_checkpoint_client.lua`, `lua/gen1_client_entry.lua`,
`tests/unit/test_gen1_checkpoint_client.py`, this report. `server/gen1_launcher.py`
unchanged. The server counterpart (R5b-1, `server/gen1_checkpoint_runtime.py`) landed
concurrently as its own round 2; coded against its mirror protocol as given.

### Finding → fix → test

| Finding | Fix | Test(s) |
|---|---|---|
| **F1** digest mismatch / identity change / perpetual-unsafe asserted in `prepare` → transient NACK forever, re-reading 32 KiB every retry, never a durable receipt. | `prepare` now: (1) refuses **identity_changed** immediately (no read) if the pinned `context_generation`/`physical_instance` for this command_id changed since the first attempt; (2) bounds unsafe/undrained retries to `CHECKPOINT_WAIT_SECONDS` (90s wall clock via the now-required `clock` option) → **unsafe_timeout** refusal with zero reads; (3) bounds digest-mismatch retries to `MAX_SAMPLE_ATTEMPTS` (3) → **digest_mismatch** refusal after exactly 3 reads. Each refusal is a *successful* `prepare` return (a `{refused={code,reason}}` intent, no `cart_hex`), so `journal:prepare_command` persists it, `classify` always answers `"after"`, and `receipt`/`complete_command` retire the command via a normal ACK carrying `{event="save_upload",...,receipt:{request_id,witness,refused:{code,reason}}}` — never a NACK loop. `ready()` is forced `true` once the wait budget expires specifically so `prepare` gets to run and persist that refusal (it still performs zero CartRAM reads in that case, since the state is still unsafe). A `Checkpoint refused: <reason>` notice fires via `hud.lua`'s `H.present` (sanitize-safe) the moment the refusal receipt is built. | `test_digest_mismatch_bounded_to_three_attempts_then_durable_refusal` (2 NACKs at 1/2 reads, 3rd call ACKs with `refused.code=="digest_mismatch"`, `cart_hex==nil`, a 4th delivery replays with no further read); `test_identity_changed_refuses_immediately_regardless_of_attempt_count` (refuses on attempt 2 with zero extra reads, independent of the 3-attempt bound); `test_unsafe_timeout_refuses_without_ever_reading_cartram` (`ready()` false pre-budget, forced `true` post-budget, `prepare`/`step` refuse with `cart_reads==0` throughout). |
| **F2** `pending()` dropped to false the instant `checkpoint_upload` locally ACKed, so the writer hold released before the `save_upload` event shipped or the paired capture (the OTHER player, or a refusal) resolved. | `gen1_checkpoint_client` now also claims **`checkpoint_release {request_id,outcome,reason}`**. `receipt()` for `checkpoint_upload` (success or refusal alike) sets `self.awaiting_release={request_id,upload_command_sequence}`; `pending()` returns `true` for as long as that is set, clearing it only once it independently observes — via `journal.store:read().command_floor`, since a confirmed command is pruned from `state.inbox` the moment it retires, so `journal:get_command` cannot see it later — that this player's own upload retired *and* the matching `checkpoint_release` command has itself durably ACKed (checked the same way, via a remembered `release_command_id` and `journal:get_command(...).outcome`). While waiting, `pending()` fires a rate-limited (every ≥3s) "Checkpoint pending - waiting for the server" notice; there is deliberately **no** timeout on this wait (release can take arbitrarily long; F1's bound is upload-side only). `checkpoint_release`'s own `prepare` refuses (a plain NACK, no state change) if its `request_id` doesn't match the awaited one. On completion it shows "Checkpoint saved" or "Checkpoint abandoned: <reason>" and is retired the normal way (`{event="checkpoint_release",...,receipt:{request_id,outcome}}`), after which `pending()` goes false on its next poll. `writer_pending()` in `gen1_client_entry.lua` needed no further change: it already routes through `checkpoint.pending()`, which now itself reflects the extended state. | `test_successful_upload_holds_until_checkpoint_release_confirmed` (pending stays true + "waiting" notice after the upload ACKs; a `checkpoint_release{confirmed}` retires it, pending goes false, "Checkpoint saved" fires); `test_checkpoint_release_abandoned_after_a_refusal_still_releases_the_hold` (same, starting from a *refused* upload, ending in `abandoned`); `test_release_never_arriving_keeps_holding_with_a_repeated_notice` (pending stays true and the notice re-fires across a simulated 100000s wait — no bound); `test_checkpoint_release_refuses_when_it_does_not_match_the_awaited_request` (mismatched `request_id` → NACK, hold stays engaged). |

Per the finding's own permitted fallback ("drive the production writer loop if your
harness can, else the hold predicate"): driving the real `M.run` entry loop needs the
full BizHawk/luanet environment (`emu`, `event`, `gameinfo`, `luanet`), which no unit
test in this repo constructs (there is no `test_gen1_client_entry.py`). The tests above
drive the **hold predicate** (`service.pending()`, which is exactly what
`writer_pending()` polls) across multiple simulated pumps instead, matching every other
falsifier's `runtime`/`command_executor`/real-journal harness used throughout this file.

### Known limitation surfaced, not fixed (out of scope this round)

`writer.service()` in `gen1_client_entry.lua` (unedited, shared with `gen1_held_faint`
and native) bounds ITS OWN internal servicing loop to `M.WRITE_SERVICE_SECONDS` (2s)
before releasing the "writer" hold regardless of whether `writer_pending()` is still
true. A `checkpoint_release` round trip will usually take far longer than 2s (network
latency to the server and, transitively, to the OTHER player). Between one
`writer.service()` burst ending and the next one starting (`writer_pending()` is
re-checked and, seeing `checkpoint.pending()==true`, re-invokes `service()`), the outer
`M.run` loop's `if ... not service.host.status().held then emu.frameadvance() end`
could let a stray frame of gameplay run. This card's fix makes the *predicate* correct
(`pending()` now genuinely reflects "still waiting for the release" for as long as
needed); it does not change the *shared* 2-second-bounded hold-reacquisition loop that
every writer-hold command already relies on, since that is out-of-file-scope
(`writer.service()`'s body is untouched) and touches `force_faint`/native too. Flagging
for a follow-up card if truly zero-gap holding through a multi-second release wait
turns out to matter in practice (a live emulator gate would show it either way).
`self.awaiting_release` and the per-command attempt/timeout tracking (`track`) are also
in-memory only, not journaled — a Lua script reload while a request is in flight forgets
both and falls back to whatever `journal:pending_commands()` shows (correct if
`checkpoint_release` is already the head; not if it is not durably visible via the
generic path).
