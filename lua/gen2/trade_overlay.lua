-- lua/gen2/trade_overlay.lua — the Gen 2 binder onto lua/gb_trade_lease.lua (P4.3b, O-27 D2-D4).
--
-- The cartridge (patch/gen2/src/trade_*.asm, P4.3a) owns the menus, the animation and the real
-- commit chain; the host answers the lease and stages the incoming mon. Every address comes from
-- the profile's generated overlay block (tools/gen_gen2_profile.py trade_block over the pinned
-- data/gen2/<title>_slink.sym): no trade block = no trade build = no binder.
--
-- Gen 2 differs from Gen 1 (lua/gen1/trade_overlay.lua):
--   * the lease is owned (mailbox + OFF_LEASE), not a borrowed union: no preimage backup;
--   * staging writes ONLY incoming OT slot 0 (+ its names), wOTPlayerName, count 1 and
--     species0 + $FF. OT slot 1 holds the native-private outgoing preimage through the held
--     lease (trade_snapshot.asm); this binder's own permit cannot reach it;
--   * D3 (check, before any write): a mail holder or an item this cartridge cannot hold is
--     refused, never stripped. The holdable set is the pack's items.json, identical to the
--     asm's SlinkTradeAllowedItems table (tests pin it).
local module_dir = debug.getinfo(1, "S").source:match("^@(.+[/\\])[^/\\]+$")
local Lease = dofile(assert(module_dir, "gen2/trade_overlay.lua must be dofile'd by path") ..
                     "../gb_trade_lease.lua")
local T = {}
local valid_bytes = Lease.valid_bytes

-- patch/gb/slink_abi.inc: the SLNK beacon, ABI 3, caps at +8. CAP is the proposed
-- SLINK_CAP_TRADE (1 << 4; phone owns 1 << 3): the asm does not advertise it yet (FOR CODEX).
T.BEACON, T.ABI_VERSION, T.OFF_CAPS, T.CAP = {0x53, 0x4C, 0x4E, 0x4B}, 3, 8, 0x10
T.PROMPT, T.APPLY = Lease.PROMPT, Lease.APPLY
T.TERMINATOR, T.GLYPH_MIN = 0x50, 0x60 -- trade_service.asm SlinkTradeCheckName

--- items.json -> {[id] = true} for every id a mon may carry through a trade (0 = none).
--- The adapter's is_valid_held_item rule (server/adapters/gen2_gsc.py): not a placeholder, not a
--- key item, not CANT_TOSS (permissions bit 7), not mail.
function T.holdable(items)
    local out = {[0] = true}
    for id, row in pairs(items.items) do
        if not row.placeholder and not row.key_item and not row.mail
           and math.floor(row.permissions / 128) % 2 == 0 then
            out[tonumber(id)] = true
        end
    end
    return out
end

local function spans_of(profile)
    local ov, d = profile.overlay, profile.derived
    local ram, name = ov.trade.ram, d.name_length
    local lease = {bank = 0, addr = ov.ram.wSlinkMailbox + Lease.OFF_LEASE, n = Lease.LEASE_SIZE}
    local function at(sym, n) return {bank = ram[sym].bank, addr = ram[sym].addr, n = n} end
    return lease, {
        player = at("wOTPlayerName", name),
        count = at("wOTPartyCount", 1),
        species = at("wOTPartySpecies", 2),        -- species0 + the $FF terminator
        mon = at("wOTPartyMon1", d.party_struct_size),
        ot = at("wOTPartyMonOTs", name),           -- slot 0 only
        nick = at("wOTPartyMonNicknames", d.mon_name_length),
    }
end

--- The trade's own write window: the 16 lease bytes and the six slot-0 staging spans, nothing
--- else (so OT slot 1 is unreachable), each re-checked mapped (WRAMX bank 1) at write time.
function T.writes(io, Permit, profile)
    local lease, stage = spans_of(profile)
    local spans = {lease}
    for _, s in pairs(stage) do spans[#spans + 1] = s end
    local function span_of(addr, n)
        for _, s in ipairs(spans) do
            if addr >= s.addr and addr + n <= s.addr + s.n then return s end
        end
    end
    local permit = Permit.new({
        write_u8 = function(addr, value, domain) return io.write_u8(addr, value, domain) end,
        domains = {["System Bus"] = {
            bounds = function(addr, n, reason) return reason == "trade" and span_of(addr, n) ~= nil end,
            mapped = function(addr, n)
                local s = span_of(addr, n)
                return s ~= nil and io.bank_valid(s.bank, addr, n) == true
            end,
            pointer_stable = function() return true end, -- fixed symbols from the pinned .sym
        }},
        lifetime = {capture = function() return io.framecount() end,
                    valid = function(token) return token == io.framecount() end},
        provenance = function(domain, addr, n, reason)
            return {addr = addr, n = n, why = reason, domain = domain, frame = io.framecount()}
        end,
    })
    return {
        log = permit.log,
        arm = function() return permit:arm("trade") end,
        disarm = function() permit:disarm() end,
        write_bytes = function(_, addr, bytes) return permit:write_bytes("System Bus", addr, bytes) end,
    }
end

--- A trainer name (the server's partner_name, decoded from the partner's hello) -> n bytes in the
--- pack charmap, or nil when nothing encodes. Only font glyphs (>= GLYPH_MIN) are kept, so the
--- result always passes SlinkTradeCheckName; control codes and unmapped characters are dropped.
function T.encode_name(charmap, text, n)
    if type(text) ~= "string" or not charmap then return nil end
    local enc, out = charmap.encoding, {}
    for ch in text:gmatch(utf8.charpattern) do
        local code = enc[ch]
        if type(code) == "number" and code >= T.GLYPH_MIN and code <= 0xFF and #out < n - 1 then
            out[#out + 1] = code
        end
    end
    if #out == 0 then return nil end
    while #out < n do out[#out + 1] = T.TERMINATOR end
    return out
end

local function valid_name(bytes, first, last)
    for i = first, last do
        if bytes[i] == T.TERMINATOR then return true end
        if bytes[i] < T.GLYPH_MIN then return false end
    end
    return false
end
local function copy(bytes, first, last)
    local out = {}
    for i = first, last do out[#out + 1] = bytes[i] end
    return out
end

--- profile: the selected title profile with overlay.trade; io: read_u8/read_range/bank_valid/
--- write_u8/framecount; Permit: lua/write_permit.lua; holdable: T.holdable(items); charmap: the
--- pack's charmap.lua (partner names).
--- Returns the lease (gb_trade_lease) with: arm(command, own_slot, token4, {blob = 70 bytes,
--- partner_name = string or nil}),
--- advertised(), closed(), withdraw(), hooks {label = {bank, addr}}, writes. Every mutating call
--- runs inside the trade permit (armed and disarmed here), so callers never arm it.
function T.new(profile, io, Permit, holdable, charmap)
    local ov = assert(profile.overlay and profile.overlay.trade and profile.overlay, "overlay.trade block required")
    assert(type(holdable) == "table", "holdable item set required")
    local d = profile.derived
    local lease_span, st = spans_of(profile)
    local S, NAME = d.party_struct_size, d.name_length
    local BLOB = S + NAME + d.mon_name_length
    local writes = T.writes(io, Permit, profile)
    local mailbox = ov.ram.wSlinkMailbox

    local function check(p, token4)
        local blob = type(p) == "table" and p.blob
        if not valid_bytes(blob, BLOB) then return "invalid trade blob length" end
        if not valid_bytes(token4, 4) then return "invalid visit token" end
        if blob[1] < 1 or blob[1] > d.species_count then return "invalid incoming species" end
        if not holdable[blob[2]] then return "held item " .. blob[2] .. " refused (mail or not holdable here)" end
        if not valid_name(blob, S + 1, S + NAME) or not valid_name(blob, S + NAME + 1, BLOB) then
            return "invalid incoming OT name or nickname"
        end
    end
    local function stage(p)
        local blob = p.blob
        local ot = copy(blob, S + 1, S + NAME)
        -- wOTPlayerName is the partner TRAINER (trade_commit.asm copies it to wOTTrademonSenderName,
        -- vanilla link.asm fills it from the partner's player data): the server's partner_name, the
        -- incoming OT only when none was sent (a PROMPT; the APPLY restages with the name)
        writes:write_bytes(st.player.addr, T.encode_name(charmap, p.partner_name, NAME) or ot)
        writes:write_bytes(st.count.addr, {1})
        writes:write_bytes(st.species.addr, {blob[1], 0xFF})
        writes:write_bytes(st.mon.addr, copy(blob, 1, S))
        writes:write_bytes(st.ot.addr, ot)
        writes:write_bytes(st.nick.addr, copy(blob, S + NAME + 1, BLOB))
    end

    local self = Lease.new({lease = lease_span.addr, party_capacity = d.party_capacity,
                            check = check, stage = stage}, io, writes)
    self.writes = writes
    self.hooks = {}
    for label, site in pairs(ov.trade.rom) do self.hooks[label] = {bank = site.bank, addr = site.addr} end

    local function scoped(fn)
        return function(...)
            writes:arm()
            local out = table.pack(pcall(fn, ...))
            writes:disarm()
            if not out[1] then error(out[2], 0) end
            return table.unpack(out, 2, out.n)
        end
    end
    for _, k in ipairs({"answer_query", "answer_offer", "arm", "release"}) do self[k] = scoped(self[k]) end

    --- The running cartridge is a live SLink build advertising the trade capability.
    function self:advertised()
        for i = 1, 4 do if io.read_u8(mailbox + i - 1) ~= T.BEACON[i] then return false end end
        if io.read_u8(mailbox + 4) ~= T.ABI_VERSION then return false end
        return math.floor((io.read_u8(mailbox + T.OFF_CAPS) or 0) / T.CAP) % 2 == 1
    end
    --- SlinkTradeClose (or Init) zeroed the command: the cartridge ended the visit.
    function self:closed() return io.read_u8(lease_span.addr + 5) == 0 end
    --- Pull an armed, never-picked-up request so the dispatcher can never run it.
    self.withdraw = scoped(function()
        writes:write_bytes(lease_span.addr + 5, {0})
        self.expected, self.phase = nil, nil
    end)
    return self
end

return T
