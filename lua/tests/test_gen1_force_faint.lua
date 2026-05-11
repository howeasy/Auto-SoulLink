--[[
  lua/tests/test_gen1_force_faint.lua — FORCE FAINT + WHITEOUT TEST FOR GEN 1

  RAM-write diagnostics for Pokémon Red / Blue / Yellow.

  Controls:
    F1/F2/F3 → faint slot 0/1/2
    F4       → restore all party HP to max HP
    F5       → faint last living mon
    F6       → faint all party mons
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

local M = require("memory_gb")
local game = require("games.gen1_rby")

local fmt = string.format
local TAG = "[T2-G1]"

local variant = game.detect_variant()
if not variant then
    error("Gen 1 RBY ROM not detected")
end
M.initProfile(game, variant)
local ok, err = M.validateROM()

console.clear()
console.log(fmt("%s ROM: %s  Validation: %s", TAG, variant, ok and "OK" or ("FAIL – " .. tostring(err))))
console.log(fmt("%s F1/F2/F3=faint slot 0/1/2  F4=restore  F5=last living  F6=all", TAG))
console.log(TAG .. " Monitoring battle transitions and HP→0 events.")

local prev_keys = {}
local prev_hp = {}
local prev_in_battle = nil
local prev_all_fainted = false

local function log(msg)
    console.log(TAG .. " " .. msg)
end

local function read_mon(slot)
    if slot < 0 or slot >= M.getPartyCount() then
        return nil
    end
    return M.readPartySlot(slot)
end

local function faint_slot(slot)
    local mon = read_mon(slot)
    if not mon then
        log(fmt("slot %d empty — skipped", slot))
        return
    end
    if mon.hp == 0 then
        log(fmt("slot %d already fainted — skipped", slot))
        return
    end
    M.forceFaint(slot)
    local after = read_mon(slot)
    log(fmt("ACTION: faint slot %d  HP %d→%d  key=%s",
        slot, mon.hp, after and after.hp or -1, mon.key))
end

local function restore_all_hp()
    local count = M.getPartyCount()
    for slot = 0, count - 1 do
        local mon = M.readPartySlot(slot)
        if mon and mon.maxHP > 0 then
            local base = M.PARTY_BASE_ADDR + slot * M.PARTY_STRUCT_SIZE
            M.write_u16_be(base + M.HP_OFFSET, mon.maxHP)
            log(fmt("restored slot %d to %d HP  key=%s", slot, mon.maxHP, mon.key))
        end
    end
    log(fmt("ACTION: restore all HP (%d slot(s))", count))
end

local function faint_last_living()
    local count = M.getPartyCount()
    for slot = count - 1, 0, -1 do
        local mon = M.readPartySlot(slot)
        if mon and mon.hp > 0 then
            log("ACTION: faint last living mon")
            faint_slot(slot)
            return
        end
    end
    log("ACTION: faint last living mon — none found")
end

local function faint_all()
    log("ACTION: faint ALL party mons")
    local count = M.getPartyCount()
    for slot = 0, count - 1 do
        faint_slot(slot)
    end
end

local function all_party_fainted()
    local count = M.getPartyCount()
    if count == 0 then return false end
    for slot = 0, count - 1 do
        local mon = M.readPartySlot(slot)
        if mon and mon.hp > 0 then
            return false
        end
    end
    return true
end

local function check_battle_state()
    local in_battle = M.isInBattle()
    if prev_in_battle ~= nil and in_battle ~= prev_in_battle then
        log(fmt("Battle state: %s → %s",
            prev_in_battle and "IN BATTLE" or "overworld",
            in_battle and (M.isWildBattle() and "wild battle" or (M.isTrainerBattle() and "trainer battle" or "battle")) or "overworld"))
    end
    prev_in_battle = in_battle
end

local function check_party_hp()
    local count = M.getPartyCount()
    for slot = 0, count - 1 do
        local mon = M.readPartySlot(slot)
        if mon then
            local prev = prev_hp[slot]
            if prev ~= nil and prev > 0 and mon.hp == 0 then
                log(fmt("FAINT DETECTED slot %d  HP %d→0  key=%s", slot, prev, mon.key))
            elseif prev ~= nil and prev ~= mon.hp then
                log(fmt("HP CHANGE slot %d  %d→%d  key=%s", slot, prev, mon.hp, mon.key))
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

local function check_whiteout()
    local all_fainted = all_party_fainted()
    if all_fainted and not prev_all_fainted then
        if M.isInBattle() then
            log("ALL PARTY FAINTED (battle — whiteout should follow in-game)")
        else
            log("ALL PARTY FAINTED (overworld — no automatic whiteout)")
        end
    end
    prev_all_fainted = all_fainted
end

local function draw_hud()
    local count = M.getPartyCount()
    gui.text(2, 2, fmt("%s %s", TAG, variant), "white", "black")
    gui.text(2, 12, fmt("battle=%s", tostring(M.isInBattle())), "white", "black")
    for slot = 0, count - 1 do
        local mon = M.readPartySlot(slot)
        if mon then
            gui.text(2, 24 + slot * 10,
                fmt("P%d %3d/%-3d %s", slot, mon.hp, mon.maxHP, mon.key:sub(1, 9)),
                mon.hp == 0 and "red" or "white", "black")
        end
    end
end

local function on_frame()
    local keys = input.get()
    local function pressed(name)
        return keys[name] and not prev_keys[name]
    end

    if pressed("F1") then faint_slot(0) end
    if pressed("F2") then faint_slot(1) end
    if pressed("F3") then faint_slot(2) end
    if pressed("F4") then restore_all_hp() end
    if pressed("F5") then faint_last_living() end
    if pressed("F6") then faint_all() end

    prev_keys = keys

    check_battle_state()
    check_party_hp()
    check_whiteout()
    draw_hud()
end

local function on_frame_safe()
    local ok2, err2 = pcall(on_frame)
    if not ok2 then
        log("ERROR (handler kept alive): " .. tostring(err2))
    end
end

event.onframeend(on_frame_safe, "t2_g1_force_faint")
console.log(TAG .. " Force faint test running.")
