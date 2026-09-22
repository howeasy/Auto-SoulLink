# Gen 2 implementation resume (updated 2026-09-22, third stopping point)

## Who coordinates

**Claude is the Gen 2 orchestrator** (owner ruling 2026-09-22, confirmed after Codex returned).
Codex is a worker/reviewer under Claude's dispatch. The coordinator session now works from THIS
worktree (`gen2-foundation`). Workers in session 3: up to 3 Opus 5.5 / Sonnet / Haiku subagents
(model set explicitly), OMP live `Gen2-Base` for coding/review, Codex live thread `Gen2-Part2`.
Only the coordinator edits the sole ledger: the sweep `RC_MASTER_GUIDE.md` checkpoint plus
`WORKTREE_REGISTER.md`. This note summarises it; it is not a second ledger.

### Codex (`Gen2-Part2`)

- It acknowledged the coordinator ruling and works read-only on cards from Claude.
- **Dispatch channel:** the magi bridge refuses live `request`s to this thread (NO_LIVE_PEER even
  when listed idle), but `note`s are delivered. Send the whole card as a `note` (with a `queueKey`);
  Codex replies with one note naming the card. There is no bridge taskId, so no `outcome` call.
- Codex cards this session: R4 second pass + supplement, R5 (P3a review). D1 was cancelled.

## Where things are

- Implementation: `E:/Google Drive/SLink/.claude/worktrees/gen2-foundation`, branch
  `codex/gen2-foundation`. HEAD is in the ledger (`source_head`). Nothing pushed since P1
  (`93ccb8e`); no master merge. Local master moved to `43590d1` (another session, "gen1 live-run
  fixes"): rebase/merge planning is a pre-merge task.
- Planning docs: the root checkout's `claude/gen2-planning-kickoff-a18801` (`9c7e7ac`) is
  historical; THIS file supersedes it. The old planning worktree was deleted (owner, 2026-09-22).
- ROM dumps and staged/built cartridges live in this worktree (all gitignored): Gen 1 + Gen 2
  dumps at the root, `patch/build/gen1_pure*.gbc`, `patch/gen1/build/slink_{red,blue}.gb`,
  `.cache/pret`, `.cache/gen2-build`. The temporary lane worktrees `g1master`/`g2lane` were deleted.
- Worktrees now: root, `gen1-rby-code-sweep-8d06e2` (ledger), `gen2-foundation`,
  `gen3-migration-planning-5d8e45`. Consolidation record: `WORKTREE_REGISTER.md` (2026-09-22);
  archives in `.cache/snapshots/` (root checkout).

## Done (see commit bodies and docs/gen2/reviews/)

Session 3:
- `9160358` **P3a.1**: every Gen 2 title spelling -> one foundation `gen2_gsc`; legacy adapter
  routing unchanged until the G3 cutover; 153 pairing-matrix tests. Review R5 (Codex):
  `R5_P3A_REVIEW_2026-09-22.md`. **P3a.2 (Gen 2 hello conformance) is OPEN.** Coverage map
  re-pinned to `protocol.md` `ed384146` (`6ed5f35`).
- `41e3ea5` **R4 fixes (N10)** for `R4_CODEX_REVIEW_2026-09-22.md` (two Codex passes + supplement):
  inspect gate compares badge fields, reaches the overworld through the qualify boot stage (a
  CONTINUE confirm screen no longer counts), keeps 100% speed, binds identity to the
  qualification receipt, validates dump provenance; re-save oracle preserves map-object script
  pointers, constrains daily flags / RTC flags to source-legal transitions, requires the native
  re-save witness; a non-+1 frame step abandons the timeline (epoch, queued batches, latches).
  Finding 2 (phone timers) was REFUTED (unsaved `wMapStatus`). Not yet independently reviewed.
- `ed6a69f` first-play source check (OMP): **the route cannot answer map-script text boxes**
  (`PromptButton`/`WaitButton`) or the weekday picker, so a live play stalls at Mom's first text.
  Card gen2-N11 fixes it before any live play.
- Owner rulings: legacy `crystal_ap` + ordinary Gen 2 legacy pairing now refused (O-8, recorded
  at G3a); Gen 1 verification DEFERRED to pre-merge.

Session 2: `0211c7c` N3 review, `acde60f` N3 fixes (BizHawk has no pair registers), `cfbcbba`
qualification callbacks + `qualify()`, `c03c15f` inspect gate, `f86c061` R3 review, `0f2b3bc`
R3 fixes, `2df48a0` + `c42061d` fishing (`fishing_water`; OPEN until a fixture fishes).
Session 1: commits `5824258`..`463bc71` (Gen 1 rebind repaired, Gen 2 reads/wire/tooling/client).

## Physical evidence so far

- Gen 1 at frozen `463bc71`: 8/10 lanes PASS (live-new-gates, inspect-purergb, apex-purergb,
  live-trade-gates, inspect-purergb-overlay, live-trade-gates-purergb, apex-refusal-purergb,
  live-gates). duo-pairs / duo-pairs-purergb fail a DIFFERENT random subset each run (loaded:
  rival_swap+2; quiet: whiteout, pc_ops; idle: ball_gate, admit_randomized, species_clause,
  poison, rival_swap), and isolated `whiteout_new`+`pc_ops_new` PASS on both master `8f6a986` and
  the branch: a flake pattern, not a proven regression. Settle before merge (card gen2-M1).
- No Gen 2 live run yet.

## Next actions, in order

1. **gen2-N11** route origins: add `PromptButton`, `WaitButton` and the weekday-picker loop as
   route origins answered with A in `lua/tests/gen2_scripted_play.lua` (qualify keeps refusing
   them), a pure test for script-state observations, real `has_existing_save`. No blind
   press-A fallback. See `docs/gen2/reviews/OMP_FIRST_PLAY_ASSUMPTIONS_2026-09-22.md`.
2. Independent review of `41e3ea5` (R4 fixes) and N11.
3. **gen2-N2** first live Gen 2 play (crystal_town) from a frozen lane worktree, then `qualify()`,
   then write `tests/fixtures/gen2/receipts/<name>.qualification.json` (the inspect gate needs it;
   check whether the staged fixture is the candidate or the re-saved copy, see `41e3ea5` body).
4. **gen2-P3a2** Gen 2 hello conformance + `docs/protocol.md` section 8 answers (Codex is a natural
   author or reviewer); re-pin the coverage map after any protocol edit.
5. The other seven fixtures, the live inspect gate run, the Gen 2 duo harness (not started).
6. Pre-merge: gen2-M1 (Gen 1 duo flake vs regression: whole duo lanes on master vs branch under
   identical idle conditions) and reconcile with local master `43590d1`.

## Runbook (exact commands; run from this worktree root)

- **Editing:** the session now lives in this worktree, so Edit/Write work here. Git is fenced to
  this worktree: run git commands plainly, without `-C` or `cd` to other checkouts.
- **Machine load rule:** NO worker/peer test runs while any emulator lane runs (contention voided
  three duo runs). Tell workers "hold tests until lane free", then release them.
- **Live lanes run from a frozen detached lane worktree** (`git worktree add --detach <path> <sha>`,
  then copy ROMs/`patch/build`/`patch/gen1/build` and junction `.cache/{build-tools,pret,downloads,gen2-build}`,
  copy `.cache/upr`). Remove it by unlinking junctions FIRST (Python `os.rmdir` on each junction),
  never a recursive delete through a junction.
- **Gen 1 lanes:** `SLINK_PURERGB_ROMS="E:/Google Drive/SLink/.cache/purergb" python tools/verify_gen1_release.py --lane <name>`
  (live-gates needs `.cache/upr/PokeRandoZX.jar`).
- **Gen 2 coverage lane:** `python tools/verify_gen2_release.py --lane coverage-map`. After ANY edit
  to `docs/gen2/gen2_requirements.md` or `docs/protocol.md`, replace that file's LF SHA256 in both
  places in `docs/gen2/gen2_coverage_map.md` (near lines 30 and 225).
- **Generators:** each has `--check`; packs must regenerate byte-identically;
  `python tools/verify_gen2_rom_layout.py` checks engine-site bytes against built ROMs.
- **First live play:** `from tools import gen2_fixtures as f; spec = next(s for s in f.FIXTURES if s.name == "crystal_town");
  f.run_play(spec, {"observer_qualified": True, "attempt_id": "<id>", "gate_script": f.GATE_SCRIPT})`
  (cold, CGB, 300%; output is a CANDIDATE). Needs N11 first.
- **Qualify:** `python -c "import json; from tools import gen2_fixtures as f; r = f.qualify('crystal_town', r'<candidate_path>', '<attempt_id>'); print(json.dumps(r, indent=2)); raise SystemExit(0 if r['passed'] else 1)"`
  (boot, resave, reload at 100%).
- **Live inspect gate:** `SLINK_LIVE=1 pytest tests/live/test_gen2_new_gates.py -q` (needs qualified
  fixtures + receipts).
- **Known red, not regressions:** `test_gen1_trade_patch.py` (RGBDS `STRSUB` warnings); 17 legacy
  `test_gen2_adapter.py` encounter tests (resolve at the G3 cutover).
- **Peers:** OMP cards literal with ABSOLUTE paths, never `wait=true`, `kind: outcome` for every
  OMP task. Codex: see "Codex (Gen2-Part2)" above. From this worktree pass
  `workingDirectory=E:\Google Drive\SLink` to reach live peers.
- **Deleting on Google Drive:** read-only attributes: `shutil.rmtree(path, onerror=chmod S_IWRITE + retry)`;
  `git worktree remove` leaves gutted dirs; `git branch -D` is blocked by the guard hook.

## Open decisions and carries

- **G3a (owner signature pending):** P3a.1 diff + R5 review; intentional legacy split (ordinary
  Gen 2 legacy + `crystal_ap` legacy refused both orders, AP/AP still pairs); artifact-kind rule
  changes at the cutover (legacy normalizes named/clean; `Gen2GSCAdapter` keeps them distinct):
  pin with tests then. Shared carry: `server.py:1321` turns falsy non-string `artifact_kind` into
  `clean` before the type check.
- **G3 cutover:** unhatched eggs are kept off the wire (O-15), so the server party count is one low
  while an egg is carried.
- **P4 carry:** mail flag not yet enforced on any transfer path (T-3).
- **Merge carry:** 13 intended Gen 1 behaviour differences in the body of `0a1aa79`; gen2-M1.
- OPEN with an exact reason: `fishing_map_association` (side-wall premise is conservative; strips
  and story blockdata not modelled); R-3 and R-5g GAME oracles (Lua-internal / DV-formula only);
  same-frame savestate replacement not detected by the frame-step heuristic; re-save oracle is a
  fresh-fixture oracle (roamers, Pokerus, Mystery Gift, RTC overflow, Battle Tower out of scope);
  four day-stamp fields still accept any value; U5 double ROM read at boot.

## Stable facts and constraints

- Sources: pokecrystal 7a7881d0d62e0ddbd82dcf10e7116807487ac651; pokegold 656583c939d30f920a316177311a502dd222b57c; RGBDS 1.0.3.
- Crystal 1.0 f4cd194bdee0d04ca4eac29e09b8e4e9d818c133 (1.1 build-only); Gold d8b8a3600a465308c9953dfa04f0081c05bdcb94; Silver 49b163f7e57702bc939d642a18f591de55d92dae.
- BizHawk 2.11.1 `emu.getregister`: single registers + bank names only, no pairs.
- Poké Balls are the sole staging exception. Scripted normal input, one emulator lane, route 300%, qualification 100%, no Computer Use.
- Stat formula doubles base AND DV; full identity is DV:OT:species; GSC SaveRAM = 32768 SRAM + 22-byte RTC trailer, oracles compare the first 32768 bytes.
- No push, master merge or release without owner authority. Remote authority covers only the exact P1 commit.
- Sole authority: E:/Google Drive/SLink/.claude/worktrees/gen1-rby-code-sweep-8d06e2/docs/gen1_reference/RC_MASTER_GUIDE.md and WORKTREE_REGISTER.md. Coordinator: Claude session 1d2b4c9a.
