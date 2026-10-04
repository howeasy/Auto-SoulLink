# Game Data Directory

All game-specific JSON data lives under `data/games/<game_id>/`.

## Directory naming

```
gen<N>_<abbreviations>
```

| Directory       | Games                                          |
|-----------------|-------------------------------------------------|
| `gen1_rby`      | Red, Blue, Yellow (Archipelago Red/Blue shares the pack) |
| `gen1_purergb`  | PureRed, PureBlue, PureGreen (pureRGB v2.7.6) — its own pack beside `gen1_rby`; `admission_overlay.json` / `*_overlay.json` cover the companion build |
| `gen2_crystal`  | Crystal — profile, admission, area map, encounters, `overlay/` and `receipts/` |
| `gen2_gold`     | Gold — same shape as `gen2_crystal` |
| `gen2_silver`   | Silver — same shape as `gen2_crystal` |
| `gen2_gsc`      | Shared Gen 2 damage-calc names only (`calc_names.json`); the adapter's `game_id`, not a game pack |
| `gen3_frlg`     | FireRed, LeafGreen — admission profile/engine-signals pack for the `lua/gen3/` client |
| `gen3_rr`       | Radical Red — admission profile/engine-signals pack for the `lua/gen3/` client |
| `gen3_emerald`  | Emerald — its own admission profile/engine-signals/area-map pack for the `lua/gen3/` client; pairs only E<->E |
| `gen3_frlge`    | Shared Gen 3 area map, locations, encounters, trainers, calc names, ROM map names and Radical Red data tables (`rr_*.json`); FRLG/RR area lookup |
| `gen3_exp/<digest>/` | Emerald Expansion reference ROM, one directory per ROM digest (today `28877d73`): profile, engine signals, area map, encounters, trainers, layout and facts for the `lua/gen3/` client |
| `gen4_hgss` / `gen4_hge` | HeartGold/SoulSilver and the hg-engine HeartGold fork (pack: profile, charmap, area map, locations, encounters, trainers; `gen4_pt` is bind-only) |
| `gen5_bw`       | Black, White, Black 2, White 2                  |

## What goes where

| Location | Contents |
|----------|----------|
| `data/games/<game_id>/` | Static game data — area maps, species data, item tables, sprite mappings, type charts. Checked into source control. |
| `data/` (root) | Per-run state files (`links.json`, `memorial.json`). Created at runtime, not checked in. |
| `data/runs/` | Run Manager working data (multi-run orchestration). Created at runtime. |

## File conventions

- **`area_map.json` / `area_map_<game>.json`** — Source-of-truth area definitions consumed by `tools/gen_area_map.py` and Lua area generators. Each entry maps raw map IDs to a canonical `area_id`.
- **`rom_map_names.json` / `rom_mapsec_names.json`** — Human-readable map and mapsec names extracted from ROM data (today only in `gen3_frlge/`).
- **`rr_*.json`** — Radical Red–specific data (items, species, sprites, trainers, types, priority/key-trainer rosters). Only loaded at runtime when `rom_type` indicates Radical Red.

## Adding a new game generation

1. Create the directory: `data/games/gen<N>_<abbrevs>/`
2. Add an `area_map.json` (or variant) defining canonical area IDs for encounter zones.
3. Add a `README.md` inside the directory describing the data files and their sources.
4. If the game has ROM-hack variants with extra data (like Radical Red for Gen 3), prefix those files with the hack abbreviation (e.g., `rr_types.json`).
5. Update any generators (`tools/gen_area_map.py`, etc.) to reference the new path.
