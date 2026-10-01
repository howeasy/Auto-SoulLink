# P3b.7 dispatch plan (Codex Gen2-Part2, card gen2-P3b7-plan, 2026-09-23)

**Historical record, superseded.** This plan's blockers (server rows selecting the legacy
`gen2_crystal` adapter, `Entry.build` production composition unimplemented, etc.) describe the
state before the P3b.8 cutover. `gen2_crystal` was since removed (`server/adapters/__init__.py`
`_RETIRED_GAME_IDS`); Gen 2 is now served by `gen2_gsc.py` + `lua/gen2/*.lua`, and the Gen 2 RC
evidence (98/98 sweep cells, tag `gen2-rc-evidence-2026-09-25`) postdates this plan. See
`docs/gen2/PLAN.md` for current status.

READ-ONLY plan pinned at `347c8000` (production and duo files unchanged since `1bb69b41`). Delivered in the Codex
transcript; recorded by the coordinator. The write leases below are PROPOSED; each needs coordinator dispatch + ACK.

## Verdict

The first Crystal<->Crystal `gen2_new` link cannot run as a production PHYSICAL lane at this cut. Fixtures exist
(both proposed inputs have four-stage receipts: `crystal_battle` OT 46401 and `crystal_battle_ot2` OT 44068), but
admission and runtime composition refuse production use.

| Prerequisite | Present | Missing for a production duo |
|---|---|---|
| P3b.2 fixtures | 8 qualified saves + receipts | per-attempt rebind; `verify_gen2_release.py:105` fixtures lane UNIMPLEMENTED |
| P3b.3 reads/admission | packs, injected reads, candidate composition (`lua/gen2/entry.lua:9-68,186-235`; `reads.lua:321,443`) | catalogs G1 **PENDING**, rows BUILT (`data/games/gen2_{crystal,gold,silver}/admission.json:9-12,65-70`); `Entry.admit` rejects selected rows; `Entry.build` "production runtime composition is not implemented" (`entry.lua:160-166,266-269`). **Needs an owner-signed admission decision.** |
| P3b.3a-P3b.5 | inspect, signals, writes, boxes, checkpoint modules | GAME R-3/R-5g open; production `Signals.new` refuses (`signals.lua:101-113`); checkpoint `runtime_authorized=false` (`gen2_write_safety.lua:123-125`); active faint/explode + live window proofs open (`writes.lua:10-16,133-136`; `boxes.lua:192-207`) |
| P3b.6 client/routes | `client.lua`, `run.lua`, title-parametric `Gen2GSCAdapter`; C/G/S share `gen2_gsc` pairing (`server/adapters/__init__.py:120-129`) | `run.lua` builds MODEL candidate IO with admission/writes denied (`run.lua:57-59,76-117`); `lua/slink.lua:84-106` selects the legacy client; server rows select `gen2_crystal` (`__init__.py:64-72,189-191`). Re-pointing fails: `Gen2GSCAdapter` needs `title` but generic construction forwards `is_rr`/`rom_type` (`gen2_gsc.py:68-71`; `__init__.py:20-28`; `server.py:1353-1364`; `state.py:905-913`) -> needs an explicit title binder. |

Smallest PHYSICAL milestone after those gates: one `gen2_new` C<->C `link`, A from `crystal_battle`, B from
`crystal_battle_ot2`, separate SaveRAM dirs (same ROM-derived save filename, `tools/e2e_duo.py:1163-1181`), normal
Route 29 input with the recorded O-10 Ball exception. The driver must observe two engine captures with distinct keys,
the server's alive `route_29` link, two native successful saves and cold reloads; an independent Python oracle
compares server state with flushed party/box/ball bytes (first `0x8000` CartRAM bytes). Partial P3b.7 evidence only.

## 5.15i extraction

The plan's `tools/e2e_duo.py:4134-4153` cite is stale. Current hardcoding: `:4216-4218` (missing post-result oracle
raises only for `gen1_new`), `:4220-4224` (save witness Gen 1 only); at `:4254-4268` two client `RESULT: PASS` lines
can pass an unbound Gen 2 scenario. Fix: an explicit evidence descriptor per migrated family requiring a witness
validator + post-result oracle, each scenario names its oracle, validated before launch and before the verdict; Gen 1 +
pureRGB rebound to the same contract; legacy families' empty contracts explicit. Inject a Gen 2 witness validator (the
Gen 1 one slices `[0x498:0x8000]`, `e2e_duo.py:682-693,4099-4110`); missing markers must FAIL, not take Gen 1's "zero
saves, skipped" path (`:4125-4129,4143-4147`). `tools/run_gb_gate.py:278-341` already plans Gen 2 ROM/CGB/SaveRAM;
its `seed_saveram` path refuses Gen 2 (`:251-263`).

## Proposed cards

| Card | Exclusive files | Prerequisite -> first falsifier -> exit evidence | Shared decision / size |
|---|---|---|---|
| U1 C hook proof | `data/games/gen2_crystal/engine_signals.json`, `lua/gen2/signals.lua`, `tests/unit/test_gen2_signals.py`, new `lua/tests/gen2_frame_align.lua`, new `tests/live/test_gen2_frame_align.py` | qualified C fixture + emulator lane -> wrong bank/site, script-bytecode arm or wrong CGB callback frame refuses -> capture/save sites fire with frame/bank receipts before production registration | reuse hook_registry/GB binding; L |
| U2 checkpoint + writes | `lua/gen2_write_safety.lua`, `lua/gen2/writes.lua`, `lua/gen2/boxes.lua`, `tests/unit/test_gen2_{writes,boxes}.py`, new `tests/live/test_gen2_write_windows.py` | U1 -> unarmed write / unsafe window succeeds or current-box traffic refused -> live negative + liveness receipts | shared permit + GB checkpoint; L |
| U3 production graph | `data/games/gen2_crystal/admission.json`, `lua/gen2/{entry,client,run}.lua`, `tests/unit/test_gen2_{entry,client}.py` | **admission authority** + U1/U2 -> unknown hash / early hello / unarmed write reaches production -> admitted Crystal via `Entry.build`, fail-closed controls | compose shared admission/hello/dispatch/write; L |
| U4 server title binder | `server/adapters/__init__.py`, `server/adapters/gen2_gsc.py`, `tests/unit/test_gen2_adapter.py`, `tests/unit/test_gen2_pairing_matrix.py`, new `tests/unit/test_gen2_server_bind.py` | pairing contract -> hello or persisted reload builds the wrong title, or a mixed title changes the locked run -> C/G/S constructor/pairing/reconnect/reload tests | generic routing, title from adapter data; adapter guard; M |
| U5 launcher/Manager route | `lua/slink.lua`, `server/manager.py`, new `tests/unit/test_gen2_launcher_route.py`, new `tests/unit/test_manager_gen2.py` | U3/U4 -> a C cartridge still opens the legacy client -> `slink.lua` launches `gen2/run.lua`, no shim | S |
| H0 neutral duo pipeline | `tools/e2e_duo.py`, new `tools/duo_oracle_pipeline.py`, new `docs/shared-duo-oracle.md`, `tests/unit/test_e2e_duo_{scenario_selection,save_witness,lane_isolation}.py` | receipt interface -> `gen2_new` without a required stage passes on client RESULT -> absent stages fail, Gen 1/pureRGB rebind green, C/C preflight hash-bound | EXTRACT orchestration + receipt transport only; M |
| H1 natural link driver | new `lua/tests/duo/{duo_gen2_main,scenario_gen2_link,gen2_route29_inputs}.lua`, new `tests/unit/test_gen2_duo_driver.py` | U3/U5 + H0 contract -> a printed CAUGHT/PASS without engine capture + save is red -> distinct OTs, captures, saves, frame-bound receipts | Gen 2 facts here; L |
| H2 independent Gen 2 oracle | new `tools/gen2_duo_oracles.py`, new `tests/unit/test_gen2_duo_oracles.py` | H0 schema -> altered links.json / wrong area / unchanged Ball pocket / torn witness passes -> SERVER/PYDEC/save/reload comparison rejects each | per game; M |
| H3 physical wrapper | new `tests/e2e/test_duo_gen2_new.py` | H0-H2 -> missing input silently skips/passes -> one C<->C `link` receipt | S |
| H4 full lane closure | `tests/live/test_gen2_new_gates.py`, `tools/verify_gen2_release.py`, `tests/unit/test_verify_gen2_release_lanes.py`, new `tests/gen2_release_requirements.json`, `docs/gen2/gen2_requirements.md` | all scenarios -> a missing scenario/oracle counts green -> C<->C, G<->S, C<->G matrix | L |

Parallel: U1, U4, H0 disjoint -> start together. U2 after U1; U3 after admission authority + U1/U2; U5 after U3/U4;
H1+H2 after H0 fixes the receipt interface; H3 alongside; H4 last. Physical runs share the one emulator lane.
