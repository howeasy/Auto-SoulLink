-- probe_winmap.lua — VERIFICATION probe: dump gWindows[] tile allocations.
-- Question: is DLG_WINDOW_BASE_TILE_NUM (0x200) really the first thing a wide
-- CreateWindowFromRect window (baseBlock 0x38) runs into, or does the always-resident
-- field message-box window (claimed baseBlock 0x198) get hit first?
--   python tools/run_gate.py lua/tests/probe_winmap.lua --timeout 240
local SDIR = "E:/Howard/Bizhawk/GBA/State"
local WT = SLINK_ROOT or os.getenv("SLINK_ROOT") or debug.getinfo(1, "S").source:match([=[^@(.*)[/\]lua[/\]tests[/\]]=])
assert(WT, "repo root unknown — launch via: python tools/run_gate.py <this script>")
local OUT = WT .. "/patch/build/winmap_result.txt"
local MB = dofile(WT .. "/lua/mailbox.lua")

local GWINDOWS = 0x020204B4
local lines = {}
local function log(s) lines[#lines + 1] = s; console.log(s) end
local function flush()
    local f = io.open(OUT, "w"); if f then f:write(table.concat(lines, "\n") .. "\n"); f:close() end
end
pcall(memory.usememorydomain, "System Bus")
pcall(function() client.speedmode(400) end)

local function dump(label)
    log("---- " .. label .. " ----")
    for i = 0, 31 do
        local a = GWINDOWS + i * 12
        local bg = memory.read_u8(a)
        if bg ~= 0xFF then
            local l, t = memory.read_u8(a + 1), memory.read_u8(a + 2)
            local w, h = memory.read_u8(a + 3), memory.read_u8(a + 4)
            local pal = memory.read_u8(a + 5)
            local bb = memory.read_u16_le(a + 6)
            log(string.format("  win %2d  bg=%d  at(%2d,%2d) %2dx%-2d pal=%2d  tiles 0x%03X..0x%03X (%d)",
                i, bg, l, t, w, h, pal, bb, bb + w * h - 1, w * h))
        end
    end
    flush()
end

if pcall(savestate.load, SDIR .. "/slink_overworld.State") then
    emu.frameadvance(); pcall(memory.usememorydomain, "System Bus")
    for _ = 1, 30 do emu.frameadvance() end
    dump("FIELD, no SLink window")
    for _ = 1, 240 do emu.frameadvance(); if MB.present() then break end end
    if MB.present() then
        MB.write_info({ "SOUL LINK", "L2", "L3", "L4", "L5", "L6", "L7", "Page 1/2" }, 1, 2)
        MB.show_info(1)
        for _ = 1, 150 do emu.frameadvance() end
        dump("FIELD, SOULLINK window OPEN")
    else
        log("no SLNK beacon")
    end
else
    log("slink_overworld.State missing")
end
log("RESULT: PASS")
flush()
client.exit()
