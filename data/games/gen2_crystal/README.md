# Gen 2 Game Data (Gold/Silver/Crystal)

Data files for Gen 2 Pokémon games (Game Boy Color).

## Status: Not Yet Implemented

## Required Data Files (when implemented)

- `area_map.json` — Route/city → area_id mapping
- `species.json` — 251 species names and IDs
- `evo_families.json` — Evolution family mappings
- `types.json` — Type data (17 types, Dark/Steel added)
- `gift_areas.json` — Gift/static encounter locations

## Notes

- Mon identity: DVs + OT ID. Shiny determined by DVs (Atk DV = 2/3/6/7/10/11/14/15, others = 10).
- Gender: Determined by Atk DV vs species threshold.
- Platform: Game Boy Color (Gambatte core in BizHawk).
- Memory map: Well-documented via pret/pokecrystal decomp.
