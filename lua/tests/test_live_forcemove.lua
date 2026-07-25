-- test_live_forcemove.lua — LIVE validation of FORCE_MOVE_SLOT (controller-swap driver).
-- Arms a forced move on the lead's SLOT 1 (Growl) and confirms it actually executes
-- (slot-1 PP drops) — the correct slot, not the default slot 0, and not a Z-move.
-- Battle save + PATCHED ROM.
--
-- How it works: when armed, the in-ROM hook swaps the player's menu controller pointer to
-- our own routine, which sets the chosen-move state and jumps to CONFIRMED, so the engine
-- executes the forced move. The test nudges the (savestate-frozen) battle to the action
-- menu with clear_exec, then lets the patch drive.

local WT = SLINK_ROOT or os.getenv("SLINK_ROOT") or debug.getinfo(1, "S").source:match([=[^@(.*)[/\]lua[/\]tests[/\]]=])
assert(WT, "repo root unknown — launch via: python tools/run_gate.py <this script>")
local OUT = WT .. "/patch/build/forcemove_result.txt"
local STATE = "E:/Howard/Bizhawk/GBA/State/slink_battle.State"
local MB = dofile(WT .. "/lua/mailbox.lua")

local gBM, gComm, gExec = 0x02023BE4, 0x02023E82, 0x02023BC8
local function pp(b,i) return memory.read_u8(gBM + b*0x58 + 0x24 + i) end
local function comm(b) return memory.read_u8(gComm + b) end
local function clear_exec(b)
    local m=(1<<b)|(1<<(b+4))|(1<<(b+8))|(1<<(b+12))|0xF0000000
    memory.write_u32_le(gExec, memory.read_u32_le(gExec)&(~m&0xFFFFFFFF))
end

local lines={}; local function log(s) lines[#lines+1]=s; console.log(s) end
local function finish(ok) log(ok and "RESULT: PASS" or "RESULT: FAIL")
  local f=io.open(OUT,"w"); if f then f:write(table.concat(lines,"\n").."\n"); f:close() end; client.exit() end

pcall(function() client.speedmode(400) end)
pcall(savestate.load, STATE); emu.frameadvance(); pcall(memory.usememorydomain,"System Bus")
if not MB.present() then log("FAIL: beacon absent"); finish(); return end

local B, POS, TARGET = 0, 1, 1     -- force slot 1 (Growl): NOT default slot 0, NOT a Z-move
local pp0 = {[0]=pp(B,0),[1]=pp(B,1),[2]=pp(B,2),[3]=pp(B,3)}
log(string.format("pp_before=%d/%d/%d/%d  forcing slot %d", pp0[0],pp0[1],pp0[2],pp0[3], POS))

MB.send(MB.OP_FORCE_MOVE_SLOT, MB.force_move_slot_args(B, TARGET, POS))   -- arm once

local fired = nil
for f = 1, 600 do
    local c = comm(B)
    if c < 2 or c >= 4 then clear_exec(B) end   -- nudge to the menu / push turn execution
    emu.frameadvance()
    for i=0,3 do if pp(B,i) < pp0[i] then fired = i; break end end
    if fired then break end
end
log(string.format("pp_after=%d/%d/%d/%d  fired_slot=%s (forced %d)",
    pp(B,0),pp(B,1),pp(B,2),pp(B,3), tostring(fired), POS))
finish(fired == POS)
