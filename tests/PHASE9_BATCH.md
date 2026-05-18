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

*Filled in as Phase 1 lands.*

---

## Phase 2 — Stat stages

*Filled in as Phase 2 lands.*

---

## Phase 3 — Moves + PP

*Filled in as Phase 3 lands.*

---

## Phase 4 — Enemy moves + PP

*Filled in as Phase 4 lands.*

---

## Phase 5 — Trainer class + name

*Filled in as Phase 5 lands.*

---

## Phase 6 — Wild encounter tables

*Filled in as Phase 6 lands.*

---

## Phase 7 — Sound effects

*Filled in as Phase 7 lands.*

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
