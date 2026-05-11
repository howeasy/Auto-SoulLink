--[[
  lua/memory_gba.lua — FRLG memory map constants and read/write helpers.
  Sourced from pret/pokefirered decomp (include/pokemon.h,
  include/pokemon_storage_system.h, src/load_save.c) and
  Skeli789/Complete-Fire-Red-Upgrade (CFRU) for Radical Red support.

  Supports three ROM profiles:
    • "vanilla"     — unmodified FireRed/LeafGreen US 1.0 (and data-only randomizers).
                      gMain+0x439 for battle detection. 80-byte BoxPokemon. Encrypted substructs.
    • "ap"          — Archipelago-patched FRLG (recompiled binary, shifted addresses).
                      EWRAM globals +0x14, IWRAM pointers −0xB0. gMain+0x038 for overworld.
                      Three-condition battle check. 80-byte BoxPokemon. Encrypted substructs.
    • "radical_red" — Radical Red 4.1 / CFRU-based hacks. Vanilla EWRAM party address.
                      gBattleMons-based battle detection ("battle_outcome" mode).
                      58-byte CompressedPokemon in PC boxes. Unencrypted substructs (fixed order).
                      EWRAM bag (not in SB1, not encrypted). 25 boxes. OUTCOME_CAUGHT=7.

  Call M.applyProfile(prof, profile_name) ONCE at startup before any other M.*
  function. Profile detection is handled by lua/game_detect.lua and
  lua/games/frlg.lua; this module only applies the resulting profile data.

  All profile-dependent addresses are passed in via the prof table and copied
  into M.* by applyProfile(). Struct field offsets, encoding tables, and
  constants that are identical across profiles remain at file scope.
--]]

local M = {}

-- Localize hot BizHawk memory functions for ~10-15% fewer dispatch lookups
-- in decrypt/scan loops that run hundreds of times per tick.
local mem_r8   = memory.read_u8
local mem_r16  = memory.read_u16_le
local mem_r32  = memory.read_u32_le
local mem_w8   = memory.write_u8
local mem_w16  = memory.write_u16_le
local mem_w32  = memory.write_u32_le
local fmt      = string.format

-- ── Profile fields that need explicit reset in applyProfile() ─────────────────
-- These are profile-dependent fields that may be set by one profile but not
-- another. applyProfile() clears them all before copying the new profile.
local _PROFILE_RESET_KEYS = {
    "BAG_IN_EWRAM", "BALL_POCKET_ADDR", "BALL_POCKET_ENC",
    "CFRU_COMPRESSED_BOX", "COMPRESSED_MON_SIZE", "CFRU_BOX_BASES",
    "POKEMON_STORAGE_BASE", "CFRU_BOX_NAME_BASE",
    "BASESTATS_ADDR", "BASESTATS_ENTRY_SIZE",
    "OVERWORLD_MODE", "OUTCOME_CAUGHT", "OUTCOME_RAN",
    "BOX_DATA_OFFSET", "BOX_SB1_OFFSET", "BOXES_PER_STORE",
    "BOX_NAMES_OFFSET", "MEMORIAL_BOX",
    "PARTY_IN_SB1", "SB1_PARTY_BASE_OFFSET",
    "CFRU_NO_ENCRYPT", "CFRU_BASESTATS_PTR",
    "TRAINER_OPPONENT_ADDR",
    "PARTY_COUNT_ADDR", "PARTY_BASE",
    "ENEMY_COUNT_ADDR", "ENEMY_BASE",
    "BATTLE_TYPE_ADDR", "BATTLE_OUTCOME_ADDR",
    "BATTLE_MONS_ADDR", "BATTLER_PARTY_INDEXES_ADDR", "BATTLERS_COUNT_ADDR",
    "BATTLE_MAIN_FUNC_ADDR", "RETURN_FROM_BATTLE_ADDR",
    "GMAIN_ADDR", "SB1_PTR_ADDR", "SB2_PTR_ADDR", "PSP_PTR_ADDR",
    "SB2_ENC_KEY_OFFSET", "SB1_BALL_POCKET_OFFSET", "SB1_BALL_POCKET_COUNT",
    "SB1_FLAGS_OFFSET", "SE_SONG_HEADERS",
    "_overworld_mode", "supports_battle_redirect",
}

-- ── ROM identification ────────────────────────────────────────────────────────
-- The 4-byte game code at 0x080000AC is preserved by all randomizers and by the
-- Archipelago patcher — it remains BPRE (FireRed) or BPGE (LeafGreen).

M.GAME_CODE_ADDR     = 0x080000AC  -- GBA ROM header: 4-byte ASCII game code
M.ROM_FIRERED_CODE   = "BPRE"      -- FireRed US 1.0 and 1.1 (vanilla, randomized, or AP)
M.ROM_LEAFGREEN_CODE = "BPGE"      -- LeafGreen US 1.0 and 1.1 (vanilla, randomized, or AP)

-- Reads the 4-byte ASCII game code from the GBA ROM header.
function M.readGameCode()
    local bytes = {}
    for i = 0, 3 do
        bytes[i + 1] = string.char(memory.read_u8(M.GAME_CODE_ADDR + i, "System Bus"))
    end
    return table.concat(bytes)
end

-- Apply a profile table to M.* constants. Called once at startup with the
-- profile returned by game_detect. Takes a profile_name string and the
-- profile data table.
-- Equivalent to the old M.initProfile() steps 3-6 + logging + refreshPartyAddrs.
function M.applyProfile(prof, profile_name)
    -- Step 1: Reset ALL profile-derived fields to nil/defaults
    for _, k in ipairs(_PROFILE_RESET_KEYS) do
        M[k] = nil
    end
    -- Reset defaults that must not be nil
    M.OUTCOME_CAUGHT = 6  -- vanilla/AP default
    M.OUTCOME_RAN    = 3  -- B_OUTCOME_RAN (vanilla/AP=3; CFRU=4 — profile overrides)
    M.BOXES_PER_STORE = 14
    M.PARTY_IN_SB1 = false
    M.BAG_IN_EWRAM = false
    M.BOX_DATA_OFFSET = 0x0004  -- vanilla/AP: PokemonStorage boxes at +0x0004
    M.BOX_NAMES_OFFSET = 0x8344  -- vanilla/AP: box names offset in PokemonStorage
    M.CFRU_COMPRESSED_BOX = false
    M.CFRU_NO_ENCRYPT = false

    -- Step 2: Store profile name
    M.profile_name = profile_name or "unknown"

    -- Step 3: Copy all keys from profile into M.*
    for k, v in pairs(prof) do
        M[k] = v
    end

    -- Step 4: Set overworld detection mode
    M._overworld_mode = prof.OVERWORLD_MODE

    -- Step 5: Set capabilities
    M.supports_battle_redirect = (prof.RETURN_FROM_BATTLE_ADDR ~= nil)

    -- Step 6: Override profile-dependent constants (if specified in profile)
    if prof.OUTCOME_CAUGHT then M.OUTCOME_CAUGHT = prof.OUTCOME_CAUGHT end
    if prof.BAG_IN_EWRAM then
        M.BAG_IN_EWRAM     = true
        M.BALL_POCKET_ADDR  = prof.BALL_POCKET_ADDR or 0
        M.BALL_POCKET_ENC   = prof.BALL_POCKET_ENC or false
    end
    if prof.BOX_DATA_OFFSET then
        M.BOX_DATA_OFFSET = prof.BOX_DATA_OFFSET
    end
    if prof.BOX_SB1_OFFSET then
        M.BOX_SB1_OFFSET = prof.BOX_SB1_OFFSET
    end
    if prof.BOXES_PER_STORE then
        M.BOXES_PER_STORE = prof.BOXES_PER_STORE
    end
    -- Memorial box is always the last box
    M.MEMORIAL_BOX = M.BOXES_PER_STORE - 1
    if prof.BOX_NAMES_OFFSET then
        M.BOX_NAMES_OFFSET = prof.BOX_NAMES_OFFSET
    end
    -- CFRU compressed box storage
    if prof.CFRU_COMPRESSED_BOX then
        M.CFRU_COMPRESSED_BOX  = true
        M.COMPRESSED_MON_SIZE  = prof.COMPRESSED_MON_SIZE
        M.CFRU_BOX_BASES       = prof.CFRU_BOX_BASES
        M.POKEMON_STORAGE_BASE = prof.POKEMON_STORAGE_BASE
        M.CFRU_BOX_NAME_BASE   = prof.CFRU_BOX_NAME_BASE
    end

    -- gBaseStats: resolve address for ability lookups
    if prof.CFRU_BASESTATS_PTR then
        -- CFRU stores a ROM pointer at a known address; dereference it.
        local ok, ptr = pcall(memory.read_u32_le, prof.CFRU_BASESTATS_PTR)
        if ok and ptr >= 0x08000000 and ptr < 0x0A000000 then
            M.BASESTATS_ADDR = ptr
        else
            M.BASESTATS_ADDR = nil
        end
    elseif prof.BASESTATS_ADDR then
        M.BASESTATS_ADDR = prof.BASESTATS_ADDR
    end
    if prof.BASESTATS_ENTRY_SIZE then
        M.BASESTATS_ENTRY_SIZE = prof.BASESTATS_ENTRY_SIZE
    end

    -- Logging
    console.log("[MEM] ROM profile: " .. M.profile_name)
    if M.BAG_IN_EWRAM then
        console.log(string.format("[MEM] EWRAM bag: ball pocket at 0x%08X (%d slots)",
            M.BALL_POCKET_ADDR, M.SB1_BALL_POCKET_COUNT))
    else
        console.log(string.format("[MEM] SB2 encKey offset=0x%04X, ball pocket=SB1+0x%04X (%d slots)",
            M.SB2_ENC_KEY_OFFSET, M.SB1_BALL_POCKET_OFFSET, M.SB1_BALL_POCKET_COUNT))
    end

    -- Refresh ASLR-dependent party addresses (no-op when PARTY_IN_SB1=false).
    M.refreshPartyAddrs()
    if M.PARTY_IN_SB1 then
        console.log(string.format("[MEM] Party in SB1: count@0x%08X (EWRAM), base@SB1+0x%04X",
            M.PARTY_COUNT_ADDR, M.SB1_PARTY_BASE_OFFSET))
    else
        console.log(string.format("[MEM] Party at EWRAM: count@0x%08X, base@0x%08X",
            M.PARTY_COUNT_ADDR, M.PARTY_BASE))
    end
    if M.CFRU_COMPRESSED_BOX then
        console.log(string.format("[MEM] CFRU compressed boxes: %d boxes, %d bytes/mon, storage@0x%08X",
            M.BOXES_PER_STORE, M.COMPRESSED_MON_SIZE, M.POKEMON_STORAGE_BASE))
    end
    if M.BASESTATS_ADDR then
        console.log(string.format("[MEM] gBaseStats at 0x%08X (entry size %d) — ability reading enabled",
            M.BASESTATS_ADDR, M.BASESTATS_ENTRY_SIZE))
    else
        console.log("[MEM] gBaseStats not available — ability reading via battle fallback only")
    end
end

-- ── Backward-compatibility shims for test scripts ─────────────────────────────
-- These allow test_*.lua scripts that call M.initProfile() / M.detectROM()
-- to continue working without modification.

function M.initProfile()
    local game_detect = require("game_detect")
    local detected = game_detect.detect()
    M.applyProfile(detected.profile, detected.variant)
end

function M.detectROM()
    local code = M.readGameCode()
    local base
    if     code == M.ROM_FIRERED_CODE   then base = "firered"
    elseif code == M.ROM_LEAFGREEN_CODE then base = "leafgreen"
    else                                     return "unknown"
    end
    if M.profile_name == "ap" then
        return base .. "_ap"
    elseif M.profile_name == "radical_red" then
        return base .. "_rr"
    end
    return base
end

-- Runtime sanity checks — call once on startup and after each save load.
-- Returns true, nil on success; false, error_string on failure.
-- Failure means the profile addresses are producing implausible values;
-- all memory WRITES should be disabled until this passes.
function M.validateROM()
    -- 0. Refresh ASLR-dependent party addresses (no-op if PARTY_IN_SB1=false)
    M.refreshPartyAddrs()
    -- 0b. If PARTY_IN_SB1 and addresses are still 0, SB1 pointer isn't valid yet
    if M.PARTY_IN_SB1 and M.PARTY_BASE == 0 then
        return false, "SB1 pointer not in EWRAM yet — save may not be loaded"
    end
    -- 1. Party count must be 0–6
    local count = memory.read_u8(M.PARTY_COUNT_ADDR)
    if count > 6 then
        return false, string.format(
            "gPlayerPartyCount=%d (expected 0-6) at 0x%08X — wrong profile (%s)?",
            count, M.PARTY_COUNT_ADDR, M.profile_name)
    end
    -- 2. gSaveBlock1Ptr must point into EWRAM (0x02000000–0x0203FFFF)
    local sb1 = memory.read_u32_le(M.SB1_PTR_ADDR)
    if sb1 < 0x02000000 or sb1 >= 0x02040000 then
        return false, string.format(
            "gSaveBlock1Ptr=0x%08X not in EWRAM (ptr at 0x%08X, profile=%s)",
            sb1, M.SB1_PTR_ADDR, M.profile_name)
    end
    -- 3. gPokemonStoragePtr must also point into EWRAM (skip if not yet known)
    if M.PSP_PTR_ADDR and M.PSP_PTR_ADDR ~= 0 then
        local psp = memory.read_u32_le(M.PSP_PTR_ADDR)
        if psp < 0x02000000 or psp >= 0x02040000 then
            return false, string.format(
                "gPokemonStoragePtr=0x%08X not in EWRAM (ptr at 0x%08X, profile=%s)",
                psp, M.PSP_PTR_ADDR, M.profile_name)
        end
    end
    -- 4. mapGroup/mapNum should be within known bounds
    local mapGroup = memory.read_u8(sb1 + 0x0004)
    local mapNum   = memory.read_u8(sb1 + 0x0005)
    if mapGroup > 42 or mapNum > 199 then
        return false, string.format(
            "mapGroup=%d mapNum=%d outside known bounds (profile=%s)",
            mapGroup, mapNum, M.profile_name)
    end
    -- 5. AP-specific: verify gMain overworld field is plausible (0 or 1)
    if M._overworld_mode == "gmain_038" then
        local ow = memory.read_u8(M.GMAIN_ADDR + 0x038)
        if ow > 1 then
            return false, string.format(
                "gMain+0x038=%d (expected 0 or 1) — AP overworld flag invalid", ow)
        end
    end
    -- 6. Bag pocket sanity: item IDs in the Pokéball pocket should be 0 or valid
    --    ball IDs. Detect corrupt/shifted reads.
    --    Valid ball IDs: 0 (empty), 1-12 (Master..Premier), 52-53 (Park/Cherish),
    --    60-62 (Dusk/Heal/Quick), 622-631 (CFRU Apricorn/Beast/Dream).
    --    Upper bound 700 covers all known balls with margin.
    local ball_base
    local ball_count = M.SB1_BALL_POCKET_COUNT
    if M.BAG_IN_EWRAM then
        ball_base = M.BALL_POCKET_ADDR
    else
        ball_base = sb1 + M.SB1_BALL_POCKET_OFFSET
    end
    for i = 0, ball_count - 1 do
        local itemId = memory.read_u16_le(ball_base + i * 4)
        if itemId > 700 then
            return false, string.format(
                "bagPocket_PokeBalls[%d].itemId=%d (>700) — pocket offset may be wrong (profile=%s)",
                i, itemId, M.profile_name)
        end
    end
    -- 7. SB2 encryptionKey sanity: should be non-zero when save is loaded
    --    (Skip for profiles where bag encryption is disabled, e.g. CFRU/RR.)
    if M.SB2_PTR_ADDR and M.SB2_PTR_ADDR ~= 0 and M.BALL_POCKET_ENC ~= false then
        local sb2 = memory.read_u32_le(M.SB2_PTR_ADDR)
        if sb2 >= 0x02000000 and sb2 < 0x02040000 then
            local encKey = memory.read_u32_le(sb2 + M.SB2_ENC_KEY_OFFSET)
            if encKey == 0 then
                console.log(string.format(
                    "[MEM] WARNING: SB2 encryptionKey=0 at +0x%04X (profile=%s) — save may not be loaded yet",
                    M.SB2_ENC_KEY_OFFSET, M.profile_name))
            end
        end
    end
    -- 8. CFRU compressed box sanity: verify currentBox in range and at least one
    --    box base is in EWRAM (catches wrong POKEMON_STORAGE_BASE).
    if M.CFRU_COMPRESSED_BOX and M.POKEMON_STORAGE_BASE then
        local curBox = memory.read_u8(M.POKEMON_STORAGE_BASE)
        if curBox >= M.BOXES_PER_STORE then
            return false, string.format(
                "CFRU currentBox=%d (>=%d) at 0x%08X — POKEMON_STORAGE_BASE may be wrong",
                curBox, M.BOXES_PER_STORE, M.POKEMON_STORAGE_BASE)
        end
    end
    -- 9. CFRU/RR save-loaded guard (best-effort).
    --    CFRU fully initialises save blocks + party at boot, making title screen
    --    indistinguishable from overworld in RAM.  This check catches the "no save
    --    exists" case (zeroed SB2 buffer) and the early-boot case (pointer not set).
    --    For existing saves, writes_enabled will be true at the title screen —
    --    users must load the script after entering the game.
    if M.CFRU_NO_ENCRYPT and M.SB2_PTR_ADDR and M.SB2_PTR_ADDR ~= 0 then
        local sb2 = memory.read_u32_le(M.SB2_PTR_ADDR)
        if sb2 < 0x02000000 or sb2 >= 0x02040000 then
            return false, string.format(
                "CFRU SB2 ptr=0x%08X not in EWRAM — not ready", sb2)
        end
        local name0 = memory.read_u8(sb2)
        if name0 == 0 or name0 == 0xFF then
            return false, string.format(
                "CFRU trainer name[0]=0x%02X — save not loaded yet", name0)
        end
    end
    return true, nil
end

-- ── PARTY_IN_SB1 support (CFRU/RR) ──────────────────────────────────────────
-- In CFRU/RR, the player party data is embedded inside SaveBlock1 (behind ASLR).
-- M.refreshPartyAddrs() recomputes PARTY_BASE from the SB1 pointer each frame.
-- PARTY_COUNT_ADDR is a fixed EWRAM global (not in SB1) and does NOT need refresh.
-- For vanilla/AP (PARTY_IN_SB1 = false), this is a no-op.
M.PARTY_IN_SB1 = false               -- overridden by RR profile
M.SB1_PARTY_BASE_OFFSET  = nil       -- set by RR profile

function M.refreshPartyAddrs()
    if not M.PARTY_IN_SB1 then return end
    local sb1 = mem_r32(M.SB1_PTR_ADDR)
    -- Guard: SB1 pointer must be in EWRAM range; before save loads it's garbage
    if sb1 < 0x02000000 or sb1 >= 0x02040000 then
        M.PARTY_BASE = 0
        return
    end
    M.PARTY_BASE = sb1 + M.SB1_PARTY_BASE_OFFSET
end

-- ── Profile-independent constants ──────────────────────────────────────────────
-- Struct sizes and field offsets are data layout, not RAM addresses — identical
-- across vanilla and AP ROMs.

M.MON_SIZE         = 0x64        -- sizeof(struct Pokemon) = 100 bytes

-- Battle type bit masks and outcome constants
-- OUTCOME_CAUGHT is profile-dependent: vanilla/AP=6, CFRU/RR=7.
-- Default is set here; initProfile() overrides if the profile specifies a value.
M.BATTLE_TYPE_TRAINER_MASK  = 0x08        -- bit 3: standard trainer battles
M.BATTLE_TYPE_FIRST_MASK    = 0x10        -- bit 4: first rival battle (also a trainer)
-- Borrowed-party battle types (CFRU/RR) — the game temporarily replaces the
-- player's party with another trainer's mons.  All party diffing, capture, and
-- faint detection must be frozen while any of these flags are set.
-- NOTE: INGAME_PARTNER (0x400000) is NOT included — that's for tag/multi
-- battles where your party stays intact and an NPC fights alongside you.
M.BATTLE_TYPE_POKE_DUDE     = 0x10000     -- Poké Dude tutorial
M.BATTLE_TYPE_MOCK_BATTLE   = 0x1000000   -- scripted mock battle
M.BATTLE_TYPE_BORROWED_MASK = 0x1010000   -- Poké Dude | Mock Battle
M.OUTCOME_WON               = 1           -- B_OUTCOME_WON_BATTLE
M.OUTCOME_LOST              = 2           -- B_OUTCOME_LOST_BATTLE (whiteout)
M.OUTCOME_RAN               = 3           -- B_OUTCOME_RAN (vanilla/AP); CFRU inserts DREW=3, shifting RAN to 4
M.OUTCOME_CAUGHT            = 6           -- B_OUTCOME_CAUGHT_MON (vanilla/AP default)

-- gBattleMons struct layout (profile-independent sizes/offsets)
M.BATTLE_MON_SIZE            = 0x58        -- sizeof(struct BattlePokemon) = 88 bytes
M.BATTLE_MON_HP_OFF          = 0x28        -- BattlePokemon.hp offset (u16)

-- gMain inBattle bit mask (used in vanilla mode)
M.GMAIN_INBATTLE_MASK = 0x02              -- bit 1 = inBattle

-- Returns the player-side battler index (0 or 2) that corresponds to the given
-- party slot, or -1 if that slot is not currently on the field.
function M.getBattlerForPartySlot(slot)
    if not M.BATTLER_PARTY_INDEXES_ADDR or not M.BATTLERS_COUNT_ADDR then return -1 end
    local idx0 = memory.read_u16_le(M.BATTLER_PARTY_INDEXES_ADDR)
    if idx0 == slot then return 0 end
    if memory.read_u8(M.BATTLERS_COUNT_ADDR) >= 4 then
        local idx2 = memory.read_u16_le(M.BATTLER_PARTY_INDEXES_ADDR + 4)
        if idx2 == slot then return 2 end
    end
    return -1
end

-- ── Overworld / in-battle detection ──────────────────────────────────────────
-- Vanilla:         gMain+0x439 bit 1 = inBattle flag.
-- AP:              gMain+0x038 == 1 means overworld; three-condition battle check.
-- RR/CFRU:         gBattleMons[0].maxHP > 0 AND gBattleOutcome == 0.
--                  Does NOT require gMain (unreliable on RR).
-- M._overworld_mode is set by initProfile().

function M.isInBattle()
    if M._overworld_mode == "gmain_038" then
        -- AP mode: three-condition check
        local not_overworld = mem_r8(M.GMAIN_ADDR + 0x038) ~= 1
        if not M.BATTLE_TYPE_ADDR or not M.BATTLE_OUTCOME_ADDR then
            return not_overworld
        end
        return not_overworld
           and mem_r32(M.BATTLE_TYPE_ADDR) ~= 0
           and mem_r8(M.BATTLE_OUTCOME_ADDR) == 0
    elseif M._overworld_mode == "battle_outcome" then
        -- RR/CFRU mode: gBattleMons[0].maxHP > 0 means battle data is loaded;
        -- gBattleOutcome == 0 means battle is still active (not resolved yet).
        -- Before the first battle, gBattleMons is zeroed → maxHP=0 → false.
        -- After battle ends, gBattleOutcome becomes 1/4/7 → false.
        if not M.BATTLE_MONS_ADDR or not M.BATTLE_OUTCOME_ADDR then return false end
        local bmon_maxHP = mem_r16(M.BATTLE_MONS_ADDR + M.BATTLE_MON_HP_OFF + 4)  -- maxHP at hp+4 (0x2C; CFRU BattlePokemon.maxHP)
        return bmon_maxHP > 0 and mem_r8(M.BATTLE_OUTCOME_ADDR) == 0
    else
        -- Vanilla mode: gMain+0x439 bit 1
        if not M.GMAIN_ADDR or M.GMAIN_ADDR == 0 then return false end
        return (mem_r8(M.GMAIN_ADDR + 0x439) & M.GMAIN_INBATTLE_MASK) ~= 0
    end
end

function M.isInOverworld()
    if M._overworld_mode == "gmain_038" then
        return mem_r8(M.GMAIN_ADDR + 0x038) == 1
    elseif M._overworld_mode == "battle_outcome" then
        -- "Not in battle" is necessary but NOT sufficient for safe writes.
        -- The game can be in menus, evolution screens, move-learn prompts, etc.
        -- For safe-state gating in client.lua, use isSafeOverworld() instead.
        return not M.isInBattle()
    else
        return not M.isInBattle()
    end
end

-- ── SaveBlock struct offsets (profile-dependent) ─────────────────────────────
-- AP recompiles the binary; struct fields may shift relative to vanilla.
-- Vanilla values from pret/pokefirered include/global.h.
-- AP values confirmed from vyneras/Archipelago worlds/pokemon_frlg/client.py.
--
-- SB2 encryptionKey: vanilla +0x0F20, AP +0x0F2A (10 bytes added before it).
-- SB1 bag pocket offsets: identical layout confirmed (AP does not expand pockets).
-- These are set by applyProfile() from the game module's profile; defaults for safety.
M.SB2_ENC_KEY_OFFSET     = 0x0F20
M.SB1_BALL_POCKET_OFFSET = 0x0430
M.SB1_BALL_POCKET_COUNT  = 13

-- CFRU/RR bag model: ball pocket lives in EWRAM, not inside SaveBlock1.
-- When BAG_IN_EWRAM is true, hasPokeballs()/countPokeballs() read from
-- BALL_POCKET_ADDR directly instead of SB1+offset.
-- Vanilla/AP profiles leave these at defaults; RR profile overrides them.
M.BAG_IN_EWRAM     = false
M.BALL_POCKET_ADDR = 0       -- absolute EWRAM address (only used when BAG_IN_EWRAM)
M.BALL_POCKET_ENC  = false   -- true if EWRAM bag quantities are XOR-encrypted

-- CFRU substruct model: substructs are stored in FIXED order (Growth, Attacks,
-- EVs, Misc) and are NOT XOR-encrypted.  Species is raw u16 at +0x20, held item
-- at +0x22.  Vanilla/AP use permuted+encrypted substructs.
M.CFRU_NO_ENCRYPT  = false

-- ── gBaseStats ROM table ─────────────────────────────────────────────────────
-- Used to resolve ability IDs from species + abilityBit.
-- Vanilla/AP: hardcoded address.  RR/CFRU: dereferenced from ROM pointer.
M.BASESTATS_ADDR       = nil   -- set by initProfile(); nil = ability reading disabled
M.BASESTATS_ENTRY_SIZE = 28    -- sizeof(struct BaseStats) with padding

-- ── struct Pokemon field offsets ──────────────────────────────────────────────
-- BoxPokemon (first 80 bytes, shared with PC):
M.OFF_PERSONALITY = 0x00   -- u32, unencrypted
M.OFF_OTID        = 0x04   -- u32, unencrypted
M.OFF_NICKNAME    = 0x08   -- u8[10], Gen III character encoding, unencrypted
M.OFF_FLAGS       = 0x13   -- u8: bit0=isBadEgg, bit1=hasSpecies, bit2=isEgg
M.OFF_CHECKSUM    = 0x1C   -- u16, covers encrypted section
M.OFF_SUBSTRUCT   = 0x20   -- u8[48], XOR-encrypted (key = personality XOR otId)
-- Party-only fields (bytes 80–99):
M.OFF_STATUS      = 0x50   -- u32, unencrypted (0 = no status)
M.OFF_LEVEL       = 0x54   -- u8,  unencrypted
M.OFF_HP          = 0x56   -- u16, unencrypted ← read/write for faint detection
M.OFF_MAX_HP      = 0x58   -- u16, unencrypted

-- ── struct PokemonStorage ─────────────────────────────────────────────────────
M.BOX_MON_SIZE    = 0x50   -- sizeof(BoxPokemon) = 80 bytes (vanilla/AP)
M.BOXES_PER_STORE = 14
M.MONS_PER_BOX    = 30
M.MEMORIAL_BOX    = 13     -- default: last box (0-indexed). Updated by initProfile().
M.BOX_DATA_OFFSET = 0x0004 -- offset from PokemonStorage to first BoxPokemon
                            -- CFRU/RR: 0x0001 (currentBox is u8 at +0x0000, boxes at +0x0001)
M.BOX_SB1_OFFSET  = nil    -- if set, box[0][0] = SB1 + offset (DPE: no PSP pointer)

-- CFRU compressed box storage (set by initProfile if CFRU_COMPRESSED_BOX)
M.CFRU_COMPRESSED_BOX   = false   -- true = boxes use 58-byte CompressedPokemon
M.COMPRESSED_MON_SIZE   = nil     -- 0x3A (58 bytes) when compressed
M.CFRU_BOX_BASES        = nil     -- table of 25 precomputed box base addresses
M.POKEMON_STORAGE_BASE  = nil     -- PokemonStorage struct base (currentBox at +0x00)
M.CFRU_BOX_NAME_BASE    = nil     -- ORIGINAL_BOX_NAME_RAM for CFRU name computation

-- PokemonStorage.boxNames: 14 names × 9 bytes (8 chars + 0xFF terminator).
-- Vanilla/AP: +0x0004 (boxes) + 14*30*80 = +0x8344.
-- CFRU/RR: +0x0001 (boxes) + 14*30*80 = +0x8341 — but CFRU source confirms +0x8344 (3 pad bytes).
M.BOX_NAMES_OFFSET = 0x8344
M.BOX_NAME_SIZE    = 9      -- BOX_NAME_LENGTH(8) + 1 terminator

-- ── Substruct permutation table (personality % 24 → substruct order) ──────────
-- Each entry is {G,A,E,M} where G=Growth(species), A=Attacks, E=EVs, M=Misc.
-- We only need index 0 (Growth substruct, contains species u16 at offset +0x00).
M.SUBSTRUCT_ORDER = {
    --  0        1        2        3        4        5
    {0,1,2,3},{0,1,3,2},{0,2,1,3},{0,2,3,1},{0,3,1,2},{0,3,2,1},
    --  6        7        8        9       10       11
    {1,0,2,3},{1,0,3,2},{2,0,1,3},{3,0,1,2},{2,0,3,1},{3,0,2,1},
    -- 12       13       14       15       16       17
    {1,2,0,3},{1,3,0,2},{2,1,0,3},{3,1,0,2},{2,3,0,1},{3,2,0,1},
    -- 18       19       20       21       22       23
    {1,2,3,0},{1,3,2,0},{2,1,3,0},{3,1,2,0},{2,3,1,0},{3,2,1,0},
}

-- ── Low-level helpers ─────────────────────────────────────────────────────────

-- Returns the stable identity key for a party/box slot.
-- Survives slot reorders, box deposits, evolutions, and server reconnects.
function M.monKey(base_addr)
    local p = mem_r32(base_addr + M.OFF_PERSONALITY)
    local o = mem_r32(base_addr + M.OFF_OTID)
    return fmt("%08X:%08X", p, o)
end

function M.slotOccupied(base_addr)
    local flags = mem_r8(base_addr + M.OFF_FLAGS)
    local maxHP = mem_r16(base_addr + M.OFF_MAX_HP)
    return (flags & 0x02) ~= 0 and maxHP > 0
end

function M.boxSlotOccupied(base_addr)
    local flags = mem_r8(base_addr + M.OFF_FLAGS)
    return (flags & 0x02) ~= 0
end

-- FRLG character encoding: map byte values → ASCII characters.
-- 0xFF = end-of-string marker.  Unknown bytes decode as "?".
local _CHARSET = {
    [0xBB]="A",[0xBC]="B",[0xBD]="C",[0xBE]="D",[0xBF]="E",
    [0xC0]="F",[0xC1]="G",[0xC2]="H",[0xC3]="I",[0xC4]="J",
    [0xC5]="K",[0xC6]="L",[0xC7]="M",[0xC8]="N",[0xC9]="O",
    [0xCA]="P",[0xCB]="Q",[0xCC]="R",[0xCD]="S",[0xCE]="T",
    [0xCF]="U",[0xD0]="V",[0xD1]="W",[0xD2]="X",[0xD3]="Y",[0xD4]="Z",
    [0xD5]="a",[0xD6]="b",[0xD7]="c",[0xD8]="d",[0xD9]="e",
    [0xDA]="f",[0xDB]="g",[0xDC]="h",[0xDD]="i",[0xDE]="j",
    [0xDF]="k",[0xE0]="l",[0xE1]="m",[0xE2]="n",[0xE3]="o",
    [0xE4]="p",[0xE5]="q",[0xE6]="r",[0xE7]="s",[0xE8]="t",
    [0xE9]="u",[0xEA]="v",[0xEB]="w",[0xEC]="x",[0xED]="y",[0xEE]="z",
    [0xA1]="0",[0xA2]="1",[0xA3]="2",[0xA4]="3",[0xA5]="4",
    [0xA6]="5",[0xA7]="6",[0xA8]="7",[0xA9]="8",[0xAA]="9",
    [0xAB]="!",[0xAC]="?",[0xAD]=".",[0xAE]="-",[0xAF]="·",
    [0xB0]="…",[0xB1]="«",[0xB2]="»",
    [0xB3]="'",[0xB4]="'",[0xB5]="♂",[0xB6]="♀",
    [0xB8]="$",[0xB9]=",",[0xBA]="/",
    [0x00]=" ",  -- space in US/English FRLG
}

-- Reverse lookup: ASCII character → FRLG byte value (for encoding strings to RAM).
local _CHARSET_REV = {}
for byte, char in pairs(_CHARSET) do _CHARSET_REV[char] = byte end

-- Decodes a FRLG-encoded string at addr up to max_len bytes.
-- Stops at 0xFF (EOS). Unknown bytes decode as "?". Trailing spaces are stripped.
function M.decodeString(addr, max_len)
    local chars = {}
    for i = 0, max_len - 1 do
        local b = mem_r8(addr + i)
        if b == 0xFF then break end
        chars[#chars + 1] = _CHARSET[b] or "?"
    end
    return (table.concat(chars):gsub("%s+$", ""))
end

-- Reads the FRLG-encoded nickname from a party or box slot.
function M.readNickname(base_addr)
    return M.decodeString(base_addr + M.OFF_NICKNAME, 10)
end

-- Reads the player's trainer name via the SaveBlock2 pointer chain.
-- playerName is the first field in SaveBlock2 (offset 0x0000), up to 7 chars.
function M.readTrainerName()
    local sb2 = memory.read_u32_le(M.SB2_PTR_ADDR)
    return M.decodeString(sb2, 7)
end

-- Reads the fields we need from one party slot (index 0–5).
-- nickname, species_id, and held_item_id use pcall guards so decrypt failures cannot crash callers.
function M.readPartySlot(slot)
    local base = M.PARTY_BASE + slot * M.MON_SIZE
    if not M.slotOccupied(base) then return nil end
    local ok_n, nick = pcall(M.readNickname,    base)
    local ok_s, sid  = pcall(M.decryptSpecies,  base)
    local ok_i, iid  = pcall(M.decryptHeldItem, base)
    local ok_a, aid  = pcall(M.getAbilityId,    base)
    return {
        slot         = slot,
        key          = M.monKey(base),
        hp           = mem_r16(base + M.OFF_HP),
        maxHP        = mem_r16(base + M.OFF_MAX_HP),
        level        = mem_r8(base + M.OFF_LEVEL),
        personality  = mem_r32(base + M.OFF_PERSONALITY),
        otId         = mem_r32(base + M.OFF_OTID),
        nickname     = ok_n and nick or "",
        species_id   = ok_s and sid  or 0,
        held_item_id = ok_i and iid  or 0,
        ability_id   = ok_a and aid  or 0,
    }
end

-- Reads all occupied party slots; returns array of slot tables.
function M.readParty()
    local count  = mem_r8(M.PARTY_COUNT_ADDR)
    local party  = {}
    for i = 0, count - 1 do
        local s = M.readPartySlot(i)
        if s then party[#party + 1] = s end
    end
    return party
end

-- Decrypts the species (u16) from a BoxPokemon located at base_addr.
-- CFRU: substructs are unencrypted, fixed order → raw u16 at +0x20.
-- Vanilla/AP: 48-byte data section at +0x20 is XOR'd with (personality XOR otId).
function M.decryptSpecies(base_addr)
    if M.CFRU_NO_ENCRYPT then
        return mem_r16(base_addr + M.OFF_SUBSTRUCT)
    end
    local personality = mem_r32(base_addr + M.OFF_PERSONALITY)
    local otId        = mem_r32(base_addr + M.OFF_OTID)
    local key         = personality ~ otId
    local perm  = M.SUBSTRUCT_ORDER[(personality % 24) + 1]
    local growth_pos = perm[1]
    local sub_base = base_addr + M.OFF_SUBSTRUCT + growth_pos * 12
    local w0 = mem_r32(sub_base + 0) ~ key
    return w0 & 0xFFFF
end

function M.decryptHeldItem(base_addr)
    if M.CFRU_NO_ENCRYPT then
        return mem_r16(base_addr + M.OFF_SUBSTRUCT + 2)
    end
    local personality = mem_r32(base_addr + M.OFF_PERSONALITY)
    local otId        = mem_r32(base_addr + M.OFF_OTID)
    local key         = personality ~ otId
    local perm        = M.SUBSTRUCT_ORDER[(personality % 24) + 1]
    local growth_pos  = perm[1]
    local sub_base    = base_addr + M.OFF_SUBSTRUCT + growth_pos * 12
    local w0          = mem_r32(sub_base + 0) ~ key
    return (w0 >> 16) & 0xFFFF
end

-- Resolves the ability ID for a party/box mon by reading gBaseStats from ROM.
-- Returns the ability ID (u8), or 0 if gBaseStats is unavailable.
--
-- Logic:
--   1. Read the "abilityBit" (bit 31 of the IVs dword in substruct3/Misc).
--      - CFRU: this is the "hiddenAbility" flag.  1 → hidden, 0 → normal.
--      - Vanilla/AP: this is "altAbility".  Selects ability1 (0) or ability2 (1).
--   2. Look up gBaseStats[species]:
--      - ability1 at +0x16, ability2 at +0x17, hiddenAbility at +0x1A (CFRU only)
--   3. For CFRU: if hiddenAbility bit → gBaseStats[species].hiddenAbility
--                else → gBaseStats[species].abilities[personality & 1]
--      For vanilla/AP: → gBaseStats[species].abilities[abilityBit]
function M.getAbilityId(base_addr)
    if not M.BASESTATS_ADDR then return 0 end
    local species = M.decryptSpecies(base_addr)
    if not species or species == 0 then return 0 end
    local personality = mem_r32(base_addr + M.OFF_PERSONALITY)
    -- Read abilityBit from substruct3 (Misc) IVs dword, bit 31
    local ivs_dword
    if M.CFRU_NO_ENCRYPT then
        -- CFRU: fixed order, Misc at substruct position 3
        ivs_dword = mem_r32(base_addr + M.OFF_SUBSTRUCT + 3 * 12 + 4)
    else
        -- Vanilla/AP: find Misc substruct via permutation table
        local otId = mem_r32(base_addr + M.OFF_OTID)
        local key  = personality ~ otId
        local perm = M.SUBSTRUCT_ORDER[(personality % 24) + 1]
        local misc_pos = perm[4]  -- 4th element = Misc substruct position
        local misc_base = base_addr + M.OFF_SUBSTRUCT + misc_pos * 12
        -- Decrypt: IVs dword is at misc+4 (bytes 4-7 of the 12-byte substruct)
        ivs_dword = mem_r32(misc_base + 4) ~ key
    end
    local ability_bit = (ivs_dword >> 31) & 1
    -- Look up in gBaseStats ROM table
    local entry_addr = M.BASESTATS_ADDR + species * M.BASESTATS_ENTRY_SIZE
    local aid
    if M.CFRU_NO_ENCRYPT and ability_bit == 1 then
        -- CFRU hidden ability at +0x1A
        aid = mem_r8(entry_addr + 0x1A)
    else
        -- Normal ability: vanilla uses abilityBit, CFRU uses personality & 1
        local slot = M.CFRU_NO_ENCRYPT and (personality % 2) or ability_bit
        aid = mem_r8(entry_addr + 0x16 + slot)
        -- ability2 == 0 means "same as ability1" — fall back
        if aid == 0 and slot == 1 then
            aid = mem_r8(entry_addr + 0x16)
        end
    end
    return aid
end

-- ── CFRU CompressedPokemon box slot readers ──────────────────────────────────
-- CompressedPokemon (58 bytes) stores species at +0x1C, heldItem at +0x1E.
-- These differ from party/BoxPokemon where species is at +0x20 (substruct0).
-- For vanilla/AP (80-byte BoxPokemon), delegate to decryptSpecies/decryptHeldItem.

function M.decryptBoxSpecies(box_addr)
    if M.CFRU_COMPRESSED_BOX then
        return mem_r16(box_addr + 0x1C)
    end
    return M.decryptSpecies(box_addr)
end

function M.decryptBoxHeldItem(box_addr)
    if M.CFRU_COMPRESSED_BOX then
        return mem_r16(box_addr + 0x1E)
    end
    return M.decryptHeldItem(box_addr)
end

-- Resolves ability ID from a box slot (handles both CompressedPokemon and BoxPokemon).
function M.getBoxAbilityId(box_addr)
    if not M.BASESTATS_ADDR then return 0 end
    local species
    if M.CFRU_COMPRESSED_BOX then
        species = mem_r16(box_addr + 0x1C)
    else
        species = M.decryptSpecies(box_addr)
    end
    if not species or species == 0 then return 0 end
    local personality = mem_r32(box_addr + M.OFF_PERSONALITY)
    -- Read IVs dword for abilityBit (bit 31)
    local ivs_dword
    if M.CFRU_COMPRESSED_BOX then
        -- CompressedPokemon: ivs at +0x36 (pokerus+metLoc+metInfo = 4 bytes at +0x32, then ivs)
        ivs_dword = mem_r32(box_addr + 0x36)
    elseif M.CFRU_NO_ENCRYPT then
        -- CFRU BoxPokemon (uncompressed): same layout as party
        ivs_dword = mem_r32(box_addr + M.OFF_SUBSTRUCT + 3 * 12 + 4)
    else
        -- Vanilla/AP: encrypted substructs
        local otId = mem_r32(box_addr + M.OFF_OTID)
        local key  = personality ~ otId
        local perm = M.SUBSTRUCT_ORDER[(personality % 24) + 1]
        local misc_pos = perm[4]
        ivs_dword = mem_r32(box_addr + M.OFF_SUBSTRUCT + misc_pos * 12 + 4) ~ key
    end
    local ability_bit = (ivs_dword >> 31) & 1
    local entry_addr = M.BASESTATS_ADDR + species * M.BASESTATS_ENTRY_SIZE
    local aid
    if (M.CFRU_NO_ENCRYPT or M.CFRU_COMPRESSED_BOX) and ability_bit == 1 then
        aid = mem_r8(entry_addr + 0x1A)
    else
        local slot = (M.CFRU_NO_ENCRYPT or M.CFRU_COMPRESSED_BOX) and (personality % 2) or ability_bit
        aid = mem_r8(entry_addr + 0x16 + slot)
        if aid == 0 and slot == 1 then
            aid = mem_r8(entry_addr + 0x16)
        end
    end
    return aid
end

-- Reads the 4 move IDs and 4 PP values from a party slot.
-- Returns moves = {id1, id2, id3, id4}, pp = {pp1, pp2, pp3, pp4}.
-- CFRU: unencrypted Attacks substruct at base+0x2C.
-- Vanilla/AP: permuted + encrypted Attacks substruct.
function M.decryptMoves(base_addr)
    local moves = {0,0,0,0}
    local pp    = {0,0,0,0}
    if M.CFRU_NO_ENCRYPT then
        -- CFRU: fixed order, Attacks substruct at +0x2C
        for i = 0, 3 do
            moves[i+1] = mem_r16(base_addr + 0x2C + i * 2)
        end
        for i = 0, 3 do
            pp[i+1] = mem_r8(base_addr + 0x34 + i)
        end
    else
        -- Vanilla/AP: find Attacks substruct via permutation table, decrypt
        local personality = mem_r32(base_addr + M.OFF_PERSONALITY)
        local otId        = mem_r32(base_addr + M.OFF_OTID)
        local key         = personality ~ otId
        local perm        = M.SUBSTRUCT_ORDER[(personality % 24) + 1]
        local atk_pos     = perm[2]  -- Attacks is element 2 in {G,A,E,M}
        local sub_base    = base_addr + M.OFF_SUBSTRUCT + atk_pos * 12
        -- Decrypt the 12-byte Attacks substruct (3 dwords)
        local w0 = mem_r32(sub_base + 0) ~ key
        local w1 = mem_r32(sub_base + 4) ~ key
        local w2 = mem_r32(sub_base + 8) ~ key
        -- Moves: 4 × u16 (first 8 bytes)
        moves[1] = w0 & 0xFFFF
        moves[2] = (w0 >> 16) & 0xFFFF
        moves[3] = w1 & 0xFFFF
        moves[4] = (w1 >> 16) & 0xFFFF
        -- PP: 4 × u8 (next 4 bytes)
        pp[1] = w2 & 0xFF
        pp[2] = (w2 >> 8) & 0xFF
        pp[3] = (w2 >> 16) & 0xFF
        pp[4] = (w2 >> 24) & 0xFF
    end
    return moves, pp
end

-- Reads move IDs from a box slot.
-- CFRU CompressedPokemon: 10-bit packed bitfields at +0x27 (no PP stored).
-- CFRU BoxPokemon: same as party (unencrypted at +0x2C).
-- Vanilla/AP: encrypted substructs (same decrypt as party).
-- Returns moves = {id1, id2, id3, id4}. No PP for box mons.
function M.decryptBoxMoves(box_addr)
    local moves = {0,0,0,0}
    if M.CFRU_COMPRESSED_BOX then
        -- CompressedPokemon: 4 moves as 10-bit bitfields in 5 bytes at +0x27
        local b0 = mem_r8(box_addr + 0x27)
        local b1 = mem_r8(box_addr + 0x28)
        local b2 = mem_r8(box_addr + 0x29)
        local b3 = mem_r8(box_addr + 0x2A)
        local b4 = mem_r8(box_addr + 0x2B)
        local packed = b0 | (b1 << 8) | (b2 << 16) | (b3 << 24) | (b4 << 32)
        moves[1] = packed & 0x3FF
        moves[2] = (packed >> 10) & 0x3FF
        moves[3] = (packed >> 20) & 0x3FF
        moves[4] = (packed >> 30) & 0x3FF
    elseif M.CFRU_NO_ENCRYPT then
        -- CFRU BoxPokemon (uncompressed): same layout as party
        for i = 0, 3 do
            moves[i+1] = mem_r16(box_addr + 0x2C + i * 2)
        end
    else
        -- Vanilla/AP: encrypted substructs
        local personality = mem_r32(box_addr + M.OFF_PERSONALITY)
        local otId        = mem_r32(box_addr + M.OFF_OTID)
        local key         = personality ~ otId
        local perm        = M.SUBSTRUCT_ORDER[(personality % 24) + 1]
        local atk_pos     = perm[2]
        local sub_base    = box_addr + M.OFF_SUBSTRUCT + atk_pos * 12
        local w0 = mem_r32(sub_base + 0) ~ key
        local w1 = mem_r32(sub_base + 4) ~ key
        moves[1] = w0 & 0xFFFF
        moves[2] = (w0 >> 16) & 0xFFFF
        moves[3] = w1 & 0xFFFF
        moves[4] = (w1 >> 16) & 0xFFFF
    end
    return moves
end

-- Returns the effective box slot size for the active profile.
function M.boxSlotSize()
    if M.CFRU_COMPRESSED_BOX then
        return M.COMPRESSED_MON_SIZE
    end
    return M.BOX_MON_SIZE
end

-- ── CFRU Party ↔ CompressedPokemon conversion ────────────────────────────────
-- Byte-perfect conversion matching CFRU's CreateCompressedMonFromBoxMon() and
-- CreateBoxMonFromCompressedMon() in src/pokemon_storage_system.c.
--
-- CompressedPokemon layout (58 bytes, packed):
--   +0x00: header (28 bytes) — identical to BoxPokemon header
--   +0x1C: species(u16), heldItem(u16), exp(u32), ppBonuses(u8),
--          friendship(u8), pokeball(u8)                          [11 bytes]
--   +0x27: 4 moves packed as 10-bit bitfields                   [5 bytes]
--   +0x2C: 6 EV bytes                                           [6 bytes]
--   +0x32: pokerus(u8), metLocation(u8), metInfo(u16), ivs(u32) [8 bytes]
--
-- Party Pokemon layout (100 bytes, CFRU unencrypted fixed-order substructs):
--   +0x00: header (28 bytes)
--   +0x1C: checksum (u16) + padding (u16)
--   +0x20: Growth substruct (12 bytes): species, item, exp, ppBonuses, friendship, pokeball, pad
--   +0x2C: Attacks substruct (12 bytes): moves[4](u16), pp[4](u8)
--   +0x38: EVs substruct (12 bytes): hp/atk/def/spd/spatk/spdef evs, then 6 contest bytes
--   +0x44: Misc substruct (12 bytes): pokerus, metLoc, metInfo, ivs, ribbons(4)

-- Converts a party Pokemon (100 bytes at srcAddr) to a CompressedPokemon
-- (58 bytes) written at dstAddr. Matches CFRU's CreateCompressedMonFromBoxMon.
function M.createCompressedMon(srcAddr, dstAddr)
    -- Zero destination
    for i = 0, M.COMPRESSED_MON_SIZE - 1 do mem_w8(dstAddr + i, 0) end
    -- Copy header (28 bytes: personality, otId, nickname, language, sanity, otName, markings)
    for i = 0, 0x1B do mem_w8(dstAddr + i, mem_r8(srcAddr + i)) end
    -- Copy CompressedPokemonSubstruct0 (11 bytes from Growth substruct)
    -- src+0x20: species(2), item(2), exp(4), ppBonuses(1), friendship(1), pokeball(1)
    for i = 0, 10 do mem_w8(dstAddr + 0x1C + i, mem_r8(srcAddr + 0x20 + i)) end
    -- Pack moves as 10-bit bitfields (40 bits = 5 bytes at dst+0x27)
    -- Source: Attacks substruct at src+0x2C: moves[0..3] as u16 each
    local m1 = mem_r16(srcAddr + 0x2C)
    local m2 = mem_r16(srcAddr + 0x2E)
    local m3 = mem_r16(srcAddr + 0x30)
    local m4 = mem_r16(srcAddr + 0x32)
    -- Mask to 10 bits each
    m1 = m1 & 0x3FF
    m2 = m2 & 0x3FF
    m3 = m3 & 0x3FF
    m4 = m4 & 0x3FF
    -- Pack: m1[9:0] | m2[9:0]<<10 | m3[9:0]<<20 | m4[9:0]<<30
    -- This gives a 40-bit value; write as 5 little-endian bytes
    local packed = m1 | (m2 << 10) | (m3 << 20) | (m4 << 30)
    mem_w8(dstAddr + 0x27, packed & 0xFF)
    mem_w8(dstAddr + 0x28, (packed >> 8) & 0xFF)
    mem_w8(dstAddr + 0x29, (packed >> 16) & 0xFF)
    mem_w8(dstAddr + 0x2A, (packed >> 24) & 0xFF)
    mem_w8(dstAddr + 0x2B, (packed >> 32) & 0xFF)
    -- Copy EVs (6 bytes from EVs substruct at src+0x38)
    for i = 0, 5 do mem_w8(dstAddr + 0x2C + i, mem_r8(srcAddr + 0x38 + i)) end
    -- Copy Misc (8 bytes: pokerus, metLocation, metInfo, ivs from src+0x44)
    for i = 0, 7 do mem_w8(dstAddr + 0x32 + i, mem_r8(srcAddr + 0x44 + i)) end
end

-- Converts a CompressedPokemon (58 bytes at srcAddr) to a BoxPokemon/party
-- (80+ bytes at dstAddr). Writes 80 bytes (BoxPokemon portion).
-- PP is NOT stored in CompressedPokemon; the caller must set party-only stats
-- (level, HP, calculated stats, PP) afterward.
-- Matches CFRU's CreateBoxMonFromCompressedMon.
function M.createBoxMonFromCompressed(srcAddr, dstAddr)
    -- Zero destination (80 bytes for BoxPokemon)
    for i = 0, M.BOX_MON_SIZE - 1 do mem_w8(dstAddr + i, 0) end
    -- Copy header (28 bytes)
    for i = 0, 0x1B do mem_w8(dstAddr + i, mem_r8(srcAddr + i)) end
    -- Checksum at +0x1C stays 0 (CFRU doesn't validate BoxPokemon checksums)
    -- Copy Growth substruct (12 bytes at dst+0x20)
    -- CompressedPokemonSubstruct0 (11 bytes at src+0x1C) → dst+0x20, pad byte 11 = 0
    for i = 0, 10 do mem_w8(dstAddr + 0x20 + i, mem_r8(srcAddr + 0x1C + i)) end
    -- Unpack moves from 10-bit bitfields (5 bytes at src+0x27)
    local b0 = mem_r8(srcAddr + 0x27)
    local b1 = mem_r8(srcAddr + 0x28)
    local b2 = mem_r8(srcAddr + 0x29)
    local b3 = mem_r8(srcAddr + 0x2A)
    local b4 = mem_r8(srcAddr + 0x2B)
    local packed = b0 | (b1 << 8) | (b2 << 16) | (b3 << 24) | (b4 << 32)
    local m1 = packed & 0x3FF
    local m2 = (packed >> 10) & 0x3FF
    local m3 = (packed >> 20) & 0x3FF
    local m4 = (packed >> 30) & 0x3FF
    -- Write moves as u16 each at dst+0x2C (Attacks substruct)
    mem_w16(dstAddr + 0x2C, m1)
    mem_w16(dstAddr + 0x2E, m2)
    mem_w16(dstAddr + 0x30, m3)
    mem_w16(dstAddr + 0x32, m4)
    -- PP bytes at dst+0x34..0x37: set to 0 (caller must recalculate or use cached values)
    -- Copy EVs (6 bytes from src+0x2C → dst+0x38)
    for i = 0, 5 do mem_w8(dstAddr + 0x38 + i, mem_r8(srcAddr + 0x2C + i)) end
    -- Copy Misc (8 bytes from src+0x32 → dst+0x44)
    for i = 0, 7 do mem_w8(dstAddr + 0x44 + i, mem_r8(srcAddr + 0x32 + i)) end
end

-- Returns current mapGroup (u8) and mapNum (u8) via the SaveBlock1 pointer chain.
-- Safe to call every frame — always dereferences ASLR pointer.
function M.getCurrentMap()
    local sb1      = mem_r32(M.SB1_PTR_ADDR)
    if sb1 < 0x02000000 or sb1 >= 0x02040000 then return 0, 0 end
    local mapGroup = mem_r8(sb1 + 0x0004)
    local mapNum   = mem_r8(sb1 + 0x0005)
    return mapGroup, mapNum
end

-- Returns true if the player has at least one Pokéball in the bag.
-- For vanilla/AP: reads SaveBlock1.bagPocket_PokeBalls (SB1+offset).
-- For CFRU/RR: reads EWRAM bag pocket directly (BAG_IN_EWRAM mode).
-- Each ItemSlot is {u16 itemId, u16 quantity}; any non-zero itemId counts.
function M.hasPokeballs()
    local base
    if M.BAG_IN_EWRAM then
        base = M.BALL_POCKET_ADDR
    else
        local sb1 = mem_r32(M.SB1_PTR_ADDR)
        base = sb1 + M.SB1_BALL_POCKET_OFFSET
    end
    for i = 0, M.SB1_BALL_POCKET_COUNT - 1 do
        local itemId = mem_r16(base + i * 4)
        if itemId ~= 0 then return true end
    end
    return false
end

-- Returns the total number of Pokéballs held across all bag pocket slots.
-- For vanilla/AP: quantities are XOR-encrypted in SB1 (actual = stored XOR encKey).
-- For CFRU/RR with BAG_IN_EWRAM: quantities may or may not be encrypted
-- depending on BALL_POCKET_ENC flag (discovery script determines this).
function M.countPokeballs()
    local base, encKey
    if M.BAG_IN_EWRAM then
        base = M.BALL_POCKET_ADDR
        if M.BALL_POCKET_ENC and M.SB2_PTR_ADDR and M.SB2_PTR_ADDR ~= 0 then
            local sb2 = mem_r32(M.SB2_PTR_ADDR)
            if sb2 >= 0x02000000 and sb2 < 0x02040000 then
                encKey = mem_r32(sb2 + M.SB2_ENC_KEY_OFFSET)
            else
                encKey = 0
            end
        else
            encKey = 0
        end
    else
        local sb1 = mem_r32(M.SB1_PTR_ADDR)
        if sb1 < 0x02000000 or sb1 >= 0x02040000 then return 0 end
        if not M.SB2_PTR_ADDR or M.SB2_PTR_ADDR == 0 then return 0 end
        local sb2 = mem_r32(M.SB2_PTR_ADDR)
        if sb2 < 0x02000000 or sb2 >= 0x02040000 then return 0 end
        encKey = mem_r32(sb2 + M.SB2_ENC_KEY_OFFSET)
        base   = sb1 + M.SB1_BALL_POCKET_OFFSET
    end
    local total = 0
    for i = 0, M.SB1_BALL_POCKET_COUNT - 1 do
        local itemId = mem_r16(base + i * 4)
        if itemId ~= 0 then
            local stored = mem_r16(base + i * 4 + 2)
            total = total + ((encKey ~ stored) & 0xFFFF)
        end
    end
    return total
end

-- Badge flags: FLAG_BADGE01_GET (0x820) through FLAG_BADGE08_GET (0x827).
-- Flags are a bitfield in SaveBlock1.flags[]; badge byte = flags_base + 0x104.
-- Returns an integer 0–8 (number of badges earned).
M.BADGE_FLAG_BYTE_OFFSET = 0x104  -- 0x820 / 8 = 260 = 0x104
function M.readBadges()
    local sb1  = mem_r32(M.SB1_PTR_ADDR)
    if sb1 < 0x02000000 or sb1 >= 0x02040000 then return 0, 0 end
    local byte = mem_r8(sb1 + M.SB1_FLAGS_OFFSET + M.BADGE_FLAG_BYTE_OFFSET)
    local count = 0
    for bit = 0, 7 do
        if (byte & (1 << bit)) ~= 0 then count = count + 1 end
    end
    return count, byte
end

function M.boxMonAddr(boxIdx, slotIdx)
    -- CFRU compressed boxes: 25 non-contiguous regions, 58-byte slots
    if M.CFRU_BOX_BASES then
        local base = M.CFRU_BOX_BASES[boxIdx + 1]  -- Lua 1-indexed
        if not base then return nil end
        return base + slotIdx * M.COMPRESSED_MON_SIZE
    end
    -- DPE/RR legacy: box storage at fixed offset from SB1 (no PSP pointer)
    if M.BOX_SB1_OFFSET then
        local sb1 = mem_r32(M.SB1_PTR_ADDR)
        return sb1 + M.BOX_SB1_OFFSET + (boxIdx * M.MONS_PER_BOX + slotIdx) * M.BOX_MON_SIZE
    end
    -- Vanilla/AP: use gPokemonStoragePtr
    if not M.PSP_PTR_ADDR or M.PSP_PTR_ADDR == 0 then
        return nil
    end
    local psp = mem_r32(M.PSP_PTR_ADDR)
    return psp + M.BOX_DATA_OFFSET + (boxIdx * M.MONS_PER_BOX + slotIdx) * M.BOX_MON_SIZE
end

function M.renameBox(boxIdx, name)
    -- Compute box name address
    local nameAddr
    if M.CFRU_BOX_NAME_BASE then
        -- CFRU: boxes 0-13 forward from name base, boxes 14-24 backward
        if boxIdx <= 13 then
            nameAddr = M.CFRU_BOX_NAME_BASE + boxIdx * M.BOX_NAME_SIZE
        else
            nameAddr = M.CFRU_BOX_NAME_BASE - (boxIdx - 13) * M.BOX_NAME_SIZE
        end
    elseif M.BOX_SB1_OFFSET then
        local sb1 = mem_r32(M.SB1_PTR_ADDR)
        nameAddr = sb1 + M.BOX_SB1_OFFSET - M.BOX_DATA_OFFSET + M.BOX_NAMES_OFFSET
                 + boxIdx * M.BOX_NAME_SIZE
    else
        if not M.PSP_PTR_ADDR or M.PSP_PTR_ADDR == 0 then return end
        local psp = mem_r32(M.PSP_PTR_ADDR)
        nameAddr = psp + M.BOX_NAMES_OFFSET + boxIdx * M.BOX_NAME_SIZE
    end
    local len  = math.min(#name, M.BOX_NAME_SIZE - 1)
    for i = 1, len do
        local b = _CHARSET_REV[name:sub(i, i)]
        if not b then return false, "unsupported character: " .. name:sub(i, i) end
        mem_w8(nameAddr + i - 1, b)
    end
    mem_w8(nameAddr + len, 0xFF)
    return true
end

-- Reads the current battle outcome byte (gBattleOutcome).
-- Returns 0 between battles (game doesn't zero it — caller should compare to
-- M.OUTCOME_* constants only while isInBattle() is true or just transitioned).
function M.getBattleOutcome()
    if not M.BATTLE_OUTCOME_ADDR or M.BATTLE_OUTCOME_ADDR == 0 then return 0 end
    return memory.read_u8(M.BATTLE_OUTCOME_ADDR)
end

-- Returns true when every occupied party slot has HP = 0.
-- battle_hp_cache: optional table [slot] → {hp, maxHP, level} from gBattleMons.
-- For CFRU/RR, party HP is stale during battle; the cache has live values.
function M.allPartyFainted(battle_hp_cache)
    local count = memory.read_u8(M.PARTY_COUNT_ADDR)
    if count == 0 then return false end
    for i = 0, count - 1 do
        local hp
        if battle_hp_cache and battle_hp_cache[i] then
            hp = battle_hp_cache[i].hp
        else
            local base = M.PARTY_BASE + i * M.MON_SIZE
            hp = memory.read_u16_le(base + M.OFF_HP)
        end
        if hp > 0 then
            return false
        end
    end
    return true
end

-- Writes HP=0 to a party slot — battle-safe faint trigger.
-- When called during a battle, also writes to the corresponding gBattleMons entry
-- so the battle engine's own faint-detection logic fires and plays the animation.
-- NOTE: The battle engine checks gBattleMons.hp during battle script execution
-- (HandleFaintedMonActions), NOT every frame. If called during move selection,
-- the faint animation will play after the player selects an action and the turn
-- resolves. This is normal behaviour — no ROM patch is needed.
-- Does NOT zero the slot; deferred memorialization handles that.
function M.forceFaint(slot)
    local base = M.PARTY_BASE + slot * M.MON_SIZE
    memory.write_u16_le(base + M.OFF_HP, 0)
    if M.isInBattle() then
        local battler = M.getBattlerForPartySlot(slot)
        if battler >= 0 then
            local bmon_base = M.BATTLE_MONS_ADDR + battler * M.BATTLE_MON_SIZE
            memory.write_u16_le(bmon_base + M.BATTLE_MON_HP_OFF, 0)
        end
    end
end

-- Forces an immediate whiteout.
--
-- In battle: zeros all party HP, sets gBattleOutcome=LOST, and redirects
-- gBattleMainFunc to ReturnFromBattleToOverworld on the next frame.
-- The faint animation is skipped; the game jumps to the "blacked out" screen.
--
-- In overworld: zeros all party HP only. The game itself does not auto-whiteout
-- from the overworld (no mechanism without a ROM patch), but the Soul Link
-- server detects all-HP=0 and declares the run over.
--
-- Returns true if the battle-redirect path was taken, false for overworld.
function M.forceImmediateWhiteout()
    local count = memory.read_u8(M.PARTY_COUNT_ADDR)
    for i = 0, count - 1 do
        memory.write_u16_le(M.PARTY_BASE + i * M.MON_SIZE + M.OFF_HP, 0)
    end
    -- CFRU reads HP from gBattleMons during battle, not party struct.
    -- Zero all player-side battler HP so the battle engine sees the faint.
    if M.isInBattle() and M.BATTLE_MONS_ADDR and M.BATTLE_MONS_ADDR ~= 0 then
        if M.BATTLER_PARTY_INDEXES_ADDR then
            -- Battler 0: always player primary
            memory.write_u16_le(M.BATTLE_MONS_ADDR + 0 * M.BATTLE_MON_SIZE + M.BATTLE_MON_HP_OFF, 0)
            -- Battler 2: player secondary in doubles
            if M.BATTLERS_COUNT_ADDR and memory.read_u8(M.BATTLERS_COUNT_ADDR) >= 4 then
                memory.write_u16_le(M.BATTLE_MONS_ADDR + 2 * M.BATTLE_MON_SIZE + M.BATTLE_MON_HP_OFF, 0)
            end
        end
        if M.supports_battle_redirect then
            memory.write_u8(M.BATTLE_OUTCOME_ADDR, M.OUTCOME_LOST)
            memory.write_u32_le(M.BATTLE_MAIN_FUNC_ADDR, M.RETURN_FROM_BATTLE_ADDR)
            return true
        end
    end
    return false
end

-- Returns the monKey for a PC box slot (or nil if empty).
function M.boxMonKey(boxIdx, slotIdx)
    local addr = M.boxMonAddr(boxIdx, slotIdx)
    if not addr then return nil end
    local flags = memory.read_u8(addr + M.OFF_FLAGS)
    if (flags & 0x02) == 0 then return nil end
    return M.monKey(addr)
end

-- Reads all occupied slots in the CURRENT PC box (the one the player last used).
-- Returns: boxIndex (0-based u8), keys (set: key → true).
-- Only reads the flags byte per slot + 8 bytes for the key when occupied.
-- Safe to call every frame; 30 flag reads is negligible overhead.
function M.readCurrentBox()
    local boxIndex
    if M.POKEMON_STORAGE_BASE then
        -- CFRU: currentBox is byte 0 of PokemonStorage struct
        boxIndex = memory.read_u8(M.POKEMON_STORAGE_BASE)
    elseif M.BOX_SB1_OFFSET then
        local sb1 = memory.read_u32_le(M.SB1_PTR_ADDR)
        boxIndex = memory.read_u8(sb1 + M.BOX_SB1_OFFSET - M.BOX_DATA_OFFSET)
    elseif M.PSP_PTR_ADDR and M.PSP_PTR_ADDR ~= 0 then
        local psp = memory.read_u32_le(M.PSP_PTR_ADDR)
        boxIndex = memory.read_u8(psp)   -- PokemonStorage.currentBox
    else
        return 0, {}
    end
    if boxIndex >= M.BOXES_PER_STORE then boxIndex = 0 end
    local keys     = {}
    for slot = 0, M.MONS_PER_BOX - 1 do
        local addr  = M.boxMonAddr(boxIndex, slot)
        if not addr then break end
        local flags = memory.read_u8(addr + M.OFF_FLAGS)
        if (flags & 0x02) ~= 0 then   -- hasSpecies
            keys[M.monKey(addr)] = true
        end
    end
    return boxIndex, keys
end

-- Returns true if the current battle is a wild encounter (not a trainer battle).
-- Returns nil if battle type cannot be determined (RR: BATTLE_TYPE_ADDR unknown).
-- Read at the battle-start frame only; gBattleTypeFlags is valid once inBattle=true.
function M.isWildBattle()
    if not M.BATTLE_TYPE_ADDR or M.BATTLE_TYPE_ADDR == 0 then
        return nil  -- unknown — caller must handle
    end
    return (memory.read_u32_le(M.BATTLE_TYPE_ADDR) & (M.BATTLE_TYPE_TRAINER_MASK | M.BATTLE_TYPE_FIRST_MASK)) == 0
end

--- Check if the current battle uses a borrowed/replaced party.
-- Returns true for Poké Dude tutorials, in-game partner battles, and mock
-- battles where the game temporarily replaces gPlayerParty with another
-- trainer's mons.  Always returns false when BATTLE_TYPE_ADDR is unavailable
-- (vanilla/AP don't have these battle types).
function M.isBorrowedBattle()
    if not M.BATTLE_TYPE_ADDR or M.BATTLE_TYPE_ADDR == 0 then
        return false
    end
    return (memory.read_u32_le(M.BATTLE_TYPE_ADDR) & M.BATTLE_TYPE_BORROWED_MASK) ~= 0
end

--- Read the current trainer opponent index (gTrainerBattleOpponent_A).
-- Returns 0 if unknown or not in a trainer battle.
function M.readTrainerOpponentId()
    if not M.TRAINER_OPPONENT_ADDR or M.TRAINER_OPPONENT_ADDR == 0 then
        return 0
    end
    return memory.read_u16_le(M.TRAINER_OPPONENT_ADDR)
end

-- Read the full enemy party (up to 6 mons) from gEnemyParty.
-- Only valid during battle — data is stale outside battle in CFRU.
-- Returns a list of {species_id, level, hp, maxHP} for occupied slots.
function M.readEnemyParty()
    local result = {}
    if not M.ENEMY_BASE then return result end
    -- CFRU may not update gEnemyPartyCount; scan slots until maxHP == 0.
    local count = 6
    if M.ENEMY_COUNT_ADDR then
        local c = mem_r8(M.ENEMY_COUNT_ADDR)
        if c >= 1 and c <= 6 then count = c end
    end
    for i = 0, count - 1 do
        local base = M.ENEMY_BASE + i * M.MON_SIZE
        local maxHP = mem_r16(base + M.OFF_MAX_HP)
        if maxHP == 0 then break end
        local ok_s, sid = pcall(M.decryptSpecies, base)
        if not ok_s or not sid or sid == 0 then sid = 0 end
        local ok_a, aid = pcall(M.getAbilityId, base)
        local ok_i, iid = pcall(M.decryptHeldItem, base)
        result[#result + 1] = {
            species_id    = sid,
            level         = mem_r8(base + M.OFF_LEVEL),
            hp            = mem_r16(base + M.OFF_HP),
            maxHP         = maxHP,
            ability_id    = (ok_a and aid) or 0,
            held_item_id  = (ok_i and iid) or 0,
        }
    end
    return result
end

-- ── Party ↔ Box sync helpers ──────────────────────────────────────────────────

-- Returns the party-only stat fields for slot (needed to restore after box retrieval).
-- These 20 bytes are NOT stored in BoxPokemon and must be cached while the mon is
-- in the party so the server can echo them back in a party_mon command.
function M.readPartyStatsFull(slot)
    local base = M.PARTY_BASE + slot * M.MON_SIZE
    if not M.slotOccupied(base) then return nil end
    return {
        level   = mem_r8(base + M.OFF_LEVEL),
        maxHP   = mem_r16(base + M.OFF_MAX_HP),
        attack  = mem_r16(base + 0x5A),
        defense = mem_r16(base + 0x5C),
        speed   = mem_r16(base + 0x5E),
        spAtk   = mem_r16(base + 0x60),
        spDef   = mem_r16(base + 0x62),
    }
end

-- Deposits a party slot to the first free non-memorial box slot.
-- For CFRU: converts the 100-byte party mon to a 58-byte CompressedPokemon.
-- For vanilla/AP: copies the 80-byte BoxPokemon portion.
-- Zeros the 100-byte party slot, compacts the party, decrements count.
-- Returns boxIdx, slotIdx on success, or nil, errMsg on failure.
-- ONLY call in safe state (overworld, not in battle).
function M.depositPartyMon(partySlot)
    local partyBase = M.PARTY_BASE + partySlot * M.MON_SIZE
    local slotSize  = M.boxSlotSize()
    for boxIdx = 0, M.BOXES_PER_STORE - 1 do
        if boxIdx ~= M.MEMORIAL_BOX then
        for slotIdx = 0, M.MONS_PER_BOX - 1 do
            local boxAddr = M.boxMonAddr(boxIdx, slotIdx)
            if not boxAddr then return nil, "box address unavailable" end
            local flags   = memory.read_u8(boxAddr + M.OFF_FLAGS)
            if (flags & 0x02) == 0 then  -- empty slot
                if M.CFRU_COMPRESSED_BOX then
                    M.createCompressedMon(partyBase, boxAddr)
                else
                    for i = 0, M.BOX_MON_SIZE - 1 do
                        memory.write_u8(boxAddr + i, memory.read_u8(partyBase + i))
                    end
                end
                -- Zero the full 100-byte party slot
                for i = 0, M.MON_SIZE - 1 do
                    memory.write_u8(partyBase + i, 0)
                end
                -- Compact party
                local count = memory.read_u8(M.PARTY_COUNT_ADDR)
                for s = partySlot, count - 2 do
                    local src = M.PARTY_BASE + (s + 1) * M.MON_SIZE
                    local dst = M.PARTY_BASE + s * M.MON_SIZE
                    for i = 0, M.MON_SIZE - 1 do
                        memory.write_u8(dst + i, memory.read_u8(src + i))
                    end
                end
                local lastBase = M.PARTY_BASE + (count - 1) * M.MON_SIZE
                for i = 0, M.MON_SIZE - 1 do memory.write_u8(lastBase + i, 0) end
                memory.write_u8(M.PARTY_COUNT_ADDR, count - 1)
                return boxIdx, slotIdx
            end
        end
        end
    end
    return nil, "no free box slot (all non-memorial boxes full)"
end

-- Scans all 14 boxes for a mon matching key (personality:otId string).
-- Returns boxIdx (0-based), slotIdx (0-based), addr on success, or nil.
function M.scanBoxForKey(key)
    if not M.CFRU_BOX_BASES and not M.BOX_SB1_OFFSET
       and (not M.PSP_PTR_ADDR or M.PSP_PTR_ADDR == 0) then return nil end
    for boxIdx = 0, M.BOXES_PER_STORE - 1 do
        for slotIdx = 0, M.MONS_PER_BOX - 1 do
            local addr  = M.boxMonAddr(boxIdx, slotIdx)
            if not addr then return nil end
            local flags = memory.read_u8(addr + M.OFF_FLAGS)
            if (flags & 0x02) ~= 0 then  -- hasSpecies
                if M.monKey(addr) == key then
                    return boxIdx, slotIdx, addr
                end
            end
        end
    end
    return nil
end

-- Retrieves a boxed mon by key to the end of the party.
-- stats: {level, maxHP, attack, defense, speed, spAtk, spDef}
--   These party-only fields are not stored in BoxPokemon; pass values cached
--   when the mon was last in the party. The mon is always restored to full HP.
-- Returns true on success, or nil, errMsg on failure.
-- ONLY call in safe state (overworld, not in battle).
-- Returns the first free slot in memorial boxes (last box, then descending).
-- Returns boxIdx, slotIdx on success, or nil if all memorial boxes are full.
function M.findFreeMemorialSlot()
    if not M.CFRU_BOX_BASES and not M.BOX_SB1_OFFSET
       and (not M.PSP_PTR_ADDR or M.PSP_PTR_ADDR == 0) then return nil end
    for boxIdx = M.MEMORIAL_BOX, 0, -1 do
        for slotIdx = 0, M.MONS_PER_BOX - 1 do
            local addr  = M.boxMonAddr(boxIdx, slotIdx)
            local flags = memory.read_u8(addr + M.OFF_FLAGS)
            if (flags & 0x02) == 0 then  -- no hasSpecies = free slot
                return boxIdx, slotIdx
            end
        end
    end
    return nil  -- all boxes completely full (extremely unlikely)
end

-- Moves a mon identified by key to the next free memorial slot.
-- For CFRU: party→memorial uses createCompressedMon; box→memorial copies 58 bytes.
-- For vanilla/AP: party→memorial copies 80 bytes; box→memorial copies 80 bytes.
-- Searches party first, then all boxes.
-- Returns memBoxIdx, memSlotIdx on success, or nil, errMsg on failure.
-- ONLY call in safe state (overworld, not in battle).
function M.memorializeMon(key)
    local memBox, memSlot = M.findFreeMemorialSlot()
    if not memBox then return nil, "all boxes full" end
    local memAddr = M.boxMonAddr(memBox, memSlot)
    local slotSize = M.boxSlotSize()

    -- Search party (includes HP=0 fainted mons — personality/otId are intact)
    local count = memory.read_u8(M.PARTY_COUNT_ADDR)
    for slot = 0, count - 1 do
        local base = M.PARTY_BASE + slot * M.MON_SIZE
        if M.monKey(base) == key then
            -- Convert party mon to box format
            if M.CFRU_COMPRESSED_BOX then
                M.createCompressedMon(base, memAddr)
            else
                for i = 0, M.BOX_MON_SIZE - 1 do
                    memory.write_u8(memAddr + i, memory.read_u8(base + i))
                end
            end
            -- Zero full 100-byte party slot then compact
            for i = 0, M.MON_SIZE - 1 do memory.write_u8(base + i, 0) end
            for s = slot, count - 2 do
                local src = M.PARTY_BASE + (s + 1) * M.MON_SIZE
                local dst = M.PARTY_BASE + s * M.MON_SIZE
                for i = 0, M.MON_SIZE - 1 do
                    memory.write_u8(dst + i, memory.read_u8(src + i))
                end
            end
            local lastBase = M.PARTY_BASE + (count - 1) * M.MON_SIZE
            for i = 0, M.MON_SIZE - 1 do memory.write_u8(lastBase + i, 0) end
            memory.write_u8(M.PARTY_COUNT_ADDR, count - 1)
            return memBox, memSlot
        end
    end

    -- Search all boxes for the key (skip the destination slot to avoid self-copy)
    for boxIdx = 0, M.BOXES_PER_STORE - 1 do
        for slotIdx = 0, M.MONS_PER_BOX - 1 do
            local addr  = M.boxMonAddr(boxIdx, slotIdx)
            if addr and addr ~= memAddr then
                local flags = memory.read_u8(addr + M.OFF_FLAGS)
                if (flags & 0x02) ~= 0 and M.monKey(addr) == key then
                    -- Box-to-box: copy exact slot size (58 for CFRU, 80 for vanilla)
                    for i = 0, slotSize - 1 do
                        memory.write_u8(memAddr + i, memory.read_u8(addr + i))
                    end
                    for i = 0, slotSize - 1 do memory.write_u8(addr + i, 0) end
                    return memBox, memSlot
                end
            end
        end
    end

    return nil, "key not found in party or boxes"
end

-- Returns nickname, species_id, held_item_id for a box slot at addr, with pcall guards.
-- For CFRU CompressedPokemon: species at +0x1C, item at +0x1E.
-- For vanilla/AP BoxPokemon or party Pokemon: uses standard decrypt functions.
-- The is_box_slot flag controls which decrypt path to use; defaults to true.
function M.readBoxSlotDisplay(addr, is_box_slot)
    if is_box_slot == nil then is_box_slot = true end
    local ok_n, nick = pcall(M.readNickname, addr)
    local ok_s, sid, ok_i, iid
    if is_box_slot then
        ok_s, sid = pcall(M.decryptBoxSpecies,  addr)
        ok_i, iid = pcall(M.decryptBoxHeldItem, addr)
    else
        ok_s, sid = pcall(M.decryptSpecies,  addr)
        ok_i, iid = pcall(M.decryptHeldItem, addr)
    end
    return ok_n and nick or "", ok_s and sid or 0, ok_i and iid or 0
end

-- ── m4a sound engine — in-game SE playback ──────────────────────────────────
-- Drives FRLG's m4a (MKS4AGB) sound driver directly via memory writes.
-- Replicates what MPlayStart() does: sets up MusicPlayerInfo + MusicPlayerTrack,
-- then the VBlank ISR (SoundMain) processes playback automatically.
--
-- References: pret/pokefirered include/gba/m4a_internal.h, include/gba/defines.h

M.SOUND_INFO_PTR_ADDR = 0x3007FF0  -- fixed IWRAM ptr to gSoundInfo (defines.h)
M.ID_NUMBER           = 0x68736D53 -- m4a ident magic ("Smsh" LE)

-- SE_SONG_HEADERS is profile-dependent — set by applyProfile() from game module.
-- For AP, the table is empty and playSE() gracefully returns false.

-- SE constants (from include/constants/songs.h)
M.SE_FAINT   = 16
M.SE_FLEE    = 17
M.SE_BOO     = 22
M.SE_SUCCESS = 25
M.SE_FAILURE = 26
M.SE_SHINY   = 95

-- MusicPlayerInfo struct offsets (64 bytes, m4a_internal.h)
local O_MPL_SONG_HDR    = 0x00
local O_MPL_STATUS      = 0x04
local O_MPL_TRACKCOUNT  = 0x08
local O_MPL_PRIORITY    = 0x09
local O_MPL_CLOCK       = 0x0C
local O_MPL_TRACKS_PTR  = 0x2C
local O_MPL_IDENT       = 0x34
local O_MPL_NEXT        = 0x3C

-- MusicPlayerTrack offsets (80 bytes)
local O_TRK_FLAGS   = 0x00
local O_TRK_BEND    = 0x0F
local O_TRK_VOLX    = 0x13
local O_TRK_LFO     = 0x19
local O_TRK_CHAN     = 0x20
local O_TRK_CMDPTR  = 0x40
local TRK_START      = 0xC0  -- EXIST(0x80) | START(0x40)

-- SoundInfo offset
local O_SNDINFO_HEAD = 0x24

--- Resolve SE1 MusicPlayerInfo address at runtime via the linked list.
-- gSoundInfo.musicPlayerHead → BGM → SE1 (next in list).
-- Cached after first successful lookup (address is stable for the session).
local cached_se1_addr = nil

local function getMPlayInfoSE1()
    if cached_se1_addr then return cached_se1_addr end
    local gsound = memory.read_u32_le(M.SOUND_INFO_PTR_ADDR)
    if gsound < 0x03000000 or gsound >= 0x03008000 then return nil end
    local head = memory.read_u32_le(gsound + O_SNDINFO_HEAD)
    if head < 0x03000000 or head >= 0x03008000 then return nil end
    -- Walk linked list: head is last-added. MPlayOpen prepends, so list order
    -- is reversed from gMPlayTable. Walk to tail-1 to find SE1 (index 1).
    -- Confirmed layout: [5]→[4]→SE3→SE2→SE1→BGM(tail)
    -- We need SE1 = second-to-last node.
    local nodes, cur = {}, head
    while cur ~= 0 and #nodes < 16 do
        if cur < 0x03000000 or cur >= 0x03008000 then break end
        nodes[#nodes + 1] = cur
        cur = memory.read_u32_le(cur + O_MPL_NEXT)
    end
    -- Reverse to get gMPlayTable order: [0]=BGM, [1]=SE1, ...
    if #nodes >= 2 then
        cached_se1_addr = nodes[#nodes - 1]
        return cached_se1_addr
    end
    return nil
end

--- Play a sound effect by writing directly to the SE1 music player.
-- songNum: SE constant (e.g. M.SE_FAINT). Only plays SEs in M.SE_SONG_HEADERS.
function M.playSE(songNum)
    local hdr = M.SE_SONG_HEADERS[songNum]
    if not hdr then return false end

    local se1 = getMPlayInfoSE1()
    if not se1 then return false end

    local ok, err = pcall(function()
        -- Validate: driver must be initialized (ident == ID_NUMBER)
        if memory.read_u32_le(se1 + O_MPL_IDENT) ~= M.ID_NUMBER then return end

        local track0 = memory.read_u32_le(se1 + O_MPL_TRACKS_PTR)
        if track0 < 0x03000000 or track0 >= 0x03008000 then return end

        -- Read SongHeader fields from ROM
        local track_count = memory.read_u8(hdr + 0x00)
        local priority    = memory.read_u8(hdr + 0x02)
        local cmd_ptr     = memory.read_u32_le(hdr + 0x08)  -- part[0]

        -- Lock player (prevent ISR race during multi-write)
        memory.write_u32_le(se1 + O_MPL_IDENT, M.ID_NUMBER + 1)

        -- Set up MusicPlayerInfo
        memory.write_u32_le(se1 + O_MPL_SONG_HDR,   hdr)
        memory.write_u32_le(se1 + O_MPL_STATUS,      (1 << track_count) - 1)
        memory.write_u8    (se1 + O_MPL_TRACKCOUNT,  track_count)
        memory.write_u8    (se1 + O_MPL_PRIORITY,    priority)
        memory.write_u32_le(se1 + O_MPL_CLOCK,       0)

        -- Set up MusicPlayerTrack[0]: clear flags word, then write fields
        memory.write_u32_le(track0 + 0x00, 0)
        memory.write_u8    (track0 + O_TRK_FLAGS, TRK_START)
        memory.write_u8    (track0 + O_TRK_BEND,  2)    -- bendRange default
        memory.write_u8    (track0 + O_TRK_VOLX,  64)   -- volume default
        memory.write_u8    (track0 + O_TRK_LFO,   22)   -- lfoSpeed default
        memory.write_u32_le(track0 + O_TRK_CHAN,   0)    -- chan* = NULL
        memory.write_u32_le(track0 + O_TRK_CMDPTR, cmd_ptr)

        -- Unlock (ISR picks this up on next VBlank)
        memory.write_u32_le(se1 + O_MPL_IDENT, M.ID_NUMBER)
    end)
    if not ok then
        console.log("[SND] playSE error: " .. tostring(err))
    end
    return ok
end


-- Returned array entries: {box, slot, key, nickname, species_id, held_item_id}.
-- Call at BOX_SCAN_INTERVAL (~300 frames ≈ 5 s) rather than every frame.
function M.readBoxSummary()
    local result = {}
    if not M.CFRU_BOX_BASES and not M.BOX_SB1_OFFSET
       and (not M.PSP_PTR_ADDR or M.PSP_PTR_ADDR == 0) then return result end
    for boxIdx = 0, M.BOXES_PER_STORE - 1 do
        for slotIdx = 0, M.MONS_PER_BOX - 1 do
            local addr = M.boxMonAddr(boxIdx, slotIdx)
            if addr and M.boxSlotOccupied(addr) then
                local nick, sid, iid = M.readBoxSlotDisplay(addr, true)
                table.insert(result, {
                    box          = boxIdx,
                    slot         = slotIdx,
                    key          = M.monKey(addr),
                    nickname     = nick,
                    species_id   = sid,
                    held_item_id = iid,
                })
            end
        end
    end
    return result
end

function M.retrieveBoxMon(key, stats)
    local count = memory.read_u8(M.PARTY_COUNT_ADDR)
    if count >= 6 then return nil, "party full" end
    local boxIdx, slotIdx, boxAddr = M.scanBoxForKey(key)
    if not boxIdx then return nil, "key not found in any box" end
    local partyBase = M.PARTY_BASE + count * M.MON_SIZE
    local slotSize  = M.boxSlotSize()
    if M.CFRU_COMPRESSED_BOX then
        -- Decompress 58-byte CompressedPokemon → 100-byte party slot
        -- First zero the full party slot
        for i = 0, M.MON_SIZE - 1 do memory.write_u8(partyBase + i, 0) end
        -- Write 80-byte BoxPokemon portion from compressed data
        M.createBoxMonFromCompressed(boxAddr, partyBase)
    else
        -- Copy 80-byte BoxPokemon from box to party
        for i = 0, M.BOX_MON_SIZE - 1 do
            memory.write_u8(partyBase + i, memory.read_u8(boxAddr + i))
        end
        -- Zero the 20 party-only bytes
        for i = M.BOX_MON_SIZE, M.MON_SIZE - 1 do
            memory.write_u8(partyBase + i, 0)
        end
    end
    -- Set party-only stats from cached values
    if stats then
        local lv = stats.level or 1
        local mh = stats.maxHP or 1
        memory.write_u8(partyBase     + M.OFF_LEVEL,   lv)
        memory.write_u16_le(partyBase + M.OFF_HP,       mh)   -- full heal on retrieval
        memory.write_u16_le(partyBase + M.OFF_MAX_HP,   mh)
        if stats.attack  then memory.write_u16_le(partyBase + 0x5A, stats.attack)  end
        if stats.defense then memory.write_u16_le(partyBase + 0x5C, stats.defense) end
        if stats.speed   then memory.write_u16_le(partyBase + 0x5E, stats.speed)   end
        if stats.spAtk   then memory.write_u16_le(partyBase + 0x60, stats.spAtk)   end
        if stats.spDef   then memory.write_u16_le(partyBase + 0x62, stats.spDef)   end
        -- Restore move PP (CFRU compressed box doesn't store PP)
        if stats.pp1 then memory.write_u8(partyBase + 0x34, stats.pp1) end
        if stats.pp2 then memory.write_u8(partyBase + 0x35, stats.pp2) end
        if stats.pp3 then memory.write_u8(partyBase + 0x36, stats.pp3) end
        if stats.pp4 then memory.write_u8(partyBase + 0x37, stats.pp4) end
        -- Fallback: if no PP cached but moves exist, set PP to safe minimum (5)
        -- so the mon can still use moves. Heal at a Pokémon Center for full PP.
        if not stats.pp1 and M.CFRU_NO_ENCRYPT then
            local moves = {
                memory.read_u16_le(partyBase + 0x2C),
                memory.read_u16_le(partyBase + 0x2E),
                memory.read_u16_le(partyBase + 0x30),
                memory.read_u16_le(partyBase + 0x32),
            }
            for i = 1, 4 do
                if moves[i] and moves[i] > 0 then
                    memory.write_u8(partyBase + 0x33 + i, 5)
                end
            end
        end
    end
    -- Zero the source box slot
    for i = 0, slotSize - 1 do
        memory.write_u8(boxAddr + i, 0)
    end
    -- Increment party count
    memory.write_u8(M.PARTY_COUNT_ADDR, count + 1)
    return true
end

return M
