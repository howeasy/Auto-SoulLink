--[[
  lua/slink_gen5.lua — SLink launcher for Gen 5 (Black / White / BW2)
  
  USAGE:
    1. Open BizHawk with a Pokémon Black, White, Black 2, or White 2 ROM.
    2. In the Lua Console, open this file (File → Open Script…).
    3. Configure SLINK_HOST, SLINK_PORT, and SLINK_PLAYER below if needed.
    4. Make sure server/server.py is running.

  The script auto-detects the ROM variant (Black/White/BW2) and loads
  the appropriate memory profile.

  SLINK_HOST   — IP address of the machine running server/server.py
                 Use "127.0.0.1" if running on the same machine.
  SLINK_PORT   — TCP port of the SLink server (default: 54321).
  SLINK_PLAYER — "a" for Player 1, "b" for Player 2.
--]]

SLINK_HOST   = "127.0.0.1"
SLINK_PORT   = 54321
SLINK_PLAYER = "a"

-- Resolve client path relative to this launcher.
local _src = debug.getinfo(1, "S").source:match("@(.+[/\\])") or ""
dofile(_src .. "clients/gen5_bw_client.lua")
