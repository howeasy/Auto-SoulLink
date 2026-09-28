# Gen 3 RC closeout runbook (one session)

Written 2026-09-27 by the combined Gen 3 coordinator (claude 30c21a7a) at the owner's request: "Get us ready for one more session to close this all out." The next coordinator is Codex, per the owner's handoff. Follow this top to bottom. Every step names its exit evidence.

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
- RR final cut on the new companion: lane `C:/slink-wt/g3-lane3`, log `C:/slink-wt/fc-rr-02ba8ed1.log`, summary `docs/gen3/probes/fc_SUMMARY_02ba8ed1_rr.txt`.
  - Triage every FAIL. Classify each as env (lane input), harness, or product.
  - Never rerun an unchanged failed row; fix first.
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
5. **EXP-DATA:** wild encounter and trainer tables for the reference build (today `encounter_table`/`trainers_for_area` return empty, a recorded limit). Trainer panels, Upcoming Key Trainers and Prep are mandatory for an RC (ruling 28).
6. **EXP-CALC:** the expansion battle calc (owner: IN the expansion RC). Coordinate with the calc lane on master (`docs/calc_multigen/HANDOFF.md`).
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
