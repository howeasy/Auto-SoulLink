-- lua/tests/duo/scenario_gen2_egg_hatch.lua -- the gen2_new `egg_hatch` duo (S-8 hatch as gift_daycare (O-15)) from an O-33 synthetic setup:
-- lua/tests/duo/gen2_synth_duo.lua kind "hatch" (its header is the marker contract).
local ROOT = SLINK_DUO and SLINK_DUO.wt or os.getenv("SLINK_ROOT") or "."
return dofile(ROOT .. "/lua/tests/duo/gen2_synth_duo.lua").new("hatch")
