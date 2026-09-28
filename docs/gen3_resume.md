# Gen 3 resume note (updated 2026-09-27, checkpoint 26: ALL GATES SIGNED; one closeout session left -- follow docs/gen3/CLOSEOUT_RUNBOOK.md)

Read this first after compaction. Authority: the owner-approved plan `docs/gen3/PLAN.md` (rev 5, §6 phases, §14 dispatch, §14.1 gate ledger) and the sole work ledger, the `AGENT_CHECKPOINT` block in `C:/Users/howar/.claude/hooks/slink/RC_MASTER_GUIDE.md` (it moved out of the retired gen1 sweep worktree). Requirements ledger: `docs/gen3_requirements.md`.

## CURRENT STATE (2026-09-27, checkpoint 26): all gates signed; ONE closeout session left

**Follow `docs/gen3/CLOSEOUT_RUNBOOK.md` top to bottom.** Summary:
- The owner signed every pending gate ("All gates are signed."): G4, G5, EG4, XG1, XG2. Each doc has a dated line.
- The landing still needs its own owner approval (ruling 41: one FR/LG/E/RR landing).
- Integration 02ba8ed1+ holds everything. The runner now stages the T5 candidates, the expansion build and the RR source cache.
- Started at handoff on cut 02ba8ed1, for the next session to collect:
  - FR/LG release_gate_quick rerun (C:/slink-wt/fc-frlg-gate-02ba8ed1.log);
  - RR final cut on the new companion (lane C:/slink-wt/g3-lane3, C:/slink-wt/fc-rr-02ba8ed1.log).
- Remaining cards: EXP-REFUSE (ruling 39) and EMERALD-TOWNS (ruling 40). Then freeze a cut, run all three final cuts, do landing prep, ping Gen 2, and ask the owner for the landing.

## Earlier state (checkpoint 25): HANDOFF. The owner hands coordination of the remaining Gen 3 work to Codex.

**Read first:**
- this section;
- the AGENT_CHECKPOINT in C:/Users/howar/.claude/hooks/slink/RC_MASTER_GUIDE.md (workers gen3-*, emerald-*);
- the register C:/Users/howar/.claude/hooks/slink/WORKTREE_REGISTER.md.

**Integration:** `claude/gen3-integration` in C:/slink-wt/g3-int, head after this doc commit (b091ff27 = code; later commits are receipts/docs only).
- Full unit suite at b091ff27: **13480 passed / 0 failed** (C:/slink-wt/suite-b091ff27.log).
- Env: `source C:/slink-wt/g3-env.sh`.
- NOTHING is on master. Landing needs the owner's explicit approval; ping Gen 2 first (shared server/*.py, lua/core/session.lua and more changed).

**Final cuts:**
- **Emerald @b091ff27: 24/24 PASS** (docs/gen3/probes/fc_SUMMARY_b091ff27_emerald.txt).
- **FR/LG @c04420a9: 42/43.** The only failure was release_gate_quick, from stale FR/LG/E profile.json. That was fixed in ca54bb42 (regenerated; the ABI source sha had moved in the T2 merge).
- **Gate rerun @b091ff27:** 0 failed, but the gate counts 31 UNEXPLAINED SKIPS as failure. All are inputs missing from the lane checkout C:/slink-wt/g3-lane:
  - (a) the T5 private candidate builds patch/build/candidate-{firered,leafgreen}-trade (tests/unit/test_gen3_trade_duo*.py);
  - (b) the expansion build syms .cache/expansion-output/reference/pokeemerald.sym (test_gen3_title_syms_exp.py);
  - (c) the RR source cache from `python tools/fetch_rr_sources.py` (test_gen3_rr_generators.py).
- **NEXT CARD:** stage these via tools/gen3_final_cut.py UNPINNED_INPUTS (same pattern as the RR clean ROM fix 0e10ebd0), or record owner-accepted skips.
  - Then rerun `python tools/gen3_final_cut.py --cut <head> --title frlg --lane C:/slink-wt/g3-lane --master C:/slink-wt/g3-lane-master --rows release_gate_quick`.
  - Ideally run the full FR/LG cut at the final head.

**Merged into integration this session (all live-proven where marked):**
- **T5 native FR/LG trade duo:** 4/4 live PASS in both directions @5eed16cc.
  - Fixes: the held apply_prepare, the baton wait, the hidden-HELLO recovery.
  - Scripts: C:/slink-wt/run_t5native2.sh, run_t5frlg.sh, run_t5lgfr.sh.
- **T2-PUBLISH (Codex Emerald 1d2a9512):** FR/LG/E production UPS + READY 1, and the Emerald native companion (panel/sound/carrier/rival/trade/Match Call).
  - Single-cart production smokes PASS (em-t2/patch/build/t2-publish-live-20260927.json).
  - OMP reviews cx-6db186a8 and cx-38e266e5 were dispositioned by Emerald.
- **RR-ENC-FORMS (FRLG d675eb3f)** and **CLAUSE-LIVE-REST (Emerald-2 2bd8a7eb):** 14 live clause receipts (docs/gen3/research/clause_live_rest_2026-09-27.md).
- **UI-QUAL**, **EXP-X23 (expansion X2+X3)**, and 10 OMP small tasks.

**RR-DURABLE MERGED as 5c8bc45d** (claude/gen3-rr-durable @75b4900b). Read docs/gen3/research/rr_durable_handback.md.
- Live PASS on gen3_rr at source 0c444561: trade_gen3, trade_decline_gen3, native_absent_gen3 (redesigned), plus the live gates test_live_tradescene/setpartymon/enemyparty_route. The branch suite was 12731/0.
- New RR companion UPS: md5 70e7e746e573a2d00df5d3ef41d19d61, sha1 da579690db7d6933a0952a1f490312842793f71a. It must be staged as patch/build/slink_RR.gba in any checkout (g3-int is staged; the old build was kept as slink_RR.gba.old-7a386749).
- On merge the coordinator re-pinned COMPANION_EXTRA_REFS for MOVE_CTRL_THUNK to 0x08379D84.
- The full suite on the merged integration PASSED: **13507 passed / 0 failed** (C:/slink-wt/suite-rrdur-int.log).
- Still owed:
  - (a) an RR final-cut sweep on this head (`--title rr`); the other RR rows' receipts are from the old companion;
  - (b) physical RR reset-between-saves recovery (only unit-proven);
  - (c) radical_red.h still says READY 0 (unused on the ABI1 path);
  - (d) ping Gen 2 (server/*.py changed).
- RR native trade is no longer refused except for an old UPS without the witness.

**Owner rulings 2026-09-27 (answered in chat; these are decisions, NOT XG1/XG2 gate signatures, which still need an explicit "yes"):**
- **38 (expansion shiny, XG2 option C):** record the shinyModifier as a known limit for the reference build now; carrying it (shared state.py/base.py/client) is the FIRST card of X4. No shared server change now.
- **39 (expansion admission):** accept the exp_*.sav SYNTH fixtures and gen3_exp registered-but-unrouted, AND refuse emerald_expansion_28877d73 server-side by name (add it to server/adapters/__init__.py _REFUSED_ROM_TYPES, as crystal_ap is) until it is routed. The duo harness's test-only admission seam must still work, i.e. use a test-only server override too. CARD for Codex.
- **40 (Emerald towns):** fix all six: Rustboro/Roxanne, Fortree/Winona, Littleroot, Oldale, Fallarbor, Verdanturf.
  - File each town's trainers, including gym leaders, under the town itself, sourced from pret, using the same E5-CITYLINK backfill as Mauville in tools/gen_area_map.py.
  - Update test_roxanne, which pins the old route_104 filing, then regenerate area_map/emerald_trainers/gen3_emerald_areas.
  - CARD for Codex.
- **42 (expansion, 2026-09-27): PARALLEL TRACK.** The closeout session also starts the expansion XG3 / data / calc cards in their own lanes (CLOSEOUT_RUNBOOK §2b). Finished work lands unrouted; routing waits for XG3 + calc + data. The FR/LG/E/RR landing does not wait.
- **41 (landing scope):** ONE landing of FR/LG/Emerald/RR together, once the FR/LG gate inputs are staged and the RR final cut passes on the rebuilt companion. The expansion code rides along unrouted, per ruling 39. Ping Gen 2 first; then ask the owner for the landing.

**Owner rulings this session:**
- 36: no phone on FR/LG/RR (Emerald Match Call stays).
- 37: randomized RR is out of this RC (the Manager refuses by name, 0d323677).
- The owner authorized merges as needed ("Just merge what you need").

**Low-priority follow-ups (recorded, not started):**
- EXP-X23 review items 2-6 (see checkpoint 24 below);
- T5 review F5 (a production:true fixture under tests/fixtures/gen3/t5_stale_projection);
- the HUD raw-key nickname fallback in lua/gen3/client.lua (nick_label).

**Worker/peer rules that stay in force** (see memory):
- Codex live threads: Emerald 01a0dec7, Emerald-2 01a0ded3, FRLG 01a0df52. Notes to them go by steer.
- Headless OMP cannot run shell. Verify and commit every OMP delivery yourself.
- Private SLINK_STATE_DIR per emulator run; kill only your own EmuHawk PIDs.
- Receipts bind to their source cut; never relabel them.

## Earlier state (checkpoint 24): wrap-up. Owner asked to finish the RC; the session ended on the owner's 30-minute call.

Integration `claude/gen3-integration` @5e001952 in C:/slink-wt/g3-int.
- The previous head, e588540d, was full-suite GREEN: 13353 passed / 0 failed.
- The final suite on 5e001952 ran at wrap-up; its log is C:/slink-wt/suite-5e001952.log. Check that its EXIT is 0 before anything else.
- Nothing is on master. Landing needs the owner's explicit approval, and Gen 2 must be pinged first: server/state.py, server/manager.py, lua/core/session.lua and more changed.

**MERGED this session:**
- **T5:** native FR/LG trade duo. 4/4 live PASS in both directions at 5eed16cc.
  - Root cause of the flaky non-commit: apply_prepare answered ok=false with "native not authorized" while the native side was briefly busy.
  - The fix holds the prepare for up to prepare_frames.
  - Also merged: the baton wait of 0.5 s → 5 s plus a give-up log (646586fd), and the hidden-HELLO recovery now runs without a native part.
- **RR-ENC-FORMS + C3 (FRLG d675eb3f):**
  - RR wild encounters, names and types all come from the ROM: 81 locations / 3745 slots, names through 1375.
  - The regional-form family is fixed.
- **CLAUSE-LIVE-REST (Emerald-2, 2bd8a7eb):** 14 new live clause receipts. Table: docs/gen3/research/clause_live_rest_2026-09-27.md.
  - Shiny exception, via a disclosed SYNTH PID rekey: FR/LG/RR/E.
  - Pre-ball gate: LG/E/RR.
  - PC release: FR/LG/RR.
  - RR gender/type/species/family.
- **UI-QUAL:** Emerald's Mauville Gym is filed under Mauville City, and there are per-title trainer panel tests.
  - OPEN proposal (not an owner ruling): the same area gap in 6 more Emerald towns (Rustboro/Roxanne, Fortree/Winona, ...), chip task_aba67c79. Ask the owner.
- **10 OMP small tasks:**
  - the RR randomize refusal (ruling 37);
  - HUD player-facing text;
  - the stale wire log;
  - RR poison N/A pinned from ROM;
  - vanilla catalog falsifiers;
  - memorial mask tests;
  - explode B mask pinned;
  - the dead savestate path and the tests/e2e/test_duo.py orphan deleted.

**UPDATE (end of session): T2-PUBLISH 1d2a9512 MERGED as integration c04420a9.** Full suite on c04420a9: C:/slink-wt/suite-c04420a9.log (check EXIT 0). Final cuts STARTED on c04420a9: FR/LG in lane C:/slink-wt/g3-lane (log C:/slink-wt/fc-frlg-c04420a9.log, ~100 min, summary docs/gen3/probes/fc_SUMMARY_c04420a9.txt in the lane). Emerald in lane C:/slink-wt/g3-lane2 (log C:/slink-wt/fc-emerald-c04420a9.log, summary fc_SUMMARY_c04420a9_emerald.txt). Copy the lane receipts into g3-int and commit them; triage any FAIL. RR cut waits on RR-DURABLE. OMP review of EXP-X23 shared files: cx-2ce936ca.

**QUEUE (in order):**
1. **T2-PUBLISH** (Codex Emerald, em-t2 `claude/gen3-emerald-t2` **@1d2a9512**, which already contains integration da089baf and review fixes c8543439): FR/LG/E production UPS + READY, and the Emerald native companion. Emerald UPS sha1 2eef703c...; FR/LG bytes are unchanged. Live PASS at wrap-up: boot/panel/trade/reload; chooser fix (red on the old candidate, green on production); phone events 1/2/3 plus busy/cooldown; locked-device refusal. Its full suite was STILL RUNNING at wrap-up: confirm its exit code 0 before merging.
   - Live PASS set: patch/build/em-live-20260927.json and t2-publish-live-20260927.json.
   - The OMP review findings for trade/save (cx-6db186a8) and Match Call (cx-38e266e5) are fixed per Emerald's report.
   - Get its final sha + suite exit, merge it, rerun the full suite and the citation test.
2. **RR-DURABLE** (Opus subagent, C:/slink-wt/g3-rrdur `claude/gen3-rr-durable`, commits b912c710..f2eb0802): **BLOCKED ON THE OWNER.**
   - The auto-mode classifier denied the worker's `git merge` of a37ebb44 into its branch. The coordinator did NOT run it for the worker.
   - Option (a): the owner runs `git -C C:/slink-wt/g3-rrdur merge --no-ff <integration head>`.
   - Option (b): the owner approves merging claude/gen3-rr-durable into integration after T2, then a fresh worker continues from integration.
   - Remaining work: the Lua RR binding (isolated durable descriptor per Emerald's ruling P1-P4), the UPS rebuild + re-pin, porting 3 live tests off the refused opcodes 16/18/21, the native_absent_gen3 redesign (apply_prepare-based), and the live RR trade/decline/native_absent rows.
3. **EXP-X23** (Opus subagent, C:/slink-wt/g3-exp `claude/gen3-exp-x23` **@1932c787**, base 4fa041bf, full suite 12427/0 at 7c550558): expansion X2+X3 done.
   - Live: faint_cmd, boxsync, whiteout and link_gen3 PASS on gen3_exp. faint_cmd and boxsync must be re-run at the final cut.
   - linked_faint_active is not run on gen3_exp: no in-battle faint plan yet for the expansion battle structs (XG3).
   - Drafts: docs/gen3_emerald/XG1_request_draft.md and XG2_request_draft.md.
   - OWNER DECISIONS (XG2 section 6):
     (1) shinyModifier: A carry it (touches shared state.py, so a Gen 2 re-sweep), B record it as a limit, C B now and A in X4. The worker recommends C.
     (2) accept the exp_*.sav SYNTH fixtures;
     (3) gen3_exp registered but unrouted;
     (4) the second compiler probe as the source of harness facts.
   - It touches the shared lua/gen3 safety/reads/client/entry and server/adapters. Merge after T2, run the full suite, OMP review, ping Gen 2.
   - OMP review cx-2ce936ca: no FR/LG/RR/E behaviour change in the shared hunks. Follow-ups:
     (1) the server routes emerald_expansion_28877d73→gen3_exp (server/adapters/__init__.py:41,88,186,238; pre-existing on integration) while the client refuses it. Decide with the XG1 "registered but unrouted" ruling: refuse server-side like crystal_ap, or route both halves together.
     (2) client.lua BATTLE_MON_MOVES_OFF/PP_OFF are still literals while stride/HP are pack-driven (latent: the expansion has no battle.handoff, so it is unreachable).
     (3) boxes_from_save under-reads the expansion storage tail (fusions, 540 B).
     (4) test_gen3_exp_reads lacks a gen3_rr row.
     (5) tests/fixtures/gen3/README.md:37-38 is stale about rr=True.
     (6) the safety IRQ exception keys on pack.title; key it on pack identity or bios_sha1.
   - Needs gitignored inputs: .cache/expansion-output/reference (the build from hgbox), the .cache/expansion-src junction, and .cache/x1-probe/probe.o.
4. **Final cuts** per title: `python tools/gen3_final_cut.py --cut <sha> --title frlg|rr|emerald --lane C:/slink-wt/g3-lane`.
5. **Landing prep:** refresh `claude/gen3-landing-prep` (C:/slink-wt/rv-land) against master, ping Gen 2, then ONE landing request to the owner.

**Owner rulings:**
- 36: no Soul Link phone on FR/LG/RR (Emerald Match Call stays unless the owner says otherwise).
- 37: randomized RR is out of this RC.

## Earlier state (checkpoint 23): owner "Finish the scope" / "Lets finish this RC"

Integration `claude/gen3-integration` @646586fd in C:/slink-wt/g3-int. The full unit suite at 4fa041bf was 13044 passed / 0 failed. Nothing is on master; landing needs the owner's explicit approval, and Gen 2 must be pinged first (server/lua shared).
Resources (owner): at most 3 subagents; unlimited headless OMP for reviews, tests and small code; Codex threads Emerald 01a0dec7, Emerald-2 01a0ded3 and FRLG 01a0df52, reached by `delivery=steer`.

**Merge order into integration (each: full unit suite + OMP review; live rows where named):**
1. **T5** native FR/LG trade duo: `codex/gen3-t5-fr-duo` @a37ebb44 (C:/slink-wt/g3-t5-fr-duo). Integration 646586fd is already merged into it; targeted tests 1628/0.
   - Before the fix: 3/4 live rows PASS. The one fail, "capability hello not acknowledged", has its root cause fixed in 646586fd (the baton waited 0.5 s; now 5 s plus a log line).
   - Rerun script: C:/slink-wt/run_t5native2.sh; logs C:/slink-wt/t5native*.log. OMP review cx-be726e1a.
2. **RR-ENC-FORMS + C3** (FRLG): `codex/gen3-rr-enc-forms` @d1231c5a.
   - The ROM-authoritative RR encounter catalog: 81 locations / 3745 slots, drift 0.
   - Names through 1375; types converted RR23 -> canonical 18.
   - The RR family generator: 1349 species / 735 edges.
   - Wait for FRLG's full-gate reply (cx-0a61f1b1).
3. **T2-PUBLISH** (Codex Emerald, em-t2 `claude/gen3-emerald-t2`): FR/LG/E production UPS + READY on top of T5.
   - Emerald native PASS set: em-t2/patch/build/em-live-20260927.json.
   - OMP review cx-ec1254e4.
4. **RR-DURABLE** (Opus subagent, C:/slink-wt/g3-rrdur `claude/gen3-rr-durable`): RR save witness, making RR native trade available.
   - Must also fold OMP cx-bfa0a588 F1/F4 into the trade oracle: typed refusal msgbox (no `phone` tag), forbid msgbox on B.
   - Live: trade/trade_decline/native_absent on gen3_rr.
5. **UI-QUAL** (Sonnet, C:/slink-wt/g3-uiq): the Emerald rival by player gender, Mauville Gym area, per-title trainer/upcoming/prep tests; then a coordinator browser check.
6. **EXP-X23** (Opus, C:/slink-wt/g3-exp): expansion X2/X3, then the XG1 request draft. XG2 needs an owner decision on the shinyModifier shared-state change.
7. **CLAUSE-LIVE-REST** (Emerald-2):
   - live rows: shiny exception (O-33 disclosed PID rekey), PC release, pre-ball gate LG/E, RR gender/type;
   - ledger docs/gen3/research/e_parity_ledger_2026-09-27.md on its branch.

**Then:**
- the final cut per title: `python tools/gen3_final_cut.py --cut <sha> --title frlg|rr|emerald --lane C:/slink-wt/g3-lane`;
- refresh the landing-prep branch `claude/gen3-landing-prep` (C:/slink-wt/rv-land) against current master;
- ping Gen 2;
- ask the owner for ONE landing;
- signatures only on the owner's explicit "yes".

**Owner rulings 2026-09-27 (in chat):** (36) "No phone" -- no Soul Link phone on FR/LG/RR (the parity cells are closed as ruled out; Emerald Match Call, already built, pending owner confirmation that it stays); (37) "RR not in scope for rando" -- randomized Radical Red is OUT of this RC (ruling 29 stays for FR/LG/Emerald).
- (a) the Soul Link phone on FR/LG/RR: none has a native phone and ruling 30's companion list has none, so it is treated as Emerald-only (Match Call) unless the owner says otherwise;
- (b) randomized Radical Red: ruling 29 says randomized Gen 3 is in scope, but UPR cannot randomize CFRU. Is it in scope, and from what source?

RR fc at 0e10ebd0 after fixes:
- faint_cmd_clean, linked_faint_active_clean and rr_opcode_gates PASS;
- native_absent FAILs only because RR trade is refused, and turns green with RR-DURABLE;
- whiteout, linked_faint_active and trade/trade_decline PASS in g3-rrfc (merged);
- species_clause and ball_gate RR wait on items 2 and 7.

## Earlier state (checkpoint 22, combined orchestrator)

- Integration `claude/gen3-integration` (C:/slink-wt/g3-int) head 66184e35: full suite 13013 passed / 0 failed. Env: `source C:/slink-wt/g3-env.sh` (now also SLINK_JDK_BIN, SLINK_UPR_JAR, SLINK_EXPANSION_SRC, SLINK_HOST_GCC, SLINK_PRET_EMERALD). pytest.ini keeps tmp_path only for failures (C: filled twice from ~7 GB/run retention).
- Merged since checkpoint 21: T4 server trade contract (+R3/R4), ruling 35 NPC-trade clause retirement (all gens), T3-R5/R6 Emerald client recovery, E-MGR randomizer write domain (+fixes), TG-MULTI, RR-SYNTH + RR NPC trade, E-RAND-CATCH, UI mocks per title, WILD-VANILLA (pret wild tables for clean FR/LG/E), EXPLODE-BIND (FR/LG/E), EMERALD-RIVAL (per-player gender filter), CLAUSE-ROWS-G3 + CLAUSE-FIX, GIFT-EGG-ROWS-G3 (O-15 applied to Gen 3: hatch = gift_daycare capture), calc Prep deep-link race fix, T3-BIND-FR (FR native trade client).
- PHYSICAL PASS today: RR evolve_gen3 + npc_trade_gen3; explode_gen3 FR/LG/E; link_gen3 FR/LG on catch_synth; link_gen3_rand E<->E; gift_gen3 + egg_hatch_gen3 on FR/LG/E/RR; clause rows 17/24; FR native trade DUO (T5, codex/gen3-t5-fr-duo d0fee98a, HARNESS_ONLY selection) trade + decline with cold reloads; companion single-cart (claude/gen3-emerald-t2): FR carrier/panel/sound/rival, LG all five.
- Open: CLAUSE-FIX-2 (Emerald-2; 7 oracle/driver fixes + RR clean trade-unavailability: ABI1 RR companion cannot meet the durable-trade contract, so RR native trade is unavailable on this branch until the RR durable delta; release drains via per-report owed gate); T5-NATIVE-CARRIER (FRLG; bind the real native carrier, FR<->LG pairing, fold review F1 visible-hello latch / F6 queue ready-skip / F7 throttle) — T5 not yet merged into integration; T2 Emerald native adapters + Match Call producer (Codex Emerald); EMERALD-RIVAL-R1 + G3-REZERO parked (Emerald-2, r1-rezero); FR/LG final-cut regression on 66184e35 running (C:/slink-wt/fc-frlg.log).
- Owner-facing notes: RR native trade status (unavailable on branch until delta, master unchanged); O-15 applied to Gen 3 eggs (flagged to owner); ruling 35 recorded.
- Landing: master has the Gen 2 landing 5b6f75eb; scratch merge showed 4 conflicting files (cartridges/manager/randomizer.js/upr_pipeline). Ask the owner for ONE landing after merging master into integration; ping Gen 2 (they said no sweep needed now).

## Earlier state (checkpoint 21)

### CURRENT STATE was (2026-09-27, checkpoint 21, combined orchestrator)

- ONE orchestrator (claude session 30c21a7a) runs FR/LG + RR + Emerald + expansion. Sole ledger: the AGENT_CHECKPOINT in C:/Users/howar/.claude/hooks/slink/RC_MASTER_GUIDE.md (workers gen3-*, emerald-*). Nothing on master (master 5b6f75eb is the Gen 2 landing; no Gen 3 branch is in it).
- **Integration branch `claude/gen3-integration`, worktree `C:/slink-wt/g3-int`**: 17988de4 + claude/gen3-emerald + everything below. Full tests/unit with ROM+pret inputs (`source C:/slink-wt/g3-env.sh`) green at 876df6e1: 11857 passed, 0 failed. Randomized ROMs kept at C:/slink-wt/rand_roms.
- Merged into integration (each independently reviewed; findings fixed or rejected with evidence):
  - Emerald client T3: lifecycle R1-R4 (after_reset restored for possibly-unsaved results; two-client cross-wire; live scene gate), ABI v2 client (card A), packaging, Emerald NPC-trade fix (entry pre-image capture; PHYSICAL PASS docs/gen3/probes/fc_npc_trade_gen3_emerald_T3_R4_eca04eb1.txt).
  - Refused key_change retry (Gen 1/2 parity) in lua/core + pending-alias resolution.
  - Trainer generator: per-title FR/LG learnsets; Emerald trainer table (851 trainers); robustness fixes.
  - Expansion XC4 trainer sets + review fixes.
  - F-7 RR generator pins; RR priority roster regenerated from the pinned sheet (owner ruling 34) with every key fight reachable.
  - FR/LG UPR write-domain audit (110-run isolation test; tutor-compat header-write claim disproved).
  - Natural-play evidence: S-8/S-9/S-11 PASS FR-as-A and LG-as-A; NPC trade key_change ACCEPTED end-to-end on FR/LG; Emerald poison + NPC trade PASS.
- **Not yet merged** (on their branches, in review/fix): randomized server `claude/gen3-rand-fix` (C:/slink-wt/g3-rfix; RF-1..RF-4 done, RF-5 = classify all 28 species bytes + project genderRatio 0x10); Emerald Match Call card C (C:/slink-wt/em-t3); T2 companion producer (C:/slink-wt/em-t2, FR trade producer physically passing at private probe, READY=0).
- Owner rulings added: 33 (UPR fork obedience/evo-gate code patch allowed with wild/starter/static randomization), 34 (RR roster from the current pinned sheet).
- Next: RF-5 -> merge rfix; card C; T2 FR producer -> LG -> Emerald -> RR; T4 server trade contract (from T3 reviews: resolve_trade must reach the client, party_hidden marker, uncertain-token journal on hello); T5 duos; Emerald randomized binding (docs/gen3/research/emerald_rom_tables_facts.md); owner live Emerald session; then ask the owner for ONE landing (merge master into integration first; ping Gen 2).

## Earlier state (2026-09-26, checkpoint 20)

- **READ FIRST NEXT SESSION: owner decision "We will combine the next work"** (2026-09-26). ONE orchestrator runs all remaining Gen 3 work (FR/LG, RR, Emerald and the expansion sub-lane). **Codex FRLG review cx-42eabc05 REJECTED the randomized server half: 2 verified BLOCKERS (refusal bypass on an unreadable or missing report; ability normalisation erases real changes). Fix these first; see the handoff §0a.** Handoff docs: `docs/gen3/HANDOFF_combined_gen3_2026-09-26.md` (this branch, 7d3b8af0) plus `docs/gen3_emerald/HANDOFF_combined_gen3_2026-09-26.md` (claude/gen3-emerald).

- **2-HOUR BLOCK 16:03-18:03 (2026-09-26 evening) -- all on the BRANCH, master untouched (owner rule: no master without approval):**
  - Rulings recorded (G4 §6):
    - 28: FR/LG trainer panels.
    - 29: randomized Gen 3 in the RC.
    - 30: FR/LG companion parity (info panel, sounds, Explode + Rival Swap).
    - 31: randomized envelope, Gen 1 defaults with the Gen 3-only UPR options OPEN.
    - 32: rule randomization refused for the RC; rand with pret-equal tables pairs as clean.
  - FR/LG trainers: 3c2a35c2. UI lane browser check PASS (Brock, rival 3 variants, 351 calc labels).
  - Randomized:
    - FRLG Codex: decoder 24caed3b, Lua collector 5a8033de, held items a24d88ac, R4 duos f9bcb991.
    - Server R1/R2: 44615f4f, ce0258aa, box census a53f942a, default moves 87f3903b, refusal at hello b9cd1bb2, pairing 363782dc.
    - R3 Manager: c7656cdb; review fixes c32a081b.
    - R4 review blockers: 9a2af9e8.
  - Evidence cards:
    - F-6 boot-checks for every fixture: 5929a287.
    - C-6 and R-1/R-2 tests: 6c28d08f.
    - C-3 dashboard: cdf8758c.
    - Ledger updated: c6deca8d.
  - **Pairing with the Emerald lane's T3** (claude/gen3-emerald-t3: lifecycle e8f51695 being FIXED after its review, census f4ec8c85, R0 rom_tables a5469ea3, CR-R1 `rand` admission 637bcd17, CR-R2 hello rom_content e5f8da76):
    - My a53f942a (reports_box_census) and all the randomized server work need T3 on master TOGETHER.
    - Next: when Emerald sends the fixed lifecycle sha, scratch-merge both branches, run the unit suite + the R4 live rows (SLINK_GEN3_RAND_ROMS=<scratchpad>), then ask the owner for ONE landing and ping Gen 2 (server/**, base.py changed).
  - **Queued:**
    - R3 review F3: an FR/LG write-domain audit plus pointer-aware table checks.
    - R3 review F4: in-game trades → key_change with no species-clause re-check (state.py).
    - GBA hello rom_sha1 == file sha1: needs a live check.
    - The contract fingerprint changes when the decoder changes.
    - Altering Cave shows only its first set.
    - R4 evidence-quality items (OMP cx-904adf25 findings 3-6).
    - Gen 1's refused key_change retry, for parity (shared lua/core).
    - test_calc_trainer_sets `_FRLG_ARRAY_RE` swallows arrays (calc lane).
    - Shared slink_fr_battle.State was overwritten by the Emerald T2 lane at 17:27; regenerate before trusting it.
    - A redundant stash entry `gen3-review-fix-redcheck-1790457729` is on the shared stack (content committed in c32a081b; the guard blocks drop).

- **OWNER RULE (2026-09-26, late): all work stays on this branch. NOTHING goes to master (not even a local ff) until the owner approves that specific landing.**
  - Master = 5313d94e. The branch is ahead with rulings 28-30 docs plus whatever lands after.
  - Open cards on the branch:
    - FR/LG trainers (ruling 28): Opus worker.
    - Randomized Gen 3 design (ruling 29): Opus, writes docs/gen3/research/randomized_gen3_design.md.
  - With the Emerald lane: FR/LG + RR trade (27) and FR/LG parity (30: info panel, native sounds, Explode + Rival Swap).

- **LANDED 2026-09-26: the RR fix batch is on LOCAL master 7c14386a (not pushed).**
  - Duos green ×2 on companion c372c428:
    - trade_gen3 and trade_decline_gen3 at 5418c725 (the earlier _RED at 539e0aea was a stale oracle ordering pair, fixed);
    - infopanel_gen3 and infopanel_dex_gen3 at 539e0aea.
  - Pinged Gen 2 (it re-sweeps) and Emerald (it merges master, then starts T2/T3). The Emerald lane now owns every trade file.
  - Open for G5: RR durable trade (T2–T5), then ONE RR frozen-cut re-run.
- (History) RR companion fix batch (owner 2026-09-26 "Fix all three now"):
  - The new RR duos found three companion bugs. `infopanel_gen3` is green ×2 (f78b533a).
  - Fixes:
    - 03b19b71: the SOULLINK START row is placed by menu shape (with Pokédex, Exit-R, page-switch trampoline).
    - 2c553181: the trade-scene names are terminated (the unterminated 10-letter nickname made StringExpandPlaceholders overrun EWRAM); the party chooser goes through RR's ChoosePartyMonByMenuType.
    - 570eb621 + dec5c45c: Overworld Presence is forced off.
  - New companion md5 c372c428 / sha1 7a386749, re-pinned. An independent Opus review ACCEPT-WITH-NITS; nit 5 fixed in 51c2079d.
  - **Next:**
    1. Wait for Gen 2's re-sweep to finish (they asked for no heavy emulator use and no shared-code landing meanwhile).
    2. Run trade_gen3 / trade_decline_gen3 / infopanel_gen3 / infopanel_dex_gen3 ×2 in lane C:/slink-wt/rrduo at the branch head, with the new slink_RR.gba in patch/build.
    3. Land the whole shared-code batch on master in ONE ff and ping Gen 2 Boogaloo (they re-sweep once).
    4. Ping Emerald ('Emerald support planning'): it merges master, then starts T2/T3.
    5. The RR frozen cut runs ONCE, after the Emerald lane's RR durable-trade row is green (T2 rebuilds the RR companion again).
  - **Ruling 27** (FR/LG patched trade IN this RC):
    - Built in the Emerald worktree. T1 design approved: `docs/gen3/research/patched_trade_design.md` + `_bindings.md` on claude/gen3-emerald-trade 5ecc0516, merged d0599417.
    - After my landing, the Emerald lane owns ALL trade files, RR included. The Gen 3 lane reviews and owns the G4/G5/requirements docs.
    - T2 + T4 shared code lands once, with a Gen 2 ping.
    - The §7 PLAN/requirements diff comes to me for review before master.
    - G4 and G5 both wait on T5 receipts (FR↔LG, RR↔RR; E↔E is Emerald's own gate).

- Local master is **615ea688** (Gen 1+2+3 + the docs sweep, NOT pushed).
- Gen 2's evidence is re-pinned 98/98 at CODE_DIGEST e8ca0067. Gen 1 is clean.
- The Gen 3 frozen cut is a2985d5a: FR/LG 43/43, RR 19/19. Post-merge passes are green at a20cd945.
- Since then, test-only changes: f87e007e (a present ROM must be the pinned build) and the item-table fix. No new cut is needed.
- G4/G5 requests: `docs/gen3/G4_request_draft.md`, `docs/gen3/G5_request_draft.md`. Both are **unsigned**, waiting on the owner's RR play session.
- **Docs accuracy sweep DONE (owner 2026-09-26), on master 615ea688:**
  - protocol.md is re-anchored to `lua/gen3/*`. The citation test checks that every cited file exists, that the line is in range, and that no bare `gen3:N` remains.
  - README and REFERENCE: Gen 3 is a RELEASE CANDIDATE, not "Stable". Only pinned carts are admitted; randomized builds are refused. The Gen 2 blocks are Gen 2's own.
  - The requirements ledger is filled: 14 rows DONE, G4/G5 unsigned.
  - TESTING.md's Gen 3 walkthrough is rewritten for the new client.
  - Dated research, reviews and probes carry folder READMEs.
  - Split with Gen1-Collab2: they own shared-*.md, shared_runtime.md and copilot-instructions.md.
- **Owner-facing gaps found by the sweep:**
  - (1) RR native trade and the info panel have no automated duo on the new client. The owner's play session is the only end-to-end evidence (flagged in the G5 request).
  - (2) Overworld Presence ON disables the PC trade NPC, and no ghost exists. The fix is a `server/manager.py` toggle, held for the owner's decision and a Gen 2 batch (`docs/gen3/TODO.md`).
  - (3) Ledger open rows: S-8/9/11/12, W-2 (RR checkpoint re-qualification after C4-SAVE), W-6, C-3, C-6, F-6/F-7, R-1/R-2 box-slot decode.
- Then P6: the requirements rows, 2 reviews, then G6 (the owner tags and ships).

## CHECKPOINT 20 (2026-09-26): Gen 3 landed on LOCAL master (not pushed); resume here

- **Owner ruling 26: "Lets just merge it."** Master (Gen 2 merged at 062977a9) was merged into the Gen 3 line in the isolated worktree `.claude/worktrees/gen3-land` (3da0615b, plus a9ad03d3 for the docs). Local master was then fast-forwarded: a9ad03d3 → 280c1af7 → **a20cd945**.
  - Verified master against the merge in the same unprovisioned env: only 1 new failure, an env artifact (the stale root slink_RR.gba). The Gen 1 gate was identical at both; Gen 2's lanes were identical except 99 STALE digest gaps (expected; Gen 2 re-sweeps).
  - The slink-adapter-guard review passed.
- **Post-merge fixes:**
  - 280c1af7: test_gen3_routes/tutorial_states no longer count parents[2] (IndexError on the main checkout; Gen1-Collab2 found it). A repo-wide grep found no other instance.
  - a20cd945: check_release_zip now expects lua/gen2 members (Gen 2's _LUA_GEN2), plus a coverage test.
  - 794b789c: the LG fixture_qualify test stubs its ROM lookup; rr_harness_syms.load accepts only a pin-matching RR build. A class check ran every Gen 3 unit test in an unprovisioned worktree: no Gen 3 failures. Master = 794b789c.
  - b6bd8f2b (Emerald-lane cards): PC.mode reaches rows >= 2, and a playlib leg whose run/check raises is finished by name. Master = b6bd8f2b.
  - Gen 2 then merged its unprovisioned-source fix: master = **88c2c1ac** (Gen 2 moved it, not pushed). The Gen 3 branch merged it (ba9a9159). `pytest tests/unit --collect-only` now collects 14201 with no error on a checkout without Gen 2 builds. Gen 2's re-sweep runs at 7ba4d552 (CODE_DIGEST e8ca0067, the same as master).
- **Post-merge passes on master:**
  - FR/LG: a9ad03d3 shards 1 (13/13) and 2 (29/30, zip_check), then the zip rows at a20cd945 3/3. **All green.**
  - RR: a9ad03d3 18/19 (rr_zip_check), then the zip rows at a20cd945 3/3. **All green.**
- **Other lanes:**
  - Gen 1: verified clean by Gen1-Collab2 at 062977a9, a9ad03d3 and 280c1af7 (1659 passed, 0 failed).
  - Gen 2: its loader fix (87779879, SourceUnavailable becomes a named skip) merges next. Its 98-cell re-sweep runs on the merged master.
  - Emerald: branch claude/gen3-emerald merged a9ad03d3; E3 has approved-direction items pending.
- **Still open:**
  - The owner's G4/G5 play session and signature. Ruling 26 landed the code first, but the release is still gated.
  - P6: requirements rows, docs and release notes, 2 reviews, then G6 (the owner tags and ships). Nothing is pushed.

## CHECKPOINT 19 (2026-09-25, 1.5-hour block): resume here

Owner rules this block: at most 3 subagents (Sonnet preferred, Opus as needed); headless OMP for reviews, tests and small code the coordinator reviews.
- **FROZEN CUT `870e5e5d`** (supersedes 382703b3 and c0f6101b):
  - FR/LG pass: `--carry --shard 1/2` on gen3-lane-clean and `--shard 2/2` on gen3-lane-2, both with `--stop-at 2026-09-25T12:53Z`.
  - To finish: re-run the same commands with `--resume` at 870e5e5d; they skip rows that already PASSed. Then `--merge-summary` writes `fc_SUMMARY_870e5e5d.txt`.
  - RR pass: `--cut 870e5e5d --title rr` writes `fc_SUMMARY_870e5e5d_rr.txt`.
  - Any code change means a new cut, so docs-only commits only.
- **Why the cut moved** (the c0f6101b receipts are kept as evidence in ef36ef8c):
  - **(a0) No pending counter on the HUD** (870e5e5d, owner: "None of that needs to be there. Look at how Gen1 does it. Player doesnt need a pend counter"): holds are logged to the console once per hold, never drawn.
  - **(a) HUD code references** (owner report: code on the HUD while memorials are held). Lua 5.4's assert put "…/lua/gen3/safety.lua:105:" into `SLink held: memorialize … (reason)`. `lua/core/session.lua` report_holds now strips the source position and reads identifiers as words (fca17782, red test).
  - **(b) Trainer probe states.** The runner never built them (`slink_pretrainer`/`slink_prefaint`), so checkpoint_firered failed in lane 2 with "state missing". The 157e1ef7 rehearsal had passed those probes only on stale copies in lane 1. `states_<title>_trainer` rows were added (382703b3).
  - c0f6101b results: FR/LG shard 1 14/14 (item6 and the zip chain included); shard 2 17/18 before it was stopped; RR 16/17. The RR failure, linked_faint_active_clean, was the driver running out of no-damage PP at turn 31 with the lead at 1 HP (RNG). If it fails again at 382703b3, fix `ctx.lose_active` in lua/tests/duo/duo_gen3_main.lua: for example re-hunt when status PP runs low, or prefer the highest-PP status move.
- **Master merged:** local master 96ae536d, via the scratch branch claude/gen3-master-sync 597c52d2, merged as e33b03b1 (Opus G4-MASTER-SYNC).
  - 9 conflicts were resolved by intent; the full list is in the merge message.
  - test_protocol_citations was repaired, and one drift was re-anchored in c0f6101b.
  - Full unit suite: 7074 passed. test_gen1_trade_patch fails only in the worktree, which has no .cache/pret/pokered; lanes provision it.
  - Merge resolution reviewed CLEAN by 2 Sonnet reviewers (no dropped hunks). The OMP cx-cd3f4189/cx-4334eae0/cx-c36d9987 runs timed out.
  - The scratch dir C:/slink-wt/g3sync is unregistered but was locked by a process; delete it once free.
- **RR whiteout:** the START-menu control now requires sStartMenuWindowId (0x0203ABE0, verified byte-identical on both RR ROMs) plus field_controls_locked. RR's marker is `start_menu`, and e2e_duo queues the probe by the per-title marker. PASS at fca70bb2 (01e50258, fca70bb2, a30e15b3).
- **Rival Team Swap:** it was off by one. It matched the trainer BEFORE each rival: gTrainers[325] Daisuke, [738] Lance, per the RR ROM. Fixed with `tid + 1` in e729abdb; OMP cx-5e891395 found nothing. The UI lane confirmed the calc already uses runtime ids.
- **RR zip boot:** real now. `zip_boot --title radical_red` boots the companion as slink_RR.gba with rr_town.sav; the client line reads `gen3_rr/radical_red (companion by hash)`, and the server logs `hello rom=firered_rr`. PASS at 58a8951f.
  - RR rows are named rr_zip_build / rr_zip_check / zip_boot_radicalred, with summary `_rr` (c0e1e98e, OMP cx-f570e611).
- **G5 gaps** (OMP cx-6827201a, verified): owner decisions for G5.
  1. Full RR clean coverage: only the two mixed clean-side rows exist.
  2. A qualifying rival swap with enemy-party readback: rival_swap is only a negative control.
  3. Opcode gates: 26 live + 12 deferred vs PLAN's 39.
  4. No explicit anchor/md5/grep/write-guard/control receipts in the RR plan.
  The G5 draft status text is stale: it still says "no RR runner rows / no zip receipt".
- **Results at the frozen cut 870e5e5d:**
  - FR/LG shard 1: 13/13 PASS (probe_gates included). Shard 2: 29/30. Every row PASSed or was CACHED except `release_gate_quick`, which was STOPPED by --stop-at before it ran; it is not a failure. FR/LG therefore stands at 42/43 with only the quick gate left.
  - Next: `python tools/gen3_final_cut.py --cut 870e5e5d --shard 2/2 --resume --lane .claude/worktrees/gen3-lane-2`. If the STOPPED receipt `fc_release_gate_quick_870e5e5d.txt` blocks the re-run, move it aside first. Then `--merge-summary`.
  - RR `--title rr`: 16/17 (`fc_SUMMARY_870e5e5d_rr.txt`). rr_opcode_gates PASS and the RR zip build/check/boot PASS.
  - The one RR FAIL, `linked_faint_active_clean_gen3_rr_as_a`, failed IDENTICALLY at c0f6101b and at 870e5e5d: "no no-damage move with PP (turn 31, hp 1, hunts 1)". The battle replays deterministically from the fixture, so this is a real driver defect, not chance.
  - FIX NEXT (red first: the receipt is the red): in `ctx.lose_active` (lua/tests/duo/duo_gen3_main.lua about 1307-1350), when the status moves are out of PP and the lead is at low HP, the foe needs only one more hit. Options, in the order to try them:
    1. keep the lead in with a no-op action, e.g. switch-in-place or struggle via the pack's move table, if one exists;
    2. choose FIGHT with the weakest damaging move only when the foe's HP exceeds that move's maximum damage;
    3. rebuild the clean-side fixture with more status PP.
    Check the clean-side fixture's lead first: which moves and PP (rr_battle*.sav clean side).
- **OWNER on the G5 gaps (2026-09-25):** "We don't need full test coverage for RR but we need a decent amount." The coordinator proposed the following, pending the owner's confirmation:
  1. Clean coverage: add ONE clean-side basic link+faint row beside native_absent and linked_faint_active_clean (after the driver fix), and accept that as sufficient.
  2. Rival swap: PRODUCE one qualifying row, a real swap plus enemy-party readback.
  3. Opcode gates: sign the 12 deferred gates as a limit (26 live).
  4. Per-item receipts: accept the existing unit/model evidence (pins, write ownership, native control unit tests).
  Work: the clean-row driver fix, 1 clean row, 1 rival row, then re-freeze and run both passes.
- **Ruling 25 work DONE** (68e6191f is the ruling):
  - Clean coverage:
    - linked_faint_active_clean_gen3 fixed. The lose_active fallback now excludes self-damage moves and only re-hunts on a WON outcome (77115d02, bc733fd0).
    - New row faint_cmd_clean_gen3 (a=companion, b=clean; the oracle proves ROM provenance by hash). Both PASS live (b71815d2). OMP cx-39175521: all 4 findings fixed.
  - Rival Team Swap: qualifying row rival_swap_real_gen3 with cached-native rr_rival.sav (Route 22 (34,6), trainer 331). Merged c566e808; PASS live at 7fddd3eb; the negative control still PASSes.
    - Client-only product fix: the RR companion pre-announces when gTrainerBattleOpponent_A turns nonzero on the field, stages the swap, and posts it in the patch's W1 window. Success requires the readback to reach the enemy battler.
    - Reviews: Opus (4) + OMP cx-3a69802a (9) folded in. OMP F1 (level-guarded rematch announce) was declined because it would re-announce the last trainer after every battle; RR rival ids are distinct.
  - Integration: faint_cmd_clean_gen3 pinned in the RR lists (a2985d5a). Gen 3 unit suites: 3708 passed.
- **FROZEN CUT a2985d5a: FR/LG (G4) 43/43 PASS** (`fc_SUMMARY_a2985d5a.txt`) **and RR (G5) 19/19 PASS** (`fc_SUMMARY_a2985d5a_rr.txt`), receipts 622aa7f5. Lane 2's first release_gate_quick FAIL was stale CRLF on LF-pinned files (a lane defect; kept as `fc_release_gate_quick_a2985d5a_LANE2_CRLF.txt`). QUEUE: make the runner's lane provisioning rewrite eol-pinned files whose working copy is `w/crlf`.
- **Gen 1 non-regression: PASS** (accepted by Gen1-Collab2). `verify_gen1_release.py --quick` at a2985d5a in gen3-lane-clean reported 0 test failures (7177 passed). The pure/overlay/yellow artifacts copied from root are sha1-identical to the pins. Every remaining skip is a missing local input: clean Blue/Yellow dumps, arm-gcc, pokegold, .cache/purergb{,-overlay} poke*.gbc, and test_gen1_trade_patch, which master already fixed. After the Gen 3 merge to master, ping Gen1-Collab2 to re-run the gate on master.
- **PRE-RELEASE FIX QUEUE** (after G4/G5 are signed, before G6; not done now, so the frozen cut doesn't move):
  1. DONE 5f050857 (owner 2026-09-25: "Just fix it. No re run."): the vanilla FR/LG item table now names exactly the Gen 3 ids from pret. This display-only fix sits on top of the frozen cut a2985d5a without a re-run. Emerald lane told.
  2. The runner's lane provisioning should rewrite eol-pinned files whose working copy is w/crlf.
- **Emerald E3 (approved direction, the grant comes with the diff):** STATE_ACTION_CONFIRMED_STANDBY comes from the pack (Emerald = 4); SE wire ids stay FR numbering and the client maps them per pack (Emerald's songs.h renumbers 25/26/95 to 31/32/102); GIFT_AREAS becomes a pack field. FR/LG/RR stay byte-identical, and a missing field fails closed.
- **Emerald lane** (session "Emerald support planning", branch claude/gen3-emerald off a2985d5a): approved to make additive title rows in the gen3 generators/codec/fixtures/title_syms, keeping FRLG/RR --check byte-identical. Ruling 24 stands until the port is signed.
- **Gen 2 is merged into LOCAL master** (062977a9, not pushed). `git merge-tree` of this branch against it shows about 20 conflicted files (server.py, adapters/__init__.py, slink.lua, game_detect.lua, memory_gba/nds.lua, e2e_duo.py, protocol.md, .gitattributes, gen1 sfx receipts, several tests). Sequence (agreed with Gen 2):
  1. The owner plays and signs G4/G5 on a2985d5a (+5f050857).
  2. Merge master into this branch in a scratch worktree (Opus, by intent), then 2 independent reviews.
  3. Re-run the FR/LG and RR passes plus the Gen 1 gate on the merged tree.
  4. Merge Gen 3 → master with the owner's say-so.
  - **Gen 2 hunks that must WIN in step 2** (Gen 2 Boogaloo, each test-pinned):
    - server.py:
      (1) the hello transaction in _dispatch: stage, apply, then _rollback_hello on a refusal, `_rejected`, or any exception (test_server_hello_transaction.py);
      (2) the adapter is rebuilt from the FULL rom_type while it is uncommitted, and committed only on an accepted hello;
      (3) _reset_connection_and_display_state() is shared by /api/reset and handle_debug_rollback, and /api/reset clears connected_players;
      (4) adapter_for(pid) on every per-player read (test_gen2_cross_title.py);
      (5) _bind_player_adapter runs after the artifact_kind commit, and set_artifact_kind is applied to the bound adapters.
    - state.py: KEY-SCOPE-5 (test_state_key_scope, test_state_key_change_ack).
    - protocol.md: the Gen 2 rows.
    - .gitattributes: Gen 2's eol=lf rules.
    - gen1 sfx receipts: take master's (f5001c5e).
    - Gen 3's intent wins on slink.lua's GBA branch.
  - **Cross-lane cost:** Gen 2's CODE_DIGEST covers lua/*.lua, lua/core/**, server/**/*.py and data/games/gen2_*/**. The Gen 3 merge will change it, so run `python tools/verify_gen2_release.py --lane release-evidence` afterwards. If it's stale, Gen 2 re-sweeps (about 2 hours). Also run the full tests/unit and Gen 2's no-emulator lanes (fixtures, duo-pairs, live-gates, live-trade-gates, live-new-gates).
- **Master is 3b41a397** (Gen 2 moved it, not pushed): Gen 2's 98/98 receipts are re-pinned at digest e8ca0067 after the Gen 3 land, with no Gen 3 regression in Gen 2's paths. The Gen 3 branch merged it (411de100).
- **RULE from Gen 2:** any Gen 3 change to lua/*.lua, lua/core/** or server/**/*.py stales every Gen 2 receipt (about a 2-hour re-sweep). BATCH shared-code changes and ping Gen 2 Boogaloo when they land. Gen 3-only paths (lua/gen3/**, data/games/gen3_*, Gen 3 tests and tools) are free.
- **Cross-lane merge plan** (settled with Gen1-Collab2 and Gen 2 Boogaloo, 2026-09-25):
  - Order: Gen 1 → Gen 2 → Gen 3. Gen 3 merges only after G4+G5 are signed (ruling 22).
  - pairing_kind (Gen 2 644b3b8f = Gen 3 80261f39) is identical on both sides.
  - server/adapters/__init__.py: Gen 2's side is additive (unrouted_rom_type_reason, persisted_migration_refusal, foundation_for_rom_type, adapter_class_for_rom_type, plus the Gen 2 entries); keep both sets.
  - gen3_frlge.py is Gen 3's.
  - Re-run `git merge-tree HEAD master` after Gen 2 lands.
  - Gen 1 fast gate: run `python tools/verify_gen1_release.py --quick` on this branch BEFORE and AFTER the master merge (9/9 lanes green on master 1b26082f). Artifact recipes are in Gen1-Collab2's note: PureGreen = clean BLUE + the pinned bps (tools/apply_bps.py --expect-sha1 fe4c63a6...), the pure overlays via patch/tools/make_ups.py ups_apply, and the UPR fork via `tools/build_upr_fork.py --bootstrap`. Report any Gen 1 red to Gen1-Collab2; it's theirs to fix. Don't run it while live lanes are busy.
  - Against master d97c8a3b (calc lane: calc_profile/calc_nature/calc_name in gen3_frlge.py, calc_names_vanilla.json; gen3_codec.py arrives byte-identical from c0f6101b), the only conflict is docs/protocol.md citation line numbers. Re-anchor them and run test_protocol_citations.
  - Gen 1 took 48709f39 (the sfx gate case-A fix plus receipts).
  - Master since 96ae536d also has: the ruff exclude, the purergb .sym LF fix, the ROM-scan ctime key, test_gen1_trade_patch reading archive/gen1/rc, and the board/connection_state/CSS work.
- **Merge review:** two Sonnet reviews found no dropped hunks (server.py + gen3_frlge.py; manager/html/make_release/REFERENCE/gen1 client). The three OMP reviews of the merge timed out on the diff size.
- **NEXT:**
  1. Fix the RR clean-row driver, then add the clean link+faint row and the qualifying rival-swap row (per the owner's G5 direction above).
  2. Re-freeze the cut and run the FR/LG pass (sharded) plus `--title rr`.
  3. The merge review is settled: 2 Sonnet reviews, clean.
  4. Fill in `<<FINAL_CUT_SHA>>` = 870e5e5d and the tables, refresh the G5 status, and put the G4 request plus the G5 gap decisions to the owner.

## CHECKPOINT 18 (2026-09-25, 1-hour block): resume here

Owner rules this block: at most 3 subagents (Sonnet preferred, Opus only if needed); headless OMP for reviews, tests and small code the coordinator reviews, never implicitly trusted. Rulings 22-24 stand.
- **FR/LG G4 dress rehearsal at 157e1ef7** (lane 1, `fc_*_157e1ef7.txt`, 4247835d):
  - all 41 rows PASS once rejudged. The runner judged 34/41; the 7 "FAIL skipped" rows were its classifier matching `saves=0 skipped (no_save)`, fixed in 160bd75a.
  - It is NOT the frozen cut, and its duo rows won't carry: 58f5c684 and later changed tools/e2e_duo.py and lua/tests/duo/**.
- **Harness:**
  - duo poll 2.0 s → 0.2 s (157e1ef7);
  - torn-read hardening: complete receipt lines only, events.json retry (58f5c684, OMP cx-aa9c1052).
- **RR whiteout_gen3 PASS at 1321bbdb** (lane 2, `rr_whiteout_gen3_rr_as_a_1321bbdb.txt`), so the RR battery is 13/13 (12 qualifying + the rival_swap control). Three fixes:
  - an RR-only follower object (graphics id 20) locking the field at the Center door, from the live trace (eb03c21a); hardened after OMP cx-84088887 in 23f7cddc (witnessed recovery, battles through handle_encounter, battles=false honoured, executable fake-world tests, an RR center_predicates test);
  - center_state dereferenced RR's literal `pokemon_storage_base` (9598a4e5);
  - RR's nurse (script 0x0904C64B) is a silent quick-heal with no multichoice, so on RR the negative control holds on the START menu (`field_controls_locked`, 600 frames, attempted=0), in 89caeb0e/74589e3f/1321bbdb (OMP review cx-6c92f636 pending).
  - Re-run at a8b60954 (hardened follow) PASS: `rr_whiteout_gen3_rr_as_a_a8b60954.txt`.
- **Runner `--title rr`** (68f5e3f6 + 769a4251, OMP cx-42592031):
  - 13 RR duo rows, derived from `scenarios_for`, plus `rr_opcode_gates` (own_verdict) and a TODO RR zip-boot row that FAILs;
  - RR rows are NEVER carried until row_inputs hashes the RR ROMs, fixtures and gate states.
  - OPEN: RR clean-ROM provisioning, gate-state pins, the RR zip-boot implementation.
- **G4/G5 drafts** (c524cc2d, e0a1c40e, ba3b4d2c; OMP FACT_CHECK cx-87648b5e verified):
  - G5 restores RR clean coverage rows and the RR zip boot as OPEN (PLAN:207/306);
  - the count reads 11 qualifying PASS + 1 control + 1 pending;
  - placeholders `<<FINAL_CUT_SHA>>`, `<<FINAL_CUT_TABLE>>` and `<<PENDING: whiteout_gen3>>` are left for the coordinator.
- **HUD (owner: "The way Gen1/2 do it is how I want"):**
  - master's GB pixel-font commits were ported onto this branch (16d9ee7e; content-identical to master);
  - the shared default now draws the fceux pixel font on the 160px GBA screen too (f1cc6038). NDS keeps Courier.
  - Screenshots are from card HUD-SHOT-GEN3. Master itself does not have f1cc6038 yet.
- **Fake-peer bystander rows** (OMP cx-2bbc6d90, verified): under the strict rule no Gen 3 row qualifies; center_controls and save_then_write only if the owner accepts a setup-only B party read. Owner question.
- **Queue:**
  - UI-lane old-client survey: the RR panel's Badges row read a count only the deleted client set (0/8), fixed in 17608b51. Remove the now-unfed `status` handler (state.py :339-340, :520-528, SoulLinkState.player_badges :288). Keep the ghost_pos relay for the post-RC ghost;
  - HUD: the UI lane's banner-below-wrapped-prompt fix is here as bc1ca258 (master a9bdce38). The GBA pixel font is on local master as 66981144 (not pushed);
  - MERGE NOTE: the UI lane is landing an RR-to-calc name table on master (owner-approved; OMP cx-6cc640f2): data/games/gen3_frlge/calc_names.json, `calc_name()` in server/adapters/base.py plus gen3_frlge.py, server calc DTO, and gen_rr_priority_trainers.py. At merge, decide whether it moves to data/games/gen3_rr/. Rival sets are keyed from trainer_battle_start's trainer_id;
  - Local master is now d3486463, not pushed (UI lane): calc names, enemy_party sanitised at intake, sprite_html regenerated, /api/reset keeps the adapter, manager lifecycle locks, a11y templates; calc/ needs `npm run build`. MERGE master into this branch BEFORE freezing the cut, so the final pass covers it; server.py overlaps with 17608b51.
  - From the UI lane, for this lane: a possible off-by-one in `rival_trainer_ids()` (Rival Team Swap), and Leech Fang / Metal Bash have no calc entry. Verify both against the RR ROM;
  - the inject_link lost-response retry (independent of the poll rate);
  - the stale RR-only block comment in tools/e2e_duo.py (explode is no longer a control);
  - gSpecialVar_Result: OMP cx-72da0fae (verified) found the cancel latch samples only after the 16-frame `G.tap`, so "overwritten the same frame" is unproven. Next: sample during the tap, or arm a write watchpoint on 0x020370D0 before B;
  - fill the ALLOWED_SKIPS mega reason, or leave it (mega is excluded from `--title rr`).
- **NEXT:**
  1. OMP cx-6c92f636 (verified; no product blocker). Two follow-ups:
     - F1: the RR hold treats any `field_controls_locked` as "START opened". Also require `start_menu_open()` (sStartMenuWindowId, gen3_boot_check.lua:55-67), after verifying that 0x0203ABE0 holds on RR. Add a Lua unit case: swallowed Start taps, a non-menu lock rejected.
     - F2: the RR marker still reads `CONTROL_LIVE/REFUSED nurse`. Rename it to `start_menu` on RR, with the e2e_duo oracle.
     Re-run RR whiteout live after both.
  2. Freeze a cut and run `gen3_final_cut.py --cut <sha> --carry` (FR/LG, sharded over both lanes), then `--title rr`.
  3. Fill in the G4/G5 placeholders and put the requests to the owner.

## CHECKPOINT 17 (2026-09-24): PAUSE at the owner's request — resume here

The tree is clean at HEAD (see git log; 62496988 is the rehearsal receipts). Nothing is in flight. Both lanes are free and clean: `.claude/worktrees/gen3-lane-clean` and `gen3-lane-2`, the latter added today (owner opened a 2nd lane). Owner rules this block:
- subagents Haiku/Sonnet/Opus, as many as manageable;
- **OMP for reviews only** (no OMP code);
- no Codex;
- nothing is released until G4+G5 are both done (ruling 22).

- **Rulings 22-24** are in G4_request_draft §6:
  - 22: no release until everything is done;
  - 23: RR CPU irq_entry;
  - 24: C5-6 archives the old client and drops Emerald/AP.
- **RR on the new client, live** (lane 2, receipts in docs/gen3/probes/rr_* and ph_*_rr_*): **12/13 PASS**:
  - all 5 P+H rows (wild, clean, L-hammer, whiteout, Explode+H), plus faint_cmd, reconnect, native_absent, link, deadzone and boxsync;
  - rival_swap as a negative control (stale_battle_id);
  - R5 (mega) is a signed limit (ruling 20).
  - **OPEN: whiteout_gen3 on RR** fails leaving the Viridian Center: "step Left stalled at (25,27)" at c23a8f46. Two static path fixes didn't explain it; it needs a LIVE trace of player/object events at the door exit on RR.
- **FR/LG:**
  - P+H rows 8/8 PASS (6d6227c6); the trainer rows now boot the cached-native trainer fixtures, 80 s/67 s instead of 23-42 min (248d6ee9);
  - RR opcode gates 26/26 (0995a82e).
- **C5-6 done:**
  - old client deleted (tag archive/gen3-old-client = f9171b9a);
  - RR routed to lua/gen3;
  - Emerald/AP refused by name;
  - duo harness rename gen3_rr_new → gen3_rr (ac448144);
  - admission hardened (405ef88b).
- **Reviews:** today's code had independent OMP reviews (verified; outcomes recorded) plus R1/R2/F1. Fixes landed:
  - stat-stage switch coherence, eb1b5c6b;
  - CPU harden, 3fa789da/c29f3cf8;
  - runner hardening, c737db8c;
  - RR oracles, cc6ec42a/156a521f/e99c3760.
- **Final-cut runner (tools/gen3_final_cut.py):**
  - carry, shard and cache are hardened;
  - the rehearsals pass: zip chain, probe_gates, bootcheck 8/8, release_gate_quick 2629/0 skipped (62496988);
  - lane fixes: pinned-input copy, .cache/pret, index refresh; .gitattributes pins LF for the Gen 3 packs and pret files.
- **Emulator time:**
  - the trainer fixtures were the big win;
  - rendering/sound off (5206fc8a) made no measurable difference; the bottleneck is emulation at ~700-800 fps, the 2.5 s EmuHawk launch, and the duo harness's 2.0 s wait_for poll;
  - queued: poll 2.0 s → 0.2 s in tools/e2e_duo.py (about -2 s/row, W23 measured), plus fake-peer bystander rows (docs/gen3/research/emu_time_reduction_2026-09-24.md, c9ae7313; its minute estimates for the P+H rows are stale, since they measure 40-70 s live).
- **Open qualifiers (recorded):**
  - RR gSpecialVar_Result 127 is overwritten the same frame (suspect a CFRU writer), so RR uses a looser PC-exit check;
  - an AP build with every pinned anchor intact would be admitted (by design, for randomizers);
  - post-battle stage chip stale ≤30 frames (cosmetic).
- **NEXT:**
  1. RR whiteout live diagnosis → 13/13.
  2. The e2e_duo poll interval.
  3. Freeze a cut and run `python tools/gen3_final_cut.py --cut <sha> --carry --shard 1/2 --lane .claude/worktrees/gen3-lane-clean`, `--shard 2/2 --lane .claude/worktrees/gen3-lane-2`, then `--merge-summary`.
  4. G4+G5 requests for the owner.

## CHECKPOINT 16 (2026-09-24): owner check-in after a 3-hour work block — resume here

Owner session rules for this block: up to 5 subagents (Haiku/Sonnet/Opus/Fable), no Codex/OMP, a SECOND emulator lane opened (`.claude/worktrees/gen3-lane-2`), "synth work" allowed (model/diff evidence instead of slow emulator re-runs). Nothing is released until G4+G5 are both done (ruling 22).
- **Owner rulings 15-23** are in `docs/gen3/G4_request_draft.md` §6 (f6d503f4, 42df5f61, 6ab91745):
  - 16: the P hand-off on every title;
  - 17: the RR lost-ball window is a limit;
  - 18: the DREW edge is accepted;
  - 19: RR Explode gets the hand-off;
  - 20: R5 (mega) is a limit;
  - 21: the game-over whiteout is accepted;
  - 22: no release until everything is done;
  - 23: RR's CPU check accepts the IRQ entry from the BIOS halt.
- **P+H (the in-battle faint with no press) is built on all titles:** 9719b519, 274fa486, 375cb963, cdc571f1, fixes 4a91daeb/9e227101. RR Explode+H is 904c134c, with M4/M5 in e9193bb2. Reviews: R1 26c7e281 and F1 40b863bd (Fable; the independent review of 904c134c, with its BLOCKER moot by ruling 22).
- **FR/LG live:** all 8 P+H rows PASS (A1, A2, whiteout, trainer, on both title orders), 6d6227c6. They are REHEARSED: the final-cut pass re-takes them, and the runner currently carries nothing because the client changed afterwards.
- **RR:**
  - the companion is rebuilt (998666b6, md5 6cf77ba4) and the opcode gates are ported (gatelib 2aad8e2a..dfd8a96d, review R2 2ebfdf1f);
  - **26/26 RR gates PASS live** (0995a82e), and the ported mkstate states rebuild live (95436847);
  - the rr_battle2 two-mon fixture is built (80913bdf);
  - **RR hello now works** (e9193bb2). The RR P+H rows still stop in the carrier: A's FIGHT press is not taken by CFRU's action menu, and the carrier's CPU-check copy lacks `irq_entry` (c12211c1). **W2 has this in flight** (card G5-RR-CARRIER-FIX; uncommitted edits in lua/tests/duo/duo_gen3_main.lua).
- **Item 6:** DONE, no regression against master (b0483efe).
- **Final-cut runner:** `tools/gen3_final_cut.py`, with `--carry`, `--shard i/n --lane` and `--merge-summary` (2aa46b8a, d9a08f5b). Runbook §5/§11 match it (7aa0aa47).
- **C5-6 prep:**
  - the plan is 6ed149b0 (35 dependents);
  - mkstate is ported (01b1fe56);
  - stat stages are read and wired in the new client (e3221685; a real feature gap);
  - the profile native block comes from handlers.c (00e76c5b);
  - C5-6 lands with the RR cutover.
- **Tools:** mkstates `--saveram` targets BizHawk's real name (236ee593) and now backs up the player's save first (95461a92). The broken shared ref `codex/gen2-foundation (1)` was removed; it pointed at an ancestor, so nothing was lost.
- **NEXT:**
  1. Land W2's RR carrier fix, then re-run RR R4, Explode and R1-R3 on a lane.
  2. Freeze a cut and run the final pass on BOTH lanes: `python tools/gen3_final_cut.py --cut <sha> --carry --shard 1/2 --lane .claude/worktrees/gen3-lane-clean`, then `--shard 2/2 --lane .claude/worktrees/gen3-lane-2`, then `--merge-summary`.
  3. Execute C5-6 with the RR cutover.
- **Owner decision pending:** C5-6 deleting the old client orphans Emerald and Archipelago FRLG, which PLAN §10 lists as "deferred" (plan doc risk 1).
- **Lane hygiene:** the worktree is shared by concurrent workers. Commit by explicit path only; never `git commit -a` or `git reset`.

## CHECKPOINT 15 (2026-09-23): BREAK (owner) — resume here

Tree clean at HEAD (see git log; cffe0a25 is the last receipt). Nothing in flight: no subagent, Codex/OMP told to stop, emulator lane free, `.claude/worktrees/gen3-lane-clean` detached at 2bee46f2 and verified clean.
- **G4 now:**
  - items 1, 2, 2a, 3 and the §3.2 save rows are PASS on both titles;
  - **2b is PASS**: probe rows f58c8dd5, A1 c13cf7c7, A2 89442a97, T2 cffe0a25; D1-D5/N3/U3 are signed limits;
  - all five owner scope decisions a-e are settled (G4 draft §6, 21ef6143/22cb85a8).
  Remaining: the P carrier update (below), the final-cut re-takes (docs/gen3/G4_final_cut_runbook.md + tools/gen3_probe_receipt.py), item 6 route-differential, and the owner's Manager run.
- **Mechanism P** (owner "A": the active battler faints in battle via the engine's Perish KO on FR/LG singles):
  - built 1b3943e3; the Explode revert is 39bcc4f8, since the owner did not want Explode Mode changed and P is for force_faint only; the bench-first ordering + DREW doc is 66595498;
  - adversarial review ACCEPT-WITH-FIXES, all fixed.
  - **NEXT CARD:** the live carrier for P. A1 (`linked_faint_active_gen3`) and A2 (`active_end_gen3`) assert the OLD hold and are now semantically wrong on FR/LG; the P worker's report lists the replacement assertions (ACTIVE_COMMIT 7 bytes, O1-O7 in docs/gen3/research/active_faint_in_battle_scope_2026-09-23.md §5).
  - Update them (Codex owns those carrier files), then run both titles plus the whiteout and trainer variants.
- **Owner decisions OPEN** (asked, not yet answered):
  1. add the controller hand-off on FR/LG too, so no A press is needed;
  2. RR lag-frame lost-ball window: record as a limit, or add a companion opcode;
  3. the DREW edge (an end-of-turn foe KO on the same turn as our last mon's Perish KO gives a whiteout): accept, or hold P on the last mon.
- **G5 (RR) research landed:**
  - save callers 76bc4486;
  - battle tuple fixed 97082a62/a1bbc686 (required clause set; battle_commit_hold);
  - FORCE_MOVE_SLOT 15a274ec/21df5314 (source only, companion rebuild = owner);
  - RR P parity scope 11a7203e (no rebuild needed; hand-off write + a writes.lua write_plan).
- **Other landed work:**
  - LG CPU census 168fde14/b21a3431;
  - receipt tools 587453bf/e8497461;
  - UI-lane cherry-picks: manager unadmitted games, Gen 4/5 removed, RR sprites bundled 3235ddf3;
  - Gen 1 SFX fix 48709f39.
- **Lane rule:** check `git status --porcelain --untracked-files=no` is empty after every lane checkout (a Drive checkout once dropped 22 files).

## CHECKPOINT 14 (2026-09-23): G4 owner rulings recorded; the 2b in-battle rows wired and run; G5's RR battle permit fixed in source

Resume from HEAD d8a62085 (see git log). Clean cuts to re-enter from: b261d045 (save rows + A1), b0511ff2 (item 3), e4c30fff (tutorial states).
**The tree is NOT clean at this checkpoint**: uncommitted edits to lua/gen3/safety.lua, patch/src/handlers.c, tools/e2e_duo.py + lua/tests/duo/duo_gen3_main.lua, tools/gen_gen3_write_checkpoint.py, data/games/gen3_rr/write_checkpoint.json and their tests, plus the untracked lua/tests/gen3_routes.lua + tests/unit/test_gen3_routes.py (the items marked "in flight" below).
- Owner rulings, all four settled in docs/gen3/G4_request_draft.md §6:
  - (a) item 6 is split (dd42cde6): 44bf25d6 goes into this cut as **48709f39** (identical patch-id; 44bf25d6 itself is a Gen 2 branch commit, not in this range); 3941198c and the legacy Gen 2 failure stay post-G4 (docs/gen3/research/item6_integration_feasibility_2026-09-23.md, 21234c4f);
  - (b) the cartridge's own in-game link battle and the Union Room entry are signed limits (f8ad32b6);
  - (c) the rollback freeze is the SHA + manifest: docs/gen3/rollback_bundle.md @ 2cd9f993 (dd42cde6);
  - (d) doubles, the target menu and Safari are current-fixture limits — 2b rows D1-D5, N3 and U3 are recorded limits, every other 2b row still runs (dd42cde6).
- Manager: gen3_ap/gen3_e stay listed but are not creatable (b8e731b2; the whitespace/case bypass closed in ac70cc39); the chips grey out from the form's own flag (05491f55 template, 2eb119d7). Gen 4/5 were first labelled not-admitted (0e869b11) and then removed from GAMES and the New-run form outright (d8a62085, code kept as tag archive/gen4-gen5; a test asserts no gen4/gen5 key is offered).
- PASS at clean cuts (receipts under docs/gen3/probes/):
  - save rows 1/3/6/9 re-taken on both titles, plus the 2b A1 FR active hold: c13cf7c7 @ b261d045 (save_then_write_fr|lg_as_a_b261d045, center_controls_fr|lg_as_a_b261d045, linked_faint_active_fr_forced_b261d045);
  - G4 item 3 probe rows (trainer, faint prompt, LG script_running, LG battle_commit_state3): 03ab26e7 @ b0511ff2 (checkpoint_fr|lg_clean_c4probe2_2026-09-23.txt);
  - the tutorial states (old man + Pokedude) built by normal inputs on FR and LG: 66d2a802 @ e4c30fff (tutorial_states_fr|lg_2026-09-23.txt).
- 2b in-battle rows, live lane (coordinator-held; no receipts in the tree yet): every row PASSes on FR+LG except bw_n7_switch, UNREACHED with 0 samples. Root cause found in 0b37e14d: the popup-opening A and the SHIFT A were one held press (gap 0 after a wait that advances no frame), so SHIFT was never chosen and the B pulse cancelled the menu; the popup witness still needs the post-fix re-run. a596b337 adds incremental verdicts and diagnosable misses.
- Harness and model: C4-ORDER dc855dda + 13b11907; the 2b matrix plan 082b33a9; the rows module db69eca8 with its review fixes (fresh commit arms, N8 receipt fields, personality:otId key) in bdbf5736; the probe wiring 920d46af, fixed by 0b37e14d and a596b337. Carriers and oracles (Codex): 3c35378b..dc7053fc and 7fec95be. T2 is the R-T route's Bug Catcher Rick 102 (082b33a9 §R-T); the prep floor is Lv13 on both titles from the OMP Monte Carlo (071143fb applies the level13 prep; the earlier Lv8 ruling is withdrawn). 2B-INTEGRATE-DUO is in flight with Codex (uncommitted: tools/e2e_duo.py, lua/tests/duo/duo_gen3_main.lua, tests/unit/test_e2e_duo_gen3.py, plus the new lua/tests/gen3_routes.lua + tests/unit/test_gen3_routes.py for the normal-input T2 route).
- G5 (RR):
  - save-caller census 76bc4486 (17 PROVEN / 1 INFERRED / 1 OPEN) plus the item 2 battle-tuple scope;
  - the RR battle permit was UNSAFE (765beb48: CFRU keeps the exec bit set while the menu is parked) and is fixed in 97082a62 (parked-menu permit = exec_flags_input == 1 + a ROM-pool controller pin); the required clause set and the RR battle_commit refusal are in flight in the working tree, uncommitted (safety.lua validates the battle block's clause set; the RR pack gains a `commit_hold` note on battle_commit);
  - FORCE_MOVE_SLOT 15a274ec is SOURCE ONLY — adversarial review ACCEPT-WITH-FIXES, and its fixes are already in the working tree, uncommitted (the CFRU second spelling 0x090A9EA1 in the gate, the link-battle exclusion, the target bound, a 0-PP refusal with reason 11): the 0-based comm enum (the menu parks at 1, the move menu at 2), comm 3 instead of 4, and the PlayerBufferExecCompleted hand-back. The companion ROM rebuild, the .ups regeneration and the patcher/tool hash re-pins need the owner.
- Open: the lag-frame CPU clause for battle() is an owner decision; the final-cut re-takes (boot-check, zip); the owner's Manager run.

## CHECKPOINT 13 (2026-09-23): MILESTONE -- Center receipts + the stale-save fix PASS live on FR and LG

Resume from HEAD after this commit (see git log). Clean lane is `.claude/worktrees/gen3-lane-clean` at 10e4a702.
- PASS on both titles at 10e4a702:
  - save_then_write_gen3 (a keyed write lands after an in-game save);
  - center_controls_gen3 (Cable Club welcome wait, link wait, no-adapter message);
  - whiteout (write inside the Center + nurse control), 5a8064f3.
- Fixes landed:
  - C4-SAVE 5923c4dd + 0e7f89e7 (sLinkOpen; save_dialog_cb as a witness; League lighting). Codex adversarial review:
    the runtime fixes are retained;
  - C4-6t 10e4a702 (rewind off in every run config; START-menu save witness);
  - harness hardening 8e9e7ba4 / f5d92327.
- Evidence docs:
  - docs/gen3/research/checkpoint_predicate_audit_2026-09-23.md (audit, census, adversarial review, RR save path);
  - docs/gen3/G4_status_2026-09-23.md;
  - docs/gen3/G4_request_draft.md, which OMP (C4-DRAFT3) is updating in the tree; commit it after review.
- Open for G4:
  - the 2b in-battle matrix (trainer, doubles, tutorial, and the remaining negatives);
  - the missing probe rows;
  - Codex's owed save/link physical rows;
  - final-cut re-takes (boot-check, zip);
  - the owner's three scope decisions (item 6 Gen 1/Gen 2 baseline, the link/Union Room limits, the rollback freeze);
  - the owner's Manager run.
- G5 (RR): its own battle-lifecycle and save-caller proof. RR still routes to the old client.
- Environment: any EmuHawk launched with the machine's base config.ini still has rewind ON (a crash risk). Owner FYI.

## CHECKPOINT 12 (2026-09-23, after a coordinator crash): Center receipts + the stale-save defect

HEAD 3fefbee7. Clean lane `.claude/worktrees/gen3-lane-clean`.
- All seven FR<->LG scenarios PASS (ac1a5490 and earlier). The G4 status and the corrected draft are in
  docs/gen3/G4_status_2026-09-23.md and G4_request_draft.md (1729c72e).
- Center (G4 2a):
  - whiteout (write inside the Center + nurse control) PASS FR-as-A and LG-as-A (5a8064f3);
  - center_controls (Cable Club welcome wait, link wait, no-adapter message) PASS FR-as-A (3fefbee7);
  - LG center_controls was interrupted by the crash; re-run it.
- PRODUCT DEFECT FOUND AND FIXED (C4-SAVE):
  - the checkpoint required sSaveDialogCB==0 and gLinkCallback==0, pointers pret never clears, so after ANY
    in-game save every overworld write was held for the rest of the session;
  - the fix is 5923c4dd (link reads sLinkOpen; League lighting allowed on FR/LG) + 0e7f89e7 (save_dialog_cb
    becomes a witness; one line in safety.lua);
  - LIVE: on LG a keyed write LANDED after a save;
  - Codex adversarial review cx-3e10776a is in flight (re-issued).
- Harness C4-6t in flight:
  - BizHawk rewind capture crashes EmuHawk (AccessViolation in mGBA SaveStateBinary via Zwinder); disable rewind
    in the generated configs;
  - the save helper's second-save dialog detection.
- Audits: docs/gen3/research/checkpoint_predicate_audit_2026-09-23.md (predicates + persistent-task census).
- Next: after C4-6t, re-run save_then_write FR+LG and LG center_controls, then the G4 remaining items and the
  owner's three scope decisions.

## CHECKPOINT 11 (2026-09-23, in progress): G4 FRLG lane

HEAD c8f0c804; clean lane worktree `.claude/worktrees/gen3-lane-clean` (detached, keep it clean).
- PASS on a clean cut with the C5 stack (d199da32): faint_cmd, link, boxsync, reconnect (+ wrong-save C-1/C-2);
  receipts and goldens are in docs/gen3/probes/*2026-09-23b.txt; conformance is 59/59 including item 15.
- Owner ruling "Apply inside too": writes land inside Pokemon Centers (5ecfae3b; Codex ACCEPT as SOURCE/MODEL).
  Live: WRITE_IN_CENTER was observed at 5.4 (7,4) with the Union Room tasks active. The full receipt (G4 2a) is owed:
  C4-6m.
- Fixed and committed today:
  - PC withdraw box_to_party (767ba0a5);
  - enemy party by occupancy (f2aec36f): item 15 and dead-zone no_catch;
  - LG FR-copied SE headers and evolution CB2s (123c6c45);
  - the rival swap C5 stack (2dc1b750; Codex REV4 ACCEPT);
  - session arrival order for force_faint vs memorialize (684bbb7a);
  - harness races and oracles.
- In flight:
  - C4-BW: the battle_faint clause becomes exec_flags==1 + HandleInputChooseAction, because pret says ==0 never
    holds at the parked menu. This blocks linked_faint_active.
  - C4-6m: Center receipt gaps, the deadzone per-player dead_zone oracle, and the nurse clause parse. This blocks
    deadzone and whiteout.
  - C4-LGSE2: a fail-closed LG guard.
  - Codex REV-session-order-1.
- Rehearsed: cold-boot 8/8 (8a13f38b); release zip boots FR on the new client (99c70d9c; gate tools/check_release_zip.py);
  rollback bundle (2cd9f993; master's RR md5 pin is stale, this branch corrects it).
- Gen 1 live: town SFX is red on master too (not caused by the cutover); a Gen 1-side gate or sound mismatch, reported.
- Still owed for G4: FRLG probe rows (battle_input_wild incl.), the Center receipt on FR and LG, final-cut re-takes,
  the Gen 2 lane re-run, and the owner's Manager run.

## STOP POINT 2026-09-23 (owner: stop at the milestone)

Resume here. HEAD 767ba0a5. Milestone: FR<->LG faint_cmd_gen3 PASS on the new client, clean cut (c6d5ea4f).
G4 lane items started after the milestone, run in the clean lane worktree `.claude/worktrees/gen3-lane-clean`:
- link_gen3 run 1 FAIL: bag fade race (fixed 43b9ccb4). Run 2: A PASS on throw 1, B out of balls (2 balls, RNG).
  ad9669b1 adds the Gen 1 ball-RNG retry. NEXT: re-run on a cut containing ad9669b1.
- boxsync_gen3 FAIL: withdraw sent no box_to_party because gPlayerPartyCount is stale inside the PC.
  Fixed in 767ba0a5 (unit falsifier). NEXT: live re-run.
- whiteout_gen3 FAIL: A's rebuilt party_mon was held for the whole wait by the safety.lua task clause
  ("unknown active task"). C4-6h DIAGNOSED (not applied): A waits inside the Viridian Center 1F, and every
  FRLG Center 1F runs CableClub_OnResume -> InitUnionRoom (pret cable_club.inc; union_room.c:3110), which
  leaves Task_InitUnionRoom / Task_SearchForChildOrParent / Task_UnionRoomListen active. Those are not on
  the allow-list (write_checkpoint.json:345-349), so the checkpoint never opens indoors. The tasks were seen
  in A's own pc-exit dump on that map; that they were active after the whiteout is inferred.
  Harness fix: walk A out of the Center before the rebuild wait, and dump the task list on wait_until
  timeouts. OWNER QUESTION: real players are held in every FRLG Center until they step outside. Is that
  acceptable? Allow-listing the RFU tasks is a signed-path change.
- Not started: reconnect_gen3 (+ --wrong-save), deadzone_gen3, linked_faint_active_gen3, then G4 items 3-7.
C5-11c: OMP fixed all 8 REV2 findings; it is UNCOMMITTED in this worktree (full suite 5467 passed with SLINK_ARMGCC).
NEXT: slink-adapter-guard + Codex REV3, then commit, patch rebuild, md5, lane gates.

## Where things are

- Worktree `E:/Google Drive/SLink/.claude/worktrees/gen3-migration-planning-5d8e45`, branch `claude/gen3-migration-planning-5d8e45`, pushed to origin once on owner authority (2026-09-21) so CI could build the pret symbols. It was merged to LOCAL master on 2026-09-26 (owner ruling 26) and has tracked master since. Nothing is pushed after 2026-09-21.
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
| G4 | NOT SIGNED. Request `docs/gen3/G4_request_draft.md` (frozen cut a2985d5a, FR/LG 43/43; rulings 25/26). Owner plays and signs. |
| G5 | NOT SIGNED. Request `docs/gen3/G5_request_draft.md` (RR 19/19). Owner plays and signs. |
| G6 | Not started (P6 docs + 2 reviews first; the owner tags and ships). |

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
- **Duo harness ACCEPTED** (Codex REV4, 2cace0a9) after C4-6b/6c/6d; OPEN RR extension evidence and NON-QUALIFYING explode/rival controls stay unqualified. C4-6b (50d580c9) and C4-6c (32e0e469) landed; FR faint_cmd_gen3 re-run PASS on the stricter harness (c82b38c1). Earlier: Codex REV2 REJECT with 4 MAJORs queued as C4-6c: bound the mutable whitelist (HP<=max, PP only on real moves, status) with scenario postconditions; require read success before BOXED/RETURNED absence; bind the RR extension RAM copy to the final save ordinal; keep explode UNQUALIFIED until an RR execution witness downstream of attackcanceler/tryexplosion; RR level bound from profile (250). Accepted parts: RR decode, no-op deposit refusal, invariant diff, extension content compare (else OPEN), no memory staging, rival as control, native_absent valid trade.
- **In flight at stop:** C4-8 busy-mailbox single-instance test + rival-swap refresh window design (OMP; uncommitted test_gen3_entry.py + docs/gen3/research/rival_swap_refresh_window.md in tree).

- **Rival swap redesign** (after checkpoint 10): OMP C4-8's five-clause refresh window was refuted by Codex (passes after every turn; the old controller snapshot overwrites a refresh; the first trainer dex write is at battle_main.c:2611). Redesign 32c61120 = option (a): post OP_SET_ENEMY_PARTY only after CreateNPCTrainerParty and before the opponent's data request, so the engine carries the swap (no Lua battle-mon write). Codex ACCEPTED the core ordering on the pinned RR hook (slink_hook runs before callback1/2) but requires: a battle epoch + late-reply correlation, validation of the enemy slots SetBattlePartyIds preselected from the old team, a corrected old-client analysis, doc minors -> C5-8b (OMP, after the C5-9 RR intro pins). Per-job dispatch receipt 6c3fe62b ACCEPTED (closes REV7). Old-client vanilla outcome patch 3ea768fa (owner: "Patch").

## Next actions (checkpoint 10)

1. Reconcile the four in-flight cards (gate, commit, review): duo harness closed: C4-6d (2cace0a9) Codex REV4 ACCEPT; live new-client transcripts committed as the first gen3_new goldens (conformance green); C4-8 -> commit test + design doc;
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
