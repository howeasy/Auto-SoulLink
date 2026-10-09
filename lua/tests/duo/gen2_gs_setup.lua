-- G/S poison/species harness-only SYNTH setup. No product event or command is injected.
-- Stats follow gen2_codec.calc_stat / native CalcMonStats; species planting follows
-- gen2_trade.lua's StartBattle hook, before the native wild record is generated.
local M = {}
local function hex(bytes)
    local out = {}
    for i, v in ipairs(bytes) do out[i] = string.format("%02x", v) end
    return table.concat(out)
end

function M.new(h, ctx, SG, facts)
    assert(facts.schema == "gen2-gs-harden-v1" and facts.title == ctx.env.title
           and (facts.title == "gold" or facts.title == "silver")
           and facts.overlay_sha1 == ctx.env.exec_sha1, "G/S setup identity differs")
    local api, c, level = ctx.api, ctx.profile.constants, facts.level
    local self, conditioned = {}, {}
    local function read(name, offset, size)
        local r = assert(facts.ram[name], "G/S setup symbol missing: " .. name)
        local addr = r.addr + (offset or 0)
        local off = SG.wram_offset(r.bank, addr, size or 1)
        return api.read_range(off, size or 1, "WRAM"), off, addr, r.bank
    end
    local function write(name, offset, bytes, purpose, extra)
        local before, off, addr, bank = read(name, offset, #bytes)
        for i, v in ipairs(bytes) do api.write_u8(off + i - 1, v, "WRAM") end
        local after = api.read_range(off, #bytes, "WRAM")
        assert(hex(after) == hex(bytes), "G/S setup write readback differs")
        local row = {frame=h.frame(), purpose=purpose, symbol=name, domain="WRAM", bank=bank,
                     address=addr, offset=offset or 0, bytes_before=hex(before), bytes_after=hex(after)}
        for k, v in pairs(extra or {}) do row[k] = v end
        h.jlog("SYNTH_SETUP", row)
    end
    local function condition(slot, purpose)
        if read("wBattleMode")[1] ~= 0 then return false, "conditioning requires overworld" end
        local count = read("wPartyCount")[1]
        if slot < 0 or slot >= count then return false, "conditioning party slot missing" end
        local offset = slot * c.PARTYMON_STRUCT_LENGTH
        local raw = read("wPartyMon1", offset, c.PARTYMON_STRUCT_LENGTH)
        local species = raw[c.MON_SPECIES + 1]
        if read("wPartySpecies", slot)[1] ~= species then return false, "conditioning refuses an egg" end
        local data = facts.species[tostring(species)]
        if not data then return false, "conditioning species facts missing" end
        local identity = string.format("%02X%02X:%02X%02X:%02X", raw[c.MON_DVS + 1], raw[c.MON_DVS + 2],
                                       raw[c.MON_OT_ID + 1], raw[c.MON_OT_ID + 2], species)
        if conditioned[identity] then return true end
        local function be(at) return raw[at + 1] * 256 + raw[at + 2] end
        if be(c.MON_HP) == 0 or raw[c.MON_STATUS + 1] ~= 0 then
            return false, "conditioning refuses a dead or statused mon"
        end
        local next = {}
        for i, v in ipairs(raw) do next[i] = v end
        local function put(at, value, size)
            for i = size, 1, -1 do next[at + i] = value % 256; value = value // 256 end
        end
        local ad, ss = raw[c.MON_DVS + 1], raw[c.MON_DVS + 2]
        local dv = {attack=ad // 16, defense=ad % 16, speed=ss // 16, special=ss % 16}
        dv.hp = (dv.attack % 2) * 8 + (dv.defense % 2) * 4 + (dv.speed % 2) * 2 + dv.special % 2
        local function stat(name, dvname, expat, hp)
            local exp = be(expat)
            local root = math.min(255, 1 + math.floor(math.sqrt(math.max(0, exp - 1))))
            return math.min(999, ((2 * (data.base_stats[name] + dv[dvname]) + root // 4) * level) // 100
                                + (hp and level + 10 or 5))
        end
        local hp = stat("hp", "hp", c.MON_HP_EXP, true)
        put(c.MON_EXP, data.exp, 3)
        put(c.MON_LEVEL, level, 1)
        put(c.MON_HP, hp, 2)
        put(c.MON_MAXHP, hp, 2)
        for _, row in ipairs({{"attack", "attack", c.MON_ATK_EXP, c.MON_ATK},
                             {"defense", "defense", c.MON_DEF_EXP, c.MON_DEF},
                             {"speed", "speed", c.MON_SPD_EXP, c.MON_SPD},
                             {"special_attack", "special", c.MON_SPC_EXP, c.MON_SAT},
                             {"special_defense", "special", c.MON_SPC_EXP, c.MON_SDF}}) do
            put(row[4], stat(row[1], row[2], row[3], false), 2)
        end
        write("wPartyMon1", offset, next, purpose, {slot=slot, key=identity, level=level,
              disclosure="SYNTH: coherent level/EXP/HP/stats only; species, DVs, OT, moves, status and names preserved"})
        conditioned[identity] = true
        return true
    end
    function self.condition_starter() return condition(0, "gs_starter_resilience") end
    function self.condition_linked(key)
        local slot = h.slot_of(key)
        if slot == nil then return false, "linked condition target missing" end
        return condition(slot, "gs_linked_poison_resilience")
    end
    function self.encounter(species)
        assert(type(species) == "number" and species % 1 == 0 and facts.species[tostring(species)],
               "G/S encounter species facts missing")
        local site, handle, planted, fault = facts.site, nil, false, nil
        assert(api.read_u8(site.flat, "ROM") == tonumber(site.hex, 16), "StartBattle anchor differs")
        handle = api.on_bus_exec(function()
            if planted or api.read_u8(ctx.profile.hram.hROMBank, "System Bus") ~= site.bank then return end
            local ok, why = pcall(function()
                if read("wOtherTrainerClass")[1] ~= 0 or read("wBattleMode")[1] ~= 0
                   or read("wBattleType")[1] ~= 0 then return end
                local map = ctx.facts.maps.Route29
                if read("wMapGroup")[1] ~= map.map_group or read("wMapNumber")[1] ~= map.map_number then return end
                write("wTempWildMonSpecies", 0, {species}, "gs_species_encounter", {species_id=species,
                      site=site, disclosure="SYNTH: chosen wild species before native record generation; RUN/catch remain native"})
                planted = true
            end)
            if not ok then fault = tostring(why) end
        end, site.addr, "duo-gs-species-setup", "System Bus")
        local ok, met, foe = pcall(h.encounter)
        api.unregister(handle)
        if not ok then error(met, 0) end
        if fault then return false, fault end
        if not planted then return false, "StartBattle species setup never fired" end
        if not met then return false, foe end
        if foe ~= species then return false, "native foe differs from planted species" end
        return true, foe
    end
    return self
end
return M
