-- lua/gen3/signals.lua — Gen 3 game events detected from the engine's own execution.
--
-- Sites come from the pack's engine_signals.json (data/games/gen3_frlg, data/games/gen3_rr),
-- never from a literal in this file. A site record carries:
--
--   address         the function/anchor address (an EVEN Thumb address; never OR'd with 1)
--   capture_offset  the hook is registered at `address + capture_offset`
--   expected_hex    the bytes that must be at `address`, in ROM at load and on the bus at fire
--   rom_offset      the flat ROM file offset of `address`
--   mode            "thumb" | "arm"
--   point           the register names to snapshot when the site fires
--
-- Fail closed. If any site's expected bytes are not at its rom_offset, S.new refuses with a
-- named reason BEFORE registering anything; if a registration is refused mid-way (a null
-- GUID or an error), every id taken so far is unregistered again, so a refused build leaves
-- no hooks armed.
--
-- Fire-time contract (PLAN §5.2, receipts docs/gen3/probes/hooks_*_2026-09-21.txt):
-- mGBA hands the callback the address it was REGISTERED at, while R15 already points at the
-- next instruction (probe row a: expected_addr=0x0800051A, first_raw_r15=0x0800051C).
-- So the assertion is `callback address == address + capture_offset`, and raw_r15 / cpsr /
-- sp / frame are RECORDED separately, never used as the identity test. A fire whose
-- callback address disagrees is rejected and counted; it is never queued or dispatched.
--
-- Everything arrives through injected tables; no BizHawk global is named here:
--   io.read_u8/read_u16/read_u32(addr)   io.read_bytes(addr, len)   io.rom_read(off, len)
--   io.framecount()                      io.register(name) -> number ("R15", "CPSR", "R13")
--   ev.on_bus_exec(fn, addr, name) -> id  ev.unregister(id)
local S = { MAX_PENDING = 64 }

-- BizHawk's sentinel for a registration it could not honour. A string is truthy, so
-- `assert(id)` alone would arm nothing and believe it did. Compared with braces stripped
-- and case-folded, so any spelling of the all-zero GUID is refused.
S.NULL_GUID = "00000000-0000-0000-0000-000000000000"
local function is_null_guid(id)
    if type(id) ~= "string" then return false end
    return id:gsub("[{}]", ""):lower() == S.NULL_GUID
end

-- BizHawk's API members are `userdata`, not `function` (and so are lupa's Python stubs), so
-- callability is checked by type class, never by `type(f) == "function"`.
local function callable(v)
    local t = type(v)
    return t == "function" or t == "userdata" or t == "table"
end

local function hex_of(bytes)
    local out = {}
    for i = 1, #bytes do out[i] = string.format("%02X", bytes[i]) end
    return table.concat(out)
end

-- kind -> { filter = function(io, profile) -> bool, point = function(io, profile, site) }
-- Empty in the observer phase: every Gen 3 site's `point` is a list of CPU registers, which
-- the generic point below reads. Semantic RAM points land with the client (P4).
S.KINDS = {}

-- The default point: one entry per register the site lists under `point`.
local function generic_point(io, _profile, site)
    local out = {}
    for _, name in ipairs(site.point or {}) do out[name] = io.register(name) end
    return out
end

-- profile: the title's table from profile.json; sites: the artifact's `sites` table from
-- engine_signals.json (kind -> site); on_fire: optional kind -> function(signal), run
-- synchronously inside the hook.
function S.new(profile, sites, io, ev, on_fire)
    assert(type(sites) == "table", "engine sites table required")
    assert(type(io) == "table" and callable(io.rom_read) and callable(io.read_bytes)
           and callable(io.register) and callable(io.framecount), "injected io required")
    assert(type(ev) == "table" and callable(ev.on_bus_exec) and callable(ev.unregister),
           "injected event registrar required")
    local self = { pending = {}, hooks = {}, failure = nil, closed = false,
                   handler_error = nil, registered = 0, rejected = 0, dropped = 0 }
    on_fire = on_fire or {}

    -- Load-time anchor: every site's bytes must be in the ROM where the pack says.
    local bad = {}
    for kind, site in pairs(sites) do
        local n = #site.expected_hex // 2
        if type(site.rom_offset) ~= "number" or type(site.address) ~= "number"
           or hex_of(io.rom_read(site.rom_offset, n)) ~= site.expected_hex then
            bad[#bad + 1] = kind
        end
    end
    if #bad > 0 then
        table.sort(bad)
        error("engine sites differ from the ROM: " .. table.concat(bad, ", "), 0)
    end

    local function fire(kind, site, callback_address)
        if self.closed or self.failure then return end
        local hook_address = site.address + (site.capture_offset or 0)
        -- The identity test. mGBA reports the registered address; a disagreement means the
        -- callback is not this site's, so it is counted and dropped, never dispatched.
        if callback_address ~= nil and callback_address ~= hook_address then
            self.rejected = self.rejected + 1
            return
        end
        local spec = S.KINDS[kind] or {}
        if spec.filter and not spec.filter(io, profile, site) then return end
        local ok, why = pcall(function()
            local n = #site.expected_hex // 2
            assert(hex_of(io.read_bytes(site.address, n)) == site.expected_hex,
                   kind .. ": ROM bytes differ at fire time")
            if #self.pending >= S.MAX_PENDING then
                self.dropped = self.dropped + 1
                error("engine signal buffer full; client stopped draining", 0)
            end
            local cpsr = io.register("CPSR")
            local signal = {
                kind = kind, frame = io.framecount(),
                address = hook_address, callback_address = callback_address,
                -- recorded, never asserted on: R15 is the NEXT instruction inside the hook
                raw_r15 = io.register("R15"), cpsr = cpsr, sp = io.register("R13"),
                thumb = cpsr and (cpsr >> 5) & 1 or nil, mode = site.mode,
                point = (spec.point or generic_point)(io, profile, site),
            }
            self.pending[#self.pending + 1] = signal
            if on_fire[kind] then
                local hok, herr = pcall(on_fire[kind], signal)
                if not hok then self.handler_error = kind .. ": " .. tostring(herr) end
            end
        end)
        if not ok then self.failure = tostring(why) end
    end

    -- Register every site, or none: an incomplete arming is rolled back and re-raised.
    local function register_all()
        for kind, site in pairs(sites) do
            local hook_address = site.address + (site.capture_offset or 0)
            local id = ev.on_bus_exec(function(callback_address)
                fire(kind, site, callback_address and math.floor(callback_address) or nil)
            end, hook_address, "SLink-gen3-" .. kind)
            assert(id and not is_null_guid(id),
                   "engine signal registration failed: " .. kind)
            self.hooks[#self.hooks + 1] = id
            self.registered = self.registered + 1
        end
    end
    local armed, why = pcall(register_all)
    if not armed then
        for _, id in ipairs(self.hooks) do pcall(ev.unregister, id) end
        self.hooks, self.registered = {}, 0
        error(tostring(why), 0)
    end

    -- Hand the queued signals to the caller in arrival order and start a fresh queue.
    function self:drain()
        local out = self.pending
        self.pending = {}
        return out
    end

    function self:status()
        return { failed = self.failure, pending = #self.pending, closed = self.closed,
                 handler_error = self.handler_error, registered = self.registered,
                 rejected = self.rejected, dropped = self.dropped }
    end

    function self:close()
        self.closed = true
        for _, id in ipairs(self.hooks) do ev.unregister(id) end
        self.hooks = {}
    end

    return self
end

return S
