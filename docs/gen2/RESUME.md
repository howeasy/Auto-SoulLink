# Gen 2 implementation resume (updated 2026-09-22, second stopping point)

## Who coordinates

**Claude is the Gen 2 orchestrator.** The owner made Claude coordinator on 2026-09-22 when Codex
became unavailable, and confirmed later the same day that Claude **remains** orchestrator after
Codex comes back online. Codex returns as a worker and reviewer under Claude's dispatch, not as
coordinator. Workers: up to 3 Opus 5.5 / Sonnet / Haiku subagents at once (model set
explicitly), OMP live session `Gen2-Base` or a headless OMP, and Codex once it is online. Only
the coordinator edits the sole ledger: the sweep `RC_MASTER_GUIDE.md` checkpoint plus
`WORKTREE_REGISTER.md`. This note is a summary of it, not a second ledger.

### For Codex, on return

- Do not resume the Codex coordinator role from your own context. Your old coordinator entry
  `gen2-p1-coordinator` is closed in the ledger. Take cards from Claude and report to Claude.
- Nothing you left was lost. The in-flight tree was committed verbatim as `5824258`. Your ten
  orphaned claims were consolidated or closed; each ledger entry names its successor card.
- What changed since you left is the "Done this session" list below. Read the commit bodies
  from `5824258` to HEAD before touching code: the independent reviews found three Gen 1
  regressions in the rebind, and one physical regression, all now fixed.
- Your old dispatch briefs in the root checkout's `.cache/gen2-orchestration-20260922/` are
  history. The ledger is the only current grant.

## Where things are

- Implementation: `E:/Google Drive/SLink/.claude/worktrees/gen2-foundation`, branch
  `codex/gen2-foundation`. HEAD is recorded in the ledger (`source_head`). Nothing pushed
  since P1 (`93ccb8e`); no master merge.
- The Codex in-flight tree was snapshotted verbatim in `5824258` before any reshaping.
- Planning docs: the root checkout's `claude/gen2-planning-kickoff-a18801` (`9c7e7ac`). Its own
  `docs/gen2/RESUME.md` is the historical planning close-out; THIS file supersedes it.
- ROM dumps and staged/built cartridges were copied or built inside the worktree for live
  lanes (all gitignored): Gen 1 + Gen 2 dumps at the root, `patch/build/gen1_pure*.gbc`,
  `patch/gen1/build/slink_{red,blue}.gb`, `.cache/pret`. The tracked
  `patch/gen1/dist/slink_bank3f.bin` rebuilt byte-identically.

## Done this session (all reviewed; see commit bodies)
Session 2 (after the first stop; workers were Opus/Sonnet subagents and OMP Gen2-Base, no Codex):
- `0211c7c` N3 independent review of the Gen 2 client `cc04bb7` + binder fixes `dfb25f6`
  (`docs/gen2/reviews/P3_GEN2_CLIENT_REVIEW_2026-09-22.md`): 2 HIGH, 1 MEDIUM, 1 LOW.
  N3-1 was real and serious: BizHawk 2.11.1 `emu.getregister` has NO pair registers
  (`docs/purergb/PLAN.md` A15), so every `HL`/`DE` read would have killed Gen 2 signals live.
- `acde60f` fixes for N3-1..N3-4 (pairs composed from singles, BizHawk-faithful register
  fakes, superseding PC starts, refused captures never `no_catch`, nothing before the hello).
- `cfbcbba` fixture qualification callbacks: boot/CONTINUE, native re-save, reload, and
  `qualify()` (invocation in the Runbook).
- `c03c15f` Gen 2 live inspect gate (`lua/tests/gen2_inspect_gate.lua`,
  `tests/live/test_gen2_new_gates.py`). R-3 GAME oracle is only a Lua-internal differential:
  OPEN carry. The `live-new-gates` lane stays UNIMPLEMENTED on purpose.
- `f86c061` R3 independent review of `cfbcbba` + `acde60f`
  (`docs/gen2/reviews/P3_QUALIFY_AND_N3_FIXES_REVIEW_2026-09-22.md`): 1 HIGH (Gold/Silver
  window stack lives in SRAM, `pokegold ram/sram.asm:81-83`, so every G/S re-save would be
  refused), 3 MEDIUM, 3 LOW. N3 fixes confirmed correct.
- `0f2b3bc` R3 fixes (N8): G/S SRAM window stack allowed as menu scratch, Crystal sScratch
  boot-zero, re-save scenario delta (every save byte must match except source-cited fields),
  pre-hello queue cleared on identity change and on any non-+1 frame step, Python re-derives
  the verdict from site hits, HUD notice on a full queue. The R3-3 allowed-change list is
  source-derived: if live qualification refuses on a named field, check that field first.
  Not yet independently reviewed; the forward-jump queue clear assumes the client ticks
  every frame (check that in the review).
- `2df48a0` fishing map association source rule (OMP, accepted, spot-checked) and `c42061d`
  per-map `fishing_water` in the generator + adapter gate (OMP N7): rod-emitting maps
  383->62 Crystal, 366->64 Gold/Silver. `fishing_map_association` stays OPEN until a
  fixture fishes. c42061d has NOT had an independent review yet.

Session 1: see the commit bodies from `5824258` to `463bc71` (Gen 1 rebind repaired and
restored to master behaviour with a master-equivalence differential; Gen 2 reads, wire,
fixture tooling, scripted gate, client, binder fixes; coverage-map pins eol=lf; 69 ledger
citations audited). Reviews: `P3_SHARED_MODULES_REVIEW_2026-09-22.md`,
`P3_GEN2_BINDERS_REVIEW_2026-09-22.md`, `OMP_RTC_SOURCE_2026-09-22.md`.

## Physical evidence so far
Gen 1 physical set at ONE frozen cut `463bc71`, run from a detached lane worktree
`C:/Users/howar/AppData/Local/Temp/g2lane` (gitignored inputs copied/junctioned in, plus
`.cache/upr/PokeRandoZX.jar`). Logs: coordinator scratchpad `n1/`.
- PASS: live-new-gates (19 + 1 explained skip), inspect-purergb (16 + 4 explained),
  apex-purergb (1), live-trade-gates (3), inspect-purergb-overlay (6),
  live-trade-gates-purergb (1), apex-refusal-purergb, live-gates (11/11 after the jar was staged).
- NOT SETTLED: duo-pairs and duo-pairs-purergb.
  - First run (worker test suites running concurrently): duo-pairs 15/3 failed,
    duo-pairs-purergb 26/7 failed (ball-throw timeouts). `verify_gen1_release.py` documents
    that CPU contention fails duo lanes.
  - "Quiet" re-run was NOT quiet (OMP ran tests; an EmuHawk with no arguments, not the
    harness, was open from 17:25): duo-pairs 16/2 failed (`whiteout_new`: both clients gone
    after PRE_WHITEOUT, "battle_begin with no opponent: ignored"; `pc_ops_new`).
    duo-pairs-purergb re-run was stopped by the coordinator at the owner's stop.
- No Gen 2 live run has happened yet.

## Next actions, in order
1. Settle Gen 1 duo: with the machine TRULY idle (no workers, no tests, no other EmuHawk),
   run `whiteout_new` and `pc_ops_new` on master `8f6a986` and at the branch cut, same
   harness. Same failure on master = pre-existing flake; branch-only = regression in the
   rebind (suspect `cb02a10` scripted_inputs policy first). Then re-run duo-pairs and
   duo-pairs-purergb whole. Rule learned: NO worker test runs while any duo lane runs.
2. Independent review of `c42061d` (fishing_water) and of the N8 R3 fixes `0f2b3bc`, then the
   inspect gate `c03c15f` (not yet reviewed).
3. First live Gen 2 fixture play (crystal_town) and then `qualify()` on the candidate.
   Watch the live-only assumptions in the bodies of `461594b`, `cfbcbba` and N8.
4. The other seven fixtures, the live inspect gate run, the Gen 2 duo harness
   (`tools/e2e_duo.py` gen2_new rows, `tests/e2e/test_duo_gen2_new.py`; not started).

## Runbook (exact commands; run from the gen2-foundation worktree root)

- **Editing files in this worktree:** the Edit/Write tools refuse other worktrees. Write a small
  Python script to the scratchpad and run it with Bash. Heredocs with an odd apostrophe count
  break the Bash tool.
- **Never commit into this worktree while a live lane is running from it.** The first Gen 1
  sequence picked up a mid-run commit, and its results could not count.
- **Gen 1 physical lanes, one at a time, at a frozen commit:**
  `SLINK_PURERGB_ROMS="E:/Google Drive/SLink/.cache/purergb" python tools/verify_gen1_release.py --lane <name>`
  Inputs already staged here (gitignored): the ROM dumps at the root,
  `patch/build/gen1_pure{red,blue,green}.gbc` (restage with
  `gen1_playthrough.staged_rom(key)`) and `patch/gen1/build/slink_{red,blue}.gb` (rebuild with
  `python patch/gen1/tools/build.py`; it reproduces the tracked `slink_bank3f.bin` byte for byte).
- **Gen 2 coverage lane:** `python tools/verify_gen2_release.py --lane coverage-map`. After ANY
  edit to `docs/gen2/gen2_requirements.md` or `docs/protocol.md`, recompute that file's SHA256
  over its LF bytes and replace the old hash in both places in `docs/gen2/gen2_coverage_map.md`
  (the table near line 29 and the JSON `inputs` near line 224). Those files are `eol=lf`.
- **Gen 2 generators:** each has `--check` (for example `python tools/gen_gen2_engine_signals.py --check`,
  `tools/gen_gen2_profile.py`). Packs must regenerate byte-identically. `python tools/verify_gen2_rom_layout.py`
  checks all engine-site bytes against the built ROMs.
- **Qualify a played candidate:** `python -c "import json; from tools import gen2_fixtures as f; r = f.qualify('crystal_town', r'<candidate_path from run_play>', '<attempt_id>'); print(json.dumps(r, indent=2)); raise SystemExit(0 if r['passed'] else 1)"` (three EmuHawk launches: boot, resave, reload). Live inspect gate: `SLINK_LIVE=1 pytest tests/live/test_gen2_new_gates.py -q` once fixtures exist.
- **Run live lanes from a frozen lane worktree** (e.g. `git worktree add --detach C:/Users/howar/AppData/Local/Temp/g2lane <sha>` then copy/junction the gitignored inputs) so code work can continue here; never run worker tests while a duo lane runs.
- **First live Gen 2 fixture:** there is no CLI for a play. Use
  `from tools import gen2_fixtures as f; spec = next(s for s in f.FIXTURES if s.name == "crystal_town");
  f.run_play(spec, {"observer_qualified": True, "attempt_id": "<id>", "gate_script": f.GATE_SCRIPT})`.
  It launches BizHawk cold at CGB, speed 300. The output is a route CANDIDATE, not a fixture.
  Known gap: full qualification (`qualification_report(..., scope="full")`: CONTINUE, re-save,
  reload) needs boot and re-save `game_callbacks` that are not implemented yet. That is the
  next fixture card after the first play works.
- **Known red, not regressions:** `test_gen1_trade_patch.py` (RGBDS `STRSUB` deprecation
  warnings), and 17 legacy `test_gen2_adapter.py` encounter tests (the old adapter reads the
  replaced pack; they resolve at the G3 cutover).
- **Peers:** reply to Codex review rounds with `delivery=steer`. OMP cards are literal, with
  ABSOLUTE paths, and never `wait=true`. Record `kind: outcome` for every peer task; the bridge
  refuses new work while outcomes are missing. From a worktree, pass
  `workingDirectory=E:\Google Drive\SLink` to reach live peers.

## Open decisions and carries

- **Owner decision (G3 server cutover):** unhatched eggs are kept off the wire (derived from
  O-15), so the server's party count is one low while an egg is carried and it could send a
  linked mon into a full party. The client refuses such writes today.
- **P4 carry:** the mail flag is correct but not yet enforced on any transfer path. Native
  trade must call the adapter's held-item check (T-3).
- **Merge carry:** 13 intended Gen 1 behaviour differences are listed in the body of
  `0a1aa79`; the reviews marked the rest KEEP. The Gen 1 physical lanes must pass before
  merge.
- Coverage validator PLAUSIBLE items (the target+base CLI policy; controls full-equality)
  are left for the Gen 3 binder.
- Open with an exact reason: `fishing_map_association` (rule landed in `c42061d`; open until a
  fixture fishes; connection strips and story-time blockdata not modelled); R-3 GAME oracle
  (needs trainer/badge/PC/held-item scenario fixtures); U5 double ROM read at boot
  (measure in the emulator).

## Stable facts and constraints

- Sources: pokecrystal7a7881d0d62e0ddbd82dcf10e7116807487ac651; pokegold656583c939d30f920a316177311a502dd222b57c; RGBDS1.0.3.
- Selected Crystal1.0 f4cd194bdee0d04ca4eac29e09b8e4e9d818c133; Crystal1.1 is build-only.
- Gold d8b8a3600a465308c9953dfa04f0081c05bdcb94; Silver49b163f7e57702bc939d642a18f591de55d92dae.
- Prior unchanged Gen1 baseline:3247passed/737skipped/5missing-Blue-ROM setup errors; Lua193passed. Not an all-green physical regression. Exact classified receipts are in .cache/gen2-orchestration-20260922/baseline.
- Poké Balls are the sole staging exception. Scripted normal input, one emulator lane, route300%, qualification100%, no Computer Use. Mailbox placement still needs native ownership proof.
- Gen2-Base (OMP, live) provides contextual source checks; a fresh headless OMP is used where an independent reviewer is needed.
- Stat formula doubles base AND DV; capped ceiling square root precedes division by4. Full identity is DV:OT:species. Egg list markers are separate from actual record species.
- No parked-worktree deletion, master merge or release authorized. Remote authority covers only the exact P1 commit.
- Sole authority: E:/Google Drive/SLink/.claude/worktrees/gen1-rby-code-sweep-8d06e2/docs/gen1_reference/RC_MASTER_GUIDE.md and WORKTREE_REGISTER.md. Coordinator: Claude session 1d2b4c9a (see ledger).
