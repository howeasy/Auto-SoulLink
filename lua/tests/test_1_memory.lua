--[[
  lua/test_1_memory.lua — LIVE MEMORY READER (console output)
  Read-only. No server needed. Safe to run at any time.
  All output goes to the BizHawk Lua console.

  ┌─ TESTING CRITERIA ────────────────────────────────────────────────────────
  │  1. ROM validation:  "ROM: firered OK" logged on startup
  │  2. Party snapshot:  printed on load and whenever count or any HP changes
  │  3. HP / MaxHP:      each slot matches the HP bar in the party menu
  │  4. Level:           each slot matches the level shown in party menu
  │  5. Map change:      logged whenever you enter a new area
  │  6. Area ID:         encounter zones show area="route_1", towns show loc="pallet_town"
  │  7. In-battle:       "in_battle=true" when battle starts, "false" when over
  │
  │  F1 = EWRAM scan (use inside a live wild battle)
  │  F2 = raw byte dump of party slot 0 (for HP/level offset verification)
  └───────────────────────────────────────────────────────────────────────────
--]]

-- ── path setup ────────────────────────────────────────────────────────────────
local _src = debug.getinfo(1, "S").source:match("@(.+[/\\])") or ""
local _lua_root = _src:match("(.+[/\\])tests[/\\]") or _src
local _proj_root = _lua_root:match("(.+[/\\])lua[/\\]") or (_lua_root .. "../")
package.path = _src .. "?.lua;"
           .. _lua_root .. "?.lua;"
           .. _proj_root .. "data/games/gen3_frlge/?.lua;"
           .. package.path

local M         = require("memory_gba")
local areas     = require("gen3_frlge_areas")
local locations = require("gen3_frlge_locations")

-- ── startup ───────────────────────────────────────────────────────────────────
M.initProfile()
local rom_type = M.detectROM()
local ok, err  = M.validateROM()

console.clear()
console.log(string.format("[T1] ROM: %s  Validation: %s",
    rom_type, ok and "OK" or ("FAIL – " .. tostring(err))))
if not ok then
    console.log("[T1] Reads will still work; all addresses are fixed EWRAM globals.")
end
console.log("[T1] F1=EWRAM scan (use in battle)  F2=raw dump party slot 0")
console.log("[T1] Logging: map changes, battle transitions, party snapshots, HP changes.")

-- ── prev-state tracking ───────────────────────────────────────────────────────
local prev_map        = ""
local prev_battle     = nil
local prev_count      = -1
local prev_hp         = {}   -- [slot_index] = last seen player hp
local prev_enemy_hp   = {}   -- [slot_index] = last seen enemy hp
local prev_gmain_sig  = -1   -- packed (state<<8 | inbattle_byte), -1 = not yet read

-- ── helpers ───────────────────────────────────────────────────────────────────
local function log_party()
    local count = memory.read_u8(M.PARTY_COUNT_ADDR)
    console.log(string.format("[T1] Player party (%d/6):", count))
    for i = 0, count - 1 do
        local s = M.readPartySlot(i)
        if s then
            console.log(string.format("  [%d] Lv%-3d  HP %d/%d  key=%s",
                i, s.level, s.hp, s.maxHP, s.key))
        else
            console.log(string.format("  [%d] (occupied in count but readPartySlot=nil)", i))
        end
    end
end

local function log_enemy_team()
    local found = 0
    for i = 0, 5 do
        local base  = M.ENEMY_BASE + i * M.MON_SIZE
        local maxHP = memory.read_u16_le(base + M.OFF_MAX_HP)
        if maxHP > 0 then
            local hp  = memory.read_u16_le(base + M.OFF_HP)
            local lv  = memory.read_u8(base + M.OFF_LEVEL)
            local key = string.format("%08X:%08X",
                memory.read_u32_le(base + M.OFF_PERSONALITY),
                memory.read_u32_le(base + M.OFF_OTID))
            console.log(string.format("  enemy[%d] Lv%-3d  HP %d/%d  key=%s",
                i, lv, hp, maxHP, key))
            found = found + 1
        end
    end
    if found == 0 then
        console.log("  (no enemy data yet — battle intro still loading?)")
    end
end

-- F2: raw byte dump of party slot 0 unencrypted fields — verifies HP/level offsets.
local function dump_party_slot0()
    local base = M.PARTY_BASE
    console.log("[T1] === Party slot 0 raw dump (unencrypted fields) ===")
    console.log(string.format("  +0x50 status  u32 = 0x%08X", memory.read_u32_le(base + M.OFF_STATUS)))
    console.log(string.format("  +0x54 level   u8  = %d",      memory.read_u8(base + M.OFF_LEVEL)))
    console.log(string.format("  +0x55 pokerus u8  = %d",      memory.read_u8(base + 0x55)))
    console.log(string.format("  +0x56 hp      u16 = %d",      memory.read_u16_le(base + M.OFF_HP)))
    console.log(string.format("  +0x58 maxHP   u16 = %d",      memory.read_u16_le(base + M.OFF_MAX_HP)))
    console.log(string.format("  +0x5A attack  u16 = %d",      memory.read_u16_le(base + 0x5A)))
    console.log(string.format("  +0x5C defense u16 = %d",      memory.read_u16_le(base + 0x5C)))
    console.log(string.format("  +0x5E speed   u16 = %d",      memory.read_u16_le(base + 0x5E)))
end

-- F1: full EWRAM scan for Pokemon-like structs (use during a live battle).
local function scan_ewram_for_pokemon()
    console.log("[T1] === EWRAM scan — run this during a live wild battle ===")
    local PARTY_START = M.PARTY_BASE
    local PARTY_END   = M.PARTY_BASE + 6 * M.MON_SIZE
    local found = {}
    for addr = 0x02000000, 0x0203FFFC, 4 do
        if addr < PARTY_START or addr >= PARTY_END then
            local pers = memory.read_u32_le(addr)
            if pers ~= 0 then
                local maxHP = memory.read_u16_le(addr + M.OFF_MAX_HP)
                if maxHP >= 1 and maxHP <= 1000 then
                    local hp = memory.read_u16_le(addr + M.OFF_HP)
                    local lv = memory.read_u8(addr + M.OFF_LEVEL)
                    if hp >= 1 and hp <= maxHP and lv >= 1 and lv <= 100 then
                        table.insert(found, string.format(
                            "  0x%08X  Lv%d HP %d/%d  pers=%08X",
                            addr, lv, hp, maxHP, pers))
                    end
                end
            end
        end
    end
    console.log(string.format("[T1] Done. %d candidate(s):", #found))
    for _, s in ipairs(found) do console.log(s) end
    if #found == 0 then
        console.log("[T1] No candidates — are you in an active wild battle?")
    end
end

-- ── per-frame ─────────────────────────────────────────────────────────────────
-- In-battle detection uses gMain.inBattle bit at 0x03003529 (bit 1, mask 0x02).
-- Source: pret/pokefirered symbols branch (pokefirered.sym): gMain = 0x030030F0
-- Struct layout (include/main.h): /*0x439*/ inBattle:1
local prev_keys = {}

local function on_frame()
    local keys = input.get()
    if keys["F1"] and not prev_keys["F1"] then scan_ewram_for_pokemon() end
    if keys["F2"] and not prev_keys["F2"] then dump_party_slot0() end
    prev_keys = keys

    local count      = memory.read_u8(M.PARTY_COUNT_ADDR)
    local mapGroup, mapNum = M.getCurrentMap()
    local map_key    = mapGroup .. ":" .. mapNum
    local area_id    = areas[map_key] or ""
    local loc_name   = locations[map_key] or map_key

    -- gMain state/flags — read via profile-aware base address
    -- Log every change so we can see all transitions (including flickers).
    local gmain_state    = memory.read_u8(M.GMAIN_ADDR + 0x438)
    local gmain_flags    = memory.read_u8(M.GMAIN_ADDR + 0x439)
    local in_battle      = M.isInBattle()
    local gmain_sig      = gmain_state * 256 + gmain_flags

    local was_in_battle = prev_battle

    -- Map change
    if map_key ~= prev_map then
        -- Show area_id for encounter zones (Soul Link context); loc_name for towns/buildings
        local display = area_id ~= "" and ("area=" .. area_id) or ("loc=" .. loc_name)
        console.log(string.format("[T1] Map → %s  %s", map_key, display))
        prev_map = map_key
    end

    -- Log every raw gMain change (state byte OR inBattle byte changed)
    if gmain_sig ~= prev_gmain_sig then
        console.log(string.format(
            "[T1] gMain.state=0x%02X  flags=0x%02X  inBattle=%s",
            gmain_state, gmain_flags, tostring(in_battle)))
        prev_gmain_sig = gmain_sig
    end

    -- in_battle binary transition
    if in_battle ~= prev_battle then
        prev_battle = in_battle
    end

    -- Battle start: snapshot full enemy team
    if in_battle and not was_in_battle then
        console.log("[T1] Enemy team:")
        log_enemy_team()
        prev_enemy_hp = {}
    end

    -- Battle end: clear enemy HP tracking
    if not in_battle and was_in_battle then
        prev_enemy_hp = {}
    end

    -- Party count change: print full snapshot and reset HP tracking
    if count ~= prev_count then
        log_party()
        prev_count = count
        prev_hp = {}
    end

    -- Per-slot player HP change
    for i = 0, count - 1 do
        local s = M.readPartySlot(i)
        if s then
            if prev_hp[i] ~= nil and prev_hp[i] ~= s.hp then
                console.log(string.format("[T1] player[%d] HP %d → %d  (Lv%d  key=%s)",
                    i, prev_hp[i], s.hp, s.level, s.key))
            end
            prev_hp[i] = s.hp
        end
    end

    -- Per-slot enemy HP change (only tracked while in battle)
    if in_battle then
        for i = 0, 5 do
            local base  = M.ENEMY_BASE + i * M.MON_SIZE
            local maxHP = memory.read_u16_le(base + M.OFF_MAX_HP)
            if maxHP > 0 then
                local hp  = memory.read_u16_le(base + M.OFF_HP)
                local lv  = memory.read_u8(base + M.OFF_LEVEL)
                local key = string.format("%08X:%08X",
                    memory.read_u32_le(base + M.OFF_PERSONALITY),
                    memory.read_u32_le(base + M.OFF_OTID))
                if prev_enemy_hp[i] ~= nil and prev_enemy_hp[i] ~= hp then
                    console.log(string.format("[T1] enemy[%d] HP %d → %d  (Lv%d  key=%s)",
                        i, prev_enemy_hp[i], hp, lv, key))
                end
                prev_enemy_hp[i] = hp
            end
        end
    end
end

local function on_frame_safe()
    local ok, err = pcall(on_frame)
    if not ok then
        console.log("[T1] ERROR (handler kept alive): " .. tostring(err))
    end
end

event.onframeend(on_frame_safe, "t1_memory")
console.log("[T1] Running — waiting for events…")
