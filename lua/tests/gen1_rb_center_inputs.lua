-- Normal-button route to the Viridian Center receptionist, shared by the physical gate
-- and the paired trade lane. No game-state writes. Route geometry: gen1_rb_parcel_inputs.lua:24-29
-- and RC_MASTER_GUIDE.md:1316; map IDs: pret/constants/map_constants.asm.
local M = {}
M.MAP = {lab = 0x28, pallet = 0x00, route1 = 0x0C, viridian = 0x01, center = 0x29}
M.STAGES = {
    {name="lab_exit", map=M.MAP.lab, next=M.MAP.pallet, waypoints={{5,11}}},
    {name="pallet_north", map=M.MAP.pallet, next=M.MAP.route1,
     waypoints={{12,11},{9,11},{9,2},{10,2},{10,-1}}},
    {name="route_one_north", map=M.MAP.route1, next=M.MAP.viridian,
     waypoints={{10,31},{8,31},{8,24},{12,24},{12,22},{9,22},
                {9,14},{14,14},{14,4},{11,4},{11,-1}}},
    {name="viridian_center", map=M.MAP.viridian, next=M.MAP.center,
     waypoints={{20,30},{19,30},{19,26},{23,26},{23,25}}},
    {name="center_receptionist", map=M.MAP.center,
     waypoints={{3,4},{11,4},{11,3}}},
}

-- Tile IDs from pret/charmap.asm:63,92-117,126-151,168-170.
local function glyph(char)
    local n = char:byte()
    if n >= 65 and n <= 90 then return 0x80 + n - 65 end
    if n >= 97 and n <= 122 then return 0xA0 + n - 97 end
    if char == " " then return 0x7F end
    if char == "." then return 0xE8 end
    if char == "?" then return 0xE6 end
    error("unsupported tile probe glyph " .. char, 0)
end

function M.has_tiles(read, tile_base, text, exact_offset)
    local want = {}
    for i = 1, #text do want[i] = glyph(text:sub(i, i)) end
    local first, last = 0, 20 * 18 - #want
    if exact_offset then first, last = exact_offset, exact_offset end
    for offset = first, last do
        local equal = true
        for i = 1, #want do
            if read(tile_base + offset + i - 1) ~= want[i] then equal = false;break end
        end
        if equal then return true end
    end
    return false
end

function M.row(read, tile_base, offset, count)
    local out = {}
    for i = 0, count - 1 do
        local b = read(tile_base + offset + i)
        if b >= 0x80 and b <= 0x99 then out[#out + 1] = string.char(65 + b - 0x80)
        elseif b >= 0xA0 and b <= 0xB9 then out[#out + 1] = string.char(97 + b - 0xA0)
        elseif b == 0x7F then out[#out + 1] = " "
        elseif b == 0xE8 then out[#out + 1] = "."
        elseif b == 0xE6 then out[#out + 1] = "?"
        else out[#out + 1] = "·" end
    end
    return table.concat(out)
end

-- The cursor geometry symbols are absent from profile.ram. Read the committed pret .sym:
-- data/pret/pokered.sym:18329-18330 (Blue uses the same addresses).
function M.menu_symbols(root, title)
    local file = assert(io.open(root .. "/data/pret/" .. (title == "blue" and "pokeblue.sym" or "pokered.sym"), "r"))
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

-- opts: read(addr), ram, row(offset,length), frame(), log(text), invariant(label,ok,detail),
-- check(label,ok,detail), menu_addr, start="lab"|"route1", linked_hp() optional.
function M.new(opts)
    assert(opts and opts.read and opts.ram and opts.row and opts.frame and opts.invariant and opts.check)
    local read, ram, row, fmt = opts.read, opts.ram, opts.row, string.format
    local menu_addr = assert(opts.menu_addr)
    local stage_index = opts.start == "route1" and 3 or 1
    local detour, detour_i, detour_side, detour_tries = nil, 1, -1, 0
    assert(opts.start == "lab" or opts.start == "route1", "center route start must be lab or route1")
    local waypoint_index, still, last_point = 1, 0, ""
    local wild_active, wild_attempts = false, 0
    local function at(symbol) return read(assert(ram[symbol], symbol .. " missing from profile")) end
    local function pulse(key) return opts.frame() % 16 < 2 and {[key]=true} or {} end

    local self = {}
    function self.step()
        local map, x, y = at("wCurMap"), at("wXCoord"), at("wYCoord")
        local battle = at("wIsInBattle")
        if battle ~= 0 then
            opts.invariant("only an ordinary Route 1 wild battle interrupted the walk",
                map == M.MAP.route1 and battle == 1 and at("wBattleType") == 0,
                fmt("map=%d battle=%d type=%d", map, battle, at("wBattleType")))
            wild_active = true
            if opts.linked_hp then
                opts.invariant("linked mon stayed alive during wild battle", opts.linked_hp() > 0,
                               fmt("linked hp=%d", opts.linked_hp()))
            end
            opts.invariant("wild RUN attempts stay bounded", wild_attempts < 8,
                           fmt("attempts=%d tile=%s", wild_attempts, row(281, 18)))
            -- gen1_rb_route1_inputs.lua:41-60: BATTLE_MENU_TEMPLATE, RUN is right/second.
            -- wTextBoxID remains $0B during "Can't escape!" with stale cursor bytes; the
            -- FIGHT glyph run proves the menu is actually drawn (physical gate run 3).
            if at("wTextBoxID") == 0x0B and row(281, 18):find("FIGHT", 1, true) then
                local mx, my = read(menu_addr.wTopMenuItemX), read(menu_addr.wTopMenuItemY)
                local index = at("wCurrentMenuItem")
                opts.invariant("observed standard wild battle menu", my == 14 and at("wMaxMenuItem") == 1,
                               fmt("x=%d y=%d index=%d max=%d", mx, my, index, at("wMaxMenuItem")))
                if mx == 9 then return pulse("Right") end
                opts.invariant("wild RUN column observed", mx == 15, fmt("x=%d", mx))
                if index == 0 then return pulse("Down") end
                opts.invariant("wild RUN row observed", index == 1, fmt("index=%d", index))
                if opts.frame() % 16 < 2 then wild_attempts = wild_attempts + 1;return {A=true} end
                return {}
            end
            return pulse("A")
        end
        if wild_active then
            local hp = opts.linked_hp and opts.linked_hp() or
                       (read(ram.wPartyMons + 1) * 256 + read(ram.wPartyMons + 2))
            local label = opts.linked_hp and "wild battle ended by RUN with linked mon alive" or
                          "wild battle ended by RUN with starter alive"
            opts.check(label, at("wBattleResult") == 2 and hp > 0,
                       fmt("result=%d hp=%d", at("wBattleResult"), hp))
            wild_active, wild_attempts = false, 0
        end
        local stage = M.STAGES[stage_index]
        if map == stage.next then
            (opts.log or function() end)(fmt("ROUTE %s -> map %d at (%d,%d) frame %d",
                stage.name, map, x, y, opts.frame()))
            stage_index, waypoint_index, still, last_point = stage_index + 1, 1, 0, ""
            stage = M.STAGES[stage_index]
        end
        opts.invariant("walk stayed on the planned map chain", map == stage.map,
                       fmt("expected %s map=%d, got map=%d (%d,%d)", stage.name, stage.map, map, x, y))
        if stage_index == #M.STAGES and waypoint_index > #stage.waypoints then return nil, true end
        local target = stage.waypoints[waypoint_index]
        if not target and stage.next then target = {x, stage.name == "lab_exit" and y + 1 or y - 1} end
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
        -- A blocked lane (trade_new B: 1800 frames at (14,12) heading north; Route 1's
        -- Youngster 2 walks LEFT_RIGHT on y=13, data/maps/objects/Route1.asm) is walked
        -- around: after 240 still frames, detour one column over for two rows, then resume;
        -- the other side second; both exhausted = fail with the facing tilemap for diagnosis.
        if still >= 240 and not detour then
            detour_side = detour_side == 1 and -1 or 1
            detour_tries = (detour_tries or 0) + 1
            if detour_tries <= 2 then
                local dy = y > target[2] and -2 or (y < target[2] and 2 or 0)
                detour = { {x + detour_side, y}, {x + detour_side, y + dy}, target }
                detour_i, still = 1, 0
                ;(opts.log or function() end)(fmt("DETOUR side=%d from (%d,%d) frame %d",
                                                    detour_side, x, y, opts.frame()))
            end
        end
        if detour then
            local d = detour[detour_i]
            if x == d[1] and y == d[2] then
                detour_i = detour_i + 1
                if detour_i > #detour then detour, detour_tries = nil, 0 else d = detour[detour_i] end
            end
            if detour then target = d end
        end
        opts.invariant("waypoint not blocked", still < 1800,
                       fmt("%s waypoint=%d at (%d,%d) target=(%d,%d) joy_ignore=%d battle=%d row13=%s row14=%s",
                           stage.name, waypoint_index, x, y, target[1], target[2], at("wJoyIgnore"),
                           at("wIsInBattle"), row(261, 18), row(281, 18)))
        if at("wJoyIgnore") ~= 0 then return pulse("A") end
        if x < target[1] then return {Right=true} end
        if x > target[1] then return {Left=true} end
        if y < target[2] then return {Down=true} end
        return {Up=true}
    end
    return self
end
return M
