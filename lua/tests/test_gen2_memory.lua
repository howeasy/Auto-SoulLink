--[[
  lua/tests/test_gen2_memory.lua — LIVE MEMORY READER FOR GEN 2 CRYSTAL
  Read-only. No server needed. Safe to run at any time.

  Controls:
    F1 = dump party slot 0
    F2 = log Poké Ball count (includes Apricorn balls)
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
package.loaded["gen2_crystal_areas"] = nil
package.loaded["gen2_crystal_locations"] = nil

local M = require("memory_gb")
local G = require("games.gen2_crystal")
local areas = require("gen2_crystal_areas")
local locations = require("gen2_crystal_locations")

M.initProfile(G, "crystal")
local detected = G.detect()
local ok, err = M.validateROM()

console.clear()
console.log(string.format("[T1-G2] Detect=%s  Validation=%s",
    tostring(detected), ok and "OK" or ("FAIL - " .. tostring(err))))
console.log(string.format("[T1-G2] Trainer=%s  OT=%04X  Badges=%d",
    M.readPlayerName(), M.readPlayerId(), M.readBadgeCount()))
console.log("[T1-G2] F1=dump party slot 0  F2=ball count")
console.log("[T1-G2] Logging: map changes, battle transitions, enemy team, party snapshots, HP changes.")

local prev_keys = {}
local prev_map = -1
local prev_area = ""
local prev_battle = nil
local prev_count = -1
local prev_hp = {}
local prev_badges = -1

local function area_state()
    local map_group, map_number = M.getMapGroupAndNumber()
    local composite = map_group * 256 + map_number
    local area_id = areas[composite] or areas[tostring(composite)] or G.resolve_area(map_group, map_number) or ""
    local loc_name = locations[area_id] or string.format("G%d M%d", map_group, map_number)
    return map_group, map_number, composite, area_id, loc_name
end

local function held_item_text(item_id)
    if item_id and item_id > 0 then
        return string.format("  item=%02X", item_id)
    end
    return ""
end

local function log_party(reason)
    local count = M.getPartyCount()
    console.log(string.format("[T1-G2] Party snapshot (%s)  count=%d", reason, count))
    for slot = 0, count - 1 do
        local mon = M.readPartySlot(slot)
        if mon then
            local nick = M.readPartyNickname(slot)
            local ot = M.readPartyOTName(slot)
            console.log(string.format(
                "  [%d] Lv%-3d HP %d/%d key=%s species=%03d nick=%s ot=%s%s",
                slot,
                mon.level,
                mon.hp,
                mon.maxHP,
                mon.key,
                mon.species_index or 0,
                nick ~= "" and nick or "(blank)",
                ot ~= "" and ot or "(blank)",
                held_item_text(mon.held_item)))
        else
            console.log(string.format("  [%d] (nil)", slot))
        end
    end
end

local function log_enemy_team()
    local enemy_count = M.getEnemyCount()
    local active = M.readActiveBattleMon()
    local species_list = M.getEnemySpeciesList()
    console.log(string.format("[T1-G2] Enemy team  battle=%s  count=%d",
        M.isWildBattle() and "wild" or (M.isTrainerBattle() and "trainer" or "other"), enemy_count))

    local found = 0
    for slot = 0, math.max(enemy_count - 1, 0) do
        local mon = M.readEnemySlot(slot)
        if mon then
            console.log(string.format("  enemy[%d] Lv%-3d HP %d/%d species=%03d",
                slot, mon.level, mon.hp, mon.maxHP, mon.species_index or 0))
            found = found + 1
        elseif species_list[slot + 1] then
            console.log(string.format("  enemy[%d] species=%03d (species list only)", slot, species_list[slot + 1]))
            found = found + 1
        end
    end

    if active then
        console.log(string.format("  active species=%03d Lv%-3d HP %d/%d party_pos=%d",
            active.species_index or 0,
            active.level or 0,
            active.hp or 0,
            active.maxHP or 0,
            active.party_pos or 0))
        found = found + 1
    end

    if found == 0 then
        console.log("  (no enemy data yet)")
    end
end

local function dump_party_slot0()
    local mon = M.readPartySlot(0)
    local base = M.PARTY_BASE_ADDR
    console.log("[T1-G2] === Party slot 0 dump ===")
    if not mon then
        console.log("[T1-G2] slot 0 is empty")
        return
    end
    console.log(string.format("  nick=%s  ot=%s", M.readPartyNickname(0), M.readPartyOTName(0)))
    console.log(string.format("  key=%s  species=%03d  held=%02X", mon.key, mon.species_index or 0, mon.held_item or 0))
    console.log(string.format("  level=%d  hp=%d  maxHP=%d", mon.level or 0, mon.hp or 0, mon.maxHP or 0))
    console.log(string.format("  +0x00 species   = %02X", M.read_u8(base + M.SPECIES_OFFSET)))
    if M.HELD_ITEM_OFFSET then
        console.log(string.format("  +0x01 held item = %02X", M.read_u8(base + M.HELD_ITEM_OFFSET)))
    end
    console.log(string.format("  +0x06 ot id     = %04X", M.read_u16_be(base + M.OTID_OFFSET)))
    console.log(string.format("  +0x15 dv1       = %02X", M.read_u8(base + M.DV_OFFSET_1)))
    console.log(string.format("  +0x16 dv2       = %02X", M.read_u8(base + M.DV_OFFSET_2)))
    console.log(string.format("  +0x1F level     = %d", M.read_u8(base + M.LEVEL_OFFSET)))
    console.log(string.format("  +0x22 hp        = %d", M.read_u16_be(base + M.HP_OFFSET)))
    console.log(string.format("  +0x24 maxHP     = %d", M.read_u16_be(base + M.MAXHP_OFFSET)))
end

local function log_ball_count()
    console.log(string.format("[T1-G2] Poké Balls=%d  has_pokeballs=%s",
        M.countPokeballs(), tostring(M.hasPokeballs())))
end

local function on_frame()
    local keys = input.get()
    local function pressed(k) return keys[k] and not prev_keys[k] end

    if pressed("F1") then dump_party_slot0() end
    if pressed("F2") then log_ball_count() end
    prev_keys = keys

    local count = M.getPartyCount()
    local map_group, map_number, composite, area_id, loc_name = area_state()
    local in_battle = M.isInBattle()
    local badge_count = M.readBadgeCount()

    if composite ~= prev_map or area_id ~= prev_area then
        console.log(string.format("[T1-G2] Map -> G%d M%d composite=%d area=%s loc=%s",
            map_group, map_number, composite,
            area_id ~= "" and area_id or "(none)",
            loc_name))
        prev_map = composite
        prev_area = area_id
    end

    if badge_count ~= prev_badges then
        console.log(string.format("[T1-G2] Badges -> total=%d  johto=%02X  kanto=%02X",
            badge_count, M.readJohtoBadges(), M.readKantoBadges()))
        prev_badges = badge_count
    end

    if prev_battle ~= nil and in_battle ~= prev_battle then
        console.log(string.format("[T1-G2] Battle -> %s (%s)",
            in_battle and "IN BATTLE" or "overworld",
            in_battle and (M.isWildBattle() and "wild" or (M.isTrainerBattle() and "trainer" or "other")) or "safe"))
        if in_battle then
            log_enemy_team()
        end
    elseif prev_battle == nil and in_battle then
        console.log(string.format("[T1-G2] Battle -> IN BATTLE (%s)",
            M.isWildBattle() and "wild" or (M.isTrainerBattle() and "trainer" or "other")))
        log_enemy_team()
    end
    prev_battle = in_battle

    local hp_changed = false
    if count ~= prev_count then
        log_party("count change")
        prev_count = count
        prev_hp = {}
    end

    for slot = 0, count - 1 do
        local mon = M.readPartySlot(slot)
        if mon then
            local prev = prev_hp[slot]
            if prev ~= nil and prev ~= mon.hp then
                console.log(string.format("[T1-G2] player[%d] HP %d -> %d  Lv%d key=%s",
                    slot, prev, mon.hp, mon.level or 0, mon.key))
                hp_changed = true
            end
            prev_hp[slot] = mon.hp
        end
    end
    for slot = count, 5 do
        prev_hp[slot] = nil
    end

    if hp_changed then
        log_party("hp change")
    end
end

local function on_frame_safe()
    local ok2, err2 = pcall(on_frame)
    if not ok2 then
        console.log("[T1-G2] ERROR (handler kept alive): " .. tostring(err2))
    end
end

event.onframeend(on_frame_safe, "t1_gen2_memory")
console.log("[T1-G2] Running - waiting for events...")
