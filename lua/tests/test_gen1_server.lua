--[[
  lua/tests/test_gen1_server.lua — SERVER CONNECTIVITY + AUTO EVENT TEST FOR GEN 1

  Connects to the Python TCP server and automatically detects core Gen 1 events.

  Manual F keys:
    F1 → area_enter
    F2 → capture (party slot 0)
    F3 → faint   (party slot 0)
    F4 → no_catch
    F5 → whiteout
    F6 → safe
    F7 → tick
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
           .. _proj_root .. "data/games/gen1_rby/?.lua;"
           .. package.path

package.loaded["memory_gb"] = nil
package.loaded["connector"] = nil
package.loaded["socket"] = nil
package.loaded["games.gen1_rby"] = nil
package.loaded["gen1_rby_locations"] = nil

local M = require("memory_gb")
local C = require("connector")
local game = require("games.gen1_rby")
local locations = require("gen1_rby_locations")

local fmt = string.format
local TAG = "[T3-G1]"

local function json_is_array(t)
    local n = 0
    for _ in pairs(t) do n = n + 1 end
    if n == 0 then return false end
    for i = 1, n do
        if t[i] == nil then return false end
    end
    return true
end

local function json_encode(val)
    local t = type(val)
    if val == nil then
        return "null"
    elseif t == "boolean" then
        return tostring(val)
    elseif t == "number" then
        return tostring(val)
    elseif t == "string" then
        return '"' .. val:gsub('\\', '\\\\'):gsub('"', '\\"'):gsub('\n', '\\n'):gsub('\r', '\\r') .. '"'
    elseif t == "table" then
        local parts = {}
        if json_is_array(val) then
            for i = 1, #val do
                parts[#parts + 1] = json_encode(val[i])
            end
            return "[" .. table.concat(parts, ",") .. "]"
        end
        for k, v in pairs(val) do
            parts[#parts + 1] = '"' .. tostring(k) .. '":' .. json_encode(v)
        end
        return "{" .. table.concat(parts, ",") .. "}"
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
        if cmd then
            cmds[#cmds + 1] = {cmd = cmd, key = key}
        end
    end
    return cmds
end

local function format_cmds(cmds)
    if #cmds == 0 then return "???" end
    local parts = {}
    for _, cmd in ipairs(cmds) do
        parts[#parts + 1] = cmd.key and (cmd.cmd .. "(" .. cmd.key:sub(1, 9) .. ")") or cmd.cmd
    end
    return table.concat(parts, ", ")
end

local variant = game.detect_variant()
if not variant then
    error("Gen 1 RBY ROM not detected")
end
M.initProfile(game, variant)
local val_ok, val_err = M.validateROM()
local writes_enabled = val_ok

local seq = 0
local pending_labels = {}

local function send(evt, label, is_auto)
    if not C.connected() then
        console.log(TAG .. " NOT CONNECTED — dropped: " .. (label or evt.event))
        return
    end
    seq = seq + 1
    evt.seq = seq
    evt.player = PLAYER_ID
    C.send(json_encode(evt))
    local prefix = is_auto and "AUTO" or "MANUAL"
    pending_labels[#pending_labels + 1] = prefix .. " " .. (label or evt.event)
end

local function current_map_id()
    return M.getCurrentMap()
end

local function current_area_id()
    return game.resolve_area(current_map_id()) or ""
end

local function current_area_label()
    local area_id = current_area_id()
    if area_id ~= "" then
        return locations[area_id] or area_id
    end
    return fmt("map 0x%02X", current_map_id())
end

local function build_party_snapshot()
    local snapshot = {}
    local count = M.getPartyCount()
    for slot = 0, count - 1 do
        local mon = M.readPartySlot(slot)
        if mon then
            snapshot[#snapshot + 1] = {
                key = mon.key,
                hp = mon.hp,
                maxHP = mon.maxHP,
                level = mon.level,
                species_id = game.toNatDex(mon.species_index),
                nickname = M.readPartyNickname(slot),
            }
        end
    end
    return snapshot
end

local function index_party()
    local party = {}
    local count = M.getPartyCount()
    for slot = 0, count - 1 do
        local mon = M.readPartySlot(slot)
        if mon then
            party[mon.key] = {
                slot = slot,
                hp = mon.hp,
                maxHP = mon.maxHP,
                level = mon.level,
                species_index = mon.species_index,
            }
        end
    end
    return party
end

local function scan_current_box_keys()
    local keys = {}
    local count = M.getBoxCount()
    for slot = 0, math.min(count, M.BOX_MAX_MONS) - 1 do
        local mon = M.readBoxSlot(slot)
        if mon then
            keys[mon.key] = {
                slot = slot,
                species_index = mon.species_index,
            }
        end
    end
    return keys
end

local function dispatch_commands(cmds)
    for _, cmd in ipairs(cmds) do
        if cmd.cmd == "force_faint" and cmd.key then
            if writes_enabled then
                local count = M.getPartyCount()
                local handled = false
                for slot = 0, count - 1 do
                    local mon = M.readPartySlot(slot)
                    if mon and mon.key == cmd.key then
                        M.forceFaint(slot)
                        console.log(fmt("%s   ↳ DISPATCHED force_faint slot=%d key=%s", TAG, slot, cmd.key))
                        handled = true
                        break
                    end
                end
                if not handled then
                    console.log(TAG .. "   ↳ force_faint key not in party: " .. cmd.key)
                end
            else
                console.log(TAG .. "   ↳ force_faint skipped (writes off): " .. cmd.key)
            end
        elseif cmd.cmd ~= "noop" then
            console.log(TAG .. "   ↳ unhandled cmd: " .. tostring(cmd.cmd))
        end
    end
end

local function send_hello()
    send({
        event = "hello",
        rom_type = variant,
        area_id = current_area_id(),
        has_pokeballs = M.hasPokeballs(),
        ball_count = M.countPokeballs(),
        badges = M.readBadgeCount(),
        trainer_name = M.readPlayerName(),
        in_battle = M.isInBattle(),
        is_trainer_battle = M.isTrainerBattle(),
        party = build_party_snapshot(),
    }, "hello", true)
end

console.clear()
C.init(SERVER_HOST, SERVER_PORT)
console.log(fmt("%s ROM: %s  Validation: %s  Writes: %s",
    TAG, variant, val_ok and "OK" or ("FAIL – " .. tostring(val_err)), writes_enabled and "ON" or "OFF"))
console.log(fmt("%s TCP: %s:%d  Player: %s", TAG, SERVER_HOST, SERVER_PORT, PLAYER_ID))
console.log(TAG .. " Auto: area_enter capture faint no_catch whiteout safe + box capture scan")
console.log(TAG .. " Manual: F1=area_enter F2=capture F3=faint F4=no_catch F5=whiteout F6=safe F7=tick")
console.log(TAG .. " --- monitoring started ---")

local prev_area = current_area_id()
local prev_party = index_party()
local prev_in_battle = M.isInBattle()
local prev_safe = not prev_in_battle
local prev_keys = {}
local frame_count = 0
local was_connected = false

local battle_area_id = nil
local battle_is_wild = false
local captured_this_battle = false
local battle_box_snapshot = {}
local post_battle_frames = 0
local POST_BATTLE_GRACE = 15
local resolved_areas = {}

local function on_frame()
    frame_count = frame_count + 1

    C.pump()

    local connected = C.connected()
    if connected ~= was_connected then
        console.log(fmt("%s TCP: %s", TAG,
            connected and ("connected to " .. SERVER_HOST .. ":" .. SERVER_PORT) or "disconnected — reconnecting…"))
        if connected then
            send_hello()
        end
        was_connected = connected
    end

    while true do
        local line = C.receive()
        if not line then break end
        local label = table.remove(pending_labels, 1) or "?"
        local cmds = parse_command_list(line)
        if label ~= "AUTO tick(auto)" then
            console.log(fmt("%s %s → %s", TAG, label, format_cmds(cmds)))
        end
        dispatch_commands(cmds)
    end

    local area = current_area_id()
    local area_label = current_area_label()
    local party = index_party()
    local in_battle = M.isInBattle()
    local safe = not in_battle

    if area ~= prev_area then
        if area ~= "" then
            send({event = "area_enter", area_id = area}, "area_enter:" .. area, true)
            console.log(fmt("%s Area → %s (%s)", TAG, area, area_label))
        else
            console.log(fmt("%s Area → (unmapped) (%s)", TAG, area_label))
        end
        prev_area = area
    end

    if not prev_in_battle and in_battle then
        battle_area_id = area
        battle_is_wild = M.isWildBattle()
        captured_this_battle = false
        battle_box_snapshot = scan_current_box_keys()
        console.log(fmt("%s Battle START (%s) area=%s", TAG,
            battle_is_wild and "wild" or (M.isTrainerBattle() and "trainer" or "unknown"),
            battle_area_id ~= nil and battle_area_id or ""))
    end

    if prev_in_battle and not in_battle then
        post_battle_frames = POST_BATTLE_GRACE
        console.log(TAG .. " Battle END (grace window started)")
    end

    for key, info in pairs(party) do
        if not prev_party[key] then
            local event_area = battle_area_id or area
            captured_this_battle = true
            if event_area and event_area ~= "" then
                resolved_areas[event_area] = true
            end
            send({
                event = "capture",
                key = key,
                area_id = event_area,
                level = info.level,
                hp = info.hp,
                maxHP = info.maxHP,
                species_id = game.toNatDex(info.species_index),
            }, "capture:" .. key:sub(1, 9), true)
        end
    end

    for key, old in pairs(prev_party) do
        local new = party[key]
        if new and old.hp > 0 and new.hp == 0 then
            send({event = "faint", key = key, area_id = area}, "faint:" .. key:sub(1, 9), true)
        end
    end

    if post_battle_frames > 0 then
        post_battle_frames = post_battle_frames - 1
        local current_box = scan_current_box_keys()
        for key, info in pairs(current_box) do
            if not battle_box_snapshot[key] and not prev_party[key] and not party[key] then
                local event_area = battle_area_id or area
                captured_this_battle = true
                if event_area and event_area ~= "" then
                    resolved_areas[event_area] = true
                end
                send({
                    event = "capture",
                    key = key,
                    area_id = event_area,
                    species_id = game.toNatDex(info.species_index),
                }, "capture:" .. key:sub(1, 9) .. "(box)", true)
                battle_box_snapshot[key] = info
            end
        end
        if post_battle_frames == 0 then
            if battle_is_wild and not captured_this_battle and battle_area_id and battle_area_id ~= "" and not resolved_areas[battle_area_id] then
                resolved_areas[battle_area_id] = true
                send({event = "no_catch", area_id = battle_area_id}, "no_catch:" .. battle_area_id, true)
            end
            captured_this_battle = false
        end
    end

    do
        local had_alive = false
        local all_zero = true
        for key, old in pairs(prev_party) do
            if old.hp > 0 then
                had_alive = true
                local new = party[key]
                if not new or new.hp > 0 then
                    all_zero = false
                end
            end
        end
        if had_alive and all_zero then
            send({event = "whiteout", area_id = area}, "whiteout", true)
        end
    end

    if safe and not prev_safe then
        send({event = "safe", area_id = area}, "safe", true)
    end

    local keys = input.get()
    local function pressed(name)
        return keys[name] and not prev_keys[name]
    end

    if pressed("F1") then
        send({event = "area_enter", area_id = area}, "area_enter:" .. (area ~= "" and area or "(none)"), false)
    end
    if pressed("F2") then
        local mon = M.readPartySlot(0)
        if mon then
            send({
                event = "capture",
                key = mon.key,
                area_id = area,
                level = mon.level,
                hp = mon.hp,
                maxHP = mon.maxHP,
                species_id = game.toNatDex(mon.species_index),
            }, "capture:" .. mon.key:sub(1, 9), false)
        else
            console.log(TAG .. " F2: slot 0 empty")
        end
    end
    if pressed("F3") then
        local mon = M.readPartySlot(0)
        if mon then
            send({event = "faint", key = mon.key, area_id = area}, "faint:" .. mon.key:sub(1, 9), false)
        else
            console.log(TAG .. " F3: slot 0 empty")
        end
    end
    if pressed("F4") then
        send({event = "no_catch", area_id = area}, "no_catch:" .. (area ~= "" and area or "(none)"), false)
    end
    if pressed("F5") then
        send({event = "whiteout", area_id = area}, "whiteout", false)
    end
    if pressed("F6") then
        send({event = "safe", area_id = area}, "safe", false)
    end
    if pressed("F7") then
        send({event = "tick", ball_count = M.countPokeballs(), area_id = area}, "tick", false)
    end
    prev_keys = keys

    if frame_count % 60 == 0 then
        send({event = "tick", ball_count = M.countPokeballs(), area_id = area}, "tick(auto)", true)
    end

    prev_party = party
    prev_in_battle = in_battle
    prev_safe = safe
end

local function on_frame_safe()
    local ok2, err2 = pcall(on_frame)
    if not ok2 then
        console.log(TAG .. " ERROR (handler kept alive): " .. tostring(err2))
    end
end

event.onframeend(on_frame_safe, "t3_g1_server")
console.log(TAG .. " Running — waiting for events…")
