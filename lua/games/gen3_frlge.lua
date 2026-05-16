--[[
  lua/games/gen3.lua — Game module for Gen 3 (FRLG + Emerald).

  Exports:
    GEN3.profiles      — address tables for vanilla, ap, radical_red (+ future RSE)
    GEN3.detect()      — returns true if ROM is Gen 3 family
    GEN3.detect_variant() — returns "vanilla", "ap", "radical_red", or "emerald"
    GEN3.rom_type_for_variant(variant) — returns rom_type string for server

  Supports ROM variants:
    • vanilla      — unmodified FRLG US 1.0 (and data-only randomizers)
    • ap           — Archipelago-patched FRLG
    • radical_red  — Radical Red 4.1 / CFRU-based hacks
    • emerald      — Pokémon Emerald US (stub — addresses TBD)
--]]

local GEN3 = {}

GEN3.game_id = "gen3_frlge"
GEN3.display_name = "Gen 3 (FRLG / Emerald)"

-- Supported ROM variants (sub-profiles)
GEN3.variants = {"vanilla", "ap", "radical_red", "emerald"}

-- Gift/static encounter areas (matches server/adapters/GEN3.py)
GEN3.GIFT_AREAS = {
    oaks_lab = true,
    intro = true,
    gift = true,
    cinnabar_lab = true,
    celadon_condominiums = true,
    silph_co_7f = true,
    saffron_dojo = true,
    route_4_pokecenter = true,
}

function GEN3.is_gift_area(area_id)
    if GEN3.GIFT_AREAS[area_id] then return true end
    if area_id and area_id:sub(1, 5) == "gift_" then return true end
    return false
end

-- Detection: returns true if the loaded ROM is Gen 3 (FRLG or Emerald)
function GEN3.detect()
    -- Read 4-byte game code from GBA ROM header at 0x080000AC
    -- Wrapped in pcall: "System Bus" domain only exists on GBA cores.
    local ok, code = pcall(function()
        local b = {}
        for i = 0, 3 do
            b[i+1] = string.char(memory.read_u8(0x080000AC + i, "System Bus"))
        end
        return table.concat(b)
    end)
    if not ok then return false end
    return code == "BPRE" or code == "BPGE"  -- FRLG
        or code == "BPEE"                     -- Emerald
end

GEN3.detect_priority = 10

-- ── Address profiles ────────────────────────────────────────────────────────
-- Each profile contains every RAM address that differs between ROM builds.
GEN3.profiles = {
    vanilla = {
        PARTY_COUNT_ADDR           = 0x02024029,
        PARTY_BASE                 = 0x02024284,
        ENEMY_COUNT_ADDR           = 0x0202402A,
        ENEMY_BASE                 = 0x0202402C,
        BATTLE_TYPE_ADDR           = 0x02022B4C,
        BATTLE_OUTCOME_ADDR        = 0x02023E8A,
        BATTLE_MONS_ADDR           = 0x02023BE4,
        BATTLER_PARTY_INDEXES_ADDR = 0x02023BCE,
        BATTLERS_COUNT_ADDR        = 0x02023BCC,
        BATTLE_MAIN_FUNC_ADDR      = 0x03004F84,
        RETURN_FROM_BATTLE_ADDR    = 0x08015B59,
        GMAIN_ADDR                 = 0x030030F0,
        SB1_PTR_ADDR               = 0x03005008,
        SB2_PTR_ADDR               = 0x0300500C,
        PSP_PTR_ADDR               = 0x03005010,
        -- SaveBlock struct offsets (pret/pokefirered include/global.h)
        SB2_ENC_KEY_OFFSET         = 0x0F20,
        SB1_BALL_POCKET_OFFSET     = 0x0430,
        SB1_BALL_POCKET_COUNT      = 13,
        SB1_FLAGS_OFFSET           = 0x0EE0,   -- SaveBlock1.flags[] bitfield
        -- Vanilla: inBattle detection via gMain+0x439 bit 1
        OVERWORLD_MODE             = "gmain_flags",
        -- SongHeader ROM addresses (FireRed US 1.0, vanilla ROM code)
        SE_SONG_HEADERS = {
            [16] = 0x086B5984,  -- SE_FAINT   (SE_POKE_DEAD)
            [17] = 0x086B59D4,  -- SE_FLEE    (SE_NIGERU)
            [22] = 0x086B5ADC,  -- SE_BOO
            [25] = 0x086B5BB0,  -- SE_SUCCESS (SE_SEIKAI)
            [26] = 0x086B5BE0,  -- SE_FAILURE (SE_HAZURE)
            [95] = 0x086B6E70,  -- SE_SHINY   (SE_REAPOKE)
        },
        -- gBaseStats ROM table (pret/pokefirered: data/pokemon/base_stats.h)
        BASESTATS_ADDR       = 0x08254784,
        BASESTATS_ENTRY_SIZE = 28,  -- sizeof(struct BaseStats) including padding
    },
    ap = {
        PARTY_COUNT_ADDR           = 0x0202403D,
        PARTY_BASE                 = 0x02024298,
        ENEMY_COUNT_ADDR           = 0x0202403E,
        ENEMY_BASE                 = 0x02024040,
        BATTLE_TYPE_ADDR           = 0x02022B60,
        BATTLE_OUTCOME_ADDR        = 0x02023E9E,
        BATTLE_MONS_ADDR           = 0x02023BF8,
        BATTLER_PARTY_INDEXES_ADDR = 0x02023BE2,
        BATTLERS_COUNT_ADDR        = 0x02023BE0,
        BATTLE_MAIN_FUNC_ADDR      = 0x03004ED4,
        RETURN_FROM_BATTLE_ADDR    = nil,  -- unknown in AP; disable battle redirect
        GMAIN_ADDR                 = 0x03003040,
        SB1_PTR_ADDR               = 0x03004F58,
        SB2_PTR_ADDR               = 0x03004F5C,
        PSP_PTR_ADDR               = 0x03004F60,
        -- AP struct offsets (ball pocket shifted +0x250; encKey shifted +0x0C)
        SB2_ENC_KEY_OFFSET         = 0x0F2C,
        SB1_BALL_POCKET_OFFSET     = 0x0680,
        SB1_BALL_POCKET_COUNT      = 13,
        SB1_FLAGS_OFFSET           = 0x1130,   -- SaveBlock1.flags[] (+0x250 from vanilla 0x0EE0)
        -- AP: overworld detection via gMain+0x038 == 1 (AP custom field)
        OVERWORLD_MODE             = "gmain_038",
        -- AP recompiles ROM code; addresses found via test_sound_discovery.lua.
        SE_SONG_HEADERS = {
            [16] = 0x086DBF50,  -- SE_FAINT   (SE_POKE_DEAD)
            [17] = 0x086DBFA0,  -- SE_FLEE    (SE_NIGERU)
            [22] = 0x086DC0A8,  -- SE_BOO
            [25] = 0x086DC17C,  -- SE_SUCCESS (SE_SEIKAI)
            [26] = 0x086DC1AC,  -- SE_FAILURE (SE_HAZURE)
            [95] = 0x086DD43C,  -- SE_SHINY   (SE_REAPOKE)
        },
        -- AP recompiles from vanilla; gBaseStats shifted from 0x08254784.
        -- Discovered via test_ability_diag.lua — Bulbasaur stats validated at this addr.
        BASESTATS_ADDR       = 0x0825634C,
        BASESTATS_ENTRY_SIZE = 28,
    },
    -- Radical Red 4.1 (CFRU-based ROM hack): IWRAM pointers shifted, party in
    -- SaveBlock1, bag in EWRAM, OUTCOME_CAUGHT = 7.  Addresses discovered via
    -- lua/test_rr_discovery.lua on a mid-game RR 4.1 ROM.
    radical_red = {
        -- Party data: CFRU preserves gPlayerParty at the vanilla EWRAM address.
        -- SB1+0x38 is a SAVE/LOAD shadow copy — writes there are overwritten by
        -- the engine from gPlayerParty on the next frame.  All reads and writes
        -- MUST target the vanilla address (0x02024284) for changes to persist.
        PARTY_IN_SB1               = false,
        SB1_PARTY_BASE_OFFSET      = 0x0038,     -- shadow copy offset (reference only)
        PARTY_COUNT_ADDR           = 0x02024029,  -- gPlayerPartyCount (vanilla EWRAM)
        PARTY_BASE                 = 0x02024284,  -- gPlayerParty (vanilla EWRAM)
        -- Enemy party: vanilla EWRAM globals don't work for CFRU.
        -- All enemy reads use gBattleMons[1] instead (see client.lua).
        -- However, gEnemyParty IS valid *during* battle for full team reads.
        ENEMY_COUNT_ADDR           = 0x0202402A,  -- gEnemyPartyCount (valid during battle only)
        ENEMY_BASE                 = 0x0202402C,  -- gEnemyParty (valid during battle only)
        BATTLE_TYPE_ADDR           = 0x02022B4C,
        BATTLE_OUTCOME_ADDR        = 0x02023E8A,
        BATTLE_MONS_ADDR           = 0x02023BE4,
        BATTLER_PARTY_INDEXES_ADDR = 0x02023BCE,  -- vanilla addr (CFRU preserves)
        BATTLERS_COUNT_ADDR        = 0x02023BCC,  -- vanilla addr (CFRU preserves)
        BATTLE_MAIN_FUNC_ADDR      = 0x03004F84,  -- confirmed same as vanilla FRLG
        RETURN_FROM_BATTLE_ADDR    = 0x08015B59,  -- confirmed same as vanilla FRLG
        GMAIN_ADDR                 = nil,
        -- IWRAM pointers
        SB1_PTR_ADDR               = 0x03003840,
        SB2_PTR_ADDR               = 0x03003838,
        PSP_PTR_ADDR               = nil,         -- DPE does NOT use gPokemonStoragePtr

        -- ── CFRU Compressed Box Storage ──────────────────────────────────────
        -- CFRU/DPE uses 58-byte CompressedPokemon (not 80-byte BoxPokemon).
        -- 25 boxes stored in 4 non-contiguous EWRAM regions via hardcoded
        -- pointer table (sPokemonBoxPtrs[] from pokemon_storage_system.c).
        -- PokemonStorage struct base at 0x02029314; currentBox at +0x00.
        CFRU_COMPRESSED_BOX        = true,
        COMPRESSED_MON_SIZE        = 0x3A,        -- 58 bytes
        POKEMON_STORAGE_BASE       = 0x02029314,
        BOXES_PER_STORE            = 25,
        -- Precomputed base address for each box (30 slots × 58 bytes = 1740 per box).
        -- Boxes 0-18: contiguous from ORIGINAL_BOX_POKEMON_RAM (0x02029318).
        -- Boxes 19-21, 22-23, 24: separate EWRAM regions.
        CFRU_BOX_BASES             = {
            [1]  = 0x02029318,                     -- box  0
            [2]  = 0x02029318 + 1740,              -- box  1
            [3]  = 0x02029318 + 1740 * 2,          -- box  2
            [4]  = 0x02029318 + 1740 * 3,          -- box  3
            [5]  = 0x02029318 + 1740 * 4,          -- box  4
            [6]  = 0x02029318 + 1740 * 5,          -- box  5
            [7]  = 0x02029318 + 1740 * 6,          -- box  6
            [8]  = 0x02029318 + 1740 * 7,          -- box  7
            [9]  = 0x02029318 + 1740 * 8,          -- box  8
            [10] = 0x02029318 + 1740 * 9,          -- box  9
            [11] = 0x02029318 + 1740 * 10,         -- box 10
            [12] = 0x02029318 + 1740 * 11,         -- box 11
            [13] = 0x02029318 + 1740 * 12,         -- box 12
            [14] = 0x02029318 + 1740 * 13,         -- box 13
            [15] = 0x02029318 + 1740 * 14,         -- box 14
            [16] = 0x02029318 + 1740 * 15,         -- box 15
            [17] = 0x02029318 + 1740 * 16,         -- box 16
            [18] = 0x02029318 + 1740 * 17,         -- box 17
            [19] = 0x02029318 + 1740 * 18,         -- box 18
            [20] = 0x0203CB44,                     -- box 19
            [21] = 0x0203CB44 + 1740,              -- box 20
            [22] = 0x0203CB44 + 1740 * 2,          -- box 21
            [23] = 0x02027434,                     -- box 22
            [24] = 0x02027434 + 1740,              -- box 23
            [25] = 0x02024638,                     -- box 24
        },
        -- Box name storage (from CFRU pokemon_storage_system.c):
        -- Boxes 0-13 forward from ORIGINAL_BOX_NAME_RAM, boxes 14-24 backward.
        CFRU_BOX_NAME_BASE         = 0x02031658,   -- ORIGINAL_BOX_NAME_RAM
        BOX_NAMES_OFFSET           = 0x8344,

        SB2_ENC_KEY_OFFSET         = 0x0F20,
        SB1_FLAGS_OFFSET           = 0x0EE0,
        -- Ball pocket in EWRAM (not inside SB1); quantities NOT encrypted
        BAG_IN_EWRAM               = true,
        BALL_POCKET_ADDR           = 0x0203C354,
        BALL_POCKET_ENC            = false,
        SB1_BALL_POCKET_COUNT      = 50,
        -- Battle detection: gBattleMons[0].maxHP > 0 AND gBattleOutcome == 0.
        OVERWORLD_MODE             = "battle_outcome",
        OUTCOME_CAUGHT             = 7,
        OUTCOME_RAN                = 4,  -- CFRU adds DREW=3, shifting RAN from 3→4
        SE_SONG_HEADERS = {
            [16] = 0x086B5984,  -- SE_FAINT   (SE_POKE_DEAD)
            [17] = 0x086B59D4,  -- SE_FLEE    (SE_NIGERU)
            [22] = 0x086B5ADC,  -- SE_BOO
            [25] = 0x086B5BB0,  -- SE_SUCCESS (SE_SEIKAI)
            [26] = 0x086B5BE0,  -- SE_FAILURE (SE_HAZURE)
            [95] = 0x086B6E70,  -- SE_SHINY   (SE_REAPOKE)
        },
        CFRU_NO_ENCRYPT            = true,
        TRAINER_OPPONENT_ADDR      = 0x020386AE,  -- gTrainerBattleOpponent_A (game uses 1-based IDs)
        -- CFRU stores a pointer to gBaseStats at ROM 0x080001BC.
        -- Dereferenced at init time; supports any CFRU-based ROM hack.
        CFRU_BASESTATS_PTR         = 0x080001BC,
        BASESTATS_ENTRY_SIZE       = 28,
    },
    -- Emerald US 1.0 — stub profile (addresses TBD, requires research)
    -- Game code: BPEE. Same Gen 3 Pokemon struct (100 bytes, encrypted substructs).
    -- Key differences from FRLG: different EWRAM layout, different gMain address,
    -- Battle Frontier, double battles in wild grass, abilities matter more.
    emerald = nil,  -- TODO: populate with Emerald-specific addresses
}

-- ── Variant detection ─────────────────────────────────────────────────────────
-- Determines which profile (vanilla, ap, radical_red) matches the running ROM.
-- Detection strategy (same priority as original M.initProfile):
--   1. Read ROM offset 0x108 for "pokemon red/green version" (present in BOTH AP and RR)
--   2. If found, disambiguate by checking IWRAM SaveBlock1 pointers:
--      - AP:  SB1_PTR at 0x03004F58
--      - RR:  SB1_PTR at 0x03003840
--   3. If 0x108 has ARM code (not ASCII), also try RR detection.
--   4. Fallback: vanilla.

-- Validate that a candidate SB1_PTR_ADDR points to plausible SaveBlock1 data.
local function _validateSB1Ptr(ptr_addr)
    local ok, sb1 = pcall(memory.read_u32_le, ptr_addr)
    if not ok then return false end
    if sb1 < 0x02000000 or sb1 >= 0x02040000 then return false end
    local mapGroup = memory.read_u8(sb1 + 0x0004)
    local mapNum   = memory.read_u8(sb1 + 0x0005)
    return mapGroup <= 42 and mapNum <= 199
end

-- Stronger RR detection: validates SB1 pointer AND party structure.
local function _detectRR()
    local rr = GEN3.profiles.radical_red
    if not rr then return false end
    if not _validateSB1Ptr(rr.SB1_PTR_ADDR) then return false end
    -- Cross-check: party count at SB1+0x0034 should be 0-6
    local ok, sb1 = pcall(memory.read_u32_le, rr.SB1_PTR_ADDR)
    if not ok then return false end
    local partyCount = memory.read_u8(sb1 + 0x0034)
    if partyCount > 6 then return false end
    -- Cross-check: if party count > 0, first mon at SB1+0x0038 should have
    -- a non-zero personality and plausible maxHP
    if partyCount > 0 then
        local pers = memory.read_u32_le(sb1 + 0x0038)
        local maxHP = memory.read_u16_le(sb1 + 0x0038 + 0x58)
        if pers == 0 or maxHP == 0 or maxHP > 999 then return false end
    end
    return true
end

--- Returns the detected variant: "vanilla", "ap", "radical_red", or "emerald".
--- Must only be called after GEN3.detect() returns true.
function GEN3.detect_variant()
    -- Check game code first — RSE is a separate variant family
    local b = {}
    for i = 0, 3 do
        b[i+1] = string.char(memory.read_u8(0x080000AC + i, "System Bus"))
    end
    local code = table.concat(b)
    if code == "BPEE" then
        return "emerald"
    end

    -- FRLG family: detect sub-variant
    -- Step 1: Read 32 bytes from ROM offset 0x108
    local rom_name_bytes = {}
    for i = 0, 31 do
        local rb = memory.read_u8(0x08000108 + i, "System Bus")
        if rb == 0 then break end
        rom_name_bytes[#rom_name_bytes + 1] = string.char(rb)
    end
    local rom_name = table.concat(rom_name_bytes):lower()
    local has_version_str = rom_name:find("pokemon red version")
                         or rom_name:find("pokemon green version")

    -- Step 2: Detect profile by validating IWRAM pointers
    if has_version_str then
        -- Both AP and RR have this string; check AP first (original priority)
        if _validateSB1Ptr(GEN3.profiles.ap.SB1_PTR_ADDR) then
            return "ap"
        elseif _detectRR() then
            return "radical_red"
        end
    else
        -- No version string — could be vanilla or RR (future builds)
        if _detectRR() then
            return "radical_red"
        end
    end
    return "vanilla"
end

--- Returns the rom_type string for the server hello event.
--- @param variant string "vanilla", "ap", "radical_red", or "emerald"
--- @return string rom_type (e.g. "firered", "firered_ap", "firered_rr", "emerald")
function GEN3.rom_type_for_variant(variant)
    -- Read game code to determine specific ROM
    local b = {}
    for i = 0, 3 do
        b[i+1] = string.char(memory.read_u8(0x080000AC + i, "System Bus"))
    end
    local code = table.concat(b)

    -- Emerald
    if code == "BPEE" then return "emerald" end

    -- FRLG family
    local base
    if     code == "BPRE" then base = "firered"
    elseif code == "BPGE" then base = "leafgreen"
    else                       return "unknown"
    end
    if variant == "ap" then
        return base .. "_ap"
    elseif variant == "radical_red" then
        return base .. "_rr"
    end
    return base
end

-- Additive Emerald US 1.0 profile from the Gen5 fork.
-- Uses Emerald-specific RAM addresses while leaving existing FRLG/AP/RR logic untouched.
GEN3.profiles.emerald = {
    PARTY_COUNT_ADDR           = 0x020244E9,
    PARTY_BASE                 = 0x020244EC,
    ENEMY_COUNT_ADDR           = 0x020244EA,
    ENEMY_BASE                 = 0x02024744,
    BATTLE_TYPE_ADDR           = 0x02022FEC,
    BATTLE_OUTCOME_ADDR        = 0x0202433A,
    BATTLE_MONS_ADDR           = 0x02024084,
    BATTLER_PARTY_INDEXES_ADDR = 0x0202406E,
    BATTLERS_COUNT_ADDR        = 0x0202406C,
    BATTLE_MAIN_FUNC_ADDR      = 0x03005D04,
    RETURN_FROM_BATTLE_ADDR    = nil,
    GMAIN_ADDR                 = 0x030022C0,
    SB1_PTR_ADDR               = 0x03005D8C,
    SB2_PTR_ADDR               = 0x03005D90,
    PSP_PTR_ADDR               = 0x03005D94,
    SB2_ENC_KEY_OFFSET         = 0x00AC,
    SB1_BALL_POCKET_OFFSET     = 0x0650,
    SB1_BALL_POCKET_COUNT      = 16,
    SB1_FLAGS_OFFSET           = 0x1270,
    OVERWORLD_MODE             = "gmain_flags",
    OUTCOME_CAUGHT             = 7,
    OUTCOME_RAN                = 4,
    SE_SONG_HEADERS            = {},
    BASESTATS_ADDR             = 0x083203CC,
    BASESTATS_ENTRY_SIZE       = 28,
    TRAINER_OPPONENT_ADDR      = 0x02038BCA,
}

-- Cache the ROM game code so Emerald-specific lookups can branch cheaply.
do
    local ok, code = pcall(function()
        local b = {}
        for i = 0, 3 do
            b[i + 1] = string.char(memory.read_u8(0x080000AC + i, "System Bus"))
        end
        return table.concat(b)
    end)
    GEN3._game_code = (ok and code) or nil
end

local function _lookup_table(frlg_module, emerald_module)
    if GEN3._game_code == "BPEE" then
        local ok, tbl = pcall(require, emerald_module)
        if ok then
            return tbl
        end
    end
    return require(frlg_module)
end

function GEN3.resolve_area(mapGroup, mapNum)
    local areas = _lookup_table("gen3_frlge_areas", "gen3_emerald_areas")
    local k = mapGroup .. ":" .. mapNum
    return areas[k] or ""
end

function GEN3.resolve_location(mapGroup, mapNum)
    local locs = _lookup_table("gen3_frlge_locations", "gen3_emerald_locations")
    local k = mapGroup .. ":" .. mapNum
    return locs[k] or ""
end

return GEN3
