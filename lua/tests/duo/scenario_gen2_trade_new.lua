-- lua/tests/duo/scenario_gen2_trade_new.lua -- P4.3e native SLINK TRADE duo, case gen2_trade_new.
-- The plan, markers and verdict are lua/tests/duo/gen2_trade.lua (T.CASES.new); this file only names the case.
local here = debug.getinfo(1, "S").source:match("^@(.*[/\\])") or ""
return dofile(here .. "gen2_trade.lua").scenario("new")
