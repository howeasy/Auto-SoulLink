--[[
  lua/tests/test_gen2_force_faint.lua — FORCE FAINT + WHITEOUT TEST FOR GEN 2 CRYSTAL

  Controls:
    F1/F2/F3 = faint slot 0/1/2
    F4       = restore all HP
    F5       = faint last living mon
    F6       = faint all
--]]

local _src = debug.getinfo(1, "S").source:match("@(.+[/\\])") or ""
local _lua_root = _src:match("(.+[/\\])tests[/\\]") or _src
local _proj_root = _lua_root:match("(.+[/\\])lua[/\\]") or (_lua_root .. "../")
package.path = _src .. "?.lua;"
           .. _lua_root .. "?.lua;"
           .. _lua_root .. "games/?.lua;"
           .. _proj_root .. "data/games/gen2_crystal/?.lua;"
           .. package.path

package.loaded["memory_gb"] = nil
package.loaded["games.gen2_crystal"] = nil

local M = require("memory_gb")
local G = require("games.gen2_crystal")

M.initProfile(G, "crystal")
local ok, err = M.validateROM()

console.clear()
console.log(string.format("[T2-G2] Validation=%s", ok and "OK" or ("FAIL - " .. tostring(err))))
console.log("[T2-G2] Controls: F1/F2/F3=faint slot 0/1/2  F4=restore  F5=faint last living  F6=faint all")
console.log("[T2-G2] Monitoring battle transitions and HP->0 changes.")

local prev_keys = {}
local prev_hp = {}
local prev_in_battle = nil
local prev_all_fainted = false

local function log(msg)
    console.log("[T2-G2] " .. msg)
end

local function read_slot(slot)
    return M.readPartySlot(slot)
end

local function faint_slot(slot)
    local mon = read_slot(slot)
    if not mon then
        log(string.format("Slot %d is empty - skipped", slot))
        return
    end
    if mon.hp == 0 then
        log(string.format("Slot %d already fainted - key=%s", slot, mon.key))
        return
    end
    M.forceFaint(slot)
    local after = read_slot(slot)
    log(string.format("ACTION: faint slot %d  HP %d->%d  key=%s",
        slot, mon.hp, after and after.hp or -1, mon.key))
end

local function restore_all_hp()
    local count = M.getPartyCount()
    for slot = 0, count - 1 do
        local mon = read_slot(slot)
        if mon and mon.maxHP > 0 then
            local base = M.PARTY_BASE_ADDR + slot * M.PARTY_STRUCT_SIZE
            M.write_u16_be(base + M.HP_OFFSET, mon.maxHP)
            log(string.format("  restored slot %d to %d HP", slot, mon.maxHP))
        end
    end
    log(string.format("ACTION: restore all HP (%d slots)", count))
end

local function faint_last_living()
    local count = M.getPartyCount()
    for slot = count - 1, 0, -1 do
        local mon = read_slot(slot)
        if mon and mon.hp > 0 then
            log("ACTION: faint last living mon")
            faint_slot(slot)
            return
        end
    end
    log("ACTION: faint last living - no living mons found")
end

local function faint_all()
    local count = M.getPartyCount()
    log("ACTION: faint all party mons")
    for slot = 0, count - 1 do
        faint_slot(slot)
    end
end

local function all_party_fainted()
    local count = M.getPartyCount()
    if count == 0 then return false end
    for slot = 0, count - 1 do
        local mon = read_slot(slot)
        if mon and mon.hp > 0 then
            return false
        end
    end
    return true
end

local function check_party_hp()
    local count = M.getPartyCount()
    for slot = 0, count - 1 do
        local mon = read_slot(slot)
        if mon then
            local prev = prev_hp[slot]
            if prev ~= nil and prev > 0 and mon.hp == 0 then
                log(string.format("FAINT DETECTED slot %d  HP %d->0  key=%s", slot, prev, mon.key))
            elseif prev ~= nil and prev ~= mon.hp then
                log(string.format("HP CHANGED slot %d  %d->%d  key=%s", slot, prev, mon.hp, mon.key))
            end
            prev_hp[slot] = mon.hp
        else
            prev_hp[slot] = nil
        end
    end
    for slot = count, 5 do
        prev_hp[slot] = nil
    end
end

local function check_battle_state()
    local in_battle = M.isInBattle()
    if prev_in_battle ~= nil and in_battle ~= prev_in_battle then
        log(string.format("Battle state: %s -> %s",
            prev_in_battle and "IN BATTLE" or "overworld",
            in_battle and (M.isWildBattle() and "wild" or (M.isTrainerBattle() and "trainer" or "battle")) or "overworld"))
    end
    prev_in_battle = in_battle
end

local function check_all_fainted()
    local all_fainted = all_party_fainted()
    if all_fainted and not prev_all_fainted then
        if M.isInBattle() then
            log("ALL PARTY FAINTED (in battle)")
        else
            log("ALL PARTY FAINTED (overworld)")
        end
    end
    prev_all_fainted = all_fainted
end

local function draw_hud()
    local count = M.getPartyCount()
    local lines = {
        string.format("[T2-G2] %s",
            M.isInBattle() and (M.isWildBattle() and "WILD" or (M.isTrainerBattle() and "TRAINER" or "BATTLE")) or "OVERWORLD")
    }

    for slot = 0, count - 1 do
        local mon = read_slot(slot)
        if mon then
            lines[#lines + 1] = string.format("S%d %d/%d", slot, mon.hp, mon.maxHP)
        end
    end

    for i, line in ipairs(lines) do
        gui.text(2, 2 + (i - 1) * 10, line, "white", "black")
    end
end

local function on_frame()
    local keys = input.get()
    local function pressed(k) return keys[k] and not prev_keys[k] end

    if pressed("F1") then faint_slot(0) end
    if pressed("F2") then faint_slot(1) end
    if pressed("F3") then faint_slot(2) end
    if pressed("F4") then restore_all_hp() end
    if pressed("F5") then faint_last_living() end
    if pressed("F6") then faint_all() end
    prev_keys = keys

    check_battle_state()
    check_party_hp()
    check_all_fainted()
    draw_hud()
end

local function on_frame_safe()
    local ok2, err2 = pcall(on_frame)
    if not ok2 then
        log("ERROR (handler kept alive): " .. tostring(err2))
    end
end

event.onframeend(on_frame_safe, "t2_gen2_force_faint")
console.log("[T2-G2] Force faint test running.")
