-- gen3_fixture_from_state.lua — build FireRed party fixtures (card gen3-P4-C4-F).
--
-- tests/fixtures/gen3/firered_town.sav is PRE-STARTER (party=0), so no party/battle scenario can
-- run from it. lua/tests/gen3_scripted_play.lua's `route1_catch` leg already proves a party of 2
-- (starter + one caught Route 1 mon) reachable; this file cold-boots battery saves derived from
-- that (no savestate ANYWHERE, per the coordinator's 2026-09-23 direction) and walks with
-- scripted normal inputs, fleeing every incidental wild encounter with the RUN action (never
-- FIGHT). It dofiles gen3_scripted_play.lua for its already-verified PATHS/DEST/play binding
-- rather than re-deriving any of it (that file is owned by another worker card and is read-only
-- here); the two small flee helpers below are built from its own EXPORTED raw witnesses
-- (BATTLER_CTRL_ADDR, HANDLE_INPUT_CHOOSE_ACTION, ACTION_CURSOR_ADDR), not a duplicate of its
-- internal FIGHT-only battle logic.
--
-- WHY COLD BOOT, NEVER A SAVESTATE (PHYSICAL 2026-09-23, recorded instrument limit): an earlier
-- version of this file resumed lua/tests/gen3_scripted_play.lua's own `slink_fr_route1_catch.
-- State` savestate directly and walked a SECOND scripted leg onto it to reach a town position.
-- That reproducibly left EmuHawk exiting with no RESULT line (no Lua error, no Windows crash
-- record) a few hundred frames after save_via_menu's own "slot-complete" phase, at every
-- destination tried -- every other variable ruled out one at a time. A cold boot -> CONTINUE at
-- the same tiles (`boot-check`) never once reproduced it. So every kind here cold-boots a
-- BATTERY (the same per-run SaveRAM + CONTINUE plumbing `gen3_fixtures.py boot-check` uses)
-- instead.
--
-- WHY TWO SHORT SESSIONS, NOT ONE LONG ONE (also PHYSICAL 2026-09-23): a cold-boot session that
-- walks Route 1 -> Viridian -> heals -> walks ALL the way back to Route 1 before saving (~9500-
-- 12000 frames) reproduced the SAME silent exit -- with RUN absorption, with FIGHT absorption
-- (a temporary probe, since ruled out), and with a verified-clean process/orphan state, so
-- neither the RUN-vs-FIGHT question nor a leftover process was the variable. A SHORT cold-boot
-- session (walk straight from Route 1 to Viridian, no heal, ~2700 frames) never once reproduced
-- it. So the round trip is split into two separate cold-boot sessions at the natural midpoint,
-- Viridian itself, each roughly half the original length.
--
-- Two kinds (SLINK_GEN3_FIXTURE_KIND), BUILT IN THIS ORDER (town first, battle from town's own
-- output) by the caller (tools/gen3_fixtures.py):
--
--   town    Cold-boots a battery standing at Route 1's grass origin (12,37) with the
--           post-route1_catch party, walks north to the Viridian Pokemon Center (fleeing any
--           encounter), heals the WHOLE party, walks back out to ViridianCity's own south tile
--           (24,39, non-grass town ground, fleeing again), and saves there.
--
--   battle  Cold-boots "town"'s own healed output (already standing at (24,39)), walks the
--           short leg back south to Route 1's grass origin (fleeing any encounter), and saves
--           there. Healthy party, tall grass, a step yields an encounter.
--
-- Environment: SLINK_ROOT, SLINK_GEN3_CHECKPOINT, SLINK_GEN3_TITLE=firered (gen3_boot_check.lua),
-- SLINK_GEN3_FIXTURE_KIND (battle|town). The caller is responsible for seeding the per-run
-- SaveRAM directory with the right source battery before launch (the accepted-but-unhealed
-- battle fixture for "town", that kind's own healed output for "battle") -- exactly like
-- `boot-check` seeds its own fixture.

local WT = SLINK_ROOT or os.getenv("SLINK_ROOT")
assert(WT, "SLINK_ROOT unset — launch via the gen3 fixture/gate tooling")
local G = dofile(WT .. "/lua/tests/gen3_boot_check.lua")
local SP = dofile(WT .. "/lua/tests/gen3_scripted_play.lua")   -- read-only; dofile only (no run())
local play = SP.play
local Reads = dofile(WT .. "/lua/gen3/reads.lua")
local JSON = dofile(WT .. "/lua/json_codec.lua")
local profile_file = assert(io.open(WT .. "/data/games/gen3_frlg/profile.json", "rb"))
local profile = assert(JSON.decode(profile_file:read("a"))).titles.firered
profile_file:close()
local function read_bytes(addr, count)
    local bytes = {}
    for i = 1, count do bytes[i] = memory.read_u8(addr + i - 1) end
    return bytes
end
local reader = Reads.new(profile, {
    read_u8 = function(a) return memory.read_u8(a) end,
    read_u32 = function(a) return memory.read_u32_le(a) end,
    read_bytes = read_bytes,
})

local function party_report()
    local mons, why = reader.read_party()
    if not mons then return nil, why end
    local rows = {}
    for i, m in ipairs(mons) do
        rows[i] = string.format("[%d] species=%d level=%d hp=%d/%d", i, m.species, m.level,
                                m.hp, m.max_hp)
    end
    return mons, table.concat(rows, " ")
end

local function party_fully_healed()
    local mons = reader.read_party()
    if not mons then return false end
    for _, m in ipairs(mons) do
        if m.max_hp > 0 and m.hp < m.max_hp then return false end
    end
    return true
end

--- Every party mon readable and none fainted -- the one check both kinds share right after
--- cold-booting to the field.
local function check_party_alive(label)
    local mons, why = party_report()
    if not mons then
        G.finish(false, label .. ": party unreadable: " .. tostring(why)); return nil
    end
    if #mons < 2 then
        G.finish(false, string.format("%s: party has %d mon(s); need >= 2", label, #mons))
        return nil
    end
    for _, m in ipairs(mons) do
        if m.hp == 0 then
            G.finish(false, label .. ": a party mon is fainted (hp=0)")
            return nil
        end
    end
    return mons, why
end

--- Combined map id the way the bound `play.map` reports it (H.map: group*256+num,
--- gen3_scripted_play.lua). Built from a DEST entry so it is never re-typed by hand.
local function combined_map(dest) return dest.group * 256 + dest.num end
local ROUTE1_MAP = combined_map(SP.DEST.route1_south)
local PALLET_MAP = combined_map(SP.DEST.pallet_north)
local VIRIDIAN_MAP = combined_map(SP.DEST.viridian_south)
local BATTLE_TARGET = { group = SP.DEST.route1_south.group, num = SP.DEST.route1_south.num,
                        x = SP.GRASS_ORIGIN[1], y = SP.GRASS_ORIGIN[2] }
local TOWN_TARGET = SP.DEST.viridian_south   -- {group=3, num=1, x=24, y=39}: ViridianCity's own
                                              -- south tile, non-grass town ground.

--- Exact-tile check (map AND coordinates), independent of play.map's combined encoding.
local function at_dest(cp, dest)
    local g, n = G.map(cp)
    local x, y = G.pos(cp)
    return g == dest.group and n == dest.num and x == dest.x and y == dest.y
end

--- Same stability-settle-then-check shape as gen3_scripted_play.lua's own (unexported)
--- verify_destination -- but calling THIS file's own G.finish, never SP's.
---
--- WHY THIS EXISTS (coordinator finding, 2026-09-23, PHYSICAL): `dofile` re-executes
--- gen3_boot_check.lua fresh for every caller, so gen3_scripted_play.lua's own `local G =
--- dofile(...)` is a SEPARATE module instance from this file's `G` -- its own `out` upvalue,
--- never opened by G.open() here. Its exported `verify_destination` (and anything that calls
--- it, like `warp_to`) calls G.finish(false, ...) on a mismatch using THAT instance: the
--- RESULT line goes to console.log only (M.log: "if out then ... end", and `out` is nil), but
--- client.exitCode(1) + client.exit() still fire, killing the whole EmuHawk process with a
--- clean exit code and NO trace in the file this driver actually reads. That is the exact
--- "no RESULT line, returncode 1, no crash record" signature every failed run showed -- not a
--- host crash, our OWN finish(false) path, just logged somewhere unread. So every destination
--- check and warp in this file uses ITS OWN verify/warp (below), never SP.verify_destination or
--- SP.warp_to, and the two indoor play.follow calls (heal_whole_party, "heal_center_to_door")
--- are routed through follow_running instead -- same reasoning: play.follow's own failure path
--- calls H.finish, which is SP's G.finish too (gen3_scripted_play.lua's own H table binds it
--- directly).
local function my_verify_destination(cp, label, dest)
    local stable = 0
    for _ = 1, 120 do
        if at_dest(cp, dest) then
            stable = stable + 1
            if stable >= 4 then break end
        else
            stable = 0
        end
        G.advance()
    end
    if at_dest(cp, dest) then return true end
    local g, n = G.map(cp)
    local x, y = G.pos(cp)
    G.shot("stuck")
    G.finish(false, string.format("%s: destination_mismatch: expected %d.%d (%d,%d), got "
             .. "%s.%s (%s,%s)", label, dest.group, dest.num, dest.x, dest.y,
             tostring(g), tostring(n), tostring(x), tostring(y)))
    return false
end


-- ── flee machinery: RUN from every incidental battle, never FIGHT ──────────────────────────────
--
-- FRLG battle action menu is a 2x2 grid (gen3_scripted_play.lua:91 "0 FIGHT, 1 BAG, 2 POKeMON,
-- 3 RUN"; ACTION_FIGHT/ACTION_BAG=0/1 are its own exported constants, RUN completes the pair).
-- Reconstructed from that file's own EXPORTED raw witnesses (BATTLER_CTRL_ADDR,
-- HANDLE_INPUT_CHOOSE_ACTION, ACTION_CURSOR_ADDR) rather than a new address guess -- these are
-- the same reads its verify_fight_cursor makes, just steered to the opposite corner of the grid.

local ACTION_RUN = 3
local function action_menu_up()
    return memory.read_u32_le(SP.BATTLER_CTRL_ADDR) == SP.HANDLE_INPUT_CHOOSE_ACTION
end
local function action_cursor() return memory.read_u8(SP.ACTION_CURSOR_ADDR) end

--- One flee ATTEMPT: wait for the action menu, steer to RUN, confirm. Escaping a wild battle in
--- FRLG is a speed-based chance (not guaranteed even on a second try), so this does not itself
--- guarantee the battle ends -- flee_battle below loops it. Returns false only on a STRUCTURAL
--- failure (the action menu never appears at all -- e.g. a forced party switch after a faint,
--- which this driver does not handle) and has already called G.finish.
local function attempt_run(cp, label)
    local up = false
    for i = 1, 600 do
        if not play.in_battle(cp) then return true end
        if action_menu_up() then up = true; break end
        if i % 2 == 0 then joypad.set({ A = true }) else joypad.set({}) end
        G.advance()
    end
    joypad.set({})
    if not up then
        if not play.in_battle(cp) then return true end
        G.shot("stuck")
        G.finish(false, label .. ": the battle action menu never came up while fleeing (a mon "
                     .. "may have fainted, forcing a party switch this driver does not handle)")
        return false
    end
    for _ = 1, 4 do
        local c = action_cursor()
        if c == ACTION_RUN then break end
        if c % 2 == 0 then G.tap("Right", 3, 20) end
        if c < 2 then G.tap("Down", 3, 20) end
    end
    if action_cursor() ~= ACTION_RUN then
        G.shot("stuck")
        G.finish(false, string.format("%s: could not steer the action cursor to RUN (reads %d)",
                 label, action_cursor()))
        return false
    end
    G.tap("A", 3, 20)
    return true
end

--- Flee a live battle with normal inputs -- RUN, never FIGHT (card gen3-P4-C4-F coordinator
--- instruction: handle incidental wild encounters by running). Bounded at 12 rounds; Route 1's
--- own early-route wildlife is low level and this party is not slower than all of it, but a
--- failed attempt is not a bug, just a retry.
local function flee_battle(cp, label)
    for round = 1, 12 do
        if not play.in_battle(cp) then return true end
        G.phase("flee", string.format("%s: round %d", label, round))
        if not attempt_run(cp, label) then return false end
        -- Clear "Can't escape!"/"Got away safely!" and land back on the NEXT action menu (or
        -- the overworld, if the escape succeeded) before the outer loop re-checks in_battle.
        play.mash_a(90, function() return not play.in_battle(cp) or action_menu_up() end)
    end
    if play.in_battle(cp) then
        G.shot("stuck")
        G.finish(false, label .. ": could not flee after repeated attempts")
        return false
    end
    return true
end

--- One directional step that flees (never fights) any battle it lands in, retrying the SAME
--- step until it genuinely lands (want=nil, matching play.follow's own "any movement counts"
--- convention -- a ledge hop still makes progress). Battles never move the player, so a step
--- that lands in one has still made its own progress; this only re-presses when the position
--- check itself says otherwise.
local function step_and_flee(cp, dir, label)
    local start_map = play.map(cp)
    for _ = 1, 8 do
        local moved, why = play.step(cp, dir, start_map, nil, false)
        if moved then
            if play.in_battle(cp) and not flee_battle(cp, label) then return false end
            return true
        end
        if why == "in_battle" then
            if not flee_battle(cp, label) then return false end
        else
            G.shot("stuck")
            G.finish(false, string.format("%s: step %s stalled (%s) at %s", label, dir,
                                          tostring(why), play.at(cp)))
            return false
        end
    end
    G.finish(false, label .. ": step " .. dir .. " never completed after repeated flee attempts")
    return false
end

--- play.follow's own shape (start-tile wait, iterate a named PATHS entry's direction list, stop
--- early on a map change), but stepping through step_and_flee instead of play.follow's own
--- FIGHT-only absorption -- gen3_scripted_play.lua's `opts.battle` is bound once, at that file's
--- own construction, to fight (never run), and is not something this file can override per
--- call; reusing play.follow on a grass-adjacent path would fight every incidental encounter.
local function follow_running(cp, path_name, label)
    local path = assert(SP.PATHS[path_name], "no PATHS entry " .. tostring(path_name))
    local start_map = play.map(cp)
    if not play.wait_at(cp, path.from[1], path.from[2], 120) then
        local x, y = G.pos(cp)
        if x ~= path.from[1] or y ~= path.from[2] then
            G.shot("stuck")
            G.finish(false, string.format(
                "%s (%s): start tile (%d,%d) is not the path's from (%d,%d)",
                label, path_name, x, y, path.from[1], path.from[2]))
            return false
        end
    end
    for _, dir in ipairs(path.dirs) do
        if not step_and_flee(cp, dir, label) then return false end
        local now = play.map(cp)
        if now ~= nil and now ~= start_map then return true end
    end
    return true
end

--- Same nurse interaction as gen3_scripted_play.lua's (unexported) heal_at_nurse, generalized
--- to the WHOLE party rather than slot 0 only (this fixture's whole point is a usable, healthy
--- party). Walks in via follow_running, not play.follow -- indoors, so no wild encounter ever
--- actually fires, but play.follow's own failure path calls SP's own G.finish (see
--- my_verify_destination's doc comment above), so it is avoided on principle here too.
local function heal_whole_party(cp, label)
    if not follow_running(cp, "pokecenter_entrance_to_nurse", label) then return false end
    G.tap("Up", 2, 13)              -- face the nurse counter (heal_at_nurse's own shape)
    local _, before = party_report()
    G.phase("heal-start", label .. ": " .. tostring(before))
    local healed = false
    for _ = 1, 120 do
        if party_fully_healed() then healed = true; break end
        G.tap("A", 3, 20)
    end
    if not healed then
        G.shot("stuck")
        local _, why = party_report()
        G.finish(false, label .. ": the nurse never restored the whole party: " .. tostring(why))
        return false
    end
    play.wait_scene_settled(cp, 1800)   -- the "we hope to see you again" bow is scripted
    local _, after = party_report()
    G.phase("healed", label .. ": " .. tostring(after))
    return true
end

--- Cross a map connection/door (play.enter_warp does no battle handling of its own -- it just
--- presses and waits for the map id to change), then flee anything that started right at the
--- crossing, then verify the landing tile. Every warp in this file goes through here so none of
--- them silently skip that defensive check.
local function warp_and_flee(cp, dir, budget, dest, label)
    local ok, why = play.enter_warp(cp, dir, budget)
    if not ok then
        G.finish(false, label .. ": warp_failed: " .. tostring(why)); return false
    end
    if play.in_battle(cp) and not flee_battle(cp, label) then return false end
    return my_verify_destination(cp, label, dest)
end

--- Same shape as gen3_scripted_play.lua's own (unexported) return_to_grass_origin -- using
--- THIS file's own G/step_and_flee throughout, never SP's (see my_verify_destination's doc
--- comment above for why: SP's own version calls SP's own, never-opened G.finish on failure).
local function my_return_to_grass_origin(cp, label)
    -- PHYSICAL 2026-09-23: a post-save row-search drift can land a few tiles south of the grass
    -- square on the same x=12/13 column (observed: (12,37) -> (12,39) after a save-menu retry).
    -- Walk back onto the square first; the loop below only ever expects 0-4 tiles of shuffle.
    do
        local px, py = G.pos(cp)
        if (px == 12 or px == 13) and py > 38 then
            for _ = 1, 10 do
                local _, cy = G.pos(cp)
                if cy <= 38 then break end
                if not step_and_flee(cp, "Up", label) then return false end
            end
        end
    end
    for _ = 1, 4 do
        local px, py = G.pos(cp)
        if px == SP.GRASS_ORIGIN[1] and py == SP.GRASS_ORIGIN[2] then return true end
        local on_square = (px == 12 or px == 13) and (py == 37 or py == 38)
        if not on_square then
            G.shot("stuck")
            G.finish(false, string.format(
                "%s: expected to be on the grass square (12..13,37..38), found %s",
                label, play.at(cp)))
            return false
        end
        if not step_and_flee(cp, px == 13 and "Left" or "Up", label) then return false end
    end
    local px, py = G.pos(cp)
    if px ~= SP.GRASS_ORIGIN[1] or py ~= SP.GRASS_ORIGIN[2] then
        G.finish(false, string.format("%s: never reached the grass origin; at %s",
                 label, play.at(cp)))
        return false
    end
    return true
end

-- Route 1's own north-edge landing tile (PATHS.route1_grass_to_north_edge's own `to`): every
-- stray press save_via_menu's row search can leak to the field is Start/A/B/Down (never
-- Left/Right -- M.save_via_menu's own code taps only those four buttons), so a drift out of
-- Viridian back onto Route 1 always lands somewhere on this same x=12 column.
local ROUTE1_NORTH_EDGE = { group = SP.DEST.route1_south.group, num = SP.DEST.route1_south.num,
                            x = 12, y = 1 }

--- Get back to whichever tile `target` needs from wherever an interrupted save_via_menu attempt
--- left us -- called before the FIRST save attempt and again before every retry, so a drift
--- (PHYSICAL 2026-09-23: a wrong-row fallback landed a stray Down press on the bare field and
--- walked the player clean across a map connection -- observed BOTH directions: Route 1's grass
--- square into Pallet Town while saving "battle", and Viridian back onto Route 1 while saving
--- "town") is corrected instead of silently saved or silently accepted as a mismatch. Flees,
--- never fights, like every other walk here.
local function reach_target(cp, label, target)
    if at_dest(cp, target) then
        return true   -- already exactly where the save needs to happen; nothing to recover
    end
    local m = play.map(cp)
    if m == PALLET_MAP then
        for _ = 1, 25 do
            local _, py = G.pos(cp)
            if py <= 0 then break end
            if not step_and_flee(cp, "Up", label) then return false end
        end
        if not my_verify_destination(cp, label .. " pallet north edge (drift recovery)",
                                     SP.DEST.pallet_north) then return false end
        if not warp_and_flee(cp, "Up", 30, SP.DEST.route1_south,
                             label .. " Pallet->Route1 (drift recovery)") then return false end
        if not follow_running(cp, "route1_south_to_grass_spot", label) then return false end
        m = ROUTE1_MAP
    end
    if m == ROUTE1_MAP then
        if target == TOWN_TARGET and not at_dest(cp, BATTLE_TARGET) then
            -- Only reachable by drifting OUT of Viridian while saving "town": walk back up the
            -- same x=12 column to the crossing and re-enter, rather than all the way down to
            -- the grass square and back (which the drift never actually reaches from here).
            for _ = 1, 45 do
                if at_dest(cp, ROUTE1_NORTH_EDGE) then break end
                if not step_and_flee(cp, "Up", label) then return false end
            end
            if not my_verify_destination(cp, label .. " route1 north edge (drift recovery)",
                                         ROUTE1_NORTH_EDGE) then return false end
            return warp_and_flee(cp, "Up", 30, TOWN_TARGET,
                                 label .. " Route1->Viridian (drift recovery)")
        end
        return my_return_to_grass_origin(cp, label)
    end
    if m == VIRIDIAN_MAP and target == TOWN_TARGET then
        return my_verify_destination(cp, label .. " viridian south (drift recovery)", target)
    end
    G.finish(false, string.format("%s: drifted to an unrecognized map id %s; cannot "
                 .. "recover automatically", label, tostring(m)))
    return false
end

--- Cold-boot -> CONTINUE (the per-run SaveRAM directory is already seeded by the caller) and
--- confirm a live, non-fainted, >=2-mon party.
local function boot_and_check(cp, label)
    local domain, seen = G.flash_domain()
    if not domain then
        G.finish(false, "no flash memory domain; domains: " .. tostring(seen)); return nil
    end
    local seeded = G.save_counter(domain)
    if seeded < 0 then
        G.finish(false, label .. ": the battery is erased at boot -- the source fixture was "
                     .. "not seeded into the per-run SaveRAM directory")
        return nil
    end
    G.phase("seeded", "counter=" .. seeded)
    if not G.boot_to_field(cp, 9000) then
        G.shot("stuck")
        local cb2 = G.pred(cp, "callback2")
        G.finish(false, string.format("%s: never reached the field in 9000 frames "
                     .. "(callback2=%08X)", label, cb2))
        return nil
    end
    local mons, report_or_why = check_party_alive(label)
    if not mons then return nil end
    G.phase("party", report_or_why)
    return domain
end

--- Save via the START menu, retrying (not blindly repeating) through any battle a stray press
--- during the row search triggers, and gate on the final position before trusting the result --
--- playlib's shared, already-proven save driver is never changed here, only re-asked. Recovery
--- from a drift (either direction across the Route1<->Viridian connection) goes through
--- reach_target, which knows the way back for both BATTLE_TARGET and TOWN_TARGET.
---
--- PHYSICAL 2026-09-23: the row search's own stray press can land AFTER the pre-save position
--- check but still land INSIDE the save transaction (save-menu opens at the right tile, the
--- drift happens while hunting for the SAVE row, and the write that follows bakes the drifted
--- position in) -- sok=true from save_via_menu is not proof the SAVED data is at `target`. So
--- the destination is re-checked AFTER every save, and a post-save mismatch is retried exactly
--- like a save failure: recover position, save again (overwriting the bad write), never trusted
--- on the strength of save_via_menu's own verdict alone. 8 attempts, not 3: PHYSICAL 2026-09-23,
--- a drift can chain into a longer row search on the very next attempt (more Down presses, more
--- chances for another stray one), so the budget has to absorb more than one bad attempt in a
--- row -- reach_target's own recovery is unconditional and idempotent, so extra attempts cost
--- time, never correctness.
local function save_at(cp, domain, target, label)
    local sok, before, after, why, post_ok
    for attempt = 1, 8 do
        if not flee_battle(cp, label) then return nil end
        if not at_dest(cp, target) then
            if not reach_target(cp, label, target) then return nil end
        end
        if not at_dest(cp, target) then
            G.finish(false, string.format("%s: attempt %d not at the save target (%s)",
                     label, attempt, play.at(cp)))
            return nil
        end
        G.phase("pre-save-pos", string.format("%s: attempt %d at %s map=%s", label, attempt,
                                              play.at(cp), tostring(play.map(cp))))
        sok, before, after, why = G.save_via_menu(cp, domain)
        if sok then
            post_ok = at_dest(cp, target)
            if post_ok then break end
            G.phase("save-drift", string.format(
                "%s: attempt %d saved but drifted post-save to %s map=%s; retrying",
                label, attempt, play.at(cp), tostring(play.map(cp))))
        else
            G.phase("save-retry", string.format("%s: attempt %d failed (%s)", label, attempt,
                                                tostring(why)))
        end
    end
    if not sok then
        G.finish(false, string.format("%s: in-game save failed (%d -> %d): %s", label,
                                      before, after, tostring(why)))
        return nil
    end
    if not post_ok then
        G.finish(false, string.format(
            "%s: saved but never landed on target after 8 attempts (last: %s map=%s)",
            label, play.at(cp), tostring(play.map(cp))))
        return nil
    end
    if not my_verify_destination(cp, label .. " final", target) then return nil end
    return before, after
end

-- ── "town": cold-boot the accepted-but-unhealed source, heal at Viridian, save AT Viridian ──────
--
-- PHYSICAL 2026-09-23: the original single-session design (cold-boot -> heal -> walk ALL the
-- way back to Route 1 -> save, ~9500-12000 frames) reproducibly left EmuHawk exiting with no
-- RESULT line right after save_via_menu's own "slot-complete" phase -- with FIGHT absorption,
-- with RUN absorption, and with a verified-clean process/orphan state, so neither RUN-vs-FIGHT
-- nor a leftover process was the variable. A SHORT cold-boot session (walk straight to
-- Viridian, no heal, ~2700 frames) never once reproduced it. So the heal-and-return round trip
-- is split into two SEPARATE cold-boot sessions at the natural midpoint -- Viridian itself --
-- each roughly half the original length: "town" heals and saves AT Viridian (this function);
-- "battle" (below) cold-boots town's own output and walks the short leg back to Route 1.

local function run_town(cp)
    local label = "fixture_from_state_town"
    local domain = boot_and_check(cp, label)
    if not domain then return end

    if not party_fully_healed() then
        if not at_dest(cp, TOWN_TARGET) then
            if not my_verify_destination(cp, label .. " start", BATTLE_TARGET) then return end
            if not follow_running(cp, "route1_grass_to_north_edge", label) then return end
            if not warp_and_flee(cp, "Up", 30, SP.DEST.viridian_south,
                                 label .. " Route1->Viridian") then return end
        end
        if not follow_running(cp, "route1_edge_to_pokecenter_door", label) then return end
        if not warp_and_flee(cp, "Up", 30, SP.DEST.center,
                             label .. " Center door") then return end
        if not heal_whole_party(cp, label) then return end

        if not follow_running(cp, "heal_center_to_door", label) then return end
        if not warp_and_flee(cp, "Down", 30, SP.DEST.center_exit,
                             label .. " Center exit") then return end
        if not follow_running(cp, "pokecenter_door_to_route1_edge", label) then return end
    end
    if not my_verify_destination(cp, label .. " healed position", TOWN_TARGET) then return end
    G.phase("town-reached", play.at(cp))

    local before, after = save_at(cp, domain, TOWN_TARGET, label)
    if not before then return end
    local _, final_report = party_report()
    G.idle(60)
    G.finish(true, string.format("counter %d -> %d party=%s", before, after,
                                 tostring(final_report)))
end

-- ── "battle": cold-boot "town"'s own healed output, walk the short leg back, save ───────────────

local function run_battle(cp)
    local label = "fixture_from_state_battle"
    local domain = boot_and_check(cp, label)
    if not domain then return end
    if not my_verify_destination(cp, label .. " start", TOWN_TARGET) then return end

    if not warp_and_flee(cp, "Down", 30, SP.DEST.route1_north,
                         label .. " Viridian->Route1") then return end
    if not follow_running(cp, "route1_north_to_south_edge", label) then return end
    if not follow_running(cp, "route1_south_to_grass_spot", label) then return end
    if not my_verify_destination(cp, label .. " position", BATTLE_TARGET) then return end
    G.phase("battle-ready", play.at(cp))

    local before, after = save_at(cp, domain, BATTLE_TARGET, label)
    if not before then return end
    local _, final_report = party_report()
    G.idle(60)
    G.finish(true, string.format("counter %d -> %d party=%s", before, after,
                                 tostring(final_report)))
end

-- ── entry ────────────────────────────────────────────────────────────────────────────────────

local function run()
    G.open("gen3_fixture_from_state")   -- patch/build/gen3_fixture_from_state_result.txt
    pcall(client.speedmode, 6399)
    G.budget = 400000   -- a full heal-and-return or Route1->Viridian walk; generous like
                        -- gen3_scripted_play.lua's own play.main budget (900000) for a full run
    local cp, title = G.checkpoint()
    G.phase("start", "title=" .. tostring(title))

    local kind = os.getenv("SLINK_GEN3_FIXTURE_KIND")
    -- INSTRUMENTATION 2026-09-23 (coordinator's own instruction: check the instrument before
    -- theorizing about session length): every "no RESULT line" failure so far has EmuHawk's own
    -- process exiting with a small, clean returncode (1) in a handful of seconds -- nowhere
    -- near any timeout in force, and with no Windows crash record -- consistent with an
    -- UNCAUGHT LUA ERROR terminating the host, not a hang or a genuine emulator crash. Wrap the
    -- dispatch in pcall so that failure mode gets an actual diagnostic RESULT line instead of a
    -- silent process death.
    local ok, err
    if kind == "battle" then
        ok, err = pcall(run_battle, cp)
    elseif kind == "town" then
        ok, err = pcall(run_town, cp)
    else
        G.finish(false, "SLINK_GEN3_FIXTURE_KIND must be battle|town")
        return
    end
    if not ok then
        G.shot("stuck")
        G.finish(false, "uncaught Lua error: " .. tostring(err))
    end
end

if (debug.getinfo(1, "S").source or "") == "main" then run() end

return { party_report = party_report }
