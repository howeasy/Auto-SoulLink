-- test_live_soullinkmenu.lua — the SOULLINK row in RR's START menu (ROADMAP §6, step 1).
--
-- Proves the menu hook: the row appears only when enabled, sits where we spliced it, its callback
-- fires, and choosing it opens the panel lua/gen3/native.lua staged (native:link_panel, the SlinkInfo
-- staging the client does on the server's link_panel command).
--
-- The enable byte for the DISABLED probes is written raw on purpose: 0 is the boot default an
-- unpatched-Lua session leaves, i.e. a precondition, not an op. native.lua has no "disable" path
-- (link_panel always publishes enable=1), and it needs none.
--
-- The three things that would each ship a silently broken feature:
--   1. boot-zero must be stock. EWRAM boots zeroed and an unpatched-Lua run never writes SI, so a
--      patched ROM with no server must show the ordinary 6-row menu.
--   2. the row must be where we think. Off-by-one here means A on SOULLINK opens the bag.
--   3. the callback must actually run. The table word could point anywhere and the menu would
--      still LOOK right.
--
--   python tools/run_gate.py lua/tests/test_live_soullinkmenu.lua --timeout 300
local G = dofile((SLINK_ROOT or os.getenv("SLINK_ROOT")) .. "/lua/tests/gen3_gatelib.lua")
local t = G.open("soullinkmenu")

local COUNT  = 0x020370F5   -- sNumStartMenuActions   \ both located live by
local ORDER  = 0x020370F6   -- sStartMenuOrder        / lua/tests/test_live_startmenu.lua
local SI     = 0x0203FD44   -- SlinkInfo: +0 enable, +1 opened, +3 lines
local SPLICE = 5            -- SOULLINK takes EXIT's index; EXIT moves to 6
local SC2    = 0x03000F9C   -- sScriptContext2Enabled

-- SI is written out literally so this gate checks handlers.c independently of the client. Cross-check
-- it against the profile native block anyway, or the two could drift apart and both this gate and
-- native.lua would keep passing while pointing at different structs.
if t.P.INFO ~= SI then
    t.fail("profile native.INFO agrees with this gate's SlinkInfo",
           string.format("profile 0x%08X, gate 0x%08X", t.P.INFO, SI))
end

local function boot(enable)
    t.boot({ state = "slink_overworld.State", beacon = 240 })
    -- After the state load EWRAM is whatever the state held, so set enable every time.
    memory.write_u8(SI, enable and 1 or 0)
    memory.write_u8(SI + 1, 0)
end

local function order_str(n)
    local o = {}
    for i = 0, n - 1 do o[#o + 1] = tostring(memory.read_u8(ORDER + i)) end
    return table.concat(o, " ")
end

-- 1. disabled (the boot default) must be indistinguishable from stock.
boot(false)
t.tap("Start", 90)
local n0 = memory.read_u8(COUNT)
t.log(string.format("disabled: count=%d order=[%s]", n0, order_str(math.max(n0, 1))))
t.check("enable=0 leaves the stock 6-row menu", n0 == 6, "count=" .. n0)
local stock = true
for i = 0, 5 do if memory.read_u8(ORDER + i) ~= i + 1 then stock = false end end
t.check("enable=0 leaves the row order stock", stock)

-- 2. enabled: exactly one extra row, spliced before EXIT.
boot(true)
t.tap("Start", 90)
local n1 = memory.read_u8(COUNT)
t.log(string.format("enabled:  count=%d order=[%s]", n1, order_str(math.max(n1, 1))))
t.check("7 rows with the feature enabled", n1 == 7, "count=" .. n1)
local want, spliced = { 1, 2, 3, 4, 5, 8, 6 }, true
for i = 1, 7 do if memory.read_u8(ORDER + i - 1) ~= want[i] then spliced = false end end
t.check("order is [1 2 3 4 5 8 6] (SOULLINK where the gate thinks it is)", spliced)

-- 3. the callback fires, and fires for exactly ONE row. Reloading between attempts keeps each
-- probe independent, which is what makes "only index 5" a real claim rather than a lucky press.
local fired = {}
for k = 0, 6 do
    boot(true)
    t.tap("Start", 90)
    for _ = 1, k do t.tap("Down", 12) end
    t.tap("A", 60)
    if memory.read_u8(SI + 1) > 0 then fired[#fired + 1] = k end
end
t.log("rows whose callback bumped SI->opened: [" .. (#fired > 0 and table.concat(fired, " ") or "none") .. "]")
t.check("some row fired slink_startmenu_cb (act[8].func runs)", #fired > 0)
t.check("exactly one row fired the callback", #fired == 1, #fired .. " rows")
t.check("the callback fired on row " .. SPLICE, fired[1] == SPLICE, "row " .. tostring(fired[1]))

-- 4. and it must not fire while disabled (the callback tail-calls the row we displaced instead).
boot(false)
t.tap("Start", 90)
for _ = 1, SPLICE do t.tap("Down", 12) end
t.tap("A", 60)
t.check("the callback does not run with enable=0", memory.read_u8(SI + 1) == 0)

-- 5. END TO END: choosing the row must actually OPEN THE SCREEN native.lua staged, with no mailbox
-- round-trip. The callback only bumps a counter; drive_info in the frame hook turns that into a panel.
local function vram_hash()
    local h = 0
    for a = 0x06000000, 0x0600FFFF, 4 do h = (h * 31 + memory.read_u32_le(a)) % 0x7FFFFFFF end
    return h
end

boot(true)
-- one linked pair in the patch's row vocabulary (5+ "\n" fields = a mon row; empty label = partner)
local PANEL = { "RT03\nBulbasaur\n12\n19/23\n31\n\n", "\nSquirtle\n11\nFNT\n0\n\n" }
local stage = t.native:link_panel({ rows = PANEL })
t.check("native:link_panel queued the staging", stage ~= nil)
t.step(nil)
t.check("SlinkInfo published: enable=1, lines=" .. #PANEL,
        memory.read_u8(SI) == 1 and memory.read_u8(SI + 3) == #PANEL,
        string.format("enable=%d lines=%d", memory.read_u8(SI), memory.read_u8(SI + 3)))
local before = vram_hash()
t.tap("Start", 90)
for _ = 1, SPLICE do t.tap("Down", 12) end
t.tap("A", 60)
t.idle(150)                                   -- start menu closes, then the script opens the panel
local after = vram_hash()
t.log(string.format("row -> panel: vram %d -> %d (drawn=%s)", before, after, tostring(before ~= after)))
pcall(function() client.screenshot(t.ROOT .. "/patch/build/soullink_menu_panel.png") end)
t.check("choosing SOULLINK opened the panel (drive_info ran the screen)", before ~= after)
t.check("a field script is locked (the panel is up)", memory.read_u8(SC2) ~= 0)
-- THE SCREEN MUST NOT BE BLACK. When a start-menu row is chosen the engine fades to black unless
-- the action function is one of three whitelisted ones, because every other stock row hands off to
-- a screen that fades itself back in. Ours stays on the field, so the patch has to undo that fade.
local lit = 0
for i = 1, 15 do if memory.read_u16_le(0x05000000 + i * 2) ~= 0 then lit = lit + 1 end end
t.check("the screen is not faded to black (>= 8/15 BG palette 0 entries lit)", lit >= 8, lit .. "/15")
t.tap("A", 60)
t.idle(90)
t.check("the panel released the field when closed", memory.read_u8(SC2) == 0)

-- and with nothing staged the row must be inert rather than drawing an empty box
boot(true)
memory.write_u8(SI + 3, 0)                    -- precondition: no lines staged
t.tap("Start", 90)
for _ = 1, SPLICE do t.tap("Down", 12) end
t.tap("A", 60)
t.idle(150)
t.check("an unstaged panel does not lock the field", memory.read_u8(SC2) == 0)
t.finish()
