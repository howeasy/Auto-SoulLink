--[[
  lua/tests/gen2_sp_lowwater_gate.lua -- SP-LOWWATER (docs/gen2/POST_RC_CARDS.md): the launcher of the sibling mode
  of lua/tests/gen2_sfx_gate.lua (read its header). One fresh boot per mode; the mode comes from
  SLINK_GEN2_SP_LOWWATER (A_held | B_held | released), set by tests/live/test_gen2_sp_lowwater_gate.py.
  Result file: patch/build/gen2_sp_lowwater_gate_result.txt (tools/run_gb_gate.py reads the first result path named
  here, so the sfx gate's own result file is never overwritten).
--]]
local ROOT = SLINK_ROOT or os.getenv("SLINK_ROOT")
assert(ROOT, "SLINK_ROOT unset -- launch via tools/run_gb_gate.py")
assert(os.getenv("SLINK_GEN2_SP_LOWWATER"), "SLINK_GEN2_SP_LOWWATER unset")
SLINK_GEN2_GATE_LIBRARY = true
local P = dofile(ROOT .. "/lua/tests/gen2_sfx_gate.lua")
SLINK_GEN2_GATE_LIBRARY = nil
P.RESULT = "patch/build/gen2_sp_lowwater_gate_result.txt"
local SG, F = P.scripted_gate(ROOT)
local api = SG.bizhawk()
client_screenshot = function(path) client.screenshot(path) end
live_api = api
P.main(api, os.getenv, SG, F)
api.exit()
error("slink-gate-finished", 0)   -- client.exit() is asynchronous; stop here for real
