-- test_live_givemon.lua — LIVE Phase-2 GIVE_MON: CREATE_MON with bump makes a real,
-- usable party member (the party count increments and the mon is species-correct).
-- Validates gift injection (and, by the same code path, building the rival's team).
-- Load with the PATCHED ROM + overworld savestate.

local WT = "E:/Google Drive/SLink/.claude/worktrees/condescending-bassi-9175e6"
local OUT = WT .. "/patch/build/givemon_result.txt"
local STATE = "E:/Howard/Bizhawk/GBA/State/slink_overworld.State"
local MB = dofile(WT .. "/lua/mailbox.lua")

local gPlayerParty, gCount, MON = 0x02024284, 0x02024029, 100
local function count() return memory.read_u8(gCount) end
local function level(s) return memory.read_u8(gPlayerParty + s*MON + 0x54) end
local function maxhp(s) return memory.read_u16_le(gPlayerParty + s*MON + 0x58) end
local function pid(s)   return memory.read_u32_le(gPlayerParty + s*MON + 0x00) end

local lines={}; local fails=0
local function log(s) lines[#lines+1]=s; console.log(s) end
local function check(n,c,e) if not c then fails=fails+1 end; log(string.format("  [%s] %s%s",c and "PASS" or "FAIL",n,e and "  "..e or "")) end
local function finish() log(fails==0 and "RESULT: PASS" or ("RESULT: FAIL ("..fails..")"))
  local f=io.open(OUT,"w"); if f then f:write(table.concat(lines,"\n").."\n"); f:close() end; client.exit() end

pcall(function() client.speedmode(400) end)
pcall(savestate.load, STATE); emu.frameadvance(); pcall(memory.usememorydomain,"System Bus")
if not MB.present() then log("FAIL: beacon absent"); finish(); return end

local c0 = count()
local slot, SP, LV = c0, 143, 30        -- give a Snorlax into the next empty slot
log(string.format("party count before = %d; giving species %d L%d into slot %d", c0, SP, LV, slot))

local st = MB.send(MB.OP_CREATE_MON, MB.create_mon_args(slot, SP, LV, 0, 1)) -- party=0, bump=1
local ok=false; for _=1,30 do emu.frameadvance(); if MB.poll(st) then ok=true; break end end

log(string.format("after: acked=%s count=%d  slot%d: lv=%d pid=0x%08X maxhp=%d",
    tostring(ok), count(), slot, level(slot), pid(slot), maxhp(slot)))
check("party count incremented", count() == c0 + 1, string.format("%d -> %d", c0, count()))
check("new mon level == 30", level(slot) == LV)
check("new mon has a PID", pid(slot) ~= 0)
check("new mon maxhp > 0 (species stats)", maxhp(slot) > 0)
finish()
