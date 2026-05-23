# Gen 5 (Pokemon Black/White/BW2) — Status

**Status:** Fixes merged into master (see "Gen 1/2/4/5 bug fixes + slink_lua.log perf"). Live BizHawk validation still pending; pending-work items in sections D/E remain open.

Originally written as a worktree handoff (`claude/flamboyant-borg-a0cdb0`, 2026-05-20). The worktree is gone — treat this as a Gen 5 status snapshot. The "Critical files to know" table at the bottom is still the right map of where Gen 5 code lives.

---

## What has been fixed (on master)

### 1. PC boxes showed `????` for all slots → fixed
**Root cause:** `PC_BOX_STRIDE = 0xFA0` in [lua/games/gen5_bw.lua:132](lua/games/gen5_bw.lua:132) was a fabricated number; comment math was self-contradictory (`30 × 0x88 = 0xFF0`, not `0xFA0`). Per-box drift was −0x50, accumulating to −0x730 by box 23 — that's why only late boxes surfaced garbage PIDs (the slots happened to land in periodic non-PC RAM).
**Fix:** Changed to `0xFF0` (= 30 × 0x88, no padding — PKHeX `BoxLayout5BW.Box5BWBoxSize`). Updated `PC_CURRENT_BOX_OFF` to `0x17E80` (24 × 0xFF0). Comments corrected.
**Also kept:** Defensive filter in PC scan loops (gen5_bw_client.lua:1338, gen4_hgsspt_client.lua:1500) — skip slots where `decrypt_block_a_ext` returns nil. Safety net against transient mid-write decryption failure.

### 2. TCP connection close/reconnect loop → fixed
**Root cause:** `asyncio.start_server` uses default 64 KiB StreamReader buffer. Gen 5 PC payload (~110 KiB after first box scan completes) exceeded that, raising `LimitOverrunError`, which the `async for raw in reader:` loop swallowed as EOF → client reconnected → loop.
**Fix:** [server/server.py](server/server.py) — passed `limit=4 * 1024 * 1024` to `asyncio.start_server`, and replaced `async for raw in reader:` with explicit `await reader.readuntil(b"\n")` wrapped in try/except for `LimitOverrunError` so we log and skip oversize lines without dropping the connection.

### 3. Party nicknames rendered as `?????` (5 question marks) → fixed
**Root cause:** Lua scope hoisting bug. `local TRAINER_NAME_ENCODING = "gen4"` was declared at [memory_nds.lua:607](lua/memory_nds.lua:607), but `readNickname()` (defined at line 391) referenced it inside its body at line 403. Lua resolves forward references as globals → nil. `if TRAINER_NAME_ENCODING == "gen5"` was always false; code fell into the Gen-4 charset branch which emits `'?'` for every unmapped charcode. Gen-5 Unicode chars don't fall in 289–350 → exactly N question marks for an N-char name. "Snivy" → "?????".
**Identical pattern** to the `SPECIES_MAX` bug we hoisted earlier.
**Fix:** Hoisted `local TRAINER_NAME_ENCODING = "gen4"` to top of [lua/memory_nds.lua](lua/memory_nds.lua) (above `readNickname`), removed the duplicate declaration at the old position.

### 4. Pokemon types blank → fixed
**Root cause:** `_NATDEX_SPECIES_TYPES` in [server/pokemon_data.py:1592](server/pokemon_data.py:1592) only covered NatDex 1–386 (Gen I–III, sourced from pokefirered base_stats). Every Gen 4 (387–493) and Gen 5 (494–649) species returned `None` for `species_types()`.
**Fix:** Added 263 entries (387–649) sourced from pret/pokeheartgold + pret/pokeblack base_stats. Verified with sample lookups: Snivy → (12,12) Grass; Victini → (14,10) Psychic/Fire; Reshiram → (16,10) Dragon/Fire.
**Caveats baked into the data:**
- Togekiss (468): Normal/Flying (Gen 4–5 value; became Fairy/Flying in Gen 6+). Correct for BW.
- Cottonee (546)/Whimsicott (547): pure Grass (Gen 5 value; became Grass/Fairy in Gen 6+). Correct for BW.
- Wormadam (413): defaults to Plant cloak (Bug/Grass). Form variants would need override.
- Darmanitan (555): defaults to Standard form (Fire). Zen form (Fire/Psychic) would need override.
- Shaymin (492): defaults to Land form (Grass). Sky form (Grass/Flying) would need override.

### 5. Capture event missing `nickname` field → fixed
**Root cause:** [lua/clients/gen5_bw_client.lua](lua/clients/gen5_bw_client.lua) capture sends (battle + gift paths) and [lua/clients/gen4_hgsspt_client.lua](lua/clients/gen4_hgsspt_client.lua) likewise omitted `nickname=...`. Server-side `pending_captures[area][player].nickname` was always `""`, confirmed in run_20260520_213541/links.json. Gen 3 client did include it.
**Fix:** `index_party()` now reads + caches nickname per slot; capture-event sends include `nickname=info.nickname`. Parity with Gen 3.

---

## What is NOT a bug (don't waste cycles on these)

### "Nuzlocke Gate active at game start"
The events.json from run_20260520_213541 shows `pokeballs_obtained: {"a": true, "b": false}`. Player A's balls *are* being detected. The gate stays "active" because Player B hasn't connected / obtained balls — that's correct soul-link behaviour. User likely misread the UI. If user reports it again **after** Player B has balls, then it's a real bug; otherwise leave it alone.

---

## Verification status

- **Lua syntax (lupa 5.5):** all modified files parse OK.
- **Type lookup:** Gen 4 + Gen 5 species now resolve correctly via `species_types(to_cfru(natdex_id))`.
- **Unit tests:** `pytest tests/unit/ -q` → 1072/1072 pass.
- **Live BizHawk Gen 5 retest:** PENDING. User needs to restart the run and verify:
  - PC boxes display real Pokemon (or are correctly empty for a fresh save) — no ghost `????` rows.
  - Party nicknames show real names ("Snivy") instead of "?????".
  - Type chips show real types instead of blank.
  - Captures populate `pending_captures.nickname` immediately (not waiting for the next tick).

---

## Known-pending Gen 5 work (next session)

### A. Verify the `PC_STORAGE_BASE` candidate selection still works
We have two candidates for Black:
- `PC_STORAGE_BASE = 0x21BFAC` (primary — Wi-Fi-Labs RNG script)
- `PC_STORAGE_BASE_ALT = 0x21BFD0` (fallback — ProjectPokemon save spec)

`_gen5_pc_base_looks_valid()` in [memory_nds.lua:1321](lua/memory_nds.lua:1321) only rejects all-0xFFFFFFFF reads. An empty save (all-zeros) would accept the primary even if it's wrong. Once the user has actual Pokemon in their box, if they appear in the wrong box, we need a smarter probe — e.g. check whether the *current box number* read from `PC_CURRENT_BOX_OFF` falls in `[0, 23]`.

### B. Bag detection scope for Gen 5
[memory_nds.lua](lua/memory_nds.lua) hardcodes `M.BAG.BALLS_COUNT = 24`, but Gen 5's profile sets `BALLS_POCKET_COUNT = 50` (because Gen 5 has no separate balls pocket — balls are in the general Items pocket among ~310 slots, sorted by ID so balls 1–16 come first). The profile's `BALLS_POCKET_COUNT` *is* wired into `M.BAG.BALLS_COUNT` by `applyProfile` (see line 626–629), so scanning is actually 50 slots wide for Gen 5. **No fix needed**, but worth confirming with the user that ball detection works once they actually have balls.

### C. Gen 5 capture event still needs `hp`/`maxHP` if they're not in the snapshot's `info`
Verified `info.hp` and `info.maxHP` come from `M.battleHP(i) or M.partyHP(i)` in `index_party()`, so they're populated. No fix needed.

### D. Gen 4 doesn't launch — separate, blocking issue
Plan item #7 (`game_detect.lua:67`). Diagnostic prints were already added in the earlier session; user needs to reload SLink on the HGSS ROM and report what `emu.getsystemid()` returns. Until Gen 4 launches, the Gen 4 fixes I made (matching Gen 5 nickname-in-capture, defensive PC filter) are untested.

### E. Form-dependent type overrides
Server-side type lookup hits `_NATDEX_SPECIES_TYPES` by base NatDex ID. For form variants (Deerling seasons, Basculin colors, Darmanitan Zen, Tornadus/Thundurus/Landorus Therian, Kyurem White/Black, etc.) the client emits a CFRU form display ID (700+) and the server tries `CFRU_FORM_TYPES.get(species_id)` first. That table already covers the BW form variants. Verify with the user once they encounter a form mon.

---

## Critical files to know

| Area | File |
|---|---|
| Gen 5 game module / profile addresses | [lua/games/gen5_bw.lua](lua/games/gen5_bw.lua) |
| Gen 5 client (event loop, party scan, PC scan, capture) | [lua/clients/gen5_bw_client.lua](lua/clients/gen5_bw_client.lua) |
| NDS memory primitives (decryption, party/PC addresses) | [lua/memory_nds.lua](lua/memory_nds.lua) |
| Gen 5 server adapter (species, types, gender, gift areas) | [server/adapters/gen5_bw.py](server/adapters/gen5_bw.py) |
| Type tables + CFRU conversions | [server/pokemon_data.py](server/pokemon_data.py) |
| TCP frame reader + capture/tick event handlers | [server/server.py](server/server.py) |
| State machine, pending_captures, nuzlocke gating | [server/state.py](server/state.py) |
| Most recent test-run logs | [data/runs/run_20260520_213541/](data/runs/run_20260520_213541) |

---

## How to continue this work as another agent

The worktree referenced in the original handoff has been removed; everything is on `master` now. Work directly in `E:\Google Drive\SLink`. To pick up the pending items in section D/E, the entry points are the "Critical files to know" table above and the Gen 5 launchers (`lua/slink_gen5.lua` → `lua/clients/gen5_bw_client.lua`).
