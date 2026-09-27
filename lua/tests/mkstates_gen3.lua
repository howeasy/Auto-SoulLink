-- mkstates_gen3.lua — the FRLG checkpoint-probe savestates (card C4-PROBE), from the committed
-- party batteries by scripted normal inputs only (no pokes). Launched by tools/mkstates_gen3.py,
-- which seeds tests/fixtures/gen3/<title>_party_<kind>.sav into a per-run SaveRAM dir.
--
-- Cold boot -> CONTINUE (gen3_boot_check.boot_to_field), then per SLINK_STATE_KIND:
--   town    Viridian City (24,39), town ground (the fixture's own tile):
--             slink_overworld.State  field idle
--             slink_door.State       (26,27), below the Center door (26,26), PATHS.route1_edge_to_pokecenter_door
--             slink_script.State     (20,13), below the Viridian woman (object 5 at (20,12),
--                                    MOVEMENT_TYPE_FACE_UP, ViridianCity_EventScript_Woman:
--                                    lock/faceplayer/msgbox) -- the probe's script_running tile
--   trainer Viridian (24,39) -> Route 22's early-rival trigger (33,6) (seeded from the town
--           fixture; route in VIRIDIAN_TO_ROUTE22 / ROUTE22_TO_RIVAL below):
--             slink_pretrainer.State the rival battle parked at the action menu (BATTLE_TYPE_TRAINER)
--             slink_prefaint.State   the first frame gBattleMons[0].hp == 0, the lead knocked out
--                                    while it only used TAIL WHIP; mashing on reaches the
--                                    forced send-out prompt (ctrl == WaitForMonSelection)
--   battle  Route 1 grass (12,37): GRASS_LOOP steps until a wild battle starts, then
--             slink_preintro.State   the first in_battle frame (intro, before any action menu)
--             slink_prebattle.State  the parked action menu (main==HandleTurnActionSelectionState,
--                                    comm[0]==1, ctrl==HandleInputChooseAction, held 30 frames)
--             slink_postbattle.State the first gBattleOutcome ~= 0 frame after RUN
-- Emerald (card E2-CKPT; title emerald, fixtures tests/fixtures/gen3/emerald_<kind>.sav):
--   town    Oldale (6,17), the heal tile one step S of the Center door (6,16):
--             slink_overworld.State = slink_door.State  field idle; Up enters the Center
--             slink_pokecenter.State Center 1F arrival mat (7,8)
--             slink_script.State     (7,4), below the nurse (7,2) across the counter
--   battle  Route 102 grass (21,16): EM_GRASS_LOOP -> slink_preintro/slink_prebattle/slink_postbattle
--   trainer Route 102 (32,16): one Right onto (33,16), Youngster Calvin's sight line ->
--             slink_pretrainer.State (parked action menu, BATTLE_TYPE_TRAINER)
-- States land in SLINK_STATE_DIR (absolute). Addresses come from the pack (cp.battle) and the
-- title syms gen3_scripted_play.lua already exports; nothing here is a new address.
local WT = SLINK_ROOT or os.getenv("SLINK_ROOT")
assert(WT, "SLINK_ROOT unset — run via tools/mkstates_gen3.py")
local G = dofile(WT .. "/lua/tests/gen3_boot_check.lua")
local SP = dofile(WT .. "/lua/tests/gen3_scripted_play.lua")   -- data/witness exports only
local DIR = assert(os.getenv("SLINK_STATE_DIR"), "SLINK_STATE_DIR unset")
local KIND = os.getenv("SLINK_STATE_KIND")

-- Plaintext battle RAM (identical in FR/LG: data/gen3/pret/poke{firered,leafgreen}.sym, checked
-- by tests/unit/test_mkstates_gen3.py). struct BattlePokemon: moves[4] @0x0C, hp @0x28
-- (pret include/pokemon.h:170-196). gMoveSelectionCursor[0] is 0..3 in a 2x2 grid; Right/Left
-- flip bit 0, Down/Up flip bit 1 (src/battle_controller_player.c HandleInputChooseMove).
local M = {
    BATTLE_MONS = 0x02023BE4, BMON_MOVES = 0x0C, BMON_HP = 0x28,
    MOVE_CURSOR = 0x02023FFC,
    HANDLE_INPUT_CHOOSE_MOVE = 0x0802EA11,   -- battle_controller_player.c, Thumb bit set
    WAIT_FOR_MON_SELECTION = 0x08030685,     -- the forced send-out prompt's controller func
    MOVE_TAIL_WHIP = 39,                     -- include/constants/moves.h:43
    BATTLE_TYPE_TRAINER = 8,                 -- include/constants/battle.h:50
}
-- Route derivation (tools/gba_map.py --bfs over the ROM layouts, FR and LG identical; ledges
-- avoided). ViridianCity 3.1 left edge -> Route22 3.41 at offset 10, so Viridian (0,19) crosses to
-- Route22 (47,9). Route22 coord_events (pret data/maps/Route22/map.json): (33,4..6) run
-- Route22_EventScript_EarlyRivalTrigger* while VAR_MAP_SCENE_ROUTE22 == 1, which the parcel
-- delivery sets (PalletTown_ProfessorOaksLab/scripts.inc:682) -- both party fixtures are past it.
-- (33,6) has elevation 0 (any). The walk crosses Route22's tall grass at (39,9..13),(37..38,9):
-- incidental wild battles are fled. It stays off Viridian's old-man tutorial triggers (20|22,8).
M.VIRIDIAN_TO_ROUTE22 = { from = { 24, 39 }, to = { 0, 19 }, dirs = {
    "Up","Up","Up","Up","Up","Up","Up","Up","Left","Left",
    "Up","Up","Up","Up","Up","Up","Up","Up","Up","Up","Up","Up",
    "Left","Left","Left","Left","Left","Left","Left","Left","Left","Left","Left",
    "Left","Left","Left","Left","Left","Left","Left","Left","Left","Left","Left" } }
M.ROUTE22_TO_RIVAL = { from = { 47, 9 }, to = { 34, 6 }, dirs = {
    "Left","Left","Down","Down","Down","Down","Down","Left","Left","Left","Left","Left","Left",
    "Up","Up","Up","Up","Up","Left","Left","Up","Up","Up","Left","Left","Left" } }
M.RIVAL_TRIGGER = { 33, 6 }
M.DOOR_TO_SCRIPT = { from = { 26, 27 }, to = { 20, 13 }, dirs = {
    "Left","Left","Left","Up","Up","Up","Up","Up","Up","Up","Up","Left",
    "Up","Up","Up","Up","Up","Up","Left","Left" } }

local cp
local ACTION_CURSOR   -- gActionSelectionCursor: SP's for FR/LG, pokeemerald.sym's for emerald (run())
local function in_battle() return not G.pred_ok(cp, "in_battle") end
local function clause(name)
    for _, c in ipairs(cp.battle.clauses) do
        if c.name == name then return c.address + (c.offset or 0), c.expect end
    end
    error("no battle clause " .. name)
end

local function save(name, detail)
    local path = DIR .. "/" .. name
    local ok, err = pcall(savestate.save, path)
    if not ok then G.finish(false, "savestate.save " .. path .. ": " .. tostring(err)) end
    G.phase("state-saved", name .. " " .. (detail or ""))
end

-- Position-fed hold (a 3-frame tap only turns the player), stopping if a battle starts.
local function step(dir)
    local x, y = G.pos(cp)
    for _ = 1, 48 do
        if in_battle() then break end
        joypad.set({ [dir] = true }); G.advance()
        local nx, ny = G.pos(cp)
        if nx ~= x or ny ~= y then break end
    end
    joypad.set({})
    for _ = 1, 24 do
        if in_battle() then break end
        G.advance()
    end
    local nx, ny = G.pos(cp)
    return nx ~= x or ny ~= y
end

local function at(g, n, x, y)
    local mg, mn = G.map(cp)
    local px, py = G.pos(cp)
    return mg == g and mn == n and px == x and py == y,
        string.format("at %d.%d (%d,%d), want %d.%d (%d,%d)", mg, mn, px, py, g, n, x, y)
end

local function field_settled()
    for _, p in ipairs({ "callback2", "in_battle", "field_controls_locked",
                         "script_context_status", "palette_fade_active" }) do
        if not G.pred_ok(cp, p) then return false, p end
    end
    return true
end

--- Returns true once the field held `hold` frames, else false and the predicate still refusing.
local function wait_field(frames, hold)
    local held, ok, why = 0, false, nil
    for _ = 1, frames or 3000 do
        ok, why = field_settled()
        held = ok and held + 1 or 0
        if held >= (hold or 30) then return true end
        G.advance()
    end
    G.shot("stuck")
    return false, why
end

-- Action-menu/outcome reads from the pack's battle clauses (bound in run()).
local B = {}

--- RUN from a wild battle (cursor 3 in the 2x2 grid 0 FIGHT/1 BAG/2 POKeMON/3 RUN), retried on
--- "Can't escape!". Returns true once gBattleOutcome ~= 0.
local function run_away()
    local function outcome() return memory.read_u8(B.out_a) ~= 0 end
    for _ = 1, 8 do
        if not G.mash(600, function() return outcome() or B.menu_up() end) then break end
        if outcome() then break end
        for _ = 1, 4 do
            local c = memory.read_u8(ACTION_CURSOR)
            if c == 3 then break end
            if c % 2 == 0 then G.tap("Right", 3, 20) end
            if c < 2 then G.tap("Down", 3, 20) end
        end
        if memory.read_u8(ACTION_CURSOR) ~= 3 then return false end
        joypad.set({ A = true }); G.advance(); G.advance(); G.advance(); joypad.set({})
        for _ = 1, 120 do
            if outcome() then break end
            G.advance()
        end
        if outcome() then break end
    end
    return outcome()
end

--- Walk `path.dirs` one tile each (NPC-block retries), fleeing any incidental wild battle.
local function follow(g, n, path, label)
    local ok, where = at(g, n, path.from[1], path.from[2])
    if not ok then return false, label .. " start: " .. where end
    for i, dir in ipairs(path.dirs) do
        local moved = false
        for _ = 1, 6 do
            moved = step(dir)
            if in_battle() then
                if not run_away() then return false, label .. ": could not flee a wild battle" end
                -- "Got away safely!" waits for A; A only (a mashed Start could open the field menu)
                for i = 1, 3000 do
                    if field_settled() then break end
                    joypad.set(i % 16 == 8 and { A = true } or {}); G.advance()
                end
                local back, why = wait_field()
                if not back then
                    return false, string.format("%s: field never returned after fleeing (%s refuses, at %s)",
                        label, tostring(why), select(2, at(g, n, -1, -1)))
                end
            end
            if moved then break end
        end
        if not moved then
            return false, string.format("%s: blocked at step %d going %s (%s)", label, i, dir,
                select(2, at(g, n, -1, -1)))
        end
    end
    return at(g, n, path.to[1], path.to[2])
end

local function run_town()
    local ok, where = at(3, 1, 24, 39)
    if not ok then return G.finish(false, "town start: " .. where) end
    G.idle(30)
    save("slink_overworld.State", where)
    local path = SP.PATHS.route1_edge_to_pokecenter_door
    for _, dir in ipairs(path.dirs) do
        local moved = false
        for _ = 1, 6 do   -- a wandering NPC can block a step; retry it
            moved = step(dir)
            if moved or in_battle() then break end
        end
        if in_battle() then return G.finish(false, "town walk: wild battle in Viridian") end
        if not moved then return G.finish(false, "town walk: blocked going " .. dir .. " " .. select(2, at(0, 0, 0, 0))) end
    end
    ok, where = at(3, 1, path.to[1], path.to[2])
    if not ok then return G.finish(false, "door walk: " .. where) end
    G.idle(20)
    save("slink_door.State", where)
    ok, where = follow(3, 1, M.DOOR_TO_SCRIPT, "script walk")
    if not ok then return G.finish(false, where) end
    G.idle(20)
    save("slink_script.State", where)
    G.finish(true, "town states in " .. DIR)
end

local function bind_battle()
    B.main_a, B.main_x = clause("battle_main_func")
    -- the pack's STATE_WAIT_ACTION_CHOSEN: 1 on FR/LG, 2 on Emerald (E2-FIX-AB F-B)
    B.comm_a, B.comm_x = clause("battle_comm_0")
    B.flags_a = clause("battle_exec_flags_input")
    B.ctrl_a, B.ctrl_x = clause("battle_input_controller")
    B.out_a = clause("battle_outcome_open")
    B.type_a = clause("battle_not_link")   -- gBattleTypeFlags
    B.vals = function()
        return string.format("main=%08X comm0=%d flags=%08X ctrl=%08X outcome=%d type=%08X hp0=%d",
            memory.read_u32_le(B.main_a), memory.read_u8(B.comm_a), memory.read_u32_le(B.flags_a),
            memory.read_u32_le(B.ctrl_a), memory.read_u8(B.out_a), memory.read_u32_le(B.type_a),
            memory.read_u16_le(M.BATTLE_MONS + M.BMON_HP))
    end
    B.menu_up = function()
        return memory.read_u32_le(B.main_a) == B.main_x and memory.read_u8(B.comm_a) == B.comm_x
            and memory.read_u32_le(B.ctrl_a) == B.ctrl_x
    end
end

--- Mash to the parked action menu (held 30 frames). Returns true when parked.
local function park()
    for _ = 1, 3 do
        G.mash(3000, B.menu_up)
        local held = 0
        for _ = 1, 30 do
            if B.menu_up() then held = held + 1 end
            G.advance()
        end
        if held == 30 then return true end
        G.tap("B", 3, 20)   -- an A that slipped onto FIGHT: back to the action menu
    end
    return false
end

local function run_battle()
    local ok, where = at(3, 19, SP.GRASS_ORIGIN[1], SP.GRASS_ORIGIN[2])
    if not ok then return G.finish(false, "battle start: " .. where) end
    -- GRASS_LOOP from (12,37): Right, Down, Left, Up; every tile of the square is MB_TALL_GRASS.
    local idx = { ["12,37"] = 1, ["13,37"] = 2, ["13,38"] = 3, ["12,38"] = 4 }
    for _ = 1, 240 do
        if in_battle() then break end
        local px, py = G.pos(cp)
        local i = idx[px .. "," .. py]
        if not i then return G.finish(false, string.format("hunt left the grass square at (%d,%d)", px, py)) end
        step(SP.GRASS_LOOP[i])
    end
    if not in_battle() then return G.finish(false, "no wild encounter in 240 grass steps") end
    save("slink_preintro.State", B.vals())
    if not park() then return G.finish(false, "action menu never parked: " .. B.vals()) end
    save("slink_prebattle.State", B.vals())
    if not run_away() then return G.finish(false, "gBattleOutcome never set: " .. B.vals()) end
    save("slink_postbattle.State", B.vals())
    G.finish(true, "battle states in " .. DIR)
end

--- One turn of TAIL WHIP (no damage, so the rival lead is never knocked out and the only way
--- the battle can move on is the player lead fainting). Called at the parked action menu.
local function tail_whip_turn()
    local function in_move() return memory.read_u32_le(B.ctrl_a) == M.HANDLE_INPUT_CHOOSE_MOVE end
    for _ = 1, 4 do   -- action cursor to FIGHT (0)
        local c = memory.read_u8(SP.ACTION_CURSOR_ADDR)
        if c == 0 then break end
        if c % 2 == 1 then G.tap("Left", 3, 13) end
        if c >= 2 then G.tap("Up", 3, 13) end
    end
    if memory.read_u8(SP.ACTION_CURSOR_ADDR) ~= 0 then return false, "action cursor never reached FIGHT" end
    G.tap("A", 3, 0)
    for _ = 1, 90 do if in_move() then break end; G.advance() end
    if not in_move() then return false, "move menu never opened: " .. B.vals() end
    local slot
    for i = 0, 3 do
        if memory.read_u16_le(M.BATTLE_MONS + M.BMON_MOVES + 2 * i) == M.MOVE_TAIL_WHIP then slot = i end
    end
    if not slot then return false, "the lead knows no TAIL WHIP" end
    G.idle(13)
    for _ = 1, 4 do
        local c = memory.read_u8(M.MOVE_CURSOR)
        if c == slot then break end
        if (c & 1) ~= (slot & 1) then G.tap((c & 1) == 0 and "Right" or "Left", 3, 13)
        else G.tap((c & 2) == 0 and "Down" or "Up", 3, 13) end
    end
    if memory.read_u8(M.MOVE_CURSOR) ~= slot then return false, "move cursor never reached TAIL WHIP" end
    G.tap("A", 3, 0)
    for _ = 1, 90 do if not in_move() then break end; G.advance() end
    return not in_move(), "TAIL WHIP not committed"
end

local function run_trainer()
    local ok, where = follow(3, 1, M.VIRIDIAN_TO_ROUTE22, "Viridian walk")
    if not ok then return G.finish(false, where) end
    if not step("Left") then return G.finish(false, "Viridian -> Route 22 crossing did not move") end
    ok, where = follow(3, 41, M.ROUTE22_TO_RIVAL, "Route 22 walk")
    if not ok then return G.finish(false, where) end
    wait_field(600)
    -- The trigger step: position changes, then the rival script locks the field and starts the
    -- battle, so this press is outside follow() (whose battle policy is to flee).
    for _ = 1, 6 do
        if step("Left") then break end
    end
    ok, where = at(3, 41, M.RIVAL_TRIGGER[1], M.RIVAL_TRIGGER[2])
    if not ok then return G.finish(false, "rival trigger: " .. where) end
    G.mash(3000, in_battle)   -- the rival approach and intro text
    if not in_battle() then return G.finish(false, "the rival battle never started") end
    if not park() then return G.finish(false, "trainer action menu never parked: " .. B.vals()) end
    if memory.read_u32_le(B.type_a) & M.BATTLE_TYPE_TRAINER == 0 then
        return G.finish(false, "parked battle is not a trainer battle: " .. B.vals())
    end
    save("slink_pretrainer.State", B.vals())

    local function hp0() return memory.read_u16_le(M.BATTLE_MONS + M.BMON_HP) end
    local function outcome() return memory.read_u8(B.out_a) ~= 0 end
    for turn = 1, 40 do
        local why
        ok, why = tail_whip_turn()
        if not ok then return G.finish(false, string.format("turn %d: %s", turn, why)) end
        G.mash(3000, function() return hp0() == 0 or outcome() or B.menu_up() end)
        if hp0() == 0 then
            save("slink_prefaint.State", string.format("turn=%d %s", turn, B.vals()))
            local prompt = G.mash(3000, function()
                return memory.read_u32_le(B.ctrl_a) == M.WAIT_FOR_MON_SELECTION
            end)
            if not prompt then return G.finish(false, "send-out prompt never reached: " .. B.vals()) end
            G.phase("send-out-prompt", B.vals())
            return G.finish(true, "trainer states in " .. DIR)
        end
        if outcome() then return G.finish(false, "battle ended before the lead fainted: " .. B.vals()) end
        if not B.menu_up() then return G.finish(false, "turn did not return to the action menu: " .. B.vals()) end
        G.idle(30)
    end
    G.finish(false, "the lead survived 40 turns: " .. B.vals())
end

-- ── Emerald (card E2-CKPT) ─────────────────────────────────────────────────────────────────
-- Tiles: tools/gen3_fixtures.py EMERALD_KINDS (Oldale 0.10 heal tile, Route 102 0.17 grass/trainer)
-- and pret data/maps/{OldaleTown,OldaleTown_PokemonCenter_1F,Route102}/map.json.
local EM = {
    TOWN = { 0, 10, 6, 17 }, ROUTE102 = { 0, 17 },
    CENTER_MAT = { 7, 8 }, NURSE_FRONT = { 7, 4 },
    GRASS = { 21, 16 },   -- the 2x2 loop stays inside the (19..25,16..17) MB_TALL_GRASS patch
    GRASS_LOOP = { ["21,16"] = "Right", ["22,16"] = "Down", ["22,17"] = "Left", ["21,17"] = "Up" },
    TRAINER_FROM = { 32, 16 }, TRAINER_TRIGGER = { 33, 16 },
}

local function em_town()
    local ok, where = at(EM.TOWN[1], EM.TOWN[2], EM.TOWN[3], EM.TOWN[4])
    if not ok then return G.finish(false, "town start: " .. where) end
    G.idle(30)
    save("slink_overworld.State", where)
    save("slink_door.State", where .. " (Up enters the Center door)")
    for _ = 1, 3 do if step("Up") then break end end
    if not wait_field(3000, 60) then return G.finish(false, "Center 1F never settled") end
    local g, n = G.map(cp)
    ok, where = at(g, n, EM.CENTER_MAT[1], EM.CENTER_MAT[2])
    if not ok or (g == EM.TOWN[1] and n == EM.TOWN[2]) then return G.finish(false, "Center entry: " .. where) end
    save("slink_pokecenter.State", where)
    ok, where = follow(g, n, { from = EM.CENTER_MAT, to = EM.NURSE_FRONT, dirs = { "Up", "Up", "Up", "Up" } },
        "nurse walk")
    if not ok then return G.finish(false, where) end
    G.idle(20)
    save("slink_script.State", where)
    G.finish(true, "emerald town states in " .. DIR)
end

local function em_battle()
    local ok, where = at(EM.ROUTE102[1], EM.ROUTE102[2], EM.GRASS[1], EM.GRASS[2])
    if not ok then return G.finish(false, "battle start: " .. where) end
    for _ = 1, 240 do
        if in_battle() then break end
        local px, py = G.pos(cp)
        local dir = EM.GRASS_LOOP[px .. "," .. py]
        if not dir then return G.finish(false, string.format("hunt left the grass square at (%d,%d)", px, py)) end
        step(dir)
    end
    if not in_battle() then return G.finish(false, "no wild encounter in 240 grass steps") end
    save("slink_preintro.State", B.vals())
    if not park() then return G.finish(false, "action menu never parked: " .. B.vals()) end
    save("slink_prebattle.State", B.vals())
    if not run_away() then return G.finish(false, "gBattleOutcome never set: " .. B.vals()) end
    save("slink_postbattle.State", B.vals())
    G.finish(true, "emerald battle states in " .. DIR)
end

local function em_trainer()
    local ok, where = at(EM.ROUTE102[1], EM.ROUTE102[2], EM.TRAINER_FROM[1], EM.TRAINER_FROM[2])
    if not ok then return G.finish(false, "trainer start: " .. where) end
    for _ = 1, 6 do if step("Right") then break end end
    ok, where = at(EM.ROUTE102[1], EM.ROUTE102[2], EM.TRAINER_TRIGGER[1], EM.TRAINER_TRIGGER[2])
    if not ok then return G.finish(false, "trainer trigger: " .. where) end
    G.mash(3000, in_battle)   -- the sight-line approach and intro text
    if not in_battle() then return G.finish(false, "the Calvin battle never started") end
    if not park() then return G.finish(false, "trainer action menu never parked: " .. B.vals()) end
    if memory.read_u32_le(B.type_a) & M.BATTLE_TYPE_TRAINER == 0 then
        return G.finish(false, "parked battle is not a trainer battle: " .. B.vals())
    end
    save("slink_pretrainer.State", B.vals())
    G.finish(true, "emerald trainer states in " .. DIR)
end

--- Emerald CONTINUE: A pulses only (a Start in the field would open the menu), then the settle.
local function em_boot()
    for i = 1, 9000 do
        if G.pred_ok(cp, "callback2") then break end
        joypad.set(i % 16 == 8 and { A = true } or {}); G.advance()
    end
    joypad.set({})
    return G.pred_ok(cp, "callback2")
end

local function run()
    G.open("mkstates_gen3")   -- patch/build/mkstates_gen3_result.txt (literal: run_gate.py)
    pcall(client.speedmode, 6399)
    G.budget = 60000
    local title
    cp, title = G.checkpoint()
    G.phase("start", string.format("title=%s kind=%s dir=%s", tostring(title), tostring(KIND), DIR))
    local em = title == "emerald"
    ACTION_CURSOR = SP.ACTION_CURSOR_ADDR
    if em then
        local P = dofile(WT .. "/lua/tests/probe_gen3_checkpoint.lua")
        ACTION_CURSOR = P.load_syms(WT .. "/data/gen3/pret/pokeemerald.sym", { "gActionSelectionCursor" })
            .gActionSelectionCursor
    end
    if not (em and em_boot() or not em and G.boot_to_field(cp, 9000)) then
        return G.finish(false, "never reached the field")
    end
    -- boot_to_field returns while FRLG's post-CONTINUE sequence still locks field controls
    -- (first FR probe run: the idle row refused 98 frames on field_controls_locked+task), so
    -- wait for the probe's own field() predicates to hold 180 frames before any state.
    if not wait_field(3000, 180) then return G.finish(false, "field never settled after CONTINUE") end
    G.phase("settled")
    bind_battle()
    local ok, err
    if KIND == "town" then ok, err = pcall(em and em_town or run_town)
    elseif KIND == "battle" then ok, err = pcall(em and em_battle or run_battle)
    elseif KIND == "trainer" then ok, err = pcall(em and em_trainer or run_trainer)
    else return G.finish(false, "SLINK_STATE_KIND must be town|battle|trainer") end
    if not ok then G.shot("stuck"); G.finish(false, "uncaught Lua error: " .. tostring(err)) end
end

if (debug.getinfo(1, "S").source or "") == "main" then run() end
return M
