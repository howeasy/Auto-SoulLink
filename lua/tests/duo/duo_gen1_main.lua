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
-- A6 storage receipts, declared before the tees that fill them. `storage_tx` is every
-- party_to_box/box_to_party the client SENDS, in order; `storage_rx` every box_mon/party_mon it
-- RECEIVES; `release_seen` every RELEASE_SEEN the client LOGS (lua/gen1/client.lua:571-592: a
-- standalone from_box RemovePokemon has no wire event, so the log line is the only receipt), each
-- stamped with how many storage sends preceded it — that stamp is what proves no release fired
-- during the WITHDRAW.
local storage_tx, storage_rx, release_seen = {}, {}, {}

-- Tee the client's own log lines into the result file.
console.log = function(s)
    _console_log(s)
    local released = tostring(s):match("RELEASE_SEEN key=(%S+)")
    if released then release_seen[#release_seen + 1] = { key = released, after = #storage_tx } end
    if logf then logf:write("[client] " .. tostring(s) .. "\n"); logf:flush() end
end

local Entry = dofile(ROOT .. "/lua/gen1/entry.lua")
local C = require("connector")
local H = require("hud")
local json = dofile(ROOT .. "/lua/json_codec.lua")
local safety = dofile(ROOT .. "/lua/gen1_write_safety.lua")
local Hunt = dofile(ROOT .. "/lua/tests/gen1_rb_hunt_inputs.lua")
local Center = dofile(ROOT .. "/lua/tests/gen1_rb_center_inputs.lua")
local Driver = dofile(ROOT .. "/lua/tests/gen1_battle_driver.lua")
local Play = dofile(ROOT .. "/lua/tests/gen1_scripted_play.lua")
-- A6 (S-6, W-5): Bill's PC by play. The module's own header carries the pret citation for
-- every screen it drives (PC hidden event, menu geometry, deposit/withdraw/release/change box,
-- wCurrentBoxNum) -- read it there, nothing is restated here. It takes an ops list rather than
-- a fixed terminal, so it is NOT in gen1_scripted_play's MODULES table: this body loads it the
-- way it loads gen1_rb_center_inputs.lua above and drives it like the hunt route.
local PC = dofile(ROOT .. "/lua/tests/gen1_rb_pc_inputs.lua")
-- The MODULE, not the built instance: only the module carries the mailbox constants
-- (lua/gen1/panel.lua:14,33) that explode_new's in-battle VBlank probe reads.
local Panel = dofile(ROOT .. "/lua/gen1/panel.lua")

log("duo instance " .. D.player .. " scenario=" .. D.scenario .. " game=" .. D.game)
log(fmt("attempt %d of %d", D.attempt or 1, D.max_attempts or 2))
pcall(function() client.speedmode(D.speed or 1600) end)

local title, header = Entry.detect_title(function(a) return memory.read_u8(a, "ROM") end)
if not title then finish(false, "not a Gen 1 cartridge (header " .. tostring(header) .. ")") end
local deps = Entry.bizhawk_deps()

-- ── S-7 (plan A12): dump the cartridge's save bytes so the SAVE is proven physically ──
-- WHERE: the pinned save_witness site is SaveMenu.save + capture_offset 3
-- (data/games/gen1_rby/engine_signals.json:129-135) — the instruction after `call SaveGameData`
-- returns (pret engine/menus/save.asm:165-166, SaveGameData at :290-295, .cache/pret/pokered
-- 405b624). At callback time the cartridge RAM therefore already holds exactly what the save
-- wrote. Reading later from the scenario coroutine would read it frames afterwards, once the
-- engine is free to touch SRAM again, which proves nothing about the save itself.
-- DOMAIN: "CartRAM" — BizHawk's flat 0x8000 image of the cartridge's four 0x2000 SRAM banks
-- (lua/memory_gb.lua:52-56; lua/gen1/entry.lua:54-64 reads the same image).
-- SLICE: 0x498..0x7FFF = 0x7B68 bytes, the slice docs/gen1_requirements.md:72 pins for S-7.
-- It starts past sSpriteBuffer0/1/2 (3 * SPRITEBUFFERSIZE = 3 * 7*7*8 = 3 * 0x188 = 0x498;
-- pret ram/sram.asm:1-5, constants/gfx_constants.asm:14) — pic-decompression scratch the engine
-- rewrites constantly and the save does not own.
local WITNESS_FROM, WITNESS_TO = 0x498, 0x8000
local witness_saves = 0
local function dump_save_witness()
    witness_saves = witness_saves + 1
    -- repo-relative in the log line: ROOT (D.wt) contains spaces, and a `path=` value with a
    -- space cannot be parsed off the log.
    local rel = fmt("patch/build/e2e_%s_%s_%d_witness.bin", D.scenario, D.player, D.attempt or 1)
    local out = {}
    -- Per-byte read_u8 rather than memory.read_bytes_as_array: the array's index base is not
    -- pinned for the Gambatte core here (†UNVERIFIED), while read_u8 is what every other
    -- CartRAM read in this tree uses. The chars go into a table and are joined ONCE — no
    -- per-byte string concatenation. 0x7B68 reads, once per SAVE, once per scenario half.
    for off = WITNESS_FROM, WITNESS_TO - 1 do
        out[#out + 1] = string.char(memory.read_u8(off, "CartRAM"))
    end
    local blob = table.concat(out)
    local wf = assert(io.open(ROOT .. "/" .. rel, "wb"), "cannot open " .. rel)
    wf:write(blob)   -- overwritten on every save, so the file is this attempt's FINAL save
    wf:close()
    log(fmt("SAVE_WITNESS_DUMP path=%s bytes=%d saves=%d frame=%d",
            rel, #blob, witness_saves, emu.framecount()))
end
-- Tee the one bus hook signals.lua registers for this site (lua/gen1/signals.lua:230, named
-- "SLink-gen1-" .. kind) so the dump runs INSIDE that callback, before the queued signal drains
-- in frame_end. The client's own save_witness arm runs at drain time and only flushes BizHawk's
-- SaveRAM file (lua/gen1/client.lua:651-652), so hooking here keeps lua/gen1/ untouched.
local _on_bus_exec = deps.on_bus_exec
deps.on_bus_exec = function(fn, addr, name, dom)
    if name == "SLink-gen1-save_witness" then
        local fire = fn
        fn = function()
            -- GATE: "the callback ran" is NOT evidence the site validated. signals.lua's `fire`
            -- returns nothing and swallows every rejection (lua/gen1/signals.lua:202-226: early
            -- `return` when closed/failed, on the wrong hLoadedROMBank, or on a filter; the PC
            -- and expected-bytes assertions are pcall'd into self.failure rather than raised).
            -- The one observable that means "validated" is the queue: :219 appends to `pending`
            -- only once every check has passed. So dump iff `pending` grew by exactly one
            -- save_witness entry across this call. The signals instance is reached through
            -- SLINK_GEN1_CLIENT (:182, the same global lua/gen1/run.lua:42 sets) because the
            -- `gclient` local is declared below this tee (:157) and the instance itself only
            -- exists after gclient:start() (lua/gen1/client.lua:1005).
            local sigs = SLINK_GEN1_CLIENT and SLINK_GEN1_CLIENT.signals
            local before = sigs and #sigs.pending or 0
            fire()
            local why
            if not sigs then
                why = "no-signals-instance"
            elseif #sigs.pending ~= before + 1 then
                why = fmt("pending-%d-to-%d", before, #sigs.pending)
            elseif sigs.pending[#sigs.pending].kind ~= "save_witness" then
                why = "kind-" .. tostring(sigs.pending[#sigs.pending].kind)
            end
            if why then
                log("SAVE_WITNESS_DUMP_SKIPPED why=" .. why)
                return
            end
            local dok, derr = pcall(dump_save_witness)
            if not dok then log("SAVE_WITNESS_DUMP_FAIL " .. tostring(derr)) end
        end
    end
    return _on_bus_exec(fn, addr, name, dom)
end

local rom_sha1 = gameinfo.getromhash():lower()
H.init({ screen_w = 160, screen_h = 144 })
C.init(SLINK_HOST, tonumber(SLINK_PORT))

-- Wire receipts: every line the client sends and every command it receives.
local seen = {} -- event/cmd name -> count
local sent_events, received_commands = {}, {}
local _send = C.send
C.send = function(line)
    local ok, msg = pcall(json.decode, line)
    local name = ok and type(msg) == "table" and msg.event or "?"
    seen[name] = (seen[name] or 0) + 1
    if name == "hello" or name == "capture" or name == "trade_offer" or name == "menu_result" or name == "trade_done"
       or name == "faint" then
        sent_events[name] = msg
    end
    if name == "party_to_box" or name == "box_to_party" then
        storage_tx[#storage_tx + 1] = { event = name, key = msg and msg.key }
    end
    if name ~= "tick" then log("TX " .. (line:sub(1, 220))) end
    if name == "faint" and D.player == "b" and
       (D.scenario == "linked_faint_active_new" or D.scenario == "explode_new") then
        log("ENGINE_BATTLE_FAINT " .. tostring(msg.key)) -- client sends only from battle_faint site in this scenario
    end
    return _send(line)
end

local gclient, parts = Entry.build({ root = ROOT, io = deps, net = C, hud = H, title = title, player = D.player,
                                     rom_sha1 = rom_sha1, log = function(s) console.log(s) end })
local _handle = gclient.handle_command
gclient.handle_command = function(self, cmd)
    local c = cmd and cmd.cmd or "?"
    seen[c] = (seen[c] or 0) + 1
    if c == "trade_mask" or c == "show_menu" or c == "apply_trade" or c == "force_faint"
       or c == "force_explode" then
        received_commands[c] = cmd
    end
    if c == "box_mon" or c == "party_mon" then
        storage_rx[#storage_rx + 1] = { cmd = c, key = cmd.key }
    end
    if c ~= "noop" then
        log("RX " .. c .. (cmd.key and (" key=" .. tostring(cmd.key)) or "") .. (cmd.text and (" text=" .. tostring(cmd.text)) or ""))
    end
    if c == "game_over" then log("GAME_OVER RX game_over") end
    if c == "hud_show" and cmd.text and cmd.text:find("WRONG SAVE", 1, true) then
        received_commands.wrong_save = cmd
        log("WRONG_SAVE_HUD " .. cmd.text)
    end
    return _handle(self, cmd)
end
local okc, errc = pcall(function() gclient:start() end)
if not okc then finish(false, "client refused to start: " .. tostring(errc)) end
SLINK_GEN1_CLIENT = gclient
log(fmt("client built: title=%s player=%s rom=%s -> %s:%s", title, D.player, rom_sha1:sub(1, 8), SLINK_HOST, tostring(SLINK_PORT)))

local reads, ram = parts.reads, parts.profile.ram
local battle_site_keys = {}
local original_on_signal = gclient.on_signal
gclient.on_signal = function(self, sig)
    if sig.kind == "bag_received" then
        seen.bag_received = (seen.bag_received or 0) + 1
        log(fmt("BAG_RECEIVED item=%d quantity=%d", sig.point.item, sig.point.quantity))
    end
    if sig.kind == "battle_faint" then
        local party = reads.read_party()
        local slot = sig.point and sig.point.active_slot
        local mon = party and slot and party[slot + 1]
        if mon then
            local key = reads.key(mon)
            battle_site_keys[key] = (battle_site_keys[key] or 0) + 1
            log(fmt("BATTLE_FAINT_SITE %s slot=%d battle_hp=%d", key, slot, sig.point.battle_hp))
        end
    end
    return original_on_signal(self, sig)
end
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
local play = Play.new(ROOT, title, D.player, { log = log })
local booted, settled = false, 0
if D.cold_boot then
    -- gen1_scripted_play.lua:116-132 uses the OverworldLoop checkpoint in the empty-party
    -- bedroom; requiring a nonempty party here would skip the entire pre-ball window.
    local ok, why = pcall(function() play.boot(step, overworld_ok, 20000) end)
    if not ok then finish(false, "cold NEW GAME failed: " .. tostring(why)) end
    booted = true
else
    for f = 1, 6000 do
        local count = memory.read_u8(ram.wPartyCount, "System Bus")
        local ok = count >= 1 and count <= 6 and overworld_ok()
        settled = ok and settled + 1 or 0
        if settled >= 30 then booted = true break end
        step((not ok and f % 16 < 2) and { A = true } or nil)
    end
end
if not booted then
    client.screenshot(ROOT .. "/patch/build/e2e_" .. D.scenario .. "_" .. D.player .. "_bootfail.png")
    finish(false, "never booted into the overworld from the battery save (frame " .. frame .. ")")
end
local map = reads.read_map()
log(fmt("booted at frame %d party=%d map=%d (%d,%d)", frame, memory.read_u8(ram.wPartyCount, "System Bus"), map.map, map.x, map.y))
if D.cold_boot then
    for _ = 1, 600 do
        if sent_events.hello then break end
        step({})
    end
    local hello = sent_events.hello
    if not hello then finish(false, "cold bedroom never sent a production hello") end
    log("BALL_HELLO " .. json.encode({ot_id=hello.ot_id, has_pokeballs=hello.has_pokeballs,
        ball_count=hello.ball_count, party_count=#hello.party, map=map.map}))
end

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
-- Battle-plan level (inside the hunt module's coroutine, or from a driver kept alive PAST the
-- hunt via options.keep_driver): set the pad directly, THEN hand the same buttons up so
-- route.step can return them to the scenario. Nothing advances a frame between this call and
-- the scenario's later yield_frame(buttons)/step(nil) (frameadvance happens exactly once, in the
-- main loop's step() at the bottom of this file), so that later re-set of the identical value is
-- a harmless no-op, not a second real press. A driver resumed by the MAIN loop after the hunt
-- returns (keep_driver) never reaches that later yield_frame at all -- setting the pad here is
-- the ONLY place its presses land. Before this fix they were dropped entirely: the main loop's
-- step(nil) ignores whatever coroutine.resume(co) yields (receipt:
-- tests/fixtures/gen1/receipts/linked_faint_active_new_b_result.txt:81, "move menu not entered").
local function yield_buttons(buttons) joypad.set(buttons or {}); coroutine.yield(buttons or {}) end
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
local function file_contains(p, marker)
    local file = io.open(p, "r")
    if not file then return false end
    local text = file:read("*a");file:close()
    return text:find(marker, 1, true) ~= nil
end
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
local symbols = play.symbols
local function rd(addr) return memory.read_u8(addr, "System Bus") end
local function hex4(addr) return fmt("%02X%02X%02X%02X", rd(addr), rd(addr + 1), rd(addr + 2), rd(addr + 3)) end
local rom = parts.profile.rom
local function hunt(mode, options)
    options = options or {}
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
                                                   mode = mode, log = log, switch_slot = options.switch_slot,
                                                   move_slot = options.move_slot, fainted = options.fainted,
                                                   start_active = options.start_active })
    local last_phase, n = nil, 0
    local terminal = { caught = true, escaped = true, ["out-of-balls"] = true, ["hunt-exhausted"] = true,
                       ["linked-fainted"] = true, ["linked-active-menu"] = true,
                       ["linked-survived-3-battles"] = true,
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
            if not options.keep_driver then driver.close() end
            log(fmt("HUNT %s after %d frames, %d encounter(s)", phase, n, route.encounters))
            return phase, options.keep_driver and driver or nil
        end
        yield_frame(buttons)
    end
end
local function new_key()
    for _, m in ipairs(party_keys()) do if not boot_keys[m.key] then return m.key, m end end
    return nil
end

local function game_save(tag)
    -- gen1_rb_save_inputs.lua drives START -> SAVE -> YES with ordinary buttons,
    -- and gen1_scripted_play.lua:138-165 supplies its read-only point/handshake.
    -- WRAM party/current-box changes only enter sPartyData/sCurBoxData on SAVE
    -- (pret engine/menus/save.asm:208-295), so the disk PYDEC oracle needs this step.
    if not wait_until(overworld_ok, 30, "overworld checkpoint before SAVE") then
        return false, "not at a safe overworld SAVE checkpoint"
    end
    local receipts = play.run(yield_frame, {"save"}, function(_, phase)
        log("SAVE_PHASE " .. tag .. " " .. phase)
    end, 3600)
    if not receipts.save then return false, "normal-button SAVE did not finish" end
    log(fmt("SAVE_WITNESS %s frames=%d", tag, receipts.save))
    frames(30) -- let the client's SaveMenu.save hook flush CartRAM before exit
    return true
end

-- The ordinary-button walk from Route 1's grass to the Viridian Center, shared by the trade
-- lane (which stops at the receptionist) and the A6 PC lane (which walks on to the PC from
-- there). `linked_hp` is the route's optional in-battle liveness probe for a linked party mon;
-- without it the route checks the starter, which is what the PC lane wants when the linked half
-- is already a memorial. Returns true, or false + reason.
local function walk_to_center(linked_hp)
    local function require_route(label, ok, detail)
        if not ok then error(label .. ": " .. tostring(detail), 0) end
    end
    local route = Center.new({
        read = rd, ram = ram, row = function(off, n) return Center.row(rd, ram.wTileMap, off, n) end,
        frame = function() return frame end,
        log = log, invariant = require_route, check = require_route, start = "route1",
        menu_addr = {wTopMenuItemX=symbols.wTopMenuItemX, wTopMenuItemY=symbols.wTopMenuItemY},
        linked_hp = linked_hp,
    })
    local arrived = false
    for _ = 1, 20000 do
        local buttons, done = route.step()
        if done then arrived = true;break end
        yield_frame(buttons)
    end
    if not arrived or rd(ram.wCurMap) ~= Center.MAP.center or rd(ram.wXCoord) ~= 11 or rd(ram.wYCoord) ~= 3 then
        return false, fmt("Center walk stopped map=%d (%d,%d)", rd(ram.wCurMap), rd(ram.wXCoord), rd(ram.wYCoord))
    end
    log(fmt("CENTER_RECEPTIONIST map=%d (%d,%d)", rd(ram.wCurMap), rd(ram.wXCoord), rd(ram.wYCoord)))
    if not wait_until(overworld_ok, 30, "Center overworld checkpoint") then return false, "Center not overworld-safe" end
    return true
end

-- Drive one Bill's PC ops list to a terminal phase. Every press comes out of the driver — this
-- loop only hands it a read-only point and gives the frame back, exactly like the hunt loop.
-- Returns the terminal phase and the LAST extended point (box number / count / initialised flag
-- read back in the overworld, after the PC has written the active box home).
local function pc_drive(ops, tag)
    local driver = PC.new({ player = D.player }, {
        rd = rd, symbols = symbols, center = Center, ops = ops,
        log = function(line)
            local op, what = line:match("^PC op %d+ (%a+)%(%d+%) (%a+)")
            if what then log(fmt("PC_OP %s %s", op, what)) end
            log(line)
        end,
    })
    local last_phase, point = nil, nil
    for _ = 1, (D.pc_frames or 60000) do
        point = PC.extend_point(play.point(), rd, symbols)
        local buttons, phase = driver.step(nil, nil, point, emu.framecount())
        if phase ~= last_phase then
            last_phase = phase
            log(fmt("PC_PHASE %s %s @%d (%d,%d) party=%d box=%d count=%d init=%s", tag, phase,
                    emu.framecount(), point.x, point.y, point.party_count,
                    point.box_number, point.box_count, tostring(point.box_initialised)))
        end
        if PC.TERMINALS[phase] then return phase, point end
        yield_frame(buttons)
    end
    return "pc-timeout", point
end

-- ── Scenarios ────────────────────────────────────────────────────────────────────────
local scenarios = {}

-- D-2: no SaveRAM seed, no injected link or bag bit. The starter gift pair links on arrival
-- (server/state.py:1404-1408,1573-1628); the pre-ball gate suppresses faint propagation.
-- The route is the ordinary-button S-1/S-7 chain: New Game -> lab loss -> parcel -> SAVE.
-- The runner releases A's rival first while B holds before its own battle. That gives the
-- partner-HP check a stable baseline instead of comparing two simultaneously fought rivals.
function scenarios.ball_gate_new()
    if not D.cold_boot then return false, "ball gate did not launch a cold cartridge" end
    if not sent_events.hello or sent_events.hello.has_pokeballs or sent_events.hello.ball_count ~= 0 then
        return false, "bedroom hello already had Poké Balls"
    end
    if not wait_go() then return false, "no ball-gate go-file" end
    local parked = false
    local function lab_phase(_, phase)
        if phase == "rival-challenge-dialogue" and not parked then
            parked = true
            local hp = play.point().party_hp
            local party = reads.read_party()
            local starter = party and party[1]
            log("BALL_PRE_RIVAL " .. json.encode({player=D.player, hp=hp,
                key=starter and reads.key(starter) or "", capture_count=seen.capture or 0,
                gift=sent_events.capture and sent_events.capture.gift or false,
                faint_count=seen.faint or 0, ball_count=play.point().ball_count}))
            local marker = D.player == "a" and "ALLOW_A_RIVAL" or "ALLOW_B_RIVAL"
            if not wait_until(function() return file_contains(D.go_file, marker) end, 900, marker) then
                error("runner never released " .. D.player .. " rival battle", 0)
            end
            log("BALL_RELEASE_RIVAL " .. json.encode({player=D.player, hp=play.point().party_hp,
                force_faint=seen.force_faint or 0, memorialize=seen.memorialize or 0}))
        end
    end
    local lab = play.run(yield_frame, {"lab"}, lab_phase, 120000)
    if not lab.lab then return false, "lab route did not reach its loss terminal" end
    local pt = play.point()
    log("BALL_LAB " .. json.encode({player=D.player, result=pt.battle_result,
        hp=pt.party_hp, faint_count=seen.faint or 0, ball_count=pt.ball_count,
        has_pokeballs=gclient.has_pokeballs, force_faint=seen.force_faint or 0,
        memorialize=seen.memorialize or 0}))
    if not wait_until(function() return file_contains(D.go_file, "ALLOW_PARCEL") end,
                      900, "ALLOW_PARCEL") then return false, "runner never released parcel route" end
    log("BALL_AFTER_LABS " .. json.encode({player=D.player, hp=play.point().party_hp,
        force_faint=seen.force_faint or 0, memorialize=seen.memorialize or 0}))
    local parcel = play.run(yield_frame, {"parcel"}, function(name, phase)
        log("BALL_PHASE " .. name .. " " .. phase)
    end, 120000)
    if not parcel.parcel then return false, "parcel route did not reach first ball" end
    if not wait_until(function()
        return (seen.bag_received or 0) > 0 and gclient.has_pokeballs and play.point().ball_count > 0
    end, 60, "bag_received and positive bag readback") then
        return false, "bag_received did not activate the client's Poké Ball state"
    end
    log("BALL_FLIP " .. json.encode({player=D.player, signal_count=seen.bag_received,
        ball_count=play.point().ball_count, has_pokeballs=gclient.has_pokeballs}))
    -- gen1_rb_parcel_inputs.lua ends INSIDE the Mart purchase UI (first-ball-readback), so the
    -- SAVE checkpoint cannot hold yet; close it the way gen1_rb_route1_inputs.lua:62-66 does,
    -- B taps on the 16-frame cadence until the CPU checkpoint holds (first live run 2026-09-17
    -- timed out here on both cartridges).
    local closing = 0
    if not wait_until(function()
        if overworld_ok() then return true end
        closing = closing + 1
        if closing % 16 == 0 then yield_frame({B=true}); yield_frame({B=true}) end
        return nil
    end, 40, "close the Mart menu after the first ball") then
        return false, "Mart menu did not close after the first ball"
    end
    log("MART_CLOSED after " .. closing .. " frames")
    if not wait_until(function() return file_contains(D.go_file, "ALLOW_SAVE") end,
                      900, "ALLOW_SAVE") then return false, "runner never released normal SAVE" end
    local saved, why = game_save("ball_gate_new")
    if not saved then return false, why end
    log("BALL_SAVED " .. json.encode({player=D.player, hp=play.point().party_hp,
        party_count=play.point().party_count}))
    return true, "cold lab loss suppressed; bag site activated; normal SAVE witnessed"
end

local function link_prerequisite_failure(why)
    -- Preserve the exact game-RNG result so e2e_duo.py retries only a missed sole ball.
    if why == "hunt ended out-of-balls" then return why end
    return "link_new prerequisite failed: " .. tostring(why)
end

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
    local saved, why = game_save("link_new")
    if not saved then return false, why end
    return true, "caught " .. key
end

-- ── A4: the clause scenarios (D-5 type clause, D-4 species clause) ───────────────────
--
-- Both ride link_new's Route 1 body against a server started with --type-clause /
-- --species-clause. Everything asserted here is what the cartridge and THIS client's own
-- RX log can show; /api/status, links.json and events.json are the runner's half, which
-- reads the markers these bodies log.
--
-- Command names are the client's own handler (lua/gen1/client.lua:252 force_faint,
-- :273 memorialize, :278 gui_prompt, :284 play_sound, :290 unresolve_area).
-- The prompt literals are the server's:
--   server/state.py:1596-1618  the REJECTED half gets force_faint, memorialize,
--                              play_sound 26, gui_prompt "[x] " .. violation and
--                              unresolve_area; its PARTNER gets play_sound 22 (SE_BOO)
--                              and nothing else. Sound 22 is queued at exactly this one
--                              site in the whole server, so it is a safe verdict signal.
--   server/state.py:2634-2635  violation = "Type clause: shared <type names, sorted>"
--   server/state.py:1726-1738  the dupes reroll: gui_prompt "Dupes clause: <SPECIES> --
--                              reroll!" + unresolve_area, queued from the wild-battle-start
--                              tick (server/server.py:1815-1835, state.py:1739-1828).
--
-- Why Route 1 makes D-5 deterministic: its entire grass table is PIDGEY and RATTATA
-- (pret data/wild/maps/Route1.asm), Normal/Flying and Normal/Normal
-- (pret data/pokemon/base_stats/pidgey.asm:6, rattata.asm:6) -- any two catches here
-- always share Normal. Neither line evolves inside the level 2-5 band that table rolls,
-- so on this route "same evolution family" and "same species byte" are the same test,
-- which is what lets B recognise A's duplicate from its own WRAM below.
local clause_rx = {}
local function clause_watch()
    -- The file-wide tee above keeps only a handful of commands and drops `sound`, and every
    -- other scenario shares it; the clause receipts are membership tests over cmd + sound +
    -- text, so wrap the (already wrapped) handler once more here instead of widening it.
    local prev = gclient.handle_command
    gclient.handle_command = function(self, cmd)
        clause_rx[#clause_rx + 1] = { cmd = cmd and cmd.cmd, key = cmd and cmd.key,
                                      text = cmd and cmd.text, sound = cmd and cmd.sound,
                                      area_id = cmd and cmd.area_id }
        return prev(self, cmd)
    end
end
-- Membership, not order: the LAST command matching `name` (and `test`) -- the newest one, so a
-- second reroll prompt logs itself and not its predecessor -- plus how many matched in all.
local function clause_got(name, test)
    local hit, n = nil, 0
    for _, c in ipairs(clause_rx) do
        if c.cmd == name and (not test or test(c)) then n = n + 1; hit = c end
    end
    return hit, n
end
local function dupes_prompt(c)
    return (c.text and c.text:find("Dupes clause:", 1, true) == 1) or false
end
-- The unlock that matters is the one for the area this scenario is fought on: Route 1 is map
-- 0x0C -> area_id "route_1" (data/games/gen1_rby/area_map.json:6). Any other unresolve_area on
-- the wire (a partner's area, a retry suppression elsewhere) is NOT the type-clause receipt,
-- and a command with no area_id at all is not one either.
local function route1_unlock(c) return c.area_id == "route_1" end

-- D-5: link_new's body with the server's --type-clause. Both catches share Normal, so the
-- LATER capturer is rejected at link formation and Route 1 stays pending for it. Which half
-- that is falls out of the game's encounter RNG, so both halves run this ONE body and read
-- their verdict off the wire: the rejected half is the one that receives force_faint for its
-- own key, its partner the one that receives SE_BOO. Deterministic: one catch each, no retry.
function scenarios.type_clause_new()
    if not wait_go() then return false, "no go-file" end
    clause_watch()
    local phase = hunt("catch")
    if phase ~= "caught" then return false, "hunt ended " .. phase end
    local key, mon = new_key()
    if not key then return false, "party grew but no new key" end
    log_party("PARTY")
    log("CAUGHT " .. key)
    log(fmt("CLAUSE_CAPTURE %s species=%d level=%d", key, mon.species, mon.level))
    -- The server can only compare once BOTH halves have captured, so this wait spans the
    -- partner's whole hunt.
    local verdict = wait_until(function()
        if clause_got("force_faint", function(c) return c.key == key end) then return "rejected" end
        if clause_got("play_sound", function(c) return c.sound == 22 end) then return "accepted" end
        return partner_done() and "partner-gone" or nil
    end, 900, "the server's type-clause verdict")
    if verdict ~= "rejected" and verdict ~= "accepted" then
        return false, "no type-clause verdict (" .. tostring(verdict) .. ")"
    end
    if verdict == "rejected" then
        local prompt = clause_got("gui_prompt", function(c)
            return (c.text and c.text:find("[x] Type clause: shared", 1, true) == 1) or false
        end)
        local memo = clause_got("memorialize", function(c) return c.key == key end)
        local fail_sfx = clause_got("play_sound", function(c) return c.sound == 26 end)
        local unres = clause_got("unresolve_area", route1_unlock)
        log("TYPE_CLAUSE " .. json.encode({player = D.player, verdict = "rejected", key = key,
            species = mon.species, prompt = prompt and prompt.text or "",
            memorialize = memo ~= nil, sound26 = fail_sfx ~= nil,
            unresolve_area = unres and unres.area_id or ""}))
        if not prompt then return false, "rejected half never got the [x] Type clause prompt" end
        if not prompt.text:find("Normal", 1, true) then
            return false, "type-clause prompt did not name Normal: " .. prompt.text
        end
        if not memo then return false, "rejected capture was never memorialized" end
        if not fail_sfx then return false, "rejected half never got play_sound 26" end
        if not unres then return false, "rejected half never got unresolve_area for route_1" end
        -- The mon leaves the party and lands in Box 12 at HP 0, the same receipt
        -- deadzone_new takes: force_faint zeroes it, memorialize moves it to sBox12
        -- (lua/gen1/boxes.lua:460-517, ram/sram.asm:44-49 -> box index 11).
        local retired, memorial_hp = nil, nil
        wait_until(function()
            for _, m in ipairs(party_keys()) do if m.key == key then return nil end end
            local sram = deps.read_range(0, 0x8000, "CartRAM")
            for _, m in ipairs(reads.read_sram_box(sram, 11) or {}) do
                if reads.key(m) == key then retired, memorial_hp = true, m.hp end
            end
            return retired or (seen.memorialize_failed and true) or nil
        end, 240, "the rejected capture to reach Box 12")
        log(fmt("MEMORIAL %s box12=%s hp=%s memorialize_done=%d memorialize_failed=%d",
                key, tostring(retired == true), tostring(memorial_hp),
                seen.memorialize_done or 0, seen.memorialize_failed or 0))
        if not retired then return false, "rejected capture never reached Box 12" end
        if memorial_hp ~= 0 then
            return false, fmt("Box 12 memorial hp=%s, expected 0", tostring(memorial_hp))
        end
    else
        -- The accepted half keeps its capture pending (quarantined in its current box by the
        -- capture-time box_mon, state.py:1554-1557) -- no link, so no party_mon ever follows.
        local ff = clause_got("force_faint")
        local tp = clause_got("gui_prompt", function(c)
            return (c.text and c.text:find("Type clause", 1, true)) and true or false
        end)
        local unres = clause_got("unresolve_area", route1_unlock)
        log("TYPE_CLAUSE " .. json.encode({player = D.player, verdict = "accepted", key = key,
            species = mon.species, force_faint = ff ~= nil, type_prompt = tp and tp.text or "",
            unresolve_area = unres and unres.area_id or ""}))
        if ff then return false, "the accepted half was force-fainted" end
        if tp then return false, "the accepted half got the rejection prompt" end
    end
    frames(120)
    log_party("PARTY")
    log(fmt("SEEN capture=%d box_mon=%d party_mon=%d force_faint=%d memorialize=%d",
            seen.capture or 0, seen.box_mon or 0, seen.party_mon or 0,
            seen.force_faint or 0, seen.memorialize or 0))
    local saved, why = game_save("type_clause_new")
    if not saved then return false, why end
    return true, "type clause " .. verdict .. " " .. key
end

-- D-4: link_new's body with the server's --species-clause, ORDERED. A catches first; the
-- runner writes "A_PENDING species=<n>" into B's go-file once /api/status shows A's pending
-- capture on route_1 (n = the species byte A logs as PENDING_CAPTURE below, so both halves
-- compare the same WRAM numbering), and only then is B released. B's first encounter
-- therefore always meets a partner pending capture, which is check 2 of
-- server/state.py:1788-1800.
--
-- B has exactly ONE free look: a RUN from a NON-duplicate sends no_catch
-- (lua/gen1/client.lua:553) and dead-zones Route 1, and only the notified duplicate is
-- exempt (state.py:1866-1872). So B runs ONLY from A's family and otherwise catches, and it
-- decides that from its OWN cartridge (wEnemyMonSpecies against the A_PENDING species) the
-- moment the battle starts -- see the loop for why the server's prompt cannot be the trigger
-- without racing the battle menu. The prompt is then required after the fact: run but no
-- prompt = the server missed the reroll = FAIL. Roughly half the time (Route 1's table is 6
-- Pidgey and 4 Rattata slots) the first encounter is A's family and the reroll branch runs; the
-- other half B just catches the other species, the link forms and the reroll goes
-- unobserved -- the run still PASSES, and carries "reroll_unobserved" in its message so the
-- runner can retry the whole scenario with fresh state.
function scenarios.species_clause_new()
    if not wait_go() then return false, "no go-file" end
    clause_watch()
    if D.player == "a" then
        local phase = hunt("catch")
        if phase ~= "caught" then return false, "hunt ended " .. phase end
        local key, mon = new_key()
        if not key then return false, "party grew but no new key" end
        log_party("PARTY")
        log("CAUGHT " .. key)
        log(fmt("PENDING_CAPTURE %s species=%d level=%d", key, mon.species, mon.level))
        -- Hold while B hunts: the link only forms on B's valid catch, and this side's half of
        -- that sync is the party_mon un-quarantine ACK (same wait as link_new).
        wait_until(function()
            return (seen.sync_retrieve_done or seen.sync_retrieve_failed or seen.box_mon_failed)
                   and true or partner_done()
        end, 900, "B's catch to link this pending capture")
        frames(120)
        log_party("PARTY")
        log("SPECIES_CLAUSE " .. json.encode({player = "a", key = key, species = mon.species,
            capture = seen.capture or 0, box_mon = seen.box_mon or 0,
            party_mon = seen.party_mon or 0, force_faint = seen.force_faint or 0,
            sync_retrieve_done = seen.sync_retrieve_done or 0}))
        local saved, why = game_save("species_clause_new_a")
        if not saved then return false, why end
        return true, "A pending " .. key
    end

    if not wait_until(function() return file_contains(D.go_file, "A_PENDING") end, 900,
                      "A_PENDING from the runner") then
        return false, "runner never released B (A_PENDING)"
    end
    local gof = io.open(D.go_file, "r")
    local gotext = gof and gof:read("*a") or ""
    if gof then gof:close() end
    local dupe = tonumber(gotext:match("A_PENDING species=(%d+)") or "")
    log("A_PENDING species=" .. tostring(dupe))
    if not dupe then return false, "A_PENDING carried no species" end

    -- Pace Route 1's grass to the next encounter. gen1_rb_hunt_inputs does this too, but its
    -- catch-or-run mode is fixed when the route is BUILT (gen1_rb_hunt_inputs.lua:68) while
    -- the reroll is only knowable once the foe is on screen -- so walk here, decide, and hand
    -- the battle that is ALREADY up to hunt(): a route built mid-battle starts its plan on the
    -- first step that sees wIsInBattle == 1 (gen1_rb_hunt_inputs.lua:212-219), so the split
    -- costs nothing. Target order (x before y) and the close-text tap are the module's own
    -- (gen1_rb_hunt_inputs.lua:23-31,243-252).
    local target = 1
    local function pace_grass()
        for _ = 1, (D.hunt_frames or 90000) do
            local p = play.point()
            if p.battle == 1 then return true end
            if p.battle ~= 0 then return false, fmt("battle flag %d while pacing", p.battle) end
            if p.font_loaded or p.joy_ignore ~= 0 then
                yield_frame({B = frame % 16 < 2})
            elseif p.map ~= 0x0C then
                return false, fmt("left Route 1 (map %d)", p.map)
            else
                local t = Hunt.GRASS[target]
                if p.x == t[1] and p.y == t[2] then target = 3 - target; t = Hunt.GRASS[target] end
                local b = {}
                if p.x < t[1] then b.Right = true elseif p.x > t[1] then b.Left = true
                elseif p.y < t[2] then b.Down = true elseif p.y > t[2] then b.Up = true end
                yield_frame(b)
            end
        end
        return false, "no encounter while pacing the grass"
    end

    local caught_key, rerolls = nil, 0
    for battle = 1, 4 do
        -- The cursor is taken BEFORE the encounter exists. The server queues the dupes prompt
        -- from the wild-battle-start tick (server/server.py:1815-1834 -> state.py:1726-1738),
        -- and the client drains the reply queue on every tick (lua/gen1/client.lua:1038-1051),
        -- so the prompt can land on ANY of the frames between InitWildBattle and the
        -- enemy-data read below -- a cursor taken after them would swallow the very prompt
        -- this loop then demands, and the post-RUN check would fail on a healthy run.
        local _, before = clause_got("gui_prompt", dupes_prompt)
        local paced, why = pace_grass()
        if not paced then return false, why end
        -- InitWildBattle sets wIsInBattle and then calls LoadEnemyMonData with no DelayFrame
        -- between them (pret engine/battle/core.asm:6695-6698), so the foe is live on the next
        -- frame boundary; four frames of margin make a stale read impossible.
        frames(4)
        local foe = wait_until(function()
            local p = Hunt.extend_point(play.point(), rd, symbols)
            local sp = reads.read_battle().enemy_species
            return (sp ~= 0 and p.enemy_max_hp ~= 0 and p.enemy_hp == p.enemy_max_hp) and sp or nil
        end, 30, "the foe's species")
        if not foe then return false, "wild battle never loaded an enemy mon" end
        log(fmt("ENCOUNTER %d species=%d dupe_of_a=%s", battle, foe, tostring(foe == dupe)))
        -- The route is handed the battle IMMEDIATELY, before its first DisplayBattleMenu:
        -- the driver counts that site from the frame it is built and D.wait_menu only accepts
        -- a LATER execution (gen1_battle_driver.lua:110-118), so idling here to wait for the
        -- server's prompt first would race the menu and hang the plan. The decision is the
        -- cartridge's own species byte; the server's prompt is then ACCOUNTED FOR below,
        -- where a missing one fails the scenario rather than steering it.
        if foe ~= dupe then
            local caught = hunt("catch")
            if caught ~= "caught" then return false, "hunt ended " .. caught end
            caught_key = new_key()
            if not caught_key then return false, "party grew but no new key" end
            break
        end
        local ran = hunt("run")
        if ran ~= "escaped" then return false, "reroll battle ended " .. ran end
        -- Back in the overworld nothing is waiting on a button, so this window is free.
        local prompt, after = nil, before
        for _ = 1, 600 do
            prompt, after = clause_got("gui_prompt", dupes_prompt)
            if after > before then break end
            yield_frame()
        end
        if after == before then
            return false, fmt("no dupes-clause prompt for species %d (A's family)", foe)
        end
        rerolls = rerolls + 1
        local unres = clause_got("unresolve_area")
        log(fmt("REROLL_SEEN species=%d prompt=%s", foe, prompt.text))
        log(fmt("REROLL_RAN no_catch=%d unresolve_area=%s", seen.no_catch or 0,
                unres and (unres.area_id or "?") or "none"))
    end
    if not caught_key then return false, "B never landed a non-duplicate catch" end
    log_party("PARTY")
    log("CAUGHT " .. caught_key)
    wait_until(function()
        return (seen.sync_retrieve_done or seen.sync_retrieve_failed or seen.box_mon_failed)
               and true or partner_done()
    end, 240, "post-link party sync or partner")
    frames(120)
    log_party("PARTY")
    local path = rerolls > 0 and "reroll_observed" or "reroll_unobserved"
    log("PATH " .. path)
    log("SPECIES_CLAUSE " .. json.encode({player = "b", key = caught_key, dupe_species = dupe,
        rerolls = rerolls, path = path, no_catch = seen.no_catch or 0,
        capture = seen.capture or 0, force_faint = seen.force_faint or 0,
        party_mon = seen.party_mon or 0, sync_retrieve_done = seen.sync_retrieve_done or 0}))
    local saved, why = game_save("species_clause_new_b")
    if not saved then return false, why end
    return true, path .. ": B linked " .. caught_key .. " after " .. rerolls .. " reroll(s)"
end

-- C-2/C-1: the first A instance is deliberately killed by the runner AFTER the
-- source game's normal SAVE. B stays online; replacement A instances use the same
-- clean Red ROM and either the flushed Red SaveRAM or an independently played Red save.
function scenarios.reconnect_new()
    if D.phase == "initial" then
        local linked, why = scenarios.link_new()
        if not linked then return false, link_prerequisite_failure(why) end
        local key = new_key()
        if not key then return false, "linked member missing before reconnect kill" end
        log("RECONNECT_READY " .. D.player .. " linked_key=" .. key)
        if D.player == "a" then
            while true do yield_frame() end -- runner kills ONLY this EmuHawk process
        end
        if not wait_until(function() return file_contains(D.go_file, "B_DONE") end, 600,
                          "B_DONE after A's reconnect legs") then return false, "B never got reconnect completion" end
        return true, "B remained online through both A relaunches"
    end
    if D.phase ~= "same_save" and D.phase ~= "wrong_save" then
        return false, "unknown reconnect phase " .. tostring(D.phase)
    end
    if not wait_until(function() return (seen.hello or 0) >= 1 end, 120, "relaunch hello") then
        return false, "relaunch did not hello from a live save"
    end
    local party = reads.read_party()
    if not party or #party < 1 then return false, "relaunch save has no readable party" end
    local found = false
    for _, mon in ipairs(party) do if D.expected_key ~= "" and reads.key(mon) == D.expected_key then found = true end end
    log(fmt("RECONNECT_HELLO %s count=%d ot_id=%d linked=%s",
            D.phase, seen.hello or 0, reads.read_player_id(), tostring(found)))
    if D.phase == "same_save" and not found then return false, "same-save relaunch lost the linked key" end
    if D.phase == "wrong_save" then
        if not wait_until(function() return received_commands.wrong_save end, 120, "WRONG SAVE hud") then
            return false, "wrong-save relaunch did not receive WRONG SAVE hud"
        end
    end
    local finish_marker = D.phase == "same_save" and "A_DONE_SAME" or "A_DONE_WRONG"
    if not wait_until(function() return file_contains(D.go_file, finish_marker) end, 300,
                      finish_marker) then return false, "runner did not finish reconnect phase" end
    if (seen.hello or 0) ~= 1 or (seen.force_faint or 0) ~= 0 or (seen.box_mon or 0) ~= 0 then
        return false, "relaunch sent multiple hellos or received force_faint/box_mon"
    end
    frames(60)
    return true, D.phase .. " hello observed once"
end

-- T-3/T-4: reuse the real Route 1 capture/link, walk to the *native* receptionist, then
-- let the two cartridges perform one prompt and one apply. The Python runner checks SRAM
-- and the server's durable link after both instances have exited.
--
-- `decline` flips ONLY the partner's answer at the native confirm (T-3/T-4's NO/B subclause):
-- everything up to and including the offer is the same code, so the NO path cannot drift from
-- the YES path. patch/gen1/src/trade_prompt.asm:82-86 reads wCurrentMenuItem after YesNoChoice
-- (0 -> d=0 accept, else d=1 decline) and pret engine/menus/text_box.asm:310-312 sets
-- wCurrentMenuItem = 1 for a B press as well, so the NO row and the B-cancel exit are the same
-- engine answer; the row is driven here because it is observable in WRAM before the A press.
-- client.lua:817 maps that d=1 to `menu_result choice=0`, and server/state.py:662-673 clears
-- pending_trade and msgboxes BOTH sides without ever queueing apply_trade.
local function trade_scenario(decline)
    if not gclient.trade_enabled then return false, "SLINK TRADE patch was not detected" end
    local linked, why = scenarios.link_new()
    if not linked then return false, link_prerequisite_failure(why) end
    if (seen.sync_retrieve_done or 0) < 1 then return false, "linked capture was not returned to party" end
    local linked_key = new_key()
    local linked_slot
    for _, mon in ipairs(party_keys()) do if mon.key == linked_key then linked_slot = mon.slot end end
    if not linked_slot or #party_keys() ~= 2 then return false, "linked mon missing from two-mon party" end
    log_party("PRE_TRADE")

    local function tile_row(offset, length) return Center.row(rd, ram.wTileMap, offset, length) end
    local function tiles(text, offset) return Center.has_tiles(rd, ram.wTileMap, text, offset) end
    local linked_hp_addr = ram.wPartyMons + linked_slot * parts.profile.derived.party_struct_size + 1
    local walked, walk_why = walk_to_center(function()
        return rd(linked_hp_addr) * 256 + rd(linked_hp_addr + 1)
    end)
    if not walked then return false, walk_why end

    local function tap(key)
        yield_frame({[key]=true});yield_frame({[key]=true});yield_frame({});yield_frame({})
    end
    local function wait_tiles(label, pred, budget, button)
        for _ = 1, budget do
            if pred() then log(label .. " tile=" .. tile_row(281, 18) .. " | " .. tile_row(321, 18));return true end
            yield_frame(button and frame % 16 < 2 and {[button]=true} or {})
        end
        return false
    end
    local function partner_has(mark)
        local file = io.open(D.partner_result, "r")
        if not file then return false end
        local text = file:read("*a");file:close()
        return text:find(mark, 1, true) ~= nil
    end

    local first_done = seen.trade_done or 0
    local first_msgbox = seen.msgbox or 0

    if D.player == "a" then
        local first_query, first_offer = seen.trade_query or 0, seen.trade_offer or 0
        -- The offer must not land while the partner is still walking. trade_prompt.asm's textbox
        -- freezes the partner's overworld and is answered with the D-pad, so an early offer leaves
        -- the Center route pressing directions into a YES/NO menu until "waypoint not blocked"
        -- (gen1_rb_center_inputs.lua:190) kills the run -- trade_decline_new first contact: b stuck
        -- at Route 1 (11,1) with row14="Trade RATTATA", then the server's trade watchdog
        -- (server/state.py:491-507) freed the slot silently and a waited out its decline notice.
        -- trade_new only passed because b reached the Center ~1300 frames FIRST that run; the two
        -- halves share this code, so the mark fixes the accept path too.
        -- Same rendezvous the whiteout rebuild lane already uses (the AT_CENTER wait at :2259-2261,
        -- 600s); walk_to_center():447 logs CENTER_RECEPTIONIST, so no extra mark is needed.
        if not wait_until(function() return partner_has("CENTER_RECEPTIONIST") end, 600,
                          "partner to reach the receptionist") then
            return false, "partner never reached the Center receptionist"
        end
        tap("Up");yield_frame({}) -- receptionist object at (11,2)
        local talked = frame
        tap("A")
        if not wait_until(function() return (seen.trade_query or 0) > first_query end, 30, "native trade_query") then
            return false, "receptionist did not query eligibility"
        end
        if frame - talked > 30 then return false, "native query exceeded 30 frames" end
        local mask_command = wait_until(function() return received_commands.trade_mask end, 30, "trade_mask")
        local mask = mask_command and mask_command.mask or 0
        if math.floor(mask / (2 ^ linked_slot)) % 2 ~= 1 then
            return false, fmt("linked physical slot %d absent from eligibility mask %d", linked_slot, mask)
        end
        -- trade_receptionist.asm:335-381: the picker lists set mask bits in ascending
        -- physical slot order, then maps the selected *visible row* back to a physical slot.
        local picker_row = 0
        for slot = 0, linked_slot - 1 do
            if math.floor(mask / (2 ^ slot)) % 2 == 1 then picker_row = picker_row + 1 end
        end
        log(fmt("TRADE_MASK %d linked_slot=%d picker_row=%d", mask, linked_slot, picker_row))
        if not wait_tiles("NATIVE_MENU", function()
            return tiles("SLINK TRADE", 42) and tiles("CABLE CLUB", 82) and tiles("CANCEL", 122)
        end, 120) then return false, "SLINK TRADE native menu not drawn" end
        if not wait_tiles("TRADE_WHICH", function() return tiles("TRADE WHICH?", 22) end, 180, "A") then
            return false, "TRADE WHICH? picker not drawn"
        end
        for _ = 1, 90 do
            if rd(ram.wCurrentMenuItem) == picker_row then break end
            yield_frame(frame % 16 < 2 and {Down=true} or {})
        end
        if rd(ram.wCurrentMenuItem) ~= picker_row then return false, "picker cursor did not reach linked row" end
        for _ = 1, 180 do
            if (seen.trade_offer or 0) > first_offer then break end
            yield_frame(frame % 16 < 2 and {A=true} or {})
        end
        local offered = sent_events.trade_offer
        if (seen.trade_offer or 0) ~= first_offer + 1 or not offered or offered.slot ~= linked_slot then
            return false, fmt("trade_offer was not the linked slot %d", linked_slot)
        end
        log(fmt("TRADE_OFFER slot=%d", offered.slot))
        if not wait_tiles("OFFER_SENT", function() return tiles("Trade offer sent.") end, 180) then
            return false, "native Trade offer sent. text not drawn"
        end
        local returned = false
        for _ = 1, 600 do
            if overworld_ok() then returned = true;break end
            yield_frame(frame % 16 < 2 and {A=true} or {})
        end
        if not returned then return false, "offer text did not return to overworld" end
        log("OFFER_RETURNED")
    else
        local prompt = wait_until(function() return received_commands.show_menu end, 300, "partner show_menu")
        if not prompt or prompt.blob_hex == nil or prompt.slot == nil then
            return false, "partner show_menu omitted native prompt fields"
        end
        -- trade_prompt.asm:77-83 calls PrintText then YesNoChoice; :106-115 renders
        -- `Trade <player>` / `for <nickname>?`. pret data/yes_no_menu_strings.asm:24-26
        -- renders YES and NO as distinct tilemap rows.
        if not wait_tiles("PARTNER_YES_NO", function()
            return tiles("Trade ") and tiles("for ") and tiles("YES") and tiles("NO")
        end, 600) then return false, "native partner Trade/for/YES/NO prompt not drawn" end
        if not wait_until(function() return partner_has("OFFER_RETURNED") end, 180,
                          "initiator to clear the offer notice") then return false, "initiator still in offer text" end
        if rd(ram.wCurrentMenuItem) ~= 0 then return false, "native prompt did not default to YES" end
        local first_result = seen.menu_result or 0
        if decline then
            -- HandleMenuInput over the TWO_OPTION_MENU (wMaxMenuItem = 1): Down moves the cursor
            -- to the NO row and stops there. Press only until it lands, never past it.
            for _ = 1, 120 do
                if rd(ram.wCurrentMenuItem) == 1 then break end
                yield_frame(frame % 16 < 2 and {Down=true} or {})
            end
            if rd(ram.wCurrentMenuItem) ~= 1 then return false, "native prompt cursor never reached NO" end
        end
        for _ = 1, 240 do
            if (seen.menu_result or 0) > first_result then break end
            yield_frame(frame % 16 < 2 and {A=true} or {})
        end
        local want = decline and 0 or 1
        if (seen.menu_result or 0) ~= first_result + 1 or not sent_events.menu_result or
           sent_events.menu_result.choice ~= want then
            return false, fmt("partner %s did not send menu_result choice=%d", decline and "NO" or "YES", want)
        end
        log(decline and "TRADE_DECLINED" or "PARTNER_ACCEPTED")
    end

    if decline then
        -- server/state.py:667-673: the NO clears pending_trade and queues one msgbox per side
        -- ("Your partner declined the trade." / "Trade declined."). No apply_trade is ever built,
        -- so neither cartridge stages a blob and neither party changes.
        if not wait_until(function() return (seen.msgbox or 0) > first_msgbox end, 300,
                          "decline notice") then return false, "no decline notice from the server" end
        if (seen.apply_trade or 0) > 0 or (seen.trade_done or 0) > first_done then
            return false, "a declined trade still applied"
        end
        if not wait_until(overworld_ok, 60, "overworld after the decline") then
            return false, "did not return to the overworld after the decline"
        end
        log("DECLINE_OVERWORLD")
        log_party("POST_DECLINE")
        if not wait_until(function() return partner_has("DECLINE_OVERWORLD") end, 300,
                          "partner to clear the declined trade") then
            return false, "partner never cleared the declined trade"
        end
        frames(120) -- let both menu_result/msgbox frames settle before client.exit()
        if (seen.apply_trade or 0) > 0 or (seen.trade_done or 0) > first_done then
            return false, "apply_trade arrived after the decline settled"
        end
        local saved_no, why_no = game_save("trade_decline_new")
        if not saved_no then return false, why_no end
        return true, "native trade declined; nothing applied"
    end

    local done = wait_until(function() return (seen.trade_done or 0) > first_done end, 300, "native apply trade_done")
    if not done then return false, "native apply never reported trade_done" end
    local report = sent_events.trade_done
    if not report or report.new_key == linked_key or report.new_species == 0 then
        return false, "trade_done reported no received mon"
    end
    log(fmt("TRADE_DONE slot=%d key=%s species=%d", report.slot or -1, report.new_key, report.new_species))
    log_party("POST_TRADE")
    if not wait_until(function() return partner_has("TRADE_DONE") end, 120, "partner trade_done") then
        return false, "partner did not finish native apply"
    end
    frames(120) -- let both trade_done frames reach the server before client.exit()
    local saved, why = game_save("trade_new")
    if not saved then return false, why end
    return true, "native trade applied once"
end

function scenarios.trade_new() return trade_scenario(false) end
function scenarios.trade_decline_new() return trade_scenario(true) end

local function partner_has_mark(mark)
    local file = io.open(D.partner_result, "r")
    if not file then return false end
    local text = file:read("*a");file:close()
    return text:find(mark, 1, true) ~= nil
end

local function pulse_at_frame(button)
    return frame % 16 < 2 and {[button] = true} or {}
end

local function tile_text(text, offset)
    return Center.has_tiles(rd, ram.wTileMap, text, offset)
end

local function menu_probe()
    local rows = {}
    for row = 0, 3 do rows[#rows + 1] = fmt("row%d=%s", row,
        Center.row(rd, ram.wTileMap, row * 20, 18)) end
    return fmt("cur=%d text=%d joy=%d %s", rd(ram.wCurrentMenuItem), rd(ram.wTextBoxID),
               rd(ram.wJoyIgnore), table.concat(rows, " | "))
end

local function menu_failure(reason)
    local detail = menu_probe()
    log("MENU_PROBE_FAIL " .. reason .. " " .. detail)
    return false, reason .. " [" .. detail .. "]"
end

local function start_menu_ready(point)
    -- DrawStartMenu restores wCurrentMenuItem from wBattleAndStartSavedMenuItem
    -- (pret engine/menus/draw_start_menu.asm:17-23; home/start_menu.asm:52-55).
    -- Probe the actual SAVE and POKéMON rows before trusting that cursor.
    local save = point.start_menu_save_index
    local pokemon = save - 3
    return save >= 3 and point.font_loaded and point.menu_y == 2 and point.menu_x == 11
       and tile_text("SAVE", (2 + 2 * save) * 20 + 12)
       and tile_text("POK", (2 + 2 * pokemon) * 20 + 12)
end

local function fainted_bang_on_tilemap()
    -- pret/constants/charmap.asm:126-151,169; text_2.asm:881-885 prints "fainted!".
    local word = "fainted"
    for offset = 0, 20 * 18 - #word - 1 do
        local match = true
        for i = 1, #word do
            if rd(ram.wTileMap + offset + i - 1) ~= 0xA0 + word:byte(i) - 97 then match = false;break end
        end
        if match and rd(ram.wTileMap + offset + #word) == 0xE7 then return offset end
    end
    return nil
end

local function linked_member()
    local key, mon = new_key()
    if not key or not mon or mon.slot ~= 1 or mon.hp <= 0 then return nil, "linked slot 1 not alive" end
    return key, mon
end

local function bench_at_route_one_side(linked_slot)
    -- The same input-only route used by the receptionist gate steps north off Route 1's
    -- grass column to (8,31), and RUNs if a wild battle interrupts it.
    local route = Center.new({
        read = rd, ram = ram, row = function(off, n) return Center.row(rd, ram.wTileMap, off, n) end,
        frame = function() return frame end, start = "route1", log = log,
        invariant = function(label, ok, detail) if not ok then error(label .. ": " .. detail, 0) end end,
        check = function(label, ok, detail) if not ok then error(label .. ": " .. detail, 0) end end,
        menu_addr = {wTopMenuItemX=symbols.wTopMenuItemX, wTopMenuItemY=symbols.wTopMenuItemY},
        linked_hp = function()
            local addr = ram.wPartyMons + linked_slot * parts.profile.derived.party_struct_size + 1
            return rd(addr) * 256 + rd(addr + 1)
        end,
    })
    for _ = 1, 12000 do
        local pos = reads.read_map()
        if pos.map == 0x0C and pos.x == 8 and pos.y == 31 and overworld_ok() then
            log("READY_BENCH map=12 x=8 y=31")
            return true
        end
        local buttons = route.step()
        yield_frame(buttons)
    end
    return false, "B could not leave Route 1 grass"
end

local function escape_after_faint(tag, replacement_slot)
    -- The game may demand a replacement starter before RUN becomes selectable. Handle
    -- both the forced party list and the standard RUN column with ordinary joypad edges.
    replacement_slot = replacement_slot or 0
    for _ = 1, 12000 do
        if rd(ram.wIsInBattle) == 0 then
            if not wait_until(overworld_ok, 30, "post-faint overworld checkpoint") then
                return false, "post-faint battle ended without an overworld checkpoint"
            end
            log(fmt("BATTLE_RESULT %s %d", tag, rd(ram.wBattleResult)))
            return true
        end
        local x, y = rd(symbols.wTopMenuItemX), rd(symbols.wTopMenuItemY)
        local cur = rd(ram.wCurrentMenuItem)
        local buttons
        if x == 0 and y == 1 then
            buttons = pulse_at_frame(cur == replacement_slot and "A" or
                (cur < replacement_slot and "Down" or "Up")) -- select living starter
        elseif x == 0x0C and y == 0x0C and rd(ram.wMaxMenuItem) == 2 then
            buttons = pulse_at_frame(cur == 0 and "A" or "Up") -- SWITCH
        elseif rd(ram.wTextBoxID) == 0x0B and tile_text("FIGHT") and y == 14 then
            if x == 9 then buttons = pulse_at_frame("Right")
            elseif x == 15 and cur == 0 then buttons = pulse_at_frame("Down")
            elseif x == 15 then buttons = pulse_at_frame("A") end
        end
        yield_frame(buttons or pulse_at_frame("A"))
    end
    return false, "post-faint battle did not end or RUN within 12000 frames"
end

local function show_bench_fnt(linked_slot, key, faint_frame)
    -- An A-edge on the first frame after force_faint opens START before the next
    -- overworld checkpoint can consume the queued memorialize. PartyMenuInit and
    -- PrintStatusCondition draw slot i's FNT at tilemap + 40*i + 17 (pret
    -- engine/menus/party_menu.asm:14,65-68; home/pokemon.asm:311-325).
    local base = ram.wPartyMons + linked_slot * parts.profile.derived.party_struct_size
    local hp = rd(base + 1) * 256 + rd(base + 2)
    local status = rd(base + 4)
    log(fmt("BENCH_HP_STATUS %04X %02X", hp, status))
    if hp ~= 0 or status ~= 0 then return false, "B bench force_faint did not clear HP/status" end
    local function removed()
        local party = reads.read_party()
        if not party then return false end -- a torn read is not proof of memorialization
        for _, mon in ipairs(party) do if reads.key(mon) == key then return false end end
        return true
    end
    local function unavailable()
        log(fmt("TILEMAP_FNT unavailable: memorialised within %d frames of the faint", frame - faint_frame))
        for _ = 1, 600 do
            if overworld_ok() then return true end
            yield_frame(pulse_at_frame("B"))
        end
        return false, "party/START menu did not close after fast memorialization"
    end
    if removed() then return unavailable() end
    for _ = 1, 240 do
        if removed() then return unavailable() end
        local point = play.point()
        if start_menu_ready(point) then break end
        yield_frame(pulse_at_frame("Start"))
    end
    local point = play.point()
    if removed() then return unavailable() end
    if not start_menu_ready(point) then return menu_failure("START menu did not open before memorialize") end
    local pokemon_row = point.start_menu_save_index - 3 -- POKEMON precedes ITEM/name/SAVE
    for _ = 1, 180 do
        if removed() then return unavailable() end
        if rd(ram.wCurrentMenuItem) == pokemon_row then break end
        yield_frame(pulse_at_frame(rd(ram.wCurrentMenuItem) < pokemon_row and "Down" or "Up"))
    end
    if rd(ram.wCurrentMenuItem) ~= pokemon_row then return menu_failure("START cursor missed POKEMON") end
    for _ = 1, 180 do
        if removed() then return unavailable() end
        if rd(symbols.wTopMenuItemY) == 1 and rd(symbols.wTopMenuItemX) == 0 then break end
        yield_frame(pulse_at_frame("A"))
    end
    if rd(symbols.wTopMenuItemY) ~= 1 or rd(symbols.wTopMenuItemX) ~= 0 then
        if removed() then return unavailable() end
        return menu_failure("party menu did not open for linked FNT readback")
    end
    local offset = 40 * linked_slot + 17
    for _ = 1, 120 do
        if tile_text("FNT", offset) or removed() then break end
        yield_frame({}) -- wait for the party menu's text renderer; no further selection
    end
    if not tile_text("FNT", offset) then
        if removed() then return unavailable() end
        local party = reads.read_party()
        if not party or not party[linked_slot + 1] then
            return menu_failure("party unreadable while checking linked FNT slot")
        end
        if not tile_text(party[linked_slot + 1].nickname, 40 * linked_slot + 3) then
            return menu_failure("linked party slot was not drawn for FNT readback")
        end
        return menu_failure("party menu lacked linked slot FNT glyphs")
    end
    log(fmt("TILEMAP_FNT row=%d offset=%d %s", 2 * linked_slot, offset,
            Center.row(rd, ram.wTileMap, 40 * linked_slot, 20)))
    for _ = 1, 600 do
        if overworld_ok() then return true end
        yield_frame(pulse_at_frame("B"))
    end
    return false, "party menu did not close after FNT readback"
end

local function reorder_linked_to_lead(key)
    -- Overworld START -> POKEMON -> slot 1 -> field menu SWITCH -> slot 0.
    -- start_sub_menus.asm:8-25,67-94 selects SWITCH at max-1; home/pokemon.asm:201-290
    -- uses party Y1/X0 and wMenuItemToSwap (1-based) for the second selection;
    -- start_sub_menus.asm:694-743 swaps species, structs and names together.
    local before = reads.read_party()
    if not before or #before ~= 2 or reads.key(before[2]) ~= key then
        return false, "linked mon was not physical slot 1 before overworld reorder"
    end
    local starter_key = reads.key(before[1])
    if not wait_until(overworld_ok, 30, "overworld before party reorder") then
        return false, "not safe to open START before reorder"
    end
    for _ = 1, 300 do
        local point = play.point()
        if start_menu_ready(point) then break end
        yield_frame(pulse_at_frame("Start"))
    end
    local point = play.point()
    if not start_menu_ready(point) then return menu_failure("START menu did not open for reorder") end
    local pokemon_row = point.start_menu_save_index - 3
    for _ = 1, 240 do
        if rd(ram.wCurrentMenuItem) == pokemon_row then break end
        yield_frame(pulse_at_frame(rd(ram.wCurrentMenuItem) < pokemon_row and "Down" or "Up"))
    end
    if rd(ram.wCurrentMenuItem) ~= pokemon_row then return menu_failure("START cursor missed POKEMON row") end
    for _ = 1, 240 do
        if rd(symbols.wTopMenuItemY) == 1 and rd(symbols.wTopMenuItemX) == 0 then break end
        yield_frame(pulse_at_frame("A"))
    end
    for _ = 1, 120 do
        if tile_text(before[2].nickname, 40 + 3) then break end
        yield_frame({})
    end
    if rd(symbols.wTopMenuItemY) ~= 1 or rd(symbols.wTopMenuItemX) ~= 0 or
       not tile_text(before[2].nickname, 40 + 3) then
        return menu_failure("party menu did not draw linked slot 1 nickname")
    end
    for _ = 1, 240 do
        if rd(ram.wCurrentMenuItem) == 1 then break end
        yield_frame(pulse_at_frame(rd(ram.wCurrentMenuItem) < 1 and "Down" or "Up"))
    end
    if rd(ram.wCurrentMenuItem) ~= 1 then return menu_failure("party cursor missed linked slot 1") end
    for _ = 1, 240 do
        if rd(ram.wTextBoxID) == 4 and rd(symbols.wTopMenuItemY) ~= 1 and rd(ram.wMaxMenuItem) >= 2 then break end
        yield_frame(pulse_at_frame("A"))
    end
    -- FIELD_MOVE_MON_MENU=$04 (pret constants/menu_constants.asm:9); the dynamic
    -- field-move list places SWITCH one row before CANCEL (start_sub_menus.asm:67-94).
    if rd(ram.wTextBoxID) ~= 4 then return menu_failure("field move menu did not open for SWITCH") end
    local switch_row = rd(ram.wMaxMenuItem) - 1
    for _ = 1, 240 do
        local cur = rd(ram.wCurrentMenuItem)
        if cur == switch_row then break end
        yield_frame(pulse_at_frame(cur < switch_row and "Down" or "Up"))
    end
    if rd(ram.wCurrentMenuItem) ~= switch_row then return menu_failure("field menu cursor missed SWITCH") end
    for _ = 1, 240 do
        if rd(symbols.wTopMenuItemY) == 1 and rd(symbols.wTopMenuItemX) == 0 and
           rd(symbols.wMenuItemToSwap) == 2 then break end
        yield_frame(pulse_at_frame("A"))
    end
    if rd(symbols.wMenuItemToSwap) ~= 2 then return menu_failure("first SWITCH choice did not latch slot 1") end
    for _ = 1, 240 do
        if rd(ram.wCurrentMenuItem) == 0 then break end
        yield_frame(pulse_at_frame("Up"))
    end
    if rd(ram.wCurrentMenuItem) ~= 0 then return menu_failure("second SWITCH cursor missed slot 0") end
    for _ = 1, 240 do
        local now = reads.read_party()
        if now and reads.key(now[1]) == key and reads.key(now[2]) == starter_key and
           rd(symbols.wMenuItemToSwap) == 0 then break end
        yield_frame(pulse_at_frame("A"))
    end
    local after = reads.read_party()
    if not after or reads.key(after[1]) ~= key or reads.key(after[2]) ~= starter_key then
        return menu_failure("overworld SWITCH did not put linked mon in lead slot 0")
    end
    for _ = 1, 120 do
        if tile_text(after[1].nickname, 3) then break end
        yield_frame({})
    end
    if not tile_text(after[1].nickname, 3) then return menu_failure("reordered party tilemap lacks lead nickname") end
    log("REORDER_LEAD " .. key .. " slot=0 from=1 tilemap=" ..
        Center.row(rd, ram.wTileMap, 0, 20))
    for _ = 1, 600 do
        if overworld_ok() then return true end
        yield_frame(pulse_at_frame("B"))
    end
    return false, "party/START menu did not close after reorder"
end

-- ── Explode Mode (W-3 / D-11) ────────────────────────────────────────────────────────
-- MoveSelectionMenu's regular menu sets wTopMenuItemX=5 / wTopMenuItemY=$0C and places the
-- names at hlcoord 6,13 with BIT_SINGLE_SPACED_LINES set (pret engine/battle/core.asm:
-- 2476-2483,2487-2506,2534-2538) -> tilemap offsets 13*20+6 = 266, 286, 306, 326.
local MOVE_MENU_X, MOVE_MENU_Y = 5, 0x0C
local MOVE_ROWS = { 266, 286, 306, 326 }

-- The patch rewrites a 16-bit little-endian frame counter at mailbox +5 from its VBlank hook
-- (patch/gen1/src/slink.asm:44,128-135), so two reads on two different frames are a live
-- proof that the hook still runs inside a battle. Only a PATCHED cartridge has the mailbox:
-- panel:present() checks the 'SLNK' beacon and the capability bits (lua/gen1/panel.lua:85-91).
local function panel_counter() return rd(Panel.MAILBOX + 5) + rd(Panel.MAILBOX + 6) * 256 end
local function log_panel_counter_in_battle()
    if not parts.panel:present() then
        log("PANEL_COUNTER_IN_BATTLE absent (unpatched cartridge)")
        return
    end
    local a = panel_counter()
    yield_frame()
    log(fmt("PANEL_COUNTER_IN_BATTLE a=%d b=%d", a, panel_counter()))
end

-- `force_explode` arms a pending battle write that the client can only apply from its
-- MainInBattleLoop hook (client.lua:612-641), and B is parked at the battle menu -- one loop
-- head too late. Cancelling the MOVE menu with B is the free re-entry: SelectMenuItem returns
-- with nz on a B press (core.asm:2620-2642) and core.asm:332-337 (`call MoveSelectionMenu ...
-- jr nz, MainInBattleLoop`) jumps straight back to the loop head without reaching
-- SelectEnemyMove, so no turn is spent and the foe never swings. FormatMovesString re-derives
-- wNumMovesMinusOne from the four move bytes (engine/battle/misc.asm:2-31), so all four
-- EXPLOSIONs get a row, and the commit's PP gate reads `[wBattleMonPP+slot] and PP_MASK`
-- (core.asm:2643-2650) -- writes.lua:92,95 leave PP 1, which passes.
local function explode_free_reentry(driver, key)
    local function move_menu(what)
        for _ = 1, 900 do
            if rd(symbols.wTopMenuItemX) == MOVE_MENU_X and rd(symbols.wTopMenuItemY) == MOVE_MENU_Y then
                frames(8) -- PlaceString runs before .menuset, but leave the row a redraw margin
                return true
            end
            yield_frame()
        end
        return false, "the move menu never opened " .. what
    end
    local function log_rows(tag)
        local out = {}
        for i, off in ipairs(MOVE_ROWS) do out[i] = Center.row(rd, ram.wTileMap, off, 12) end
        log(fmt("MOVE_MENU_%s %s", tag, table.concat(out, " | ")))
    end

    -- 1. the catch's OWN moves (Rattata Tackle/Tail Whip, Pidgey Gust -- base_stats/rattata.asm:13,
    --    pidgey.asm:13), read before anything of ours has touched the battle struct.
    if not driver.choose("FIGHT").ok then return false, "B could not open the move menu before the explode write" end
    local opened, why = move_menu("before the cancel")
    if not opened then return false, why end
    log_rows("BEFORE")
    if tile_text("EXPLOSION") then return false, "the move menu showed EXPLOSION before the write landed" end

    -- 2. B, until the write lands. Stop pressing the moment the menu is gone so the stray edge
    --    cannot reach the battle menu behind it.
    local cancelled, landed = false, false
    for _ = 1, 900 do
        if rd(symbols.wTopMenuItemX) ~= MOVE_MENU_X then cancelled = true end
        if rd(ram.wBattleMonMoves) == 0x99 then landed = true break end
        yield_frame((not cancelled) and pulse_at_frame("B") or nil)
    end
    if not landed then return false, "the explode write never landed at the loop head" end

    -- 3. the same menu again: four EXPLOSION rows, from a turn that was never spent.
    local menu = driver.wait_menu(900)
    if not menu.ok then return false, "the battle menu did not return after the cancel: " .. tostring(menu.why) end
    if not driver.choose("FIGHT").ok then return false, "B could not re-open the move menu after the explode write" end
    opened, why = move_menu("after the cancel")
    if not opened then return false, why end
    log_rows("AFTER")
    for _, off in ipairs(MOVE_ROWS) do
        if not tile_text("EXPLOSION", off) then
            return false, fmt("move row at tilemap offset %d is not EXPLOSION", off)
        end
    end
    log(fmt("MOVE_MENU_EXPLOSION rows=4 key=%s moves=%s pp=%s", key, hex4(ram.wBattleMonMoves), hex4(ram.wBattleMonPP)))
    return true
end

local function linked_faint_scenario(active, explode)
    local linked, why = scenarios.link_new() -- real catch, server link, withdrawal, game SAVE
    if not linked then return false, link_prerequisite_failure(why) end
    if (seen.sync_retrieve_done or 0) < 1 then return false, "linked capture was not returned" end
    local key, mon = linked_member()
    if not key then return false, mon end
    local first_faint = seen.faint or 0
    if D.player == "a" then
        local ready = active and "READY_ACTIVE" or "READY_BENCH"
        if not wait_until(function() return partner_has_mark(ready) end, 180, "B " .. ready) then
            return false, "B did not park in the required faint window"
        end
        local phase = hunt("sacrifice", {switch_slot=1, move_slot=1,
                                        fainted=function() return (battle_site_keys[key] or 0) > 0 end})
        if phase == "linked-survived-3-battles" then return false, "linked mon survived 3 battles" end
        if phase ~= "linked-fainted" or not battle_site_keys[key] or
           not sent_events.faint or sent_events.faint.key ~= key then
            return false, "A linked mon did not faint at the engine battle_faint site: " .. tostring(phase)
        end
        log("A_ENGINE_FAINT " .. key)
        local escaped, error_text = escape_after_faint("a")
        if not escaped then return false, error_text end
    elseif active then
        local reordered, reorder_why = reorder_linked_to_lead(key)
        if not reordered then return false, reorder_why end
        local phase, driver = hunt("switch-hold", {start_active=true, keep_driver=true})
        if phase ~= "linked-active-menu" then return false, "B could not hold its linked mon active: " .. tostring(phase) end
        if rd(ram.wPlayerMonNumber) ~= 0 or not reads.read_party() or
           reads.key(reads.read_party()[1]) ~= key then return false, "B linked lead not active at hold menu" end
        log("READY_ACTIVE linked_slot=0")
        if explode then log_panel_counter_in_battle() end
        local wrote = false
        local old = gclient.on_battle_loop_head
        gclient.on_battle_loop_head = function(self, sig)
            local pending = self.pending_battle_writes[1]
            -- BEFORE the write: a natural KO during the 900-frame `opened` wait also arrives at
            -- the loop head with HP 0, so the post-condition alone cannot tell the forced write
            -- from the foe doing it. Only a mon that was still ALIVE on entry to this head and
            -- is at 0 on exit was killed by writes.lua.
            local hp_before = rd(ram.wBattleMonHP) * 256 + rd(ram.wBattleMonHP + 1)
            old(self, sig)
            if not (pending and pending.key == key and #self.pending_battle_writes == 0) then return end
            if explode then
                -- writes.lua:89-96 fills both move blocks with EXPLOSION ($99) and PP 1 and does
                -- NOT touch wPlayerSelectedMove -- B still has to pick FIGHT -> slot 1.
                log(fmt("LOOP_HEAD_EXPLODE moves=%s pp=%s", hex4(ram.wBattleMonMoves), hex4(ram.wBattleMonPP)))
            elseif hp_before ~= 0 and rd(ram.wBattleMonHP) == 0 and rd(ram.wBattleMonHP + 1) == 0 and
                   rd(ram.wPlayerSelectedMove) == 0xFF then
                wrote = true
                log("LOOP_HEAD_WRITE key=" .. key .. " battle_hp=0000 selected=FF hp_before=" .. hp_before)
            end
        end
        local want = explode and "force_explode" or "force_faint"
        local forced = false
        for _ = 1, 60000 do
            if received_commands[want] and received_commands[want].key == key then forced = true;break end
            yield_frame()
        end
        if not forced then driver.close();return false, want .. " never arrived" end
        if explode then
            log(fmt("EXPLODE_CMDS force_explode=%d force_faint=%d",
                    seen.force_explode or 0, seen.force_faint or 0))
            if (seen.force_faint or 0) ~= 0 then
                driver.close();return false, "Explode Mode sent force_faint as well as force_explode"
            end
            local reentered, reentry_why = explode_free_reentry(driver, key)
            if not reentered then driver.close();return false, reentry_why end
            local committed = driver.commit_move(1, 900)
            log(fmt("B_ACTIVE_COMMIT %s selected=%02X pp_before=%s", tostring(committed.why),
                    committed.selected_move or 0xFF, tostring(committed.pp_before)))
        else
            -- B is parked INSIDE DisplayBattleMenu, one loop head too late for the queued write,
            -- and the linked mon is still at its capture HP (5/15 in the run that failed).
            -- COMMITTING a move spends the turn: core.asm:338-339 falls through to
            -- SelectEnemyMove/Execute*, the foe swings, and a capture-HP mon is a coin flip --
            -- exactly the natural KO that left W-2 with no LOOP_HEAD_WRITE (the earlier pass
            -- predates e95cefa, when the kept-alive driver's presses were silent). Take the same
            -- free re-entry explode_free_reentry documents instead: cancel the MOVE menu with B
            -- and core.asm:332-337 (`call MoveSelectionMenu ... jr nz, MainInBattleLoop`) jumps
            -- straight back to the loop head without reaching SelectEnemyMove, so the write lands
            -- before any enemy move can run. The signal is a synchronous on_bus_exec at
            -- MainInBattleLoop+0 (signals.lua:78-89 defines the site), i.e. before `call
            -- ReadPlayerMonCurHPAndStatus`, so the very same head takes `jp z,
            -- HandlePlayerMonFainted`. No turn is spent and no RNG decides the outcome.
            if not driver.choose("FIGHT").ok then
                driver.close();return false, "B could not choose FIGHT after force_faint"
            end
            local opened = false
            for _ = 1, 900 do
                if rd(symbols.wTopMenuItemX) == MOVE_MENU_X and
                   rd(symbols.wTopMenuItemY) == MOVE_MENU_Y then opened = true break end
                yield_frame()
            end
            if not opened then
                driver.close();return false, "B's move menu never opened for the free cancel"
            end
            -- On the success path the write lands at the loop head the B press bounces us to and
            -- `wrote` breaks the loop, so no battle menu is ever reached and `cancelled` never
            -- matters. The latch is purely for the FAILURE path: if the write does not land, stop
            -- pressing the moment the MOVE menu is gone so no stray B edge reaches the battle menu.
            local cancelled = false
            for _ = 1, 900 do
                if rd(symbols.wTopMenuItemX) ~= MOVE_MENU_X then cancelled = true end
                if wrote then break end
                yield_frame((not cancelled) and pulse_at_frame("B") or nil)
            end
            if not wrote then
                driver.close();return false, "the force_faint write never landed at the loop head"
            end
        end
        driver.close()
        local faint_text
        for _ = 1, 1800 do
            faint_text = fainted_bang_on_tilemap()
            if faint_text and (seen.faint or 0) > first_faint then break end
            if (seen.faint or 0) > first_faint and rd(ram.wIsInBattle) == 0 then break end
            yield_frame(pulse_at_frame("A"))
        end
        if not battle_site_keys[key] or not sent_events.faint or sent_events.faint.key ~= key then
            return false, "B engine battle_faint site was not observed for the linked key"
        end
        if faint_text then log(fmt("TILEMAP_FAINTED offset=%d", faint_text))
        else log("TILEMAP_FAINTED unavailable: native faint text advanced before probe") end
        local escaped, error_text = escape_after_faint("b", 1)
        if not escaped then return false, error_text end
    else
        local parked, error_text = bench_at_route_one_side(mon.slot)
        if not parked then return false, error_text end
        local forced = false
        for _ = 1, 60000 do
            if received_commands.force_faint and received_commands.force_faint.key == key then forced = true;break end
            yield_frame()
        end
        if not forced then return false, "force_faint never arrived" end
        local fainted = false
        for _ = 1, 300 do
            local base = ram.wPartyMons + mon.slot * parts.profile.derived.party_struct_size
            if rd(base + 1) == 0 and rd(base + 2) == 0 then fainted = true;break end
            yield_frame()
        end
        if not fainted then return false, "B bench force_faint never zeroed party HP" end
        local shown, why_fnt = show_bench_fnt(mon.slot, key, frame)
        if not shown then return false, why_fnt end
    end
    if not wait_until(function() return (seen.memorialize_done or 0) >= 1 end, 180,
                      "both linked memorial commands") then return false, "memorialize_done never arrived" end
    log_party("POST_LINKED_FAINT")
    local saved, save_why = game_save(D.scenario) -- same tag as before for the two faint scenarios
    if not saved then return false, save_why end
    if explode then return true, "explode self-KO and memorial saved" end
    return true, "engine linked faint and memorial saved"
end

function scenarios.linked_faint_bench_new() return linked_faint_scenario(false) end
function scenarios.linked_faint_active_new() return linked_faint_scenario(true) end
-- W-3 / D-11: linked_faint_active_new against a server started with --explode-mode. A's half is
-- byte-for-byte the same sacrifice hunt; only B's half changes, because state.py:2678-2680 sends
-- `force_explode` instead of `force_faint` on exactly that path.
function scenarios.explode_new() return linked_faint_scenario(true, true) end

-- F-4: admission itself is decided by the server. Both cartridges only boot their town
-- battery save, send the production hello, and hold the ordinary overworld for 600 frames.
-- The runner reads /api/status, events.json, and slink.log for opposite verdicts.
function scenarios.admit_randomized_new()
    local party = reads.read_party()
    local place = reads.read_map()
    -- The disclosed town fixtures park at Oak's Lab $28 (5,6):
    -- lua/tests/test_gen1_receptionist_gate.lua:1-12, pret/map_constants.asm.
    if not party or #party < 1 or place.map ~= 0x28 or place.x ~= 5 or place.y ~= 6 then
        return false, fmt("town save not live: party=%s map=%d (%d,%d)",
                          party and #party or "unreadable", place.map, place.x, place.y)
    end
    log(fmt("ADMIT_MAP %d %d %d", place.map, place.x, place.y))
    log(fmt("ADMIT_PARTY %d", #party))
    if not wait_until(function() return sent_events.hello end, 120, "production hello") then
        return false, "client did not send hello from the live game"
    end
    local hello = sent_events.hello
    local content = hello.rom_content
    if not content or not content.wild or not content.variant then
        return false, "hello omitted its raw ROM content"
    end
    local maps = 0
    for _ in pairs(content.wild) do maps = maps + 1 end
    if maps == 0 then return false, "hello ROM content carried no wild maps" end
    log(fmt("HELLO_RECEIPT %s %d wild_maps", content.variant, maps))
    if not wait_go() then return false, "no go-file after admission verdicts" end
    -- Both halves SAVE. The saved-state oracle reads each cartridge's flushed SaveRAM, and
    -- rejection is a server fact, not a cartridge one: B reaches this overworld checkpoint
    -- before its hello (lua/gen1/client.lua:866-873) and game_save gates on safety.check
    -- (duo_gen1_main.lua:126), not on admission -- so B drives the same ordinary-button SAVE,
    -- and its readback is what proves the server touched neither cartridge's save.
    local saved, save_error = game_save("admit_randomized_new")
    if not saved then return false, save_error end
    frames(600)
    local again = reads.read_party()
    local pos = reads.read_map()
    if not again or #again < 1 or pos.map ~= 0x28 or pos.x ~= 5 or pos.y ~= 6 then
        return false, "town save stopped being a live party during passive hold"
    end
    return true, "live hello held for 600 frames"
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
        local saved, why = game_save("deadzone_new_a")
        if not saved then return false, why end
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
    if not retired or not memorial then return false, "retired mon did not reach Box 12 before SAVE" end
    local saved, why = game_save("deadzone_new_b")
    if not saved then return false, why end
    return true, "dead-zone catch " .. key .. (retired and " retired" or " fainted only")
end

-- W-6: the A+B+SELECT+START soft reset on a LIVE, already-helloed cartridge.
--
-- Engine timing, all from pret/pokered:
--   engine/joypad.asm:5-7   `cp PAD_BUTTONS` -> TrySoftReset only when hJoyInput is EXACTLY the
--                           four buttons, which is why the chord carries no d-pad.
--   engine/joypad.asm:50-61 one DelayFrame + one `dec hSoftReset` per poll, from 16
--                           (home/init.asm:81-82) -> 16 held frames before SoftReset runs.
--   home/init.asm:1-6       SoftReset whites out and DelayFrames 32, then falls into Init,
--                           which zero-fills $C000-$DFFF.
-- 16 + 32 = the WRAM clear lands ~48 frames after the chord starts; the chord is held 24 frames
-- (8 spare polls) and the clear is then awaited for up to 120 more. hSoftReset is only ever
-- re-seeded by Init (engine/joypad.asm:12-40 never restores it), so the 16 polls must be
-- CONSECUTIVE-from-boot only in the sense that nothing else in this run presses all four.
--
-- Client timing (lua/gen1/client.lua:18,168-205): validate() runs on `frame % 60 == 0`, and a
-- cleared WRAM is "pre-game (title/new game)" because wPlayerID is 0 with an empty party.
--   * the FIRST invalid validation clears hello_sent (:192-193) -> within 60 frames of the clear;
--   * the FIFTH (MAX_INVALID) pauses writes (:196-205) -> 4 further 60-frame validations, so the
--     pause lands 241..300 frames after the clear, NOT ">= 300": the first invalid validation can
--     fall on the very next frame boundary. The assertion below carries one validation of margin
--     either way and the exact delta is logged.
-- Then CONTINUE reloads the save (MainMenu -> TryLoadSaveFile), validate() goes live again and
-- logs "writes re-enabled after a live validation" (:183-186), and frame_end re-hellos from the
-- overworld checkpoint with the SAME wPlayerID (:908-911).
--
-- SCOPE: the claims here cover the IDLE, SAME-SAVE reset only. Retained deferred/known_keys/trade
-- state surviving a reset is by design, and a NEW GAME after a reset is C-1's REJECTED hello --
-- neither is claimed from this run.
function scenarios.soft_reset_new()
    if not wait_go() then return false, "no go-file" end
    if not wait_until(function() return sent_events.hello end, 120, "checkpoint hello") then
        return false, "no hello before the reset"
    end
    if D.player == "b" then
        -- The idle partner: it only has to stay live and helloed across A's whole reset, so the
        -- server's "A reconnected, nothing else changed" verdict has a witness on the wire.
        if not wait_until(function() return partner_has_mark("REHELLO ot=") end, 600,
                          "A to re-hello after its reset") then
            return false, "A never re-helloed after its soft reset"
        end
        log(fmt("IDLE_PARTNER hellos=%d frame=%d", seen.hello or 0, frame))
        if (seen.hello or 0) ~= 1 then return false, "the idle partner helloed more than once" end
        local saved_b, why_b = game_save("soft_reset_new_b")
        if not saved_b then return false, why_b end
        return true, "idled at the checkpoint across the partner reset"
    end

    if not overworld_ok() then return false, "A is not at the overworld checkpoint" end
    if not gclient.hello_sent then return false, "A helloed but the client does not hold hello_sent" end
    local ot0 = sent_events.hello.ot_id
    local hellos_before = seen.hello or 0
    log(fmt("HELLO_AT_CHECKPOINT ot=%04X hellos=%d map=%d", ot0, hellos_before, rd(ram.wCurMap)))

    -- boxes.lua's cart writes go through entry.lua:59-65, which bypasses writes.log entirely and
    -- logs nothing, so the only way to count them is to watch the injected door itself. This is a
    -- late-bound table field (boxes.lua:232,260-262 call io.write_cart_bytes), so wrapping the
    -- table the client was built with intercepts every one of them.
    local cart_writes = 0
    local _write_cart_bytes = parts.box_io.write_cart_bytes
    parts.box_io.write_cart_bytes = function(off, bytes)
        cart_writes = cart_writes + 1
        log(fmt("BOX_WRITE off=%d n=%d frame=%d", off, #bytes, frame))
        return _write_cart_bytes(off, bytes)
    end

    local chord_start = frame
    for _ = 1, 24 do yield_frame({A=true, B=true, Select=true, Start=true}) end
    yield_frame({})
    local reset_frame
    for _ = 1, 120 do
        -- wCurMap 0 is Pallet Town, but the battle fixture stands on Route 1 ($0C) and wPlayerID
        -- is never 0 in a loaded save: together they are the zero-fill, not a map transition.
        if reads.read_player_id() == 0 and rd(ram.wCurMap) == 0 then reset_frame = frame break end
        yield_frame({})
    end
    if not reset_frame then
        return false, fmt("soft reset chord did not clear WRAM (ot=%d map=%d)",
                          reads.read_player_id(), rd(ram.wCurMap))
    end
    log(fmt("RESET_SEEN frame=%d abs=%d", reset_frame - chord_start, reset_frame))
    local writes_before = #parts.writes.log
    local cart_before = cart_writes

    -- No inputs at all: the intro and the title screen hold the cleared WRAM long enough for the
    -- client to walk the whole hello-withhold -> writes-pause path before anything reloads a save.
    local cleared, paused
    for _ = 1, 420 do
        if not cleared and not gclient.hello_sent then
            cleared = frame
            log(fmt("HELLO_CLEARED frame=%d delta=%d", frame, frame - reset_frame))
        end
        if not paused and gclient.gate_revoked and not gclient.writes_enabled then
            paused = frame
            log(fmt("WRITES_PAUSED frame=%d delta=%d", frame, frame - reset_frame))
        end
        yield_frame({})
    end
    if not cleared then return false, "the client kept hello_sent across a cleared WRAM" end
    if cleared - reset_frame > 120 then
        return false, fmt("hello_sent cleared %d frames after the reset (two validations max)",
                          cleared - reset_frame)
    end
    if not paused then return false, "writes were never paused by the cleared WRAM" end
    local pause_delta = paused - reset_frame
    if pause_delta < 240 or pause_delta > 360 then
        return false, fmt("writes paused %d frames after the reset, outside 240..360", pause_delta)
    end

    -- CONTINUE: the same boot inputs the battery-save boot above uses (an A tap on the 16-frame
    -- cadence until the party is plausible and the write checkpoint has held for 30 frames).
    -- MainMenu defaults to CONTINUE whenever the SRAM holds a save, so the taps never branch.
    local resumed, settled_again, rebooted = nil, 0, false
    for _ = 1, 9000 do
        if not resumed and gclient.writes_enabled and not gclient.gate_revoked then
            resumed = frame
            log(fmt("WRITES_RESUMED frame=%d delta=%d", frame, frame - reset_frame))
        end
        local count = memory.read_u8(ram.wPartyCount, "System Bus")
        local live = count >= 1 and count <= 6 and overworld_ok()
        settled_again = live and settled_again + 1 or 0
        if settled_again >= 30 then rebooted = true break end
        yield_frame((not live) and pulse_at_frame("A") or {})
    end
    if not rebooted then return false, "CONTINUE never came back to the overworld checkpoint" end
    log(fmt("CONTINUED frame=%d map=%d party=%d", frame, rd(ram.wCurMap),
            memory.read_u8(ram.wPartyCount, "System Bus")))
    if not resumed then
        if not wait_until(function()
            return gclient.writes_enabled and not gclient.gate_revoked
        end, 60, "writes re-enabled") then return false, "writes stayed paused after CONTINUE" end
        resumed = frame
        log(fmt("WRITES_RESUMED frame=%d delta=%d", frame, frame - reset_frame))
    end

    if not wait_until(function() return (seen.hello or 0) > hellos_before end, 120, "re-hello") then
        return false, "the reloaded save never re-helloed"
    end
    local again = sent_events.hello
    log(fmt("REHELLO ot=%04X hellos=%d frame=%d", again.ot_id, seen.hello or 0, frame))
    if again.ot_id ~= ot0 then
        return false, fmt("re-hello OT %04X is not the pre-reset OT %04X", again.ot_id, ot0)
    end
    if (seen.hello or 0) ~= hellos_before + 1 then
        return false, fmt("the reset produced %d hellos, not one", (seen.hello or 0) - hellos_before)
    end

    local wrote = #parts.writes.log - writes_before
    log(fmt("NO_WRITES_IN_WINDOW writes=%d cart_writes=%d", wrote, cart_writes - cart_before))
    if wrote ~= 0 or cart_writes ~= cart_before then
        return false, fmt("%d WRAM write(s) and %d cart write(s) landed on the cleared WRAM",
                          wrote, cart_writes - cart_before)
    end
    log_party("POST_RESET")
    local saved_a, why_a = game_save("soft_reset_new_a")
    if not saved_a then return false, why_a end
    return true, "same-save soft reset: one re-hello, no writes in the cleared window"
end

-- S-6 / W-5 (Bill's PC listing), A6 scenario 1: the link_new body, then A walks to the Viridian
-- Center and drives DEPOSIT -> WITHDRAW -> DEPOSIT -> RELEASE through the native menus. Every
-- press comes from gen1_rb_pc_inputs.lua, whose header holds the pret citation for each screen.
--
-- The RELEASE half depends on the client contract in lua/gen1/client.lua:552-592: move_mon keys
-- from the SIGNAL-TIME snapshot (signals.lua:141-166), and a standalone from_box RemovePokemon
-- (not preceded by a move_mon in the same frame, so not Bill's WITHDRAW) logs RELEASE_SEEN and
-- sends NOTHING. Releasing a boxed linked mon is therefore invisible to the server -- the pair
-- stays ALIVE with a phantom boxed half. That is the documented shared-protocol gap this
-- scenario pins, not a defect of this run.
--
-- A re-enters the PC for the second DEPOSIT only after B has finished, so the second deposit's
-- partner sync (state.py:2091-2109 would queue another box_mon once B's sync_retrieve_done has
-- put the key back in party_keys) cannot land on a live B: B's receipt is exactly box_mon then
-- party_mon, in that order, and nothing after.
function scenarios.pc_ops_new()
    local linked, why = scenarios.link_new()
    if not linked then return false, link_prerequisite_failure(why) end
    if (seen.sync_retrieve_done or 0) < 1 then return false, "linked capture was not returned to party" end
    local linked_key = new_key()
    if not linked_key then return false, "no linked key after the shared link_new body" end
    -- link_new's own quarantine box_mon/party_mon already sit in these logs; index past them.
    local tx0, rx0 = #storage_tx, #storage_rx

    if D.player == "b" then
        local synced = wait_until(function()
            return #storage_rx >= rx0 + 2 and storage_rx[rx0 + 2].cmd == "party_mon" or nil
        end, 420, "box_mon then party_mon for B's linked key")
        for i = rx0 + 1, #storage_rx do
            log(fmt("PC_PARTNER_RX %d %s %s", i - rx0, storage_rx[i].cmd, tostring(storage_rx[i].key)))
        end
        if not synced then
            return false, fmt("partner sync never arrived (%d command(s) after the link)", #storage_rx - rx0)
        end
        if storage_rx[rx0 + 1].cmd ~= "box_mon" or storage_rx[rx0 + 1].key ~= linked_key
           or storage_rx[rx0 + 2].key ~= linked_key then
            return false, "partner sync was not box_mon then party_mon for B's own linked key"
        end
        -- The PHYSICAL observation, not the bookkeeping: the mon is actually back in the party.
        if not wait_until(function()
            for _, m in ipairs(party_keys()) do if m.key == linked_key then return true end end
            return nil
        end, 120, "B's linked mon back in the party") then
            return false, "party_mon arrived but the mon never re-entered B's party"
        end
        log_party("PC_PARTNER")
        local saved_b, why_b = game_save("pc_ops_new_b")
        if not saved_b then return false, why_b end
        return true, "idled while the partner deposited and withdrew " .. linked_key
    end

    local linked_slot
    for _, m in ipairs(party_keys()) do if m.key == linked_key then linked_slot = m.slot end end
    if not linked_slot or #party_keys() ~= 2 then return false, "linked mon missing from a two-mon party" end
    log_party("PRE_PC")
    local linked_hp_addr = ram.wPartyMons + linked_slot * parts.profile.derived.party_struct_size + 1
    local walked, walk_why = walk_to_center(function()
        return rd(linked_hp_addr) * 256 + rd(linked_hp_addr + 1)
    end)
    if not walked then return false, walk_why end
    local before = PC.extend_point(play.point(), rd, symbols)
    log(fmt("PC_BOX_BEFORE box=%d count=%d init=%s", before.box_number, before.box_count,
            tostring(before.box_initialised)))
    if before.box_count ~= 0 then
        return false, fmt("Box %d already held %d mon(s) before the deposit", before.box_number, before.box_count)
    end

    local phase, mid = pc_drive({{"deposit", linked_slot + 1}, {"withdraw", 1}}, "deposit-withdraw")
    if phase ~= "pc-done" then return false, "PC deposit/withdraw ended " .. phase end
    if #storage_tx ~= tx0 + 2 or storage_tx[tx0 + 1].event ~= "party_to_box"
       or storage_tx[tx0 + 2].event ~= "box_to_party" then
        return false, fmt("deposit/withdraw sent %d storage event(s), not party_to_box then box_to_party",
                          #storage_tx - tx0)
    end
    if storage_tx[tx0 + 1].key ~= linked_key or storage_tx[tx0 + 2].key ~= linked_key then
        return false, "deposit/withdraw carried a key that is not the linked one"
    end
    log("PC_DEPOSIT_KEY " .. linked_key)
    log("PC_WITHDRAW_KEY " .. linked_key)
    if #release_seen ~= 0 then return false, "a RELEASE_SEEN fired during the WITHDRAW" end
    log(fmt("PC_MID party=%d box=%d count=%d", mid.party_count, mid.box_number, mid.box_count))

    if not wait_partner_done(420) then return false, "the idle partner never finished" end
    phase = pc_drive({{"deposit", linked_slot + 1}, {"release_box", 1}}, "deposit-release")
    if phase ~= "pc-done" then return false, "PC deposit/release ended " .. phase end
    if #storage_tx ~= tx0 + 3 or storage_tx[tx0 + 3].event ~= "party_to_box"
       or storage_tx[tx0 + 3].key ~= linked_key then
        return false, fmt("the second deposit sent %d storage event(s), not one party_to_box",
                          #storage_tx - tx0 - 2)
    end
    if #release_seen ~= 1 then return false, fmt("%d RELEASE_SEEN line(s) in the receipt, not 1", #release_seen) end
    if release_seen[1].key ~= linked_key then return false, "RELEASE_SEEN named a key that is not the linked one" end
    if release_seen[1].after ~= tx0 + 3 then
        return false, fmt("RELEASE_SEEN landed after %d storage event(s), not %d (the WITHDRAW window)",
                          release_seen[1].after - tx0, 3)
    end
    log("PC_RELEASE_SEEN " .. linked_key)

    local final = PC.extend_point(play.point(), rd, symbols)
    log(fmt("PC_FINAL party=%d box=%d count=%d init=%s", final.party_count, final.box_number,
            final.box_count, tostring(final.box_initialised)))
    if final.party_count ~= 1 then return false, fmt("A's party holds %d mon(s), not the starter alone", final.party_count) end
    if final.box_count ~= 0 then return false, fmt("Box %d still holds %d mon(s) after the release", final.box_number, final.box_count) end
    log_party("POST_PC")
    local saved, why_a = game_save("pc_ops_new_a")
    if not saved then return false, why_a end
    return true, "deposited, withdrew, deposited and released " .. linked_key
end

-- A6 scenario 2: the deadzone_new body (B's dead-zone catch is force-fainted into the Box 12
-- memorial), then B walks to the Center PC and CHANGEs BOX into 12 and back to 1. A's half IS
-- deadzone_new. The two box changes run as separate ops lists so the box state can be read
-- between them from the overworld, after the PC has written the active box home.
function scenarios.changebox_new()
    local ok, why = scenarios.deadzone_new()
    if not ok then return false, why end
    if D.player == "a" then return true, why end
    local walked, walk_why = walk_to_center()
    if not walked then return false, walk_why end
    local phase, at12 = pc_drive({{"changebox", 12}}, "changebox-12")
    if phase ~= "pc-done" then return false, "CHANGE BOX to 12 ended " .. phase end
    log(fmt("CHANGEBOX_TO %d initialised=%s count=%d", at12.box_number,
            tostring(at12.box_initialised), at12.box_count))
    if at12.box_number ~= 12 or not at12.box_initialised then
        return false, fmt("CHANGE BOX left box=%d initialised=%s", at12.box_number, tostring(at12.box_initialised))
    end
    if at12.box_count < 1 then return false, "Box 12 no longer lists the memorial after the box change" end
    local back, at1 = pc_drive({{"changebox", 1}}, "changebox-1")
    if back ~= "pc-done" then return false, "CHANGE BOX back to 1 ended " .. back end
    log(fmt("CHANGEBOX_BACK %d", at1.box_number))
    if at1.box_number ~= 1 then return false, fmt("the current box is %d, not 1", at1.box_number) end
    local saved, why_b = game_save("changebox_new_b")
    if not saved then return false, why_b end
    return true, "changed to Box 12 with the memorial listed and back to Box 1"
end

-- ── D-7 / S-4 (blackout half): the whiteout REBUILD ──────────────────────────────────
-- A single-pair whiteout with the pair IN THE PARTY is the already-proven game-over path, so
-- this lane proves the other branch: both halves box their linked catch first, A then loses its
-- starter (its only party mon) to a wild Route 1 foe, and the server rebuilds the pair out of
-- the two PCs. No game over, no memorial, the link unchanged.
--
-- WHY THE PAIR SURVIVES. server/state.py:1982-2054 `_handle_whiteout` retires only links whose
-- half is still in `party_keys` (:2024-2026) -- both halves are boxed by then -- and plans the
-- rebuild from ALIVE pairs with BOTH halves boxed (`_alive_pc_mons` :2336-2363, `_plan_rebuild`
-- :2365-2392). One `party_mon` is queued to each half and `rebuild_start` to A
-- (`_queue_rebuild_commands` :2394-2445); `rebuild_done` goes to A alone, once A's
-- `sync_retrieve_done` lands (state.py:299-307, `_maybe_finish_rebuild` :2448-2462). B's
-- receipt therefore holds no rebuild_done, only its own party_mon + sync_retrieve_done.
--
-- WHY BOTH HALVES DEPOSIT BY HAND, AND WHY THE RUNNER GATES THE NEXT STEP. A deposit is mirrored
-- to the partner as `box_mon` the moment the server sees `party_to_box`, and the partner's key
-- leaves `party_keys` THERE, before that cartridge has moved anything
-- (state.py:2066-2107). Bookkeeping is therefore not evidence: each half waits for the PHYSICAL
-- reads (party = starter only, the catch listed in the active box) and the runner then polls
-- /api/status (server/server.py:2209 publishes `players.<pid>.party_keys`) and appends
-- BOTH_BOXED to the go-file. A mirrored `box_mon` that lands on an already-deposited mon is a
-- no-op, not a failure: lua/gen1/boxes.lua:296-318 returns true when the key is already in the
-- current box and no longer in the party, so the two hand-driven deposits cannot race each
-- other into `box_mon_failed` (which would put the key back into party_keys, state.py:336-349,
-- and starve the rebuild).
--
-- THE FATAL BATTLE. lua/tests/gen1_rb_hunt_inputs.lua has no "lose with the mon that is already
-- out" mode (:69-70): `sacrifice` opens with `D.switch_to` (:141), which a one-mon party cannot
-- do (gen1_battle_driver.lua:212-256 refuses -- "AlreadyOut"). So this body reuses `switch-hold`
-- with `start_active` (:132-136), which parks at the first wild battle menu WITHOUT spending a
-- turn, keeps the driver alive (`options.keep_driver`, :316-318 above) and plays GROWL itself.
-- GROWL is move id $2D (pret constants/move_constants.asm:53), slot 2 of both starters' level-1
-- learnsets (data/pokemon/base_stats/bulbasaur.asm:13, charmander.asm:13) and PP 40 with power 0
-- (data/moves/moves.asm:58) -- it cannot end the battle, so the wild foe does all the work.
--
-- THE WIRE. `emit_faint` (lua/gen1/client.lua:491-504) sends `faint` for the starter -- an
-- orphan key the server only discards (state.py:1694-1701) -- and then `whiteout` ONCE, because
-- nothing else in the snapshot is alive. `whiteout_sent` is re-armed per battle (:517) and the
-- blackout site would send it only if that first one had not (:565). Neither the `whiteout`
-- cause on a link nor the ordering of `TX whiteout` against the blackout site is asserted here.
--
-- THE BLACKOUT. `ResetStatusAndHalveMoneyOnBlackout` (pret engine/events/black_out.asm:19-37)
-- halves the three BCD bytes of wPlayerMoney with DivideBCDPredef3, i.e. floor(before/2); the
-- battle fixture holds 2800 after its single 200 Poké Ball, so 1400. Ticks carry no money
-- (tests/unit/protocol_schema.py:25-29), so the driver decodes wPlayerMoney itself -- the
-- point's `money` field is exactly that decode over the pret symbol
-- (lua/tests/gen1_rb_point_fields.lua:11-18, gen1_scripted_play.lua:101), never
-- reads.read_money. The destination is wLastBlackoutMap (engine/overworld/special_warps.asm:
-- 79-80,113-131), which is 0 = PALLET_TOWN on these fixtures: `SetLastBlackoutMap` is called
-- only from the Center's HEALING script (engine/events/pokecenter.asm:17) and this lane uses
-- the Center's PC, never the nurse. FlyWarpDataPtr's Pallet entry is
-- `fly_warp PALLET_TOWN, 5, 6` (data/maps/special_warps.asm:65,79); the macro (:20-24) hands
-- x,y to `event_displacement`, which emits y then x (macros/coords.asm:75-79) into
-- wYCoord/wXCoord (ram/wram.asm:1788-1789) -- so x=5, y=6.

-- gen1_rb_center_inputs.lua only ever walks FORWARD: `stage_index` is advanced at :145-148 and
-- never decremented. A5 is the only lane that needs the way back, so its OWN waypoint table is
-- replayed in reverse here -- read, not copied, and the module itself is untouched.
local function back_waypoints(stage_name)
    for _, stage in ipairs(Center.STAGES) do
        if stage.name == stage_name then
            local out = {}
            for i = #stage.waypoints, 1, -1 do
                -- {11,-1} is the module's "keep stepping off the north edge" marker (:154), not a tile
                if stage.waypoints[i][2] >= 0 then out[#out + 1] = stage.waypoints[i] end
            end
            return out
        end
    end
    error("no center route stage " .. tostring(stage_name), 0)
end

-- Center PC -> Viridian -> Route 1, the reverse of walk_to_center. Exits, from pret:
-- the Center's warp tiles are (3,7)/(4,7) (data/maps/objects/ViridianPokecenter.asm:11-12), so
-- walking south down the module's own {3,4} column lands on one; Viridian's Center door is
-- (23,25) (ViridianCity.asm:14) and Route 1 connects north to Viridian
-- (data/maps/headers/Route1.asm:2). The walk STOPS at the module's own first Route 1 waypoint
-- {10,31}: that is one row north of the grass (gen1_rb_hunt_inputs.lua:15-18 -- grass is
-- x 10-11, y 32-35), so the whole way back is grass-free and no wild battle can interrupt it.
-- The hunt owns every encounter from there, exactly as in link_new.
local function walk_back_to_route1()
    local legs = {
        { map = Center.MAP.center,   points = back_waypoints("center_receptionist"), into = Center.MAP.viridian },
        -- skip_first: the forward stage's LAST waypoint is the Center's door tile (23,25)
        -- (data/maps/objects/ViridianCity.asm:14), which is exactly where stepping warps back
        -- inside. Coming out, the leg starts one tile south of it and must never target it.
        { map = Center.MAP.viridian, points = back_waypoints("viridian_center"),     into = Center.MAP.route1,
          skip_first = true },
        { map = Center.MAP.route1,   points = back_waypoints("route_one_north") },
    }
    for leg_index, leg in ipairs(legs) do
        local index, still, side, detour, last, arrived = leg.skip_first and 2 or 1, 0, 1, nil, "", false
        for _ = 1, 30000 do
            local map, x, y = rd(ram.wCurMap), rd(ram.wXCoord), rd(ram.wYCoord)
            if rd(ram.wIsInBattle) ~= 0 then
                return false, fmt("a battle interrupted the grass-free walk back at map=%d (%d,%d)", map, x, y)
            end
            if leg.into and map == leg.into then arrived = true;break end
            if map ~= leg.map then
                return false, fmt("the walk back left the planned map chain: map=%d (%d,%d) leg=%d", map, x, y, leg_index)
            end
            if detour and x == detour[1] and y == detour[2] then detour, still = nil, 0 end
            if not detour and index <= #leg.points and x == leg.points[index][1] and y == leg.points[index][2] then
                index, still = index + 1, 0
            end
            if index > #leg.points and not leg.into then arrived = true;break end
            -- past the last waypoint of a leg that still has to change maps: keep going south,
            -- the mirror of the module's `y - 1` off-map step.
            local target = detour or leg.points[index] or {x, y + 1}
            local here = fmt("%d:%d:%d:%d", map, x, y, index)
            still = (here == last) and still + 1 or 0
            last = here
            if still >= 240 then
                -- ponytail: one-column side-step, the same escape the forward module makes
                -- (gen1_rb_center_inputs.lua:170-186) for Route 1's Youngster, who paces
                -- LEFT_RIGHT across this path (data/maps/objects/Route1.asm). Ceiling: it clears
                -- a one-tile block; port the module's two-sided detour if a wider one appears.
                side, detour, still = -side, {x + side, y}, 0
                log(fmt("BACK_DETOUR side=%d from (%d,%d) frame %d", side, x, y, frame))
            end
            local buttons
            if rd(ram.wJoyIgnore) ~= 0 then buttons = pulse_at_frame("B") -- B never talks to an NPC
            elseif x < target[1] then buttons = {Right=true}
            elseif x > target[1] then buttons = {Left=true}
            elseif y < target[2] then buttons = {Down=true}
            elseif y > target[2] then buttons = {Up=true} end
            yield_frame(buttons)
        end
        if not arrived then
            return false, fmt("the walk back stalled on leg %d at map=%d (%d,%d) waypoint %d",
                              leg_index, rd(ram.wCurMap), rd(ram.wXCoord), rd(ram.wYCoord), index)
        end
    end
    log(fmt("BACK_AT_ROUTE1 map=%d (%d,%d)", rd(ram.wCurMap), rd(ram.wXCoord), rd(ram.wYCoord)))
    return true
end

-- The half of the scenario both cartridges share: the server's rebuild arrives as ONE party_mon,
-- the client withdraws it on its own sync path (client.lua:431-439) and answers
-- sync_retrieve_done. Every counter is read against a baseline taken at BOTH_BOXED, so
-- link_new's own un-quarantine party_mon -- and any box_mon the partner's deposit mirrored --
-- is behind us and cannot be counted as the rebuild's.
local function await_rebuild(linked_key, base, secs)
    local rx_before, done_before = base.rx, base.sync_retrieve_done
    if not wait_until(function()
        for i = rx_before + 1, #storage_rx do
            if storage_rx[i].cmd == "party_mon" and storage_rx[i].key == linked_key then return true end
        end
        return nil
    end, secs, "the rebuild's party_mon") then
        return false, "no rebuild party_mon arrived from the server"
    end
    log("REBUILD_PARTY_MON " .. linked_key)
    if not wait_until(function() return (seen.sync_retrieve_done or 0) > done_before end, 120,
                      "sync_retrieve_done for the rebuilt mon") then
        return false, "the client never confirmed the rebuild withdraw"
    end
    log("SYNC_RETRIEVE_DONE " .. linked_key)
    frames(120) -- let a second command, if the server ever queued one, arrive before counting
    local party_mons = 0
    for i = rx_before + 1, #storage_rx do
        if storage_rx[i].cmd == "party_mon" then party_mons = party_mons + 1 end
    end
    if party_mons ~= 1 then return false, fmt("%d rebuild party_mon command(s), not 1", party_mons) end
    if (seen.sync_retrieve_done or 0) ~= done_before + 1 then
        return false, fmt("%d sync_retrieve_done event(s) for one rebuild, not 1",
                          (seen.sync_retrieve_done or 0) - done_before)
    end
    for _, name in ipairs({"sync_retrieve_failed", "force_faint", "memorialize", "game_over"}) do
        if (seen[name] or 0) ~= base[name] then
            return false, fmt("the rebuild was not clean: %d %s since the deposit", (seen[name] or 0) - base[name], name)
        end
    end
    local rebuilt = wait_until(function()
        local pt = PC.extend_point(play.point(), rd, symbols)
        if pt.party_count ~= 2 or pt.box_count ~= 0 then return nil end
        for _, m in ipairs(party_keys()) do if m.key == linked_key then return pt end end
        return nil
    end, 120, "the restored two-mon party over an empty box")
    if not rebuilt then
        local pt = PC.extend_point(play.point(), rd, symbols)
        return false, fmt("after the rebuild the party holds %d mon(s) and Box %d holds %d",
                          pt.party_count, pt.box_number, pt.box_count)
    end
    log(fmt("REBUILT party=%d box_count=%d", rebuilt.party_count, rebuilt.box_count))
    log_party("POST_REBUILD")
    return true
end

function scenarios.whiteout_new()
    local linked, why = scenarios.link_new()
    if not linked then return false, link_prerequisite_failure(why) end
    if (seen.sync_retrieve_done or 0) < 1 then return false, "linked capture was not returned to party" end
    local linked_key = new_key()
    if not linked_key then return false, "no linked key after the shared link_new body" end
    local starter_key, linked_slot
    for _, m in ipairs(party_keys()) do
        if boot_keys[m.key] then starter_key = m.key elseif m.key == linked_key then linked_slot = m.slot end
    end
    if not starter_key or not linked_slot or #party_keys() ~= 2 then
        return false, "expected a two-mon party of the boot starter plus the linked catch"
    end
    log_party("PRE_WHITEOUT")

    local linked_hp_addr = ram.wPartyMons + linked_slot * parts.profile.derived.party_struct_size + 1
    local walked, walk_why = walk_to_center(function()
        return rd(linked_hp_addr) * 256 + rd(linked_hp_addr + 1)
    end)
    if not walked then return false, walk_why end
    -- Both halves deposit; starting them together keeps each cartridge inside the PC menus
    -- (where the client's writes are disarmed) while the partner's mirrored box_mon arrives.
    log("AT_CENTER " .. D.player)
    if not wait_until(function() return partner_has_mark("AT_CENTER") end, 600,
                      "the partner at the Center") then return false, "the partner never reached the Center" end
    local tx0 = #storage_tx
    local phase = pc_drive({{"deposit", linked_slot + 1}}, "deposit-for-rebuild")
    if phase ~= "pc-done" then return false, "the PC deposit ended " .. phase end
    if #storage_tx < tx0 + 1 or storage_tx[tx0 + 1].event ~= "party_to_box"
       or storage_tx[tx0 + 1].key ~= linked_key then
        return false, "the deposit did not send party_to_box for the linked key"
    end
    local boxed = wait_until(function()
        local pt = PC.extend_point(play.point(), rd, symbols)
        if pt.party_count ~= 1 or pt.box_count < 1 then return nil end
        for _, m in ipairs(reads.read_active_box() or {}) do
            if reads.key(m) == linked_key then return pt end
        end
        return nil
    end, 180, "the catch physically in the active box over a starter-only party")
    if not boxed then
        local pt = PC.extend_point(play.point(), rd, symbols)
        return false, fmt("the deposit was not physically observable: party=%d box %d count=%d",
                          pt.party_count, pt.box_number, pt.box_count)
    end
    log("DEPOSITED_FOR_REBUILD " .. linked_key) -- extract_marks splits on the first space
    log(fmt("PC_BOX_AFTER party=%d box=%d count=%d", boxed.party_count, boxed.box_number, boxed.box_count))
    -- The server's half of the same fact, which only the runner can read (/api/status).
    if not wait_until(function() return file_contains(D.go_file, "BOTH_BOXED") end, 900,
                      "BOTH_BOXED from the runner") then
        return false, "the runner never confirmed both keys boxed on the server"
    end
    log("BOTH_BOXED status=true")
    local base = { rx = #storage_rx }
    for _, name in ipairs({"sync_retrieve_done", "sync_retrieve_failed", "force_faint",
                           "memorialize", "game_over"}) do base[name] = seen[name] or 0 end

    if D.player == "b" then
        -- B idles at its checkpoint for A's whole walk back, hunt and blackout; the rebuild
        -- reaches it on the client's own sync path, not through a second PC drive.
        local ok_b, why_b = await_rebuild(linked_key, base, 900)
        if not ok_b then return false, why_b end
        local saved_b, save_why_b = game_save("whiteout_new_b")
        if not saved_b then return false, save_why_b end
        return true, "mirrored the partner's whiteout rebuild and saved " .. linked_key
    end

    local back, back_why = walk_back_to_route1()
    if not back then return false, back_why end
    local money_before = play.point().money
    log(fmt("MONEY_BEFORE %d", money_before))

    -- Baselines, so a faint from link_new's own catch battle could never be read as this KO.
    local ko_before, faint_before = battle_site_keys[starter_key] or 0, seen.faint or 0
    local hunted, driver = hunt("switch-hold", {start_active = true, keep_driver = true})
    if hunted ~= "linked-active-menu" then
        return false, "A never reached a wild battle menu with its starter out: " .. tostring(hunted)
    end
    local move2, pp2 = rd(ram.wBattleMonMoves + 1), rd(ram.wBattleMonPP + 1) % 64
    if move2 ~= 0x2D then
        driver.close()
        return false, fmt("the starter's move slot 2 is $%02X, not GROWL ($2D)", move2)
    end
    log(fmt("GROWL_SLOT move=%02X pp=%d", move2, pp2))
    local function starter_ko()
        return (battle_site_keys[starter_key] or 0) > ko_before
            or ((seen.faint or 0) > faint_before and sent_events.faint
                and sent_events.faint.key == starter_key) or nil
    end
    -- GROWL's stat-drop line ends in `prompt` (_FellText, pret data/text/text_3.asm:122-124,
    -- printed by StatModifierDownEffect engine/battle/effects.asm:691-741), and PromptText ->
    -- ManualTextScroll -> WaitForTextScrollButtonPress (home/text.asm:209-217, home/joypad2.asm:
    -- 55-81) blocks on A/B forever outside a link battle. driver.wait_menu only IDLES, so after
    -- turn 1 the engine sat on that down-arrow and the next DisplayBattleMenu never came
    -- (receipt: e2e_whiteout_new_a "GROWL turn 1 -> player_move hp=14" then nothing). Tap B
    -- between short waits, exactly as the hunt plan's own wrapper does for the same reason
    -- (lua/tests/gen1_rb_hunt_inputs.lua:100-112). B is not in the battle menu's watched keys
    -- (RIGHT|A / LEFT|A), so a stray tap there is ignored, not a menu action.
    local function wait_menu_tapping_b(budget)
        local used = 0
        while used < budget do
            local r = driver.wait_menu(240)
            used = used + r.frames
            if r.ok or r.why == "battle_over" then return r end
            for _ = 1, 32 do yield_frame(pulse_at_frame("B")); used = used + 1 end
        end
        return { ok = false, why = "timeout" }
    end
    -- Every exit says which one it was: the silent `break`s are what made the receipt above
    -- unreadable. GROWL (0 power, 40 PP = the 40-turn budget) is the right move here and Tackle
    -- would be wrong: the starter must NOT KO the foe, and the -1 Attack per turn cannot slow
    -- the foe below MIN_NEUTRAL_DAMAGE = 2 (constants/battle_constants.asm:47, added back in
    -- CalculateDamage engine/battle/core.asm:4452-4459), 3 after STAB. A 14-19 HP L5 starter
    -- therefore falls in <= 10 turns to Route 1's GUST/TACKLE (data/wild/maps/Route1.asm).
    local exit_turn, exit_why = 0, "budget"
    for turn = 1, 40 do
        exit_turn = turn
        if starter_ko() then exit_why = "ko" break end
        local menu = wait_menu_tapping_b(1800)
        if not menu.ok then exit_why = "menu:" .. tostring(menu.why) break end
        if starter_ko() then exit_why = "ko" break end
        local chosen = driver.choose("FIGHT")
        if not chosen.ok then exit_why = "choose:" .. tostring(chosen.why) break end
        local move = driver.commit_move(2, 900)
        log(fmt("GROWL turn %d -> %s hp=%d", turn, tostring(move.why),
                rd(ram.wBattleMonHP) * 256 + rd(ram.wBattleMonHP + 1)))
        if move.why == "battle_over" then exit_why = "battle_over" break end
    end
    log(fmt("GROWL_LOOP_EXIT turn=%d why=%s", exit_turn, exit_why))
    driver.close()
    if not wait_until(starter_ko, 120, "the starter's engine faint site") then
        return false, "the wild foe never KO'd the starter"
    end
    log(fmt("STARTER_KO frame=%d key=%s", frame, starter_key))
    if not wait_until(function() return (seen.whiteout or 0) >= 1 end, 120, "TX whiteout") then
        return false, "the client never sent whiteout"
    end
    log(fmt("TX whiteout x%d", seen.whiteout))

    local blacked_out, arrived = nil, false
    for _ = 1, 9000 do
        if not blacked_out and tile_text("blacked out") then blacked_out = frame end
        if rd(ram.wCurMap) == 0 and overworld_ok() then arrived = true;break end
        yield_frame(pulse_at_frame("B")) -- B advances text and never talks to an NPC
    end
    if not arrived then
        return false, fmt("A never reached the Pallet Town blackout checkpoint (map=%d)", rd(ram.wCurMap))
    end
    log(blacked_out and fmt("BLACKED_OUT_TEXT frame=%d", blacked_out)
        or "BLACKED_OUT_TEXT unavailable: the text advanced before the probe")
    local site = reads.read_map()
    log(fmt("BLACKOUT_SITE map=%d x=%d y=%d", site.map, site.x, site.y))
    if site.map ~= 0 or site.x ~= 5 or site.y ~= 6 then
        return false, fmt("the blackout warp was map=%d (%d,%d), not Pallet Town (5,6)", site.map, site.x, site.y)
    end
    local money_after = play.point().money
    log(fmt("MONEY_AFTER %d", money_after))
    if money_after ~= math.floor(money_before / 2) then
        return false, fmt("money went %d -> %d, not the BCD halving to %d",
                          money_before, money_after, math.floor(money_before / 2))
    end
    log(fmt("MONEY_HALVED before=%d after=%d", money_before, money_after))
    if (seen.whiteout or 0) ~= 1 then return false, fmt("%d whiteout events, not 1", seen.whiteout or 0) end

    local ok_a, why_a = await_rebuild(linked_key, base, 300)
    if not ok_a then return false, why_a end
    if not wait_until(function() return (seen.rebuild_done or 0) >= 1 end, 120, "rebuild_done") then
        return false, "the server never closed the rebuild"
    end
    log(fmt("REBUILD_DONE rebuild_start=%d rebuild_done=%d", seen.rebuild_start or 0, seen.rebuild_done or 0))
    local saved, save_why = game_save("whiteout_new_a")
    if not saved then return false, save_why end
    return true, "whited out with an empty party and was rebuilt from the PC: " .. linked_key
end

-- A7 (S-4): a REAL poison faint and the blackout that follows it, on Blue's lone Charmander.
--
-- Shape: B (Blue) leaves the BATTLE fixture's Route 1 park tile (10,35), walks north to
-- Viridian Forest, paces the two grass half-blocks (18,41)<->(18,40) running from everything
-- that is not a Weedle and Growling at the Weedle until Charmander is PSN, RUNs, then shuttles
-- the non-grass pair (18,43)<->(18,44) -- encounter-free by construction, not by luck -- until
-- the 1-HP-per-4th-step poison tick (pret engine/events/poison.asm:10-12,26-41) drops the ONLY
-- mon. Every route, geometry, wild-data and poison fact this leg stands on is pinned to a pret
-- file:line in the driver's own header (lua/tests/gen1_rb_forest_inputs.lua:1-120); nothing is
-- restated here, and nothing below is a remembered constant.
--
-- The blackout is the point. With one mon the client's emit_faint must send `whiteout` AT the
-- poison_faint site (lua/gen1/client.lua:562-563 -> :495-504), one hook BEFORE the engine
-- reaches the blackout site (ResetStatusAndHalveMoneyOnBlackout, bank 1 $40B0 --
-- data/games/gen1_rby/engine_signals.json:74-81), so the blackout site's own fallback
-- (client.lua:565-566) must find whiteout_sent already true. That ordering is asserted.
--
-- A (Red) has no leg here: it only has to outlive B's walk, hunt, shuttle and blackout, the
-- same idle half deadzone_new's A plays (:1557-1558).
--
-- RNG, never a driver fault: the hunt bound is 3x the pinned mean (60 encounters,
-- gen1_rb_forest_inputs.lua:130) and roughly a fifth of Weedle battles KO Charmander before
-- the poison lands. Both come back as "RNG: ..." reasons -- tools/e2e_duo.py:242-248
-- GEN1_RNG_REASON_CLASS must map them to CAUSE_RNG for the bounded retry to see them.
function scenarios.poison_new()
    if not wait_go() then return false, "no go-file" end
    if D.player ~= "b" then
        log("POISON_IDLE a")
        -- B's walk + hunt + shuttle is the longest leg in the suite and the runner gives the
        -- scenario 2400 s (tools/e2e_duo.py:191). A idling out FIRST turns B's still-running
        -- (and still-legal) leg into a pair failure, so A's bound is the scenario's own budget
        -- less a reserve for its game_save below -- never a smaller constant of its own.
        if not wait_partner_done((D.timeout_secs or 2400) - 300) then
            return false, "the idle partner never finished the poison leg"
        end
        local saved_a, why_a = game_save("poison_new_a")
        if not saved_a then return false, why_a end
        return true, "idled through the partner's poison faint and blackout"
    end

    local Forest = dofile(ROOT .. "/lua/tests/gen1_rb_forest_inputs.lua")
    local start = party_keys()
    if #start ~= 1 then
        return false, fmt("the poison fixture must hold exactly one mon, not %d", #start)
    end
    local starter_key = start[1].key
    log_party("PRE_POISON")

    -- Ordered signal trace plus the poison_faint site receipt. The harness already wrapped the
    -- client's on_signal once (:124-142); wrapping it again here keeps this leg's trace its own.
    -- `frame` and `seen` are the main loop's, and both are readable from the hook.
    local sigs, sites, whiteouts_at_blackout = {}, {}, nil
    local prev_on_signal = gclient.on_signal
    gclient.on_signal = function(self_, sig)
        sigs[#sigs + 1] = sig.kind
        if sig.kind == "poison_faint" then
            -- signals.lua:60-66: the point carries wWhichPokemon, the slot that just fainted.
            local which = (sig.point and sig.point.which) or -1
            sites[#sites + 1] = which
            log(fmt("POISON_FAINT_SITE frame=%d slot=%d", frame, which))
        elseif sig.kind == "blackout" then
            whiteouts_at_blackout = seen.whiteout or 0
            log(fmt("BLACKOUT_SIGNAL frame=%d whiteout_so_far=%d", frame, whiteouts_at_blackout))
        end
        return prev_on_signal(self_, sig)
    end
    local base = {}
    for _, name in ipairs({"faint", "whiteout", "no_catch"}) do base[name] = seen[name] or 0 end
    log(fmt("POISON_BASELINE key=%s faint=%d whiteout=%d no_catch=%d signals=%d",
            starter_key, base.faint, base.whiteout, base.no_catch, #sigs))

    -- One loop for all three forest drivers: they share the route-module protocol
    -- (gen1_rb_forest_inputs.lua:4-12), so only the terminal set differs. The caller owns the
    -- frame, exactly as hunt() drives the Route 1 module (:305-319).
    local function drive(route, tag, terminals)
        local last = nil
        for _ = 1, (D.hunt_frames or 90000) do
            local point = play.point()
            -- A wild foe that KOs the lone starter is the game's RNG. Name it HERE, before the
            -- route modules' own `party_hp > 0` assertions (gen1_rb_route1_inputs.lua:42-43)
            -- turn it into a bare scenario error no retry rule could classify.
            if point.battle ~= 0 and point.party_hp == 0 then return "starter-koed" end
            local buttons, phase = route.step(nil, nil, point, emu.framecount())
            if phase ~= last then
                last = phase
                log(fmt("POISON_PHASE %s %s @%d map=%d (%d,%d) battle=%d hp=%d", tag, phase,
                        emu.framecount(), point.map, point.x, point.y, point.battle, point.party_hp))
            end
            -- Not the game's RNG: a live party in a battle this leg never asks for (wIsInBattle
            -- 2 is a TRAINER battle, pret engine/battle/core.asm:6691-6692) means the fixture or
            -- the route is wrong. Carry the value out so the FINAL failure names it, and never
            -- let it borrow the "starter-koed" RNG string above.
            if phase == "unexpected-battle" then
                return fmt("unexpected-battle (wIsInBattle=%d party_hp=%d)", point.battle, point.party_hp)
            end
            if terminals[phase] then return phase end
            yield_frame(buttons)
        end
        return tag .. "-timeout"
    end

    -- Leg 1: Route 1 (10,35) -> Viridian Forest (18,41). Route 1's only northbound corridor is
    -- solid grass (15 forced steps at 25/256, gen1_rb_forest_inputs.lua:112-120), so incidental
    -- wild battles on this leg are EXPECTED; the module RUNs from them and logs
    -- INCIDENTAL_BATTLE. They are not failures.
    local walked = drive(Forest.new({ player = D.player }, { log = log }), "walk",
                         { ["forest-parked"] = true, ["unknown-map"] = true })
    if walked == "starter-koed" then
        return false, "RNG: a wild foe knocked the starter out before the poisoning"
    end
    if walked ~= "forest-parked" then return false, "the walk to Viridian Forest ended " .. walked end
    log(fmt("FOREST_PARKED map=%d (%d,%d)", rd(ram.wCurMap), rd(ram.wXCoord), rd(ram.wYCoord)))

    -- Leg 2: the hunt. Same battle driver the Route 1 hunt builds (:279-297). The driver only
    -- looks addresses up by NAME and never iterates that table (gen1_battle_driver.lua:63-80),
    -- so the whole .sym map is a valid bundle; `sites` IS iterated (:69), so it stays curated.
    local driver = Driver.new({
        step = yield_buttons, u8 = rd, addresses = symbols,
        sites = { display_battle_menu = rom.DisplayBattleMenu.addr,
                  move_selection_menu = rom.MoveSelectionMenu.addr,
                  select_enemy_move = rom.SelectEnemyMove.addr,
                  execute_player_move = rom.ExecutePlayerMove.addr,
                  execute_enemy_move = rom.ExecuteEnemyMove.addr },
    })
    local forest_hunt = Forest.hunt({ player = D.player }, { driver = driver, step = yield_buttons,
                                                            rd = rd, symbols = symbols, log = log })
    local hunted = drive(forest_hunt, "hunt", { poisoned = true, ["hunt-exhausted"] = true,
                                                ["starter-koed"] = true, ["hunt-stuck"] = true })
    driver.close()
    if hunted == "hunt-exhausted" then
        return false, "RNG: the forest hunt spent its encounter budget without a poisoning"
    end
    if hunted == "starter-koed" then
        return false, "RNG: a wild foe knocked the starter out before the poisoning"
    end
    if hunted ~= "poisoned" then return false, "the forest hunt ended " .. hunted end
    -- PSN is bit 3 of the status byte (constants/battle_constants.asm:64), mask $08, and
    -- ReadPlayerMonCurHPAndStatus has copied it into the party struct (core.asm:280-281).
    local status_addr = assert(symbols.wPartyMon1Status, "no symbol wPartyMon1Status")
    local status = rd(status_addr)
    if math.floor(status / 8) % 2 ~= 1 then
        return false, fmt("wPartyMon1Status is $%02X, which carries no PSN bit ($08)", status)
    end
    log(fmt("POISON_PSN encounters=%d steps=%d status=%02X",
            forest_hunt.encounters, forest_hunt.grass_steps, status))

    -- gen1_rb_point_fields.lua:11-18 decodes wPlayerMoney's three raw BCD bytes and nothing
    -- else in the point touches money, so this IS the raw read the oracle halves.
    local money_before = play.point().money
    log(fmt("MONEY_BEFORE %d", money_before))
    frames(120) -- let the final RUN's own battle_end land BEFORE the suffix mark
    local mark = #sigs

    -- Leg 3: the shuttle. (18,43)/(18,44) are non-grass, and a non-grass half-block in the
    -- FOREST tileset can never roll (wild_encounters.asm:38-46), so nothing can interrupt the
    -- poison ticks -- which is what makes the suffix assertion below meaningful.
    local fell = drive(Forest.shuttle({ player = D.player }, { log = log }), "shuttle",
                       { ["poison-fainted"] = true, ["unknown-map"] = true })
    if fell ~= "poison-fainted" then return false, "the poison shuttle ended " .. fell end

    if not wait_until(function() return (seen.faint or 0) > base.faint end, 120, "TX faint") then
        return false, "the client never sent faint for the poisoned starter"
    end
    local faint_key = sent_events.faint and sent_events.faint.key
    if faint_key ~= starter_key then
        return false, fmt("the faint event named %s, not the starter %s", tostring(faint_key), starter_key)
    end
    log("TX faint " .. starter_key)
    if not wait_until(function() return (seen.whiteout or 0) > base.whiteout end, 120, "TX whiteout") then
        return false, "the client never sent whiteout"
    end
    log(fmt("TX whiteout x%d", (seen.whiteout or 0) - base.whiteout))

    local blackout_addr = assert(symbols.wOutOfBattleBlackout, "no symbol wOutOfBattleBlackout")
    local blacked_out, flagged, arrived = nil, nil, false
    for _ = 1, 9000 do
        if not blacked_out and tile_text("blacked out") then blacked_out = frame end
        -- poison.asm:107-114 writes $ff here and home/overworld.asm:318-320 turns it into
        -- `jp HandleBlackOut`; nothing clears it before the next completed step, and the loop
        -- breaks at the Pallet checkpoint without taking one.
        if not flagged and rd(blackout_addr) == 0xFF then flagged = frame end
        if rd(ram.wCurMap) == 0 and overworld_ok() then arrived = true;break end
        yield_frame(pulse_at_frame("B")) -- B advances text and never talks to an NPC
    end
    if not arrived then
        return false, fmt("B never reached the Pallet Town blackout checkpoint (map=%d)", rd(ram.wCurMap))
    end
    log(blacked_out and fmt("BLACKED_OUT_TEXT frame=%d", blacked_out)
        or "BLACKED_OUT_TEXT unavailable: the text advanced before the probe")
    if not flagged then
        return false, "wOutOfBattleBlackout never read 0xFF, so the game never took HandleBlackOut"
    end
    log(fmt("BLACKOUT_FLAG frame=%d value=FF", flagged))
    local site = reads.read_map()
    log(fmt("BLACKOUT_SITE map=%d x=%d y=%d", site.map, site.x, site.y))
    if site.map ~= 0 or site.x ~= 5 or site.y ~= 6 then
        return false, fmt("the blackout warp was map=%d (%d,%d), not Pallet Town (5,6)",
                          site.map, site.x, site.y)
    end
    local money_after = play.point().money
    log(fmt("MONEY_AFTER %d", money_after))
    if money_after ~= math.floor(money_before / 2) then
        return false, fmt("money went %d -> %d, not the BCD halving to %d",
                          money_before, money_after, math.floor(money_before / 2))
    end
    log(fmt("MONEY_HALVED before=%d after=%d", money_before, money_after))
    -- ResetStatusAndHalveMoneyOnBlackout ends `predef_jump HealParty`, so HP coming back is
    -- proof HandleBlackOut ran to completion rather than wedging on a text box.
    local healed = party_keys()
    if #healed ~= 1 or healed[1].hp <= 0 then
        return false, fmt("after the blackout the party held %d mon(s) at hp=%d, not one healed starter",
                          #healed, healed[1] and healed[1].hp or -1)
    end
    log(fmt("PARTY_HEALED key=%s hp=%d", healed[1].key, healed[1].hp))

    if (seen.whiteout or 0) - base.whiteout ~= 1 then
        return false, fmt("%d whiteout event(s) for one blackout, not 1",
                          (seen.whiteout or 0) - base.whiteout)
    end
    if #sites < 1 then return false, "the client never reached the poison_faint site" end
    if sites[#sites] ~= 0 then
        return false, fmt("the last poison_faint site named wWhichPokemon=%d, not slot 0", sites[#sites])
    end
    if (whiteouts_at_blackout or base.whiteout) <= base.whiteout then
        return false, "whiteout was sent at the blackout site, not from the poison faint"
    end
    -- The suffix, i.e. everything after the last RUN: a battle_faint or a battle_end in here
    -- would mean this blackout came out of a battle, not the poison. Earlier battles emit both
    -- legitimately, which is why the window starts at `mark` and not at 0.
    local order, stray = {}, nil
    for i = mark + 1, #sigs do
        local kind = sigs[i]
        if kind == "poison_faint" or kind == "blackout" then order[#order + 1] = kind end
        if kind == "battle_faint" or kind == "battle_end" then stray = stray or kind end
    end
    if stray then return false, "a " .. stray .. " signal fired after the final RUN" end
    if order[1] ~= "poison_faint" or order[#order] ~= "blackout" then
        return false, "the post-RUN signal order was [" .. table.concat(order, ",")
                      .. "], not poison_faint->blackout"
    end
    log(fmt("SIGNAL_ORDER poison_faint->blackout ok faints=%d suffix=%d", #sites, #sigs - mark))

    local saved, why = game_save("poison_new_b")
    if not saved then return false, why end
    return true, "poisoned in Viridian Forest, blacked out to Pallet and saved " .. starter_key
end

-- ── A13 (D-11 swap half, W-4): the rival team swap on Route 22 ───────────────────────
--
-- Prerequisite is link_new on BOTH halves. The swap ships the PARTNER's live party, and the
-- server only has one to ship once B's snapshots have reached its blob cache: every hello /
-- tick party entry carries `blob_hex` (lua/gen1/client.lua:90-100) and server/state.py:
-- 2799-2843 ingests it, while queue_rival_team_swap refuses with "partner has no cached party
-- blobs" when it is empty (state.py:2866-2868). B therefore idles on its checkpoint rather
-- than closing: its tick cadence is what keeps that cache warm across A's whole walk.
--
-- A walks Route 1 -> Viridian -> the WEST exit -> Route 22 -> the rival trigger tile and then
-- fights Rival1. The walk, the trigger geometry and the fight are all
-- lua/tests/gen1_rb_route22_inputs.lua, whose header carries the pret citation for every
-- coordinate (connection arithmetic, the ledge that forces the detour, the four unavoidable
-- grass steps, the in-battle party-menu geometry); nothing is restated here.
--
-- The wire. The client's battle_begin arm sends `trainer_battle_start{trainer_id}` for any
-- opponent id >= OPP_ID_OFFSET (lua/gen1/client.lua:511-518). 225 = OPP_RIVAL1 is in the Gen 1
-- adapter's rival set (server/adapters/gen1_rby.py:318-320), so with --rival-team-swap on,
-- _handle_trainer_battle_start queues `replace_rival_team` (server/state.py:2882-2915) and the
-- queue drains at the END of handling that same event (state.py:379-388) -- one round trip.
-- The client may still hold the reply: the enemy party may only be rewritten between
-- InitBattleCommon staging wEnemyMonPartyPos = $FF (pret engine/battle/core.asm:6689-6690,
-- AFTER DoBattleTransitionAndInitBattleVariables at :6680) and LoadEnemyMonData replacing it
-- with the sent-out index (:6055), so an early reply is parked in `pending_rival` and released
-- by rival_window_tick (lua/gen1/client.lua:331-402), still bounded by RIVAL_SWAP_FRAMES = 120
-- from battle_begin (:19-22). With the server answering in one round trip, `error=late_reply`
-- on the wire is a FAIL here, never RNG.
function scenarios.rival_swap_new()
    local linked, why = scenarios.link_new()
    if not linked then return false, link_prerequisite_failure(why) end

    if D.player ~= "a" then
        log("RIVAL_IDLE b")
        if not wait_until(function() return partner_has_mark("RIVAL_DONE") or partner_done() end,
                          2400, "A's rival leg") then
            return false, "the idle partner never saw A finish the rival leg"
        end
        local saved_b, why_b = game_save("rival_swap_new_b")
        if not saved_b then return false, why_b end
        return true, "idled through the partner's rival battle and saved"
    end

    local Route22 = dofile(ROOT .. "/lua/tests/gen1_rb_route22_inputs.lua")
    local derived = parts.profile.derived
    log_party("PRE_RIVAL")

    -- The trigger's two preconditions, both set by OaksLabRivalLeavesWithPokedexScript when
    -- Oak hands the Pokedex over (pret scripts/OaksLab.asm:634,636) and both read by
    -- Route22DefaultScript before it looks at the player's coordinates (scripts/Route22.asm:
    -- 59-60,72-73). Their ordinals are 1312 and 1319 -- wEventFlags byte 164, bits 0 and 7 --
    -- counted out of constants/event_constants.asm the same way gen1_rb_point_fields.lua:3-4
    -- counts EVENT_GOT_OAKS_PARCEL (57) and gen1_scripted_play.lua:113 counts EVENT_GOT_POKEDEX
    -- (37); that counter reproduces both of those pinned values, which is its control.
    -- Only the "battle" fixture chain runs the Pokedex handover (tools/gen1_fixtures.py:40,
    -- "battle": "lab,parcel,route1,save" vs "town": "lab,save"), so a town-fixture A would walk
    -- the whole route and meet nobody. Name that here instead of 20000 frames later.
    local events = rd(assert(symbols.wEventFlags) + 164)
    log(fmt("RIVAL_EVENTS byte164=%02X first=%d wants=%d", events, events % 2,
            math.floor(events / 128) % 2))
    if events % 2 ~= 1 or math.floor(events / 128) % 2 ~= 1 then
        return false, fmt("the Route 22 rival events are not armed (wEventFlags[164]=%02X): "
                          .. "this fixture never ran the Pokedex chain", events)
    end

    -- This leg's own receipts. The file-wide tees (:161-179, :183-203) keep a fixed set of
    -- names and drop `blobs_hex`, so wrap the already-wrapped hooks once more here, the way
    -- clause_watch does (:616-630), instead of widening them for every other scenario.
    local swap = {}
    local prev_cmd = gclient.handle_command
    gclient.handle_command = function(self_, cmd)
        if cmd and cmd.cmd == "replace_rival_team" and not swap.rx then
            swap.rx = cmd
            log(fmt("RX replace_rival_team n=%s", tostring(cmd.n or #(cmd.blobs_hex or {}))))
        end
        return prev_cmd(self_, cmd)
    end
    local prev_send = C.send
    C.send = function(line)
        local ok, msg = pcall(json.decode, line)
        if ok and type(msg) == "table" then
            if msg.event == "trainer_battle_start" and not swap.start_tx then swap.start_tx = msg end
            if msg.event == "rival_team_replaced" and not swap.reply then
                swap.reply, swap.reply_frame = msg, frame
            end
        end
        return prev_send(line)
    end
    -- battle_begin fires at InitBattleCommon for WILD battles too (data/games/gen1_rby/
    -- engine_signals.json sites.battle_begin, capture_offset 0), so the window's origin is the
    -- one whose point names the rival -- not merely the first battle of the leg.
    local prev_signal = gclient.on_signal
    gclient.on_signal = function(self_, sig)
        if sig.kind == "battle_begin" and sig.point and sig.point.cur_opponent == Route22.RIVAL1
           and not swap.begin_frame then
            swap.begin_frame = frame
            log(fmt("RIVAL_BATTLE_BEGIN frame=%d opponent=%d", frame, sig.point.cur_opponent))
        end
        return prev_signal(self_, sig)
    end

    local function hex_bytes(hex)
        local out = {}
        for j = 1, #hex, 2 do out[#out + 1] = tonumber(hex:sub(j, j + 1), 16) end
        return out
    end
    -- Byte-compare the three parallel enemy arrays against the blobs the command carried, in
    -- the shape lua/gen1/writes.lua:105-133 writes them: count, species list + $FF terminator,
    -- then struct / OT name / nickname per slot. Returns a failure string, or nil.
    local function compare_enemy_party()
        local blobs = {}
        for i, hex in ipairs(swap.rx.blobs_hex or {}) do blobs[i] = hex_bytes(hex) end
        local n = #blobs
        if n < 1 then return "replace_rival_team carried no blobs" end
        local count = rd(ram.wEnemyPartyCount)
        if count ~= n then return fmt("wEnemyPartyCount is %d, not the %d blobs the command carried", count, n) end
        for i = 1, n do
            local got, want = rd(ram.wEnemyPartySpecies + i - 1), blobs[i][1]
            if got ~= want then return fmt("wEnemyPartySpecies[%d] is %d, not %d", i - 1, got, want) end
        end
        local terminator = rd(ram.wEnemyPartySpecies + n)
        if terminator ~= 0xFF then return fmt("the species list terminator is %02X, not FF", terminator) end
        for i = 1, n do
            local k, blob = i - 1, blobs[i]
            local arrays = { { ram.wEnemyMons, derived.battle_struct_size, 0, "struct" },
                             { ram.wEnemyMonOT, derived.name_length, derived.battle_struct_size, "OT name" },
                             { ram.wEnemyMonNicks, derived.name_length,
                               derived.battle_struct_size + derived.name_length, "nickname" } }
            for _, a in ipairs(arrays) do
                for j = 1, a[2] do
                    local got, want = rd(a[1] + k * a[2] + j - 1), blob[a[3] + j]
                    if got ~= want then
                        log(fmt("ENEMY_MONS_MISMATCH slot=%d", k))
                        return fmt("enemy %s byte %d of slot %d is %02X, not the blob's %02X",
                                   a[4], j, k, got, want)
                    end
                end
            end
        end
        log(fmt("ENEMY_MONS_MATCH slots=%d", n))
        swap.lead_species = blobs[1][1]
        return nil
    end

    -- One per-frame witness, driven from the route loop below so the reads land on the frames
    -- the engine is actually in: the compare runs the frame the reply is seen (before any turn
    -- can write HP back into wEnemyMons), the send-out read the frame LoadEnemyMonData replaces
    -- the staged $FF with the party index it chose (core.asm:6053-6055).
    local function witness()
        if swap.failure then return end
        if swap.reply and not swap.compared then
            swap.compared = true
            if swap.reply.error then
                swap.failure = "the client refused the swap: error=" .. tostring(swap.reply.error)
                return
            end
            if not swap.rx then swap.failure = "rival_team_replaced without a replace_rival_team"; return end
            log(fmt("RIVAL_TEAM_REPLACED frame=%d within=%d", swap.reply_frame,
                    swap.begin_frame and (swap.reply_frame - swap.begin_frame) or -1))
            swap.failure = compare_enemy_party()
            return
        end
        if swap.compared and not swap.sent_out and rd(ram.wEnemyMonPartyPos) ~= 0xFF then
            swap.sent_out = true
            local species = rd(ram.wEnemyMonSpecies)
            log(fmt("ENEMY_SENDOUT species=%d expected=%d", species, swap.lead_species or -1))
            if species ~= swap.lead_species then
                swap.failure = fmt("the enemy sent out species %d, not the partner's slot-1 %d",
                                   species, swap.lead_species or -1)
            end
        end
    end

    local route = Route22.new({ player = D.player }, { log = log })
    local terminal = { ["rival-won"] = true, ["rival-lost"] = true, ["rival-drawn"] = true,
                       ["rival-never-triggered"] = true, ["starter-koed"] = true,
                       ["unknown-map"] = true }
    local last, phase = nil, nil
    for _ = 1, (D.hunt_frames or 90000) do
        local point = play.point()
        local buttons
        buttons, phase = route.step(nil, nil, point, emu.framecount())
        if phase ~= last then
            last = phase
            log(fmt("RIVAL_PHASE %s @%d map=%d (%d,%d) battle=%d opponent=%d hp=%d", phase,
                    emu.framecount(), point.map, point.x, point.y, point.battle,
                    point.opponent, point.party_hp))
        end
        witness()
        if terminal[phase] then break end
        yield_frame(buttons)
    end
    if not terminal[phase] then return false, "the Route 22 leg made no bounded progress (" .. tostring(phase) .. ")" end
    if phase == "starter-koed" then
        return false, "RNG: a wild foe knocked the lead out on the way to Route 22"
    end
    if phase == "rival-never-triggered" then
        return false, "A stood on the Route 22 trigger tile and no rival battle started"
    end
    if phase == "unknown-map" then
        return false, fmt("the walk left the planned map chain at map=%d (%d,%d)",
                          rd(ram.wCurMap), rd(ram.wXCoord), rd(ram.wYCoord))
    end

    if not swap.start_tx then return false, "the client never sent trainer_battle_start" end
    if swap.start_tx.trainer_id ~= Route22.RIVAL1 then
        return false, fmt("trainer_battle_start named trainer_id %s, not Rival1's %d",
                          tostring(swap.start_tx.trainer_id), Route22.RIVAL1)
    end
    if not swap.rx then return false, "the server never sent replace_rival_team for the rival battle" end
    if not swap.reply then return false, "the client never answered with rival_team_replaced" end
    if swap.failure then return false, swap.failure end
    if not swap.sent_out then return false, "the enemy never left the staged $FF party position" end
    log(fmt("RIVAL_RESULT %s", phase == "rival-won" and "win" or (phase == "rival-lost" and "loss" or "draw")))

    -- The post-battle script (pret scripts/Route22.asm:148-186 on a win, the blackout on a
    -- loss) still owns the frame: pulse B until the write-safe overworld checkpoint holds, the
    -- way the poison leg walks out of its blackout (:2497-2508). B never talks to an NPC.
    local settled = false
    for _ = 1, 9000 do
        if overworld_ok() then settled = true break end
        yield_frame(pulse_at_frame("B"))
    end
    if not settled then
        return false, fmt("no overworld checkpoint after the rival battle (map=%d)", rd(ram.wCurMap))
    end
    log_party("POST_RIVAL")
    log("RIVAL_DONE")
    local saved, why_save = game_save("rival_swap_new_a")
    if not saved then return false, why_save end
    return true, fmt("rival team swapped to the partner's %d mon(s) and the battle was a %s",
                     swap.rx.n or #(swap.rx.blobs_hex or {}),
                     phase == "rival-won" and "win" or (phase == "rival-lost" and "loss" or "draw"))
end

local scen = scenarios[D.scenario]
if not scen then finish(false, "no gen1_new scenario " .. tostring(D.scenario)) end
local co = coroutine.create(function()
    -- --idle-jitter: BizHawk is deterministic, so a retry only changes the game RNG through
    -- timing; the harness writes idle_jitter (+37 per attempt) and checks applied == requested.
    local requested, applied = D.idle_jitter or 0, 0
    for _ = 1, requested do yield_frame(); applied = applied + 1 end
    log(fmt("JITTER requested=%d applied=%d attempt=%d", requested, applied, D.attempt or 1))
    return scen()
end)
local timeout = D.timeout_frames or 150000
while true do
    local ok, pass, msg = coroutine.resume(co)
    if not ok then finish(false, "scenario error: " .. tostring(pass)) end
    if coroutine.status(co) == "dead" then finish(pass, msg) end
    step(nil)
    if frame % 3600 == 0 then log(fmt("heartbeat f=%d party=%d connected=%s", frame, memory.read_u8(ram.wPartyCount, "System Bus"), tostring(C.connected()))) end
    if frame > timeout then finish(false, "scenario timeout after " .. timeout .. " frames") end
end
