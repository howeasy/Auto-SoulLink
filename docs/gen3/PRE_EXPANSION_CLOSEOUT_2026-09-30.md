# Pre-expansion closeout — 2026-09-30

The earlier core wrap-up and the RR continuation are delivered in local main. [RR closeout](RR_COMPLETION_2026-09-30.md) records the exact-source 28/28 standard and 3/3 recovery passes, source/model checks, preservation and cleanup limits. Expansion implementation stays paused and production expansion admission remains refused. This is a bounded completion record, not a release declaration.

## Completed evidence

- **RR final cut: PASS 28/28 and explicit recovery: PASS 3/3** at `e1e2adbd`; [current evidence and scope](RR_COMPLETION_2026-09-30.md). The older title/global figures below keep their original cut identities.

- **FRLG final cut: PASS 43/43** at `067768b920d1e797e6f8fc39d2bd6a872126ee23`: eight dependency/input-key cached build/tutorial rows and 35 newly run rows; no carried rows. See [summary](probes/fc_SUMMARY_067768b9.txt).
- **Emerald final cut: PASS 24/24**, all newly run, at the same cut. See [summary](probes/fc_SUMMARY_067768b9_emerald.txt).
- **Corrected global unit and cheap source gate:** 15,660 passed, 1,905 existing allowed skips, zero unexplained skips or failures; seven other source lanes passed. Frozen source `b9518fe4`; the final-cut candidate adds retained evidence only. See [actual log](CORE_FINAL_GLOBAL_UNIT_2026-09-30.txt). The `--quick` invocation excludes emulator release lanes.
- **Gen3 cheap source gate:** 4,988 passed with zero skips or failures, plus Lua, pin, generation and Emerald shadow lanes. See [actual log](CORE_SOURCE_GATES_2026-09-30.txt).
- **RR native species preflight:** targeted physical PASS at `0beca30d`, attempt 6 of 8; five preceding family mismatches aborted with both battles held. Later exact encounter-binding assertions have source/model coverage and independent review. The targeted receipt does not qualify the whole RR cut. See [scope and review record](RR_SPECIES_PREFLIGHT_2026-09-30.md).
- **Adjacent PureGreen prerequisite correction:** the original first-catch KO/dead-zone failure is retained; reviewed harness correction preserves successful-capture and zero-ball precedence and the existing three-attempt cap. Changed targeted physical replay passed attempt 1 of 3 at `8d8a77e2`. Its successful path was observed; failed-first-catch retry handling remains model evidence. See [replay](CORE_PUREGREEN_CATCH_REPLAY_2026-09-30.txt).

Source changes reuse the existing hunter, duo transport, classifier and clause oracle. Gold menu selection and expansion source-location fixes are test-only. Independent implementation reviews and red/green evidence are recorded in the coordinator's sole checkpoint and the linked receipts. No server rule, fixture or ROM fact was relaxed to manufacture a pass.

## Still pending

- A full Gen3 release-gate invocation.
- A complete all-green Gen1 release invocation after the corrections. The earlier full run remains a retained FAIL; subsequent corrected quick gate and targeted physical replay do not rewrite it.
- Expansion physical qualification, including pending observer/register-liveness and battle work. Source/build evidence does not authorize production routing.

## Preservation and cleanup

Verified reusable inputs live in the main checkout and `C:/slink-cache/gen3-inputs/`; two genuinely independent current Linux builds and pinned Gold/Silver inputs are retained. Ignored core evidence, environment bindings and per-file hashes are recorded in [preservation manifest](CORE_WRAP_PRESERVATION_2026-09-30.json) before removing the merged task checkout and branch.

Local main integration and all 72 final-cut receipts are committed at `01e2978c`. The merged `codex/gen3-core-finish` branch and its Git worktree registration were removed. External cache links were unlinked and the temporary environment file was removed after verified preservation. Ordinary filesystem deletion left Windows access-denied remnants under `C:/slink-wt/g3-core`; the preservation manifest records exact paths and operations. This directory residue is not a parked Git worktree or unmerged source change.

The task does not own main's untracked `lua/memory_gba.lua` or `server/adapters/gen2_crystal.py`; both remain untouched. Earlier ACL-denied residue (`C:/slink-wt/g3-lane` and four old Git worktree metadata directories) remains a separately recorded cleanup blocker. No ACL or trust bypass is authorized or used. No push, tag or release publication is performed.
