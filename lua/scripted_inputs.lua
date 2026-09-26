-- Shared synchronous input-step host. No game facts, routes, memory or emulator globals.
-- The caller owns point construction, terminal meaning, request policy and cleanup.
local S = {}
local LIMIT = 1000000

local function integer(value, low, high, name)
    assert(type(value) == "number" and value % 1 == 0 and value >= low and value <= high,
        "invalid " .. name)
    return value
end

function S.new(io)
    assert(type(io) == "table" and type(io.step) == "function" and type(io.frame) == "function",
        "injected step and frame functions required")
    assert(type(io.idle) == "table" and next(io.idle) ~= nil, "explicit idle button map required")
    local idle = {}
    for key, value in pairs(io.idle) do
        assert(type(key) == "string" and key ~= "" and value == false, "idle buttons must all be false")
        idle[key] = false
    end
    local step, frame = io.step, io.frame
    local function clock()
        return integer(frame(), 0, 9007199254740991, "frame clock")
    end
    local function buttons(raw)
        assert(type(raw) == "table", "driver must return a button table")
        local result = {}
        for key in pairs(idle) do result[key] = false end
        for key, value in pairs(raw) do
            assert(idle[key] ~= nil and type(value) == "boolean", "unknown/nonboolean input button")
            result[key] = value
        end
        return result
    end
    local function advance(raw)
        local before = clock()
        step(buttons(raw))
        assert(clock() == before + 1, "step must advance exactly one frame")
    end
    local self = {}

    function self.idle(frames)
        integer(frames, 0, LIMIT, "idle frame bound")
        for _ = 1, frames do advance(idle) end
        return frames
    end

    function self.run(spec, decide, on_phase, on_request)
        assert(type(spec) == "table" and type(spec.name) == "string" and spec.name ~= "", "named step specification required")
        assert(type(spec.terminal) == "string" and spec.terminal ~= "", "explicit terminal phase required")
        assert(type(decide) == "function", "pure driver callback required")
        assert(on_phase == nil or type(on_phase) == "function", "phase callback must be a function")
        assert(on_request == nil or type(on_request) == "function", "request callback must be a function")
        local bound = integer(spec.max_frames, 1, LIMIT, "total frame bound")
        local phase_bound = integer(spec.max_phase_frames, 1, bound, "phase frame bound")
        local stable = integer(spec.settle_frames or 1, 1, bound, "terminal settling bound")
        local trace_bound = integer(spec.max_phase_changes or 256, 1, LIMIT, "phase trace bound")
        assert(type(spec.terminal_idle) == "boolean", "terminal idle policy required")
        local may_park = spec.phase_callback_may_advance
        assert(may_park == nil or type(may_park) == "boolean", "phase callback policy must be boolean")
        local start, previous, phase_frames, settled = clock(), nil, 0, 0
        local trace, requests = {}, 0
        for iteration = 1, bound do
            local current = clock()
            local raw, phase, point, request = decide(current, iteration)
            assert(clock() == current, "driver advanced a frame outside the host")
            local pressed = buttons(raw)
            assert(type(phase) == "string" and phase ~= "" and #phase <= 256, "driver must return a bounded phase name")
            if phase ~= previous then
                assert(#trace < trace_bound, spec.name .. ": phase trace bound exceeded")
                trace[#trace + 1] = {phase=phase, frame=current, iteration=iteration}
                previous, phase_frames = phase, 0
                if on_phase then on_phase(spec.name, phase, current, point) end
                -- Opt-in park: frames the callback spends are not iterations, and the point and
                -- buttons decided before it stand. Its own wait is the only bound on them.
                local after = clock()
                assert(after == current or (may_park and after > current),
                    "phase callback advanced a frame outside the host")
            end
            phase_frames = phase_frames + 1
            assert(phase_frames <= phase_bound, spec.name .. ": phase made no bounded progress: " .. phase)
            if request ~= nil then
                assert(type(request) == "table" and on_request ~= nil, spec.name .. ": request handler required")
                assert(on_request(request, point, current) == true, spec.name .. ": request was not acknowledged")
                assert(clock() == current, "request handler advanced a frame outside the host")
                requests = requests + 1
            end
            settled = phase == spec.terminal and settled + 1 or 0
            if settled >= stable then
                if spec.terminal_idle then advance(idle) end
                return {name=spec.name, terminal=spec.terminal, iterations=iteration,
                    frames=clock()-start, start_frame=start, end_frame=clock(), trace=trace, requests=requests}
            end
            advance(pressed)
        end
        error(spec.name .. ": route made no bounded progress (" .. bound .. " frames)", 0)
    end

    return self
end

return S
