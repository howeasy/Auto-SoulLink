-- APEX write-window live proof: boot + lab route (RC driver), inject an APEX CHIP, use it on slot 1,
-- restore the old DVs at ItemUseMedicine.useApexChip+$11 and check they survive .recalculateStats.
local ROOT = os.getenv("SLINK_RC_ROOT")
local OUT = os.getenv("SLINK_PROBE_OUT") or (ROOT .. "/rc_apex_out.txt")
local f = assert(io.open(OUT, "w"))
local function log(s) f:write(tostring(s) .. "\n"); f:flush() end
local bus = "System Bus"
local function u8(a) return memory.read_u8(a, bus) end
local S = { wCurMap=0xD366, wIsInBattle=0xD057, wJoyIgnore=0xCD6B, wFontLoaded=0xCFC4, wNumBagItems=0xD542, wBagItems=0xD543,
            wPartyCount=0xD16B, wPartyMon1=0xD173, DVs=0xD18E, Stats=0xD195, HP=0xD174, wUsedItemOnWhichPokemon=0xCF06, wCurrentMenuItem=0xCC26 }
local RESTORE = true
local old_dv1, old_dv2, pre_hits, commit_hits, recalc_hits = nil, nil, 0, 0, 0
local function mon_dump(tag)
    local st = {}
    for i = 0, 9 do st[#st+1] = string.format("%02X", u8(S.Stats + i)) end
    log(string.format("%s DVs=%02X%02X HP=%02X%02X stats=%s bag=%d item0=%02X x%d", tag, u8(S.DVs), u8(S.DVs+1), u8(S.HP), u8(S.HP+1), table.concat(st, " "), u8(S.wNumBagItems), u8(S.wBagItems), u8(S.wBagItems+1)))
end
event.on_bus_exec(function()
    if emu.getregister("ROMX BANK") ~= 3 then return end
    local hl = emu.getregister("H") * 256 + emu.getregister("L")
    old_dv1, old_dv2 = u8(hl), u8(hl + 1); pre_hits = pre_hits + 1
    log(string.format("PREFLIGHT .setDVs pc=%04X hl=%04X dv=%02X%02X target=%d frame=%d", emu.getregister("PC"), hl, old_dv1, old_dv2, u8(S.wUsedItemOnWhichPokemon), emu.framecount()))
end, 0x5B43, "apex_pre")
event.on_bus_exec(function()
    if emu.getregister("ROMX BANK") ~= 3 then return end
    local hl = emu.getregister("H") * 256 + emu.getregister("L")  -- points at DV byte 2 after the two stores
    commit_hits = commit_hits + 1
    log(string.format("COMMIT +11 pc=%04X hl=%04X written=%02X%02X frame=%d", emu.getregister("PC"), hl, u8(hl - 1), u8(hl), emu.framecount()))
    if RESTORE and old_dv1 then
        memory.write_u8(hl - 1, old_dv1, bus); memory.write_u8(hl, old_dv2, bus)
        log(string.format("RESTORED dv=%02X%02X (bus write inside the callback)", u8(hl - 1), u8(hl)))
    end
end, 0x5B45, "apex_commit")
event.on_bus_exec(function() if emu.getregister("ROMX BANK") == 3 then recalc_hits = recalc_hits + 1 end end, 0x5A4D, "apex_recalc")
client.speedmode(800)
local P = dofile(ROOT .. "/lua/tests/gen1_scripted_play.lua")
local function step(buttons) joypad.set(buttons); emu.frameadvance() end
local function overworld_ok()
    local sp = emu.getregister("SP")
    return emu.getregister("PC") == 0x0040 and memory.read_u16_le(sp, bus) == 0x1E8E and memory.read_u16_le(sp + 2, bus) == 0x03D7
        and u8(0xD12B) == 0 and u8(S.wCurMap) == 0x26 and u8(S.wIsInBattle) == 0 and u8(S.wJoyIgnore) == 0 and u8(S.wFontLoaded) % 2 == 0
end
local play = P.new(ROOT, "red", "a", { log = log })
assert(play.boot(step, overworld_ok))
local ok, err = pcall(function() return play.run(step, {"lab"}, function(name, phase, frame) end) end)
log("lab ok=" .. tostring(ok) .. " " .. tostring(err))
local IDLE = {A=false,B=false,Start=false,Select=false,Up=false,Down=false,Left=false,Right=false}
local function press(key, n)
    for i = 1, (n or 1) do
        local b = {A=false,B=false,Start=false,Select=false,Up=false,Down=false,Left=false,Right=false}; b[key] = true
        step(b); step(b); for _ = 1, 30 do step(IDLE) end
    end
end
for _ = 1, 120 do step(IDLE) end
mon_dump("BEFORE")
local saves = 0
event.on_bus_exec(function() if emu.getregister("ROMX BANK") == 0x1C then saves = saves + 1; log("SAVE_WITNESS SaveMenu.save+3 frame=" .. emu.framecount()) end end, 0x77D1, "save_w")
press("Start"); press("Down", 3); press("A")        -- START (no Pokédex): POKéMON, ITEM, PLAYER, SAVE -> SAVE
log("menu item=" .. u8(S.wCurrentMenuItem))
for i = 1, 6 do press("A"); for _ = 1, 60 do step(IDLE) end end  -- text scroll + YES
for _ = 1, 600 do step(IDLE) end
for _ = 1, 4 do press("B") end
for _ = 1, 60 do step(IDLE) end
log("saves=" .. saves)
pcall(function() client.saveram() end); log("saveram flushed")
mon_dump("FINAL")
log("RESULT: DONE"); f:close(); client.exit()
