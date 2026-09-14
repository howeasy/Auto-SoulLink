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

    local function byte(flat)
        local value = io.read_u8(flat, "ROM")
        assert(type(value) == "number" and value >= 0 and value <= 255, "ROM byte unavailable at " .. tostring(flat))
        return value
    end

    local function little16(flat)
        return byte(flat) + 256 * byte(flat + 1)
    end

    local function hex_bytes(flat, length)
        local parts = {}
        for i = 0, length - 1 do parts[#parts + 1] = string.format("%02x", byte(flat + i)) end
        return table.concat(parts)
    end

    local function bank_pointer(symbol, pointer)
        -- GB switchable ROM window; server/adapters/gen1_rom_scan.py:163-174,244-249.
        assert(pointer >= 16384 and pointer <= 32767, "ROM pointer outside switchable bank")
        return symbol.bank * 16384 + pointer - 16384
    end

    function self.rom_content()
        -- The generated title is the scanner's variant (gen1_rom_scan.py:70,134).
        local payload = { variant = assert(profile.variant, "profile.variant required"), wild = {}, super_rod = {} }

        -- pret data/wild/grass_water.asm:1,251-252: one LE pointer per map,
        -- terminated by dw -1. Nonzero rate precedes ten level/species pairs;
        -- server/adapters/gen1_rom_scan.py:150-153,183-212 defines the same walk.
        local wild_symbol = assert(rom.WildDataPointers, "WildDataPointers symbol required")
        local table_flat, first_record, map_id = wild_symbol.flat, math.huge, 0
        while true do
            assert(map_id <= 255, "wild pointer terminator missing")
            local pointer_flat = table_flat + 2 * map_id
            local pointer = little16(pointer_flat)
            if pointer == 65535 then break end
            assert(pointer_flat < first_record, "wild pointer table entered records")
            local record = bank_pointer(wild_symbol, pointer)
            first_record = math.min(first_record, record)
            local cursor, populated = record, false
            for _ = 1, 2 do
                local rate = byte(cursor)
                cursor = cursor + 1
                if rate ~= 0 then
                    populated = true
                    cursor = cursor + 20 -- ten level/species pairs; gen1_rom_scan.py:75,208
                end
            end
            if populated then payload.wild[tostring(map_id)] = hex_bytes(record, cursor - record) end
            map_id = map_id + 1
        end

        -- pret engine/items/item_effects.asm:1826-1830 (Yellow:2026-2030):
        -- `lb bc, 5, MAGIKARP` assembles as opcode 01, then species, level;
        -- gen1_rom_scan.py:220-228 pins the +6 displacement and byte order.
        local old = assert(rom.ItemUseOldRod, "ItemUseOldRod symbol required").flat + 6
        assert(byte(old) == 1, "Old Rod instruction changed")
        payload.old_rod = hex_bytes(old + 1, 2)
        -- pret data/wild/good_rod.asm:2-5: two level/species pairs.
        payload.good_rod = hex_bytes(assert(rom.GoodRodMons, "GoodRodMons symbol required").flat, 4)

        if rom.SuperRodFishingSlots then
            -- Yellow data/wild/super_rod.asm:1-2,32-33: 9-byte records,
            -- map then four species/level pairs, ending in db -1.
            local cursor, seen = rom.SuperRodFishingSlots.flat, 0
            while byte(cursor) ~= 255 do
                assert(seen <= 255, "Yellow Super Rod terminator missing")
                payload.super_rod[tostring(byte(cursor))] = hex_bytes(cursor + 1, 8)
                cursor, seen = cursor + 9, seen + 1
            end
        else
            -- R/B data/wild/super_rod.asm:2-4,34-39: map + LE group pointer,
            -- then count followed by that many level/species pairs; db -1 ends.
            local symbol = assert(rom.SuperRodData, "Super Rod symbol required")
            local cursor, seen = symbol.flat, 0
            while byte(cursor) ~= 255 do
                assert(seen <= 255, "Super Rod terminator missing")
                local group = bank_pointer(symbol, little16(cursor + 1))
                local count = byte(group)
                assert(count >= 1 and count <= 10, "invalid Super Rod group count")
                payload.super_rod[tostring(byte(cursor))] = hex_bytes(group, 1 + 2 * count)
                cursor, seen = cursor + 3, seen + 1
            end
        end
        return payload
    end

    return self
end

return Rom
