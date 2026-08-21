--[[
  lua/tests/probe_gen1_bootwalk.lua — WHY does the suppressed boot walk take 10x as long?

  Suppressing battles across the boot (M.setNoBattles, wired into duo_gb_main) stopped the
  Route 1 grass fixture from starting a wild encounter during the walk that proves the game
  is live — measured, `suppressed=true (in_battle=false)`, and route_1 stayed un-dead-zoned.
  It also took prove_booted from frame 1053 to frame 11327, and the duo runner's 120s cap on
  "MYKEY from both instances" then killed the second instance before it finished booting.

  1053 was never a fair baseline: it is the frame a WILD BATTLE started, which prove_booted
  accepts as proof precisely so a grass fixture does not have to complete a walk. With
  battles suppressed the full proof has to run — two round trips separated by 90 idle
  frames — so some of the increase is simply the real thing being measured for the first
  time. The question this probe answers is how much, and whether the round trips are
  FAILING rather than merely costing more.

  It reimplements prove_booted's loop with the same numbers and logs, per iteration:
  the party count, in-battle flag, position, and which of the two round-trip legs moved the
  player. If the legs are moving, the cost is honest and the runner's timeout is what needs
  raising. If a leg never moves, the fixture's tile is blocked and the walk needs a
  different direction — a completely different fix.

      python tools/run_gb_gate.py lua/tests/probe_gen1_bootwalk.lua --rom red --target battle

  Not a gate: it measures and prints a table. Its output is the evidence.
--]]

local G = dofile((SLINK_ROOT or os.getenv("SLINK_ROOT")) .. "/lua/tests/gen1_gatelib.lua")
local t = G.start("probe_gen1_bootwalk", {no_boot = true})
local M = t.M
local fmt = string.format

-- Same coordinate derivation prove_booted uses, so this measures the same bytes.
local CUR_MAP = M.MAP_ID_ADDR
local Y_COORD, X_COORD = CUR_MAP + 3, CUR_MAP + 4
local function pos() return M.read_u8(X_COORD), M.read_u8(Y_COORD) end
local function u8(a) return M.read_u8(a) end

local function step(b) t.step(b) end
local function hold(btn, n, stop)
    for _ = 1, n do
        if stop and stop() then return true end
        step({[btn] = true})
    end
    step(nil)
    return stop and stop() or false
end

-- The suppression under test, re-asserted every frame exactly as duo_gb_main does it.
local suppress = true
local function nb_step(b)
    if suppress then M.setNoBattles(true) end
    step(b)
end
local function nb_hold(btn, n, stop)
    for _ = 1, n do
        if stop and stop() then return true end
        nb_step({[btn] = true})
    end
    nb_step(nil)
    return stop and stop() or false
end

t.check("the profile carries a verified wStatusFlags4", M.STATUS_FLAGS_4_ADDR ~= nil
        and M.STATUS_FLAGS_4_ADDR ~= false,
        "without it there is nothing to suppress and this probe measures nothing")

--- One leg: hold `dir` and report whether the player actually moved.
local function leg(dir)
    local x0, y0 = pos()
    nb_hold(dir, 20, function()
        local x, y = pos()
        return x ~= x0 or y ~= y0
    end)
    local x1, y1 = pos()
    return (x1 ~= x0 or y1 ~= y0), x0, y0, x1, y1
end

local first_overworld, booted_at
local moved_any, blocked = {}, {}
for i = 1, 400 do
    local pc = M.getPartyCount()
    local inb = M.isInBattle()
    local x, y = pos()

    -- Note the first frame that looks like a real overworld, so the title-screen frames can
    -- be told apart from the walking frames in the total.
    if not first_overworld and pc >= 1 and pc <= 6 and not inb and u8(CUR_MAP) == 0x0C then
        first_overworld = t.frame
        t.log(fmt("[probe] first overworld-looking frame %d: map=0x%02X pos=(%d,%d) party=%d",
                  t.frame, u8(CUR_MAP), x, y, pc))
    end

    if pc >= 1 and pc <= 6 then
        local out = (i % 2 == 0) and "Right" or "Left"
        local back = (i % 2 == 0) and "Left" or "Right"
        local moved, ox, oy, nx, ny = leg(out)
        if first_overworld then
            if moved then moved_any[out] = (moved_any[out] or 0) + 1
            else blocked[out] = (blocked[out] or 0) + 1 end
        end
        if moved then
            local back_ok = leg(back)
            local xa, ya = pos()
            if back_ok and xa == ox and ya == oy then
                for _ = 1, 90 do nb_step(nil) end
                local xb, yb = pos()
                if xa == xb and ya == yb then
                    -- Same direction for the second round trip, matching the gatelib fix
                    -- this probe's first run motivated.
                    local m2 = leg(out)
                    if m2 then
                        local m3 = leg(back)
                        if m3 and select(1, pos()) == ox then
                            booted_at = t.frame
                            t.log(fmt("[probe] FULL PROOF completed at frame %d "
                                      .. "(iteration %d)", t.frame, i))
                            break
                        end
                    end
                end
            end
        elseif first_overworld and i <= 8 then
            t.log(fmt("[probe] iter %d: %s did NOT move the player off (%d,%d) "
                      .. "-> (%d,%d) in_battle=%s", i, out, ox, oy, nx, ny, tostring(inb)))
        end
    end
    nb_hold("A", 6, nil)
    for _ = 1, 16 do nb_step(nil) end
end

t.log(fmt("[probe] first overworld frame: %s", tostring(first_overworld)))
t.log(fmt("[probe] full proof frame:      %s", tostring(booted_at)))
if first_overworld and booted_at then
    t.log(fmt("[probe] frames spent WALKING (proof - overworld) = %d",
              booted_at - first_overworld))
end
t.log(fmt("[probe] legs that moved:   Left=%d Right=%d",
          moved_any.Left or 0, moved_any.Right or 0))
t.log(fmt("[probe] legs that blocked: Left=%d Right=%d",
          blocked.Left or 0, blocked.Right or 0))
t.log(fmt("[probe] final: map=0x%02X pos=(%d,%d) in_battle=%s statusFlags4=0x%02X",
          u8(CUR_MAP), select(1, pos()), select(2, pos()), tostring(M.isInBattle()),
          M.STATUS_FLAGS_4_ADDR and u8(M.STATUS_FLAGS_4_ADDR) or 0))

t.check("the boot walk reached a live overworld at all", first_overworld ~= nil,
        "never saw map 0x0C with a sane party out of battle")
t.check("battles really were suppressed for the whole walk", not M.isInBattle(),
        "an encounter started despite the per-frame write")
t.check("at least one direction moves the player", (moved_any.Left or 0)
        + (moved_any.Right or 0) > 0,
        "BOTH legs are blocked — the fixture's tile, not the timeout, is the problem")

t.finish(fmt("overworld=%s proof=%s", tostring(first_overworld), tostring(booted_at)))
