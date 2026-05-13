# Gen 2 Game Data (Gold/Silver/Crystal)

Data files for Gen 2 Pokémon games (Game Boy Color).

## Status: Implemented (Crystal)

## Data Files

- `area_map.json` — Route/city → area_id mapping (124 entries)
- `species_types.json` — Species type data (251 species)
- `gender_ratios.json` — Species gender ratio data
- `item_names.json` — Item ID → name mapping

## Notes

- Mon identity: DVs + OT ID. Shiny determined by DVs (Atk DV = 2/3/6/7/10/11/14/15, others = 10).
- Gender: Determined by Atk DV vs species threshold.
- Platform: Game Boy Color (Gambatte core in BizHawk).
- Memory map: Well-documented via pret/pokecrystal decomp.
- Crystal only — Gold/Silver can be added later as variant profiles in `gen2_crystal.lua`.
