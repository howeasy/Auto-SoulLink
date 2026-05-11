# Gen 5 Game Data (Black/White/B2W2)

Data files for Gen 5 Pokémon games (Nintendo DS).

## Status: Not Yet Implemented

## Required Data Files (when implemented)

- `area_map.json` — Route/city → area_id mapping
- `species.json` — 649 species names and IDs
- `evo_families.json` — Evolution family mappings
- `types.json` — Type data (17 types)
- `abilities.json` — Ability data
- `gift_areas.json` — Gift/static encounter locations

## Notes

- Mon identity: personality:otId (same as Gen 3/4).
- Shiny: Same formula as Gen 3/4.
- Platform: Nintendo DS (melonDS or DeSmuME core in BizHawk).
- Memory map: Similar to Gen 4 but with expanded Pokémon struct (220 bytes party).
- Encryption: Block shuffle + rolling XOR similar to Gen 4.
