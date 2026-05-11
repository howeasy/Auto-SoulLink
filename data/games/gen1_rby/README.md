# Gen 1 Game Data (Red/Blue/Yellow)

Data files for Gen 1 Pokémon games (Game Boy / Game Boy Color).

## Status: Implemented (Prototype)

## Data Files

- `gen1_rby_areas.lua` — Map ID → encounter area_id mapping (all three games share IDs)
- `gen1_rby_locations.lua` — Map ID → display name mapping

## Architecture Notes

- **Mon identity**: Composite key format `DDDD:TTTT:II` (DVs + OT ID + internal species index).
  Evolution changes the species byte → key changes → `key_change` event migrates it.
- **Shiny**: Not applicable in Gen 1 (no shiny mechanic).
- **Platform**: Game Boy — Gambatte core in BizHawk. Memory domain: "System Bus".
- **Memory map**: Based on pret/pokered decomp (verified addresses).
- **Variants**: Red/Blue share identical WRAM layout. Yellow is shifted ~1 byte.
- **Badges**: 8 badges tracked via bitfield at wObtainedBadges.
- **Quarantine**: box_mon/party_mon commands supported (deposit/retrieve via WRAM writes).
- **Memorialize**: Dead mons deposited to current active box (Gen 1 has 12 boxes × 20 mons).
- **Sprites**: Gen 1 Red/Blue transparent sprites from PokeAPI with pixelated rendering and crop.
