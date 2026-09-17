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
    if sys_ok and (sys == "GB" or sys == "GBC") then
        local Entry = dofile(_dir .. "gen1/entry.lua")
        if Entry.detect_title(function(addr) return memory.read_u8(addr, "ROM") end) then
            dofile(_dir .. "gen1/run.lua")
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
