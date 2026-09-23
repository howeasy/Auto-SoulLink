-- Gen 3 PC moves. All cartridge mutations pass through the armed writes sink.
-- REQUIRED_PROFILE_FIELDS (generator/profile owner must supply these for FR/LG):
--   rom.EXPERIENCE_TABLES_ADDR: FR 0x08253AE4, LG 0x08253AC0
--     pret pokefirered.sym:26980; pokeleafgreen.sym:26982 (gExperienceTables).
--   rom.BATTLE_MOVES_ADDR: FR 0x08250C04, LG 0x08250BE0
--     pret pokefirered.sym:26905; pokeleafgreen.sym:26907 (gBattleMoves).
--   rom.PP_UP_GET_MASK_ADDR: FR 0x0825DEA1, LG 0x0825DE81
--     pret pokefirered.sym:27396; pokeleafgreen.sym:27398 (gPPUpGetMask).
--   derived.BATTLE_MOVE_ENTRY_SIZE=12, BATTLE_MOVE_PP_OFFSET=4
--     pret include/pokemon.h:238-249; gBattleMoves sym size 0x10A4 / 355.
--   derived.SHEDINJA_SPECIES_ID=303 (pret include/constants/species.h:312).
-- RR-OPEN: compressed layout is from the RR profile's CFRU_BOX_BASES/stride and
-- old memory_gba.lua:1015-1104; this unit suite has no RR-binary save readback.
-- Experience and PP use the RR binary-pinned tables and dimensions. Full RR stat
-- calculation is a replacement routine (ROM 0x0803E47C detours to 0x090788FC),
-- so table layout alone does not establish vanilla stat semantics. Keep complete
-- engine-derived cached stats; a natural RR boxsync save witness still gates RC.
local B = {}
local PARTY_SIZE, BOX_SIZE = 100, 80 -- pret include/pokemon.h:105-141
local ATTACKS_POSITION = {
    [0]=1, 1, 2, 3, 2, 3, 0, 0, 0, 0, 0, 0,
    2, 3, 1, 1, 3, 2, 2, 3, 1, 1, 3, 2,
} -- pret src/pokemon.c GetSubstruct; position of Attacks for PID % 24

local function word(bytes, off, width)
    local result = 0
    for i = width - 1, 0, -1 do result = result * 256 + bytes[off + i + 1] end
    return result
end
local function put(bytes, off, width, value)
    for i = 0, width - 1 do
        bytes[off + i + 1] = value & 0xFF
        value = value >> 8
    end
end
local function copy(bytes, off, length)
    local out = {}
    for i = 1, length do out[i] = bytes[off + i] end
    return out
end
local function zero(length)
    local out = {}
    for i = 1, length do out[i] = 0 end
    return out
end

function B.new(profile, reads, io)
    assert(type(profile) == "table" and type(profile.ram) == "table"
           and type(profile.derived) == "table", "Gen 3 title profile required")
    assert(type(reads) == "table" and type(io) == "table" and io.writes,
           "read facade and armed writes required")
    local d = profile.derived
    local a = profile.ram
    local rr = d.CFRU_COMPRESSED_BOX == true
    local box_count = assert(d.BOXES_PER_STORE, "box count required")
    local mons_per_box = assert(d.MONS_PER_BOX or reads.mons_per_box, "box capacity required")
    local stride = rr and assert(d.COMPRESSED_MON_SIZE, "compressed stride required") or BOX_SIZE
    local self = {memorial_box = box_count - 1}
    -- Optional RR companion executor owns its own native safety/ABI. Entry does
    -- not inject it in P4, so the default remains the Lua storage path below.
    local native = rr and io.native_executor

    local function layout()
        local party_base, why = reads.party_base()
        if not party_base then return nil, why end
        local storage
        if not rr then
            storage, why = reads.read_storage()
            if not storage then return nil, why end
        end
        local function box_addr(box, slot)
            if rr then
                local base = assert(d.CFRU_BOX_BASES and d.CFRU_BOX_BASES[box + 1],
                                    "RR box base missing from profile")
                return base + slot * stride
            end
            return storage + assert(d.BOX_DATA_OFFSET, "box data offset required")
                   + (box * mons_per_box + slot) * stride
        end
        local function allow(addr, length)
            local ending = addr + length
            if addr >= party_base and ending <= party_base + PARTY_SIZE * reads.party_capacity then
                return true
            end
            if addr == a.PARTY_COUNT_ADDR and length == 1 then return true end
            if rr then
                for box = 0, box_count - 1 do
                    local base = box_addr(box, 0)
                    if addr >= base and ending <= base + mons_per_box * stride then return true end
                end
            else
                local base = box_addr(0, 0)
                if addr >= base and ending <= base + box_count * mons_per_box * stride then
                    return true
                end
            end
            return false
        end
        return {party = party_base, storage = storage, box_addr = box_addr, allow = allow}
    end

    local expanded_box
    local function boxes_state(place)
        local found, free
        for box = 0, box_count - 1 do
            for slot = 0, mons_per_box - 1 do
                local addr = place.box_addr(box, slot)
                local raw = io.read_bytes(addr, stride)
                local mon, why = reads.decode_box_mon(expanded_box(raw))
                if not mon then return nil, nil, why end
                -- The game tests MON_DATA_SPECIES, not the hasSpecies header bit.
                if mon.species ~= 0 then
                    local key = string.format("%08X:%08X", word(raw, 0, 4), word(raw, 4, 4))
                    found = found or {}
                    found[#found + 1] = {box=box, slot=slot, addr=addr, raw=raw, key=key}
                elseif box ~= self.memorial_box and not free then
                    free = {box=box, slot=slot, addr=addr}
                end
            end
        end
        return found or {}, free
    end

    local function matches(entries, key)
        local found
        for _, entry in ipairs(entries) do
            if entry.key == key then
                if found then return nil, "ambiguous duplicate boxed key" end
                found = entry
            end
        end
        return found
    end

    local function write_plan(place, plan)
        io.writes:arm("overworld", place.allow)
        local ok, err = pcall(function()
            -- A relocation between read/plan and arm must not make the
            -- arm-time safety snapshot bless the old storage address.
            if not rr then
                local current = reads.read_storage()
                assert(current == place.storage, "storage pointer moved before box write")
            end
            for _, change in ipairs(plan) do io.writes:write_bytes(change[1], change[2]) end
        end)
        io.writes:disarm()
        if not ok then error(err) end
    end

    local function restored_box(raw, mon)
        if rr then
            -- CFRU CompressedPokemon is a packed 58-byte projection of BoxPokemon.
            -- Keep the old client's proven wire shape; RR binary equivalence is RR-OPEN.
            local result = zero(stride)
            for i = 0, 0x1B do result[i + 1] = raw[i + 1] end
            for i = 0, 10 do result[0x1C + i + 1] = raw[0x20 + i + 1] end
            local packed = 0
            for i = 0, 3 do packed = packed | ((mon.moves[i + 1] & 0x3FF) << (10 * i)) end
            put(result, 0x27, 5, packed)
            for i = 0, 5 do result[0x2C + i + 1] = raw[0x38 + i + 1] end
            for i = 0, 7 do result[0x32 + i + 1] = raw[0x44 + i + 1] end
            return result
        end
        -- Unlike the old Lua helper's raw 80-byte copy (memory_gba.lua:1774-1807),
        -- the GAME calls BoxMonRestorePP before placing a mon in a PC box
        -- (pret pokemon_storage_system_data.c:625-633; pokemon.c:5998-6010).
        local result = copy(raw, 0, BOX_SIZE)
        local move_base = assert(profile.rom and profile.rom.BATTLE_MOVES_ADDR,
                                 "profile.rom.BATTLE_MOVES_ADDR required")
        local move_stride = assert(d.BATTLE_MOVE_ENTRY_SIZE,
                                   "profile.derived.BATTLE_MOVE_ENTRY_SIZE required")
        local pp_offset = assert(d.BATTLE_MOVE_PP_OFFSET,
                                 "profile.derived.BATTLE_MOVE_PP_OFFSET required")
        local mask_addr = assert(profile.rom.PP_UP_GET_MASK_ADDR,
                                 "profile.rom.PP_UP_GET_MASK_ADDR required")
        local key = mon.personality ~ mon.ot_id
        local plain = {}
        for off = 0, 44, 4 do put(plain, off, 4, word(result, 0x20 + off, 4) ~ key) end
        local attack = ATTACKS_POSITION[mon.personality % 24] * 12
        for i = 0, 3 do
            local move = mon.moves[i + 1]
            if move and move ~= 0 then
                local raw_pp = io.rom_read(move_base - 0x08000000
                                           + move * move_stride + pp_offset, 1)
                local base_pp = raw_pp and raw_pp[1]
                assert(type(base_pp) == "number" and base_pp > 0,
                       "move PP unreadable in ROM")
                local mask_bytes = io.rom_read(mask_addr - 0x08000000 + i, 1)
                local mask = mask_bytes and mask_bytes[1]
                assert(type(mask) == "number" and mask ~= 0, "PP-Up mask unreadable in ROM")
                local ups = (mon.pp_bonuses & mask) >> (2 * i)
                plain[attack + 8 + i + 1] = base_pp + math.floor(base_pp * 20 * ups / 100)
            end
        end
        local checksum = 0
        for off = 0, 46, 2 do checksum = checksum + word(plain, off, 2) end
        put(result, 0x1C, 2, checksum & 0xFFFF)
        for off = 0, 44, 4 do put(result, 0x20 + off, 4, word(plain, off, 4) ~ key) end
        return result
    end

    expanded_box = function(raw)
        if not rr then return copy(raw, 0, BOX_SIZE) end
        local result = zero(BOX_SIZE)
        for i = 0, 0x1B do result[i + 1] = raw[i + 1] end
        for i = 0, 10 do result[0x20 + i + 1] = raw[0x1C + i + 1] end
        local packed = word(raw, 0x27, 5)
        for i = 0, 3 do put(result, 0x2C + i * 2, 2, (packed >> (10 * i)) & 0x3FF) end
        for i = 0, 5 do result[0x38 + i + 1] = raw[0x2C + i + 1] end
        for i = 0, 7 do result[0x44 + i + 1] = raw[0x32 + i + 1] end
        return result
    end

    local function rom_bytes(address, length)
        assert(type(address) == "number" and address >= 0x08000000,
               "ROM profile address required")
        local bytes = io.rom_read(address - 0x08000000, length)
        assert(bytes and #bytes == length, "ROM record unreadable")
        return bytes
    end

    local function species_base(mon)
        local rom = assert(profile.rom, "ROM profile required")
        local base_addr
        if rr then
            local pointer = assert(rom.CFRU_BASESTATS_PTR,
                                   "profile.rom.CFRU_BASESTATS_PTR required")
            base_addr = word(rom_bytes(pointer, 4), 0, 4)
        else
            local code_bytes = io.rom_read(0xAC, 4) -- GBA header title code
            local code = string.char(code_bytes[1], code_bytes[2], code_bytes[3], code_bytes[4])
            local bases = d.BASESTATS_ADDR_BY_GAME_CODE
            base_addr = bases and bases[code] or rom.BASESTATS_ADDR
        end
        assert(base_addr, "base stats table missing for title")
        local entry_size = assert(d.BASESTATS_ENTRY_SIZE, "base stats stride required")
        local base = rom_bytes(base_addr + mon.species * entry_size, entry_size)
        assert(mon.species > 0 and base[1] > 0 and base[2] > 0,
               "species base stats unreadable")
        local growth = base[assert(d.BASESTATS_GROWTH_RATE_OFFSET,
                                   "profile.derived.BASESTATS_GROWTH_RATE_OFFSET required") + 1]
        assert(growth and growth < 6, "invalid growth rate")
        return base, growth
    end

    local function level_from_exp(mon, growth)
        local level = 1
        local exp_table = assert(profile.rom.EXPERIENCE_TABLES_ADDR,
                                 "profile.rom.EXPERIENCE_TABLES_ADDR required")
        local count = assert(d.EXPERIENCE_TABLE_ENTRY_COUNT, "experience row size required")
        local maximum = assert(d.MAX_LEVEL, "maximum level required")
        assert(maximum >= 1 and maximum < count, "invalid experience dimensions")
        for candidate = 2, maximum do
            local threshold = word(rom_bytes(exp_table + (growth * count + candidate) * 4, 4), 0, 4)
            if threshold > mon.experience then break end
            level = candidate
        end
        return level
    end

    local function vanilla_tail(mon)
        local base, growth = species_base(mon)
        local level = level_from_exp(mon, growth)
        local hp
        if mon.species == assert(d.SHEDINJA_SPECIES_ID,
                                 "profile.derived.SHEDINJA_SPECIES_ID required") then
            hp = 1
        else
            hp = math.floor(((2 * base[1] + mon.ivs.hp + math.floor(mon.evs.hp / 4))
                             * level) / 100) + level + 10
        end
        local nature = mon.personality % 25
        local up, down = math.floor(nature / 5), nature % 5
        local fields = {
            {"attack", 2}, {"defense", 3}, {"speed", 4},
            {"sp_attack", 5}, {"sp_defense", 6},
        }
        local stats = {}
        for index, field in ipairs(fields) do
            local name, base_index = field[1], field[2]
            local value = math.floor(((2 * base[base_index] + mon.ivs[name]
                                       + math.floor(mon.evs[name] / 4)) * level) / 100) + 5
            if up ~= down then
                if up == index - 1 then value = math.floor(value * 110 / 100) end
                if down == index - 1 then value = math.floor(value * 90 / 100) end
            end
            stats[index] = value
        end
        return level, hp, stats
    end

    local function party_from_box(box_raw, stats)
        local record = expanded_box(box_raw)
        local mon, why = reads.decode_box_mon(record)
        if not mon then return nil, why end
        if not rr and mon.checksum_ok ~= true then return nil, "box checksum invalid" end
        local level, hp, computed
        if rr then
            local function valid(value, maximum)
                return type(value) == "number" and value % 1 == 0
                       and value > 0 and value <= maximum
            end
            if type(stats) ~= "table" or not valid(stats.level, assert(d.MAX_LEVEL, "maximum level required"))
               or not valid(stats.maxHP, 65535)
               or not valid(stats.attack, 65535) or not valid(stats.defense, 65535)
               or not valid(stats.speed, 65535) or not valid(stats.spAtk, 65535)
               or not valid(stats.spDef, 65535) then
                return nil, "missing stats"
            end
            level, hp = stats.level, stats.maxHP
            computed = {stats.attack, stats.defense, stats.speed, stats.spAtk, stats.spDef}
            for i = 0, 3 do
                if mon.moves[i + 1] ~= 0 then
                    local pp = stats["pp" .. (i + 1)]
                    if not (type(pp) == "number" and pp % 1 == 0 and pp >= 0 and pp <= 255) then
                        local ok, value = pcall(function()
                            local rom = assert(profile.rom)
                            local moves = assert(rom.BATTLE_MOVES_ADDR)
                            local stride = assert(d.BATTLE_MOVE_ENTRY_SIZE)
                            local off = assert(d.BATTLE_MOVE_PP_OFFSET)
                            local base_pp = rom_bytes(moves + mon.moves[i + 1] * stride + off, 1)[1]
                            local mask = rom_bytes(assert(rom.PP_UP_GET_MASK_ADDR) + i, 1)[1]
                            assert(type(base_pp) == "number" and base_pp > 0 and base_pp <= 255)
                            assert(mask == (3 << (2 * i)), "invalid PP-Up mask")
                            local ups = (mon.pp_bonuses & mask) >> (2 * i)
                            local maximum = base_pp + math.floor(base_pp * 20 * ups / 100)
                            assert(maximum <= 255, "invalid move PP")
                            return maximum
                        end)
                        if not ok then return nil, "PP unavailable" end
                        pp = value
                    end
                    record[0x34 + i + 1] = pp
                end
            end
        else
            level, hp, computed = vanilla_tail(mon)
        end
        for i = BOX_SIZE + 1, PARTY_SIZE do record[i] = 0 end
        put(record, 0x50, 4, 0) -- BoxMonToMon clears status
        put(record, 0x54, 1, level)
        put(record, 0x55, 1, 0xFF) -- MAIL_NONE
        put(record, 0x56, 2, hp)
        put(record, 0x58, 2, hp)
        for i = 1, 5 do put(record, 0x58 + i * 2, 2, computed[i]) end
        return record
    end

    local function party_match(key, slot_hint)
        local party, why = reads.read_party()
        if not party then return nil, nil, why end
        local found
        for _, mon in ipairs(party) do
            if not rr and mon.checksum_ok ~= true then
                return nil, nil, "party checksum invalid"
            end
            if mon.has_species == 1 and reads.key(mon) == key then
                if found then return nil, nil, "ambiguous duplicate key" end
                found = mon
            end
        end
        -- Hints can go stale after party compaction. The key remains authoritative.
        local _ = slot_hint
        return party, found
    end

    function self:deposit(key, slot_hint)
        if native and native.deposit then return native.deposit(key, slot_hint) end
        local party, mon, why = party_match(key, slot_hint)
        if not party then return nil, why end
        local place
        place, why = layout()
        if not place then return nil, why end
        local entries, free, scan_why = boxes_state(place)
        if not entries then return nil, scan_why end
        local boxed
        boxed, why = matches(entries, key)
        if why then return nil, why end
        if not mon then
            if boxed then return true end
            return nil, "key not in party"
        end
        if boxed then return nil, "ambiguous key exists in both party and box" end
        if #party <= 1 then return nil, "last party mon" end
        if not free then return nil, "current box full" end
        local source = io.read_bytes(place.party + mon.slot * PARTY_SIZE, PARTY_SIZE)
        local box_raw = restored_box(source, mon)
        local plan = {{free.addr, box_raw}}
        for slot = mon.slot, #party - 2 do
            plan[#plan + 1] = {place.party + slot * PARTY_SIZE,
                               io.read_bytes(place.party + (slot + 1) * PARTY_SIZE, PARTY_SIZE)}
        end
        plan[#plan + 1] = {place.party + (#party - 1) * PARTY_SIZE, zero(PARTY_SIZE)}
        plan[#plan + 1] = {a.PARTY_COUNT_ADDR, {#party - 1}}
        write_plan(place, plan)
        return true
    end

    function self:withdraw(key, stats, nickname)
        if native and native.withdraw then return native.withdraw(key, stats, nickname) end
        local _ = nickname -- BoxMonToMon preserves the stored nickname.
        local party, mon, why = party_match(key)
        if not party then return nil, why end
        local place
        place, why = layout()
        if not place then return nil, why end
        local entries, _, scan_why = boxes_state(place)
        if not entries then return nil, scan_why end
        local boxed
        boxed, why = matches(entries, key)
        if why then return nil, why end
        if mon then
            if boxed then return nil, "ambiguous key exists in both party and box" end
            return true
        end
        if #party >= reads.party_capacity then return nil, "party full" end
        if not boxed then return nil, "key not boxed" end
        local record
        record, why = party_from_box(boxed.raw, stats)
        if not record then return nil, why end
        write_plan(place, {
            {place.party + #party * PARTY_SIZE, record},
            {boxed.addr, zero(stride)},
            {a.PARTY_COUNT_ADDR, {#party + 1}},
        })
        return true
    end
    function self:memorialize(key, slot_hint)
        if native and native.memorialize then return native.memorialize(key, slot_hint) end
        local party, mon, why = party_match(key, slot_hint)
        if not party then return nil, why end
        local place
        place, why = layout()
        if not place then return nil, why end
        local entries, _, scan_why = boxes_state(place)
        if not entries then return nil, scan_why end
        local boxed
        boxed, why = matches(entries, key)
        if why then return nil, why end
        if boxed and boxed.box == self.memorial_box then
            if mon then return nil, "ambiguous key exists in both party and memorial" end
            return true
        end
        if mon and boxed then return nil, "ambiguous key exists in both party and box" end
        if not mon and not boxed then return nil, "key not in party" end
        if mon and #party <= 1 then return nil, "last party mon" end
        local destination
        for slot = 0, mons_per_box - 1 do
            local addr = place.box_addr(self.memorial_box, slot)
            local raw = io.read_bytes(addr, stride)
            local candidate, candidate_why = reads.decode_box_mon(expanded_box(raw))
            if not candidate then return nil, candidate_why end
            if candidate.species == 0 then
                destination = addr
                break
            end
        end
        if not destination then return nil, "memorial box full" end
        local source, source_mon
        if mon then
            source = io.read_bytes(place.party + mon.slot * PARTY_SIZE, PARTY_SIZE)
            source_mon = mon
        else
            source = boxed.raw
            source_mon, why = reads.decode_box_mon(expanded_box(source))
            if not source_mon then return nil, why end
        end
        -- A boxed RR mon is already in the 58-byte format. Recompressing those
        -- bytes as if they were a party record would corrupt Growth/Misc fields.
        local target = (rr and boxed and not mon) and copy(source, 0, stride)
                       or restored_box(source, source_mon)
        local plan = {{destination, target}}
        if mon then
            for slot = mon.slot, #party - 2 do
                plan[#plan + 1] = {place.party + slot * PARTY_SIZE,
                                   io.read_bytes(place.party + (slot + 1) * PARTY_SIZE, PARTY_SIZE)}
            end
            plan[#plan + 1] = {place.party + (#party - 1) * PARTY_SIZE, zero(PARTY_SIZE)}
            plan[#plan + 1] = {a.PARTY_COUNT_ADDR, {#party - 1}}
        else
            plan[#plan + 1] = {boxed.addr, zero(stride)}
        end
        write_plan(place, plan)
        return true
    end
    function self:scan()
        local place, why = layout()
        if not place then return nil, why end
        local entries, _, scan_why = boxes_state(place)
        if not entries then return nil, scan_why end
        local out = {}
        for _, entry in ipairs(entries) do
            local mon
            mon, why = reads.decode_box_mon(expanded_box(entry.raw))
            if not mon then return nil, why end
            local _, growth = species_base(mon)
            out[#out + 1] = {
                box = entry.box, slot = entry.slot, key = entry.key,
                species_id = mon.species, nickname = mon.nickname,
                level = level_from_exp(mon, growth), moves = mon.moves,
            }
        end
        return out
    end
    return self
end

return B
