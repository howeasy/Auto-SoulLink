-- lua/gen1/signals.lua — Gen 1 game events detected from the engine's own execution.
--
-- Every event the client reports (faint, capture, save, map load, ...) is a bus-exec hook
-- at a pret routine, not a WRAM-diff heuristic. Sites come from
-- data/games/gen1_rby/engine_signals.json (+ extensions): bank, address, capture_offset,
-- expected bytes, flat ROM offset. At load the expected bytes are checked in the ROM domain;
-- a mismatch refuses to start, because hooking the wrong bytes reports the wrong game.
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

local function hex_of(bytes)
    local out = {}
    for i = 1, #bytes do out[i] = string.format("%02X", bytes[i]) end
    return table.concat(out)
end

-- kind -> { filter = function(io, ram) -> bool, point = function(io, ram, reads) -> table }
-- `filter` drops hits that are not the event (e.g. AddItemToInventory_.done fires for every
-- item; only a Poke Ball class item with the carry flag set is `bag_received`).
-- `point` snapshots the WRAM the server needs at the instant the engine is there.
S.KINDS = {}

S.KINDS.bag_received = {
    -- AddItemToInventory_.done: HL == wNumBagItems and carry set means "added to the bag"
    -- (home/inventory.asm); items 1..4 are the four ball classes (constants/item_constants.asm).
    filter = function(io, ram)
        local hl = io.register("H") * 256 + io.register("L")
        local carry = math.floor(io.register("F") / 16) % 2 == 1
        local item = io.read_u8(ram.wCurItem, "System Bus")
        return hl == ram.wNumBagItems and carry and item >= 1 and item <= 4
    end,
    point = function(io, ram)
        return { item = io.read_u8(ram.wCurItem, "System Bus"),
                 quantity = io.read_u8(ram.wItemQuantity, "System Bus"),
                 bag = io.read_range(ram.wNumBagItems, 42, "System Bus") }
    end,
}

local function battle_point(io, ram)
    return { party = io.read_range(ram.wPartyCount, 404, "System Bus"),
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
S.KINDS.poison_faint = { point = battle_point }
S.KINDS.starter_begin = { point = battle_point }
S.KINDS.starter_end = { point = battle_point }
S.KINDS.save_witness = {
    point = function(io, ram)
        return { save_file_status = io.read_u8(ram.wSaveFileStatus, "System Bus") }
    end,
}
S.KINDS.blackout = { point = battle_point }

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
        return p
    end,
}

-- Acquisition and storage. The mon is not in place yet when these fire (they are entries), so
-- the client treats each as "a legitimate party/box change follows" and diffs once after.
local function acquisition_point(io, ram)
    return { in_battle = io.read_u8(ram.wIsInBattle, "System Bus"),
             species = io.read_u8(ram.wCurPartySpecies, "System Bus"),
             level = io.read_u8(ram.wCurEnemyLevel, "System Bus"),
             map = io.read_u8(ram.wCurMap, "System Bus"),
             party_count = io.read_u8(ram.wPartyCount, "System Bus") }
end
S.KINDS.add_party_mon = { point = acquisition_point }
S.KINDS.capture_box = { point = acquisition_point }
S.KINDS.move_mon = {
    -- wMoveMonType: 0 BOX_TO_PARTY, 1 PARTY_TO_BOX, 2 DAYCARE_TO_PARTY, 3 PARTY_TO_DAYCARE
    -- (constants/menu_constants.asm:60-63); wWhichPokemon is the source slot.
    point = function(io, ram)
        return { move_type = io.read_u8(ram.wMoveMonType, "System Bus"),
                 which = io.read_u8(ram.wWhichPokemon, "System Bus"),
                 party_count = io.read_u8(ram.wPartyCount, "System Bus"),
                 box_count = io.read_u8(ram.wBoxCount, "System Bus") }
    end,
}
S.KINDS.remove_pokemon = {
    -- wRemoveMonFromBox non-zero = the current box, else the party (ram/wram.asm:1120-1122).
    point = function(io, ram)
        return { from_box = io.read_u8(ram.wRemoveMonFromBox, "System Bus") ~= 0,
                 which = io.read_u8(ram.wWhichPokemon, "System Bus"),
                 party_count = io.read_u8(ram.wPartyCount, "System Bus"),
                 box_count = io.read_u8(ram.wBoxCount, "System Bus") }
    end,
}
S.KINDS.evolve = {
    point = function(io, ram)
        return { which = io.read_u8(ram.wWhichPokemon, "System Bus"),
                 party = io.read_range(ram.wPartyCount, 404, "System Bus") }
    end,
}
S.KINDS.npc_trade = {
    point = function(io, ram)
        return { which = io.read_u8(ram.wWhichPokemon, "System Bus"),
                 give = io.read_u8(ram.wInGameTradeGiveMonSpecies, "System Bus"),
                 receive = io.read_u8(ram.wInGameTradeReceiveMonSpecies, "System Bus"),
                 party = io.read_range(ram.wPartyCount, 404, "System Bus") }
    end,
}

-- profile: the title's table from profile.json (ram/rom/derived); sites: the title's
-- `sites` table from engine_signals.json (kind -> site).
function S.new(profile, sites, io)
    local ram = assert(profile.ram, "profile.ram required")
    local self = { pending = {}, hooks = {}, failure = nil, closed = false }

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
        local spec = S.KINDS[kind] or {}
        if spec.filter and not spec.filter(io, ram) then return end
        local pc = site.address + (site.capture_offset or 0)
        local ok, why = pcall(function()
            assert(io.register("PC") == pc, kind .. ": callback PC differs")
            local n = #site.expected_hex / 2
            assert(hex_of(io.read_range(site.address, n, "System Bus")) == site.expected_hex,
                   kind .. ": bank/bytes differ at fire time")
            assert(#self.pending < S.MAX_PENDING, "engine signal buffer full; client stopped draining")
            local frame = io.framecount()
            self.pending[#self.pending + 1] = {
                kind = kind, frame = frame, pc = pc, bank = site.bank, sp = io.register("SP"),
                point = spec.point and spec.point(io, ram) or nil,
            }
        end)
        if not ok then self.failure = tostring(why) end
    end

    for kind, site in pairs(sites) do
        local pc = site.address + (site.capture_offset or 0)
        local id = io.on_bus_exec(function() fire(kind, site) end, pc, "SLink-gen1-" .. kind, "System Bus")
        assert(id, "engine signal registration failed: " .. kind)
        self.hooks[#self.hooks + 1] = id
    end

    -- Hand the queued signals to the caller in arrival order and start a fresh queue.
    function self:drain()
        local out = self.pending
        self.pending = {}
        return out
    end

    function self:status()
        return { failed = self.failure, pending = #self.pending, closed = self.closed }
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
