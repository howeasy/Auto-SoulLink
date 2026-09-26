# Emerald lane resume note

Read this first after a pause or compaction. The plan is `docs/gen3_emerald/PLAN.md` and the ledger is
`docs/gen3_emerald/REQUIREMENTS.md`. The branch is `claude/gen3-emerald` in worktree
`E:/Google Drive/SLink/.claude/worktrees/gen3-emerald`. It is local only: not pushed or merged. Its
base is Gen 3 `5f050857`.

## CHECKPOINT 2 (2026-09-26 ~06:25Z, owner pause after 3 h): resume here

**Owner rules this block:**
- Haiku, Sonnet and Opus workers, at most 3 at once, `model` set explicitly.
- Headless OMP is NON-BLOCKING (owner 2026-09-26): call `omp_peer` headless with `wait=false`, as
  many as useful, no Sonnet relay. Never trust it implicitly: verify every finding and record
  `kind=outcome`.
- "Synth hard to create tests if needed": disclosed O-33 SYNTH fixtures are fine; the behaviour
  under test runs native.
- One emulator lane: run dirs in `C:/slink-wt/emerald-e2`; kill only our own PIDs.

**Where things are:**
- Branch `claude/gen3-emerald` @ `the commit adding this checkpoint (after `c7fcbe50`)`, local only.
- **Gen 3 is on master** (ruling 26; master `a20cd945` merged in as `90cf2a04`). The branch is
  now master + Emerald, and future syncs are merges of master.
- Worker worktrees `C:/slink-wt/em-fx` and `C:/slink-wt/em-legs` are synced to the lane; both
  workers are done.

**Gates:**
- EG0 and EG1 are SIGNED.
- **The EG2 request is written** (`docs/gen3_emerald/EG2_request.md`) and waits for the owner.
  The owner decides whether to sign it; do not self-sign.

**E2 done in this block** (commits since `f9b3277b`):

| Commit | What it did |
|---|---|
| `3c17af21` | Battle checkpoint rows admitted; witnesses follow the pack's comm numbering. 21/21 live. |
| `b00a475e` + `65177074` | Observer-only seam `SLINK_SHADOW_UNADMITTED=gen3_emerald/emerald` (Gen 3 grant with four guard tests; now scoped to the exact pack/title). |
| `a5e3dcaf`, `d5208074`, `8ae455a0` | SYNTH fixtures `pc`, `lowhp`, `badges`, `catch`, `evolve`, `poison`, `gift`, built on the lane by `make-emerald`. |
| `611913a2`, `cc710007`, `d27090d9`, `414afb92` | Emerald legs: PC ×4, faint, whiteout, catch, evolve, poison_faint, mon_given; Emerald STOP_AFTER; the fixes found live (details below). |
| `5ea14b1f`, `68936b8b`, `96ec3c77` | OMP review fixes. |
| `d27b1721`, `c7fcbe50` | Observer receipts + `docs/gen3_emerald/negatives_manifest.json`. |

Defects fixed in `611913a2`–`414afb92`, each found live:
- boot/save predicate polarity;
- grass legs not chaining;
- `PC.mode` target wait;
- the catch nickname prompt;
- the reader io missing `read_u16`;
- the gift arriving only after the fanfare.

**Observer kinds PHYSICAL on BPEE:** battle_begin/end, faint (battle + field), whiteout, map_load, save, pc_move (deposit/withdraw/box_place/release), capture_wild, mon_given, evolve_species_store, poison_faint: 11 of 12; negatives manifest 70/70.
- `reads == PYDEC` holds at 0 and at 4 badges; the badge limit is retired.
- OPEN, carried to E4/E5: `trade_done` (needs link/E5).

**NEXT (in order):**
1. The owner reviews and signs `docs/gen3_emerald/EG2_request.md`. Nothing on the E3 track starts
   before that.
2. E3, after EG2. The Gen 3 coordinator has approved the direction, with these conditions:
   - the FR/LG/RR packs gain explicit fields for today's values;
   - FR/LG/RR client behaviour stays byte-identical;
   - a missing field fails closed.

   The work:
   - `client.lua:52` STATE_ACTION_CONFIRMED_STANDBY comes from `battle.commit_guard.value`;
     the explode rows use the pack value too.
   - SE ids: the wire keeps the FR ids, the client maps them to title SE ids through a pack
     table, and `docs/protocol.md` documents it.
   - `GIFT_AREAS` becomes a pack field.

   Plus the items carried from EG1:
   - the Nature Power overlay;
   - codec API refusals;
   - server foundation `emerald -> gen3_emerald`;
   - ROUTED at EG4.
3. Gen 3 lane card: the shared `PC.mode` should wait for progress (`~= current`), not the
   target (OMP cx-6559e6e9). Emerald uses `EMH.pc_top_row` meanwhile.

**Open review items (not blocking):**
- cx-fe784f21:
  - F6/F7/F8: the play-leg tests are mostly source-text assertions; a behavioural fake-RAM test
    for `EMH.poison_party` and `EMH.lead_is` would be stronger.
  - F3: `read_balls` sums the whole pocket.
- cx-39602c02 #5: the fake-host globals share a LuaRuntime.
- cx-b47da8b1 F5: badges 5-8 are not proven physically.

**Lane tooling (scratch, `C:/slink-wt/emerald-e2`):**
- `run_play.py <run> <fixture> [FROM] [STOP] [--noshadow]` (env `STATE_OVERRIDE`, `PLAY_SCRIPT`);
  note that run_gate's exit code is wrong for Emerald play, so read `g_*_result.txt`.
- `run_groups8.sh` runs the eight groups.
- `mk_shadow_receipts.py` writes the receipts and the manifest at a clean tree.
- `run_probe.py` for the checkpoint probe; `run_reads_pydec.py <state|BOOT>` (env `FIXTURE`).
- `guide_update.py <json>` updates the guide checkpoint.

**Environment-only test failures in this worktree:**
- Gen 2 tests: no `.cache/gen2-build`.
- Gen 1 pure lanes and trade-patch tests: no built `patch/build/gen1_red.gb` or pokered cache.
- The RR harness sha.

## CHECKPOINT 1 (2026-09-25, owner pause after 1.5 h): resume here

Owner rules this block:
- Haiku, Sonnet and Opus workers, at most 3 at once, `model` set explicitly.
- Unlimited headless OMP for short, contained reviews. OMP here cannot run code, so the coordinator runs
  every change OMP writes, and OMP findings are never trusted without a check.
- One emulator lane: kill only our own PIDs; run dirs go in `C:/slink-wt/emerald-e2`.

**Gates:**
- EG0 and EG1 are SIGNED by owner delegation ("Do what you think is best. Lets go to the next major
  checkpoint", 2026-09-25). See `docs/gen3_emerald/EG1_request.md`.
- EG2 (probe + observer + checkpoint PHYSICAL) is in progress.

**E2 done** (each commit reviewed by OMP; every finding checked before acceptance):

| Commit | What it did | Review |
|---|---|---|
| `04960989` + `e425dcd2` | Emerald pack registered in PACKS/PACK_FILES only, NOT ROUTED. A test fails if ROUTED gains it, and a pinned BPEE still ends in the by-name refusal (Gen 3 coordinator grant). The release manifest ships the pack, and a test derives the manifest from `Entry.PACK_FILES`; this fixed a real blocker, a zip that refused every GBA cartridge. Badge read via `BADGE_FIRST_FLAG`. | cx-7b74a808 |
| `ead073d6` | Hook-probe rows a-g PHYSICAL on BPEE (live gates rr/fr/emerald 3/3). Frame-end census: modal PC `0x080008C8`, now `observed_pc`. | cx-cb4fb1b8 |
| `ce17be7d` | Census and probe hardening. The live census row and the Emerald hooks row are UNRUN at a clean cut; see NEXT. | — |
| `517d78f9` | Emerald scripted-play legs (offline). `gba_map` reads Emerald's tileset struct. | — |
| `59a51807` | Research brief for the in-battle ball throw. | cx-6e4bea59 |
| `1de687be` | Checkpoint PHYSICAL: 12 rows (see the table in the receipt `docs/gen3_emerald/probes/checkpoint_emerald_2026-09-25.txt`). The map-name popup is allowed, backed by pret evidence and a falsifier run. reads==PYDEC PASS. | — |

**Also done before the pause:**
- `a9419e8d` E2-CATCH-LEG: the Emerald ball throw per the brief, and `emerald_route102_catch` is a real leg. UNRUN live.
- `ddff9b81` E2-FIX-AB:
  - F-A: the badge guard ignores the json null sentinel; red->green on the real profile.
  - F-B: `battle_comm_0` = STATE_WAIT_ACTION_CHOSEN, which is 2 on Emerald; commit_guard is 4. FRLG/RR are byte-identical.
- **Live at the clean cut `ddff9b81`:** `SLINK_LIVE=1 pytest tests/live/test_gen3_probe_gates.py -k emerald` passes both rows, the Emerald hooks row and the frame-end census (idle >= 90%, modal non-IRQ PC == observed_pc). This retires the dirty-tree finding from cx-cb4fb1b8.
- No worker is running, no EmuHawk of ours is running, and the tree is clean.

**Reviews pending, since the pause means no new dispatch:** OMP reviews of `1de687be` (E2-CKPT), `a9419e8d` (CATCH-LEG) and `ddff9b81` (FIX-AB). Run them first on resume.

**NEXT (in order, all on the one lane):**
1. The three pending OMP reviews (above).
2. After F-B, admit and run the in-battle reason rows on Emerald: `battle_input_wild`, `battle_input_trainer`
   and `battle_move_menu` in `lua/tests/probe_gen3_checkpoint.lua`. Then re-run the reads==PYDEC driver
   (`C:/slink-wt/emerald-e2/run_reads_pydec.py`) against the committed `reads.lua` (F-A).
3. E2-PLAY: run the Emerald observer with shadow on (`SLINK_SHADOW`, via `tools/run_gate.py --shadow`) over
   `EMERALD_LEGS`. Record a positive and a negative receipt per exercised kind, using an Emerald negatives manifest
   (`docs/gen3_emerald/negatives_manifest.json`, checked with `tools/gen3_shadow_negatives.py --manifest`).
   Kinds:
   - pinned: map_load, save, battle_begin/end;
   - capture_wild, if the catch leg works;
   - OPEN: pc_*, faint, whiteout, mon_given.
4. Optional before EG2: add a disclosed SYNTH fixture variant with 2 party mons and a low-HP lead. That
   unlocks pc_* and faint/whiteout; `tools/gen3_fixtures.py make-emerald` is the tool.
5. Write the EG2 request (template T3) and stop for the owner.

**Recorded limits / carried items:**
- Emerald-only forbidden states are SOURCE-only; see §8 of `docs/gen3_emerald/write_checkpoint.md`.
- ~~The badge receipt only proves agreement on 0 badges~~ retired at checkpoint 2 (`d5208074`: 4 badges across the byte straddle).
- F-C: the `gen3_boot_check.lua` SIZES table has no Emerald section sizes.
- F-D: `probe_gen3_reads_dump.lua` and `gen3_reads_pydec.py main()` have no Emerald rows.
- Carried from EG1 to E3: per-title SE ids, the Nature Power move overlay, codec API refusals, and the
  server foundation `emerald -> gen3_emerald` (at EG4, with ROUTED).

**Workstation notes:**
- This worktree holds a gitignored copy of the pinned RR companion ROM (`patch/build/slink_RR.gba`, sha1 `ea5352f8`).
- The main checkout's copy differs from it.
- A Gen 1/Gen 2 EmuHawk may be running on this machine and is not ours.

## Working in this lane (read after compaction)

**Who and where:**
- Coordinator: session "Emerald support planning". Its own planning worktree `emerald-support-planning-225c0a` holds no code.
- All code lives in `.claude/worktrees/gen3-emerald`. The Write/Edit tools refuse that path from this session, so edit with Bash + python (or scratchpad + cp).
- Shell tools reset cwd each call: `cd` explicitly.

**Progress** (sessions: estimate / status):
- E0 ¼ done; E1 1½ done; E2 1, ~65%.
- Then BLOCKED until the Gen 3 branch merges to master (after its G4/G5; merge order Gen 1, Gen 2, Gen 3).
- Then E3 ½ + E4/E4b 1½ + E7 ½ = the Emerald RC; E5 trade 2; expansion X0-X4 8-10.

**Grants from the Gen 3 coordinator** (session "Gen3 migration planning"):
- Additive rows in the gen3 generators, codec, fixtures and title_syms.
- `entry.lua` PACKS/PACK_FILES only; NEVER ROUTED before EG4 (a test enforces this).
- `reads.lua` + `tools/gen3_reads_pydec.py` badge read.
- Always: FRLG + RR outputs byte-identical, and no commits on their branch.
- The calc lane freezes `decode_party_mon(raw, rr=False)` and its ivs/evs/party-tail keys.

**Commands:**
- `python -m pytest tests/unit -q -k "emerald or gen3"`. Known env-only failures: the RR harness sha and the gen1_trade_patch errors (no pokered cache).
- `python tools/gen_gen3_profile.py --check`, `python tools/gen_gen3_write_checkpoint.py --check`, `git diff --quiet data/games/gen3_frlg data/games/gen3_rr`.
- Live: `SLINK_LIVE=1 SLINK_GEN3_FIXTURE_RUNS=C:/slink-wt/emerald-e2/runs python -m pytest tests/live/test_gen3_probe_gates.py -k emerald`.
- Fixtures: `python tools/gen3_fixtures.py qualify --title emerald tests/fixtures/gen3/emerald_*.sav` and `boot-check --title emerald --fixture <sav> --rom "<abs ROM path>"`.

**Quirks:**
- Running a generator for real can flip FRLG files' line endings (content unchanged).
  - The guard_git hook blocks path-reverting checkouts, and even matches that phrase inside heredoc text.
  - Restore by writing `git show HEAD:<path>` back: for `.lua`/`.md`, convert LF to CRLF via python; for `.json`, a plain redirect.
- `&&` chains that end in `| tail` do NOT stop on a pytest failure. Check the output before committing (one bad commit happened: 50c0eb51 fixed 20aba5a5).

**Emulator:**
- One lane. Run dirs go in `C:/slink-wt/emerald-e2`.
- Kill only our own PIDs; Gen 1/Gen 2 duos share the machine. Before assuming an EmuHawk is ours, check its command line with `Get-CimInstance Win32_Process`.

**Workers:**
- Haiku/Sonnet/Opus, at most 3, `model` explicit, every brief points at `docs/agents/worker_card.md`, with an exact lease and a hard stop time.
- OMP headless cannot execute code here: use it for read-only reviews and run every OMP-written change yourself.
- OMP has been wrong on game facts and Thumb decoding (rejected: cx-8f7dfa4f stub value, cx-84f064cb "not faithful Emerald", cx-b9d33a79 map_load/badge arithmetic). Record every review with `kind=outcome`.

**Lesson (keep):** MODEL/review agreement is not proof. The live runs caught three defects that tests and reviews passed:
- battle_comm_0 meaning;
- the json null sentinel;
- the missing release-manifest row.
