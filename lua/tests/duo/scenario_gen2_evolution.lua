-- lua/tests/duo/scenario_gen2_evolution.lua -- the gen2_new `evolution` duo (S-5 evolution, D-1 key_change) from an
-- O-33 synthetic setup: lua/tests/duo/gen2_synth_duo.lua kind "evolve" (its header is the marker contract).
local ROOT = SLINK_DUO and SLINK_DUO.wt or os.getenv("SLINK_ROOT") or "."
return dofile(ROOT .. "/lua/tests/duo/gen2_synth_duo.lua").new("evolve")
