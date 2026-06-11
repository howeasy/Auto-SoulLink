-- input_sanity.lua — does joypad.set reach the GBA core from this savestate? Try each direction; log the
-- player tile before/after + what joypad.get reports, to find the correct input invocation.
local SDIR = "E:/Howard/Bizhawk/GBA/State"
local WT  = "E:/Google Drive/SLink/.claude/worktrees/condescending-bassi-9175e6"
local OUT = WT .. "/patch/build/input_sanity_result.txt"
local function poe() local id = memory.read_u8(0x02037078 + 5); if id >= 16 then id = 0 end; return 0x02036E38 + id * 0x24 end
local function tile() return memory.read_u16_le(poe() + 0x10), memory.read_u16_le(poe() + 0x12) end
local function face() return memory.read_u8(poe() + 0x18) & 0x0F end
local lines = {}; local function log(s) lines[#lines+1] = s; console.log(s) end

pcall(function() client.speedmode(100) end)
pcall(savestate.load, SDIR .. "/slink_prebattle.State"); emu.frameadvance(); pcall(memory.usememorydomain, "System Bus")

-- 1) what does joypad.get report (button-name format / controller index)?
local g1 = joypad.get(1)
local names = {}; for k, _ in pairs(g1 or {}) do names[#names+1] = k end
table.sort(names)
log("joypad.get(1) keys: " .. table.concat(names, ","))

-- 2) try holding a direction 24 frames, both with and without an explicit controller index
local function trydir(dir, idx)
    pcall(savestate.load, SDIR .. "/slink_prebattle.State"); emu.frameadvance()
    local x0, y0 = tile()
    for _ = 1, 24 do
        if idx then joypad.set({ [dir] = true }, idx) else joypad.set({ [dir] = true }) end
        emu.frameadvance()
    end
    local x1, y1 = tile()
    local gg = joypad.get(idx or 1)
    log(string.format("hold %-5s idx=%s : tile (%d,%d)->(%d,%d) face=%d  get[%s]=%s",
        dir, tostring(idx), x0, y0, x1, y1, face(), dir, tostring(gg and gg[dir])))
end
trydir("Down", 1)
trydir("Down", nil)
trydir("Up", 1)
trydir("Left", 1)
trydir("Right", 1)

local f = io.open(OUT, "w"); if f then f:write(table.concat(lines, "\n") .. "\n"); f:close() end
client.exit()
