# Radical Red closeout — 2026-09-30

The reviewed RR changes are integrated into local `master`. Qualified source: `e1e2adbdf7c0fb3090a76986aba5d31b5e863ffd`; the 165 retained evidence files were committed at `b90e0846`. No push or release publication was performed.

## Qualification

| Evidence | Result | Receipt |
|---|---|---|
| PHYSICAL standard RR cut | **28/28 PASS** | [Exact-cut summary](probes/fc_SUMMARY_e1e2adbd_rr.txt) |
| PHYSICAL explicit recovery controls | **3/3 PASS**: OS journal lock, native-success cold reload, commit-window interruption | [Recovery summary](probes/fc_SUMMARY_e1e2adbd_rr_recovery.txt) |
| SOURCE/MODEL quick gate | **5,021 passed, zero skips/failures**, plus Lua, pins, profile generation and shadow negatives | [Gate output](probes/rr_source_gates_e1e2adbd.txt) |

All 31 physical receipts passed `gen3_final_cut.fc_check` against the exact source and their exit/cleanliness records. Trade and release ran first and were resumed within the same cut; no result was carried from another source cut. The opcode suite reports 27 passed tests and 12 existing deferred/empty-parameter skips under its established policy. The tested player ZIP contains 182 verified members and passed its RR boot check.

Additional model checks: 613 release/route/harness tests; 224 focused trade tests; 16 new picker cases independently reproduced by a fresh nonauthor; 79 protocol/conformance checks, including 9 citation checks independently repeated by the coordinator. Both captured trade wire transcripts passed their conformance checks (2 tests). These counts overlap and are not added together.

## Changes

- Shared server lifecycle retains a native Trade action, selected pair or accepted offer while party visibility is withheld. It releases commands only after a fresh visible census passes the existing identity, slot, eligibility and capability checks. Duplicate choices cannot renew the watchdog; cancellation, withdrawal and expiry remain bounded. These pre-application waits are memory-only.
- The trade carrier records a bound raw 100-byte donor preimage before selection/confirmation. Strict invariant comparison, including moves, uses that record rather than the starting fixture. This accepts natural growth before a trade without masking transfer corruption; missing, wrong, late or malformed evidence fails.
- Release transit reuses the existing ordinary-input incidental-escape policy so the walk does not fight away the other usable party member. PC checks, game facts and runtime guards remain unchanged. The corrected physical row records escape, deposit, withdrawal, second deposit, release, partner memorial and matching independent save witnesses.

The native-wait, preimage and release changes received independent OMP reviews (cx-7fe86ed3, cx-7e0a4d71, cx-d21d063d, cx-b5d7ed2b). The final selection correction received a fresh Sol review with no actionable findings. Shared behavior stays in shared modules; no new title-specific facts or admission exceptions were introduced.

## Scope and retained failures

The historical `617c7360` standard pass lacked a passing lock probe. `43e9b99e` had standard 27/28 and recovery 3/3. At `e632e14e`, release passed but a later selection was rejected and canceled; its explicitly incomplete 14/28 summary retains 13 PASS and 1 FAIL. The old trace lacks wire visibility facts: a real-server replay proved the hidden-selection gap separately, so that causal attribution for the old live failure remains an inference. None of these results was rewritten or combined to manufacture a current pass.

FRLG 43/43 and Emerald 24/24 at `067768b9` remain historical exact-cut evidence. Their cut plans contain no native trade scenario. This closeout does not assert refreshed FRLG/Emerald cuts or a full Gen1/Gen3 release-gate invocation. The separately registered gift, hatch, evolve, NPC-trade, species-family and shiny-bonus scenarios were not executed by this 28+3 run; no new qualification is claimed for them. Existing RR S-8/S-9/S-11/S-12 and Mega limits remain recorded. The G5 owner signature of 2026-09-27 is preserved; no new waiver is invented. Expansion remains paused and production admission refused.

## Delivery and cleanup

The qualified ZIP is in main at `dist/SLink-player-g4-e1e2adbd.zip`. [Preservation record](RR_FINISH_PRESERVATION_2026-09-30.json) names the archive, four manifests, hashes and all 4,223 preserved members, including failed runs, final outputs and private recovery data.

The task's Git worktree registration and `codex/gen3-rr-finish` branch were removed after integration; external cache junctions were unlinked without touching their targets. Windows denied deletion of directory remnants under `C:/slink-wt/rr-finish` and its Git metadata directory. Automatic approval review also blocked the follow-up recursive cleanup command, reporting only “blocked by policy.” This is filesystem residue, not an unmerged branch or registered worktree. No ACL/trust bypass was attempted. Main's two foreign untracked files retain their original hashes.
