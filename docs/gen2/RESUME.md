# Gen 2 implementation resume (updated 2026-09-23, session 8 late: FIRST PHYSICAL Gen 2 PRODUCTION WRITE (gen2_faint C<->C + G<->S); paused for compaction)

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

## Session 8, late: the first physical production write (compaction point)

- **MILESTONE `554a2290`: `gen2_faint` PASS physically on C<->C and G<->S.**
  - A's linked mon faints in a wild battle, and the production `battle_faint` site fires.
  - The server propagates the faint, and B's production client zeroes the partner mon via the U2 checkpoint write permit.
  - The independent PYDEC oracle checks both saves. The pair ends MEMORIAL: owner-approved, because Gen 2 NACKs memorialize until BOX lands.
  - C<->C: A `1288:B541:10`, B `BD57:AC24:A1`. G<->S: A `01A5:C4A6:10`, B `F89B:C78C:10`.
- **Link re-runs with the fact-bearing PYDEC line:** C<->C `91ea1919`, G<->S `5c408840`, C<->G `d3270118`.
- **C<->G `gen2_faint` is still FAILING on the Crystal A side.**
  - Run 1: "the target survived 3 battles".
  - Diagnostic run 2: "UI is not valid in phase walk: yes_no". Suspects: an unexpected YES/NO while walking, e.g. a Crystal phone call (OMP O19 said that is possible only after ~20 in-game minutes) or a battle prompt.
  - The LIVE worker holds the lane worktrees `.claude/worktrees/gen2-{cc,gs,cg}-faint-link`.
- Landed since the link milestone:
  - U1d `0cd791e0`: battle_faint PHYSICAL C/G/S.
  - O-24 server faint repair (`6e9bff5b`, `25bfca25`: 60 s window, budget 3, 5 min refill, `faint_repair_stalled` on status).
  - O-25 AP refused plus the legacy Gen 2 REMOVE: `aa9c960b`, `d8028dbf`, `c6201179`, `c84f41b4`, cleanup `b5ff1b55`/`e545616c`, legacy duo chain `d8bcfb83` (Codex H6).
  - gsc fixed-species gift `63c2558d`.
  - H4b live-new-gates `034728e7`.
  - H5 faint lane/oracle `3a64b0e3` (Codex).
  - H1c faint driver `4f1ea1b4`..`ceb4825a`.
  - Gen 1 fixes: `3941198c`/`a32dc385` (force_faint arrival order) and `44bf25d6` (stale SFX gate).
- Owner rulings this session:
  - O-24: server faint repair.
  - O-25: refuse Archipelago Crystal.
  - O-26: shiny_bonus is a recorded limit.
  - O-27: the P4 decisions (mailbox at WRAM0 C $CFD8 / G,S $C1D9, Gen 1-shape trade, refuse mail/unholdable items, patched<->patched pairing, one DelayFrame sound site).
  - Unlimited emulators, but the machine crashed the coordinator twice under ~6 EmuHawks + 5 agents. Keep live lanes at 2 with staggered starts.
- Plans/facts:
  - `docs/gen2/reviews/DUO_SCENARIO_ROADMAP_2026-09-23.md` (SCN)
  - `docs/gen2/reviews/P4_PLAN_2026-09-23.md`
  - `docs/gen2/reviews/OMP_O21_U1E_SITE_FACTS_2026-09-23.md` (U1e order: poison_faint < gift < evolution < npc_trade < egg_hatch < whiteout; P4 START row grows in bank 4; receptionist = the 2-byte object pointer; SFX hold on wMusicFade)
- In flight at the pause:
  - LIVE: the C<->G faint diagnosis, then the live `gen2_admit_wrong_rom` (Codex H7 `2dc959d0`).
  - BOX: the box executor `0bd77db6` plus a pending composition commit, and 2 live lanes (C, G) for U2 box_runs.
  - SCN: wave A drivers done (`d1567fc1` admit_wrong_rom, `c58b55fb` reconnect, `33d03063` soft_reset), now the wave B clause drivers.
  - P4.1a build tool (Sonnet), P4.1b mailbox census (Sonnet).
  - Codex: H8 reconnect (G<->S wrong_save fails closed until `gold_battle_ot2` exists) -> H9 soft_reset -> P4.1c asm skeleton.
- Queued (not dispatched):
  - a pre-live review of the wave A drivers (the Gen 2 OMP session closed)
  - the U1e poison_faint + gift party-row proof
  - the `gold_battle_ot2` fixture (play + qualify)
  - the full unit suite

## Done this session (8) — every O-16 pair linked physically

- **MILESTONE `8363d262`: G<->S and C<->G `link` PASS** (first attempt each; drivers PASS, SAVE_WITNESS, PYDEC PASS).
  G<->S: Gold A 6DB1:C4A6:A3 HOOTHOOT <-> Silver B F5D0:C78C:13 RATTATA. C<->G: Crystal A 354D:B541:13 RATTATA <->
  Gold B 2B42:C4A6:A3 HOOTHOOT. Receipts `tests/fixtures/gen2/receipts/duo_link_{gs,cg}_*`, registered in
  `tests/gen2_release_requirements.json` (H4 matrix `python tools/verify_gen2_release.py --duo-matrix`). Run from a
  detached lane worktree with `.cache/gen2-build` COPIED in (not junctioned); that works for Gen 2.
- Landed:
  - `3d6f09d1`: static-canon (OMP), title-independent static area ids.
  - `f6bb495a`: H1b driver for Gold/Silver.
  - `0a9eb50e`: H3b pairings `gen2_gold_silver` / `gen2_crystal_gold` (Codex); production route, override removed.
  - `a1a5f8ea`: H2b oracle, per-side title.
  - `49a5c69d`: a pre-U5 persisted run is REFUSED (UnsafeGameMigration), because legacy gift/daycare area ids
    differ from gen2_gsc's.
  - `abec68c0`: H4 duo matrix.
  - `55107069`: P3b.8a manifest + extracted-bundle boot + census `docs/gen2/reviews/P3B8_CUTOVER_CENSUS_2026-09-23.md`.
  - `6cafd2b1`: U3 nit.
  - `c5275252`: O13 witness test.
- Reviews: U5 guard APPROVE; U3/U3b APPROVE (214/214).
- Reviews still open: O16 (cx-4373a801) REQUEST CHANGES on H4 + H2b.
  - The PYDEC receipt names nothing, so a copy passes.
  - `fixture_sha256` is unchecked.
  - Gold and Silver saves are layout-identical.
  - Fixes are routed: Codex (oracle/lane, H5) and H4b (matrix). The 3 pairs' pydec receipts get re-run after.
- Gen 1 (owner: "You own Gen1 in the sense you have to make it work in the shared framework YOU created"):
  - `3941198c` + `a32dc385`: a battle-held force_faint keeps its arrival place ahead of a later memorialize
    (OMP O12; Gen 3 684bbb7a is the same shape; folds into lua/core at convergence). Gen 2 is not affected.
  - `44bf25d6`: the Gen 1 SFX gate case A was stale after f6229e77 (notify code 4 = $8F on CHAN8). Live
    red/blue town PASS.
- Owner ruling **O-24** (`830289e7`): server-side force_faint repair (re-issue when a DEAD-linked mon shows alive;
  bounded; dead stays dead). The card is in flight.
- Owner/Gen 3 ruling: shared layers converge after Gen 3 G4. Don't add lua/core-duplicating modules.
- Facts: `docs/gen2/reviews/OMP_O15_FAINT_FACTS_2026-09-23.md` (Growl-spam faint, MIN_DAMAGE 2 -> <=7 hits;
  switch-in route; per-title addresses).
- **Blocker found for gen2_faint:** production registers only U1-proven sites, and `battle_faint` is not proven.
  Card U1d (Opus) is proving it live per title.

## Done in session 7 — toward the first PHYSICAL Gen 2 duo

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

1. In flight:
   - U1d `battle_faint` PHYSICAL receipts (needs the emulator lane).
   - H1c driver + Codex H5 lane/oracle for `gen2_faint` (plus the O16 oracle fixes and lane-scoped result files).
   - H4b: live-new-gates lane + O16 matrix fixes.
   - SRV-O24 server force_faint repair.
2. Then run the live `gen2_faint` duo per pair (the first physical production WRITE: party_faint -> party_hp at the
   U2 checkpoint). Re-run the `link` pydec receipts under the new note, and register everything in the matrix.
3. Carries:
   - P3b.7 scenarios beyond link/faint (ball_gate, boxed_capture, ...; `duo-pairs` stays UNIMPLEMENTED).
   - P3b.8 deletions wait for the owner (crystal_ap still uses the legacy client/adapter).
   - `tools/verify_profile_addresses.py` needs its own card.
   - `test_gen2_adapter.py` REPLACE is pending.
   - gen2-M1.

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

## Session 8, night (2026-09-24): duo matrix fully receipted

- `python tools/verify_gen2_release.py --duo-matrix`: every pair x scenario cell RECEIPTED (a69f3526):
  admit_wrong_rom, gen2_faint (memorial preimage), reconnect, soft_reset, type/gender/species clause on C<->C, G<->S, C<->G.
  `--new-gates`: every engine-site, write-window and qualification receipt bound and PHYSICAL.
- P4 on the overlays (final sha1 C 3e620195, G a9f3a26f, S b63d374a; 7af14c7d): panel gate PHYSICAL (9eba863f),
  native sound gate PHYSICAL (032b32ee). BUILT admission rows stay FUTURE until P4.4.
- Product fixes found live: hello flap in battle (c7c3fe08), box-withdraw loss window Gen 2 (699930b6, live 368547fa)
  and Gen 1 (84a9f88a), clause violation events (468bab0f), evolution-escape of a deferred faint (e0442e96).
- Owner rulings O-28 (SLINK replaces EXIT), O-29 (phone easter egg, plan 427d1a0a + amendment 328a87c0),
  O-30 (all faints land in battle; Gen 1 19d87a24; Gen 2 USEITEM at `call DetermineMoveOrder`, facts
  docs/gen2/reviews/INBATTLE_FAINT_FACTS_2026-09-23.md).
- In flight at this note: U1e Gold via gold_battle_errand (then U1f PC/change_box/whiteout), in-battle faint
  phases 3-4, P4.5c phone Lua, W6 write-watch, Codex P4.3a trade asm (then P4.5b phone asm).
- Next: P4.3b trade overlay, P4.3e trade duos, linked_faint_active duo, P4.4 promotion, re-pin panel/sfx gates after
  each overlay publication (`SLINK_LIVE=1 pytest tests/live/test_gen2_panel_gate.py`, `.../test_gen2_sfx_gate.py`).

## Session 8, late night (2026-09-24): break point, workers still running

State at this note (HEAD ~4a157d4a+; --new-gates and --duo-matrix green at last check):
- Owner rulings added: O-30 all faints land in battle (Gen 2 USEITEM at `call DetermineMoveOrder`; Gen 1 19d87a24);
  Perish Song rejected for Gen 2 (facts §6 of docs/gen2/reviews/INBATTLE_FAINT_FACTS_2026-09-23.md). Contest = kill
  on ContestReturnMons; Battle Tower = kill in battle + checkpoint re-zero.
- In-battle faint PHYSICAL on C/G (S follows Gold): e0442e96, a8e93be7, ade01a6e. Regression duos still pass (9e38810b).
- poison_faint PHYSICAL on all three (G via gold_battle_errand, a7bf1773). Gift deferred post-RC.
- P4: trade asm bd6c68b1 + phone asm, published d09e76c1 (C 651dc6bf, G d563669e, S 76c6c112, caps 31); panel +
  sfx re-pinned on them (4a157d4a); trade binder ff576e02/8c561345/ed7f87c6; phone Lua 2f1c018e/2173e3f1/f24b2a2b.
- Workers still running at the break (owner: "let them work"):
  U1f PC/change_box/whiteout (then crystal/crystal_ot2/silver errand fixtures for trades);
  W6 mailbox write-watch (then P4.5d phone gate);
  LIVE3 gen2_faint_active (driver 9ea2a319; waits on Codex H11 lane);
  TRADE-RECON server uncertain-trade reconciliation (shared server);
  TRADE-DRIVER P4.3e drivers (contract: coordinator scratchpad p43e_driver_contract.md, also relayed);
  Codex: H11 then P4.3e harness; OMP: P4.3a adversarial review (cx-a14b449a).
- Open owner decision coming: trade-evolution / held-mail specimens may be unreachable early -> recorded limit or long play.
- Shared-file commit rule: files several workers edit are staged with `git apply --cached` (own hunks) and committed
  without a pathspec; `git commit -- <path>` takes the whole working-tree file.

## Session 8, day 2 (2026-09-24): compaction point, 7 subagents running; Codex + OMP DOWN

Owner: Codex and OMP are down ("only you and your subagents"); up to 7 subagents allowed. Rulings since the last
note: O-31 disclosed test-only setup (HARNESS_WRITE) for trade-evolution + D3 refusal (26564aed).

Landed since 60aebf0b (all physical unless noted):
- U1f PC sites + whiteout_before_heal on all three (C 3dd70162, S 2caf9126, G a882a763): 18 sites per receipt.
- gen2_faint_active duo cc/gs/cg (8ba39408, 2e1bbf56, 3fca3cbd); duo matrix fully receipted (8 scenarios x 3).
- W6 mailbox write-watch C/S 8e83b202, G bf655ef2; phone gate C/G/S eb49da00; panel/sfx re-pinned 4a157d4a.
- Trade-ready seeds: crystal/crystal_ot2/silver/gold *_battle_errand (8b83ff52, 7e697c98, b6930da8, a7bf1773).
- Server uncertain-trade reconciliation 1ac09296 + 9a436c95 (MODEL). P4.3e harness pieces 9c182ef2, 78aa49bb,
  9debf1d5 (Codex); trade drivers e9e914fb + d482fd37 (MODEL; contract in coordinator scratchpad p43e_driver_contract.md).

Running at compaction (subagent ids for SendMessage):
- HARNESS a4b25b9791322bccf: took over Codex's UNCOMMITTED P4.3e runner/oracle (tools/e2e_duo.py, gen2_trade_oracles.py,
  tests) + owns all Codex trade helpers + verify_gen2_release.py/release requirements; register 7 trade cases.
- TRADE-ASM a301092ac0ba8f1ce: receptionist host-wait bounds (30 f -> >=300 f), republish overlays, re-pin
  panel/sfx/phone/W6 (W6 U1 leg on the U1f chain for all three).
- TRADE-HARDEN a2e4b167c1a20a405: server cancel on proposer leave (one-sided-commit bug), trade_done uncertain fast
  path Gen 1 + Gen 2, server journals trade_uncertain for explicit claims.
- DRIVER-ROBUST a95e01a5592ddb1eb: shared ledge helper (route_facts fingerprints unchanged) + poison-leg flake.
- EVO-U1 ab5b9af5b6ee52bcc: prove the evolution engine site on C/G/S (Caterpie/Weedle L7) -> production key_change.
- DUO-WAVE-C abba0c5b5800bffe2: pc_ops / changebox / whiteout / poison duos (registration via HARNESS).
- Next after HARNESS + TRADE-ASM: a LIVE worker for trade lanes (gold-seed receptionist smoke, then G<->S trade_new, ...).

Queue: trade_problem status banner (UI lane), conflict admin-resolve, ship errand qualification reports if needed,
P4.4 promotion (owner G4 signature). Commit rule on shared files: `git apply --cached` own hunks, commit without a
pathspec. End-of-turn orchestration hook: Codex/OMP removed from tracking (peers down).

## Session 8, day 2 (2026-09-24, afternoon): usage-limit stop; resuming at 3 subagents

A session usage limit (~14:15Z) stopped every worker mid-step; no emulator/python process survived. Owner: resume with at
most 3 subagents (Haiku/Sonnet/Opus), no Codex/OMP. Uncommitted WIP from the stopped workers remains in the tree, owned by
its worker; resume each worker by agent id (SendMessage keeps its context) rather than re-dispatching.

Owner rulings today: O-32 (Gen 2 bench death immediate, PHYSICAL 0752a3ab), O-33 (synthetic setup fixtures allowed,
disclosed SYNTH), O-34 (native C<->G/S trades allowed and tested on all three pairings), O-35 (a PC release kills and
memorializes the partner). Coordinator: contest trade refusal is MODEL-only (f7597d62).

Landed today (highlights): trade asm review fixes 9805ac1c; server trade hardening (7de364f0 .. 2676c2f9); O-30 follow-ups
00c9373c/4e6aea39; Gen 1 forced trade save 61a693c4/6a4269d8 + receipts ff4df383; release lanes wired 71773b26/bad46a70,
bundle ships Gen 2 UPS f4f1167d, promotion path 6f9e5579; first PHYSICAL native trade G<->S (trgs2; oracle fix bec9eea2);
pc_ops cc PHYSICAL 84c18cb2; Fable invariant review 7b36cf2b with fixes 15f1e786, 14df4aee, 3b5b5a5a, 779c73c2, 7e9e5543;
synth builder ca6c2229; engine-site receipt v2 050caf08.

Running (resumed): INV-SERVER ada59c171d19b1955 (O-35 + Fable server minors), INV-CLIENT ab3f54b5bb3d2e92d (MINOR-7
durable dead-key re-zero), TRADE-ASM a301092ac0ba8f1ce (single re-pin of panel/sfx/phone/W6 on 9805ac1c; W6 Silver left).
Resume queue, one per freed slot: U1G ab5b9af5b6ee52bcc (synth grass/kyle/bill runs, signals v2) -> TRADE-DRIVER
a925de0c09c73c33f (trade matrix G-S, C-C, C-G) -> DRIVER-ROBUST a95e01a5592ddb1eb (hanging test_gen2_duo_driver silver case)
-> DUO-WAVE-C abba0c5b5800bffe2 (changebox, C-G registration, path guard, pc_ops O-35 flip) -> FIXTURES-LANE
a8a6b740b0e396f49 (reapply scratchpad/fixtures_lane_staged.patch) -> RELEASE-LANES a4d67676aa73f2900 (O-34 rows,
CODE-DIGEST) -> DUO-MATRIX-REPROOF a29f6e1c21f776ce9 (9 stale cells + trainer variant) -> DUO-WAVE-D abbc4cf2cb77a0b05
(ball_gate) -> GEN1-RECEIPTS aa417b5feac05a49c (pureRGB batch). EVO-U1/U1G resume brief: scratchpad/evo_u1_resume_brief.md
(superseded by U1G synth plan). Lanes: short non-Drive paths (BizHawk MAX_PATH silent SaveRAM failure).

## Session 8, day 2 (2026-09-24 ~20:25Z): compaction point; heading to the MAJOR milestone

Owner: stop only at a MAJOR milestone = release evidence complete (every verify_gen2_release lane green except the owner G4
signature). Up to 3 subagents (Haiku/Sonnet/Opus); OMP headless allowed for reviews and small code (its model tier
varies; ALWAYS validate: check findings at file:line, review the diff, scan for raw control bytes, run the tests
yourself, commit by pathspec). Rulings today: O-32..O-36 (O-36: emulator speed as high as needed; qualification 100%).

Landed since the last note (highlights): U1G engine sites PHYSICAL C/G/S from synth fixtures (cf4ef58e); ALL 21 native
trades PHYSICAL C-C/G-S/C-G (a9c4a64c .. bd5f0f84; C-G registration 5e6d5382); wave-D duos ball_gate/egg_hatch/gift/
boxed_capture/npc_trade PHYSICAL C-C+G-S; wave-C cc changebox/whiteout/whiteout_rebuild/poison + gs changebox; W6 Silver
clock fix 253d4e99/164f78b2; Fable + OMP fixes (INV-SERVER/INV-CLIENT/KEY-SCOPE 71d68454 + 2b8fcf0f c6c84dc5 c26012ca,
BOX-MEMORIAL 57e292dc); EMU-SPEED (preflight 375 s -> 9 s: 222956d2 db3075f2; trades 388 -> 184 s: d0633bf7; 3+
parallel duo lanes; --speed-percent 70439d4f); oracle rollover b661fcdd.

Running at compaction (resume by id with SendMessage; context intact):
- DUO-WAVE-C abba0c5b5800bffe2: gs/cg poison, whiteout(+rebuild), changebox; pc_ops rerun after 57e292dc.
- RELEASE-LANES a4d67676aa73f2900: CODE-DIGEST first (tools/gen2_code_digest.py) -> integrate scratchpad
  fixtures_lane_staged.patch (fixtures lane) -> all release rows (scratchpad release_lanes_resume_additions.md items 0-9)
  -> clock-setup-v1 check -> PROMOTION-HARDEN verify side (G4 signature parse, lane completeness).
- FINAL-SWEEP a29f6e1c21f776ce9: finish faint_active trainer variant; build the parallel final-sweep driver; dry-run 2
  cells; WAIT for the coordinator's "freeze".
- OMP: cx-8db7d326 (stack canary hardening delegate: oracle/gen2_trade.lua/tests), cx-7d8b0e9a (PROMOTION-HARDEN admission
  side: tools/gen_gen2_admission.py + tests), cx-7fe36bd8 (review 57e292dc), cx-4e252daa (re-review KEY-SCOPE-2).
  Queued for OMP after RELEASE-LANES commits day_clock: apply day_clock to the plain test_gen2_frame_align Silver U1.
Then: CODE FREEZE -> FINAL SWEEP (all duo/trade/gate cells with CODE_DIGEST, 3-5 parallel lanes) -> Gen 1/pureRGB receipts
(stale after 61a693c4 + 57e292dc) -> npc_trade both-sided -> release-evidence green except G4 -> STOP and check in.
Idle lanes to clean (unlink junctions first): C:/Users/howar/AppData/Local/Temp/{trl,tr2,tr3,spd,sp2}.

Update (~20:35Z, just before compaction): DUO-WAVE-C DONE: pc_ops/changebox/whiteout/whiteout_rebuild/poison PHYSICAL on
C-C/G-S/C-G (15/15; rows relayed to RELEASE-LANES, notes in scratchpad duo_wave_c_rows.md). FINAL-SWEEP built the sweep
driver (8b8f37b2: `python tools/gen2_final_sweep.py --list` = 92 cells; `--lanes 4 [--sha <frozen>]` after freeze;
2-cell dry run PASS) and the faint_active trainer duo (68277bdb, unrun). Before freeze: live-gate runners must stamp
CODE_DIGEST (FINAL-SWEEP, using RELEASE-LANES' tools/gen2_code_digest.py). Running: RELEASE-LANES, FINAL-SWEEP + OMP jobs.
