# XG3 request: expansion probe / observer / duos (draft, 2026-10-01)

- **Branch:** `claude/gen3-exp-xg3` (worktree `C:/slink-wt/exp-xg3`), off local master `ea9c8a07`.
  Local only: not pushed, not merged, not committed here.
- **Plan:** `docs/gen3_emerald/PLAN.md:84` — the **X3** row ("Probe/observer/duos"), gate **XG3**.
- **Ledger:** `docs/gen3_emerald/REQUIREMENTS.md` expansion rows (source pin + compiler rows are
  **SIGNED XG0 2026-09-26**; `XG1`–`XG4` unsigned).
- **Status: NOT SIGNED.** Nothing in this draft is a qualification claim on the owner's behalf.

Tags: **S** source (a file/commit in this tree) · **M** model (a unit suite or independent review) ·
**P** physical (a receipt from a real run). A **dev run is not a receipt**: the harness's
clean-cut gate refuses a `+dirty` tree (`probes/dev_2026-10-01/whiteout2.log:38`). Every dev result
below is labelled **DEV (not receipt-grade)**. Where no receipt exists the row says `<<EVIDENCE?>>`.

## 0 Summary

The expansion reference build (`28877d73`) has **22 engine-site kinds bound and generated**, all
generated from the build's own `.sym`/`.map` and reproducible by `--check` (**S**). Four duo
scenarios pass end to end and a single-cart observer has fired 8 kinds across two dev runs (**P**,
but **DEV** — both runs predate a clean cut). **No receipt-grade final cut has been run**, so XG3
is not signable yet: §3 lists exactly what is still owed.

## 1 What XG3 signs

From `PLAN.md:84`, XG3 signs the **probe / observer / duo** layer on the expansion RC candidate:

- Every `gen3_exp` row of the final cut: source `--check` rows, the expansion unit gate, the
  test-only duo rows, and the ZIP build + boot (`tools/gen3_final_cut.py --title exp`).
- `gen3_title_syms.lua` gets **generated** per-build entries from the build's `.sym` (no hand column).
- P+H re-derived for `struct Volatiles` for this build.

**XG3 does NOT sign:** admission/routing (still refused in production, ruling 39), XG1's data
extraction, XG2's record layout, or the master landing.

## 2 Claim table by engine-site kind (22)

All 22 kinds carry `PINNED_SOURCE_ONLY` in `data/games/gen3_exp/28877d73/engine_signals.json`
(`inventory`, 22 entries); the pack's `live_verified` is `false`. **S** = symbol + anchor pinned
from the build's `.sym`/`.map`, reproducible by `engine_signals_generated_check_exp`.

| Kind | Site status | Fired in a run | Evidence |
|---|---|---|---|
| `frame_control` | S + M | yes (STATUS counter) | `pclegs1.log:39` |
| `map_load` | S | yes, run 1 | `pclegs1.log` SHADOW |
| `pc_deposit` | S | yes, run 1 (f.1522) | `pclegs1.log` SHADOW |
| `pc_box_place` | S | yes, runs 1+2 (f.1522 / f.3509) | `pclegs1.log`, `pclegs2.log` |
| `pc_withdraw` | S | yes, run 1 (f.2494) | `pclegs1.log` SHADOW |
| `pc_release_begin` | S | yes, run 2 (f.4650) | `pclegs2.log:44` |
| `pc_release` | S | yes, run 2 (f.4650, same frame) | `pclegs2.log:45` |
| `save` | S | yes, run 2 (f.5699); counter 2→3 | `shadow.log`, `pclegs2.log:32` |
| `hatch` | S + M | `<<EVIDENCE?>>` no observer run | `d6102d23` |
| `battle_begin` | S + M | duo only (`link_gen3`) | `link_gen3.log` |
| `battle_end` | S + M | `<<EVIDENCE?>>` | — |
| `capture_wild` | S + M | `<<EVIDENCE?>>` | — |
| `mon_given` | **superseded**: `54ec247e` re-pinned it to `GiveScriptedMonToPlayer` `081C2E74`+0x68 (`081C2EDC`), the routine script `givemon`/`createmon` actually reach; `05acb5ba` then also hooked every site at `+0x02000000` after the 0x0A ROM mirror made 0x08-only hooks blind. `gift_gen3` and `egg_receive_gen3` PASSED live (PHYSICAL DEV; `b5024ed7` report: one signal per side, callback `0A1C2EDC`, no double fire). | `54ec247e`, `05acb5ba`, `b5024ed7` |
| `evolve_species_store` | S + M | `<<EVIDENCE?>>` | — |
| `faint` | S + M | duo (`faint_cmd_gen3`) | `faint_cmd_gen3.log` |
| `whiteout` | S + M | duo **DEV** (PYDEC FAIL) | `whiteout2.log` |
| `poison_faint` | S + M | `<<EVIDENCE?>>` | — |
| `poison_hp_before` | S + M | `<<EVIDENCE?>>` | — |
| `pc_move` | S + M | `<<EVIDENCE?>>` | — |
| `trade_begin` | S + M | `<<EVIDENCE?>>` | — |
| `trade_done` | S + M | `<<EVIDENCE?>>` | — |
| `trade_evolve_species_store` | S + M | `<<EVIDENCE?>>` | — |

Observer totals, both retained runs: **22 registered, 0 rejected, 0 dropped, no handler error** — these logs are **PRE-MIRROR**. Current runs register **22 kinds / 44 hooks** (each site also hooked at `+0x02000000` since `05acb5ba`). **7 fired kinds** across the two runs plus the `frame_control` STATUS counter.
(`pclegs1.log:37`, `pclegs2.log:40`, `gen3_scripted_play_emerald_result.shadow.log`). **P DEV.**
Note the retained `…_result.shadow.log` is **run 2 only**; deposit/withdraw/map_load survive solely
as text in `pclegs1.log`.

**Hatch pin (S):** `AddHatchedMonToParty` `0811B284`, size `0xF4`, capture `+0xDA`, anchor
`A4F05FFF0AB070BC01BC0047C046641B` at rom_offset `0x0011B35A`, unique in the ROM; the hatchling
pointer is **R4** in this build, not R5. Commit `d6102d23`; verified by independent adversarial
review (**M**).

**Duo results (P, DEV — none at a clean cut):**

| Scenario | Both clients | PYDEC | Receipt |
|---|---|---|---|
| `link_gen3` | PASS | PASS | `link_gen3.log:33-38` |
| `faint_cmd_gen3` | PASS | PASS | `faint_cmd_gen3.log:41-46` |
| `boxsync_gen3` | PASS | PASS | `boxsync_gen3.log:41-46` |
| `release_gen3` | PASS | PASS | `rel1.log:31-36` |
| `whiteout_gen3` | PASS | **FAIL** `+dirty` | `whiteout2.log:33,38` |
| `linked_faint_active_gen3` | PASS | **FAIL** `+dirty` | `lfa2.log:29,34` |

The last two are **DEV (not receipt-grade)**: both clients reached `RESULT: PASS` but the harness
refused them at the clean-cut gate. They must pass again at the frozen cut. `summary.txt` is the
first baseline batch only (predates `release_gen3` and the reruns).

**PC legs (P DEV):** run 1 passed `emerald_enter_pc`, `emerald_pc_deposit`, `emerald_pc_withdraw`,
then **FAILED** at `emerald_pc_box_place` (`pclegs1.log:33`, fixed in `f4763732`); run 2 resumed at
that leg and reached `emerald_pc_release` and `emerald_save_town` (`pclegs2.log:36`).

## 3 Rows still to run at the frozen cut

`tools/gen3_final_cut.py --title exp` (S, read not run — `tools/gen3_final_cut.py:536-566`). It
builds, per expansion row, **no** dependency: every row RUNs and no historical qualification is
carried (`:564`). Runtime rows must log the server's `--test-only-route
emerald_expansion_28877d73`.

- **6 SOURCE rows:** `profile_generated_check_exp`, `write_checkpoint_generated_check_exp`,
  `engine_signals_generated_check_exp`, `area_map_generated_check_exp`, `gift_census_check_exp`,
  `wild_rom_check_exp` (`:548-555`).
- **1 MODEL row:** `unit_exp` over `EXPANSION_UNIT_FILES` (`:557`).
- **Duo rows:** every `e2e_duo.SCENARIOS` name where `scenario_applies(s, "gen3_exp")` (`:541-544`);
  the set is pinned in `tests/unit/test_e2e_duo_scenario_selection.py`.
- **ZIP rows:** `zip_rows(cut, lane, "exp")` — build + boot (`:559`).
- Summary artifact: `fc_SUMMARY_<cut8>_exp.txt`.

**In progress, not yet receipts:** `docs/gen3_emerald/probes/exp_acq_*_qual_fd673a1c.txt` (10 files,
`SYNTH_QUALIFY PASS`, `case=` gift / choice_gift / egg_receive / gift_box / hatch, sides a+b). Their
own header reads `source=… SOURCE/MODEL setup + PHYSICAL native resave; uncommitted harness`, so
they are **not** yet receipt-grade. `<<EVIDENCE?>>` for the acquisition / static / wild physical
rows themselves, and for wild-method sampling.

## 4 Calc and panels

- **Six-town trainer fix** (`3376e179`, **S** + **M**): Rustboro/Mauville/Fortree and the four
  other towns' trainers and gym leaders now file under their town; previously Roxanne was under
  `route_104`, Wattson `route_110`, Winona `route_119`, which rendered those panels empty.
- **Browser mock check (coordinator session; numbers NOT retained in-repo):** `/calc/normal.html`
  Gen 9 calc resolved a SYNTH Mudkip and Roxanne's Nosepass and returned
  `"Lvl 14 Mudkip Water Gun vs. Lvl 15 Nosepass: 12-14 (32.4 - 37.8%)"`; dashboard preview showed
  move damage rows; Upcoming Key Trainers carried Roxanne/Norman with four rematches each;
  `?prep=Leader%20Roxanne` opened the Prep tab. This is a mock-browser check in the shape of the
  other titles' calc evidence (`docs/calc_multigen/HANDOFF.md`); **no title has had a live
  two-emulator calc run**, and no expansion-specific calc receipt exists. `<<EVIDENCE?>>`
- **Gift areas** (`9fc060ed` → `bfc00eb8`, **S** + **M**): `gift_areas` was `[]`, which the client
  reads as "every area is a gift" (`lua/gen3/client.lua:121-137`), so no `no_catch` could form on
  the expansion. Five ids, re-derived from the source census: `lavaridge_town`,
  `littleroot_town_professor_birchs_lab`, `mossdeep_city_stevens_house`,
  `route119_weather_institute_2f`, `rustboro_city_devon_corp_2f`. The generator fails closed on an
  unaccounted gift kind, a wild-area gift, an unmapped gift map, or a mapless gift row that is not
  the Route 101 starter. `7c349ab4` applied the M2/M3 review items.

## 5 Known limits proposed for the owner's ruling

1. **Routing stays refused** until the owner routes the expansion (ruling 39). Every live run used
   `--test-only-route emerald_expansion_28877d73`. **S**
2. **shinyModifier** (ruling 38) stays a known limit — not covered by XG3. **S**
3. **Unmapped calc data:** 6 abilities and 54 items have no mapping
   (`tools/gen_expansion_calc_names.py` `EXPECTED_UNRESOLVED`); the user sees a default ability and
   no item. Of 1825 trainer party slots, 1 is affected (Smoke ball). **S**, proposed as a named
   limit.
4. **Altering Cave set-0 scope:** the wild ROM scan covers its declared scope only; the set-0
   variants are outside it. `<<EVIDENCE?>>` for the set-0 rows.
5. **Wynaut egg is not fixed-species:** it hatches from a breeding roll, so it cannot use the
   fixed-species gift bypass; it is published at hatch in `gift_daycare` instead. **S**
6. **Whiteout fallback:** on a lead knowing Thrash, Uproar or a recharge move the whiteout
   scenario **cannot complete** — those moves pass the no-damage gate and then fail closed
   (`0d067d6f`, `5634a0b0`). **S** + **M**.
7. **No live two-emulator calc run**, for this or any title — a shared gap, not expansion
   specific. **S** Separately, this title's own calc evidence is a coordinator mock-browser check
   that is **not retained in-repo**, so it is not citable; see XG3_PROGRESS "Live results".
8. **Ghost-rival filter:** the expansion adapter filters the rival by player gender
   (`server/adapters/gen3_expansion.py`, `7c349ab4`); this file is in **Gen 2's `CODE_DIGEST`
   scope** — ping the Gen 2 lane before landing. **S**
9. **`faint` misses the C fallback path.** `FAINT_BLOCK_FAINT_TARGET`
   (`battle_move_resolution.c:3730`) calls `SetValuesOnFaint` directly, so a faint taken through
   it is never published and a linked mon would not be killed. A single re-pin inside
   `SetValuesOnFaint` (+0x86) covers both callers; designed and verified by disassembly, **not yet
   applied**. **M**
10. **`map_load` misses three returns.** New-game, cable-club and contest-hall returns each set
    `CB2_Overworld` themselves and never reach `CB2_LoadMap2` (`overworld.c:1949`, `:2013`,
    `:2021`), so no area check runs after them. Either a second site or this named limit. **S**
11. **Mystery Event gift** is a direct `gParties[5]` write (`mystery_event_script.c:338`) that
    bypasses every `Give*` routine, so it would publish as a plain capture in the current area.
    e-Reader only; no physical run. **S**
12. **Shedinja from evolution** takes a party slot no kind publishes. **Inherited, not
    expansion-specific**: `checkpoint_unreached_states.md:69` and `engine_sites.md:232` list it
    for the qualified titles too, so this is a shared coverage gap, not a new risk. **S**

Not a limit, recorded so it is not re-litigated: gym-interior trainer panels list no trainers,
which is byte-identical to the qualified Emerald area map (ruling 40 files leaders under their
town). Rulings 38-40 are cited from `docs/gen3_resume.md`.

## 6 What the owner is asked

1. **Do not sign XG3 yet.** The final cut at a frozen commit has not been run; §3 is what is owed.
2. When it has: sign **XG3** on the resulting `fc_SUMMARY_<cut8>_exp.txt`.
3. **Routing is a separate decision.** The production routing flip needs its own explicit owner
   yes and is out of scope for this gate.
4. A **Gen 2 ping is required before landing**, because `server/adapters/gen3_expansion.py` is in
   Gen 2's `CODE_DIGEST` scope on this branch — the only file that is.
5. Rule on §5 items 3–6, or record them as signed limits.

## 7 Reproduce

```bash
# generated-artifact checks (each is an XG3 SOURCE row)
python tools/gen_gen3_profile.py            --expansion 28877d73 --check
python tools/gen_gen3_write_checkpoint.py   --expansion 28877d73 --check
python tools/gen_gen3_engine_signals.py     --expansion 28877d73 --check
python tools/gen_area_map.py --game emerald --expansion 28877d73 --check
python tools/gen_gen3_exp_gifts.py         --check
python tools/verify_gen3_exp_wild.py       --check

# the whole test-only plan at a frozen cut (writes a lane; not run here)
python tools/gen3_final_cut.py --cut <sha> --title exp
```

Provenance of every pin: `data/gen3_exp_sources.lock.json` (source commit `e8bd1cd7…`, ROM sha1
`28877d733492299599f2b8fff50493109d72653c`, `symbols_sha256`
`ac24a47c0137ab9b2233ccf37bf0cabe8b6eb08b715aa7e87f15787507a1f01e`), restated in
`engine_signals.json:source`.

## 8 Evidence index

`docs/gen3_emerald/XG3_PROGRESS_2026-10-01.md` (authoritative for what passed and what is dev-only)
· `XG3_GIFTS_SOURCE_2026-09-29.md` · `XG3_PC_SITES_2026-09-29.md` · `XG3_WILD_ROM_2026-09-29.md` ·
`XG3_FAINT_evidence_2026-09-27.md` · `probes/dev_2026-10-01/` · `git log master..HEAD`
(16 commits at `e00b439f` when this draft was written; the branch is moving, so re-read the log
rather than trusting that count).
