--[[
  lua/tests/test_gen5_server.lua — Gen 5 TCP connectivity + auto event test

  Automatic detection:
    hello, area_enter, capture, faint, no_catch, whiteout, safe, tick

  Manual controls:
    F1 → area_enter
    F2 → capture (party slot 0)
    F3 → faint (party slot 0)
    F4 → no_catch
    F5 → whiteout
    F6 → safe
    F7 → tick

  Tag: [T3-G5]
--]]

local SERVER_HOST = "127.0.0.1"
local SERVER_PORT = 54321
local PLAYER_ID = "a"

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
package.loaded["connector"] = nil
package.loaded["socket"] = nil

local M = require("memory_nds")
local game = require("gen5_bw")
local areas = require("gen5_bw_areas")
local locations = require("gen5_bw_locations")
local C = require("connector")

local RAM = "Main RAM"
local fmt = string.format

local function mem_u32(addr)
    return memory.read_u32_le(addr, RAM)
end

local function log(msg)
    console.log("[T3-G5] " .. msg)
end

local function json_is_array(t)
    local n = 0
    for _ in pairs(t) do n = n + 1 end
    for i = 1, n do
        if t[i] == nil then return false end
    end
    return n > 0
end

local function json_encode(val)
    local t = type(val)
    if val == nil then return "null"
    elseif t == "boolean" then return tostring(val)
    elseif t == "number" then return tostring(val)
    elseif t == "string" then
        return '"' .. val:gsub('\\', '\\\\'):gsub('"', '\\"'):gsub('\n', '\\n') .. '"'
    elseif t == "table" then
        local p = {}
        if json_is_array(val) then
            for _, v in ipairs(val) do p[#p + 1] = json_encode(v) end
            return "[" .. table.concat(p, ",") .. "]"
        end
        for k, v in pairs(val) do
            p[#p + 1] = '"' .. tostring(k) .. '":' .. json_encode(v)
        end
        return "{" .. table.concat(p, ",") .. "}"
    end
    return '"[' .. t .. ']"'
end

local function parse_command_list(raw)
    local cmds = {}
    local arr = raw:match('"commands"%s*:%s*(%b[])')
    if not arr then return cmds end
    for obj in arr:gmatch('%b{}') do
        local cmd = obj:match('"cmd"%s*:%s*"([^"]+)"')
        local key = obj:match('"key"%s*:%s*"([^"]+)"')
        if cmd then cmds[#cmds + 1] = {cmd = cmd, key = key} end
    end
    return cmds
end

local function format_cmds(cmds)
    if #cmds == 0 then return "???" end
    local p = {}
    for _, c in ipairs(cmds) do
        p[#p + 1] = c.key and (c.cmd .. "(" .. c.key:sub(1, 8) .. "...)" ) or c.cmd
    end
    return table.concat(p, ", ")
end

local function full_key(addr)
    if not addr then return nil end
    local pid = mem_u32(addr)
    if pid == 0 then return nil end
    local _, ot = M.decrypt_block_a(addr)
    if ot then return fmt("%08X:%08X", pid, ot) end
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

local function has_pokeballs()
    return count_pokeballs() > 0
end

local function current_area_state()
    local zone_id = M.readZoneID()
    local area_id = areas[zone_id] or game.resolve_area(zone_id)
    local loc_name = area_id ~= "" and (locations[area_id] or area_id) or ("Zone " .. tostring(zone_id))
    return zone_id, area_id, loc_name
end

local function read_live_party_slot(slot, in_battle)
    local addr = M.partyAddr(slot)
    if not addr then return nil end
    local live = in_battle and M.battleHP(slot) or M.partyHP(slot)
    if not live then return nil end
    return {
        key = full_key(addr) or live.key,
        level = live.level,
        hp = live.hp,
        maxHP = live.maxHP,
        slot = slot,
    }
end

local function index_party(in_battle)
    local t = {}
    local count = M.readPartyCount()
    for i = 0, count - 1 do
        local slot = read_live_party_slot(i, in_battle)
        if slot then t[slot.key] = slot end
    end
    return t
end

local function build_party_snapshot(in_battle)
    local snap = {}
    local count = M.readPartyCount()
    for i = 0, count - 1 do
        local slot = read_live_party_slot(i, in_battle)
        if slot then snap[#snap + 1] = slot end
    end
    return snap
end

local function read_box_keys(box)
    local t = {}
    for slot = 0, 29 do
        local addr = M.pcBoxAddr(box, slot)
        local key = addr and full_key(addr) or nil
        if key then t[key] = true end
    end
    return t
end

local function find_new_box_key(box, before)
    for slot = 0, 29 do
        local addr = M.pcBoxAddr(box, slot)
        local key = addr and full_key(addr) or nil
        if key and not before[key] then
            return key
        end
    end
    return nil
end

local function find_party_slot_by_key(key)
    local count = M.readPartyCount()
    for slot = 0, count - 1 do
        local addr = M.partyAddr(slot)
        if addr and full_key(addr) == key then
            return slot
        end
    end
    return nil
end

local function log_enemy_team()
    for i = 0, 5 do
        local addr = M.enemyBattleAddr(i)
        local slot = M.readEnemySlot(i)
        if addr and slot then
            log(fmt("  enemy[%d] Lv%-3d HP %d/%d key=%s", i, slot.level, slot.hp, slot.maxHP, full_key(addr) or slot.key))
        end
    end
end

local writes_enabled = false

local function dispatch_commands(cmds)
    for _, c in ipairs(cmds) do
        if c.cmd == "force_faint" and c.key then
            if not writes_enabled then
                log("  -> force_faint skipped (writes off) key=" .. c.key)
            else
                local slot = find_party_slot_by_key(c.key)
                if slot ~= nil then
                    M.forceFaint(slot)
                    log(fmt("  -> DISPATCHED force_faint slot=%d key=%s", slot, c.key))
                else
                    log("  -> force_faint key not in party: " .. c.key)
                end
            end
        elseif c.cmd ~= "noop" then
            log("  -> unhandled cmd: " .. tostring(c.cmd))
        end
    end
end

local seq = 0
local pending_labels = {}

local function send(evt, label, is_auto, is_silent)
    if not C.connected() then
        log("NOT CONNECTED — dropped: " .. (label or evt.event))
        return
    end
    seq = seq + 1
    evt.seq = seq
    evt.player = PLAYER_ID
    C.send(json_encode(evt))
    local prefix = is_auto and "AUTO" or "MANUAL"
    pending_labels[#pending_labels + 1] = ((is_silent and "SILENT:" or "") .. prefix .. " " .. (label or evt.event))
end

local variant = game.detect_variant()
local rom_type = game.rom_type_for_variant(variant)
M.applyProfile(game.profiles[variant])

console.clear()
C.init(SERVER_HOST, SERVER_PORT)
log(fmt("Variant: %s  rom_type=%s  TCP=%s:%d  player=%s", variant, rom_type, SERVER_HOST, SERVER_PORT, PLAYER_ID))
log("Auto: hello area_enter capture faint no_catch whiteout safe tick")
log("Manual: F1=area_enter F2=capture F3=faint F4=no_catch F5=whiteout F6=safe F7=tick")

local prev_ready = nil
local prev_zone_id = -1
local prev_area = ""
local prev_loc = ""
local prev_party = {}
local prev_in_battle = false
local prev_safe = false
local prev_keys = {}
local frame_count = 0
local was_connected = false

local battle_area_id = nil
local battle_is_wild = false
local captured_this_battle = false
local battle_box_index = nil
local battle_box_snapshot = nil
local post_battle_frames = 0
local POST_BATTLE_GRACE = 30
local resolved_areas = {}
local pending_safe = false

local function on_frame()
    frame_count = frame_count + 1
    local keys = input.get()
    local function pressed(k)
        return keys[k] and not prev_keys[k]
    end

    C.pump()

    local base = M.init()
    if base == nil then
        if prev_ready ~= false then
            log("init=nil — save not loaded yet")
        end
        prev_ready = false
        prev_keys = keys
        return
    end

    if not writes_enabled then
        local ok, err = M.validateSave()
        if ok then
            writes_enabled = true
            log("save validated — writes enabled")
        elseif prev_ready ~= true or frame_count % 300 == 0 then
            log("validateSave FAIL: " .. tostring(err))
        end
    end
    prev_ready = true

    local zone_id, area, loc = current_area_state()
    local in_battle = M.isInBattle()
    local safe_now = M.isInOverworld()

    local now_connected = C.connected()
    if now_connected ~= was_connected then
        if now_connected then
            log("TCP connected to " .. SERVER_HOST .. ":" .. SERVER_PORT)
            send({
                event = "hello",
                rom_type = rom_type,
                area_id = area,
                loc_name = loc,
                zone_id = zone_id,
                trainer_name = M.readTrainerName(),
                badges = M.readBadges1(),
                ball_count = count_pokeballs(),
                has_pokeballs = has_pokeballs(),
                party = build_party_snapshot(false),
            }, "hello", true)
        else
            log("TCP disconnected — reconnecting…")
        end
        was_connected = now_connected
    end

    while true do
        local line = C.receive()
        if not line then break end
        local label = table.remove(pending_labels, 1) or "?"
        local cmds = parse_command_list(line)
        if label:sub(1, 7) ~= "SILENT:" then
            log(label .. " -> " .. format_cmds(cmds))
        end
        dispatch_commands(cmds)
    end

    if zone_id ~= prev_zone_id then
        if area ~= "" then
            send({event = "area_enter", area_id = area, loc_name = loc, zone_id = zone_id}, "area_enter:" .. area, true)
        end
        prev_zone_id = zone_id
        prev_area = area
        prev_loc = loc
    end

    if not prev_in_battle and in_battle then
        battle_area_id = area
        battle_is_wild = M.isWildBattle()
        captured_this_battle = false
        battle_box_index = nil
        battle_box_snapshot = nil
        if M.readPartyCount() == 6 then
            battle_box_index = M.readCurrentBox()
            battle_box_snapshot = read_box_keys(battle_box_index)
        end
        log(fmt("Battle: overworld -> IN BATTLE  wild=%s  area=%s", tostring(battle_is_wild), battle_area_id ~= "" and battle_area_id or "(none)"))
        log_enemy_team()
    end

    if prev_in_battle and not in_battle then
        post_battle_frames = POST_BATTLE_GRACE
        pending_safe = true
        log("Battle: IN BATTLE -> overworld (grace window started)")
    end

    local curr_party = index_party(in_battle)

    for key, info in pairs(curr_party) do
        if not prev_party[key] then
            local evt_area = battle_area_id or area
            captured_this_battle = true
            if evt_area ~= "" then resolved_areas[evt_area] = true end
            send({event = "capture", key = key, level = info.level, hp = info.hp, maxHP = info.maxHP, area_id = evt_area},
                 "capture:" .. key:sub(1, 8), true)
        end
    end

    for key, prev_info in pairs(prev_party) do
        local curr_info = curr_party[key]
        if curr_info and prev_info.hp > 0 and curr_info.hp == 0 then
            send({event = "faint", key = key, area_id = area}, "faint:" .. key:sub(1, 8), true)
        end
    end

    if post_battle_frames > 0 then
        if battle_box_index ~= nil and battle_box_snapshot and not captured_this_battle then
            local new_key = find_new_box_key(battle_box_index, battle_box_snapshot)
            if new_key then
                local evt_area = battle_area_id or area
                captured_this_battle = true
                if evt_area ~= "" then resolved_areas[evt_area] = true end
                send({event = "capture", key = new_key, area_id = evt_area, box_capture = true},
                     "capture:" .. new_key:sub(1, 8) .. "(box)", true)
            end
        end
        post_battle_frames = post_battle_frames - 1
        if post_battle_frames == 0 then
            if battle_is_wild and not captured_this_battle and battle_area_id and battle_area_id ~= ""
                    and not resolved_areas[battle_area_id] then
                resolved_areas[battle_area_id] = true
                send({event = "no_catch", area_id = battle_area_id}, "no_catch:" .. battle_area_id, true)
            end
            captured_this_battle = false
            battle_box_index = nil
            battle_box_snapshot = nil
        end
    end

    do
        local had_alive, all_zero = false, true
        for key, prev_info in pairs(prev_party) do
            if prev_info.hp > 0 then
                had_alive = true
                local curr_info = curr_party[key]
                if not curr_info or curr_info.hp > 0 then
                    all_zero = false
                end
            end
        end
        if had_alive and all_zero then
            send({event = "whiteout"}, "whiteout", true)
        end
    end

    if pending_safe and not in_battle then
        pending_safe = false
        send({event = "safe"}, "safe", true)
    elseif safe_now and not prev_safe and not in_battle then
        send({event = "safe"}, "safe", true)
    end

    if pressed("F1") then
        send({event = "area_enter", area_id = area, loc_name = loc, zone_id = zone_id}, "area_enter:" .. (area ~= "" and area or "(none)"), false)
    end
    if pressed("F2") then
        local slot = read_live_party_slot(0, in_battle)
        if slot then
            send({event = "capture", key = slot.key, level = slot.level, hp = slot.hp, maxHP = slot.maxHP, area_id = area},
                 "capture:" .. slot.key:sub(1, 8), false)
        else
            log("F2: slot 0 empty")
        end
    end
    if pressed("F3") then
        local slot = read_live_party_slot(0, in_battle)
        if slot then
            send({event = "faint", key = slot.key, area_id = area}, "faint:" .. slot.key:sub(1, 8), false)
        else
            log("F3: slot 0 empty")
        end
    end
    if pressed("F4") then
        send({event = "no_catch", area_id = area ~= "" and area or "(none)"}, "no_catch:" .. (area ~= "" and area or "(none)"), false)
    end
    if pressed("F5") then send({event = "whiteout"}, "whiteout", false) end
    if pressed("F6") then send({event = "safe"}, "safe", false) end
    if pressed("F7") then
        send({event = "tick", rom_type = rom_type, area_id = area, loc_name = loc, zone_id = zone_id, in_battle = in_battle,
              ball_count = count_pokeballs(), has_pokeballs = has_pokeballs(), party = build_party_snapshot(in_battle)},
             "tick(manual)", false)
    end
    prev_keys = keys

    if frame_count % 60 == 0 then
        send({event = "tick", rom_type = rom_type, area_id = area, loc_name = loc, zone_id = zone_id, in_battle = in_battle,
              ball_count = count_pokeballs(), has_pokeballs = has_pokeballs(), party = build_party_snapshot(in_battle)},
             "tick(auto)", true, true)
    end

    prev_party = curr_party
    prev_in_battle = in_battle
    prev_safe = safe_now
    prev_area = area
    prev_loc = loc
end

local function on_frame_safe()
    local ok, err = pcall(on_frame)
    if not ok then
        log("ERROR (handler kept alive): " .. tostring(err))
    end
end

do
    local base = M.init()
    if base ~= nil then
        prev_party = index_party(false)
        prev_in_battle = M.isInBattle()
        prev_safe = M.isInOverworld()
        prev_zone_id, prev_area, prev_loc = current_area_state()
        local ok = M.validateSave()
        writes_enabled = ok and true or false
    end
end

event.onframeend(on_frame_safe, "t3_gen5_server")
log("Running — waiting for events…")
