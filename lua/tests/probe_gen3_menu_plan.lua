-- Plan-driven Gen 3 main-menu probe: runs SLINK_PLAN (';'-separated steps) against the loaded game and writes screenshots,
-- memory reads and VRAM/palette dumps into SLINK_SHOT_DIR. Used to look at the real FireRed / LeafGreen / Radical Red /
-- Emerald main menu (vanilla and companion-patched) -- never per-frame logging.
--   w:N              advance N frames
--   p:Button:N       hold Button (Start, A, B, Up, Down..., or A+B+Start+Select) for N frames, then 6 frames released
--   s:name           screenshot <name>.png
--   r32:name:addr    log "name = 0x...." for a 32-bit read on the System Bus   (r16 / r8 likewise)
--   w16:addr:val     write 16 bits (also w8 / w32): used to force a flag the real save has not set
--   d:name           dump VRAM (0x18000), palette (0x400) and the I/O registers to <name>_{vram,pal}.bin / _io.txt
--   until:addr:val:N advance until the u32 at addr == val (at most N frames) and log whether it did
client.speedmode(tonumber(os.getenv("SLINK_SPEED") or "800"))
local dir = assert(os.getenv("SLINK_SHOT_DIR"))
local logf = assert(io.open(dir .. "/log.txt", "a"))
local function log(s) logf:write(s, "\n"); logf:flush() end
local function rd(width, addr)
    if width == 8 then return memory.read_u8(addr, "System Bus") end
    if width == 16 then return memory.read_u16_le(addr, "System Bus") end
    return memory.read_u32_le(addr, "System Bus")
end
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
local frame = 0
local function adv(n)
    for _ = 1, n do emu.frameadvance(); frame = frame + 1 end
end
for step in (os.getenv("SLINK_PLAN") or ""):gmatch("[^;]+") do
    local p = {}
    for tok in step:gmatch("[^:]+") do p[#p + 1] = tok end
    local op = p[1]
    if op == "w" then adv(tonumber(p[2]))
    elseif op == "p" then
        local b = {}
        for name in p[2]:gmatch("[^+]+") do b[name] = true end     -- Button or A+B+Start+Select
        for _ = 1, tonumber(p[3]) do joypad.set(b); emu.frameadvance(); frame = frame + 1 end
        adv(6)
    elseif op == "s" then client.screenshot(dir .. "/" .. p[2] .. ".png")
    elseif op == "r32" or op == "r16" or op == "r8" then
        local width = tonumber(op:sub(2))
        log(string.format("f%d %s = 0x%X", frame, p[2], rd(width, tonumber(p[3]))))
    elseif op == "w32" or op == "w16" or op == "w8" then
        local width, addr, val = tonumber(op:sub(2)), tonumber(p[2]), tonumber(p[3])
        if width == 8 then memory.write_u8(addr, val, "System Bus")
        elseif width == 16 then memory.write_u16_le(addr, val, "System Bus")
        else memory.write_u32_le(addr, val, "System Bus") end
    elseif op == "flag" then
        -- flag:<ptrAddr>:<flagsOffset>:<flagId> sets a save-block flag: *(ptr) + flagsOffset + (id >> 3), bit (id & 7)
        local base = memory.read_u32_le(tonumber(p[2]), "System Bus")
        local id = tonumber(p[4])
        local addr = base + tonumber(p[3]) + (id >> 3)
        memory.write_u8(addr, memory.read_u8(addr, "System Bus") | (1 << (id & 7)), "System Bus")
        log(string.format("f%d flag %d set at 0x%X (sb=0x%X)", frame, id, addr, base))
    elseif op == "d" then
        local regs = {}
        for off = 0, 0x58, 2 do regs[#regs + 1] = string.format("%04X", memory.read_u16_le(0x04000000 + off, "System Bus")) end
        local fh = assert(io.open(dir .. "/" .. p[2] .. "_io.txt", "w")); fh:write(table.concat(regs, " "), "\n"); fh:close()
        dump(p[2] .. "_vram.bin", "VRAM", 0x18000)
        dump(p[2] .. "_pal.bin", "PALRAM", 0x400)
    elseif op == "until" then
        local addr, val, n = tonumber(p[2]), tonumber(p[3]), tonumber(p[4])
        local hit = false
        for _ = 1, n do
            if rd(32, addr) == val then hit = true; break end
            emu.frameadvance(); frame = frame + 1
        end
        log(string.format("f%d until 0x%X==0x%X %s", frame, addr, val, hit and "HIT" or "MISS"))
    end
end
log("DONE f" .. frame)
logf:close()
client.exit()
