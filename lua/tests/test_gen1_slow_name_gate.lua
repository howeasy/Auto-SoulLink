-- FIX-ACQ physical receipt. Buttons only; the production client sends to G's loopback.
-- Result file: patch/build/test_gen1_slow_name_gate_result.txt
-- Coordinator-owned emulator lane: run_gb_gate.py --rom red|blue|yellow --target battle.
local G = dofile((SLINK_ROOT or os.getenv("SLINK_ROOT")) .. "/lua/tests/gen1_gate.lua")
local t = G.start("test_gen1_slow_name_gate")
local C = dofile(t.ROOT .. "/lua/tests/gen1_inputs_common.lua")
local P = dofile(t.ROOT .. "/lua/tests/gen1_scripted_play.lua")
local Hunt = dofile(t.ROOT .. "/lua/tests/gen1_rb_hunt_inputs.lua")
local Driver = dofile(t.ROOT .. "/lua/tests/gen1_battle_driver.lua")
local play = P.new(t.ROOT, t.title, "a", {log = t.log})
local S, rom = play.symbols, t.parts.profile.rom
local json, reads = t.parts.json, t.parts.reads
local function rd(addr) return memory.read_u8(addr, "System Bus") end
local function frame() return emu.framecount() end
local HOLD_FRAMES, NAME = 2400, "AAA"
local captures, failures, acquired = {}, {}, {}
local input_hits, naming_entered, named = 0, false, false
local driver, hooks = nil, {}

-- Diagnostic hooks are bank/PC qualified and pinned to the clean title dumps.
-- pret pokered naming_screen.asm:87-147; Yellow uses the same input flow.
-- Entry stops YES taps before the alphabet can consume another A. inputLoop
-- proves the 2400-frame pause is on the naming screen, not the YES/NO prompt.
local NAMING = {
    red = {entry = 0x6596, entry_hex = "E52130D7CBF6", input = 0x65FF},
    blue = {entry = 0x6596, entry_hex = "E52130D7CBF6", input = 0x65FF},
    yellow = {entry = 0x6307, entry_hex = "E5212FD7CBF6", input = 0x636F},
}
local function hook(pc, expected, label, callback)
    assert(S[label] == pc, "naming symbol disagrees: " .. label)
    for i = 1, #expected, 2 do
        local offset = (i - 1) / 2
        assert(memory.read_u8(pc + offset, "ROM") == tonumber(expected:sub(i, i + 1), 16),
               "naming ROM anchor differs: " .. label) -- bank 1 flat offset equals bus PC
    end
    local id = event.on_bus_exec(function()
        if rd(S.hLoadedROMBank) == 1 and emu.getregister("PC") == pc then callback() end
    end, pc, "slow-name-" .. label, "System Bus")
    assert(id, "naming hook registration failed")
    hooks[#hooks + 1] = id
end

-- Observe, then delegate unchanged: these are the production client's own signals/TX.
local on_signal = t.client.on_signal
function t.client:on_signal(sig)
    if sig.kind == "add_party_mon" and sig.point.in_battle == 1
       and sig.point.mon_location == 0 then
        acquired[#acquired + 1] = sig.frame
        t.log(string.format("ACQUIRE add_party_mon@%d", sig.frame))
    end
    return on_signal(self, sig)
end
local send = t.net.send
function t.net.send(line)
    send(line)
    local msg = assert(json.decode(line))
    if msg.event == "capture" then
        captures[#captures + 1] = {msg = msg, frame = frame()}
        t.log("TX " .. line)
    elseif msg.event == "no_catch" then
        failures[#failures + 1] = msg
        t.log("TX " .. line)
    end
end

local function balls()
    local bag = assert(reads.read_bag())
    local n = 0
    for _, item in ipairs(bag.items) do
        if item.id >= 1 and item.id <= 4 then n = n + item.qty end
    end
    return n
end
local function advance(buttons)
    t.step(buttons or C.idle()) -- always release unspecified buttons
    t.client:frame_end()
    local status = t.client.signals:status()
    assert(not status.failed and not status.handler_error, json.encode(status))
    if #failures > 0 then
        if #acquired == 0 and balls() == 0 then error("RNG: ball missed", 0) end
        error("unexpected no_catch (foe KO / battle failed)", 0)
    end
end
local function idle(n) for _ = 1, n do advance(C.idle()) end end
local function buffer()
    return reads.decode_name(t.deps.read_range(S.wStringBuffer, 11, "System Bus"))
end
local function until_(limit, predicate, buttons, why)
    for i = 1, limit do
        if predicate() then return end
        advance(buttons and buttons(i) or C.idle())
    end
    assert(predicate(), why)
end
local function name_slowly()
    assert(#acquired == 1, "expected exactly one player acquisition signal")
    -- AskName's initial YES row is zero (naming_screen.asm:17-24).
    until_(1800, function() return naming_entered end,
        function(i) return C.tap("A", i) end, "nickname YES did not open naming screen")
    until_(600, function() return input_hits > 0 end, nil, "naming input loop not reached")
    assert(buffer() == "", "unexpected input before naming hold")
    assert(rd(S.wNamingScreenSubmitName) == 0, "name already submitted")
    local begin, hits = frame(), input_hits
    t.log(string.format("NAMING_HOLD_BEGIN frame=%d input_hits=%d", begin, hits))
    idle(HOLD_FRAMES)
    assert(frame() - begin == HOLD_FRAMES, "hold did not advance exactly 2400 frames")
    assert(input_hits > hits and buffer() == "" and rd(S.wNamingScreenSubmitName) == 0,
           "naming screen did not remain idle throughout hold")
    assert(#captures == 0 and #failures == 0, "acquisition resolved during naming hold")
    t.log(string.format("NAMING_HOLD_END frame=%d frames=%d input_hits=%d", frame(), frame() - begin, input_hits))
    -- UpperCaseAlphabet begins ABC...; untouched cursor is row 1, column 1.
    -- Three released A presses choose AAA; START submits (naming_screen.asm:204-207).
    -- A frame boundary is normally INSIDE AnimatePartyMon_ForceSpeed1: it
    -- sets wCurrentMenuItem=0, then waits in DelayFrame (mon_icons.asm:1-6,42).
    -- naming_screen.asm:129-134 saves/restores the real row around that call.
    -- PlaceMenuCursor's tile pointer survives this temporary animation scratch
    -- value (home/window.asm:185-188); its next tile is what pressedA consumes
    -- (naming_screen.asm:223-230). Check that actual glyph instead of the raw row.
    local cursor = rd(S.wMenuCursorLocation) + 256 * rd(S.wMenuCursorLocation + 1)
    assert(cursor >= S.wTileMap and cursor + 1 < S.wTileMap + 360,
           "naming cursor pointer is outside the tilemap")
    local glyph = rd(cursor + 1)
    t.log(string.format("NAMING_CURSOR raw_row=%d x=%d alphabet=%d pointer=%04X glyph=%02X",
        rd(S.wCurrentMenuItem), rd(S.wTopMenuItemX), rd(S.wAlphabetCase), cursor, glyph))
    assert(rd(S.wAlphabetCase) == 0 and glyph == 0x80,
           "initial naming cursor does not select uppercase A")
    for length = 1, 3 do
        until_(180, function() return #buffer() >= length end,
            function(i) return C.tap("A", i) end, "letter press was not accepted")
        idle(12)
        assert(buffer() == NAME:sub(1, length), "nickname differs after letter press")
    end
    until_(180, function() return rd(S.wNamingScreenSubmitName) ~= 0 end,
        function(i) return C.tap("Start", i) end, "START did not submit name")
    until_(900, function() return #captures > 0 end, nil, "client emitted no capture after naming")
    named = true
end

local function run()
    local initial = assert(reads.read_party())
    assert(#initial >= 1 and #initial < 6, "fixture needs a free party slot")
    local point = play.point()
    assert(point.map == 12 and point.x == 10 and point.y == 35, "wrong battle fixture parking tile")
    assert(balls() == 1, "fixture must have exactly one ball")
    local site = assert(NAMING[t.title])
    hook(site.entry, site.entry_hex, "DisplayNamingScreen", function() naming_entered = true end)
    hook(site.input, "FA26CCF5061C", "DisplayNamingScreen.inputLoop", function() input_hits = input_hits + 1 end)
    t.client:start()
    t.online = true
    until_(600, function() return t.client.hello_sent end, nil, "loopback hello was not sent")
    local function yield_buttons(buttons) coroutine.yield(buttons or C.idle()) end
    driver = Driver.new({step = yield_buttons, u8 = rd, addresses = S,
        sites = {display_battle_menu = rom.DisplayBattleMenu.addr,
                 move_selection_menu = rom.MoveSelectionMenu.addr,
                 select_enemy_move = rom.SelectEnemyMove.addr,
                 execute_player_move = rom.ExecutePlayerMove.addr,
                 execute_enemy_move = rom.ExecuteEnemyMove.addr}})
    local hunt = Hunt.new({player = "a"}, {driver = driver, step = yield_buttons,
        rd = rd, symbols = S, mode = "catch", log = t.log})
    local last, terminal = nil, nil
    for _ = 1, 40000 do
        if #acquired > 0 and not named then name_slowly() end
        local p = Hunt.extend_point(play.point(), rd, S)
        local buttons, phase = hunt.step(nil, nil, p, frame())
        if phase ~= last then t.log("HUNT_PHASE " .. phase); last = phase end
        if phase == "caught" then terminal = phase; break end
        if phase == "out-of-balls" then error("RNG: ball missed", 0) end
        assert(phase ~= "stuck" and phase ~= "whiteout" and phase ~= "hunt-exhausted"
               and phase ~= "unexpected-battle", "hunt failed: " .. phase)
        advance(buttons)
    end
    assert(terminal == "caught", "hunt timeout")
    idle(120) -- include battle-end and delayed TX in the same receipt
    assert(named and #acquired == 1, "slow naming route was not executed exactly once")
    assert(#captures == 1 and #failures == 0, "expected exactly one capture and no no_catch")
    local cap, elapsed = captures[1].msg, captures[1].frame - acquired[1]
    assert(cap.area_id == "route_1" and cap.in_box == false, "wrong capture area/destination")
    assert(cap.nickname == NAME and elapsed >= HOLD_FRAMES, "wrong nickname or insufficient signal-to-TX dwell")
    local party = assert(reads.read_party())
    assert(#party == #initial + 1 and reads.key(party[#party]) == cap.key
           and party[#party].nickname == NAME, "TX identity differs from actual appended party mon")
    t.log(string.format("SLOW_NAME_RECEIPT acquire_frame=%d capture_frame=%d gap=%d hold=%d captures=%d no_catch=%d name=%s",
        acquired[1], captures[1].frame, elapsed, HOLD_FRAMES, #captures, #failures, NAME))
    t.check("one Route 1 party capture after 2400 idle naming frames; no no_catch", true)
end
local ok, err = pcall(run)
if not ok then t.check("slow naming physical route", false, err) end
if driver then driver.close() end
for _, id in ipairs(hooks) do event.unregisterbyid(id) end
pcall(function() t.client:stop() end)
local extra
if not ok then extra = tostring(err) end
t.finish(extra)
