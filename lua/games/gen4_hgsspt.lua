--[[
  lua/games/gen4_hgsspt.lua — Game module for Gen 4 (HGSS + Platinum).

  Exports:
    M.profiles          — address tables for heartgold, soulsilver, platinum
    M.detect()          — returns true if ROM is Gen 4 family
    M.detect_variant()  — returns "heartgold", "soulsilver", or "platinum"
    M.rom_type_for_variant(variant) — returns rom_type string for server
    M.is_gift_area(area_id) — true for gift/static encounter areas
    M.resolve_area(mapGroup, mapNum) — returns area_id from zone lookup

  Supports ROM variants:
    • heartgold   — Pokémon HeartGold US (IPKE)
    • soulsilver  — Pokémon SoulSilver US (IPGE)
    • platinum    — Pokémon Platinum US (CPUE) — stub, addresses TBD
--]]

local M = {}

M.game_id = "gen4_hgsspt"
M.display_name = "Gen 4 (HGSS / Platinum)"
M.implemented = true

M.variants = {"heartgold", "soulsilver", "platinum"}

-- Gift/static encounter areas (matches server/adapters/gen4_hgsspt.py)
M.GIFT_AREAS_HGSS = {
    new_bark_town  = true,   -- starter (Prof. Elm's lab)
    route_30       = true,   -- Togepi egg from Mr. Pokémon
    ruins_of_alph  = true,   -- Unown gift encounters
    dragons_den    = true,   -- Dratini from Elder / ES Dratini
    goldenrod_city = true,   -- Eevee from Bill / Game Corner prizes
    mt_mortar      = true,   -- Tyrogue from Kiyo
    cianwood_city  = true,   -- Shuckle from Kirk
    ilex_forest    = true,   -- Spiky-eared Pichu (event)
    route_35       = true,   -- Kenya the Spearow (guard delivery)
}

M.GIFT_AREAS_PT = {
    twinleaf_town  = true,   -- Starter (Turtwig/Chimchar/Piplup from Prof. Rowan)
    sandgem_town   = true,   -- Dawn/Lucas Egg + other town events
    eterna_city    = true,   -- Togepi egg (Underground Man) + Cleffa (house)
    hearthome_city = true,   -- Eevee from Bebe
    iron_island    = true,   -- Riolu egg from Riley
    veilstone_city = true,   -- Porygon (condominiums)
    route_212      = true,   -- Togepi egg from Cynthia (alternate)
    pal_park       = true,   -- Pokémon migrated via Pal Park
}

-- Union of both gift area sets (used by server adapter via M.GIFT_AREAS)
M.GIFT_AREAS = {}
for k, v in pairs(M.GIFT_AREAS_HGSS) do M.GIFT_AREAS[k] = v end
for k, v in pairs(M.GIFT_AREAS_PT)   do M.GIFT_AREAS[k] = v end

-- ── ROM detection ────────────────────────────────────────────────────────────
-- BizHawk NDS does NOT expose ROM as a readable memory domain.
-- Use emu.getsystemid() for platform detection and gameinfo for variant.
local _NDS_GAME_CODES = {
    IPKE = true,   -- HeartGold US
    IPGE = true,   -- SoulSilver US
    CPUE = true,   -- Platinum US
}

-- Variant name patterns in gameinfo.getromname()
local _VARIANT_PATTERNS = {
    { pattern = "heart ?gold",   variant = "heartgold" },
    { pattern = "soul ?silver",  variant = "soulsilver" },
    { pattern = "platinum",      variant = "platinum" },
    { pattern = "ipke",          variant = "heartgold" },
    { pattern = "ipge",          variant = "soulsilver" },
    { pattern = "cpue",          variant = "platinum" },
}

function M.detect()
    -- Primary: check if BizHawk reports NDS system
    if emu and emu.getsystemid then
        local ok_sys, sys = pcall(emu.getsystemid)
        if ok_sys and sys == "NDS" then
            -- Verify it's a supported Pokémon game via gameinfo
            if gameinfo and gameinfo.getromname then
                local ok_name, name = pcall(gameinfo.getromname)
                if ok_name and name then
                    local lower = name:lower()
                    for _, entry in ipairs(_VARIANT_PATTERNS) do
                        if lower:find(entry.pattern) then return true end
                    end
                end
            end
            -- If gameinfo unavailable/unrecognized but system is NDS,
            -- still return true (assume it's a supported ROM)
            return true
        end
        if ok_sys then return false end  -- system known but not NDS
    end
    return false
end

M.detect_priority = 20  -- higher than Gen 3 (10) so NDS is checked first

-- ── Memory profiles ─────────────────────────────────────────────────────────
-- HGSS profile: confirmed from pret/pokeheartgold + live testing.
-- All offsets are relative to the resolved base pointer (M._base in memory_nds).
local _HGSS_PROFILE = {
    -- Pointer chain
    P1_PTR_ADDR      = 0x0BA8,
    BASE_PTR_OFF     = 0x20,

    -- Party
    PARTY_COUNT_OFF  = 0xA4,
    PARTY_OFF        = 0xA8,
    MON_SIZE         = 0xEC,  -- 236 bytes (PartyPokemon)

    -- PC Storage
    PC_ARRAY_HDR_OFF = 0x232AC,
    PC_BOX_STRIDE    = 0x1000,
    PC_SLOT_STRIDE   = 0x88,   -- 136 bytes (BoxPokemon)
    BOXES_COUNT      = 18,
    MEMORIAL_BOX     = 17,     -- Box 18 (0-indexed)

    -- Battle
    PLAYER_BATTLE_OFF = 0x4EA98,
    ENEMY_BATTLE_OFF  = 0x4F068,
    BATTLE_STATUS_ADDR = 0x246F48,

    -- Bag (Pokéball pocket)
    BALLS_POCKET_OFF   = 0xD14,
    BALLS_POCKET_COUNT = 24,

    -- Zone / area
    ZONE_ID_OFF      = 0x25FE4,
    ZONE_ID_MAX      = 0x200,  -- HGSS has 540 zones
    TRAINER_ID_OFF   = 0x440AA,

    -- Player profile
    PLAYER_NAME_OFF  = 0x74,
    BADGES_1_OFF     = 0x8E,   -- Johto badges
    BADGES_2_OFF     = 0x93,   -- Kanto badges (nil for Platinum)

    -- Platform
    RAM_DOMAIN       = "Main RAM",
    ROM_DOMAIN       = "ROM",
}

-- Platinum profile: confirmed from Brian0255/NDS-Ironmon-Tracker + pret/pokeplatinum.
-- Source: MemoryAddresses.lua (CPUE entry) + GameConfigurator.lua (pointer chain).
-- All offsets are relative to versionPtrAddr (= *(*(0x0BA8) + 0x20) & 0xFFFFFF),
-- IDENTICAL pointer chain to HGSS.
local _PT_PROFILE = {
    -- Pointer chain — IDENTICAL to HGSS (confirmed: NDS-Ironmon-Tracker GLOBAL_POINTER=0xBA8)
    P1_PTR_ADDR      = 0x0BA8,
    BASE_PTR_OFF     = 0x20,

    -- Party (source: NDS-Ironmon-Tracker playerBase=0xB4; pret: Party{capacity+0, count+4, mon+8})
    PARTY_COUNT_OFF  = 0xB0,   -- party struct at base+0xAC, count at +4
    PARTY_OFF        = 0xB4,   -- first PartyPokemon slot
    MON_SIZE         = 0xEC,   -- 236 bytes (NDS-Ironmon-Tracker ENCRYPTED_POKEMON_SIZE=236)

    -- PC Storage — not tracked by NDS-Ironmon-Tracker; TBD via BizHawk RAM watch.
    PC_ARRAY_HDR_OFF = nil,    -- TBD: PCBoxes save entry index 37 (vs HGSS index 41)
    PC_BOX_STRIDE    = 0x1000, -- same as HGSS (30 × 0x88 = 0xF90, padded to 0x1000)
    PC_SLOT_STRIDE   = 0x88,   -- BoxPokemon = 0x88 bytes (confirmed pret/pokeplatinum)
    BOXES_COUNT      = 18,
    MEMORIAL_BOX     = 17,

    -- Battle (source: NDS-Ironmon-Tracker playerBattleBase=0x4B8AC, enemyBase=0x4BE5C)
    PLAYER_BATTLE_OFF  = 0x4B8AC,
    ENEMY_BATTLE_OFF   = 0x4BE5C,
    BATTLE_STATUS_ADDR = 0x24A55A,  -- absolute (NDS-Ironmon-Tracker GLOBAL.battleStatus)

    -- Bag (Pokéball pocket).
    -- Source: NDS-Ironmon-Tracker medicine@0xB60 + pret struct: medicine at bag+0x51C,
    -- berries at bag+0x5BC (0xB60+0x5BC=0xC00 matches tracker's berryBagStart=0xC00 ✓),
    -- pokeballs at bag+0x6BC → 0x644+0x6BC = 0xD00.
    BALLS_POCKET_OFF   = 0xD00,  -- ⚠ derived; verify in BizHawk RAM watch
    BALLS_POCKET_COUNT = 15,     -- pret: POKEBALL_POCKET_SIZE = 15 (vs 24 HGSS)

    -- Zone / area (source: NDS-Ironmon-Tracker childMapHeader=0x239B0, read as u16)
    ZONE_ID_OFF      = 0x239B0,
    ZONE_ID_MAX      = 0x280,  -- 593 zones (MAP_HEADER_COUNT); 0x280=640 gives headroom
    TRAINER_ID_OFF   = 0x4189E,  -- enemy trainer ID; 0=wild (NDS-Ironmon-Tracker)

    -- Player profile (name not tracked by NDS-Ironmon-Tracker; TBD via binary analysis)
    PLAYER_NAME_OFF  = nil,    -- TBD
    BADGES_1_OFF     = 0x96,   -- single Sinnoh badge byte (NDS-Ironmon-Tracker badges=0x96)
    BADGES_2_OFF     = false,  -- Platinum has only one badge set → nil

    RAM_DOMAIN       = "Main RAM",
    ROM_DOMAIN       = "ROM",
}

M.profiles = {
    heartgold  = _HGSS_PROFILE,
    soulsilver = _HGSS_PROFILE,
    platinum   = _PT_PROFILE,
}

-- ── Area lookup ─────────────────────────────────────────────────────────────
local _AREAS = require("gen4_hgsspt_areas")

function M.resolve_area(mapGroup, mapNum)
    local key = mapGroup * 1000 + mapNum
    return _AREAS[key] or ""
end

function M.is_gift_area(area_id)
    return M.GIFT_AREAS[area_id] == true
end

-- ── Variant detection ───────────────────────────────────────────────────────
function M.detect_variant()
    if gameinfo and gameinfo.getromname then
        local ok_name, name = pcall(gameinfo.getromname)
        if ok_name and name then
            local lower = name:lower()
            for _, entry in ipairs(_VARIANT_PATTERNS) do
                if lower:find(entry.pattern) then return entry.variant end
            end
        end
    end
    return "heartgold"  -- fallback default
end

--- Returns the rom_type string sent to the server in hello events.
function M.rom_type_for_variant(variant)
    if variant == "heartgold"  then return "heartgold" end
    if variant == "soulsilver" then return "soulsilver" end
    if variant == "platinum"   then return "platinum" end
    return "hgss"
end

return M
