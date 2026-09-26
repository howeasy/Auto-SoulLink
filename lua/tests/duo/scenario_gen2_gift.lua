-- lua/tests/duo/scenario_gen2_gift.lua -- the gen2_new `gift` duo (S-8 gifts) from an O-33 synthetic setup:
-- lua/tests/duo/gen2_synth_duo.lua kind "bill" (its header is the marker contract).
local ROOT = SLINK_DUO and SLINK_DUO.wt or os.getenv("SLINK_ROOT") or "."
return dofile(ROOT .. "/lua/tests/duo/gen2_synth_duo.lua").new("bill")
