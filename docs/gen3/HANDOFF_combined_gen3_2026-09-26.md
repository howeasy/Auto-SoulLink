# Combined Gen 3 handoff: the FR/LG + RR half (2026-09-26 evening)

Owner decision, 2026-09-26: "We will combine the next work." From the next session ONE orchestrator
runs all remaining Gen 3 work: FR/LG, RR, Emerald, and the expansion sub-lane. This is the FR/LG +
RR half. The Emerald half is `docs/gen3_emerald/HANDOFF_combined_gen3_2026-09-26.md` on
`claude/gen3-emerald`. Read both, then `docs/gen3_resume.md` CURRENT STATE.

## 0. Standing owner rules (non-negotiable)

- **Nothing reaches master, even as a local fast-forward, until the owner approves that specific
  landing** (2026-09-26). Work happens on the worktree branch. Merging master INTO a branch is fine.
- Scripted normal inputs only. Game facts come from the ROM or decomp, never from screenshots. RR
  data is never a vanilla reference.
- Kill only the EmuHawk PIDs you launched. Never use bare `git stash` in a shared worktree.
  Commit by explicit path.
- Headless OMP is allowed for bounded reviews, tests and short coding. It is never trusted
  implicitly and, in this environment, CANNOT execute (no shell), so run and fix its test files
  yourself. Codex is used through the named live threads only. The magi bridge refuses new cards
  until you record `outcome` for past replies.
- Claude subagents: at most 3 at a time (Haiku/Sonnet/Opus). OMP: unlimited.
- `server/**/*.py`, `lua/*.lua`, `lua/core/**` stale the Gen 2 CODE_DIGEST. Batch them into one
  landing and ping "Gen 2 Boogaloo" before it. On 2026-09-26 the owner said "skip testing" to
  Gen 2, whose receipts read stale until he asks for a sweep.

## 1. Branch and worktree

- Worktree `E:/Google Drive/SLink/.claude/worktrees/gen3-migration-planning-5d8e45`, branch
  `claude/gen3-migration-planning-5d8e45`. **HEAD is at or after `f775ac72`**; the doc commit that
  adds this file is the handoff sha sent to the Emerald lane. Clean tree.
- Local master is `5313d94e` (not pushed by this lane). The branch is 27+ commits ahead.
- Run lane `C:/slink-wt/rrduo` (a detached worktree) was used for the RR duos. `patch/build` there
  holds companion md5 c372c428. `SLINK_GEN3_RAND_ROMS` should point at a dir with
  `{FireRed,LeafGreen}_allowed.gba`. The session scratchpad has them, plus `_widest` controls and
  `r3_run/` / `r3_wide/` Manager outputs: `C:/Users/howar/AppData/Local/Temp/claude/E--Google-Drive-SLink--claude-worktrees-gen3-migration-planning-5d8e45/30c21a7a-9a9b-44db-b573-10e09226bcc8/scratchpad/`.
  Copy them somewhere durable: temp dirs vanish.

## 2. Owner rulings (recorded in `docs/gen3/G4_request_draft.md` §6)

| # | Ruling |
|---|---|
| 26 | Land Gen 3 on local master (done earlier; since superseded for new work by the no-master rule) |
| 27 | FR/LG in-game trade on PATCHED ROMs is IN the RC; mimic the Gen 1/2 + RR framework; evolve on receipt; reset handled as Gen 1/2 do. Built in the Emerald worktree (T2-T5). |
| 28 | Trainer names, Upcoming Key Trainers and calc Prep are mandatory on vanilla FR/LG too. Gen 3 built it. |
| 29 | Randomized Gen 3 is IN the RC. The Gen 3 lane builds it end to end; Emerald binds later. |
| 30 | FR/LG companion parity: info panel, native sounds, Explode Mode, Rival Team Swap. The in-battle calc display stays RR-only. It rides the Emerald lane's T2/T3. |
| 31 | Randomized envelope: Gen 1's forbidden set; Gen 3-only UPR options OPEN (held items, tutors, in-game trades, shops, pickup); safe misc tweaks allowed; out-of-Manager ROMs admitted as `rand`; FR↔LG pair allowed; calc Prep falls back to species/level. |
| 32 | (a) Rule-changing randomization stays REFUSED for the RC. (b) A `rand` whose tables equal pret pairs as CLEAN. Relayed from the Emerald session. |
| N-3 | Amended under 27: the raw `OP_SET_PARTY_MON` swap must not remain a success path. It is still shipped until T2/T3 land. |

## 3. What this lane built (all on the branch, none on master)

**FR/LG trainers (ruling 28):**
- `3c2a35c2`: `tools/gen_gen3_trainers.py`, `data/games/gen3_frlge/frlg_trainers.json` (743 trainers,
  47 key, 351 FRLG.js calc labels) and the FR/LG branches behind `_frlg_trainer_table()`.
- The UI lane's browser check passed (Brock, rival with 3 variants, Misty; calc buttons).
- `87f3903b`: default moves via pret GiveBoxMonInitialMoveset, shared with the generator.

**Randomized FR/LG (rulings 29, 31, 32).** The design is `docs/gen3/research/randomized_gen3_design.md`.
- R2a `24caed3b` + R2c `a24d88ac` (Codex FRLG): `server/adapters/gen3_rom_tables.py`, which decodes
  gTrainers (all 4 party layouts, held items), gWildMonHeaders and gEvolutionTable by following ROM pointers.
- R2b `5a8033de` (Codex FRLG): `lua/gen3/rom_content.lua`, the client collector. Payload
  `{tables=[{addr,hex}], fingerprint=sha1(raw)}`, about 179 KB.
- `44615f4f`: `gen3_content_fingerprint` (sha256 over the decode) lives in gen3_rom_tables and is
  shared by the server and the Manager.
- `ce0258aa` (R1+R2 server): `rand` kind; ingest with a transport-sha1 recheck; forbidden-rule refusal
  (`ForbiddenRomTables`); per-player adopted trainer + wild tables; calc_label omitted for rand.
- `b9cd1bb2`: a forbidden ROM is refused at hello even without a contract. Adds the base hook
  `refused_rom_content` plus three server.py lines.
- `363782dc` (ruling 32b): base classmethod `pairing_kind_for(kind, rom_content)`; `_mixed_games_error`
  passes rom_content; the effective kind is committed. Pinned clean fingerprints: FR 70693903…,
  LG 7ef4b959….
- R3 `c7656cdb` + fixes `c32a081b` + `8a3b3c58`: the Manager randomizer for FR/LG (`server/upr_*`,
  `cartridges`, `manager`, randomizer.js). It requires the fork jar. Each output is re-proved:
  21 engine sites + context windows + 5 anchors byte-identical, species rules and evolutions
  unchanged. A real Manager pair was made.
- R4 `f9bcb991` (Codex FRLG) + blocker fixes `9a2af9e8`: duo rows `admit_randomized_frlg`,
  `link_gen3_rand` and `trainer_panel_gen3_rand` (`explicit_only`; they need SLINK_GEN3_RAND_ROMS).
  **LIVE: BLOCKED** until T3's CR-R1/CR-R2 are on the same branch.

**Box census (KEY-SCOPE-5):**
- `a53f942a`: `reports_box_census() -> True` for FR/LG + RR.
- It **MUST land together with Emerald T3 `f4ec8c85`**, the client stamp. Without the stamp, key_changes get
  refused (a snapshot with no generation counts as no census).

**Evidence cards:**
- F-6: all 21 fixtures boot-check PASS (`5929a287`).
- C-6 idempotence tests (`6c28d08f`). R-1/R-2 occupied-slot decode (`6c28d08f`). C-3 dashboard render (`cdf8758c`).
- Ledger updated (`c6deca8d`, `f775ac72`).

**Earlier today** (already on master 7c14386a before the no-master rule):
- the RR companion fix batch (START row `03b19b71`, trade names / chooser `2c553181`, companion md5 c372c428);
- Overworld Presence forced off;
- RR trade / decline / infopanel / infopanel_dex duos green ×2.

## 4. Workers at handoff

| Worker | State |
|---|---|
| Codex "FRLG" (live thread) | cx-42eabc05, an ADVERSARIAL_REVIEW of the randomized server half (44615f4f..363782dc), may still be running. Reconcile its reply against the source, then record `outcome`. |
| Opus / Sonnet subagents | none running |
| OMP headless | none running; every outcome recorded |
| S-8/S-11/F-7 card | **never dispatched** (the FRLG thread took R2a-R4 instead); still open |

## 5. First task for the combined orchestrator

1. Build ONE integration worktree (short path, e.g. `C:/slink-wt/g3-int`). Merge
   `claude/gen3-emerald-t3` into a branch cut from `claude/gen3-migration-planning-5d8e45`, after the
   Emerald lane's reviewed lifecycle fix for e8f51695 lands on T3. Resolve `docs/protocol.md` citation
   conflicts with `tests/unit/test_protocol_citations.py`.
2. Pair-test:
   - T3 census `f4ec8c85` ↔ this lane's `a53f942a`;
   - T3 CR-R1 `637bcd17` (`rand` admission) and CR-R2 `e5f8da76` (hello rom_content) ↔ `ce0258aa` / `b9cd1bb2` / `363782dc`;
   - T3 R0 `a5469ea3` (`rom_tables` profile block) ↔ `rom_content.lua`.
   Then run the full `tests/unit` without piping, and the three R4 live rows once each
   (`python tools/e2e_duo.py --game gen3_frlg --scenario <row> --lane r4 --keep-data`).
3. Ask the owner for ONE master landing of the combined result and ping Gen 2 Boogaloo.
4. Then the Emerald lane's T2-T5 (patched trade + parity on FR/LG/RR/Emerald). After the RR
   durable-trade row is green, run ONE RR frozen-cut re-run, then new FR/LG and RR cuts for G4/G5.

## 6. Open queue (FR/LG + RR side)

**Randomized:**
- R3 review F3: a full FR/LG write-domain audit (as pureRGB's T6), plus pointer-aware table checks.
- R3 re-review F1: parity for cartsWhy/describe_rom on the stock jar. F2: the remaining KeyError paths
  become named refusals. F4/F5: missing tests.
- In-game trades are OPEN (ruling 31), but `state.py` `_handle_key_change` never re-checks the species
  clause. A rules card, shared server code.
- Prove that the GBA hello `rom_sha1` (gameinfo.getromhash) equals the file sha1 (live).
- The contract fingerprint depends on the decoder version (`r3_run/rom_contract.json` is already stale).
- Altering Cave shows only its first encounter set.
- R4 evidence quality (OMP cx-904adf25 findings 3-6): the level check isn't independent; the area
  branch is dead; a ROM-free probe test is needed; no row evidences 32(b) admission.

**Parity and robustness:**
- Gen 1-style refused-key_change retry after a newer census (`resend_refused_change`). A shared
  lua/core change, in scope for "match or beat Gen 1/2".

**Evidence still open:**
- S-8 (evolution) and S-11 (poison faint) natural-play legs.
- F-7 (pin the RR generator sources).
- W-2 RR checkpoint re-qualification (after the final companion).
- C-3 browser receipt.

**Housekeeping:**
- The shared `E:/Howard/Bizhawk/GBA/State/slink_fr_battle.State` was overwritten by the Emerald T2
  lane at 17:27. Regenerate it before trusting any checkpoint battle-row receipt taken from the
  shared dir.
- A redundant stash entry `gen3-review-fix-redcheck-1790457729` is on the SHARED stack. Its content
  is committed in c32a081b; guard_git blocks `drop`.
- `tests/unit/test_calc_trainer_sets.py` `_FRLG_ARRAY_RE` lets a dummy array swallow the next one.
  Calc lane.

## 7. Awaiting the owner

- **Approval** of the combined master landing (after §5 steps 1-2).
- **G4 (FR/LG) and G5 (RR) signatures.** Both wait on: T2-T5 trade + parity; randomized live rows;
  new frozen cuts. The G4/G5 drafts record everything above.
- **Who orchestrates** the combined lane (the Emerald lane recommends this session). That's the owner's call.
