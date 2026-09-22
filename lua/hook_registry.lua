-- Neutral hook lifecycle. No CPU, memory-domain, frame, or game policy defaults.
local Registry = {}
local owners, names, handles = {}, {}, {}

local function integer(n)
    return type(n) == "number" and n == math.floor(n) and n >= -9007199254740991 and n <= 9007199254740991
end
local function copy(value, seen)
    if type(value) ~= "table" then return value end
    assert(getmetatable(value) == nil, "plain descriptor/event tables required")
    seen = seen or {}
    assert(not seen[value], "cyclic descriptor/event table")
    seen[value] = true
    local result = {}
    for key, item in pairs(value) do result[key] = copy(item,seen) end
    seen[value] = nil
    return result
end

local function sequence(values)
    assert(type(values) == "table" and getmetatable(values) == nil, "plain site array required")
    local count, last = 0, 0
    for key in pairs(values) do
        assert(integer(key) and key >= 1, "site array index invalid")
        count, last = count+1, math.max(last,key)
    end
    assert(count == last and count > 0, "nonempty dense site array required")
    return count
end

function Registry.new(options)
    local state = {queue={},owned={},reserved={},closed=false,ready=false,registered=0,cleanup_errors={}}
    local self = {registered=0}
    local owner, unregister, capture, on_event, capacity

    function self:status()
        return {failed=state.failure,handler_error=state.handler_error,pending=#state.queue,
                closed=state.closed,registered=state.registered,cleanup_errors=copy(state.cleanup_errors)}
    end
    -- Read-only view for observers (e.g. a test tee): a detached copy, never the live queue.
    function self:peek() return copy(state.queue) end
    function self:drain()
        local result = state.queue
        state.queue = {}
        return result
    end
    function self:close()
        state.closed, state.ready = true, false
        local remaining, errors = {}, {}
        for i = #state.owned, 1, -1 do
            local handle = state.owned[i]
            local ok, result = pcall(unregister,handle)
            if not ok or result == false then
                table.insert(remaining,1,handle)
                errors[#errors+1] = tostring(handle) .. ": " .. tostring(ok and "unregister returned false" or result)
            else
                if handles[handle] == self then handles[handle] = nil end
            end
        end
        state.owned, state.cleanup_errors = remaining, errors
        if #remaining == 0 then
            for name in pairs(state.reserved) do if names[name] == self then names[name] = nil end end
            if owner and owners[owner] == self then owners[owner] = nil end
        end
        return #remaining == 0
    end

    local function callback(site,...)
        -- handler_error is a status field, not a kill switch: a handler fault is contained
        -- and later signals keep queuing (the capture/queue faults above do latch).
        if not state.ready or state.closed or state.failure then return end
        local ok, event = pcall(capture,copy(site),...)
        if not ok then state.failure=tostring(event); return end
        if event == nil then return end
        local queued, why = pcall(function()
            assert(type(event) == "table", "capture must return an event table or nil")
            assert(#state.queue < capacity, "engine signal buffer full; client stopped draining")
            local snapshot = copy(event)
            state.queue[#state.queue+1] = snapshot
            return copy(snapshot)
        end)
        if not queued then state.failure=tostring(why); return end
        if on_event then
            local handled, err = pcall(on_event,why)
            if not handled then state.handler_error=tostring(err) end
        end
    end

    local ok, why = pcall(function()
        assert(type(options) == "table", "registry options required")
        owner, capacity = options.owner, options.max_pending
        assert(type(owner) == "string" and owner:match("^[%w_.%-]+$"), "explicit owner namespace required")
        assert(not owners[owner], "hook owner namespace already active: " .. owner)
        assert(integer(capacity) and capacity > 0, "explicit positive queue bound required")
        for _, key in ipairs({"validate","register","unregister","valid_handle","capture"}) do
            assert(type(options[key]) == "function", key .. " callback required")
        end
        assert(options.on_event == nil or type(options.on_event) == "function", "on_event must be a function")
        assert(options.name_for_site == nil or type(options.name_for_site) == "function", "name_for_site must be a function")
        unregister, capture, on_event = options.unregister, options.capture, options.on_event
        owners[owner] = self
        local prepared, ids = {}, {}
        -- Every descriptor and name is validated before any external registration.
        for i = 1, sequence(options.sites) do
            local site = copy(options.sites[i])
            assert(type(site.id) == "string" and site.id:match("^[%w_.%-]+$") and not ids[site.id], "unique site id required")
            ids[site.id] = true
            local checked = copy(options.validate(copy(site)))
            assert(type(checked) == "table" and checked.id == site.id, "validator must preserve site id")
            local name = options.name_for_site and options.name_for_site(copy(checked)) or owner .. ":" .. site.id
            assert(type(name) == "string" and name ~= "" and not names[name], "hook name already owned or invalid: " .. tostring(name))
            names[name], state.reserved[name] = self, true
            prepared[i] = {site=checked,name=name}
        end
        for _, descriptor in ipairs(prepared) do
            local site = descriptor.site
            local handle = options.register(copy(site),function(...) callback(site,...) end,descriptor.name)
            assert(options.valid_handle(handle) == true, "engine signal registration failed: " .. site.id)
            assert(not handles[handle], "engine signal registration returned an already owned handle: " .. site.id)
            handles[handle] = self
            state.owned[#state.owned+1] = handle
            state.registered = state.registered+1
            self.registered = state.registered
        end
        state.ready = true
    end)
    if not ok then
        state.failure = tostring(why)
        local cleaned = self:close()
        local message = state.failure
        if not cleaned then message = message .. "; cleanup failed: " .. table.concat(state.cleanup_errors,"; ") end
        return nil,message,self
    end
    return self
end

return Registry
