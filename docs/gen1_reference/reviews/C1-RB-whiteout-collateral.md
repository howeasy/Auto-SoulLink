# C1-RB whiteout collateral force-faint — ROUND 2 (candidate 8ea6f25 rejected; fixed)

`settle_whiteout` (`server/gen1_whiteout.py`) previously discarded the entire engine-signal batch
with `JournalError("whiteout found a linked party member its faint settlement left alive")`
whenever `_handle_whiteout` (`server/state.py:2013`) legitimately force-faulted a *second*
still-ALIVE linked pair during a full-party wipe (CLAUDE.md "Whiteout": every partner of a
remaining linked party mon gets force-fainted). That guard was written to catch a genuine
duplicate — the triggering mon's own link being re-killed — but it fired on any force_faint the
whiteout produced, collateral or not, and a raised `JournalError` there discards the whole staged
transaction (`server/gen1_engine_signal_runtime.py:34`: "Discard both detached values if
validation fails"), so B received *nothing*, not even the already-settled triggering death. This
lands the fix: collateral deaths are now recorded as real, ack-able obligations instead of
silently dropped, while the genuine-duplicate case still refuses.

Owner: this worker (C1 implementation). Round 1 was committed as candidate `8ea6f25` and
adversarially reviewed: **REJECT** — the collateral branch's decoded-kind check could never pass
`verify_state` on restore, and the round-1 positive test never called `verify_state`, so it never
caught this. This is round 2 on the same four files, base `6ae72a9`, HEAD `0dd29bc` at dispatch
(candidate `8ea6f25` already in it). Canonical checkout
`E:/Google Drive/SLink/.claude/worktrees/gen1-rby-code-sweep-8d06e2`, branch `gen1/rc`; HEAD at this
report: `cbd8dc19c00b211bfd2e803468f3901c25f06e07` (actively shared worktree; other agents' concurrent
commits/edits — R5a, manager.py, paired_save_checkpoints.py, etc. — landed during this work and are
excluded from this report's diff, which is scoped to the three touched files below). Writes touched
exactly the four files the card named: `server/gen1_whiteout.py`, `server/gen1_faint_runtime.py`,
`tests/unit/test_gen1_whiteout.py`, and this report. No git commit/stash/checkout was run.

This corroborates and closes the gap the prior successor reports modeled: [C1-repro-successor.md](C1-repro-successor.md)
reproduced the exact `JournalError` through the real public runtime with two source-qualified
linked pairs, and flagged the hard part — "A collateral Lapras record cannot truthfully reuse the
Eevee's decoded key" (persisted-death verification expects a decoded `faint` signal whose key
matches). [C1-reachability-successor.md](C1-reachability-successor.md) found a **source-supported
natural route** to the collateral-ALIVE condition (a pre-activation faint observed while rules are
inactive, so that link is never individually settled before a later whiteout). This report is the
first to actually change behavior rather than model it.

## Diff (round 2 increment, on top of committed candidate `8ea6f25`)

```
git diff --stat -- server/gen1_whiteout.py server/gen1_faint_runtime.py tests/unit/test_gen1_whiteout.py
 server/gen1_faint_runtime.py     |  26 +++++-
 server/gen1_whiteout.py          |   2 +-
 tests/unit/test_gen1_whiteout.py | 225 ++++++++++++++++++++++++++++++--------
 3 files changed, 198 insertions(+), 55 deletions(-)
```

SHA256 of `git diff -- server/gen1_whiteout.py server/gen1_faint_runtime.py tests/unit/test_gen1_whiteout.py`
(computed via `hashlib.sha256`, not the coreutils tool):

```
cf1843a09daae43b48dd7ad2e1a6af5599c3a2b1b1e837707c6781dfba108ca5
```

## Round-2 findings → fix → test

| # | Finding (reviewer) | Root cause | Fix | Red test → green |
|---|---|---|---|---|
| 1 | Wrong discriminator: `verify_state`'s decoded `row` from `verified_source`/`validate_batch` reports `kind=="faint"` for **both** `battle_faint` and `poison_faint` (`gen1_engine_signals.py:88,93`); the round-1 collateral branch checked `row["kind"] not in ("battle_faint","poison_faint")`, which is never true, so every collateral row raised `"collateral death differs from source evidence"`. | Conflated the *decoded* row (always `"faint"`) with the *raw* signal kind. | `gen1_faint_runtime.py` collateral branch now checks `row["kind"] == "faint"` (like the primary path) and separately reads `raw_kind = death["engine_record"]["payload"]["signals"][death["index"]]["kind"]`, requiring `raw_kind in ("battle_faint","poison_faint")`. Also checks `row["key"] == trigger["key"]` (the decoded row is the *trigger's* evidence, not the collateral's own). | `test_two_alive_links_whiteout_produces_collateral_force_faint` now builds a **real, decodable** `entry["payload"]` via `two_mon_batch()` and calls `gen1_faint_runtime.verify_state`/`wo.verify_state` after `settle_whiteout` — round 1's version never called either, so it "passed" while masking exactly this bug. Confirmed red against round-1 source (the unconditionally-false raw-name check), green after the fix. |
| 2 | Cause mismatch: shared `_handle_whiteout` always sets `link.cause = "whiteout"` (`state.py:2062`) for a collateral retirement, but the shared per-death check required `link.cause == row["cause"]` (`"battle"`/`"poison"`, decoded from the *trigger's* signal) — always false for collateral. | The shared `link.cause`/`row["cause"]` equality check assumed every death's cause traces to its own decoded signal; untrue for collateral. | `expected_cause = "whiteout" if "collateral_of" in death else row["cause"]`, compared against `link.cause`. Primary-path comparison unchanged. | Same fixture/test as #1 — `faint_verify_state(fake)` exercises this comparison for the collateral record (`link.cause=="whiteout"`) and is asserted green; the primary record's comparison (unchanged code path) stays covered by all pre-existing green tests. |
| 3 | Collateral binding: nothing proved the trigger really caused a whiteout, that the collateral key differs from the trigger's, or that `peer_key`/`link_id`/`members` bind to the *actual* rule link. | Round-1 anchored only on `(engine_record, index)` equality — insufficient once #1/#2 are fixed, since a forged collateral record could still name the wrong link/peer/trigger. | Added: (a) `document["components"][gen1_whiteout.COMPONENT].get(collateral_of) is not None` (a real settled whiteout exists for the trigger); (b) `death["key"] != trigger["key"]`; (c) `getattr(stage.rules.find_link(player, death["key"]), peer).key == death["peer_key"]`; (d) `_link_identity(stage, initials, that_link) == (death["link_id"], death["members"])`. | New `test_collateral_death_binding_is_refused_when_tampered`, parametrized over `non_whiteout_trigger`, `unrelated_pair`, `wrong_peer_key`, `reused_trigger_key`, `swapped_identity` — each starts from the green fixture, corrupts exactly one binding, and asserts `verify_state` raises. All 5 pass (refused). |
| 4 | Need a real two-player-runtime test (real registered linked members, real activation, real battle_faint batch) exercising validate→commit→reopen, two distinct death_ids, and both real ACKs to `pending_memorial`. | — | Partially done; see deviation below. | See "What changed vs. what's still MODEL-only." |
| 5 | Deferred case: a collateral death behind a busy storage job must take `pending_issue`, issued only at the actual storage ACK. | `record_death_obligation` already checks `_storage_jobs` generically (shared with the primary path) — untested for a collateral death specifically. | No source change needed; behaviour was already correct once `record_death_obligation` was reused for collateral in round 1. | New `test_collateral_death_defers_behind_a_busy_storage_job`: injects an incomplete `gen1-storage-settlement` job for the collateral pair's keys, asserts the collateral record is `phase=="pending_issue"` with `deferred["origin"] is None` and no `force_faint` in the returned feedback, and that `verify_state` still accepts it. |
| 6 | Typo `force-faulting` → `force-fainting`. | — | `server/gen1_whiteout.py:100` fixed. | Covered incidentally by every passing test that reaches that log line; no dedicated assertion (it's a log message). |

## Tests

`tests/unit/test_gen1_whiteout.py` now has a shared `_collateral_fixture(tmp_path)` (real
`create_runtime`/`paired()` for L1's identity+initials, a real, decodable `two_mon_batch()` engine
signal batch as `entry`/`index`/`signal`, L1's own faint settled first via the real
`rules.handle_event`/`take_commands`, then `record_death_obligation` called directly for the
trigger) used by four tests:

- `test_two_alive_links_whiteout_produces_collateral_force_faint` — the positive case, now also
  calling `gen1_faint_runtime.verify_state` and `wo.verify_state` (round 1's gap).
- `test_whiteout_still_refuses_a_genuine_duplicate_of_the_triggering_mon` — unchanged from round 1.
- `test_collateral_death_binding_is_refused_when_tampered` — 5-way parametrized negative matrix
  (finding #3).
- `test_collateral_death_defers_behind_a_busy_storage_job` — finding #5.

Exit-criteria run, this worktree, `PYTHONDONTWRITEBYTECODE=1` (writing `.pyc` into the shared
worktree is blocked by the sandbox as a shared-resource modification):

```
python -m pytest tests/unit/test_gen1_whiteout.py tests/unit/test_gen1_faint_runtime.py tests/unit/test_gen1_memorial_runtime.py -q -o addopts= -p no:cacheprovider
........................................................................ [ 75%]
........................                                                 [100%]
96 passed in 145.70s (0:02:25)
```

(24 whiteout + 37 faint_runtime + 35 memorial_runtime = 96. `tests/unit/test_gen1_runtime_state.py`
does not exist in this checkout, so it was omitted per the exit instruction. Also ran
`tests/unit/test_gen1_deferred_faint_storage.py` — 3 passed — as an extra check on the shared
`verify_state`/`identifier` change; not part of the stated exit criteria.)

`ruff check server/gen1_whiteout.py server/gen1_faint_runtime.py tests/unit/test_gen1_whiteout.py`
→ `All checks passed!` (no findings, new or pre-existing, on the three touched files).

## What changed vs. what's still MODEL-only (finding #4)

I attempted the full production path the reviewer asked for: two real acquisitions
(`grant:eevee:0` / `grant:lapras:0`, mirroring `C1-repro-successor.md`) through
`gen1_acquisition_runtime.py`'s real `record()`/`stage_acquisitions` — both settled with real
identities, real `stage.identities.create_link` link ids, and real party-checkpoint continuity
(confirmed by log lines `Linked <key> ↔ <key> in <area>` for both pairs). This *is* real for the
part findings #1-#3 are actually about: identity/link formation and the `verify_state` binding.

What I could **not** complete in the time available: after both grants settle, Gen 1's
`party_keys` (the "is this mon physically carried in the party" bookkeeping `_handle_whiteout`
reads) is deliberately **not** set by `gen1_acquisition_runtime.py` itself — the module's own
docstring says usability is "published only by its proved physical disposition (callers own
`party_keys`)". For a second real link that disposition is a `gen1_storage_runtime.py` "linked"
job requiring its own prepared/read/write ACK cycle (the same machinery
`test_gen1_deferred_faint_storage.py` drives for the primary force-faint path, and that
`test_gen1_storage_runtime.py`'s `complete_storage()` helper drains generically) — but no existing
test exercises a "linked" job specifically (`grep -rn '"linked"' tests/unit/test_gen1_storage_runtime.py`
is empty), and reverse-engineering its prepared/read/write receipt shapes from source alone did not
converge before the time budget on this round ran out.

**Deviation:** the four positive/negative unit tests above use the real starter+rules engine for
L1 and a hand-built `LinkEntry` + minimal `_FakeIdentities`/`_FakeBlockers` doubles for L2, exactly
as round 1 did — `_link_identity`'s interaction with the *real* `IdentityRegistry` for a second
capture remains covered only by other suites (`gen1_starter_settlement`, `gen1_acquisition_runtime`),
not end-to-end through this exact whiteout scenario. The real-runtime ACK-to-`pending_memorial`
proof (validate→commit→reopen, two ACKs) that finding #4 specifically asked for is **not done**.
I flag this explicitly rather than claim it: the two-real-grant setup (proving identity/link
formation is genuine) is committed nowhere — it lives only in this session's scratch exploration —
so it is not part of this diff and buys nothing toward finding #4 without the storage-job piece.

Remaining MODEL-only items from round 1, still true:
- No live/duo/emulator evidence — source + unit-level only.
- `C1-reachability-successor.md`'s natural pre-activation route is still only source-modeled.
- The `log.warning` collateral message (finding #6's neighbourhood) has no dedicated assertion.

READY/merge decision is left to the coordinator, per the card. Given finding #4 is not fully
closed, I would flag this round as **fix confirmed correct and tested at the unit/verify_state
level (findings #1, #2, #3, #5, #6), finding #4 incomplete** rather than claim full closure.
