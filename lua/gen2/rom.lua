-- Read-only Gen 2 ROM tables, independently derived from these exact sources:
-- C = pret/pokecrystal@7a7881d0d62e0ddbd82dcf10e7116807487ac651
-- G = pret/pokegold@656583c939d30f920a316177311a502dd222b57c
-- P = Rangi42/polishedcrystal@3fa43192379df5c3e7b09a08e4d5d79af4f02f42 (title "polished")
-- C/G constants/pokemon_data_constants.asm and data/pokemon/base_stats/*.asm;
-- data/wild/{*_grass,*_water,probabilities,treemons,treemon_maps,fish,roammon_maps}.asm;
-- engine/events/{treemons,fish}.asm and engine/overworld/wildmons.asm InitRoamMons.
-- No legacy Gen 2 tables or Gen 1 record offsets are consumed. All addresses and
-- source-dependent counts come from a generated selected-title profile.
-- A profile without `layout` is vanilla Gen 2 and decodes exactly as before. Polished's
-- generated `layout` (tools/gen_polished_profile.py, docs/polished/ROMTABLES.md) only
-- changes numbers: 2-byte `dp` species, 1-byte probability rows, the fish group header,
-- badge-relative levels, set 0 enabled, `inc a` in InitRoamMons, base-stat field offsets.
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
    assert(title == "crystal" or title == "gold" or title == "silver" or title == "polished",
        "unsupported Gen 2 title")
    local facts = assert(profile.rom, "profile.rom required")
    local derived = assert(profile.derived, "profile.derived required")
    assert(io and io.read_u8, "io.read_u8 required")
    local size = integer(derived.rom_size, 1, 0x800000, "ROM size")
    local function constant(name, low, high)
        return integer(derived[name], low, high, "profile.derived." .. name)
    end
    -- Vanilla geometry unless the profile declares otherwise (only Polished's does).
    local layout = profile.layout or {}
    assert(title ~= "polished" or profile.layout, "polished profile requires layout")
    local species_bytes = integer(layout.species_bytes or 1, 1, 2, "layout.species_bytes")
    local prob_width = integer(layout.prob_width or 2, 1, 2, "layout.prob_width")
    local fish_header = integer(layout.fish_group_header or 7, 7, 8, "layout.fish_group_header")
    local fish_base = integer(layout.fish_group_base or 1, 0, 1, "layout.fish_group_base")
    local tree_first = integer(layout.tree_first_set or 1, 0, 1, "layout.tree_first_set")
    local badge_level = layout.level_from_badges
    if badge_level ~= nil then integer(badge_level, 101, 255, "layout.level_from_badges") end
    local count = constant("species_count", 1, 1023)
    local stride = constant("base_stats_stride", 24, 255)
    -- Base-stat geometry must equal the layout's declaration: vanilla's is the pinned 251 x 32,
    -- Polished's comes from its UPR ini while profile.derived comes from source, so a drifted
    -- profile refuses instead of truncating or misaligning the catalog.
    assert(count == (layout.species_count or 251) and stride == (layout.base_stats_stride or 32),
        "base-stat geometry disagrees with the declared layout")
    -- C/G constants/pokemon_data_constants.asm:1-32 (BASE_DEX_NO first); Polished's
    -- generated base_fields come from its own BASE_* rs block (no species byte at all).
    local fields = layout.base_fields or {species = 0, hp = 1, attack = 2, defense = 3,
        speed = 4, sat = 5, sdf = 6, type1 = 7, type2 = 8, catch_rate = 9, base_exp = 10,
        item1 = 11, item2 = 12, gender = 13, hatch = 15, growth = 22, egg_groups = 23, tmhm = 24}
    -- Replaces the old `count == 251 and stride == 32` pin (one game's numbers): every
    -- declared field must sit inside the record, before the TM/HM bit block.
    integer(fields.tmhm, 1, stride - 1, "base_fields.tmhm")
    for name, offset in pairs(fields) do
        if name ~= "tmhm" then integer(offset, 0, fields.tmhm - 1, "base_fields." .. name) end
    end
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
    -- Raw species at `flat`: vanilla 1 byte; Polished `dp` = LOW(species), then
    -- HIGH(species) << MON_EXTSPECIES_F | form (P macros/data.asm:89-95). Returns id, form.
    local function raw_species(flat)
        if species_bytes == 1 then return byte(flat), nil end
        local high = byte(flat + 1)
        assert(high < 0x40, "invalid dp species high byte")
        local form = high % 0x20
        return byte(flat) + (high - form) * 8, form
    end
    local function species_at(flat)
        local id, form = raw_species(flat)
        return species(id), form
    end
    local function level(value)
        return integer(value, 1, 100, "level")
    end
    -- Sets the level of `slot`. Polished AdjustLevelForBadges (P engine/overworld/wildmons.asm
    -- :1176-1193) reads a raw byte above MAX_LEVEL as LEVEL_FROM_BADGES +/- offset, resolved
    -- only at runtime from the badge count, so such a slot carries the raw value, no level.
    local function set_level(slot, raw)
        if badge_level ~= nil and raw > 100 then
            slot.level_raw, slot.level_from_badges_offset = raw, raw - badge_level
        else
            slot.level = level(raw)
        end
        return slot
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
        -- Plain-form records are indexed species - 1 in both (P GetSpeciesAndFormIndex
        -- `.normal`); Polished's variant records past NUM_SPECIES are not exposed here.
        local flat = entry.flat + (id - 1) * stride
        span(flat, stride, bank_end(entry), "base stats")
        local f = fields
        if f.species then
            assert(byte(flat + f.species) == id, "base stats species does not match record")
        end
        local function at(name) return f[name] and byte(flat + f[name]) end
        local record = { species = id, hp = at("hp"), attack = at("attack"),
            defense = at("defense"), speed = at("speed"),
            special_attack = at("sat"), special_defense = at("sdf"),
            type1 = at("type1"), type2 = at("type2"), catch_rate = at("catch_rate"),
            base_exp = at("base_exp"), item1 = at("item1"), item2 = at("item2"),
            gender_ratio = at("gender"), hatch_cycles = at("hatch"),
            growth_rate = at("growth"), egg_group1 = math.floor(at("egg_groups") / 16),
            egg_group2 = at("egg_groups") % 16, tmhm_bytes = {} }
        for offset = f.tmhm, stride - 1 do
            record.tmhm_bytes[#record.tmhm_bytes + 1] = byte(flat + offset)
        end
        return record
    end

    local function probabilities(name, slots)
        local entry, result, previous, seen = symbol(name), {}, 0, {}
        span(entry.flat, slots * prob_width, bank_end(entry), name)
        for index = 0, slots - 1 do
            local threshold = byte(entry.flat + index * prob_width)
            assert(threshold > previous and threshold <= 100, "invalid wild probability threshold")
            -- vanilla `mon_prob` = (percent, slot offset); Polished table_width 1 = the
            -- cumulative percent only, the slot implied by position.
            local offset = index * 2
            if prob_width == 2 then
                offset = byte(entry.flat + index * 2 + 1)
                assert(offset % 2 == 0 and offset < slots * 2 and not seen[offset],
                    "invalid wild probability slot offset")
            end
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
        local width = 1 + species_bytes
        local function read_table(name, slots, times, output, declared)
            local entry, seen = symbol(name), {}
            local cursor, length = entry.flat, 2 + #times + slots * #times * width
            assert(declared == nil or declared == length, name .. " row length disagrees with layout")
            while true do
                span(cursor, 1, bank_end(entry), name)
                if byte(cursor) == 255 then return end
                span(cursor, length, bank_end(entry), name)
                local map = map_at(cursor)
                unique_map(seen, map)
                for time_index, time in ipairs(times) do
                    local row = {table = name, map_group = map.map_group, map_number = map.map_number,
                        time = time, rate = byte(cursor + 1 + time_index), slots = {}}
                    local start = cursor + 2 + #times + (time_index - 1) * slots * width
                    for index = 0, slots - 1 do
                        local at = start + index * width
                        local id, form = species_at(at + 1)
                        row.slots[#row.slots + 1] = set_level({species = id, form = form}, byte(at))
                    end
                    output[#output + 1] = row
                end
                cursor = cursor + length
            end
        end
        for _, region in ipairs(layout.wild_regions or {"Johto", "Kanto", "Swarm"}) do
            read_table(region .. "GrassWildMons", grass_slots, {"morning", "day", "night"}, result.grass,
                layout.wild_grass_row)
            read_table(region .. "WaterWildMons", water_slots, {"all"}, result.water, layout.wild_water_row)
        end
        return result
    end

    function self.tree()
        local set_count = constant("num_treemon_sets", 2, 256)
        local rock_id = constant("treemon_set_rock", 1, set_count - 1)
        -- Generated profile fact (tools/gen_gen2_profile.py): GetTreeMons refuses set 0
        -- and every set >= limit (C engine/events/treemons.asm:100-105, G :98-102).
        -- Polished's GetTreeMons is only `cp NUM_TREEMON_SETS / ret nc`: set 0 is live.
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
        local width = 2 + species_bytes
        local function slots(cursor)
            local output, total = {}, 0
            while true do
                span(cursor, 1, bank_end(entry), "tree slots")
                if byte(cursor) == 255 then
                    assert(total == 100, "incomplete tree weights")
                    return output, cursor + 1
                end
                span(cursor, width, bank_end(entry), "tree slots")
                local weight = integer(byte(cursor), 1, 100, "tree weight")
                total = total + weight
                assert(total <= 100, "tree weights exceed 100")
                local id, form = species_at(cursor + 1)
                output[#output + 1] = set_level({weight = weight, species = id, form = form},
                    byte(cursor + width - 1))
                cursor = cursor + width
            end
        end
        -- Disabled sets (zero, and G/S UNUSED/CITY) are deliberately not decoded,
        -- even when their pointers alias real data.
        for id = tree_first, limit - 1 do
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
        -- Polished has no TimeFishGroups: a species-0 row is an engine time-of-day pick
        -- (P engine/events/fish.asm .TimeEncounter) whose level byte is a real level.
        local time_count = constant("num_time_fishgroups", profile.layout and 0 or 1, 256)
        local entry = symbol("FishGroups")
        local result = {groups = {}, time_groups = {}}
        span(entry.flat, groups * fish_header, bank_end(entry), "FishGroups")
        local time_entry
        if time_count > 0 then
            time_entry = symbol("TimeFishGroups")
            span(time_entry.flat, time_count * 4, bank_end(time_entry), "TimeFishGroups")
        end
        local width = 2 + species_bytes
        local function rod(cursor)
            local output, previous = {}, -1
            while true do
                span(cursor, width, bank_end(entry), "fishing slots")
                local threshold, raw = byte(cursor), byte(cursor + width - 1)
                local id, form = raw_species(cursor + 1)
                assert(threshold > previous, "fishing thresholds must increase")
                local slot = {threshold = threshold, species = id, form = form}
                if id == 0 and time_count > 0 then
                    integer(raw, 0, time_count - 1, "fishing time group index")
                    slot.level = raw
                elseif id == 0 then
                    slot.time_dependent = true
                    set_level(slot, raw)
                else
                    species(id)
                    set_level(slot, raw)
                end
                output[#output + 1] = slot
                if threshold == 255 then return output end
                cursor, previous = cursor + width, threshold
            end
        end
        -- Header: the bite threshold(s), then three rod pointers in its last six bytes.
        for index = 0, groups - 1 do
            local cursor = entry.flat + index * fish_header
            local row = {group_id = index + fish_base, bite_threshold = byte(cursor)}
            if fish_header == 8 then row.bite_or_item_threshold = byte(cursor + 1) end
            for rod_index, name in ipairs({"old", "good", "super"}) do
                row[name] = rod(pointer(entry, word(cursor + fish_header - 8 + rod_index * 2),
                    entry.flat + groups * fish_header))
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

    -- Bug-Catching Contest table (Polished ContestMons..ContestMonsEnd: % chance, dp,
    -- min level, max level). The vanilla profiles carry no ContestMons, so this refuses there.
    function self.contest()
        local entry, finish = symbol("ContestMons"), symbol("ContestMonsEnd")
        local width = 3 + species_bytes
        assert(finish.bank == entry.bank and (finish.flat - entry.flat) % width == 0
            and finish.flat > entry.flat, "contest table bounds")
        local output, total = {}, 0
        for cursor = entry.flat, finish.flat - 1, width do
            local id, form = species_at(cursor + 1)
            local weight = integer(byte(cursor), 1, 100, "contest weight")
            local low = level(byte(cursor + width - 2))
            local high = level(byte(cursor + width - 1))
            assert(low <= high, "contest level range inverted")
            total = total + weight
            output[#output + 1] = {weight = weight, species = id, form = form,
                min_level = low, max_level = high}
        end
        assert(total == 100, "contest weights must total 100")
        return output
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
        -- Polished adds `inc a` (P wildmons.asm:689 `assert RAIKOU + 1 == ENTEI`), and
        -- only a layout that declares it may use it.
        local cursor, accumulator, returned = start.flat, nil, false
        while cursor < finish.flat do
            local opcode = byte(cursor)
            if opcode == 0x3e then -- ld a, immediate
                span(cursor, 2, finish.flat, "roamer immediate")
                accumulator, cursor = byte(cursor + 1), cursor + 2
            elseif opcode == 0xaf then -- xor a
                accumulator, cursor = 0, cursor + 1
            elseif opcode == 0x3c and layout.roamer_inc_a then -- inc a
                assert(accumulator ~= nil, "roamer inc a before load")
                accumulator, cursor = (accumulator + 1) % 256, cursor + 1
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
