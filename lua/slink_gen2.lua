--[[
  slink_gen2.lua — SLink Gen 2 Launcher
  ======================================
  Load this script in BizHawk's Lua Console to start SLink
  for Gen 2 Crystal.

  Configure host/port/player below, then load this file.
  The launcher sets up the environment and starts the Gen 2 client.
--]]

-- ── CONFIGURE ─────────────────────────────────────────────────────────────────
SLINK_HOST   = "127.0.0.1"   -- IP of the machine running server.py
SLINK_PORT   = 54321          -- TCP port (must match server --port)
SLINK_PLAYER = "a"            -- "a" or "b"
-- ─────────────────────────────────────────────────────────────────────────────

local _dir = debug.getinfo(1, "S").source:match([=[@(.+[/\])]=]) or ""
dofile(_dir .. "clients/gen2_crystal_client.lua")
