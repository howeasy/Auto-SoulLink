-- Read-only Polished exec-callback PC probe; wrong banks retain at most 16 rows per site.
-- Setup is PLAYED: the supplied route includes native boot/CONTINUE/battle input.
-- No client, synthetic battle, warp, guest-memory write, or CPU/register mutation.
local L = dofile(assert(os.getenv("SLINK_ROOT")) .. "/tools/polished_live/pol_lib.lua")
local config
local trace, hits, protected_hits, elapsed = {}, 0, 0, 0
local guest_writes, cpu_changes, driver_errors = 0, 0, 0
local wrong_bank_sample_limit = 16
local hook_counts = {}
for _, site in ipairs({"gate", "next", "last"}) do
    hook_counts[site] = {total = 0, qualified = 0, wrong_pc = 0,
                         wrong_banks = {}, wrong_bank_samples = 0}
end
local function append(kind, extra)
    local e = {kind = kind, ord = #trace + 1, frame = emu.framecount()}
    if extra then for k, v in pairs(extra) do e[k] = v end end
    trace[#trace + 1] = e
end

-- Guard Lua mutation APIs, not native engine writes (normal play necessarily writes RAM).
-- A denied attempt is evidence of a probe violation even if the hook recorder overflowed.
local raw_memory, raw_emu = memory, emu
memory = setmetatable({}, {__index = function(_, name)
    if name:match("^write") then
        return function()
            guest_writes = guest_writes + 1
            if guest_writes == 1 then append("guest_write", {api = "memory." .. name}) end
            error("read-only probe denied memory." .. name, 0)
        end
    end
    return raw_memory[name]
end})
emu = setmetatable({}, {__index = function(_, name)
    if name == "setregister" then
        return function()
            cpu_changes = cpu_changes + 1
            if cpu_changes == 1 then append("cpu_change", {api = "emu.setregister"}) end
            error("read-only probe denied emu.setregister", 0)
        end
    end
    return raw_emu[name]
end})

local function rom_hex(addr)
    local bytes = {}
    local offset = 0x0F * 0x4000 + addr - 0x4000
    for i = 0, 5 do bytes[#bytes + 1] = memory.read_u8(offset + i, "ROM") end
    return L.hex(bytes)
end
local function recorder(kind, addr)
    return function()
        local counts = hook_counts[kind]
        hits, counts.total = hits + 1, counts.total + 1
        local bank, pc = L.bus(0xFF87), emu.getregister("PC")
        local matched = addr < 0x4000 or bank == 0x0F
        local qualified = matched and pc == addr
        if not matched then
            local key = string.format("%d", bank)
            counts.wrong_banks[key] = (counts.wrong_banks[key] or 0) + 1
            if counts.wrong_bank_samples >= wrong_bank_sample_limit then return end
            counts.wrong_bank_samples = counts.wrong_bank_samples + 1
        else
            if qualified then counts.qualified = counts.qualified + 1
            else counts.wrong_pc = counts.wrong_pc + 1 end
            if protected_hits >= config.trace_cap then return end
            protected_hits = protected_hits + 1
        end
        append(kind, {
            hook_addr = addr, pc = pc, sp = emu.getregister("SP"),
            bank = bank, matched = matched, qualified = qualified,
            mode = L.rw("wBattleMode"), trainer_class = L.rw("wOtherTrainerClass"),
            trainer_id = L.rw("wOtherTrainerID"), cur_ot_mon = L.rw("wCurOTMon"),
            cur_party_mon = L.rw("wCurPartyMon"), ot_party_count = L.rw("wOTPartyCount"),
            -- Always read the pinned bank via ROM, never accidentally read another bank's System Bus bytes.
            site_bytes = rom_hex(0x47DD), hook_bytes = rom_hex(addr),
        })
        -- Fail closed as soon as capacity is reached, even if there is no later hook.
        if matched and protected_hits == config.trace_cap then
            append("overflow", {cap = config.trace_cap})
        end
    end
end

local function play()
    config = L.json.decode(L.slurp(assert(os.getenv("POL_PROBE_CONFIG"))))
    L.hook_at("rival_probe_gate", 0x0F, 0x47DD, recorder("gate", 0x47DD))
    L.hook_at("rival_probe_next", 0x0F, 0x47E0, recorder("next", 0x47E0))
    L.hook_at("rival_probe_last", 0x0F, 0x480D, recorder("last", 0x480D))
    client.speedmode(400)
    for _, step in ipairs(config.steps) do
        local buttons = {}
        for _, button in ipairs(step.buttons) do buttons[button] = true end
        for _ = 1, step.frames do
            L.frame(buttons)
            elapsed = elapsed + 1
        end
    end
    while elapsed < config.frames do
        L.frame()
        elapsed = elapsed + 1
    end
end

local ok, err = pcall(play)
if not ok then
    driver_errors = driver_errors + 1
    append("driver_error", {error = tostring(err)})
end
local final = {completed = ok, elapsed = elapsed, guest_writes = guest_writes,
               cpu_changes = cpu_changes, hook_hits = hits, driver_errors = driver_errors,
               wrong_bank_sample_limit = wrong_bank_sample_limit, hook_counts = hook_counts}
append("final", final)
final = trace[#trace]

-- Independent, small JSON encoder for the minimal failure record. Never retry the primary.
local function fallback_json(value)
    local t = type(value)
    if t == "string" then
        return '"' .. value:gsub('[%z\1-\31\\"]', function(c)
            return string.format("\\u%04x", string.byte(c))
        end) .. '"'
    elseif t == "number" or t == "boolean" then return tostring(value)
    elseif t == "table" then
        local parts = {}
        if #value > 0 then
            for _, v in ipairs(value) do parts[#parts + 1] = fallback_json(v) end
            return "[" .. table.concat(parts, ",") .. "]"
        end
        for k, v in pairs(value) do
            parts[#parts + 1] = fallback_json(tostring(k)) .. ":" .. fallback_json(v)
        end
        return "{" .. table.concat(parts, ",") .. "}"
    end
    return "null"
end
local encoded_ok, encoded = pcall(L.json.encode, trace)
if not encoded_ok or type(encoded) ~= "string" then
    driver_errors = driver_errors + 1
    final.completed, final.driver_errors = false, driver_errors
    local message = encoded_ok and "JSON encoder returned " .. type(encoded) or tostring(encoded)
    local failure = {kind = "driver_error", error = message}
    encoded = fallback_json({failure, final})
    ok, err = false, message
end
-- Bounded trace, one dump at the end; failures still reach finish.
local dump_ok, dump_err = pcall(function()
    local f = assert(io.open(L.RUN .. "/trace.json", "w"))
    local write_ok, write_err = pcall(function() assert(f:write(encoded)) end)
    f:close()
    assert(write_ok, write_err)
end)
L.check("played route completed without probe mutations",
        ok and dump_ok and guest_writes == 0 and cpu_changes == 0,
        not dump_ok and tostring(dump_err) or (ok and ("recorded " .. hits .. " hooks") or tostring(err)))
-- Driver PASS means complete recording only. Python alone decides PASS / NO_GATE_HIT / PC findings.
L.finish("rival-gate-probe recording")
