-- Gen 1 PC moves. All writes go through the caller's armed write_bytes and
-- write_cart_bytes gates; this module never calls BizHawk or MBC registers.
-- Source: pret pokered 405b624, pokeyellow 0a08515. The R/B/Y layout facts
-- below are shared; every WRAM/SRAM symbol comes from profile.ram.
local B = {}
local BANK_SIZE = 0x2000 -- layout.link:195-202, SRAM bank window $a000-$bfff
local SRAM_ADDR = 0xA000 -- constants/hardware.inc:811-813; layout.link:195-202
local GROWTH = { -- data/growth_rates.asm:15-20; pokemon_data_constants.asm:85-94
    {1, 1, 0, 0, 0}, {3, 4, 10, 0, 30}, {3, 4, 20, 0, 70},
    {6, 5, -15, 100, 140}, {4, 5, 0, 0, 0}, {5, 4, 0, 0, 0},
}

local function copy(src)
    local out = {}
    for i = 1, #src do out[i] = src[i] end
    return out
end
local function part(src, first, n)
    local out = {}
    for i = 1, n do out[i] = src[first + i - 1] end
    return out
end
local function replace(dst, first, src)
    for i = 1, #src do dst[first + i - 1] = src[i] end
end
local function checksum(bytes, first, n)
    -- engine/menus/save.asm:297-310: one's complement of byte sum.
    local sum = 0
    for i = first, first + n - 1 do sum = (sum + bytes[i]) % 256 end
    return 255 - sum
end
local function put_word(dst, first, value)
    dst[first], dst[first + 1] = math.floor(value / 256) % 256, value % 256
end
local function byte(v)
    return type(v) == "number" and v == math.floor(v) and v >= 0 and v <= 255
end
local function valid_bytes(bytes, n)
    if type(bytes) ~= "table" or #bytes ~= n then return false end
    for i = 1, n do if not byte(bytes[i]) then return false end end
    return true
end

function B.new(profile, reads, io)
    assert(type(profile) == "table" and profile.ram and profile.derived, "title profile required")
    assert(type(reads) == "table" and reads.decode_party_mon and reads.key and
           reads.read_current_box_num and reads.decode_name, "Gen 1 reads instance required")
    assert(type(io) == "table" and type(io.read_range) == "function" and
           type(io.read_cart) == "function" and type(io.write_bytes) == "function" and
           type(io.write_cart_bytes) == "function", "injected armed byte IO required")
    local ram, d = profile.ram, profile.derived
    local perbank, banks = d.sram_boxes_per_bank, d.sram_box_banks
    local box_count = perbank * #banks
    local self = {}

    local function layout(prefix, capacity, stride)
        -- ram/wram.asm:1722-1744,2226-2248; macros/ram.asm:7-36.
        local stem = "w" .. prefix
        local base = ram[stem .. "Count"]
        local species = ram[stem .. "Species"] - base + 1
        local mons = ram[stem .. "Mons"] - base + 1
        local ot = ram[stem .. "MonOT"] - base + 1
        local nick = ram[stem .. "MonNicks"] - base + 1
        return {base = base, capacity = capacity, stride = stride, species = species,
                mons = mons, ot = ot, nick = nick, size = nick - 1 + capacity * d.name_length}
    end
    local party = layout("Party", d.party_capacity, d.party_struct_size)
    local box = layout("Box", d.box_capacity, d.box_struct_size)
    assert(box.size == d.sram_box_stride, "profile box geometry disagrees")

    local function read_wram(lay)
        local raw = io.read_range(lay.base, lay.size)
        if not valid_bytes(raw, lay.size) then return nil, "invalid WRAM byte range" end
        return raw
    end
    local function entries(raw, lay, boxed)
        local count = raw[1]
        if not byte(count) or count > lay.capacity then return nil, "invalid collection count" end
        if raw[lay.species + count] ~= 0xFF then return nil, "missing species terminator" end
        local out = {}
        for slot = 0, count - 1 do
            local species = raw[lay.species + slot]
            if species == 0 or species == 0xFF then return nil, "invalid internal species" end
            local blob = part(raw, lay.mons + slot * lay.stride, lay.stride)
            local mon, why = reads.decode_party_mon(blob, boxed)
            if not mon then return nil, why end
            if mon.species ~= species then return nil, "species list/struct mismatch" end
            out[#out + 1] = {species = species, blob = blob,
                ot = part(raw, lay.ot + slot * d.name_length, d.name_length),
                nick = part(raw, lay.nick + slot * d.name_length, d.name_length),
                mon = mon, key = reads.key(mon)}
        end
        return out
    end
    local function compose(raw, lay, list)
        -- _MoveMon/RemovePokemon shift all active species, structs and both names:
        -- engine/pokemon/add_mon.asm:365-413,433-489; remove_mon.asm:8-107.
        if #list > lay.capacity then return nil, "collection full" end
        local out = copy(raw)
        out[1] = #list
        for i, entry in ipairs(list) do
            if not byte(entry.species) or entry.species == 0 or entry.species == 0xFF or
               not valid_bytes(entry.blob, lay.stride) or entry.blob[1] ~= entry.species or
               not valid_bytes(entry.ot, d.name_length) or
               not valid_bytes(entry.nick, d.name_length) then
                return nil, "invalid collection entry"
            end
            out[lay.species + i - 1] = entry.species
            replace(out, lay.mons + (i - 1) * lay.stride, entry.blob)
            replace(out, lay.ot + (i - 1) * d.name_length, entry.ot)
            replace(out, lay.nick + (i - 1) * d.name_length, entry.nick)
        end
        out[lay.species + #list] = 0xFF
        return out
    end
    local function without(list, slot)
        local out = {}
        for i, entry in ipairs(list) do if i ~= slot then out[#out + 1] = entry end end
        return out
    end
    local function find(list, key)
        local hit
        for i, entry in ipairs(list) do
            if entry.key == key then
                if hit then return nil, "ambiguous duplicate key" end
                hit = i
            end
        end
        return hit
    end
    local function same_transfer(party_entry, box_entry)
        -- _MoveMon copies first 33 bytes (add_mon.asm:409-427), but BoxLevel
        -- may be replaced on deposit and the party's real level rebuilt on
        -- withdraw. Ignore byte 4 only; OT and all other bytes must match.
        if not party_entry or not box_entry or party_entry.species ~= box_entry.species then
            return false
        end
        for i = 1, d.box_struct_size do
            if i ~= 4 and party_entry.blob[i] ~= box_entry.blob[i] then return false end
        end
        for i = 1, d.name_length do
            if party_entry.ot[i] ~= box_entry.ot[i] then return false end
        end
        return true
    end

    local function bank_info(bank_slot)
        local bank = banks[bank_slot]
        local anchor = bank_slot == 1 and "sBox1" or "sBox7"
        local allsym = "sBank" .. bank .. "AllBoxesChecksum"
        local indsym = "sBank" .. bank .. "IndividualBoxChecksums"
        local base = bank * BANK_SIZE + ram[anchor] - SRAM_ADDR
        return {base = base, all = ram[allsym] - ram[anchor] + 1,
                individual = ram[indsym] - ram[anchor] + 1,
                size = ram[indsym] - ram[anchor] + perbank}
    end
    local function read_bank(bank_slot)
        local info = bank_info(bank_slot)
        local out = {}
        for i = 1, info.size do out[i] = io.read_cart(info.base + i - 1) end
        if not valid_bytes(out, info.size) then return nil, "invalid CartRAM byte range" end
        return out, info
    end
    local function seal_bank(raw, info)
        -- save.asm:312-327,427-431,561-565: all six full 1122-byte boxes,
        -- then whole-bank complement over six contiguous boxes.
        for slot = 0, perbank - 1 do
            raw[info.individual + slot] = checksum(raw, slot * d.sram_box_stride + 1,
                                                   d.sram_box_stride)
        end
        raw[info.all] = checksum(raw, 1, info.all - 1)
    end

    local function saved_main_with_initialized_flag()
        -- save.asm:208-240 copies wMainDataStart..End into sMainData separately from
        -- wPlayerName, then CalcCheckSum covers sGameData..sGameDataEnd. ram/sram.asm:16-24.
        -- The saved byte is sMainData+(wCurrentBoxNum-wMainDataStart), NOT an offset from
        -- wPlayerName (pokered.sym:19158,19259,17399; gen1_codec.py:74-77).
        local function flat(symbol)
            return profile.sram_bank[symbol] * BANK_SIZE + ram[symbol] - SRAM_ADDR
        end
        local first, last = flat("sGameData"), flat("sGameDataEnd")
        local saved = flat("sMainData") + ram.wCurrentBoxNum - ram.wMainDataStart
        assert(first <= saved and saved < last and last == flat("sMainDataCheckSum"),
               "saved current-box byte outside main checksum domain")
        local raw = {}
        for offset = first, last do raw[#raw + 1] = io.read_cart(offset) end
        if not valid_bytes(raw, last - first + 1) then return nil, "invalid saved main-data range" end
        local index = saved - first + 1
        raw[index] = raw[index] % 128 + 128 -- preserve the SAVED box index, set only bit 7
        raw[#raw] = checksum(raw, 1, #raw - 1) -- save.asm:297-310, game's complement sum
        -- only the two bytes that changed are written (review: a ~4 KiB byte-by-byte image
        -- with its checksum last is a tear window that would reject the whole save on boot)
        return {flag = {offset = saved, value = raw[index]}, sum = {offset = last, value = raw[#raw]}}
    end
    local function valid_bank(raw, info)
        if raw[info.all] ~= checksum(raw, 1, info.all - 1) then return false end
        for slot = 0, perbank - 1 do
            if raw[info.individual + slot] ~= checksum(raw, slot * d.sram_box_stride + 1,
                                                         d.sram_box_stride) then return false end
        end
        return true
    end
    local function target(index, current)
        if index == current.index then
            local raw, why = read_wram(box)
            if not raw then return nil, why end
            local list
            list, why = entries(raw, box, true)
            if not list then return nil, why end
            return {raw = raw, list = list, current = true}
        end
        if not current.initialized then return nil, "saved boxes not initialized" end
        local bank_slot = math.floor(index / perbank) + 1
        local bank, info = read_bank(bank_slot)
        if not bank then return nil, info end
        if not valid_bank(bank, info) then return nil, "saved-box checksums invalid" end
        local slot = index % perbank
        local raw = part(bank, slot * d.sram_box_stride + 1, d.sram_box_stride)
        local list, why = entries(raw, box, true)
        if not list then return nil, why end
        return {raw = raw, list = list, current = false, bank = bank,
                bank_info = info, bank_slot = slot}
    end
    local function write_target(t, newraw)
        if t.current then
            -- save.asm:246-260 copies WRAM wBoxData to sCurBoxData on SAVE.
            io.write_bytes(box.base, newraw)
        else
            replace(t.bank, t.bank_slot * d.sram_box_stride + 1, newraw)
            seal_bank(t.bank, t.bank_info)
            io.write_cart_bytes(t.bank_info.base, t.bank)
        end
    end
    local function current_box()
        return reads.read_current_box_num() -- ram/wram.asm:1897-1899; ram_constants.asm:50-52
    end

    function self.ensure_boxes_initialised()
        local current, why = current_box()
        if not current then return nil, why end
        if current.initialized then return true end
        -- First ChangeBox does this before swapping: save.asm:365-387,529-572.
        -- EmptySRAMBox changes ONLY count and first species byte, preserving all
        -- unused tail bytes. Then each bank gets six individual and one whole
        -- checksum. Set bit 7 afterwards so ChangeBox cannot wipe these banks.
        local changes = {}
        for bank_slot = 1, #banks do
            local raw, info = read_bank(bank_slot)
            if not raw then return nil, info end
            for slot = 0, perbank - 1 do
                local first = slot * d.sram_box_stride + 1
                raw[first], raw[first + 1] = 0, 0xFF
            end
            seal_bank(raw, info)
            changes[#changes + 1] = {base = info.base, raw = raw}
        end
        local durable, error_text = saved_main_with_initialized_flag()
        if not durable then return nil, error_text end
        for _, change in ipairs(changes) do io.write_cart_bytes(change.base, change.raw) end
        io.write_cart_bytes(durable.sum.offset, {durable.sum.value})
        io.write_cart_bytes(durable.flag.offset, {durable.flag.value})
        io.write_bytes(ram.wCurrentBoxNum, {current.raw + 128})
        return true
    end

    -- `slot_hint` (0-based party slot, optional): a caller that has already located the record
    -- (client.lua find_party_slot's validated retirement locator) names it, so a duplicate of
    -- the same key elsewhere in the party is not an ambiguity; the record at the hint must
    -- still carry `key` or the hint is ignored.
    local function party_source(key, slot_hint)
        local raw, why = read_wram(party)
        if not raw then return nil, why end
        local list
        list, why = entries(raw, party, false)
        if not list then return nil, why end
        local slot
        if slot_hint and list[slot_hint + 1] and list[slot_hint + 1].key == key then
            slot = slot_hint + 1
        else
            slot, why = find(list, key)
            if why then return nil, why end
        end
        return {raw = raw, list = list, slot = slot}
    end
    local function all_box_matches(key, current)
        local found
        for index = 0, box_count - 1 do
            if index == current.index or current.initialized then
                local t, why = target(index, current)
                if not t then return nil, why end
                local slot
                slot, why = find(t.list, key)
                if why then return nil, why end
                if slot then
                    if found then return nil, "ambiguous duplicate boxed key" end
                    found = {index = index, slot = slot, target = t}
                end
            end
        end
        return found
    end

    function self.box_mon(key, slot_hint)
        local current, why = current_box()
        if not current then return nil, why end
        local source
        source, why = party_source(key, slot_hint)
        if not source then return nil, why end
        local existing
        existing, why = all_box_matches(key, current)
        if why then return nil, why end
        if existing then
            if source.slot then
                if existing.index ~= current.index or
                   not same_transfer(source.list[source.slot],
                                     existing.target.list[existing.slot]) then
                    return nil, "ambiguous key exists in both party and box"
                end
                local newparty
                newparty, why = compose(source.raw, party, without(source.list, source.slot))
                if not newparty then return nil, why end
                io.write_bytes(party.base, newparty) -- finish interrupted deposit
            end
            return true -- idempotent after a completed deposit
        end
        if not source.slot then return nil, "key not in party" end
        if #source.list <= 1 then return nil, "last party mon" end
        local t
        t, why = target(current.index, current)
        if not t then return nil, why end
        if #t.list >= box.capacity then return nil, "current box full" end
        local original = source.list[source.slot]
        local blob = part(original.blob, 1, d.box_struct_size)
        -- add_mon.asm:409-427: box copies first 33 bytes; deposit replaces
        -- BoxLevel byte (+3) with the party Level byte (+33).
        blob[4] = original.blob[d.box_struct_size + 1]
        local added = {species = original.species, blob = blob,
                       ot = original.ot, nick = original.nick}
        local boxes = copy(t.list)
        boxes[#boxes + 1] = added
        local newbox, newparty
        newbox, why = compose(t.raw, box, boxes)
        if not newbox then return nil, why end
        newparty, why = compose(source.raw, party, without(source.list, source.slot))
        if not newparty then return nil, why end
        write_target(t, newbox) -- target first: no loss if interrupted between writes
        io.write_bytes(party.base, newparty)
        return true
    end

    local function exp_level(growth, exp)
        -- engine/pokemon/experience.asm:6-27,39-136; growth_rates.asm:15-20.
        local row = GROWTH[growth + 1]
        if not row then return nil, "missing or invalid growth rate" end
        for level = 2, 255 do
            local needed = (math.floor(row[1] * level ^ 3 / row[2]) +
                            row[3] * level ^ 2 + row[4] * level - row[5]) % 16777216
            if needed > exp then return level - 1 end
        end
        return nil, "experience level would wrap"
    end
    local function calc_stat(base, dv, stat_exp, level, hp)
        -- home/move_mon.asm:73-92,109-226: ceil sqrt capped at 255,
        -- floor /4, floor after level /100, HP +level+10, other +5, max999.
        local root = math.min(255, math.ceil(math.sqrt(stat_exp)))
        local value = math.floor(((base + dv) * 2 + math.floor(root / 4)) * level / 100)
        return math.min(999, value + (hp and level + 10 or 5))
    end
    local function rebuild(entry, base)
        if type(base) ~= "table" or not byte(base.growth_rate) or
           not byte(base.hp) or not byte(base.attack) or not byte(base.defense) or
           not byte(base.speed) or not byte(base.special) then
            return nil, "verified base stats and growth rate required"
        end
        local mon = entry.mon
        local level, why = exp_level(base.growth_rate, mon.exp)
        if not level then return nil, why end
        local blob = part(entry.blob, 1, d.box_struct_size)
        local stat_names = {{"hp", "hp"}, {"attack", "atk"}, {"defense", "def"},
                            {"speed", "spd"}, {"special", "spc"}}
        blob[d.box_struct_size + 1] = level
        for i, pair in ipairs(stat_names) do
            local name, dv_name = pair[1], pair[2]
            local value = calc_stat(base[name], mon.dvs[dv_name], mon.stat_exp[dv_name],
                                    level, i == 1)
            put_word(blob, d.box_struct_size + 2 + (i - 1) * 2, value)
        end
        return blob
    end
    local function encode_nickname(name)
        -- Reverse reads.decode_name, whose English glyphs come from
        -- constants/charmap.asm:5-196; no lossy ASCII fallback.
        if type(name) ~= "string" then return nil, "nickname must be a string" end
        -- Literal glyph tiles only ($7F-$BF, $E0-$EB, $EF-$FF, as the trade receptionist's
        -- SlinkTradeUIValidName checks): pureRGB's charmap also names text-compression codes
        -- ("an" = $34, "the", "ing", ...), and a greedy match wrote "Rockman" as ...m + $34.
        local tokens, values = {}, {}
        for b = 0x7F, 255 do
            local glyph = (b < 0xC0 or (b >= 0xE0 and b < 0xEC) or b >= 0xEF) and reads.decode_name({b})
            if glyph and glyph ~= "" and not values[glyph] then tokens[#tokens + 1], values[glyph] = glyph, b end
        end
        table.sort(tokens, function(a, b) return #a > #b end)
        local out = {}
        while #name > 0 and name:sub(1, 1) ~= "@" do
            local found
            for _, token in ipairs(tokens) do
                if name:sub(1, #token) == token then found = token; break end
            end
            if not found then return nil, "nickname has unsupported glyph" end
            out[#out + 1] = values[found]
            name = name:sub(#found + 1)
        end
        if #out >= d.name_length then return nil, "nickname too long" end
        while #out < d.name_length do out[#out + 1] = 0x50 end -- charmap.asm:12
        return out
    end

    -- Durability (mirror of lua/gen2/boxes.lua ops.withdraw/ops.settle, OMP BOX review F1): a
    -- non-current saved box is bank SRAM, durable at once, while the party is WRAM until the next
    -- native SAVE. Removing the box copy before that save loses the mon on a reset (the saved party
    -- lacks it, the bank lost it). With opts.defer_backing the party copy is written now and the box
    -- copy stays (a duplicate, never a loss); after the save witness the caller re-runs party_mon(key),
    -- whose interrupted-withdraw replay below drops the box copy on a full-record match (the settle).
    -- The current box lives in WRAM (reverts with the party), so it needs no deferral.
    function self.party_mon(key, base_stats, nickname, stats, opts)
        -- stats is the server's optional cache, retained for command-shape
        -- compatibility; rebuilt values from verified base stats are authoritative.
        local _ = stats
        local current, why = current_box()
        if not current then return nil, why end
        local source
        source, why = party_source(key)
        if not source then return nil, why end
        if source.slot then
            local duplicate
            duplicate, why = all_box_matches(key, current)
            if why then return nil, why end
            if duplicate then
                local t = duplicate.target
                if not same_transfer(source.list[source.slot], t.list[duplicate.slot]) then
                    return nil, "ambiguous key exists in both party and box"
                end
                local newbox
                newbox, why = compose(t.raw, box, without(t.list, duplicate.slot))
                if not newbox then return nil, why end
                write_target(t, newbox) -- finish interrupted withdraw
            end
            return true -- idempotent after completed withdraw
        end
        if #source.list >= party.capacity then return nil, "party full" end
        local hit
        hit, why = all_box_matches(key, current)
        if why then return nil, why end
        if not hit then return nil, "key not boxed" end
        local t, original = hit.target, hit.target.list[hit.slot]
        local blob
        blob, why = rebuild(original, base_stats)
        if not blob then return nil, why end
        local nick = original.nick
        if nickname ~= nil then
            nick, why = encode_nickname(nickname)
            if not nick then return nil, why end
        end
        local added = {species = original.species, blob = blob, ot = original.ot, nick = nick}
        local partylist = copy(source.list)
        partylist[#partylist + 1] = added
        local newparty, newbox
        newparty, why = compose(source.raw, party, partylist)
        if not newparty then return nil, why end
        newbox, why = compose(t.raw, box, without(t.list, hit.slot))
        if not newbox then return nil, why end
        io.write_bytes(party.base, newparty) -- party first: no loss if interrupted
        if not t.current and type(opts) == "table" and opts.defer_backing == true then
            return true, "backing removal deferred to the save witness"
        end
        write_target(t, newbox)
        return true
    end

    function self.memorialize(key, colon_key, slot_hint)
        -- Accept both boxes.memorialize(key[, hint]) and client boxes:memorialize(key[, hint]).
        if type(key) == "table" then key = colon_key else slot_hint = colon_key end
        local current, why = current_box()
        if not current then return nil, why end
        local source
        source, why = party_source(key, slot_hint)
        if not source then return nil, why end
        local memorial = box_count - 1 -- sBox12: ram/sram.asm:44-49
        if not source.slot then
            local t
            t, why = target(memorial, current)
            if not t then return nil, why end
            local slot
            slot, why = find(t.list, key)
            if why then return nil, why end
            if slot then return true end -- idempotent after completed move
            return nil, "key not in party"
        end
        if #source.list <= 1 then return nil, "last party mon" end
        if memorial ~= current.index and not current.initialized then
            local ok
            ok, why = self.ensure_boxes_initialised()
            if not ok then return nil, why end
            current, why = current_box()
            if not current then return nil, why end
        end
        local t
        t, why = target(memorial, current)
        if not t then return nil, why end
        local duplicate
        duplicate, why = find(t.list, key)
        if why then return nil, why end
        if duplicate then
            if not same_transfer(source.list[source.slot], t.list[duplicate]) then
                return nil, "ambiguous key exists in both party and memorial"
            end
            local newparty
            newparty, why = compose(source.raw, party, without(source.list, source.slot))
            if not newparty then return nil, why end
            io.write_bytes(party.base, newparty) -- finish interrupted memorial
            return true
        end
        if #t.list >= box.capacity then return nil, "memorial box full" end
        local original = source.list[source.slot]
        local blob = part(original.blob, 1, d.box_struct_size)
        blob[4] = original.blob[d.box_struct_size + 1] -- add_mon.asm:421-427
        local boxes = copy(t.list)
        boxes[#boxes + 1] = {species = original.species, blob = blob,
                             ot = original.ot, nick = original.nick}
        local newbox, newparty
        newbox, why = compose(t.raw, box, boxes)
        if not newbox then return nil, why end
        newparty, why = compose(source.raw, party, without(source.list, source.slot))
        if not newparty then return nil, why end
        -- an unsettled deferred withdraw left the durable box copy (mirror of gen2 ops.memorialize):
        -- it goes too, AFTER the memorial and the party, so a reset in between leaves a duplicate
        local copy
        copy, why = all_box_matches(key, current)
        if why then return nil, why end
        if copy and not same_transfer(original, copy.target.list[copy.slot]) then
            return nil, "ambiguous key exists in both party and box"
        end
        write_target(t, newbox)
        io.write_bytes(party.base, newparty)
        if copy then
            -- re-read: the memorial write rewrote (and re-sealed) a whole bank the copy may share
            local again, slot
            again, why = target(copy.index, current)
            if not again then return nil, why end
            slot, why = find(again.list, key)
            if not slot then return nil, why or "box copy vanished" end
            local rest
            rest, why = compose(again.raw, box, without(again.list, slot))
            if not rest then return nil, why end
            write_target(again, rest)
        end
        return true
    end

    -- Client-facing command aliases. The caller must select the *matching*
    -- species' base-stat record before withdraw; a national-dex keyed table
    -- cannot safely be indexed by this command's opaque identity key.
    function self:deposit(key, slot_hint) return self.box_mon(key, slot_hint) end
    function self:withdraw(key, stats, base_stats, nickname, opts)
        return self.party_mon(key, base_stats, nickname, stats, opts)
    end

    return self
end

return B
