-- playlib.lua — the scripted-play runtime every natural-play driver shares (card gen3-P3-C3-9).
--
-- WHAT THIS IS. Three drivers (lua/tests/gen3_scripted_play.lua, gen3_rr_scripted_play.lua,
-- gen3_fr_newgame_inputs.lua) each grew their own copy of the same machinery: an ordered LEGS
-- runner, a step/follow walker, a press-into-warp, a debounced scene wait, an A-only battle
-- mash, the shadow-observer block, and the object-event readers. Every copy drifted, and the
-- drift cost lane runs — the in_battle polarity bug, the multi-return-in-format bug and the
-- "leg inherited the previous leg's situation" bug each had to be found and fixed more than
-- once. This module is the single definition of all of it.
--
-- WHAT THIS IS NOT. It knows nothing about any game. Gen 3's helper module
-- (lua/tests/gen3_boot_check.lua) stays exactly what it is — a Gen 3 helper — and playlib
-- never requires it: the driver INJECTS it, along with the handful of game facts below, so a
-- Gen 1 or Gen 2 driver can inject its own reader set and get the same runner for free.
--
--   local PL   = dofile(WT .. "/lua/tests/playlib.lua")
--   local play = PL.bind(G, { paths = PATHS, obj_events = 0x02036E38,
--                             party_count_addr = 0x02024029, state_dir = "..." })
--
-- THE INJECTED HELPER TABLE `H` (Gen 3 drivers pass gen3_boot_check's module; any table with
-- these names works). playlib calls only these, never a Gen 3 symbol:
--   H.pos(cp) -> x, y            player tile coordinates
--   H.map(cp) -> group, num      map identity, negative when unreadable
--   H.pred_ok(cp, name) -> bool  a named predicate from the checkpoint pack
--   H.advance() / H.idle(n) / H.tap(btn, hold, gap)      frame + input primitives
--   H.phase(name, detail) / H.finish(ok, msg) / H.shot(name) / H.open(name)   reporting
--   H.checkpoint() -> cp, title  the pack the predicates come from
--   H.budget                     the runaway frame cap H.advance() enforces
--
-- THE INJECTED GAME FACTS (`opts`), all optional — a helper that needs one it was not given
-- says so instead of reading a wrong address:
--   paths             the driver's precomputed PATHS table (for follow)
--   obj_events        the object-event array base (obj_pos / obj_facing)
--   party_count_addr  the party-count byte
--   state_dir         where bare savestate names resolve
--
-- MULTI-RETURN SAFETY. `H.pos(cp)` returns TWO values, so using it anywhere but last in a
-- string.format argument list silently drops every following argument and the format call
-- errors at run time (PHYSICAL: three lane runs lost to this on 2026-09-21; the lint that
-- catches it lives in tests/unit/test_gen3_scripted_play.py). Every formatting helper here
-- (`at`, `where`, `obj_at`) returns ONE string, which is the fix rather than the warning.

local M = {}

local DELTA = { Up = { 0, -1 }, Down = { 0, 1 }, Left = { -1, 0 }, Right = { 1, 0 } }

--- os.getenv, with the empty string treated as unset (a runner passing an empty variable
--- through means "not set", not "a leg named """).
local function env(name)
    local v = os.getenv(name)
    if v == "" then return nil end
    return v
end

--- Bind the injected helper table + game facts into a play instance. Every returned helper
--- takes `cp` explicitly, exactly as the drivers' own copies did — no hidden per-instance
--- state, so a leg closure behaves identically whether it is driven by the runner or called
--- directly by a test.
function M.bind(H, opts)
    opts = opts or {}
    local P = { H = H, opts = opts }

    -- ── identity and formatting ─────────────────────────────────────────────────────────────

    --- group*256+num, UNFILTERED: an unreadable map (H.map returning -1,-1) yields -257 here,
    --- which compares unequal to every real map id. That is what the walkers want — "the map
    --- id is no longer what it was" is the signal, and a mid-warp read is exactly that.
    function P.mapid(cp)
        local g, n = H.map(cp)
        return g * 256 + n
    end

    --- ...and the filtered form for callers that must DISTINGUISH "unreadable" from "changed":
    --- nil when the SaveBlock pointer is not sane. A warp oracle that cannot tell those apart
    --- reports a map change that never happened (Codex review cx-378ce251).
    function P.readable_mapid(cp)
        local g, n = H.map(cp)
        if g < 0 or n < 0 then return nil end
        return g * 256 + n
    end

    function P.at(cp)
        local x, y = H.pos(cp)
        return string.format("(%d,%d)", x, y)
    end

    function P.where(cp)
        return string.format("map=%d at=%s", P.mapid(cp), P.at(cp))
    end

    -- ── object-event readers ────────────────────────────────────────────────────────────────
    -- Object 0 is the player. currentCoords are s16 x/y at +0x10/+0x12 stored +7 (MAP_OFFSET),
    -- facingDirection is the HIGH nibble at +0x18 (1=down 2=up 3=left 4=right) — pret
    -- include/global.fieldmap.h struct ObjectEvent. Introduced on FR run 8 to cross-check the
    -- live object against SaveBlock1.pos when the two disagreed.

    local function obj_base()
        return assert(opts.obj_events, "playlib: opts.obj_events was not injected")
    end

    function P.obj_pos(i)
        local base = obj_base() + (i or 0) * 0x24
        return memory.read_s16_le(base + 0x10) - 7, memory.read_s16_le(base + 0x12) - 7
    end

    function P.obj_facing(i)
        return memory.read_u8(obj_base() + (i or 0) * 0x24 + 0x18) >> 4
    end

    function P.obj_at(i)
        local x, y = P.obj_pos(i)
        return string.format("(%d,%d)", x, y)
    end

    -- ── battle / field state ────────────────────────────────────────────────────────────────

    --- POLARITY (Codex review cx-378ce251). The `in_battle` predicate row is a MASK plus an
    --- expect of 0, and pred_ok compares (value & mask) == expect — so H.pred_ok(cp,"in_battle")
    --- is TRUE when we are NOT in a battle. Wrapped here once, for every driver, because
    --- reading it the other way is what let G.mash pulse Start on the field.
    function P.in_battle(cp) return not H.pred_ok(cp, "in_battle") end

    function P.on_field(cp)
        return H.pred_ok(cp, "in_battle") and H.pred_ok(cp, "callback2")
    end

    function P.party_count()
        return memory.read_u8(assert(opts.party_count_addr,
                                     "playlib: opts.party_count_addr was not injected"))
    end

    --- A-only mash, for use INSIDE a battle and in menus. Deliberately NOT gen3_boot_check's
    --- G.mash, which pulses Start every 16 frames: on the field that opens the START menu.
    function P.mash_a(taps, stop)
        for _ = 1, taps do
            if stop and stop() then return true end
            H.tap("A", 3, 13)
        end
        return stop and stop() or false
    end

    -- ── walking ─────────────────────────────────────────────────────────────────────────────

    --- Fight a battle that started on its own to its end, A-only, then wait out the post-battle
    --- script. The default is the generic one: the action cursor resets to FIGHT each battle, so
    --- A, A is move slot 1, and A keeps advancing the text afterwards. A game whose battles need
    --- more injects `opts.battle`.
    function P.fight_through(cp, budget)
        if opts.battle then return opts.battle(cp) end
        if not P.mash_a(budget or 1200, function() return not P.in_battle(cp) end) then
            return false
        end
        return P.wait_scene_settled(cp, 1800)
    end

    --- A wild encounter that starts MID-STEP is not a stalled step and must not be treated as
    --- one: mashing A at a battle intro does nothing for the walk, and the path is still
    --- perfectly good afterwards. PHYSICAL (FR lane run 12): "parcel_fetch
    --- (route1_south_to_north_edge): step Left stalled at (9,32)" on a tall-grass tile whose
    --- collision is 0 and whose BFS path is unambiguous — the stall WAS an encounter.
    ---
    --- So: fight it, then continue the SAME path from wherever the player stands. A battle does
    --- not displace the player, so an unchanged position is required, not hoped for — the case
    --- that violates it is a whiteout, which teleports the player to a Pokémon Center and makes
    --- every remaining direction in the path meaningless. Bounded per path, and each encounter
    --- is reported: these are natural battle_begin/battle_end/faint sources the observer wants.
    function P.handle_encounter(cp, enc, dir)
        enc = enc or { n = 0 }
        local limit = enc.max or opts.max_encounters or 12
        enc.n = enc.n + 1
        local ex, ey = H.pos(cp)
        H.phase("encounter", string.format("#%d during step %s at (%d,%d)", enc.n, dir, ex, ey))
        if enc.n > limit then
            H.shot("stuck")
            H.finish(false, string.format(
                "more than %d wild encounters on one path (the last at (%d,%d)) — the walk is "
                .. "not making progress through the grass", limit, ex, ey))
        end
        if not P.fight_through(cp) then
            H.shot("stuck")
            H.finish(false, string.format("encounter #%d never ended (at (%d,%d))", enc.n, ex, ey))
        end
        local nx, ny = H.pos(cp)
        if nx ~= ex or ny ~= ey then
            H.shot("stuck")
            H.finish(false, string.format(
                "encounter #%d moved the player from (%d,%d) to (%d,%d) — a battle must not "
                .. "displace the player, so this was a whiteout (or a scripted warp) and the "
                .. "rest of the path no longer applies", enc.n, ex, ey, nx, ny))
        end
        H.phase("encounter-done", string.format("#%d resolved at (%d,%d)", enc.n, nx, ny))
    end

    --- One step in `dir`, verified against the position reader, bounded at 6 attempts.
    ---
    --- A step that does not move the player is NOT a failure on the first try: a textbox or a
    --- field script owns the player (Radical Red adds intro dialogue where FireRed has none),
    --- so the recovery is A presses followed by a retry of the SAME step.
    ---
    --- `want` chooses the success test. Without it, ANY movement counts (a ledge hop or a
    --- forced step still made progress along a BFS path); with it, the step must land exactly
    --- one tile along `dir` from where it started — the stricter form the new-game walk uses,
    --- where an unexpected displacement means the intro went wrong. A map change always counts:
    --- the warp tile took us.
    --- `enc` is the per-path encounter budget ({ n = 0, max = N }); pass `false` to refuse to
    --- absorb battles at all (a path whose own leg owns the battle that follows it).
    function P.step(cp, dir, start_map, want, enc)
        local x, y
        local wx, wy
        local function rebase()
            x, y = H.pos(cp)
            if want then wx, wy = x + DELTA[dir][1], y + DELTA[dir][2] end
        end
        rebase()
        local attempts = 0
        while attempts < 6 do
            attempts = attempts + 1
            for _ = 1, 12 do joypad.set({ [dir] = true }); H.advance() end
            H.idle(4)
            -- Judge the step BEFORE dealing with any battle: an encounter typically fires as
            -- the player lands on the new tile, so the step has usually already succeeded and
            -- re-walking it would put us one tile past the path.
            local nx, ny = H.pos(cp)
            local moved
            if want then moved = (nx == wx and ny == wy) else moved = (nx ~= x or ny ~= y) end
            if enc ~= false and P.in_battle(cp) then
                -- An encounter is not a stalled attempt: fight it, then carry on.
                P.handle_encounter(cp, enc, dir)
                if moved then return true end
                rebase()
                attempts = attempts - 1
            else
                if moved then return true end
                if P.mapid(cp) ~= start_map then return true end
                -- A textbox or field script owns the player (Radical Red adds intro dialogue
                -- where FireRed has none): clear it, then retry the SAME step.
                for _ = 1, 4 do H.tap("A", 3, 13) end
                if want then rebase() end
            end
        end
        return false
    end

    --- Follow a precomputed entry of the injected `paths` table, one step per direction.
    --- Returns as soon as the map changes (the path walked into a warp).
    ---
    --- A precomputed path is only valid FROM ITS START TILE: this refuses loudly rather than
    --- walking a wrong-offset route into collision (the first FR lane run stalled exactly so).
    function P.follow(cp, path_name, label)
        local paths = assert(opts.paths, "playlib: opts.paths was not injected")
        local p = assert(paths[path_name], "no PATHS entry " .. tostring(path_name))
        local start_map = P.mapid(cp)
        -- One encounter budget PER PATH: a grass crossing may be interrupted several times, but
        -- a walk that keeps being jumped is not making progress. `p.battles = false` opts a path
        -- out entirely (its leg owns the battle that follows it).
        -- NOT `x and false or y`: in Lua that evaluates to y, because `false` is falsy. An
        -- opt-out has to be written out.
        local enc = { n = 0, max = p.max_encounters or opts.max_encounters or 12 }
        if p.battles == false then enc = false end
        local sx, sy = H.pos(cp)
        if sx ~= p.from[1] or sy ~= p.from[2] then
            H.shot("stuck")
            H.finish(false, string.format(
                "%s (%s): start tile (%d,%d) is not the path's from (%d,%d)",
                label, path_name, sx, sy, p.from[1], p.from[2]))
        end
        for _, dir in ipairs(p.dirs) do
            if not P.step(cp, dir, start_map, nil, enc) then
                H.shot("stuck")
                H.finish(false, string.format("%s (%s): step %s stalled at %s",
                                              label, path_name, dir, P.at(cp)))
            end
            if P.mapid(cp) ~= start_map then return end
        end
    end

    --- Press `dir` repeatedly into an arrow warp until the map changes, then wait out the fade.
    --- FRLG stairs and doors are ARROW warps: the warp fires when the player presses INTO the
    --- warp tile from the adjacent walkable tile, so this is a press, not a walk.
    function P.enter_warp(cp, dir, budget)
        local from_map = P.mapid(cp)
        for _ = 1, (budget or 20) do
            if P.mapid(cp) ~= from_map then break end
            for _ = 1, 16 do joypad.set({ [dir] = true }); H.advance() end
            if P.mapid(cp) == from_map then for _ = 1, 2 do H.tap("A", 3, 13) end end
        end
        for _ = 1, 600 do
            if P.mapid(cp) ~= from_map and H.pred_ok(cp, "palette_fade_active") then
                H.idle(16)
                return true
            end
            H.advance()
        end
        return false
    end

    -- ── scripted scenes ─────────────────────────────────────────────────────────────────────

    --- Wait through a scripted scene: A-only while script_context_status/field_controls_locked
    --- are not both quiet, then require that quiet to HOLD for `stable` consecutive frames (no
    --- further input) before trusting it — never a single read.
    ---
    --- PHYSICAL lesson, repeated across FR runs 4-7 (starter scene) and 11 (rival battle): both
    --- predicates can read "done" for a frame or two mid-scene. An optional `also()` predicate
    --- adds extra ground truth (a scene var, an object position).
    function P.wait_scene_settled(cp, budget, also, stable_frames)
        local need = stable_frames or 60
        local stable = 0
        for _ = 1, (budget or 6000) do
            local quiet = H.pred_ok(cp, "script_context_status")
                      and H.pred_ok(cp, "field_controls_locked")
            if quiet and also then quiet = also() end
            if quiet then
                stable = stable + 1
                if stable >= need then return true end
                H.advance()
            else
                stable = 0
                H.tap("A", 2, 10)
            end
        end
        return false
    end

    -- ── savestates ──────────────────────────────────────────────────────────────────────────

    --- An absolute path passes through; a bare file name resolves against SLINK_STATE_DIR, or
    --- the injected default.
    function P.state_path(name)
        if not name or name == "" then return nil end
        if name:find("[/\\]") then return name end
        local dir = os.getenv("SLINK_STATE_DIR") or opts.state_dir
        if not dir then return nil end
        return dir .. "/" .. name
    end

    -- ── the runner ──────────────────────────────────────────────────────────────────────────

    --- Run an ordered LEGS table.
    ---
    --- Leg contract:
    ---   name         unique; the resume key
    ---   state        optional savestate the RUNNER loads before this leg — never inherited
    ---                from whatever the previous leg happened to leave behind (that bug cost
    ---                an RR lane run: door_warp walked out of wild_faint's leftovers)
    ---   check(cp)    optional; nil when the situation is right, else the reason it is not
    ---   open         true for a leg that is documented but not scripted; it is SKIPPED and
    ---                reported separately, never counted as reached
    ---   open_reason  why, for an open leg
    ---   run(cp)      the leg body; absent on an open leg
    ---
    --- `o` fields: name (result file base), budget, boot(cp), shadow = { script, result },
    --- resume_env (default SLINK_GEN3_PLAY_FROM), state_env (default SLINK_STATE).
    ---
    --- ORDER MATTERS AND IS PART OF THE CONTRACT: boot FIRST, then the observer, then the legs.
    --- Starting the observer before a cold boot would attribute the title screen's own map
    --- loads to natural play.
    function P.main(LEGS, o)
        o = o or {}
        H.open(o.name)
        pcall(client.speedmode, 6399)
        if o.budget then H.budget = o.budget end
        local cp, title = H.checkpoint()
        H.phase("start", "title=" .. tostring(title))

        if o.boot then o.boot(cp) end

        local resume_env = o.resume_env or "SLINK_GEN3_PLAY_FROM"
        local from_idx = 1
        local play_from = env(resume_env)
        if play_from then
            local found = false
            for i, leg in ipairs(LEGS) do
                if leg.name == play_from then from_idx, found = i, true; break end
            end
            if not found then
                H.finish(false, resume_env .. " names no leg: " .. play_from)
            end
            H.phase("resume", "from=" .. play_from)
        end

        -- The shadow observer, read-only, beside the driver when SLINK_SHADOW is set (same
        -- block shape as lua/tests/duo/duo_main.lua). A driver that ran the whole play and
        -- silently observed NOTHING is worse than a failure, so a failed dofile, a failed
        -- start and the FIRST poll error are all fatal rather than a logged shrug.
        local shadow_err = nil
        if o.shadow and os.getenv("SLINK_SHADOW") then
            local okshd, shd = pcall(dofile, o.shadow.script)
            if not okshd or not shd then
                H.finish(false, "shadow: dofile of " .. tostring(o.shadow.script)
                             .. " failed: " .. tostring(shd))
            end
            local okst, st = pcall(shd.start,
                                   { duo = { result = o.shadow.result, player = "a" } })
            if not okst or not st then
                H.finish(false, "shadow: observer start failed: " .. tostring(st))
            end
            H.phase("shadow", "observer started admitted_by=" .. tostring(st.admitted_by))
            event.onframeend(function()
                if shadow_err then return end       -- report the FIRST error, stop retrying
                local ok, err = pcall(st.poll)
                if not ok then shadow_err = tostring(err) end
            end, o.shadow.name or "SLink-play-shadow-poll")
        end

        -- An explicit state overrides the FIRST leg's declared one (an operator trying a
        -- different capture); every later leg loads exactly what it declares.
        local override = P.state_path(env(o.state_env or "SLINK_STATE"))

        local reached, skipped = {}, {}
        for i = from_idx, #LEGS do
            local leg = LEGS[i]
            if leg.open then
                H.phase("skip-open", leg.name .. ": " .. tostring(leg.open_reason))
                skipped[#skipped + 1] = leg.name
            else
                if leg.state then
                    local state = (i == from_idx and override) or P.state_path(leg.state)
                    if not state or not pcall(savestate.load, state) then
                        H.finish(false, string.format("%s: savestate.load failed: %s",
                                                      leg.name, tostring(state)))
                    end
                    H.idle(30)
                    H.phase("leg-state", string.format("%s <- %s", leg.name, state))
                end
                local why = leg.check and leg.check(cp)
                if why then
                    H.shot("stuck")
                    H.finish(false, string.format("%s: precondition failed: %s", leg.name, why))
                end
                H.phase("leg-start", leg.name)
                leg.run(cp)
                if shadow_err then
                    H.finish(false, "shadow: poll failed during " .. leg.name .. ": " .. shadow_err)
                end
                H.phase("leg-done", leg.name)
                reached[#reached + 1] = leg.name
            end
        end

        if shadow_err then H.finish(false, "shadow: poll failed: " .. shadow_err) end
        H.finish(true, string.format("reached: %s | open (skipped): %s",
                                     table.concat(reached, ","), table.concat(skipped, ",")))
    end

    return P
end

M.DELTA = DELTA

return M
