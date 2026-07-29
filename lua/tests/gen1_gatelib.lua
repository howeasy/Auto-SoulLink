--[[
  lua/tests/gen1_gatelib.lua — Gen 1 view of the shared GB gatelib.

  The boot drive moved to lua/tests/gatelib.lua when Gen 2 became its second caller. This
  shim exists so the six Gen 1 gates that predate the split, and tools/run_gb_gate.py's
  verdict-file regex, keep working unchanged.

  New gates should dofile gatelib.lua directly and pass {game = "..."}.
--]]

local ROOT = SLINK_ROOT or os.getenv("SLINK_ROOT")
assert(ROOT, "SLINK_ROOT unset — launch via tools/run_gb_gate.py")

local Shared = dofile(ROOT .. "/lua/tests/gatelib.lua")

local Lib = {}

function Lib.start(gate_name, opts)
    opts = opts or {}
    opts.game = opts.game or "gen1_rby"
    return Shared.start(gate_name, opts)
end

return Lib
