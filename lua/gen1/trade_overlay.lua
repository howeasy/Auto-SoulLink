-- Foreground SLINK TRADE overlay over the borrowed serial/map tile union.
-- The cartridge owns prompts and physical mutation. All host writes use the
-- injected writes.lua instance, which must be armed for this frame.
-- The lease framing (SLT1 frame, commands, visit/stale-token refusal) is the shared
-- lua/gb_trade_lease.lua (P4.3c); this binder supplies the Gen 1 lease address, the
-- 66-byte mon payload check and its enemy-slot staging + union backup.
local module_dir = debug.getinfo(1, "S").source:match("^@(.+[/\\])[^/\\]+$")
local Lease = dofile(assert(module_dir, "gen1/trade_overlay.lua must be dofile'd by path") ..
                     "../gb_trade_lease.lua")
local T = {}
local valid_bytes = Lease.valid_bytes
local function copy(bytes, first, last)
    local out = {}
    for i = first, last do out[#out + 1] = bytes[i] end
    return out
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
    local mon_len = d.party_struct_size + 2 * d.name_length

    local function check(p, token4)
        if not valid_bytes(p.blob, mon_len) or
           not valid_bytes(p.name, d.name_length) or not valid_bytes(token4, 4) then
            return "invalid trade blob, name or token length"
        end
        if p.blob[1] == 0 or p.blob[1] == 0xFF or
           token4[1] + token4[2] + token4[3] + token4[4] == 0 then
            return "invalid incoming species or zero token"
        end
    end
    local function stage(p, preimage)
        local blob66 = p.blob
        local mon = {species = blob66[1], blob = copy(blob66, 1, d.party_struct_size),
                     ot = copy(blob66, d.party_struct_size + 1,
                               d.party_struct_size + d.name_length),
                     nick = copy(blob66, d.party_struct_size + d.name_length + 1, mon_len)}
        -- native_trade.asm:85-99,133-163 consumes enemy slot0; prompt.asm:41-60
        -- checks the same staging. writes.lua owns the count/species/struct/names.
        writes:write_enemy_party({mon})
        writes:write_bytes(ram.wLinkEnemyTrainerName, p.name)
        writes:write_bytes(backup, preimage)
    end

    local self = Lease.new({lease = overlay, party_capacity = d.party_capacity,
                            check = check, stage = stage}, io, writes)
    local lease_arm = self.arm
    function self:arm(command, own_slot, blob66, partner_name11, token4)
        return lease_arm(self, command, own_slot, token4, {blob = blob66, name = partner_name11})
    end
    self.service_address = function() return T.service_address(profile) end
    return self
end

return T
