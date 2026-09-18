local OUT = os.getenv("SLINK_PROBE_OUT") or "probe_battle_out.txt"
local MAX = tonumber(os.getenv("SLINK_PROBE_FRAMES") or "30000")
local f = assert(io.open(OUT, "w"))
local function log(s) f:write(s .. "\n"); f:flush() end
local bus = "System Bus"
local function u8(a) return memory.read_u8(a, bus) end
local S = { wCurMap=0xD366, wXCoord=0xD36A, wYCoord=0xD369, wIsInBattle=0xD057, wBattleType=0xD05A,
            wCurOpponent=0xD059, wEnemyMonSpecies2=0xD000, wCurEnemyLevel=0xD127, wPlayerMonNumber=0xCC2F, wPartyCount=0xD16B, hLoadedROMBank=0xFFB8 }
local WILD_BEGIN, LOOP_HEAD = 0x6F4A, 0x4253  -- InitWildBattle+$13, MainInBattleLoop+6 (bank $0F)
local hits = {}
local function hook(name, addr)
    event.on_bus_exec(function()
        local pc, rb = emu.getregister("PC"), emu.getregister("ROMX BANK")
        local bytes = {}
        for i = 0, 5 do bytes[#bytes+1] = string.format("%02X", u8(addr + i)) end
        log(string.format("%s pc=%04X romx=%02X hLoaded=%02X frame=%d bytes=%s inb=%d type=%d opp=%02X species2=%02X level=%d monnum=%d map=%02X",
            name, pc, rb, u8(S.hLoadedROMBank), emu.framecount(), table.concat(bytes, " "), u8(S.wIsInBattle), u8(S.wBattleType),
            u8(S.wCurOpponent), u8(S.wEnemyMonSpecies2), u8(S.wCurEnemyLevel), u8(S.wPlayerMonNumber), u8(S.wCurMap)))
        hits[name] = (hits[name] or 0) + 1
    end, addr, "probe_" .. name)
end
hook("wild_begin", WILD_BEGIN); hook("loop_head", LOOP_HEAD)
local frame, walk, seen_battle = 0, false, 0
local last_map = nil
client.speedmode(800)
event.on_bus_exec(function() walk = true end, 0x03D6, "probe_ow")
local ROUTES = { [0x26] = {{4,6},{4,1},{7,1}}, [0x25] = {{7,2},{2,2},{2,8}}, [0x00] = {{5,7},{9,7},{9,2},{10,2},{10,-1}}, [0x0C] = {{10,33},{10,35}}, [0x28] = {{5,4},{8,4}} }
local wp = 1
event.onframeend(function()
    frame = frame + 1
    local b = {A=false,B=false,Start=false,Select=false,Up=false,Down=false,Left=false,Right=false}
    local map = u8(S.wCurMap)
    if map ~= last_map then wp = 1; log("map " .. string.format("%02X", map) .. " frame " .. frame); last_map = map end
    if u8(S.wIsInBattle) ~= 0 then
        seen_battle = seen_battle + 1
        if seen_battle > 600 then log("battle observed; exiting"); log("RESULT: DONE"); f:close(); client.exit() end
        b.B = frame % 8 < 2  -- do not advance the battle; just let hooks fire
    elseif not walk then
        b.A = frame % 8 < 2; b.Start = frame % 40 < 2
    elseif map == 0x28 and u8(S.wPartyCount) > 0 then
        b.B = frame % 16 < 2  -- RC idiom: B declines the nickname and advances text until the rival battle
    else
        local r = ROUTES[map]
        if r then
            local x, y, t = u8(S.wXCoord), u8(S.wYCoord), r[wp]
            if map == 0x0C then wp = (frame % 120 < 60) and 1 or 2; t = r[wp] end
            if t and x == t[1] and (y == t[2]) and map ~= 0x0C then wp = math.min(wp + 1, #r); t = r[wp] end
            if map == 0x28 and frame % 16 < 2 then b.A = true end -- advance Oak's dialogue while walking (RC idiom)
            if t and frame % 4 < 3 then
                if x < t[1] then b.Right = true elseif x > t[1] then b.Left = true
                elseif y < t[2] then b.Down = true elseif y > t[2] then b.Up = true end
            end
            if map == 0x28 and wp == #r and x == t[1] and y == t[2] then
                -- in the lab at the starter ball: face up, then mash A through the pick + rival
                b.Up = true; if frame % 16 < 2 then b.A = true end  -- RC: press A with Up held at (8,4)
            end
        end
        if frame % 200 == 0 then b.B = true end
    end
    joypad.set(b)
    if frame % 1200 == 0 then log(string.format("frame %d map %02X pos %d,%d walk=%s", frame, map, u8(S.wXCoord), u8(S.wYCoord), tostring(walk))) end
    if frame >= MAX then log("RESULT: DONE (no battle)"); f:close(); client.exit() end
end)
