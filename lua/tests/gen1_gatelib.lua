--[[
  lua/tests/gen1_gatelib.lua — shared boot + assertion helpers for the Gen 1 headless gates.

  dofile() this from a gate; it returns a table.

  WHY NO SAVESTATES: the Gen 3 gates each load a slink_*.State, which is version-locked —
  BizHawk stops on a modal dialog when handed a state from another release, so
  tools/mkstates.py exists purely to rebuild them after an upgrade. Gen 1 does not need any
  of that. tests/fixtures/gen1/*.SaveRAM are BATTERY saves, so a gate just boots the ROM and
  picks CONTINUE, which costs a second or two at speedmode and never goes stale.

  A gate looks like:

      local G = dofile(os.getenv("SLINK_ROOT") .. "/lua/tests/gen1_gatelib.lua")
      local t = G.start("mygate")            -- boots to player control
      t.check("party is loaded", t.M.getPartyCount() == 1)
      t.finish()
--]]

local Lib = {}

function Lib.start(gate_name)
    local ROOT = SLINK_ROOT or os.getenv("SLINK_ROOT")
    assert(ROOT, "SLINK_ROOT unset — launch via tools/run_gen1_gate.py")

    package.path = ROOT .. "/lua/?.lua;" .. ROOT .. "/lua/games/?.lua;"
                .. ROOT .. "/data/games/gen1_rby/?.lua;" .. package.path
    package.loaded["memory_gb"] = nil
    package.loaded["games.gen1_rby"] = nil
    local M = require("memory_gb")
    local G = require("games.gen1_rby")

    -- run_gate.py finds a gate's verdict file by scanning its SOURCE for this exact path
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
        t.log("RESULT: FAIL not a Gen 1 ROM")
        client.exit()
        error("slink-gate-finished", 0)
    end
    M.initProfile(G, variant)
    t.variant = variant
    t.log(fmt("[%s] variant=%s — booting from battery save", gate_name, variant))

    -- Boot to CONTINUE, then PROVE we are actually in the game by walking.
    --
    -- "party count is sane AND isInOverworld()" is NOT sufficient, and believing it made
    -- every gate green while the emulator sat on the title screen: the CONTINUE menu loads
    -- the save preview (PLAYER / BADGES / POKeDEX / TIME) into the same WRAM the party
    -- lives in, so the count reads 1 and wJoyIgnore/wStatusFlags5 read 0 with nothing
    -- running. Screenshotting it was the only way that showed up.
    --
    -- Walking cannot be faked: if the coordinates change, the overworld loop is live.
    local x_addr = M.MAP_ID_ADDR + 4      -- wXCoord = wCurMap + 4 (0xD35E -> 0xD362)
    local y_addr = M.MAP_ID_ADDR + 3      -- wYCoord = wCurMap + 3
    -- Two conditions, in this order, and BOTH are required:
    --
    --   1. the party count is sane — only CONTINUE produces that. A NEW GAME has no party
    --      until Oak's lab, so this also catches an A press landing on the wrong menu row.
    --   2. the player actually walks — proves the overworld loop is live.
    --
    -- Checking movement alone is NOT enough: during boot wXCoord/wYCoord flip from 0xFF
    -- (uninitialised) to 0x00, which reads as "the player moved" on a blank screen. That
    -- false positive is what let the whole gate suite pass while the emulator sat on the
    -- title menu, with the reads only looking right because the CONTINUE preview loads
    -- save data into the very WRAM the party lives in.
    --
    -- Probe with LEFT/RIGHT, never up/down: the title list is a VERTICAL menu, so a Down
    -- press moves the cursor off CONTINUE onto NEW GAME.
    local booted = false
    local dirs = {"Right", "Left"}
    for i = 1, 300 do
        local pc = M.getPartyCount()
        if pc >= 1 and pc <= 6 then
            local x0, y0 = M.read_u8(x_addr), M.read_u8(y_addr)
            -- A direction must be HELD to walk; a tap only turns the player to face it.
            t.hold(dirs[(i % 2) + 1], 20, function()
                return M.read_u8(x_addr) ~= x0 or M.read_u8(y_addr) ~= y0
            end)
            if M.read_u8(x_addr) ~= x0 or M.read_u8(y_addr) ~= y0 then booted = true break end
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
                    t.frame, M.getPartyCount(), M.read_u8(x_addr), M.read_u8(y_addr), gate_name))
        t.finish("boot failed")
    end

    t.log(fmt("[%s] booted at frame %d (party=%d)", gate_name, t.frame, M.getPartyCount()))
    return t
end

return Lib
