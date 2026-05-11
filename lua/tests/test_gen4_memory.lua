--[[
  lua/tests/test_gen4_memory.lua — Gen 4 (HGSS / Platinum) live memory reader.
  Read-only diagnostics. Safe to run any time.

  Testing criteria:
    1. Variant auto-detect logs heartgold / soulsilver / platinum on startup.
    2. Save warning appears until a save is loaded; reads resume automatically.
    3. Party snapshot logs on load and whenever count / HP changes.
    4. Zone changes log zone ID, area_id, and human-readable location.
    5. Battle state changes log cleanly; enemy team dumps on battle start.
    6. Badge byte changes log correct badge totals.

  Controls:
    F1 = dump party slot 0
    F2 = log ball pocket contents
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
package.loaded["gen4_hgsspt_locations"] = nil

local M = require("memory_nds")
local game = require("games.gen4_hgsspt")
local locations = require("gen4_hgsspt_locations")

local variant = game.detect_variant()
local profile = game.profiles[variant] or game.profiles.heartgold
local RAM = profile.RAM_DOMAIN or "Main RAM"
M.applyProfile(profile)

local function log(msg)
    console.log("[T1-G4] " .. msg)
end

local function bit_count(n)
    local c = 0
    while n and n > 0 do
        c = c + (n % 2)
        n = math.floor(n / 2)
    end
    return c
end

local function slot_key_from_addr(addr)
    if not addr then return nil, nil, nil, nil end
    local pid = memory.read_u32_le(addr, RAM)
    if pid == 0 then return nil, nil, nil, nil end
    local species, otid = M.decrypt_block_a(addr)
    if otid then
        return string.format("%08X:%08X", pid, otid), pid, otid, species
    end
    return string.format("%08X", pid), pid, nil, species
end

local function read_party_slot(slot)
    local s = M.readPartySlot(slot)
    if not s then return nil end
    local addr = M.partyAddr(slot)
    local key, pid, otid, species = slot_key_from_addr(addr)
    return {
        pid = pid,
        otid = otid,
        species = species,
        key = key or s.key,
        level = s.level,
        hp = s.hp,
        maxHP = s.maxHP,
    }
end

local function read_enemy_slot(slot)
    local s = M.readEnemySlot(slot)
    if not s then return nil end
    local addr = M.enemyBattleAddr(slot)
    local key, pid, otid, species = slot_key_from_addr(addr)
    return {
        pid = pid,
        otid = otid,
        species = species,
        key = key or s.key,
        level = s.level,
        hp = s.hp,
        maxHP = s.maxHP,
    }
end

local function log_party()
    local count = M.readPartyCount()
    log(string.format("Party snapshot (%d/6):", count))
    for i = 0, count - 1 do
        local s = read_party_slot(i)
        if s then
            log(string.format("  [%d] Lv%-3d HP %d/%d  key=%s", i, s.level, s.hp, s.maxHP, s.key))
        else
            log(string.format("  [%d] unreadable", i))
        end
    end
end

local function log_enemy_team()
    log("Enemy team:")
    local found = 0
    for i = 0, 5 do
        local s = read_enemy_slot(i)
        if s then
            log(string.format("  enemy[%d] Lv%-3d HP %d/%d  key=%s", i, s.level, s.hp, s.maxHP, s.key))
            found = found + 1
        end
    end
    if found == 0 then
        log("  (no enemy data yet)")
    end
end

local function dump_slot0()
    local s = read_party_slot(0)
    local addr = M.partyAddr(0)
    if not s or not addr then
        log("F1: party slot 0 empty / unreadable")
        return
    end
    log("=== Party slot 0 dump ===")
    log(string.format("  addr=0x%08X  pid=0x%08X  otid=%s", addr, s.pid or 0, s.otid and string.format("0x%08X", s.otid) or "(nil)"))
    log(string.format("  key=%s  species=%s  level=%d", s.key, tostring(s.species), s.level))
    log(string.format("  hp=%d/%d", s.hp, s.maxHP))
    local nick = M.readNickname(addr)
    if nick then
        log("  nickname=" .. nick)
    end
end

local function log_ball_pocket()
    local addr = M.bagBallsAddr()
    if not addr then
        log("F2: ball pocket unavailable (save not loaded)")
        return
    end
    local total = 0
    log(string.format("Ball pocket @ 0x%08X:", addr))
    for i = 0, (profile.BALLS_POCKET_COUNT or M.BAG.BALLS_COUNT or 0) - 1 do
        local item = M.readItemSlot(addr, i)
        if item.id ~= 0 and item.qty > 0 then
            total = total + item.qty
            log(string.format("  [%02d] item=0x%04X qty=%d", i, item.id, item.qty))
        end
    end
    log("Total balls: " .. total)
end

console.clear()
log(string.format("Variant: %s  detect()=%s", variant, tostring(game.detect())))
log("F1=dump party slot 0  F2=log ball pocket")
log("Monitoring: save load, zone changes, battle transitions, party HP, badges")

local prev_keys = {}
local prev_zone = nil
local prev_in_battle = nil
local prev_count = -1
local prev_party = {}
local prev_enemy_hp = {}
local prev_badges1 = nil
local prev_badges2 = nil
local save_ready = false
local warned_waiting = false

local function on_frame()
    local keys = input.get()
    local function pressed(k) return keys[k] and not prev_keys[k] end

    if pressed("F1") then dump_slot0() end
    if pressed("F2") then log_ball_pocket() end
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
        prev_count = -1
        prev_zone = nil
        prev_in_battle = nil
        prev_party = {}
        prev_enemy_hp = {}
        prev_badges1 = nil
        prev_badges2 = nil
        return
    end

    if not save_ready then
        warned_waiting = false
        save_ready = true
        local ok, err = M.validateSave()
        log(string.format("Save pointer resolved @ 0x%08X  Validation: %s", base, ok and "OK" or ("FAIL - " .. tostring(err))))
        log(string.format("Trainer=%s  Badges1=0x%02X  Badges2=0x%02X", M.readTrainerName(), M.readBadges1(), M.readBadges2()))
    end

    local zone = M.readZoneID()
    local area = game.resolve_area(zone)
    local loc = locations[zone] or locations[tostring(zone)] or ("zone_" .. tostring(zone))
    local in_battle = M.isInBattle()
    local count = M.readPartyCount()
    local badges1 = M.readBadges1()
    local badges2 = M.readBadges2()

    if zone ~= prev_zone then
        log(string.format("Zone -> %d  %s  loc=%s", zone, area ~= "" and ("area=" .. area) or "area=(none)", loc))
        prev_zone = zone
    end

    if in_battle ~= prev_in_battle then
        log("Battle state -> " .. (in_battle and "IN BATTLE" or "OVERWORLD"))
        if in_battle then
            log_enemy_team()
            prev_enemy_hp = {}
        else
            prev_enemy_hp = {}
        end
        prev_in_battle = in_battle
    end

    if badges1 ~= prev_badges1 or badges2 ~= prev_badges2 then
        log(string.format(
            "Badges -> set1 0x%02X (%d)  set2 0x%02X (%d)  total=%d",
            badges1, bit_count(badges1), badges2, bit_count(badges2), bit_count(badges1) + bit_count(badges2)))
        prev_badges1 = badges1
        prev_badges2 = badges2
    end

    local snapshot_changed = (count ~= prev_count)
    local curr_party = {}
    for i = 0, count - 1 do
        local s = read_party_slot(i)
        curr_party[i] = s
        local prev = prev_party[i]
        if s then
            if prev and prev.hp ~= s.hp then
                log(string.format("player[%d] HP %d -> %d  (Lv%d  key=%s)", i, prev.hp, s.hp, s.level, s.key))
            end
            if (not prev)
                    or prev.hp ~= s.hp
                    or prev.maxHP ~= s.maxHP
                    or prev.level ~= s.level
                    or prev.key ~= s.key then
                snapshot_changed = true
            end
        elseif prev then
            snapshot_changed = true
        end
    end
    for i = count, 5 do
        if prev_party[i] ~= nil then
            snapshot_changed = true
        end
    end
    if snapshot_changed then
        log_party()
        prev_count = count
    end
    prev_party = curr_party

    if in_battle then
        for i = 0, 5 do
            local s = read_enemy_slot(i)
            if s then
                if prev_enemy_hp[i] ~= nil and prev_enemy_hp[i] ~= s.hp then
                    log(string.format("enemy[%d] HP %d -> %d  (Lv%d  key=%s)", i, prev_enemy_hp[i], s.hp, s.level, s.key))
                end
                prev_enemy_hp[i] = s.hp
            else
                prev_enemy_hp[i] = nil
            end
        end
    end
end

local function on_frame_safe()
    local ok, err = pcall(on_frame)
    if not ok then log("ERROR (handler kept alive): " .. tostring(err)) end
end

event.onframeend(on_frame_safe, "t1_gen4_memory")
log("Running — waiting for events...")
