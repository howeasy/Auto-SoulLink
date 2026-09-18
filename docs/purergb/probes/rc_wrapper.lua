-- Drive the RC scripted host (lab route) on the built PureRed with the pure .sym swapped in.
local ROOT = os.getenv("SLINK_RC_ROOT")
local OUT = os.getenv("SLINK_PROBE_OUT") or (ROOT .. "/rc_out.txt")
local f = assert(io.open(OUT, "w"))
local function log(s) f:write(tostring(s) .. "\n"); f:flush() end
local bus = "System Bus"
local function u8(a) return memory.read_u8(a, bus) end
local S = { wCurMap=0xD366, wIsInBattle=0xD057, wJoyIgnore=0xCD6B, wFontLoaded=0xCFC4, wBattleType=0xD05A,
            wCurOpponent=0xD059, wEnemyMonSpecies2=0xD000, wCurEnemyLevel=0xD12F, wPlayerMonNumber=0xCC2F, hLoadedROMBank=0xFFB8 }
local function hook(name, addr)
    event.on_bus_exec(function()
        local bytes = {}
        for i = 0, 5 do bytes[#bytes+1] = string.format("%02X", u8(addr + i)) end
        log(string.format("HOOK %s pc=%04X romx=%02X hLoaded=%02X frame=%d bytes=%s inb=%d type=%d opp=%02X species2=%02X level=%d monnum=%d map=%02X",
            name, emu.getregister("PC"), emu.getregister("ROMX BANK"), u8(S.hLoadedROMBank), emu.framecount(), table.concat(bytes, " "),
            u8(S.wIsInBattle), u8(S.wBattleType), u8(S.wCurOpponent), u8(S.wEnemyMonSpecies2), u8(S.wCurEnemyLevel), u8(S.wPlayerMonNumber), u8(S.wCurMap)))
    end, addr, "rc_" .. name)
end
hook("wild_begin_InitWildBattle+13", 0x6F4A); hook("loop_head_MainInBattleLoop+6", 0x4253)
hook("trainer_staging__InitBattleCommon+48", 0x6FBA)
hook("battle_faint_RemoveFaintedPlayerMon", 0x47CD); hook("EndOfBattle_3A", 0x44FD); hook("save_witness_SaveMenu.save+3", 0x77D1)
client.speedmode(800)
local P = dofile(ROOT .. "/lua/tests/gen1_scripted_play.lua")
local function step(buttons) joypad.set(buttons); emu.frameadvance() end
local function overworld_ok()
    -- pure checkpoint shape measured live: halted in DelayFrame from OverworldLoop
    local sp = emu.getregister("SP")
    return emu.getregister("PC") == 0x0040 and memory.read_u16_le(sp, bus) == 0x1E8E and memory.read_u16_le(sp + 2, bus) == 0x03D7
        and u8(0xD12B) == 0 and u8(S.wCurMap) == 0x26 and u8(S.wIsInBattle) == 0 and u8(S.wJoyIgnore) == 0 and u8(S.wFontLoaded) % 2 == 0
end
local play = P.new(ROOT, "red", "a", { log = log })
local bok, berr = pcall(function() return play.boot(step, overworld_ok) end)
log("boot ok=" .. tostring(bok) .. " " .. tostring(berr))
if bok then
    local rok, rerr = pcall(function()
        return play.run(step, {"lab", "save"}, function(name, phase, frame) log(string.format("phase %s: %s @%d", name, phase, frame)) end)
    end)
    log("lab ok=" .. tostring(rok) .. " " .. tostring(rerr))
    if not rok then log("POINT " .. (pcall(function() return require and "" end) and "" or "")) end
end
pcall(function() client.saveram() end); log("saveram flushed"); log("RESULT: DONE"); f:close(); client.exit()
