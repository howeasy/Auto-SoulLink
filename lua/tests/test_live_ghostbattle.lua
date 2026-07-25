-- test_live_ghostbattle.lua — the ghost must SUSPEND during battle (patch must not touch gSprites,
-- which the battle engine reuses -> the reported rival-battle corruption/crash). Load an in-battle
-- savestate, request a ghost, advance frames, and assert it does NOT spawn / drive while in battle.
local WT = SLINK_ROOT or os.getenv("SLINK_ROOT") or debug.getinfo(1, "S").source:match([=[^@(.*)[/\]lua[/\]tests[/\]]=])
assert(WT, "repo root unknown — launch via: python tools/run_gate.py <this script>")
local OUT = WT .. "/patch/build/ghostbattle_result.txt"
local MB = dofile(WT .. "/lua/mailbox.lua")
local GBATTLEMONS, GBATTLEOUTCOME = 0x02023BE4, 0x02023E8A
local lines={}; local fails=0
local function log(s) lines[#lines+1]=s; console.log(s) end
local function check(n,c,e) if not c then fails=fails+1 end; log(string.format("  [%s] %s%s",c and "PASS" or "FAIL",n,e and "  "..e or "")) end
local function finish() log(fails==0 and "RESULT: PASS" or ("RESULT: FAIL ("..fails..")"))
  local f=io.open(OUT,"w"); if f then f:write(table.concat(lines,"\n").."\n"); f:close() end; client.exit() end

pcall(function() client.speedmode(400) end)
pcall(savestate.load, "E:/Howard/Bizhawk/GBA/State/slink_battle.State")
emu.frameadvance(); pcall(memory.usememorydomain,"System Bus")
check("patch present", MB.present()); if not MB.present() then finish(); return end

local maxhp = memory.read_u16_le(GBATTLEMONS + 0x2C)
local outcome = memory.read_u8(GBATTLEOUTCOME)
log(string.format("battle state: gBattleMons[0].maxHP=%d gBattleOutcome=%d", maxhp, outcome))
check("savestate is in-battle (maxHP>0 && outcome==0)", maxhp > 0 and outcome == 0)

-- request a ghost + post a target; the patch must REFUSE to spawn/drive while in battle.
MB.ghost_set_pos(160, 160, 1, 0, 0, false)
MB.ghost_spawn(0)
local spawned = false
for _=1,120 do emu.frameadvance(); if MB.ghost_oe() < 16 then spawned = true; break end end
check("ghost did NOT spawn while in battle (suspended)", not spawned, "oeId=" .. MB.ghost_oe())
MB.ghost_clear()
finish()
