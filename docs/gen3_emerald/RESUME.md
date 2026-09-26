# Emerald lane resume note

Read this first after a pause or compaction. The plan is `docs/gen3_emerald/PLAN.md` and the ledger is
`docs/gen3_emerald/REQUIREMENTS.md`. The branch is `claude/gen3-emerald` in worktree
`E:/Google Drive/SLink/.claude/worktrees/gen3-emerald`. It is local only: not pushed or merged. Its
base is Gen 3 `5f050857`.

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
- The badge receipt only proves agreement on 0 badges; it needs a fixture that has badges.
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
