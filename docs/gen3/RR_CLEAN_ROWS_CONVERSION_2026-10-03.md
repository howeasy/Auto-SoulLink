# RR clean rows: conversion to refusal proofs (2026-10-03)

Patch-first (owner 2026-10-02): the SLink companion patch is REQUIRED for Gen 3 FR/LG/E/RR. A clean
(unpatched) Radical Red ROM is refused at launch: `lua/gen3/entry.lua` `Entry.admit_routed` returns
`this radical_red cartridge needs the SLink companion patch; prepare it through the Manager or /patcher`
(called by `lua/slink.lua` and `lua/gen3/run.lua`, the duo harness entry), and the server refuses on
companion_abi evidence (`server/server.py` `_companion_refusal`). Any live row that booted a clean RR as
a WORKING client is therefore invalid. Each such row is converted into a refusal proof or retired.

Nothing here was run live (no emulator). The RR final cut `aab6fb32` (41/41 PASS,
[RR_COMPLETION_2026-09-30.md](RR_COMPLETION_2026-09-30.md)) was recorded with the old rows; its receipts
stay as history. The RR plan is derived from `tools/e2e_duo.py` SCENARIOS and is now **39 rows**.

| Old item | Now |
|---|---|
| `lua/tests/test_mailbox_absent.lua` (clean ROM gate) | KEPT and extended. Its native-absent checks are unchanged; new check `the launcher refuses the clean RR: the companion patch is required` asserts `Entry.admit_routed` (via `t.routed()` in `lua/tests/gen3_gatelib.lua`, same args as `t.boot`) returns nil with a reason containing `needs the SLink companion patch`. |
| `test_gen3_gatelib.py::test_absent_gate_passes_on_clean_and_fails_on_a_beacon` | Asserts PASS on clean plus the new check line, FAIL on a beacon. New `test_absent_gate_fails_if_the_launcher_would_admit_the_clean_rr` (a gate copy whose `t.routed()` says admitted must FAIL). The dead `_rr_clean_is_production()` / "non-production cartridge" branch is removed; the `production:false` flip is NOT done. |
| `native_absent_gen3` (A companion, B clean; valid apply_prepare to both) | CONVERTED into the single duo refusal-proof row and RENAMED `clean_rr_refused_gen3` (2026-10-03 review: `gen3_final_cut.py --resume` reuses a receipt by row NAME, so keeping the id would have shown the old clean-client PASS as this row's PASS; the old id is gone from SCENARIOS and every plan, its scenario module is `lua/tests/duo/scenario_gen3_clean_rr_refused.lua`). Scenario field `expect_refused: ("b",)`; `no_save: ("a","b")`. B: the driver (`launch_verdict` in `lua/tests/duo/duo_gen3_main.lua`) passes B only when `run.lua` logged `[SLink-gen3] refused: ... needs the SLink companion patch` and built no client; it logs `REFUSED_AT_LAUNCH` and `WRITES 0`. The oracle requires that line and forbids MYKEY, any TX/RX, any `write`, any admission line, any save dump. A: boots and connects alone, `PROBE_SETTLED writes=0 rx=0` after GO, none of the partner-driven commands; the server shows b never connected and no link. Orchestration waits for A's MYKEY and hello and B's refusal line, then releases A. |
| `linked_faint_active_clean_gen3` (rom_kind a companion, b clean) | RETIRED. Its purpose (the P+H link/faint mechanics on a clean cartridge) has no meaning when the clean RR cannot run a client; its refusal meaning is the B half of `clean_rr_refused_gen3`. Removed from SCENARIOS, the orchestrate/oracle aliases, the unit tests and the e2e lists. |
| `faint_cmd_clean_gen3` (rom_kind a companion, b clean) | RETIRED, same reason. Its `_gen3_rom_provenance_problems` helper and `assert_faint_cmd_clean_gen3_saved` wrapper had no other user and are removed. |
| native_absent A half: companion answers a valid `apply_prepare` after the native pre-save (PRESAVE_COUNTER, NATIVE_PREPARED) | RETIRED from this row (A is now passive). The native pre-save path is covered by the durable-trade rows (`trade_gen3`, `trade_decline_gen3`, `trade_reset_*_gen3`) and `test_live_tradescene.lua`. |
| `GEN3_CLEAN_RR_ROM`, `rom_kind`, `UNPINNED_INPUTS` "Pokemon - Radical Red.gba" | KEPT: still needed by the refusal-proof side and the absent gate. |
| engine_signals `production` | Documented (generator comment, `tools/gen_gen3_engine_signals.py`): it does not decide admission of clean companion titles; the companion-required rule does. |

## Live commands to run later

```
# 1. the clean-ROM gate (needs the unpatched RR dump; spawns EmuHawk)
SLINK_LIVE=1 python -m pytest tests/live/test_lua_gates.py -q -p no:randomly -k mailbox_absent

# 2. the duo refusal proof (A companion + B clean RR; needs both RR dumps and the rr_battle2 fixtures)
python tools/e2e_duo.py --game gen3_rr --scenario clean_rr_refused_gen3

# 3. the RR final cut row set (39 rows), or just the two rows above through the plan
python tools/gen3_final_cut.py --cut <sha> --title rr --lane <clean lane> --master master
```

Expected receipt for B: `[client] [SLink-gen3] refused: this radical_red cartridge needs the SLink
companion patch; ...`, `REFUSED_AT_LAUNCH`, `WRITES 0`, `RESULT: PASS (refused at launch ...)`. If A's
settle window shows a write or a command on the first live run (the link panel may still be talking),
widen the 120-frame pre-baseline wait in `lua/tests/duo/scenario_gen3_clean_rr_refused.lua`.

## Second pass (2026-10-03): every other clean / randomized-clean leg

The same rule reaches further than the RR rows. `Entry.admit_routed` refuses kind `clean` AND `rand` for every
`companion_required` pack (gen3_frlg, gen3_rr, gen3_emerald), and `launch_verdict` ends any side that built no client, so
a clean or randomized-clean leg dies at LAUNCH instead of producing the server-side verdict it was written to observe.

| Row | Side | Cartridge (was) | Expectation (was) | Decision |
|---|---|---|---|---|
| `admit_randomized_frlg` / `_emerald` pair | a, b | randomized clean (`rand`) | both admitted, contract matches | RE-POINTED: randomized COMPANION carts (`overlay_randomized`: the randomized ROM plus the published companion overlay; hello kind stays `rand`, plus `companion_abi`) |
| same, `wrong_rom` | a | other player's randomized clean | server rejects, "not the cartridge built for player a" | RE-POINTED (companion overlay) |
| same, `rules_changed` | a | widest-settings randomized clean | server rejects the randomized evolutions | RE-POINTED (companion overlay) |
| same, `mixed_kind` | b | CLEAN | server rejects "Mixed artifact kinds ... 'clean' ... 'rand'" | RE-POINTED: the plain COMPANION build (hello kind `companion`); server still rejects "Mixed artifact kinds" naming `'rand'` and `'companion'` |
| same, new `clean_refused` | b | CLEAN | (none: the clean cartridge never reached a verdict) | NEW launch-refusal proof, reusing `expect_refused`: the clean B must show the companion-patch refusal, no hello/MYKEY/write/save, and the server never sees it (`_observe_gen3_rand_refused`; the admission oracle needs this leg) |
| same, `equivalent_pair` | a, b | clean-equivalent unknown-hash randomized clean + CLEAN partner | declared `rand`, effective `clean`, both admitted | RE-POINTED: the companion build with one unused 0xFF padding byte outside every protected span changed (`gen3_rand_equivalent_rom`), plus the plain companion partner |
| `link_gen3_rand`, `trainer_panel_gen3_rand` | a, b | randomized clean pair | link / nearby-trainer panel on each side's OWN randomized tables | RE-POINTED (companion overlay pair) |
| every row of the clean `--title frlg` / `--title emerald` plans (FR/LG/E duos, bootchecks, `zip_boot_firered`, `zip_boot_emerald`) | both | CLEAN FR/LG/E | clean-client behaviour | NOT CONVERTIBLE (their meaning is a clean client). The live successor is `--title frlgc` (companion twins). `run_pass` (reached through `main`) now refuses these titles by name unless `--dry-run/--list/--merge-summary` (F1); the duo harness refuses a clean launch up front (`_gen3_launch_refusal_problems`); their clean receipts are history |
| `zip_boot_firered`, `zip_boot_emerald` | a | CLEAN, shipped client | identity line + TCP connect + hello | CONVERTED for direct `zip-boot --title firered|emerald` use into a refusal proof and RENAMED `zip_boot_firered_refused` / `zip_boot_emerald_refused`: PASS only on the shipped client's own `Unsupported Gen 3 cartridge ... needs the SLink companion patch` error, no `TCP connected`, no server hello |
| RR rows, `--title rr` | both | companion (except the refusal proof) | unchanged | NO CHANGE |
| `gen3_exp` rows, `--title exp` | both | clean expansion | unchanged | NO CHANGE: the pack has no `companion_required` (exempt until its companion lands) |

Live-unverified by construction (no emulator was run): the companion-overlay randomized carts are admitted through the anchors path
(unknown hash, kind `rand_companion`), the rows' fixtures are the same clean-derived SYNTH saves, and a companion client may use native
paths where the clean one used the Lua fallback; the randomized rows (explicit_only, `SLINK_GEN3_RAND_ROMS`) need one live pass before
their results are trusted. Open owner call: whether to retire the clean `frlg`/`emerald` plan definitions altogether (they are inspectable
but unrunnable).

## Review follow-ups F1-F5 (2026-10-03)

- F1: `--title frlg` and `--title emerald` refused up front by `clean_plan_refusal`, called from `run_pass` (not `main`) (message points at `--title frlgc`); `rr`, `exp`, `frlgc` unaffected.
  `classify_failure` is left alone: an unexpected launch refusal already ends with `RESULT: FAIL`, a real failure, and the refusal-proof rows
  print the refusal text on PASS, so keying "contention" on that text would misclassify them.
- F2: `gen3_fixtures.py boot-check --companion` refuses a `--rom` whose sha1 is not the `patch/dist/gen3_companions.json` `rom_sha1` of the checkout the tool runs from (the lane's copy, since the rows run `tools/gen3_fixtures.py` from the lane) for the title;
  the 12 `frlgc_bootcheck_*` rows pass it.
- F3: `fc_check(..., lane=None)` judges companion evidence against the CUT's pins (`lane` when given, else `git show <cut>:patch/dist/gen3_companions.json`),
  never `REPO`'s; an unreadable cut fails closed.
- F4: `--resume` adopts a prior receipt only if its `# inputs:` equal the lane's current `hash_inputs(row_inputs(row, lane))` (`resume_inputs_problem`).
- F5: `_gen3_flushed` exempts a NO-WRITE half (`no_save` side) from the mtime-after-launch rule. What proves "nothing wrote" differs by row: for
  `active_end_gen3` B and `reconnect_gen3` A the oracle reads the battery and compares the bytes; for the `center_controls_gen3` and
  `save_then_write_gen3` B halves no oracle reads the battery, and the proof is the declared-no_save gate in `check_save_witness_gen3` (a
  no_save half whose receipt dumped a save FAILS). The 8 frlgc no-write halves are pinned by name, each with its proof kind as data, in
  `tests/unit/test_e2e_duo_gen3_companion_battery.py`.
