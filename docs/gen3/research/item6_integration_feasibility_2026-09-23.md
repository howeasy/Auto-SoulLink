# Item 6 integration feasibility: (a) integrate Gen 2-branch fixes vs (b) accept route-differential evidence

Card C4-ITEM6-FEAS, read-only analysis. Non-mutating git only (`git apply --check`,
`git merge-base --is-ancestor`); no cherry-pick/checkout/merge/stash performed.

## Verdict

| | Cost | Recommendation input |
|---|---|---|
| **44bf25d6** (Gen 1 SFX gate) | `git apply --check` clean on Gen 3 HEAD (`dc855dda`), 3 files, 0 conflicts. Test-fixture-only change. | Cheap to port if the owner wants it in-branch. |
| **3941198c** (Gen 1 ordering fix) | `git apply --check --3way` reports **conflicts in `lua/gen1/client.lua`** (the other touched file, `tests/unit/test_gen1_client.py`, applies clean). Gen 3's own `lua/gen1/client.lua` has structurally diverged from the Gen 2-branch copy (1889 vs 1998 lines at the common ancestor `c411b2f3`; Gen 3's queue stores the raw `cmd` table directly, Gen 2-branch's reconstructs `{cmd,key,nickname}`). Not a clean cherry-pick — needs hand re-derivation against Gen 3's own copy. | Not cheap; is real integration work, not a port. |
| **(b) route-differential evidence** | Zero new code. Cites existing red-on-master baseline for the Gen 1 SFX town gate and the legacy Gen 2 duo; record the delta is pre-existing, not caused by the route change. | Matches item 6 as already scoped in `G4_status_2026-09-23.md` / `G4_request_draft.md` §2 row 6. |

**Bottom line:** (a) is two different costs bundled as one line item. The SFX-gate commit is a
free port (clean apply, test-only). The ordering-fix commit is not a port at all on this branch —
Gen 3's Gen 1 client already diverged from the Gen 2-branch shape, so "integrating" it means
re-implementing the arrival-order fix against Gen 3's own `lua/gen1/client.lua`, which is exactly
the kind of module-by-module reconciliation the owner ruling assigns to the **post-G4 convergence
card**, not to G4.

## 1. What each commit changes

- **`44bf25d6`** ("case A follows the notify mapping"): touches only
  `lua/tests/test_gen1_sfx_gate.lua` and its two fixture receipt files
  (`tests/fixtures/gen1/receipts/test_gen1_sfx_gate_{blue,red}_patched_town_result.txt`). It updates
  test case A's expected SFX code/channel to match `f6229e77` (`play_sound 25` -> code 4/CHAN8 on a
  cartridge with `SLINK_CAP_SFX_NOTIFY`, else code 1/CHAN5). No production Lua or ROM change; it is
  a stale-expectation fix in the test itself.
  - **Dependency**: `f6229e77` ("gen1: a short notify blip...", the ROM/overlay change that
    introduced SFX code 4 and `SLINK_CAP_SFX_NOTIFY`). Checked: `git merge-base --is-ancestor
    f6229e77 HEAD` -> **YES**, and `lua/gen1/panel.lua:27,132,136` on Gen 3 HEAD already has
    `CAP_SFX_NOTIFY` / `sfx_code_for`. **The underlying product fix is already on Gen 3.** Only the
    Gen 2-branch test file itself needs 44bf25d6's specific edit; Gen 3's own copy of
    `lua/tests/test_gen1_sfx_gate.lua` still has the stale case-A expectation (this is exactly what
    makes the Gen 1 SFX town gate red on master/Gen 3 too, per the G4 status doc).

- **`3941198c`** ("a battle-held force_faint keeps its arrival place"): touches
  `lua/gen1/client.lua` (stamps `cmd.arrival` in `handle_command`, adds `arrivals` counter and a
  `defer_held()` insert-by-arrival helper, replaces two append-only hand-offs at the battle-end
  flush and the special/link loop-head fallback) and `tests/unit/test_gen1_client.py` (28 new
  lines).
  - **Dependency named in the commit message itself**: "Same shape as Gen 3 `684bbb7a`
    (`lua/core/deferred.lua` `Deferred:push`); folds into that at the post-G4 convergence card."
    Checked: `git merge-base --is-ancestor 684bbb7a HEAD` -> **YES**, `684bbb7a` is already on Gen 3
    HEAD (it landed *in this branch's own history*, same day, fixing the identical
    append-vs-arrival-order shape in the shared `lua/core/deferred.lua`/`lua/core/session.lua`).
    But Gen 3's `lua/gen1/client.lua` does not call `lua/core/deferred.lua` — it keeps its own local
    `self.deferred` array, unrelated to the shared module. So the *shared-layer* version of this
    fix is already in Gen 3; only Gen 1's own local queue (both on the Gen 2 branch and,
    independently, on Gen 3) needs the same append-order fix applied to itself.
  - Gen 3's own `lua/gen1/client.lua` (HEAD `dc855dda`) still has the unfixed append-only pattern at
    the equivalent site (`self.deferred[#self.deferred + 1] = { cmd = "force_faint", key = w.key,
    nickname = w.nickname }` in the battle-end flush, no arrival ordering) — the same class of bug
    3941198c fixes on the Gen 2 branch is plausibly still live in Gen 3's own Gen 1 copy,
    independently of whether 3941198c itself is ported.

## 2. Apply-cleanliness (non-mutating checks)

Both commits' single-commit patches were extracted with `git format-patch -1 <sha> --stdout` and
checked with `git apply --check --3way` against Gen 3 HEAD (`dc855dda`). No cherry-pick, checkout,
merge, stash, or worktree mutation was performed; `--check` does not touch the working tree.
(A naive `git merge-tree --write-tree <merge-base> HEAD <sha>` was tried first and rejected as
noise: the merge-base with either commit is the old common ancestor `c411b2f3`, so a real 3-way
merge pulls in the entire accumulated divergence between the two branches since then —
`docs/protocol.md`, `lua/slink.lua`, `server/server.py`, `server/adapters/__init__.py`,
`tools/e2e_duo.py`, `tools/make_release.py`, `tools/release_lanes.py`,
`tests/unit/test_mixed_foundations.py` (add/add) all show as conflicted — none of which the two
target commits actually touch. The per-commit `format-patch` + `apply --check` isolates to just the
files each commit changes.)

- `44bf25d6.patch` -> `git apply --check --3way`: **applies cleanly**, all 3 files.
- `3941198c.patch` -> `git apply --check --3way`: `tests/unit/test_gen1_client.py` applies cleanly;
  **`lua/gen1/client.lua` applies "with conflicts"** (3-way fallback triggered — the file's blob
  ancestry no longer matches closely enough for a clean patch, consistent with the ~110-line net
  structural diff between the two branches' copies of this file at the touched regions: line
  159/160 struct-init, ~490-560 `handle_command`, ~1004-1007 battle-end flush, ~1456-1473
  special/link fallback).

## 3. Gen 3 files/tests touched; shared-layer overlap

- `lua/tests/test_gen1_sfx_gate.lua`, `tests/fixtures/gen1/receipts/*` — Gen 1-only test/fixture,
  no shared-layer overlap.
- `lua/gen1/client.lua`, `tests/unit/test_gen1_client.py` — Gen 1-only production file and its unit
  test. **Not** `lua/core/*` (no `require` of `lua/core/deferred.lua` in either branch's copy),
  **not** `lua/gen3/*`, **not** `tools/e2e_duo.py` / `tools/run_gate.py` / `tools/gen1_playthrough.py`.
  No direct file overlap with the Gen 3 shared layer.
- Semantic overlap only: `3941198c`'s fix is the same bug shape already fixed in the shared
  `lua/core/deferred.lua` by `684bbb7a` (both already on Gen 3 HEAD). This is a convergence-relevant
  duplication, not a file collision.

## 4. What still has to run under (a) vs (b)

Per `docs/gen3/G4_status_2026-09-23.md` and `G4_request_draft.md` §2 row 6 / §6:

- **Item 6 as written today = 34 invocations** regardless of (a)/(b) — that count is the row's
  current scope, not yet reduced by either decision.
- **(a) integrate**: port `44bf25d6` (free, clean apply) *and* hand-reconcile `3941198c`'s
  arrival-order fix against Gen 3's independently-diverged `lua/gen1/client.lua` (not a port — new
  implementation work against a different code shape, plus its own red-first falsifier per the
  session's own testing norm), then re-run the Gen 1 SFX town gate and legacy Gen 2 duo to confirm
  green, i.e. still pay some/all of the 34 invocations afterward to prove the integration didn't
  regress anything else.
  - Net cost: 1 free test-fixture port + nontrivial Gen-1-client logic work (new arrival-stamping
    change to Gen 3's own file, new falsifier, live SFX-gate + Gen 2 duo re-runs) + the 34
    invocations (or a re-scoped subset) to close the row.
- **(b) accept route-differential evidence**: cite the already-established fact that the Gen 1 SFX
  town gate and legacy Gen 2 duo are red on `master` too (pre-existing, not caused by this branch's
  route change), record that as the agreed baseline/subset per `G4_request_draft.md` decision (a)
  option (ii), and close item 6 without integration work. This is the path the draft's own framing
  favors: "Route-differential evidence proves no regression, not full Gen 1/Gen 2 correctness" —
  i.e., it is an explicitly weaker but cheaper and *already-available* claim, not a stopgap that
  invents new evidence.
  - Net cost: none beyond documenting the baseline citation (already done in `G4_status_2026-09-23.md`
    and `G4_request_draft.md`).

## 5. Conflict with the "converge after G4" ruling (`docs/gen3/PLAN.md` §0, `ca53e491`)

Yes, in effect for `3941198c`. `PLAN.md` §0 states: "Two shared layers exist on unmerged branches
... G4 lane work finishes first; then a convergence card compares the two layers module by module,
picks ONE canonical set, and re-binds Gen 1/2/3 onto it ... fixes to shared semantics (for example
684bbb7a, the arrival order for battle-held commands) are recorded for the convergence card."

`3941198c`'s own commit message says the same thing about itself: "Same shape as Gen 3 684bbb7a
... folds into that at the post-G4 convergence card." Doing (a) for `3941198c` now — hand-porting
an arrival-order fix into Gen 3's own `lua/gen1/client.lua` ahead of the convergence card — is
precisely the module-by-module reconciliation work the ruling defers until after G4. It would not
break anything structurally (no shared-layer file is touched), but it preempts the ruling's
ordering and duplicates work the convergence card is meant to do once, canonically, instead of
twice (once here, once at convergence). `44bf25d6` does not have this problem: it is a Gen
1-test-only fixture fix with no shared-layer or convergence-card content.

`G4_request_draft.md` §6 "Settled" item 3 already draws this same line: "The generations converge
after G4: the Gen 1 SFX gate (44bf25d6) and the Gen 1 ordering fix (3941198c) live on the Gen 2
branch and are not this cut's work. What is open is only how item 6 records that." This research
confirms that framing is accurate for 3941198c and slightly generous for 44bf25d6 (which would be a
zero-risk, zero-shared-layer port if the owner wanted it done now) — but the report treats both as
one bundled decision, and the ordering-fix half is the one that actually collides with the
convergence-timing ruling.
