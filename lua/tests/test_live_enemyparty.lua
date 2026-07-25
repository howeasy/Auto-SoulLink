-- test_live_enemyparty.lua — LIVE Phase-2: CREATE_MON into the ENEMY party (the
-- Rival-Team-Swap fix). Creates a bulky and a frail species into empty gEnemyParty slots
-- on the in-battle save and confirms each is species-accurate. Load with the PATCHED ROM.

local WT = SLINK_ROOT or os.getenv("SLINK_ROOT") or debug.getinfo(1, "S").source:match([=[^@(.*)[/\]lua[/\]tests[/\]]=])
assert(WT, "repo root unknown — launch via: python tools/run_gate.py <this script>")
local OUT = WT .. "/patch/build/enemyparty_result.txt"
local STATE = "E:/Howard/Bizhawk/GBA/State/slink_battle.State"
local MB = dofile(WT .. "/lua/mailbox.lua")

local gEnemyParty, MON = 0x0202402C, 100
local function pid(s)   return memory.read_u32_le(gEnemyParty + s*MON + 0x00) end
local function level(s) return memory.read_u8 (gEnemyParty + s*MON + 0x54) end
local function maxhp(s) return memory.read_u16_le(gEnemyParty + s*MON + 0x58) end

local lines={}; local fails=0
local function log(s) lines[#lines+1]=s; console.log(s) end
local function check(n,c,e) if not c then fails=fails+1 end; log(string.format("  [%s] %s%s",c and "PASS" or "FAIL",n,e and "  "..e or "")) end
local function finish() log(fails==0 and "RESULT: PASS" or ("RESULT: FAIL ("..fails..")"))
  local f=io.open(OUT,"w"); if f then f:write(table.concat(lines,"\n").."\n"); f:close() end; client.exit() end

pcall(function() client.speedmode(400) end)
pcall(savestate.load, STATE); emu.frameadvance(); pcall(memory.usememorydomain,"System Bus")
if not MB.present() then log("FAIL: beacon absent"); finish(); return end
log("beacon up; enemy slot0 (active) maxhp="..maxhp(0))

local gEnemyCount = 0x0202402A
local LV = 40
local MONS = { {slot=1, name="Snorlax", id=143}, {slot=2, name="Diglett", id=50} }
for _, m in ipairs(MONS) do
    -- party=1 (enemy), bump=1 (set gEnemyPartyCount) — the full Rival-Team-Swap build
    local st = MB.send(MB.OP_CREATE_MON, MB.create_mon_args(m.slot, m.id, LV, 1, 1))
    local ok=false; for _=1,30 do emu.frameadvance(); if MB.poll(st) then ok=true; break end end
    m.lv, m.pid, m.hp = level(m.slot), pid(m.slot), maxhp(m.slot)
    log(string.format("  enemy %s (id=%d) -> acked=%s lv=%d pid=0x%08X maxhp=%d", m.name, m.id, tostring(ok), m.lv, m.pid, m.hp))
    check(m.name.." level==40", m.lv == LV)
    check(m.name.." pid!=0", m.pid ~= 0)
    check(m.name.." maxhp>0", m.hp > 0)
end
check("Snorlax maxhp > Diglett maxhp (species-specific base stats, enemy side)",
      MONS[1].hp > MONS[2].hp, string.format("snorlax=%d diglett=%d", MONS[1].hp, MONS[2].hp))
check("gEnemyPartyCount bumped to 3", memory.read_u8(gEnemyCount) == 3,
      "count=" .. memory.read_u8(gEnemyCount))
finish()
