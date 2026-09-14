-- lua/tests/gen1_gate.lua — headless gate harness for the NEW Gen 1 client modules.
--
-- Like gatelib.lua but built on lua/gen1/entry.lua (profile.json, reads, signals, writes,
-- write_safety) instead of the pre-rewrite memory_gb/gen1_rby modules, which are not evidence.
-- Boot proof is the measured one from gatelib: two walking round trips with an idle between,
-- because party count / flags / map id all read plausibly on the title and loading screens.
--
--   local G = dofile(SLINK_ROOT .. "/lua/tests/gen1_gate.lua")
--   local t = G.start("test_gen1_inspect_gate")   -- result: patch/build/<name>_result.txt
--   t.check(what, ok, detail); t.finish()
local Lib = {}

function Lib.start(gate_name, opts)
    opts = opts or {}
    local ROOT = SLINK_ROOT or os.getenv("SLINK_ROOT")
    assert(ROOT, "SLINK_ROOT unset — launch via tools/run_gb_gate.py")
    package.path = ROOT .. "/lua/?.lua;" .. package.path
    local Entry = dofile(ROOT .. "/lua/gen1/entry.lua")
    local OUT = ROOT .. "/patch/build/" .. gate_name .. "_result.txt"
    local fmt = string.format
    local t = { ROOT = ROOT, Entry = Entry, frame = 0, failures = 0, lines = {} }

    function t.log(s)
        console.log(s)
        t.lines[#t.lines + 1] = s
        local f = io.open(OUT, "w")
        if f then f:write(table.concat(t.lines, "\n") .. "\n"); f:close() end
    end
    function t.check(what, ok, detail)
        if not ok then t.failures = t.failures + 1 end
        t.log(fmt("  [%s] %s%s", ok and "ok" or "FAIL", what, detail and ("  — " .. tostring(detail)) or ""))
        return ok
    end
    function t.finish(extra)
        t.log(fmt("RESULT: %s %s (%d checks failed)", t.failures == 0 and "PASS" or "FAIL", extra or gate_name, t.failures))
        client.exit()
        error("slink-gate-finished", 0)
    end
    function t.step(buttons)
        if buttons then joypad.set(buttons) end
        emu.frameadvance()
        t.frame = t.frame + 1
    end
    function t.hold(btn, frames, stop)
        for _ = 1, frames do
            if stop and stop() then return true end
            t.step({ [btn] = true })
        end
        t.step(nil)
        return stop and stop() or false
    end
    function t.idle(frames) for _ = 1, frames do t.step(nil) end end

    client.speedmode(6399)
    local title, header = Entry.detect_title(function(a) return memory.read_u8(a, "ROM") end)
    if not title then
        t.log(fmt("RESULT: FAIL not a Gen 1 ROM (header %q)", tostring(header)))
        client.exit()
        error("slink-gate-finished", 0)
    end
    t.title = title
    t.deps = Entry.bizhawk_deps()
    local sent, replies = {}, {}
    t.sent, t.replies = sent, replies
    -- a loopback "server": the gate inspects what the client would send and feeds replies
    t.net = {
        init = function() end, connected = function() return t.online == true end, pump = function() end,
        send = function(line) sent[#sent + 1] = line end,
        receive = function() return table.remove(replies, 1) end,
    }
    t.hud = { show = function() end, prompt = function() end, set_game_over = function() end,
              set_rebuilding = function() end, clear_rebuilding = function() end }
    t.client, t.parts = Entry.build({ root = ROOT, io = t.deps, net = t.net, hud = t.hud, title = title,
                                      player = "a", rom_sha1 = gameinfo.getromhash():lower(),
                                      log = function(s) console.log(s) end })
    local ram = t.parts.profile.ram
    t.ram = ram
    t.log(fmt("[%s] title=%s rom=%s", gate_name, title, gameinfo.getromhash():lower():sub(1, 8)))
    if opts.no_boot then return t end

    -- Boot proof (see gatelib.prove_booted for why each escalation exists).
    local function pos() return memory.read_u8(ram.wXCoord, "System Bus"), memory.read_u8(ram.wYCoord, "System Bus") end
    local function round_trip(out)
        local back = (out == "Right") and "Left" or "Right"
        local x0, y0 = pos()
        t.hold(out, 20, function() local x, y = pos(); return x ~= x0 or y ~= y0 end)
        local x1, y1 = pos()
        if x1 == x0 and y1 == y0 then return false end
        t.hold(back, 20, function() local x, y = pos(); return x == x0 and y == y0 end)
        local x2, y2 = pos()
        return x2 == x0 and y2 == y0
    end
    local booted = false
    for attempt = 1, 40 do
        if attempt % 2 == 0 then t.step({ A = true }) end -- through the title/CONTINUE screens
        t.idle(30)
        local count = memory.read_u8(ram.wPartyCount, "System Bus")
        if count >= 1 and count <= 6 and memory.read_u8(ram.wIsInBattle, "System Bus") == 0 then
            if round_trip("Right") or round_trip("Left") then
                local x, y = pos()
                t.idle(90)
                local x2, y2 = pos()
                if x == x2 and y == y2 and (round_trip("Right") or round_trip("Left")) then booted = true break end
            end
        end
    end
    if not booted then
        client.screenshot(ROOT .. "/patch/build/" .. gate_name .. "_bootfail.png")
        t.check("booted into the overworld from the battery save", false, fmt("stuck at frame %d", t.frame))
        t.finish("boot failed")
    end
    t.log(fmt("[%s] booted at frame %d (party=%d, map=%d)", gate_name, t.frame,
              memory.read_u8(ram.wPartyCount, "System Bus"), memory.read_u8(ram.wCurMap, "System Bus")))
    return t
end

return Lib
