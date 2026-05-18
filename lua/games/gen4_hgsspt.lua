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

  Address sources (cross-referenced; each constant cites its primary source inline):
    • pret/pokeheartgold include/save.h + include/constants/save_arrays.h
      — SaveData struct layout, arrayHeaders[SAVE_PCSTORAGE=41].offset field
    • pret/pokeheartgold include/party.h
      — struct Party { u8 curCount; PartyPokemon mons[6]; } → PARTY_COUNT/PARTY_OFF
    • pret/pokeheartgold include/pokemon_types_def.h
      — sizeof(PartyPokemon)=0xEC, sizeof(BoxPokemon)=0x88, Block A/B/C/D layouts
    • pret/pokeheartgold include/pokemon_storage_system.h
      — NUM_BOXES=18, MONS_PER_BOX=30, PCStorage.boxes[NUM_BOXES][MONS_PER_BOX]
    • pret/pokeheartgold include/player_data.h
      — struct PlayerProfile (name[8] @ +0x00, johtoBadges @ +0x1A, kantoBadges @ +0x1F)
    • pret/pokeheartgold include/field_system.h + include/map_header.h
      — FieldSystem.childMapHeader → MapHeader.mapID (u16 @ +0x02)
    • pret/pokeheartgold include/battle/battle.h + src/battle/battle_setup.c
      — BattleSystem, TrainerData.id (concrete RAM offset not symbolised; see Ironmon)
    • pret/pokeplatinum — same headers, Platinum-specific offsets (different
      dynamic_region delta: +0x14 vs HGSS +0x10)
    • Brian0255/NDS-Ironmon-Tracker MemoryAddresses.lua + GameConfigurator.lua
      — concrete RAM offsets confirmed against live battles (where pret only
      provides struct layout, not the runtime heap chunk address)
    • kwsch/PKHeX SAV4HGSS.cs / SAV4Pt.cs / SAV4.cs / PlayerBag4*.cs
      — independently verifies Trainer1 / Party / Bag base offsets

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

M.variants = {"heartgold", "soulsilver", "platinum", "renegade_platinum"}

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
-- Ordering matters: more specific patterns (e.g. "renegade") must come BEFORE
-- the general "platinum" pattern so RP isn't misdetected as vanilla Pt.
local _VARIANT_PATTERNS = {
    { pattern = "renegade",      variant = "renegade_platinum" },  -- RP ROM filename hint
    { pattern = "heart ?gold",   variant = "heartgold" },
    { pattern = "soul ?silver",  variant = "soulsilver" },
    { pattern = "platinum",      variant = "platinum" },
    { pattern = "ipke",          variant = "heartgold" },
    { pattern = "ipge",          variant = "soulsilver" },
    { pattern = "cpue",          variant = "platinum" },
}

-- Renegade Platinum CRC32 / SHA1 whitelist. RP keeps Platinum's CPUE game code,
-- so the only reliable runtime distinguisher is the ROM hash or filename hint.
-- Add the SHA1 of any RP build the user wants supported. Empty by default → falls
-- back to filename pattern detection above (matches "renegade" substring).
local _RP_ROM_HASHES = {
    -- ["SHA1:..."] = true,
}

-- Read a few bytes from ROM banner / build string area to look for an RP marker.
-- Returns true if a recognizable RP signature is found. Used as last-ditch
-- detection when neither the filename nor the hash whitelist matches.
local function _rom_has_rp_signature()
    if not memory or not memory.read_u8 then return false end
    -- Try common NDS ROM domains (BizHawk exposes "ROM" or "Cartridge ROM" depending on version).
    local domains = { "ROM", "Cartridge ROM", "NDS ROM" }
    for _, dom in ipairs(domains) do
        local ok, b = pcall(memory.read_u8, 0x200, dom)  -- typical Drayano banner area
        if ok and b then
            -- Scan a 256-byte window for "RENEGADE" or "Drayano".
            local buf = {}
            for i = 0, 255 do
                local ok2, c = pcall(memory.read_u8, 0x200 + i, dom)
                if ok2 then buf[#buf+1] = string.char(c) end
            end
            local s = table.concat(buf)
            if s:find("RENEGADE") or s:find("Renegade") or s:find("Drayano") then
                return true
            end
            return false   -- domain readable but no signature
        end
    end
    return false
end

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

    -- PC Storage
    -- pret/pokeheartgold: SaveData.arrayHeaders[SAVE_PCSTORAGE=41].offset field.
    -- arrayHeaders[0] at SaveData+0x23014; [41] at +0x232A4; .offset (u32, struct+8) at +0x232AC.
    -- Read u32_le at base+0x232AC → byte offset within dynamic_region of PC box data.
    -- HGSS dynamic_region starts at SaveData+0x10 — see PKHeX SAV4HGSS.cs General buffer offset.
    PC_ARRAY_HDR_OFF   = 0x232AC,
    DYNAMIC_REGION_OFF = 0x10,   -- SaveData → dynamic_region delta (HGSS)
    PC_BOX_STRIDE      = 0x1000, -- 30 × 0x88 = 0xF90, padded to 0x1000 (Gen 4 style)
    PC_SLOT_STRIDE     = 0x88,   -- BoxPokemon = 136 bytes
    BOXES_COUNT        = 18,
    MEMORIAL_BOX       = 17,     -- Box 18 (0-indexed), UI "Box 18", "THE DEAD"

    -- Battle
    -- Ironmon: playerBattleBase=0x4EA98, enemyBase=0x4F068 ✓
    PLAYER_BATTLE_OFF = 0x4EA98,
    ENEMY_BATTLE_OFF  = 0x4F068,
    BATTLE_STATUS_ADDR = 0x246F48,  -- absolute (Ironmon GLOBAL.battleStatus); not used by isInBattle()
    -- BattleMon stat stages + active PID, confirmed from NDS-Ironmon-Tracker
    -- MemoryAddresses.lua (HEART_GOLD block: statStagesPlayer=0x49E2C, statStagesEnemy=0x49EEC,
    -- playerBattleMonPID=0x49E7C). Stride between same-side battlers = 0x180.
    -- Active mon PID lives at stat_stages_base + 0x50 (BattleMon layout).
    -- Source: pret/pokeheartgold src/battle/struct_battle_mon.c BattleMon.statChanges +
    --         NDS-Ironmon-Tracker MemoryAddresses.lua for concrete RAM offsets.
    STAT_STAGES_PLAYER_OFF = 0x49E2C,   -- battler 0 (player_L) stat changes [s8 × 7]
    STAT_STAGES_ENEMY_OFF  = 0x49EEC,   -- battler 1 (enemy_L)  stat changes [s8 × 7]
    BATTLE_R_STRIDE        = 0x180,     -- left → right battler delta (doubles only)
    ACTIVE_MON_PID_DELTA   = 0x50,      -- stat_stages_base → active mon PID (BattleMon offset)

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

    -- PC Storage
    -- Platinum SaveData has an extra u32 prefix vs HGSS, shifting dynamic_region from
    -- SaveData+0x10 → SaveData+0x14. arrayHeaders[41].offset stays at the same SaveData-
    -- relative position (+0x232AC), but the chunk-offset value it stores must be added
    -- to SaveData+0x14 (not +0x10) to land on PCStorage.boxes[0].
    -- Source: PKHeX SAV4Pt.cs General buffer offset = 0x14 (vs SAV4HGSS.cs = 0x10).
    PC_ARRAY_HDR_OFF   = 0x232AC,
    DYNAMIC_REGION_OFF = 0x14,   -- SaveData → dynamic_region delta (Platinum-specific)
    PC_BOX_STRIDE      = 0x1000,
    PC_SLOT_STRIDE     = 0x88,
    BOXES_COUNT        = 18,
    MEMORIAL_BOX       = 17,

    -- Battle
    -- Ironmon: playerBattleBase=0x4B8AC, enemyBase=0x4BE5C ✓
    PLAYER_BATTLE_OFF  = 0x4B8AC,
    ENEMY_BATTLE_OFF   = 0x4BE5C,
    BATTLE_STATUS_ADDR = 0x24A55A,  -- absolute (Ironmon GLOBAL.battleStatus); not used by isInBattle()
    -- BattleMon stat stages + active PID, confirmed from NDS-Ironmon-Tracker
    -- MemoryAddresses.lua (PLATINUM block: statStagesPlayer=0x475D0, statStagesEnemy=0x47690,
    -- playerBattleMonPID=0x47620). Same struct layout as HGSS; only base addresses differ.
    STAT_STAGES_PLAYER_OFF = 0x475D0,
    STAT_STAGES_ENEMY_OFF  = 0x47690,
    BATTLE_R_STRIDE        = 0x180,
    ACTIVE_MON_PID_DELTA   = 0x50,

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

-- Renegade Platinum profile — RP keeps Platinum's CPUE game code AND the same
-- SaveData layout, so every Pt offset is inherited. RP-specific deltas (if any
-- are discovered during live scans) are listed below as explicit overrides.
-- Source: live-scan verification via lua/tests/test_gen4_rp_scan.lua; no pret
-- citation since RP is a hack on top of pret/pokeplatinum.
local _RP_PROFILE = {}
for k, v in pairs(_PT_PROFILE) do _RP_PROFILE[k] = v end
-- RP-specific deltas go here once discovered. Expected to be empty for the
-- standard RP releases (Drayano keeps the save format unchanged).
-- _RP_PROFILE.SOMETHING = 0xNEW

M.profiles = {
    heartgold          = _HGSS_PROFILE,
    soulsilver         = _HGSS_PROFILE,
    platinum           = _PT_PROFILE,
    renegade_platinum  = _RP_PROFILE,
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
-- Detection order (most specific first):
--   1. User override: SLINK_VARIANT_OVERRIDE global set before requiring this module.
--   2. ROM hash whitelist (_RP_ROM_HASHES) — definitive for known RP builds.
--   3. ROM banner signature scan (Drayano build string) — best-effort fallback.
--   4. Filename pattern match via _VARIANT_PATTERNS — catches user-renamed ROMs
--      containing "renegade" / "heartgold" / "soulsilver" / "platinum".
-- The 1–3 steps are RP-specific; 4 handles all vanilla variants.
function M.detect_variant()
    -- 1. Manual override.
    if _G.SLINK_VARIANT_OVERRIDE then
        local ov = tostring(_G.SLINK_VARIANT_OVERRIDE):lower()
        if M.profiles[ov] then return ov end
    end
    -- 2. ROM hash whitelist.
    if gameinfo and gameinfo.getromhash then
        local ok_h, hash = pcall(gameinfo.getromhash)
        if ok_h and hash and _RP_ROM_HASHES[hash] then
            return "renegade_platinum"
        end
    end
    -- 3. ROM banner signature scan.
    if _rom_has_rp_signature() then
        return "renegade_platinum"
    end
    -- 4. Filename pattern match.
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
    if variant == "heartgold"          then return "heartgold" end
    if variant == "soulsilver"         then return "soulsilver" end
    if variant == "platinum"           then return "platinum" end
    if variant == "renegade_platinum"  then return "renegade_platinum" end
    return "hgss"
end

return M
