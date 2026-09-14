# C3 — whiteout automatic rebuild through the storage-job machinery (implementation spec)

Status: accepted (coordinator, 2026-09-14). Source: Gen1-CodexPeer task cx-3610046a at `53a390b`,
read-only. Claim: C3 claim row in RC_MASTER_GUIDE.md. Prerequisite: C1 frozen (record_death_obligation
in gen1_faint_runtime.py; settle_whiteout collateral loop in gen1_whiteout.py). Shared `state.py`
untouched; all new code is Gen 1.

## (1) Plan capture
- Call `gen1_rebuild_runtime.plan(stage, document, player, entry, index, captured)` after the
  collateral obligations are recorded and before `settle_whiteout` returns (captured at
  `gen1_whiteout.py:81-82`; collateral loop ends `:99`; HUD/return `:102-113`).
- Persist `components["gen1-rebuild"]["plans"][<whiteout-id>] = {schema, initiator, source: {player,
  operation_id, index, whiteout_id}, ordered_pairs: [{ordinal, keys: {a, b}, link_id, members: {a, b},
  source_refs, job_id: null, completed_ref: null}], phase, blocked_reason}`. Bind the order to
  `rebuild_pending.queued_keys/queued_partner_keys` and the captured `party_mon` commands; reject
  mismatches/duplicates, never reselect silently (`state.py:2034-2042,2434-2452`).
- Resolve members with the same initial-context identity lookup storage `_job` uses; box/slot is
  optional observed metadata with a checkpoint reference, not authority
  (`gen1_storage_runtime.py:208-241`).
- Keep `classify_death(captured, ...)` unchanged so the existing "REBUILD PENDING" feedback remains;
  plan creation never claims a physical restore (`gen1_whiteout.py:105-113`;
  `tests/unit/test_gen1_whiteout.py:95-99`).

## (2) Scheduler
- Narrow `schedule_rebuild(...)` wrapper around `storage_runtime._job(state, document, origin,
  "rebuild", keys, source={rebuild_id, ordinal, source_ref})`; `_job` persists the job/blocker and
  returns both `storage_observe` commands (`gen1_storage_runtime.py:201-251`). `stage()` /
  `schedule_pending()` are PC/acquisition entry points, not rebuild APIs (`:254-325,353-427`).
- One pair job active at a time. Never call `_job` while `_busy`; record the deferred plan and
  schedule from later faint/storage/memorial settlements. Stable source-derived origin so replay
  reuses the same job.
- `resolve(kind == "rebuild")`: require both current ALIVE linked identities; each exact target in
  party → confirm, in box → withdraw; either boxed target with physical `party_count >= 6` →
  explicit storage HOLD, no keep-boxed fallback (`gen1_storage_policy.py:81,96-104`;
  `gen1_storage.py:238-249`). A full side whose target is already in party needs confirm, not a
  capacity refusal. Fresh held storage reads, exact lineage/blob preimages; reserved-grave/dead/
  missing targets HOLD. A blocked rebuild is never expressed as a completed confirm-only pair.
- The existing Lua `storage_apply` executes the server-prepared delta/full-save receipt; no new
  withdrawal executor (`lua/gen1_held_storage.lua:1-35`; `gen1_storage.py:189-249`). Both sides need
  `isPartyWriteSafe` + `physical_stop_verified` (`lua/gen1_held_faint.lua:33-51`).
- Completion: after BOTH writes equal the prepared keys, exact hold and poststates validate, call
  `rebuild.completed(...)` in the same journal commit; require prepared keys exactly {a, b}, both
  targets in party, no refusal (`gen1_storage_runtime.py:681-719`). Only then feed shared
  `handle_event(initiator, {event: "sync_retrieve_done", key: initiator_key})`, drain its feedback,
  mark the pair completed with receipt refs; `_maybe_finish_rebuild` emits `rebuild_done` after all
  picks (`state.py:326-334,2479-2494`). Never `sync_retrieve_failed`.

## (3) Ordering with C1 collaterals and memorials (conditional, not universal)
- Finish pending_issue/pending_faint collaterals first. Before issuing memorial reads, use CURRENT
  physical counts to decide whether a minimum survivor pair fits or removable dead members must free
  slots first.
- Critical seam: faint ACK immediately calls `memorial_runtime.schedule`
  (`gen1_faint_runtime.py:310-334`). `memorial_runtime.schedule` must consult rebuild arbitration
  BEFORE enqueuing a last-member memorial, for all callers (`gen1_memorial_runtime.py:53-67`);
  otherwise its head command blocks the later restore.
- `_busy` (`gen1_storage_runtime.py:172-189`) is not bypassed globally: prevent inappropriate
  memorial issuance, complete already-owned work, then permit the selected rebuild job; add a plan
  priority gate so unrelated storage does not take ownership.
- Both sides have room → restore the first ALIVE pair, then memorialize dead members, then the
  remaining ordered pairs. One side full with >1 physical members → archive its eligible zero-HP
  dead member(s) first while deferring the other side's last-member memorial. No legal capacity
  action → HOLD with reason; never remove the last party member (`gen1_memorial.py:57-69`).
- Blackout timing is NOT solved by ordering: memorial refuses a target healed above 0 HP
  (`gen1_memorial.py:68-69`); freshly healed logically DEAD targets HOLD. Automatic re-faint /
  blackout interception is a separate authority — an explicit automation boundary of this card.

## (4) Restart reconciliation
- The persisted plan is authority; reconcile stable job ids and both completion receipts against it;
  never regenerate completed jobs or repeat `sync_retrieve_done`; keep completed plan/tombstone refs.
- `verify_state` in `gen1_runtime_state._verify_components` and `verify_journal` in the gen1_runtime
  audit path: source whiteout event, exact ordered picks, identities/link history, active job,
  completed receipt refs and shared `restored_keys` must agree (`gen1_runtime_state.py:115-164`;
  `gen1_storage_runtime.py:774-893`); storage replay validation learns rebuild source/refusals.

## (5) Tests (red first)
- Selected whiteout with two boxed ALIVE pairs today yields HUD but no rebuild storage job
  (`test_gen1_whiteout.py:75-99`): assert durable plan + deferred/first `storage_observe` according
  to outstanding faints. Reuse `faint()`/`two_mon_batch()` and storage `source()`, `read()`,
  `write()`, `complete_storage()`, `latest_job()`; real journal checks
  (`test_gen1_whiteout.py:27,102`; `test_gen1_storage_runtime.py:28,67,93,122,162`).
- First-side ACK leaves the plan pending; second verified ACK completes exactly one pair; final pair
  clears shared pending/banner. Corrupt-file ACK changes neither usable keys nor plan (oracle
  `test_gen1_storage_runtime.py:246`).
- Last-dead-member + reserve; asymmetric full-side capacity; both-full HOLD; healed-dead-target HOLD;
  changed/dead reserve HOLD; duplicate/reopen after each ACK; no reserve → run_over unchanged. Tests
  must distinguish `storage_observe` ACKs from `storage_apply` ACKs.

## (6) Files
NEW `server/gen1_rebuild_runtime.py`, NEW `tests/unit/test_gen1_rebuild_runtime.py`; edit
`gen1_whiteout.py`, `gen1_storage_runtime.py`, `gen1_storage_policy.py`, `gen1_faint_runtime.py`,
`gen1_memorial_runtime.py`, `gen1_runtime_state.py`, `gen1_runtime.py`; extend the whiteout/storage
tests. All Gen 1; `state.py` untouched. C1 overlap: `gen1_whiteout.py:95-113` and faint settlement
/ memorial scheduling — C1's final cut must be frozen first.

## (7) Falsifier
Any `restored_keys`/banner completion after only one side's ACK; any full-party refusal that drops a
pick; any memorial head that prevents the minimum restore; any replay that repeats a restore or
consumes a different reserve. The `linked` policy capacity fallback is unsuitable
(`gen1_storage_policy.py:96-104`).

## (8) Risks
"No new Lua" covers storage withdrawal only, not blackout-heal timing or re-fainting a healed dead
target (explicit boundary). Spec entries are proposed code, not existing behaviour.

## (9) Decision
READY WAIT(C1 accepted). Implementation on the C1 worker (holds the faint/whiteout context); single
writer across all listed files.
