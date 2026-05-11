--[[
  lua/games/gen5_bw.lua — Game module for Gen 5 (Black/White 1 & 2).

  Exports:
    M.profiles          — address tables for pokemon_black, pokemon_white,
                          pokemon_black_2, pokemon_white_2
    M.detect()          — returns true if ROM is Gen 5 family (BW/BW2)
    M.detect_variant()  — returns "pokemon_black", "pokemon_white", etc.
    M.rom_type_for_variant(variant) — returns rom_type string for server
    M.is_gift_area(area_id) — true for gift/static encounter areas
    M.resolve_area(zone_id) — returns area_id from BW zone lookup

  ROM detection: read game code (4 ASCII bytes) from Main RAM at 0x3FFE0C.
    Black:    IRBO → 0x4F425249
    White:    IRAO → 0x4F415249
    Black 2:  IREO → 0x4F455249
    White 2:  IRDO → 0x4F445249
  Source: Brian0255/NDS-Ironmon-Tracker GameInfo.lua

  Memory addresses: all absolute (DIRECT_ADDR = true).
  Sources:
    • Brian0255/NDS-Ironmon-Tracker MemoryAddresses.lua — party, battle, zone, badges
    • Wi-Fi-Labs/PokeRNG-LuaScripts BW_RNG_BizHawk_SM.lua / B2W2_RNG_BizHawk_SM.lua
      — PC_STORAGE_BASE (boxAddr), PLAYER_NAME_OFF (trainerIDsAddr − 0x14 + 0x04)
    • kwsch/PKHeX PlayerBag5BW.cs / PlayerBag5B2W2.cs
      — Items pocket layout (no separate Balls pocket; balls at block+0x000)

  Address notes:
    • Gen 5 has NO separate Balls pocket. Poké Balls live in the general Items pocket
      (Block 25 at offset 0x000). BALLS_POCKET_OFF points to Block25_base; the client
      scans for ball item IDs (0x0001–0x0010) within the first BALLS_POCKET_COUNT slots.
    • White = Black + 0x20 for ALL fields (party, zone, badge, items, OT name, PC).
    • White 2 = Black 2 + 0x80 for party/zone/badge/item fields, but
      + 0x40 for TrainerData (PLAYER_NAME_OFF) and PCStorage (PC_STORAGE_BASE).
    • PC_BOX_STRIDE = 0xFA0 (30 × 0x88 + 0x10 box header; no Gen-4-style padding).
    • PC_CURRENT_BOX_OFF = 0x17D80 (estimate: 24 × 0xFA0; VERIFY_ME via BizHawk).
--]]

local M = {}

M.game_id      = "gen5_bw"
M.display_name = "Gen 5 (Black / White / BW2)"
M.implemented  = true

M.variants = {"pokemon_black", "pokemon_white", "pokemon_black_2", "pokemon_white_2"}

-- ── Gift / static encounter areas ───────────────────────────────────────────
-- Only areas where the Pokémon is received directly (no Pokéball needed).
-- Legendary static encounters (Reshiram, Zekrom, Kyurem) are wild battles
-- and are NOT gift areas — they consume a nuzlocke slot normally.

M.GIFT_AREAS_BW1 = {
    nuvema_town   = true,  -- Starter Pokémon (Prof. Juniper's lab)
    striaton_city = true,  -- Elemental monkey (Striaton Restaurant gift)
    castelia_city = true,  -- Eevee from Amanita (Bianca's sister)
    nacrene_city  = true,  -- Fossil revives (Nacrene Museum)
    gift          = true,  -- fallback for unmapped gift locations
}

M.GIFT_AREAS_BW2 = {
    aspertia_city  = true,  -- Starter Pokémon (Bianca's gift)
    floccesy_ranch = true,  -- Riolu egg from Alder's grandson
    castelia_city  = true,  -- Eevee from Amanita
    nacrene_city   = true,  -- Fossil revives
    gift           = true,  -- fallback
}

-- Union for code that doesn't care which sub-game
M.GIFT_AREAS = {}
for k, v in pairs(M.GIFT_AREAS_BW1) do M.GIFT_AREAS[k] = v end
for k, v in pairs(M.GIFT_AREAS_BW2) do M.GIFT_AREAS[k] = v end

-- ── ROM detection ────────────────────────────────────────────────────────────
-- Game code lives at 0x3FFE0C in Main RAM (NDS ROM header mirrors to 0x3FFE00).
-- Read as u32_le. Values confirmed from NDS-Ironmon-Tracker GameInfo.lua.
local _ROM_CODE_ADDR = 0x3FFE0C
local _GAME_CODES = {
    [0x4F425249] = "pokemon_black",    -- "IRBO" reversed LE
    [0x4F415249] = "pokemon_white",    -- "IRAO"
    [0x4F455249] = "pokemon_black_2",  -- "IREO"
    [0x4F445249] = "pokemon_white_2",  -- "IRDO"
}

local _VARIANT_PATTERNS = {
    { pattern = "pokemon.?black.?version.?2",  variant = "pokemon_black_2" },
    { pattern = "pokemon.?white.?version.?2",  variant = "pokemon_white_2" },
    { pattern = "pokemon.?black",              variant = "pokemon_black" },
    { pattern = "pokemon.?white",              variant = "pokemon_white" },
    { pattern = "ireo",                        variant = "pokemon_black_2" },
    { pattern = "irdo",                        variant = "pokemon_white_2" },
    { pattern = "irbo",                        variant = "pokemon_black" },
    { pattern = "irao",                        variant = "pokemon_white" },
}

function M.detect()
    -- Must be NDS
    if emu and emu.getsystemid then
        local ok_sys, sys = pcall(emu.getsystemid)
        if ok_sys and sys ~= "NDS" then return false end
    end
    -- Check RAM code first (fast, reliable)
    local ok_mem, code = pcall(memory.read_u32_le, _ROM_CODE_ADDR, "Main RAM")
    if ok_mem and _GAME_CODES[code] then return true end
    -- Fallback: ROM name
    if gameinfo and gameinfo.getromname then
        local ok_name, name = pcall(gameinfo.getromname)
        if ok_name and name then
            local lower = name:lower()
            for _, entry in ipairs(_VARIANT_PATTERNS) do
                if lower:find(entry.pattern) then return true end
            end
        end
    end
    return false
end

M.detect_priority = 25  -- higher than Gen 4 (20) — checked first among NDS games

-- ── Memory profiles ─────────────────────────────────────────────────────────
-- All addresses are absolute (DIRECT_ADDR = true; no pointer chain needed).
-- Source: Brian0255/NDS-Ironmon-Tracker MemoryAddresses.lua
--
-- Fields marked VERIFY_ME require BizHawk RAM Watch confirmation.
-- Use the corresponding Vanilla estimate as a starting point.

local _COMMON_GEN5 = {
    DIRECT_ADDR          = true,
    ZONE_ID_DIRECT       = true,   -- zone 0 is valid (Black City / Marine Tube)
    MON_SIZE             = 0xDC,   -- 220 bytes (PartyPokemon in Gen 5)
    -- PC box stride: 30 slots × 0x88 + 0x10 header = 0xFA0 (confirmed from Wi-Fi-Labs RNG scripts)
    PC_BOX_STRIDE        = 0xFA0,  -- no padding (Gen 4 uses 0x1000 with padding)
    PC_SLOT_STRIDE       = 0x88,   -- BoxPokemon = 136 bytes (same as Gen 4)
    BOXES_COUNT          = 24,     -- Gen 5 has 24 PC boxes
    MEMORIAL_BOX         = 23,     -- Box 24, "THE DEAD" (0-indexed)
    -- PC_CURRENT_BOX_OFF: 24 boxes × 0xFA0 = 0x17D80 bytes of box data;
    -- currentBox u8 sits immediately after (VERIFY_ME — needs BizHawk RAM Watch)
    PC_CURRENT_BOX_OFF   = 0x17D80,
    BADGES_2_OFF         = false,  -- Gen 5 has only one set of 8 Unova badges
    TRAINER_NAME_ENCODING = "gen5", -- UTF-16LE passthrough (0x0020-0x007E → ASCII)
    RAM_DOMAIN           = "Main RAM",
    ROM_DOMAIN           = "ROM",
}

-- Black US (all addresses confirmed from NDS-Ironmon-Tracker / Wi-Fi-Labs RNG scripts)
local _BLACK_PROFILE = {}
for k, v in pairs(_COMMON_GEN5) do _BLACK_PROFILE[k] = v end
local _BLACK_ADDRS = {
    PARTY_COUNT_OFF    = 0x2349B0,  -- u8, 0-6
    PARTY_OFF          = 0x2349B4,  -- PKM[6], 220 bytes each
    PLAYER_BATTLE_OFF  = 0x26A794,  -- player battle-mon copy (PID at base)
    ENEMY_BATTLE_OFF   = 0x26B254,  -- enemy battle-mon copy
    BATTLE_STATUS_ADDR = 0x1D0798,  -- u32: non-zero = in battle
    ZONE_ID_OFF        = 0x2592B2,  -- u16 childMapHeader zone ID (direct read)
    ZONE_ID_MAX        = 0x300,     -- BW1 has <600 zones; 0x300=768 gives headroom
    TRAINER_ID_OFF     = 0x2697BE,  -- u16 enemy trainer ID (0 = wild)
    BADGES_1_OFF       = 0x23CDB0,  -- u8 Unova badge bitfield
    -- Items pocket base (Block 25 offset 0x000); balls are in the general Items pocket.
    -- Confirmed: Block25_base = itemStart(0x234784) − 0x7D8 = 0x233FAC
    -- Source: PKHeX PlayerBag5BW.cs (Items at block+0x000) + Wi-Fi-Labs RNG scripts.
    BALLS_POCKET_OFF   = 0x233FAC,  -- Items pocket (contains all items including balls)
    BALLS_POCKET_COUNT = 50,        -- scan first 50 slots; balls (IDs 1-16) sort early
    -- PC storage base = Box 0, Slot 0. Source: Wi-Fi-Labs BW_RNG_BizHawk_SM.lua (boxAddr)
    PC_STORAGE_BASE    = 0x21BFAC,
    -- Player OT name (u16[8] UTF-16LE). Source: Wi-Fi-Labs BW_RNG_BizHawk_SM.lua
    PLAYER_NAME_OFF    = 0x234FB0,
}
for k, v in pairs(_BLACK_ADDRS) do _BLACK_PROFILE[k] = v end

-- White US (all addresses = Black + 0x20, confirmed NDS-Ironmon-Tracker)
local _WHITE_PROFILE = {}
for k, v in pairs(_BLACK_PROFILE) do _WHITE_PROFILE[k] = v end
do
    local delta = 0x20
    local shifted = {
        "PARTY_COUNT_OFF", "PARTY_OFF", "PLAYER_BATTLE_OFF", "ENEMY_BATTLE_OFF",
        "BATTLE_STATUS_ADDR", "ZONE_ID_OFF", "TRAINER_ID_OFF", "BADGES_1_OFF",
        "BALLS_POCKET_OFF", "PC_STORAGE_BASE", "PLAYER_NAME_OFF",
    }
    for _, field in ipairs(shifted) do
        if _WHITE_PROFILE[field] then
            _WHITE_PROFILE[field] = _WHITE_PROFILE[field] + delta
        end
    end
end

-- Black 2 US (confirmed from NDS-Ironmon-Tracker / Wi-Fi-Labs RNG scripts)
local _BLACK2_PROFILE = {}
for k, v in pairs(_COMMON_GEN5) do _BLACK2_PROFILE[k] = v end
local _BLACK2_ADDRS = {
    PARTY_COUNT_OFF    = 0x21E428,
    PARTY_OFF          = 0x21E42C,
    PLAYER_BATTLE_OFF  = 0x258314,
    ENEMY_BATTLE_OFF   = 0x258874,
    BATTLE_STATUS_ADDR = 0x1B5138,  -- ⚠ White2 uses 0x1B5178 (+0x40, NOT +0x80)
    ZONE_ID_OFF        = 0x246860,  -- u16 childMapHeader
    ZONE_ID_MAX        = 0x300,     -- BW2 has more zones but same headroom
    TRAINER_ID_OFF     = 0x257332,
    BADGES_1_OFF       = 0x226728,
    -- Items pocket base (Block 25 offset 0x000); confirmed from PKHeX + Wi-Fi-Labs.
    -- Block25_base = itemStart(0x21E1FC) − 0x7D8 = 0x21DA24
    BALLS_POCKET_OFF   = 0x21DA24,
    BALLS_POCKET_COUNT = 50,
    -- PC storage base. Source: Wi-Fi-Labs B2W2_RNG_BizHawk_SM.lua (boxAddr)
    PC_STORAGE_BASE    = 0x2059E4,
    -- Player OT name. Source: Wi-Fi-Labs B2W2_RNG_BizHawk_SM.lua (trainerIDsAddr − 0x14 + 0x04)
    -- NOTE: White 2 uses +0x40 offset from Black 2 here, NOT the usual +0x80.
    PLAYER_NAME_OFF    = 0x21E9E8,
}
for k, v in pairs(_BLACK2_ADDRS) do _BLACK2_PROFILE[k] = v end

-- White 2 US (most fields = Black2 + 0x80; TrainerData and PCStorage blocks use +0x40)
local _WHITE2_PROFILE = {}
for k, v in pairs(_BLACK2_PROFILE) do _WHITE2_PROFILE[k] = v end
do
    local delta = 0x80
    local shifted = {
        "PARTY_COUNT_OFF", "PARTY_OFF", "PLAYER_BATTLE_OFF", "ENEMY_BATTLE_OFF",
        "ZONE_ID_OFF", "TRAINER_ID_OFF", "BADGES_1_OFF",
        "BALLS_POCKET_OFF",
    }
    for _, field in ipairs(shifted) do
        if _WHITE2_PROFILE[field] then
            _WHITE2_PROFILE[field] = _WHITE2_PROFILE[field] + delta
        end
    end
    -- White2 battleStatus is +0x40 from Black2, NOT +0x80 (confirmed NDS-Ironmon-Tracker)
    _WHITE2_PROFILE.BATTLE_STATUS_ADDR = 0x1B5178
    -- TrainerData and PCStorage blocks use +0x40 offset for White 2, NOT +0x80.
    -- Source: Wi-Fi-Labs B2W2_RNG_BizHawk_SM.lua (getGameAddrOffset uses 0x40 for these blocks)
    _WHITE2_PROFILE.PLAYER_NAME_OFF  = 0x21EA28   -- 0x21E9E8 + 0x40
    _WHITE2_PROFILE.PC_STORAGE_BASE  = 0x205A24   -- 0x2059E4 + 0x40
end

M.profiles = {
    pokemon_black   = _BLACK_PROFILE,
    pokemon_white   = _WHITE_PROFILE,
    pokemon_black_2 = _BLACK2_PROFILE,
    pokemon_white_2 = _WHITE2_PROFILE,
}

-- ── Area lookup ─────────────────────────────────────────────────────────────
-- BW1 and BW2 share the same zone ID space; a single table serves all 4 variants.
-- The areas table is loaded lazily on first call to avoid load-order issues.
local _AREAS

local function _load_areas()
    if _AREAS then return end
    local ok, t = pcall(require, "gen5_bw_areas")
    if ok then _AREAS = t else _AREAS = {} end
end

function M.resolve_area(zone_id)
    _load_areas()
    return _AREAS[zone_id] or ""
end

function M.is_gift_area(area_id)
    return M.GIFT_AREAS[area_id] == true
end

-- ── Variant detection ───────────────────────────────────────────────────────
function M.detect_variant()
    -- Primary: ROM code from Main RAM (fastest, most reliable)
    local ok_mem, code = pcall(memory.read_u32_le, _ROM_CODE_ADDR, "Main RAM")
    if ok_mem and _GAME_CODES[code] then
        return _GAME_CODES[code]
    end
    -- Fallback: ROM name string
    if gameinfo and gameinfo.getromname then
        local ok_name, name = pcall(gameinfo.getromname)
        if ok_name and name then
            local lower = name:lower()
            for _, entry in ipairs(_VARIANT_PATTERNS) do
                if lower:find(entry.pattern) then return entry.variant end
            end
        end
    end
    return "pokemon_black"  -- fallback
end

function M.rom_type_for_variant(variant)
    if variant == "pokemon_black"   then return "pokemon_black"   end
    if variant == "pokemon_white"   then return "pokemon_white"   end
    if variant == "pokemon_black_2" then return "pokemon_black_2" end
    if variant == "pokemon_white_2" then return "pokemon_white_2" end
    return "pokemon_black"
end

return M
