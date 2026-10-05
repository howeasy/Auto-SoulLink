# Polished Crystal RC tracker

**Not an RC.** `python tools/verify_polished_release.py` currently fails 18 items by design: 5 OPEN
blocking items (`OPEN-WRITE-PATH`, `OPEN-EXPLODE-RIVAL`, `OPEN-TITLE-SPLASH`, `OPEN-PANEL-PAGES`,
`OPEN-IN-GAME-TRADE`), 11 LIVE receipts that are stale against the current overlay, and the
BUILD-OVERLAY / MODEL-DATA cells (count from the 2026-10-05 coordinator run; this rewrite did not
re-run the verifier to completion). The reasons are in `RC_STATUS.md`. No row below is
**QUALIFIED ON THIS CUT**.

Rewritten 2026-10-05 against `claude/gen2-integration` HEAD `df26d343a` after a Codex source audit of
the previous table. Everything here was checked with grep, `ls`, `git log`, `git cat-file` and
`git merge-base --is-ancestor`. No emulator was run. Test counts are `pytest --collect-only`
counts (collected, not passed); no row claims a pass that was not run for this rewrite.

## Vocabulary

| level | meaning |
|---|---|
| IMPLEMENTED | code is in the tree; it may have no test, or no live run |
| MODEL-TESTED | a unit test on disk exercises it (Python model, or Lua under lupa where the row says so); it never ran on a cartridge |
| LIVE-RUN | ran on an emulated cartridge in an older run, on the overlay sha1 named in the row. A sha1 is not a commit. These are DEV runs from `LIVE_RESULTS.md` or a lane result file, not PHYSICAL receipts |
| QUALIFIED ON THIS CUT | the verifier's live receipts for the CURRENT code and overlay are green. **No row has this level** |

The current integrated overlay is `data/polished/overlay_provenance.json` `output.sha1`, which is
`deebb1004d4f6123667d5d9e061ad0bf867ac021` (`deebb100`, commit `da7c9bad4`). The column "live on
`deebb100`?" is the marker for which rows were run live on that overlay and which only on an
older or lane overlay. Do not copy a sha1 between trees: read the file.

Older overlay sha1s that appear below (all are overlay sha1s, not commits): `29ea04c2` (Runs 1-3),
`34942315` (Phone Stage 1, `c9f1ad14f`), `9c60bc8f` (first panel build, `5ed073821`), `ac65532c`
(sound-only build, `ef7fdd60e`), `7461c828` (a pol-panel2 lane build; not committed as the
integrated overlay).

## Table of record

| feature | level | live on `deebb100`? | source and commits | tests and live records |
|---|---|---|---|---|
| hello + admission (overlay) | MODEL-TESTED, LIVE-RUN (`29ea04c2`) | YES: Stage A `PASS polished-live` frame 8590, lane `F:/slink-work/lanes/g2int-ov/stageA.out` (not recorded in a committed doc) | `lua/gen2/polished.lua` `P.admit`; `lua/gen2/entry.lua` `admit_polished` | `tests/unit/test_polished_client.py`, `tests/unit/test_polished_companion.py`; `LIVE_RESULTS.md` Run 1 Stage 1, Run 2 Stage A |
| hello + admission (randomized cartridge) | MODEL-TESTED, LIVE-RUN (`29ea04c2` lineage) | NO | `lua/gen2/polished.lua` `P.admit`, `P.RAND_ANCHORS` | `tests/unit/test_polished_rand_admission.py`; `LIVE_RESULTS.md` Run 3 Stages R1-R3 |
| title / version stamping | IMPLEMENTED on branch `claude/pol-title2` only | NO: never run live | source commit `e5f66d89c` on `claude/pol-title2` (also merged into `claude/pol-ov2`); **not an ancestor of the integration branch**. Built green twice in lane `pol-title2` (its own run, generated artifacts not included) | `tests/unit/test_build_polished_syms_export.py` is on branch pol-ov2 / pol-title2, not yet in the integration branch. The old `claude/pol-title` branch is superseded |
| wild-catch detection | MODEL-TESTED, LIVE-RUN (`29ea04c2`) | YES: Stage A capture-site bank 3 hits 1, `g2int-ov/stageA.out` | `lua/gen2/signals.lua` `S.new_polished` (site `capture_party` `03:652b`) | `tests/unit/test_polished_sites.py`, `tests/unit/test_gen_polished_engine_sites.py`; `LIVE_RESULTS.md` Run 1 Stage 2 |
| forms identity (key + effective wire) | MODEL-TESTED | NO: never run live; the Alolan Persian GAP in `LIVE_RESULTS.md` was closed in code by `43ee19f0` | commit `43ee19f0`; `server/adapters/polished_codec.py` `key_form` | `tests/unit/test_polished_effective_wire.py`, `tests/unit/test_gen_polished_forms.py` |
| variant evolution families | MODEL-TESTED | NO | `server/adapters/gen2_polished.py` `evo_family` (lowest effective id of the evolution component, over variants too) | `tests/unit/test_polished_forms_adapter.py` (18), `tests/unit/test_polished_upr_forms.py` |
| box census (read-only) | MODEL-TESTED, LIVE-RUN (`29ea04c2`) | YES: Stage A census follows the battle end (`g2int-ov/stageA.out`) | `lua/gen2/polished_boxes.lua` | `tests/unit/test_polished_boxes_census.py`, `tests/unit/test_polished_boxes.py`; `LIVE_RESULTS.md` Run 1 Stage 3, Run 2 Stage A |
| memorial / insert writes | IMPLEMENTED (helpers); composed only as `box_mon` below. No memorial executor composed | NO | `move_to_memorial` and `insert_mon` in `lua/gen2/polished_boxes.lua` | `tests/unit/test_polished_boxes.py` |
| box_mon deposit | MODEL-TESTED, LIVE-RUN. Composed and hardened (verify-before-publish, count last, compaction fix). `supports_box_mon` is still **False** | YES: check (b) PASS on `deebb100` (see note W) | `lua/gen2/polished_overworld.lua` `O.boxes`; `server/adapters/gen2_polished.py:755` (capability False: it would strand linked catches until withdraw is wired). Commits `9f5783869`, `dfeec7555` | `tests/unit/test_polished_write_path.py` (43), `tests/unit/test_polished_writes.py`; `tools/polished_live/writes.lua`, `tools/polished_live/writes_run.py`; lane result `F:/slink-work/lanes/pol-livew/writes/result.txt` |
| party_mon withdraw | MODEL-TESTED (executor composed). **No live proof.** Capability stays False | NO | `lua/gen2/polished_overworld.lua` withdraw branch (`:590-651`): party half first, count last, verified append, narrowed permits, reconciliation, ambiguity refusal. Commit `290d47b63`; savemon to party reconstruction in `lua/gen2/polished_stats.lua` and `polished_codec.savemon_to_party` (`805f65b56`, `6a0c13211`) | `tests/unit/test_polished_withdraw_path.py` (42), `tests/unit/test_polished_stats.py` (47), `tests/unit/test_polished_stats_lua.py`; spec `WITHDRAW.md`. HP comes back full and status cleared (engine behaviour) |
| force_faint (overworld) | MODEL-TESTED, LIVE-RUN. Check (a) PASS on `deebb100`; the negatives (c) are **NOT RUN live** | YES for (a): bench mon HP 0/0, status 0, party count unchanged, all writes inside the party block. NO for (c) | `lua/gen2/polished_overworld.lua`; commits `9f5783869`, `9fd4619a5` | `tests/unit/test_polished_write_path.py`; lane result `lanes/pol-livew/writes/result.txt` (it ends at the `(cc1)` in-battle poke with no verdict recorded) |
| Bug Catching Contest death hold | MODEL-TESTED | NO | `lua/gen2/entry.lua:919-924` `contest_mask={bank=1, address=0xD7E4, bit=2}` (a KO during the contest is held, not dropped) | `tests/unit/test_polished_write_path.py:902-916` |
| explode mode | MODEL-TESTED. Composed behind `supports_explode_mode()` False | NO | `lua/gen2/polished_explode.lua`; `server/adapters/gen2_polished.py:751`; commit `90648f4e1` | `tests/unit/test_polished_explode_path.py` (44) |
| rival team swap | **NOT composed** | NO | the client lacks PARTYMON_STRUCT_LENGTH / MON_HP / MON_SPECIES constants and the write is only valid at `0f:47DD`; `faint_active_battler` refuses. Spec `EXPLODE_RIVAL.md` | none |
| battle-sites binder (opt-in) | MODEL-TESTED | NO | `lua/gen2/polished_battle.lua`; commit `6e7a1b53` | `tests/unit/test_polished_battle_sites.py` |
| runtime party / battle / player decoding, party and savemon codecs | MODEL-TESTED (Lua under lupa and Python) | NO beyond what Stage A exercised | `lua/gen2/polished.lua`, `server/adapters/polished_codec.py` | `tests/unit/test_polished_lua.py` (24), `tests/unit/test_polished_codec.py` (17), `tests/unit/test_polished_stats.py` |
| trainer / rival identification, badge ordering | MODEL-TESTED | NO | `server/adapters/gen2_polished.py` (moved trainer classes RIVAL0/1/2 + LYRA1/2; wild `level_from_badges` handling) | `tests/unit/test_gen2_polished_adapter.py` (18) |
| server adoption of randomized encounter tables | MODEL-TESTED, LIVE-RUN (Run 3 R2, older overlay) | NO | `server/adapters/gen2_polished.py:411-433` `ingest_rom_content` and `use_rom_encounters` (the server's own read of the Manager file, sha1 pinned; unreadable cartridge shows no encounters) | `tests/unit/test_polished_rand_data.py` (12); `LIVE_RESULTS.md` Run 3 |
| randomizer + UPR jar | MODEL-TESTED, LIVE-RUN (Run 3, older overlay) | NO | `server/upr_pipeline.py` (`POLISHED_VARIANT`), `tools/gen_upr_polished_ini.py` | `tests/unit/test_upr_polished_pipeline.py`, `tests/unit/test_gen_upr_polished_ini.py`; `LIVE_RESULTS.md` Run 3 Stages R1-R3 |
| Phone-card SLink contact | MODEL-TESTED, LIVE-RUN | YES: `PASS pol-phone` frame 3103 on `deebb100`, lane `g2int-ov/phone2.out` (not in a committed doc). The earlier Stage 1 run (`34942315`) is in `LIVE_RESULTS.md` | `patch/polished/src/slink.asm` (`SlinkPhone_*`); `lua/gen2/phone.lua`; commit `c9f1ad14f` | `tests/unit/test_polished_phone_entry.py`, `tests/unit/test_polished_companion.py`. "Call" on the contact now opens `SlinkPanel` (`slink.asm:179-191`); the old "CallGate prints a stub" wording is obsolete |
| phone calls (real in-game calls) | NOT STARTED: no call transport | NO | `SlinkPhone_CallGate` opens the panel and never rings | `tests/unit/test_polished_phone_entry.py` |
| panel pages | MODEL-TESTED, LIVE-RUN. C0-C5 PASS on lane overlay `7461c828` only | NO: `deebb100` still has the pre-fix `panel.asm`. On it the panel opens and shows "SOUL LINK / NO CLIENT" (phone2 run) but C1-C5 were not run | `patch/polished/src/panel.asm`; commit `5ed073821`; spec `PANEL.md` | `tests/unit/test_polished_panel.py`. `7461c828` run: lane `F:/slink-work/lanes/pol-panel2/run/result.txt` `PASS pol-panel` frame 806. `docs/polished/LIVE_PANEL.md` exists only on branch `claude/pol-panel` and records the older `9c60bc8f` run as FAIL (never reached ROUTE_29) |
| sounds | MODEL-TESTED, LIVE-RUN. PASS on `ac65532c` and on `deebb100` | YES: `PASS pol-sounds` frame 633, caps `$07`, four codes post to ack to play, busy-channel hold 163 frames (under 240), every host write at `$C612` | `lua/gen2/polished_sounds.lua`; commits `ef7fdd60e`, `983693620` | `tests/unit/test_polished_sounds.py`, `tests/unit/test_polished_sounds_wired.py`; `LIVE_SOUNDS.md`. Not exercised: reset-latch path, music-fade hold. The Manager `native_sounds` row was never run through a real client/server pair |
| native trade (receptionist) | **PARTIAL.** The Python 53-byte trademon codec is MODEL-TESTED. The Lua twin `lua/gen2/polished_trade.lua` is **not referenced by any test**, so both-language validation is not claimed. No asm service, no anchor | NO | `server/adapters/polished_codec.py` `TRADEMON`; `lua/gen2/polished_trade.lua`; commit `06be5c99` | `tests/unit/test_polished_trade_codec.py` (29) |
| trade dispatch fingerprint | MODEL-TESTED. Engine-state blocks are INFERRED, not measured | NO | `server/adapters/polished_trade_fingerprint.py` and Lua twin `lua/gen2/polished_trade_fp.lua` | `tests/unit/test_polished_trade_fp.py` (38; see its docstring on INFERRED values) |
| trade lease / mailbox binder | NOT STARTED | NO | `polished_trade.lua` `compose()` returns `nil, why` without `profile.overlay.trade` | none |
| calculator | **PARTIAL**: baseline works (`calculateRBYGSC` over Polished data). Crit is wrong: the Gen 3 engine applies x2 while Polished uses x1.5 (x2.25 with Sniper), `effect_commands.asm:4333-4343` (`CALC.md` section 4.1). Abilities unsupported: `supports_abilities()` is False (`gen2_polished.py:630`) | NO | `tools/gen_polished_calc.py`; commit `c32791fe` | `tests/unit/test_gen_polished_calc.py` (19) |
| overlay build + byte guard | MODEL-TESTED | n/a (build artefact) | `tools/build_polished_companion.py`; current overlay sha1 `deebb100` (read it from `overlay_provenance.json` `output.sha1`) | `tests/unit/test_polished_companion.py`, `tests/unit/test_polished_release_guards.py`. A full rgbds rebuild is a BUILD-OVERLAY verifier item and is red off the build host |
| ROM tables / ram doc / forms pack | MODEL-TESTED (source only) | n/a | `tools/gen_polished_*.py` | `tests/unit/test_polished_rom_tables.py` (one skip when pokecrystal is not cloned), `test_polished_ram_doc.py`, `test_polished_area_map.py` |
| player ZIP carries the composed Polished dependencies | MODEL-TESTED | n/a | `tools/make_release.py` `_LUA_GEN2` (`polished*.lua`) and the `polished_crystal` pack rows (`items.json`, `species_index.json`, `moves.json`, `engine_signals.json`, `overlay/beacon.json`) and `overlay_provenance.json`. `polished_trade.lua` and `polished_trade_fp.lua` are not listed (nothing composes them yet) | `tests/unit/test_polished_release_manifest.py` (3) |
| Polished release verifier | IMPLEMENTED and MODEL-TESTED. Its verdict is red | n/a | `tools/verify_polished_release.py`, manifest `tests/polished_release_requirements.json`, report `RC_STATUS.md`; false-green paths closed in `6fb8ea629` | `tests/unit/test_verify_polished_release.py` (90). Known red: see the header |
| C-5 randomized duo gate | PARTIAL. The gate is real release evidence: `c5_gate_errors` (`tools/verify_gen2_release.py:2462`) requires an installed, sound packet and a PHYSICAL PASS per cell at the current digest. The installer `tools/c5_install_receipts.py` has a link-safe destination and an unpinned-file gate (`verify_gen2_release.py:2458`). **Receipts are NOT installed** (`tests/fixtures/gen2/receipts/c5/` does not exist) | NO | `tools/c5_runner.py` (needs EmuHawk, about 20 min, run at freeze) | `tests/unit/test_verify_gen2_c5.py`, `tests/unit/test_c5_install.py` |

**Note W (box_mon / force_faint).** The committed `docs/polished/LIVE_WRITES.md` is stale: it still says
check (a), (b) and (c) are NOT RUN (the save fixture did not load). The later driver commits
`9fd4619a5` (a) and `dfeec7555` (b) fixed the harness, and the lane result file
`F:/slink-work/lanes/pol-livew/writes/result.txt` (2026-10-05) shows (a1)-(a4b) and (b0)-(b4) all `[ok]`
on the integrated overlay `deebb100`. The document was not updated by that run; this tracker cites the
result file and does not claim more than it shows. Check (c) did not finish.

## How to re-derive this table

```bash
git log --oneline --all -- <the feature's main source file>
git branch --contains <sha>            # which branch carries it
git merge-base --is-ancestor <sha> HEAD && echo in-HEAD
python -m pytest tests/unit -k polished --collect-only -q | tail -1
python -c "import json;print(json.load(open('data/polished/overlay_provenance.json'))['output']['sha1'])"
```

## Known-stale text elsewhere in `docs/polished/`

Marked in place, not rewritten (the original wording is kept as history):

* `LIVE_WRITES.md` says (a), (b) and (c) are NOT RUN. Superseded for (a) and (b); see note W.
* `LIVE_RESULTS.md` Phone Stage 1 describes the entry text "SLink is linked." That was the Stage 1
  overlay (`34942315`); the contact now opens the panel.
* `FORMS.md`, owner rulings: said `polished_codec.key` "today keeps form 0-4 as traits". `key_form`
  normalises cosmetic forms now (`server/adapters/polished_codec.py:82-85`).
* `LIVE_RESULTS.md`, the Alolan Persian GAP: closed in code by `43ee19f0` and the effective-species wire.
* `PHONE.md`, `PHONE_SLOT.md`, `POKEGEAR_SLOT.md`, `TITLE.md`: said ROM0 has "351 bytes free at `$015f`".
  `$015f` is that **count**, not an address; the real gaps are `$0089-$00FF` and the part of `$3F34-$3FFF`
  after the phone bridge. `HOOKS.md:812-813` carries the correction.
* `CLIENT.md` line 4 quotes overlay sha1 `29ea04c2` as current. That is right for the runs it describes;
  the current overlay is in `data/polished/overlay_provenance.json`.

## Unverified in this table

* Every LIVE-RUN statement is a claim about a historic DEV run recorded in `LIVE_RESULTS.md`,
  `LIVE_SOUNDS.md` or a lane result file. None was re-run here and none is a PHYSICAL receipt. The
  lane files under `F:/slink-work/lanes/` are outside the repository.
* The count "18 failing items" is the coordinator's figure; this rewrite started the verifier and
  stopped it before it finished.
* Test counts are collected, not passed.
