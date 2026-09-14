--[[
PHYSICAL PREP ONLY: patched Red/Blue, normal buttons from the real town save.
No RAM/register/savestate staging. tests/fixtures/gen1/{red,blue}_town.SaveRAM
qualify and park at Oak's Lab map $28 (5,6); we walk lab -> Pallet -> Route 1
-> Viridian -> Pokemon Center. The route reuses input-only waypoint geometry
from gen1_rb_parcel_inputs.lua:24-29, N1-PATH in RC_MASTER_GUIDE.md:1316,
and the wild RUN menu logic in gen1_rb_route1_inputs.lua:41-60.
Source map IDs: pret/constants/map_constants.asm (OAKS_LAB $28, PALLET $00,
ROUTE_1 $0C, VIRIDIAN $01, VIRIDIAN_POKECENTER $29).
The receptionist is object 4 at (11,2), approached from (11,3) facing Up:
pret/data/maps/objects/ViridianPokecenter.asm and RC N1-PATH.
Result file: patch/build/test_gen1_receptionist_gate_result.txt
]]
local G = dofile((SLINK_ROOT or os.getenv("SLINK_ROOT")) .. "/lua/tests/gen1_gate.lua")
local t = G.start("test_gen1_receptionist_gate")
local fmt = string.format
local r, json, ram = t.parts.reads, t.parts.json, t.parts.profile.ram
local Center = dofile(t.ROOT .. "/lua/tests/gen1_rb_center_inputs.lua")
local MAP = Center.MAP
local TILE_COUNT = 20 * 18 -- pret/constants/gfx_constants.asm SCREEN_WIDTH/HEIGHT

local function read(addr) return memory.read_u8(addr, "System Bus") end
local function at(symbol) return read(assert(ram[symbol], symbol .. " missing from profile")) end
local function step(buttons)
    t.step(buttons or {}) -- {} releases the prior held normal button
    t.client:frame_end()
end
local function pulse(button)
    step({[button] = true});step({[button] = true});step({});step({})
end
local function require_check(label, ok, detail)
    if not t.check(label, ok, detail) then error(label .. ": " .. tostring(detail), 0) end
end
-- per-frame invariants: silent while they hold (console.log per frame starves the emulator
-- and floods the receipt — run 2 wrote 3000 [ok] lines for one walk), fatal when they break
local function invariant(label, ok, detail)
    if not ok then require_check(label, ok, detail) end
end
local function tile_bytes()
    local bytes = {}
    for i = 0, TILE_COUNT - 1 do bytes[#bytes + 1] = read(ram.wTileMap + i) end
    return bytes
end
local function tile_code(text)
    -- pret/constants/charmap.asm:63,92-117,126-151,168-170: space,
    -- upper/lower letters, period and question mark are tile IDs, not ASCII.
    local out = {}
    for i = 1, #text do
        local c = text:sub(i, i);local n = c:byte()
        if n >= 65 and n <= 90 then out[#out + 1] = 0x80 + n - 65
        elseif n >= 97 and n <= 122 then out[#out + 1] = 0xA0 + n - 97
        elseif c == " " then out[#out + 1] = 0x7F
        elseif c == "." then out[#out + 1] = 0xE8
        elseif c == "?" then out[#out + 1] = 0xE6
        else error("unsupported tile probe glyph " .. c, 0) end
    end
    return out
end
local function has_tiles(text, exact_offset)
    local want, have = tile_code(text), tile_bytes()
    local first, last = 1, #have - #want + 1
    if exact_offset then first, last = exact_offset + 1, exact_offset + 1 end
    for i = first, last do
        local equal = true
        for j = 1, #want do if have[i + j - 1] ~= want[j] then equal = false;break end end
        if equal then return true end
    end
    return false
end
local function row(offset, n)
    local out = {}
    for i = 0, n - 1 do
        local b = read(ram.wTileMap + offset + i)
        if b >= 0x80 and b <= 0x99 then out[#out + 1] = string.char(65 + b - 0x80)
        elseif b >= 0xA0 and b <= 0xB9 then out[#out + 1] = string.char(97 + b - 0xA0)
        elseif b == 0x7F then out[#out + 1] = " "
        elseif b == 0xE8 then out[#out + 1] = "."
        elseif b == 0xE6 then out[#out + 1] = "?"
        else out[#out + 1] = "·" end
    end
    return table.concat(out)
end
local function find_sent(event, first)
    for i = first + 1, #t.sent do
        local message = assert(json.decode(t.sent[i]))
        if message.event == event then return message, i end
    end
    return nil
end
local function reply(command)
    t.replies[#t.replies + 1] = assert(json.encode({commands = {command}}))
end
local function wait_for(predicate, frames, label, repulse)
    -- emitted != accepted: a native menu (HandleMenuInput) polls on its own cadence, so a
    -- single 2-frame pulse can land before it listens (receipt: SLINK TRADE row drawn,
    -- cursor at 0, one A pulse, picker never appeared in 180 frames). With `repulse`, the
    -- button is re-pulsed every 16 frames until the predicate holds.
    for _ = 1, frames do
        if predicate() then return true end
        step(repulse and t.frame % 16 < 2 and {[repulse] = true} or {})
    end
    require_check(label, false, fmt("not seen in %d frames; map=%d x=%d y=%d tile=%s",
                                   frames, at("wCurMap"), at("wXCoord"), at("wYCoord"), row(281, 18)))
end

local route = Center.new({
    read = read, ram = ram, row = row, frame = function() return t.frame end,
    log = t.log, invariant = invariant, check = require_check, start = "lab",
    menu_addr = Center.menu_symbols(t.ROOT, t.title),
})
local function route_buttons() return route.step() end

local ok, err = xpcall(function()
    require_check("patched Red/Blue client enabled SLINK TRADE", t.title == "red" or t.title == "blue")
    t.client:start()
    require_check("trade_enabled on the patched build", t.client.trade_enabled == true,
                  tostring(t.client.trade_enabled))
    local signal_status = t.client.signals:status()
    require_check("bank-qualified trade service site registered", signal_status.failed == nil and
                  signal_status.handler_error == nil and signal_status.closed == false,
                  fmt("failed=%s handler=%s pending=%s", tostring(signal_status.failed),
                      tostring(signal_status.handler_error), tostring(signal_status.pending)))
    t.online = true
    t.client:frame_end() -- first loopback hello; every later step drives frame_end
    local arrived = false
    for _ = 1, 20000 do
        local buttons, ready = route_buttons()
        if ready then arrived = true;break end
        step(buttons)
    end
    require_check("walked from Oak's Lab to the physical Center receptionist", arrived and
                  at("wCurMap") == MAP.center and at("wXCoord") == 11 and at("wYCoord") == 3,
                  fmt("map=%d x=%d y=%d frame=%d", at("wCurMap"), at("wXCoord"), at("wYCoord"), t.frame))

    local function visit(accepted)
        local first = #t.sent
        pulse("Up");step({}) -- face the receptionist object at (11,2)
        local talked = t.frame
        pulse("A")
        local query
        for _ = 1, 26 do
            query = find_sent("trade_query", first)
            if query then break end
            step({})
        end
        require_check("native receptionist emitted trade_query within 30 frames",
                      query ~= nil and t.frame - talked <= 30,
                      fmt("visit=%d now=%d map=%d", talked, t.frame, at("wCurMap")))
        reply({cmd="trade_mask", mask=1})
        -- trade_receptionist.asm:270-296 prints these three rows at +42/+82/+122.
        wait_for(function() return has_tiles("SLINK TRADE", 42) and
                                   has_tiles("CABLE CLUB", 82) and has_tiles("CANCEL", 122) end,
                 120, "SLINK TRADE / CABLE CLUB / CANCEL native menu")
        t.log("MENU SLINK " .. row(42, 16))
        t.log("MENU CABLE " .. row(82, 16))
        t.log("MENU CANCEL " .. row(122, 16))
        require_check("native menu defaulted to SLINK TRADE row", at("wCurrentMenuItem") == 0,
                      fmt("index=%d", at("wCurrentMenuItem")))
        -- trade_receptionist.asm:345-390 prints the picker at +22.
        wait_for(function() return has_tiles("TRADE WHICH?", 22) end, 180,
                 "TRADE WHICH? linked-party list", "A")
        t.log("MENU PARTY " .. row(22, 16))
        local chosen = t.frame
        -- mask=1 makes the first visible row physical slot 0; re-pulse A on the 16-frame
        -- cadence until the offer is on the wire (run 3: one pulse, picker stayed up 180 frames)
        local offered
        for _ = 1, 180 do
            offered = find_sent("trade_offer", first)
            if offered then break end
            step(t.frame % 16 < 2 and {A=true} or {})
        end
        require_check("selected slot zero emitted trade_offer within 180 frames",
                      offered and offered.slot == 0 and t.frame - chosen <= 180,
                      offered and fmt("slot=%s frame=%d", tostring(offered.slot), t.frame)
                              or fmt("no offer frame=%d", t.frame))
        reply({cmd="trade_offer_ack", ok=accepted})
        local notice = accepted and "Trade offer sent." or "Trade unavailable."
        wait_for(function() return has_tiles(notice) end, 180, notice .. " native notice")
        t.log("NOTICE " .. row(281, 18) .. " | " .. row(321, 18))
        local returned = false
        for i = 1, 600 do
            if t.overworld_ok() then returned = true;break end
            step(i % 16 < 2 and {A=true} or {})
        end
        require_check("native offer returned cleanly to the overworld", returned,
                      fmt("notice=%s map=%d x=%d y=%d frame=%d", notice,
                          at("wCurMap"), at("wXCoord"), at("wYCoord"), t.frame))
    end
    visit(false)
    visit(true)

    -- T-1's other half: CABLE CLUB and CANCEL fall through to vanilla. Talk again, wait for the
    -- native menu, move the cursor with re-pulsed Down until the engine shows the row, select.
    local function open_menu()
        local first = #t.sent
        pulse("Up");step({})
        pulse("A")
        wait_for(function() return find_sent("trade_query", first) ~= nil end, 30, "trade_query on the revisit")
        reply({cmd="trade_mask", mask=1})
        wait_for(function() return has_tiles("SLINK TRADE", 42) and has_tiles("CANCEL", 122) end,
                 120, "native menu on the revisit")
        return first
    end
    local function choose_row(index)
        wait_for(function() return at("wCurrentMenuItem") == index end, 120,
                 fmt("cursor on native menu row %d", index), "Down")
    end
    -- CABLE CLUB: engine/link/cable_club_npc.asm CableClubNPC prints CableClubNPCWelcomeText, then
    -- (Pokedex obtained) tries the serial link for 90 frames and fails without a cable.
    open_menu()
    choose_row(1)
    wait_for(function() return has_tiles("Welcome to the") end, 180, "vanilla CABLE CLUB welcome text", "A")
    t.log("VANILLA " .. row(281, 18) .. " | " .. row(321, 18))
    local returned = false
    for i = 1, 900 do
        if t.overworld_ok() then returned = true;break end
        step(i % 16 < 2 and {A=true} or {})
    end
    require_check("CABLE CLUB fell through to vanilla and returned to the overworld", returned,
                  fmt("map=%d x=%d y=%d frame=%d", at("wCurMap"), at("wXCoord"), at("wYCoord"), t.frame))
    -- CANCEL: the menu closes with no offer and no notice
    local before = #t.sent
    open_menu()
    choose_row(2)
    local closed = false
    for i = 1, 300 do
        if t.overworld_ok() and not has_tiles("SLINK TRADE", 42) then closed = true;break end
        step(i % 16 < 2 and {A=true} or {})
    end
    require_check("CANCEL closed the native menu with no offer", closed and
                  find_sent("trade_offer", before) == nil,
                  fmt("closed=%s map=%d frame=%d", tostring(closed), at("wCurMap"), t.frame))
end, debug.traceback)

if not ok then t.check("receptionist gate sequence", false, tostring(err)) end
-- The wrapper validates EVERY client wire line against protocol_schema.py.
-- Append in one batch so the gate result file is written once, even on a long walk.
for _, line in ipairs(t.sent) do t.lines[#t.lines + 1] = "SENT " .. line end
t.finish("normal-input Red/Blue receptionist gate")
