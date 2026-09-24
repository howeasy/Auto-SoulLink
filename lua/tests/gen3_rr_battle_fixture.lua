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

if (debug.getinfo(1, "S").source or "") == "main" then
    local ok, err = pcall(run)
    if not ok then G.shot("stuck"); G.finish(false, "uncaught Lua error: " .. tostring(err)) end
end
