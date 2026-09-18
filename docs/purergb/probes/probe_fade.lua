-- GBC FADE bank-2 stress: loop the house stairs (warp = fade out + fade in) with GBC FADE forced on.
local OUT = os.getenv("SLINK_PROBE_OUT") or "probe_fade_out.txt"
local MAX = tonumber(os.getenv("SLINK_PROBE_FRAMES") or "24000")
local f = assert(io.open(OUT, "w"))
local function log(s) f:write(s .. "\n"); f:flush() end
local bus = "System Bus"
local function u8(a) return memory.read_u8(a, bus) end
local S = { wCurMap=0xD366, wXCoord=0xD36A, wYCoord=0xD369, wOptions2=0xDA45, wIsInBattle=0xD057, wJoyIgnore=0xCD6B, wFontLoaded=0xCFC4 }
local vb, vb2, rw_calls, rw_bank2, halted_bank2, warps = 0, 0, 0, 0, 0, 0
local walk, fade_set, last_map = false, false, nil
event.on_bus_exec(function()
    vb = vb + 1
    local wb = emu.getregister("WRAM BANK")
    if wb == 2 then
        vb2 = vb2 + 1
        local sp = emu.getregister("SP")
        log(string.format("VBLANK_BANK2 frame=%d [SP]=%04X [SP+2]=%04X romx=%02X", emu.framecount(), memory.read_u16_le(sp, bus), memory.read_u16_le(sp + 2, bus), emu.getregister("ROMX BANK")))
    end
end, 0x0040, "fade_vblank")
event.on_bus_exec(function() rw_calls = rw_calls + 1 end, 0x7616, "fade_rw")           -- BufferAllPokeyellowColorsGBC.readwriteinc (bank 1C)
event.on_bus_exec(function() walk = true end, 0x03D6, "fade_ow")
-- count VBlanks that land while the readwriteinc loop has bank 2 selected: sample rWBK at the halt too
event.on_bus_exec(function() if emu.getregister("WRAM BANK") == 2 then halted_bank2 = halted_bank2 + 1 end end, 0x1E8D, "fade_halt")
client.speedmode(800)
local frame = 0
event.onframeend(function()
    frame = frame + 1
    local b = {A=false,B=false,Start=false,Select=false,Up=false,Down=false,Left=false,Right=false}
    local map = u8(S.wCurMap)
    if not walk then
        b.A = frame % 8 < 2; b.Start = frame % 40 < 2
    else
        if not fade_set and emu.getregister("WRAM BANK") == 1 then
            memory.write_u8(S.wOptions2, u8(S.wOptions2) | 0x20, bus); fade_set = true
            log(string.format("fade_set frame=%d wOptions2=%02X", frame, u8(S.wOptions2)))
        end
        if last_map ~= nil and map ~= last_map then warps = warps + 1 end
        last_map = map
        local x, y = u8(S.wXCoord), u8(S.wYCoord)
        if map == 0x26 or map == 0x25 then
            local t = (y == 1) and {7, 2} or {7, 1}
            if map == 0x26 and y > 2 then t = {4, 1} end
            if map == 0x26 and y > 2 and x ~= 4 then t = {4, y} end
            if frame % 4 < 3 then
                if x < t[1] then b.Right = true elseif x > t[1] then b.Left = true
                elseif y < t[2] then b.Down = true elseif y > t[2] then b.Up = true end
            end
        end
        if frame % 200 == 0 then b.B = true end
    end
    joypad.set(b)
    if frame % 2000 == 0 then log(string.format("frame=%d map=%02X warps=%d vblanks=%d vblank_bank2=%d readwriteinc_calls=%d halt_bank2=%d", frame, map, warps, vb, vb2, rw_calls, halted_bank2)) end
    if frame >= MAX then
        log(string.format("FINAL frames=%d warps=%d vblanks=%d vblank_bank2=%d readwriteinc_calls=%d halt_bank2=%d fade_set=%s", frame, warps, vb, vb2, rw_calls, halted_bank2, tostring(fade_set)))
        log("RESULT: DONE"); f:close(); client.exit()
    end
end)
