# Emerald Expansion XG3 progress, 2026-10-02 (pre-cut refresh, v3)

Branch `claude/gen3-exp-xg3` (worktree `C:/slink-wt/exp-xg3`), off local master `ea9c8a07`. Nothing here is on master. At HEAD `d78eb2b9` the branch is **88 commits ahead of `ea9c8a07` and of local master** and **1 commit behind master** (`git rev-list --count master..HEAD` = 88, `HEAD..master` = 1; `git status --short` was empty when read). The one master-only commit is `735dea38` (README port notes plus the hidden-NPC `key_change_rejected` test expectation; owner-approved, not pushed; it touches `README.md` and `tests/unit/test_state_npc_trade_clauses.py` only, no server change), so the branch needs a rebase or squash at landing. The count moves; **recount at the freeze: `<COMMITS_AHEAD>`**. The expansion stays unrouted and refused server-side (ruling 39); every live run used the logged `--test-only-route emerald_expansion_28877d73`.

Tags used throughout: **SOURCE** (a file, commit or ROM disassembly in this tree) · **MODEL** (a unit suite or independent review) · **DEV** (a real run that is not receipt-grade) · **PHYSICAL** (a real emulator run). This record keeps them distinct. **Dev runs are not receipts.**

**Status, stated once and plainly: XG3 is UNSIGNED. The final cut has NOT been run and NOTHING is frozen. No row below is receipt-grade.** The qualifying runs are the `--title exp` final cut at a frozen commit. **Freeze SHA = the tip commit recorded at freeze (`git rev-parse HEAD`)**; this record does not name one. A full cut needs about 15 h serial, or about 5 h in 3 shards (lane-reported; the retained plan dump's summed budget ceiling is 887 m, about 14.8 h, a ceiling and not a measurement).

## What changed since the last refresh (`dc3e2a24`)

`git log --oneline dc3e2a24..HEAD` is three commits, all Rock Smash: `8dd64eaa` (diagnostic of ordinary player recovery), `cd6b0648` (the driver step), `d78eb2b9` (bind the default pass to the context replacement and test live object matching). Before `dc3e2a24` the tree also took `3c495a47` (a four-line change to `lua/tests/gen3_scripted_play.lua`).

1. **Rock Smash is now DEV PASS** (details below), with an **owner disposition** replacing "gates the cut".
2. **Owner rulings 2026-10-02 on the other three limit candidates:** (a), (b), (c) are ACCEPTED named limits (below).
3. **Local master advanced to `735dea38`**; the branch is one commit behind.
4. **Every one of the 19 duo rows now has a retained PASS log** (DEV, differing source cuts; table below). The earlier "final hatch verdict not recorded" gap is closed by a retained DEV PASS (`egg_hatch_gen3` at `6282a092`).
5. **Independent OMP reviews found and fixed defects along the way** (the faint oracle, a Rock probe label, the PC legs) (lane-reported; the fixes are in the commit history, the individual review transcripts are not retained here). The new Gen 3 OMP peers are addressed by id (lane-reported; names drift).

## Rock Smash row: DEV PASS, OWNER DISPOSITION: driver step + document it

**Result (DEV, source `cd6b0648`, TEST-ONLY route).** The default Rock row (diagnostic flag absent) passed both clients: `RESULT: PASS` on a and b, `PYDEC: PASS`, `EXIT 0`, one attempt. Native SAVE witnesses: **A `c12fe035736627a3f7c3518d3be084cb7c4a671d647540485c0ab4e248d2fe83`, counter 3 to 4; B `b26997907fd8b70e61ceb021c82150e72f308b11c2cc4b7e79d871300e8230ef`, counter 4 to 5**; both `match=true`. Retained as `docs/gen3_emerald/probes/exp_rock_default_cd6b0648_{,a_,b_}dev.txt` plus `..._trace.json` (committed in `d78eb2b9`; header: `DEFAULT Rock row; diagnostic flag ABSENT; ... no final-cut qualification`). The probe env var `SLINK_ROCK_PLAYER_PROBE` appears only in the Lua as an opt-in (`scenario_gen3_static_wild.lua:360`); the header says it was absent for this run. **`d78eb2b9` changed the scenario Lua after this run** (it is the commit that retained the receipt); the PASS is therefore at `cd6b0648`, not at the tip.

**The row now REQUIRES one native NPC interaction.** The Route 111 "Rock Smash tip" fat man object (`Route111_EventScript_RockSmashTipFatMan`, graphics id 17, at (19,101); logged as `ROCK_PLAYER_OBJECT`): from (18,102) one step Up onto the cleared rock tile (18,101), face Right, press A, and complete the native dialogue. The driver verifies the object is active and its hide flag is clear (`FLAG_HIDE_ROUTE_111_ROCK_SMASH_TIP_GUY` = `0x34B`, checked in the pinned expansion `include/constants/flags.h:894`) and aborts on unknown fields. `sGlobalScriptContextStatus` goes **1 (WAITING) to 0 (RUNNING) to 2 (SHUTDOWN)**. Trace, both players: before (stall 0) 1; one-step (50) 1; object-facing (72) 1; object-interact (105) 0; after (**745** frames from battle return) 2. 745 frames is about **12.4 s at 60 fps**, including the dialogue.

**Why:** the NPC script's `ScriptContext_SetupScript` **overwrites** the parked `EventScript_SmashRock` context (`src/script.c:305-313` in the pinned expansion, read here); the Rock script is NOT resumed (its pending `releaseall`/`end` never run). SOURCE, expansion `e8bd1cd7`: `EventScript_SmashRock` parks at `waitstate` (`data/scripts/field_move_scripts.inc:91`) and `Task_ReturnToFieldNoScript` (`src/field_screen_effect.c:492-500`) never calls `ScriptContext_Enable`.

**Expected-failure control, retained.** The earlier A-only run at `901e888d` (no interaction; `exp_parallel_exp_static_rock_gen3_901e888d_{,a_,b_}dev.txt`) FAILED: `capture scene did not settle ... (1800 frames)`. In player a's log all 722 parsed `CAPTURE_SETTLE_WATCH` samples read status 1, out to watcher age 21600 (so "more than 21,500 frames" holds). The `hold-300` screenshot showed a bare overworld with no text box. This stays as the negative control: **the PASS depends on the NPC interaction.**

**Ordinary-input diagnostic (`8dd64eaa`, DEV, opt-in flag `SLINK_ROCK_PLAYER_PROBE=1`, not the default row).** Idle 300 frames, START menu open and close, B and A against nothing, and a plain step all left status at 1 (field lock toggling); only the object interaction took it 1 to 0 to 2. Both sides `RESULT: PASS`, saved, PYDEC PASS. Its trace file records that the historical `ROCK_PLAYER_PROBE_RESULT waiting-after-all-inputs` is a last-iteration label bug (both raw final observations are status 2 and unlocked); the raw receipts are unchanged. (The label defect is one of the OMP-found items.)

**Owner disposition (2026-10-02): "driver step + document it".** Accepted native limit text, verbatim:

> After a Rock Smash wild battle the field script is left WAITING (EventScript_SmashRock waitstate not resumed by Task_ReturnToFieldNoScript; identical in vanilla pret); the SLink overworld checkpoint withholds hello and writes until the player's next script FINISHES (NPC/sign interaction, door or map load); also true of the qualified Emerald title; fail-closed; possible later fix = a checkpoint clause (signed predicate, separate project).

No checkpoint, client or gate change was made. (The text committed in `tests/fixtures/gen3/README.md` and the manifest has "next script (NPC/sign interaction, door or map load)" without "FINISHES"; the owner's wording is the one above. Align the committed text when the docs are next touched.)

**Independent verification (OMP, 2026-10-02, source-only; lane-reported, not verified here except where marked).**
* Same code in the expansion pin, vanilla pret `pokeemerald` and `pokefirered`, so **FRLG is affected too**. I verified only the pinned expansion (`script.c:305-313`, `field_screen_effect.c:492-500`, `field_move_scripts.inc:81-93`); an independent OMP source-only pass (2026-10-02) read vanilla pret pokeemerald and pokefirered and found the same code, and Radical Red remains unverifiable from source.
* **Radical Red: UNVERIFIED.** No RR source here; its pack declares the same predicate (`script_context_status` expect 2).
* The expansion's **Overworld Wild Encounters** (`InteractWithOverworldWildEncounter` to `StartWildBattleWithOWE` to `BattleSetup_StartWildBattle`) share the stall. Expansion-only; real map use unverified. I confirmed `StartWildBattleWithOWE` ends in `BattleSetup_StartWildBattle()` (`wild_encounter_ow.c:364-410`); the stall inference is the reviewer's.
* **DexNav is NOT affected** (scripted return: `ScriptContext_SetupScript(EventScript_StartDexNavBattle)` at `dexnav.c:1102` is consistent; the return path was not traced here).
* `force_faint` and `force_explode` are NOT affected (battle() clauses only) (lane-reported).
* Recovery needs a script to finish (expect 2 = SHUTDOWN). Start menu, idle, plain steps, and B/A against nothing do NOT reset it (verified from the `8dd64eaa` trace, above).

Earlier Rock attempts failed for other reasons (`b32454c5` hello timeout from the Mirage pulse; `db1ed073` slot mismatch; `f09bf2cd` settle), all retained as fail logs.

## Duo rows: retained PASS per row (DEV; NOT frozen, NOT carry-qualified)

Source: `patch/build/exp_final_dev_row_table.json` (Codex's table; `patch/build/` is gitignored, so this file is not in the repo; its scope line is "19 historical DEV receipts at different cuts; every frozen final-cut row must still RUN"). I checked that each named receipt exists, is tracked, and shows `RESULT: PASS` for both clients and `PYDEC: PASS` with no FAIL line; where a log has an `EXIT` line it is `EXIT 0`. Rows marked (nx) have no `EXIT` line in the retained excerpt.

| Row | Retained PASS at | Receipt (under `docs/gen3_emerald/probes/`) |
|---|---|---|
| `link_gen3` (nx) | `ea9c8a07` | `dev_2026-10-01/link_gen3.log` |
| `boxsync_gen3` (nx) | `ea9c8a07` | `dev_2026-10-01/boxsync_gen3.log` |
| `release_gen3` | `343d2345` | `dev_2026-10-01/rel1.log` |
| `gift_gen3` (nx) | `b5024ed7` | `exp_acq_gift_gen3_b5024ed7_dev_console.txt` |
| `egg_receive_gen3` (nx) | `b5024ed7` | `exp_acq_egg_receive_gen3_b5024ed7_dev_console.txt` |
| `egg_hatch_gen3` (nx) | `6282a092` | `exp_acq_egg_hatch_gen3_6282a092_dev_console.txt` |
| `choice_gift_gen3` (nx) | `6282a092` | `exp_acq_choice_gift_gen3_6282a092_dev_console.txt` |
| `gift_box_gen3` (nx) | `ec79c703` | `exp_box_fixed_ec79c703_console.txt` |
| `faint_cmd_gen3` | `65e667e6` | `exp_live_faint_cmd_gen3_65e667e6_dev.txt` |
| `linked_faint_active_gen3` | `1a735d4e` | `exp_parallel_linked_faint_active_gen3_1a735d4e_dev.txt` |
| `whiteout_gen3` | `1a735d4e` | `exp_parallel_whiteout_gen3_1a735d4e_dev.txt` |
| `exp_static_static_gen3` | `65e667e6` | `exp_live_exp_static_static_gen3_65e667e6_dev.txt` |
| `exp_static_static_run_gen3` | `65e667e6` | `exp_live_exp_static_static_run_gen3_65e667e6_dev.txt` |
| `exp_static_grass_gen3` | `65e667e6` | `exp_live_exp_static_grass_gen3_65e667e6_dev.txt` |
| `exp_static_surf_gen3` | `b32454c5` | `exp_live_exp_static_surf_gen3_b32454c5_dev.txt` |
| `exp_static_fish_gen3` | `1a735d4e` | `exp_parallel_exp_static_fish_gen3_1a735d4e_dev.txt` |
| `exp_static_altering0_gen3` | `1a735d4e` | `exp_parallel_exp_static_altering0_gen3_1a735d4e_dev.txt` |
| `exp_static_altering1_gen3` | `db1ed073` (FAIL at `1a735d4e`) | `exp_parallel_exp_static_altering1_gen3_db1ed073_dev.txt` |
| `exp_static_rock_gen3` | `cd6b0648` (FAIL at `901e888d`, `db1ed073`, `f09bf2cd`) | `exp_rock_default_cd6b0648_dev.txt` |

These are **19 rows, 19 retained PASS logs at 10 distinct source SHAs**; none is at the current tip, and none is a final-cut receipt. The `linked_faint_active_gen3` wording and the Altering 1 fix (live-pointer selector reads, `db1ed073`) are unchanged from the last refresh (below).

* **`linked_faint_active_gen3` wording (the claim as it should be read).** The faint is an **engine-resolved in-battle HP0, observed by the harness HP-0 watcher**. It is **not a damage-KO claim and not test-forced**: `ACTIVE_KO ... inputs=0 hp_writes=0` and a `FORCED_HP0` marker emitted by the watcher. The scenario reaches that state through the client's `force_faint` Perish commit (`ACTIVE_COMMIT ... writes=5`), so the setup does write; the HP drop itself does not. The `ENGINE_FAINT_SITE` marker is not key-bound (limit (c), now accepted).
* The earlier note that the lane re-passed `static`, `static_run`, `grass`, `surf` in the `1a735d4e` wave is **lane-reported; no `1a735d4e` log for those four is in the tree.**
* Static/wild rows use the disclosed Damp lead (abilityNum 1 to 2) and Master Ball preps. `static_run` is the dead-zone negative with its exact ledger via `is_formed_link`.

## Landed on the branch (rows unchanged from the last refresh unless marked)

| Commit | Change | Evidence |
|---|---|---|
| `8dd64eaa`, `cd6b0648`, `d78eb2b9` | **New:** Rock diagnostic, the driver step (native tip dialogue before the unchanged settle/SAVE/PYDEC), the default-row binding to the context replacement with live object matching; manifest and README text updated; unit tests extended. | MODEL (unit) + DEV (above). Tracked change set: `lua/tests/duo/{duo_gen3_main,scenario_gen3_static_wild}.lua`, `tools/gen3_static_wild_rows.py`, `tests/unit/test_gen3_exp_static_wild_rows.py`, fixtures README + manifest. No `lua/gen3/*` or server change. |
| `0d067d6f`, `5634a0b0` | `ctx.lose_active` finishes a whiteout on the expansion (own `MoveInfo.effect` table; plain `EFFECT_HIT` fallback once the no-damage move's PP is spent). | MODEL; independent review ACCEPT. Limit: Thrash/Uproar/Recharge fail closed. `whiteout_gen3` PASS DEV. |
| `d6102d23` | `hatch` site (AddHatchedMonToParty `0811B284`, capture +0xDA, hatchling in **R4**); PC release pairing by frame window. | SOURCE (disassembly) + MODEL. **Red at its own SHA** (the 21 to 22 site pin landed in `9fc060ed`): squash at landing. |
| `9fc060ed`, `7c349ab4`, `bfc00eb8`, `f67c12e4` | `gift_areas` was `[]`; now five verified ids with fail-closed generator guards; rival filtered by player gender in `server/adapters/gen3_expansion.py`; gift policy from the source census. | SOURCE + MODEL; independent review findings applied. |
| `6df0441f` and later | `tools/gen3_final_cut.py --title exp`. | MODEL. **30 rows = 7 SOURCE (the six generated/census checks plus `shadow_negatives_exp`) + 1 unit (`unit_exp`, 39 test modules = 29 by filename glob `test_gen3_exp_*`/`test_gen3_expansion_*` + 10 in `EXPANSION_UNIT_EXTRAS`; a new expansion test outside those names and not added to the extras is silently excluded) + 19 duo + 3 ZIP (`exp_zip_build`, `exp_zip_check`, `zip_boot_exp`).** Retained plan dump `exp_plan_1b050038_2026-10-01.txt` header: `rows=30`. |
| `343d2345`, `f4763732` | `release_gen3` selectable for `gen3_exp`; `emerald_pc_box_place` uses `PC.OPTION.move_mons` (0 on the expansion). | MODEL + DEV live PASS. |
| `3376e179` | Ruling 40 for the expansion: gym leaders and trainers file under their town. | SOURCE + MODEL; browser check (DEV, mock, not retained). |
| `02df12c6`, `c2c55d75`, `379f4f5b`, `f9a93b7d`, `c6b093e6`, `3c495a47` | Unknown release pairing mode refused; PC negative legs ordered after `emerald_save_town`; cancel, full-box and bypass legs authored and corrected; the full-box closing note names the real absence window. | MODEL; observer receipts below. |
| `54ec247e`, `05acb5ba`, `5b94a8ab` | `mon_given` re-pinned to `GiveScriptedMonToPlayer` `081C2E74`+0x68; every site also hooked at its `+0x02000000` ROM-mirror alias (**22 kinds / 44 hooks**). Bounded: `gScriptCmdTable` 231/231 mirrored, `gBattleScriptingCommandsTable` 0/251, `gSpecials` 1/621. | SOURCE + MODEL. |
| `eacb615b` | `faint` re-pinned inside `SetValuesOnFaint` (`080df4a4`, hook `+0x82`, capture `+0x86`). | SOURCE + MODEL (`test_gen3_exp_faint_pin.py`). |
| `906b34f2` | Native catch EV oracle. | MODEL. |
| `9094ef93`, `28d37a8e`, `8c79b995`, `9b2d0d30`, `048db86b` | Fixture registry (`exp_*.sav` fixtures in `tests/fixtures/gen3/`; 38 files re-counted at `d6d6470c`), including the SYNTH `exp_pc_negative_chain_synth` (one extra usable boxed record), `box0-full`, and Mirage-resolved Rock seeds. | SOURCE + MODEL; SYNTH, disclosed in manifests. |
| **`67493da5`** (+ `9a6a8d69`, `89af051f`, `ec169b94`) | **Client cold-boot baseline fix in `lua/gen3/client.lua`**: `observe_known` calls `rescan_boxes()` before `seed_known()`. | MODEL (commit messages only; not re-verified here). **Runs for VANILLA Gen 3 titles too**: see blast radius. |
| `b32454c5`, `13d58ca4` | `linked_faint_active` oracle: read-only FORCED_HP0 watcher binds HP0 < engine site <= TX faint < completion. | MODEL + DEV PASS. |
| `db1ed073`, `ab101124`, `901e888d`, `9cb921db`, `1dba386c`, `8e3486d9`, `76580197` | EXP-C: live-pointer selector reads; SYNTH SFC32 state at the Rock entry; read-only Rock post-capture observation; retained evidence. | MODEL + DEV. |
| `b443c438`, `1a735d4e`, `1c9f222c`, `41ee8c66` | Harness only: `expected_ball`; screenshots namespaced per row/player; HELLO diagnostics. | MODEL. |
| `a77f3520`, `1b050038`, `0c36fe9a`, `5ce0eb57`, `901e888d`, `ccfa94e0`, `311cbe7e` | EXP-E: `docs/gen3_exp/negatives_manifest.json`, plan row `shadow_negatives_exp`, three PC windows and positive siblings bound to the manifest. | MODEL + PHYSICAL DEV (below). |

Earlier rows not repeated here (`8e6dc74b`, `a531d5cf`, `b5024ed7`, the Lease C rows) are unchanged.

## Unit lane (MODEL)

* **Last complete record:** the 39-module expansion unit set from clean `1b050038`: **940 passed, 0 skips, exit 0, 313 s** (`patch/build/exp_unit39_final.txt`, header `SOURCE_UNIT_DEV cut=1b050038... modules=39; no emulator/frozen-cut qualification`; retained in-repo as `docs/gen3_emerald/probes/exp_units_1b050038_2026-10-01.txt`). Earlier 37-module run: 810 passed.
* **Current tip `2270e033`** (receipts only atop code `d78eb2b9`): the full 39-module expansion unit set at `d78eb2b9` is **953 passed, 0 skips, exit 0** (`docs/gen3_emerald/probes/exp_units_d78eb2b9_2026-10-02.txt`); 3 of the 6 generated/census checks (`gen_gen3_profile`, `gen_gen3_write_checkpoint`, `gen_gen3_engine_signals`) and the PC manifest checker (15 zero checks) exit 0 at `d78eb2b9`; `area_map_generated_check_exp`, `gift_census_check_exp` and `wild_rom_check_exp` were NOT in that receipt and are evidenced only at `1b050038`; `--dry-run` shows 30 RUN / 0 CARRY / 0 CACHE (`exp_checks_d78eb2b9_2026-10-02.txt`, `exp_plan_d78eb2b9_2026-10-02.txt`). Source/model evidence, not a cut.
* The same file set is the plan's `unit_exp` row; a dev run is not the row itself.
* **SOURCE-only dry run at `1b050038`** (retained in `462ed983`): `exp_source_checks_1b050038_2026-10-01.txt` (six generated/census checks each `EXIT 0`; `tools/gen3_shadow_negatives.py`: `SUMMARY PASS receipts=3 checks=15 passed=15 failed=0`) and `exp_plan_1b050038_2026-10-01.txt` (**30 rows, RUN 30 / CACHED 0 / CARRY 0, budget ceiling 887 m**). I read these and ran nothing. They are stale against the tip (the three new commits touch Lua scenario, tools and unit files, not the generated artifacts, but I did not re-run the checks).

## Live results other than the duo table (DEV unless marked)

* **Single-cart PC observer, positive legs:** two earlier runs (`pclegs1.log`, `pclegs2.log`) are **PRE-MIRROR** (registered 22 before `05acb5ba`). Fired kinds across them: 7 (`map_load`, `pc_deposit`, `pc_box_place`, `pc_withdraw`, `pc_release_begin`, `pc_release`, `save`) plus the `frame_control` STATUS counter. Current runs register 22 kinds / 44 hooks.
* **Browser check** (coordinator's in-app browser, SYNTH payloads): numbers **not retained in-repo**. No title has had a live two-emulator calc run.

## PC negative legs (PHYSICAL DEV, single-cart observer)

Receipts under `docs/gen3_exp/probes/`, bound by `docs/gen3_exp/negatives_manifest.json` (`evidence: PHYSICAL_DEV_OBSERVER`) with the window and sibling claims asserted by the unit row `test_exp_pc_negative_manifest_binds_real_windows_and_positive_siblings` (`tests/unit/test_gen3_final_cut_exp.py:464`); plan row `shadow_negatives_exp` proves only that the three receipts are present, intact and free of five unrelated kinds (checker not run by me; Codex's retained source-only output at `1b050038` is `SUMMARY PASS receipts=3 checks=15`). The manifest's scope line: raw observer windows, **client reporting not qualified**.

* **Bypass** (run at `048db86b`, window frames 5813 to 6991): the grabbed mon is gone from every box and the party is unchanged; `pc_release` at frame 6609 with **no `pc_release_begin`** (unpaired).
* **Cancel** (same run, window 6991 to 8667): release **absent** in the window; a later real YES release is valid at frame 9782 (begin plus release). Runs on `exp_pc_negative_chain_synth`.
* **Full box** (run at `ccfa94e0`, window 1602 to 2168): `box-full` reached (`MSG_BOX_IS_FULL`), `pc_deposit` count 0 in the window, and a positive sibling deposit into box 1 happens later.
* **Not proven:** the **client half** (that the client reports no release for the bypass) is a **DUO claim**, not shown by these windows. It is part of accepted limit (b).

## Pin-completeness audit and the ROM mirror (unchanged)

22 site kinds under `titles.emerald_expansion_28877d73.artifacts.clean.sites` (SOURCE, `--check`). The 0x0A ROM mirror was the one expansion-wide finding and is fixed (`05acb5ba`). Otherwise complete or fail-closed: `whiteout` (7 callers), `save`, `battle_begin`/`battle_end`, `poison_faint`, the five PC kinds. `map_load` misses new-game, cable-club and contest-hall returns (named limit). The moved-mon bypass is reachable by source (`pokemon_storage_system.c:7813-7814`, `:7510-7513`, `:6558-6561`) and is observed physically.

## Known issues found, not caused here

* `tests/unit/test_e2e_duo_scenario_selection.py::test_gen3_frlg_keys_do_not_leak_and_nothing_leaks_in` failed on master `ea9c8a07` too (RR lane; no log retained). Master `735dea38` fixed "two stale expectations" (README ports, hidden-NPC `key_change`); I did not check whether it also covers this test.
* Regenerating `calc/src/js/data/sets/games/EmeraldExpansion.js` writes LF while the working tree is CRLF, which trips the clean-tree gate. Convert to CRLF after regenerating.
* 6 abilities and 54 items have no calc mapping (`EXPECTED_UNRESOLVED`); 1 of 1825 trainer slots affected (Smoke Ball).

## SYNTH preconditions used (disclosed; the owner explicitly allowed SYNTH tests)

Damp lead (abilityNum 1 to 2); Master Ball item (static positive and method rows); Mirage-resolved seeds; the Rock SFC32 state (runtime, not saved); box0-full, 420-record and 5-usable PC seeds. Each is in an `exp_*_manifest.json`. SYNTH marks setup only; the behaviour under test runs natively.

## Shared-runtime blast radius (unchanged; re-read at HEAD)

Against `ea9c8a07`, `git diff --stat -- lua/gen3/client.lua lua/gen3/signals.lua` is client.lua +32/-7 (39 lines changed) and signals.lua 63 lines changed (86 insertions, 16 deletions in total). **`67493da5` changes `lua/gen3/client.lua` for the VANILLA Gen 3 titles too**, so it is not vanilla-neutral and stales vanilla Gen 3 receipts. I did not audit the other client.lua hunks for vanilla no-ops. **Gen 2 digest scope:** `git diff --stat ea9c8a07..HEAD -- server lua/core lua/gen2 'data/games/gen2_*'` returns only `server/adapters/gen3_expansion.py` (+56/-4) at `d78eb2b9`; re-run at the freeze. The three new commits touch none of those paths.

## Named limits

**Owner rulings 2026-10-02 (recorded as stated to me; the ruling documents themselves were not read here):**

* **(a) ACCEPTED:** the visible Mirage Tower pulse task `UpdateMirageTowerPulseBlend` is not in the checkpoint allow-list (fail-closed; hello and writes withheld; also true of the qualified Emerald). The Rock seeds use the disclosed SYNTH Mirage-resolved state.
* **(b) ACCEPTED:** a held mon released through the PC is discarded with no `pc_release_begin`. The client half is a duo claim, unproven.
* **(c) ACCEPTED:** the `ENGINE_FAINT_SITE` marker is not key-bound (active-slot and frame bound only).
* **(e) Rock Smash: ACCEPTED NATIVE LIMIT with a driver step**, verbatim text above. It no longer gates the cut.

**Still proposals (no ruling reported):** (1) shinyModifier (ruling 38). (2) 6 abilities / 54 items unmapped in calc. (3) Altering Cave set 0 only (display-only). (4) Wynaut egg not fixed-species. (5) Thrash/Uproar/Recharge cannot complete the whiteout fallback. (6) Shedinja from evolution (inherited). (7) Mystery Event gift. (8) `map_load` coverage (three returns). (9) No live two-emulator calc run. (10) Routing refused until routed. **(d)** SYNTH preconditions are a disclosure (list above), not a ruling item.

## Owner decisions, kept separate

1. **Sign XG3 only after the final cut** (not run; about 15 h serial, about 5 h in 3 shards). Sign on `fc_SUMMARY_<CUT_SHA8>_exp.txt`, `<ROWS_PASSED>` of `<ROWS_TOTAL>`.
2. **Routing flip (ruling 39)** is a distinct yes, with a Gen 2 ping.
3. **Gen 2 ping before landing** (only `server/adapters/gen3_expansion.py`).
4. **Landing** is squashed into about 6 logical groups (`d6102d23` is red at its own SHA), rebased over `735dea38`.
5. **Push and tag** are separate approvals.
6. Rulings still open: the earlier proposal list (1) to (10).

## Still open

* The `--title exp` cut at the frozen tip: `<ROWS_TOTAL>` rows (30 expected), `<ROWS_PASSED>` passed, `<ROWS_FAILED>` failed; ZIP build and boot; XC5 live two-emulator calc.
* The frozen-cut unit row (the 953-pass run above is source/model evidence at `d78eb2b9`, not the cut).
* Observer receipts for the remaining kinds (`battle_end`, `evolve_species_store`, `poison_faint`, `poison_hp_before`, `pc_move`, `trade_*` have no run evidence in the table).
* Client-half proof for the PC bypass (accepted limit (b)).

### How to run the cut (shard pattern; nothing here was run by me)

```
python tools/gen3_final_cut.py --cut <CUT_SHA> --title exp                  # serial (not measured)
python tools/gen3_final_cut.py --cut <CUT_SHA> --title exp --shard 1/3      # 3 shards: measured 2026-10-02, source+unit 10-14 min alone, then the 19 duos in about 8-20 min per shard, ZIP about 1 min
python tools/gen3_final_cut.py --cut <CUT_SHA> --title exp --shard 2/3
python tools/gen3_final_cut.py --cut <CUT_SHA> --title exp --shard 3/3
```

`--shard i/n` exists in `tools/gen3_final_cut.py` (`parse_shard`, line 2092; each shard writes `fc_..._shard<i>of<n>` outputs, rows are split with state/tutorial chains kept together); `--dry-run` prints the plan and launches nothing; `--lane` and `--master` default to sibling `gen3-lane-*` worktrees. SOURCE read only; nothing run. The 3-shard split and the 5 h figure remain lane-reported.

### Cut record 2026-10-02 (evidence; not signed, not a landing)

* `f2551363`: 29/30 PASS. Only `whiteout_gen3_exp_as_a` FAILED (driver `lose_active` hunt cap 6: the lone Mudkip lead, HP20, burned Growl's 40 PP, then the Tackle fallback beat every wild foe; the HP 6..3 `ENGINE_FAINT_SITE` lines were FOE faints). Unit 953 pass / 0 skip, ZIP 3/3 PASS. Receipts `fc_*_f2551363.txt` and `fc_SUMMARY_f2551363_exp.txt` are retained, no verdict rewritten.
* Fix `965dbc08` (+ evidence `43e534ba`): disclosed SYNTH whiteout-only seed `exp_whiteout_synth[_b].sav` (lead HP 1/20: `BoxPokemon.hpLost` +0x1E 0->19 and cached `Pokemon.hp` +0x56 20->1, nothing else; native CONTINUE/SAVE qualified; the game itself logged HP 1/20 at the first battle turn, `exp_whiteout_965dbc08_a_full.txt:37`). No driver or `lose_active` change.
* `43e534ba`: source 7/7 PASS, then `unit_exp` FAILED on skips (956 passed, 9 skipped, 851 s): the nine `test_extract_expansion_data.py` vanilla-control tests skipped because `SLINK_EMERALD_ROM` was not set and the fresh lane has no vanilla Emerald copy. Cause: the launch omitted the documented `os.environ['SLINK_EMERALD_ROM']` line that the first cut's launch had. Not a product regression, but the skip=FAIL rule stands and a FAIL receipt blocks the row at that SHA, so `43e534ba` is finished; no duos ran there. Receipts `fc_*_43e534ba.txt` retained.
* **`0b3f15ea3152c5b3e1f8bc53415f26c28f3631b3` (code identical to `965dbc08`): `--title exp` cut 30/30 PASS** (`RUN 30 / CARRIED 0 / CACHED 0 / FAIL 0`, every row attempt 1, merged summary `docs/gen3/probes/fc_SUMMARY_0b3f15ea_exp.txt`, receipts `fc_*_0b3f15ea.txt`). 7 SOURCE PASS; `unit_exp` 965 passed / 0 skips (480 s; the nine vanilla-control tests ran); 19 duo PASS in three concurrent shards; ZIP build/check/test-only boot PASS. `whiteout_gen3` passed with the native first-turn HP 1/20 (frame 3264) and a strict PYDEC; `exp_static_rock_gen3` passed with its accepted native limit (NPC interaction step). The cut is evidence for the owner's XG3 signature decision; XG3 remains UNSIGNED, routing remains refused, nothing is pushed or landed on master.
* Required for every launch of the `--title exp` cut: after sourcing `g3-env.sh`, set `SLINK_EMERALD_ROM` to the absolute path of the root vanilla Emerald ROM (`Pokemon - Emerald Version (USA, Europe).gba`, sha1 `f3ae088181bf583e55daf962a92bb46f4f1d07b7`, checked by `tools/extract_expansion_data.py:37`) and print its sha1 in the controller console before the first row. `copy_expansion_inputs` stages only the expansion bundle and pret, not the vanilla ROM.

## Claims I could not verify

* The `1a735d4e` wave re-PASS of `static`, `static_run`, `grass`, `surf` (no `1a735d4e` log; older-SHA PASS logs exist).
* That the `1a735d4e` wave tree was clean (logs carry no `dirty` string; the lane says clean). The same holds for the other retained PASS logs (I grepped them for `dirty`: none).
* The independent OMP verification of the Rock limit beyond the expansion pin: identical code in vanilla pret `pokeemerald`/`pokefirered` (so FRLG affected), Radical Red (UNVERIFIED by the source of the claim as well), OWE sharing the stall, DexNav and `force_faint`/`force_explode` not affected. I read only the pinned expansion lines.
* "Also true of the qualified Emerald title" (Rock and Mirage): no Emerald run and no Emerald checkpoint policy re-derivation here.
* The owner rulings of 2026-10-02 and the exact limit text (taken from the task statement; the committed README and manifest carry the text without the word "FINISHES").
* That OMP reviews found and fixed the faint oracle, Rock probe label and PC legs (commit history is consistent; the review transcripts are not in the tree). That the new Gen 3 OMP peers are addressed by id.
* The 15 h serial / 5 h in 3 shards estimate (887 m is a budget ceiling).
* (resolved: 953 passed at `d78eb2b9`; the 940 figure was for `1b050038`.)
* `67493da5` red-first / revert-checked / 293 tests; whether the other `lua/gen3/client.lua` hunks are no-ops on vanilla titles; that the Gen 2 digest excludes `lua/gen3/`.
* That `area_map_generated_check_exp`, `gift_census_check_exp` and `wild_rom_check_exp` still pass at the tip (their retained output is at `1b050038`).
* That the 19-row table is the full duo set for `gen3_exp` (the count 19 comes from the table and the earlier derivation of `build_plan_exp` with git stubbed; I did not call the function this time).
* That the browser-check numbers and the `exp_*.sav` fixture count are current (not re-counted).
