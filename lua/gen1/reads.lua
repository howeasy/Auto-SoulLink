-- Pure Gen 1 reads over a pret-generated title profile and injected byte reader.
-- No BizHawk globals. Struct offsets: pokered/constants/pokemon_data_constants.asm:26-56;
-- pokered/macros/ram.asm:7-36. Yellow has the same record layout.
local R = {NULL = {__gen1_null = true}} -- explicit None for absent box-only stats

-- The three runs below are pokered/constants/charmap.asm:92-117,126-151,187-196.
-- EXTRA is generated from the remaining English charmap rows, not inferred from glyph art.
-- constants/charmap.asm:5-63,90-196; checked against pret and Python oracle.
local EXTRA = {
    [0x00] = "<NULL>", [0x49] = "<PAGE>", [0x4A] = "<PKMN>", [0x4B] = "<_CONT>", [0x4C] = "<SCROLL>",
    [0x4E] = "<NEXT>", [0x4F] = "<LINE>", [0x51] = "<PARA>", [0x52] = "<PLAYER>", [0x53] = "<RIVAL>",
    [0x54] = "#", [0x55] = "<CONT>", [0x56] = "<……>", [0x57] = "<DONE>", [0x58] = "<PROMPT>",
    [0x59] = "<TARGET>", [0x5A] = "<USER>", [0x5B] = "<PC>", [0x5C] = "<TM>", [0x5D] = "<TRAINER>",
    [0x5E] = "<ROCKET>", [0x5F] = "<DEXEND>", [0x60] = "<BOLD_A>", [0x61] = "<BOLD_B>", [0x62] = "<BOLD_C>",
    [0x63] = "<BOLD_D>", [0x64] = "<BOLD_E>", [0x65] = "<BOLD_F>", [0x66] = "<BOLD_G>", [0x67] = "<BOLD_H>",
    [0x68] = "<BOLD_I>", [0x69] = "<BOLD_V>", [0x6A] = "<BOLD_S>", [0x6B] = "<BOLD_L>", [0x6C] = "<BOLD_M>",
    [0x6D] = "<COLON>", [0x6E] = "ぃ", [0x6F] = "ぅ", [0x70] = "‘", [0x71] = "’",
    [0x72] = "“", [0x73] = "”", [0x74] = "·", [0x75] = "…", [0x76] = "ぁ",
    [0x77] = "ぇ", [0x78] = "ぉ", [0x79] = "┌", [0x7A] = "─", [0x7B] = "┐",
    [0x7C] = "│", [0x7D] = "└", [0x7E] = "┘", [0x7F] = " ", [0x9A] = "(",
    [0x9B] = ")", [0x9C] = ":", [0x9D] = ";", [0x9E] = "[", [0x9F] = "]",
    [0xBA] = "é", [0xBB] = "'d", [0xBC] = "'l", [0xBD] = "'s", [0xBE] = "'t",
    [0xBF] = "'v", [0xE0] = "'", [0xE1] = "<PK>", [0xE2] = "<MN>", [0xE3] = "-",
    [0xE4] = "'r", [0xE5] = "'m", [0xE6] = "?", [0xE7] = "!", [0xE8] = ".",
    [0xE9] = "ァ", [0xEA] = "ゥ", [0xEB] = "ェ", [0xEC] = "▷", [0xED] = "▶",
    [0xEE] = "▼", [0xEF] = "♂", [0xF0] = "¥", [0xF1] = "×", [0xF2] = "<DOT>",
    [0xF3] = "/", [0xF4] = ",", [0xF5] = "♀",
}

local function glyph(b)
    if b >= 0x80 and b <= 0x99 then return string.char(string.byte("A") + b - 0x80) end
    if b >= 0xA0 and b <= 0xB9 then return string.char(string.byte("a") + b - 0xA0) end
    if b >= 0xF6 and b <= 0xFF then return string.char(string.byte("0") + b - 0xF6) end
    return EXTRA[b] or string.format("<$%02X>", b)
end

-- The ONE glyph table per foundation: {terminator, glyphs[0..255], codes[glyph] = byte}.
-- A pack that ships charmap.lua (gen1_purergb) supplies `profile.charmap` = its return value;
-- vanilla has no generated file yet, so its table is built once from EXTRA/glyph above.
-- reads.decode_name, boxes.encode_nickname, panel tiles and the trade name encoder all
-- consume this object, never a second transcription. `codes` keeps the FIRST byte of a glyph.
function R.charmap(profile)
    local cm = profile and profile.charmap
    if not cm then
        if not R.VANILLA then
            local glyphs = {}
            for b = 0, 255 do glyphs[b] = glyph(b) end
            R.VANILLA = { terminator = 0x50, glyphs = glyphs } -- constants/charmap.asm:12, @
        end
        cm = R.VANILLA
    end
    assert(type(cm.glyphs) == "table" and type(cm.terminator) == "number", "charmap needs glyphs + terminator")
    if not cm.codes then
        local codes = {}
        for b = 0, 255 do
            local g = cm.glyphs[b]
            if g and codes[g] == nil then codes[g] = b end
        end
        cm.codes = codes
    end
    return cm
end

local function word(b, i) return b[i] * 256 + b[i + 1] end
local function take(b, start, length)
    local out = {}
    for i = 1, length do out[i] = b[start + i - 1] end
    return out
end
-- home/move_mon.asm:109-153: A/D/S/S nibbles, HP DV from their low bits. Shared by
-- decode_party_mon (party/box records) and read_enemy_battle_mon (the live struct).
local function dvs_from_raw(raw)
    local atk, def = math.floor(raw / 4096) % 16, math.floor(raw / 256) % 16
    local spd, spc = math.floor(raw / 16) % 16, raw % 16
    return {raw = raw, atk = atk, def = def, spd = spd, spc = spc,
            hp = (atk % 2) * 8 + (def % 2) * 4 + (spd % 2) * 2 + spc % 2}
end

function R.new(profile, io, Scanner)
    assert(type(profile) == "table" and type(profile.ram) == "table" and
           type(profile.derived) == "table", "Gen 1 title profile required")
    assert(type(io) == "table" and type(io.read_u8) == "function" and
           type(io.read_range) == "function", "injected WRAM byte reader required")
    assert(type(Scanner) == "table" and type(Scanner.new) == "function",
        "injected token Scanner required")
    local a, d = profile.ram, profile.derived
    local cm = R.charmap(profile)
    local r = {NULL = R.NULL, charmap = cm}
    local bag_capacity = assert(d.bag_capacity, "profile.derived.bag_capacity required")
    local opp_id_offset = assert(d.opp_id_offset, "profile.derived.opp_id_offset required")
    r.bag_capacity, r.opp_id_offset = bag_capacity, opp_id_offset

    r.decode_name = Scanner.new({glyphs = cm.glyphs, terminator = cm.terminator,
        max_length = d.name_length,
        unknown = function(byte) return string.format("<$%02X>", byte) end})

    function r.decode_party_mon(b, box)
        local size = box and d.box_struct_size or d.party_struct_size
        if #b ~= size then return nil, "record length disagrees with profile" end
        -- All word/three-byte fields are most-significant-byte first:
        -- home/move_mon.asm:39-43; engine/pokemon/experience.asm:11-24.
        local dvs = dvs_from_raw(word(b, 28)) -- pokemon_data_constants.asm:45
        local mon = {
            box = not not box, species = b[1], hp = word(b, 2), box_level = b[4],
            level = box and b[4] or b[34], status = b[5], types = take(b, 6, 2),
            catch_rate = b[8], moves = take(b, 9, 4), ot_id = word(b, 13),
            exp = b[15] * 65536 + b[16] * 256 + b[17],
            stat_exp = {hp = word(b, 18), atk = word(b, 20), def = word(b, 22),
                        spd = word(b, 24), spc = word(b, 26)}, dvs = dvs,
            pp = {}, pp_ups = {},
            max_hp = box and R.NULL or word(b, 35),
            atk = box and R.NULL or word(b, 37), def = box and R.NULL or word(b, 39),
            spd = box and R.NULL or word(b, 41), spc = box and R.NULL or word(b, 43),
        }
        -- PP high two bits are PP Up count; low six are remaining PP:
        -- constants/pokemon_data_constants.asm:100-102.
        for i = 1, 4 do
            mon.pp[i], mon.pp_ups[i] = b[29 + i] % 64, math.floor(b[29 + i] / 64)
        end
        return mon
    end

    local function collection(count, species, structs, ots, nicks, capacity, stride, box)
        if count > capacity then return nil, "count exceeds profile capacity" end
        if species[count + 1] ~= 0xFF then return nil, "missing species terminator" end
        local result = {}
        for slot = 0, count - 1 do
            local listed = species[slot + 1]
            if listed == 0 or listed == 0xFF then return nil, "invalid species in list" end
            local mon, why = r.decode_party_mon(take(structs, slot * stride + 1, stride), box)
            if not mon then return nil, why end
            if listed ~= mon.species then return nil, "species list and struct disagree" end
            mon.slot, mon.species_list_entry = slot, listed
            mon.ot_name_bytes = take(ots, slot * d.name_length + 1, d.name_length)
            mon.nickname_bytes = take(nicks, slot * d.name_length + 1, d.name_length)
            mon.ot_name, why = r.decode_name(mon.ot_name_bytes)
            if mon.ot_name == nil then return nil, "invalid OT name: " .. why end
            mon.nickname, why = r.decode_name(mon.nickname_bytes)
            if mon.nickname == nil then return nil, "invalid nickname: " .. why end
            result[#result + 1] = mon
        end
        return result
    end

    local function wram_collection(prefix, capacity, stride, box)
        -- ram/wram.asm:1722-1744,2226-2248; Yellow:1903-1925,2491-2513.
        -- Every base is a profile symbol, including the separate OT/nickname blocks.
        local count = io.read_u8(a["w" .. prefix .. "Count"])
        if count > capacity then return nil, "count exceeds profile capacity" end
        return collection(count,
            io.read_range(a["w" .. prefix .. "Species"], capacity + 1),
            io.read_range(a["w" .. prefix .. "Mons"], capacity * stride),
            io.read_range(a["w" .. prefix .. "MonOT"], capacity * d.name_length),
            io.read_range(a["w" .. prefix .. "MonNicks"], capacity * d.name_length),
            capacity, stride, box)
    end

    function r.read_party()
        return wram_collection("Party", d.party_capacity, d.party_struct_size, false)
    end
    function r.read_active_box()
        return wram_collection("Box", d.box_capacity, d.box_struct_size, true)
    end

    function r.read_current_box_num()
        -- ram/wram.asm:1897-1899; constants/ram_constants.asm:50-52:
        -- low seven bits are a zero-based box; high bit says boxes were initialized.
        local raw = io.read_u8(a.wCurrentBoxNum)
        local index = raw % 128
        if index >= d.sram_boxes_per_bank * #d.sram_box_banks then
            return nil, "current box number outside profile"
        end
        return {raw = raw, index = index, initialized = raw >= 128}
    end

    function r.read_sram_box(sram_bytes, box_index)
        -- layout.link:195-202; ram/sram.asm:29-49. The image contains bank 0
        -- through the last profile box bank; derive bank size from the image.
        local per_bank, banks = d.sram_boxes_per_bank, d.sram_box_banks
        if type(box_index) ~= "number" or box_index ~= math.floor(box_index) or
           box_index < 0 or box_index >= per_bank * #banks then
            return nil, "box index outside profile"
        end
        local bank_slot = math.floor(box_index / per_bank) + 1
        local bank = banks[bank_slot]
        local bank_size = #sram_bytes / (banks[#banks] + 1)
        if bank_size ~= math.floor(bank_size) or bank_size < per_bank * d.sram_box_stride then
            return nil, "SRAM image geometry disagrees with profile"
        end
        local within_bank = box_index % per_bank
        local base = bank_slot == 1 and a.sBox1 or a.sBox7
        -- The generated profile need only name anchor boxes. ram/sram.asm:29-49
        -- declares each bank as six consecutive wBoxData-sized records.
        local offset = bank * bank_size + base - a.sBox1 + within_bank * d.sram_box_stride
        if offset < 0 or offset + d.sram_box_stride > #sram_bytes then
            return nil, "SRAM box outside image"
        end
        return r.box_from_snapshot(take(sram_bytes, offset + 1, d.sram_box_stride))
    end

    -- One contiguous box image -> the same decoded list read_active_box returns: count,
    -- species list (+ $FF), structs, OT names, nicknames. ram/sram.asm:29-49 lays a saved box
    -- out that way and the WRAM mirror (ram/wram.asm:2226-2248) is the identical run, so a
    -- byte snapshot taken at an engine site decodes here without a second live read.
    function r.box_from_snapshot(raw)
        if type(raw[1]) ~= "number" then return nil, "box snapshot is empty" end
        local species_start, mon_start = 2, 2 + d.box_capacity + 1
        local ot_start = mon_start + d.box_capacity * d.box_struct_size
        local nick_start = ot_start + d.box_capacity * d.name_length
        return collection(raw[1], take(raw, species_start, d.box_capacity + 1),
            take(raw, mon_start, d.box_capacity * d.box_struct_size),
            take(raw, ot_start, d.box_capacity * d.name_length),
            take(raw, nick_start, d.box_capacity * d.name_length),
            d.box_capacity, d.box_struct_size, true)
    end

    function r.key(mon)
        -- docs/protocol.md:143-150: DDDD:OOOO:SS, internal species byte.
        return string.format("%04X:%04X:%02X", mon.dvs.raw, mon.ot_id, mon.species)
    end

    function r.read_bag()
        -- ram/wram.asm:1757-1761; constants/menu_constants.asm:1; and
        -- engine/items/get_bag_item_quantity.asm:5-17 ($FF terminates IDs).
        local count = io.read_u8(a.wNumBagItems)
        local capacity = bag_capacity
        if count > capacity then return nil, "bag count exceeds storage" end
        local raw = io.read_range(a.wBagItems, capacity * 2 + 1)
        if raw[count * 2 + 1] ~= 0xFF then return nil, "missing bag terminator" end
        local items = {}
        for i = 0, count - 1 do
            if raw[i * 2 + 1] == 0 or raw[i * 2 + 1] == 0xFF then
                return nil, "invalid bag item ID"
            end
            items[#items + 1] = {id = raw[i * 2 + 1], qty = raw[i * 2 + 2]}
        end
        return {items = items}
    end
    function r.has_item(id)
        local bag, why = r.read_bag()
        if not bag then return nil, why end
        for _, item in ipairs(bag.items) do
            if item.id == id and item.qty > 0 then return true end
        end
        return false
    end
    function r.read_badges() return io.read_u8(a.wObtainedBadges) end -- ram/wram.asm:1767
    function r.read_player_id()
        -- ram/wram.asm:1773; engine/pokemon/add_mon.asm:195-200 copies the
        -- first ID byte then second into MON_OTID: big-endian display order.
        local b = io.read_range(a.wPlayerID, 2)
        return word(b, 1)
    end
    function r.read_player_name()
        return r.decode_name(io.read_range(a.wPlayerName, d.name_length)) -- ram/wram.asm:1715
    end
    function r.read_money()
        -- ram/wram.asm:1761: three BCD bytes, high decimal digit first;
        -- engine/events/black_out.asm:20-37 handles the same byte order.
        local b = io.read_range(a.wPlayerMoney, 3)
        local total = 0
        for i = 1, 3 do
            local hi, lo = math.floor(b[i] / 16), b[i] % 16
            if hi > 9 or lo > 9 then return nil, "invalid money BCD" end
            total = total * 100 + hi * 10 + lo
        end
        return total
    end
    function r.read_map()
        -- ram/wram.asm:1782-1789 (X follows Y in memory; use symbols).
        return {map = io.read_u8(a.wCurMap), x = io.read_u8(a.wXCoord),
                y = io.read_u8(a.wYCoord)}
    end
    function r.read_battle()
        -- ram/wram.asm:1236-1252, battle structs in macros/ram.asm:39-59;
        -- constants/trainer_constants.asm:1: trainer class = opponent - OPP_ID_OFFSET
        -- (200 vanilla, 197 pureRGB: profile.derived.opp_id_offset). With the vanilla value
        -- this reads exactly as before: is_trainer = opponent >= 200 and
        -- trainer_class = opponent >= 200 and opponent - 200 or NULL.
        local opponent = io.read_u8(a.wCurOpponent)
        local enemy_hp = io.read_range(a.wEnemyMonHP, 2)
        local enemy_max_hp = io.read_range(a.wEnemyMonMaxHP, 2) -- battle_struct MaxHP, big-endian
        local player_hp = io.read_range(a.wBattleMonHP, 2)
        return {in_battle = io.read_u8(a.wIsInBattle), type = io.read_u8(a.wBattleType),
                cur_opponent = opponent, is_trainer = opponent >= opp_id_offset,
                trainer_class = opponent >= opp_id_offset and opponent - opp_id_offset or R.NULL,
                enemy_species = io.read_u8(a.wEnemyMonSpecies),
                enemy_level = io.read_u8(a.wEnemyMonLevel), enemy_hp = word(enemy_hp, 1),
                enemy_max_hp = word(enemy_max_hp, 1),
                battle_mon_hp = word(player_hp, 1),
                player_mon_number = io.read_u8(a.wPlayerMonNumber),
                result = io.read_u8(a.wBattleResult), link_state = io.read_u8(a.wLinkState),
                -- pureRGB-only symbols (PLAN §3.5 SAFARI_TYPE_CLASSIC; RUN witness bit 1): absent
                -- from the vanilla profile, so absent from the vanilla table too
                safari_type = a.wSafariType and io.read_u8(a.wSafariType) or nil,
                functional_flags = a.wBattleFunctionalFlags and io.read_u8(a.wBattleFunctionalFlags) or nil}
    end
    -- The active wEnemyMon battle struct: 29 bytes, big-endian words, identical geometry in
    -- pureRGB (macros/ram.asm:39-59; profile.ram.wEnemyMon == wEnemyMonSpecies, its first
    -- byte). No profile aliases exist for DVs/MaxHP/PP -- only fixed offsets from wEnemyMon,
    -- unlike decode_party_mon's named struct. party_pos is wEnemyMonPartyPos (offset +3):
    -- valid only once EnemySendOutFirstMon has settled it (see client.lua's RIVAL_* comment);
    -- callers must range-check it before indexing wEnemyMons with it.
    function r.read_enemy_battle_mon()
        local b = io.read_range(a.wEnemyMon, 29)
        local pp = {}
        for i = 1, 4 do pp[i] = b[25 + i] % 64 end -- pokemon_data_constants.asm:100-102
        return {species = b[1], party_pos = b[4], status = b[5],
                moves = take(b, 9, 4), dvs = dvs_from_raw(word(b, 13)), level = b[15],
                max_hp = word(b, 16), pp = pp}
    end
    -- Daycare: one full party-mon record at wDayCareMon (PLAN §4 row 24 / A7); nil when the
    -- profile has no symbol. The struct is the party shape, so decode_party_mon is the decoder.
    function r.read_daycare_mon()
        if not a.wDayCareMon then return nil, "profile has no wDayCareMon" end
        if a.wDayCareInUse and io.read_u8(a.wDayCareInUse) == 0 then return nil, "daycare empty" end
        local mon, why = r.decode_party_mon(io.read_range(a.wDayCareMon, d.party_struct_size), false)
        if not mon then return nil, why end
        if mon.species == 0 or mon.species == 0xFF then return nil, "daycare empty" end
        return mon
    end
    -- pureRGB stamps its save with wGameInternalVersion; the updater saves before stamping, so a
    -- mismatch against derived.game_internal_version means "not live yet". nil = no such symbol.
    function r.read_game_internal_version()
        if not a.wGameInternalVersion then return nil end
        return io.read_u8(a.wGameInternalVersion)
    end
    function r.read_stat_stages(side)
        -- ram/wram.asm:543-576 has SIX named modifiers and two unused bytes.
        -- Stored raw range 1..13; 7 means neutral (not a seventh modifier).
        local stem = side == "player" and "wPlayerMon" or side == "enemy" and "wEnemyMon"
        if not stem then return nil, "side must be player or enemy" end
        local out = {}
        for _, name in ipairs({"Attack", "Defense", "Speed", "Special", "Accuracy", "Evasion"}) do
            out[string.lower(name)] = io.read_u8(a[stem .. name .. "Mod"])
        end
        return out
    end
    function r.read_save_file_status() return io.read_u8(a.wSaveFileStatus) end -- wram.asm:1382
    function r.read_options() return io.read_u8(a.wOptions) end -- wram.asm:1765
    function r.read_status_flags4() return io.read_u8(a.wStatusFlags4) end -- wram.asm:2112
    return r
end

return R
