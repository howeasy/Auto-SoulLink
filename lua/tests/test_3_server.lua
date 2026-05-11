--[[
  lua/test_3_server.lua — SERVER CONNECTIVITY + AUTO EVENT TEST

  Connects to the Python TCP server and automatically detects + sends every
  SLink event type as they happen in the game.  All output goes to the Lua
  console — no GUI overlay.

  Transport: LuaSocket TCP (non-blocking, Archipelago technique).
  Requires: server running + lua/x64/socket-windows-5-4.dll present.

  Run server first:
      python -m server.server --host 127.0.0.1 --port 54321

  Configure SERVER_HOST, SERVER_PORT, and PLAYER_ID below, then load.

  Automatic detection:
    area_enter  — mapGroup+mapNum changes to an encounter zone
    capture     — new monKey in party; OR new key in current PC box when party=6
    faint       — any party HP drops to 0
    no_catch    — wild battle ends, no capture found within grace window
    whiteout    — all party mons at HP=0 (transition from any-alive)
    safe        — first frame back in overworld after battle

  Manual F keys:
    F1  → area_enter  (current area_id)
    F2  → capture     (party slot 0)
    F3  → faint       (party slot 0)
    F4  → no_catch    (current area_id)
    F5  → whiteout
    F6  → safe
    F7  → tick        (manual poll)

  ┌─ TESTING CRITERIA ────────────────────────────────────────────────────────
  │  ✓ "[T3] TCP connected to 127.0.0.1:54321" on startup
  │  ✓ Walk into route → "[T3] AUTO area_enter:route_N → noop"
  │  ✓ Catch a Pokémon (party not full) → "[T3] AUTO capture:<key> → noop"
  │  ✓ Catch with party=6 → "[T3] AUTO capture:<key> → noop" (from box)
  │  ✓ Party mon HP→0 → "[T3] AUTO faint:<key>"
  │  ✓ Flee/KO in wild battle → "[T3] AUTO no_catch:route_N"
  │    (trainer battle ends → no no_catch fired)
  │  ✓ All party fainted → "[T3] AUTO whiteout"
  │  ✓ Battle start/end logged to console
  │
  │  FAIL: no_catch after successful catch → battle detection bug
  │  FAIL: trainer battle fires no_catch   → gBattleTypeFlags bug
  └───────────────────────────────────────────────────────────────────────────
--]]

-- ── CONFIGURE ─────────────────────────────────────────────────────────────────
local SERVER_HOST = "127.0.0.1"
local SERVER_PORT = 54321
local PLAYER_ID   = "a"   -- "a" = FireRed, "b" = LeafGreen
-- ─────────────────────────────────────────────────────────────────────────────

-- ── Module loading ────────────────────────────────────────────────────────────
local _src = debug.getinfo(1, "S").source:match("@(.+[/\\])") or ""
local _lua_root = _src:match("(.+[/\\])tests[/\\]") or _src
local _proj_root = _lua_root:match("(.+[/\\])lua[/\\]") or (_lua_root .. "../")
package.path = _src .. "?.lua;"
           .. _lua_root .. "?.lua;"
           .. _proj_root .. "data/games/gen3_frlge/?.lua;"
           .. package.path

package.loaded["memory_gba"]        = nil
package.loaded["gen3_frlge_areas"]  = nil
package.loaded["connector"] = nil
package.loaded["socket"]    = nil

local M     = require("memory_gba")
local areas = require("gen3_frlge_areas")
local C     = require("connector")

-- ── JSON encoder ──────────────────────────────────────────────────────────────
local function json_is_array(t)
    local n = 0; for _ in pairs(t) do n = n + 1 end
    for i = 1, n do if t[i] == nil then return false end end
    return n > 0
end
local function json_encode(val)
    local t = type(val)
    if val == nil         then return "null"
    elseif t == "boolean" then return tostring(val)
    elseif t == "number"  then return tostring(val)
    elseif t == "string"  then
        return '"' .. val:gsub('\\','\\\\'):gsub('"','\\"'):gsub('\n','\\n') .. '"'
    elseif t == "table" then
        if json_is_array(val) then
            local p = {}; for _, v in ipairs(val) do p[#p+1] = json_encode(v) end
            return "[" .. table.concat(p, ",") .. "]"
        else
            local p = {}
            for k, v in pairs(val) do p[#p+1] = '"'..tostring(k)..'":'..json_encode(v) end
            return "{" .. table.concat(p, ",") .. "}"
        end
    else return '"['..t..']"' end
end

-- ── Response parsing ──────────────────────────────────────────────────────────
local function parse_command_list(raw)
    local cmds = {}
    local arr = raw:match('"commands"%s*:%s*(%b[])')
    if not arr then return cmds end
    for obj in arr:gmatch('%b{}') do
        local cmd = obj:match('"cmd"%s*:%s*"([^"]+)"')
        local key = obj:match('"key"%s*:%s*"([^"]+)"')
        if cmd then cmds[#cmds+1] = {cmd=cmd, key=key} end
    end
    return cmds
end
local function format_cmds(cmds)
    if #cmds == 0 then return "???" end
    local p = {}
    for _, c in ipairs(cmds) do
        p[#p+1] = c.key and (c.cmd.."("..c.key:sub(1,8).."...)") or c.cmd
    end
    return table.concat(p, ", ")
end

-- ── Command dispatcher ────────────────────────────────────────────────────────
local writes_enabled = false

local function dispatch_commands(cmds)
    for _, c in ipairs(cmds) do
        if c.cmd == "force_faint" and c.key then
            if writes_enabled then
                local count = memory.read_u8(M.PARTY_COUNT_ADDR)
                local found = false
                for slot = 0, count - 1 do
                    local base = M.PARTY_BASE + slot * M.MON_SIZE
                    if M.monKey(base) == c.key then
                        M.forceFaint(slot)
                        console.log(string.format("[T3]   ↳ DISPATCHED force_faint slot=%d key=%s", slot, c.key))
                        found = true; break
                    end
                end
                if not found then console.log("[T3]   ↳ force_faint key not in party: " .. c.key) end
            else
                console.log("[T3]   ↳ force_faint skipped (writes off) key=" .. c.key)
            end
        elseif c.cmd ~= "noop" then
            console.log("[T3]   ↳ unhandled cmd: " .. tostring(c.cmd))
        end
    end
end

-- ── Send / receive ────────────────────────────────────────────────────────────
local seq            = 0
local pending_labels = {}

local function send(evt, label, is_auto)
    if not C.connected() then
        console.log("[T3] NOT CONNECTED — dropped: " .. (label or evt.event))
        return
    end
    seq = seq + 1; evt.seq = seq; evt.player = PLAYER_ID
    C.send(json_encode(evt))
    local prefix    = is_auto and "AUTO" or "MANUAL"
    local is_silent = (evt.event == "tick")
    local lbl       = (is_silent and "SILENT:" or "") .. prefix .. " " .. (label or evt.event)
    pending_labels[#pending_labels+1] = lbl
end

-- ── Helpers ───────────────────────────────────────────────────────────────────
local function current_area_id()
    local g, n = M.getCurrentMap()
    return areas[g .. ":" .. n] or ""
end

local function index_party()
    local t = {}
    local count = memory.read_u8(M.PARTY_COUNT_ADDR)
    for i = 0, count - 1 do
        local base = M.PARTY_BASE + i * M.MON_SIZE
        if M.slotOccupied(base) then
            local k = M.monKey(base)
            t[k] = {
                hp    = memory.read_u16_le(base + M.OFF_HP),
                maxHP = memory.read_u16_le(base + M.OFF_MAX_HP),
                level = memory.read_u8(base + M.OFF_LEVEL),
                slot  = i,
            }
        end
    end
    return t
end

-- ── ROM validation ────────────────────────────────────────────────────────────
M.initProfile()
local rom_type = M.detectROM()
local val_ok, val_err = M.validateROM()
if val_ok then writes_enabled = true end

-- ── Startup ───────────────────────────────────────────────────────────────────
console.clear()
C.init(SERVER_HOST, SERVER_PORT)
console.log(string.format("[T3] ROM: %s  Validation: %s  Writes: %s",
    rom_type, val_ok and "OK" or ("FAIL – "..tostring(val_err)),
    writes_enabled and "ON" or "OFF"))
console.log(string.format("[T3] TCP: %s:%d  Player: %s", SERVER_HOST, SERVER_PORT, PLAYER_ID))
console.log("[T3] Auto: area_enter capture faint no_catch(wild only) whiteout safe + battle state")
console.log("[T3] Manual: F1=area_enter F2=capture(s0) F3=faint(s0) F4=no_catch F5=whiteout F6=safe F7=tick")
console.log("[T3] --- monitoring started ---")

-- ── Per-frame state ───────────────────────────────────────────────────────────
local prev_area      = current_area_id()
local prev_party     = index_party()
local prev_in_battle = M.isInBattle()
local prev_safe      = false
local prev_keys      = {}
local frame_count    = 0
local was_connected  = false

-- Battle-scoped capture tracking (reset on each battle start):
local battle_area_id       = nil
local battle_is_wild       = false
local captured_this_battle = false
local battle_box_index     = nil
local battle_box_snapshot  = {}
local post_battle_frames   = 0
local POST_BATTLE_GRACE    = 15
-- Per-session: areas that already had a capture or no_catch outcome.
local resolved_areas       = {}

local function on_frame()
    frame_count = frame_count + 1

    -- 1. Drive TCP
    C.pump()

    -- 2. Log connection changes
    local now_connected = C.connected()
    if now_connected ~= was_connected then
        console.log(string.format("[T3] TCP: %s",
            now_connected
            and ("connected to "..SERVER_HOST..":"..SERVER_PORT)
            or  "disconnected — reconnecting…"))
        was_connected = now_connected
    end

    -- 3. Dispatch received responses
    while true do
        local line = C.receive()
        if not line then break end
        local label = table.remove(pending_labels, 1) or "?"
        local cmds  = parse_command_list(line)
        if label:sub(1,7) ~= "SILENT:" then
            console.log(string.format("[T3] %s → %s", label, format_cmds(cmds)))
        end
        dispatch_commands(cmds)
    end

    -- 4. Read current state
    local area        = current_area_id()
    local curr_party  = index_party()
    local in_battle   = M.isInBattle()
    local safe        = M.isInOverworld()

    -- AUTO: area_enter
    if area ~= prev_area then
        if area ~= "" then send({event="area_enter", area_id=area}, "area_enter:"..area, true) end
        prev_area = area
    end

    -- Battle start: snapshot context
    if not prev_in_battle and in_battle then
        battle_area_id       = area
        captured_this_battle = false
        battle_is_wild       = M.isWildBattle()
        local party_count    = memory.read_u8(M.PARTY_COUNT_ADDR)
        if party_count == 6 then
            battle_box_index, battle_box_snapshot = M.readCurrentBox()
        else
            battle_box_index    = nil
            battle_box_snapshot = {}
        end
        console.log(string.format("[T3] Battle: overworld → IN BATTLE  wild=%s  area=%s",
            tostring(battle_is_wild), battle_area_id or "(none)"))
    end

    -- Battle end: start grace window
    if prev_in_battle and not in_battle then
        post_battle_frames = POST_BATTLE_GRACE
        console.log("[T3] Battle: IN BATTLE → overworld (grace window started)")
    end

    -- AUTO: capture from PARTY (new key)
    for k, info in pairs(curr_party) do
        if not prev_party[k] then
            local evt_area = battle_area_id or area
            captured_this_battle = true
            resolved_areas[evt_area] = true
            send({event="capture", key=k, level=info.level, hp=info.hp, maxHP=info.maxHP,
                  area_id=evt_area}, "capture:"..k:sub(1,8), true)
        end
    end

    -- AUTO: faint (HP → 0 for known mon)
    for k, prev_info in pairs(prev_party) do
        local curr_info = curr_party[k]
        if curr_info and prev_info.hp > 0 and curr_info.hp == 0 then
            send({event="faint", key=k, area_id=area}, "faint:"..k:sub(1,8), true)
        end
    end

    -- Post-battle grace window: box capture check + no_catch decision
    if post_battle_frames > 0 then
        post_battle_frames = post_battle_frames - 1

        if battle_box_index ~= nil then
            local curr_box_idx, curr_box_keys = M.readCurrentBox()
            if curr_box_idx == battle_box_index then
                local new_keys = {}
                for k in pairs(curr_box_keys) do
                    if not battle_box_snapshot[k] and not prev_party[k] then
                        new_keys[#new_keys+1] = k
                    end
                end
                if #new_keys == 1 then
                    local k        = new_keys[1]
                    local evt_area = battle_area_id or area
                    captured_this_battle   = true
                    battle_box_snapshot[k] = true
                    resolved_areas[evt_area] = true
                    send({event="capture", key=k, area_id=evt_area},
                         "capture:"..k:sub(1,8).."(box)", true)
                end
            end
        end

        if post_battle_frames == 0 then
            if battle_is_wild and not captured_this_battle
                    and battle_area_id and battle_area_id ~= ""
                    and not resolved_areas[battle_area_id] then
                resolved_areas[battle_area_id] = true
                send({event="no_catch", area_id=battle_area_id},
                     "no_catch:"..battle_area_id, true)
            end
            captured_this_battle = false
        end
    end

    -- AUTO: whiteout (all-alive → all-zero transition)
    do
        local had_alive, all_zero = false, true
        for k, prev_info in pairs(prev_party) do
            if prev_info.hp > 0 then
                had_alive = true
                local ci  = curr_party[k]
                if not ci or ci.hp > 0 then all_zero = false end
            end
        end
        if had_alive and all_zero then
            send({event="whiteout"}, "whiteout", true)
        end
    end

    -- AUTO: safe (first overworld frame)
    if safe and not prev_safe then
        send({event="safe"}, "safe", true)
    end

    -- Manual F keys
    local keys = input.get()
    local function pressed(k) return keys[k] and not prev_keys[k] end

    if pressed("F1") then
        send({event="area_enter", area_id=area}, "area_enter:"..(area~="" and area or "(none)"), false)
    end
    if pressed("F2") then
        if M.slotOccupied(M.PARTY_BASE) then
            local k  = M.monKey(M.PARTY_BASE)
            local lv = memory.read_u8(M.PARTY_BASE + M.OFF_LEVEL)
            local hp = memory.read_u16_le(M.PARTY_BASE + M.OFF_HP)
            local mx = memory.read_u16_le(M.PARTY_BASE + M.OFF_MAX_HP)
            send({event="capture", key=k, level=lv, hp=hp, maxHP=mx, area_id=area},
                 "capture:"..k:sub(1,8), false)
        else console.log("[T3] F2: slot 0 empty") end
    end
    if pressed("F3") then
        if M.slotOccupied(M.PARTY_BASE) then
            local k = M.monKey(M.PARTY_BASE)
            send({event="faint", key=k, area_id=area}, "faint:"..k:sub(1,8), false)
        else console.log("[T3] F3: slot 0 empty") end
    end
    if pressed("F4") then
        send({event="no_catch", area_id=area}, "no_catch:"..(area~="" and area or "(none)"), false)
    end
    if pressed("F5") then send({event="whiteout"}, "whiteout", false) end
    if pressed("F6") then send({event="safe"},     "safe",     false) end
    if pressed("F7") then send({event="tick"},     "tick",     false) end
    prev_keys = keys

    -- Auto-tick every 60 frames
    if frame_count % 60 == 0 then send({event="tick"}, "tick(auto)", true) end

    -- Advance prev state
    prev_party     = curr_party
    prev_in_battle = in_battle
    prev_safe      = safe
end

local function on_frame_safe()
    local ok, err = pcall(on_frame)
    if not ok then console.log("[T3] ERROR (handler kept alive): " .. tostring(err)) end
end

event.onframeend(on_frame_safe, "t3_server")
console.log("[T3] Running — waiting for events…")