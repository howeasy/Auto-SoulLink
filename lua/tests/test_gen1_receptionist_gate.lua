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
local MAP = {lab = 0x28, pallet = 0x00, route1 = 0x0C, viridian = 0x01, center = 0x29}
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
local function wait_for(predicate, frames, label)
    for _ = 1, frames do
        if predicate() then return true end
        step({})
    end
    require_check(label, false, fmt("not seen in %d frames; map=%d x=%d y=%d tile=%s",
                                   frames, at("wCurMap"), at("wXCoord"), at("wYCoord"), row(281, 18)))
end

-- The profile intentionally omits the two menu cursor geometry symbols. Read
-- their committed pret .sym addresses (pokered.sym:18329-18330), not an R/B
-- hardcoded WRAM guess.
local function menu_symbols()
    local path = t.ROOT .. "/data/pret/pokered.sym"
    local file = assert(io.open(path, "r"))
    local addresses = {}
    for line in file:lines() do
        local bank, addr, name = line:match("^(%x+):(%x+) (%S+)")
        if (name == "wTopMenuItemX" or name == "wTopMenuItemY") and bank == "00" then
            addresses[name] = tonumber(addr, 16)
        end
    end
    file:close()
    assert(addresses.wTopMenuItemX and addresses.wTopMenuItemY, "menu geometry missing from pret sym")
    return addresses
end
local menu_addr = menu_symbols()

local stages = {
    {name="lab_exit", map=MAP.lab, next=MAP.pallet, waypoints={{5,11}}},
    {name="pallet_north", map=MAP.pallet, next=MAP.route1,
     waypoints={{12,11},{9,11},{9,2},{10,2},{10,-1}}},
    {name="route_one_north", map=MAP.route1, next=MAP.viridian,
     waypoints={{10,31},{8,31},{8,24},{12,24},{12,22},{9,22},
                {9,14},{14,14},{14,4},{11,4},{11,-1}}},
    {name="viridian_center", map=MAP.viridian, next=MAP.center,
     waypoints={{20,30},{19,30},{19,26},{23,26},{23,25}}},
    {name="center_receptionist", map=MAP.center,
     waypoints={{3,4},{11,4},{11,3}}},
}
local stage_index, waypoint_index, still, last_point = 1, 1, 0, ""
local wild_active, wild_attempts = false, 0
local function route_buttons()
    local map, x, y = at("wCurMap"), at("wXCoord"), at("wYCoord")
    local battle = at("wIsInBattle")
    if battle ~= 0 then
        require_check("only an ordinary Route 1 wild battle interrupted the walk",
            map == MAP.route1 and battle == 1 and at("wBattleType") == 0,
            fmt("map=%d battle=%d type=%d", map, battle, at("wBattleType")))
        wild_active = true
        require_check("wild RUN attempts stay bounded", wild_attempts < 8,
                      fmt("attempts=%d tile=%s", wild_attempts, row(281, 18)))
        -- gen1_rb_route1_inputs.lua:41-60: BATTLE_MENU_TEMPLATE, right column,
        -- second item RUN. All actions are normal joypad pulses.
        if at("wTextBoxID") == 0x0B then
            local mx, my = read(menu_addr.wTopMenuItemX), read(menu_addr.wTopMenuItemY)
            local index = at("wCurrentMenuItem")
            require_check("observed standard wild battle menu", my == 14 and at("wMaxMenuItem") == 1,
                          fmt("x=%d y=%d index=%d max=%d", mx, my, index, at("wMaxMenuItem")))
            if mx == 9 then return t.frame % 16 < 2 and {Right=true} or {} end
            require_check("wild RUN column observed", mx == 15, fmt("x=%d", mx))
            if index == 0 then return t.frame % 16 < 2 and {Down=true} or {} end
            require_check("wild RUN row observed", index == 1, fmt("index=%d", index))
            if t.frame % 16 < 2 then wild_attempts = wild_attempts + 1;return {A=true} end
            return {}
        end
        return t.frame % 16 < 2 and {A=true} or {}
    end
    if wild_active then
        require_check("wild battle ended by RUN with starter alive", at("wBattleResult") == 2 and
                      read(ram.wPartyMons + 1) + 256 * read(ram.wPartyMons + 2) > 0,
                      fmt("result=%d hp=%d", at("wBattleResult"),
                          read(ram.wPartyMons + 1) * 256 + read(ram.wPartyMons + 2)))
        wild_active, wild_attempts = false, 0
    end
    local stage = stages[stage_index]
    if map == stage.next then
        t.log(fmt("ROUTE %s -> map %d at (%d,%d) frame %d", stage.name, map, x, y, t.frame))
        stage_index, waypoint_index, still, last_point = stage_index + 1, 1, 0, ""
        stage = stages[stage_index]
    end
    require_check("walk stayed on the planned map chain", map == stage.map,
                  fmt("expected %s map=%d, got map=%d (%d,%d)", stage.name, stage.map, map, x, y))
    if stage_index == #stages and waypoint_index > #stage.waypoints then return nil, true end
    local target = stage.waypoints[waypoint_index]
    if not target and stage.next then
        target = {x, stage.name == "lab_exit" and y + 1 or y - 1}
    end
    if target[2] >= 0 and x == target[1] and y == target[2] and
       waypoint_index <= #stage.waypoints then
        waypoint_index = waypoint_index + 1
        target = stage.waypoints[waypoint_index]
        if not target then
            if stage.next then target = {x, y + (stage.name == "lab_exit" and 1 or -1)}
            else return nil, true end
        end
    end
    local point = fmt("%d:%d:%d:%d", map, x, y, waypoint_index)
    still = point == last_point and still + 1 or 0
    last_point = point
    require_check("waypoint not blocked", still < 300,
                  fmt("%s waypoint=%d at (%d,%d) target=(%d,%d)",
                      stage.name, waypoint_index, x, y, target[1], target[2]))
    if at("wJoyIgnore") ~= 0 then
        return t.frame % 16 < 2 and {A=true} or {}
    end
    if x < target[1] then return {Right=true} end
    if x > target[1] then return {Left=true} end
    if y < target[2] then return {Down=true} end
    return {Up=true}
end

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
        pulse("A")
        -- trade_receptionist.asm:345-390 prints the picker at +22.
        wait_for(function() return has_tiles("TRADE WHICH?", 22) end, 180,
                 "TRADE WHICH? linked-party list")
        t.log("MENU PARTY " .. row(22, 16))
        local chosen = t.frame
        pulse("A") -- mask=1 makes the first visible row physical slot 0
        local offered
        for _ = 1, 176 do
            offered = find_sent("trade_offer", first)
            if offered then break end
            step({})
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
end, debug.traceback)

if not ok then t.check("receptionist gate sequence", false, tostring(err)) end
-- The wrapper validates EVERY client wire line against protocol_schema.py.
-- Append in one batch so the gate result file is written once, even on a long walk.
for _, line in ipairs(t.sent) do t.lines[#t.lines + 1] = "SENT " .. line end
t.finish("normal-input Red/Blue receptionist gate")
