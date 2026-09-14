-- duo_gen1_main.lua — two-instance live harness for the NEW Gen 1 client (lua/gen1/*).
--
-- tools/e2e_duo.py (game "gen1_new") generates patch/build/duo_{a,b}.lua, which sets
-- SLINK_HOST/PORT/PLAYER plus SLINK_DUO and dofiles this file. It builds the REAL client the
-- way lua/gen1/run.lua does (Entry.build over Entry.bizhawk_deps(), the LuaSocket connector,
-- the HUD), boots the battery fixture with gen1_gate's checkpoint proof, then plays the
-- scenario as a coroutine that yields once per frame while this loop runs
-- `emu.frameadvance(); client:frame_end()` every frame, exactly like production.
--
-- Nothing is injected: the scenarios walk Route 1's grass with the hunt route module
-- (lua/tests/gen1_rb_hunt_inputs.lua), meet real wild Pokemon and throw the fixture's one
-- Poke Ball. Result protocol as duo_gb_main: log lines, "MYKEY <slot> <key>" per party mon
-- (after boot and after each capture), "CAUGHT <key>", the client's wire traffic as
-- "TX <event> ..." / "RX <cmd> ...", and a final "RESULT: PASS|FAIL (reason)".
local D = SLINK_DUO
assert(D and D.wt and D.player and D.scenario and D.result, "SLINK_DUO not configured (run via tools/e2e_duo.py)")
assert(D.game == "gen1_new", "duo_gen1_main only serves game gen1_new, got " .. tostring(D.game))

local ROOT = D.wt
package.path = ROOT .. "/lua/?.lua;" .. package.path
local fmt = string.format

local logf = io.open(D.result, "w")
local _console_log = console.log
local function log(s)
    _console_log("[duo" .. D.player:upper() .. "] " .. tostring(s))
    if logf then logf:write(tostring(s) .. "\n"); logf:flush() end
end
local function finish(pass, msg)
    log("RESULT: " .. (pass and "PASS" or "FAIL") .. (msg and (" (" .. msg .. ")") or ""))
    if logf then logf:close() end
    client.exit()
    error("slink-duo-finished", 0) -- client.exit() is async
end
-- Tee the client's own log lines into the result file.
console.log = function(s)
    _console_log(s)
    if logf then logf:write("[client] " .. tostring(s) .. "\n"); logf:flush() end
end

local Entry = dofile(ROOT .. "/lua/gen1/entry.lua")
local C = require("connector")
local H = require("hud")
local json = dofile(ROOT .. "/lua/json_codec.lua")
local safety = dofile(ROOT .. "/lua/gen1_write_safety.lua")
local Hunt = dofile(ROOT .. "/lua/tests/gen1_rb_hunt_inputs.lua")
local Driver = dofile(ROOT .. "/lua/tests/gen1_battle_driver.lua")
local Play = dofile(ROOT .. "/lua/tests/gen1_scripted_play.lua")

log("duo instance " .. D.player .. " scenario=" .. D.scenario .. " game=" .. D.game)
pcall(function() client.speedmode(D.speed or 1600) end)

local title, header = Entry.detect_title(function(a) return memory.read_u8(a, "ROM") end)
if not title then finish(false, "not a Gen 1 cartridge (header " .. tostring(header) .. ")") end
local deps = Entry.bizhawk_deps()
local rom_sha1 = gameinfo.getromhash():lower()
H.init({ screen_w = 160, screen_h = 144 })
C.init(SLINK_HOST, tonumber(SLINK_PORT))

-- Wire receipts: every line the client sends and every command it receives.
local seen = {} -- event/cmd name -> count
local _send = C.send
C.send = function(line)
    local ok, msg = pcall(json.decode, line)
    local name = ok and type(msg) == "table" and msg.event or "?"
    seen[name] = (seen[name] or 0) + 1
    if name ~= "tick" then log("TX " .. (line:sub(1, 220))) end
    return _send(line)
end

local gclient, parts = Entry.build({ root = ROOT, io = deps, net = C, hud = H, title = title, player = D.player,
                                     rom_sha1 = rom_sha1, log = function(s) console.log(s) end })
local _handle = gclient.handle_command
gclient.handle_command = function(self, cmd)
    local c = cmd and cmd.cmd or "?"
    seen[c] = (seen[c] or 0) + 1
    if c ~= "noop" then
        log("RX " .. c .. (cmd.key and (" key=" .. tostring(cmd.key)) or "") .. (cmd.text and (" text=" .. tostring(cmd.text)) or ""))
    end
    return _handle(self, cmd)
end
local okc, errc = pcall(function() gclient:start() end)
if not okc then finish(false, "client refused to start: " .. tostring(errc)) end
SLINK_GEN1_CLIENT = gclient
log(fmt("client built: title=%s player=%s rom=%s -> %s:%s", title, D.player, rom_sha1:sub(1, 8), SLINK_HOST, tostring(SLINK_PORT)))

local reads, ram = parts.reads, parts.profile.ram
local ws = assert(json.decode(assert(io.open(ROOT .. "/data/games/gen1_rby/write_checkpoint.json", "rb")):read("*a"))[title])
local function overworld_ok() return safety.check(ws, deps) == true end

-- ── Frame primitives: the client ticks on EVERY frame, boot included ─────────────────
local frame = 0
local last_count, unreadable = nil, false
local function step(buttons)
    if buttons then joypad.set(buttons) end
    emu.frameadvance()
    frame = frame + 1
    local ok, err = pcall(gclient.frame_end, gclient)
    if not ok then log("client frame error: " .. tostring(err)) end
    H.render()
    -- Receipts: party count edges (quarantine deposit / withdraw / memorial show here) and the
    -- windows in which the client's own party read refuses (it revokes writes after 5 of them).
    local count = memory.read_u8(ram.wPartyCount, "System Bus")
    if count ~= last_count then log(fmt("PARTY_COUNT %s -> %d @%d", tostring(last_count), count, frame)); last_count = count end
    if frame % 10 == 0 then
        local party, why = reads.read_party()
        if (party == nil) ~= unreadable then
            unreadable = party == nil
            local species = {}
            for i = 0, 6 do species[#species + 1] = fmt("%02X", memory.read_u8(ram.wPartySpecies + i, "System Bus")) end
            log(fmt("PARTY_%s @%d %s (count=%d species=%s)", unreadable and "UNREADABLE" or "READABLE", frame, why or "", count, table.concat(species, " ")))
        end
    end
end

-- ── Boot proof (gen1_gate.lua): the checkpoint holds 30 frames with a plausible party ────
local booted, settled = false, 0
for f = 1, 6000 do
    local count = memory.read_u8(ram.wPartyCount, "System Bus")
    local ok = count >= 1 and count <= 6 and overworld_ok()
    settled = ok and settled + 1 or 0
    if settled >= 30 then booted = true break end
    step((not ok and f % 16 < 2) and { A = true } or nil)
end
if not booted then
    client.screenshot(ROOT .. "/patch/build/e2e_" .. D.scenario .. "_" .. D.player .. "_bootfail.png")
    finish(false, "never booted into the overworld from the battery save (frame " .. frame .. ")")
end
local map = reads.read_map()
log(fmt("booted at frame %d party=%d map=%d (%d,%d)", frame, memory.read_u8(ram.wPartyCount, "System Bus"), map.map, map.x, map.y))

local function party_keys()
    local party = reads.read_party()
    local out = {}
    for _, m in ipairs(party or {}) do out[#out + 1] = { slot = m.slot, key = reads.key(m), hp = m.hp, species = m.species, level = m.level } end
    return out
end
local function log_party(tag)
    for _, m in ipairs(party_keys()) do
        log(fmt("MYKEY %d %s", m.slot, m.key))
        log(fmt("%s slot=%d key=%s species=%d level=%d hp=%d", tag or "PARTY", m.slot, m.key, m.species, m.level, m.hp))
    end
end
log_party("PARTY")
local boot_keys = {}
for _, m in ipairs(party_keys()) do boot_keys[m.key] = true end

-- ── Scenario context ─────────────────────────────────────────────────────────────────
-- Scenario level: set the pad, give the frame back to the main loop.
local function yield_frame(buttons) joypad.set(buttons or {}); coroutine.yield() end
-- Battle-plan level (inside the hunt module's coroutine): hand the buttons UP to route.step,
-- which returns them to the scenario, which sets the pad. One frame per call either way.
local function yield_buttons(buttons) coroutine.yield(buttons or {}) end
local function frames(n) for _ = 1, n do yield_frame() end end
local function wait_until(pred, secs, what)
    local deadline = os.time() + secs
    while os.time() < deadline do
        local v = pred()
        if v then return v end
        yield_frame()
    end
    log("timeout waiting for " .. tostring(what))
    return nil
end
local function file_exists(p) local f = io.open(p, "r"); if f then f:close() return true end return false end
local function wait_go() return wait_until(function() return file_exists(D.go_file) or nil end, 900, "go-file") end
local function partner_done()
    local f = io.open(D.partner_result, "r")
    if not f then return nil end
    local text = f:read("*a"); f:close()
    return text:find("RESULT:", 1, true) ~= nil or nil
end
local function wait_partner_done(secs) return wait_until(partner_done, secs or 600, "partner to finish") end

-- The hunt: gen1_scripted_play's WRAM point extended with the hunt's fields, the battle driver
-- over a step that yields, and the route module run to a terminal phase.
local play = Play.new(ROOT, title, D.player, { log = log })
local symbols = play.symbols
local function rd(addr) return memory.read_u8(addr, "System Bus") end
local rom = parts.profile.rom
local function hunt(mode)
    local driver = Driver.new({
        step = yield_buttons, u8 = rd,
        sites = { display_battle_menu = rom.DisplayBattleMenu.addr, move_selection_menu = rom.MoveSelectionMenu.addr,
                  select_enemy_move = rom.SelectEnemyMove.addr, execute_player_move = rom.ExecutePlayerMove.addr,
                  execute_enemy_move = rom.ExecuteEnemyMove.addr },
        addresses = { wTopMenuItemX = symbols.wTopMenuItemX, wTopMenuItemY = symbols.wTopMenuItemY,
                      wCurrentMenuItem = symbols.wCurrentMenuItem, wMaxMenuItem = symbols.wMaxMenuItem,
                      wMenuWatchedKeys = symbols.wMenuWatchedKeys, wIsInBattle = symbols.wIsInBattle,
                      wPlayerSelectedMove = symbols.wPlayerSelectedMove,
                      wActionResultOrTookBattleTurn = symbols.wActionResultOrTookBattleTurn,
                      hLoadedROMBank = symbols.hLoadedROMBank, wListScrollOffset = symbols.wListScrollOffset,
                      wPlayerMonNumber = symbols.wPlayerMonNumber, wPartyCount = symbols.wPartyCount,
                      wBattleMonMoves = symbols.wBattleMonMoves, wBattleMonPP = symbols.wBattleMonPP,
                      wBattleMonHP = symbols.wBattleMonHP, wEnemyMonHP = symbols.wEnemyMonHP,
                      wEnemySelectedMove = symbols.wEnemySelectedMove, wCurItem = symbols.wCurItem,
                      wNumRunAttempts = symbols.wNumRunAttempts, hJoyPressed = symbols.hJoyPressed },
    })
    local route = Hunt.new({ player = D.player }, { driver = driver, step = yield_buttons, rd = rd, symbols = symbols,
                                                   mode = mode, log = log })
    local last_phase, n = nil, 0
    local terminal = { caught = true, escaped = true, ["out-of-balls"] = true, ["hunt-exhausted"] = true,
                       whiteout = true, stuck = true, ["unexpected-battle"] = true }
    while true do
        n = n + 1
        if n > (D.hunt_frames or 90000) then driver.close(); return "hunt-timeout" end
        local point = Hunt.extend_point(play.point(), rd, symbols)
        local buttons, phase = route.step(nil, nil, point, emu.framecount())
        if phase ~= last_phase then
            last_phase = phase
            log(fmt("phase %s @%d (%d,%d) battle=%d party=%d", phase, emu.framecount(), point.x, point.y, point.battle, point.party_count))
        end
        if terminal[phase] then
            driver.close()
            log(fmt("HUNT %s after %d frames, %d encounter(s)", phase, n, route.encounters))
            return phase
        end
        yield_frame(buttons)
    end
end
local function new_key()
    for _, m in ipairs(party_keys()) do if not boot_keys[m.key] then return m.key, m end end
    return nil
end

-- ── Scenarios ────────────────────────────────────────────────────────────────────────
local scenarios = {}

-- D-1: both catch on Route 1; the server pairs the two captures by area on its own.
function scenarios.link_new()
    if not wait_go() then return false, "no go-file" end
    local phase = hunt("catch")
    if phase ~= "caught" then return false, "hunt ended " .. phase end
    local key = new_key()
    if not key then return false, "party grew but no new key" end
    log_party("PARTY")
    log("CAUGHT " .. key)
    -- Let the server's quarantine (box_mon) and the post-link party_mon settle on both sides.
    -- The link forms on the partner's capture; this side's half of the sync is the party_mon
    -- (un-quarantine) ACK. Wait for that, or for the partner to give up. No mutual wait: each
    -- side's client only has to outlive its own writes.
    wait_until(function() return (seen.sync_retrieve_done or seen.sync_retrieve_failed or seen.box_mon_failed) and true or partner_done() end,
               240, "post-link party sync or partner")
    frames(120)
    log_party("PARTY")
    log(fmt("SEEN capture=%d box_mon=%d stats_cache=%d party_mon=%d sync_retrieve_done=%d sync_retrieve_failed=%d box_mon_failed=%d",
            seen.capture or 0, seen.box_mon or 0, seen.stats_cache or 0, seen.party_mon or 0,
            seen.sync_retrieve_done or 0, seen.sync_retrieve_failed or 0, seen.box_mon_failed or 0))
    return true, "caught " .. key
end

-- D-3: A runs from its first encounter (no_catch -> dead zone); B then catches there and the
-- server retires the catch (force_faint + memorialize).
function scenarios.deadzone_new()
    if not wait_go() then return false, "no go-file" end
    if D.player == "a" then
        local phase = hunt("run")
        if phase ~= "escaped" then return false, "hunt ended " .. phase end
        if not wait_until(function() return seen.no_catch end, 30, "no_catch") then return false, "no_catch never sent" end
        log("NO_CATCH sent")
        log_party("PARTY")
        -- Stay up while B plays (the server's dead-zone msgbox lands here too); bounded.
        wait_partner_done(420)
        return true, "ran from the first encounter"
    end
    local phase = hunt("catch")
    if phase ~= "caught" then return false, "hunt ended " .. phase end
    local key = new_key()
    if not key then return false, "party grew but no new key" end
    log_party("PARTY")
    log("CAUGHT " .. key)
    local fainted, retired, memorial = nil, nil, nil
    wait_until(function()
        local in_party = false
        for _, m in ipairs(party_keys()) do
            if m.key == key then
                in_party = true
                if m.hp == 0 and not fainted then fainted = frame; log("FAINTED " .. key .. " hp=0 in party slot " .. m.slot) end
            end
        end
        if fainted and not in_party and not retired then
            retired = frame
            log("RETIRED " .. key .. " left the party")
            local sram = deps.read_range(0, 0x8000, "CartRAM")
            local box = reads.read_sram_box(sram, 11)
            for _, m in ipairs(box or {}) do if reads.key(m) == key then memorial = true end end
            log("MEMORIAL " .. key .. " in box 12: " .. tostring(memorial == true))
        end
        return (retired or (seen.memorialize_failed and fainted)) and true or nil
    end, 180, "force_faint + memorialize")
    log_party("PARTY")
    log(fmt("SEEN capture=%d force_faint=%d memorialize=%d memorialize_done=%d memorialize_failed=%d",
            seen.capture or 0, seen.force_faint or 0, seen.memorialize or 0, seen.memorialize_done or 0, seen.memorialize_failed or 0))
    if not fainted then return false, "the dead-zone capture was never force-fainted" end
    return true, "dead-zone catch " .. key .. (retired and " retired" or " fainted only")
end

local scen = scenarios[D.scenario]
if not scen then finish(false, "no gen1_new scenario " .. tostring(D.scenario)) end
local co = coroutine.create(scen)
local timeout = D.timeout_frames or 150000
while true do
    local ok, pass, msg = coroutine.resume(co)
    if not ok then finish(false, "scenario error: " .. tostring(pass)) end
    if coroutine.status(co) == "dead" then finish(pass, msg) end
    step(nil)
    if frame % 3600 == 0 then log(fmt("heartbeat f=%d party=%d connected=%s", frame, memory.read_u8(ram.wPartyCount, "System Bus"), tostring(C.connected()))) end
    if frame > timeout then finish(false, "scenario timeout after " .. timeout .. " frames") end
end
