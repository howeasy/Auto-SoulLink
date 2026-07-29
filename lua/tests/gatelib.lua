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
        coord_base = function(M) return M.MAP_ID_ADDR end,
        coord_dy   = 3,
        coord_dx   = 4,
    },
    gen2_crystal = {
        module     = "games.gen2_crystal",
        data_dir   = "gen2_crystal",
        label      = "Gen 2",
        coord_base = function(M) return M.MAP_NUMBER_ADDR end,
        coord_dy   = 1,
        coord_dx   = 2,
    },
}

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
    -- Walking cannot be faked: if the coordinates change, the overworld loop is live.
    local base = spec.coord_base(M)
    assert(base, fmt("%s profile has no coordinate base address", spec.label))
    local x_addr, y_addr = base + spec.coord_dx, base + spec.coord_dy

    -- Three conditions, and ALL are required:
    --
    --   1. the party count is sane — only CONTINUE produces that. A NEW GAME has no party,
    --      so this also catches an A press landing on the wrong menu row.
    --   2. the player walks one way,
    --   3. and walks BACK to exactly where it started.
    --
    -- (3) is not belt-and-braces. During boot the coordinates flip from 0xFF (uninitialised)
    -- to 0x00, which reads as "the player moved" on a blank screen, and 0xFF -> 0x00 is even
    -- a delta of one — so no amount of scrutiny of a SINGLE move can tell a walk from an
    -- initialisation flip. Requiring the party count to be sane was supposed to cover that,
    -- and does not: measured on Crystal, this loop declared itself booted at frame 398, some
    -- 800 frames before the title screen even appears, on WRAM that also reported 8 badges
    -- and a nickname of "8?9?9?9?9?9". A round trip cannot be faked by initialisation —
    -- there is no second flip to carry the value back.
    --
    -- Probe with LEFT/RIGHT, never up/down: both generations' title lists are VERTICAL
    -- menus, so a Down press moves the cursor off CONTINUE onto NEW GAME. The outward
    -- direction alternates because whichever way we try first may be a wall.
    local booted = false
    local function pos() return M.read_u8(x_addr), M.read_u8(y_addr) end
    for i = 1, 300 do
        local pc = M.getPartyCount()
        if pc >= 1 and pc <= 6 then
            local out = (i % 2 == 0) and "Right" or "Left"
            local back = (out == "Right") and "Left" or "Right"
            local x0, y0 = pos()
            -- A direction must be HELD to walk; a tap only turns the player to face it.
            t.hold(out, 20, function()
                local x, y = pos()
                return x ~= x0 or y ~= y0
            end)
            local x1, y1 = pos()
            if x1 ~= x0 or y1 ~= y0 then
                t.hold(back, 20, function()
                    local x, y = pos()
                    return x == x0 and y == y0
                end)
                local x2, y2 = pos()
                if x2 == x0 and y2 == y0 and M.getPartyCount() == pc then
                    booted = true
                    break
                end
            end
        end
        -- Advance the attract loop / title menu / save-preview box. 6 frames, not 2 — a
        -- short tap does not reliably register (the same thing that left the naming cursor
        -- unmoved and the player pivoting instead of walking).
        t.hold("A", 6, nil)
        for _ = 1, 16 do t.step(nil) end
    end
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
