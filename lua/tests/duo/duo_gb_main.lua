-- duo_gb_main.lua — Game Boy wrapper for the TWO-INSTANCE headless E2E harness.
--
-- Covers Gen 1 (RBY) and Gen 2 (Crystal). tools/e2e_duo.py generates a per-instance stub
-- (patch/build/duo_{a,b}.lua) that sets the production client globals plus SLINK_DUO, then
-- dofiles this file. SLINK_DUO.game selects the generation; everything that differs is a
-- table entry in lua/tests/gatelib.lua, not a branch here.
--
-- TWO REAL DIFFERENCES FROM THE GEN 3 WRAPPER:
--
--  1. NO SAVESTATE. Gen 3 loads a version-locked slink_*.State; these boot from a battery
--     save (tests/fixtures/<gen>/*.SaveRAM), which never goes stale. The boot has to be
--     PROVEN rather than assumed — the CONTINUE menu loads the save preview into the same
--     WRAM the party lives in, so a party-count check alone passes while the emulator sits
--     on the title screen. This file used to carry its own copy of that proof, in its
--     weakest form; it now calls the shared Lib.prove_booted, which needs a walked ROUND
--     TRIP that PERSISTS across an idle. See that function for the two versions of the
--     claim that were measured passing on a title screen and on a blank screen.
--
--  2. THE TWO INSTANCES MAY SHARE A CARTRIDGE. Gen 1 pairs Red with Blue, but Gen 2 has one
--     dump, so e2e_duo gives each instance its own SaveRAM directory — BizHawk names saves
--     from its gamedb entry, keyed on ROM hash, so two instances of one cartridge would
--     otherwise stamp on each other's save.
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

local Lib  = dofile(D.wt .. "/lua/tests/gatelib.lua")
local GAME = D.game or "gen1_rby"
local SPEC = Lib.GAMES[GAME]
assert(SPEC, "unknown SLINK_DUO.game " .. tostring(GAME))

package.path = D.wt .. "/lua/?.lua;" .. D.wt .. "/lua/games/?.lua;"
            .. D.wt .. "/data/games/" .. SPEC.data_dir .. "/?.lua;" .. package.path
package.loaded["memory_gb"] = nil
package.loaded[SPEC.module] = nil
local M = require("memory_gb")
local G = require(SPEC.module)

log("duo instance " .. D.player .. " scenario=" .. D.scenario)
pcall(function() client.speedmode(400) end)

local variant = G.detect_variant()
if not variant then finish(false, "not a " .. SPEC.label .. " ROM") end
M.initProfile(G, variant)
log("variant=" .. variant)

-- ── Boot from the battery save ───────────────────────────────────────────────
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

-- ── Do not let the boot walk start a battle ──────────────────────────────────
-- prove_booted walks to prove the emulator is live, and a fixture parked in tall grass
-- answers that walk with a wild encounter -- which commits a species before the scenario
-- can force one, and dead-zones the area whichever way the battle is then ended (measured:
-- a flush that ran away produced area_states {"route_1": "dead_zone"}). Closing the
-- engine's own NewBattle gate for the duration of the boot makes a grass fixture behave
-- like a town one. Scenarios that want battles reopen it -- gen1_hunt.force_wild does so as
-- soon as it has chosen the species, so the window is only ever open before that choice.
--
-- Advisory, not fatal: Gen 2 has no such address wired and AP disowns it, and neither of
-- those should stop a scenario that never walks into grass. prove_booted still accepts a
-- battle as proof, so a fixture that does encounter one is no worse off than before.
--
-- RE-ASSERT IT EVERY FRAME, do not set it once. This script runs BEFORE the ROM has
-- booted: the ~1000 frames prove_booted spends getting from the title screen into the
-- overworld are the game initialising its own WRAM, which wipes wStatusFlags4 along with
-- everything else. Measured -- a single write here read back set, and Route 1 still
-- answered the boot walk with a wild battle. Wrapping the frame primitives is what makes
-- the suppression outlive the initialisation that erases it.
local nb_step, nb_hold = step, hold
if M.setNoBattles then
    nb_step = function(btns) M.setNoBattles(true) step(btns) end
    nb_hold = function(btn, n, stop)
        for _ = 1, n do
            if stop and stop() then return true end
            nb_step({[btn] = true})
        end
        nb_step(nil)
        return stop and stop() or false
    end
end

local booted = Lib.prove_booted(M, GAME, nb_step, nb_hold)
if M.setNoBattles then
    -- THE WINDOW CLOSES HERE, and it covers the boot walk and nothing else. Scenarios walk
    -- in wildly different ways -- gen1_hunt.H.hunt, or a hand-rolled loop as in
    -- `playthrough` -- so any boundary further in has to be repeated per scenario and will
    -- be missed: reopening inside force_wild stranded `playthrough` and `deadzone`, which
    -- hunt without forcing, and reopening inside H.hunt still stranded `playthrough`, which
    -- does not use it ("no wild encounter in 600 steps", both times).
    -- Closing it here needs no such knowledge and is safe, because a Gen 1 encounter is
    -- rolled per STEP (TryDoWildEncounter, called from the overworld step handler) and
    -- nothing between this line and a scenario's first walk presses a direction -- the
    -- filler mon, hello and wait_go all idle. So the species a scenario forces is still
    -- chosen before anything can walk into an encounter.
    local reopened = M.setNoBattles(false)
    log(string.format("boot: battles suppressed for the walk, reopened=%s (in_battle=%s)",
                      tostring(reopened), tostring(M.isInBattle())))
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
    -- Through the profile, never a literal: Gen 1 keeps DVs at +0x1B/+0x1C and Gen 2 at
    -- +0x15/+0x16, so hardcoding Gen 1's would scribble over Gen 2's PP and happiness.
    M.write_u8(base + M.DV_OFFSET_1, 0xA5)
    M.write_u8(base + M.DV_OFFSET_2, 0x5A)
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
    M.write_u8(dst + M.DV_OFFSET_1, 0x24)
    M.write_u8(dst + M.DV_OFFSET_2, 0x42)
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
local okc, errc = pcall(dofile, D.wt .. "/lua/clients/" .. SPEC.client)
log("client dofile ok=" .. tostring(okc) .. (okc and "" or (" err=" .. tostring(errc))))
if not okc then finish(false, "client dofile error: " .. tostring(errc)) end

-- ── Scenario context ─────────────────────────────────────────────────────────
local ctx = {player = D.player, log = log, M = M, G = G}

function ctx.frames(n) for _ = 1, n do coroutine.yield() end end

-- Input. Both GB gens need a direction HELD to walk — a tap only turns the player — so scenarios
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
-- Scenario lookup: the generation's own file first, then the shared `gb` one. faint,
-- boxsync and memorialize are written entirely against ctx and are identical for both
-- generations, so they live under scenario_gb_*; anything that reaches into a specific
-- engine (the Gen 1 wild-table hunts, the rival swap) keeps its own prefixed file.
local function load_scenario()
    for _, name in ipairs({"scenario_" .. SPEC.scenario_prefix .. D.scenario,
                           "scenario_gb_" .. D.scenario}) do
        local path = D.wt .. "/lua/tests/duo/" .. name .. ".lua"
        local f = io.open(path, "r")
        if f then f:close() return dofile(path), name end
    end
    finish(false, "no scenario file for " .. tostring(D.scenario) .. " (" .. GAME .. ")")
end
local scen_fn, scen_name = load_scenario()
log("scenario file: " .. scen_name)
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
