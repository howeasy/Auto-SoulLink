-- test_live_soullinkmenu.lua — the SOULLINK row in RR's START menu (ROADMAP §6, step 1).
--
-- Proves the menu hook and NOTHING else: the row appears only when enabled, sits where we spliced
-- it, and its callback fires. No screen is drawn yet — that is deliberate, so the hook is gated
-- before a single pixel of the info screen exists.
--
-- The three things that would each ship a silently broken feature:
--   1. boot-zero must be stock. EWRAM boots zeroed and an unpatched-Lua run never writes SI, so a
--      patched ROM with no server must show the ordinary 6-row menu.
--   2. the row must be where we think. Off-by-one here means A on SOULLINK opens the bag.
--   3. the callback must actually run. The table word could point anywhere and the menu would
--      still LOOK right.
--
--   python tools/run_gate.py lua/tests/test_live_soullinkmenu.lua --timeout 300
local SDIR = "E:/Howard/Bizhawk/GBA/State"
local WT = SLINK_ROOT or os.getenv("SLINK_ROOT") or debug.getinfo(1, "S").source:match([=[^@(.*)[/\]lua[/\]tests[/\]]=])
assert(WT, "repo root unknown — launch via: python tools/run_gate.py <this script>")
local OUT = WT .. "/patch/build/soullinkmenu_result.txt"
local MB = dofile(WT .. "/lua/mailbox.lua")

local COUNT  = 0x020370F5   -- sNumStartMenuActions   \ both located live by
local ORDER  = 0x020370F6   -- sStartMenuOrder        / lua/tests/test_live_startmenu.lua
local SI     = 0x0203FD44   -- SlinkInfo: +0 enable, +1 opened
local SPLICE = 5            -- SOULLINK takes EXIT's index; EXIT moves to 6

local lines = {}
local function log(s) lines[#lines + 1] = s; console.log(s) end
local function finish(ok)
    log(ok and "RESULT: PASS" or "RESULT: FAIL")
    local f = io.open(OUT, "w")
    if f then f:write(table.concat(lines, "\n") .. "\n"); f:close() end
    client.exit()
end

pcall(memory.usememorydomain, "System Bus")
pcall(function() client.speedmode(400) end)

-- The addresses above are written out literally so this gate checks handlers.c independently of
-- the Lua client. Cross-check them against mailbox.lua anyway, or the two could drift apart and
-- both this gate and the client would keep passing while pointing at different structs.
if MB.INFO ~= SI or MB.INFO_ENABLE ~= SI or MB.INFO_OPENED ~= SI + 1 then
    log(string.format("FAIL: mailbox.lua SlinkInfo (0x%08X) disagrees with this gate (0x%08X)",
                      MB.INFO, SI))
    finish(false)
end

local function boot(enable)
    assert(pcall(savestate.load, SDIR .. "/slink_overworld.State"), "no overworld savestate")
    emu.frameadvance()
    local up = false
    for _ = 1, 240 do emu.frameadvance(); if MB.present() then up = true; break end end
    if not up then log("FAIL: no 'SLNK' beacon — unpatched ROM?"); finish(false) end
    -- After the state load EWRAM is whatever the state held, so set enable every time.
    memory.write_u8(SI, enable and 1 or 0)
    memory.write_u8(SI + 1, 0)
end

local function tap(btn, frames)
    for f = 1, (frames or 20) do
        joypad.set(f <= 3 and { [btn] = true } or {})
        emu.frameadvance()
    end
end

local function order_str(n)
    local t = {}
    for i = 0, n - 1 do t[#t + 1] = tostring(memory.read_u8(ORDER + i)) end
    return table.concat(t, " ")
end

-- 1. disabled (the boot default) must be indistinguishable from stock.
boot(false)
tap("Start", 90)
local n0 = memory.read_u8(COUNT)
log(string.format("disabled: count=%d order=[%s]", n0, order_str(math.max(n0, 1))))
if n0 ~= 6 then
    log("FAIL: enable=0 changed the menu — the boot default is not stock")
    finish(false); return
end
for i = 0, 5 do
    if memory.read_u8(ORDER + i) ~= i + 1 then
        log("FAIL: enable=0 perturbed the row order")
        finish(false); return
    end
end

-- 2. enabled: exactly one extra row, spliced before EXIT.
boot(true)
tap("Start", 90)
local n1 = memory.read_u8(COUNT)
log(string.format("enabled:  count=%d order=[%s]", n1, order_str(math.max(n1, 1))))
if n1 ~= 7 then
    log("FAIL: expected 7 rows with the feature enabled, got " .. n1)
    finish(false); return
end
local want = { 1, 2, 3, 4, 5, 8, 6 }
for i = 1, 7 do
    if memory.read_u8(ORDER + i - 1) ~= want[i] then
        log("FAIL: order is not [1 2 3 4 5 8 6] — SOULLINK is not where the gate thinks it is")
        finish(false); return
    end
end

-- 3. the callback fires, and fires for exactly ONE row. Reloading between attempts keeps each
-- probe independent, which is what makes "only index 5" a real claim rather than a lucky press.
local fired = {}
for k = 0, 6 do
    boot(true)
    tap("Start", 90)
    for _ = 1, k do tap("Down", 12) end
    tap("A", 60)
    if memory.read_u8(SI + 1) > 0 then fired[#fired + 1] = k end
end
log("rows whose callback bumped SI->opened: [" ..
    (#fired > 0 and table.concat(fired, " ") or "none") .. "]")

if #fired == 0 then
    log("FAIL: no row fired slink_startmenu_cb — act[8].func never runs")
    finish(false); return
end
if #fired > 1 then
    log("FAIL: more than one row fired the callback")
    finish(false); return
end
if fired[1] ~= SPLICE then
    log(string.format("FAIL: the callback fired on row %d, expected %d", fired[1], SPLICE))
    finish(false); return
end

-- 4. and it must not fire while disabled (the callback tail-calls the row we displaced instead).
boot(false)
tap("Start", 90)
for _ = 1, SPLICE do tap("Down", 12) end
tap("A", 60)
if memory.read_u8(SI + 1) ~= 0 then
    log("FAIL: the callback ran with enable=0")
    finish(false); return
end

log("SOULLINK row: hidden when disabled, spliced at index 5 when enabled, callback fires there only")
finish(true)
