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
local Center = dofile(ROOT .. "/lua/tests/gen1_rb_center_inputs.lua")
local Driver = dofile(ROOT .. "/lua/tests/gen1_battle_driver.lua")
local Play = dofile(ROOT .. "/lua/tests/gen1_scripted_play.lua")

log("duo instance " .. D.player .. " scenario=" .. D.scenario .. " game=" .. D.game)
log(fmt("attempt %d of 2", D.attempt or 1))
pcall(function() client.speedmode(D.speed or 1600) end)

local title, header = Entry.detect_title(function(a) return memory.read_u8(a, "ROM") end)
if not title then finish(false, "not a Gen 1 cartridge (header " .. tostring(header) .. ")") end
local deps = Entry.bizhawk_deps()
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
    if name == "hello" or name == "trade_offer" or name == "menu_result" or name == "trade_done"
       or name == "faint" then
        sent_events[name] = msg
    end
    if name ~= "tick" then log("TX " .. (line:sub(1, 220))) end
    if name == "faint" and D.player == "b" and D.scenario == "linked_faint_active_new" then
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
    if c == "trade_mask" or c == "show_menu" or c == "apply_trade" or c == "force_faint" then
        received_commands[c] = cmd
    end
    if c ~= "noop" then
        log("RX " .. c .. (cmd.key and (" key=" .. tostring(cmd.key)) or "") .. (cmd.text and (" text=" .. tostring(cmd.text)) or ""))
    end
    if c == "game_over" then log("GAME_OVER RX game_over") end
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

-- ── Scenarios ────────────────────────────────────────────────────────────────────────
local scenarios = {}

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

-- T-3/T-4: reuse the real Route 1 capture/link, walk to the *native* receptionist, then
-- let the two cartridges perform one prompt and one apply. The Python runner checks SRAM
-- and the server's durable link after both instances have exited.
function scenarios.trade_new()
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
    local function require_route(label, ok, detail)
        if not ok then error(label .. ": " .. tostring(detail), 0) end
    end
    local linked_hp_addr = ram.wPartyMons + linked_slot * parts.profile.derived.party_struct_size + 1
    local route = Center.new({
        read = rd, ram = ram, row = tile_row, frame = function() return frame end,
        log = log, invariant = require_route, check = require_route, start = "route1",
        menu_addr = {wTopMenuItemX=symbols.wTopMenuItemX, wTopMenuItemY=symbols.wTopMenuItemY},
        linked_hp = function() return rd(linked_hp_addr) * 256 + rd(linked_hp_addr + 1) end,
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

    if D.player == "a" then
        local first_query, first_offer = seen.trade_query or 0, seen.trade_offer or 0
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
        for _ = 1, 240 do
            if (seen.menu_result or 0) > first_result then break end
            yield_frame(frame % 16 < 2 and {A=true} or {})
        end
        if (seen.menu_result or 0) ~= first_result + 1 or not sent_events.menu_result or
           sent_events.menu_result.choice ~= 1 then return false, "partner YES did not send menu_result choice=1" end
        log("PARTNER_ACCEPTED")
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
        if point.start_menu_save_index >= 0 and point.font_loaded then break end
        yield_frame(pulse_at_frame("Start"))
    end
    local point = play.point()
    if removed() then return unavailable() end
    if point.start_menu_save_index < 0 then return false, "START menu did not open before memorialize" end
    local pokemon_row = point.start_menu_save_index - 3 -- POKEMON precedes ITEM/name/SAVE
    for _ = 1, 180 do
        if removed() then return unavailable() end
        if rd(ram.wCurrentMenuItem) == pokemon_row then break end
        yield_frame(pulse_at_frame(rd(ram.wCurrentMenuItem) < pokemon_row and "Down" or "Up"))
    end
    if rd(ram.wCurrentMenuItem) ~= pokemon_row then return false, "START cursor missed POKEMON" end
    for _ = 1, 180 do
        if removed() then return unavailable() end
        if rd(symbols.wTopMenuItemY) == 1 and rd(symbols.wTopMenuItemX) == 0 then break end
        yield_frame(pulse_at_frame("A"))
    end
    if rd(symbols.wTopMenuItemY) ~= 1 or rd(symbols.wTopMenuItemX) ~= 0 then
        if removed() then return unavailable() end
        return false, "party menu did not open for linked FNT readback"
    end
    local offset = 40 * linked_slot + 17
    if not tile_text("FNT", offset) then
        if removed() then return unavailable() end
        local party = reads.read_party()
        if not party or not party[linked_slot + 1] then
            return false, "party unreadable while checking linked FNT slot"
        end
        if not tile_text(party[linked_slot + 1].nickname, 40 * linked_slot + 3) then
            return false, "linked party slot was not drawn for FNT readback"
        end
        return false, "party menu lacked linked slot FNT glyphs"
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
        if point.start_menu_save_index >= 0 and point.font_loaded then break end
        yield_frame(pulse_at_frame("Start"))
    end
    local point = play.point()
    if point.start_menu_save_index < 0 then return false, "START menu did not open for reorder" end
    local pokemon_row = point.start_menu_save_index - 3
    for _ = 1, 240 do
        if rd(ram.wCurrentMenuItem) == pokemon_row then break end
        yield_frame(pulse_at_frame(rd(ram.wCurrentMenuItem) < pokemon_row and "Down" or "Up"))
    end
    if rd(ram.wCurrentMenuItem) ~= pokemon_row then return false, "START cursor missed POKEMON row" end
    for _ = 1, 240 do
        if rd(symbols.wTopMenuItemY) == 1 and rd(symbols.wTopMenuItemX) == 0 then break end
        yield_frame(pulse_at_frame("A"))
    end
    if rd(symbols.wTopMenuItemY) ~= 1 or rd(symbols.wTopMenuItemX) ~= 0 or
       not tile_text(before[2].nickname, 40 + 3) then
        return false, "party menu did not draw linked slot 1 nickname"
    end
    for _ = 1, 240 do
        if rd(ram.wCurrentMenuItem) == 1 then break end
        yield_frame(pulse_at_frame(rd(ram.wCurrentMenuItem) < 1 and "Down" or "Up"))
    end
    if rd(ram.wCurrentMenuItem) ~= 1 then return false, "party cursor missed linked slot 1" end
    for _ = 1, 240 do
        if rd(ram.wTextBoxID) == 4 and rd(symbols.wTopMenuItemY) ~= 1 and rd(ram.wMaxMenuItem) >= 2 then break end
        yield_frame(pulse_at_frame("A"))
    end
    -- FIELD_MOVE_MON_MENU=$04 (pret constants/menu_constants.asm:9); the dynamic
    -- field-move list places SWITCH one row before CANCEL (start_sub_menus.asm:67-94).
    if rd(ram.wTextBoxID) ~= 4 then return false, "field move menu did not open for SWITCH" end
    local switch_row = rd(ram.wMaxMenuItem) - 1
    for _ = 1, 240 do
        local cur = rd(ram.wCurrentMenuItem)
        if cur == switch_row then break end
        yield_frame(pulse_at_frame(cur < switch_row and "Down" or "Up"))
    end
    if rd(ram.wCurrentMenuItem) ~= switch_row then return false, "field menu cursor missed SWITCH" end
    for _ = 1, 240 do
        if rd(symbols.wTopMenuItemY) == 1 and rd(symbols.wTopMenuItemX) == 0 and
           rd(symbols.wMenuItemToSwap) == 2 then break end
        yield_frame(pulse_at_frame("A"))
    end
    if rd(symbols.wMenuItemToSwap) ~= 2 then return false, "first SWITCH choice did not latch slot 1" end
    for _ = 1, 240 do
        if rd(ram.wCurrentMenuItem) == 0 then break end
        yield_frame(pulse_at_frame("Up"))
    end
    if rd(ram.wCurrentMenuItem) ~= 0 then return false, "second SWITCH cursor missed slot 0" end
    for _ = 1, 240 do
        local now = reads.read_party()
        if now and reads.key(now[1]) == key and reads.key(now[2]) == starter_key and
           rd(symbols.wMenuItemToSwap) == 0 then break end
        yield_frame(pulse_at_frame("A"))
    end
    local after = reads.read_party()
    if not after or reads.key(after[1]) ~= key or reads.key(after[2]) ~= starter_key then
        return false, "overworld SWITCH did not put linked mon in lead slot 0"
    end
    for _ = 1, 120 do
        if tile_text(after[1].nickname, 3) then break end
        yield_frame({})
    end
    if not tile_text(after[1].nickname, 3) then return false, "reordered party tilemap lacks lead nickname" end
    log("REORDER_LEAD " .. key .. " slot=0 from=1 tilemap=" ..
        Center.row(rd, ram.wTileMap, 0, 20))
    for _ = 1, 600 do
        if overworld_ok() then return true end
        yield_frame(pulse_at_frame("B"))
    end
    return false, "party/START menu did not close after reorder"
end

local function linked_faint_scenario(active)
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
        local old = gclient.on_battle_loop_head
        gclient.on_battle_loop_head = function(self, sig)
            local pending = self.pending_battle_writes[1]
            old(self, sig)
            if pending and pending.key == key and #self.pending_battle_writes == 0 and
               rd(ram.wBattleMonHP) == 0 and rd(ram.wBattleMonHP + 1) == 0 and
               rd(ram.wPlayerSelectedMove) == 0xFF then
                log("LOOP_HEAD_WRITE key=" .. key .. " battle_hp=0000 selected=FF")
            end
        end
        local forced = false
        for _ = 1, 60000 do
            if received_commands.force_faint and received_commands.force_faint.key == key then forced = true;break end
            yield_frame()
        end
        if not forced then driver.close();return false, "force_faint never arrived" end
        local chosen = driver.choose("FIGHT")
        if not chosen.ok then driver.close();return false, "B could not choose FIGHT after force_faint" end
        local committed = driver.commit_move(1, 900)
        log("B_ACTIVE_COMMIT " .. tostring(committed.why))
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
    local saved, save_why = game_save(active and "linked_faint_active_new" or "linked_faint_bench_new")
    if not saved then return false, save_why end
    return true, "engine linked faint and memorial saved"
end

function scenarios.linked_faint_bench_new() return linked_faint_scenario(false) end
function scenarios.linked_faint_active_new() return linked_faint_scenario(true) end

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
