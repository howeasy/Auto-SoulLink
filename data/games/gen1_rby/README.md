# Gen 1 Game Data (Red/Blue/Yellow)

Data files for Gen 1 Pokémon games (Game Boy / Game Boy Color).

## Status

⚠️ **Experimental** — feature parity with Gen 3 (Red, Blue, Yellow), but
limited live-play coverage. Every profile address verified by
[tools/verify_profile_addresses.py](../../../tools/verify_profile_addresses.py)
against the pret decomp .sym output. Runtime smoke-test checklist in
[docs/gen1_gen2_runtime_checks.md](../../../docs/gen1_gen2_runtime_checks.md).

## Files

- `gen1_rby_areas.lua` — Map ID → encounter area_id mapping (all three games share IDs)
- `gen1_rby_locations.lua` — Map ID → display name mapping
- `moves.json` — 165 moves: name, type, power, accuracy, pp, split
- `trainers.json` — `classes` (class_id → class name) + `named_trainers` (gym leaders, E4, rivals)
- `encounter_tables.json` — Wild encounter slots by area_id (partial coverage; extend by adding more areas)
- `species_index.json` — Internal species index ↔ National dex map

## Sources

- [pret/pokered](https://github.com/pret/pokered) — Red/Blue decompilation
- [pret/pokeyellow](https://github.com/pret/pokeyellow) — Yellow decompilation
- Archipelago: Alchav fork for Red/Blue (auto-detected via seed-name at 0xFFDB; no Yellow AP world upstream)

## Notes

- Mon identity: composite key `DDDD:TTTT:II` (DVs + OT ID + internal species index). Evolution changes the species byte → key changes → `key_change` event migrates it.
- Shiny: not applicable (no shiny mechanic in Gen 1).
- Platform: Game Boy — Gambatte core in BizHawk. Memory domain: "System Bus".
- Variants: `red` / `blue` / `yellow` (vanilla), `red_ap` / `blue_ap` (Archipelago).
- Stat stages: Atk/Def/Spd/Spc/Acc/Eva (6 bytes; Special is unified in Gen 1). Client normalizes Gen 1's 1..13 (neutral 7) encoding to Gen 3's 0..12 (neutral 6) so the existing renderer works as-is. Special mirrors into both SAtk and SDef slots for display.
- Moves: 4 move IDs at party_struct +0x08; 4 raw PP bytes at +0x1D (no PP-Up encoding in Gen 1).
- Badges: 8 badges tracked via bitfield at wObtainedBadges.
- Memorial box: Box 12 (via `M.depositMemorialMon`; falls back to `depositPartyMon` if Box 12 is full).
- Sprites: Gen 1 Red/Blue transparent sprites from PokeAPI with pixelated rendering and edge crop.
