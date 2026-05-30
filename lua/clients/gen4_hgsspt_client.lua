--[[
  lua/clients/gen4_hgsspt_client.lua — SLink Soul Link Nuzlocke Client
  Gen 4: Pokémon HeartGold / SoulSilver / Platinum (NDS, BizHawk)

  EVENTS DETECTED AUTOMATICALLY
    hello        — on TCP connect / reconnect (party snapshot)
    area_enter   — zone ID changes to a mapped encounter zone
    capture      — new PID appears in party (battle / gift / egg pickup; carries is_egg flag)
    hatch        — an egg in the party transitions to a real species (egg flag clears)
    faint        — party mon HP transitions from > 0 to 0
    whiteout     — all living party mons transition to HP = 0
    no_catch     — wild battle ends without capture (gated by nuzlocke_active)
    safe         — first overworld frame after battle
    tick         — every 30 frames; carries ball_count + party snapshot

  COMMANDS DISPATCHED
    force_faint  — write HP = 0 to matching party slot (immediate; gated by writes_enabled)
    memorialize  — copy dead Pokémon's BoxPokemon to PC Box 18 (deferred: safe state)
    box_mon      — deposit partner's linked mon to PC (deferred: safe state)
    party_mon    — retrieve partner's linked mon from PC (deferred: safe state)
    pending_sync — logged as console warning

  Manual F keys:
    F1  → area_enter (current area_id)
    F2  → capture    (party slot 0)
    F3  → faint      (party slot 0)
    F4  → no_catch   (current area_id)
    F5  → whiteout
    F6  → safe
    F7  → tick       (with party snapshot)
    F8  → party_to_box (party slot 0)
    F9  → memorialize  (party slot 0 → Box 18, Lua-only, no server)

  Identity key: "PID:OTID" — 8-hex-char personality ID + 8-hex-char OT ID.
  OT ID (TID in low 16 bits, SID in high 16 bits) is read by decrypting Block A.
  Enables shiny clause, identity lock, and gender detection server-side.

  KNOWN HGSS LIMITATIONS (acceptable for current scope):
    • party_mon stats restoration is partial (party-only bytes zeroed; game recalculates on menu open).
    • memorialize writes BoxPokemon to PC Box 18 in live RAM; persists on save.
    • Sound effects not supported (NDS audio architecture different from GBA m4a).
--]]

-- ── CONFIGURE ─────────────────────────────────────────────────────────────────
local SERVER_HOST = SLINK_HOST   or "127.0.0.1"
local SERVER_PORT = SLINK_PORT   or 54321
local PLAYER_ID   = SLINK_PLAYER or "a"    -- "a" = Player 1, "b" = Player 2
SLINK_HOST = nil; SLINK_PORT = nil; SLINK_PLAYER = nil
-- ─────────────────────────────────────────────────────────────────────────────

-- ── Module loading ─────────────────────────────────────────────────────────────
-- Resolve lua/ root from this script's location (lua/clients/ → lua/)
local _src = debug.getinfo(1, "S").source:match("@(.+[/\\])") or ""
local _lua_root = _src:match("(.+[/\\])clients[/\\]") or _src
local _proj_root = _lua_root:match("(.+[/\\])lua[/\\]") or (_lua_root .. "../")
package.path = _lua_root .. "?.lua;"
            .. _lua_root .. "games/?.lua;"
            .. _proj_root .. "data/games/gen4_hgsspt/?.lua;"
            .. _src .. "?.lua;"
            .. package.path
package.loaded["memory_nds"]                = nil
package.loaded["gen4_hgsspt_areas"]         = nil
package.loaded["gen4_hgsspt_areas_pt"]      = nil
package.loaded["gen4_hgsspt_locations"]     = nil
package.loaded["gen4_hgsspt_locations_pt"]  = nil
package.loaded["connector"]                 = nil
package.loaded["socket"]                    = nil
package.loaded["hud"]                       = nil

local M           = require("memory_nds")
local GAME_MODULE = require("gen4_hgsspt")  -- profiles, gift areas, variant detection
local C           = require("connector")
local HUD         = require("hud")

-- AREAS and LOCATIONS are loaded after variant detection (below) because Platinum
-- uses gen4_hgsspt_areas_pt / gen4_hgsspt_locations_pt, not the HGSS variants.
local AREAS, LOCATIONS

-- ── Localized hot-path globals ────────────────────────────────────────────────
-- Explicitly bind "Main RAM" domain — omitting it uses BizHawk's default domain
-- which on NDS may differ from "Main RAM" and silently return wrong data.
local _RAM = "Main RAM"
local function mem_u8 (a)   return memory.read_u8      (a, _RAM) end
local function mem_u16(a)   return memory.read_u16_le  (a, _RAM) end
local function mem_u32(a)   return memory.read_u32_le  (a, _RAM) end
local function mem_w16(a,v) return memory.write_u16_le (a, v, _RAM) end
local fmt     = string.format

-- ── Variant detection ─────────────────────────────────────────────────────────
-- Delegate to GAME_MODULE.detect_variant() so the detection logic — including
-- Renegade Platinum's hash/signature/filename match chain — lives in exactly
-- one place. Falls back to "heartgold" if the module returns nil.
local _ROM_TYPE = GAME_MODULE.detect_variant() or "heartgold"
if not GAME_MODULE.profiles[_ROM_TYPE] then
    console.log("[SLink] WARNING: Unknown ROM variant '" .. _ROM_TYPE .. "' — falling back to heartgold")
    _ROM_TYPE = "heartgold"
end
console.log(fmt("[SLink] ROM variant: %s", _ROM_TYPE))

-- Apply game-specific memory address profile (parameterises all address constants
-- in memory_nds.lua via upvalue reassignment; must happen before M.init()).
M.applyProfile(GAME_MODULE.profiles[_ROM_TYPE])

-- Load variant-specific area and location tables.
-- Platinum and Renegade Platinum share Sinnoh map structure; HGSS uses Johto/Kanto.
if _ROM_TYPE == "platinum" or _ROM_TYPE == "renegade_platinum" then
    package.loaded["gen4_hgsspt_areas_pt"]     = nil
    package.loaded["gen4_hgsspt_locations_pt"] = nil
    local ok_a, a = pcall(require, "gen4_hgsspt_areas_pt")
    local ok_l, l = pcall(require, "gen4_hgsspt_locations_pt")
    if ok_a then AREAS = a else
        console.log("[SLink] WARNING: gen4_hgsspt_areas_pt not found — area detection disabled for Platinum")
        AREAS = {}
    end
    if ok_l then LOCATIONS = l else LOCATIONS = {} end
else
    AREAS     = require("gen4_hgsspt_areas")
    LOCATIONS = require("gen4_hgsspt_locations")
end

-- ── JSON encoder ──────────────────────────────────────────────────────────────
local _json_esc = {['\\']='\\\\', ['"']='\\"', ['\n']='\\n'}
local function json_encode(val)
    local t = type(val)
    if val == nil         then return "null"
    elseif t == "boolean" then return val and "true" or "false"
    elseif t == "number"  then
        if val == val and val % 1 == 0 and val >= -2147483648 and val <= 2147483647 then
            return fmt("%d", val)
        end
        return tostring(val)
    elseif t == "string"  then
        return '"' .. val:gsub('[\\"\n]', _json_esc) .. '"'
    elseif t == "table" then
        local n = #val
        local is_arr = (n > 0)
        if is_arr then
            local cnt = 0
            for _ in pairs(val) do cnt = cnt + 1; if cnt > n then is_arr = false; break end end
            if cnt ~= n then is_arr = false end
        end
        local p, pn = {}, 0
        if is_arr then
            for i = 1, n do pn = pn + 1; p[pn] = json_encode(val[i]) end
            return "[" .. table.concat(p, ",") .. "]"
        else
            for k, v in pairs(val) do
                pn = pn + 1
                p[pn] = '"' .. tostring(k) .. '":' .. json_encode(v)
            end
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
        local cmd   = obj:match('"cmd"%s*:%s*"([^"]+)"')
        local key   = obj:match('"key"%s*:%s*"([^"]+)"')
        local msg   = obj:match('"message"%s*:%s*"([^"]*)"')
        local text  = obj:match('"text"%s*:%s*"([^"]*)"')
        local r     = tonumber(obj:match('"r"%s*:%s*(%d+)'))
        local g     = tonumber(obj:match('"g"%s*:%s*(%d+)'))
        local b     = tonumber(obj:match('"b"%s*:%s*(%d+)'))
        local frames = tonumber(obj:match('"frames"%s*:%s*(%d+)'))
        local area_id = obj:match('"area_id"%s*:%s*"([^"]*)"')
        local areas_arr = nil
        local areas_raw = obj:match('"areas"%s*:%s*(%b[])')
        if areas_raw then
            areas_arr = {}
            for a in areas_raw:gmatch('"([^"]+)"') do areas_arr[#areas_arr+1] = a end
        end
        if cmd then
            cmds[#cmds+1] = {cmd=cmd, key=key, message=msg,
                             text=text, r=r, g=g, b=b, frames=frames,
                             area_id=area_id, areas=areas_arr}
        end
    end
    return cmds
end

-- ── HUD overlay (shared module) ──────────────────────────────────────────────
-- NDS screen: 256 × 192. HUD appears at bottom of the lower screen (BizHawk layout).
HUD.init({screen_w = 256, screen_h = 192, hud_x = 3, hud_y = 180, hud_right = 253,
          prompt_y = 53, prompt_h = 14, gameover_y = 70})
local hud_show   = HUD.show
local hud_render = HUD.render

-- ── Game-over persistent overlay ─────────────────────────────────────────────
local game_over_flag = false
local rebuild_active = false  -- true between rebuild_start and rebuild_done

-- ── Deferred sync state ────────────────────────────────────────────────────────
local pending_sync_cmds = {}    -- box_mon / party_mon / memorialize queue
local resolved_areas    = {}    -- area_id → true (already had a catch/no-catch)
local resolved_seeded   = false
local pending_hud_area  = nil

-- ── Write safety ──────────────────────────────────────────────────────────────
-- writes_enabled = false until M.validateSave() passes. Prevents force_faint /
-- memorialize / box_mon / party_mon from firing when the game state is garbage
-- (title screen, mid-save, reset). Re-validated every frame when disabled.
local writes_enabled = false
local SYNC_COOLDOWN_FRAMES = 120   -- ~2 s after battle ends before allowing sync writes
local sync_cooldown        = 0
local sync_block_log_timer = 0

-- Nick label cache (forward-declared here so command handlers can use it)
local _nick_cache = {}   -- [key] → display string
local function nick_label(key)
    if _nick_cache[key] then return _nick_cache[key] end
    return key and key:sub(1, 8) or "?"
end

-- ── Command dispatcher ────────────────────────────────────────────────────────

local function _filter_pending(exclude_cmd, key)
    local filtered = {}
    for _, p in ipairs(pending_sync_cmds) do
        if not (p.key == key and p.cmd == exclude_cmd) then
            filtered[#filtered + 1] = p
        end
    end
    return filtered
end

local function dispatch_commands(cmds)
    for _, c in ipairs(cmds) do
        local short_key = c.key and c.key:sub(1, 8) or "?"
        if c.cmd == "force_faint" and c.key then
            if not writes_enabled then
                console.log("[SLink]   ↳ force_faint BLOCKED (writes disabled)")
                hud_show("!! force_faint: save invalid", 255, 80, 80, 360)
            else
                -- Scan party for matching PID; write curHP = 0
                local count = M.readPartyCount()
                if count > 6 then count = 0 end
                local found = false
                for slot = 0, count - 1 do
                    local base = M.partyAddr(slot)
                    if base then
                        local pid = mem_u32(base)
                        if pid ~= 0 and fmt("%08X", pid) == short_key then
                            M.forceFaint(slot)
                            console.log(fmt("[SLink]   ↳ force_faint slot=%d key=%s", slot, c.key))
                            hud_show("!! " .. nick_label(c.key) .. " KO'd", 255, 80, 80, 360)
                            found = true
                            break
                        end
                    end
                end
                if not found then
                    console.log(fmt("[SLink]   ↳ force_faint: key %s not found in party", c.key))
                end
            end
        elseif c.cmd == "pending_sync" then
            console.log("[SLink]   ↳ ⚠ SYNC REQUIRED: " .. (c.message or "check partner at PC"))
            hud_show("!! SYNC REQUIRED", 255, 200, 60, 600)
        elseif c.cmd == "box_mon" and c.key then
            -- Cancel any pending party_mon for the same key (opposing commands = net no-op).
            pending_sync_cmds = _filter_pending("party_mon", c.key)
            table.insert(pending_sync_cmds, {cmd="box_mon", key=c.key})
            console.log("[SLink]   ↳ box_mon QUEUED: " .. short_key)
        elseif c.cmd == "party_mon" and c.key then
            -- Cancel any pending box_mon for the same key (opposing commands = net no-op).
            pending_sync_cmds = _filter_pending("box_mon", c.key)
            table.insert(pending_sync_cmds, {cmd="party_mon", key=c.key, stats=c.stats})
            console.log("[SLink]   ↳ party_mon QUEUED: " .. short_key)
        elseif c.cmd == "memorialize" and c.key then
            -- Deduplicate: skip if this key already has a pending memorialize
            local already_queued = false
            for _, p in ipairs(pending_sync_cmds) do
                if p.cmd == "memorialize" and p.key == c.key then
                    already_queued = true; break
                end
            end
            if not already_queued then
                table.insert(pending_sync_cmds, {cmd="memorialize", key=c.key})
                console.log(fmt("[SLink]   ↳ memorialize QUEUED: %s", short_key))
            else
                console.log(fmt("[SLink]   ↳ memorialize DEDUPED: %s", short_key))
            end
        elseif c.cmd == "resolved_areas" and c.areas then
            for _, a in ipairs(c.areas) do resolved_areas[a] = true end
            resolved_seeded = true
            console.log(fmt("[SLink]   ↳ resolved_areas: %d areas seeded", #c.areas))
            if pending_hud_area and not resolved_areas[pending_hud_area] then
                local disp = pending_hud_area:gsub("_", " "):gsub("(%a)([%w]*)", function(a, b) return a:upper()..b end)
                hud_show(">> New encounter: " .. disp, 80, 255, 120, 180)
            end
            pending_hud_area = nil
        elseif c.cmd == "unresolve_area" and c.area_id then
            resolved_areas[c.area_id] = nil
            console.log("[SLink]   ↳ unresolve_area: " .. c.area_id)
        elseif c.cmd == "hud_show" and c.text then
            hud_show(c.text, c.r or 255, c.g or 255, c.b or 255, c.frames or 300)
        elseif c.cmd == "game_over" then
            game_over_flag = true
            if M.playSE then M.playSE(M.SE_GAME_OVER) end
            HUD.set_game_over()
            console.log("[SLink]   ↳ GAME OVER — SOUL LINK")
        elseif c.cmd == "rebuild_start" then
            rebuild_active = true
            HUD.set_rebuilding(c.text or "REBUILDING TEAM")
            console.log("[SLink]   ↳ rebuild_start: " .. tostring(c.text))
        elseif c.cmd == "rebuild_done" then
            rebuild_active = false
            HUD.clear_rebuilding()
            console.log("[SLink]   ↳ rebuild_done")
        elseif c.cmd ~= "noop" then
            console.log("[SLink]   ↳ cmd: " .. tostring(c.cmd))
        end
    end
end

-- ── Send / receive ────────────────────────────────────────────────────────────
local seq            = 0
local pending_labels = {}

local function send(evt, label, is_auto, is_silent)
    if not C.connected() then
        console.log("[SLink] NOT CONNECTED — dropped: " .. (label or evt.event))
        return
    end
    seq = seq + 1; evt.seq = seq; evt.player = PLAYER_ID
    C.send(json_encode(evt))
    local prefix = is_auto and "AUTO" or "MANUAL"
    local lbl = (is_silent and "SILENT:" or "") .. (prefix .. " " .. seq .. ": " .. (label or evt.event))
    pending_labels[#pending_labels+1] = lbl
    if not is_silent then
        console.log(fmt("[SLink] [→] seq=%d  %s: %s", seq, prefix, label or evt.event))
    end
end

local function format_cmds(cmds)
    if #cmds == 0 then return "???" end
    local p = {}
    for _, c in ipairs(cmds) do
        if c.key then p[#p+1] = c.cmd.."("..c.key:sub(1,8)..")"
        else           p[#p+1] = c.cmd end
    end
    return table.concat(p, ", ")
end

-- ── Deferred sync execution (safe-state only) ─────────────────────────────────

local function exec_memorialize(key)
    -- Drain any stale box_mon/party_mon for this key from the queue
    local filtered = {}
    for _, c in ipairs(pending_sync_cmds) do
        if not (c.key == key and (c.cmd == "box_mon" or c.cmd == "party_mon")) then
            filtered[#filtered + 1] = c
        end
    end
    pending_sync_cmds = filtered

    -- Copy dead Pokémon's BoxPokemon data to PC Box 18 (index 17).
    local pc_base = M.pcStorageBase()
    if not pc_base then
        console.log("[SLink]   ↳ memorialize EXEC FAIL: PC storage unreachable")
        hud_show("!! mem: PC unavailable", 255, 140, 40, 600)
        send({event="memorialize_failed", key=key, reason="pc_unavailable"},
             "memorialize_failed:"..key:sub(1,8), true, true)
        return
    end
    local pid_hex = key:sub(1, 8)

    -- First: scan party for the mon.
    local count = M.readPartyCount()
    if count > 6 then count = 0 end
    local found_addr = nil
    local found_in = "party"
    for slot = 0, count - 1 do
        local addr = M.partyAddr(slot)
        if addr then
            local pid = mem_u32(addr)
            if pid ~= 0 and fmt("%08X", pid) == pid_hex then
                found_addr = addr
                break
            end
        end
    end

    -- Second: if not in party, scan PC boxes 0-16 (not box 17/memorial).
    if not found_addr then
        for box = 0, 16 do
            for slot = 0, 29 do
                local addr = M.pcBoxAddr(box, slot)
                if addr then
                    local pid = mem_u32(addr)
                    if pid ~= 0 and fmt("%08X", pid) == pid_hex then
                        found_addr = addr
                        found_in = fmt("box%d_s%d", box + 1, slot + 1)
                        break
                    end
                end
            end
            if found_addr then break end
        end
    end

    -- Third: check if already in Box 18 (already memorialized).
    if not found_addr then
        for slot = 0, 29 do
            local addr = M.pcBoxAddr(17, slot)
            if addr then
                local pid = mem_u32(addr)
                if pid ~= 0 and fmt("%08X", pid) == pid_hex then
                    console.log(fmt("[SLink]   ↳ memorialize: %s already in Box 18 s%d", pid_hex, slot + 1))
                    hud_show("+ " .. nick_label(key) .. " in grave", 100, 255, 100, 360)
                    send({event="memorialize_done", key=key, box=17, slot=slot},
                         "memorialize_done:"..pid_hex, true)
                    return
                end
            end
        end
        -- Truly not found anywhere — retry (return false signals re-queue).
        console.log(fmt("[SLink]   ↳ memorialize: %s not found in party or PC (retry)", pid_hex))
        return false
    end

    -- Find memorial slot: try Box 18 (index 17), then overflow backwards (16, 15, ...)
    local mem_box = nil
    local empty = nil
    for box = 17, 0, -1 do
        local slot = M.pcBoxFirstEmpty(box)
        if slot then
            mem_box = box
            empty = slot
            break
        end
    end
    if not mem_box then
        console.log("[SLink]   ↳ memorialize EXEC FAIL: ALL PC boxes full!")
        hud_show("!! All boxes full", 255, 80, 80, 600)
        send({event="memorialize_failed", key=key, reason="box_full"},
             "memorialize_failed:"..key:sub(1,8), true, true)
        return
    end
    local pc_addr = M.pcBoxAddr(mem_box, empty)
    -- Copy 0x88 bytes (BoxPokemon) from source to memorial slot.
    for i = 0, 0x87 do
        memory.write_u8(pc_addr + i, memory.read_u8(found_addr + i, _RAM), _RAM)
    end
    -- Clear decryption flags on the PC copy (bits 0-1 of FLAGS u16 at +4).
    local pc_flags = mem_u16(pc_addr + 0x004)
    mem_w16(pc_addr + 0x004, pc_flags & 0xFFFC)
    -- Verify
    local verify_pid = mem_u32(pc_addr)
    local expected_pid = mem_u32(found_addr)
    if verify_pid == expected_pid and verify_pid ~= 0 then
        -- Zero source slot and compact party if the mon was in the party
        if found_in == "party" then
            -- Safety: don't reduce party below 1 (game crash protection)
            if count <= 1 then
                console.log("[SLink]   ↳ memorialize: last party mon — leaving in party")
                hud_show("!! Only mon!", 255, 200, 60, 240)
                return
            end
            local found_slot = nil
            for slot = 0, count - 1 do
                if M.partyAddr(slot) == found_addr then found_slot = slot; break end
            end
            if found_slot then
                -- Zero the full PartyPokemon (0xEC bytes)
                for i = 0, M.MON_SIZE - 1 do
                    memory.write_u8(found_addr + i, 0, _RAM)
                end
                -- Compact: shift higher slots down
                for s = found_slot, count - 2 do
                    local src = M.partyAddr(s + 1)
                    local dst = M.partyAddr(s)
                    for i = 0, M.MON_SIZE - 1 do
                        memory.write_u8(dst + i, memory.read_u8(src + i, _RAM), _RAM)
                    end
                end
                -- Zero the last slot (now a duplicate)
                local last = M.partyAddr(count - 1)
                for i = 0, M.MON_SIZE - 1 do
                    memory.write_u8(last + i, 0, _RAM)
                end
                M.writePartyCount(count - 1)
                M.clearDebounce()  -- stale cache after party rewrite
            end
        elseif found_in ~= "party" then
            -- Zero source in PC box (0x88 bytes)
            for i = 0, 0x87 do
                memory.write_u8(found_addr + i, 0, _RAM)
            end
        end
        console.log(fmt("[SLink]   ↳ memorialize OK: %s (%s) → Box %d slot %d",
            pid_hex, found_in, mem_box + 1, empty + 1))
        hud_show(fmt("+ %s buried -> Box %d", nick_label(key), mem_box + 1),
            255, 140, 40, 360)
        send({event="memorialize_done", key=key, box=mem_box, slot=empty},
             "memorialize_done:"..pid_hex, true)
    else
        console.log(fmt("[SLink]   ↳ memorialize VERIFY FAIL: wrote to Box %d s%d but PID mismatch", mem_box + 1, empty + 1))
        hud_show("!! mem verify failed", 255, 80, 80, 600)
        send({event="memorialize_failed", key=key, reason="verify_mismatch"},
             "memorialize_failed:"..pid_hex, true, true)
    end
end

local function exec_box_mon(key)
    -- Deposit matched party mon to first empty PC slot (any box except 17=memorial).
    local count = M.readPartyCount()
    if count <= 1 then
        console.log("[SLink]   ↳ box_mon skipped: " .. key:sub(1,8) .. " (last mon in party)")
        hud_show("! Only mon!", 255, 200, 60, 240)
        return
    end
    local found_slot = nil
    local found_addr = nil
    for slot = 0, count - 1 do
        local addr = M.partyAddr(slot)
        if addr then
            local pid = mem_u32(addr)
            if pid ~= 0 and fmt("%08X", pid) == key:sub(1, 8) then
                found_slot = slot
                found_addr = addr
                break
            end
        end
    end
    if not found_slot then
        console.log("[SLink]   ↳ box_mon: " .. key:sub(1,8) .. " not found in party (already boxed?)")
        sync_written_keys[key] = true
        return
    end
    -- Find first empty slot in boxes 0-16 (skip box 17 = memorial)
    local dst_box, dst_slot = nil, nil
    for box = 0, 16 do
        local s = M.pcBoxFirstEmpty(box)
        if s then dst_box = box; dst_slot = s; break end
    end
    if not dst_box then
        console.log("[SLink]   ↳ box_mon FAIL: all PC boxes full!")
        hud_show("!! Boxes full", 255, 80, 80, 600)
        return
    end
    -- Read stats before depositing (for server stats_cache)
    local slot_data = M.readPartySlot(found_slot)
    local stats_tbl = slot_data and {level=slot_data.level, maxHP=slot_data.maxHP} or nil
    -- Copy to PC box
    local pc_addr = M.pcBoxAddr(dst_box, dst_slot)
    M.writeBoxMonFromParty(found_addr, pc_addr)
    -- Zero source party slot and compact
    for i = 0, M.MON_SIZE - 1 do
        memory.write_u8(found_addr + i, 0, _RAM)
    end
    for s = found_slot, count - 2 do
        local src = M.partyAddr(s + 1)
        local dst = M.partyAddr(s)
        for i = 0, M.MON_SIZE - 1 do
            memory.write_u8(dst + i, memory.read_u8(src + i, _RAM), _RAM)
        end
    end
    local last = M.partyAddr(count - 1)
    for i = 0, M.MON_SIZE - 1 do
        memory.write_u8(last + i, 0, _RAM)
    end
    M.writePartyCount(count - 1)
    M.clearDebounce()  -- stale cache after party rewrite
    if stats_tbl then
        send({event="stats_cache", key=key, stats=stats_tbl},
             "stats_cache:"..key:sub(1,8), true, true)
    end
    console.log(fmt("[SLink]   ↳ box_mon OK: %s → Box %d slot %d", key:sub(1,8), dst_box + 1, dst_slot + 1))
    hud_show(fmt("v %s boxed -> Box %d", nick_label(key), dst_box + 1), 100, 180, 255, 240)
end

local function exec_party_mon(key, stats)
    -- Retrieve matched mon from PC boxes back to party.
    stats = stats or {}
    local count = M.readPartyCount()
    -- Check if already in party
    for slot = 0, count - 1 do
        local addr = M.partyAddr(slot)
        if addr and mem_u32(addr) ~= 0 and fmt("%08X", mem_u32(addr)) == key:sub(1, 8) then
            console.log("[SLink]   ↳ party_mon: " .. key:sub(1,8) .. " already in party")
            sync_written_keys[key] = true
            send({event="sync_retrieve_done", key=key},
                 "sync_retrieve_done:"..key:sub(1,8), true, true)
            return
        end
    end
    if count >= 6 then
        console.log("[SLink]   ↳ party_mon: party full for " .. key:sub(1,8))
        hud_show("! Unbox " .. nick_label(key), 255, 200, 60, 600)
        return false  -- signal retry
    end
    -- Scan PC boxes 0-17 for the key
    local src_box, src_slot, src_addr = nil, nil, nil
    for box = 0, 17 do
        for slot = 0, 29 do
            local addr = M.pcBoxAddr(box, slot)
            if addr then
                local pid = mem_u32(addr)
                if pid ~= 0 and fmt("%08X", pid) == key:sub(1, 8) then
                    src_box = box; src_slot = slot; src_addr = addr
                    break
                end
            end
        end
        if src_box then break end
    end
    if not src_box then
        console.log("[SLink]   ↳ party_mon: " .. key:sub(1,8) .. " not found in any PC box")
        hud_show("! Unbox " .. nick_label(key), 255, 200, 60, 600)
        send({event="sync_retrieve_failed", key=key},
             "sync_retrieve_failed:"..key:sub(1,8), true, true)
        return
    end
    -- Copy BoxPokemon (0x88 bytes) to party slot at position `count`
    local dst_addr = M.partyAddr(count)
    if not dst_addr then
        console.log("[SLink]   ↳ party_mon: can't compute party slot address")
        send({event="sync_retrieve_failed", key=key},
             "sync_retrieve_failed:"..key:sub(1,8), true, true)
        return
    end
    -- Copy the 0x88 box data to the party slot (first 0x88 bytes of the 0xEC party mon)
    for i = 0, 0x87 do
        memory.write_u8(dst_addr + i, memory.read_u8(src_addr + i, _RAM), _RAM)
    end
    -- Initialize the party-only battle stats block (0x88..0xEB) with encrypted values.
    -- The battle stats are PID-seeded LCRNG encrypted in Gen 4 — zeroing causes corruption.
    local pid = mem_u32(dst_addr)
    local s_level = stats.level or 5
    local s_maxHP = stats.maxHP or 1
    local s_curHP = s_maxHP  -- retrieve at full HP
    -- Zero the entire party extension area first (includes trailing bytes)
    for i = 0x88, 0xEB do
        memory.write_u8(dst_addr + i, 0, _RAM)
    end
    -- Write encrypted battle stats: status=0 (healthy), level, curHP=maxHP, maxHP
    M.encrypt_stats(dst_addr + 0x88, pid, 0, s_level, s_curHP, s_maxHP, 0, 0, 0, 0, 0)
    -- Increment party count
    M.writePartyCount(count + 1)
    M.clearDebounce()  -- stale cache after party rewrite
    for i = 0, 0x87 do
        memory.write_u8(src_addr + i, 0, _RAM)
    end
    sync_written_keys[key] = true
    all_known_keys[key]    = true
    console.log(fmt("[SLink]   ↳ party_mon OK: %s ← Box %d slot %d → party[%d]",
        key:sub(1,8), src_box + 1, src_slot + 1, count))
    hud_show(fmt("^ %s unboxed Box %d", nick_label(key), src_box + 1), 100, 255, 160, 240)
    send({event="sync_retrieve_done", key=key},
         "sync_retrieve_done:"..key:sub(1,8), true, true)
end

-- ── Party helpers ─────────────────────────────────────────────────────────────

-- Identity key: "PID:OTID" — both values as 8-char uppercase hex.
-- Decrypted from Block A on PID change (or when species is still unresolved).
local _mk_pid     = {}   -- [slot] → last PID (cache invalidation)
local _mk_str     = {}   -- [slot] → cached key string
local _mk_species = {}   -- [slot] → cached species_id (0 = not yet resolved)

local function cachedMonKey(slot, slotAddr)
    local pid = mem_u32(slotAddr)
    -- Serve from cache if PID unchanged AND species already resolved.
    if pid == _mk_pid[slot] and (_mk_species[slot] or 0) > 0 then
        return _mk_str[slot]
    end
    local species_id, ot_id = M.decrypt_block_a(slotAddr)
    local key
    if ot_id then
        key = fmt("%08X:%08X", pid, ot_id)
    else
        key = fmt("%08X", pid)  -- fallback if Block A unreadable (transient state)
    end
    _mk_pid[slot]     = pid
    _mk_str[slot]     = key
    _mk_species[slot] = species_id or 0
    -- Populate nick_label cache
    if key and species_id and species_id > 0 and not _nick_cache[key] then
        _nick_cache[key] = fmt("species#%d", species_id)
    end
    return key
end

-- True when slot contains a valid Pokémon (PID≠0 and checksum≠0).
-- maxHP is encrypted in HGSS RAM so cannot be used as a validity check.
local function slotOccupied(slotAddr)
    return mem_u32(slotAddr) ~= 0 and mem_u16(slotAddr + M.PKM.CHKSUM) ~= 0
end

-- Double-buffer for party indexing.
local _ip_buf = {{}, {}}
local _ip_idx = 1
local _ip_pool = {{}, {}}
for _b = 1, 2 do
    for _s = 0, 5 do _ip_pool[_b][_s] = {hp=0, maxHP=0, level=0, slot=0, species_id=0} end
end

-- Index party into { [monKey] = {hp, maxHP, level, slot, species_id} }.
-- During battle, HP/level are read from the battle copy for live values.
-- HP is debounced over 2 frames to suppress between-turn re-encryption garbage.
local function index_party(in_battle)
    _ip_idx = (_ip_idx == 1) and 2 or 1
    local t    = _ip_buf[_ip_idx]
    local pool = _ip_pool[_ip_idx]
    for k in pairs(t) do t[k] = nil end

    local base_addr = M.init()
    if not base_addr then return t, 0 end

    local count = M.readPartyCount()
    if count > 6 then return t, 0 end

    for i = 0, count - 1 do
        local base = M.partyAddr(i)
        if base and mem_u32(base) ~= 0 then
            local k = cachedMonKey(i, base)
            local s = in_battle and M.battleHP(i) or M.partyHP(i)
            if s then
                local entry = pool[i]
                entry.hp         = s.hp
                entry.maxHP      = s.maxHP
                entry.level      = s.level
                entry.slot       = i
                entry.species_id = _mk_species[i] or 0
                -- Capture events read this entry directly; including nickname
                -- here matches Gen 3 client behaviour so the server's
                -- pending_captures gets the real name immediately rather than
                -- waiting for the next tick snapshot.
                local cached_nick = _nick_cache[k]
                if cached_nick == nil or cached_nick:sub(1, 8) == "species#" then
                    local fresh = M.readNickname(base)
                    if fresh then
                        _nick_cache[k] = fresh
                        cached_nick = fresh
                    end
                end
                entry.nickname = cached_nick or ""
                t[k] = entry
            end
        end
    end
    return t, count
end

-- Build party snapshot array for events.
-- Uses debounced HP values (same as index_party) for consistency.
-- Includes held_item, ability, and nickname for status page display.
local function build_party_snapshot(in_battle)
    local count = M.readPartyCount()
    if count > 6 then return {} end
    local snap = {}
    for i = 0, count - 1 do
        local base = M.partyAddr(i)
        if base and mem_u32(base) ~= 0 then
            local k = cachedMonKey(i, base)
            local s = in_battle and M.battleHP(i) or M.partyHP(i)
            if s then
                local species, ot_id, held_item, ability = M.decrypt_block_a_ext(base)
                local nickname = M.readNickname(base)
                local bb = M.decrypt_block_b(base)
                local bd = M.decrypt_block_d(base)
                -- Cache nickname for HUD use (real nickname overrides species#N)
                if k and nickname then
                    _nick_cache[k] = nickname
                end
                snap[#snap+1] = {
                    key          = k,
                    hp           = s.hp,
                    maxHP        = s.maxHP,
                    level        = s.level,
                    species_id   = species or (_mk_species[i] or 0),
                    held_item_id = held_item or 0,
                    ability_id   = ability or 0,
                    nickname     = nickname or "",
                    status_cond  = s.status_cond or 0,
                    -- Block B-derived fields (Phase 2+):
                    moves        = bb and bb.moves or {0, 0, 0, 0},
                    pp           = bb and bb.pp or {0, 0, 0, 0},
                    pp_ups       = bb and bb.pp_ups or {0, 0, 0, 0},
                    is_egg       = (bb and bb.is_egg) or false,
                    form         = bb and bb.form or 0,
                    -- Block D-derived fields (Phase 2+):
                    pokeball     = bd and bd.pokeball or 0,
                    met_level    = bd and bd.met_level or 0,
                }
            end
        end
    end
    return snap
end

-- ── Pokéball helpers ──────────────────────────────────────────────────────────
-- Standard ball IDs:   0x0001–0x0010  (Master Ball → Cherish Ball, all games)
-- Apricorn/Kurt balls: 0x01EC–0x01F4  (HGSS-exclusive — not present in Platinum)

local function _is_ball_id(id)
    if id >= 0x0001 and id <= 0x0010 then return true end
    -- Apricorn balls only exist in HGSS; Platinum + Renegade Platinum (Sinnoh) lack them.
    if _ROM_TYPE == "heartgold" or _ROM_TYPE == "soulsilver" then
        if id >= M.BALL_APRICORN_MIN and id <= M.BALL_APRICORN_MAX then
            return true
        end
    end
    return false
end

local function hasPokeballs()
    local addr = M.bagBallsAddr()
    if addr == nil then return false end
    for i = 0, M.BAG.BALLS_COUNT - 1 do
        local slot = M.readItemSlot(addr, i)
        if slot and slot.qty > 0 and _is_ball_id(slot.id) then return true end
    end
    return false
end

local function countPokeballs()
    local addr = M.bagBallsAddr()
    if addr == nil then return 0 end
    local total = 0
    for i = 0, M.BAG.BALLS_COUNT - 1 do
        local slot = M.readItemSlot(addr, i)
        if slot and slot.qty > 0 and _is_ball_id(slot.id) then total = total + slot.qty end
    end
    return total
end

-- ── Gift area IDs (no wild encounters; only gift/starter Pokémon spawns here)
-- Pull from game module so adding a new variant's gifts is done in one place.
-- Platinum + Renegade Platinum share Sinnoh gifts; HGSS uses Johto/Kanto.
local _is_sinnoh = (_ROM_TYPE == "platinum" or _ROM_TYPE == "renegade_platinum")
local GIFT_AREAS = _is_sinnoh and GAME_MODULE.GIFT_AREAS_PT
                              or  GAME_MODULE.GIFT_AREAS_HGSS

-- Areas with wild encounters (routes, caves, forests, etc.) — HUD prompt only fires here.
-- Johto routes (HGSS):
local ENCOUNTER_AREAS_HGSS = {
    route_1=true, route_2=true, route_3=true, route_4=true, route_5=true,
    route_6=true, route_7=true, route_8=true, route_9=true, route_10=true,
    route_11=true, route_12=true, route_13=true, route_14=true, route_15=true,
    route_16=true, route_17=true, route_18=true, route_19=true, route_20=true,
    route_21=true, route_22=true, route_24=true, route_25=true, route_26=true,
    route_27=true, route_28=true, route_29=true, route_30=true, route_31=true,
    route_32=true, route_33=true, route_34=true, route_35=true, route_36=true,
    route_37=true, route_38=true, route_39=true, route_40=true, route_41=true,
    route_42=true, route_43=true, route_44=true, route_45=true, route_46=true,
    route_47=true, route_48=true,
    dark_cave=true, sprout_tower=true, ruins_of_alph=true, union_cave=true,
    slowpoke_well=true, ilex_forest=true, national_park=true, burned_tower=true,
    bell_tower=true, whirl_islands=true, mt_mortar=true, lake_of_rage=true,
    ice_path=true, dragons_den=true, mt_silver=true, mt_silver_cave=true,
    cliff_cave=true, safari_zone=true, embedded_tower=true,
    tohjo_falls=true, victory_road=true, mt_moon=true, rock_tunnel=true,
    seafoam_islands=true, cerulean_cave=true, digletts_cave=true,
    viridian_forest=true, sinjoh_ruins=true,
}
-- Sinnoh routes (Platinum):
local ENCOUNTER_AREAS_PT = {
    route_201=true, route_202=true, route_203=true, route_204=true, route_205=true,
    route_206=true, route_207=true, route_208=true, route_209=true, route_210=true,
    route_211=true, route_212=true, route_213=true, route_214=true, route_215=true,
    route_216=true, route_217=true, route_218=true, route_219=true, route_220=true,
    route_221=true, route_222=true, route_223=true, route_224=true, route_225=true,
    route_226=true, route_227=true, route_228=true, route_229=true, route_230=true,
    oreburgh_mine=true, mt_coronet=true, wayward_cave=true, ravaged_path=true,
    floaroma_meadow=true, valley_windworks=true, fuego_ironworks=true,
    eterna_forest=true, old_chateau=true,
    solaceon_ruins=true, lost_tower=true,
    iron_island=true, lake_valor=true, lake_verity=true, lake_acuity=true,
    acuity_lakefront=true, valor_lakefront=true, spring_path=true,
    sendoff_spring=true, turnback_cave=true, distortion_world=true,
    victory_road_pt=true, stark_mountain=true, snowpoint_temple=true,
    trophy_garden=true, great_marsh=true,
}
local ENCOUNTER_AREAS = _is_sinnoh and ENCOUNTER_AREAS_PT
                                   or  ENCOUNTER_AREAS_HGSS

-- ── Per-frame state ───────────────────────────────────────────────────────────
local initialized    = false
local was_connected  = false
local nuzlocke_active = false
local frame_count    = 0
local prev_keys      = {}

-- Initialise these lazily (need M.init() to succeed first).
local prev_zone_id   = -1
local prev_area      = ""
local prev_loc       = ""
local prev_in_battle = false
local prev_party     = {}

-- Zone ID debounce — only accept a new zone after stable for N frames.
-- Prevents transient garbage during building exits / map transitions.
local ZONE_DEBOUNCE_FRAMES = 8
local zone_debounce_cand   = -1   -- candidate zone ID
local zone_debounce_count  = 0    -- frames candidate has been stable
local zone_confirmed       = -1   -- last confirmed (debounced) zone ID

-- Battle-scoped state
local battle_area_id       = nil
local battle_is_wild       = false
local captured_this_battle = false
local post_battle_frames   = 0
local POST_BATTLE_GRACE    = 90   -- ~1.5 s
local pending_safe         = false
local battle_box_snapshot  = nil  -- {[pid_hex]=true} — snapshot of current box at battle start (party==6)
local battle_enc_species   = 0    -- enemy species cached during battle for no_catch
local battle_enc_level     = 0    -- enemy level cached during battle for no_catch
-- Enemy team accumulator (mirrors gen3 battle_seen_enemies in gen3_frlge_client.lua).
-- Tracks the full opponent roster as it's revealed via switches across the battle.
-- Keyed by "species:level" (PID:OTID isn't always available pre-decryption for the
-- inactive slots in the buffer). Reset at every battle start. Each entry is the
-- live mon table from M.readEnemyParty() plus an `active=true|false` flag.
local battle_seen_enemies  = {}

-- Party change debounce
local PARTY_DEBOUNCE_FRAMES  = 3
local pending_box_to_party   = {}  -- key → frames_seen
local pending_party_to_box   = {}  -- key → {frames=N, info=prev_info}
local sync_written_keys      = {}
local all_known_keys         = {}

-- Gift capture buffer — hold new-outside-battle keys for 45 frames before confirming.
-- Prevents false gift events from mass party swaps (e.g., borrowed battles in FRLG).
local GIFT_BUFFER_WINDOW     = 45
local gift_capture_buffer    = {}  -- key → {frame=frame_count, info=..., area=...}

local TICK_INTERVAL = 30   -- auto-tick every 30 frames

-- Incremental PC box scanning — scan 1 box per tick round-robin.
local BOX_SCAN_TOTAL   = 18
local box_scan_idx     = 0   -- current box to scan (0-based)
local pc_box_cache     = {}  -- [box] → {{slot, key, species_id}, ...}
local memorial_box_renamed = false  -- one-shot: rename Box 18 to "THE DEAD"

-- ── Main frame handler ────────────────────────────────────────────────────────
local function on_frame()
    frame_count = frame_count + 1

    -- 1. Drive TCP pump
    C.pump()

    -- 2. Resolve pointer chain (must succeed before any address reads).
    local base_addr = M.init()
    if not base_addr then
        -- Save not loaded / title screen — skip event detection but keep TCP alive.
        if writes_enabled then
            writes_enabled = false
            console.log("[SLink] writes DISABLED (base pointer lost)")
        end
        return
    end

    -- 2b. Re-validate writes if previously disabled (save may load after script start).
    if not writes_enabled then
        local ok, err = M.validateSave()
        if ok then
            writes_enabled = true
            console.log("[SLink] ✓ save validated — writes enabled")
            -- Rename memorial box — DISABLED until offset is confirmed
            -- if not memorial_box_renamed then
            --     local rok, rerr = pcall(M.renameBox, 17, "THE DEAD")
            --     if rok then
            --         memorial_box_renamed = true
            --         console.log("[SLink] Memorial box (18) renamed to 'THE DEAD'")
            --     else
            --         console.log("[SLink] Memorial box rename FAILED: " .. tostring(rerr))
            --     end
            -- end
        elseif frame_count % 300 == 0 then
            console.log("[SLink] validateSave FAIL: " .. (err or "unknown"))
        end
    end

    -- 3. Connection state change → send hello on (re)connect.
    local now_connected = C.connected()
    if now_connected ~= was_connected then
        if now_connected then
            console.log("[SLink] [TCP] connected to " .. SERVER_HOST .. ":" .. SERVER_PORT)
            if writes_enabled and hasPokeballs() then
                nuzlocke_active = true
                console.log("[SLink] nuzlocke ACTIVE (pokeballs in bag at startup)")
            end
            local snap = build_party_snapshot(false)
            for k in pairs(prev_party) do all_known_keys[k] = true end
            send({event="hello", area_id=prev_area, loc_name=prev_loc, rom_type=_ROM_TYPE,
                  writes_enabled=writes_enabled, has_pokeballs=nuzlocke_active,
                  ball_count=countPokeballs(), party=snap,
                  trainer_name=M.readTrainerName(),
                  badges=M.readBadges1(),
                  kanto_badges=M.readBadges2()}, "hello", true)
            if #snap > 0 then
                for i, m in ipairs(snap) do
                    console.log(fmt("[SLink] party[%d] key=%s level=%d maxHP=%d",
                        i-1, m.key or "?", m.level or 0, m.maxHP or 0))
                end
            end
            initialized = true
        else
            console.log("[SLink] [TCP] disconnected — reconnecting…")
        end
        was_connected = now_connected
    end

    -- 4. Dispatch received responses.
    while true do
        local line = C.receive()
        if not line then break end
        local label = table.remove(pending_labels, 1) or "?"
        local cmds  = parse_command_list(line)
        if label:sub(1,7) ~= "SILENT:" then
            console.log("[SLink] [←] " .. label .. " → " .. format_cmds(cmds))
        end
        dispatch_commands(cmds)
    end

    if not initialized then return end

    -- 5. Read current state.
    local raw_zone_id = M.readZoneID()
    local in_battle   = M.isInBattle()

    -- Zone ID debounce: only accept new zone after stable for ZONE_DEBOUNCE_FRAMES.
    if raw_zone_id == zone_debounce_cand then
        zone_debounce_count = zone_debounce_count + 1
    else
        zone_debounce_cand  = raw_zone_id
        zone_debounce_count = 1
    end
    if zone_debounce_count >= ZONE_DEBOUNCE_FRAMES then
        zone_confirmed = zone_debounce_cand
    end
    local zone_id = zone_confirmed
    local area    = AREAS[zone_id] or ""
    local loc     = LOCATIONS[zone_id] or ""

    -- Track battle-end transition for sync_cooldown.
    local battle_just_ended = prev_in_battle and not in_battle
    if battle_just_ended then
        sync_cooldown = SYNC_COOLDOWN_FRAMES
    elseif sync_cooldown > 0 then
        sync_cooldown = sync_cooldown - 1
    end

    -- 5b. Flush one deferred sync cmd if safe (BEFORE party diff so writes are clean).
    -- Gate on: overworld, cooldown expired, writes enabled, post-battle grace done.
    local is_overworld = not in_battle
    local safe_now = is_overworld and sync_cooldown == 0
                     and not battle_just_ended and post_battle_frames == 0
    if #pending_sync_cmds > 0 then
        if not safe_now or not writes_enabled then
            sync_block_log_timer = sync_block_log_timer - 1
            if sync_block_log_timer <= 0 then
                sync_block_log_timer = 120
                console.log(fmt("[SLink] SYNC BLOCKED: safe=%s writes=%s cooldown=%d pbf=%d cmd=%s",
                    tostring(safe_now), tostring(writes_enabled), sync_cooldown,
                    post_battle_frames, pending_sync_cmds[1].cmd))
            end
        else
            sync_block_log_timer = 0
        end
    end
    if safe_now and #pending_sync_cmds > 0 and writes_enabled then
        local cmd = pending_sync_cmds[1]  -- peek before removing
        -- Never memorialize the last party mon — emptying the party softlocks.
        local blocked = false
        if cmd.cmd == "memorialize" and cmd.key then
            local q_count = M.readPartyCount()
            if q_count <= 1 then
                for q_s = 0, q_count - 1 do
                    local addr = M.partyAddr(q_s)
                    if addr and M.monKey(addr) == cmd.key then
                        if game_over_flag then
                            table.remove(pending_sync_cmds, 1)
                            blocked = true
                            console.log("[SLink] memorialize dropped (game over, last party mon): "..cmd.key:sub(1,8))
                        else
                            -- Block the memorialize — the party must never be
                            -- empty (softlock). Normally party_mon arrives
                            -- before this memorialize and lifts the block
                            -- automatically. But when the party was full at
                            -- whiteout, party_mon retried to the end of the
                            -- queue. Rescue: promote the first party_mon to
                            -- front so it runs next frame.
                            blocked = true
                            for look = 2, #pending_sync_cmds do
                                if pending_sync_cmds[look].cmd == "party_mon" then
                                    local pm = table.remove(pending_sync_cmds, look)
                                    table.insert(pending_sync_cmds, 1, pm)
                                    console.log("[SLink] memorialize blocked: promoted party_mon to front ("..pm.key:sub(1,8)..")")
                                    break
                                end
                            end
                        end
                        break
                    end
                end
            end
        end
        if not blocked then
        local cmd = table.remove(pending_sync_cmds, 1)
        local exec_ok, exec_result = true, nil
        if cmd.cmd == "box_mon" then
            exec_ok, exec_result = pcall(exec_box_mon, cmd.key)
        elseif cmd.cmd == "party_mon" then
            exec_ok, exec_result = pcall(exec_party_mon, cmd.key, cmd.stats)
        elseif cmd.cmd == "memorialize" then
            exec_ok, exec_result = pcall(exec_memorialize, cmd.key)
        end
        if not exec_ok then
            console.log(fmt("[SLink] ✗ SYNC CMD ERROR (%s key=%s): %s",
                cmd.cmd, (cmd.key or "?"):sub(1,8), tostring(exec_result)))
            cmd._retries = (cmd._retries or 0) + 1
            if cmd._retries <= 3 then
                table.insert(pending_sync_cmds, 1, cmd)
                console.log(fmt("[SLink]   ↳ re-queued (attempt %d/3)", cmd._retries))
            else
                console.log("[SLink]   ↳ DROPPED after 3 retries")
                hud_show("X " .. cmd.cmd .. " fail: " .. nick_label(cmd.key or ""), 255, 80, 80, 600)
            end
        elseif cmd.cmd == "party_mon" and exec_result == false then
            -- exec_party_mon returns false to signal retry (party full)
            cmd._retries = (cmd._retries or 0) + 1
            if cmd._retries <= 3 then
                table.insert(pending_sync_cmds, cmd)
                console.log(fmt("[SLink]   ↳ party_mon re-queued (attempt %d/3)", cmd._retries))
            else
                console.log("[SLink]   ↳ party_mon DROPPED after 3 retries: " .. (cmd.key or "?"):sub(1,8))
                hud_show("! Unbox " .. nick_label(cmd.key or ""), 255, 200, 60, 600)
                send({event="sync_retrieve_failed", key=cmd.key},
                     "sync_retrieve_failed:"..(cmd.key or "?"):sub(1,8), true, true)
            end
        elseif cmd.cmd == "memorialize" and exec_result == false then
            -- exec_memorialize returns false to signal retry (not found yet)
            cmd._retries = (cmd._retries or 0) + 1
            if cmd._retries <= 5 then
                table.insert(pending_sync_cmds, cmd)
                console.log(fmt("[SLink]   ↳ memorialize re-queued (attempt %d/5)", cmd._retries))
            else
                console.log("[SLink]   ↳ memorialize DROPPED: " .. (cmd.key or "?"):sub(1,8) .. " not found")
                hud_show("!! mem: not found", 255, 140, 40, 600)
                send({event="memorialize_failed", key=cmd.key, reason="not_found"},
                     "memorialize_failed:"..(cmd.key or "?"):sub(1,8), true, true)
            end
        end
        end -- not blocked
    end

    -- 6. area_enter — fire on any zone ID change to a mapped area.
    -- Zone debounce ensures transient garbage during transitions is filtered.
    if zone_id ~= prev_zone_id then
        if area ~= "" then
            send({event="area_enter", area_id=area, loc_name=loc}, "area_enter:" .. area, true)
            if nuzlocke_active and area ~= prev_area
                    and ENCOUNTER_AREAS[area] and not GIFT_AREAS[area] then
                if resolved_seeded then
                    if not resolved_areas[area] then
                        local disp = area:gsub("_", " "):gsub("(%a)([%w]*)", function(a, b) return a:upper()..b end)
                        hud_show(">> NEW ENCOUNTER <<  " .. disp, 255, 220, 60, 240)
                    end
                else
                    pending_hud_area = area
                end
            end
        end
    end

    -- 7. battle start.
    if not prev_in_battle and in_battle then
        battle_area_id       = area
        captured_this_battle = false
        battle_is_wild       = M.isWildBattle()
        battle_box_snapshot  = nil
        battle_enc_species   = 0
        battle_enc_level     = 0
        battle_seen_enemies  = {}  -- reset enemy team accumulator
        M.clearDebounce()         -- clear on battle start; battle copy has fresh values
        -- If party is full (6), snapshot current PC box to detect box captures.
        local pcount = M.readPartyCount()
        if pcount >= 6 then
            local cur_box = M.readCurrentBox()
            battle_box_snapshot = {box=cur_box, pids=M.readBoxPIDs(cur_box)}
        end
        console.log(fmt("[SLink] [battle] start  wild=%s  area=%s  party=%d",
            tostring(battle_is_wild), battle_area_id or "(none)", pcount))
        if battle_is_wild and nuzlocke_active and battle_area_id ~= ""
                and ENCOUNTER_AREAS[battle_area_id]
                and not resolved_areas[battle_area_id]
                and not GIFT_AREAS[battle_area_id] then
            local disp = battle_area_id:gsub("_", " "):gsub("(%a)([%w]*)", function(a, b) return a:upper()..b end)
            hud_show(">> NEW ENCOUNTER <<  " .. disp, 255, 220, 60, 360)
        end
    end

    -- 8. battle end.
    if battle_just_ended then
        M.clearDebounce()       -- clear on battle end; party copy has post-battle values
        post_battle_frames = POST_BATTLE_GRACE
        pending_safe       = true
        console.log("[SLink] [battle] end  grace window started")
    end

    -- 8a. Cache enemy encounter data during battle (for no_catch species/level).
    if in_battle and battle_is_wild and battle_enc_species == 0 then
        local ebbase = M.enemyBattleAddr(0)
        if ebbase then
            local epid = mem_u32(ebbase)
            if epid ~= 0 and mem_u16(ebbase + M.PKM.CHKSUM) ~= 0 then
                local sid, _ = M.decrypt_block_a(ebbase)
                if sid and sid > 0 then
                    battle_enc_species = sid
                    local lv, _, _ = M.decrypt_stats(ebbase + M.PKM.STATUS, epid)
                    if lv and lv >= 1 and lv <= 100 then battle_enc_level = lv end
                end
            end
        end
    end

    -- 8b. Post-battle grace: detect party-full box captures.
    -- On the last frame of grace, if party was 6 at battle start and battle_box_snapshot
    -- exists, diff to detect new entries in the current box (= capture went to PC).
    if post_battle_frames == 1 and battle_box_snapshot and not captured_this_battle then
        local snap = battle_box_snapshot
        local cur_pids = M.readBoxPIDs(snap.box)
        local new_keys = {}
        for pid_hex, _ in pairs(cur_pids) do
            if not snap.pids[pid_hex] then
                new_keys[#new_keys + 1] = pid_hex
            end
        end
        if #new_keys == 1 then
            -- Exactly one new mon appeared in the current box → box capture.
            local new_key = new_keys[1]
            local box_addr = nil
            for slot = 0, 29 do
                local addr = M.pcBoxAddr(snap.box, slot)
                if addr and fmt("%08X", mem_u32(addr)) == new_key then
                    box_addr = addr; break
                end
            end
            local species_id = 0
            if box_addr then
                local sp = M.decrypt_block_a(box_addr)
                if sp then species_id = sp end
            end
            captured_this_battle = true
            local evt_area = battle_area_id or area
            resolved_areas[evt_area] = true
            all_known_keys[new_key] = true
            send({event="capture", key=new_key, species_id=species_id,
                  area_id=evt_area, box_capture=true},
                 "capture(box):" .. new_key:sub(1,8), true)
            console.log(fmt("[SLink] capture(box): %s → Box %d (species=%d)",
                new_key, snap.box + 1, species_id))
        elseif #new_keys > 1 then
            -- Ambiguous (multiple new entries); suppress no_catch.
            captured_this_battle = true
            console.log(fmt("[SLink] [battle] %d new box entries — suppressing no_catch", #new_keys))
        end
        battle_box_snapshot = nil
    end

    -- 9. Read current party (after battle transition so HP is settled).
    local curr_party, party_count = index_party(in_battle)

    -- party_diff_ok: suppress diff during early post-battle transition (first 10 frames)
    -- where memory reads are unreliable (garbage HP/keys during scene transition).
    local party_diff_ok = in_battle or (post_battle_frames > 0 and post_battle_frames < (POST_BATTLE_GRACE - 10))
                          or (not in_battle and post_battle_frames == 0)

    if party_diff_ok then

    -- ── capture ──────────────────────────────────────────────────────────────
    for k, info in pairs(curr_party) do
        if not prev_party[k] and not sync_written_keys[k] then
            if in_battle or post_battle_frames > 0 then
                -- Battle capture
                local evt_area = battle_area_id or area
                captured_this_battle     = true
                resolved_areas[evt_area] = true
                all_known_keys[k]        = true
                send({event="capture", key=k, hp=info.hp, maxHP=info.maxHP,
                      level=info.level, species_id=info.species_id or 0,
                      nickname=info.nickname or "",
                      area_id=evt_area, is_egg=info.is_egg or false,
                      form=info.form or 0, pokeball=info.pokeball or 0},
                     "capture(battle):" .. k:sub(1,8), true)
            elseif all_known_keys[k] then
                -- Previously seen key returned from PC → box_to_party (debounced)
                if not pending_box_to_party[k] then
                    pending_box_to_party[k] = PARTY_DEBOUNCE_FRAMES
                end
            else
                -- New key outside battle → buffer as potential gift/starter (or egg pickup).
                -- Hold for GIFT_BUFFER_WINDOW frames before confirming (protects against
                -- mass swaps / transient garbage).
                if not gift_capture_buffer[k] then
                    local gift_area
                    if not nuzlocke_active then
                        gift_area = "intro"
                    elseif area ~= "" then
                        gift_area = area
                    else
                        gift_area = "gift_zone_" .. tostring(zone_id)
                    end
                    -- Tag egg pickups with "egg_" prefix so the server can route them
                    -- through is_egg_pickup_area (preserves clause semantics for eggs).
                    if info.is_egg then
                        gift_area = "egg_" .. gift_area
                    end
                    gift_capture_buffer[k] = {frame=frame_count, info=info, area=gift_area}
                end
            end
        end
    end

    -- ── gift capture buffer flush────────────────────────────────────────────
    for k, buf in pairs(gift_capture_buffer) do
        if not curr_party[k] then
            -- Key vanished during buffer window → was transient/glitch; discard.
            gift_capture_buffer[k] = nil
        elseif frame_count - buf.frame >= GIFT_BUFFER_WINDOW then
            -- Held long enough → confirm as real gift capture (or egg pickup).
            all_known_keys[k] = true
            gift_capture_buffer[k] = nil
            local info = buf.info
            send({event="capture", key=k, hp=info.hp, maxHP=info.maxHP,
                  level=info.level, species_id=info.species_id or 0,
                  nickname=info.nickname or "",
                  area_id=buf.area, is_egg=info.is_egg or false,
                  form=info.form or 0, pokeball=info.pokeball or 0},
                 "capture(gift):" .. k:sub(1,8), true)
        end
    end

    -- ── hatch detection ──────────────────────────────────────────────────────
    -- An egg that hatches: prev_party[k].is_egg = true, curr_party[k].is_egg = false.
    -- The species_id changes from the egg placeholder (494) to the actual species at
    -- the same instant. Emit a "hatch" event so the server can update the linked record.
    for k, prev_info in pairs(prev_party) do
        local curr_info = curr_party[k]
        if curr_info and prev_info.is_egg and not curr_info.is_egg then
            send({event="hatch", key=k, species_id=curr_info.species_id or 0,
                  area_id=area, form=curr_info.form or 0,
                  hp=curr_info.hp, maxHP=curr_info.maxHP, level=curr_info.level},
                 "hatch:" .. k:sub(1,8), true)
            console.log(fmt("[SLink] hatch: %s → species %d at %s",
                k:sub(1,8), curr_info.species_id or 0, area))
        end
    end

    -- ── faint + party_to_box ─────────────────────────────────────────────────
    local had_alive = false
    local all_zero  = true

    for k, prev_info in pairs(prev_party) do
        local curr_info = curr_party[k]
        if curr_info then
            pending_party_to_box[k] = nil  -- still in party, clear debounce
            if prev_info.hp > 0 then had_alive = true end
            if prev_info.hp > 0 and curr_info.hp == 0 then
                send({event="faint", key=k, area_id=area}, "faint:" .. k:sub(1,8), true)
            end
            if curr_info.hp > 0 then all_zero = false end
        else
            -- Key disappeared — candidate for party_to_box (debounced, overworld only)
            if not in_battle and prev_info.hp > 0 and not sync_written_keys[k] then
                if not pending_party_to_box[k] then
                    pending_party_to_box[k] = {
                        frames = PARTY_DEBOUNCE_FRAMES,
                        info   = {hp=prev_info.hp, maxHP=prev_info.maxHP,
                                  level=prev_info.level, slot=prev_info.slot},
                    }
                end
            end
            all_zero = false
        end
    end

    -- ── debounce: party_to_box confirmation ──────────────────────────────────
    for k, ptb in pairs(pending_party_to_box) do
        if curr_party[k] then
            pending_party_to_box[k] = nil   -- back in party → glitch
        else
            ptb.frames = ptb.frames - 1
            if ptb.frames <= 0 then
                pending_party_to_box[k] = nil
                local st = ptb.info
                local stats_tbl = st and {level=st.level, maxHP=st.maxHP} or nil
                send({event="party_to_box", key=k, stats=stats_tbl},
                     "party_to_box:" .. k:sub(1,8), true)
            end
        end
    end

    -- ── debounce: box_to_party confirmation ──────────────────────────────────
    -- NOTE: Runs AFTER party_to_box confirmation so that PC swaps (Move Pokemon)
    -- send the deposit event before the retrieval event.
    for k, remaining in pairs(pending_box_to_party) do
        if not curr_party[k] then
            pending_box_to_party[k] = nil     -- vanished → was a glitch
        else
            remaining = remaining - 1
            if remaining <= 0 then
                pending_box_to_party[k] = nil
                send({event="box_to_party", key=k, area_id=area}, "box_to_party:" .. k:sub(1,8), true)
            else
                pending_box_to_party[k] = remaining
            end
        end
    end

    -- ── whiteout ─────────────────────────────────────────────────────────────
    if had_alive and all_zero then
        send({event="whiteout"}, "whiteout", true)
    end

    end -- party_diff_ok

    -- 10. Post-battle grace window → no_catch at end.
    if post_battle_frames > 0 then
        post_battle_frames = post_battle_frames - 1
        if post_battle_frames == 0 then
            -- Fire no_catch if wild, no capture, area is mapped, nuzlocke active
            if nuzlocke_active and battle_is_wild and not captured_this_battle
                    and battle_area_id and battle_area_id ~= ""
                    and not resolved_areas[battle_area_id]
                    and not GIFT_AREAS[battle_area_id] then
                resolved_areas[battle_area_id] = true
                send({event="no_catch", area_id=battle_area_id,
                      species_id=battle_enc_species, level=battle_enc_level},
                     "no_catch:" .. battle_area_id, true)
            end
            captured_this_battle = false
        end
    end

    -- 11. Activate nuzlocke once Pokéballs appear in bag (only after save validated).
    if not nuzlocke_active and writes_enabled and frame_count % 15 == 0 and hasPokeballs() then
        nuzlocke_active = true
        console.log("[SLink] nuzlocke ACTIVE (pokeballs in bag)")
        HUD.nuzlocke_start("Nuzlocke Start!")
        if M.playSE then M.playSE(M.SE_NUZLOCKE_START) end
    end

    -- 12. safe — first overworld frame after battle.
    if pending_safe and not in_battle then
        pending_safe = false
        send({event="safe"}, "safe", true)
    end

    -- 13. auto tick every TICK_INTERVAL frames.
    if frame_count % TICK_INTERVAL == 0 then
        local raw_count = M.readPartyCount()
        local save_ok   = raw_count >= 0 and raw_count <= 6
        local evt = {
            event         = "tick",
            ball_count    = countPokeballs(),
            has_pokeballs = nuzlocke_active,
            area_id       = area,
            loc_name      = loc,
            in_battle     = in_battle,
            -- TODO(NDS doubles): gBattlersCount address not yet discovered; always false.
            is_doubles    = false,
            badges        = M.readBadges1(),
            kanto_badges  = M.readBadges2(),
            trainer_name  = M.readTrainerName(),
        }
        if save_ok then
            local snap = build_party_snapshot(in_battle)
            -- Only include party if non-empty; an empty snap would clear server party_details.
            if #snap > 0 then evt.party = snap end
        end
        if in_battle then
            evt.is_trainer_battle = not M.isWildBattle()
            evt.trainer_id = M.readEnemyTrainerId()
            evt.opponent_name = M.readEnemyTrainerName()
            evt.is_doubles = M.isDoubleBattle()
            -- Read the full opponent party (moves, PP, form, abilities, items per slot)
            -- and merge into battle_seen_enemies so the team persists across switches.
            local fresh = M.readEnemyParty()
            local active_l = M.getBattlerPartyIndex(1) or 0  -- enemy_L party slot
            local active_r = evt.is_doubles and M.getBattlerPartyIndex(3) or nil
            -- Stat stages overlay for the currently-active enemy battlers.
            local stages_l = M.readStatStages(1)
            local stages_r = evt.is_doubles and M.readStatStages(3) or nil
            for ei, mon in ipairs(fresh) do
                local key = tostring(mon.species_id) .. ":" .. tostring(mon.level)
                mon.active = ((ei - 1) == active_l) or (active_r and (ei - 1) == active_r) or false
                if mon.active then
                    if (ei - 1) == active_l and stages_l then mon.stat_stages = stages_l end
                    if active_r and (ei - 1) == active_r and stages_r then mon.stat_stages = stages_r end
                end
                -- Merge into accumulator. Overwrite with live HP/PP/stat_stages on each tick,
                -- but keep the entry so switches don't lose history.
                battle_seen_enemies[key] = mon
            end
            -- Flatten accumulator → list for the event.
            local enemy_list = {}
            for _, mon in pairs(battle_seen_enemies) do
                enemy_list[#enemy_list + 1] = mon
            end
            -- Stable order: actives first, then by species:level lexicographic.
            table.sort(enemy_list, function(a, b)
                if (a.active and 1 or 0) ~= (b.active and 1 or 0) then
                    return (a.active and 1 or 0) > (b.active and 1 or 0)
                end
                local ka = tostring(a.species_id) .. ":" .. tostring(a.level)
                local kb = tostring(b.species_id) .. ":" .. tostring(b.level)
                return ka < kb
            end)
            evt.enemy_party = enemy_list
        end
        -- Incremental PC box scan: scan 1 box per tick cycle.
        if not in_battle and writes_enabled then
            local box = box_scan_idx
            local entries = {}
            for slot = 0, 29 do
                local addr = M.pcBoxAddr(box, slot)
                if addr then
                    local pid = mem_u32(addr)
                    if pid ~= 0 then
                        local sp, ot, hi, abl = M.decrypt_block_a_ext(addr)
                        -- Skip slots whose block-A doesn't decrypt to a valid
                        -- species. See gen5_bw_client.lua for full rationale —
                        -- prevents garbage PIDs from rendering as ???? entries.
                        if sp and sp >= 1 then
                            local key = ot and fmt("%08X:%08X", pid, ot) or fmt("%08X", pid)
                            local nick = M.readNickname(addr)
                            entries[#entries + 1] = {
                                box=box, slot=slot, key=key, species_id=sp,
                                held_item_id=hi or 0, ability_id=abl or 0,
                                nickname=nick or "",
                            }
                            -- Populate nick_label cache
                            if nick and nick ~= "" then
                                _nick_cache[key] = nick
                            elseif not _nick_cache[key] then
                                _nick_cache[key] = fmt("species#%d", sp)
                            end
                        end
                    end
                end
            end
            pc_box_cache[box] = entries
            box_scan_idx = (box_scan_idx + 1) % BOX_SCAN_TOTAL
            -- Flatten pc_box_cache into pc_boxes list (same format as Gen 3)
            local flat = {}
            for _, bx_entries in pairs(pc_box_cache) do
                for _, e in ipairs(bx_entries) do
                    flat[#flat + 1] = e
                end
            end
            evt.pc_boxes = flat
        end
        send(evt, "tick(auto)", true, true)
    end

    -- 14. Manual F keys.
    local keys = input.get()
    local function pressed(k) return keys[k] and not prev_keys[k] end

    if pressed("F1") then
        send({event="area_enter", area_id=area},
             "area_enter:" .. (area~="" and area or "(none)"), false)
    end
    if pressed("F2") then
        local base = M.partyAddr(0)
        if base and slotOccupied(base) then
            local k  = cachedMonKey(0, base)
            local hp = mem_u16(base + M.PKM.CUR_HP)
            local mx = mem_u16(base + M.PKM.MAX_HP)
            local lv = mem_u8 (base + M.PKM.LEVEL)
            send({event="capture", key=k, hp=hp, maxHP=mx, level=lv, area_id=area},
                 "capture(manual):" .. k:sub(1,8), false)
        else console.log("[SLink] F2: slot 0 empty") end
    end
    if pressed("F3") then
        local base = M.partyAddr(0)
        if base and slotOccupied(base) then
            local k = cachedMonKey(0, base)
            send({event="faint", key=k, area_id=area}, "faint:" .. k:sub(1,8), false)
        else console.log("[SLink] F3: slot 0 empty") end
    end
    if pressed("F4") then
        local area4 = area ~= "" and area or "(none)"
        send({event="no_catch", area_id=area4}, "no_catch:" .. area4, false)
    end
    if pressed("F5") then send({event="whiteout"}, "whiteout",    false) end
    if pressed("F6") then send({event="safe"},      "safe",        false) end
    if pressed("F7") then
        send({event="tick", ball_count=countPokeballs(), has_pokeballs=nuzlocke_active,
              area_id=area, in_battle=in_battle,
              party=build_party_snapshot(in_battle)}, "tick(manual)", false)
    end
    if pressed("F8") then
        -- Manual party_to_box: deposit slot 0 to PC
        local addr = M.partyAddr(0)
        if addr and mem_u32(addr) ~= 0 then
            local k = cachedMonKey(0, addr)
            send({event="party_to_box", key=k}, "party_to_box(manual):" .. k:sub(1,8), false)
        end
    end
    if pressed("F9") then
        -- Direct memorialize: slot 0 → Box 18, no server (Lua-only write)
        if writes_enabled then
            local addr = M.partyAddr(0)
            local f9_count = M.readPartyCount()
            if f9_count <= 1 then
                console.log("[SLink] F9: blocked — would empty party")
            elseif addr and mem_u32(addr) ~= 0 then
                local k = cachedMonKey(0, addr)
                pcall(exec_memorialize, k)
            end
        else
            console.log("[SLink] F9: writes disabled — cannot memorialize")
        end
    end
    prev_keys = keys

    -- 15. HUD overlay (drawn last — on top of everything).
    hud_render()

    -- 17. Clear per-frame write guard + advance prev state.
    sync_written_keys = {}
    if party_diff_ok then
        prev_party = curr_party
        -- Re-inject keys still in party_to_box debounce so they stay "seen" next frame.
        for k, ptb in pairs(pending_party_to_box) do
            if not prev_party[k] then prev_party[k] = ptb.info end
        end
    end
    prev_zone_id   = zone_id
    prev_area      = area
    prev_loc       = loc
    prev_in_battle = in_battle
end

local function on_frame_safe()
    local ok, err = pcall(on_frame)
    if not ok then console.log("[SLink] ERROR (handler kept alive): " .. tostring(err)) end
end

-- ── Startup ────────────────────────────────────────────────────────────────────
console.clear()
C.init(SERVER_HOST, SERVER_PORT)
console.log(fmt("[SLink] TCP: %s:%d  Player: %s", SERVER_HOST, SERVER_PORT, PLAYER_ID))
console.log("[SLink] Game: HeartGold/SoulSilver (NDS)  Profile: vanilla HGSS")
console.log("[SLink] Auto: hello area_enter capture(battle/gift) box_to_party party_to_box faint no_catch(wild) whiteout safe tick")
console.log("[SLink] Manual: F1=area F2=capture F3=faint F4=no_catch F5=whiteout F6=safe F7=tick F8=deposit F9=memorialize")
console.log(fmt("[SLink] Writes: %s (validateSave gates force_faint/memorialize/box_mon/party_mon)",
    writes_enabled and "ON" or "OFF — waiting for save validation"))
console.log("[SLink] --- monitoring started ---")

-- Seed prev_party (best-effort; M.init() may fail before save loads)
do
    local b = M.init()
    if b then
        prev_party, _ = index_party(false)
        for k in pairs(prev_party) do all_known_keys[k] = true end
        -- Also seed from PC boxes so withdrawals aren't mistaken for captures
        for box = 0, BOX_SCAN_TOTAL - 1 do
            for slot = 0, 29 do
                local addr = M.pcBoxAddr(box, slot)
                if addr then
                    local pid = mem_u32(addr)
                    if pid ~= 0 then
                        local sp, ot = M.decrypt_block_a_ext(addr)
                        if ot then
                            all_known_keys[fmt("%08X:%08X", pid, ot)] = true
                        end
                    end
                end
            end
        end
        prev_zone_id = M.readZoneID()
        prev_area    = AREAS[prev_zone_id] or ""
        prev_loc     = LOCATIONS[prev_zone_id] or ""
        prev_in_battle = M.isInBattle()
    end
end

event.onframeend(on_frame_safe, "slink_events")
console.log("[SLink] Running — play normally to trigger events…")
