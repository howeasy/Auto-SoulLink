-- probe_gen3_frameend_census.lua — E2 frame-end CPU census, checkpoint-driven (docs/gen3/PLAN.md
-- §5.3; the FR/LG/RR receipts came from lua/tests/archive/gen3_old_client/probe_gen3_frameend_pc.lua,
-- archived with memory_gba by C5-6, so it cannot run any more).
--
-- Boots the per-run battery (tools/gen3_fixtures.py's SaveRAM plumbing) to the field with A only —
-- never Start, which in the field would open the menu (gen3_emerald_boot_check.lua:72-89) — waits
-- for field controls to stay free, then presses NOTHING and tallies R15 / CPSR mode+T / a coarse
-- state label / the active gTasks set over 1800 frame ends. Every address comes from the title's
-- write_checkpoint.json (SLINK_GEN3_CHECKPOINT + SLINK_GEN3_TITLE), so nothing here is per-title.
-- Output keeps the old census format (tests/unit/test_gen3_write_checkpoint.py census_rows).
-- Logs phase transitions and two summaries only.

local WT = SLINK_ROOT or os.getenv("SLINK_ROOT")
assert(WT, "SLINK_ROOT unset")
local G = dofile(WT .. "/lua/tests/gen3_boot_check.lua")
G.open("probe_gen3_frameend_census")   -- patch/build/probe_gen3_frameend_census_result.txt
pcall(client.speedmode, 6399)
local cp, title = G.checkpoint()
G.phase("start", "title=" .. tostring(title) .. " hash=" .. tostring(gameinfo.getromhash()))

local FRAMES = 1800
local function free() return G.pred_ok(cp, "callback2") and G.pred_ok(cp, "field_controls_locked") end
local held = 0
for i = 1, 9000 do
    if free() then held = held + 1; joypad.set({}) else held = 0; joypad.set(i % 16 == 8 and { A = true } or {}) end
    if held >= 60 then break end
    G.advance()
end
if held < 60 then G.shot("stuck"); G.finish(false, "never reached a free field in 9000 frames") end
local mg, mn = G.map(cp)
local px, py = G.pos(cp)
G.phase("field", string.format("map=(%d,%d) pos=(%d,%d)", mg, mn, px, py))

local T = cp.tasks
local function task_set()
    local active = {}
    for i = 0, T.count - 1 do
        local base = math.floor(T.address) + i * 0x28      -- struct Task: func u32, isActive u8
        local fn = memory.read_u32_le(base)
        if memory.read_u8(base + 4) ~= 0 and fn ~= 0 then active[#active + 1] = string.format("%08X", fn) end
    end
    table.sort(active)
    return table.concat(active, ",")
end
local function label()
    if not G.pred_ok(cp, "in_battle") then return "in-battle" end
    if not G.pred_ok(cp, "palette_fade_active") then return "fade" end
    if not G.pred_ok(cp, "callback2") then return "other-callback2" end
    if not G.pred_ok(cp, "field_controls_locked") then return "field-locked" end
    return "overworld-idle"
end

local frame, bios_seen, labels = 0, false, {}
local function top(counts, n)
    local arr = {}
    for k, c in pairs(counts) do arr[#arr + 1] = { k = k, c = c } end
    table.sort(arr, function(a, b) return a.c > b.c or (a.c == b.c and a.k < b.k) end)
    return { table.unpack(arr, 1, math.min(n, #arr)) }, #arr
end
local function summary(tag)
    G.log(string.format("---- [probe] %s at frame %d (bios_seen=%s) ----", tag, frame, tostring(bios_seen)))
    for name, agg in pairs(labels) do
        G.log(string.format("  %s: %d frames", name, agg.count))
        for _, e in ipairs((top(agg.r15, 10))) do G.log(string.format("    R15=0x%08X x%d", e.k, e.c)) end
        for _, e in ipairs((top(agg.cpsr, 10))) do G.log(string.format("    CPSR mode/T=%s x%d", e.k, e.c)) end
        local tasks, n = top(agg.tasks, 10)
        for _, e in ipairs(tasks) do G.log(string.format("    tasks={%s} x%d", e.k == "" and "none" or e.k, e.c)) end
        G.log(string.format("    (%d distinct task-function sets total)", n))
    end
end

joypad.set({})
G.phase("armed", "sampling " .. FRAMES .. " frame ends, no input")
event.onframeend(function()
    local pc, cpsr = emu.getregister("R15"), emu.getregister("CPSR")
    if type(pc) ~= "number" or type(cpsr) ~= "number" then return end
    frame = frame + 1
    if pc < 0x4000 then bios_seen = true end
    local name = label()
    labels[name] = labels[name] or { count = 0, r15 = {}, cpsr = {}, tasks = {} }
    local agg = labels[name]
    agg.count = agg.count + 1
    agg.r15[pc] = (agg.r15[pc] or 0) + 1
    local k = (cpsr & 0x1F) .. "/" .. ((cpsr >> 5) & 1)
    agg.cpsr[k] = (agg.cpsr[k] or 0) + 1
    local ts = task_set()
    agg.tasks[ts] = (agg.tasks[ts] or 0) + 1
    if frame == 600 then summary("interim") end
    if frame >= FRAMES then
        summary("final")
        local idle = labels["overworld-idle"] and labels["overworld-idle"].count or 0
        G.finish(idle > 0, "overworld-idle=" .. idle .. "/" .. frame)
    end
end, "SLink-gen3-census")
while true do emu.frameadvance() end
