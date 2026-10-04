-- Gen 4 companion C1: ITCM mailbox CANARY watch. Instrumentation, not a production binding.
-- melonDS write callbacks may not fire for TCM, so the host fills the candidate span with a run-specific
-- pattern after boot, re-verifies it every cfg.check_every frames and at every phase checkpoint, and a second
-- run uses a different pattern (a coincidental same-value write cannot hide in both).
-- Controls (a run with a red control is INVALID, never PASS):
--   b  known positive: a canary over a byte the game provably writes (gSystem.vblankCounter, system.h:33)
--   c  host rewrite: the host flips one span byte, the check must name that exact offset, restore reads clean
--   a  the ITCM domain write sticks and the "Instruction TCM" window agrees with the ARM9 bus at 0x01FF8000+off
-- Offline consumers set SLINK_GEN4_MAILBOX_TEST=true and receive the model API (no emulator needed).
-- Live: one terminal io.open receipt of `PROBE <a-i> <PASS|FAIL|OPEN> {json}` lines + `RESULT:`. No console in loops.
local M = {}
local BUS, ITCM = "ARM9 System Bus", "Instruction TCM"
local ITCM_BASE = 0x01FF8000
M.ROWS = "abcdefghi"
M.PHASE_ROW = {boot = "d", overworld = "e", menu = "f", battle = "g", save = "h"}
M.MIN_FRAMES = {boot = 1, overworld = 300, menu = 30, battle = 60, save = 30}

local function check(value, name) assert(value, name) end

-- 1..253 never 0x00/0xFF (the usual init/erase bytes); B is A shifted by 126 mod 253, so A[i] ~= B[i] everywhere.
function M.canary(kind, seed, n)
    check(kind == "A" or kind == "B", "canary kind A or B")
    local out = {}
    for i = 0, n - 1 do
        local a = (i * 37 + seed * 11) % 253 + 1
        out[i + 1] = kind == "A" and a or ((a - 1 + 126) % 253) + 1
    end
    return out
end

-- io: {write(off, tbl), read(off, n) -> tbl, hash(off, n) -> string|nil}; offsets are from the watch base.
function M.new_watch(io, name, base, n, bytes)
    local w = {io = io, name = name, base = base, n = n, expected = bytes, armed = false, checks = 0,
               events = {}, foreign_checks = 0, foreign_bytes = 0}
    local function diff()
        local back, found = io.read(0, n), {}
        for i = 1, n do if back[i] ~= bytes[i] then found[#found + 1] = {off = i - 1, want = bytes[i], got = back[i]} end end
        return found
    end
    function w:arm()
        io.write(0, bytes)
        local found = diff()
        if #found > 0 then self.arm_error = string.format("write does not stick at +%#x (want %#x got %#x)", found[1].off, found[1].want, found[1].got); return false end
        self.h0 = io.hash and io.hash(0, n) or nil
        self.armed = true
        return true
    end
    -- returns the list of mismatches found now; records and re-arms unless opts.keep (a deliberate host rewrite).
    function w:check(label, frame, opts)
        check(self.armed, "watch not armed: " .. name)
        self.checks = self.checks + 1
        if self.h0 and io.hash and io.hash(0, n) == self.h0 then return {} end
        local found = diff()
        if #found == 0 then return found end
        if not (opts and opts.keep) then
            self.foreign_checks = self.foreign_checks + 1
            self.foreign_bytes = self.foreign_bytes + #found
            for _, f in ipairs(found) do
                if #self.events < 32 then self.events[#self.events + 1] = {off = f.off, want = f.want, got = f.got, frame = frame, phase = label, prev = self.last_label} end
            end
            io.write(0, bytes) -- keep watching: a later write is reported separately
        end
        return found
    end
    function w:note(label) self.last_label = label end
    return w
end

-- c: the host flips one byte INSIDE the watched span; check() must name exactly that offset, and restore reads clean.
function M.control_host_rewrite(w, frame)
    local off = w.n // 2
    local orig = w.expected[off + 1]
    local flipped = (~orig) & 0xFF
    w.io.write(off, {flipped})
    local found = w:check("control", frame, {keep = true})
    w.io.write(off, {orig})
    local clean = w:check("control", frame, {keep = true})
    local ok = #found == 1 and found[1].off == off and found[1].want == orig and found[1].got == flipped and #clean == 0
    return {ok = ok, offset = off, found = #found, clean_after_restore = #clean == 0}
end

-- b: a canary byte over an address the game writes every frame MUST be seen overwritten within `frames`.
function M.control_known_positive(io, step, frames, seed)
    local original = io.read(0, 1)[1]
    local canary = M.canary("A", seed, 1)
    local w = M.new_watch(io, "known-positive", 0, 1, canary)
    if not w:arm() then return {detected = false, error = w.arm_error} end
    local seen
    for k = 1, frames do
        step()
        local found = w:check("control", k, {keep = true})
        if #found > 0 then seen = {frames = k, got = found[1].got}; break end
    end
    io.write(0, {(original + (seen and seen.frames or 0)) & 0xFF}) -- a frame counter: restore to "original + elapsed"
    return {detected = seen ~= nil, frames = seen and seen.frames, got = seen and seen.got, canary = canary[1]}
end

-- obs: see run(); returns {row -> {status, reason}}.
function M.evaluate(obs)
    local rows = {}
    local function put(r, status, reason) rows[r] = {status = status, reason = reason} end
    local a = obs.arm or {}
    if not a.itcm_size_ok then put("a", "FAIL", "Instruction TCM domain missing or not 32768 bytes")
    elseif a.arm_error then put("a", "FAIL", a.arm_error)
    elseif not a.bus_agree then put("a", "FAIL", "Instruction TCM window disagrees with the ARM9 bus at 0x01FF8000+off")
    elseif not a.armed then put("a", "OPEN", "canary never armed (boot did not reach the arm frame)")
    else put("a", "PASS") end
    local kp, hr = obs.known_positive, obs.host_rewrite
    if kp == nil then put("b", "OPEN", "known-positive control not run")
    elseif not kp.detected then put("b", "FAIL", "known-positive control NOT detected: the instrument cannot see a game write" .. (kp.error and (" (" .. kp.error .. ")") or ""))
    else put("b", "PASS") end
    if hr == nil then put("c", "OPEN", "host-rewrite control not run")
    elseif not hr.ok then put("c", "FAIL", "host-rewrite control wrong: found=" .. tostring(hr.found) .. " clean_after_restore=" .. tostring(hr.clean_after_restore))
    else put("c", "PASS") end
    local invalid = rows.a.status ~= "PASS" or rows.b.status ~= "PASS" or rows.c.status ~= "PASS"
    for phase, row in pairs(M.PHASE_ROW) do
        local p = (obs.phases or {})[phase] or {}
        local foreign = (obs.foreign or {})[phase] or 0
        if foreign > 0 then put(row, "FAIL", string.format("%d foreign write check(s) in span during %s", foreign, phase))
        elseif invalid then put(row, "FAIL", "run INVALID: a control row is not PASS, so silence proves nothing")
        elseif (p.verified or 0) < M.MIN_FRAMES[phase] then
            put(row, "OPEN", string.format("%s not reached: %d verified frames < %d", phase, p.verified or 0, M.MIN_FRAMES[phase]))
        else put(row, "PASS") end
    end
    local total = obs.span_foreign_total or 0
    if total > 0 then put("i", "FAIL", string.format("%d foreign write check(s) in the span (first: +%#x at frame %s)", total, obs.first_event and obs.first_event.off or -1, tostring(obs.first_event and obs.first_event.frame)))
    elseif invalid then put("i", "FAIL", "run INVALID: control row not PASS")
    elseif (obs.checks or 0) < 1 then put("i", "OPEN", "no verification ran")
    else put("i", "PASS") end
    return rows
end

if SLINK_GEN4_MAILBOX_TEST then return M end

-- ------------------------------------------------------------------------------------------ live run
local function run()
    local root = assert(SLINK_ROOT or os.getenv("SLINK_ROOT"), "SLINK_ROOT required")
    local json = dofile(root .. "/lua/json_codec.lua")
    local function read_json(path)
        local f = assert(io.open(path, "rb"), "cannot read " .. path); local raw = f:read("a"); f:close()
        local parsed = assert(json.decode(raw))
        local function strip(t) for k, v in pairs(t) do if v == json.null then t[k] = nil elseif type(v) == "table" then strip(v) end end end
        strip(parsed); return parsed
    end
    local cfg = read_json(assert(os.getenv("SLINK_GEN4_MAILBOX_CONFIG"), "SLINK_GEN4_MAILBOX_CONFIG required"))
    local out = assert(os.getenv("SLINK_GEN4_MAILBOX_OUT"), "SLINK_GEN4_MAILBOX_OUT required")
    -- reuse the G1 probe's boot/recipe/predicate helpers instead of re-deriving them
    SLINK_GEN4_PROBE_TEST = true
    local H = dofile(root .. "/lua/tests/probe_gen4_hooks.lua")
    SLINK_GEN4_PROBE_TEST = nil
    local LO, HI = cfg.span[1], cfg.span[2]
    local ALO, AHI = cfg.arena[1], cfg.arena[2]
    local obs = {arm = {}, phases = {}, foreign = {}, checks = 0}
    local errors, fatal_open = {}, nil
    local title, pack
    local started, advanced = os.clock(), 0
    local watch, arena_watch, last_check, armed_frame, arm_tried, prev_label = nil, nil, 0, nil, false, "boot"
    local function u32(v) return v & 0xFFFFFFFF end
    local function read(a) return u32(memory.read_u32_le(a, BUS)) end
    local function symbol(name) return assert(title.symbols[name], "symbol:" .. name).address end
    local function bytes(a, n) local b = memory.read_bytes_as_array(a, n, BUS); local t = {}; for i = 1, n do t[i] = string.format("%02x", b[i]) end; return table.concat(t) end

    -- ITCM io: offsets from the span / arena base, through the TCM domain (BUS used only for the agreement check)
    local function itcm_io(base)
        local o = base & 0x7FFF
        return {write = function(off, t) memory.write_bytes_as_array(o + off, t, ITCM) end,
                read = function(off, n) return memory.read_bytes_as_array(o + off, n, ITCM) end,
                hash = function(off, n) -- nil when the API is absent or fails: check() then falls back to a byte diff
                    local good, h = pcall(function() return memory.hash_region(o + off, n, ITCM) end)
                    return good and h or nil
                end}
    end
    local function idle_field()
        local fs, sp = read(symbol("sFieldSysPtr")), read(symbol("sSaveDataPtr"))
        if fs == 0 or sp == 0 then return false end
        local p = title.profile.probe_field
        local sub = read(fs + p.sub)
        if not (sub ~= 0 and read(fs + p.save) == sp and read(fs + p.task) == 0 and read(fs + p.live) ~= 0
            and read(sub + p.launched_app) == 0 and read(sub + p.field_app) ~= 0 and read(sub + p.paused) == 0) then return false end
        local driver = read(fs + p.save_driver); if driver == 0 then return false end
        local data = read(driver + p.save_driver_data_off)
        return data ~= 0 and memory.read_u8(data + p.save_state, BUS) == 1
    end
    local function observed_phase()
        local fs = read(symbol("sFieldSysPtr")); if fs == 0 then return "boot" end
        local p = title.profile.probe_field
        if idle_field() then return "overworld" end
        local sub = read(fs + p.sub); if sub == 0 then return "boot" end
        local battle = title.sites.BtlCmd_TryFaintMon
        if H.resident(title, read, battle.overlay_id) then return "battle" end
        local driver = read(fs + p.save_driver)
        if driver ~= 0 then
            local data = read(driver + p.save_driver_data_off)
            if data ~= 0 then local s = memory.read_u8(data + p.save_state, BUS); if s >= 2 and s <= 7 then return "save" end end
        end
        if read(fs + p.task) ~= 0 or read(sub + p.launched_app) ~= 0 then return "menu" end
        return "boot"
    end
    local function verify(label)
        obs.checks = obs.checks + 1
        local found = watch:check(label, emu.framecount())
        if #found > 0 then
            obs.span_foreign_total = (obs.span_foreign_total or 0) + 1
            obs.first_event = obs.first_event or watch.events[1]
            -- a write landed somewhere in (previous check, this check]: charge both phases
            for _, p in ipairs({label, prev_label}) do obs.foreign[p] = (obs.foreign[p] or 0) + 1 end
        end
        if arena_watch then
            if #arena_watch:check(label, emu.framecount()) > 0 then obs.arena_foreign_checks = (obs.arena_foreign_checks or 0) + 1 end
        end
        prev_label = label
    end
    local function arm()
        arm_tried = true
        local d = {}
        for _, name in pairs(memory.getmemorydomainlist()) do d[name] = memory.getmemorydomainsize(name) end
        obs.arm.itcm_size_ok = d[ITCM] == 32768 and d[BUS] ~= nil
        if not obs.arm.itcm_size_ok then return end
        local span_bytes = M.canary(cfg.canary, cfg.seed, HI - LO)
        watch = M.new_watch(itcm_io(LO), "span", LO, HI - LO, span_bytes)
        if cfg.fill == "arena" then
            -- the arena outside the span is informational only; the span stays the verdict
            local abytes = M.canary(cfg.canary, cfg.seed + 1, AHI - ALO)
            for i = 1, HI - LO do abytes[LO - ALO + i] = span_bytes[i] end
            arena_watch = M.new_watch(itcm_io(ALO), "arena", ALO, AHI - ALO, abytes)
            if not arena_watch:arm() then obs.arm.arm_error = arena_watch.arm_error; return end
        end
        if not watch:arm() then obs.arm.arm_error = watch.arm_error; return end
        local bus = memory.read_bytes_as_array(LO, HI - LO, BUS)
        obs.arm.bus_agree = true
        for i = 1, HI - LO do if bus[i] ~= span_bytes[i] then obs.arm.bus_agree = false; break end end
        obs.arm.armed, obs.arm.canary, obs.arm.span = obs.arm.bus_agree, cfg.canary, {LO, HI}
        armed_frame = emu.framecount()
        last_check = armed_frame
    end
    local last_phase
    local function step(buttons)
        joypad.set(buttons or {}); emu.frameadvance(); advanced = advanced + 1
        local f = emu.framecount()
        if not arm_tried and f >= cfg.arm_after then arm() end
        if armed_frame and obs.arm.armed then
            local p = observed_phase()
            local rec = obs.phases[p] or {verified = 0}; obs.phases[p] = rec; rec.verified = rec.verified + 1
            if f - last_check >= cfg.check_every or p ~= last_phase then verify(p); last_check = f end
            last_phase = p
        end
    end
    local function idle(n) for _ = 1, n do step({}) end end

    -- bridge routing: the same host-planner protocol probe_gen4_hooks.lua uses for gen4_route_play.lua
    local bridge_driver, bridge_sequence = nil, 0
    local function bridge_play(name)
        if name == "boot_continue_to_overworld" then return end
        if not bridge_driver then
            SLINK_GEN4_ROUTE_LIBRARY = true
            local ok, driver = pcall(dofile, root .. "/lua/tests/gen4_route_play.lua")
            SLINK_GEN4_ROUTE_LIBRARY = nil
            check(ok, "route library load failed: " .. tostring(driver)); bridge_driver = driver
        end
        for _ = 1, 12 do
            bridge_sequence = bridge_sequence + 1
            local request = {id = bridge_sequence, leg = name, position = bridge_driver.position(title)}
            local f = assert(io.open(cfg.bridge_request, "w")); f:write(assert(json.encode(request))); f:close()
            local reply
            for _ = 1, 12000 do
                local input = io.open(cfg.bridge_response, "rb")
                if input then local v = json.decode(input:read("a")); input:close(); if v and v.id == request.id then reply = v; break end end
                step({})
            end
            check(reply, "bridge: host planner response timeout")
            if reply.open then error({open = reply.open}, 0) end
            check(not reply.error, "bridge planner failed: " .. tostring(reply.error))
            local context = {route = reply.route, title = title, step = step, env = {G4_REPO = root, G4_LANE = cfg.bridge_lane, G4_TAG = "mbx-" .. bridge_sequence}}
            local ok, result = pcall(bridge_driver.run, context)
            check(not ok and type(result) == "table" and result.route_result, "route library failed: " .. tostring(result))
            result = result.route_result
            if result.status == "BATTLE" or result.status == "PC_DEPOSIT" then return end
            check(result.status == "RESYNC", "route bridge status " .. result.status .. ": " .. tostring(result.detail))
        end
        error({open = "bridge: route resync limit reached for " .. name}, 0)
    end
    local function play_route(route)
        for _, leg in ipairs(route or {}) do
            if leg.bridge then bridge_play(leg.bridge)
            elseif leg.steps then H.play_recipe(leg, step, function(p) return H.predicate(title, read, p) end)
            else
                local buttons = {}; for _, b in ipairs(leg.buttons or {}) do buttons[b] = true end
                check(type(leg.frames) == "number" and leg.frames > 0 and leg.frames <= 12000, "route frame bound")
                for _ = 1, leg.frames do step(buttons) end
            end
        end
    end

    local ok, fatal = pcall(function()
        pack = read_json(cfg.profile)
        check(pack.schema == "gen4-profile-v1", "profile schema")
        title = assert(pack.titles[cfg.title], "profile title:" .. cfg.title)
        check(title.rom.sha1:lower() == cfg.rom_sha1:lower(), "profile/file hash mismatch")
        emu.limitframerate(true); client.speedmode(cfg.requested_rate)
        -- boot: normal buttons (A/Start pulses) until the field is idle; the canary arms at cfg.arm_after
        local x = H.boot("normal", cfg.boot_frames, idle_field, function() local fs = read(symbol("sFieldSysPtr")); return fs ~= 0 and read(fs + title.profile.probe_field.live) ~= 0 end, step, emu.framecount)
        check(x.overworld, "CONTINUE did not reach an idle field")
        check(armed_frame, "canary was never armed during boot")
        verify("pre-control")
        -- b: known positive over the vblank counter's low byte (gSystem + system.vblank_counter_off)
        local sysaddr = symbol("gSystem") + assert(title.profile.system.vblank_counter_off, "profile.system.vblank_counter_off")
        obs.known_positive = M.control_known_positive(
            {write = function(_, t) memory.write_u8(sysaddr, t[1], BUS) end, read = function() return {memory.read_u8(sysaddr, BUS)} end},
            function() step({}) end, 120, cfg.seed)
        -- c: the host rewrites one span byte mid-run
        obs.host_rewrite = M.control_host_rewrite(watch, emu.framecount())
        -- field idle, then the pack route (battle, menu) and persistence route (menu, SAVE)
        idle(cfg.idle_frames)
        play_route(cfg.route)
        idle(cfg.idle_frames)
        verify("final")
    end)
    if not ok then
        if type(fatal) == "table" and fatal.open then fatal_open = fatal.open else errors.run = tostring(fatal) end
    end
    local rows = M.evaluate(obs)
    local lines, overall = {}, "PASS"
    obs.span_foreign_total = obs.span_foreign_total or 0
    obs.span_events = watch and watch.events or {}
    obs.arena_foreign_checks = obs.arena_foreign_checks or 0
    for _, row in ipairs({"a", "b", "c", "d", "e", "f", "g", "h", "i"}) do
        local r = rows[row]
        local status, reason = r.status, r.reason
        if errors.run and status ~= "FAIL" then status, reason = "FAIL", "run aborted: " .. errors.run end
        if fatal_open and status == "PASS" then status, reason = "OPEN", fatal_open end
        if status == "FAIL" then overall = "FAIL" elseif status == "OPEN" and overall == "PASS" then overall = "OPEN" end
        local payload = {schema = "gen4-mailbox-row-v1", run_id = cfg.run_id, title = cfg.title, rom_sha1 = cfg.rom_sha1, level = "PHYSICAL",
            canary = cfg.canary, seed = cfg.seed, span = cfg.span, arena = cfg.arena, fill = cfg.fill, reason = reason, observation = obs,
            source_head = cfg.source_head, script_sha256 = cfg.code_sha256, profile_sha256 = cfg.profile_sha256,
            module_sha256 = cfg.module_sha256, surface_sha256 = cfg.surface_sha256, receipt_kind = cfg.receipt_kind,
            setup = cfg.setup or "NATIVE", callback_errors = 0, advanced_frames = advanced, check_every = cfg.check_every,
            elapsed_clock_seconds = os.clock() - started}
        lines[#lines + 1] = "PROBE " .. row .. " " .. status .. " " .. assert(json.encode(payload))
    end
    lines[#lines + 1] = "RESULT: " .. overall
    local f = assert(io.open(out, "w"), "cannot publish mailbox receipt: " .. out)
    f:write(table.concat(lines, "\n"), "\n"); f:close(); pcall(client.exit)
end
run()
return M
