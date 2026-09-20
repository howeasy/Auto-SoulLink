-- FIX-EVO physical receipt: a level-up evolution reaches the production client as ONE
-- `key_change reason=evolution`, through the after-battle path that never enters
-- TryEvolvingMon. Buttons only; the production client sends to G's loopback.
-- Result file: patch/build/test_gen1_evolution_gate_result.txt
-- Coordinator-owned emulator lane: run_gb_gate.py --rom red|blue --target battle.
--   SLINK_EVO_CANCEL=1  variant: B during the animation cancels the evolution; the receipt
--                       must then show EvolutionAfterBattle + CancelledEvolution and NO
--                       evolve signal / key_change.
--
-- Route (R/B only: gen1_rb_forest_inputs decodes pret/pokered's .blk maps and Yellow's forest
-- is a different map; Route 1 itself has only Pidgey/Rattata in all three titles):
--   battle fixture Route 1 (10,35) -> Viridian Forest (18,41) by the forest walker
--   (incidental battles are RUN by the route-1 driver);
--   pace the two grass half-blocks, RUN from everything but a Caterpie/Weedle, CATCH the
--   first one with the fixture's one ball (gen1_rb_hunt_inputs' catch plan; its B-taps
--   decline the nickname);
--   stage the catch's experience (below); then the level-up battle: RUN from everything but
--   a Kakuna/Metapod (Harden only, zero damage -- 40% of the forest in both titles), switch
--   the catch in, and let it Tackle/Poison Sting the foe down. It gains the exp alone, grows
--   to level 7 in that battle, and EndOfBattle evolves it.
--
-- INSTRUMENT, not product: a forest Caterpie/Weedle is L3-5 and would need ~10 solo wins
-- (exp 27..135 -> 343 at yield 52-53 x level / 7) with no Center in reach, which a 15-17 HP
-- bug does not survive. The gate therefore writes the catch's experience to
-- exp_for_level(7) - 1 at the overworld checkpoint (three big-endian bytes at struct +14,
-- pokemon_data_constants.asm:39), the way the retired stone gate staged its Clefairy. Every
-- product step after that is the engine's own: GainExperience -> "grew to level 7" ->
-- EndOfBattle.evolution -> predef EvolutionAfterBattle (end_of_battle.asm:42-45) ->
-- Evolution_PartyMonLoop -> the species publish the client hooks -> key_change.
-- Nothing is written through the client, and nothing the client keys on (DVs, OT, species)
-- is touched by the staging.
local G = dofile((SLINK_ROOT or os.getenv("SLINK_ROOT")) .. "/lua/tests/gen1_gate.lua")
local t = G.start("test_gen1_evolution_gate")
local C = dofile(t.ROOT .. "/lua/tests/gen1_inputs_common.lua")
local P = dofile(t.ROOT .. "/lua/tests/gen1_scripted_play.lua")
local Hunt = dofile(t.ROOT .. "/lua/tests/gen1_rb_hunt_inputs.lua")
local Forest = dofile(t.ROOT .. "/lua/tests/gen1_rb_forest_inputs.lua")
local Driver = dofile(t.ROOT .. "/lua/tests/gen1_battle_driver.lua")
local CANCEL = os.getenv("SLINK_EVO_CANCEL") == "1"
local play = P.new(t.ROOT, t.title, "a", {log = t.log})
local S, rom = play.symbols, t.parts.profile.rom
local json, reads = t.parts.json, t.parts.reads
local ram, d = t.parts.profile.ram, t.parts.profile.derived
local function rd(addr) return memory.read_u8(addr, "System Bus") end
local function frame() return emu.framecount() end

-- internal indices (data/pokemon/dex_order.asm): Caterpie $7B -> Metapod $7C (dex 11),
-- Weedle $70 -> Kakuna $71 (dex 14). The cocoons are also the harmless level-up foes.
local TARGETS = {[0x7B] = {evolved = 0x7C, dex = 11, name = "CATERPIE"},
                 [0x70] = {evolved = 0x71, dex = 14, name = "WEEDLE"}}
local COCOONS = {[0x71] = "KAKUNA", [0x7C] = "METAPOD"}
local EVO_LEVEL = 7
local WALK_FRAMES, HUNT_FRAMES, HUNT_ENCOUNTERS = 90000, 90000, 40
local LEVEL_FRAMES, LEVEL_ENCOUNTERS, LEVEL_TURNS = 90000, 20, 45
local tx = {captures = {}, key_changes = {}, no_catch = {}}
local sig = {evolve = {}}
local hits = {TryEvolvingMon = 0, EvolutionAfterBattle = 0, CancelledEvolution = 0}
local hooks, driver = {}, nil
local catch = nil      -- {slot, key, species, nick, level} once caught
local levelup_frame = nil

-- ── observation only: the production client's own signals and TX ─────────────────────────
local on_signal = t.client.on_signal
function t.client:on_signal(s)
    if s.kind == "evolve" then
        sig.evolve[#sig.evolve + 1] = {frame = s.frame, pc = s.pc, which = s.point and s.point.which}
        t.log(string.format("SIGNAL evolve@%d pc=%04X which=%s", s.frame, s.pc, tostring(s.point and s.point.which)))
    end
    return on_signal(self, s)
end
local send = t.net.send
function t.net.send(line)
    send(line)
    local msg = assert(json.decode(line))
    local bucket = ({capture = tx.captures, key_change = tx.key_changes, no_catch = tx.no_catch})[msg.event]
    if bucket then
        bucket[#bucket + 1] = {msg = msg, frame = frame()}
        t.log("TX " .. line)
    end
end

-- ── diagnostic hooks, bank/PC qualified, pinned to this title's pret .sym ────────────────
local function hook(name, first_byte)
    local pc = assert(S[name], "no symbol " .. name)
    local bank = rom.TryEvolvingMon.bank
    assert(memory.read_u8(bank * 0x4000 + pc - 0x4000, "ROM") == first_byte, "ROM anchor differs: " .. name)
    local id = event.on_bus_exec(function()
        if rd(S.hLoadedROMBank) == bank and emu.getregister("PC") == pc then
            hits[name] = hits[name] + 1
            t.log(string.format("HOOK %s@%d", name, frame()))
        end
    end, pc, "evo-gate-" .. name, "System Bus")
    assert(id, "hook registration failed: " .. name)
    hooks[#hooks + 1] = id
end

local function balls()
    local bag = assert(reads.read_bag())
    local n = 0
    for _, item in ipairs(bag.items) do if item.id >= 1 and item.id <= 4 then n = n + item.qty end end
    return n
end
local function party_level(slot) return rd(ram.wPartyMons + slot * d.party_struct_size + 33) end
local function battle_hp() return rd(S.wBattleMonHP) * 256 + rd(S.wBattleMonHP + 1) end
local function advance(buttons)
    t.step(buttons or C.idle())
    t.client:frame_end()
    local status = t.client.signals:status()
    assert(not status.failed and not status.handler_error, json.encode(status))
    if catch and not levelup_frame and party_level(catch.slot) >= EVO_LEVEL then
        levelup_frame = frame()
        t.log(string.format("LEVEL_UP slot=%d level=%d frame=%d", catch.slot, party_level(catch.slot), levelup_frame))
    end
end
local function idle(n) for _ = 1, n do advance(C.idle()) end end
local function until_(limit, predicate, buttons, why)
    for i = 1, limit do
        if predicate() then return end
        advance(buttons and buttons(i) or C.idle())
    end
    assert(predicate(), why)
end
local function point() return Hunt.extend_point(play.point(), rd, S) end
local function pace(p, state)
    local target = Forest.PACE[state.target]
    if p.x == target[1] and p.y == target[2] then state.target = 3 - state.target; target = Forest.PACE[state.target] end
    return C.move(p, target)
end
local function yield_buttons(buttons) coroutine.yield(buttons or C.idle()) end
local function new_hunt(mode)
    return Hunt.new({player = "a"}, {driver = driver, step = yield_buttons, rd = rd, symbols = S, mode = mode, log = t.log})
end
-- One RUN battle through the hunt module's run mode (a fresh instance per battle: its
-- terminal is sticky). Returns buttons, and true once the escape has been classified.
local function drive_runner(runner, p)
    local buttons, phase = runner.step(nil, nil, p, frame())
    assert(phase ~= "stuck" and phase ~= "whiteout" and phase ~= "unexpected-battle", "run failed: " .. tostring(phase))
    return buttons, phase == "escaped"
end
local function check_party(p)
    if p.party_hp == 0 then error("RNG: starter fainted (poison from the catch battle)", 0) end
    if p.battle ~= 0 and p.battle ~= 1 then error("unexpected battle state " .. p.battle, 0) end
end

-- ── 1. the walk: battle fixture -> forest park ───────────────────────────────────────────
local function walk_to_forest()
    local walker = Forest.new({player = "a"}, {log = t.log})
    local last
    for _ = 1, WALK_FRAMES do
        local p = play.point()
        local buttons, phase = walker.step(nil, nil, p, frame())
        if phase ~= last then t.log("WALK_PHASE " .. phase); last = phase end
        if phase == "forest-parked" then return end
        advance(buttons)
    end
    error("forest walk timeout", 0)
end

-- ── 2. the hunt: RUN from everything but a target, CATCH the first target ────────────────
local function hunt_target()
    local catcher = new_hunt("catch")
    local runner, state, encounters = nil, {target = 1}, 0
    for _ = 1, HUNT_FRAMES do
        local p = point()
        check_party(p)
        if p.battle == 1 and not runner and not catcher.battle_co then
            encounters = encounters + 1
            assert(encounters <= HUNT_ENCOUNTERS, "RNG: no Caterpie/Weedle caught in " .. HUNT_ENCOUNTERS .. " encounters")
            driver.new_battle()
            local species = rd(S.wEnemyMonSpecies)
            t.log(string.format("HUNT_ENCOUNTER %d species=%02X (%d,%d) balls=%d", encounters, species, p.x, p.y, balls()))
            if not TARGETS[species] then
                t.log(string.format("HUNT_RUN_WRONG_SPECIES species=%02X", species))
                runner = new_hunt("run")
            end
        end
        local buttons
        if runner then
            local escaped
            buttons, escaped = drive_runner(runner, p)
            if escaped then runner = nil end
        elseif p.battle ~= 0 or catcher.battle_co or catcher.outcome then
            local phase
            buttons, phase = catcher.step(nil, nil, p, frame())
            if phase == "caught" then return end
            if phase == "out-of-balls" then error("RNG: ball missed", 0) end
            if phase == "hunt-exhausted" then error("RNG: six target battles without a catch", 0) end
            assert(phase ~= "stuck" and phase ~= "whiteout" and phase ~= "unexpected-battle", "catch failed: " .. tostring(phase))
        elseif p.font_loaded or p.joy_ignore ~= 0 then
            buttons = C.tap("B", frame())
        else
            assert(p.map == Forest.MAP.forest, "left the forest")
            buttons = pace(p, state)
        end
        advance(buttons)
    end
    error("hunt timeout", 0)
end

-- ── 3. stage the experience (instrument; see the header) ─────────────────────────────────
local function exp_for_level(growth, level)
    -- data/growth_rates.asm:15-20 (the rows lua/gen1/boxes.lua carries), 24-bit like the engine
    local rows = {{1, 1, 0, 0, 0}, {3, 4, 10, 0, 30}, {3, 4, 20, 0, 70}, {6, 5, -15, 100, 140}, {4, 5, 0, 0, 0}, {5, 4, 0, 0, 0}}
    local r = assert(rows[growth + 1], "growth rate")
    return (math.floor(r[1] * level ^ 3 / r[2]) + r[3] * level ^ 2 + r[4] * level - r[5]) % 16777216
end
local function stage_exp()
    until_(1800, function() return t.overworld_ok() end, function(i) return C.tap("B", i) end, "no overworld checkpoint after the catch")
    local base = assert(t.parts.rom.base_stats_for(catch.species))
    local want = exp_for_level(base.growth_rate, EVO_LEVEL) - 1
    local at = ram.wPartyMons + catch.slot * d.party_struct_size + 14
    local before = assert(reads.read_party())[catch.slot + 1]
    assert(before.level < EVO_LEVEL and before.exp < want, "catch already at or past the evolution level")
    memory.write_u8(at, math.floor(want / 65536) % 256, "System Bus")
    memory.write_u8(at + 1, math.floor(want / 256) % 256, "System Bus")
    memory.write_u8(at + 2, want % 256, "System Bus")
    local after = assert(reads.read_party())[catch.slot + 1]
    assert(after.exp == want and after.level == before.level and reads.key(after) == catch.key, "exp staging changed more than exp")
    t.log(string.format("EXP_STAGED slot=%d species=%02X growth=%d exp=%d->%d level=%d key=%s",
        catch.slot, catch.species, base.growth_rate, before.exp, want, after.level, catch.key))
end

-- ── 4. the level-up battle: catch switched in, Tackles a cocoon down; A (B = cancel) after ─
local function level_battle()
    local btn = CANCEL and "B" or "A"
    local function mash(n) for i = 1, n do yield_buttons(C.tap(btn, i)) end end
    -- The next battle menu, advancing text with A -- never B: Evolution_CheckForCancel
    -- (evolution.asm:141-158) reads hJoy5 for PAD_B while wIsInBattle is still 1, because
    -- EndOfBattle clears it only AFTER the evolution (end_of_battle.asm:42-50). The cancel
    -- variant taps B for the same reason.
    local function wait_menu(budget)
        local used = 0
        while used < budget do
            local r = driver.wait_menu(240)
            used = used + r.frames
            if r.ok then return "menu" end
            if r.why == "battle_over" then return "battle_over" end
            mash(32); used = used + 32
        end
        return "timeout"
    end
    local function plan()
        local m = wait_menu(1800)
        if m ~= "menu" then return m end
        local sw = driver.switch_to(catch.slot, 900)
        t.log("LEVEL_SWITCH slot=" .. catch.slot .. " -> " .. tostring(sw.why))
        if not sw.ok then return sw.why == "battle_over" and "battle_over" or "stuck" end
        for turn = 1, LEVEL_TURNS do
            m = wait_menu(6000)    -- the last one spans the KO text, the level-up box and the evolution
            if m ~= "menu" then return m end
            if battle_hp() == 0 then return "catch-koed" end
            local c = driver.choose("FIGHT")
            if not c.ok then return c.why == "battle_over" and "battle_over" or "stuck" end
            local mv = driver.commit_move(1, 900)
            t.log(string.format("LEVEL_TURN %d foe_hp=%d -> %s", turn, mv.hp_after and mv.hp_after.enemy or -1, tostring(mv.why)))
            if mv.why == "battle_over" then return "battle_over" end
            if mv.why == "player_fainted" or mv.why == "party_menu" then return "catch-koed" end
        end
        return "stuck"
    end
    local state, encounters, co, runner = {target = 1}, 0, nil, nil
    for _ = 1, LEVEL_FRAMES do
        local p = point()
        check_party(p)
        if p.battle == 1 and not co and not runner then
            encounters = encounters + 1
            assert(encounters <= LEVEL_ENCOUNTERS, "RNG: no Kakuna/Metapod in " .. LEVEL_ENCOUNTERS .. " encounters")
            driver.new_battle()
            local species = rd(S.wEnemyMonSpecies)
            t.log(string.format("LEVEL_ENCOUNTER %d species=%02X (%d,%d)", encounters, species, p.x, p.y))
            if COCOONS[species] then co = coroutine.create(plan)
            else t.log(string.format("LEVEL_RUN_WRONG_SPECIES species=%02X", species)); runner = new_hunt("run") end
        end
        local buttons = C.idle()
        if runner then
            local escaped
            buttons, escaped = drive_runner(runner, p)
            if escaped then runner = nil end
        elseif co then
            local ok, res = coroutine.resume(co)
            assert(ok, "level battle plan error: " .. tostring(res))
            if coroutine.status(co) == "dead" then
                co = nil
                t.log("LEVEL_OUTCOME " .. tostring(res))
                if res == "catch-koed" then error("RNG: the catch fainted before the KO", 0) end
                assert(res == "battle_over", "level battle failed: " .. tostring(res))
            else
                buttons = res or C.idle()
            end
        elseif p.battle ~= 0 then
            buttons = C.tap(btn, frame())          -- never reached after battle_over; kept for a late text box
        elseif levelup_frame then
            -- the battle is over (wIsInBattle 0, so the evolution is too): settle, then drain
            until_(3000, function() return t.overworld_ok() end, function(i) return C.tap("B", i) end, "no checkpoint after the evolution")
            idle(120)
            return encounters
        elseif p.font_loaded or p.joy_ignore ~= 0 then
            buttons = C.tap("B", frame())
        else
            assert(p.map == Forest.MAP.forest, "left the forest")
            buttons = pace(p, state)
        end
        advance(buttons)
    end
    error("level-up battle timeout", 0)
end

-- ── the gate ─────────────────────────────────────────────────────────────────────────────
local function run()
    assert(t.title == "red" or t.title == "blue", "R/B only: no Yellow forest walker (see the header)")
    local initial = assert(reads.read_party())
    assert(#initial >= 1 and #initial < 6, "fixture needs a free party slot")
    local p0 = play.point()
    assert(p0.map == 12 and p0.x == 10 and p0.y == 35, "wrong battle fixture parking tile")
    assert(balls() == 1, "fixture must have exactly one ball")
    assert(S.EvolutionAfterBattle == S.TryEvolvingMon + 14 and rom.TryEvolvingMon.addr == S.TryEvolvingMon,
           "evolution symbols disagree with the profile")
    hook("TryEvolvingMon", 0x21)          -- ld hl, wCanEvolveFlags       (evos_moves.asm:2-3)
    hook("EvolutionAfterBattle", 0xF0)    -- ldh a, [hTileAnimations]     (:13-14)
    hook("CancelledEvolution", 0x21)      -- ld hl, StoppedEvolvingText   (:292-293)
    t.client:start()
    t.online = true
    until_(600, function() return t.client.hello_sent end, nil, "loopback hello was not sent")
    driver = Driver.new({step = yield_buttons, u8 = rd, addresses = S,
        sites = {display_battle_menu = rom.DisplayBattleMenu.addr, move_selection_menu = rom.MoveSelectionMenu.addr,
                 select_enemy_move = rom.SelectEnemyMove.addr, execute_player_move = rom.ExecutePlayerMove.addr,
                 execute_enemy_move = rom.ExecuteEnemyMove.addr}})

    walk_to_forest()
    t.log(string.format("FOREST_PARKED frame=%d", frame()))
    hunt_target()
    idle(120)
    local party = assert(reads.read_party())
    assert(#party == #initial + 1, "party did not grow by one")
    local mon = party[#party]
    assert(TARGETS[mon.species], string.format("caught species %02X is not a target", mon.species))
    assert(#tx.captures == 1 and tx.captures[1].msg.key == reads.key(mon), "expected exactly one capture TX naming the catch")
    catch = {slot = mon.slot, key = reads.key(mon), species = mon.species, nick = mon.nickname, level = mon.level}
    t.log(string.format("CAUGHT %s slot=%d key=%s level=%d nick=%s frame=%d", TARGETS[mon.species].name,
        catch.slot, catch.key, catch.level, catch.nick, tx.captures[1].frame))
    stage_exp()
    local encounters = level_battle()

    -- ── verdict ──
    assert(levelup_frame, "the catch never reached level " .. EVO_LEVEL)
    assert(hits.EvolutionAfterBattle >= 1, "EvolutionAfterBattle never ran")
    assert(hits.TryEvolvingMon == 0, "TryEvolvingMon ran on the level-up path")
    assert(#tx.captures == 1, "a second capture went out")
    local after = assert(reads.read_party())[catch.slot + 1]
    local want = TARGETS[catch.species]
    local site = json.decode(assert(io.open(t.ROOT .. "/data/games/gen1_rby/engine_signals.json", "rb")):read("*a")).titles[t.title].sites.evolve
    if CANCEL then
        assert(hits.CancelledEvolution >= 1, "B did not cancel: CancelledEvolution never ran (cancel window not reachable by scripted input)")
        assert(#sig.evolve == 0 and #tx.key_changes == 0, "a cancelled evolution produced an evolve signal or key_change")
        assert(after.species == catch.species and reads.key(after) == catch.key and after.level == EVO_LEVEL,
               "a cancelled evolution changed the mon")
        t.log(string.format("EVOLUTION_RECEIPT variant=cancel catch_frame=%d levelup_frame=%d after_battle_hits=%d cancelled_hits=%d try_hits=%d evolve_signals=0 key_changes=0 species=%02X level=%d key=%s encounters=%d",
            tx.captures[1].frame, levelup_frame, hits.EvolutionAfterBattle, hits.CancelledEvolution, hits.TryEvolvingMon,
            after.species, after.level, catch.key, encounters))
        t.check("B during the animation cancelled the evolution; no evolve signal, no key_change", true)
        return
    end
    assert(hits.CancelledEvolution == 0, "the evolution was cancelled")
    assert(#sig.evolve == 1, "expected exactly one evolve signal, got " .. #sig.evolve)
    assert(sig.evolve[1].pc == site.address and sig.evolve[1].which == catch.slot, "evolve signal PC/slot differ from the pinned site")
    assert(#tx.key_changes == 1, "expected exactly one key_change, got " .. #tx.key_changes)
    local kc = tx.key_changes[1].msg
    assert(kc.reason == "evolution", "wrong key_change reason")
    assert(kc.old_key == catch.key and kc.new_key == reads.key(after), "key_change keys differ from the cartridge")
    assert(kc.old_key:sub(1, 10) == kc.new_key:sub(1, 10), "DV:OT prefix changed across the evolution")
    assert(kc.new_species == want.evolved and after.species == want.evolved, "wrong evolved species")
    assert(t.parts.rom.natdex(kc.new_species) == want.dex, "evolved species is not dex " .. want.dex)
    assert(after.level == EVO_LEVEL and after.nickname == catch.nick, "level/nickname after the evolution")
    assert(tx.key_changes[1].frame > tx.captures[1].frame and sig.evolve[1].frame >= levelup_frame, "receipt order")
    t.log(string.format("EVOLUTION_RECEIPT variant=levelup catch_frame=%d levelup_frame=%d evolve_signal_frame=%d key_change_frame=%d after_battle_hits=%d try_hits=%d cancelled_hits=%d old=%s new=%s species=%02X dex=%d level=%d nick=%s encounters=%d",
        tx.captures[1].frame, levelup_frame, sig.evolve[1].frame, tx.key_changes[1].frame, hits.EvolutionAfterBattle,
        hits.TryEvolvingMon, hits.CancelledEvolution, kc.old_key, kc.new_key, kc.new_species, want.dex, after.level, after.nickname, encounters))
    t.check("one key_change reason=evolution from the after-battle path; TryEvolvingMon never ran", true)
end
local ok, err = pcall(run)
if not ok then t.check("level-up evolution physical route", false, err) end
if driver then driver.close() end
for _, id in ipairs(hooks) do event.unregisterbyid(id) end
pcall(function() t.client:stop() end)
local extra
if not ok then extra = tostring(err) end
t.finish(extra)
