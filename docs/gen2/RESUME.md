# Gen 2 implementation resume (updated 2026-09-23, session 4 in progress)

## Who coordinates

**Claude is the Gen 2 orchestrator** (owner ruling 2026-09-22). Session 4 coordinator: Claude
session 5efbb71c, working from THIS worktree. Workers: up to 3 Haiku / Opus 5.5 / Sonnet
subagents at a time (model set explicitly), OMP live `Gen2-Base` (coding + review, one card at a
time), Codex live thread **`Gen2-Part2`** (NOT "Gen 3 Part 2", which is the Gen 3 lane; owner
correction 2026-09-23). Only the coordinator edits the sole ledger:
`C:/Users/howar/.claude/hooks/slink/RC_MASTER_GUIDE.md` (checkpoint) and `WORKTREE_REGISTER.md`
there (the sweep worktree is gone). This note summarises it; it is not a second ledger.

### Peer channels

- **Codex `Gen2-Part2`:** live `request`s are refused (NO_LIVE_PEER); send cards as `note`s with a
  `queueKey`. Codex's own approval review may block its reply notes to Claude: read its answer with
  `kind: transcript` (`peer: Gen2-Part2`). Codex implements and reviews; subagents allowed.
- **OMP `Gen2-Base`:** `request` with `delivery: live, wait: false`; always `outcome` each task.
- **Subagents** that end their turn waiting on a background pytest show as not running; they wake
  on completion. Say so rather than calling them active.

## Where things are

- Branch `codex/gen2-foundation`, not pushed since P1 (`93ccb8e`). Local master (`c411b2f`) is
  merged INTO the branch (`5d0a41b`, `1ad7fd7`); master itself is 19 ahead of origin, unpushed.
- **Pinned pret sources are `.cache/gen2-build/{pokecrystal,pokegold}`** (7a7881d / 656583c).
  `.cache/pret` holds OTHER commits (3438c70 / e78abb8): never cite it.
- Staged (gitignored): Gen 1/2 dumps at the root; `patch/build/gen1_pure*_overlay.gbc` re-applied
  from master's UPS (sha1 == `data/purergb/overlay_provenance.json`); `.cache/purergb` is a
  JUNCTION to the root pinned pureRGB checkout (remove with `os.rmdir` on the junction only).
  Root `.cache/slink-upr/PokeRandoZX.jar` is the notify-SFX (patch 0009) jar (owner);
  the old one is `PokeRandoZX-pre0009-2026-09-21.jar`.
- Uncommitted work under review: per-card patches in `.cache/snapshots/gen2-session4-2026-09-23/`.

## Done this session (commit bodies + docs/gen2/reviews/ carry the evidence)

- `5d0a41b` / `1ad7fd7` merge master (one conflict: Gen 1 hook-latch logging re-expressed on the
  shared `hook_registry` `status()`); the post-merge suite's 30 failures all fixed or explained.
- `e2586c6` **P3a.2** Gen 2 hello conformance (shared schema, `protocol.md` §8.1); `e09d0a9` cites.
- `6a55f99` owner ruling **O-21** (Crystal Tin Tower Suicune = `legend_245`) + R6 review record.
- `f5b23cc` O-21 in the Crystal static pack/adapter (SOURCE only; runtime capture = card N12b);
  legacy `Gen2CrystalAdapter.encounter_table` reads the pack per hello title.
- `40d614f` **N14a** (R6 #6 full-chain receipt gate; S2 rewind cancels queued work).
- `ca0888b` **N15** server: only a MISSING `artifact_kind` defaults to clean.
- Cross-title areas: only `battle_tower` is Crystal-only (no acquisitions); owner: fine as-is.

## In flight / next, in order (the owner check-in is AFTER step 3)

1. Commit after review: **N11+N11b** route origins (`PromptButton.input_wait_loop`,
   `JoyWaitAorB`, `SetDayOfWeek.loop2`, yes/no at `_YesNoBox` so the `PlaceYesNoBox` save prompt
   is seen; real `has_existing_save`; qualify answers `prompt_button` only in the save phase);
   **N13** registry read-only site view (no per-hit copy); **N13b** Gen 1/2 signals reject path
   allocates nothing; **N14c** R7 follow-ups.
2. After the `lua/gen2/client.lua` commits: re-pin `protocol.md` client cites (+N) and the
   coverage-map sha; rewrite the §2.2 server.py:1321 note (fixed by `ca0888b`).
3. **gen2-N2 first live Gen 2 play**: commit N11 first, freeze a lane worktree, junction only
   `.cache/gen2-build`, `mkdir tests/fixtures/gen2/receipts`, run_play crystal_town (300%), then
   `qualify()` (100%), stage the CANDIDATE SaveRAM, write the receipt (OMP preflight READY,
   cx-2e09cd35; budgets unmeasured: a stall costs the 1200 s timeout). **Then stop and check in.**
4. Queued: N14b strict re-save rules (facts card with Codex); N12b static-capture runtime path
   (design OMP cx-4f13cf07); gen2-M1 Gen 1 duo A/B after N13/N13b (isolated discriminator master
   99.3 s vs branch 112.8 s); other fixtures; Gen 2 duo harness.

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
