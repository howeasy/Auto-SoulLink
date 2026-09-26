# EG2 request: Emerald probe, observer and checkpoint PHYSICAL (2026-09-26)

- **Branch:** `claude/gen3-emerald` (worktree `.claude/worktrees/gen3-emerald`). Local only: not
  pushed.
- **Base:** master `a20cd945` (Gen 3 landed per ruling 26) is merged in.
- **Frozen cut for this request:** `c7fcbe50`; the live runs ran at `414afb92`. The hooks
  re-run and the request corrections from the OMP fact check cx-3b167167 land on top (docs and
  receipts only).
- **Plan:** `docs/gen3_emerald/PLAN.md` (E2 row). **Ledger:** `docs/gen3_emerald/REQUIREMENTS.md`
  (E2 evidence block).

## 1 What EG2 signs

On the pinned BPEE cartridge (sha1 `f3ae088181bf583e55daf962a92bb46f4f1d07b7`) in BizHawk 2.11.1,
you sign that:

- **Sites.** The `gen3_emerald` engine sites fire on real play, with a positive and a negative
  receipt per exercised kind (§2). 11 of the 12 coverage kinds are PHYSICAL; `trade_done` is OPEN
  (link partner, E5).
- **Checkpoint.** The write checkpoint predicate judges every PROBED Emerald state correctly:
  21/21 rows (the core seven, the Oldale Center and map-popup rows, the Emerald battle-field rows
  and nine battle-reason rows), tracked-clean at `3c17af21`. The probe constructs no writer
  (`WRITE_SURFACE none`), so every negative row is a refusal count; write behaviour itself is not
  exercised here (duos, E4). Rows NOT run on Emerald, carried in §5: `pc_menu`,
  `battle_faint_prompt`, `battle_link`, `native_idle_field`, `native_idle_battle`,
  `battle_commit_held_rr` (the last three are companion/RR rows). **`pc_menu` matters:** the
  `pc_move` SITES fire (§2), but the checkpoint's PC write window is not proven on Emerald.
- **Reads.** `reads.lua` == the PYDEC twin on live Emerald RAM: party/box, location, balls, and
  badges at 0 and at 4 across the flag-byte straddle.

**EG2 does NOT sign:**
- Admission or routing. Emerald stays refused by name and absent from `Entry.ROUTED` (ruling 24).
- Any Soul Link behaviour. Duos are E4.
- The server.
- The in-battle P+H faint on Emerald (EW-2, E4).
- `trade_done`.

The observer builds the unadmitted title only through the observer-only seam
`SLINK_SHADOW_UNADMITTED=gen3_emerald/emerald`:
- granted by the Gen 3 coordinator 2026-09-26 (`b00a475e`, scoped in `65177074`);
- four guard tests;
- production refuses it with the same message;
- every receipt carries its `NOTE observer building unadmitted` line.

## 1a Status

**Commits since checkpoint 1** (`f9b3277b..c7fcbe50`, first-parent, excluding the master merges):

| Commit | What | Independent review |
|---|---|---|
| `3c17af21` | battle checkpoint rows admitted; witnesses follow the pack's comm numbering | OMP cx-9a842fc0 (fixed `96ec3c77`) |
| `c78db7bc` | receipts: checkpoint 21/21, reads==PYDEC | — |
| `b00a475e` | observer-only seam | OMP cx-a604a780 (fixed `65177074`) |
| `a5e3dcaf` | SYNTH fixtures pc, lowhp | OMP cx-fd70ac8f (fixed `8ae455a0`) |
| `611913a2` | legs: PC ×4, faint, whiteout, STOP_AFTER, polarity fixes | OMP cx-39602c02 |
| `5ea14b1f` | review fixes: popup callee walk, mkstates comm value | relay reviews of `1de687be`/`a9419e8d`/`ddff9b81` |
| `cc710007` | legs round 2: box_place, catch resolution | OMP cx-39602c02 |
| `d5208074` | SYNTH badges fixture; reads==PYDEC at 4 badges | OMP cx-b47da8b1 (fixed `68936b8b`) |
| `d27b1721` | interim observer receipts | — |
| `68936b8b` | badges tests | — |
| `d27090d9` | legs round 3: evolve, poison_faint, mon_given; the catch on 20 balls | OMP cx-fe784f21 (fixed `414afb92`) |
| `65177074` | seam scoped to exact pack/title | — |
| `96ec3c77` | probe notes, comm_shift guard | — |
| `8ae455a0` | SYNTH fixtures catch, evolve, poison, gift; pc rebuilt | — |
| `414afb92` | live fixes: reader `read_u16`, gift fanfare wait, poison guard | — |
| `c7fcbe50` | final observer receipts + negatives manifest | — |

- **Workers:** a Sonnet fixture worker and an Opus legs worker, three rounds each, in isolated
  worktrees. The coordinator ran every emulator step.
- **Headless OMP:** fact checks cx-45a36733 (map_load/whiteout) and cx-9198a33f (FR hard-codes,
  routed to E3); diagnoses cx-6559e6e9 (box_place) and cx-2e7b20d6 (catch, rejected on live
  evidence). Every finding was verified before acceptance, and every one is recorded with
  `kind=outcome`.

## 2 Per-kind status (observer receipts `docs/gen3_emerald/probes/shadow_emerald_<group>_2026-09-26.{txt,shadow.log}`)

| Kind (semantic) | Positive receipt (count) | Negative receipts (manifest must_not) | Status |
|---|---|---|---|
| map_load | pc: door warp into the Center (1) | battle, catch, lowhp, trainer, evolve, poison, gift (structural: `CB2_LoadMap2` has one caller, pret `overworld.c:1579`) | PHYSICAL |
| save | pc: `save_town` (1); fires ~230 frames after the flash counter flips | battle, catch, lowhp, trainer, evolve, poison, gift | PHYSICAL |
| battle_begin / battle_end | battle, catch, lowhp, trainer, evolve (5/5) | pc, poison, gift | PHYSICAL |
| faint | lowhp: the raw battle `faint` site (1); the poison receipt adds 1 through the reducer's poison_faint→faint fold, and the raw `faint` site does NOT fire on field poison | pc, battle, catch, trainer, evolve, gift | PHYSICAL |
| whiteout | lowhp: 1-HP Mudkip faints, returns to Oldale (1) | pc, battle, catch, trainer, evolve, poison, gift | PHYSICAL |
| pc_move (deposit/withdraw/box_place/release) | pc: 6 normalized events from 7 raw `pc_*` lines (`pc_release_begin` folds into release; `pc_box_place` co-fires with deposit/withdraw as on FR/RR) | battle, catch, lowhp, trainer, evolve, poison, gift | PHYSICAL |
| capture_wild | catch: 3 real throws, balls 20→17, outcome CAUGHT (1) | pc, battle, lowhp, trainer, evolve, poison, gift | PHYSICAL |
| mon_given | gift: the Lavaridge egg (1); catch (co-fires through `GiveMonToPlayer`) | pc, battle, lowhp, trainer, evolve, poison | PHYSICAL |
| evolve_species_store | evolve: Mudkip → Marshtomp, A only (1) | pc, battle, catch, lowhp, trainer, poison, gift | PHYSICAL |
| poison_faint | poison: field poison takes a 1-HP lead to 0 (1); a healthy second mon keeps the party up by design | pc, battle, catch, lowhp, trainer, evolve, gift | PHYSICAL |
| trade_done | none | all eight receipts | OPEN (link partner; E5) |

`python tools/gen3_shadow_negatives.py docs/gen3_emerald/negatives_manifest.json`: 8 receipts,
75 expected-zero checks, all PASS: the complete matrix, 12 kinds × 8 receipts minus the 21
present-kind cells.

**Checkpoint:**
- `probes/checkpoint_emerald_2026-09-25.txt`: core seven, center_idle, and map_popup with its
  falsifier run. A DIRTY-tree receipt (`ead073d6` + edits); every row is re-covered tracked-clean
  by the 09-26 receipt.
- `probes/checkpoint_emerald_battle_2026-09-26.txt`: 21/21 at `3c17af21`, tracked-clean.

**Reads:** `probes/reads_pydec_emerald_2026-09-26.txt` (two states) and
`probes/reads_pydec_emerald_badges_2026-09-26.txt` (4 badges).

**Probe matrix:** `probes/hooks_emerald_2026-09-26.txt`, tracked-clean at `c891455d` (code ==
the run cut); it replaces the dirty-tree 09-25 receipt. Rows a, b-base, c, d, e and g PASS.
OPEN: a-return (no battle driven, by design), b-interior (+1/+2 interior hooks never fire, as on
FR), and f (the fps legs pin at 60 under the 1x-throttled gate config). The frame-end census
passes in the same run (overworld idle 1800/1800 at the modal PC).

## 3 Defects found and fixed during E2

Most were found only by live runs:
- **F-A:** the badge guard broke on the json null sentinel. **F-B:** `battle_comm_0` is 2 on
  Emerald (`ddff9b81`).
- The checkpoint probe witnesses hard-coded FR's comm numbering (`3c17af21`).
- The observer could not build an unadmitted title (`b00a475e`); the first seam unlocked every
  unadmitted title (`65177074`).
- The Emerald boot and the save menu read the field-free predicate inverted, in three places
  (`611913a2`). The save event first looked "missing" because of it.
- Grass legs didn't chain (`611913a2`).
- `PC.mode` waited for the target row after a single Down; the Emerald fix is `EMH.pc_top_row`
  (`cc710007`).
- The catch pressed A into the nickname prompt (`cc710007`). Five real full-HP throws then
  missed, so a 20-ball fixture was added (`8ae455a0`).
- The play reader io had no `read_u16`, so the catch guard died silently (`414afb92`).
- The gift arrives only after `waitfanfare` (`414afb92`).

## 4 MODEL evidence

- **Emerald/Gen 3 selection:** 461 passed (`-k "(emerald or fixture or play_legs) and not gen2 and not e2e_duo_trade"`).
- **Full unit suite without Gen 2:** 7627 passed.
- **Environment-only failures:**
  - Gen 2 tests: no `.cache/gen2-build`.
  - gen1_pure_lanes and gen1_trade_patch: no built `gen1_red.gb`, no pokered cache.
- **FR/LG/RR byte identity:** `gen_gen3_profile.py --check` and `gen_gen3_write_checkpoint.py
  --check` are current, and `git diff` over `data/games/gen3_frlg` and `data/games/gen3_rr` is
  empty.

## 5 Limits carried forward (not signed by EG2)

- The Emerald-only forbidden states (contests, secret bases, record mixing, Frontier,
  multi-partner) are SOURCE-only (`docs/gen3_emerald/write_checkpoint.md` §8).
- ER-3: badges 5-8, battle reads and trainer reads are SOURCE/MODEL only. (The 09-26
  reads receipt's "badges only at 0" line predates the badges receipt of the same day.)
- EW-1: the checkpoint rows not run on Emerald (§1); the PC write window (`pc_menu`); and write
  behaviour under the predicate (no writer in the probe).
- Hooks rows a-return, b-interior and f stay OPEN, as on FR.
- Pins: pret master `5eff7864` was the research snapshot; the symbols branch `dba968c6` is
  built FROM source commit `c65e93f2`. Every address and citation uses `c65e93f2`, the commit
  EG0 signed.
- F-C (`gen3_boot_check.lua` SIZES) and F-D (reads dump driver rows) are still open.
- **To E3** (the Gen 3 coordinator approved the direction on these conditions: the FR/LG/RR packs
  gain explicit fields, the FR/LG/RR client stays byte-identical, and a missing field fails
  closed):
  - `client.lua:52` STATE_ACTION_CONFIRMED_STANDBY=3 must come from the pack
    (`battle.commit_guard.value`, 4 on Emerald). Today the Emerald P+H perish plan is refused
    every frame.
  - SE ids: the wire keeps the FR numbering, and a pack table maps it to Emerald's 31/32/102.
  - `GIFT_AREAS` becomes a pack field.
- Carried from EG1: the Nature Power move overlay, codec API refusals, the server foundation
  `emerald -> gen3_emerald`, and ROUTED at EG4.
- Test quality, OMP-open: the play-leg tests are mostly source-text assertions. A behavioural
  fake-RAM test for the guards and the catch loop would be stronger.

## 6 Owner decisions requested

1. Accept the observer-only seam `SLINK_SHADOW_UNADMITTED=<pack>/<title>` as the way
   pre-admission Emerald observer receipts are taken. The Gen 3 coordinator granted it for this
   branch.
2. Accept the disclosed SYNTH fixtures (O-33): `pc`, `lowhp`, `badges`, `catch`, `evolve`,
   `poison`, `gift`. The behaviour under test ran natively, and `tests/fixtures/gen3/README.md`
   lists every synthetic field.
3. Accept `trade_done` as OPEN, carried to E5, and the §5 limits as carried.
4. Sign EG2. E3 then starts on master + this branch.

## 7 How to verify

```
git -C .claude/worktrees/gen3-emerald log --oneline --first-parent f9b3277b..c7fcbe50
python -m pytest tests/unit -q -k "(emerald or fixture or play_legs) and not gen2 and not e2e_duo_trade"
python tools/gen3_shadow_negatives.py docs/gen3_emerald/negatives_manifest.json
python tools/gen3_fixtures.py qualify --title emerald tests/fixtures/gen3/emerald_*.sav
python tools/gen_gen3_profile.py --check
```
