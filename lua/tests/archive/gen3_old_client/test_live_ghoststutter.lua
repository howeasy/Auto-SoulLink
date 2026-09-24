-- test_live_ghoststutter.lua — REPRODUCE the user's "uneven/unnatural" walk, then prove it's fixed.
--
-- The peer is another real player walking continuously. The sender broadcasts their sub-pixel
-- WORLD-PIXEL position at ~20 Hz (on_ghost_pos every 3rd frame); the patch LERPs the ghost toward
-- it. We drive the REAL receiver (peer_ghost_npc) exactly as the client does and sample the ghost
-- sprite pos1.x every frame. With a continuously-moving partner the ghost must slide ~monotonically
-- with NO multi-frame stalls. The local player is stationary (savestate) so coordOffset is constant
-- and pos1.x == the ghost's own world movement.
--
-- (The OLD tile-quantized held-movement driver froze ~10 frames at each tile boundary. The sub-pixel
--  LERP driver slides continuously.)
local WT = SLINK_ROOT or os.getenv("SLINK_ROOT") or debug.getinfo(1, "S").source:match([=[^@(.*)[/\]lua[/\]tests[/\]]=])
assert(WT, "repo root unknown — launch via: python tools/run_gate.py <this script>")
local OUT = WT .. "/patch/build/ghoststutter_result.txt"
package.path = WT .. "/lua/?.lua;" .. package.path
local PG = require("peer_ghost_npc")
local OE, OST, GS, GST = 0x02036E38, 0x24, 0x0202063C, 0x44
local function p_grp() return memory.read_u8(OE + 0x0A) end
local function p_num() return memory.read_u8(OE + 0x09) end
local function p_tx()  return memory.read_s16_le(OE + 0x10) end
local function p_ty()  return memory.read_s16_le(OE + 0x12) end
local function p_gfx() return memory.read_u8(OE + 0x05) end
local function oe_spr(i) return memory.read_u8(OE + i*OST + 0x04) end
local function spr_x(s)  return memory.read_s16_le(GS + s*GST + 0x20) end

local lines={}; local fails=0
local function log(s) lines[#lines+1]=s; console.log(s) end
local function check(n,c,e) if not c then fails=fails+1 end; log(string.format("  [%s] %s%s",c and "PASS" or "FAIL",n,e and "  "..e or "")) end
local function finish() log(fails==0 and "RESULT: PASS" or ("RESULT: FAIL ("..fails..")"))
  local f=io.open(OUT,"w"); if f then f:write(table.concat(lines,"\n").."\n"); f:close() end; client.exit() end

pcall(function() client.speedmode(400) end)
pcall(savestate.load, "E:/Howard/Bizhawk/GBA/State/slink_overworld.State")
emu.frameadvance(); pcall(memory.usememorydomain,"System Bus")
PG.init()
check("receiver reports patch present", PG.present()); if not PG.present() then finish(); return end

local grp, num, ptx, pty, gfx = p_grp(), p_num(), p_tx(), p_ty(), p_gfx()
log(string.format("local map=(grp%d,num%d) tile=(%d,%d) gfx=%d", grp, num, ptx, pty, gfx))

-- Partner world-pixel position (same map coord space): start one tile east, walk continuously east.
local wy = pty * 16
local wx = (ptx + 1) * 16
local function feed() PG.on_ghost_pos({ mg=grp, mn=num, x=wx, y=wy, f=4, mv=1, an=6, run=0, gfx=gfx }) end
feed()
local oe
for _=1,150 do PG.on_frame(); emu.frameadvance(); oe = PG.debug().oeId; if oe and oe < 16 then break end end
check("receiver spawned the ghost", oe and oe < 16, "oeId=" .. tostring(oe))
if not (oe and oe < 16) then finish(); return end
local sid = oe_spr(oe)
-- settle (ghost snaps to the start position, queue calm)
for k=1,60 do if k%3==0 then feed() end; PG.on_frame(); emu.frameadvance() end

-- WALK the partner continuously east at ~1 px/frame (player walk speed). Two passes:
--   steady   — feed every 2nd frame (the production 30 Hz moving cadence): with the lead
--              extrapolation the ghost must NEVER freeze while the partner moves (<= 1).
--   jittered — drop every 4th send (server coalescing / pump hiccups): the lead must bridge
--              the 4-frame gaps (<= 2). The pre-lead driver fails this pass (reach-and-pause).
local function walk_pass(name, drop_every, max_allowed)
  local samples = {}
  local fnum, sends = 0, 0
  for k = 1, 96 do
    fnum = fnum + 1
    wx = wx + 1                              -- partner advances 1 px this frame (continuous)
    if fnum % 2 == 0 then                     -- 30 Hz sub-pixel sampling of the moving partner
      sends = sends + 1
      if not (drop_every and sends % drop_every == 0) then feed() end
    end
    PG.on_frame()
    emu.frameadvance()
    samples[#samples+1] = spr_x(sid)
  end
  local WARM = 10
  local zero_run, max_zero_run, total_zero, moves = 0, 0, 0, 0
  for i = WARM + 1, #samples do
    local d = samples[i] - samples[i-1]
    if d == 0 then zero_run = zero_run + 1; total_zero = total_zero + 1
      if zero_run > max_zero_run then max_zero_run = zero_run end
    else zero_run = 0; moves = moves + 1 end
  end
  log(name .. " pos1.x full seq: " .. table.concat(samples, ","))
  log(string.format("%s window: %d frames, %d moved, %d frozen, longest frozen run = %d",
      name, #samples - WARM, moves, total_zero, max_zero_run))
  check(name .. ": ghost moved during the walk", moves > 0)
  check(name .. ": no stall while the partner is moving", max_zero_run <= max_allowed,
        "longest frozen run = " .. max_zero_run .. " frames (want <= " .. max_allowed .. ")")
end
walk_pass("steady", nil, 1)
walk_pass("jittered", 4, 2)
PG.on_ghost_pos({ mg=grp, mn=num, x=wx, y=wy, f=4, mv=0, an=3, run=0, gfx=gfx })
for _=1,8 do PG.on_frame(); emu.frameadvance() end
finish()
