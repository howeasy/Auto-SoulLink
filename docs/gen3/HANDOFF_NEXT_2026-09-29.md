# Gen 3 handoff: where to pick up (2026-09-29)

Read this first. It supersedes the "HANDOFF" and "HANDOFF 2" sections at the bottom of `CLOSEOUT_RUNBOOK.md` for *what is left*; those sections still hold the evidence trail. `CLOSEOUT_2026-09-28.md` is the authoritative record of the fixes.

## 1. State in one screen

| Item | State |
|---|---|
| Frozen candidate | `5a67e3f6` on `claude/gen3-integration` (`C:/slink-wt/g3-int`) |
| Landing candidate | `38c68769` on `claude/gen3-landing-prep` (`C:/slink-wt/rv-land`), merged clean with master |
| Local master | `abc6bf28`, untouched. Not pushed, not tagged |
| Full unit suite | 13759 passed, 0 failed |
| FR/LG final cut | 43/43 PASS |
| Emerald final cut | 24/24 PASS |
| **RR final cut** | **24/28. Four rows open (section 3)** |
| Gen 1 gate `--quick` | all Gen 1 lanes pass. Two non-Gen-1 failures (need a full pokeemerald clone and `SLINK_PURERGB_SRC`) |
| Gates | ALL signed (G3, G4, G5, EG1-EG4, XG0-XG2), owner 2026-09-27 |
| Rulings | 36-42 in `docs/gen3_resume.md`. 39 (refuse expansion server-side) and 40 (six Emerald towns) are done and integrated. 41 = one landing of FR/LG/E/RR together |

Fixes confirmed merged into integration: `c8d66f6f` ball edge, `ec6d1325` journal contention, `3383c8d2` RR cold reload, `b1e039f8` commit-window interruption, `13028cf9` session counter, `e137de4f` rival refusal, `53412bb2` journal-lock retry, `401da78f` six towns. The journal-liveness finding is closed: `linked_faint_active_lhammer_gen3` passes a/b live (`docs/gen3/probes/journal_lhammer_126ff87b/run.txt`).

## 2. Hard constraints (unchanged)

- **Nothing lands on master, local or remote, without the owner's explicit yes for that landing** (ruling 41). A gate signature is not a landing approval.
- No push, tag or `gh release` without the owner.
- Private `SLINK_STATE_DIR` for every emulator run. Kill only your own EmuHawk PIDs, never by image name. Gen 2 shares this machine.
- Do not run an action for a peer that its own permission check denied. Surface it to the owner.
- Game facts come from ROM/decomp, never screenshots. Commit by explicit path. No bare `git stash`.
- **New (owner 2026-09-29): one worktree per active task, removed with its branch when it merges.** See `feedback_worktree_lifecycle_rule` in memory and `orchestration.md`. Do not create numbered lane copies; reuse a lane.

## 3. Job 1: the four open RR rows

Run on `gen3_rr`. Last seen at cut `5a67e3f6`, lane `g3-lane4` after a genuine rerun (7/11 of the previously failing rows passed):

| Row | Last failure text | Suspicion |
|---|---|---|
| `linked_faint_active_whiteout_gen3_rr_as_a` | not triaged | unknown |
| `boxsync_gen3_rr_as_a` | `no party_to_box for F56D8C1D:2BDDC8BF` | PC-storage class |
| `release_gen3_rr_as_a` | `pc_storage_choice_wrong_task tasks=[0808D2BD]` | same PC-storage class as boxsync |
| `species_clause_gen3_rr_as_a` | attempt 2 of 8: `no species-clause verdict (partner-gone)` / `native capture has no production TX` | may be the fresh-encounter retry budget, or a real capture-TX gap |

None touches trade, durable, reconnect, counter or journal work. These are all verified fixed. Suggested order:
1. `boxsync` and `release` first. They share the PC-menu task (`0808D2BD`), so one root cause may clear both.
2. Then `species_clause`, then `whiteout`.
3. Classify each as **env** (lane input), **harness**, or **product**. Build a fast red replay before fixing. Never rerun an unchanged failed row.
4. Owner option: accept some or all as **named known limits** and land RR with them open. That is the owner's call, so ask before assuming. Record the decision in `docs/gen3_resume.md`.

**Runner gotchas (both cost a session):**
- `tools/gen3_final_cut.py` refuses to re-execute any row that already has a receipt at the same cut, even with `--resume` or `--rows`. To force a rerun, delete `docs/gen3/probes/fc_<row>_<cut8>.txt` first.
- After a failed live row, use a **fresh lane**. Reusing one leaves mid-trade saves or guard files, and `trade_journal.lua:226` then fails closed with "saved/live party count mismatch". That is correct behaviour, not a bug.
- Do not run more than one heavy job at once (the 17/28 result was resource contention).
- Any fix changes the cut. After it, re-freeze, rerun the suite, and rerun all three final cuts on the new sha.

## 4. Job 2: landing sequence (after Job 1, or after the owner accepts the limits)

1. Re-freeze the cut. Refresh `claude/gen3-landing-prep` in `rv-land` (merge current master, then the cut). Hotspots from the last refresh: `server/cartridges.py`, `server/manager.py`, `server/upr_pipeline.py`, `server/static/.../randomizer.js`, `docs/protocol.md` citations.
2. Full unit suite on the landing branch. Check the exit code on its own, never piped into a commit.
3. **Ping Gen 2 first, this is required.** Shared files changed since Gen 2's last ACK: `server/state.py`, `server/server.py`, `server/adapters/__init__.py`, `server/adapters/gen3_expansion.py`, `lua/core/deferred.lua`. Each stales Gen 2's CODE_DIGEST (about a 2 h re-sweep). Use the live Codex thread "Gen2-Part2" via `delivery=steer`, with `workingDirectory=<repo root>`.
4. Send the owner one landing request: the cut sha, three final-cut summaries, suite count, signed gates, rulings 36-42, and known limits. Template: `docs/gen3/G*_request_draft.md`.
5. **Only on an explicit yes:** merge or fast-forward into local master. Push, tag and `gh release create` each need their own approval. The version lives only in git tags.

## 5. Job 3: the expansion parallel track (ruling 42, not blocking the landing)

Unrouted and refused server-side. XG3 is open and shinyModifier ships as a known limit (ruling 38, carried in X4). Details are in `CLOSEOUT_RUNBOOK.md` section 2b and `docs/gen3_resume.md` checkpoint 24. It must never delay the core cut or change production routing.

## 6. Cleanup status (DONE 2026-09-29, owner ran the script)

- **Result:** 97 of 97 worktrees and 116 of 116 branches removed, no errors (`C:/slink-wt-archive/cleanup_run.json`). Worktrees 115 -> 18, local branches 130 -> 14, C: free space 45 GB -> 85 GB.
- **Kept, Gen 3:** `g3-int`, `rv-land`, `g3-lane`, `g3-lane-master` (hold until the owner closes the RC). Tips unchanged: integration `742d5934`, landing-prep `38c68769`, master `abc6bf28`.
- **Kept, other lanes (never touch):** Gen 2 (`codex/gen2-foundation`, `omp/gen2-*` branches, `Temp/g2omp`), Gen 4, emerald-support-planning, `claude/ui-board-ambiguous`, this planning session's tree, the main checkout.
- **Recoverable:** 29 tips not reachable from a kept ref were tagged `archive/gen3-wt/*` and `archive/gen3-br/*` (108 `archive/*` tags in total). The 5 dirty trees' diffs are in `C:/slink-wt-archive/patches/`: `core-hud-red`, `g3-rival-rezero` (touches `lua/core/session.lua`, `lua/gen3/client.lua`), `g3-t5-fr-duo`, `g3-uiq`, `o-rrrand`. If something looks missing, look there first.
- **Still open (follow-up sweep):**
  - about 217 loose logs and scripts in the root of `C:/slink-wt`. Commit anything that is a needed receipt, delete the rest;
  - the `g3-lane*-state` directories;
  - Temp worktrees `fs1`-`fs4`, `g2unprov`, `g2unprov2`, `uiamb` (look like Gen 2's, so ask Gen 2 before removing);
  - the 3 untracked `docs/gen3/probes/checkpoint_{fr,lg,emerald}_clean_5a67e3f6.txt` in `g3-int`: inspect them and commit by path if they are real receipts;
  - `g3-lane` and `g3-lane-master` once the owner closes the RC.

## 7. Owner actions still open

- Kill the 3 orphaned `server.server` processes (the auto-mode classifier blocked the agent):
  `taskkill //F //PID 29084 //PID 21764 //PID 2036`
- Decide: fix the 4 RR rows, or accept them as named limits.
- Approve (or not) the landing when it is requested.

## 8. Env quick start

```bash
source C:/slink-wt/g3-env.sh          # in C:/slink-wt/g3-int
python -m pytest -q -p no:cacheprovider tests/unit    # check the exit code on its own
python tools/gen3_final_cut.py --cut <sha> --title rr --lane <fresh lane> --rows <rows>
```

Gitignored inputs staged in `g3-int` (the runner copies them into lanes): `patch/build/slink_RR.gba` (the NEW RR companion, sha1 `da579690...`; never restore the `.old-7a386749`), `patch/build/candidate-{firered,leafgreen}-trade/`, `.cache/expansion-output/`, `data/.rr_src_cache/`, and the Gen 1 ROMs plus `.cache/pret/{pokered,pokeyellow}` (real copies; the old symlink was broken).
