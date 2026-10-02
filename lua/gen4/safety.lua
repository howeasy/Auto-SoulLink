-- lua/gen4/safety.lua -- read-only Gen 4 write checkpoint (docs/gen4/research/checkpoint.md §5).
--
-- `Safety.new(title, mem, opts)`:
--   title  the pack title object (a `.profile` and `.symbols`; the bare profile is accepted for
--          the offsets but then gSystem cannot resolve: pack_gap:symbols.gSystem)
--   mem    read-only adapter, dot-called u8/u16/u32 (same as lua/gen4/reads.lua)
--   opts.reads             the lua/gen4/reads.lua module (range-checked readers; not duplicated)
--   opts.encounter_active  function() -> bool: the client's encounter lifecycle, true from battle
--                          setup until the encounter task has ended (copy-back done)
--
-- `s:checkpoint()` -> true | false, reason. Stateful: it remembers the last gSystem.vblankCounter,
-- so the FIRST call only records a baseline (false, "no_new_frame"). Poll once per frame. It is
-- true only when ALL clauses hold; the reason names the FIRST failing clause, in this order:
--   no_new_frame        gSystem.vblankCounter differs from the previous poll (wrap-safe)
--   fieldsys_*          [sFieldSysPtr] readable, non-null, whole probed extent in RAM; fs->unk0 likewise
--   save_data_mismatch  [fs+save] == [sSaveDataPtr], non-null
--   field_not_live      fs->unk6C != 0
--   paused              fs->unk0->isPaused == 0
--   task_running        [fs+task] == NULL (script/menu/warp/battle launch are all field tasks)
--   field_app_null      fs->unk0->unk0 != NULL (the field app is alive)
--   app_launched        fs->unk0->unk4 == NULL (no bag/party/battle app)
--   save_driver_null    [fs+0xD8] and its data pointer non-null (read only AFTER app_launched: view_photo reuses it)
--   save_driver_range   either pointer's struct extent is not inside main RAM (checked before it is dereferenced)
--   save_busy           save driver state byte == 1 (idle)
--   encounter_active    opts.encounter_active() is false; a throwing predicate is "encounter_unknown"
-- Any unreadable cell is "<clause>_unreadable"; a missing pack field is "pack_gap:<field>".
-- Deliberately NO "PC is in OS_WaitIrq" clause (checkpoint.md §5 clause 1: measured never true).
local S = {}

local function need(p, ...)
    local v, path = p, ""
    for _, k in ipairs({ ... }) do
        path = path .. (path == "" and "" or ".") .. k
        if type(v) ~= "table" or v[k] == nil then return nil, "pack_gap:" .. path end
        v = v[k]
    end
    return v
end

function S.new(title, mem, opts)
    local R = assert(opts and opts.reads, "opts.reads (lua/gen4/reads.lua) required")
    local encounter_active = assert(opts.encounter_active, "opts.encounter_active required")
    local p = title.profile or title
    local self, prev = {}, nil

    -- Resolve every pack value once; a gap makes every checkpoint refuse by name.
    local c, gap = {}, nil
    for _, f in ipairs({
        { "fs_ptr", "fieldsys_ptr", "address" }, { "sd_ptr", "save_ptr", "address" },
        { "vb", "system", "vblank_counter_off" },
        { "save", "probe_field", "save" }, { "task", "probe_field", "task" }, { "live", "probe_field", "live" },
        { "sub", "probe_field", "sub" }, { "paused", "probe_field", "paused" },
        { "field_app", "probe_field", "field_app" }, { "launched", "probe_field", "launched_app" },
        { "driver", "probe_field", "save_driver" }, { "driver_data", "probe_field", "save_driver_data_off" },
        { "state", "probe_field", "save_state" },
    }) do
        c[f[1]], gap = need(p, table.unpack(f, 2))
        if gap then break end
    end
    if not gap then
        local sym
        sym, gap = need(title, "symbols", p.system.symbol or "gSystem", "address")
        c.gsys = sym
    end
    local fs_extent = gap or math.max(c.save, c.task, c.live, c.driver) + 4
    local sub_extent = gap or math.max(c.field_app, c.launched, c.paused) + 4

    local function rd(addr, size) return R.read(mem, addr, size) end

    function self:checkpoint()
        if gap then return false, gap end
        local vb = rd(c.gsys + c.vb, 4)
        if not vb then return false, "vblank_unreadable" end
        local last = prev
        prev = vb
        if last == nil or vb == last then return false, "no_new_frame" end

        local fs = rd(c.fs_ptr, 4)
        if not fs then return false, "fieldsys_unreadable" end
        if fs == 0 then return false, "fieldsys_null" end
        if not R.in_ram(fs, fs_extent) then return false, "fieldsys_range" end
        local sub = rd(fs + c.sub, 4)
        if not sub then return false, "fieldsys_unreadable" end
        if sub == 0 then return false, "fieldsys_null" end
        if not R.in_ram(sub, sub_extent) then return false, "fieldsys_range" end

        local sd, sp = rd(fs + c.save, 4), rd(c.sd_ptr, 4)
        if not sd or not sp then return false, "save_data_unreadable" end
        if sd == 0 or sd ~= sp then return false, "save_data_mismatch" end
        local live = rd(fs + c.live, 4)
        if not live then return false, "field_not_live_unreadable" end
        if live == 0 then return false, "field_not_live" end
        local paused = rd(sub + c.paused, 4)
        if not paused then return false, "paused_unreadable" end
        if paused ~= 0 then return false, "paused" end
        local task = rd(fs + c.task, 4)
        if not task then return false, "task_running_unreadable" end
        if task ~= 0 then return false, "task_running" end
        local app = rd(sub + c.field_app, 4)
        if not app then return false, "field_app_null_unreadable" end
        if app == 0 then return false, "field_app_null" end
        local launched = rd(sub + c.launched, 4)
        if not launched then return false, "app_launched_unreadable" end
        if launched ~= 0 then return false, "app_launched" end

        -- both pointers are range-checked BEFORE they are dereferenced (F5), not left to the reader's own guard
        local drv = rd(fs + c.driver, 4)
        if not drv then return false, "save_driver_unreadable" end
        if drv == 0 then return false, "save_driver_null" end
        if not R.in_ram(drv, c.driver_data + 4) then return false, "save_driver_range" end
        local data = rd(drv + c.driver_data, 4)
        if not data then return false, "save_driver_unreadable" end
        if data == 0 then return false, "save_driver_null" end
        if not R.in_ram(data, c.state + 1) then return false, "save_driver_range" end
        local state = rd(data + c.state, 1)
        if not state then return false, "save_busy_unreadable" end
        if state ~= 1 then return false, "save_busy" end

        local ok, active = pcall(encounter_active)
        if not ok then return false, "encounter_unknown" end
        if active then return false, "encounter_active" end
        return true
    end

    -- The D7 in-battle write gate is a separate, narrower predicate on the live battle context
    -- (PLAN 4.3); not part of this card.
    function self:in_battle_write_ok() return false, "not_implemented" end

    return self
end

return S
