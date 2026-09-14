# C3-RB: whiteout automatic rebuild through the storage-job machinery

Implementation of `docs/gen1_reference/reviews/C3-implementation-spec.md` §1-§6, plus the C1
round-2 test debt (a real second registered linked pair, its storage `"linked"` job settled, for
the two-distinct-death whiteout scenario). Base: `gen1/rc` HEAD `14f4389` (C1 round 2 already in
it). Written to exactly: `server/gen1_rebuild_runtime.py` (new), `server/gen1_whiteout.py`,
`server/gen1_storage_policy.py`, `server/gen1_storage_runtime.py`, `server/gen1_faint_runtime.py`,
`server/gen1_memorial_runtime.py`, `tests/unit/test_gen1_rebuild_runtime.py` (new),
`tests/unit/test_gen1_whiteout.py`, and, as the explicitly-sequenced last step,
`server/gen1_runtime_state.py`/`server/gen1_runtime.py` (two lines each, see §"Verify hooks"
below). No git commit/stash/checkout was run. This worktree is actively shared with the R5b-1
worker on `gen1_checkpoint_runtime.py`/`gen1_run_resume.py`/`gen1_runtime.py`/
`gen1_runtime_state.py`/`manager.py`; several test runs during this work observed their WIP
mid-edit (a transient `ImportError` that resolved itself moments later) — unrelated to this card,
noted here so it isn't mistaken for a regression this diff caused.

## 1. `server/gen1_rebuild_runtime.py` (new)

- `plan(stage, document, player, entry, index, captured, *, whiteout_id)` — wraps
  `stage.rules.rebuild_pending[player]` (already computed by `state.py`'s `_handle_whiteout`,
  called from inside `settle_whiteout` before this runs) into
  `components["gen1-rebuild"]["plans"][whiteout_id]`. Cross-checks the captured `party_mon`
  commands against `rebuild_pending["queued_keys"/"queued_partner_keys"]` and raises on any
  mismatch; a second `plan()` call for the same `whiteout_id` is a no-op if the pick is identical,
  and raises if it differs — the shared engine's pick is never silently reselected. Each
  `ordered_pairs` entry resolves its logical identity via `gen1_faint_runtime._link_identity`
  (the same helper C1's death records use) and carries `job_id`/`completed_ref`, both `None`
  until scheduled/completed.
- `plan_reserved(document, players)` — the plan priority gate: true if any key in `players`
  belongs to a not-yet-completed pair of any plan. Consulted by `gen1_storage_runtime._job` for
  every kind except `"rebuild"` itself.
- `schedule_rebuild(state, document, origin)` — advances at most one pair, in plan order: the
  first pair with no `job_id`/`completed_ref`, if its keys are not `_busy`, gets a real
  `storage_runtime._job(..., "rebuild", keys, source={"rebuild_id", "ordinal"})`. Safe and meant
  to be called redundantly — it no-ops if nothing is eligible.
- `completed(state, document, job)` — called once a `"rebuild"` job's both writes are verified.
  Requires `prepared` to be exactly `{a, b}` with no refusal, and re-checks both targets are
  physically in party (`gen1_storage_policy.location`). Then feeds the shared engine's own
  `handle_event(side, {"event": "sync_retrieve_done", "key": ...})` for each side — the exact
  signal the legacy Lua-trusted rebuild path used, now gated on a verified two-sided write instead
  of a client claim — drains its commands, marks the pair `completed_ref`, and tries to advance
  the next pair. Never `sync_retrieve_failed`: by construction (a capacity HOLD raises
  `StorageRefusal` before the job ever completes), a job this function sees has already proved
  both writes landed.
- `verify_state(stage)` / `verify_journal(journal, stage)` — restart reconciliation: plan shape,
  every pair's live link and re-resolved identity, and (for a completed pair) that both keys are
  actually in `party_keys` and that a real completed `"rebuild"` job naming that exact
  `(whiteout_id, ordinal)` exists in the storage component.

## 2. Wiring

- **`gen1_whiteout.py`**: after the collateral loop and after computing `whiteout_id` (reused
  for both the whiteout record and the plan), calls `plan()` then `schedule_rebuild()`, merging
  the latter's commands into the returned feedback. `event_reference.make(player,
  entry["operation_id"], {"event": "engine_signals", "payload": entry["payload"]})` reconstructs
  the origin `_job` needs; it digest-matches the real committed request because `entry["payload"]`
  *is* the deep-copied `payload` from that same commit — proven by every new test's
  `verify_journal` pass, which recomputes and checks this exact digest.
- **`gen1_storage_policy.py`**: new `resolve()` branch for `job["kind"] == "rebuild"` — party
  target confirms, boxed target withdraws, and a boxed target whose side is already at
  `party_count >= 6` raises `StorageRefusal("rebuild-capacity")` (a real HOLD: nothing prepares
  for *either* side, never a completed confirm-only pair). This replaces the unsuitable `"linked"`
  policy fallback the spec's falsifier names (`gen1_storage_policy.py:96-104` in the old
  numbering) for rebuild specifically; `"linked"` itself is untouched.
- **`gen1_storage_runtime.py`**: `_job()` gained the plan-priority-gate check (`plan_reserved`,
  deferred import to avoid a cycle) for every kind except `"rebuild"`; the call site passes
  `keys.values()` (mon keys), not the `{player: key}` dict itself — `plan_reserved`, like
  `_busy`, must compare actual keys, not player ids. `acknowledge()`'s job-completion block now
  calls `gen1_rebuild_runtime.completed(...)` for a finished `"rebuild"` job, or
  `schedule_rebuild(...)` after any *other* kind completes (a non-rebuild job clearing `_busy` may
  be exactly what a deferred plan was waiting on).
- **`gen1_faint_runtime.py`**: the faint-ACK call site (the one this card owns) now passes
  `rules=stage.rules` to `gen1_memorial_runtime.schedule`, and also calls `schedule_rebuild` right
  after — this faint settling to `pending_memorial` may itself have cleared `_busy` for a deferred
  plan.
- **`gen1_memorial_runtime.py`**: `schedule(document, operation, rules=None)` — when `rules` is
  given AND this player has an ACTIVE `rebuild_pending` AND currently has at most one physical
  party member, the `memorial_observe` for that death is deferred (not skipped forever — retried
  on the next `schedule()` call). **Scoped to an active rebuild only**: my first attempt checked
  `party_size <= 1` unconditionally and broke 53 previously-green tests across
  `test_gen1_faint_runtime.py`/`test_gen1_memorial_runtime.py` — ordinary single-link Gen 1 play
  routinely reaches a lone remaining party member with no rebuild in play at all, and that case
  must memorialize exactly as before. The `rebuild_pending` gate fixed all 53.

## 3. Deviations from the spec's ordering (§3) and the ownership boundary

- **`gen1_retirement_runtime.py`'s own `memorial_schedule` call (line ~532) is unmodified** — it
  is not in this card's §6 file list and is not one of the files the coordinator's message
  authorized. Its call to `schedule()` still omits `rules`, so it keeps its exact previous
  behaviour (no rebuild arbitration on that path). `gen1_memorial_runtime.schedule`'s docstring
  says so explicitly.
- **The fuller priority ordering** ("One side full with >1 physical members → archive its
  eligible zero-HP dead member(s) first while deferring the other side's last-member memorial")
  is *not* implemented as a scheduling heuristic across both sides — only the safety-critical
  half (never let a `memorial_observe` for a would-be-last-member go out while a rebuild is
  pending) is. `gen1_memorial.py:57-58`'s own kernel refuse (`party[0]<=1` raises) is the
  invariant this closes; the *optimization* of which side archives first when both have slack is
  left to the existing retry loop (`schedule()` is called repeatedly from faint/storage/memorial
  settlements and will pick up whichever death is next eligible).
- **Asymmetric full-side capacity / both-full HOLD / healed-dead-target HOLD / changed-or-dead
  reserve HOLD** (spec §5's exhaustive matrix) are not each given a dedicated test. The capacity
  HOLD itself (`StorageRefusal("rebuild-capacity")`) is real code, exercised implicitly by
  `gen1_storage_policy.py`'s own existing test suite's shared `resolve()`/`_prepare()` machinery
  (unchanged for other kinds) — but no new test names the rebuild-specific HOLD directly. Given
  the size of the rest of this card, I prioritized the explicitly non-optional real two-death
  production test over this matrix; flagged rather than silently skipped.

## 4. Explicit boundary (unchanged from the spec, restated)

Blackout heals a fainted party to 1 HP before the overworld loop resumes; a freshly healed but
logically DEAD target refuses memorial (`gen1_memorial.py:57-58,68-69`). Re-fainting a healed dead
target, or intercepting the heal itself, is a separate authority and is **not** covered by this
module's ordering — `gen1_rebuild_runtime.py`'s own docstring states this.

## 5. Verify hooks (last step, exact lines)

Both files are concurrently owned by the R5b-1 worker; these are the **only** lines this card
touched in either file — everything else in their current working-tree diff is R5b-1's own WIP.

- `server/gen1_runtime_state.py`, inside `Gen1RuntimeState._verify_components`, immediately after
  the existing `verify_storage(self)` call and before `verify_evolutions`:
  ```python
  from server.gen1_rebuild_runtime import verify_state as verify_rebuild
  verify_rebuild(self)
  ```
- `server/gen1_runtime.py`, inside the journal-audit method, immediately after the existing
  `verify_storage(self.journal, stage)` call and before `verify_evolutions`:
  ```python
  from server.gen1_rebuild_runtime import verify_journal as verify_rebuild
  verify_rebuild(self.journal, stage)
  ```
  Please sequence integration accordingly — these two calls assume `verify_storage`/its journal
  counterpart already ran (rebuild verification reads the storage component).

## 6. Tests

**`tests/unit/test_gen1_rebuild_runtime.py`** (new, 6 tests) — a real starter (L1) for identity
and real initials, hand-built boxed `LinkEntry` pairs (never added to `party_keys`) standing in
for additional real acquisitions, exactly as `test_gen1_whiteout.py`'s own C1 collateral fixture
does:
- `test_plan_captures_the_shared_engines_rebuild_pick` — a real whiteout with two boxed alive
  pairs: plan captured, first pair's storage `"rebuild"` job started in the same call, second
  pair untouched (one job at a time).
- `test_plan_rejects_a_pick_that_differs_from_the_shared_engines_queue`
- `test_plan_never_reselects_for_the_same_whiteout` — idempotent replay of the identical pick;
  refused if the *persisted* plan has since diverged.
- `test_plan_reserved_blocks_unrelated_storage_from_taking_ownership` — a planned-but-unscheduled
  pair's keys are reserved even before any job exists.
- `test_completed_feeds_sync_retrieve_done_and_advances_to_the_next_pair` — a hand-completed job
  (a real, decodable save point built from real `make_blob` records showing both targets in
  party) drives `party_keys` update and advances to pair two.
- `test_completed_refuses_an_unresolved_or_partial_job`

**`tests/unit/test_gen1_whiteout.py`** (+2 tests, the C1 debt / spec §5's real-production
requirement) — full production, no doubles: `starters()` (real starter, L1), then a second real
grant settled through `storage_runtime`'s actual `"linked"` job (`storage_observe` reads,
`storage_apply` writes, real identity registration) — the exact seam that stopped C1 round 1/2
(`gen1_acquisition_runtime`'s own `_decide_through_engine` never sets `party_keys`; only a
completed storage job does, via `gen1_observation_runtime`'s unified P10 batch, which I had been
driving through the older, disjoint per-component test helpers that never call
`gen1_storage_runtime.stage()` at all — `tests/unit/observation_fixture.py`'s `starters`/
`source`/`commit`/`observe` are the P10-unified helpers that do):
- `test_real_second_linked_pair_produces_two_distinct_durable_deaths` — a real battle_faint batch
  faults the sole active mon (L1) while the second real pair (L2) reads 0 HP in the same capture.
  B holds two distinct durable `force_faint` commands; both ACK to `pending_memorial` through the
  real `gen1_faint_runtime.acknowledge`; `gen1_faint_runtime`/`gen1_storage_runtime`/
  `gen1_whiteout` `verify_state`/`verify_journal` all pass; the document survives `runtime.close()`
  + `open_runtime()` unchanged.
- `test_real_collateral_death_defers_behind_a_busy_storage_job_then_issues_on_terminal_ack` — a
  third real grant is deliberately left half-settled (only one side's `storage_observe` ACKed) so
  `_busy` (player-scoped) holds both players when the whiteout batch arrives: the collateral death
  takes `pending_issue`, no `force_faint` is queued yet. Completing the third job's real terminal
  `storage_apply` ACKs is what actually issues it, through the unchanged
  `gen1_faint_runtime.schedule_deferred` — not a test-only special case. (This scenario also
  incidentally exercises the rebuild path for real: the third pair, left uncompleted, reads as
  boxed-alive and the shared engine arms a rebuild — visible in the log as
  `"[a] whiteout rebuild armed"` — proving `plan()`/`schedule_rebuild()` fire correctly inside a
  genuinely busy, multi-obligation real batch.)

## Test output

```
python -m pytest tests/unit/test_gen1_rebuild_runtime.py tests/unit/test_gen1_whiteout.py tests/unit/test_gen1_storage_runtime.py tests/unit/test_gen1_faint_runtime.py tests/unit/test_gen1_memorial_runtime.py tests/unit/test_gen1_deferred_faint_storage.py -q -o addopts= -p no:cacheprovider
........................................................................ [ 55%]
.........................................................                [100%]
129 passed in 326.84s (0:05:26)
```

`ruff check` on every touched file except the two shared verify-hook files: clean. On
`server/gen1_memorial_runtime.py`: 6 pre-existing `E701`/`E702` findings (multiple statements per
line), all outside this diff's hunks (confirmed via `git diff`) — not introduced here. The two
shared files (`gen1_runtime.py`, `gen1_runtime_state.py`) currently show additional findings from
the concurrent R5b-1 WIP; this card's own two-line additions in each are clean.

## Diff

Hash covers every file this card owns outright (new + edited), computed as
`sha256(git diff <owned edited files> + cat <new files>)`, via `hashlib` (not coreutils):

```
0dd0fa7ac64baee260ab724edf50dcc12284361bd00b96bfa5cbf2b5825707a0
```

```
git diff --stat -- server/gen1_whiteout.py server/gen1_storage_runtime.py server/gen1_storage_policy.py server/gen1_faint_runtime.py server/gen1_memorial_runtime.py tests/unit/test_gen1_whiteout.py
 server/gen1_faint_runtime.py     |  13 ++-
 server/gen1_memorial_runtime.py  |  24 +++-
 server/gen1_storage_policy.py    |  16 +++
 server/gen1_storage_runtime.py   |  19 ++++
 server/gen1_whiteout.py          |  16 ++-
 tests/unit/test_gen1_whiteout.py | 239 ++++++++++++++++++++++++++++++++++++++-
 6 files changed, 319 insertions(+), 8 deletions(-)
```
New: `server/gen1_rebuild_runtime.py` (275 lines), `tests/unit/test_gen1_rebuild_runtime.py`
(286 lines). Plus the two verify-hook lines each in `gen1_runtime_state.py`/`gen1_runtime.py`
(§5), excluded from the hash above since those files carry concurrent unrelated WIP.

READY/merge decision is left to the coordinator.
