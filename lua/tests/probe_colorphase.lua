-- probe_colorphase.lua — why did E2E colors render dark? Isolate: the SAME direct gold (4) call at
-- (A) the ACTION menu phase and (B) turn RESOLUTION (the phase where the theme demo showed color), and
-- dump SLINK_TEXT_BUF's first bytes to prove whether the FC 01 04 prefix is staged in both.
local SDIR = "E:/Howard/Bizhawk/GBA/State"
local WT = SLINK_ROOT or os.getenv("SLINK_ROOT") or debug.getinfo(1, "S").source:match([=[^@(.*)[/\]lua[/\]tests[/\]]=])
assert(WT, "repo root unknown — launch via: python tools/run_gate.py <this script>")
local OUT  = WT .. "/patch/build/colorphase_result.txt"
local MB   = dofile(WT .. "/lua/mailbox.lua")
local lines = {}; local function log(s) lines[#lines+1]=s; console.log(s) end
local function shot(n) pcall(function() client.screenshot(WT .. "/patch/build/" .. n) end) end
local function dump_buf(tag)
    local t = {}
    for i = 0, 7 do t[#t+1] = string.format("%02X", memory.read_u8(0x0203F900 + i)) end
    log(tag .. " TEXT_BUF: " .. table.concat(t, " "))
end

pcall(function() client.speedmode(400) end)

-- (A) ACTION-select menu phase (where E2E msg2/msg3 drew)
pcall(savestate.load, SDIR .. "/slink_actionmenu.State"); emu.frameadvance(); pcall(memory.usememorydomain, "System Bus")
MB.show_battle_message("GOLD TEST", 200, 0x0D, 4)
dump_buf("actionmenu")
for _ = 1, 16 do emu.frameadvance() end
shot("phase_actionmenu.png")

-- (B) turn RESOLUTION phase (where the theme demo showed correct colors)
pcall(savestate.load, SDIR .. "/slink_movemenu.State"); emu.frameadvance(); pcall(memory.usememorydomain, "System Bus")
joypad.set({ A = true }); emu.frameadvance()
for _ = 1, 22 do emu.frameadvance() end
MB.show_battle_message("GOLD TEST", 200, 0x0D, 4)
dump_buf("resolution")
for _ = 1, 16 do emu.frameadvance() end
shot("phase_resolution.png")

local f=io.open(OUT,"w"); if f then f:write(table.concat(lines,"\n").."\n"); f:close() end
client.exit()
