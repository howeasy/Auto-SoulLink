-- lua/tests/test_gen1_rand_lab_gate.lua — PHYSICAL: a RANDOMIZED pureRGB cartridge hands out
-- what its OWN tables say. Cold boot -> NEW GAME -> bedroom -> Oak's lab -> a FIXED ball (x=8,
-- the R/B lab driver's player-"a" ball; Bulbasaur on a clean cartridge) -> the rival battle,
-- ordinary buttons only. At the first battle frame where the enemy party is complete (the
-- battle mon equals the first party mon, i.e. LoadEnemyMonData ran after ReadTrainer) it prints
-- the starter, the rival's party, wTrainerNo and wRivalStarter as one RAND_OBS line and stops.
-- tests/live/test_gen1_rand_gates.py decodes the OUTPUT ROM's StarterOffsets and RIVAL1 trainer
-- records and compares. The battle is never fought: the lab driver's deliberate Growl loss
-- assumes a vanilla moveset, and the outcome proves nothing about the tables.
-- Result file: patch/build/test_gen1_rand_lab_gate_result.txt
-- Lane: run_gb_gate.py --rom purered_rand_cold (cold: no battery save).
local G = dofile((SLINK_ROOT or os.getenv("SLINK_ROOT")) .. "/lua/tests/gen1_gate.lua")
local t = G.start("test_gen1_rand_lab_gate", { no_boot = true })
local fmt = string.format
local P = dofile(t.ROOT .. "/lua/tests/gen1_scripted_play.lua")
local json, ram, d = t.parts.json, t.parts.profile.ram, t.parts.profile.derived
local rd = t.Entry.harness_bus_u8()
local MAX_FRAMES = 120000
local BALL_X = 8

local safety = dofile(t.ROOT .. "/lua/gen1_write_safety.lua")
local ws = json.decode(assert(io.open(t.checkpoint_path, "rb")):read("*a"))[t.title]
local function overworld_ok() return safety.check(ws, t.deps) == true end

t.log(fmt("ADMITTED title=%s pack=%s kind=%s", t.title, t.pack, t.kind))
t.check("admitted as a randomized pure cartridge (kind rand)", t.kind == "rand", t.kind)

local play = P.new(t.ROOT, t.title, "a", { log = t.log })   -- player "a" = the ball at x=8
local bok, berr = pcall(function() return play.boot(t.step, overworld_ok) end)
t.check("NEW GAME reached the bedroom", bok, berr)
if not bok then t.finish("boot failed") end

-- The lab driver, stepped here rather than through play.run: play.run returns only at the
-- driver's terminal (lab-loss-complete), which needs Growl in slot 2.
local E = play.expected
local driver = dofile(t.ROOT .. "/lua/tests/" .. play.modules.lab.file).new(E)
local handshake = { ready = true, run_id = E.run_id, player = E.player, rom_sha1 = E.rom_sha1,
                    context_generation = 1, physical_instance = E.physical_instance }
local status = { observation_loop = true,
                 context = { context_generation = 1, physical_instance = E.physical_instance },
                 host = { owner_id = E.physical_instance, held = false },
                 runtime = { connected = true, session_state = "admitted", failed = false } }

local function enemy_party()
    local n = rd(ram.wEnemyPartyCount)
    if n < 1 or n > d.party_capacity then return nil end
    local mons = {}
    for i = 0, n - 1 do
        local at = ram.wEnemyMons + i * d.party_struct_size
        mons[#mons + 1] = { species = rd(at), level = rd(at + 33), list_species = rd(ram.wEnemyPartySpecies + i) }
    end
    return mons
end

local obs, last_phase = nil, nil
local rok, rerr = pcall(function()
    for _ = 1, MAX_FRAMES do
        local point = play.point()
        local buttons, phase = driver.step(handshake, status, point, emu.framecount())
        if phase ~= last_phase then
            t.log(fmt("  phase lab: %s @%d", phase, emu.framecount()))
            last_phase = phase
        end
        if point.battle ~= 0 and point.party_count >= 1 then
            local mons = enemy_party()
            if mons and mons[1].species ~= 0 and rd(ram.wEnemyMonSpecies) == mons[1].species then
                -- the party struct opens with its species byte (no wPartyMon1Species in the profile)
                obs = { ball_x = BALL_X, starter = rd(ram.wPartyMons), starter_level = rd(ram.wPartyMon1Level),
                        party_count = point.party_count, opponent = point.opponent, battle = point.battle,
                        trainer_class = rd(ram.wTrainerClass), trainer_no = rd(ram.wTrainerNo),
                        rival_starter = rd(assert(play.symbols.wRivalStarter, "no symbol wRivalStarter")),
                        enemy = mons, frame = emu.framecount() }
                return
            end
        end
        t.step(buttons)
    end
    error("no rival battle within " .. MAX_FRAMES .. " frames", 0)
end)
t.check("lab route reached the rival battle", rok, rerr)
if not rok then
    client.screenshot(t.ROOT .. "/patch/build/test_gen1_rand_lab_gate_fail.png")
    t.log("POINT " .. json.encode(play.point()))
    t.finish("route failed")
end
t.check("first battle is lab Rival1", obs.opponent == t.facts.TRAINER.OPP_RIVAL1, obs.opponent)
t.check("one starter in the party", obs.party_count == 1, obs.party_count)
for i, m in ipairs(obs.enemy) do
    t.check(fmt("enemy mon %d: species list agrees with its struct", i), m.list_species == m.species,
            fmt("%02X vs %02X", m.list_species, m.species))
end
t.log("RAND_OBS " .. json.encode(obs))

-- ── optional leg: Route 1's first wild encounter ─────────────────────────────────────────
-- Win or lose the rival battle by mashing A (FIGHT, move 1; any outcome is fine, the lab
-- script heals a loss), let the lab driver play the rival's exit to SCRIPT_OAKSLAB_NOOP
-- (never stepping it AT noop: its terminal asserts the deliberate loss), then the parcel
-- driver's own lab_exit/pallet_north/route_north waypoints into Route 1's grass. The wild
-- battle mon is sampled when it equals wCurOpponent (the wild species); the driver's RUN
-- logic is never reached. A failure here is reported as WILD_FAIL, not a gate failure.
local C = dofile(t.ROOT .. "/lua/tests/gen1_inputs_common.lua").with_facts(t.facts)
local NOOP = t.facts.SCRIPT.OAKSLAB.NOOP
local wild
local wok, werr = pcall(function()
    local point
    for _ = 1, 30000 do
        point = play.point()
        if point.battle == 0 then break end
        t.step(C.tap("A", emu.framecount()))
    end
    assert(point.battle == 0, "rival battle did not end in 30000 frames of A")
    t.log(fmt("RIVAL_BATTLE_OVER result=%d party_hp=%d @%d", point.battle_result, point.party_hp, emu.framecount()))
    for _ = 1, 30000 do
        point = play.point()
        if point.lab_script == NOOP and point.joy_ignore == 0 and not point.npc_moving then break end
        local buttons, phase = driver.step(handshake, status, point, emu.framecount())
        if phase ~= last_phase then t.log(fmt("  phase lab: %s @%d", phase, emu.framecount())); last_phase = phase end
        t.step(buttons)
    end
    assert(point.lab_script == NOOP, "lab script did not reach NOOP after the battle")
    local parcel = dofile(t.ROOT .. "/lua/tests/gen1_rb_parcel_inputs.lua").new(E)
    last_phase = nil
    for _ = 1, 60000 do
        point = play.point()
        -- sampled at the drawn battle menu (the parcel driver's own oracle): LoadEnemyMonData
        -- has long finished, so nothing here is the rival battle's stale bytes
        if point.map == t.facts.MAP.ROUTE_1 and point.battle == 1 and point.text_box == t.facts.MENU.BATTLE.template then
            wild = { map = point.map, x = point.x, y = point.y, species = rd(ram.wEnemyMonSpecies),
                     species2 = rd(ram.wEnemyMonSpecies2), opponent = point.opponent,
                     level = rd(ram.wEnemyMonLevel), battle_type = point.battle_type, frame = emu.framecount() }
            return
        end
        local buttons, phase = parcel.step(handshake, status, point, emu.framecount())
        if phase ~= last_phase then t.log(fmt("  phase parcel: %s @%d", phase, emu.framecount())); last_phase = phase end
        t.step(buttons)
    end
    error("no Route 1 wild battle within 60000 frames", 0)
end)
if wok then t.log("RAND_WILD " .. json.encode(wild))
else t.log("WILD_FAIL " .. tostring(werr)); t.log("POINT " .. json.encode(play.point())) end
t.finish()
