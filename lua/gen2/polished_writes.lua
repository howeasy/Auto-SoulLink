-- Polished Crystal v3.2.3 Explode Mode (W-3) and Rival Team Swap (W-4) writers. Pure: no emulator
-- globals, no activation, NOT wired into lua/gen2/client.lua yet. Same permit/gate/refusal conventions as
-- lua/gen2/writes.lua (shared lua/write_permit.lua; arm -> one guarded call -> disarm).
-- Spec: docs/polished/EXPLODE_RIVAL.md §6-§10 (they supersede §1-§5); struct offsets docs/polished/RAM.md.
--
-- W-3, at battle_hold (write_checkpoint.json titles.polished_crystal.battle_hold.execution_before, the
-- `call DetermineMoveOrder` at 0f:416A, core.asm:190). Priority resolves GetBattleVar(BATTLE_VARS_MOVE) ->
-- wCurPlayerMove (§6.1), so the vanilla rule transfers. Write order:
--   wBattleMonMoves[wCurMoveNum] = EXPLOSION; wBattleMonPP[wCurMoveNum] = (old & $C0) | 1;
--   party mirror of wPartyMon<wCurBattleMon> (Moves +2.., PP +22..), same values, so
--   UpdateBattleMonInParty (00:34b0) does not undo it; wCurPlayerMove = EXPLOSION LAST (§9.1).
-- The PP byte is read-modify-write: bits 6-7 are the PP Up count (polished_codec.encode_party_mon).
--
-- W-4, at the PC gate rival_swap_gate (0f:47dd, SendInUserPkmn's enemy branch, §10.4-§10.5): the copy of
-- wOTPartyMons[wCurPartyMon] into the battle struct has not run yet and wCurOTMon/wCurPartyMon are
-- already committed (0f:47cc). Writes wOTPartyCount, then count x 48 B party_struct records at
-- wOTPartyMons, count x 11 B OT fields (8 name + 3 Extra) at wOTPartyMonOTs, count x 11 B nicknames at
-- wOTPartyMonNicknames. NEVER wMirrorHerbPendingBoosts (01:d284..wOTPartyMons): every declared range is
-- asserted disjoint from it here and again on every write. Polished has no enemy species list: the
-- 9-bit species is the record's own Species byte (+0) plus the EXTSPECIES bit of its Form byte (+21),
-- exactly as polished_codec writes it. Which trainer classes count as rivals is an owner question
-- (§3.4) and is the caller's, not this module's. Firing only once per battle is the caller's too.
--
-- coords: {[label] = {bank, address}} for W.COORDS, straight from the overlay .sym
-- (data/polished/polished_slink.sym; the clean polishedcrystal.sym agrees for these labels).
-- tools/gen_polished_profile.py should emit them as titles.polished.write_coords = {label: [bank, addr]}
-- for exactly W.COORDS; until then {profile.ram_bank[l], profile.ram[l]} covers all but wCurPlayerMove,
-- wCurMoveNum, wBattlePlayerAction, wCurOTMon and wCurPartyMon, which the profile does not carry.
-- profile: the generated title (constants, structs.party, structs.battle, provenance) as polished.lua reads.
-- hold: write_checkpoint.json titles.polished_crystal.battle_hold (execution_before + rival_swap_gate).
local W = {}
W.EXPLOSION = 0x99
W.COORDS = {"wBattleMonMoves", "wBattleMonPP", "wCurPlayerMove", "wCurMoveNum", "wCurBattleMon",
            "wBattlePlayerAction", "wPartyCount", "wPartyMons", "wOTPartyCount", "wMirrorHerbPendingBoosts",
            "wOTPartyMons", "wOTPartyMonOTs", "wOTPartyMonNicknames", "wOTPartyDataEnd", "wCurOTMon",
            "wCurPartyMon"}

local function integer(value, low, high)
    return type(value) == "number" and value % 1 == 0 and value >= low and value <= high
end

function W.new(profile, coords, io, Permit, policy, hold)
    assert(type(profile) == "table" and profile.title == "polished", "generated Polished profile required")
    assert(Permit and type(Permit.new) == "function" and type(Permit.sequence_length) == "function",
           "shared write permit factory required")
    assert(type(io) == "table" and type(io.write_u8) == "function" and type(io.read_u8) == "function"
           and type(io.bank_valid) == "function", "explicit write_u8, read_u8 and bank_valid required")
    assert(type(policy) == "table", "explicit ownership policy required")
    for _, name in ipairs({"authorize", "pointer_stable", "provenance"}) do
        assert(type(policy[name]) == "function", "explicit policy." .. name .. " required")
    end
    assert(type(policy.lifetime) == "table" and type(policy.lifetime.capture) == "function"
           and type(policy.lifetime.valid) == "function", "explicit lifetime capture/valid required")
    assert(type(profile.artifact) == "string" and type(profile.rom_sha1) == "string" and #profile.rom_sha1 == 40,
           "profile artifact provenance required")
    local c, s, b = assert(profile.constants), assert(profile.structs).party, profile.structs.battle
    assert(c.PARTY_LENGTH == 6 and c.NUM_MOVES == 4 and c.NAME_LENGTH == 11 and c.MON_NAME_LENGTH == 11
           and integer(c.TRAINER_BATTLE, 1, 255) and integer(c.EXTSPECIES_MASK, 1, 255)
           and integer(c.IS_EGG_MASK, 1, 255), "unsupported or missing Polished constants")
    assert(type(s) == "table" and s.End == 48 and s.Species == 0 and s.Moves == 2 and s.Form == 21
           and s.PP == 22 and s.HP == 34, "party_struct geometry disagrees (RAM.md §2.1)")
    assert(type(b) == "table" and b.Moves == 2 and b.PP == 11, "battle_struct geometry disagrees (RAM.md §2.3)")
    assert(type(hold) == "table" and type(hold.execution_before) == "table" and type(hold.rival_swap_gate) == "table",
           "battle_hold record with execution_before and rival_swap_gate required")
    for _, site in ipairs({hold.execution_before, hold.rival_swap_gate}) do
        assert(integer(site.bank, 1, 0x7F) and integer(site.pc, 0x4000, 0x7FFF), "gate PC coordinates required")
    end

    local at, bank_of = {}, {}
    assert(type(coords) == "table", "coords table required")
    for _, label in ipairs(W.COORDS) do
        local row = coords[label]
        assert(type(row) == "table" and integer(row[1], 0, 7) and integer(row[2], 0xC000, 0xDFFF),
               "coords missing: " .. label)
        at[label], bank_of[label] = row[2], row[1]
    end
    local P, N, NM = c.PARTY_LENGTH, c.NUM_MOVES, s.End
    -- wMirrorHerbPendingBoosts (wramx.asm:760-762) is the whole gap between the count and the records
    local herb, herb_end = at.wMirrorHerbPendingBoosts, at.wOTPartyMons
    assert(herb == at.wOTPartyCount + 1 and herb_end > herb, "Mirror Herb geometry disagrees (RAM.md §2.4)")
    assert(at.wOTPartyMonOTs == at.wOTPartyMons + P * NM and at.wOTPartyMonNicknames == at.wOTPartyMonOTs + P * c.NAME_LENGTH
           and at.wOTPartyDataEnd == at.wOTPartyMonNicknames + P * c.MON_NAME_LENGTH, "enemy party block geometry disagrees")
    assert(at.wBattleMonPP - at.wBattleMonMoves == b.PP - b.Moves and bank_of.wBattleMonPP == bank_of.wBattleMonMoves,
           "battle move/PP coords disagree with battle_struct")
    for _, label in ipairs({"wOTPartyCount", "wOTPartyMons", "wOTPartyMonOTs", "wOTPartyMonNicknames"}) do
        assert(bank_of[label] == 1 and at[label] >= 0xD000, "enemy party is not in WRAMX bank 1: " .. label)
    end

    -- The declared write list per gate: {address, length, bank}. Nothing else is ever writable.
    local ranges = {
        battle_hold = {{at.wBattleMonMoves, N, bank_of.wBattleMonMoves}, {at.wBattleMonPP, N, bank_of.wBattleMonPP},
                       {at.wCurPlayerMove, 1, bank_of.wCurPlayerMove}},
        rival_swap = {{at.wOTPartyCount, 1, 1}, {at.wOTPartyMons, P * NM, 1},
                      {at.wOTPartyMonOTs, P * c.NAME_LENGTH, 1}, {at.wOTPartyMonNicknames, P * c.MON_NAME_LENGTH, 1}},
    }
    for slot = 0, P - 1 do
        local base = at.wPartyMons + slot * NM
        table.insert(ranges.battle_hold, {base + s.Moves, N, bank_of.wPartyMons})
        table.insert(ranges.battle_hold, {base + s.PP, N, bank_of.wPartyMons})
    end
    local function touches_herb(addr, n) return addr < herb_end and addr + n > herb end
    for reason, list in pairs(ranges) do
        for _, r in ipairs(list) do
            assert(not touches_herb(r[1], r[2]), "declared " .. reason .. " range intersects wMirrorHerbPendingBoosts")
        end
    end
    local function declared(reason, addr, n)
        for _, r in ipairs(ranges[reason] or {}) do
            if addr >= r[1] and addr + n <= r[1] + r[2] then return r end
        end
    end

    local gate = Permit.new({
        write_u8 = io.write_u8,
        domains = {
            ["System Bus"] = {
                bounds = function(addr, n, reason)
                    return not touches_herb(addr, n) and declared(reason, addr, n) ~= nil
                end,
                mapped = function(addr, n, reason)
                    local r = declared(reason, addr, n)
                    return r ~= nil and io.bank_valid(r[3], addr, n) == true
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
    local self = setmetatable({}, {__index=function(_, key)
        if key == "armed" or key == "log" then return gate[key] end
    end})
    function self:arm(reason, allow) return gate:arm(reason, allow) end
    function self:disarm() return gate:disarm() end

    local function read(label, offset)
        local addr = at[label] + (offset or 0)
        assert(io.bank_valid(bank_of[label], addr, 1) == true, "read refused: " .. label .. " bank not mapped")
        return io.read_u8(addr, "System Bus")
    end
    local function common(reason, snapshot, site)
        assert(gate.armed == reason, "write refused: " .. reason .. " gate not armed")
        assert(type(snapshot) == "table" and snapshot.link_mode == 0, "linked or unknown battle context refused")
        assert(snapshot.bank == site.bank and snapshot.pc == site.pc, "snapshot not taken at the " .. reason .. " PC")
    end
    local function authorized(operation, request)
        assert(policy.authorize(operation, request, gate.armed) == true, "write ownership refused")
    end

    -- snapshot = {link_mode, bank, pc, player_action, active_slot, move_num}, read at the battle hold.
    -- Stale = any of wCurBattleMon / wCurMoveNum / wBattlePlayerAction no longer reads what it says.
    function self:explode_active_battler(slot, snapshot)
        return gate:guard(function()
            common("battle_hold", snapshot, hold.execution_before)
            assert(snapshot.player_action == 0, "explode needs a committed move (USEMOVE)")
            assert(integer(slot, 0, P - 1) and slot < read("wPartyCount"), "battler slot invalid")
            assert(snapshot.active_slot == slot, "target is not the active battler")
            assert(integer(snapshot.move_num, 0, N - 1), "move slot invalid")
            assert(read("wCurBattleMon") == slot and read("wCurMoveNum") == snapshot.move_num
                   and read("wBattlePlayerAction") == snapshot.player_action, "stale snapshot")
            authorized("battle_explode", {slot=slot, snapshot=snapshot})
            local m, x = snapshot.move_num, W.EXPLOSION
            local party = slot * NM
            local function pp(label, offset) return (read(label, offset) & 0xC0) | 1 end -- keep the PP Ups
            return gate:write_batch({
                {domain="System Bus", addr=at.wBattleMonMoves + m, bytes={x}},
                {domain="System Bus", addr=at.wBattleMonPP + m, bytes={pp("wBattleMonPP", m)}},
                {domain="System Bus", addr=at.wPartyMons + party + s.Moves + m, bytes={x}},
                {domain="System Bus", addr=at.wPartyMons + party + s.PP + m, bytes={pp("wPartyMons", party + s.PP + m)}},
                {domain="System Bus", addr=at.wCurPlayerMove, bytes={x}},
            })
        end)
    end

    -- mons = list of {record = 48 bytes (polished_codec.encode_party_mon), ot = 11, nick = 11}.
    -- snapshot = {link_mode, mode, bank, pc, cur_ot_mon}, read at the rival_swap_gate PC. The engine copies
    -- wOTPartyMons[wCurPartyMon] next, so that index must exist in the new party and have HP.
    function self:write_enemy_party(mons, snapshot)
        return gate:guard(function()
            common("rival_swap", snapshot, hold.rival_swap_gate)
            assert(snapshot.mode == c.TRAINER_BATTLE, "not a trainer battle")
            local count = Permit.sequence_length(mons, "enemy party")
            assert(count >= 1 and count <= P, "enemy party count must be 1.." .. P)
            local cur = snapshot.cur_ot_mon
            assert(integer(cur, 0, count - 1), "the enemy mon being sent out is outside the new party")
            assert(read("wCurOTMon") == cur and read("wCurPartyMon") == cur, "stale snapshot")
            local records, names, nicks = {}, {}, {}
            for i, mon in ipairs(mons) do
                local what = "enemy mon " .. i
                assert(type(mon) == "table", what .. ": table required")
                for field, n in pairs({record = NM, ot = c.NAME_LENGTH, nick = c.MON_NAME_LENGTH}) do
                    assert(Permit.sequence_length(mon[field], what .. " " .. field) == n,
                           what .. ": " .. field .. " must be " .. n .. " bytes")
                    for j = 1, n do assert(integer(mon[field][j], 0, 255), what .. ": " .. field .. " byte out of range") end
                end
                local r = mon.record
                local form = r[s.Form + 1]
                local species = r[s.Species + 1] + ((form & c.EXTSPECIES_MASK) ~= 0 and 0x100 or 0)
                assert(species >= 1, what .. ": no species")
                assert((form & c.IS_EGG_MASK) == 0, what .. ": an egg cannot battle")
                assert(i ~= cur + 1 or r[s.HP + 1] * 256 + r[s.HP + 2] > 0, what .. " is sent out next and has no HP")
                for j = 1, NM do records[#records + 1] = r[j] end
                for j = 1, c.NAME_LENGTH do names[#names + 1] = mon.ot[j] end
                for j = 1, c.MON_NAME_LENGTH do nicks[#nicks + 1] = mon.nick[j] end
            end
            authorized("enemy_party", {count=count, snapshot=snapshot})
            return gate:write_batch({
                {domain="System Bus", addr=at.wOTPartyCount, bytes={count}},
                {domain="System Bus", addr=at.wOTPartyMons, bytes=records},
                {domain="System Bus", addr=at.wOTPartyMonOTs, bytes=names},
                {domain="System Bus", addr=at.wOTPartyMonNicknames, bytes=nicks},
            })
        end)
    end
    return self
end

return W
