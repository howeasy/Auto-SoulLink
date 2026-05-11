--[[
  lua/tests/test_gen5_memory.lua — Gen 5 live memory reader
  Read-only diagnostics for Pokémon Black / White / Black 2 / White 2.

  Controls:
    F1 → dump party slot 0
    F2 → log Poké Ball count

  Tag: [T1-G5]
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
package.loaded["gen5_bw_areas"] = nil
package.loaded["gen5_bw_locations"] = nil

local M = require("memory_nds")
local game = require("gen5_bw")
local areas = require("gen5_bw_areas")
local locations = require("gen5_bw_locations")

local RAM = "Main RAM"
local fmt = string.format

local function mem_u32(addr)
    return memory.read_u32_le(addr, RAM)
end

local function log(msg)
    console.log("[T1-G5] " .. msg)
end

local function count_bits(n)
    local c = 0
    while n and n > 0 do
        c = c + (n & 1)
        n = n >> 1
    end
    return c
end

local function full_key(addr)
    if not addr then return nil end
    local pid = mem_u32(addr)
    if pid == 0 then return nil end
    local _, ot = M.decrypt_block_a(addr)
    if ot then
        return fmt("%08X:%08X", pid, ot)
    end
    return fmt("%08X", pid)
end

local function count_pokeballs()
    local addr = M.bagBallsAddr()
    if not addr then return 0 end
    local total = 0
    for i = 0, M.BAG.BALLS_COUNT - 1 do
        local slot = M.readItemSlot(addr, i)
        if slot and slot.qty > 0 and slot.id >= 0x0001 and slot.id <= 0x0010 then
            total = total + slot.qty
        end
    end
    return total
end

local function area_label(zone_id, area_id)
    if area_id ~= "" then
        return fmt("area=%s  loc=%s", area_id, locations[area_id] or area_id)
    end
    return fmt("unmapped zone=%d", zone_id)
end

local function read_live_party(slot, in_battle)
    return in_battle and M.battleHP(slot) or M.partyHP(slot)
end

local function log_party(in_battle)
    local count = M.readPartyCount()
    local badges = count_bits(M.readBadges1()) + count_bits(M.readBadges2())
    local trainer = M.readTrainerName()
    log(fmt("Party snapshot (%d/6) trainer=%s badges=%d balls=%d%s",
        count,
        trainer ~= "" and trainer or "(blank)",
        badges,
        count_pokeballs(),
        in_battle and " [battle]" or ""))
    for i = 0, count - 1 do
        local addr = M.partyAddr(i)
        local raw = M.readPartySlot(i)
        local live = read_live_party(i, in_battle) or raw
        if addr and raw and live then
            log(fmt("  [%d] Lv%-3d HP %d/%d key=%s",
                i, live.level, live.hp, live.maxHP, full_key(addr) or raw.key))
        else
            log(fmt("  [%d] unreadable", i))
        end
    end
end

local function log_enemy_team()
    local found = 0
    for i = 0, 5 do
        local addr = M.enemyBattleAddr(i)
        local slot = M.readEnemySlot(i)
        if addr and slot then
            log(fmt("  enemy[%d] Lv%-3d HP %d/%d key=%s",
                i, slot.level, slot.hp, slot.maxHP, full_key(addr) or slot.key))
            found = found + 1
        end
    end
    if found == 0 then
        log("  (no enemy data yet)")
    end
end

local function dump_party_slot0()
    local addr = M.partyAddr(0)
    local slot = M.readPartySlot(0)
    if not addr or not slot then
        log("slot 0 empty")
        return
    end
    local species, ot, held_item, ability = M.decrypt_block_a_ext(addr)
    local nickname = M.readNickname(addr) or ""
    log("=== Party slot 0 ===")
    log(fmt("  key=%s  nick=%s", full_key(addr) or slot.key, nickname ~= "" and nickname or "-"))
    log(fmt("  species=%d held=%d ability=%d", species or 0, held_item or 0, ability or 0))
    log(fmt("  level=%d hp=%d/%d pid=0x%08X ot=0x%08X",
        slot.level, slot.hp, slot.maxHP, mem_u32(addr), ot or 0))
end

local variant = game.detect_variant()
local rom_type = game.rom_type_for_variant(variant)
local is_bw2 = variant == "pokemon_black_2" or variant == "pokemon_white_2"
local gift_areas = is_bw2 and game.GIFT_AREAS_BW2 or game.GIFT_AREAS_BW1

M.applyProfile(game.profiles[variant])

console.clear()
log(fmt("Variant: %s  rom_type=%s  gift_set=%s", variant, rom_type, is_bw2 and "BW2" or "BW1"))
log(fmt("Gift areas active: %d  memorial_box=%d  direct_addr=true", (function()
    local n = 0
    for _ in pairs(gift_areas) do n = n + 1 end
    return n
end)(), M.MEMORIAL_BOX + 1))
log("Controls: F1=dump party slot 0  F2=log Poké Ball count")
log("Logging: init/save readiness, zone changes, battle transitions, party snapshots, HP changes")

local prev_ready = nil
local prev_zone_id = -1
local prev_in_battle = nil
local prev_party_sig = {}
local prev_party_live = {}
local prev_enemy_live = {}
local prev_trainer = ""
local prev_badges = -1
local prev_keys = {}

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

    if pressed("F1") then dump_party_slot0() end
    if pressed("F2") then log(fmt("Poké Balls in bag: %d", count_pokeballs())) end
    prev_keys = keys

    local zone_id = M.readZoneID()
    local area_id = areas[zone_id] or game.resolve_area(zone_id)
    local in_battle = M.isInBattle()
    local trainer = M.readTrainerName()
    local badges = count_bits(M.readBadges1()) + count_bits(M.readBadges2())
    local count = M.readPartyCount()

    if zone_id ~= prev_zone_id then
        log(fmt("Zone -> %d  %s", zone_id, area_label(zone_id, area_id)))
        log(fmt("Gift area for this variant: %s", tostring(game.is_gift_area(area_id, rom_type))))
        prev_zone_id = zone_id
    end

    if trainer ~= prev_trainer or badges ~= prev_badges then
        log(fmt("Trainer=%s  Badges=%d", trainer ~= "" and trainer or "(blank)", badges))
        prev_trainer = trainer
        prev_badges = badges
    end

    if in_battle ~= prev_in_battle then
        log(fmt("Battle state -> %s  wild=%s  overworld=%s",
            tostring(in_battle), tostring(M.isWildBattle()), tostring(M.isInOverworld())))
        if in_battle then
            log("Enemy team:")
            log_enemy_team()
            prev_enemy_live = {}
        else
            prev_enemy_live = {}
        end
        prev_in_battle = in_battle
    end

    local party_changed = false
    for i = 0, count - 1 do
        local addr = M.partyAddr(i)
        local raw = M.readPartySlot(i)
        local live = read_live_party(i, in_battle) or raw
        local sig = raw and live and addr and fmt("%s|%d|%d|%d", full_key(addr) or raw.key, live.level, live.hp, live.maxHP) or ""
        if prev_party_sig[i] ~= sig then
            party_changed = true
        end
        prev_party_sig[i] = sig
    end
    for i = count, 5 do
        if prev_party_sig[i] and prev_party_sig[i] ~= "" then
            party_changed = true
        end
        prev_party_sig[i] = ""
        prev_party_live[i] = nil
    end
    if party_changed then
        log_party(in_battle)
    end

    for i = 0, count - 1 do
        local addr = M.partyAddr(i)
        local live = read_live_party(i, in_battle)
        if addr and live then
            local key = full_key(addr) or live.key
            local prev = prev_party_live[i]
            if prev and prev.key == key and prev.hp ~= live.hp then
                log(fmt("player[%d] HP %d -> %d  (Lv%d  key=%s)",
                    i, prev.hp, live.hp, live.level, key))
            end
            prev_party_live[i] = {key = key, hp = live.hp}
        else
            prev_party_live[i] = nil
        end
    end

    if in_battle then
        for i = 0, 5 do
            local addr = M.enemyBattleAddr(i)
            local live = M.enemyHP(i)
            if addr and live then
                local key = full_key(addr) or live.key
                local prev = prev_enemy_live[i]
                if prev and prev.key == key and prev.hp ~= live.hp then
                    log(fmt("enemy[%d] HP %d -> %d  (Lv%d  key=%s)",
                        i, prev.hp, live.hp, live.level, key))
                end
                prev_enemy_live[i] = {key = key, hp = live.hp}
            else
                prev_enemy_live[i] = nil
            end
        end
    end
end

local function on_frame_safe()
    local ok, err = pcall(on_frame)
    if not ok then
        log("ERROR (handler kept alive): " .. tostring(err))
    end
end

event.onframeend(on_frame_safe, "t1_gen5_memory")
log("Running — waiting for events…")
