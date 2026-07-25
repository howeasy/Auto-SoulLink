-- probe_palettes.lua — which BG palette slot does the in-battle text color id index, and how does it
-- differ between the ACTION-menu phase (colors render dark) and turn RESOLUTION (colors render right)?
-- Dumps all 16 BG palette slots (16 u16 colours each) at both phases and logs the slots that differ.
local SDIR = "E:/Howard/Bizhawk/GBA/State"
local WT = SLINK_ROOT or os.getenv("SLINK_ROOT") or debug.getinfo(1, "S").source:match([=[^@(.*)[/\]lua[/\]tests[/\]]=])
assert(WT, "repo root unknown — launch via: python tools/run_gate.py <this script>")
local OUT  = WT .. "/patch/build/palettes_result.txt"
local lines = {}; local function log(s) lines[#lines+1]=s; console.log(s) end

local function dump_bg()
    local pal = {}
    for slot = 0, 15 do
        local row = {}
        for i = 0, 15 do row[i] = memory.read_u16_le(0x05000000 + slot*32 + i*2) end
        pal[slot] = row
    end
    return pal
end
local function fmt_row(row)
    local t = {}
    for i = 0, 15 do t[#t+1] = string.format("%04X", row[i]) end
    return table.concat(t, " ")
end

pcall(function() client.speedmode(400) end)

-- phase A: action menu
pcall(savestate.load, SDIR .. "/slink_actionmenu.State"); emu.frameadvance(); pcall(memory.usememorydomain, "System Bus")
for _ = 1, 4 do emu.frameadvance() end
local A = dump_bg()

-- phase B: resolution
pcall(savestate.load, SDIR .. "/slink_movemenu.State"); emu.frameadvance(); pcall(memory.usememorydomain, "System Bus")
joypad.set({ A = true }); emu.frameadvance()
for _ = 1, 22 do emu.frameadvance() end
local B = dump_bg()

for slot = 0, 15 do
    local diff = false
    for i = 0, 15 do if A[slot][i] ~= B[slot][i] then diff = true; break end end
    if diff then
        log(string.format("BG palette slot %2d DIFFERS:", slot))
        log("  menu: " .. fmt_row(A[slot]))
        log("  reso: " .. fmt_row(B[slot]))
    else
        log(string.format("BG palette slot %2d same: %s", slot, fmt_row(A[slot])))
    end
end
local f=io.open(OUT,"w"); if f then f:write(table.concat(lines,"\n").."\n"); f:close() end
client.exit()
