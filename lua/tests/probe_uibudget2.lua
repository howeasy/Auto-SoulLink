-- probe_uibudget2.lua — RESEARCH probe: OBJ/BG palette + sprite/tile occupancy across SCENES.
-- One map is not a budget. Sample every field-ish savestate we own so "slot N is free" is a claim
-- about the game, not about one quiet route.
--   python tools/run_gate.py lua/tests/probe_uibudget2.lua --timeout 300
local SDIR = "E:/Howard/Bizhawk/GBA/State"
local WT = SLINK_ROOT or os.getenv("SLINK_ROOT") or debug.getinfo(1, "S").source:match([=[^@(.*)[/\]lua[/\]tests[/\]]=])
assert(WT, "repo root unknown — launch via: python tools/run_gate.py <this script>")
local OUT = WT .. "/patch/build/uibudget2_result.txt"

local lines = {}
local function log(s) lines[#lines + 1] = s; console.log(s) end
pcall(memory.usememorydomain, "System Bus")
pcall(function() client.speedmode(400) end)

local PAL_BG, PAL_OBJ = 0x05000000, 0x05000200
local SPR_TAGS, TILE_BM, GSPRITES = 0x03000DE8, 0x02021B48, 0x0202063C

local function nonzero(base, slot)
    for i = 0, 15 do if memory.read_u16_le(base + slot * 32 + i * 2) ~= 0 then return true end end
    return false
end
local function occ(base)
    local t = {}
    for s = 0, 15 do t[#t + 1] = nonzero(base, s) and "X" or "." end
    return table.concat(t)
end
local function tagstr()
    local t = {}
    for i = 0, 15 do
        local v = memory.read_u16_le(SPR_TAGS + i * 2)
        t[#t + 1] = (v == 0xFFFF) and "." or string.format("%04X", v)
    end
    return table.concat(t, " ")
end
local function tiles()
    local used = 0
    for b = 0, 127 do
        local v = memory.read_u8(TILE_BM + b)
        for k = 0, 7 do if (v >> k) % 2 == 1 then used = used + 1 end end
    end
    return used
end
local function sprites()
    local n = 0
    for i = 0, 63 do if memory.read_u8(GSPRITES + i * 0x44 + 0x3E) % 2 == 1 then n = n + 1 end end
    return n
end

local function flush()
    local f = io.open(OUT, "w"); if f then f:write(table.concat(lines, "\n") .. "\n"); f:close() end
end

local STATES = { "slink_overworld", "slink_door", "slink_pokecenter", "slink_prebattle",
                 "slink_battle", "slink_actionmenu" }
log("scene              BGpal 0-15        OBJpal 0-15       objTiles sprites  spritePalTags")
flush()
for _, s in ipairs(STATES) do
    local ok = pcall(savestate.load, SDIR .. "/" .. s .. ".State")
    if ok then
        emu.frameadvance(); pcall(memory.usememorydomain, "System Bus")
        for _ = 1, 30 do emu.frameadvance() end
        log(string.format("%-18s %s  %s  %4d/1024 %2d/64  %s",
            s, occ(PAL_BG), occ(PAL_OBJ), tiles(), sprites(), tagstr()))
    else
        log(string.format("%-18s (missing)", s))
    end
    flush()
end
log("RESULT: PASS")
flush()
client.exit()
