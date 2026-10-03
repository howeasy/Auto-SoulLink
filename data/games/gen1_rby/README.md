# Gen 1 Game Data (Red/Blue/Yellow)

Data files for Gen 1 Pokémon games (Game Boy / Game Boy Color).

## Status

🟡 **Partially verified.** The mechanisms are proven against running cartridges; a playthrough
is not. Every profile address is checked against the pret decomp .sym output by
`tests/unit/test_gen1_profile.py`, and on top of
that:

```bash
SLINK_LIVE=1 pytest tests/live/test_gen1_gates.py -q   # 11: companion-patch (3) + SFX matrix (4) + menu row (3) + randomized panel (1)
SLINK_E2E=1 pytest tests/e2e/test_duo_gen1_new.py -q   # 20 gen1_new scenarios, Red (A) vs Blue (B)
python tools/verify_gen1_release.py                    # all of the above, fail-closed
```

The duo E2E runs one pairing — **Red as player A, Blue as player B** (no Yellow pairing) —
over the 20 scenarios in `SCENARIOS` (`tests/e2e/test_duo_gen1_new.py`), each implemented as
a `scenarios.<name>()` function in `lua/tests/duo/duo_gen1_main.lua` (see
[lua/tests/README.md](../../../lua/tests/README.md)). Fixtures are battery saves
(`tests/fixtures/gen1/*.SaveRAM`) built from a cold boot by
[tools/gen1_playthrough.py](../../../tools/gen1_playthrough.py); unlike the Gen 3 `.State` files
they are not BizHawk-version-locked, so they never go stale.

**What IS covered live.** `link_new`, `deadzone_new`, `type_clause_new`, `species_clause_new`,
`poison_new` and `whiteout_new` play for real: both cartridges walk Route 1's grass, meet real
wild Pokemon, throw real Poke Balls, and the server pairs the captures by area (docs/gen1_requirements.md
D-1/D-3). That covers encounter linking, the dead zone and the species/type clauses with no
injection at all. Most of the remaining scenarios inject the state they verify, which is the
point — they isolate one rule each. (The old `playthrough`/`dupes` scenario names this section
used to cite were retired with the pre-rewrite client; the `_new`-suffixed names above are their
replacements.)

**What that does NOT cover.** Route 1 is the only encounter area any live test visits: the
scripted warp turned out to be undrivable from Lua (`hWarpDestinationMap` at `$FF81` is
shared HRAM the renderer overwrites within the frame, measured three ways before the probe was
retired), and the fly warp reaches thirteen destinations of which only two carry wild
encounters. So the remaining areas are covered by the source-derived oracle and the ROM
scanner, not by play. Fishing is scanned from ROM on all three titles but no rod has ever
been used in-engine.
`retrieveBoxMon` (the withdraw half of party sync) has never run on a cartridge, and the
Archipelago variants have never been launched. See
[docs/gen1_gen2_runtime_checks.md](../../../docs/gen1_gen2_runtime_checks.md).

## Files

- `area_map.json` — Map ID → `{area_id, display name}` source (86 entries; all three games share IDs). Read directly by the new client's closure (`lua/gen1/entry.lua`); no longer generates standalone `.lua` lookup tables (those, and their `gen_gen1_area_map.py` generator, were retired with the legacy client in P8-4b).
- `map_names.json` — Map ID → name for every map (226; the unused ids left out), from pret's `constants/map_constants.asm` by `python tools/gen_gen1_map_names.py`. The board names a map that is no encounter area with it (the client reports those as `map_<id>`): Viridian City, a gym, a house — not "Map 1".
- `moves.json` — 165 moves: name, type, power, accuracy, pp, split
- `trainers.json` — `classes` (class_id → class name) + `named_trainers` (gym leaders, E4, rivals)
- `encounter_tables.json` — Wild encounter slots, keyed **by game version first**
  (`red` / `blue` / `yellow`), then by area_id. 39 areas each. Red and Blue differ in 25 of
  those areas and Yellow differs from Red in 36, so they cannot share one table — the
  generator honours pokered's `IF DEF(_RED)` / `IF DEF(_BLUE)` blocks and reads Yellow from
  pokeyellow. Regenerate with `python tools/gen_gen1_encounters.py`, which refuses to write
  unless every method block sums to 100% with no zero-rate species.
- `species_index.json` — Internal species index ↔ National dex map
- `profile.json` — Per-title (red/blue/yellow) RAM/ROM symbol table (`gen1-profile-v1`) sourced
  from pret's `.sym` files. Regenerate with `python tools/gen_gen1_profile.py`; checked against
  the pinned decomp by `tests/unit/test_gen1_profile.py`.
- `evolutions.json` — Species evolution edges, from pret's `data/pokemon/evos_moves.asm`.
  Regenerate with `python tools/gen_gen1_evos.py`.
- `gifts.json` — Narrative (non-static) gifts and starters. Regenerate with
  `python tools/gen_gen1_gifts.py`.
- `static_encounters.json` — Map ID → species list for static encounters (`gen1-statics-v1`).
  Regenerate with `python tools/gen_gen1_statics.py`.
- `floor_labels.json` — Map ID → floor suffix for multi-floor buildings; written as a side
  effect of `python tools/gen_gen1_encounters.py` (same command as `encounter_tables.json`).
- `calc_names.json` — Display-name → damage-calc (`calc/`) name overrides for Gen 1, inherited
  by pureRGB. Applied by `Gen1Adapter.calc_name()` (`server/adapters/gen1_rby.py`).
- `engine_signals.json`, `continue_sites.json`, `wild_encounter_sites.json` — bus-exec hook-site
  tables (`rby-engine-signal-sites-v1`, `rby-continue-sites-v1`, `rby-wild-encounter-sites-v1`)
  that `lua/gen1/signals.lua` arms. These came from the `gen1/rc` research worktree rather than
  a generator in this repo's `tools/`; they are re-verified (byte-for-byte against the clean
  ROMs, and cross-checked against `profile.json`) rather than trusted, by
  `tests/unit/test_gen1_engine_sites.py`. See [docs/gen1_engine_sites.md](../../../docs/gen1_engine_sites.md).
- `write_checkpoint.json` — The overworld write-safety checkpoint (DelayFrame halt PC/SP shape)
  consumed by `lua/gen1_write_safety.lua`. Hand-pinned, not regenerated by any tool in this repo
  (`tools/gen_gen1_write_checkpoint.py` only covers the pureRGB counterpart); also
  cross-checked by `tests/unit/test_gen1_engine_sites.py`.

## Sources

- [pret/pokered](https://github.com/pret/pokered) — Red/Blue decompilation
- [pret/pokeyellow](https://github.com/pret/pokeyellow) — Yellow decompilation
- Archipelago: [Alchav's pokered fork](https://github.com/Alchav/pokered) (branch
  `pokemon-archipelago`) for Red/Blue; no Yellow AP world upstream. Detected by decoding the
  seed name at **ROM offset `0x5F22`** (`Title_Seed`) from the flat `ROM` domain — it is in
  bank 1, so a System Bus read would return whichever bank is mapped. Detection tests
  "does this decode as Gen 1 text", never a specific string: the shipped basepatch holds the
  placeholder `(NOT RANDOMIZED)` and a generated multiworld overwrites it with the real seed.
  **AP relocates WRAM.** The fork adds ~121 lines of tracking variables, moving 861 of the
  2171 symbols shared with vanilla — `wCurMap` +216, `wEnemyMons` −18, the PC box block +11.
  `M.PROFILES.red_ap` therefore overrides 11 addresses and inherits the rest; those overrides
  are verified against the `alchav_pokered` entry in `data/pret_syms.json`.

## Notes

- Mon identity: composite key `DDDD:TTTT:II` (DVs + OT ID + internal species index). Evolution changes the species byte → key changes → `key_change` event migrates it.
- Shiny: not applicable (no shiny mechanic in Gen 1).
- Platform: Game Boy — Gambatte core in BizHawk. Memory domain: "System Bus".
- Variants: `red` / `blue` / `yellow` (vanilla), `red_ap` / `blue_ap` (Archipelago).
- Stat stages: Atk/Def/Spd/Spc/Acc/Eva (6 bytes; Special is unified in Gen 1). Client normalizes Gen 1's 1..13 (neutral 7) encoding to Gen 3's 0..12 (neutral 6) so the existing renderer works as-is. Special mirrors into both SAtk and SDef slots for display.
- Moves: 4 move IDs at party_struct +0x08; 4 PP bytes at +0x1D. PP is **packed**, not raw:
  pret/pokered defines `PP_UP_MASK %11000000` / `PP_MASK %00111111`, so the low 6 bits are
  current PP and the top 2 are the PP-Up count — same encoding as Gen 2 (`pp_encoding = "ppup_packed"`).
- Badges: 8 badges tracked via bitfield at wObtainedBadges.
- Memorial box: Box 12 (`lua/gen1/boxes.lua`). **`ChangeBox` empties every SRAM box the first
  time the player opens the box menu** (`bit BIT_HAS_CHANGED_BOXES` / `call z,
  EmptyAllSRAMBoxes`, save.asm:366), which would erase the memorial if SLink wrote into an
  uninitialised bank. The rewritten client does not pre-run that init itself (the pre-rewrite
  client's `M.protectSramBoxes()` did; it and `memory_gb.lua`'s Gen 1 helpers were removed in
  `9969845`) — instead `lua/gen1/boxes.lua` refuses to write an SRAM box until the game's own
  `ChangeBox` has initialised it, logging "saved boxes not initialized" rather than writing.
  Box-bank checksums are recomputed for consistency, but vanilla never reads them.
- Sound: **requires the companion patch** (required for Red/Blue; Yellow and AP are exempt and
  have none, so they are silent). Gen 1 has no RAM-writable sound trigger — `wNewSoundID` is
  `PlaySound`'s internal scratch, not a polled mailbox — so the client posts a semantic code
  (1 success, 2 failure, 3 boo, 4 notify) at mailbox `+7` and the patch's `SlinkSfxService`
  (`patch/gen1/src/slink.asm`, capability `SLINK_CAP_SFX`) plays it on the main thread,
  resolving the id against the audio bank loaded at play time. The client requests it only when
  the panel reports the capability and the run's `native_sounds` toggle is on
  (`request_sfx_local` in `lua/gen1/client.lua`, `panel:sfx_present()`).
- **Rival Team Swap and Explode Mode need no ROM patch.** Gen 3 required the companion
  patch for the swap because `gEnemyParty` is encrypted and checksummed; Gen 1's enemy party
  is plaintext at a fixed address, so the rewritten client's `self:replace_rival_team`
  (`lua/gen1/client.lua:781`) is a byte copy over
  `wEnemyPartyCount` (`0xD89C`) → species list → `wEnemyMons` → `wEnemyMonOT` → `wEnemyMonNicks`,
  a contiguous 0x194-byte block. Rivals are identified by CLASS: RIVAL1/2/3 = `$19`/`$2A`/`$2B`
  + `OPP_ID_OFFSET(200)` = **225 / 242 / 243**, read from `wCurOpponent`.
  Per `LoadEnemyMonData`, a trainer mon takes species, HP, status, moves and level from the
  structs we write, but its **stats and DVs are recomputed with fixed trainer DVs** — so a
  swapped team fights at the partner's levels with their moves and HP, not as byte-perfect
  clones. Explode Mode writes Explosion (move 153) into the active battler's move slot 0 and
  `wPlayerSelectedMove`; the active slot comes from `wPlayerMonNumber` (`0xCC2F`), never
  assumed to be slot 0.
  Timing of both writes was derived from pret source and then measured on hardware by the
  rivalswap/explode probes (retired in Phase 8): the swap must land **before the first
  send-out** (`LoadEnemyMonData` re-derives the active mon from the party arrays), so the
  client writes on `trainer_battle_start`, gated on three stable frames of `wIsInBattle == 2`.
  Both are exercised end-to-end by the `rivalswap` and `explode_g1` duo scenarios.
- Sprites: Gen 1 Red/Blue transparent sprites from PokeAPI with pixelated rendering and edge crop.
