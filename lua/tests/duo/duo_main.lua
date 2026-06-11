-- duo_main.lua — shared wrapper for the TWO-INSTANCE headless E2E harness (tools/e2e_duo.py).
--
-- The runner generates a per-instance stub (patch/build/duo_{a,b}.lua) that sets the production
-- client globals (SLINK_HOST/PORT/PLAYER) plus a SLINK_DUO table, then dofiles this file:
--   SLINK_DUO = {
--     wt        = "<worktree root, forward slashes>",
--     player    = "a" | "b",
--     scenario  = "faint" | "boxsync" | "trade" | "ghost",
--     savestate = "<absolute .State path>",
--     mutate_otid = false | true,   -- true on instance B: distinct keys from the shared save
--     result    = "<absolute result file path>",
--     go_file   = "<absolute go-file path>",  -- runner creates it when orchestration may proceed
--     timeout_frames = 36000,
--   }
-- Protocol (result file): incremental log lines; "MYKEY <slot> <key>" after mutation (the runner
-- links A slot0 <-> B slot0 by these keys); final line "RESULT: PASS|FAIL ...". The wrapper tees
-- the production client's console.log into the result file ("[client]" prefix) for diagnosis.
--
-- RR fixed addresses (CFRU NO_ENCRYPT, validated in ADDRESSES.md / memory_gba.lua):
local PARTY_BASE  = 0x02024284
local PARTY_COUNT = 0x02024029
local MON_SIZE    = 100
local OFF_PID     = 0x00
local OFF_OTID    = 0x04
local OFF_LEVEL   = 0x54
local OFF_HP      = 0x56
local OFF_MAXHP   = 0x58

local D = SLINK_DUO
assert(D and D.wt and D.player and D.scenario, "SLINK_DUO not configured (run via tools/e2e_duo.py)")

local logf = io.open(D.result, "w")
local function log(s)
    console.log("[duo" .. D.player:upper() .. "] " .. tostring(s))
    if logf then logf:write(tostring(s) .. "\n"); logf:flush() end
end
local function finish(pass, msg)
    log("RESULT: " .. (pass and "PASS" or "FAIL") .. (msg and (" (" .. msg .. ")") or ""))
    if logf then logf:close() end
    client.exit()
end

-- Tee the production client's own logs (dispatch decisions, faint routing, config) into the file.
local _console_log = console.log
console.log = function(s)
    _console_log(s)
    if logf then logf:write("[client] " .. tostring(s) .. "\n"); logf:flush() end
end

log("duo instance " .. D.player .. " scenario=" .. D.scenario)
pcall(function() client.speedmode(400) end)
local okst, errst = pcall(savestate.load, D.savestate)
log("savestate load ok=" .. tostring(okst) .. (okst and "" or (" err=" .. tostring(errst))))
if not okst then return finish(false, "savestate load failed") end
emu.frameadvance()

-- ── Party filler (the overworld save has a 1-mon party) ──────────────────────
-- Scenarios need spare mons (memorialize forbids the last mon; boxsync deposits slot 1).
-- Reuse test_live_memorialize's pattern: native OP_CREATE_MON via the mailbox. Both
-- instances share RNG state from the same savestate, so fillers get IDENTICAL PIDs across
-- instances — fine, because instance B mutates OTIDs below.
pcall(memory.usememorydomain, "System Bus")
local MB = dofile(D.wt .. "/lua/mailbox.lua")
for _ = 1, 60 do emu.frameadvance() end
if not MB.present() then return finish(false, "no SLNK beacon (unpatched ROM?)") end
local count = memory.read_u8(PARTY_COUNT)
if count == 0 or count > 6 then return finish(false, "bad party count " .. count) end
local FILLERS = {1, 4, 7}  -- Bulbasaur/Charmander/Squirtle lines, lv 5
while count < 3 do
    local seq = MB.send(MB.OP_CREATE_MON, MB.create_mon_args(count, FILLERS[count], 5, 0, 1))
    local st
    for _ = 1, 120 do emu.frameadvance(); st = MB.poll(seq); if st then break end end
    if st ~= MB.ST_OK then return finish(false, "filler OP_CREATE_MON failed: " .. tostring(st)) end
    count = memory.read_u8(PARTY_COUNT)
end
log("party count=" .. count)

-- ── Instance-B identity mutation ──────────────────────────────────────────────
-- Both instances load states from the SAME save, so the mon keys (personality:otId) would
-- collide in the server's flat _key_index. XOR a bit pattern into each party mon's OTID
-- (unencrypted header in CFRU NO_ENCRYPT; the substruct checksum doesn't cover it), then
-- de-shiny if the new TIDxSID^PID shiny value dropped under 8 (shiny clause / event spam).
if D.mutate_otid then
    for s = 0, count - 1 do
        local base = PARTY_BASE + s * MON_SIZE
        local otid = memory.read_u32_le(base + OFF_OTID)
        otid = otid ~ 0x000B0000
        local pid = memory.read_u32_le(base + OFF_PID)
        local shiny = ((otid & 0xFFFF) ~ (otid >> 16) ~ (pid & 0xFFFF) ~ (pid >> 16)) & 0xFFFF
        if shiny < 8 then otid = otid ~ 0x00080000 end
        memory.write_u32_le(base + OFF_OTID, otid)
    end
    log("mutated OTIDs on " .. count .. " party mons")
end
for s = 0, count - 1 do
    local base = PARTY_BASE + s * MON_SIZE
    log(string.format("MYKEY %d %08X:%08X", s,
        memory.read_u32_le(base + OFF_PID), memory.read_u32_le(base + OFF_OTID)))
end

-- ── Production client ─────────────────────────────────────────────────────────
local okc, errc = pcall(dofile, D.wt .. "/lua/clients/gen3_frlge_client.lua")
log("client dofile ok=" .. tostring(okc) .. (okc and "" or (" err=" .. tostring(errc))))
if not okc then return finish(false, "client dofile error") end

-- ── Scenario context ──────────────────────────────────────────────────────────
local ctx = {
    player = D.player, duo = D, log = log,
    PARTY_BASE = PARTY_BASE, PARTY_COUNT = PARTY_COUNT, MON_SIZE = MON_SIZE,
    OFF_PID = OFF_PID, OFF_OTID = OFF_OTID, OFF_LEVEL = OFF_LEVEL,
    OFF_HP = OFF_HP, OFF_MAXHP = OFF_MAXHP,
}
function ctx.frames(n)
    for _ = 1, n do coroutine.yield() end
end
-- Wait until pred() is truthy; returns its value, or nil after max_frames.
function ctx.wait_until(pred, max_frames, what)
    for _ = 1, max_frames do
        local v = pred()
        if v then return v end
        coroutine.yield()
    end
    log("TIMEOUT waiting for " .. (what or "condition") .. " after " .. max_frames .. " frames")
    return nil
end
-- Wait for the runner's go-file; returns its content lines as a table, nil on timeout.
function ctx.wait_go(max_frames)
    return ctx.wait_until(function()
        local gf = io.open(D.go_file, "r")
        if not gf then return nil end
        local lines = {}
        for l in gf:lines() do lines[#lines + 1] = l end
        gf:close()
        return lines
    end, max_frames or 18000, "go-file " .. D.go_file)
end
function ctx.party_count() return memory.read_u8(PARTY_COUNT) end
function ctx.slot_base(s) return PARTY_BASE + s * MON_SIZE end
function ctx.slot_key(s)
    local base = ctx.slot_base(s)
    return string.format("%08X:%08X",
        memory.read_u32_le(base + OFF_PID), memory.read_u32_le(base + OFF_OTID))
end
function ctx.find_slot_by_key(key)
    for s = 0, ctx.party_count() - 1 do
        if ctx.slot_key(s) == key then return s end
    end
    return nil
end

-- ── Run the scenario as a coroutine driven from the frame loop ────────────────
local scen_fn = dofile(D.wt .. "/lua/tests/duo/scenario_" .. D.scenario .. ".lua")
local co = coroutine.create(function() return scen_fn(ctx) end)
local timeout = D.timeout_frames or 36000
local heartbeat = 0
for frame = 1, timeout do
    local ok, pass, msg = coroutine.resume(co)
    if not ok then return finish(false, "scenario error: " .. tostring(pass)) end
    if coroutine.status(co) == "dead" then return finish(pass, msg) end
    heartbeat = heartbeat + 1
    if heartbeat % 1800 == 0 then
        log(string.format("heartbeat f=%d count=%d", frame, memory.read_u8(PARTY_COUNT)))
    end
    emu.frameadvance()
end
finish(false, "scenario timeout after " .. timeout .. " frames")
