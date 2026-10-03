-- lua/gb_trade_lease.lua — the GB trade-lease framing (P4.3c, O-27 coordinator amendment).
--
-- One 16-byte lease frame drives the cartridge-native SLINK TRADE flow: magic "SLT1", version,
-- command, generation/ack publication, the visit token and the stale-token refusal. Gen 1 binds
-- it on its borrowed serial/map tile union (lua/gen1/trade_overlay.lua); Gen 2 binds it in the
-- mailbox at +OFF_LEASE (patch/gb/slink_abi.inc). Gen 3 does not (EWRAM seq/ack, lua/mailbox.lua).
-- Payload shape, item validation and staging stay per game: the binder's `check` and `stage`.
--
-- Frame (0-based): +0..3 magic, +4 version, +5 command, +6 game/host generation, +7 ack,
-- +8 result, +9 slot, +10 available, +11 eligibility mask, +12..15 visit token.
-- Line cites are the Gen 1 companion patch (patch/gen1/src/receptionist.asm, trade_service.asm).
local L = {}
L.MAGIC = {0x53, 0x4C, 0x54, 0x31} -- trade_service.asm:173-185; receptionist.asm:240-241
L.VERSION, L.QUERY, L.OFFER, L.PROMPT, L.APPLY, L.DONE, L.RELEASE = 1, 1, 2, 3, 5, 7, 8
-- receptionist.asm:171-173,240-241,457-466; trade_service.asm:72-88,113,122-143.
L.OFF_LEASE, L.LEASE_SIZE = 14, 16 -- slink_abi.inc SLINK_OFS_TRADE_LEASE / SLINK_TRADE_LEASE_SIZE
local MAGIC, VERSION = L.MAGIC, L.VERSION
local QUERY, OFFER, PROMPT, APPLY, DONE, RELEASE = L.QUERY, L.OFFER, L.PROMPT, L.APPLY, L.DONE, L.RELEASE

local function valid_bytes(bytes, n)
    if type(bytes) ~= "table" or #bytes ~= n then return false end
    for i = 1, n do
        local v = bytes[i]
        if type(v) ~= "number" or v < 0 or v > 255 or v ~= math.floor(v) then return false end
    end
    return true
end
L.valid_bytes = valid_bytes
local function same_token(a, b)
    for i = 13, 16 do if a[i] ~= b[i] then return false end end
    return true
end

--- spec (every field required, a missing one asserts):
---   lease          base address of the 16-byte frame
---   party_capacity slots; bounds offer/own slots and the eligibility mask (2^capacity)
---   check(payload, token4) -> nil | error string   (per-game payload validation, no writes)
---   stage(payload, preimage16)                      (per-game staging, before the frame publishes)
---   pickup(evidence, expected16) -> bool | nil,error (optional binder-owned consumption witness)
---     false = poll/no evidence; nil,error = native boundary reached but binding unverified (hold).
--- io needs read_u8/read_range; writes needs write_bytes (armed by the caller).
function L.new(spec, io, writes)
    assert(type(spec) == "table", "lease spec required")
    for _, k in ipairs({"lease", "party_capacity", "check", "stage"}) do
        assert(spec[k] ~= nil, "lease spec." .. k .. " required")
    end
    assert(type(io) == "table" and io.read_u8 ~= nil and io.read_range ~= nil, "injected read IO required")
    assert(type(writes) == "table" and writes.write_bytes ~= nil, "armed writes instance required")
    assert(spec.pickup == nil or type(spec.pickup) == "function", "pickup verifier must be a function")
    local overlay, capacity, check, stage = spec.lease, spec.party_capacity, spec.check, spec.stage
    local self = {expected = nil, phase = nil, visit_token = nil, entry_observed = false}

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
        if type(mask) ~= "number" or mask ~= math.floor(mask) or mask < 0 or mask >= 2 ^ capacity or
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
           bytes[10] < capacity and
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

    function self:arm(command, own_slot, token4, payload)
        if command ~= PROMPT and command ~= APPLY then return nil, "invalid trade command" end
        if type(own_slot) ~= "number" or own_slot ~= math.floor(own_slot) or
           own_slot < 0 or own_slot >= capacity then return nil, "invalid own slot" end
        local why = check(payload, token4)
        if why then return nil, why end
        if not valid_bytes(token4, 4) or token4[1] + token4[2] + token4[3] + token4[4] == 0 then
            return nil, "invalid or zero visit token"
        end
        local preimage = frame()
        if not preimage then return nil, "unreadable lease frame" end
        local previous = io.read_u8(overlay + 6)
        if type(previous) ~= "number" or previous < 0 or previous > 255 then
            return nil, "unreadable lease generation"
        end
        local generation = (previous + 1) % 256
        stage(payload, preimage)
        local bytes = {MAGIC[1], MAGIC[2], MAGIC[3], MAGIC[4], VERSION, command,
                       previous, previous, 0xFF, own_slot, 1, 0,
                       token4[1], token4[2], token4[3], token4[4]}
        -- service.asm:82-95 reads gen/ack/slot, restores backup before native
        -- UI or mutation. Host writes +6 last to publish the complete request.
        writes:write_bytes(overlay, bytes)
        writes:write_bytes(overlay + 6, {generation})
        bytes[7] = generation
        self.expected, self.phase, self.pickup_error, self.entry_observed = bytes, "armed", nil, false
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
        self.expected, self.phase, self.entry_observed = nil, nil, false
        return true
    end

    function self:observe_entry()
        if self.phase ~= "armed" or not self.expected then return false end
        self.entry_observed = true -- reset only when a new request is successfully armed
        return true
    end

    function self:hold_consumed(why)
        if self.phase ~= "armed" or not self.expected then return false end
        self.phase, self.pickup_error = "picked_up", tostring(why)
        return nil, self.pickup_error
    end

    function self:clobbered()
        if not self.expected then return false end
        if self.phase == "picked_up" or self.phase == "done" then return false end
        local current = frame()
        if completion(current) then return false end -- DONE is native progress
        local changed = current == nil
        if current then
            for i = 1, 16 do
                if current[i] ~= self.expected[i] then changed = true; break end
            end
        end
        if changed and spec.pickup and self.entry_observed then
            -- The entry was seen, but the exact consumption hit may have been dropped.
            -- A restored/clobbered borrowed union is now ambiguous: never re-stage over it.
            self:hold_consumed("service entry observed; consumption witness missing")
            return false
        end
        return changed
    end

    function self:picked_up(evidence)
        if self.phase ~= "armed" or not self.expected then return false end
        if spec.pickup then
            -- Borrowed-buffer binders prove consumption at their native restore boundary.
            -- A poll or a changed buffer alone must not revoke cancellation.
            local ok, verified, why = pcall(spec.pickup, evidence, self.expected)
            if not ok then verified, why = nil, "pickup witness error: " .. tostring(verified) end
            if verified == nil then
                -- The native boundary was reached. Never re-stage/cancel over native work
                -- merely because its retained request could not be bound to ours.
                return self:hold_consumed(why)
            end
            if not verified then return false end
        elseif self:clobbered() then
            return false -- owned-mailbox binders retain their qualified entry-hook contract
        end
        self.phase = "picked_up"
        return true
    end

    return self
end

return L
