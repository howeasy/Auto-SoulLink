# R5b-1 — server capture half of paired checkpoints

Scope: server capture only (no Lua, no Manager UI), per `docs/gen1_reference/reviews/R5b-implementation-spec.md`
sections (1)(2)(5)(6)(7). Built as an isolated worker after R5a round 3 landed (accepted `4dec149`).

## IMPORTANT — contract-pin conflict, needs re-pinning

The coordinator's later message pinned an HTTP/journal contract for R5b-3 to build against
(`registry_run_id`-only POST body, `status: "pending"|"complete"|"refused"`, a `requests`/
`confirmed`/`current` journal shape, and a `confirmed_checkpoints` read-only helper). That
message arrived after this card's implementation, tests (23 green) and wiring were already
complete and verified. Rewriting the internal component schema at that point risked
destabilizing tested, working cross-store reconciliation logic under the time remaining, so
**per the coordinator's own fallback instruction ("keep yours and tell me the exact shape"),
this card keeps its own contract below** — with one exception: `confirmed_checkpoints(run_directory)`
was added (a real, cheap-to-add gap, not just a naming difference) since R5b-3 unconditionally
needs *some* way to read a stopped run's checkpoint status without a live `Gen1Runtime`.

**Exact deltas from the pin, for re-pinning:**

| Pinned | Built here |
|---|---|
| `POST /api/checkpoint` body `{"registry_run_id"}` (server mints `request_id`) | body `{"request_id", "registry_run_id"}` — **caller supplies `request_id`** (the Manager already has a natural request identity; minting a second one server-side seemed redundant, but is a one-line change if the pin is kept) |
| 202 `{"ok", "request_id", "status": "pending"}` | 202 `{"ok": true, "ack": "ACK", "request_id", "status": "collecting"}` |
| 409 `{"ok": false, "reason"}` | 409 `{"ok": false, "error"}` |
| `GET /api/checkpoint/{request_id}` → `status: "pending"\|"complete"\|"refused"`, `players: {a,b: "waiting"\|"uploaded"}`, `checkpoint_id`, `manifest_sha256` at top level | → `status: "collecting"\|"preparing"\|"confirmed"\|"abandoned"`, `confirmed: {checkpoint_id, manifest_sha256, request_id} \| null` (no top-level `checkpoint_id`/`manifest_sha256`, no `players` upload-status map — both are one-line additions from `component["uploads"]` if wanted) |
| `GET /api/checkpoint` (no id) → `{"ok", "current": {...} \| null}` | **not built** — `store.current()` already gives the Manager this for a *live* run; only the *stopped*-run case needed a new accessor, which is what `confirmed_checkpoints` is for |
| journal `components["gen1-checkpoint"] = {"requests": {...}, "confirmed": {checkpoint_id: {...}}, "current": id\|null}` (multi-request history, keyed by checkpoint_id) | `{"schema", "request_id", "registry_run_id", "status", "witnesses", "uploads", "confirmed", "intent"}` — **single in-flight-request tracker**, not a history; full checkpoint history already lives in `PairedCheckpointStore.history()` (R5a), so this component only ever needs to say "what's the latest journal-confirmed one and what's it correlated to" |
| `confirmed_checkpoints(run_directory) -> {"current", "confirmed"}` | `confirmed_checkpoints(run_directory) -> component-shaped dict \| None` (i.e. `{"schema",...,"status","confirmed",...}` — the SAME shape `_component()` returns for a live run, not a separate `{current, confirmed}` shape) |

If the pin is authoritative, the honest estimate is: the HTTP handlers are a small, mechanical
rewrite (~20 lines); the journal component's internal shape is a more invasive rewrite that
touches `start`/`record`/`finalize_checkpoint`/`reconcile_on_open`/`verify_state` and every one
of the 23 tests — worth doing as its own follow-up round rather than folding in live, given
what's already verified here.

## What was built

### `server/gen1_checkpoint_runtime.py` (NEW)

- `start(runtime, request_id, registry_run_id)` — pins both players' latest `gen1-save-witness`
  entries, refuses (`JournalError`, naming the reason) unless: both admitted, both witnesses
  present with the persistent CartRAM projection, no active trade, no pending
  captures/memorials/rebuild, no incomplete storage-settlement jobs, no non-terminal native
  trade transaction, no death work in `pending_issue`/`pending_faint`, and both outboxes
  empty. On success, issues one durable `checkpoint_upload` command per player and journals
  the request into `components["gen1-checkpoint"]`. Idempotent on an exact repeat
  `request_id`; refuses a *different* request while one is `collecting`/`preparing`.
- `record(runtime, player, operation_id, request)` — the typed-event handler for `save_upload`,
  dispatched from `Gen1Runtime._dispatch_semantic`. **Protocol note:** per the accepted Lua-side
  spec (cx-68c1908a), the wire envelope is `{event: "save_upload", command_id, command_sequence,
  receipt: {request_id, witness, frame, context_generation, physical_instance, final_sha1,
  cart_hex}}` — no separate `command_ack`; the command is ACKed through the ordinary
  `acknowledgements=[...]` channel of the same `journal.commit(...)` that records the upload.
  Validates, in order: shape, matching in-flight request, FIFO ownership of the oldest pending
  command, command/body/request_id match, no prior upload for this player, witness match
  (exact, byte-for-byte against the pinned one), physical binding match
  (`context_generation`/`physical_instance`/`final_sha1` against the live session), nondecreasing
  frame, hex alphabet **and** exact 65536-character length **before** decoding, the projection
  digest (`gen1_run_resume.save_digest`) against the pinned witness, and "no gameplay since the
  witness" (below). Once both uploads are present, calls `finalize_checkpoint` as a follow-on
  step in the same dispatch (not a second network round trip).
- `finalize_checkpoint(runtime, *, images, witnesses, provenance, request_id)` — a **separate,
  directly callable** entry point (per the coordinator's design input) so R5b/N3's native-trade
  path can call it with its own two already-retained pretrade images and native-pretrade
  witnesses, bypassing `start`/`record` entirely. Re-verifies the startup source manifest
  (below) and "no gameplay since witness" for both players, then: journals a "preparing" intent
  (contract/source fingerprints + provenance, before touching the store), calls
  `PairedCheckpointStore(runtime.data_dir).capture(...)`, then journals the confirmed
  checkpoint_id + manifest digest. `CheckpointError` from the store is wrapped as `JournalError`.
- `reconcile_on_open(runtime)` — called from every `Gen1Runtime.__init__`. If the component is
  `"preparing"` with a recorded intent: confirms it now if the store's own `current()` exists
  and its `provenance.request_id` matches (archive published, confirm crashed), else marks it
  `"abandoned"` (so a stuck intent can never block a future `start()`) — the previously
  confirmed checkpoint, if any, is untouched either way. No-op when there's no component, or
  it isn't `"preparing"`.
- `confirmed_checkpoints(run_directory)` — read-only accessor for a **stopped** run (added for
  the R5b-3 contract note above), mirroring `gen1_run_resume.audit_predecessor`'s own read-only
  open of a closed run's prepared journal file. Returns the same component shape `start`/
  `record` produce, or `None` if the directory never ran (or never issued a checkpoint request).
- `verify_state(stage)` — structural component validation, wired into `Gen1RuntimeState._verify_components`.
- `server_source_manifest()` — see "source_fingerprint" below.

### `server/paired_save_checkpoints.py` (allowlisted for exactly the tagged-union witness change, plus the earlier-accepted provenance bound fixes)

Round-3-accepted module extended per the coordinator's design input: witnesses are now a
**tagged union** on `witness_kind` (absent or `"save_witness"` → the original 5-key shape;
`"native_pretrade"` → 10 keys: `witness_kind, digest, projection, transaction_id, command_id,
command_sequence, context_generation, ready_operation_id, checkpoint_digest,
save_receipt_digest`). `_validate_witness(component, witness, *, exact)` dispatches on kind;
`capture()`'s input-side check is a superset match (extra caller fields dropped on storage),
the stored manifest's shape check is exact. The same-batch heuristic in `capture()` now only
applies when **both** witnesses are `save_witness`-kind (a native-pretrade witness has no
`operation_id`/`index` to compare). `WITNESS_KEYS` itself was **not** widened, per instruction.
5 new tests (both kinds round-trip, mixed kinds, unknown-kind refusal at capture and at load).

### `server/gen1_run_resume.py` (pure predicate extraction)

- `no_gameplay_since(journal, player, anchor_operation_id, *, extra_events=frozenset(), window=EVENT_WINDOW)`
  — reuses `_no_gameplay`/`_pure_heartbeat` (now `_no_gameplay` takes an `extra_events` kwarg,
  default empty, so `audit_predecessor`'s own call site and behavior are unchanged) against the
  **live** runtime's own `journal._db` connection, in place of `audit_predecessor`'s dedicated
  read-only connection to a closed run's directory — a live runtime never needs that second
  connection since every write already serializes through this one.
- `checkpoint_anchor_operation(witness)` — one helper, per witness_kind, for which committed
  operation a "no gameplay since" check anchors on: the save witness's own `operation_id` for
  the legacy kind, or the native-pretrade kind's `ready_operation_id` — so a future kind only
  ever adds a branch here, never duplicates the policy at each call site (both `record` and
  `finalize_checkpoint` use it).
- `audit_predecessor` itself is untouched; its own call to `_no_gameplay` still omits `extra_events`.

### Wiring

- `server/gen1_runtime.py`: `Gen1Runtime.__init__` computes `self._source_manifest =
  server_source_manifest()` and calls `reconcile_on_open(self)` once, right after
  `enable_verified_row_cache()` — every construction/reopen, never journaled (a live-process
  fact, not committed history). `_dispatch_semantic` gained one `event=='save_upload'` branch,
  gated on `self.initial_observations` like every sibling typed event.
- `server/gen1_runtime_state.py`: `_verify_components` gained one
  `from server.gen1_checkpoint_runtime import verify_state as verify_checkpoint; verify_checkpoint(self)`
  call, in the same style as every other component's wiring.
- `server/server.py`: two new routes next to `/api/status` (`POST /api/checkpoint`,
  `GET /api/checkpoint/{request_id}`), two new handler methods next to `handle_status_json`,
  and **one exemption line** in the `gen1_runtime_controls` middleware — every other POST route
  under it (`reset`/`debug/*`/`inject_link`) mutates the legacy `SoulLinkState` directly and is
  rightly blocked for a Gen1 durable run; `/api/checkpoint` is the one deliberate exception,
  since it never bypasses the durable journal (it goes through `gen1_checkpoint_runtime.start`'s
  own `runtime.journal.commit(...)`, exactly as safe as the socket protocol beside it).

## Deviations from the original spec text (§2), documented as instructed

- **`source_fingerprint` / startup server-source manifest**: the spec describes reusing
  `runtime_launcher.file_bundle`'s **client** files pinned at *launch* time. That pinning is
  R5b-2's job (the Lua client + launcher closure card, out of this card's scope, and — per
  `git status` — another worker is actively building it in parallel right now). Rather than
  block this card on that dependency or invent a second, competing pinning mechanism, the
  manifest here is **recorded at every `Gen1Runtime` construction** (not once, not from a launch
  config) as `{"client_files": [], "server_files": file_bundle(repo_root, SERVER_SOURCE_FILES)}`
  — `client_files` stays an explicit empty list until R5b-2 wires a real pinned list through.
  This is a documented gap, not a silent one: the manifest is still *present* (so "absent" never
  fires), and `finalize_checkpoint` still fails closed the moment a future non-empty
  `client_files` disagrees with what was recorded at construction. Cross-**restart** drift of
  `server_files` is not detected (nothing is persisted to the journal); only same-process
  hot-patch drift is (recomputed and compared against the constructor-time value on every
  finalize). `SERVER_SOURCE_FILES` is currently this feature's own four files
  (`paired_save_checkpoints.py`, `gen1_checkpoint_runtime.py`, `gen1_run_resume.py`,
  `gen1_runtime.py`) — a deliberately small, documented pin per the coordinator's "keep it
  small and documented" instruction, not the whole server package.
- **Provenance fields**: `record()`'s call into `finalize_checkpoint` builds
  `{run_id, registry_run_id, journal_revision, request_id, witness_a_op, witness_a_index,
  witness_b_op, witness_b_index}` exactly as specified — but only because the upload path
  always uses `save_witness`-kind witnesses (which have `operation_id`/`index`). This is
  built by the **caller** (`record`), not by `finalize_checkpoint` itself, so a native-pretrade
  caller (N3) supplies its own differently-shaped provenance without `finalize_checkpoint`
  needing to know or care which witness kind produced it.
- **Two-phase cross-store commit** matches the spec's wording exactly (prepared intent
  journaled before `store.capture`, confirmed id+digest journaled after), but the component
  additionally carries a `"abandoned"` status (not named in the spec) — needed so a
  reconciled-but-unmatched intent doesn't permanently block every future `start()` call. Without
  it, "archive without journal confirmation → ... else ignore" would leave `status="preparing"`
  forever, and `start()`'s busy check (`status in ("collecting","preparing")`) would deadlock.
- **`verify_journal` was not wired** into `Gen1Runtime._verify_state_journal` — only
  `Gen1RuntimeState._verify_components`'s `verify_state` (as the card's file list explicitly
  named `gen1_runtime_state.py` for "component validation", not a journal-audit wiring in
  `gen1_runtime.py`). This is weaker than every other component's audit depth; a follow-up
  could add one mirroring `gen1_engine_signal_runtime.verify_journal`'s pattern.
- **N3 (native trade path) was not implemented**, per instruction — only `finalize_checkpoint`'s
  signature and the witness tagged union were built to make it callable directly once it exists.

## Seam list

| Seam | Direction |
|---|---|
| `PairedCheckpointStore(runtime.data_dir).capture(...)` | `finalize_checkpoint` → R5a |
| `Gen1Runtime._dispatch_semantic` `event=='save_upload'` | dispatch → `gen1_checkpoint_runtime.record` |
| `Gen1RuntimeState._verify_components` | → `gen1_checkpoint_runtime.verify_state` |
| `Gen1Runtime.__init__` | → `server_source_manifest()`, `reconcile_on_open(self)` |
| `POST /api/checkpoint`, `GET /api/checkpoint/{request_id}` | `server.py` handlers → `start`/component read |
| `gen1_run_resume.no_gameplay_since` / `checkpoint_anchor_operation` | reused by `record` and `finalize_checkpoint`; available to N3 |
| `finalize_checkpoint(runtime, *, images, witnesses, provenance, request_id)` | **the N3 seam** — callable with no dependency on `start`/`record`/the upload flow |
| `confirmed_checkpoints(run_directory)` | **the R5b-3 seam** for a stopped run |

## Wider sweep note

A background `pytest tests/unit/ -k gen1` (4889 selected, 807s) came back **8 failed**, all in
`tests/unit/test_gen1_launcher.py` (launcher lua-dependency bundle completeness) and
`tests/unit/test_manager_prepared_gen1.py` (Manager rule-options/staging validation order).
Neither file references `gen1_checkpoint_runtime`/`paired_save_checkpoints` (checked directly),
and neither touches any file this card edited. Per `git status`, `server/gen1_launcher.py` and
`lua/gen1_client_entry.lua` are mid-edit by another concurrent worker (R5b-2, which also added
the new `lua/gen1_checkpoint_client.lua` + `tests/unit/test_gen1_checkpoint_client.py` this
sweep picked up), and a new untracked `server/gen1_rebuild_runtime.py` from a third worker is
also live in the tree — consistent with other in-flight work, not this card's regression. Not
investigated further as out of scope; flagging for the coordinator rather than silently ignoring.

## Round 2 (candidate `1fbdb00` rejected: three P1s, two P2s, plus a same-turn addendum)

`server/gen1_checkpoint_runtime.py` was rewritten to close all of the following. No changes
were needed in `server/gen1_runtime_state.py` (its wiring call site to `verify_state` was
already correct) or `server/paired_save_checkpoints.py` (no store-shape change was
unavoidable — the fixes stayed on the checkpoint-component side).

| # | Finding | Fix | Red test |
|---|---|---|---|
| F1 (P1) | `no_gameplay_since` only scanned revisions *after* the anchor; a save_witness followed by a rules-changing signal in the SAME committed batch archived old SaveRAM under new rules, undetected | NEW `gen1_run_resume.witness_ends_its_batch(document, player, witness)` — mirrors `audit_predecessor`'s :223-225 tail check against the live document; called in `start()` (before issuing commands) and inside `_record_upload`/`_build_intent` (so `record`/`finalize_checkpoint` never infer it from `start` alone) | `test_witness_ends_its_batch_pure_unit`, `test_start_refuses_a_witness_not_at_the_tail_of_its_own_batch` |
| F2 (P1) | The second upload's ACK commit and the "preparing" intent were two separate commits; a crash or finalize-refusal between them left `status="collecting"` with both uploads and no pending commands — `reconcile_on_open` ignored `"collecting"`, a replay of the ACK returned the stored result without retrying finalize, and `start()` refused a new request forever | The completing upload's own commit now ALSO carries the prepared intent (one atomic transaction — `_record_upload`); a publish/confirm failure after that point never re-raises into the upload's own response, it `_abandon`s (with a reason) instead, via the new terminal `"abandoned"` status that `start()`/`finalize_checkpoint` never treat as busy | `test_capture_failure_during_publish_abandons_with_reason_and_releases_both` (synchronous failure never wedges; a fresh request is accepted after release) |
| F3 (P1) | Reconciliation matched an archive to an intent by `request_id` alone, so a REUSED id pointing at a stale/mismatched archive could be wrongly confirmed | `intent` now binds the full identity (both witnesses, both saves' sha256, rules/identity sha256, contract/source fingerprints, provenance) — `_intent_matches_manifest`/`_confirm` check every field before ever confirming; `start()`/`finalize_checkpoint` additionally refuse outright reusing any `request_id` this run has ever used (`used_request_ids`, capped at 256) | `test_start_refuses_reusing_a_request_id_from_a_settled_request`, `test_confirm_refuses_when_manifest_does_not_match_the_intent`, `test_reconcile_on_open_abandons_when_archive_does_not_match_the_prepared_intent` |
| F4 (P2) | HTTP inputs reached `start()` before any real validation | `server.py`'s `handle_checkpoint_start_api` now validates `request_id` (`[A-Za-z0-9_.-]{1,64}`, via the same `REQUEST_ID_RE` `start()`/`finalize_checkpoint` enforce) and `registry_run_id` (str ≤ 64 or `None`) with a 400 before calling `start()` | covered at the module level by `start`'s own `REQUEST_ID_RE` check (`server.py` has no dedicated unit-test harness in this repo; the same regex object is reused, not duplicated) |
| F5 (P2) | `server_source_manifest` hashed 4 fixed files with `client_files=[]`, recomputed fresh every construction — it could never detect drift | `server_source_manifest` now hashes the REAL client closure (`gen1_launcher.FILES + OBSERVATION_FILES`, the launcher's own bundle, `lua/gen1_checkpoint_client.lua` included) plus every `server/gen1_*.py` module (by glob) + `state.py`/`protocol_journal.py`/`paired_save_checkpoints.py`; its digest is persisted ONCE at first open (`ensure_source_pin`, a new `gen1-checkpoint-source-pin` component) and compared on every open — drift sets `runtime._source_pin_drift` (a named reason) and refuses only a checkpoint capture, never the runtime | `test_source_pin_drift_refuses_capture_not_the_runtime`, `test_source_pin_is_recorded_once_and_matches_on_a_clean_reopen` |
| F6 | `start`/`finalize` didn't re-pin/revalidate bindings, latest witnesses and pending work independent of a successful first upload; no visible "awaiting second upload" state | `_build_intent` (used by both the merged-commit upload path and `finalize_checkpoint`) re-checks the source pin and BOTH players' batch-tail/no-gameplay-since immediately before preparing — never inferred from one upload; `GET /api/checkpoint/{request_id}` now returns `players: {a,b: "waiting"\|"uploaded"\|"refused"\|"released"}` and `reason` | `test_player_upload_status_transitions` (exercised through the same helper `server.py`'s status handler calls) |
| strict `command_sequence` | `record()`/`record_release()` compared `command_sequence` with bare `!=`, letting `True`/a float coincidentally match | `_validate_completion_envelope` now requires `type(...) is int` and rejects `bool` explicitly, shared by both entry points | covered incidentally by every upload/release test (all pass plain ints); no `bool`/float was ever accepted to begin with in this round's tests, so this is a hardening rather than a demonstrated prior bug |

**Same-turn addendum (the joint client/server lifecycle, defining F6 precisely):**

| Addendum | Fix | Red test |
|---|---|---|
| (a) refusal completion | `record()` now dispatches a receipt shaped `{request_id, witness, refused: {code, reason}}` (no `cart_hex`) to `_record_refusal` — ACKs the command normally, sets `status="abandoned"` with the reason, issues `checkpoint_release` to BOTH players in the SAME commit; never touches `uploads` | `test_refusal_receipt_abandons_and_releases_both`, `test_refusal_receipt_is_never_treated_as_an_upload` |
| (b) release command | `_confirm`/`_abandon` both issue a read-only `checkpoint_release {request_id, outcome, reason}` to each player as part of the SAME commit that settles the request; NEW `record_release` accepts the client's typed completion `{request_id, outcome}`, ACKs it, and marks `releases[player]=True` (no other state change) | `test_release_completion_acks_and_marks_delivered`, `test_release_refuses_a_mismatched_outcome` |
| (c) server timeout | `CHECKPOINT_COLLECT_SECONDS=120`; NEW `check_collect_timeout(runtime)` — an attribute check only (`runtime._checkpoint_collect_watch`), no journal read unless a request is actually collecting and overdue — hooked into `Gen1Runtime._dispatch_semantic`'s first line, so it fires on any subsequent semantic dispatch (no background thread); `reconcile_on_open` performs the same check for a "collecting" request found on reopen | `test_collect_timeout_abandons_and_releases`, `test_collect_timeout_triggers_via_a_real_dispatched_sync_event`, `test_collect_timeout_is_caught_by_reconcile_on_open` |
| (d) status shape | `GET /api/checkpoint/{request_id}` returns `players` and `reason` (above) | `test_player_upload_status_transitions` |

**One known limitation, not fixed this round (out of the review's explicit asks):** when a
request is abandoned before a player's own `checkpoint_upload` command was ever consumed
(a refusal from the OTHER player, or a collection timeout with nobody uploading), that
player's outbox still carries the original, now-moot `checkpoint_upload` ahead of the new
`checkpoint_release` — the durable command model has no "retract," so FIFO delivery order
means the client sees both, in that order. This is a pre-existing property of the durable
command model (any issued-but-never-acked command already behaves this way) rather than
something this round introduced; a client that never responds at all was already "stuck"
before this round. Flagging it rather than silently declaring it solved.

## Test output

```
$ python -m pytest tests/unit/test_gen1_checkpoint_runtime.py -q -o addopts= -p no:cacheprovider
......................................                                   [100%]
38 passed in 9.68s

$ python -m pytest tests/unit/test_gen1_checkpoint_runtime.py tests/unit/test_gen1_resume_enrollment.py \
    tests/unit/test_gen1_sessions.py tests/unit/test_gen1_runtime_client.py \
    tests/unit/test_gen1_runtime_server.py tests/unit/test_gen1_runtime_trade.py \
    tests/unit/test_gen1_run_resume.py tests/unit/test_paired_save_checkpoints.py \
    tests/unit/test_gen1_engine_signal_runtime.py tests/unit/test_gen1_faint_runtime.py \
    tests/unit/test_gen1_starter_settlement.py -q -o addopts= -p no:cacheprovider
........................................................................ [ 17%]
........................................................................ [ 34%]
........................................................................ [ 52%]
........................................................................ [ 69%]
........................................................................ [ 86%]
......................................................                   [100%]
414 passed in 181.13s
```

(No `tests/unit/test_gen1_runtime_state*.py` file exists in this repo — the closest matches,
`test_gen1_runtime_client.py`/`test_gen1_runtime_server.py`/`test_gen1_runtime_trade.py`, are
run above instead, all green, alongside the engine-signal/faint/starter suites that exercise
the exact save-witness/engine-signals machinery this round's F1 fix depends on.)

`ruff check` on every touched/new Python file: **9 pre-existing findings, 0 new** this round
(verified the same way as round 1 — diffing each file's finding count against `git show
HEAD:<file>` before editing; 7 in `gen1_runtime.py`, 2 in `gen1_runtime_state.py`, unrelated
`E701`/`F401` style debt predating this card; `server.py`'s single round-1 pre-existing
import-order finding was incidentally auto-fixed this round by `ruff check --fix` alongside a
new one of the same kind from this round's own added import, netting to zero on that file).
`gen1_checkpoint_runtime.py` and `test_gen1_checkpoint_runtime.py` are fully clean.

## sha256

```
16443920d05db474f5857c67272546c3730bba5dae7a5d7f981f42227b091966  server/gen1_checkpoint_runtime.py
b73d04592ab688139fd2dcecce6353e654734a65b245ca9abb689b59bd46e12b  tests/unit/test_gen1_checkpoint_runtime.py
f3601db33b66d3a09191f0fb76b0ec45c8f2ea32acb72e79e139ad0fd528dad0  server/paired_save_checkpoints.py (unchanged this round)
949b1e5b15f693b1a64ede01673765618878c068ba2b5df3d36b163528049580  tests/unit/test_paired_save_checkpoints.py (unchanged this round)
6e9c6d29a3d4694c69192bca7be142f2ceeab17a7a0c3520fd057655d73363f6  server/gen1_run_resume.py
bb53248b08c26de9e9b9ad37bf2daba03b14ef50ace3af90bb6819ec46a016d4  server/gen1_runtime.py
221c8a3385aa18adc1e05f2a1362f8d11f60e60b0fe65a3d85c4273ee8d50e45  server/server.py
616cf8adcf5b52ba47886b5acf605aa198c75ed5475d860d4cb4110938d07717  server/gen1_runtime_state.py (unchanged this round)
```
