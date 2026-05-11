--[[
  lua/tests/test_gen4_force_faint.lua — Gen 4 (HGSS / Platinum) force-faint test.

  Writes encrypted curHP=0 / maxHP using memory_nds.lua helpers.
  Save a BizHawk state before testing.

  Controls:
    F1/F2/F3 = faint slot 0/1/2
    F4       = restore all HP
    F5       = faint last living mon
    F6       = faint all party mons
--]]

local _src = debug.getinfo(1, "S").source:match("@(.+[/\\])") or ""
local _lua_root = _src:match("(.+[/\\])tests[/\\]") or _src
local _proj_root = _lua_root:match("(.+[/\\])lua[/\\]") or (_lua_root .. "../")
package.path = _src .. "?.lua;"
           .. _lua_root .. "?.lua;"
           .. _lua_root .. "games/?.lua;"
           .. _proj_root .. "data/games/gen4_hgsspt/?.lua;"
           .. package.path

package.loaded["memory_nds"] = nil
package.loaded["games.gen4_hgsspt"] = nil

local M = require("memory_nds")
local game = require("games.gen4_hgsspt")

local variant = game.detect_variant()
local profile = game.profiles[variant] or game.profiles.heartgold
local RAM = profile.RAM_DOMAIN or "Main RAM"
M.applyProfile(profile)

local function log(msg)
    console.log("[T2-G4] " .. msg)
end

local function slot_key_from_addr(addr)
    if not addr then return nil end
    local pid = memory.read_u32_le(addr, RAM)
    if pid == 0 then return nil end
    local _, otid = M.decrypt_block_a(addr)
    if otid then
        return string.format("%08X:%08X", pid, otid)
    end
    return string.format("%08X", pid)
end

local function read_party_slot(slot)
    local s = M.readPartySlot(slot)
    if not s then return nil end
    return {
        key = slot_key_from_addr(M.partyAddr(slot)) or s.key,
        level = s.level,
        hp = s.hp,
        maxHP = s.maxHP,
    }
end

local function live_party_slot(slot)
    local s = M.partyHP(slot) or M.readPartySlot(slot)
    if not s then return nil end
    return {
        key = slot_key_from_addr(M.partyAddr(slot)) or s.key,
        level = s.level,
        hp = s.hp,
        maxHP = s.maxHP,
    }
end

local function live_battle_slot(slot)
    local s = M.battleHP(slot) or M.readBattleSlot(slot)
    if not s then return nil end
    return {
        key = slot_key_from_addr(M.partyAddr(slot)) or s.key,
        level = s.level,
        hp = s.hp,
        maxHP = s.maxHP,
    }
end

local function faint_slot(slot)
    local before_party = read_party_slot(slot)
    if not before_party then
        log(string.format("ACTION faint slot %d skipped (empty)", slot))
        return
    end
    if before_party.hp == 0 then
        log(string.format("ACTION faint slot %d skipped (already fainted) key=%s", slot, before_party.key))
        return
    end

    local before_battle = M.isInBattle() and live_battle_slot(slot) or nil
    M.forceFaint(slot)

    local after_party = read_party_slot(slot)
    local after_battle = M.isInBattle() and live_battle_slot(slot) or nil
    log(string.format(
        "ACTION faint slot %d  party %d->%s  battle %s->%s  key=%s",
        slot,
        before_party.hp,
        after_party and tostring(after_party.hp) or "?",
        before_battle and tostring(before_battle.hp) or "-",
        after_battle and tostring(after_battle.hp) or "-",
        before_party.key))
end

local function restore_all_hp()
    local count = M.readPartyCount()
    for i = 0, count - 1 do
        local before = read_party_slot(i)
        if before then
            M.restoreHP(i)
            local after = read_party_slot(i)
            log(string.format("  restored slot %d: %s -> %s  key=%s", i,
                before.hp, after and after.hp or "?", before.key))
        end
    end
    log(string.format("ACTION restore all HP (%d slots)", count))
end

local function faint_last_living()
    for i = M.readPartyCount() - 1, 0, -1 do
        local s = live_party_slot(i)
        if s and s.hp > 0 then
            log("ACTION faint last living mon")
            faint_slot(i)
            return
        end
    end
    log("ACTION faint last living mon skipped (no living mons)")
end

local function faint_all()
    local count = M.readPartyCount()
    log("ACTION faint all party mons")
    for i = 0, count - 1 do
        faint_slot(i)
    end
end

console.clear()
log(string.format("Variant: %s  detect()=%s", variant, tostring(game.detect())))
log("Controls: F1/F2/F3 faint slot 0/1/2, F4 restore, F5 faint last living, F6 faint all")
log("Monitoring: save load, battle transitions, party HP->0, all-party fainted")

local prev_keys = {}
local prev_party_hp = {}
local prev_in_battle = nil
local prev_all_fainted = false
local save_ready = false
local warned_waiting = false

local function check_party_hp()
    local count = M.readPartyCount()
    for i = 0, count - 1 do
        local p = live_party_slot(i)
        local hp = p and p.hp or 0
        local prev = prev_party_hp[i]
        if prev ~= nil and prev > 0 and hp == 0 then
            local battle = M.isInBattle() and live_battle_slot(i) or nil
            log(string.format("FAINT DETECTED slot %d  party %d->0  battle=%s  key=%s",
                i, prev, battle and tostring(battle.hp) or "-", p and p.key or "?"))
        end
        prev_party_hp[i] = hp
    end
    for i = count, 5 do prev_party_hp[i] = nil end
end

local function check_battle_state()
    local in_battle = M.isInBattle()
    if prev_in_battle ~= nil and in_battle ~= prev_in_battle then
        log("Battle state -> " .. (in_battle and "IN BATTLE" or "OVERWORLD"))
    end
    prev_in_battle = in_battle
end

local function check_all_fainted()
    local all_fainted = M.allPartyFainted()
    if all_fainted and not prev_all_fainted then
        log(M.isInBattle()
            and "ALL PARTY FAINTED (in battle)"
            or  "ALL PARTY FAINTED (overworld)")
    end
    prev_all_fainted = all_fainted
end

local function draw_hud()
    if not save_ready then
        gui.text(2, 2, "[T2-G4] waiting for loaded save", "yellow", "black")
        return
    end

    local count = M.readPartyCount()
    local party_bits = {}
    for i = 0, count - 1 do
        local s = live_party_slot(i)
        if s then
            party_bits[#party_bits + 1] = string.format("P%d:%d/%d", i, s.hp, s.maxHP)
        end
    end
    gui.text(2, 2, string.format("[T2-G4] %s  %s", variant, M.isInBattle() and "BATTLE" or "OVERWORLD"), "white", "black")
    gui.text(2, 14, "Party: " .. table.concat(party_bits, "  "), "white", "black")

    if M.isInBattle() then
        local battle_bits = {}
        for i = 0, count - 1 do
            local s = live_battle_slot(i)
            if s then
                battle_bits[#battle_bits + 1] = string.format("B%d:%d/%d", i, s.hp, s.maxHP)
            end
        end
        gui.text(2, 26, "Battle: " .. table.concat(battle_bits, "  "), "white", "black")
    end
end

local function on_frame()
    local keys = input.get()
    local function pressed(k) return keys[k] and not prev_keys[k] end
    prev_keys = keys

    local base = M.init()
    if not base then
        if save_ready then
            log("Save pointer lost — waiting for loaded save...")
        elseif not warned_waiting then
            log("Waiting for loaded save (M.init() returned nil)...")
            warned_waiting = true
        end
        save_ready = false
        prev_in_battle = nil
        prev_all_fainted = false
        prev_party_hp = {}
        draw_hud()
        return
    end

    if not save_ready then
        warned_waiting = false
        save_ready = true
        local ok, err = M.validateSave()
        log(string.format("Save pointer resolved @ 0x%08X  Validation: %s", base, ok and "OK" or ("FAIL - " .. tostring(err))))
    end

    if pressed("F1") then faint_slot(0) end
    if pressed("F2") then faint_slot(1) end
    if pressed("F3") then faint_slot(2) end
    if pressed("F4") then restore_all_hp() end
    if pressed("F5") then faint_last_living() end
    if pressed("F6") then faint_all() end

    check_battle_state()
    check_party_hp()
    check_all_fainted()
    draw_hud()
end

local function on_frame_safe()
    local ok, err = pcall(on_frame)
    if not ok then log("ERROR (handler kept alive): " .. tostring(err)) end
end

event.onframeend(on_frame_safe, "t2_gen4_force_faint")
log("Running — waiting for events...")
