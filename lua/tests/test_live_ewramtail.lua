-- test_live_ewramtail.lua — prove the UNALLOCATED EWRAM tail is REALLY free.
--
-- This is the last contiguous EWRAM the patch can claim, and §6 already took 264 bytes of it.
-- Its freeness had only ever been ASSERTED, never measured: the argument was
-- that it sits above CFRU's highest KNOWN EWRAM symbol — the ceiling of an admittedly incomplete
-- list. An attempt to shore that up with a ROM literal-pool scan did not survive review (the scan
-- found 35 references into the window, and none of them is a literal pool at all — they are
-- coincidental word matches inside PCM and graphics data, so the metric says nothing either way).
-- The mailbox base got a real runtime watch before anyone trusted it (ADDRESSES.md
-- "Runtime-validated"); this region never did, and static analysis is not going to settle it.
--
-- So do the same thing here: paint a per-address pattern, play the game hard across every
-- savestate we have, and report ANY byte that changes. A stray engine write into a screen the
-- player is looking at is exactly the bug that would be impossible to attribute later.
--
--   python tools/run_gate.py lua/tests/test_live_ewramtail.lua --timeout 420
--
-- Bound to lua/tests/gen3_gatelib.lua (the new Gen 3 native layer): the paint and the beacon clobber
-- below are the probe's own instrumentation, not native ops, so they stay raw memory writes.
local G = dofile((SLINK_ROOT or os.getenv("SLINK_ROOT")) .. "/lua/tests/gen3_gatelib.lua")
local t = G.open("ewram_tail")

-- The first run proved 0x0203FD44..0x0203FFFF untouched. SlinkInfo later claimed
-- 0x0203FD44..0x0203FE4B, and RR-DURABLE then claimed 0x0203FE50..0x0203FF60
-- (shadow mailbox, witness, producer, and pre-save flag; handlers.c RT_*), and the main-menu version line
-- then claimed 0x0203FF61 (handlers.c SLM_STATE).
-- Never paint owned state: the producer writes its shadow mailbox every frame.
local RT_BASE, RT_END = 0x0203FE50, 0x0203FF62 -- RT_END is exclusive (past RT_PRESAVE 0x0203FF60 and SLM_STATE 0x0203FF61)
local TAIL_LO, TAIL_HI = RT_END, 0x0203FFFF
local N = TAIL_HI - TAIL_LO + 1                     -- 158
if t.P.INFO + 264 > RT_BASE or RT_BASE + 0x112 ~= TAIL_LO then
    t.fail("the watched tail starts after RR-DURABLE", string.format(
        "INFO+264=0x%08X RT_END=0x%08X", t.P.INFO + 264, RT_BASE + 0x112))
end
local log = t.log
local function finish(ok)
    t.check("EWRAM tail untouched across every scene", ok)
    t.finish()
end

-- Per-address pattern, so a hit tells us WHICH address was written even if the value is copied
-- around, and so a memset-to-zero or a memset-to-0xFF both register as a change everywhere.
local function want(addr) return (((addr * 0x9E) ~ 0x5A) & 0xFF) end

local function paint()
    for a = TAIL_LO, TAIL_HI do memory.write_u8(a, want(a)) end
end

-- Bulk read where the API allows it; per-byte reads every few frames add avoidable Lua work to
-- distort the very timing we are trying to observe.
local bulk = nil
do
    local ok, r = pcall(memory.read_bytes_as_array, TAIL_LO, N)
    if ok and type(r) == "table" then bulk = true; log("bulk read: read_bytes_as_array")
    else bulk = false; log("bulk read: unavailable, per-byte fallback") end
end

local hits = {}          -- [addr] = {frame, got, scene} — first hit per address only
local nhits = 0
local function check(scene, frame)
    local arr
    if bulk then
        local ok, r = pcall(memory.read_bytes_as_array, TAIL_LO, N)
        if ok then arr = r end
    end
    for i = 0, N - 1 do
        local a = TAIL_LO + i
        -- read_bytes_as_array is 1-based in BizHawk's Lua table marshalling
        local got = arr and arr[i + 1] or memory.read_u8(a)
        if got ~= want(a) and not hits[a] then
            hits[a] = { frame = frame, got = got, scene = scene }
            nhits = nhits + 1
        end
    end
end

-- Mash a rotating input set so the engine walks, opens menus, advances text and fights rather
-- than idling on one code path. START/SELECT are included deliberately: the §6 entry lives in
-- the start menu, so the start menu is the single most important thing to have exercised here.
local PRESS = { { Up = true }, { Right = true }, { A = true }, { Down = true }, { Left = true },
                { B = true }, { Start = true }, { A = true }, { B = true }, { Select = true } }

-- Negative control. A watch that cannot see a write would "pass" on a paused emulator, a failed
-- paint, or a bulk-read that silently returns stale bytes — and it would pass forever, silently.
-- The mailbox signature is rewritten with 'SLNK' by the frame hook every frame, so painting over
-- it and watching it come back proves paint + read + frame advance are all really happening.
local function detector_works()
    for i = 0, 3 do memory.write_u8(t.P.BASE + i, 0x5A) end
    if memory.read_u32_le(t.P.BASE) ~= 0x5A5A5A5A then return false, "paint did not stick" end
    for _ = 1, 10 do
        t.step(nil)
        if memory.read_u32_le(t.P.BASE) == t.P.SIG then return true end
    end
    return false, "beacon never restored — frames not advancing, or hook not running"
end

local function soak(name, state, frames)
    local f = io.open(G.STATE_DIR .. "/" .. state, "rb")
    if not f then
        log("SKIP " .. name .. ": no savestate " .. state)
        return false
    end
    f:close()
    -- Let the beacon come up first: painting before the hook runs would be testing nothing.
    t.boot({ state = state, beacon = 240 })

    -- Hard failure, not a skip: a blind watch reporting "clean" is worse than no watch at all.
    local okd, why = detector_works()
    if not okd then
        log("FAIL: detector self-check failed in " .. name .. " — " .. why)
        finish(false)
    end

    paint()
    local before = nhits
    for f = 1, frames do
        t.step(PRESS[(f // 12) % #PRESS + 1])
        if f % 6 == 0 then check(name, f) end
    end
    check(name, frames)
    log(string.format("  %-12s %4d frames  new-hits=%d", name, frames, nhits - before))
    return true
end

log(string.format("watching EWRAM tail 0x%08X..0x%08X (%d bytes)", TAIL_LO, TAIL_HI, N))

local ran = 0
-- Named in full so tests/live/test_lua_gates.py's STATE_RE can see which savestates this gate
-- needs and skip it when they are stale, rather than letting BizHawk stop on a version dialog.
for _, s in ipairs({ { "overworld", "slink_overworld.State", 900 },
                     { "pokecenter", "slink_pokecenter.State", 900 },
                     { "door", "slink_door.State", 600 },
                     { "battle", "slink_battle.State", 900 },
                     { "actionmenu", "slink_actionmenu.State", 600 },
                     { "movemenu", "slink_movemenu.State", 600 },
                     { "prebattle", "slink_prebattle.State", 600 } }) do
    if soak(s[1], s[2], s[3]) then ran = ran + 1 end
end

if ran == 0 then
    log("FAIL: no scene ran — savestates missing (python tools/mkstates.py)")
    finish(false); return
end

if nhits > 0 then
    -- Report contiguously so a 4-byte word write reads as one finding, not four.
    local addrs = {}
    for a in pairs(hits) do addrs[#addrs + 1] = a end
    table.sort(addrs)
    log(string.format("FAIL: %d of %d tail bytes were written by something else", nhits, N))
    local i = 1
    while i <= #addrs and i <= 40 do
        local lo = addrs[i]
        local j = i
        while j < #addrs and addrs[j + 1] == addrs[j] + 1 do j = j + 1 end
        local h = hits[lo]
        log(string.format("  0x%08X..0x%08X (%d B) first seen in %s at frame %d, got 0x%02X",
                          lo, addrs[j], addrs[j] - lo + 1, h.scene, h.frame, h.got))
        i = j + 1
    end
    log("the remaining tail is NOT free — do not allocate it")
    finish(false); return
end

log(string.format("clean: %d scenes, %d bytes untouched — tail is free for allocation", ran, N))
finish(true)
