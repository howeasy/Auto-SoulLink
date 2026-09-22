-- lua/gen1/writes.lua — every byte the Gen 1 client writes into the game, in one place.
--
-- Two rules, enforced here rather than trusted to callers:
--   1. Nothing is written unless the caller has ARMED a write window: either the overworld
--      write-safe checkpoint (lua/gen1_write_safety.lua) or a battle hook site. `W.arm(reason)`
--      opens the window until explicit disarm; `write_bytes` refuses outside it (W-7).
--   2. Every multi-byte write is validated completely before the first byte lands (W-4).
--
-- Facts (pret pokered 405b624 / pokeyellow 0a08515; all addresses come from profile.ram):
--   party_struct (macros/ram.asm:7-37): HP @+1 (BE u16), Status @+4, Moves @+8..11, PP @+29..32
--   battle_struct (macros/ram.asm:39-59): HP @+1, Status @+4, Moves @+8..11, PP @+25..28
--   The engine judges "fainted" at MainInBattleLoop from wBattleMonHP == 0; a zero written
--   only to the party struct is copied over from the battle struct each turn (RC
--   BATTLE_FORCE_FAINT_WINDOW.md), so an active battler needs BOTH plus
--   wPlayerSelectedMove = $FF (CANNOT_MOVE) so the corpse does not act first.
--   EXPLOSION = $99 (constants/move_constants.asm:161).
--   TRANSFORMED = bit 3 of wPlayerBattleStatus3 (constants/battle_constants.asm:106).
local W = { EXPLOSION = 0x99, CANNOT_MOVE = 0xFF }
-- CGB WRAM banking (Pan Docs SVBK $FF70): banks 0 and 1 both map bank 1 at $D000-$DFFF; any
-- other value maps a bank the profile's $Dxxx symbols do not describe. pureRGB runs its
-- palette fade with bank 2 selected and interrupts enabled (PLAN §4 row 13, A8/A15), so a
-- $Dxxx write landing there would hit the fade buffer. Gated by profile.derived.wram_bank_gate.
W.WRAM_BANKED_LO, W.WRAM_BANKED_HI = 0xD000, 0xDFFF
W.WRAM_BANKS_OK = { [0] = true, [1] = true }

local function be16(v) return math.floor(v / 256) % 256, v % 256 end

local function is_byte(b) return type(b) == "number" and b % 1 == 0 and b >= 0 and b <= 255 end

-- Every element of `list` is a byte, by INDEX rather than by `#list`: a payload decoded from
-- hex can carry a nil hole, and `#` on a table with a hole may stop short of it.
local function check_bytes(list, n, what)
    for i = 1, n do assert(is_byte(list[i]), what .. ": byte " .. i .. " out of range") end
end

-- Guard for W-2 (pure; caller passes the reads). Returns ok, reason.
--   battle: {in_battle, type, link_state, player_mon_number, battle_species, transformed}
--   party_mon: the decoded party entry the server named (species = internal index)
function W.active_faint_guard(battle, slot, party_mon)
    if battle.in_battle ~= 1 and battle.in_battle ~= 2 then return false, "not in a battle" end
    if battle.type ~= 0 then return false, "special battle type (old man / safari)" end
    if battle.link_state == 4 then return false, "link battle" end
    if battle.player_mon_number ~= slot then return false, "target is not the active battler" end
    -- Transform rewrites wBattleMonSpecies to the foe's species; the party slot is still ours.
    if not battle.transformed and battle.battle_species ~= party_mon.species then
        return false, "battle struct species differs from the party slot"
    end
    return true
end

-- Helper for callers building a 16-bit big-endian pair.
function W.u16be(v) return { be16(v) } end

function W.new(profile, io, Permit)
    local ram, d = assert(profile.ram), assert(profile.derived)
    assert(Permit and type(Permit.new) == "function", "shared write permit factory required")
    local species_count = assert(d.species_count, "profile.derived.species_count required")
    -- Gen 1's flat CartRAM bound comes from the profile's highest native box bank.
    -- GB SRAM banks are $2000 bytes; both pinned Gen 1 profiles use banks 0..3.
    local highest_bank = -1
    for _, bank in ipairs(assert(d.sram_box_banks, "profile SRAM box banks required")) do
        assert(type(bank) == "number" and bank % 1 == 0 and bank >= 0, "invalid SRAM bank")
        highest_bank = math.max(highest_bank, bank)
    end
    assert(highest_bank >= 0, "profile SRAM box banks empty")
    local cart_size = (highest_bank + 1) * 0x2000
    local self = Permit.new({
        write_u8 = function(addr, value, domain) return io.write_u8(addr, value, domain) end,
        domains = {
            ["System Bus"] = {
                bounds = function(addr, n) return addr >= 0 and addr + n <= 0x10000 end,
                mapped = function(addr, n)
                    if d.wram_bank_gate and addr + n - 1 >= W.WRAM_BANKED_LO and addr <= W.WRAM_BANKED_HI then
                        -- The native CGB policy remains Gen 1-owned. Never switch rWBK.
                        local bank = io.register and io.register("WRAM BANK")
                        assert(W.WRAM_BANKS_OK[bank], string.format(
                            "write refused: WRAM BANK %s outside {0,1} for $%04X (W-10)", tostring(bank), addr))
                    end
                    return true
                end,
                -- These builders pass concrete numeric addresses, not pointers which
                -- the shared mechanism may resolve again after validation.
                pointer_stable = function() return true end,
            },
            CartRAM = {
                bounds = function(addr, n, reason)
                    assert(reason ~= "panel", "cart write refused: the panel window writes WRAM only")
                    return addr >= 0 and addr + n <= cart_size
                end,
                mapped = function() return true end, -- flat CartRAM bypasses bus SRAM banking
                pointer_stable = function() return true end, -- concrete flat byte offsets
            },
        },
        -- Legacy Gen 1 arm persists until disarm. Framecount is receipt metadata,
        -- never expiry authority; the caller's checkpoint/hook supplies the scope.
        lifetime = { capture = function() return {} end, valid = function() return true end },
        provenance = function(domain, addr, n, reason)
            return { addr = addr, n = n, why = reason, domain = domain,
                     cart = domain == "CartRAM" and true or nil,
                     frame = io.framecount and io.framecount() or nil }
        end,
    })
    local permit_arm, permit_write = self.arm, self.write_bytes

    -- Open the write window until explicit disarm. `reason` names its checkpoint
    -- ("overworld", "battle_loop_head"); it is recorded with every write for the receipts.
    -- `allow(addr, n)` optionally NARROWS the window to a byte range (the panel paints into
    -- wTileMap and must not reach the menu state one byte past it). The predicate answers for
    -- the FULL interval, so a straddling write is refused whole rather than clipped.
    function self:arm(reason, allow)
        return self:guard(function()
            assert(allow == nil or type(allow) == "function", "allow must be a predicate")
            local narrowed = allow and function(domain, addr, n)
                return domain == "System Bus" and allow(addr, n)
            end or nil
            return permit_arm(self, reason, narrowed)
        end)
    end

    function self:write_bytes(addr, bytes)
        return permit_write(self, "System Bus", addr, bytes)
    end
    function self:write_cart_bytes(addr, bytes)
        return self:guard(function()
            assert(self.armed, "cart write refused: no armed write window (W-7)")
            return permit_write(self, "CartRAM", addr, bytes)
        end)
    end

    local function party_slot_base(slot) return ram.wPartyMons + slot * d.party_struct_size end
    local function check_slot(slot)
        assert(type(slot) == "number" and slot % 1 == 0 and slot >= 0 and slot < d.party_capacity,
               "party slot out of range")
    end

    -- W-1: benched (or out-of-battle) mon: HP 0, status clear. `slot` is 0-based.
    function self:faint_party_slot(slot)
        check_slot(slot)
        local base = party_slot_base(slot)
        self:write_bytes(base + (ram.wPartyMon1HP - ram.wPartyMon1), { 0, 0 })
        self:write_bytes(base + (ram.wPartyMon1Status - ram.wPartyMon1), { 0 })
    end

    -- W-2: the active battler, from the MainInBattleLoop hook only. Zero the battle struct HP,
    -- mirror it into the party slot, and make the corpse unable to move this turn.
    function self:faint_active_battler(slot)
        assert(self.armed == "battle_loop_head", "active-battler faint only at the battle loop head")
        check_slot(slot)
        self:write_bytes(ram.wBattleMonHP, { 0, 0 })
        self:write_bytes(ram.wPlayerSelectedMove, { W.CANNOT_MOVE })
        self:faint_party_slot(slot)
    end

    -- W-8 (pureRGB APEX CHIP, PLAN A1 / Live 4): put the two original DV bytes back after
    -- ItemUseMedicine.useApexChip stored $FFFF and before `call .recalculateStats` runs, so a
    -- use whose FFFF:OTID:SS key would collide with a live key changes nothing (the chip is
    -- still consumed, decision U6). `addr` is HL from the preflight hook (the slot's first DV
    -- byte); it must lie inside the party structs. Armed only inside the apex_commit hook.
    function self:restore_apex_dvs(addr, dvs)
        assert(self.armed == "apex_commit", "APEX DV restore only inside the apex_commit hook")
        assert(Permit.sequence_length(dvs, "two DV bytes") == 2, "two DV bytes required")
        assert(addr >= ram.wPartyMons and addr + 1 < ram.wPartyMons + d.party_capacity * d.party_struct_size,
               "APEX DV address outside the party structs")
        self:write_bytes(addr, { dvs[1], dvs[2] })
    end

    -- W-9 (pureRGB transformations, PLAN A2): ChangePartyPokemonSpecies stores HP := new max
    -- HP; a mon whose pre-transform HP was 0 (dead or fainted) is zeroed again right after
    -- that store, from inside the transform_hp_lo hook. `addr` is the HP word's address.
    -- †UNVERIFIED (T2 gate): the hook fires BEFORE `ld [hld],a` lands the low byte; the
    -- client backs this write with a checkpoint re-zero through the deferred force_faint path.
    function self:restore_transform_hp_zero(addr)
        assert(self.armed == "transform", "transform HP zero only inside the transform hook")
        assert(addr >= ram.wPartyMons and addr + 1 < ram.wPartyMons + d.party_capacity * d.party_struct_size,
               "transform HP address outside the party structs")
        self:write_bytes(addr, { 0, 0 })
    end

    -- W-3: Explode Mode — all four move slots become EXPLOSION with PP 1 (battle struct AND
    -- party mirror), so the engine offers nothing else. Slot-0-only was escapable (RC).
    function self:explode_active_battler(slot)
        assert(self.armed == "battle_loop_head", "explode only at the battle loop head")
        check_slot(slot)
        -- pureRGB (profile derived.explode_low_hp_fraction): EXPLOSION faints its user only below
        -- max/N HP, so the active battler is put there first (the engine writes the party mirror
        -- back at the faint). ponytail: a max HP under 2N cannot go low enough; no real battler has one.
        local frac = d.explode_low_hp_fraction
        if frac then
            local u16 = function(a) return io.read_u8(a, "System Bus") * 256 + io.read_u8(a + 1, "System Bus") end
            local low = math.max(1, math.floor(u16(ram.wBattleMonMaxHP) / frac) - 1)
            if u16(ram.wBattleMonHP) > low then self:write_bytes(ram.wBattleMonHP, { math.floor(low / 256), low % 256 }) end
            -- ...and it must move first, or the foe's hit lands on a mon at max/3 HP before the
            -- explosion does (seen live: "the wild foe knocked the linked mon out before
            -- EXPLOSION"). Turn order is a plain speed compare (core.asm .compareSpeed; only
            -- priority moves come before it), so the battle-struct speed becomes 999 -- the
            -- struct is discarded at the faint, the party mirror keeps the real stat.
            self:write_bytes(ram.wBattleMonSpeed, { 3, 0xE7 })
        end
        self:write_bytes(ram.wBattleMonMoves, { W.EXPLOSION, W.EXPLOSION, W.EXPLOSION, W.EXPLOSION })
        self:write_bytes(ram.wBattleMonPP, { 1, 1, 1, 1 })
        local base = party_slot_base(slot)
        self:write_bytes(base + (ram.wPartyMon1Moves - ram.wPartyMon1), { W.EXPLOSION, W.EXPLOSION, W.EXPLOSION, W.EXPLOSION })
        self:write_bytes(base + (ram.wPartyMon1PP - ram.wPartyMon1), { 1, 1, 1, 1 })
    end

    -- W-4: replace the enemy (rival) party. `mons` = list of {blob = 44 bytes, ot = 11, nick = 11,
    -- species = internal index}. Everything is validated before any write; the write itself is
    -- count, species list (+ $FF), structs, OT names, nicknames — the same shape the engine
    -- fills in engine/battle/read_trainer_party.asm.
    function self:write_enemy_party(mons)
        local count = Permit.sequence_length(mons, "enemy party")
        assert(count >= 1 and count <= d.party_capacity, "enemy party count must be 1..6")
        for i, m in ipairs(mons) do
            assert(Permit.sequence_length(m.blob, "enemy mon " .. i .. ": blob") == d.battle_struct_size,
                   "enemy mon " .. i .. ": blob must be " .. d.battle_struct_size .. " bytes")
            assert(Permit.sequence_length(m.ot, "enemy mon " .. i .. ": OT name") == d.name_length
                   and Permit.sequence_length(m.nick, "enemy mon " .. i .. ": nickname") == d.name_length,
                   "enemy mon " .. i .. ": names must be " .. d.name_length .. " bytes")
            assert(m.species >= 1 and m.species <= species_count and m.species == m.blob[1], "enemy mon " .. i .. ": species/blob mismatch")
            -- W-4: write_bytes checks bytes per CALL, so without this the first two mons would
            -- already be in wEnemyMons when the third one's bad byte is found. `tonumber("-1", 16)`
            -- is a number that passes every length and species check, so this is reachable.
            check_bytes(m.blob, d.battle_struct_size, "enemy mon " .. i .. ": blob")
            check_bytes(m.ot, d.name_length, "enemy mon " .. i .. ": OT name")
            check_bytes(m.nick, d.name_length, "enemy mon " .. i .. ": nickname")
        end
        local species = {}
        for i, m in ipairs(mons) do species[i] = m.species end
        species[#mons + 1] = 0xFF
        self:write_bytes(ram.wEnemyPartyCount, { #mons })
        self:write_bytes(ram.wEnemyPartySpecies, species)
        for i, m in ipairs(mons) do
            local k = i - 1
            self:write_bytes(ram.wEnemyMons + k * d.battle_struct_size, m.blob)
            self:write_bytes(ram.wEnemyMonOT + k * d.name_length, m.ot)
            self:write_bytes(ram.wEnemyMonNicks + k * d.name_length, m.nick)
        end
    end

    -- A game-specific preflight error must close the same permit as an IO error.
    for _, name in ipairs({ "faint_party_slot", "faint_active_battler", "restore_apex_dvs",
                             "restore_transform_hp_zero", "explode_active_battler", "write_enemy_party" }) do
        local method = self[name]
        self[name] = function(obj, ...) return obj:guard(method, obj, ...) end
    end
    self.active_faint_guard = W.active_faint_guard
    return self
end

function W.bizhawk_io()
    return {
        read_u8 = function(addr, domain) return memory.read_u8(addr, domain) end,
        write_u8 = function(addr, v, domain) return memory.write_u8(addr, v, domain) end,
        register = function(name) return emu.getregister(name) end,
    }
end

return W
