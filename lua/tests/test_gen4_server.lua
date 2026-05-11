--[[
  lua/tests/test_gen4_server.lua — Gen 4 (HGSS / Platinum) TCP server test.

  Automatic detection:
    area_enter  — zone change into a mapped encounter area
    capture     — new PID:OTID key in party or current PC box
    faint       — any known party mon HP drops to 0
    no_catch    — wild battle ends without a capture in the grace window
    whiteout    — all party mons faint
    safe        — first overworld frame after battle

  Manual controls:
    F1 = area_enter   F2 = capture(slot 0)   F3 = faint(slot 0)
    F4 = no_catch     F5 = whiteout          F6 = safe
    F7 = tick
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
           .. _proj_root .. "data/games/gen4_hgsspt/?.lua;"
           .. package.path

package.loaded["memory_nds"] = nil
package.loaded["games.gen4_hgsspt"] = nil
package.loaded["gen4_hgsspt_locations"] = nil
package.loaded["connector"] = nil
package.loaded["socket"] = nil

local M = require("memory_nds")
local game = require("games.gen4_hgsspt")
local locations = require("gen4_hgsspt_locations")
local C = require("connector")

local variant = game.detect_variant()
local profile = game.profiles[variant] or game.profiles.heartgold
local RAM = profile.RAM_DOMAIN or "Main RAM"
M.applyProfile(profile)

local function log(msg)
    console.log("[T3-G4] " .. msg)
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
    if val == nil then
        return "null"
    elseif t == "boolean" or t == "number" then
        return tostring(val)
    elseif t == "string" then
        return '"' .. val:gsub('\\', '\\\\'):gsub('"', '\\"'):gsub('\n', '\\n') .. '"'
    elseif t == "table" then
        local out = {}
        if json_is_array(val) then
            for _, v in ipairs(val) do out[#out + 1] = json_encode(v) end
            return "[" .. table.concat(out, ",") .. "]"
        end
        for k, v in pairs(val) do
            out[#out + 1] = '"' .. tostring(k) .. '":' .. json_encode(v)
        end
        return "{" .. table.concat(out, ",") .. "}"
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
    local parts = {}
    for _, c in ipairs(cmds) do
        parts[#parts + 1] = c.key and (c.cmd .. "(" .. c.key:sub(1, 8) .. "...)") or c.cmd
    end
    return table.concat(parts, ", ")
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

local function current_area_state()
    local zone = M.readZoneID()
    return {
        zone = zone,
        area = game.resolve_area(zone),
        loc = locations[zone] or locations[tostring(zone)] or ("zone_" .. tostring(zone)),
    }
end

local function indexed_party(in_battle)
    local out = {}
    local count = M.readPartyCount()
    for i = 0, count - 1 do
        local key = slot_key_from_addr(M.partyAddr(i))
        local s = in_battle and (M.battleHP(i) or M.readBattleSlot(i)) or (M.partyHP(i) or M.readPartySlot(i))
        if key and s then
            out[key] = {
                hp = s.hp,
                maxHP = s.maxHP,
                level = s.level,
                slot = i,
            }
        end
    end
    return out, count
end

local function current_box_keys(box)
    local keys = {}
    if box == nil then return keys end
    for slot = 0, 29 do
        local addr = M.pcBoxAddr(box, slot)
        if addr then
            local key = slot_key_from_addr(addr)
            if key then keys[key] = true end
        end
    end
    return keys
end

local writes_enabled = false
local seq = 0
local pending_labels = {}
local save_ready = false
local warned_waiting = false
local was_connected = false

local function send(evt, label, is_auto)
    if not C.connected() then
        log("NOT CONNECTED — dropped: " .. (label or evt.event))
        return
    end
    seq = seq + 1
    evt.seq = seq
    evt.player = PLAYER_ID
    C.send(json_encode(evt))
    local prefix = is_auto and "AUTO" or "MANUAL"
    local silent = (evt.event == "tick")
    pending_labels[#pending_labels + 1] = (silent and "SILENT:" or "") .. prefix .. " " .. (label or evt.event)
end

local function dispatch_commands(cmds)
    for _, c in ipairs(cmds) do
        if c.cmd == "force_faint" and c.key then
            if not writes_enabled then
                log("  ↳ force_faint skipped (writes off) key=" .. c.key)
            else
                local count = M.readPartyCount()
                local found = false
                for slot = 0, count - 1 do
                    if slot_key_from_addr(M.partyAddr(slot)) == c.key then
                        M.forceFaint(slot)
                        log(string.format("  ↳ DISPATCHED force_faint slot=%d key=%s", slot, c.key))
                        found = true
                        break
                    end
                end
                if not found then
                    log("  ↳ force_faint key not in party: " .. c.key)
                end
            end
        elseif c.cmd ~= "noop" then
            log("  ↳ unhandled cmd: " .. tostring(c.cmd))
        end
    end
end

console.clear()
C.init(SERVER_HOST, SERVER_PORT)
log(string.format("Variant: %s  detect()=%s", variant, tostring(game.detect())))
log(string.format("TCP: %s:%d  Player: %s", SERVER_HOST, SERVER_PORT, PLAYER_ID))
log("Auto: area_enter capture faint no_catch whiteout safe")
log("Manual: F1 area_enter  F2 capture(slot 0)  F3 faint(slot 0)  F4 no_catch  F5 whiteout  F6 safe  F7 tick")

local prev_area = ""
local prev_in_battle = false
local prev_safe = false
local prev_party = {}
local prev_all_fainted = false
local prev_keys = {}
local frame_count = 0

local battle_area_id = nil
local battle_is_wild = false
local battle_box_index = nil
local battle_box_snapshot = {}
local captured_this_battle = false
local post_battle_frames = 0
local POST_BATTLE_GRACE = 90
local resolved_areas = {}

local function on_frame()
    frame_count = frame_count + 1

    C.pump()
    local now_connected = C.connected()
    if now_connected ~= was_connected then
        log(now_connected and ("TCP connected to " .. SERVER_HOST .. ":" .. SERVER_PORT)
            or "TCP disconnected — reconnecting...")
        was_connected = now_connected
    end

    local base = M.init()
    if not base then
        if save_ready then
            log("Save pointer lost — waiting for loaded save...")
        elseif not warned_waiting then
            log("Waiting for loaded save (M.init() returned nil)...")
            warned_waiting = true
        end
        save_ready = false
        writes_enabled = false
        prev_area = ""
        prev_in_battle = false
        prev_safe = false
        prev_party = {}
        prev_all_fainted = false
        prev_keys = input.get()
        return
    end

    if not save_ready then
        warned_waiting = false
        save_ready = true
        local ok, err = M.validateSave()
        writes_enabled = ok
        log(string.format("Save pointer resolved @ 0x%08X  Validation: %s  Trainer=%s",
            base, ok and "OK" or ("FAIL - " .. tostring(err)), M.readTrainerName()))
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

    local area_state = current_area_state()
    local area = area_state.area
    local in_battle = M.isInBattle()
    local safe = M.isInOverworld()
    local curr_party, party_count = indexed_party(in_battle)
    local all_fainted = M.allPartyFainted()

    if area ~= prev_area then
        if area ~= "" then
            send({event = "area_enter", area_id = area}, "area_enter:" .. area, true)
            log(string.format("Zone -> %d  area=%s  loc=%s", area_state.zone, area, area_state.loc))
        end
        prev_area = area
    end

    if not prev_in_battle and in_battle then
        battle_area_id = area
        battle_is_wild = M.isWildBattle()
        captured_this_battle = false
        battle_box_index = nil
        battle_box_snapshot = {}
        if party_count >= 6 then
            battle_box_index = M.readCurrentBox()
            battle_box_snapshot = current_box_keys(battle_box_index)
        end
        log(string.format("Battle: start  wild=%s  area=%s  trainer_id=%d",
            tostring(battle_is_wild), battle_area_id ~= "" and battle_area_id or "(none)", M.readEnemyTrainerId()))
    end

    if prev_in_battle and not in_battle then
        post_battle_frames = POST_BATTLE_GRACE
        log("Battle: end  grace window started")
    end

    for key, info in pairs(curr_party) do
        if not prev_party[key] then
            local evt_area = battle_area_id ~= nil and battle_area_id or area
            captured_this_battle = true
            if evt_area and evt_area ~= "" then resolved_areas[evt_area] = true end
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
        post_battle_frames = post_battle_frames - 1
        if battle_box_index ~= nil and not captured_this_battle then
            local cur_box = M.readCurrentBox()
            if cur_box == battle_box_index then
                local cur_keys = current_box_keys(cur_box)
                local new_keys = {}
                for key in pairs(cur_keys) do
                    if not battle_box_snapshot[key] and not prev_party[key] then
                        new_keys[#new_keys + 1] = key
                    end
                end
                if #new_keys == 1 then
                    local evt_area = battle_area_id ~= nil and battle_area_id or area
                    captured_this_battle = true
                    if evt_area and evt_area ~= "" then resolved_areas[evt_area] = true end
                    send({event = "capture", key = new_keys[1], area_id = evt_area},
                        "capture:" .. new_keys[1]:sub(1, 8) .. "(box)", true)
                end
            end
        end
        if post_battle_frames == 0 then
            if battle_is_wild and not captured_this_battle
                    and battle_area_id and battle_area_id ~= ""
                    and not resolved_areas[battle_area_id] then
                resolved_areas[battle_area_id] = true
                send({event = "no_catch", area_id = battle_area_id}, "no_catch:" .. battle_area_id, true)
            end
            captured_this_battle = false
            battle_box_index = nil
            battle_box_snapshot = {}
            battle_area_id = nil
        end
    end

    if all_fainted and not prev_all_fainted then
        send({event = "whiteout"}, "whiteout", true)
    end

    if safe and not prev_safe then
        send({event = "safe"}, "safe", true)
    end

    local keys = input.get()
    local function pressed(k) return keys[k] and not prev_keys[k] end

    if pressed("F1") then
        send({event = "area_enter", area_id = area}, "area_enter:" .. (area ~= "" and area or "(none)"), false)
    end
    if pressed("F2") then
        local key = slot_key_from_addr(M.partyAddr(0))
        local s = M.partyHP(0) or M.readPartySlot(0)
        if key and s then
            send({event = "capture", key = key, level = s.level, hp = s.hp, maxHP = s.maxHP, area_id = area},
                "capture:" .. key:sub(1, 8), false)
        else
            log("F2: slot 0 empty")
        end
    end
    if pressed("F3") then
        local key = slot_key_from_addr(M.partyAddr(0))
        if key then
            send({event = "faint", key = key, area_id = area}, "faint:" .. key:sub(1, 8), false)
        else
            log("F3: slot 0 empty")
        end
    end
    if pressed("F4") then
        send({event = "no_catch", area_id = area}, "no_catch:" .. (area ~= "" and area or "(none)"), false)
    end
    if pressed("F5") then send({event = "whiteout"}, "whiteout", false) end
    if pressed("F6") then send({event = "safe"}, "safe", false) end
    if pressed("F7") then send({event = "tick"}, "tick", false) end
    prev_keys = keys

    if frame_count % 60 == 0 then
        send({event = "tick"}, "tick(auto)", true)
    end

    prev_party = curr_party
    prev_in_battle = in_battle
    prev_safe = safe
    prev_all_fainted = all_fainted
end

local function on_frame_safe()
    local ok, err = pcall(on_frame)
    if not ok then log("ERROR (handler kept alive): " .. tostring(err)) end
end

event.onframeend(on_frame_safe, "t3_gen4_server")
log("Running — waiting for events...")
