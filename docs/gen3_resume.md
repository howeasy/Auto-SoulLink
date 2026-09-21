# Gen 3 migration — resume note (2026-09-21, session 2 in progress)

Read this first after compaction. Authority: the owner-approved plan `docs/gen3/PLAN.md` (rev 5, §6 phases, §14 dispatch, §14.1 gate ledger) and the sole work ledger, the `AGENT_CHECKPOINT` block in the sweep worktree's `docs/gen1_reference/RC_MASTER_GUIDE.md` (`E:/Google Drive/SLink/.claude/worktrees/gen1-rby-code-sweep-8d06e2`). Requirements ledger: `docs/gen3_requirements.md`.

## Where things are

- Worktree `E:/Google Drive/SLink/.claude/worktrees/gen3-migration-planning-5d8e45`, branch `claude/gen3-migration-planning-5d8e45`, pushed to origin on owner authority (2026-09-21) so CI could build the pret symbols. Not merged to master. Base: master `4749a2c`.
- Coordinator: Claude session `92be0738-12a4-4228-b388-eb5fe6f7c779` (Fable 5.1). Codex live thread "Plan Gen3 support" (repo root, `E:/Google Drive/SLink`) is the research/implementation peer; headless Codex persists `gen3-syms`, `gen3-tap` exist (their sandbox cannot run Python: the coordinator runs their checks).
- Owner rulings (G0 signed 2026-09-21): FRLG vanilla + Radical Red only; strangler; battery fixtures; agbcc git pin; admitted companion = what the shipped `SLink-RR.ups` produces (md5 `bf8e94a0…`, patcher pin corrected at `72dffad`); LeafGreen dump placed and verified; keep the two-reviewer G6 precedent; `codex/rr-foundation` tagged `archive/codex/rr-foundation` (local); vanilla FRLG trade NOT in this release; no `sync_pending`/`trade_failed`.

## Gate status

| Gate | Status |
|---|---|
| G0 | SIGNED (PLAN §14.1) |
| G1 | **SIGNED 2026-09-21** (PLAN §14.1). Receipts: hook probe PASS on FR clean + RR companion (`docs/gen3/probes/hooks_*_2026-09-21.txt`), frame-end census (`census_rr_overworld_2026-09-21.txt`: R15 parked in BIOS `0x1C4`, System/ARM), flash domain = `SRAM` 0x20000, six RR duos PASS twice on the old client, golden transcripts committed (`tests/fixtures/gen3/wire/`, 796K, four gzipped), conformance suite 16 passed with the old-client characterization (items 1/14 documented as A19; 29/30 were checker over-assertions; 28 unevidenced). Ask the owner to sign G1 with those receipts. |
| G2 | **SIGNED 2026-09-21** as pinned facts only (PLAN §14.1; report `docs/gen3/G2_report_2026-09-21.md`, §9 = G3 carry-forward list). |

## Landed this session (planning branch, in order)

P0: `docs/gen3/PLAN.md` (d42088c, 5e9d7ba), `docs/gen3_requirements.md` (3a00150 → Pins filled 4ad934f), `docs/gen3/research/{pins,flash_save,pins_inventory}.md`, `tools/gen3_pins.py`, G0 record `72dffad`.
P1: `lua/tests/probe_gen3_hooks.lua` + `tests/live/test_gen3_probe_gates.py` (79e1e87, receipts 6e064c3), `lua/tests/probe_gen3_frameend_pc.lua` (75903aa, d820052, receipt c363f2d), wire-log tap in `server/server.py` + `tools/e2e_duo.py --wire-log` (b0e0538 → 91c7025 → 8aac4a0 → e643af7; guard PASS ×3, Codex ACCEPT cx-e19e74ac), conformance suite `tests/unit/test_protocol_conformance.py` + `conformance_map.py` (1847c7c → a729205), transcripts committed (a729205), protocol Appendix A19 (ece022d).
P2: pret symbols `data/gen3/pret/` from CI run 35603224233 (20ab8cb; `tools/build_pret_gba_syms.py`, `.github/workflows/gen3-syms.yml`), profiles `data/games/gen3_{frlg,rr}/profile.json` + `tools/gen_gen3_profile.py` (2ef0eb5), engine sites `engine_signals.json` + `docs/gen3_engine_sites.md` + `tools/{pin_gen3_site,gen_gen3_engine_signals}.py` (84d0b6a, a8c32f3: FR/LG 21 kinds pinned, RR 15), write checkpoint packs + `docs/gen3_write_checkpoint.md` (9c6ab37: 67-row writer inventory, idle task allow-list byte-verified in RR), codec `server/adapters/gen3_codec.py` (3bea4be, f7aa76d: RR save layout pinned, `parse_flash` truncation bug fixed), fixtures `tests/fixtures/gen3/rr_town.sav` + `tools/gen3_fixtures.py` (b266f69, d0e8b38: boot-check + make-fr drivers), release runner core `tools/release_lanes.py` + `tools/verify_gen3_release.py` (910dbdd, 8aed5aa, d0e8b38).
Fixes found by the work: `lua/memory_gba.lua` permutation rows 3/4 swapped vs pret (fa9b677, differential test `tests/unit/test_gen3_lua_vs_codec.py`); `server/patcher.py` + `patch/README.md` stale companion md5 (72dffad).

## Session 2 (2026-09-21, after compaction)

- Relayed task from the pureRGB session (Codex cx-0921a375): old Gen 3 client sound cues were last-write-wins. Landed `f55c4d1`: `lua/sfx_arbiter.lua` + client `M.sfx` (GAME_OVER > whiteout > linked KO > generic, one flush per frame in `on_frame_safe`, deferred KO muted after game_over), 15 lupa tests, shipped by make_release. Old client is byte-identical to master 2629d36 → cherry-pick candidate for the owner. Codex REVIEW cx-e8acc8bc REJECTED round 1 (a client cue newly routed native could be queued behind a same-frame native memorialize and overwrite its ack on pump-before-poll); fixed in 16c1553/6428a46/a76103a (winner carries a native_ok flag; only the server play_sound site sets it; tie keeps native only if all allowed); round 2 cx-c26a5baa REJECTED too (a deferred server sound queued behind a native op inverts the pre-arbiter order); fixed at 4aab46d exactly as recommended: `MB.busy()` in lua/mailbox.lua, native sound only while the mailbox has no outstanding work, regression test over the real mailbox.lua with a memory stub + negative control (72 tests); round 3 cx-3c3b6319 ACCEPT (comment narrowed at ac518de). Card closed; CHERRY-PICKED to local master efc15cb..e9faff0 on owner authority (102 passed, lua parse OK on master; not pushed). Pre-existing pump-before-poll ack weakness (server play_sound beside native memorialize) queued for P5 native.lua. Not verified: in-emulator native route (RR audio trace, lane item).
- Instrument findings: BizHawk names the battery with spaces for unknown ROMs (`gen3 slink RR.SaveRAM`, now the default) and by gamedb name for known ones (`Pokemon - FireRed Version (USA).SaveRAM`, needs `--saveram-name`); the flash counter appears ~950 frames before the 14-sector loop ends (~66 frames/sector), so `gen3_boot_check.lua` waits for 14/14 sectors (flushing at the counter yields a torn slot).
- FR new-game script: walk-out PINNED from pret/pokefirered c75f352 (cloned to `E:/Google Drive/SLink/.cache/pret/pokefirered`): spawn (6,6) 2F, stairs (10,2) via Left arrow-warp, 1F door (4,8) via Down, town map 768; steps verified by SaveBlock1 coords; stalled steps clear textboxes with A (RR intro dialogue). Intro legs remain timed, verified by outcome. `firered_town.sav` is PRE-STARTER (empty party): scenarios needing a party need an extended script through the starter choice (queued).

## P3 / P3a (session 2, after G1+G2 signed 2026-09-21)

Landed on the planning branch: C3-2 writes/safety (92081f4, Codex), C3-3 shadow runner (3031841 + 4c65272 real-Entry binding), C3-4 shadow differential (ae9456e, Codex headless), C3-1 entry/reads/signals (4ad63eb) + storage-pointer follow-up with the C3-6 pack gap (1340417: vanilla box geometry from pret; gPokemonStoragePtr dereferenced, bound [0,124] from load_save.c), P3a pairing (80261f3 + 959c578; guard PASS x2; Codex REJECT->ACCEPT cx-1b5fe474; Gen 1 lanes link/trade/reconnect(--wrong-save)/pc_ops PASS) -> **G3a signature requested**. First PHYSICAL shadow run (965ecc8, `docs/gen3/probes/shadow_rr_explode_2026-09-21.txt`): RR companion explode duo with the observer beside the old client, 19 sites registered, frame_control fires per frame with callback==site; no other kind seen in explode (Codex research cx-bab5e874 settles which kinds each duo SHOULD fire). Two observer instrument bugs fixed on the way (signals:drain() colon; emu.framecount not memory.framecount).

Shadow lane invocation: `SLINK_SHADOW=1 python tools/e2e_duo.py --game gen3_rr --scenario <s> --lane shadow --wire-log` (flag, no path); logs land in `patch/build/e2e_<s>_{a,b}_result.shadow.log` (STATUS + SHADOW lines); differ: `python tools/gen3_shadow_diff.py ... --wire ... --shadow ... --ledger ...`.

## In flight / uncommitted at compaction

- HEAD 1712738 (PC census). UNCOMMITTED: playlib fix round 4 from worker ab9af09 (lua/tests/{playlib,gen3_scripted_play,gen3_rr_scripted_play,gen3_fr_newgame_inputs}.lua, tests/unit/{test_playlib,test_gen3_rr_scripted_play}.py) — standing gates green (213 Lua parse, 105 tests in the touched files, ruff; the 13 full-suite failures are the worktree environment: pret checkout/UPR jar/calc pages live at the repo root); Codex round-2 REVIEW cx-bc675fa4 in flight. Commit once Codex has no blockers.
- Worker ab9af09 resumed on the pinned RR pc_ops recipe (message queued). FR play run 16 launched in the background (`patch/build/gen3_scripted_play_result.txt`, run dir fr_play16).

## P3 physical state at checkpoint 3 (2026-09-21, after G3a)

- Coverage: FR 6 kinds PHYSICAL (map_load, mon_given, battle_begin, battle_end, whiteout, save — run 15 `shadow_fr_play_run15`), RR 6 kinds PHYSICAL (+ faint at the CFRU cleareffectsonfaint completion 0x0909EED2 `shadow_rr_faint`). capture_wild (RR 0x0907DD80+8) and pc_move: not yet witnessed live by the observer.
- RR PC flow PINNED by exec hooks (`census_rr_pc_deposit_2026-09-21.txt`, 1712738): five A presses precede the storage menu; Deposit = Down,A; slot Down,A; Store A → TryStorePartyMonInBox 0x080930E4; party count byte updates only on storage exit. State `slink_pokecenter_full.State` (3 mons) made by `mkstate_gen3_rr_fill.lua`; `slink_prebattle_balls.State` for catch.
- P3 exit items: checkpoint negatives PASS on RR (`checkpoint_rr_companion`), FR needs battle/door savestates; overhead PASS at real time, 0 semantic wire deltas (`overhead_rr_*`, `wire_delta_rr_explode`); reads == PYDEC PASS on the RR real party (`reads_pydec_rr`), FR weak (empty records).
- Instruments: census script mode (SLINK_CENSUS_SCRIPT: buttons/waitN/shot, position-fed direction holds), `tools/gba_map.py` (ROM map parser + BFS PATHS), `tools/gen3_reads_pydec.py`, `probe_gen3_rr_bag.lua`.

## Next actions (in order)

1. Reconcile Codex cx-bc675fa4 (playlib round 2), commit the round-4 diff; integrate the worker's RR pc_ops leg and run the RR lane (pc_ops + wild_catch with the bag timing fix) requiring `pc_move` and `capture_wild` SHADOW lines.
2. FR run 16 result: route1_catch (hunt_encounter loop over four MB_TALL_GRASS tiles) → capture_wild on FR; then route1_faint, viridian_pc_deposit_withdraw (FR PC flow from pret: derive with the census script mode as on RR), save.
3. FR checkpoint negatives: make FR battle/door savestates (the driver can save states per leg like the RR driver) and run `probe_gen3_checkpoint.lua` on FR.
4. G3 evidence assembly: per-artifact coverage table into docs/gen3_requirements.md + PLAN §14.1 G3 row; uncovered kinds listed OPEN (evolve_species_store, trade_done, poison_faint, borrowed_party, nature_change, pc_release).
5. Queued (unchanged): strict artifact_kind wire validation; SB1/SB2 base symbols; storage pointer canonical source; LG fixture; mailbox lifecycle (P5); shadow poll error handling; codec stale comment; older queue.

## Standing rules that bit this session

Codex headless sandboxes cannot launch Python: always run their checks yourself. The Bash tool breaks on heredocs with odd apostrophe counts: use the Edit/Write tools for code. Shared `server/` changes need `slink-adapter-guard` + a non-author review; the guard blocked once (unguarded tap I/O) and passed after the fix. The fail-closed runner counts a collection-time skip from an unrelated module as a failure: keep lane selectors tight.
