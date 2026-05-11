--[[
  lua/tests/test_gen2_server.lua — SERVER CONNECTIVITY + AUTO EVENT TEST FOR GEN 2 CRYSTAL

  Run server first:
      python -m server.server --host 127.0.0.1 --port 54321

  Manual F keys:
    F1 -> area_enter
    F2 -> capture (party slot 0)
    F3 -> faint   (party slot 0)
    F4 -> no_catch
    F5 -> whiteout
    F6 -> safe
    F7 -> tick
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
           .. _proj_root .. "data/games/gen2_crystal/?.lua;"
           .. package.path

package.loaded["memory_gb"] = nil
package.loaded["connector"] = nil
package.loaded["socket"] = nil
package.loaded["games.gen2_crystal"] = nil
package.loaded["gen2_crystal_areas"] = nil
package.loaded["gen2_crystal_locations"] = nil

local M = require("memory_gb")
local C = require("connector")
local G = require("games.gen2_crystal")
local areas = require("gen2_crystal_areas")
local locations = require("gen2_crystal_locations")

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
        local parts = {}
        if json_is_array(val) then
            for _, v in ipairs(val) do
                parts[#parts + 1] = json_encode(v)
            end
            return "[" .. table.concat(parts, ",") .. "]"
        else
            for k, v in pairs(val) do
                parts[#parts + 1] = '"' .. tostring(k) .. '":' .. json_encode(v)
            end
            return "{" .. table.concat(parts, ",") .. "}"
        end
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
        local text = obj:match('"text"%s*:%s*"([^"]*)"')
        if cmd then cmds[#cmds + 1] = {cmd = cmd, key = key, text = text} end
    end
    return cmds
end

local function format_cmds(cmds)
    if #cmds == 0 then return "???" end
    local parts = {}
    for _, c in ipairs(cmds) do
        parts[#parts + 1] = c.key and (c.cmd .. "(" .. c.key:sub(1, 9) .. "...") .. ")" or c.cmd
    end
    return table.concat(parts, ", ")
end

local function resolve_current_area()
    local map_group, map_number = M.getMapGroupAndNumber()
    local composite = map_group * 256 + map_number
    local area_id = areas[composite] or areas[tostring(composite)] or G.resolve_area(map_group, map_number) or ""
    local loc_name = locations[area_id] or string.format("G%d M%d", map_group, map_number)
    return map_group, map_number, composite, area_id, loc_name
end

local function read_party_state()
    local by_slot = {}
    local by_key = {}
    local count = M.getPartyCount()
    for slot = 0, count - 1 do
        local mon = M.readPartySlot(slot)
        if mon and mon.maxHP > 0 and mon.level > 0 then
            mon.slot = slot
            mon.nickname = M.readPartyNickname(slot)
            by_slot[slot] = mon
            by_key[mon.key] = mon
        end
    end
    return by_slot, by_key
end

local function read_box_state()
    local by_key = {}
    local ok_count, count = pcall(M.getBoxCount)
    if not ok_count or not count or count > M.BOX_MAX_MONS then return by_key end
    for slot = 0, count - 1 do
        local ok_slot, mon = pcall(M.readBoxSlot, slot)
        if ok_slot and mon and mon.key then
            mon.slot = slot
            local ok_nick, nick = pcall(M.readBoxNickname, slot)
            mon.nickname = ok_nick and nick or ""
            by_key[mon.key] = mon
        end
    end
    return by_key
end

local function build_party_snapshot()
    local by_slot = select(1, read_party_state())
    local snap = {}
    for slot = 0, 5 do
        local mon = by_slot[slot]
        if mon then
            local entry = {
                key = mon.key,
                hp = mon.hp,
                maxHP = mon.maxHP,
                level = mon.level,
                species_id = mon.species_index,
                nickname = mon.nickname,
            }
            if mon.held_item and mon.held_item > 0 then
                entry.held_item = mon.held_item
            end
            snap[#snap + 1] = entry
        end
    end
    return snap
end

local function build_hello_event(area_id)
    return {
        event = "hello",
        game_id = G.game_id,
        rom_type = G.display_name,
        area_id = area_id,
        has_pokeballs = M.hasPokeballs(),
        ball_count = M.countPokeballs(),
        badges = M.readJohtoBadges(),
        kanto_badges = M.readKantoBadges(),
        in_battle = M.isInBattle(),
        is_trainer_battle = M.isTrainerBattle(),
        trainer_name = M.readPlayerName(),
        party = build_party_snapshot(),
    }
end

local function build_tick_event(area_id)
    return {
        event = "tick",
        area_id = area_id,
        has_pokeballs = M.hasPokeballs(),
        ball_count = M.countPokeballs(),
        badges = M.readJohtoBadges(),
        kanto_badges = M.readKantoBadges(),
        in_battle = M.isInBattle(),
    }
end

M.initProfile(G, "crystal")
local detected = G.detect()
local val_ok, val_err = M.validateROM()
local writes_enabled = val_ok

local seq = 0
local pending_labels = {}
local prev_keys = {}
local frame_count = 0
local was_connected = false
local all_known_keys = {}
local resolved_areas = {}
local post_battle_frames = 0
local POST_BATTLE_GRACE = 15
local battle_area_id = nil
local battle_is_wild = false
local captured_this_battle = false
local battle_box_snapshot = {}
local whiteout_sent = false

local prev_party_slots, prev_party_keys = read_party_state()
local prev_box_keys = read_box_state()
for key in pairs(prev_party_keys) do all_known_keys[key] = true end
for key in pairs(prev_box_keys) do all_known_keys[key] = true end

local _, _, _, start_area = resolve_current_area()
local prev_area = start_area
local prev_in_battle = M.isInBattle()
local prev_safe = not prev_in_battle

local function send(evt, label, is_auto)
    if not C.connected() then
        console.log("[T3-G2] NOT CONNECTED - dropped: " .. (label or evt.event))
        return
    end
    seq = seq + 1
    evt.seq = seq
    evt.player = PLAYER_ID
    C.send(json_encode(evt))
    pending_labels[#pending_labels + 1] = (is_auto and "AUTO " or "MANUAL ") .. (label or evt.event)
end

local function send_tick(area_id, label, is_auto)
    send(build_tick_event(area_id), label or "tick", is_auto)
end

local function dispatch_commands(cmds)
    for _, c in ipairs(cmds) do
        if c.cmd == "force_faint" and c.key then
            if writes_enabled then
                local count = M.getPartyCount()
                local found = false
                for slot = 0, count - 1 do
                    local mon = M.readPartySlot(slot)
                    if mon and mon.key == c.key then
                        M.forceFaint(slot)
                        console.log(string.format("[T3-G2]   -> DISPATCHED force_faint slot=%d key=%s", slot, c.key))
                        found = true
                        break
                    end
                end
                if not found then
                    console.log("[T3-G2]   -> force_faint key not in party: " .. c.key)
                end
            else
                console.log("[T3-G2]   -> force_faint skipped (writes off) key=" .. c.key)
            end
        elseif c.cmd == "hud_show" and c.text then
            console.log("[T3-G2]   -> hud_show: " .. c.text)
        elseif c.cmd ~= "noop" then
            console.log("[T3-G2]   -> unhandled cmd: " .. tostring(c.cmd))
        end
    end
end

console.clear()
C.init(SERVER_HOST, SERVER_PORT)
console.log(string.format("[T3-G2] Detect=%s  Validation=%s  Writes=%s",
    tostring(detected), val_ok and "OK" or ("FAIL - " .. tostring(val_err)), writes_enabled and "ON" or "OFF"))
console.log(string.format("[T3-G2] TCP=%s:%d  Player=%s", SERVER_HOST, SERVER_PORT, PLAYER_ID))
console.log("[T3-G2] Auto: area_enter capture faint no_catch whiteout safe + tick")
console.log("[T3-G2] Manual: F1=area_enter F2=capture F3=faint F4=no_catch F5=whiteout F6=safe F7=tick")
console.log("[T3-G2] Area lookup uses gen2_crystal_areas + gen2_crystal_locations.")

local function on_frame()
    frame_count = frame_count + 1
    C.pump()

    local now_connected = C.connected()
    if now_connected ~= was_connected then
        if now_connected then
            local _, _, _, area_id = resolve_current_area()
            console.log(string.format("[T3-G2] TCP connected to %s:%d", SERVER_HOST, SERVER_PORT))
            send(build_hello_event(area_id), "hello", true)
        else
            console.log("[T3-G2] TCP disconnected - reconnecting...")
        end
        was_connected = now_connected
    end

    while true do
        local line = C.receive()
        if not line then break end
        local label = table.remove(pending_labels, 1) or "?"
        local cmds = parse_command_list(line)
        console.log(string.format("[T3-G2] %s -> %s", label, format_cmds(cmds)))
        dispatch_commands(cmds)
    end

    local _, _, _, area_id, loc_name = resolve_current_area()
    local curr_party_slots, curr_party_keys = read_party_state()
    local curr_box_keys = read_box_state()
    local in_battle = M.isInBattle()
    local safe = not in_battle
    local nuzlocke_active = M.hasPokeballs()

    if area_id ~= prev_area and area_id ~= "" and not in_battle then
        send({event = "area_enter", area_id = area_id}, "area_enter:" .. area_id, true)
        console.log(string.format("[T3-G2] Area -> %s (%s)", area_id, loc_name))
        prev_area = area_id
    elseif area_id ~= prev_area and area_id == "" and not in_battle then
        prev_area = area_id
    end

    if not prev_in_battle and in_battle then
        battle_area_id = area_id ~= "" and area_id or prev_area
        battle_is_wild = M.isWildBattle()
        captured_this_battle = false
        battle_box_snapshot = curr_box_keys
        whiteout_sent = false
        console.log(string.format("[T3-G2] Battle: overworld -> IN BATTLE  wild=%s  area=%s",
            tostring(battle_is_wild), battle_area_id or "(none)"))
    end

    local evolved_new_keys = {}
    for slot = 0, 5 do
        local prev = prev_party_slots[slot]
        local curr = curr_party_slots[slot]
        if prev and curr and prev.key ~= curr.key and prev.key:sub(1, 9) == curr.key:sub(1, 9) then
            all_known_keys[prev.key] = nil
            all_known_keys[curr.key] = true
            evolved_new_keys[curr.key] = true
            console.log(string.format("[T3-G2] Evolution/key change slot=%d %s -> %s",
                slot, prev.key, curr.key))
        end
    end

    for key, mon in pairs(curr_party_keys) do
        if not prev_party_keys[key] and not all_known_keys[key] and not evolved_new_keys[key] then
            local evt_area = battle_area_id or area_id
            local evt = {
                event = "capture",
                key = key,
                level = mon.level,
                hp = mon.hp,
                maxHP = mon.maxHP,
                area_id = evt_area,
                species_id = mon.species_index,
                nickname = mon.nickname,
            }
            if mon.held_item and mon.held_item > 0 then
                evt.held_item = mon.held_item
            end
            captured_this_battle = true
            all_known_keys[key] = true
            if evt_area and evt_area ~= "" then resolved_areas[evt_area] = true end
            send(evt, "capture:" .. key:sub(1, 9), true)
        end
    end

    if nuzlocke_active then
        for key, prev_mon in pairs(prev_party_keys) do
            local curr_mon = curr_party_keys[key]
            if curr_mon and prev_mon.hp > 0 and curr_mon.hp == 0 then
                send({event = "faint", key = key, area_id = area_id}, "faint:" .. key:sub(1, 9), true)
            end
        end
    end

    if prev_in_battle and not in_battle then
        post_battle_frames = POST_BATTLE_GRACE
        console.log("[T3-G2] Battle: IN BATTLE -> overworld (grace window started)")
    end

    if post_battle_frames > 0 then
        for key, mon in pairs(curr_box_keys) do
            if not battle_box_snapshot[key] and not prev_party_keys[key] and not all_known_keys[key] then
                local evt_area = battle_area_id or area_id
                local evt = {
                    event = "capture",
                    key = key,
                    area_id = evt_area,
                    species_id = mon.species_index,
                    nickname = mon.nickname,
                }
                if mon.held_item and mon.held_item > 0 then
                    evt.held_item = mon.held_item
                end
                captured_this_battle = true
                all_known_keys[key] = true
                if evt_area and evt_area ~= "" then resolved_areas[evt_area] = true end
                send(evt, "capture:" .. key:sub(1, 9) .. "(box)", true)
            end
        end

        post_battle_frames = post_battle_frames - 1
        if post_battle_frames == 0 and battle_is_wild and not captured_this_battle
                and nuzlocke_active and battle_area_id and battle_area_id ~= ""
                and not resolved_areas[battle_area_id] then
            resolved_areas[battle_area_id] = true
            send({event = "no_catch", area_id = battle_area_id}, "no_catch:" .. battle_area_id, true)
        end
    end

    if nuzlocke_active then
        local had_alive = false
        local all_zero = next(curr_party_keys) ~= nil
        for key, prev_mon in pairs(prev_party_keys) do
            if prev_mon.hp > 0 then
                had_alive = true
            end
        end
        for _, mon in pairs(curr_party_keys) do
            if mon.hp > 0 then
                all_zero = false
                break
            end
        end
        if had_alive and all_zero and not whiteout_sent then
            whiteout_sent = true
            send({event = "whiteout", area_id = area_id}, "whiteout", true)
        elseif not all_zero then
            whiteout_sent = false
        end
    end

    if safe and not prev_safe then
        send({event = "safe", area_id = area_id}, "safe", true)
    end

    local keys = input.get()
    local function pressed(k) return keys[k] and not prev_keys[k] end

    if pressed("F1") then
        send({event = "area_enter", area_id = area_id}, "area_enter:" .. (area_id ~= "" and area_id or "(none)"), false)
    end
    if pressed("F2") then
        local mon = M.readPartySlot(0)
        if mon then
            local evt = {
                event = "capture",
                key = mon.key,
                level = mon.level,
                hp = mon.hp,
                maxHP = mon.maxHP,
                area_id = area_id,
                species_id = mon.species_index,
                nickname = M.readPartyNickname(0),
            }
            if mon.held_item and mon.held_item > 0 then
                evt.held_item = mon.held_item
            end
            send(evt, "capture:" .. mon.key:sub(1, 9), false)
        else
            console.log("[T3-G2] F2: slot 0 empty")
        end
    end
    if pressed("F3") then
        local mon = M.readPartySlot(0)
        if mon then
            send({event = "faint", key = mon.key, area_id = area_id}, "faint:" .. mon.key:sub(1, 9), false)
        else
            console.log("[T3-G2] F3: slot 0 empty")
        end
    end
    if pressed("F4") then
        send({event = "no_catch", area_id = area_id}, "no_catch:" .. (area_id ~= "" and area_id or "(none)"), false)
    end
    if pressed("F5") then
        send({event = "whiteout", area_id = area_id}, "whiteout", false)
    end
    if pressed("F6") then
        send({event = "safe", area_id = area_id}, "safe", false)
    end
    if pressed("F7") then
        send_tick(area_id, "tick", false)
    end
    prev_keys = keys

    if frame_count % 60 == 0 then
        send_tick(area_id, "tick(auto)", true)
    end

    prev_party_slots = curr_party_slots
    prev_party_keys = curr_party_keys
    prev_box_keys = curr_box_keys
    prev_in_battle = in_battle
    prev_safe = safe
end

local function on_frame_safe()
    local ok2, err2 = pcall(on_frame)
    if not ok2 then
        console.log("[T3-G2] ERROR (handler kept alive): " .. tostring(err2))
    end
end

event.onframeend(on_frame_safe, "t3_gen2_server")
console.log("[T3-G2] Running - waiting for events...")
