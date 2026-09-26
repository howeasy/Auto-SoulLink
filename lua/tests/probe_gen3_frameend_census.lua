-- probe_gen3_frameend_census.lua — E2 frame-end CPU census, checkpoint-driven (docs/gen3/PLAN.md
-- §5.3; the FR/LG/RR receipts came from lua/tests/archive/gen3_old_client/probe_gen3_frameend_pc.lua,
-- archived with memory_gba by C5-6, so it cannot run any more).
--
-- Boots the per-run battery (tools/gen3_fixtures.py's SaveRAM plumbing) to the field with A only —
-- never Start, which in the field would open the menu (gen3_emerald_boot_check.lua:72-89) — waits
-- for field controls to stay free, THEN waits again for the frame to be fully checkpoint-clean
-- (callback2/field_controls_locked alone can read free for a few frames while the map-name popup
-- is still settling -- the task clause below judges that, not this file) before arming the
-- sampler. Once armed it
-- presses NOTHING and tallies R15 / CPSR mode+T / a coarse state label / the active gTasks set
-- over 1800 frame ends. Every address comes from the title's write_checkpoint.json
-- (SLINK_GEN3_CHECKPOINT + SLINK_GEN3_TITLE), so nothing here is per-title.
-- Output keeps the old census format (tests/unit/test_gen3_write_checkpoint.py census_rows).
-- Logs phase transitions and two summaries only.
--
-- P below is pure (no BizHawk global): tests/unit/test_gen3_census_probe.py loads this file with
-- lupa executing the source, which compiles and runs the chunk without entering run() (the
-- main-guard at the bottom only fires for the real --lua= launch, reference_bizhawk_lua_selflocate),
-- and exercises P.label / P.tasks_allowed against a fake io table.
local P = {}

-- BizHawk's gTasks stores the function pointer with the Thumb bit set; write_checkpoint.json's
-- tasks.allowed_overworld_tasks addresses are Thumb-bit-stripped (even --
-- test_allowed_tasks_are_even_thumb_free_addresses), so every active task func read off the bus
-- must be masked the same way before it can be compared against the allow-list.
function P.mask(fn) return fn & ~1 end

--- True iff every ACTIVE task's function (masked) is in tasks.allowed_overworld_tasks -- the same
--- clause production write safety enforces (lua/gen3/safety.lua:129-141, the "task" clause).
--- tasks is the pack's cp.tasks block (address/count/struct_size/func_offset/is_active_offset/
--- allowed_overworld_tasks); io is {read_u8 = function(addr) end, read_u32 = function(addr) end}.
function P.tasks_allowed(io, tasks)
    local allowed = {}
    for _, addr in pairs(tasks.allowed_overworld_tasks) do allowed[math.floor(addr)] = true end
    for i = 0, tasks.count - 1 do
        local base = math.floor(tasks.address) + i * tasks.struct_size
        if io.read_u8(base + tasks.is_active_offset) ~= 0 then
            local fn = io.read_u32(base + tasks.func_offset)
            if fn ~= 0 and not allowed[P.mask(fn)] then return false end
        end
    end
    return true
end

--- Space-separated hex set of active task funcs, masked so it compares with the allow-list, for
--- the per-frame top() tally.
function P.task_set(io, tasks)
    local active = {}
    for i = 0, tasks.count - 1 do
        local base = math.floor(tasks.address) + i * tasks.struct_size
        if io.read_u8(base + tasks.is_active_offset) ~= 0 then
            local fn = io.read_u32(base + tasks.func_offset)
            if fn ~= 0 then active[#active + 1] = string.format("%08X", P.mask(fn)) end
        end
    end
    table.sort(active)
    return table.concat(active, ",")
end

--- The coarse per-frame state. G is the gen3_boot_check helpers module (G.pred_ok reads the
--- BizHawk memory domain directly), io/cp.tasks feed P.tasks_allowed.
function P.label(G, io, cp)
    if not G.pred_ok(cp, "in_battle") then return "in-battle" end
    if not G.pred_ok(cp, "palette_fade_active") then return "fade" end
    if not G.pred_ok(cp, "callback2") then return "other-callback2" end
    if not G.pred_ok(cp, "field_controls_locked") then return "field-locked" end
    if not P.tasks_allowed(io, cp.tasks) then return "overworld-task-refused" end
    return "overworld-idle"
end

-- -- the live driver -----------------------------------------------------------------------------
local function run()
    local WT = SLINK_ROOT or os.getenv("SLINK_ROOT")
    assert(WT, "SLINK_ROOT unset")
    local G = dofile(WT .. "/lua/tests/gen3_boot_check.lua")
    G.open("probe_gen3_frameend_census")   -- patch/build/probe_gen3_frameend_census_result.txt
    pcall(client.speedmode, 6399)
    local cp, title = G.checkpoint()
    G.phase("start", "title=" .. tostring(title) .. " hash=" .. tostring(gameinfo.getromhash()))

    local MEMIO = { read_u8 = memory.read_u8, read_u32 = memory.read_u32_le }
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

    -- Arm only once the frame is fully checkpoint-clean: callback2/field_controls_locked going
    -- free does not by itself mean every active task is admitted (e.g. the map-name popup task
    -- settling in), so a sampler armed right off free() above can start on an
    -- "overworld-task-refused" frame. Bounded, held so a one-frame flicker cannot pass.
    local CLEAN_HOLD = 60
    local clean = 0
    for i = 1, 1800 do
        if P.label(G, MEMIO, cp) == "overworld-idle" then clean = clean + 1 else clean = 0 end
        if clean >= CLEAN_HOLD then break end
        joypad.set({})
        G.advance()
    end
    if clean < CLEAN_HOLD then
        G.shot("stuck")
        G.finish(false, "never reached a checkpoint-clean frame (map-name popup?) within 1800 frames")
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
        local name = P.label(G, MEMIO, cp)
        labels[name] = labels[name] or { count = 0, r15 = {}, cpsr = {}, tasks = {} }
        local agg = labels[name]
        agg.count = agg.count + 1
        agg.r15[pc] = (agg.r15[pc] or 0) + 1
        local k = (cpsr & 0x1F) .. "/" .. ((cpsr >> 5) & 1)
        agg.cpsr[k] = (agg.cpsr[k] or 0) + 1
        local ts = P.task_set(MEMIO, cp.tasks)
        agg.tasks[ts] = (agg.tasks[ts] or 0) + 1
        if frame == 600 then summary("interim") end
        if frame >= FRAMES then
            summary("final")
            local idle = labels["overworld-idle"] and labels["overworld-idle"].count or 0
            -- The verdict is a rate, not a nonzero count: idle must be at least 90% of what was
            -- actually sampled.
            local ok = frame > 0 and idle >= 0.9 * frame
            G.finish(ok, "overworld-idle=" .. idle .. "/" .. frame)
        end
    end, "SLink-gen3-census")
    while true do emu.frameadvance() end
end

-- source == "main" ONLY for a top-level --lua= script (reference_bizhawk_lua_selflocate);
-- a lupa lua.execute(SOURCE) or dofile() sees the chunk's own path/name and just gets P.
if (debug.getinfo(1, "S").source or "") == "main" then run() end
return P
