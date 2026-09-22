-- Pure Gen 2 decoding. No emulator globals, bank switches, writes, or admission grants.
-- Pins: pokecrystal@7a7881d0d62e0ddbd82dcf10e7116807487ac651;
--       pokegold@656583c939d30f920a316177311a502dd222b57c (Gold and Silver).
-- Layout: C macros/ram.asm:7-44,102-123; G macros/ram.asm:7-42,99-124;
-- C constants/pokemon_data_constants.asm:75-115,135-142; G:75-109,115-122.
-- Party block: C ram/wram.asm:3413-3433; G:2756-2776.
-- Selected profile supplies every cartridge symbol and record offset.
-- IO: read_range(address,length,domain), bank_valid(bank,address,length),
--     domain_size("CartRAM"), cart_ram_linear=true. Bank validity must reflect
-- the actual mode/mapping; this module never treats DMG as an implied bank 1.
local R = {}
-- Both pinned repos: constants/battle_constants.asm:2 (MAX_LEVEL = 100).
-- CalcLevel, engine/pokemon/experience.asm:5-30, can return 1; MIN_LEVEL = 2
-- is not this record decoder's floor. This is a pinned Gen 2 fact, not a fallback.
local MAX_LEVEL = 100

local function integer(value, low, high)
    return type(value) == "number" and value == math.floor(value) and value >= low and value <= high
end

local function bytes_ok(bytes, length)
    if type(bytes) ~= "table" or #bytes ~= length then return false end
    for key, value in pairs(bytes) do
        if not integer(key, 1, length) or not integer(value, 0, 255) then return false end
    end
    for i = 1, length do if not integer(bytes[i], 0, 255) then return false end end
    return true
end

local function slice(bytes, offset, length)
    local result = {}
    for i = 1, length do result[i] = bytes[offset + i] end
    return result
end

local function hex(bytes)
    local result = {}
    for i = 1, #bytes do result[i] = string.format("%02x", bytes[i]) end
    return table.concat(result)
end

local function be16(bytes, offset) return bytes[offset + 1] * 256 + bytes[offset + 2] end

function R.new(profile, io, decode_name)
    if type(profile) ~= "table" or not ({crystal=true, gold=true, silver=true})[profile.title]
       or type(profile.ram) ~= "table" or type(profile.ram_bank) ~= "table"
       or type(profile.sram_bank) ~= "table" or type(profile.constants) ~= "table"
       or type(profile.derived) ~= "table" or type(profile.storage_boxes) ~= "table" then
        return nil, "selected generated Gen 2 profile required"
    end
    if type(io) ~= "table" or type(io.read_range) ~= "function" then
        return nil, "injected read_range required"
    end
    if decode_name ~= nil and type(decode_name) ~= "function" then
        return nil, "name decoder must be a function"
    end
    local c, d, a = profile.constants, profile.derived, profile.ram
    -- Refuse mismatched generated dimensions; these define this decoder version.
    local dimensions = {
        PARTYMON_STRUCT_LENGTH=48, BOXMON_STRUCT_LENGTH=32, NAME_LENGTH=11,
        MON_NAME_LENGTH=11, PARTY_LENGTH=6, MONS_PER_BOX=20, NUM_BOXES=14,
        NUM_MOVES=4, NUM_POKEMON=251, EGG=253, BOX_LENGTH=1104,
    }
    for name, value in pairs(dimensions) do
        if c[name] ~= value then return nil, "unsupported or missing profile constant " .. name end
    end
    for name, constant in pairs({party_struct_size="PARTYMON_STRUCT_LENGTH", box_struct_size="BOXMON_STRUCT_LENGTH",
        name_length="NAME_LENGTH", mon_name_length="MON_NAME_LENGTH", party_capacity="PARTY_LENGTH",
        box_capacity="MONS_PER_BOX", num_boxes="NUM_BOXES", sram_box_stride="BOX_LENGTH",
        species_count="NUM_POKEMON", egg_species="EGG"}) do
        if d[name] ~= c[constant] then return nil, "derived profile dimension disagrees: " .. name end
    end
    -- Verify an exact field partition, including the two auxiliary bytes that are
    -- caught data in Crystal and unused in Gold/Silver. They are not Gen 1 fields.
    local offset = 0
    for _, field in ipairs({{"MON_SPECIES",1},{"MON_ITEM",1},{"MON_MOVES",4},{"MON_OT_ID",2},
        {"MON_EXP",3},{"MON_HP_EXP",2},{"MON_ATK_EXP",2},{"MON_DEF_EXP",2},{"MON_SPD_EXP",2},
        {"MON_SPC_EXP",2},{"MON_DVS",2},{"MON_PP",4},{"MON_HAPPINESS",1},{"MON_POKERUS",3},
        {"MON_LEVEL",1},{"MON_STATUS",2},{"MON_HP",2},{"MON_MAXHP",2},{"MON_ATK",2},
        {"MON_DEF",2},{"MON_SPD",2},{"MON_SAT",2},{"MON_SDF",2}}) do
        if c[field[1]] ~= offset then return nil, "record offset disagrees: " .. field[1] end
        offset = offset + field[2]
    end
    local r = {title=profile.title, transfer_blob_size=c.PARTYMON_STRUCT_LENGTH+c.NAME_LENGTH+c.MON_NAME_LENGTH}

    local function names(mon, ot, nickname)
        for _, field in ipairs({{"ot",ot,c.NAME_LENGTH},{"nickname",nickname,c.MON_NAME_LENGTH}}) do
            if field[2] ~= nil then
                if not bytes_ok(field[2], field[3]) then return nil, "invalid " .. field[1] .. " name bytes" end
                mon[field[1] .. "_raw_hex"] = hex(field[2])
                if decode_name then
                    local ok, value = pcall(decode_name, slice(field[2], 0, field[3]))
                    if not ok or type(value) ~= "string" then return nil, "name decoder unavailable or failed" end
                    mon[field[1] == "ot" and "ot_name" or "nickname"] = value
                end
            end
        end
        return mon
    end

    function r.decode_record(bytes, kind, species_marker, ot, nickname)
        local size = kind == "party" and c.PARTYMON_STRUCT_LENGTH or kind == "box" and c.BOXMON_STRUCT_LENGTH
        if not size then return nil, "record kind must be party or box" end
        if not bytes_ok(bytes, size) then return nil, "invalid or incomplete record bytes" end
        local species = bytes[c.MON_SPECIES + 1]
        if not integer(species, 1, c.NUM_POKEMON) then return nil, "invalid record species" end
        if not integer(species_marker, 1, c.NUM_POKEMON) and species_marker ~= c.EGG then
            return nil, "species-list marker required"
        end
        if species_marker ~= c.EGG and species_marker ~= species then return nil, "species list/record mismatch" end
        local level = bytes[c.MON_LEVEL+1]
        if not integer(level,1,MAX_LEVEL) then return nil, "record level outside 1.." .. MAX_LEVEL end
        -- Egg creation stores the real species in the record and EGG in the list:
        -- C engine/pokemon/move_mon.asm:1174-1188; G has the corresponding AddEggMonToParty path.
        local dv = be16(bytes, c.MON_DVS)
        local attack, defense = math.floor(dv / 4096), math.floor(dv / 256) % 16
        local speed, special = math.floor(dv / 16) % 16, dv % 16
        -- HP DV: C engine/pokemon/move_mon.asm:1483-1506; G:1496-1519.
        local mon = {
            species_id=species, species_marker=species_marker, is_egg=species_marker == c.EGG,
            held_item=bytes[c.MON_ITEM+1], moves=slice(bytes,c.MON_MOVES,c.NUM_MOVES),
            ot_id=be16(bytes,c.MON_OT_ID), exp=bytes[c.MON_EXP+1]*65536+bytes[c.MON_EXP+2]*256+bytes[c.MON_EXP+3],
            stat_exp={hp=be16(bytes,c.MON_HP_EXP),attack=be16(bytes,c.MON_ATK_EXP),defense=be16(bytes,c.MON_DEF_EXP),
                      speed=be16(bytes,c.MON_SPD_EXP),special=be16(bytes,c.MON_SPC_EXP)},
            dv_word=dv, dvs={attack=attack,defense=defense,speed=speed,special=special,
                            hp=(attack%2)*8+(defense%2)*4+(speed%2)*2+special%2},
            pp={},pp_ups={},happiness=bytes[c.MON_HAPPINESS+1],pokerus=bytes[c.MON_POKERUS+1],
            aux_bytes_hex=hex(slice(bytes,c.MON_POKERUS+1,2)),level=level,raw_hex=hex(bytes),
        }
        -- PP partition: C constants/pokemon_data_constants.asm:238-240; G:216-218.
        for i = 1, c.NUM_MOVES do
            local packed = bytes[c.MON_PP+i]
            mon.pp[i], mon.pp_ups[i] = packed % 64, math.floor(packed / 64)
        end
        if kind == "party" then
            mon.status, mon.hp, mon.max_hp = bytes[c.MON_STATUS+1], be16(bytes,c.MON_HP), be16(bytes,c.MON_MAXHP)
            mon.stats = {attack=be16(bytes,c.MON_ATK),defense=be16(bytes,c.MON_DEF),speed=be16(bytes,c.MON_SPD),
                         special_attack=be16(bytes,c.MON_SAT),special_defense=be16(bytes,c.MON_SDF)}
        end
        return names(mon, ot, nickname)
    end

    function r.decode_transfer_blob(bytes, species_marker)
        if not bytes_ok(bytes,r.transfer_blob_size) then return nil, "transfer blob must contain 48+11+11 bytes" end
        -- SLink Gen 2 transfer shape, not a claim about the cartridge's serial protocol.
        return r.decode_record(slice(bytes,0,c.PARTYMON_STRUCT_LENGTH),"party",species_marker,
            slice(bytes,c.PARTYMON_STRUCT_LENGTH,c.NAME_LENGTH),
            slice(bytes,c.PARTYMON_STRUCT_LENGTH+c.NAME_LENGTH,c.MON_NAME_LENGTH))
    end

    local function collection(bytes, kind, capacity, padding)
        local stride = kind == "party" and c.PARTYMON_STRUCT_LENGTH or c.BOXMON_STRUCT_LENGTH
        local mons_start = 1 + capacity + 1
        local ot_start = mons_start + capacity * stride
        local nickname_start = ot_start + capacity * c.NAME_LENGTH
        local used = nickname_start + capacity * c.MON_NAME_LENGTH
        local length = used + padding
        if not bytes_ok(bytes,length) then return nil,"invalid or incomplete collection bytes" end
        local count = bytes[1]
        if count > capacity then return nil,"collection count exceeds capacity" end
        if bytes[2+count] ~= 255 then return nil,"missing species-list terminator" end
        local result = {count=count,mons={},raw_hex=hex(bytes),snapshot_qualified=false}
        for slot = 0, count-1 do
            local mon, why = r.decode_record(slice(bytes,mons_start+slot*stride,stride),kind,bytes[2+slot],
                slice(bytes,ot_start+slot*c.NAME_LENGTH,c.NAME_LENGTH),
                slice(bytes,nickname_start+slot*c.MON_NAME_LENGTH,c.MON_NAME_LENGTH))
            if not mon then return nil,"slot " .. slot .. ": " .. why end
            mon.slot = slot
            result.mons[#result.mons+1] = mon
        end
        if kind == "box" then result.copy_length = used end
        if padding > 0 then result.padding_hex = hex(slice(bytes,used,padding)) end
        return result
    end

    function r.decode_party_block(bytes) return collection(bytes,"party",c.PARTY_LENGTH,0) end
    function r.decode_box_block(bytes) return collection(bytes,"box",c.MONS_PER_BOX,2) end
    function r.decode_active_box_block(bytes) return collection(bytes,"box",c.MONS_PER_BOX,0) end

    local function read_range(address,length,domain)
        local ok, bytes = pcall(io.read_range,address,length,domain)
        if not ok or not bytes_ok(bytes,length) then return nil,"unavailable or malformed " .. domain .. " read" end
        return slice(bytes,0,length)
    end

    local function wram(name,length)
        local address, bank = a[name],profile.ram_bank[name]
        if not integer(address,0xC000,0xDFFF) or not integer(length,1,0x2000)
           or not integer(bank,0,7) then return nil,"missing/invalid WRAM symbol " .. name end
        if (address < 0xD000 and (bank ~= 0 or address+length > 0xD000))
           or (address >= 0xD000 and (bank == 0 or address+length > 0xE000)) then
            return nil,"WRAM range crosses its bank window"
        end
        if type(io.bank_valid) ~= "function" then return nil,"explicit WRAM bank validity required" end
        local ok, valid = pcall(io.bank_valid,bank,address,length)
        if not ok or valid ~= true then return nil,"WRAM bank unavailable or invalid" end
        local bytes, why = read_range(address,length,"System Bus")
        if not bytes then return nil,why end
        ok, valid = pcall(io.bank_valid,bank,address,length)
        if not ok or valid ~= true then return nil,"WRAM bank changed or became unavailable" end
        return bytes
    end

    local function cart_ram(bank,address,length)
        -- GB SRAM window geometry, as represented by RGBDS linkdefs.cpp and the
        -- generated bank/address pairs. Linear CartRAM binding is an explicit IO input.
        if not integer(bank,0,255) or not integer(address,0xA000,0xBFFF)
           or not integer(length,1,0x2000) or address+length > 0xC000 then return nil,"invalid SRAM window" end
        if io.cart_ram_linear ~= true or type(io.domain_size) ~= "function" then
            return nil,"qualified linear CartRAM binding required"
        end
        local ok, size = pcall(io.domain_size,"CartRAM")
        local flat = bank*0x2000 + address-0xA000
        if not ok or not integer(size,1,256*0x2000) or flat+length > size then return nil,"CartRAM range unavailable" end
        return read_range(flat,length,"CartRAM")
    end

    function r.read_party()
        local count = a.wPartyCount
        if not integer(count,0xC000,0xDFFF) then return nil,"missing party count address" end
        local positions = {wPartySpecies=count+1,wPartyMons=count+2+c.PARTY_LENGTH}
        positions.wPartyMonOTs = positions.wPartyMons+c.PARTY_LENGTH*c.PARTYMON_STRUCT_LENGTH
        positions.wPartyMonNicknames = positions.wPartyMonOTs+c.PARTY_LENGTH*c.NAME_LENGTH
        for name, address in pairs(positions) do
            if a[name] ~= address or profile.ram_bank[name] ~= profile.ram_bank.wPartyCount then
                return nil,"party block symbol geometry disagrees: " .. name
            end
        end
        local length = positions.wPartyMonNicknames+c.PARTY_LENGTH*c.MON_NAME_LENGTH-count
        local bytes,why = wram("wPartyCount",length)
        if not bytes then return nil,why end
        local result
        result,why = r.decode_party_block(bytes)
        if not result then return nil,why end
        result.ownership = "live_party_wram"
        return result
    end

    function r.read_current_box_num()
        local bytes,why = wram("wCurBox",1)
        if not bytes then return nil,why end
        -- GetBoxAddress treats the entire byte as the index; no Gen 1 high-bit mask.
        -- C engine/menus/save.asm:874-879; G has the same GetBoxAddress sequence.
        if bytes[1] >= c.NUM_BOXES then return nil,"current box index outside 0..13" end
        return bytes[1]
    end

    local function read_box(bank,address,index,ownership,length)
        local before,why = r.read_current_box_num()
        if before == nil then return nil,why end
        local bytes
        bytes,why = cart_ram(bank,address,length)
        if not bytes then return nil,why end
        local after
        after,why = r.read_current_box_num()
        if after == nil then return nil,why end
        if before ~= after then return nil,"current box changed during read" end
        local result
        if ownership == "active_sram_shadow" then result,why = r.decode_active_box_block(bytes)
        else result,why = r.decode_box_block(bytes) end
        if not result then return nil,why end
        result.ownership,result.bank,result.address = ownership,bank,address
        result.box_index = index == nil and before or index
        result.is_current = result.box_index == before
        -- SaveBox copies 1102 bytes from bank-1 sBox to a backing box; LoadBox does
        -- the reverse. Neither the two padding bytes nor a read is a durability receipt.
        -- C engine/menus/save.asm:900-1034; C layout.link:368-378; G layout.link:294-303.
        result.active_shadow_authoritative = result.is_current
        result.durable_save_verified = false
        return result
    end

    function r.read_active_box()
        local bank,address = profile.sram_bank.sBox,a.sBox
        if bank ~= 1 or not integer(address,0xA000,0xBFFF) then return nil,"missing/invalid active sBox binding" end
        local positions = {sBoxCount=0,sBoxSpecies=1,sBoxMons=2+c.MONS_PER_BOX,
            sBoxMonOTs=2+c.MONS_PER_BOX+c.MONS_PER_BOX*c.BOXMON_STRUCT_LENGTH,
            sBoxMonNicknames=2+c.MONS_PER_BOX+c.MONS_PER_BOX*(c.BOXMON_STRUCT_LENGTH+c.NAME_LENGTH),
            sBoxEnd=c.BOX_LENGTH-2}
        for name,offset_value in pairs(positions) do
            if a[name] ~= address+offset_value or profile.sram_bank[name] ~= bank then
                return nil,"active box symbol geometry disagrees: " .. name
            end
        end
        -- Gold/Silver's active curbox has no padding: ram/sram.asm:109 and
        -- macros/ram.asm:99-124. Never read the next section as its padding.
        return read_box(bank,address,nil,"active_sram_shadow",a.sBoxEnd-address)
    end

    function r.read_storage_box(index)
        if not integer(index,0,c.NUM_BOXES-1) then return nil,"storage box index outside 0..13" end
        if #profile.storage_boxes ~= c.NUM_BOXES then return nil,"all 14 storage bindings required" end
        local box = profile.storage_boxes[index+1]
        local expected_bank = index < c.NUM_BOXES/2 and 2 or 3
        local symbol = "sBox" .. (index+1)
        if type(box) ~= "table" or box.number ~= index+1 or box.bank ~= expected_bank
           or box.length ~= c.BOX_LENGTH or box.addr ~= a[symbol] or profile.sram_bank[symbol] ~= box.bank then
            return nil,"storage box binding disagrees with profile symbols"
        end
        return read_box(box.bank,box.addr,index,"backing_sram_box",c.BOX_LENGTH)
    end

    local function raw_observation(result)
        result.evidence, result.snapshot_qualified = "RAW_RAM_ONLY", false
        return result
    end

    local function geometry(base_symbol, fields)
        local base, bank = a[base_symbol], profile.ram_bank[base_symbol]
        if not integer(base,0xC000,0xDFFF) or not integer(bank,0,7) then
            return nil,"missing/invalid WRAM symbol " .. base_symbol
        end
        for name,offset_value in pairs(fields) do
            if a[name] ~= base+offset_value or profile.ram_bank[name] ~= bank then
                return nil,"symbol geometry disagrees: " .. name
            end
        end
        return true
    end

    function r.read_player()
        -- C ram/wram.asm:2994-2996; G:2399-2401. Trainer Card prints the ID
        -- as a two-byte number (C trainer_card.asm:241-243; G:239-241).
        -- PrintNum's .word loads the first byte as high: C engine/math/print_num.asm:48-53;
        -- G home/print_num.asm:48-53. NAME_LENGTH is the allocation, not the input-screen limit.
        local valid,why = geometry("wPlayerID",{wPlayerName=2})
        if not valid then return nil,why end
        local bytes
        bytes,why = wram("wPlayerID",2+c.NAME_LENGTH)
        if not bytes then return nil,why end
        local result
        result,why = names({ot_id=be16(bytes,0),identity_qualified=false},slice(bytes,2,c.NAME_LENGTH))
        if not result then return nil,why end
        result.name_raw_hex,result.player_name = result.ot_raw_hex,result.ot_name
        result.ot_raw_hex,result.ot_name = nil,nil
        result.raw_hex = hex(bytes)
        return raw_observation(result)
    end

    function r.read_map()
        -- C ram/wram.asm:3400-3403; G:2744-2747. The source stores Y before X.
        local valid,why = geometry("wMapGroup",{wMapNumber=1,wYCoord=2,wXCoord=3})
        if not valid then return nil,why end
        local bytes
        bytes,why = wram("wMapGroup",4)
        if not bytes then return nil,why end
        return raw_observation({group=bytes[1],number=bytes[2],y=bytes[3],x=bytes[4],raw_hex=hex(bytes)})
    end

    local pockets = {
        items={count="wNumItems",data="wItems",constant="MAX_ITEMS",derived="bag_capacity",capacity=20,width=2},
        balls={count="wNumBalls",data="wBalls",constant="MAX_BALLS",derived="ball_capacity",capacity=12,width=2},
        key_items={count="wNumKeyItems",data="wKeyItems",constant="MAX_KEY_ITEMS",derived="key_item_capacity",capacity=25,width=1},
    }
    function r.read_pocket(pocket)
        -- C ram/wram.asm:3109-3118; G:2507-2516. Ordinary/ball pockets contain
        -- (id,quantity) entries; key items contain IDs only; each count-based list
        -- has an FF terminator. Both engine/items/items.asm:158-232,316-330,404-415
        -- preserve separate stacks and limit quantities to MAX_ITEM_STACK.
        if c.MAX_ITEM_STACK ~= 99 then return nil,"unsupported/missing MAX_ITEM_STACK" end
        if pocket == "tmhm" then
            if c.NUM_TM_HM ~= 57 then return nil,"unsupported/missing NUM_TM_HM" end
            local valid,why = geometry("wTMsHMs",{wNumItems=c.NUM_TM_HM})
            if not valid then return nil,why end
            local bytes
            bytes,why = wram("wTMsHMs",c.NUM_TM_HM)
            if not bytes then return nil,why end
            for _,quantity in ipairs(bytes) do
                if quantity > c.MAX_ITEM_STACK then return nil,"TM/HM quantity exceeds source bound" end
            end
            -- Indices are TM/HM ordinals, not item IDs; no guessed item-id arithmetic.
            return raw_observation({quantities=bytes,raw_hex=hex(bytes)})
        end
        local p = pockets[pocket]
        if not p then return nil,"unknown bag pocket" end
        if c[p.constant] ~= p.capacity or d[p.derived] ~= p.capacity then
            return nil,"unsupported/missing pocket capacity " .. p.constant
        end
        local fields = {}; fields[p.data] = 1
        local valid,why = geometry(p.count,fields)
        if not valid then return nil,why end
        local bytes
        bytes,why = wram(p.count,2+p.capacity*p.width)
        if not bytes then return nil,why end
        local count = bytes[1]
        if count > p.capacity then return nil,"pocket count exceeds capacity" end
        if bytes[2+count*p.width] ~= 255 then return nil,"missing pocket terminator" end
        local result = {count=count,entries={},raw_hex=hex(bytes)}
        for slot = 0,count-1 do
            local offset = 2+slot*p.width
            local id = bytes[offset]
            if not integer(id,1,254) then return nil,"invalid occupied pocket item id" end
            local entry = {slot=slot,id=id}
            if p.width == 2 then
                local quantity = bytes[offset+1]
                if not integer(quantity,1,c.MAX_ITEM_STACK) then return nil,"invalid occupied pocket quantity" end
                entry.quantity = quantity
            end
            result.entries[#result.entries+1] = entry
        end
        return raw_observation(result)
    end

    function r.read_bag()
        local result = {}
        for _,pocket in ipairs({"items","balls","key_items","tmhm"}) do
            local value,why = r.read_pocket(pocket)
            if not value then return nil,pocket .. ": " .. why end
            result[pocket] = value
        end
        return raw_observation(result)
    end

    function r.read_badges()
        -- C ram/wram.asm:3106-3107 and constants/ram_constants.asm:261-284;
        -- G ram/wram.asm:2504-2505 and constants/ram_constants.asm:250-273.
        if c.NUM_JOHTO_BADGES ~= 8 or c.NUM_KANTO_BADGES ~= 8 then
            return nil,"unsupported/missing badge-count facts"
        end
        local valid,why = geometry("wJohtoBadges",{wKantoBadges=1})
        if not valid then return nil,why end
        local bytes
        bytes,why = wram("wJohtoBadges",2)
        if not bytes then return nil,why end
        return raw_observation({johto=bytes[1],kanto=bytes[2],raw_hex=hex(bytes)})
    end

    local function byte_symbol(name)
        local bytes,why = wram(name,1)
        if not bytes then return nil,why end
        return bytes[1]
    end

    local function masked(value,mask)
        local result,place = 0,1
        for _ = 1,8 do
            if value%2 == 1 and mask%2 == 1 then result = result+place end
            value,mask,place = math.floor(value/2),math.floor(mask/2),place*2
        end
        return result
    end

    function r.read_battle()
        -- C ram/wram.asm:2720-2739; G:2186-2207. These bytes describe raw
        -- context, not a qualified running battle. In particular LOSE is transient.
        local flags = profile.title == "crystal" and 192 or 128
        if c.WILD_BATTLE ~= 1 or c.TRAINER_BATTLE ~= 2 or c.BATTLERESULT_BITMASK ~= flags then
            return nil,"unsupported/missing battle-context facts"
        end
        local mode,why = byte_symbol("wBattleMode")
        if mode == nil then return nil,why end
        if mode ~= 0 and mode ~= c.WILD_BATTLE and mode ~= c.TRAINER_BATTLE then
            return nil,"battle mode outside source enumeration"
        end
        local battle_type,result
        battle_type,why = byte_symbol("wBattleType")
        if battle_type == nil then return nil,why end
        result,why = byte_symbol("wBattleResult")
        if result == nil then return nil,why end
        -- BATTLERESULT_BITMASK contains flags to REMOVE, not result-code bits:
        -- C constants/battle_constants.asm:261-269; G:259-266.
        local observed = {mode=mode,battle_type=battle_type,result_raw=result,
            result_code=masked(result,255-c.BATTLERESULT_BITMASK),battle_qualified=false}
        if mode ~= 0 then
            observed.active_slot,why = byte_symbol("wCurBattleMon")
            if observed.active_slot == nil then return nil,why end
            if observed.active_slot >= c.PARTY_LENGTH then return nil,"active battle slot outside party capacity" end
            if mode == c.TRAINER_BATTLE then
                local class,id
                class,why = byte_symbol("wOtherTrainerClass")
                if class == nil then return nil,why end
                id,why = byte_symbol("wOtherTrainerID")
                if id == nil then return nil,why end
                observed.trainer = {class_raw=class,id_raw=id}
            end
        end
        local after
        after,why = byte_symbol("wBattleMode")
        if after == nil then return nil,why end
        if after ~= mode then return nil,"battle mode changed during read" end
        return raw_observation(observed)
    end

    function r.read_battle_mon(side)
        local prefix = side == "player" and "wBattleMon" or side == "enemy" and "wEnemyMon"
        if not prefix then return nil,"battle side must be player or enemy" end
        -- battle_struct is 32 bytes but is NOT box_struct. C macros/ram.asm:79-100;
        -- G:76-97. Offsets come from the selected generated member symbols.
        local fields,offset = {},0
        for _,field in ipairs({{"Species",1},{"Item",1},{"Moves",c.NUM_MOVES},{"DVs",2},
            {"PP",c.NUM_MOVES},{"Happiness",1},{"Level",1},{"Status",2},{"HP",2},{"MaxHP",2},
            {"Attack",2},{"Defense",2},{"Speed",2},{"SpclAtk",2},{"SpclDef",2},{"Type1",1},{"Type2",1}}) do
            fields[prefix .. field[1]] = offset
            offset = offset+field[2]
        end
        fields[prefix .. "StructEnd"] = offset
        local valid,why = geometry(prefix,fields)
        if not valid then return nil,why end
        local bytes
        bytes,why = wram(prefix,offset)
        if not bytes then return nil,why end
        local function at(field) return a[prefix .. field]-a[prefix] end
        local function value(field) return bytes[at(field)+1] end
        local function word(field) return be16(bytes,at(field)) end
        if not integer(value("Species"),1,c.NUM_POKEMON) then return nil,"invalid battle-view species" end
        if not integer(value("Level"),1,MAX_LEVEL) then return nil,"battle-view level outside source bounds" end
        local dv = word("DVs")
        local attack,defense,speed,special = math.floor(dv/4096),math.floor(dv/256)%16,math.floor(dv/16)%16,dv%16
        local mon = {species_id=value("Species"),held_item=value("Item"),
            moves=slice(bytes,at("Moves"),c.NUM_MOVES),pp_raw=slice(bytes,at("PP"),c.NUM_MOVES),
            pp={},pp_ups={},dv_word=dv,dvs={attack=attack,defense=defense,speed=speed,special=special,
                hp=(attack%2)*8+(defense%2)*4+(speed%2)*2+special%2},
            happiness=value("Happiness"),level=value("Level"),status=value("Status"),
            status_aux_raw=bytes[at("Status")+2],hp=word("HP"),max_hp=word("MaxHP"),
            stats={attack=word("Attack"),defense=word("Defense"),speed=word("Speed"),
                   special_attack=word("SpclAtk"),special_defense=word("SpclDef")},
            types_raw={value("Type1"),value("Type2")},raw_hex=hex(bytes),
            battle_qualified=false,identity_qualified=false}
        for i,packed in ipairs(mon.pp_raw) do mon.pp[i],mon.pp_ups[i] = packed%64,math.floor(packed/64) end
        local nickname
        nickname,why = wram(prefix .. "Nickname",c.MON_NAME_LENGTH)
        if not nickname then return nil,why end
        mon,why = names(mon,nil,nickname)
        if not mon then return nil,why end
        return raw_observation(mon)
    end

    function r.read_stat_stages(side)
        local prefix = side == "player" and "wPlayer" or side == "enemy" and "wEnemy"
        if not prefix then return nil,"stat-stage side must be player or enemy" end
        -- Both battle_constants.asm:10-11,35-46 define neutral 7, max 13 and
        -- eight allocated levels; WRAM names seven then ds1 (C:454-472, G:942-960).
        -- StatDown refuses decrement to zero/clamps sharp drops to one:
        -- C effect_commands.asm:4339-4349; G:4306-4316. The producer proves min=1.
        if c.BASE_STAT_LEVEL ~= 7 or c.MAX_STAT_LEVEL ~= 13 or c.NUM_LEVEL_STATS ~= 8
            or d.stat_stage_min ~= 1 then return nil,"unsupported/missing stat-stage facts" end
        local symbols = {"Atk","Def","Spd","SAtk","SDef","Acc","Eva"}
        local indices = {"ATTACK","DEFENSE","SPEED","SP_ATTACK","SP_DEFENSE","ACCURACY","EVASION"}
        local fields = {}
        for index,suffix in ipairs(symbols) do
            if c[indices[index]] ~= index-1 then return nil,"generated stat-stage order disagrees" end
            fields[prefix .. suffix .. "Level"] = c[indices[index]]
        end
        local valid,why = geometry(prefix .. "StatLevels",fields)
        if not valid then return nil,why end
        local bytes
        bytes,why = wram(prefix .. "StatLevels",c.NUM_LEVEL_STATS)
        if not bytes then return nil,why end
        local wire = {}
        for index = 1,#symbols do
            if not integer(bytes[index],d.stat_stage_min,c.MAX_STAT_LEVEL) then
                return nil,"named stat-stage value outside source bounds"
            end
            -- docs/protocol.md §4.1 requires seven entries, 0..12 with neutral 6.
            wire[index] = bytes[index]-c.BASE_STAT_LEVEL+6
        end
        return raw_observation({raw=bytes,wire=wire,unused_raw=bytes[c.NUM_LEVEL_STATS],
            raw_hex=hex(bytes),battle_qualified=false})
    end

    function r.read_admission_facts()

    function r.read_admission_facts()
        local saved,why = wram("wSavedAtLeastOnce",1)
        if not saved then return nil,why end
        local battle
        battle,why = wram("wBattleMode",1)
        if not battle then return nil,why end
        return {saved_at_least_once=saved[1],battle_mode=battle[1],evidence="RAW_RAM_ONLY",
            admission_established=false,requires={"independently validated live save",
                "qualified checkpoint or qualified running battle","current ROM/session/reset identity"}}
    end

    return r
end

return R
