-- Read-only Polished exec-callback PC probe; launched only by rival_gate_probe.py.
-- Setup is PLAYED: the supplied route includes native boot/CONTINUE/battle input.
-- No client, synthetic battle, warp, guest-memory write, or CPU/register mutation.
local L = dofile(assert(os.getenv("SLINK_ROOT")) .. "/tools/polished_live/pol_lib.lua")
local config = L.json.decode(L.slurp(assert(os.getenv("POL_PROBE_CONFIG"))))
local trace, hits = {}, 0
local guest_writes, cpu_changes = 0, 0
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
    return function(matched)
        if hits >= config.trace_cap then return end
        hits = hits + 1
        append(kind, {
            hook_addr = addr, pc = emu.getregister("PC"), sp = emu.getregister("SP"),
            bank = L.bus(0xFF87), matched = matched,
            mode = L.rw("wBattleMode"), trainer_class = L.rw("wOtherTrainerClass"),
            trainer_id = L.rw("wOtherTrainerID"), cur_ot_mon = L.rw("wCurOTMon"),
            cur_party_mon = L.rw("wCurPartyMon"), ot_party_count = L.rw("wOTPartyCount"),
            -- Always read the pinned bank via ROM, never accidentally read another bank's System Bus bytes.
            site_bytes = rom_hex(0x47DD), hook_bytes = rom_hex(addr),
        })
        -- Fail closed as soon as capacity is reached, even if there is no later hook.
        if hits == config.trace_cap then append("overflow", {cap = config.trace_cap}) end
    end
end

local function play()
    L.hook_at("rival_probe_gate", 0x0F, 0x47DD, recorder("gate", 0x47DD))
    L.hook_at("rival_probe_next", 0x0F, 0x47E0, recorder("next", 0x47E0))
    L.hook_at("rival_probe_last", 0x0F, 0x480D, recorder("last", 0x480D))
    client.speedmode(400)
    local elapsed = 0
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
    append("final", {completed = true, elapsed = elapsed, guest_writes = guest_writes,
                     cpu_changes = cpu_changes, hook_hits = hits})
end

local ok, err = pcall(play)
if not ok then append("driver_error", {error = tostring(err)}) end
-- Bounded trace, one dump at the end; no per-frame console logging.
local f = assert(io.open(L.RUN .. "/trace.json", "w"))
f:write(L.json.encode(trace))
f:close()
L.check("played route completed without probe mutations", ok and guest_writes == 0 and cpu_changes == 0,
        ok and ("recorded " .. hits .. " hooks") or tostring(err))
-- Driver PASS means complete recording only. Python alone decides PASS / NO_GATE_HIT / PC findings.
L.finish("rival-gate-probe recording")
