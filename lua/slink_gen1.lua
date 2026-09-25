--[[
  slink_gen1.lua — SLink Gen 1 Launcher
  ======================================
  Load this script in BizHawk's Lua Console to start SLink
  for Gen 1 games (Red, Blue, Yellow).

  Configure host/port/player below, then load this file.
  The launcher sets up the environment and starts the Gen 1 client.
--]]

-- ── CONFIGURE ─────────────────────────────────────────────────────────────────
SLINK_HOST   = "127.0.0.1"   -- IP of the machine running server.py
SLINK_PORT   = 54321          -- TCP port (must match server --port)
SLINK_PLAYER = "a"            -- "a" or "b"
-- ─────────────────────────────────────────────────────────────────────────────

local _dir = debug.getinfo(1, "S").source:match("@(.+[/\\])") or ""
-- Same floor as slink.lua's Gen 1 branch: the engine hooks are only proven on 2.11.x.
local ver = tostring(client.getversion and client.getversion() or "?")
local maj, min = ver:match("^(%d+)%.(%d+)")
if not maj or tonumber(maj) * 100 + tonumber(min) < 211 then
    error("[SLink] BizHawk " .. ver .. " is too old for Gen 1 -- install BizHawk 2.11 or newer", 0)
end
dofile(_dir .. "gen1/run.lua")
