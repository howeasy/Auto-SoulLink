-- lua/tests/gen1_rb_route22_inputs.lua — the Route 22 rival driver for the D-11/W-4 rival
-- team swap scenario (plan A13).  One driver:
--
--   M.new(expected [, opts])   Route 1 (10,35) -> Viridian City -> the WEST edge -> Route 22
--                              -> the rival trigger tile, then FIGHTs Rival1 to the end.
--                              terminals "rival-won" | "rival-lost" | "rival-drawn"
--                                        | "rival-never-triggered" | "active-koed"
--                                        | "rival-fight-stuck" | "unknown-map"
--
-- The rival battle is played THROUGH lua/tests/gen1_battle_driver.lua (opts.driver, bridged with
-- a coroutine exactly as gen1_rb_hunt_inputs.lua:56-63 does it). This file owns no battle-menu
-- state machine of its own: the move cursor in particular is 1-BASED
-- (wCurrentMenuItem = wPlayerMoveListIndex + 1, pret engine/battle/core.asm:2544-2547, :2575-2578;
-- index 0 wraps to the LAST move, :2692-2700; the conversion back to 0-based happens only after
-- the selection, :2624-2636), and D.commit_move is the one implementation that knows that.
--
-- Same shape as the sibling route modules (gen1_rb_route1_inputs / gen1_rb_forest_inputs /
-- gen1_rb_center_inputs): step(handshake, status, point, frame) -> buttons, phase; the caller
-- owns emu.frameadvance and feeds gen1_scripted_play.lua's read-only point.
--
-- Logged markers (phase transitions and events only — no per-frame logging):
--   INCIDENTAL_BATTLE n map=M (x,y)     a wild battle on the walk; RUN from, not fatal
--   WALK_KO slot=N                      the ACTIVE battler fainted on the walk (terminal)
--   RIVAL_TRIGGER map=M x=X y=Y         the frame wJoyIgnore latched on a trigger tile
--   RIVAL_SWITCH slot=N                 the replacement the ENGINE accepted after a KO
--   RIVAL_FIGHT end=<why>               how the battle plan left the rival battle
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
-- The shared input shapes (idle/hold/tap/move): this file's own directory locates the module,
-- the way the sibling drivers are already loaded.
local function here() return (debug.getinfo(1, "S").source or ""):match("^@(.*[/\\])") or "" end
local C = dofile(here() .. "gen1_inputs_common.lua")
local idle, hold, tap, move = C.idle, C.hold, C.tap, C.move

local M = {}

M.MAP = { route1 = 0x0C, viridian = 0x01, route22 = 0x21 }
M.RIVAL1 = 225                 -- OPP_RIVAL1, see the header
M.TRIGGER = { { 29, 5 }, { 29, 4 } }
M.STALL_BOUND = 1800           -- the gate drivers' NPC stall bound
M.STALL_NUDGE = 48             -- frames on one tile before sidestepping a wanderer
M.DETOUR_FRAMES = 32
M.BATTLE_BOUND = 60000         -- a rival battle that never closes is a driver fault
M.TRIGGER_GRACE = 600          -- frames parked on (29,4) before "the rival never triggered"
-- PartyMenuInit geometry (home/pokemon.asm:210-216) and PARTYMON_STRUCT_LENGTH = $2c
-- (constants/pokemon_data_constants.asm:56); current HP is bytes +1/+2, so wPartyMon1HP is base.
M.PARTY_MENU = { y = 1, x = 0, watched = 0x03 }  -- watched = PAD_A | PAD_B
M.PARTY_STRUCT = 44

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

-- opts.driver   gen1_battle_driver built by the caller over a step that yields the buttons
--               (the same wiring gen1_rb_hunt_inputs.lua:56-63 / duo_gen1_main.lua:357-377 use)
-- opts.step     that same yielding step, for the taps between driver calls
-- opts.rd       read_u8 on the System Bus;  opts.symbols  the title's pret .sym table
-- opts.log      optional line sink
function M.new(expected, opts)
    assert(expected and (expected.player=="a" or expected.player=="b"), "R/B Route 22 identity required")
    opts = opts or {}
    assert(opts.driver and opts.step and opts.rd and opts.symbols,
           "Route 22 needs driver/step/rd/symbols: the rival fight runs on gen1_battle_driver")
    local D, step, rd, S = opts.driver, opts.step, opts.rd, opts.symbols
    local log = opts.log or function() end
    paths.route1_north = paths.route1_north
        or assert(dofile(here() .. "gen1_rb_forest_inputs.lua").PATHS.route1_north,
                  "forest module carries no route1_north path")
    local r1 = dofile(here() .. "gen1_rb_route1_inputs.lua").new(expected)
    local self = { last_frame=-1, segments={}, wild_active=false, incidental_battles=0,
                   tile=nil, tile_frame=0, detour=nil, detour_along=nil, detour_until=nil,
                   flip=false, triggered=nil, rival_seen=false, rival_frame=nil,
                   arrival_frame=nil, over_logged=false, battle_co=nil, koed_slot=nil }

    -- `assert` returns ALL its arguments, so the address is bound first and never passed
    -- straight into rd() (which would hand it the message as a second argument).
    local HP1 = assert(S.wPartyMon1HP, "no symbol wPartyMon1HP")
    local COUNT = assert(S.wPartyCount, "no symbol wPartyCount")
    local ACTIVE = assert(S.wPlayerMonNumber, "no symbol wPlayerMonNumber")
    local CURSOR = assert(S.wCurrentMenuItem, "no symbol wCurrentMenuItem")
    local function slot_hp(slot)
        local at = HP1 + slot * M.PARTY_STRUCT
        return rd(at)*256 + rd(at+1)
    end
    local function party_menu_up()
        local st = D.state()
        return st.y==M.PARTY_MENU.y and st.x==M.PARTY_MENU.x and st.watched==M.PARTY_MENU.watched
    end
    local function idle_frames(n) for _=1,n do step(nil) end end
    local function mash(btn, frames) for i=1,frames do step({[btn]=i%16<2}) end end
    -- the un-mergeable press shape gen1_battle_driver.lua:87-88 uses: released, held, released
    local function press(btn) idle_frames(2); for _=1,3 do step({[btn]=true}) end; idle_frames(3) end

    -- The party menu is only FORCED when the active battler is down; the menu's geometry alone
    -- does not say that, because nothing on the acceptance path clears it (see below). This is
    -- the predicate that decides whether a replacement is owed, and it is engine truth.
    local function needs_replacement()
        return party_menu_up() and slot_hp(rd(ACTIVE)) == 0
    end

    -- Forced replacement after a KO: HandlePlayerMonFainted -> ChooseNextMon -> DisplayPartyMenu
    -- (core.asm:1086-1089). Three rules, all the engine's:
    --   * only offer a slot whose party HP is non-zero. A on a fainted slot returns through
    --     HasMonFainted/GoBackToPartyMenu (:1096-1097) and the menu reopens on the SAME index --
    --     which is why the old "mark this slot tried the frame we emit A" bookkeeping blacklisted
    --     USABLE mons: the tap held A for two frames and the second frame took the tried branch
    --     for a press the menu had not been polled for yet.
    --   * accept only the engine's own receipt that a slot was taken: wPlayerMonNumber moving
    --     from the fainted slot to the chosen live one, `ld a,[wWhichPokemon] /
    --     ld [wPlayerMonNumber], a` (:1108-1109), with the fainted slot still at 0 HP. Never an
    --     emitted button.
    --   * the menu GEOMETRY is not part of that receipt. HandlePartyMenuInput returns through
    --     `call BankswitchBack / and a / ret` (home/pokemon.asm:264-275) without resetting
    --     wTopMenuItemY/X or wMenuWatchedKeys, and the commit at :1108-1109 is followed by
    --     LoadBattleMonFromParty, the palette/HUD loads (:1118-1123) and the whole of SendOutMon
    --     (:1124, :1723-1766: PrintSendOutMonMessage, LoadMonBackPic, POOF_ANIM,
    --     AnimateSendingOutMon, PlayCry). Waiting for the fields to go stale-clear declared
    --     `no-replacement` on a slow send-out the engine had already accepted, or pressed A into
    --     it a second time. party_menu_up() is kept only for deciding whether to PRESS.
    local function choose_replacement()
        local count = rd(COUNT)
        local down = rd(ACTIVE) -- the slot that just fainted; the receipt is a move away from it
        for slot = 0, math.min(count, 6) - 1 do
            if slot ~= down and slot_hp(slot) > 0 then
                for _ = 1, 8 do
                    local cur = rd(CURSOR)
                    if cur == slot then break end
                    press(cur < slot and "Down" or "Up")
                    local moved = false
                    for _ = 1, 12 do
                        if rd(CURSOR) ~= cur then moved = true break end
                        step(nil)
                    end
                    if not moved then break end
                end
                if party_menu_up() and rd(CURSOR) == slot then
                    for _ = 1, 3 do
                        press("A")
                        -- the commit is a handful of frames behind the accepted press
                        -- (HandlePartyMenuInput -> .monChosen -> ClearSprites -> :1108)
                        for _ = 1, 90 do
                            if rd(ACTIVE)==slot and slot_hp(down)==0 then
                                log(string.format("RIVAL_SWITCH slot=%d", slot))
                                return true
                            end
                            step(nil)
                        end
                    end
                end
            end
        end
        return false
    end

    -- The rival fight, start to finish, inside a coroutine the caller resumes once per frame:
    -- FIGHT + move slot 1 every turn, a replacement on every KO. Every menu press goes through
    -- the battle driver, which pins the geometry and the 1-based move cursor to core.asm.
    local function battle_plan()
        -- This coroutine is created on the first frame of the rival battle, and the driver it
        -- runs on already drove the walk's incidental wild battles: re-seed its DisplayBattleMenu
        -- baseline so "the battle menu is up" cannot be answered out of those
        -- (gen1_battle_driver.lua D.new_battle).
        D.new_battle()
        for _ = 1, 400 do
            if D.state().in_battle==0 then return "battle-over" end
            if needs_replacement() then
                if not choose_replacement() then return "no-replacement" end
                -- the menu-entry evidence is the NEXT loop's D.wait_menu: needs_replacement() is
                -- false the moment the engine commits, so the send-out plays out down there
            else
                local m = D.wait_menu(120)
                if m.why=="battle_over" then return "battle-over" end
                if m.ok then
                    local c = D.choose("FIGHT")
                    if c.why=="battle_over" then return "battle-over" end
                    if c.ok then
                        local t = D.commit_move(1, 900)
                        if t.why=="battle_over" then return "battle-over" end
                    elseif not needs_replacement() then
                        -- The cursor never reached FIGHT, so a PrintText box owns the frame and
                        -- the menu is not really up; D.choose only ever emits directions here and
                        -- WaitForTextScrollButtonPress watches A|B alone (home/joypad2.asm:55-81),
                        -- so without this the plan burns its whole 400-iteration budget pressing a
                        -- key nothing reads. Same B-mash, same reason, as the branch below.
                        mash("B", 32)
                    end
                elseif not needs_replacement() then
                    mash("B", 32) -- a PrintText box between menus; B is watched by neither
                end
            end
        end
        return "battle-stuck"
    end

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
                self.battle_co = self.battle_co or coroutine.create(battle_plan)
                if coroutine.status(self.battle_co) ~= "dead" then
                    local ok, res = coroutine.resume(self.battle_co)
                    assert(ok, "rival battle plan error: "..tostring(res))
                    if coroutine.status(self.battle_co) ~= "dead" then return res or idle(), "rival-fight" end
                    self.fight_why = res
                    log("RIVAL_FIGHT end="..tostring(res))
                end
                if self.fight_why=="battle-stuck" or self.fight_why=="no-replacement" then
                    return idle(), "rival-fight-stuck"
                end
                return tap("B", frame), "rival-closing"
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
        -- The KO that ends this leg is the ACTIVE battler's, not slot 0's: point.party_hp is
        -- wPartyMon1HP alone (gen1_scripted_play.lua:88,98) while the engine can have any slot
        -- out (wPlayerMonNumber, written at core.asm:1108-1109). Name the SLOT and leave the
        -- naming to the caller, which owns the keys -- and note that a faint here propagates to
        -- the partner (the client sends `faint`, the server answers force_faint), so their party
        -- may change as a consequence of this one.
        if point.battle~=0 or self.wild_active then
            if point.battle~=0 then
                local active = rd(ACTIVE)
                if active < rd(COUNT) and slot_hp(active)==0 then
                    self.koed_slot = active
                    log(string.format("WALK_KO slot=%d", active))
                    return idle(), "active-koed"
                end
            end
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
