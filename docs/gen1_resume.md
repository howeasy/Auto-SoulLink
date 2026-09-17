# Gen 1 master release — resume note (2026-09-17 ~17:15Z, owner check-in)

Read this first after a context reset. The ledger `docs/gen1_requirements.md` is the authority on
evidence; this note is the working state around it. Plan (owner-approved, v3.9):
`C:\Users\howar\.claude\plans\system-reminder-you-are-operating-gleaming-pretzel.md`. The standing
worker contract every card brief points at is `docs/agents/worker_card.md`.

## Where things are

- Worktree `E:/Google Drive/SLink/.claude/worktrees/gen1-master-release-plan-6b4279`, branch
  `claude/gen1-master-release-plan-6b4279` = **master `d2c30fb`** (rebased 2026-09-17, tag
  `pre-rebase-gen1-release-c9bf880`) + ~110 commits. HEAD `2533016` at the time of writing.
- Workers: Codex is at its usage cap until 2026-09-19 07:34 (owner contingency: OMP + Claude
  subagents). OMP live session `Gen1 Peer 2` (pid 25980, cwd = repo root; name it explicitly) took
  every harness/tooling/oracle card; Opus subagents took the Lua bodies, drivers, client card, and
  independent reviews; the coordinator dispatches, reviews, integrates, commits, and holds the
  emulator lane. Standing rule from today: **no lane run while `lua/gen1/` or `duo_gen1_main.lua`
  is leased** (a run on a half-edited tree is void evidence).
- Checkpoint (hook contract): `gen1-rby-code-sweep-8d06e2/docs/gen1_reference/RC_MASTER_GUIDE.md`
  worker `master-release-lane` + `WORKTREE_REGISTER.md`; refreshed by
  `gen1-rby-code-sweep-8d06e2/docs/gen1_reference/refresh_master_lane_checkpoint.py`
  (args: state, files-json, next_action, live_lane, head, register-note; it edits the JSON block
  between the AGENT_CHECKPOINT markers and the register's master-release paragraph).

## PHYSICAL today (receipts under `tests/fixtures/gen1/receipts/`, all committed)

| Scenario / gate | Rows | Commit |
|---|---|---|
| `ball_gate_new` (cold cartridges, real server) | D-2, S-7 New Game identity | b1cee87 |
| `reconnect_new` both legs (same save + second-OT save) | C-1, C-2, D-14, W-5 reload half | e844db2 |
| `admit_randomized_new` (both halves SAVE, provenance oracle) | C-5 saved half | 48a51d7 |
| `link_new` under the oracle registry | S-2 bag removal (`BAG_BALLS 1 -> 0`) | 1259f9c |
| menu-row gate Red/Blue/randomized Red + companion-patch gate on the NEW client | T-1 prerequisites | 8f7ef74 |

Client/server findings those runs produced, all fixed with red-first tests: gift key read
mid-`_AddPartyMon` (850f9f5), `no_catch` withheld before the first ball + Mart close before SAVE
(f0ce91a), server seq per-connection + hello-first (0629736), connector queue on disconnect
(6aba43d), kept-alive battle driver pressed nothing (e95cefa), and the four review findings on the
client card (6dc40d6: rival reply held until pret stages `$FF`, snapshot-keyed party removal,
2-frame `move_mon` age window, rescan never clobbers a pending npc_trade).

## Built and committed but NOT yet run live (each scenario's first run is its smoke test)

| Item | Lua body | Python side | Commits |
|---|---|---|---|
| `soft_reset_new`, `trade_decline_new` (A2) | 50f265a | 65e33e3 | |
| `explode_new` (A3, `--explode-mode`, patched ROMs) | c0eb442 | f0f5310 | |
| `pc_ops_new`, `changebox_new` (A6; driver a8a1010) | d95ff6d | 54b30db | |
| `whiteout_new` (A5) | 2533016 | **missing**: SCENARIOS entry, `assert_whiteout_both_boxed` gate, `assert_whiteout_new_saved` — spec verbatim in 2533016's report/commit | |
| LINK PANEL wired into the client (A11) | 095b63f (+ module 354efa7) | gates 3c82cf0 | live PASS 8f7ef74 |
| the ONE client card (A5/A6/A8/Y-0/A13) | 6a4154e + 6dc40d6 | tests red-first | |
| Yellow: lab driver a0349b8, scripted host f6c1a44 | | | fixtures NOT rebuilt (LEGACY kept, TODO in `tools/gen1_fixtures.py`) |
| Viridian Forest driver (A7) 7374bf2 | poison body not written | | plan correction: Route 1 north forces 15 grass steps |
| harness: oracle registry + provenance + jitter + honest verdict (A0-H1/H2) | | 9e4a686, 107cc99 | |

## Where it stopped (owner: "stop after all in-flight tasks and check in")

- Last lane run: `linked_faint_active_new` rerun on the frozen tree at 6a4154e — FAIL by the game's
  RNG (A's starter lost its first wild battle and whited out before the link formed; not in the
  bounded-retry set) and the harness hung at teardown (killed; no EmuHawk left). The earlier rerun
  (pad fix, tree not frozen) is void. **`B_ACTIVE_COMMIT` now reads a real `player_move`**, so the
  pad fix is proven; the scenario itself still needs one clean PASS on a frozen tree.
- The ledger pass (170f12a) flipped every row above; open cells it named: T-1 MODEL still cites the
  pre-rebase dist commit `76ba1ff`; C-1/C-2 MODEL and D-1 SOURCE unflipped though tests exist.
- Known open items recorded in commits: an NPC trade emits both `party_to_box` and `key_change`
  (6dc40d6); the same-second duplicate-row splice in the reconnect checker (9e4a686);
  `docs/gen1_engine_sites.md` bag-removal wording (ledger).

## Next steps, in order (none dispatched — owner check-in pending)

1. Lane, on the frozen tree at HEAD: `linked_faint_active_new` (clean PASS), then
   `soft_reset_new`, `trade_decline_new`, `explode_new`, `pc_ops_new`, `changebox_new`; diagnose
   every failure from its kept run dir before any rerun (`--keep-data`).
2. OMP: A5 Python (SCENARIOS + `assert_whiteout_both_boxed` + `assert_whiteout_new_saved`), then
   `whiteout_new` on the lane.
3. Lane: `python tools/gen1_fixtures.py yellow town` / `yellow battle`, then the Yellow lab gate
   (`SLINK_LIVE=1 pytest tests/live/test_gen1_new_gates.py -k "new_game_lab_route and yellow"`);
   delete the three LEGACY sites the TODO names.
4. Subagents: A4 clauses bodies (`type_clause_new`, `species_clause_new`), A7 `poison_new` body
   (driver landed), A13 rival swap (optional); OMP: their Python; A9 dashboard snapshots during a
   run; the docs items (T-1 dist commit id, C-1/C-2 MODEL cells).
5. A12 full `duo-pairs` lane pass + S-7 witness, then Track B (P8-0 adapter isolation, launcher
   rewire, deletions, `memory_gb.lua` trim, docs regeneration incl. `docs/shared_runtime.md`,
   release note), re-rebase, Gen 3 check, full runner, package boot, FF, owner tags `v0.3.0`.

## Commands

```bash
python -m pytest tests/unit -q -p no:cacheprovider          # 2954 passed at 54b30db
ruff check . && python tools/lua_syntax_check.py
python tools/verify_gen1_release.py --quick
python tools/e2e_duo.py --game gen1_new --scenario <name> --keep-data
python tools/e2e_duo.py --game gen1_new --scenario reconnect_new --wrong-save tests/fixtures/gen1/red_town_ot2.SaveRAM
```
