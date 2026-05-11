--[[
  lua/tests/test_gen5_force_faint.lua — Gen 5 force faint + whiteout validation

  Controls:
    F1/F2/F3 → faint slot 0/1/2
    F4       → restore all HP
    F5       → faint last living mon
    F6       → faint all party mons

  Tag: [T2-G5]
--]]

local _src = debug.getinfo(1, "S").source:match("@(.+[/\\])") or ""
local _lua_root = _src:match("(.+[/\\])tests[/\\]") or _src
local _proj_root = _lua_root:match("(.+[/\\])lua[/\\]") or (_lua_root .. "../")
package.path = _src .. "?.lua;"
           .. _lua_root .. "?.lua;"
           .. _lua_root .. "games/?.lua;"
           .. _proj_root .. "data/games/gen5_bw/?.lua;"
           .. package.path

package.loaded["memory_nds"] = nil
package.loaded["gen5_bw"] = nil

local M = require("memory_nds")
local game = require("gen5_bw")

local RAM = "Main RAM"
local fmt = string.format

local function mem_u32(addr)
    return memory.read_u32_le(addr, RAM)
end

local function log(msg)
    console.log("[T2-G5] " .. msg)
end

local function full_key(addr)
    if not addr then return nil end
    local pid = mem_u32(addr)
    if pid == 0 then return nil end
    local _, ot = M.decrypt_block_a(addr)
    if ot then return fmt("%08X:%08X", pid, ot) end
    return fmt("%08X", pid)
end

local variant = game.detect_variant()
local rom_type = game.rom_type_for_variant(variant)
M.applyProfile(game.profiles[variant])

console.clear()
log(fmt("Variant: %s  rom_type=%s  direct_addr=true", variant, rom_type))
log("Controls: F1/F2/F3=faint slot 0/1/2  F4=restore all  F5=faint last living  F6=faint all")
log("HUD shows party HP and battle HP (when in battle)")

local prev_ready = nil
local prev_in_battle = nil
local prev_all_fainted = false
local prev_live_hp = {}
local prev_keys = {}

local function live_slot(slot, in_battle)
    return in_battle and M.battleHP(slot) or M.partyHP(slot)
end

local function faint_slot(slot)
    local count = M.readPartyCount()
    if slot >= count then
        log(fmt("Slot %d is empty — skipped", slot))
        return
    end
    local addr = M.partyAddr(slot)
    local before = live_slot(slot, M.isInBattle()) or M.readPartySlot(slot)
    if not addr or not before then
        log(fmt("Slot %d unreadable — skipped", slot))
        return
    end
    if before.maxHP == 0 then
        log(fmt("Slot %d empty — skipped", slot))
        return
    end
    if before.hp == 0 then
        log(fmt("Slot %d already fainted — skipped", slot))
        return
    end
    M.forceFaint(slot)
    local after_party = M.partyHP(slot) or M.readPartySlot(slot)
    local after_battle = M.battleHP(slot)
    log(fmt("ACTION: faint slot %d  party HP %d->%d%s  key=%s",
        slot,
        before.hp,
        after_party and after_party.hp or -1,
        after_battle and fmt(" / battle HP->%d", after_battle.hp) or "",
        full_key(addr) or "?"))
end

local function restore_all_hp()
    local count = M.readPartyCount()
    for i = 0, count - 1 do
        local addr = M.partyAddr(i)
        local before = M.partyHP(i) or M.readPartySlot(i)
        if addr and before and before.maxHP > 0 then
            M.restoreHP(i)
            log(fmt("  restored slot %d -> %d  key=%s", i, before.maxHP, full_key(addr) or "?"))
        end
    end
    log(fmt("ACTION: restore all HP (%d slots)", count))
end

local function faint_last_living()
    local count = M.readPartyCount()
    for i = count - 1, 0, -1 do
        local slot = M.partyHP(i) or M.readPartySlot(i)
        if slot and slot.hp > 0 then
            log("ACTION: faint last living mon")
            faint_slot(i)
            return
        end
    end
    log("ACTION: faint last living mon — none alive")
end

local function faint_all()
    local count = M.readPartyCount()
    log("ACTION: faint all party mons")
    for i = 0, count - 1 do
        local slot = M.partyHP(i) or M.readPartySlot(i)
        if slot and slot.hp > 0 then
            M.forceFaint(i)
        end
    end
end

local function check_party_hp(in_battle)
    local count = M.readPartyCount()
    for i = 0, count - 1 do
        local addr = M.partyAddr(i)
        local slot = live_slot(i, in_battle)
        if addr and slot then
            local key = full_key(addr) or slot.key
            local prev = prev_live_hp[i]
            if prev and prev.key == key and prev.hp > 0 and slot.hp == 0 then
                log(fmt("FAINT DETECTED slot %d  HP %d->0  key=%s", i, prev.hp, key))
            elseif prev and prev.key == key and prev.hp ~= slot.hp then
                log(fmt("HP CHANGE slot %d  %d->%d  key=%s", i, prev.hp, slot.hp, key))
            end
            prev_live_hp[i] = {key = key, hp = slot.hp}
        else
            prev_live_hp[i] = nil
        end
    end
    for i = count, 5 do
        prev_live_hp[i] = nil
    end
end

local function draw_hud(in_battle)
    local count = M.readPartyCount()
    local lines = {}
    local party_parts = {}
    for i = 0, count - 1 do
        local slot = M.partyHP(i) or M.readPartySlot(i)
        if slot then
            party_parts[#party_parts + 1] = fmt("P%d:%d/%d", i, slot.hp, slot.maxHP)
        end
    end
    lines[#lines + 1] = "Party: " .. table.concat(party_parts, "  ")
    if in_battle then
        local battle_parts = {}
        for i = 0, count - 1 do
            local slot = M.battleHP(i)
            if slot then
                battle_parts[#battle_parts + 1] = fmt("B%d:%d/%d", i, slot.hp, slot.maxHP)
            end
        end
        lines[#lines + 1] = "Battle: " .. table.concat(battle_parts, "  ")
    end
    for i, line in ipairs(lines) do
        gui.text(2, 2 + (i - 1) * 10, line, "white", "black")
    end
end

local function on_frame()
    local keys = input.get()
    local function pressed(k)
        return keys[k] and not prev_keys[k]
    end

    local base = M.init()
    if base == nil then
        if prev_ready ~= false then
            log("init=nil — save not loaded yet")
        end
        prev_ready = false
        prev_keys = keys
        return
    end
    if prev_ready ~= true then
        local ok, err = M.validateSave()
        log(fmt("init=%s  validateSave=%s", tostring(base), ok and "OK" or ("FAIL - " .. tostring(err))))
    end
    prev_ready = true

    if pressed("F1") then faint_slot(0) end
    if pressed("F2") then faint_slot(1) end
    if pressed("F3") then faint_slot(2) end
    if pressed("F4") then restore_all_hp() end
    if pressed("F5") then faint_last_living() end
    if pressed("F6") then faint_all() end
    prev_keys = keys

    local in_battle = M.isInBattle()
    if in_battle ~= prev_in_battle then
        log(fmt("Battle state: %s -> %s",
            prev_in_battle == nil and "(init)" or (prev_in_battle and "IN BATTLE" or "overworld"),
            in_battle and "IN BATTLE" or "overworld"))
        prev_in_battle = in_battle
    end

    check_party_hp(in_battle)

    local all = M.allPartyFainted()
    if all and not prev_all_fainted then
        log(in_battle and "ALL PARTY FAINTED (battle)" or "ALL PARTY FAINTED (overworld)")
    end
    prev_all_fainted = all

    draw_hud(in_battle)
end

local function on_frame_safe()
    local ok, err = pcall(on_frame)
    if not ok then
        log("ERROR (handler kept alive): " .. tostring(err))
    end
end

event.onframeend(on_frame_safe, "t2_gen5_force_faint")
log("Running — press F1-F6 to test force faint / restore")
