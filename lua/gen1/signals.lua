-- lua/gen1/signals.lua — Gen 1 game events detected from the engine's own execution.
--
-- Every event the client reports (faint, capture, save, map load, ...) is a bus-exec hook
-- at a pret routine, not a WRAM-diff heuristic. Sites come from the pack's
-- engine_signals.json (data/games/gen1_rby or gen1_purergb): bank, address (= anchor),
-- capture_offset (hook = address + capture_offset), expected bytes, flat ROM offset. At load
-- the expected bytes are checked in the ROM domain; a mismatch refuses to start, because
-- hooking the wrong bytes reports the wrong game. A kind with no S.KINDS entry gets the
-- generic point: every symbol the site lists under `point`, read as one byte each.
--
-- Pattern proven live on gen1/rc (gen1_engine_signals.lua): bank check via hLoadedROMBank,
-- PC == site + capture_offset, bytes re-read on the System Bus at fire time, frame stamped
-- with emu.framecount() (== the frame the step was armed for, BizHawk 2.11.1 Gambatte).
--
-- `io` is injected so lupa can drive this without BizHawk:
--   io.read_u8(addr, domain)      io.read_range(addr, len, domain) -> {b0, b1, ...}
--   io.on_bus_exec(fn, addr, name, domain) -> id      io.unregister(id)
--   io.framecount()               io.register(name) -> value ("PC", "SP", "H", "L", "F")
local S = { MAX_PENDING = 64 }
-- BizHawk's sentinel for a registration it could not honour (research card A15). A string is
-- truthy, so `assert(id)` alone would arm nothing and believe it did.
-- †UNVERIFIED exact casing/braces across BizHawk versions: compared after stripping braces,
-- case-insensitively, so any spelling of the all-zero GUID is refused.
S.NULL_GUID = "00000000-0000-0000-0000-000000000000"
local function is_null_guid(id)
    if type(id) ~= "string" then return false end
    return id:gsub("[{}]", ""):lower() == S.NULL_GUID
end

local function hex_of(bytes)
    local out = {}
    for i = 1, #bytes do out[i] = string.format("%02X", bytes[i]) end
    return table.concat(out)
end

-- kind -> { filter = function(io, ram, d) -> bool, point = function(io, ram, d) -> table }
-- `filter` drops hits that are not the event (e.g. AddItemToInventory_.done fires for every
-- item; only a Poke Ball class item with the carry flag set is `bag_received`).
-- `point` snapshots the WRAM the server needs at the instant the engine is there.
-- `d` is profile.derived: capacities, the ball set, struct sizes.
S.KINDS = {}

local function ball_set(d)
    if d.__ball_set then return d.__ball_set end
    local set = {}
    for _, id in ipairs(assert(d.ball_items, "profile.derived.ball_items required")) do
        set[id] = true
    end
    d.__ball_set = set
    return set
end
local function bag_bytes(ram, d)
    -- count byte + capacity id/qty pairs + the $FF terminator
    return 2 + 2 * assert(d.bag_capacity, "profile.derived.bag_capacity required")
end

S.KINDS.bag_received = {
    -- AddItemToInventory_.done: HL == wNumBagItems and carry set means "added to the bag"
    -- (home/inventory.asm); the ball classes are profile.derived.ball_items.
    filter = function(io, ram, d)
        local hl = io.register("H") * 256 + io.register("L")
        local carry = math.floor(io.register("F") / 16) % 2 == 1
        local item = io.read_u8(ram.wCurItem, "System Bus")
        return hl == ram.wNumBagItems and carry and ball_set(d)[item] == true
    end,
    point = function(io, ram, d)
        return { item = io.read_u8(ram.wCurItem, "System Bus"),
                 quantity = io.read_u8(ram.wItemQuantity, "System Bus"),
                 bag = io.read_range(ram.wNumBagItems, bag_bytes(ram, d), "System Bus") }
    end,
}

-- count + species list + structs + OT names + nicknames is one contiguous WRAM run whose
-- tail (the nickname block) is the same size as the OT block: ram/wram.asm:1722-1744 (party),
-- :2226-2248 (box); Yellow :1903-1925, :2491-2513; pureRGB keeps the run (404 / 1122 bytes).
local function block_len(ram, prefix)
    return (ram["w" .. prefix .. "MonNicks"] - ram["w" .. prefix .. "Count"])
         + (ram["w" .. prefix .. "MonNicks"] - ram["w" .. prefix .. "MonOT"])
end

local function battle_point(io, ram)
    return { party = io.read_range(ram.wPartyCount, block_len(ram, "Party"), "System Bus"),
             map = io.read_u8(ram.wCurMap, "System Bus"),
             in_battle = io.read_u8(ram.wIsInBattle, "System Bus"),
             active_slot = io.read_u8(ram.wPlayerMonNumber, "System Bus"),
             battle_hp = io.read_u8(ram.wBattleMonHP, "System Bus") * 256
                       + io.read_u8(ram.wBattleMonHP + 1, "System Bus"),
             battle_species = io.read_u8(ram.wBattleMonSpecies, "System Bus"),
             mon_location = io.read_u8(ram.wMonDataLocation, "System Bus"),
             cur_species = io.read_u8(ram.wCurPartySpecies, "System Bus"),
             cur_level = io.read_u8(ram.wCurEnemyLevel, "System Bus") }
end
S.KINDS.battle_faint = { point = battle_point }
-- ApplyOutOfBattlePoisonDamage.noBorrow (engine/events/poison.asm): fires once per mon that
-- fainted from the step's damage; wWhichPokemon is that party slot, HP already zeroed
S.KINDS.poison_faint = { point = function(io, ram)
    local pt = battle_point(io, ram)
    pt.which = io.read_u8(ram.wWhichPokemon, "System Bus")
    return pt
end }
S.KINDS.starter_begin = { point = battle_point }
S.KINDS.starter_end = { point = battle_point }
S.KINDS.save_witness = {
    point = function(io, ram)
        return { save_file_status = io.read_u8(ram.wSaveFileStatus, "System Bus") }
    end,
}
S.KINDS.blackout = { point = battle_point }
S.KINDS.trade_service = {}  -- companion-patch receptionist pickup; registered by the client when patched
-- MainInBattleLoop+0: the only instant the engine judges wBattleMonHP (W-2). The client's
-- on_fire handler applies pending in-battle writes synchronously inside this hook.
S.KINDS.battle_loop_head = {
    point = function(io, ram)
        return { active_slot = io.read_u8(ram.wPlayerMonNumber, "System Bus"),
                 battle_hp = io.read_u8(ram.wBattleMonHP, "System Bus") * 256
                           + io.read_u8(ram.wBattleMonHP + 1, "System Bus"),
                 battle_species = io.read_u8(ram.wBattleMonSpecies, "System Bus"),
                 in_battle = io.read_u8(ram.wIsInBattle, "System Bus"),
                 battle_type = io.read_u8(ram.wBattleType, "System Bus"),
                 link_state = io.read_u8(ram.wLinkState, "System Bus"),
                 status3 = io.read_u8(ram.wPlayerBattleStatus3, "System Bus") }
    end,
}

-- Battle lifecycle. InitBattleCommon runs for wild and trainer battles; wCurOpponent is the
-- wild species, or trainer class + 200 (constants/trainer_constants.asm). InitWildBattle+5 is
-- past `ld a,1 / ld [wIsInBattle],a` so the species/level are already staged.
local function opponent_point(io, ram)
    return { cur_opponent = io.read_u8(ram.wCurOpponent, "System Bus"),
             species = io.read_u8(ram.wEnemyMonSpecies2, "System Bus"),
             level = io.read_u8(ram.wCurEnemyLevel, "System Bus"),
             battle_type = io.read_u8(ram.wBattleType, "System Bus"),
             is_in_battle = io.read_u8(ram.wIsInBattle, "System Bus"),
             map = io.read_u8(ram.wCurMap, "System Bus"),
             link_state = io.read_u8(ram.wLinkState, "System Bus") }
end
S.KINDS.battle_begin = { point = opponent_point }
S.KINDS.wild_begin = { point = opponent_point }
S.KINDS.battle_end = {
    point = function(io, ram)
        local p = opponent_point(io, ram)
        p.result = io.read_u8(ram.wBattleResult, "System Bus")  -- 0 won, 1 lost, 2 ran (core.asm)
        -- pureRGB: bit 1 = the player RAN (PLAN M2-b RUN witness); no such byte on vanilla
        if ram.wBattleFunctionalFlags then
            p.functional_flags = io.read_u8(ram.wBattleFunctionalFlags, "System Bus")
        end
        return p
    end,
}
S.KINDS.trainer_staging = {
    point = function(io, ram)
        local p = opponent_point(io, ram)
        if ram.wTrainerClass then p.trainer_class = io.read_u8(ram.wTrainerClass, "System Bus") end
        return p
    end,
}

-- Acquisition and storage. The mon is not in place yet when these fire (they are entries), so
-- the client treats each as "a legitimate party/box change follows" and diffs once after.
local function acquisition_point(io, ram)
    -- wMonDataLocation: low nybble 0 = the player's party, else the ENEMY party being built
    -- by ReadTrainer; $80 = the NPC in-game trade's incoming mon (add_mon.asm:6-10,
    -- in_game_trades.asm:146-148). Only the first is an acquisition.
    return { in_battle = io.read_u8(ram.wIsInBattle, "System Bus"),
             mon_location = io.read_u8(ram.wMonDataLocation, "System Bus"),
             species = io.read_u8(ram.wCurPartySpecies, "System Bus"),
             level = io.read_u8(ram.wCurEnemyLevel, "System Bus"),
             map = io.read_u8(ram.wCurMap, "System Bus"),
             party_count = io.read_u8(ram.wPartyCount, "System Bus") }
end
S.KINDS.add_party_mon = { point = acquisition_point }
S.KINDS.capture_box = { point = acquisition_point }
S.KINDS.capture_party_begin = { point = acquisition_point }
S.KINDS.capture_party_end = { point = acquisition_point }
S.KINDS.capture_box_begin = { point = acquisition_point }
S.KINDS.capture_box_end = { point = acquisition_point }
-- _MoveMon copies the mon and _RemovePokemon shifts every later slot down
-- (engine/pokemon/add_mon.asm:365-413, remove_mon.asm:8-107), so by the time the client drains
-- one of these signals the live party/box no longer holds what moved. Both points therefore
-- snapshot the whole party and the whole active box, the way `battle_point` snapshots the party.
--
-- wMoveMonType and wRemoveMonFromBox are ONE byte in both foundations (vanilla $CF95 =
-- pureRGB $CF95: ram/wram.asm:1120-1122 declares them as a union; they are never live at
-- once). `move_mon` reads it as the move type, `remove_pokemon` as the party/box flag, and
-- nothing here may read both from one hook.
local function storage_point(io, ram)
    return { which = io.read_u8(ram.wWhichPokemon, "System Bus"),
             party_count = io.read_u8(ram.wPartyCount, "System Bus"),
             box_count = io.read_u8(ram.wBoxCount, "System Bus"),
             box_num = io.read_u8(ram.wCurrentBoxNum, "System Bus"),
             party = io.read_range(ram.wPartyCount, block_len(ram, "Party"), "System Bus"),
             box = io.read_range(ram.wBoxCount, block_len(ram, "Box"), "System Bus") }
end

S.KINDS.move_mon = {
    -- wMoveMonType: 0 BOX_TO_PARTY, 1 PARTY_TO_BOX, 2 DAYCARE_TO_PARTY, 3 PARTY_TO_DAYCARE
    -- (constants/menu_constants.asm:60-63); wWhichPokemon is the source slot.
    point = function(io, ram)
        local pt = storage_point(io, ram)
        pt.move_type = io.read_u8(ram.wMoveMonType, "System Bus")
        return pt
    end,
}
S.KINDS.remove_pokemon = {
    -- wRemoveMonFromBox non-zero = the current box, else the party (ram/wram.asm:1120-1122).
    point = function(io, ram)
        local pt = storage_point(io, ram)
        pt.from_box = io.read_u8(ram.wRemoveMonFromBox, "System Bus") ~= 0
        return pt
    end,
}
S.KINDS.pc_deposit = S.KINDS.remove_pokemon
S.KINDS.pc_withdraw = S.KINDS.remove_pokemon
S.KINDS.pc_release = S.KINDS.remove_pokemon
-- DaycareGentlemanText.enoughMoney: `call MoveMon` with DAYCARE_TO_PARTY staged. The daycare
-- never touches the box (PLAN §4 row 24): the mon about to be appended at wPartyCount-1 is
-- the wDayCareMon record, snapshotted here before _MoveMon copies it.
S.KINDS.daycare_withdraw = {
    point = function(io, ram, d)
        local pt = storage_point(io, ram)
        pt.move_type = io.read_u8(ram.wMoveMonType, "System Bus")
        if ram.wDayCareMon then pt.daycare = io.read_range(ram.wDayCareMon, d.party_struct_size, "System Bus") end
        return pt
    end,
}
S.KINDS.evolve = {
    point = function(io, ram)
        return { which = io.read_u8(ram.wWhichPokemon, "System Bus"),
                 party = io.read_range(ram.wPartyCount, block_len(ram, "Party"), "System Bus") }
    end,
}
local function npc_trade_point(io, ram)
    return { which = io.read_u8(ram.wWhichPokemon, "System Bus"),
             give = io.read_u8(ram.wInGameTradeGiveMonSpecies, "System Bus"),
             receive = io.read_u8(ram.wInGameTradeReceiveMonSpecies, "System Bus"),
             party_count = io.read_u8(ram.wPartyCount, "System Bus"),
             party = io.read_range(ram.wPartyCount, block_len(ram, "Party"), "System Bus") }
end
S.KINDS.npc_trade = { point = npc_trade_point }
-- pureRGB (PLAN §4 row 25): selection happens INSIDE InGameTrade_DoTrade, RemovePokemon
-- compacts the party and the received mon is appended, so identity is taken at the removal
-- call (wWhichPokemon is final there) and the readback at npc_trade_done is wPartyCount-1.
S.KINDS.npc_trade_remove = { point = npc_trade_point }
S.KINDS.npc_trade_add = { point = npc_trade_point }
S.KINDS.npc_trade_done = { point = npc_trade_point }

-- ChangePartyPokemonSpecies+0 (pureRGB transformations, PLAN A2): the slot is wWhichPokemon
-- and its HP is still the PRE-transform value here; +$4A/+$4C are the new-max-HP stores.
local function party_hp_addr(ram, d, slot)
    return ram.wPartyMons + slot * d.party_struct_size + (ram.wPartyMon1HP - ram.wPartyMon1)
end
S.KINDS.transform = {
    point = function(io, ram, d)
        local which = io.read_u8(ram.wWhichPokemon, "System Bus")
        local hp = party_hp_addr(ram, d, which)
        return { which = which,
                 cur_species = io.read_u8(ram.wCurPartySpecies, "System Bus"),
                 party_count = io.read_u8(ram.wPartyCount, "System Bus"),
                 old_hp = io.read_u8(hp, "System Bus") * 256 + io.read_u8(hp + 1, "System Bus"),
                 party = io.read_range(ram.wPartyCount, block_len(ram, "Party"), "System Bus") }
    end,
}
-- The HP stores: HL names the byte about to be written (`ld [hli],a` / `ld [hld],a`).
local function hp_store_point(io, ram)
    return { which = io.read_u8(ram.wWhichPokemon, "System Bus"),
             hl = io.register("H") * 256 + io.register("L") }
end
S.KINDS.transform_hp_hi = { point = hp_store_point }
S.KINDS.transform_hp_lo = { point = hp_store_point }

-- ItemUseMedicine.useApexChip (PLAN A1): the target slot is wUsedItemOnWhichPokemon, NOT
-- wWhichPokemon, and HL points at the slot's first DV byte at .setDVs (Live 4: hl=D18E ==
-- wPartyMon1DVs for slot 0). preflight = before the $FF stores, commit = after both.
local function apex_point(io, ram)
    local hl = io.register("H") * 256 + io.register("L")
    return { target = io.read_u8(ram.wUsedItemOnWhichPokemon, "System Bus"),
             which = io.read_u8(ram.wWhichPokemon, "System Bus"),
             party_count = io.read_u8(ram.wPartyCount, "System Bus"),
             hl = hl,
             party = io.read_range(ram.wPartyCount, block_len(ram, "Party"), "System Bus") }
end
S.KINDS.apex_preflight = { point = apex_point }
S.KINDS.apex_commit = { point = apex_point }
S.KINDS.apex_recalc_call = { point = apex_point }

-- Generic point for a site kind with no entry above: one byte per listed symbol.
local function generic_point(site)
    return function(io, ram)
        local out = {}
        for _, sym in ipairs(site.point or {}) do
            if ram[sym] then out[sym] = io.read_u8(ram[sym], "System Bus") end
        end
        return out
    end
end

-- profile: the title's table from profile.json (ram/rom/derived); sites: the title's
-- `sites` table from engine_signals.json (kind -> site); on_fire: optional kind -> function(signal)
-- run synchronously inside the hook (for writes that must land at that exact instant).
function S.new(profile, sites, io, on_fire)
    local ram = assert(profile.ram, "profile.ram required")
    local d = profile.derived or {}
    local self = { pending = {}, hooks = {}, failure = nil, closed = false, handler_error = nil,
                   registered = 0 }
    on_fire = on_fire or {}

    -- Load-time anchor: every site's bytes must be in the ROM where the JSON says.
    local bad = {}
    for kind, site in pairs(sites) do
        local n = #site.expected_hex / 2
        if hex_of(io.read_range(site.rom_offset, n, "ROM")) ~= site.expected_hex then
            bad[#bad + 1] = kind
        end
    end
    if #bad > 0 then
        table.sort(bad)
        error("engine sites differ from the ROM: " .. table.concat(bad, ", "), 0)
    end

    local function fire(kind, site)
        if self.closed or self.failure then return end
        if site.bank > 0 and io.read_u8(ram.hLoadedROMBank, "System Bus") ~= site.bank then return end
        local spec = S.KINDS[kind] or { point = generic_point(site) }
        if spec.filter and not spec.filter(io, ram, d) then return end
        local pc = site.address + (site.capture_offset or 0)
        local ok, why = pcall(function()
            assert(io.register("PC") == pc, kind .. ": callback PC differs")
            local n = #site.expected_hex / 2
            assert(hex_of(io.read_range(site.address, n, "System Bus")) == site.expected_hex,
                   kind .. ": bank/bytes differ at fire time")
            assert(#self.pending < S.MAX_PENDING, "engine signal buffer full; client stopped draining")
            local frame = io.framecount()
            local signal = {
                kind = kind, frame = frame, pc = pc, bank = site.bank, sp = io.register("SP"),
                point = spec.point and spec.point(io, ram, d) or nil,
            }
            self.pending[#self.pending + 1] = signal
            if on_fire[kind] then
                local hok, herr = pcall(on_fire[kind], signal)
                if not hok then self.handler_error = kind .. ": " .. tostring(herr) end
            end
        end)
        if not ok then self.failure = tostring(why) end
    end

    local expected = 0
    for kind, site in pairs(sites) do
        expected = expected + 1
        local pc = site.address + (site.capture_offset or 0)
        local id = io.on_bus_exec(function() fire(kind, site) end, pc, "SLink-gen1-" .. kind, "System Bus")
        assert(id and not is_null_guid(id), "engine signal registration failed: " .. kind)
        self.hooks[#self.hooks + 1] = id
        self.registered = self.registered + 1
    end
    assert(self.registered == expected, "engine signal registration incomplete: "
           .. self.registered .. " of " .. expected)

    -- Hand the queued signals to the caller in arrival order and start a fresh queue.
    function self:drain()
        local out = self.pending
        self.pending = {}
        return out
    end

    function self:status()
        return { failed = self.failure, pending = #self.pending, closed = self.closed,
                 handler_error = self.handler_error }
    end

    function self:close()
        self.closed = true
        for _, id in ipairs(self.hooks) do io.unregister(id) end
        self.hooks = {}
    end

    return self
end

-- Production io over the BizHawk globals; the client passes S.new(profile, sites, S.bizhawk_io()).
function S.bizhawk_io()
    return {
        read_u8 = function(addr, domain) return memory.read_u8(addr, domain) end,
        read_range = function(addr, len, domain)
            -- per-byte reads: no dependence on read_bytes_as_array's table indexing
            local out = {}
            for i = 1, len do out[i] = memory.read_u8(addr + i - 1, domain) end
            return out
        end,
        on_bus_exec = function(fn, addr, name, domain) return event.on_bus_exec(fn, addr, name, domain) end,
        unregister = function(id) return event.unregisterbyid(id) end,
        framecount = function() return emu.framecount() end,
        register = function(name) return emu.getregister(name) end,
    }
end

return S
