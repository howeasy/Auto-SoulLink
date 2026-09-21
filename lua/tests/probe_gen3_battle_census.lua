-- probe_gen3_battle_census.lua — which battle-path functions actually EXECUTE when a Radical
-- Red (or FR) battle starts? (P3 instrument, 2026-09-21.)
--
-- Motivation: the shadow observer registers every pinned site on the RR companion, the binary
-- scan says every pinned function keeps its vanilla callers, and exec hooks provably deliver at
-- low/mid ROM addresses (probe_gen3_exec_addr.lua), yet no battle kind fired in any RR duo. So
-- hook EVERY battle-related function start from the FR .sym (SLINK_CENSUS_FILE, one
-- "name=0xADDR" per line, generated from data/gen3/pret/pokefirered.sym) and count hits while
-- a battle is started from the overworld savestate the duos use (SLINK_STATE), replaying the
-- explode scenario's entry inputs (Down for 60 frames into the trainer's sight, then A).
-- Prints one COUNT line per function that fired (hits, first callback address, first frame)
-- and a SILENT list; RESULT: PASS when at least one hooked function fired after the walk.
--
-- Environment: SLINK_ROOT, SLINK_STATE (savestate path), SLINK_CENSUS_FILE, SLINK_PROBE_FRAMES
-- (default 1800), plus SLINK_GEN3_CHECKPOINT/SLINK_GEN3_TITLE for gen3_boot_check.lua helpers.

local WT = SLINK_ROOT or os.getenv("SLINK_ROOT")
assert(WT, "SLINK_ROOT unset")
local G = dofile(WT .. "/lua/tests/gen3_boot_check.lua")

G.open("gen3_battle_census")               -- patch/build/gen3_battle_census_result.txt
pcall(client.speedmode, 6399)
local cp, title = G.checkpoint()
G.phase("start", "title=" .. tostring(title))

local STATE = os.getenv("SLINK_STATE")
if STATE and STATE ~= "" then
    local ok = pcall(savestate.load, STATE)
    G.phase("state", (ok and "loaded " or "FAILED ") .. STATE)
    G.idle(30)
else
    if not G.boot_to_field(cp, 9000) then G.shot("stuck"); G.finish(false, "never reached the field") end
end
G.phase("field", string.format("map=%d,%d", G.map(cp)))

local list = assert(os.getenv("SLINK_CENSUS_FILE"), "SLINK_CENSUS_FILE unset")
SNAP = nil
do
    local s = os.getenv("SLINK_CENSUS_SNAP")
    if s and s ~= "" then SNAP = {}; for hex in s:gmatch("0x%x+") do SNAP[#SNAP + 1] = tonumber(hex) end end
end
local probes = {}
for line in io.lines(list) do
    local name, hex = line:match("^(%S+)=(0x%x+)")
    if name then
        local p = { name = name, addr = tonumber(hex), hits = 0, snaps = {} }
        p.id = event.on_bus_exec(function(cb)
            p.hits = p.hits + 1
            if not p.first_cb then p.first_cb = cb; p.first_frame = emu.framecount() end
            -- SLINK_CENSUS_SNAP="0xADDR,0xADDR": record those RAM bytes at every hit (first 40)
            if SNAP and #p.snaps < 40 then
                local vals = {}
                for i, a in ipairs(SNAP) do vals[i] = memory.read_u8(a) end
                p.snaps[#p.snaps + 1] = string.format("f%d:%s", emu.framecount(), table.concat(vals, "/"))
            end
        end, p.addr, "SLink-census-" .. name)
        probes[#probes + 1] = p
    end
end
G.phase("registered", tostring(#probes) .. " functions")

local FRAMES = tonumber(os.getenv("SLINK_PROBE_FRAMES") or "") or 1800
local f0 = emu.framecount()
-- explode scenario entry: Down held 60 frames (into the trainer's line of sight), then A every
-- other frame until the budget ends (lua/tests/duo/scenario_explode.lua).
-- SLINK_CENSUS_ENCOUNTERS=1: after each battle returns to the field, walk Down/Up in the
-- tall grass the prebattle state stands in until the next encounter, and keep fighting with
-- FIGHT/move 1 (A) so the player eventually faints (the wild_faint leg needed <= 4 encounters).
local grass = os.getenv("SLINK_CENSUS_ENCOUNTERS") == "1"
local function in_battle() return not G.pred_ok(cp, "in_battle") end
-- SLINK_CENSUS_SCRIPT="Up,wait20,A,wait60,...": replay a fixed input script (same syntax as
-- probe_gen3_rr_bag.lua: button names, waitN) INSTEAD of the battle-entry inputs, then idle
-- the remaining frames. Lets one run show which hooked bodies execute during a menu flow.
local script = os.getenv("SLINK_CENSUS_SCRIPT")
if script and script ~= "" then
    local used, shots = 0, 0
    for raw in script:gmatch("[^,]+") do
        local s = raw:match("^%s*(.-)%s*$")
        local n = s:match("^wait(%d+)$")
        if n then G.idle(tonumber(n)); used = used + tonumber(n)
        elseif s == "shot" then     -- runtime-state confirmation only (never geometry)
            shots = (shots or 0) + 1
            pcall(client.screenshot, WT .. string.format("/patch/build/gen3_census_%02d.png", shots))
        elseif s == "Up" or s == "Down" or s == "Left" or s == "Right" then
            -- a 3-frame tap only TURNS when the player faces another way (PHYSICAL 2026-09-21:
            -- the first Right/Up of the PC walk were turns and the walk ended a tile short), so
            -- hold the direction until the tile changes (bounded: a wall just bumps).
            local x0, y0 = G.pos(cp)
            for _ = 1, 48 do
                joypad.set({ [s] = true }); G.advance(); used = used + 1
                local x1, y1 = G.pos(cp)
                if x1 ~= x0 or y1 ~= y0 then break end
            end
            joypad.set({}); G.idle(20); used = used + 20
        else for _ = 1, 3 do joypad.set({ [s] = true }); G.advance() end; G.idle(13); used = used + 16 end
        local px, py = G.pos(cp)
        local mg, mn = G.map(cp)
        G.phase("script", string.format("%s frame=%d party=%d pos=(%d,%d) map=%d,%d facing=%d", s, emu.framecount(),
            memory.read_u8(0x02024029), px, py, mg, mn, memory.read_u8(0x02036E38 + 0x18) >> 4))
    end
    FRAMES = math.max(0, FRAMES - used)
end
-- SLINK_CENSUS_SAVE=<path>: save a state when the script ends (fixture maker: idle/door states);
-- SLINK_CENSUS_SAVE_ON_BATTLE=<path>: save once in_battle first holds (a real in-battle state).
SAVE_ON_BATTLE = os.getenv("SLINK_CENSUS_SAVE_ON_BATTLE")
if SAVE_ON_BATTLE == "" then SAVE_ON_BATTLE = nil end
do
    local out = os.getenv("SLINK_CENSUS_SAVE")
    if out and out ~= "" and script and script ~= "" then
        local oks = pcall(savestate.save, out)
        G.phase("saved", string.format("script-end state saved=%s -> %s", tostring(oks), out))
    end
end
local walk_dir, walk_n = "Down", 0
for i = 1, FRAMES do
    if script and script ~= "" and not grass then G.advance(); goto continue end
    if SAVE_ON_BATTLE and in_battle() then
        G.idle(120)   -- let the intro settle so the state reloads INSIDE the battle
        local oks = pcall(savestate.save, SAVE_ON_BATTLE)
        G.phase("saved", string.format("in-battle state saved=%s -> %s", tostring(oks), SAVE_ON_BATTLE))
        break
    end
    if grass and not in_battle() and i > 60 then
        walk_n = walk_n + 1
        if walk_n % 24 == 0 then walk_dir = (walk_dir == "Down") and "Up" or "Down" end
        if walk_n % 24 < 12 then joypad.set({ [walk_dir] = true }) else joypad.set({ A = (i % 2 == 0) }) end
    elseif i <= 60 then joypad.set({ Down = true })
    elseif i % 2 == 0 then joypad.set({ A = true })
    else joypad.set({}) end
    G.advance()
    ::continue::
end
joypad.set({})
local mg, mn = G.map(cp)   -- two returns: capture first, or the next format arg is dropped
G.phase("walked", string.format("map=%d,%d in_battle=%s", mg, mn, tostring(G.pred(cp, "in_battle"))))

table.sort(probes, function(a, b) return (a.first_frame or 1e12) < (b.first_frame or 1e12) end)
local fired, silent = 0, {}
for _, p in ipairs(probes) do
    if p.hits > 0 then
        fired = fired + 1
        G.phase("count", string.format("%s addr=0x%08X hits=%d first_cb=0x%08X first_frame=%d",
                                       p.name, p.addr, p.hits, p.first_cb, p.first_frame))
        if #p.snaps > 0 then G.phase("snaps", p.name .. " " .. table.concat(p.snaps, " ")) end
    else
        silent[#silent + 1] = p.name
    end
    pcall(event.unregisterbyid, p.id)
end
G.phase("silent", table.concat(silent, ","))
G.finish(fired > 0, string.format("%d of %d hooked functions fired over %d frames",
                                  fired, #probes, emu.framecount() - f0))
