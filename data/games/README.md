# Game Data Directory

All game-specific JSON data lives under `data/games/<game_id>/`.

## Directory naming

```
gen<N>_<abbreviations>
```

| Directory       | Games                                          |
|-----------------|-------------------------------------------------|
| `gen1_rby`      | Red, Blue, Yellow                               |
| `gen2_crystal`  | Crystal (Gold/Silver supported as variant profiles) |
| `gen3_frlge`    | FireRed, LeafGreen, Emerald, Radical Red        |
| `gen4_hgsspt`   | HeartGold, SoulSilver, Platinum                 |
| `gen5_bw`       | Black, White                                    |

## What goes where

| Location | Contents |
|----------|----------|
| `data/games/<game_id>/` | Static game data — area maps, species data, item tables, sprite mappings, type charts. Checked into source control. |
| `data/` (root) | Per-run state files (`links.json`, `memorial.json`). Created at runtime, not checked in. |
| `data/runs/` | Run Manager working data (multi-run orchestration). Created at runtime. |

## File conventions

- **`area_map.json` / `area_map_<game>.json`** — Source-of-truth area definitions consumed by `tools/gen_area_map.py` and Lua area generators. Each entry maps raw map IDs to a canonical `area_id`.
- **`rom_map_names.json` / `rom_mapsec_names.json`** — Human-readable map and mapsec names extracted from ROM data.
- **`rr_*.json`** — Radical Red–specific data (items, species, sprites, trainers, types, priority/key-trainer rosters). Only loaded at runtime when `rom_type` indicates Radical Red.

## Adding a new game generation

1. Create the directory: `data/games/gen<N>_<abbrevs>/`
2. Add an `area_map.json` (or variant) defining canonical area IDs for encounter zones.
3. Add a `README.md` inside the directory describing the data files and their sources.
4. If the game has ROM-hack variants with extra data (like Radical Red for Gen 3), prefix those files with the hack abbreviation (e.g., `rr_types.json`).
5. Update any generators (`tools/gen_area_map.py`, etc.) to reference the new path.
