-- lua/tests/gen1_scripted_play.lua — standalone scripted NEW GAME play for Red/Blue gates.
--
-- The proven gen1/rc route modules (gen1_rb_ball_gate_inputs / gen1_rb_parcel_inputs /
-- gen1_rb_save_inputs) are pure step functions: point -> buttons, phase. gen1/rc drove them
-- through its durable runtime; this host drives them with ordinary joypad presses and a
-- read-only WRAM point, nothing else. Normal buttons only — no RAM, register or save staging.
--
--   local P = dofile(ROOT .. "/lua/tests/gen1_scripted_play.lua")
--   local play = P.new(ROOT, title, player)             -- "red"/"blue", "a"/"b"
--   play.boot(step)                                      -- title -> NEW GAME -> bedroom
--   play.run(step, {"lab", "parcel", "save"}, on_phase)  -- chain of route modules to their terminals
-- `step(buttons)` advances one frame with the buttons held (the gate harness owns it).
--
-- Every game literal the route modules read comes from one facts table (P3b-e): the vanilla twin
-- lua/tests/gen1_rb_facts.lua by default, the lane's own file for a pureRGB run. `expected.facts`
-- is how the drivers receive it, so a lane that is not vanilla passes its own file:
--   local play = P.new(ROOT, title, player, {facts = "gen1_pure_facts.lua"})
local P = {}

local MODULES = {
    lab = { file = "gen1_rb_ball_gate_inputs.lua", terminal = "lab-loss-complete" },
    parcel = { file = "gen1_rb_parcel_inputs.lua", terminal = "first-ball-readback" },
    route1 = { file = "gen1_rb_route1_inputs.lua", terminal = "route1-parked" },
    save = { file = "gen1_rb_save_inputs.lua", terminal = "save-witnessed" },
}
P.MODULES = MODULES

-- The lab route is the one module with a per-title twin: Yellow's Pallet intercept, Pikachu
-- demonstration battle and Oak's-lab scripts all differ from Red/Blue, so its driver is a
-- separate file (a0349b8). MODULES is built at file scope while the title only exists inside
-- P.new, so the choice is made there and everything else stays shared. The pureRGB titles take
-- the shared R/B driver: pureRGB's Oak's-lab script tables match pokered's (SAME rows, verified
-- against the pinned source) and the pure leg ran that route live.
local LAB_FILES = { red = "gen1_rb_ball_gate_inputs.lua", blue = "gen1_rb_ball_gate_inputs.lua",
                    yellow = "gen1_y_ball_gate_inputs.lua",
                    purered = "gen1_rb_ball_gate_inputs.lua", pureblue = "gen1_rb_ball_gate_inputs.lua",
                    puregreen = "gen1_rb_ball_gate_inputs.lua" }
P.LAB_FILES = LAB_FILES

-- Title -> the lane's driver-facts table (P3b-e). These are the titles the packs admit
-- (lua/gen1/entry.lua Entry.PACKS), so the SYMBOLS come from the matching .sym set too: the
-- pureRAM addresses moved, and reading vanilla symbols on a pure cartridge would be plausible
-- bytes from the wrong places. `opts.facts` still overrides the table for a caller that knows
-- better (the pure probes did, before the vocabulary existed).
local TITLE_FACTS = { red = "gen1_rb_facts.lua", blue = "gen1_rb_facts.lua", yellow = "gen1_rb_facts.lua",
                      purered = "gen1_pure_facts.lua", pureblue = "gen1_pure_facts.lua",
                      puregreen = "gen1_pure_facts.lua" }
P.TITLE_FACTS = TITLE_FACTS
local TITLE_SYMBOLS = { red = "data/pret/pokered.sym", blue = "data/pret/pokeblue.sym",
                        yellow = "data/pret/pokeyellow.sym", purered = "data/purergb/pokered.sym",
                        pureblue = "data/purergb/pokeblue.sym", puregreen = "data/purergb/pokegreen.sym" }
P.TITLE_SYMBOLS = TITLE_SYMBOLS

local IDLE = { A = false, B = false, Start = false, Select = false, Up = false, Down = false, Left = false, Right = false }

local function load_symbols(ROOT, title)
    local rel = assert(TITLE_SYMBOLS[title], "no symbol set for " .. tostring(title))
    local symbols = {}
    for line in io.lines(ROOT .. "/" .. rel) do
        local _, address, name = line:match("^(%x+):(%x+) (%S+)$")
        if address then symbols[name] = tonumber(address, 16) end
    end
    return symbols
end

function P.new(ROOT, title, player, opts)
    assert(TITLE_FACTS[title],
           "scripted play has a Red/Blue lab route and a Yellow one, plus the pureRGB titles; "
           .. "nothing else")
    assert(player == "a" or player == "b")
    opts = opts or {}
    local symbols = load_symbols(ROOT, title)
    -- Per-instance module table: the lab entry is the title's driver, the rest are shared.
    local modules = {}
    for name, spec in pairs(MODULES) do modules[name] = spec end
    modules.lab = { file = assert(LAB_FILES[title], "no lab driver for " .. title),
                    terminal = MODULES.lab.terminal }
    -- Foundation facts (P3b-e): every game literal the drivers below read comes from one table.
    -- The lane names its own file by title; `opts.facts` names it outright for callers whose title
    -- vocabulary has no pure spelling yet (pureRGB keeps the R/B ROM header, so
    -- Entry.detect_title still answers "red" on a pure cartridge).
    local F = dofile(ROOT .. "/lua/tests/" .. (opts.facts or TITLE_FACTS[title]))
    local FIELDS = dofile(ROOT .. "/lua/tests/gen1_rb_point_fields.lua").with_facts(F)
    local SIG = dofile(ROOT .. "/lua/tests/gen1_rb_mart_signature.lua").with_facts(F)
    local function rd(addr) return memory.read_u8(addr, "System Bus") end
    local function sym(name) return rd(assert(symbols[name], "no symbol " .. name)) end
    local self = { symbols = symbols, log = opts.log or function() end, modules = modules }

    -- New Game menus, from gen1/rc's bootstrap: A on a 16-frame cadence with Start pulses; the
    -- four-item name menus (wMaxMenuItem 3 at Y2/X1) take Down once then A = the first preset name
    -- (engine/movie/oak_speech/oak_speech2.asm:172-182; the alphabet grid in
    -- engine/menus/naming_screen.asm is Y3/X1/max7 and is a different screen), so both players and
    -- rivals get preset names. The geometry is a lane fact (F.MENU.NAMING).
    local beat = 0
    local function menu_buttons()
        beat = beat + 1
        local moment = beat % F.TUNING.input_cadence
        local buttons = { A = moment < 2, Start = moment == 8 }
        if sym("wMaxMenuItem") == F.MENU.NAMING.menu_max and sym("wTopMenuItemY") == F.MENU.NAMING.menu_y
            and sym("wTopMenuItemX") == F.MENU.NAMING.menu_x then
            buttons = { Down = sym("wCurrentMenuItem") == 0, A = sym("wCurrentMenuItem") > 0 and moment < 2 }
        end
        local pressed = {}
        for key, value in pairs(IDLE) do pressed[key] = buttons[key] or value end
        return pressed
    end

    -- 0-based START menu row whose glyphs read "SAVE" (S,A,V,E = $92,$80,$95,$84); the menu's
    -- cursor sits at (menu_x, menu_y) = (11, 2) and its glyph column is one tile right of it
    -- (engine/menus/draw_start_menu.asm:17-38,83-89), so the rows are (menu_x+1, menu_y+2*i);
    -- -1 if the menu is not drawn.
    local function save_row()
        for i = 0, 7 do
            local at = assert(symbols.wTileMap) + (F.MENU.START.menu_y + 2 * i) * 20 + (F.MENU.START.menu_x + 1)
            if rd(at) == 0x92 and rd(at + 1) == 0x80 and rd(at + 2) == 0x95 and rd(at + 3) == 0x84 then return i end
        end
        return -1
    end

    function self.point()
        local event_byte = rd(assert(symbols.wEventFlags) + 4)
        local hp = rd(assert(symbols.wPartyMon1HP)) * 256 + rd(assert(symbols.wPartyMon1HP) + 1)
        local raw = {
            map = sym("wCurMap"), x = sym("wXCoord"), y = sym("wYCoord"),
            party_count = sym("wPartyCount"), battle = sym("wIsInBattle"), opponent = sym("wCurOpponent"),
            menu_y = sym("wTopMenuItemY"), menu_x = sym("wTopMenuItemX"), menu_max = sym("wMaxMenuItem"),
            menu_index = sym("wCurrentMenuItem"), move2 = rd(assert(symbols.wBattleMonMoves) + 1),
            move2_pp = rd(assert(symbols.wBattleMonPP) + 1),
            move1 = rd(assert(symbols.wBattleMonMoves)), move1_pp = rd(assert(symbols.wBattleMonPP)),
            text_box = sym("wTextBoxID"), lab_script = sym("wOaksLabCurScript"),
            pallet_script = sym("wPalletTownCurScript"), joy_ignore = sym("wJoyIgnore"),
            npc_moving = sym("wStatusFlags5") % 2 == 1,
            battle_result = sym("wBattleResult"), party_hp = hp,
            lab_rival_done = math.floor(event_byte / 8) % 2 == 1,
            ball_count = FIELDS.bag_quantity(rd, assert(symbols.wNumBagItems), assert(symbols.wBagItems), FIELDS.POKE_BALL),
            parcel_count = FIELDS.bag_quantity(rd, assert(symbols.wNumBagItems), assert(symbols.wBagItems), FIELDS.OAKS_PARCEL),
            money = FIELDS.bcd_money(rd, assert(symbols.wPlayerMoney)),
            got_parcel = FIELDS.event_bit(rd, assert(symbols.wEventFlags), FIELDS.EVENT_GOT_OAKS_PARCEL),
            oak_got_parcel = FIELDS.event_bit(rd, assert(symbols.wEventFlags), FIELDS.EVENT_OAK_GOT_PARCEL),
            mart_script = sym("wViridianMartCurScript"),
            simulated_joypad_index = sym("wSimulatedJoypadStatesIndex"),
            facing = FIELDS.facing_name(sym("wSpritePlayerStateData1FacingDirection")),
            battle_type = sym("wBattleType"), run_attempts = sym("wNumRunAttempts"),
            list_menu_id = sym("wListMenuID"), cur_item = sym("wCurItem"), quantity = sym("wItemQuantity"),
            chosen_menu_item = sym("wChosenMenuItem"), menu_exit_method = sym("wMenuExitMethod"),
            list_scroll_offset = sym("wListScrollOffset"), menu_watch_oob = sym("wMenuWatchMovingOutOfBounds"),
            font_loaded = sym("wFontLoaded") % 2 == 1, save_file_status = sym("wSaveFileStatus"),
            got_pokedex = FIELDS.event_bit(rd, assert(symbols.wEventFlags), F.EVENT.GOT_POKEDEX),
            start_menu_save_index = save_row(),
        }
        raw.menu_kind, raw.item_id, raw.confirm_index = SIG.mart_menu(raw, title)
        return raw
    end

    -- The route modules assert a paired handshake and an owned-runtime status; standalone play
    -- supplies constant identities (the assertions are identity checks, not behaviour).
    local expected = { run_id = "scripted", player = player, rom_sha1 = gameinfo.getromhash():lower(),
                       context_generation = 1, physical_instance = "scripted-host", title = title,
                       facts = F }
    self.expected = expected
    local handshake = { ready = true, run_id = expected.run_id, player = player, rom_sha1 = expected.rom_sha1,
                        context_generation = 1, physical_instance = expected.physical_instance }
    local status = { observation_loop = true, context = { context_generation = 1, physical_instance = expected.physical_instance },
                     host = { owner_id = expected.physical_instance, held = false },
                     runtime = { connected = true, session_state = "admitted", failed = false } }

    -- Boot: title -> NEW GAME -> names -> Oak's speech -> the bedroom (REDS_HOUSE_2F).
    -- WRAM already reads map $26 / party 0 / joy_ignore 0 while Oak is still talking (the
    -- intro pre-loads the bedroom), so no static read can say the player is in control. The
    -- oracle is `overworld_ok()` = gen1_write_safety.check(): the main thread parked in
    -- OverworldLoop's DelayFrame with PC at the IRQ vector — the same fact gen1/rc's
    -- "observation_loop" status meant. Done when that holds for 30 straight frames on map $26.
    function self.boot(step, overworld_ok, max_frames)
        assert(type(overworld_ok) == "function", "boot needs the overworld checkpoint predicate")
        max_frames = max_frames or 20000
        local settled = 0
        -- Idle frames on the title screen move the trainer ID. Random runs every VBlank
        -- (home/vblank.asm:37; engine/math/random.asm:1-13 folds rDIV into hRandomAdd/Sub) and
        -- InitPlayerData2 takes both for wPlayerID (engine/movie/oak_speech/init_player_data.asm:
        -- 4-10), so a different idle count is a different, still deterministic, OT -- what the
        -- A1 second-OT fixture is built with. 0 for every caller that does not ask for it.
        local idled = 0
        for _ = 1, (opts.title_idle or 0) do step(IDLE); idled = idled + 1 end
        if opts.log then opts.log(("TITLE_IDLE requested=%d applied=%d"):format(opts.title_idle or 0, idled)) end
        for f = 1, max_frames do
            local ok = sym("wCurMap") == F.MAP.REDS_HOUSE_2F and sym("wPartyCount") == 0 and overworld_ok()
            settled = ok and settled + 1 or 0
            if settled >= 30 then self.log(string.format("[scripted] bedroom reached after %d frames", f)) return f end
            step(ok and IDLE or menu_buttons())
        end
        error("scripted New Game made no bounded progress (" .. max_frames .. " frames)", 0)
    end

    -- Run route modules in order to their terminals. on_phase(name, phase, frame) is called on
    -- every phase change. Returns the receipts {module -> frames}.
    function self.run(step, chain, on_phase, max_frames_each)
        max_frames_each = max_frames_each or 120000
        local receipts = {}
        for _, name in ipairs(chain) do
            local spec = assert(modules[name], "unknown route " .. tostring(name))
            local driver = assert(dofile(ROOT .. "/lua/tests/" .. spec.file)).new(expected)
            local last_phase, frames = nil, 0
            while true do
                frames = frames + 1
                assert(frames <= max_frames_each, name .. ": route made no bounded progress")
                local frame = emu.framecount()
                local point = self.point()
                local buttons, phase = driver.step(handshake, status, point, frame)
                if phase ~= last_phase then
                    last_phase = phase
                    if on_phase then on_phase(name, phase, frame, point) end
                end
                if phase == spec.terminal then
                    step(IDLE)
                    receipts[name] = frames
                    break
                end
                step(buttons)
            end
        end
        return receipts
    end

    return self
end

return P
