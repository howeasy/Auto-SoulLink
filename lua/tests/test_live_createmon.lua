-- test_live_createmon.lua — LIVE Phase-2 validation: CREATE_MON calls the engine's
-- CreateMon natively. Creates two very different species at the same level in empty party
-- slots and confirms each has the requested level, a real PID, and species-specific maxHP
-- (Snorlax >> Bulbasaur) — proving correct per-species base stats (the "wrong base stats"
-- bug a pure-RAM clone would have). Load with the PATCHED ROM + overworld savestate.

local WT = SLINK_ROOT or os.getenv("SLINK_ROOT") or debug.getinfo(1, "S").source:match([=[^@(.*)[/\]lua[/\]tests[/\]]=])
assert(WT, "repo root unknown — launch via: python tools/run_gate.py <this script>")
local OUT = WT .. "/patch/build/createmon_result.txt"
local STATE = "E:/Howard/Bizhawk/GBA/State/slink_overworld.State"
local MB = dofile(WT .. "/lua/mailbox.lua")

local gPlayerParty, MON = 0x02024284, 100
local function pid(s)   return memory.read_u32_le(gPlayerParty + s*MON + 0x00) end
local function level(s) return memory.read_u8 (gPlayerParty + s*MON + 0x54) end
local function maxhp(s) return memory.read_u16_le(gPlayerParty + s*MON + 0x58) end

local lines = {}; local fails = 0
local function log(s) lines[#lines+1]=s; console.log(s) end
local function check(n,c,e) if not c then fails=fails+1 end; log(string.format("  [%s] %s%s", c and "PASS" or "FAIL", n, e and "  "..e or "")) end
local function finish() log(fails==0 and "RESULT: PASS" or ("RESULT: FAIL ("..fails..")"))
  local f=io.open(OUT,"w"); if f then f:write(table.concat(lines,"\n").."\n"); f:close() end; client.exit() end

pcall(function() client.speedmode(400) end)
pcall(savestate.load, STATE); emu.frameadvance(); pcall(memory.usememorydomain,"System Bus")
if not MB.present() then log("FAIL: beacon absent"); finish(); return end
log("beacon up; party count="..memory.read_u8(0x02024029))

local LV = 50
local SPECIES = { {slot=4, name="Bulbasaur", id=1}, {slot=5, name="Snorlax", id=143} }
for _, s in ipairs(SPECIES) do
    log(string.format("slot %d before: pid=0x%08X lv=%d maxhp=%d", s.slot, pid(s.slot), level(s.slot), maxhp(s.slot)))
    local st = MB.send(MB.OP_CREATE_MON, MB.create_mon_args(s.slot, s.id, LV))
    local ok=false; for _=1,30 do emu.frameadvance(); if MB.poll(st) then ok=true; break end end
    s.pid, s.lv, s.hp = pid(s.slot), level(s.slot), maxhp(s.slot)
    log(string.format("  %s (id=%d) -> acked=%s lv=%d pid=0x%08X maxhp=%d", s.name, s.id, tostring(ok), s.lv, s.pid, s.hp))
    check(s.name.." level==50", s.lv == LV)
    check(s.name.." pid!=0", s.pid ~= 0)
    check(s.name.." maxhp>0", s.hp > 0)
end
-- species-specific base stats: Snorlax (bulky) must out-HP Bulbasaur at the same level
check("Snorlax maxhp > Bulbasaur maxhp (per-species base stats)",
      SPECIES[2].hp > SPECIES[1].hp,
      string.format("snorlax=%d bulba=%d", SPECIES[2].hp, SPECIES[1].hp))
finish()
