# Gen 2 implementation resume (updated 2026-09-22, stopping point)

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

- Gen 1 rebind onto the shared modules repaired and restored to master behaviour
  (`0a1aa79`, `e0b38b7`, `3c48b20`, `cb02a10`), with a master-equivalence differential that
  runs master's own files. Two independent Opus reviews plus closures:
  `docs/gen2/reviews/P3_SHARED_MODULES_REVIEW_2026-09-22.md`.
- Gen 2 reads, wire projection, fixture tooling, scripted fixture gate, client (candidate
  graph only), R2 binder fixes (mail list, per-title GetTreeMons limit, box re-assert):
  `17aeb62`, `92f5445`, `b6c5b87`, `461594b`, `d1cadea`, `cc04bb7`, `bf2d5e1`. Review:
  `docs/gen2/reviews/P3_GEN2_BINDERS_REVIEW_2026-09-22.md`.
- Coverage map: F-3 cells amended (`d2b023c`); input pins made checkout-independent with
  `eol=lf` (`58054c1`); the lane is green. Ledger citations corrected from OMP audits
  (`bf99768`, `d204b31`, `53e5659`: all 69 ledger citations audited, 9 corrected). RTC
  trailer facts: `docs/gen2/reviews/OMP_RTC_SOURCE_2026-09-22.md`.
- Gen 2 client on the candidate graph (`cc04bb7`) and signal-binder fixes (`dfb25f6`):
  boundaries keep finalized events, refusals are values not kill switches, faints carry
  identity, evolution qualified from the ROM's evolution table. **Not yet independently
  reviewed** (author tests only).

## Physical evidence so far

- **Gen 1 `live-new-gates` PASSED at `3c48b20`:** 19 passed, 1 explained skip, 0 failed.
- The rest of that Gen 1 lane sequence is **not evidence**: it picked up `cb02a10` mid-run
  and was stopped at the owner's stopping point. It found one real regression (the
  `ball_gate_new` park, fixed in `cb02a10`); its other failures were missing inputs, since
  staged.
- No Gen 2 live run has happened yet.

## Next actions, in order

1. Nothing is in flight. The signal-binder fixes (`dfb25f6`: boundaries keep finalized events,
   refusals are values, faints carry identity, evolution qualified) and both OMP ledger audits
   (`53e5659`: all 69 citations audited, 9 corrected) are committed.
2. Re-run the whole Gen 1 physical set at ONE frozen commit, with
   `SLINK_PURERGB_ROMS="E:/Google Drive/SLink/.cache/purergb"`, one lane at a time:
   inspect-purergb, apex-purergb, duo-pairs, duo-pairs-purergb, live-gates,
   live-trade-gates, inspect-purergb-overlay, live-trade-gates-purergb,
   apex-refusal-purergb. That is the gate for the Gen 1 rebind ever reaching master.
   `test_gen1_trade_patch.py` is red on RGBDS `STRSUB` deprecation warnings; it's
   pre-existing and not from this branch.
3. First live Gen 2 fixture run (crystal_town) through `tools/gen2_fixtures.py` and
   `lua/tests/test_gen2_scripted_gate.lua`. Expect route timing and menu parsing to need
   live tuning; the list of live-only assumptions is in commit `461594b`.
4. Independent (non-author) review of the Gen 2 client `cc04bb7` and binder fixes `dfb25f6`
   before the live inspect gate. It can run in parallel with steps 2-3; Codex is a natural
   reviewer once it is online.
5. Fixture qualification callbacks (boot, CONTINUE, re-save, reload) so a played candidate
   can become a qualified fixture. Then the other seven fixtures, the live inspect gate and
   the Gen 2 duo harness.

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
- Open with an exact reason: indoor fishing map association; U5 double ROM read at boot
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
