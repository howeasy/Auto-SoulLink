# Gen 2 Game Data (Gold/Silver/Crystal)

Data files for Gen 2 Pokémon games (Game Boy / Game Boy Color).
The directory name reflects Crystal as the reference profile; Gold and Silver
ship as variant profiles using pret/pokegold addresses.

## Status

Feature-parity with Gen 3 — Crystal, Gold, and Silver supported. Every
profile address verified by [tools/verify_profile_addresses.py](../../../tools/verify_profile_addresses.py)
against the pret decomp .sym output. Runtime smoke-test checklist in
[docs/gen1_gen2_runtime_checks.md](../../../docs/gen1_gen2_runtime_checks.md).

## Files

- `area_map.json` — Route/city → area_id mapping (124 entries)
- `species_types.json` — Species type data (251 species)
- `gender_ratios.json` — Species gender ratio data
- `item_names.json` — Item ID → name mapping
- `moves.json` — 251 moves: name, type, power, accuracy, pp, split, effect_chance
- `trainers.json` — `classes` (class_id → class name) + `named_trainers` (Johto/Kanto leaders, E4, rivals)
- `encounter_tables.json` — Wild encounter slots by area_id with Morn/Day/Nite variants (partial coverage; extend by adding more areas)

## Sources

- [pret/pokecrystal](https://github.com/pret/pokecrystal) — Crystal decompilation
- [pret/pokegold](https://github.com/pret/pokegold) — Gold/Silver decompilation
- Archipelago: gerbiljames fork (auto-detected via seed signature)

## Notes

- Mon identity: composite key `DDDD:TTTT:SS` (DVs + OT ID + species byte).
- Shiny: derived from DVs (Atk DV in {2,3,6,7,10,11,14,15}, others = 10).
- Gender: Atk DV vs species threshold.
- Platform: Game Boy Color — Gambatte core in BizHawk.
- Memorial box: Box 14 (Crystal's dedicated graveyard box at SRAM offset 0x79E0).
- Eggs: species byte `0xFD` (constant `EGG` in pret). The Mystery Egg from Mr. Pokémon is treated as a gift; daycare-bred / Odd Eggs from the Day-Care Man on Route 34 follow the normal capture flow (Pokéball required, quarantine until linked).
