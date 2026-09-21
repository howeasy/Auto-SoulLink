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
local probes = {}
for line in io.lines(list) do
    local name, hex = line:match("^(%S+)=(0x%x+)")
    if name then
        local p = { name = name, addr = tonumber(hex), hits = 0 }
        p.id = event.on_bus_exec(function(cb)
            p.hits = p.hits + 1
            if not p.first_cb then p.first_cb = cb; p.first_frame = emu.framecount() end
        end, p.addr, "SLink-census-" .. name)
        probes[#probes + 1] = p
    end
end
G.phase("registered", tostring(#probes) .. " functions")

local FRAMES = tonumber(os.getenv("SLINK_PROBE_FRAMES") or "") or 1800
local f0 = emu.framecount()
-- explode scenario entry: Down held 60 frames (into the trainer's line of sight), then A every
-- other frame until the budget ends (lua/tests/duo/scenario_explode.lua).
for i = 1, FRAMES do
    if i <= 60 then joypad.set({ Down = true })
    elseif i % 2 == 0 then joypad.set({ A = true })
    else joypad.set({}) end
    G.advance()
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
    else
        silent[#silent + 1] = p.name
    end
    pcall(event.unregisterbyid, p.id)
end
G.phase("silent", table.concat(silent, ","))
G.finish(fired > 0, string.format("%d of %d hooked functions fired over %d frames",
                                  fired, #probes, emu.framecount() - f0))
