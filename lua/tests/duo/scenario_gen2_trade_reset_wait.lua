-- lua/tests/duo/scenario_gen2_trade_reset_wait.lua -- P4.3e native SLINK TRADE duo, case gen2_trade_reset_wait.
-- The plan, markers and verdict are lua/tests/duo/gen2_trade.lua (T.CASES.reset_wait); this file only names the case.
local here = debug.getinfo(1, "S").source:match("^@(.*[/\\])") or ""
return dofile(here .. "gen2_trade.lua").scenario("reset_wait")
