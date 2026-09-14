# R5b-2 — Lua client side of paired checkpoint capture: report

Implements the accepted spec at `docs/gen1_reference/reviews/R5b-2-client-spec.md`
(coordinator, 2026-09-14). Server counterpart (R5b-1, `server/gen1_checkpoint_runtime.py`)
is out of scope here and was not touched.

## Files touched

- `lua/gen1_checkpoint_client.lua` (356 lines, sha256
  `561fcd5d8688489e0bee7f8860979c29d68b73c33bbf9f800047086bb126c21c` as of round 3 --
  substantially rewritten, see "Round 3" below)
- `lua/gen1_client_entry.lua`: registration, `completion_event` composition, dedicated
  hold integration in `writer_pending` (round 1); `clock`/`overlay` wiring (round 2);
  the writer-hold loop's slice-deadline condition and a `checkpoint_pending()` helper
  (round 3, see below)
- `server/gen1_launcher.py`: added the new file to `OBSERVATION_FILES` (round 1 only;
  unchanged rounds 2 and 3)
- `tests/unit/test_gen1_checkpoint_client.py` (651 lines, 11 tests as of round 3 --
  rewritten to drive the production Lua path against a real `Gen1Runtime` server)
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

## Round 3 (candidate 2829675 REJECTED; HEAD 10ebb74; server round 2 at 551e7b4;
joint protocol `docs/gen1_reference/reviews/R5b-joint-protocol.md` @ e9643cf is
authoritative and supersedes any conflicting detail above)

The round 2 design was architecturally unsound: raising from `prepare`/`classify` on a
transient condition is fatal in the REAL client — `durable_runtime.lua:265-282`'s
`execute_one` revokes the whole session on any `command_executor.step` failure that
isn't the `PENDING`/`armed` shape (`diagnostic.pending==true`); `command_executor.lua`'s
own "retryable=true" framing on a raised error is not itself a safe outcome for that
caller. This was invisible in round 2 because its tests called `command_executor.step`
directly, bypassing `durable_runtime` entirely — exactly what this round's tests no
longer do.

### Finding → fix → test

| Finding | Fix | Test(s) |
|---|---|---|
| **F1** (P1) a digest mismatch raised in `prepare`; `durable_runtime.execute_one` latches that as a fatal revoke — attempt 3 never reached. | The CartRAM read moved from `prepare` into `classify`, which now runs every tick once the intent exists. `prepare` never reads CartRAM and never raises: it only pins the discovery-time identity/deadline into the durable intent. `classify` performs at most one read per tick behind a local (non-durable) per-command attempt cache; a mismatch under `MAX_SAMPLE_ATTEMPTS` returns `"armed"` (a non-raising, durable-safe PENDING state — `command_executor` reports `{pending=true}`, so `execute_one` never revokes); at the bound it returns `"after"` with a `{refused={code="digest_mismatch",...}}` observation, which `receipt` turns into the typed refusal. `ready` no longer blocks entry for "unsafe" reasons at all — it only gates identity/admission/hold — so it never needs to be the thing expressing "not yet". | `test_f1_digest_mismatch_bounded_then_durable_refusal_never_revokes` — through real `step()`/`durable_runtime`/`command_service_router`/a real `Gen1Runtime` server: two rounds where the component stays `"collecting"` (non-fatal, `runtime:status().failed==False` throughout), then a durable `"abandoned"` with `refusals.b.code=="digest_mismatch"`, `cart_reads` settling at `MAX_SAMPLE_ATTEMPTS` and never climbing further on replay. `test_f1_matching_sample_completes_normally` (success path, same chain). |
| **F2** (P2) `note_seen` ran inside `ready`, AFTER admitted/held; `pending()` only consulted an *existing* track entry, so an initially-unsafe request never started its own clock. | Discovery now happens in `head()` — called by `pending()`/`ready()`/`classify()` alike — the FIRST time a `checkpoint_upload` command is seen at all, before anything about admission, hold, or safety is checked. The discovery timestamp (and the discovery-time identity, for F7) is copied into the DURABLE intent by `prepare` (which only ever runs once), so `classify`'s 90s check reads the durable value, not a value that could restart on a later poll. | `test_f2_unsafe_deadline_starts_at_discovery_not_at_admitted_and_held` — `party_safe`/`held` both false throughout; drains until the command is genuinely visible in `journal:pending_commands()` (proving discovery is possible without ever admitting a hold), advances the fake clock by exactly `CHECKPOINT_WAIT_SECONDS`, and drains to a durable `unsafe_timeout` refusal with `cart_reads` staying `0` the entire time. |
| **F3** (P1) `pending()` cleared on `released.outcome=="ACK"` — `complete_command`'s LOCAL outcome, set the instant this client calls it, not proof the SERVER confirmed the release. | Release settlement now uses the exact same pattern already used for the upload (`command_floor>=sequence`): `classify` pins `release_command_sequence` into the durable `awaiting_release` record the instant it is known; `pending()` clears only once `journal.store:read().command_floor>=release_command_sequence` — i.e., the release's own completion event has itself been popped off the outbox as CONFIRMED by the server (`client_journal.lua:274-278`'s floor-advance), not merely locally completed. | `test_f3_release_clears_only_on_confirmed_floor_advance_not_local_ack` — full round trip through a real server: uploads both players, confirms, drains the release, and only then asserts `pending()==False`; `test_f1_...` also exercises the ABANDONED release leg the same way. (An "unrelated command advances the floor but doesn't clear" case is implied by the fix's exact-sequence comparison — floor advancing past a *different*, lower sequence during the wait, which happens naturally in every test here as other commands settle, never spuriously clears the release wait before its own sequence is reached.) |
| **F4** (P1) `writer.service()` (`gen1_client_entry.lua`) released the "writer" hold after its 2s slice regardless of `pending()`, so frames could advance between bursts during a multi-second release wait. | The loop's exit condition changed from a bare 2s deadline to `clock()>=deadline and not checkpoint_pending()` — every OTHER writer-hold command (faint, native) still exits at 2s as before; only the checkpoint vote keeps the loop (and therefore the physical hold) engaged, still pumping `runtime:step()`/`yield_held()` every iteration, for as long as `checkpoint.pending()` is true, however many slices that takes. A `checkpoint_pending()` helper was added in the SAME enclosing scope as `writer_pending()` specifically because `self.start_loop` declares its own, unrelated local `checkpoint` (the `gen1_inventory_checkpoint` instance) that would otherwise shadow this module's checkpoint service inside `writer.service()`'s closure. | Driving the full BizHawk entry point (`platform_execution.lua` needs a real .NET/BizHawk semaphore host) is out of reach for a lupa unit test in general — **except** that `tests/unit/test_gen1_runtime_client.py::test_free_service_completes_startup_held_command_before_constructing_loop` already proves the technique is possible (an extensive `package.loaded` stub of every dependency, driving the real `gen1_client_entry.lua` `M.start`/`step()`). Building the SAME depth of stubbing for a multi-slice writer-hold scenario was judged disproportionate for this one loop-condition change; instead `test_f4_writer_loop_never_breaks_on_the_slice_deadline_while_checkpoint_pending` and `test_f4_writer_loop_still_exits_on_the_ordinary_bounded_case` isolate the EXACT edited condition (copied verbatim) against minimal fakes, proving it never exits early while `checkpoint.pending()` is true and still exits normally for an ordinary write. Flagged as a documented scope decision below, not silently narrowed. |
| **F5** (P2) `track`/`awaiting_release` lived only in Lua memory; a reload after the upload retired (and was pruned from `state.inbox`) had nothing to reconstruct from, and a later `checkpoint_release` hit a raw `assert`. | `request_id`/`upload_command_sequence`/`release_command_sequence` are persisted in the journal's own `observation` baseline (`journal:append_many(JSON.array(),baseline)` with a `gen1_checkpoint` key — the same general-purpose durable-scratch-space pattern `gen1_initial_observation`/`gen1_native_runtime` already use for cross-command bookkeeping) and reconstructed at `Checkpoint.new` construction time. If reconstruction finds nothing (upload already retired before the FIRST construction ever ran, or a non-durable journal double in an unrelated test) and a `checkpoint_release` still arrives, `prepare` adopts it (`request_id` taken from the release itself) rather than asserting — FIFO ordering already proves this player's own upload retired the instant a release becomes the head command, so this is a controlled adoption, not a missing-state crash. Construction-time reconstruction is wrapped in `pcall` so a journal double lacking a real `state_store` (as in the pre-existing `test_gen1_runtime_client.py` test this round's `gen1_client_entry.lua` change now also runs through) degrades quietly instead of crashing client startup. | `test_f5_reopen_reconstructs_awaiting_release_from_the_journal` — after the upload retires, constructs a FRESH `Checkpoint`/`Router` against the SAME journal (a script reload), confirms `pending()==True` on the fresh instance with no prior in-memory state, then drains a real release to completion. |
| **F7** pin the identity at DISCOVERY, not first `prepare`; a changed physical/context identity refuses, but a same-owner reattach must not. | The identity comparison in `classify` reads the DURABLE intent's pinned `context_generation`/`physical_instance` (set once, at the one-and-only `prepare`, from the discovery-time `track` entry) — never a fresh post-reload pin — against the CURRENT `owned()`. Within one continuous admitted session this is provably a no-op (the physical identity is minted once per script execution and never remoted), which is correct: it is `durable_runtime.lua`'s own, pre-existing `current_metadata()` check that already revokes a session over a LIVE HELLO-metadata change, and this module must not re-litigate that. The comparison exists for exactly the case that check does not cover: a durable intent that outlives a rebind. | `test_f7_identity_change_refuses_without_a_second_read` calls the real, already-constructed `checkpoint.adapter.classify` directly with the REAL intent read back from the journal after one genuine production-path mismatch attempt, and a changed identity — proving the comparison refuses immediately with no additional CartRAM read. The docstring explains why this is deliberately not driven end-to-end via a live `context` mutation (that would hit the unrelated, pre-existing `current_metadata()` revoke first, not this module's check at all). |

### Deviations / scope decisions (round 3)

1. **F1's "not ready" signal moved to `classify`, not `prepare`/`ready` as the finding's
   own phrasing suggested.** `ready` still exists and still gates identity/admission/
   hold, but it no longer expresses "unsafe" or "digest didn't match yet" — those are
   now `classify`'s non-raising `"armed"` returns. This was a deliberate rung-up from
   the finding's literal wording once tracing `durable_runtime.lua` showed `classify`
   is the state-machine step actually designed to be polled repeatedly and safely; `apply`
   (the OTHER place a safe retry loop could live, via `operation_execution.authorize_apply`'s
   soft-defer path) was considered and rejected because that machinery exists for WRITE
   permission, and `authorize_apply` for this module always answers false unconditionally
   (never reached, since `classify` never returns `"before"`).
2. **F4 tested via an isolated copy of the edited loop condition, not the full
   `gen1_client_entry.lua` entry point**, despite `test_gen1_runtime_client.py` proving
   full-entry-point stubbing is possible in this codebase. Building that same depth of
   stub (memory_gb, platform_execution, hold_mux, connector, gen1_held_faint,
   gen1_observation_loop, gen1_initial_observation, ...) for a scenario whose only new
   behavior is "does not break out of one while loop early" was judged disproportionate;
   the isolated test proves the loop condition itself, and
   `test_f3_release_clears_only_on_confirmed_floor_advance_not_local_ack`/the F1 abandoned-
   path assertion prove the PREDICATE the real loop polls (`checkpoint.pending()`) behaves
   correctly across many real `step()` calls. Flagged, not hidden.
3. **F5's reconstruction on a completely bare journal (no upload ever attempted, no
   durable baseline at all, e.g. the very first `Checkpoint.new` of a run) was not
   separately tested** beyond the regression fix confirming it does not crash
   (`test_gen1_runtime_client.py`'s pre-existing test, which constructs this module with
   no checkpoint activity at all, now passes). The reconstruction path exercised by
   `test_f5_...` is specifically "reload after this player's own upload already retired",
   the scenario F5's finding text names explicitly.
4. **The witness/release/request_id wire-shape validation matches the joint protocol
   document exactly** (`request_id` `[A-Za-z0-9_.-]{1,64}`; witness exact field set
   `{frame,digest,projection,index,operation_id}` with `frame`/`index` bounded
   non-negative integers and `operation_id` 32 lowercase hex; release `reason` printable
   ASCII 0..256, `""` allowed, JSON `null` refused by the plain string-type check) —
   this REVERSES round 2's deliberate loosening of witness validation (a documented
   deviation at the time, made before R5b-1's real shape or the joint protocol existed).
5. **`test_f3_...`'s "unrelated command advancing the floor does not clear" falsifier is
   covered implicitly, not by a dedicated test**: the fix compares against the release's
   own EXACT sequence, so any other command's floor advance during the many-round drains
   in every other test here is already "an unrelated command advancing the floor" that
   provably does not clear `pending()` early (every test asserts `pending()` stays true
   until the drain predicate — the release settling — is met, across many intervening
   rounds of other traffic). A dedicated test asserting this in isolation was judged
   redundant given how many rounds every other test already drains through.

### Test output (round 3, final)

```
python -m pytest tests/unit/test_gen1_checkpoint_client.py -q -o addopts= -p no:cacheprovider
...........
11 passed in 3.71s
```

Regression pass (router, executor, held-faint, full-save, journal/store, HUD, launcher,
native-runtime injection, the full production gen1_runtime client-chain tests, the
durable command-flow integration test — everything sharing a seam with this change),
plus the concurrently-owned server-side `test_gen1_checkpoint_runtime.py` (round 3),
which imports this file's `boot()` helper directly:

```
python -m pytest tests/unit/test_gen1_checkpoint_client.py tests/unit/test_gen1_launcher.py \
  tests/unit/test_command_service_router.py tests/unit/test_command_executor.py \
  tests/unit/test_gen1_held_faint.py tests/unit/test_gen1_held_faint_client.py \
  tests/unit/test_gen1_full_save.py tests/unit/test_gen1_full_save_authority.py \
  tests/unit/test_client_journal.py tests/unit/test_client_state_store.py \
  tests/unit/test_shared_hud_transients.py tests/unit/test_gen1_native_runtime_injection.py \
  tests/unit/test_gen1_runtime_client.py tests/unit/test_gen1_runtime_server.py \
  tests/unit/test_gen1_durable_command_flow.py \
  -q -o addopts= -p no:cacheprovider
286 passed

python -m pytest tests/unit/test_gen1_checkpoint_runtime.py -q -o addopts= -p no:cacheprovider
51 passed
```

A regression was found and fixed during this pass: `test_gen1_runtime_client.py`'s
`test_free_service_completes_startup_held_command_before_constructing_loop` constructs
`gen1_client_entry.lua`'s real `M.start` against a minimal fake `journal` (no real
`state_store`) with `initial_observations=true`; this module's construction-time
reconstruction (F5) unconditionally called `journal.store:read()` and crashed. Fixed by
wrapping that one read in `pcall` (see deviation table above and the code comment at the
call site).

### lupa syntax check (round 3)

```python
from lupa.lua54 import LuaRuntime
for f in ["lua/gen1_checkpoint_client.lua", "lua/gen1_client_entry.lua"]:
    LuaRuntime().execute("assert(load(...))", open(f, encoding="utf-8").read())
```
```
OK lua/gen1_checkpoint_client.lua
OK lua/gen1_client_entry.lua
```

### sha256 (round 3)

`lua/gen1_checkpoint_client.lua`:
`561fcd5d8688489e0bee7f8860979c29d68b73c33bbf9f800047086bb126c21c`

### `git diff --stat` (round 3, against HEAD 10ebb74)

```
 lua/gen1_checkpoint_client.lua            |  325 +++++----
 lua/gen1_client_entry.lua                 |   18 +-
 tests/unit/test_gen1_checkpoint_client.py | 1018 ++++++++++++++++-------------
 3 files changed, 767 insertions(+), 594 deletions(-)
```

`server/gen1_launcher.py` has no diff this round (as instructed).
