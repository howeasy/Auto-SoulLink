# Gen 4 Game Data (HGSS + Platinum)

Data files for Gen 4 Pokémon games (Nintendo DS).
Naming convention: `gen4_hgsspt` covers HeartGold, SoulSilver, and Platinum.

## Status: HGSS + Platinum Working

## Data Files

- `area_map_hgss.json` — HGSS zone ID → area_id mapping (98 area definitions, 195 zone ID mappings in Lua)
- `area_map_platinum.json` — Platinum zone ID → area_id mapping (78 area definitions, 530 zone ID mappings in Lua)

## Notes

- Mon identity: PID-only (OT ID encrypted in Block A, not extractable without decryption)
- Shiny detection: Disabled (PID-only key cannot determine shininess)
- Platform: Nintendo DS (melonDS or DeSmuME core in BizHawk)
- Party struct: 236 bytes (vs 100 in Gen 3), LCRNG encryption on battle stats
- PC storage: 18 boxes × 30 slots, BoxPokemon = 136 bytes
- Memorial box: Box 18 (internal index 17)
