-- Foreground SLINK TRADE overlay over the borrowed serial/map tile union.
-- The cartridge owns prompts and physical mutation. All host writes use the
-- injected writes.lua instance, which must be armed for this frame.
local T = {}
local MAGIC = {0x53, 0x4C, 0x54, 0x31} -- trade_service.asm:173-185; receptionist.asm:240-241
local VERSION, QUERY, OFFER, PROMPT, APPLY, DONE, RELEASE = 1, 1, 2, 3, 5, 7, 8
-- receptionist.asm:171-173,240-241,457-466; trade_service.asm:72-88,113,122-143.

local function valid_bytes(bytes, n)
    if type(bytes) ~= "table" or #bytes ~= n then return false end
    for i = 1, n do
        local v = bytes[i]
        if type(v) ~= "number" or v < 0 or v > 255 or v ~= math.floor(v) then return false end
    end
    return true
end
local function copy(bytes, first, last)
    local out = {}
    for i = first, last do out[#out + 1] = bytes[i] end
    return out
end
local function same_token(a, b)
    for i = 13, 16 do if a[i] ~= b[i] then return false end end
    return true
end

function T.service_address(profile)
    -- The vanilla companion patch's fixed linked SECTION (trade_service.asm:67-68, bank
    -- $3F:$4500); an overlay build names its own through profile.trade.service (PLAN M3).
    local t = profile and profile.trade
    if t and t.service then return {bank = t.service.bank, addr = t.service.addr} end
    return {bank = 0x3F, addr = 0x4500}
end

function T.new(profile, io, writes)
    assert(type(profile) == "table" and type(profile.ram) == "table" and
           type(profile.derived) == "table", "Gen 1 title profile required")
    assert(type(io) == "table" and type(io.read_u8) == "function" and
           type(io.read_range) == "function", "injected read IO required")
    assert(type(writes) == "table" and type(writes.write_bytes) == "function" and
           type(writes.write_enemy_party) == "function", "armed writes.lua instance required")
    local ram, d = profile.ram, profile.derived
    local overlay = assert(ram.wSerialPartyMonsPatchList)
    local backup = assert(ram.wEnemyMons) + d.battle_struct_size
    -- trade_service.asm:6-7 aliases the 16-byte union and enemy slot1's
    -- otherwise unused first 16 bytes; trade_prompt.asm:36-40 uses +60 onward.
    local self = {expected = nil, phase = nil, visit_token = nil}

    local function frame()
        local bytes = io.read_range(overlay, 16)
        if not valid_bytes(bytes, 16) then return nil end
        return bytes
    end
    local function header(bytes, command)
        -- ASCII SLT1, version byte4, command byte5: receptionist.asm:240-241;
        -- service.asm:173-185 and :72-80. Lua array indices are one-based.
        if not bytes then return false end
        for i = 1, 4 do if bytes[i] ~= MAGIC[i] then return false end end
        return bytes[5] == VERSION and bytes[6] == command
    end
    local function completion(bytes)
        -- service.asm:108-125 publishes cmd7/result8, then ack gen at +7 LAST;
        -- :139-167 requires identical gen/token before host RELEASE cmd8.
        local expected = self.expected
        return expected and header(bytes, DONE) and bytes[7] == expected[7] and
               bytes[8] == expected[7] and bytes[10] == expected[10] and
               same_token(bytes, expected) and bytes[9] <= 3
    end

    function self:poll_query()
        local bytes = frame()
        -- receptionist.asm:161-185: game publishes generation at +6 last,
        -- waits <=30 frames until host writes matching ack generation at +7.
        if header(bytes, QUERY) and bytes[8] ~= bytes[7] then
            return {gen = bytes[7]}
        end
        return nil
    end

    function self:answer_query(gen, mask, token)
        local question = self:poll_query()
        if not question or question.gen ~= gen then return nil, "query generation changed" end
        if type(mask) ~= "number" or mask ~= math.floor(mask) or mask < 0 or mask >= 64 or
           not valid_bytes(token, 4) or (mask ~= 0 and
           token[1] + token[2] + token[3] + token[4] == 0) then
            return nil, "invalid eligibility mask or visit token"
        end
        -- receptionist.asm:189-214 checks available+mask+nonzero token after ack.
        writes:write_bytes(overlay + 10,
            {mask ~= 0 and 1 or 0, mask, token[1], token[2], token[3], token[4]})
        writes:write_bytes(overlay + 7, {gen}) -- publication last
        self.visit_token = mask ~= 0 and {token[1], token[2], token[3], token[4]} or nil
        return true
    end

    function self:poll_offer()
        local bytes = frame()
        -- receptionist.asm:439-466: cmd2, slot+9, new gen+6 after ack+7;
        -- :476-510 accepts a matching token and result 0/1 within 180 frames.
        -- receptionist.asm:202-221,450-455,497-506 carries this visit's
        -- nonzero token into the offer and verifies it again after our ACK.
        if header(bytes, OFFER) and self.visit_token and bytes[7] ~= bytes[8] and
           bytes[10] < d.party_capacity and
           bytes[13] == self.visit_token[1] and bytes[14] == self.visit_token[2] and
           bytes[15] == self.visit_token[3] and bytes[16] == self.visit_token[4] then
            return {slot = bytes[10], gen = bytes[7]}
        end
        return nil
    end

    function self:answer_offer(gen, ok)
        local offer = self:poll_offer()
        if not offer or offer.gen ~= gen then return nil, "offer generation changed" end
        if type(ok) ~= "boolean" then return nil, "offer decision must be boolean" end
        writes:write_bytes(overlay + 8, {ok and 0 or 1})
        writes:write_bytes(overlay + 7, {gen}) -- result before acknowledgement
        return true
    end

    function self:arm(command, own_slot, blob66, partner_name11, token4)
        if command ~= PROMPT and command ~= APPLY then return nil, "invalid trade command" end
        if type(own_slot) ~= "number" or own_slot ~= math.floor(own_slot) or
           own_slot < 0 or own_slot >= d.party_capacity then return nil, "invalid own slot" end
        if not valid_bytes(blob66, d.party_struct_size + 2 * d.name_length) or
           not valid_bytes(partner_name11, d.name_length) or not valid_bytes(token4, 4) then
            return nil, "invalid trade blob, name or token length"
        end
        if blob66[1] == 0 or blob66[1] == 0xFF or
           token4[1] + token4[2] + token4[3] + token4[4] == 0 then
            return nil, "invalid incoming species or zero token"
        end
        local preimage = frame()
        if not preimage then return nil, "unreadable borrowed union" end
        local previous = io.read_u8(overlay + 6)
        if type(previous) ~= "number" or previous < 0 or previous > 255 then
            return nil, "unreadable overlay generation"
        end
        local generation = (previous + 1) % 256
        local mon = {species = blob66[1], blob = copy(blob66, 1, d.party_struct_size),
                     ot = copy(blob66, d.party_struct_size + 1,
                               d.party_struct_size + d.name_length),
                     nick = copy(blob66, d.party_struct_size + d.name_length + 1,
                                 d.party_struct_size + 2 * d.name_length)}
        -- native_trade.asm:85-99,133-163 consumes enemy slot0; prompt.asm:41-60
        -- checks the same staging. writes.lua owns the count/species/struct/names.
        writes:write_enemy_party({mon})
        writes:write_bytes(ram.wLinkEnemyTrainerName, partner_name11)
        writes:write_bytes(backup, preimage)
        local bytes = {MAGIC[1], MAGIC[2], MAGIC[3], MAGIC[4], VERSION, command,
                       previous, previous, 0xFF, own_slot, 1, 0,
                       token4[1], token4[2], token4[3], token4[4]}
        -- service.asm:82-95 reads gen/ack/slot, restores backup before native
        -- UI or mutation. Host writes +6 last to publish the complete request.
        writes:write_bytes(overlay, bytes)
        writes:write_bytes(overlay + 6, {generation})
        bytes[7] = generation
        self.expected, self.phase = bytes, "armed"
        return generation
    end

    function self:poll_done()
        local bytes = frame()
        if not completion(bytes) then return nil end
        self.phase = "done"
        return {result = bytes[9]}
    end

    function self:release(generation)
        local done = self:poll_done()
        if not done or not self.expected or generation ~= self.expected[7] then
            return nil, "no matching trade completion"
        end
        if done.result == 2 then return nil, "uncertain native append; do not release" end
        -- service.asm:139-171: only cmd8 with matching gen/token releases the
        -- foreground lease and restores the backup over the borrowed union.
        writes:write_bytes(overlay + 5, {RELEASE})
        self.expected, self.phase = nil, nil
        return true
    end

    function self:clobbered()
        if not self.expected then return false end
        if self.phase == "picked_up" or self.phase == "done" then return false end
        local current = frame()
        if completion(current) then return false end -- DONE is native progress
        if not current then return true end
        for i = 1, 16 do
            if current[i] ~= self.expected[i] then return true end
        end
        return false
    end

    function self:picked_up()
        -- Call from the bank-qualified on_bus_exec at SlinkTradeService, BEFORE
        -- service.asm:90-95 restores the tile union. After pickup, the cartridge
        -- owns the borrowed bytes until DONE and clobber re-arming must stop.
        if self.phase ~= "armed" or self:clobbered() then return false end
        self.phase = "picked_up"
        return true
    end

    self.service_address = function() return T.service_address(profile) end
    return self
end

return T
