-- lua/tests/gen1_rb_forest_inputs.lua — the Viridian Forest scripted-input drivers for the
-- S-4 poison-faint scenario (plan A7). Three drivers share this file:
--
--   M.new(expected [, opts])     Route 1 (10,35) -> Viridian City -> Route 2 -> Viridian
--                                Forest South Gate -> Viridian Forest, parked at (18,41).
--                                No hunt, no capture.                terminal "forest-parked"
--   M.hunt(expected, opts)       pace (18,41)<->(18,40) until Charmander is PSN.  terminals
--                                "poisoned" | "hunt-exhausted" | "starter-koed" | "hunt-stuck"
--                                (the last is a wedged battle driver, never the game's RNG)
--   M.shuttle(expected [, opts]) (18,41) -> (18,43), then shuttle (18,43)<->(18,44) until the
--                                party HP reaches 0.                terminal "poison-fainted"
--
-- Same shape as the sibling route modules (gen1_rb_route1_inputs / gen1_rb_parcel_inputs /
-- gen1_rb_hunt_inputs): step(handshake, status, point, frame) -> buttons, phase; the caller
-- owns emu.frameadvance. M.new matches the module protocol of gen1_scripted_play.lua:137-163
-- so the host can register it in MODULES. M.hunt/M.shuttle additionally take the hunt module's
-- opts bundle (driver/step/rd/symbols/log, gen1_rb_hunt_inputs.lua:56-63) because they must
-- read WRAM the scripted point does not carry and must drive battle menus through
-- gen1_battle_driver.lua (never reimplemented here).
--
-- Logged markers (phase transitions and events only — no per-frame logging):
--   INCIDENTAL_BATTLE n map=M (x,y)        a wild battle on the walk; run from, not fatal
--   HUNT_ENCOUNTER n species=S (x,y)       every forest encounter
--   HUNT_RUN_WRONG_SPECIES species=S       not Weedle -> RUN
--   HUNT_GROWL turn=T why=W                one Growl at the Weedle
--   HUNT_POISONED encounters=N steps=M     wPartyMon1Status PSN observed
--   HUNT_EXHAUSTED steps=N encounters=M    the bound was hit (RNG, not a driver fault)
--   POISON_SHUTTLE hp=H / POISON_FAINT steps=N
--
-- ─────────────────────────────────────────────────────────────────────────────────────────
-- VERIFIED FACTS (pret/pokered @ 405b6246372d7e5a2cb029cbb65219b13286b8c9, checked out at
-- E:/Google Drive/SLink/.cache/pret/pokered).  Everything below was read out of those files;
-- nothing here is a remembered constant.  Items the plan marked † are called out as such.
--
-- Geometry decoding procedure (same one gen1_rb_hunt_inputs.lua:15-18 used for Route 1):
--   maps/<Map>.blk is width*height block ids; gfx/blocksets/<tileset>.bst is 16 tile ids per
--   block (4x4).  A player coordinate is a HALF-block, so map size in (x,y) is 2x the block
--   size.  Within the 4x4 block the half-block (x,y) covers tile columns 2*(x%2)..+1 and rows
--   2*(y%2)..+1.  The COLLISION tile is the half-block's bottom-LEFT tile — the engine reads
--   it at tilemap (8,9) (home/overworld.asm:1298 "tile the player is on", and
--   engine/overworld/player_state.asm:260-292 offsets by 2 tiles for the tile in front) — and
--   a tile is walkable iff it appears in that tileset's *_Coll list
--   (data/tilesets/collision_tile_ids.asm; Overworld :12, Forest :29, ForestGate :32).  The
--   GRASS tile is the half-block's bottom-RIGHT tile, read at tilemap (9,9)
--   (engine/battle/wild_encounters.asm:27-33).  Ledge tiles ($27/$36/$37/$0D/$1D,
--   data/tilesets/ledge_tiles.asm) are absent from Overworld_Coll, so this decoding treats a
--   ledge as impassable — which is what a northbound route needs.
--   Control: re-running it on Route 1 reproduces gen1_rb_hunt_inputs.lua's pinned grass patch
--   (x 10-11, y 32-35, probe $52) exactly, so the probe itself is known-good.
--
-- Maps and sizes (constants/map_constants.asm): ROUTE_1 $0C 10x18 (:42), VIRIDIAN_CITY $01
--   20x18 (:27), ROUTE_2 $0D 10x36 (:43), VIRIDIAN_FOREST_SOUTH_GATE $32 5x4 (:86),
--   VIRIDIAN_FOREST $33 17x24 (:89).
--
-- †Connections (macros/scripts/maps.asm:180-190: a north connection arrives at
--   _y = TARGET_HEIGHT*2 - 1 with _x = offset * -2 added to the player's x):
--     data/maps/headers/Route1.asm:2       connection north, ViridianCity, -5
--                                          -> Route 1 (11,-1) arrives Viridian (21,35)
--     data/maps/headers/ViridianCity.asm:2 connection north, Route2, 5
--                                          -> Viridian (18,-1) arrives Route 2 (8,71)
--   Both match the plan's pinned entry coordinates, and the Viridian->Route 1 direction
--   agrees with the proven-live gen1_rb_parcel_inputs.lua:20-21 southbound numbers.
--
-- †Warps (macros/scripts/maps.asm:51-52 stores warp_id - 1, i.e. the .asm ids are 1-based):
--     data/maps/objects/Route2.asm:14   warp_event 3,43 -> SOUTH_GATE id 3 -> stored 2
--                                       -> South Gate warp #2 = (4,7)
--                                          (ViridianForestSouthGate.asm:11)
--     data/maps/objects/ViridianForestSouthGate.asm:10 warp_event 5,0 -> FOREST id 5
--                                       -> stored 4 -> forest warp #4 = (17,47)
--                                          (ViridianForest.asm:19)
--   †(4,0) of the gate is NOT a warp the route can use: its collision tile is $4a, which is
--   absent from ForestGate_Coll (collision_tile_ids.asm:32-34) — a wall.  (5,0) (tile $3b) is
--   the only walkable tile in gate row 0, so {5,7},{5,0} is forced.
--
-- †Viridian City obstacles (data/maps/objects/ViridianCity.asm):
--     :22 bg_event 19,1 TRAINER_TIPS1 — the sign.  (19,1) decodes as non-walkable, so the
--         northbound column must shift to x=18 at y=2 before leaving the map.  Confirmed.
--     :29 youngster (13,20) WALK ANY_DIR and :35 old man (17,5) WALK LEFT_RIGHT.  Row 5 is
--         walkable x=16..27 and row 20 x=4..35, so both wanderers can stand on the x=19/20
--         column this route uses -> the stall/detour logic below is required, not optional.
--     Ledge row y=27 has exactly two passable columns, x=15 and x=19; the waypoints use x=19.
--
-- †Route 2 (decoded): ledge row y=61 is passable only at x=7 and x=15 (the waypoints use
--   x=7), and row y=47 only at x=8..10 (the waypoints use x=10).  The Route 2 grass block is
--   x=4..9, y=48..51 (probe $52); holding y=52 from x=4 to x=10 bypasses all of it.
--
-- †Viridian Forest hazards (data/maps/objects/ViridianForest.asm + scripts/ViridianForest.asm):
--     Bug Catchers at (30,33) and (30,19) have sight range 4 (scripts:36,38) and (2,18) has
--     range 1 (scripts:40); all three face LEFT in rows 33/19/18.  This route never leaves
--     rows 40-47, so no sight line can reach it.  The non-trainer youngster at (16,43)
--     (objects:31) is adjacent to the (17,43) waypoint but never on it.
--
-- †Wild data (data/wild/maps/ViridianForest.asm): :2 def_grass_wildmons 8 — the encounter
--   rate byte is 8 (of 256).  The _BLUE block (:13-21) has `db 3, WEEDLE` as slot 8; slots
--   1-7 and 9-10 are Caterpie/Metapod/Kakuna/Pikachu.  Weedle's INTERNAL species id is $70
--   (constants/pokemon_constants.asm:121), cross-checked against this repo's
--   data/games/gen1_rby/species_index.json (national 13 -> index 112 = $70).
--
-- †Grass tiles: data/tilesets/tileset_headers.asm:15 `tileset Forest, -1,-1,-1, $20` (and
--   :12 Overworld $52).  Decoded at the pacing column:
--       (18,41) probe $20  (18,40) probe $20   -> BOTH grass
--       (19,41) probe $34  (19,40) probe $34   -> the RIGHT half-blocks are NOT grass
--   x=18 is even, i.e. the LEFT half-block of its block: †"only the left-hand steps of a
--   block encounter" confirmed — every step of the (18,41)<->(18,40) pace rolls.
-- †Shuttle tiles: (18,43) probe $30 and (18,44) probe $30 — non-grass.  Stronger still, a
--   non-grass half-block in Viridian Forest can NEVER roll: wild_encounters.asm:38-46 falls
--   through to `.CantEncounter2` for the FOREST tileset, so the shuttle is encounter-free by
--   construction, not by luck.
--
-- Encounter-roll eligibility (the hunt budget counts these, not raw steps):
--   engine/battle/core.asm:6661-6664 — DetermineWildOpponent returns before TryDoWildEncounter
--   while wNumberOfNoRandomBattleStepsLeft is non-zero; home/overworld.asm:15-16 grants 3 of
--   them on map entry after a battle and :296-305 burns one per completed step.  So an
--   "eligible" step is a completed step onto a grass half-block with that byte at 0.
--
-- Poison:
--   PSN is bit 3 of the status byte (constants/battle_constants.asm:64; engine/events/
--   poison.asm:18 `and 1 << PSN`), i.e. mask $08.
--   Mid-turn, PoisonEffect writes only wBattleMonStatus (engine/battle/effects.asm:78-86 and
--   :119-120) — but ReadPlayerMonCurHPAndStatus copies HP+status into the party struct at the
--   TOP of every MainInBattleLoop iteration (engine/battle/core.asm:280-281, :1798-1809), so
--   wPartyMon1Status is exact at each battle menu.  This driver only reads it at a battle
--   menu, which is why the plan's wPartyMon1Status oracle is sound.
--   Overworld: 1 HP every 4th step (engine/events/poison.asm:10-12), the faint text at :41-57,
--   and $FF into wOutOfBattleBlackout once no party member is alive (:89-108).
--   Growl is Charmander's move slot 2 — the same slot gen1_rb_ball_gate_inputs.lua:109-131
--   already drives through move2/move2_pp.
--
-- COMPUTED ZERO-GRASS CHECK (each waypoint segment walked with the same x-then-y rule move()
-- uses below, every half-block stood on tested against the decoded tile ids):
--     Route 1      (10,35) -> (11,-1)   53 steps  0 unwalkable  15 GRASS
--     Viridian     (21,35) -> (18,-1)   39 steps  0 unwalkable   0 grass
--     Route 2       (8,71) -> (3,43)    45 steps  0 unwalkable   0 grass
--     South Gate     (4,7) -> (5,0)      8 steps  0 unwalkable   0 grass
--     Forest       (17,47) -> (18,41)    7 steps  0 unwalkable   1 grass (the park tile)
-- The plan's "zero grass steps until the forest" holds from the Viridian entry onward, but
-- NOT for the Route 1 leg: a Dijkstra over the decoded Route 1 with grass as cost, from
-- (10,35) to the north edge, returns a minimum of 15 grass steps — and its minimum-cost path
-- is exactly the proven-live gen1_rb_parcel_inputs.lua:18 `route_north` waypoint list reused
-- here.  Route 1's only northbound corridor (x=10-11, y=32-35) is solid grass.  At Route 1's
-- 25/256 rate (data/wild/maps/Route1.asm:2) an incidental battle on that leg is likely, so it
-- is RUN from (the proven handling in gen1_rb_route1_inputs.lua:41-61, delegated to rather
-- than copied) and logged INCIDENTAL_BATTLE.  RUN ends an encounter; it does not prevent one.
local M = {}

M.MAP = { route1 = 0x0C, viridian = 0x01, route2 = 0x0D, gate = 0x32, forest = 0x33 }
M.WEEDLE = 0x70          -- internal species id, see the header
M.GROWL_SLOT = 2         -- Charmander's move 2
M.PARK = { 18, 41 }
M.PACE = { { 18, 41 }, { 18, 40 } }
M.SHUTTLE = { { 18, 43 }, { 18, 44 } }
M.MAX_ENCOUNTERS = 60    -- 3x the ~20-encounter mean for a slot-8 Weedle
M.MAX_GRASS_STEPS = 2000 -- ~3x the ~630 eligible-step mean; 0 encounters here = a real fault
M.MAX_GROWL_TURNS = 20
M.STALL_BOUND = 1800     -- the gate drivers' NPC stall bound
M.STALL_NUDGE = 48       -- frames on one tile before sidestepping a wanderer
M.DETOUR_FRAMES = 32

-- Northbound waypoints. Route 1's list is gen1_rb_parcel_inputs.lua:18 `route_north`
-- (proven live, and provably the minimum-grass crossing); the rest are decoded here.
local paths = {
    route1_north = { {10,31},{8,31},{8,24},{12,24},{12,22},{9,22},{9,14},{14,14},{14,4},{11,4},{11,-1} },
    viridian_north = { {20,30},{19,30},{19,26},{19,2},{18,2},{18,-1} },
    route2_north = { {8,62},{7,62},{7,57},{4,57},{4,52},{10,52},{10,44},{3,44},{3,43} },
    gate_north = { {5,7},{5,0} },
    forest_park = { {17,43},{18,43},{18,42},{18,41} },
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
        and type(point.battle)=="number" and type(point.party_hp)=="number",
        "complete read-only "..what.." point required")
end
local function identity(expected, what)
    assert(expected and (expected.player=="a" or expected.player=="b"), what.." identity required")
end
-- This file is dofile'd by absolute path, so its own directory locates its siblings.
local function here()
    return (debug.getinfo(1, "S").source or ""):match("^@(.*[/\\])") or ""
end

-- ── the walk: Route 1 north end -> parked in the forest at (18,41) ────────────────────────
function M.new(expected, opts)
    identity(expected, "R/B forest route")
    opts = opts or {}
    local log = opts.log or function() end
    local r1 = dofile(here() .. "gen1_rb_route1_inputs.lua").new(expected)
    local self = { last_frame=-1, segments={}, wild_active=false, incidental_battles=0,
                   tile=nil, tile_frame=0, detour=nil, detour_along=nil, detour_until=nil, flip=false }
    local function follow(name, point, frame)
        local targets = paths[name]
        local index = self.segments[name] or 1
        while targets[index] and point.x==targets[index][1] and point.y==targets[index][2] do index=index+1 end
        self.segments[name] = index
        if not targets[index] then return idle(), name.."-arrival" end
        -- A step blocked by a wanderer leaves the tile unchanged. After STALL_NUDGE frames on
        -- one tile, detour: DETOUR_FRAMES sideways (alternating sides), then DETOUR_FRAMES
        -- along the travel axis, so the re-aim lands PAST the blocker instead of walking back
        -- into it -- move() is x-then-y, so a sidestep alone always returns to the same tile.
        -- The detour window is frame-based on purpose: it must survive the tiles it changes.
        local tile = point.map.."/"..point.x.."/"..point.y
        if tile ~= self.tile then self.tile, self.tile_frame = tile, frame end
        assert(frame - self.tile_frame <= M.STALL_BOUND,
            "forest route stalled "..M.STALL_BOUND.." frames at "..tile)
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
    function self.step(handshake, status, point, frame)
        assert(type(frame)=="number" and frame>self.last_frame, "forest route frame did not advance")
        self.last_frame = frame
        check_point(point, "forest route")
        -- Incidental wild battle: hand the frame to the proven RUN handling in
        -- gen1_rb_route1_inputs.lua:41-61 (map-agnostic; its own post-battle assertion runs on
        -- the first non-battle frame, so it is called once more to let that fire).
        if point.battle ~= 0 or self.wild_active then
            local buttons, phase = r1.step(handshake, status, point, frame)
            if point.battle ~= 0 then
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
        if point.font_loaded or point.joy_ignore ~= 0 then return tap("B", frame), "close-text" end
        if point.map == M.MAP.route1 then return follow("route1_north", point, frame) end
        if point.map == M.MAP.viridian then return follow("viridian_north", point, frame) end
        if point.map == M.MAP.route2 then return follow("route2_north", point, frame) end
        if point.map == M.MAP.gate then return follow("gate_north", point, frame) end
        if point.map == M.MAP.forest then
            if point.x==M.PARK[1] and point.y==M.PARK[2] then return idle(), "forest-parked" end
            return follow("forest_park", point, frame)
        end
        return idle(), "unknown-map"
    end
    return self
end

-- ── the hunt: pace the two grass half-blocks until Charmander is poisoned ─────────────────
-- opts.driver  gen1_battle_driver built by the caller over a step that yields the buttons
-- opts.step    that same yielding step;  opts.rd  read_u8 on the System Bus
-- opts.symbols the title's pret .sym table;  opts.log  optional line sink
function M.hunt(expected, opts)
    identity(expected, "R/B forest hunt")
    assert(opts and opts.driver and opts.step and opts.rd and opts.symbols,
        "forest hunt needs driver/step/rd/symbols")
    local D, step, rd, S = opts.driver, opts.step, opts.rd, opts.symbols
    local log = opts.log or function() end
    local self = { last_frame=-1, encounters=0, grass_steps=0, target=1, tile=nil,
                   battle_co=nil, stage="pace", terminal=nil, outcome=nil }
    -- assert() returns (value, message), so bind first: rd must be called with one argument.
    local function u8(name) local a = assert(S[name], "no symbol "..name); return rd(a) end
    local function poisoned() return math.floor(u8("wPartyMon1Status")/8)%2 == 1 end
    local function mash(btn, frames) for i=1,frames do step({[btn] = i%16<2}) end end
    -- The next battle menu after the driver's last A press, tapping B through anything that
    -- waits for a button (damage text, the "was poisoned" box, level-up boxes).
    local function wait_menu(budget)
        local used = 0
        while used < budget do
            local r = D.wait_menu(240)
            used = used + r.frames
            if r.ok then return "menu" end
            if r.why == "battle_over" then return "battle_over" end
            mash("B", 32); used = used + 32
        end
        return "timeout"
    end
    local function run_away()
        for _ = 1, 10 do
            local t = D.run(600)
            if t.ok then return "ran" end
            if t.why == "battle_over" then return "battle_over" end
            if t.why ~= "battle_menu_again" then
                local m = wait_menu(1200)
                if m ~= "menu" then return m end
            end
        end
        return "stuck"
    end
    -- One encounter, start to finish, inside a coroutine so every buttons value still costs
    -- the caller exactly one frame.
    local function plan()
        self.stage = "intro"
        local m = wait_menu(1800)
        if m ~= "menu" then return m end
        local species = u8("wEnemyMonSpecies")
        if species ~= M.WEEDLE then
            self.stage = "run-wrong-species"
            log("HUNT_RUN_WRONG_SPECIES species=" .. species)
            return run_away()
        end
        for turn = 1, M.MAX_GROWL_TURNS do
            if poisoned() then break end
            self.stage = "growl"
            local c = D.choose("FIGHT")
            if not c.ok then return c.why == "battle_over" and "battle_over" or "stuck" end
            local t = D.commit_move(M.GROWL_SLOT, 900)
            log(string.format("HUNT_GROWL turn=%d why=%s", turn, tostring(t.why)))
            if t.why == "battle_over" then return "battle_over" end
            m = wait_menu(1800)
            if poisoned() then break end
            if m ~= "menu" then return m end
        end
        self.stage = "run"
        local why = run_away()
        return poisoned() and "poisoned" or why
    end
    function self.step(handshake, status, point, frame)
        assert(type(frame)=="number" and frame>self.last_frame, "forest hunt frame did not advance")
        self.last_frame = frame
        check_point(point, "forest hunt")
        if self.terminal then return idle(), self.terminal end
        if point.battle ~= 0 and point.battle ~= 1 then
            self.terminal = "starter-koed"
            return idle(), self.terminal
        end
        if point.battle == 1 and not self.battle_co then
            self.encounters = self.encounters + 1
            self.battle_co = coroutine.create(plan)
            log(string.format("HUNT_ENCOUNTER %d species=%d (%d,%d)",
                self.encounters, u8("wEnemyMonSpecies"), point.x, point.y))
        end
        if self.battle_co then
            local ok, res = coroutine.resume(self.battle_co)
            assert(ok, "forest hunt battle plan error: " .. tostring(res))
            if coroutine.status(self.battle_co) ~= "dead" then return res or idle(), "wild-"..self.stage end
            self.battle_co, self.outcome, self.tile = nil, res, nil
            return idle(), "wild-" .. tostring(res)
        end
        if point.battle ~= 0 then return idle(), "wild-ending" end
        if self.outcome then
            local why = self.outcome
            self.outcome = nil
            if point.party_hp == 0 then self.terminal = "starter-koed"
            elseif poisoned() then
                self.terminal = "poisoned"
                log(string.format("HUNT_POISONED encounters=%d steps=%d", self.encounters, self.grass_steps))
            -- A wedged battle driver is NOT a KO: give it its own terminal so the receipt
            -- cannot be read as the game's RNG.
            elseif why == "stuck" or why == "timeout" then self.terminal = "hunt-stuck" end
            if self.terminal then return idle(), self.terminal end
        end
        if point.font_loaded or point.joy_ignore ~= 0 then return tap("B", frame), "close-text" end
        if point.map ~= M.MAP.forest then return idle(), "unknown-map" end
        -- Count only steps that can actually roll (see the header): a completed step with the
        -- post-battle cooldown at 0. Both pace tiles are grass, so every such step is eligible.
        local tile = point.x .. "/" .. point.y
        if tile ~= self.tile then
            if self.tile and u8("wNumberOfNoRandomBattleStepsLeft") == 0 then
                self.grass_steps = self.grass_steps + 1
            end
            self.tile = tile
        end
        if self.encounters >= M.MAX_ENCOUNTERS or self.grass_steps >= M.MAX_GRASS_STEPS then
            self.terminal = "hunt-exhausted"
            log(string.format("HUNT_EXHAUSTED steps=%d encounters=%d", self.grass_steps, self.encounters))
            return idle(), self.terminal
        end
        local target = M.PACE[self.target]
        if point.x == target[1] and point.y == target[2] then
            self.target = 3 - self.target
            target = M.PACE[self.target]
        end
        return move(point, target), "pace-grass"
    end
    return self
end

-- ── the shuttle: walk non-grass tiles until poison drops the last mon ─────────────────────
function M.shuttle(expected, opts)
    identity(expected, "R/B forest shuttle")
    opts = opts or {}
    local log = opts.log or function() end
    local self = { last_frame=-1, target=1, terminal=nil, steps=0, tile=nil, announced=false }
    function self.step(handshake, status, point, frame)
        assert(type(frame)=="number" and frame>self.last_frame, "forest shuttle frame did not advance")
        self.last_frame = frame
        check_point(point, "forest shuttle")
        if self.terminal then return idle(), self.terminal end
        -- poison_faint is the client's own signal when the host extends the point with it;
        -- party HP 0 is the game's state and is enough on its own.
        if point.party_hp == 0 or point.poison_faint then
            self.terminal = "poison-fainted"
            log(string.format("POISON_FAINT steps=%d", self.steps))
            return idle(), self.terminal
        end
        if not self.announced then
            self.announced = true
            log(string.format("POISON_SHUTTLE hp=%d", point.party_hp))
        end
        -- "<MON> fainted"/"blacked out!" boxes wait for a button (engine/events/poison.asm:41-57).
        if point.font_loaded or point.joy_ignore ~= 0 then return tap("B", frame), "poison-text" end
        if point.map ~= M.MAP.forest then return idle(), "unknown-map" end
        local tile = point.x .. "/" .. point.y
        if tile ~= self.tile then
            if self.tile then self.steps = self.steps + 1 end
            self.tile = tile
        end
        -- From the pace tile, (18,42) and (18,43) are both non-grass, so the approach cannot
        -- roll an encounter either (FOREST tileset, wild_encounters.asm:38-46).
        if point.y < M.SHUTTLE[1][2] then return move(point, M.SHUTTLE[1]), "shuttle-approach" end
        local target = M.SHUTTLE[self.target]
        if point.x == target[1] and point.y == target[2] then
            self.target = 3 - self.target
            target = M.SHUTTLE[self.target]
        end
        return move(point, target), "shuttle-poison"
    end
    return self
end

return M
