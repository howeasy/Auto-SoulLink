# SLink — Gen 1 rewrite release notes

**Owner draft — not a release verdict.** This note describes the release-preparation tree and its recorded evidence, not a completed tag; the version is not stated here because it comes from the git tag at publication (`.github/workflows/release.yml:3-5,21-34`). It was drafted against a `471529b`/`c2605ae` snapshot whose identity was †UNVERIFIED at drafting time; this pass re-verified citations against the branch tip at the time of this card (172 commits ahead of the merge-base `d2c30fb` with `master`). Pending integration and reruns remain explicitly listed in `docs/gen1_resume.md:73-91`.

Citations below point into the repository tree; `prep/PLAN_v3.9.md` is the owner plan. Re-check citations and replace the verification status with final-tree receipts before publication. The existing docs directory contains no prior release-note file; this draft uses the repository's Markdown heading/bullet/table style rather than claiming an established release-note template. No CHANGELOG or source-version bump is proposed; the packager accepts an explicit version and otherwise uses `dev` (`tools/make_release.py:416-418`).

## What's new

Grouped by area, from the commit log between the merge-base `d2c30fb` and this branch tip.

**Client.** The Gen 1 client was rewritten from pret data rather than the pre-rewrite reverse-engineered evidence (`02283ce`): a composed runtime — `lua/gen1/entry.lua` wires reads, engine signals, guarded writes, boxes, ROM reads, the trade overlay and the native panel — sits under `lua/gen1/run.lua`'s BizHawk bootstrap. Generated profiles, engine-site bytes, wild/fishing tables, evolution families and dex mappings are pinned to pokered `405b6246372d7e5a2cb029cbb65219b13286b8c9` and pokeyellow `0a08515`; Archipelago is profile-generation-only in this release (`docs/gen1_requirements.md:3-24,46-51`). HUD rendering was moved into its own `pcall` after the protected tick so a tick error can no longer skip a frame's redraw, and a HUD error can no longer skip Gen 3-5 bookkeeping (`77d1e91`). Yellow-specific driver fixes (lab/parcel scripted play reaching first contact, `1a205c3`/`2492554`) landed alongside the shared Red/Blue path.

**Server.** `GameRulesAdapter.native_trade_ui()` (`eef6a1c`) replaced six `game_id == "gen1_rby"` branches in the shared trade FSM with a capability the Gen 1 adapter opts into for Red/Blue only — Yellow and every other game keep the ordinary server-driven trade menu, consistent with `supports_info_panel()`. Sync commands (`party_mon`, `box_mon`, `memorialize`) now stay in flight until acked or the reconciler's pass budget expires, closing a double-delivery bug where a drift reconciler could re-issue a command already on the wire (`d9225a1`); TCP sequence numbers are now scoped per connection and ignored before hello (`0629736`); the trade watchdog notifies both players when it abandons a confirming trade instead of freeing the slot silently (`580b3f8`); and the board's stat-stage chips read their labels from the adapter's `stat_stage_labels` capability, so Gen 1 renders DEF/SPC instead of Gen 3's SATK/SDEF (`56b2e2c`).

**Harness.** The duo E2E runner (`tools/e2e_duo.py`, game `gen1_new`) grew a dedicated Lua driver (`lua/tests/duo/duo_gen1_main.lua`, separate from the shared `duo_gb_main.lua` Gen 2 uses) and eighteen scenarios — `link_new`, `deadzone_new`, `linked_faint_bench_new`, `linked_faint_active_new`, `reconnect_new`, `ball_gate_new`, `trade_new`, `soft_reset_new`, `trade_decline_new`, `explode_new`, `pc_ops_new`, `changebox_new`, `whiteout_new`, `type_clause_new`, `species_clause_new`, `poison_new`, `rival_swap_new`, `admit_randomized_new` — pairing Red (player A) against Blue (player B). Battery-save fixtures for all three titles were rebuilt from scripted play rather than byte-staged (`tools/gen1_fixtures.py`, `tools/gen1_playthrough.py`). Individual scenario hardening landed throughout the sweep: the Explode branch's RNG-loss retry phrasing (`e6aa7a4`, `733cd59`), a walk-back path around incidental Route 1 grass battles (`f453238`), and the reconnect probe's kill-and-relaunch sequence (`944ec61`) — each red-first under the fail-closed runner and its live receipts.

**Launchers and package.** Both production launchers now load the rewritten client (`ca17a26`): `lua/slink_gen1.lua` `dofile`s `lua/gen1/run.lua` directly, and the universal `lua/slink.lua` routes any GB/GBC cartridge through `Entry.detect_title` before it ever reaches the legacy `game_detect`/`_CLIENT_MAP` path. `tools/make_release.py` now ships the rewritten client's full closure in the player ZIP — the ten `lua/gen1/*.lua` modules, `json_codec.lua`, `gen1_write_safety.lua`, and the five `data/games/gen1_rby/*.json` files `entry.lua` opens — alongside the legacy client, which still ships pending its own retirement below.

**Legacy retirement.** The pre-rewrite Gen 1 gates, probes and console diagnostics were retired (`9aa7989`): 26 `lua/tests` scripts and `tools/gen1_ap_rom.py` deleted, `tests/live/test_gen1_gates.py` cut down to the companion-patch-only gates (patch, menu row, randomized panel), and the AP skip allowance dropped from both `tools/verify_gen1_release.py` and the `no_hardcoded_addresses` check. The two pre-rewrite client gates were dropped from the `live-gates` lane earlier in the sweep (`82ced2d`), and the adapter rewrite itself retired the old natdex tests (`02283ce`). The legacy client (`lua/clients/gen1_rby_client.lua`, `lua/games/gen1_rby.lua`) is no longer reachable from either launcher but still exists in the tree and still ships in the package, pending Track B step 5 (P8-4).

**Docs.** The ledger (`docs/gen1_requirements.md`), `docs/protocol.md`'s sync-command-lifetime section, `docs/gen1_engine_sites.md`, `docs/shared_runtime.md` and `docs/gen1_rebase_plan.md` were written or re-verified against the branch tip across roughly forty `docs(gen1*)` commits, tracking each requirement row's evidence as live receipts landed (e.g. `64a5bfb`).

**An explicit physical-evidence bar carries through all of the above.** A ledger requirement closes only with SOURCE plus PHYSICAL evidence: real cartridges in BizHawk, judged independently through engine hooks, Python decoding, game screens/save loading, server state or an independent control. MODEL tests alone never close a row; pre-rewrite evidence does not count (`docs/gen1_requirements.md:3-11,26-36`). The reusable mechanisms this rewrite produced — signal dispatch, armed write windows, hello/validation/queue handling, composition, JSON/HUD helpers, post-result oracles and the fail-closed runner — are porting material, not a completed cross-generation framework: Gen 1 layouts and policies remain Gen 1-specific, and a later consumer must supply its own bank/register model, site table, layouts and checkpoint predicate (`prep/PLAN_v3.9.md:874-887`).

## What the recorded cartridge evidence proves

These are the ledger's physical claims, not an assertion that all release rows are complete:

| Capability | Evidence and boundary |
|---|---|
| Hook bytes, live reads, stat control and qualified saves | F-2/F-6/R-1/R-2: pinned hooks on hardware, six inspect cases, independent Lua/Python decode, saved-stat recomputation and seven qualified fixtures (`docs/gen1_requirements.md:47,51,57-58`). |
| Scripted New Game and starter/rival sequence | S-1: Red/Blue plus Yellow's recorded lab-gate pass (`docs/gen1_requirements.md:66`). |
| Route 1 capture, consumption and ball gating | S-2/D-2: real captures/RUN, one consumed ball per saved bag, pre-ball RUN withheld, starter pair linked while the lab-loss gate remains closed (`docs/gen1_requirements.md:67,105`). |
| Map/area identity and gifts | S-8 map-load/area/gift subclauses are physical; statics and fishing maps remain MODEL (`docs/gen1_requirements.md:73`). |
| Encounter linking and dead zones | D-1/D-3: server state plus cartridge readback; catch-in-dead-zone retirement also witnessed (`docs/gen1_requirements.md:104,106`). |
| Linked faint in both write windows | W-1/W-2/D-6: checkpoint bench faint and living active battler forced to faint at the loop head; native faint tilemap and independent saved bytes (`docs/gen1_requirements.md:79-80,109`). |
| Memorials, checksum-safe save reload, box change and command-driven PC sync | W-5/D-8/D-9: Box 12 readback, same-save reload, ChangeBox and both sync command directions. This does not close the separate S-6 PC-menu operations row (`docs/gen1_requirements.md:71,83,111-112`). |
| Wrong-save refusal and reconnect | C-1/C-2/D-14: wrong OT refused with links unchanged; same save reconnects without duplicate gameplay events (`docs/gen1_requirements.md:92-93,117`). |
| Randomized cartridge admission | C-5: matching randomized Red admitted; mismatching clean Blue refused; saved cartridge bytes independently qualified (`docs/gen1_requirements.md:96`). |
| Red/Blue SLINK TRADE | T-1/T-2: one Center's native menu/fall-through and ineligible refusal. T-3/T-4: YES and NO paths, received mon in last party slot, decoded swapped halves. Trade evolution/save-reload coverage remains limited (`docs/gen1_requirements.md:123-126,149-150`). |
| Type rejection | D-5 type half physical, including rejected mon in saved Box 12; the row stays partial because gender is MODEL-only (`docs/gen1_requirements.md:108`). |

S-7's runner-side witness receipt, D-4's link-after-reroll completion and C-3's dashboard proof are not complete in this snapshot. Poison/whiteout, PC-menu operations and Explode Mode have pending fixes/reruns; do not turn an observed intermediate action into an end-to-end pass (`docs/gen1_requirements.md:69,71-72,81,94,107,110`; `docs/gen1_resume.md:47-53,73-91`).

## Upgrade and prerequisites

- **Use the new release's launcher and complete runtime, not a saved copy of the old Gen 1 client.** This has shipped: both launchers route to `lua/gen1/run.lua` over `entry.lua` (`ca17a26`) — `lua/slink_gen1.lua` `dofile`s it directly, and the universal `lua/slink.lua` detects GB/GBC and routes through `Entry.detect_title` before the legacy `_CLIENT_MAP` is ever consulted. The package manifest (`tools/make_release.py`) ships the new client's full closure alongside the still-present legacy client. Package extraction and a real Red boot through the extracted launcher should still be re-proven on the final tag tree (`prep/PLAN_v3.9.md:899-902`).
- **Both players need their ROM and the full runtime assets.** Downloaded launchers are stubs; sending only a `.lua` file is insufficient. Load the cartridge/save before the script (`README.md:23-25,55-62`). The Gen 1 evidence environment is BizHawk **2.11.1, Gambatte**, not a promise that every version in README's generic 2.9+ range was verified (`docs/gen1_requirements.md:21`).
- **Clean US ROM pins:** Red SHA-1 `ea9bcae617fdf159b045185467ae58b2e4a48b9a`; Blue `d7037c83e1ae5b39bde3c30787637ba1d4c48ce2`; Yellow `cc7d03262ebfaf2f06772c1a480c7d9d5f4a38e1` (`docs/gen1_requirements.md:20`). Randomized admission additionally checks the run contract's content fingerprint (`docs/gen1_requirements.md:96`). Red/Blue native trade uses the companion patch; Yellow trade is excluded (`docs/gen1_requirements.md:119-127,157-158`).
- **For maintainers reproducing evidence:** use newly qualified scripted-play fixtures, not legacy byte-staged fixtures or old savestates. All seven fixtures are recorded qualified with LEGACY empty; this is a test prerequisite, not a demand that players replace legitimate saves (`docs/gen1_requirements.md:9,51`; `docs/gen1_resume.md:99`). Missing emulator, ROM or UPR jar fails the release gate rather than converting a skipped lane into a pass (`tools/verify_gen1_release.py:4-9`).

## Verification counts and release status

| Check | Recorded result / configuration |
|---|---|
| Unit suite | **3084 passed at `1093ee7`**, reported in the resume; not a run on this snapshot or the final rebased tree (`docs/gen1_resume.md:95-96`). |
| Fixture qualification | **7 OK; LEGACY empty**, ledger F-6 (`docs/gen1_requirements.md:51`). |
| Inspect gate | **6/6** live reads (`docs/gen1_requirements.md:57`). |
| Yellow lab gate | **1 passed, 8 deselected**, a targeted receipt, not a whole-lane pass (`docs/gen1_requirements.md:66`). |
| Runner inventory | **12 configured lanes: 8 fast, 4 emulator**; count from the executable lane definitions, which `docs/gen1_gen2_runtime_checks.md` now matches (`tools/verify_gen1_release.py:52-53,92-139`; `docs/gen1_gen2_runtime_checks.md:15-26`). |
| Final release runner / final total test count / Gen 3 regression | **†UNVERIFIED: no final-tree run output supplied or executed for this drafting card.** Quick mode explicitly is not a release verdict (`tools/verify_gen1_release.py:271-279`). |

Publication requires the full final-tree runner receipt, ledger closure outside the recorded limits, Gen 3 shared-path verification (or explicit unavailable-prerequisite disclosure), extracted-package boot, fast-forward integration and owner tag approval. Attach the actual runner output with this note; do not substitute the configured lane count or historical unit count (`prep/PLAN_v3.9.md:888-903,974-976`).

The following section is reproduced verbatim from `docs/gen1_requirements.md:139-167`, including both earlier limits. Its embedded implementation line references are the ledger's own historical references, not independently re-certified here.

## Recorded limits

Out of scope for this tag — the owner-accepted limits text, verbatim (the three 2026-09-17
amendments are already inside it: F-3/S-2 bag removal, S-8 statics and fishing, W-5 full memorial
box):

S-3 (party full → box), S-5/D-10 (Moon Stone / NPC-trade key migration; SOURCE+MODEL only — the old
gate staged RAM), W-4/D-11 rival team swap ONLY if A13 is skipped, D-13 key collision (MODEL: client
refuses ambiguous keys on both lookup paths; outbound `emit_faint` still reports the colliding key;
1/65536 per pair), R-3 badges/PP-Ups non-zero decodes (MODEL; fresh cartridges hold zeros) and the
rival's NAME on the wire (class only), T-1 physical at every Center (one Center), T-3/T-4 trade
evolution + save reload (MODEL), D-12 HUD game-over text (overlay, not tilemap-readable), C-3 SPC
stage-chip rendering (MODEL: no early Special-stage move; DEF chip and PSN pill are physical), C-4
fault injection (MODEL by construction), F-3 evolution and capture→box sites (MODEL) and bag REMOVAL
observed by the bag read rather than a hook (S-2 subclause amended), S-8 statics and fishing maps
(MODEL; unreachable on this route — gifts are physical), W-5 full memorial box → `memorialize_failed`
(MODEL; 20 memorials are not driveable), S-6 release of a
boxed linked mon is not propagated (shared-protocol gap in every gen; observed and logged, pair stays
ALIVE with a phantom boxed half), Yellow duo/trade/panel
(no free WRAM for the mailbox), AP variants, durable runtime / paired checkpoints, whiteout without a
rebuildable pair (= the proven game-over path), Explode Mode on a benched target (= faint at the
checkpoint), `ChangeBox`'s own save carries no witness (the next SAVE does), the panel patch keeps
AWAIT after its 90-frame timeout (the client enforces the deadline; a patch fix changes the DIST-1
md5s), the two-write bank-1 window (REVIEW-BOXES-1), two-human session (first post-tag).

Limits recorded earlier, kept in full:

- **Box writes touch the game's own SRAM structures.** The initialised-boxes flag + main checksum are written as two bank-1 bytes (`780d6c1`); a process death between them rejects the save on boot (two-write window). Recomputing the checksum would also re-seal a damaged-but-named save (unreachable mid-run: the save loaded at boot). A crash between the bank-1 write and the WRAM flag write self-heals on the next hello (memorialize re-queued). OMP review REVIEW-BOXES-1.
- **Force-faint demotion is silent.** When the queued in-battle write misses its `MainInBattleLoop` head (the mon was switched out or already KO'd before the next head), `lua/gen1/client.lua:754-756` moves it to the checkpoint queue and `:411-421` drops it if the key has left the party, logging one line and sending no NACK (the protocol has none). Observed live 2026-09-17 in a `linked_faint_active_new` run where the wild KO'd the 5/15-HP linked mon in the same turn; the scenario now cancels the move menu so the write lands before any enemy move.
