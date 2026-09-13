# Gen 1 RC worktree register

Current owner/status is in [RC_MASTER_GUIDE.md](RC_MASTER_GUIDE.md), the sole dispatch authority. This register records worktree location/classification and current file ownership. [Prior transition records](WORKTREE_REGISTER_TRANSITIONS_2026-09-13.md) are preserved history, not active grants.

## Current ownership

- Canonical: `E:/Google Drive/SLink/.claude/worktrees/gen1-rby-code-sweep-8d06e2`, branch `gen1/rc`; coordinator Codex `01a09ae0-ad6f-7b01-8753-5e6b71eb1cfa` on HOUNDOOM owns guide/register, reviews and integration.
- Product behavior15727ec; scripted test source6283d58. Metadata census before this documentation update found canonical HEAD e7161be and all18 registered worktrees; root master remains adf3362. No checkout was created, removed, moved, reset or cleaned in this work packet.
- D0-S scripted Y/Y run completed exit0; all helpers/emulators/resources closed, no live lane. No Computer Use or OS UI input is permitted. Normal-button scripted tests do not require human availability.
- No active source/test-file writer. Sol builders and independent source reviewers are released.
- Claude Gen1-Collab2 owns only the next R0 contract report correction under the guide's exact source/design scope, conditional on matching ACK; no code/runtime authority. OMP has only the frozen D0-S receipt check, read-only/reply-only, conditional on matching ACK.
- Speed-gate remains parked and administratively locked. Its repaired metadata and original worktree are preserved; see [recovery receipt](reviews/SPEED_GATE_ADMIN_RECOVERY_2026-09-13.md).

## Preserved checkout classifications

The table below retains the last full file-status audit; it does not claim that every parked tree's files were rescanned today. Today's metadata census confirmed all18 registrations and the speed-gate lock. Parked dirty evidence must not be discarded or cherry-picked without a separate reviewed claim.
| Checkout under `E:/Google Drive/SLink/.claude/worktrees/` | HEAD at audit | Classification and action |
| --- | --- | --- |
| `gen1-rby-code-sweep-8d06e2` (`gen1/rc`) | product15727ec; test6283d58; query Git for current docs HEAD | **CANONICAL.** Current ownership and grants are only in RC_MASTER_GUIDE.md. |
| `gen1-native-free-service` | `3404bc9` | **PARKED DIRTY.** Claude stopped the normal-walk experiment: two modified selected-smoke files and untracked `tests/live/test_gen1_native_selected_progression.py`. Do not merge, clean, or delete; product B code through `10a500a` was already integrated at `e9f11f9`. |
| `gen1-storage-sync-runtime` | `f8325dc` | **PARKED FUTURE C**, clean modeled storage work. No implementation authorization in the current A+B3 slice. Rebase/review before any future code. |
| `gen1-collab-bad73b` | `adf3362` | **HISTORICAL PEER CHECKOUT**, clean; no SLink Claude session was reachable at handoff check. Verify task binding before any physical move. |
| `gen1-active-3x-rc`, `gen1-active-3x-rc-measure` | `b858743` each | **HISTORICAL CLEAN**, A integrated at `3945f24`; ignored `.cache` evidence and task paths stay in place. Do not cherry-pick or use as current code. |
| `gen1-continuity`, `gen1-hud-client`, `gen1-hud-server`, `gen1-memory-boundaries`, `gen1-nonlive-closure`, `gen1-registration`, `gen1-service-lease`, `gen1-speed-gate` | `fe7f1e1`, `da88b5f`, `9ea513e`, `e63f525`, `60362b8`, `547c5b3`, `1db7788`, `35b7894` | **HISTORICAL CLEAN, archived in place.** Their branch tips are not necessarily ancestors of RC because integration/reconciliation used different commits. Do not re-cherry-pick or assume their old README/status is current. |
| `gen1-runtime-performance` | `fbaa506` | **DIRTY QUARANTINE**, three modified performance/inventory files. Old unqualified experiment; do not use as A source or discard user data. |
| `agent-a7f68e4f2daf34d8d` (`claude/ui-mockup-track-b`) | `05c419b` | **OUT OF GEN1 RC**, six untracked UI files. Untouched. |
| `shared-framework` | `9433c80` | **OUT OF GEN1 RC**, clean. Untouched. |


## Update and safety rules

Read the master guide first; verify only the assigned checkout with `git --no-optional-locks status --short`, HEAD and necessary source hashes. No broad ignored-cache scan for a read-only card. Coordinator updates this register on worktree/ownership/integration transitions and before handoff/compaction.

All Git mutations use `-c maintenance.auto=false -c gc.auto=0`. Before any future physical archive/move/delete, verify absolute workspace containment, tracked/untracked/ignored receipt preservation and live bindings. Current authorization does not permit deleting parked worktrees, merging to master or pushing. “Archived” means classification/exclusion unless a separate physical action is explicitly authorized.