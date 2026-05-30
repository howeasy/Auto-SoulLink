# Gen 4 Game Data (HGSS + Platinum + Renegade Platinum)

Data files for Gen 4 Pokémon games (Nintendo DS).
Naming convention: `gen4_hgsspt` covers HeartGold, SoulSilver, and Platinum;
Renegade Platinum (Drayano60's difficulty hack on Platinum) inherits the
Platinum profile with overrides for the extended dex.

## Status

⚠️ **Experimental** — feature parity with Gen 3, but limited live-play
coverage. Live battle-struct addresses for doubles + stat stages are
read-only-scannable via `lua/tests/test_gen4_battlers_count.lua` and
`test_gen4_stat_stages.lua`; populate the profile from a one-time live capture.

## Files

- `area_map_hgss.json` — HGSS zone ID → area_id mapping (101 areas, 532 map entries)
- `area_map_platinum.json` — Platinum zone ID → area_id mapping (78 areas, 530 zone IDs)
- `gen4_hgsspt_areas.lua` / `gen4_hgsspt_areas_pt.lua` — Generated zone lookup tables (Lua, runtime)
- `gen4_hgsspt_locations.lua` / `gen4_hgsspt_locations_pt.lua` — Area display name lookups
- `encounters_hgss.json` / `encounters_pt.json` — Wild encounter tables (area → method → entries)
- `trainers_hgss.json` / `trainers_pt.json` — `classes` + `trainers` dicts for story/gym/E4/champion entries
- `PRET_CITATIONS.md` — Per-address citations into pret/pokeheartgold + pret/pokeplatinum

## Sources

- [pret/pokeheartgold](https://github.com/pret/pokeheartgold) — HGSS decompilation
- [pret/pokeplatinum](https://github.com/pret/pokeplatinum) — Platinum decompilation
- [NDS-Ironmon-Tracker](https://github.com/Brian0255/NDS-Ironmon-Tracker) — Live RAM addresses (cross-referenced)
- [PKHeX PK4.cs](https://github.com/kwsch/PKHeX) — Pokemon struct + Block A/B/C/D decryption

## Notes

- Mon identity: `PID:OTID`. Same shiny formula as Gen 3.
- Platform: Nintendo DS — melonDS or DeSmuME core in BizHawk.
- Party struct: 236 bytes (vs 100 in Gen 3), LCRNG block decryption.
- PC storage: 18 boxes × 30 slots, BoxPokemon = 136 bytes. Memorial box: Box 18 (internal index 17).
- Platinum and HGSS share the SaveData arrayHeaders layout but Platinum offsets `dynamic_region` by +0x14 (vs HGSS's +0x10) — verified in commit `6c7867b`.
- Renegade Platinum: detected via ROM banner ("RENEGADE" / "Drayano") + filename hint. Inherits Platinum's full profile with `SPECIES_MAX` raised to 1025 to cover cross-gen mons.
