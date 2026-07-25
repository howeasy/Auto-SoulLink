-- test_live_ghostwarp.lua — the post-area-change cleanup. The old bug: after a map change the
-- spawned ghost wasn't cleaned up, its slot got reused by a real NPC, and "a different trainer with
-- collision" appeared. The patch's drive_ghost now owns map-change detection and RemoveEventObject's
-- the ghost cleanly. Assert: (1) OP_GHOST_CLEAR fully removes the ghost; (2) a simulated map change
-- never leaves an ORPHAN object-event with our localId (0xF0). Load PATCHED ROM + overworld save.
local WT = SLINK_ROOT or os.getenv("SLINK_ROOT") or debug.getinfo(1, "S").source:match([=[^@(.*)[/\]lua[/\]tests[/\]]=])
assert(WT, "repo root unknown — launch via: python tools/run_gate.py <this script>")
local OUT = WT .. "/patch/build/ghostwarp_result.txt"
local MB = dofile(WT .. "/lua/mailbox.lua")
local OE, OST = 0x02036E38, 0x24
local function p_sx() return memory.read_s16_le(OE + 0x10) end
local function p_sy() return memory.read_s16_le(OE + 0x12) end
local function p_gfx() return memory.read_u8(OE + 0x05) end
local function oe_active(i) return (memory.read_u8(OE + i*OST) & 1) == 1 end
local function oe_localid(i) return memory.read_u8(OE + i*OST + 0x08) end
local function ghost_oe_count()
  local n = 0
  for i = 0, 15 do if oe_active(i) and oe_localid(i) == 0xF0 then n = n + 1 end end
  return n
end

local lines={}; local fails=0
local function log(s) lines[#lines+1]=s; console.log(s) end
local function check(n,c,e) if not c then fails=fails+1 end; log(string.format("  [%s] %s%s",c and "PASS" or "FAIL",n,e and "  "..e or "")) end
local function finish() log(fails==0 and "RESULT: PASS" or ("RESULT: FAIL ("..fails..")"))
  local f=io.open(OUT,"w"); if f then f:write(table.concat(lines,"\n").."\n"); f:close() end; client.exit() end
local function spawn()
  MB.ghost_set_pos(p_sx() * 16, p_sy() * 16, 1, 0, 0); MB.ghost_spawn(p_gfx())
  for _=1,120 do emu.frameadvance(); if MB.ghost_oe() < 16 then return MB.ghost_oe() end end
  return 16
end

pcall(function() client.speedmode(400) end)
pcall(savestate.load, "E:/Howard/Bizhawk/GBA/State/slink_overworld.State")
emu.frameadvance(); pcall(memory.usememorydomain,"System Bus")
check("patch present", MB.present()); if not MB.present() then finish(); return end

-- (1) clean removal via OP_GHOST_CLEAR (same RemoveEventObject path the warp uses)
local oe = spawn()
check("ghost spawned", oe < 16, "oe=" .. oe); if oe >= 16 then finish(); return end
check("exactly one ghost OE", ghost_oe_count() == 1)
MB.ghost_clear()
for _=1,6 do emu.frameadvance() end
check("ghost fully removed after clear (no localId-0xF0 OE)", ghost_oe_count() == 0)
check("old slot freed (not active+ours)", not (oe_active(oe) and oe_localid(oe) == 0xF0))

-- (2) simulated map change must not leave an orphan
oe = spawn()
check("re-spawned ghost", oe < 16); if oe >= 16 then finish(); return end
local real_mn = memory.read_u8(OE + 0x09)
memory.write_u8(OE + 0x09, (real_mn + 1) % 256)   -- pretend the player warped to another map
for _=1,6 do emu.frameadvance() end
check("no ORPHAN ghost after map change (<=1 localId-0xF0 OE)", ghost_oe_count() <= 1,
      "count=" .. ghost_oe_count())
memory.write_u8(OE + 0x09, real_mn)
for _=1,6 do emu.frameadvance() end
check("still <=1 ghost after map restore", ghost_oe_count() <= 1, "count=" .. ghost_oe_count())

MB.ghost_clear()
finish()
