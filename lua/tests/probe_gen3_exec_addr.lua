-- probe_gen3_exec_addr.lua — does event.on_bus_exec deliver at ROM addresses beyond the one
-- site that is known to fire? (P3 instrument check, 2026-09-21.)
--
-- Physical fact that motivates it: on the RR companion, lua/gen3/signals.lua registers all 19
-- sites (rejected 0, dropped 0) yet only frame_control (0x0800051A) ever fires, while the
-- binary scan (docs/gen3/research/rr_site_reachability.md) shows every pinned function is
-- reachable with vanilla caller sets. So hook known-positive CONTROLS that run every frame in
-- the overworld at a low and a mid ROM address, plus the pinned battle_begin address, and count.
--
-- Boots the seeded battery to the field the way gen3_boot_check.lua does, registers the hooks,
-- runs SLINK_PROBE_FRAMES (default 900) frames, prints one COUNT line per address, RESULT: PASS
-- when every control fired at least once (the PASS/FAIL is about the controls; the battle_begin
-- count is informational: no battle starts in this probe).
--
-- Addresses come from SLINK_PROBE_ADDRS ("name=0xADDR,name=0xADDR,..."), so the same script
-- serves FR and RR. Defaults are the RR controls from the reachability note.

local WT = SLINK_ROOT or os.getenv("SLINK_ROOT")
assert(WT, "SLINK_ROOT unset — launch via tools/gen3_fixtures.py helpers")
local G = dofile(WT .. "/lua/tests/gen3_boot_check.lua")

G.open("gen3_exec_addr_probe")           -- patch/build/gen3_exec_addr_probe_result.txt
pcall(client.speedmode, 6399)
local cp, title = G.checkpoint()
G.phase("start", "title=" .. tostring(title))

local spec = os.getenv("SLINK_PROBE_ADDRS")
    or "control_frame=0x0800051A,AnimateSprites=0x08006B5C,RunTasks=0x08077578,battle_begin=0x0801019C"
local FRAMES = tonumber(os.getenv("SLINK_PROBE_FRAMES") or "") or 900

if not G.boot_to_field(cp, 9000) then
    G.shot("stuck")
    G.finish(false, "never reached the field")
end
G.phase("field", string.format("map=%d,%d", G.map(cp)))

local probes = {}
for name, hex in spec:gmatch("(%w+)=(0x%x+)") do
    local addr = tonumber(hex)
    local p = { name = name, addr = addr, hits = 0, first_cb = nil, first_frame = nil }
    p.id = event.on_bus_exec(function(cb)
        p.hits = p.hits + 1
        if not p.first_cb then p.first_cb = cb; p.first_frame = emu.framecount() end
    end, addr, "SLink-probe-" .. name)
    G.phase("registered", string.format("%s addr=0x%08X id=%s", name, addr, tostring(p.id)))
    probes[#probes + 1] = p
end

local f0 = emu.framecount()
for _ = 1, FRAMES do G.advance() end

local ok, missing = true, {}
for _, p in ipairs(probes) do
    G.phase("count", string.format("%s addr=0x%08X hits=%d first_cb=%s first_frame=%s",
        p.name, p.addr, p.hits, p.first_cb and string.format("0x%08X", p.first_cb) or "-",
        tostring(p.first_frame)))
    if p.name ~= "battle_begin" and p.hits == 0 then ok = false; missing[#missing + 1] = p.name end
    pcall(event.unregisterbyid, p.id)
end
G.finish(ok, ok and string.format("all controls fired over %d frames", emu.framecount() - f0)
                or ("controls silent: " .. table.concat(missing, ",")))
