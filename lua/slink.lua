--[[
  lua/slink.lua — Universal SLink Entry Point
  ============================================
  Auto-detects the loaded ROM and starts the appropriate game client.
  The launcher sets SLINK_HOST, SLINK_PORT, SLINK_PLAYER as globals before
  running this file — those are consumed by whichever client gets loaded.
--]]

local _dir = debug.getinfo(1, "S").source:match([=[@(.+[/\])]=]) or ""
package.path = _dir .. "?.lua;" .. _dir .. "?/init.lua;" .. package.path

-- ── Console tee ──────────────────────────────────────────────────────────────
-- BizHawk's Lua console scrolls and drops old lines, so when something logs
-- a lot at startup (BizHawk's "Unable to find domain" warnings, our diagnostic
-- output, etc.) the user can't scroll back far enough to copy it. Mirror every
-- console.log() call to slink_lua.log in the project root for post-mortem.
-- The log is truncated on each run so old content doesn't accumulate.
do
    local log_path = _dir .. "../slink_lua.log"
    -- Close any handle left open by a previous script-load so reloads don't leak.
    if _G.__slink_log_fh then
        pcall(function() _G.__slink_log_fh:close() end)
        _G.__slink_log_fh = nil
    end
    -- Open once for the lifetime of this run (truncate-at-boot via "w").
    -- Keeping the handle open avoids per-call open/close, which is several ms
    -- per log line on Drive-synced paths and a primary source of event-frame stutter.
    local fh = io.open(log_path, "w")
    if fh then
        fh:write(string.format("=== SLink Lua boot %s ===\n", os.date()))
        fh:flush()
        _G.__slink_log_fh = fh
        local orig_log = console.log
        console.log = function(...)
            local h = _G.__slink_log_fh
            if h then
                local parts = {...}
                for i = 1, select("#", ...) do
                    parts[i] = tostring(parts[i])
                end
                local ok = pcall(function()
                    h:write(table.concat(parts, "\t") .. "\n")
                    h:flush()
                end)
                if not ok then
                    -- Drop the handle on first write failure so we don't
                    -- hot-loop reopening; reload the script to recover.
                    pcall(function() h:close() end)
                    _G.__slink_log_fh = nil
                end
            end
            orig_log(...)
        end
        console.log("[SLink] Console tee -> " .. log_path)
    end
end

-- ── Gen 1 route ──────────────────────────────────────────────────────────────
-- Red/Blue/Yellow run the rewritten client under lua/gen1/, which owns its own
-- cartridge detection (entry.lua Entry.detect_title). It is checked before the
-- game_detect registry so the Gen 1 entry is never decided in two places; Gen 2-5
-- fall through unchanged. emu is indexed inside the pcall because a broken/absent
-- core would otherwise error before the guard could refuse.
do
    local sys_ok, sys = pcall(function() return emu.getsystemid() end)
    -- "SGB" is what EmuHawk reports when GbAsSgb is on (Gambatte in Super Game Boy mode,
    -- opt-in, off in the stock config); the cartridge is the same Gen 1 ROM.
    if sys_ok and (sys == "GB" or sys == "GBC" or sys == "SGB") then
        local Entry = dofile(_dir .. "gen1/entry.lua")
        if Entry.detect_title(function(addr) return memory.read_u8(addr, "ROM") end) then
            -- The engine hooks (gen1/signals.lua) are only proven on 2.11.x; on 2.9.1 they
            -- latched a failure and every capture/battle went unreported (live run 2026-09-22).
            local ver = tostring(client.getversion and client.getversion() or "?")
            local maj, min = ver:match("^(%d+)%.(%d+)")
            if not maj or tonumber(maj) * 100 + tonumber(min) < 211 then
                error("[SLink] BizHawk " .. ver .. " is too old for Gen 1 -- install BizHawk 2.11 or newer", 0)
            end
            dofile(_dir .. "gen1/run.lua")
            return
        end
    end
end

-- ── Gen 3 route ──────────────────────────────────────────────────────────────
-- FireRed/LeafGreen admitted as pack gen3_frlg by HASH or ANCHORS run under lua/gen3/, the
-- rewritten client. Header-only admissions (an unpinned cartridge whose header merely says
-- BPRE/BPGE), Radical Red (gen3_rr, until G5), Emerald, Archipelago and any other GBA
-- cartridge fall through to game_detect -> the old client exactly as today (owner rulings
-- 2026-09-23, docs/gen3/PLAN.md §0). `admitted_by ~= "header"` matters: RR carries FireRed's
-- header code, so an unpinned RR build must not be routed here and refused by the site check.
--
-- TODO(lua/gen3/entry.lua): once entry.lua defines Entry.ROUTED (the P5 card that adds
-- gen3_rr to it), read that instead of the local set below; until then this is the routed
-- set's one home.
local _GEN3_ROUTED_PACKS = { gen3_frlg = true }
do
    local sys_ok, sys = pcall(function() return emu.getsystemid() end)
    if sys_ok and sys == "GBA" then
        -- Admission itself is isolated in a pcall: a refusal (or, defensively, any admission
        -- error) must fall through to game_detect exactly like an unrecognised cartridge,
        -- never crash the launcher. The BizHawk-version guard below is deliberately OUTSIDE
        -- this pcall so it propagates like the Gen 1 route's does.
        local admit_ok, Entry, admitted = pcall(function()
            local E = dofile(_dir .. "gen3/entry.lua")
            if not E then return nil end
            local function rom_read(off, n)
                local t = {}
                for i = 1, n do t[i] = memory.read_u8(off + i - 1, "ROM") end
                return t
            end
            local hash = gameinfo and gameinfo.getromhash and gameinfo.getromhash() or ""
            local ok_hc, header_code = pcall(E.header_code, rom_read)
            local a = E.admit({ root = _dir .. "..", json = dofile(_dir .. "json_codec.lua"),
                                rom_hash = hash, rom_read = rom_read,
                                header_code = ok_hc and header_code or "" })
            return E, a
        end)
        local routed_set = admit_ok and Entry and (Entry.ROUTED or _GEN3_ROUTED_PACKS) or nil
        if admit_ok and Entry and admitted and routed_set[admitted.pack]
           and admitted.admitted_by ~= "header" then
            -- The engine hooks are only proven on 2.11.x (same guard as the Gen 1 route,
            -- slink.lua Gen 1 block above).
            local ver = tostring(client.getversion and client.getversion() or "?")
            local maj, min = ver:match("^(%d+)%.(%d+)")
            if not maj or tonumber(maj) * 100 + tonumber(min) < 211 then
                error("[SLink] BizHawk " .. ver .. " is too old for Gen 3 -- install BizHawk 2.11 or newer", 0)
            end
            dofile(_dir .. "gen3/run.lua")
            return
        end
    end
end

-- Detect which game is loaded
package.loaded["game_detect"]       = nil
local game_detect = require("game_detect")
local detected    = game_detect.detect()

-- Map game_id to client script path
-- No gen1_rby row: the Gen 1 route above returns before this table is reached, so a
-- row here could only ever mis-fire (game_detect's Gen 1 detector is strictly narrower
-- than Entry.detect_title and runs behind the same GB/GBC guard).
local _CLIENT_MAP = {
    gen2_crystal  = "clients/gen2_crystal_client.lua",
    gen3_frlge    = "clients/gen3_frlge_client.lua",
    gen4_hgsspt   = "clients/gen4_hgsspt_client.lua",
    gen5_bw       = "clients/gen5_bw_client.lua",
}

local client_path = _CLIENT_MAP[detected.game_id]
if not client_path then
    error("[SLink] No client available for detected game: " .. detected.game_id
          .. " (" .. detected.module.display_name .. ")")
end

dofile(_dir .. client_path)
