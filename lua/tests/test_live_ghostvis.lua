-- test_live_ghostvis.lua — reproduce "ghost randomly disappears on the same map". Walk the player
-- around (real engine movement + camera scroll) while keeping the ghost 2 tiles away (clearly
-- on-screen), and catch any frame where the ghost's sprite is invisible despite being on-screen.
-- Logs the sprite callback ptr + OE flags so we can see WHAT hides it.
local WT = "E:/Google Drive/SLink/.claude/worktrees/condescending-bassi-9175e6"
local OUT = WT .. "/patch/build/ghostvis_result.txt"
package.path = WT .. "/lua/?.lua;" .. package.path
local PG = require("peer_ghost_npc")
local OE, GS, OST, GST = 0x02036E38, 0x0202063C, 0x24, 0x44
local function p_m9() return memory.read_u8(OE + 0x09) end
local function p_mA() return memory.read_u8(OE + 0x0A) end
local function p_tx() return memory.read_u16_le(OE + 0x10) end
local function p_ty() return memory.read_u16_le(OE + 0x12) end
local function spr_invis(s) return (memory.read_u8(GS + s*GST + 0x3E) & 0x04) ~= 0 end
local function spr_inuse(s) return (memory.read_u8(GS + s*GST + 0x3E) & 0x01) ~= 0 end
local function spr_cb(s) return memory.read_u32_le(GS + s*GST + 0x1C) end
local function oe_flags(i) return memory.read_u8(OE + i*OST + 0x00) end       -- bit0=active
local function oe_flags2(i) return memory.read_u8(OE + i*OST + 0x01) end      -- invisible bit lives here-ish

local lines={}; local fails=0
local function log(s) lines[#lines+1]=s; console.log(s) end
local function finish() log(fails==0 and "RESULT: PASS" or ("RESULT: FAIL ("..fails.." hidden-while-onscreen frames)"))
  local f=io.open(OUT,"w"); if f then f:write(table.concat(lines,"\n").."\n"); f:close() end; client.exit() end

pcall(function() client.speedmode(400) end)
pcall(savestate.load, "E:/Howard/Bizhawk/GBA/State/slink_overworld.State")
emu.frameadvance(); pcall(memory.usememorydomain,"System Bus")
PG.init()
if not PG.present() then log("FAIL: beacon absent"); finish(); return end

local m9, mA = p_m9(), p_mA()
-- seed the ghost 2 tiles east, spawn it
PG.on_ghost_pos({ mg=m9, mn=mA, x=(p_tx()+2)*16, y=p_ty()*16, f=4, mv=0 })
for _=1,40 do PG.on_frame(); emu.frameadvance() end
local d = PG.debug()
log("spawned oeId="..tostring(d.oeId).." sprId="..tostring(d.sprId).." cb=0x"..(d.sprId and string.format("%08X",spr_cb(d.sprId)) or "?"))
if not d.oeId then log("FAIL: never spawned"); finish(); return end
local sid = d.sprId
local cb0 = spr_cb(sid)

-- Walk the player around for 400 frames; keep the ghost 2 tiles east (on-screen). Flag any frame
-- the ghost is invisible while on-screen.
local dirs = {"Down","Up","Left","Right"}
local cb_changed, first_hidden = false, nil
for n=1,400 do
  local dir = dirs[((n // 16) % 4) + 1]   -- change direction every 16 frames to roam
  joypad.set({ [dir]=true })
  -- keep the ghost 2 tiles east of wherever the player now is
  PG.on_ghost_pos({ mg=p_m9(), mn=p_mA(), x=(p_tx()+2)*16, y=p_ty()*16, f=4, mv=1 })
  PG.on_frame()
  emu.frameadvance()
  if PG.debug().oeId == nil then log("note: ghost dropped/re-spawning at frame "..n);
  else
    if spr_cb(sid) ~= cb0 and not cb_changed then cb_changed = true
      log(string.format("frame %d: sprite callback CHANGED 0x%08X -> 0x%08X (engine re-pointed it)", n, cb0, spr_cb(sid))) end
    if spr_inuse(sid) and spr_invis(sid) then
      fails = fails + 1
      if not first_hidden then first_hidden = n
        log(string.format("frame %d: HIDDEN while on-screen — cb=0x%08X oeFlags=0x%02X/0x%02X playerTile=(%d,%d)",
          n, spr_cb(sid), oe_flags(d.oeId), oe_flags2(d.oeId), p_tx(), p_ty())) end
    end
  end
end
joypad.set({})
log(string.format("hidden-while-onscreen frames: %d/400 ; callback re-pointed: %s", fails, tostring(cb_changed)))
PG.on_ghost_clear()
finish()
