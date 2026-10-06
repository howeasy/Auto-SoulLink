-- D3: read-only dispatcher-entry measurement. Native played input only, no lease publication.
-- All hook addresses and nine pinned byte VALUES come from Python's sym-derived input.json.
local L = dofile(assert(os.getenv("SLINK_ROOT")) .. "/tools/polished_live/pol_lib.lua")
local config = L.json.decode(L.slurp(assert(os.getenv("POL_PROBE_CONFIG"))))
local C = config.contract
local trace, recorded, dispatch_hits, prompt_hits = {}, 0, 0, 0
local guest_writes, cpu_changes = 0, 0
local phase, phase_frames = "setup", {}
local function append(kind, extra)
    local e = {kind = kind, ord = #trace + 1, frame = emu.framecount(), phase = phase}
    if extra then for k, v in pairs(extra) do e[k] = v end end
    trace[#trace + 1] = e
end

-- Guard PROBE writes, not ordinary native engine RAM writes caused by played input.
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

local function recorder(kind, addr)
    return function(bank_matched)
        local pc, bank = emu.getregister("PC"), L.bus(C.rombank_addr)
        local qualified = bank_matched and bank == C.bank and pc == addr
        if qualified then
            if kind == "dispatch" then dispatch_hits = dispatch_hits + 1 else prompt_hits = prompt_hits + 1 end
        end
        if recorded >= config.trace_cap then return end
        recorded = recorded + 1
        local sp, stack = emu.getregister("SP"), {}
        for i = 0, 27 do stack[i + 1] = L.bus((sp + i) % 0x10000) end
        local stack_match = true
        for _, pin in ipairs(C.pins) do
            if stack[pin.offset + 1] ~= pin.value then stack_match = false end
        end
        local e = {hook_addr = addr, pc = pc, sp = sp, bank = bank, matched = bank_matched,
                   qualified = qualified, stack = L.hex(stack), stack_match = stack_match,
                   svbk = L.bus(C.svbk_addr)}
        -- These are the dispatcher's actual System Bus loads, not flat WRAM bank-1 aliases.
        for field, symbol in pairs(C.fields) do e[field] = L.bus(L.SYM[symbol][2]) end
        e.engine_clean = e.svbk % 8 < 2 and e.script_mode == 0 and e.battle_mode == 0 and e.link_mode == 0
                         and e.paused == 0 and e.in_menu == 0 and e.vblank == 0
                         and e.map_status == C.map_status_handle
                         and math.floor(e.step_flags / C.step_continue_mask) % 2 == 0
                         and e.map_event_status == C.map_events_on
        -- Context eligibility ONLY. The unpublished lease still refuses actual prompt dispatch.
        e.context_accept = qualified and stack_match and e.engine_clean
        append(kind, e)
        if recorded == config.trace_cap then append("overflow", {cap = config.trace_cap}) end
    end
end

local function advance(buttons)
    L.frame(buttons)
    phase_frames[phase] = (phase_frames[phase] or 0) + 1
end
local function play()
    L.hook_at("dispatch_probe_entry", C.bank, C.dispatch_addr, recorder("dispatch", C.dispatch_addr))
    L.hook_at("dispatch_probe_prompt", C.bank, C.prompt_addr, recorder("prompt", C.prompt_addr))
    client.speedmode(400)
    local elapsed = 0
    for _, step in ipairs(config.steps) do
        phase = step.phase
        local buttons = {}
        for _, button in ipairs(step.buttons) do buttons[button] = true end
        for _ = 1, step.frames do advance(buttons) elapsed = elapsed + 1 end
    end
    phase = "setup" -- any spare observation budget is unclassified, never a mislabeled positive.
    while elapsed < config.frames do advance() elapsed = elapsed + 1 end
    append("final", {completed = true, elapsed = elapsed, phase_frames = phase_frames,
                     guest_writes = guest_writes, cpu_changes = cpu_changes,
                     dispatch_hits = dispatch_hits, prompt_hits = prompt_hits})
end
local ok, err = pcall(play)
if not ok then append("driver_error", {error = tostring(err)}) end
local f = assert(io.open(L.RUN .. "/trace.json", "w"))
f:write(L.json.encode(trace))
f:close()
L.check("played route recorded without probe mutations", ok and guest_writes == 0 and cpu_changes == 0,
        ok and ("dispatch hits " .. dispatch_hits .. ", prompt hits " .. prompt_hits) or tostring(err))
-- This RESULT means complete recording only; the Python oracle owns the measurement verdict.
L.finish("dispatch-probe recording")
