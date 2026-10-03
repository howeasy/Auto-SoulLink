# XG3 request: expansion probe / observer / duos (draft v3, 2026-10-02)

- **Branch:** `claude/gen3-exp-xg3` (worktree `C:/slink-wt/exp-xg3`), off local master `ea9c8a07`.
  Local only: not pushed, not merged. **88 commits ahead of master at HEAD `d78eb2b9`, and 1 commit behind
  master** (`735dea38`: README port notes and a hidden-NPC `key_change` test expectation; owner-approved, not
  pushed). Rebase or squash at landing. Recount at the freeze: `<COMMITS_AHEAD>`.
- **Plan:** `docs/gen3_emerald/PLAN.md:84` — the **X3** row ("Probe/observer/duos"), gate **XG3**.
- **Ledger:** `docs/gen3_emerald/REQUIREMENTS.md` expansion rows (source pin + compiler rows are
  **SIGNED XG0 2026-09-26**; `XG1`–`XG4` unsigned).
- **Status: SIGNED 2026-10-02 by the owner in chat** ("Yes, sign XG3 at 0b3f15ea", answer to an explicit question), against the final cut
  `0b3f15ea3152c5b3e1f8bc53415f26c28f3631b3`: `python tools/gen3_final_cut.py --title exp` = **30 of 30 rows PASS**
  (RUN 30 / CARRIED 0 / CACHED 0 / FAIL 0, `docs/gen3/probes/fc_SUMMARY_0b3f15ea_exp.txt`, receipts committed at `6c3b8146`).
  The signature accepts: named limits (a)(b)(c) and the Rock Smash native limit, the disclosed SYNTH list including the
  whiteout-only HP 1/20 seed (`965dbc08`), and the earlier-listed limits. It does NOT flip routing (ruling 39: owner chose
  "flip routing after landing", shown to the owner before it lands) and does not push or tag. The `<CUT_SHA>`,
  `<ROWS_TOTAL>`, `<ROWS_PASSED>` placeholders below resolve to 0b3f15ea / 30 / 30; the draft body is otherwise the
  pre-cut text and is kept as written.

Tags: **SOURCE** (a file/commit/ROM disassembly in this tree) · **MODEL** (a unit suite or
independent review) · **DEV** (a real run that is not a receipt) · **PHYSICAL** (a real emulator run;
receipt-grade only at the frozen cut). A **dev run is not a receipt**: the harness's clean-cut gate
refuses a `+dirty` tree (`probes/dev_2026-10-01/whiteout2.log:38`). Where no run evidence exists the
row says `<<EVIDENCE?>>`. Companion record: `docs/gen3_emerald/XG3_PROGRESS_2026-10-01.md` (v3) is
authoritative for what passed and what is dev-only.

## 0 Summary

The expansion reference build (`28877d73`) has **22 engine-site kinds bound and generated** (counted
from `titles.emerald_expansion_28877d73.artifacts.clean.sites` in
`data/games/gen3_exp/28877d73/engine_signals.json`), generated from the build's own `.sym`/`.map` and
reproducible by `--check` (**SOURCE**). Every site is also hooked at its `+0x02000000` ROM-mirror alias
(22 kinds / 44 hooks). The faint site is re-pinned (`eacb615b`).

Since the last draft (`dc3e2a24`): **every one of the 19 duo rows now has a retained DEV PASS**
(source cuts differ; none frozen); **Rock Smash is DEV PASS** with an owner disposition ("driver step +
document it") in place of the old "gates the cut"; the owner **accepted limits (a), (b), (c)**; local
master advanced to `735dea38`. XG3 is still not signable: the cut has not run. §3 lists what is owed.
Independent OMP reviews found and fixed defects along the way (faint oracle, Rock probe label, PC legs)
(lane-reported); the new Gen 3 OMP peers are addressed by id.

## 1 What XG3 signs

From `PLAN.md:84`, XG3 signs the **probe / observer / duo** layer on the expansion RC candidate:

- Every `gen3_exp` row of the final cut: source `--check` rows, a receipt-integrity and expected-zero checker (`shadow_negatives_exp`: 15 checks, all on five unrelated
  kinds; the three PC negative claims are bound by the unit row `tests/unit/test_gen3_final_cut_exp.py:464`,
  not by that row), the
  expansion unit gate, the test-only duo rows, and the ZIP build + boot (`tools/gen3_final_cut.py
  --title exp`).
- `gen3_title_syms.lua` gets **generated** per-build entries from the build's `.sym` (no hand column).
- P+H re-derived for `struct Volatiles` for this build.

**XG3 does NOT sign:** admission/routing (still refused in production, ruling 39), XG1's data
extraction, XG2's record layout, or the master landing.

## 2 Evidence by engine-site kind and by row

All 22 kinds are pinned at `PINNED_SOURCE_ONLY` (**SOURCE**); the pack is not marked live-verified.
"Fired" means seen firing in a **DEV** run.

| Kind | Site status | Fired in a run | Evidence |
|---|---|---|---|
| `frame_control` | SOURCE + MODEL | yes (STATUS counter, not a fired kind) | `pclegs1.log:39` |
| `map_load` | SOURCE | yes, run 1 (pre-mirror) | `pclegs1.log` SHADOW |
| `pc_deposit` | SOURCE | yes, run 1 (pre-mirror); **absent by design in the full-box window** | `pclegs1.log`; `docs/gen3_exp/probes/pc_ccfa94e0_*_windows.txt` |
| `pc_box_place` | SOURCE | yes, runs 1+2 (pre-mirror) | `pclegs1.log`, `pclegs2.log` |
| `pc_withdraw` | SOURCE | yes, run 1 (pre-mirror) | `pclegs1.log` SHADOW |
| `pc_release_begin` | SOURCE | yes, run 2 (pre-mirror); **absent by design in the bypass and cancel windows** | `pclegs2.log:44`; `pc_release_bypass_observer.shadow.log` |
| `pc_release` | SOURCE | yes, run 2; **present and unpaired in the bypass window** (frame 6609) | `pclegs2.log:45`; `pc_release_bypass_observer.shadow.log` |
| `save` | SOURCE | yes, run 2; counter 2 to 3 | `pclegs2.log:32` |
| `hatch` | SOURCE + MODEL | duo DEV: `egg_hatch_gen3` retained PASS at `6282a092` (both clients, PYDEC PASS) | `exp_acq_egg_hatch_gen3_6282a092_dev_console.txt` |
| `battle_begin` | SOURCE + MODEL | duo DEV (`link_gen3`) | `link_gen3.log` |
| `battle_end` | SOURCE + MODEL | `<<EVIDENCE?>>` | — |
| `capture_wild` | SOURCE + MODEL | static/grass/Surf/Altering/fishing/**Rock** duo rows DEV PASS | `probes/exp_live_exp_static_*_dev.txt`, `exp_parallel_*_dev.txt`, `exp_rock_default_cd6b0648_dev.txt` |
| `mon_given` | re-pinned `54ec247e` to `GiveScriptedMonToPlayer` `081C2E74`+0x68 (`081C2EDC`); mirror alias `05acb5ba`. `gift_gen3`, `egg_receive_gen3` PASS (one signal per side, callback `0A1C2EDC`) | yes, duo DEV | `b5024ed7` logs |
| `evolve_species_store` | SOURCE + MODEL | `<<EVIDENCE?>>` | — |
| `faint` | SOURCE + MODEL; re-pinned `eacb615b` inside `SetValuesOnFaint` (hook `+0x82`, capture `+0x86`) | `faint_cmd_gen3` PASS DEV (`65e667e6`); `linked_faint_active_gen3` PASS DEV (`1a735d4e`) | `exp_live_faint_cmd_gen3_65e667e6_dev.txt`, `exp_parallel_linked_faint_active_gen3_1a735d4e_dev.txt` |
| `whiteout` | SOURCE + MODEL | `whiteout_gen3` PASS DEV (`1a735d4e`) | `exp_parallel_whiteout_gen3_1a735d4e_dev.txt` |
| `poison_faint`, `poison_hp_before`, `pc_move`, `trade_begin`, `trade_done`, `trade_evolve_species_store` | SOURCE + MODEL | `<<EVIDENCE?>>` | — |

**Duo results: one retained PASS per row (PHYSICAL DEV; source cuts differ; NOT frozen, NOT
carry-qualified).** Each log shows `RESULT: PASS` on both clients and `PYDEC: PASS`; where an `EXIT`
line exists it is `EXIT 0`. Source: Codex's `patch/build/exp_final_dev_row_table.json` (gitignored, not
in the repo; its own scope line says every frozen final-cut row must still RUN), with the receipts
checked to exist and be tracked.

| Row | PASS at | Receipt (`docs/gen3_emerald/probes/`) |
|---|---|---|
| `link_gen3`, `boxsync_gen3` | `ea9c8a07` | `dev_2026-10-01/{link_gen3,boxsync_gen3}.log` |
| `release_gen3` | `343d2345` | `dev_2026-10-01/rel1.log` |
| `gift_gen3`, `egg_receive_gen3` | `b5024ed7` | `exp_acq_{gift,egg_receive}_gen3_b5024ed7_dev_console.txt` |
| `egg_hatch_gen3`, `choice_gift_gen3` | `6282a092` | `exp_acq_{egg_hatch,choice_gift}_gen3_6282a092_dev_console.txt` |
| `gift_box_gen3` | `ec79c703` | `exp_box_fixed_ec79c703_console.txt` |
| `faint_cmd_gen3` | `65e667e6` | `exp_live_faint_cmd_gen3_65e667e6_dev.txt` |
| `linked_faint_active_gen3`, `whiteout_gen3` | `1a735d4e` | `exp_parallel_{linked_faint_active,whiteout}_gen3_1a735d4e_dev.txt` |
| `exp_static_static_gen3`, `_static_run_gen3`, `_grass_gen3` | `65e667e6` | `exp_live_exp_static_*_65e667e6_dev.txt` |
| `exp_static_surf_gen3` | `b32454c5` | `exp_live_exp_static_surf_gen3_b32454c5_dev.txt` |
| `exp_static_fish_gen3`, `exp_static_altering0_gen3` | `1a735d4e` | `exp_parallel_exp_static_{fish,altering0}_gen3_1a735d4e_dev.txt` |
| `exp_static_altering1_gen3` | `db1ed073` (**FAIL** at `1a735d4e`: Lua RESULT PASS on both clients, PYDEC oracle FAIL (`observed selector differs from pending fixture`), unlike Rock's client-side FAIL) | `exp_parallel_exp_static_altering1_gen3_db1ed073_dev.txt` |
| `exp_static_rock_gen3` | `cd6b0648` (**FAIL** at `901e888d`, `db1ed073`, `f09bf2cd`) | `exp_rock_default_cd6b0648_dev.txt` |

19 rows, 10 distinct source SHAs, none at the tip. The lane reports Surf, static, static_run and grass
also passed in the `1a735d4e` wave; **no `1a735d4e` log for those four is in the tree (lane-reported, not
verified here)**.

**`linked_faint_active_gen3` wording.** An **engine-resolved in-battle HP0, observed by the harness
HP-0 watcher**; **not a damage-KO claim and not test-forced** (log: `ACTIVE_KO inputs=0 hp_writes=0`,
`FORCED_HP0` emitted by the watcher). The scenario reaches the state through the client's `force_faint`
Perish commit (`writes=5`); the HP drop itself is not written. The `ENGINE_FAINT_SITE` marker is
frame/active-slot bound, not key-bound (accepted limit (c)).

**Rock Smash (DEV PASS at `cd6b0648`; owner disposition 2026-10-02: "driver step + document it").**
The default Rock row (diagnostic flag absent) passed both clients plus PYDEC, `EXIT 0`, with native SAVE
witnesses **A `c12fe035736627a3f7c3518d3be084cb7c4a671d647540485c0ab4e248d2fe83` (counter 3 to 4) and B
`b26997907fd8b70e61ceb021c82150e72f308b11c2cc4b7e79d871300e8230ef` (counter 4 to 5)**, both
`match=true`. It **requires one native NPC interaction**: the Route 111 "Rock Smash tip" fat man object
at (19,101) (graphics id 17, hide flag `0x34B` clear): one step Up from (18,102), face Right, A through
the dialogue. `sGlobalScriptContextStatus` goes **1 to 0 to 2**, because the NPC script's
`ScriptContext_SetupScript` **overwrites** the parked `EventScript_SmashRock` context
(`src/script.c:305-313`); it is not resumed. From battle return to status 2 is **745 frames, about 12.4 s
at 60 fps**, dialogue included. The earlier A-only run without the interaction (`901e888d`) stayed at
status 1 for more than 21,500 frames and FAILED; it is retained as the expected-failure control. An opt-in
diagnostic (`8dd64eaa`, `SLINK_ROCK_PLAYER_PROBE=1`) showed idle, START menu, and B/A against nothing do
not reset it. `d78eb2b9` (the tip) changed the scenario Lua after the PASS; the PASS is at `cd6b0648`.

Accepted native limit, verbatim: *After a Rock Smash wild battle the field script is left WAITING
(EventScript_SmashRock waitstate not resumed by Task_ReturnToFieldNoScript; identical in vanilla pret);
the SLink overworld checkpoint withholds hello and writes until the player's next script FINISHES
(NPC/sign interaction, door or map load); also true of the qualified Emerald title; fail-closed;
possible later fix = a checkpoint clause (signed predicate, separate project).*

Independent verification (OMP, 2026-10-02, source-only; lane-reported, I read only the expansion pin):
same code in the expansion pin, vanilla pret `pokeemerald` and `pokefirered` (so **FRLG is affected too**);
**Radical Red UNVERIFIED** (no RR source here; its pack declares the same predicate `script_context_status`
expect 2); the expansion's Overworld Wild Encounters (`InteractWithOverworldWildEncounter` to
`StartWildBattleWithOWE` to `BattleSetup_StartWildBattle`, `wild_encounter_ow.c:364-410`) share the stall
(expansion-only; real map use unverified); **DexNav is NOT affected** (scripted return);
`force_faint`/`force_explode` are NOT affected (battle() clauses only); recovery needs a script to finish
(expect 2 = SHUTDOWN).

**Observer totals, the two earlier positive-leg runs:** 22 registered, 0 rejected, 0 dropped, no handler
error; **PRE-MIRROR** logs (current runs register 22 kinds / 44 hooks). **7 fired kinds** (`map_load`,
`pc_deposit`, `pc_box_place`, `pc_withdraw`, `pc_release_begin`, `pc_release`, `save`) plus the
`frame_control` STATUS counter. **PHYSICAL DEV.**

**Pins (SOURCE):** hatch `AddHatchedMonToParty` `0811B284`, capture `+0xDA`, hatchling in **R4**
(`d6102d23`, independent adversarial review ACCEPT, MODEL). Faint `SetValuesOnFaint` `080df4a4`, size
`0xD0`, two BL callers by ROM-wide scan (`eacb615b`, `tests/unit/test_gen3_exp_faint_pin.py`, MODEL).

**PC negative legs (PHYSICAL DEV, single-cart observer).** Receipts in `docs/gen3_exp/probes/`, bound
by `docs/gen3_exp/negatives_manifest.json`. The window and positive-sibling claims are asserted by the unit row
(`test_exp_pc_negative_manifest_binds_real_windows_and_positive_siblings`, `tests/unit/test_gen3_final_cut_exp.py:464`);
plan row `shadow_negatives_exp` proves only that the three receipts are present, intact and free of five unrelated
kinds (faint, capture_wild, mon_given, whiteout, trade_done). The manifest scope:
raw observer windows; **client reporting not qualified**.

| Leg | Run | Window | Observer result |
|---|---|---|---|
| bypass (moved-mon release) | `048db86b` | 5813 to 6991 | held-mon release removes the target from every box, party unchanged; `pc_release_begin` **absent**, `pc_release` **unpaired** (frame 6609) |
| cancel | `048db86b` | 6991 to 8667 | release **absent**; a later real YES release is valid (frame 9782). Uses `exp_pc_negative_chain_synth` |
| full box | `ccfa94e0` | 1602 to 2168 | `MSG_BOX_IS_FULL`; `pc_deposit` **absent** in the window; positive sibling deposit into box 1 follows |

`exp_pc_negative_chain_synth` is a **SYNTH** seed with one extra usable boxed record, because the pin's
release precondition refuses a release below 3 usable mons (chain 5, 4, 3, 3, 2). Only native
CONTINUE/SAVE is qualified for the seed. The **client half** (that the client reports no release for
the bypass) is a **DUO claim, not proven** (part of accepted limit (b)). `shadow_negatives_exp`'s checker
was **not run by me**; Codex's retained source-only output at `1b050038` is `SUMMARY PASS receipts=3
checks=15 passed=15 failed=0`.

> **Open: Rock's DEV PASS is at `cd6b0648`; `d78eb2b9` changed the scenario Lua afterwards (label/read-only extraction). The final cut re-runs `exp_static_rock_gen3` at the frozen SHA; do not rely on accepted limit (e) text until it has.**

## 3 Rows still to run at the frozen cut

`tools/gen3_final_cut.py --title exp` (**SOURCE**, read, not run). Every row RUNs and no historical
qualification is carried. Runtime rows log the server's `--test-only-route emerald_expansion_28877d73`.

**The plan is 30 rows = 7 SOURCE (incl. `shadow_negatives_exp`) + 1 unit (39 modules) + 19 duo + 3
ZIP.** The retained plan dump (`exp_plan_1b050038_2026-10-01.txt`) says `rows=30`, RUN 30 / CACHED 0 /
CARRY 0. The count is derived from the registry, so **recompute at the cut: `<ROWS_TOTAL>` rows,
`<ROWS_PASSED>` passed.**

- **7 SOURCE rows:** `profile_generated_check_exp`, `write_checkpoint_generated_check_exp`,
  `engine_signals_generated_check_exp`, `area_map_generated_check_exp`, `gift_census_check_exp`,
  `wild_rom_check_exp`, `shadow_negatives_exp`.
- **1 MODEL row:** `unit_exp` over `EXPANSION_UNIT_FILES` (39 modules). **Last complete dev run, clean
  `1b050038`: 940 passed, 0 skips, exit 0, 313 s** (`patch/build/exp_unit39_final.txt`; retained as
  `docs/gen3_emerald/probes/exp_units_1b050038_2026-10-01.txt`). **At the clean code tip `d78eb2b9` the full 39-module suite at `d78eb2b9` passed 953, 0 skips, exit 0** (`docs/gen3_emerald/probes/exp_units_d78eb2b9_2026-10-02.txt`); no final count is quoted. This is a dev run, not the row.
- **19 duo rows:** every `e2e_duo.SCENARIOS` name where `scenario_applies(s, "gen3_exp")`.
- **3 ZIP rows:** `exp_zip_build`, `exp_zip_check`, `zip_boot_exp`.
- Summary artifact: `fc_SUMMARY_<CUT_SHA8>_exp.txt`.
- **Time:** about 15 h serial, or about 5 h in 3 shards (lane-reported; the plan dump's summed budget
  ceiling is 887 m, about 14.8 h, a ceiling and not a measurement).
- **Source-only dry run at `1b050038` (DEV, retained in `462ed983`, read, not run by me):** the six
  generated/census checks `EXIT 0`; the PC-negative checker `SUMMARY PASS receipts=3 checks=15`; the plan
  dump `rows=30`. Stale against the tip; re-run at the freeze.

The SYNTH fixture registry (`tests/fixtures/gen3/README.md`; 38 `exp_*.sav` fixtures re-counted at `d6d6470c`, generator raw pins,
420-record full-box derivation, 30-record `box0-full` seed, `exp_pc_negative_chain_synth`) is **SOURCE +
MODEL**, disclosed as SYNTH in the `exp_*_manifest.json` files. The native catch EV oracle (`906b34f2`)
is **MODEL**.

## 4 Calc and panels

- **Six-town trainer fix** (`3376e179`, **SOURCE** + **MODEL**): Rustboro/Mauville/Fortree and four
  other towns' trainers and gym leaders file under their town (ruling 40).
- **Browser mock check (coordinator session; numbers NOT retained in-repo):** `/calc/normal.html` Gen 9
  calc resolved a SYNTH Mudkip and Roxanne's Nosepass (`Lvl 14 Mudkip Water Gun vs. Lvl 15 Nosepass:
  12-14 (32.4 - 37.8%)`); Upcoming Key Trainers carried Roxanne/Norman with four rematches each;
  `?prep=Leader%20Roxanne` opened the Prep tab. **DEV**, mock only; **no title has had a live
  two-emulator calc run**. `<<EVIDENCE?>>`
- **Gift areas** (`9fc060ed` → `bfc00eb8`, **SOURCE** + **MODEL**): five ids from the source census
  (`lavaridge_town`, `littleroot_town_professor_birchs_lab`, `mossdeep_city_stevens_house`,
  `route119_weather_institute_2f`, `rustboro_city_devon_corp_2f`); the generator fails closed on an
  unaccounted gift kind.

## 5 SYNTH preconditions (disclosed; the owner explicitly allowed SYNTH tests)

Damp lead (abilityNum 1 to 2); Master Ball item (static positive and method rows); Mirage-resolved
seeds (`VAR_MIRAGE_TOWER_STATE=3`, native `NoTower` layout 392); the Rock SFC32 state (runtime, not
saved); box0-full, 420-record and 5-usable PC seeds. SYNTH marks setup only; the behaviour under test
runs natively.

## 6 Named limits

**Owner rulings 2026-10-02 (as stated to me; the ruling record itself was not read here): ACCEPTED.**

* **(a)** The visible Mirage Tower pulse task `UpdateMirageTowerPulseBlend` is not in the checkpoint
  allow-list (fail-closed; hello and writes withheld; also true of the qualified Emerald). The Rock seeds
  use a disclosed SYNTH Mirage-resolved state.
* **(b)** A held mon released through the PC is discarded with no `pc_release_begin`. The client half is
  a duo claim, unproven (observer: PHYSICAL DEV, §2).
* **(c)** The `ENGINE_FAINT_SITE` marker is not key-bound (active-slot and frame bound only).
* **(e) Rock Smash: accepted native limit + driver step** (verbatim text in §2). No longer gates the cut.

**Still proposals; none signed:**

1. **Routing stays refused** until the owner routes the expansion (ruling 39). **SOURCE**
2. **shinyModifier** (ruling 38). **SOURCE**
3. **Unmapped calc data:** 6 abilities and 54 items; 1 of 1825 trainer slots (Smoke Ball). **SOURCE**
4. **Altering Cave set-0 scope:** display-only. Altering 0 and 1 rows both have retained DEV PASS.
5. **Wynaut egg is not fixed-species.** **SOURCE**
6. **Whiteout fallback:** Thrash, Uproar, recharge moves fail closed. **SOURCE** + **MODEL**
7. **No live two-emulator calc run**, for this or any title.
8. **Ghost-rival filter** in `server/adapters/gen3_expansion.py` (`7c349ab4`): in **Gen 2's `CODE_DIGEST`
   scope**; ping Gen 2 before landing. **SOURCE**
9. **`map_load` misses three returns** (new-game, cable-club, contest-hall). **SOURCE**
10. **Mystery Event gift** is a direct `gParties[5]` write; e-Reader only. **SOURCE**
11. **Shedinja from evolution** takes a party slot no kind publishes; inherited from the qualified
    titles. **SOURCE**
12. **(d) SYNTH preconditions** (§5) are disclosed in the manifests; recorded for explicitness, not a
    ruling item.

Not a limit: gym-interior trainer panels list no trainers, byte-identical to the qualified Emerald area
map. Rulings 38-40 are cited from `docs/gen3_resume.md`.

## 7 What the owner is asked (separate decisions)

1. **Sign XG3 only after the final cut.** Not yet: the cut has not been run and nothing is frozen. When
   it has, sign on `fc_SUMMARY_<CUT_SHA8>_exp.txt` (`<ROWS_PASSED>` of `<ROWS_TOTAL>`).
2. **Routing flip (ruling 39)** is a distinct yes, out of scope for this gate.
3. **Gen 2 ping before landing.** At `d78eb2b9`, `git diff --stat ea9c8a07..HEAD -- server lua/core
   lua/gen2 'data/games/gen2_*'` returns only `server/adapters/gen3_expansion.py` (+56/-4); re-check at
   the freeze.
4. **Landing** is squashed into about 6 logical groups (`d6102d23` is red at its own SHA: never land
   un-squashed), rebased over master `735dea38`.
5. **Push and tag** are separate approvals.
6. **Rulings still open:** the proposal list in §6 (items 1 to 11).

(Already decided 2026-10-02, not asked again: Rock Smash disposition, and accepting (a), (b), (c).)

**Shared-runtime blast radius.** `67493da5` changes `lua/gen3/client.lua` for the **vanilla Gen 3
titles too** (the cold-boot box rescan), so it is not vanilla-neutral and stales vanilla Gen 3 receipts.
Against `ea9c8a07`, `client.lua` has 4 commits / 5 hunks (+32/-7) and `signals.lua` has 2 commits. Per the
lane, this is **not Gen 2 digest scope** (the digest sees `server/adapters/gen3_expansion.py` only); the
digest definition was not re-read here, and I did not audit whether the other `client.lua` hunks are
no-ops on vanilla titles. The three Rock commits since `dc3e2a24` touch no `lua/gen3/*` or server file.

## 8 Reproduce

```bash
# generated-artifact checks (each is an XG3 SOURCE row)
python tools/gen_gen3_profile.py            --expansion 28877d73 --check
python tools/gen_gen3_write_checkpoint.py   --expansion 28877d73 --check
python tools/gen_gen3_engine_signals.py     --expansion 28877d73 --check
python tools/gen_area_map.py --game emerald --expansion 28877d73 --check
python tools/gen_gen3_exp_gifts.py         --check
python tools/verify_gen3_exp_wild.py       --check
python tools/gen3_shadow_negatives.py docs/gen3_exp/negatives_manifest.json

# preview the plan (launches nothing), then the whole test-only plan at a frozen cut
python tools/gen3_final_cut.py --cut <CUT_SHA> --title exp --dry-run
python tools/gen3_final_cut.py --cut <CUT_SHA> --title exp                  # serial
# or in 3 shards (one command per shard; writes a lane; not run here)
python tools/gen3_final_cut.py --cut <CUT_SHA> --title exp --shard 1/3
python tools/gen3_final_cut.py --cut <CUT_SHA> --title exp --shard 2/3
python tools/gen3_final_cut.py --cut <CUT_SHA> --title exp --shard 3/3
```

(`<CUT_SHA>` = the freeze SHA, `git rev-parse HEAD` at freeze. `--shard i/n`, `--dry-run`, `--lane`,
`--master` exist in the option parser as read; I ran none of them.) Provenance of every pin:
`data/gen3_exp_sources.lock.json` (source commit `e8bd1cd7…`, ROM sha1
`28877d733492299599f2b8fff50493109d72653c`, `symbols_sha256`
`ac24a47c0137ab9b2233ccf37bf0cabe8b6eb08b715aa7e87f15787507a1f01e`), restated in `engine_signals.json:source`.

## 9 Evidence index

`docs/gen3_emerald/XG3_PROGRESS_2026-10-01.md` (v3; authoritative for what passed and what is dev-only) ·
`XG3_GIFTS_SOURCE_2026-09-29.md` · `XG3_PC_SITES_2026-09-29.md` · `XG3_WILD_ROM_2026-09-29.md` ·
`XG3_FAINT_evidence_2026-09-27.md` · `probes/dev_2026-10-01/` · `probes/exp_*` (Rock:
`exp_rock_default_cd6b0648_*`, `exp_rock_normal_player_8dd64eaa_*`, `exp_parallel_exp_static_rock_gen3_*`) ·
`docs/gen3_exp/negatives_manifest.json` and `docs/gen3_exp/probes/pc_*` · `patch/build/exp_unit39_final.txt`
(gitignored) · `docs/gen3_emerald/probes/exp_{units,source_checks,plan}_1b050038_2026-10-01.txt` ·
`patch/build/exp_final_dev_row_table.json` (gitignored) · `git log master..HEAD` (88 commits at
`d78eb2b9`; re-read the log rather than trusting that count).

## 10 Claims not verified here

- The `1a735d4e` wave re-PASS of `static`, `static_run`, `grass`, `surf` (no log in tree).
- That the retained PASS-run trees were clean (no `dirty` string in the 19 logs; the lane says clean).
- The OMP source-only verification of the Rock limit beyond the expansion pin (vanilla pret/FRLG,
  Radical Red, OWE, DexNav, `force_*`); "also true of the qualified Emerald" (no Emerald run or policy
  re-derivation here).
- The 2026-10-02 owner rulings and exact limit text (from the task statement; the committed fixtures
  README and manifest carry the Rock text without the word "FINISHES").
- That OMP reviews found and fixed the faint oracle, Rock probe label and PC legs (transcripts not in the
  tree); that the new Gen 3 OMP peers are addressed by id.
- The 15 h serial / 5 h sharded cut estimate (887 m is a budget ceiling).
- (resolved: 953 passed at `d78eb2b9`.)
- `67493da5` red-first / revert-checked / 293 tests; whether other `client.lua` hunks are vanilla no-ops;
  that the Gen 2 digest excludes `lua/gen3/`.
- That `area_map_generated_check_exp`, `gift_census_check_exp` and `wild_rom_check_exp` pass at the tip (retained output is at
  `1b050038`).
- That 19 is the current `gen3_exp` duo count (taken from the row table and the earlier stubbed-plan
  derivation; not re-derived this time).
