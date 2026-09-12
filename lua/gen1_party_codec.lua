-- Read-only gen1-rby-party-v1 validation. No emulator memory is read or written.
local ok, Data = pcall(require, "gen1_party_codec_data")
if not ok then
    local root = rawget(_G, "SLINK_ROOT") or os.getenv("SLINK_ROOT")
    Data = dofile((root and (root .. "/") or "") .. "data/games/gen1_rby/gen1_party_codec_data.lua")
end
assert(Data.schema == "gen1-rby-codec-data-v1", "unsupported party-codec data schema")
local M = {VERSION = "gen1-rby-party-v1", BLOB_LENGTH = 66, data_hash = Data.content_sha256}
local names = {}
for _, byte in ipairs(Data.name_bytes) do names[byte] = true end

local function integer(value, minimum, maximum)
    return type(value) == "number" and value % 1 == 0 and value >= minimum and value <= maximum
end

local function key_set(keys)
    if type(keys) ~= "table" or getmetatable(keys) ~= nil then return false end
    for key, present in pairs(keys) do
        if type(key) ~= "string" or not key:match("^[0-9A-F][0-9A-F][0-9A-F][0-9A-F]:[0-9A-F][0-9A-F][0-9A-F][0-9A-F]:[0-9A-F][0-9A-F]$")
            or present ~= true then return false end
    end
    return true
end

local function byte_array(raw)
    if type(raw) ~= "table" and type(raw) ~= "string" then
        return nil, "party blob must be bytes or an integer array"
    end
    if #raw ~= 66 then return nil, "party blob must be exactly 66 bytes" end
    local copy = {}
    if type(raw) == "string" then
        for i = 1, 66 do copy[i] = raw:byte(i) end
    else
        if getmetatable(raw) ~= nil then return nil, "blob array must have no metatable" end
        local count = 0
        for key, value in pairs(raw) do
            if not integer(key, 1, 66) or not integer(value, 0, 255) then
                return nil, "invalid blob byte or array index"
            end
            copy[key] = value
            count = count + 1
        end
        if count ~= 66 then return nil, "party blob must have every byte" end
    end
    return copy
end

local function be16(raw, offset) return raw[offset + 1] * 256 + raw[offset + 2] end
local function identity(raw)
    return string.format("%02X%02X:%04X:%02X", raw[28], raw[29], be16(raw, 12), raw[1])
end
local function valid_name(raw, offset)
    for index = 0, 10 do
        local byte = raw[offset + index + 1]
        if byte == 0x50 then return index >= 1 end
        if not names[byte] then return false end
    end
    return false
end
-- OT-only rule: the engine's in-game-trade OT (`dname "<TRAINER>"`: $5D then ten $50)
-- is legal verbatim as all 11 bytes; nicknames and player names stay strict.
local function valid_ot(raw, offset)
    for index = 1, 11 do
        if raw[offset + index] ~= Data.npc_trade_ot[index] then return valid_name(raw, offset) end
    end
    return true
end

function M.experienceForLevel(growth, level)
    if not integer(growth, 0, 5) or not integer(level, 1, 100) then return nil end
    local c = Data.growth_rates[growth + 1]
    return (math.floor(c[1] * level ^ 3 / c[2]) + c[3] * level ^ 2 + c[4] * level - c[5]) % 0x1000000
end

function M.levelFromExperience(growth, experience)
    local maximum = M.experienceForLevel(growth, 100)
    if not maximum or not integer(experience, 0, maximum) then return nil end
    local level = 1
    for next_level = 2, 100 do
        if M.experienceForLevel(growth, next_level) > experience then break end
        level = next_level
    end
    return level
end

function M.maxPP(variant, move, ups)
    local profile = Data.titles[variant]
    if not profile or not integer(move, 1, 165) or not integer(ups, 0, 3) then return nil end
    local base = profile.move_pp[move]
    return base + ups * math.min(7, math.floor(base / 5))
end

function M.validateBlob(raw, variant, expected_key)
    local profile = Data.titles[variant]
    if not profile then return nil, "party codec requires admitted Red, Blue or Yellow" end
    local blob, err = byte_array(raw)
    if not blob then return nil, err end
    local species = blob[1]
    local facts = profile.species[species]
    if not facts then return nil, "invalid internal species" end
    local key = identity(blob)
    if expected_key ~= nil and key ~= expected_key then return nil, "key does not match species, DVs and OTID" end
    local level = blob[34]
    if not integer(level, 1, 100) then return nil, "invalid level" end
    if not integer(blob[4], 0, 100) then return nil, "invalid box level" end
    local experience = blob[15] * 65536 + blob[16] * 256 + blob[17]
    if M.levelFromExperience(facts.growth_rate, experience) ~= level then
        return nil, "level does not match experience"
    end
    if blob[6] ~= facts.types[1] or blob[7] ~= facts.types[2] then
        return nil, "types differ from the canonical species"
    end
    local status = blob[5]
    if status > 7 and status ~= 8 and status ~= 16 and status ~= 32 and status ~= 64 then
        return nil, "invalid or combined Gen1 status"
    end
    -- Stat experience may have grown since the last level-up. Party-tail stats
    -- must be in range, but need not equal a fresh CalcStats call until withdrawal.
    for offset = 34, 42, 2 do
        if not integer(be16(blob, offset), 1, 999) then return nil, "invalid computed stat" end
    end
    local hp, maximum = be16(blob, 1), be16(blob, 34)
    if hp > maximum then return nil, "current HP exceeds max HP" end
    local moves, pp, pp_ups, empty = {}, {}, {}, false
    for slot = 1, 4 do
        local move, packed = blob[8 + slot], blob[29 + slot]
        local current, ups = packed % 64, math.floor(packed / 64)
        if move == 0 then
            empty = true
            if packed ~= 0 then return nil, "empty move slot has PP or PP Ups" end
        else
            if empty then return nil, "nonempty move after an empty slot" end
            local limit = M.maxPP(variant, move, ups)
            if not limit then return nil, "invalid move" end
            if current > limit then return nil, "PP exceeds the canonical PP-Up maximum" end
        end
        moves[slot], pp[slot], pp_ups[slot] = move, current, ups
    end
    if moves[1] == 0 then return nil, "Pokemon must have at least one move" end
    if not valid_ot(blob, 44) then return nil, "invalid or unterminated OT name" end
    if not valid_name(blob, 55) then return nil, "invalid or unterminated nickname" end
    local stat_exp, stats, ot_name, nickname = {}, {}, {}, {}
    for i = 1, 5 do stat_exp[i], stats[i] = be16(blob, 15 + i * 2), be16(blob, 32 + i * 2) end
    for i = 1, 11 do ot_name[i], nickname[i] = blob[44 + i], blob[55 + i] end
    return {blob = blob, key = key, species_index = species, species_id = facts.dex,
            level = level, hp = hp, maxHP = maximum, status = status,
            moves = moves, pp = pp, pp_ups = pp_ups, box_level = blob[4],
            types = {blob[6], blob[7]}, catch_rate = blob[8], ot_id = be16(blob, 12),
            dv_word = be16(blob, 27), experience = experience, stat_experience = stat_exp,
            computed_stats = stats, ot_name = ot_name, nickname = nickname}
end

function M.validateParty(blobs, variant, species_list, boxed_keys)
    if boxed_keys ~= nil and not key_set(boxed_keys) then return nil, "invalid boxed inventory" end
    if type(blobs) ~= "table" or getmetatable(blobs) ~= nil or not integer(#blobs, 1, 6) then
        return nil, "party must contain 1..6 blobs"
    end
    local entries = 0
    for index in pairs(blobs) do
        if not integer(index, 1, #blobs) then return nil, "invalid party index" end
        entries = entries + 1
    end
    if entries ~= #blobs then return nil, "missing party entry" end
    local result, seen = {}, {}
    for index = 1, #blobs do
        local mon, err = M.validateBlob(blobs[index], variant)
        if not mon then return nil, "blob " .. index .. ": " .. err end
        if seen[mon.key] or (boxed_keys and boxed_keys[mon.key]) then
            return nil, "duplicate party or boxed key"
        end
        seen[mon.key], result[index] = true, mon
    end
    if species_list ~= nil then
        if type(species_list) ~= "table" or (#species_list ~= #result + 1 and #species_list ~= 7) then
            return nil, "invalid party species-list length"
        end
        if getmetatable(species_list) ~= nil then return nil, "invalid species-list table" end
        local size = 0
        for index, value in pairs(species_list) do
            if not integer(index, 1, #species_list) or not integer(value, 0, 255) then
                return nil, "invalid species-list byte or index"
            end
            size = size + 1
        end
        if size ~= #species_list then return nil, "missing species-list byte" end
        for index, mon in ipairs(result) do
            if species_list[index] ~= mon.species_index then return nil, "party species list differs" end
        end
        if species_list[#result + 1] ~= 255 then return nil, "party species terminator differs" end
    end
    return result
end

function M.prepareExchange(blobs, variant, slot, incoming, expected_key, incoming_key, evolved_species, boxed_keys)
    -- Raw keys are recipient-scoped. The coordinator proves separate admitted
    -- physical participants and logical link membership; this codec only checks
    -- local occupancy after removing the selected outgoing slot.
    if not key_set(boxed_keys) then return nil, "verified boxed inventory is required before trade preparation" end
    if type(expected_key) ~= "string" or type(incoming_key) ~= "string" then return nil, "both exact selected keys are required" end
    local party, err = M.validateParty(blobs, variant, nil, boxed_keys)
    if not party then return nil, err end
    if not integer(slot, 0, #party - 1) then return nil, "invalid selected slot" end
    local selected = party[slot + 1]
    if selected.key ~= expected_key or selected.hp == 0 then
        return nil, "selected Pokemon moved, changed identity or fainted"
    end
    local received, incoming_error = M.validateBlob(incoming, variant, incoming_key)
    if not received then return nil, incoming_error end
    if received.hp == 0 then return nil, "incoming linked Pokemon is fainted" end
    if not integer(evolved_species, 1, 190) or not Data.titles[variant].species[evolved_species] then
        return nil, "invalid predicted evolution species"
    end
    local allowed = evolved_species == received.species_index
    for _, target in ipairs(Data.titles[variant].species[received.species_index].evolution_targets) do
        if target == evolved_species then allowed = true end
    end
    if not allowed then return nil, "predicted evolution changes the canonical evolution target" end
    local predicted_key = received.key:sub(1, -3) .. string.format("%02X", evolved_species)
    local result = {}
    for index, mon in ipairs(party) do
        if index ~= slot + 1 then
            if mon.key == received.key or mon.key == predicted_key then return nil, "incoming or post-evolution key collision" end
            result[#result + 1] = mon.blob
        end
    end
    if boxed_keys and (boxed_keys[received.key] or boxed_keys[predicted_key]) then
        return nil, "incoming or post-evolution boxed key collision"
    end
    result[#result + 1] = received.blob
    return {blobs = result, predicted_key = predicted_key}
end

return M
