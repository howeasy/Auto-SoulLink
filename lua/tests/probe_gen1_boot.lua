--[[
  lua/tests/probe_gen1_boot.lua — what actually happens during a Gen 1 cold boot?

  gen1_playthrough.lua kept wedging with wCurMap reading 0x26 (REDS_HOUSE_2F) and the
  player immobile, which suggested the "in the bedroom" test was firing on a STALE wCurMap
  before the game had really started. Rather than guess a third time, this logs the boot
  sequence so the playthrough's phase conditions can be written against what the game
  really does.

  Mashes A/Start like the real driver and dumps the interesting bytes on change, so the
  output is a state timeline rather than a wall of identical lines.

  Read-only. Launched by tools/gen1_playthrough.py --probe.
--]]

local ROOT = SLINK_ROOT or os.getenv("SLINK_ROOT")
    or (debug.getinfo(1, "S").source or ""):match([=[^@(.*)[/\]lua[/\]tests[/\]]=])
assert(ROOT, "repo root unknown")
local OUT = ROOT .. "/patch/build/gen1_boot_probe.txt"

local fmt = string.format
local lines = {}
local function emit(s)
    console.log(s)
    lines[#lines + 1] = s
    local f = io.open(OUT, "w")
    if f then f:write(table.concat(lines, "\n") .. "\n"); f:close() end
end

-- Red/Blue addresses (this probe is for Red).
local NAMING, CURMAP, PARTY = 0xD07D, 0xD35E, 0xD163
local CURMENU, MAXMENU = 0xCC26, 0xCC28
local JOY, STATUS5, X, Y = 0xCD6B, 0xD730, 0xD362, 0xD361
local r8 = function(x) return memory.read_u8(x, "System Bus") end

client.speedmode(6399)
emit("[boot-probe] tracking map/naming/party/status5/curMenu/maxMenu")

local last, frame = nil, 0
while frame < 20000 do
    local key = fmt("%02X|%02X|%d|%02X|%d|%d",
                    r8(CURMAP), r8(NAMING), r8(PARTY), r8(STATUS5), r8(CURMENU), r8(MAXMENU))
    if key ~= last then
        emit(fmt("[boot-probe] %6d map=0x%02X naming=0x%02X party=%d status5=0x%02X curMenu=%d maxMenu=%d",
                 frame, r8(CURMAP), r8(NAMING), r8(PARTY), r8(STATUS5), r8(CURMENU), r8(MAXMENU)))
        last = key
    end
    local phase = math.floor(frame / 8) % 3
    if phase == 0 then joypad.set({A = true})
    elseif phase == 1 then joypad.set({Start = true}) end
    emu.frameadvance()
    frame = frame + 1
end
emit("RESULT: PASS boot probe complete")
client.exit()
