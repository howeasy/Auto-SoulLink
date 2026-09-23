# Gen 2 implementation resume (updated 2026-09-23, session 7: all three titles pass O-22; first C<->C duo run in progress; paused for compaction)

## Who coordinates

**Claude is the Gen 2 orchestrator** (owner ruling 2026-09-22). Session 4-5 coordinator: Claude
session 5efbb71c ("Gen 2 Boogaloo"), working from THIS worktree. Workers: up to 3 Haiku / Opus 5.5 /
Sonnet subagents at a time (model set explicitly), OMP (Gen 2 session; coding + review, one card at a
time), Codex thread **`Gen2-Part2`** (NOT "Gen 3 Part 2"). Only the coordinator edits the sole ledger:
`C:/Users/howar/.claude/hooks/slink/RC_MASTER_GUIDE.md` (checkpoint) and `WORKTREE_REGISTER.md` there.
This note summarises it; it is not a second ledger.

### Peer channels

- **Codex `Gen2-Part2`:** live `request`s are refused (NO_LIVE_PEER); send cards as `note`s with a
  `queueKey` and read answers with `kind: transcript`. It is a SAVED conversation: a note is read only
  when its desktop opens it (it went idle ~62 min at session end). Close hook tasks with
  `python C:/Users/howar/.claude/hooks/orchestration.py done note:<queueKey> --session <id>`.
- **OMP (Gen 2):** the name `Gen2-Base` and its session id CHANGE between cards (replies came from
  01a0c535..., 01a0ce10..., 01a0ce2f...); when the name does not resolve, try the id from its latest
  PEER REPLY. `kind: peers` lists only `Gen3-2` (the Gen 3 lane's: never cross). OMP works in its own
  detached worktree `C:/Users/howar/AppData/Local/Temp/g2omp` (branches omp/gen2-O6, omp/gen2-U4b);
  the coordinator cherry-picks. `request` with `delivery: live, wait: false`; `outcome` every task.
- **Machine sharing:** other lanes run EmuHawk on this machine. The Gen 3 lane's
  `tools/gen3_fixtures.py` once ran `taskkill /F /IM EmuHawk.exe` and killed five Gen 2 gate runs; the
  Gen 3 coordinator fixed it (PID/run-dir scoped). Symptom of a foreign kill: result file stops early,
  no RESULT line, no crash record. Diagnose with the EmuHawk parent command lines (Win32_Process).
- **Never shell-background (`&`) a live run from the Bash tool:** it survives the call, and a second
  run then shares `patch/build/<gate>_result.txt` (one all-eight run was voided that way). Use
  `run_in_background` and one run at a time.

## Where things are

- Branch `codex/gen2-foundation`, not pushed since P1 (`93ccb8e`). Local master `7957c24` merged in at
  `1bb69b4` (clean; unit suite 6026 passed / 15 skipped).
- **Pinned pret sources are `.cache/gen2-build/{pokecrystal,pokegold}`** (7a7881d / 656583c).
  `.cache/pret` holds OTHER commits: never cite it.
- Coordinator lane drivers (gitignored): `.cache/requal.py <suffix> [names]` = qualify() of each
  COMMITTED fixture with its original played receipt (no replay); `run_fixtures.py` (session scratchpad;
  replay + qualify + stage). Staged inputs as in the runbook.

## Done this session (7) — toward the first PHYSICAL Gen 2 duo

- **U1 PHYSICAL on all three titles**: Crystal `7c08529`, Gold `eac806c`, Silver `92318de`
  (`tests/fixtures/gen2/receipts/{title}.engine_sites.json`; U1-GS `9a2643c7` made the gate per-title; each title
  keeps its own rows — Silver's capture sites sit 2 bytes below Gold's). `S.PHYSICAL_TITLES` maps each title to its
  own receipt.
- **Owner ruling O-23** (`b7f8459`): Silver's U2 gate = Gold's write-window receipt while their checkpoint rows are
  identical. => Crystal, Gold and Silver ALL satisfy O-22.
- **U3** `1f07f71e` + **U3b** `3352cab3`: Crystal, Gold AND Silver run through `Entry.build` as production (receipts
  shipped under `data/games/gen2_*/receipts/`, byte-identical to the fixtures; only party_faint->party_hp writes;
  box ops NACK; only U1-proven sites register). Non-author review pending.
- **U5** (in flight, uncommitted at the pause): title-scoped launcher branch in `lua/slink.lua`, server row flip,
  Gen 2 release-manifest rows, legacy-route test updates (input: `docs/gen2/reviews/OMP_U5_CUTOVER_FACTS_2026-09-23.md`).
- **H1** `7b9cab48` Gen 2 duo driver (`lua/tests/duo/duo_gen2_main.lua` header = contract; Sonnet APPROVE).
  **H2** `23fbc80e`+`469dad08` independent oracle `tools/gen2_duo_oracles.py` (Sonnet APPROVE; carry H2b: defensive
  checksum inside `link_oracle`, document the removed OT-differ guard). **H3** `674303bb` (Codex) `gen2_new` family +
  `link` lane in `tools/e2e_duo.py` + `tests/e2e/test_duo_gen2_new.py`; Crystal server routing is a lane-local
  override in the child process until U5; duo unit selection 428 passed.
- **N18** `8c3b0cd` committed-receipt validators (27 passed with all receipts). Codex static-canon DESIGN done
  (pack-owned `static_<lowercase_map_const>_<species>`, keep `legend_245`); OMP implementing it
  (`omp/gen2-static-canon` in `C:/Users/howar/AppData/Local/Temp/g2omp`, card cx-7bde9c30) — cherry-pick after review;
  its signals.lua hunk is the static-zone function only.
- Collaboration mode (owner): parallel workers message each other directly by agent id (cc coordinator); Codex is
  steered (`delivery: steer`) for every mid-card update.

## Done in session 6 — Crystal O-22 gates PHYSICAL

- **U1 Crystal engine-hook proof PHYSICAL** (`7c08529`, `tests/fixtures/gen2/receipts/crystal.engine_sites.json`):
  wild_ready, capture_party, capture_party_finalized, battle_end, save_completed fire at their pinned bank/PC on
  a scripted walk -> wild battle -> Poke Ball catch -> native save; frame alignment armed == callback; party count
  changes one frame BEFORE the capture callback (TryAddMonToParty increments first, GeneratePartyMonStats crosses a
  VBlank); negatives refused. Live-found fixes: U1c `41da2d6` (the battle menu is a 2x2 grid the shared parser
  misread), `a5392d4` (probe control from the wild_ready party count), `28ec846` (wrapper field).
- **U2 write windows PHYSICAL**: Crystal `6ba4527`, Gold `7718619` (covers Silver while its checkpoint rows stay
  identical; Gold sha pinned). Receipt v2 carries raw window records, `M.qualified` recomputes them; covered
  controls: idle reacquisition + warp/Continue (party_hp, box_deposit writes). U2b `8f84aeb` (review hardening),
  U2c `a76f299` (post-save snapshot: Gold/Silver rewrite SRAM window stack + sScratch after the flush).
- **N17** `4f6846ec` shared scripted gate reads the 2x2 battle menu at source geometry (valid for C/G/S);
  **N17b** `7a744a7` U1 gate uses the shared reader.
- **U4b cross-title per-player data** fixed: `917321b` (Codex, per-player acquisition rules + bind after
  acceptance) and `434c678` (reset/rollback close live sockets so every gen re-hellos; the first fix locked out
  connected Gen 1/Gen 3 clients) — guard review APPROVE; `/slink-test 3` 525 passed.
- Facts: `OMP_U1_BATTLE_FACTS_2026-09-23.md` (Crystal battle UI sequence; Gold/Silver engine-site parity:
  G/S battle-menu anchor `_2DMenuInterpretJoypad` 09:419C, Silver capture sites 2 bytes below Gold's).
- Open design (Codex card gen2-static-canon, read-only, in flight): equivalent statics get different area ids
  per title (Gold Lapras `static_799_131`, Crystal `static_807_131`) -> cross-title pairing needs a canonical id.

## Done in session 5 — commit bodies + docs/gen2/reviews/ carry the evidence

- `1bb69b4` merge master 7957c24 (OMP O4: no semantic conflict). Owner: master's pixel-font HUD is
  expected -> `ac097cd` Gen 2 NEW ENCOUNTER banner newline-separated like Gen 1.
- `347c800` HOLD comment: the walk step is 8 frames (OMP O3, StepVectors); route walks never use press().
- `e2a6738` **N16** server refuses an unknown `artifact_kind` string (guard APPROVE; carry: pre-N15
  persisted kinds load unvalidated).
- `4ae0f7f` **N14b** strict re-save rules + fresh-fixture guards (Sonnet APPROVE). `e01ae24` **all eight
  receipts re-qualified under N14b**, 4/4 stages each, fixture bytes unchanged.
- **Live inspect gate 8/8 PASS at `0c9eabc`** incl. the OMP O6 display oracle (Trainer Card ID/name,
  stats gender/shiny, item line) on Crystal/Gold/Silver -> R-3 tilemap half + R-5g display half
  PHYSICAL (badges = OAM and PC box header stay OPEN). Live-found fixes: `71dbc44` G/S stats label
  `StatsScreen_LoadPage.joypad_loop`, `81d7892` 12-frame display HOLD, `195544e` START menu reads
  POKéMON (the `#` code expands to POKé), `0c9eabc` items.json (legacy item_names.json is Crystal-only).
- Owner ruling **O-22** (`4f3a2b6`): conditional production admission — U3 admits a title only after
  its U1 + U2 PHYSICAL proofs pass.
- P3b.7 plan from Codex (`7265ba0`, docs/gen2/reviews/P3B7_PLAN_CODEX_2026-09-23.md): cards U1-U5, H0-H4.
- **U4** `09d4339` server title binder (OMP APPROVE); **U4b** `c0d8998`+`adbeb88` per-player title data
  for cross-title pairs (O-16), review queued with Codex (note gen2-U4b-review).
- **H0** `afcc568` (Codex) neutral duo evidence contract per family (Sonnet APPROVE).
- **U1** `a867df4` + **U1b** `e92b182` Crystal engine-hook proof + hardened receipt (Opus review of U1;
  U1b answers it). **Live U1 run FAILED** (`.cache/u1-live.log`): walk OK, `wild_ready` fired once at
  its pinned bank/PC (first PHYSICAL site hit), then the BATTLE phase made no bounded progress (no
  screen dump in this gate). Likely: a battle screen with no mapped UI kind falls through to the
  overworld wait (lua/tests/gen2_frame_align.lua ~:131-175).
- **U2** `e2952725` write windows (MODEL only): Opus review REQUEST CHANGES (2 HIGH receipt trust, see
  ledger gen2-U2-review). Source correction to OMP O8: a START-menu frame DOES fail predicates
  (CheckMenuOW -> CallScript sets wScriptRunning; PlayerEvents .ok sets wScriptMode).
- Facts recorded: N12B_OPEN_FACTS (Celebi unreachable on pinned 1.0; static re-fight table; Electrodes
  consumed on a win), OMP_R3_R5G_DISPLAY_FACTS, OMP_U2_WRITE_WINDOW_FACTS (+O8; Bug Contest bit = 2).

## Next, in order

1. **First physical C<->C duo — the Soul Link FORMED on hardware (run 1, 2026-09-23)**: both production clients
   (A crystal_battle, B crystal_battle_ot2) walked Route 29, caught a Rattata each, saved; the server linked
   `route_29` A 0C6D:B541:13 <-> B 0F5C:AC24:13 (alive, area linked); both drivers RESULT PASS; witness validator
   PASS. The run was marked FAIL only because H2's oracle counted `mon_stats` as an extra acceptance -> fixed
   `855c91e`; the fixed oracle PASSES on run 1's real output (data dir C:/Users/howar/AppData/Local/Temp/
   slink_duo_link_o5ax1k53). **Run 2 FAILED on A: "no Poke Ball left in the pocket"** although A booted from the
   exact fixture (.bak == fixture): the pack's Ball pocket was read while item names were still garbage tiles
   (`items=- cursor=nil`, only `CANCEL` decoded; log .cache/duo-gen2-cc-link2.log) -> a pocket-draw readiness
   race in the pack reading (lua/tests/duo/gen2_route29_inputs.lua / the shared pack UI kinds, F.ball_cursor).
   Also A's hello carried `ball_count: 0` with `in_battle: true` — check the client's in-battle ball count read.
   **CAVEAT: run 2 is contaminated** — it ran 14:53-14:56 while U3b's Gold/Silver edits to lua/gen2/{entry,client,run}.lua
   were uncommitted in the tree (committed 14:56:48 as `3352cab3`); they change hello readiness, which may explain A's
   odd hello. NEXT: wait for U5 to commit (its server/launcher edits are in the tree), then rerun the duo on a CLEAN
   committed tree; only if A's pocket race recurs, cut the Ball-pocket readiness card (stable decodable item list,
   bounded) + the in-battle ball_count check.
2. Reconcile U5 (commit + slink-adapter-guard review + Gen 3 unit check) and U3's final report (G/S admission scope);
   non-author review of U3.
3. Gold/Silver admission + route if U3/U5 did not include them; then G<->S duo and the C<->G `link` (O-16); OMP
   static-canon-impl cherry-pick + review; H2b; the H4 lane closure; gen2-M1 Gen 1 duo A/B.

## Runbook (exact commands; run from this worktree root)

- **Editing:** the session now lives in this worktree, so Edit/Write work here. Git is fenced to
  this worktree: run git commands plainly, without `-C` or `cd` to other checkouts.
- **Machine load rule:** NO worker/peer test runs while any emulator lane runs (contention voided
  three duo runs). Tell workers "hold tests until lane free", then release them.
- **Gen 2 live runs: run from THIS worktree at a clean committed HEAD**, not a junctioned lane: `run_gb_gate._gen2_plan`
  requires the RESOLVED ROM path inside REPO, and a junctioned `.cache/gen2-build` resolves outside. Diagnose stalls with
  `SLINK_GEN2_TRACE=1` (trace every 30 frames; screen dump on a failed stage in `patch/build/test_gen2_scripted_gate_result.txt`).
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
