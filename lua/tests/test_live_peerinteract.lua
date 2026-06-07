-- test_live_peerinteract.lua — talk-to-ghost with the engine-driven ghost. The patch spawns the
-- ghost (OP_GHOST_SPAWN) and AUTO-ARMS interaction on it; we walk it to the tile in front of the
-- player, press A facing it, and assert pi_count bumps. The patch NO LONGER opens its own box on
-- interact (the SERVER now drives the talk-to-partner menu via OP_SHOW_MENU; a local box would set
-- sScriptContext2Enabled and make that menu bounce) — so we also assert no box auto-opened.
-- Load with the PATCHED ROM + overworld savestate.
local WT = "E:/Google Drive/SLink/.claude/worktrees/condescending-bassi-9175e6"
local OUT = WT .. "/patch/build/peerinteract_result.txt"
local MB = dofile(WT .. "/lua/mailbox.lua")
local OE, OST, gStringVar4 = 0x02036E38, 0x24, 0x02021D18
local function p_tx() return memory.read_s16_le(OE + 0x10) end
local function p_ty() return memory.read_s16_le(OE + 0x12) end
local function p_gfx() return memory.read_u8(OE + 0x05) end
local function oe_cx(i) return memory.read_s16_le(OE + i*OST + 0x10) end
local function oe_cy(i) return memory.read_s16_le(OE + i*OST + 0x12) end
local function face_right() local v = memory.read_u8(OE + 0x18); memory.write_u8(OE + 0x18, (v & 0xF0) | 4) end

local lines={}; local fails=0
local function log(s) lines[#lines+1]=s; console.log(s) end
local function check(n,c,e) if not c then fails=fails+1 end; log(string.format("  [%s] %s%s",c and "PASS" or "FAIL",n,e and "  "..e or "")) end
local function finish() log(fails==0 and "RESULT: PASS" or ("RESULT: FAIL ("..fails..")"))
  local f=io.open(OUT,"w"); if f then f:write(table.concat(lines,"\n").."\n"); f:close() end; client.exit() end

pcall(function() client.speedmode(400) end)
pcall(savestate.load, "E:/Howard/Bizhawk/GBA/State/slink_overworld.State")
emu.frameadvance(); pcall(memory.usememorydomain,"System Bus")
if not MB.present() then log("FAIL: beacon absent"); finish(); return end

local px, py = p_tx(), p_ty()
MB.write_message("Hi from your partner!")
MB.ghost_set_pos((px + 1) * 16, py * 16, 3, 0, 0)   -- 1 tile EAST (world px); collision tile pinned there
MB.ghost_spawn(p_gfx())
local oe = 16
for _=1,150 do emu.frameadvance(); oe = MB.ghost_oe()
  if oe < 16 and oe_cx(oe) == px+1 and oe_cy(oe) == py then break end end
check("ghost spawned + walked to the front tile", oe < 16 and oe_cx(oe) == px+1 and oe_cy(oe) == py,
      string.format("oe=%d at (%d,%d) want (%d,%d)", oe, oe < 16 and oe_cx(oe) or -1, oe < 16 and oe_cy(oe) or -1, px+1, py))
if oe >= 16 then finish(); return end

local c0 = MB.peer_interact_count()
joypad.set({}); emu.frameadvance(); face_right()
joypad.set({A=true}); emu.frameadvance()         -- A newly pressed, facing the ghost
joypad.set({}); for _=1,20 do emu.frameadvance() end

check("peer-interact counter incremented", MB.peer_interact_count() > c0,
      string.format("%d -> %d", c0, MB.peer_interact_count()))
-- The patch must NOT open its own box (server drives the menu): sScriptContext2Enabled stays 0.
check("no local box auto-opened (server drives the menu)", memory.read_u8(0x03000F9C) == 0,
      "sScriptContext2Enabled=" .. memory.read_u8(0x03000F9C))
check("game still running (no softlock)", MB.present())

MB.ghost_clear()
finish()
