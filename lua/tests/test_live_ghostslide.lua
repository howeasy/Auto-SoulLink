-- test_live_ghostslide.lua — does the ghost SLIDE sub-pixel between tiles, or jump 16px at a time?
-- Sample the ghost sprite's pos1.x (gSprites+0x20) every frame while it walks and report the
-- per-frame deltas. A real walk slides ~1-2px/frame; a jump shows ~16px steps (or snap teleports).
local WT = "E:/Google Drive/SLink/.claude/worktrees/condescending-bassi-9175e6"
local OUT = WT .. "/patch/build/ghostslide_result.txt"
local MB = dofile(WT .. "/lua/mailbox.lua")
local OST, GST = 0x24, 0x44
local function poe() return MB.player_oe() end
local function oe_spr(i) return memory.read_u8(0x02036E38 + i*OST + 0x04) end
local function oe_cx(i) return memory.read_s16_le(0x02036E38 + i*OST + 0x10) end
local function spr_x(s) return memory.read_s16_le(0x0202063C + s*GST + 0x20) end

local lines={}; local fails=0
local function log(s) lines[#lines+1]=s; console.log(s) end
local function check(n,c,e) if not c then fails=fails+1 end; log(string.format("  [%s] %s%s",c and "PASS" or "FAIL",n,e and "  "..e or "")) end
local function finish() log(fails==0 and "RESULT: PASS" or ("RESULT: FAIL ("..fails..")"))
  local f=io.open(OUT,"w"); if f then f:write(table.concat(lines,"\n").."\n"); f:close() end; client.exit() end

pcall(function() client.speedmode(400) end)
pcall(savestate.load, "E:/Howard/Bizhawk/GBA/State/slink_overworld.State")
emu.frameadvance(); pcall(memory.usememorydomain,"System Bus")
check("patch present", MB.present()); if not MB.present() then finish(); return end

local px = memory.read_s16_le(poe()+0x10); local py = memory.read_s16_le(poe()+0x12); local g = memory.read_u8(poe()+0x05)
MB.ghost_set_target(px+7, py, 4, 0, g); MB.ghost_spawn(g)
local oe = 16; for _=1,90 do emu.frameadvance(); oe = MB.ghost_oe(); if oe < 16 then break end end
check("ghost spawned", oe < 16); if oe >= 16 then finish(); return end
local sid = oe_spr(oe)

-- Walk it and record pos1.x each frame; classify the deltas.
local last = spr_x(sid)
local deltas, big = {}, 0
local seq = {}
for s = 1, 80 do
  MB.ghost_set_target(px+7, py, 4, 0, g)
  emu.frameadvance()
  local x = spr_x(sid)
  local d = x - last
  if d ~= 0 then deltas[#deltas+1] = d; if math.abs(d) >= 8 then big = big + 1 end end
  if #seq < 24 then seq[#seq+1] = x end
  last = x
end
log("pos1.x sequence (first 24 frames): " .. table.concat(seq, ","))
local dl = {}; for _,d in ipairs(deltas) do dl[#dl+1] = d end
log("non-zero pos1.x deltas: " .. table.concat(dl, ","))
log("frames with >=8px jump: " .. big .. " / " .. #deltas .. " moving frames")

check("the ghost slid (had sub-tile pixel steps, not only 16px jumps)", #deltas > 0 and big == 0,
      big .. " big jumps among " .. #deltas .. " moves")
MB.ghost_clear()
finish()
