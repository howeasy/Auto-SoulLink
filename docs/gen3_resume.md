# Gen 3 migration — resume note (updated 2026-09-23, checkpoint 10: first live duo on the new client PASS)

Read this first after compaction. Authority: the owner-approved plan `docs/gen3/PLAN.md` (rev 5, §6 phases, §14 dispatch, §14.1 gate ledger) and the sole work ledger, the `AGENT_CHECKPOINT` block in the sweep worktree's `docs/gen1_reference/RC_MASTER_GUIDE.md` (`E:/Google Drive/SLink/.claude/worktrees/gen1-rby-code-sweep-8d06e2`). Requirements ledger: `docs/gen3_requirements.md`.

## Where things are

- Worktree `E:/Google Drive/SLink/.claude/worktrees/gen3-migration-planning-5d8e45`, branch `claude/gen3-migration-planning-5d8e45`, pushed to origin on owner authority (2026-09-21) so CI could build the pret symbols. Not merged to master. Base: master `4749a2c`.
- Coordinator: Claude session `30c21a7a-9a9b-44db-b573-10e09226bcc8` (Opus 5.5; earlier sessions 92be0738, f4121ed4). Peers (2026-09-23): Codex live thread **"Review Gen 3 Part 2"** (id 01a0cba4-88cf-7a51-9616-2e0eb582bc87, workingDirectory `E:\Google Drive\SLink`). Its live REQUESTS return NO_LIVE_PEER, so cards go as `delivery: steer` NOTES with a `queueKey`, and replies come back as notes or via `magi exchange <id>`. OMP session **"Gen3-2"** (case-sensitive) takes live requests, one card at a time. Subagents: Haiku/Sonnet/Opus with `model` set, at most 3 at a time. The Stop hook `~/.claude/hooks/orchestration.py` tracks note cards (`done note:<queueKey>`); never `clear` to silence it. magi refuses new requests until old replies get `kind: outcome` (RECONCILE_FIRST).
- Owner rulings (G0 signed 2026-09-21): FRLG vanilla + Radical Red only; strangler; battery fixtures; agbcc git pin; admitted companion = what the shipped `SLink-RR.ups` produces (md5 `bf8e94a0…`, patcher pin corrected at `72dffad`); LeafGreen dump placed and verified; keep the two-reviewer G6 precedent; `codex/rr-foundation` tagged `archive/codex/rr-foundation` (local); vanilla FRLG trade NOT in this release; no `sync_pending`/`trade_failed`.

## Gate status

| Gate | Status |
|---|---|
| G0 | SIGNED (PLAN §14.1) |
| G1 | **SIGNED 2026-09-21** (PLAN §14.1). Receipts: hook probe PASS on FR clean + RR companion (`docs/gen3/probes/hooks_*_2026-09-21.txt`), frame-end census (`census_rr_overworld_2026-09-21.txt`: R15 parked in BIOS `0x1C4`, System/ARM), flash domain = `SRAM` 0x20000, six RR duos PASS twice on the old client, golden transcripts committed (`tests/fixtures/gen3/wire/`, 796K, four gzipped), conformance suite 16 passed with the old-client characterization (items 1/14 documented as A19; 29/30 were checker over-assertions; 28 unevidenced). Ask the owner to sign G1 with those receipts. |
| G2 | **SIGNED 2026-09-21** as pinned facts only (PLAN §14.1; report `docs/gen3/G2_report_2026-09-21.md`, §9 = G3 carry-forward list). |
| G3a | SIGNED (P3a pairing; see P3/P3a section). |
| G3 | **SIGNED 2026-09-23** (PLAN §14.1) on `docs/gen3/G3_request_draft.md` as written; OPEN/PARTIAL/LG+RR-clean carried as limits. P4 started. |

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

## Checkpoint 6 (2026-09-22, owner stop) — leg oracles hardened after the R12 audit

- Tree clean at the commit after this note. No workers running. Peers: OMP "Gen3-Resume" idle; Codex live thread is "Gen 3 Part 2" (use delivery=live; "Plan Gen3 support" was unreachable for tasks). Rule: one OMP card at a time; closed headless Codex runs keep writing.
- Landed since checkpoint 5: checkpoint attribution (every negative refused by its own clause; FR all PASS, RR 9/9, `checkpoint_*_2026-09-22e/c`); checkpoint-pack follow-ups 6f0e301 (two independent Codex ACCEPTs); negatives tool low items; old-client detector fixed (vanilla FR/LG no longer radical_red; LG own base-stats table; ROM-only AP split) 8e125fe/897fefc3/d393c2f2 (Opus review ACCEPT, B1 profile git_head fixed); FR battle bag pinned + pocket settle; FR parcel_deliver really talks to Oak (69fadd0); save oracle 4db7855 (footer id 0xFF4, one slot, unique ids, checksums, fails on dialog timeout/flush failure); RR leg oracles (C3-28: target-bound PC ops with box readback, catch placement, warp destination, per-battle faint baseline).
- PHYSICAL at this checkpoint: RR r7 (`shadow_rr_play_r7_2026-09-22`): battle_to_field, wild_faint, wild_catch, door_warp, pc_ops, pc_release all PASS on the new oracles (release: target gone from party and every box, boxes unchanged); observer saw capture_wild, pc_deposit/withdraw/box_place, pc_release_begin/pc_release, save, faint, whiteout. The save leg FAILS on the stricter helper: counter 4->5 and slot valid, but the "saved" dialog never closed in 600 frames (the old helper returned true here). FR run 24: parcel_deliver never reached Oak (whiteout on the southbound walk went to the Viridian Center, the last heal location).

> SYNC 2026-09-22: master merged into this branch as ff9b9b95 (29 commits, clean) and again as 40f7e3ca after the owner-requested pureRGB fix on master (c411b2f3: six overlay symbol pins recomputed on LF bytes; f6229e77 had hashed a CRLF checkout). Both checkouts' LF-pinned files rewritten from their blobs (no content change). Remaining unit failures in this worktree are environment-only (pret cache lives at the repo root). Nothing pushed.

> OWNER RULINGS 2026-09-23: native text (OP_SHOW_MESSAGE / OP_SHOW_BATTLE_MESSAGE) removed from the RC; AP deferred post-RC. Both are tracked in docs/gen3/TODO.md with the peer ghost.

> OWNER RULING 2026-09-22: peer ghost removed from the Gen 3 RC and deferred post-RC (PLAN §0/§10, requirements 'Not in this release'). P5 drops ghost.lua and the ghost scenario; RR duo set is eight.

## Checkpoint 10 (2026-09-23, owner stop): first live duo on the NEW Gen 3 client PASS

- **Milestone:** `gen3_frlg` `faint_cmd_gen3` PASS live on the new client (receipt `docs/gen3/probes/duo_fr_faint_cmd_gen3_2026-09-23.txt`, c8098b30): A's faint -> B force_faint lands through the overworld checkpoint, both memorialize to box 13, both save (counter 4->5, 14/14 sectors, hook dump == flushed battery), PYDEC oracle PASS. First attempt failed on a HARNESS bug (debug inject_event drains A's queue into the HTTP reply; fixed c8020f61). The first RR attempt died on a load bug (RR title syms), fixed c8020f61, not yet re-run.
- **Owner rulings this stretch (PLAN §0):** in-battle faint must work on vanilla with RR parity; RR comes under the new standard alongside P4 (all cards pack-neutral, P5 cards in parallel, RR route flips at G5); old RR client addresses are trusted evidence, design follows the Gen 1 standard (not behaviour-for-behaviour).
- **Landed (P4/P5, all gated; ~35 commits 10cd25f9..c8098b30):** G3 signed (10cd25f9); shared core `lua/core/{session,identity,deferred}.lua` (89601bc3 + fix rounds f3575ff5, aa062f61, 690e1c63, a7bba8b1); `lua/gen3/client.lua` pack-neutral driver + Entry production mode + World harness (73736eda); reads/profile for both packs (af529c86, RR pins 6c955402, exec flags + LG BASESTATS fix 13913c25); boxes (3554c986, 3c9c42a5, d1d4fcec); native.lua (7a03318f, BUSY fix + per-op deadlines a15de812); safety reason dispatch battle/battle_commit/native/sound (2a52924e); Entry binding single native instance (9505648b); sound (f02ed90b); RR trade FSM (a15de812, 78908fe8); RR save layout in the codec (62887460); bootstrap/route/manifest (099fc0cc); conformance World + write ownership (7efcc74d); duo harness gen3_frlg (d146b992) + gen3_rr_new (46a5f597); LG scripted helpers (912dbecd); FR party fixtures cold-boot only (03276561); Gen 1 rebind handoff doc (2f74068a).
- **Save helper root fix landed** (C4-F2, c1507b7d): wait for field controls to be free before Start, gate Down on the start-menu window, pick SAVE from sStartMenuOrder; lane re-verified first-attempt saves.
- **Independent review status (Codex):** ACCEPT writes.lua, deferred.lua, identity.lua, entry binding, native.lua, core session.lua (REV6). client.lua quiet-timer ACCEPT; trade lifecycle fixes 78908fe8 ACCEPT (REV7; caveat: when refresh_enemy starts writing through the sink, replace the attempted-byte "posted" inference with a per-job dispatch receipt from native.lua). Duo harness REJECT (7 MAJORs: RR decode, whiteout no-op, record integrity, RR extension freshness, explode HP poke, rival/native_absent non-performance, wait_go) -> fix card C4-6b in flight. boxes.lua: Opus REJECT fixed in d1d4fcec.
- **Duo harness:** C4-6b (50d580c9) and C4-6c (32e0e469) landed; FR faint_cmd_gen3 re-run PASS on the stricter harness (c82b38c1). Earlier: Codex REV2 REJECT with 4 MAJORs queued as C4-6c: bound the mutable whitelist (HP<=max, PP only on real moves, status) with scenario postconditions; require read success before BOXED/RETURNED absence; bind the RR extension RAM copy to the final save ordinal; keep explode UNQUALIFIED until an RR execution witness downstream of attackcanceler/tryexplosion; RR level bound from profile (250). Accepted parts: RR decode, no-op deposit refusal, invariant diff, extension content compare (else OPEN), no memory staging, rival as control, native_absent valid trade.
- **In flight at stop:** C4-8 busy-mailbox single-instance test + rival-swap refresh window design (OMP; uncommitted test_gen3_entry.py + docs/gen3/research/rival_swap_refresh_window.md in tree).

## Next actions (checkpoint 10)

1. Reconcile the four in-flight cards (gate, commit, review): C4-6c landed (32e0e469) -> Codex REV3-duo-harness in flight; C4-8 -> commit test + design doc;
2. Lane: re-run gen3_rr_new faint_cmd_gen3 (RR load fixed); then the remaining FRLG duos (link, deadzone, boxsync, whiteout, reconnect, linked_faint_active needs the battle policy which is now bound) after C4-6b; the 13 battle/native/sound probe rows (need 5 battle savestates).
3. Open design items: rival-swap gBattleMons refresh window (OMP C4-8 doc); LeafGreen fixtures for the FR<->LG G4 duo; RR battle fixtures; RR walking/battle-menu syms beyond the 13 cited.
4. DONE (owner: "Patch"): old client vanilla OUTCOME_CAUGHT/RAN fixed to pret 7/4 (3ea768fa). Master cherry-pick only on owner authority.
5. Regression sweep after the stop: RR scripted-play fixture leaked SLINK_GEN3_TITLE into later FR tests (fixed 45285857); entry.lua local named `client` tripped the BizHawk-global scan (fixed); probe tests updated for the 13 reason rows (4abad314); live wire logs moved to docs/gen3/probes/wire. gen3 unit suite 1632 passed; full unit suite only fails the env-only test_gen1_trade_patch (no .cache/pret/pokered here).

## Checkpoint 9 (2026-09-23, owner stop): G3 request ready

- **G3 request draft is ready for the owner**: `docs/gen3/G3_request_draft.md` (5efd1f24). It has a summary at the top. The owner is asked to sign the evidenced FR clean / RR companion G3 cells. The 7 OPEN kinds, 4 PARTIAL rows and deferred LG/RR clean artifacts are carried forward as limits. This is not G4 or RC approval.
- PHYSICAL this round:
  - FR runs 28e and 29: viridian_pc deposit/withdraw, pc_release and save PASS, twice, with identical frames. Receipts a2f2fea1, fde19a89. First FR save hook fire.
  - RR r9 whole lane PASS (checkpoint 8).
- Landed (all gated):
  - C3-38 c3560eac: RAM-witnessed PC flow (pins in docs/gen3/research/fr_pc_ram_witnesses.md, OMP O4). Coordinator follow-ups from runs 28a-d:
    - 0a8d4787: whiteout recover/resume into the Center.
    - 39fb1bc6: Continue-BOX prompt answered with B. Its comment claimed the prompt starts on YES; it starts on NO, corrected in 37c531f1.
    - 36457936: PC failure diagnostics.
    - 259e701e: B out of Task_PCMainMenu, the real 28b-d loop.
  - C3-39 5efd1f24: G3 draft. Codex.
  - C3-40 37c531f1: FR PC guard mutation matrix 4/27 -> 27/27 (OMP; Codex ACCEPT).
  - C3-41 c0c0760b: 13 timeout names witnessed, 0/15 -> 15/15. OMP.
  - af3f1b16: RR yes/no rationale comment.
- Owner rulings this session:
  - Native text removed from the RC and disabled with the code kept (0786894b, d3c69de7; docs/gen3/TODO.md).
  - AP deferred post-RC (494d3866).
  - Peer ghost deferred (checkpoint 6).
- Reviews: C3-36 Opus ACCEPT; C3-38 OMP ACCEPT (top-menu blocker already fixed); C3-40 Codex ACCEPT; C3-33 Sonnet ACCEPT.

## Next actions (in order)

0. (checkpoint 9) (a) OWNER: review and sign G3 from docs/gen3/G3_request_draft.md (PLAN §14.1 ledger row). (b) Queued minors, none blocking:
   - PC.popup's search can never reach the last popup row (4) within its budget, an off-by-one (OMP C3-41). No current leg uses it.
   - A focused area=2/option=2 test for the PC.popup mapping (Codex review of 37c531f1).
   - Optionally, comment the two cursor-guard reachability notes (OMP C3-41 finding 2).
   (c) After G3: P4 (new client + FRLG cutover), per PLAN §6/§14.

Older (checkpoint 8):

## Checkpoint 8 (2026-09-23, owner stop)

- Peers: magi restarted, and steer now works for Codex (`magi doctor`: "Codex app steer channel found"). Codex thread "Review Gen 3 Part 2" still returns NO_LIVE_PEER for live REQUESTS, so cards go as steer notes WITH a `queueKey`; Codex replies by note or into the task mailbox (`magi exchange <id>`). OMP "Gen3-2" takes live requests. The hook `~/.claude/hooks/orchestration.py` was fixed: failed deliveries and plain notes no longer mark a peer idle.
- Landed and gated:
  - C3-33 09c051d0: RR pack save-block pointers are ROM-derived (0x03005008/0C/10) plus the saveblocks_setter anchor. Sonnet ACCEPT (it re-derived the ROM bytes).
  - C3-34 78f2a29e: FR review follow-ups. The Opus review was BLOCKED; its blocker is fixed by C3-36.
  - C3-35 eb97f457: non-IRQ sample floor. OMP.
  - C3-36 4f511a1e: route1_faint finishes its battle; the forced send-out party menu is handled via CB2_UpdatePartyMenu 0x0811EBA0. Opus review IN FLIGHT at stop.
  - Coordinator fixes: 88311449 (C3-31 review minors), 904ad4d3 (the grass hunt's first step follows the tile).
  - C3-37 0c3f0ec5: G3 request draft + requirements §X.1 refreshed. OMP.
- PHYSICAL:
  - RR r9 whole lane PASS at 09c051d0 (277429b4).
  - RR checkpoint 9/9 PASS on the current cut (bac6ea77).
  - FR census header title=firered (2340cbd9).
  - FR runs 26-27 (e131f747): route1_faint now completes its battle. viridian_pc reaches the Viridian PC after 2 incidental battles, but the deposit input route stalls at the PC top menu ("Which PC should be accessed?"), so nothing departs and the pc_target oracle refuses.

## Next actions at checkpoint 8 (superseded by checkpoint 9 above)

0. (checkpoint 8) (a) DONE: Opus ACCEPT of 4f511a1e (C3-36; closes the C3-34 blocker). Queued minors, none blocking:
   - The move-slot A (~:780) and the mash_a stop on party_menu_up (~:784) have no test. The fake should model A on a fainted slot opening the popup first, and "has no energy" appearing only after SEND OUT (party_menu.c:3743-3757).
   - If a stray A already opened the popup, one B recovers it (:3083-3087), instead of failing forced_party_input_not_ready.
   - gPartyMenuUseExitCallback is never cleared, so the :1239 check proves little.
   - The faint baseline (~:1965) should be `> 0` after each battle, because BattleStartClearSetData zeroes playerFaintCounter (battle_main.c:2308).
   - Eggs have HP > 0 (~:1197).
   - The route1_faint in_battle/settle gates are covered only by the source-grep test. (b) FR deposit route: runs 27b stalls at the PC top menu. Diagnose from pret: the PC owner menu rows once the Pokedex is obtained (docs/gen3/research/fr_pc_flow_and_pc_move_sites.md, Codex R9), how the leg's A presses are paced, and whether a witness (the Task_PCMainMenu 0x0808C39C task or a menu-cursor var) shows the first A landed. Fix in the FR driver with a RAM-witnessed step per menu, like RR's pinned flow. Then run FR 28 from `SLINK_STATE=slink_fr_route1_faint.State SLINK_GEN3_PLAY_FROM=viridian_pc_deposit_withdraw` (the state is now saved on the field) through pc_release and save. (c) When the FR PC kinds are PHYSICAL, fold them into docs/gen3/G3_request_draft.md and send the G3 request. (d) AP: deferred post-RC (owner 2026-09-23, PLAN §0); the " AP" header check is no longer an RC item.

Older (checkpoint 7):

## Checkpoint 7 (2026-09-23, owner stop to restart magi)

- Peers this session: Codex live thread **"Review Gen 3 Part 2"** (the "Gen 3 Part 2" thread refused live requests; the Gen 2 coordinator also routes to it), OMP **"Gen3-2"** (case-sensitive). `delivery: steer` failed every time with NO_STEER_CHANNEL (the Codex desktop app-tools channel is missing; magi doctor warns codex 0.155.1 is newer than verified 0.153.4). That is the reason for the restart. magi refuses new requests (RECONCILE_FIRST) until old replies get `kind: outcome`.
- Landed (all gated): C3-30 save helper 30d13c63 (close = field_controls_locked released; open = sSaveDialogCB changed; pret never clears it; Haiku ACCEPT); C3-29 FR driver d18a6080 (lastHealLocation whiteout projection, starter/rival/parcel/warp/PC oracles; Opus ACCEPT) + coordinator fixes 3ef34edc/a1c53f31 (destination checks wait for the step off the door) and c06970f3 (return_to_grass_origin); C3-32 probes 2b4e0c68 (census title by ROM hash; positive rows over non-IRQ frames; Haiku ACCEPT); C3-31 RR driver 02150752 (stable_field nil fix, ten deletion-sensitive guard tests, two unreachable guards removed; Opus review IN FLIGHT at stop).
- Reviews closed: C3-26 Opus ACCEPT, C3-27 Sonnet ACCEPT, C3-28 OMP cx-a59b23a9 (no false pass; gaps -> C3-31).
- PHYSICAL: RR r8 save leg PASS (880c10ed). **FR run 25 (6a253ee5): parcel_deliver PASS, route1_catch PASS with the observer seeing capture_wild (the last G3 lane item), route1_faint PASS.** 25e viridian_pc FAIL: an incidental encounter's A-mash hit the remembered action cursor (POKEMON) and looped on the fainted lead (screenshot "SQUIRTLE has no energy"). FR checkpoint controls PASS on the non-IRQ scoring (37f3043b: idle non-IRQ 276/276, all 24 refusals IRQ).
- OMP fact-check cx-77ee4cb6: RR gSaveBlock1Ptr is 0x03005008 (ROM setter pool 0x4C08C, InitMainCallbacks, savestates). 0x03003840 is an IntrMain_Buffer literal-pool constant that equals the pointer only because RR's ASLR offset is hard 0. The new RR packs carried the legacy value.
- UNCOMMITTED at stop (stop notes sent; patches saved in `.claude/handoffs/2026-09-23-wip-*.patch`, gitignored):
  - C3-34 (Codex cx-33906f6a): gen3_scripted_play.lua + test_gen3_fr_story_oracles.py. Scope: the R13 minors (untested guards :789/:799, G.finish without return, recover outside pcall, heal checkpoint only when displaced) + addendum 6, where the battle policy must steer to FIGHT via verify_fight_cursor, re-steering each time the menu returns.
  - C3-33 (OMP cx-bfac60e9): RR packs' saveblock pointers derived from the ROM (0x03005008/0C/10, source rom:SetSaveBlocksPointers pool), generators, tests, docs/gen3_write_checkpoint.md.
- Housekeeping: two stash entries `c3-30-lua-redcheck` and `c3-30-cb0-redcheck` are already applied (their content is in 30d13c63). guard_git blocks `stash drop`, so the owner can drop them.

## Next actions at checkpoint 7 (superseded by checkpoint 8 above)

0. (checkpoint 7) (a) Reconcile C3-34 and C3-33: read each peer's reply (or `magi mail --task <id>`), gate, commit, and get a non-author review of each. (b) Record the Opus review of 02150752 (C3-31). (c) PHYSICAL: RR r9 whole lane on the committed C3-31 + C3-33 cut (first run on the ROM-derived pointer); FR run 26 from `SLINK_STATE=slink_fr_route1_faint.State SLINK_GEN3_PLAY_FROM=viridian_pc_deposit_withdraw` through viridian_pc, pc_release, save. FR lane invocation: `SLINK_GEN3_CHECKPOINT=<wt>/data/games/gen3_frlg/write_checkpoint.json SLINK_GEN3_TITLE=firered python tools/run_gate.py lua/tests/gen3_scripted_play.lua --rom "patch/build/gen3_Pokemon_-_FireRed_Version_(USA).gba" --shadow --timeout 3000`. The FR legs do NOT declare savestates, so SLINK_STATE is required when resuming. (d) Queued minors: a non-IRQ minimum-sample floor for positive checkpoint rows; the FR census re-run with the new header. (e) The AP " AP" header still needs an AP-patched dump from the owner (none on disk). (f) Then update the G3 draft (FR capture_wild now PHYSICAL) and send the G3 request with the OPEN list.

Older (checkpoint 6):

0. (checkpoint 6) (a) save_via_menu: dismiss the final "saved the game" message (A until the dialog callback clears) before the 600-frame close check; RR r7 save shows the save completed but the dialog stayed up. (b) FR whiteout recovery must read the destination from SaveBlock1 lastHealLocation, not opts.heal_map (FR run 24 warped to the Viridian Center); then FR run 25 from slink_fr_parcel_fetch.State to deliver the parcel, then catch. (c) FR story oracles from R12 (starter species, rival outcome + lab flag, parcel_fetch key-pocket grant, exact warp destinations, target-bound FR PC ops with box readback). (d) Independent reviews pending: C3-28 RR oracles, C3-27 save oracle, C3-26 parcel. (e) AP header " AP" suffix: confirm on an AP-patched dump.

1. FR capture_wild (the only remaining lane item for G3): FR runs 20/21 reach the action menu deterministically and steer to BAG, but the in-battle bag pocket navigation to POKe BALL is unpinned (run 21: one battle, never resolved, outcome 0). Card: pin it from pret (src/item_menu.c: which pocket the battle bag opens on — remembered last pocket; pocket switch keys; POKe BALLS pocket index; Oak gives 5 Poke Balls after the Pokedex) with a RAM witness for the open pocket (gBagMenuState / sBagMenuState pocket field from the .sym), then re-run from slink_fr_parcel_deliver.State (SLINK_GEN3_PLAY_FROM=route1_catch). Then route1_faint, viridian_pc_deposit_withdraw, pc_release on FR for the FR PC kinds.
2. Reconcile the four OMP replies; fix any blockers.
3. Update the G3 draft with FR capture_wild/PC and send the G3 request with the OPEN list (evolve_species_store, trade_done, poison_faint, borrowed_party/nature_change, pc_move_full_party, native-op-staged) and the five PARTIAL rows stated as limits.
4. OMP review cx-eabcfef4 (parked-CPU, 900a51b) reconciled: range + pret citation + LG + RR-unchanged VERIFIED. Accepted findings, queued: (a) HIGH, shipped old client: `lua/games/gen3_frlge.lua` `_detectRR()` (:413-433, called from :448-490) can classify vanilla FireRed as radical_red (the FR census header reads `variant=radical_red`), applying RR addresses to a vanilla game; fix = require the CFRU ROM pointer at 0x080001BC before returning radical_red, plus a detector test. The new Gen 3 client admits by sha1 and is unaffected. (b) census probe must pin/assert the title and record the ROM sha1 in its receipt header; the FR census's state labels were read at RR addresses (R15 and task data are still valid; the FR checkpoint receipts confirm the range independently). (c) commit 900a51b's "revert fails 5 tests" is 4 (measured by the reviewer). (d) FR idle positive margin is thin (275-276/300 vs the 0.90 bar, with ~5% IRQ frame ends refused by design): score over non-IRQ frames. (e) missing WaitForVBlank symbol raises a bare KeyError: give it a named SystemExit.
5. OMP review cx-f470be07 (checkpoint probe rows, ef17e39) reconciled, all accepted and queued: (a) HIGH for G3 evidence: a negative row passes on ANY refusal (P.verdict probe:72-77; safety.lua reports the first failing predicate in pairs order); the 22b FR receipt passed script_running on wireless_comm_type. Current receipts (22d FR, 22b RR) show a fitting reason on every row, but the probe must enforce it: record the failing predicate per sample and require the row's terminal clause (or sample with that clause admitted). Note RR pc_menu was refused by script_context_status, not the task allow-list. (b) script_running witness re-reads the predicate's own byte: honest wording "not independent evidence"; the pre-A shutdown check stays. (c) TASK_PC_MAIN_MENU pinned only to itself: derive from the .sym/pack; LG sym differs at that line. (d) move the >=60 hold into the row spec + verdict. (e) the WRITE_LOG count=0 assert is tautological (nothing writes): delete it from receipts' evidence claims or implement it.
6. OMP review cx-c878cf0d (R11 unreachable states, 94dda53) reconciled: production harness + RR zero-relocation bytes + native GAP VERIFIED; the doc DID flag the FR wireless liveness risk (its CloseLink mechanism was wrong; C3-22's title-menu adapter-probe cause replaced it). Rejected: "maybe read via the misdetected profile" (the checkpoint probe runs the hash-admitted new FR pack). Queued: (a) §7 "refusing clause" column -> "a refusing clause (order-dependent, safety.lua:52-56)" until first-failing keys are logged; (b) RR evolution row rests on the generic allow-list property, not the RR address 0x080CE8DC: annotate, or add a test that uses the pinned RR task address.
7. OMP review cx-175db98d (link predicate, 422a25a) reconciled: pret set/clear sites for both transports + RR literal-pool derivation VERIFIED, no pre-exchange counterexample found. Queued: (a) RR link-ACTIVE side is inference only (the RR idle side is PHYSICAL: 300/300 in checkpoint_rr_companion_2026-09-22b): add an RR/FR link-room probe row (enter Cable Club/Union Room while sampling, then leave) or state the limit at docs/gen3_write_checkpoint.md:219; (b) the "revert fails 12/12" fires on "missing predicate", not the semantic change: add a pack test that no predicate sits at 0x03003F3C / named wireless_comm_type; (c) CFRU-added link entries are not decoded (limit).
8. Queued: negatives tool low items (pc_move diagnostic double count, poison_faint derivation, inert source_head); RR pointer provenance (0x03003840 vs setter pool 0x03005008); strict artifact_kind wire validation; LG fixture; older queue.

## Standing rules that bit this session

Codex headless sandboxes cannot launch Python: always run their checks yourself. The Bash tool breaks on heredocs with odd apostrophe counts: use the Edit/Write tools for code. Shared `server/` changes need `slink-adapter-guard` + a non-author review; the guard blocked once (unguarded tap I/O) and passed after the fix. The fail-closed runner counts a collection-time skip from an unrelated module as a failure: keep lane selectors tight.
