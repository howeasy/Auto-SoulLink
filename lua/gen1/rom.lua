-- lua/gen1/rom.lua — the two ROM tables the client needs, read from the cartridge itself.
--
--   dex order   PokedexOrder (data/pokemon/dex_order.asm): internal index (1..190) -> dex (0 = hole)
--   base stats  BaseStats (data/pokemon/base_stats.asm): 28-byte records in dex order,
--               dex 1..150 on R/B (Mew apart at MewBaseStats), 1..151 inline on Yellow.
--               Record: dex @0, hp/atk/def/spd/spc @1..5, types @6-7, catch rate @8, exp yield @9,
--               ... growth rate @19 (constants/pokemon_data_constants.asm:3-24).
-- Addresses come from profile.rom (pret .sym); the Python twin is server/adapters/gen1_rom_scan.py.
-- io.read_u8(addr, "ROM") reads the flat ROM image.
local Rom = { RECORD = 28, GROWTH = 19 }

function Rom.new(profile, io)
    local rom = assert(profile.rom, "profile.rom required")
    local self = {}
    local dex_cache, stats_cache = {}, {}

    function self.natdex(internal)
        if type(internal) ~= "number" or internal < 1 or internal > 190 then return nil end
        if dex_cache[internal] == nil then
            dex_cache[internal] = io.read_u8(rom.PokedexOrder.flat + internal - 1, "ROM")
        end
        local dex = dex_cache[internal]
        if dex == 0 then return nil end
        return dex
    end

    local function record_at(flat)
        local r = {}
        for i = 0, Rom.RECORD - 1 do r[i] = io.read_u8(flat + i, "ROM") end
        return { dex = r[0], hp = r[1], attack = r[2], defense = r[3], speed = r[4], special = r[5],
                 type1 = r[6], type2 = r[7], catch_rate = r[8], growth_rate = r[Rom.GROWTH] }
    end

    -- Base stats for a national dex number; nil when the dex is out of range or the record's
    -- own dex byte disagrees (a wrong stride or symbol, never silently "close enough").
    function self.base_stats(dex)
        if type(dex) ~= "number" or dex < 1 or dex > 151 then return nil, "dex out of range" end
        if stats_cache[dex] then return stats_cache[dex] end
        local flat
        if dex == 151 and rom.MewBaseStats then flat = rom.MewBaseStats.flat
        else flat = rom.BaseStats.flat + (dex - 1) * Rom.RECORD end
        local rec = record_at(flat)
        if rec.dex ~= dex then return nil, "base stats record dex byte differs" end
        stats_cache[dex] = rec
        return rec
    end

    -- Convenience: base stats straight from a party mon's internal species index.
    function self.base_stats_for(internal)
        local dex = self.natdex(internal)
        if not dex then return nil, "no dex entry for species " .. tostring(internal) end
        return self.base_stats(dex)
    end

    return self
end

return Rom
