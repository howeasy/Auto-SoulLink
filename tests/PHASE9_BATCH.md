# Phase 9 — Consolidated user testing batch

This is the **single end-of-migration user testing session**. All coding phases (0–8) produce diagnostic Lua scripts but do not require user interaction until this point. Work through each section in order. Any failures get noted at the bottom and rolled into a Phase 9a/9b cleanup commit before the branch merges to master.

**Setup**
- BizHawk with Gambatte (GB/GBC) core for Gen 1/2 ROMs.
- BizHawk with mGBA core for Gen 3 regression check.
- SLink server running: `python -m server.server --host 127.0.0.1 --port 54321`.
- A second player (or yourself with two clients) may be required for soul-link partner events; if running solo, ignore partner-side checks.

**How to load a diagnostic Lua script in BizHawk**
1. Tools → Lua Console → Open Script…
2. Navigate to `lua/tests/<script>.lua`
3. The script prints to the Lua Console immediately. Use F-keys per the script's header comment.

---

## Phase 0 — Profile address audit (run FIRST per ROM)

**This is foundational.** If a profile address is wrong, every downstream feature test on top of it is unreliable. Run Phase 0 first for each ROM you have available.

### 0.1 Gen 1: Red

1. Load Pokemon Red US.gb (or any Gen 1 ROM).
2. Load `lua/tests/test_gen1_profile_audit.lua` in BizHawk Lua console.
3. **At boot screen** (before pressing A to load save): press **F1**. Capture the dump.
4. Continue past title screen, load save. **In overworld idle** (e.g. inside player's house or Pallet Town): press **F1**, **F2**, **F3**.
5. Find a wild battle (Route 1 grass with low-level Pokemon). **In wild battle** (after intro animation): press **F1**, **F2**, **F4**.
6. End the wild battle (run or KO). Walk to **Brock** (or any trainer): start trainer battle. **In trainer battle**: press **F1**, **F2**, **F4**.
7. Report values for: `battle_flag_addr` (profile=0xD057) vs `battle_flag_alt_D05A`. **The address that transitioned 0→1 on wild battle start AND 0→2 on trainer battle start is the correct one.**

**Expected output (overworld)**:
- `party_count_addr @ 0xD163 = 0..6`
- All `party_species_addr[*]` ≤ 190 or 0xFF
- `battle_flag_addr @ 0xD057` = 0 (or whichever is right)
- `map_id_addr @ 0xD35E` = small value (Pallet Town = 0x00)

**FAIL if**: any address has `⚠` plausibility warnings throughout the test; party_count > 6; species values are random bytes (>190 and not 0xFF).

### 0.2 Gen 1: Blue

Same as 0.1 but on Blue ROM. The profile is identical to Red, so the values should look the same. Confirm.

### 0.3 Gen 1: Yellow

Same flow but on Yellow. **Yellow uses different (-1 shifted) addresses** per `lua/games/gen1_rby.lua` lines 101-140. The audit script auto-detects Yellow and uses the right profile. Report whether all addresses still pass plausibility.

### 0.4 Gen 2: Crystal

1. Load Pokemon Crystal US.gbc.
2. Load `lua/tests/test_gen2_profile_audit.lua` in BizHawk.
3. **At boot screen**: press **F1**.
4. **In overworld** (New Bark Town starting point): press **F1**, **F3**, **F5**.
5. Walk to **Route 29 grass**, get into a wild battle (Pidgey/Sentret). **In wild battle**: press **F1**, **F4**, **F5**.
6. End wild battle. Walk to **Falkner's Gym in Violet City** (after Bug Catcher trainers on Route 31). Engage Falkner. **In trainer battle**: press **F1**, **F4**, **F5**.
7. **Visit Day-Care on Route 34** (after gym 2). Press **F1** — confirms map address reads.
8. Report values for the 4 TODO addresses: `enemy_count_addr (0xD280)`, `enemy_base_addr (0xD288)`, `enemy_species_list_addr (0xD281)`, `battle_flag_addr (0xD22D)`. **These transition meaningfully on battle entry; the correct profile values are confirmed when they hold sensible values in the right states.**

**FAIL if**: TODO addresses show 0xFF / random in battle; party_count > 6; party_struct offsets read wrong values (e.g. level > 100).

### 0.5 Report format

For each ROM section, report by pasting the Lua console output into the bottom of this file (under "Phase 0 results"). Specifically:
- Boot dump
- Overworld dump
- Wild battle dump
- Trainer battle dump
- Daycare dump (Crystal only)

Address fixes get rolled into a Phase 9a commit by Claude.

---

## Phase 1 — Gen 2 plumbing (no user-facing UI changes beyond labels)

### 1.1 Memorialize routing (Gen 1 AND Gen 2)

**What changed**: Both `lua/clients/gen1_rby_client.lua` and `lua/clients/gen2_crystal_client.lua` now call `M.depositMemorialMon(slot)` for the `memorialize` command instead of `M.depositPartyMon(slot)`. Dead pairs go to:
- Gen 1: Box 12 (CartRAM 0x75EA)
- Gen 2: Box 14 (CartRAM 0x79E0)

**Live verification**:
1. Load Red or Crystal in BizHawk.
2. Run the regular SLink client (`lua/clients/gen1_rby_client.lua` or `lua/clients/gen2_crystal_client.lua`).
3. Start a soul-linked run (catch a Pokemon, link with partner B).
4. Faint your linked mon → server fires `memorialize` for B's partner.
5. **Open the PC** and check: B's deceased mon should be in **Box 12 (Gen 1)** or **Box 14 (Gen 2)** — NOT the current active box.
6. The corresponding partner should also end up in the same memorial box on the other side.

**FAIL if**: dead mon appears in the active PC box instead of Box 12/14.

### 1.2 Egg-gift classification (Gen 2 only)

**What changed**: `lua/games/gen2_crystal.lua` now declares `is_egg_species = 0xFD`. `lua/memory_gb.lua` sets `result.is_egg = true` on any party/box slot whose species byte equals `0xFD`. `lua/clients/gen2_crystal_client.lua` forwards `is_egg` in capture events. `server/adapters/gen2_crystal.py` exposes `is_daycare_area("route_34") = True`, and Route 34 is removed from `_GIFT_AREAS` (it was previously misclassified as a gift area which made wild captures there false-positive gifts).

**Live verification**:

A. **Wild capture on Route 34 grass (Crystal)** — was broken before Phase 1, should now work like any normal route:
1. Walk to Route 34 grass with Pokéballs.
2. Catch a wild Pokemon (Rattata/Drowzee/etc).
3. The server should:
   - Activate the Pokéball gate (if not already active)
   - Queue a `box_mon` quarantine if partner B hasn't caught yet on Route 34
4. **FAIL** if the capture is treated as a gift (no quarantine, no Pokéball gate flip).

B. **Mystery Egg from Mr. Pokemon (Route 30, classified as gift)**:
1. Progress to the early-game Mr. Pokemon errand.
2. Accept the Mystery Egg (will become Togepi).
3. Walk back to Professor Elm's lab and continue until egg joins party.
4. When the egg appears in party (party scan fires `capture` event with `is_egg=true`):
   - Server should NOT activate Pokéball gate.
   - Server should NOT quarantine to box.
   - Egg should be classified as gift.
5. **FAIL** if egg gets quarantined or Pokéball gate flips.

C. **Daycare-bred egg on Route 34 (NOT a gift)**:
1. Deposit two compatible Pokemon at the Day-Care on Route 34.
2. Walk steps until the Day-Care Man has an egg ready.
3. Accept the egg.
4. When the egg joins party:
   - Server SHOULD activate Pokéball gate (if not yet active).
   - Server SHOULD queue `box_mon` quarantine.
5. **FAIL** if egg is misclassified as gift (would let user "free-equip" daycare eggs).

D. **Box pickup of an existing egg (sanity)**:
1. Move a daycare egg from party to PC box.
2. Move it back from box to party.
3. Confirm normal behavior (no spurious gift classification).

### 1.3 No live verification needed for force_whiteout

The handoff's claim that Gen 2 was missing `force_whiteout` was incorrect — neither Gen 1 nor Gen 2 has (or needs) a separate dispatcher case. Whiteout propagation is handled by the server sending individual `force_faint` commands per slot, which both gens already process correctly. No action taken in Phase 1.

---

## Phase 2 — Stat stages

### 2.1 Gen 1 stat stage live verification (R / B / Y)

**What changed**: Profile declares `player_stat_stages_addr` and `enemy_stat_stages_addr` for each variant. `lua/memory_gb.lua` exposes `M.readPlayerStatStages()` and `M.readEnemyStatStages()` which normalize Gen 1/2's 1..13 (neutral 7) encoding to the Gen 3 0..12 (neutral 6) convention. Gen 1's 6 stat-stage bytes (Atk/Def/Spd/Spc/Acc/Eva) are mapped to the 7-slot Gen 3 array by mirroring the unified Special stat into both SpA and SpD slots. Clients attach `stat_stages` to party slot 0 (assumed active) and to the active enemy battler when in battle.

**Verification (Red, then Blue, then Yellow)**:
1. Load `lua/tests/test_gen1_stat_stages.lua` in BizHawk.
2. Engage a wild Pokemon (Route 1 grass).
3. Wait for the battle intro to finish — at this point both player and enemy stat-stage bytes should read **7** (neutral).
4. Press F1 — confirm: all 12 bytes (6 player + 6 enemy) read 7, helper output looks like `{6, 6, 6, 6, 6, 6, 6}` (Gen 3 normalized neutral).
5. Use a stat-debuff move on the enemy: **Growl** (Atk -1) → enemy ATK byte should drop from 7 to 6. Press F1 to confirm.
6. Use **Sand Attack** → enemy ACC byte drops.
7. Force a stat-up move via Defense Curl or Withdraw → player DEF byte rises 7 → 8.
8. **FAIL** if values are 0x00 / 0xFF / random in idle battle state, or if Growl doesn't decrement the enemy ATK byte.

Repeat for Blue and Yellow. Yellow uses tentative -1 shifted addresses; F2 wide sweep can find the right addresses if the dump is out of range.

### 2.2 Gen 2 stat stage live verification (Crystal)

**What changed**: Same plumbing as Gen 1, with 7-byte stat-stage layout (Atk/Def/Spd/SAtk/SDef/Acc/Eva) per pret/pokecrystal `wPlayerStatLevels`/`wEnemyStatLevels`. Profile addresses are **tentative** (0xC68A / 0xC691 working hypothesis).

**Verification**:
1. Load `lua/tests/test_gen2_stat_stages.lua` in BizHawk on Crystal.
2. Engage a wild battle (Route 29 grass — Pidgey/Sentret).
3. Once the battle intro finishes, press F1.
4. **EXPECT**: 14 bytes (7 player + 7 enemy) all reading 7.
5. If F1 dump shows values outside 1..13, press **F2** to sweep WRAM0 looking for 14 consecutive bytes all in 1..13 range — that's the right address pair.
6. Use Growl, Tail Whip, Sand Attack, Defense Curl — verify each modifies the expected stat byte.
7. Report the correct addresses (if different from 0xC68A / 0xC691) so they can be fixed in the Phase 9a cleanup commit.

### 2.3 Status page rendering

After the addresses are confirmed (steps 2.1 / 2.2 above):
1. Run the regular SLink client (`lua/clients/gen1_rby_client.lua` or `lua/clients/gen2_crystal_client.lua`).
2. Open the status page at `http://localhost:8080/` and locate the party panel.
3. Engage a battle, apply Growl to the enemy → status page should show **−1 ATK** badge on the enemy.
4. Apply Sand Attack to enemy → **−1 ACC** badge.
5. Defense Curl on player → **+1 DEF** badge on the player's slot 0.

**FAIL** if badges don't appear despite the diagnostic script showing correct address values (renderer regression — investigate `server/server.py:_stat_stages_html`).

---

## Phase 3 — Moves + PP

### 3.1 Move data files

**What changed**: `data/games/gen1_rby/moves.json` (165 entries) and `data/games/gen2_crystal/moves.json` (251 entries) added. Both adapters now expose `move_name(move_id)` and `move_data(move_id)` returning `{name, type_id, type_name, power, accuracy, pp, split}` (Gen 2 also includes `effect_chance`). The split is type-based (Gen 1/2 convention) but power-0 moves are forced to Status.

Regenerate from pret tables: `python tools/gen_moves_data.py`.

### 3.2 Profile + Lua plumbing

`lua/games/gen1_rby.lua` declares `moves_offset=0x08`, `pp_offset=0x1D`, `pp_encoding="raw"`. `lua/games/gen2_crystal.lua` declares `moves_offset=0x02`, `pp_offset=0x17`, `pp_encoding="ppup_packed"` (top 2 bits of each PP byte = PP-Up count, bottom 6 = current PP). `M.readMovesAndPP(base, nil)` in `lua/memory_gb.lua` reads + decodes both formats.

Both clients' `build_party_snapshot` attach `moves[]`, `pp[]`, and `pp_bonuses` to each party slot. The server's existing `_enrich_party` resolves move IDs to full move details and the status page renders them.

### 3.3 Live verification (Gen 1)

1. Load `lua/tests/test_gen1_moves.lua` on Red, Blue, or Yellow.
2. Press **F1** in overworld. Expect slot 0's moves to be valid IDs (1..165) for the moves your starter knows, and `0` for empty slots. PP values should be in 5..40 range.
3. Use a move in battle, return to overworld, press F1. The PP of that move should have decremented.
4. Use a Heal Item / Pokémon Center → PP refilled to base.
5. **FAIL** if move IDs are random (>165), or if PP values are unreasonable (>40 / random bytes).

### 3.4 Live verification (Gen 2)

1. Load `lua/tests/test_gen2_moves.lua` on Crystal.
2. Press **F1**. Expect slot 0 moves valid (1..251), `pp_ups` typically 0, PP in 0..63 (decoded from packed byte).
3. **Use a PP-Up on one move**, then press F1 + F3. `pp_ups` for that move should increment to 1 and max PP should grow accordingly.
4. **F3 raw dump**: Verify the raw PP byte = `(pp_ups << 6) | current_pp`. E.g. if a move with base PP 35 has 1 PP Up applied (pp_ups=1) and you've used it down to 30, the raw byte should be `(1 << 6) | 30 = 0x5E = 94`.
5. **FAIL** if move IDs are out of range, or if PP encoding decodes wrong (max PP doesn't match base+ups formula).

### 3.5 Status page rendering

1. Run the regular SLink client. Open `http://localhost:8080/`.
2. The party panel should now show a clickable **Moves(N)** badge on each slot.
3. Expand it — each move should display **name (PP cur/max)** with a colored PP bar.
4. **FAIL** if Moves(N) doesn't appear (server enrichment broken) or shows ID numbers instead of names (move_data lookup broken).

---

## Phase 4 — Enemy moves + PP

**What changed**: Profile declares `enemy_battle_moves_addr` and `enemy_battle_pp_addr` per variant (absolute addresses into the wEnemyMon battle struct). `M.readEnemyBattleMovesAndPP()` returns `{moves[], pp[], pp_bonuses=0}`. Both clients' `build_enemy_snapshot` attach these to the active enemy entry. Renderer's `_enrich_battle_state` resolves into `move_details`.

**Verification**:
1. Load `lua/tests/test_gen{1,2}_enemy_moves.lua` per gen.
2. Enter a wild battle. Press **F1** once the battle screen is visible.
3. Expect 1-4 valid move IDs (Gen 1: 1..165; Gen 2: 1..251) and reasonable PP values.
4. Watch the enemy use a move → PP decrements. Press F1 again to confirm.
5. **FAIL** if all 4 move IDs are 0, or if IDs exceed valid range, or if PP doesn't decrement after enemy attacks.

**Status page check**: with the regular client running, the enemy display panel during battle should show a Moves(N) badge expanding to the same moves shown by the diagnostic.

---

## Phase 5 — Trainer class + name

**What changed**:
- Profile addresses `trainer_class_addr` and `trainer_id_addr` per gen.
- `lua/games/gen{1_rby,2_crystal}_trainers.lua` — class-name + named-trainer lookup tables matching `data/games/gen*/trainers.json` (covers gym leaders + elite four + named special trainers).
- Both clients' tick/hello events emit `trainer_class_id`, `trainer_id`, plus resolved `opponent_class`/`opponent_name` when in a trainer battle.
- `server/server.py` battle-state handler widened to accept `opponent_class` from the message (previously only accepted `opponent_name`). The change only fires when `adapter.trainer_info()` returns empty — Gen 3 path is unchanged.

**Verification**:
1. Load `lua/tests/test_gen{1,2}_trainer_info.lua` per gen.
2. Engage a known trainer:
   - Gen 1: Fight Brock (Pewter Gym). Press F1 mid-battle. Expect `class_id=233`, `class='Leader'`, `name='Brock'`.
   - Gen 1: Fight a generic Bug Catcher (Route 25). Expect `class_id=202`, `class='Bug Catcher'`, `name=''`.
   - Gen 2: Fight Falkner (Violet Gym). Expect `class_id=1`, `class='Leader'`, `name='Falkner'`.
   - Gen 2: Fight a generic Youngster. Expect `class_id=22`, `class='Youngster'`, `name=''`.
3. **FAIL** if class_id is out of expected range (Gen 1: 200..246; Gen 2: 0..67) — wrong profile address.

**Status page check**: run the regular client. During a trainer battle, the status page enemy panel header should show "Leader Brock" or "Bug Catcher" etc. Generic trainers show the class only; named trainers show class + name.

---

## Phase 6 — Wild encounter tables

**What changed**:
- `data/games/gen{1_rby,2_crystal}/encounter_tables.json` — encounter data per area, keyed by method (Grass/Water for Gen 1; Morn/Day/Nite/Surf/... for Gen 2). Initial coverage is partial (early-game routes); the schema supports incremental expansion.
- Both adapters implement `encounter_table(area_id)` returning the per-method entries.
- The stream overlay `/stream/enc-table-{a,b}` already calls `adapter.encounter_table()` and is gen-agnostic — no overlay changes required.

**Verification**:
1. Run the regular SLink client + server.
2. Open `http://localhost:8080/stream/enc-table-a` (or -b) in a browser.
3. Walk player A's tracker into a covered area:
   - Gen 1: Route 1, Route 2, Viridian Forest, Mt. Moon 1F, etc.
   - Gen 2: Route 29, Route 30, Route 31, Sprout Tower, Union Cave.
4. The overlay should show the species/rates/levels for that area.
5. For uncovered areas, overlay shows blank — that's expected.
6. **FAIL** if overlay shows blank on a covered route (encounter JSON didn't load or area_id mismatch).

**Coverage expansion**: edit the relevant `encounter_tables.json` file to add more areas. The adapter loads on import — restart server to pick up changes.

---

## Phase 7 — Sound effects (infrastructure only — addresses TBD live)

**What changed**: `lua/memory_gb.lua` exposes `M.playSfx(event_name)` and `M.playSfxRaw(sfx_id)` helpers. Profiles can declare `sfx_dispatch_addr` (the ROM register that triggers a sound when written) and `sfx_ids` (event_name → ROM SFX constant). Both clients call `M.playSfx("capture")`, `M.playSfx("faint")`, etc. at appropriate event points — but `sfx_dispatch_addr` is **nil by default** in both profiles, making the calls **no-ops** until the user verifies dispatch via diagnostic and enables them.

**Why disabled by default**: Writing to a wrong dispatch register can corrupt music state or other RAM. The diagnostic scripts let the user safely probe candidate addresses + SFX IDs before turning auto-play on.

**Verification protocol**:

1. Load `lua/tests/test_gen{1,2}_sfx.lua` in BizHawk.
2. In overworld (preferably a quiet area with music paused or muted), press F1-F4 to write candidate SFX IDs to candidate dispatch addresses.
3. Listen for audible sound effects. Note which key+address combination triggered the expected sound (capture chime, faint thump, level-up jingle).
4. Once identified, edit the profile to populate `sfx_dispatch_addr` and `sfx_ids = {capture=..., faint=..., whiteout=..., gift=...}`.
5. Restart the regular SLink client. From now on, in-game SFX should auto-play on capture/faint/whiteout events.

**If no F-key combination triggers a sound**: the dispatch protocol in pret/pokered or pret/pokecrystal is more complex than a single-byte write (likely involves writing to multiple registers in sequence). Phase 7 then stays disabled; document findings and leave it as future work.

**FAIL only if**: enabling the profile addresses causes BizHawk audio glitches / silent music / crashes during normal play. Revert the profile change if so.

---

## Phase 8 — Archipelago variant detection

*Filled in as Phase 8 lands.*

---

## Regression spot-check (run LAST)

Load Pokemon FireRed (vanilla or RR). Start a new game, walk 10 paces, check overlays look identical to pre-migration baseline. **No Gen 3 code was changed — this is just a sanity check that no shared-file changes broke anything.**

---

## Phase 0 results

*(User pastes Lua console outputs here during testing)*

### Gen 1 Red
*(placeholder)*

### Gen 1 Blue
*(placeholder)*

### Gen 1 Yellow
*(placeholder)*

### Gen 2 Crystal
*(placeholder)*

## Phase 0 actionable corrections

*(After user reports results, Claude lists profile corrections here, then makes them in a single Phase 9a commit before re-testing features.)*
