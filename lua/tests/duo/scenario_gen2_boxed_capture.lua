-- lua/tests/duo/scenario_gen2_boxed_capture.lua -- the gen2_new `boxed_capture` duo (S-2/S-3 box half, D-3) from an O-33 synthetic setup:
-- lua/tests/duo/gen2_synth_duo.lua kind "full" (its header is the marker contract).
local ROOT = SLINK_DUO and SLINK_DUO.wt or os.getenv("SLINK_ROOT") or "."
return dofile(ROOT .. "/lua/tests/duo/gen2_synth_duo.lua").new("full")
