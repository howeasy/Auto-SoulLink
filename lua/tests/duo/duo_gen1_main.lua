-- duo_gen1_main.lua — Gen 1 wrapper for the TWO-INSTANCE headless E2E harness.
--
-- The Gen 1 counterpart to duo_main.lua. tools/e2e_duo.py generates a per-instance stub
-- (patch/build/duo_{a,b}.lua) that sets the production client globals plus SLINK_DUO, then
-- dofiles this file.
--
-- TWO REAL DIFFERENCES FROM THE GEN 3 WRAPPER:
--
--  1. NO SAVESTATE. Gen 3 loads a version-locked slink_*.State; Gen 1 boots from a battery
--     save (tests/fixtures/gen1/*.SaveRAM), which never goes stale. The boot has to be
--     PROVEN rather than assumed — the CONTINUE menu loads the save preview into the same
--     WRAM the party lives in, so a party-count check alone passes while the emulator is
--     still sitting on the title screen. Require the party AND actual movement.
--
--  2. A IS RED AND B IS BLUE — genuinely different cartridges, which is closer to how the
--     feature is played than Gen 3's same-ROM duo, and it means the two instances cannot
--     collide over BizHawk's SaveRAM (it names saves per gamedb entry).
--
-- Result protocol is identical: incremental log lines, "MYKEY <slot> <key>" so the runner
-- can link A slot0 <-> B slot0, and a final "RESULT: PASS|FAIL ...".

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
    error("slink-duo-finished", 0)     -- client.exit() is async
end

-- Tee the production client's own logs (dispatch decisions, faint routing) into the file.
local _console_log = console.log
console.log = function(s)
    _console_log(s)
    if logf then logf:write("[client] " .. tostring(s) .. "\n"); logf:flush() end
end

package.path = D.wt .. "/lua/?.lua;" .. D.wt .. "/lua/games/?.lua;"
            .. D.wt .. "/data/games/gen1_rby/?.lua;" .. package.path
package.loaded["memory_gb"] = nil
package.loaded["games.gen1_rby"] = nil
local M = require("memory_gb")
local G = require("games.gen1_rby")

log("duo instance " .. D.player .. " scenario=" .. D.scenario)
pcall(function() client.speedmode(400) end)

local variant = G.detect_variant()
if not variant then finish(false, "not a Gen 1 ROM") end
M.initProfile(G, variant)
log("variant=" .. variant)

-- ── Boot from the battery save ───────────────────────────────────────────────
local x_addr, y_addr = M.MAP_ID_ADDR + 4, M.MAP_ID_ADDR + 3
local frame = 0
local function step(b)
    if b then joypad.set(b) end
    emu.frameadvance()
    frame = frame + 1
end
local function hold(btn, n, stop)
    for _ = 1, n do
        if stop and stop() then return true end
        step({[btn] = true})
    end
    step(nil)
    return stop and stop() or false
end

local booted = false
local dirs = {"Right", "Left"}   -- never up/down: that moves the title cursor onto NEW GAME
for i = 1, 300 do
    local pc = M.getPartyCount()
    if pc >= 1 and pc <= 6 then
        local x0, y0 = M.read_u8(x_addr), M.read_u8(y_addr)
        hold(dirs[(i % 2) + 1], 20, function()
            return M.read_u8(x_addr) ~= x0 or M.read_u8(y_addr) ~= y0
        end)
        if M.read_u8(x_addr) ~= x0 or M.read_u8(y_addr) ~= y0 then booted = true break end
    end
    hold("A", 6, nil)
    for _ = 1, 16 do step(nil) end
end
if not booted then finish(false, "never booted into the overworld from the battery save") end
log(string.format("booted at frame %d party=%d", frame, M.getPartyCount()))

-- ── Distinct identities ──────────────────────────────────────────────────────
-- Both fixtures were produced by the same scripted playthrough, so their mons can share a
-- key (DVs:OTID:species). The server indexes links by key, so a collision would link a mon
-- to itself. Instance B rewrites its OT id and DVs before hello.
if D.mutate_otid then
    local base = M.PARTY_BASE_ADDR
    M.write_u16_be(base + M.OTID_OFFSET, 0x7B0B)
    M.write_u8(base + 0x1B, 0xA5)      -- Atk/Def DVs
    M.write_u8(base + 0x1C, 0x5A)      -- Spd/Spc DVs
    M.write_u16_be(M.PLAYER_ID_ADDR, 0x7B0B)
    log("mutated OTID/DVs so B's keys cannot collide with A's")
end

-- ── Filler mon ───────────────────────────────────────────────────────────────
-- Some scenarios need a spare: depositPartyMon refuses to box the LAST party mon (that
-- would soft-lock the save), so a 1-mon party cannot exercise box sync at all.
--
-- Added BEFORE the production client is loaded, so it is present in the client's very
-- first party snapshot. Adding it later would look like a wild capture and fire a `capture`
-- event mid-scenario.
if D.fillers then
    local struct = M.PARTY_STRUCT_SIZE
    local src, dst = M.PARTY_BASE_ADDR, M.PARTY_BASE_ADDR + struct
    for i = 0, struct - 1 do M.write_u8(dst + i, M.read_u8(src + i)) end
    -- Distinct DVs and level, or the filler shares slot 0's key and the server's flat key
    -- index links a mon to itself.
    M.write_u8(dst + 0x1B, 0x24)
    M.write_u8(dst + 0x1C, 0x42)
    M.write_u8(dst + M.LEVEL_OFFSET, 8)
    for i = 0, 10 do
        M.write_u8(M.PARTY_OT_NAMES_ADDR + 11 + i, M.read_u8(M.PARTY_OT_NAMES_ADDR + i))
        M.write_u8(M.PARTY_NICKS_ADDR + 11 + i, M.read_u8(M.PARTY_NICKS_ADDR + i))
    end
    M.write_u8(M.PARTY_SPECIES_ADDR + 1, M.read_u8(M.PARTY_SPECIES_ADDR))
    M.write_u8(M.PARTY_SPECIES_ADDR + 2, 0xFF)
    M.write_u8(M.PARTY_COUNT_ADDR, 2)
    log("added filler mon in slot 1 (party is now 2)")
end

for slot = 0, M.getPartyCount() - 1 do
    local mon = M.readPartySlot(slot)
    if mon then log(string.format("MYKEY %d %s", slot, mon.key)) end
end

-- ── Load the REAL production client ──────────────────────────────────────────
-- It registers event.onframeend rather than blocking, so control returns here and the
-- scenario coroutine can run alongside it.
local okc, errc = pcall(dofile, D.wt .. "/lua/clients/gen1_rby_client.lua")
log("client dofile ok=" .. tostring(okc) .. (okc and "" or (" err=" .. tostring(errc))))
if not okc then finish(false, "client dofile error: " .. tostring(errc)) end

-- ── Scenario context ─────────────────────────────────────────────────────────
local ctx = {player = D.player, log = log, M = M, G = G}

function ctx.frames(n) for _ = 1, n do coroutine.yield() end end

-- Input. Gen 1 needs a direction HELD to walk — a tap only turns the player — so scenarios
-- that actually play the game (rather than poking RAM) need to drive the pad, not just wait.
-- joypad.set is per-frame, so the hold has to be re-applied every frame it should last.
function ctx.hold(btn, frames, stop)
    for _ = 1, (frames or 8) do
        joypad.set({[btn] = true})
        coroutine.yield()
        if stop and stop() then return true end
    end
    coroutine.yield()
    return false
end

function ctx.wait_until(pred, max_frames, what)
    for _ = 1, (max_frames or 14400) do
        local v = pred()
        if v then return v end
        coroutine.yield()
    end
    log("timeout waiting for " .. tostring(what))
    return nil
end

function ctx.wait_go(max_frames)
    return ctx.wait_until(function()
        local f = io.open(D.go_file, "r")
        if f then f:close() return true end
        return nil
    end, max_frames or 14400, "go-file")
end

--- Wait for the partner instance to write its verdict.
--- Needed because finish() calls client.exit(): whichever side returns first stops
--- emulating, and its client stops sending. A that exits right after writing HP=0 never
--- gets another frame to emit `faint`, so B waits forever for a message nobody sent.
function ctx.wait_partner_done(max_frames)
    return ctx.wait_until(function()
        local f = io.open(D.partner_result, "r")
        if not f then return nil end
        local text = f:read("*a"); f:close()
        return text:match("RESULT:") ~= nil or nil
    end, max_frames or 14400, "partner to finish")
end

function ctx.party_count() return M.getPartyCount() end
function ctx.slot_key(s)
    local mon = M.readPartySlot(s)
    return mon and mon.key or nil
end
-- The raw memory module, for scenarios that must corroborate a transient (e.g. a mon that
-- was at 0 HP for two frames before memorialize removed it) against durable state.
ctx.M = M

function ctx.find_slot_by_key(key)
    for s = 0, ctx.party_count() - 1 do
        if ctx.slot_key(s) == key then return s end
    end
    return nil
end
-- Generation-agnostic HP access: Gen 1 stores HP BIG-endian, Gen 3 little-endian, so a
-- scenario must never poke raw memory itself.
function ctx.read_hp(slot)
    return M.read_u16_be(M.PARTY_BASE_ADDR + slot * M.PARTY_STRUCT_SIZE + M.HP_OFFSET)
end
function ctx.write_hp(slot, v)
    M.write_u16_be(M.PARTY_BASE_ADDR + slot * M.PARTY_STRUCT_SIZE + M.HP_OFFSET, v)
end

-- ── Drive the scenario as a coroutine ────────────────────────────────────────
local scen_fn = dofile(D.wt .. "/lua/tests/duo/scenario_gen1_" .. D.scenario .. ".lua")
local co = coroutine.create(function() return scen_fn(ctx) end)
local timeout = D.timeout_frames or 36000
for f = 1, timeout do
    local ok, pass, msg = coroutine.resume(co)
    if not ok then finish(false, "scenario error: " .. tostring(pass)) end
    if coroutine.status(co) == "dead" then finish(pass, msg) end
    if f % 1800 == 0 then
        log(string.format("heartbeat f=%d party=%d", f, M.getPartyCount()))
    end
    emu.frameadvance()
end
finish(false, "scenario timeout after " .. timeout .. " frames")
