-- gen3_scripted_play.lua — scripted natural-play driver for vanilla FireRed (card gen3-P3-C3-5).
--
-- Exercises the engine sites the shadow observer (lua/gen3/shadow_run.lua) must witness, from
-- the committed fixture tests/fixtures/gen3/firered_town.sav (Pallet Town, trainer JONN, EMPTY
-- party — pre-starter; see tests/fixtures/gen3/README.md). Runs an ordered LEGS table; each leg
-- names the site kinds it exercises (docs/gen3_engine_sites.md's 23-kind list) and a pret
-- citation (pokefirered @ c75f352, cloned at .cache/pret/pokefirered).
--
-- WALK PATHS ARE PRECOMPUTED, NOT GUESSED. Every direction list below (the `PATHS` table) was
-- produced OFFLINE by a Python BFS over data/layouts/<Map>/map.bin: each block is a 16-bit LE
-- word, collision = (word >> 10) & 3 (nonzero blocked), object_event tiles blocked, 4-directional
-- BFS from a start tile to a target tile. Door/warp tiles are collision-BLOCKED in the raw data
-- (verified: PalletTown's own house door (6,7) and the lab door (16,13) both read collision=1);
-- the walkable tile is the one just outside/inside it, and the warp fires on a held press INTO
-- the door from that tile — the same "arrow warp" shape gen3_fr_newgame_inputs.lua leg 6 uses.
-- Map-to-map edges without a door (Route1/PalletTown/ViridianCity) are `connections`
-- (data/maps/<Map>/map.json "connections"), crossed by walking off the relevant edge; the
-- landing x on the far side was verified against that map's own collision grid (not assumed).
-- Every PATHS entry below cites the exact start/end tile and the offline BFS command used.
--
-- WHAT REMAINS A REAL RISK (stated, not hidden — see each leg's comment):
--  - The rival battle and any Route 1 wild battle are driven by generic default-cursor mashing
--    (A repeatedly), not a verified move-by-move plan. gActionSelectionCursor resets to 0 each
--    battle (src/battle_controller_player.c) so "press A twice" IS a pinned FIGHT->move-slot-1
--    selection; anything the wild/rival side does in response is not controlled.
--  - Opening the BAG from the action menu is pinned (Right toggles cursor bit0 to
--    B_ACTION_USE_ITEM, src/battle_controller_player.c:248-253), but the BAG's own pocket-tab
--    and item-list navigation to POKE BALL is NOT pinned from source here — mashed with A on a
--    fallback Down/A pattern, bounded, verified by the real RAM outcome (BATTLE_OUTCOME_ADDR),
--    never assumed to have worked.
--  - The Oak "Pokedex scene" after delivering the parcel is almost entirely NPC `applymovement`
--    (the player only appears to walk when the script itself moves them — the ApproachCounter/
--    dex-scene movements are scripted, not driven by joypad input at all); this driver only
--    mashes A to clear message boxes and waits for the engine to hand control back.
--
-- RESUME: SLINK_GEN3_PLAY_FROM=<leg name> skips every leg before it, assuming the save state
-- those earlier legs would have left is already loaded — the coordinator's job, not this
-- script's.
--
-- Environment: SLINK_ROOT, SLINK_GEN3_CHECKPOINT, SLINK_GEN3_TITLE (see gen3_boot_check.lua),
-- SLINK_GEN3_PLAY_FROM (optional).

local WT = SLINK_ROOT or os.getenv("SLINK_ROOT")
assert(WT, "SLINK_ROOT unset — launch via the gen3 fixture/gate tooling")
local G = dofile(WT .. "/lua/tests/gen3_boot_check.lua")

-- Plaintext (no decrypt needed) RAM observables pinned in lua/games/gen3_frlge.lua's `vanilla`
-- profile table, cited per use below.
local PARTY_COUNT_ADDR    = 0x02024029  -- gPlayerPartyCount (vanilla.PARTY_COUNT_ADDR)
local BATTLE_OUTCOME_ADDR = 0x02023E8A  -- vanilla.BATTLE_OUTCOME_ADDR; B_OUTCOME_CAUGHT == 7
                                         -- (pret include/constants/battle.h:82)
local BATTLE_RESULTS_ADDR = 0x03004F90  -- vanilla.BATTLE_RESULTS_ADDR; playerFaintCounter @ +0
local B_OUTCOME_CAUGHT = 7

local function party_count() return memory.read_u8(PARTY_COUNT_ADDR) end
local function battle_outcome() return memory.read_u8(BATTLE_OUTCOME_ADDR) end
local function player_faints() return memory.read_u8(BATTLE_RESULTS_ADDR) end

local function mapid(cp) local g, n = G.map(cp); return g * 256 + n end

--- POLARITY (Codex review cx-378ce251): the `in_battle` predicate is gMain+1081 & 2 with
--- expect=0 (data/games/gen3_frlg/write_checkpoint.json firered.predicates.in_battle,
--- gen3_boot_check.lua:104-114 pred_ok compares (value&mask)==expect), so
--- G.pred_ok(cp,"in_battle") is TRUE when we are NOT in a battle. Wrapped once here (same shape
--- as lua/tests/gen3_rr_scripted_play.lua:74) so no leg touches the raw predicate directly.
local function in_battle(cp) return not G.pred_ok(cp, "in_battle") end

--- A-only mash, for use INSIDE a battle: G.mash pulses Start every 16 frames
--- (gen3_boot_check.lua:212-221), which opens the START menu if it ever fires on the field —
--- exactly what the in_battle polarity bug caused (Codex cx-378ce251). Same shape as
--- lua/tests/gen3_rr_scripted_play.lua:104-110.
local function mash_a(taps, stop)
    for _ = 1, taps do
        if stop and stop() then return true end
        G.tap("A", 3, 13)
    end
    return stop and stop() or false
end

local function int(x) return math.floor(x) end

-- VAR_MAP_SCENE_PALLET_TOWN_PROFESSOR_OAKS_LAB (pret include/constants/vars.h:137) = 0x4055.
-- SaveBlock1.vars[] lives at SB1+0x1000 (pret include/global.h:791), each entry a u16, so this
-- var's byte offset from SaveBlock1 is 0x1000 + (0x4055-0x4000)*2.
local SB1_VARS_OFFSET = 0x1000
local VAR_MAP_SCENE_PALLET_TOWN_PROFESSOR_OAKS_LAB = 0x4055
local LAB_SCENE_VAR_OFFSET = SB1_VARS_OFFSET + (VAR_MAP_SCENE_PALLET_TOWN_PROFESSOR_OAKS_LAB - 0x4000) * 2

--- The lab scene var, read through cp.pointers.gSaveBlock1Ptr the way G.map/G.pos do
--- (gen3_boot_check.lua:118-123): -1 while the pointer is not yet a sane EWRAM address.
local function lab_scene_var(cp)
    local ptr = assert(cp.pointers and cp.pointers.gSaveBlock1Ptr, "no gSaveBlock1Ptr")
    local sb1 = memory.read_u32_le(int(ptr.address))
    if sb1 < 0x02000000 or sb1 >= 0x02040000 then return -1 end
    return memory.read_u16_le(sb1 + LAB_SCENE_VAR_OFFSET)
end

-- ── PATHS: every direction list below, OFFLINE-BFS-computed ────────────────────────────────────
-- Tool: a Python BFS (scratchpad, not checked in) over data/layouts/<map>/map.bin: block u16,
-- collision=(word>>10)&3, blocked if nonzero; object_event tiles from data/maps/<map>/map.json
-- also blocked; 4-directional BFS, shortest path. Every entry names the map, start, end tile.
local PATHS = {
    -- PalletTown/map.json coord_events: OakTriggerLeft @ (12,1), var VAR_MAP_SCENE_PALLET_TOWN_OAK
    -- == 0 (true on a fresh save). Walking onto this TILE fires it (a coord_event, not a warp —
    -- no press-into needed). This is the FIRST entry into the lab, not the door: on a fresh
    -- save Oak is not in the lab and the starter balls are inert (PalletTown_ProfessorOaksLab/
    -- scripts.inc:1219-1223 "Those are Poke Balls") until this trigger's scripted sequence
    -- (data/maps/PalletTown/scripts.inc:181-217) leads the player in and warps them to
    -- (6,12) with VAR_MAP_SCENE_PALLET_TOWN_PROFESSOR_OAKS_LAB=1. Path avoids (13,1)/(13,2)
    -- (OakTriggerRight / SignLadyTrigger) entirely (checked cell-by-cell against the BFS output).
    town_start_to_oak_trigger = {
        map = "PalletTown", from = { 6, 9 }, to = { 12, 1 },
        dirs = { "Right","Right","Right","Right","Right","Up","Up","Up","Up","Up","Up","Up",
                 "Right","Up" },
    },
    -- Re-entry path for every LATER lab visit (parcel_deliver, route1_catch), once
    -- FLAG_HIDE_OAK_IN_PALLET_TOWN is set and the door works normally again.
    -- PalletTown/map.json warp_events[2] = (16,13) MAP_PALLET_TOWN_PROFESSOR_OAKS_LAB warp 0.
    -- Door tile (16,13) reads collision=1; the walkable approach is (16,14), one tile south.
    town_start_to_lab_door = {
        map = "PalletTown", from = { 6, 9 }, to = { 16, 14 },   -- (6,9): FRLG door exit walks one tile south of the door (PHYSICAL 2026-09-21)
        dirs = { "Down", "Right", "Right", "Right", "Right", "Down", "Down", "Down", "Down", "Right", "Right", "Right", "Right", "Right", "Right" },
    },
    -- PalletTown_ProfessorOaksLab/map.json warp_events[0] = (6,12), the lab's own landing tile
    -- (collision=0, walk-through). SquirtleBall object_event at (9,4) (collision=1, solid);
    -- (9,5) one tile south is the interact-facing approach. Used by LATER visits that enter
    -- via the door directly (the first visit's own scripted walk ends at (6,4), not (6,12) —
    -- see lab_oak_scene_end_to_ball below).
    lab_entrance_to_ball = {
        map = "PalletTown_ProfessorOaksLab", from = { 6, 12 }, to = { 9, 5 },
        dirs = { "Up","Up","Up","Up","Up","Up","Up","Right","Right","Right" },
    },
    -- ONE-TIME: the ChooseStarterScene's own scripted player movement
    -- (PalletTown_ProfessorOaksLab_Movement_PlayerEnter, scripts.inc:238-247: walk_up x8 from
    -- the (6,12) landing tile) parks the player at (6,4), not (6,12) — computed from the
    -- movement macro, the same "engine drives this walk" exception as mart_scene_end_to_exit.
    -- Verified at runtime by follow()'s start-tile check like every other path.
    lab_oak_scene_end_to_ball = {
        map = "PalletTown_ProfessorOaksLab", from = { 6, 4 }, to = { 9, 5 },
        dirs = { "Down","Right","Right","Right" },
    },
    -- coord_events RivalBattleTriggerLeft/Mid/Right @ y=8, x in {5,6,7}
    -- (PalletTown_ProfessorOaksLab/map.json).
    ball_to_rival_row = {
        map = "PalletTown_ProfessorOaksLab", from = { 9, 5 }, to = { 6, 8 },
        dirs = { "Down","Down","Left","Left","Down","Left" },
    },
    -- warp_events[0..2] = (5,12)/(6,12)/(7,12) -> PalletTown warp 2; walk-through, no press-in.
    rival_row_to_lab_exit = {
        map = "PalletTown_ProfessorOaksLab", from = { 6, 8 }, to = { 6, 12 },
        dirs = { "Down","Down","Down","Down" },
    },
    -- PROF_OAK object_event @ (6,3) (collision=1, solid); (6,4) is the approach.
    lab_entrance_to_oak = {
        map = "PalletTown_ProfessorOaksLab", from = { 6, 12 }, to = { 6, 4 },
        dirs = { "Up","Up","Up","Up","Up","Up","Up","Up" },
    },
    oak_to_lab_exit = {
        map = "PalletTown_ProfessorOaksLab", from = { 6, 4 }, to = { 6, 12 },
        dirs = { "Down","Down","Down","Down","Down","Down","Down","Down" },
    },
    -- PalletTown/map.json connections[0]: MAP_ROUTE1 direction=up offset=0 -> Route1's local x
    -- equals PalletTown's. Top rows (y=0,1) open only at x=10..13; the north-open column x=12
    -- lines up with Route1's own south grass gap at x=12,13 (verified against both grids).
    lab_exit_to_route1_edge = {
        map = "PalletTown", from = { 16, 14 }, to = { 12, 1 },
        dirs = { "Left","Left","Left","Left","Up","Up","Up","Up","Up","Up","Up","Up","Up","Up",
                 "Up","Up","Up" },
    },
    route1_edge_to_lab_door = {
        map = "PalletTown", from = { 12, 1 }, to = { 16, 14 },
        dirs = { "Down","Down","Down","Down","Down","Down","Down","Down","Down","Down","Down",
                 "Down","Down","Right","Right","Right","Right" },
    },
    -- Route1/map.json connections: down->PalletTown offset=0 (own x); up->ViridianCity offset=-12
    -- under the "this_x = other_x + offset" convention pret uses (verified empirically: crossing
    -- at Route1 x=12 lands ViridianCity x=24, which is open ground; x=12-12=0 there is a border
    -- wall). South wall (y=38,39) is open ONLY at x=12,13 (both tall-grass metatiles 10-13 in
    -- gTileset_General, data/tilesets/primary/general/metatile_attributes.bin low-byte 0x02 =
    -- MB_TALL_GRASS); grass at the entrance is unavoidable, not a choice.
    route1_south_to_grass_spot = {
        map = "Route1", from = { 12, 39 }, to = { 12, 37 }, dirs = { "Up","Up" },
    },
    route1_south_to_north_edge = {
        map = "Route1", from = { 12, 39 }, to = { 12, 1 },
        dirs = { "Up", "Up", "Up", "Up", "Up", "Up", "Up", "Left", "Left", "Left", "Left", "Up", "Up", "Up", "Up", "Up", "Right", "Right", "Right", "Right", "Up", "Up", "Up", "Up", "Up", "Up", "Left", "Left", "Up", "Up", "Up", "Up", "Right", "Right", "Right", "Right", "Right", "Right", "Up", "Up", "Up", "Up", "Up", "Up", "Up", "Up", "Up", "Up", "Up", "Up", "Up", "Up", "Up", "Left", "Left", "Left", "Up", "Left" },
    },
    route1_north_to_south_edge = {
        map = "Route1", from = { 12, 1 }, to = { 12, 39 },
        dirs = { "Down","Down","Down","Right","Right","Right","Right","Down","Down","Down","Down",
                 "Down","Down","Down","Down","Down","Down","Down","Down","Down","Down","Down",
                 "Left","Left","Left","Left","Left","Left","Down","Down","Down","Down","Down",
                 "Right","Right","Down","Down","Down","Down","Down","Down","Left","Left","Left",
                 "Left","Down","Down","Down","Down","Down","Right","Right","Right","Right","Down",
                 "Down","Down","Down" },
    },
    route1_grass_to_north_edge = {
        map = "Route1", from = { 12, 37 }, to = { 12, 1 },
        dirs = { "Up","Up","Up","Up","Up","Left","Left","Left","Left","Up","Up","Up","Up","Up",
                 "Right","Right","Right","Right","Up","Up","Up","Up","Up","Up","Left","Left","Up",
                 "Up","Up","Up","Right","Right","Right","Right","Right","Right","Up","Up","Up",
                 "Up","Up","Up","Up","Up","Up","Up","Up","Up","Up","Up","Up","Left","Left","Left",
                 "Up","Left" },
    },
    -- ViridianCity/map.json connections down->Route1 offset=12 ("this_x = other_x + offset"
    -- i.e. Route1_x = ViridianCity_x - 12); the crossing landing (24,39) was verified open
    -- ground on ViridianCity's own collision grid. Mart door (36,19) collision=1; approach
    -- (36,20) collision=0 (warp_events entries in data/maps/ViridianCity/map.json).
    route1_edge_to_mart_door = {
        map = "ViridianCity", from = { 24, 39 }, to = { 36, 20 },
        dirs = { "Up","Up","Up","Up","Up","Up","Up","Up","Left","Left","Up","Up","Up","Up","Up",
                 "Up","Up","Up","Up","Up","Up","Right","Right","Right","Right","Right","Right",
                 "Right","Right","Right","Right","Right","Right","Right","Right" },
    },
    mart_door_to_route1_edge = {
        map = "ViridianCity", from = { 36, 20 }, to = { 24, 39 },
        dirs = { "Down", "Down", "Down", "Down", "Down", "Down", "Down", "Down", "Down", "Left", "Left", "Left", "Left", "Left", "Left", "Left", "Left", "Left", "Left", "Left", "Left", "Left", "Left", "Down", "Down", "Down", "Down", "Down", "Down", "Down", "Down", "Down", "Down", "Right", "Right" },
    },
    -- PokeCenter door (26,26) in ViridianCity/map.json; collision=1, approach (26,27)=0.
    route1_edge_to_pokecenter_door = {
        map = "ViridianCity", from = { 24, 39 }, to = { 26, 27 },
        dirs = { "Up","Up","Up","Up","Up","Up","Up","Up","Left","Left","Up","Up","Up","Up",
                 "Right","Right","Right","Right" },
    },
    -- ViridianCity_Mart's own warp_events[1] = (4,7); the parcel scene's scripted player
    -- movement (ViridianCity_Mart_Movement_ApproachCounter: walk_up x4) ends at (4,3) facing
    -- left — computed from the movement macro in data/maps/ViridianCity_Mart/scripts.inc, not
    -- observed; that is the one non-BFS coordinate below (see the leg comment).
    mart_scene_end_to_exit = {
        map = "Mart", from = { 4, 3 }, to = { 4, 7 }, dirs = { "Down","Down","Down","Down" },
    },
    -- PokemonCenter_1F's own warp_events[1] = (7,8) (used entering from ViridianCity warp 1).
    -- PC counter metatile (MB_PC=0x83, pret include/constants/metatile_behaviors.h:94) found at
    -- gTileset_Building metatile ids 98/99 (data/tilesets/primary/building/metatile_attributes.bin
    -- low byte 0x83), placed at (11,1) in data/layouts/PokemonCenter_1F/map.bin; collision=1,
    -- approach (11,2)=0.
    pokecenter_entrance_to_pc = {
        map = "PokemonCenter_1F", from = { 7, 8 }, to = { 11, 2 },
        dirs = { "Up","Up","Up","Up","Right","Right","Right","Right","Up","Up" },
    },
}

-- Follow a precomputed PATHS entry: one step per direction, each step verified by G.pos; a step
-- that doesn't move the player is treated as a textbox/script owning the field and cleared with
-- A before the SAME step is retried (bounded) — same recovery gen3_fr_newgame_inputs.lua's
-- step() uses, applied to a pinned path instead of a guessed one.
local function follow(cp, path_name, label)
    local p = assert(PATHS[path_name], "no PATHS entry " .. tostring(path_name))
    local start_map = mapid(cp)
    -- A precomputed path is only valid from ITS start tile: refuse loudly instead of walking
    -- a wrong-offset route into collision (the first lane run stalled exactly that way).
    local sx, sy = G.pos(cp)
    if sx ~= p.from[1] or sy ~= p.from[2] then
        G.shot("stuck")
        G.finish(false, string.format("%s (%s): start tile (%d,%d) is not the path's from (%d,%d)",
                                      label, path_name, sx, sy, p.from[1], p.from[2]))
    end
    for _, dir in ipairs(p.dirs) do
        local x, y = G.pos(cp)
        local moved = false
        for attempt = 1, 6 do
            for _ = 1, 12 do joypad.set({ [dir] = true }); G.advance() end
            G.idle(4)
            local nx, ny = G.pos(cp)
            if nx ~= x or ny ~= y then moved = true; break end
            if mapid(cp) ~= start_map then moved = true; break end
            for _ = 1, 4 do G.tap("A", 3, 13) end
        end
        if not moved then
            G.shot("stuck")
            G.finish(false, string.format("%s (%s): step %s stalled at (%d,%d)",
                                          label, path_name, dir, G.pos(cp)))
        end
        if mapid(cp) ~= start_map then return end
    end
end

-- Press `dir` repeatedly into an arrow-warp door until the map changes (bounded).
local function enter_warp(cp, dir, budget)
    local from_map = mapid(cp)
    for _ = 1, (budget or 20) do
        if mapid(cp) ~= from_map then break end
        for _ = 1, 16 do joypad.set({ [dir] = true }); G.advance() end
        if mapid(cp) == from_map then for _ = 1, 2 do G.tap("A", 3, 13) end end
    end
    for _ = 1, 600 do
        if mapid(cp) ~= from_map and G.pred_ok(cp, "palette_fade_active") then G.idle(16); return true end
        G.advance()
    end
    return false
end

local function require_map_change(cp, from_map, label)
    for _ = 1, 900 do
        if mapid(cp) ~= from_map then G.idle(16); return end
        G.advance()
    end
    G.shot("stuck")
    G.finish(false, label .. ": map never changed from " .. from_map)
end

local PLAY_FROM = os.getenv("SLINK_GEN3_PLAY_FROM")
if PLAY_FROM == "" then PLAY_FROM = nil end

local LEGS = {}

-- ── leg: starter ─────────────────────────────────────────────────────────────────────────────
LEGS[#LEGS + 1] = {
    name = "starter",
    exercises = { "mon_given", "map_load" },
    source = {
        "data/maps/PalletTown/map.json (coord_events OakTriggerLeft @ 12,1)",
        "data/maps/PalletTown/scripts.inc:169-217 (OakTrigger: lockall, lead player to the lab, warp MAP_PALLET_TOWN_PROFESSOR_OAKS_LAB 6 12)",
        "data/maps/PalletTown_ProfessorOaksLab/scripts.inc:44-48,199-227 (OnFrame ChooseStarterScene: scripted Oak+player movement, ends VAR_MAP_SCENE_PALLET_TOWN_PROFESSOR_OAKS_LAB=2)",
        "data/maps/PalletTown_ProfessorOaksLab/map.json (object_events SquirtleBall @ 9,4; (9,5) one tile south is the only walkable approach — collision=1 at (9,4) itself, confirmed with the same PATHS/collision method as every door in this file)",
        "data/maps/PalletTown_ProfessorOaksLab/scripts.inc:1212-1223 (SquirtleBall: lock; faceplayer — the object turns to face the player, matching facing Up from (9,5) — only ConfirmStarterChoice-reachable once scene==2, else \"Those are Poke Balls\")",
        "data/maps/PalletTown_ProfessorOaksLab/scripts.inc:1092-1096 (ConfirmSquirtle: msgbox ..., MSGBOX_YESNO)",
        "src/script_menu.c:873 (ScriptMenu_YesNo -> DisplayYesNoMenuDefaultYes: every MSGBOX_YESNO in this file, including the nickname prompt, defaults to YES)",
        "data/maps/PalletTown_ProfessorOaksLab/scripts.inc:1115-1134 (ChoseStarter: givemon PLAYER_STARTER_SPECIES,5 at line 1122 fires before the nickname prompt at line 1129 -- Text_GiveNicknameToThisMon, MSGBOX_YESNO)",
        "src/script_menu.c:887-913 (Task_YesNoMenu_HandleInput: MENU_B_PRESSED is handled identically to selecting NO -- gSpecialVar_Result=FALSE -- so B declines the nickname without opening the naming screen)",
        "data/maps/PalletTown_ProfessorOaksLab/scripts.inc:1140-1180 (RivalPicksStarter -> RivalWalksToX -> RivalTakesStarter: trailing rival dialogue, all plain `message`/`msgbox` with no further MSGBOX_YESNO)",
    },
    run = function(cp)
        -- Walking onto (12,1) fires the coord_event; from here to landing in the lab at scene=2
        -- is ENTIRELY scripted (lockall): Oak enters, leads the player north through the door,
        -- an internal `warp` command lands them at (6,12) in the lab, and the lab's own
        -- ON_FRAME ChooseStarterScene fires immediately (scene==1) — more scripted dialogue and
        -- an applymovement walk that parks the player at (6,4). No joypad steering happens or
        -- would do anything during this; only A to clear message boxes.
        local town_map = mapid(cp)
        follow(cp, "town_start_to_oak_trigger", "starter")
        local reached_lab = false
        for _ = 1, 6000 do
            if mapid(cp) ~= town_map then reached_lab = true; break end
            G.tap("A", 2, 10)
        end
        if not reached_lab then
            G.shot("stuck")
            G.finish(false, "starter: Oak's intercept never warped the player into the lab")
        end
        G.phase("in-lab", string.format("map=%d at=(%d,%d)", mapid(cp), G.pos(cp)))
        -- GROUND TRUTH, not position/idle guessing (PHYSICAL runs 4-7: position (6,4) + script
        -- idle + field controls unlocked was NOT sufficient — Oak was still talking). scripts.inc
        -- (ChooseStarterScene) only reaches `setvar VAR_MAP_SCENE_PALLET_TOWN_PROFESSOR_OAKS_LAB,
        -- 2` at the very end, line 225, right before `releaseall`. A-only: this is entirely a
        -- scripted cutscene (lockall), so Start must never fire here (see the mash_a comment).
        local scene_done = false
        for _ = 1, 6000 do
            if lab_scene_var(cp) == 2 then scene_done = true; break end
            G.tap("A", 2, 10)
        end
        if not scene_done then
            G.shot("stuck")
            G.finish(false, string.format(
                "starter: lab scene var never reached 2 (last=%d) at (%d,%d)",
                lab_scene_var(cp), G.pos(cp)))
        end
        -- The var can read 2 a frame or two before `releaseall` actually restores control
        -- (PHYSICAL risk noted by the coordinator); debounce script idle + field controls
        -- unlocked held for 60 consecutive frames, no further input, before trusting it.
        local stable, settled = 0, false
        for _ = 1, 900 do
            if G.pred_ok(cp, "script_context_status") and G.pred_ok(cp, "field_controls_locked") then
                stable = stable + 1
                if stable >= 60 then settled = true; break end
            else
                stable = 0
            end
            G.advance()
        end
        if not settled then
            G.shot("stuck")
            G.finish(false, "starter: scene var==2 but idle+unlocked never held 60 frames")
        end
        G.phase("scene-done", "var=2, idle+unlocked held 60f")

        -- DIAGNOSTIC (run 8): the live player OBJECT coords vs SaveBlock1.pos, and a screenshot,
        -- because after the scripted scene the screen showed the player beside Oak while
        -- SaveBlock1.pos claimed the walk to (9,5) succeeded. gObjectEvents = 0x02036E38
        -- (pokefirered.sym:205), object 0 = player, currentCoords s16 x/y at +0x10/+0x12
        -- (include/global.fieldmap.h struct ObjectEvent), stored +7 (MAP_OFFSET).
        do
            local ox = memory.read_s16_le(0x02036E38 + 0x10) - 7
            local oy = memory.read_s16_le(0x02036E38 + 0x12) - 7
            local sx, sy = G.pos(cp)
            G.phase("pre-walk", string.format("obj0=(%d,%d) sb1=(%d,%d)", ox, oy, sx, sy))
            G.shot("prewalk")
        end
        follow(cp, "lab_oak_scene_end_to_ball", "starter")   -- asserts the real (6,4), not assumed
        do
            local ox = memory.read_s16_le(0x02036E38 + 0x10) - 7
            local oy = memory.read_s16_le(0x02036E38 + 0x12) - 7
            local sx, sy = G.pos(cp)
            G.phase("post-walk", string.format("obj0=(%d,%d) sb1=(%d,%d)", ox, oy, sx, sy))
            G.shot("postwalk")
        end
        do
            -- Face the ball and PROVE the facing: ObjectEvent.facingDirection is the low nibble
            -- at +0x18 (include/global.fieldmap.h: u8 movementDirection:4 / facingDirection:4);
            -- 1=down 2=up 3=left 4=right. Hold Up until it reads 2 (the ball object is solid,
            -- so Up can only turn, never step).
            local function facing() return memory.read_u8(0x02036E38 + 0x18) >> 4 end
            for _ = 1, 4 do
                if facing() == 2 then break end
                for _ = 1, 8 do joypad.set({ Up = true }); G.advance() end
                G.idle(8)
            end
            G.phase("facing", string.format("dir=%d (2=up)", facing()))
            G.shot("facing")
        end

        -- Phase 1: A only, checked each tap, until givemon actually lands (party_count 0->1).
        -- Every MSGBOX_YESNO up to and including "would you like Squirtle?" (ConfirmSquirtle,
        -- scripts.inc:1092-1096) defaults to YES (src/script_menu.c:873), so plain A-mashing is
        -- a pinned accept, not a guess -- and it can only ever accept the STARTER here, because
        -- the nickname prompt (the only OTHER yes/no reachable from this script) cannot appear
        -- before givemon fires (scripts.inc:1122 precedes 1129).
        local got = false
        for _ = 1, 40 do
            G.tap("A", 3, 20)
            if party_count() > 0 then got = true; break end
        end
        if not got then
            G.shot("stuck")
            G.finish(false, "starter: party_count() never left 0 after interacting with the ball")
        end
        G.phase("starter-got", "party=" .. party_count())

        -- Phase 2: the trailing "received {mon} from OAK!" message/fanfare, the nickname
        -- Yes/No (Text_GiveNicknameToThisMon, scripts.inc:1129), and the rival's own dialogue
        -- (scripts.inc:1140-1180) all run before script_context_status goes idle. A alone would
        -- risk landing on the nickname box's default YES and opening the naming screen this
        -- driver doesn't handle; B alone risks not dismissing a plain message (only A does).
        -- Alternating A then B on every tap is safe both ways: a plain `message`/`waitmessage`
        -- box only closes on A (B is a no-op there); the one Yes/No box left (nickname) treats
        -- B identically to NO (src/script_menu.c:901-905, MENU_B_PRESSED -> FALSE) without
        -- opening the keyboard -- so the exact frame the box appears doesn't need to be known.
        local idle = false
        for _ = 1, 40 do
            if G.pred_ok(cp, "script_context_status") then idle = true; break end
            G.tap("A", 3, 16)
            G.tap("B", 3, 16)
        end
        if not idle then
            G.shot("stuck")
            G.finish(false, "starter: trailing text/nickname-decline never went idle "
                         .. "(script_context_status)")
        end
        G.phase("starter-idle", "party=" .. party_count())
    end,
}

-- ── leg: rival_battle ────────────────────────────────────────────────────────────────────────
LEGS[#LEGS + 1] = {
    name = "rival_battle",
    exercises = { "battle_begin", "battle_end" },
    source = {
        "data/maps/PalletTown_ProfessorOaksLab/map.json (coord_events RivalBattleTrigger* @ y=8)",
        "data/maps/PalletTown_ProfessorOaksLab/scripts.inc:299-311 (RivalApproachForBattleSquirtle)",
    },
    run = function(cp)
        follow(cp, "ball_to_rival_row", "rival_battle")
        local entered = false
        for _ = 1, 1200 do
            if in_battle(cp) then entered = true; break end
            for _ = 1, 4 do G.tap("A", 3, 13) end
        end
        if not entered then
            G.shot("stuck")
            G.finish(false, "rival_battle: never entered battle after the y=8 trigger row")
        end
        G.phase("battle-begin")
        -- gActionSelectionCursor resets to 0 (USE_MOVE) each battle
        -- (src/battle_controller_player.c); A,A is a pinned FIGHT->move-slot-1 selection, not a
        -- guess. What the rival does in response is not controlled — RISK stated in the header.
        -- A-only (mash_a): G.mash's Start pulse must never fire while a battle is up.
        local ended = mash_a(315, function() return not in_battle(cp) end)
        if not ended then
            G.shot("stuck")
            G.finish(false, "rival_battle: in_battle never cleared within budget")
        end
        G.phase("battle-end")
    end,
}

-- ── leg: leave_lab_for_parcel ────────────────────────────────────────────────────────────────
LEGS[#LEGS + 1] = {
    name = "leave_lab_for_parcel",
    exercises = { "map_load" },
    source = { "data/maps/PalletTown_ProfessorOaksLab/map.json (warp_events -> PalletTown warp 2)" },
    run = function(cp)
        local lab_map = mapid(cp)
        follow(cp, "rival_row_to_lab_exit", "leave_lab_for_parcel")
        require_map_change(cp, lab_map, "leave_lab_for_parcel")
        G.phase("outside", string.format("map=%d at=(%d,%d)", mapid(cp), G.pos(cp)))
    end,
}

-- ── leg: parcel_fetch ────────────────────────────────────────────────────────────────────────
-- PalletTown -> Route1 -> ViridianCity -> the Mart. ViridianCity_Mart_EventScript_ParcelScene
-- (data/maps/ViridianCity_Mart/scripts.inc:16-32) is a MAP_SCRIPT_ON_FRAME script gated on
-- VAR_MAP_SCENE_VIRIDIAN_CITY_MART==0 — it fires automatically once the map loads, no player
-- action needed to trigger it, and it moves the PLAYER object itself via `applymovement`
-- (ViridianCity_Mart_Movement_ApproachCounter: walk_up x4). Verified by
-- `script_context_status` returning to idle (2) after being busy — a real predicate, not a
-- frame count.
LEGS[#LEGS + 1] = {
    name = "parcel_fetch",
    exercises = { "map_load" },
    source = {
        "data/maps/PalletTown/map.json (connections up -> Route1)",
        "data/maps/Route1/map.json (connections up -> ViridianCity)",
        "data/maps/ViridianCity/map.json (warp_events[4] -> ViridianCity_Mart)",
        "data/maps/ViridianCity_Mart/scripts.inc:16-32 (ParcelScene, ON_FRAME-triggered)",
    },
    run = function(cp)
        follow(cp, "lab_exit_to_route1_edge", "parcel_fetch")
        if not enter_warp(cp, "Up", 30) then G.finish(false, "parcel_fetch: PalletTown->Route1 crossing never fired") end
        follow(cp, "route1_south_to_north_edge", "parcel_fetch")
        if not enter_warp(cp, "Up", 30) then G.finish(false, "parcel_fetch: Route1->ViridianCity crossing never fired") end
        follow(cp, "route1_edge_to_mart_door", "parcel_fetch")
        if not enter_warp(cp, "Up", 30) then G.finish(false, "parcel_fetch: the mart door never fired a warp") end
        G.phase("in-mart", string.format("map=%d at=(%d,%d)", mapid(cp), G.pos(cp)))
        -- Let the ON_FRAME script run and clear its own message boxes with A; the scene owns
        -- player movement, this loop only advances dialogue.
        local settled = false
        for _ = 1, 3000 do
            if G.pred_ok(cp, "script_context_status") then settled = true; break end
            G.tap("A", 2, 10)
        end
        if not settled then
            G.shot("stuck")
            G.finish(false, "parcel_fetch: the mart's parcel scene never returned control")
        end
        G.phase("parcel-scene-done", string.format("at=(%d,%d)", G.pos(cp)))
    end,
}

-- ── leg: parcel_deliver ──────────────────────────────────────────────────────────────────────
LEGS[#LEGS + 1] = {
    name = "parcel_deliver",
    exercises = { "map_load" },
    source = {
        "data/maps/PalletTown_ProfessorOaksLab/scripts.inc:600-660 (DeliveredOaksParcel -> dex scene -> ReceivedFivePokeBalls)",
    },
    run = function(cp)
        -- mart_scene_end_to_exit's start (4,3) is the ApproachCounter movement's computed end
        -- tile (walk_up x4 from the (4,7) entrance), not a BFS/observed tile — the one path
        -- entry in this file that isn't independently source-BFS'd, because the engine (not the
        -- player) drove that walk. Verified at runtime by G.pos same as every other step.
        follow(cp, "mart_scene_end_to_exit", "parcel_deliver")
        if not enter_warp(cp, "Down", 30) then G.finish(false, "parcel_deliver: the mart exit never fired a warp") end
        follow(cp, "mart_door_to_route1_edge", "parcel_deliver")
        if not enter_warp(cp, "Down", 30) then G.finish(false, "parcel_deliver: ViridianCity->Route1 crossing never fired") end
        follow(cp, "route1_north_to_south_edge", "parcel_deliver")
        if not enter_warp(cp, "Down", 30) then G.finish(false, "parcel_deliver: Route1->PalletTown crossing never fired") end
        follow(cp, "route1_edge_to_lab_door", "parcel_deliver")
        if not enter_warp(cp, "Up", 30) then G.finish(false, "parcel_deliver: the lab door never fired a warp") end
        follow(cp, "lab_entrance_to_oak", "parcel_deliver")
        G.tap("Up", 2, 13)
        -- Talking to Oak with the parcel triggers the whole delivery + Pokedex + 5-balls
        -- cutscene (scripts.inc:600-660); long, almost entirely message boxes and NPC
        -- applymovement. Bounded mash, verified by the engine handing control back.
        local settled = false
        for _ = 1, 6000 do
            if G.pred_ok(cp, "callback2") and G.pred_ok(cp, "script_context_status") then
                settled = true; break
            end
            G.tap("A", 2, 10)
        end
        if not settled then
            G.shot("stuck")
            G.finish(false, "parcel_deliver: Oak's dex-scene never returned control")
        end
        G.phase("balls-received", "assumed from the scene completing (no bag read available)")
    end,
}

-- ── leg: route1_catch (capture_wild) ─────────────────────────────────────────────────────────
LEGS[#LEGS + 1] = {
    name = "route1_catch",
    exercises = { "capture_wild" },
    source = {
        "data/maps/Route1/map.json; data/layouts/Route1/map.bin metatiles 10-13 = MB_TALL_GRASS",
        "src/battle_controller_player.c:248-253 (Right toggles B_ACTION_USE_ITEM/BAG)",
        "src/battle_script_commands.c (BattleScript_SuccessBallThrow); include/constants/battle.h:82 (B_OUTCOME_CAUGHT=7)",
    },
    run = function(cp)
        local lab_map = mapid(cp)
        follow(cp, "oak_to_lab_exit", "route1_catch")
        require_map_change(cp, lab_map, "route1_catch")
        follow(cp, "lab_exit_to_route1_edge", "route1_catch")
        if not enter_warp(cp, "Up", 30) then G.finish(false, "route1_catch: PalletTown->Route1 crossing never fired") end
        follow(cp, "route1_south_to_grass_spot", "route1_catch")
        local caught = false
        for encounter = 1, 4 do
            local entered = false
            for _ = 1, 400 do
                if in_battle(cp) then entered = true; break end
                -- oscillate in the two-tile grass gap to keep triggering the per-step encounter
                -- check without leaving the grass patch (Route1/map.json; the corridor is
                -- exactly 2 tiles wide here)
                local dir = (G.spent % 2 == 0) and "Left" or "Right"
                for _ = 1, 12 do joypad.set({ [dir] = true }); G.advance() end
            end
            if not entered then
                G.shot("stuck")
                G.finish(false, "route1_catch: no wild encounter after " .. encounter .. " grass cycles")
            end
            -- RISK (see header): BAG is pinned (Right, A); reaching POKE BALL inside it is not.
            G.tap("Right", 3, 20)  -- FIGHT(0) -> BAG/USE_ITEM(1), pinned bit toggle
            G.tap("A", 3, 30)
            for _ = 1, 30 do G.tap("A", 3, 20) end   -- bag category/list/throw-confirm, mashed
            -- A-only (mash_a): G.mash's Start pulse must never fire while a battle is up.
            local resolved = mash_a(160, function() return not in_battle(cp) end)
            if resolved and battle_outcome() == B_OUTCOME_CAUGHT then
                caught = true
                break
            end
        end
        if not caught then
            G.shot("stuck")
            G.finish(false, string.format(
                "route1_catch: never reached B_OUTCOME_CAUGHT (last outcome=%d) after 4 encounters "
                .. "— the bag-menu mash (RISK, see header) is the likely culprit", battle_outcome()))
        end
        G.phase("caught", "outcome=" .. battle_outcome())
    end,
}

-- ── leg: route1_faint ────────────────────────────────────────────────────────────────────────
LEGS[#LEGS + 1] = {
    name = "route1_faint",
    exercises = { "faint" },
    source = {
        "data/maps/Route1/map.json (wild encounter table, same grass patch)",
        "lua/games/gen3_frlge.lua:vanilla.BATTLE_RESULTS_ADDR (gBattleResults.playerFaintCounter @ +0)",
    },
    run = function(cp)
        local before = player_faints()
        local fainted = false
        for encounter = 1, 20 do
            local entered = false
            for _ = 1, 400 do
                if in_battle(cp) then entered = true; break end
                local dir = (G.spent % 2 == 0) and "Left" or "Right"
                for _ = 1, 12 do joypad.set({ [dir] = true }); G.advance() end
            end
            if not entered then
                G.shot("stuck")
                G.finish(false, "route1_faint: no wild encounter after " .. encounter .. " grass cycles")
            end
            -- Keep attacking (RISK, see header) until this battle ends, then check the faint
            -- counter — a strong starter may just keep winning; bounded at 20 encounters.
            -- A-only (mash_a): G.mash's Start pulse must never fire while a battle is up.
            mash_a(160, function() return not in_battle(cp) end)
            if player_faints() > before then fainted = true; break end
        end
        if not fainted then
            G.shot("stuck")
            G.finish(false, "route1_faint: playerFaintCounter never advanced after 20 encounters "
                         .. "(RISK: the starter may simply keep winning — see header)")
        end
        G.phase("fainted", "playerFaintCounter=" .. player_faints())
    end,
}

-- ── leg: viridian_pc_deposit_withdraw ────────────────────────────────────────────────────────
LEGS[#LEGS + 1] = {
    name = "viridian_pc_deposit_withdraw",
    exercises = { "pc_move", "pc_deposit", "pc_withdraw" },
    source = {
        "data/maps/ViridianCity/map.json (warp_events[0] -> PokemonCenter_1F)",
        "include/constants/metatile_behaviors.h:94 (MB_PC); data/tilesets/primary/building/metatile_attributes.bin (ids 98/99); data/layouts/PokemonCenter_1F/map.bin (placed @ 11,1)",
        "src/pokemon_storage_system.c (storage menu)",
    },
    run = function(cp)
        follow(cp, "route1_grass_to_north_edge", "viridian_pc_deposit_withdraw")
        if not enter_warp(cp, "Up", 30) then G.finish(false, "viridian_pc: Route1->ViridianCity crossing never fired") end
        follow(cp, "route1_edge_to_pokecenter_door", "viridian_pc_deposit_withdraw")
        if not enter_warp(cp, "Up", 30) then G.finish(false, "viridian_pc: the PokeCenter door never fired a warp") end
        follow(cp, "pokecenter_entrance_to_pc", "viridian_pc_deposit_withdraw")
        G.tap("Up", 2, 13)
        local before = party_count()
        -- Storage menu navigation past "what do you want to do" is mashed (not pinned row-by-
        -- row); verified by party_count actually changing, never by the presses alone.
        local deposited = false
        for _ = 1, 60 do
            G.tap("A", 3, 20)
            if party_count() < before then deposited = true; break end
        end
        if not deposited then
            G.shot("stuck")
            G.finish(false, string.format("viridian_pc: party_count() never dropped from %d (deposit)", before))
        end
        G.phase("deposited", "party=" .. party_count())
        local after_deposit = party_count()
        local withdrawn = false
        for _ = 1, 60 do
            G.tap("A", 3, 20)
            if party_count() > after_deposit then withdrawn = true; break end
        end
        if not withdrawn then
            G.shot("stuck")
            G.finish(false, string.format("viridian_pc: party_count() never rose from %d (withdraw)", after_deposit))
        end
        G.phase("withdrawn", "party=" .. party_count())
        for _ = 1, 20 do
            if G.pred_ok(cp, "callback2") then break end
            G.tap("B", 3, 20)
        end
    end,
}

-- ── leg: save ────────────────────────────────────────────────────────────────────────────────
LEGS[#LEGS + 1] = {
    name = "save",
    exercises = { "save" },
    source = { "src/save.c:701 (TrySavingData); row search + flash sector counter witness (lua/tests/gen3_boot_check.lua save_via_menu), no guessed menu row" },
    run = function(cp)
        local domain = select(1, G.flash_domain())
        if not domain then G.finish(false, "save: no flash memory domain") end
        local ok, before, after = G.save_via_menu(cp, domain)
        if not ok then
            G.finish(false, string.format("save: never advanced (%d -> %d)", before, after))
        end
        pcall(client.saveram)
        G.phase("saved", string.format("counter %d -> %d", before, after))
    end,
}

-- ── leg: pc_release (OPEN) ───────────────────────────────────────────────────────────────────
LEGS[#LEGS + 1] = {
    name = "pc_release",
    exercises = { "pc_box_place", "pc_release_begin", "pc_release" },
    source = {
        "src/pokemon_storage_system.c (release flow)",
        "lua/games/gen3_frlge.lua:vanilla (no box-mon-count/species read pinned; species is inside the encrypted BoxPokemon substructure)",
    },
    open = true,
    open_reason = "release verification needs a PC-box read (species is encrypted; no decrypt-free box-count observable pinned for vanilla FRLG yet)",
    run = function(cp) G.phase("pc_release", "OPEN: " .. LEGS[#LEGS].open_reason) end,
}

-- ── leg: gift_mon (OPEN) ─────────────────────────────────────────────────────────────────────
LEGS[#LEGS + 1] = {
    name = "gift_mon",
    exercises = { "mon_given" },
    source = { "data/maps/Route4_PokemonCenter_1F/scripts.inc:49 (givemon SPECIES_MAGIKARP, 5)" },
    open = true,
    open_reason = "earliest non-starter givemon is Route 4's Magikarp, past Mt. Moon",
    run = function(cp) G.phase("gift_mon", "OPEN: earliest is Route 4 PokeCenter, past Mt. Moon") end,
}

-- ── leg: npc_trade (OPEN) ────────────────────────────────────────────────────────────────────
LEGS[#LEGS + 1] = {
    name = "npc_trade",
    exercises = { "trade_done", "trade_begin", "trade_evolve_species_store" },
    source = {
        "data/maps/CeruleanCity_House3/scripts.inc (trade NPC)",
        "src/data/ingame_trades.h (INGAME_TRADE_MR_MIME, requestedSpecies SPECIES_ABRA)",
    },
    open = true,
    open_reason = "earliest trade is Cerulean's Mr. Mime for an Abra, needing Route 24",
    run = function(cp) G.phase("npc_trade", "OPEN: earliest is Cerulean Mr. Mime, needs Route 24 Abra") end,
}

-- ── leg: evolution (OPEN) ────────────────────────────────────────────────────────────────────
LEGS[#LEGS + 1] = {
    name = "evolution",
    exercises = { "evolve_species_store" },
    source = { "src/evolution_scene.c (level-up evolution path)" },
    open = true,
    open_reason = "earliest is the starter's own level-up (Squirtle Lv.16); needs many more battles",
    run = function(cp) G.phase("evolution", "OPEN: earliest is a starter level-up, needs battle grinding") end,
}

-- ── run ──────────────────────────────────────────────────────────────────────────────────────

local function run()
    G.open("gen3_scripted_play")
    pcall(client.speedmode, 6399)
    G.budget = 900000
    local cp, title = G.checkpoint()
    G.phase("start", "title=" .. tostring(title))

    -- The fixture's battery is seeded but the field pointer is not sane at cold boot until the
    -- title screen -> CONTINUE has run (gen3_boot_check.lua run():300-320); a leg cannot read
    -- G.pos/G.map before this.
    if not G.boot_to_field(cp, 9000) then
        G.shot("stuck")
        local cb2 = G.pred(cp, "callback2")
        G.finish(false, string.format("boot: never reached the field (callback2=%08X)", cb2))
    end

    -- P3 shadow observer beside this driver when SLINK_SHADOW is set (same block shape as
    -- lua/tests/duo/duo_main.lua): read-only, logs to patch/build/gen3_scripted_play.shadow.log.
    if os.getenv("SLINK_SHADOW") then
        local okshd, shd = pcall(dofile, WT .. "/lua/gen3/shadow_run.lua")
        if okshd and shd then
            local okst, st = pcall(shd.start, { duo = {
                result = WT .. "/patch/build/gen3_scripted_play_result.txt", player = "a" } })
            if okst and st then
                G.phase("shadow", "observer started admitted_by=" .. tostring(st.admitted_by))
                event.onframeend(function() pcall(st.poll) end, "SLink-gen3-shadow-poll")
            else
                G.phase("shadow", "observer start failed: " .. tostring(st))
            end
        else
            G.phase("shadow", "shadow_run dofile failed: " .. tostring(shd))
        end
    end

    local from_idx = 1
    if PLAY_FROM then
        for i, leg in ipairs(LEGS) do
            if leg.name == PLAY_FROM then from_idx = i; break end
        end
        G.phase("resume", "from=" .. PLAY_FROM .. " (assumes that leg's save state is already loaded)")
    end

    local reached = {}
    for i = from_idx, #LEGS do
        local leg = LEGS[i]
        if leg.open then
            G.phase("skip-open", leg.name .. ": " .. tostring(leg.open_reason))
        else
            G.phase("leg-start", leg.name)
            leg.run(cp)
            G.phase("leg-done", leg.name)
        end
        reached[#reached + 1] = leg.name
    end

    G.finish(true, "reached: " .. table.concat(reached, ","))
end

if (debug.getinfo(1, "S").source or "") == "main" then run() end

return {
    LEGS = LEGS, PATHS = PATHS, follow = follow,
    -- test hooks (Codex review cx-378ce251): the in_battle polarity wrapper and the lab scene
    -- var address arithmetic, both independently checkable without an emulator.
    in_battle = in_battle,
    LAB_SCENE_VAR_OFFSET = LAB_SCENE_VAR_OFFSET,
}
