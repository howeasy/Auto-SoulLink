-- lua/tests/gen1_rb_route22_inputs.lua — the Route 22 rival driver for the D-11/W-4 rival
-- team swap scenario (plan A13).  One driver:
--
--   M.new(expected [, opts])   Route 1 (10,35) -> Viridian City -> the WEST edge -> Route 22
--                              -> the rival trigger tile, then FIGHTs Rival1 to the end.
--                              terminals "rival-won" | "rival-lost" | "rival-drawn"
--                                        | "rival-never-triggered" | "starter-koed"
--                                        | "unknown-map"
--
-- Same shape as the sibling route modules (gen1_rb_route1_inputs / gen1_rb_forest_inputs /
-- gen1_rb_center_inputs): step(handshake, status, point, frame) -> buttons, phase; the caller
-- owns emu.frameadvance and feeds gen1_scripted_play.lua's read-only point.
--
-- Logged markers (phase transitions and events only — no per-frame logging):
--   INCIDENTAL_BATTLE n map=M (x,y)     a wild battle on the walk; RUN from, not fatal
--   RIVAL_TRIGGER map=M x=X y=Y         the frame wJoyIgnore latched on a trigger tile
--   RIVAL_SWITCH slot=N                 the in-battle party menu picked a replacement
--   RIVAL_OVER result=R                 wBattleResult the frame the battle closed
--
-- ─────────────────────────────────────────────────────────────────────────────────────────
-- VERIFIED FACTS (pret/pokered @ 405b6246372d7e5a2cb029cbb65219b13286b8c9, checked out at
-- E:/Google Drive/SLink/.cache/pret/pokered).  Everything below was read out of those files.
--
-- Trigger.  OaksLabRivalLeavesWithPokedexScript (scripts/OaksLab.asm:628-640) sets
--   EVENT_1ST_ROUTE22_RIVAL_BATTLE (:634), resets EVENT_2ND_ROUTE22_RIVAL_BATTLE (:635) and
--   sets EVENT_ROUTE22_RIVAL_WANTS_BATTLE (:636), then ShowObject's TOGGLE_ROUTE_22_RIVAL_1.
--   Route22DefaultScript (scripts/Route22.asm:58-80) returns unless
--   EVENT_ROUTE22_RIVAL_WANTS_BATTLE is set (:59-60) and the player stands on one of
--   .Route22RivalBattleCoords = dbmapcoord 29,4 / 29,5 (:77-80); it then writes
--   wJoyIgnore = PAD_CTRL_PAD and wPlayerMovingDirection = PLAYER_DIR_LEFT (:66-70), i.e. the
--   player arrives walking WEST, which is what the waypoints below do.
--   Route22Rival1StartBattleScript (:104-140) clears wJoyIgnore, displays the challenge text
--   and sets wCurOpponent = OPP_RIVAL1 (:135-136).
--   OPP_RIVAL1 = OPP_ID_OFFSET + RIVAL1 = 200 + $19 = 225 (constants/trainer_constants.asm:1,5,42).
--   Vanilla Rival1 on Route 22 is `db $FF, 9, PIDGEY, 8, <starter>, 0`
--   (data/trainers/parties.asm:491-493) — the team the swap is expected to replace.
--
-- †Connection (macros/scripts/maps.asm:210-220: a WEST connection arrives at
--   _x = TARGET_WIDTH*2 - 1 with _y = offset * -2 added to the player's y).
--     data/maps/headers/ViridianCity.asm:4  connection west, Route22, ROUTE_22, 4
--       -> Viridian (-1,y) arrives Route 22 (39, y-8);   ROUTE_22_WIDTH = 20 (map_constants.asm:63)
--     data/maps/headers/Route22.asm:3       connection east, ViridianCity, VIRIDIAN_CITY, -4
--       -> the inverse, y_viridian = y_route22 + 8.  Self-consistent.
--   Cross-checked two further ways: (a) the macro's _map = (CURRENT_MAP_WIDTH + 6) * (4+3)
--   puts the strip at bordered block row 7 = map block row 4 = Viridian y 8..25, so Route 22
--   y 0 lines up with Viridian y 8 — the same delta of 8; (b) the two maps' walkable edge
--   bands decode as Viridian x=0 y=14..17 and Route 22 x=39 y=6..9, which is exactly that
--   delta.  This route leaves at Viridian (0,17) and lands on Route 22 (39,9).
--
-- Geometry decoding procedure (identical to gen1_rb_forest_inputs.lua:36-49, which states it
--   in full): maps/<Map>.blk is width*height block ids, gfx/blocksets/overworld.bst is 16 tile
--   ids per block; a player coordinate is a HALF-block, its COLLISION tile is the half-block's
--   bottom-left tile and its GRASS tile the bottom-right one; walkable iff the collision tile
--   is in Overworld_Coll (data/tilesets/collision_tile_ids.asm:12), grass iff the grass tile is
--   $52 (data/tilesets/tileset_headers.asm:12).  Ledges ($27/$36/$37, data/tilesets/
--   ledge_tiles.asm) are absent from Overworld_Coll and so decode as walls, which is correct
--   for a route that must climb, not hop.
--   Controls: the decoder reproduces Route 1's pinned grass patch (x 10-11, y 32-35, probe
--   $52) and walks the proven-live gen1_rb_center_inputs.lua:14-15 Viridian leg with zero
--   unwalkable tiles.
--
-- Maps (constants/map_constants.asm): ROUTE_1 $0C 10x18 (:42), VIRIDIAN_CITY $01 20x18 (:27),
--   ROUTE_22 $21 20x9 (:63).
--
-- †Viridian City (decoded; objects from data/maps/objects/ViridianCity.asm): the west exit
--   band is y=14..17 at x=0.  The waypoints reach it via the x=20/21 corridor out of the
--   Route 1 entry (the ledge row y=27 is passable only at x=15 and x=19; this route uses 19,
--   the same column gen1_rb_center_inputs.lua:14 uses), then row 26 west to x=14, down to
--   row 22, west to x=9, and the x=8 column down to row 17.  39 steps, 0 grass (Viridian has
--   no grass half-block at all).  Row 21/22 at x=9..13 is the closest this route comes to the
--   wandering youngster at (13,20) WALK ANY_DIR (objects:29) — hence the stall/detour below.
--   The fisher (6,23) and youngster2 (30,25) are off the path; the sleepy old man (18,9) who
--   blocks the NORTH road is irrelevant to a westbound route.
--
-- †Route 22 (decoded; objects from data/maps/objects/Route22.asm): the east entry pocket
--   (x=35..39, y=6..12) is cut off from the row 4/5 plateau by the ledge column x=36 y=4
--   ($27) and the ledge row y=5 x=36..39 ($37) — those are one-way hops INTO the pocket, so
--   the only way out towards the trigger is south along x=35 to row 12, west to x=31, then
--   NORTH up the x=31 grass column (y=8..11, probe $52) to row 6.  A Dijkstra over the decoded
--   map with grass as cost confirms 4 grass steps is the minimum from any entry y — they are
--   unavoidable, not a lazy path.  Route 22's encounter rate is 25/256
--   (data/wild/maps/Route22.asm:2), so an incidental wild battle on those four steps is
--   EXPECTED and is RUN from, exactly as the Route 1 leg does.
--   The rival sprite stands at (25,5) (objects:14) and is walked right into place by the
--   script, so it never blocks the approach along row 5.
--
-- †In-battle party menu (home/pokemon.asm:205-216 PartyMenuInit): wTopMenuItemY = 1,
--   wTopMenuItemX = 0, wMaxMenuItem = wPartyCount - 1.  That geometry is how this driver
--   recognises the "choose a POKéMON" screen after a KO instead of pressing A blind.
--
-- †wBattleResult (ram/wram.asm:998-1002): $00 win, $01 lose, $02 draw.
local M = {}

M.MAP = { route1 = 0x0C, viridian = 0x01, route22 = 0x21 }
M.RIVAL1 = 225                 -- OPP_RIVAL1, see the header
M.TRIGGER = { { 29, 5 }, { 29, 4 } }
M.STALL_BOUND = 1800           -- the gate drivers' NPC stall bound
M.STALL_NUDGE = 48             -- frames on one tile before sidestepping a wanderer
M.DETOUR_FRAMES = 32
M.BATTLE_BOUND = 60000         -- a rival battle that never closes is a driver fault
M.TRIGGER_GRACE = 600          -- frames parked on (29,4) before "the rival never triggered"

-- This file is dofile'd by absolute path, so its own directory locates its siblings.
local function here()
    return (debug.getinfo(1, "S").source or ""):match("^@(.*[/\\])") or ""
end

-- Route 1's northbound list is gen1_rb_forest_inputs.lua's `route1_north` (itself the
-- proven-live gen1_rb_parcel_inputs.lua:18 list, and provably the minimum-grass crossing);
-- it is imported rather than restated so there is one copy of that geometry.
local paths = {
    viridian_west = { {20,35},{20,30},{19,30},{19,26},{14,26},{14,22},{9,22},{9,21},{8,21},{8,17},{0,17},{-1,17} },
    -- {39,9} first is a no-op on the planned entry and a square-up if a Viridian detour pushed
    -- the exit onto another row of the y=14..17 band: (39,6) walking west runs into the wall at
    -- (35,6) ($3a), while the x=39 column y=6..9 is clear.
    route22_rival = { {39,9},{35,9},{35,12},{31,12},{31,6},{30,6},{30,5},{29,5},{29,4} },
}
M.PATHS = paths

local function idle() return {A=false,B=false,Start=false,Select=false,Up=false,Down=false,Left=false,Right=false} end
local function hold(name) local b=idle(); b[name]=true; return b end
-- Native menus and text boxes are re-pulsed on the 16-frame cadence, never held.
local function tap(name, frame) local b=idle(); b[name]=frame%16<2; return b end
local function move(point, target)
    if point.x<target[1] then return hold("Right") end
    if point.x>target[1] then return hold("Left") end
    if point.y<target[2] then return hold("Down") end
    if point.y>target[2] then return hold("Up") end
    return idle()
end
local function check_point(point, what)
    assert(point and type(point.map)=="number" and type(point.x)=="number" and type(point.y)=="number"
        and type(point.battle)=="number" and type(point.party_hp)=="number"
        and type(point.opponent)=="number" and type(point.battle_result)=="number",
        "complete read-only "..what.." point required")
end
local function on_trigger_tile(point)
    for _, t in ipairs(M.TRIGGER) do
        if point.x==t[1] and point.y==t[2] then return true end
    end
    return false
end

function M.new(expected, opts)
    assert(expected and (expected.player=="a" or expected.player=="b"), "R/B Route 22 identity required")
    opts = opts or {}
    local log = opts.log or function() end
    paths.route1_north = paths.route1_north
        or assert(dofile(here() .. "gen1_rb_forest_inputs.lua").PATHS.route1_north,
                  "forest module carries no route1_north path")
    local r1 = dofile(here() .. "gen1_rb_route1_inputs.lua").new(expected)
    local self = { last_frame=-1, segments={}, wild_active=false, incidental_battles=0,
                   tile=nil, tile_frame=0, detour=nil, detour_along=nil, detour_until=nil,
                   flip=false, triggered=nil, rival_seen=false, rival_frame=nil, switch_tried={},
                   arrival_frame=nil, over_logged=false }

    -- Same follow/detour routine as gen1_rb_forest_inputs.lua:203-238; a step blocked by a
    -- wanderer leaves the tile unchanged, so after STALL_NUDGE frames on one tile the route
    -- sidesteps for DETOUR_FRAMES (alternating sides) and then moves DETOUR_FRAMES along the
    -- travel axis, so the re-aim lands PAST the blocker rather than walking back into it.
    local function follow(name, point, frame)
        local targets = paths[name]
        local index = self.segments[name] or 1
        while targets[index] and point.x==targets[index][1] and point.y==targets[index][2] do index=index+1 end
        self.segments[name] = index
        if not targets[index] then return idle(), name.."-arrival" end
        local tile = point.map.."/"..point.x.."/"..point.y
        if tile ~= self.tile then self.tile, self.tile_frame = tile, frame end
        assert(frame - self.tile_frame <= M.STALL_BOUND,
            "Route 22 route stalled "..M.STALL_BOUND.." frames at "..tile)
        if self.detour_until and frame < self.detour_until then
            local sideways = frame < self.detour_until - M.DETOUR_FRAMES
            return hold(sideways and self.detour or self.detour_along), name.."-detour"
        end
        if frame - self.tile_frame >= M.STALL_NUDGE then
            self.flip = not self.flip
            if point.x == targets[index][1] then           -- walking on y: sidestep on x
                self.detour = self.flip and "Left" or "Right"
                self.detour_along = point.y < targets[index][2] and "Down" or "Up"
            else                                           -- walking on x: sidestep on y
                self.detour = self.flip and "Up" or "Down"
                self.detour_along = point.x < targets[index][1] and "Right" or "Left"
            end
            self.detour_until = frame + 2 * M.DETOUR_FRAMES
            return hold(self.detour), name.."-detour"
        end
        return move(point, targets[index]), name
    end

    -- The rival fight: FIGHT, move slot 1, every turn.  The replacement team is the partner's
    -- own party, so neither the outcome nor the number of turns is knowable in advance — the
    -- caller reads wBattleResult off the terminal phase.
    local function fight(point, frame)
        local main_menu = point.menu_y==14 and point.menu_max==1
        local move_menu = point.menu_y==12 and point.menu_x==5
        local party_menu = point.menu_y==1 and point.menu_x==0   -- PartyMenuInit, see the header
        if main_menu then
            if point.menu_x~=9 then return tap("Left", frame), "rival-select-fight" end
            return tap("A", frame), "rival-open-fight"
        end
        if move_menu then
            if point.menu_index~=0 then return tap("Up", frame), "rival-select-move" end
            return tap("A", frame), "rival-use-move"
        end
        if party_menu then
            -- A KO opened "choose a POKéMON".  A on a fainted slot is refused with a text box
            -- and the menu reopens on the SAME index (wPartyAndBillsPCSavedMenuItem), so an
            -- index that has already been offered an A is stepped past instead of retried.
            if self.switch_tried[point.menu_index] then return tap("Down", frame), "rival-switch-next" end
            local buttons = tap("A", frame)
            if buttons.A then
                self.switch_tried[point.menu_index] = true
                log(string.format("RIVAL_SWITCH slot=%d", point.menu_index))
            end
            return buttons, "rival-switch"
        end
        return tap("A", frame), "rival-dialogue"
    end

    function self.step(handshake, status, point, frame)
        assert(type(frame)=="number" and frame>self.last_frame, "Route 22 route frame did not advance")
        self.last_frame = frame
        check_point(point, "Route 22 route")
        -- The rival battle: wIsInBattle == 2 (core.asm:6691-6692, set by InitBattleCommon for
        -- every trainer battle).  It is the only trainer battle this route can meet.
        if point.battle==2 or self.rival_seen then
            if point.battle==2 then
                assert(point.opponent==M.RIVAL1,
                    "trainer battle on Route 22 was opponent "..point.opponent..", not Rival1")
                if not self.rival_seen then self.rival_seen, self.rival_frame = true, frame end
                assert(frame - self.rival_frame <= M.BATTLE_BOUND, "the rival battle never closed")
                return fight(point, frame)
            end
            if not self.over_logged then
                self.over_logged = true
                log(string.format("RIVAL_OVER result=%d", point.battle_result))
            end
            if point.battle_result==0 then return idle(), "rival-won" end
            if point.battle_result==1 then return idle(), "rival-lost" end
            return idle(), "rival-drawn"
        end
        -- Incidental wild battle: hand the frame to the proven RUN handling in
        -- gen1_rb_route1_inputs.lua:41-61 (map-agnostic; its own post-battle assertion runs on
        -- the first non-battle frame, so it is called once more to let that fire).
        if point.battle~=0 or self.wild_active then
            if point.battle~=0 and point.party_hp==0 then return idle(), "starter-koed" end
            local buttons, phase = r1.step(handshake, status, point, frame)
            if point.battle~=0 then
                if not self.wild_active then
                    self.wild_active = true
                    self.incidental_battles = self.incidental_battles + 1
                    log(string.format("INCIDENTAL_BATTLE %d map=%d (%d,%d)",
                        self.incidental_battles, point.map, point.x, point.y))
                end
                return buttons, phase
            end
            self.wild_active = false
            self.tile = nil -- the battle froze the stall clock; restart it on the next step
        end
        -- Standing on a trigger coordinate IS the script's condition (Route22DefaultScript
        -- :62-63 ArePlayerCoordsInArray), so the marker is logged on arrival rather than on
        -- the wJoyIgnore edge the script raises one frame later and clears again at :124.
        if point.map==M.MAP.route22 and on_trigger_tile(point) and not self.triggered then
            self.triggered = frame
            log(string.format("RIVAL_TRIGGER map=%d x=%d y=%d", point.map, point.x, point.y))
        end
        -- B advances every prompt-gated text box and never talks to an NPC, so it is safe both
        -- for the walk's stray boxes and for the rival's scripted challenge dialogue.
        if point.font_loaded or point.joy_ignore~=0 then return tap("B", frame), "close-text" end
        if point.map==M.MAP.route1 then return follow("route1_north", point, frame) end
        if point.map==M.MAP.viridian then return follow("viridian_west", point, frame) end
        if point.map==M.MAP.route22 then
            local buttons, phase = follow("route22_rival", point, frame)
            -- Parked on the last trigger tile with the script quiet means the trigger never
            -- armed: the Pokedex chain did not run, or the event was already spent. Graced,
            -- because the script needs a frame to raise wJoyIgnore after the step lands.
            if phase=="route22_rival-arrival" then
                self.arrival_frame = self.arrival_frame or frame
                if frame - self.arrival_frame >= M.TRIGGER_GRACE then return idle(), "rival-never-triggered" end
                return idle(), "rival-trigger-wait"
            end
            return buttons, phase
        end
        return idle(), "unknown-map"
    end
    return self
end

return M
