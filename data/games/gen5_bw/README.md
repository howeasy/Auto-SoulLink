# Gen 5 Game Data (Black/White/B2W2)

Data files for Gen 5 Pokémon games (Nintendo DS).
Covers all four US variants: Pokémon Black, Pokémon White, Pokémon Black 2,
Pokémon White 2.

## Status

Feature parity with Gen 3 — enemy moves/PP, doubles detection, Unova
form normalization, Gen 4-5 move data, hidden abilities. Minimal BizHawk
RAM-Watch verification remains via `lua/tests/test_gen5_block_b.lua` and
`lua/tests/test_gen5_doubles.lua`.

## Files

- `area_map_bw.json` — Black/White zone ID → area_id mapping
- `area_map_bw2.json` — Black 2 / White 2 zone ID → area_id mapping
- `gen5_bw_areas.lua` — Generated zone lookup table (BW + BW2)
- `gen5_bw_locations.lua` — Area display name lookup
- `encounters_pokemon_black.json` / `..._white.json` / `..._black_2.json` / `..._white_2.json` — Per-variant wild encounter tables (area → method → entries)

## Sources

- [veekun/pokedex](https://github.com/veekun/pokedex) — Encounter + item + move tables (auto-extracted from CSVs)
- [PKHeX PK5.cs](https://github.com/kwsch/PKHeX) — Pokemon struct + Block A/B/C/D layout
- [NDS-Ironmon-Tracker BattleHandlerGen5](https://github.com/Brian0255/NDS-Ironmon-Tracker) — Battle-mode address + doubles detection
- Bulbapedia — Form-byte semantics (Deerling seasons, Kyurem forms, etc.)

## Notes

- Mon identity: `PID:OTID` (same as Gen 3/4).
- Shiny: same formula as Gen 3/4.
- Platform: Nintendo DS — melonDS or DeSmuME core in BizHawk.
- Memory map: similar to Gen 4 but with a slightly different Pokemon struct (220 bytes party vs Gen 4's 236).
- Encryption: identical Block A/B/C/D LCRNG shuffle to Gen 4 (PK4 and PK5 share the layout); the `decrypt_block_b` function in `lua/memory_nds.lua` serves both.
- Nicknames: UTF-16LE in Gen 5 (vs Gen 4's custom charcode table). Profile field `TRAINER_NAME_ENCODING = "gen5"` selects the codepath.
- `SPECIES_MAX = 649` (Genesect, last Gen V species).
- Memorial box: Box 24 (internal index 23).
