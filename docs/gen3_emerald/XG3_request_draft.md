# XG3 request: expansion probe / observer / duos (draft, final refresh 2026-10-01)

- **Branch:** `claude/gen3-exp-xg3` (worktree `C:/slink-wt/exp-xg3`), off local master `ea9c8a07`.
  Local only: not pushed, not merged. **83 commits ahead of master at HEAD `462ed983` (82 at `1b050038`; the
  extra commit is docs-only); recount at the freeze: `<COMMITS_AHEAD>`.**
- **Plan:** `docs/gen3_emerald/PLAN.md:84` — the **X3** row ("Probe/observer/duos"), gate **XG3**.
- **Ledger:** `docs/gen3_emerald/REQUIREMENTS.md` expansion rows (source pin + compiler rows are
  **SIGNED XG0 2026-09-26**; `XG1`–`XG4` unsigned).
- **Status: NOT SIGNED. The final cut has NOT been run and is NOT frozen. No row is receipt-grade.**
  Nothing in this draft is a qualification claim on the owner's behalf. Figures that must come from
  the cut are placeholders (`<ROWS_TOTAL>`, `<ROWS_PASSED>`, `<COMMITS_AHEAD>`).
- **Freeze SHA = the tip commit recorded at freeze (`git rev-parse HEAD`).** It will include the docs
  commit, so this draft does not name one.

Tags: **SOURCE** (a file/commit/ROM disassembly in this tree) · **MODEL** (a unit suite or
independent review) · **DEV** (a real run that is not a receipt) · **PHYSICAL** (a real emulator run;
receipt-grade only at the frozen cut). A **dev run is not a receipt**: the harness's clean-cut gate
refuses a `+dirty` tree (`probes/dev_2026-10-01/whiteout2.log:38`). Where no run evidence exists the
row says `<<EVIDENCE?>>`.

## 0 Summary

The expansion reference build (`28877d73`) has **22 engine-site kinds bound and generated** (counted
from `titles.emerald_expansion_28877d73.artifacts.clean.sites` in
`data/games/gen3_exp/28877d73/engine_signals.json`), generated from the build's own `.sym`/`.map` and
reproducible by `--check` (**SOURCE**). Every site is also hooked at its `+0x02000000` ROM-mirror alias
(22 kinds / 44 hooks). The faint site is re-pinned (`eacb615b`).

Since the last draft (62 commits at `1a735d4e`), a **DEV wave** ran, the **three PC negative legs got
PHYSICAL observer receipts**, the plan grew to **30 rows**, and the **39-module unit set ran green
(940 passed)**. One row **fails and gates the cut: Rock Smash** (§2). XG3 is not signable yet; §3 lists
what is owed.

## 1 What XG3 signs

From `PLAN.md:84`, XG3 signs the **probe / observer / duo** layer on the expansion RC candidate:

- Every `gen3_exp` row of the final cut: source `--check` rows, the PC-negative receipt check, the
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
| `hatch` | SOURCE + MODEL | duo DEV (`egg_hatch_gen3`: fired once per side at `0811B35E`; row verdict not final) | `b5024ed7` console log, `exp_acq_hatch_*_qual_exp1_eacb615b.txt` |
| `battle_begin` | SOURCE + MODEL | duo DEV (`link_gen3`) | `link_gen3.log` |
| `battle_end` | SOURCE + MODEL | `<<EVIDENCE?>>` | — |
| `capture_wild` | SOURCE + MODEL | static/grass/Surf/Altering/fishing duo rows DEV; **Rock capture fired on both sides (FAIL at settle, below)** | `probes/exp_live_exp_static_*_dev.txt`, `exp_parallel_*_dev.txt` |
| `mon_given` | re-pinned `54ec247e` to `GiveScriptedMonToPlayer` `081C2E74`+0x68 (`081C2EDC`); mirror alias `05acb5ba`. `gift_gen3`, `egg_receive_gen3` PASS (PHYSICAL DEV; one signal per side, callback `0A1C2EDC`) | yes, duo DEV | `b5024ed7` logs |
| `evolve_species_store` | SOURCE + MODEL | `<<EVIDENCE?>>` | — |
| `faint` | SOURCE + MODEL; re-pinned `eacb615b` inside `SetValuesOnFaint` (hook `+0x82`, capture `+0x86`) | `faint_cmd_gen3` PASS DEV (`65e667e6`); `linked_faint_active_gen3` PASS DEV (`1a735d4e`) | `exp_live_faint_cmd_gen3_65e667e6_dev.txt`, `exp_parallel_linked_faint_active_gen3_1a735d4e_dev.txt` |
| `whiteout` | SOURCE + MODEL | `whiteout_gen3` PASS DEV (`1a735d4e`) | `exp_parallel_whiteout_gen3_1a735d4e_dev.txt` |
| `poison_faint`, `poison_hp_before`, `pc_move`, `trade_begin`, `trade_done`, `trade_evolve_species_store` | SOURCE + MODEL | `<<EVIDENCE?>>` | — |

**Duo results (PHYSICAL DEV, none at a clean cut):**

| Scenario | Both clients | PYDEC | SHA | Receipt |
|---|---|---|---|---|
| `link_gen3`, `boxsync_gen3`, `release_gen3` | PASS | PASS | original baseline | `probes/dev_2026-10-01/` |
| `faint_cmd_gen3` | PASS | PASS | `65e667e6` | `exp_live_faint_cmd_gen3_65e667e6_dev.txt` |
| `linked_faint_active_gen3` | PASS | PASS | `1a735d4e` | `exp_parallel_linked_faint_active_gen3_1a735d4e_dev.txt` |
| `whiteout_gen3` | PASS | PASS | `1a735d4e` | `exp_parallel_whiteout_gen3_1a735d4e_dev.txt` |
| `gift_gen3`, `egg_receive_gen3` | PASS | PASS | `b5024ed7` | `exp_acq_*_b5024ed7_dev_console.txt` |
| `exp_static_static`, `_static_run`, `_grass` | PASS | PASS | `65e667e6` | `exp_live_exp_static_*_65e667e6_dev.txt` |
| `exp_static_surf` | PASS | PASS | `b32454c5` | `exp_live_exp_static_surf_gen3_b32454c5_dev.txt` |
| `exp_static_altering0`, `exp_static_fish` (Old Rod, state-aware flow) | PASS | PASS | `1a735d4e` | `exp_parallel_exp_static_{altering0,fish}_gen3_1a735d4e_dev.txt` |
| `exp_static_altering1` | **FAIL** at `1a735d4e` (selector differs from pending fixture), then **PASS** (native + PYDEC + SAVE witnesses) | PASS | `db1ed073` | `exp_parallel_exp_static_altering1_gen3_db1ed073_dev.txt` |
| `exp_static_rock` | **FAIL** | FAIL | `901e888d` | `exp_parallel_exp_static_rock_gen3_901e888d_{,a_,b_}dev.txt` |

The lane reports Surf, static, static_run and grass also passed in the `1a735d4e` wave; **no
`1a735d4e` log for those four is in the tree (lane-reported, not verified here)**; the retained PASS
logs are the older SHAs above.

**`linked_faint_active_gen3` wording.** An **engine-resolved in-battle HP0, observed by the harness
HP-0 watcher**; **not a damage-KO claim and not test-forced** (log: `ACTIVE_KO inputs=0 hp_writes=0`,
`FORCED_HP0` emitted by the watcher). The scenario reaches the state through the client's `force_faint`
Perish commit (`writes=5`); the HP drop itself is not written. **OPEN:** the `ENGINE_FAINT_SITE`
marker is frame/active-slot bound, not key-bound (limit candidate (c)).

**Rock Smash (FAIL, gates the cut).** Proven on both sides: the SYNTH SFC32 state at the Rock entry
(runtime, not saved; native `Random32` counter 17 to 19), a native encounter, a slot-valid capture
(Geodude Lv 15, species 74, `Route 111`), and the server link. Afterwards the game sits in a bare
overworld with `sGlobalScriptContextStatus` = 1 (WAITING) and no text box (I viewed the screenshot),
until the 1800-frame budget ends. Cause (**SOURCE**, expansion `e8bd1cd7`): `EventScript_SmashRock`
parks at `waitstate` (`data/scripts/field_move_scripts.inc:91`) and `Task_ReturnToFieldNoScript`
(`src/field_screen_effect.c:492-500`) never calls `ScriptContext_Enable`; the overworld checkpoint
requires status 2 and refuses. Probably native/benign and also true of the qualified Emerald title
(**lane-reported, not verified here**; the vanilla pret comparison at `field_screen_effect.c:446-454`
was not read). Settle, SAVE and PYDEC are **not qualified**. Limit candidate (e): the owner chooses
fix-before-signing or a named limit.

**Observer totals, the two earlier positive-leg runs:** 22 registered, 0 rejected, 0 dropped, no handler
error; **PRE-MIRROR** logs (current runs register 22 kinds / 44 hooks). **7 fired kinds** (`map_load`,
`pc_deposit`, `pc_box_place`, `pc_withdraw`, `pc_release_begin`, `pc_release`, `save`) plus the
`frame_control` STATUS counter. **PHYSICAL DEV.**

**Pins (SOURCE):** hatch `AddHatchedMonToParty` `0811B284`, capture `+0xDA`, hatchling in **R4**
(`d6102d23`, independent adversarial review ACCEPT, MODEL). Faint `SetValuesOnFaint` `080df4a4`, size
`0xD0`, two BL callers by ROM-wide scan (`eacb615b`, `tests/unit/test_gen3_exp_faint_pin.py`, MODEL).

**PC negative legs (PHYSICAL DEV, single-cart observer).** Receipts in `docs/gen3_exp/probes/`, bound
by `docs/gen3_exp/negatives_manifest.json` and plan row `shadow_negatives_exp`. The manifest scope:
raw observer windows; **client reporting not qualified**.

| Leg | Run | Window | Observer result |
|---|---|---|---|
| bypass (moved-mon release) | `048db86b` | 5813 to 6991 | held-mon release removes the target from every box, party unchanged; `pc_release_begin` **absent**, `pc_release` **unpaired** (frame 6609) |
| cancel | `048db86b` | 6991 to 8667 | release **absent**; a later real YES release is valid (frame 9782). Uses `exp_pc_negative_chain_synth` |
| full box | `ccfa94e0` | 1602 to 2168 | `MSG_BOX_IS_FULL`; `pc_deposit` **absent** in the window; positive sibling deposit into box 1 follows |

`exp_pc_negative_chain_synth` is a **SYNTH** seed with one extra usable boxed record, because the pin's
release precondition refuses a release below 3 usable mons (chain 5, 4, 3, 3, 2). Only native
CONTINUE/SAVE is qualified for the seed. The **client half** (that the client reports no release for
the bypass) is a **DUO claim, not proven**. `shadow_negatives_exp`'s checker was **not run by me**; Codex's retained source-only output at `1b050038` is `SUMMARY PASS receipts=3 checks=15 passed=15 failed=0`.

## 3 Rows still to run at the frozen cut

`tools/gen3_final_cut.py --title exp` (**SOURCE**, read, not run). Every row RUNs and no historical
qualification is carried. Runtime rows log the server's `--test-only-route emerald_expansion_28877d73`.

**`build_plan_exp` yields 30 rows = 7 SOURCE (incl. `shadow_negatives_exp`) + 1 unit (39 modules) + 19
duo + 3 ZIP**, recomputed by calling the function with git stubbed (nothing run). The count is derived
from the registry, so **recompute at the cut: `<ROWS_TOTAL>` rows, `<ROWS_PASSED>` passed.**

- **7 SOURCE rows:** `profile_generated_check_exp`, `write_checkpoint_generated_check_exp`,
  `engine_signals_generated_check_exp`, `area_map_generated_check_exp`, `gift_census_check_exp`,
  `wild_rom_check_exp`, `shadow_negatives_exp`.
- **1 MODEL row:** `unit_exp` over `EXPANSION_UNIT_FILES` (39 modules). **Dev run from clean
  `1b050038`: 940 passed, 0 skips, exit 0, 313 s** (`patch/build/exp_unit39_final.txt`). Earlier
  37-module run: 810 passed. This is a dev run, not the row.
- **19 duo rows:** every `e2e_duo.SCENARIOS` name where `scenario_applies(s, "gen3_exp")`.
- **3 ZIP rows:** `exp_zip_build`, `exp_zip_check`, `zip_boot_exp`.
- Summary artifact: `fc_SUMMARY_<CUT_SHA8>_exp.txt`.
- **Time:** a full cut needs about 15 h serial, or about 5 h in 3 shards (lane-reported; the retained plan dump's summed budget ceiling is 887 m, about 14.8 h, a ceiling and not a measurement).
- **Source-only dry run at `1b050038` (DEV, retained in `462ed983`, read, not run by me):** the six generated/census checks `EXIT 0`; the PC-negative checker `SUMMARY PASS receipts=3 checks=15`; the plan dump `rows=30, RUN 30 / CACHED 0 / CARRY 0`. Headers: `no final-cut/runtime qualification`.

The SYNTH fixture registry (`tests/fixtures/gen3/README.md`; **38** `exp_*.sav` fixtures, generator raw
pins, 420-record full-box derivation, 30-record `box0-full` seed, `exp_pc_negative_chain_synth`) is
**SOURCE + MODEL**, disclosed as SYNTH in the `exp_*_manifest.json` files. The native catch EV oracle
(`906b34f2`) is **MODEL**.

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

## 6 Known limits proposed for the owner's ruling

All are proposals; none is signed.

1. **Routing stays refused** until the owner routes the expansion (ruling 39). **SOURCE**
2. **shinyModifier** (ruling 38) stays a known limit. **SOURCE**
3. **Unmapped calc data:** 6 abilities and 54 items; 1 of 1825 trainer slots (Smoke Ball). **SOURCE**
4. **Altering Cave set-0 scope:** display-only. Altering 0 and 1 rows both PASS DEV.
5. **Wynaut egg is not fixed-species.** **SOURCE**
6. **Whiteout fallback:** Thrash, Uproar, recharge moves fail closed. **SOURCE** + **MODEL**
7. **No live two-emulator calc run**, for this or any title.
8. **Ghost-rival filter** in `server/adapters/gen3_expansion.py` (`7c349ab4`): in **Gen 2's `CODE_DIGEST`
   scope**; ping Gen 2 before landing. **SOURCE**
9. **`map_load` misses three returns** (new-game, cable-club, contest-hall). **SOURCE**
10. **Mystery Event gift** is a direct `gParties[5]` write; e-Reader only. **SOURCE**
11. **Shedinja from evolution** takes a party slot no kind publishes; inherited from the qualified
    titles. **SOURCE**

New candidates:

12. **(a) Route 111 Mirage Tower pulse task** `UpdateMirageTowerPulseBlend` is not in the overworld
    checkpoint allow-list of either the expansion or the qualified Emerald (fail-closed; hello and
    writes withheld). The Rock seeds use a disclosed SYNTH Mirage-resolved state. The symbol appears
    nowhere under `data/games/`; the Emerald half is **lane-reported**. **SOURCE + DEV**
    (`probes/exp_rock_hello_*_fail.txt`)
13. **(b) A held mon released through the PC moved-mon path** is discarded with no `pc_release_begin`
    (observer: PHYSICAL DEV, three windows above). The client half is a **duo claim, not proven**.
14. **(c) `ENGINE_FAINT_SITE` marker is not key-bound** (slot/frame bound). **MODEL**, OPEN.
15. **(d) SYNTH preconditions** (§5) are disclosed in the manifests; recorded for explicitness, not as a gap.
16. **(e) Rock Smash leaves `sGlobalScriptContextStatus` at 1** after the native capture return, so the
    overworld checkpoint refuses; probably native/benign; settle/SAVE/PYDEC not qualified. **GATES THE
    CUT.** **SOURCE** + **DEV**

Not a limit: gym-interior trainer panels list no trainers, byte-identical to the qualified Emerald area
map. Rulings 38-40 are cited from `docs/gen3_resume.md`.

## 7 What the owner is asked (separate decisions)

1. **Sign XG3 only after the final cut.** Not yet: the cut has not been run and nothing is frozen. When
   it has, sign on `fc_SUMMARY_<CUT_SHA8>_exp.txt` (`<ROWS_PASSED>` of `<ROWS_TOTAL>`).
2. **Rock Smash:** fix before signing, or rule a named limit (e).
3. **Routing flip (ruling 39)** is a distinct yes, out of scope for this gate.
4. **Push and tag** are separate approvals.
5. **Named limits:** rule on §6 items 3-6 and candidates (a) to (e), plus the earlier list, or record
   them as signed limits.
6. **Landing** is squashed into about 6 logical groups (`d6102d23` is red at its own SHA: never land
   un-squashed).
7. **Gen 2 ping before landing.** At HEAD `462ed983`, `git diff --stat ea9c8a07..HEAD -- server lua/core
   lua/gen2 'data/games/gen2_*'` returns only `server/adapters/gen3_expansion.py` (+56/-4); re-check at
   the freeze.

**Shared-runtime blast radius (corrected).** Earlier wording said "two vanilla-neutral hunks"; that is
wrong. `67493da5` changes `lua/gen3/client.lua` for the **vanilla Gen 3 titles too** (the cold-boot box
rescan), so it is not vanilla-neutral and stales vanilla Gen 3 receipts. Against master, `client.lua`
has 4 commits / 5 hunks (+32/-7) and `signals.lua` has 2 commits. Per the lane, this is **not Gen 2
digest scope** (the digest sees `server/adapters/gen3_expansion.py` only); the digest definition was
not re-read here, and I did not audit whether the other `client.lua` hunks are no-ops on vanilla titles.

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

# the whole test-only plan at a frozen cut (writes a lane; not run here)
python tools/gen3_final_cut.py --cut <CUT_SHA> --title exp
```

(`<CUT_SHA>` = the freeze SHA, `git rev-parse HEAD` at freeze.) Provenance of every pin:
`data/gen3_exp_sources.lock.json` (source commit `e8bd1cd7…`, ROM sha1
`28877d733492299599f2b8fff50493109d72653c`, `symbols_sha256`
`ac24a47c0137ab9b2233ccf37bf0cabe8b6eb08b715aa7e87f15787507a1f01e`), restated in `engine_signals.json:source`.

## 9 Evidence index

`docs/gen3_emerald/XG3_PROGRESS_2026-10-01.md` (authoritative for what passed and what is dev-only) ·
`XG3_GIFTS_SOURCE_2026-09-29.md` · `XG3_PC_SITES_2026-09-29.md` · `XG3_WILD_ROM_2026-09-29.md` ·
`XG3_FAINT_evidence_2026-09-27.md` · `probes/dev_2026-10-01/` · `probes/exp_*` ·
`docs/gen3_exp/negatives_manifest.json` and `docs/gen3_exp/probes/pc_*` · `patch/build/exp_unit39_final.txt` ·
`docs/gen3_emerald/probes/exp_{units,source_checks,plan}_1b050038_2026-10-01.txt` (source-only dry-run records, `462ed983`) · `git log master..HEAD` (83 commits at `462ed983`; re-read the log rather than trusting that count).

## 10 Claims not verified here

- The `1a735d4e` wave re-PASS of `static`, `static_run`, `grass`, `surf` (no log in tree).
- That the wave tree was clean (no `dirty` string in the logs; the lane says clean).
- "Probably native/benign" for Rock (vanilla pret and qualified Emerald not read or run).
- The 15 h serial / 5 h sharded cut estimate (887 m is a budget ceiling).
- `67493da5` red-first / revert-checked / 293 tests; whether other `client.lua` hunks are vanilla no-ops.
- That the Gen 2 digest excludes `lua/gen3/`.
- That `shadow_negatives_exp` passes inside a cut (I read Codex's retained source-only output, not a run of mine).
- The Mirage allow-list claim for the qualified Emerald.
