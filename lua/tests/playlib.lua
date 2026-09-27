-- playlib.lua — the scripted-play runtime every natural-play driver shares (card gen3-P3-C3-9,
-- rewritten for Codex review cx-67a6e199, which rejected the first cut as neither
-- game-agnostic nor fail-closed).
--
-- WHAT THIS IS. An ordered LEGS runner plus the walking, warping, scene-waiting and
-- battle-absorbing machinery the drivers used to own private, drifting copies of. Every copy
-- cost a lane run at least once: the in_battle polarity bug, the multi-return-in-format bug,
-- the leg-inherits-the-previous-leg's-situation bug, the connection-arrival-row bug.
--
-- WHAT THIS IS NOT. It knows nothing about any game AND nothing about any host. There is no
-- `memory`, `joypad`, `client`, `event`, `savestate` or `dofile` in this file: every host call
-- and every game fact arrives through the injected `H` table, so a Gen 1 or Gen 2 driver binds
-- its own and gets the same runner. A test can bind a fake and drive the whole thing with no
-- emulator (tests/unit/test_playlib.py does exactly that).
--
-- THE INJECTED TABLE `H`. Required:
--   pos(cp) -> x, y                the player's tile
--   map(cp) -> id | nil            map identity, nil when UNREADABLE. nil is not a map: it is
--                                  never equal to, and never different from, any other map.
--   in_battle(cp) -> bool          semantic, already de-polarised by the binding
--   on_field(cp) -> bool           walkable field, callbacks settled
--   advance() / idle(n) / tap(btn, hold, gap)      frames and single presses
--   press(buttons)                 one frame with these buttons held ({ Up = true })
--   phase(name, detail) / finish(ok, msg) / shot(name) / open(name)      reporting
--   checkpoint() -> cp, title      the profile the readers close over
-- Optional, asserted only by the helper that needs one:
--   scene_quiet(cp) -> bool        field script idle AND player control unlocked
--   obj_pos(i) -> x, y  /  obj_facing(i)     object-event readers (layout is the binding's)
--   party_count() -> n
--   party_key(i) -> string         a stable identity for party slot i (PID:OTID and the like)
--   party_record(i) -> string      slot i's whole record, for "did the survivors move?"
--   load_state(path) -> ok         savestates
--   register_frame_end(fn, name) -> id | nil   /  unregister_frame_end(id)
--   observer(result_path) -> st | nil, err     st.poll(), st.status() (status is REQUIRED)
--   moving(cp) -> bool             true while the player sprite is mid-step, if the game can
--                                  say; without it, arrival is judged by the tile holding still
--   set_budget(n) / speed_max()
--
-- THE INJECTED `opts`:
--   paths            the driver's precomputed PATHS table (for follow)
--   battle(cp, budget) -> bool     how THIS game fights a battle it did not choose. Required
--                                  before any walk can absorb an encounter: "mash A and hope"
--                                  is a Gen 3 fact, not a universal one.
--   clear_dialogue(cp)             how THIS game dismisses a textbox holding the player still
--   advance_scene(cp)              how THIS game advances one beat of a scripted scene
--   menu_back(cp, gap)             how THIS game backs out of a menu, one press
--   heal_map         the map id a whiteout warps the player to (enables whiteout recovery)
--   max_encounters   absorbed battles per path (default 12)
--   max_recoveries   whiteout restarts per leg (default 2)
--   state_dir        where bare savestate names resolve
--
-- MULTI-RETURN SAFETY. `H.pos(cp)` returns TWO values, so using it anywhere but last in a
-- string.format argument list silently drops every following argument and the format call
-- errors at run time (PHYSICAL: three lane runs lost to this). Every formatting helper here
-- (`at`, `where`, `obj_at`) returns ONE string, which is the fix rather than the warning.

local M = {}

local DELTA = { Up = { 0, -1 }, Down = { 0, 1 }, Left = { -1, 0 }, Right = { 1, 0 } }

--- os.getenv, with the empty string treated as unset. `os` is not a host API: it is Lua's own
--- standard library, available wherever this runs.
local function env(name)
    local v = os.getenv(name)
    if v == "" then return nil end
    return v
end

function M.bind(H, opts)
    opts = opts or {}
    local P = { H = H, opts = opts }
    -- Mark a finish, so a leg that raises is told apart from H.finish's own abort (which ends the
    -- script: client.exit() live, a raise under test). Only a raise with NO finish before it is a
    -- real Lua error, and that one is finished here by name instead of dying on the gate timeout
    -- with no RESULT, screenshot or phase trail (Emerald lost a 1500 s run; OMP cx-7ebf0d0f #8).
    if H.finish and not H.finish_marked then
        local real_finish = H.finish
        H.finish = function(...) P.finished = true; return real_finish(...) end
        H.finish_marked = true
    end
    local function raised(leg, where, err)
        if P.finished then error(err, 0) end          -- H.finish's abort: pass it through untouched
        if H.shot then H.shot("stuck") end
        H.finish(false, string.format("%s: %s raised: %s", leg.name, where, tostring(err)))
        error(err, 0)                                 -- only reached if the binding's finish returns
    end

    local function need(name)
        return assert(H[name], "playlib: the binding supplies no H." .. name)
    end

    -- ── identity and formatting ─────────────────────────────────────────────────────────────

    --- The map id, or nil when the binding cannot read one. EVERY comparison in this file goes
    --- through here. The first cut folded "unreadable" into a sentinel number, which compares
    --- unequal to every real map and so read as "the map changed" — a warp oracle that cannot
    --- tell those apart reports warps that never happened (Codex cx-67a6e199).
    function P.map(cp) return H.map(cp) end

    --- Same map, both readable. nil on either side is NOT sameness and NOT change.
    local function same_map(a, b) return a ~= nil and b ~= nil and a == b end

    function P.at(cp)
        local x, y = H.pos(cp)
        return string.format("(%d,%d)", x, y)
    end

    function P.where(cp)
        return string.format("map=%s at=%s", tostring(P.map(cp)), P.at(cp))
    end

    function P.obj_pos(i) return need("obj_pos")(i) end
    function P.obj_facing(i) return need("obj_facing")(i) end
    function P.obj_at(i)
        local x, y = P.obj_pos(i)
        return string.format("(%d,%d)", x, y)
    end
    function P.party_count() return need("party_count")() end

    -- ── battle / field state ────────────────────────────────────────────────────────────────

    function P.in_battle(cp) return H.in_battle(cp) end
    function P.on_field(cp) return H.on_field(cp) end

    -- ── the keyed party snapshot ────────────────────────────────────────────────────────────
    -- A PC round trip cannot be judged by a count: deposit A then withdraw B restores the count
    -- and is not a round trip, and a release followed by withdrawing something else restores it
    -- too. What settles it is WHICH record left and whether the SAME one came back. The shape
    -- of that argument is the same in every game; only the reads are per-game, so they are
    -- injected (H.party_key, H.party_record) and the reasoning lives here.

    --- { n, keys = { key -> record }, order = { key, ... } }. Keyed, not indexed: a deposit
    --- compacts the party, so slot numbers move and only keys are stable.
    function P.party_snapshot()
        local count = need("party_count")()
        local key = need("party_key")
        local record = H.party_record
        local snap = { n = count, keys = {}, order = {} }
        for i = 0, count - 1 do
            local k = key(i)
            snap.keys[k] = record and record(i) or k
            snap.order[#snap.order + 1] = k
        end
        return snap
    end

    function P.keylist(snap) return table.concat(snap.order, ",") end

    --- The single key `before` had and `after` does not. Returns nil plus a reason when that is
    --- not exactly one key — "several left" and "none left" are both wrong answers, and both
    --- look like success to a count.
    function P.departed_key(before, after)
        local gone
        for _, k in ipairs(before.order) do
            if after.keys[k] == nil then
                if gone then
                    return nil, string.format("more than one record left the party (%s and %s)",
                                              gone, k)
                end
                gone = k
            end
        end
        if not gone then
            return nil, string.format("no record left the party ([%s] -> [%s])",
                                      P.keylist(before), P.keylist(after))
        end
        return gone
    end

    --- Every record OTHER than `moved_key` must still be there, byte for byte. The travelling
    --- one is excluded on purpose: a box round trip can be lossy by design (RR stores a 58-byte
    --- CompressedPokemon), so its KEY is what must survive, not its bytes.
    function P.survivors_intact(before, after, moved_key)
        for _, k in ipairs(before.order) do
            if k ~= moved_key then
                if after.keys[k] == nil then
                    return false, string.format("record %s left the party too", k)
                end
                if after.keys[k] ~= before.keys[k] then
                    return false, string.format("record %s is not byte-identical", k)
                end
            end
        end
        return true
    end

    --- A-only mash. Deliberately not a helper that also pulses Start: on the field that opens
    --- the START menu, which is what the in_battle polarity bug turned into a lane failure.
    function P.mash_a(taps, stop)
        for _ = 1, taps do
            if stop and stop() then return true end
            H.tap("A", 3, 13)
        end
        return stop and stop() or false
    end

    --- Clear a textbox that is holding the player still. Which button does that is a per-game
    --- fact, so the binding supplies it, exactly like opts.battle.
    function P.clear_dialogue(cp)
        local clear = opts.clear_dialogue
        if not clear then
            H.finish(false, "playlib: a step stalled on a textbox, but the binding supplied no "
                         .. "opts.clear_dialogue — which button dismisses one is a per-game fact")
        end
        return clear(cp)
    end

    --- Advance a scripted scene by one beat.
    function P.advance_scene(cp)
        local adv = opts.advance_scene
        if not adv then
            H.finish(false, "playlib: a scripted scene needs advancing, but the binding supplied "
                         .. "no opts.advance_scene")
        end
        return adv(cp)
    end

    --- Fight a battle that started on its own. The POLICY is the binding's: which buttons pick
    --- a move, whether a menu must be waited for, what counts as over. playlib only knows that
    --- a battle must end before a walk can continue, and refuses to guess.
    function P.fight_through(cp, budget)
        local fight = opts.battle
        if not fight then
            H.finish(false, "playlib: a wild battle interrupted a walk, but the binding "
                         .. "supplied no opts.battle — how to fight is a per-game fact")
        end
        return fight(cp, budget or 1200)
    end

    -- ── walking ─────────────────────────────────────────────────────────────────────────────

    --- Is the player mid-step? A binding that has no such signal says "unknown", and every
    --- caller falls back to watching the position hold still instead.
    function P.moving(cp)
        if not H.moving then return false end
        return H.moving(cp) and true or false
    end

    --- Wait, bounded, for the player to come to REST on (x, y).
    ---
    --- A door or warp exit ANIMATES the player one tile: the map id and the callbacks settle
    --- while the sprite is still sliding, so a position read taken the instant a leg starts can
    --- be one tile short of where the engine is putting them. PHYSICAL (FR run 16):
    --- leave_lab_for_parcel reported leg-done at frame 12326 and parcel_fetch immediately
    --- refused with "start tile (16,13) is not the path's from (16,14)". The step was IN
    --- FLIGHT, not wrong — run 15 passed the same walk only because nothing checked.
    ---
    --- Resting means the tile matches AND is still matching a few frames later (or the binding
    --- says the object has stopped). A single equal read mid-slide is not arrival.
    function P.wait_at(cp, x, y, budget)
        local stable = 0
        for _ = 1, (budget or 120) do
            -- REST NEEDS READABLE EVIDENCE. H.pos reports (-1,-1) exactly when the SaveBlock
            -- pointer is unreadable, so a coordinate comparison made without checking the map
            -- can "arrive" at a tile the game cannot even report (Codex cx-93926f12).
            local px, py = H.pos(cp)
            if P.map(cp) ~= nil and px == x and py == y and not P.moving(cp) then
                stable = stable + 1
                if stable >= 4 then return true end
            else
                stable = 0
            end
            H.advance()
        end
        -- Budget exhausted. NOT rest: returning a bare coordinate match here would report
        -- arrival for a player still sliding, or one whose position was never readable.
        return false
    end

    local function new_budget()
        return { n = 0, max = opts.max_encounters or 12 }
    end

    --- A wild encounter that starts MID-STEP is not a stalled step. PHYSICAL (FR lane run 12):
    --- "step Left stalled at (9,32)" on a tall-grass tile whose collision is 0 — the stall WAS
    --- an encounter. Fight it, then continue the same path from where the player stands.
    ---
    --- `before` is the (map, x, y) captured before the battle. A battle does not move the
    --- player OR change the map; anything that did both-or-either is a displacement. The named
    --- case is a whiteout, which the runner can recover from; everything else is fatal, because
    --- nothing here can say what it was.
    function P.handle_encounter(cp, enc, dir, before)
        enc = enc or new_budget()
        local limit = enc.max or opts.max_encounters or 12
        enc.n = enc.n + 1
        H.phase("encounter", string.format("#%d during step %s at %s", enc.n, dir, P.at(cp)))
        if enc.n > limit then
            H.shot("stuck")
            H.finish(false, string.format(
                "more than %d wild encounters on one path (the last at %s) — the walk is not "
                .. "making progress through the grass", limit, P.at(cp)))
        end
        if not P.fight_through(cp) then
            H.shot("stuck")
            H.finish(false, string.format("encounter #%d never ended (at %s)", enc.n, P.at(cp)))
        end

        local nx, ny = H.pos(cp)
        local nmap = P.map(cp)
        local moved = (nx ~= before.x or ny ~= before.y)
        -- A MAP change with identical coordinates is still a displacement: (8,5) in the house
        -- is not (8,5) on Route 1, and comparing coordinates alone would have called it fine.
        local warped = not same_map(nmap, before.map)
        if moved or warped then
            if opts.heal_map and nmap == opts.heal_map then
                H.phase("whiteout", string.format(
                    "encounter #%d: fainted on map %s at (%d,%d), woke on the heal map %s at %s",
                    enc.n, tostring(before.map), before.x, before.y,
                    tostring(opts.heal_map), P.at(cp)))
                error({ whiteout = true, map = nmap, from_map = before.map,
                        from_x = before.x, from_y = before.y }, 0)
            end
            H.shot("stuck")
            H.finish(false, string.format(
                "encounter #%d displaced the player: map %s at (%d,%d) -> map %s at %s. A "
                .. "battle moves neither, and the destination is not the heal map, so this was "
                .. "not a whiteout either; the rest of the path no longer applies",
                enc.n, tostring(before.map), before.x, before.y, tostring(nmap), P.at(cp)))
        end
        H.phase("encounter-done", string.format("#%d resolved at %s", enc.n, P.at(cp)))
    end

    --- One step in `dir`, verified against the position reader, bounded at 6 attempts.
    ---
    --- `want` chooses the success test: without it ANY movement counts (a ledge hop still made
    --- progress along a BFS path), with it the step must land exactly one tile along `dir`.
    --- A readable map change always counts: the tile we walked onto was a warp.
    ---
    --- `enc` is the encounter budget. Omitted, ONE is allocated for this call — not one per
    --- encounter, which is what the first cut did, quietly making the bound meaningless.
    --- `false` refuses to absorb battles at all (a path whose leg owns the battle after it).
    function P.step(cp, dir, start_map, want, enc)
        if enc == nil then enc = new_budget() end
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
            for _ = 1, 12 do H.press({ [dir] = true }) end
            H.idle(4)
            -- Judge the step BEFORE dealing with a battle: an encounter fires as the player
            -- lands, so the step has usually already succeeded and re-walking it would put us
            -- one tile past the path.
            -- UNREADABLE IS NEVER PROGRESS. H.pos can report (-1,-1) exactly when the map id
            -- is unreadable, so a tile that merely went unreadable would otherwise read as a
            -- move, and a readable map compared against a nil start would read as a warp
            -- (Codex cx-bc675fa4). No judgement is made on an attempt we cannot read.
            local now = P.map(cp)
            local nx, ny = H.pos(cp)
            local readable = (now ~= nil)
            local moved = false
            if readable then
                if want then moved = (nx == wx and ny == wy) else moved = (nx ~= x or ny ~= y) end
            end
            if enc ~= false and P.in_battle(cp) then
                -- The displacement baseline is where the battle STARTED, which is where the
                -- step just landed — not the tile we stepped off. A battle does not move the
                -- player from where it found them; the step before it is allowed to.
                P.handle_encounter(cp, enc, dir, { map = P.map(cp), x = nx, y = ny })
                if moved then return true end
                rebase()
                attempts = attempts - 1
            else
                if moved then return true end
                -- A warp needs BOTH ids readable: "changed" is a statement about two maps.
                if readable and start_map ~= nil and now ~= start_map then return true end
                -- BATTLES REFUSED, AND ONE STARTED ANYWAY. With enc == false the caller said
                -- it owns whatever battle happens here, so a step that ended inside one is
                -- neither progress nor a stall -- it is the caller's answer. PHYSICAL (FR run
                -- 17): the encounter fired during a Down step of the grass hunt, the step fell
                -- through to tapping dialogue at a battle intro until its attempts ran out,
                -- and the hunt reported "the grass loop stalled on Down" while the observer
                -- was logging battle_begin.
                if enc == false and P.in_battle(cp) then return false, "in_battle" end
                -- A textbox or field script owns the player (Radical Red adds intro dialogue
                -- where FireRed has none): clear it, then retry the SAME step.
                P.clear_dialogue(cp)
                if want then rebase() end
            end
        end
        return false, "stalled"
    end

    --- Follow a precomputed entry of the injected `paths` table. Returns as soon as the map
    --- changes (the path walked into a warp); otherwise the final tile MUST be the path's `to`
    --- — a walk that ended somewhere else did not walk the path, however many steps it took.
    function P.follow(cp, path_name, label)
        local paths = assert(opts.paths, "playlib: opts.paths was not injected")
        local p = assert(paths[path_name], "no PATHS entry " .. tostring(path_name))
        local start_map = P.map(cp)
        if start_map == nil then
            H.shot("stuck")
            H.finish(false, string.format("%s (%s): the map id is unreadable before the walk",
                                          label, path_name))
        end
        local enc = { n = 0, max = p.max_encounters or opts.max_encounters or 12 }
        if p.battles == false then enc = false end
        -- Give an in-flight step time to land before calling the start tile wrong (see
        -- wait_at: FR run 16 died on a door-exit animation, not on a bad path).
        local sx, sy = H.pos(cp)
        if sx ~= p.from[1] or sy ~= p.from[2] then
            -- The answer is USED: a wait that ran out of budget has not seen the player come
            -- to rest, and walking a pinned path from a position nobody has confirmed is how
            -- the door-exit bug turned into a wrong-offset walk in the first place.
            if not P.wait_at(cp, p.from[1], p.from[2], 120) then
                H.shot("stuck")
                local nx, ny = H.pos(cp)
                H.finish(false, string.format(
                    "%s (%s): the player never came to rest on the path's from (%d,%d) — 120 "
                    .. "frames after the leg began they read (%d,%d) on map %s",
                    label, path_name, p.from[1], p.from[2], nx, ny, tostring(P.map(cp))))
            end
            sx, sy = H.pos(cp)
        end
        if sx ~= p.from[1] or sy ~= p.from[2] then
            H.shot("stuck")
            H.finish(false, string.format(
                "%s (%s): start tile (%d,%d) is not the path's from (%d,%d), and 120 frames "
                .. "were not enough for a step in flight to land there",
                label, path_name, sx, sy, p.from[1], p.from[2]))
        end
        for _, dir in ipairs(p.dirs) do
            if not P.step(cp, dir, start_map, nil, enc) then
                H.shot("stuck")
                H.finish(false, string.format("%s (%s): step %s stalled at %s",
                                              label, path_name, dir, P.at(cp)))
            end
            local now = P.map(cp)
            if now ~= nil and not same_map(now, start_map) then return end
        end
        if P.map(cp) == nil then
            H.shot("stuck")
            H.finish(false, string.format(
                "%s (%s): the walk ended with the map id unreadable, so where it ended cannot "
                .. "be said at all", label, path_name))
        end
        local ex, ey = H.pos(cp)
        if p.to and (ex ~= p.to[1] or ey ~= p.to[2]) then
            H.shot("stuck")
            H.finish(false, string.format(
                "%s (%s): the walk ended at (%d,%d), not the path's to (%d,%d)",
                label, path_name, ex, ey, p.to[1], p.to[2]))
        end
    end

    --- Press `dir` into a warp until the map changes, then wait for the field to settle.
    --- Returns ok, detail.
    ---
    --- The single definition: the RR driver grew a stronger copy of this (valid before/after
    --- ids plus a settle requirement) while the shared one still accepted the unreadable-map
    --- sentinel as a change. This is the stronger one, and the copy is gone.
    function P.enter_warp(cp, dir, budget)
        local from = P.map(cp)
        if from == nil then
            return false, "the map id is unreadable before the warp"
        end
        for _ = 1, (budget or 20) do
            local now = P.map(cp)
            if now ~= nil and now ~= from then break end
            for _ = 1, 16 do H.press({ [dir] = true }) end
            -- A textbox in the doorway is cleared by the BINDING's button, not by A: a
            -- library that presses A here is a library that only works on games where A is
            -- the dismiss button (Codex cx-93926f12).
            if same_map(P.map(cp), from) then P.clear_dialogue(cp) end
        end
        local to = P.map(cp)
        if to == nil then
            return false, string.format("the map id went unreadable and never came back "
                                     .. "(from %s)", tostring(from))
        end
        if to == from then
            return false, string.format("map never changed from %s", tostring(from))
        end
        for _ = 1, 900 do
            if P.on_field(cp) and P.map(cp) ~= nil then
                H.idle(16)
                -- Recheck AFTER the settle: those 16 frames are exactly when a second fade or
                -- an on-entry script can take the field back, and returning success from the
                -- read before them would be reporting the past (Codex cx-bc675fa4).
                if P.on_field(cp) and P.map(cp) ~= nil then
                    return true, string.format("map %s -> %s", tostring(from), tostring(P.map(cp)))
                end
            end
            H.advance()
        end
        return false, string.format("map %s -> %s but the field never settled",
                                    tostring(from), tostring(to))
    end

    -- ── scripted scenes ─────────────────────────────────────────────────────────────────────

    --- Wait through a scripted scene: A-only while the scene is busy, then require quiet to
    --- HOLD for `stable` consecutive frames before trusting it — never a single read. PHYSICAL
    --- lesson from FR runs 4-7 and 11: the quiet predicates flicker mid-scene.
    function P.wait_scene_settled(cp, budget, also, stable_frames)
        local quiet_fn = need("scene_quiet")
        local want = stable_frames or 60
        local stable = 0
        for _ = 1, (budget or 6000) do
            -- Scene advancement is a menu button policy, not a battle policy. Every caller
            -- must finish its battle explicitly; unknown state cannot authorize a press.
            if P.in_battle(cp) ~= false then
                return false, "scene wait refused: battle active or unreadable"
            end
            local quiet = quiet_fn(cp)
            if quiet and also then quiet = also() end
            -- A binding's predicate may advance a frame. Recheck at the input/success edge.
            if P.in_battle(cp) ~= false then
                return false, "scene wait refused: battle active or unreadable"
            end
            if quiet then
                stable = stable + 1
                if stable >= want then return true end
                H.advance()
            else
                stable = 0
                P.advance_scene(cp)
            end
        end
        return false
    end

    --- Leave a menu and get back to a field that HOLDS.
    ---
    --- Reaching the field is not the same as leaving the menu: on_field goes true while the
    --- menu's own exit textbox is still up. PHYSICAL (RR lane r5b/r5c): the back-button loop
    --- stopped on that early true, the lingering textbox ate the first press of the NEXT menu
    --- open, and every press after it landed one place off -- the run's "withdraw" half
    --- deposited a second mon instead of withdrawing the first. Two whole lane runs read as a
    --- menu-order problem when they were a timing one.
    ---
    --- So: dismiss until the field appears, keep dismissing through the textbox, settle, and
    --- then check the field is STILL there. The back button is the binding's (opts.menu_back);
    --- the shape is not.
    function P.leave_menu(cp, label, o)
        o = o or {}
        local back = opts.menu_back
        if not back then
            H.finish(false, "playlib: a menu needs leaving, but the binding supplied no "
                         .. "opts.menu_back — which button backs out is a per-game fact")
        end
        local out = false
        for _ = 1, (o.tries or 60) do
            if P.on_field(cp) then out = true; break end
            back(cp)
        end
        if not out then
            H.shot("stuck")
            H.finish(false, string.format(
                "%s: never got back to the field from the menu", label))
        end
        for _ = 1, (o.flush or 5) do back(cp, o.flush_gap) end
        H.idle(o.settle or 60)
        if not P.on_field(cp) then
            H.shot("stuck")
            H.finish(false, string.format(
                "%s: the field did not hold after leaving the menu — something is still open",
                label))
        end
    end

    -- ── savestates ──────────────────────────────────────────────────────────────────────────

    function P.state_path(name)
        if not name or name == "" then return nil end
        if name:find("[/\\]") then return name end
        local dir = os.getenv("SLINK_STATE_DIR") or opts.state_dir
        if not dir then return nil end
        return dir .. "/" .. name
    end

    -- ── the runner ──────────────────────────────────────────────────────────────────────────

    --- Run one leg, recovering from a whiteout if the leg says how.
    function P.run_leg(cp, leg, o)
        local limit = (o and o.max_recoveries) or opts.max_recoveries or 2
        for attempt = 0, limit do
            local body = (attempt > 0 and leg.resume) or leg.run
            local ok, err = pcall(body, cp)
            if ok then return end
            -- Anything that is not our own whiteout signal — above all H.finish's abort —
            -- belongs to the caller, untouched.
            if type(err) ~= "table" or not err.whiteout then raised(leg, "run", err) end
            if not leg.recover then
                H.shot("stuck")
                H.finish(false, string.format(
                    "%s: whited out on map %s at (%d,%d) and declares no recover()",
                    leg.name, tostring(err.from_map), err.from_x, err.from_y))
            end
            if attempt >= limit then
                H.shot("stuck")
                H.finish(false, string.format(
                    "%s: whited out %d times (limit %d); the party is losing every trip",
                    leg.name, attempt + 1, limit))
            end
            H.phase("whiteout-recover", string.format("%s: attempt %d of %d",
                                                      leg.name, attempt + 1, limit))
            leg.recover(cp)
            H.phase("whiteout-recovered", string.format("%s restarts at %s", leg.name, P.at(cp)))
        end
    end

    --- The observer's own health. A run that played the whole game and observed NOTHING is
    --- worse than a failed one, and a swallowed pcall around poll() cannot tell the difference
    --- (Codex cx-67a6e199). Every one of these states means the receipt is not evidence.
    local function observer_trouble(st)
        if not st then return nil end
        if not st.status then
            return "the observer exposes no status(), so its health cannot be read at all"
        end
        local ok, s = pcall(st.status)
        if not ok or type(s) ~= "table" then
            return "status() itself failed: " .. tostring(s)
        end
        if s.failed then return "failed=" .. tostring(s.failed) end
        if s.handler_error then return "handler_error=" .. tostring(s.handler_error) end
        if s.closed then return "the signal queue is closed" end
        if (s.rejected or 0) > 0 then
            return string.format("rejected=%d (a hook fired with a callback address that is "
                              .. "not its site's)", s.rejected)
        end
        if (s.dropped or 0) > 0 then
            return string.format("dropped=%d (the queue overflowed between drains, so fires "
                              .. "were lost)", s.dropped)
        end
        if (s.registered or 0) < 1 then return "registered=0 (no site was hooked at all)" end
        return nil
    end

    --- `o` fields: name, budget, boot(cp), shadow = { result, name },
    --- save_states (a filename PREFIX: each finished leg is saved as <prefix><leg>.State),
    --- save_states (a filename PREFIX: each finished leg is saved as <prefix><leg>.State),
    --- resume_env (default SLINK_GEN3_PLAY_FROM), state_env (default SLINK_STATE),
    --- max_recoveries.
    ---
    --- ORDER IS PART OF THE CONTRACT: validate the resume target, THEN boot, THEN start the
    --- observer, THEN run the legs. Validating after the boot wastes a cold boot on a typo;
    --- starting the observer before the boot attributes the title screen's own map loads to
    --- natural play.
    ---
    --- STATE OWNERSHIP. `leg.state` is the leg's own declared starting point and the runner
    --- loads it before every leg — never inherited from whatever the previous leg left behind.
    --- An explicit SLINK_STATE is the OPERATOR's override and wins for the first leg that
    --- actually runs, whether or not that leg declares a state of its own; if the resume target
    --- is an open (skipped) leg, the override lands on the first runnable leg after it. It
    --- applies exactly once.
    function P.main(LEGS, o)
        o = o or {}
        H.open(o.name)
        if H.speed_max then pcall(H.speed_max) end
        if o.budget and H.set_budget then H.set_budget(o.budget) end

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
        end

        local cp, title = H.checkpoint()
        H.phase("start", "title=" .. tostring(title))
        if play_from then H.phase("resume", "from=" .. play_from) end

        if o.boot then o.boot(cp) end

        local shadow_err, observer, frame_hook = nil, nil, nil
        if o.shadow and os.getenv("SLINK_SHADOW") then
            local make = need("observer")
            local st, err = make(o.shadow.result)
            if not st then
                H.finish(false, "shadow: the observer did not start: " .. tostring(err))
            end
            observer = st
            local trouble = observer_trouble(st)
            if trouble then
                H.finish(false, "shadow: the observer is unhealthy at startup: " .. trouble)
            end
            frame_hook = need("register_frame_end")(function()
                if shadow_err then return end       -- report the FIRST error, stop retrying
                local ok, err2 = pcall(st.poll)
                if not ok then shadow_err = tostring(err2) end
            end, o.shadow.name or "SLink-play-shadow-poll")
            if not frame_hook then
                H.finish(false, "shadow: the frame-end poll could not be registered, so the "
                             .. "observer would never drain")
            end
            H.phase("shadow", "observer started " .. tostring(st.detail or ""))
        end

        local function observer_ok(where)
            if shadow_err then
                H.finish(false, "shadow: poll failed" .. where .. ": " .. shadow_err)
            end
            local trouble = observer and observer_trouble(observer)
            if trouble then
                H.finish(false, "shadow: the observer is unhealthy" .. where .. ": " .. trouble)
            end
        end

        local override = P.state_path(env(o.state_env or "SLINK_STATE"))
        local reached, skipped = {}, {}

        -- Everything from here runs inside a pcall so the frame-end hook is ALWAYS removed:
        -- a failing leg, a refused precondition and an unhealthy observer all raise, and a
        -- hook that outlives the run keeps polling a finished observer (Codex cx-bc675fa4).
        local function body()
        for i = from_idx, #LEGS do
            local leg = LEGS[i]
            if leg.open then
                H.phase("skip-open", leg.name .. ": " .. tostring(leg.open_reason))
                skipped[#skipped + 1] = leg.name
            else
                local state = override or P.state_path(leg.state)
                override = nil                        -- the operator's override is used once
                if state then
                    if not need("load_state")(state) then
                        H.finish(false, string.format("%s: could not load the savestate %s",
                                                      leg.name, tostring(state)))
                    end
                    H.idle(30)
                    H.phase("leg-state", string.format("%s <- %s", leg.name, state))
                end
                local why
                if leg.check then
                    local ok, res = pcall(leg.check, cp)
                    if not ok then raised(leg, "check", res) end
                    why = res
                end
                if why then
                    H.shot("stuck")
                    H.finish(false, string.format("%s: precondition failed: %s", leg.name, why))
                end
                H.phase("leg-start", leg.name)
                P.run_leg(cp, leg, o)
                observer_ok(" during " .. leg.name)
                -- SAVE AFTER A LEG THAT FINISHED, AND ONLY THEN. These states are the only
                -- route to situations a fixture cannot reach: the FR checkpoint negatives need
                -- an in-battle-reachable state and a door state, and the firered_town fixture
                -- has party=0, so no wild battle exists from it. A leg that FAILED never gets
                -- here, which is the point -- a state saved mid-failure would be a trap.
                if o.save_states and H.save_state then
                    local path = P.state_path(string.format("%s%s.State",
                                                            o.save_states, leg.name))
                    if path and H.save_state(path) then
                        H.phase("leg-state-saved", string.format("%s -> %s", leg.name, path))
                    else
                        H.phase("leg-state-saved", string.format(
                            "%s: could not write %s (continuing; the run is the artifact, the "
                            .. "state is a convenience)", leg.name, tostring(path)))
                    end
                end
                H.phase("leg-done", leg.name)
                reached[#reached + 1] = leg.name
            end
        end

        observer_ok("")
        H.finish(true, string.format("reached: %s | open (skipped): %s",
                                     table.concat(reached, ","), table.concat(skipped, ",")))
        end

        local ok, err = pcall(body)
        if frame_hook and H.unregister_frame_end then
            pcall(H.unregister_frame_end, frame_hook)
        end
        if not ok then error(err, 0) end
    end

    return P
end

M.DELTA = DELTA

return M
