# Gen 5 Game Data (Black/White/B2W2)

Data files for Gen 5 Pokémon games (Nintendo DS).

## Status: Implemented (Black, White, Black 2, White 2)

## Data Files

- `area_map_bw.json` — Black/White zone ID → area_id mapping
- `area_map_bw2.json` — Black 2/White 2 zone ID → area_id mapping
- `gen5_bw_areas.lua` — Generated zone lookup table (BW + BW2)
- `gen5_bw_locations.lua` — Area display name lookup

## Notes

- Mon identity: personality:otId (same as Gen 3/4).
- Shiny: Same formula as Gen 3/4.
- Platform: Nintendo DS (melonDS or DeSmuME core in BizHawk).
- Memory map: Similar to Gen 4 but with expanded Pokémon struct (220 bytes party).
- Encryption: Block shuffle + rolling XOR similar to Gen 4.
