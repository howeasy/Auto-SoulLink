-- Read-only Gen 2 ROM tables, independently derived from these exact sources:
-- C = pret/pokecrystal@7a7881d0d62e0ddbd82dcf10e7116807487ac651
-- G = pret/pokegold@656583c939d30f920a316177311a502dd222b57c
-- C/G constants/pokemon_data_constants.asm and data/pokemon/base_stats/*.asm;
-- data/wild/{*_grass,*_water,probabilities,treemons,treemon_maps,fish,roammon_maps}.asm;
-- engine/events/{treemons,fish}.asm and engine/overworld/wildmons.asm InitRoamMons.
-- No legacy Gen 2 tables or Gen 1 record offsets are consumed. All addresses and
-- source-dependent counts come from a generated selected-title profile.
-- Methods use dot calls: reader.base_stats(species), reader.scan_all(), etc.
-- Invalid/missing data raises an error; unavailable families never become empty success.
-- This exports source table facts, not runtime selection, area policy or write authority.

local Rom = {}

local function integer(value, low, high, label)
    assert(type(value) == "number" and value % 1 == 0 and value >= low and value <= high,
        "invalid " .. label)
    return value
end

function Rom.new(profile, io)
    assert(type(profile) == "table", "selected title profile required")
    local title = profile.title
    assert(title == "crystal" or title == "gold" or title == "silver", "unsupported Gen 2 title")
    local facts = assert(profile.rom, "profile.rom required")
    local derived = assert(profile.derived, "profile.derived required")
    assert(io and io.read_u8, "io.read_u8 required")
    local size = integer(derived.rom_size, 1, 0x800000, "ROM size")
    local function constant(name, low, high)
        return integer(derived[name], low, high, "profile.derived." .. name)
    end
    local count = constant("species_count", 1, 251)
    local stride = constant("base_stats_stride", 24, 255)
    -- The supported schema is the pinned 251-species, 32-byte Gen 2 format.
    -- A changed profile is not permission to truncate a catalog or reinterpret it.
    assert(count == 251 and stride == 32, "unsupported Gen 2 base-stat geometry")
    local self = {}

    local function byte(flat)
        integer(flat, 0, size - 1, "ROM bounds")
        return integer(io.read_u8(flat, "ROM"), 0, 255, "ROM byte at " .. flat)
    end
    local function word(flat)
        return byte(flat) + byte(flat + 1) * 256
    end
    local function symbol(name)
        local entry = assert(facts[name], "required ROM symbol " .. name)
        local bank = integer(entry.bank, 0, 511, name .. " bank")
        local address = integer(entry.addr, bank == 0 and 0 or 0x4000,
            bank == 0 and 0x3fff or 0x7fff, name .. " ROM address")
        local flat = bank == 0 and address or bank * 0x4000 + address - 0x4000
        assert(entry.flat == flat, name .. " inconsistent bank/address/flat")
        integer(flat, 0, size - 1, name .. " ROM bounds")
        return entry
    end
    local function bank_end(entry)
        return math.min(size, (entry.bank + 1) * 0x4000)
    end
    local function span(flat, length, finish, label)
        assert(flat >= 0 and flat + length <= finish, label .. " exceeds ROM/table bounds")
    end
    local function pointer(entry, value, minimum)
        integer(value, 0x4000, 0x7fff, "banked ROM pointer")
        local flat = entry.bank * 0x4000 + value - 0x4000
        assert(entry.bank > 0 and flat >= minimum and flat < bank_end(entry),
            "ROM pointer outside table bounds")
        return flat
    end
    local function species(value)
        return integer(value, 1, count, "species")
    end
    local function level(value)
        return integer(value, 1, 100, "level")
    end
    local function map_at(flat)
        return {
            map_group = integer(byte(flat), 1, 254, "map group"),
            map_number = integer(byte(flat + 1), 1, 254, "map number"),
        }
    end
    local function unique_map(seen, row)
        local key = row.map_group .. ":" .. row.map_number
        assert(not seen[key], "duplicate map record")
        seen[key] = true
    end

    function self.base_stats(id)
        species(id)
        local entry = symbol("BaseData")
        local flat = entry.flat + (id - 1) * stride
        span(flat, stride, bank_end(entry), "base stats")
        assert(byte(flat) == id, "base stats species does not match record")
        -- C/G constants/pokemon_data_constants.asm:1-32: six base stat bytes,
        -- two types, held items, gender, hatch cycles, growth, packed egg groups.
        local record = { species = id, hp = byte(flat + 1), attack = byte(flat + 2),
            defense = byte(flat + 3), speed = byte(flat + 4),
            special_attack = byte(flat + 5), special_defense = byte(flat + 6),
            type1 = byte(flat + 7), type2 = byte(flat + 8), catch_rate = byte(flat + 9),
            base_exp = byte(flat + 10), item1 = byte(flat + 11), item2 = byte(flat + 12),
            gender_ratio = byte(flat + 13), hatch_cycles = byte(flat + 15),
            growth_rate = byte(flat + 22), egg_group1 = math.floor(byte(flat + 23) / 16),
            egg_group2 = byte(flat + 23) % 16, tmhm_bytes = {} }
        for offset = 24, stride - 1 do
            record.tmhm_bytes[#record.tmhm_bytes + 1] = byte(flat + offset)
        end
        return record
    end

    local function probabilities(name, slots)
        local entry, result, previous, seen = symbol(name), {}, 0, {}
        span(entry.flat, slots * 2, bank_end(entry), name)
        for index = 0, slots - 1 do
            local threshold, offset = byte(entry.flat + index * 2), byte(entry.flat + index * 2 + 1)
            assert(threshold > previous and threshold <= 100, "invalid wild probability threshold")
            assert(offset % 2 == 0 and offset < slots * 2 and not seen[offset],
                "invalid wild probability slot offset")
            result[#result + 1] = {threshold = threshold, slot_offset = offset}
            seen[offset], previous = true, threshold
        end
        assert(previous == 100, "incomplete wild probability table")
        return result
    end

    function self.wild()
        local grass_slots = constant("num_grassmon", 1, 32)
        local water_slots = constant("num_watermon", 1, 32)
        local result = {grass = {}, water = {},
            grass_probabilities = probabilities("GrassMonProbTable", grass_slots),
            water_probabilities = probabilities("WaterMonProbTable", water_slots)}
        local function read_table(name, slots, times, output)
            local entry, seen = symbol(name), {}
            local cursor, length = entry.flat, 2 + #times + slots * #times * 2
            while true do
                span(cursor, 1, bank_end(entry), name)
                if byte(cursor) == 255 then return end
                span(cursor, length, bank_end(entry), name)
                local map = map_at(cursor)
                unique_map(seen, map)
                for time_index, time in ipairs(times) do
                    local row = {table = name, map_group = map.map_group, map_number = map.map_number,
                        time = time, rate = byte(cursor + 1 + time_index), slots = {}}
                    local start = cursor + 2 + #times + (time_index - 1) * slots * 2
                    for index = 0, slots - 1 do
                        row.slots[#row.slots + 1] = {
                            level = level(byte(start + index * 2)),
                            species = species(byte(start + index * 2 + 1)),
                        }
                    end
                    output[#output + 1] = row
                end
                cursor = cursor + length
            end
        end
        for _, region in ipairs({"Johto", "Kanto", "Swarm"}) do
            read_table(region .. "GrassWildMons", grass_slots, {"morning", "day", "night"}, result.grass)
            read_table(region .. "WaterWildMons", water_slots, {"all"}, result.water)
        end
        return result
    end

    function self.tree()
        local set_count = constant("num_treemon_sets", 2, 256)
        local rock_id = constant("treemon_set_rock", 1, set_count - 1)
        -- Generated profile fact (tools/gen_gen2_profile.py): GetTreeMons refuses set 0
        -- and every set >= limit (C engine/events/treemons.asm:100-105, G :98-102).
        local limit = constant("treemon_enabled_limit", rock_id + 1, set_count)
        local result = {headbutt_maps = {}, rock_smash_maps = {}, sets = {}, enabled_set_limit = limit}
        local function maps(name)
            local entry, output, seen = symbol(name), {}, {}
            local cursor = entry.flat
            while true do
                span(cursor, 1, bank_end(entry), name)
                if byte(cursor) == 255 then return output end
                span(cursor, 3, bank_end(entry), name)
                local row = map_at(cursor)
                unique_map(seen, row)
                row.set_id = integer(byte(cursor + 2), 0, set_count - 1, "tree set id")
                output[#output + 1], cursor = row, cursor + 3
            end
        end
        result.headbutt_maps, result.rock_smash_maps = maps("TreeMonMaps"), maps("RockMonMaps")
        local entry = symbol("TreeMons")
        span(entry.flat, set_count * 2, bank_end(entry), "TreeMons")
        local function slots(cursor)
            local output, total = {}, 0
            while true do
                span(cursor, 1, bank_end(entry), "tree slots")
                if byte(cursor) == 255 then
                    assert(total == 100, "incomplete tree weights")
                    return output, cursor + 1
                end
                span(cursor, 3, bank_end(entry), "tree slots")
                local weight = integer(byte(cursor), 1, 100, "tree weight")
                total = total + weight
                assert(total <= 100, "tree weights exceed 100")
                output[#output + 1] = {weight = weight, species = species(byte(cursor + 1)),
                    level = level(byte(cursor + 2))}
                cursor = cursor + 3
            end
        end
        -- Disabled sets (zero, and G/S UNUSED/CITY) are deliberately not decoded,
        -- even when their pointers alias real data.
        for id = 1, limit - 1 do
            local cursor = pointer(entry, word(entry.flat + id * 2), entry.flat + set_count * 2)
            local common, next_cursor = slots(cursor)
            local rare = {}
            if id ~= rock_id then rare = slots(next_cursor) end
            result.sets[#result.sets + 1] = {set_id = id,
                kind = id == rock_id and "rock_smash" or "headbutt", common = common, rare = rare}
        end
        return result
    end

    function self.fishing()
        local groups = constant("num_fishgroups", 1, 255)
        local time_count = constant("num_time_fishgroups", 1, 256)
        local entry, time_entry = symbol("FishGroups"), symbol("TimeFishGroups")
        local result = {groups = {}, time_groups = {}}
        span(entry.flat, groups * 7, bank_end(entry), "FishGroups")
        span(time_entry.flat, time_count * 4, bank_end(time_entry), "TimeFishGroups")
        local function rod(cursor)
            local output, previous = {}, -1
            while true do
                span(cursor, 3, bank_end(entry), "fishing slots")
                local threshold, id, lev = byte(cursor), byte(cursor + 1), byte(cursor + 2)
                assert(threshold > previous, "fishing thresholds must increase")
                if id == 0 then
                    integer(lev, 0, time_count - 1, "fishing time group index")
                else
                    species(id)
                    level(lev)
                end
                output[#output + 1] = {threshold = threshold, species = id, level = lev}
                if threshold == 255 then return output end
                cursor, previous = cursor + 3, threshold
            end
        end
        for index = 0, groups - 1 do
            local cursor = entry.flat + index * 7
            local row = {group_id = index + 1, bite_threshold = byte(cursor)}
            for rod_index, name in ipairs({"old", "good", "super"}) do
                row[name] = rod(pointer(entry, word(cursor + rod_index * 2 - 1), entry.flat + groups * 7))
            end
            result.groups[#result.groups + 1] = row
        end
        for index = 0, time_count - 1 do
            local cursor = time_entry.flat + index * 4
            result.time_groups[#result.time_groups + 1] = {group_id = index,
                day = {species = species(byte(cursor)), level = level(byte(cursor + 1))},
                night = {species = species(byte(cursor + 2)), level = level(byte(cursor + 3))}}
        end
        return result
    end

    function self.roamers()
        local active = constant("roamer_count", 1, 3)
        local map_count = constant("num_roammon_maps", 1, 255)
        local ram = assert(profile.ram, "profile.ram required for roamer instruction binding")
        local start, finish = symbol("InitRoamMons"), symbol("CheckEncounterRoamMon")
        assert(start.bank == finish.bank and finish.flat > start.flat, "roamer initializer bounds")
        local destinations, values = {}, {}
        for index = 1, active do
            values[index] = {}
            for _, name in ipairs({"Species", "Level", "MapGroup", "MapNumber", "HP"}) do
                local address = integer(ram["wRoamMon" .. index .. name], 0xc000, 0xdfff,
                    "roamer RAM binding")
                assert(not destinations[address], "duplicate roamer RAM binding")
                destinations[address] = {index, name}
            end
        end
        -- Interpret only the straight-line load/store initializer's observed
        -- instruction vocabulary. Unknown opcode/target/order or missing ret fails.
        local cursor, accumulator, returned = start.flat, nil, false
        while cursor < finish.flat do
            local opcode = byte(cursor)
            if opcode == 0x3e then -- ld a, immediate
                span(cursor, 2, finish.flat, "roamer immediate")
                accumulator, cursor = byte(cursor + 1), cursor + 2
            elseif opcode == 0xaf then -- xor a
                accumulator, cursor = 0, cursor + 1
            elseif opcode == 0xea then -- ld [absolute RAM], a
                span(cursor, 3, finish.flat, "roamer store")
                local target = assert(destinations[word(cursor + 1)], "unknown roamer store target")
                local record = values[target[1]]
                assert(accumulator ~= nil and record[target[2]] == nil, "invalid roamer assignment")
                record[target[2]], cursor = accumulator, cursor + 3
            elseif opcode == 0xc9 then -- ret
                assert(cursor + 1 == finish.flat, "roamer initializer trailing bytes")
                returned, cursor = true, cursor + 1
            else
                error("unsupported roamer initializer opcode " .. opcode)
            end
        end
        assert(returned, "roamer initializer return missing")
        local result = {initial = {}, maps = {}}
        for _, record in ipairs(values) do
            assert(record.HP == 0, "roamer HP initializer not zero")
            result.initial[#result.initial + 1] = {species = species(record.Species),
                level = level(record.Level), map_group = integer(record.MapGroup, 1, 254, "roamer map group"),
                map_number = integer(record.MapNumber, 1, 254, "roamer map number")}
        end
        local entry, seen = symbol("RoamMaps"), {}
        cursor = entry.flat
        for _ = 1, map_count do
            span(cursor, 3, bank_end(entry), "RoamMaps")
            local row = map_at(cursor)
            unique_map(seen, row)
            local connections = integer(byte(cursor + 2), 1, 4, "roamer connection count")
            span(cursor, 4 + connections * 2, bank_end(entry), "RoamMaps destinations")
            row.destinations = {}
            for offset = 0, connections - 1 do
                row.destinations[#row.destinations + 1] = map_at(cursor + 3 + offset * 2)
            end
            cursor = cursor + 3 + connections * 2
            assert(byte(cursor) == 0, "roamer map separator missing")
            cursor = cursor + 1
            result.maps[#result.maps + 1] = row
        end
        span(cursor, 1, bank_end(entry), "RoamMaps terminator")
        assert(byte(cursor) == 255, "roamer map terminator missing")
        for _, row in ipairs(result.maps) do
            for _, dest in ipairs(row.destinations) do
                assert(seen[dest.map_group .. ":" .. dest.map_number], "roamer destination outside graph")
            end
        end
        return result
    end

    function self.scan_all()
        local result = {schema = "gen2-rom-tables-v1", title = title, base_stats = {},
            wild = self.wild(), tree = self.tree(), fishing = self.fishing(), roamers = self.roamers(),
            open_obligations = {"fishing_map_association", "contest_encounters", "runtime_encounter_selection"}}
        for id = 1, count do result.base_stats[#result.base_stats + 1] = self.base_stats(id) end
        return result
    end
    return self
end

return Rom
