-- probe_uibudget.lua — RESEARCH probe (not a gate): what UI resources are actually free while the
-- SOULLINK info window is open on the field?
--
-- Answers, live, the questions a static disassembly cannot:
--   * which of the 16 BG palette slots are unused (candidates for an icon / HP-bar palette)
--   * which of the 16 OBJ palette slots are unused, per the engine's own sSpritePaletteTags
--   * how many gSprites slots and how many of the 1024 OBJ VRAM tiles are free
--   * and whether opening the window changes any of it.
--
--   python tools/run_gate.py lua/tests/probe_uibudget.lua --timeout 300
local SDIR = "E:/Howard/Bizhawk/GBA/State"
local WT = SLINK_ROOT or os.getenv("SLINK_ROOT") or debug.getinfo(1, "S").source:match([=[^@(.*)[/\]lua[/\]tests[/\]]=])
assert(WT, "repo root unknown — launch via: python tools/run_gate.py <this script>")
local OUT = WT .. "/patch/build/uibudget_result.txt"
local MB = dofile(WT .. "/lua/mailbox.lua")

local lines = {}
local function log(s) lines[#lines + 1] = s; console.log(s) end
local function finish(ok)
    log(ok and "RESULT: PASS" or "RESULT: FAIL")
    local f = io.open(OUT, "w")
    if f then f:write(table.concat(lines, "\n") .. "\n"); f:close() end
    client.exit()
end

pcall(memory.usememorydomain, "System Bus")
pcall(function() client.speedmode(400) end)

local PAL_BG   = 0x05000000
local PAL_OBJ  = 0x05000200
local SPR_TAGS = 0x03000DE8   -- sSpritePaletteTags, u16[16]
local TILE_BM  = 0x02021B48   -- sSpriteTileAllocBitmap, 128 B = 1024 OBJ tiles
local GSPRITES = 0x0202063C
local SPR_STR  = 0x44

local function pal_row(base, slot)
    local t = {}
    for i = 0, 15 do t[#t + 1] = string.format("%04X", memory.read_u16_le(base + slot * 32 + i * 2)) end
    return table.concat(t, " ")
end
local function pal_allzero(base, slot)
    for i = 0, 15 do if memory.read_u16_le(base + slot * 32 + i * 2) ~= 0 then return false end end
    return true
end
local function tags()
    local t = {}
    for i = 0, 15 do t[#t + 1] = string.format("%04X", memory.read_u16_le(SPR_TAGS + i * 2)) end
    return table.concat(t, " ")
end
local function free_tag_slots()
    local n = 0
    for i = 0, 15 do if memory.read_u16_le(SPR_TAGS + i * 2) == 0xFFFF then n = n + 1 end end
    return n
end
local function free_tiles()
    local used = 0
    for b = 0, 127 do
        local v = memory.read_u8(TILE_BM + b)
        for k = 0, 7 do if (v >> k) % 2 == 1 then used = used + 1 end end
    end
    return 1024 - used, used
end
local function free_sprites()
    local n = 0
    for i = 0, 63 do
        if memory.read_u8(GSPRITES + i * SPR_STR + 0x3E) % 2 == 0 then n = n + 1 end
    end
    return n
end

local function snapshot(label)
    log("---- " .. label .. " ----")
    local bgfree, objfree = {}, {}
    for s = 0, 15 do
        local z = pal_allzero(PAL_BG, s)
        if z then bgfree[#bgfree + 1] = s end
        log(string.format("  BG  pal %2d %s %s", s, z and "ZERO" or "used", pal_row(PAL_BG, s)))
    end
    for s = 0, 15 do
        local z = pal_allzero(PAL_OBJ, s)
        if z then objfree[#objfree + 1] = s end
        log(string.format("  OBJ pal %2d %s %s", s, z and "ZERO" or "used", pal_row(PAL_OBJ, s)))
    end
    local ft, ut = free_tiles()
    log("  sSpritePaletteTags: " .. tags())
    log(string.format("  free OBJ pal slots (tag==FFFF): %d", free_tag_slots()))
    log(string.format("  OBJ VRAM tiles: %d used, %d free (of 1024)", ut, ft))
    log(string.format("  free gSprites slots: %d / 64", free_sprites()))
    log("  BG pal slots all-zero: " .. table.concat(bgfree, ","))
    log("  OBJ pal slots all-zero: " .. table.concat(objfree, ","))
end

assert(pcall(savestate.load, SDIR .. "/slink_overworld.State"), "no overworld savestate")
emu.frameadvance()
for _ = 1, 240 do emu.frameadvance(); if MB.present() then break end end
if not MB.present() then log("FAIL: no SLNK beacon"); finish(false); return end
memory.write_u8(MB.INFO_LINES, 0)
for _ = 1, 30 do emu.frameadvance() end

snapshot("FIELD, no window")

MB.write_info({ "SOUL LINK", "Bulbasaur  L12  19/23", "Squirtle   L11  RIP", "Page 1/2" }, 1, 2)
local seq = MB.show_info(1)
for _ = 1, 150 do emu.frameadvance() end
snapshot("FIELD, SOULLINK window OPEN")

-- and with a plain field message box up, for comparison (the other window path)
for f = 1, 60 do joypad.set(f <= 3 and { A = true } or {}); emu.frameadvance() end
for _ = 1, 120 do emu.frameadvance() end
snapshot("FIELD, window closed again")
log("seq=" .. tostring(seq))
finish(true)
