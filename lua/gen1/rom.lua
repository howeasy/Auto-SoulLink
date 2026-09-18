-- lua/gen1/rom.lua — the two ROM tables the client needs, read from the cartridge itself.
--
--   dex order   PokedexOrder (data/pokemon/dex_order.asm): internal index (1..190) -> dex (0 = hole)
--   base stats  BaseStats (data/pokemon/base_stats.asm): records in dex order, stride
--               profile.derived.base_stats_stride (28 vanilla, 35 pureRGB; PLAN §4 row 8),
--               dex 1..150 on R/B (Mew apart at MewBaseStats), 1..151 inline on Yellow/pureRGB.
--               Record: dex @0, hp/atk/def/spd/spc @1..5, types @6-7, catch rate @8, exp yield @9,
--               ... growth rate @19 (constants/pokemon_data_constants.asm:3-24). pureRGB appends
--               8 bytes after vanilla's 27 + padding, so every offset above is shared.
-- Addresses come from profile.rom (pret .sym); the Python twin is server/adapters/gen1_rom_scan.py.
-- io.read_u8(addr, "ROM") reads the flat ROM image.
--
-- `species_index` (optional, the pack's species_index.json) carries `species[internal]` for a
-- foundation whose dex map is many-to-one (pureRGB: forms carry their base dex "for rules",
-- MISSINGNO $B5 is the real dex 0, NonDex records live outside BaseStats). When it is absent
-- (vanilla) the cartridge's own PokedexOrder/BaseStats are the only source, as before.
local Rom = { RECORD = 28, GROWTH = 19 }
-- constants/pokemon_data_constants.asm:88-93 (const order), for pack-supplied growth names
Rom.GROWTH_INDEX = { GROWTH_MEDIUM_FAST = 0, GROWTH_SLIGHTLY_FAST = 1, GROWTH_SLIGHTLY_SLOW = 2,
                     GROWTH_MEDIUM_SLOW = 3, GROWTH_FAST = 4, GROWTH_SLOW = 5 }

function Rom.new(profile, io, species_index)
    local rom = assert(profile.rom, "profile.rom required")
    local d = assert(profile.derived, "profile.derived required")
    local stride = assert(d.base_stats_stride, "profile.derived.base_stats_stride required")
    local species_count = assert(d.species_count, "profile.derived.species_count required")
    -- dex_count counts dex NUMBERS: 151 (1..151) vanilla, 152 (0..151) when the pack seats
    -- MISSINGNO at dex 0. Either way the last numbered record is dex_hi.
    local dex_hi = assert(d.dex_count, "profile.derived.dex_count required") - 1
    local pack = species_index and species_index.species or nil
    local self = { stride = stride }
    local dex_cache, stats_cache = {}, {}

    local function pack_entry(internal)
        if not pack then return nil end
        return pack[tostring(internal)] or pack[internal]
    end

    function self.natdex(internal)
        if type(internal) ~= "number" or internal < 1 or internal > species_count then return nil end
        local e = pack_entry(internal)
        if e then
            if e.dex and e.dex > 0 then return e.dex end
            if e.classification == "missingno" then return 0 end -- a real, catchable dex 0
            return nil
        end
        if dex_cache[internal] == nil then
            dex_cache[internal] = io.read_u8(rom.PokedexOrder.flat + internal - 1, "ROM")
        end
        local dex = dex_cache[internal]
        if dex == 0 then return nil end
        return dex
    end

    local function record_at(flat)
        local r = {}
        for i = 0, stride - 1 do r[i] = io.read_u8(flat + i, "ROM") end
        return { dex = r[0], hp = r[1], attack = r[2], defense = r[3], speed = r[4], special = r[5],
                 type1 = r[6], type2 = r[7], catch_rate = r[8], growth_rate = r[Rom.GROWTH] }
    end

    -- A pack record (NonDex table / MISSINGNO) in the same shape record_at produces.
    local function pack_record(e)
        local st = e.stats or {}
        local growth = Rom.GROWTH_INDEX[e.growth_rate or ""]
        if not growth or not st.hp then return nil, "pack record incomplete for " .. tostring(e.name) end
        return { dex = e.dex, hp = st.hp, attack = st.atk, defense = st.def, speed = st.spd, special = st.spc,
                 type1 = e.types and e.types[1], type2 = e.types and e.types[2],
                 catch_rate = e.catch_rate, growth_rate = growth, pack = true }
    end

    -- Base stats for a national dex number; nil when the dex is out of range or the record's
    -- own dex byte disagrees (a wrong stride or symbol, never silently "close enough").
    function self.base_stats(dex)
        if type(dex) ~= "number" or dex < 1 or dex > dex_hi then return nil, "dex out of range" end
        if stats_cache[dex] then return stats_cache[dex] end
        local flat
        if dex == 151 and rom.MewBaseStats then flat = rom.MewBaseStats.flat
        else flat = rom.BaseStats.flat + (dex - 1) * stride end
        local rec = record_at(flat)
        if rec.dex ~= dex then return nil, "base stats record dex byte differs" end
        stats_cache[dex] = rec
        return rec
    end

    -- Convenience: base stats straight from a party mon's internal species index. A species
    -- whose record is not in BaseStats (pureRGB forms/spirits: stats_source "NonDex:n",
    -- MISSINGNO dex 0) comes from the pack, which was walked from the built ROM.
    function self.base_stats_for(internal)
        local e = pack_entry(internal)
        if e and (not e.stats_source or e.stats_source:sub(1, 9) ~= "BaseStats") then
            return pack_record(e)
        end
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

        -- rom.GoodRodMonsOcean only exists in a pureRGB profile (EXTRA_ROM_SYMBOLS,
        -- tools/gen_gen1_profile.py) -- vanilla's profile never carries it, so its presence
        -- is the same profile-driven signal the rest of this module uses elsewhere
        -- (rom.SuperRodFishingSlots above) rather than a foundation flag of its own.
        if rom.GoodRodMonsOcean then
            -- pureRGB engine/items/item_effects.asm's ItemUseOldRod is a 50/50 Magikarp/
            -- Goldeen roll: TWO `lb bc, LEVEL, SPECIES` immediates (each compiles to
            -- `ld bc,nn` = 01 <species> <level>, same shape as vanilla's one) at fixed
            -- offsets from the symbol -- the fixed-length instructions ahead of them
            -- (call FishingInit + jp c,.. + call Random + and 1 + jr z,.. = 13 bytes, then
            -- the fall-through `lb bc` itself) put them at +13 and +18 in all three built
            -- ROMs (gen1_rom_scan.py's _scan_old_rod_purergb docstring works out the same
            -- offsets from the same source). Each opcode is asserted first, exactly like
            -- vanilla's single site below, so a reassembled routine fails loudly instead of
            -- silently reading whatever byte happens to sit there.
            local old = assert(rom.ItemUseOldRod, "ItemUseOldRod symbol required").flat
            assert(byte(old + 13) == 1, "pureRGB Old Rod first lb bc site moved")
            assert(byte(old + 18) == 1, "pureRGB Old Rod second lb bc site moved")
            payload.old_rod = hex_bytes(old + 14, 2) .. hex_bytes(old + 19, 2)

            -- pureRGB data/wild/good_rod.asm: two tables back-to-back, GoodRodMons (land,
            -- pond/lake encounters) then GoodRodMonsOcean, each up to ten (level, species)
            -- pairs ending -1,-1 -- gen1_rom_scan.py's _scan_good_rod_purergb reads the same
            -- shape. The terminator itself is never sent: server/adapters/gen1_rom_scan.py's
            -- parse_client_content treats every two hex bytes as one more entry with no
            -- length hint, so a stray FF,FF would read back as a bogus species/level pair.
            local function read_pairs(flat)
                local pairs, cursor = {}, flat
                for _ = 1, 10 do
                    local level, species = byte(cursor), byte(cursor + 1)
                    if level == 255 and species == 255 then return table.concat(pairs) end
                    pairs[#pairs + 1] = hex_bytes(cursor, 2)
                    cursor = cursor + 2
                end
                error("Good Rod table: no -1,-1 terminator within 10 entries")
            end
            payload.good_rod = read_pairs(
                assert(rom.GoodRodMons, "GoodRodMons symbol required").flat)
            payload.good_rod_ocean = read_pairs(
                assert(rom.GoodRodMonsOcean, "GoodRodMonsOcean symbol required").flat)
        else
            -- pret engine/items/item_effects.asm:1826-1830 (Yellow:2026-2030):
            -- `lb bc, 5, MAGIKARP` assembles as opcode 01, then species, level;
            -- gen1_rom_scan.py:220-228 pins the +6 displacement and byte order.
            local old = assert(rom.ItemUseOldRod, "ItemUseOldRod symbol required").flat + 6
            assert(byte(old) == 1, "Old Rod instruction changed")
            payload.old_rod = hex_bytes(old + 1, 2)
            -- pret data/wild/good_rod.asm:2-5: two level/species pairs.
            payload.good_rod = hex_bytes(
                assert(rom.GoodRodMons, "GoodRodMons symbol required").flat, 4)
        end

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
