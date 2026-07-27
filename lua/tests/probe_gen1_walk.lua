--[[
  lua/tests/probe_gen1_walk.lua — why will the player not walk out of the bedroom?

  The playthrough driver reaches the bedroom with a name set and control returned, then
  holds directions and goes nowhere: wXCoord/wYCoord stay at (3,6). Reasoning about it has
  produced three wrong theories, so this LOOKS instead: it screenshots the screen and logs
  the coordinate response to a long, uninterrupted hold of each direction.

  Writes patch/build/gen1_walk_probe.txt plus screenshots next to it.
--]]

local ROOT = SLINK_ROOT or os.getenv("SLINK_ROOT")
    or (debug.getinfo(1, "S").source or ""):match([=[^@(.*)[/\]lua[/\]tests[/\]]=])
assert(ROOT, "repo root unknown")
local OUT = ROOT .. "/patch/build/gen1_walk_probe.txt"
local SHOT = ROOT .. "/patch/build/"

local fmt = string.format
local lines = {}
local function emit(s)
    console.log(s)
    lines[#lines + 1] = s
    local f = io.open(OUT, "w")
    if f then f:write(table.concat(lines, "\n") .. "\n"); f:close() end
end

local CURMAP, PARTY, NAME = 0xD35E, 0xD163, 0xD158
local JOY, STATUS5, X, Y = 0xCD6B, 0xD730, 0xD362, 0xD361
local MAXMENU, TOPY, TOPX, CURMENU = 0xCC28, 0xCC24, 0xCC25, 0xCC26
local r8 = function(x) return memory.read_u8(x, "System Bus") end

local frame = 0
local function step(b)
    if b then joypad.set(b) end
    emu.frameadvance(); frame = frame + 1
end

client.speedmode(6399)

-- Get through the intro exactly as the driver now does: low-duty A until the name is set
-- and we are standing in the bedroom with control.
local function name_set() local b = r8(NAME); return b >= 0x80 and b <= 0x99 end
while frame < 20000 do
    if name_set() and r8(CURMAP) == 0x26 and r8(JOY) == 0 and r8(STATUS5) < 0x80 then break end
    local p = frame % 16
    step(p < 2 and {A = true} or nil)
end
emit(fmt("[walk-probe] intro done frame=%d map=0x%02X (%d,%d) name0=0x%02X",
         frame, r8(CURMAP), r8(X), r8(Y), r8(NAME)))
emit(fmt("[walk-probe] joy=0x%02X status5=0x%02X maxMenu=%d topY=%d topX=%d curMenu=%d",
         r8(JOY), r8(STATUS5), r8(MAXMENU), r8(TOPY), r8(TOPX), r8(CURMENU)))
client.screenshot(SHOT .. "walkprobe_bedroom.png")

-- Settle with NO input at all, then look again.
for _ = 1, 120 do step(nil) end
emit(fmt("[walk-probe] after 120 idle frames: (%d,%d) joy=0x%02X status5=0x%02X",
         r8(X), r8(Y), r8(JOY), r8(STATUS5)))
client.screenshot(SHOT .. "walkprobe_idle.png")

-- Hold ONE direction for a long, uninterrupted run and watch the coordinates.
for _, btn in ipairs({"Down", "Left", "Up", "Right"}) do
    local x0, y0 = r8(X), r8(Y)
    local changed_at = nil
    for i = 1, 180 do
        step({[btn] = true})
        if not changed_at and (r8(X) ~= x0 or r8(Y) ~= y0) then changed_at = i end
    end
    step(nil)
    emit(fmt("[walk-probe] hold %-5s 180f: (%d,%d) -> (%d,%d)  first change at frame %s",
             btn, x0, y0, r8(X), r8(Y), tostring(changed_at)))
    client.screenshot(SHOT .. "walkprobe_" .. btn .. ".png")
end

emit(fmt("[walk-probe] final map=0x%02X (%d,%d)", r8(CURMAP), r8(X), r8(Y)))
emit("RESULT: PASS walk probe complete")
client.exit()
