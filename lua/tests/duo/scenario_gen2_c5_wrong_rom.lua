-- lua/tests/duo/scenario_gen2_c5_wrong_rom.lua -- C-5 refused-at-hello duo (lua/tests/duo/gen2_c5_refused.lua).
local ROOT = SLINK_DUO and SLINK_DUO.wt or os.getenv("SLINK_ROOT") or "."
return dofile(ROOT .. "/lua/tests/duo/gen2_c5_refused.lua").new()
