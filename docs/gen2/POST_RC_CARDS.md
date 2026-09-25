# Gen 2 post-RC cards

Work found or requested during the RC final sweep (freeze `df04e065`, 2026-09-24) and deliberately held out of
the RC so the production code digest (`ccd62421…`) and its receipts stay valid. Each card states the problem, its
evidence, the proposed shape, the first falsifier, the exit evidence and what it costs in re-proof. Nothing here
ships without the owner's authority. Rows marked **GATE** must land before the named event.

Evidence ids: `cx-…` are OMP (magi) task ids; reviews are read-only and every finding was checked against the
source before it was accepted here.

## Ordering

1. KEY-SCOPE-5: **GATE before Gen 3 rides this server**. It is also an owner decision whether Gen 2's release waits for it.
2. SP-LOWWATER, REVIEW-P4-HASH: evidence hygiene, cheap.
3. PHONE-NAMES, TITLE-VERSION: owner-requested features.
4. The rest: driver/fixture robustness, housekeeping.

Every card that touches CODE_SCOPE (`tools/gen2_code_digest.py`: `lua/*.lua`, `lua/gen2/**`, `lua/core/**`,
`server/**/*.py`, `data/games/gen2_*/**`) changes the production digest. Every stamped receipt then goes STALE,
so batch those cards and re-run `tools/gen2_final_sweep.py` once.

---

## KEY-SCOPE-5: harden the key_change collision check (server)

**Why.** KEY-SCOPE-4 (`1dc9dfc8`) accepts a `key_change` that its own tick beat, instead of killing the pair. OMP review
`cx-96f94b31` found gaps around it. The coordinator checked each one against the source:

| # | Finding | Status | Reachable in Gen 2? |
|---|---|---|---|
| F1 | The self-report proof counts `partner_blobs`, a filtered cache: entries with a missing/malformed `blob_hex` are dropped (`server/state.py` `_ingest_party_blobs`), so a genuine duplicate with no blob is invisible and the collision is waived | regression from 1dc9dfc8 | No. The Gen 2 client fails the whole snapshot closed on any missing blob (`lua/gen2/client.lua:211-223`). **Gen 3 is reachable**: it sends `blob_hex=""` on a failed read (`lua/clients/gen3_frlge_client.lua:1304-1306`) |
| F2 | A same-mon tick whose entry has no blob (or an adapter with `party_blob_size()==0`) still rejects and kills `identity_lost` | pre-existing behaviour (before 1dc9dfc8 every tick-first case rejected) | No (Gen 2 always has blobs) |
| F3 | The boxed-twin check trusts `srv.pc_boxes`; if the box census is absent or stale (`pc_boxes` is optional on the wire, `docs/protocol.md`), a boxed twin is missed once the party refs are waived | regression from 1dc9dfc8 | Low: Gen 2 sends `pc_boxes` from `box_cache` on every tick/hello |
| F4 | A reconnect replay where the hello re-reports the old key is rejected, not acked `migrated:false`; a delayed old tick can roll `party_keys` back | pre-existing | Only via a soft reset or reload onto a pre-change save; unconfirmed |
| F5 | The `ambiguous_keys` latch is checked on `old_key` only; a latch on `new_key` doesn't veto the waiver | pre-existing | Needs an earlier KEY-SCOPE-3 clash plus a dead index; improbable |
| F6 | `_presentation_key_in_use` excludes only the primary memorial box, not overflow memorial boxes (`_memorial_box_indices`), so a buried key reads as live | pre-existing | Needs an evolution into a key equal to a buried mon's key; improbable |

**Shape.**
1. Keep a raw per-player party key list, including entries with no blob, at every hello/tick/safe ingest. Prove "self-report" from that multiset (`count(new_key)==1 and old_key not in raw`), never from `partner_blobs`.
2. An absent or stale box census fails closed. Either keep a server-side box-key index updated only from complete box snapshots, or hold the key change until a fresh census arrives.
3. `_presentation_key_in_use`: use `_memorial_box_indices()`.
4. The ambiguity latch is checked on both `old_key` and `new_key`.
5. A bounded accepted-migration ledger (`old→new`), so a replay acks `migrated:false` and a stale snapshot can't re-add the old key.

**Files.** `server/state.py` (the `_handle_key_change` collision block, ingest, reconcile), `server/server.py`
(`_presentation_key_in_use`), `tests/unit/test_state_key_scope.py`, `tests/unit/test_state_key_change_ack.py`.

**First falsifiers.** OMP's 9 listed cases (`cx-96f94b31` "TESTS"). At minimum:
- two same-key party entries, one without a blob → reject;
- a same-mon tick without a blob → accept;
- a boxed twin with `pc_boxes` omitted → reject;
- accept, then a reconnect hello with the old key, then a replay → ack `migrated:false`;
- `ambiguous_keys[new_key]` → reject;
- an overflow memorial key → reusable.

**Exit.** Unit tests red→green, a Gen 3 run by the Gen 3 lane, and a full Gen 2 re-sweep (it's a server change, so the digest moves).

**Detailed design (OMP `cx-ee316c45`, checked):**
1. **Raw party census.** Add `party_key_census[pid]` (key → count) plus a `current` flag, taken from every hello/tick/safe party list BEFORE blob filtering (at the top of `_ingest_party_blobs`, ahead of the `party_blob_size()==0` return).
   - In-memory only, never persisted: a stale observation must not waive a collision after a restart.
   - Predicate: `current and raw[new_key]==1 and old_key not in raw`. Drop the extra `party_keys` term.
2. **Box census completeness.** A census counts as complete only when the message carries `pc_boxes` together with a new `pc_boxes_generation` (monotonic per client session). Missing, stale, repeated or invalidated means incomplete; a box mutation invalidates it.
   - The collision hook becomes tri-state (`True/False/None`), and `None` rejects with "box census unavailable".
   - Clients: Gen 1/2 bump the generation after each successful full `rescan_boxes` (never on failure). Gen 3 publishes a full census at hello, reusing its startup box walk.
   - **Reject only after an atomic client+server cutover**; otherwise implement HOLD first (a persisted pending queue and a `key_change_pending` response). A missing census is uncertainty, not evidence of a collision.
3. **Memorial indices.** `_presentation_key_in_use` excludes every memorial box index. **Also fix `_memorial_box_indices`** (`server/server.py:4518-4546`, coordinator-verified):
   - `(dead - per_box) // per_box` misses the first overflow box (21 dead at 20 per box gives 0);
   - it adds both players' `pending_memorials` to one link count.
   Count per player (dead/memorial link halves ∪ pending) and use a ceiling. The helper is currently uncalled, so fixing it changes no behaviour today.
4. **Ambiguity latch.** `_refuse_ambiguous` also checks `new_key` on a `key_change`, before the replay ledger. Refuse; don't retire the pair.
5. **Replay ledger.** A persisted per-player `deque(maxlen=256)` of accepted `{old_key,new_key}`, checked before the old-key lookup, so a replay acks `migrated:false`.
   - `_dispatch` migrates presentation only on an internal status of "migrated".
   - Stale snapshots are canonicalized through the ledger: an old alias resolves to its terminal key; an alias and its terminal key both present in one snapshot latches ambiguity.
   - A server-owned `connection_generation`: the newest hello supersedes older sockets.
6. **Tests.** The 9 pytests are named and specified in `cx-ee316c45` §6. Cases 1-7 and 9 are red on the current code; case 8 (both-sided NPC trade) is a green control.
   - Maintenance: update `_snap` with the blob/generation parameters, and delete the source-text test `test_the_server_migrates_every_structure_on_a_key_change` (`tests/unit/test_gen1_statics_and_trades.py:73-86`).
7. **Blast radius.** Clients for Gen 1 (generation field), Gen 2 (generation, and a failed rescan must not advance it) and Gen 3 (a full hello census). Adapters with `party_blob_size()==0` gain the fixed raw self-report.
8. **Size.** Server ~190-300 LOC, clients ~50-100, tests ~260-380, docs/schema ~25-50. Order: census+predicate → box generation → memorial → latch → ledger/fencing.

**Gen 3 follow-up (Gen 3 lane; not done in the KS5 batch).**
- Owner default, as built: a missing or stale census REJECTS (`box census unavailable`; after `cx-8f3a6ce9` F2 it retires nothing), but only for a client that advertises one by sending `pc_boxes_generation`. `lua/clients/gen3_frlge_client.lua` sends none, so Gen 3 keeps the presence-based `pc_boxes` check, which is F3's gap.
- Gen 3 gets the raw party census now, with no client change: F1 (a duplicate without a blob) rejects and F2 (a same-mon tick without a blob) accepts.
- To close F3 for Gen 3: publish a full box census on hello by reusing the startup box walk, send `pc_boxes_generation` only with a complete census, and never send it with the incremental 2-4-box tick cache. Otherwise every key change in the first seconds after connecting would be rejected.
- Then a Gen 3 live run: a Nature Changer on a linked mon, plus a reconnect replay.

---

## SP-LOWWATER: measure the worst-case stack during battle-text service

**Why.** OMP hook census `cx-f10d0dca` §7: `patch/gen2/src/slink.asm:50-52` says the live minimum SP in battle/link is
unmeasured. The `DelayFrame` bridge → `SlinkService` → `PlaySFX` → VBlank chain is statically balanced, but no receipt
records its low-water mark. Gold's stack is `$DF03-$DFFF`. No overflow has ever been observed. This is an evidence gap,
not a known defect.

**Shape.** Reuse the trade stack witness v2 (the bus-write hooks over `[wStackBottom, floor+64)` plus the SP-1 canary; the
canary geometry is `address == SP` under gambatte, `e57b9954`). Run it in a live gate that posts SFX and phone requests
while the PC is in `PrintLetterDelay` with `wTextDelayFrames != 0`, with A/B held and not held. Record the SP low-water,
`hVBlank`, `wTextDelayFrames` and `wVBlankOccurred`.

**Exit.** A PHYSICAL receipt per title, with a margin to `wStackBottom` ≥ an agreed floor. Harness only, so no digest change.

## REVIEW-P4-HASH: refresh a stale review artifact

`docs/gen2/reviews/REVIEW_P4_OVERLAY_ASM_2026-09-24.md:6-10` names overlay hash `d563669e`; the current Gold overlay is
`15fc8213…` (`data/gen2/overlay_provenance.json:144-150`). Mark it superseded, or re-point it at the current artifact.
Docs only.

---

## PHONE-NAMES: phone calls name the partner trainer and the Pokemon (owner request 2026-09-24)

**Why.** Today every SLink call is fixed text. The server adds only `"phone":"fallen"|"dead_zone"|"first_link"`
(`server/state.py:2355,2673,3679`). `lua/gen2/phone.lua` maps that to ID 1-3 at mailbox +32. `SlinkPhoneCallScript` picks one
of four fixed `writetext` blocks (`patch/gen2/src/phone.asm:113-141`). The caller header shows `PHONE_00` "----------".

**Feasibility (OMP `cx-db0c2158`, spot-checked): M.**
- The data exists: the fallen command already carries the nickname (`server/state.py:3675`); the trainer names are in `player_identity`/`trainer_names`.
- The mailbox is too small (39 B G/S, 40 B Crystal, `patch/gen2/src/slink.asm`; about 5 bytes free, two names need 22).
- Stage in `wUnusedMapBuffer`: 24 B, Crystal `$C7E8`, G/S `$C6E8`. `HandleNewMap` clears it (`engine/overworld/warp_connection.asm:1-4`), so it needs a cookie byte, and an invalid payload falls back to the fixed text.
- The call script copies the names into `wStringBuffer3/4` (19 B each) and prints them with `text_ram`.
- The caller name needs a `GetCallerName` hook gated on `wSpecialPhoneCallID == SPECIALCALL_SLINK`, because the header renders before the script (`engine/phone/phone.asm:424-428`).
- Encoding: reuse `T.encode_name` (`lua/gen2/trade_overlay.lua:95-105`) plus `data/games/gen2_*/charmap.lua`. There is no Python-side encoder. Lines are 18 tiles, so the example needs two lines.
- Cheapest first version: send the species ID and use the native `getmonname`; add nickname transport later.

**Top risk.** Scratch lifetime: the staged bytes must survive from arming until the delayed ring, across map changes.

**Detailed design.** OMP `cx-ee02eac7` (in flight at the time of writing; its result is appended below when it lands).

**Exit.**
- unit tests: client staging, the ABI linked-byte tests, the protocol schema;
- the phone live gate extended to a map change between arming and ringing, max-length names, and all three titles;
- the overlay sha1s re-pinned;
- a re-sweep. This touches CODE_SCOPE, so batch it with KEY-SCOPE-5.

**Owner questions.** Nicknames or species names? The wording?

## TITLE-VERSION: SLink version on screen, then an SLink logo (owner request 2026-09-24)

**Feasibility (OMP `cx-b41bfa58`, spot-checked): text S, logo banner M.**
- The main menu is the easy spot for text: the font is already loaded (`engine/menus/main_menu.asm`). On the title screen, `LoadStandardFont` would overwrite logo tiles in `vTiles1`, so title-screen text needs a tiny custom tile strip.
- The Gold/Silver subtitle is baked into `gfx/title/logo_bottom_{gold,silver}.png` (`gfx/misc.asm:9-23`). Crystal's is in `gfx/title/logo.png` (`engine/movie/title.asm:75-79`).
- `rgbgfx` v1.0.3 is in the pinned toolchain (`.cache/build-tools/rgbds-v1.0.3/bin`).
- `verify_symbol_scope` (`tools/build_gen2_companion.py:451-469`) forbids moving native symbols. The hook must be a same-size trampoline at a fixed address, or get a narrow exemption.
- A visible stamp changes every overlay sha1 pin (`data/gen2/overlay_provenance.json:129-174`) on every release. The version must come from an explicit release version or a clean exact tag, recorded in provenance. The builder hashes only `.asm/.inc` today (`:535-552`), so it must add the version and the PNG inputs.

**Detailed design.** OMP `cx-26133223` (in flight at the time of writing; its result is appended below when it lands).

**Owner questions.** Who draws the logo? A clean pixel "SLINK" placeholder is proposed. The wording? Main menu only, or the title screen too?

---

## Robustness and housekeeping

- **POISON-DUO-CAP.**
  - G-S `gen2_poison` fights Route 31 Wade once per save. Even with `PI.STING_LOW_HP=6` in trainer sting fights (`7f20ecc2`, derived from the decomp: Wade's fixed-DV Weedle deals at most 6), the 15-HP target caps the success rate at ~83%/fight. The sweep allows 2 attempts (`89b33356`).
  - Option: an O-33 disclosed seed where the linked mon starts poisoned, so only the overworld poison faint runs natively. That needs an owner check that it still tests what S-4 intends.
  - **Evaluated (OMP `cx-67178e9a`, coordinator-reviewed):**
    - The verdict checks only the `poison_faint` engine event and the following `faint` send (`scenario_gen2_poison.lua:2-15,37-55`; S-4 names `DoPoisonStep`).
    - A PSN seed can't target the linked mon, because it is created by the in-run capture.
    - OMP proposed planting a poison move in the capture battle plus pinning the battle RNG. **Rejected:** in its own capture battle the linked mon is the *wild* side, so the plant would poison the player's lead, not the catch. Pinning the RNG would also rig the game behaviour the scenario exercises.
  - **Decision: keep the native Wade fight.** It's ~83%/fight with `STING_LOW_HP=6`, and 2 attempts give ~97%.
  - Revisit only if a disclosed post-capture plant is designed: a second wild battle with the linked mon active against a planted POISON STING/POISONPOWDER foe, with no RNG pin. That's still probabilistic but gives more rolls.
- **TRAINER-SEED-A.** In the RC re-run pass, C-C `gen2_faint_active_trainer`'s A side (the native L5 errand save) lost its Route 29 link-capture battle (catch RNG). If the retry also fails, give A the same O-33 L10 seed B got (`5a7b04c8`). That changes one release row.
- **TRADE-EVOLVE-CATCH.** `gen2_trade_evolve` ran out of balls in 3 of 5 link captures during the RC sweep; the other trade cases on the same errand fixtures never did.
  - Cause: O-31's disclosed plant (`lua/tests/duo/gen2_trade.lua:90`, `tools/gen2_trade_facts` `plants.evolve_species`) makes the first Route 29 wild mon a HAUNTER. Catch rate 90 gives ~12%/Poké Ball at full HP. A's Totodile only knows SCRATCH/LEER, which can't touch a Ghost, and Lick paralysis and Mean Look drag the fight out. One G-S run spent all 15 balls in a single battle.
  - For the RC: up to 3 attempts per cell.
  - Post-RC fix, recommended: an O-33 SYNTH A seed with the builder's existing `balls` edit (`[["MASTER_BALL", 5]]`), so the catch is certain while the plant and the evolution stay native. This changes the trade oracle's `expected_case` boot fixture sha256 and the release row.
  - Alternative: the plant also lowers the planted mon's HP or level, which changes the plant disclosure.
- **TRAINER-FAINT-LIVE-TURN.** `gen2_faint_active_trainer` requires an `enemy_turn` after `REPLACED`.
  - With B's L10 seed (`5a7b04c8`), the replacement's first Scratch can crit-KO Joey's only mon (the L4 Rattata, ~17 HP) before it moves: ~7% a turn. That happened in the RC run on C-C `fsw-rerun2`, after every behaviour under test had proved physically.
  - Fix, verdict/oracle only: "a live turn" = an `enemy_turn` after `REPLACED`, OR a witnessed enemy faint after `REPLACED` (a `FaintEnemyPokemon` exec hook from the pack's battle_hold oracles, or a `wEnemyMonHP` read).
  - Rules to change: `tools/gen2_duo_oracles.validate_faint_active_markers(trainer=True)` and RELEASE-LANES' `_active_faint_cell_errors`. That's a release-row binding change.
  - For the RC: re-run as is (~93%).
- **GEN1-ENEMY-MAXHP** (reported by the UI lane). `lua/gen1/client.lua:279-285` `enemy_party` builds the foe as `{species_id, level, hp, active}` with no `maxHP`, so `server/board.py` `hp_pct` divides by `maxHP or 1`: every Gen 1 enemy shows a full bar and "17/".
  - Fix: read pret `wEnemyMonMaxHP` (2 bytes big-endian, next to `wEnemyMonHP`) through the reads' symbol resolution, and send `maxHP`.
  - Gen 2 is unaffected: `lua/gen2/wire.lua` `foe_entry` already emits `maxHP` and refuses a foe without it.
  - `lua/gen1/**` is outside the Gen 2 CODE_SCOPE, but it makes the Gen 1 receipts stale. Land it AFTER the Gen 1 release gate, then re-run the affected Gen 1 lanes.
  - The UI lane is adding a template guard (no bar when `maxHP` is missing), held for the post-freeze batch.
- **MASTER-MERGE** (post-freeze). Local master moved to `d3486463` (UI lane, not pushed; 3416 pass):
  - `server/server.py`: `enemy_party` sanitized at intake; sprite_html regenerated; `/api/reset` keeps the adapter; `?filter=all` on the event stream; calc_name passthrough.
  - `server/manager.py`: lifecycle locks and a readiness probe; the Windows liveness check no longer uses `os.kill(pid, 0)`, which killed runs.
  - Templates: a11y changes and the "HP 17" guard.
  - Also `lua/hud.lua` `66981144` and `a9bdce38`.
  - Merge or cherry-pick ONCE, together with BOARD-AMBIGUOUS (`95f2c629`) and the other CODE_SCOPE cards, then re-sweep once.
  - Our side: the `server/adapters/gen2_crystal.py` sprite `<img>` needs `alt=""` (the Gen 1 adapter already sets it).
  - **Refresh the shipped receipt copies** `data/games/gen2_{crystal,gold,silver}/receipts/*.engine_sites.json` and `*.write_window.json` from the CODE_DIGEST-stamped evidence copies in `tests/fixtures/gen2/receipts/`. They prove the same sites (27/27, checked). They're production data inside the digest, so the refresh has to ride the post-RC re-sweep; `dd783f2e` relaxed the byte-equality test until then. Longer term, consider moving shipped receipts out of CODE_SCOPE, or stamping their digest over the code only, so re-proving doesn't move the digest it binds.
- **ADMISSION-MIXED-KINDS-VERDICT** (server, found by GEN1-PCOPS). When the mixed-artifact-kinds check refuses a hello (`server/server.py:1386-1398`, `_mixed_games_error` ~:580), it sets `identity_error` but records no admission verdict. `/api/status` and the board keep showing the refused player as "admitted" with an empty reason.
  - Fix: also set `self.admission[pid] = {"state": "rejected", "reason": ...}` and journal a durable "REJECTED —" event, matching the other refusal paths. Red test first.
  - The harness no longer depends on hello order (`c8b7fc96`, pureRGB admit_randomized launches B first).
- **GEN1-UPR-FORK-SOURCE** (environment, OWNER). `tests/unit/test_upr_gen1_ini.py::test_handler_key_list_matches_the_fork_source` skips because the UPR fork source (`.cache/slink-upr/src/...Gen1RomHandler.java`) isn't on this machine: only the jars are. The Gen 1 gate treats that skip as unexplained, so its unit lane can't go green here. Restore the fork source checkout; don't add an ALLOWED_SKIPS excuse.
- **GEN1-GATE-REWRITES-RECEIPTS.** Running `verify_gen1_release.py` (live-gates lane) overwrites the committed `tests/fixtures/gen1/receipts/test_gen1_sfx_gate_*_result.txt`, dropping their `# lane HEAD=… git-status=clean` and `# cmd:` provenance header. This is the same trap as the Gen 2 attestation (`44f6fb97`). The coordinator restored the committed copies after the 2026-09-25 gate (the rewritten copies are in the scratchpad `gen1_sfx_rewritten/`). Fix: the gate writes to `patch/build` only, and a separate receipt-capture step stamps the header.
- **GEN2-CALC** (calc multi-gen lane contract, 2026-09-25). After that lane's P1 lands inert `calc_profile / calc_name / calc_nature / calc_stats` in `server/adapters/base.py` on master, merge master and implement them in `server/adapters/gen2_gsc.py`, NOT `gen2_crystal.py` (gone on this branch):
  - `calc_profile` → `{"gen": 2, "dex": "vanilla"}`, only once the numbers are right; None hides the Calc tab.
  - `calc_name` maps to the calc's GSC spellings (DynamicPunch→Dynamic Punch, ExtremeSpeed→Extreme Speed, Faint Attack→Feint Attack, BrightPowder→Bright Powder, TwistedSpoon→Twisted Spoon, BlackBelt→Black Belt…), generated from `calc/calc/src/data/{species,moves,items}.ts`; `tests/unit/test_rr_calc_names.py` is the model.
  - `calc_nature` → None.
  - `calc_stats(detail)` → `{"dvs":{atk,def,spe,spc}, "stat_exp":{hp,atk,def,spe,spc}, "stats":{hp,atk,def,spa,spd,spe}}`, decoded from `blob_hex` via `server/adapters/gen2_codec.py`.
  - stat_stages order sent to that lane: Atk, Def, Spe, SpA, SpD, Acc, Eva, values 0..12 with 6 neutral.
- **CLAUSE-BENCH-LIMITS.** OMP `cx-43b52a71` F2/F3/F5 were kept by design: the oracle cross-references the U2 receipt, and the full qualification lives in the release verifier's write-window lane; `PC == 0x0040` is a stricter harness invariant. Revisit only if that lane's coverage changes.
- **BOARD-AMBIGUOUS: BUILT, held for the freeze.** The UI lane's commit `95f2c629` is on branch `claude/ui-board-ambiguous` (worktree `Temp/uiamb`), cut from `0800da84`. Design from OMP `cx-8a2f08c6`:
  - add a top-level `ambiguous_keys` to the status and to `status_payload.py`;
  - render one `identity-warn` line per latched key in the per-player warning loop, showing the POST endpoint as a text hint (no link or button: resolving erases a safety assertion);
  - no `board.py` change and no new zone.
  It touches `server/**/*.py`, so cherry-pick it in the post-RC batch. The UI lane's `lua/hud.lua` commits `66981144` (GBA pixel font) and `a9bdce38` (the banner drops below a wrapped prompt on 160x144) are also CODE_SCOPE: pick them in the same batch.
- **TEMP-LANES.** Inventory from OMP `cx-1b2b86fe`:
  - Remove after the milestone: `trl`, `tr2`, `tr3` (all `5e6d5382`) and `sp2` (`67fd29ea`), plus the sweep's `fs1..fs4` once receipts are pinned and no sweep process remains.
  - `spd` (`70439d4f`) has an uncommitted `tools/e2e_duo.py` change: save the diff first.
  - `g1rc` (`ff4df383`) and `g2omp` (`9c015785`) need an ownership check. Their `.cache` junctions point into this worktree's `.cache` and the root `.cache/purergb*`.
  - `c47head`, `c4b2head`, `c338`, `c338h` and `c340-review-…` are not worktrees.
  - `.git/worktrees/ui-sprite-size` is another session's residue: never touch it.
  - Procedure: `git status --porcelain` per lane; unlink every junction with `os.rmdir` on the junction itself; `git worktree remove --force`, falling back to `shutil.rmtree` with a chmod `onerror`; then `git worktree list --porcelain`, and check the shared cache targets still exist.
- **PURERGB-OVERLAY-EOL: DONE (`65b3c4b1`).** The writer (`tools/gen_gen1_write_checkpoint.py --kind overlay`) emits LF, and the index blob is LF and byte-identical. `core.autocrlf=true` made git report the file as modified anyway. Fixed with an exact-file `text eol=lf` rule; the sibling Gen 1 packs were left alone. OMP `cx-a84b761e` guessed the stored copy had CRLF endings, and `git ls-files --eol` disproved that.
- **OMP-TIMEOUTS.** Headless OMP runs must be told their kill limit in the task text. Two 30-minute studies died silently (`cx-e179bf94`, `cx-a496d30a`); runs told "budget N minutes, reply PARTIAL if long" returned on time.

## Appended results

### PHONE-NAMES detailed design (OMP `cx-ee02eac7`; addresses checked against the linked maps)

**Wire.** Keep `phone` as the discriminator. Add an optional `phone_data`, relative to the receiver:
`{trainer_name, caller_mon:{species_id, nickname}, receiver_mon:{species_id, nickname}}`
- It goes on `force_faint`, `force_explode` and `msgbox`.
- The server builds it in `_propagate_faint` (`server/state.py:3663-3680`), from the source trainer and the recipient.
- It needs a separate per-recipient object for `first_link` (`:2344-2360`) and for `dead_zone` (`:2662-2681`): today one `linked_box` dict is shared by both queues.
- Missing data leaves the tag in place and omits `phone_data`, so the client falls back to the fixed text.
- Schema: `docs/protocol.md:318-363`, `tests/unit/protocol_schema.py:96-108`, with strict nested validation.

**Staging record** in `wUnusedMapBuffer` (Crystal `$C7E8`, G/S `$C6E8`, 24 B), the cookie deliberately last:

| Offset | Size | Field |
|---|---|---|
| +0 | 1 | event 1-3 |
| +1 | 1 | caller species |
| +2 | 1 | receiver species |
| +3 | 8 | trainer name (7 glyphs + `$50`) |
| +11 | 11 | caller nickname (10 + `$50`) |
| +22 | 1 | reserved, 0 |
| +23 | 1 | cookie `$A6` (layout v1) |

**Client** (`lua/gen2/phone.lua`):
- Encode with `T.encode_name`.
- An invalid or absent `phone_data` stages all zeros, which clears any stale cookie.
- The queue holds `{id, record}` atomically.
- Under one permit (the predicate widened to `stage/24` or `mailbox+32/1`), write the record first, then the request byte. A failed stage write blocks the request.
- While ARMED equals the in-flight id, check the cookie/event each frame (`phone:service()`) and re-stage ONCE if a map change wiped it (`HandleNewMap` → `ClearUnusedMapBuffer`, `home/map.asm:3-8`). No ROM hook on HandleNewMap.

**ROM:**
- `SlinkPhonePrepareCall` (a `callasm` in `SlinkPhoneCallScript`) validates the whole record (cookie, reserved, event == ARMED, terminators, species 1..251) before touching any buffer.
- Caller display goes to `wStringBuffer3`: the nickname, or the species via `GetPokemonName` (C `$343B`, G/S `$367E`). Receiver display goes to `wStringBuffer4` as the species name.
- `wScriptVar` selects the named text, or 0 for the existing fixed text, which stays as the fallback.
- `GetCallerName` (bank `$24`; C `$43A9`, G/S `$439D`): a same-size 5-byte entry rewrite, `jp SlinkPhoneCallerName` plus the native `jr`. The SLink path requires `wSpecialPhoneCallID == SPECIALCALL_SLINK`, `PHONE_00`, ARMED == the stage event and a valid cookie, and prints the trainer name with no colon. Anything else continues natively.
- The builder (`tools/build_gen2_companion.py:114-120,288-320,414-451`) adds the verify-once anchor edit, and the binary verifier allows exactly those 5 bytes.
- Space: ROM0 growth is 0. About 350-550 B goes in the service bank, which has ~13 KB free in both.

**Text** (≤18 tiles per line, worst case checked):
- Fallen: "BOB's / PIDGEY / fainted! / Your RATTATA / is gone too!"
- First link: "BOB's / PIDGEY / linked with / your RATTATA / They're linked!"
- Dead zone names the caller and keeps the current body.
- The built-byte width test must learn `TX_RAM` (it charges 7 tiles for the trainer name, 10 per mon name).

**Name policy (owner decision).** 24 B can't carry two full nicknames: that needs ~34 B plus metadata, and truncating both is rejected. The recommendation is the caller's mon by nickname and the receiver's mon by species. The server still sends both nicknames, so the policy can change later.

**Tests:**
- server direction and fallback;
- the nested protocol schema;
- Lua staging, order and re-stage-once;
- ABI linked bytes, buffers, text widths and mutations;
- the builder hook;
- profile stage addresses;
- the live phone gate v2 on C/G/S: the named header and body, max-length names, a map change between arming and ringing (a hook on ClearUnusedMapBuffer proves the wipe and the re-stage), and the fixed-text fallback.

**Re-proof cost.** Any `phone.asm` edit changes all three overlay sha1s. That means a republish of:
- provenance, sym/map and the UPS;
- the profiles and admission rows;
- 12 overlay gate receipts (panel/SFX/W6/phone × C/G/S);
- the trade receipts that bind the overlay (21 cells).

If G4 is already signed, the overlay grant fingerprint changes and needs re-signing. **Bundle it with the other overlay work (TITLE-VERSION) and KEY-SCOPE-5 into one re-sweep.**

**Size.** About 1,000-1,500 hand-written LOC across 18 files (the list is in `cx-ee02eac7` §7).

**Owner questions:**
- the asymmetric nickname policy;
- the wording;
- whether dead-zone calls name the caller only.

### SP-LOWWATER detailed design (OMP `cx-947d9423`)

- **Gate:** a sibling mode of `lua/tests/gen2_sfx_gate.lua`, reusing its qualified `<title>_battle` arrival, panel binding and Route 29 battle driver. It emits a separate `gen2-sp-lowwater-v1` receipt; `gen2-sfx-gate-v1` is unchanged.
- **Runs:** 3 fresh boots per title: `A_held`, `B_held`, `released`. Fresh boots are needed because phone ARMED is single-slot.
- **Trigger:** `PrintLetterDelay.checkjoypad`, with `wBattleMode == 1` and `wTextDelayFrames > 0`.
- **Requests:** post SFX via `panel:request_sfx`, and phone via `Phone:request("dead_zone")` (the shipped binders, never a direct write).
- **Caveat:** `.wait` never calls `DelayFrame`, so the `released` case means "posted while released, then resumed by a normal A press". It cannot mean "serviced while released".
- **Witness:** trade witness v2 (window `[wStackBottom, floor+64)`, canary with `address == SP`, plus the `hSPBuffer` arming fix `902cf7c8`). Every row also records hROMBank/hVBlank/rIE/wTextDelayFrames/wVBlankOccurred/the mailbox. Add SP guards at the service/audio exec hooks, so an excursion below the window can't pass.
- **Pass criteria:**
  - margin ≥ **N = 32** above `wStackBottom`;
  - text resumes within 300 frames;
  - the SFX is consumed and played;
  - the phone is acked and armed, and doesn't ring in battle;
  - `hVBlank == VBLANK_NORMAL` and `rIE & 1`.
  - If no VBlank overlapping the service window is observed, the result is **INCONCLUSIVE**, not PASS.
- **Static bound** (from the asm): PrintLetterDelay 12 + bridge/service/SFX/`_PlaySFX` leaf 38 + normal VBlank 36 = **86 B**, against a capacity of 255 B (Crystal) and 252 B (G/S).
- **Release:** a new `sp_lowwater_gate` kind in `LIVE_GATE_KINDS`/`CLIENT_PATH_GATE_KINDS`, a `_sp_lowwater_gate_row_errors` through `_overlay_gate_errors`, 3 rows `new-gates.sp-lowwater.<title>` (N-1/N-2) in `tests/gen2_live_gate_requirements.json`, and the suffix added in `test_gen2_physical_receipts.py`.
- **Size:** ~700-1,000 LOC, harness/tests/verifier only, so no digest change.

### TITLE-VERSION part A: version text on the main menu (OMP `cx-ee46a1ba`, checked)

- **Hook.** Each title's only `call SetUpMenu` (`MainMenuJoypadLoop`; Crystal `engine/menus/main_menu.asm:241`, G/S `:143`, one occurrence each, verified). A same-size 3-byte `call` goes to a small ROM0/same-bank bridge, which far-calls a service-bank routine. That routine far-calls `SetUpMenu`, then prints the version. A direct cross-bank `call` can't work: `call`/`jp` don't switch banks. ROM0 has 194 B (G/S) and 249 B (Crystal) free for the bridge.
- **Position.** Tile `(1,10)`: clear of the menu (rows 0-6), Crystal's time box (rows 14-15), G/S's time box (rows 12-15) and the G/S debug menu. The string is `SLINK vX.Y.Z`; glyphs `v`=181, `.`=232, `0-9`=246-255 (`charmap.lua:150,175,189-198`, verified).
- **Build.**
  - Add an explicit required `--version vX.Y.Z`, taken from the release tag rather than trusting `git describe`. It's injected as `DEF SLINK_BUILD_VERSION EQUS` and emitted with `db` through the title charmap.
  - Add `overlay.version` and `overlay.version_sha256` to provenance: today the CLI string isn't hashed (`tools/build_gen2_companion.py:535-548`).
  - Validate the anchor exactly once before mutating, following `_start_menu_text` (`:178-212,230-279`).
  - Assert the new labels link in the service bank. `verify_symbol_scope` is satisfied, since the call replacement is equal-size.
- **Release flow.** Build once from the tag, run the gates, then ONE promotion step regenerates provenance, profiles, admission and receipts from the same bytes, in one commit, with no hand-edited sha1s.
- **Size.** M: ~60-80 production + ~40-60 test LOC.
- **Risks.** Bridge space; `--check` must receive `--version`; any missed pin.

### TITLE-VERSION part B: the SLink logo banner (OMP `cx-face49ff`, checked)

- **The native subtitle is ONE row.**
  - Gold/Silver: 10 tiles at `(5,6)`, BG palette 3 (`engine/movie/title.asm:157-160`, verified). The art is baked into `logo_bottom_{gold,silver}.png` (`TitleScreenGFX1`), decompressed to `vTiles2`.
  - Crystal: 11 tiles at `(5,9)`, BG palette 1 (`title.asm:75-79`, verified). It's part of `TitleLogoGFX` in `vTiles1`.
- **Recommended: a same-size, one-row wordmark overwrite.** An `SLINK` wordmark of 10 tiles (160 B) on G/S and 11 tiles (176 B) on Crystal. The tile bytes are copied after the native decompression and before the LCD is enabled.
  - No new tile IDs, no tilemap edits, and no new CGB palette: reuse G/S palette 3 and Crystal palette 1. Crystal uses every BG palette slot 0-7.
  - On DMG it goes two-tone through `rBGP`; the silhouette survives.
- **If a 2-row banner is required:** 10×2 = 320 B in the free tile window G/S `$5C-$77` (28 tiles) or Crystal `$3C-$7F` (68 tiles), with both rows remapped. That's ~35-55 asm LOC, against ~20-30 for the single row. The Pokémon logo cells stay untouched either way.
- **Pipeline:** `rgbgfx --colors dmg -o x.2bpp x.png` (the generic Makefile rule; the Crystal logo also uses `--trim-end 4`), then a raw `INCBIN` in the service bank. Add the PNG to the builder's hashed inputs (see part A).
- **Unverified until implementation:** G/S's exact subtitle tile IDs (open `logo.tilemap`), the safest pre-LCD hook point, service-bank space, and SGB border overlap. All of these need a boot check on Gold/Silver/Crystal in DMG/SGB/CGB.
- **Owner questions:** who draws the logo; one row (fits natively) or two; the placeholder is a pixel "SLINK" wordmark. The design-only OMP cards also in flight: KEY-SCOPE-5 `cx-ee316c45`, SP-LOWWATER `cx-947d9423`, POISON-DUO-CAP `cx-2ea3c763`, BOARD-AMBIGUOUS `cx-8a2f08c6`, PURERGB-OVERLAY-EOL `cx-a84b761e`, TEMP-LANES `cx-1b2b86fe`.)
