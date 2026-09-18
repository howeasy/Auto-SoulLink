local OUT = os.getenv("SLINK_PROBE_OUT") or "probe_wram_out.txt"
local MAX = tonumber(os.getenv("SLINK_PROBE_FRAMES") or "3600")
local f = assert(io.open(OUT, "w"))
local function log(s) f:write(s .. "\n"); f:flush() end
local bus = "System Bus"
local mism, same, bank0, bank1, bank2, wrote = 0, 0, 0, 0, 0, false
local frame = 0
client.speedmode(800)
event.onframeend(function()
    frame = frame + 1
    local wb = emu.getregister("WRAM BANK")
    if wb == 0 then bank0 = bank0 + 1 elseif wb == 1 then bank1 = bank1 + 1 else bank2 = bank2 + 1 end
    -- compare 64 bytes of bank-1 WRAM through both domains
    local ok = true
    for i = 0, 63 do
        local a = 0xD300 + i
        if memory.read_u8(a, bus) ~= memory.read_u8(0x1000 + (a - 0xD000), "WRAM") then ok = false end
    end
    if ok then same = same + 1 else mism = mism + 1 end
    -- WRAM0 through both domains
    if memory.read_u8(0xC100, bus) ~= memory.read_u8(0x0100, "WRAM") then mism = mism + 1000 end
    if frame == 600 and not wrote then
        -- write round trip through the flat WRAM domain into a proven-free tail byte ($DEFF, bank 1)
        local before = memory.read_u8(0xDEFF, bus)
        memory.write_u8(0x1000 + 0x0EFF, 0x5A, "WRAM")
        local viabus = memory.read_u8(0xDEFF, bus)
        memory.write_u8(0x1000 + 0x0EFF, before, "WRAM")
        log(string.format("write_roundtrip before=%02X viabus_after_write=%02X restored=%02X", before, viabus, memory.read_u8(0xDEFF, bus)))
        wrote = true
    end
    local b = {A = frame % 8 < 2, Start = frame % 40 < 2}
    joypad.set(b)
    if frame >= MAX then
        log(string.format("frames=%d same=%d mism=%d wrambank0=%d wrambank1=%d wrambank2=%d SVBK=%02X", frame, same, mism, bank0, bank1, bank2, memory.read_u8(0xFF70, bus)))
        log("RESULT: DONE"); f:close(); client.exit()
    end
end)
