-- probe_uibudget3.lua — RESEARCH probe: which palette BANKS are actually REFERENCED on screen?
--
-- "the palette slot is non-zero" only proves something was loaded there once. What decides whether a
-- slot is safe to borrow is whether any visible tile or sprite INDEXES it. So: read every BG's
-- tilemap (palette bank = bits 12-15 of each entry) and all 128 OAM entries (attr2 bits 12-15), and
-- histogram the banks actually in use — with and without the SOULLINK window open.
--   python tools/run_gate.py lua/tests/probe_uibudget3.lua --timeout 240
local SDIR = "E:/Howard/Bizhawk/GBA/State"
local WT = SLINK_ROOT or os.getenv("SLINK_ROOT") or debug.getinfo(1, "S").source:match([=[^@(.*)[/\]lua[/\]tests[/\]]=])
assert(WT, "repo root unknown — launch via: python tools/run_gate.py <this script>")
local OUT = WT .. "/patch/build/uibudget3_result.txt"
local MB = dofile(WT .. "/lua/mailbox.lua")

local lines = {}
local function log(s) lines[#lines + 1] = s; console.log(s) end
local function flush()
    local f = io.open(OUT, "w"); if f then f:write(table.concat(lines, "\n") .. "\n"); f:close() end
end
pcall(memory.usememorydomain, "System Bus")
pcall(function() client.speedmode(400) end)

local function bg_banks()
    local dispcnt = memory.read_u16_le(0x04000000)
    local seen, info = {}, {}
    for bg = 0, 3 do
        local enabled = ((dispcnt >> (8 + bg)) % 2) == 1
        local cnt = memory.read_u16_le(0x04000008 + bg * 2)
        local sbb = (cnt >> 8) % 32          -- screen base block, 2 KB units
        local pal256 = ((cnt >> 7) % 2) == 1 -- 256-colour mode: banks meaningless
        info[#info + 1] = string.format("BG%d %s cnt=%04X sbb=%d %s", bg,
            enabled and "on " or "off", cnt, sbb, pal256 and "8bpp" or "4bpp")
        if enabled and not pal256 then
            local base = 0x06000000 + sbb * 0x800
            for i = 0, 0x3FF do
                local e = memory.read_u16_le(base + i * 2)
                seen[(e >> 12) % 16] = true
            end
        end
    end
    return seen, table.concat(info, " | ")
end

local function obj_banks()
    local seen = {}
    for i = 0, 127 do
        local a0 = memory.read_u16_le(0x07000000 + i * 8)
        local a2 = memory.read_u16_le(0x07000000 + i * 8 + 4)
        local disabled = (((a0 >> 8) % 4) == 2) and (((a0 >> 8) % 2) == 0)
        -- affine-off + double-size bit set == hidden; also skip the parked y=160 dummies
        local hidden = (((a0 >> 8) % 2) == 0) and (((a0 >> 9) % 2) == 1)
        local y = a0 % 256
        if not hidden and y ~= 160 then seen[(a2 >> 12) % 16] = true end
        local _ = disabled
    end
    return seen
end

local function fmt(seen)
    local t = {}
    for s = 0, 15 do t[#t + 1] = seen[s] and "X" or "." end
    return table.concat(t)
end

local function sample(label)
    local bg, info = bg_banks()
    local ob = obj_banks()
    log(string.format("%-34s BGbanks %s  OBJbanks %s", label, fmt(bg), fmt(ob)))
    log("      " .. info)
    flush()
end

for _, s in ipairs({ "slink_overworld", "slink_door", "slink_pokecenter", "slink_prebattle" }) do
    if pcall(savestate.load, SDIR .. "/" .. s .. ".State") then
        emu.frameadvance(); pcall(memory.usememorydomain, "System Bus")
        for _ = 1, 30 do emu.frameadvance() end
        sample(s)
    else
        log(s .. " (missing)"); flush()
    end
end

-- and with our own window open
if pcall(savestate.load, SDIR .. "/slink_overworld.State") then
    emu.frameadvance(); pcall(memory.usememorydomain, "System Bus")
    for _ = 1, 240 do emu.frameadvance(); if MB.present() then break end end
    if MB.present() then
        MB.write_info({ "SOUL LINK", "Bulbasaur  L12  19/23", "Squirtle   L11  RIP", "Page 1/2" }, 1, 2)
        MB.show_info(1)
        for _ = 1, 150 do emu.frameadvance() end
        sample("overworld + SOULLINK window open")
        pcall(function() client.screenshot(WT .. "/patch/build/uibudget3_window.png") end)
    else
        log("no SLNK beacon"); flush()
    end
end
log("RESULT: PASS")
flush()
client.exit()
