-- gen3_rr_battle_fixture.lua — build tests/fixtures/gen3/rr_battle.sav (card G4-LANE-1).
--
-- The Radical Red analogue of firered_party_battle.sav: the player standing on Route 1's grass
-- origin (12,37), the tile every Gen 3 duo scenario's grass hunt starts from
-- (lua/tests/gen3_scripted_play.lua GRASS_ORIGIN / GRASS_LOOP). SCRIPTED NORMAL INPUTS ONLY:
-- cold boot -> CONTINUE from rr_town.sav, walk, flee any wild battle with RUN, save in-game.
-- No memory write, no savestate, no save editing anywhere in this file.
--
-- GEOMETRY FROM THE RR ROM, NOT A SCREENSHOT. rr_town.sav stands on map 3.19 at (7,33)
-- (SaveBlock1 pos; its boot-check receipt reports map=(3,19)). Parsed from patch/build/
-- slink_RR.gba itself (tools/gba_map.py; RR's code still loads gMapGroups 0x083526A8 from the
-- single literal pool at 0x0805524C, the same word FR US 1.0 has):
--
--   python tools/gba_map.py patch/build/slink_RR.gba --map 3.19 --bfs 7,33 12,37 --find-behaviour 0x02
--   -> map 3.19: 24x40, 0 warps, 2 objects, 0 coords, 1 bg, 2 connections
--      bfs (7, 33) -> (12, 37): Down Down Right Right Right Right Right Down Down
--      behaviour 0x02 (MB_TALL_GRASS) includes (7,33) (12,37) (13,37) (12,38) (13,38)
--
-- RR's map 3.19 parses byte-identical to FR US 1.0's (collision, behaviours, connections), so
-- the FR grass square the duo scenarios use exists unchanged on RR.
--
-- FLEE, NEVER FIGHT. RR's action menu is FRLG's 2x2 grid (FIGHT BAG / POKeMON RUN; the pinned
-- battle-bag sequence in gen3_rr_scripted_play.lua starts "Right, A" = BAG). pret
-- HandleInputChooseAction moves Right only from an even cursor and Down only from cursor < 2,
-- so Right, Down lands on RUN (3) from ANY cursor; no cursor address is assumed. The action
-- menu is recognised by gBattlerControllerFuncs[0] (0x03004FE0) holding HandleInputChooseAction
-- (0x0802E439, gen3_rr_scripted_play.lua) or CFRU's detour 0x090A9EA1
-- (docs/gen3/research/rr_battle_tuple_2026-09-23.md §1). Outcome is logged, never assumed.
--
-- Environment: SLINK_ROOT, SLINK_GEN3_CHECKPOINT (data/games/gen3_rr/write_checkpoint.json),
-- SLINK_GEN3_TITLE=radical_red, all set by tools/gen3_fixtures.py `_launch(..., rr=True)`.
-- The caller seeds the per-run SaveRAM directory with rr_town.sav (like boot-check).

local WT = SLINK_ROOT or os.getenv("SLINK_ROOT")
assert(WT, "SLINK_ROOT unset — launch via tools/gen3_fixtures.py _launch")
local G = dofile(WT .. "/lua/tests/gen3_boot_check.lua")
local PL = dofile(WT .. "/lua/tests/playlib.lua")
local JSON = dofile(WT .. "/lua/json_codec.lua")
local Reads = dofile(WT .. "/lua/gen3/reads.lua")

local pf = assert(io.open(WT .. "/data/games/gen3_rr/profile.json", "rb"))
local profile = assert(JSON.decode(pf:read("a"))).titles.radical_red
pf:close()
local reader = Reads.new(profile, {
    read_u8 = memory.read_u8, read_u32 = memory.read_u32_le,
    read_bytes = function(addr, n)
        local t = {}
        for i = 1, n do t[i] = memory.read_u8(addr + i - 1) end
        return t
    end,
})

local START = { map = 3 * 256 + 19, x = 7, y = 33 }      -- rr_town.sav's saved tile
local TARGET = { group = 3, num = 19, x = 12, y = 37 }    -- GRASS_ORIGIN
local PATHS = {
    rr_town_to_grass_origin = {
        map = "Route1 (group 3, map 19)", from = { 7, 33 }, to = { 12, 37 },
        dirs = { "Down", "Down", "Right", "Right", "Right", "Right", "Right", "Down", "Down" },
    },

    -- ── card G5-RR-FIXTURE-DRIVER: grass -> Mart -> Oak's Lab -> grass ─────────────────────
    -- Every direction list below is `tools/gba_map.py`'s own BFS over the clean RR ROM
    -- (E:/Google Drive/SLink/Pokemon - Radical Red.gba, md5 8529f3a45d32bce4da637976fcf269d4),
    -- re-run and cited in docs/gen3/research/rr_fixture_route_2026-09-24.md. PROVEN geometry,
    -- not a guess: `python tools/gba_map.py <rom> --map G.N --bfs "x,y" "x,y"`.
    route1_grass_to_north_edge = {
        map = "Route1 (3.19)", from = { 12, 37 }, to = { 12, 0 },
        dirs = { "Up", "Up", "Up", "Up", "Up", "Left", "Left", "Left", "Left", "Up", "Up", "Up",
                 "Up", "Up", "Right", "Right", "Right", "Right", "Up", "Up", "Up", "Up", "Up",
                 "Up", "Left", "Left", "Up", "Up", "Up", "Up", "Right", "Right", "Right", "Right",
                 "Right", "Right", "Up", "Up", "Up", "Up", "Up", "Up", "Up", "Up", "Up", "Up",
                 "Up", "Up", "Up", "Up", "Up", "Left", "Left", "Left", "Up", "Up", "Left" },
    },
    viridian_arrival_to_mart_door_south = {
        map = "ViridianCity (3.1)", from = { 24, 39 }, to = { 36, 20 },
        dirs = { "Up", "Up", "Up", "Up", "Up", "Up", "Up", "Up", "Left", "Left", "Up", "Up", "Up",
                 "Up", "Up", "Up", "Up", "Up", "Up", "Up", "Up", "Right", "Right", "Right",
                 "Right", "Right", "Right", "Right", "Right", "Right", "Right", "Right", "Right",
                 "Right", "Right" },
    },
    viridian_mart_door_south_to_south_edge = {
        map = "ViridianCity (3.1)", from = { 36, 20 }, to = { 24, 39 },
        dirs = { "Down", "Down", "Down", "Down", "Down", "Down", "Down", "Down", "Down",
                 "Left", "Left", "Left", "Left", "Left", "Left", "Left", "Left", "Left",
                 "Left", "Left", "Left", "Left", "Left", "Down", "Down", "Down", "Down",
                 "Down", "Down", "Down", "Down", "Down", "Down", "Right", "Right" },
    },
    route1_north_edge_to_south_edge = {
        map = "Route1 (3.19)", from = { 12, 0 }, to = { 12, 39 },
        dirs = { "Down", "Down", "Down", "Down", "Right", "Right", "Right", "Right", "Down",
                 "Down", "Down", "Down", "Down", "Down", "Down", "Down", "Down", "Down",
                 "Down", "Down", "Down", "Down", "Down", "Left", "Left", "Left", "Left",
                 "Left", "Left", "Down", "Down", "Down", "Down", "Down", "Right", "Right",
                 "Down", "Down", "Down", "Down", "Down", "Down", "Left", "Left", "Left",
                 "Left", "Down", "Down", "Down", "Down", "Down", "Right", "Right", "Right",
                 "Right", "Down", "Down", "Down", "Down" },
    },
    pallet_north_edge_to_lab_door_south = {
        map = "PalletTown (3.0)", from = { 12, 0 }, to = { 16, 14 },
        dirs = { "Down", "Down", "Down", "Down", "Down", "Down", "Down", "Down", "Down", "Down",
                 "Down", "Down", "Down", "Down", "Right", "Right", "Right", "Right" },
    },
    pallet_lab_door_south_to_north_edge = {
        map = "PalletTown (3.0)", from = { 16, 14 }, to = { 12, 0 },
        dirs = { "Left", "Left", "Left", "Left", "Up", "Up", "Up", "Up", "Up", "Up", "Up", "Up",
                 "Up", "Up", "Up", "Up", "Up", "Up" },
    },
    route1_south_edge_to_grass_origin = {
        map = "Route1 (3.19)", from = { 12, 39 }, to = { 12, 37 },
        dirs = { "Up", "Up" },
    },
    -- OaksLab (4.3) interior: entering from Pallet's door (16,13) via its warp_id 0 lands
    -- exactly at the lab's own first warp-event coordinate (6,12) -- an indoor arrival is the
    -- destination map's own stated coordinate, not a connection-offset guess. Prof. Oak
    -- (OBJ_EVENT_GFX_PROF_OAK, local_id 4, x=6 y=3 elevation=3 movement_type=FACE_DOWN=8) blocks
    -- (6,3); walking to (6,4) and pressing Up bumps into him, which is how a normal-collision
    -- object event's script fires in this engine (no separate menu interact needed).
    oakslab_entrance_to_oak = {
        map = "PalletTown_ProfessorOaksLab (4.3)", from = { 6, 12 }, to = { 6, 4 },
        dirs = { "Up", "Up", "Up", "Up", "Up", "Up", "Up", "Up" },
    },
    oakslab_oak_to_entrance = {
        map = "PalletTown_ProfessorOaksLab (4.3)", from = { 6, 4 }, to = { 6, 12 },
        dirs = { "Down", "Down", "Down", "Down", "Down", "Down", "Down", "Down" },
    },
}

local CTRL_ADDR = 0x03004FE0
local ACTION_MENU = { [0x0802E439] = true, [0x090A9EA1] = true }
local BATTLE_OUTCOME_ADDR = 0x02023E8A   -- radical_red gBattleOutcome (gen3_rr_scripted_play.lua)

local H, play
local function action_menu_up() return ACTION_MENU[memory.read_u32_le(CTRL_ADDR)] == true end

--- RUN until the battle is over. Text is advanced with B (a no-op at a singles action menu).
local function flee(cp, budget)
    local runs = 0
    for _ = 1, (budget or 6000) do
        if not H.in_battle(cp) then break end
        if action_menu_up() then
            runs = runs + 1
            if runs > 12 then return false end
            G.phase("flee", "run attempt " .. runs)
            G.tap("Right", 3, 20); G.tap("Down", 3, 20); G.tap("A", 3, 20)
        else
            joypad.set((G.spent % 16 == 0) and { B = true } or {})
            G.advance()
        end
    end
    if H.in_battle(cp) then return false end
    G.phase("fled", string.format("outcome=%d runs=%d", memory.read_u8(BATTLE_OUTCOME_ADDR), runs))
    return play.wait_scene_settled(cp, 1800)
end

H = {
    advance = G.advance, idle = G.idle, tap = G.tap, pos = G.pos,
    phase = G.phase, finish = G.finish, shot = G.shot, open = G.open, checkpoint = G.checkpoint,
    press = function(buttons) joypad.set(buttons); G.advance() end,
    map = function(cp)
        local g, n = G.map(cp)
        if g < 0 or n < 0 then return nil end
        return g * 256 + n
    end,
    in_battle = function(cp) return not G.pred_ok(cp, "in_battle") end,   -- expect=0 mask
    on_field = function(cp) return G.pred_ok(cp, "in_battle") and G.pred_ok(cp, "callback2") end,
    scene_quiet = function(cp)
        return G.pred_ok(cp, "script_context_status") and G.pred_ok(cp, "field_controls_locked")
    end,
}
play = PL.bind(H, {
    paths = PATHS,
    battle = flee,
    clear_dialogue = function() for _ = 1, 4 do G.tap("A", 3, 13) end end,
    advance_scene = function() G.tap("A", 2, 10) end,
    menu_back = function(_, gap) G.tap("B", 3, gap or 20) end,
})

-- ── card G5-RR-FIXTURE-DRIVER: parcel/lab/catch constants and RAM witnesses ─────────────────
-- Every id below is PROVEN in docs/gen3/research/rr_fixture_route_2026-09-24.md by decoding
-- RR's own compiled map/NPC scripts (Viridian Mart's ON_FRAME table and clerk talk script, and
-- Oak's talk script), never assumed from vanilla FireRed.
local VARS_START = 0x4000
local VAR_MART = 0x4057                -- VAR_MAP_SCENE_VIRIDIAN_CITY_MART: 0 before any Mart
                                        -- visit, 1 after the auto-parcel scene, 2 after delivery
local FLAG_SYS_POKEDEX_GET = 0x829
local ITEM_POKE_BALL = 4
local BALL_POCKET_ADDR = assert(profile.ram.BALL_POCKET_ADDR,
    "profile has no ram.BALL_POCKET_ADDR")
local B_OUTCOME_CAUGHT = profile.derived.OUTCOME_CAUGHT or 7   -- pret battle.h:82

-- SaveBlock1.flags/.vars, read live via the SAME gSaveBlock1Ptr dereference reads.lua's own
-- read_badges()/read_party() use (reader.read_sb1(), profile.derived.SB1_FLAGS_OFFSET /
-- SB1_VARS_OFFSET) -- no address here is new, only the generic bit/word indexing on top of it.
local function read_var(var_id)
    local sb1, why = reader.read_sb1()
    if not sb1 then return nil, why end
    local off = profile.derived.SB1_VARS_OFFSET
    return memory.read_u16_le(sb1 + off + (var_id - VARS_START) * 2)
end
local function read_flag(flag_id)
    local sb1, why = reader.read_sb1()
    if not sb1 then return nil, why end
    local off = profile.derived.SB1_FLAGS_OFFSET
    local byte_i, bit_i = flag_id // 8, flag_id % 8
    return (memory.read_u8(sb1 + off + byte_i) >> bit_i) & 1
end
-- (itemId, quantity) of RR's EWRAM ball-pocket slot 0 -- the same read
-- lua/tests/gen3_rr_scripted_play.lua's proven `wild_catch` leg uses (ball_slot0), safe here
-- because this run's own pocket is empty until Oak's Lab writes it and nothing else touches it.
local function ball_slot0()
    return memory.read_u16_le(BALL_POCKET_ADDR), memory.read_u16_le(BALL_POCKET_ADDR + 2)
end

--- Step onto/off the grass tile in place (Up/Down oscillation) until a wild battle starts.
--- Ported from gen3_rr_scripted_play.lua's `pace`: standing still never rolls an encounter,
--- only a step onto tall grass does, and (12,37)/(12,38) are both MB_TALL_GRASS (this file's own
--- header, and docs/gen3/research/rr_fixture_route_2026-09-24.md).
local function pace_for_encounter(cp, frames)
    for i = 1, (frames or 4000) do
        if H.in_battle(cp) then joypad.set({}); return true end
        local phase = i % 64
        if phase < 28 then joypad.set({ Up = true })
        elseif phase < 32 then joypad.set({})
        elseif phase < 60 then joypad.set({ Down = true })
        else joypad.set({}) end
        G.advance()
    end
    joypad.set({})
    return H.in_battle(cp)
end

--- Throw Poke Balls until caught or the pocket is exhausted (bounded at 5, matching the
--- precedent this is ported from). THE PINNED SEQUENCE AND ITS TIMING ARE NOT THIS CARD'S: both
--- come verbatim from lua/tests/gen3_rr_scripted_play.lua's `wild_catch` leg (card gen3-P3-C3,
--- physically thrown 2026-09-21, docs/gen3/probes/census_rr_faint_v3b_catch_2026-09-21.txt) --
--- RR's battle bag needs ~90 frames to open and ~20 more per pocket-tab switch, so a flat
--- cadence eats the two pocket-switch presses during the fade and never reaches Poke Balls.
--- That file is read-only from here (W3 owns it); this is a citation, not a copy of authority.
local function throw_pokeballs(cp, label)
    local throws = 0
    for _ = 1, 5 do
        if not H.in_battle(cp) then break end
        local menu = false
        for _ = 1, 300 do
            if action_menu_up() then menu = true; break end
            if not H.in_battle(cp) then break end
            G.tap("A", 3, 13)
        end
        if not H.in_battle(cp) then break end
        if not menu then
            G.shot("stuck")
            G.finish(false, string.format(
                "%s: the action menu never appeared (throw %d)", label, throws + 1))
            return
        end
        throws = throws + 1
        local _, qty_before = ball_slot0()
        G.tap("Right", 3, 13); G.idle(16)    -- action menu: FIGHT -> BAG
        G.tap("A", 3, 13);     G.idle(90)    -- open the BAG (the slow one)
        G.tap("Right", 3, 13); G.idle(20)    -- pocket: Items -> Key Items
        G.tap("Right", 3, 13); G.idle(20)    -- pocket: Key Items -> Poke Balls
        G.tap("A", 3, 13);     G.idle(30)    -- select the Poke Ball
        G.tap("A", 3, 13)                    -- use it
        local thrown = false
        for _ = 1, 300 do
            local _, q = ball_slot0()
            if q < qty_before then thrown = true; break end
            G.advance()
        end
        if not thrown then
            G.shot("stuck")
            G.finish(false, string.format(
                "%s: ball not thrown on throw %d — the pocket still holds %d, so the pinned bag "
                .. "sequence never reached USE", label, throws, qty_before))
            return
        end
        for _ = 1, 1200 do
            if memory.read_u8(BATTLE_OUTCOME_ADDR) ~= 0 or action_menu_up() then break end
            G.tap("A", 3, 13)
        end
        if memory.read_u8(BATTLE_OUTCOME_ADDR) == B_OUTCOME_CAUGHT then
            G.phase("throw-caught", string.format("%s: throw %d caught it", label, throws))
            return true
        end
        G.phase("throw-missed", string.format("%s: throw %d, outcome=%d", label, throws,
                                              memory.read_u8(BATTLE_OUTCOME_ADDR)))
    end
    return memory.read_u8(BATTLE_OUTCOME_ADDR) == B_OUTCOME_CAUGHT
end

local function party_line()
    local mons, why = reader.read_party()
    if not mons then return nil, why end
    local rows, healed = {}, true
    for i, m in ipairs(mons) do
        rows[i] = string.format("[%d] species=%d level=%d hp=%d/%d", i, m.species, m.level,
                                m.hp, m.max_hp)
        if m.hp < m.max_hp then healed = false end
    end
    return table.concat(rows, " "), healed, #mons
end

local function at_target(cp)
    local g, n = G.map(cp)
    local x, y = G.pos(cp)
    return g == TARGET.group and n == TARGET.num and x == TARGET.x and y == TARGET.y
end

local function run()
    G.open("gen3_rr_battle_fixture")   -- patch/build/gen3_rr_battle_fixture_result.txt
    pcall(client.speedmode, 6399)
    G.budget = 200000
    local cp, title = G.checkpoint()
    G.phase("start", "title=" .. tostring(title))
    if title ~= "radical_red" then G.finish(false, "title must be radical_red"); return end

    local domain, seen = G.flash_domain()
    if not domain then G.finish(false, "no flash domain; domains: " .. tostring(seen)); return end
    local seeded = G.save_counter(domain)
    if seeded < 0 then G.finish(false, "battery erased at boot: seed not found"); return end
    G.phase("seeded", "counter=" .. seeded)
    if not G.boot_to_field(cp, 9000) then
        G.shot("stuck"); G.finish(false, "never reached the field"); return
    end

    local x, y = G.pos(cp)
    if H.map(cp) ~= START.map or x ~= START.x or y ~= START.y then
        G.finish(false, string.format("not on rr_town's tile: map=%s at=(%d,%d)",
                                      tostring(H.map(cp)), x, y))
        return
    end
    local line, _, n = party_line()
    if not line or n < 1 then G.finish(false, "party unreadable or empty"); return end
    G.phase("party", line)

    play.follow(cp, "rr_town_to_grass_origin", "rr_battle_fixture")   -- finishes on failure
    if not play.wait_at(cp, TARGET.x, TARGET.y, 120) or not at_target(cp) then
        G.shot("stuck"); G.finish(false, "not at the grass origin: " .. play.where(cp)); return
    end
    G.phase("grass-origin", play.where(cp))

    local ok, before, after, why = G.save_via_menu(cp, domain)
    if not ok then
        G.finish(false, string.format("in-game save failed (%d -> %d): %s", before, after,
                                      tostring(why)))
        return
    end
    if not play.wait_at(cp, TARGET.x, TARGET.y, 120) or not at_target(cp) then
        G.shot("stuck"); G.finish(false, "moved during the save: " .. play.where(cp)); return
    end
    local final, healed = party_line()
    G.idle(60)
    G.finish(true, string.format("counter %d -> %d at %s healed=%s party=%s", before, after,
                                 play.where(cp), tostring(healed), tostring(final)))
end

-- ── card G5-RR-FIXTURE-DRIVER: rr_battle.sav -> Mart -> Oak's Lab -> grass -> catch -> save ──
-- Produces tests/fixtures/gen3/rr_battle2.sav (+ derive-b's rr_battle2_b.sav), NEVER rr_battle*
-- (W3 owns that pair). Seeded from rr_battle.sav itself -- already standing at the grass origin
-- with a 1-mon party and an empty ball pocket -- so this leg is that fixture's own story
-- continued forward, not a second cold walk from rr_town.sav.
--
-- Crosses the map connections/doors with play.enter_warp (map-id-verified, field-settle-
-- verified) between every play.follow leg in PATHS above. Every gate this leg depends on is a
-- RAM read, never a frame count: VAR_MART (0x4057) and FLAG_SYS_POKEDEX_GET (0x829) via
-- gSaveBlock1Ptr (reader.read_sb1(), the same live pointer reads.lua's read_badges()/
-- read_party() already dereference), and the ball pocket via profile.ram.BALL_POCKET_ADDR --
-- see docs/gen3/research/rr_fixture_route_2026-09-24.md for why this route exists and how each
-- id was PROVEN against RR's own compiled scripts (not vanilla FireRed's).
local function run_route2()
    G.open("gen3_rr_battle_fixture_route2")  -- patch/build/gen3_rr_battle_fixture_route2_result.txt
    pcall(client.speedmode, 6399)
    G.budget = 400000
    local cp, title = G.checkpoint()
    G.phase("start", "title=" .. tostring(title))
    if title ~= "radical_red" then G.finish(false, "title must be radical_red"); return end

    local domain, seen = G.flash_domain()
    if not domain then G.finish(false, "no flash domain; domains: " .. tostring(seen)); return end
    local seeded = G.save_counter(domain)
    if seeded < 0 then G.finish(false, "battery erased at boot: seed not found"); return end
    G.phase("seeded", "counter=" .. seeded)
    if not G.boot_to_field(cp, 9000) then
        G.shot("stuck"); G.finish(false, "never reached the field"); return
    end

    -- THE PRECONDITION IS THE FIXTURE. This leg is only meaningful continuing rr_battle.sav's
    -- own saved state: grass origin, one mon, an empty ball pocket, VAR_MART unset. A run seeded
    -- from anything else fails here with a clear reason rather than wandering a route pinned to
    -- a state it never reached.
    if not at_target(cp) then
        G.finish(false, "not at the grass origin (must be seeded from rr_battle.sav): "
                     .. play.where(cp))
        return
    end
    local line, _, n_before = party_line()
    if not line or n_before ~= 1 then
        G.finish(false, "party is not the expected 1 mon (must be seeded from rr_battle.sav): "
                     .. tostring(line))
        return
    end
    local mart_var_before, why = read_var(VAR_MART)
    if mart_var_before == nil then G.finish(false, "VAR_MART unreadable: " .. tostring(why)); return end
    if mart_var_before ~= 0 then
        G.finish(false, string.format(
            "VAR_MART reads %d, not 0 — this save has already visited the Mart, so the parcel "
            .. "route this leg drives no longer applies", mart_var_before))
        return
    end
    local balls_before = select(2, ball_slot0())
    if balls_before ~= 0 then
        G.finish(false, string.format(
            "the ball pocket already holds %d — must be seeded from rr_battle.sav's empty "
            .. "pocket", balls_before))
        return
    end
    G.phase("party", line)

    -- ── leg: grass origin -> Viridian Mart (auto-receives Oak's Parcel, no shopping) ────────
    play.follow(cp, "route1_grass_to_north_edge", "route2")
    local ok1, why1 = play.enter_warp(cp, "Up", 30)
    if not ok1 then G.shot("stuck"); G.finish(false, "route2 Route1->Viridian: " .. tostring(why1)); return end
    if H.map(cp) ~= 3 * 256 + 1 then
        G.shot("stuck"); G.finish(false, "route2: not on Viridian City after the crossing: " .. play.where(cp)); return
    end
    play.follow(cp, "viridian_arrival_to_mart_door_south", "route2")
    local ok2, why2 = play.enter_warp(cp, "Up", 30)
    if not ok2 then G.shot("stuck"); G.finish(false, "route2 Viridian->Mart: " .. tostring(why2)); return end
    if H.map(cp) ~= 5 * 256 + 3 then
        G.shot("stuck"); G.finish(false, "route2: not inside the Mart after the crossing: " .. play.where(cp)); return
    end
    G.phase("mart-entered", play.where(cp))

    -- The parcel scene is an automatic MAP_SCRIPT_ON_FRAME_TABLE entry (fires the instant the
    -- map loads, no interaction needed) -- confirmed this card by decoding it from the ROM.
    if not play.wait_scene_settled(cp, 3000) then
        G.shot("stuck"); G.finish(false, "route2: the Mart parcel scene never settled"); return
    end
    local mart_var_after, why3 = read_var(VAR_MART)
    if mart_var_after ~= 1 then
        G.shot("stuck")
        G.finish(false, string.format(
            "route2: VAR_MART reads %s after the Mart scene, not 1 — the parcel scene did not "
            .. "run as decoded (%s)", tostring(mart_var_after), tostring(why3)))
        return
    end
    G.phase("parcel-received", "VAR_MART=1")

    -- ── leg: Mart -> Oak's Lab (deliver the parcel, receive the Pokedex flag + 10 Poke Balls) ─
    local ok3, why4 = play.enter_warp(cp, "Down", 30)
    if not ok3 then G.shot("stuck"); G.finish(false, "route2 Mart->Viridian: " .. tostring(why4)); return end
    if H.map(cp) ~= 3 * 256 + 1 then
        G.shot("stuck"); G.finish(false, "route2: not back on Viridian City: " .. play.where(cp)); return
    end
    play.follow(cp, "viridian_mart_door_south_to_south_edge", "route2")
    local ok4, why5 = play.enter_warp(cp, "Down", 30)
    if not ok4 then G.shot("stuck"); G.finish(false, "route2 Viridian->Route1: " .. tostring(why5)); return end
    if H.map(cp) ~= 3 * 256 + 19 then
        G.shot("stuck"); G.finish(false, "route2: not back on Route1: " .. play.where(cp)); return
    end
    play.follow(cp, "route1_north_edge_to_south_edge", "route2")
    local ok5, why6 = play.enter_warp(cp, "Down", 30)
    if not ok5 then G.shot("stuck"); G.finish(false, "route2 Route1->Pallet: " .. tostring(why6)); return end
    if H.map(cp) ~= 3 * 256 + 0 then
        G.shot("stuck"); G.finish(false, "route2: not on Pallet Town: " .. play.where(cp)); return
    end
    play.follow(cp, "pallet_north_edge_to_lab_door_south", "route2")
    local ok6, why7 = play.enter_warp(cp, "Up", 30)
    if not ok6 then G.shot("stuck"); G.finish(false, "route2 Pallet->OaksLab: " .. tostring(why7)); return end
    if H.map(cp) ~= 4 * 256 + 3 then
        G.shot("stuck"); G.finish(false, "route2: not inside Oak's Lab: " .. play.where(cp)); return
    end
    G.phase("lab-entered", play.where(cp))

    play.follow(cp, "oakslab_entrance_to_oak", "route2")
    -- FACING Oak is not talking to him (gen3_scripted_play.lua's own parcel_deliver leg, same
    -- shape): one more Up turns the player to face the blocking object event without moving,
    -- then A is the interact button that starts his `lock; faceplayer` talk script
    -- (PalletTown_ProfessorOaksLab_EventScript_ProfOak, decoded this card at ROM addr
    -- 0x9050959). No RR key-items-pocket read is pinned to witness the parcel leaving the bag
    -- (the FR precedent's witness), so scene_quiet going false is this leg's own witness that
    -- the talk script actually started.
    G.tap("Up", 2, 13)
    local scene_started = false
    for _ = 1, 400 do
        if not H.scene_quiet(cp) then scene_started = true; break end
        G.tap("A", 3, 16)
    end
    if not scene_started then
        G.shot("stuck"); G.finish(false, "route2: talking to Oak never started a scene"); return
    end
    if not play.wait_scene_settled(cp, 9000) then
        G.shot("stuck"); G.finish(false, "route2: Oak's delivery scene never settled"); return
    end

    local mart_var_final, why8 = read_var(VAR_MART)
    local dex_flag, why9 = read_flag(FLAG_SYS_POKEDEX_GET)
    local ball_item, ball_qty = ball_slot0()
    if mart_var_final ~= 2 or dex_flag ~= 1 or ball_item ~= ITEM_POKE_BALL or ball_qty < 2 then
        G.shot("stuck")
        G.finish(false, string.format(
            "route2: Oak's delivery scene did not leave the expected RAM state: VAR_MART=%s "
            .. "(want 2, %s) FLAG_SYS_POKEDEX_GET=%s (want 1, %s) ball_pocket_slot0=item %s "
            .. "x%s (want item %d, qty>=2)", tostring(mart_var_final), tostring(why8),
            tostring(dex_flag), tostring(why9), tostring(ball_item), tostring(ball_qty),
            ITEM_POKE_BALL))
        return
    end
    G.phase("parcel-delivered", string.format("VAR_MART=2 dex=1 balls=%d", ball_qty))

    -- ── leg: Oak's Lab -> grass origin ──────────────────────────────────────────────────────
    play.follow(cp, "oakslab_oak_to_entrance", "route2")
    local ok7, why10 = play.enter_warp(cp, "Down", 30)
    if not ok7 then G.shot("stuck"); G.finish(false, "route2 OaksLab->Pallet: " .. tostring(why10)); return end
    if H.map(cp) ~= 3 * 256 + 0 then
        G.shot("stuck"); G.finish(false, "route2: not back on Pallet Town: " .. play.where(cp)); return
    end
    play.follow(cp, "pallet_lab_door_south_to_north_edge", "route2")
    local ok8, why11 = play.enter_warp(cp, "Up", 30)
    if not ok8 then G.shot("stuck"); G.finish(false, "route2 Pallet->Route1: " .. tostring(why11)); return end
    if H.map(cp) ~= 3 * 256 + 19 then
        G.shot("stuck"); G.finish(false, "route2: not back on Route1: " .. play.where(cp)); return
    end
    play.follow(cp, "route1_south_edge_to_grass_origin", "route2")
    if not play.wait_at(cp, TARGET.x, TARGET.y, 120) or not at_target(cp) then
        G.shot("stuck"); G.finish(false, "route2: not back at the grass origin: " .. play.where(cp)); return
    end
    G.phase("back-at-grass-origin", play.where(cp))

    -- ── leg: catch a second mon with a normal input (weaken not needed: 10 fresh balls) ─────
    if not H.in_battle(cp) then
        if not pace_for_encounter(cp, 4000) then
            G.shot("stuck")
            G.finish(false, "route2: no wild encounter after pacing the grass origin"); return
        end
    end
    if not throw_pokeballs(cp, "route2") then
        G.shot("stuck")
        G.finish(false, string.format(
            "route2: never reached B_OUTCOME_CAUGHT (last outcome=%d)",
            memory.read_u8(BATTLE_OUTCOME_ADDR)))
        return
    end
    if not play.mash_a(2400, function() return H.on_field(cp) end) then
        G.finish(false, "route2: caught outcome never returned to a controllable field"); return
    end
    local line_after, _, n_after = party_line()
    if not line_after or n_after ~= n_before + 1 then
        G.finish(false, string.format(
            "route2: party did not grow by exactly one after the catch (%s mons -> %s): %s",
            tostring(n_before), tostring(n_after), tostring(line_after)))
        return
    end
    G.phase("caught", line_after)

    -- ── leg: save in-game at the grass origin ───────────────────────────────────────────────
    if not play.wait_at(cp, TARGET.x, TARGET.y, 120) or not at_target(cp) then
        G.shot("stuck"); G.finish(false, "route2: drifted off the grass origin before saving: "
                     .. play.where(cp)); return
    end
    local ok9, before9, after9, why12 = G.save_via_menu(cp, domain)
    if not ok9 then
        G.finish(false, string.format("route2: in-game save failed (%d -> %d): %s", before9,
                                      after9, tostring(why12)))
        return
    end
    if not play.wait_at(cp, TARGET.x, TARGET.y, 120) or not at_target(cp) then
        G.shot("stuck"); G.finish(false, "route2: moved during the save: " .. play.where(cp)); return
    end
    G.idle(60)
    G.finish(true, string.format(
        "counter %d -> %d at %s party=%s balls_after_catch=%d",
        before9, after9, play.where(cp), line_after, select(2, ball_slot0())))
end

-- SLINK_GEN3_RR_FIXTURE_LEG selects which driver runs; unset (the default) is `run` exactly as
-- it always was, so rr_battle.sav's own build (W3's, untouched by this card) is byte-for-byte
-- unaffected. "route2" runs the new grass->Mart->Lab->grass->catch->save leg above, seeded from
-- rr_battle.sav, producing rr_battle2.sav via the same tools/gen3_fixtures.py import pipeline.
if (debug.getinfo(1, "S").source or "") == "main" then
    local leg = os.getenv("SLINK_GEN3_RR_FIXTURE_LEG")
    local target = (leg == "route2") and run_route2 or run
    local ok, err = pcall(target)
    if not ok then G.shot("stuck"); G.finish(false, "uncaught Lua error: " .. tostring(err)) end
end
