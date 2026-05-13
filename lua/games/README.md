# Game Modules

This directory contains game-specific modules for the multi-game Soul Link framework.
Each module encapsulates all game-specific logic: memory addresses, battle detection,
mon data reading, and area resolution.

## Directory Structure

```
lua/
├── slink.lua              ← Universal entry point (auto-detects game)
├── slink_gen1.lua         ← Manual launcher for Gen 1
├── slink_gen2.lua         ← Manual launcher for Gen 2
├── slink_gen3.lua         ← Manual launcher for Gen 3
├── slink_gen4.lua         ← Manual launcher for Gen 4
├── slink_gen5.lua         ← Manual launcher for Gen 5
├── game_detect.lua        ← Game detection dispatcher
├── hud.lua                ← Shared HUD overlay module
├── connector.lua          ← Shared TCP connector
├── socket.lua             ← LuaSocket loader
├── memory_gb.lua          ← GB/GBC memory helpers (Gen 1 & Gen 2)
├── memory_gba.lua         ← GBA memory helpers (Gen 3)
├── memory_nds.lua         ← NDS memory helpers (Gen 4 & Gen 5)
├── games/                 ← Game modules (this directory)
│   ├── gen1_rby.lua           — Gen 1 (Red / Blue / Yellow)
│   ├── gen2_crystal.lua       — Gen 2 (Crystal)
│   ├── gen3_frlge.lua         — Gen 3 (FRLG / Emerald)
│   ├── gen4_hgsspt.lua        — Gen 4 (HGSS / Platinum)
│   └── gen5_bw.lua            — Gen 5 (Black / White / BW2)
├── clients/               ← Game-specific client scripts
│   ├── gen1_rby_client.lua    — Gen 1 client (Red / Blue / Yellow)
│   ├── gen2_crystal_client.lua — Gen 2 client (Crystal)
│   ├── gen3_frlge_client.lua  — Gen 3 client (FRLG / Emerald / RR)
│   ├── gen4_hgsspt_client.lua — Gen 4 client (HGSS / Platinum)
│   └── gen5_bw_client.lua     — Gen 5 client (Black / White / BW2)
├── tests/                 ← BizHawk test scripts
└── x64/                   ← LuaSocket native DLLs
```

## Module Contract

Each game module is a Lua file that returns a table with these fields:

```lua
return {
    -- Identity
    game_id = "frlg",                    -- matches server adapter game_id
    display_name = "FireRed / LeafGreen", -- human-readable name

    -- Memory profile (addresses, struct sizes, detection mode)
    profile = { ... },                    -- same format as PROFILES in memory.lua

    -- Area resolution
    resolve_area = function(mapGroup, mapNum)
        -- Returns area_id string or "" for unmapped areas
    end,

    -- Battle state detection
    is_in_battle = function()
        -- Returns true if currently in battle
    end,
    is_in_overworld = function()
        -- Returns true if in safe overworld state
    end,
    get_battle_outcome = function()
        -- Returns outcome code (0=none, 1=won, 7=caught for CFRU, etc.)
    end,

    -- Mon data reading
    read_party_slot = function(slot)
        -- Returns {key, hp, maxHP, level, species_id, nickname, ...}
    end,
    mon_key = function(base_addr)
        -- Returns the identity string for a mon at the given address
    end,

    -- Gift/special detection
    is_gift_area = function(area_id)
        -- Returns true for gift/static encounter areas
    end,

    -- ROM identification
    detect = function()
        -- Returns true if this game module matches the loaded ROM
        -- Called during auto-detection
    end,
    detect_priority = 10,                -- higher = checked first (RR=20, AP=15, vanilla=10)
}
```

## Implemented Modules

### Gen 1 — `gen1_rby.lua`

Game module for Pokémon Red, Blue, and Yellow (US English).

- **ROM titles**: `POKEMON RED`, `POKEMON BLUE`, `POKEMON YELLOW` — read from GB ROM header at `0x0134` (16 bytes)
- **Variants**: `red` (shared with Blue), `yellow` (shifted addresses)
- **Platform**: GB/GBC — uses `memory_gb.lua` for party/box reads
- **Memory domain**: System Bus (WRAM addresses)
- **Area lookup**: single-byte map ID → area_id via `data/games/gen1_rby/gen1_rby_areas.lua`
- **Gift areas**: `pallet_town`, `oaks_lab`, `celadon_city`, `saffron_city`, `silph_co`, `cinnabar_island`, `route_4`, `celadon_game_corner`
- **Mon key format**: `DDDD:TTTT:II` (DVs + OT ID + species index) — evolves on species change
- **Badge tracking**: wObtainedBadges bitfield (8 badges)
- **Commands**: `force_faint`, `box_mon`, `party_mon`, `memorialize`, `hud_show`, `resolved_areas`, `unresolve_area`, `game_over`
- **Exports**: `PROFILES` (red/yellow address tables), `detect()`, `detect_variant()`, `rom_type_for_variant()`, `is_gift_area()`, `resolve_area()`, `toNatDex()`, `INDEX_TO_NATDEX`

### Gen 3 — `gen3_frlge.lua`

Game module for FireRed, LeafGreen, and Emerald.

- **ROM codes**: `BPRE` (FireRed US), `BPGE` (LeafGreen US) — read from GBA ROM header at `0x080000AC` (System Bus)
- **Variants**: `vanilla`, `ap` (Archipelago), `radical_red` (CFRU-based), `emerald` (stub)
- **Platform**: GBA — uses `memory_gba.lua` for party/box reads
- **Memory domain**: System Bus (EWRAM/IWRAM addresses)
- **Area lookup**: `mapGroup * 256 + mapNum` → area_id via `data/games/gen3_frlge/gen3_frlge_areas.lua` (175 entries)
- **Gift areas**: `oaks_lab`, `intro`, `gift`, `cinnabar_lab`, `celadon_condominiums`, `silph_co_7f`, `saffron_dojo`
- **Exports**: `profiles` (vanilla/ap/radical_red address tables), `detect()`, `detect_variant()`, `rom_type_for_variant()`, `is_gift_area()`

### Gen 4 — `gen4_hgsspt.lua`

Game module for HeartGold, SoulSilver, and Platinum.

- **ROM codes**: `IPKE` (HeartGold US), `IPGE` (SoulSilver US), `CPUE` (Platinum US) — read from NDS ROM header at offset `0x0C` in the `"ROM"` memory domain
- **Variants**: `heartgold`, `soulsilver`, `platinum` (stub — addresses TBD)
- **Platform**: NDS — requires `memory_nds.lua` for party/box reads
- **Memory domain**: `"Main RAM"` (NDS ARM9)
- **Area lookup**: zone IDs (u16 NARC indices) → area_id strings via `data/games/gen4_hgsspt/gen4_hgsspt_areas.lua` (195 zone entries)
- **Gift areas**: `new_bark_town`, `route_30`, `ruins_of_alph`, `dragons_den`
- **Area data source**: `data/games/gen4_hgsspt/area_map_hgss.json`
- **Exports**: `profiles` (HGSS profile with NDS pointer chain, party/box/battle offsets), `detect()`, `detect_variant()`, `rom_type_for_variant()`, `is_gift_area()`, `resolve_area()`

### `data/games/gen4_hgsspt/gen4_hgsspt_areas.lua`

Auto-generated area lookup table for HGSS. Maps 195 zone IDs to area_id strings. Includes 4 gift areas (`dragons_den`, `new_bark_town`, `route_30`, `ruins_of_alph`). Regenerated from `data/games/gen4_hgsspt/area_map_hgss.json`.

### Gen 5 — `gen5_bw.lua`

Game module for Pokémon Black, White, Black 2, and White 2.

- **ROM codes**: `IRBO`/`IRGO` (BW US), `IREO`/`IRDO` (BW2 US) — read from NDS ROM header
- **Variants**: `black`, `white`, `black2`, `white2`
- **Platform**: NDS — uses `memory_nds.lua` for party/box reads
- **Memory domain**: `"Main RAM"` (NDS ARM9)
- **Area lookup**: zone IDs → area_id strings via `data/games/gen5_bw/gen5_bw_areas.lua`
- **Gift areas**: `nuvema_town`, `accumula_town`, `castelia_city` (BW); `aspertia_city` (BW2)
- **Exports**: `profiles` (per-variant NDS addresses), `detect()`, `detect_variant()`, `rom_type_for_variant()`, `is_gift_area()`, `resolve_area()`

## Detection Order

Modules are sorted by `detect_priority` (descending) and checked in order.
The first module whose `detect()` returns `true` is selected. Higher priority
means more specific — e.g., Radical Red (priority 20) is checked before
vanilla FRLG (priority 10) since RR is a superset ROM.

## Module Lifecycle

1. **Boot**: All modules in `lua/games/` are loaded
2. **Detection**: Modules are sorted by priority and `detect()` is called
3. **Initialization**: The matched module's `profile` is applied to the appropriate memory module
4. **Runtime**: The client script calls module functions for game-specific behavior

## Adding a New Game

1. Create `lua/games/<game_id>.lua`
2. Implement the contract fields above
3. Create a corresponding server adapter in `server/adapters/<game_id>.py`
4. Add area map data in `data/games/<game_id>/`
5. Optionally create a client script in `lua/clients/<game_id>_client.lua`
6. Create a top-level launcher in `lua/slink_<gen>.lua`
