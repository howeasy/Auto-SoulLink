-- mkstates_gen3.lua — the FRLG checkpoint-probe savestates (card C4-PROBE), from the committed
-- party batteries by scripted normal inputs only (no pokes). Launched by tools/mkstates_gen3.py,
-- which seeds tests/fixtures/gen3/<title>_party_<kind>.sav into a per-run SaveRAM dir.
--
-- Cold boot -> CONTINUE (gen3_boot_check.boot_to_field), then per SLINK_STATE_KIND:
--   town    Viridian City (24,39), town ground (the fixture's own tile):
--             slink_overworld.State  field idle
--             slink_door.State       (26,27), below the Center door (26,26), PATHS.route1_edge_to_pokecenter_door
--   battle  Route 1 grass (12,37): GRASS_LOOP steps until a wild battle starts, then
--             slink_preintro.State   the first in_battle frame (intro, before any action menu)
--             slink_prebattle.State  the parked action menu (main==HandleTurnActionSelectionState,
--                                    comm[0]==1, ctrl==HandleInputChooseAction, held 30 frames)
--             slink_postbattle.State the first gBattleOutcome ~= 0 frame after RUN
-- States land in SLINK_STATE_DIR (absolute). Addresses come from the pack (cp.battle) and the
-- title syms gen3_scripted_play.lua already exports; nothing here is a new address.
local WT = SLINK_ROOT or os.getenv("SLINK_ROOT")
assert(WT, "SLINK_ROOT unset — run via tools/mkstates_gen3.py")
local G = dofile(WT .. "/lua/tests/gen3_boot_check.lua")
local SP = dofile(WT .. "/lua/tests/gen3_scripted_play.lua")   -- data/witness exports only
local DIR = assert(os.getenv("SLINK_STATE_DIR"), "SLINK_STATE_DIR unset")
local KIND = os.getenv("SLINK_STATE_KIND")

local cp
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
    G.finish(true, "town states in " .. DIR)
end

local function run_battle()
    local ok, where = at(3, 19, SP.GRASS_ORIGIN[1], SP.GRASS_ORIGIN[2])
    if not ok then return G.finish(false, "battle start: " .. where) end
    local main_a, main_x = clause("battle_main_func")
    local comm_a = clause("battle_comm_0")
    local flags_a = clause("battle_exec_flags_input")
    local ctrl_a, ctrl_x = clause("battle_input_controller")
    local out_a = clause("battle_outcome_open")
    local function vals()
        return string.format("main=%08X comm0=%d flags=%08X ctrl=%08X outcome=%d",
            memory.read_u32_le(main_a), memory.read_u8(comm_a), memory.read_u32_le(flags_a),
            memory.read_u32_le(ctrl_a), memory.read_u8(out_a))
    end
    local function menu_up()
        return memory.read_u32_le(main_a) == main_x and memory.read_u8(comm_a) == 1
            and memory.read_u32_le(ctrl_a) == ctrl_x
    end
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
    save("slink_preintro.State", vals())

    local parked = false
    for _ = 1, 3 do
        G.mash(3000, menu_up)
        local held = 0
        for _ = 1, 30 do
            if menu_up() then held = held + 1 end
            G.advance()
        end
        if held == 30 then parked = true; break end
        G.tap("B", 3, 20)   -- an A that slipped onto FIGHT: back to the action menu
    end
    if not parked then return G.finish(false, "action menu never parked: " .. vals()) end
    save("slink_prebattle.State", vals())

    -- RUN (cursor 3 in the 2x2 grid 0 FIGHT/1 BAG/2 POKeMON/3 RUN), retried on "Can't escape!".
    local function outcome() return memory.read_u8(out_a) ~= 0 end
    for _ = 1, 8 do
        if not G.mash(600, function() return outcome() or menu_up() end) then break end
        if outcome() then break end
        for _ = 1, 4 do
            local c = memory.read_u8(SP.ACTION_CURSOR_ADDR)
            if c == 3 then break end
            if c % 2 == 0 then G.tap("Right", 3, 20) end
            if c < 2 then G.tap("Down", 3, 20) end
        end
        if memory.read_u8(SP.ACTION_CURSOR_ADDR) ~= 3 then return G.finish(false, "cursor never reached RUN") end
        joypad.set({ A = true }); G.advance(); G.advance(); G.advance(); joypad.set({})
        for _ = 1, 120 do
            if outcome() then break end
            G.advance()
        end
        if outcome() then break end
    end
    if not outcome() then return G.finish(false, "gBattleOutcome never set: " .. vals()) end
    save("slink_postbattle.State", vals())
    G.finish(true, "battle states in " .. DIR)
end

local function run()
    G.open("mkstates_gen3")   -- patch/build/mkstates_gen3_result.txt (literal: run_gate.py)
    pcall(client.speedmode, 6399)
    G.budget = 60000
    local title
    cp, title = G.checkpoint()
    G.phase("start", string.format("title=%s kind=%s dir=%s", tostring(title), tostring(KIND), DIR))
    if not G.boot_to_field(cp, 9000) then return G.finish(false, "never reached the field") end
    -- boot_to_field returns while FRLG's post-CONTINUE sequence still locks field controls
    -- (first FR probe run: the idle row refused 98 frames on field_controls_locked+task), so
    -- wait for the probe's own field() predicates to hold 180 frames before any state.
    local held = 0
    for _ = 1, 3000 do
        local settled = true
        for _, p in ipairs({ "callback2", "in_battle", "field_controls_locked",
                             "script_context_status", "palette_fade_active" }) do
            settled = settled and G.pred_ok(cp, p)
        end
        held = settled and held + 1 or 0
        if held >= 180 then break end
        G.advance()
    end
    if held < 180 then return G.finish(false, "field never settled after CONTINUE") end
    G.phase("settled")
    local ok, err
    if KIND == "town" then ok, err = pcall(run_town)
    elseif KIND == "battle" then ok, err = pcall(run_battle)
    else return G.finish(false, "SLINK_STATE_KIND must be town|battle") end
    if not ok then G.shot("stuck"); G.finish(false, "uncaught Lua error: " .. tostring(err)) end
end

if (debug.getinfo(1, "S").source or "") == "main" then run() end
