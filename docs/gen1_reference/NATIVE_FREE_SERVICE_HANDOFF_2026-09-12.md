# Native trade on the free_service path: handoff, 2026-09-12

Branch `claude/gen1-native-free-service`, worktree `.claude/worktrees/gen1-native-free-service`, base
`gen1/rc` 5ff5f17, implementation commit db8dd7a (pushed with this page). Working tree clean. Delegated by
Codex as cx-ed33518b (source map + blockers) and cx-94dfe897 (break handoff). Owner's direction: wrap up;
Codex is preparing the overall RC handoff separately. No emulator was used in this lane; EmuHawk stays under
Codex's lane coordination (the performance and memory-boundary owners last held it).

## 1. What exists (source map, verified 2026-09-12 against 5ff5f17)

- The production client (`lua/gen1_client_entry.lua`) is free_service only: `:20` refuses
  `native_manifest`; `:70-71` is a plain `platform_execution` host; the journal opens without
  `Native.journal_options` (`:87`); only the faint executor is routed (`:120-122`, `:237-239`);
  `writer_pending` (`:252-254`) ignores native `frames_pending`; `inventory()` (`:264-273`) has no
  receptionist-checkpoint path; `hard_revoke` (`:135-147`) never closes a native runtime.
- The old native composition (`git show 48c64d0^:lua/gen1_client_entry.lua:21-24,70-81,101-103,183-200,340-349`)
  required `ordinary_frames==true` (tier 1, deleted) and was mutually exclusive with free_service.
- Ownership primitives available today: held one-use writes (`gen1_held_faint.lua:132-140`,
  `held_write_permit` uses:1 ttl<=1000) patch bytes under a halted CPU; the battle instruction window
  (`instruction_executor.lua:33-66`, `instruction_authority.py:30,141-179`) patches bytes when a pinned PC
  is reached, <=64 frames, one use, and cannot transfer control to ROM; `gen1_write_safety.lua:49-51`
  refuses any link/serial/cable-club state. Neither can drive the trade routine.
- The only primitive that runs the ORIGINAL ROM routine under ownership is the kept tier-2 pair:
  `platform_bounded_execution.step_one` (`lua/platform_bounded_execution.lua:129-167`, one core step under
  exclusive hold) authorized per frame by `execution_window.consume` from server grants of <=60 frames /
  1000 ms (`gen1_native_execution.py:156`, ceiling 60000).
- Tier-2 still leans on the retired `gen1-frame-progress` ledger: `gen1_native_frame_client.lua:60-61`,
  `gen1_native_frame_accounting.persist_grant:618-621` (no-op without the ledger),
  `gen1_native_observation._read_checkpoints` (ledger anchor; fixed for free entries in db8dd7a),
  `handoff_status:912-963`.
- Continuity and native are exclusive server-side: `gen1_runtime.py:220-221`,
  `gen1_service_continuity.py:367-368, :417-421` (the latter blocks on any trade outside {cancelled,
  completed}, not the coordinator's TERMINAL set).
- Manager cannot produce a native-capable run: `manager.py:770-774` (clean contract, no
  prepared_cartridges/native_trade), `:732-734` (launcher never passes native_trade); clean profiles carry
  `pc_trade:false`. `install_native_execution` already accepts canonical companion profiles when no
  reproduced cartridges are present (`gen1_native_binding.py:32-37`); `PreparedCartridges.__init__` re-runs
  the UPR jar on every `read_bound_configuration` (`gen1_prepared_cartridges.py:82-86`).
- Both-peer authorization and prepared state are in memory only: `NativeTradePolicy.prepared`
  (`gen1_native_policy.py:91-107`), `execution.observed` (`gen1_native_execution.py:117-119,133-139`,
  `gen1_full_save.py:228,241-245`); the journal keeps `checkpoint_digest`/`boxed_keys` and the ready/applied
  receipts inside command acknowledgements.
- Post-COMMIT forward recovery does not exist: `recovery_required` (`gen1_runtime.py:184,295-298`,
  `trade_coordinator.py:508-510`) stops `NativeTradePolicy.authorize` (:55), `NativeExecutionPolicy` (:76),
  `TradeDriver` (:137) and `authorize_delivery` (:516-527); only `finalize` clears it (:495). The only thing
  that proceeds is a unit-test policy knob (`tests/unit/test_trade_coordinator.py:313`).

## 2. Decisions taken (Codex, 2026-09-12, binding for this lane)

1. Ordinary gameplay stays free_service with NO frame-loan / `gen1-frame-progress` ledger.
2. Exclusive-hold `platform_bounded_execution.step_one` + `execution_window` are retained ONLY for the original
   native trade routine, with per-frame server authority and `loop:observe()` between steps.
3. Unified prepared-artifact contract: first prove Manager create/download with the canonical
   companion-patched clean pair (patcher-shipped, no Java on launcher GET), then UPR/PreparedCartridges
   through the same pinned interface; cache per-run artifact validation; never infer patched from clean; no
   randomized-playthrough claim until the UPR path is exercised.
4. Order: free native checkpoint bridge and durable both-peer ready/full-save/lease records first; while
   `active_trade` is set, read-only native checkpoints and CONTROL may be admitted but ordinary
   acquisition/storage/evolution/rule mutations are quarantined.
5. Post-COMMIT is irrevocably forward-only: if the exact durable lease plus fresh physical/save readback cannot
   classify a half-complete state, hold both sides (recovery required); never guess, never retry a mutating
   routine, never roll back. An explicit unknown-classifier/proof matrix and a controlled mid-routine live
   probe come before any forward action is enabled.
6. Idle continuity only with the coordinator's TERMINAL set {cancelled, declined, expired, link_committed} and
   empty journal/native obligations.
7. Before Manager/client composition: send the classifier matrix and remaining unknowns.

## 3. Implemented and proven (db8dd7a)

Free-run checkpoint bridge, server side only:
- `gen1_observation_runtime`: optional `native_checkpoint` on the batch (typed; requires the same-batch
  inventory; deferred with it behind any open obligation; `native_checkpoint_digest` /
  `native_checkpoint_deferred` in the result). Quarantine: with `active_trade` set, a batch carrying signals,
  acquisitions, a trainer engagement or a battle byte is refused; heartbeat-only batches keep the sequence
  alive.
- `gen1_native_observation.stage_free`: same entry shape plus `anchor.inventory_sequence`; free entries are
  current exactly while they belong to the player's latest committed inventory observation
  (`_current_free`), audited against the observation batch and the inventory record (`_verify_free_origin`);
  the ledger path is unchanged.
- Tests (`tests/unit/test_gen1_native_observation.py`, 13 passed): anchor/verify/stale/current-again/reopen;
  four faults commit nothing; deferral behind a pending faint. Focused suites green: native observation,
  observation runtime, provenance, inventory observation (95 passed). A broad native-adjacent selection was
  started and stopped by Codex for the owner's break; it has NO verdict, and in this fresh worktree it also
  errors on the absent `.cache/pret` symbols (environment, not code). The `active_trade` quarantine guard has
  no dedicated test yet.

## 4. Not done, in order (each a tested commit; nothing speculative was left in the tree)

1. Durable native windows: journal every issued native grant without the ledger (new component, e.g.
   `gen1-native-windows`, mirroring `policy.observed`/`published` so `verified()` and release survive a
   restart); make `persist_grant` use it when the player is not ledgered.
2. Durable preparation: `NativeTradePolicy.checkpoint()` falls back to the ready receipt in the journal
   (`receipt.stages.ready.checkpoint`, digest-checked against `trade.ready[player].details.checkpoint_digest`);
   full-save point from `stages.save.point`; lease token from the commit intent. Add the `active_trade`
   quarantine test for observation batches.
3. Forward-only recovery: classifier on reopen with `recovery_required` from the durable COMMIT record, the
   lease token and fresh readback at the next write-safe checkpoint, classes {not_applied, applied_unverified,
   applied_verified, saved, unknown -> hold}; re-issue the same commit/verify/finalize commands with the same
   lease token; never abort after COMMIT. Matrix and unknowns go to Codex BEFORE any client/Manager work.
4. Client composition on the free entry (accept `native_manifest` with free_service; bounded host on
   `hold_mux`; `Native.journal_options`; `command_service_router(faint, native)`; `writer_pending` covering
   native `frames_pending`; bounded stepping inside `writer.service` with `loop:observe()` between steps;
   `pump_native` per tick; receptionist checkpoint in `inventory()`; `hard_revoke` closes native; send
   `native_checkpoint` with every heartbeat). Launcher: FREE_FILES + NATIVE_FILES; `bizhawk_launch` manifest
   carries the final sha1 and native manifest digest. Continuity aligned with TERMINAL.
5. Manager: native-capable Gen 1 run creation (companion-patched clean pair first), `native_trade` through
   `handle_launcher`, per-run cached artifact validation.

## 5. Open unknowns (post-COMMIT)

- Whether a client killed inside `SavePartyAndDexData` leaves a state classifiable from readback alone
  (party image vs `TradeResultRules` prediction, save region vs before/after) without a live probe. Needs
  the controlled mid-routine live experiment under Codex's emulator lane.
- Whether the Lua lease store (`gen1-native-trade-lease-v1`) survives a savestate load that rewinds the
  cartridge past COMMIT; if not, load-state after COMMIT must be a permanent hold.
- Whether continuity with a `link_committed` trade on the journal needs the release receipt first.

## 6. NO-GO gates for this lane

- No native launch on a production run until steps 1-3 are proven by unit/integration tests and the
  classifier matrix has Codex's sign-off.
- No emulator run without Codex granting the lane; no live claim from any interrupted suite.
- No cross-generation or manifest/inventory edits from this lane; the release rows stay untouched.
