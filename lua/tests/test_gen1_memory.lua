--[[
  lua/tests/test_gen1_memory.lua — LIVE MEMORY READER FOR GEN 1 (RBY)

  Read-only diagnostics for Pokémon Red / Blue / Yellow.
  Safe to run at any time. All output goes to the BizHawk Lua console.

  Controls:
    F1 → dump party slot 0 raw bytes + decoded fields
    F2 → log Pokéball count / hasPokeballs()
--]]

local _src = debug.getinfo(1, "S").source:match("@(.+[/\\])") or ""
local _lua_root = _src:match("(.+[/\\])tests[/\\]") or _src
local _proj_root = _lua_root:match("(.+[/\\])lua[/\\]") or (_lua_root .. "../")
package.path = _src .. "?.lua;"
           .. _lua_root .. "?.lua;"
           .. _lua_root .. "games/?.lua;"
           .. _proj_root .. "data/games/gen1_rby/?.lua;"
           .. package.path

package.loaded["memory_gb"] = nil
package.loaded["games.gen1_rby"] = nil
package.loaded["gen1_rby_areas"] = nil
package.loaded["gen1_rby_locations"] = nil

local M = require("memory_gb")
local game = require("games.gen1_rby")
local locations = require("gen1_rby_locations")

local fmt = string.format
local TAG = "[T1-G1]"

local variant = game.detect_variant()
if not variant then
    error("Gen 1 RBY ROM not detected")
end
M.initProfile(game, variant)
local ok, err = M.validateROM()

console.clear()
console.log(fmt("%s ROM: %s  Validation: %s", TAG, variant, ok and "OK" or ("FAIL – " .. tostring(err))))
console.log(fmt("%s Player=%s  OT=%04X  Badges=%d", TAG, M.readPlayerName(), M.readPlayerId(), M.readBadgeCount()))
console.log(fmt("%s F1=slot0 raw dump  F2=Pokéball count", TAG))
console.log(fmt("%s Logging map changes, battle transitions, party snapshots, HP changes.", TAG))

local prev_map_id = -1
local prev_area_id = ""
local prev_battle = nil
local prev_count = -1
local prev_hp = {}
local prev_keys = {}

local function area_display(area_id, map_id)
    if area_id ~= "" then
        return locations[area_id] or area_id
    end
    return fmt("map 0x%02X", map_id)
end

local function log_party_snapshot(reason)
    local count = M.getPartyCount()
    console.log(fmt("%s Party snapshot (%s) count=%d", TAG, reason, count))
    for slot = 0, count - 1 do
        local mon = M.readPartySlot(slot)
        if mon then
            console.log(fmt("  [%d] Lv%-3d HP %d/%d key=%s species_idx=0x%02X",
                slot, mon.level, mon.hp, mon.maxHP, mon.key, mon.species_index))
        else
            console.log(fmt("  [%d] <empty / unreadable>", slot))
        end
    end
end

local function log_enemy_team()
    local count = M.getEnemyCount()
    console.log(fmt("%s Enemy team count=%d", TAG, count))
    local found = 0
    for slot = 0, math.max(count, 1) - 1 do
        local mon = M.readEnemySlot(slot)
        if mon then
            console.log(fmt("  enemy[%d] Lv%-3d HP %d/%d species_idx=0x%02X",
                slot, mon.level, mon.hp, mon.maxHP, mon.species_index))
            found = found + 1
        end
    end
    if found == 0 then
        local active = M.readActiveBattleMon()
        if active then
            console.log(fmt("  active enemy Lv%-3d HP %d/%d species_idx=0x%02X party_pos=%d",
                active.level, active.hp, active.maxHP, active.species_index, active.party_pos or 0))
        else
            console.log("  (no enemy data yet — battle intro may still be loading)")
        end
    end
end

local function dump_party_slot0()
    local mon = M.readPartySlot(0)
    local base = M.PARTY_BASE_ADDR
    console.log(fmt("%s === Party slot 0 raw dump ===", TAG))
    if mon then
        console.log(fmt("  key=%s  level=%d  hp=%d/%d  species_idx=0x%02X",
            mon.key, mon.level, mon.hp, mon.maxHP, mon.species_index))
        console.log(fmt("  nickname=%s  ot_name=%s", M.readPartyNickname(0), M.readPartyOTName(0)))
    else
        console.log("  slot 0 is empty")
    end
    for row = 0, M.PARTY_STRUCT_SIZE - 1, 11 do
        local bytes = {}
        for i = 0, math.min(10, M.PARTY_STRUCT_SIZE - row - 1) do
            bytes[#bytes + 1] = fmt("%02X", M.read_u8(base + row + i))
        end
        console.log(fmt("  +0x%02X  %s", row, table.concat(bytes, " ")))
    end
    console.log(fmt("  raw HP=%d  raw MaxHP=%d  raw OTID=%04X  raw map=%02X",
        M.read_u16_be(base + M.HP_OFFSET),
        M.read_u16_be(base + M.MAXHP_OFFSET),
        M.read_u16_be(base + M.OTID_OFFSET),
        M.getCurrentMap()))
end

local function log_pokeballs()
    console.log(fmt("%s Pokéballs: has=%s  count=%d", TAG, tostring(M.hasPokeballs()), M.countPokeballs()))
end

local function on_frame()
    local keys = input.get()
    if keys["F1"] and not prev_keys["F1"] then dump_party_slot0() end
    if keys["F2"] and not prev_keys["F2"] then log_pokeballs() end
    prev_keys = keys

    local map_id = M.getCurrentMap()
    local area_id = game.resolve_area(map_id)
    local in_battle = M.isInBattle()
    local count = M.getPartyCount()

    if map_id ~= prev_map_id then
        console.log(fmt("%s Map → 0x%02X  area=%s  display=%s",
            TAG, map_id, area_id ~= "" and area_id or "(unmapped)", area_display(area_id, map_id)))
        prev_map_id = map_id
        prev_area_id = area_id
    end

    if in_battle ~= prev_battle then
        if in_battle then
            local battle_kind = M.isWildBattle() and "wild" or (M.isTrainerBattle() and "trainer" or "unknown")
            console.log(fmt("%s Battle START (%s) area=%s", TAG, battle_kind, area_id ~= "" and area_id or prev_area_id or ""))
            log_enemy_team()
        else
            console.log(fmt("%s Battle END", TAG))
        end
        prev_battle = in_battle
    end

    local snapshot_reason = nil
    if count ~= prev_count then
        snapshot_reason = fmt("party count %d→%d", prev_count, count)
        prev_count = count
    end

    for slot = 0, count - 1 do
        local mon = M.readPartySlot(slot)
        if mon then
            if prev_hp[slot] ~= nil and prev_hp[slot] ~= mon.hp then
                console.log(fmt("%s party[%d] HP %d → %d  Lv%d  key=%s",
                    TAG, slot, prev_hp[slot], mon.hp, mon.level, mon.key))
                snapshot_reason = snapshot_reason or fmt("HP change slot %d", slot)
            end
            prev_hp[slot] = mon.hp
        else
            prev_hp[slot] = nil
        end
    end
    for slot = count, 5 do
        prev_hp[slot] = nil
    end

    if snapshot_reason then
        log_party_snapshot(snapshot_reason)
    end
end

local function on_frame_safe()
    local ok2, err2 = pcall(on_frame)
    if not ok2 then
        console.log(TAG .. " ERROR (handler kept alive): " .. tostring(err2))
    end
end

event.onframeend(on_frame_safe, "t1_g1_memory")
console.log(TAG .. " Running — waiting for events…")
