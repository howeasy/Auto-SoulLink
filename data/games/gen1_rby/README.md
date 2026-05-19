# Gen 1 Game Data (Red/Blue/Yellow)

Data files for Gen 1 Pokémon games (Game Boy / Game Boy Color).

## Status: Feature-parity with Gen 3 (pending Phase 9 live verification)

The gen1-gen2-parity branch brought R/B/Y up to Gen 3's tracker feature set:
moves+PP from party, stat stages in battle, enemy moves+PP, trainer class
+ named gym leaders/E4/rivals, partial wild encounter tables, sound-effect
infrastructure, and Archipelago Red/Blue variant detection. All addresses
are flagged for live BizHawk verification in `docs/gen1_gen2_runtime_checks.md`.

## Data Files

- `gen1_rby_areas.lua` — Map ID → encounter area_id mapping (all three games share IDs)
- `gen1_rby_locations.lua` — Map ID → display name mapping
- `moves.json` — 165 moves: name, type, power, accuracy, pp, split (Phase 3)
- `trainers.json` — class_id → class_name + named gym leaders / E4 / rivals (Phase 5)
- `encounter_tables.json` — wild encounter slots by area_id (Phase 6; partial coverage — extend by adding more areas)

## Architecture Notes

- **Mon identity**: Composite key format `DDDD:TTTT:II` (DVs + OT ID + internal species index).
  Evolution changes the species byte → key changes → `key_change` event migrates it.
- **Shiny**: Not applicable in Gen 1 (no shiny mechanic).
- **Platform**: Game Boy — Gambatte core in BizHawk. Memory domain: "System Bus".
- **Memory map**: Based on pret/pokered decomp + DataCrystal cross-references. Addresses are pre-verification tentative until Phase 9 audit runs.
- **Variants**: `red` / `blue` / `yellow` (vanilla) + `red_ap` / `blue_ap` (Archipelago by Alchav, auto-detected via seed-name at 0xFFDB). Yellow has no upstream AP world.
- **Stat stages**: Atk/Def/Spd/Spc/Acc/Eva (6 bytes in Gen 1, Special is unified). Client normalizes Gen 1's 1..13 (neutral 7) encoding to Gen 3's 0..12 (neutral 6) so the existing renderer Just Works. Special is mirrored into both SAtk and SDef slots.
- **Moves**: 4 move IDs at party_struct +0x08; 4 raw PP bytes at +0x1D (no PP-Up encoding in Gen 1).
- **Badges**: 8 badges tracked via bitfield at wObtainedBadges.
- **Memorialize**: Dead mons go to **Box 12** (memorial box) via `M.depositMemorialMon`. Falls back to `depositPartyMon` if box 12 is full.
- **Sprites**: Gen 1 Red/Blue transparent sprites from PokeAPI with pixelated rendering and crop.
