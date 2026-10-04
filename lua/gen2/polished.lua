-- lua/gen2/polished.lua — the Polished Crystal v3.2.3 foundation: dev admission, pure decoding and the
-- party/foe wire entries (P.wire, the client's injected wire). No emulator globals, bank switches, writes or boxes.
--
-- Every address and struct member offset is the generated profile's
-- (data/games/polished_crystal/profile.json, tools/gen_polished_profile.py, from the overlay .sym).
-- The record decode matches server/adapters/polished_codec.py field for field: party_struct 48 B
-- (6 one-byte EVs at +11, 3 DV bytes at +17, personality +20, ext-species/form +21, PP +22), the 11-B OT
-- field = 8 name bytes + 3 Extra (never text), a 9-bit species with the egg flag in the record (there is
-- no species list), battle_struct 35 B. The identity key is polished_codec.key, DDDDDD:OOOO:SSS:TT.
--
-- ADMISSION IS DEV-GRADE and deliberately separate from lua/gen2/entry.lua's vanilla production gate
-- (no catalog rows, no G4 grant, no receipts): the exact overlay sha1 of data/polished/overlay_provenance.json
-- is admitted, the clean release is refused with the companion message, everything else is refused.
local P = {}

P.TITLE, P.ROM_TYPE = "polished", "polished_crystal"
-- the server pairing foundation (server/adapters/__init__.py _ROM_TYPE_TO_FOUNDATION): never pairs with GSC
P.FOUNDATION = "gen2_polished"
P.PROFILE = "data/games/polished_crystal/profile.json"
P.CHARMAP = "data/games/polished_crystal/charmap.lua"
P.PROVENANCE = "data/polished/overlay_provenance.json"
P.HEADER = "PKPCRYSTAL"
local MAX_SPECIES = 0x1FF
-- the members the decoders read (tools/gen_polished_profile.py PARTY_REQUIRED / BATTLE_REQUIRED)
P.PARTY_FIELDS = {"Species", "Item", "Moves", "ID", "Exp", "HPEV", "AtkEV", "DefEV", "SpeEV", "SatEV", "SdfEV",
    "DVs", "Personality", "Form", "PP", "Happiness", "PokerusStatus", "CaughtData", "CaughtLevel",
    "CaughtLocation", "Level", "Status", "Unused", "HP", "MaxHP", "Attack", "Defense", "Speed", "SpAtk", "SpDef"}
P.BATTLE_FIELDS = {"Species", "Item", "Moves", "DVs", "Personality", "Form", "PP", "Happiness", "Level",
    "Status", "HP", "MaxHP", "Attack", "Defense", "Speed", "SpAtk", "SpDef", "Type1", "Type2"}

local function integer(value, low, high)
    return type(value) == "number" and value == math.floor(value) and value >= low and value <= high
end

local function bytes_ok(bytes, length)
    if type(bytes) ~= "table" or #bytes ~= length then return false end
    for i = 1, length do if not integer(bytes[i], 0, 255) then return false end end
    return true
end

local function slice(bytes, offset, length)
    local out = {}
    for i = 1, length do out[i] = bytes[offset + i] end
    return out
end

local function hex(bytes)
    local out = {}
    for i = 1, #bytes do out[i] = string.format("%02x", bytes[i]) end
    return table.concat(out)
end

local function load_json(json, path)
    local handle = assert(io.open(path, "rb"), "cannot open " .. path)
    local text = handle:read("*a")
    handle:close()
    return assert(json.decode(text))
end

local function hex_of(text)
    local out = {}
    for i = 1, #text do out[i] = string.format("%02x", text:byte(i)) end
    return table.concat(out)
end

--- The generated profile's polished title, checked against the pack's own source pin.
function P.load(root, json)
    local wrapper = load_json(json, root .. "/" .. P.PROFILE)
    assert(wrapper.schema == "gen2-profile-v1" and type(wrapper.titles) == "table", "generated Polished profile required")
    local profile = assert(wrapper.titles[P.TITLE], "polished title missing from profile")
    local charmap = dofile(root .. "/" .. P.CHARMAP)
    for _, key in ipairs({"rom_sha1", "commit", "lock_sha256"}) do
        assert(type(wrapper.source[key]) == "string" and charmap.source[key] == wrapper.source[key],
               "profile/pack source mismatch: " .. key)
    end
    assert(profile.rom_sha1 == wrapper.source.rom_sha1, "profile title/source mismatch")
    return profile, charmap, wrapper
end

--- Dev admission: {title, kind="overlay", rom_sha1, rehashed=true, ...} (an immutable Admission decision),
--- or nil, why. args = {root, rom_size, read_rom_u8}.
function P.admit(args)
    local ok, result, reason = pcall(function()
        local root = assert(args.root, "root required")
        local Admission = dofile(root .. "/lua/admission.lua")
        local json = dofile(root .. "/lua/json_codec.lua")
        local profile = P.load(root, json)
        local prov = load_json(json, root .. "/" .. P.PROVENANCE)
        local overlay = assert(profile.overlay, "profile has no overlay block")
        assert(prov.schema == "polished-overlay-provenance-v1" and prov.output.sha1 == overlay.rom_sha1
               and prov.base_sha1 == overlay.base_sha1 and prov.base_sha1 == profile.rom_sha1,
               "Polished profile is stale against data/polished/overlay_provenance.json")
        local anchors = {{offset=0x134, hex=hex_of(P.HEADER)}}
        local engine = Admission.new({
            acquire=function(request) return {size=request.rom_size, read_u8=request.read_rom_u8} end,
            catalog=function()
                return {{kind="overlay", sha1=prov.output.sha1}, {kind="clean", sha1=prov.base_sha1}}
            end,
            hashes=function(candidate) return {candidate.sha1} end,
            eligible=function(candidate)
                if candidate.kind == "clean" then
                    return false, "this Polished Crystal cartridge needs the SLink companion patch; "
                                  .. "prepare it through the Manager or /patcher"
                end
                return true
            end,
            anchors=function() return anchors end,
            kind=function(candidate, mode)
                if mode == "sha1" and candidate.kind == "overlay" then return "overlay" end
                return nil, "only the pinned Polished overlay is admitted"
            end,
            describe=function()
                return {pack="polished_crystal", title=P.TITLE, foundation=P.FOUNDATION, rom_type=P.ROM_TYPE,
                        qualification="DEV_OVERLAY_SHA1"}
            end,
            allow_unknown_hash=false,
        })
        return engine:admit(args)
    end)
    if not ok then return nil, tostring(result) end
    if result == nil then return nil, reason end
    return result
end

-- polished_codec.key: 3 DV bytes, OT ID, 9-bit species, traits (shiny bit 7, female bit 6, form 0-4).
function P.mon_key(mon)
    if type(mon) ~= "table" then return nil, "mon record required" end
    if not integer(mon.dv_bytes, 0, 0xFFFFFF) then return nil, "invalid or missing dv_bytes" end
    if not integer(mon.ot_id, 0, 0xFFFF) then return nil, "invalid or missing ot_id" end
    if not integer(mon.species_id, 1, MAX_SPECIES) then return nil, "invalid or missing species_id" end
    if not integer(mon.form, 0, 31) then return nil, "invalid or missing form" end
    local traits = (mon.shiny and 0x80 or 0) + (mon.gender == "female" and 0x40 or 0) + mon.form
    return string.format("%06X:%04X:%03X:%02X", mon.dv_bytes, mon.ot_id, mon.species_id, traits)
end

local function four(list)
    if type(list) ~= "table" or #list ~= 4 then return nil end
    for i = 1, 4 do if not integer(list[i], 0, 255) then return nil end end
    return {list[1], list[2], list[3], list[4]}
end

local function stages_of(stages)
    if stages == nil then return nil end
    if type(stages) ~= "table" or #stages ~= 7 then return nil, "invalid stat_stages" end
    for i = 1, 7 do if not integer(stages[i], 0, 12) then return nil, "invalid stat_stages" end end
    return {stages[1], stages[2], stages[3], stages[4], stages[5], stages[6], stages[7]}
end

local function common(mon)
    if not integer(mon.level, 1, 100) then return nil, "invalid or missing level" end
    if not integer(mon.hp, 0, 65535) or not integer(mon.max_hp, 0, 65535) then return nil, "invalid or missing hp/max_hp" end
    if not integer(mon.status, 0, 255) then return nil, "invalid or missing status" end
    if not integer(mon.held_item, 0, 255) then return nil, "invalid or missing held_item" end
    local moves, pp, pp_ups = four(mon.moves), four(mon.pp), four(mon.pp_ups)
    if not (moves and pp and pp_ups) then return nil, "invalid or missing moves/pp/pp_ups" end
    return {species_id=mon.species_id, level=mon.level, hp=mon.hp, maxHP=mon.max_hp, status_cond=mon.status,
            held_item_id=mon.held_item, moves=moves, pp=pp, pp_ups=pp_ups}
end

--- docs/protocol.md S4.1, lua/gen2/wire.lua party_entry's shape with the Polished key and the 70-byte
--- blob (48-byte record + 11-byte OT field + 11-byte nickname, gen2_polished.decode_party_blob). An egg
--- is refused like wire.lua's (no party wire shape for it).
function P.party_entry(mon, active_slot, stages)
    if type(mon) ~= "table" then return nil, "mon record required" end
    if mon.is_egg then return nil, "egg record: no defined Gen 2 party wire shape" end
    local key, why = P.mon_key(mon)
    if not key then return nil, why end
    if not integer(mon.slot, 0, 5) then return nil, "invalid or missing slot" end
    local blob = (mon.raw_hex or "") .. (mon.ot_raw_hex or "") .. (mon.nickname_raw_hex or "")
    if #blob ~= 140 or not blob:match("^%x+$") then return nil, "missing/invalid party blob hex" end
    if mon.nickname ~= nil and type(mon.nickname) ~= "string" then return nil, "nickname must be a decoded string" end
    local entry
    entry, why = common(mon)
    if not entry then return nil, why end
    entry.key, entry.slot, entry.blob_hex = key, mon.slot, blob
    entry.active = active_slot ~= nil and mon.slot == active_slot
    entry.nickname = mon.nickname
    if entry.active and stages ~= nil then
        entry.stat_stages, why = stages_of(stages)
        if not entry.stat_stages then return nil, why end
    end
    return entry
end

--- docs/protocol.md S4.3 (element of enemy_party), lua/gen2/wire.lua foe_entry's shape over a 9-bit species.
function P.foe_entry(mon, stages)
    if type(mon) ~= "table" then return nil, "mon record required" end
    if not integer(mon.species_id, 1, MAX_SPECIES) then return nil, "invalid or missing species_id" end
    local entry, why = common(mon)
    if not entry then return nil, why end
    entry.active = true
    if stages ~= nil then
        entry.stat_stages, why = stages_of(stages)
        if not entry.stat_stages then return nil, why end
    end
    return entry
end

--- docs/protocol.md S4.4 (element of `pc_boxes`) in lua/gen2/wire.lua box_entry's shape over Polished's 20 boxes:
--- `box` is 0-based (gen2_polished memorial_box_index 19 = box 20), `slot` 0..19. An egg is refused (the client
--- omits it, as in the party).
function P.box_entry(mon, box_index)
    if type(mon) ~= "table" then return nil, "mon record required" end
    if mon.is_egg then return nil, "egg record: no defined Gen 2 box wire shape" end
    local key, why = P.mon_key(mon)
    if not key then return nil, why end
    if not integer(box_index, 0, 19) then return nil, "invalid or missing box_index" end
    if not integer(mon.slot, 0, 19) then return nil, "invalid or missing slot" end
    if not integer(mon.level, 1, 100) then return nil, "invalid or missing level" end
    local moves = four(mon.moves)
    if not moves then return nil, "invalid or missing moves" end
    if not integer(mon.held_item, 0, 255) then return nil, "invalid or missing held_item" end
    if mon.nickname ~= nil and type(mon.nickname) ~= "string" then return nil, "nickname must be a decoded string" end
    local entry = {box=box_index, slot=mon.slot, key=key, species_id=mon.species_id, level=mon.level,
                   held_item_id=mon.held_item, moves=moves}
    if mon.nickname ~= nil then entry.nickname = mon.nickname end
    return entry
end

--- The wire.lua-shaped table lua/gen2/client.lua takes by injection (p.wire).
P.wire = {mon_key=P.mon_key, party_entry=P.party_entry, foe_entry=P.foe_entry, box_entry=P.box_entry}

--- Reads over the generated profile. io: read_range(address, length, domain), bank_valid(bank, address, length).
function P.new(profile, io, decode_name)
    if type(profile) ~= "table" or profile.title ~= P.TITLE or type(profile.ram) ~= "table"
       or type(profile.ram_bank) ~= "table" or type(profile.constants) ~= "table"
       or type(profile.derived) ~= "table" or type(profile.structs) ~= "table" then
        return nil, "generated Polished profile required"
    end
    if type(io) ~= "table" or type(io.read_range) ~= "function" then return nil, "injected read_range required" end
    if decode_name ~= nil and type(decode_name) ~= "function" then return nil, "name decoder must be a function" end
    local c, d, a, banks = profile.constants, profile.derived, profile.ram, profile.ram_bank
    local s, b = profile.structs.party, profile.structs.battle
    if type(s) ~= "table" or type(b) ~= "table" or s.End ~= d.party_struct_size or b.StructEnd ~= d.battle_struct_size
       or c.NUM_MOVES ~= 4 or c.NAME_LENGTH ~= d.name_length or c.MON_NAME_LENGTH ~= d.mon_name_length
       or not integer(c.PLAYER_NAME_LENGTH, 1, c.NAME_LENGTH) or c.PARTY_LENGTH ~= d.party_capacity then
        return nil, "Polished profile dimensions disagree"
    end
    for _, name in ipairs(P.PARTY_FIELDS) do
        if not integer(s[name], 0, s.End) then return nil, "party_struct member missing: " .. name end
    end
    for _, name in ipairs(P.BATTLE_FIELDS) do
        if not integer(b[name], 0, b.StructEnd) then return nil, "battle_struct member missing: " .. name end
    end
    for _, name in ipairs({"SHINY_MASK", "ABILITY_MASK", "NATURE_MASK", "GENDER_MASK", "IS_EGG_MASK",
                           "EXTSPECIES_MASK", "FORM_MASK"}) do
        if not integer(c[name], 1, 255) then return nil, "missing profile mask " .. name end
    end
    local r = {title=P.TITLE, transfer_blob_size=s.End + c.NAME_LENGTH + c.MON_NAME_LENGTH}
    local function be16(bytes, offset) return bytes[offset + 1] * 256 + bytes[offset + 2] end
    local function field(mask, value) return (value & mask) // (mask & -mask) end -- mask's bits, shifted down

    local function decode(bytes, name, length)
        if not bytes_ok(bytes, length) then return nil, "invalid " .. name .. " bytes" end
        if not decode_name then return nil end
        local ok, value = pcall(decode_name, bytes)
        if not ok or type(value) ~= "string" then return nil, "name decoder unavailable or failed" end
        return value
    end

    -- personality (shiny bit 7, ability bits 5-6, nature 0-4) + species/form byte (female bit 7, egg bit 6,
    -- species bit 8 in bit 5, form 0-4): pokemon_data_constants.asm masks, carried in the profile.
    local function traits(mon, personality, form_byte)
        mon.shiny = field(c.SHINY_MASK, personality) == 1
        mon.ability_slot = field(c.ABILITY_MASK, personality)
        mon.nature = field(c.NATURE_MASK, personality)
        mon.gender = field(c.GENDER_MASK, form_byte) == 1 and "female" or "male"
        mon.is_egg = field(c.IS_EGG_MASK, form_byte) == 1
        mon.form = field(c.FORM_MASK, form_byte)
        mon.species_id = mon.species_id + field(c.EXTSPECIES_MASK, form_byte) * 256
    end

    local function dvs_of(mon, bytes, at)
        local hp_atk, def_spe, sat_sdf = bytes[at + 1], bytes[at + 2], bytes[at + 3]
        mon.dv_bytes = hp_atk * 65536 + def_spe * 256 + sat_sdf
        mon.dvs = {hp=hp_atk // 16, attack=hp_atk % 16, defense=def_spe // 16, speed=def_spe % 16,
                   special_attack=sat_sdf // 16, special_defense=sat_sdf % 16}
    end

    local function pp_of(mon, bytes, at)
        mon.pp, mon.pp_ups = {}, {}
        for i = 1, c.NUM_MOVES do
            local packed = bytes[at + i]
            mon.pp[i], mon.pp_ups[i] = packed % 64, packed // 64
        end
    end

    local function stats_of(bytes, src)
        return {attack=be16(bytes, src.Attack), defense=be16(bytes, src.Defense), speed=be16(bytes, src.Speed),
                special_attack=be16(bytes, src.SpAtk), special_defense=be16(bytes, src.SpDef)}
    end

    --- One party_struct + its 11-byte OT field + 11-byte nickname (either may be nil).
    function r.decode_record(bytes, ot, nickname)
        if not bytes_ok(bytes, s.End) then return nil, "invalid or incomplete record bytes" end
        local mon = {species_id=bytes[s.Species + 1], held_item=bytes[s.Item + 1],
            moves=slice(bytes, s.Moves, c.NUM_MOVES), ot_id=be16(bytes, s.ID),
            exp=bytes[s.Exp + 1] * 65536 + bytes[s.Exp + 2] * 256 + bytes[s.Exp + 3],
            evs={hp=bytes[s.HPEV + 1], attack=bytes[s.AtkEV + 1], defense=bytes[s.DefEV + 1],
                 speed=bytes[s.SpeEV + 1], special_attack=bytes[s.SatEV + 1], special_defense=bytes[s.SdfEV + 1]},
            happiness=bytes[s.Happiness + 1], pokerus=bytes[s.PokerusStatus + 1],
            caught_data=bytes[s.CaughtData + 1], caught_level=bytes[s.CaughtLevel + 1],
            caught_location=bytes[s.CaughtLocation + 1], level=bytes[s.Level + 1], status=bytes[s.Status + 1],
            unused=bytes[s.Unused + 1], hp=be16(bytes, s.HP), max_hp=be16(bytes, s.MaxHP),
            stats=stats_of(bytes, s), raw_hex=hex(bytes)}
        traits(mon, bytes[s.Personality + 1], bytes[s.Form + 1])
        if not integer(mon.species_id, 1, MAX_SPECIES) then return nil, "invalid record species" end
        if not integer(mon.level, 1, c.MAX_LEVEL) then return nil, "record level outside 1.." .. c.MAX_LEVEL end
        dvs_of(mon, bytes, s.DVs)
        pp_of(mon, bytes, s.PP)
        local why
        if ot ~= nil then
            if not bytes_ok(ot, c.NAME_LENGTH) then return nil, "invalid ot bytes" end
            mon.ot_raw_hex = hex(ot)
            -- the OT field is PLAYER_NAME_LENGTH name bytes + Extra (hyper training), never text
            mon.ot_name, why = decode(slice(ot, 0, c.PLAYER_NAME_LENGTH), "ot", c.PLAYER_NAME_LENGTH)
            if why then return nil, why end
        end
        if nickname ~= nil then
            if not bytes_ok(nickname, c.MON_NAME_LENGTH) then return nil, "invalid nickname bytes" end
            mon.nickname_raw_hex = hex(nickname)
            mon.nickname, why = decode(nickname, "nickname", c.MON_NAME_LENGTH)
            if why then return nil, why end
        end
        mon.key = P.mon_key(mon)
        return mon
    end

    function r.decode_transfer_blob(bytes)
        if not bytes_ok(bytes, r.transfer_blob_size) then return nil, "transfer blob must contain 48+11+11 bytes" end
        return r.decode_record(slice(bytes, 0, s.End), slice(bytes, s.End, c.NAME_LENGTH),
                               slice(bytes, s.End + c.NAME_LENGTH, c.MON_NAME_LENGTH))
    end

    -- the party block from wPartyCount to wPartyMonNicknamesEnd (the 7 bytes after the count are unused:
    -- Polished has no species list)
    local mons_at = a.wPartyMons and a.wPartyCount and a.wPartyMons - a.wPartyCount
    local ots_at = mons_at and mons_at + c.PARTY_LENGTH * s.End
    local nicks_at = ots_at and ots_at + c.PARTY_LENGTH * c.NAME_LENGTH
    local party_length = nicks_at and nicks_at + c.PARTY_LENGTH * c.MON_NAME_LENGTH

    function r.decode_party_block(bytes)
        if not bytes_ok(bytes, party_length) then return nil, "invalid or incomplete party block bytes" end
        local count = bytes[1]
        if count > c.PARTY_LENGTH then return nil, "party count exceeds capacity" end
        local result = {count=count, mons={}, raw_hex=hex(bytes), snapshot_qualified=false}
        for slot = 0, count - 1 do
            local mon, why = r.decode_record(slice(bytes, mons_at + slot * s.End, s.End),
                slice(bytes, ots_at + slot * c.NAME_LENGTH, c.NAME_LENGTH),
                slice(bytes, nicks_at + slot * c.MON_NAME_LENGTH, c.MON_NAME_LENGTH))
            if not mon then return nil, "slot " .. slot .. ": " .. why end
            mon.slot = slot
            result.mons[#result.mons + 1] = mon
        end
        return result
    end

    local function wram(name, length)
        local address, bank = a[name], banks[name]
        if not integer(address, 0xC000, 0xDFFF) or not integer(length, 1, 0x2000) or not integer(bank, 0, 7) then
            return nil, "missing/invalid WRAM symbol " .. name
        end
        if (address < 0xD000 and (bank ~= 0 or address + length > 0xD000))
           or (address >= 0xD000 and (bank == 0 or address + length > 0xE000)) then
            return nil, "WRAM range crosses its bank window"
        end
        if type(io.bank_valid) ~= "function" then return nil, "explicit WRAM bank validity required" end
        local ok, valid = pcall(io.bank_valid, bank, address, length)
        if not ok or valid ~= true then return nil, "WRAM bank unavailable or invalid" end
        local bytes
        ok, bytes = pcall(io.read_range, address, length, "System Bus")
        if not ok or not bytes_ok(bytes, length) then return nil, "unavailable or malformed System Bus read" end
        ok, valid = pcall(io.bank_valid, bank, address, length)
        if not ok or valid ~= true then return nil, "WRAM bank changed or became unavailable" end
        return slice(bytes, 0, length)
    end

    local function geometry(base, fields)
        if not integer(a[base], 0xC000, 0xDFFF) then return nil, "missing/invalid WRAM symbol " .. base end
        for name, offset in pairs(fields) do
            if a[name] ~= a[base] + offset or banks[name] ~= banks[base] then
                return nil, "symbol geometry disagrees: " .. name
            end
        end
        return true
    end

    local function raw(result)
        result.evidence, result.snapshot_qualified = "RAW_RAM_ONLY", false
        return result
    end

    local function byte_symbol(name)
        local bytes, why = wram(name, 1)
        if not bytes then return nil, why end
        return bytes[1]
    end

    function r.read_party()
        if not party_length then return nil, "missing party block symbols" end
        local valid, why = geometry("wPartyCount", {wPartyMons=mons_at, wPartyMonOTs=ots_at,
            wPartyMonNicknames=nicks_at, wPartyMonNicknamesEnd=party_length})
        if not valid then return nil, why end
        local bytes
        bytes, why = wram("wPartyCount", party_length)
        if not bytes then return nil, why end
        local result
        result, why = r.decode_party_block(bytes)
        if not result then return nil, why end
        result.ownership = "live_party_wram"
        return result
    end

    function r.read_player()
        -- wPlayerID (dw, high byte first), then wPlayerGender, then wPlayerName (NAME_LENGTH)
        local name_at = integer(a.wPlayerName, 0xC000, 0xDFFF) and integer(a.wPlayerID, 0xC000, 0xDFFF)
                        and a.wPlayerName - a.wPlayerID
        if not name_at or name_at < 2 or banks.wPlayerName ~= banks.wPlayerID then
            return nil, "player symbol geometry disagrees"
        end
        local bytes, why = wram("wPlayerID", name_at + c.NAME_LENGTH)
        if not bytes then return nil, why end
        local name = slice(bytes, name_at, c.NAME_LENGTH)
        local result = {ot_id=be16(bytes, 0), identity_qualified=false, name_raw_hex=hex(name), raw_hex=hex(bytes)}
        result.player_name, why = decode(name, "player name", c.NAME_LENGTH)
        if why then return nil, why end
        return raw(result)
    end

    function r.read_map()
        local valid, why = geometry("wMapGroup", {wMapNumber=1, wYCoord=2, wXCoord=3})
        if not valid then return nil, why end
        local bytes
        bytes, why = wram("wMapGroup", 4)
        if not bytes then return nil, why end
        return raw({group=bytes[1], number=bytes[2], y=bytes[3], x=bytes[4], raw_hex=hex(bytes)})
    end

    function r.read_badges()
        if c.NUM_JOHTO_BADGES ~= 8 or c.NUM_KANTO_BADGES ~= 8 then return nil, "unsupported/missing badge-count facts" end
        local valid, why = geometry("wJohtoBadges", {wKantoBadges=1})
        if not valid then return nil, why end
        local bytes
        bytes, why = wram("wJohtoBadges", 2)
        if not bytes then return nil, why end
        return raw({johto=bytes[1], kanto=bytes[2], raw_hex=hex(bytes)})
    end

    --- items / medicine / balls / berries: (id, quantity) pairs + $FF terminator (wramx.asm bag block).
    function r.read_pocket(pocket)
        local p = type(d.pockets) == "table" and d.pockets[pocket]
        if type(p) ~= "table" or not integer(p.capacity, 1, 255) then return nil, "unknown bag pocket" end
        local valid, why = geometry(p.count, {[p.data]=1})
        if not valid then return nil, why end
        local bytes
        bytes, why = wram(p.count, 2 + p.capacity * 2)
        if not bytes then return nil, why end
        local count = bytes[1]
        if count > p.capacity then return nil, "pocket count exceeds capacity" end
        if bytes[2 + count * 2] ~= 255 then return nil, "missing pocket terminator" end
        local result = {count=count, entries={}, raw_hex=hex(bytes)}
        for slot = 0, count - 1 do
            local id, quantity = bytes[2 + slot * 2], bytes[3 + slot * 2]
            if not integer(id, 1, 254) then return nil, "invalid occupied pocket item id" end
            if not integer(quantity, 1, c.MAX_ITEM_STACK) then return nil, "invalid occupied pocket quantity" end
            result.entries[#result.entries + 1] = {slot=slot, id=id, quantity=quantity}
        end
        return raw(result)
    end

    function r.read_current_box_num()
        local value, why = byte_symbol("wCurBox")
        if value == nil then return nil, why end
        if value >= c.NUM_BOXES then return nil, "current box index outside 0.." .. (c.NUM_BOXES - 1) end
        return value
    end

    function r.read_battle()
        if c.WILD_BATTLE ~= 1 or c.TRAINER_BATTLE ~= 2 or not integer(c.BATTLERESULT_BITMASK, 0, 255) then
            return nil, "unsupported/missing battle-context facts"
        end
        local mode, why = byte_symbol("wBattleMode")
        if mode == nil then return nil, why end
        if mode ~= 0 and mode ~= c.WILD_BATTLE and mode ~= c.TRAINER_BATTLE then
            return nil, "battle mode outside source enumeration"
        end
        local battle_type, result
        battle_type, why = byte_symbol("wBattleType")
        if battle_type == nil then return nil, why end
        result, why = byte_symbol("wBattleResult")
        if result == nil then return nil, why end
        -- BATTLERESULT_BITMASK holds the flag bits to remove, not result-code bits
        local observed = {mode=mode, battle_type=battle_type, result_raw=result,
            result_code=result & (255 - c.BATTLERESULT_BITMASK), battle_qualified=false}
        if mode ~= 0 then
            observed.active_slot, why = byte_symbol("wCurBattleMon")
            if observed.active_slot == nil then return nil, why end
            if observed.active_slot >= c.PARTY_LENGTH then return nil, "active battle slot outside party capacity" end
            if mode == c.TRAINER_BATTLE then
                local class, id
                class, why = byte_symbol("wOtherTrainerClass")
                if class == nil then return nil, why end
                id, why = byte_symbol("wOtherTrainerID")
                if id == nil then return nil, why end
                observed.trainer = {class_raw=class, id_raw=id}
            end
        end
        local after
        after, why = byte_symbol("wBattleMode")
        if after == nil then return nil, why end
        if after ~= mode then return nil, "battle mode changed during read" end
        return raw(observed)
    end

    function r.read_battle_mon(side)
        local prefix = side == "player" and "wBattleMon" or side == "enemy" and "wEnemyMon"
        if not prefix then return nil, "battle side must be player or enemy" end
        local fields = {}
        for name, offset in pairs(b) do fields[prefix .. name] = offset end
        local valid, why = geometry(prefix, fields)
        if not valid then return nil, why end
        local bytes
        bytes, why = wram(prefix, b.StructEnd)
        if not bytes then return nil, why end
        local mon = {species_id=bytes[b.Species + 1], held_item=bytes[b.Item + 1],
            moves=slice(bytes, b.Moves, c.NUM_MOVES), pp_raw=slice(bytes, b.PP, c.NUM_MOVES),
            happiness=bytes[b.Happiness + 1], level=bytes[b.Level + 1], status=bytes[b.Status + 1],
            status_aux_raw=bytes[b.Status + 2], hp=be16(bytes, b.HP), max_hp=be16(bytes, b.MaxHP),
            stats=stats_of(bytes, b), types_raw={bytes[b.Type1 + 1], bytes[b.Type2 + 1]}, raw_hex=hex(bytes),
            battle_qualified=false, identity_qualified=false}
        traits(mon, bytes[b.Personality + 1], bytes[b.Form + 1])
        if not integer(mon.species_id, 1, MAX_SPECIES) then return nil, "invalid battle-view species" end
        if not integer(mon.level, 1, c.MAX_LEVEL) then return nil, "battle-view level outside source bounds" end
        dvs_of(mon, bytes, b.DVs)
        pp_of(mon, bytes, b.PP)
        local nickname
        nickname, why = wram(prefix .. "Nickname", c.MON_NAME_LENGTH)
        if not nickname then return nil, why end
        mon.nickname_raw_hex = hex(nickname)
        mon.nickname, why = decode(nickname, "nickname", c.MON_NAME_LENGTH)
        if why then return nil, why end
        return raw(mon)
    end

    local STAGE_SUFFIX = {"Atk", "Def", "Spe", "SAtk", "SDef", "Acc", "Eva"}
    local STAGE_INDEX = {"ATTACK", "DEFENSE", "SPEED", "SP_ATTACK", "SP_DEFENSE", "ACCURACY", "EVASION"}
    function r.read_stat_stages(side)
        local prefix = side == "player" and "wPlayer" or side == "enemy" and "wEnemy"
        if not prefix then return nil, "stat-stage side must be player or enemy" end
        if c.BASE_STAT_LEVEL ~= 7 or c.MAX_STAT_LEVEL ~= 13 or c.NUM_LEVEL_STATS ~= 8 then
            return nil, "unsupported/missing stat-stage facts"
        end
        local fields = {}
        for i, suffix in ipairs(STAGE_SUFFIX) do
            if c[STAGE_INDEX[i]] ~= i - 1 then return nil, "generated stat-stage order disagrees" end
            fields[prefix .. suffix .. "Level"] = i - 1
        end
        local valid, why = geometry(prefix .. "StatLevels", fields)
        if not valid then return nil, why end
        local bytes
        bytes, why = wram(prefix .. "StatLevels", c.NUM_LEVEL_STATS)
        if not bytes then return nil, why end
        local wire = {}
        for i = 1, #STAGE_SUFFIX do
            -- docs/protocol.md §4.1: seven entries 0..12, neutral 6
            if not integer(bytes[i], 1, c.MAX_STAT_LEVEL) then return nil, "named stat-stage value outside 1..13" end
            wire[i] = bytes[i] - c.BASE_STAT_LEVEL + 6
        end
        return raw({raw=bytes, wire=wire, unused_raw=bytes[c.NUM_LEVEL_STATS], raw_hex=hex(bytes), battle_qualified=false})
    end

    return r
end

-- ── C-BOX: the read-only newbox census (docs/polished/CLIENT.md C-BOX, docs/polished/NEWBOX.md) ─────────────
-- Coordinates are the pinned .sym {bank, address} pairs (data/polished/polished_slink.sym;
-- tests/unit/test_polished_boxes_census.py re-derives every one from it). The profile does not carry them yet.
local SYM = {sBoxMons1A={2, 0xA000}, sBoxMons1B={0, 0xA000}, sBoxMons1C={1, 0xB60C},
             sBoxMons2A={3, 0xA000}, sBoxMons2B={0, 0xABF1}, sBoxMons2C={1, 0xB858},
             wPokeDB1UsedEntries={2, 0xD8B7}, wPokeDB2UsedEntries={2, 0xD8D1},
             wGameLogicPaused={0, 0xCEB9}, sWritingBackup={0, 0xABE5},
             sSaveVersion={0, 0xABE2}, sGameData={1, 0xA008}, sGameDataEnd={1, 0xAB83}, sChecksum={1, 0xAD0D}}
local NEWBOX_AT, BACKUP_NEWBOX_AT, NEWBOX_STRIDE, SAVE_VERSION = {1, 0xB0E4}, {1, 0xB378}, 0x21, 10

--- {[label] = {bank, address}} for polished_boxes.lua B.COORD_LABELS plus the save anchors.
function P.newbox_coords()
    local out = {}
    for label, at in pairs(SYM) do out[label] = {at[1], at[2]} end
    for n = 1, 20 do
        out["sNewBox" .. n] = {NEWBOX_AT[1], NEWBOX_AT[2] + NEWBOX_STRIDE * (n - 1)}
        out["sBackupNewBox" .. n] = {BACKUP_NEWBOX_AT[1], BACKUP_NEWBOX_AT[2] + NEWBOX_STRIDE * (n - 1)}
    end
    return out
end

--- The census as the client box readers. Boxes = lua/gen2/polished_boxes.lua; io = the production io (read_u8 with
--- a domain, domain_size, cart_ram_linear); decode_text optional; log optional (called once per distinct refusal).
--- Returns {read_current_box_num, read_active_box, read_storage_box}: client.lua rescan_boxes walks boxes 0..19
--- through read_storage_box (no volatile active shadow here, so the current box is -1) and read_storage_box(0)
--- takes the one fresh scan the other 19 are served from. NEVER writes.
---
--- FAIL CLOSED (a refusal returns nil, why and the client treats it as not a census, client.lua:322): a scan counts
--- only when (1) CartRAM and WRAM are the flat 32 KiB images, (2) no native save is running, (3) the SAVE is real:
--- sSaveVersion == 10 big-endian and the 16-bit byte sum of sGameData (01:A008..AB82) equals sChecksum, so a zeroed,
--- never-saved or mis-mapped image can never read as an empty census, and (4) every one of the 20 boxes decoded:
--- no corrupt pointer, no invalid record, no Bad Egg (checksum mismatch) and no pointer whose WRAM allocation flag is
--- clear (the engine never leaves a referenced entry unflagged, so that means the flag mapping is wrong).
--- UNPROVEN without a Polished cartridge: the WRAM-domain flat mapping of bank 2 (NEWBOX 7) and the flag semantics.
function P.census(Boxes, io, decode_text, log)
    if type(Boxes) ~= "table" or type(io) ~= "table" or type(io.read_u8) ~= "function" then
        return nil, "Boxes module and explicit read_u8 required"
    end
    local boxes, why = Boxes.new(P.newbox_coords(), io, P.mon_key, decode_text)
    if not boxes then return nil, why end
    local CART, WRAM = "CartRAM", "WRAM"
    local function rd(domain, offset)
        local value = io.read_u8(offset, domain)
        if not integer(value, 0, 255) then error("unavailable or malformed " .. domain .. " read", 0) end
        return value
    end
    local function cart(label, plus) return SYM[label][1] * 0x2000 + SYM[label][2] - 0xA000 + (plus or 0) end
    local function scan()
        if io.cart_ram_linear ~= true or type(io.domain_size) ~= "function" then
            return nil, "qualified linear CartRAM binding required"
        end
        local sram, wram = io.domain_size(CART), io.domain_size(WRAM)
        if not integer(sram, 0x8000, 0x80000) or not integer(wram, 0x8000, 0x8000) then
            return nil, "CartRAM must be the 32 KiB SRAM image and WRAM the 32 KiB CGB image"
        end
        if rd(WRAM, SYM.wGameLogicPaused[2] - 0xC000) ~= 0 then return nil, "native save running (game logic paused)" end
        if rd(CART, cart("sWritingBackup")) == 1 then return nil, "backup save in progress" end
        local version = rd(CART, cart("sSaveVersion")) * 256 + rd(CART, cart("sSaveVersion", 1))
        if version ~= SAVE_VERSION then return nil, string.format("no valid Polished save (sSaveVersion %04X)", version) end
        local sum = 0
        for at = cart("sGameData"), cart("sGameDataEnd") - 1 do sum = (sum + rd(CART, at)) & 0xFFFF end
        if sum ~= rd(CART, cart("sChecksum")) + 256 * rd(CART, cart("sChecksum", 1)) then
            return nil, "save checksum mismatch (SRAM mapping or save invalid)"
        end
        local snap
        snap, why = boxes.read_boxes("gameplay")
        if not snap then return nil, why end
        if not snap.complete then return nil, "box census incomplete (corrupt pointer or invalid record)" end
        if #snap.bad_eggs > 0 then return nil, "box census incomplete (Bad Egg entry)" end
        if #snap.unflagged > 0 then return nil, "box census incomplete (referenced entry with a clear WRAM flag)" end
        return snap
    end

    local c, snapshot, last, last_reason = {}, nil, nil, nil
    local function guarded()
        local ok, snap, reason = pcall(scan)
        if not ok then snap, reason = nil, tostring(snap) end
        if not snap and log and reason ~= last then log("[SLink-gen2] polished box census withheld: " .. tostring(reason)) end
        last = (not snap) and reason or nil
        return snap, reason
    end
    function c.read_current_box_num() return -1 end
    function c.read_active_box() return nil, "Polished has no active box shadow" end
    function c.read_storage_box(index)
        if not integer(index, 0, 19) then return nil, "storage box index outside 0..19" end
        if index == 0 then snapshot, last_reason = guarded() end -- the client always walks 0..19: one scan per pass
        if not snapshot then return nil, last_reason or "census scan starts at box 0" end
        local mons = {}
        for _, mon in ipairs(snapshot.boxes[index + 1].mons) do
            local copy = {}
            for k, v in pairs(mon) do copy[k] = v end
            copy.slot = mon.slot - 1
            copy.moves = {}
            for i = 0, 3 do copy.moves[i + 1] = tonumber(mon.raw_hex:sub(5 + 2 * i, 6 + 2 * i), 16) end -- savemon bytes 2..5
            mons[#mons + 1] = copy
        end
        return {mons=mons}
    end
    return c
end

return P
