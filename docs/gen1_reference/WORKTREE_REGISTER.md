# Gen 1 RC worktree register

Current owner/status is in [RC_MASTER_GUIDE.md](RC_MASTER_GUIDE.md), the sole dispatch authority. This register records worktree location/classification and current file ownership. [Prior transition records](WORKTREE_REGISTER_TRANSITIONS_2026-09-13.md) are preserved history, not active grants.

## Current ownership

**RESUMED under explicit owner authorization (2026-09-14 UTC).** Canonical `E:/Google Drive/SLink/.claude/worktrees/gen1-rby-code-sweep-8d06e2`, `gen1/rc`; HEAD `59b6b0b` at takeover; BI-1 integrated at `57eabf7` (current code cut). Coordinator: Claude Opus 5 session `9a7ac120-04eb-489f-8fd1-c9ecb67b31a6` (`slink-63`); roles, not providers, carry authority (see the guide). R7 completed and PASSED (controlled-scripted); lane released; no EmuHawk running.

Current file claims: BI-1 integrated and released (`lua/tests/gen1_rb_ball_gate_inputs.lua`, `tests/unit/test_gen1_selected_rb_ball_gate.py`, `docs/gen1_reference/reviews/D1-RB-implementation-successor.md`; two Codex reviews recorded in the guide). R7 receipts preserved under `.cache/d1-rb-starter-rival-r7*` (ignored; do not clean) ( the Codex headless delegate HOLDed on sandbox Python access after adding the red test). Read-only cards: R6-SRC (Gen1-CodexPeer, DONE/reconciled), TK-1, R7-PREP and E-1 DONE; TK-2, P-1 and E-2 DONE. Active: P-2b and D2-CLAIM done. D2-HOST and P-2a integrated and released; the parcel candidate files are now tracked. D2-LUA integrated (coordinator review; owner capped harness spend). Was: `lua/tests/gen1_scripted_new_game.lua`, new `lua/tests/gen1_rb_mart_signature.lua`, `lua/tests/gen1_rb_point_fields.lua`, `lua/tests/gen1_rb_parcel_inputs.lua` (menu branch), new `tests/unit/test_gen1_rb_mart_signature.py`, new `tests/unit/test_gen1_scripted_chain.py`, `tests/unit/test_gen1_rb_parcel_inputs.py`, one line in `tests/live/gen1_selected_scenario.py`. P-2a-T, D3-CLAIM, D3-PATH done. WB-1 integrated and released (only `lua/gen1_acquisition_observers.lua` + four test files changed). P2A-1 (A+B) integrated and released. No active file claims; coordinator holds the emulator lane for parcel r3. Parcel live receipts r1–r6 preserved under `.cache/d1-rb-parcel-r*` (ignored); r6 = D2 PASS. Lane released. P2A-2 (both lanes) integrated and released at `b9658d7`. P2A-3/4 and RS-1 integrated at `501fd16`. P2A-5 integrated at `c8f5465`; pin `a99d8b4`. P2A-6/6C integrated at `2064c60`; pin `aa40b43`. P2A-7 integrated; pin `6ba8329`. P2A-8 integrated; pin re-set. No active file claims. Coordinator alone edits the guide, this register and `docs/agents/orchestration.md`.

Preserve dirty R0 report and untracked parcel Lua/unit/report (hashes verified at takeover). All 18 parked registrations remain as classified; no parked worktree was moved/deleted/reset. Root master is not the RC checkout. Native hook trust/activation is not claimed.

## Preserved checkout classifications

The table below retains the last full file-status audit; it does not claim that every parked tree's files were rescanned today. Today's metadata census confirmed all18 registrations and the speed-gate lock. Parked dirty evidence must not be discarded or cherry-picked without a separate reviewed claim.
| Checkout under `E:/Google Drive/SLink/.claude/worktrees/` | HEAD at audit | Classification and action |
| --- | --- | --- |
| `gen1-rby-code-sweep-8d06e2` (`gen1/rc`) | product15727ec; testa63d793; query Git for current docs HEAD | **CANONICAL.** Current ownership and grants are only in RC_MASTER_GUIDE.md. |
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
