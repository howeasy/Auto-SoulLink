# Emerald Expansion XG3 progress, 2026-10-01 (final refresh, pre-cut)

Branch `claude/gen3-exp-xg3` (worktree `C:/slink-wt/exp-xg3`), off local master `ea9c8a07`. Nothing here is on master. At HEAD `462ed983` (a docs-only commit on top of `1b050038`) the branch is **83 commits ahead of master** (82 at `1b050038`) (`git rev-list --count ea9c8a07..HEAD`); that count moves, so **recount at the freeze: `<COMMITS_AHEAD>`**. The expansion stays unrouted and refused server-side (ruling 39); every live run used the logged `--test-only-route emerald_expansion_28877d73`.

Tags used throughout: **SOURCE** (a file, commit or ROM disassembly in this tree) · **MODEL** (a unit suite or independent review) · **DEV** (a real run that is not receipt-grade) · **PHYSICAL** (a real emulator run). This record keeps them distinct. **Dev runs are not receipts.**

**Status, stated once and plainly: XG3 is UNSIGNED. The final cut has NOT been run and NOTHING is frozen. No row below is receipt-grade.** The qualifying runs are the `--title exp` final cut at a frozen commit. **Freeze SHA = the tip commit recorded at freeze (`git rev-parse HEAD`)**, which will include the docs commit; this record does not name one. A full cut needs about 15 h serial, or about 5 h in 3 shards (lane-reported; the retained plan dump's summed budget ceiling is 887 m, about 14.8 h, a ceiling and not a measurement).

## What changed since the last refresh (the 62-commit state at `1a735d4e`)

1. **A wave of duo rows ran at `1a735d4e`** (DEV, three distinct private test-only routes at a time; headers read `nofinalcutclaim`). Verified from the retained logs in `docs/gen3_emerald/probes/`:
   * `linked_faint_active_gen3`: **PASS** (both clients, PYDEC PASS, SAVE witnesses `match=true`).
   * `whiteout_gen3`: **PASS** (both clients, PYDEC PASS). The `+dirty` refusal of the earlier run does not recur in this log.
   * `exp_static_altering0_gen3`: **PASS**. `exp_static_fish_gen3` (Old Rod, state-aware flow): **PASS**. Both are now **retained in-repo** (the last draft said they were not).
   * `exp_static_altering1_gen3`: **FAIL at `1a735d4e`** (`observed selector differs from pending fixture`, both players), then **PASS at `db1ed073`** (RESULT PASS both, PYDEC PASS, SAVE witnesses match). The fix was a cached SaveBlock1 pointer that ASLR moves between boots: selector reads are now bound to the live pointer (`db1ed073`).
   * `exp_static_rock_gen3`: **FAIL**, see the Rock section below. **It gates the cut.**
   * `exp_static_static`, `exp_static_static_run`, `exp_static_grass`, `exp_static_surf`: retained PASS logs are at older SHAs (`65e667e6`; `b32454c5` for Surf). The lane reports they also passed in the `1a735d4e` wave; **no `1a735d4e` log for those four is in this tree, so that is lane-reported, not verified here.**
   * `faint_cmd_gen3`: **PASS** at `65e667e6` (`exp_live_faint_cmd_gen3_65e667e6_dev.txt`).
2. **The three PC negative legs now have PHYSICAL (single-cart observer) receipts**, see the PC section.
3. **`--title exp` is now 30 rows** (was 29).
4. **The unit lane** grew from 38 to 39 modules and ran green, see below.
5. **Harness and diagnostics changes** (all MODEL/DEV, none touch the ROM): `expected_ball` (`b443c438`), screenshot namespacing (`1a735d4e`), HELLO diagnostics (`1c9f222c`, `41ee8c66`), the Rock probe (`ab101124`, `901e888d`), `PC.cursor` box-grid walk (`f96df71a`), and corrections to the cancel, bypass and full-box legs.

## Landed on the branch (summary; rows unchanged from the last refresh unless marked)

| Commit | Change | Evidence |
|---|---|---|
| `0d067d6f`, `5634a0b0` | `ctx.lose_active` finishes a whiteout on the expansion (own `MoveInfo.effect` table; plain `EFFECT_HIT` fallback once the no-damage move's PP is spent). | MODEL; independent review ACCEPT. Limit: Thrash/Uproar/Recharge fail closed. `whiteout_gen3` now PASS DEV (above). |
| `d6102d23` | `hatch` site (AddHatchedMonToParty `0811B284`, capture +0xDA, hatchling in **R4**); PC release pairing by frame window. | SOURCE (disassembly) + MODEL. **Red at its own SHA** (the 21 to 22 site pin landed in `9fc060ed`): squash at landing. |
| `9fc060ed`, `7c349ab4`, `bfc00eb8`, `f67c12e4` | `gift_areas` was `[]` ("every area is a gift"); now five verified ids with fail-closed generator guards; rival filtered by player gender in `server/adapters/gen3_expansion.py`; gift policy from the source census. | SOURCE + MODEL; independent review findings applied. |
| `6df0441f` and later | `tools/gen3_final_cut.py --title exp`. | MODEL. **Re-derived now: 30 rows = 7 SOURCE (the six generated/census checks plus `shadow_negatives_exp`) + 1 unit (`unit_exp`, 39 test modules by glob) + 19 duo + 3 ZIP (`exp_zip_build`, `exp_zip_check`, `zip_boot_exp`).** Method: `build_plan_exp` called with `subprocess.run` stubbed (no git, no run). |
| `343d2345`, `f4763732` | `release_gen3` selectable for `gen3_exp`; `emerald_pc_box_place` uses `PC.OPTION.move_mons` (0 on the expansion). | MODEL + DEV live PASS. |
| `3376e179` | Ruling 40 for the expansion: gym leaders and trainers file under their town. | SOURCE + MODEL; browser check (DEV, mock, not retained). |
| `02df12c6`, `c2c55d75`, `379f4f5b`, `f9a93b7d`, `c6b093e6` | Unknown release pairing mode refused; PC negative legs ordered after `emerald_save_town`; cancel, full-box and bypass legs authored and corrected. | MODEL; the legs now have observer receipts (below). |
| `54ec247e`, `05acb5ba`, `5b94a8ab` | `mon_given` re-pinned to `GiveScriptedMonToPlayer` `081C2E74`+0x68; every site also hooked at its `+0x02000000` ROM-mirror alias (**22 kinds / 44 hooks**). Bounded: `gScriptCmdTable` 231/231 mirrored, `gBattleScriptingCommandsTable` 0/251, `gSpecials` 1/621. | SOURCE + MODEL. |
| `eacb615b` | `faint` re-pinned inside `SetValuesOnFaint` (`080df4a4`, hook `+0x82`, capture `+0x86`); covers the opcode and the C fallback. | SOURCE + MODEL (`test_gen3_exp_faint_pin.py`). |
| `906b34f2` | Native catch EV oracle (exact source-species yield, multiplier-free seeds). | MODEL (red oracle replay). |
| `9094ef93`, `28d37a8e`, `8c79b995`, `9b2d0d30`, `048db86b` | Fixture registry. **38 `exp_*.sav` fixtures** now in `tests/fixtures/gen3/` (counted). Adds `exp_pc_negative_chain_synth`, a SYNTH seed with **one extra usable boxed record**, because the pin's release precondition refuses a release below 3 usable mons (chain: 5, 4, 3, 3, 2 usable). Native CONTINUE/SAVE qualified only (`NATIVE_CONTINUE_SAVE_ONLY`); also the `box0-full` (30-record) seed and the Mirage-resolved Rock seeds. | SOURCE + MODEL; SYNTH, disclosed in manifests. |
| **`67493da5`** (+ `9a6a8d69`, `89af051f`, `ec169b94`) | **Client cold-boot baseline fix in `lua/gen3/client.lua`**: `observe_known` calls `rescan_boxes()` before `seed_known()` on the settled quiet count change. | MODEL (red-first by commit message; reviewer-reported revert-checked; **not re-verified here**). **Runs for VANILLA Gen 3 titles too**, see the blast-radius section. |
| `b32454c5`, `13d58ca4` | `linked_faint_active` oracle: read-only FORCED_HP0 watcher binds HP0 < engine site <= TX faint < completion. | MODEL + the PASS above. |
| `db1ed073`, `ab101124`, `901e888d`, `9cb921db`, `1dba386c`, `8e3486d9`, `76580197` | EXP-C: live-pointer selector reads; SYNTH SFC32 state at the Rock entry; read-only Rock post-capture observation; retained evidence. | MODEL + DEV. |
| `b443c438`, `1a735d4e`, `1c9f222c`, `41ee8c66` | Harness only: `expected_ball`; screenshots namespaced per row/player; HELLO diagnostics. | MODEL. |
| `a77f3520`, `1b050038`, `0c36fe9a`, `5ce0eb57`, `901e888d`, `ccfa94e0`, `311cbe7e` | EXP-E: `docs/gen3_exp/negatives_manifest.json`, plan row `shadow_negatives_exp`, three PC windows and positive siblings bound to the manifest. | MODEL + PHYSICAL DEV (below). |

Earlier rows not repeated here (`8e6dc74b`, `a531d5cf`, `b5024ed7`, the Lease C rows) are unchanged from the previous refresh.

## Unit lane (MODEL)

The 39-module expansion unit set ran from clean `1b050038`: **940 passed, 0 skips, exit 0, 313 s** (`patch/build/exp_unit39_final.txt`, header `SOURCE_UNIT_DEV cut=1b050038... modules=39; no emulator/frozen-cut qualification`; Codex then committed the same log as `docs/gen3_emerald/probes/exp_units_1b050038_2026-10-01.txt` in `462ed983`). `462ed983` also retains a **SOURCE-only dry run at `1b050038`**: `exp_source_checks_1b050038_2026-10-01.txt` (the six generated/census checks each `EXIT 0`, and `tools/gen3_shadow_negatives.py` on the manifest: `SUMMARY PASS receipts=3 checks=15 passed=15 failed=0`) and `exp_plan_1b050038_2026-10-01.txt` (a plan dump: **30 rows, RUN 30 / CACHED 0 / CARRY 0, budget ceiling 887 m**). I read those files and ran nothing; they carry the header `no final-cut/runtime qualification`. The earlier 37-module run was 810 passed. This is a dev run of the same command as the plan's `unit_exp` row, not the row itself.

## Live results (DEV unless marked; none receipt-grade)

* **Duo scenarios** (both clients `RESULT: PASS`, PYDEC PASS): `link_gen3`, `boxsync_gen3`, `release_gen3` (original baseline, `probes/dev_2026-10-01/`); `faint_cmd_gen3` (`65e667e6`, after the faint re-pin); `linked_faint_active_gen3` and `whiteout_gen3` (`1a735d4e`); `gift_gen3` and `egg_receive_gen3` (`b5024ed7`). The final hatch verdict is still not recorded (retained qualification files `exp_acq_hatch_{a,b}_qual_exp1_eacb615b.txt` exist).
* **`linked_faint_active_gen3` wording (the claim as it should be read).** The faint is an **engine-resolved in-battle HP0, observed by the harness HP-0 watcher**. It is **not a damage-KO claim and not test-forced**: the log shows `ACTIVE_KO ... inputs=0 hp_writes=0` and a `FORCED_HP0` marker emitted by the watcher. One nuance from the log: the scenario reaches that state through the client's `force_faint` Perish commit (`ACTIVE_COMMIT ... writes=5`), so the setup does write; the HP drop itself does not. **OPEN: the `ENGINE_FAINT_SITE` marker is not key-bound** (frame and active-slot bound only; the log header says so). Named-limit candidate (c).
* **Static/wild rows**: see "What changed" above. They use the disclosed Damp lead (abilityNum 1 to 2) and Master Ball preps. `static_run` is the dead-zone negative with its exact ledger via `is_formed_link`.
* **Single-cart PC observer, positive legs**: two earlier runs (`pclegs1.log`, `pclegs2.log`) are **PRE-MIRROR** (registered 22 before `05acb5ba`). Fired kinds across them: 7 (`map_load`, `pc_deposit`, `pc_box_place`, `pc_withdraw`, `pc_release_begin`, `pc_release`, `save`) plus the `frame_control` STATUS counter. Current runs register 22 kinds / 44 hooks.
* **Browser check** (coordinator's in-app browser, SYNTH payloads): numbers **not retained in-repo**; unchanged from the last refresh. No title has had a live two-emulator calc run.

## Rock Smash row: FAIL, GATES THE CUT

Retained logs: `exp_parallel_exp_static_rock_gen3_901e888d_{,a_,b_}dev.txt`, screenshots `exp_rock_901e888d_{a,b}_{first-hold,hold-300}.png` (committed in `76580197`).

* **Proven on both sides (from the logs):** the SYNTH SFC32 state is seeded at the Rock Smash entry (`SYNTH_ROCK_RNG_PREP`; counter 17 to 18 to 19 across two native `Random32` draws; runtime only, not saved); the native encounter starts and the capture is slot-valid (TX `capture` species 74, Geodude Lv 15, `Route 111`, on both players); the server link forms (`Geodude and Geodude linked!`).
* **Then the game sits in a bare overworld** and the row times out (`native catch failed: capture scene did not settle ... (1800 frames)`). In the logs `sGlobalScriptContextStatus` reads **1 (WAITING)** for 722 of 723 samples on player a and 720 of 721 on b (the remaining sample reads 2). I viewed the `hold-300` screenshot of player a: overworld, **no text box**.
* **Cause (SOURCE, pinned expansion commit `e8bd1cd7`, read in `C:/slink-cache/expansion/`):** `EventScript_SmashRock` ends in `waitstate` after `special RockSmashWildEncounter` (`data/scripts/field_move_scripts.inc:91`). The wild-battle return task `Task_ReturnToFieldNoScript` (`src/field_screen_effect.c:492-500`) calls `UnlockPlayerFieldControls` and `ScriptUnfreezeObjectEvents` and never `ScriptContext_Enable`, so the script context stays parked. The overworld checkpoint requires status 2, so it refuses until another script runs. The logs show the task running (`POST_CAPTURE_FLOW ... Task_ReturnToFieldNoScript`).
* **Probably native/benign.** The lane says the body is the same as vanilla pret `field_screen_effect.c:446-454` and that the qualified Emerald title behaves the same; **neither is verified here** (no vanilla pret tree was read, and no Emerald Rock run was made).
* **Not qualified for this row:** settle, SAVE, PYDEC. Earlier Rock attempts failed for other reasons (`b32454c5` hello timeout from the Mirage pulse; `db1ed073` slot mismatch; `f09bf2cd` settle), all retained as fail logs.
* **Named-limit candidate (e)**; **owner choice: fix before signing, or rule it a named limit.** This record does not choose.

## PC negative legs (PHYSICAL DEV, single-cart observer)

Receipts under `docs/gen3_exp/probes/`, bound by `docs/gen3_exp/negatives_manifest.json` (`evidence: PHYSICAL_DEV_OBSERVER`) and checked by plan row `shadow_negatives_exp` (the checker `tools/gen3_shadow_negatives.py` was **not run by me**; Codex's retained output at `1b050038` is `SUMMARY PASS receipts=3 checks=15`, source-only). The manifest's own scope line: raw observer windows, **client reporting not qualified**.

* **Bypass** (run at `048db86b`, window frames 5813 to 6991): the readback says the grabbed mon is gone from every box and the party is unchanged; the observer shows `pc_release` at frame 6609 with **no `pc_release_begin`** (unpaired).
* **Cancel** (same run, window 6991 to 8667): release **absent** in the window; a later real YES release is valid at frame 9782 (begin plus release). It runs on `exp_pc_negative_chain_synth`.
* **Full box** (run at `ccfa94e0`, window 1602 to 2168): `box-full` reached (`MSG_BOX_IS_FULL`, `TryStorePartyMonInBox` FALSE), `pc_deposit` count 0 in the window, and a positive sibling deposit into box 1 happens later (`sibling_later=true`).
* **Not proven:** the **client half** (that the client reports no release for the bypass) is a **DUO claim**, not shown by these observer windows. **Named-limit candidate (b):** a held mon released through the moved-mon path is discarded with no `pc_release_begin`; the client keeps it "carried".

## Pin-completeness audit and the ROM mirror (unchanged)

22 site kinds under `titles.emerald_expansion_28877d73.artifacts.clean.sites` (SOURCE, `--check`). The 0x0A ROM mirror was the one expansion-wide finding and is fixed (`05acb5ba`). Otherwise complete or fail-closed: `whiteout` (7 callers), `save`, `battle_begin`/`battle_end`, `poison_faint`, the five PC kinds. `map_load` misses new-game, cable-club and contest-hall returns (named limit). The moved-mon bypass is reachable by source (`pokemon_storage_system.c:7813-7814`, `:7510-7513`, `:6558-6561`) and is now observed physically.

**Mirage Tower pulse task.** On Route 111 the visible tower runs `UpdateMirageTowerPulseBlend`, not in the overworld checkpoint allow-list, so hello and writes are withheld. The Rock seeds use `VAR_MIRAGE_TOWER_STATE=3` (SYNTH, native `NoTower` layout 392) so the tower is resolved. A grep finds the symbol nowhere under `data/games/` (consistent with "not allow-listed" for both the expansion and the qualified Emerald), but I did not re-derive the checkpoint policy semantics; the "qualified Emerald fails closed the same way" half is **lane-reported**. Named-limit candidate (a).

## Known issues found, not caused here

* `tests/unit/test_e2e_duo_scenario_selection.py::test_gen3_frlg_keys_do_not_leak_and_nothing_leaks_in` failed on master `ea9c8a07` too (RR lane; no log retained).
* Regenerating `calc/src/js/data/sets/games/EmeraldExpansion.js` writes LF while the working tree is CRLF, which trips the clean-tree gate. Convert to CRLF after regenerating.
* 6 abilities and 54 items have no calc mapping (`EXPECTED_UNRESOLVED`); 1 of 1825 trainer slots affected (Smoke Ball).

## SYNTH preconditions used (disclosed; the owner explicitly allowed SYNTH tests)

Damp lead (abilityNum 1 to 2); Master Ball item (static positive and method rows); Mirage-resolved seeds; the Rock SFC32 state (runtime, not saved); box0-full, 420-record and 5-usable PC seeds (the last one is `exp_pc_negative_chain_synth`). Each is in an `exp_*_manifest.json`. SYNTH marks setup only; the behaviour under test runs natively.

## Shared-runtime blast radius (corrected)

Earlier wording called the client changes "two vanilla-neutral hunks". That is wrong. Against master, `lua/gen3/client.lua` has **4 commits, 5 hunks, +32/-7** (`d6102d23`, `02df12c6`, `ec169b94`, `67493da5`) and `lua/gen3/signals.lua` has 2 (`05acb5ba`, `5b94a8ab`). **`67493da5` changes `lua/gen3/client.lua` for the VANILLA Gen 3 titles too** (`observe_known` now rescans boxes before re-seeding), so it is not vanilla-neutral, and it stales vanilla Gen 3 receipts. I did not audit whether the other client.lua hunks are no-ops on vanilla titles. **Gen 2 digest scope:** per the lane's statement the digest sees `server/` and Gen 2 paths, not `lua/gen3/`. At HEAD `1b050038`, `git diff --stat ea9c8a07..HEAD -- server lua/core lua/gen2 'data/games/gen2_*'` returns only `server/adapters/gen3_expansion.py` (+56/-4); re-run it at the freeze.

## Named limits (proposals; the owner rules)

Earlier list: (1) shinyModifier (ruling 38). (2) 6 abilities / 54 items unmapped in calc. (3) Altering Cave set 0 only (display-only). (4) Wynaut egg not fixed-species. (5) Thrash/Uproar/Recharge cannot complete the whiteout fallback. (6) Shedinja from evolution (inherited). (7) Mystery Event gift. (8) `map_load` coverage (three returns). (9) No live two-emulator calc run. (10) Routing refused until routed.

New candidates:

* **(a)** Mirage Tower pulse task not in the checkpoint allow-list (fail-closed; SYNTH Mirage-resolved seeds).
* **(b)** Held mon released through the PC moved-mon path is discarded with no `pc_release_begin` (observer shows it; client half is a duo claim, not proven).
* **(c)** `ENGINE_FAINT_SITE` marker not key-bound (OPEN; slot/frame bound).
* **(d)** SYNTH preconditions disclosed (list above).
* **(e)** Rock Smash leaves `sGlobalScriptContextStatus` at 1 after the native capture return, so the overworld checkpoint refuses (probably native/benign). **Gates the cut.**

## Owner decisions, kept separate

1. **Sign XG3 only after the final cut** (not run; about 15 h serial, about 5 h in 3 shards). Sign on `fc_SUMMARY_<CUT_SHA8>_exp.txt`, `<ROWS_PASSED>` of `<ROWS_TOTAL>`.
2. **Rock Smash:** fix before signing, or rule limit (e).
3. **Routing flip (ruling 39)** is a distinct yes, with a Gen 2 ping.
4. **Push and tag** are separate approvals.
5. **Named limits** (a) to (e) plus the earlier list.
6. **Landing** is squashed into about 6 logical groups (`d6102d23` is red at its own SHA); **Gen 2 ping before landing** (only `server/adapters/gen3_expansion.py`).

## Still open

* The `--title exp` cut at the frozen tip: `<ROWS_TOTAL>` rows (30 expected), `<ROWS_PASSED>` passed, `<ROWS_FAILED>` failed; ZIP build and boot; XC5 live two-emulator calc.
* Rock Smash row (FAIL).
* Observer receipts for the remaining kinds (`battle_end`, `evolve_species_store`, `poison_faint`, `poison_hp_before`, `pc_move`, `trade_*` have no run evidence in the table).
* Client-half proof for the PC bypass.

## Claims I could not verify

* The `1a735d4e` wave re-PASS of `static`, `static_run`, `grass`, `surf` (no log in the tree; older-SHA PASS logs exist).
* That the `1a735d4e` wave tree was clean (the logs carry no `dirty` string; the lane says clean).
* "Probably native/benign" for Rock: vanilla pret `field_screen_effect.c:446-454` and the qualified Emerald behaviour were not read or run.
* The 15 h serial / 5 h in 3 shards estimate (887 m is a budget ceiling).
* `67493da5` red-first / revert-checked / 293 tests (commit messages and the lane only).
* Whether the other `lua/gen3/client.lua` hunks are no-ops on vanilla titles.
* That the Gen 2 digest excludes `lua/gen3/`.
* That the plan row `shadow_negatives_exp` passes inside a cut (I read Codex's retained source-only checker output, `SUMMARY PASS 15/15`; I did not run it); the exact command equivalence of the unit dev run to the plan row.
* The Mirage allow-list claim for the qualified Emerald.
