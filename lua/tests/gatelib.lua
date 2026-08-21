--[[
  lua/tests/gatelib.lua — shared boot + assertion helpers for the Game Boy headless gates.

  dofile() this from a gate; it returns a table.

      local G = dofile(os.getenv("SLINK_ROOT") .. "/lua/tests/gatelib.lua")
      local t = G.start("mygate", {game = "gen2_crystal"})   -- boots to player control
      t.check("party is loaded", t.M.getPartyCount() == 1)
      t.finish()

  `game` defaults to gen1_rby, so lua/tests/gen1_gatelib.lua is a one-line shim and the six
  Gen 1 gates that predate this file are untouched.

  WHY NO SAVESTATES: the Gen 3 gates each load a slink_*.State, which is version-locked —
  BizHawk stops on a modal dialog when handed a state from another release, so
  tools/mkstates.py exists purely to rebuild them after an upgrade. The GB gates boot from
  tests/fixtures/{gen1,gen2}/*.SaveRAM, which are BATTERY saves: plain SRAM, never stale.

  EXTRACTED AT THE SECOND CALLER, on purpose. Designing this seam against one real case and
  one imagined one would have guessed wrong about what varies; waiting until a third would
  have meant merging three drifted copies. What actually varies turned out to be small and
  entirely data — where the player's coordinates live, and which data directory to load —
  so it is a table, not a set of hooks.
--]]

local Lib = {}

-- Per-generation boot facts.
--
-- `coord_base`/`coord_dx`/`coord_dy`: the boot drive proves it is in the game by WALKING,
-- which means it needs the player's coordinates, and neither memory_gb nor the profiles
-- carry them (nothing in production reads them). They are derived from an address the
-- profile DOES carry, rather than hardcoded, so a relocated variant follows automatically —
-- Archipelago Crystal shifts wMapGroup by +11, and a literal would silently read a
-- neighbouring byte there. The offsets are uniform across every variant of each generation:
--   pokered    wCurMap    0xD35E -> wYCoord +3, wXCoord +4   (pokeyellow: same deltas)
--   pokecrystal wMapNumber 0xDCB6 -> wYCoord +1, wXCoord +2  (pokegold:   same deltas)
local GAMES = {
    gen1_rby = {
        module     = "games.gen1_rby",
        data_dir   = "gen1_rby",
        label      = "Gen 1",
        client     = "gen1_rby_client.lua",
        scenario_prefix = "gen1_",
        coord_base = function(M) return M.MAP_ID_ADDR end,
        coord_dy   = 3,
        coord_dx   = 4,
    },
    gen2_crystal = {
        module     = "games.gen2_crystal",
        data_dir   = "gen2_crystal",
        label      = "Gen 2",
        client     = "gen2_crystal_client.lua",
        scenario_prefix = "gen2_",
        coord_base = function(M) return M.MAP_NUMBER_ADDR end,
        coord_dy   = 1,
        coord_dx   = 2,
    },
}

Lib.GAMES = GAMES

--- Prove the emulator is in a LIVE overworld, not on a title screen or a loading screen.
---
--- Exported because the two-instance duo harness needs exactly this and had its own older
--- copy — the single-move version, with the false positive documented below still in it.
--- `step(buttons)` and `hold(btn, frames, stop)` are passed in because the gate driver and
--- the duo driver advance frames differently (the duo runs inside a coroutine).
---
--- WHAT IT TAKES TO BELIEVE THE GAME IS RUNNING, in three escalations, each of which was
--- measured to be insufficient before the next was added:
---
---   1. Party count sane + ONE move. Declared success on Gen 1's title screen, because the
---      coordinates flip from 0xFF (uninitialised) to 0x00 during boot and the CONTINUE
---      preview loads the save into the very WRAM the party lives in.
---   2. Add a ROUND TRIP — move out, move back to exactly the start. Declared success on
---      Crystal at frame 404, screenshotted as a BLANK SCREEN, with the title screen not
---      appearing until frame ~1400. The loader writes those bytes repeatedly while a map is
---      being set up, so a there-and-back pattern happens by itself.
---   3. Add PERSISTENCE. Two round trips separated by 90 frames of pressing nothing, with
---      the position required to be unchanged across the idle. A parked player does not move
---      when nothing is pressed; a screen that is still loading keeps writing.
---
--- Note what is NOT used: "the map id is nonzero" is the obvious extra condition and is
--- wrong, because Gen 1's town fixture stands in Pallet Town, which IS map 0.
---
--- Probes with LEFT/RIGHT only, never up/down: both generations' title lists are VERTICAL
--- menus, so a Down press moves the cursor off CONTINUE onto NEW GAME. That makes the
--- fixture's parking tile a hard requirement, which is why each playthrough certifies its
--- own — a save parked between a bed and a desk hangs every gate on a perfectly live game.
function Lib.prove_booted(M, game_key, step, hold)
    local spec = GAMES[game_key]
    assert(spec, "unknown game " .. tostring(game_key))
    local base = spec.coord_base(M)
    assert(base, "profile has no coordinate base address")
    local x_addr, y_addr = base + spec.coord_dx, base + spec.coord_dy
    local function pos() return M.read_u8(x_addr), M.read_u8(y_addr) end

    local function round_trip(out)
        local back = (out == "Right") and "Left" or "Right"
        local x0, y0 = pos()
        -- A direction must be HELD to walk; a tap only turns the player to face it.
        hold(out, 20, function()
            local x, y = pos()
            return x ~= x0 or y ~= y0
        end)
        local x1, y1 = pos()
        if x1 == x0 and y1 == y0 then return false end
        hold(back, 20, function()
            local x, y = pos()
            return x == x0 and y == y0
        end)
        local x2, y2 = pos()
        return x2 == x0 and y2 == y0
    end

    -- A WILD BATTLE IS ALSO PROOF, and on a grass fixture it is the likelier outcome: the
    -- walking this proof does is exactly what triggers encounters, so requiring a completed
    -- round trip in tall grass fails whenever the game does the most normal thing it can do.
    -- Measured — the Gen 1 `playthrough` scenario, the only one that boots onto Route 1,
    -- stopped reaching its first line at all.
    --
    -- IT MUST BE A TRANSITION, NOT A READING. "in a battle now, and still in a battle 60
    -- frames later" asks the emulator for nothing: on a frozen screen NOTHING is running, so
    -- nothing changes, and any screen whose wIsInBattle byte happens to sit at 1 or 2 passes
    -- for free. That is the same shape as the bug c227922 exists to close — a proof that a
    -- stopped machine satisfies. Requiring a non-battle frame FIRST makes it a state change
    -- the emulator had to execute, which no stalled screen can produce.
    --
    -- Not airtight, and stated rather than implied: a screen that reads 0 and later flips to
    -- a stable 1 would still pass. The walk below is the strong proof; this is the narrow
    -- exception for fixtures that start in grass, so it is kept as tight as it can be while
    -- still firing.
    local saw_out_of_battle = false
    for i = 1, 400 do
        local pc = M.getPartyCount()
        if pc >= 1 and pc <= 6 and not M.isInBattle() then saw_out_of_battle = true end
        if saw_out_of_battle and pc >= 1 and pc <= 6 and M.isInBattle() then
            -- Persistence on top of the transition: wIsInBattle can read garbage while WRAM
            -- is being initialised, so it has to STILL be a battle 60 frames later with the
            -- party count unchanged. A loader transient does not survive that.
            for _ = 1, 60 do step(nil) end
            if M.isInBattle() and M.getPartyCount() == pc then
                return true, x_addr, y_addr
            end
        end
        -- BOTH round trips go the SAME way. They used to go opposite ways, which quietly
        -- required the fixture to have open ground on BOTH sides -- and the Gen 1 `battle`
        -- fixture does not: measured at Route 1 (10,35), Left moved the player 0 times in
        -- 185 attempts and Right 183 times in 186 (lua/tests/probe_gen1_bootwalk.lua). The
        -- first round trip would succeed going Right and the second would then be asked to
        -- set off Left into a wall, so the full proof could never complete there and the
        -- boot only ever finished by way of the wild-battle exception above. Alternating
        -- `out` across iterations still tries both directions, so a fixture walled in on
        -- the other side is equally well served; nothing about the proof is weakened,
        -- because a there-and-back plus an idle plus another there-and-back is the same
        -- claim whichever side it is measured on.
        local out = (i % 2 == 0) and "Right" or "Left"
        if pc >= 1 and pc <= 6 and round_trip(out) then
            local xa, ya = pos()
            for _ = 1, 90 do step(nil) end        -- press NOTHING and watch
            local xb, yb = pos()
            if xa == xb and ya == yb
               and round_trip(out)
               and M.getPartyCount() == pc then
                return true, x_addr, y_addr
            end
        end
        -- Advance the attract loop / title menu / save-preview box. 6 frames, not 2 — a
        -- short tap does not reliably register (the same thing that left the naming cursor
        -- unmoved and the player pivoting instead of walking).
        hold("A", 6, nil)
        for _ = 1, 16 do step(nil) end
    end
    return false, x_addr, y_addr
end

-- opts.game    → key into GAMES above (default "gen1_rby")
-- opts.no_boot → set up M/G and the check helpers but skip the boot-to-CONTINUE drive, for
--                gates that have no battery save to boot FROM (the Archipelago builds) and
--                assert on the ROM rather than on a loaded game.
function Lib.start(gate_name, opts)
    opts = opts or {}
    local spec = GAMES[opts.game or "gen1_rby"]
    assert(spec, "unknown game " .. tostring(opts.game) .. " — add it to GAMES in gatelib.lua")

    local ROOT = SLINK_ROOT or os.getenv("SLINK_ROOT")
    assert(ROOT, "SLINK_ROOT unset — launch via tools/run_gb_gate.py")

    package.path = ROOT .. "/lua/?.lua;" .. ROOT .. "/lua/games/?.lua;"
                .. ROOT .. "/data/games/" .. spec.data_dir .. "/?.lua;" .. package.path
    package.loaded["memory_gb"] = nil
    package.loaded[spec.module] = nil
    local M = require("memory_gb")
    local G = require(spec.module)

    -- run_gb_gate.py finds a gate's verdict file by scanning its SOURCE for this exact path
    -- shape (see _OUT_RE), so the name has to be built this way.
    local OUT = ROOT .. "/patch/build/" .. gate_name .. "_result.txt"
    local fmt = string.format
    local t = {M = M, G = G, ROOT = ROOT, frame = 0, failures = 0, lines = {}}

    function t.log(s)
        console.log(s)
        t.lines[#t.lines + 1] = s
        local f = io.open(OUT, "w")
        if f then f:write(table.concat(t.lines, "\n") .. "\n"); f:close() end
    end

    function t.check(what, ok, detail)
        if not ok then t.failures = t.failures + 1 end
        t.log(fmt("  [%s] %s%s", ok and "ok" or "FAIL", what,
                  detail and ("  — " .. tostring(detail)) or ""))
        return ok
    end

    function t.finish(extra)
        t.log(fmt("RESULT: %s %s (%d checks failed)",
                  t.failures == 0 and "PASS" or "FAIL", extra or gate_name, t.failures))
        client.exit()
        error("slink-gate-finished", 0)     -- client.exit() is async; stop here for real
    end

    function t.step(buttons)
        if buttons then joypad.set(buttons) end
        emu.frameadvance()
        t.frame = t.frame + 1
    end

    function t.hold(btn, frames, stop)
        for _ = 1, frames do
            if stop and stop() then return true end
            t.step({[btn] = true})
        end
        t.step(nil)
        return stop and stop() or false
    end

    client.speedmode(6399)
    local variant = G.detect_variant()
    if not variant then
        t.log(fmt("RESULT: FAIL not a %s ROM", spec.label))
        client.exit()
        error("slink-gate-finished", 0)
    end
    M.initProfile(G, variant)
    t.variant = variant
    if opts.no_boot then
        t.log(fmt("[%s] variant=%s — no_boot: asserting without a battery save",
                  gate_name, variant))
        return t
    end
    t.log(fmt("[%s] variant=%s — booting from battery save", gate_name, variant))

    -- Boot to CONTINUE, then PROVE we are actually in the game by walking.
    --
    -- "party count is sane AND isInOverworld()" is NOT sufficient, and believing it made
    -- every Gen 1 gate green while the emulator sat on the title screen: the CONTINUE menu
    -- loads the save preview (PLAYER / BADGES / POKeDEX / TIME) into the same WRAM the party
    -- lives in, so the count reads 1 and the safe-state flags read 0 with nothing running.
    -- Screenshotting it was the only way that showed up. Crystal's continue screen shows the
    -- same fields and so has the same hazard.
    --
    -- Walking cannot be faked: if the coordinates change, the overworld loop is live. See
    -- Lib.prove_booted for the two weaker versions of that claim that were measured passing
    -- on a title screen and on a blank screen.
    local booted, x_addr, y_addr = Lib.prove_booted(M, opts.game or "gen1_rby", t.step, t.hold)

    if not booted then
        client.screenshot(ROOT .. "/patch/build/" .. gate_name .. "_bootfail.png")
        t.check("booted into the overworld from the battery save", false,
                fmt("stuck at frame %d (party=%d, pos=%d,%d) — see %s_bootfail.png",
                    t.frame, M.getPartyCount(), M.read_u8(x_addr), M.read_u8(y_addr),
                    gate_name))
        t.finish("boot failed")
    end

    t.x_addr, t.y_addr = x_addr, y_addr
    t.log(fmt("[%s] booted at frame %d (party=%d, pos=%d,%d)", gate_name, t.frame,
              M.getPartyCount(), M.read_u8(x_addr), M.read_u8(y_addr)))
    return t
end

return Lib
