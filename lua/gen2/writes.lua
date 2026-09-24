-- Source-derived Gen 2 party write binder. No emulator globals or activation.
-- Requires the shared write_permit factory; it does not copy permit lifecycle.
-- C = pokecrystal@7a7881d0d62e0ddbd82dcf10e7116807487ac651
-- G = pokegold@656583c939d30f920a316177311a502dd222b57c (Gold and Silver)
-- Party layout: C macros/ram.asm:7-44; G:7-42; constants/pokemon_data_constants.asm
-- C:75-113 / G:75-107. Status is +32, unused byte +33, HP is BE +34..35.
-- Native faint clears status: C engine/battle/core.asm:2656-2670; G:2551-2565.
-- Battle-to-party copy: C home/battle.asm:110-124; G:111-125.
--
-- Active faint (W-2, O-30): only inside the battle hold, before `call DetermineMoveOrder` in
-- BattleTurn (write_checkpoint.json battle_hold; docs/gen2/reviews/INBATTLE_FAINT_FACTS_2026-09-23.md).
-- BattleTurn+0 is NOT the site: C core.asm:160-208 / G:146-184 parse and execute a move before any
-- HasPlayerFainted. Conditional explode remains disabled; this module grants no write timing,
-- checkpoint, fixture, storage, client or physical qualification.
local W = {}

local function integer(value, low, high)
    return type(value) == "number" and value % 1 == 0 and value >= low and value <= high
end

-- battle (optional): write_checkpoint.json titles[t].battle_hold.write ({skip_action, targets}); nil
-- composes no in-battle write (faint_active_battler refuses).
function W.new(profile, io, Permit, policy, battle)
    assert(type(profile) == "table" and ({crystal=true, gold=true, silver=true})[profile.title],
           "selected generated Gen 2 profile required")
    assert(Permit and type(Permit.new) == "function" and type(Permit.sequence_length) == "function",
           "shared write permit factory required")
    assert(type(io) == "table" and type(io.write_u8) == "function" and type(io.bank_valid) == "function",
           "explicit write_u8 and bank_valid required")
    assert(type(policy) == "table", "explicit Gen 2 ownership policy required")
    for _, name in ipairs({"authorize", "pointer_stable", "provenance"}) do
        assert(type(policy[name]) == "function", "explicit policy." .. name .. " required")
    end
    assert(type(policy.lifetime) == "table" and type(policy.lifetime.capture) == "function"
           and type(policy.lifetime.valid) == "function", "explicit lifetime capture/valid required")
    local c, d, ram, banks = assert(profile.constants), assert(profile.derived),
                              assert(profile.ram), assert(profile.ram_bank)
    assert(c.PARTYMON_STRUCT_LENGTH == 48 and c.PARTY_LENGTH == 6 and c.MON_STATUS == 32 and c.MON_HP == 34,
           "unsupported or missing Gen 2 party field constants")
    assert(d.party_struct_size == c.PARTYMON_STRUCT_LENGTH and d.party_capacity == c.PARTY_LENGTH,
           "derived party geometry disagrees with source constants")
    local base, bank = ram.wPartyMons, banks.wPartyMons
    -- The permit domain is the whole party block wPartyCount..wPartyMonNicknamesEnd (C/G
    -- ram/wram.asm wPokemonData): the box executor rewrites count, species list, records and names.
    local block = ram.wPartyCount
    local block_length = c.PARTY_LENGTH * (c.PARTYMON_STRUCT_LENGTH + c.NAME_LENGTH + c.MON_NAME_LENGTH)
                         + c.PARTY_LENGTH + 2
    assert(integer(base, 0xC000, 0xDFFF) and integer(bank, 0, 7) and integer(block, 0xC000, 0xDFFF),
           "party WRAM coordinates required")
    assert(base == block + c.PARTY_LENGTH + 2 and banks.wPartyCount == bank
           and ram.wPartyMonNicknamesEnd == block + block_length, "party block geometry disagrees")
    assert((block < 0xD000 and bank == 0 and block + block_length <= 0xD000)
           or (block >= 0xD000 and bank >= 1 and block + block_length <= 0xE000),
           "party storage crosses its declared WRAM bank window")
    for name, offset in pairs({wPartyMon1=0, wPartyMon1Status=c.MON_STATUS, wPartyMon1HP=c.MON_HP}) do
        assert(ram[name] == base + offset and banks[name] == bank, "profile field/bank contradiction: " .. name)
    end
    assert(type(profile.artifact) == "string" and type(profile.rom_sha1) == "string"
           and #profile.rom_sha1 == 40, "profile artifact provenance required")

    -- O-30: the battle hold's exact targets (battle struct HP, the player action byte), each with its
    -- own WRAM bank; nothing else outside the party block is ever writable.
    local targets = {}
    if battle ~= nil then
        assert(type(battle) == "table" and type(battle.targets) == "table" and integer(battle.skip_action, 1, 255),
               "battle hold write facts required")
        for _, name in ipairs({"wBattleMonHP", "wBattlePlayerAction"}) do
            local t = assert(battle.targets[name], "battle target missing: " .. name)
            assert(integer(t.address, 0xC000, 0xDFFF) and integer(t.bank, 0, 7) and integer(t.width, 1, 2),
                   "battle target coordinates required: " .. name)
            targets[name] = t
        end
    end
    local function target_of(addr, n)
        for _, t in pairs(targets) do if addr == t.address and n == t.width then return t end end
    end
    local function in_block(addr, n) return addr >= block and addr + n <= block + block_length end
    local gate = Permit.new({
        write_u8 = io.write_u8,
        domains = {
            ["System Bus"] = {
                bounds = function(addr, n) return in_block(addr, n) or target_of(addr, n) ~= nil end,
                -- Same explicit platform mapping seam as gen2/reads.lua. There is
                -- no assumed DMG mode, selected WRAM bank or bank-switch fallback.
                mapped = function(addr, n)
                    local t = not in_block(addr, n) and target_of(addr, n)
                    return io.bank_valid(t and t.bank or bank, addr, n) == true
                end,
                pointer_stable = function(addr, n, _reason, token)
                    return policy.pointer_stable(token, addr, n) == true
                end,
            },
        },
        lifetime = {
            capture = policy.lifetime.capture,
            valid = function(token, reason) return policy.lifetime.valid(token, reason) == true end,
        },
        provenance = function(domain, addr, n, reason, token)
            local supplied = policy.provenance(domain, addr, n, reason, token)
            assert(type(supplied) == "table" and type(supplied.site) == "string" and supplied.site ~= "",
                   "write-site provenance required")
            local receipt = {}
            for key, value in pairs(supplied) do receipt[key] = value end
            receipt.domain, receipt.addr, receipt.n, receipt.why = domain, addr, n, reason
            receipt.title, receipt.artifact, receipt.rom_sha1 = profile.title, profile.artifact, profile.rom_sha1
            return receipt
        end,
    })
    -- Expose observations, not the raw domain writer or private permit state.
    local self = setmetatable({}, {__index=function(_, key)
        if key == "armed" or key == "log" then return gate[key] end
    end})
    function self:arm(reason, allow) return gate:arm(reason, allow) end
    function self:disarm() return gate:disarm() end

    local function slot_base(slot)
        assert(integer(slot, 0, c.PARTY_LENGTH - 1), "party slot out of range")
        return base + slot * c.PARTYMON_STRUCT_LENGTH
    end
    local function authorized(operation, request)
        assert(gate.armed, "write refused: no armed write window")
        assert(policy.authorize(operation, request, gate.armed) == true, "write ownership refused")
    end

    -- A byte builder seam, not identity selection. The required ownership policy
    -- must prove that this occupied slot/preimage belongs to the intended target.
    function self:write_party_bytes(slot, offset, bytes)
        return gate:guard(function()
            local address = slot_base(slot)
            local n = Permit.sequence_length(bytes, "party payload")
            assert(integer(offset, 0, c.PARTYMON_STRUCT_LENGTH)
                   and n <= c.PARTYMON_STRUCT_LENGTH - offset, "party span outside record")
            authorized("party_bytes", {slot=slot, offset=offset, length=n})
            return gate:write_bytes("System Bus", address + offset, bytes)
        end)
    end

    function self:faint_party_slot(slot, snapshot)
        return gate:guard(function()
            local address = slot_base(slot)
            assert(type(snapshot) == "table" and integer(snapshot.mode, 0, 2), "explicit battle snapshot required")
            assert(snapshot.link_mode == 0, "linked or unknown battle context refused")
            -- O-30: a bench faint inside the battle hold is qualified in every battle kind but link
            -- (facts doc §3); anywhere else in battle the special types stay refused.
            local held = gate.armed == "battle_hold"
            if snapshot.mode ~= 0 then
                assert(held or snapshot.battle_type == 0, "special battle context not qualified")
                assert(integer(snapshot.active_slot, 0, c.PARTY_LENGTH - 1), "active slot snapshot required")
                assert(snapshot.active_slot ~= slot, "active faint timing is not qualified") -- faint_active_battler owns it
            end
            authorized(held and "battle_faint" or "party_faint", {slot=slot, snapshot=snapshot})
            local status, hp = address + c.MON_STATUS, address + c.MON_HP
            -- The fields are discontiguous. The shared permit preflights BOTH
            -- complete spans, including mapping/pointer/provenance policies,
            -- before emission; the unused byte between them is never targeted.
            return gate:write_batch({
                {domain="System Bus", addr=status, bytes={0}},
                {domain="System Bus", addr=hp, bytes={0, 0}},
            })
        end)
    end

    -- The whole party block (box executor, lua/gen2/boxes.lua). The executor composes the block from
    -- the live read in the same held frame; ownership (receipt kind party_collection) is the policy's.
    function self:write_party_block(bytes)
        return gate:guard(function()
            assert(Permit.sequence_length(bytes, "party block") == block_length, "party block length mismatch")
            authorized("party_collection", {length=block_length})
            return gate:write_bytes("System Bus", block, bytes)
        end)
    end

    -- W-2, mirroring lua/gen1/writes.lua faint_active_battler: battle struct HP 0, the party mirror,
    -- and the corpse's action suppressed. Gen 2 differs on purpose: the site is the battle hold (not
    -- MainInBattleLoop+0, which Gen 2 lacks) and the suppression is wBattlePlayerAction = USEITEM,
    -- written LAST (not CANNOT_MOVE): DetermineMoveOrder then puts the player first, DoPlayerTurn
    -- returns, and Battle_PlayerFirst's HasPlayerFainted runs the native HandlePlayerMonFaint before
    -- the foe can move (facts doc §2, §6).
    function self:faint_active_battler(slot, snapshot)
        return gate:guard(function()
            assert(targets.wBattleMonHP, "no in-battle write composed")
            assert(gate.armed == "battle_hold", "active-battler faint only inside the battle hold")
            local address = slot_base(slot)
            assert(type(snapshot) == "table" and snapshot.link_mode == 0, "linked or unknown battle context refused")
            assert(snapshot.active_slot == slot, "target is not the active battler")
            authorized("battle_faint", {slot=slot, snapshot=snapshot, active=true})
            return gate:write_batch({
                {domain="System Bus", addr=targets.wBattleMonHP.address, bytes={0, 0}},
                {domain="System Bus", addr=address + c.MON_STATUS, bytes={0}},
                {domain="System Bus", addr=address + c.MON_HP, bytes={0, 0}},
                {domain="System Bus", addr=targets.wBattlePlayerAction.address, bytes={battle.skip_action}},
            })
        end)
    end
    function self:explode_active_battler()
        return gate:guard(function() error("conditional explode action-selection path is not qualified", 0) end)
    end
    return self
end

return W
