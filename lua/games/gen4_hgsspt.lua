--[[
  lua/games/gen4_hgsspt.lua — Game module for Gen 4 (HGSS + Platinum).

  Exports:
    M.profiles          — address tables for heartgold, soulsilver, platinum
    M.detect()          — returns true if ROM is Gen 4 family
    M.detect_variant()  — returns "heartgold", "soulsilver", or "platinum"
    M.rom_type_for_variant(variant) — returns rom_type string for server
    M.is_gift_area(area_id) — true for gift/static encounter areas
    M.resolve_area(zone_id) — returns area_id from zone lookup

  Supports ROM variants:
    • heartgold   — Pokémon HeartGold US (IPKE)
    • soulsilver  — Pokémon SoulSilver US (IPGE) — identical offsets to HG
    • platinum    — Pokémon Platinum US (CPUE)

  Pointer chain (same for all Gen 4):
    p1   = memory.read_u32_le(0x0BA8, "Main RAM") & 0xFFFFFF
    base = memory.read_u32_le(p1 + 0x20, "Main RAM") & 0xFFFFFF
  All offsets below are relative to `base`.

  Address sources:
    • Brian0255/NDS-Ironmon-Tracker MemoryAddresses.lua + GameConfigurator.lua
      — party, battle, zone, trainer ID, badge offsets (confirmed production-tested)
    • kwsch/PKHeX SAV4HGSS.cs / SAV4Pt.cs / SAV4.cs
      — Trainer1 field offset (player name, badges), Party field offset
    • kwsch/PKHeX PlayerBag4HGSS.cs / PlayerBag4Pt.cs
      — Bag base offset + pocket-relative offsets → BALLS_POCKET_OFF per variant
    • pret/pokeheartgold include/save.h + include/constants/save_arrays.h
      — SaveData struct layout, arrayHeaders[SAVE_PCSTORAGE=41].offset field

  Coordinate system:
    PKHeX uses a "General" save buffer whose byte 0 = SaveData.dynamic_region[0].
    dynamic_region starts at SaveData+0x10 (HGSS) or SaveData+0x14 (Platinum).
    Since base = &SaveData, all PKHeX General offsets need +0x10 (HGSS) or +0x14 (Pt)
    to become base-relative offsets.

  Note: SoulSilver and HeartGold use IDENTICAL offsets (confirmed Ironmon-Tracker).
  Unlike Gen 5, there is no version-to-version delta between HG and SS.
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
-- HGSS profile: all offsets confirmed from two independent sources:
--   • Brian0255/NDS-Ironmon-Tracker MemoryAddresses.lua (live BizHawk Lua)
--   • kwsch/PKHeX SAV4HGSS.cs / SAV4.cs / PlayerBag4HGSS.cs
--
-- SoulSilver uses the SAME profile as HeartGold (confirmed from Ironmon-Tracker —
-- the SOUL_SILVER block in MemoryAddresses.lua is byte-for-byte identical to HG).
-- Unlike Gen 5 (Black/White have a +0x20 delta), there is NO version offset here.
local _HGSS_PROFILE = {
    -- Pointer chain (same for both HG and SS, and for Platinum)
    P1_PTR_ADDR      = 0x0BA8,
    BASE_PTR_OFF     = 0x20,

    -- Party
    -- PKHeX: SAV4HGSS.cs Party=0x98 → General[0x94] = count; base+0xA4 = 0x94+0x10 ✓
    -- Ironmon: playerBase=0xA8 ✓
    PARTY_COUNT_OFF  = 0xA4,   -- u8, 0-6
    PARTY_OFF        = 0xA8,   -- PartyPokemon[6], stride 0xEC (236 bytes)
    MON_SIZE         = 0xEC,   -- 236 bytes (PartyPokemon)
    SPECIES_MAX      = 493,    -- Arceus, last Gen IV species

    -- PC Storage
    -- pret/pokeheartgold: SaveData.arrayHeaders[SAVE_PCSTORAGE=41].offset field.
    -- arrayHeaders[0] at SaveData+0x23014; [41] at +0x232A4; .offset (u32, struct+8) at +0x232AC.
    -- Read u32_le at base+0x232AC → byte offset within dynamic_region of PC box data.
    PC_ARRAY_HDR_OFF = 0x232AC,
    PC_BOX_STRIDE    = 0x1000,   -- 30 × 0x88 = 0xF90, padded to 0x1000 (Gen 4 style)
    PC_SLOT_STRIDE   = 0x88,     -- BoxPokemon = 136 bytes
    BOXES_COUNT      = 18,
    MEMORIAL_BOX     = 17,       -- Box 18 (0-indexed), UI "Box 18", "THE DEAD"

    -- Battle
    -- Ironmon: playerBattleBase=0x4EA98, enemyBase=0x4F068 ✓
    PLAYER_BATTLE_OFF = 0x4EA98,
    ENEMY_BATTLE_OFF  = 0x4F068,
    BATTLE_STATUS_ADDR = 0x246F48,  -- absolute (Ironmon GLOBAL.battleStatus); not used by isInBattle()

    -- Bag (Pokéball pocket)
    -- PKHeX PlayerBag4HGSS.cs: BaseOffset=0x644, Balls pocket at +0x6C0.
    -- General buffer: 0x644+0x6C0 = 0xD04; base-relative: 0xD04+0x10 = 0xD14. ✓
    -- Slot count: BattleItems at +0x720; (0x720-0x6C0)/4 = 0x60/4 = 24 slots. ✓
    BALLS_POCKET_OFF   = 0xD14,
    BALLS_POCKET_COUNT = 24,

    -- Zone / area
    -- Ironmon: childMapHeader=0x25FE4 (pointer to map header; zone u16 at ptr+2) ✓
    ZONE_ID_OFF      = 0x25FE4,
    ZONE_ID_MAX      = 0x220,   -- HGSS has 540 zones (IDs 0x000–0x21B); 0x220=544 covers all of them.
    TRAINER_ID_OFF   = 0x440AA, -- u16; 0=wild (Ironmon: enemyTrainerID=0x440AA) ✓

    -- Player profile
    -- PKHeX SAV4HGSS.cs: Trainer1=0x64 → base+0x74 (0x64+0x10). Name = u16[8].
    -- Badges: SAV4.cs General[Trainer1+0x1A] → 0x64+0x1A=0x7E → base+0x8E (Johto)
    --         SAV4HGSS.cs General[Trainer1+0x1F] → 0x64+0x1F=0x83 → base+0x93 (Kanto)
    PLAYER_NAME_OFF  = 0x74,
    BADGES_1_OFF     = 0x8E,   -- u8, Johto badges (bit 0=Zephyr … bit 7=Rising)
    BADGES_2_OFF     = 0x93,   -- u8, Kanto badges (bit 0=Boulder … bit 7=Earth)

    -- Platform
    RAM_DOMAIN       = "Main RAM",
    ROM_DOMAIN       = "ROM",
}

-- Platinum profile: confirmed from Brian0255/NDS-Ironmon-Tracker + kwsch/PKHeX.
-- Sources: MemoryAddresses.lua (CPUE entry), SAV4Pt.cs, PlayerBag4Pt.cs.
-- All offsets are relative to the same base pointer as HGSS (P1_PTR_ADDR identical).
-- PKHeX delta for Platinum: dynamic_region starts at SaveData+0x14 (vs +0x10 HGSS).
local _PT_PROFILE = {
    -- Pointer chain — IDENTICAL to HGSS (confirmed: Ironmon GLOBAL_POINTER=0xBA8)
    P1_PTR_ADDR      = 0x0BA8,
    BASE_PTR_OFF     = 0x20,

    -- Party
    -- PKHeX SAV4Pt.cs: Party=0xA0 → count at General[0x9C] → base+0xB0 (0x9C+0x14) ✓
    -- Ironmon: playerBase=0xB4 ✓
    PARTY_COUNT_OFF  = 0xB0,   -- u8, 0-6
    PARTY_OFF        = 0xB4,   -- first PartyPokemon slot
    MON_SIZE         = 0xEC,   -- 236 bytes (Ironmon ENCRYPTED_POKEMON_SIZE=236) ✓
    SPECIES_MAX      = 493,    -- Arceus, last Gen IV species

    -- PC Storage
    -- Platinum SaveData struct not in public decompilation; assumed same layout as HGSS:
    -- arrayHeaders[41].offset field at SaveData+0x232AC (VERIFY_ME: pause BizHawk, check
    -- u32_le at base+0x232AC is a small offset < 0x23000 pointing to PC box data).
    PC_ARRAY_HDR_OFF = 0x232AC,   -- likely correct (same SaveData layout); VERIFY_ME
    PC_BOX_STRIDE    = 0x1000,    -- 30 × 0x88 = 0xF90, padded to 0x1000 (same as HGSS)
    PC_SLOT_STRIDE   = 0x88,      -- BoxPokemon = 136 bytes (confirmed pret/pokeplatinum)
    BOXES_COUNT      = 18,
    MEMORIAL_BOX     = 17,

    -- Battle
    -- Ironmon: playerBattleBase=0x4B8AC, enemyBase=0x4BE5C ✓
    PLAYER_BATTLE_OFF  = 0x4B8AC,
    ENEMY_BATTLE_OFF   = 0x4BE5C,
    BATTLE_STATUS_ADDR = 0x24A55A,  -- absolute (Ironmon GLOBAL.battleStatus); not used by isInBattle()

    -- Bag (Pokéball pocket)
    -- PKHeX PlayerBag4Pt.cs: BaseOffset=0x630, Balls at +0x6BC.
    -- General_Pt: 0x630+0x6BC = 0xCEC; base-relative: 0xCEC+0x14 = 0xD00. ✓
    -- Slot count: BattleItems at +0x6F8; (0x6F8-0x6BC)/4 = 0x3C/4 = 15 slots. ✓
    BALLS_POCKET_OFF   = 0xD00,
    BALLS_POCKET_COUNT = 15,

    -- Zone / area
    -- Ironmon: childMapHeader=0x239B0 (map header pointer; zone u16 at ptr+2) ✓
    -- Platinum has 593 zones (MAP_HEADER_COUNT); ZONE_ID_MAX=0x280=640 gives headroom.
    ZONE_ID_OFF      = 0x239B0,
    ZONE_ID_MAX      = 0x280,
    TRAINER_ID_OFF   = 0x4189E,  -- u16 enemy trainer ID; 0=wild (Ironmon) ✓

    -- Player profile
    -- PKHeX SAV4Pt.cs: Trainer1=0x68 → base+0x7C (0x68+0x14). Name = u16[8].
    -- Same charcode encoding as HGSS (custom Gen IV 16-bit codes, not Unicode).
    -- Badges: SAV4.cs General[Trainer1+0x1A] → 0x68+0x1A=0x82 → base+0x96 (Sinnoh) ✓
    PLAYER_NAME_OFF  = 0x7C,
    BADGES_1_OFF     = 0x96,   -- u8, Sinnoh badges (bit 0=Coal … bit 7=Beacon)
    BADGES_2_OFF     = false,  -- Platinum has only one badge set → disables readBadges2()

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

-- resolve_area(zone_id) — maps sequential zone ID to area_id.
-- Backward-compatible form: resolve_area(mapGroup, mapNum) still accepts legacy composite keys.
function M.resolve_area(mapGroup, mapNum)
    local key = (mapNum == nil) and mapGroup or (mapGroup * 1000 + mapNum)
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
