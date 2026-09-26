-- Generation-neutral armed permit and validated byte writes.
-- Every domain, address bound, mapping/pointer rule, lifetime and receipt comes
-- from the binder. This module provides no game policy or frame-based default.
local Permit = {}
local unpack_values = table.unpack or unpack
local function pack(...) return { n = select("#", ...), ... } end
local function integer(v) return type(v) == "number" and v % 1 == 0 end
-- Lua builds may use binary64 numbers even for integral inputs. Every byte
-- address and the exclusive end must lie in its contiguous integer range.
local MAX_EXACT_INTEGER = 9007199254740991

function Permit.sequence_length(values, what)
    what = what or "payload"
    assert(type(values) == "table" and getmetatable(values) == nil, what .. ": plain array required")
    local count, last = 0, 0
    for key in next, values do
        assert(integer(key) and key >= 1, what .. ": positive integer indices required")
        count, last = count + 1, math.max(last, key)
    end
    assert(count == last, what .. ": array has a hole")
    return count
end

function Permit.new(policy)
    assert(type(policy) == "table", "write permit policy required")
    local emit = assert(policy.write_u8, "write_u8 required")
    assert(type(emit) == "function", "write_u8 must be a function")
    local domains = assert(policy.domains, "explicit domains required")
    assert(type(domains) == "table" and next(domains), "explicit nonempty domains required")
    for name, domain in pairs(domains) do
        assert(type(name) == "string" and name ~= "", "named domains required")
        for _, key in ipairs({ "bounds", "mapped", "pointer_stable" }) do
            assert(type(domain[key]) == "function", name .. "." .. key .. " policy required")
        end
    end
    local lifetime = assert(policy.lifetime, "explicit lifetime required")
    assert(type(lifetime.capture) == "function" and type(lifetime.valid) == "function",
           "lifetime.capture and lifetime.valid required")
    local provenance = assert(policy.provenance, "explicit provenance required")
    assert(type(provenance) == "function", "provenance must be a function")
    local active
    local self = { armed = nil, allow = nil, log = {} }

    function self:disarm()
        active, self.armed, self.allow = nil, nil, nil
    end

    -- Binder operations use the same error boundary for assertions outside a
    -- byte write. A successful guard preserves the binder's explicit lifetime.
    function self:guard(callback, ...)
        local result = pack(pcall(callback, ...))
        if not result[1] then self:disarm(); error(result[2], 0) end
        return unpack_values(result, 2, result.n)
    end

    function self:arm(reason, allow)
        self:disarm()
        return self:guard(function()
            assert(type(reason) == "string" and reason ~= "", "arm needs a reason")
            assert(allow == nil or type(allow) == "function", "allow must be a predicate")
            local token = lifetime.capture(reason)
            assert(token ~= nil, "lifetime capture returned no token")
            active = { reason = reason, allow = allow, token = token }
            self.armed, self.allow = reason, allow
        end)
    end

    function self:scope(reason, allow, callback, ...)
        self:arm(reason, allow)
        local result = pack(pcall(callback, ...))
        self:disarm()
        if not result[1] then error(result[2], 0) end
        return unpack_values(result, 2, result.n)
    end

    local function snapshot_span(span)
        assert(type(span) == "table" and getmetatable(span) == nil, "write span: plain table required")
        for key in next, span do
            assert(key == "domain" or key == "addr" or key == "bytes", "write span: unsupported field")
        end
        local domain_name, addr, bytes = span.domain, span.addr, span.bytes
        local domain = assert(domains[domain_name], "write refused: unknown domain")
        assert(integer(addr), "write refused: integer address required")
        local n = Permit.sequence_length(bytes, "write payload")
        local limit = addr + n
        assert(addr >= -MAX_EXACT_INTEGER and addr <= MAX_EXACT_INTEGER
               and integer(limit) and limit >= addr and limit <= MAX_EXACT_INTEGER
               and limit - addr == n,
               "write refused: interval arithmetic overflow")
        local payload = {}
        for i = 1, n do
            local value = bytes[i]
            assert(integer(value) and value >= 0 and value <= 255, "byte out of range")
            payload[i] = value
        end
        return { domain_name=domain_name, domain=domain, addr=addr, n=n, payload=payload }
    end

    local function current(permit, span)
        assert(active == permit, "write refused: permit replaced or disarmed")
        assert(lifetime.valid(permit.token, permit.reason), "write refused: permit lifetime expired")
        local domain, addr, n = span.domain, span.addr, span.n
        assert(domain.bounds(addr, n, permit.reason, permit.token), "write refused: interval outside domain bounds")
        assert(not permit.allow or permit.allow(span.domain_name, addr, n),
               string.format("write refused: %d byte(s) at $%X outside the %s window (W-7)",
                             n, addr, permit.reason))
        assert(domain.mapped(addr, n, permit.reason, permit.token), "write refused: mapped-bank policy")
        assert(domain.pointer_stable(addr, n, permit.reason, permit.token), "write refused: pointer stability policy")
    end

    function self:write_batch(spans)
        return self:guard(function()
            local permit = assert(active, "write refused: no armed write window (W-7)")
            local count = Permit.sequence_length(spans, "write batch")
            local prepared = {}
            -- Snapshot every descriptor and payload before any policy or I/O can
            -- observe them. A later invalid span cannot follow an earlier write.
            for i = 1, count do prepared[i] = snapshot_span(spans[i]) end
            assert(active == permit, "write refused: permit replaced or disarmed")
            assert(lifetime.valid(permit.token, permit.reason), "write refused: permit lifetime expired")
            for i = 1, count do current(permit, prepared[i]) end
            for i = 1, count do
                local span = prepared[i]
                local supplied = provenance(span.domain_name, span.addr, span.n, permit.reason, permit.token)
                assert(type(supplied) == "table", "provenance must produce a receipt")
                -- Each span owns its receipt fields even if a binder reuses a table.
                local receipt = {}
                for key, value in pairs(supplied) do receipt[key] = value end
                receipt.batch_index, receipt.batch_size = i, count
                span.receipt = receipt
            end
            -- Policies/provenance are trusted and side-effect-free. Recheck the
            -- whole prepared batch immediately before the first emission anyway.
            for i = 1, count do current(permit, prepared[i]) end
            for _, span in ipairs(prepared) do
                local completed, attempted = 0, 0
                local ok, why = pcall(function()
                    for i = 1, span.n do
                        current(permit, span)
                        attempted = i
                        emit(span.addr + (i - 1), span.payload[i], span.domain_name)
                        completed = i
                    end
                end)
                local receipt = span.receipt
                receipt.status, receipt.completed, receipt.attempted = ok and "written" or "error", completed, attempted
                receipt.error = not ok and tostring(why) or nil
                self.log[#self.log + 1] = receipt
                if not ok then error(why, 0) end
            end
        end)
    end

    function self:write_bytes(domain_name, addr, bytes)
        return self:write_batch({{ domain=domain_name, addr=addr, bytes=bytes }})
    end
    return self
end

return Permit
