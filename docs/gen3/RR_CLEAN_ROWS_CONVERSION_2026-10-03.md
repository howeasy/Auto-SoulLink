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
| `native_absent_gen3` (A companion, B clean; valid apply_prepare to both) | CONVERTED into the single duo refusal-proof row (id kept). Scenario field `expect_refused: ("b",)`; `no_save: ("a","b")`. B: the driver (`launch_verdict` in `lua/tests/duo/duo_gen3_main.lua`) passes B only when `run.lua` logged `[SLink-gen3] refused: ... needs the SLink companion patch` and built no client; it logs `REFUSED_AT_LAUNCH` and `WRITES 0`. The oracle requires that line and forbids MYKEY, any TX/RX, any `write`, any admission line, any save dump. A: boots and connects alone, `PROBE_SETTLED writes=0 rx=0` after GO, none of the partner-driven commands; the server shows b never connected and no link. Orchestration waits for A's MYKEY and hello and B's refusal line, then releases A. |
| `linked_faint_active_clean_gen3` (rom_kind a companion, b clean) | RETIRED. Its purpose (the P+H link/faint mechanics on a clean cartridge) has no meaning when the clean RR cannot run a client; its refusal meaning is the B half of `native_absent_gen3`. Removed from SCENARIOS, the orchestrate/oracle aliases, the unit tests and the e2e lists. |
| `faint_cmd_clean_gen3` (rom_kind a companion, b clean) | RETIRED, same reason. Its `_gen3_rom_provenance_problems` helper and `assert_faint_cmd_clean_gen3_saved` wrapper had no other user and are removed. |
| native_absent A half: companion answers a valid `apply_prepare` after the native pre-save (PRESAVE_COUNTER, NATIVE_PREPARED) | RETIRED from this row (A is now passive). The native pre-save path is covered by the durable-trade rows (`trade_gen3`, `trade_decline_gen3`, `trade_reset_*_gen3`) and `test_live_tradescene.lua`. |
| `GEN3_CLEAN_RR_ROM`, `rom_kind`, `UNPINNED_INPUTS` "Pokemon - Radical Red.gba" | KEPT: still needed by the refusal-proof side and the absent gate. |
| engine_signals `production` | Documented (generator comment, `tools/gen_gen3_engine_signals.py`): it does not decide admission of clean companion titles; the companion-required rule does. |

## Live commands to run later

```
# 1. the clean-ROM gate (needs the unpatched RR dump; spawns EmuHawk)
SLINK_LIVE=1 python -m pytest tests/live/test_lua_gates.py -q -p no:randomly -k mailbox_absent

# 2. the duo refusal proof (A companion + B clean RR; needs both RR dumps and the rr_battle2 fixtures)
python tools/e2e_duo.py --game gen3_rr --scenario native_absent_gen3

# 3. the RR final cut row set (39 rows), or just the two rows above through the plan
python tools/gen3_final_cut.py --cut <sha> --title rr --lane <clean lane> --master master
```

Expected receipt for B: `[client] [SLink-gen3] refused: this radical_red cartridge needs the SLink
companion patch; ...`, `REFUSED_AT_LAUNCH`, `WRITES 0`, `RESULT: PASS (refused at launch ...)`. If A's
settle window shows a write or a command on the first live run (the link panel may still be talking),
widen the 120-frame pre-baseline wait in `lua/tests/duo/scenario_gen3_native_absent.lua`.
