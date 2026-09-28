# Gen 3 RC closeout runbook (one session)

Written 2026-09-27 by the combined Gen 3 coordinator (claude 30c21a7a) at the owner's request: "Get us ready for one more session to close this all out." The next coordinator is Codex, per the owner's handoff. Follow this top to bottom. Every step names its exit evidence.

## Closeout execution update — 2026-09-28

The current run started from `ea1d0d66` on `claude/gen3-integration`. Local master remains `abc6bf28`; landing still needs the separate owner approval below.

- Gate inputs: `SLINK_GEN3_UPR_SCRATCH=C:/slink-wt/rand_roms` admits the existing audited allowed ROMs. A real `cartridges.provision(..., companion=False)` pair now exists at `r3_run`. The pinned expansion source is junctioned into integration and all four cut lanes; it is deliberately not copied through `UNPINNED_INPUTS`. The 60 targeted input tests pass without skips.
- Ruling 40: six town backfills and 19 trainer-area updates are integrated; generators current, 75 focused tests pass. Lavaridge was already named and is outside this new backfill.
- Ruling 39: production hello and persisted `gen3_exp` loads are refused. Only the explicitly logged `--test-only-route emerald_expansion_28877d73` duo process admits the expansion. Host verification: 214 focused tests pass; broader routing regression 608 pass, 32 unrelated fixture skips. Final-cut gate still must have no unexplained skips.
- RR tail: the old gate painted the allocated durable block. It now watches the remaining `0x0203FF61..0x0203FFFF` (159 bytes); a fresh live gate passed seven scenes/5,100 frames. This was a harness overlap, not evidence of production overlap.
- RR capture: the original `sync_retrieve_failed` said `missing stats`. Party catch and hatch now send full stats before a link can queue retrieval; catch/hatch controls fail on the old payload and 210 focused tests pass. A fresh RR link passed, but that catch receipt does not physically qualify hatch.
- Session initialization: the birth winner retries its own initial publish, and wait bounds are about 15 seconds. Real two-runtime interleavings plus exhaustion controls pass (35 tests, zero compiler skips). Permanent crash/ACL failure still fails closed; no loser recreates a counter. Busy waiting and manual recovery remain limitations.
- Reconnect: Gen 3 permits multiple newly accepted capability HELLOs, while rejecting any failed refresh and retaining identity/link/party/gameplay checks. The Gen 1 exactly-one default remains. Focused 21 tests pass.
- RR type clause: a nonmatching first B encounter now aborts while still in battle, before RUN/no_catch; the runner retries a fresh server and fresh seeded batteries, at most eight attempts. The oracle requires one overlapping first encounter and no no_catch/dead-zone evidence. The earlier within-attempt RUN hunt was reverted because it could close the pending area.

First cut `16925cfb`: Emerald 24/24, RR 28/28, FR/LG 42/43. The release unit gate and standalone suite found a stale Roxanne area assertion and stale generated expansion harness facts/layout hashes; both are fixed in the correction. RR happened to find overlap on its first encounter, so that PASS did not exercise the unsafe RUN branch. Receipts are retained in `docs/gen3/probes/*16925cfb*.txt`. The corrected cut must rerun the complete validation.

FR/LG uses the runner's existing two-shard plan (~51 minutes each), with isolated lane and state directories. Expansion XG3 work remains separate until reviewed; it never delays the core cut or changes production routing.

## 0. Ground truth before you start

- **Integration:** `claude/gen3-integration` in `C:/slink-wt/g3-int`, at 02ba8ed1 or later. It holds ALL Gen 3 work:
  - FR/LG/E/RR native trade;
  - the FR/LG/E production companion;
  - the Emerald native companion with Match Call;
  - RR durable trade;
  - RR ROM encounter data;
  - clause live rows;
  - the expansion X2+X3.
- The full unit suite was 13507 passed / 0 failed at e38c238f (`C:/slink-wt/suite-rrdur-int.log`).
- Env: `source C:/slink-wt/g3-env.sh`. Always set a private `SLINK_STATE_DIR` per emulator run, and kill only your own EmuHawk PIDs. Gen 2 lanes share this machine.
- **Gates:** ALL signed. The owner said "All gates are signed." on 2026-09-27, covering G4, G5, EG4, XG1 and XG2. G3, EG1-EG3 and XG0 were signed earlier. Each doc carries a dated signature line.
- **The master landing is NOT approved.** It needs its own explicit owner "yes" (ruling 41). Never push, tag or `gh release` without the owner.
- **Owner rulings 36-41:** see `docs/gen3_resume.md`. 36 no phone on FR/LG/RR; 37 randomized RR out; 38 expansion shinyModifier as a known limit, carried in X4; 39 refuse the expansion server-side until routed; 40 fix six Emerald towns; 41 one landing of FR/LG/E/RR together.
- **Staged gitignored inputs in g3-int** (the final-cut runner copies them into lanes):
  - `patch/build/slink_RR.gba`: the NEW RR companion, sha1 `da579690db7d6933a0952a1f490312842793f71a`. The old one is kept as `slink_RR.gba.old-7a386749`; don't restore it.
  - `patch/build/candidate-{firered,leafgreen}-trade/`: T5 builds from `C:/slink-wt/g3-t5-fr-duo`.
  - `.cache/expansion-output/`: the expansion reference build from `C:/slink-wt/g3-exp`.
  - `data/.rr_src_cache/`: from `python tools/fetch_rr_sources.py`.

## 1. Collect the runs started at handoff

Both were started on cut 02ba8ed1 at the end of the previous session.
- FR/LG `release_gate_quick` rerun: log `C:/slink-wt/fc-frlg-gate-02ba8ed1.log`; receipt `docs/gen3/probes/fc_release_gate_quick_02ba8ed1.txt` in g3-int.
  - Expected: 0 failed and 0 unexplained skips, now that the runner stages the three inputs.
  - If a skip remains, it names a missing input: stage it (UNPINNED_INPUTS in `tools/gen3_final_cut.py`) and rerun the row.
  - If the T5 candidate tests fail rather than skip, the candidate builds are stale against the integration source. Rebuild them in g3-int: `python patch/tools/build.py --target firered --trade-candidate --rom "E:/Google Drive/SLink/Pokemon - FireRed Version (USA).gba"` (same for leafgreen), with `SLINK_ARMGCC` set as in `C:/slink-wt/run_t5native2.sh`.
- **RESULT at handoff (02ba8ed1):** the FR/LG gate now reports 0 failed and 6 unexplained skips (it had 31). To clear the 6:
  - (a) 3x `test_gen3_exp_pack.py`: "pokeemerald not cloned: <lane>/.cache/expansion-src". Create that junction explicitly in each lane, pointing at `SLINK_EXPANSION_SRC`; do not add the clone to the runner copytree inputs.
  - (b) 2x `test_gen3_rom_content_lua.py`: the UPR "_allowed" FR/LG ROMs. The test now reads `SLINK_GEN3_UPR_SCRATCH` (default `C:/slink-wt/upr_scratch`); it used to hard-code one Claude session's scratchpad. Use the existing audited FireRed_allowed.gba and LeafGreen_allowed.gba in `C:/slink-wt/rand_roms`, and export that folder as the env var in g3-env.sh.
  - (c) 1x `test_gen3_rom_ingest.py`: the Manager-made randomized pair `C:/slink-wt/rand_roms/r3_run` (set `SLINK_GEN3_RAND_ROMS`). Recreate it through the Manager provisioning path with `companion=False`, so the randomized ROMs match the contract.
  - Then rerun the gate row.
- RR final cut on the new companion: lane `C:/slink-wt/g3-lane3`, log `C:/slink-wt/fc-rr-02ba8ed1.log`, summary `docs/gen3/probes/fc_SUMMARY_02ba8ed1_rr.txt`.
  - Triage every FAIL. Classify each as env (lane input), harness, or product.
  - Never rerun an unchanged failed row; fix first.
- **RR final cut RESULT at handoff (02ba8ed1, new companion da579690): 23/28.** The receipts are committed, and the summary is docs/gen3/probes/fc_SUMMARY_02ba8ed1_rr.txt. Triage, in priority order:
  1. `rr_opcode_gates`: `test_live_ewramtail.lua did not report PASS`. **Likely REAL.** The RR durable block (rr_trade_relay.h) sits at 0x0203FE50 in the "free EWRAM tail". Check it against what test_live_ewramtail and the RR START-menu hijack use (memory note: "the proven-free EWRAM tail"). An overlap would corrupt state.
  2. `link_gen3`: `the client sent sync_retrieve_failed`. Possibly the same overlap, since box sync retrieval fails. Recheck after 1.
  3. `reconnect_gen3`: `timed out after 30s waiting for durable accepted reconnect hello`. RR now takes the durable reconnect path; align the harness or fix the client.
  4. `trade_gen3`: `the server refused the trade: Trade unavailable for Radical Red`. A did not advertise trade_prepare. Most likely the first-launch session-counter race on a fresh lane (the RR worker hit it too; see rr_durable_handback.md §open 2). That is a PRODUCT risk for two windows on a fresh install: fix the first-birth race in lua/gen3/run.lua next_session_counter, not just the harness.
  5. `type_clause_gen3`: both sides passed, but PYDEC says "type clause unobserved": the encounter did not produce a type conflict. Rerun once after 1-4, and check the RR type data against the new ROM-derived types.
- Commit the receipts by explicit path.

## 2. Two small cards from the owner's rulings

These can run in parallel: one Codex thread or subagent each, in their own worktrees off integration.

- **EXP-REFUSE (ruling 39).** Add `emerald_expansion_28877d73` to `_REFUSED_ROM_TYPES` in `server/adapters/__init__.py`, with a player-facing reason, following the crystal_ap precedent.
  - The expansion duo harness (`--game gen3_exp`) must still run: give it a test-only override that is logged in every receipt, like the client-side `TEST-ONLY route of gen3_exp`.
  - Tests:
    - `unrouted_rom_type_reason("emerald_expansion_28877d73")` returns the refusal;
    - a persisted run with `game_id: gen3_exp` is refused on load;
    - the duo seam still admits it.
  - This is a server/*.py change, so it is part of the Gen 2 ping.
- **EMERALD-TOWNS (ruling 40).** Extend the Mauville backfill (`tools/gen_area_map.py`, tag `E5-CITYLINK`, commit f66129ce) to Rustboro, Fortree, Littleroot, Oldale, Fallarbor and Verdanturf, from pret pokeemerald map data.
  - Regenerate `data/games/gen3_emerald/{area_map.json,emerald_trainers.json,gen3_emerald_areas.lua}` and run the generators' `--check`.
  - Update `tests/unit/test_gen3_trainers_emerald.py::test_roxanne`: Roxanne is now under rustboro_city, not route_104.
  - Red first: one test per town.

Exit: each card is merged into integration, and the full unit suite exits 0.

## 2b. PARALLEL: the Emerald expansion track (owner ruling 42, 2026-09-27)

The owner chose a parallel track. The closeout session starts the expansion's remaining work alongside §1-§5 in its own worktrees and lanes. Whatever finishes and passes review merges into integration and lands **unrouted**: the server refuses it by name (ruling 39) and the client keeps it out of `Entry.ROUTED`. **Routing waits** until XG3, the calc and the encounter/trainer data are all done. The landing (§5) must NOT wait on this track.

Setup:
- Base: a fresh branch off integration, e.g. `claude/gen3-exp-xg3` in `C:/slink-wt/g3-exp2`.
- Stage the gitignored inputs:
  - `.cache/expansion-output/reference`, already in g3-int; the build itself comes from hgbox;
  - `.cache/expansion-src` as a junction to `SLINK_EXPANSION_SRC`;
  - `.cache/x1-probe/probe.o` from hgbox.
- Duo runs: `python tools/e2e_duo.py --game gen3_exp --scenario <row> --lane <x>` with a private `SLINK_STATE_DIR`.
- Sources:
  - the handback in `docs/gen3_emerald/XG2_request_draft.md`, the Appendix "X3 progress";
  - OMP review cx-2ce936ca follow-ups in `docs/gen3_resume.md` checkpoint 24.

Cards, in dependency order. Each gets a failing test first, facts come from the expansion source at the pin or the built ROM/.sym, and each merges only after an OMP review of shared files.
1. **XG3-FAINT:** derive the in-battle linked-faint plan (the Perish KO + hand-off) for the expansion's 140-byte BattlePokemon from its compiler facts, and add `battle.handoff` to `data/games/gen3_exp/28877d73/write_checkpoint.json`. Make `BATTLE_MON_MOVES_OFF`/`PP_OFF` pack-driven (review item 2). Live row: `linked_faint_active_gen3` on gen3_exp.
2. **XG3-SITES:** observer receipts per engine-site kind. Resolve the three OPEN PC sites (pc_deposit, pc_release_begin, pc_release; their functions are inlined, so hook the caller or the inlined span).
3. **XG3-GIFTS:** the gift/static census from the expansion source, plus the gift/egg live rows.
4. **XG3-FC:** `tools/gen3_final_cut.py --title exp` (the rows plus zip build/boot). Rerun faint_cmd and boxsync at the final cut.
5. **EXP-DATA:** trainer tables/panels and Prep sets are built (XC4/XC4b, SOURCE/MODEL). Wild tables remain a separate candidate: `codex/close-exp-wild` must model the header generator's EMERALD/FIRERED/LEAFGREEN conditionals and record Altering Cave set-0 scope before integration. Compiled-ROM wild readback is still OPEN. Trainer panels, Upcoming Key Trainers and Prep are mandatory for an RC (ruling 28).
6. **EXP-CALC:** profile, names, stats and trainer sets are built; XC5 live calc validation remains OPEN, as do warnings for unsupported ability/item mappings. Coordinate with the calc lane on master (`docs/calc_multigen/HANDOFF.md`). Do not report SOURCE/MODEL implementation as physical qualification.
7. **Later, not this session:** routing both halves together (the reverse of ruling 39); X4, the onboarding recipe on one owner-picked open-source hack, whose first card is carrying the shinyModifier (ruling 38).

Worker suggestion: with up to 3 subagents, run XG3-FAINT (Opus, needs the emulator) and EXP-DATA (Sonnet, source-only) in parallel with the closeout. XG3-SITES/GIFTS go to a Codex thread. Headless OMP handles reviews and small tasks, but can't run a shell: verify and commit its work yourself.

## 3. Freeze the cut and run the three final cuts

1. Freeze: record the integration sha as `CUT`. Run `python -m pytest -q -p no:cacheprovider tests/unit` and check its exit code on its own; don't pipe it into a commit.
2. If step 2 changed shared server code, `docs/protocol.md` citations may drift. `tests/unit/test_protocol_citations.py` catches it. Remap with a difflib line map from the old file to the new one, as done in 45f44adb.
3. Profiles: `python tools/gen_gen3_profile.py --check` must say current. The ABI source sha moves whenever abi.h changes; see ca54bb42.
4. Final cuts, one lane each, run concurrently:
   - `python tools/gen3_final_cut.py --cut $CUT --title frlg --lane C:/slink-wt/g3-lane --master C:/slink-wt/g3-lane-master` (43 rows, ~100 min);
   - `python tools/gen3_final_cut.py --cut $CUT --title emerald --lane C:/slink-wt/g3-lane2` (24 rows, ~12 min);
   - `python tools/gen3_final_cut.py --cut $CUT --title rr --lane C:/slink-wt/g3-lane3` (28 rows, ~25 min).
   - Each gets its own `SLINK_STATE_DIR` (`C:/slink-wt/g3-lane{,2,3}-state`).
5. Exit: all three `OVERALL: PASS`. The only allowed skip is `linked_faint_active_mega_gen3_*` (ruling 20). Commit the receipts.

Known prior results:
- Emerald 24/24 at b091ff27;
- FR/LG 42/43 at c04420a9, where the one fail was stale profiles, since fixed;
- RR 18/28 at d9a928d7 on the OLD companion, since superseded by the RR-FC-FIX and RR-DURABLE work.

## 4. Optional items

Do these if time allows; otherwise record them as known limits in the landing request.

- Physical RR reset-between-saves recovery: a reset after the native pre-save and before the post-save, then the journal and a reload proof on the real battery. So far this is only unit-proven; see `docs/gen3/research/rr_durable_handback.md`.
- HUD: `lua/gen3/client.lua` nickname fallback shows a raw mon key (`nick_label` pattern, OMP cx-a0dcdcbb). `lua/gen3/run.lua` refusal texts show raw errors.
- Expansion review follow-ups 2-6 (`docs/gen3_resume.md` checkpoint 24).

## 5. Landing prep (ruling 41: one landing, FR/LG/E/RR together)

1. Refresh `claude/gen3-landing-prep` in `C:/slink-wt/rv-land`: merge current local master, then merge `CUT`.
   - Known conflict hotspots from the last refresh (e18e77fc): `server/cartridges.py`, `server/manager.py`, `server/upr_pipeline.py`, `server/static/.../randomizer.js`, and `docs/protocol.md` citations.
   - Regenerate `tests/fixtures/ui/capabilities.json` if the UI capabilities changed.
2. Full unit suite on the landing branch, EXIT 0.
3. **Ping Gen 2 before anything goes to master.** These shared files changed: `server/*.py`, `lua/core/session.lua`, `lua/*.lua`. That stales the Gen 2 CODE_DIGEST and costs about a 2 h re-sweep. Use the Gen 2 lane's live Codex thread ("Gen2-Part2") by steer, or whatever the owner names.
4. Ask the owner for the landing with a one-page summary:
   - the frozen cut sha;
   - the three final-cut summaries;
   - the suite count;
   - the signed gates;
   - rulings 36-41;
   - known limits (from §4 and the gate docs' recorded limits).
5. Only on the owner's explicit yes: fast-forward or merge into LOCAL master. Push, tag and `gh release create` each need their own explicit owner approval. The version lives only in git tags; there is no CHANGELOG.

## 6. After landing: cleanup

Remove merged worktrees. On this Drive setup, unlink junctions first (`os.path.isjunction` → `os.rmdir`), then `git worktree remove`, or `shutil.rmtree` with a `chmod S_IWRITE` onerror. Never use `Remove-Item`/`rmdir`.

Candidates: em-t2, g3-exp, g3-uiq, g3-rrfc, g3-rrdur, g3-t5-fr-duo, o-*, g3-clause-live-rest, g3-clause-run, g3-rr-enc-forms, g3-lane2, g3-lane3. Keep g3-int, g3-lane, g3-lane-master and rv-land until the owner closes the RC.

Update `C:/Users/howar/.claude/hooks/slink/RC_MASTER_GUIDE.md` (the checkpoint) and `WORKTREE_REGISTER.md` at every transition.
