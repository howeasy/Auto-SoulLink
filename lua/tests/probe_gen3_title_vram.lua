-- Dump the settled Gen 3 title screen: DISPCNT/BGnCNT/scroll, VRAM, palette RAM and OAM, raw, so the layout can be
-- analysed offline (tools/analyze_gen3_title.py). SLINK_PROBE_FRAMES = comma list of frames to dump at; SLINK_SHOT_DIR = out.
client.speedmode(tonumber(os.getenv("SLINK_SPEED") or "800"))
local dir = assert(os.getenv("SLINK_SHOT_DIR"))
local frames = {}
for f in (os.getenv("SLINK_PROBE_FRAMES") or "2400"):gmatch("%d+") do frames[#frames + 1] = tonumber(f) end
local function dump(name, domain, n)
    local fh = assert(io.open(dir .. "/" .. name, "wb"))
    local parts = {}
    for a = 0, n - 4, 4 do
        local w = memory.read_u32_le(a, domain)
        parts[#parts + 1] = string.char(w & 0xFF, (w >> 8) & 0xFF, (w >> 16) & 0xFF, (w >> 24) & 0xFF)
        if #parts == 4096 then fh:write(table.concat(parts)); parts = {} end
    end
    fh:write(table.concat(parts)); fh:close()
end
local function io16(off) return memory.read_u16_le(0x04000000 + off, "System Bus") end
local last = frames[#frames]
local idx = 1
for f = 1, last do
    emu.frameadvance()
    if f == frames[idx] then
        local tag = string.format("f%05d_", f)
        local regs = {}
        for off = 0, 0x58, 2 do regs[#regs + 1] = string.format("%04X", io16(off)) end
        local fh = assert(io.open(dir .. "/" .. tag .. "io.txt", "w")); fh:write(table.concat(regs, " "), "\n"); fh:close()
        dump(tag .. "vram.bin", "VRAM", 0x18000)
        dump(tag .. "pal.bin", "PALRAM", 0x400)
        dump(tag .. "oam.bin", "OAM", 0x400)
        client.screenshot(dir .. "/" .. tag .. "shot.png")
        idx = idx + 1
    end
end
client.exit()
