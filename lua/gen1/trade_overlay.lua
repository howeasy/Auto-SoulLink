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
    -- The vanilla companion patch's foreground poll anchor (trade_service.asm:67-68, bank
    -- $3F:$4500); an overlay build names its own through profile.trade.service (PLAN M3).
    local t = profile and profile.trade
    if t and t.service then return {bank = t.service.bank, addr = t.service.addr} end
    return {bank = 0x3F, addr = 0x4500}
end

-- Locate the instruction AFTER the ROM has retained the request on its stack and
-- restored the borrowed union via CopyData. Both shipped bodies have this exact
-- straight-line sequence (trade_service.asm save_overlay_on_stack + first CopyData).
-- Unlike SlinkForeground/service entry, reaching this point proves all ROM guards ran.
function T.pickup_site(profile, read_rom_u8)
    local svc = T.service_address(profile)
    local lease = assert(profile.ram.wSerialPartyMonsPatchList)
    local backup = assert(profile.ram.wEnemyMons) + assert(profile.derived.battle_struct_size)
    local pattern = {0x21, lease & 0xFF, lease >> 8}
    for _ = 1, 8 do
        for _, byte in ipairs({0x2A, 0x57, 0x2A, 0x5F, 0xD5}) do pattern[#pattern+1] = byte end
    end
    for _, byte in ipairs({0x21, backup & 0xFF, backup >> 8, 0x11, lease & 0xFF,
                           lease >> 8, 0x01, 0x10, 0x00, 0xCD}) do
        pattern[#pattern+1] = byte
    end
    local found
    local first = svc.bank * 0x4000 + svc.addr - 0x4000
    for offset = first, math.min(first + 0x200, (svc.bank+1)*0x4000 - #pattern - 8) do
        local matches = true
        for i, byte in ipairs(pattern) do
            if read_rom_u8(offset+i-1) ~= byte then matches=false; break end
        end
        -- CopyData is in ROM0 on both foundations; the call must return here.
        if matches and read_rom_u8(offset+#pattern+1) < 0x40 then
            assert(not found, "ambiguous native trade restore anchor")
            local after = offset + #pattern + 2
            local hex = {}
            for i = 0, 5 do hex[#hex+1] = string.format("%02X", read_rom_u8(after+i)) end
            found = {bank=svc.bank, address=0x4000+after%0x4000, rom_offset=after,
                     capture_offset=0, expected_hex=table.concat(hex),
                     symbol="SlinkTradeService (after lease restore)"}
        end
    end
    assert(found, "native trade restore anchor missing")
    return found
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

    local function consumed(sp, expected)
        if sp == nil then return false end -- foreground poll; no consumption witness
        if type(sp) ~= "number" or sp % 1 ~= 0 or sp < 0xC000 or sp > 0xDFF0 then
            return nil, "native trade restore SP outside WRAM"
        end
        local changed = false
        for i = 1, 16 do
            -- Eight DE pairs were pushed in order: stack low-to-high is the reversed frame.
            if io.read_u8(sp+16-i) ~= expected[i] then return nil, "native trade retained request differs" end
            local current = io.read_u8(overlay+i-1)
            if current ~= io.read_u8(backup+i-1) then return nil, "native trade restore differs from backup" end
            changed = changed or current ~= expected[i]
        end
        if not changed then return nil, "native trade restore left the published request unchanged" end
        return true
    end
    local self = Lease.new({lease = overlay, party_capacity = d.party_capacity,
                            check = check, stage = stage, pickup = consumed}, io, writes)
    local lease_arm = self.arm
    function self:arm(command, own_slot, blob66, partner_name11, token4)
        return lease_arm(self, command, own_slot, token4, {blob = blob66, name = partner_name11})
    end
    self.service_address = function() return T.service_address(profile) end
    self.pickup_site = function(read_rom_u8) return T.pickup_site(profile, read_rom_u8) end
    --- MAJOR-4: pull an armed, never-picked-up APPLY. The caller arms writes. The borrowed union gets
    --- its preimage back (arm backed it up); a clobbered frame is already the game's again.
    function self:withdraw()
        if self.phase ~= "armed" then return false end
        local clobbered = self:clobbered()
        if self.phase ~= "armed" then return false end -- an observed-entry ambiguity became a hold
        if not clobbered then
            local preimage = io.read_range(backup, 16)
            if not valid_bytes(preimage, 16) then return false end
            writes:write_bytes(overlay, preimage)
        end
        self.expected, self.phase, self.entry_observed = nil, nil, false
        return true
    end
    return self
end

return T
