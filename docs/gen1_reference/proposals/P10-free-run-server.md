# P10: free-run observation server (handoff item 3, server half and wiring)

> **Update 2026-09-12 (commit 6f07831).** Section 5's fail-closed list is historical: statics, NPC
> exchanges, evolutions and wild encounters now ride the observation batch and stage in `stage_observation`
> after acquisitions, so only genuinely unknown receipt kinds fail closed. The credit-path deletion listed
> here landed as commit 48c64d0 with tier 2 (the native-trade window machinery) deliberately kept.


Status: implemented as two new files plus two patches. Verified in a private copy of the
scratch worktree with P8 and P9 applied; nothing that already existed in the sweep worktree
was edited. Line numbers below are the patched files as they read after both patches apply.

- `server/gen1_observation_runtime.py` (new, 183 lines): `record`, `stage_observation`,
  `verify_state`, `verify_journal` for the `observation` event that
  `lua/gen1_observation_loop.lua` (P4) publishes.
- `tests/unit/test_gen1_observation_runtime.py` (new, 16 tests): the six the handoff asked
  for plus the starter route through batches, the deferred heartbeat, and the selection.
- `docs/gen1_reference/proposals/P10-free-run-server.patch` (23 hunks, my five files):
  `server/gen1_runtime.py`, `server/gen1_run_config.py`, `server/gen1_launcher.py`,
  `lua/gen1_client_entry.lua`, `lua/gen1_initial_observation.lua`.
- `docs/gen1_reference/proposals/P10-free-run-server-verifiers.patch` (7 hunks, 14 added
  lines in two files outside my set): `server/gen1_observation_provenance.py`,
  `server/gen1_acquisition_runtime.py`. Section 3 says why it cannot be avoided and why it is
  delivered separately. Root decides.

```bash
git apply --check docs/gen1_reference/proposals/P10-free-run-server.patch            # OK
git apply --check docs/gen1_reference/proposals/P10-free-run-server-verifiers.patch  # OK
git apply docs/gen1_reference/proposals/P10-free-run-server.patch
git apply docs/gen1_reference/proposals/P10-free-run-server-verifiers.patch
python -m pytest tests/unit/test_gen1_observation_runtime.py -q                       # 16 passed
python tools/lua_syntax_check.py                                                      # OK: 301 Lua files
ruff check . --select E9,F6,F7,F81,F82                                                # All checks passed
```

The two patches are order independent. Their hunks do not overlap the P8 hunks
(`gen1_faint_runtime.py`) or the P9 hunks (`gen1_acquisition_runtime.py:24-28,248-322`); the
verifier hunks sit at `receipts_of` (`:104-108`) and inside `verify_journal` (`:452-461`,
`:496-500`).

## 1. What it is

One client event, one atomic settlement. The loop publishes, per P4 section 1:

```json
{"schema": "rby-observation-v1", "event": "observation", "frame": 4821, "sequence": 17,
 "context": {"context_generation": "...", "physical_instance": "...", "save_identity": {}},
 "rom": "<final sha1>",
 "signals": {"schema": "rby-engine-signals-v1", "sequence": 3, "signals": []},
 "acquisitions": [{"kind": "capture", "receipt": {}}],
 "inventory": {"schema": "rby-initial-observation-v1", "frame": 4821, "host": {}, "source": {}}}
```

`record(runtime, player, operation, request)` replays through `runtime.journal.event`, then
stages everything on ONE detached stage/document and commits once with
`runtime.journal.commit(...)`, carrying every record and both outboxes, the way
`gen1_frame_journal.returned` commits a compound frame bundle and the way
`gen1_acquisition_runtime.record` commits a standalone event.

Validation before any staging (`stage_observation`, `:78-102`): exact field set and types
(`typed`, `:45-63`); initial enrollment and an admitted owner; `rom` equals the admitted
`final_rom_sha1`; `context.context_generation` equals the enrollment binding;
`context.physical_instance` and `context.save_identity` equal the admitted metadata; the
player is not frame-accounted; `sequence` is exactly the previous plus one, persisted per
player in the component `gen1-observation-progress` (`{sequence, operation_id, frame}`);
`frame` advances. Refusal is total: the detached document is discarded and nothing commits.

## 2. Event handling order, and what each part reuses

Inside the one document, in this order:

1. **Inventory** (`:114-132`). `gen1_inventory_observation.stage_observation` with the
   `inventory_observation` payload the compound path builds (`sequence` and
   `previous_operation_id` derived from the component), so the transition, the write
   attribution and `settle_ready` (starter settlement) run unchanged. A standalone checkpoint
   may not cross an open physical obligation (`gen1_inventory_observation.py:149-150`,
   `gen1_starter_settlement.py:95-96` refuse it); the obligation receipt carries its own
   checkpoint, so while ANY player has a pending command the heartbeat checkpoint is
   **deferred, not refused**: signals and receipts in the same batch still settle and the
   result says `inventory_deferred: true`. The next heartbeat after the last receipt records
   again. This is the only policy decision in the module.
2. **Engine signals** (`:133-137`). `gen1_engine_signal_runtime.stage_observation` with
   `{"event": "engine_signals", "payload": batch}`: `validate_batch`, the contiguous engine
   sequence, `remember_source` (starter) and `gen1_faint_runtime.settle` (ball activation,
   faints, the peer command) exactly as the standalone event.
3. **Acquisitions** (`:138-148`). `gen1_acquisition_runtime.decode_receipts` (kinds
   `capture` and `grant`) then `stage_acquisitions(..., frame_request=request, rom=rom)`
   standalone style; also run with no new rows when pending facts exist and a checkpoint was
   recorded in this batch, as `gen1_frame_acquisitions.stage` does.

Result: `{"ack": "ACK", "ordinary_execution": false, "observation_digest", plus
"inventory_transition_digest" | "engine_evidence_digest" | "acquisition_digest" for the parts
present, "inventory_deferred": true when deferred}`. Each part digest is the digest the part
module publishes for its own entry, so the existing verifiers can be pointed at the outer
event (section 3).

Order note: the compound path stages engine signals before inventory. Inventory first, as the
handoff asked, means a starter source and its stable checkpoint arriving in the SAME batch
settle at the next heartbeat instead (the checkpoint is staged before the source is
remembered); `test_starter_source_and_checkpoint_settle_through_observation_batches` shows
the two-batch route settling. The faint path is order independent: the death is decided
from the signal party bytes.

## 3. Why the verifier patch exists, and why it is separate

`Gen1Runtime.state()` re-verifies every component against the journal on every call. Three
checks key on the NAME of the committing event, and a single `observation` commit satisfies
none of them without help:

| Verifier | What it demands today | Line |
| --- | --- | --- |
| `gen1_observation_provenance.semantic_receipt` (used by the engine, inventory, faint, starter, storage and grave verifiers) | no `frame_origin`: `journal.event(player, op, semantic)`, which raises `operation ID was reused with different semantic content` when the stored request is not the `engine_signals` / `inventory_observation` request itself | `:106-108` |
| `gen1_acquisition_runtime.verify_journal` | the current entry event is `acquisition_observation` with the exact standalone result, or a `frame_complete` | `:452-458` |
| `gen1_acquisition_runtime.receipts_of` and the stable-event branch of `verify_journal` | the receipt list and the stable inventory come from `acquisition_observation` / `inventory_observation` / `frame_complete` requests only | `:100-107`, `:490-495` |

So after the first observation commit the next `runtime.state()` would raise, and every
event after it would be refused. The verifier patch adds an `observation` branch beside the
existing `frame_complete` branch in each place (14 lines): `semantic_receipt` resolves the
outer observation, checks that `signals` / `inventory` contain the semantic payload and that
the outer result carries the entry digest, and returns the same legacy-shaped
`EventReceipt(revision, {ack, <digest field>, ordinary_execution}, command_ids)` it returns
for a compound frame. No new evidence semantics: the entries, records and digests are the
ones the part modules already produce.

Both files are root-owned and were reserved from this track, hence a separate patch and no
edits to them in the shared scratch tree (my tests were run in a private copy). The one
alternative that needs no foreign lines is sequential sub-commits (call the three standalone
`record` functions with derived operation ids and then commit an envelope event): two to
four journal events and `state()` audits per batch instead of one, and no atomicity across
the parts. It is described here so root can choose it if the verifier lines are unwelcome;
it was not built.

## 4. Exact wiring lines

`server/gen1_runtime.py`: `free_service=False` constructor flag (`:109`), validated as a
bool that requires `initial_observations` and refuses `ordinary_frames` (`:125-127`;
`native_trade` therefore stays impossible with it); `verify_observations(self.journal, stage)`
in `state()` right after the inventory verifier (`:228-229`); `_dispatch_semantic` routes
`event == "observation"` to `gen1_observation_runtime.record` when `self.free_service`
(`:284-288`), mirroring the `ordinary_frames` gate for `frame_complete`.

`server/gen1_run_config.py`: `free_service` is an allowed key of `gen1_runtime.json` that
must be `true`, requires `initial_observations`, and excludes `ordinary_frames` (`:30-34`);
`configure_runtime` persists it (`:68`); `open_runtime` restores it (`:94`);
`create_runtime(..., free_service=False)` accepts and validates it (`:100-110`, `:135`). The
run configuration `mode` stays `held_service`; the LAUNCH configuration is what changes.

`server/gen1_launcher.py`: `SOURCE_FILES` (the six read-only acquisition observers and their
site data) is split out of `ORDINARY_FILES` (`:27-38`); `FREE_FILES = ("lua/gen1_observation_loop.lua",) + SOURCE_FILES`
(`:38`); `configuration` passes `free_service` (`:50`); `build_configuration` validates it
(`:63-64`), sets `"mode": "free_service"` (`:66`) and ships `FREE_FILES` (`:70`). The frame
client, bounded execution, execution window, pacer, identity guard and native frame client
are not shipped in free mode.

`lua/gen1_client_entry.lua` (`mode == "free_service"`):

| Line | Change |
| --- | --- |
| `:12-13`, `:25-26` | `validate` accepts `free_service` beside `held_service`; requires `initial_observations` and no `ordinary_frames` |
| `:34` | `local free=launch.mode=="free_service"` |
| `:117-119` | `owned()` under free-run asserts a verified hold now, not the launch frame: the hold is momentary |
| `:131` | `at_boundary()` reads `self.loop_ctx.at_boundary==true`; nil until the loop exists |
| `:135-137` | `Observation.new` gets `ordinary_frames=launch.ordinary_frames or free` (no standalone engine flush, no inventory stream: both live inside the batches) and `at_boundary=at_boundary` |
| `:140-144` | `self.acquisitions` is built for free_service too; `held` is `physical_stop_verified==true or at_boundary()` (P4 section 4, second line) |
| `:243-244` | control and sync intervals as for ordinary frames |
| `:248-249` | the runtime host wrapper: once the loop runs, control-service holds and releases are bookkeeping only; the loop and its writer own the physical hold |
| `:256` | `read_context=free and source_owned or owned` (HELLO and control turns run released) |
| `:260-311` | `self.start_loop`: once initial inventory and bootstrap are acknowledged, engine signals and observers exist and the runtime is bound, build `loop_ctx` (P4 section 3 sketch, plus `inventory` and `writer`), `Loop.new`, release the hold, phase `free_service` |
| `:326-331` | `step()`: with a loop, one `tick()` per call; under a hold taken outside the loop only the runtime pumps, so a tick never re-observes a frame |
| `:342` | `start_loop()` after the held-phase step |
| `:368` | `status()` reports `free_service` and `observation_loop` |
| `:396-397` | `run()`: with the loop and no hold, `emu.frameadvance()` between steps; otherwise the held yield as today |

`lua/gen1_initial_observation.lua:52`: `held` for the engine signals becomes
`physical_stop_verified or (options.at_boundary and options.at_boundary()==true)` (P4
section 4, first line).

Three client details that P4 did not settle:

- **The heartbeat checkpoint is captured under a momentary verified hold** (`:282-291`):
  `gen1_initial_observation.validate` refuses a point whose `host.held` is not `true`
  (`server/gen1_initial_observation.py:113-117`) and `verify_entry` requires the host stanza
  to equal the initial observation (`gen1_inventory_observation.py:44-45`). Taking
  `set_held(true)` for the 28 ms capture and releasing it makes `held=true` a true statement
  and reuses `Observation.capture` unchanged; the flip happens inside one script turn between
  frames, so the core never sees it.
- **`run()` keeps the main loop and advances with `emu.frameadvance()`** rather than
  registering `event.onframeend`. The durable entry is the main chunk of `lua/slink.lua`
  (`:27` returns `run(configuration)`), not a `dofile` of the duo harness (the harness
  dofiles the legacy clients under `lua/clients/`), so nothing waits for it to return. Inside
  a frame-end callback the writer could not `yield_held()` across a permit round trip, and
  the item 5 window (`owner.step_one` from `writer:service()`) cannot step frames from inside
  the core callback at all. P4 shipped `run()` in this exact shape.
- **The writer** (`:292-303`) is the smallest adaptation of how the entry services
  `gen1_held_faint` today: `pending()` is a queued command the held-faint executor handles
  while the party is write-safe; `service()` takes the hold and pumps the runtime under
  `yield_held()` until the command closes or `M.WRITE_SERVICE_SECONDS` (2) pass, then
  releases; while pending it is retried every tick, so gameplay stays held one frame at a
  time until the write closes. In battle the command waits (item 5 replaces this with the
  window). The executor still requires the control service to be in its held authority
  state; item 4 owns that policy.

## 5. Tests and results

`tests/unit/test_gen1_observation_runtime.py`, 16 passed:

| Test | Proves |
| --- | --- |
| sequence contiguous | seq 3 after 1 and a repeated seq 1 are refused, a frame going backwards is refused, nothing commits, seq 2 then records; the progress record equals its journal record |
| replay | the same operation and request return the committed result with no new revision; a different request under the same id is refused |
| faint parity (battle and poison) | the death record (minus timestamps and run-bound ids), the link status, the released party keys and the queued peer `force_faint` are identical whether the batch arrives as `engine_signals` or inside an `observation` |
| heartbeat inventory | the checkpoint records with `party_hp_zero`, chains its predecessor through the batch operation, the transition digest is the result field, restore reproduces both components |
| acquisition | a grant receipt stays pending until a later checkpoint settles it; receipt and checkpoint in one batch settle at once; ordinals, identity, the link and both acquisition verifiers pass, before and after reopen |
| starter route | starter source signals then the stable checkpoint, both through batches, settle the exempt link |
| deferred heartbeat | while a faint command is pending for the peer, both players heartbeats are deferred; after the faint receipt the memorial obligations keep it deferred |
| hostile batches (7) | wrong ROM, context generation, physical instance, save identity, an unsettleable receipt kind, a missing field, an unenrolled player: refused, nothing commits |
| selection | `create_runtime(free_service=True)` persists and reopens the flag, the launch is `mode=free_service` shipping `lua/gen1_observation_loop.lua` and not the frame client; a held runtime refuses the event with `ProtocolError`; free plus ordinary is refused |

Neighbouring suites in the private copy (both patches applied): `test_gen1_engine_signal_runtime`,
`test_gen1_inventory_observation`, `test_gen1_acquisition_runtime`, `test_gen1_runtime_server`,
`test_gen1_runtime_client`, `test_gen1_runtime_trade`, `test_gen1_faint_runtime`,
`test_gen1_observation_provenance`, `test_gen1_launcher`, `test_gen1_frame_journal`,
`test_gen1_frame_acquisitions`, `test_gen1_starter_settlement`, `test_gen1_observation_loop`:
285 passed, 6 failed. Five are the pre-existing failures the proposals README lists
(confirmed failing in the shared scratch tree without these patches); the sixth,
`test_settlement_constants_match_pinned_cartridge_sources`, reads `.cache/pret` through a
junction that did not resolve in the private copy and passes in the shared tree.
Client-side suites that load the patched entry and observation module
(`test_gen1_composed_entry`, `test_gen1_inventory_observation_client`,
`test_gen1_engine_signals_client`, `test_gen1_observation_loop`, `test_gen1_initial_observation`):
59 passed. Lua parse gate: 301 files OK. `ruff check . --select E9,F6,F7,F81,F82`: clean.

## 6. Deliberately not done

- **The credit-path deletion.** A separate step, after root has run the loop live. File set
  from handoff item 3: `server/frame_progress.py`, `server/execution_window.py`,
  `server/gen1_frame_control.py`, `server/gen1_frame_journal.py`, `server/gen1_frame_runtime.py`,
  `server/gen1_native_frame_accounting.py`, `lua/execution_window.lua`, `lua/frame_pacer.lua`,
  `lua/gen1_frame_client.lua`, `lua/gen1_native_frame_client.lua`, the `frame_grant` and
  `frame_complete` events, the four `shared-*` contracts, their tests (about 35 files under
  `tests/unit/`), the `ordinary_frames` and `native_trade` selections in
  `gen1_runtime.py` / `gen1_run_config.py` / `gen1_launcher.py`, the `ordinary_frames` branch
  of `gen1_client_entry.lua`, and the `frame_complete` branches this patch sits beside in
  `gen1_observation_provenance.py` and `gen1_acquisition_runtime.py`. `ORDINARY_FILES` in the
  launcher then collapses into `SOURCE_FILES`.
- **Static, NPC exchange, wild encounter and evolution rows.** Their runtimes are welded to
  `frame_complete` (`gen1_static_lifecycle.py:235`, `gen1_npc_exchange_runtime.py:137,313`,
  `gen1_wild_encounter_runtime.py:37`, `gen1_evolution_runtime.py:38,431`,
  `gen1_storage_runtime.py:256`), all reserved. The handler refuses those kinds fail-closed
  (`SETTLED_KINDS`), so the loop cannot yet cross a wild encounter; rebinding them is the
  same shape as section 2, one stager each.
- **Storage jobs** (quarantine and linked disposition) are scheduled only by
  `gen1_storage_runtime.stage`, which requires `frame_complete`; not called here.
- **Reconnect.** Standalone staging compares the session metadata to the enrollment metadata
  by equality (`gen1_inventory_observation.py:146`, `gen1_engine_signal_runtime.py:82`,
  `gen1_starter_settlement.py:106`), so a re-admission (new session id and epoch) refuses
  every later batch; the compound path relaxed this to `same_admitted_context` through the
  frame origin. The relaxation belongs with the validator rewrite of item 2.
- **Items 4 and 5**: the executor map for every engine command and the in-battle window. The
  writer above is the placeholder they replace.
- **Heartbeat period**: the loop default of 30 frames stands (P4 owner decision).
