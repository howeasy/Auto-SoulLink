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

- C3-5 scripted play (Sonnet rework: boot via CONTINUE, BFS-precomputed paths, pinned legs through parcel/balls/catch/faint/PC ops) — untracked lua/tests/gen3_scripted_play.lua + tests/unit/test_gen3_scripted_play.py.
- Shadow runs of boxsync/trade/ghost/infopanel/faint with --wire-log (coordinator lane).
- Codex research cx-bab5e874 (expected kinds per RR duo; queue-flooding risk from frame_control vs S.MAX_PENDING 64).

## Next actions (in order)

1. Owner signs **G3a** (evidence in the P3/P3a section). P3 continues: (dispatched already) per PLAN §14 row P3 — C3-1 `lua/gen3/{entry,reads,signals}.lua` + tests (Opus); C3-2 `lua/gen3/{writes,safety}.lua` + tests (Codex DELEGATE); C3-3 `lua/gen3/shadow_run.lua` + isolation test + `duo_main.lua` `SLINK_SHADOW` + `run_gate.py` flag (Sonnet); C3-4 `tools/gen3_shadow_diff.py` + mutation tests (Codex, second worktree); C3-5 `lua/tests/gen3_scripted_play.lua` (Sonnet). **P3a** in parallel: C3a-1 pairing change (Opus, shared `server/` files: guard + Codex REVIEW). Phase worktree off the planning branch; worker cards in the checkpoint before dispatch.
2. Lane, serialized, once C3-x land: shadow beside the old client on FR, RR clean, RR companion (LG has no fixture yet) for scripted play + six RR duos; forbidden-state controls; overhead budget both callback orders. Gen 1 lanes after any shared touch.
3. Queued out-of-lease: extended FR script through the starter (party for faint/boxsync) and an LG fixture; RR audio/frame trace of the native SE route; mailbox pump-before-poll ack lifetime + ST_BUSY-after-clear ops (P5 native.lua); `server/adapters/gen3_codec.py:391-394` stale CFRU comment; `poison_faint` N/A for RR in the coverage table; `tools/mkstates.py:102` RTC wording; fold `ROM_SPECS` duplicates; `data/gen3/pret/README.md`; `flash_save.md` §7 superseded rows; RR profile `GMAIN_ADDR`; "box the last mon" capture for item 28; retire census probe UNVERIFIED notes; borrowed_party/nature_change UNVERIFIED.
4. Master is at e9faff0 locally (pureRGB merges + the sfx range); NOT pushed — owner authority.

## Standing rules that bit this session

Codex headless sandboxes cannot launch Python: always run their checks yourself. The Bash tool breaks on heredocs with odd apostrophe counts: use the Edit/Write tools for code. Shared `server/` changes need `slink-adapter-guard` + a non-author review; the guard blocked once (unguarded tap I/O) and passed after the fix. The fail-closed runner counts a collection-time skip from an unrelated module as a failure: keep lane selectors tight.
